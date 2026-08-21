"""Tests for the deterministic insight engine (Phase 3B slice).

Covers ``analyze_metric_contexts``, ``explain_anomalies``,
``group_related_anomalies`` and ``build_insight_report`` against the
documented Phase 3B policies: exact output schemas, numeric factor
alignment rules, localization verdicts, peer profiles, trend context,
correlation evidence bands, greedy grouping, validation errors,
determinism, and caller-input immutability. Mathematical expectations
are recomputed independently inside the tests (via ``statistics``
rather than the service's numpy path) wherever practical.
"""

from __future__ import annotations

import copy
import statistics
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.constants import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
)
from core.exceptions import DataValidationError
from services.anomaly_service import (
    MIN_HISTORY_DAYS,
    SUPPORTED_METRICS,
    Z_SCORE_CAP,
    detect_anomalies,
    summarize_anomalies,
)
from services.data_service import load_dataset
from services.insight_service import (
    CONCENTRATED_CUMULATIVE_SHARE_PCT,
    CORRELATION_MODERATE_R,
    CORRELATION_STRONG_R,
    FACTOR_Z_THRESHOLD,
    GROUP_DATE_WINDOW_DAYS,
    LEAD_TIME_GAP_PCT_THRESHOLD,
    LOCALIZED_SHARE_PCT,
    MAX_CONTRIBUTORS,
    MAX_CORRELATIONS_PER_INSIGHT,
    MIN_CORRELATION_POINTS,
    TREND_WINDOW_DAYS,
    _correlation_strength,
    analyze_metric_contexts,
    build_insight_report,
    explain_anomalies,
    group_related_anomalies,
)

METRICS_SORTED: list[str] = sorted(SUPPORTED_METRICS)
VALID_SEVERITIES: set[str] = {
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
}

EXPECTED_INSIGHT_KEYS: set[str] = {
    "type",
    "anomaly_index",
    "scope",
    "metric",
    "entity",
    "date",
    "severity",
    "headline",
    "factors",
    "localization",
    "peer_profile",
    "trend",
    "correlations",
    "related_anomaly_indices",
}
EXPECTED_FACTOR_KEYS: set[str] = {"factor", "direction", "strength", "evidence"}
EXPECTED_LOCALIZATION_KEYS: set[str] = {"dimension", "verdict", "contributors"}
EXPECTED_CONTRIBUTOR_KEYS: set[str] = {"entity", "share_pct"}
EXPECTED_PEER_KEYS: set[str] = {"profile", "ratios", "gaps_pct"}
EXPECTED_PEER_RATIO_KEYS: set[str] = {
    "metric_vs_peer_median",
    "units_vs_peer_median",
    "cost_vs_peer_median",
}
EXPECTED_PEER_GAP_KEYS: set[str] = {
    "average_lead_time_days",
    "profit_margin_pct_points",
}
EXPECTED_TREND_KEYS: set[str] = {"direction", "change_pct"}
EXPECTED_CORRELATION_ITEM_KEYS: set[str] = {"pair", "r", "strength"}

EXPECTED_GROUP_KEYS: set[str] = {
    "group_id",
    "severity",
    "max_score",
    "start_date",
    "end_date",
    "member_indices",
    "member_count",
    "shared_metrics",
    "shared_entities",
    "headline",
}

