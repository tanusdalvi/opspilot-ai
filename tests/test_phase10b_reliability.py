"""Phase 10B reliability tests: error hardening and regression guards.

Proves at the application boundary that raw SQL/driver text, filesystem
paths, and environment secrets never reach the UI; that unexpected
failures degrade to safe generic messages (with type-only logging); and
that the Phase 10A localization optimization plus deterministic pipeline
behavior remain intact. Also runs the offline demo smoke script.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.state import DATABASE_UI_ERROR, _sanitize_user_message  # noqa: E402
from core.logging import configure_logging  # noqa: E402
from database import repository  # noqa: E402


class _ListHandler(logging.Handler):
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


# --- Message sanitization ---------------------------------------------------------


class TestMessageSanitization:
    @pytest.mark.parametrize(
        ("raw", "forbidden"),
        [
            (r"failed for C:\Users\someone\secret\db.sqlite3", ["C:", "secret"]),
            ("cannot read /home/user/private/data.csv", ["/home/user"]),
            (
                r"unc path \\\\fileserver\\share\\x.csv unreachable",
                ["fileserver"],
            ),
        ],
    )
    def test_absolute_paths_are_redacted(self, raw, forbidden):
        sanitized = _sanitize_user_message(raw)
        assert "<path>" in sanitized
        for token in forbidden:
            assert token not in sanitized

    def test_safe_messages_pass_through_unchanged(self):
        message = "Dataset filename must not be empty"
        assert _sanitize_user_message(message) == message

    def test_overlong_messages_are_bounded(self):
        sanitized = _sanitize_user_message("x" * 5000)
        assert len(sanitized) <= 301
        assert sanitized.endswith("…")

    def test_static_database_message_stays_clean(self):
        lowered = DATABASE_UI_ERROR.lower()
        for forbidden in ("sqlite", "select ", "sqlalchemy", ".db", "traceback"):
            assert forbidden not in lowered


# --- Boundary rendering -------------------------------------------------------------


class TestBoundaryRendering:
    def test_typed_error_with_embedded_path_is_redacted(self):
        def scenario():
            from app.state import run_page
            from core.exceptions import DataValidationError

            run_page(
                "Boundary",
                None,
                lambda: (_ for _ in ()).throw(
                    DataValidationError(
                        r"Cannot read C:\Users\someone\uploads\private.csv"
                    )
                ),
            )

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(error.value for error in at.error)
        assert "DataValidationError" in rendered
        assert "C:" not in rendered
        assert "someone" not in rendered
        assert "<path>" in rendered

    def test_unexpected_exception_hides_message_and_secrets(
        self, monkeypatch, captured
    ):
        monkeypatch.setenv("GEMINI_API_KEY", "sk-boundary-secret-987")

        def scenario():
            import os

            from app.state import run_page

            secret = os.environ["GEMINI_API_KEY"]

            def boom():
                raise RuntimeError(f"connection failed with {secret} at /var/ops/x.db")

            run_page("Boundary", None, boom)

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(error.value for error in at.error)
        assert "RuntimeError" in rendered
        assert "sk-boundary-secret-987" not in rendered
        assert "/var/ops/x.db" not in rendered
        # Internal log carries the type only — never raw text or secrets.
        combined = "\n".join(captured.records)
        assert "unexpected_error" in combined
        assert "error_type=RuntimeError" in combined
        assert "sk-boundary-secret-987" not in combined
        assert "/var/ops/x.db" not in combined

    def test_database_error_renders_static_message(self):
        def scenario():
            from app.state import run_page
            from core.exceptions import DatabaseError

            def boom():
                raise DatabaseError("(sqlite3.OperationalError) SELECT 1 [SQL: x]")

            run_page("Boundary", None, boom)

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(error.value for error in at.error)
        assert rendered.strip() == DATABASE_UI_ERROR
        assert "SELECT" not in rendered


# --- Repository integrity failures ----------------------------------------------------


class _FakeBegin:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeSession:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def begin(self):
        return _FakeBegin()

    def add(self, row):
        pass

    def flush(self):
        raise IntegrityError(
            "INSERT INTO recommendation_plans (storage_schema_version) "
            "VALUES (1) — UNIQUE constraint failed",
            None,
            Exception("UNIQUE constraint failed: recommendation_plans.id"),
        )


class TestRepositoryIntegrityFailures:
    def test_plan_persistence_failure_hides_raw_sql(self, monkeypatch):
        from tests.test_persistence_service import make_plan, make_record

        monkeypatch.setattr(repository, "Session", _FakeSession)
        plan = make_plan([make_record(recommendation_id="R-INT-1")])
        with pytest.raises(repository.DatabaseError) as info:
            repository.record_plan(engine=None, plan=plan)
        message = str(info.value)
        assert message == "failed to persist recommendation plan (integrity constraint)"
        assert "INSERT" not in message
        assert "UNIQUE constraint" not in message
        # Original driver detail remains on the cause chain for debugging.
        assert isinstance(info.value.__cause__, IntegrityError)


# --- Phase 10A regression guard --------------------------------------------------------


def _tiny_frame() -> object:
    import pandas as pd

    values = [100.0, 101.0, 99.0, 100.0, 102.0, 98.0, 101.0, 400.0]
    return pd.DataFrame(
        {
            "date": [f"2024-04-{offset + 1:02d}" for offset in range(8)],
            "region": ["North"] * 8,
            "product": ["A"] * 8,
            "units_sold": [10] * 8,
            "revenue": values,
            "cost": [5.0] * 8,
            "lead_time_days": [5] * 8,
        }
    )


class TestPhase10APreserved:
    def test_localization_index_is_precomputed_once_per_dataset(self):
        from services.analytics_service import _prepare_operational_data
        from services.anomaly_service import SUPPORTED_METRICS
        from services.insight_service import (
            LOCALIZATION_DIMENSIONS,
            _ContextTables,
        )

        tables = _ContextTables(_prepare_operational_data(_tiny_frame()))
        expected_keys = {
            (dimension, metric)
            for dimension in LOCALIZATION_DIMENSIONS
            for metric in sorted(SUPPORTED_METRICS)
        }
        assert set(tables.localization_index) == expected_keys

    def test_date_formatting_does_not_scale_with_anomalies(self):
        import pandas as pd

        from services.insight_service import explain_anomalies

        frame = _tiny_frame()

        def make_records(count: int) -> list[dict]:
            return [
                {
                    "type": "daily_spike",
                    "scope": "daily",
                    "metric": "revenue",
                    "entity": None,
                    "date": "2024-04-08",
                    "value": 400.0,
                    "expected_value": 100.0,
                    "deviation_pct": 300.0,
                    "score": 90.0,
                    "severity": "CRITICAL",
                    "rule": "zscore_rolling",
                    "details": {"z": 9.9, "baseline_std": 1.0, "threshold": 3.0},
                }
                for _ in range(count)
            ]

        def count_strftime(records: list[dict]) -> int:
            counter = {"calls": 0}
            original = pd.Timestamp.strftime

            def counting(self, *args, **kwargs):
                counter["calls"] += 1
                return original(self, *args, **kwargs)

            pd.Timestamp.strftime = counting  # type: ignore[method-assign]
            try:
                explain_anomalies(frame, records)
            finally:
                pd.Timestamp.strftime = original  # type: ignore[method-assign]
            return counter["calls"]

        one = count_strftime(make_records(1))
        many = count_strftime(make_records(6))
        assert one > 0
        assert one == many, f"per-anomaly date formatting returned ({one} -> {many})"

    def test_pipeline_remains_deterministic(self):
        from app.orchestrator import run_pipeline

        first = run_pipeline(_tiny_frame(), dataset_name="guard.csv")
        second = run_pipeline(_tiny_frame(), dataset_name="guard.csv")
        assert first.anomaly_summary == second.anomaly_summary
        assert first.insights == second.insights


# --- Offline demo smoke ------------------------------------------------------------------


class TestDemoSmokeScript:
    def test_end_to_end_smoke_passes_without_gemini(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        script = PROJECT_ROOT / "scripts" / "demo_smoke.py"
        assert script.is_file()
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(PROJECT_ROOT),
        )
        output = result.stdout
        assert result.returncode == 0, output + result.stderr
        for stage in (
            "Dataset",
            "Validation",
            "Analysis",
            "Artifacts",
            "Anomalies",
            "Insights",
            "Recommendations",
            "Persistence",
            "Exports",
            "Audit",
        ):
            assert f"{stage}: PASS" in output, stage
        assert "Gemini: SKIPPED" in output
        assert "Overall: PASS" in output
        assert "analysis_duration_seconds=" in output
        assert "Traceback" not in output
