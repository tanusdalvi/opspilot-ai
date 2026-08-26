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

import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
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
from core.config import DATA_DIR, get_env
from core.constants import (
    MAX_UPLOAD_BYTES,
    RECOVERY_CONTEXT_FILENAME,
    RECOVERY_CONTEXT_VERSION,
    UPLOAD_DUPLICATE_POLICY,
    VALID_SENSITIVITIES,
)
from core.exceptions import ConfigurationError, DataValidationError
from core.logging import get_logger, log_event
from database import repository
from services.analytics_service import (
    calculate_daily_trends,
    calculate_period_comparison,
    calculate_product_performance,
    calculate_region_performance,
)
from services.anomaly_service import MAX_ANOMALIES, summarize_anomalies
from services.capability_service import build_capability_profile
from services.data_service import load_csv, load_dataset
from services.finding_service import build_findings
from services.validation_service import ensure_valid, validate_dataframe

logger = get_logger(__name__)

# Directory for staged CSV uploads (gitignored via data/uploads/).
UPLOAD_DIR: Path = DATA_DIR / "uploads"

# Explicit reviewer decisions understood by apply_review.
REVIEW_DECISIONS: tuple[str, ...] = ("APPROVE", "REJECT", "REQUEST_CHANGES", "RESUBMIT")

_REVIEW_DECISION_ALIASES: dict[str, str] = {
    "approve": "APPROVE",
    "reject": "REJECT",
    "request_changes": "REQUEST_CHANGES",
    "resubmit": "RESUBMIT",
}

_REVIEW_HANDLERS = {
    "APPROVE": approve_recommendation,
    "REJECT": reject_recommendation,
    "REQUEST_CHANGES": request_changes,
    "RESUBMIT": resubmit_recommendation,
}


