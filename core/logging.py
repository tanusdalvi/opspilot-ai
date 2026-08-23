"""Minimal structured logging for OpsPilot AI (Phase 10B).

One conservative configuration for the whole application:

* All application loggers live under the ``opspilot`` namespace.
* Exactly one ``StreamHandler`` is attached to the namespace root, and
  repeated configuration (Streamlit reruns modules constantly) can never
  duplicate it — handlers are guarded by an attribute marker and the
  logger itself is a process-wide singleton.
* The level defaults to ``INFO`` and may be lowered/raised via the
  ``OPSPILOT_LOG_LEVEL`` environment variable.

Log records carry structured context only — durations, counts, safe
dataset names, exception class names. Raw CSV contents, SQL statements,
filesystem paths, credentials, and full exception strings are never
logged by application code using this module's helpers.
"""

from __future__ import annotations

import logging

LOGGER_NAMESPACE = "opspilot"

_HANDLER_MARKER = "_opspilot_configured_handler"
_DEFAULT_LEVEL = logging.INFO


def _resolve_level() -> int:
    """Resolve the configured level name to a ``logging`` constant."""
    from core.config import get_env

    raw = (get_env("OPSPILOT_LOG_LEVEL") or "").strip().upper()
    if raw in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        return getattr(logging, raw)
    if raw:
        return _DEFAULT_LEVEL
    return _DEFAULT_LEVEL


def configure_logging() -> logging.Logger:
    """Return the ``opspilot`` namespace root, configuring it once.

    Idempotent by construction: the handler carries a marker attribute,
    and attachment is skipped whenever any marked handler already
    exists. Module reloads and Streamlit reruns therefore cannot create
    duplicate handlers or duplicated log lines.
    """
    root = logging.getLogger(LOGGER_NAMESPACE)
    if any(getattr(handler, _HANDLER_MARKER, False) for handler in root.handlers):
        root.setLevel(_resolve_level())
        return root
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    setattr(handler, _HANDLER_MARKER, True)
    root.addHandler(handler)
    root.setLevel(_resolve_level())
    root.propagate = False
    return root


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``opspilot`` namespace, configured once."""
    configure_logging()
    if name == LOGGER_NAMESPACE or name.startswith(f"{LOGGER_NAMESPACE}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAMESPACE}.{name}")


def log_event(
    logger: logging.Logger, event: str, **fields: object
) -> None:
    """Emit one structured ``event key=value ...`` record (INFO level).

    Values are rendered with ``str``; callers pass only safe scalar
    metadata (names, counts, durations, class names).
    """
    parts = [event]
    parts.extend(f"{key}={value}" for key, value in fields.items())
    logger.info(" ".join(parts))
