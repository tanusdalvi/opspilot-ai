"""Phase 10B logging tests: idempotent configuration, safe content.

Verifies that the ``opspilot`` logging namespace configures exactly one
handler no matter how often it is initialized (Streamlit reruns modules
constantly), that structured events render as ``event key=value``
records, and that lifecycle logging never leaks secrets, paths, or raw
dataset contents.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.logging import (  # noqa: E402
    LOGGER_NAMESPACE,
    _HANDLER_MARKER,
    configure_logging,
    get_logger,
    log_event,
)
from app.orchestrator import _safe_dataset_name, run_pipeline  # noqa: E402


class _ListHandler(logging.Handler):
    """Capture handler collecting formatted record messages."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


@pytest.fixture()
def captured():
    handler = _ListHandler()
    root = configure_logging()
    root.addHandler(handler)
    yield handler
    root.removeHandler(handler)


# --- Handler configuration -----------------------------------------------------


class TestHandlerConfiguration:
    def test_repeated_configuration_never_duplicates_handlers(self):
        first = configure_logging()
        count_after_first = sum(
            1
            for handler in first.handlers
            if getattr(handler, _HANDLER_MARKER, False)
        )
        assert count_after_first == 1

        for _ in range(5):
            again = configure_logging()
            assert again is first

        count_final = sum(
            1
            for handler in first.handlers
            if getattr(handler, _HANDLER_MARKER, False)
        )
        assert count_final == 1, "handler duplication on reconfiguration"

    def test_get_logger_namespaces_foreign_modules(self):
        configured = get_logger("some.random.module")
        assert configured.name == f"{LOGGER_NAMESPACE}.some.random.module"
        assert get_logger(LOGGER_NAMESPACE).name == LOGGER_NAMESPACE

    def test_emitted_events_are_not_duplicated(self, captured):
        logger = get_logger("tests.logging.dedup")
        log_event(logger, "analysis_started", dataset="x.csv")
        log_event(logger, "analysis_completed", dataset="x.csv", duration_ms=5)
        assert len(captured.records) == 2


# --- Structured event rendering --------------------------------------------------


class TestEventRendering:
    def test_log_event_structure(self, captured):
        logger = get_logger("tests.logging.render")
        log_event(logger, "analysis_completed", duration_ms=42, anomalies=7)
        assert captured.records == ["analysis_completed duration_ms=42 anomalies=7"]


# --- Safe dataset names ------------------------------------------------------------


class TestSafeDatasetName:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("demo_operational_data.csv", "demo_operational_data.csv"),
            (r"C:\Users\someone\uploads\data.csv", "data.csv"),
            ("/var/tmp/secret/dataset.csv", "dataset.csv"),
            ("../../etc/passwd.csv", "passwd.csv"),
            ("", "dataset"),
            (None, "dataset"),
            (123, "dataset"),
            ("   ", "dataset"),
        ],
    )
    def test_paths_and_junk_collapse_to_base_names(self, raw, expected):
        assert _safe_dataset_name(raw) == expected

    def test_long_names_are_bounded(self):
        assert len(_safe_dataset_name("x" * 500 + ".csv")) <= 80


# --- No secret leakage through lifecycle logging -----------------------------------


def _tiny_frame() -> pd.DataFrame:
    rows = []
    values = [100.0, 101.0, 99.0, 100.0, 102.0, 98.0, 101.0, 987654.0]
    for offset, revenue in enumerate(values):
        rows.append(
            {
                "date": f"2024-01-{offset + 1:02d}",
                "region": "North",
                "product": "A",
                "units_sold": 10,
                "revenue": revenue,
                "cost": 5.0,
                "lead_time_days": 5,
            }
        )
    return pd.DataFrame(rows)


class TestNoSecretLeakage:
    def test_lifecycle_logs_contain_no_key_or_path_or_rows(self, captured, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "sk-super-secret-value-123")
        artifacts = run_pipeline(_tiny_frame(), dataset_name=r"C:\tmp\upload.csv")

        combined = "\n".join(captured.records)
        assert "sk-super-secret-value-123" not in combined
        assert "C:" not in combined and "tmp" not in combined
        assert "upload.csv" in combined  # safe base name only
        # Row contents are never logged (the distinctive spike appears nowhere).
        assert "987654" not in combined
        # Structured lifecycle events are present.
        assert any(record.startswith("analysis_started") for record in captured.records)
        assert any(
            record.startswith("analysis_completed") and "anomalies=" in record
            for record in captured.records
        )
        assert artifacts is not None

    def test_failure_log_contains_only_exception_type(self, captured):
        from core.exceptions import DataValidationError

        with pytest.raises(DataValidationError):
            run_pipeline(
                _tiny_frame(),
                dataset_name="ok.csv",
                sensitivity="bogus-level",
            )
        failure_lines = [
            record for record in captured.records if record.startswith("analysis_failed")
        ]
        assert len(failure_lines) == 1
        assert "error_type=DataValidationError" in failure_lines[0]
        assert "bogus" not in failure_lines[0]
