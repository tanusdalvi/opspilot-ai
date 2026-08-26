"""Operational Finding compression service.

Transforms raw anomalies into a small set of meaningful *Operational
Findings* — the product-level concept the UI centers on.  Instead of
showing 40+ individual anomalies, the user sees 3–5 prioritised business
problems, each with a severity, affected metric/entity, time window,
human-readable summary, and the count of supporting signals.

Compression strategy:

1. **Metric-first bucketing** — all anomalies sharing the same metric
   are placed into one candidate bucket.
2. **Direction split** — within a metric bucket, spikes and drops are
   separated (a revenue spike is a different business problem than a
   revenue drop).
3. **Entity sub-grouping** — entity-level outliers (region/product) are
   grouped per entity; daily anomalies with the same entity are also
   grouped together.
4. **Temporal sub-bucketing** — daily anomalies whose dates are within
   ``FINDING_DATE_WINDOW_DAYS`` of each other are merged into one
   episode.
5. **Scoring & ranking** — each candidate is scored by a deterministic
   composite formula (severity weight × deviation magnitude ×
   observation density) and banded into CRITICAL / HIGH / MEDIUM / LOW.
6. **Headline generation** — a one-sentence, human-readable summary is
   templated per finding from the constituent signals.
"""

from __future__ import annotations

from datetime import date

from core.constants import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
)
from core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FINDING_DATE_WINDOW_DAYS: int = 14
"""Anomalies within this many days of each other on the same metric and
direction are considered part of the same operational episode."""

_SEVERITY_WEIGHT: dict[str, float] = {
    SEVERITY_CRITICAL: 4.0,
    SEVERITY_HIGH: 3.0,
    SEVERITY_MEDIUM: 2.0,
    SEVERITY_LOW: 1.0,
}

# Composite scoring weights
_W_SEVERITY: float = 0.50
_W_DEVIATION: float = 0.30
_W_DENSITY: float = 0.20

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_date(value: object) -> date | None:
    """Best-effort ISO date parser (returns *date*, not *datetime*)."""
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _severity_weight(severity: object) -> float:
    return _SEVERITY_WEIGHT.get(str(severity).upper(), 1.0)


def _is_spike(anomaly: dict) -> bool:
    """Return True if the anomaly represents a spike (value above expected)."""
    atype = str(anomaly.get("type", ""))
    if "spike" in atype or "high" in atype:
        return True
    dev = anomaly.get("deviation_pct")
    if isinstance(dev, (int, float)):
        return dev > 0
    return False


def _direction_key(anomaly: dict) -> str:
    return "spike" if _is_spike(anomaly) else "drop"


def _entity_key(anomaly: dict) -> str:
    """Return the entity string, or '__none__' for dataset-wide anomalies."""
    entity = anomaly.get("entity")
    return str(entity) if entity else "__none__"


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------


def _build_buckets(
    anomalies: list[dict],
) -> dict[str, dict[str, list[tuple[int, dict]]]]:
    """Build a nested bucket structure: metric → direction → [(original_idx, anomaly)].

    The original index is the position in the caller-provided anomaly list,
    which is preserved through to ``anomaly_indices`` in the output.
    """
    buckets: dict[str, dict[str, list[tuple[int, dict]]]] = {}
    for idx, anomaly in enumerate(anomalies):
        metric = str(anomaly.get("metric", "unknown"))
        direction = _direction_key(anomaly)
        buckets.setdefault(metric, {}).setdefault(direction, []).append(
            (idx, anomaly)
        )
    return buckets


def _temporal_sub_bucket(
    items: list[tuple[int, dict]],
) -> list[list[tuple[int, dict]]]:
    """Split items into temporal groups based on date proximity.

    Anomalies within ``FINDING_DATE_WINDOW_DAYS`` of each other belong
    to the same temporal group.  Items with no date (entity outliers) are
    placed in their own catch-all group.
    """
    with_date: list[tuple[int, dict]] = []
    no_date: list[tuple[int, dict]] = []

    for idx, anomaly in items:
        if _parse_date(anomaly.get("date")) is not None:
            with_date.append((idx, anomaly))
        else:
            no_date.append((idx, anomaly))

    # Sort dated items by date ascending for stable grouping
    with_date.sort(key=lambda t: str(t[1].get("date", "")))

    groups: list[list[tuple[int, dict]]] = []

    # Greedy temporal sub-bucketing
    for idx, anomaly in with_date:
        a_date = _parse_date(anomaly.get("date"))
        placed = False
        for group in groups:
            group_dates = [_parse_date(a.get("date")) for _, a in group]
            if a_date is not None and any(
                d is not None
                and abs((a_date - d).days) <= FINDING_DATE_WINDOW_DAYS
                for d in group_dates
            ):
                group.append((idx, anomaly))
                placed = True
                break
        if not placed:
            groups.append([(idx, anomaly)])

    # Undated anomalies go into their own groups (one per unique entity)
    if no_date:
        by_entity: dict[str, list[tuple[int, dict]]] = {}
        for idx, anomaly in no_date:
            entity = str(anomaly.get("entity") or "unknown")
            by_entity.setdefault(entity, []).append((idx, anomaly))
        for entity_items in by_entity.values():
            groups.append(entity_items)

    return groups


