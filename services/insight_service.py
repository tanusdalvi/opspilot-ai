"""Deterministic insight engine for OpsPilot AI (Phase 3B).

Turns Phase 3A anomaly records into evidence-backed operational
explanations. Every explanation is a ranked list of numeric,
rule-derived factors — correlational evidence, never causal claims.
No LLM, no ML, no randomness, no wall-clock time.

Policies
--------
* **Determinism**: identical input always produces identical output.
  Iteration follows fixed orders (sorted metrics, ascending dates,
  input record order); grouping is a single greedy pass over the
  detector-ordered anomaly list; all sorts are stable.
* **Immutability**: caller DataFrames and anomaly records are never
  modified. All work happens on the normalized working copy from
  ``services.analytics_service._prepare_operational_data`` and freshly
  built output containers.
* **Input policy**: DataFrames follow the analytics/anomaly policy
  (must pass ``validate_dataframe``, at least one row). Anomaly lists
  are validated with ``summarize_anomalies`` conventions: list of
  dictionaries each containing ``type``/``scope``/``metric``/
  ``severity`` with a supported severity; violations raise
  ``DataValidationError``. Well-formed anomalies with unknown
  ``type``/``rule`` values are tolerated via generic fallbacks.
* **Numeric factor rules** (no subjective classification):
  - A supporting metric *aligns* on an anomaly date when its Phase 3A
    z-score exists (trailing ``MIN_HISTORY_DAYS`` observed points,
    candidate excluded), ``|z| >= FACTOR_Z_THRESHOLD`` and its sign
    matches the target metric's deviation direction.
  - Factor labels by aligned metric: ``units_sold`` → ``volume``,
    ``revenue`` → ``monetary``, ``cost`` → ``cost``,
    ``lead_time_days`` → ``supply``.
  - Revenue moves without aligned units → ``price_margin``
    (flatness-based strength).
  - No rule satisfied → single ``unattributed`` factor.
* **Localization** (daily scope): per-entity deviation against that
  entity's own previous ``MIN_HISTORY_DAYS`` observed values; signed
  share of total absolute deviation; top share >=
  ``LOCALIZED_SHARE_PCT`` is ``localized``, top-2 cumulative >=
  ``CONCENTRATED_CUMULATIVE_SHARE_PCT`` is ``concentrated``, else
  ``distributed``. The more concentrated dimension wins (tie:
  region). Contributor lists are capped at ``MAX_CONTRIBUTORS``.
* **Peer profile** (entity scope): full-period aggregates vs peer
  medians (anomaly entity excluded). Units ratio >=
  ``VOLUME_RATIO_THRESHOLD`` with cost ratio below threshold →
  ``volume_driven``; cost ratio >= threshold or lead-time gap >=
  ``LEAD_TIME_GAP_PCT_THRESHOLD`` → ``efficiency_driven``; else
  ``mixed``. Rules are evaluated in that fixed order.
* **Trend** (daily scope): trailing ``TREND_WINDOW_DAYS`` observed
  days before the candidate, split into halves; mean(last half) vs
  mean(first half) with the safe percentage-change convention;
  direction is ``rising``/``falling`` beyond ``TREND_FLAT_BAND_PCT``
  in absolute change, else ``flat``.
* **Correlations**: Pearson r between daily totals of metric pairs,
  requiring ``MIN_CORRELATION_POINTS`` observations; |r| bands map to
  ``strong``/``moderate``/``none``. Zero-variance series yield r=0.0.
* **Safe math**: zero denominators never divide; every derived number
  is finite and rounded to ``ROUNDING_DECIMALS`` only when placed
  into output. No NaN or infinity is ever emitted.
* **Grouping**: greedy, order-following assignment (see
  ``group_related_anomalies``); date window ``GROUP_DATE_WINDOW_DAYS``;
  compatibility = shared entity OR shared scope+metric (daily records
  have no entity and match on scope+metric); final ordering by
  severity priority, max score descending, earliest date, first
  member index.
"""

from __future__ import annotations

from datetime import date as _date

import numpy as np
import pandas as pd

from core.exceptions import DataValidationError
from services.analytics_service import (
    _prepare_operational_data,
    _round,
    _safe_pct_change,
)
from services.anomaly_service import (
    MIN_HISTORY_DAYS,
    SEVERITY_PRIORITY,
    SUPPORTED_METRICS,
    Z_SCORE_CAP,
    detect_anomalies,
    summarize_anomalies,
)

# --- Tuning constants --------------------------------------------------------

# Maximum calendar distance for two dated anomalies to be groupable.
GROUP_DATE_WINDOW_DAYS: int = 1