def date_at(offset: int, start: str = "2024-01-01") -> str:
    return (pd.Timestamp(start) + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")


CANDIDATE_DATE: str = date_at(MIN_HISTORY_DAYS)
BASELINE_EIGHT: list[float] = [100.0, 102.0, 98.0, 101.0, 99.0, 103.0, 97.0, 110.0]


# --- Frame builders ----------------------------------------------------------


def make_daily_frame(
    values: list[float], *, metric: str = "revenue", start: str = "2024-01-01"
) -> pd.DataFrame:
    """One row per day so daily totals equal the given values."""
    count = len(values)
    frame = pd.DataFrame(
        {
            "date": [date_at(offset, start) for offset in range(count)],
            "region": ["North"] * count,
            "product": ["A"] * count,
            "units_sold": [10] * count,
            "revenue": [100.0] * count,
            "cost": [50.0] * count,
            "lead_time_days": [5] * count,
        }
    )
    frame[metric] = list(values)
    return frame


def make_schedule_frame(values: list[float]) -> pd.DataFrame:
    return make_daily_frame(values)


FACTOR_BASELINES: dict[str, list[float]] = {
    "revenue": [100.0, 102.0, 98.0, 101.0, 99.0, 103.0, 97.0],
    "units_sold": [10.0, 12.0, 8.0, 11.0, 9.0, 13.0, 7.0],
    "cost": [50.0, 52.0, 48.0, 51.0, 49.0, 53.0, 47.0],
    "lead_time_days": [5.0, 6.0, 4.0, 5.0, 5.0, 6.0, 4.0],
}


def make_factor_frame(candidate: dict[str, float]) -> pd.DataFrame:
    """Eight-day single-combo frame with wiggly baselines for all metrics."""
    rows: list[dict[str, object]] = []
    for offset in range(8):
        row: dict[str, object] = {
            "date": date_at(offset),
            "region": "North",
            "product": "A",
        }
        for metric, baseline in FACTOR_BASELINES.items():
            row[metric] = candidate[metric] if offset == 7 else baseline[offset]
        rows.append(row)
    return pd.DataFrame(rows)


def make_grid_frame(
    combos: list[tuple[str, str]],
    days: int,
    *,
    base_revenue: float = 10.0,
    overrides: dict[tuple[str, str], float] | None = None,
    override_offset: int | None = None,
    extra_rows: list[dict[str, object]] | None = None,
) -> pd.DataFrame:
    """Multi-entity grid; every combo gets ``base_revenue`` per day."""
    overrides = overrides or {}
    if override_offset is None:
        override_offset = days - 1
    rows: list[dict[str, object]] = []
    for offset in range(days):
        for region, product in combos:
            revenue = base_revenue
            if offset == override_offset and (region, product) in overrides:
                revenue = overrides[(region, product)]
            rows.append(
                {
                    "date": date_at(offset),
                    "region": region,
                    "product": product,
                    "units_sold": 10,
                    "revenue": revenue,
                    "cost": 5.0,
                    "lead_time_days": 5,
                }
            )
    if extra_rows:
        rows.extend(extra_rows)
    return pd.DataFrame(rows)


def make_entity_frame(
    profiles: dict[str, dict[str, float]],
    *,
    dimension: str = "region",
    entity_label: str = "R",
    days: int = 8,
) -> pd.DataFrame:
    """Constant per-day profile per entity across the full period."""
    rows: list[dict[str, object]] = []
    for offset in range(days):
        for index, (entity, profile) in enumerate(sorted(profiles.items())):
            name = entity if dimension == "region" else f"{entity_label}{index + 1}"
            region = name if dimension == "region" else entity_label
            product = name if dimension == "product" else "P"
            rows.append(
                {
                    "date": date_at(offset),
                    "region": region,
                    "product": product,
                    "units_sold": profile["units"],
                    "revenue": profile["revenue"],
                    "cost": profile["cost"],
                    "lead_time_days": profile["lead"],
                }
            )
    return pd.DataFrame(rows)


def make_record(**overrides: object) -> dict[str, object]:
    """Minimal but schema-complete daily-scope anomaly record."""
    record: dict[str, object] = {
        "type": "daily_spike",
        "scope": "daily",
        "metric": "revenue",
        "entity": None,
        "date": CANDIDATE_DATE,
        "value": 115.0,
        "expected_value": 100.0,
        "deviation_pct": 15.0,
        "score": 77.16,
        "severity": SEVERITY_HIGH,
        "rule": "zscore_rolling",
        "details": {"z": 4.63, "baseline_std": 2.16, "threshold": 3.0},
    }
    record.update(overrides)
    return record


def assert_no_nan_or_inf(value: object) -> None:
    """Every numeric leaf reachable from ``value`` must be finite."""
    if isinstance(value, dict):
        for child in value.values():
            assert_no_nan_or_inf(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            assert_no_nan_or_inf(child)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        assert np.isfinite(value), f"Non-finite value found: {value!r}"


@pytest.fixture(scope="module")
def demo_df() -> pd.DataFrame:
    return load_dataset("demo_operational_data.csv")


# --- Tuning constants --------------------------------------------------------


class TestTuningConstants:
    def test_grouping_window_is_one_day(self) -> None:
        assert GROUP_DATE_WINDOW_DAYS == 1

    def test_localization_thresholds(self) -> None:
        assert LOCALIZED_SHARE_PCT == 60.0
        assert CONCENTRATED_CUMULATIVE_SHARE_PCT == 80.0
        assert MAX_CONTRIBUTORS == 3

    def test_factor_and_profile_thresholds(self) -> None:
        assert FACTOR_Z_THRESHOLD == 2.0
        assert LEAD_TIME_GAP_PCT_THRESHOLD == 25.0

    def test_trend_and_correlation_limits(self) -> None:
        assert TREND_WINDOW_DAYS == 14
        assert MIN_CORRELATION_POINTS == 8
        assert CORRELATION_STRONG_R == 0.7
        assert CORRELATION_MODERATE_R == 0.4
        assert MAX_CORRELATIONS_PER_INSIGHT == 3


# --- analyze_metric_contexts --------------------------------------------------


class TestContextSchema:
    @pytest.fixture()
    def context(self) -> dict[str, object]:
        return analyze_metric_contexts(make_daily_frame(BASELINE_EIGHT))

    def test_exact_top_level_keys(self, context: dict[str, object]) -> None:
        assert set(context.keys()) == {
            "dates",
            "daily_totals",
            "z_scores_by_date",
            "correlations",
        }

    def test_dates_are_ascending_iso_strings(self, context: dict[str, object]) -> None:
        dates = context["dates"]  # type: ignore[index]
        assert all(isinstance(item, str) for item in dates)  # type: ignore[union-attr]
        assert dates == sorted(dates)  # type: ignore[type-var,union-attr]
        assert dates[0] == date_at(0)  # type: ignore[index]

    def test_daily_totals_cover_all_metrics_sorted(self, context: dict[str, object]) -> None:
        totals = context["daily_totals"]  # type: ignore[index]
        assert list(totals.keys()) == METRICS_SORTED  # type: ignore[union-attr]
        for values in totals.values():  # type: ignore[union-attr]
            assert len(values) == len(context["dates"])  # type: ignore[arg-type]

    def test_daily_totals_match_independent_sums(self, context: dict[str, object]) -> None:
        expected = {date_at(i): round(BASELINE_EIGHT[i], 2) for i in range(len(BASELINE_EIGHT))}
        actual = context["daily_totals"]["revenue"]  # type: ignore[index]
        assert [expected[date] for date in context["dates"]] == actual  # type: ignore[index,union-attr]

    def test_types_are_python_natives(self, context: dict[str, object]) -> None:
        assert all(isinstance(item, str) for item in context["dates"])  # type: ignore[arg-type,union-attr]
        sample = context["daily_totals"]["revenue"][0]  # type: ignore[index]
        assert isinstance(sample, float)


class TestContextZScores:
    def test_first_min_history_dates_have_no_scores(self) -> None:
        context = analyze_metric_contexts(make_daily_frame(BASELINE_EIGHT))
        z_scores = context["z_scores_by_date"]  # type: ignore[index]
        early = {date_at(offset) for offset in range(MIN_HISTORY_DAYS)}
        assert not early & set(z_scores.keys())  # type: ignore[arg-type]
        assert set(z_scores.keys()) == {CANDIDATE_DATE}  # type: ignore[arg-type]

    def test_z_score_matches_independent_statistics_computation(self) -> None:
        baseline = [100.0, 102.0, 98.0, 101.0, 99.0, 103.0, 97.0]
        frame = make_daily_frame(baseline + [110.0])
        context = analyze_metric_contexts(frame)
        expected = round((110.0 - statistics.mean(baseline)) / statistics.stdev(baseline), 2)
        actual = context["z_scores_by_date"][CANDIDATE_DATE]["revenue"]  # type: ignore[index]
        assert actual == pytest.approx(expected, abs=1e-9)

    def test_sliding_window_uses_previous_seven_observed_points(self) -> None:
        baseline = [100.0, 102.0, 98.0, 101.0, 99.0, 103.0, 97.0]
        window = baseline[1:] + [110.0]
        frame = make_daily_frame(baseline + [110.0, 115.0])
        context = analyze_metric_contexts(frame)
        z_scores = context["z_scores_by_date"]  # type: ignore[index]
        expected_first = round((110.0 - statistics.mean(baseline)) / statistics.stdev(baseline), 2)
        expected_second = round((115.0 - statistics.mean(window)) / statistics.stdev(window), 2)
        assert z_scores[date_at(7)]["revenue"] == pytest.approx(expected_first, abs=1e-9)  # type: ignore[index]
        assert z_scores[date_at(8)]["revenue"] == pytest.approx(expected_second, abs=1e-9)  # type: ignore[index]

    def test_zero_variance_window_yields_none(self) -> None:
        frame = make_daily_frame([100.0] * 8)
        context = analyze_metric_contexts(frame)
        row = context["z_scores_by_date"][CANDIDATE_DATE]  # type: ignore[index]
        assert all(value is None for value in row.values())  # type: ignore[union-attr]

    def test_every_metric_has_an_entry_per_scored_date(self) -> None:
        frame = make_daily_frame([100.0, 102.0, 98.0, 101.0, 99.0, 103.0, 97.0, 110.0])
        context = analyze_metric_contexts(frame)
        row = context["z_scores_by_date"][CANDIDATE_DATE]  # type: ignore[index]
        assert list(row.keys()) == METRICS_SORTED  # type: ignore[union-attr]


class TestContextCorrelations:
    def test_pairwise_pairs_sorted_by_names(self) -> None:
        frame = make_schedule_frame([100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0])
        correlations = analyze_metric_contexts(frame)["correlations"]  # type: ignore[index]
        pairs = [(item["metric_a"], item["metric_b"]) for item in correlations]  # type: ignore[union-attr,index]
        expected = sorted(
            (a, b) for index, a in enumerate(METRICS_SORTED) for b in METRICS_SORTED[index + 1 :]
        )
        assert pairs == expected

    def test_correlation_item_schema_and_points(self) -> None:
        frame = make_schedule_frame([100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0])
        correlations = analyze_metric_contexts(frame)["correlations"]  # type: ignore[index]
        assert len(correlations) == 6  # type: ignore[arg-type]
        for item in correlations:  # type: ignore[union-attr]
            assert set(item.keys()) == {
                "metric_a",
                "metric_b",
                "r",
                "strength",
                "points",
            }  # type: ignore[union-attr]
            assert item["points"] == 8  # type: ignore[union-attr,index]
            assert item["strength"] in {"strong", "moderate", "none"}  # type: ignore[union-attr,index]

    def test_perfect_positive_linear_series_is_strong(self) -> None:
        revenue = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0]
        frame = make_schedule_frame(revenue)
        frame["cost"] = [value / 2 for value in revenue]
        correlations = analyze_metric_contexts(frame)["correlations"]  # type: ignore[index]
        pair = next(
            item
            for item in correlations  # type: ignore[union-attr]
            if {item["metric_a"], item["metric_b"]} == {"cost", "revenue"}  # type: ignore[union-attr,index]
        )
        assert pair["r"] == pytest.approx(1.0, abs=1e-9)  # type: ignore[union-attr,index]
        assert pair["strength"] == "strong"  # type: ignore[union-attr,index]

    def test_perfect_inverse_series_is_strong_negative(self) -> None:
        revenue = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0]
        frame = make_schedule_frame(revenue)
        frame["units_sold"] = [200.0 - value for value in revenue]
        correlations = analyze_metric_contexts(frame)["correlations"]  # type: ignore[index]
        pair = next(
            item
            for item in correlations  # type: ignore[union-attr]
            if {item["metric_a"], item["metric_b"]} == {"revenue", "units_sold"}  # type: ignore[union-attr,index]
        )
        assert pair["r"] == pytest.approx(-1.0, abs=1e-9)  # type: ignore[union-attr,index]
        assert pair["strength"] == "strong"  # type: ignore[union-attr,index]

    def test_zero_variance_series_yield_zero_r(self) -> None:
        frame = make_daily_frame([100.0] * 8)
        correlations = analyze_metric_contexts(frame)["correlations"]  # type: ignore[index]
        for item in correlations:  # type: ignore[union-attr]
            assert item["r"] == 0.0  # type: ignore[union-attr,index]
            assert item["strength"] == "none"  # type: ignore[union-attr,index]

    def test_fewer_than_min_points_yield_no_correlations(self) -> None:
        frame = make_daily_frame([100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0])
        assert analyze_metric_contexts(frame)["correlations"] == []  # type: ignore[index]

    @pytest.mark.parametrize(
        ("r", "expected"),
        [
            (1.0, "strong"),
            (CORRELATION_STRONG_R, "strong"),
            (-0.9, "strong"),
            (0.69, "moderate"),
            (CORRELATION_MODERATE_R, "moderate"),
            (-0.5, "moderate"),
            (0.39, "none"),
            (0.0, "none"),
            (-CORRELATION_MODERATE_R - 0.01, "moderate"),
        ],
    )
    def test_strength_band_mapping(self, r: float, expected: str) -> None:
        assert _correlation_strength(r) == expected


