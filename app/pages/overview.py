"""Overview page — the executive command center (Phase 11B).

The strongest page: operational posture first, then the attention
strip, business pulse, trend explorer, top signals, decision queue and
recent audit activity. Every number is either read from stored
artifacts or passed through :mod:`app.ui.posture` — one explicitly
defined presentation transformation of deterministic severity counts.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from app import exports  # noqa: E402
from app.state import require_artifacts, run_page  # noqa: E402
from app.ui.charts import area_trends, diverging_pct  # noqa: E402
from app.ui.components import (  # noqa: E402
    badge,
    chips_row,
    metric_row,
    section,
    severity_badge,
)
from app.ui.icons import escape_label  # noqa: E402
from app.ui.posture import (  # noqa: E402
    posture_band,
    posture_ring,
    posture_score,
    severity_color_for,
)
from app.ui.theme import severity_color  # noqa: E402

SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
_TREND_LABELS = {
    "revenue": ("Revenue", "trending-up"),
    "profit": ("Profit", "trending-up"),
    "units_sold": ("Units sold", "layers"),
}


def _signal_rows(anomalies: list[dict], limit: int = 6) -> list[tuple[int, dict]]:
    """Highest-attention anomalies first: severity rank, then magnitude."""

    def sort_key(item: tuple[int, dict]):
        _, record = item
        severity = str(record.get("severity") or "").upper()
        rank = (
            SEVERITY_ORDER.index(severity)
            if severity in SEVERITY_ORDER else len(SEVERITY_ORDER)
        )
        try:
            magnitude = abs(float(record.get("deviation_pct") or 0.0))
        except (TypeError, ValueError):
            magnitude = 0.0
        return (rank, -magnitude)

    return sorted(enumerate(anomalies), key=sort_key)[:limit]


def _signal_row_html(index: int, record: dict) -> str:
    color = severity_color(record.get("severity"))
    deviation = record.get("deviation_pct")
    deviation_text = (
        f"{float(deviation):+.1f}%" if isinstance(deviation, (int, float)) else "—"
    )
    bits = "".join(
        f"<span class='ops-chip'>{escape_label(value)}</span>"
        for value in (
            record.get("type"), record.get("scope"),
            record.get("entity"), record.get("date"),
        )
        if value
    )
    return (
        "<div class='ops-card ops-hover ops-sev-stripe' "
        f"style='--ops-sev:{color};padding:.75rem .95rem'>"
        "<div style='display:flex;justify-content:space-between;gap:8px;"
        "align-items:center;margin-bottom:5px'>"
        f"<span style='display:flex;gap:7px;align-items:center'>"
        f"<span class='ops-mono' style='color:var(--ops-text-3)'>#{index}</span>"
        f"{severity_badge(record.get('severity'))}"
        f"<strong style='font-size:.92rem'>"
        f"{escape_label(str(record.get('metric') or '—').title())}</strong>"
        "</span>"
        f"<span class='ops-metric-value' style='font-size:1.05rem;color:{color}'>"
        f"{deviation_text}</span></div>"
        f"<div style='display:flex;flex-wrap:wrap;gap:5px'>{bits}</div></div>"
    )


def render_overview() -> None:
    artifacts = require_artifacts()
    if artifacts is None:
        return

    kpis = artifacts.kpis
    changes = artifacts.period_comparison["changes_pct"]
    periods = artifacts.period_comparison
    trends = artifacts.daily_trends
    date_col = "date" if "date" in trends.columns else trends.columns[0]

    plan = st.session_state.get("plan") or {}
    recommendations = plan.get("recommendations", [])
    pending_recs = [r for r in recommendations if r.get("status") == "PENDING"]

    valid = artifacts.validation_report["error_count"] == 0
    by_sev = artifacts.anomaly_summary.get("by_severity") or {}
    score = posture_score(by_sev)
    band_label, band_tone = posture_band(score)

    # --- posture + attention strip + business pulse ---------------------------------------------
    posture_col, strip_col, pulse_col = st.columns([1.15, 2.1, 2.1])
    with posture_col:
        st.markdown(posture_ring(score, band_label, band_tone), unsafe_allow_html=True)
        chips_row([
            badge(artifacts.dataset_name, "accent"),
            badge(
                f"Validation {'clean' if valid else 'warnings'} · "
                f"{artifacts.validation_report['row_count']:,} records",
                "success" if valid else "warning",
            ),
            badge(f"{len(recommendations)} recommendations",
                  "ai" if pending_recs else "muted"),
        ])
    with strip_col:
        section("Attention", icon="crisis_alert",
                caption="Detected signals by severity")
        metric_row(
            [dict(label=sev.title(), value=by_sev.get(sev, 0),
                  icon="alert-octagon" if sev == "CRITICAL" else "activity",
                  caption=f"{sev.lower()} signals")
             for sev in SEVERITY_ORDER]
            + [dict(label="Total", value=artifacts.anomaly_result["total_count"],
                    icon="grid", caption="all severities")],
            columns=3,
        )
    with pulse_col:
        section("Business pulse", icon="target",
                caption="Deterministic aggregates")
        units_value = kpis.get("total_units_sold", kpis.get("units_sold", 0))
        metric_row([
            dict(label="Revenue", value=f"{kpis.get('total_revenue', 0):,.0f}",
                 icon="trending-up"),
            dict(label="Profit", value=f"{kpis.get('total_profit', 0):,.0f}",
                 icon="trending-up"),
            dict(label="Margin", value=f"{kpis.get('profit_margin_pct', 0):.1f}%",
                 icon="percent"),
            dict(label="Lead time", value=f"{kpis.get('average_lead_time_days', 0):.1f} d",
                 icon="clock"),
            dict(label="Units", value=f"{units_value:,}", icon="layers"),
            dict(label="Regions", value=kpis.get("unique_regions", 0), icon="grid"),
        ], columns=3)

    # --- trend explorer + period comparison --------------------------------------------------------
    left, right = st.columns([3, 2])
    with left:
        section("Operational trend", icon="monitoring",
                caption="Pick the metrics to overlay across the analyzed window")
        choices = [c for c in _TREND_LABELS if c in trends.columns] or [
            c for c in trends.columns if c != date_col
        ]
        selected = st.multiselect(
            "Metrics",
            choices,
            default=choices[:2],
            format_func=lambda c: _TREND_LABELS.get(c, (c, ""))[0].title(),
        )
        if selected:
            st.altair_chart(area_trends(trends, date_col, selected),
                            width="stretch")
        else:
            st.caption("Select at least one metric to draw the trend.")
    with right:
        section("Period comparison", icon="clock",
                caption=f"{periods['period_1']['start']} → {periods['period_1']['end']} "
                        f"vs {periods['period_2']['start']} → {periods['period_2']['end']}")
        st.altair_chart(diverging_pct(changes), width="stretch")
        st.caption(
            "Lead-time changes are amber by design: whether an increase is bad "
            "depends on context."
        )

    # --- top operational signals ---------------------------------------------------------------------
    section("Top operational signals", icon="star",
            caption="Highest attention first — open Anomalies for the full explorer")
    anomalies = artifacts.anomalies
    if not anomalies:
        st.caption("No anomalies detected — nothing needs attention right now.")
    else:
        rows = _signal_rows(anomalies)
        for start in range(0, len(rows), 2):
            batch = rows[start:start + 2]
            cols = st.columns(len(batch))
            for col, (index, record) in zip(cols, batch):
                with col:
                    st.markdown(_signal_row_html(index, record), unsafe_allow_html=True)
        st.page_link("pages/anomalies.py", label="Open the anomaly explorer",
                     icon=":material/crisis_alert:")

    # --- decision queue --------------------------------------------------------------------------------
    section("Decision queue", icon="task_alt",
            caption="Highest-priority recommendations awaiting human review")
    if not pending_recs:
        chips_row([badge("No pending decisions", "success")])
    else:
        ranked = sorted(
            pending_recs, key=lambda r: float(r.get("priority_score") or 0),
            reverse=True,
        )[:3]
        queue_cols = st.columns(len(ranked))
        for col, record in zip(queue_cols, ranked):
            color = severity_color_for(record.get("priority"))
            with col:
                strength = float(record.get("evidence_strength") or 0.0)
                score_value = float(record.get("priority_score") or 0)
                st.markdown(
                    "<div class='ops-card ops-hover ops-sev-stripe' "
                    f"style='--ops-sev:{color};height:100%'>"
                    "<div style='display:flex;justify-content:space-between;"
                    "align-items:center;gap:6px;margin-bottom:4px'>"
                    f"{severity_badge(record.get('priority'))}"
                    f"<span class='ops-mono' style='color:var(--ops-text-3)'>"
                    f"score {score_value:.0f}</span></div>"
                    f"<div style='font-weight:630;font-size:.93rem;line-height:1.3'>"
                    f"{escape_label(record.get('title'))}</div>"
                    f"<div class='ops-card-sub' style='margin-top:4px'>"
                    f"Evidence strength {strength:.0f}% &#183; "
                    "human review required</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )
                if st.button("Review decision",
                             key=f"queue-{record['recommendation_id']}",
                             width="stretch"):
                    st.session_state.selected_recommendation_id = \
                        record["recommendation_id"]
                    st.switch_page("pages/review.py")

    # --- recent activity ---------------------------------------------------------------------------------
    from app.state import get_engine

    engine = None
    try:
        engine = get_engine()
    except Exception:  # noqa: BLE001 - overview must render even if DB is unavailable
        engine = None

    section("Recent activity", icon="history",
            caption="Latest entries from the append-only audit store")
    activity_items: list[tuple[str, str, str]] = []  # (when, html, tone)
    if engine is not None:
        from database import repository as repo

        for plan_row in repo.list_plans(engine)[:5]:
            activity_items.append((
                str(plan_row["recorded_at"]),
                f"<strong>Plan #{plan_row['plan_id']} generated</strong> "
                f"<span class='ops-card-sub'>· "
                f"{plan_row['recommendation_count']} recommendation(s)</span>",
                "accent",
            ))
        for event in repo.list_review_events(engine)[:5]:
            tone = {"APPROVE": "success", "REJECT": "danger"}.get(
                str(event["decision"]), "info")
            activity_items.append((
                str(event["occurred_at"]),
                f"<strong>{escape_label(event['recommendation_id'])} "
                f"{escape_label(str(event['decision']).lower())}d</strong> "
                f"<span class='ops-card-sub'>· reviewer "
                f"{escape_label(event['reviewer_id'])}</span>",
                tone,
            ))
    if anomalies:
        activity_items.append((
            "",
            f"<strong>Detection run completed</strong> <span class='ops-card-sub'>"
            f"· {len(anomalies)} anomalies · evidence pack ready</span>",
            "warning",
        ))
    if not activity_items:
        st.caption("No audit activity recorded yet.")
    else:
        dot_map = {
            "accent": "var(--ops-accent)", "success": "var(--ops-success)",
            "danger": "var(--ops-danger)", "warning": "var(--ops-warning)",
            "info": "var(--ops-info)",
        }
        for when, html, tone in activity_items[:6]:
            st.markdown(
                "<div style='display:flex;gap:10px;align-items:center;"
                "padding:.32rem 0;border-bottom:1px solid var(--ops-line)'>"
                f"<span style='flex:none;width:8px;height:8px;border-radius:50%;"
                f"background:{dot_map.get(tone, 'var(--ops-text-3)')}'></span>"
                f"<span style='flex:1;font-size:.88rem'>{html}</span>"
                f"<span class='ops-mono' style='color:var(--ops-text-3);"
                f"font-size:.74rem'>{escape_label(when[:19])}</span>"
                "</div>",
                unsafe_allow_html=True,
            )
        st.page_link("pages/history.py", label="Open the full audit trail",
                     icon=":material/history:")

    # --- exports -------------------------------------------------------------------------------------------
    section("Exports", icon="download",
            caption="Identical data always produces identical files")
    export_base = "".join(
        character for character in Path(artifacts.dataset_name).stem
        if character.isalnum() or character in "-_"
    ) or "dataset"
    dl_left, dl_right = st.columns(2)
    dl_left.download_button(
        "Analysis Summary (JSON)",
        data=exports.canonical_json(exports.analysis_summary_payload(artifacts)),
        file_name=f"{export_base}-analysis-summary.json",
        mime="application/json",
        icon=":material/download:",
        width="stretch",
    )
    dl_right.download_button(
        "Anomalies (CSV)",
        data=exports.anomalies_csv_text(artifacts),
        file_name=f"{export_base}-anomalies.csv",
        mime="text/csv",
        icon=":material/table:",
        width="stretch",
    )

    if engine is not None:
        from database import repository as repo

        st.caption(
            f"Audit store · {repo.count_plans(engine)} plans · "
            f"{repo.count_recommendations(engine)} recommendation snapshots · "
            f"{repo.count_review_events(engine)} review events"
        )


run_page("Overview", "Current operational posture across the analyzed dataset — "
         "signals, decisions and audit activity at a glance",
         render_overview, icon="space_dashboard", eyebrow="Command Center")
