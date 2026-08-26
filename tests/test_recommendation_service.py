"""Tests for the Phase 5 deterministic recommendation engine.

Covers ``agent.recommendation_service.generate_recommendations`` and its
pure helpers against the approved design: exact plan contract, closed
action vocabulary, additive explainable scoring with no trend term,
deterministic deduplication/ranking/id assignment, structural validation
of every input shape, provenance-only use of Phase 4B investigation
results, immutability, JSON safety, and end-to-end golden values on both
the bundled demo dataset and minimal synthetic packs. No LLM, no
randomness, no network.
"""

from __future__ import annotations

import copy
import itertools
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent import recommendation_playbooks as pb
from agent.evidence import build_investigation_context
from agent.recommendation_service import (
    compute_evidence_strength,
    compute_priority,
    deduplicate_recommendations,
    generate_recommendations,
    match_playbook_candidates,
)
from agent.schemas import (
    ACTION_TYPES,
    ANOMALY_ENTRY_FIELDS,
    CONTEXT_SCHEMA_VERSION,
    DATE_WINDOW_KEYS,
    EXPECTED_PLAN_KEYS,
    EXPECTED_SOURCE_KEYS,
    EXPECTED_SUMMARY_KEYS,
    GROUP_ENTRY_FIELDS,
    INVESTIGATION_CONTEXT_TYPE,
    NARRATIVE_INSTRUCTIONS,
    PRIORITY_CRITICAL_MIN_SCORE,
    PRIORITY_HIGH_MIN_SCORE,
    PRIORITY_MEDIUM_MIN_SCORE,
    RECOMMENDATION_KEYS,
    RECOMMENDATION_PLAN_TYPE,
    RECOMMENDATION_SCHEMA_VERSION,
)
from core.constants import RECOMMENDATION_PENDING
from core.exceptions import DataValidationError

# --- Shared fixtures -------------------------------------------------------------

_DEMO_CACHE: dict[str, object] = {}


def demo_pack() -> dict:
    """Build the demo evidence pack once per session."""
    if "pack" not in _DEMO_CACHE:
        df = pd.read_csv(Path(__file__).resolve().parents[1] / "data" / "demo" / "demo_operational_data.csv")
        _DEMO_CACHE["pack"] = build_investigation_context(df)
        _DEMO_CACHE["df"] = df
    return copy.deepcopy(_DEMO_CACHE["pack"])


@pytest.fixture(scope="module")
def plan_fixture() -> dict:
    """One canonical demo plan reused by contract assertions."""
    return generate_recommendations(demo_pack())


# --- Synthetic record builders ------------------------------------------------------


def make_anomaly(**over: object) -> dict:
    base: dict[str, object] = {
        "type": "daily_spike",
        "scope": "daily",
        "metric": "revenue",
        "entity": None,
        "date": "2025-01-05",
        "value": 125.0,
        "expected_value": 100.0,
        "deviation_pct": 25.0,
        "score": 80.0,
        "severity": "HIGH",
        "rule": "zscore_rolling",
        "details": {"z": 3.2},
    }
    base.update(over)
    return base


def make_factor(label: str = "monetary", strength: float = 0.8) -> dict:
    return {
        "factor": label,
        "direction": "increase",
        "strength": strength,
        "evidence": f"{label} z=3.0 on 2025-01-05",
    }


def make_localization(
    verdict: str = "localized",
    dimension: str = "region",
    contributors: list | None = None,
) -> dict:
    return {
        "dimension": dimension,
        "verdict": verdict,
        "contributors": (
            [{"entity": "North", "share_pct": 90.0}] if contributors is None else contributors
        ),
    }


def make_insight(**over: object) -> dict:
    base: dict[str, object] = {
        "type": "insight",
        "anomaly_index": 0,
        "scope": "daily",
        "metric": "revenue",
        "entity": None,
        "date": "2025-01-05",
        "severity": "HIGH",
        "headline": "Daily revenue spike.",
        "factors": [make_factor()],
        "localization": None,
        "peer_profile": None,
        "trend": {"direction": "flat", "change_pct": 0.1},
        "correlations": [],
        "related_anomaly_indices": [],
    }
    base.update(over)
    return base


def make_entity_anomaly(**over: object) -> dict:
    base = make_anomaly(
        type="entity_outlier",
        scope="region",
        entity="North",
        date=None,
        deviation_pct=-30.0,
        value=700.0,
        expected_value=1000.0,
        rule="peer_median_ratio",
    )
    base.update(over)
    return base


def make_entity_insight(profile: str | None = "volume_driven", ratio: float | None = 2.5, **over: object) -> dict:
    peer_profile = None
    if profile is not None:
        peer_profile = {
            "profile": profile,
            "ratios": {
                "metric_vs_peer_median": ratio,
                "units_vs_peer_median": 1.5,
                "cost_vs_peer_median": 1.1,
            },
            "gaps_pct": {
                "average_lead_time_days": 20.0,
                "profit_margin_pct_points": -3.0,
            },
        }
    base = make_insight(scope="region", entity="North", date=None, factors=[], localization=None, peer_profile=peer_profile)
    base.update(over)
    return base


def make_group(group_id: int, members: list[int], *, severity: str = "HIGH", max_score: float = 80.0) -> dict:
    return {
        "group_id": group_id,
        "severity": severity,
        "max_score": max_score,
        "member_indices": list(members),
        "member_count": len(members),
        "shared_metrics": ["revenue"],
        "shared_entities": [],
        "headline": f"group {group_id}",
        "start_date": "2025-01-05",
        "end_date": "2025-01-06",
    }


def tiny_pack(
    *,
    anomalies: list[dict] | None = None,
    insights: list[dict] | None = None,
    groups: list[dict] | None = None,
    include_evidence: bool = True,
) -> dict:
    """Minimal structurally valid pack carrying exactly the given records."""
    anomalies = list(anomalies or [])
    insights = list(insights or [])
    groups = list(groups or [])
    if groups and not anomalies:
        raise AssertionError("groups require anomalies in tiny packs")
    pack: dict[str, object] = {
        "type": INVESTIGATION_CONTEXT_TYPE,
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "parameters": {"sensitivity": "medium", "metrics": ["revenue"], "focus": {}},
        "context": {
            "dataset_name": "synthetic",
            "period": {"start": "2025-01-01", "end": "2025-01-10"},
        },
        "kpis": {},
        "period_comparison": {},
        "top_performers": {},
        "bottom_performers": {},
        "narrative_instructions": copy.deepcopy(NARRATIVE_INSTRUCTIONS),
        "anomalies": copy.deepcopy(anomalies),
        "insights": copy.deepcopy(insights),
        "groups": {"groups": copy.deepcopy(groups)},
        "evidence_index": {"E1": {"kind": "kpi", "field": "total_revenue", "value": 1000.0, "id": "E1"}},
    }
    ids = itertools.count(2)
    if include_evidence:
        for position, anomaly in enumerate(pack["anomalies"]):
            evidence_id = f"E{next(ids)}"
            entry: dict[str, object] = {"kind": "anomaly", "anomaly_index": position, "id": evidence_id}
            entry.update({field: anomaly[field] for field in ANOMALY_ENTRY_FIELDS})
            pack["evidence_index"][evidence_id] = entry  # type: ignore[index]
        for group in pack["groups"]["groups"]:  # type: ignore[union-attr]
            evidence_id = f"E{next(ids)}"
            entry = {"kind": "group", "group_id": group["group_id"], "id": evidence_id}
            entry.update({field: group[field] for field in GROUP_ENTRY_FIELDS})
            pack["evidence_index"][evidence_id] = entry  # type: ignore[index]
    return pack


