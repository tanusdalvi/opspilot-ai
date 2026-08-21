"""Tests for the validation service (services/validation_service.py)."""

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
from services.data_service import load_dataset
from services.validation_service import (
    CODE_DUPLICATE_ROWS,
    CODE_INVALID_DATE,
    CODE_INVALID_NUMERIC_TYPE,
    CODE_INVALID_TEXT_TYPE,
    CODE_MISSING_COLUMNS,
    CODE_NULL_VALUES,
    CODE_OUT_OF_RANGE,
    CODE_UNEXPECTED_COLUMNS,
    MAX_SAMPLED_ROWS,
    REQUIRED_COLUMNS,
    ensure_valid,
    validate_dataframe,
)


def make_valid_frame(rows: int = 3) -> pd.DataFrame:
    """Build a small DataFrame that satisfies the full schema."""
    return pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"][:rows],
            "region": ["North", "South", "West"][:rows],
            "product": ["Widget Pro", "Widget Pro", "Gadget"][:rows],
            "units_sold": [146, 115, 159][:rows],
            "revenue": [3844.5, 2781.36, 3828.75][:rows],
            "cost": [1998.78, 1694.13, 2278.53][:rows],
            "lead_time_days": [7, 7, 6][:rows],
        }
    )


def codes(report: dict[str, object]) -> list[str]:
    """Extract issue codes from the errors of a report."""
    return [str(issue["code"]) for issue in report["errors"]]  # type: ignore[index]


def warning_codes(report: dict[str, object]) -> list[str]:
    """Extract issue codes from the warnings of a report."""
    return [str(issue["code"]) for issue in report["warnings"]]  # type: ignore[index]


class TestValidData:
    def test_valid_dataframe_passes(self) -> None:
        report = validate_dataframe(make_valid_frame())
        assert report["valid"] is True
        assert report["error_count"] == 0
        assert report["warning_count"] == 0
        assert report["errors"] == []
        assert report["warnings"] == []

    def test_report_structure(self) -> None:
        report = validate_dataframe(make_valid_frame())
        expected_keys = {
            "valid",
            "row_count",
            "column_count",
            "error_count",
            "warning_count",
            "errors",
            "warnings",
        }
        assert expected_keys <= set(report.keys())
        assert report["row_count"] == 3
        assert report["column_count"] == len(REQUIRED_COLUMNS)

    def test_empty_frame_with_full_schema_is_valid(self) -> None:
        frame = make_valid_frame(0)
        report = validate_dataframe(frame)
        assert report["valid"] is True

    def test_issue_entries_are_structured(self) -> None:
        frame = make_valid_frame()
        frame.loc[0, "region"] = np.nan
        report = validate_dataframe(frame)
        issue = report["errors"][0]  # type: ignore[index]
        assert set(issue.keys()) == {"code", "message", "column", "rows"}  # type: ignore[attr-defined]
        assert issue["column"] == "region"  # type: ignore[index]
        assert issue["rows"] == [0]  # type: ignore[index]


class TestSchemaValidation:
    def test_missing_column_is_error(self) -> None:
        frame = make_valid_frame().drop(columns=["revenue"])
        report = validate_dataframe(frame)
        assert report["valid"] is False
        assert CODE_MISSING_COLUMNS in codes(report)

    def test_missing_columns_listed_in_message(self) -> None:
        frame = make_valid_frame().drop(columns=["revenue", "cost"])
        report = validate_dataframe(frame)
        issue = next(
            issue
            for issue in report["errors"]  # type: ignore[union-attr,index]
            if issue["code"] == CODE_MISSING_COLUMNS  # type: ignore[union-attr]
        )
        assert "revenue" in str(issue["message"])
        assert "cost" in str(issue["message"])

    def test_unexpected_column_is_warning_not_error(self) -> None:
        frame = make_valid_frame()
        frame["extra_note"] = ["a", "b", "c"]
        report = validate_dataframe(frame)
        assert CODE_UNEXPECTED_COLUMNS not in codes(report)
        assert CODE_UNEXPECTED_COLUMNS in warning_codes(report)
        assert report["valid"] is True

    def test_missing_and_unexpected_together(self) -> None:
        frame = make_valid_frame().drop(columns=["date"])
        frame["surplus"] = 1
        report = validate_dataframe(frame)
        assert CODE_MISSING_COLUMNS in codes(report)
        assert CODE_UNEXPECTED_COLUMNS in warning_codes(report)
        assert report["valid"] is False

    def test_empty_frame_without_columns_reports_missing_schema(self) -> None:
        report = validate_dataframe(pd.DataFrame())
        assert report["valid"] is False
        assert CODE_MISSING_COLUMNS in codes(report)