# ---------------------------------------------------------------------------
# Finding merge
# ---------------------------------------------------------------------------


def _compute_finding_severity(
    worst_severity: str,
    max_deviation: float,
    observation_count: int,
) -> str:
    """Derive finding severity from worst anomaly, deviation, and count.

    The composite score determines the final severity band.  The worst
    anomaly severity sets the baseline; higher deviation and more
    observations push the score upward.
    """
    sev_w = _severity_weight(worst_severity)
    dev_norm = min(max_deviation / 50.0, 1.0)
    count_norm = min(observation_count / 10.0, 1.0)

    raw = _W_SEVERITY * (sev_w / 4.0) + _W_DEVIATION * dev_norm + _W_DENSITY * count_norm
    score = round(raw * 100, 1)

    if score >= 75:
        return SEVERITY_CRITICAL
    if score >= 55:
        return SEVERITY_HIGH
    if score >= 35:
        return SEVERITY_MEDIUM
    return SEVERITY_LOW


def _merge_group(
    anomalies: list[dict],
    original_indices: list[int],
) -> dict | None:
    """Merge a group of anomalies into a single finding dict.

    Returns ``None`` when the input is empty.
    """
    if not anomalies:
        return None

    metric = str(anomalies[0].get("metric", "unknown"))
    severities = [str(a.get("severity", "LOW")).upper() for a in anomalies]
    worst_severity = max(severities, key=lambda s: _SEVERITY_WEIGHT.get(s, 1.0))

    deviations = [
        abs(float(a.get("deviation_pct", 0)))
        for a in anomalies
        if isinstance(a.get("deviation_pct"), (int, float))
    ]
    max_dev = max(deviations) if deviations else 0.0
    avg_dev = sum(deviations) / len(deviations) if deviations else 0.0

    values = [
        float(a.get("value", 0))
        for a in anomalies
        if isinstance(a.get("value"), (int, float))
    ]
    expected_values = [
        float(a.get("expected_value", 0))
        for a in anomalies
        if isinstance(a.get("expected_value"), (int, float))
    ]

    dates = [_parse_date(a.get("date")) for a in anomalies]
    valid_dates = [d for d in dates if d is not None]
    entities = sorted({str(a.get("entity")) for a in anomalies if a.get("entity")})
    scopes = sorted({str(a.get("scope")) for a in anomalies if a.get("scope")})
    scores_list = [float(a.get("score", 0)) for a in anomalies]

    # Determine direction from majority of anomalies
    spike_count = sum(1 for a in anomalies if _is_spike(a))
    direction = "spike" if spike_count > len(anomalies) / 2 else "drop"

    finding_severity = _compute_finding_severity(
        worst_severity, max_dev, len(anomalies)
    )

    start_date = min(valid_dates).isoformat() if valid_dates else None
    end_date = max(valid_dates).isoformat() if valid_dates else None

    # Observed and expected values
    observed_value = round(sum(values), 2) if values else 0.0
    expected_value = round(sum(expected_values), 2) if expected_values else 0.0

    # Overall deviation: percentage difference between summed observed and expected
    if expected_value != 0:
        deviation_pct = round(
            (observed_value - expected_value) / expected_value * 100.0, 1
        )
    else:
        deviation_pct = round(avg_dev, 1)

    # Headline
    from agent.recommendation_playbooks import metric_label as _metric_label

    metric_label_text = _metric_label(metric)

    if start_date and end_date and start_date != end_date:
        period = f"{start_date} to {end_date}"
    elif start_date:
        period = start_date
    else:
        period = "the analysis period"

    entity_text = ""
    if len(entities) == 1:
        entity_text = f" in {entities[0]}"
    elif len(entities) > 1:
        entity_text = f" across {len(entities)} entities"

    direction_label = "increase" if direction == "spike" else "decrease"
    headline = (
        f"Sustained {direction_label} in {metric_label_text}"
        f"{entity_text} ({period})"
    )

    # One-sentence explanation
    count = len(anomalies)
    if count == 1:
        explanation = (
            f"Single anomalous {direction_label} of {metric_label_text}"
            f" detected{entity_text} on {period} "
            f"({abs(deviation_pct):.1f}% from expected)."
        )
    else:
        explanation = (
            f"{count} related anomalies show a consistent {direction_label}"
            f" in {metric_label_text}{entity_text} between {period}, "
            f"averaging {abs(avg_dev):.1f}% deviation from expected."
        )

    return {
        "finding_id": "",
        "headline": headline,
        "severity": finding_severity,
        "score": round(
            _compute_score(worst_severity, max_dev, len(anomalies)), 1
        ),
        "metric": metric,
        "metric_label": metric_label_text,
        "entity": entities[0] if len(entities) == 1 else None,
        "entities": entities,
        "scopes": scopes,
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "direction": direction,
        "observed_value": observed_value,
        "expected_value": expected_value,
        "deviation_pct": deviation_pct,
        "signal_count": count,
        "confidence": count,
        "explanation": explanation,
        "evidence_count": count,
        "anomaly_indices": sorted(original_indices),
    }


