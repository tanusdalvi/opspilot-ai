"""Validation service: schema and data-quality checks for ingested DataFrames.

Validates DataFrames against the canonical operational dataset schema and
returns a structured report. The service never mutates the caller's
DataFrame and never raises for data-quality problems; use
``ensure_valid`` to turn a failing report into a ``DataValidationError``.

Validation policy
-----------------
* Missing required columns are **errors**.
* Unexpected extra columns are **warnings** (data remains usable).
* Null values in any known column are **errors**.
* Values in text columns must be strings (**errors** otherwise).
* Values in numeric columns must be real numbers, not booleans
  (**errors** otherwise).
* Values in date columns must parse as dates (**errors** otherwise).
* Numeric values outside their configured range are **errors**.
* Fully duplicated rows are **warnings** only: duplicates do not make a
  dataset invalid because they can be resolved downstream by deduplication.
"""

from __future__ import annotations

import numbers

import numpy as np
import pandas as pd

from core.exceptions import DataValidationError

# --- Canonical dataset schema ----------------------------------------------

REQUIRED_COLUMNS: tuple[str, ...] = (
    "date",
    "region",
    "product",
    "units_sold",
    "revenue",
    "cost",
    "lead_time_days",
)

TEXT_COLUMNS: frozenset[str] = frozenset({"region", "product"})

NUMERIC_COLUMNS: frozenset[str] = frozenset(
    {"units_sold", "revenue", "cost", "lead_time_days"}
)

DATE_COLUMNS: frozenset[str] = frozenset({"date"})

# Inclusive bounds as ``(min, max)`` where ``None`` means unbounded.
NUMERIC_RANGES: dict[str, tuple[float | None, float | None]] = {
    "units_sold": (0.0, None),
    "revenue": (0.0, None),
    "cost": (0.0, None),
    "lead_time_days": (0.0, None),
}

# Maximum row indices embedded per issue so reports stay bounded.
MAX_SAMPLED_ROWS: int = 20

# --- Issue codes ------------------------------------------------------------

CODE_MISSING_COLUMNS = "MISSING_COLUMNS"
CODE_UNEXPECTED_COLUMNS = "UNEXPECTED_COLUMNS"
CODE_NULL_VALUES = "NULL_VALUES"
CODE_INVALID_TEXT_TYPE = "INVALID_TEXT_TYPE"
CODE_INVALID_NUMERIC_TYPE = "INVALID_NUMERIC_TYPE"
CODE_INVALID_DATE = "INVALID_DATE"
CODE_OUT_OF_RANGE = "OUT_OF_RANGE"
CODE_DUPLICATE_ROWS = "DUPLICATE_ROWS"


def _make_issue(
    code: str,
    message: str,
    column: str | None = None,
    rows: list[int] | None = None,
) -> dict[str, object]:
    """Build one structured issue entry for the validation report."""
    return {
        "code": code,
        "message": message,
        "column": column,
        "rows": list(rows or []),
    }


def _sample_rows(mask: pd.Series) -> list[int]:
    """Return the (capped) positional indices where ``mask`` is true."""
    positions = mask[mask].index.tolist()
    return [int(index) for index in positions[:MAX_SAMPLED_ROWS]]


def _validate_columns(df: pd.DataFrame) -> tuple[list[dict[str, object]], list[dict[str, object]], set[str]]:
    """Check required/extra columns.

    Returns ``(errors, warnings, usable_columns)`` where ``usable_columns``
    is the intersection of the DataFrame columns with the known schema.
    """
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []

    present = set(map(str, df.columns))
    expected = set(REQUIRED_COLUMNS)
    missing = sorted(expected - present)
    unexpected = sorted(present - expected)

    if missing:
        errors.append(
            _make_issue(
                CODE_MISSING_COLUMNS,
                f"Missing required columns: {', '.join(missing)}",
            )
        )
    if unexpected:
        warnings.append(
            _make_issue(
                CODE_UNEXPECTED_COLUMNS,
                f"Unexpected extra columns ignored by validation: "
                f"{', '.join(unexpected)}",
            )
        )

    return errors, warnings, present & expected


def _is_null(value: object) -> bool:
    """Return ``True`` for pandas/numpy missing values."""
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return False
    return bool(result) if isinstance(result, bool) else False


