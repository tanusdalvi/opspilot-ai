"""Tests for the daily time-series anomaly detector (Phase 3B slice).

Only the functionality implemented in this checkpoint is covered:
``detect_metric_anomalies`` over daily totals. Mathematical expectations
are recomputed independently inside the tests (via ``statistics`` rather
than the service's numpy path) and then compared against the service.
"""

from __future__ import annotations

import copy
import re
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
    SEVERITY_CRITICAL_MIN_SCORE,
    SEVERITY_HIGH_MIN_SCORE,
    SEVERITY_MEDIUM_MIN_SCORE,
    SENSITIVITY_THRESHOLDS,
    Z_SCORE_CAP,
    _classify_severity,
    _deviation_pct,
    detect_metric_anomalies,
    summarize_anomalies,
)
from services.data_service import load_dataset

# Seven-day baseline with nonzero variance so candidates are evaluable.
# mean = 100.0 exactly; sample std = sqrt(28/6).
BASELINE: list[float] = [100.0, 102.0, 98.0, 101.0, 99.0, 103.0, 97.0]

BASELINE_STD: float = statistics.stdev(BASELINE)
BASELINE_MEAN: float = statistics.mean(BASELINE)

EXPECTED_ANOMALY_KEYS: set[str] = {
    "type",
    "scope",
    "metric",
    "entity",
    "date",
    "value",
    "expected_value",
    "deviation_pct",
    "score",
    "severity",
    "rule",
    "details",
}
EXPECTED_DETAILS_KEYS: set[str] = {"z", "baseline_std", "threshold"}
VALID_SEVERITIES: set[str] = {SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW}