class TestNullDetection:
    @pytest.mark.parametrize("column", sorted(REQUIRED_COLUMNS))
    def test_null_in_any_required_column_is_error(self, column: str) -> None:
        frame = make_valid_frame()
        if column in ("units_sold",):
            frame.loc[1, column] = None
        elif column in ("revenue", "cost"):
            frame.loc[1, column] = np.nan
        else:
            frame.loc[1, column] = None
        report = validate_dataframe(frame)
        assert CODE_NULL_VALUES in codes(report), f"column={column}"
        assert report["valid"] is False

    def test_multiple_nulls_counted(self) -> None:
        frame = make_valid_frame()
        frame.loc[[0, 2], "product"] = None
        report = validate_dataframe(frame)
        null_issues = [
            issue
            for issue in report["errors"]  # type: ignore[union-attr,index]
            if issue["code"] == CODE_NULL_VALUES and issue["column"] == "product"  # type: ignore[union-attr]
        ]
        assert len(null_issues) == 1
        assert "2" in str(null_issues[0]["message"])
        assert null_issues[0]["rows"] == [0, 2]


class TestTypeValidation:
    def test_numeric_in_text_column_is_error(self) -> None:
        frame = make_valid_frame()
        frame["region"] = frame["region"].astype(object)
        frame.loc[0, "region"] = 42
        report = validate_dataframe(frame)
        assert CODE_INVALID_TEXT_TYPE in codes(report)

    def test_string_in_numeric_column_is_error(self) -> None:
        frame = make_valid_frame()
        frame["units_sold"] = frame["units_sold"].astype(object)
        frame.loc[1, "units_sold"] = "lots"
        report = validate_dataframe(frame)
        assert CODE_INVALID_NUMERIC_TYPE in codes(report)

    def test_boolean_in_numeric_column_is_error(self) -> None:
        frame = make_valid_frame()
        frame["lead_time_days"] = frame["lead_time_days"].astype(object)
        frame.loc[0, "lead_time_days"] = True
        report = validate_dataframe(frame)
        assert CODE_INVALID_NUMERIC_TYPE in codes(report)

    def test_type_error_suppresses_range_check_for_same_column(self) -> None:
        frame = make_valid_frame()
        frame["units_sold"] = frame["units_sold"].astype(object)
        frame.loc[0, "units_sold"] = "bad"
        frame.loc[1, "units_sold"] = -5
        report = validate_dataframe(frame)
        assert CODE_INVALID_NUMERIC_TYPE in codes(report)
        assert CODE_OUT_OF_RANGE not in codes(report)

    def test_other_columns_still_range_checked_after_type_error(self) -> None:
        frame = make_valid_frame()
        frame["units_sold"] = frame["units_sold"].astype(object)
        frame.loc[0, "units_sold"] = "bad"
        frame.loc[1, "cost"] = -10.0
        report = validate_dataframe(frame)
        assert CODE_INVALID_NUMERIC_TYPE in codes(report)
        assert any(
            issue["code"] == CODE_OUT_OF_RANGE and issue["column"] == "cost"
            for issue in report["errors"]  # type: ignore[union-attr,index]
        )


class TestDateParsing:
    def test_invalid_date_is_error(self) -> None:
        frame = make_valid_frame()
        frame.loc[2, "date"] = "not-a-date"
        report = validate_dataframe(frame)
        assert CODE_INVALID_DATE in codes(report)
        date_issues = [
            issue
            for issue in report["errors"]  # type: ignore[union-attr,index]
            if issue["code"] == CODE_INVALID_DATE  # type: ignore[union-attr]
        ]
        assert date_issues[0]["rows"] == [2]

    def test_mixed_date_formats_parse(self) -> None:
        frame = make_valid_frame()
        frame["date"] = ["2024-01-01", "01/15/2024", "March 5, 2024"]
        report = validate_dataframe(frame)
        assert CODE_INVALID_DATE not in codes(report)
        assert report["valid"] is True


