"""Audit History page — read-only views over the append-only audit store.

Functional contract unchanged from Phase 8/9: every read goes through
``database.repository`` and exports stay byte-identical. Phase 11B
presents plans and review events as a day-grouped audit timeline. The
plan expander labels ("Plan #<id> … recommendation(s)") are part of the
Phase 9 smoke-test surface and are preserved verbatim.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import streamlit as st  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import exports  # noqa: E402
from app.state import get_engine, run_page  # noqa: E402
from app.ui.components import (  # noqa: E402
    badge,
    chips_row,
    empty_state,
    metric_row,
    section,
    timeline,
    timeline_item,
)
from app.ui.icons import escape_label  # noqa: E402
from database import repository as repo  # noqa: E402

_DECISION_TONE = {"APPROVE": "success", "REJECT": "danger",
                  "REQUEST_CHANGES": "info", "RESUBMIT": "accent"}


def _day_label(day: str, today: date | None = None) -> str:
    """Human day label for an ISO date string (pure, testable).

    ``2026-08-23`` → ``Today`` / ``Yesterday`` when applicable, otherwise
    the ISO date itself. Unparseable input passes through unchanged.
    """
    try:
        parsed = date.fromisoformat(str(day)[:10])
    except (TypeError, ValueError):
        return str(day)
    reference = today or date.today()
    if parsed == reference:
        return "Today"
    if parsed == reference - timedelta(days=1):
        return "Yesterday"
    return parsed.isoformat()


def _grouped_by_day(events: list[dict]) -> list[tuple[str, list[dict]]]:
    """Group events into consecutive day buckets, newest bucket first.

    Events are assumed ordered oldest → newest as returned by the
    repository; the display order reverses them.
    """
    buckets: list[tuple[str, str, list[dict]]] = []
    for event in reversed(events):
        day = str(event.get("occurred_at") or "")[:10]
        label = _day_label(day)
        if buckets and buckets[-1][0] == label and buckets[-1][1] == day:
            buckets[-1][2].append(event)
        else:
            buckets.append((label, day, [event]))
    return [(label, items) for label, _day, items in buckets]


def _render_plans(engine) -> None:
    st.subheader("Plans")
    plans = repo.list_plans(engine)
    if not plans:
        empty_state(
            "file-text", "No plans persisted yet",
            "Generate a plan on the Recommendations page; it will be recorded "
            "here as an immutable audit entry.",
        )
        return
    rows = [
        {
            "plan_id": p["plan_id"],
            "recorded_at": p["recorded_at"],
            "type": p["plan_type"],
            "schema": p["schema_version"],
            "recommendations": p["recommendation_count"],
            "anomaly_count": p["source"].get("anomaly_count"),
            "investigation": p["source"].get("investigation_status") or "—",
        }
        for p in plans
    ]
    st.dataframe(rows, width="stretch", hide_index=True)

    for p in plans:
        with st.expander(
            f"Plan #{p['plan_id']} · recorded {p['recorded_at']} · "
            f"{p['recommendation_count']} recommendation(s)",
            expanded=False,
        ):
            left, right = st.columns(2)
            with left:
                st.caption("**Parameters**")
                st.json(p["parameters"])
            with right:
                st.caption("**Source provenance**")
                st.json(p["source"])
            st.caption("**Summary**")
            st.json(p["summary"])

            full = repo.get_plan(engine, p["plan_id"])
            snapshots = (full or {}).get("recommendations", [])
            if snapshots:
                st.dataframe(
                    [
                        {
                            "id": snap["recommendation_id"],
                            "priority": snap["priority"],
                            "score": snap["priority_score"],
                            "action": snap["action_type"],
                            "status": snap["status"],
                            "evidence": ", ".join(snap["evidence_ids"]) or "—",
                        }
                        for snap in snapshots
                    ],
                    width="stretch",
                    hide_index=True,
                )

    payload = exports.plan_audit_payload(
        [repo.get_plan(engine, p["plan_id"]) for p in plans],
        repo.list_review_events(engine),
    )
    st.download_button(
        "Download Plans + Audit (JSON)",
        data=exports.canonical_json(payload),
        file_name="opspilot-plan-audit-export.json",
        mime="application/json",
        icon=":material/download:",
    )


def render_history() -> None:
    engine = get_engine()

    section("Audit store", icon="archive",
            caption="Append-only: records are never edited or deleted")
    metric_row([
        dict(label="Plans", value=repo.count_plans(engine), icon="file-text"),
        dict(label="Recommendation snapshots",
             value=repo.count_recommendations(engine), icon="layers"),
        dict(label="Review events", value=repo.count_review_events(engine),
             icon="user-check"),
    ], columns=4)

    _render_plans(engine)

    section("Recommendation snapshots", icon="layers")
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
            "title": escape_label(str(snap["title"])[:60]),
            "status": snap["status"],
        }
        for position, snap in enumerate(snapshots)
    ]
    st.dataframe(rows, width="stretch", hide_index=True)

    latest_id = st.selectbox(
        "Latest snapshot for recommendation",
        sorted({snap["recommendation_id"] for snap in snapshots}),
    )
    latest = repo.get_latest_recommendation(engine, latest_id)
    if latest:
        with st.expander(f"Latest stored state of {latest_id}", expanded=True):
            st.json(latest)

    section("Review events", icon="user-check")
    events = repo.list_review_events(engine)
    if not events:
        st.info("No review events recorded yet.")
        return

    chips_row([
        badge(f"{len(events)} decision(s)", "accent"),
        badge(f"{len({e['reviewer_id'] for e in events})} reviewer(s)", "muted"),
    ])

    for day_label, day_events in _grouped_by_day(events):
        st.markdown(
            f"<div class='ops-day-label'><span></span>{escape_label(day_label)}"
            "</div>",
            unsafe_allow_html=True,
        )
        timeline_items = []
        for e in day_events:
            tone = _DECISION_TONE.get(str(e["decision"]), "muted")
            transition = (
                f"{e['previous_status']} → {e['new_status']}"
                if e.get("previous_status") != e.get("new_status")
                else str(e["new_status"])
            )
            comment = f" · {e.get('comment')}" if e.get("comment") else ""
            timeline_items.append(timeline_item(
                when=str(e["occurred_at"])[11:16] or e["occurred_at"],
                badges=[
                    badge(str(e["decision"]), tone),
                    badge(transition, "muted"),
                ],
                # Repository contract: recommendation_id key (no id key).
                body=(f"{e['recommendation_id']} · reviewer "
                      f"{e['reviewer_id']}{comment}"),
                tone=tone,
            ))
        timeline(timeline_items)

    with st.expander("Raw events table"):
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
        st.dataframe(event_rows, width="stretch", hide_index=True)


run_page("Audit History", "Everything the application has recorded — plans, "
         "snapshots and review events (read-only)", render_history,
         icon="history", eyebrow="Audit")
