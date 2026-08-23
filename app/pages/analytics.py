"""Analytics page — KPI dashboard, trends and the analysis lifecycle.

Owns the explicit analysis lifecycle exactly as in Phase 8/10B: one
user action runs the deterministic pipeline once, results land in
session state, and every other page consumes the stored artifacts.
Phase 11B adds the KPI ribbon and an honest loading checklist; the
pipeline itself is untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

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
from app.ui.charts import area_trends, performance_bars  # noqa: E402
from app.ui.components import (  # noqa: E402
    badge,
    chips_row,
    loading_panel,
    metric_row,
    section,
    skeleton_cards,
    stage_checklist,
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


def _kpi_ribbon(artifacts) -> None:
    """Presentation-only KPI ribbon derived from stored analytics."""
    kpis = dict(getattr(artifacts, "kpis", {}) or {})
    revenue = float(kpis.get("total_revenue") or 0.0)
    profit = float(kpis.get("total_profit") or kpis.get("profit") or 0.0)
    margin = (profit / revenue * 100.0) if revenue else None
    units = (
        kpis.get("total_units_sold", kpis.get("units_sold")) or 0
    )
    metric_row([
        dict(label="Revenue", value=f"{revenue:,.0f}", icon="trending-up"),
        dict(label="Profit", value=f"{profit:,.0f}",
             icon="trending-down" if profit < 0 else "trending-up",
             delta_tone="good" if profit >= 0 else "bad"),
        dict(label="Margin",
             value=f"{margin:.1f}%" if margin is not None else "—",
             icon="percent"),
        dict(label="Units sold", value=f"{float(units):,.0f}", icon="table"),
        dict(label="Anomalies", value=len(artifacts.anomalies), icon="crisis_alert"),
    ], columns=5)


def _dimension_block(frame: pd.DataFrame, dimension_col: str, label: str) -> None:
    value_col = next(
        (c for c in ("revenue", "total_revenue", "profit") if c in frame.columns),
        frame.columns[1],
    )
    st.altair_chart(
        performance_bars(frame, dimension_col, value_col, title_y=label),
        width="stretch",
    )
    top = frame.sort_values(value_col, ascending=False).head(3)[dimension_col]
    bottom = frame.sort_values(value_col, ascending=True).head(3)[dimension_col]
    chips_row([badge("Top", "success"), *(badge(str(v), "muted") for v in top.tolist())])
    chips_row([
        badge("Bottom", "warning"),
        *(badge(str(v), "muted") for v in bottom.tolist()),
    ])
    with st.expander("Full table"):
        st.dataframe(frame, width="stretch")


def _render_analytics(artifacts) -> None:
    trends: pd.DataFrame = artifacts.daily_trends
    date_col = "date" if "date" in trends.columns else trends.columns[0]

    section("Key performance indicators", icon="target",
            caption="Derived from the deterministic analytics service output")
    _kpi_ribbon(artifacts)

    section("Daily trends", icon="monitoring",
            caption="Revenue, profit and unit volume across the analyzed window")
    value_cols = [c for c in ("revenue", "profit", "units_sold") if c in trends.columns]
    if value_cols:
        st.altair_chart(area_trends(trends, date_col, value_cols),
                        width="stretch")
        with st.expander("Recent daily records"):
            st.dataframe(trends.tail(15), width="stretch", hide_index=True)

    left, right = st.columns(2)
    with left:
        section("Region performance", icon="grid")
        _dimension_block(artifacts.region_performance, "region", "Region")
    with right:
        section("Product performance", icon="layers")
        _dimension_block(artifacts.product_performance, "product", "Product")


def render_analytics() -> None:
    df = st.session_state.get("df")
    if df is None:
        st.warning("Load a dataset on the **Data** page first.")
        return

    with st.container(border=True):
        controls = st.columns([2, 2])
        with controls[0]:
            sensitivity = st.radio(
                "Detection sensitivity", list(SENSITIVITIES),
                index=SENSITIVITIES.index(st.session_state.get("sensitivity", "medium")),
                horizontal=True,
            )
        report = st.session_state.get("validation_report")

        running = get_analysis_status() == ANALYSIS_RUNNING
        dataset_name = st.session_state.get("dataset_name", "dataset")

        run_clicked = st.button(
            "Run / Refresh Analysis", type="primary",
            icon=":material/play_arrow:", disabled=running,
            width="stretch",
            help="Runs validation, analytics, anomaly detection, insights and "
                 "the evidence pack exactly once.",
        )

        # ONE user action -> ONE pipeline execution. Sensitivity changes only
        # mark existing results stale; they never silently trigger a rerun.
        if run_clicked:
            _run_analysis(df, sensitivity)

        if report is not None:
            chips_row([
                badge("Validation", "accent"),
                badge(f"{report['error_count']} errors",
                      "danger" if report["error_count"] else "success"),
                badge(f"{report['warning_count']} warnings",
                      "warning" if report["warning_count"] else "muted"),
            ])

        st.session_state.sensitivity = sensitivity

        if get_analysis_status() == ANALYSIS_RUNNING:
            loading_panel(
                f"Analyzing {dataset_name} at {sensitivity} sensitivity",
                sub="Deterministic operational analysis is running. Results appear "
                    "automatically on every page once it completes.",
            )
            skeleton_cards(4)
            # The pipeline is one indivisible call, so the checklist shows a
            # single active stage — no invented per-step progress.
            stage_checklist(
                "Pipeline status",
                [("Deterministic pipeline", "active")],
                sub="One execution covers validation → analytics → anomaly "
                    "detection → insights → evidence pack.",
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
         "computed by the deterministic analytics service", render_analytics,
         icon="monitoring", eyebrow="Data")