class TestContextValidationAndImmutability:
    def test_non_dataframe_raises(self) -> None:
        for bad_input in [{}, [], None, "csv", 42]:
            with pytest.raises(DataValidationError):
                analyze_metric_contexts(bad_input)  # type: ignore[arg-type]

    def test_missing_required_column_raises(self) -> None:
        frame = make_daily_frame([100.0] * 8).drop(columns=["cost"])
        with pytest.raises(DataValidationError):
            analyze_metric_contexts(frame)

    def test_empty_dataframe_raises(self) -> None:
        with pytest.raises(DataValidationError):
            analyze_metric_contexts(make_daily_frame([100.0]).iloc[0:0])

    def test_non_finite_values_raise(self) -> None:
        frame = make_daily_frame([100.0] * 8)
        frame.loc[3, "revenue"] = np.inf
        with pytest.raises(DataValidationError):
            analyze_metric_contexts(frame)

    def test_caller_dataframe_never_mutated(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 20.0, "cost": 55.0, "lead_time_days": 5.0}
        )
        snapshot = copy.deepcopy(frame)
        analyze_metric_contexts(frame)
        pd.testing.assert_frame_equal(frame, snapshot)

    def test_repeated_calls_identical(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 20.0, "cost": 55.0, "lead_time_days": 5.0}
        )
        assert analyze_metric_contexts(frame) == analyze_metric_contexts(frame)

    def test_shuffled_rows_produce_identical_output(self) -> None:
        frame = make_grid_frame(
            [("North", "A"), ("South", "B")], 8, overrides={("North", "A"): 40.0}
        )
        shuffled = frame.sample(frac=1.0, random_state=7).reset_index(drop=True)
        assert analyze_metric_contexts(frame) == analyze_metric_contexts(shuffled)


# --- explain_anomalies: schema and ordering -----------------------------------


class TestExplainSchemaAndOrder:
    def test_empty_anomaly_list_yields_no_insights(self) -> None:
        frame = make_daily_frame([100.0] * 8)
        assert explain_anomalies(frame, []) == {"insights": []}

    def test_one_insight_per_record_in_input_order(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 20.0, "cost": 55.0, "lead_time_days": 5.0}
        )
        records = [
            make_record(),
            make_record(scope="region", type="entity_outlier_high", entity="North"),
            make_record(metric="cost", type="daily_drop", deviation_pct=-12.0),
        ]
        shuffled = [records[2], records[0], records[1]]
        result = explain_anomalies(frame, shuffled)["insights"]  # type: ignore[index]
        assert [insight["anomaly_index"] for insight in result] == [0, 1, 2]
        assert result[0]["metric"] == "cost"
        assert result[0]["scope"] == "daily"
        assert result[2]["scope"] == "region"
        assert result[2]["entity"] == "North"

    def test_exact_insight_keys(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 20.0, "cost": 55.0, "lead_time_days": 5.0}
        )
        insight = explain_anomalies(frame, [make_record()])["insights"][0]  # type: ignore[index]
        assert set(insight.keys()) == EXPECTED_INSIGHT_KEYS

    def test_passthrough_fields_mirror_records(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 20.0, "cost": 55.0, "lead_time_days": 5.0}
        )
        records = [
            make_record(severity=SEVERITY_CRITICAL),
            make_record(
                scope="region",
                type="entity_outlier_low",
                entity="North",
                date=None,
                severity=SEVERITY_LOW,
            ),
        ]
        insights = explain_anomalies(frame, records)["insights"]  # type: ignore[index]
        assert insights[0]["severity"] == SEVERITY_CRITICAL  # type: ignore[index]
        assert insights[1]["scope"] == "region"  # type: ignore[index]
        assert insights[1]["entity"] == "North"  # type: ignore[index]
        assert insights[1]["date"] is None  # type: ignore[index]
        assert insights[1]["severity"] == SEVERITY_LOW  # type: ignore[index]
        assert all(insight["type"] == "insight" for insight in insights)  # type: ignore[union-attr,index]


# --- explain_anomalies: factor rules ------------------------------------------