def make_daily_frame(
    values: list[float], *, metric: str = "revenue", start: str = "2024-01-01"
) -> pd.DataFrame:
    """Handcrafted frame with one row per day so daily totals equal values."""
    count = len(values)
    frame = pd.DataFrame(
        {
            "date": [
                (pd.Timestamp(start) + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")
                for offset in range(count)
            ],
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


def value_for_z(k: float) -> float:
    """Daily total producing |z| == k against BASELINE (mean 100)."""
    return BASELINE_MEAN + k * BASELINE_STD


def date_at(offset: int) -> str:
    return (pd.Timestamp("2024-01-01") + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")


@pytest.fixture(scope="module")
def demo_df() -> pd.DataFrame:
    """Load the bundled demo dataset once for the end-to-end tests."""
    return load_dataset("demo_operational_data.csv")


def assert_no_nan_or_inf(record: dict[str, object]) -> None:
    """Every numeric leaf in an anomaly record must be finite."""
    for value in record.values():
        if isinstance(value, dict):
            assert_no_nan_or_inf(value)  # type: ignore[arg-type]
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            assert np.isfinite(value)


class TestSpikeDetection:
    def test_spike_detected_with_independently_computed_math(self) -> None:
        anomalies = detect_metric_anomalies(make_daily_frame(BASELINE + [110.0]), "revenue")
        assert len(anomalies) == 1
        anomaly = anomalies[0]

        expected_mean = statistics.mean(BASELINE)
        expected_std = statistics.stdev(BASELINE)
        expected_z = (110.0 - expected_mean) / expected_std
        expected_score = min(100.0, 100.0 * abs(expected_z) / Z_SCORE_CAP)

        assert anomaly["type"] == "daily_spike"
        assert anomaly["date"] == date_at(7)
        assert anomaly["value"] == 110.0
        assert anomaly["expected_value"] == pytest.approx(round(expected_mean, 2), abs=1e-9)
        assert anomaly["deviation_pct"] == pytest.approx(10.0, abs=1e-9)
        assert anomaly["details"]["z"] == pytest.approx(  # type: ignore[union-attr]
            round(expected_z, 2), abs=1e-9
        )
        assert anomaly["details"]["baseline_std"] == pytest.approx(  # type: ignore[union-attr]
            round(expected_std, 2), abs=1e-9
        )
        assert anomaly["score"] == pytest.approx(round(expected_score, 2), abs=1e-9)

    def test_drop_detected_with_negative_deviation(self) -> None:
        anomalies = detect_metric_anomalies(make_daily_frame(BASELINE + [90.0]), "revenue")
        assert len(anomalies) == 1
        anomaly = anomalies[0]
        expected_z = (90.0 - BASELINE_MEAN) / BASELINE_STD

        assert anomaly["type"] == "daily_drop"
        assert anomaly["date"] == date_at(7)
        assert anomaly["value"] == 90.0
        assert anomaly["deviation_pct"] == pytest.approx(-10.0, abs=1e-9)
        assert anomaly["details"]["z"] == pytest.approx(round(expected_z, 2), abs=1e-9)  # type: ignore[union-attr]
        assert anomaly["score"] == pytest.approx(  # type: ignore[union-attr]
            round(min(100.0, 100.0 * abs(expected_z) / Z_SCORE_CAP), 2), abs=1e-9
        )

    def test_record_carries_requested_metric(self) -> None:
        frame = make_daily_frame(BASELINE + [110.0], metric="units_sold")
        anomalies = detect_metric_anomalies(frame, "units_sold")
        assert len(anomalies) == 1
        assert anomalies[0]["metric"] == "units_sold"

    def test_severity_matches_score_band(self) -> None:
        anomalies = detect_metric_anomalies(make_daily_frame(BASELINE + [110.0]), "revenue")
        score = anomalies[0]["score"]
        assert score >= SEVERITY_HIGH_MIN_SCORE  # type: ignore[operator]
        assert anomalies[0]["severity"] == _classify_severity(score)  # type: ignore[arg-type]


class TestOutputSchema:
    @pytest.fixture()
    def spike_anomaly(self) -> dict[str, object]:
        return detect_metric_anomalies(make_daily_frame(BASELINE + [110.0]), "revenue")[0]

    def test_exact_top_level_keys(self, spike_anomaly: dict[str, object]) -> None:
        assert set(spike_anomaly.keys()) == EXPECTED_ANOMALY_KEYS

    def test_exact_details_keys(self, spike_anomaly: dict[str, object]) -> None:
        assert set(spike_anomaly["details"].keys()) == EXPECTED_DETAILS_KEYS  # type: ignore[union-attr]

    def test_scope_entity_rule(self, spike_anomaly: dict[str, object]) -> None:
        assert spike_anomaly["scope"] == "daily"
        assert spike_anomaly["entity"] is None
        assert spike_anomaly["rule"] == "zscore_rolling"

    def test_threshold_embedded_for_sensitivity(
        self, spike_anomaly: dict[str, object]
    ) -> None:
        details = spike_anomaly["details"]  # type: ignore[union-attr]
        assert details["threshold"] == SENSITIVITY_THRESHOLDS["medium"]  # type: ignore[index]

    def test_types_are_python_natives(self, spike_anomaly: dict[str, object]) -> None:
        assert isinstance(spike_anomaly["date"], str)
        assert isinstance(spike_anomaly["value"], float)
        assert isinstance(spike_anomaly["expected_value"], float)
        assert isinstance(spike_anomaly["deviation_pct"], float)
        assert isinstance(spike_anomaly["score"], float)
        assert isinstance(spike_anomaly["severity"], str)
        assert isinstance(spike_anomaly["details"]["z"], float)  # type: ignore[union-attr,index]

    def test_date_is_iso_formatted(self, spike_anomaly: dict[str, object]) -> None:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(spike_anomaly["date"]))  # type: ignore[arg-type]


class TestHistoryWindow:
    def test_exactly_seven_unique_dates_yield_no_candidates(self) -> None:
        assert detect_metric_anomalies(make_daily_frame(BASELINE), "revenue") == []

    def test_eight_dates_allow_day_eight_evaluation(self) -> None:
        anomalies = detect_metric_anomalies(make_daily_frame(BASELINE + [110.0]), "revenue")
        assert [anomaly["date"] for anomaly in anomalies] == [date_at(7)]

    def test_min_history_days_constant_is_seven(self) -> None:
        assert MIN_HISTORY_DAYS == 7

    def test_trailing_window_slides_and_excludes_candidate(self) -> None:
        anomalies = detect_metric_anomalies(
            make_daily_frame(BASELINE + [110.0, 115.0]), "revenue", sensitivity="medium"
        )
        assert [anomaly["date"] for anomaly in anomalies] == [date_at(7), date_at(8)]

        second_window = BASELINE[1:] + [110.0]
        expected_mean = statistics.mean(second_window)
        expected_std = statistics.stdev(second_window)
        expected_z = (115.0 - expected_mean) / expected_std

        second = anomalies[1]
        assert second["expected_value"] == pytest.approx(round(expected_mean, 2), abs=1e-9)
        assert second["details"]["baseline_std"] == pytest.approx(  # type: ignore[union-attr]
            round(expected_std, 2), abs=1e-9
        )
        assert second["details"]["z"] == pytest.approx(  # type: ignore[union-attr]
            round(expected_z, 2), abs=1e-9
        )

    def test_constant_baseline_produces_no_anomaly_despite_huge_jump(self) -> None:
        flat = [100.0] * MIN_HISTORY_DAYS
        assert detect_metric_anomalies(make_daily_frame(flat + [500.0]), "revenue") == []

    def test_zero_history_with_spike_is_safe(self) -> None:
        zeros = [0.0] * MIN_HISTORY_DAYS
        assert detect_metric_anomalies(make_daily_frame(zeros + [100.0]), "revenue") == []

    def test_deviation_pct_helper_signed_math(self) -> None:
        assert _deviation_pct(120.0, 100.0) == pytest.approx(20.0)
        assert _deviation_pct(80.0, 100.0) == pytest.approx(-20.0)

    def test_deviation_pct_helper_zero_expected_is_safe(self) -> None:
        assert _deviation_pct(50.0, 0.0) == 0.0
        assert _deviation_pct(0.0, 0.0) == 0.0


class TestSensitivityLevels:
    def test_low_threshold_is_three_point_five(self) -> None:
        anomalies = detect_metric_anomalies(
            make_daily_frame(BASELINE + [value_for_z(3.4)]), "revenue", sensitivity="low"
        )
        assert anomalies == []

    def test_medium_threshold_is_three(self) -> None:
        anomalies = detect_metric_anomalies(
            make_daily_frame(BASELINE + [value_for_z(2.9)]), "revenue", sensitivity="medium"
        )
        assert anomalies == []

    def test_high_threshold_is_two_point_five(self) -> None:
        anomalies = detect_metric_anomalies(
            make_daily_frame(BASELINE + [value_for_z(2.6)]), "revenue", sensitivity="high"
        )
        assert len(anomalies) == 1

    def test_bands_between_thresholds(self) -> None:
        high_only = make_daily_frame(BASELINE + [value_for_z(2.7)])
        medium_too = make_daily_frame(BASELINE + [value_for_z(3.2)])

        assert len(detect_metric_anomalies(high_only, "revenue", sensitivity="high")) == 1
        assert detect_metric_anomalies(high_only, "revenue", sensitivity="medium") == []
        assert detect_metric_anomalies(high_only, "revenue", sensitivity="low") == []

        assert len(detect_metric_anomalies(medium_too, "revenue", sensitivity="high")) == 1
        assert len(detect_metric_anomalies(medium_too, "revenue", sensitivity="medium")) == 1
        assert detect_metric_anomalies(medium_too, "revenue", sensitivity="low") == []

    def test_sensitivity_monotonicity_high_subset_medium_subset_low(self) -> None:
        frame = make_daily_frame(
            BASELINE + [value_for_z(2.7), value_for_z(3.2), 110.0]
        )
        dates = {
            sensitivity: {
                anomaly["date"]
                for anomaly in detect_metric_anomalies(
                    frame, "revenue", sensitivity=sensitivity
                )
            }
            for sensitivity in ("high", "medium", "low")
        }
        assert dates["high"] >= dates["medium"]
        assert dates["medium"] >= dates["low"]

        lengths = [len(dates[sensitivity]) for sensitivity in ("high", "medium", "low")]
        assert lengths == sorted(lengths, reverse=True)


class TestScoringAndSeverity:
    def test_score_monotonic_in_deviation_magnitude(self) -> None:
        smaller = detect_metric_anomalies(
            make_daily_frame(BASELINE + [108.0]), "revenue", sensitivity="low"
        )[0]["score"]
        larger = detect_metric_anomalies(
            make_daily_frame(BASELINE + [112.0]), "revenue", sensitivity="low"
        )[0]["score"]
        assert larger > smaller

    def test_score_capped_at_one_hundred(self) -> None:
        anomalies = detect_metric_anomalies(
            make_daily_frame(BASELINE + [value_for_z(10.0)]), "revenue"
        )
        assert anomalies[0]["score"] == 100.0
        assert anomalies[0]["severity"] == SEVERITY_CRITICAL

    def test_score_bounds_and_finiteness(self) -> None:
        for values in (BASELINE + [110.0], BASELINE + [90.0], BASELINE + [value_for_z(10.0)]):
            for anomaly in detect_metric_anomalies(make_daily_frame(values), "revenue"):
                assert 0.0 <= anomaly["score"] <= 100.0  # type: ignore[operator]
                assert_no_nan_or_inf(anomaly)

    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (100.0, SEVERITY_CRITICAL),
            (SEVERITY_CRITICAL_MIN_SCORE, SEVERITY_CRITICAL),
            (84.99, SEVERITY_HIGH),
            (SEVERITY_HIGH_MIN_SCORE, SEVERITY_HIGH),
            (69.99, SEVERITY_MEDIUM),
            (SEVERITY_MEDIUM_MIN_SCORE, SEVERITY_MEDIUM),
            (49.99, SEVERITY_LOW),
            (0.0, SEVERITY_LOW),
        ],
    )
    def test_severity_bands_are_exact(
        self, score: float, expected: str
    ) -> None:
        assert _classify_severity(score) == expected


class TestDeterminismAndImmutability:
    def make_two_region_frame(self) -> pd.DataFrame:
        frames = []
        for region in ("North", "South"):
            frame = make_daily_frame(BASELINE + [110.0])
            frame["region"] = region
            frames.append(frame)
        return pd.concat(frames, ignore_index=True)

    def test_shuffled_rows_produce_identical_results(self) -> None:
        ordered = self.make_two_region_frame()
        shuffled = ordered.sample(frac=1.0, random_state=42).reset_index(drop=True)
        assert detect_metric_anomalies(ordered, "revenue") == detect_metric_anomalies(
            shuffled, "revenue"
        )

    def test_repeated_calls_identical(self) -> None:
        frame = make_daily_frame(BASELINE + [110.0])
        assert (
            detect_metric_anomalies(frame, "revenue")
            == detect_metric_anomalies(frame, "revenue")
        )

    def test_duplicate_rows_do_not_block_detection(self) -> None:
        frame = make_daily_frame(BASELINE + [110.0])
        duplicated = pd.concat([frame, frame], ignore_index=True)
        base = detect_metric_anomalies(frame, "revenue")[0]
        doubled = detect_metric_anomalies(duplicated, "revenue")[0]
        # Doubling every daily total leaves z-scores unchanged (scale invariant).
        assert doubled["date"] == base["date"]
        assert doubled["details"]["z"] == base["details"]["z"]  # type: ignore[index]

    def test_extra_columns_do_not_block_detection(self) -> None:
        frame = make_daily_frame(BASELINE + [110.0])
        frame["warehouse"] = "X1"
        assert detect_metric_anomalies(frame, "revenue") == detect_metric_anomalies(
            make_daily_frame(BASELINE + [110.0]), "revenue"
        )

    def test_caller_dataframe_never_mutated(self) -> None:
        frame = make_daily_frame(BASELINE + [110.0])
        snapshot = copy.deepcopy(frame)
        for metric in ("units_sold", "revenue", "cost", "lead_time_days"):
            detect_metric_anomalies(frame, metric)
        pd.testing.assert_frame_equal(frame, snapshot)
        assert frame.columns.tolist() == snapshot.columns.tolist()
        assert frame.dtypes.tolist() == snapshot.dtypes.tolist()


class TestInputValidation:
    @pytest.mark.parametrize("bad_metric", ["", "Profit", "profit_margin", 123, None, True])
    def test_invalid_metric_raises(self, bad_metric: object) -> None:
        with pytest.raises(DataValidationError):
            detect_metric_anomalies(make_daily_frame(BASELINE + [110.0]), bad_metric)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "bad_sensitivity", ["", "HIGH", "extreme", 3.0, None, True]
    )
    def test_invalid_sensitivity_raises(self, bad_sensitivity: object) -> None:
        with pytest.raises(DataValidationError):
            detect_metric_anomalies(
                make_daily_frame(BASELINE + [110.0]), "revenue", sensitivity=bad_sensitivity  # type: ignore[arg-type]
            )

    def test_non_dataframe_input_raises(self) -> None:
        for bad_input in [{}, [], None, "csv", 42]:
            with pytest.raises(DataValidationError):
                detect_metric_anomalies(bad_input, "revenue")  # type: ignore[arg-type]

    def test_missing_required_column_raises(self) -> None:
        frame = make_daily_frame(BASELINE + [110.0]).drop(columns=["cost"])
        with pytest.raises(DataValidationError):
            detect_metric_anomalies(frame, "cost")

    def test_empty_dataframe_raises(self) -> None:
        empty = make_daily_frame(BASELINE).iloc[0:0]
        with pytest.raises(DataValidationError):
            detect_metric_anomalies(empty, "revenue")

    def test_null_value_raises(self) -> None:
        frame = make_daily_frame(BASELINE + [110.0])
        frame["revenue"] = frame["revenue"].astype(object)
        frame.loc[0, "revenue"] = None
        with pytest.raises(DataValidationError):
            detect_metric_anomalies(frame, "revenue")

    def test_non_numeric_value_raises(self) -> None:
        frame = make_daily_frame(BASELINE + [110.0])
        frame["revenue"] = frame["revenue"].astype(object)
        frame.loc[1, "revenue"] = "not-a-number"
        with pytest.raises(DataValidationError):
            detect_metric_anomalies(frame, "revenue")

    def test_infinite_value_raises(self) -> None:
        frame = make_daily_frame(BASELINE + [110.0])
        frame["revenue"] = frame["revenue"].astype(object)
        frame.loc[2, "revenue"] = np.inf
        with pytest.raises(DataValidationError):
            detect_metric_anomalies(frame, "revenue")

    def test_invalid_date_raises(self) -> None:
        frame = make_daily_frame(BASELINE + [110.0])
        frame.loc[3, "date"] = "not-a-date"
        with pytest.raises(DataValidationError):
            detect_metric_anomalies(frame, "revenue")


