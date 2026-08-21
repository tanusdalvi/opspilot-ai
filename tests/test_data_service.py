"""Tests for the data service (services/data_service.py)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.exceptions import DataValidationError
from services.data_service import (
    get_dataset_info,
    list_datasets,
    load_csv,
    load_dataset,
)

DEMO_FILENAME = "demo_operational_data.csv"
EXPECTED_COLUMNS = [
    "date",
    "region",
    "product",
    "units_sold",
    "revenue",
    "cost",
    "lead_time_days",
]
EXPECTED_ROWS = 8760


def _dataset_names() -> set[str]:
    return {entry["name"] for entry in list_datasets()}


def test_demo_csv_found_by_list_datasets() -> None:
    assert DEMO_FILENAME in _dataset_names()


def test_gitkeep_is_ignored() -> None:
    assert ".gitkeep" not in _dataset_names()


def test_demo_dataset_loads_successfully() -> None:
    df = load_dataset(DEMO_FILENAME)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty


def test_expected_columns_exist() -> None:
    df = load_dataset(DEMO_FILENAME)
    for column in EXPECTED_COLUMNS:
        assert column in df.columns


def test_loaded_demo_csv_has_8760_rows() -> None:
    df = load_dataset(DEMO_FILENAME)
    assert len(df) == EXPECTED_ROWS


@pytest.mark.parametrize(
    "filename",
    ["does_not_exist.csv", "demo_operational_data.txt", ""],
)
def test_nonexistent_or_invalid_dataset_raises(filename: str) -> None:
    with pytest.raises(DataValidationError):
        load_dataset(filename)


@pytest.mark.parametrize(
    "filename",
    [
        "../secret.csv",
        "..\\..\\secret.csv",
        "sub/../../outside.csv",
        "C:/Windows/system.ini",
    ],
)
def test_path_traversal_is_rejected(filename: str) -> None:
    with pytest.raises(DataValidationError):
        load_dataset(filename)


def test_temporary_csv_loads_successfully(tmp_path: Path) -> None:
    csv_path = tmp_path / "tiny.csv"
    pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_csv(
        csv_path, index=False
    )
    df = load_csv(csv_path)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 3


def test_missing_csv_raises(tmp_path: Path) -> None:
    with pytest.raises(DataValidationError):
        load_csv(tmp_path / "missing.csv")


def test_get_dataset_info_returns_correct_counts() -> None:
    df = pd.DataFrame(
        {"a": range(10), "b": range(10, 20), "c": ["x"] * 10}
    )
    info = get_dataset_info(df)
    assert info["row_count"] == 10
    assert info["column_count"] == 3
    assert info["columns"] == ["a", "b", "c"]
    assert info["memory_usage_bytes"] > 0
