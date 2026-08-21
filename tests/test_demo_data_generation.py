"""Tests for the Phase 1 demo data generator (scripts/generate_demo_data.py)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_demo_data import (
    LEAD_TIME_MAX,
    NUM_DAYS,
    PRODUCTS,
    REGIONS,
    REQUIRED_COLUMNS,
    generate_demo_data,
    save_demo_data,
)


def test_generated_csv_file_is_created(tmp_path: Path) -> None:
    df = generate_demo_data()
    output_path = tmp_path / "nested" / "demo_operational_data.csv"
    result = save_demo_data(df, output_path)
    assert result == output_path
    assert output_path.is_file()
    reloaded = pd.read_csv(output_path)
    assert list(reloaded.columns) == REQUIRED_COLUMNS
    assert len(reloaded) == len(df)


def test_required_columns_present() -> None:
    df = generate_demo_data()
    assert list(df.columns) == REQUIRED_COLUMNS


def test_row_count_at_least_1000() -> None:
    df = generate_demo_data()
    assert len(df) >= 1000
    assert len(df) == NUM_DAYS * len(REGIONS) * len(PRODUCTS)


def test_multiple_regions_and_products() -> None:
    df = generate_demo_data()
    assert set(df["region"].unique()) == set(REGIONS)
    assert set(df["product"].unique()) == set(PRODUCTS)
    assert df.groupby(["region", "product"]).size().eq(NUM_DAYS).all()


def test_dates_are_valid_daily_range() -> None:
    df = generate_demo_data()
    dates = pd.to_datetime(df["date"])
    assert dates.min() == pd.Timestamp("2024-01-01")
    assert (dates.max() - dates.min()).days == NUM_DAYS - 1


def test_values_are_valid() -> None:
    df = generate_demo_data()
    assert (df["units_sold"] > 0).all()
    assert pd.api.types.is_integer_dtype(df["units_sold"])
    assert (df["revenue"] > 0).all()
    assert (df["cost"] > 0).all()
    assert pd.api.types.is_numeric_dtype(df["revenue"])
    assert pd.api.types.is_numeric_dtype(df["cost"])
    assert (df["lead_time_days"] >= 1).all()
    assert (df["lead_time_days"] <= LEAD_TIME_MAX).all()
    assert pd.api.types.is_integer_dtype(df["lead_time_days"])
    assert np.isfinite(df["revenue"]).all()
    assert np.isfinite(df["cost"]).all()


def test_revenue_and_cost_consistent_with_units_sold() -> None:
    df = generate_demo_data()
    implied_price = df["revenue"] / df["units_sold"]
    implied_unit_cost = df["cost"] / df["units_sold"]
    assert implied_price.between(1.0, 100.0).all()
    assert implied_unit_cost.between(1.0, 60.0).all()
    assert (df["revenue"] > df["cost"]).all()


def test_variation_and_trends_exist_for_analysis() -> None:
    df = generate_demo_data()
    units = df["units_sold"]
    assert units.nunique() > 50
    assert units.std() > 0
    monthly = df.assign(month=pd.to_datetime(df["date"]).dt.to_period("M")).groupby(
        "month"
    )["units_sold"].sum()
    first_half = monthly.iloc[:12].mean()
    second_half = monthly.iloc[12:].mean()
    assert second_half > first_half


def test_deterministic_generation(tmp_path: Path) -> None:
    df_first = generate_demo_data()
    df_second = generate_demo_data()
    pd.testing.assert_frame_equal(df_first, df_second)

    path_a = tmp_path / "a.csv"
    path_b = tmp_path / "b.csv"
    save_demo_data(df_first, path_a)
    save_demo_data(df_second, path_b)
    assert path_a.read_bytes() == path_b.read_bytes()