class TestDemoDataset:
    def test_all_metrics_and_sensitivities_execute(
        self, demo_df: pd.DataFrame
    ) -> None:
        for metric in ("units_sold", "revenue", "cost", "lead_time_days"):
            for sensitivity in ("low", "medium", "high"):
                anomalies = detect_metric_anomalies(
                    demo_df, metric, sensitivity=sensitivity
                )
                dates = [anomaly["date"] for anomaly in anomalies]
                assert dates == sorted(dates)
                assert len(dates) == len(set(dates))
                for anomaly in anomalies:
                    assert set(anomaly.keys()) == EXPECTED_ANOMALY_KEYS
                    assert anomaly["metric"] == metric
                    assert anomaly["scope"] == "daily"
                    assert anomaly["entity"] is None
                    assert anomaly["rule"] == "zscore_rolling"
                    assert anomaly["severity"] in VALID_SEVERITIES
                    assert 0.0 <= anomaly["score"] <= 100.0  # type: ignore[operator]
                    assert_no_nan_or_inf(anomaly)

    def test_demo_caller_frame_not_mutated(self, demo_df: pd.DataFrame) -> None:
        snapshot = copy.deepcopy(demo_df)
        detect_metric_anomalies(demo_df, "revenue")
        pd.testing.assert_frame_equal(demo_df, snapshot)


