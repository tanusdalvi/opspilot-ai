"""Recommendations page — the decision-intelligence workspace (Phase 11B).

Deterministic plan display with explainable scoring, a "why this
recommendation exists" narrative composed from provenance fields, and
one-click routing into the Human Review console. Functional contract
unchanged from Phase 8/9: plan generation goes through the
orchestrator; persistence is append-only and at most once per plan via
``should_record_plan``.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from app import orchestrator  # noqa: E402
from app.state import get_engine, require_artifacts, run_page  # noqa: E402
from app.ui.charts import hbar_counts  # noqa: E402
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
from app.ui.theme import severity_color  # noqa: E402

STATUS_BADGE = {
    "PENDING": ("warning", "PENDING"),
    "APPROVED": ("success", "APPROVED"),
    "REJECTED": ("danger", "REJECTED"),
    "CHANGES_REQUESTED": ("info", "CHANGES_REQUESTED"),
}


def _status_badge(status: object) -> str:
    tone, text = STATUS_BADGE.get(str(status), ("muted", str(status)))
    return badge(text, tone)


def _score_meter(value: float, label: str, color: str | None = None) -> str:
    """0-100 score bar with tabular readout (presentation only)."""
    pct = max(0.0, min(100.0, float(value)))
    fill = f"background:{color};" if color else ""
    return (
        "<div style='display:flex;align-items:center;gap:8px'>"
        f"<span style='font-size:.72rem;color:var(--ops-text-3);"
        f"width:86px'>{escape_label(label)}</span>"
        "<div class='ops-meter' style='flex:1'>"
        f"<div style='width:{pct:.0f}%;{fill}'></div></div>"
        f"<span class='ops-mono' style='color:var(--ops-text-2);width:38px;"
        f"text-align:right'>{value:.0f}</span></div>"
    )


def _recommendation_card(record: dict, selected: bool) -> str:
    color = severity_color(record["priority"])
    window = record.get("date_window")
    window_text = (
        f"{window['start']} → {window['end']}"
        if isinstance(window, dict)
        else "—"
    )
    related_count = len(record.get("source_anomaly_indices") or []) + len(
        record.get("source_group_ids") or [])
    related_text = (
        f"{related_count} related signal(s)" if related_count else "no grouped signals"
    )
    score_text = badge(f"score {float(record['priority_score']):.0f}", "muted")
    target_text = badge(
        str(record.get("target_entity") or record.get("target_metric") or "—"), "muted"
    )
    border_css = "border:1.5px solid var(--ops-accent);" if selected else ""
    return (
        "<div class='ops-card ops-hover ops-sev-stripe' "
        f"style='--ops-sev:{color};{border_css}'>"
        "<div style='display:flex;justify-content:space-between;align-items:center;"
        "gap:8px;margin-bottom:6px'>"
        f"<span class='ops-mono' style='color:var(--ops-text-3)'>"
        f"{escape_label(record['recommendation_id'])}</span>"
        f"{_status_badge(record.get('status'))}</div>"
        f"<div style='font-weight:640;margin-bottom:4px'>{escape_label(record['title'])}</div>"
        "<div style='display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px'>"
        f"{severity_badge(record['priority'])}"
        f"{score_text}"
        f"{badge(str(record['action_type']), 'accent')}"
        f"{target_text}"
        "</div>"
        f"<div class='ops-card-sub'>Window · {escape_label(window_text)} · "
        f"{escape_label(related_text)}</div>"
        f"{strength_meter(float(record['evidence_strength']), maximum=100.0)}"
        "</div>"
    )


def _why_section(record: dict) -> None:
    """Compose WHY THIS RECOMMENDATION EXISTS from stored provenance."""
    st.markdown("**Why this recommendation exists**")
    factors = [
        str(factor).replace("_", " ")
        for factor in (record.get("source_factors") or [])
    ]
    narrative = (
        f"The deterministic scoring engine generated {record['recommendation_id']} "
        f"because the analyzed window contains "
        + (
            " · ".join(factors)
            if factors else "scored signals from the evidence pack"
        )
        + f". It targets **{escape_label(str(record.get('target_entity') or record.get('scope') or 'the dataset'))}**"
    )
    window = record.get("date_window")
    if isinstance(window, dict):
        narrative += f" over **{window.get('start')} → {window.get('end')}**"
    narrative += (
        f". Evidence strength is **{float(record['evidence_strength']):.0f}%** and the "
        f"priority score is **{float(record['priority_score']):.0f}/100**."
    )
    st.write(narrative)

    evidence_ids = record.get("evidence_ids") or []
    chips_row([
        badge(evidence_id, "accent") for evidence_id in evidence_ids
    ] or [badge("No explicit evidence ids attached", "muted")])

    related_count = len(record.get("source_anomaly_indices") or [])
    group_count = len(record.get("source_group_ids") or [])
    if related_count or group_count:
        chips_row([
            badge(f"{related_count} source anomalies", "info"),
            badge(f"{group_count} source groups", "info"),
        ])
    st.caption(
        "Scores are deterministic service output — never recalculated in "
        "this interface."
    )


def _show_detail(record: dict) -> None:
    with st.container(border=True):
        chips_row([
            badge(record["recommendation_id"], "accent"),
            severity_badge(record["priority"]),
            _status_badge(record.get("status")),
            badge(record["action_type"], "muted"),
            badge(f"strength {float(record['evidence_strength']):.1f}", "muted"),
        ])
        st.markdown(f"**{record['title']}**")
        st.write(record["description"])
        _why_section(record)
        col_score, col_strength = st.columns(2)
        with col_score:
            st.markdown(_score_meter(
                float(record["priority_score"]), "Priority score",
                color=severity_color(record["priority"]),
            ), unsafe_allow_html=True)
        with col_strength:
            st.markdown(strength_meter(
                float(record["evidence_strength"]), maximum=100.0,
            ), unsafe_allow_html=True)
        meta = {
            "scope": record["scope"],
            "target_entity": record.get("target_entity"),
            "target_metric": record.get("target_metric"),
            "date_window": record.get("date_window"),
            "source_factors": record.get("source_factors"),
            "source_anomaly_indices": record.get("source_anomaly_indices"),
            "source_group_ids": record.get("source_group_ids"),
            "evidence_ids": record.get("evidence_ids"),
        }
        with st.expander("Technical details"):
            st.json(meta)
        if record.get("requires_human_review") is True:
            if st.button("Open decision console", type="primary",
                         icon=":material/task_alt:", width="stretch"):
                st.session_state.selected_recommendation_id = \
                    record["recommendation_id"]
                st.switch_page("pages/review.py")
        else:
            st.info("This record does not carry the mandatory human-review flag.")


def render_recommendations() -> None:
    artifacts = require_artifacts()
    if artifacts is None:
        return

    plan = st.session_state.get("plan")
    left, right = st.columns([1, 3])
    limit = right.number_input(
        "Max recommendations (0 = service default)", min_value=0,
        value=int(st.session_state.get("plan_limit", 0)),
    )
    limit = int(limit) or None

    generate = left.button("Generate recommendations", type="primary",
                           icon=":material/route:", width="stretch")
    regenerate = left.button(
        "Regenerate (new audit record)",
        help="Creates a fresh deterministic plan and persists it as a NEW "
             "append-only audit record.",
        width="stretch",
    )

    if generate or regenerate:
        with st.spinner("Generating recommendations..."):
            plan = orchestrator.generate_plan(
                artifacts.pack,
                investigation=st.session_state.get("investigation_result"),
                max_recommendations=limit,
            )
        if regenerate or orchestrator.should_record_plan(st.session_state.get("plan_id")):
            with st.spinner("Saving audit record..."):
                engine = get_engine()
                st.session_state.plan_id = orchestrator.persist_plan(engine, plan)
        elif generate and not orchestrator.should_record_plan(st.session_state.get("plan_id")):
            st.caption("Existing active plan reused (already persisted).")
        st.session_state.plan = plan
        st.session_state.selected_recommendation_id = None

    if not plan:
        empty_state(
            "route", "No recommendations yet",
            "Recommendations appear after the deterministic analysis pipeline "
            "produces actionable signals. Generate the plan from the current "
            "evidence pack — every recommendation carries explainable scoring "
            "and requires human approval.",
            cta_label="Open Evidence pack",
            cta_page="pages/evidence.py",
        )
        return

    st.session_state.setdefault("plan", plan)
    summary = plan.get("summary", {})
    by_priority = summary.get("by_priority", {})

    section("Plan summary", icon="route",
            caption="Deterministic scoring — human approval is always required")
    metric_row([
        dict(label="Total", value=summary.get("total_count", 0), icon="layers"),
        dict(label="Critical", value=by_priority.get("CRITICAL", 0), icon="alert-octagon"),
        dict(label="High", value=by_priority.get("HIGH", 0), icon="crisis_alert"),
        dict(label="Medium", value=by_priority.get("MEDIUM", 0), icon="alert-triangle"),
        dict(label="Low", value=by_priority.get("LOW", 0), icon="info"),
    ], columns=5)

    chart_col, table_col = st.columns([2, 3])
    with chart_col:
        st.altair_chart(
            hbar_counts({k: v for k, v in by_priority.items() if v},
                        accent="#7C6CFF", height=180),
            width="stretch",
        )
    with table_col:
        rows = []
        for record in plan.get("recommendations", []):
            window = record.get("date_window")
            rows.append(
                {
                    "id": record["recommendation_id"],
                    "priority": record["priority"],
                    "score": record["priority_score"],
                    "action": record["action_type"],
                    "title": record["title"],
                    "status": record.get("status"),
                    "evidence": ", ".join(record.get("evidence_ids") or []),
                    "window": (f"{window['start']} → {window['end']}"
                               if isinstance(window, dict) else "—"),
                }
            )
        st.dataframe(rows, width="stretch", hide_index=True)

    ids = [r["recommendation_id"] for r in plan["recommendations"]]
    current = st.session_state.get("selected_recommendation_id")
    selected = st.selectbox(
        "Inspect a recommendation",
        ids,
        index=ids.index(current) if current in ids else 0,
    )
    st.session_state.selected_recommendation_id = selected

    section("Recommendation cards", icon="layers",
            caption="Selected record is outlined — open its decision console below")
    records = plan["recommendations"]
    batch_size = 2
    for start in range(0, len(records), batch_size):
        batch = records[start:start + batch_size]
        cols = st.columns(batch_size)
        for col, record in zip(cols, batch):
            with col:
                chosen = record["recommendation_id"] == selected
                st.markdown(_recommendation_card(record, chosen),
                            unsafe_allow_html=True)
    record = next(r for r in records if r["recommendation_id"] == selected)
    _show_detail(record)


run_page("Recommendations", "Deterministic playbook recommendations with explainable "
         "scoring — human approval is always required", render_recommendations,
         icon="route", eyebrow="Decision")