def _is_numpy_numeric(series: pd.Series) -> bool:
    """Return ``True`` for plain numpy numeric dtypes (never nullable)."""
    dtype = series.dtype
    return (
        pd.api.types.is_float_dtype(dtype)
        or pd.api.types.is_signed_integer_dtype(dtype)
        or pd.api.types.is_unsigned_integer_dtype(dtype)
    ) and not isinstance(dtype, pd.api.extensions.ExtensionDtype)


# Every scalar of these dtypes is a registered ``numbers.Real`` and never a
# ``bool``, so the per-value type predicate is vacuously satisfied.
_NUMPY_NUMERIC_KINDS = frozenset("fiu")


def _validate_text_column(series: pd.Series, column: str) -> list[dict[str, object]]:
    """Report non-null values in ``column`` that are not strings.

    Vectorized over ``not null``; the string-type predicate runs once per
    non-null value via a comprehension over raw values (identical to the
    historical element-wise semantics for every input type).
    """
    not_null = ~series.isna()
    if bool(not_null.any()):
        raw = series.to_numpy()
        null_values = pd.isna(raw)
        bad_values = np.array(
            [not isinstance(v, str) for v in raw], dtype=bool
        )
        mask = pd.Series(bad_values & ~null_values, index=series.index)
    else:
        mask = pd.Series(False, index=series.index)
    if not mask.any():
        return []
    return [
        _make_issue(
            CODE_INVALID_TEXT_TYPE,
            f"Column '{column}' contains {int(mask.sum())} non-string value(s)",
            column=column,
            rows=_sample_rows(mask),
        )
    ]


def _is_valid_number(value: object) -> bool:
    """Return ``True`` when ``value`` is a real number but not a boolean."""
    if isinstance(value, (bool,)) or _is_null(value):
        return False
    return isinstance(value, numbers.Real)


def _validate_numeric_column(series: pd.Series, column: str) -> list[dict[str, object]]:
    """Report non-null values in ``column`` that are not numeric.

    Plain numpy numeric columns are valid by construction (fast path);
    everything else falls back to the exact per-value predicate.
    """
    issues: list[dict[str, object]] = []
    fast_valid = (
        _is_numpy_numeric(series)
        or series.empty
    )
    if fast_valid:
        return issues

    def bad(value: object) -> bool:
        return not _is_null(value) and not _is_valid_number(value)

    mask = series.map(bad)
    if mask.any():
        issues.append(
            _make_issue(
                CODE_INVALID_NUMERIC_TYPE,
                f"Column '{column}' contains {int(mask.sum())} non-numeric value(s)",
                column=column,
                rows=_sample_rows(mask),
            )
        )
    return issues


def _validate_numeric_range(series: pd.Series, column: str) -> list[dict[str, object]]:
    """Report numeric values outside the configured inclusive bounds.

    Fast path compares whole numpy arrays at C speed; NaN compares
    ``False`` against both bounds exactly like the per-value predicate.
    """
    minimum, maximum = NUMERIC_RANGES[column]
    if minimum is None and maximum is None:
        return []

    if _is_numpy_numeric(series) and series.dtype.kind in _NUMPY_NUMERIC_KINDS:
        values = series.to_numpy()
        exceeds = np.zeros(len(values), dtype=bool)
        if minimum is not None:
            exceeds |= values < minimum
        if maximum is not None:
            exceeds |= values > maximum
        mask = pd.Series(exceeds, index=series.index)
    else:

        def out_of_range(value: object) -> bool:
            if not _is_valid_number(value):
                return False
            if minimum is not None and value < minimum:
                return True
            return maximum is not None and value > maximum

        mask = series.map(out_of_range)

    if not mask.any():
        return []
    bound_text = f"[{minimum}, {maximum}]".replace(", None]", ", inf]")
    return [
        _make_issue(
            CODE_OUT_OF_RANGE,
            f"Column '{column}' has {int(mask.sum())} value(s) outside range "
            f"{bound_text}",
            column=column,
            rows=_sample_rows(mask),
        )
    ]