def _maybe_aggregate_to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate sub-daily data to daily granularity for the analysis engine.

    The anomaly and insight services are designed for daily time-series.
    When the input has multiple rows per calendar day (e.g. hourly data),
    numeric columns are summed and text dimensions are collapsed to the
    most frequent value per day.  Already-daily data passes through
    unchanged.
    """
    from services.validation_service import NUMERIC_COLUMNS, TEXT_COLUMNS

    # Fast date extraction: take the first 10 chars of each date string
    # (YYYY-MM-DD) instead of slow pd.to_datetime on 100k+ rows.
    date_str = df["date"].astype(str).str[:10]
    total_rows = len(df)

    if total_rows <= 1000:
        return df

    unique_days = date_str.nunique()
    if unique_days >= total_rows or unique_days == 0:
        return df
    avg_rows_per_day = total_rows / unique_days
    if avg_rows_per_day < 2.0:
        return df

    work = df.copy()
    work["_day"] = date_str

    agg: dict[str, object] = {}
    for col in work.columns:
        if col in ("date", "_day"):
            continue
        if col in NUMERIC_COLUMNS:
            agg[col] = "sum"
        elif col in TEXT_COLUMNS:
            # Use first() for dimensions — in sub-daily data the dimension
            # is the same across hours within a day.  Avoids expensive
            # per-group mode() computation.
            agg[col] = "first"
        else:
            agg[col] = "first"

    grouped = work.groupby("_day", sort=True).agg(agg)
    grouped["date"] = grouped.index
    grouped = grouped.reset_index(drop=True)

    ordered = [c for c in df.columns if c in grouped.columns]
    grouped = grouped[ordered].reset_index(drop=True)
    return grouped


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
    findings: list[dict]
    capability_profile: dict

    @property
    def anomalies(self) -> list:
        return self.anomaly_result["anomalies"]

    @property
    def groups(self) -> list:
        return self.grouping["groups"]


# --- dataset loading --------------------------------------------------------------------


# Longest safe dataset name emitted to logs or stored in recovery
# metadata. Names are display identifiers only, never paths.
_MAX_SAFE_NAME_LENGTH = 80


def _safe_dataset_name(value: object) -> str:
    """Reduce a dataset label to a short, path-free log-safe name.

    Keeps only the base filename, strips directory separators and
    control characters, and caps the length. Unusable input collapses
    to ``"dataset"``.
    """
    if not isinstance(value, str):
        return "dataset"
    name = Path(value).name.strip()
    cleaned = "".join(char for char in name if char.isprintable()).strip()
    if not cleaned:
        return "dataset"
    return cleaned[:_MAX_SAFE_NAME_LENGTH]


def list_demo_datasets() -> list[dict]:
    """Return metadata for the bundled demo datasets."""
    from services.data_service import list_datasets

    return list_datasets()


def load_demo_dataset(filename: str) -> pd.DataFrame:
    """Load a demo dataset by filename (delegates to data_service)."""
    frame = load_dataset(filename)
    log_event(
        logger,
        "dataset_loaded",
        source="demo",
        dataset=_safe_dataset_name(filename),
        rows=len(frame),
    )
    return frame


def stage_upload(filename: object, content: bytes) -> Path:
    """Stage uploaded CSV bytes under the gitignored ``data/uploads/`` directory.

    Only the base filename is kept; parent-path components are dropped so
    an upload can never escape the uploads directory.

    Duplicate policy: when an upload reuses an existing basename, the
    staged file is replaced deterministically
    (``core.constants.UPLOAD_DUPLICATE_POLICY``). Staged files are
    transient working copies and are never persisted to the audit store,
    so replacement cannot affect recorded history.

    Files larger than ``core.constants.MAX_UPLOAD_BYTES`` are rejected
    before any disk write or parsing work happens.

    Returns:
        Path of the staged file, ready for :func:`load_csv`.

    Raises:
        DataValidationError: On missing names, empty content, non-CSV
            extensions, or oversized uploads.
    """
    if not isinstance(filename, str) or not filename.strip():
        raise DataValidationError("Uploaded file has no name")
    if not isinstance(content, bytes) or len(content) == 0:
        raise DataValidationError("Uploaded file is empty")
    safe_name = Path(filename).name
    if Path(safe_name).suffix.lower() != ".csv":
        raise DataValidationError(f"Only CSV uploads are supported; got {safe_name!r}")
    if len(content) > MAX_UPLOAD_BYTES:
        limit_mib = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise DataValidationError(
            f"Upload is too large ({len(content):,} bytes); the limit is "
            f"{limit_mib} MiB. Export a smaller date range and try again."
        )
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / safe_name
    target.write_bytes(content)
    return target


def load_uploaded_dataset(filename: object, content: bytes) -> pd.DataFrame:
    """Stage and load an uploaded CSV into a DataFrame.

    Common parse failures are mapped to typed, user-facing validation
    errors so raw pandas/driver details never reach the interface.
    """
    staged = stage_upload(filename, content)
    try:
        frame = load_csv(staged)
    except pd.errors.EmptyDataError as exc:
        raise DataValidationError(
            "The uploaded file contains no CSV data (it is empty or has "
            "only a header row with no delimiter content)."
        ) from exc
    except UnicodeDecodeError as exc:
        raise DataValidationError(
            "The uploaded file could not be read as text — it appears to be "
            "binary or uses an unsupported encoding. Please upload a UTF-8 "
            "CSV file."
        ) from exc
    except pd.errors.ParserError as exc:
        raise DataValidationError(
            "The uploaded file is not a well-formed CSV (malformed rows or "
            "inconsistent columns). Check the delimiter and column layout."
        ) from exc
    log_event(
        logger,
        "dataset_loaded",
        source="upload",
        dataset=_safe_dataset_name(filename),
        rows=len(frame),
    )
    return frame


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

    For non-time-series datasets (Types B, C, D), the pipeline adapts:
    time-dependent operations are skipped and the capability profile
    reports what analysis was performed.

    Sequence:

    1. ``build_capability_profile`` — determine what analysis is possible
    2. ``assess_and_adapt``         — project dataset to canonical schema
    3. ``ensure_valid``             — hard validation gate (fast fail)
    4. ``build_investigation_context`` — one full pass over the dataset;
       yields the pack plus KPIs, comparison, performers, anomalies,
       insights, and groups
    5. rendering tables            — region/product performance and
       daily trends (absent from the aggregate-only pack)

    Raises:
        DataValidationError: If the dataset fails validation or any
            service rejects its inputs. Invalid datasets never reach
            analysis.
    """
    from services.schema_adapter import assess_and_adapt

    safe_name = _safe_dataset_name(dataset_name)
    started = time.perf_counter()
    log_event(
        logger, "analysis_started", dataset=safe_name, sensitivity=sensitivity
    )

    # Step 1: Build capability profile from the raw dataset
    capability = build_capability_profile(df)
    log_event(
        logger,
        "capability_profiled",
        dataset=safe_name,
        dataset_class=capability.dataset_class,
        has_date=capability.has_date,
        has_numeric=capability.has_numeric,
    )

    # Step 2: Class E (insufficient) — fail early with honest explanation
    if capability.dataset_class == "E":
        reasons = "; ".join(capability.classification_reasons)
        raise DataValidationError(
            f"Dataset cannot be analyzed: {reasons}"
        )

    # Step 3: Adapt the dataset to canonical schema
    try:
        analysis_df, compat_report = assess_and_adapt(df)
    except Exception as exc:
        log_event(
            logger,
            "analysis_failed",
            dataset=safe_name,
            error_type=type(exc).__name__,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        raise DataValidationError(
            f"Dataset adaptation failed: {exc}"
        ) from exc

    if analysis_df is None:
        reasons = "; ".join(compat_report.reasons)
        raise DataValidationError(
            f"Dataset cannot be analyzed: {reasons}"
        )

    # Step 4: Validate the adapted dataset
    report = require_valid_dataset(analysis_df)

    # Step 5: Run the analysis pipeline
    has_time = capability.has_date and capability.time_series_analysis
    try:
        if has_time:
            # Full time-series pipeline
            work_df = _maybe_aggregate_to_daily(analysis_df)
            pack = build_investigation_context(
                work_df, sensitivity=sensitivity, focus=focus
            )
        else:
            # Non-time-series pipeline: skip date-dependent analysis
            work_df = analysis_df
            pack = build_investigation_context(
                work_df, sensitivity=sensitivity, focus=focus
            )
    except Exception as exc:  # noqa: BLE001 - logged safely, then re-raised
        log_event(
            logger,
            "analysis_failed",
            dataset=safe_name,
            error_type=type(exc).__name__,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        raise

    anomalies = pack["anomalies"]
    summary = summarize_anomalies(anomalies)
    period_comparison = pack["period_comparison"]
    if not has_time and period_comparison is None:
        period_comparison = {
            "periods": [],
            "comparison": None,
            "summary": "Period comparison unavailable: dataset has no time dimension.",
        }
    elif period_comparison is None:
        # Single-date or otherwise degenerate time-series: no meaningful
        # period-over-period comparison is possible.
        period_comparison = {
            "periods": [],
            "comparison": None,
            "summary": "Period comparison unavailable: dataset has fewer than two distinct dates.",
        }
    insights = pack["insights"]
    grouping = pack["groups"]
    findings = build_findings(
        anomalies,
        insights=insights,
        grouping=grouping,
    )

    # Step 6: Compute rendering tables (skip time-dependent for non-time-series)
    if has_time:
        region_perf = calculate_region_performance(work_df)
        product_perf = calculate_product_performance(work_df)
        daily_trends = calculate_daily_trends(work_df)
    else:
        # For non-time-series data, provide empty DataFrames with correct columns
        region_perf = (
            calculate_region_performance(work_df)
            if capability.has_categorical
            else pd.DataFrame(columns=["region", "revenue", "units_sold"])
        )
        product_perf = (
            calculate_product_performance(work_df)
            if capability.has_categorical
            else pd.DataFrame(columns=["product", "revenue", "units_sold"])
        )
        daily_trends = pd.DataFrame(
            columns=["date", "revenue", "units_sold", "cost", "lead_time_days"]
        )

    log_event(
        logger,
        "analysis_completed",
        dataset=safe_name,
        duration_ms=int((time.perf_counter() - started) * 1000),
        anomalies=len(anomalies),
        findings=len(findings),
    )
    return AnalysisArtifacts(
        dataset_name=dataset_name,
        df=df,
        validation_report=report,
        kpis=pack["kpis"],
        region_performance=region_perf,
        product_performance=product_perf,
        daily_trends=daily_trends,
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
        insights=insights,
        grouping=grouping,
        pack=pack,
        findings=findings,
        capability_profile=capability.to_dict(),
    )


# --- recommendations ------------------------------------------------------------------------


def generate_plan(
    df_or_context: object,
    *,
    investigation: dict | None = None,
    max_recommendations: int | None = None,
) -> dict:
    """Generate the deterministic recommendation plan (thin delegation)."""
    plan = _generate_plan(
        df_or_context, investigation=investigation, max_recommendations=max_recommendations
    )
    recommendations = plan.get("recommendations")
    log_event(
        logger,
        "recommendations_generated",
        count=len(recommendations) if isinstance(recommendations, list) else 0,
    )
    return plan


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

    Accepts any casing of the canonical decision strings and normalises
    them to uppercase before dispatch. This means "approve", "Approve",
    "APPROVE" all map to the same handler.

    Dispatches to the matching ``agent.review_service`` wrapper; this
    module never mutates recommendation records itself.

    Returns:
        ``(updated_record, review_event)`` exactly as produced by the
        service.
    """
    normalized = (
        _REVIEW_DECISION_ALIASES.get(str(decision).strip().lower())
        if isinstance(decision, str) else None
    )
    handler = _REVIEW_HANDLERS.get(normalized) if normalized else None
    if handler is None:
        raise DataValidationError(
            f"decision must be one of {list(REVIEW_DECISIONS)}; got {decision!r}"
        )
    updated_record, event = handler(
        recommendation, reviewer_id=reviewer_id, comment=comment, occurred_at=occurred_at
    )
    log_event(logger, "review_applied", decision=normalized)
    return updated_record, event


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
    plan_id = repository.record_plan(engine, plan)
    log_event(logger, "plan_persisted", plan_id=plan_id)
    return plan_id


def persist_review(engine, updated_record: dict, event: dict) -> tuple[int, int]:
    """Record one completed review (snapshot + event) atomically."""
    snapshot_id, event_id = repository.record_review(engine, updated_record, event)
    log_event(logger, "review_persisted", event_id=event_id)
    return snapshot_id, event_id


# --- restart recovery ------------------------------------------------------------------------------
#
# After a process restart Streamlit session state (and therefore any
# in-memory analysis artifacts) is gone. The audit database survives,
# but database history is NOT a substitute for live artifacts. This
# module therefore maintains a tiny metadata sidecar describing the
# last SUCCESSFUL analysis — dataset identity, sensitivity, timestamp —
# so the application can offer a deterministic "previous analysis
# found — reload/re-run" affordance instead of silently pretending an
# analysis is still loaded.
#
# Safety rules enforced here:
# * only lightweight scalar metadata is stored (never DataFrames);
# * the sidecar schema is versioned; unknown versions are rejected;
# * corrupted, invalid, or unreadable context fails safe to ``None``;
# * dataset identity is resolved through the existing demo/upload
#   loaders at restore time — raw filesystem paths are never exposed.


def _recovery_context_path() -> Path:
    """Return the recovery sidecar path (env-overridable for tests)."""
    override = get_env("OPSPILOT_RECOVERY_PATH")
    if override:
        return Path(override)
    return UPLOAD_DIR / RECOVERY_CONTEXT_FILENAME


def _demo_dataset_names() -> set[str]:
    try:
        return {entry["name"] for entry in list_demo_datasets()}
    except Exception:  # noqa: BLE001 - discovery must never break recovery
        return set()


def build_recovery_context(dataset_name: str, sensitivity: str) -> dict:
    """Build the validated, serializable recovery record for one run."""
    safe_name = _safe_dataset_name(dataset_name)
    source = "demo" if safe_name in _demo_dataset_names() else "upload"
    return {
        "version": RECOVERY_CONTEXT_VERSION,
        "dataset_name": safe_name,
        "source": source,
        "sensitivity": sensitivity if sensitivity in VALID_SENSITIVITIES else "medium",
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "status": "READY",
    }


def save_recovery_context(dataset_name: str, sensitivity: str) -> None:
    """Persist last-successful-analysis metadata (best effort).

    Recovery bookkeeping must never break or delay analysis completion,
    so every failure here is swallowed and logged with its type only.
    """
    context = build_recovery_context(dataset_name, sensitivity)
    try:
        path = _recovery_context_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(context), encoding="utf-8")
    except OSError as exc:
        logger.warning("recovery_save_failed error_type=%s", type(exc).__name__)


def clear_recovery_context() -> None:
    """Remove the recovery sidecar (best effort)."""
    try:
        _recovery_context_path().unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("recovery_clear_failed error_type=%s", type(exc).__name__)


def load_recovery_context() -> dict | None:
    """Load and strictly validate the recovery sidecar, or ``None``.

    Any structural problem — missing file, unparsable JSON, wrong
    version, bad field types, unknown sensitivity, unparseable
    timestamp — yields ``None`` and never raises.
    """
    path = _recovery_context_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log_event(logger, "recovery_rejected", reason=type(exc).__name__)
        return None

    context = _validate_recovery_context(raw)
    if context is None:
        log_event(logger, "recovery_rejected", reason="invalid_context")
    return context


def _validate_recovery_context(raw: object) -> dict | None:
    """Enforce the exact recovery sidecar contract."""
    if not isinstance(raw, dict):
        return None
    if raw.get("version") != RECOVERY_CONTEXT_VERSION:
        return None
    dataset_name = raw.get("dataset_name")
    if not isinstance(dataset_name, str) or not dataset_name or len(dataset_name) > 200:
        return None
    if Path(dataset_name).name != dataset_name:
        return None
    sensitivity = raw.get("sensitivity")
    if sensitivity not in VALID_SENSITIVITIES:
        return None
    source = raw.get("source")
    if source not in ("demo", "upload"):
        return None
    status = raw.get("status")
    if status != "READY":
        return None
    completed_at = raw.get("completed_at")
    if not isinstance(completed_at, str):
        return None
    try:
        datetime.fromisoformat(completed_at)
    except ValueError:
        return None
    return {
        "version": RECOVERY_CONTEXT_VERSION,
        "dataset_name": dataset_name,
        "source": source,
        "sensitivity": sensitivity,
        "completed_at": completed_at,
        "status": status,
    }


def recovery_dataset_available(context: object) -> bool:
    """True when the referenced dataset can currently be reloaded.

    Demo datasets must exist in the demo directory; uploads must exist
    as staged basenames under the uploads directory. Renamed, deleted,
    or stale datasets simply report unavailable — callers treat that as
    a safe recovery failure, never an error dialog.
    """
    if not isinstance(context, dict):
        return False
    name = context.get("dataset_name")
    source = context.get("source") if isinstance(name, str) else None
    if not isinstance(name, str) or not name:
        return False
    if source == "demo":
        return name in _demo_dataset_names()
    if source == "upload":
        candidate = UPLOAD_DIR / Path(name).name
        try:
            return candidate.is_file()
        except OSError:
            return False
    return False


__all__ = [
    "AnalysisArtifacts",
    "REVIEW_DECISIONS",
    "apply_review",
    "build_recovery_context",
    "clear_recovery_context",
    "generate_plan",
    "investigation_available",
    "load_demo_dataset",
    "load_recovery_context",
    "load_uploaded_dataset",
    "list_demo_datasets",
    "persist_plan",
    "persist_review",
    "recovery_dataset_available",
    "require_valid_dataset",
    "run_investigation",
    "run_pipeline",
    "save_recovery_context",
    "should_record_plan",
    "stage_upload",
    "validate_dataset",
]
