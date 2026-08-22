"""Tests for the Phase 7 SQLite persistence and audit repository.

Covers ``database.connection``, ``database.models``, and
``database.repository`` against the approved contract: SQLite-only URL
resolution, idempotent schema bootstrap, strict structural validation of
Phase 5 plans/records and Phase 6 review events before anything is
written, append-only semantics with no update/delete paths, lossless
round-trips, caller-injected timestamps, defense-in-depth lifecycle
re-validation, determinism, and end-to-end integration with the real
Phase 5 generator and Phase 6 review workflow.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.evidence import build_investigation_context
from agent.recommendation_service import generate_recommendations
from agent.review_service import (
    KNOWN_REVIEW_STATUSES,
    approve_recommendation,
    create_review_event,
    request_changes,
    resubmit_recommendation,
    review_recommendation,
)
from agent.schemas import (
    EXPECTED_REVIEW_EVENT_KEYS,
    RECOMMENDATION_CHANGES_REQUESTED,
    PERSISTENCE_SCHEMA_VERSION,
    RECOMMENDATION_KEYS,
    RECOMMENDATION_PLAN_TYPE,
    RECOMMENDATION_SCHEMA_VERSION,
)
from core.constants import (
    RECOMMENDATION_APPROVED,
    RECOMMENDATION_PENDING,
    RECOMMENDATION_REJECTED,
)
from core.exceptions import DataValidationError, DatabaseError
from database import repository as repo
from database.connection import (
    DEFAULT_DATABASE_URL,
    connect,
    init_db,
    resolve_database_url,
)
from database.models import PlanRecord, RecommendationRecord, ReviewEventRecord

# --- Shared fixtures -------------------------------------------------------------


@pytest.fixture()
def engine(tmp_path):
    """Fresh file-backed SQLite engine with the schema bootstrapped."""
    eng = connect(f"sqlite:///{(tmp_path / 'audit.db').as_posix()}")
    init_db(eng)
    yield eng
    eng.dispose()


def make_record(**overrides: object) -> dict[str, object]:
    """Minimal valid Phase 5 record (exact 17-key contract)."""
    base: dict[str, object] = {
        "recommendation_id": "R1",
        "priority": "HIGH",
        "priority_score": 60.0,
        "action_type": "manual_investigation",
        "title": "Investigate HIGH anomaly",
        "description": "A localized HIGH revenue anomaly was detected.",
        "scope": "dataset",
        "target_entity": None,
        "target_metric": None,
        "date_window": None,
        "source_factors": ["localized_high_anomaly"],
        "source_anomaly_indices": [3],
        "source_group_ids": [],
        "evidence_ids": ["EV-4"],
        "evidence_strength": 20.0,
        "requires_human_review": True,
        "status": RECOMMENDATION_PENDING,
    }
    base.update(overrides)
    return base


def make_event(**overrides: object) -> dict[str, object]:
    """Minimal valid structured review event (APPROVE on R1)."""
    base: dict[str, object] = {
        "event_type": "recommendation_review",
        "recommendation_id": "R1",
        "reviewer_id": "ops-user",
        "previous_status": RECOMMENDATION_PENDING,
        "new_status": RECOMMENDATION_APPROVED,
        "decision": "APPROVE",
        "comment": None,
        "occurred_at": "2026-03-01T10:00:00+00:00",
    }
    base.update(overrides)
    return base


def make_plan(records: list[dict] | None = None, **overrides: object) -> dict[str, object]:
    """Minimal valid Phase 5 plan wrapping the given records."""
    records = [make_record()] if records is None else records
    by_priority: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for record in records:
        by_priority[str(record["priority"])] = by_priority.get(str(record["priority"]), 0) + 1
        action = str(record["action_type"])
        by_action[action] = by_action.get(action, 0) + 1
    base: dict[str, object] = {
        "type": RECOMMENDATION_PLAN_TYPE,
        "schema_version": RECOMMENDATION_SCHEMA_VERSION,
        "parameters": {
            "sensitivity": 2.5,
            "metrics": ["revenue"],
            "focus": {"scopes": ["daily"], "entities": [], "date_range": None},
        },
        "source": {
            "anomaly_count": 3,
            "group_count": 1,
            "investigation_status": None,
            "cited_evidence_ids": ["EV-4"],
        },
        "recommendations": records,
        "summary": {
            "total_count": len(records),
            "by_priority": by_priority,
            "by_action_type": dict(sorted(by_action.items())),
        },
    }
    base.update(overrides)
    return base


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# --- Connection contract -----------------------------------------------------------


class TestConnectionContract:
    def test_explicit_url_wins(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite:///from_env.db")
        assert resolve_database_url("sqlite:///explicit.db") == "sqlite:///explicit.db"

    def test_env_url_used_without_argument(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite:///env_choice.db")
        assert resolve_database_url() == "sqlite:///env_choice.db"

    def test_default_when_nothing_configured(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert resolve_database_url() == DEFAULT_DATABASE_URL

    def test_default_matches_env_example_convention(self):
        assert DEFAULT_DATABASE_URL == "sqlite:///opspilot.db"

    @pytest.mark.parametrize(
        "url", ["postgresql://localhost/db", "mysql://x", "memory://", "sqlite-clone://y"]
    )
    def test_non_sqlite_scheme_fails_closed(self, url):
        with pytest.raises(DataValidationError, match="SQLite"):
            resolve_database_url(url)

    @pytest.mark.parametrize("url", ["", "   ", 42])
    def test_malformed_urls_rejected(self, url):
        with pytest.raises(DataValidationError):
            resolve_database_url(url)


# --- Schema bootstrap --------------------------------------------------------------


class TestSchemaBootstrap:
    def test_exactly_three_tables_created(self, engine):
        from sqlalchemy import inspect

        assert sorted(inspect(engine).get_table_names()) == [
            "recommendation_plans",
            "recommendations",
            "review_events",
        ]

    def test_init_db_is_idempotent(self, engine):
        init_db(engine)
        init_db(engine)
        assert repo.count_plans(engine) == 0

    def test_rows_survive_reinitialization(self, engine):
        repo.record_plan(engine, make_plan(), recorded_at="2026-03-01T09:00:00+00:00")
        init_db(engine)
        assert repo.count_plans(engine) == 1

    def test_connect_produces_working_engine(self, tmp_path):
        eng = connect(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
        try:
            init_db(eng)
            assert repo.count_review_events(eng) == 0
        finally:
            eng.dispose()


# --- record_plan ---------------------------------------------------------------------


class TestRecordPlan:
    def test_returns_sequential_ids_and_counts(self, engine):
        first = repo.record_plan(engine, make_plan(), recorded_at="2026-03-01T09:00:00+00:00")
        second = repo.record_plan(
            engine,
            make_plan([make_record(recommendation_id="R2")]),
            recorded_at="2026-03-01T09:05:00+00:00",
        )
        assert isinstance(first, int) and isinstance(second, int)
        assert second == first + 1
        assert repo.count_plans(engine) == 2
        assert repo.count_recommendations(engine) == 2

    def test_round_trip_is_lossless(self, engine):
        record = make_record(
            priority_score=60.5,
            title="Ünïcode — título ✓",
            description="Déjà vu",
            source_factors=["localized_high_anomaly", "peer_gap"],
            evidence_ids=["EV-4", "EV-9"],
        )
        repo.record_plan(engine, make_plan([record]), recorded_at="2026-03-01T09:00:00+00:00")
        assert repo.get_latest_recommendation(engine, "R1") == record

    def test_empty_plan_allowed(self, engine):
        plan_id = repo.record_plan(engine, make_plan([]), recorded_at="2026-03-01T09:00:00+00:00")
        assert isinstance(plan_id, int)
        assert repo.count_plans(engine) == 1
        assert repo.count_recommendations(engine) == 0

    def test_plan_row_columns_stored_verbatim(self, engine):
        plan = make_plan()
        repo.record_plan(engine, plan, recorded_at="2026-03-02T08:30:00+00:00")
        with Session(engine) as session:
            row = session.scalars(select(PlanRecord)).one()
        assert row.recorded_at == "2026-03-02T08:30:00+00:00"
        assert row.storage_schema_version == PERSISTENCE_SCHEMA_VERSION
        assert row.schema_version == RECOMMENDATION_SCHEMA_VERSION
        assert row.plan_type == RECOMMENDATION_PLAN_TYPE
        assert json.loads(row.parameters_json) == plan["parameters"]
        assert json.loads(row.source_json) == plan["source"]
        assert json.loads(row.summary_json) == plan["summary"]

    def test_json_text_is_canonical_sorted_keys(self, engine):
        plan = make_plan()
        repo.record_plan(engine, plan, recorded_at="2026-03-01T09:00:00+00:00")
        with Session(engine) as session:
            row = session.scalars(select(PlanRecord)).one()
        assert row.source_json == _canonical(plan["source"])

    def test_omitted_recorded_at_defaults_to_utc_now(self, engine):
        before = datetime.now(timezone.utc)
        repo.record_plan(engine, make_plan())
        with Session(engine) as session:
            row = session.scalars(select(PlanRecord)).one()
        parsed = datetime.fromisoformat(row.recorded_at)
        assert parsed.tzinfo is not None
        assert before - parsed < pd.Timedelta(seconds=30)

    def test_same_id_across_different_plans_allowed(self, engine):
        older = make_record(status=RECOMMENDATION_PENDING)
        newer = make_record(status=RECOMMENDATION_APPROVED)
        repo.record_plan(engine, make_plan([older]), recorded_at="2026-03-01T09:00:00+00:00")
        repo.record_plan(engine, make_plan([newer]), recorded_at="2026-03-01T10:00:00+00:00")
        latest = repo.get_latest_recommendation(engine, "R1")
        assert latest["status"] == RECOMMENDATION_APPROVED
        assert repo.count_recommendations(engine) == 2

    def test_duplicate_ids_within_one_plan_rejected_and_atomic(self, engine):
        with pytest.raises(DataValidationError, match="duplicate"):
            repo.record_plan(engine, make_plan([make_record(), make_record()]))
        assert repo.count_plans(engine) == 0
        assert repo.count_recommendations(engine) == 0

    def test_input_plan_never_mutated(self, engine):
        plan = make_plan()
        snapshot = copy.deepcopy(plan)
        repo.record_plan(engine, plan, recorded_at="2026-03-01T09:00:00+00:00")
        assert plan == snapshot


# --- record_recommendation ---------------------------------------------------------


class TestRecordRecommendationStandalone:
    def test_standalone_snapshot_round_trips(self, engine):
        record = make_record()
        row_id = repo.record_recommendation(engine, record)
        assert isinstance(row_id, int)
        assert repo.get_latest_recommendation(engine, "R1") == record

    def test_linked_to_existing_plan(self, engine):
        plan_id = repo.record_plan(engine, make_plan([]), recorded_at="2026-03-01T09:00:00+00:00")
        repo.record_recommendation(engine, make_record(), plan_id=plan_id)
        with Session(engine) as session:
            row = session.scalars(select(RecommendationRecord)).one()
        assert row.plan_id == plan_id

    def test_unknown_plan_reference_raises_database_error(self, engine):
        with pytest.raises(DatabaseError, match="does not exist"):
            repo.record_recommendation(engine, make_record(), plan_id=999)

    @pytest.mark.parametrize("bad", [0, -1, True, "7"])
    def test_invalid_plan_ids_rejected(self, engine, bad):
        with pytest.raises(DataValidationError, match="plan_id"):
            repo.record_recommendation(engine, make_record(), plan_id=bad)

    def test_malformed_record_writes_nothing(self, engine):
        broken = make_record()
        del broken["priority_score"]
        with pytest.raises(DataValidationError):
            repo.record_recommendation(engine, broken)
        assert repo.count_recommendations(engine) == 0

    def test_history_is_append_only_per_id(self, engine):
        repo.record_recommendation(engine, make_record(status=RECOMMENDATION_PENDING))
        repo.record_recommendation(engine, make_record(status=RECOMMENDATION_REJECTED))
        listed = repo.list_recommendations(engine)
        assert len(listed) == 2
        assert [r["status"] for r in listed] == [
            RECOMMENDATION_PENDING,
            RECOMMENDATION_REJECTED,
        ]
        assert repo.get_latest_recommendation(engine, "R1")["status"] == RECOMMENDATION_REJECTED


# --- review event validation and recording ------------------------------------------


class TestReviewEvents:
    def test_event_round_trip_is_lossless(self, engine):
        event = make_event(comment="Solid evidence.")
        row_id = repo.record_review_event(engine, event)
        assert isinstance(row_id, int)
        assert repo.list_review_events(engine) == [event]

    def test_filter_by_recommendation_id(self, engine):
        repo.record_review_event(engine, make_event())
        other = make_event(
            recommendation_id="R2", decision="REJECT",
            previous_status=RECOMMENDATION_PENDING, new_status=RECOMMENDATION_REJECTED,
        )
        repo.record_review_event(engine, other)
        assert repo.list_review_events(engine, recommendation_id="R2") == [other]
        assert len(repo.list_review_events(engine)) == 2

    def test_identical_duplicate_events_are_kept_as_log_entries(self, engine):
        repo.record_review_event(engine, make_event())
        repo.record_review_event(engine, make_event())
        assert len(repo.list_review_events(engine)) == 2

    def test_insertion_order_is_deterministic(self, engine):
        chain = [
            make_event(decision="REQUEST_CHANGES", new_status=RECOMMENDATION_CHANGES_REQUESTED),
            make_event(
                decision="RESUBMIT",
                previous_status=RECOMMENDATION_CHANGES_REQUESTED,
                new_status=RECOMMENDATION_PENDING,
            ),
            make_event(),
        ]
        for event in chain:
            repo.record_review_event(engine, event)
        assert repo.list_review_events(engine) == chain
        assert repo.list_review_events(engine) == repo.list_review_events(engine)

    @pytest.mark.parametrize(
        "mutation",
        [
            lambda e: e.pop("comment"),
            lambda e: e.update(extra_key=1),
            lambda e: e.update(event_type="other_event"),
            lambda e: e.update(decision="MAYBE"),
            lambda e: e.update(previous_status=RECOMMENDATION_APPROVED),  # terminal + APPROVE
            lambda e: e.update(new_status=RECOMMENDATION_REJECTED),  # mismatch vs table
            lambda e: e.update(occurred_at="not-a-timestamp"),
            lambda e: e.update(reviewer_id=""),
            lambda e: e.update(reviewer_id=7),
            lambda e: e.update(previous_status="SOMEDAY"),
            lambda e: e.update(comment=42),
            lambda e: e.update(recommendation_id=""),
        ],
    )
    def test_malformed_events_fail_closed_without_writes(self, engine, mutation):
        event = make_event()
        mutation(event)
        with pytest.raises(DataValidationError):
            repo.record_review_event(engine, event)
        assert repo.count_review_events(engine) == 0

    def test_terminal_state_cannot_take_decisions(self, engine):
        for terminal, decision in (
            (RECOMMENDATION_APPROVED, "APPROVE"),
            (RECOMMENDATION_APPROVED, "REJECT"),
            (RECOMMENDATION_REJECTED, "APPROVE"),
            (RECOMMENDATION_REJECTED, "RESUBMIT"),
        ):
            with pytest.raises(DataValidationError, match="illegal review transition"):
                repo.validate_review_event(
                    make_event(previous_status=terminal, decision=decision,
                               new_status=RECOMMENDATION_APPROVED)
                )

    def test_z_suffix_timestamp_normalized_on_storage(self, engine):
        repo.record_review_event(engine, make_event(occurred_at="2026-03-01T10:00:00Z"))
        stored = repo.list_review_events(engine)[0]
        assert stored["occurred_at"] == "2026-03-01T10:00:00+00:00"

    def test_validate_review_event_non_dict_input(self):
        with pytest.raises(DataValidationError):
            repo.validate_review_event(["not", "a", "dict"])

    def test_event_shape_matches_phase_6_constant(self):
        assert set(make_event()) == set(EXPECTED_REVIEW_EVENT_KEYS)

    def test_phase6_constructed_events_pass_storage_validation(self):
        event = create_review_event(
            recommendation_id="R1",
            reviewer_id="ops-user",
            previous_status=RECOMMENDATION_PENDING,
            new_status=RECOMMENDATION_APPROVED,
            decision="APPROVE",
        )
        repo.validate_review_event(event)
        assert set(event) == set(EXPECTED_REVIEW_EVENT_KEYS)


# --- record_review bridge -------------------------------------------------------------


class TestRecordReviewBridge:
    def test_pair_persists_atomically(self, engine):
        reviewed = make_record(status=RECOMMENDATION_APPROVED)
        event = make_event()
        rec_id, evt_id = repo.record_review(engine, reviewed, event)
        assert rec_id >= 1 and evt_id >= 1
        assert repo.count_recommendations(engine) == 1
        assert repo.count_review_events(engine) == 1
        assert repo.get_latest_recommendation(engine, "R1")["status"] == RECOMMENDATION_APPROVED

    def test_real_phase6_output_pair_accepted(self, engine):
        updated, event = review_recommendation(
            make_record(), decision="APPROVE", reviewer_id="ops-user"
        )
        repo.record_review(engine, updated, event)
        assert repo.get_latest_recommendation(engine, "R1") == updated
        assert repo.list_review_events(engine) == [event]

    def test_identity_mismatch_rejected_atomically(self, engine):
        with pytest.raises(DataValidationError, match="targets"):
            repo.record_review(
                engine,
                make_record(recommendation_id="R9", status=RECOMMENDATION_APPROVED),
                make_event(),
            )
        assert repo.count_recommendations(engine) == 0
        assert repo.count_review_events(engine) == 0

    def test_status_mismatch_rejected(self, engine):
        with pytest.raises(DataValidationError, match="new_status"):
            repo.record_review(engine, make_record(status=RECOMMENDATION_REJECTED), make_event())

    def test_full_revision_loop_chain(self, engine):
        pending = make_record()
        changes = make_event(
            decision="REQUEST_CHANGES", new_status=RECOMMENDATION_CHANGES_REQUESTED,
            occurred_at="2026-03-01T10:00:00+00:00",
        )
        repo.record_review(engine, make_record(status=RECOMMENDATION_CHANGES_REQUESTED), changes)
        resub = make_event(
            decision="RESUBMIT",
            previous_status=RECOMMENDATION_CHANGES_REQUESTED,
            new_status=RECOMMENDATION_PENDING,
            reviewer_id="analyst-2",
            comment="Revised with fresh data.",
            occurred_at="2026-03-02T10:00:00+00:00",
        )
        repo.record_review(engine, pending, resub)
        approved_evt = make_event(occurred_at="2026-03-03T10:00:00+00:00")
        repo.record_review(engine, make_record(status=RECOMMENDATION_APPROVED), approved_evt)

        events = repo.list_review_events(engine)
        assert [e["decision"] for e in events] == ["REQUEST_CHANGES", "RESUBMIT", "APPROVE"]
        assert repo.get_latest_recommendation(engine, "R1")["status"] == RECOMMENDATION_APPROVED
        assert repo.count_recommendations(engine) == 3

    def test_inputs_never_mutated_by_bridge(self, engine):
        reviewed = make_record(status=RECOMMENDATION_APPROVED)
        event = make_event()
        snap_rec, snap_evt = copy.deepcopy(reviewed), copy.deepcopy(event)
        repo.record_review(engine, reviewed, event)
        assert reviewed == snap_rec and event == snap_evt


# --- validation strictness --------------------------------------------------------


class TestValidationStrictness:
    @pytest.mark.parametrize(
        "mutation",
        [
            lambda p: p.pop("summary"),
            lambda p: p.update(extra_field=True),
            lambda p: p.update(type="something_else"),
            lambda p: p.update(schema_version="2.0"),
            lambda p: p.update(parameters=["not", "a", "dict"]),
            lambda p: p["source"].pop("group_count"),
            lambda p: p["source"].update(anomaly_count=-1),
            lambda p: p["source"].update(cited_evidence_ids=[1, 2]),
            lambda p: p["source"].update(investigation_status=99),
            lambda p: p["summary"].update(unexpected=0),
            lambda p: p.update(recommendations={"R1": {}}),
        ],
    )
    def test_malformed_plans_rejected(self, mutation):
        plan = make_plan()
        mutation(plan)
        with pytest.raises(DataValidationError):
            repo.validate_plan(plan)

    def test_rec_inside_plan_must_pass_shared_validator(self):
        gated_off = make_record(requires_human_review=False)
        with pytest.raises(DataValidationError, match="requires_human_review"):
            repo.validate_plan(make_plan([gated_off]))

    def test_unknown_status_inside_plan_rejected(self):
        with pytest.raises(DataValidationError, match="status"):
            repo.validate_plan(make_plan([make_record(status="QUEUED")]))

    def test_validate_plan_non_dict_input(self):
        with pytest.raises(DataValidationError):
            repo.validate_plan("plan")

    def test_storage_vocabulary_blocks_foreign_statuses(self, engine):
        with pytest.raises(DataValidationError):
            repo.record_plan(engine, make_plan([make_record(status="EXECUTED")]))
        assert repo.count_plans(engine) == 0

    def test_known_status_vocabulary_matches_phase_6(self):
        assert KNOWN_REVIEW_STATUSES == {
            RECOMMENDATION_PENDING,
            RECOMMENDATION_APPROVED,
            RECOMMENDATION_REJECTED,
            RECOMMENDATION_CHANGES_REQUESTED,
        }


# --- append-only guarantees and determinism ------------------------------------------


class TestAppendOnlyGuarantees:
    def test_repository_exports_no_mutation_functions(self):
        forbidden = ("update_", "delete_", "drop_", "truncate_", "alter_", "execute_")
        offenders = [name for name in dir(repo) if name.startswith(forbidden)]
        assert offenders == []

    def test_returned_dicts_are_detached_copies(self, engine):
        repo.record_plan(engine, make_plan(), recorded_at="2026-03-01T09:00:00+00:00")
        first = repo.get_latest_recommendation(engine, "R1")
        first["title"] = "tampered"
        second = repo.get_latest_recommendation(engine, "R1")
        assert second["title"] == "Investigate HIGH anomaly"

    def test_deterministic_reconstruction_across_databases(self, tmp_path):
        digests = []
        for run in range(2):
            eng = connect(f"sqlite:///{(tmp_path / f'run{run}.db').as_posix()}")
            init_db(eng)
            try:
                plan = make_plan([make_record(), make_record(recommendation_id="R2")])
                repo.record_plan(eng, plan, recorded_at="2026-03-01T09:00:00+00:00")
                repo.record_review_event(eng, make_event(comment="ok"))
                payload = json.dumps(
                    {
                        "recs": sorted(repo.list_recommendations(eng), key=lambda r: r["recommendation_id"]),
                        "events": repo.list_review_events(eng),
                    },
                    sort_keys=True,
                )
                digests.append(payload)
            finally:
                eng.dispose()
        assert digests[0] == digests[1]


# --- end-to-end integration with phases 5 and 6 ---------------------------------------


_DEMO_CACHE: dict[str, object] = {}


def demo_pack() -> dict:
    if "pack" not in _DEMO_CACHE:
        df = pd.read_csv(PROJECT_ROOT / "data" / "demo" / "demo_operational_data.csv")
        _DEMO_CACHE["pack"] = build_investigation_context(df)
    return copy.deepcopy(_DEMO_CACHE["pack"])


class TestEndToEndPipeline:
    def test_generated_demo_plan_persists_completely(self, engine):
        plan = generate_recommendations(demo_pack())
        snapshot = copy.deepcopy(plan)
        repo.record_plan(engine, plan, recorded_at="2026-03-01T09:00:00+00:00")

        assert repo.count_plans(engine) == 1
        assert repo.count_recommendations(engine) == plan["summary"]["total_count"]
        for record in plan["recommendations"]:
            assert repo.get_latest_recommendation(engine, record["recommendation_id"]) == record
        assert plan == snapshot

    def test_generate_then_review_then_persist_full_chain(self, engine):
        plan = generate_recommendations(demo_pack())
        target = plan["recommendations"][0]
        repo.record_plan(engine, plan, recorded_at="2026-03-01T09:00:00+00:00")

        updated, event = review_recommendation(
            target,
            decision="APPROVE",
            reviewer_id="ops-manager",
            comment="Matches the capacity report.",
            occurred_at="2026-03-02T12:00:00+00:00",
        )
        repo.record_review(engine, updated, event)

        latest = repo.get_latest_recommendation(engine, target["recommendation_id"])
        assert latest == updated
        assert latest["status"] == RECOMMENDATION_APPROVED
        stored_event = repo.list_review_events(engine)[0]
        assert stored_event == event
        assert stored_event["reviewer_id"] == "ops-manager"

    def test_changes_requested_flow_via_public_helpers(self, engine):
        plan = generate_recommendations(demo_pack(), max_recommendations=1)
        target = plan["recommendations"][0]
        changed, chg_evt = request_changes(target, reviewer_id="qa", comment="Needs unit context.")
        repo.record_review(engine, changed, chg_evt)
        resubmitted, resub_evt = resubmit_recommendation(changed, reviewer_id="analyst")
        repo.record_review(engine, resubmitted, resub_evt)
        approved, appr_evt = approve_recommendation(resubmitted, reviewer_id="ops-manager")
        repo.record_review(engine, approved, appr_evt)

        decisions = [e["decision"] for e in repo.list_review_events(engine)]
        assert decisions == ["REQUEST_CHANGES", "RESUBMIT", "APPROVE"]
        assert repo.count_recommendations(engine) == 3
