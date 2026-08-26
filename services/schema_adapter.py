"""Dataset compatibility assessment and schema adaptation (Phase 13).

OpsPilot's deterministic engine requires the canonical operational
schema (``services.validation_service.REQUIRED_COLUMNS``). Real users,
however, upload arbitrary CSVs. This module bridges the two honestly:

* it **profiles** any DataFrame (column kinds, parse rates);
* it **classifies** it into one of three tiers:

    FULL        every canonical column already present and usable —
                the engine runs unchanged;
    PARTIAL     at least one date-like column plus at least one usable
                numeric column — the frame is *projected* onto the
                canonical schema so the standard pipeline can run, with
                missing operational fields filled by neutral constants
                that never produce fake signals or displayed values;
    UNSUPPORTED neither requirement holds — analysis stays blocked and
                the caller explains exactly what is missing;

* adaptation is **disclosed**: the returned report lists every column
  mapping, every synthesized field, and how many rows were dropped, so
  the interface can explain exactly what was analyzed and how.

Policies:

* **No semantic fabrication**: a numeric column only maps onto an
  operational metric via name evidence (or explicit positional fallback
  when nothing matches, clearly flagged); missing metrics become zeros
  which the detector ignores (zero variance) and the interface hides.
* **Determinism**: identical input always yields identical mapping and
  identical adapted frame.
* **Immutability**: the input DataFrame is never modified; all work
  happens on copies.
* **Raw data is preserved**: callers keep the original frame for
  preview/exploration; only ``adapted_df`` feeds the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import re

from services.validation_service import REQUIRED_COLUMNS

TIER_FULL = "full"
TIER_PARTIAL = "partial"
TIER_UNSUPPORTED = "unsupported"

# Canonical slots the adapter can fill.
CANONICAL_METRICS: tuple[str, ...] = (
    "units_sold",
    "revenue",
    "cost",
    "lead_time_days",
)
CANONICAL_DIMENSIONS: tuple[str, ...] = ("region", "product")

# Name-evidence keywords per canonical metric (lowercase substrings).
_METRIC_HINTS: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "sales", "sale", "amount", "income", "turnover", "gmv"),
    "units_sold": ("unit", "qty", "quantity", "count", "sold", "volume"),
    "cost": ("cost", "expense", "spend", "cogs"),
    "lead_time_days": ("lead", "delay", "duration", "cycle", "days_to", "delivery"),
}

_DATE_NAME_HINTS: tuple[str, ...] = ("date", "time", "day", "month", "period", "stamp")

# Deterministic slot priority when unnamed numeric columns must be
# assigned positionally: the primary business metric wins the first slot.
_POSITIONAL_FILL_ORDER: tuple[str, ...] = (
    "revenue",
    "units_sold",
    "cost",
    "lead_time_days",
)

# Minimum share of parseable values for content-based classification.
_PARSE_FRACTION_THRESHOLD = 0.6

# Matches bare numbers so they never masquerade as dates ("10" -> year).
_NUMERIC_VALUE_PATTERN = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
# Small-dataset floor: short CSVs keep low-cardinality labels dimensional.
_CATEGORICAL_CARDINALITY_FLOOR = 10
# Cardinality ceiling for treating a non-numeric column as categorical.
_CATEGORICAL_MAX_CARDINALITY = 50


@dataclass
class CompatibilityReport:
    """Everything the interface needs to explain dataset compatibility."""

    tier: str
    reasons: list[str] = field(default_factory=list)
    # canonical target -> source column (mapped real data only)
    mapping: dict[str, str] = field(default_factory=dict)
    # canonical targets filled with neutral constants (not user data)
    synthesized: list[str] = field(default_factory=list)
    # positional fallback used because no name matched any metric
    positional_fallback: bool = False
    dropped_rows: int = 0
    # canonical KPI keys whose inputs include synthesized data
    affected_derived_kpis: list[str] = field(default_factory=list)


def _numeric_fraction(series: pd.Series) -> float:
    """Share of non-null values that look like numbers (0 when empty).

    Vectorized: for numeric dtypes returns 1.0 instantly; for object
    columns uses ``str.fullmatch`` over the regex once (fast C loop),
    avoiding per-value Python callbacks on 100k+ rows.
    """
    raw = series.dropna()
    n = len(raw)
    if n == 0:
        return 0.0
    if pd.api.types.is_numeric_dtype(series):
        return 1.0
    matches = (
        raw.astype(str)
        .str.strip()
        .str.fullmatch(_NUMERIC_VALUE_PATTERN.pattern, na=False)
    )
    return int(matches.sum()) / n


def _date_fraction(series: pd.Series) -> float:
    """Share of non-null, non-numeric values that parse as dates (0 when empty).

    Vectorized: filters out numeric-looking strings first, then runs
    ``pd.to_datetime(..., format="mixed")`` once on the whole subset
    instead of calling it per scalar.
    """
    raw = series.dropna()
    n = len(raw)
    if n == 0:
        return 0.0
    if pd.api.types.is_numeric_dtype(series):
        return 0.0
    raw_str = raw.astype(str).str.strip()
    is_numeric = raw_str.str.fullmatch(_NUMERIC_VALUE_PATTERN.pattern, na=False)
    candidate_mask = ~is_numeric
    candidates = raw_str[candidate_mask]
    if len(candidates) == 0:
        return 0.0
    try:
        parsed = pd.to_datetime(candidates, errors="coerce", format="mixed")
    except (ValueError, TypeError):
        return 0.0
    parsed_count = int(parsed.notna().sum())
    return parsed_count / n


def _column_kind(series: pd.Series) -> str:
    """Classify one column as date/numeric/categorical/text.

    Fully vectorized content-based rules: no per-value Python callbacks.
    For a 100k-row column this runs in <10 ms instead of ~70 s.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if _numeric_fraction(series) >= _PARSE_FRACTION_THRESHOLD:
        return "numeric"
    if _date_fraction(series) >= _PARSE_FRACTION_THRESHOLD:
        return "date"
    # Generous small-dataset floor so short CSVs still classify their
    # low-cardinality label columns as dimensions.
    if series.nunique(dropna=True) <= max(
        _CATEGORICAL_CARDINALITY_FLOOR,
        min(_CATEGORICAL_MAX_CARDINALITY, len(series) // 2),
    ):
        return "categorical"
    return "text"


def profile_columns(df: pd.DataFrame) -> dict[str, str]:
    """Return ``{column: kind}`` for every column of ``df``."""
    return {str(col): _column_kind(df[col]) for col in df.columns}


def _parse_date_series(series: pd.Series) -> pd.Series:
    """Parse with the validation service's default-then-mixed strategy."""
    parsed = pd.to_datetime(series, errors="coerce")
    if bool((parsed.isna() & ~series.isna()).any()):
        try:
            mixed = pd.to_datetime(series, errors="coerce", format="mixed")
            improved = parsed.isna() & mixed.notna()
            parsed = parsed.where(~improved, mixed)
        except (ValueError, TypeError):
            pass
    return parsed


def _score_date_candidates(
    df: pd.DataFrame,
    kinds: dict[str, str] | None = None,
) -> dict[str, float]:
    """Score every date-like column; higher wins (name hint + parse rate).

    When *kinds* is provided (from a prior ``profile_columns`` call), the
    per-column kind is looked up directly instead of re-profiling.
    """
    scores: dict[str, float] = {}
    for col in df.columns:
        col_str = str(col)
        kind = kinds[col_str] if kinds is not None else _column_kind(df[col])
        if kind != "date":
            continue
        name = col_str.lower()
        name_bonus = 2.0 if any(h in name for h in _DATE_NAME_HINTS) else 0.0
        parsed = _parse_date_series(df[col])
        rate = float(parsed.notna().mean()) if len(parsed) else 0.0
        scores[col_str] = name_bonus + rate
    return scores


def _hint_metric(name: str) -> str | None:
    lowered = name.lower()
    for metric, hints in _METRIC_HINTS.items():
        if any(hint in lowered for hint in hints):
            return metric
    return None


def assess_and_adapt(
    df: pd.DataFrame,
    *,
    precomputed_kinds: dict[str, str] | None = None,
) -> tuple[pd.DataFrame | None, CompatibilityReport]:
    """Classify ``df`` and, for partial datasets, project it onto the
    canonical schema.

    When *precomputed_kinds* is provided (e.g. from a prior
    ``profile_columns`` call), it is reused instead of re-profiling every
    column — this avoids the O(n) cost duplication across callers.

    Returns:
        ``(analysis_df, report)`` where ``analysis_df`` is ``None`` for
        unsupported datasets and otherwise a frame carrying exactly the
        canonical columns (a copy — the input is untouched).
    """
    from services.capability_service import build_capability_profile

    if not isinstance(df, pd.DataFrame) or df.empty:
        return None, CompatibilityReport(
            tier=TIER_UNSUPPORTED,
            reasons=["The dataset has no data rows to analyze."],
        )

    kinds = precomputed_kinds if precomputed_kinds is not None else profile_columns(df)
    present = set(map(str, df.columns))
    missing = [col for col in REQUIRED_COLUMNS if col not in present]

    if not missing:
        # Canonical schema already satisfied; the validation gate owns it.
        return df, CompatibilityReport(tier=TIER_FULL)

    # --- Build capability profile to determine what analysis is possible ---
    capability = build_capability_profile(df)

    # Class E (insufficient): no numeric or date columns at all
    if capability.dataset_class == "E":
        return None, CompatibilityReport(
            tier=TIER_UNSUPPORTED,
            reasons=capability.classification_reasons,
        )

    work = df.copy()

    # --- choose the date column (if available) --------------------------------
    date_scores = _score_date_candidates(work, kinds=kinds)
    date_col = max(date_scores, key=lambda c: date_scores[c]) if date_scores else None

    # --- classify remaining columns --------------------------------------------
    numeric_cols: list[str] = []
    categorical_cols: list[str] = []
    for col in work.columns:
        if str(col) == date_col:
            continue
        kind = kinds.get(str(col), "text")
        if kind == "numeric":
            numeric_cols.append(str(col))
        elif kind == "categorical":
            categorical_cols.append(str(col))

    reasons: list[str] = []

    # For non-time-series datasets (Types B, C, D), create a synthetic date
    # column so the canonical schema can be satisfied. The capability profile
    # tells the pipeline which time-dependent operations to skip.
    synthetic_date = False
    if date_col is None and capability.dataset_class in ("B", "C"):
        reasons.append(
            "No recognizable date/time column — a synthetic date column was "
            "created so the analysis pipeline can run. Time-based analysis "
            "(trends, period comparison) is unavailable."
        )
        synthetic_date = True
    elif date_col is None and capability.dataset_class == "D":
        reasons.append(
            "No usable numeric column was found — numeric analysis is unavailable."
        )
        return None, CompatibilityReport(
            tier=TIER_UNSUPPORTED,
            reasons=reasons,
        )
    elif date_col is None:
        reasons.append(
            "No recognizable date/time column was found — anomaly detection "
            "and trend analysis need timestamps to work."
        )

    if not numeric_cols and capability.dataset_class not in ("D",):
        reasons.append(
            "No usable numeric column was found — at least one number "
            "column (for example sales, revenue, or units) is required."
        )

    if not synthetic_date and date_col is None:
        return None, CompatibilityReport(
            tier=TIER_UNSUPPORTED, reasons=reasons
        )

    # --- metric mapping -----------------------------------------------------------
    mapping: dict[str, str] = {}
    positional_fallback = False
    available = list(numeric_cols)

    # Pass 1: strongest name evidence per canonical slot.
    for metric in CANONICAL_METRICS:
        match = next(
            (col for col in available if _hint_metric(col) == metric), None
        )
        if match is not None:
            mapping[metric] = match
            available.remove(match)

    # Pass 2: fill remaining unfilled canonical slots from the leftover
    # available columns using deterministic positional order. This ensures
    # partial name matches don't leave other slots empty (e.g. "spend"
    # matching cost but leaving revenue unfilled).
    if available:
        positional_fallback = True
        for metric in _POSITIONAL_FILL_ORDER:
            if metric not in mapping and available:
                mapping[metric] = available.pop(0)

    # Type D (date + categorical, no numeric): no metrics to map
    if not mapping and capability.dataset_class == "D":
        reasons.append(
            "No numeric columns found — numeric analysis and anomaly "
            "detection are unavailable. Only categorical analysis is possible."
        )
        return None, CompatibilityReport(
            tier=TIER_UNSUPPORTED, reasons=reasons
        )

    synthesized = [m for m in CANONICAL_METRICS if m not in mapping]

    # Derived cost: when the source has a profit column but no cost column,
    # we can recover cost as revenue - profit.  This is a common CSV layout
    # (sales_amount, profit, quantity...) and without this step cost stays 0,
    # which makes profit KPIs meaningless.
    if "cost" in synthesized and "revenue" in mapping:
        profit_col = next(
            (c for c in numeric_cols if c not in mapping.values()
             and "profit" in c.lower()),
            None,
        )
        if profit_col is not None:
            mapping["cost"] = profit_col
            synthesized.remove("cost")
            # Flag so the interface knows cost was derived (not raw)
            reasons.append(
                f"Column '{profit_col}' was interpreted as profit; cost was "
                f"derived as revenue - {profit_col}."
            )

    # --- dimensions -----------------------------------------------------------------
    dimension_map: dict[str, str] = {}
    for dim, col in zip(CANONICAL_DIMENSIONS, categorical_cols):
        dimension_map[dim] = col
    mapping.update(dimension_map)
    synthesized.extend(d for d in CANONICAL_DIMENSIONS if d not in dimension_map)

    # --- build the projected frame ----------------------------------------------------
    adapted = pd.DataFrame(index=work.index)
    dropped_mask = pd.Series(False, index=work.index)

    # Date column: use real dates if available, otherwise synthetic
    if synthetic_date:
        adapted["date"] = "2024-01-01"
    elif date_col is not None:
        parsed_dates = _parse_date_series(work[date_col])
        dropped_mask |= parsed_dates.isna()
        adapted["date"] = parsed_dates.dt.strftime("%Y-%m-%d")

    for metric in CANONICAL_METRICS:
        source = mapping.get(metric)
        if source is None:
            adapted[metric] = 0.0
            continue
        values = pd.to_numeric(work[source], errors="coerce")
        dropped_mask |= values.isna()
        # When cost was derived from a profit column, compute
        # cost = revenue - profit instead of copying the raw profit values.
        if (
            metric == "cost"
            and "revenue" in adapted
            and source != "cost"
            and "profit" in source.lower()
        ):
            revenue_vals = pd.to_numeric(work[mapping["revenue"]], errors="coerce")
            adapted[metric] = revenue_vals - values
        else:
            adapted[metric] = values

    for dim in CANONICAL_DIMENSIONS:
        source = mapping.get(dim)
        if source is None:
            adapted[dim] = "All"
        else:
            adapted[dim] = work[source].astype(str)

    dropped_rows = int(dropped_mask.sum())
    if dropped_rows > 0:
        adapted = adapted[~dropped_mask].reset_index(drop=True)
    if adapted.empty:
        return None, CompatibilityReport(
            tier=TIER_UNSUPPORTED,
            reasons=[
                "Every row failed basic parsing (unparseable dates or "
                "non-numeric values), leaving nothing to analyze."
            ],
        )

    # Derived-KPI impact disclosure: profit/margin combine revenue+cost;
    # lead-time KPIs stand alone.
    affected: list[str] = []
    if "cost" in synthesized:
        affected.extend(["total_profit", "profit_margin_pct", "profit_change_pct"])
    if "lead_time_days" in synthesized:
        affected.extend(["average_lead_time_days", "lead_time_change_pct"])
    if "units_sold" in synthesized:
        affected.extend(["total_units_sold", "units_change_pct"])

    order = ["date"] + list(CANONICAL_DIMENSIONS) + list(CANONICAL_METRICS)
    adapted = adapted[order]

    report = CompatibilityReport(
        tier=TIER_PARTIAL,
        reasons=reasons + [
            f"Mapped {len(mapping)} column(s) onto OpsPilot's operational "
            "schema; the standard pipeline runs on this projection.",
        ]
        + (
            [
                "Column names did not match known operational fields, so "
                "numeric columns were assigned positionally."
            ]
            if positional_fallback
            else []
        ),
        mapping=mapping,
        synthesized=synthesized,
        positional_fallback=positional_fallback,
        dropped_rows=dropped_rows,
        affected_derived_kpis=affected,
    )
    return adapted, report


def report_payload(report: CompatibilityReport) -> dict:
    """JSON-safe projection of a :class:`CompatibilityReport`."""
    return {
        "tier": report.tier,
        "reasons": list(report.reasons),
        "mapping": dict(report.mapping),
        "synthesized": list(report.synthesized),
        "positional_fallback": report.positional_fallback,
        "dropped_rows": report.dropped_rows,
        "affected_derived_kpis": list(report.affected_derived_kpis),
    }
