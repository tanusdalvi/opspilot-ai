"""Evidence page — the citable evidence pack and optional AI investigation (Phase 8)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import orchestrator  # noqa: E402
from app.state import require_artifacts, run_page  # noqa: E402


def _show_investigation(result: dict) -> None:
    status = result.get("status")
    st.markdown(f"Investigation status: **{status}**")
    if status == "narrative_rejected":
        st.warning(
            "The generated narrative failed grounding validation and was "
            "rejected. The deterministic evidence pack below remains the "
            "source of truth."
        )
    narrative = result.get("narrative") or {}
    if narrative.get("executive_summary"):
        st.markdown("**Executive summary (AI-generated, grounded)**")
        st.write(narrative["executive_summary"])
    findings = narrative.get("key_findings") or []
    for finding in findings:
        st.markdown(f"- {finding.get('claim')} {' '.join(finding.get('evidence_ids') or [])}")
    hypotheses = result.get("hypotheses") or []
    if hypotheses:
        with st.expander(f"Hypotheses ({len(hypotheses)})"):
            st.dataframe(hypotheses, use_container_width=True)
    citations = result.get("citations") or []
    if citations:
        with st.expander(f"Citations ({len(citations)})"):
            st.dataframe(citations, use_container_width=True)
    grounding = result.get("grounding_report") or {}
    with st.expander("Grounding report", expanded=not grounding.get("valid", True)):
        st.json(grounding)


def render_evidence() -> None:
    artifacts = require_artifacts()
    if artifacts is None:
        return
    pack = artifacts.pack

    st.subheader("Evidence pack")
    st.caption(
        f"Type `{pack['type']}` · schema version `{pack['schema_version']}` · "
        f"sensitivity `{pack['parameters']['sensitivity']}`"
    )

    left, right = st.columns([1, 2])
    with left:
        st.markdown("**KPI context**")
        st.json({k: pack["kpis"][k] for k in sorted(pack["kpis"])})
        st.markdown("**Parameters**")
        st.json(pack["parameters"])
    with right:
        changes = pack["period_comparison"]["changes_pct"]
        st.markdown("**Period comparison (change %)**")
        st.dataframe(
            [{"metric": k.replace("_change_pct", ""), "change_pct": v}
             for k, v in sorted(changes.items())],
            use_container_width=True,
            hide_index=True,
        )
        st.markdown(f"**Anomalies:** {len(pack['anomalies'])} · "
                    f"**Insights:** {len(pack['insights'])} · "
                    f"**Groups:** {len(pack['groups']['groups'])}")

    st.divider()
    st.subheader(f"Evidence index ({len(pack['evidence_index'])} citable entries)")
    evidence_rows = [
        {"id": ev_id, "kind": entry.get("kind"), "label": entry.get("label"),
         "value": entry.get("value")}
        for ev_id, entry in sorted(pack["evidence_index"].items(),
                                   key=lambda kv: str(kv[0]))
    ]
    st.dataframe(evidence_rows, use_container_width=True)
    st.caption(
        "Citations use the [E<id>] format shown above. Every claim in an AI "
        "narrative must cite these ids; the grounding validator rejects "
        "anything else."
    )

    st.divider()
    st.subheader("Optional AI investigation")
    if not orchestrator.investigation_available():
        st.info(
            "AI investigation unavailable — GEMINI_API_KEY is not configured.\n\n"
            "Deterministic analysis remains fully available: the evidence pack "
            "above contains every number the AI would be allowed to cite."
        )
        return

    if st.button("Run AI investigation", type="secondary"):
        with st.spinner("Running AI investigation..."):
            try:
                result = orchestrator.run_investigation(pack)
                st.session_state.investigation_result = result
            except Exception as exc:
                st.session_state.investigation_result = None
                st.error(f"AI investigation failed ({type(exc).__name__}). "
                         "The deterministic evidence pack remains authoritative.")
    stored = st.session_state.get("investigation_result")
    if stored:
        _show_investigation(stored)


run_page("Evidence", "Aggregate-only investigation context with a fully citable "
         "evidence index", render_evidence)
