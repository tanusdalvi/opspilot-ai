"""Application configuration for OpsPilot AI.

Loads environment variables from a ``.env`` file in the project root
(see ``.env.example``) and exposes small helper functions so later phases
can access configuration cleanly.

Secrets such as ``GEMINI_API_KEY`` are only ever read from the environment.
They are never hardcoded and never printed or logged by this module.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root is the parent directory of this file's package (core/).
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# Directory that holds runtime data (raw uploads, demo data, processed files).
DATA_DIR: Path = PROJECT_ROOT / "data"

# Load .env once at import time; missing .env is fine because every getter
# falls back to defaults suitable for local development.
load_dotenv(PROJECT_ROOT / ".env")


def get_env(name: str, default: str | None = None) -> str | None:
    """Return an environment variable value, or ``default`` if unset."""
    return os.getenv(name, default)


def get_gemini_api_key() -> str | None:
    """Return the configured Gemini API key, or ``None`` if not set.

    The key must be provided via the ``GEMINI_API_KEY`` environment variable
    (typically defined in ``.env``). Callers must never log or display it.
    """
    key = os.getenv("GEMINI_API_KEY")
    if key is None:
        return None
    key = key.strip()
    return key or None


def has_gemini_api_key() -> bool:
    """Return ``True`` when a Gemini API key is configured (without exposing it)."""
    return get_gemini_api_key() is not None


def get_environment() -> str:
    """Return the current environment name (e.g. ``development``)."""
    return (os.getenv("APP_ENV") or "development").strip().lower()


def is_development() -> bool:
    """Return ``True`` when running in the development environment."""
    return get_environment() == "development"
