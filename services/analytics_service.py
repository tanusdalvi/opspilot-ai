"""Deterministic operational analytics engine for OpsPilot AI.

Single trusted calculation layer for KPIs, region/product performance,
daily trends, period comparison, and top/bottom performers. Every later
module (dashboard, alerts, anomaly detection, agent, reports) consumes
this service instead of recomputing metrics itself.

Policies
--------
* **Determinism**: identical input always produces identical output.
  All outputs are explicitly sorted; no randomness or wall-clock time
  is involved anywhere.
* **Immutability**: caller DataFrames are never modified. All work is
  performed on internal copies and derived objects.
* **Input policy**: analytics requires a dataset that passes
  ``services.validation_service.validate_dataframe`` with zero errors
  (warnings such as extra columns or duplicate rows do not block).
  Non-DataFrame input, schema errors, empty datasets, invalid numeric
  values, unparseable dates, and non-finite numbers (NaN/inf) raise
  ``DataValidationError`` from ``core.exceptions``. An empty dataset
  never silently yields zeros.
* **Rounding**: all internal math keeps full float precision. Values are
  rounded to 2 decimal places only when placed into output structures.
  Unit totals are returned as ``int`` when integral, otherwise as floats
  rounded to 2 decimals. Dates in outputs are ISO ``YYYY-MM-DD`` strings.
* **Safe division**: whenever a denominator is zero (revenue, units,
  previous-period value), the calculated percentage is ``0.0`` instead
  of ``inf``/``NaN``. No calculated metric is ever ``inf`` or ``NaN``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.exceptions import DataValidationError
from services.validation_service import (
    NUMERIC_COLUMNS,
    REQUIRED_COLUMNS,
    validate_dataframe,
)

# Default number of entities returned by the performer functions.
DEFAULT_PERFORMER_LIMIT: int = 5

# Decimal places used for every rounded presentation value.
ROUNDING_DECIMALS: int = 2

# Canonical numeric metrics and their preferred display direction.
_METRIC_DIRECTION: dict[str, str] = {
    "units_sold": "higher_is_better",
    "revenue": "higher_is_better",
    "cost": "lower_is_better",
    "lead_time_days": "lower_is_better",
}


# --- Private helpers --------------------------------------------------------


def _round(value: float) -> float:
    """Round a presentation value to the configured number of decimals."""
    return round(float(value), ROUNDING_DECIMALS)


def _as_count(value: float) -> int | float:
    """Return ``value`` as ``int`` when integral, else rounded to 2 decimals."""
    numeric = float(value)
    if numeric.is_integer():
        return int(numeric)
    return _round(numeric)


def _to_python(value: object) -> object:
    """Convert numpy scalars to native Python values for dict outputs."""
    if hasattr(value, "item"):
        return value.item()
    return value


def _safe_ratio(numerator: float, denominator: float) -> float:
    """Divide safely; a zero denominator yields ``0.0`` instead of inf/NaN."""
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _safe_pct_change(current: float, previous: float) -> float:
    """Percentage change ``(current - previous) / previous * 100``.

    A zero previous value yields ``0.0`` per the documented safe policy.
    """
    return _round(_safe_ratio(current - previous, previous) * 100.0)


def _require_usable_frame(df: pd.DataFrame) -> None:
    """Raise ``DataValidationError`` unless ``df`` is analytics-ready.

    The frame must be a pandas DataFrame whose validation report contains
    no errors (per ``validate_dataframe``) and at least one row.
    """
    if not isinstance(df, pd.DataFrame):
        raise DataValidationError(
            f"Expected a pandas DataFrame, got {type(df).__name__}"
        )
    report = validate_dataframe(df)
    if report["error_count"] > 0:
        details = "; ".join(
            f"{issue['code']}: {issue['message']}"  # type: ignore[index]
            for issue in report["errors"]  # type: ignore[index]
        )
        raise DataValidationError(f"Dataset is not usable for analytics ({details})")
    if len(df) == 0:
        raise DataValidationError(
            "Dataset is empty; analytics require at least one data row"
        )


def _parse_date_column(series: pd.Series) -> pd.Series:
    """Parse the validated date column to datetimes.

    Mirrors the validation service strategy: default parsing first, then a
    ``format="mixed"`` retry so differently formatted but genuine dates
    still parse consistently.
    """
    parsed = pd.to_datetime(series, errors="coerce")
    if bool((parsed.isna() & ~series.isna()).any()):
        try:
            mixed = pd.to_datetime(series, errors="coerce", format="mixed")
        except (ValueError, TypeError):
            return parsed
        improved = parsed.isna() & mixed.notna()
        parsed = parsed.where(~improved, mixed)
    return parsed


def _prepare_operational_data(df: pd.DataFrame) -> pd.DataFrame:
    """Validate ``df`` and return an independent normalized working copy.

    The working copy contains the available canonical columns with the date
    column parsed to datetimes and numeric columns cast to ``float``.
    The caller's DataFrame is never touched.  Only columns present in the
    input are carried forward — a missing canonical column does not cause
    a crash.
    """
    _require_usable_frame(df)
    available = [col for col in REQUIRED_COLUMNS if col in df.columns]
    work = df[available].copy()
    if "date" in work.columns:
        work["date"] = _parse_date_column(work["date"])
    for column in sorted(NUMERIC_COLUMNS & set(work.columns)):
        values = work[column].astype(float)
        if not bool(np.isfinite(values.to_numpy()).all()):
            raise DataValidationError(
                f"Column '{column}' contains non-finite values (NaN or infinity)"
            )
        work[column] = values
    return work


def _normalize_units_column(series: pd.Series) -> pd.Series:
    """Return unit sums as ``int64`` when integral, else rounded floats."""
    if not pd.api.types.is_float_dtype(series):
        return series
    try:
        if bool((series % 1 == 0).all()):
            return series.astype("int64")
    except (ValueError, TypeError, OverflowError):  # pragma: no cover
        return series.round(ROUNDING_DECIMALS)
    return series.round(ROUNDING_DECIMALS)


def _aggregate_by(work: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Aggregate sums and lead-time means grouped by ``keys``.

    Only columns that actually exist in *work* are aggregated.  Missing
    canonical numeric columns are silently skipped so the function works
    with partial schemas.
    """
    aggs: dict[str, tuple[str, str]] = {}
    if "units_sold" in work.columns:
        aggs["units_sold"] = ("units_sold", "sum")
    if "revenue" in work.columns:
        aggs["revenue"] = ("revenue", "sum")
    if "cost" in work.columns:
        aggs["cost"] = ("cost", "sum")
    if "lead_time_days" in work.columns:
        aggs["average_lead_time_days"] = ("lead_time_days", "mean")
    grouped = work.groupby(keys, sort=False, observed=True).agg(**aggs)
    return grouped.reset_index()