# Minimum |z| for a supporting metric to count as an aligned factor.
FACTOR_Z_THRESHOLD: float = 2.0

# Localization verdict thresholds (percent of total absolute deviation).
LOCALIZED_SHARE_PCT: float = 60.0
CONCENTRATED_CUMULATIVE_SHARE_PCT: float = 80.0

# Contributor lists never exceed this length.
MAX_CONTRIBUTORS: int = 3

# Peer-profile classification thresholds.
VOLUME_RATIO_THRESHOLD: float = 2.0
COST_RATIO_THRESHOLD: float = 2.0
LEAD_TIME_GAP_PCT_THRESHOLD: float = 25.0

# Trend context: trailing observed days before the candidate date.
TREND_WINDOW_DAYS: int = 14
TREND_FLAT_BAND_PCT: float = 2.0

# Correlation requirements and strength bands.
MIN_CORRELATION_POINTS: int = 8
CORRELATION_STRONG_R: float = 0.7
CORRELATION_MODERATE_R: float = 0.4

# Attached correlations per insight never exceed this length.
MAX_CORRELATIONS_PER_INSIGHT: int = 3

# Factor label for each supporting metric when it aligns.
FACTOR_LABELS: dict[str, str] = {
    "units_sold": "volume",
    "revenue": "monetary",
    "cost": "cost",
    "lead_time_days": "supply",
}

# Dimensions eligible for localization analysis, in tie-break order.
LOCALIZATION_DIMENSIONS: tuple[str, ...] = ("region", "product")


# --- Private helpers ---------------------------------------------------------


def _parse_iso_date(value: object) -> _date | None:
    """Parse an ISO ``YYYY-MM-DD`` anomaly date; ``None`` passes through."""
    if value is None:
        return None
    try:
        return _date.fromisoformat(str(value))
    except ValueError as exc:
        raise DataValidationError(
            f"Anomaly date {value!r} is not an ISO YYYY-MM-DD string"
        ) from exc


def _validate_anomaly_records(anomalies: object) -> None:
    """Structural validation reused from ``summarize_anomalies``."""
    summarize_anomalies(anomalies)  # type: ignore[arg-type]


def _metric_daily_series(work: pd.DataFrame, metric: str) -> pd.Series:
    """Sum ``metric`` per unique observed date, sorted ascending."""
    return work.groupby("date", sort=True)[metric].sum()


def _entity_daily_frame(
    work: pd.DataFrame, dimension: str, metric: str
) -> pd.DataFrame:
    """Per-entity daily totals: rows are observed dates, columns entities.

    Built from explicit per-(entity, date) sums so missing combinations
    stay absent instead of becoming zeros; consumers use each column's
    own observed index.
    """
    grouped = work.groupby([dimension, "date"], sort=True)[metric].sum()
    return grouped.unstack(level=0)


def _correlation_strength(r: float) -> str:
    """Map an |r| value onto the fixed strength bands."""
    magnitude = abs(r)
    if magnitude >= CORRELATION_STRONG_R:
        return "strong"
    if magnitude >= CORRELATION_MODERATE_R:
        return "moderate"
    return "none"