class TestFactorRules:
    def test_aligned_supporting_metrics_vote_with_labels_and_strength(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 20.0, "cost": 55.0, "lead_time_days": 5.0}
        )
        factors = explain_anomalies(frame, [make_record(deviation_pct=10.0)])["insights"][0][  # type: ignore[index]
            "factors"
        ]
        units_mean = statistics.mean(FACTOR_BASELINES["units_sold"])
        units_std = statistics.stdev(FACTOR_BASELINES["units_sold"])
        cost_mean = statistics.mean(FACTOR_BASELINES["cost"])
        cost_std = statistics.stdev(FACTOR_BASELINES["cost"])
        z_units = (20.0 - units_mean) / units_std
        z_cost = (55.0 - cost_mean) / cost_std

        assert [item["factor"] for item in factors] == ["volume", "cost"]
        assert factors[0]["strength"] == round(min(1.0, abs(z_units) / Z_SCORE_CAP), 2)  # type: ignore[index]
        assert factors[1]["strength"] == round(min(1.0, abs(z_cost) / Z_SCORE_CAP), 2)  # type: ignore[index]
        assert factors[0]["direction"] == "increase"  # type: ignore[index]
        assert factors[0]["evidence"] == f"units_sold z={round(z_units, 2)} on {CANDIDATE_DATE}"  # type: ignore[index]
        assert factors[1]["evidence"] == f"cost z={round(z_cost, 2)} on {CANDIDATE_DATE}"  # type: ignore[index]
        for item in factors:
            assert set(item.keys()) == EXPECTED_FACTOR_KEYS

    def test_factors_sorted_by_strength_then_name(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 200.0, "cost": 500.0, "lead_time_days": 5.0}
        )
        factors = explain_anomalies(frame, [make_record(deviation_pct=10.0)])["insights"][0][  # type: ignore[index]
            "factors"
        ]
        assert [item["factor"] for item in factors] == ["cost", "volume"]
        assert all(item["strength"] == 1.0 for item in factors)  # type: ignore[union-attr]

    def test_drop_direction_requires_matching_sign(self) -> None:
        frame = make_factor_frame(
            {"revenue": 90.0, "units_sold": 2.0, "cost": 46.0, "lead_time_days": 5.0}
        )
        factors = explain_anomalies(
            frame, [make_record(type="daily_drop", deviation_pct=-10.0)]
        )["insights"][0]["factors"]  # type: ignore[index]
        units_std = statistics.stdev(FACTOR_BASELINES["units_sold"])
        z_units = (2.0 - statistics.mean(FACTOR_BASELINES["units_sold"])) / units_std

        assert len(factors) == 1
        assert factors[0]["factor"] == "volume"  # type: ignore[index]
        assert factors[0]["direction"] == "decrease"  # type: ignore[index]
        assert factors[0]["strength"] == round(min(1.0, abs(z_units) / Z_SCORE_CAP), 2)  # type: ignore[index]

    def test_sign_mismatch_produces_unattributed(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 2.0, "cost": 50.0, "lead_time_days": 5.0}
        )
        factors = explain_anomalies(frame, [make_record(deviation_pct=10.0)])["insights"][0][  # type: ignore[index]
            "factors"
        ]
        assert factors == [
            {
                "factor": "unattributed",
                "direction": "none",
                "strength": 0.0,
                "evidence": "no metric satisfied alignment rules on this date",
            }
        ]

    def test_sub_threshold_support_is_not_aligned(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 10.5, "cost": 51.0, "lead_time_days": 5.0}
        )
        factors = explain_anomalies(frame, [make_record(deviation_pct=10.0)])["insights"][0][  # type: ignore[index]
            "factors"
        ]
        assert [item["factor"] for item in factors] == ["price_margin"]

    def test_price_margin_for_revenue_without_unit_support(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 11.0, "cost": 50.0, "lead_time_days": 5.0}
        )
        factors = explain_anomalies(frame, [make_record(deviation_pct=10.0)])["insights"][0][  # type: ignore[index]
            "factors"
        ]
        units_std = statistics.stdev(FACTOR_BASELINES["units_sold"])
        z_units = (11.0 - statistics.mean(FACTOR_BASELINES["units_sold"])) / units_std
        flatness = max(0.0, min(1.0, 1.0 - abs(z_units) / FACTOR_Z_THRESHOLD))

        assert len(factors) == 1
        assert factors[0] == {
            "factor": "price_margin",
            "direction": "increase",
            "strength": round(flatness, 2),
            "evidence": (
                f"units_sold z={round(z_units, 2)} below +/-{FACTOR_Z_THRESHOLD} "
                f"while revenue moved on {CANDIDATE_DATE}"
            ),
        }

    def test_non_revenue_target_never_gets_price_margin(self) -> None:
        frame = make_factor_frame(
            {"revenue": 101.0, "units_sold": 20.0, "cost": 50.0, "lead_time_days": 5.0}
        )
        factors = explain_anomalies(
            frame,
            [make_record(metric="units_sold", deviation_pct=100.0)],
        )["insights"][0]["factors"]  # type: ignore[index]
        assert factors == [
            {
                "factor": "unattributed",
                "direction": "none",
                "strength": 0.0,
                "evidence": "no metric satisfied alignment rules on this date",
            }
        ]

    def test_strength_saturates_at_one(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 200.0, "cost": 55.0, "lead_time_days": 5.0}
        )
        factors = explain_anomalies(frame, [make_record(deviation_pct=10.0)])["insights"][0][  # type: ignore[index]
            "factors"
        ]
        volume = next(item for item in factors if item["factor"] == "volume")
        assert volume["strength"] == 1.0

    def test_supporting_metric_at_baseline_is_never_aligned(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 10.0, "cost": 50.0, "lead_time_days": 5.0}
        )
        factors = explain_anomalies(frame, [make_record(deviation_pct=10.0)])["insights"][0][  # type: ignore[index]
            "factors"
        ]
        assert [item["factor"] for item in factors] == ["price_margin"]


# --- explain_anomalies: localization -----------------------------------------


class TestLocalization:
    def test_dominant_region_is_localized(self) -> None:
        frame = make_grid_frame(
            [("North", "A"), ("North", "B"), ("South", "A"), ("South", "B")],
            8,
            overrides={("North", "A"): 40.0, ("North", "B"): 40.0},
        )
        localization = explain_anomalies(frame, [make_record()])["insights"][0][  # type: ignore[index]
            "localization"
        ]
        assert localization == {
            "dimension": "region",
            "verdict": "localized",
            "contributors": [
                {"entity": "North", "share_pct": 100.0},
                {"entity": "South", "share_pct": 0.0},
            ],
        }

    def test_concentrated_verdict_and_contributor_cap(self) -> None:
        frame = make_grid_frame(
            [("East", "P"), ("North", "P"), ("South", "P"), ("West", "P")],
            8,
            overrides={
                ("East", "P"): 45.0,
                ("North", "P"): 45.0,
                ("South", "P"): 20.0,
                ("West", "P"): 10.0,
            },
        )
        localization = explain_anomalies(frame, [make_record()])["insights"][0][  # type: ignore[index]
            "localization"
        ]
        assert localization is not None
        assert set(localization.keys()) == EXPECTED_LOCALIZATION_KEYS
        assert localization["dimension"] == "region"
        assert localization["verdict"] == "concentrated"
        assert localization["contributors"] == [
            {"entity": "East", "share_pct": 43.75},
            {"entity": "North", "share_pct": 43.75},
            {"entity": "South", "share_pct": 12.5},
        ]

    def test_even_spread_is_distributed(self) -> None:
        frame = make_grid_frame(
            [("East", "P"), ("North", "P"), ("South", "P"), ("West", "P")],
            8,
            overrides={
                ("East", "P"): 35.0,
                ("North", "P"): 35.0,
                ("South", "P"): 35.0,
                ("West", "P"): 15.0,
            },
        )
        localization = explain_anomalies(frame, [make_record()])["insights"][0][  # type: ignore[index]
            "localization"
        ]
        assert localization is not None
        assert localization["verdict"] == "distributed"

    def test_more_concentrated_dimension_wins(self) -> None:
        frame = make_grid_frame(
            [("North", "A"), ("North", "B"), ("South", "A"), ("South", "B")],
            8,
            overrides={("North", "A"): 35.0},
        )
        localization = explain_anomalies(frame, [make_record()])["insights"][0][  # type: ignore[index]
            "localization"
        ]
        assert localization is not None
        assert localization["dimension"] == "region"
        assert localization["verdict"] == "localized"

    def test_entities_without_own_history_are_excluded(self) -> None:
        frame = make_grid_frame(
            [("East", "P"), ("North", "P"), ("South", "P"), ("West", "P")],
            8,
            overrides={
                ("East", "P"): 45.0,
                ("North", "P"): 45.0,
                ("South", "P"): 20.0,
                ("West", "P"): 10.0,
            },
            extra_rows=[
                {
                    "date": CANDIDATE_DATE,
                    "region": "Peak",
                    "product": "P",
                    "units_sold": 10,
                    "revenue": 1000.0,
                    "cost": 5.0,
                    "lead_time_days": 5,
                }
            ],
        )
        localization = explain_anomalies(frame, [make_record()])["insights"][0][  # type: ignore[index]
            "localization"
        ]
        assert localization is not None
        entities = {item["entity"] for item in localization["contributors"]}  # type: ignore[union-attr,index]
        assert entities == {"East", "North", "South"}

    def test_none_before_min_history_position(self) -> None:
        frame = make_grid_frame(
            [("North", "A"), ("South", "A")], 8, overrides={("North", "A"): 40.0}
        )
        record = make_record(date=date_at(3))
        insight = explain_anomalies(frame, [record])["insights"][0]  # type: ignore[index]
        assert insight["localization"] is None

    def test_none_when_date_absent_from_dataset(self) -> None:
        frame = make_grid_frame([("North", "A"), ("South", "A")], 8)
        record = make_record(date="2030-06-01")
        insight = explain_anomalies(frame, [record])["insights"][0]  # type: ignore[index]
        assert insight["localization"] is None

    def test_none_with_single_entity_per_dimension(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 20.0, "cost": 55.0, "lead_time_days": 5.0}
        )
        insight = explain_anomalies(frame, [make_record()])["insights"][0]  # type: ignore[index]
        assert insight["localization"] is None


