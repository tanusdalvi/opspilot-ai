"""Evidence page — the investigation workspace (Phase 11B).

The deterministic evidence pack stays the single source of truth and
remains visually authoritative; the optional Gemini investigation is a
clearly separated, explicitly started layer. Functional contract
unchanged from Phase 8/9/10B: citations use [E<id>] ids and grounding
validation rejects ungrounded narratives.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from app import orchestrator  # noqa: E402
from app.state import require_artifacts, run_page  # noqa: E402
from app.ui.charts import diverging_pct  # noqa: E402
from app.ui.components import (  # noqa: E402
    badge,
    chips_row,
    empty_state,
    metric_row,
    section,
    stage_checklist,
)
from app.ui.icons import escape_label  # noqa: E402


def _show_investigation(result: dict) -> None:
    status = result.get("status")
    chips_row([
        badge("AI investigation", "ai"),
        badge(str(status), "success" if status == "complete" else "warning"),
    ])
    if status == "narrative_rejected":
        st.warning(
            "The generated narrative failed grounding validation and was "
            "rejected. The deterministic evidence pack remains the "
            "source of truth."
        )
    narrative = result.get("narrative") or {}
    if narrative.get("executive_summary"):
        with st.container(border=True):
            st.markdown("**Executive summary**  \n*AI-generated, grounded*")
            st.write(narrative["executive_summary"])
    findings = narrative.get("key_findings") or []
    for finding in findings:
        ids = "".join(
            f" {badge(eid, 'accent')}" for eid in (finding.get("evidence_ids") or [])
        )
        st.markdown(
            f"- {finding.get('claim')} {ids}",
            unsafe_allow_html=True,
        )
    hypotheses = result.get("hypotheses") or []
    citations = result.get("citations") or []
    if hypotheses or citations:
        tab_h, tab_c = st.tabs(
            ["Hypotheses" + (f" ({len(hypotheses)})" if hypotheses else ""),
             "Citations" + (f" ({len(citations)})" if citations else "")])
        with tab_h:
            if hypotheses:
                st.dataframe(hypotheses, width="stretch", hide_index=True)
            else:
                st.caption("No hypotheses returned.")
        with tab_c:
            if citations:
                st.dataframe(citations, width="stretch", hide_index=True)
            else:
                st.caption("No citations returned.")
    grounding = result.get("grounding_report") or {}
    valid = grounding.get("valid", True)
    with st.expander("Grounding report", expanded=not valid):
        st.json(grounding)


def _format_kpi(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, float):
        if abs(value) >= 1000:
            return f"{value:,.0f}"
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def render_evidence() -> None:
    artifacts = require_artifacts()
    if artifacts is None:
        return
    pack = artifacts.pack

    # --- workspace header --------------------------------------------------------------------------
    index_size = len(pack["evidence_index"])
    sensitivity = pack["parameters"]["sensitivity"]
    ai_ready = orchestrator.investigation_available()
    stored_result = st.session_state.get("investigation_result")

    header_left, header_right = st.columns([2.4, 3])
    with header_left:
        section("Investigation workspace", icon="fact_check",
                caption="Aggregate-only context; every claim must cite this pack")
        chips_row([
            badge(f"Evidence pack · {pack['type']}", "accent"),
            badge(f"{index_size} references", "muted"),
            badge(f"sensitivity · {sensitivity}",
                  "warning" if sensitivity == "high" else "info"),
            badge(f"schema v{pack['schema_version']}", "muted"),
        ])
    with header_right:
        stages = [
            ("Evidence prepared", "done"),
            ("Signals analyzed", "done"),
            ("Evidence indexed", "done"),
        ]
        if stored_result:
            stages.append(("AI investigation", "done"))
        elif ai_ready:
            stages.append(("AI investigation", "active"))
        stage_checklist(
            "Investigation status",
            stages,
            sub=("Deterministic stages are complete. The AI step runs only "
                 "when you start it." if ai_ready else
                 "Deterministic stages are complete; AI is not configured."),
        )

    left, right = st.columns([2, 3])
    with left:
        section("KPI context", icon="target")
        kpis = pack["kpis"]
        metric_row(
            [dict(label=str(k).replace("_", " ").title(), value=_format_kpi(kpis[k]),
                  icon="grid")
             for k in sorted(kpis)],
            columns=2,
        )
        section("Parameters", icon="tune")
        params = pack["parameters"]
        chips_row([
            badge(f"{k} · {params[k]}", "muted") for k in sorted(params)
        ])
    with right:
        section("Period comparison", icon="clock", caption="change % between halves")
        changes = pack["period_comparison"]["changes_pct"]
        st.altair_chart(diverging_pct(changes), width="stretch")

    # --- searchable evidence index -------------------------------------------------------------------
    section(f"Evidence index · {index_size}", icon="search",
            caption="Claims must cite these [E<id>] entries")
    search_col, kind_col = st.columns([3, 1.4])
    query = search_col.text_input("Search the index",
                                  placeholder="id, label or value…",
                                  label_visibility="collapsed")
    all_rows = [
        {"id": ev_id, "kind": entry.get("kind"), "label": entry.get("label"),
         "value": entry.get("value")}
        for ev_id, entry in sorted(pack["evidence_index"].items(),
                                   key=lambda kv: str(kv[0]))
    ]
    kinds = ["All kinds"] + sorted({str(row["kind"]) for row in all_rows})
    chosen_kind = kind_col.selectbox("Category", kinds, label_visibility="collapsed")

    filtered = [
        row for row in all_rows
        if (chosen_kind == "All kinds" or str(row["kind"]) == chosen_kind)
        and (not query or query.lower() in str(
            (row["id"], row["kind"], row["label"], row["value"])).lower())
    ]
    st.caption(f"{len(filtered)} of {index_size} references shown.")
    st.dataframe(
        filtered,
        width="stretch",
        hide_index=True,
        column_config={"id": st.column_config.TextColumn("Id")},
    )
    st.caption(
        "Citations use the [E<id>] format shown above. Every claim in an AI "
        "narrative must cite these ids; the grounding validator rejects "
        "anything else."
    )

    # --- optional AI layer (visually separate) ---------------------------------------------------------
    section("Optional AI explanation", icon="sparkle",
            caption="Explicit action; deterministic evidence stays authoritative")
    if not ai_ready:
        empty_state(
            "sparkle", "AI investigation unavailable",
            "GEMINI_API_KEY is not configured. Deterministic analysis remains "
            "fully available: the evidence pack contains every number the AI "
            "would be allowed to cite.",
        )
        return

    if st.button("Run AI investigation", type="secondary",
                 icon=":material/play_arrow:"):
        with st.spinner("Running AI investigation..."):
            try:
                result = orchestrator.run_investigation(pack)
                st.session_state.investigation_result = result
            except Exception as exc:  # noqa: BLE001 - same boundary as before
                st.session_state.investigation_result = None
                st.session_state.investigation_error = type(exc).__name__
    if "investigation_error" in st.session_state:
        error_name = st.session_state.pop("investigation_error")
        st.warning(
            "**AI investigation unavailable** — the request could not be "
            "completed.\n\nYour deterministic evidence pack remains fully "
            "available above; nothing about it depends on the AI layer."
        )
        st.caption(f"Failure class: {error_name}. You can retry at any time.")
    stored = st.session_state.get("investigation_result")
    if stored:
        _show_investigation(stored)


run_page("Evidence", "Aggregate-only investigation context with a fully citable "
         "evidence index", render_evidence,
         icon="fact_check", eyebrow="Intelligence")
