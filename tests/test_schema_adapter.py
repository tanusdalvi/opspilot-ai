"""Schema adapter tests: compatibility tiers, mapping disclosure, cleaning.

Covers the Phase 13 dynamic-dataset contract:

* canonical-schema datasets classify FULL and pass through untouched;
* generic date+numeric CSVs classify PARTIAL and are projected onto the
  operational schema with an explicit, deterministic mapping;
* name-evidence mapping wins over positional fallback; positional
  fallback is flagged, never silent;
* missing metrics are synthesized as neutral constants and disclosed
  (affected derived KPIs listed);
* unsupported datasets (no date / no numerics) are rejected with clear,
  actionable reasons;
* row cleaning drops unparseable rows and reports the count;
* the input DataFrame is never mutated.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.schema_adapter import (
    TIER_FULL,
    TIER_PARTIAL,
    TIER_UNSUPPORTED,
    assess_and_adapt,
    profile_columns,
    report_payload,
)

CANONICAL = ["date", "region", "product", "units_sold", "revenue", "cost",
             "lead_time_days"]


def _canonical_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-02", "2025-01-03"],
            "region": ["north", "south", "north"],
            "product": ["alpha", "beta", "alpha"],
            "units_sold": [10, 12, 9],
            "revenue": [100.0, 140.0, 95.0],
            "cost": [60.0, 70.0, 55.0],
            "lead_time_days": [3, 4, 2],
        }
    )


def test_canonical_schema_is_full_tier_unchanged():
    df = _canonical_frame()
    adapted, report = assess_and_adapt(df)
    assert report.tier == TIER_FULL
    assert list(adapted.columns) == CANONICAL
    pd.testing.assert_frame_equal(adapted, df)


def test_generic_sales_csv_is_partial_with_hint_mapping():
    df = pd.DataFrame(
        {
            "order_date": ["2025-01-01", "2025-01-02", "2025-01-03"],
            "store": ["a", "b", "a"],
            "sales_amount": [100.0, 120.0, 90.0],
            "quantity": [5, 6, 4],
        }
    )
    adapted, report = assess_and_adapt(df)
    assert report.tier == TIER_PARTIAL
    assert not report.positional_fallback
    # Name evidence maps sales->revenue and quantity->units_sold.
    assert report.mapping["revenue"] == "sales_amount"
    assert report.mapping["units_sold"] == "quantity"
    assert report.mapping["region"] == "store"
    # cost/lead_time/product were never provided: synthesized + disclosed.
    assert set(report.synthesized) == {"cost", "lead_time_days", "product"}
    assert "total_profit" in report.affected_derived_kpis
    # Adapted frame satisfies the canonical layout exactly.
    assert sorted(adapted.columns) == sorted(CANONICAL)
    # Synthesized metric columns are neutral constants (never fake signals).
    assert (adapted["cost"] == 0).all()
    # Real mapped values survive projection.
    assert adapted["revenue"].tolist() == [100.0, 120.0, 90.0]


def test_unnamed_numerics_use_disclosed_positional_fallback():
    df = pd.DataFrame(
        {
            "d": ["2025-01-01", "2025-01-02"],
            "col_a": [1.0, 2.0],
            "col_b": [10.0, 20.0],
        }
    )
    adapted, report = assess_and_adapt(df)
    assert report.tier == TIER_PARTIAL
    assert report.positional_fallback is True
    assert any("positionally" in reason for reason in report.reasons)
    assert report.mapping["revenue"] == "col_a"
    assert report.mapping["units_sold"] == "col_b"
    assert len(adapted) == 2


def test_no_date_column_is_supported_with_synthetic_date():
    """Type B datasets (numeric + categorical, no date) get a synthetic date."""
    df = pd.DataFrame({"value": [1.0, 2.0], "label": ["x", "y"]})
    adapted, report = assess_and_adapt(df)
    assert adapted is not None
    assert report.tier == TIER_PARTIAL
    assert "synthetic" in " ".join(report.reasons).lower() or "date" in " ".join(report.reasons).lower()
    assert len(adapted) == 2
    assert "date" in adapted.columns


def test_no_numeric_column_is_unsupported_with_reason():
    df = pd.DataFrame({"day": ["2025-01-01"], "label": ["x"]})
    adapted, report = assess_and_adapt(df)
    assert adapted is None
    assert report.tier == TIER_UNSUPPORTED
    assert any("numeric" in reason.lower() for reason in report.reasons)


def test_unparseable_rows_are_dropped_and_counted():
    df = pd.DataFrame(
        {
            "date": ["2025-01-01", "not-a-date", "2025-01-03"],
            "sales": ["10", "20", "oops"],
        }
    )
    adapted, report = assess_and_adapt(df)
    assert report.tier == TIER_PARTIAL
    assert report.dropped_rows == 2
    assert len(adapted) == 1


def test_all_rows_invalid_becomes_unsupported():
    df = pd.DataFrame({"date": ["bad", "worse"], "sales": ["x", "y"]})
    adapted, report = assess_and_adapt(df)
    assert adapted is None
    assert report.tier == TIER_UNSUPPORTED


def test_input_dataframe_is_never_mutated():
    df = pd.DataFrame(
        {
            "order_date": ["2025-01-01", "2025-01-02"],
            "sales_amount": [100.0, 120.0],
        }
    )
    before = df.copy()
    assess_and_adapt(df)
    pd.testing.assert_frame_equal(df, before)


def test_empty_frame_is_unsupported():
    adapted, report = assess_and_adapt(pd.DataFrame())
    assert adapted is None
    assert report.tier == TIER_UNSUPPORTED


def test_profile_columns_kinds():
    df = _canonical_frame()
    kinds = profile_columns(df)
    assert kinds["date"] == "date"
    assert kinds["revenue"] == "numeric"
    assert kinds["region"] == "categorical"


def test_report_payload_is_json_safe():
    df = pd.DataFrame(
        {
            "day": ["2025-01-01", "2025-01-02"],
            "sales": [1.0, 2.0],
        }
    )
    _, report = assess_and_adapt(df)
    payload = report_payload(report)
    assert payload["tier"] == TIER_PARTIAL
    assert isinstance(payload["mapping"], dict)
    assert isinstance(payload["reasons"], list)


def test_partial_projection_feeds_the_real_pipeline():
    """End-to-end guarantee: a projected frame passes the validation gate."""
    from services.validation_service import ensure_valid

    df = pd.DataFrame(
        {
            "timestamp": ["2025-01-01", "2025-01-02", "2025-01-03"],
            "warehouse": ["w1", "w2", "w1"],
            "revenue_usd": [500.0, 650.0, 480.0],
        }
    )
    adapted, report = assess_and_adapt(df)
    assert report.tier == TIER_PARTIAL
    clean = ensure_valid(adapted)  # must not raise
    assert clean["valid"] is True