# --- explain_anomalies: peer profiles ----------------------------------------


VOLUME_PROFILES: dict[str, dict[str, float]] = {
    "North": {"units": 120.0, "revenue": 1500.0, "cost": 300.0, "lead": 10.0},
    "South": {"units": 50.0, "revenue": 900.0, "cost": 250.0, "lead": 10.0},
    "East": {"units": 60.0, "revenue": 1100.0, "cost": 270.0, "lead": 8.0},
}

PRODUCT_PROFILES: dict[str, dict[str, float]] = {
    "p1": VOLUME_PROFILES["North"],
    "p2": VOLUME_PROFILES["South"],
    "p3": VOLUME_PROFILES["East"],
}


def region_record(**overrides: object) -> dict[str, object]:
    record = make_record(
        scope="region",
        type="entity_outlier_high",
        entity="North",
        date=None,
        deviation_pct=50.0,
        score=80.0,
    )
    record.update(overrides)
    return record


class TestPeerProfile:
    def test_volume_driven_profile_with_exact_ratios(self) -> None:
        frame = make_entity_frame(VOLUME_PROFILES)
        peer = explain_anomalies(frame, [region_record()])["insights"][0][  # type: ignore[index]
            "peer_profile"
        ]
        assert peer is not None
        assert set(peer.keys()) == EXPECTED_PEER_KEYS
        assert peer["profile"] == "volume_driven"
        assert peer["ratios"] == {
            "metric_vs_peer_median": 1.5,
            "units_vs_peer_median": 2.18,
            "cost_vs_peer_median": 1.15,
        }
        assert peer["gaps_pct"] == {
            "average_lead_time_days": 11.11,
            "profit_margin_pct_points": 6.16,
        }

    def test_efficiency_driven_via_cost_ratio(self) -> None:
        profiles = {
            "North": {"units": 60.0, "revenue": 1500.0, "cost": 600.0, "lead": 10.0},
            "South": {"units": 50.0, "revenue": 900.0, "cost": 250.0, "lead": 10.0},
            "East": {"units": 60.0, "revenue": 1100.0, "cost": 270.0, "lead": 8.0},
        }
        frame = make_entity_frame(profiles)
        peer = explain_anomalies(frame, [region_record()])["insights"][0]["peer_profile"]  # type: ignore[index]
        assert peer is not None
        assert peer["profile"] == "efficiency_driven"
        assert peer["ratios"]["cost_vs_peer_median"] == 2.31  # type: ignore[index,union-attr]

    def test_efficiency_driven_via_lead_time_gap(self) -> None:
        profiles = {
            "North": {"units": 60.0, "revenue": 1500.0, "cost": 300.0, "lead": 15.0},
            "South": {"units": 50.0, "revenue": 900.0, "cost": 250.0, "lead": 10.0},
            "East": {"units": 60.0, "revenue": 1100.0, "cost": 270.0, "lead": 10.0},
        }
        frame = make_entity_frame(profiles)
        peer = explain_anomalies(frame, [region_record()])["insights"][0]["peer_profile"]  # type: ignore[index]
        assert peer is not None
        assert peer["profile"] == "efficiency_driven"
        assert peer["gaps_pct"]["average_lead_time_days"] == 50.0  # type: ignore[index,union-attr]

    def test_mixed_profile(self) -> None:
        profiles = {
            "North": {"units": 70.0, "revenue": 1200.0, "cost": 280.0, "lead": 10.0},
            "South": {"units": 50.0, "revenue": 900.0, "cost": 250.0, "lead": 10.0},
            "East": {"units": 60.0, "revenue": 1100.0, "cost": 270.0, "lead": 8.0},
        }
        frame = make_entity_frame(profiles)
        peer = explain_anomalies(frame, [region_record()])["insights"][0]["peer_profile"]  # type: ignore[index]
        assert peer is not None
        assert peer["profile"] == "mixed"

    def test_product_scope_profiles_use_products_as_peers(self) -> None:
        frame = make_entity_frame(PRODUCT_PROFILES, dimension="product")
        record = make_record(
            scope="product",
            type="entity_outlier_high",
            entity="R1",
            date=None,
            deviation_pct=50.0,
            score=80.0,
        )
        peer = explain_anomalies(frame, [record])["insights"][0]["peer_profile"]  # type: ignore[index]
        assert peer is not None
        assert peer["profile"] == "volume_driven"

    def test_none_with_single_entity_in_dimension(self) -> None:
        frame = make_entity_frame({"North": VOLUME_PROFILES["North"]})
        insight = explain_anomalies(frame, [region_record()])["insights"][0]  # type: ignore[index]
        assert insight["peer_profile"] is None

    def test_none_when_entity_missing_from_dimension(self) -> None:
        frame = make_entity_frame(VOLUME_PROFILES)
        record = region_record(entity="Atlantis")
        insight = explain_anomalies(frame, [record])["insights"][0]  # type: ignore[index]
        assert insight["peer_profile"] is None

    def test_daily_scope_records_carry_no_peer_profile(self) -> None:
        frame = make_entity_frame(VOLUME_PROFILES)
        insight = explain_anomalies(frame, [make_record()])["insights"][0]  # type: ignore[index]
        assert insight["peer_profile"] is None


# --- explain_anomalies: trend context ----------------------------------------


class TestTrendContext:
    def test_rising_trend_with_exact_change(self) -> None:
        schedule = [100.0] * 7 + [120.0] * 7 + [125.0]
        frame = make_schedule_frame(schedule)
        trend = explain_anomalies(
            frame, [make_record(date=date_at(14))]
        )["insights"][0]["trend"]  # type: ignore[index]
        assert trend == {"direction": "rising", "change_pct": 20.0}

    def test_falling_trend(self) -> None:
        schedule = [100.0] * 7 + [80.0] * 7 + [75.0]
        frame = make_schedule_frame(schedule)
        trend = explain_anomalies(
            frame, [make_record(date=date_at(14), type="daily_drop", deviation_pct=-40.0)]
        )["insights"][0]["trend"]  # type: ignore[index]
        assert trend == {"direction": "falling", "change_pct": -20.0}

    def test_flat_trend_on_constant_history(self) -> None:
        frame = make_schedule_frame([100.0] * 15)
        trend = explain_anomalies(
            frame, [make_record(date=date_at(14))]
        )["insights"][0]["trend"]  # type: ignore[index]
        assert trend == {"direction": "flat", "change_pct": 0.0}

    def test_flat_band_boundary_is_inclusive(self) -> None:
        schedule = [100.0] * 7 + [102.0] * 7 + [102.0]
        frame = make_schedule_frame(schedule)
        trend = explain_anomalies(
            frame, [make_record(date=date_at(14))]
        )["insights"][0]["trend"]  # type: ignore[index]
        assert trend is not None
        assert trend["direction"] == "flat"
        assert trend["change_pct"] == pytest.approx(2.0)

    def test_none_before_trend_window(self) -> None:
        frame = make_schedule_frame([100.0] * 10)
        insight = explain_anomalies(frame, [make_record(date=date_at(9))])["insights"][0]  # type: ignore[index]
        assert insight["trend"] is None

    def test_trend_keys(self) -> None:
        frame = make_schedule_frame([100.0] * 15)
        trend = explain_anomalies(
            frame, [make_record(date=date_at(14))]
        )["insights"][0]["trend"]  # type: ignore[index]
        assert set(trend.keys()) == EXPECTED_TREND_KEYS  # type: ignore[union-attr]

    def test_entity_scope_records_carry_no_trend(self) -> None:
        frame = make_entity_frame(VOLUME_PROFILES)
        insight = explain_anomalies(frame, [region_record()])["insights"][0]  # type: ignore[index]
        assert insight["trend"] is None


