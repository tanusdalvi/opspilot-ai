"""Phase 9 tests: deterministic machine-readable exports.

Verifies structure, stable ordering, and byte-identical repeatability of
the three export surfaces (Analysis Summary JSON, Anomalies CSV,
Plans + Audit JSON) built by ``app.exports``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from agent.schemas import (  # noqa: E402
    EXPECTED_REVIEW_EVENT_KEYS,
    RECOMMENDATION_KEYS,
    REVIEW_EVENT_TYPE,
)
from app import exports  # noqa: E402
from database import repository as repo  # noqa: E402
from database.connection import connect, init_db  # noqa: E402
from services.data_service import load_dataset  # noqa: E402
from tests.test_persistence_service import make_plan, make_record  # noqa: E402

DEMO_DATASET = "demo_operational_data.csv"


@pytest.fixture(scope="module")
def artifacts():
    """One real pipeline run over the bundled demo dataset."""
    from app.orchestrator import run_pipeline

    return run_pipeline(load_dataset(DEMO_DATASET), dataset_name=DEMO_DATASET)


# --- Analysis Summary JSON -------------------------------------------------------------


class TestAnalysisSummary:
    def test_required_top_level_structure(self, artifacts):
        payload = exports.analysis_summary_payload(artifacts)
        assert set(payload) == {
            "export",
            "dataset",
            "validation",
            "kpis",
            "period_comparison",
            "trend",
            "anomalies",
            "insights",
            "grouping",
            "top_performers",
            "bottom_performers",
        }
        assert payload["export"]["kind"] == "opspilot-analysis-summary"
        assert payload["dataset"]["name"] == DEMO_DATASET
        assert payload["dataset"]["row_count"] > 0
        assert isinstance(payload["anomalies"]["total_count"], int)
        assert isinstance(payload["insights"], list)

    def test_deterministic_serialization(self, artifacts):
        first = exports.canonical_json(exports.analysis_summary_payload(artifacts))
        second = exports.canonical_json(exports.analysis_summary_payload(artifacts))
        assert first == second
        assert first.endswith("\n")


# --- Anomalies CSV ----------------------------------------------------------------------


class TestAnomaliesCsv:
    def test_header_and_row_alignment(self, artifacts):
        text = exports.anomalies_csv_text(artifacts)
        lines = text.splitlines()
        header = tuple(lines[0].split(","))
        assert header == exports.ANOMALY_CSV_COLUMNS
        expected_rows = artifacts.anomaly_result["total_count"]
        assert len(lines) - 1 == expected_rows
        for line in lines[1:]:
            assert len(line.split(",")) == len(exports.ANOMALY_CSV_COLUMNS)

    def test_no_memory_addresses_or_timestamps(self, artifacts):
        text = exports.anomalies_csv_text(artifacts)
        assert "0x" not in text.lower()
        assert "Timestamp" not in text

    def test_deterministic_output(self, artifacts):
        assert (
            exports.anomalies_csv_text(artifacts)
            == exports.anomalies_csv_text(artifacts)
        )


# --- Canonical JSON helper ----------------------------------------------------------------


class TestCanonicalJson:
    def test_key_order_is_sorted_regardless_of_insertion(self):
        left = exports.canonical_json({"b": 1, "a": {"z": 1, "y": 2}})
        right = exports.canonical_json({"a": {"y": 2, "z": 1}, "b": 1})
        assert left == right


# --- Plans + Audit JSON --------------------------------------------------------------------


class TestPlanAuditPayload:
    @pytest.fixture()
    def seeded(self, tmp_path):
        engine = connect(f"sqlite:///{(tmp_path / 'audit_export.db').as_posix()}")
        init_db(engine)
        plan_id = repo.record_plan(
            engine, make_plan([make_record(recommendation_id="R-EX")])
        )
        event = {
            "event_type": REVIEW_EVENT_TYPE,
            "recommendation_id": "R-EX",
            "reviewer_id": "auditor",
            "previous_status": "PENDING",
            "new_status": "APPROVED",
            "decision": "APPROVE",
            "comment": None,
            "occurred_at": "2026-01-01T00:00:00+00:00",
        }
        repo.record_review_event(engine, event)
        plan_details = [
            p for p in (repo.get_plan(engine, plan_id),) if p is not None
        ]
        events = repo.list_review_events(engine)
        yield plan_details, events
        engine.dispose()

    def test_structure_and_contract_fidelity(self, seeded):
        plan_details, events = seeded
        payload = exports.plan_audit_payload(plan_details, events)
        assert set(payload) == {"export", "plans", "review_events"}
        snapshot = payload["plans"][0]["recommendations"][0]
        assert set(snapshot) == set(RECOMMENDATION_KEYS)
        assert set(payload["review_events"][0]) == set(EXPECTED_REVIEW_EVENT_KEYS)

    def test_deterministic_output(self, seeded):
        plan_details, events = seeded
        first = exports.canonical_json(exports.plan_audit_payload(plan_details, events))
        second = exports.canonical_json(
            exports.plan_audit_payload(plan_details, events)
        )
        assert first == second

    def test_exports_never_contain_secrets(self, seeded):
        plan_details, events = seeded
        blob = exports.canonical_json(exports.plan_audit_payload(plan_details, events))
        assert "GEMINI_API_KEY" not in blob
        assert "api_key" not in blob.lower()


# --- Guard against accidental nondeterministic inputs ----------------------------------------


class TestNoNondeterministicInputs:
    def test_summary_survives_dataframe_trend_columns(self, artifacts):
        """Daily trends are reduced to bounds; raw frames never serialized."""
        payload_text = exports.canonical_json(exports.analysis_summary_payload(artifacts))
        assert isinstance(payload_text, str)
        # A pandas repr would contain the class name; canonical JSON must not.
        assert "DataFrame" not in payload_text
