"""Analytics page — KPI dashboard and trends (Phase 8).

Owns the explicit analysis lifecycle: one user action runs the
deterministic pipeline exactly once and every other page consumes the
stored artifacts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import orchestrator  # noqa: E402
from app.state import (  # noqa: E402
    ANALYSIS_RUNNING,
    begin_analysis,
    complete_analysis,
    fail_analysis,
    get_analysis_status,
    is_analysis_stale,
    require_artifacts,
    run_page,
)
from core.exceptions import OpsPilotError  # noqa: E402

SENSITIVITIES = ("low", "medium", "high")


def _run_analysis(df, sensitivity: str) -> None:
    """Run the pipeline exactly once for one explicit user action.

    Lifecycle: ANALYZING before the expensive work starts, READY on
    success, ERROR with a safe message on failure. Previous valid
    artifacts are only replaced by a successful run. A queued duplicate
    interaction can never start a second execution.
    """
    if get_analysis_status() == ANALYSIS_RUNNING:
        return
    begin_analysis()
    try:
        with st.spinner("Running deterministic operational analysis..."):
            artifacts = orchestrator.run_pipeline(
                df,
                dataset_name=st.session_state.get("dataset_name", "dataset"),
                sensitivity=sensitivity,
            )
    except OpsPilotError as exc:
        fail_analysis(str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - same boundary as run_page
        fail_analysis(f"Unexpected application error ({type(exc).__name__}).")
        return
    complete_analysis(artifacts)


def _render_analytics(artifacts) -> None:
    trends: pd.DataFrame = artifacts.daily_trends
    st.subheader("Daily trends")
    date_col = "date" if "date" in trends.columns else trends.columns[0]
    value_cols = [c for c in ("revenue", "profit", "units_sold") if c in trends.columns]
    if value_cols:
        chart_df = trends.set_index(date_col)[value_cols]
        st.line_chart(chart_df)
        st.dataframe(trends.tail(15), use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Region performance")
        st.dataframe(artifacts.region_performance, use_container_width=True)
        top_r = artifacts.top_performers.get("top_regions") or []
        bottom_r = artifacts.bottom_performers.get("bottom_regions") or []
        if top_r or bottom_r:
            st.markdown(f"**Top regions:** {', '.join(str(r) for r in top_r[:3])}  |  "
                        f"**Bottom:** {', '.join(str(r) for r in bottom_r[:3])}")
    with right:
        st.subheader("Product performance")
        st.dataframe(artifacts.product_performance, use_container_width=True)
        top_p = artifacts.top_performers.get("top_products") or []
        bottom_p = artifacts.bottom_performers.get("bottom_products") or []
        if top_p or bottom_p:
            st.markdown(f"**Top products:** {', '.join(str(p) for p in top_p[:3])}  |  "
                        f"**Bottom:** {', '.join(str(p) for p in bottom_p[:3])}")


def render_analytics() -> None:
    df = st.session_state.get("df")
    if df is None:
        st.warning("Load a dataset on the **Data** page first.")
        return

    controls = st.columns([1, 2])
    sensitivity = controls[0].selectbox(
        "Detection sensitivity", SENSITIVITIES,
        index=SENSITIVITIES.index(st.session_state.get("sensitivity", "medium")),
    )
    report = st.session_state.get("validation_report")
    if report is not None:
        controls[1].metric("Validation errors", report["error_count"])

    st.session_state.sensitivity = sensitivity

    running = get_analysis_status() == ANALYSIS_RUNNING
    dataset_name = st.session_state.get("dataset_name", "dataset")

    run_clicked = st.button(
        "Run / Refresh Analysis", type="primary",
        disabled=running,
        help="Runs validation, analytics, anomaly detection, insights and "
             "the evidence pack exactly once.",
    )

    # ONE user action -> ONE pipeline execution. Sensitivity changes only
    # mark existing results stale; they never silently trigger a rerun.
    if run_clicked:
        _run_analysis(df, sensitivity)

    if get_analysis_status() == ANALYSIS_RUNNING:
        st.info(
            f"⏳ **Analysis in progress** — processing `{dataset_name}` at "
            f"sensitivity `{sensitivity}`. Please wait..."
        )

    if is_analysis_stale(sensitivity, dataset_name):
        st.warning(
            "Analysis settings changed. The results below reflect the "
            "previous settings — press **Run / Refresh Analysis** to update."
        )

    artifacts = require_artifacts()
    if artifacts is None:
        return
    _render_analytics(artifacts)


run_page("Analytics", "KPIs, daily trends and regional/product performance — "
         "computed by the deterministic analytics service", render_analytics)