def make_anomaly(**overrides: object) -> dict[str, object]:
    """Minimal but schema-complete anomaly record for summary tests."""
    record: dict[str, object] = {
        "type": "daily_spike",
        "scope": "daily",
        "metric": "revenue",
        "entity": None,
        "date": "2024-01-08",
        "value": 110.0,
        "expected_value": 100.0,
        "deviation_pct": 10.0,
        "score": 75.0,
        "severity": SEVERITY_HIGH,
        "rule": "zscore_rolling",
        "details": {"z": 3.2, "baseline_std": 2.0, "threshold": 3.0},
    }
    record.update(overrides)
    return record


class TestSummarizeAnomalies:
    def test_normal_summary_shape_and_counts(self) -> None:
        anomalies = [
            make_anomaly(),
            make_anomaly(severity=SEVERITY_LOW, score=10.0),
            make_anomaly(
                type="entity_outlier_high",
                scope="region",
                entity="North",
                date=None,
                rule="iqr_fence",
            ),
        ]
        result = summarize_anomalies(anomalies)

        assert set(result.keys()) == {
            "total_count",
            "by_severity",
            "by_type",
            "by_scope",
            "by_metric",
        }
        assert result["total_count"] == 3
        assert result["by_severity"] == {
            SEVERITY_CRITICAL: 0,
            SEVERITY_HIGH: 2,
            SEVERITY_MEDIUM: 0,
            SEVERITY_LOW: 1,
        }
        assert result["by_type"] == {"daily_spike": 2, "entity_outlier_high": 1}
        assert result["by_scope"] == {"daily": 2, "region": 1}
        assert result["by_metric"] == {"revenue": 3}

    def test_empty_list_returns_all_zero_severities(self) -> None:
        assert summarize_anomalies([]) == {
            "total_count": 0,
            "by_severity": {
                SEVERITY_CRITICAL: 0,
                SEVERITY_HIGH: 0,
                SEVERITY_MEDIUM: 0,
                SEVERITY_LOW: 0,
            },
            "by_type": {},
            "by_scope": {},
            "by_metric": {},
        }

    def test_multiple_severities_counted(self) -> None:
        anomalies = [
            make_anomaly(severity=severity)
            for severity in (
                SEVERITY_CRITICAL,
                SEVERITY_CRITICAL,
                SEVERITY_MEDIUM,
                SEVERITY_LOW,
            )
        ]
        result = summarize_anomalies(anomalies)
        assert result["total_count"] == 4
        assert result["by_severity"][SEVERITY_CRITICAL] == 2
        assert result["by_severity"][SEVERITY_HIGH] == 0
        assert result["by_severity"][SEVERITY_MEDIUM] == 1
        assert result["by_severity"][SEVERITY_LOW] == 1

    def test_multiple_types_scopes_and_metrics(self) -> None:
        anomalies = [
            make_anomaly(type="daily_spike", scope="daily", metric="revenue"),
            make_anomaly(type="daily_drop", scope="daily", metric="cost"),
            make_anomaly(type="entity_outlier_high", scope="region", metric="units_sold"),
            make_anomaly(
                type="entity_outlier_low", scope="product", metric="lead_time_days"
            ),
            make_anomaly(type="daily_spike", scope="daily", metric="revenue"),
        ]
        result = summarize_anomalies(anomalies)
        assert result["total_count"] == 5
        assert result["by_type"] == {
            "daily_drop": 1,
            "daily_spike": 2,
            "entity_outlier_high": 1,
            "entity_outlier_low": 1,
        }
        assert result["by_scope"] == {"daily": 3, "product": 1, "region": 1}
        assert result["by_metric"] == {
            "cost": 1,
            "lead_time_days": 1,
            "revenue": 2,
            "units_sold": 1,
        }
        assert sum(result["by_severity"].values()) == 5

    def test_by_severity_always_has_four_keys_with_zeros(self) -> None:
        result = summarize_anomalies([make_anomaly(severity=SEVERITY_CRITICAL)])
        assert list(result["by_severity"].keys()) == [
            SEVERITY_CRITICAL,
            SEVERITY_HIGH,
            SEVERITY_MEDIUM,
            SEVERITY_LOW,
        ]
        assert result["by_severity"][SEVERITY_HIGH] == 0
        assert result["by_severity"][SEVERITY_MEDIUM] == 0
        assert result["by_severity"][SEVERITY_LOW] == 0

    def test_bucket_keys_are_sorted_deterministically(self) -> None:
        anomalies = [
            make_anomaly(type="zulu", scope="omega", metric="tango"),
            make_anomaly(type="alpha", scope="bravo", metric="kilo"),
            make_anomaly(type="mike", scope="sierra", metric="foxtrot"),
        ]
        result = summarize_anomalies(anomalies)
        assert list(result["by_type"]) == ["alpha", "mike", "zulu"]
        assert list(result["by_scope"]) == ["bravo", "omega", "sierra"]
        assert list(result["by_metric"]) == ["foxtrot", "kilo", "tango"]

    @pytest.mark.parametrize(
        "bad_input", [None, "spikes", 42, 3.5, True, {"a": 1}, ("tuple",), {"set"}]
    )
    def test_non_list_input_raises(self, bad_input: object) -> None:
        with pytest.raises(DataValidationError):
            summarize_anomalies(bad_input)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad_item", [None, "spike", 42, ["list"], ("tuple",)])
    def test_non_dict_item_raises(self, bad_item: object) -> None:
        with pytest.raises(DataValidationError):
            summarize_anomalies([make_anomaly(), bad_item])  # type: ignore[list-item]

    @pytest.mark.parametrize("missing_field", ["type", "scope", "metric", "severity"])
    def test_missing_required_field_raises(self, missing_field: str) -> None:
        record = make_anomaly()
        del record[missing_field]
        with pytest.raises(DataValidationError):
            summarize_anomalies([record])

    @pytest.mark.parametrize(
        "bad_severity", ["URGENT", "", "critical", None, 3.0, True]
    )
    def test_unknown_severity_raises(self, bad_severity: object) -> None:
        with pytest.raises(DataValidationError):
            summarize_anomalies([make_anomaly(severity=bad_severity)])

    def test_all_valid_severities_accepted(self) -> None:
        anomalies = [
            make_anomaly(severity=severity)
            for severity in (SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW)
        ]
        result = summarize_anomalies(anomalies)
        assert result["by_severity"] == {
            SEVERITY_CRITICAL: 1,
            SEVERITY_HIGH: 1,
            SEVERITY_MEDIUM: 1,
            SEVERITY_LOW: 1,
        }

    def test_input_list_and_records_not_mutated(self) -> None:
        anomalies = [
            make_anomaly(),
            make_anomaly(severity=SEVERITY_CRITICAL),
            make_anomaly(scope="product", type="entity_outlier_low"),
        ]
        snapshot = copy.deepcopy(anomalies)
        summarize_anomalies(anomalies)
        assert anomalies == snapshot

    def test_repeated_calls_identical_including_key_order(self) -> None:
        anomalies = [
            make_anomaly(type="zulu", scope="omega", metric="tango"),
            make_anomaly(type="alpha", scope="bravo", metric="kilo"),
        ]
        first = summarize_anomalies(anomalies)
        second = summarize_anomalies(anomalies)
        assert first == second
        assert list(first["by_type"]) == list(second["by_type"])
        assert list(first["by_scope"]) == list(second["by_scope"])
        assert list(first["by_metric"]) == list(second["by_metric"])
        assert list(first["by_severity"]) == list(second["by_severity"])

    def test_values_are_plain_python_types(self) -> None:
        result = summarize_anomalies([make_anomaly()])
        assert isinstance(result["total_count"], int)
        for counts in (
            result["by_severity"],
            result["by_type"],
            result["by_scope"],
            result["by_metric"],
        ):
            assert all(isinstance(key, str) for key in counts)  # type: ignore[union-attr]
            assert all(isinstance(value, int) for value in counts.values())  # type: ignore[union-attr]