# --- explain_anomalies: attached correlations ---------------------------------


def make_correlated_frame() -> pd.DataFrame:
    revenue = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0]
    frame = make_schedule_frame(revenue)
    frame["units_sold"] = [200.0 - value for value in revenue]
    frame["cost"] = [value / 2 for value in revenue]
    frame["lead_time_days"] = [5.0] * len(revenue)
    return frame


class TestAttachedCorrelations:
    def test_only_strong_or_moderate_pairs_involving_metric_attached(self) -> None:
        frame = make_correlated_frame()
        correlations = explain_anomalies(frame, [make_record()])["insights"][0][  # type: ignore[index]
            "correlations"
        ]
        assert correlations == [
            {"pair": ["cost", "revenue"], "r": 1.0, "strength": "strong"},
            {"pair": ["revenue", "units_sold"], "r": -1.0, "strength": "strong"},
        ]

    def test_items_carry_exact_keys(self) -> None:
        frame = make_correlated_frame()
        correlations = explain_anomalies(frame, [make_record()])["insights"][0][  # type: ignore[index]
            "correlations"
        ]
        for item in correlations:
            assert set(item.keys()) == EXPECTED_CORRELATION_ITEM_KEYS

    def test_unrelated_metric_has_no_qualifying_pairs(self) -> None:
        frame = make_correlated_frame()
        correlations = explain_anomalies(
            frame, [make_record(metric="lead_time_days")]
        )["insights"][0]["correlations"]  # type: ignore[index]
        assert correlations == []

    def test_attachment_cap_respected(self) -> None:
        frame = make_correlated_frame()
        correlations = explain_anomalies(frame, [make_record()])["insights"][0][  # type: ignore[index]
            "correlations"
        ]
        assert len(correlations) <= MAX_CORRELATIONS_PER_INSIGHT  # type: ignore[arg-type]


# --- explain_anomalies: related indices and headlines -------------------------


class TestRelatedIndices:
    def make_linked_records(self) -> list[dict[str, object]]:
        return [
            make_record(date=date_at(7)),
            make_record(date=date_at(8)),
            make_record(date=date_at(11)),
            make_record(
                scope="region",
                type="entity_outlier_high",
                entity="North",
                metric="cost",
                date=None,
            ),
            make_record(
                scope="region",
                type="entity_outlier_high",
                entity="North",
                date=None,
            ),
            make_record(
                scope="region",
                type="entity_outlier_high",
                entity="South",
                date=None,
            ),
        ]

    def test_window_of_one_day_is_inclusive(self) -> None:
        records = [
            make_record(date=date_at(7)),
            make_record(date=date_at(8)),
            make_record(date=date_at(10)),
        ]
        insights = explain_anomalies(make_correlated_frame(), records)["insights"]  # type: ignore[index]
        related = [insight["related_anomaly_indices"] for insight in insights]  # type: ignore[index,union-attr]
        assert related == [[1], [0], []]

    def test_entity_and_link_compatibility_rules(self) -> None:
        records = self.make_linked_records()
        insights = explain_anomalies(make_correlated_frame(), records)["insights"]  # type: ignore[index]
        related = [insight["related_anomaly_indices"] for insight in insights]  # type: ignore[index,union-attr]
        assert related == [[1], [0], [], [4], [3, 5], [4]]

    def test_self_index_never_listed(self) -> None:
        records = self.make_linked_records()
        insights = explain_anomalies(make_correlated_frame(), records)["insights"]  # type: ignore[index]
        for position, insight in enumerate(insights):  # type: ignore[union-attr]
            assert position not in insight["related_anomaly_indices"]  # type: ignore[index,union-attr,item-access]


class TestHeadlines:
    def test_daily_spike_headline_with_primary_factor(self) -> None:
        frame = make_factor_frame(
            {"revenue": 110.0, "units_sold": 20.0, "cost": 55.0, "lead_time_days": 5.0}
        )
        headline = explain_anomalies(frame, [make_record(deviation_pct=10.0)])["insights"][0][  # type: ignore[index]
            "headline"
        ]
        assert headline == (
            f"Daily revenue spike on {CANDIDATE_DATE} (+10.00% vs expected); "
            "primary factor volume."
        )

    def test_daily_drop_headline(self) -> None:
        frame = make_factor_frame(
            {"revenue": 90.0, "units_sold": 2.0, "cost": 46.0, "lead_time_days": 5.0}
        )
        headline = explain_anomalies(
            frame, [make_record(type="daily_drop", deviation_pct=-10.0)]
        )["insights"][0]["headline"]  # type: ignore[index]
        assert headline == (
            f"Daily revenue drop on {CANDIDATE_DATE} (-10.00% vs expected); "
            "primary factor volume."
        )

    def test_localized_clause_appears_in_headline(self) -> None:
        frame = make_grid_frame(
            [("North", "A"), ("North", "B"), ("South", "A"), ("South", "B")],
            8,
            overrides={("North", "A"): 40.0, ("North", "B"): 40.0},
        )
        headline = explain_anomalies(frame, [make_record()])["insights"][0]["headline"]  # type: ignore[index]
        assert headline == (
            f"Daily revenue spike on {CANDIDATE_DATE} (+15.00% vs expected); "
            "primary factor unattributed; localized in region North (100.00% of excess)."
        )

    def test_concentrated_clause_wording(self) -> None:
        frame = make_grid_frame(
            [("East", "P"), ("North", "P"), ("South", "P"), ("West", "P")],
            8,
            overrides={
                ("East", "P"): 45.0,
                ("North", "P"): 45.0,
                ("South", "P"): 20.0,
                ("West", "P"): 10.0,
            },
        )
        headline = explain_anomalies(frame, [make_record()])["insights"][0]["headline"]  # type: ignore[index]
        assert headline.endswith("; primary factor unattributed; concentrated across regions.")

    def test_trend_clause_appears_when_available(self) -> None:
        schedule = [100.0] * 7 + [120.0] * 7 + [125.0]
        frame = make_schedule_frame(schedule)
        headline = explain_anomalies(
            frame, [make_record(date=date_at(14), deviation_pct=4.0)]
        )["insights"][0]["headline"]  # type: ignore[index]
        assert headline.endswith("; preceded by rising trend (+20.00%).")

    def test_region_outlier_headline_with_profile(self) -> None:
        frame = make_entity_frame(VOLUME_PROFILES)
        headline = explain_anomalies(frame, [region_record()])["insights"][0]["headline"]  # type: ignore[index]
        assert headline == (
            "Region North is a revenue high outlier: 1.50x peer median; "
            "profile volume_driven."
        )

    def test_region_outlier_headline_without_profile(self) -> None:
        frame = make_entity_frame({"North": VOLUME_PROFILES["North"]})
        record = region_record(type="entity_outlier_low")
        headline = explain_anomalies(frame, [record])["insights"][0]["headline"]  # type: ignore[index]
        assert headline == "Region North is a revenue low outlier; peer comparison unavailable."

    def test_unknown_scope_fallback_headline(self) -> None:
        frame = make_daily_frame([100.0] * 8)
        record = make_record(scope="warehouse")
        headline = explain_anomalies(frame, [record])["insights"][0]["headline"]  # type: ignore[index]
        assert headline == (
            "Anomaly recorded for revenue (scope warehouse); "
            "no specific explanation rules apply."
        )


