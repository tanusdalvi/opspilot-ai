"""Human Review page — the safety boundary between analysis and decision (Phase 8)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import orchestrator  # noqa: E402
from app.state import get_engine, run_page  # noqa: E402

ACTIONS_BY_STATUS = {
    "PENDING": ("APPROVE", "REJECT", "REQUEST_CHANGES"),
    "CHANGES_REQUESTED": ("RESUBMIT",),
    "APPROVED": (),
    "REJECTED": (),
}


def _active_record():
    plan = st.session_state.get("plan")
    selected = st.session_state.get("selected_recommendation_id")
    if not plan or not selected:
        return None, None
    for index, record in enumerate(plan.get("recommendations", [])):
        if record["recommendation_id"] == selected:
            return record, index
    return None, None


def render_review() -> None:
    record, index = _active_record()
    if record is None:
        st.warning(
            "Select a recommendation on the **Recommendations** page first."
        )
        return

    st.subheader(f"{record['recommendation_id']} — {record['title']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Priority", record["priority"])
    c2.metric("Action type", record["action_type"])
    c3.metric("Current status", record["status"])

    reviewer_id = st.text_input(
        "Reviewer ID",
        value=st.session_state.get("reviewer_id", ""),
        placeholder="e.g. ops-manager",
    )
    comment = st.text_area("Comment (optional)", value="")

    available = ACTIONS_BY_STATUS.get(record.get("status"), ())
    if not available:
        st.info(
            f"Status **{record['status']}** is terminal — no further review "
            "actions are available for this recommendation."
        )
        return
    if not reviewer_id.strip():
        st.info("Enter a non-empty reviewer ID to enable review actions.")
    st.session_state.reviewer_id = reviewer_id.strip()

    buttons = {}
    cols = st.columns(len(available))
    labels = {"APPROVE": "✅ Approve", "REJECT": "⛔ Reject",
              "REQUEST_CHANGES": "🔁 Request changes", "RESUBMIT": "📤 Resubmit"}
    enabled = bool(reviewer_id.strip())
    for col, decision in zip(cols, available):
        buttons[decision] = col.button(
            labels[decision], type="primary" if decision == "APPROVE" else "secondary",
            disabled=not enabled,
        )

    chosen = next((d for d, clicked in buttons.items() if clicked), None)
    if chosen is None:
        return

    with st.spinner("Applying review decision..."):
        updated, event = orchestrator.apply_review(
            chosen, record,
            reviewer_id=st.session_state.reviewer_id,
            comment=comment.strip() or None,
        )
    with st.spinner("Saving audit record..."):
        engine = get_engine()
        rec_row_id, event_row_id = orchestrator.persist_review(engine, updated, event)

    plan = st.session_state.plan
    plan["recommendations"][index] = updated
    st.session_state.plan = plan

    st.success(f"Review recorded (audit rows {rec_row_id} / {event_row_id}).")
    result = st.container()
    with result:
        st.subheader("Recorded review")
        st.json(event)
    st.rerun()


run_page("Human Review", "Explicit human decisions applied through the Phase 6 "
         "state machine — statuses never change any other way", render_review)