def _add_profit_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Add ``profit`` and ``profit_margin_pct`` columns to an aggregate frame.

    Profit is only computed when both ``revenue`` and ``cost`` columns
    exist **and** their combined total is non-zero.  When the totals are
    both zero (e.g. synthesized constants) the columns are omitted so
    downstream consumers never see meaningless profit values.
    """
    if "revenue" not in frame.columns or "cost" not in frame.columns:
        return frame
    total_revenue = float(frame["revenue"].sum())
    total_cost = float(frame["cost"].sum())
    if total_revenue == 0.0 and total_cost == 0.0:
        return frame
    frame["profit"] = frame["revenue"] - frame["cost"]
    frame["profit_margin_pct"] = [
        _round(_safe_ratio(profit, revenue) * 100.0)
        for profit, revenue in zip(frame["profit"], frame["revenue"], strict=True)
    ]
    return frame


def _performance_by_dimension(work: pd.DataFrame, dimension: str) -> pd.DataFrame:
    """Build the shared region/product performance table.

    Sorted deterministically by the first available numeric metric
    descending then entity name ascending.  Share percentages compare
    each group against the totals of the whole dataset; zero totals
    yield ``0.0`` shares.  Only columns that exist in the aggregated
    frame are included in the output.
    """
    frame = _aggregate_by(work, [dimension])
    frame = _add_profit_columns(frame)

    # Determine the primary sort metric (first available numeric column).
    _available_metrics = [
        c for c in ("revenue", "units_sold", "cost", "average_lead_time_days")
        if c in frame.columns
    ]
    sort_metric = _available_metrics[0] if _available_metrics else dimension

    # Compute share percentages for available metrics.
    _share_names = {"revenue": "revenue_share_pct", "units_sold": "units_share_pct"}
    for metric, share_col in _share_names.items():
        if metric in frame.columns:
            total = float(work[metric].sum()) if metric in work.columns else 0.0
            frame[share_col] = [
                _round(_safe_ratio(val, total) * 100.0)
                for val in frame[metric]
            ]

    # Round and normalize available columns.
    if "average_lead_time_days" in frame.columns:
        frame["average_lead_time_days"] = frame["average_lead_time_days"].map(_round)
    if "revenue" in frame.columns:
        frame["revenue"] = frame["revenue"].map(_round)
    if "cost" in frame.columns:
        frame["cost"] = frame["cost"].map(_round)
    if "profit" in frame.columns:
        frame["profit"] = frame["profit"].map(_round)
    if "units_sold" in frame.columns:
        frame["units_sold"] = _normalize_units_column(frame["units_sold"])

    frame = frame.sort_values(
        [sort_metric, dimension], ascending=[False, True], kind="stable"
    ).reset_index(drop=True)

    # Build output columns in a stable order.
    out_cols = [dimension]
    for col in (
        "units_sold", "revenue", "cost", "profit", "profit_margin_pct",
        "average_lead_time_days", "revenue_share_pct", "units_share_pct",
    ):
        if col in frame.columns:
            out_cols.append(col)
    return frame[out_cols]


def _period_summary(work: pd.DataFrame) -> tuple[dict[str, object], dict[str, float]]:
    """Summarize one slice of the working copy into a period dictionary.

    Returns ``(presentation, raw)`` where ``presentation`` holds the
    rounded output values and ``raw`` holds the unrounded aggregates used
    for percentage-change calculations.  Only columns that exist in the
    working copy are included.
    """
    dates = pd.DatetimeIndex(sorted(work["date"].unique()))
    presentation: dict[str, object] = {
        "start": dates.min().strftime("%Y-%m-%d"),
        "end": dates.max().strftime("%Y-%m-%d"),
    }
    raw: dict[str, float] = {}

    if "units_sold" in work.columns:
        total_units = float(work["units_sold"].sum())
        presentation["units_sold"] = _as_count(total_units)
        raw["units_sold"] = total_units

    if "revenue" in work.columns:
        total_revenue = float(work["revenue"].sum())
        presentation["revenue"] = _round(total_revenue)
        raw["revenue"] = total_revenue

    if "cost" in work.columns:
        total_cost = float(work["cost"].sum())
        presentation["cost"] = _round(total_cost)
        raw["cost"] = total_cost

    if "revenue" in raw and "cost" in raw:
        profit = raw["revenue"] - raw["cost"]
        if raw["revenue"] != 0.0 or raw["cost"] != 0.0:
            presentation["profit"] = _round(profit)
            presentation["profit_margin_pct"] = _round(
                _safe_ratio(profit, raw["revenue"]) * 100.0
            )
            raw["profit"] = profit
            raw["profit_margin_pct"] = _safe_ratio(profit, raw["revenue"]) * 100.0

    if "lead_time_days" in work.columns:
        average_lead_time = float(work["lead_time_days"].mean())
        presentation["average_lead_time_days"] = _round(average_lead_time)
        raw["average_lead_time_days"] = average_lead_time

    return presentation, raw


# --- Public API -------------------------------------------------------------


def _build_metric_metadata(work: pd.DataFrame) -> dict[str, dict[str, object]]:
    """Build per-metric metadata for the frontend.

    For each canonical numeric metric that exists in *work*, reports:
    * ``real`` – ``True`` when the column contains non-zero variance
      (i.e. at least one value differs from the rest);
    * ``synthesized`` – ``True`` when all values are identical (typically
      zero-filled by the schema adapter);
    * ``direction`` – ``"higher_is_better"`` or ``"lower_is_better"``.
    """
    metadata: dict[str, dict[str, object]] = {}
    for metric in ("units_sold", "revenue", "cost", "lead_time_days"):
        if metric not in work.columns:
            continue
        series = work[metric]
        has_variance = bool(series.nunique(dropna=True) > 1)
        metadata[metric] = {
            "real": has_variance,
            "synthesized": not has_variance,
            "direction": _METRIC_DIRECTION.get(metric, "higher_is_better"),
        }
    return metadata


def calculate_kpis(df: pd.DataFrame) -> dict[str, object]:
    """Calculate headline operational KPIs for a validated dataset.

    Only metrics whose columns exist in the input are computed.  A
    ``metric_metadata`` dict is included in the result so the frontend
    knows which metrics are *real* (mapped from user data) versus
    *synthesized* (filled with neutral constants), plus the preferred
    display direction for each metric.

    Args:
        df: Operational DataFrame following the canonical schema. It is
            never mutated.

    Returns:
        Dictionary with ``total_units_sold``, ``total_revenue``,
        ``total_cost``, ``total_profit``, ``profit_margin_pct``,
        ``average_daily_units_sold``, ``average_daily_revenue``,
        ``average_daily_cost``, ``average_daily_profit``,
        ``average_lead_time_days``, ``unique_regions``,
        ``unique_products``, ``date_range`` (``start``/``end`` ISO
        strings), and ``metric_metadata``.  Daily averages divide by the
        number of unique dates, not the row count.

    Raises:
        DataValidationError: If the dataset is unusable (see module policy).
    """
    work = _prepare_operational_data(df)

    unique_dates = int(work["date"].nunique())

    result: dict[str, object] = {}

    # --- numeric totals -------------------------------------------------------
    if "units_sold" in work.columns:
        total_units = float(work["units_sold"].sum())
        result["total_units_sold"] = _as_count(total_units)
        result["average_daily_units_sold"] = _round(total_units / unique_dates)

    if "revenue" in work.columns:
        total_revenue = float(work["revenue"].sum())
        result["total_revenue"] = _round(total_revenue)
        result["average_daily_revenue"] = _round(total_revenue / unique_dates)

    if "cost" in work.columns:
        total_cost = float(work["cost"].sum())
        result["total_cost"] = _round(total_cost)
        result["average_daily_cost"] = _round(total_cost / unique_dates)

    # Profit / margin only when both revenue and cost exist.
    if "revenue" in work.columns and "cost" in work.columns:
        total_revenue = float(work["revenue"].sum())
        total_cost = float(work["cost"].sum())
        total_profit = total_revenue - total_cost
        if total_revenue != 0.0 or total_cost != 0.0:
            result["total_profit"] = _round(total_profit)
            result["profit_margin_pct"] = _round(
                _safe_ratio(total_profit, total_revenue) * 100.0
            )
            result["average_daily_profit"] = _round(total_profit / unique_dates)

    if "lead_time_days" in work.columns:
        result["average_lead_time_days"] = _round(work["lead_time_days"].mean())

    # --- dimension counts -----------------------------------------------------
    if "region" in work.columns:
        result["unique_regions"] = int(work["region"].nunique())
    if "product" in work.columns:
        result["unique_products"] = int(work["product"].nunique())

    # --- date range -----------------------------------------------------------
    result["date_range"] = {
        "start": work["date"].min().strftime("%Y-%m-%d"),
        "end": work["date"].max().strftime("%Y-%m-%d"),
    }

    # --- metric metadata ------------------------------------------------------
    result["metric_metadata"] = _build_metric_metadata(work)

    return result


def calculate_region_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate performance metrics per region.

    Args:
        df: Operational DataFrame. It is never mutated.

    Returns:
        DataFrame with columns for the dimension (``region``) and any
        available numeric metrics, sorted by the first available numeric
        metric descending then region ascending.

    Raises:
        DataValidationError: If the dataset is unusable (see module policy).
    """
    work = _prepare_operational_data(df)
    return _performance_by_dimension(work, "region")