# --- explain_anomalies: validation, determinism, immutability ------------------


class TestExplainValidationImmutabilityDeterminism:
    def make_frame(self) -> pd.DataFrame:
        return make_factor_frame(
            {"revenue": 110.0, "units_sold": 20.0, "cost": 55.0, "lead_time_days": 5.0}
        )

    def test_non_list_anomalies_raise(self) -> None:
        for bad_input in [None, "spikes", 42, {"a": 1}, ("tuple",)]:
            with pytest.raises(DataValidationError):
                explain_anomalies(self.make_frame(), bad_input)  # type: ignore[arg-type]

    def test_non_dict_item_raises(self) -> None:
        with pytest.raises(DataValidationError):
            explain_anomalies(self.make_frame(), [make_record(), "spike"])  # type: ignore[list-item]

    def test_missing_required_field_raises(self) -> None:
        record = make_record()
        del record["severity"]
        with pytest.raises(DataValidationError):
            explain_anomalies(self.make_frame(), [record])

    def test_unknown_severity_raises(self) -> None:
        with pytest.raises(DataValidationError):
            explain_anomalies(self.make_frame(), [make_record(severity="URGENT")])

    def test_unparseable_date_string_raises(self) -> None:
        with pytest.raises(DataValidationError):
            explain_anomalies(self.make_frame(), [make_record(date="01/08/2024")])

    def test_unusable_dataframe_raises(self) -> None:
        for bad_df in [{}, [], None, "csv"]:
            with pytest.raises(DataValidationError):
                explain_anomalies(bad_df, [make_record()])  # type: ignore[arg-type]
        with pytest.raises(DataValidationError):
            explain_anomalies(make_daily_frame([100.0]).iloc[0:0], [make_record()])

    def test_caller_inputs_never_mutated(self) -> None:
        frame = self.make_frame()
        records = [make_record(), make_record(metric="cost", deviation_pct=-5.0)]
        frame_snapshot = copy.deepcopy(frame)
        records_snapshot = copy.deepcopy(records)
        explain_anomalies(frame, records)
        group_related_anomalies(records)
        pd.testing.assert_frame_equal(frame, frame_snapshot)
        assert records == records_snapshot

    def test_repeated_calls_identical(self) -> None:
        frame = self.make_frame()
        records = [make_record(), make_record(metric="cost", deviation_pct=-5.0)]
        first = explain_anomalies(frame, records)
        second = explain_anomalies(frame, records)
        assert first == second


# --- group_related_anomalies ---------------------------------------------------


class TestGroupRelatedAnomalies:
    def test_exact_result_and_group_keys(self) -> None:
        records = [make_record()]
        result = group_related_anomalies(records)
        assert set(result.keys()) == {"groups", "ungrouped_count"}
        assert set(result["groups"][0].keys()) == EXPECTED_GROUP_KEYS  # type: ignore[index]

    def test_empty_list(self) -> None:
        assert group_related_anomalies([]) == {"groups": [], "ungrouped_count": 0}

    def test_far_apart_records_stay_singletons(self) -> None:
        records = [
            make_record(date=date_at(1)),
            make_record(date=date_at(10)),
            make_record(date=date_at(20)),
        ]
        result = group_related_anomalies(records)
        assert result["ungrouped_count"] == 3
        assert [group["member_count"] for group in result["groups"]] == [1, 1, 1]  # type: ignore[union-attr,index]
        assert [group["group_id"] for group in result["groups"]] == [1, 2, 3]  # type: ignore[union-attr,index]

    def test_same_metric_within_window_merges(self) -> None:
        records = [make_record(date=date_at(7)), make_record(date=date_at(8))]
        result = group_related_anomalies(records)
        assert result["ungrouped_count"] == 0
        group = result["groups"][0]  # type: ignore[index]
        assert group["member_indices"] == [0, 1]  # type: ignore[index,union-attr]
        assert group["member_count"] == 2  # type: ignore[index,union-attr]
        assert group["start_date"] == date_at(7)  # type: ignore[index,union-attr]
        assert group["end_date"] == date_at(8)  # type: ignore[index,union-attr]
        assert group["shared_metrics"] == ["revenue"]  # type: ignore[index,union-attr]
        assert group["shared_entities"] == []  # type: ignore[index,union-attr]

    def test_different_metrics_same_date_do_not_merge(self) -> None:
        records = [
            make_record(metric="revenue"),
            make_record(metric="cost", type="daily_drop", deviation_pct=-3.0),
        ]
        result = group_related_anomalies(records)
        assert result["ungrouped_count"] == 2
        assert len(result["groups"]) == 2  # type: ignore[arg-type]

    def test_shared_entity_links_across_metrics_and_scopes(self) -> None:
        records = [
            make_record(
                scope="region",
                type="entity_outlier_high",
                entity="North",
                metric="cost",
                date=None,
                severity=SEVERITY_LOW,
                score=10.0,
            ),
            make_record(
                scope="region",
                type="entity_outlier_high",
                entity="North",
                metric="revenue",
                date=None,
                severity=SEVERITY_MEDIUM,
                score=55.0,
            ),
        ]
        result = group_related_anomalies(records)
        assert result["ungrouped_count"] == 0
        group = result["groups"][0]  # type: ignore[index]
        assert group["shared_metrics"] == ["cost", "revenue"]  # type: ignore[index,union-attr]
        assert group["shared_entities"] == ["North"]  # type: ignore[index,union-attr]
        assert group["start_date"] is None  # type: ignore[index,union-attr]
        assert group["end_date"] is None  # type: ignore[index,union-attr]
        assert group["severity"] == SEVERITY_MEDIUM  # type: ignore[index,union-attr]

    def test_shared_entities_empty_reports_dataset_wide_in_headline(self) -> None:
        records = [make_record(date=date_at(7)), make_record(date=date_at(8))]
        group = group_related_anomalies(records)["groups"][0]  # type: ignore[index]
        assert group["headline"] == (  # type: ignore[index,union-attr]
            "Cluster of 2 anomalies (HIGH=2) between 2024-01-08 and 2024-01-09; "
            "metrics: revenue; entities: dataset-wide."
        )

    def test_entity_window_enforced_for_dated_records(self) -> None:
        far = [
            make_record(
                scope="region",
                type="entity_outlier_high",
                entity="North",
                date=date_at(1),
            ),
            make_record(
                scope="region",
                type="entity_outlier_high",
                entity="North",
                date=date_at(10),
            ),
        ]
        near = [
            make_record(
                scope="region",
                type="entity_outlier_high",
                entity="North",
                date=date_at(7),
            ),
            make_record(
                scope="region",
                type="entity_outlier_high",
                entity="North",
                date=date_at(8),
            ),
        ]
        assert len(group_related_anomalies(far)["groups"]) == 2  # type: ignore[arg-type]
        assert len(group_related_anomalies(near)["groups"]) == 1  # type: ignore[arg-type]

    def test_greedy_pass_joins_most_recent_compatible_group(self) -> None:
        records = [
            make_record(
                scope="region",
                type="entity_outlier_high",
                entity="South",
                metric="cost",
                date=None,
                severity=SEVERITY_LOW,
                score=5.0,
            ),
            make_record(),
            make_record(
                scope="region",
                type="entity_outlier_high",
                entity="East",
                metric="cost",
                date=None,
                severity=SEVERITY_MEDIUM,
                score=55.0,
            ),
        ]
        result = group_related_anomalies(records)
        members = sorted(group["member_indices"] for group in result["groups"])  # type: ignore[union-attr,type-var,func-returns-value]
        assert members == [[0, 2], [1]]

    def test_group_ordering_and_ids(self) -> None:
        records = [
            make_record(score=80.0, severity=SEVERITY_HIGH),
            make_record(
                metric="cost",
                score=99.456,
                severity=SEVERITY_CRITICAL,
                type="daily_drop",
                deviation_pct=-30.0,
            ),
            make_record(date=date_at(8), score=90.0, severity=SEVERITY_HIGH),
        ]
        result = group_related_anomalies(records)
        groups = result["groups"]  # type: ignore[index]
        assert [group["group_id"] for group in groups] == [1, 2]  # type: ignore[union-attr,index]
        assert groups[0]["severity"] == SEVERITY_CRITICAL  # type: ignore[index]
        assert groups[0]["max_score"] == 99.46  # type: ignore[index]
        assert groups[0]["member_indices"] == [1]  # type: ignore[index]
        assert groups[1]["severity"] == SEVERITY_HIGH  # type: ignore[index]
        assert groups[1]["max_score"] == 90.0  # type: ignore[index]
        assert groups[1]["member_indices"] == [0, 2]  # type: ignore[index]
        assert groups[1]["start_date"] == date_at(7)  # type: ignore[index]

    def test_group_carries_worst_member_severity(self) -> None:
        records = [
            make_record(date=date_at(7), severity=SEVERITY_LOW, score=5.0),
            make_record(date=date_at(8), severity=SEVERITY_CRITICAL, score=95.0),
        ]
        group = group_related_anomalies(records)["groups"][0]  # type: ignore[index]
        assert group["severity"] == SEVERITY_CRITICAL  # type: ignore[index,union-attr]

    def test_full_period_span_headline_for_undated_groups(self) -> None:
        records = [
            make_record(
                scope="region",
                type="entity_outlier_high",
                entity="North",
                metric="cost",
                date=None,
            ),
            make_record(
                scope="region",
                type="entity_outlier_high",
                entity="North",
                date=None,
            ),
        ]
        group = group_related_anomalies(records)["groups"][0]  # type: ignore[index]
        assert group["headline"].startswith(  # type: ignore[index,union-attr]
            "Cluster of 2 anomalies (HIGH=2) across the full period; "
            "metrics: cost, revenue; entities: North."
        )

    @pytest.mark.parametrize(
        "bad_record",
        [
            {"metric": "revenue", "scope": "daily"},
            "not-a-dict",
            None,
        ],
    )
    def test_structural_violations_raise(self, bad_record: object) -> None:
        with pytest.raises(DataValidationError):
            group_related_anomalies([bad_record])  # type: ignore[list-item]

    def test_bad_severity_raises(self) -> None:
        with pytest.raises(DataValidationError):
            group_related_anomalies([make_record(severity="URGENT")])

    def test_unparseable_date_raises(self) -> None:
        with pytest.raises(DataValidationError):
            group_related_anomalies([make_record(date="not-a-date")])

    def test_input_records_never_mutated(self) -> None:
        records = [make_record(), make_record(date=date_at(8))]
        snapshot = copy.deepcopy(records)
        group_related_anomalies(records)
        assert records == snapshot

    def test_repeated_calls_identical(self) -> None:
        records = [make_record(), make_record(date=date_at(8))]
        assert group_related_anomalies(records) == group_related_anomalies(records)