def singleton_groups(anomalies: list[dict]) -> list[dict]:
    return [
        make_group(
            index + 1,
            [index],
            severity=str(anomaly.get("severity", "HIGH")),
            max_score=float(anomaly.get("score", 80.0)),
        )
        for index, anomaly in enumerate(anomalies)
    ]


def make_candidate(**over: object) -> dict:
    base: dict[str, object] = {
        "action_type": "cost_variance_review",
        "target_entity": None,
        "target_metric": "cost",
        "scope": "dataset",
        "severity": "HIGH",
        "detector_score": 80.0,
        "deviation_pct": 12.0,
        "origin": "factor",
        "source_factors": ["cost"],
        "primary_factor_strength": 0.8,
        "localization_verdict": "",
        "source_anomaly_indices": [0],
        "source_group_ids": [],
        "evidence_ids": ["E2"],
        "date_window": {"start": "2025-01-01", "end": "2025-01-02"},
        "corroboration_count": 1,
        "concentration_flag": False,
        "priority_score": 55.0,
    }
    base.update(over)
    return base


def make_result(pack: dict, *, status: str = "complete", cited: str = "E36", uncited: str = "E999") -> dict:
    """A valid Phase 4B result citing one caller-chosen evidence id.

    ``cited`` should exist in the pack under test; ``uncited`` never does,
    exercising the known-id filter.
    """
    narrative = {
        "executive_summary": "Summary.",
        "key_findings": [{"claim": "c1", "evidence_ids": [cited]}],
        "operational_interpretation": [{"claim": "c2", "evidence_ids": [uncited]}],
    }
    hypotheses = [
        {
            "hypothesis": "h1",
            "factor": "monetary",
            "confidence": "medium",
            "evidence_ids": [cited],
        }
    ]
    citations = [{"evidence_id": cited, "claim": "supports c1"}]
    grounding_report = {
        "valid": True,
        "citation_errors": [],
        "numeric_errors": [],
        "causation_errors": [],
        "schema_errors": [],
        "unsupported_claims": [],
    }
    return {
        "status": status,
        "evidence_pack": copy.deepcopy(pack),
        "narrative": narrative,
        "hypotheses": hypotheses,
        "citations": citations,
        "grounding_report": grounding_report,
    }


# --- Playbook registry -----------------------------------------------------------------


class TestPlaybookRegistry:
    def test_factor_action_map_is_exact(self):
        assert pb.FACTOR_ACTION_MAP == {
            "volume": "demand_capacity_review",
            "monetary": "revenue_operations_review",
            "cost": "cost_variance_review",
            "supply": "supplier_escalation_review",
            "price_margin": "pricing_margin_review",
            "unattributed": "manual_investigation",
        }

    def test_profile_action_map_is_exact(self):
        assert pb.PROFILE_ACTION_MAP == {
            "volume_driven": "demand_capacity_review",
            "efficiency_driven": "fulfillment_bottleneck_review",
            "mixed": "entity_performance_review",
        }

    def test_unknown_factor_fallback_constant(self):
        assert pb.UNKNOWN_FACTOR_FALLBACK_ACTION == "manual_investigation"

    def test_factor_actions_stay_in_closed_vocabulary(self):
        assert set(pb.FACTOR_ACTION_MAP.values()) <= set(ACTION_TYPES)

    def test_profile_actions_stay_in_closed_vocabulary(self):
        assert set(pb.PROFILE_ACTION_MAP.values()) <= set(ACTION_TYPES)

    def test_priority_base_points_match_severity_ladder(self):
        assert pb.PRIORITY_BASE_POINTS == {"CRITICAL": 40.0, "HIGH": 30.0, "MEDIUM": 20.0, "LOW": 10.0}

    def test_evidence_strength_weights_sum_to_one(self):
        total = (
            pb.EVIDENCE_STRENGTH_FACTOR_WEIGHT
            + pb.EVIDENCE_STRENGTH_SCORE_WEIGHT
            + pb.EVIDENCE_STRENGTH_CORROBORATION_WEIGHT
            + pb.EVIDENCE_STRENGTH_CONCENTRATION_WEIGHT
        )
        assert total == pytest.approx(1.0)

    def test_concentration_points_values(self):
        assert pb.CONCENTRATION_BONUS_POINTS == {"localized": 10.0, "concentrated": 6.0}
        assert pb.PEER_CONCENTRATION_BONUS_POINTS == 10.0

    def test_metric_labels_and_passthrough(self):
        assert pb.METRIC_LABELS == {
            "units_sold": "unit sales",
            "revenue": "revenue",
            "cost": "cost",
            "lead_time_days": "lead times",
        }
        assert pb.metric_label("units_sold") == "unit sales"
        assert pb.metric_label("widgets") == "widgets"

    def test_action_phrases_cover_every_action(self):
        assert set(pb.ACTION_PHRASES) == set(ACTION_TYPES)
        for action, phrase in pb.ACTION_PHRASES.items():
            assert phrase == phrase.lower()
            assert "_" not in phrase
        assert pb.action_phrase("demand_capacity_review") == "review demand and capacity planning"
        assert pb.action_phrase("future_action_kind") == "future action kind"

    def test_scoring_constants_match_approved_design(self):
        assert pb.FACTOR_STRENGTH_BONUS_WEIGHT == 25.0
        assert pb.CORROBORATION_BONUS_WEIGHT == 15.0
        assert pb.MAX_CORROBORATION_STEPS == 3
        assert pb.PEER_RATIO_CONCENTRATION_THRESHOLD == 2.0
        assert pb.MAX_CANDIDATES_PER_INSIGHT == 2


# --- Schema constants --------------------------------------------------------------------