class _ContextTables:
    """Precomputed per-dataset tables shared by all insight builders.

    Holding these once keeps ``explain_anomalies`` linear in the number
    of anomalies instead of recomputing dataset-wide statistics per
    record. All stored values keep full precision; rounding happens at
    output assembly time only.
    """

    def __init__(self, work: pd.DataFrame) -> None:
        self.metrics: list[str] = sorted(SUPPORTED_METRICS)
        self.daily: dict[str, pd.Series] = {
            metric: _metric_daily_series(work, metric) for metric in self.metrics
        }
        first = self.daily[self.metrics[0]]
        self.dates: list[pd.Timestamp] = list(first.index)
        self.date_positions: dict[str, int] = {
            stamp.strftime("%Y-%m-%d"): position
            for position, stamp in enumerate(self.dates)
        }

        # Raw (unrounded) Phase 3A-convention z-scores per date/metric.
        self.z_raw: dict[str, dict[str, float | None]] = {}
        for position in range(MIN_HISTORY_DAYS, len(self.dates)):
            row: dict[str, float | None] = {}
            for metric in self.metrics:
                series = self.daily[metric]
                window = series.iloc[position - MIN_HISTORY_DAYS : position].to_numpy(
                    dtype=float
                )
                std = float(np.std(window, ddof=1))
                if std == 0.0:
                    row[metric] = None
                    continue
                value = float(series.iloc[position])
                row[metric] = (value - float(np.mean(window))) / std
            self.z_raw[self.dates[position].strftime("%Y-%m-%d")] = row

        self.correlations: list[dict[str, object]] = []
        for index, metric_a in enumerate(self.metrics):
            for metric_b in self.metrics[index + 1 :]:
                a = self.daily[metric_a].to_numpy(dtype=float)
                b = self.daily[metric_b].to_numpy(dtype=float)
                if len(a) < MIN_CORRELATION_POINTS:
                    continue
                if float(np.std(a)) == 0.0 or float(np.std(b)) == 0.0:
                    r = 0.0
                else:
                    r = float(np.corrcoef(a, b)[0, 1])
                self.correlations.append(
                    {
                        "metric_a": metric_a,
                        "metric_b": metric_b,
                        "r": _round(r),
                        "strength": _correlation_strength(r),
                        "points": int(len(a)),
                    }
                )

        # Per-entity daily frames used by localization analysis.
        self.entity_daily: dict[tuple[str, str], pd.DataFrame] = {
            (dimension, metric): _entity_daily_frame(work, dimension, metric)
            for dimension in LOCALIZATION_DIMENSIONS
            for metric in self.metrics
        }

        # Localization lookup structures derived from ``entity_daily`` so
        # ``_localization_for`` never re-parses dates or re-drops nulls
        # per anomaly. For each (dimension, metric): an ISO-date ->
        # frame-position map, plus one entry per entity (visited in the
        # same sorted-by-name order as the original per-anomaly loop)
        # carrying the entity's observed (non-null) values as a float
        # array and an ISO-date -> observed-position map. Built once per
        # analysis context; nothing here outlives the tables instance.
        self.localization_index: dict[
            tuple[str, str],
            tuple[dict[str, int], list[tuple[str, "np.ndarray", dict[str, int]]]],
        ] = {}
        for dimension in LOCALIZATION_DIMENSIONS:
            for metric in self.metrics:
                frame = self.entity_daily[(dimension, metric)]
                frame_positions = {
                    stamp.strftime("%Y-%m-%d"): position
                    for position, stamp in enumerate(frame.index)
                }
                entities: list[tuple[str, np.ndarray, dict[str, int]]] = []
                for entity in sorted(map(str, frame.columns)):
                    observed = frame[entity].dropna()
                    entities.append(
                        (
                            entity,
                            observed.to_numpy(dtype=float),
                            {
                                stamp.strftime("%Y-%m-%d"): observed_position
                                for observed_position, stamp in enumerate(observed.index)
                            },
                        )
                    )
                self.localization_index[(dimension, metric)] = (
                    frame_positions,
                    entities,
                )

        # Full-period per-entity aggregates used by peer profiling.
        self.entity_aggregates: dict[str, pd.DataFrame] = {}
        for dimension in LOCALIZATION_DIMENSIONS:
            frame = work.groupby(dimension, sort=True).agg(
                units_sold=("units_sold", "sum"),
                revenue=("revenue", "sum"),
                cost=("cost", "sum"),
                average_lead_time_days=("lead_time_days", "mean"),
            )
            frame["profit"] = frame["revenue"] - frame["cost"]
            frame["profit_margin_pct"] = [
                _round(
                    (profit / revenue * 100.0) if revenue != 0 else 0.0
                )
                for profit, revenue in zip(frame["profit"], frame["revenue"], strict=True)
            ]
            self.entity_aggregates[dimension] = frame


def _analyze_contexts_output(tables: _ContextTables) -> dict[str, object]:
    """Public presentation view of the precomputed context tables."""
    z_scores_by_date: dict[str, dict[str, float | None]] = {}
    for iso_date in sorted(tables.z_raw):
        row = tables.z_raw[iso_date]
        z_scores_by_date[iso_date] = {
            metric: (None if row[metric] is None else _round(row[metric]))
            for metric in tables.metrics
        }
    daily_totals = {
        metric: [_round(value) for value in tables.daily[metric].to_numpy(dtype=float)]
        for metric in tables.metrics
    }
    correlations = sorted(
        tables.correlations,
        key=lambda item: (str(item["metric_a"]), str(item["metric_b"])),
    )
    return {
        "dates": [stamp.strftime("%Y-%m-%d") for stamp in tables.dates],
        "daily_totals": daily_totals,
        "z_scores_by_date": z_scores_by_date,
        "correlations": [dict(item) for item in correlations],
    }


