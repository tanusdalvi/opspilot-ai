"""OpsPilot AI API — transport adapters over the intelligence engine.

Phase 12 boundary: every route delegates to ``app.orchestrator`` /
``database.repository`` exactly like the Streamlit app. No analytics,
recommendation, review, audit, or Gemini logic lives here.

Error contract (never leaks internals or secrets):

* ``DataValidationError``  -> 400 with the project's safe message
* ``ConfigurationError``   -> 503 "AI not configured"
* ``AgentError``           -> 502 "AI investigation failed"
* other ``OpsPilotError``  -> 400 with the safe message
* anything unexpected      -> 500 generic, type name logged only
"""

from __future__ import annotations

import threading
from typing import Any, Iterator

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agent.gemini_client import DEFAULT_GEMINI_MODEL
from app import exports, orchestrator
from core.exceptions import (
    AgentError,
    ConfigurationError,
    DataValidationError,
    OpsPilotError,
)
from core.logging import get_logger, log_event

from backend.api import serializers
from backend.api.sessions import (
    WorkspaceSession,
    apply_decision,
    generate_plan_once,
    get_session,
    history_payload,
    run_analysis_sync,
    start_investigation_sync,
)

logger = get_logger(__name__)

SESSION_HEADER = "X-OpsPilot-Session"


def session_dependency(
    request: Request, response: Response
) -> Iterator[WorkspaceSession]:
    """Resolve (or mint) the workspace session; always echoes the header."""
    token = request.headers.get(SESSION_HEADER) or request.query_params.get(
        "session"
    )
    session = get_session(token)
    response.headers[SESSION_HEADER] = session.token
    yield session


app = FastAPI(title="OpsPilot AI API", version="12.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[SESSION_HEADER],
)


@app.exception_handler(DataValidationError)
@app.exception_handler(OpsPilotError)
def _project_error(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(ConfigurationError)
def _config_error(_request: Request, _exc: ConfigurationError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": "AI investigation is not configured. Deterministic "
            "analysis remains fully available."
        },
    )


@app.exception_handler(AgentError)
def _agent_error(_request: Request, _exc: AgentError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"error": "The AI investigation could not be completed."},
    )


@app.exception_handler(Exception)
def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    log_event(logger, "api_unexpected_error", error_type=type(exc).__name__,
              path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Unexpected application error. Please retry."},
    )


# --- schemas ----------------------------------------------------------------------------------------


class LoadDemoRequest(BaseModel):
    filename: str


class AnalysisRunRequest(BaseModel):
    sensitivity: str = "medium"
    wait: bool = False


class PlanRequest(BaseModel):
    max_recommendations: int | None = None


class ReviewRequest(BaseModel):
    recommendation_id: str
    decision: str
    reviewer_id: str
    comment: str | None = None


# --- system / health ---------------------------------------------------------------------------------


@app.get("/api/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/system")
def system(session: WorkspaceSession = Depends(session_dependency)) -> dict[str, Any]:
    return serializers.system_payload(session)


# --- datasets -----------------------------------------------------------------------------------------


@app.get("/api/demo-datasets")
def demo_datasets() -> dict[str, Any]:
    return {"datasets": orchestrator.list_demo_datasets()}


def _load_into_session(session: WorkspaceSession, df, name: str) -> dict:
    report = orchestrator.validate_dataset(df)
    from backend.api.sessions import reset_dataset

    reset_dataset(session, df, name, report)
    log_event(logger, "api_dataset_loaded", dataset=orchestrator._safe_dataset_name(name))
    return {
        "dataset": {
            "name": name,
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "memory_bytes": int(df.memory_usage(deep=True).sum()),
        },
        "validation_report": report,
        "analysis_status": "IDLE",
    }


@app.post("/api/datasets/load-demo")
def load_demo(body: LoadDemoRequest,
              session: WorkspaceSession = Depends(session_dependency)) -> dict:
    try:
        df = orchestrator.load_demo_dataset(body.filename)
    except DataValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _load_into_session(session, df, body.filename)


@app.post("/api/datasets/upload")
async def upload(file: UploadFile = File(...),
                 session: WorkspaceSession = Depends(session_dependency)) -> dict:
    content = await file.read()
    df = orchestrator.load_uploaded_dataset(file.filename or "", content)
    return _load_into_session(session, df, file.filename or "")


@app.get("/api/datasets/preview")
def dataset_preview(
    rows: int = 500,
    session: WorkspaceSession = Depends(session_dependency),
) -> dict[str, Any]:
    if session.df is None:
        raise HTTPException(
            status_code=409,
            detail="No dataset is loaded. Load a dataset to explore it.",
        )
    return serializers.preview_payload(session.df, limit=rows)


# --- analysis pipeline ----------------------------------------------------------------------------------