def calculate_product_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate performance metrics per product.

    Args:
        df: Operational DataFrame. It is never mutated.

    Returns:
        DataFrame with the same metric columns as
        ``calculate_region_performance`` but keyed by ``product``, sorted
        by the first available numeric metric descending then product
        ascending.

    Raises:
        DataValidationError: If the dataset is unusable (see module policy).
    """
    work = _prepare_operational_data(df)
    return _performance_by_dimension(work, "product")


def calculate_daily_trends(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily totals across all regions and products.

    Args:
        df: Operational DataFrame. It is never mutated.

    Returns:
        DataFrame with exactly one row per unique date containing
        ``date`` (ISO ``YYYY-MM-DD`` string) and any available numeric
        columns (``units_sold``, ``revenue``, ``cost``, ``profit``,
        ``profit_margin_pct``, ``average_lead_time_days``), sorted
        ascending by date regardless of the original row order.

    Raises:
        DataValidationError: If the dataset is unusable (see module policy).
    """
    work = _prepare_operational_data(df)
    frame = _aggregate_by(work, ["date"])
    frame = _add_profit_columns(frame)
    if "average_lead_time_days" in frame.columns:
        frame["average_lead_time_days"] = frame["average_lead_time_days"].map(_round)
    if "revenue" in frame.columns:
        frame["revenue"] = frame["revenue"].map(_round)
    if "cost" in frame.columns:
        frame["cost"] = frame["cost"].map(_round)
    if "profit" in frame.columns:
        frame["profit"] = frame["profit"].map(_round)
    if "units_sold" in frame.columns:
        frame["units_sold"] = _normalize_units_column(frame["units_sold"])
    frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
    frame = frame.sort_values("date", ascending=True, kind="stable").reset_index(
        drop=True
    )
    out_cols = ["date"]
    for col in (
        "units_sold", "revenue", "cost", "profit",
        "profit_margin_pct", "average_lead_time_days",
    ):
        if col in frame.columns:
            out_cols.append(col)
    return frame[out_cols]


