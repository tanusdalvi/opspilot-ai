"""Streamlit runtime helpers shared by every OpsPilot AI page (Phase 8).

Keeps Streamlit-specific concerns out of the pure orchestrator:

* ``get_engine``   — one cached SQLAlchemy engine per process, with the
  schema bootstrapped once via ``database.connection``.
* ``run_page``     — the consistent error boundary used by all pages:
  ``OpsPilotError`` becomes a clean message; anything unexpected becomes
  a concise user-facing error without raw tracebacks.
* ``page_header``  — uniform page titles/subtitles.

Nothing in this module implements business rules or touches SQLAlchemy
models; pages read and write exclusively through repository functions
called from the orchestrator.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.exceptions import DatabaseError, OpsPilotError
from core.logging import get_logger, log_event
from database.connection import connect, init_db

logger = get_logger(__name__)

# --- analysis lifecycle ----------------------------------------------------------------------
#
# IDLE      no completed analysis exists (initial state, or reset by a
#           newly loaded dataset)
# ANALYZING one explicit user-triggered pipeline run is executing
# READY     the latest run finished; ``analysis_artifacts`` is current
# ERROR     the latest run failed; previous artifacts are preserved and
#           the safe failure reason is stored for display
# RECOVERY_AVAILABLE  derived state (never stored): the process was
#           restarted, no artifacts exist in memory, but validated
#           metadata describes a previous successful analysis that can
#           be re-run. It never claims artifacts exist.
ANALYSIS_IDLE: str = "IDLE"
ANALYSIS_RUNNING: str = "ANALYZING"
ANALYSIS_READY: str = "READY"
ANALYSIS_ERROR: str = "ERROR"
ANALYSIS_RECOVERY_AVAILABLE: str = "RECOVERY_AVAILABLE"

_ANALYSIS_STATUSES: frozenset[str] = frozenset(
    {
        ANALYSIS_IDLE,
        ANALYSIS_RUNNING,
        ANALYSIS_READY,
        ANALYSIS_ERROR,
        ANALYSIS_RECOVERY_AVAILABLE,
    }
)


def get_analysis_status() -> str:
    """Return the current analysis lifecycle status (default IDLE).

    ``RECOVERY_AVAILABLE`` is derived, never stored: it applies only
    while the session is genuinely IDLE with no artifacts in memory,
    and only when validated restart-recovery metadata references a
    dataset that can still be loaded. A stale or deleted dataset falls
    back to plain IDLE.
    """
    status = st.session_state.get("analysis_status", ANALYSIS_IDLE)
    if status not in _ANALYSIS_STATUSES:
        return ANALYSIS_IDLE
    if status != ANALYSIS_IDLE:
        return status
    if _recovery_offer_applicable():
        return ANALYSIS_RECOVERY_AVAILABLE
    return ANALYSIS_IDLE


def _get_recovery_context() -> dict | None:
    """Return the validated recovery context, checked once per session.

    The result (which may be ``None`` after a rejected/corrupt sidecar)
    is memoized in session state so reruns never re-read the file, and
    it is invalidated whenever a new analysis begins or completes.
    """
    if "recovery_context_cache" in st.session_state:
        return st.session_state.recovery_context_cache
    from app import orchestrator

    context = orchestrator.load_recovery_context()
    st.session_state.recovery_context_cache = context
    if context is not None:
        log_event(
            logger,
            "recovery_available",
            dataset=context.get("dataset_name"),
            source=context.get("source"),
        )
    return context


def _recovery_offer_applicable() -> bool:
    """True when IDLE + artifact-free + a reloadable previous analysis."""
    artifacts = st.session_state.get("analysis_artifacts")
    if artifacts is not None:
        return False
    context = _get_recovery_context()
    if context is None:
        return False
    from app import orchestrator

    try:
        return orchestrator.recovery_dataset_available(context)
    except Exception:  # noqa: BLE001 - recovery must never break status
        return False


def begin_analysis() -> None:
    """Mark a pipeline run as started (before the expensive work)."""
    st.session_state.analysis_status = ANALYSIS_RUNNING
    st.session_state.analysis_error = None
    # A fresh run supersedes any recovery decision made earlier.
    st.session_state.recovery_context_cache = None


def complete_analysis(artifacts) -> None:
    """Store the fresh artifacts and mark the analysis READY.

    The lightweight restart-recovery sidecar is refreshed so a future
    process restart can offer to re-run this same analysis. Sidecar
    bookkeeping is best effort and never affects the lifecycle.
    """
    st.session_state.analysis_artifacts = artifacts
    st.session_state.analysis_status = ANALYSIS_READY
    st.session_state.analysis_error = None
    st.session_state.recovery_context_cache = None
    try:
        from app import orchestrator

        parameters = (artifacts.pack.get("parameters") or {}) if getattr(artifacts, "pack", None) else {}
        orchestrator.save_recovery_context(
            artifacts.dataset_name, str(parameters.get("sensitivity", "medium"))
        )
    except Exception as exc:  # noqa: BLE001 - recovery is never critical
        logger.warning("recovery_save_failed error_type=%s", type(exc).__name__)


def fail_analysis(message: str) -> None:
    """Record a failed run with its safe, user-facing reason."""
    st.session_state.analysis_status = ANALYSIS_ERROR
    st.session_state.analysis_error = str(message)


def is_analysis_stale(sensitivity: object, dataset_name: object) -> bool:
    """True when settings changed after the stored analysis was produced.

    Derived from session state on every rerun — no extra bookkeeping —
    so it can never drift out of sync with the artifacts themselves.
    """
    if get_analysis_status() != ANALYSIS_READY:
        return False
    artifacts = get_artifacts()
    if artifacts is None:
        return False
    parameters = artifacts.pack.get("parameters") or {}
    if parameters.get("sensitivity") != sensitivity:
        return True
    return bool(dataset_name) and artifacts.dataset_name != dataset_name


@st.cache_resource
def get_engine():
    """Return the process-wide SQLite engine (schema created idempotently)."""
    engine = connect()
    init_db(engine)
    return engine


# Safe user-facing message for database failures. Raw SQLAlchemy/driver
# text (SQL fragments, file paths, connection details) must never reach
# the interface, so ``DatabaseError`` is rendered with this static string
# at the presentation boundary; the exception taxonomy itself is unchanged.
DATABASE_UI_ERROR: str = (
    "**Database error** - the audit store could not be accessed. "
    "Please retry; if the problem persists, restart the application."
)

# Longest user-facing message rendered from a typed error. Curated
# OpsPilot messages are far shorter; the cap only bounds worst cases.
_MAX_UI_MESSAGE_LENGTH = 300

# Absolute-path-like tokens (Windows drive paths, UNC paths, and POSIX
# absolute paths) are redacted from typed error messages before render.
_PATH_TOKEN_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s'\"<>|]*|\\\\[^\s'\"<>]+|/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)"
)


def _sanitize_user_message(message: str) -> str:
    """Redact path-like tokens and bound the length of a UI message."""
    sanitized = _PATH_TOKEN_PATTERN.sub("<path>", message)
    if len(sanitized) > _MAX_UI_MESSAGE_LENGTH:
        sanitized = sanitized[:_MAX_UI_MESSAGE_LENGTH].rstrip() + "…"
    return sanitized


def run_page(title: str, subtitle: str | None, render: Callable[[], None]) -> None:
    """Render one page inside the shared error boundary."""
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    try:
        render()
    except DatabaseError:
        st.error(DATABASE_UI_ERROR)
    except OpsPilotError as exc:
        st.error(f"**{type(exc).__name__}** - {_sanitize_user_message(str(exc))}")
    except Exception as exc:  # noqa: BLE001 - final user-facing boundary
        log_event(logger, "unexpected_error", error_type=type(exc).__name__, page=title)
        logger.debug("unexpected page failure", exc_info=True)
        st.error(f"Unexpected application error ({type(exc).__name__}). Please retry.")


def get_artifacts():
    """Return the active analysis artifacts bundle, or ``None``."""
    return st.session_state.get("analysis_artifacts")


def require_artifacts():
    """Return artifacts, or render the correct lifecycle message.

    The message always reflects reality:

    * ``ANALYZING`` — an explicit run is executing; never claims data is
      missing and never renders stale artifacts as current.
    * ``READY``     — artifacts exist; render them (a failed refresh
      keeps the previous valid results visible with a warning).
    * ``ERROR``     — the last attempt failed; show the reason and how
      to retry when no previous results exist.
    * ``RECOVERY_AVAILABLE`` — a previous successful analysis was found
      after a restart; offer to reload/re-run it. Artifacts are never
      fabricated: nothing is rendered as current results.
    * ``IDLE``      — genuinely nothing analyzed yet; actionable hint.
    """
    from app.orchestrator import AnalysisArtifacts

    if get_analysis_status() == ANALYSIS_RUNNING:
        dataset = st.session_state.get("dataset_name") or "the selected dataset"
        st.info(
            f"⏳ **Analysis in progress** — OpsPilot is processing `{dataset}`.\n\n"
            "Deterministic operational analysis is running. Results appear "
            "automatically on every page once it completes."
        )
        return None

    artifacts = get_artifacts()
    if isinstance(artifacts, AnalysisArtifacts):
        if get_analysis_status() == ANALYSIS_ERROR:
            reason = st.session_state.get("analysis_error")
            st.warning(
                "The last analysis attempt could not be completed. "
                "Previous results are shown below; re-run the analysis "
                "from the **Analytics** page to refresh them."
            )
            if reason:
                st.caption(f"Reason: {reason}")
        return artifacts

    status = get_analysis_status()

    if status == ANALYSIS_RECOVERY_AVAILABLE:
        context = _get_recovery_context() or {}
        st.info(
            "**Previous analysis found** — the application was restarted "
            "since the last successful run, so its interactive results "
            "are no longer in memory.\n\n"
            f"Last completed analysis: `{context.get('dataset_name')}` "
            f"(sensitivity `{context.get('sensitivity')}`, finished "
            f"{context.get('completed_at')}).\n\n"
            "To restore it: open **Data** in the sidebar, load the same "
            "dataset, then press *Run / Refresh Analysis* on the "
            "**Analytics** page."
        )
        return None

    if status == ANALYSIS_ERROR:
        st.error(
            "**Analysis could not be completed.** Open **Analytics** and "
            "press *Run / Refresh Analysis* to try again."
        )
        reason = st.session_state.get("analysis_error")
        if reason:
            st.caption(f"Reason: {reason}")
        return None

    st.warning(
        "No analyzed dataset yet. Load and validate a dataset on the "
        "**Data** page in the sidebar, then run the analysis from the "
        "**Analytics** page."
    )
    return None
