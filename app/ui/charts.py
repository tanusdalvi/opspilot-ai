"""Altair chart builders with the OpsPilot dark theme (Phase 11).

All charts share one visual language: transparent backgrounds, subtle
grids, muted axis labels, the electric blue/indigo accent family, and
semantic colors for good/bad deltas. Builders are pure functions from
data to ``alt.Chart``; pages own layout.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

from app.ui.theme import (
    ACCENT,
    ACCENT_2,
    DANGER,
    INFO,
    SUCCESS,
    TEXT_2,
    WARNING,
)

_AXIS = alt.Axis(labelColor=TEXT_2, titleColor=TEXT_2, gridColor="rgba(148,163,184,.12)",
                 domainColor="rgba(148,163,184,.25)", labelFontSize=11, titleFontSize=11)
_LEGEND = alt.Legend(labelColor=TEXT_2, titleColor=TEXT_2, labelFontSize=11)


def _configure(chart: alt.Chart) -> alt.Chart:
    """Shared chart finishing: transparent background and no chrome.

    ``actions: False`` suppresses Vega-Embed's hover action bar (the
    floating "Open in Vega Editor / Save as SVG / PNG" menu), which read
    as stray ``svg`` labels next to every visualization; tooltips stay
    enabled. Passed via ``usermeta`` so it reaches vega-embed regardless
    of the Streamlit wrapper.
    """
    return chart.properties(
        background="transparent",
        usermeta={"embedOptions": {"actions": False}},
    )


def area_trends(trends: pd.DataFrame, date_col: str,
                value_cols: list[str], height: int = 280) -> alt.Chart:
    """Smooth gradient area chart for daily metric trends."""
    labels = {
        "revenue": "Revenue",
        "profit": "Profit",
        "units_sold": "Units sold",
    }
    long = trends.melt(
        id_vars=[date_col], value_vars=[c for c in value_cols if c in trends.columns],
        var_name="metric", value_name="value",
    )
    if long.empty:
        long = pd.DataFrame({date_col: [], "metric": [], "value": []})
    long["metric"] = long["metric"].map(lambda m: labels.get(m, m))
    base = alt.Chart(long).encode(
        x=alt.X(f"{date_col}:T", axis=_AXIS, title=None),
        y=alt.Y("value:Q", axis=_AXIS, title=None),
        color=alt.Color("metric:N", legend=_LEGEND, title=None,
                        scale=alt.Scale(domain=list(labels.values()),
                                        range=[ACCENT, SUCCESS, INFO])),
        tooltip=[alt.Tooltip(f"{date_col}:T", title="Date"),
                 alt.Tooltip("metric:N", title="Metric"),
                 alt.Tooltip("value:Q", title="Value", format=",.0f")],
    )
    areas = base.mark_area(interpolate="monotone", opacity=.16, line=True)
    return _configure(areas.properties(height=height))


def hbar_counts(counts: dict[str, int] | dict[str, float], height: int = 220,
                accent: str = ACCENT) -> alt.Chart:
    """Horizontal bars for a name -> count mapping (sorted descending)."""
    data = pd.DataFrame(
        {"value": [str(k) for k in counts], "count": [float(v) for v in counts.values()]}
    ).sort_values("count", ascending=False)
    if data.empty:
        data = pd.DataFrame({"value": [], "count": []})
    chart = alt.Chart(data).encode(
        x=alt.X("count:Q", axis=_AXIS, title=None),
        y=alt.Y("value:N", sort="-x", axis=_AXIS, title=None),
        tooltip=[alt.Tooltip("value:N", title="Value"),
                 alt.Tooltip("count:Q", title="Count", format=",.0f")],
    )
    bars = chart.mark_bar(cornerRadius=4, height=14).encode(
        color=alt.value(accent),
    )
    return _configure(bars.properties(height=height))


def performance_bars(frame: pd.DataFrame, dimension_col: str, value_col: str,
                     title_y: str | None = None, height: int = 300) -> alt.Chart:
    """Horizontal bars for region/product performance frames."""
    data = frame[[dimension_col, value_col]].copy()
    data[dimension_col] = data[dimension_col].astype(str)
    data = data.sort_values(value_col, ascending=False)
    if data.empty:
        data = pd.DataFrame({dimension_col: [], value_col: []})
    chart = alt.Chart(data).encode(
        x=alt.X(f"{value_col}:Q", axis=_AXIS, title=None),
        y=alt.Y(f"{dimension_col}:N", sort="-x", axis=_AXIS, title=title_y),
        tooltip=[
            alt.Tooltip(f"{dimension_col}:N", title=title_y or "Dimension"),
            alt.Tooltip(f"{value_col}:Q", title="Value", format=",.1f"),
        ],
    )
    bars = chart.mark_bar(cornerRadius=4).encode(
        color=alt.Color(f"{value_col}:Q", legend=None,
                        scale=alt.Scale(range=[ACCENT_2, ACCENT, INFO])),
    )
    return _configure(bars.properties(height=height))


def diverging_pct(changes: dict[str, float | None], height: int = 240) -> alt.Chart:
    """Diverging bars for period-over-period percentage changes.

    Lead time is rendered in amber (its impact is context-dependent);
    every other metric uses green for increases and red for decreases.
    """
    def _label(key: str) -> str:
        return str(key).replace("_change_pct", "").replace("_", " ").title()

    rows = [
        {"metric": _label(key),
         "pct": None if value is None else round(float(value), 1)}
        for key, value in sorted(changes.items())
    ]
    data = pd.DataFrame(rows, columns=["metric", "pct"])
    data["tone"] = [
        TEXT_2 if p is None or p != p  # None / NaN -> neutral
        else (WARNING if m == "Lead time" else (SUCCESS if p >= 0 else DANGER))
        for m, p in zip(data["metric"], data["pct"])
    ]

    chart = alt.Chart(data).encode(
        x=alt.X("pct:Q", axis=_AXIS, title=None),
        y=alt.Y("metric:N", sort=list(data["metric"]), axis=_AXIS, title=None),
        tooltip=[alt.Tooltip("metric:N", title="Metric"),
                 alt.Tooltip("pct:Q", title="Change %", format="+.1f")],
    )
    bars = chart.mark_bar(cornerRadius=3, height=15).encode(
        color=alt.Color("tone:N", legend=None, scale=None),
    )
    rule = alt.Chart(pd.DataFrame({"zero": [0]})).mark_rule(
        color="rgba(148,163,184,.35)"
    ).encode(x=alt.X("zero:Q"))
    return _configure((bars + rule).properties(height=height))
