"""Data page — dataset selection, CSV upload, validation gate (Phase 11B).

Functional contract unchanged: derived artifacts reset on every newly
activated dataset, uploads are staged via the orchestrator only, and
validation is read-only with errors blocking analysis. The dataset
identity card is a presentation-only summary of the loaded frame.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import orchestrator  # noqa: E402
from app.state import run_page  # noqa: E402
from app.ui.components import (  # noqa: E402
    badge,
    chips_row,
    empty_state,
    metric_row,
    section,
)
from app.ui.icons import escape_label  # noqa: E402
from core.constants import UPLOAD_ROW_ADVISORY  # noqa: E402

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


def _date_coverage(df) -> str | None:
    """Presentation-only date span derived from a parseable date column."""
    if "date" not in df.columns:
        return None
    parsed = None
    try:
        import pandas as pd

        parsed = pd.to_datetime(df["date"], errors="coerce")
    except Exception:  # noqa: BLE001 - any parsing failure means no coverage
        return None
    parsed = parsed.dropna()
    if parsed.empty:
        return None
    return f"{parsed.min():%Y-%m-%d} → {parsed.max():%Y-%m-%d}"


def _identity_card(name: str, df) -> None:
    """Dataset identity card: shape, footprint, coverage, column profile."""
    memory_mb = float(df.memory_usage(deep=True).sum()) / (1024 * 1024)
    chips_row([
        badge(f"active · {name}", "accent"),
        badge(f"{memory_mb:.2f} MiB in memory", "muted"),
    ])
    coverage = _date_coverage(df)
    metric_row([
        dict(label="Rows", value=f"{len(df):,}", icon="table"),
        dict(label="Columns", value=df.shape[1], icon="grid"),
        dict(label="Memory", value=f"{memory_mb:.2f} MiB", icon="cpu"),
        dict(label="Date range", value=coverage or "—", icon="calendar"),
    ], columns=4)

    with st.expander("Column profile"):
        profile = []
        for column in df.columns:
            series = df[column]
            missing = int(series.isna().sum())
            profile.append({
                "column": str(column),
                "dtype": str(series.dtype),
                "missing": f"{missing:,}",
                "unique": f"{int(series.nunique(dropna=True)):,}",
            })
        st.dataframe(profile, width="stretch", hide_index=True)


def _show_report(report: dict) -> None:
    metric_row([
        dict(label="Rows", value=f"{report['row_count']:,}", icon="table"),
        dict(label="Columns", value=report["column_count"], icon="grid"),
        dict(label="Errors", value=report["error_count"], icon="x-circle",
             delta_tone="bad" if report["error_count"] else "good"),
        dict(label="Warnings", value=report["warning_count"], icon="alert-triangle"),
    ], columns=4)
    for kind in ("errors", "warnings"):
        issues = report[kind]
        if not issues:
            continue
        tone = {"errors": "danger", "warnings": "warning"}[kind]
        with st.expander(
            f"{kind.capitalize()} ({len(issues)})",
            expanded=kind == "errors",
        ):
            chips_row([badge(issue["code"], tone) for issue in issues[:12]])
            rows = [
                {
                    "code": issue["code"],
                    "message": issue["message"],
                    "column": issue.get("column") or "—",
                    "rows": ", ".join(map(str, issue.get("rows") or [])) or "—",
                }
                for issue in issues
            ]
            st.dataframe(rows, width="stretch", hide_index=True)


def render_data() -> None:
    with st.container(border=True):
        section("Choose a source", icon="database",
                caption="Demo datasets ship with the project; uploads stay local")
        source = st.radio(
            "Source", ["Demo dataset", "Upload CSV"],
            horizontal=True, label_visibility="collapsed",
        )

        if source == "Demo dataset":
            datasets = orchestrator.list_demo_datasets()
            if not datasets:
                empty_state("database", "No demo datasets found",
                            "Place canonical CSV files under data/demo/ and "
                            "they will appear here.")
                return
            options = [d["name"] for d in datasets]
            choice = st.selectbox("Available demo datasets", options)
            size = next(d["size_bytes"] for d in datasets if d["name"] == choice)
            chips_row([
                badge(f"{choice}", "accent"),
                badge(f"{size:,} bytes", "muted"),
            ])
            if st.button("Load demo dataset", type="primary",
                         icon=":material/database:", width="stretch"):
                with st.spinner("Loading dataset..."):
                    df = orchestrator.load_demo_dataset(choice)
                _activate_dataset(df, choice)
                st.toast(f"Loaded **{choice}**.", icon=":material/check_circle:")
        else:
            upload = st.file_uploader("Upload a canonical operational CSV", type="csv")
            st.caption(
                "Required columns: date, region, product, units_sold, revenue, "
                "cost, lead_time_days. Uploads are staged under gitignored "
                "data/uploads/ and never persisted to the audit store. "
                f"Maximum size: {orchestrator.MAX_UPLOAD_BYTES // (1024 * 1024)} MiB; "
                "re-uploading the same filename replaces the staged copy."
            )
            if upload is not None and st.button("Load uploaded file", type="primary",
                                                icon=":material/upload:",
                                                width="stretch"):
                with st.spinner("Loading dataset..."):
                    content = upload.getvalue()
                    df = orchestrator.load_uploaded_dataset(upload.name, content)
                _activate_dataset(df, upload.name)
                st.toast(f"Loaded **{upload.name}**.", icon=":material/check_circle:")

    # Session state is the single source of truth after every Streamlit rerun.
    df = st.session_state.get("df")
    name = st.session_state.get("dataset_name")
    if df is None or not name:
        empty_state(
            "layers", "No active dataset",
            "Load a demo dataset or upload a CSV to begin. Loading a dataset "
            "never runs analysis by itself.",
            cta_label=None,
        )
        return

    section(f"Active · {escape_label(str(name))}", icon="check-circle",
            caption="A new dataset invalidates all previous results")

    if len(df) > UPLOAD_ROW_ADVISORY:
        st.warning(
            f"This dataset has {len(df):,} rows (above the "
            f"{UPLOAD_ROW_ADVISORY:,}-row advisory). It will still load and "
            "analyze normally, but analysis may take noticeably longer."
        )

    _identity_card(name, df)

    with st.container(border=True):
        section("Validation gate", icon="flask",
                caption="Read-only: no rows are dropped or imputed; errors block analysis")
        if st.button("Validate dataset", type="primary", icon=":material/science:"):
            with st.spinner("Validating dataset..."):
                report = orchestrator.validate_dataset(df)
            st.session_state.validation_report = report

        report = st.session_state.get("validation_report")
        if report is not None:
            _show_report(report)
            if report["valid"]:
                st.success("Dataset is valid — ready for analysis.")
                st.page_link("pages/analytics.py", label="Continue → Analytics",
                             icon=":material/monitoring:")
            else:
                st.error(
                    "Validation failed. Errors block analysis; fix the data or "
                    "choose another file. No rows are dropped or imputed."
                )


run_page("Data", "Load a demo dataset or upload a CSV, then validate it before "
         "any analysis runs", render_data, icon="database", eyebrow="Data")
