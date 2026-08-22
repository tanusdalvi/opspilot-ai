"""Data page — dataset selection, CSV upload, validation gate (Phase 8)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import orchestrator  # noqa: E402
from app.state import run_page  # noqa: E402

# Derived artifacts invalidated whenever a new dataset becomes active.
# ``analysis_status`` resets to its IDLE default: a fresh dataset means
# any previous analysis no longer describes the active data.
_DOWNSTREAM_KEYS = (
    "analysis_artifacts",
    "analysis_status",
    "analysis_error",
    "investigation_result",
    "plan",
    "plan_id",
    "selected_recommendation_id",
    "validation_report",
)


def _reset_downstream() -> None:
    """Drop derived artifacts so stale results can never be displayed."""
    for key in _DOWNSTREAM_KEYS:
        st.session_state.pop(key, None)


def _activate_dataset(df, name: str) -> None:
    """Persist the freshly loaded dataset in session state (rerun-safe)."""
    _reset_downstream()
    st.session_state.df = df
    st.session_state.dataset_name = name


def _show_report(report: dict) -> None:
    col = st.columns(4)
    col[0].metric("Rows", f"{report['row_count']:,}")
    col[1].metric("Columns", report["column_count"])
    col[2].metric("Errors", report["error_count"])
    col[3].metric("Warnings", report["warning_count"])
    for kind in ("errors", "warnings"):
        issues = report[kind]
        if not issues:
            continue
        icon = "🚫" if kind == "errors" else "⚠️"
        with st.expander(f"{icon} {kind.capitalize()} ({len(issues)})",
                         expanded=kind == "errors"):
            rows = [
                {
                    "code": issue["code"],
                    "message": issue["message"],
                    "column": issue.get("column") or "—",
                    "rows": ", ".join(map(str, issue.get("rows") or [])) or "—",
                }
                for issue in issues
            ]
            st.dataframe(rows, use_container_width=True)


def render_data() -> None:
    with st.container(border=True):
        st.subheader("1 · Choose a dataset")
        source = st.radio(
            "Source", ["Demo dataset", "Upload CSV"],
            horizontal=True, label_visibility="collapsed",
        )

        if source == "Demo dataset":
            datasets = orchestrator.list_demo_datasets()
            if not datasets:
                st.info("No demo datasets found in data/demo/.")
                return
            options = [d["name"] for d in datasets]
            choice = st.selectbox("Available demo datasets", options)
            size = next(d["size_bytes"] for d in datasets if d["name"] == choice)
            st.caption(f"`{choice}` · {size:,} bytes")
            if st.button("Load demo dataset", type="primary", icon="📥"):
                with st.spinner("Loading dataset..."):
                    df = orchestrator.load_demo_dataset(choice)
                _activate_dataset(df, choice)
                st.toast(f"Loaded **{choice}**.", icon="✅")
        else:
            upload = st.file_uploader("Upload a canonical operational CSV", type="csv")
            st.caption(
                "Required columns: date, region, product, units_sold, revenue, "
                "cost, lead_time_days. Uploads are staged under gitignored "
                "data/uploads/ and never persisted to the audit store."
            )
            if upload is not None and st.button("Load uploaded file", type="primary",
                                                icon="📤"):
                with st.spinner("Loading dataset..."):
                    content = upload.getvalue()
                    df = orchestrator.load_uploaded_dataset(upload.name, content)
                _activate_dataset(df, upload.name)
                st.toast(f"Loaded **{upload.name}**.", icon="✅")

    # Session state is the single source of truth after every Streamlit rerun.
    df = st.session_state.get("df")
    name = st.session_state.get("dataset_name")
    if df is None or not name:
        st.info("Load a demo dataset or upload a CSV to begin.")
        return

    st.divider()
    active_cols = st.columns([3, 1, 1])
    active_cols[0].markdown(f"**Active dataset**  \n`{name}`")
    active_cols[1].metric("Rows", f"{len(df):,}")
    active_cols[2].metric("Columns", df.shape[1])

    with st.container(border=True):
        st.subheader("2 · Validate")
        st.caption(
            "Validation is read-only: no rows are dropped or imputed, and "
            "errors block any downstream analysis."
        )
        if st.button("Validate dataset", type="primary", icon="🧪"):
            with st.spinner("Validating dataset..."):
                report = orchestrator.validate_dataset(df)
            st.session_state.validation_report = report

        report = st.session_state.get("validation_report")
        if report is not None:
            _show_report(report)
            if report["valid"]:
                st.success("Dataset is valid — ready for analysis.")
                st.page_link("pages/overview.py", label="Continue → Overview",
                             icon="➡️")
            else:
                st.error(
                    "Validation failed. Errors block analysis; fix the data or "
                    "choose another file. No rows are dropped or imputed."
                )


run_page("Data", "Load a demo dataset or upload a CSV, then validate it before "
         "any analysis runs", render_data)
