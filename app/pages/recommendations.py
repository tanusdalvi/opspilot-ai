"""Recommendations page — deterministic plan display and one-time persistence (Phase 8)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import orchestrator  # noqa: E402
from app.state import get_engine, require_artifacts, run_page  # noqa: E402

PRIORITY_COLORS = {
    "CRITICAL": "🔴",
    "HIGH": "🟠",
    "MEDIUM": "🟡",
    "LOW": "🟢",
}
STATUS_BADGE = {
    "PENDING": "🟡 PENDING",
    "APPROVED": "✅ APPROVED",
    "REJECTED": "⛔ REJECTED",
    "CHANGES_REQUESTED": "🔁 CHANGES_REQUESTED",
}


def _plan_rows(plan: dict) -> list[dict]:
    rows = []
    for record in plan.get("recommendations", []):
        window = record.get("date_window")
        rows.append(
            {
                "recommendation_id": record["recommendation_id"],
                "priority": f"{PRIORITY_COLORS.get(record['priority'], '')} "
                            f"{record['priority']} ({record['priority_score']:.0f})",
                "action": record["action_type"],
                "title": record["title"],
                "scope": record["scope"],
                "target": record.get("target_entity") or record.get("target_metric")
                          or "—",
                "strength": round(float(record["evidence_strength"]), 1),
                "status": STATUS_BADGE.get(record.get("status"),
                                           record.get("status")),
                "evidence": ", ".join(record.get("evidence_ids") or []),
                "window": (f"{window['start']} → {window['end']}"
                           if isinstance(window, dict) else "—"),
            }
        )
    return rows


def _show_detail(record: dict) -> None:
    st.markdown(f"#### {record['recommendation_id']} — {record['title']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Priority", record["priority"], delta=f"score {record['priority_score']:.0f}")
    c2.metric("Evidence strength", f"{record['evidence_strength']:.1f}")
    c3.metric("Action type", record["action_type"])
    c4.metric("Status", STATUS_BADGE.get(record.get("status"), record.get("status")))
    st.write(record["description"])
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
    st.json(meta)
    if record.get("requires_human_review") is True:
        st.warning("**Human review required** — this recommendation cannot be "
                   "executed automatically. Approve or reject it on the "
                   "**Human Review** page.")
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

    generate = left.button("Generate recommendations", type="primary")
    regenerate = left.button(
        "Regenerate (new audit record)",
        help="Creates a fresh deterministic plan and persists it as a NEW "
             "append-only audit record.",
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
        st.info("No recommendations generated yet for this dataset.")
        return

    st.session_state.setdefault("plan", plan)
    summary = plan.get("summary", {})
    by_priority = summary.get("by_priority", {})
    m = st.columns(5)
    m[0].metric("Total", summary.get("total_count", 0))
    m[1].metric("Critical", by_priority.get("CRITICAL", 0))
    m[2].metric("High", by_priority.get("HIGH", 0))
    m[3].metric("Medium", by_priority.get("MEDIUM", 0))
    m[4].metric("Low", by_priority.get("LOW", 0))

    rows = _plan_rows(plan)
    st.dataframe(rows, use_container_width=True)

    ids = [r["recommendation_id"] for r in plan["recommendations"]]
    current = st.session_state.get("selected_recommendation_id")
    selected = st.selectbox(
        "Inspect a recommendation",
        ids,
        index=ids.index(current) if current in ids else 0,
    )
    st.session_state.selected_recommendation_id = selected
    record = next(r for r in plan["recommendations"]
                  if r["recommendation_id"] == selected)
    _show_detail(record)


run_page("Recommendations", "Deterministic playbook recommendations with explainable "
         "scoring — human approval is always required", render_recommendations)