def analyze_metric_contexts(df: pd.DataFrame) -> dict[str, object]:
    """Compute dataset-wide context foundations once.

    Builds the daily-total series per supported metric, Phase 3A-
    convention z-scores for every candidate date (trailing
    ``MIN_HISTORY_DAYS`` observed points, candidate excluded, no
    calendar filling; unavailable scores are ``None``), and pairwise
    Pearson correlations between metric daily totals.

    Args:
        df: Operational DataFrame following the canonical schema. It is
            never mutated.

    Returns:
        Dictionary with exactly ``dates`` (ISO strings ascending),
        ``daily_totals`` (metric -> rounded values aligned with
        ``dates``), ``z_scores_by_date`` (ISO date -> metric ->
        rounded z or ``None``, dates ascending), and ``correlations``
        (list of ``metric_a``/``metric_b``/``r``/``strength``/
        ``points``, sorted by metric names).

    Raises:
        DataValidationError: If the dataset is unusable (see module
            policy).
    """
    tables = _ContextTables(_prepare_operational_data(df))
    return _analyze_contexts_output(tables)


def _localization_for(
    tables: _ContextTables,
    metric: str,
    iso_date: str,
    direction: int,
) -> dict[str, object] | None:
    """Signed contribution shares across both dimensions for one day.

    Returns the winning dimension's localization block (more
    concentrated dimension wins; tie goes to ``region``) or ``None``
    when no dimension yields a usable contributor pool. Entities need
    their own ``MIN_HISTORY_DAYS`` prior observed values to participate.

    All date/entity positions come from the precomputed
    ``tables.localization_index``; this function performs dictionary
    lookups and numpy slicing only, so per-anomaly cost is independent
    of dataset length.
    """
    position = tables.date_positions.get(iso_date)
    if position is None or position < MIN_HISTORY_DAYS:
        return None
    if direction not in (-1, 1):
        direction = 1 if direction >= 0 else -1

    best: tuple[float, int, dict[str, object]] | None = None

    for dimension in LOCALIZATION_DIMENSIONS:
        entry = tables.localization_index[(dimension, metric)]
        frame_positions, entities = entry
        if iso_date not in frame_positions:
            continue
        contributions: list[tuple[str, float]] = []
        for entity, values, observed_positions in entities:
            entity_position = observed_positions.get(iso_date)
            if entity_position is None or entity_position < MIN_HISTORY_DAYS:
                continue
            window = values[entity_position - MIN_HISTORY_DAYS : entity_position]
            deviation = float(values[entity_position]) - float(np.mean(window))
            contributions.append((entity, deviation))

        deviations = [deviation for _, deviation in contributions]
        total_abs = sum(abs(deviation) for deviation in deviations)
        if total_abs == 0.0 or len(contributions) < 2:
            continue

        same_direction_total = sum(
            deviation * direction for deviation in deviations if deviation * direction > 0
        )
        contributors_all: list[dict[str, object]] = []
        for entity, deviation in sorted(
            contributions, key=lambda item: (-abs(item[1]), item[0])
        ):
            share_pct = deviation / total_abs * 100.0
            contributors_all.append(
                {
                    "scope": dimension,
                    "entity": entity,
                    "share_pct": _round(share_pct),
                    "directional_share_pct": (
                        _round(deviation * direction / same_direction_total * 100.0)
                        if same_direction_total > 0
                        else 0.0
                    ),
                }
            )

        top_abs = abs(contributors_all[0]["share_pct"])
        cumulative_two = sum(
            abs(contributors_all[index]["share_pct"])
            for index in range(min(2, len(contributors_all)))
        )
        if top_abs >= LOCALIZED_SHARE_PCT:
            verdict = "localized"
        elif cumulative_two >= CONCENTRATED_CUMULATIVE_SHARE_PCT:
            verdict = "concentrated"
        else:
            verdict = "distributed"

        block = {
            "dimension": dimension,
            "verdict": verdict,
            "contributors": [
                {key: item[key] for key in ("entity", "share_pct")}
                for item in contributors_all[:MAX_CONTRIBUTORS]
            ],
        }
        rank_key = (-top_abs, LOCALIZATION_DIMENSIONS.index(dimension))
        if best is None or rank_key < (-best[0], best[1]):
            best = (top_abs, LOCALIZATION_DIMENSIONS.index(dimension), block)

    return None if best is None else best[2]


