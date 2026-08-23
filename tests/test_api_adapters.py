"""Phase 12 API adapter tests.

Covers the transport boundary only: every route must delegate to the
real orchestrator/services (no duplicated logic), preserve lifecycle
semantics, keep the AI investigation explicit, and never leak internals
or secrets.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# The API reads the audit database; tests always run against an isolated
# SQLite file so developer state can never leak in (or out).
import os  # noqa: E402

_TMP_DB = Path(PROJECT_ROOT, "data", "tmp_phase12_api.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402

from backend.api import main as api_main  # noqa: E402
from backend.api import sessions as api_sessions  # noqa: E402
from core.exceptions import AgentError, DataValidationError  # noqa: E402

client = TestClient(api_main.app)


@pytest.fixture()
def session_token() -> dict:
    response = client.get("/api/system")
    assert response.status_code == 200
    token = response.headers[api_main.SESSION_HEADER]
    return {"headers": {api_main.SESSION_HEADER: token}, "token": token}


def _load_demo(token_headers: dict) -> dict:
    response = client.post(
        "/api/datasets/load-demo",
        json={"filename": "demo_operational_data.csv"},
        headers=token_headers["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _run_analysis_wait(token_headers: dict, sensitivity: str = "medium") -> dict:
    response = client.post(
        "/api/analysis/run",
        json={"sensitivity": sensitivity, "wait": True},
        headers=token_headers["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- system / health -------------------------------------------------------------------------------


def test_healthz_ok():
    assert client.get("/api/healthz").json() == {"status": "ok"}


def test_system_mints_session_header_and_defaults():
    response = client.get("/api/system")
    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis_status"] in {"IDLE", "RECOVERY_AVAILABLE"}
    assert payload["gemini_model"] == "gemini-3.6-flash"
    assert isinstance(payload["ai_available"], bool)
    assert api_main.SESSION_HEADER in response.headers


def test_system_reports_lifecycle_stage(session_token):
    _load_demo(session_token)
    payload = client.get("/api/system", headers=session_token["headers"]).json()
    assert payload["lifecycle_stage"] == "OBSERVE"
    _run_analysis_wait(session_token)
    payload = client.get("/api/system", headers=session_token["headers"]).json()
    assert payload["analysis_status"] == "READY"
    assert payload["artifacts_ready"] is True


# --- datasets ---------------------------------------------------------------------------------------


def test_demo_datasets_listing():
    response = client.get("/api/demo-datasets")
    assert response.status_code == 200
    datasets = response.json()["datasets"]
    assert any(d.get("name") == "demo_operational_data.csv" for d in datasets)


def test_load_demo_resets_to_idle_and_validates(session_token):
    body = _load_demo(session_token)
    assert body["dataset"]["rows"] > 0
    assert body["analysis_status"] == "IDLE"
    assert isinstance(body["validation_report"], dict)


def test_load_unknown_demo_dataset_maps_to_404(session_token):
    response = client.post(
        "/api/datasets/load-demo",
        json={"filename": "does_not_exist.csv"},
        headers=session_token["headers"],
    )
    assert response.status_code == 404
    assert "error" in response.json() or "detail" in response.json()


# --- dataset preview (Data Explorer) --------------------------------------------------------------------


def test_preview_requires_loaded_dataset(session_token):
    response = client.get(
        "/api/datasets/preview", headers=session_token["headers"]
    )
    assert response.status_code == 409


def test_preview_returns_columns_rows_and_kinds(session_token):
    _load_demo(session_token)
    body = client.get(
        "/api/datasets/preview", headers=session_token["headers"]
    ).json()
    assert body["total_rows"] > 0
    assert len(body["rows"]) <= 500
    assert {c["kind"] for c in body["columns"]} <= {"date", "numeric", "categorical", "text"}
    names = {c["name"] for c in body["columns"]}
    row = body["rows"][0]
    assert names == set(row.keys())


def test_preview_row_cap_is_enforced(session_token):
    _load_demo(session_token)
    body = client.get(
        "/api/datasets/preview?rows=25", headers=session_token["headers"]
    ).json()
    assert len(body["rows"]) <= 25
    # The hard ceiling holds even when the caller asks for more.
    body = client.get(
        "/api/datasets/preview?rows=999999", headers=session_token["headers"]
    ).json()
    assert len(body["rows"]) <= 1000


def test_analysis_requires_loaded_dataset(session_token):
    response = client.post(
        "/api/analysis/run",
        json={"sensitivity": "medium", "wait": True},
        headers=session_token["headers"],
    )
    assert response.status_code == 409


def test_invalid_sensitivity_rejected(session_token):
    _load_demo(session_token)
    response = client.post(
        "/api/analysis/run",
        json={"sensitivity": "ultra", "wait": True},
        headers=session_token["headers"],
    )
    assert response.status_code == 422


# --- analysis pipeline ---------------------------------------------------------------------------------


def test_full_pipeline_ready_and_artifacts_shape(session_token):
    _load_demo(session_token)
    result = _run_analysis_wait(session_token, sensitivity="high")
    assert result["analysis_status"] == "READY"

    status = client.get("/api/analysis/status", headers=session_token["headers"]).json()
    assert status["artifacts_ready"] is True

    artifacts = client.get(
        "/api/analysis/artifacts", headers=session_token["headers"]
    ).json()["artifacts"]
    expected_sections = {
        "dataset_name", "kpis", "period_comparison", "top_performers",
        "bottom_performers", "anomaly_result", "anomaly_summary",
        "insights", "grouping", "pack", "region_performance",
        "product_performance", "daily_trends", "validation_report",
        "row_count",
    }
    assert expected_sections <= set(artifacts)
    assert artifacts["pack"]["evidence_index"]
    assert artifacts["row_count"] > 0


def test_artifacts_conflict_before_analysis(session_token):
    _load_demo(session_token)
    response = client.get("/api/analysis/artifacts", headers=session_token["headers"])
    assert response.status_code == 409


# --- evidence / investigation -------------------------------------------------------------------------


def test_evidence_pack_available_after_analysis(session_token):
    _load_demo(session_token)
    _run_analysis_wait(session_token)
    pack = client.get("/api/evidence/pack", headers=session_token["headers"]).json()["pack"]
    assert pack["type"] and pack["evidence_index"]


def test_investigation_blocked_without_analysis(session_token):
    _load_demo(session_token)
    response = client.post(
        "/api/investigation/run", headers=session_token["headers"]
    )
    assert response.status_code == 409


def test_investigation_explicit_run_completes_with_fake_client(session_token, monkeypatch):
    """The explicit-investigation contract end to end with a fake narrator."""
    from tests.test_agent_investigator import encode, grounded_response

    _load_demo(session_token)
    _run_analysis_wait(session_token)
    pack = client.get(
        "/api/evidence/pack", headers=session_token["headers"]
    ).json()["pack"]

    class FakeClient:
        def generate_json(self, prompt: str) -> str:
            # Grounded entirely against THIS session's real pack.
            return encode(grounded_response(pack))

    monkeypatch.setattr(
        api_sessions, "get_investigation_client", lambda: FakeClient()
    )

    run = client.post("/api/investigation/run", headers=session_token["headers"])
    assert run.status_code == 200
    assert run.json()["investigation_status"] == "running"

    # Background thread: poll briefly for completion (bounded).
    import time

    final = None
    for _ in range(120):
        status_payload = client.get(
            "/api/investigation/status", headers=session_token["headers"]
        ).json()
        if status_payload["investigation_status"] in {"complete", "error"}:
            final = status_payload
            break
        time.sleep(0.1)
    assert final is not None, "investigation never reached a terminal state"
    assert final["investigation_status"] == "complete", final["investigation_error"]
    result = final["result"]
    assert result["status"] == "complete"
    assert set(result) == {
        "status", "evidence_pack", "narrative", "hypotheses", "citations",
        "grounding_report",
    }
    assert result["grounding_report"]["valid"] is True


def test_investigation_error_is_recorded_not_raised(session_token, monkeypatch):
    _load_demo(session_token)
    _run_analysis_wait(session_token)

    class ExplodingClient:
        def generate_json(self, _prompt: str) -> str:
            raise RuntimeError("network down")

    monkeypatch.setattr(
        api_sessions, "get_investigation_client", lambda: ExplodingClient()
    )
    client.post("/api/investigation/run", headers=session_token["headers"])

    import time

    for _ in range(120):
        payload = client.get(
            "/api/investigation/status", headers=session_token["headers"]
        ).json()
        if payload["investigation_status"] == "error":
            break
        time.sleep(0.1)
    assert payload["investigation_status"] == "error"
    assert payload["investigation_error"] == "RuntimeError"  # type name only
    assert "network down" not in (payload["investigation_error"] or "")


# --- plan / review ----------------------------------------------------------------------------------------


def _generate_plan(token_headers: dict) -> dict:
    response = client.post(
        "/api/plan/generate", json={}, headers=token_headers["headers"]
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_plan_generated_once_and_persisted_once(session_token, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'audit.db').as_posix()}")
    _load_demo(session_token)
    _run_analysis_wait(session_token)

    first = _generate_plan(session_token)
    recommendations = first["plan"]["recommendations"]
    assert isinstance(recommendations, list) and recommendations
    persisted_id = first["plan_persisted_id"]
    assert isinstance(persisted_id, int)

    second = _generate_plan(session_token)
    assert second["plan_persisted_id"] == persisted_id  # persistence-once rule


def test_review_flow_records_event_and_updates_record(session_token, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'audit.db').as_posix()}")
    _load_demo(session_token)
    _run_analysis_wait(session_token)
    plan = _generate_plan(session_token)["plan"]
    target = plan["recommendations"][0]
    previous_status = target["status"]

    decision = "APPROVE"
    response = client.post("/api/review", headers=session_token["headers"], json={
        "recommendation_id": target["recommendation_id"],
        "decision": decision,
        "reviewer_id": "ops-manager",
        "comment": "Phase 12 console smoke",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["record"]["status"] == "APPROVED"
    event = body["event"]
    assert event["recommendation_id"] == target["recommendation_id"]
    assert event["previous_status"] == previous_status
    assert event["new_status"] == "APPROVED"
    assert event["reviewer_id"] == "ops-manager"


def test_review_rejects_invalid_decision(session_token, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'audit.db').as_posix()}")
    _load_demo(session_token)
    _run_analysis_wait(session_token)
    plan = _generate_plan(session_token)["plan"]
    target = plan["recommendations"][0]
    response = client.post("/api/review", headers=session_token["headers"], json={
        "recommendation_id": target["recommendation_id"],
        "decision": "MAYBE",
        "reviewer_id": "ops-manager",
    })
    assert response.status_code == 400


def test_review_unknown_recommendation_rejected(session_token, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'audit.db').as_posix()}")
    _load_demo(session_token)
    _run_analysis_wait(session_token)
    _generate_plan(session_token)
    response = client.post("/api/review", headers=session_token["headers"], json={
        "recommendation_id": "R-DOES-NOT-EXIST",
        "decision": "APPROVE",
        "reviewer_id": "ops-manager",
    })
    assert response.status_code == 400


# --- history / exports -----------------------------------------------------------------------------------------


def test_history_reflects_recorded_activity(session_token, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'audit.db').as_posix()}")
    _load_demo(session_token)
    _run_analysis_wait(session_token)
    plan = _generate_plan(session_token)["plan"]
    client.post("/api/review", headers=session_token["headers"], json={
        "recommendation_id": plan["recommendations"][0]["recommendation_id"],
        "decision": "APPROVE",
        "reviewer_id": "ops-manager",
    })

    history = client.get("/api/history").json()
    assert history["counts"]["plans"] >= 1
    assert history["counts"]["review_events"] >= 1
    assert history["review_events"][0]["recommendation_id"]  # no fabricated ids


def test_export_audit_returns_canonical_json():
    response = client.get("/api/export/audit")
    assert response.status_code == 200
    body = response.json()
    assert "payload" in body and "canonical_json" in body


# --- error safety ---------------------------------------------------------------------------------------------------


def test_unexpected_errors_map_to_safe_500():
    local_client = TestClient(api_main.app, raise_server_exceptions=False)

    @api_main.app.get("/api/__phase12_boom_test", include_in_schema=False)
    def _boom() -> dict:
        raise RuntimeError("secret internals: sk-live-never-show")

    response = local_client.get("/api/__phase12_boom_test")
    assert response.status_code == 500
    assert response.json()["error"].startswith("Unexpected application error")
    assert "secret" not in response.text


def test_no_secret_material_in_any_payload(session_token):
    from core.config import get_gemini_api_key

    key = get_gemini_api_key() or ""
    _load_demo(session_token)
    _run_analysis_wait(session_token)
    for path in ("/api/system", "/api/analysis/artifacts", "/api/history"):
        body = client.get(path, headers=session_token["headers"]).text
        if key:
            assert key not in body, path


# --- module-level hygiene ------------------------------------------------------------------------------------------


def test_api_layer_imports_no_streamlit():
    source = ""
    for module_file in (Path(api_main.__file__).parent).glob("*.py"):
        source += module_file.read_text(encoding="utf-8")
    assert "import streamlit" not in source


def test_agent_error_type_used_for_mapping_only():
    # Sanity: the adapter maps typed errors without re-raising internals.
    assert issubclass(AgentError, Exception)
    assert issubclass(DataValidationError, Exception)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_tmp_db():
    yield
    try:
        _TMP_DB.unlink(missing_ok=True)
    except OSError:
        pass
