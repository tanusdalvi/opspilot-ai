"""Anomalies page — detection results with severity/type/scope filters (Phase 8)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.state import require_artifacts, run_page  # noqa: E402

SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def render_anomalies() -> None:
    artifacts = require_artifacts()
    if artifacts is None:
        return

    result = artifacts.anomaly_result
    summary = artifacts.anomaly_summary

    c = st.columns(4)
    by_sev = summary.get("by_severity") or {}
    for col, sev in zip(c, SEVERITY_ORDER):
        count = by_sev.get(sev, 0)
        col.metric(sev.title(), count)

    st.subheader("Breakdowns")
    b1, b2, b3 = st.columns(3)
    for col, (label, key) in zip(
        (b1, b2, b3),
        (("By type", "by_type"), ("By metric", "by_metric"), ("By scope", "by_scope")),
    ):
        counts = summary.get(key) or {}
        if counts:
            col.markdown(f"**{label}**")
            col.dataframe(
                [{"value": k, "count": v} for k, v in sorted(counts.items())],
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    st.subheader("Anomaly records")
    anomalies = artifacts.anomalies
    if not anomalies:
        st.success("No anomalies detected at the current sensitivity.")
        return

    f1, f2, f3 = st.columns(3)
    severities = st.multiselect(
        "Severity", list(SEVERITY_ORDER),
        default=[s for s in SEVERITY_ORDER if s in {a.get('severity') for a in anomalies}],
    )
    metrics = sorted({str(a.get("metric")) for a in anomalies})
    scopes = sorted({str(a.get("scope")) for a in anomalies})
    chosen_metrics = f2.multiselect("Metric", metrics)
    chosen_scopes = f3.multiselect("Scope", scopes)

    rows = []
    for index, record in enumerate(anomalies):
        if severities and record.get("severity") not in severities:
            continue
        if chosen_metrics and record.get("metric") not in chosen_metrics:
            continue
        if chosen_scopes and record.get("scope") not in chosen_scopes:
            continue
        rows.append(
            {
                "#": index,
                "severity": record.get("severity"),
                "type": record.get("type"),
                "scope": record.get("scope"),
                "metric": record.get("metric"),
                "entity": record.get("entity"),
                "date": record.get("date"),
                "value": record.get("value"),
                "expected": record.get("expected_value"),
                "deviation %": record.get("deviation_pct"),
                "score": record.get("score"),
            }
        )
    st.caption(f"{len(rows)} of {len(anomalies)} anomaly records shown.")
    st.dataframe(rows, use_container_width=True)


run_page("Anomalies", "Statistically detected spikes, drops and entity outliers "
         "(deterministic detectors)", render_anomalies)
