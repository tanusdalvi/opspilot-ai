"""Human Review page — the safety boundary between analysis and decision.

Functional contract unchanged from Phase 8/10B: statuses change only
through the Phase 6 state machine via ``apply_review`` and every
decision is persisted as append-only audit rows. Phase 11B presents
the console as an explicit two-step gate: choose a decision, then
confirm it — the human is always the final gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from app import orchestrator  # noqa: E402
from app.state import get_engine, run_page  # noqa: E402
from app.ui.components import (  # noqa: E402
    badge,
    chips_row,
    empty_state,
    metric_row,
    section,
    severity_badge,
    stepper,
)
from app.ui.icons import escape_label  # noqa: E402

ACTIONS_BY_STATUS = {
    "PENDING": ("APPROVE", "REJECT", "REQUEST_CHANGES"),
    "CHANGES_REQUESTED": ("RESUBMIT",),
    "APPROVED": (),
    "REJECTED": (),
}

_BUTTON_META = {
    "APPROVE": ("Approve", ":material/task_alt:", "primary"),
    "REJECT": ("Reject", ":material/cancel:", "secondary"),
    "REQUEST_CHANGES": ("Request changes", ":material/edit_note:", "secondary"),
    "RESUBMIT": ("Resubmit", ":material/upload:", "secondary"),
}

_DECISION_COPY = {
    "APPROVE": (
        "Approving marks this recommendation APPROVED in the audit trail. "
        "The operational action itself remains a separate, tracked step."
    ),
    "REJECT": (
        "Rejecting marks this recommendation REJECTED and closes its review "
        "path. The decision and your reasoning are permanently auditable."
    ),
    "REQUEST_CHANGES": (
        "Requesting changes returns the record to CHANGES_REQUESTED so it "
        "can be revised and resubmitted."
    ),
    "RESUBMIT": (
        "Resubmitting moves the record back to PENDING for a fresh review."
    ),
}

_FLOW_ORDER = ("PENDING", "CHANGES_REQUESTED", "APPROVED")


def _active_record():
    plan = st.session_state.get("plan")
    selected = st.session_state.get("selected_recommendation_id")
    if not plan or not selected:
        return None, None
    for index, record in enumerate(plan.get("recommendations", [])):
        if record["recommendation_id"] == selected:
            return record, index
    return None, None


def _status_steps(current: object) -> list[tuple[str, str]]:
    """Honest step states: highlight only the true current status.

    The state machine allows PENDING -> APPROVED directly, so earlier
    steps are never claimed as 'done'; a REJECTED record blocks the flow.
    """
    if current == "REJECTED":
        return [(step, "blocked") for step in _FLOW_ORDER]
    return [
        (step, "active" if step == current else "todo")
        for step in _FLOW_ORDER
    ]


def _decision_banner(record: dict) -> None:
    strength = record.get("evidence_strength")
    strength_text = (
        f"{float(strength):.0f}% evidence strength"
        if isinstance(strength, (int, float)) else "deterministic scoring"
    )
    st.markdown(
        "<div class='ops-decision-banner'>"
        "<div class='ops-decision-banner-icon'>"
        f"{'&#9878;'}</div>"
        "<div>"
        "<div class='ops-decision-banner-title'>Human decision required · "
        f"{escape_label(record['recommendation_id'])}</div>"
        "<div class='ops-decision-banner-sub'>Your approval is the final "
        f"gate before any recommended action proceeds · {strength_text} · "
        f"{escape_label(str(record.get('priority')))} priority</div>"
        "</div></div>",
        unsafe_allow_html=True,
    )


def _confirmation_panel(record: dict, reviewer_id: str, comment: str) -> None:
    decision = st.session_state.pending_decision
    label = decision.replace("_", " ").title()
    st.markdown(
        "<div class='ops-confirm'>"
        "<div class='ops-confirm-title'>Confirm decision</div>"
        f"<div class='ops-card-sub'>{escape_label(_DECISION_COPY[decision])}"
        "</div></div>",
        unsafe_allow_html=True,
    )
    chips_row([
        badge(f"decision · {label}", "accent"),
        badge(f"record · {record['recommendation_id']}", "muted"),
        severity_badge(record.get("priority")),
        badge(f"reviewer · {reviewer_id}", "info"),
    ])
    col_confirm, col_cancel, _spacer = st.columns([1.4, 1, 3])
    with col_confirm:
        confirmed = st.button(
            f"Confirm {label}", type="primary",
            icon=":material/task_alt:", width="stretch",
            key="confirm-decision",
        )
    with col_cancel:
        cancelled = st.button(
            "Cancel", width="stretch", key="cancel-decision",
        )
    if cancelled:
        st.session_state.pending_decision = None
        st.rerun()
    if not confirmed:
        return

    with st.spinner("Applying review decision..."):
        updated, event = orchestrator.apply_review(
            decision, record,
            reviewer_id=reviewer_id,
            comment=comment.strip() or None,
        )
    with st.spinner("Saving audit record..."):
        engine = get_engine()
        rec_row_id, event_row_id = orchestrator.persist_review(engine, updated, event)

    plan = st.session_state.plan
    plan["recommendations"][
        next(i for i, r in enumerate(plan["recommendations"])
             if r["recommendation_id"] == record["recommendation_id"])
    ] = updated
    st.session_state.plan = plan
    st.session_state.pending_decision = None

    st.markdown(
        "<div class='ops-confirm ops-confirm-done'>"
        "<div class='ops-confirm-title'>Decision recorded</div>"
        f"<div class='ops-card-sub'>{escape_label(label)} applied to "
        f"{escape_label(record['recommendation_id'])} · audit rows "
        f"{rec_row_id} / {event_row_id} · visible in Audit History</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    with st.expander("Recorded review event"):
        st.json(event)
    st.page_link("pages/history.py", label="View in Audit History",
                 icon=":material/history:")


def render_review() -> None:
    record, _index = _active_record()
    if record is None:
        empty_state(
            "task_alt", "No recommendation selected",
            "Select a recommendation on the Recommendations page first — "
            "review decisions always apply to one specific record.",
            cta_label="Open Recommendations",
            cta_page="pages/recommendations.py",
        )
        return

    _decision_banner(record)

    with st.container(border=True):
        chips_row([
            badge(record["recommendation_id"], "accent"),
            severity_badge(record["priority"]),
            badge(record["action_type"], "muted"),
        ])
        st.markdown(f"**{record['title']}**")
        metric_row([
            dict(label="Priority", value=record["priority"], icon="crisis_alert"),
            dict(label="Action type", value=record["action_type"], icon="route"),
            dict(label="Current status", value=record["status"], icon="task_alt"),
        ], columns=4)
        stepper(_status_steps(record.get("status")))

    section("Reviewer", icon="user-check",
            caption="A non-empty reviewer id is required for every decision")
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

    pending = st.session_state.get("pending_decision")
    if pending in available and reviewer_id.strip():
        _confirmation_panel(record, reviewer_id.strip(), comment)
        return

    buttons = {}
    cols = st.columns(len(available))
    enabled = bool(reviewer_id.strip())
    for col, decision in zip(cols, available):
        label, material_icon, kind = _BUTTON_META[decision]
        with col:
            buttons[decision] = st.button(
                label, type=kind, disabled=not enabled,
                icon=material_icon, width="stretch",
                key=f"decision-{decision}",
            )

    chosen = next((d for d, clicked in buttons.items() if clicked), None)
    if chosen is None:
        return
    st.session_state.pending_decision = chosen
    st.rerun()


run_page("Human Review", "Explicit human decisions applied through the Phase 6 "
         "state machine — statuses never change any other way", render_review,
         icon="task_alt", eyebrow="Decision")
