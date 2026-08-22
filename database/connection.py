"""SQLite connection management for OpsPilot AI (Phase 7).

Resolves the database URL (``DATABASE_URL`` environment variable,
defaulting to ``sqlite:///opspilot.db`` as documented in
``.env.example``), creates SQLAlchemy engines, and bootstraps the schema
idempotently.

Only SQLite is supported: the platform's persistence contract is a
local, file-backed audit store. Any other URL scheme fails closed with
``DataValidationError`` so misconfiguration can never silently target an
unintended backend.
"""

from __future__ import annotations

from core.config import get_env
from core.exceptions import DataValidationError
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

# Mirrors the DATABASE_URL placeholder in .env.example; relative paths
# resolve against the current working directory.
DEFAULT_DATABASE_URL: str = "sqlite:///opspilot.db"

SQLITE_SCHEME: str = "sqlite:"


def resolve_database_url(url: object = None) -> str:
    """Resolve and validate the SQLite connection URL.

    Precedence: explicit argument, then ``DATABASE_URL`` from the
    environment, then ``DEFAULT_DATABASE_URL``. Only SQLite URLs are
    accepted — any other scheme raises ``DataValidationError``.

    Args:
        url: Optional explicit connection URL overriding configuration.

    Returns:
        A validated SQLite URL string.

    Raises:
        DataValidationError: On empty/non-string values or non-SQLite
            schemes.
    """
    candidate = url if url is not None else get_env("DATABASE_URL", DEFAULT_DATABASE_URL)
    if not isinstance(candidate, str) or not candidate.strip():
        raise DataValidationError(
            f"database url must be a non-empty string; got {candidate!r}"
        )
    resolved = candidate.strip()
    if not resolved.startswith(SQLITE_SCHEME):
        raise DataValidationError(
            f"only SQLite databases are supported ({resolved!r}); expected "
            f"a {SQLITE_SCHEME}// URL such as '{DEFAULT_DATABASE_URL}'"
        )
    return resolved


def connect(url: object = None) -> Engine:
    """Create a SQLAlchemy engine for the configured SQLite database.

    Args:
        url: Optional explicit SQLite URL (see
            :func:`resolve_database_url`).

    Returns:
        A fresh :class:`sqlalchemy.engine.Engine`. Callers own its
        lifecycle; pass it to ``init_db`` and repository functions.
    """
    return create_engine(resolve_database_url(url))


def init_db(engine: Engine) -> None:
    """Create all Phase 7 tables when missing. Idempotent and additive.

    Existing tables and rows are never altered or dropped; this module
    deliberately exposes no migration or teardown capability.
    """
    from database.models import Base

    Base.metadata.create_all(engine)