def calculate_period_comparison(df: pd.DataFrame) -> dict[str, object]:
    """Compare the first half of the timeline against the second half.

    Periods are built from the sorted unique dates. ``period_1`` is the
    earlier half and acts as the *previous* period; ``period_2`` is the
    later half and acts as the *current* period.  When the number of
    unique dates is odd, the middle date belongs to ``period_1`` so that
    ``period_1`` always contains ``ceil(n / 2)`` dates.

    Percentage changes use ``(current - previous) / previous * 100`` and
    are computed from the unrounded aggregates so that presentation
    rounding never leaks into the change math; a zero previous value
    yields ``0.0``.  Only metrics whose columns exist are compared.

    Args:
        df: Operational DataFrame. It is never mutated.

    Returns:
        Dictionary with ``period_1`` and ``period_2`` summaries (each
        with ``start``, ``end``, and available metric keys) plus
        ``changes_pct`` containing ``*_change_pct`` for each available
        metric.

    Raises:
        DataValidationError: If the dataset is unusable or contains fewer
            than two distinct dates.
    """
    work = _prepare_operational_data(df)
    unique_dates = pd.DatetimeIndex(sorted(work["date"].unique()))
    if len(unique_dates) < 2:
        raise DataValidationError(
            "Period comparison requires at least two distinct dates"
        )

    split = (len(unique_dates) + 1) // 2
    period_1_dates = unique_dates[:split]
    period_2_dates = unique_dates[split:]

    period_1, raw_1 = _period_summary(work[work["date"].isin(period_1_dates)])
    period_2, raw_2 = _period_summary(work[work["date"].isin(period_2_dates)])

    # Build changes only for metrics present in both periods.
    _change_map: list[tuple[str, str, str]] = [
        ("units_sold", "units_change_pct", "units_sold"),
        ("revenue", "revenue_change_pct", "revenue"),
        ("cost", "cost_change_pct", "cost"),
        ("profit", "profit_change_pct", "profit"),
        ("profit_margin_pct", "margin_change_pct", "profit_margin_pct"),
        ("average_lead_time_days", "lead_time_change_pct", "average_lead_time_days"),
    ]
    changes_pct: dict[str, float] = {}
    for raw_key, change_key, _ in _change_map:
        if raw_key in raw_1 and raw_key in raw_2:
            changes_pct[change_key] = _safe_pct_change(raw_2[raw_key], raw_1[raw_key])

    return {
        "period_1": period_1,
        "period_2": period_2,
        "changes_pct": changes_pct,
    }


