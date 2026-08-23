"""Phase 10B restart-recovery tests.

Covers the recovery metadata sidecar (save/load/validate/availability)
and the derived ``RECOVERY_AVAILABLE`` lifecycle state, proving that:

* missing, corrupt, future-versioned, or invalid context fails safe;
* a deleted or renamed dataset yields plain IDLE, never an error;
* recovery NEVER fabricates READY — artifacts only exist after a real
  run in the live session;
* successful and failed re-run transitions preserve Phase 8A behavior.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.orchestrator import (  # noqa: E402
    build_recovery_context,
    clear_recovery_context,
    load_recovery_context,
    recovery_dataset_available,
    run_pipeline,
    save_recovery_context,
)


@pytest.fixture()
def recovery_path(tmp_path, monkeypatch):
    path = tmp_path / "recovery_context.json"
    monkeypatch.setenv("OPSPILOT_RECOVERY_PATH", str(path))
    return path


# --- Sidecar persistence and validation --------------------------------------


class TestRecoverySidecar:
    def test_missing_file_loads_as_none(self, recovery_path):
        assert load_recovery_context() is None

    def test_save_then_load_round_trip(self, recovery_path):
        save_recovery_context("demo_operational_data.csv", "medium")
        context = load_recovery_context()
        assert context is not None
        assert context["dataset_name"] == "demo_operational_data.csv"
        assert context["source"] == "demo"
        assert context["sensitivity"] == "medium"
        assert context["status"] == "READY"
        assert context["version"] == 1

    def test_corrupt_json_fails_safe(self, recovery_path):
        recovery_path.write_text("{not valid json!!", encoding="utf-8")
        assert load_recovery_context() is None

    @pytest.mark.parametrize(
        "mutation",
        [
            {"version": 999},  # incompatible future metadata
            {"dataset_name": ""},
            {"dataset_name": "../escape.csv"},
            {"dataset_name": 123},
            {"sensitivity": "turbo"},
            {"source": "cloud"},
            {"status": "RUNNING"},
            {"completed_at": "not-a-timestamp"},
            {"completed_at": None},
        ],
    )
    def test_invalid_fields_fail_safe(self, recovery_path, mutation):
        save_recovery_context("demo_operational_data.csv", "low")
        raw = json.loads(recovery_path.read_text(encoding="utf-8"))
        raw.update(mutation)
        recovery_path.write_text(json.dumps(raw), encoding="utf-8")
        assert load_recovery_context() is None, mutation

    def test_non_mapping_payload_fails_safe(self, recovery_path):
        recovery_path.write_text("[1, 2, 3]", encoding="utf-8")
        assert load_recovery_context() is None

    def test_clear_removes_sidecar(self, recovery_path):
        save_recovery_context("demo_operational_data.csv", "high")
        clear_recovery_context()
        assert load_recovery_context() is None

    def test_upload_source_recorded_for_unknown_demo_names(self, recovery_path):
        save_recovery_context("my_upload.csv", "high")
        assert load_recovery_context()["source"] == "upload"

    def test_loading_is_deterministic(self, recovery_path):
        save_recovery_context("demo_operational_data.csv", "medium")
        first = load_recovery_context()
        second = load_recovery_context()
        assert first == second


# --- Dataset availability -------------------------------------------------------


class TestDatasetAvailability:
    def test_existing_demo_dataset_is_available(self):
        context = build_recovery_context("demo_operational_data.csv", "medium")
        assert recovery_dataset_available(context) is True

    def test_deleted_or_renamed_demo_dataset_is_unavailable(self):
        context = build_recovery_context("deleted_dataset.csv", "medium")
        assert context["source"] == "upload"  # unknown demo names are uploads
        assert recovery_dataset_available(context) is False

    def test_missing_staged_upload_is_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.orchestrator.UPLOAD_DIR", tmp_path / "uploads", raising=False
        )
        context = {
            "dataset_name": "gone.csv",
            "source": "upload",
        }
        assert recovery_dataset_available(context) is False

    def test_non_dict_context_is_unavailable(self):
        assert recovery_dataset_available(None) is False
        assert recovery_dataset_available("demo_operational_data.csv") is False

    def test_unknown_source_is_unavailable(self):
        assert recovery_dataset_available(
            {"dataset_name": "x.csv", "source": "ftp"}
        ) is False


# --- Lifecycle integration (real AppTest sessions) -------------------------------
#
# AppTest.from_function re-executes scenario source in isolation, so every
# scenario is self-contained. The sidecar path travels via OPSPILOT_RECOVERY_PATH.


def _write_sidecar(path: str, dataset: str, source: str = "demo") -> None:
    from pathlib import Path as _Path

    payload = {
        "version": 1,
        "dataset_name": dataset,
        "source": source,
        "sensitivity": "medium",
        "completed_at": "2026-08-23T10:00:00",
        "status": "READY",
    }
    target = _Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")


class TestRecoveryLifecycle:
    def test_no_context_means_plain_idle(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "OPSPILOT_RECOVERY_PATH", str(tmp_path / "none.json")
        )

        def scenario():
            import streamlit as st

            from app.state import ANALYSIS_IDLE, get_analysis_status

            st.session_state.clear()
            assert get_analysis_status() == ANALYSIS_IDLE

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception

    def test_valid_context_offers_recovery_without_artifacts(
        self, tmp_path, monkeypatch
    ):
        sidecar = tmp_path / "rec.json"
        _write_sidecar(str(sidecar), "demo_operational_data.csv")
        monkeypatch.setenv("OPSPILOT_RECOVERY_PATH", str(sidecar))

        def scenario():
            import streamlit as st

            from app.state import (
                ANALYSIS_RECOVERY_AVAILABLE,
                get_analysis_status,
                require_artifacts,
            )

            st.session_state.clear()
            assert get_analysis_status() == ANALYSIS_RECOVERY_AVAILABLE
            # The affordance renders guidance; it fabricates nothing.
            require_artifacts()
            from app.state import get_artifacts

            assert get_artifacts() is None

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        infos = "\n".join(str(info.value) for info in at.info)
        assert "Previous analysis found" in infos

    def test_missing_referenced_dataset_falls_back_to_idle(
        self, tmp_path, monkeypatch
    ):
        sidecar = tmp_path / "rec.json"
        _write_sidecar(str(sidecar), "renamed_away.csv", source="upload")
        monkeypatch.setenv("OPSPILOT_RECOVERY_PATH", str(sidecar))

        def scenario():
            import streamlit as st

            from app.state import ANALYSIS_IDLE, get_analysis_status

            st.session_state.clear()
            assert get_analysis_status() == ANALYSIS_IDLE

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception

    def test_corrupt_sidecar_falls_back_to_idle(self, tmp_path, monkeypatch):
        sidecar = tmp_path / "rec.json"
        sidecar.write_text("{{{corrupt", encoding="utf-8")
        monkeypatch.setenv("OPSPILOT_RECOVERY_PATH", str(sidecar))

        def scenario():
            import streamlit as st

            from app.state import ANALYSIS_IDLE, get_analysis_status

            st.session_state.clear()
            assert get_analysis_status() == ANALYSIS_IDLE

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception

    def test_full_success_transition_and_no_fake_ready(self, tmp_path, monkeypatch):
        sidecar = tmp_path / "rec.json"
        _write_sidecar(str(sidecar), "demo_operational_data.csv")
        monkeypatch.setenv("OPSPILOT_RECOVERY_PATH", str(sidecar))

        def scenario():
            import pandas as pd
            import streamlit as st

            from app.orchestrator import run_pipeline
            from app.state import (
                ANALYSIS_READY,
                ANALYSIS_RECOVERY_AVAILABLE,
                ANALYSIS_RUNNING,
                begin_analysis,
                complete_analysis,
                fail_analysis,
                get_analysis_status,
                get_artifacts,
                require_artifacts,
            )

            st.session_state.clear()
            assert get_analysis_status() == ANALYSIS_RECOVERY_AVAILABLE

            # User chooses to re-run: IDLE-equivalent -> ANALYZING -> READY.
            begin_analysis()
            assert get_analysis_status() == ANALYSIS_RUNNING

            values = [100.0, 101.0, 99.0, 100.0, 102.0, 98.0, 101.0, 400.0]
            frame = pd.DataFrame(
                {
                    "date": [f"2024-01-{offset + 1:02d}" for offset in range(8)],
                    "region": ["North"] * 8,
                    "product": ["A"] * 8,
                    "units_sold": [10] * 8,
                    "revenue": values,
                    "cost": [5.0] * 8,
                    "lead_time_days": [5] * 8,
                }
            )
            artifacts = run_pipeline(frame, dataset_name="demo_operational_data.csv")
            complete_analysis(artifacts)

            status = get_analysis_status()
            assert status == ANALYSIS_READY
            stored = get_artifacts()
            assert stored is not None and stored.anomaly_result["total_count"] > 0

            # READY without artifacts can never occur through the helpers:
            # simulate a corrupted session and prove nothing is fabricated.
            st.session_state.analysis_artifacts = None
            st.session_state.analysis_status = "READY"
            assert require_artifacts() is None

        at = AppTest.from_function(scenario, default_timeout=120)
        at.run()
        assert not at.exception

    def test_failed_rerun_transitions_to_error_safely(self, tmp_path, monkeypatch):
        sidecar = tmp_path / "rec.json"
        _write_sidecar(str(sidecar), "demo_operational_data.csv")
        monkeypatch.setenv("OPSPILOT_RECOVERY_PATH", str(sidecar))

        def scenario():
            import streamlit as st

            from core.exceptions import DataValidationError
            from app.state import (
                ANALYSIS_ERROR,
                ANALYSIS_RUNNING,
                begin_analysis,
                fail_analysis,
                get_analysis_status,
                get_artifacts,
            )

            st.session_state.clear()
            begin_analysis()
            assert get_analysis_status() == ANALYSIS_RUNNING
            fail_analysis(str(DataValidationError("bad dataset")))
            assert get_analysis_status() == ANALYSIS_ERROR
            assert get_artifacts() is None
            reason = st.session_state.get("analysis_error")
            assert reason == "bad dataset"

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception

    def test_previous_artifacts_survive_a_later_failed_run(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv(
            "OPSPILOT_RECOVERY_PATH", str(tmp_path / "rec.json")
        )

        def scenario():
            import pandas as pd
            import streamlit as st

            from app.orchestrator import run_pipeline
            from app.state import (
                begin_analysis,
                complete_analysis,
                fail_analysis,
                get_analysis_status,
                require_artifacts,
            )

            st.session_state.clear()

            def build_frame(spike: float) -> pd.DataFrame:
                values = [100.0, 101.0, 99.0, 100.0, 102.0, 98.0, 101.0, spike]
                return pd.DataFrame(
                    {
                        "date": [f"2024-02-{offset + 1:02d}" for offset in range(8)],
                        "region": ["North"] * 8,
                        "product": ["A"] * 8,
                        "units_sold": [10] * 8,
                        "revenue": values,
                        "cost": [5.0] * 8,
                        "lead_time_days": [5] * 8,
                    }
                )

            complete_analysis(run_pipeline(build_frame(400.0), dataset_name="a.csv"))
            good = require_artifacts()
            assert good is not None

            begin_analysis()
            fail_analysis("Unexpected application error (RuntimeError).")

            # Existing intended lifecycle: previous valid results remain
            # visible with a warning; they are not silently discarded.
            kept = require_artifacts()
            assert kept is good
            assert get_analysis_status() == "ERROR"

        at = AppTest.from_function(scenario, default_timeout=120)
        at.run()
        assert not at.exception
        warnings_text = "\n".join(str(w.value) for w in at.warning)
        assert "Previous results are shown below" in warnings_text


# --- Deterministic re-runs --------------------------------------------------------


class TestRecoveryDeterminism:
    def test_repeated_pipelines_are_equivalent(self):
        values = [100.0, 101.0, 99.0, 100.0, 102.0, 98.0, 101.0, 400.0]
        frame = pd.DataFrame(
            {
                "date": [f"2024-03-{offset + 1:02d}" for offset in range(8)],
                "region": ["North"] * 8,
                "product": ["A"] * 8,
                "units_sold": [10] * 8,
                "revenue": values,
                "cost": [5.0] * 8,
                "lead_time_days": [5] * 8,
            }
        )
        first = run_pipeline(frame, dataset_name="determinism.csv")
        second = run_pipeline(frame, dataset_name="determinism.csv")
        assert first.anomaly_summary == second.anomaly_summary
        assert first.insights == second.insights
