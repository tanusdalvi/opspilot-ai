"""Deterministic analytical tool registry for OpsPilot AI.

Exposes composable analytical functions as named tools.  The investigation
planner selects a subset of these based on the user's question and the
dataset's capability profile.  Every tool is pure-deterministic: same input
always produces the same output, no randomness, no wall-clock time.

Architecture
------------
question → planner → selected tools → evidence → grounding → narrative
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from core.constants import SEVERITY_LOW, SEVERITY_MEDIUM, SEVERITY_HIGH, SEVERITY_CRITICAL


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Tool:
    """A single analytical tool exposed to the investigation planner."""

    name: str
    description: str
    required_columns: frozenset[str]
    category: str  # "summary", "trend", "comparison", "anomaly", "segment"
    # Callable: (df, **kwargs) -> dict[str, Any]
    fn: Callable[..., dict[str, Any]] = field(repr=False)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _get_sales_summary(df: pd.DataFrame, **_kw: Any) -> dict[str, Any]:
    """Compute aggregate sales metrics from the active dataset."""
    result: dict[str, Any] = {"metrics": {}}
    for col in ("units_sold", "revenue", "cost"):
        if col in df.columns:
            total = float(df[col].sum())
            mean = float(df[col].mean())
            result["metrics"][col] = {
                "total": round(total, 2),
                "daily_average": round(mean, 2),
                "min": round(float(df[col].min()), 2),
                "max": round(float(df[col].max()), 2),
            }
    if "revenue" in df.columns and "cost" in df.columns:
        total_rev = float(df["revenue"].sum())
        total_cost = float(df["cost"].sum())
        if total_rev > 0:
            result["metrics"]["profit_margin_pct"] = round(
                (1 - total_cost / total_rev) * 100, 2
            )
    if "lead_time_days" in df.columns:
        result["metrics"]["lead_time_days"] = {
            "average": round(float(df["lead_time_days"].mean()), 2),
            "median": round(float(df["lead_time_days"].median()), 2),
            "max": round(float(df["lead_time_days"].max()), 2),
            "p95": round(float(df["lead_time_days"].quantile(0.95)), 2),
        }
    return result


def _get_product_performance(df: pd.DataFrame, **_kw: Any) -> dict[str, Any]:
    """Break down metrics by product."""
    if "product" not in df.columns:
        return {"error": "No product column in dataset"}
    products = []
    for product, grp in df.groupby("product"):
        entry: dict[str, Any] = {"product": str(product)}
        for col in ("units_sold", "revenue", "cost", "lead_time_days"):
            if col in grp.columns:
                entry[col] = {
                    "total": round(float(grp[col].sum()), 2),
                    "average": round(float(grp[col].mean()), 2),
                }
        if "revenue" in grp.columns and "cost" in grp.columns:
            rev = float(grp["revenue"].sum())
            cost = float(grp["cost"].sum())
            entry["profit_margin_pct"] = round((1 - cost / rev) * 100, 2) if rev > 0 else 0
        products.append(entry)
    return {"products": products}


def _get_region_performance(df: pd.DataFrame, **_kw: Any) -> dict[str, Any]:
    """Break down metrics by region."""
    if "region" not in df.columns:
        return {"error": "No region column in dataset"}
    regions = []
    for region, grp in df.groupby("region"):
        entry: dict[str, Any] = {"region": str(region)}
        for col in ("units_sold", "revenue", "cost", "lead_time_days"):
            if col in grp.columns:
                entry[col] = {
                    "total": round(float(grp[col].sum()), 2),
                    "average": round(float(grp[col].mean()), 2),
                }
        regions.append(entry)
    return {"regions": regions}


def _get_period_comparison(df: pd.DataFrame, **_kw: Any) -> dict[str, Any]:
    """Compare first half vs second half of the date range."""
    if "date" not in df.columns:
        return {"error": "No date column in dataset"}
    dates = pd.to_datetime(df["date"])
    midpoint = dates.min() + (dates.max() - dates.min()) / 2
    p1 = df[dates <= midpoint]
    p2 = df[dates > midpoint]
    changes: dict[str, Any] = {}
    for col in ("units_sold", "revenue", "cost", "lead_time_days"):
        if col in df.columns:
            v1 = float(p1[col].sum()) if len(p1) > 0 else 0
            v2 = float(p2[col].sum()) if len(p2) > 0 else 0
            changes[col] = {
                "period_1_total": round(v1, 2),
                "period_2_total": round(v2, 2),
                "change_pct": round((v2 - v1) / v1 * 100, 2) if v1 != 0 else None,
            }
    return {"period_1_range": f"{dates.min().date()} to {midpoint.date()}",
            "period_2_range": f"{midpoint.date()} to {dates.max().date()}",
            "changes": changes}


def _detect_anomalies(df: pd.DataFrame, **_kw: Any) -> dict[str, Any]:
    """Run z-score anomaly detection on available metrics."""
    from services.anomaly_service import detect_anomalies
    from services.analytics_service import _prepare_operational_data
    sensitivity = _kw.get("sensitivity", "medium")

    work_df = _prepare_operational_data(df)
    try:
        result = detect_anomalies(work_df, sensitivity=sensitivity)
    except Exception:
        return {"total_anomalies": 0, "metrics_analyzed": [], "anomalies": []}
    return {
        "total_anomalies": result.get("total_count", 0),
        "by_severity": result.get("by_severity", {}),
        "metrics_analyzed": result.get("metrics_analyzed", []),
        "anomalies": result.get("anomalies", [])[:20],
    }


def _get_trend_analysis(df: pd.DataFrame, **_kw: Any) -> dict[str, Any]:
    """Compute simple trend (direction + magnitude) for each metric."""
    if "date" not in df.columns:
        return {"error": "No date column in dataset"}
    work = df.copy()
    work["_date"] = pd.to_datetime(work["date"])
    work = work.sort_values("_date")
    trends: dict[str, Any] = {}
    for col in ("units_sold", "revenue", "cost", "lead_time_days"):
        if col not in work.columns:
            continue
        daily = work.groupby("_date")[col].sum().reset_index()
        if len(daily) < 10:
            continue
        first_half = daily.iloc[: len(daily) // 2][col].mean()
        second_half = daily.iloc[len(daily) // 2 :][col].mean()
        change_pct = ((second_half - first_half) / first_half * 100) if first_half != 0 else 0
        trends[col] = {
            "first_half_average": round(float(first_half), 2),
            "second_half_average": round(float(second_half), 2),
            "change_pct": round(float(change_pct), 2),
            "direction": "increasing" if change_pct > 5 else ("decreasing" if change_pct < -5 else "stable"),
        }
    return {"trends": trends}


def _get_cost_ratio_analysis(df: pd.DataFrame, **_kw: Any) -> dict[str, Any]:
    """Analyze cost-to-revenue ratio trends."""
    if "revenue" not in df.columns or "cost" not in df.columns:
        return {"error": "Need both revenue and cost columns"}
    if "date" not in df.columns:
        return {"error": "No date column in dataset"}
    work = df.copy()
    work["_date"] = pd.to_datetime(work["date"])
    daily = work.groupby("_date").agg({"revenue": "sum", "cost": "sum"}).reset_index()
    daily["ratio"] = daily["cost"] / daily["revenue"].replace(0, float("nan"))
    daily = daily.dropna()
    if len(daily) < 10:
        return {"error": "Insufficient data"}
    first_half = daily.iloc[: len(daily) // 2]["ratio"].mean()
    second_half = daily.iloc[len(daily) // 2 :]["ratio"].mean()
    return {
        "first_half_cost_ratio": round(float(first_half) * 100, 2),
        "second_half_cost_ratio": round(float(second_half) * 100, 2),
        "change_pct_points": round(float((second_half - first_half) * 100), 2),
        "trend": "worsening" if second_half > first_half * 1.05 else (
            "improving" if second_half < first_half * 0.95 else "stable"
        ),
    }


def _get_lead_time_analysis(df: pd.DataFrame, **_kw: Any) -> dict[str, Any]:
    """Analyze lead time trends and distribution."""
    if "lead_time_days" not in df.columns:
        return {"error": "No lead_time_days column in dataset"}
    work = df.copy()
    if "date" in work.columns:
        work["_date"] = pd.to_datetime(work["date"])
        work = work.sort_values("_date")
        mid = len(work) // 2
        first_half = work.iloc[:mid]["lead_time_days"]
        second_half = work.iloc[mid:]["lead_time_days"]
    else:
        n = len(work)
        first_half = work["lead_time_days"].iloc[: n // 2]
        second_half = work["lead_time_days"].iloc[n // 2 :]

    result: dict[str, Any] = {
        "overall": {
            "mean": round(float(work["lead_time_days"].mean()), 2),
            "median": round(float(work["lead_time_days"].median()), 2),
            "p95": round(float(work["lead_time_days"].quantile(0.95)), 2),
            "max": int(work["lead_time_days"].max()),
        },
        "trend": {
            "first_half_mean": round(float(first_half.mean()), 2),
            "second_half_mean": round(float(second_half.mean()), 2),
            "change_pct": round(
                float((second_half.mean() - first_half.mean()) / first_half.mean() * 100), 2
            ) if first_half.mean() != 0 else 0,
        },
    }
    # Breakdown by region if available
    if "region" in work.columns:
        result["by_region"] = {}
        for region, grp in work.groupby("region"):
            result["by_region"][str(region)] = {
                "mean": round(float(grp["lead_time_days"].mean()), 2),
                "max": int(grp["lead_time_days"].max()),
            }
    if "product" in work.columns:
        result["by_product"] = {}
        for product, grp in work.groupby("product"):
            result["by_product"][str(product)] = {
                "mean": round(float(grp["lead_time_days"].mean()), 2),
                "max": int(grp["lead_time_days"].max()),
            }
    return result


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_TOOLS: list[Tool] = [
    Tool(
        name="get_sales_summary",
        description="Aggregate sales metrics: total units sold, revenue, cost, profit margin, lead time averages.",
        required_columns=frozenset(),
        category="summary",
        fn=_get_sales_summary,
    ),
    Tool(
        name="get_product_performance",
        description="Break down sales, revenue, cost, and lead time by product. Identifies which products are underperforming.",
        required_columns=frozenset({"product"}),
        category="segment",
        fn=_get_product_performance,
    ),
    Tool(
        name="get_region_performance",
        description="Break down sales, revenue, cost, and lead time by geographic region.",
        required_columns=frozenset({"region"}),
        category="segment",
        fn=_get_region_performance,
    ),
    Tool(
        name="get_period_comparison",
        description="Compare first half vs second half of the dataset date range. Shows period-over-period changes.",
        required_columns=frozenset({"date"}),
        category="comparison",
        fn=_get_period_comparison,
    ),
    Tool(
        name="detect_anomalies",
        description="Run statistical anomaly detection (z-score) on numeric metrics. Flags unusual spikes and drops.",
        required_columns=frozenset(),
        category="anomaly",
        fn=_detect_anomalies,
    ),
    Tool(
        name="get_trend_analysis",
        description="Compute trend direction and magnitude for each metric. Identifies increasing, decreasing, or stable trends.",
        required_columns=frozenset({"date"}),
        category="trend",
        fn=_get_trend_analysis,
    ),
    Tool(
        name="get_cost_ratio_analysis",
        description="Analyze cost-to-revenue ratio trends. Detects margin compression or improvement.",
        required_columns=frozenset({"revenue", "cost"}),
        category="trend",
        fn=_get_cost_ratio_analysis,
    ),
    Tool(
        name="get_lead_time_analysis",
        description="Analyze lead time trends, distribution, and breakdown by region/product. Detects fulfillment pressure.",
        required_columns=frozenset({"lead_time_days"}),
        category="trend",
        fn=_get_lead_time_analysis,
    ),
]


def get_available_tools(df: pd.DataFrame) -> list[Tool]:
    """Return tools whose required_columns are all present in the DataFrame."""
    cols = set(df.columns)
    return [t for t in ALL_TOOLS if t.required_columns.issubset(cols)]


def execute_tool(tool: Tool, df: pd.DataFrame, **kwargs: Any) -> dict[str, Any]:
    """Execute a single tool against the DataFrame."""
    try:
        return tool.fn(df, **kwargs)
    except Exception as exc:
        return {"error": f"{tool.name} failed: {type(exc).__name__}: {exc}"}


def execute_tools(
    tool_names: list[str],
    df: pd.DataFrame,
    **kwargs: Any,
) -> dict[str, dict[str, Any]]:
    """Execute multiple tools and return a dict keyed by tool name."""
    available = {t.name: t for t in get_available_tools(df)}
    results: dict[str, dict[str, Any]] = {}
    for name in tool_names:
        tool = available.get(name)
        if tool is None:
            results[name] = {"error": f"Tool '{name}' not available for this dataset"}
        else:
            results[name] = execute_tool(tool, df, **kwargs)
    return results
