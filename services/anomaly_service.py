"""Daily time-series anomaly detection for OpsPilot AI (Phase 3B).

First slice of the anomaly engine: detects spikes and drops in the
dataset-wide daily totals of a single operational metric, plus
entity-level (region/product) outlier detection via Tukey IQR fences
over each entity's full-period metric total.

Policies
--------
* **Determinism**: identical input always produces identical output.
  Dates are processed in ascending order; no randomness or wall-clock
  time is involved anywhere.
* **Immutability**: caller DataFrames are never modified. All work is
  performed on the normalized working copy produced by
  ``services.analytics_service._prepare_operational_data``.
* **Input policy**: identical to analytics — the dataset must pass
  ``validate_dataframe`` with zero errors and contain at least one row.
  ``metric`` must be one of the four supported numeric metrics and
  ``sensitivity`` one of ``low``/``medium``/``high``; violations raise
  ``DataValidationError`` from ``core.exceptions``.
* **Aggregation**: the metric is summed per unique observed date,
  yielding exactly one value per date sorted ascending. Missing calendar
  dates are never filled and never assumed to exist; raw unrounded
  values are used for all math.
* **Baseline**: each candidate date is compared against the previous
  ``MIN_HISTORY_DAYS`` observed points (a trailing window that excludes
  the candidate itself). Fewer than ``MIN_HISTORY_DAYS + 1`` unique
  dates means there are no candidates at all.
* **Safe math**: a zero baseline standard deviation produces no anomaly;
  a zero expected value yields a deviation percentage of ``0.0``. No
  NaN or infinity is ever emitted.
* **Rounding**: full precision is kept during calculation; values are
  rounded to 2 decimal places only when placed into the output.
  Severity is derived from the rounded presentation score so every
  anomaly record is internally consistent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.constants import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
)
from core.exceptions import DataValidationError
from services.analytics_service import ROUNDING_DECIMALS, _prepare_operational_data

# A candidate date needs this many previous observed daily points.
MIN_HISTORY_DAYS: int = 7

# Absolute z-score at which the anomaly score saturates at 100.
Z_SCORE_CAP: float = 6.0

# Sensitivity name -> minimum |z| required to flag an anomaly.
SENSITIVITY_THRESHOLDS: dict[str, float] = {
    "low": 3.5,
    "medium": 3.0,
    "high": 2.5,
}

# Canonical metric names used for the standard pipeline.
# ``detect_anomalies`` may also analyse any additional numeric column
# present in the working copy, but these are always included when
# available.
SUPPORTED_METRICS: frozenset[str] = frozenset(
    {"units_sold", "revenue", "cost", "lead_time_days"}
)

# Rule identifier embedded in every anomaly record.
RULE_ZSCORE_ROLLING: str = "zscore_rolling"

# Rule identifier for entity-level IQR fence outliers.
RULE_IQR_FENCE: str = "iqr_fence"

# Dimensions eligible for entity-level outlier detection.
SUPPORTED_DIMENSIONS: frozenset[str] = frozenset({"region", "product"})

# Entity comparisons need at least this many entities to be meaningful.
MIN_ENTITY_COUNT: int = 4

# Fences sit at Q1/Q3 minus/plus this multiple of the IQR.
IQR_FENCE_MULTIPLIER: float = 1.5

# Divisor converting an IQR into a robust standard-deviation estimate.
ROBUST_Z_SCALE: float = 1.349

# Inclusive minimum score for each severity band.
SEVERITY_CRITICAL_MIN_SCORE: float = 85.0
SEVERITY_HIGH_MIN_SCORE: float = 70.0
SEVERITY_MEDIUM_MIN_SCORE: float = 50.0

# Hard cap on the number of anomalies returned by detect_anomalies.
# Hourly or sub-daily data can generate thousands of flagged points;
# downstream explain_anomalies is O(n) per anomaly with O(n) inner
# loops, so unbounded output causes multi-minute hangs on large data.
# The cap keeps the most severe anomalies and discards the rest.
MAX_ANOMALIES: int = 500


# --- Private helpers --------------------------------------------------------


def _round(value: float) -> float:
    """Round a presentation value to the configured number of decimals."""
    return round(float(value), ROUNDING_DECIMALS)


def _validate_metric(metric: object) -> None:
    """Raise ``DataValidationError`` unless ``metric`` is supported."""
    if not isinstance(metric, str) or metric not in SUPPORTED_METRICS:
        supported = ", ".join(sorted(SUPPORTED_METRICS))
        raise DataValidationError(
            f"Unsupported metric {metric!r}; expected one of: {supported}"
        )


def _validate_dimension(dimension: object) -> None:
    """Raise ``DataValidationError`` unless ``dimension`` is supported."""
    if not isinstance(dimension, str) or dimension not in SUPPORTED_DIMENSIONS:
        supported = ", ".join(sorted(SUPPORTED_DIMENSIONS))
        raise DataValidationError(
            f"Unsupported dimension {dimension!r}; expected one of: {supported}"
        )


def _validate_sensitivity(sensitivity: object) -> float:
    """Return the threshold for a valid sensitivity, else raise."""
    if not isinstance(sensitivity, str) or sensitivity not in SENSITIVITY_THRESHOLDS:
        choices = ", ".join(sorted(SENSITIVITY_THRESHOLDS))
        raise DataValidationError(
            f"Unsupported sensitivity {sensitivity!r}; expected one of: {choices}"
        )
    return SENSITIVITY_THRESHOLDS[sensitivity]


def _classify_severity(score: float) -> str:
    """Map a presentation score onto the shared severity constants."""
    if score >= SEVERITY_CRITICAL_MIN_SCORE:
        return SEVERITY_CRITICAL
    if score >= SEVERITY_HIGH_MIN_SCORE:
        return SEVERITY_HIGH
    if score >= SEVERITY_MEDIUM_MIN_SCORE:
        return SEVERITY_MEDIUM
    return SEVERITY_LOW


def _deviation_pct(value: float, expected_value: float) -> float:
    """Signed percentage deviation; zero expected values yield ``0.0``."""
    if expected_value == 0:
        return 0.0
    return (value - expected_value) / expected_value * 100.0


def _daily_series(work: pd.DataFrame, metric: str) -> pd.Series:
    """Sum ``metric`` per unique observed date, sorted ascending."""
    return work.groupby("date", sort=True)[metric].sum()


# Severity ranking used when ordering combined anomaly records.
SEVERITY_PRIORITY: dict[str, int] = {
    SEVERITY_CRITICAL: 0,
    SEVERITY_HIGH: 1,
    SEVERITY_MEDIUM: 2,
    SEVERITY_LOW: 3,
}

# Severity labels accepted inside anomaly records.
VALID_SEVERITIES: frozenset[str] = frozenset(SEVERITY_PRIORITY)

# Fields every anomaly record must expose for ``summarize_anomalies``.
SUMMARY_REQUIRED_FIELDS: tuple[str, ...] = ("type", "scope", "metric", "severity")


def _severity_rank(severity: object) -> int:
    """Return the sort rank for a severity label (lower = worse)."""
    return SEVERITY_PRIORITY.get(severity, len(SEVERITY_PRIORITY))  # type: ignore[arg-type]


def _aggregate_sort_key(record: dict[str, object]) -> tuple[object, ...]:
    """Deterministic ordering key for combined anomaly records.

    Severity priority (CRITICAL first), then higher score, then date
    ascending, then entity ascending, then metric/type as final tie
    breakers. Missing ``date``/``entity`` values (entity-level records
    carry ``None``) sort as empty strings.
    """
    return (
        _severity_rank(record.get("severity")),
        -float(record.get("score", 0.0)),  # type: ignore[arg-type]
        str(record.get("date") or ""),
        str(record.get("entity") or ""),
        str(record.get("metric") or ""),
        str(record.get("type") or ""),
    )


# --- Public API -------------------------------------------------------------


def _detect_metric_anomalies_core(
    work: pd.DataFrame,
    metric: str,
    threshold: float,
) -> list[dict[str, object]]:
    """Core daily spike/drop detection on an already-prepared working copy.

    This is the validation-free internal variant used by
    ``detect_anomalies`` when iterating over dynamically discovered
    metrics.  The public ``detect_metric_anomalies`` wraps this with
    input validation and ``_prepare_operational_data``.
    """
    daily = _daily_series(work, metric)
    values = daily.to_numpy(dtype=float)
    dates = daily.index

    anomalies: list[dict[str, object]] = []
    for position in range(MIN_HISTORY_DAYS, len(values)):
        window = values[position - MIN_HISTORY_DAYS : position]
        baseline_mean = float(np.mean(window))
        baseline_std = float(np.std(window, ddof=1))
        if baseline_std == 0.0:
            continue
        value = float(values[position])
        z = (value - baseline_mean) / baseline_std
        if abs(z) < threshold:
            continue
        score = min(100.0, 100.0 * abs(z) / Z_SCORE_CAP)
        rounded_score = _round(score)
        anomalies.append(
            {
                "type": "daily_spike" if value > baseline_mean else "daily_drop",
                "scope": "daily",
                "metric": metric,
                "entity": None,
                "date": dates[position].strftime("%Y-%m-%d"),
                "value": _round(value),
                "expected_value": _round(baseline_mean),
                "deviation_pct": _round(_deviation_pct(value, baseline_mean)),
                "score": rounded_score,
                "severity": _classify_severity(rounded_score),
                "rule": RULE_ZSCORE_ROLLING,
                "details": {
                    "z": _round(z),
                    "baseline_std": _round(baseline_std),
                    "threshold": threshold,
                },
            }
        )
    return anomalies


def _detect_entity_anomalies_core(
    work: pd.DataFrame,
    dimension: str,
    metric: str,
) -> list[dict[str, object]]:
    """Core entity outlier detection on an already-prepared working copy.

    Validation-free internal variant used by ``detect_anomalies``.
    """
    totals = work.groupby(dimension, sort=True)[metric].sum()
    if len(totals) < MIN_ENTITY_COUNT:
        return []

    values = totals.to_numpy(dtype=float)
    q1 = float(np.quantile(values, 0.25))
    median = float(np.quantile(values, 0.50))
    q3 = float(np.quantile(values, 0.75))
    iqr = q3 - q1
    if iqr == 0.0:
        return []

    lower_fence = q1 - IQR_FENCE_MULTIPLIER * iqr
    upper_fence = q3 + IQR_FENCE_MULTIPLIER * iqr
    robust_std = iqr / ROBUST_Z_SCALE

    anomalies: list[dict[str, object]] = []
    for entity, raw_value in totals.items():
        value = float(raw_value)
        if lower_fence <= value <= upper_fence:
            continue
        z = (value - median) / robust_std
        score = min(100.0, round(100.0 * abs(z) / Z_SCORE_CAP, ROUNDING_DECIMALS))
        anomalies.append(
            {
                "type": (
                    "entity_outlier_high" if value > upper_fence else "entity_outlier_low"
                ),
                "scope": dimension,
                "metric": metric,
                "entity": str(entity),
                "date": None,
                "value": _round(value),
                "expected_value": _round(median),
                "deviation_pct": _round(_deviation_pct(value, median)),
                "score": score,
                "severity": _classify_severity(score),
                "rule": RULE_IQR_FENCE,
                "details": {
                    "z": _round(z),
                    "q1": _round(q1),
                    "median": _round(median),
                    "q3": _round(q3),
                    "iqr": _round(iqr),
                    "lower_fence": _round(lower_fence),
                    "upper_fence": _round(upper_fence),
                },
            }
        )
    return anomalies


def detect_metric_anomalies(
    df: pd.DataFrame, metric: str, *, sensitivity: str = "medium"
) -> list[dict[str, object]]:
    """Detect spike/drop anomalies in the daily totals of one metric.

    For every observed date that has at least ``MIN_HISTORY_DAYS``
    preceding observed points, the date's total is compared against the
    trailing window of previous daily totals (which never includes the
    candidate itself). A date is anomalous when the absolute z-score
    against that window reaches the sensitivity threshold.

    Args:
        df: Operational DataFrame following the canonical schema. It is
            never mutated.
        metric: One of ``units_sold``, ``revenue``, ``cost``,
            ``lead_time_days``.
        sensitivity: ``low`` (threshold 3.5), ``medium`` (3.0), or
            ``high`` (2.5). Higher sensitivity flags more dates.

    Returns:
        List of anomaly dictionaries sorted by date ascending. Each
        record contains exactly ``type`` (``daily_spike`` or
        ``daily_drop``), ``scope`` (always ``daily``), ``metric``,
        ``entity`` (always ``None``), ``date`` (ISO string), ``value``,
        ``expected_value``, ``deviation_pct``, ``score`` (0-100),
        ``severity``, ``rule`` (always ``zscore_rolling``), and
        ``details`` with ``z``, ``baseline_std``, and ``threshold``.
        Datasets with fewer than eight unique dates yield an empty list.

    Raises:
        DataValidationError: If the dataset is unusable (see module
            policy) or ``metric``/``sensitivity`` is invalid.
    """
    _validate_metric(metric)
    threshold = _validate_sensitivity(sensitivity)
    work = _prepare_operational_data(df)
    return _detect_metric_anomalies_core(work, metric, threshold)


def detect_entity_anomalies(
    df: pd.DataFrame,
    dimension: str,
    metric: str,
    *,
    sensitivity: str = "medium",
) -> list[dict[str, object]]:
    """Detect outlier entities in the full-period total of one metric.

    The metric is summed per entity (``region`` or ``product``) over the
    complete observed period. When at least four entities exist, Tukey
    fences are built from the quartiles of those totals; an entity
    outside ``[Q1 - 1.5 * IQR, Q3 + 1.5 * IQR]`` is flagged as an
    outlier. A degenerate distribution (``IQR == 0``) yields no
    anomalies.

    Args:
        df: Operational DataFrame following the canonical schema. It is
            never mutated.
        dimension: Either ``region`` or ``product``.
        metric: One of ``units_sold``, ``revenue``, ``cost``,
            ``lead_time_days``.
        sensitivity: Validated for API consistency with the daily
            detector; fence placement itself is fixed at ``1.5 * IQR``.

    Returns:
        List of anomaly dictionaries ordered by entity name ascending.
        Each record contains exactly ``type``
        (``entity_outlier_high`` above the upper fence,
        ``entity_outlier_low`` below the lower fence), ``scope`` (the
        requested dimension), ``metric``, ``entity``, ``date`` (always
        ``None``), ``value``, ``expected_value`` (the median),
        ``deviation_pct``, ``score`` (0-100, derived from a robust
        z-score using the ``IQR / 1.349`` scale estimate), ``severity``,
        ``rule`` (always ``iqr_fence``), and ``details`` with ``z``,
        ``q1``, ``median``, ``q3``, ``iqr``, ``lower_fence``, and
        ``upper_fence``. Datasets with fewer than four entities yield an
        empty list.

    Raises:
        DataValidationError: If the dataset is unusable (see module
            policy) or ``dimension``/``metric``/``sensitivity`` is
            invalid.
    """
    _validate_dimension(dimension)
    _validate_metric(metric)
    _validate_sensitivity(sensitivity)
    work = _prepare_operational_data(df)
    return _detect_entity_anomalies_core(work, dimension, metric)


def _discover_numeric_metrics(df: pd.DataFrame) -> list[str]:
    """Discover numeric columns available for anomaly detection.

    Inspects the working copy (post ``_prepare_operational_data``) and
    returns a sorted list of columns that contain finite numeric data.
    Canonical metrics are always included first (when present); any
    additional numeric columns discovered are appended.
    """
    work = _prepare_operational_data(df)
    numeric_cols: list[str] = []
    for col in work.columns:
        if col == "date":
            continue
        try:
            values = pd.to_numeric(work[col], errors="coerce")
            if values.notna().any() and bool(np.isfinite(values.dropna()).all()):
                numeric_cols.append(col)
        except (TypeError, ValueError):
            continue
    canonical = sorted(col for col in numeric_cols if col in SUPPORTED_METRICS)
    extra = sorted(col for col in numeric_cols if col not in SUPPORTED_METRICS)
    return canonical + extra


def detect_anomalies(
    df: pd.DataFrame, *, sensitivity: str = "medium"
) -> dict[str, object]:
    """Run every detector across all available metrics and combine.

    Discovers numeric columns dynamically from the working copy rather
    than relying on a hardcoded metric list.  For each discovered metric
    this invokes ``detect_metric_anomalies`` (daily scope) plus
    ``detect_entity_anomalies`` for the ``region`` and ``product``
    dimensions (when they exist), merges all returned records without
    deduplication, and sorts them deterministically: severity priority
    (``CRITICAL`` first, then ``HIGH``, ``MEDIUM``, ``LOW``), higher
    score first, date ascending, entity ascending, then metric/type as
    final tie breakers.

    Args:
        df: Operational DataFrame following the canonical schema. It is
            never mutated.
        sensitivity: Passed through to every underlying detector;
            validated up front with the shared validation logic.

    Returns:
        Dictionary with exactly ``anomalies`` (the combined, sorted
        records), ``total_count`` (int), ``by_severity`` (counts for all
        four severity constants; always present), ``sensitivity`` (the
        requested level), ``metrics_analyzed`` (the discovered metric
        names in deterministic sorted order), and ``original_metric_names``
        (mapping of canonical metric -> original column name when the
        schema adapter preserved original names).

    Raises:
        DataValidationError: If the dataset is unusable (see module
            policy) or ``sensitivity`` is invalid.
    """
    _validate_sensitivity(sensitivity)
    metrics = _discover_numeric_metrics(df)
    threshold = SENSITIVITY_THRESHOLDS[sensitivity]

    combined: list[dict[str, object]] = []
    work = _prepare_operational_data(df)
    has_region = "region" in work.columns
    has_product = "product" in work.columns

    for metric in metrics:
        if metric not in work.columns:
            continue
        combined.extend(_detect_metric_anomalies_core(work, metric, threshold))
        if has_region:
            combined.extend(
                _detect_entity_anomalies_core(work, "region", metric)
            )
        if has_product:
            combined.extend(
                _detect_entity_anomalies_core(work, "product", metric)
            )

    combined.sort(key=_aggregate_sort_key)

    # Cap output to prevent O(n²) downstream processing on high-cardinality data.
    if len(combined) > MAX_ANOMALIES:
        combined = combined[:MAX_ANOMALIES]

    by_severity: dict[str, int] = {
        severity: 0
        for severity in (
            SEVERITY_CRITICAL,
            SEVERITY_HIGH,
            SEVERITY_MEDIUM,
            SEVERITY_LOW,
        )
    }
    for record in combined:
        severity = str(record["severity"])
        if severity in by_severity:
            by_severity[severity] += 1

    return {
        "anomalies": combined,
        "total_count": len(combined),
        "by_severity": by_severity,
        "sensitivity": sensitivity,
        "metrics_analyzed": metrics,
    }


def summarize_anomalies(
    anomalies: list[dict[str, object]],
) -> dict[str, object]:
    """Summarize anomaly records by severity, type, scope, and metric.

    Pure counting helper over already-produced anomaly records (for
    example the ``anomalies`` list returned by ``detect_anomalies``).
    The input list and its records are never mutated; all returned
    containers are plain Python dictionaries of integers keyed by
    strings. ``by_severity`` always contains exactly the four shared
    severity constants (including zero counts); ``by_type``,
    ``by_scope``, and ``by_metric`` contain only observed values with
    keys in ascending order for deterministic output.

    Args:
        anomalies: List of anomaly dictionaries. An empty list is valid
            and yields an all-zero summary.

    Returns:
        Dictionary with exactly ``total_count`` (int, equal to
        ``len(anomalies)``), ``by_severity`` (all four severity
        constants), ``by_type``, ``by_scope``, and ``by_metric``.

    Raises:
        DataValidationError: If ``anomalies`` is not a list, any item is
            not a dictionary, any item lacks one of ``type``,
            ``scope``, ``metric``, or ``severity``, or any severity is
            not one of the four supported constants.
    """
    if not isinstance(anomalies, list):
        raise DataValidationError(
            f"Expected a list of anomaly dictionaries; got {type(anomalies).__name__}"
        )

    by_type: dict[str, int] = {}
    by_scope: dict[str, int] = {}
    by_metric: dict[str, int] = {}
    by_severity: dict[str, int] = {
        severity: 0
        for severity in (
            SEVERITY_CRITICAL,
            SEVERITY_HIGH,
            SEVERITY_MEDIUM,
            SEVERITY_LOW,
        )
    }

    for position, record in enumerate(anomalies):
        if not isinstance(record, dict):
            raise DataValidationError(
                f"Anomaly at index {position} is not a dictionary "
                f"(got {type(record).__name__})"
            )
        missing = [field for field in SUMMARY_REQUIRED_FIELDS if field not in record]
        if missing:
            raise DataValidationError(
                f"Anomaly at index {position} is missing required field(s): "
                + ", ".join(missing)
            )
        severity = record["severity"]
        if not isinstance(severity, str) or severity not in VALID_SEVERITIES:
            expected = ", ".join(sorted(VALID_SEVERITIES))
            raise DataValidationError(
                f"Anomaly at index {position} has unsupported severity "
                f"{severity!r}; expected one of: {expected}"
            )
        by_severity[severity] += 1
        for bucket, field in (
            (by_type, "type"),
            (by_scope, "scope"),
            (by_metric, "metric"),
        ):
            label = str(record[field])
            bucket[label] = bucket.get(label, 0) + 1

    return {
        "total_count": len(anomalies),
        "by_severity": by_severity,
        "by_type": dict(sorted(by_type.items())),
        "by_scope": dict(sorted(by_scope.items())),
        "by_metric": dict(sorted(by_metric.items())),
    }
