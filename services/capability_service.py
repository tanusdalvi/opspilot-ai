"""Capability-based dataset analysis profile (Phase 14).

Determines what analysis OpsPilot can perform on any given dataset,
without requiring a specific schema. The system inspects column types
and data characteristics to derive a capability profile.

Dataset classes:
  A: date + numeric       → full time-series analysis
  B: numeric + categorical, no date → segment/outlier analysis
  C: numeric only         → distribution/outlier analysis
  D: categorical + date, no numeric → frequency/composition analysis
  E: insufficient         → rejected with honest explanation
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from services.schema_adapter import (
    _column_kind,
    _date_fraction,
    _numeric_fraction,
    profile_columns,
)


@dataclass
class CapabilityProfile:
    """Determines what analysis is possible for a dataset."""

    # Column classification
    has_date: bool = False
    has_numeric: bool = False
    has_categorical: bool = False

    date_columns: list[str] = field(default_factory=list)
    numeric_columns: list[str] = field(default_factory=list)
    categorical_columns: list[str] = field(default_factory=list)
    text_columns: list[str] = field(default_factory=list)

    # Row/column counts
    row_count: int = 0
    column_count: int = 0

    # Derived capabilities
    time_series_analysis: bool = False
    anomaly_detection: bool = False
    trend_analysis: bool = False
    period_comparison: bool = False
    distribution_analysis: bool = False
    segment_comparison: bool = False
    outlier_detection: bool = False
    correlation_analysis: bool = False
    category_frequency: bool = False
    visualization: bool = False
    finding_generation: bool = False
    recommendation_generation: bool = False

    # Human-readable status
    dataset_class: str = "E"
    classification_reasons: list[str] = field(default_factory=list)
    unavailable_capabilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dataset_class": self.dataset_class,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "has_date": self.has_date,
            "has_numeric": self.has_numeric,
            "has_categorical": self.has_categorical,
            "date_columns": self.date_columns,
            "numeric_columns": self.numeric_columns,
            "categorical_columns": self.categorical_columns,
            "capabilities": {
                "time_series_analysis": self.time_series_analysis,
                "anomaly_detection": self.anomaly_detection,
                "trend_analysis": self.trend_analysis,
                "period_comparison": self.period_comparison,
                "distribution_analysis": self.distribution_analysis,
                "segment_comparison": self.segment_comparison,
                "outlier_detection": self.outlier_detection,
                "correlation_analysis": self.correlation_analysis,
                "category_frequency": self.category_frequency,
                "visualization": self.visualization,
                "finding_generation": self.finding_generation,
                "recommendation_generation": self.recommendation_generation,
            },
            "classification_reasons": self.classification_reasons,
            "unavailable_capabilities": self.unavailable_capabilities,
        }


def build_capability_profile(df: pd.DataFrame) -> CapabilityProfile:
    """Derive a capability profile from the actual dataset structure.

    This is deterministic and does not modify the input DataFrame.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return CapabilityProfile(
            dataset_class="E",
            classification_reasons=["Dataset is empty or not a valid DataFrame."],
        )

    kinds = profile_columns(df)
    profile = CapabilityProfile(
        row_count=len(df),
        column_count=len(df.columns),
    )

    for col, kind in kinds.items():
        if kind == "date":
            profile.date_columns.append(col)
        elif kind == "numeric":
            profile.numeric_columns.append(col)
        elif kind == "categorical":
            profile.categorical_columns.append(col)
        else:
            profile.text_columns.append(col)

    profile.has_date = len(profile.date_columns) > 0
    profile.has_numeric = len(profile.numeric_columns) > 0
    profile.has_categorical = len(profile.categorical_columns) > 0

    # Determine dataset class and capabilities
    reasons: list[str] = []
    unavailable: list[str] = []

    if profile.has_date and profile.has_numeric:
        # Type A: Full time-series analysis
        profile.dataset_class = "A"
        reasons.append(
            f"Detected date column(s): {', '.join(profile.date_columns)}. "
            f"Detected numeric column(s): {', '.join(profile.numeric_columns)}."
        )
        profile.time_series_analysis = True
        profile.anomaly_detection = True
        profile.trend_analysis = True
        profile.period_comparison = True
        profile.distribution_analysis = True
        profile.segment_comparison = bool(profile.categorical_columns)
        profile.outlier_detection = True
        profile.correlation_analysis = len(profile.numeric_columns) >= 2
        profile.category_frequency = bool(profile.categorical_columns)
        profile.visualization = True
        profile.finding_generation = True
        profile.recommendation_generation = True

    elif profile.has_numeric and profile.has_categorical:
        # Type B: Numeric + categorical, no date
        profile.dataset_class = "B"
        reasons.append(
            "No date/time column detected; time-based analysis is unavailable. "
            f"Detected numeric column(s): {', '.join(profile.numeric_columns)}. "
            f"Detected categorical column(s): {', '.join(profile.categorical_columns)}."
        )
        unavailable.append("time_series_analysis")
        unavailable.append("trend_analysis")
        unavailable.append("period_comparison")
        profile.distribution_analysis = True
        profile.segment_comparison = True
        profile.outlier_detection = True
        profile.correlation_analysis = len(profile.numeric_columns) >= 2
        profile.category_frequency = True
        profile.visualization = True
        profile.finding_generation = True
        profile.recommendation_generation = True

    elif profile.has_numeric:
        # Type C: Numeric only
        profile.dataset_class = "C"
        reasons.append(
            "No date/time or categorical columns detected. "
            f"Detected numeric column(s): {', '.join(profile.numeric_columns)}."
        )
        unavailable.append("time_series_analysis")
        unavailable.append("trend_analysis")
        unavailable.append("period_comparison")
        unavailable.append("segment_comparison")
        unavailable.append("category_frequency")
        profile.distribution_analysis = True
        profile.outlier_detection = True
        profile.correlation_analysis = len(profile.numeric_columns) >= 2
        profile.visualization = True
        profile.finding_generation = True
        profile.recommendation_generation = True

    elif profile.has_date and not profile.has_numeric:
        # Type D: Categorical + date, no numeric
        profile.dataset_class = "D"
        reasons.append(
            "No numeric columns detected; numeric analysis is unavailable. "
            f"Detected date column(s): {', '.join(profile.date_columns)}. "
            f"Detected categorical column(s): {', '.join(profile.categorical_columns)}."
        )
        unavailable.append("anomaly_detection")
        unavailable.append("outlier_detection")
        unavailable.append("correlation_analysis")
        unavailable.append("distribution_analysis")
        unavailable.append("segment_comparison")
        profile.time_series_analysis = True
        profile.trend_analysis = True
        profile.category_frequency = True
        profile.visualization = True
        # Findings possible only if we have categorical data to analyze
        if profile.has_categorical:
            profile.finding_generation = True
            profile.recommendation_generation = True

    else:
        # Type E: Insufficient
        profile.dataset_class = "E"
        if profile.has_categorical:
            reasons.append(
                f"Only categorical columns detected ({', '.join(profile.categorical_columns)}). "
                "No numeric or date columns found for meaningful analysis."
            )
        elif profile.text_columns:
            reasons.append(
                f"Only text columns detected ({', '.join(profile.text_columns)}). "
                "No numeric, date, or categorical columns found for analysis."
            )
        else:
            reasons.append("No analyzable columns found in the dataset.")
        unavailable.extend([
            "time_series_analysis", "anomaly_detection", "trend_analysis",
            "period_comparison", "distribution_analysis", "segment_comparison",
            "outlier_detection", "correlation_analysis", "category_frequency",
            "visualization", "finding_generation", "recommendation_generation",
        ])

    profile.classification_reasons = reasons
    profile.unavailable_capabilities = unavailable
    return profile
