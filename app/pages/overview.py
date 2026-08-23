"""Overview page — executive summary of the analyzed dataset (Phase 8)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import exports  # noqa: E402
from app.state import require_artifacts, run_page  # noqa: E402
from database import repository as repo  # noqa: E402


def _pct(value: float) -> str:
    return f"{value:+.1f}%"


def render_overview() -> None:
    artifacts = require_artifacts()
    if artifacts is None:
        return

    kpis = artifacts.kpis
    changes = artifacts.period_comparison["changes_pct"]
    periods = artifacts.period_comparison

    st.subheader(f"Dataset: {artifacts.dataset_name}")
    trends: pd.DataFrame = artifacts.daily_trends
    date_col = "date" if "date" in trends.columns else trends.columns[0]
    st.markdown(
        f"Date range **{trends[date_col].min()} → {trends[date_col].max()}** · "
        f"{artifacts.validation_report['row_count']} records · "
        f"validated with {artifacts.validation_report['error_count']} errors, "
        f"{artifacts.validation_report['warning_count']} warnings"
    )

    plan = st.session_state.get("plan") or {}
    recommendations = plan.get("recommendations", [])
    pending = sum(1 for r in recommendations if r.get("status") == "PENDING")

    c = st.columns(4)
    c[0].metric("Total revenue", f"{kpis.get('total_revenue', 0):,.0f}")
    c[1].metric("Total profit", f"{kpis.get('total_profit', 0):,.0f}")
    c[2].metric("Profit margin", f"{kpis.get('profit_margin_pct', 0):.1f}%")
    c[3].metric("Avg lead time", f"{kpis.get('average_lead_time_days', 0):.1f} d")
    c2 = st.columns(4)
    c2[0].metric("Unique regions", kpis.get("unique_regions", 0))
    c2[1].metric("Anomalies detected", artifacts.anomaly_result["total_count"])
    c2[2].metric("Recommendations", len(recommendations))
    c2[3].metric("Pending review", pending)

    st.divider()
    st.subheader("Period comparison")
    p1, p2 = periods["period_1"], periods["period_2"]
    st.caption(
        f"First half {p1['start']} → {p1['end']} versus second half "
        f"{p2['start']} → {p2['end']}"
    )
    labels = {
        "revenue_change_pct": "Revenue",
        "profit_change_pct": "Profit",
        "units_change_pct": "Units sold",
        "cost_change_pct": "Cost",
        "margin_change_pct": "Margin",
        "lead_time_change_pct": "Lead time",
    }
    cols = st.columns(len(labels))
    for col, (key, label) in zip(cols, labels.items()):
        value = changes.get(key)
        if value is None:
            col.metric(label, "n/a")
            continue
        delta = _pct(float(value))
        col.metric(label, delta, delta=delta,
                   delta_color=("off" if key == "lead_time_change_pct" else "normal"))
    st.caption(
        "Changes compare the two halves of the timeline; lead-time increases are "
        "shown without a good/bad colour because impact depends on context."
    )

    st.divider()
    st.subheader("Exports")
    st.caption(
        "Deterministic machine-readable snapshots of the current analysis. "
        "Identical data always produces identical files."
    )
    export_base = "".join(
        character for character in Path(artifacts.dataset_name).stem
        if character.isalnum() or character in "-_"
    ) or "dataset"
    left, right = st.columns(2)
    left.download_button(
        "Download Analysis Summary (JSON)",
        data=exports.canonical_json(exports.analysis_summary_payload(artifacts)),
        file_name=f"{export_base}-analysis-summary.json",
        mime="application/json",
        icon="⬇️",
    )
    right.download_button(
        "Download Anomalies (CSV)",
        data=exports.anomalies_csv_text(artifacts),
        file_name=f"{export_base}-anomalies.csv",
        mime="text/csv",
        icon="⬇️",
    )

    st.divider()
    engine = None
    from app.state import get_engine

    try:
        engine = get_engine()
    except Exception:  # noqa: BLE001 - overview must render even if DB is unavailable
        engine = None
    if engine is not None:
        st.caption(
            f"Audit store: {repo.count_plans(engine)} plans · "
            f"{repo.count_recommendations(engine)} recommendation snapshots · "
            f"{repo.count_review_events(engine)} review events"
        )


run_page("Overview", "Executive view of the current dataset and workflow state",
         render_overview)