@app.post("/api/analysis/run")
def analysis_run(body: AnalysisRunRequest,
                 session: WorkspaceSession = Depends(session_dependency)) -> dict:
    if session.df is None:
        raise HTTPException(
            status_code=409,
            detail="No dataset is loaded. Load a dataset before running analysis.",
        )
    if body.sensitivity not in orchestrator.VALID_SENSITIVITIES:
        raise HTTPException(
            status_code=422,
            detail=f"sensitivity must be one of {sorted(orchestrator.VALID_SENSITIVITIES)}.",
        )
    if body.wait:
        run_analysis_sync(session, body.sensitivity)
        return {"analysis_status": session.status}
    threading.Thread(
        target=_run_analysis_worker, args=(session, body.sensitivity), daemon=True
    ).start()
    return {"analysis_status": "ANALYZING"}


def _run_analysis_worker(session: WorkspaceSession, sensitivity: str) -> None:
    try:
        # run_analysis_sync already records READY/ERROR + safe reason.
        run_analysis_sync(session, sensitivity)
    except Exception as exc:  # noqa: BLE001 - worker boundary; status recorded
        log_event(logger, "api_analysis_worker_exit", error_type=type(exc).__name__)


@app.get("/api/analysis/status")
def analysis_status(
    session: WorkspaceSession = Depends(session_dependency),
) -> dict[str, Any]:
    return serializers.system_payload(session)


@app.get("/api/analysis/artifacts")
def analysis_artifacts(
    session: WorkspaceSession = Depends(session_dependency),
) -> dict[str, Any]:
    if session.status != "READY" or session.artifacts is None:
        raise HTTPException(
            status_code=409,
            detail="No completed analysis in this session yet.",
        )
    return {"artifacts": serializers.artifacts_payload(session.artifacts)}


# --- evidence + AI investigation ---------------------------------------------------------------------------


@app.get("/api/evidence/pack")
def evidence_pack(
    session: WorkspaceSession = Depends(session_dependency),
) -> dict[str, Any]:
    if session.artifacts is None:
        raise HTTPException(status_code=409, detail="No analyzed dataset in this session yet.")
    return {"pack": session.artifacts.pack}


@app.post("/api/investigation/run")
def investigation_run(
    session: WorkspaceSession = Depends(session_dependency),
) -> dict[str, Any]:
    if not orchestrator.investigation_available():
        raise HTTPException(
            status_code=503,
            detail="AI investigation is not configured; deterministic analysis "
                   "remains fully available.",
        )
    if session.artifacts is None:
        raise HTTPException(
            status_code=409,
            detail="Run the deterministic analysis before starting an AI investigation.",
        )
    threading.Thread(
        target=_investigation_worker, args=(session,), daemon=True
    ).start()
    return {"investigation_status": "running"}


def _investigation_worker(session: WorkspaceSession) -> None:
    try:
        start_investigation_sync(session)
    except Exception as exc:  # noqa: BLE001 - status already recorded above
        log_event(logger, "api_investigation_worker_exit",
                  error_type=type(exc).__name__)


@app.get("/api/investigation/status")
def investigation_status(
    session: WorkspaceSession = Depends(session_dependency),
) -> dict[str, Any]:
    result = session.investigation_result
    return {
        "investigation_status": session.investigation_status,
        "investigation_error": session.investigation_error,
        "result": result,
        "gemini_model": DEFAULT_GEMINI_MODEL,
    }


# --- recommendations / review -------------------------------------------------------------------------------


@app.post("/api/plan/generate")
def plan_generate(body: PlanRequest,
                  session: WorkspaceSession = Depends(session_dependency)) -> dict:
    plan = generate_plan_once(session, max_recommendations=body.max_recommendations)
    return {"plan": plan, "plan_persisted_id": session.plan_persisted_id}


@app.post("/api/review")
def review(body: ReviewRequest,
           session: WorkspaceSession = Depends(session_dependency)) -> dict:
    updated_record, event = apply_decision(
        session,
        decision=body.decision,
        recommendation_id=body.recommendation_id,
        reviewer_id=body.reviewer_id,
        comment=body.comment,
    )
    return {"record": updated_record, "event": event}


# --- history / exports ----------------------------------------------------------------------------------------


@app.get("/api/history")
def history() -> dict[str, Any]:
    return history_payload()


@app.get("/api/export/audit")
def export_audit() -> dict[str, Any]:
    from database.connection import connect, init_db
    from database import repository as repo

    engine = connect()
    init_db(engine)
    plans = [repo.get_plan(engine, p["plan_id"]) for p in repo.list_plans(engine)]
    payload = exports.plan_audit_payload(plans, repo.list_review_events(engine))
    return {"payload": payload, "canonical_json": exports.canonical_json(payload)}