def _peer_profile(
    tables: _ContextTables, dimension: str, entity: str, metric: str
) -> dict[str, object] | None:
    """Compare one outlier entity against its same-dimension peers."""
    frame = tables.entity_aggregates.get(dimension)
    if frame is None or entity not in frame.index or len(frame) < 2:
        return None
    peers = frame.drop(index=entity)

    def median(column: str) -> float | None:
        values = peers[column].to_numpy(dtype=float)
        return float(np.median(values))

    medians = {column: median(column) for column in (
        metric,
        "units_sold",
        "cost",
        "average_lead_time_days",
        "profit_margin_pct",
    )}
    own = {column: float(frame.loc[entity, column]) for column in medians}

    def ratio(column: str) -> float | None:
        base = medians[column]
        if base is None or base == 0:
            return None
        return _round(own[column] / base)

    metric_ratio = ratio(metric)
    units_ratio = ratio("units_sold")
    cost_ratio = ratio("cost")

    lead_median = medians["average_lead_time_days"]
    lead_gap = (
        None
        if lead_median is None or lead_median == 0
        else _safe_pct_change(own["average_lead_time_days"], lead_median)
    )
    margin_median = medians["profit_margin_pct"]
    margin_gap = (
        None if margin_median is None else _round(own["profit_margin_pct"] - margin_median)
    )

    ratios_present = [
        value
        for value in (metric_ratio, units_ratio, cost_ratio)
        if value is not None
    ]
    if not ratios_present:
        profile = None
    elif (
        units_ratio is not None
        and units_ratio >= VOLUME_RATIO_THRESHOLD
        and (cost_ratio is None or cost_ratio < COST_RATIO_THRESHOLD)
    ):
        profile = "volume_driven"
    elif (
        (cost_ratio is not None and cost_ratio >= COST_RATIO_THRESHOLD)
        or (lead_gap is not None and abs(lead_gap) >= LEAD_TIME_GAP_PCT_THRESHOLD)
    ):
        profile = "efficiency_driven"
    else:
        profile = "mixed"

    if profile is None:
        return None

    return {
        "profile": profile,
        "ratios": {
            "metric_vs_peer_median": metric_ratio,
            "units_vs_peer_median": units_ratio,
            "cost_vs_peer_median": cost_ratio,
        },
        "gaps_pct": {
            "average_lead_time_days": lead_gap,
            "profit_margin_pct_points": margin_gap,
        },
    }


def _trend_for(
    tables: _ContextTables, metric: str, iso_date: str
) -> dict[str, object] | None:
    """Two-mean trend over the trailing observed days before a date."""
    position = tables.date_positions.get(iso_date)
    if position is None or position < TREND_WINDOW_DAYS:
        return None
    series = tables.daily[metric]
    window = series.iloc[position - TREND_WINDOW_DAYS : position].to_numpy(dtype=float)
    split = TREND_WINDOW_DAYS // 2
    earlier = float(np.mean(window[:split]))
    later = float(np.mean(window[split:]))
    change_pct = _safe_pct_change(later, earlier)
    if change_pct > TREND_FLAT_BAND_PCT:
        direction = "rising"
    elif change_pct < -TREND_FLAT_BAND_PCT:
        direction = "falling"
    else:
        direction = "flat"
    return {"direction": direction, "change_pct": _round(change_pct)}


def _factors_for(
    tables: _ContextTables,
    record: dict[str, object],
    direction: int,
) -> list[dict[str, object]]:
    """Ranked numeric factor votes for a daily-scope anomaly."""
    iso_date = record.get("date")
    metric = str(record.get("metric"))
    z_row = tables.z_raw.get(str(iso_date)) if iso_date is not None else None
    factors: list[dict[str, object]] = []

    if z_row is not None:
        for supporting in tables.metrics:
            if supporting == metric:
                continue
            z_value = z_row.get(supporting)
            if z_value is None or abs(z_value) < FACTOR_Z_THRESHOLD:
                continue
            if (z_value > 0) != (direction > 0):
                continue
            factors.append(
                {
                    "factor": FACTOR_LABELS[supporting],
                    "direction": "increase" if direction > 0 else "decrease",
                    "strength": _round(min(1.0, abs(z_value) / Z_SCORE_CAP)),
                    "evidence": f"{supporting} z={_round(z_value)} on {iso_date}",
                }
            )

        if metric == "revenue":
            units_z = z_row.get("units_sold")
            if units_z is not None and abs(units_z) < FACTOR_Z_THRESHOLD:
                flatness = 1.0 - abs(units_z) / FACTOR_Z_THRESHOLD
                factors.append(
                    {
                        "factor": "price_margin",
                        "direction": "increase" if direction > 0 else "decrease",
                        "strength": _round(max(0.0, min(1.0, flatness))),
                        "evidence": (
                            f"units_sold z={_round(units_z)} below +/-{FACTOR_Z_THRESHOLD} "
                            f"while revenue moved on {iso_date}"
                        ),
                    }
                )

    if not factors:
        factors.append(
            {
                "factor": "unattributed",
                "direction": "none",
                "strength": 0.0,
                "evidence": "no metric satisfied alignment rules on this date",
            }
        )

    factors.sort(key=lambda item: (-float(item["strength"]), str(item["factor"])))
    return factors


