"""Tests for the Phase 8 application orchestration layer.

Covers ``app/orchestrator.py`` — the thin coordination layer between the
Streamlit UI and the existing tested services. The orchestrator itself is
Streamlit-free, so these tests run it directly: pipeline sequencing and
validation gating, artifact structure, determinism, upload staging
safety, review dispatch through the real Phase 6 service, persistence-once
behavior, no-Gemini degradation, and end-to-end persistence round trips
against temporary SQLite databases.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import orchestrator  # noqa: E402
from core.exceptions import ConfigurationError, DataValidationError, OpsPilotError  # noqa: E402
from database import repository as repo  # noqa: E402
from database.connection import connect, init_db  # noqa: E402


# --- fixtures ---------------------------------------------------------------------------


def make_valid_frame(rows_per_date: int = 4) -> pd.DataFrame:
    """Minimal canonical dataset spanning several dates/regions/products."""
    rows = []
    for day in range(1, 5):
        for region_number in range(2):
            for product_number in range(2):
                base = 100.0 + day * 10 + region_number * 5 + product_number
                spike = 3.0 if (day == 4 and region_number == 0) else 1.0
                revenue = base * spike * 7
                cost = revenue * 0.6
                rows.append(
                    {
                        "date": f"2026-01-0{day}",
                        "region": f"R{region_number}",
                        "product": f"P{product_number}",
                        "units_sold": int(base),
                        "revenue": round(revenue, 2),
                        "cost": round(cost, 2),
                        "lead_time_days": 3.0 + region_number,
                    }
                )
    return pd.DataFrame(rows)


@pytest.fixture(scope="session")
def demo_df() -> pd.DataFrame:
    """Loaded once per session; every consumer treats it as read-only."""
    return orchestrator.load_demo_dataset("demo_operational_data.csv")


@pytest.fixture()
def engine(tmp_path):
    eng = connect(f"sqlite:///{(tmp_path / 'audit.db').as_posix()}")
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def artifacts(demo_df):
    """Full demo pipeline result built once; deterministic and read-only."""
    return orchestrator.run_pipeline(
        demo_df, dataset_name="demo_operational_data.csv", sensitivity="medium"
    )


# --- 1/2. pipeline execution and validation gate -----------------------------------------


class TestPipelineGate:
    def test_valid_dataframe_produces_artifacts(self, demo_df):
        artifacts = orchestrator.run_pipeline(demo_df)
        assert isinstance(artifacts, orchestrator.AnalysisArtifacts)

    def test_invalid_dataframe_is_rejected_before_analysis(self):
        broken = make_valid_frame().drop(columns=["revenue"])
        with pytest.raises(DataValidationError, match="MISSING_COLUMNS"):
            orchestrator.run_pipeline(broken)

    def test_negative_values_block_analysis(self):
        frame = make_valid_frame()
        frame.loc[0, "revenue"] = -5.0
        with pytest.raises(DataValidationError, match="OUT_OF_RANGE"):
            orchestrator.run_pipeline(frame)

    def test_warnings_do_not_block_analysis(self):
        frame = make_valid_frame()
        frame["extra_column"] = 1
        artifacts = orchestrator.run_pipeline(frame)
        report = artifacts.validation_report
        assert report["valid"] is True
        assert report["warning_count"] >= 1

    def test_invalid_rows_are_never_dropped_or_imputed(self):
        frame = make_valid_frame()
        frame.loc[0, "region"] = None
        with pytest.raises(DataValidationError):
            orchestrator.run_pipeline(frame)


# --- 3. artifact structure -----------------------------------------------------------------


class TestArtifactStructure:
    EXPECTED_FIELDS = (
        "dataset_name", "df", "validation_report", "kpis", "region_performance",
        "product_performance", "daily_trends", "period_comparison",
        "top_performers", "bottom_performers", "anomaly_result",
        "anomaly_summary", "insights", "grouping", "pack",
    )

    def test_bundle_carries_every_rendering_artifact(self, artifacts):
        for field in self.EXPECTED_FIELDS:
            assert getattr(artifacts, field) is not None, field

    def test_validation_report_shape(self, artifacts):
        report = artifacts.validation_report
        assert set(report) == {
            "valid", "row_count", "column_count", "error_count",
            "warning_count", "errors", "warnings",
        }
        assert report["valid"] is True

    def test_anomaly_result_shape(self, artifacts):
        result = artifacts.anomaly_result
        assert {"anomalies", "total_count", "by_severity",
                "sensitivity", "metrics_analyzed"} <= set(result)
        assert result["total_count"] == len(result["anomalies"])

    def test_grouping_shape(self, artifacts):
        assert {"groups", "ungrouped_count"} == set(artifacts.grouping)

    def test_properties_expose_display_collections(self, artifacts):
        assert artifacts.anomalies == artifacts.anomaly_result["anomalies"]
        assert artifacts.groups == artifacts.grouping["groups"]

    def test_period_comparison_changes_present(self, artifacts):
        changes = artifacts.period_comparison["changes_pct"]
        assert "revenue_change_pct" in changes and "profit_change_pct" in changes


# --- 4. deterministic repeatability ----------------------------------------------------------


class TestDeterminism:
    def test_pipeline_is_repeatable(self, demo_df):
        first = orchestrator.run_pipeline(demo_df, dataset_name="x")
        second = orchestrator.run_pipeline(demo_df, dataset_name="x")
        assert first.kpis == second.kpis
        assert first.period_comparison == second.period_comparison
        assert first.top_performers == second.top_performers
        assert first.bottom_performers == second.bottom_performers
        assert first.anomaly_result == second.anomaly_result
        assert first.anomaly_summary == second.anomaly_summary
        assert first.insights == second.insights
        assert first.grouping == second.grouping
        assert first.pack == second.pack

    def test_input_dataframe_never_mutated(self, demo_df):
        snapshot = demo_df.copy(deep=True)
        orchestrator.run_pipeline(demo_df)
        pd.testing.assert_frame_equal(demo_df, snapshot)

    @pytest.mark.parametrize("sensitivity", ["low", "medium", "high"])
    def test_pipeline_is_repeatable_per_sensitivity(self, sensitivity):
        """Same frame + sensitivity + focus => equivalent artifacts."""
        frame = make_valid_frame()
        kwargs = {"dataset_name": "x", "sensitivity": sensitivity}
        first = orchestrator.run_pipeline(frame, **kwargs)
        second = orchestrator.run_pipeline(frame, **kwargs)
        assert first.anomaly_result == second.anomaly_result
        assert first.insights == second.insights
        assert first.pack == second.pack


# --- Phase 8A: single-pass orchestration -------------------------------------------------------


class TestSinglePassOrchestration:
    """The expensive deterministic work must happen exactly once.

    ``run_pipeline`` builds the evidence pack once and reuses its fields;
    these instrumented-call-count tests protect against regressing into
    "detect -> build evidence -> detect again" style double execution.
    """

    def _instrument(self, monkeypatch, counters):
        import agent.evidence as evidence_module
        import app.orchestrator as orch_module

        def wrap(module, name, key):
            original = getattr(module, name)

            def counted(*args, **kwargs):
                counters[key] = counters.get(key, 0) + 1
                return original(*args, **kwargs)

            monkeypatch.setattr(module, name, counted)

        # Orchestrator-level entry points (what run_pipeline calls directly).
        for name in (
            "build_investigation_context",
            "summarize_anomalies",
            "calculate_region_performance",
            "calculate_product_performance",
            "calculate_daily_trends",
            "calculate_period_comparison",
        ):
            wrap(orch_module, name, f"orch.{name}")

        # Evidence-pack internals (what the pack computes on our behalf;
        # any extra independent recomputation would show up here).
        for name in (
            "detect_anomalies",
            "explain_anomalies",
            "group_related_anomalies",
            "calculate_kpis",
            "calculate_period_comparison",
            "calculate_top_performers",
            "calculate_bottom_performers",
        ):
            wrap(evidence_module, name, f"evidence.{name}")

    def test_heavy_functions_execute_exactly_once(self, monkeypatch):
        counters: dict[str, int] = {}
        self._instrument(monkeypatch, counters)
        orchestrator.run_pipeline(make_valid_frame())

        expected_once = {
            "orch.build_investigation_context": 1,
            "orch.summarize_anomalies": 1,
            "orch.calculate_region_performance": 1,
            "orch.calculate_product_performance": 1,
            "orch.calculate_daily_trends": 1,
            "orch.calculate_period_comparison": 0,  # reused from the pack
            "evidence.detect_anomalies": 1,
            "evidence.explain_anomalies": 1,
            "evidence.group_related_anomalies": 1,
            "evidence.calculate_kpis": 1,
            "evidence.calculate_period_comparison": 1,
            "evidence.calculate_top_performers": 1,
            "evidence.calculate_bottom_performers": 1,
        }
        for key, expected in expected_once.items():
            assert counters.get(key, 0) == expected, (
                f"{key} executed {counters.get(key, 0)}x (expected {expected})"
            )

    def test_artifacts_equal_independent_service_outputs(self):
        """Pack-reuse reproduces exactly what direct service calls yield."""
        from agent.evidence import build_investigation_context
        from services.analytics_service import (
            calculate_bottom_performers,
            calculate_daily_trends,
            calculate_kpis,
            calculate_period_comparison,
            calculate_top_performers,
        )
        from services.anomaly_service import detect_anomalies, summarize_anomalies

        frame = make_valid_frame()
        artifacts = orchestrator.run_pipeline(frame, dataset_name="svc")
        pack = build_investigation_context(frame)

        assert artifacts.validation_report == orchestrator.validate_dataset(frame)
        assert artifacts.kpis == calculate_kpis(frame) == pack["kpis"]
        assert artifacts.period_comparison == calculate_period_comparison(frame)
        assert artifacts.top_performers == calculate_top_performers(frame)
        assert artifacts.bottom_performers == calculate_bottom_performers(frame)
        pd.testing.assert_frame_equal(
            artifacts.daily_trends, calculate_daily_trends(frame)
        )
        # Reuse within one pipeline: no second detection pass.
        assert artifacts.pack["anomalies"] is artifacts.anomaly_result["anomalies"]
        # Equivalent to the historical direct-detection behavior.
        assert artifacts.anomaly_result["anomalies"] == detect_anomalies(frame)["anomalies"]
        assert artifacts.anomaly_result["total_count"] == len(pack["anomalies"])
        assert artifacts.anomaly_result["by_severity"] == summarize_anomalies(
            pack["anomalies"]
        )["by_severity"]
        assert artifacts.insights == pack["insights"]
        assert artifacts.grouping == pack["groups"]

    def test_single_date_dataset_still_raises(self):
        """Degenerate datasets keep the historical hard-failure contract."""
        frame = make_valid_frame()
        single = frame[frame["date"] == "2026-01-01"].reset_index(drop=True)
        with pytest.raises(DataValidationError):
            orchestrator.run_pipeline(single)


# --- 5/6. demo CSV end to end and evidence pack ------------------------------------------------


class TestDemoEndToEnd:
    def test_demo_dataset_discoverable_and_loadable(self):
        names = [d["name"] for d in orchestrator.list_demo_datasets()]
        assert "demo_operational_data.csv" in names

    def test_demo_csv_to_full_artifacts(self, demo_df):
        report = orchestrator.validate_dataset(demo_df)
        assert report["valid"] is True
        artifacts = orchestrator.run_pipeline(
            demo_df, dataset_name="demo_operational_data.csv"
        )
        assert len(artifacts.daily_trends) >= 2

    def test_evidence_pack_generation(self, artifacts):
        pack = artifacts.pack
        assert pack["type"] == "investigation_context"
        assert pack["schema_version"] == "1.0"
        assert pack["parameters"]["sensitivity"] == "medium"
        assert len(pack["evidence_index"]) > 0
        assert all(eid.startswith("E") for eid in pack["evidence_index"])

    def test_pack_matches_pipeline_counts(self, artifacts):
        assert len(artifacts.pack["anomalies"]) == artifacts.anomaly_result["total_count"]
        assert len(artifacts.pack["insights"]) == len(artifacts.insights)


# --- 7. recommendation generation ----------------------------------------------------------------


class TestRecommendationGeneration:
    def test_plan_generated_from_pack(self, artifacts):
        plan = orchestrator.generate_plan(artifacts.pack)
        assert plan["type"] == "recommendation_plan"
        assert isinstance(plan["recommendations"], list)
        for record in plan["recommendations"]:
            assert record["requires_human_review"] is True
            assert record["status"] == "PENDING"

    def test_plan_deterministic_for_same_inputs(self, artifacts):
        first = orchestrator.generate_plan(artifacts.pack)
        second = orchestrator.generate_plan(artifacts.pack)
        assert first == second

    def test_max_recommendations_respected(self, artifacts):
        capped = orchestrator.generate_plan(artifacts.pack, max_recommendations=1)
        assert len(capped["recommendations"]) <= 1


# --- 8. no-Gemini graceful behavior -----------------------------------------------------------------


class TestNoGeminiMode:
    def test_investigation_unavailable_without_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert orchestrator.investigation_available() is False

    def test_run_investigation_fails_closed_without_key(self, monkeypatch, artifacts):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
            orchestrator.run_investigation(artifacts.pack)

    def test_pipeline_works_without_any_gemini_dependency(
        self, monkeypatch, demo_df
    ):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        artifacts = orchestrator.run_pipeline(demo_df)
        assert artifacts.pack["evidence_index"]
        plan = orchestrator.generate_plan(artifacts.pack)
        assert plan["summary"]["total_count"] == len(plan["recommendations"])


# --- 9. plan persistence round trip --------------------------------------------------------------------


class TestPlanPersistenceRoundTrip:
    def test_persist_then_read_back(self, artifacts, engine):
        plan = orchestrator.generate_plan(artifacts.pack)
        plan_id = orchestrator.persist_plan(engine, plan)
        assert isinstance(plan_id, int) and plan_id >= 1
        assert repo.count_plans(engine) == 1
        assert repo.count_recommendations(engine) == plan["summary"]["total_count"]
        for record in plan["recommendations"]:
            latest = repo.get_latest_recommendation(engine, record["recommendation_id"])
            assert latest == record


# --- 10/11. review integration and history -----------------------------------------------------------------


class TestReviewIntegration:
    def test_apply_review_uses_real_service_contract(self, artifacts):
        plan = orchestrator.generate_plan(artifacts.pack)
        target = plan["recommendations"][0]
        updated, event = orchestrator.apply_review(
            "APPROVE", target, reviewer_id="tester"
        )
        assert updated["status"] == "APPROVED"
        assert event["decision"] == "APPROVE"
        assert target["status"] == "PENDING"

    @pytest.mark.parametrize("decision,status", [
        ("REJECT", "REJECTED"),
        ("REQUEST_CHANGES", "CHANGES_REQUESTED"),
    ])
    def test_each_decision_dispatches_correctly(self, artifacts, decision, status):
        plan = orchestrator.generate_plan(artifacts.pack)
        target = plan["recommendations"][0]
        updated, _ = orchestrator.apply_review(decision, target, reviewer_id="qa")
        assert updated["status"] == status

    def test_invalid_decision_rejected(self, artifacts):
        plan = orchestrator.generate_plan(artifacts.pack)
        with pytest.raises(DataValidationError):
            orchestrator.apply_review(
                "EXECUTE_IT_ANYWAY", plan["recommendations"][0], reviewer_id="x"
            )

    def test_review_persists_and_appears_in_history(self, artifacts, engine):
        plan = orchestrator.generate_plan(artifacts.pack)
        target = plan["recommendations"][0]
        plan_id = orchestrator.persist_plan(engine, plan)
        updated, event = orchestrator.apply_review(
            "APPROVE", target, reviewer_id="ops-manager", comment="Looks right."
        )
        rec_row, evt_row = orchestrator.persist_review(engine, updated, event)
        assert rec_row >= 1 and evt_row >= 1

        events = repo.list_review_events(engine)
        assert len(events) == 1
        stored = events[0]
        assert stored["recommendation_id"] == target["recommendation_id"]
        assert stored["previous_status"] == "PENDING"
        assert stored["new_status"] == "APPROVED"
        assert stored["reviewer_id"] == "ops-manager"
        assert stored["comment"] == "Looks right."

        latest = repo.get_latest_recommendation(engine, target["recommendation_id"])
        assert latest["status"] == "APPROVED"
        assert repo.count_plans(engine) == 1
        assert plan_id >= 1

    def test_full_revision_loop_round_trip(self, artifacts, engine):
        plan = orchestrator.generate_plan(artifacts.pack)
        orchestrator.persist_plan(engine, plan)
        target = plan["recommendations"][0]

        changed, chg_event = orchestrator.apply_review(
            "REQUEST_CHANGES", target, reviewer_id="qa", comment="Add unit context."
        )
        orchestrator.persist_review(engine, changed, chg_event)
        resubmitted, resub_event = orchestrator.apply_review(
            "RESUBMIT", changed, reviewer_id="analyst"
        )
        orchestrator.persist_review(engine, resubmitted, resub_event)
        approved, appr_event = orchestrator.apply_review(
            "APPROVE", resubmitted, reviewer_id="boss"
        )
        orchestrator.persist_review(engine, approved, appr_event)

        decisions = [e["decision"] for e in repo.list_review_events(engine)]
        assert decisions == ["REQUEST_CHANGES", "RESUBMIT", "APPROVE"]
        assert repo.count_review_events(engine) == 3
        latest = repo.get_latest_recommendation(engine, target["recommendation_id"])
        assert latest["status"] == "APPROVED"


# --- 12. persistence-once / rerun protection ------------------------------------------------------------------


class TestPersistenceOnceBehavior:
    def test_should_record_plan_rule(self):
        assert orchestrator.should_record_plan(None) is True
        assert orchestrator.should_record_plan(1) is False
        assert orchestrator.should_record_plan(42) is False

    def test_streamlit_style_rerun_records_only_once(self, artifacts, engine):
        """Simulate reruns: only the first generation persists a plan."""
        recorded_ids = []

        def simulate_page_rerun():
            session_plan_id = recorded_ids[-1] if recorded_ids else None
            if not orchestrator.should_record_plan(session_plan_id):
                return "reused"
            plan = orchestrator.generate_plan(artifacts.pack)
            recorded_ids.append(orchestrator.persist_plan(engine, plan))
            return "recorded"

        outcomes = [simulate_page_rerun() for _ in range(5)]
        assert outcomes == ["recorded", "reused", "reused", "reused", "reused"]
        assert repo.count_plans(engine) == 1

    def test_explicit_regeneration_creates_new_audit_record(self, artifacts, engine):
        first_plan_id = orchestrator.persist_plan(
            engine, orchestrator.generate_plan(artifacts.pack)
        )
        second_plan_id = orchestrator.persist_plan(
            engine, orchestrator.generate_plan(artifacts.pack)
        )
        assert second_plan_id == first_plan_id + 1
        assert repo.count_plans(engine) == 2


# --- upload staging safety ---------------------------------------------------------------------------------------


class TestUploadStaging:
    def test_stages_upload_under_gitignored_uploads_dir(self, tmp_path, monkeypatch):
        from app import orchestrator as orch

        monkeypatch.setattr(orch, "UPLOAD_DIR", tmp_path / "uploads")
        staged = orch.stage_upload("my_data.csv", b"date,region\n2026-01-01,R\n")
        assert staged.parent == tmp_path / "uploads"
        assert staged.read_bytes().startswith(b"date,region")

    def test_parent_paths_are_sanitized(self, tmp_path, monkeypatch):
        from app import orchestrator as orch

        monkeypatch.setattr(orch, "UPLOAD_DIR", tmp_path / "uploads")
        staged = orch.stage_upload("../../evil.csv", b"a,b\n1,2\n")
        assert staged.name == "evil.csv"
        assert staged.parent.name != ".."

    def test_non_csv_and_empty_content_rejected(self, tmp_path, monkeypatch):
        from app import orchestrator as orch

        monkeypatch.setattr(orch, "UPLOAD_DIR", tmp_path / "uploads")
        with pytest.raises(DataValidationError):
            orch.stage_upload("data.xlsx", b"x")
        with pytest.raises(DataValidationError):
            orch.stage_upload("data.csv", b"")

    def test_uploaded_dataset_flows_through_gate(self, tmp_path, monkeypatch):
        from app import orchestrator as orch

        monkeypatch.setattr(orch, "UPLOAD_DIR", tmp_path / "uploads")
        good = make_valid_frame().to_csv(index=False).encode()
        df = orch.load_uploaded_dataset("upload.csv", good)
        assert orchestrator.validate_dataset(df)["valid"] is True

        bad = df.drop(columns=["cost"]).to_csv(index=False).encode()
        bad_df = orch.load_uploaded_dataset("bad.csv", bad)
        with pytest.raises(OpsPilotError):
            orchestrator.require_valid_dataset(bad_df)
