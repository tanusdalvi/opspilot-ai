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

import asyncio
import threading
import time as _time
import uuid
from typing import Any, Iterator

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

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
from services.tool_registry import get_available_tools, execute_tools

logger = get_logger(__name__)

SESSION_HEADER = "X-OpsPilot-Session"

# In-memory upload job registry (process-local, keyed by upload_id).
_UPLOAD_JOBS: dict[str, dict] = {}


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


class InvestigateRequest(BaseModel):
    question: str
    tools: list[str] | None = None  # None = auto-select based on question


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


def _load_into_session(session: WorkspaceSession, df, name: str,
                       source: str = "upload") -> dict:
    report = orchestrator.validate_dataset(df)
    from services.schema_adapter import (
        assess_and_adapt,
        profile_columns,
        report_payload,
    )
    from services.capability_service import build_capability_profile

    kinds = profile_columns(df)
    adapted_df, compatibility = assess_and_adapt(df, precomputed_kinds=kinds)
    capability = build_capability_profile(df)
    from backend.api.sessions import reset_dataset

    reset_dataset(
        session, df, name, report,
        adapted_df=adapted_df if compatibility.tier == "partial" else None,
        compatibility=report_payload(compatibility),
        capability_profile=capability.to_dict(),
        source=source,
    )
    log_event(
        logger, "api_dataset_loaded",
        dataset=orchestrator._safe_dataset_name(name),
        compatibility=compatibility.tier,
        dataset_class=capability.dataset_class,
        source=source,
    )
    return {
        "dataset": {
            "name": name,
            "source": source,
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "memory_bytes": int(df.memory_usage(deep=True).sum()),
        },
        "validation_report": report,
        "compatibility": report_payload(compatibility),
        "capability_profile": capability.to_dict(),
        "analysis_status": "IDLE",
    }


@app.post("/api/datasets/load-demo")
def load_demo(body: LoadDemoRequest,
              session: WorkspaceSession = Depends(session_dependency)) -> dict:
    try:
        df = orchestrator.load_demo_dataset(body.filename)
    except DataValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _load_into_session(session, df, body.filename, source="demo")


@app.post("/api/datasets/upload")
async def upload(file: UploadFile = File(...),
                 session: WorkspaceSession = Depends(session_dependency)) -> dict:
    content = await file.read()
    # CPU-bound pandas work must not block the event loop.
    df = await run_in_threadpool(
        orchestrator.load_uploaded_dataset, file.filename or "", content
    )
    result = await run_in_threadpool(
        _load_into_session, session, df, file.filename or ""
    )
    return result


@app.post("/api/uploads")
async def create_upload(
    file: UploadFile = File(...),
    session: WorkspaceSession = Depends(session_dependency),
) -> dict:
    upload_id = uuid.uuid4().hex[:12]
    content = await file.read()
    _UPLOAD_JOBS[upload_id] = {
        "id": upload_id,
        "filename": file.filename or "upload.csv",
        "stage": "RECEIVED",
        "progress": 0,
        "result": None,
        "error": None,
        "started_at": _time.time(),
    }
    threading.Thread(
        target=_process_upload_job,
        args=(upload_id, file.filename or "upload.csv", content, session),
        daemon=True,
    ).start()
    return {"upload_id": upload_id, "stage": "RECEIVED"}


def _process_upload_job(
    upload_id: str, filename: str, content: bytes, session: WorkspaceSession
) -> None:
    job = _UPLOAD_JOBS[upload_id]
    try:
        job["stage"] = "PARSING"
        job["progress"] = 20
        df = orchestrator.load_uploaded_dataset(filename, content)

        job["stage"] = "VALIDATING"
        job["progress"] = 40

        job["stage"] = "PROFILING"
        job["progress"] = 60

        job["stage"] = "ADAPTING"
        job["progress"] = 80
        result = _load_into_session(session, df, filename)

        job["stage"] = "READY"
        job["progress"] = 100
        job["result"] = result
    except Exception as exc:
        job["stage"] = "FAILED"
        job["error"] = str(exc)


