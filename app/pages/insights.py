"""Insights page — the intelligence feed (Phase 11B).

Correlational factor explanations and grouped issues, presented as a
filterable feed with per-insight detail. Functional contract unchanged
from Phase 8/10A: insights, factors and localization verdicts come
straight from stored artifacts; nothing here re-ranks or re-scores.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from app.state import require_artifacts, run_page  # noqa: E402
from app.ui.components import (  # noqa: E402
    badge,
    chips_row,
    empty_state,
    metric_row,
    section,
    severity_badge,
    strength_meter,
)
from app.ui.icons import escape_label  # noqa: E402

CORRELATION_NOTE = (
    "These explanations are **correlational evidence derived from rules**, "
    "never causal claims. The engine ranks numeric factors; it does not prove "
    "why something happened."
)

_DIRECTION_TONE = {"up": "success", "down": "danger", "increase": "success",
                   "decrease": "danger"}


def _insight_card(insight: dict) -> None:
    title = insight.get("headline") or f"{insight.get('metric')} anomaly"
    scope_bits = [str(insight.get(k)) for k in ("scope", "entity", "date")
                  if insight.get(k)]
    header_bits = [badge(bit, "muted") for bit in scope_bits if bit != "None"]
    with st.container(border=True):
        chips_row([severity_badge(insight.get("severity")),
                   badge(title, "accent"), *header_bits])
        factors = insight.get("factors") or []
        if not factors:
            st.caption("No ranked factors for this insight.")
        else:
            for factor in factors[:6]:
                direction = str(factor.get("direction") or "").lower()
                tone = _DIRECTION_TONE.get(direction, "info")
                try:
                    strength = float(factor.get("strength", 0.0))
                except (TypeError, ValueError):
                    strength = 0.0
                st.markdown(
                    "<div style='margin:6px 0'>"
                    "<div style='display:flex;justify-content:space-between;gap:10px;"
                    "align-items:center;margin-bottom:3px'>"
                    f"<span style='font-size:.85rem'>{escape_label(factor.get('factor'))}</span>"
                    f"{badge(str(factor.get('direction') or '—'), tone)}"
                    "</div>"
                    f"{strength_meter(strength, maximum=1.0)}",
                    unsafe_allow_html=True,
                )
                evidence = factor.get("evidence")
                if evidence:
                    st.caption(f"Evidence: {evidence}")
                st.markdown("</div>", unsafe_allow_html=True)


def _insight_detail(insight: dict) -> None:
    """Expandable detail: every ranked factor plus localization verdict."""
    st.markdown("**All ranked contributing factors**")
    factors = insight.get("factors") or []
    if not factors:
        st.caption("No factors recorded for this insight.")
    else:
        rows = [
            {
                "factor": factor.get("factor"),
                "direction": factor.get("direction"),
                "strength": factor.get("strength"),
                "evidence": factor.get("evidence"),
            }
            for factor in factors
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
    localization = insight.get("localization")
    if localization:
        chips_row([
            badge("Localization", "ai"),
            badge(f"dimension · {localization.get('dimension')}", "muted"),
            badge(f"verdict · {localization.get('verdict')}", "info"),
            *([
                badge(f"{k} · {localization[k]}", "muted")
                for k in sorted(localization)
                if k not in {"dimension", "verdict"} and localization.get(k) is not None
            ]),
        ])
    st.caption(
        "Correlational by design: factor strength reflects how strongly a "
        "numeric factor moved with the detected signal — not a causal claim."
    )


def render_insights() -> None:
    artifacts = require_artifacts()
    if artifacts is None:
        return

    st.info(CORRELATION_NOTE, icon=":material/info:")
    insights = artifacts.insights

    section("Signal summary", icon="lightbulb")
    metric_row([
        dict(label="Insights", value=len(insights), icon="lightbulb"),
        dict(label="Anomalies explained", value=len(artifacts.anomalies),
             icon="crisis_alert"),
        dict(label="Grouped issues", value=len(artifacts.groups), icon="layers"),
    ], columns=4)

    if not insights:
        empty_state("lightbulb", "No insights available",
                    "The rule engine produced no ranked explanations for the "
                    "current analysis.")
    else:
        section("Intelligence feed", icon="star",
                caption="Filter by severity or search headlines and factors")
        f1, f2 = st.columns([1.2, 2])
        severities = f1.multiselect(
            "Severity", ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
            default=[s for s in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
                     if s in {i.get("severity") for i in insights}],
        )
        search = f2.text_input("Search",
                               placeholder="headline, metric, entity…")

        def _matches(insight: dict) -> bool:
            if severities and insight.get("severity") not in severities:
                return False
            if not search:
                return True
            needle = search.lower()
            haystacks = [
                insight.get("headline"), insight.get("metric"),
                insight.get("entity"), insight.get("scope"),
                *(factor.get("factor") for factor in (insight.get("factors") or [])),
            ]
            return any(needle in str(value or "").lower() for value in haystacks)

        shown = 0
        for position, insight in enumerate(insights):
            if not _matches(insight):
                continue
            shown += 1
            with st.container(border=True):
                _insight_card(insight)
                with st.expander("Insight detail"):
                    _insight_detail(insight)
        if shown == 0:
            st.caption("No insights match the current filters.")
        elif shown < len(insights):
            st.caption(f"Showing {shown} of {len(insights)} insights.")

    grouping = artifacts.grouping
    section("Grouped operational issues", icon="layers",
            caption=(f"{grouping['ungrouped_count']} anomalies are standalone"
                     if grouping.get("ungrouped_count") else None))
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
    st.dataframe(rows, width="stretch", hide_index=True)


run_page("Insights", "Rule-derived explanations of the detected anomalies — "
         "correlational by design", render_insights,
         icon="lightbulb", eyebrow="Intelligence")
