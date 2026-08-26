"""Tests for the Phase 6 human review & approval workflow.

Covers ``agent.review_service`` against the approved design: mandatory
human gate on every Phase 5 recommendation, explicit fail-closed state
machine (approval, rejection, change requests, resubmission), structured
auditable review events, strict preservation of recommendation identity
and content, deterministic outputs under pinned timestamps, reviewer and
record validation, and the deliberate absence of any execution,
persistence, or auto-approval path.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import agent.review_service as review_service_module
from agent.recommendation_service import generate_recommendations
from agent.review_service import (
    approve_recommendation,
    create_review_event,
    reject_recommendation,
    request_changes,
    resubmit_recommendation,
    review_recommendation,
    validate_review_transition,
    validate_reviewable_recommendation,
)
from agent.schemas import (
    EXPECTED_REVIEW_EVENT_KEYS,
    RECOMMENDATION_CHANGES_REQUESTED,
    REVIEW_DECISIONS,
    REVIEW_EVENT_TYPE,
    RECOMMENDATION_KEYS,
    VALID_REVIEW_TRANSITIONS,
)
from core.constants import (
    RECOMMENDATION_APPROVED,
    RECOMMENDATION_PENDING,
    RECOMMENDATION_REJECTED,
)
from core.exceptions import DataValidationError
from services.data_service import load_dataset

PINNED_TIME = "2026-01-15T10:30:00+00:00"

# --- Shared fixtures ------------------------------------------------------------------


def make_rec(**over: object) -> dict:
    """A structurally valid Phase 5 recommendation record."""
    base: dict[str, object] = {
        "recommendation_id": "R1",
        "priority": "HIGH",
        "priority_score": 70.0,
        "action_type": "cost_variance_review",
        "title": "Review cost variance drivers for revenue",
        "description": (
            "HIGH dataset revenue signal observed on 2025-01-05 deviating "
            "+25.00% versus expected; proposed for human review; no "
            "automated action is taken."
        ),
        "scope": "dataset",
        "target_entity": None,
        "target_metric": "revenue",
        "date_window": {"start": "2025-01-05", "end": "2025-01-05"},
        "source_factors": ["monetary"],
        "source_anomaly_indices": [0],
        "source_group_ids": [1],
        "evidence_ids": ["E36", "E82"],
        "evidence_strength": 0.7,
        "requires_human_review": True,
        "status": RECOMMENDATION_PENDING,
        "problem_statement": "Revenue showed an anomalous spike on 2025-01-05.",
        "why_it_matters": "Unplanned revenue variance may indicate data quality issues.",
        "likely_drivers": ["monetary", "seasonal"],
        "expected_benefit": "Investigating this could prevent future revenue misreporting.",
    }
    base.update(over)
    return base


@pytest.fixture(scope="session")
def demo_plan() -> dict:
    """One real Phase 5 plan built from the bundled demo dataset."""
    df = load_dataset("demo_operational_data.csv")
    return generate_recommendations(df)


# --- A. Initial state -------------------------------------------------------------------


class TestInitialState:
    def test_generated_recommendations_are_pending(self, demo_plan):
        for rec in demo_plan["recommendations"]:
            assert rec["status"] == RECOMMENDATION_PENDING == "PENDING"

    def test_generated_recommendations_keep_gate_raised(self, demo_plan):
        for rec in demo_plan["recommendations"]:
            assert rec["requires_human_review"] is True

    def test_real_phase5_record_passes_validation(self, demo_plan):
        rec = demo_plan["recommendations"][0]
        validate_reviewable_recommendation(rec)

    def test_core_phase1_constants_are_reused_not_redefined(self):
        assert RECOMMENDATION_PENDING == "PENDING"
        assert RECOMMENDATION_APPROVED == "APPROVED"
        assert RECOMMENDATION_REJECTED == "REJECTED"


# --- B. Approval --------------------------------------------------------------------------


class TestApproval:
    def make_updated_and_event(self, **kwargs):
        rec = make_rec()
        return approve_recommendation(rec, reviewer_id="rev-7", occurred_at=PINNED_TIME, **kwargs)

    def test_pending_can_be_approved(self):
        updated, _ = self.make_updated_and_event()
        assert updated["status"] == RECOMMENDATION_APPROVED

    def test_recommendation_id_unchanged(self):
        updated, _ = self.make_updated_and_event()
        assert updated["recommendation_id"] == "R1"

    def test_content_other_than_status_unchanged(self):
        original = make_rec()
        updated, _ = self.make_updated_and_event()
        for key in RECOMMENDATION_KEYS - {"status"}:
            assert updated[key] == original[key], key

    def test_reviewer_recorded_in_event(self):
        _, event = self.make_updated_and_event()
        assert event["reviewer_id"] == "rev-7"

    def test_event_created_with_lifecycle_fields(self):
        _, event = self.make_updated_and_event()
        assert event["event_type"] == REVIEW_EVENT_TYPE
        assert event["previous_status"] == RECOMMENDATION_PENDING
        assert event["new_status"] == RECOMMENDATION_APPROVED
        assert event["decision"] == "APPROVE"
        assert event["occurred_at"] == PINNED_TIME

    def test_approval_comment_preserved(self):
        updated, event = self.make_updated_and_event(comment="Cost driver confirmed.")
        assert updated["status"] == RECOMMENDATION_APPROVED
        assert event["comment"] == "Cost driver confirmed."

    def test_input_record_never_mutated(self):
        rec = make_rec()
        snapshot = copy.deepcopy(rec)
        approve_recommendation(rec, reviewer_id="rev-7", occurred_at=PINNED_TIME)
        assert rec == snapshot

    def test_approved_still_satisfies_public_contract(self):
        updated, _ = self.make_updated_and_event()
        assert set(updated) == set(RECOMMENDATION_KEYS)


# --- C. Rejection ------------------------------------------------------------------------------


class TestRejection:
    def make_updated_and_event(self, **kwargs):
        rec = make_rec()
        return reject_recommendation(rec, reviewer_id="rev-9", occurred_at=PINNED_TIME, **kwargs)

    def test_pending_can_be_rejected(self):
        updated, _ = self.make_updated_and_event()
        assert updated["status"] == RECOMMENDATION_REJECTED

    def test_identity_and_content_preserved(self):
        original = make_rec()
        updated, _ = self.make_updated_and_event()
        assert updated["recommendation_id"] == original["recommendation_id"]
        for key in RECOMMENDATION_KEYS - {"status"}:
            assert updated[key] == original[key], key

    def test_reviewer_recorded(self):
        _, event = self.make_updated_and_event()
        assert event["reviewer_id"] == "rev-9"

    def test_reason_preserved_when_supplied(self):
        _, event = self.make_updated_and_event(comment="Duplicate of R2.")
        assert event["comment"] == "Duplicate of R2."

    def test_comment_optional_by_design(self):
        _, event = self.make_updated_and_event()
        assert event["comment"] is None

    def test_event_records_transition(self):
        _, event = self.make_updated_and_event()
        assert event["previous_status"] == RECOMMENDATION_PENDING
        assert event["new_status"] == RECOMMENDATION_REJECTED
        assert event["decision"] == "REJECT"

    def test_input_record_never_mutated(self):
        rec = make_rec()
        snapshot = copy.deepcopy(rec)
        reject_recommendation(rec, reviewer_id="rev-9", occurred_at=PINNED_TIME)
        assert rec == snapshot


# --- D. State machine transitions -----------------------------------------------------------------


class TestStateMachine:
    @pytest.mark.parametrize(
        ("current", "decision", "expected"),
        [
            (RECOMMENDATION_PENDING, "APPROVE", RECOMMENDATION_APPROVED),
            (RECOMMENDATION_PENDING, "REJECT", RECOMMENDATION_REJECTED),
            (RECOMMENDATION_PENDING, "REQUEST_CHANGES", RECOMMENDATION_CHANGES_REQUESTED),
            (RECOMMENDATION_CHANGES_REQUESTED, "RESUBMIT", RECOMMENDATION_PENDING),
        ],
    )
    def test_valid_transitions(self, current, decision, expected):
        assert validate_review_transition(current, decision) == expected

    @pytest.mark.parametrize(
        ("current", "decision"),
        [
            (RECOMMENDATION_PENDING, "EXECUTE"),
            (RECOMMENDATION_PENDING, "AUTO_APPROVE"),
            (RECOMMENDATION_PENDING, "approve"),
            (RECOMMENDATION_APPROVED, "APPROVE"),
            (RECOMMENDATION_APPROVED, "REJECT"),
            (RECOMMENDATION_APPROVED, "REQUEST_CHANGES"),
            (RECOMMENDATION_APPROVED, "RESUBMIT"),
            (RECOMMENDATION_REJECTED, "APPROVE"),
            (RECOMMENDATION_REJECTED, "REJECT"),
            (RECOMMENDATION_REJECTED, "RESUBMIT"),
            (RECOMMENDATION_CHANGES_REQUESTED, "APPROVE"),
            (RECOMMENDATION_CHANGES_REQUESTED, "REJECT"),
            (RECOMMENDATION_CHANGES_REQUESTED, "REQUEST_CHANGES"),
            ("EXECUTED", "APPROVE"),
            (42, "APPROVE"),
        ],
    )
    def test_invalid_transitions_fail_closed(self, current, decision):
        with pytest.raises(DataValidationError):
            validate_review_transition(current, decision)

    def test_executed_is_absent_from_the_state_machine(self):
        targets = set(VALID_REVIEW_TRANSITIONS.values())
        assert "EXECUTED" not in targets
        assert "EXECUTE" not in REVIEW_DECISIONS

    def test_operations_on_terminal_states_raise(self):
        for status in (RECOMMENDATION_APPROVED, RECOMMENDATION_REJECTED):
            rec = make_rec(status=status)
            with pytest.raises(DataValidationError):
                approve_recommendation(rec, reviewer_id="rev-1", occurred_at=PINNED_TIME)
            with pytest.raises(DataValidationError):
                reject_recommendation(rec, reviewer_id="rev-1", occurred_at=PINNED_TIME)

    def test_double_approval_does_not_create_second_event(self):
        rec = make_rec()
        approved, first_event = approve_recommendation(rec, reviewer_id="r", occurred_at=PINNED_TIME)
        with pytest.raises(DataValidationError):
            approve_recommendation(approved, reviewer_id="r", occurred_at=PINNED_TIME)
        assert first_event["decision"] == "APPROVE"


# --- E. Change request / resubmission loop -------------------------------------------------------------


class TestChangeRequestLoop:
    def test_pending_moves_to_changes_requested(self):
        updated, event = request_changes(
            make_rec(), reviewer_id="rev-3", comment="Needs region split.", occurred_at=PINNED_TIME
        )
        assert updated["status"] == RECOMMENDATION_CHANGES_REQUESTED
        assert event["decision"] == "REQUEST_CHANGES"
        assert event["new_status"] == RECOMMENDATION_CHANGES_REQUESTED

    def test_resubmit_returns_to_pending_for_fresh_review(self):
        pending_again, event = resubmit_recommendation(
            make_rec(status=RECOMMENDATION_CHANGES_REQUESTED),
            reviewer_id="analyst-2",
            occurred_at=PINNED_TIME,
        )
        assert pending_again["status"] == RECOMMENDATION_PENDING
        assert event["previous_status"] == RECOMMENDATION_CHANGES_REQUESTED
        assert event["new_status"] == RECOMMENDATION_PENDING
        assert event["decision"] == "RESUBMIT"

    def test_resubmit_only_allowed_from_changes_requested(self):
        with pytest.raises(DataValidationError):
            resubmit_recommendation(make_rec(), reviewer_id="analyst-2")

    def test_full_revision_loop_then_approval(self):
        rec = make_rec()
        chain: list[dict] = []
        rec, e1 = request_changes(rec, reviewer_id="rev-a", occurred_at=PINNED_TIME)
        chain.append(e1)
        rec, e2 = resubmit_recommendation(rec, reviewer_id="ops-b", occurred_at=PINNED_TIME)
        chain.append(e2)
        rec, e3 = approve_recommendation(rec, reviewer_id="mgr-c", occurred_at=PINNED_TIME)
        chain.append(e3)
        assert rec["status"] == RECOMMENDATION_APPROVED
        assert [(e["previous_status"], e["new_status"]) for e in chain] == [
            (RECOMMENDATION_PENDING, RECOMMENDATION_CHANGES_REQUESTED),
            (RECOMMENDATION_CHANGES_REQUESTED, RECOMMENDATION_PENDING),
            (RECOMMENDATION_PENDING, RECOMMENDATION_APPROVED),
        ]
        assert len({e["reviewer_id"] for e in chain}) == 3


# --- F. Reviewer validation --------------------------------------------------------------------------------


class TestReviewerValidation:
    @pytest.mark.parametrize("bad_reviewer", [None, "", "   ", 42, ["team"]])
    def test_bad_reviewer_ids_rejected(self, bad_reviewer):
        with pytest.raises(DataValidationError):
            review_recommendation(
                make_rec(), decision="APPROVE", reviewer_id=bad_reviewer, occurred_at=PINNED_TIME
            )

    def test_bad_reviewer_rejected_via_wrappers(self):
        for wrapper in (approve_recommendation, reject_recommendation, request_changes):
            with pytest.raises(DataValidationError):
                wrapper(make_rec(), reviewer_id="", occurred_at=PINNED_TIME)

    def test_reviewer_id_whitespace_normalized(self):
        _, event = approve_recommendation(
            make_rec(), reviewer_id="  rev-5  ", occurred_at=PINNED_TIME
        )
        assert event["reviewer_id"] == "rev-5"


# --- G. Recommendation validation ------------------------------------------------------------------------------


class TestRecommendationValidation:
    @pytest.mark.parametrize("bad_rec", [None, [], "R1", 7])
    def test_non_dict_records_rejected(self, bad_rec):
        with pytest.raises(DataValidationError):
            validate_reviewable_recommendation(bad_rec)

    def test_missing_required_field_rejected(self):
        rec = make_rec()
        del rec["priority_score"]
        with pytest.raises(DataValidationError, match="missing"):
            validate_reviewable_recommendation(rec)

    def test_extra_metadata_key_pollution_rejected(self):
        rec = make_rec(_internal_note="helper scratchpad")
        with pytest.raises(DataValidationError, match="unexpected"):
            validate_reviewable_recommendation(rec)

    @pytest.mark.parametrize("bad_id", [None, "", "   ", 12, []])
    def test_missing_or_invalid_recommendation_id_rejected(self, bad_id):
        with pytest.raises(DataValidationError):
            validate_reviewable_recommendation(make_rec(recommendation_id=bad_id))

    @pytest.mark.parametrize(
        "bad_status", ["APPROVE", "EXECUTED", "approved", "", None, 3]
    )
    def test_unknown_statuses_rejected(self, bad_status):
        with pytest.raises(DataValidationError):
            validate_reviewable_recommendation(make_rec(status=bad_status))

    @pytest.mark.parametrize("gate_value", [False, None, "yes", 1])
    def test_lowered_or_missing_gate_blocks_review(self, gate_value):
        rec = make_rec(requires_human_review=gate_value)
        with pytest.raises(DataValidationError, match="not reviewable"):
            review_recommendation(
                rec, decision="APPROVE", reviewer_id="rev-1", occurred_at=PINNED_TIME
            )


# --- H. Review event contract ------------------------------------------------------------------------------------


class TestReviewEventContract:
    def test_event_has_exact_keys(self):
        event = create_review_event(
            recommendation_id="R1",
            reviewer_id="rev-1",
            previous_status=RECOMMENDATION_PENDING,
            new_status=RECOMMENDATION_APPROVED,
            decision="APPROVE",
            comment=None,
            occurred_at=PINNED_TIME,
        )
        assert set(event) == set(EXPECTED_REVIEW_EVENT_KEYS)
        assert event["event_type"] == "recommendation_review"

    def test_event_never_carries_recommendation_content(self):
        event = create_review_event(
            recommendation_id="R1",
            reviewer_id="rev-1",
            previous_status=RECOMMENDATION_PENDING,
            new_status=RECOMMENDATION_APPROVED,
            decision="APPROVE",
            occurred_at=PINNED_TIME,
        )
        assert set(event).isdisjoint(RECOMMENDATION_KEYS - {"recommendation_id"})

    def test_event_creator_validates_inputs(self):
        with pytest.raises(DataValidationError):
            create_review_event(
                recommendation_id="R1",
                reviewer_id=None,
                previous_status=RECOMMENDATION_PENDING,
                new_status=RECOMMENDATION_APPROVED,
                decision="APPROVE",
            )
        with pytest.raises(DataValidationError):
            create_review_event(
                recommendation_id="",
                reviewer_id="rev-1",
                previous_status=RECOMMENDATION_PENDING,
                new_status=RECOMMENDATION_APPROVED,
                decision="APPROVE",
            )
        with pytest.raises(DataValidationError):
            create_review_event(
                recommendation_id="R1",
                reviewer_id="rev-1",
                previous_status=RECOMMENDATION_PENDING,
                new_status=RECOMMENDATION_APPROVED,
                decision="SIGN_OFF",
            )

    @pytest.mark.parametrize("bad_comment", [42, ["why"], {"text": "x"}])
    def test_non_string_comment_rejected(self, bad_comment):
        with pytest.raises(DataValidationError):
            review_recommendation(
                make_rec(),
                decision="REJECT",
                reviewer_id="rev-1",
                comment=bad_comment,
                occurred_at=PINNED_TIME,
            )

    def test_pinned_timestamp_normalized_verbatim(self):
        _, event = approve_recommendation(make_rec(), reviewer_id="r", occurred_at=PINNED_TIME)
        assert event["occurred_at"] == PINNED_TIME

    def test_date_only_timestamp_normalized(self):
        _, event = approve_recommendation(make_rec(), reviewer_id="r", occurred_at="2026-02-01")
        assert event["occurred_at"] == "2026-02-01T00:00:00"

    def test_omitted_timestamp_defaults_to_utc_now_iso(self):
        _, event = approve_recommendation(make_rec(), reviewer_id="r")
        parsed = datetime.fromisoformat(event["occurred_at"])
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0

    @pytest.mark.parametrize("bad_time", ["yesterday", "2026-13-40T99:00:00", 17, True])
    def test_unparseable_timestamps_rejected(self, bad_time):
        with pytest.raises(DataValidationError):
            approve_recommendation(make_rec(), reviewer_id="r", occurred_at=bad_time)


# --- I. Determinism ------------------------------------------------------------------------------------------------


class TestDeterminism:
    def test_identical_decisions_identical_outputs(self):
        first = approve_recommendation(make_rec(), reviewer_id="rev-1", comment="ok", occurred_at=PINNED_TIME)
        second = approve_recommendation(make_rec(), reviewer_id="rev-1", comment="ok", occurred_at=PINNED_TIME)
        assert json.dumps(first[0], sort_keys=True) == json.dumps(second[0], sort_keys=True)
        assert json.dumps(first[1], sort_keys=True) == json.dumps(second[1], sort_keys=True)

    def test_decision_without_comment_differs_from_one_with_comment(self):
        plain = approve_recommendation(make_rec(), reviewer_id="r", occurred_at=PINNED_TIME)[1]
        annotated = approve_recommendation(
            make_rec(), reviewer_id="r", comment="because", occurred_at=PINNED_TIME
        )[1]
        assert plain["comment"] is None and annotated["comment"] == "because"
        annotated.pop("comment"), plain.pop("comment")
        assert plain == annotated

    def test_different_decisions_produce_different_new_statuses(self):
        results = {
            review_recommendation(make_rec(), decision=d, reviewer_id="r", occurred_at=PINNED_TIME)[0]["status"]
            for d in ("APPROVE", "REJECT", "REQUEST_CHANGES")
        }
        assert results == {RECOMMENDATION_APPROVED, RECOMMENDATION_REJECTED, RECOMMENDATION_CHANGES_REQUESTED}


# --- J. Human gate / no execution --------------------------------------------------------------------------------------


class TestHumanGateAndNoExecution:
    def test_validation_alone_never_advances_state(self):
        rec = make_rec()
        validate_reviewable_recommendation(rec)
        validate_review_transition(RECOMMENDATION_PENDING, "APPROVE")
        assert rec["status"] == RECOMMENDATION_PENDING

    def test_missing_decision_kwarg_refuses_to_run(self):
        with pytest.raises(TypeError):
            review_recommendation(make_rec(), reviewer_id="r")

    def test_execute_is_not_a_decision(self):
        with pytest.raises(DataValidationError):
            review_recommendation(
                make_rec(), decision="EXECUTE", reviewer_id="r", occurred_at=PINNED_TIME
            )

    def test_no_execution_functionality_exists(self):
        public_callables = [
            name
            for name in dir(review_service_module)
            if not name.startswith("_") and callable(getattr(review_service_module, name))
        ]
        assert not any("execute" in name.lower() for name in public_callables)

    def test_events_are_json_safe_plain_dicts(self):
        _, event = reject_recommendation(make_rec(), reviewer_id="r", occurred_at=PINNED_TIME)
        encoded = json.dumps(event, sort_keys=True)
        assert "recommendation_review" in encoded


# --- K. Integration with the real Phase 5 plan -------------------------------------------------------------------------


class TestPhase5Integration:
    def test_real_recommendation_round_trip(self, demo_plan):
        plan_snapshot = copy.deepcopy(demo_plan)
        target = demo_plan["recommendations"][0]
        approved, event = approve_recommendation(
            target, reviewer_id="ops-manager", comment="Matches known issue.", occurred_at=PINNED_TIME
        )
        # The plan itself is untouched by reviewing one of its records.
        assert demo_plan == plan_snapshot
        # Only the status moved; identity and analysis are byte-identical.
        for key in RECOMMENDATION_KEYS - {"status"}:
            assert approved[key] == target[key], key
        assert approved["status"] == RECOMMENDATION_APPROVED
        assert event["recommendation_id"] == target["recommendation_id"]
        assert set(event) == set(EXPECTED_REVIEW_EVENT_KEYS)

    def test_every_demo_recommendation_is_reviewable(self, demo_plan):
        for rec in demo_plan["recommendations"]:
            validate_reviewable_recommendation(rec)

    def test_reject_two_merge_partners_independently(self, demo_plan):
        pair = demo_plan["recommendations"][:2]
        approved, _ = approve_recommendation(pair[0], reviewer_id="a", occurred_at=PINNED_TIME)
        rejected, _ = reject_recommendation(pair[1], reviewer_id="b", occurred_at=PINNED_TIME)
        assert approved["status"] != rejected["status"]
        assert approved["recommendation_id"] != rejected["recommendation_id"]
