"""JSON serialization adapters for API responses (Phase 12).

Pure projection helpers: they convert existing engine outputs into
JSON-safe structures and never compute business values.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from app import orchestrator
from agent.gemini_client import DEFAULT_GEMINI_MODEL
from core.config import get_environment
from backend.api.sessions import (
    ANALYSIS_ERROR,
    ANALYSIS_IDLE,
    ANALYSIS_READY,
    ANALYSIS_RECOVERY_AVAILABLE,
    ANALYSIS_RUNNING,
    INVESTIGATION_RUNNING,
    effective_status,
)


def df_records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
    """DataFrame -> list of plain dicts (dates ISO-encoded, NaN -> null)."""
    if df is None:
        return []
    return json.loads(df.to_json(orient="records"))


def column_kind(series: pd.Series) -> str:
    """Presentational column typing for the Data Explorer (not analytics)."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    name_hint = str(series.name or "").lower()
    parsed = pd.to_datetime(
        series.head(20), errors="coerce", format="mixed"
    )
    if ("date" in name_hint or "time" in name_hint) and parsed.notna().sum() >= max(
        1, int(len(parsed) * 0.8)
    ):
        return "date"
    if series.nunique(dropna=True) <= max(1, min(30, len(series) // 2)):
        return "categorical"
    return "text"


def preview_payload(df: pd.DataFrame | None, limit: int = 500) -> dict[str, Any]:
    """Sample of the active dataset for visual exploration.

    Pure projection: a bounded head of rows plus one display ``kind`` per
    column. No analysis values are computed here.
    """
    if df is None:
        return {"columns": [], "rows": [], "total_rows": 0}
    bounded = df.head(max(1, min(int(limit), 1000)))
    columns = [
        {"name": str(col), "kind": column_kind(df[col])}
        for col in df.columns
    ]
    return {
        "columns": columns,
        "rows": json.loads(bounded.to_json(orient="records")),
        "total_rows": int(len(df)),
    }


def _wire_pack(pack: dict) -> dict:
    """Frontend view of the evidence pack.

    The full in-process pack feeds the server-side AI investigation.
    Over the wire, sections already serialized at the artifacts top
    level (anomalies, insights, groups, performers, metric contexts)
    are omitted — they would otherwise double the payload without
    adding information. Everything the interface reads (identity,
    parameters, citable evidence index, KPIs, period changes) stays.
    """
    return {
        "type": pack.get("type"),
        "schema_version": pack.get("schema_version"),
        "parameters": pack.get("parameters"),
        "kpis": pack.get("kpis"),
        "period_comparison": pack.get("period_comparison"),
        "evidence_index": pack.get("evidence_index"),
        "_omitted_sections": [
            "context",
            "top_performers",
            "bottom_performers",
            "anomalies",
            "insights",
            "groups",
            "narrative_instructions",
        ],
    }


def artifacts_payload(artifacts: orchestrator.AnalysisArtifacts) -> dict[str, Any]:
    """Project one AnalysisArtifacts bundle onto the wire format."""
    pack = artifacts.pack
    return {
        "dataset_name": artifacts.dataset_name,
        "validation_report": artifacts.validation_report,
        "kpis": artifacts.kpis,
        "period_comparison": artifacts.period_comparison,
        "top_performers": artifacts.top_performers,
        "bottom_performers": artifacts.bottom_performers,
        "anomaly_result": artifacts.anomaly_result,
        "anomaly_summary": artifacts.anomaly_summary,
        "insights": artifacts.insights,
        "grouping": artifacts.grouping,
        "findings": artifacts.findings,
        "pack": _wire_pack(pack),
        "region_performance": df_records(artifacts.region_performance),
        "product_performance": df_records(artifacts.product_performance),
        "daily_trends": df_records(artifacts.daily_trends),
        "row_count": int(len(artifacts.df)) if artifacts.df is not None else None,
        "posture": _posture(artifacts),
    }


def _posture(artifacts: orchestrator.AnalysisArtifacts) -> dict[str, Any] | None:
    """Signal Posture via the existing Phase 11B formula (adapter reuse).

    ``core.posture`` defines the one presentation transformation over
    detector output with no Streamlit dependency. The formula itself is
    NOT re-implemented.
    """
    if getattr(artifacts, "anomaly_summary", None) is None:
        return None
    try:
        from core.posture import posture_band, posture_score

        by_severity = (
            artifacts.anomaly_summary.get("by_severity")
            or (artifacts.anomaly_result or {}).get("by_severity")
            or {}
        )
        score = int(posture_score(dict(by_severity)))
        band_label, band_tone = posture_band(score)
        return {"score": score, "band": str(band_label), "tone": str(band_tone)}
    except Exception:  # noqa: BLE001 - presentation extra must never 500
        return None


def system_payload(session) -> dict[str, Any]:
    """Workspace context for the global shell (status, AI, recovery)."""
    status = effective_status(session)
    recovery = None
    if status == ANALYSIS_RECOVERY_AVAILABLE:
        recovery = orchestrator.load_recovery_context()
    dataset = None
    if session.df is not None:
        dataset = {
            "name": session.dataset_name,
            "source": getattr(session, "dataset_source", "upload"),
            "rows": int(len(session.df)),
            "columns": int(len(session.df.columns)),
            "memory_bytes": int(session.df.memory_usage(deep=True).sum()),
            "date_coverage": _date_coverage(session.df),
            "compatibility": getattr(session, "compatibility", None),
            "capability_profile": getattr(session, "capability_profile", None),
        }
    artifacts_ready = session.status == ANALYSIS_READY and session.artifacts is not None
    return {
        "session_token": session.token,
        "analysis_status": status,
        "analysis_error": session.analysis_error,
        "analysis_running": status == ANALYSIS_RUNNING,
        "artifacts_ready": artifacts_ready,
        "dataset": dataset,
        "ai_available": orchestrator.investigation_available(),
        "gemini_model": DEFAULT_GEMINI_MODEL,
        "investigation_status": session.investigation_status,
        "recovery_context": recovery,
        "lifecycle_stage": _lifecycle_stage(status, artifacts_ready, session),
        "environment": get_environment(),
    }


def _date_coverage(df: pd.DataFrame) -> dict[str, Any] | None:
    """First/last date span when a date-like column exists (display only)."""
    date_col = next(
        (col for col in df.columns if "date" in str(col).lower()), None
    )
    if date_col is None:
        return None
    series = pd.to_datetime(df[date_col], errors="coerce").dropna()
    if series.empty:
        return None
    return {
        "column": str(date_col),
        "first": series.min().strftime("%Y-%m-%d"),
        "last": series.max().strftime("%Y-%m-%d"),
        "days": int((series.max() - series.min()).days) + 1,
    }


def _lifecycle_stage(status: str, artifacts_ready: bool, session) -> str:
    """Map workspace state onto the seven-stage lifecycle rail label."""
    if status in (ANALYSIS_IDLE, ANALYSIS_RECOVERY_AVAILABLE):
        return "OBSERVE"
    if status == ANALYSIS_RUNNING:
        return "UNDERSTAND"
    if status == ANALYSIS_ERROR:
        return "DETECT"
    if not artifacts_ready:
        return "OBSERVE"
    if session.investigation_status == INVESTIGATION_RUNNING:
        return "INVESTIGATE"
    return "RECOMMEND"