def _validate_limit(limit: int) -> None:
    """Raise ``DataValidationError`` for non-integer or non-positive limits."""
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise DataValidationError(
            f"limit must be a positive integer, got {type(limit).__name__}"
        )
    if limit < 1:
        raise DataValidationError(f"limit must be a positive integer, got {limit}")


def _extreme_performers(
    df: pd.DataFrame, limit: int, *, top: bool
) -> dict[str, list[dict[str, object]]]:
    """Shared implementation for top/bottom performer selection."""
    _validate_limit(limit)
    frames = {
        "regions": (calculate_region_performance(df), "region"),
        "products": (calculate_product_performance(df), "product"),
    }
    result: dict[str, list[dict[str, object]]] = {}
    for key, (frame, dimension) in frames.items():
        # Determine sort metric: first available numeric column.
        _numeric = [
            c for c in ("revenue", "units_sold", "cost", "average_lead_time_days")
            if c in frame.columns
        ]
        sort_col = _numeric[0] if _numeric else dimension
        ordered = frame.sort_values(
            [sort_col, dimension], ascending=[not top, True], kind="stable"
        ).head(limit)
        records = [
            {str(column): _to_python(value) for column, value in row.items()}
            for row in ordered.to_dict(orient="records")
        ]
        for rank, record in enumerate(records, start=1):
            record["rank"] = rank
        result[key] = records
    return result


