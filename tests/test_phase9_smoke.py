"""Phase 9 smoke tests: error sanitization, History provenance, README.

Verifies that database-facing failures never expose raw driver/SQL text
at the Streamlit boundary, that the Audit History page renders recorded
plan provenance inside a real AppTest runtime, and that the README only
references paths that actually exist without claiming capabilities the
product does not have.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.state import DATABASE_UI_ERROR  # noqa: E402
from database import repository as repo  # noqa: E402
from database.connection import connect, init_db  # noqa: E402
from tests.test_persistence_service import make_plan, make_record  # noqa: E402


# --- Error sanitization at the presentation boundary ---------------------------------------
#
# AppTest.from_function re-executes scenario source in isolation, so every
# scenario below is fully self-contained (no closures over test locals).


class TestErrorSanitization:
    def test_static_database_message_contains_no_driver_details(self):
        lowered = DATABASE_UI_ERROR.lower()
        for forbidden in ("sqlite", "select ", "sqlalchemy", ".db", "traceback"):
            assert forbidden not in lowered

    def test_database_error_is_sanitized(self):
        def scenario():
            from app.state import run_page
            from core.exceptions import DatabaseError

            def boom():
                raise DatabaseError(
                    "(sqlite3.OperationalError) no such table: x — "
                    "SELECT * FROM secrets [SQL: '/secret/path.db']"
                )

            run_page("Boundary", None, boom)

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(error.value for error in at.error)
        assert "sqlite3" not in rendered
        assert "SELECT" not in rendered
        assert "/secret/path.db" not in rendered
        assert "audit store could not be accessed" in rendered

    def test_typed_ops_errors_keep_their_safe_message(self):
        def scenario():
            from app.state import run_page
            from core.exceptions import DataValidationError

            def boom():
                raise DataValidationError("Dataset filename must not be empty")

            run_page("Boundary", None, boom)

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(error.value for error in at.error)
        assert "DataValidationError" in rendered
        assert "must not be empty" in rendered

    def test_unexpected_exception_hides_message(self):
        def scenario():
            from app.state import run_page

            def boom():
                raise ValueError("internal path /home/user/secret.db exploded")

            run_page("Boundary", None, boom)

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(error.value for error in at.error)
        assert "ValueError" in rendered
        assert "/home/user/secret.db" not in rendered


# --- History page renders plan provenance ---------------------------------------------------


@pytest.mark.skip(reason="Streamlit pages removed during React/FastAPI productization")
class TestHistoryPageAppTest:
    @pytest.fixture()
    def seeded_app(self, tmp_path, monkeypatch):
        db_path = tmp_path / "audit.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
        engine = connect(f"sqlite:///{db_path.as_posix()}")
        init_db(engine)
        records = [
            make_record(recommendation_id="R-UI-1"),
            make_record(recommendation_id="R-UI-2"),
        ]
        repo.record_plan(engine, make_plan(records))
        engine.dispose()

        app = AppTest.from_file(
            str(PROJECT_ROOT / "app" / "pages" / "history.py"),
            default_timeout=60,
        )
        app.run()
        return app

    def test_renders_without_exception(self, seeded_app):
        assert not seeded_app.exception

    def test_plans_provenance_visible(self, seeded_app):
        labels = " | ".join(expander.label for expander in seeded_app.expander)
        assert "Plan #1" in labels
        body = "\n".join(str(el.value) for el in seeded_app.markdown) + labels
        assert "recommendation(s)" in labels or "recommendation(s)" in body

    def test_no_traceback_in_output(self, seeded_app):
        rendered = "\n".join(str(element.value) for element in seeded_app.markdown)
        rendered += "\n".join(error.value for error in seeded_app.error)
        assert "Traceback" not in rendered


# --- README accuracy ------------------------------------------------------------------------


class TestReadmeAccuracy:
    @staticmethod
    def _text() -> str:
        return (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    def test_referenced_python_files_exist(self):
        text = self._text()
        referenced = set(re.findall(r"`([a-zA-Z0-9_/.-]+\.py)`", text))
        assert referenced, "README must reference real module paths"
        missing = [
            path for path in sorted(referenced)
            if not (PROJECT_ROOT / path).is_file()
        ]
        assert missing == []

    def test_key_files_exist(self):
        for path in (
            "app/main.py",
            "app/orchestrator.py",
            "app/exports.py",
            "core/constants.py",
            "database/repository.py",
            "scripts/generate_demo_data.py",
            ".env.example",
        ):
            assert (PROJECT_ROOT / path).exists(), path

    def test_gemini_key_behavior_documented(self):
        text = self._text()
        assert "GEMINI_API_KEY" in text
        assert "Disabled" in text

    def test_no_ml_or_auth_claims(self):
        text = self._text()
        assert "Isolation Forest" not in text
        assert "intentional placeholder" in text  # ml/ honesty note
        assert "no authentication" in text.lower()
