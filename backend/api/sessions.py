"""Session-scoped workspace state for the Phase 12 API.

Mirrors the Streamlit session lifecycle implemented in ``app.state``
(IDLE / RUNNING / READY / ERROR plus the derived RECOVERY_AVAILABLE)
without importing Streamlit: the lifecycle constants are duplicated as
literals with ``app.state`` kept as the documented source of truth, and
every transition rule is identical:

* loading a new dataset resets to IDLE (downstream artifacts dropped);
* an explicit run transitions RUNNING -> READY or RUNNING -> ERROR;
* a successful run refreshes the restart-recovery sidecar;
* recovery is derived (never stored) when a validated sidecar exists
  and the session holds no artifacts;
* the AI investigation runs only on explicit request and its result is
  cached per session until the next analysis supersedes it.

Sessions are process-local and keyed by an opaque token supplied by the
frontend; no personal data is stored.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app import orchestrator
from core.exceptions import (
    ConfigurationError,
    DataValidationError,
    OpsPilotError,
)
from core.logging import get_logger

logger = get_logger(__name__)

# Lifecycle literals — source of truth: app/state.py (kept in sync).
ANALYSIS_IDLE = "IDLE"
ANALYSIS_RUNNING = "ANALYZING"
ANALYSIS_READY = "READY"
ANALYSIS_ERROR = "ERROR"
ANALYSIS_RECOVERY_AVAILABLE = "RECOVERY_AVAILABLE"

INVESTIGATION_IDLE = "idle"
INVESTIGATION_RUNNING = "running"
INVESTIGATION_COMPLETE = "complete"
INVESTIGATION_ERROR = "error"


def get_investigation_client() -> object | None:
    """Return an injectable Gemini client, or ``None`` for production.

    Production constructs :class:`GeminiNarratorClient` implicitly via
    ``orchestrator.run_investigation``. Tests monkeypatch this function
    to inject fakes; no other seam is required.
    """
    return None


@dataclass
class WorkspaceSession:
    """All mutable UI state for one frontend session."""

    token: str
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # dataset layer
    df: pd.DataFrame | None = None
    dataset_name: str | None = None
    dataset_source: str = "upload"
    validation_report: dict | None = None
    # canonical-schema projection used by the pipeline (partial datasets)
    adapted_df: pd.DataFrame | None = None
    compatibility: dict | None = None
    capability_profile: dict | None = None

    # analysis lifecycle
    status: str = ANALYSIS_IDLE
    analysis_error: str | None = None
    artifacts: orchestrator.AnalysisArtifacts | None = None

    # recommendation plan (computed at most once per artifact set)
    plan: dict | None = None
    plan_persisted_id: int | None = None
    plan_source_artifacts_id: int | None = None

    # AI investigation
    investigation_status: str = INVESTIGATION_IDLE
    investigation_result: dict | None = None
    investigation_error: str | None = None


_SESSIONS: dict[str, WorkspaceSession] = {}
_REGISTRY_LOCK = threading.Lock()


def get_session(token: str | None) -> WorkspaceSession:
    """Return the session for ``token``, creating one when absent."""
    key = token or uuid.uuid4().hex
    with _REGISTRY_LOCK:
        session = _SESSIONS.get(key)
        if session is None:
            session = WorkspaceSession(token=key)
            _SESSIONS[key] = session
            logger.info("api_session_created sessions=%d", len(_SESSIONS))
        return session


def reset_dataset(session: WorkspaceSession, df: pd.DataFrame, name: str,
                  report: dict, adapted_df: pd.DataFrame | None = None,
                  compatibility: dict | None = None,
                  capability_profile: dict | None = None,
                  source: str = "upload") -> None:
    """Activate a newly loaded dataset; drops all downstream state."""
    with session.lock:
        session.df = df
        session.dataset_name = name
        session.dataset_source = source
        session.validation_report = report
        session.adapted_df = adapted_df
        session.compatibility = compatibility
        session.capability_profile = capability_profile
        session.status = ANALYSIS_IDLE
        session.analysis_error = None
        session.artifacts = None
        session.plan = None
        session.plan_persisted_id = None
        session.plan_source_artifacts_id = None
        session.investigation_status = INVESTIGATION_IDLE
        session.investigation_result = None
        session.investigation_error = None


def begin_analysis(session: WorkspaceSession) -> None:
    """Mark a pipeline run as started (mirrors app.state.begin_analysis)."""
    with session.lock:
        session.status = ANALYSIS_RUNNING
        session.analysis_error = None


def complete_analysis(session: WorkspaceSession,
                      artifacts: orchestrator.AnalysisArtifacts) -> None:
    """Store fresh artifacts; refresh the recovery sidecar (best effort)."""
    with session.lock:
        session.artifacts = artifacts
        session.status = ANALYSIS_READY
        session.analysis_error = None
        session.plan = None
        session.plan_persisted_id = None
        session.plan_source_artifacts_id = None
        session.investigation_status = INVESTIGATION_IDLE
        session.investigation_result = None
        session.investigation_error = None
    parameters = (artifacts.pack.get("parameters") or {}) if getattr(
        artifacts, "pack", None) else {}
    try:
        orchestrator.save_recovery_context(
            artifacts.dataset_name, str(parameters.get("sensitivity", "medium"))
        )
    except Exception as exc:  # noqa: BLE001 - recovery is never critical
        logger.warning("recovery_save_failed error_type=%s", type(exc).__name__)


def fail_analysis(session: WorkspaceSession, message: str) -> None:
    """Record a failed run with its safe reason (artifacts preserved)."""
    with session.lock:
        session.status = ANALYSIS_ERROR
        session.analysis_error = message


def effective_status(session: WorkspaceSession) -> str:
    """Resolve the stored status, deriving RECOVERY_AVAILABLE like the UI.

    Transient states are authoritative and are never masked: while a run
    is in flight (ANALYZING) or has just failed (ERROR), polling clients
    must observe exactly that — a stale recovery sidecar on disk must
    not hide an active lifecycle transition, or the frontend would stop
    polling mid-run and never learn the outcome. RECOVERY_AVAILABLE is
    derived only when the session is otherwise idle with no artifacts.
    """
    if session.status in (ANALYSIS_READY, ANALYSIS_RUNNING, ANALYSIS_ERROR):
        return session.status
    if session.artifacts is not None:
        return session.status
    context = orchestrator.load_recovery_context()
    if context and orchestrator.recovery_dataset_available(context):
        return ANALYSIS_RECOVERY_AVAILABLE
    return session.status


def run_analysis_sync(session: WorkspaceSession, sensitivity: str) -> None:
    """Execute one deterministic pipeline run synchronously.

    The API route executes this on a worker thread so the frontend can
    poll honest status; there are no fake progress stages. Partially
    compatible datasets run on their canonical-schema projection
    (``adapted_df``); fully compatible datasets run on the raw frame.
    """
    begin_analysis(session)
    try:
        analysis_df = (
            session.adapted_df if session.adapted_df is not None else session.df
        )
        artifacts = orchestrator.run_pipeline(
            analysis_df, dataset_name=session.dataset_name or "dataset",
            sensitivity=sensitivity,
        )
    except Exception as exc:  # noqa: BLE001 - mapped by the caller
        fail_analysis(session, str(exc) if isinstance(exc, OpsPilotError)
                      else type(exc).__name__)
        raise
    complete_analysis(session, artifacts)


def start_investigation_sync(session: WorkspaceSession) -> dict:
    """Run exactly one AI investigation against the current pack."""
    with session.lock:
        if session.investigation_status == INVESTIGATION_RUNNING:
            raise OpsPilotError("An AI investigation is already running.")
        if session.artifacts is None:
            raise DataValidationError(
                "No analyzed dataset is loaded; run the analysis first."
            )
        session.investigation_status = INVESTIGATION_RUNNING
        session.investigation_error = None
    try:
        result = orchestrator.run_investigation(
            session.artifacts.pack, client=get_investigation_client()
        )
    except Exception as exc:  # noqa: BLE001 - mapped by the caller
        with session.lock:
            session.investigation_status = INVESTIGATION_ERROR
            session.investigation_result = None
            session.investigation_error = (
                str(exc) if isinstance(exc, OpsPilotError)
                else type(exc).__name__
            )
        raise
    with session.lock:
        session.investigation_status = INVESTIGATION_COMPLETE
        session.investigation_result = result
    return result


def generate_plan_once(session: WorkspaceSession,
                       max_recommendations: int | None = None) -> dict:
    """Compute the deterministic plan once per artifact set.

    Persistence-once rule mirrors ``app.orchestrator.should_record_plan``:
    the plan row is recorded only the first time a given artifact set is
    planned, never on repeated page loads.
    """
    from database.connection import connect, init_db
    from app.orchestrator import persist_plan, should_record_plan

    with session.lock:
        if session.artifacts is None:
            raise DataValidationError(
                "No analyzed dataset is loaded; run the analysis first."
            )
        artifacts_id = id(session.artifacts)
        if session.plan is not None and session.plan_source_artifacts_id == artifacts_id:
            return session.plan
        investigation = (
            session.investigation_result
            if session.investigation_status == INVESTIGATION_COMPLETE else None
        )
        plan = orchestrator.generate_plan(
            session.artifacts.pack, investigation=investigation,
            max_recommendations=max_recommendations,
        )
        session.plan = plan
        session.plan_source_artifacts_id = artifacts_id

    if should_record_plan(session.plan_persisted_id):
        engine = connect()
        init_db(engine)
        # record_plan persists the plan AND every recommendation snapshot
        # atomically; no additional snapshot inserts are needed.
        session.plan_persisted_id = persist_plan(engine, plan)
    return plan


def apply_decision(session: WorkspaceSession, *, decision: str,
                   recommendation_id: str, reviewer_id: str,
                   comment: str | None) -> tuple[dict, dict]:
    """Apply one human decision through the real state machine + audit."""
    from database.connection import connect, init_db
    from app.orchestrator import apply_review, persist_review

    with session.lock:
        plan = session.plan
        record = None
        if plan:
            record = next(
                (r for r in (plan.get("recommendations") or [])
                 if r.get("recommendation_id") == recommendation_id), None)
        if record is None:
            raise DataValidationError(
                f"Unknown recommendation {recommendation_id!r} for this session."
            )
        updated_record, event = apply_review(
            decision, record, reviewer_id=reviewer_id, comment=comment
        )
        recommendations = plan.get("recommendations") or []
        for index, current in enumerate(recommendations):
            if current.get("recommendation_id") == recommendation_id:
                recommendations[index] = updated_record

    engine = connect()
    init_db(engine)
    persist_review(engine, updated_record, event)
    return updated_record, event


def history_payload() -> dict[str, Any]:
    """Serialize the append-only audit store via repository reads only."""
    from database.connection import connect, init_db
    from database import repository as repo

    engine = connect()
    init_db(engine)
    plans = repo.list_plans(engine)
    events = repo.list_review_events(engine)
    snapshots = repo.list_recommendations(engine)
    return {
        "counts": {
            "plans": repo.count_plans(engine),
            "recommendations": repo.count_recommendations(engine),
            "review_events": repo.count_review_events(engine),
        },
        "plans": plans,
        "recommendation_snapshots": snapshots,
        "review_events": events,
    }
