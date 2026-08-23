"""Anomalies page — the anomaly command center (Phase 11B).

Detection results with severity/type/scope filters, per-signal cards
and an investigation detail panel per anomaly. Functional contract
unchanged from Phase 8: reads stored artifacts; filters are
presentation-only; related-signal grouping is a display heuristic
(same entity + metric), never a new detection rule.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from app.state import require_artifacts, run_page  # noqa: E402
from app.ui.charts import hbar_counts  # noqa: E402
from app.ui.components import (  # noqa: E402
    badge,
    chips_row,
    empty_state,
    metric_row,
    section,
    severity_badge,
)
from app.ui.icons import escape_label  # noqa: E402
from app.ui.theme import severity_color  # noqa: E402

SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def _anomaly_card(index: int, record: dict) -> str:
    severity = record.get("severity")
    color = severity_color(severity)
    deviation = record.get("deviation_pct")
    deviation_text = (
        f"{float(deviation):+.1f}%" if isinstance(deviation, (int, float)) else "—"
    )
    meta = "".join(
        f"<span class='ops-chip'>{escape_label(value)}</span>"
        for value in (
            record.get("type"), record.get("scope"),
            f"{record.get('metric')} · {record.get('entity')}",
            record.get("date"),
        )
        if value
    )
    return (
        f"<div class='ops-card ops-hover ops-sev-stripe' style='--ops-sev:{color}'>"
        "<div style='display:flex;justify-content:space-between;align-items:center;"
        "gap:8px;margin-bottom:6px'>"
        f"<span class='ops-mono' style='color:var(--ops-text-3)'>#{index}</span>"
        f"{severity_badge(severity)}</div>"
        f"<div style='display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px'>{meta}</div>"
        "<div class='ops-kv'>"
        f"<dt>Observed</dt><dd>{escape_label(record.get('value'))}</dd>"
        f"<dt>Expected</dt><dd>{escape_label(record.get('expected_value'))}</dd>"
        f"<dt>Deviation</dt><dd>{deviation_text}</dd>"
        f"<dt>Score</dt><dd>{escape_label(record.get('score'))}</dd>"
        "</div></div>"
    )


def _date_only(value) -> date | None:
    """Parse the ISO date prefix of a timestamp string (None if invalid)."""
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _related_anomalies(anomalies: list[dict], index: int,
                       limit: int = 4) -> list[tuple[int, dict]]:
    """Same entity+metric signals, nearest date first (display relation)."""
    anchor = _date_only(anomalies[index].get("date"))

    def sort_key(item: tuple[int, dict]):
        other_date = _date_only(item[1].get("date"))
        if anchor is None or other_date is None:
            return 10**9
        return abs((other_date - anchor).days)

    candidates = [
        (i, a) for i, a in enumerate(anomalies)
        if i != index
        and a.get("entity") == anomalies[index].get("entity")
        and a.get("metric") == anomalies[index].get("metric")
    ]
    return sorted(candidates, key=sort_key)[:limit]


def _anomaly_detail(index: int, record: dict, artifacts) -> None:
    """Expanded investigation panel for one signal."""
    deviation = record.get("deviation_pct")
    st.markdown(
        "**What happened**  \n"
        f"The {str(record.get('metric') or 'metric')} for "
        f"**{escape_label(str(record.get('entity') or record.get('scope') or 'the dataset'))}** "
        f"on **{escape_label(str(record.get('date') or 'the detected date'))}** read "
        f"`{escape_label(record.get('value'))}` against an expected baseline of "
        f"`{escape_label(record.get('expected_value'))}`"
        + (
            f" — a deviation of **{float(deviation):+.1f}%**."
            if isinstance(deviation, (int, float))
            else "."
        )
    )
    chips_row([
        badge(f"type · {record.get('type')}", "muted"),
        badge(f"scope · {record.get('scope')}", "muted"),
        badge(f"detection score · {record.get('score')}", "info"),
    ])
    localization = None
    for insight in getattr(artifacts, "insights", []) or []:
        if str(insight.get("metric")) == str(record.get("metric")) and (
            insight.get("entity") in (None, record.get("entity"))
        ):
            localization = insight.get("localization")
            break
    if localization:
        chips_row([
            badge("Localization", "ai"),
            badge(f"dimension · {localization.get('dimension')}", "muted"),
            badge(f"verdict · {localization.get('verdict')}", "info"),
        ])
    else:
        st.caption("No entity-level localization verdict exists for this signal.")
    st.caption(
        "Deterministic detectors establish that this value deviates from its "
        "baseline; they do not establish why. Correlational context lives on "
        "the Insights page; aggregate evidence lives in the evidence pack."
    )
    all_anomalies = getattr(artifacts, "anomalies", []) or []
    if len(all_anomalies) > 1:
        related = _related_anomalies(all_anomalies, index)
        if related:
            st.caption("**Related signals (same entity · metric, nearest dates)**")
            rows = [
                {"#": i, "date": a.get("date"), "severity": a.get("severity"),
                 "value": a.get("value"), "expected": a.get("expected_value"),
                 "deviation %": a.get("deviation_pct")}
                for i, a in related
            ]
            st.dataframe(rows, width="stretch", hide_index=True)
    st.page_link("pages/insights.py", label="Open correlational insights",
                 icon=":material/lightbulb:")


def render_anomalies() -> None:
    artifacts = require_artifacts()
    if artifacts is None:
        return

    result = artifacts.anomaly_result
    summary = artifacts.anomaly_summary
    by_sev = summary.get("by_severity") or {}

    section("Signal overview", icon="crisis_alert",
            caption="Deterministic detectors — no thresholds were tuned to this data")
    metric_row([
        dict(label=sev.title(), value=by_sev.get(sev, 0),
             icon="alert-octagon" if sev == "CRITICAL" else "activity",
             caption=f"{sev.lower()} signals")
        for sev in SEVERITY_ORDER
    ] + [
        dict(label="Total", value=result["total_count"], icon="grid",
             caption="all severities"),
    ], columns=5)

    breakdowns = {
        "By type": summary.get("by_type") or {},
        "By metric": summary.get("by_metric") or {},
        "By scope": summary.get("by_scope") or {},
    }
    non_empty = {label: counts for label, counts in breakdowns.items() if counts}
    if non_empty:
        section("Severity distribution", icon="grid",
                caption="Where the detected volume concentrates")
        cols = st.columns(len(non_empty))
        for col, (label, counts) in zip(cols, non_empty.items()):
            with col:
                st.caption(label)
                st.altair_chart(hbar_counts(counts), width="stretch")

    anomalies = artifacts.anomalies
    if not anomalies:
        empty_state(
            "check-circle", "No anomalies detected",
            "At the current sensitivity the deterministic detectors found "
            "nothing unusual. Try a different sensitivity on the Analytics page.",
        )
        return

    section(f"Anomaly explorer · {len(anomalies)}", icon="search")
    f1, f2, f3, f4 = st.columns([1.2, 1, 1, 1.4])
    severities = f1.multiselect(
        "Severity", list(SEVERITY_ORDER),
        default=[s for s in SEVERITY_ORDER
                 if s in {a.get("severity") for a in anomalies}],
    )
    metrics = sorted({str(a.get("metric")) for a in anomalies})
    scopes = sorted({str(a.get("scope")) for a in anomalies})
    chosen_metrics = f2.multiselect("Metric", metrics)
    chosen_scopes = f3.multiselect("Scope", scopes)
    search = f4.text_input("Search", placeholder="entity, metric or type…")

    def _matches_search(record: dict) -> bool:
        if not search:
            return True
        needle = search.lower()
        return any(
            needle in str(record.get(field) or "").lower()
            for field in ("entity", "metric", "type", "scope", "date")
        )

    rows = []
    for index, record in enumerate(anomalies):
        if severities and record.get("severity") not in severities:
            continue
        if chosen_metrics and record.get("metric") not in chosen_metrics:
            continue
        if chosen_scopes and record.get("scope") not in chosen_scopes:
            continue
        if not _matches_search(record):
            continue
        rows.append((index, record))

    st.caption(f"{len(rows)} of {len(anomalies)} anomaly records shown.")
    view = st.radio("View as", ["Cards", "Table"], horizontal=True,
                    label_visibility="collapsed")

    if view == "Table":
        st.dataframe(
            [
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
                for index, record in rows
            ],
            width="stretch",
            hide_index=True,
        )
        return

    batch_size = 3
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        cols = st.columns(batch_size)
        for col, (index, record) in zip(cols, batch):
            with col:
                st.markdown(_anomaly_card(index, record), unsafe_allow_html=True)

    section("Investigate a signal", icon="fact_check",
            caption="Full context panel for one selected anomaly")
    labels = [f"#{index} · {r.get('severity')} · {r.get('metric')} · "
              f"{r.get('entity')} · {r.get('date')}" for index, r in rows]
    detail_choice = st.selectbox("Signal", labels,
                                 label_visibility="collapsed")
    detail_index = rows[labels.index(detail_choice)][0] if labels else None
    if detail_index is not None:
        _anomaly_detail(detail_index, anomalies[detail_index], artifacts)


run_page("Anomalies", "Statistically detected spikes, drops and entity outliers "
         "(deterministic detectors)", render_anomalies,
         icon="crisis_alert", eyebrow="Intelligence")