# --- build_insight_report ------------------------------------------------------


class TestBuildInsightReport:
    def make_frame(self) -> pd.DataFrame:
        return make_factor_frame(
            {"revenue": 110.0, "units_sold": 20.0, "cost": 55.0, "lead_time_days": 5.0}
        )

    def test_exact_top_level_keys(self) -> None:
        report = build_insight_report(self.make_frame())
        assert set(report.keys()) == {"summary", "insights", "groups", "parameters"}

    def test_parameters_block(self) -> None:
        report = build_insight_report(self.make_frame(), sensitivity="high")
        assert report["parameters"] == {  # type: ignore[index,union-attr]
            "sensitivity": "high",
            "metrics": METRICS_SORTED,
        }

    def test_matches_manual_composition_from_detection(self) -> None:
        frame = self.make_frame()
        report = build_insight_report(frame)
        detection = detect_anomalies(frame, sensitivity="medium")
        assert report["summary"] == summarize_anomalies(detection["anomalies"])  # type: ignore[index,union-attr]
        assert report["insights"] == explain_anomalies(frame, detection["anomalies"])[  # type: ignore[index,union-attr]
            "insights"
        ]
        assert report["groups"] == group_related_anomalies(detection["anomalies"])  # type: ignore[index,union-attr]
        assert detection["total_count"] > 0  # type: ignore[index,union-attr]

    def test_invalid_sensitivity_raises(self) -> None:
        with pytest.raises(DataValidationError):
            build_insight_report(self.make_frame(), sensitivity="extreme")

    def test_flat_dataset_yields_empty_report(self) -> None:
        frame = make_daily_frame([100.0] * 8)
        report = build_insight_report(frame)
        assert report["summary"]["total_count"] == 0  # type: ignore[index,union-attr]
        assert report["insights"] == []  # type: ignore[index,union-attr]
        assert report["groups"] == {"groups": [], "ungrouped_count": 0}  # type: ignore[index,union-attr]

    def test_repeated_calls_identical(self) -> None:
        frame = self.make_frame()
        assert build_insight_report(frame) == build_insight_report(frame)

    def test_caller_dataframe_never_mutated(self) -> None:
        frame = self.make_frame()
        snapshot = copy.deepcopy(frame)
        build_insight_report(frame)
        pd.testing.assert_frame_equal(frame, snapshot)


class TestDemoDatasetReport:
    def test_end_to_end_structure_integrity(self, demo_df: pd.DataFrame) -> None:
        report = build_insight_report(demo_df)
        summary = report["summary"]  # type: ignore[index]
        insights = report["insights"]  # type: ignore[index]
        groups = report["groups"]["groups"]  # type: ignore[index,union-attr]

        assert set(report.keys()) == {"summary", "insights", "groups", "parameters"}
        assert summary["total_count"] == len(insights)  # type: ignore[index,union-attr]
        assert [insight["anomaly_index"] for insight in insights] == list(range(len(insights)))  # type: ignore[index,union-attr]

        for insight in insights:
            assert set(insight.keys()) == EXPECTED_INSIGHT_KEYS
            assert insight["severity"] in VALID_SEVERITIES
            assert insight["scope"] in {"daily", "region", "product"}
            for related in insight["related_anomaly_indices"]:  # type: ignore[union-attr]
                assert 0 <= related < len(insights)
                assert related != insight["anomaly_index"]
            for item in insight["correlations"]:  # type: ignore[union-attr]
                assert set(item.keys()) == EXPECTED_CORRELATION_ITEM_KEYS
                assert insight["metric"] in item["pair"]  # type: ignore[index,union-attr]
            for factor in insight["factors"]:  # type: ignore[union-attr]
                assert set(factor.keys()) == EXPECTED_FACTOR_KEYS
            assert_no_nan_or_inf(insight)

        member_union: list[int] = []
        for position, group in enumerate(groups, start=1):
            assert set(group.keys()) == EXPECTED_GROUP_KEYS
            assert group["group_id"] == position
            assert group["member_count"] == len(group["member_indices"])  # type: ignore[arg-type,index]
            member_union.extend(group["member_indices"])  # type: ignore[arg-type,index]
            assert group["severity"] in VALID_SEVERITIES
            assert_no_nan_or_inf(group)
        assert sorted(member_union) == list(range(len(insights)))
        assert report["groups"]["ungrouped_count"] == sum(  # type: ignore[index,union-attr,func-returns-value]
            1 for group in groups if group["member_count"] == 1
        )

    def test_demo_caller_frame_not_mutated(self, demo_df: pd.DataFrame) -> None:
        snapshot = copy.deepcopy(demo_df)
        build_insight_report(demo_df)
        pd.testing.assert_frame_equal(demo_df, snapshot)

    def test_demo_report_deterministic(self, demo_df: pd.DataFrame) -> None:
        assert build_insight_report(demo_df) == build_insight_report(demo_df)
