"""End-to-end deterministic demo smoke check for OpsPilot AI (Phase 10B).

Exercises the complete local workflow — dataset load, validation,
analysis, artifacts, anomaly/insight expectations, recommendations,
audit persistence and read-back, and export generation — against the
bundled demo dataset using the same public entry points as the app.

The script is fully offline:

* no browser automation, no external network calls;
* Gemini is never invoked. Without ``GEMINI_API_KEY`` it reports
  ``Gemini: SKIPPED (no configured key)`` which is a valid successful
  condition; AI output is never faked;
* persistence runs against a temporary throwaway SQLite database so
  the developer's real audit store is untouched.

Usage (from the repository root):

    .\\.venv\\Scripts\\python.exe scripts\\demo_smoke.py

Exit code 0 = overall PASS, 1 = any stage failed.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.schemas import EXPECTED_PLAN_KEYS, RECOMMENDATION_KEYS  # noqa: E402
from app import exports, orchestrator  # noqa: E402
from core.config import has_gemini_api_key  # noqa: E402
from database import repository  # noqa: E402
from database.connection import connect, init_db  # noqa: E402


class _Stages:
    """Collects one PASS/FAIL result per named stage."""

    def __init__(self) -> None:
        self.results: list[tuple[str, str]] = []

    def record(self, name: str, ok: bool, detail: str = "") -> bool:
        line = "PASS" if ok else "FAIL"
        if detail and not ok:
            line = f"FAIL ({detail})"
        self.results.append((name, line))
        return ok


def main() -> int:
    stages = _Stages()
    analysis_seconds = float("nan")

    db_path = Path(tempfile.mkstemp(suffix=".db", prefix="opspilot_smoke_")[1])
    engine = None
    try:
        # --- Dataset -------------------------------------------------
        try:
            df = orchestrator.load_demo_dataset("demo_operational_data.csv")
            ok = df is not None and len(df) > 0
            stages.record("Dataset", ok)
        except Exception as exc:  # noqa: BLE001 - reported as stage failure
            stages.record("Dataset", False, type(exc).__name__)
            return _finish(stages, analysis_seconds)

        # --- Validation ----------------------------------------------
        try:
            report = orchestrator.require_valid_dataset(df)
            stages.record("Validation", isinstance(report, dict))
        except Exception as exc:  # noqa: BLE001
            stages.record("Validation", False, type(exc).__name__)
            return _finish(stages, analysis_seconds)

        # --- Analysis --------------------------------------------------
        try:
            started = time.perf_counter()
            artifacts = orchestrator.run_pipeline(
                df, dataset_name="demo_operational_data.csv"
            )
            analysis_seconds = time.perf_counter() - started
            stages.record("Analysis", artifacts is not None)
        except Exception as exc:  # noqa: BLE001
            stages.record("Analysis", False, type(exc).__name__)
            return _finish(stages, analysis_seconds)

        # --- Artifacts ---------------------------------------------------
        pack = artifacts.pack
        artifacts_ok = all(
            getattr(artifacts, field, None) is not None
            for field in (
                "kpis",
                "region_performance",
                "product_performance",
                "daily_trends",
                "period_comparison",
                "top_performers",
                "bottom_performers",
            )
        ) and isinstance(pack.get("parameters"), dict)
        stages.record("Artifacts", artifacts_ok)

        # --- Anomalies / Insights -----------------------------------------
        anomaly_count = len(artifacts.anomalies)
        insight_count = len(artifacts.insights)
        stages.record("Anomalies", anomaly_count > 0, detail="none detected")
        insights_ok = insight_count == anomaly_count and all(
            isinstance(insight.get("headline"), str) and insight["headline"]
            for insight in artifacts.insights
        )
        stages.record("Insights", insights_ok)

        # --- Recommendations ------------------------------------------------
        try:
            plan = orchestrator.generate_plan(pack)
            recommendations = plan.get("recommendations") or []
            schema_ok = EXPECTED_PLAN_KEYS.issubset(plan.keys()) and all(
                RECOMMENDATION_KEYS.issubset(record.keys())
                for record in recommendations
            )
            stages.record("Recommendations", schema_ok and len(recommendations) > 0)
        except Exception as exc:  # noqa: BLE001
            stages.record("Recommendations", False, type(exc).__name__)

        # --- Persistence + Audit (temporary throwaway database) -------------
        audit_ok = False
        try:
            engine = connect(f"sqlite:///{db_path}")
            init_db(engine)

            plan_id = orchestrator.persist_plan(engine, plan)
            stored = repository.get_plan(engine, plan_id)
            persistence_ok = (
                stored is not None
                and stored["plan_id"] == plan_id
                and len(stored.get("recommendations", [])) == len(recommendations)
            )

            first = dict(recommendations[0])
            updated_record, event = orchestrator.apply_review(
                "APPROVE", first, reviewer_id="demo-smoke"
            )
            orchestrator.persist_review(engine, updated_record, event)

            counts_ok = (
                repository.count_plans(engine) == 1
                and repository.count_recommendations(engine) >= len(recommendations)
                and repository.count_review_events(engine) == 1
                and len(repository.list_plans(engine)) == 1
            )
            audit_ok = counts_ok
            stages.record("Persistence", persistence_ok)
            stages.record("Audit", audit_ok)
        except Exception as exc:  # noqa: BLE001
            stages.record("Persistence", False, type(exc).__name__)
            stages.record("Audit", False, type(exc).__name__)

        # --- Exports -----------------------------------------------------------
        try:
            summary_text = exports.canonical_json(
                exports.analysis_summary_payload(artifacts)
            )
            csv_text = exports.anomalies_csv_text(artifacts)
            audit_payload = exports.plan_audit_payload(
                [repository.get_plan(engine, plan_id)],
                repository.list_review_events(engine),
            )
            exports_ok = (
                len(summary_text) > 0
                and csv_text.count("\n") >= max(anomaly_count, 1)
                and exports.canonical_json(audit_payload)  # must serialize cleanly
            )
            stages.record("Exports", bool(exports_ok))
        except Exception as exc:  # noqa: BLE001
            stages.record("Exports", False, type(exc).__name__)

    finally:
        if engine is not None:
            engine.dispose()
        try:
            db_path.unlink(missing_ok=True)
        except OSError:
            pass

    return _finish(stages, analysis_seconds)


def _finish(stages: _Stages, analysis_seconds: float) -> int:
    gemini_line = (
        "CONFIGURED (not exercised offline)"
        if has_gemini_api_key()
        else "SKIPPED (no configured key)"
    )
    failed = [name for name, line in stages.results if not line.startswith("PASS")]
    overall = "PASS" if not failed else "FAIL"

    print()
    for name, line in stages.results:
        print(f"{name}: {line}")
    print(f"Gemini: {gemini_line}")
    print(f"Overall: {overall}")
    print(f"analysis_duration_seconds={analysis_seconds:.2f}")
    if failed:
        print(f"failed_stages={','.join(failed)}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