@app.get("/api/uploads/{upload_id}")
def get_upload_status(upload_id: str) -> dict:
    job = _UPLOAD_JOBS.get(upload_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Upload job not found")
    return {
        "id": job["id"],
        "filename": job["filename"],
        "stage": job["stage"],
        "progress": job["progress"],
        "result": job["result"],
        "error": job["error"],
    }


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
    compatibility = session.compatibility or {}
    if compatibility.get("tier") == "unsupported":
        reasons = " ".join(compatibility.get("reasons") or [])
        raise HTTPException(
            status_code=422,
            detail=(
                "This dataset cannot be analyzed: "
                + (reasons or "it lacks the minimum structure OpsPilot needs.")
            ),
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


# --- Investigation Center (deterministic tool-based investigation) -------------------------


def _select_tools_for_question(question: str, available_names: list[str]) -> list[str]:
    """Select relevant tools based on the user's question keywords."""
    q = question.lower()
    selected: list[str] = []

    # Always include summary for context
    if "get_sales_summary" in available_names:
        selected.append("get_sales_summary")

    # Keyword-based tool selection
    keyword_tool_map = {
        "product": "get_product_performance",
        "region": "get_region_performance",
        "area": "get_region_performance",
        "geographic": "get_region_performance",
        "period": "get_period_comparison",
        "trend": "get_trend_analysis",
        "direction": "get_trend_analysis",
        "cost": "get_cost_ratio_analysis",
        "margin": "get_cost_ratio_analysis",
        "profit": "get_cost_ratio_analysis",
        "lead time": "get_lead_time_analysis",
        "delivery": "get_lead_time_analysis",
        "fulfil": "get_lead_time_analysis",
        "fulfill": "get_lead_time_analysis",
        "anomal": "detect_anomalies",
        "unusual": "detect_anomalies",
        "spike": "detect_anomalies",
        "drop": "detect_anomalies",
        "outlier": "detect_anomalies",
    }

    for keyword, tool_name in keyword_tool_map.items():
        if keyword in q and tool_name in available_names and tool_name not in selected:
            selected.append(tool_name)

    # If no specific tools matched, include trend and period comparison
    if len(selected) <= 1:
        for fallback in ("get_trend_analysis", "get_period_comparison", "detect_anomalies"):
            if fallback in available_names and fallback not in selected:
                selected.append(fallback)

    return selected


@app.post("/api/investigate")
def investigate(body: InvestigateRequest,
                session: WorkspaceSession = Depends(session_dependency)) -> dict[str, Any]:
    """Deterministic tool-based investigation. Runs analytical tools against
    the active dataset and returns structured evidence without requiring AI."""
    if session.df is None:
        raise HTTPException(
            status_code=409,
            detail="No dataset is loaded. Load a dataset before investigating.",
        )
    if session.artifacts is None:
        raise HTTPException(
            status_code=409,
            detail="Run analysis before investigating. Click 'Run Analysis' first.",
        )

    df = session.df
    available = get_available_tools(df)
    available_names = [t.name for t in available]

    # Select tools: user-specified or auto-selected based on question
    tool_names = body.tools if body.tools else _select_tools_for_question(body.question, available_names)

    # Execute tools
    tool_results = execute_tools(tool_names, df, sensitivity="medium")

    # Build investigation evidence
    evidence_items: list[dict[str, Any]] = []
    for tool_name, result in tool_results.items():
        if "error" in result:
            evidence_items.append({
                "tool": tool_name,
                "status": "error",
                "error": result["error"],
            })
        else:
            evidence_items.append({
                "tool": tool_name,
                "status": "success",
                "data": result,
            })

    # Build the deterministic investigation plan
    tool_descriptions = {t.name: t.description for t in available}
    plan = {
        "question": body.question,
        "selected_tools": [
            {"name": n, "description": tool_descriptions.get(n, "")}
            for n in tool_names
        ],
        "available_tools": [
            {"name": t.name, "description": t.description, "category": t.category}
            for t in available
        ],
    }

    # Synthesize a deterministic conclusion from the evidence
    summary_parts: list[str] = []
    for item in evidence_items:
        if item["status"] == "success":
            data = item["data"]
            tool_name = item["tool"]
            if tool_name == "get_sales_summary" and "metrics" in data:
                m = data["metrics"]
                if "revenue" in m:
                    summary_parts.append(
                        f"Total revenue: ${m['revenue']['total']:,.0f} "
                        f"(${m['revenue']['daily_average']:,.0f}/day avg)"
                    )
                if "lead_time_days" in m:
                    summary_parts.append(
                        f"Average lead time: {m['lead_time_days']['average']:.1f} days "
                        f"(p95: {m['lead_time_days']['p95']:.1f} days)"
                    )
            elif tool_name == "get_trend_analysis" and "trends" in data:
                for metric, trend in data["trends"].items():
                    summary_parts.append(
                        f"{metric}: {trend['direction']} "
                        f"({trend['change_pct']:+.1f}% period-over-period)"
                    )
            elif tool_name == "get_cost_ratio_analysis":
                if "trend" in data:
                    summary_parts.append(
                        f"Cost ratio: {data.get('first_half_cost_ratio', '?')}% → "
                        f"{data.get('second_half_cost_ratio', '?')}% "
                        f"({data['trend']})"
                    )
            elif tool_name == "get_lead_time_analysis" and "trend" in data:
                t = data["trend"]
                summary_parts.append(
                    f"Lead time trend: {t['first_half_mean']:.1f} → "
                    f"{t['second_half_mean']:.1f} days "
                    f"({t['change_pct']:+.1f}%)"
                )
            elif tool_name == "detect_anomalies":
                summary_parts.append(
                    f"Anomalies detected: {data.get('total_anomalies', 0)} "
                    f"across {len(data.get('metrics_analyzed', []))} metrics"
                )
            elif tool_name == "get_product_performance" and "products" in data:
                for p in data["products"]:
                    summary_parts.append(
                        f"Product '{p['product']}': "
                        f"{p.get('units_sold', {}).get('total', 0):,} units, "
                        f"${p.get('revenue', {}).get('total', 0):,.0f} revenue"
                    )
            elif tool_name == "get_region_performance" and "regions" in data:
                for r in data["regions"]:
                    summary_parts.append(
                        f"Region '{r['region']}': "
                        f"${r.get('revenue', {}).get('total', 0):,.0f} revenue, "
                        f"avg lead time {r.get('lead_time_days', {}).get('average', 0):.1f} days"
                    )

    conclusion = (
        "Investigation of: " + body.question + "\n\n"
        + "\n".join(f"• {part}" for part in summary_parts)
        if summary_parts
        else "The analytical tools returned no results for this question."
    )

    return {
        "status": "complete",
        "plan": plan,
        "evidence": evidence_items,
        "conclusion": conclusion,
        "tools_available": len(available),
        "tools_executed": len(tool_names),
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
