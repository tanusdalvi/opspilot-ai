"""Regression tests for capability-based dataset analysis (Phase 14).

Tests that non-date datasets (Types B, C, D, E) are handled correctly
by the capability profile and schema adapter.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.capability_service import build_capability_profile, CapabilityProfile
from services.schema_adapter import assess_and_adapt, TIER_PARTIAL, TIER_UNSUPPORTED
from app import orchestrator


# --- Capability profile tests ---


class TestCapabilityProfile:
    def test_type_a_date_and_numeric(self):
        df = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02"],
            "value": [1.0, 2.0],
        })
        profile = build_capability_profile(df)
        assert profile.dataset_class == "A"
        assert profile.has_date is True
        assert profile.has_numeric is True
        assert profile.time_series_analysis is True
        assert profile.anomaly_detection is True
        assert profile.finding_generation is True

    def test_type_b_numeric_and_categorical(self):
        df = pd.DataFrame({
            "score": [1.0, 2.0, 3.0],
            "category": ["a", "b", "c"],
        })
        profile = build_capability_profile(df)
        assert profile.dataset_class == "B"
        assert profile.has_date is False
        assert profile.has_numeric is True
        assert profile.has_categorical is True
        assert profile.time_series_analysis is False
        assert profile.distribution_analysis is True
        assert profile.segment_comparison is True
        assert profile.finding_generation is True

    def test_type_c_numeric_only(self):
        df = pd.DataFrame({
            "col_a": [1.0, 2.0, 3.0],
            "col_b": [4.0, 5.0, 6.0],
        })
        profile = build_capability_profile(df)
        assert profile.dataset_class == "C"
        assert profile.has_date is False
        assert profile.has_numeric is True
        assert profile.has_categorical is False
        assert profile.distribution_analysis is True
        assert profile.outlier_detection is True
        assert profile.correlation_analysis is True
        assert profile.finding_generation is True

    def test_type_d_categorical_with_date(self):
        df = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02"],
            "category": ["a", "b"],
        })
        profile = build_capability_profile(df)
        assert profile.dataset_class == "D"
        assert profile.has_date is True
        assert profile.has_numeric is False
        assert profile.time_series_analysis is True
        assert "anomaly_detection" in profile.unavailable_capabilities

    def test_type_e_empty(self):
        df = pd.DataFrame()
        profile = build_capability_profile(df)
        assert profile.dataset_class == "E"
        assert profile.finding_generation is False

    def test_type_e_categorical_only(self):
        df = pd.DataFrame({
            "color": ["red", "blue", "green"],
            "size": ["small", "medium", "large"],
        })
        profile = build_capability_profile(df)
        assert profile.dataset_class == "E"
        assert profile.finding_generation is False

    def test_to_dict_is_json_safe(self):
        df = pd.DataFrame({"value": [1.0, 2.0], "label": ["a", "b"]})
        profile = build_capability_profile(df)
        d = profile.to_dict()
        assert isinstance(d, dict)
        assert "dataset_class" in d
        assert "capabilities" in d
        assert isinstance(d["capabilities"], dict)


# --- Schema adapter integration tests ---


class TestCapabilityAwareAdapt:
    def test_type_b_gets_synthetic_date(self):
        df = pd.DataFrame({
            "score": [1.0, 2.0, 3.0],
            "category": ["a", "b", "c"],
        })
        adapted, report = assess_and_adapt(df)
        assert adapted is not None
        assert report.tier == TIER_PARTIAL
        assert "date" in adapted.columns
        assert len(adapted) == 3

    def test_type_c_gets_synthetic_date(self):
        df = pd.DataFrame({
            "col_a": [1.0, 2.0, 3.0],
            "col_b": [4.0, 5.0, 6.0],
        })
        adapted, report = assess_and_adapt(df)
        assert adapted is not None
        assert report.tier == TIER_PARTIAL
        assert "date" in adapted.columns

    def test_type_d_rejected(self):
        df = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02"],
            "category": ["a", "b"],
        })
        adapted, report = assess_and_adapt(df)
        assert adapted is None
        assert report.tier == TIER_UNSUPPORTED

    def test_type_e_rejected(self):
        df = pd.DataFrame({
            "color": ["red", "blue"],
        })
        adapted, report = assess_and_adapt(df)
        assert adapted is None
        assert report.tier == TIER_UNSUPPORTED


# --- Pipeline integration tests ---


class TestCapabilityPipeline:
    def test_type_b_runs_pipeline(self):
        df = pd.DataFrame({
            "score": [10.0, 20.0, 30.0, 40.0, 50.0],
            "category": ["a", "b", "a", "b", "a"],
        })
        artifacts = orchestrator.run_pipeline(df, dataset_name="test_b")
        assert isinstance(artifacts, orchestrator.AnalysisArtifacts)
        assert artifacts.capability_profile["dataset_class"] == "B"
        assert artifacts.capability_profile["has_date"] is False
        assert artifacts.daily_trends.empty

    def test_type_c_runs_pipeline(self):
        df = pd.DataFrame({
            "col_a": [1.0, 2.0, 3.0, 4.0, 5.0],
            "col_b": [5.0, 4.0, 3.0, 2.0, 1.0],
        })
        artifacts = orchestrator.run_pipeline(df, dataset_name="test_c")
        assert isinstance(artifacts, orchestrator.AnalysisArtifacts)
        assert artifacts.capability_profile["dataset_class"] == "C"
        assert artifacts.period_comparison is not None

    def test_type_e_rejected(self):
        df = pd.DataFrame({"color": ["red", "blue"]})
        with pytest.raises(Exception):
            orchestrator.run_pipeline(df)

    def test_type_a_unchanged(self):
        df = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "region": ["R0", "R0", "R0"],
            "product": ["P0", "P0", "P0"],
            "units_sold": [100, 110, 120],
            "revenue": [1000, 1100, 1200],
            "cost": [600, 660, 720],
            "lead_time_days": [3.0, 3.0, 3.0],
        })
        artifacts = orchestrator.run_pipeline(df, dataset_name="test_a")
        assert artifacts.capability_profile["dataset_class"] == "A"
        assert not artifacts.daily_trends.empty
