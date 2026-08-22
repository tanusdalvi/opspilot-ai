"""Insights page — correlational factor explanations and grouped issues (Phase 8)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.state import require_artifacts, run_page  # noqa: E402

CORRELATION_NOTE = (
    "These explanations are **correlational evidence derived from rules**, "
    "never causal claims. The engine ranks numeric factors; it does not prove "
    "why something happened."
)


def render_insights() -> None:
    artifacts = require_artifacts()
    if artifacts is None:
        return

    insights = artifacts.insights
    st.info(CORRELATION_NOTE)
    c = st.columns(3)
    c[0].metric("Insights", len(insights))
    c[1].metric("Anomalies explained", len(artifacts.anomalies))
    c[2].metric("Grouped issues", len(artifacts.groups))

    st.subheader("Top insights")
    for insight in insights[:10]:
        title = insight.get("headline") or f"{insight.get('metric')} anomaly"
        scope_bits = [str(insight.get(k)) for k in ("scope", "entity", "date")
                      if insight.get(k)]
        with st.expander(f"{insight.get('severity', '')} · {title}"
                         + (f" · {' / '.join(b for b in scope_bits if b != 'None')}"
                            if scope_bits else "")):
            factors = insight.get("factors") or []
            if factors:
                rows = [
                    {
                        "factor": f.get("factor"),
                        "direction": f.get("direction"),
                        "strength": round(float(f.get("strength", 0.0)), 2),
                        "evidence": f.get("evidence"),
                    }
                    for f in factors[:6]
                ]
                st.dataframe(rows, use_container_width=True)
            else:
                st.caption("No ranked factors for this insight.")
            localization = insight.get("localization")
            if localization:
                st.markdown(
                    f"Localization: dimension **{localization.get('dimension')}**, "
                    f"verdict **{localization.get('verdict')}**"
                )

    st.divider()
    st.subheader("Grouped operational issues")
    grouping = artifacts.grouping
    if grouping.get("ungrouped_count"):
        st.caption(f"{grouping['ungrouped_count']} anomalies are standalone.")
    groups = grouping["groups"]
    if not groups:
        st.caption("No simultaneous multi-anomaly clusters detected.")
        return
    rows = [
        {
            "group": g.get("group_id"),
            "severity": g.get("severity"),
            "members": g.get("member_count"),
            "max score": g.get("max_score"),
            "window": f"{g.get('start_date')} → {g.get('end_date')}",
            "shared metrics": ", ".join(g.get("shared_metrics") or []),
        }
        for g in groups[:15]
    ]
    st.dataframe(rows, use_container_width=True)


run_page("Insights", "Rule-derived explanations of the detected anomalies — "
         "correlational by design", render_insights)