class TestNumericRanges:
    @pytest.mark.parametrize(
        ("column", "value"),
        [
            ("units_sold", -1),
            ("revenue", -0.01),
            ("cost", -100.0),
            ("lead_time_days", -3),
        ],
    )
    def test_negative_values_out_of_range(self, column: str, value: float) -> None:
        frame = make_valid_frame()
        frame.loc[0, column] = value
        report = validate_dataframe(frame)
        range_issues = [
            issue
            for issue in report["errors"]  # type: ignore[union-attr,index]
            if issue["code"] == CODE_OUT_OF_RANGE  # type: ignore[union-attr]
        ]
        assert len(range_issues) == 1
        assert range_issues[0]["column"] == column
        assert range_issues[0]["rows"] == [0]

    def test_zero_and_positive_values_in_range(self) -> None:
        frame = make_valid_frame()
        for column in ("units_sold", "revenue", "cost", "lead_time_days"):
            frame[column] = 0
        report = validate_dataframe(frame)
        assert CODE_OUT_OF_RANGE not in codes(report)
        assert report["valid"] is True


class TestDuplicatePolicy:
    def test_exact_duplicates_are_warnings_only(self) -> None:
        duplicated = pd.concat([make_valid_frame(), make_valid_frame()], ignore_index=True)
        report = validate_dataframe(duplicated)
        assert CODE_DUPLICATE_ROWS in warning_codes(report)
        assert report["valid"] is True

    def test_duplicate_warning_captures_row_indices(self) -> None:
        duplicated = pd.concat([make_valid_frame(), make_valid_frame()], ignore_index=True)
        report = validate_dataframe(duplicated)
        issue = next(
            issue
            for issue in report["warnings"]  # type: ignore[union-attr,index]
            if issue["code"] == CODE_DUPLICATE_ROWS  # type: ignore[union-attr]
        )
        assert sorted(issue["rows"]) == [0, 1, 2, 3, 4, 5]  # type: ignore[index]

    def test_unique_rows_produce_no_duplicate_warning(self) -> None:
        report = validate_dataframe(make_valid_frame())
        assert CODE_DUPLICATE_ROWS not in warning_codes(report)

    def test_row_sampling_is_capped(self) -> None:
        big = pd.concat([make_valid_frame()] * (MAX_SAMPLED_ROWS + 5), ignore_index=True)
        report = validate_dataframe(big)
        duplicate_issue = next(
            issue
            for issue in report["warnings"]  # type: ignore[union-attr,index]
            if issue["code"] == CODE_DUPLICATE_ROWS  # type: ignore[union-attr]
        )
        assert len(duplicate_issue["rows"]) == MAX_SAMPLED_ROWS  # type: ignore[index]


class TestErrorHandling:
    def test_non_dataframe_raises_data_validation_error(self) -> None:
        with pytest.raises(DataValidationError):
            validate_dataframe({"date": []})  # type: ignore[arg-type]

    def test_ensure_valid_returns_report_for_good_data(self) -> None:
        report = ensure_valid(make_valid_frame())
        assert report["valid"] is True

    def test_ensure_valid_raises_on_invalid_data(self) -> None:
        frame = make_valid_frame().drop(columns=["date"])
        with pytest.raises(DataValidationError) as excinfo:
            ensure_valid(frame)
        assert "MISSING_COLUMNS" in str(excinfo.value)

    def test_ensure_valid_raises_with_issue_details(self) -> None:
        frame = make_valid_frame()
        frame.loc[0, "revenue"] = -1.0
        with pytest.raises(DataValidationError) as excinfo:
            ensure_valid(frame)
        assert "OUT_OF_RANGE" in str(excinfo.value)


class TestPandasCompatibilityAndSafety:
    def test_caller_dataframe_is_never_mutated(self) -> None:
        frame = make_valid_frame()
        frame.loc[0, "revenue"] = -5.0
        frame.loc[1, "date"] = "garbage"
        snapshot = copy.deepcopy(frame)

        validate_dataframe(frame)

        pd.testing.assert_frame_equal(frame, snapshot)

    def test_validation_runs_repeatedly_on_same_frame(self) -> None:
        frame = make_valid_frame()
        first = validate_dataframe(frame)
        second = validate_dataframe(frame)
        assert first == second

    def test_demo_dataset_end_to_end(self) -> None:
        df = load_dataset("demo_operational_data.csv")
        report = validate_dataframe(df)
        assert report["valid"] is True, report["errors"]