def _compute_score(
    worst_severity: str, max_deviation: float, count: int
) -> float:
    """Compute composite score for ranking (0–100)."""
    sev_w = _severity_weight(worst_severity)
    dev_norm = min(max_deviation / 50.0, 1.0)
    count_norm = min(count / 10.0, 1.0)
    raw = (
        _W_SEVERITY * (sev_w / 4.0)
        + _W_DEVIATION * dev_norm
        + _W_DENSITY * count_norm
    )
    return raw * 100


# ---------------------------------------------------------------------------
# Finding count selection
# ---------------------------------------------------------------------------


def _select_finding_count(candidates: list[dict]) -> int:
    """Dynamically determine how many findings to return.

    Target 3–5 for a normal dataset.  Show fewer when there are few
    meaningful findings; show more when there are many genuinely
    independent issues.  Hard cap at 7.
    """
    if not candidates:
        return 0

    if len(candidates) <= 3:
        return len(candidates)

    # Look at score drop-off to find a natural cutoff
    scores = [c["score"] for c in candidates]
    if len(candidates) <= 5:
        return len(candidates)

    # Check if there's a natural gap in scores after 5
    if len(candidates) > 5:
        gap_5 = scores[4] - scores[5] if len(scores) > 5 else 0
        if gap_5 > 15:
            return 5
        # Also check gap after 3
        gap_3 = scores[2] - scores[3] if len(scores) > 3 else 0
        if gap_3 > 20:
            return 3

    return min(5, len(candidates))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_findings(
    anomalies: list[dict],
    *,
    insights: list[dict] | None = None,
    grouping: dict | None = None,
) -> list[dict]:
    """Compress anomalies into prioritised Operational Findings.

    This is the core signal-compression step: 40+ raw anomalies become
    3–5 meaningful business findings.

    Grouping order:
    1. By metric (revenue vs. cost vs. units_sold vs. lead_time_days)
    2. By direction (spikes vs. drops within each metric)
    3. Entity-level outliers of same metric+direction merged into one finding
    4. Daily anomalies sub-grouped by entity, then by temporal proximity

    Args:
        anomalies: Raw anomaly records from ``detect_anomalies``.
        insights: Optional insight records (reserved for future use).
        grouping: Optional group dict (reserved for future use).

    Returns:
        List of finding dicts sorted by score descending, dynamically
        sized between 3–5 for a typical dataset.  Each finding has a
        ``finding_id`` assigned 1-based.
    """
    if not anomalies:
        return []

    # Build buckets: metric → direction → [(original_index, anomaly)]
    metric_dir_buckets = _build_buckets(anomalies)

    candidates: list[dict] = []

    for metric, dir_buckets in metric_dir_buckets.items():
        for direction, items in dir_buckets.items():
            # Split by entity presence
            entity_items: list[tuple[int, dict]] = []
            daily_items: list[tuple[int, dict]] = []

            for idx, anomaly in items:
                if anomaly.get("entity"):
                    entity_items.append((idx, anomaly))
                else:
                    daily_items.append((idx, anomaly))

            # Entity-level anomalies: all grouped together per metric+direction
            # (e.g. 3 regional revenue drops = 1 finding about regional revenue decline)
            if entity_items:
                indices = [i for i, _a in entity_items]
                entity_anomalies = [a for _, a in entity_items]
                finding = _merge_group(entity_anomalies, indices)
                if finding is not None:
                    candidates.append(finding)

            # Daily anomalies: sub-bucket by temporal proximity
            if daily_items:
                temporal_groups = _temporal_sub_bucket(daily_items)
                for group in temporal_groups:
                    indices = [i for i, _a in group]
                    group_anomalies = [a for _, a in group]
                    finding = _merge_group(group_anomalies, indices)
                    if finding is not None:
                        candidates.append(finding)

    # Sort by composite score descending
    candidates.sort(key=lambda f: (-f["score"], f.get("metric", "")))

    # Dynamically determine finding count
    finding_count = _select_finding_count(candidates)
    capped = candidates[:finding_count]

    # Assign IDs
    for idx, finding in enumerate(capped, start=1):
        finding["finding_id"] = f"F{idx}"

    logger.info(
        "findings_built anomaly_count=%d finding_count=%d",
        len(anomalies),
        len(capped),
    )
    return capped
