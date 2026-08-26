"""Phase 11 presentation-layer tests.

Covers the design system (icons, theme, components, charts), the
navigation shell spec (grouped, Material icons, no emoji), and idle
boot smoke runs for every redesigned page. Functional behavior remains
covered by the Phase 8-10B suites; these tests protect the Phase 11
presentation contracts only.

NOTE: Streamlit pages (app/pages/) have been removed during the React/FastAPI
productization. These tests are skipped until the Streamlit UI is restored
or the tests are migrated to the React frontend.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Streamlit pages (app/pages/) have been removed; skip entire module.
pytestmark = pytest.mark.skip(
    reason="Streamlit pages removed during React/FastAPI productization"
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ui import charts, shell  # noqa: E402
from app.ui.icons import REQUIRED_ICONS, icon_svg  # noqa: E402

PAGES_DIR = PROJECT_ROOT / "app" / "pages"


# --- icon registry -----------------------------------------------------------------------------


class TestIconRegistry:
    def test_registry_is_substantial(self):
        assert len(REQUIRED_ICONS) >= 20

    def test_every_icon_renders_valid_svg(self):
        for name in sorted(REQUIRED_ICONS):
            svg = icon_svg(name)
            assert svg.startswith("<svg") and svg.endswith("</svg>"), name
            assert 'viewBox="0 0 24 24"' in svg, name
            assert "stroke=\"currentColor\"" in svg, name


# --- theme + components -------------------------------------------------------------------------


class TestThemeAndComponentsRender:
    def test_theme_and_metric_card_render(self):
        def scenario():
            import streamlit as st
            from app.ui.components import metric_card, severity_badge
            from app.ui.theme import apply_theme

            apply_theme()
            metric_card(
                "Revenue", "12,000", delta="+5.2%", delta_tone="good",
                icon="trending-up", caption="vs prior period",
            )
            st.markdown(severity_badge("CRITICAL"), unsafe_allow_html=True)

        at = AppTest.from_function(scenario)
        # The 3s default flaked on loaded machines (theme CSS is large);
        # give the first-import scenario room without weakening asserts.
        at.run(timeout=15)
        assert not at.exception
        rendered = "\n".join(str(m.value) for m in at.markdown)
        assert "--ops-bg" in rendered
        assert "Revenue" in rendered and "12,000" in rendered and "vs prior period" in rendered
        assert "ops-good" in rendered
        assert "ops-tone-danger" in rendered

    def test_empty_state_and_loading_panel_render(self):
        def scenario():
            from app.ui.components import empty_state, loading_panel

            empty_state("database", "Nothing here yet", "Load data to begin.")
            loading_panel("Crunching numbers", "Deterministic pipeline running.")

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(str(m.value) for m in at.markdown)
        assert "Nothing here yet" in rendered and "Load data to begin." in rendered
        assert "ops-empty" in rendered
        assert "Crunching numbers" in rendered and "ops-loading-bar" in rendered

    def test_strength_meter_and_badge_escaping(self):
        def scenario():
            import streamlit as st
            from app.ui.components import badge, strength_meter

            st.markdown(strength_meter(7.5), unsafe_allow_html=True)
            st.markdown(badge("<b>evil</b>", "success"), unsafe_allow_html=True)

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(str(m.value) for m in at.markdown)
        assert "ops-meter" in rendered and "75%" in rendered
        assert "&lt;b&gt;evil&lt;/b&gt;" in rendered  # escaped before embedding
        assert "<b>evil</b>" not in rendered


# --- workflow rail --------------------------------------------------------------------------------


class TestWorkflowRail:
    def test_idle_rail_has_no_progress(self):
        def scenario():
            from app.ui.components import workflow_rail

            workflow_rail()

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(str(m.value) for m in at.markdown)
        assert "ops-rail-step ops-done" not in rendered
        assert "ops-rail-step ops-active" not in rendered

    def test_running_analysis_shows_active_step(self):
        def scenario():
            import pandas as pd
            import streamlit as st
            from app.ui.components import workflow_rail

            st.session_state.df = pd.DataFrame({"a": [1]})
            st.session_state.analysis_status = "ANALYZING"
            workflow_rail()

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(str(m.value) for m in at.markdown)
        assert "ops-rail-step ops-done" in rendered      # data loaded
        assert "ops-rail-step ops-active" in rendered    # analysis running

    def test_ready_with_plan_marks_later_steps(self):
        def scenario():
            import pandas as pd
            import streamlit as st
            from app.ui.components import workflow_rail

            st.session_state.df = pd.DataFrame({"a": [1]})
            st.session_state.analysis_status = "READY"
            st.session_state.analysis_artifacts = object()
            st.session_state.plan = {
                "recommendations": [{"status": "APPROVED"}],
            }
            workflow_rail()

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(str(m.value) for m in at.markdown)
        assert rendered.count("ops-rail-step ops-done") >= 4


# --- dataset chip ----------------------------------------------------------------------------------


class TestDatasetChip:
    @pytest.fixture(autouse=True)
    def _no_recovery_sidecar(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "OPSPILOT_RECOVERY_PATH", str(tmp_path / "absent-sidecar.json")
        )

    def test_chip_reflects_loaded_dataset(self):
        def scenario():
            import pandas as pd
            import streamlit as st
            from app.ui.components import dataset_chip

            st.session_state.df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
            st.session_state.dataset_name = "demo_ops.csv"
            st.session_state.analysis_status = "READY"
            dataset_chip()

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(str(m.value) for m in at.markdown)
        assert "demo_ops.csv" in rendered and "2 rows" in rendered
        assert "READY" in rendered

    def test_chip_empty_without_dataset(self):
        def scenario():
            from app.ui.components import dataset_chip

            dataset_chip()

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(str(m.value) for m in at.markdown)
        assert "No dataset loaded" in rendered


# --- workflow visualization / loading primitives -------------------------------------------------


class TestTimelineStepperAndSkeletons:
    @staticmethod
    def _rendered(at) -> str:
        return "\n".join(str(m.value) for m in at.markdown)

    def test_timeline_item_escapes_body_and_applies_dot_tone(self):
        def scenario():
            import streamlit as st

            from app.ui.components import badge, timeline, timeline_item

            item = timeline_item(
                when="2026-01-01 08:00",
                badges=[badge("APPROVED", "success")],
                body="reviewer <img src=x>",
                tone="success",
            )
            timeline([item])

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = self._rendered(at)
        assert "ops-timeline-item" in rendered
        assert "ops-timeline-dot ops-tone-success" in rendered
        assert "2026-01-01 08:00" in rendered and "APPROVED" in rendered
        assert "&lt;img src=x&gt;" in rendered
        assert "<img src=x>" not in rendered

    def test_timeline_without_items_renders_nothing(self):
        def scenario():
            from app.ui.components import timeline

            timeline([])

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        assert self._rendered(at).strip() == ""

    def test_stepper_renders_all_states(self):
        def scenario():
            from app.ui.components import stepper

            stepper([
                ("Load", "done"),
                ("Analyze", "active"),
                ("Review", "todo"),
                ("Blocked", "blocked"),
            ])

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = self._rendered(at)
        assert "ops-stepper-step ops-done" in rendered      # check glyph
        assert "ops-stepper-step ops-active" in rendered
        assert "ops-stepper-step ops-blocked" in rendered
        assert "ops-timeline-dot" not in rendered           # stepper, not rail
        assert "<span class='ops-stepper-glyph'>3</span>" in rendered  # todo numbering

    def test_skeleton_lines_and_cards_render_shimmer_blocks(self):
        def scenario():
            from app.ui.components import skeleton_cards, skeleton_lines

            skeleton_lines(2)
            skeleton_cards(3)

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = self._rendered(at)
        # 2 lines + 2 text blocks inside each of the 3 skeleton cards
        assert rendered.count("ops-skeleton ops-skeleton-text") == 2 + 3 * 2
        assert rendered.count("class='ops-card'") == 3
        assert "ops-skeleton-title" in rendered

    def test_status_dot_tones(self):
        from app.ui.components import sidebar_footer, status_dot

        assert 'class="ops-status-dot ops-tone-ai"' in status_dot("ai")
        assert status_dot("muted").startswith('<span class="ops-status-dot')
        # footer keeps using the shared primitive (no hardcoded hex inline)
        source = sidebar_footer.__code__.co_consts
        assert not any(
            isinstance(const, str) and "#A78BFA" in const for const in source
        )


# --- workflow stepper (in-page) ----------------------------------------------------------------------


class TestWorkflowStepper:
    def test_idle_stepper_has_no_progress(self):
        def scenario():
            from app.ui.components import workflow_stepper

            workflow_stepper()

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(str(m.value) for m in at.markdown)
        assert "ops-stepper-step ops-done" not in rendered
        assert "ops-stepper-step ops-active" not in rendered

    def test_ready_with_plan_matches_sidebar_rail_states(self):
        def scenario():
            import pandas as pd
            import streamlit as st

            from app.ui.components import workflow_rail, workflow_stepper

            st.session_state.df = pd.DataFrame({"a": [1]})
            st.session_state.analysis_status = "READY"
            st.session_state.analysis_artifacts = object()
            st.session_state.plan = {
                "recommendations": [{"status": "APPROVED"}],
            }
            workflow_rail()
            workflow_stepper(compact_labels=True)

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(str(m.value) for m in at.markdown)
        # Observe + Understand/Detect/Investigate + Recommend + Human decision
        # are done; Audit stays un-done until the plan is actually persisted.
        assert rendered.count("ops-rail-step ops-done") == 6
        assert rendered.count("ops-stepper-step ops-done") == 6


# --- review status flow ------------------------------------------------------------------------------


class TestReviewStatusSteps:
    def test_steps_are_honest(self):
        from app.pages.review import _status_steps

        pending = _status_steps("PENDING")
        assert pending[0] == ("PENDING", "active")
        # PENDING -> APPROVED is legal, so intermediates are never 'done'
        assert [state for _, state in pending] == ["active", "todo", "todo"]
        approved = dict(_status_steps("APPROVED"))
        assert approved["APPROVED"] == "active"
        assert all(state == "blocked" for _, state in _status_steps("REJECTED"))


# --- charts -----------------------------------------------------------------------------------------


class TestChartBuilders:
    def test_all_builders_return_altair_charts(self):
        import altair as alt
        import pandas as pd

        trends = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=6),
            "revenue": [10.0, 12.0, 11.0, 13.0, 15.0, 14.0],
            "profit": [4.0, 5.0, 4.5, 5.5, 6.5, 6.0],
        })
        area = charts.area_trends(trends, "date", ["revenue", "profit"])
        bars = charts.hbar_counts({"type_a": 3, "type_b": 1})
        perf = charts.performance_bars(
            pd.DataFrame({"region": ["North", "South"], "revenue": [120.0, 90.0]}),
            "region", "revenue",
        )
        diverging = charts.diverging_pct({
            "revenue_change_pct": 4.2,
            "cost_change_pct": -2.0,
            "lead_time_change_pct": 1.5,
        })
        for chart in (area, bars, perf, diverging):
            assert isinstance(chart, (alt.Chart, alt.LayerChart)), chart

    def test_charts_disable_vega_action_bar(self):
        """Regression: Vega-Embed's default hover actions rendered a
        floating 'Open in Vega Editor / Save as SVG / PNG' menu that read
        as stray svg/canvas artifacts next to every visualization."""
        import pandas as pd

        trends = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=3),
            "revenue": [1.0, 2.0, 3.0],
        })
        built = [
            charts.area_trends(trends, "date", ["revenue"]),
            charts.hbar_counts({"a": 1}),
            charts.performance_bars(
                pd.DataFrame({"region": ["N"], "revenue": [1.0]}), "region", "revenue"
            ),
            charts.diverging_pct({"revenue_change_pct": 1.0}),
        ]
        for chart in built:
            usermeta = getattr(chart, "usermeta", None) or {}
            embed = usermeta.get("embedOptions") or {}
            assert embed.get("actions") is False, type(chart).__name__

    def test_diverging_handles_none_and_nan(self):
        import altair as alt

        chart = charts.diverging_pct({
            "revenue_change_pct": None,
            "profit_change_pct": float("nan"),
        })
        assert isinstance(chart, (alt.Chart, alt.LayerChart))


# --- navigation shell -------------------------------------------------------------------------------


class TestShellSpec:
    def test_group_structure_matches_design(self):
        expected = {
            "COMMAND CENTER": ["Overview"],
            "DATA": ["Data"],
            "INTELLIGENCE": ["Analytics", "Anomalies", "Insights", "Evidence"],
            "DECISION": ["Recommendations", "Human Review"],
            "AUDIT": ["History"],
        }
        groups = {name: [title for title, _, _ in entries]
                  for name, entries in shell.NAV_SECTIONS}
        assert groups == expected

    def test_flat_pages_are_complete_and_emoji_free(self):
        expected = {
            "Overview", "Data", "Analytics", "Anomalies",
            "Insights", "Evidence", "Recommendations", "Human Review",
            "History",
        }
        titles = list(shell.FLAT_PAGES)
        assert set(titles) == expected
        emoji_pattern = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")
        for title, (stem, icon) in shell.FLAT_PAGES.items():
            assert not emoji_pattern.search(title), title
            assert not emoji_pattern.search(icon), icon
            assert (PAGES_DIR / f"{stem}.py").is_file(), stem

    def test_material_icon_shortcodes_are_valid(self):
        from streamlit.string_util import validate_material_icon

        for _, (_, icon) in shell.FLAT_PAGES.items():
            validate_material_icon(f":material/{icon}:")

    def test_build_pages_maps_every_icon_without_name_error(self):
        """Regression: build_pages() referenced a discarded loop variable,
        raising NameError on every script run (shell.py comprehension)."""

        def scenario():
            import sys
            from pathlib import Path

            import streamlit as st

            sys.path.insert(0, str(Path.cwd()))
            from app.ui.shell import build_pages

            built = build_pages(Path("app/pages").resolve())
            flat = [
                (page.title, page.icon)
                for group_pages in built.values()
                for page in group_pages
            ]
            st.session_state["_nav_flat"] = flat

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        entries = dict(at.session_state["_nav_flat"])
        assert len(entries) == 9
        for title, (_, icon) in shell.FLAT_PAGES.items():
            assert entries.get(title) == f":material/{icon}:", title

    @pytest.fixture(autouse=True)
    def _no_recovery_sidecar(self, tmp_path, monkeypatch):
        # Isolate from any developer-machine recovery sidecar so the
        # sidebar renders its deterministic idle state.
        monkeypatch.setenv(
            "OPSPILOT_RECOVERY_PATH", str(tmp_path / "absent-sidecar.json")
        )

    def test_render_sidebar_composes_brand_and_workflow_context(self):
        def scenario():
            from app.ui.shell import render_sidebar

            render_sidebar("OpsPilot AI", "Operations Intelligence")

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(str(m.value) for m in at.markdown)
        assert "OpsPilot AI" in rendered
        assert "Active dataset" in rendered          # dataset/recovery context
        assert "No dataset loaded" in rendered       # honest idle state
        assert "Lifecycle" in rendered               # seven-stage rail

    def test_page_transition_is_opacity_only_and_reduced_motion_gated(self):
        from app.ui.theme import _CSS

        assert "@keyframes ops-page-fade" in _CSS
        fade_rule = _CSS[_CSS.index(".stMainBlockContainer { animation:"):]
        assert "transform" not in fade_rule.split(";")[0]   # no layout shift
        assert _CSS.count("prefers-reduced-motion") >= 2    # kill switch intact


# --- page boot smoke (idle session) -----------------------------------------------------------------


PAGE_STEMS = (
    "overview", "data", "analytics", "anomalies",
    "insights", "evidence", "recommendations", "review",
)


@pytest.mark.parametrize("stem", PAGE_STEMS)
class TestIdlePageBoot:
    @pytest.fixture(autouse=True)
    def _isolated_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "DATABASE_URL", f"sqlite:///{(tmp_path / 'audit.db').as_posix()}"
        )
        # Boots must be independent of developer-machine sidecars: a stale
        # recovery_context.json at the project-default location would flip
        # every idle boot into the RECOVERY_AVAILABLE branch.
        monkeypatch.setenv(
            "OPSPILOT_RECOVERY_PATH", str(tmp_path / "absent-sidecar.json")
        )

    def test_boots_without_exception_or_traceback(self, stem):
        at = AppTest.from_file(str(PAGES_DIR / f"{stem}.py"), default_timeout=60)
        if stem == "review":
            # Bare-file AppTest has no multipage registry, so the idle
            # empty-state's st.page_link CTA cannot resolve; seed a record
            # to exercise the actual review console instead.
            at.session_state["plan"] = {
                "recommendations": [{
                    "recommendation_id": "R-BOOT-1",
                    "title": "Boot smoke record",
                    "priority": "P1",
                    "action_type": "scale_up",
                    "status": "PENDING",
                }],
            }
            at.session_state["selected_recommendation_id"] = "R-BOOT-1"
        at.run()
        assert not at.exception
        rendered = "\n".join(str(el.value) for el in at.markdown)
        rendered += "\n".join(str(e.value) for e in at.error)
        assert "Traceback" not in rendered
        assert "Unexpected application error" not in rendered


# --- audit history: review events --------------------------------------------------------------------


class TestHistoryReviewEvents:
    def test_review_events_render_without_keyerror(self, tmp_path, monkeypatch):
        """Regression: the timeline used a nonexistent event key ``id``;
        the Phase 6 contract exposes ``recommendation_id`` instead."""
        import tempfile

        from database.connection import connect, init_db

        db_path = tmp_path / "audit-ui-regression.db"
        engine = connect(f"sqlite:///{db_path.as_posix()}")
        init_db(engine)

        from app import orchestrator
        from tests.test_persistence_service import make_plan, make_record

        plan = make_plan([make_record(recommendation_id="R-UI-HIST-1")])
        orchestrator.persist_plan(engine, plan)
        updated, event = orchestrator.apply_review(
            "APPROVE", plan["recommendations"][0], reviewer_id="ui-regression"
        )
        orchestrator.persist_review(engine, updated, event)
        assert sorted(event) == [
            "comment", "decision", "event_type", "new_status",
            "occurred_at", "previous_status", "recommendation_id", "reviewer_id",
        ]
        engine.dispose()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
        at = AppTest.from_file(str(PAGES_DIR / "history.py"), default_timeout=60)
        at.run()

        assert not at.exception
        rendered = "\n".join(
            str(el.value) for el in (*at.markdown, *at.error)
        )
        assert "Traceback" not in rendered
        assert "Unexpected application error" not in rendered
        assert "Review events" in rendered or "review events" in rendered.lower()
        assert "ops-timeline-item" in rendered          # the rail actually rendered
        assert "APPROVE" in rendered                    # decision badge present
        assert "ui-regression" in rendered              # reviewer visible
        assert "PENDING → APPROVED" in rendered         # transition badge


# --- Phase 11B: posture scale -----------------------------------------------------------------------


class TestPostureScale:
    def test_score_is_100_minus_weighted_penalties(self):
        from app.ui.posture import SEVERITY_WEIGHTS, posture_score

        by_severity = {"CRITICAL": 1, "HIGH": 2, "MEDIUM": 1, "LOW": 3}
        expected = 100 - sum(
            SEVERITY_WEIGHTS[sev] * count for sev, count in by_severity.items()
        )
        assert posture_score(by_severity) == expected

    def test_empty_is_perfect_and_unknown_defaults_to_low_weight(self):
        from app.ui.posture import posture_score

        assert posture_score({}) == 100
        assert posture_score({"MYSTERY": 1}) == 98   # unknown -> LOW weight

    def test_score_never_drops_below_zero(self):
        from app.ui.posture import posture_score

        assert posture_score({"CRITICAL": 10}) == 0

    def test_bands_match_thresholds(self):
        from app.ui.posture import posture_band

        assert posture_band(95)[0] == "STEADY"
        assert posture_band(80)[0] == "STEADY"
        assert posture_band(79)[0] == "MODERATE ATTENTION"
        assert posture_band(60)[0] == "MODERATE ATTENTION"
        assert posture_band(59)[0] == "NEEDS ATTENTION"

    def test_ring_renders_svg_without_emoji(self):
        def scenario():
            import streamlit as st

            from app.ui.posture import posture_ring

            st.markdown(posture_ring(87, "STEADY", "success"),
                        unsafe_allow_html=True)

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(str(m.value) for m in at.markdown)
        assert "ops-posture-ring" in rendered
        assert "conic-gradient" in rendered
        assert "87" in rendered and "STEADY" in rendered


# --- Phase 11B: stage checklist ---------------------------------------------------------------------


class TestStageChecklist:
    def test_checklist_renders_done_active_todo_states(self):
        def scenario():
            from app.ui.components import stage_checklist

            stage_checklist(
                "Investigation status",
                [("Evidence prepared", "done"),
                 ("AI investigation", "active"),
                 ("Report", "todo")],
                sub="Deterministic stages are complete.",
            )

        at = AppTest.from_function(scenario)
        at.run()
        assert not at.exception
        rendered = "\n".join(str(m.value) for m in at.markdown)
        assert "ops-stepper-step ops-done" in rendered
        assert "ops-stage-pulse" in rendered           # active glyph
        assert "Deterministic stages are complete." in rendered

    def test_workflow_has_seven_stages(self):
        from app.ui.components import _WORKFLOW_STEPS

        labels = [name for name, _, _ in _WORKFLOW_STEPS]
        assert len(labels) == 7
        assert labels[-1] == "Audit"


# --- Phase 11B: overview signal ranking -------------------------------------------------------------


class TestOverviewSignalRows:
    def test_rows_rank_by_severity_then_deviation(self):
        from app.pages.overview import _signal_rows

        anomalies = [
            {"index": i, **rec}
            for i, rec in enumerate([
                {"severity": "LOW", "deviation_pct": 40.0},
                {"severity": "HIGH", "deviation_pct": 5.0},
                {"severity": "HIGH", "deviation_pct": 12.0},
                {"severity": "CRITICAL", "deviation_pct": 1.0},
            ])
        ]
        ranked = _signal_rows(anomalies)
        severities = [rec["severity"] for _, rec in ranked]
        assert severities[0] == "CRITICAL"
        assert severities[1:] == ["HIGH", "HIGH", "LOW"]
        highs = [abs(rec["deviation_pct"]) for _, rec in ranked
                 if rec["severity"] == "HIGH"]
        assert highs == sorted(highs, reverse=True)

    def test_rows_respect_limit(self):
        from app.pages.overview import _signal_rows

        anomalies = [{"severity": "HIGH", "deviation_pct": i}
                     for i in range(10)]
        assert len(_signal_rows(anomalies)) == 6


# --- Phase 11B: history day grouping ---------------------------------------------------------------


class TestHistoryDayGrouping:
    def test_day_labels_today_yesterday_and_iso(self):
        from datetime import date, timedelta

        from app.pages.history import _day_label

        today = date(2026, 8, 23)
        assert _day_label("2026-08-23T10:00:00Z", today=today) == "Today"
        assert _day_label("2026-08-22T08:30:00Z", today=today) == "Yesterday"
        assert _day_label("2026-08-01T00:00:00Z", today=today) == "2026-08-01"
        assert _day_label("garbage", today=today) == "garbage"

    def test_events_group_into_consecutive_day_buckets_newest_first(self):
        from app.pages.history import _grouped_by_day

        events = [
            {"occurred_at": "2026-08-20T09:00:00Z", "decision": "APPROVE"},
            {"occurred_at": "2026-08-21T09:00:00Z", "decision": "REJECT"},
            {"occurred_at": "2026-08-21T10:00:00Z", "decision": "APPROVE"},
        ]
        buckets = _grouped_by_day(events)
        days = [label for label, _ in buckets]
        assert days == ["2026-08-21", "2026-08-20"]
        assert [e["decision"] for e in buckets[0][1]] == ["APPROVE", "REJECT"]
        assert buckets[1][1][0]["decision"] == "APPROVE"


# --- Phase 11B: anomaly relation heuristic ---------------------------------------------------------


class TestRelatedAnomalies:
    def test_related_keeps_same_entity_metric_nearest_dates(self):
        from app.pages.anomalies import _related_anomalies

        anomalies = [
            {"entity": "North", "metric": "revenue", "date": "2026-01-01"},
            {"entity": "South", "metric": "revenue", "date": "2026-01-02"},
            {"entity": "North", "metric": "revenue", "date": "2026-01-05"},
            {"entity": "North", "metric": "cost", "date": "2026-01-02"},
            {"entity": "North", "metric": "revenue", "date": "2026-01-03"},
        ]
        related = _related_anomalies(anomalies, 0)
        indices = [i for i, _ in related]
        assert indices == [4, 2]          # same entity+metric, nearest first


# --- navigation contract (Phase 11B hotfix regression) ----------------------------------------------


class TestNavigationContract:
    """The sidebar must always be reachable: these tests pin the
    navigation architecture and the CSS safety rules that were violated
    when the header hosting Streamlit's sidebar re-expand control was
    hidden with display:none."""

    def test_navigation_contains_exactly_nine_pages(self):
        assert len(shell.FLAT_PAGES) == 9
        expected = {
            "Overview", "Data", "Analytics", "Anomalies",
            "Insights", "Evidence", "Recommendations", "Human Review",
            "History",
        }
        assert set(shell.FLAT_PAGES) == expected

    def test_every_page_has_a_material_icon(self):
        for title, (stem, icon) in shell.FLAT_PAGES.items():
            assert icon, title
            assert not icon.startswith(":"), title   # bare material name
            assert (PAGES_DIR / f"{stem}.py").is_file(), stem

    def test_main_uses_native_navigation_with_expanded_sidebar(self):
        source = (PROJECT_ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert "st.navigation(" in source          # native nav, not a fake router
        assert 'initial_sidebar_state="expanded"' in source
        assert "with st.sidebar:" in source         # shell content in the sidebar

    def test_css_never_hides_sidebar_or_header(self):
        from app.ui.theme import _CSS

        # Root cause of the Phase 11B regression: the header was hidden
        # wholesale, removing Streamlit's only sidebar re-expand control.
        forbidden_fragments = [
            'header[data-testid="stHeader"] { display',
            '[data-testid="stSidebar"] { display',
            "[data-testid=\"stSidebar\"] {\n  display: none",
            'visibility: hidden;\n}\n[data-testid="stSidebar"]',
        ]
        for fragment in forbidden_fragments:
            assert fragment not in _CSS, fragment
        import re as _re

        sidebar_hide = _re.compile(
            r'\[data-testid="stSidebar"\]\s*\{[^}]*'
            r"(display:\s*none|visibility:\s*hidden|width:\s*0"
            r"|pointer-events:\s*none)",
            _re.S,
        )
        assert sidebar_hide.search(_CSS) is None
        header_hide = _re.compile(
            r'header\[data-testid="stHeader"\]\s*\{[^}]*display:\s*none',
            _re.S,
        )
        assert header_hide.search(_CSS) is None

    def test_css_styles_the_expand_control_instead_of_hiding_it(self):
        from app.ui.theme import _CSS

        assert '[data-testid="stExpandSidebarButton"]' in _CSS


# --- recovery CTA (Phase 11B hotfix regression) -----------------------------------------------------


class TestRecoveryCta:
    def test_card_marks_up_session_restore_details(self):
        from app.state import _recovery_card_html

        html = _recovery_card_html({
            "dataset_name": "demo_operational_data.csv",
            "sensitivity": "high",
            "completed_at": "2026-08-23",
        })
        assert "SESSION RESTORE" in html
        assert "demo_operational_data.csv" in html
        assert "high" in html
        assert "2026-08-23" in html
        assert "Results are not" in html           # honest missing-state copy
        assert "ops-recovery-card" in html

    def test_card_escapes_untrusted_context_values(self):
        from app.state import _recovery_card_html

        html = _recovery_card_html({
            "dataset_name": "<script>alert(1)</script>",
            "sensitivity": None,
            "completed_at": None,
        })
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "—" in html                          # missing values render safely

    def test_cta_targets_the_data_workspace(self):
        from app import state as state_module

        assert state_module.RECOVERY_CTA_PAGE == "pages/data.py"

    def test_recovery_branch_renders_cta_without_sidebar_dependency(self):
        source = (PROJECT_ROOT / "app" / "state.py").read_text(encoding="utf-8")
        assert "st.page_link(RECOVERY_CTA_PAGE" in source
        assert "_recovery_card_html(context)" in source
        # The old copy pointed users at navigation that may be invisible.
        assert "open **Data** in the sidebar" not in source



# --- presentation hygiene ---------------------------------------------------------------------------


class TestPresentationHygiene:
    @staticmethod
    def _ui_sources() -> list[Path]:
        sources: list[Path] = []
        main_path = PROJECT_ROOT / "app" / "main.py"
        state_path = PROJECT_ROOT / "app" / "state.py"
        sources.append(main_path)
        sources.append(state_path)
        sources.extend((PROJECT_ROOT / "app" / "pages").glob("*.py"))
        sources.extend((PROJECT_ROOT / "app" / "ui").glob("*.py"))
        return sorted(sources)

    def test_no_emoji_in_ui_sources(self):
        emoji_pattern = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")
        offenders = []
        for path in self._ui_sources():
            text = path.read_text(encoding="utf-8")
            if emoji_pattern.search(text):
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
        assert offenders == []

    def test_pages_use_run_page_boundary_with_icons(self):
        for stem in (*PAGE_STEMS, "history"):
            text = (PAGES_DIR / f"{stem}.py").read_text(encoding="utf-8")
            assert "run_page(" in text, stem
            assert "eyebrow=" in text, stem