class TestSchemaConstants:
    def test_plan_identity_constants(self):
        assert RECOMMENDATION_PLAN_TYPE == "recommendation_plan"
        assert RECOMMENDATION_SCHEMA_VERSION == "1.0"

    def test_expected_plan_keys(self):
        assert EXPECTED_PLAN_KEYS == frozenset(
            {"type", "schema_version", "parameters", "source", "recommendations", "summary"}
        )
        assert EXPECTED_SOURCE_KEYS == frozenset(
            {"anomaly_count", "group_count", "investigation_status", "cited_evidence_ids"}
        )
        assert EXPECTED_SUMMARY_KEYS == frozenset({"total_count", "by_priority", "by_action_type"})

    def test_recommendation_record_has_exactly_21_fields(self):
        assert len(RECOMMENDATION_KEYS) == 21
        assert "requires_human_review" in RECOMMENDATION_KEYS
        assert "status" in RECOMMENDATION_KEYS
        assert "priority_score" in RECOMMENDATION_KEYS
        assert "problem_statement" in RECOMMENDATION_KEYS
        assert "why_it_matters" in RECOMMENDATION_KEYS
        assert "likely_drivers" in RECOMMENDATION_KEYS
        assert "expected_benefit" in RECOMMENDATION_KEYS

    def test_action_vocabulary_has_exactly_8_actions(self):
        assert len(ACTION_TYPES) == 8
        assert "manual_investigation" in ACTION_TYPES

    def test_priority_band_edges_are_ordered(self):
        assert (
            PRIORITY_CRITICAL_MIN_SCORE > PRIORITY_HIGH_MIN_SCORE > PRIORITY_MEDIUM_MIN_SCORE > 0
        )

    def test_date_window_keys(self):
        assert DATE_WINDOW_KEYS == frozenset({"start", "end"})


# --- Input resolution -------------------------------------------------------------------------


class TestInputResolution:
    def test_dataframe_and_pack_inputs_agree(self):
        demo_pack()
        cached = _DEMO_CACHE
        from_df = generate_recommendations(cached["df"])
        from_pack = generate_recommendations(demo_pack())
        assert json.dumps(from_df, sort_keys=True) == json.dumps(from_pack, sort_keys=True)

    @pytest.mark.parametrize("bad_input", [None, [], ["x"], "text", 42])
    def test_unsupported_primary_types_rejected(self, bad_input):
        with pytest.raises(DataValidationError):
            generate_recommendations(bad_input)

    def test_result_as_primary_input_uses_embedded_pack(self):
        pack = tiny_pack(
            anomalies=[make_anomaly()],
            insights=[make_insight()],
            groups=singleton_groups([make_anomaly()]),
        )
        result = make_result(pack)
        from_result = generate_recommendations(result)
        from_pack = generate_recommendations(pack, investigation=result)
        assert json.dumps(from_result, sort_keys=True) == json.dumps(from_pack, sort_keys=True)

    def test_result_plus_investigation_parameter_conflict_rejected(self):
        pack = tiny_pack(
            anomalies=[make_anomaly()],
            insights=[make_insight()],
            groups=singleton_groups([make_anomaly()]),
        )
        result = make_result(pack)
        with pytest.raises(DataValidationError):
            generate_recommendations(result, investigation=result)

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda r: r.pop("grounding_report"),
            lambda r: r.update({"unexpected": True}),
            lambda r: r.update({"status": "finished"}),
            lambda r: r.update({"narrative": []}),
            lambda r: r["narrative"].update({"key_findings": {}}),
            lambda r: r["narrative"].update({"key_findings": ["not-a-dict"]}),
            lambda r: r["narrative"].update({"key_findings": [{"claim": "c"}]}),
            lambda r: r["narrative"].update({"key_findings": [{"claim": "c", "evidence_ids": "E36"}]}),
            lambda r: r["narrative"].update({"key_findings": [{"claim": "c", "evidence_ids": [1]}]}),
            lambda r: r.update({"hypotheses": {}}),
            lambda r: r.update({"hypotheses": [{"hypothesis": "h", "factor": "f", "confidence": "low", "evidence_ids": [None]}]}),
            lambda r: r.update({"citations": {}}),
            lambda r: r.update({"citations": [{"evidence_id": 7, "claim": "c"}]}),
        ],
    )
    def test_malformed_investigation_parameter_rejected(self, mutate):
        pack = tiny_pack(
            anomalies=[make_anomaly()],
            insights=[make_insight()],
            groups=singleton_groups([make_anomaly()]),
        )
        result = make_result(pack)
        mutate(result)
        with pytest.raises(DataValidationError):
            generate_recommendations(pack, investigation=result)


# --- max_recommendations handling --------------------------------------------------------------