def calculate_top_performers(
    df: pd.DataFrame, limit: int = DEFAULT_PERFORMER_LIMIT
) -> dict[str, list[dict[str, object]]]:
    """Identify the strongest regions and products by revenue.

    Args:
        df: Operational DataFrame. It is never mutated.
        limit: Maximum number of entries per category (default 5). Fewer
            entries are returned when fewer entities exist.

    Returns:
        Dictionary with ``regions`` and ``products`` keys; each holds a
        ranked list of performance records sorted by revenue descending
        (ties broken by name ascending).

    Raises:
        DataValidationError: If the dataset is unusable or ``limit`` is
            not a positive integer.
    """
    return _extreme_performers(df, limit, top=True)


def calculate_bottom_performers(
    df: pd.DataFrame, limit: int = DEFAULT_PERFORMER_LIMIT
) -> dict[str, list[dict[str, object]]]:
    """Identify the weakest regions and products by revenue.

    Args:
        df: Operational DataFrame. It is never mutated.
        limit: Maximum number of entries per category (default 5). Fewer
            entries are returned when fewer entities exist.

    Returns:
        Dictionary with ``regions`` and ``products`` keys; each holds a
        ranked list of performance records sorted by revenue ascending
        (ties broken by name ascending).

    Raises:
        DataValidationError: If the dataset is unusable or ``limit`` is
            not a positive integer.
    """
    return _extreme_performers(df, limit, top=False)