def _correlations_for(tables: _ContextTables, metric: str) -> list[dict[str, object]]:
    """Bounded, strongest-first correlation evidence involving ``metric``."""
    relevant = [
        item
        for item in tables.correlations
        if metric in (item["metric_a"], item["metric_b"])
        and item["strength"] in ("strong", "moderate")
    ]
    relevant.sort(
        key=lambda item: (-abs(float(item["r"])), str(item["metric_a"]), str(item["metric_b"]))
    )
    trimmed = [
        {
            "pair": [str(item["metric_a"]), str(item["metric_b"])],
            "r": item["r"],
            "strength": item["strength"],
        }
        for item in relevant[:MAX_CORRELATIONS_PER_INSIGHT]
    ]
    return trimmed


def _related_indices(
    anomalies: list[dict[str, object]], index: int
) -> list[int]:
    """Indices of other records sharing entity or scope+metric within window."""
    target = anomalies[index]
    target_date = _parse_iso_date(target.get("date"))
    related: list[int] = []
    for other_index, other in enumerate(anomalies):
        if other_index == index:
            continue
        link_compatible = (
            (
                target.get("entity") is not None
                and other.get("entity") == target.get("entity")
            )
            or (other.get("scope"), other.get("metric"))
            == (target.get("scope"), target.get("metric"))
        )
        if not link_compatible:
            continue
        other_date = _parse_iso_date(other.get("date"))
        if target_date is None or other_date is None:
            date_compatible = True
        else:
            distance = abs((target_date - other_date).days)
            date_compatible = distance <= GROUP_DATE_WINDOW_DAYS
        if date_compatible:
            related.append(other_index)
    return related


def _headline_for(record: dict[str, object], insight_facts: dict[str, object]) -> str:
    """Deterministic template headline assembled from computed facts."""
    scope = str(record.get("scope"))
    metric = str(record.get("metric"))

    if scope == "daily":
        direction_word = "spike" if insight_facts["direction"] > 0 else "drop"
        parts = [
            f"Daily {metric} {direction_word} on {record.get('date')} "
            f"({float(record.get('deviation_pct', 0.0)):+.2f}% vs expected)"
        ]
        factors = insight_facts["factors"]
        primary = factors[0]["factor"] if factors else "unattributed"
        parts.append(f"primary factor {primary}")
        localization = insight_facts["localization"]
        if localization is not None:
            contributors = localization["contributors"]
            if contributors:
                lead = contributors[0]
                parts.append(
                    f"{localization['verdict']} in {localization['dimension']} "
                    f"{lead['entity']} ({float(lead['share_pct']):.2f}% of excess)"
                    if localization["verdict"] == "localized"
                    else f"{localization['verdict']} across {localization['dimension']}s"
                )
        trend = insight_facts["trend"]
        if trend is not None:
            parts.append(f"preceded by {trend['direction']} trend ({trend['change_pct']:+.2f}%)")
        return "; ".join(parts) + "."

    if scope in LOCALIZATION_DIMENSIONS:
        outlier_kind = "high" if "high" in str(record.get("type")) else "low"
        profile_block = insight_facts["peer_profile"]
        if profile_block is not None:
            ratio_value = profile_block["ratios"]["metric_vs_peer_median"]
            ratio_text = f"{float(ratio_value):.2f}x" if ratio_value is not None else "n/a"
            return (
                f"{scope.capitalize()} {record.get('entity')} is a {metric} "
                f"{outlier_kind} outlier: {ratio_text} peer median; "
                f"profile {profile_block['profile']}."
            )
        return (
            f"{scope.capitalize()} {record.get('entity')} is a {metric} "
            f"{outlier_kind} outlier; peer comparison unavailable."
        )

    return f"Anomaly recorded for {metric} (scope {scope}); no specific explanation rules apply."


