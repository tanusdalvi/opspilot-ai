"""Audit History page — read-only views over the append-only audit store (Phase 8)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.state import get_engine, run_page  # noqa: E402
from database import repository as repo  # noqa: E402


def render_history() -> None:
    engine = get_engine()
    c = st.columns(4)
    c[0].metric("Plans", repo.count_plans(engine))
    c[1].metric("Recommendation snapshots", repo.count_recommendations(engine))
    c[2].metric("Review events", repo.count_review_events(engine))
    c[3].metric("", "")

    st.caption(
        "This is an **append-only audit trail**: records are never edited or "
        "deleted. Each review creates a new recommendation snapshot next to "
        "its structured event."
    )

    st.divider()
    st.subheader("Recommendation snapshots")
    snapshots = repo.list_recommendations(engine)
    if not snapshots:
        st.info("No recommendations persisted yet.")
        return
    rows = [
        {
            "row": position + 1,
            "id": snap["recommendation_id"],
            "priority": snap["priority"],
            "score": snap["priority_score"],
            "action": snap["action_type"],
            "title": snap["title"][:60],
            "status": snap["status"],
        }
        for position, snap in enumerate(snapshots)
    ]
    st.dataframe(rows, use_container_width=True)

    latest_id = st.selectbox(
        "Latest snapshot for recommendation",
        sorted({snap["recommendation_id"] for snap in snapshots}),
    )
    latest = repo.get_latest_recommendation(engine, latest_id)
    if latest:
        with st.expander(f"Latest stored state of {latest_id}", expanded=True):
            st.json(latest)

    st.divider()
    st.subheader("Review events")
    events = repo.list_review_events(engine)
    if not events:
        st.info("No review events recorded yet.")
        return
    event_rows = [
        {
            "when": e["occurred_at"],
            "id": e["recommendation_id"],
            "decision": e["decision"],
            "previous": e["previous_status"],
            "new": e["new_status"],
            "reviewer": e["reviewer_id"],
            "comment": e.get("comment") or "—",
        }
        for e in events
    ]
    st.dataframe(event_rows, use_container_width=True)


run_page("Audit History", "Everything the application has recorded — plans, "
         "snapshots and review events (read-only)", render_history)
