"""Phase 9 tests: plan provenance reads (``repository.list_plans``/``get_plan``).

Covers the additive read contract over the append-only audit store:
deterministic ordering, empty results, missing plans, invalid id
arguments, lossless round-trips through the real write path, per-plan
recommendation counts, and fail-closed behavior when stored JSON blocks
are corrupted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.schemas import RECOMMENDATION_KEYS  # noqa: E402
from core.exceptions import DataValidationError  # noqa: E402
from database import repository as repo  # noqa: E402
from database.connection import connect, init_db  # noqa: E402
from database.models import PlanRecord  # noqa: E402
from tests.test_persistence_service import make_plan, make_record  # noqa: E402


@pytest.fixture()
def engine(tmp_path):
    """Fresh file-backed SQLite engine with the schema bootstrapped."""
    eng = connect(f"sqlite:///{(tmp_path / 'plan_reads.db').as_posix()}")
    init_db(eng)
    yield eng
    eng.dispose()


def _two_distinct_records() -> list[dict]:
    return [
        make_record(recommendation_id="R-ALPHA"),
        make_record(recommendation_id="R-BETA"),
    ]


# --- list_plans ------------------------------------------------------------------------


class TestListPlans:
    def test_empty_store_returns_empty_list(self, engine):
        assert repo.list_plans(engine) == []

    def test_round_trip_single_plan(self, engine):
        records = _two_distinct_records()
        source_plan = make_plan(records)
        plan_id = repo.record_plan(engine, source_plan)

        plans = repo.list_plans(engine)
        assert len(plans) == 1
        entry = plans[0]
        assert entry["plan_id"] == plan_id
        assert entry["recommendation_count"] == 2
        assert entry["parameters"] == source_plan["parameters"]
        assert entry["source"] == source_plan["source"]
        assert entry["summary"] == source_plan["summary"]
        assert isinstance(entry["recorded_at"], str) and entry["recorded_at"]
        assert isinstance(entry["schema_version"], str)
        assert isinstance(entry["storage_schema_version"], str)
        assert entry["plan_type"] == source_plan["type"]

    def test_multiple_plans_deterministic_ordering(self, engine):
        ids = [
            repo.record_plan(engine, make_plan([make_record(recommendation_id=f"R-{i}")]))
            for i in range(3)
        ]
        listed = [plan["plan_id"] for plan in repo.list_plans(engine)]
        assert listed == sorted(ids)

    def test_recommendation_count_matches_linked_snapshots(self, engine):
        records = _two_distinct_records()
        repo.record_plan(engine, make_plan(records))
        # A standalone snapshot without a plan must not distort the count.
        repo.record_recommendation(engine, make_record(recommendation_id="R-SOLO"))
        plans = repo.list_plans(engine)
        assert len(plans) == 1
        assert plans[0]["recommendation_count"] == 2


# --- get_plan --------------------------------------------------------------------------


class TestGetPlan:
    def test_missing_plan_returns_none(self, engine):
        assert repo.get_plan(engine, 999) is None

    def test_round_trip_full_provenance_and_snapshots(self, engine):
        records = _two_distinct_records()
        source_plan = make_plan(records)
        plan_id = repo.record_plan(engine, source_plan)

        stored = repo.get_plan(engine, plan_id)
        assert stored is not None
        for block in ("parameters", "source", "summary"):
            assert stored[block] == source_plan[block]
        recommendations = stored["recommendations"]
        assert [r["recommendation_id"] for r in recommendations] == [
            "R-ALPHA",
            "R-BETA",
        ]
        for snapshot in recommendations:
            assert set(snapshot) == set(RECOMMENDATION_KEYS)

    def test_invalid_plan_ids_rejected(self, engine):
        repo.record_plan(engine, make_plan(_two_distinct_records()))
        for bad in (0, -1, "1", True, 1.5, None):
            with pytest.raises(DataValidationError):
                repo.get_plan(engine, bad)


# --- corrupted stored data fails closed ------------------------------------------------


class TestCorruptedStoredPlans:
    @staticmethod
    def _insert_corrupt_row(engine, column: str) -> int:
        valid = {
            "parameters_json": json.dumps(make_plan()["parameters"]),
            "source_json": json.dumps(make_plan()["source"]),
            "summary_json": json.dumps(make_plan()["summary"]),
        }
        values = {key: text for key, text in valid.items() if key != column}
        values[column] = "{not-valid-json"
        row = PlanRecord(
            recorded_at="2026-01-01T00:00:00+00:00",
            storage_schema_version="1.0.0",
            schema_version="1.0.0",
            plan_type="ops.recommendation.plan/v1",
            **values,
        )
        with Session(engine) as session, session.begin():
            session.add(row)
            session.flush()
            return int(row.id)

    @pytest.mark.parametrize(
        "column",
        ["parameters_json", "source_json", "summary_json"],
    )
    def test_corrupt_json_block_fails_closed(self, engine, column):
        plan_id = self._insert_corrupt_row(engine, column)
        with pytest.raises(DataValidationError, match="corrupted"):
            repo.list_plans(engine)
        with pytest.raises(DataValidationError, match="corrupted"):
            repo.get_plan(engine, plan_id)


# --- write-path regression guard -------------------------------------------------------


class TestWritePathGuardsStillHold:
    def test_duplicate_recommendation_ids_within_plan_rejected(self, engine):
        duplicated = make_record(recommendation_id="R-DUP")
        with pytest.raises(DataValidationError):
            repo.record_plan(engine, make_plan([duplicated, duplicated]))