def explain_anomalies(
    df: pd.DataFrame, anomalies: list[dict[str, object]]
) -> dict[str, object]:
    """Explain already-computed anomaly records without re-running detection.

    Each anomaly receives one insight built from deterministic,
    numeric rules: metric alignment votes, contribution localization
    (daily scope), peer profiling (entity scope), trend context, and
    cross-metric correlations. Uniform evidence depth applies to every
    severity; only structural limits (contributor/correlation caps)
    bound the output.

    Args:
        df: Operational DataFrame following the canonical schema. It is
            never mutated.
        anomalies: Anomaly dictionaries in any order; each must satisfy
            the structural contract enforced by ``summarize_anomalies``.
            The list and its records are never modified.

    Returns:
        Dictionary with exactly ``insights``: one record per input
        anomaly, in input order, each carrying ``type``,
        ``anomaly_index``, ``scope``, ``metric``, ``entity``, ``date``,
        ``severity``, ``headline``, ``factors``, ``localization``,
        ``peer_profile``, ``trend``, ``correlations``, and
        ``related_anomaly_indices``.

    Raises:
        DataValidationError: If the dataset is unusable or any anomaly
            record violates the structural contract.
    """
    _validate_anomaly_records(anomalies)
    tables = _ContextTables(_prepare_operational_data(df))

    insights: list[dict[str, object]] = []
    for index, record in enumerate(anomalies):
        scope = str(record.get("scope"))
        metric = str(record.get("metric"))
        iso_date = record.get("date")
        deviation_pct = float(record.get("deviation_pct", 0.0))  # type: ignore[arg-type]
        direction = 1 if deviation_pct >= 0 else -1

        factors: list[dict[str, object]] = []
        localization: dict[str, object] | None = None
        peer_profile: dict[str, object] | None = None
        trend: dict[str, object] | None = None

        if scope == "daily":
            factors = _factors_for(tables, record, direction)
            if isinstance(iso_date, str):
                localization = _localization_for(tables, metric, iso_date, direction)
                trend = _trend_for(tables, metric, iso_date)
        elif scope in LOCALIZATION_DIMENSIONS:
            peer_profile = _peer_profile(
                tables, scope, str(record.get("entity")), metric
            )

        facts = {
            "direction": direction,
            "factors": factors,
            "localization": localization,
            "peer_profile": peer_profile,
            "trend": trend,
        }
        insights.append(
            {
                "type": "insight",
                "anomaly_index": index,
                "scope": scope,
                "metric": metric,
                "entity": record.get("entity"),
                "date": iso_date,
                "severity": record.get("severity"),
                "headline": _headline_for(record, facts),
                "factors": factors,
                "localization": localization,
                "peer_profile": peer_profile,
                "trend": trend,
                "correlations": _correlations_for(tables, metric),
                "related_anomaly_indices": _related_indices(anomalies, index),
            }
        )

    return {"insights": insights}


