"""Thin application orchestration layer for OpsPilot AI (Phase 8).

Coordinates the existing, tested services into the exact application
sequence. This module implements **no business rules**: it validates
datasets through ``services.validation_service``, computes analytics
through ``services.analytics_service``, detects anomalies and explains
them through ``services.anomaly_service``/``services.insight_service``,
assembles evidence through ``agent.evidence``, generates plans through
``agent.recommendation_service``, applies reviews through
``agent.review_service``, and persists through ``database.repository``.

Every function here is a deterministic composition of deterministic
services — the only exception is :func:`run_investigation`, which is
optional, explicit, and never influences scores, statuses, or storage.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.evidence import build_investigation_context
from agent.recommendation_service import generate_recommendations as _generate_plan
from agent.review_service import (
    approve_recommendation,
    reject_recommendation,
    request_changes,
    resubmit_recommendation,
)
from core.config import DATA_DIR
from core.exceptions import ConfigurationError, DataValidationError
from database import repository
from services.analytics_service import (
    calculate_daily_trends,
    calculate_period_comparison,
    calculate_product_performance,
    calculate_region_performance,
)
from services.anomaly_service import summarize_anomalies
from services.data_service import load_csv, load_dataset
from services.validation_service import ensure_valid, validate_dataframe

# Directory for staged CSV uploads (gitignored via data/uploads/).
UPLOAD_DIR: Path = DATA_DIR / "uploads"

# Explicit reviewer decisions understood by apply_review.
REVIEW_DECISIONS: tuple[str, ...] = ("APPROVE", "REJECT", "REQUEST_CHANGES", "RESUBMIT")

_REVIEW_HANDLERS = {
    "APPROVE": approve_recommendation,
    "REJECT": reject_recommendation,
    "REQUEST_CHANGES": request_changes,
    "RESUBMIT": resubmit_recommendation,
}


@dataclass
class AnalysisArtifacts:
    """Bundle of every deterministic artifact produced by one analysis run."""

    dataset_name: str
    df: pd.DataFrame
    validation_report: dict
    kpis: dict
    region_performance: pd.DataFrame
    product_performance: pd.DataFrame
    daily_trends: pd.DataFrame
    period_comparison: dict
    top_performers: dict
    bottom_performers: dict
    anomaly_result: dict
    anomaly_summary: dict
    insights: list
    grouping: dict
    pack: dict

    @property
    def anomalies(self) -> list:
        return self.anomaly_result["anomalies"]

    @property
    def groups(self) -> list:
        return self.grouping["groups"]


# --- dataset loading --------------------------------------------------------------------


def list_demo_datasets() -> list[dict]:
    """Return metadata for the bundled demo datasets."""
    from services.data_service import list_datasets

    return list_datasets()


def load_demo_dataset(filename: str) -> pd.DataFrame:
    """Load a demo dataset by filename (delegates to data_service)."""
    return load_dataset(filename)


def stage_upload(filename: object, content: bytes) -> Path:
    """Stage uploaded CSV bytes under the gitignored ``data/uploads/`` directory.

    Only the base filename is kept; parent-path components are dropped so
    an upload can never escape the uploads directory.

    Returns:
        Path of the staged file, ready for :func:`load_csv`.
    """
    if not isinstance(filename, str) or not filename.strip():
        raise DataValidationError("Uploaded file has no name")
    if not isinstance(content, bytes) or len(content) == 0:
        raise DataValidationError("Uploaded file is empty")
    safe_name = Path(filename).name
    if Path(safe_name).suffix.lower() != ".csv":
        raise DataValidationError(f"Only CSV uploads are supported; got {safe_name!r}")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / safe_name
    target.write_bytes(content)
    return target


def load_uploaded_dataset(filename: object, content: bytes) -> pd.DataFrame:
    """Stage and load an uploaded CSV into a DataFrame."""
    return load_csv(stage_upload(filename, content))


# --- validation gate ----------------------------------------------------------------------


def validate_dataset(df: object) -> dict:
    """Validate a DataFrame without raising on quality problems."""
    report = validate_dataframe(df)
    if not isinstance(report, dict):
        raise DataValidationError("Unexpected validation report shape")
    return report


def require_valid_dataset(df: object) -> dict:
    """Hard gate: validate ``df`` and raise when it contains errors."""
    return ensure_valid(df)


# --- analysis pipeline ---------------------------------------------------------------------


def run_pipeline(
    df: pd.DataFrame,
    *,
    dataset_name: str = "dataset",
    sensitivity: str = "medium",
    focus: dict | None = None,
) -> AnalysisArtifacts:
    """Run the complete deterministic analysis pipeline exactly once.

    The expensive deterministic work happens in a single pass inside
    ``build_investigation_context`` (KPIs, period comparison, performer
    rankings, metric contexts, anomaly detection, explanations, and
    grouping). Every artifact the evidence pack already contains is
    reused from it; only the three rendering tables the pack does not
    carry (region/product performance and daily trends) are computed
    separately.

    Sequence:

    1. ``ensure_valid``            — hard validation gate (fast fail)
    2. ``build_investigation_context`` — one full pass over the dataset;
       yields the pack plus KPIs, comparison, performers, anomalies,
       insights, and groups
    3. rendering tables            — region/product performance and
       daily trends (absent from the aggregate-only pack)

    Raises:
        DataValidationError: If the dataset fails validation or any
            service rejects its inputs. Invalid datasets never reach
            analysis.
    """
    report = require_valid_dataset(df)
    pack = build_investigation_context(df, sensitivity=sensitivity, focus=focus)
    anomalies = pack["anomalies"]
    summary = summarize_anomalies(anomalies)
    period_comparison = pack["period_comparison"]
    if period_comparison is None:
        # Degenerate (< two dates) dataset: reproduce the hard failure
        # the direct call always raised instead of rendering ``None``.
        period_comparison = calculate_period_comparison(df)
    return AnalysisArtifacts(
        dataset_name=dataset_name,
        df=df,
        validation_report=report,
        kpis=pack["kpis"],
        region_performance=calculate_region_performance(df),
        product_performance=calculate_product_performance(df),
        daily_trends=calculate_daily_trends(df),
        period_comparison=period_comparison,
        top_performers=pack["top_performers"],
        bottom_performers=pack["bottom_performers"],
        anomaly_result={
            "anomalies": anomalies,
            "total_count": len(anomalies),
            "by_severity": dict(summary["by_severity"]),
            "sensitivity": pack["parameters"]["sensitivity"],
            "metrics_analyzed": list(pack["parameters"]["metrics"]),
        },
        anomaly_summary=summary,
        insights=pack["insights"],
        grouping=pack["groups"],
        pack=pack,
    )


# --- recommendations ------------------------------------------------------------------------


def generate_plan(
    df_or_context: object,
    *,
    investigation: dict | None = None,
    max_recommendations: int | None = None,
) -> dict:
    """Generate the deterministic recommendation plan (thin delegation)."""
    return _generate_plan(
        df_or_context, investigation=investigation, max_recommendations=max_recommendations
    )


# --- human review ------------------------------------------------------------------------------


def apply_review(
    decision: object,
    recommendation: dict,
    *,
    reviewer_id: object,
    comment: object = None,
    occurred_at: object = None,
) -> tuple[dict, dict]:
    """Apply one reviewer decision through the real Phase 6 service.

    Dispatches to the matching ``agent.review_service`` wrapper; this
    module never mutates recommendation records itself.

    Returns:
        ``(updated_record, review_event)`` exactly as produced by the
        service.
    """
    handler = _REVIEW_HANDLERS.get(decision) if isinstance(decision, str) else None
    if handler is None:
        raise DataValidationError(
            f"decision must be one of {list(REVIEW_DECISIONS)}; got {decision!r}"
        )
    return handler(
        recommendation, reviewer_id=reviewer_id, comment=comment, occurred_at=occurred_at
    )


# --- optional AI investigation -------------------------------------------------------------------


def investigation_available() -> bool:
    """Return True when Gemini is configured (key presence only)."""
    from core.config import has_gemini_api_key

    return bool(has_gemini_api_key())


def run_investigation(pack: dict, *, client: object = None) -> dict:
    """Run one evidence-grounded investigation (explicit user action only).

    Args:
        pack: Evidence pack produced by the pipeline.
        client: Optional pre-built client (tests inject fakes). Defaults
            to :class:`GeminiNarratorClient`, which requires
            ``GEMINI_API_KEY``.

    Raises:
        ConfigurationError: When no key/client is available.
    """
    if client is None and not investigation_available():
        raise ConfigurationError(
            "AI investigation unavailable — GEMINI_API_KEY is not configured. "
            "Deterministic analysis remains fully usable."
        )
    from agent.gemini_client import GeminiNarratorClient

    resolved = client if client is not None else GeminiNarratorClient()
    from agent.investigator import investigate

    return investigate(pack, client=resolved)


# --- persistence helpers ---------------------------------------------------------------------------


def should_record_plan(existing_plan_id: object) -> bool:
    """Persistence-once rule: record a plan only when no id exists yet.

    Streamlit reruns pages constantly; pages consult this helper before
    calling :func:`persist_plan` so a rendered page can never create
    duplicate plan rows.
    """
    return existing_plan_id is None


def persist_plan(engine, plan: dict) -> int:
    """Record one generated plan in the append-only audit store."""
    return repository.record_plan(engine, plan)


def persist_review(engine, updated_record: dict, event: dict) -> tuple[int, int]:
    """Record one completed review (snapshot + event) atomically."""
    return repository.record_review(engine, updated_record, event)


__all__ = [
    "AnalysisArtifacts",
    "REVIEW_DECISIONS",
    "apply_review",
    "generate_plan",
    "investigation_available",
    "load_demo_dataset",
    "load_uploaded_dataset",
    "list_demo_datasets",
    "persist_plan",
    "persist_review",
    "require_valid_dataset",
    "run_investigation",
    "run_pipeline",
    "should_record_plan",
    "stage_upload",
    "validate_dataset",
]