def _parse_dates(series: pd.Series) -> pd.Series:
    """Parse ``series`` to datetimes, coercing unparseable values to NaT.

    Default parsing infers one format from the first value, so values
    written in another layout silently become NaT. When that happens the
    parse is retried with ``format="mixed"`` so differently formatted but
    genuine dates still validate.
    """
    parsed = pd.to_datetime(series, errors="coerce")
    if bool((parsed.isna() & ~series.isna()).any()):
        try:
            mixed = pd.to_datetime(series, errors="coerce", format="mixed")
        except (ValueError, TypeError):
            return parsed
        improved = parsed.isna() & mixed.notna()
        parsed = parsed.where(~improved, mixed)
    return parsed


def _validate_date_column(series: pd.Series, column: str) -> list[dict[str, object]]:
    """Report non-null values that cannot be parsed as dates."""
    parsed = _parse_dates(series)
    mask = parsed.isna() & ~series.isna()
    if not bool(mask.any()):
        return []
    return [
        _make_issue(
            CODE_INVALID_DATE,
            f"Column '{column}' contains {int(mask.sum())} unparseable "
            f"date value(s)",
            column=column,
            rows=_sample_rows(mask),
        )
    ]


def _validate_duplicates(df: pd.DataFrame) -> list[dict[str, object]]:
    """Report fully duplicated rows as warnings."""
    duplicate_mask = df.duplicated(keep=False)
    count = int(duplicate_mask.sum())
    if count == 0:
        return []
    return [
        _make_issue(
            CODE_DUPLICATE_ROWS,
            f"Found {count} row(s) participating in exact duplicates "
            f"(warning only; resolve via downstream deduplication)",
            rows=_sample_rows(duplicate_mask),
        )
    ]


def validate_dataframe(df: pd.DataFrame) -> dict[str, object]:
    """Validate a DataFrame against the operational dataset schema.

    Args:
        df: The DataFrame to validate. It is never mutated.

    Returns:
        A structured report dictionary::

            {
                "valid": bool,
                "row_count": int,
                "column_count": int,
                "error_count": int,
                "warning_count": int,
                "errors": [{"code", "message", "column", "rows"}, ...],
                "warnings": [...],
            }

    Raises:
        DataValidationError: If ``df`` is not a pandas DataFrame.
    """
    if not isinstance(df, pd.DataFrame):
        raise DataValidationError(
            f"Expected a pandas DataFrame, got {type(df).__name__}"
        )

    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []

    schema_errors, schema_warnings, usable_columns = _validate_columns(df)
    errors.extend(schema_errors)
    warnings.extend(schema_warnings)

    # Row-level checks run on every column that exists in the schema, even
    # when other required columns are missing, so callers get full feedback.
    for column in sorted(usable_columns):
        series = df[column]
        if column in TEXT_COLUMNS:
            errors.extend(_validate_text_column(series, column))
        elif column in NUMERIC_COLUMNS:
            type_issues = _validate_numeric_column(series, column)
            errors.extend(type_issues)
            if not type_issues:
                errors.extend(_validate_numeric_range(series, column))
        elif column in DATE_COLUMNS:
            errors.extend(_validate_date_column(series, column))

        null_mask = series.isna()
        if bool(null_mask.any()):
            errors.append(
                _make_issue(
                    CODE_NULL_VALUES,
                    f"Column '{column}' contains {int(null_mask.sum())} null value(s)",
                    column=column,
                    rows=_sample_rows(null_mask),
                )
            )

    if len(df.columns) > 0:
        warnings.extend(_validate_duplicates(df))

    return {
        "valid": len(errors) == 0,
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def ensure_valid(df: pd.DataFrame) -> dict[str, object]:
    """Validate ``df`` and raise ``DataValidationError`` if it is invalid.

    Args:
        df: The DataFrame to validate. It is never mutated.

    Returns:
        The structured validation report from ``validate_dataframe``.

    Raises:
        DataValidationError: If the report contains any errors. The message
            lists every failing issue code with its first message.
    """
    report = validate_dataframe(df)
    if report["valid"]:
        return report
    details = "; ".join(
        f"{issue['code']}: {issue['message']}"  # type: ignore[index]
        for issue in report["errors"]  # type: ignore[index]
    )
    raise DataValidationError(f"DataFrame failed validation ({details})")