def group_related_anomalies(
    anomalies: list[dict[str, object]],
) -> dict[str, object]:
    """Group simultaneous anomalies with a greedy single-pass algorithm.

    Records are visited in input order (the natural order is the
    severity-first ordering emitted by ``detect_anomalies``). A record
    joins the most recently created compatible group, or opens a new
    one. Compatibility requires BOTH:

    * *link*: shared non-null ``entity`` OR identical
      ``scope``+``metric`` (daily records carry no entity and match on
      scope+metric), AND
    * *date*: either record is undated (period-level entity records)
      or the calendar distance between dated members is at most
      ``GROUP_DATE_WINDOW_DAYS``.

    Final groups are ordered deterministically by highest member
    severity priority, max score descending, earliest date ascending,
    then first member index; ``group_id`` values are assigned 1-based
    after this ordering.

    Args:
        anomalies: Anomaly dictionaries satisfying the structural
            contract; never modified.

    Returns:
        Dictionary with exactly ``groups`` and ``ungrouped_count``
        (number of singleton groups). Each group carries ``group_id``,
        ``severity``, ``max_score``, ``start_date``, ``end_date``,
        ``member_indices``, ``member_count``, ``shared_metrics``,
        ``shared_entities``, and a templated ``headline``.

    Raises:
        DataValidationError: If any anomaly record violates the
            structural contract or carries an unparseable date.
    """
    _validate_anomaly_records(anomalies)

    parsed: list[tuple[int, dict[str, object], _date | None]] = [
        (index, record, _parse_iso_date(record.get("date")))
        for index, record in enumerate(anomalies)
    ]

    groups: list[dict[str, object]] = []
    for index, record, parsed_date in parsed:
        entity = record.get("entity")
        link = (str(record.get("scope")), str(record.get("metric")))

        target_group: dict[str, object] | None = None
        for candidate in reversed(groups):
            dated = [d for d in candidate["dates"] if d is not None]  # type: ignore[union-attr]
            if parsed_date is not None and dated:
                distance = min(abs((parsed_date - other).days) for other in dated)
                if distance > GROUP_DATE_WINDOW_DAYS:
                    continue
            entities_match = entity is not None and entity in candidate["entities"]  # type: ignore[operator]
            pair_match = link in candidate["links"]  # type: ignore[operator]
            if entities_match or pair_match:
                target_group = candidate
                break

        if target_group is None:
            target_group = {
                "members": [],
                "dates": [],
                "entities": set(),
                "links": set(),
            }
            groups.append(target_group)

        target_group["members"].append(index)  # type: ignore[union-attr]
        target_group["dates"].append(parsed_date)  # type: ignore[union-attr]
        if entity is not None:
            target_group["entities"].add(entity)  # type: ignore[union-attr]
        target_group["links"].add(link)  # type: ignore[union-attr]

    built_groups: list[dict[str, object]] = []
    for group in groups:
        members: list[int] = group["members"]  # type: ignore[assignment]
        records = [anomalies[position] for position in members]
        severities = [str(record.get("severity")) for record in records]
        severity = min(severities, key=lambda name: SEVERITY_PRIORITY.get(name, len(SEVERITY_PRIORITY)))
        max_score = max(float(record.get("score", 0.0)) for record in records)  # type: ignore[arg-type]
        dated = [parsed_date for parsed_date in group["dates"] if parsed_date is not None]  # type: ignore[union-attr]
        start_date = min(dated).strftime("%Y-%m-%d") if dated else None
        end_date = max(dated).strftime("%Y-%m-%d") if dated else None
        shared_metrics = sorted({str(record.get("metric")) for record in records})
        shared_entities = sorted({str(entity) for entity in group["entities"]})  # type: ignore[arg-type]

        severity_counts = sorted(
            {
                (SEVERITY_PRIORITY.get(name, len(SEVERITY_PRIORITY)), name)
                for name in set(severities)
            }
        )
        severity_text = ", ".join(f"{name}={severities.count(name)}" for _, name in severity_counts)
        if start_date is None:
            span_text = "across the full period"
        elif start_date == end_date:
            span_text = f"around {start_date}"
        else:
            span_text = f"between {start_date} and {end_date}"
        headline = (
            f"Cluster of {len(members)} anomalies ({severity_text}) {span_text}; "
            f"metrics: {', '.join(shared_metrics)}; "
            f"entities: {', '.join(shared_entities) if shared_entities else 'dataset-wide'}."
        )

        built_groups.append(
            {
                "group_id": 0,
                "severity": severity,
                "max_score": _round(max_score),
                "start_date": start_date,
                "end_date": end_date,
                "member_indices": list(members),
                "member_count": len(members),
                "shared_metrics": shared_metrics,
                "shared_entities": shared_entities,
                "headline": headline,
            }
        )

    built_groups.sort(
        key=lambda group: (
            SEVERITY_PRIORITY.get(str(group["severity"]), len(SEVERITY_PRIORITY)),
            -float(group["max_score"]),
            str(group["start_date"] or ""),
            int(group["member_indices"][0]),
        )
    )
    for assigned_id, group in enumerate(built_groups, start=1):
        group["group_id"] = assigned_id

    ungrouped_count = sum(1 for group in built_groups if group["member_count"] == 1)
    return {"groups": built_groups, "ungrouped_count": ungrouped_count}


def build_insight_report(
    df: pd.DataFrame, *, sensitivity: str = "medium"
) -> dict[str, object]:
    """Run detection and produce the complete insight report.

    Orchestrates ``detect_anomalies`` (Phase 3A), explains every
    returned record via ``explain_anomalies``, groups them via
    ``group_related_anomalies``, and attaches the aggregate summary.

    Args:
        df: Operational DataFrame following the canonical schema. It is
            never mutated.
        sensitivity: Passed through to every underlying detector;
            validated up front by the shared validation logic.

    Returns:
        Dictionary with exactly ``summary`` (the ``summarize_anomalies``
        result for the detected records), ``insights``,
        ``groups``, and ``parameters`` containing ``sensitivity`` and
        ``metrics`` (supported metrics in deterministic sorted order).

    Raises:
        DataValidationError: If the dataset is unusable or
            ``sensitivity`` is invalid.
    """
    detection = detect_anomalies(df, sensitivity=sensitivity)
    anomalies = detection["anomalies"]
    return {
        "summary": summarize_anomalies(anomalies),
        "insights": explain_anomalies(df, anomalies)["insights"],
        "groups": group_related_anomalies(anomalies),
        "parameters": {
            "sensitivity": sensitivity,
            "metrics": sorted(SUPPORTED_METRICS),
        },
    }