class TestMaxRecommendations:
    def test_zero_yields_empty_but_valid_plan(self):
        pack = tiny_pack(
            anomalies=[make_anomaly()],
            insights=[make_insight()],
            groups=singleton_groups([make_anomaly()]),
        )
        plan = generate_recommendations(pack, max_recommendations=0)
        assert plan["recommendations"] == []
        assert plan["summary"]["total_count"] == 0
        assert plan["summary"]["by_priority"] == {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        assert plan["summary"]["by_action_type"] == {}

    def test_positive_cap_keeps_top_prefix(self):
        # Distinct metrics keep the dedup keys apart so nothing merges.
        pack = tiny_pack(
            anomalies=[
                make_anomaly(metric="revenue", date="2025-01-05", score=90.0),
                make_anomaly(metric="units_sold", date="2025-01-06", score=85.0),
                make_anomaly(metric="cost", date="2025-01-07", score=70.0),
            ],
            insights=[
                make_insight(metric="revenue", date="2025-01-05"),
                make_insight(metric="units_sold", date="2025-01-06"),
                make_insight(metric="cost", date="2025-01-07"),
            ],
            groups=singleton_groups(
                [
                    make_anomaly(metric="revenue", date="2025-01-05", score=90.0),
                    make_anomaly(metric="units_sold", date="2025-01-06", score=85.0),
                    make_anomaly(metric="cost", date="2025-01-07", score=70.0),
                ]
            ),
        )
        full = generate_recommendations(pack)["recommendations"]
        capped = generate_recommendations(pack, max_recommendations=2)["recommendations"]
        assert len(full) == 3 and len(capped) == 2
        assert capped == full[:2]
        assert [r["recommendation_id"] for r in capped] == ["R1", "R2"]

    @pytest.mark.parametrize("bad_limit", [-1, True, False, 2.5, "3"])
    def test_invalid_limits_rejected(self, bad_limit):
        with pytest.raises(DataValidationError):
            generate_recommendations(tiny_pack(), max_recommendations=bad_limit)


# --- Structural validation ------------------------------------------------------------------------


def build_valid_pair() -> tuple[list, list, list]:
    anomaly = make_anomaly()
    insight = make_insight(localization=make_localization())
    return ([anomaly], [insight], singleton_groups([anomaly]))


class TestStructuralValidation:
    def test_length_mismatch_rejected(self):
        anomalies, insights, groups = build_valid_pair()
        with pytest.raises(DataValidationError):
            generate_recommendations(
                tiny_pack(anomalies=anomalies, insights=insights[:0], groups=groups)
            )

    def test_non_dict_insight_rejected(self):
        anomalies, insights, groups = build_valid_pair()
        with pytest.raises(DataValidationError):
            generate_recommendations(
                tiny_pack(anomalies=anomalies, insights=["nope"], groups=groups)
            )

    def test_missing_required_insight_field_rejected(self):
        for field in ("scope", "metric", "severity", "factors"):
            anomalies, insights, groups = build_valid_pair()
            del insights[0][field]
            with pytest.raises(DataValidationError):
                generate_recommendations(
                    tiny_pack(anomalies=anomalies, insights=insights, groups=groups)
                )

    def test_unsupported_severity_rejected(self):
        anomalies, insights, groups = build_valid_pair()
        anomalies[0]["severity"] = "EXTREME"
        insights[0]["severity"] = "EXTREME"
        with pytest.raises(DataValidationError):
            generate_recommendations(
                tiny_pack(anomalies=anomalies, insights=insights, groups=groups)
            )

    def test_boolean_score_rejected(self):
        anomalies, insights, groups = build_valid_pair()
        anomalies[0]["score"] = True
        with pytest.raises(DataValidationError):
            generate_recommendations(
                tiny_pack(anomalies=anomalies, insights=insights, groups=groups)
            )

    def test_nan_score_rejected(self):
        anomalies, insights, groups = build_valid_pair()
        anomalies[0]["score"] = float("nan")
        with pytest.raises(DataValidationError):
            generate_recommendations(
                tiny_pack(anomalies=anomalies, insights=insights, groups=groups)
            )

    @pytest.mark.parametrize("bad_deviation", ["25", float("inf"), float("-inf"), None])
    def test_bad_deviation_rejected(self, bad_deviation):
        anomalies, insights, groups = build_valid_pair()
        anomalies[0]["deviation_pct"] = bad_deviation
        with pytest.raises(DataValidationError):
            generate_recommendations(
                tiny_pack(anomalies=anomalies, insights=insights, groups=groups)
            )

    def test_factors_not_a_list_rejected(self):
        anomalies, insights, groups = build_valid_pair()
        insights[0]["factors"] = {}
        with pytest.raises(DataValidationError):
            generate_recommendations(
                tiny_pack(anomalies=anomalies, insights=insights, groups=groups)
            )

    def test_daily_empty_factors_rejected(self):
        anomalies, insights, groups = build_valid_pair()
        insights[0]["factors"] = []
        with pytest.raises(DataValidationError):
            generate_recommendations(
                tiny_pack(anomalies=anomalies, insights=insights, groups=groups)
            )

    def test_factor_entry_not_dict_rejected(self):
        anomalies, insights, groups = build_valid_pair()
        insights[0]["factors"] = ["cost"]
        with pytest.raises(DataValidationError):
            generate_recommendations(
                tiny_pack(anomalies=anomalies, insights=insights, groups=groups)
            )

    def test_factor_label_not_string_rejected(self):
        anomalies, insights, groups = build_valid_pair()
        insights[0]["factors"] = [make_factor(label=7)]
        with pytest.raises(DataValidationError):
            generate_recommendations(
                tiny_pack(anomalies=anomalies, insights=insights, groups=groups)
            )

    def test_factor_strength_not_numeric_rejected(self):
        anomalies, insights, groups = build_valid_pair()
        insights[0]["factors"] = [make_factor(strength="high")]
        with pytest.raises(DataValidationError):
            generate_recommendations(
                tiny_pack(anomalies=anomalies, insights=insights, groups=groups)
            )

    def test_factor_strength_non_finite_rejected(self):
        anomalies, insights, groups = build_valid_pair()
        insights[0]["factors"] = [make_factor(strength=float("inf"))]
        with pytest.raises(DataValidationError):
            generate_recommendations(
                tiny_pack(anomalies=anomalies, insights=insights, groups=groups)
            )

    def test_groups_container_not_list_rejected(self):
        anomalies, insights, groups = build_valid_pair()
        pack = tiny_pack(anomalies=anomalies, insights=insights, groups=groups)
        pack["groups"] = {"groups": {}}
        with pytest.raises(DataValidationError):
            generate_recommendations(pack)

    def test_missing_anomaly_evidence_mapping_rejected(self):
        anomalies, insights, groups = build_valid_pair()
        pack = tiny_pack(
            anomalies=anomalies, insights=insights, groups=groups, include_evidence=False
        )
        with pytest.raises(DataValidationError):
            generate_recommendations(pack)

    def test_out_of_range_strength_clamped_not_rejected(self):
        anomaly = make_anomaly()
        insight = make_insight(factors=[make_factor(strength=1.5)], localization=make_localization())
        pack = tiny_pack(
            anomalies=[anomaly], insights=[insight], groups=singleton_groups([anomaly])
        )
        plan = generate_recommendations(pack)
        rec = plan["recommendations"][0]
        assert rec["priority_score"] == pytest.approx(65.0)
        assert rec["evidence_strength"] == pytest.approx(0.8)


# --- Matcher semantics: daily scope ---------------------------------------------------------------


class TestMatcherDailyScope:
    def test_localized_targets_lead_contributor(self):
        insight = make_insight(localization=make_localization(verdict="localized"))
        candidates = match_playbook_candidates(insight, make_anomaly())
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate["action_type"] == "revenue_operations_review"
        assert candidate["target_entity"] == "North"
        assert candidate["scope"] == "region"
        assert candidate["date_window"] == {"start": "2025-01-05", "end": "2025-01-05"}
        assert candidate["source_factors"] == ["monetary"]

    def test_concentrated_targets_lead_contributor(self):
        insight = make_insight(localization=make_localization(verdict="concentrated"))
        candidate = match_playbook_candidates(insight, make_anomaly())[0]
        assert candidate["target_entity"] == "North"

    def test_distributed_stays_dataset_wide(self):
        insight = make_insight(localization=make_localization(verdict="distributed"))
        candidate = match_playbook_candidates(insight, make_anomaly())[0]
        assert candidate["target_entity"] is None
        assert candidate["scope"] == "dataset"
        assert candidate["date_window"] == {"start": "2025-01-05", "end": "2025-01-05"}

    def test_missing_localization_block_dataset_wide(self):
        candidate = match_playbook_candidates(make_insight(), make_anomaly())[0]
        assert candidate["target_entity"] is None
        assert candidate["scope"] == "dataset"

    def test_primary_factor_is_first_not_strongest(self):
        factors = [
            make_factor(label="cost", strength=0.2),
            make_factor(label="volume", strength=0.95),
        ]
        candidate = match_playbook_candidates(make_insight(factors=factors), make_anomaly())[0]
        assert candidate["action_type"] == "cost_variance_review"
        assert candidate["source_factors"] == ["cost"]
        assert candidate["primary_factor_strength"] == pytest.approx(0.2)

    def test_each_known_factor_maps_to_its_action(self):
        for label, action in pb.FACTOR_ACTION_MAP.items():
            insight = make_insight(factors=[make_factor(label=label)])
            candidate = match_playbook_candidates(insight, make_anomaly())[0]
            assert candidate["action_type"] == action

    def test_unknown_future_factor_falls_back_gracefully(self):
        insight = make_insight(factors=[make_factor(label="weather_pressure")])
        candidate = match_playbook_candidates(insight, make_anomaly())[0]
        assert candidate["action_type"] == "manual_investigation"
        assert candidate["source_factors"] == ["weather_pressure"]

    def test_corroboration_counts_union_with_related_indices(self):
        insight = make_insight(related_anomaly_indices=[3, 4, 3])
        candidate = match_playbook_candidates(insight, make_anomaly())[0]
        assert candidate["corroboration_count"] == 3

    def test_detector_score_clamped_into_unit_interval_fraction(self):
        candidate = match_playbook_candidates(make_insight(), make_anomaly(score=250.0))[0]
        assert candidate["detector_score"] == 100.0
        candidate = match_playbook_candidates(make_insight(), make_anomaly(score=-20.0))[0]
        assert candidate["detector_score"] == 0.0


# --- Matcher semantics: entity scope ---------------------------------------------------------------


class TestMatcherEntityScope:
    def entity_candidates(self, profile: str | None = "volume_driven", ratio: float | None = None):
        insight = make_entity_insight(profile=profile, ratio=ratio)
        return match_playbook_candidates(insight, make_entity_anomaly())

    def test_volume_driven_maps_and_targets_entity(self):
        candidate = self.entity_candidates("volume_driven", ratio=2.5)[0]
        assert candidate["action_type"] == "demand_capacity_review"
        assert candidate["target_entity"] == "North"
        assert candidate["source_factors"] == ["volume_driven"]
        assert candidate["date_window"] is None
        assert candidate["scope"] == "region"

    def test_efficiency_driven_maps(self):
        candidate = self.entity_candidates("efficiency_driven")[0]
        assert candidate["action_type"] == "fulfillment_bottleneck_review"

    def test_mixed_maps(self):
        candidate = self.entity_candidates("mixed")[0]
        assert candidate["action_type"] == "entity_performance_review"

    def test_unknown_profile_falls_back(self):
        candidate = self.entity_candidates("seasonality_driven")[0]
        assert candidate["action_type"] == "manual_investigation"
        assert candidate["source_factors"] == ["seasonality_driven"]
        assert candidate["target_entity"] == "North"

    def test_missing_peer_profile_targets_entity_without_factors(self):
        candidate = self.entity_candidates(profile=None)[0]
        assert candidate["action_type"] == "manual_investigation"
        assert candidate["source_factors"] == []
        assert candidate["target_entity"] == "North"

    def test_high_peer_ratio_flags_concentration(self):
        candidate = self.entity_candidates(ratio=2.5)[0]
        assert candidate["concentration_flag"] is True
        assert "2.50x" in candidate["profile_note"]

    @pytest.mark.parametrize("low_ratio", [None, 1.9])
    def test_low_or_missing_ratio_no_concentration(self, low_ratio):
        candidate = self.entity_candidates(ratio=low_ratio)[0]
        assert candidate["concentration_flag"] is False

    def test_product_scope_supported(self):
        insight = make_entity_insight(profile="mixed", ratio=1.0)
        insight["scope"] = "product"
        candidate = match_playbook_candidates(insight, make_entity_anomaly(scope="product"))[0]
        assert candidate["scope"] == "product"


# --- compute_priority -------------------------------------------------------------------------------


class TestComputePriority:
    def zero_bonus(self, severity):
        return {
            "severity": severity,
            "primary_factor_strength": 0.0,
            "corroboration_count": 1,
            "concentration_flag": False,
        }

    def test_base_points_only_land_below_medium_band(self):
        assert compute_priority(self.zero_bonus("CRITICAL")) == ("LOW", 40.0)
        assert compute_priority(self.zero_bonus("HIGH")) == ("LOW", 30.0)
        assert compute_priority(self.zero_bonus("MEDIUM")) == ("LOW", 20.0)
        assert compute_priority(self.zero_bonus("LOW")) == ("LOW", 10.0)

    def test_full_stack_critical_hits_ninety(self):
        candidate = {
            "severity": "CRITICAL",
            "primary_factor_strength": 1.0,
            "corroboration_count": 4,
            "concentration_flag": True,
            "localization_verdict": "localized",
        }
        assert compute_priority(candidate) == ("CRITICAL", 90.0)

    def test_concentrated_verdict_scores_six_points_less(self):
        candidate = {
            "severity": "CRITICAL",
            "primary_factor_strength": 1.0,
            "corroboration_count": 4,
            "concentration_flag": True,
            "localization_verdict": "concentrated",
        }
        assert compute_priority(candidate) == ("CRITICAL", 86.0)

    def test_band_edge_at_85_is_critical(self):
        candidate = {
            "severity": "CRITICAL",
            "primary_factor_strength": 0.8,
            "corroboration_count": 4,
            "concentration_flag": True,
            "localization_verdict": "localized",
        }
        assert compute_priority(candidate) == ("CRITICAL", 85.0)

    def test_just_below_85_is_high(self):
        candidate = {
            "severity": "CRITICAL",
            "primary_factor_strength": 0.79,
            "corroboration_count": 4,
            "concentration_flag": True,
            "localization_verdict": "localized",
        }
        label, score = compute_priority(candidate)
        assert label == "HIGH"
        assert score == pytest.approx(84.75)

    def test_band_edge_at_70_is_high(self):
        candidate = {
            "severity": "HIGH",
            "primary_factor_strength": 1.0,
            "corroboration_count": 4,
            "concentration_flag": False,
        }
        assert compute_priority(candidate) == ("HIGH", 70.0)

    def test_just_below_70_is_medium(self):
        candidate = {
            "severity": "HIGH",
            "primary_factor_strength": 0.98,
            "corroboration_count": 4,
            "concentration_flag": False,
        }
        assert compute_priority(candidate) == ("MEDIUM", 69.5)

    def test_band_edge_at_50_is_medium(self):
        candidate = {
            "severity": "CRITICAL",
            "primary_factor_strength": 0.4,
            "corroboration_count": 1,
            "concentration_flag": False,
        }
        assert compute_priority(candidate) == ("MEDIUM", 50.0)

    def test_just_below_50_is_low(self):
        candidate = {
            "severity": "CRITICAL",
            "primary_factor_strength": 0.39,
            "corroboration_count": 1,
            "concentration_flag": False,
        }
        assert compute_priority(candidate) == ("LOW", 49.75)

    def test_corroboration_steps_table(self):
        for count, expected in [(1, 30.0), (2, 35.0), (3, 40.0), (4, 45.0), (9, 45.0)]:
            candidate = {
                "severity": "HIGH",
                "primary_factor_strength": 0.0,
                "corroboration_count": count,
                "concentration_flag": False,
            }
            assert compute_priority(candidate)[1] == pytest.approx(expected)

    def test_strength_clamped_both_directions(self):
        high = {
            "severity": "HIGH",
            "primary_factor_strength": 1.5,
            "corroboration_count": 1,
            "concentration_flag": False,
        }
        assert compute_priority(high)[1] == pytest.approx(55.0)
        low = dict(high, primary_factor_strength=-0.7)
        assert compute_priority(low)[1] == pytest.approx(30.0)

    def test_unknown_severity_defaults_to_low_base(self):
        candidate = {
            "severity": "WEIRD",
            "primary_factor_strength": 0.0,
            "corroboration_count": 1,
            "concentration_flag": False,
        }
        assert compute_priority(candidate) == ("LOW", 10.0)

    def test_empty_candidate_degrades_safely(self):
        assert compute_priority({}) == ("LOW", 10.0)

    def test_returns_label_and_float(self):
        result = compute_priority(self.zero_bonus("HIGH"))
        assert isinstance(result, tuple)
        assert isinstance(result[0], str)
        assert isinstance(result[1], float)


# --- compute_evidence_strength --------------------------------------------------------------------------


class TestComputeEvidenceStrength:
    def test_zero_support_is_zero(self):
        candidate = {
            "severity": "LOW",
            "detector_score": 0.0,
            "primary_factor_strength": 0.0,
            "corroboration_count": 1,
            "concentration_flag": False,
        }
        assert compute_evidence_strength(candidate) == 0.0

    def test_known_blend_demo_index_zero_shape(self):
        candidate = {
            "severity": "CRITICAL",
            "detector_score": 96.5,
            "primary_factor_strength": 0.52,
            "corroboration_count": 1,
            "concentration_flag": True,
        }
        assert compute_evidence_strength(candidate) == pytest.approx(0.6)

    def test_maximum_support_is_one(self):
        candidate = {
            "severity": "CRITICAL",
            "detector_score": 100.0,
            "primary_factor_strength": 1.0,
            "corroboration_count": 9,
            "concentration_flag": True,
        }
        assert compute_evidence_strength(candidate) == pytest.approx(1.0)

    def test_extreme_detector_score_clamped(self):
        candidate = {
            "severity": "LOW",
            "detector_score": -500.0,
            "primary_factor_strength": 0.0,
            "corroboration_count": 1,
            "concentration_flag": False,
        }
        assert compute_evidence_strength(candidate) == 0.0

    def test_mid_case_exact_blend(self):
        candidate = {
            "severity": "HIGH",
            "detector_score": 80.0,
            "primary_factor_strength": 0.5,
            "corroboration_count": 1,
            "concentration_flag": False,
        }
        assert compute_evidence_strength(candidate) == pytest.approx(0.45)


# --- deduplicate_recommendations ---------------------------------------------------------------------------


class TestDeduplication:
    def test_same_key_merges_sorted_unions(self):
        first = make_candidate(source_factors=["cost", "supply"], source_anomaly_indices=[2], evidence_ids=["E10"])
        second = make_candidate(source_factors=["cost"], source_anomaly_indices=[1], source_group_ids=[3], evidence_ids=["E2", "E10"])
        merged = deduplicate_recommendations([first, second])
        assert len(merged) == 1
        combined = merged[0]
        assert combined["source_factors"] == ["cost", "supply"]
        assert combined["source_anomaly_indices"] == [1, 2]
        assert combined["source_group_ids"] == [3]
        assert combined["evidence_ids"] == ["E2", "E10"]

    def test_distinct_keys_keep_first_occurrence_order(self):
        a = make_candidate(target_metric="cost")
        b = make_candidate(target_entity="North")
        c = make_candidate(action_type="manual_investigation")
        merged = deduplicate_recommendations([a, b, c])
        assert [m["target_metric"] for m in merged] == ["cost", "cost", "cost"]
        assert merged[1]["target_entity"] == "North"
        assert merged[2]["action_type"] == "manual_investigation"

    def test_leader_highest_score_supplies_presentation(self):
        weak = make_candidate(priority_score=40.0, deviation_pct=5.0)
        strong = make_candidate(priority_score=70.0, deviation_pct=44.0)
        merged = deduplicate_recommendations([weak, strong])
        assert merged[0]["deviation_pct"] == 44.0

    def test_tie_keeps_first_member_presentation(self):
        first = make_candidate(deviation_pct=11.0)
        second = make_candidate(deviation_pct=22.0)
        merged = deduplicate_recommendations([first, second])
        assert merged[0]["deviation_pct"] == 11.0

    def test_date_windows_span_all_dated_members(self):
        spanned = deduplicate_recommendations(
            [
                make_candidate(),
                make_candidate(date_window={"start": "2025-01-05", "end": "2025-01-06"}),
                make_candidate(date_window=None),
            ]
        )
        assert spanned[0]["date_window"] == {"start": "2025-01-01", "end": "2025-01-06"}
        undated = deduplicate_recommendations([make_candidate(date_window=None)])
        assert undated[0]["date_window"] is None

    def test_cross_member_corroboration_counts_distinct_anomalies(self):
        merged = deduplicate_recommendations(
            [
                make_candidate(source_anomaly_indices=[1]),
                make_candidate(source_anomaly_indices=[2]),
            ]
        )
        assert merged[0]["corroboration_count"] == 2

    def test_inputs_never_mutated(self):
        first = make_candidate()
        second = make_candidate(source_anomaly_indices=[5])
        snapshot = json.dumps([first, second], sort_keys=True)
        deduplicate_recommendations([first, second])
        assert json.dumps([first, second], sort_keys=True) == snapshot

    def test_empty_input_gives_empty_output(self):
        assert deduplicate_recommendations([]) == []


# --- Plan contract on the demo dataset ------------------------------------------------------------------------


class TestDemoPlanContract:
    def test_exact_top_level_contract(self, plan_fixture):
        assert set(plan_fixture) == set(EXPECTED_PLAN_KEYS)
        assert plan_fixture["type"] == RECOMMENDATION_PLAN_TYPE
        assert plan_fixture["schema_version"] == RECOMMENDATION_SCHEMA_VERSION

    def test_parameters_echoed_from_pack(self, plan_fixture):
        pack = demo_pack()
        assert plan_fixture["parameters"] == pack["parameters"]

    def test_source_block_values(self, plan_fixture):
        source = plan_fixture["source"]
        assert set(source) == set(EXPECTED_SOURCE_KEYS)
        assert source["anomaly_count"] == 46
        assert source["group_count"] == 46
        assert source["investigation_status"] is None
        assert source["cited_evidence_ids"] == []

    def test_summary_block_contract(self, plan_fixture):
        summary = plan_fixture["summary"]
        recommendations = plan_fixture["recommendations"]
        assert set(summary) == set(EXPECTED_SUMMARY_KEYS)
        assert summary["total_count"] == len(recommendations)
        assert list(summary["by_priority"]) == ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        assert sum(summary["by_priority"].values()) == summary["total_count"]
        actions = summary["by_action_type"]
        assert list(actions) == sorted(actions)
        assert sum(actions.values()) == summary["total_count"]
        assert set(actions) <= set(ACTION_TYPES)

    def test_every_record_matches_public_schema(self, plan_fixture):
        for position, rec in enumerate(plan_fixture["recommendations"], start=1):
            assert set(rec) == set(RECOMMENDATION_KEYS)
            assert rec["recommendation_id"] == f"R{position}"
            assert rec["requires_human_review"] is True
            assert rec["status"] == RECOMMENDATION_PENDING
            assert rec["action_type"] in ACTION_TYPES
            assert rec["target_metric"] in {"units_sold", "revenue", "cost", "lead_time_days"}
            assert rec["scope"] in {"daily", "region", "product", "dataset"}
            assert 0.0 <= rec["priority_score"] <= 100.0
            assert 0.0 <= rec["evidence_strength"] <= 1.0

    def test_priority_bands_consistent_with_scores(self, plan_fixture):
        for rec in plan_fixture["recommendations"]:
            score = rec["priority_score"]
            if score >= PRIORITY_CRITICAL_MIN_SCORE:
                assert rec["priority"] == "CRITICAL"
            elif score >= PRIORITY_HIGH_MIN_SCORE:
                assert rec["priority"] == "HIGH"
            elif score >= PRIORITY_MEDIUM_MIN_SCORE:
                assert rec["priority"] == "MEDIUM"
            else:
                assert rec["priority"] == "LOW"

    def test_scores_rank_monotonically(self, plan_fixture):
        scores = [rec["priority_score"] for rec in plan_fixture["recommendations"]]
        assert scores == sorted(scores, reverse=True)

    def test_provenance_references_resolve_inside_the_pack(self, plan_fixture):
        pack = demo_pack()
        index = pack["evidence_index"]
        known_group_ids = {g["group_id"] for g in pack["groups"]["groups"]}
        for rec in plan_fixture["recommendations"]:
            indices = rec["source_anomaly_indices"]
            assert indices and all(isinstance(i, int) and 0 <= i < len(pack["anomalies"]) for i in indices)
            assert all(g in known_group_ids for g in rec["source_group_ids"])
            assert rec["evidence_ids"]
            for evidence_id in rec["evidence_ids"]:
                assert evidence_id in index
                assert index[evidence_id]["kind"] in {"anomaly", "group"}

    def test_date_windows_are_well_formed(self, plan_fixture):
        for rec in plan_fixture["recommendations"]:
            window = rec["date_window"]
            if window is None:
                continue
            assert set(window) == set(DATE_WINDOW_KEYS)
            assert window["start"] <= window["end"]

    def test_titles_descriptions_human_readable(self, plan_fixture):
        for rec in plan_fixture["recommendations"]:
            phrase = pb.action_phrase(rec["action_type"]).capitalize()
            assert rec["title"].startswith(phrase)
            assert rec["description"].endswith(".")
            assert "human review" in rec["description"]
            if rec["target_entity"]:
                assert f"for {rec['target_entity']} (" in rec["title"]
                assert rec["title"].endswith(")")

    def test_first_demo_anomaly_contributes_one_merged_record(self, plan_fixture):
        matches = [
            rec for rec in plan_fixture["recommendations"] if 0 in rec["source_anomaly_indices"]
        ]
        assert len(matches) == 1
        rec = matches[0]
        assert rec["target_entity"] == "Gadget Plus"
        assert rec["source_factors"] == ["monetary"]
        assert rec["source_group_ids"] == [1]
        assert {"E36", "E82"} <= set(rec["evidence_ids"])
        assert "+14.51%" in rec["description"]
        assert rec["action_type"] == "revenue_operations_review"

    def test_every_demo_anomaly_appears_somewhere(self, plan_fixture):
        seen: set[int] = set()
        for rec in plan_fixture["recommendations"]:
            seen.update(rec["source_anomaly_indices"])
        assert seen == set(range(46))

    def test_json_serializable(self, plan_fixture):
        encoded = json.dumps(plan_fixture, sort_keys=True)
        assert "NaN" not in encoded and "Infinity" not in encoded


# --- Determinism, immutability, no trend influence ------------------------------------------------------------


class TestDeterminismAndImmutability:
    def test_identical_inputs_identical_plans(self):
        first = generate_recommendations(demo_pack())
        second = generate_recommendations(demo_pack())
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_caller_pack_never_mutated(self):
        pack = demo_pack()
        snapshot = json.dumps(pack, sort_keys=True)
        generate_recommendations(pack)
        assert json.dumps(pack, sort_keys=True) == snapshot

    def test_caller_frame_never_mutated(self):
        df = copy.copy(_DEMO_CACHE["df"])
        snapshot = df.copy(deep=True)
        generate_recommendations(df)
        pd.testing.assert_frame_equal(df, snapshot)

    def test_returned_containers_are_fresh(self):
        first = generate_recommendations(demo_pack())
        first["parameters"]["sensitivity"] = "tampered"
        first["recommendations"][0]["title"] = "tampered"
        second = generate_recommendations(demo_pack())
        assert second["parameters"]["sensitivity"] != "tampered"
        assert second["recommendations"][0]["title"] != "tampered"

    def test_trend_never_influences_output(self):
        pack = demo_pack()
        baseline = generate_recommendations(pack)
        mutated = demo_pack()
        for insight in mutated["insights"]:
            insight["trend"] = {"direction": "spike", "change_pct": 999.0} if insight["trend"] else None
        adjusted = generate_recommendations(mutated)
        assert json.dumps(baseline["recommendations"], sort_keys=True) == json.dumps(
            adjusted["recommendations"], sort_keys=True
        )


# --- Investigation provenance ----------------------------------------------------------------------------------


class TestInvestigationProvenance:
    def test_status_and_citations_flow_through_filtered(self):
        pack = tiny_pack(
            anomalies=[make_anomaly()], insights=[make_insight()], groups=singleton_groups([make_anomaly()])
        )
        result = make_result(pack, cited="E2", uncited="E999")
        plan = generate_recommendations(pack, investigation=result)
        assert plan["source"]["investigation_status"] == "complete"
        # E2 is the tiny pack's only anomaly evidence entry; the unknown
        # E999 must be filtered out.
        assert plan["source"]["cited_evidence_ids"] == ["E2"]

    def test_narrative_rejected_status_accepted(self):
        pack = tiny_pack(
            anomalies=[make_anomaly()], insights=[make_insight()], groups=singleton_groups([make_anomaly()])
        )
        result = make_result(pack, status="narrative_rejected")
        plan = generate_recommendations(pack, investigation=result)
        assert plan["source"]["investigation_status"] == "narrative_rejected"

    def test_citations_do_not_change_recommendations(self):
        pack = tiny_pack(
            anomalies=[make_anomaly()], insights=[make_insight()], groups=singleton_groups([make_anomaly()])
        )
        plain = generate_recommendations(pack)
        cited = generate_recommendations(pack, investigation=make_result(pack))
        assert json.dumps(plain["recommendations"], sort_keys=True) == json.dumps(
            cited["recommendations"], sort_keys=True
        )


# --- End-to-end goldens on synthetic packs -----------------------------------------------------------------------


class TestSyntheticGoldens:
    def single_pair_plan(self, anomaly, insight):
        return generate_recommendations(
            tiny_pack(anomalies=[anomaly], insights=[insight], groups=singleton_groups([anomaly]))
        )["recommendations"]

    def test_golden_single_localized_daily_recommendation(self):
        recs = self.single_pair_plan(
            make_anomaly(), make_insight(localization=make_localization())
        )
        assert len(recs) == 1
        rec = recs[0]
        assert rec["recommendation_id"] == "R1"
        assert rec["priority"] == "MEDIUM"
        # HIGH base 30 + strength bonus round(25 * 0.8) = 20 + localized 10.
        assert rec["priority_score"] == pytest.approx(60.0)
        assert rec["evidence_strength"] == pytest.approx(0.70)
        assert rec["action_type"] == "revenue_operations_review"
        assert rec["target_entity"] == "North"
        assert rec["scope"] == "region"
        assert rec["target_metric"] == "revenue"
        assert rec["date_window"] == {"start": "2025-01-05", "end": "2025-01-05"}
        assert rec["source_factors"] == ["monetary"]
        assert rec["source_anomaly_indices"] == [0]
        assert rec["source_group_ids"] == [1]
        assert rec["title"] == "Review revenue operations for North (revenue)"
        assert "observed on 2025-01-05" in rec["description"]
        assert "+25.00%" in rec["description"]
        assert "primary factor 'monetary' (strength 0.80)" in rec["description"]
        assert "localized in region North (90.00% share)" in rec["description"]

    def test_golden_two_day_merge_spans_window_and_corroborates(self):
        anomalies = [
            make_anomaly(date="2025-01-05", score=80.0, deviation_pct=25.0),
            make_anomaly(date="2025-01-06", score=70.0, deviation_pct=18.0),
        ]
        insights = [
            make_insight(date="2025-01-05", factors=[make_factor(strength=0.8)], localization=make_localization()),
            make_insight(date="2025-01-06", factors=[make_factor(strength=0.6)], localization=make_localization()),
        ]
        pack = tiny_pack(anomalies=anomalies, insights=insights, groups=singleton_groups(anomalies))
        recs = generate_recommendations(pack)["recommendations"]
        assert len(recs) == 1
        rec = recs[0]
        assert rec["priority"] == "MEDIUM"
        assert rec["priority_score"] == pytest.approx(65.0)
        assert rec["evidence_strength"] == pytest.approx(0.75)
        assert rec["source_anomaly_indices"] == [0, 1]
        assert rec["date_window"] == {"start": "2025-01-05", "end": "2025-01-06"}
        assert "observed between 2025-01-05 and 2025-01-06" in rec["description"]
        assert "corroborated by 2 related anomaly record(s)" in rec["description"]
        summary = generate_recommendations(pack)["summary"]
        assert summary["total_count"] == 1
        assert summary["by_action_type"] == {"revenue_operations_review": 1}

    def test_golden_entity_outlier_profile_recommendation(self):
        recs = self.single_pair_plan(
            make_entity_anomaly(), make_entity_insight(profile="volume_driven", ratio=2.5)
        )
        assert len(recs) == 1
        rec = recs[0]
        assert rec["action_type"] == "demand_capacity_review"
        assert rec["target_entity"] == "North"
        assert rec["scope"] == "region"
        assert rec["date_window"] is None
        assert rec["source_factors"] == ["volume_driven"]
        assert rec["priority"] == "LOW"
        assert rec["priority_score"] == pytest.approx(40.0)
        assert rec["evidence_strength"] == pytest.approx(0.30)
        assert rec["title"] == "Review demand and capacity planning for North (revenue)"
        assert "peer profile 'volume_driven'" in rec["description"]
        assert "peer ratio 2.50x meets or exceeds the 2.0x concentration threshold" in rec["description"]

    def test_full_ranking_tie_break_sequence(self):
        north_volume = make_anomaly(metric="units_sold", date="2025-01-05", score=80.0)
        insight_volume = make_insight(
            metric="units_sold", factors=[make_factor(label="volume", strength=0.8)],
            localization=make_localization(),
        )
        north_revenue = make_anomaly(metric="revenue", date="2025-01-06", score=80.0)
        insight_north_revenue = make_insight(date="2025-01-06", localization=make_localization())
        south_revenue = make_anomaly(
            metric="revenue", date="2025-01-07", score=80.0, entity="South", value=125.0, expected_value=100.0
        )
        insight_south_revenue = make_insight(
            date="2025-01-07", entity="South", localization=make_localization(contributors=[{"entity": "South", "share_pct": 88.0}])
        )
        anomalies = [north_volume, north_revenue, south_revenue]
        insights = [insight_volume, insight_north_revenue, insight_south_revenue]
        pack = tiny_pack(anomalies=anomalies, insights=insights, groups=singleton_groups(anomalies))
        recs = generate_recommendations(pack)["recommendations"]
        assert [(r["recommendation_id"], r["action_type"], r["target_entity"]) for r in recs] == [
            ("R1", "demand_capacity_review", "North"),
            ("R2", "revenue_operations_review", "North"),
            ("R3", "revenue_operations_review", "South"),
        ]
        assert all(r["priority_score"] == pytest.approx(60.0) for r in recs)
