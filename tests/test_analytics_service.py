"""Tests for the analytics service (services/analytics_service.py)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.exceptions import DataValidationError
from services.analytics_service import (
    calculate_bottom_performers,
    calculate_daily_trends,
    calculate_kpis,
    calculate_period_comparison,
    calculate_product_performance,
    calculate_region_performance,
    calculate_top_performers,
)
from services.data_service import load_dataset


@pytest.fixture(scope="module")
def demo_df() -> pd.DataFrame:
    """Load the bundled demo dataset once for the end-to-end tests."""
    return load_dataset("demo_operational_data.csv")


def make_frame() -> pd.DataFrame:
    """Small handcrafted dataset with fully predictable arithmetic."""
    return pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"],
            "region": ["North", "South", "North", "South"],
            "product": ["A", "A", "B", "B"],
            "units_sold": [10, 20, 30, 40],
            "revenue": [100.0, 200.0, 300.0, 400.0],
            "cost": [50.0, 80.0, 120.0, 160.0],
            "lead_time_days": [5, 10, 7, 14],
        }
    )


def numeric_values_are_finite(values: list[object]) -> bool:
    """Return True when every int/float in ``values`` is finite."""
    return all(
        np.isfinite(value) for value in values if isinstance(value, (int, float))
    )


class TestKpis:
    def test_valid_kpis_structure(self) -> None:
        kpis = calculate_kpis(make_frame())
        expected_keys = {
            "total_units_sold",
            "total_revenue",
            "total_cost",
            "total_profit",
            "profit_margin_pct",
            "average_daily_units_sold",
            "average_daily_revenue",
            "average_daily_cost",
            "average_daily_profit",
            "average_lead_time_days",
            "unique_regions",
            "unique_products",
            "date_range",
        }
        assert expected_keys <= set(kpis.keys())

    def test_total_units_sold(self) -> None:
        assert calculate_kpis(make_frame())["total_units_sold"] == 100

    def test_total_units_sold_is_python_int(self) -> None:
        assert isinstance(calculate_kpis(make_frame())["total_units_sold"], int)

    def test_fractional_units_stay_float(self) -> None:
        frame = make_frame().iloc[[0]].copy()
        frame["units_sold"] = frame["units_sold"].astype(object)
        frame.loc[0, "units_sold"] = 10.5
        kpis = calculate_kpis(frame)
        assert kpis["total_units_sold"] == 10.5
        assert isinstance(kpis["total_units_sold"], float)

    def test_total_revenue(self) -> None:
        assert calculate_kpis(make_frame())["total_revenue"] == 1000.0

    def test_total_cost(self) -> None:
        assert calculate_kpis(make_frame())["total_cost"] == 410.0

    def test_total_profit_is_revenue_minus_cost(self) -> None:
        kpis = calculate_kpis(make_frame())
        assert kpis["total_profit"] == 590.0
        assert (
            kpis["total_profit"] == kpis["total_revenue"] - kpis["total_cost"]
        )

    def test_profit_margin(self) -> None:
        assert calculate_kpis(make_frame())["profit_margin_pct"] == 59.0

    def test_average_daily_metrics_use_unique_dates(self) -> None:
        kpis = calculate_kpis(make_frame())
        assert kpis["average_daily_units_sold"] == 50.0
        assert kpis["average_daily_revenue"] == 500.0
        assert kpis["average_daily_cost"] == 205.0
        assert kpis["average_daily_profit"] == 295.0

    def test_average_daily_ignores_row_count(self) -> None:
        frame = pd.concat([make_frame()] * 10, ignore_index=True)
        kpis = calculate_kpis(frame)
        assert len(frame) == 40
        assert kpis["average_daily_units_sold"] == 500.0
        assert kpis["average_daily_revenue"] == 5000.0

    def test_average_lead_time(self) -> None:
        assert calculate_kpis(make_frame())["average_lead_time_days"] == 9.0

    def test_unique_region_and_product_counts(self) -> None:
        kpis = calculate_kpis(make_frame())
        assert kpis["unique_regions"] == 2
        assert kpis["unique_products"] == 2

    def test_date_range(self) -> None:
        kpis = calculate_kpis(make_frame())
        assert kpis["date_range"] == {"start": "2024-01-01", "end": "2024-01-02"}

    def test_zero_revenue_yields_zero_margin(self) -> None:
        frame = make_frame()
        frame["revenue"] = 0.0
        kpis = calculate_kpis(frame)
        assert kpis["profit_margin_pct"] == 0.0
        assert np.isfinite(kpis["profit_margin_pct"])

    def test_all_kpi_values_finite(self) -> None:
        kpis = calculate_kpis(make_frame())
        flat = [value for value in kpis.values() if not isinstance(value, dict)]
        assert numeric_values_are_finite(flat)


class TestRegionPerformance:
    def test_region_aggregation_values(self) -> None:
        result = calculate_region_performance(make_frame())
        south = result[result["region"] == "South"].iloc[0]
        north = result[result["region"] == "North"].iloc[0]
        assert south["units_sold"] == 60
        assert south["revenue"] == 600.0
        assert south["cost"] == 240.0
        assert south["profit"] == 360.0
        assert south["profit_margin_pct"] == 60.0
        assert south["average_lead_time_days"] == 12.0
        assert north["units_sold"] == 40
        assert north["revenue"] == 400.0
        assert north["average_lead_time_days"] == 6.0

    def test_region_sorting_revenue_desc_then_name_asc(self) -> None:
        result = calculate_region_performance(make_frame())
        assert result["region"].tolist() == ["South", "North"]

    def test_region_revenue_shares(self) -> None:
        result = calculate_region_performance(make_frame())
        shares = dict(zip(result["region"], result["revenue_share_pct"], strict=True))
        assert shares == {"South": 60.0, "North": 40.0}

    def test_region_units_shares(self) -> None:
        result = calculate_region_performance(make_frame())
        shares = dict(zip(result["region"], result["units_share_pct"], strict=True))
        assert shares == {"South": 60.0, "North": 40.0}

    def test_region_columns_exact(self) -> None:
        result = calculate_region_performance(make_frame())
        assert result.columns.tolist() == [
            "region",
            "units_sold",
            "revenue",
            "cost",
            "profit",
            "profit_margin_pct",
            "average_lead_time_days",
            "revenue_share_pct",
            "units_share_pct",
        ]

    def test_zero_revenue_region_share_is_safe(self) -> None:
        frame = make_frame()
        frame.loc[frame["region"] == "North", "revenue"] = 0.0
        result = calculate_region_performance(frame)
        north = result[result["region"] == "North"].iloc[0]
        assert north["revenue_share_pct"] == 0.0
        assert north["profit_margin_pct"] == 0.0
        assert np.isfinite(north["revenue_share_pct"])


class TestProductPerformance:
    def test_product_aggregation_values(self) -> None:
        result = calculate_product_performance(make_frame())
        b = result[result["product"] == "B"].iloc[0]
        a = result[result["product"] == "A"].iloc[0]
        assert b["units_sold"] == 70
        assert b["revenue"] == 700.0
        assert b["profit"] == 420.0
        assert b["profit_margin_pct"] == 60.0
        assert a["units_sold"] == 30
        assert a["revenue"] == 300.0
        assert a["profit_margin_pct"] == 56.67

    def test_product_sorting_revenue_desc_then_name_asc(self) -> None:
        result = calculate_product_performance(make_frame())
        assert result["product"].tolist() == ["B", "A"]

    def test_product_revenue_shares(self) -> None:
        result = calculate_product_performance(make_frame())
        shares = dict(zip(result["product"], result["revenue_share_pct"], strict=True))
        assert shares == {"B": 70.0, "A": 30.0}

    def test_product_columns_match_region_schema(self) -> None:
        region = calculate_region_performance(make_frame())
        product = calculate_product_performance(make_frame())
        assert product.columns.tolist()[0] == "product"
        assert region.columns.tolist()[0] == "region"
        assert product.columns.tolist()[1:] == region.columns.tolist()[1:]


class TestDailyTrends:
    def test_daily_aggregation_one_row_per_unique_date(self) -> None:
        result = calculate_daily_trends(make_frame())
        assert len(result) == 2
        assert result["date"].nunique() == len(result)

    def test_daily_values(self) -> None:
        result = calculate_daily_trends(make_frame())
        first = result.iloc[0]
        second = result.iloc[1]
        assert first["date"] == "2024-01-01"
        assert first["units_sold"] == 30
        assert first["revenue"] == 300.0
        assert first["cost"] == 130.0
        assert first["profit"] == 170.0
        assert first["profit_margin_pct"] == 56.67
        assert first["average_lead_time_days"] == 7.5
        assert second["date"] == "2024-01-02"
        assert second["units_sold"] == 70
        assert second["profit_margin_pct"] == 60.0

    def test_daily_sorted_ascending_regardless_of_input_order(self) -> None:
        shuffled = make_frame().sample(frac=1.0, random_state=7).reset_index(drop=True)
        result = calculate_daily_trends(shuffled)
        assert result["date"].tolist() == ["2024-01-01", "2024-01-02"]

    def test_daily_totals_match_dataset_totals(self) -> None:
        frame = make_frame()
        trends = calculate_daily_trends(frame)
        kpis = calculate_kpis(frame)
        assert trends["units_sold"].sum() == kpis["total_units_sold"]
        assert trends["revenue"].sum() == pytest.approx(kpis["total_revenue"])


class TestPeriodComparison:
    def test_structure(self) -> None:
        comparison = calculate_period_comparison(make_frame())
        assert set(comparison.keys()) == {"period_1", "period_2", "changes_pct"}
        period_keys = {
            "start",
            "end",
            "units_sold",
            "revenue",
            "cost",
            "profit",
            "profit_margin_pct",
            "average_lead_time_days",
        }
        assert set(comparison["period_1"].keys()) == period_keys  # type: ignore[union-attr]
        assert set(comparison["period_2"].keys()) == period_keys  # type: ignore[union-attr]

    def test_two_dates_split_into_previous_and_current(self) -> None:
        comparison = calculate_period_comparison(make_frame())
        assert comparison["period_1"]["start"] == "2024-01-01"  # type: ignore[index]
        assert comparison["period_1"]["end"] == "2024-01-01"  # type: ignore[index]
        assert comparison["period_2"]["start"] == "2024-01-02"  # type: ignore[index]
        assert comparison["period_2"]["end"] == "2024-01-02"  # type: ignore[index]
        assert comparison["period_1"]["units_sold"] == 30  # type: ignore[index]
        assert comparison["period_2"]["units_sold"] == 70  # type: ignore[index]

    def test_odd_date_policy_middle_day_in_previous_period(self) -> None:
        frame = pd.DataFrame(
            {
                "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "region": ["North"] * 3,
                "product": ["A"] * 3,
                "units_sold": [10, 20, 30],
                "revenue": [100.0, 200.0, 300.0],
                "cost": [50.0, 80.0, 120.0],
                "lead_time_days": [5, 10, 15],
            }
        )
        comparison = calculate_period_comparison(frame)
        assert comparison["period_1"]["start"] == "2024-01-01"  # type: ignore[index]
        assert comparison["period_1"]["end"] == "2024-01-02"  # type: ignore[index]
        assert comparison["period_1"]["units_sold"] == 30  # type: ignore[index]
        assert comparison["period_2"]["start"] == "2024-01-03"  # type: ignore[index]
        assert comparison["period_2"]["end"] == "2024-01-03"  # type: ignore[index]
        assert comparison["period_2"]["units_sold"] == 30  # type: ignore[index]

    def test_percentage_changes(self) -> None:
        changes = calculate_period_comparison(make_frame())["changes_pct"]
        assert changes == {
            "units_change_pct": 133.33,
            "revenue_change_pct": 133.33,
            "cost_change_pct": 115.38,
            "profit_change_pct": 147.06,
            "margin_change_pct": 5.88,
            "lead_time_change_pct": 40.0,
        }

    def test_margin_change_uses_unrounded_values(self) -> None:
        frame = pd.DataFrame(
            {
                "date": ["2024-01-01", "2024-01-02"],
                "region": ["North", "North"],
                "product": ["A", "A"],
                "units_sold": [1, 2],
                "revenue": [30.0, 30.0],
                "cost": [20.0, 10.0],
                "lead_time_days": [5, 5],
            }
        )
        comparison = calculate_period_comparison(frame)
        assert comparison["period_1"]["profit_margin_pct"] == 33.33  # type: ignore[index]
        assert comparison["period_2"]["profit_margin_pct"] == 66.67  # type: ignore[index]
        assert comparison["changes_pct"]["margin_change_pct"] == 100.0

    def test_lead_time_change_uses_unrounded_values(self) -> None:
        frame = pd.DataFrame(
            {
                "date": ["2024-01-01", "2024-01-01", "2024-01-01", "2024-01-02"],
                "region": ["North"] * 4,
                "product": ["A"] * 4,
                "units_sold": [1, 1, 1, 1],
                "revenue": [10.0, 10.0, 10.0, 10.0],
                "cost": [5.0, 5.0, 5.0, 5.0],
                "lead_time_days": [2, 3, 5, 5],
            }
        )
        comparison = calculate_period_comparison(frame)
        assert comparison["period_1"]["average_lead_time_days"] == 3.33  # type: ignore[index]
        assert comparison["period_2"]["average_lead_time_days"] == 5.0  # type: ignore[index]
        assert comparison["changes_pct"]["lead_time_change_pct"] == 50.0

    def test_zero_previous_period_change_is_safe(self) -> None:
        frame = pd.DataFrame(
            {
                "date": ["2024-01-01", "2024-01-02"],
                "region": ["North", "North"],
                "product": ["A", "A"],
                "units_sold": [0, 10],
                "revenue": [0.0, 100.0],
                "cost": [10.0, 50.0],
                "lead_time_days": [5, 5],
            }
        )
        changes = calculate_period_comparison(frame)["changes_pct"]
        assert changes["units_change_pct"] == 0.0  # type: ignore[index]
        assert changes["revenue_change_pct"] == 0.0  # type: ignore[index]
        assert changes["margin_change_pct"] == 0.0  # type: ignore[index]
        assert np.isfinite(changes["revenue_change_pct"])  # type: ignore[index]

    def test_single_unique_date_raises(self) -> None:
        frame = make_frame()
        frame["date"] = "2024-01-01"
        with pytest.raises(DataValidationError):
            calculate_period_comparison(frame)

    def test_period_summaries_contain_no_nonfinite_values(self) -> None:
        comparison = calculate_period_comparison(make_frame())
        for key in ("period_1", "period_2"):
            values = [
                value
                for value in comparison[key].values()  # type: ignore[union-attr]
                if isinstance(value, (int, float))
            ]
            assert numeric_values_are_finite(values)


class TestPerformers:
    def test_top_performers_ranking(self) -> None:
        performers = calculate_top_performers(make_frame(), limit=2)
        assert [record["region"] for record in performers["regions"]] == [
            "South",
            "North",
        ]
        assert [record["rank"] for record in performers["regions"]] == [1, 2]
        assert [record["product"] for record in performers["products"]] == ["B", "A"]

    def test_bottom_performers_ranking(self) -> None:
        performers = calculate_bottom_performers(make_frame(), limit=2)
        assert [record["region"] for record in performers["regions"]] == [
            "North",
            "South",
        ]
        assert [record["rank"] for record in performers["regions"]] == [1, 2]
        assert [record["product"] for record in performers["products"]] == ["A", "B"]

    def test_limit_larger_than_entity_count_returns_all(self) -> None:
        performers = calculate_top_performers(make_frame(), limit=99)
        assert len(performers["regions"]) == 2
        assert len(performers["products"]) == 2

    def test_default_limit_is_five(self) -> None:
        performers = calculate_top_performers(make_frame())
        assert len(performers["regions"]) == 2
        assert len(performers["products"]) == 2

    def test_limit_one_selects_extreme(self) -> None:
        top = calculate_top_performers(make_frame(), limit=1)
        bottom = calculate_bottom_performers(make_frame(), limit=1)
        assert top["regions"][0]["region"] == "South"
        assert bottom["regions"][0]["region"] == "North"

    def test_records_use_python_scalars(self) -> None:
        performers = calculate_top_performers(make_frame(), limit=1)
        revenue = performers["regions"][0]["revenue"]
        units = performers["regions"][0]["units_sold"]
        assert isinstance(revenue, float)
        assert isinstance(units, int)

    @pytest.mark.parametrize("bad_limit", [0, -1, "3", 2.5, True, None])
    def test_invalid_limit_raises(self, bad_limit: object) -> None:
        with pytest.raises(DataValidationError):
            calculate_top_performers(make_frame(), limit=bad_limit)  # type: ignore[arg-type]
        with pytest.raises(DataValidationError):
            calculate_bottom_performers(make_frame(), limit=bad_limit)  # type: ignore[arg-type]


class TestInputValidation:
    def test_non_dataframe_input_raises(self) -> None:
        for bad_input in [{"date": []}, ["not", "a", "frame"], None, "csv"]:
            with pytest.raises(DataValidationError):
                calculate_kpis(bad_input)  # type: ignore[arg-type]

    def test_missing_required_column_raises(self) -> None:
        with pytest.raises(DataValidationError) as excinfo:
            calculate_kpis(make_frame().drop(columns=["revenue"]))
        assert "MISSING_COLUMNS" in str(excinfo.value)

    def test_empty_dataframe_without_schema_raises(self) -> None:
        with pytest.raises(DataValidationError):
            calculate_kpis(pd.DataFrame())

    def test_empty_dataframe_with_full_schema_raises(self) -> None:
        empty = make_frame().iloc[0:0]
        with pytest.raises(DataValidationError) as excinfo:
            calculate_kpis(empty)
        assert "empty" in str(excinfo.value).lower()

    def test_every_public_function_rejects_empty_data(self) -> None:
        empty = make_frame().iloc[0:0]
        functions = [
            calculate_kpis,
            calculate_region_performance,
            calculate_product_performance,
            calculate_daily_trends,
            calculate_period_comparison,
            calculate_top_performers,
            calculate_bottom_performers,
        ]
        for function in functions:
            with pytest.raises(DataValidationError):
                function(empty)

    def test_invalid_numeric_value_raises(self) -> None:
        frame = make_frame()
        frame["revenue"] = frame["revenue"].astype(object)
        frame.loc[0, "revenue"] = "not-a-number"
        with pytest.raises(DataValidationError):
            calculate_kpis(frame)

    def test_null_value_raises(self) -> None:
        frame = make_frame()
        frame.loc[1, "cost"] = None
        with pytest.raises(DataValidationError):
            calculate_region_performance(frame)

    def test_invalid_date_raises(self) -> None:
        frame = make_frame()
        frame.loc[2, "date"] = "not-a-date"
        with pytest.raises(DataValidationError):
            calculate_daily_trends(frame)

    def test_infinite_value_raises(self) -> None:
        frame = make_frame()
        frame["revenue"] = frame["revenue"].astype(object)
        frame.loc[0, "revenue"] = np.inf
        with pytest.raises(DataValidationError) as excinfo:
            calculate_kpis(frame)
        assert "non-finite" in str(excinfo.value)

    def test_duplicate_rows_do_not_block_analytics(self) -> None:
        duplicated = pd.concat([make_frame(), make_frame()], ignore_index=True)
        kpis = calculate_kpis(duplicated)
        assert kpis["total_units_sold"] == 200

    def test_unexpected_extra_column_does_not_block_analytics(self) -> None:
        frame = make_frame()
        frame["extra"] = 1
        kpis = calculate_kpis(frame)
        assert kpis["total_units_sold"] == 100


class TestImmutabilityAndDeterminism:
    def test_caller_dataframe_never_mutated(self) -> None:
        frame = make_frame()
        snapshot = copy.deepcopy(frame)

        calculate_kpis(frame)
        calculate_region_performance(frame)
        calculate_product_performance(frame)
        calculate_daily_trends(frame)
        calculate_period_comparison(frame)
        calculate_top_performers(frame)
        calculate_bottom_performers(frame)

        pd.testing.assert_frame_equal(frame, snapshot)
        assert frame.columns.tolist() == snapshot.columns.tolist()
        assert frame.dtypes.tolist() == snapshot.dtypes.tolist()

    def test_original_row_order_preserved(self) -> None:
        frame = make_frame().sample(frac=1.0, random_state=11).reset_index(drop=True)
        snapshot = copy.deepcopy(frame)
        calculate_region_performance(frame)
        pd.testing.assert_frame_equal(frame, snapshot)

    def test_deterministic_repeated_execution(self) -> None:
        frame = make_frame()
        assert calculate_kpis(frame) == calculate_kpis(frame)
        assert calculate_region_performance(frame).equals(
            calculate_region_performance(frame)
        )
        assert calculate_product_performance(frame).equals(
            calculate_product_performance(frame)
        )
        assert calculate_daily_trends(frame).equals(calculate_daily_trends(frame))
        assert calculate_period_comparison(frame) == calculate_period_comparison(frame)
        assert calculate_top_performers(frame) == calculate_top_performers(frame)
        assert calculate_bottom_performers(frame) == calculate_bottom_performers(frame)

    def test_row_order_does_not_affect_results(self) -> None:
        ordered = make_frame()
        shuffled = ordered.sample(frac=1.0, random_state=13).reset_index(drop=True)
        assert calculate_kpis(ordered) == calculate_kpis(shuffled)
        assert calculate_region_performance(ordered).equals(
            calculate_region_performance(shuffled)
        )
        assert calculate_daily_trends(ordered).equals(
            calculate_daily_trends(shuffled)
        )


class TestDemoDatasetEndToEnd:
    """End-to-end analytics over the bundled Phase 1 demo dataset."""

    def test_demo_kpis_execute_and_are_finite(self, demo_df: pd.DataFrame) -> None:
        kpis = calculate_kpis(demo_df)
        flat = [value for value in kpis.values() if not isinstance(value, dict)]
        assert numeric_values_are_finite(flat)
        assert kpis["unique_regions"] == 4
        assert kpis["unique_products"] == 3
        assert kpis["date_range"]["start"] == "2024-01-01"  # type: ignore[index]

    def test_demo_kpis_mathematically_consistent(self, demo_df: pd.DataFrame) -> None:
        kpis = calculate_kpis(demo_df)
        assert kpis["total_units_sold"] == int(demo_df["units_sold"].sum())
        assert kpis["total_revenue"] == round(float(demo_df["revenue"].sum()), 2)
        assert kpis["total_profit"] == round(
            float(demo_df["revenue"].sum() - demo_df["cost"].sum()), 2
        )
        unique_dates = demo_df["date"].nunique()
        assert kpis["average_daily_revenue"] == round(
            float(demo_df["revenue"].sum()) / unique_dates, 2
        )

    def test_demo_region_performance_covers_all_regions(
        self, demo_df: pd.DataFrame
    ) -> None:
        result = calculate_region_performance(demo_df)
        assert len(result) == 4
        assert set(result["region"]) == {"North", "South", "East", "West"}
        assert result["revenue_share_pct"].sum() == pytest.approx(100.0, abs=0.05)
        assert result["units_share_pct"].sum() == pytest.approx(100.0, abs=0.05)

    def test_demo_product_performance_covers_all_products(
        self, demo_df: pd.DataFrame
    ) -> None:
        result = calculate_product_performance(demo_df)
        assert len(result) == 3
        assert set(result["product"]) == {"Widget Pro", "Gadget Plus", "Sensor Lite"}
        assert result["revenue_share_pct"].sum() == pytest.approx(100.0, abs=0.05)

    def test_demo_daily_trends_cover_complete_period(
        self, demo_df: pd.DataFrame
    ) -> None:
        trends = calculate_daily_trends(demo_df)
        expected_days = demo_df["date"].nunique()
        assert len(trends) == expected_days
        assert trends["date"].is_monotonic_increasing
        assert trends["date"].iloc[0] == "2024-01-01"
        expected_last = (
            pd.Timestamp("2024-01-01") + pd.Timedelta(days=expected_days - 1)
        ).strftime("%Y-%m-%d")
        assert trends["date"].iloc[-1] == expected_last
        assert trends["revenue"].sum() == pytest.approx(
            round(float(demo_df["revenue"].sum()), 2), abs=0.05
        )

    def test_demo_period_comparison_executes(self, demo_df: pd.DataFrame) -> None:
        comparison = calculate_period_comparison(demo_df)
        assert comparison["period_1"]["end"] < comparison["period_2"]["start"]  # type: ignore[operator]
        changes = comparison["changes_pct"]
        assert set(changes.keys()) == {  # type: ignore[union-attr]
            "units_change_pct",
            "revenue_change_pct",
            "cost_change_pct",
            "profit_change_pct",
            "margin_change_pct",
            "lead_time_change_pct",
        }
        assert numeric_values_are_finite(list(changes.values()))  # type: ignore[union-attr]

    def test_demo_performers_execute(self, demo_df: pd.DataFrame) -> None:
        top = calculate_top_performers(demo_df)
        bottom = calculate_bottom_performers(demo_df)
        assert len(top["regions"]) == 4
        assert len(top["products"]) == 3
        assert len(bottom["regions"]) == 4
        assert len(bottom["products"]) == 3
        assert top["regions"][0]["region"] == bottom["regions"][-1]["region"]
        assert top["regions"][0]["revenue"] >= bottom["regions"][0]["revenue"]

    def test_demo_results_have_no_nan_or_inf(self, demo_df: pd.DataFrame) -> None:
        for frame in (
            calculate_region_performance(demo_df),
            calculate_product_performance(demo_df),
            calculate_daily_trends(demo_df),
        ):
            numbers = frame.select_dtypes(include=[np.number]).to_numpy()
            assert bool(np.isfinite(numbers).all())

    def test_demo_results_deterministic(self, demo_df: pd.DataFrame) -> None:
        assert calculate_kpis(demo_df) == calculate_kpis(demo_df)
        assert calculate_region_performance(demo_df).equals(
            calculate_region_performance(demo_df)
        )
        assert calculate_daily_trends(demo_df).equals(
            calculate_daily_trends(demo_df)
        )
        assert calculate_period_comparison(demo_df) == calculate_period_comparison(
            demo_df
        )

    def test_demo_caller_frame_not_mutated(self, demo_df: pd.DataFrame) -> None:
        snapshot = copy.deepcopy(demo_df)
        calculate_kpis(demo_df)
        calculate_region_performance(demo_df)
        calculate_daily_trends(demo_df)
        pd.testing.assert_frame_equal(demo_df, snapshot)
