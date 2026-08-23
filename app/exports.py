"""Deterministic machine-readable exports for OpsPilot AI (Phase 9).

Pure presentation-layer helpers: every function projects data that the
caller already holds (analysis artifacts or repository read results)
into a stable, machine-readable serialization. No business logic, no
session access, and no generated timestamps — identical inputs always
produce byte-identical output.

Exports never include secrets (API keys), raw DataFrames, stack traces,
or driver details.
"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Stable column order for the anomalies export.
ANOMALY_CSV_COLUMNS: tuple[str, ...] = (
    "index",
    "metric",
    "type",
    "rule",
    "severity",
    "score",
    "value",
    "expected_value",
    "deviation_pct",
    "scope",
    "entity",
    "date",
    "z",
)


def _json_safe(value: object) -> object:
    """Recursively coerce values into JSON-safe plain Python types."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, type(None))):
        return value
    if hasattr(value, "item"):  # numpy scalar → plain Python scalar
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError, AttributeError):
            return str(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        number = float(value)
        return number if math.isfinite(number) else None
    return str(value)


def canonical_json(payload: object) -> str:
    """Serialize ``payload`` with stable key ordering and indentation.

    Identical input structures always yield byte-identical text; the
    output ends with a trailing newline for clean file handling.
    """
    return json.dumps(
        _json_safe(payload),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"


def analysis_summary_payload(artifacts) -> dict:
    """Project one completed analysis run into an exportable dictionary.

    Deterministic projection of dataset metadata, the validation summary,
    KPIs, period comparison, trend bounds, anomaly summary, insight
    headlines, and performer rankings. List ordering follows the pipeline's
    own deterministic order; dynamically-keyed mappings are sorted.
    """
    validation = artifacts.validation_report
    kpis = artifacts.kpis or {}
    anomaly_result = artifacts.anomaly_result
    periods = artifacts.period_comparison
    trends = artifacts.daily_trends
    date_col = "date" if "date" in trends.columns else trends.columns[0]

    return {
        "export": {
            "kind": "opspilot-analysis-summary",
            "version": "phase-9",
        },
        "dataset": {
            "name": str(artifacts.dataset_name),
            "row_count": int(validation["row_count"]),
            "column_count": int(validation["column_count"]),
            "validation_valid": bool(validation["valid"]),
        },
        "validation": {
            "error_count": int(validation["error_count"]),
            "warning_count": int(validation["warning_count"]),
            "errors": list(validation.get("errors") or []),
            "warnings": list(validation.get("warnings") or []),
        },
        "kpis": {str(key): _json_safe(kpis[key]) for key in sorted(kpis)},
        "period_comparison": {
            "period_1": _json_safe(dict(periods.get("period_1") or {})),
            "period_2": _json_safe(dict(periods.get("period_2") or {})),
            "changes_pct": {
                str(key): _json_safe(periods["changes_pct"][key])
                for key in sorted(periods.get("changes_pct") or {})
            },
        },
        "trend": {
            "date_min": str(trends[date_col].min()),
            "date_max": str(trends[date_col].max()),
            "days": int(len(trends)),
        },
        "anomalies": {
            "total_count": int(anomaly_result["total_count"]),
            "by_severity": {
                str(severity): int(count)
                for severity, count in sorted(anomaly_result["by_severity"].items())
            },
            "sensitivity": anomaly_result.get("sensitivity"),
            "metrics_analyzed": sorted(
                str(metric) for metric in anomaly_result.get("metrics_analyzed", [])
            ),
        },
        "insights": [
            {
                "headline": str(insight.get("headline", "")),
                "severity": str(insight.get("severity", "")),
                "metric": str(insight.get("metric", "")),
                "entity": (
                    None if insight.get("entity") is None else str(insight["entity"])
                ),
            }
            for insight in artifacts.insights
        ],
        "grouping": {"group_count": len(artifacts.groups)},
        "top_performers": _json_safe(artifacts.top_performers),
        "bottom_performers": _json_safe(artifacts.bottom_performers),
    }


def anomalies_csv_text(artifacts) -> str:
    """Render the current anomalies as deterministic CSV text.

    Columns follow :data:`ANOMALY_CSV_COLUMNS` exactly; rows follow the
    pipeline's anomaly order (already deterministic); missing optional
    fields render as empty cells. Never includes memory addresses or
    timestamps.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(ANOMALY_CSV_COLUMNS)
    for position, record in enumerate(artifacts.anomaly_result["anomalies"]):
        details = record.get("details") or {}

        def cell(name: str) -> str:
            value = record.get(name)
            if value is None:
                return ""
            if isinstance(value, float):
                return "" if not math.isfinite(value) else repr(float(value))
            return str(value)

        z_value = details.get("z")
        writer.writerow(
            [
                position,
                cell("metric"),
                cell("type"),
                cell("rule"),
                cell("severity"),
                cell("score"),
                cell("value"),
                cell("expected_value"),
                cell("deviation_pct"),
                cell("scope"),
                cell("entity") if "entity" in record else "",
                cell("date"),
                "" if z_value is None else repr(float(z_value)),
            ]
        )
    return buffer.getvalue()


def plan_audit_payload(plan_details: list[dict], review_events: list[dict]) -> dict:
    """Assemble the Plans + Audit export from repository read results.

    ``plan_details`` are :func:`database.repository.get_plan` results
    ordered by plan id; ``review_events`` is
    :func:`database.repository.list_review_events` output (ordered by
    insertion). The function adds no timestamps of its own so repeated
    calls against identical store contents produce identical bytes.
    """
    return {
        "export": {
            "kind": "opspilot-plan-audit-export",
            "version": "phase-9",
        },
        "plans": plan_details,
        "review_events": review_events,
    }
