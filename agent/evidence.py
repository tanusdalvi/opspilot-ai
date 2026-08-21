"""Deterministic evidence-pack builder for the agentic investigation layer.

Phase 4A: assembles the complete, aggregate-only *investigation context*
that the Phase 4B narrator will reason over. The pack bundles analytics,
anomaly detection, insight generation, and grouping outputs behind one
stable contract, and derives a flat ``evidence_index`` of citable
``E<id>`` entries. No LLM, no network, no randomness, no wall-clock time.

Policies
--------
* **Determinism**: identical input always produces identical output.
  Evidence ids are assigned ``E1..En`` in a fixed section order (KPIs,
  period changes, performers, correlations, anomalies, groups); all
  underlying services are deterministic; no wall-clock time is involved
  anywhere in the pack.
* **Immutability**: caller DataFrames and focus dictionaries are never
  modified. Every container in the returned pack is freshly built by
  this module or by the deterministic services it calls.
* **Aggregates only**: raw dataset rows never enter the pack. Only
  service-produced aggregates, anomaly records, insights, groups, and
  derived evidence entries are embedded.
* **Input policy**: the DataFrame follows the analytics/anomaly policy
  (must pass ``validate_dataframe`` with zero errors, at least one row).
  ``sensitivity`` must be one of ``low``/``medium``/``high`` and is
  validated up front. ``focus`` must be ``None``, an empty mapping, or a
  mapping restricted to ``agent.schemas.FOCUS_KEYS``; violations raise
  ``DataValidationError`` from ``core.exceptions``.
* **Focus semantics**: all provided filters are ANDed over detected
  anomaly records. Date bounds apply only to dated records; undated
  entity-scope records pass date filters untouched but are excluded by
  an ``entities`` filter unless their entity is listed. Insights and
  groups are recomputed from the retained records so that
  ``anomaly_index`` values and group member indices stay aligned.
* **Period comparison**: requires at least two distinct dates. Datasets
  with fewer dates yield ``period_comparison: None`` instead of failing;
  every other section remains fully populated.
* **Error behavior**: unusable datasets raise ``DataValidationError``
  via the underlying services; invalid ``sensitivity``/``focus`` fail
  fast before any computation.
"""

from __future__ import annotations

from datetime import date as _date

import pandas as pd

from agent.schemas import (
    ANOMALY_ENTRY_FIELDS,
    CITABLE_CORRELATION_STRENGTHS,
    CONTEXT_SCHEMA_VERSION,
    EVIDENCE_CHANGE_FIELDS,
    EVIDENCE_ID_PREFIX,
    EVIDENCE_KPI_FIELDS,
    FOCUS_KEYS,
    FOCUS_SCOPES,
    GROUP_ENTRY_FIELDS,
    INVESTIGATION_CONTEXT_TYPE,
    NARRATIVE_INSTRUCTIONS,
    PERFORMER_LIST_ORDER,
)
from core.exceptions import DataValidationError
from services.anomaly_service import (
    SENSITIVITY_THRESHOLDS,
    SUPPORTED_METRICS,
    detect_anomalies,
)
from services.analytics_service import (
    calculate_bottom_performers,
    calculate_kpis,
    calculate_period_comparison,
    calculate_top_performers,
)
from services.insight_service import (
    analyze_metric_contexts,
    explain_anomalies,
    group_related_anomalies,
)

# --- Private helpers ---------------------------------------------------------


def _validate_sensitivity(sensitivity: object) -> None:
    """Raise ``DataValidationError`` unless ``sensitivity`` is supported."""
    if not isinstance(sensitivity, str) or sensitivity not in SENSITIVITY_THRESHOLDS:
        choices = ", ".join(sorted(SENSITIVITY_THRESHOLDS))
        raise DataValidationError(
            f"Unsupported sensitivity {sensitivity!r}; expected one of: {choices}"
        )


def _validate_focus(focus: object) -> dict[str, object]:
    """Validate ``focus`` and return its normalized copy.

    ``None`` normalizes to an empty mapping (no restrictions). Unknown
    keys, wrong container types, empty lists, unsupported metric/scope
    values, non-string entities, and unparseable or inverted date bounds
    all raise ``DataValidationError``.
    """
    if focus is None:
        return {}
    if not isinstance(focus, dict):
        raise DataValidationError(
            f"focus must be a dictionary or None; got {type(focus).__name__}"
        )
    unknown = sorted(set(map(str, focus)) - FOCUS_KEYS)
    if unknown:
        raise DataValidationError(
            f"Unknown focus key(s): {', '.join(unknown)}; "
            f"supported keys: {', '.join(sorted(FOCUS_KEYS))}"
        )

    normalized: dict[str, object] = {}

    metrics = focus.get("metrics")
    if metrics is not None:
        if not isinstance(metrics, list) or not metrics:
            raise DataValidationError("focus['metrics'] must be a non-empty list")
        invalid = sorted({str(item) for item in metrics} - SUPPORTED_METRICS)
        if invalid:
            raise DataValidationError(
                f"Unsupported focus metric(s): {', '.join(invalid)}; "
                f"supported metrics: {', '.join(sorted(SUPPORTED_METRICS))}"
            )
        normalized["metrics"] = list(metrics)

    scopes = focus.get("scopes")
    if scopes is not None:
        if not isinstance(scopes, list) or not scopes:
            raise DataValidationError("focus['scopes'] must be a non-empty list")
        invalid = sorted({str(item) for item in scopes} - FOCUS_SCOPES)
        if invalid:
            raise DataValidationError(
                f"Unsupported focus scope(s): {', '.join(invalid)}; "
                f"supported scopes: {', '.join(sorted(FOCUS_SCOPES))}"
            )
        normalized["scopes"] = list(scopes)

    entities = focus.get("entities")
    if entities is not None:
        if not isinstance(entities, list) or not entities:
            raise DataValidationError("focus['entities'] must be a non-empty list")
        if any(not isinstance(item, str) or not item for item in entities):
            raise DataValidationError(
                "focus['entities'] must contain only non-empty strings"
            )
        normalized["entities"] = list(entities)

    start_raw = focus.get("date_start")
    end_raw = focus.get("date_end")
    start = _parse_focus_date(start_raw, "date_start") if start_raw is not None else None
    end = _parse_focus_date(end_raw, "date_end") if end_raw is not None else None
    if start is not None and end is not None and start > end:
        raise DataValidationError(
            f"focus['date_start'] {start_raw!r} must not be after "
            f"focus['date_end'] {end_raw!r}"
        )
    if start_raw is not None:
        normalized["date_start"] = start_raw
    if end_raw is not None:
        normalized["date_end"] = end_raw

    return normalized


def _parse_focus_date(value: object, key: str) -> _date:
    """Parse an ISO ``YYYY-MM-DD`` focus bound or raise ``DataValidationError``."""
    if isinstance(value, str):
        try:
            return _date.fromisoformat(value)
        except ValueError:
            pass
    raise DataValidationError(
        f"focus[{key!r}] must be an ISO YYYY-MM-DD string; got {value!r}"
    )


def _in_focus(record: dict[str, object], focus: dict[str, object]) -> bool:
    """Return ``True`` when one anomaly record satisfies every focus filter."""
    metrics = focus.get("metrics")
    if metrics is not None and record.get("metric") not in metrics:
        return False

    scopes = focus.get("scopes")
    if scopes is not None and record.get("scope") not in scopes:
        return False

    entities = focus.get("entities")
    if entities is not None:
        entity = record.get("entity")
        if entity is None or entity not in entities:
            return False

    start_raw = focus.get("date_start")
    end_raw = focus.get("date_end")
    if start_raw is not None or end_raw is not None:
        iso_date = record.get("date")
        if iso_date is None:
            return True
        parsed = _parse_anomaly_date(iso_date)
        if start_raw is not None and parsed < _date.fromisoformat(str(start_raw)):
            return False
        if end_raw is not None and parsed > _date.fromisoformat(str(end_raw)):
            return False

    return True


def _parse_anomaly_date(iso_date: object) -> _date:
    """Parse a detector-produced ISO date string defensively."""
    try:
        return _date.fromisoformat(str(iso_date))
    except ValueError as exc:
        raise DataValidationError(
            f"Anomaly date {iso_date!r} is not an ISO YYYY-MM-DD string"
        ) from exc


def _period_comparison_or_none(df: pd.DataFrame) -> dict[str, object] | None:
    """Return the period comparison, or ``None`` for single-date datasets.

    Safe because ``calculate_kpis`` has already validated the dataset by
    the time this runs; the only remaining failure mode is the
    fewer-than-two-dates rule.
    """
    try:
        return calculate_period_comparison(df)
    except DataValidationError:
        return None


# --- Evidence entry builders ---------------------------------------------------


def _kpi_entries(kpis: dict[str, object]) -> list[dict[str, object]]:
    """One evidence entry per promoted KPI field, in fixed order."""
    return [
        {"kind": "kpi", "field": field, "value": kpis[field]}
        for field in EVIDENCE_KPI_FIELDS
        if field in kpis
    ]


def _change_entries(period_comparison: dict[str, object] | None) -> list[dict[str, object]]:
    """One evidence entry per promoted period-change field."""
    if period_comparison is None:
        return []
    changes = period_comparison["changes_pct"]
    return [
        {"kind": "period_change", "field": field, "value": changes[field]}
        for field in EVIDENCE_CHANGE_FIELDS
        if field in changes
    ]


def _performer_entries(
    top_performers: dict[str, list[dict[str, object]]],
    bottom_performers: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    """One revenue evidence entry per ranked performer record."""
    sources = {
        "top_regions": top_performers.get("regions", []),
        "top_products": top_performers.get("products", []),
        "bottom_regions": bottom_performers.get("regions", []),
        "bottom_products": bottom_performers.get("products", []),
    }
    entries: list[dict[str, object]] = []
    for list_name in PERFORMER_LIST_ORDER:
        for record in sources[list_name]:
            entity = next(
                (record[key] for key in ("region", "product") if key in record),
                None,
            )
            entries.append(
                {
                    "kind": "performer",
                    "list": list_name,
                    "rank": record.get("rank"),
                    "entity": entity,
                    "value": record.get("revenue"),
                }
            )
    return entries


def _correlation_entries(context: dict[str, object]) -> list[dict[str, object]]:
    """Citable correlation entries restricted to moderate/strong bands."""
    entries: list[dict[str, object]] = []
    for item in context["correlations"]:
        if item["strength"] not in CITABLE_CORRELATION_STRENGTHS:
            continue
        entries.append(
            {
                "kind": "correlation",
                "pair": [item["metric_a"], item["metric_b"]],
                "r": item["r"],
                "strength": item["strength"],
            }
        )
    return entries


def _anomaly_entries(anomalies: list[dict[str, object]]) -> list[dict[str, object]]:
    """One evidence entry per retained anomaly, index-aligned with the pack."""
    entries: list[dict[str, object]] = []
    for position, record in enumerate(anomalies):
        entry: dict[str, object] = {"kind": "anomaly", "anomaly_index": position}
        for field in ANOMALY_ENTRY_FIELDS:
            if field in record:
                entry[field] = record[field]
        entries.append(entry)
    return entries


def _group_entries(groups: list[dict[str, object]]) -> list[dict[str, object]]:
    """One evidence entry per anomaly group, ordered by ``group_id``."""
    entries: list[dict[str, object]] = []
    for group in groups:
        entry: dict[str, object] = {"kind": "group"}
        for field in GROUP_ENTRY_FIELDS:
            if field in group:
                entry[field] = group[field]
        entries.append(entry)
    return entries


def _build_evidence_index(
    kpis: dict[str, object],
    period_comparison: dict[str, object] | None,
    top_performers: dict[str, list[dict[str, object]]],
    bottom_performers: dict[str, list[dict[str, object]]],
    context: dict[str, object],
    anomalies: list[dict[str, object]],
    groups: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Assign sequential ``E<id>`` values across fixed evidence sections."""
    ordered: list[dict[str, object]] = []
    ordered.extend(_kpi_entries(kpis))
    ordered.extend(_change_entries(period_comparison))
    ordered.extend(_performer_entries(top_performers, bottom_performers))
    ordered.extend(_correlation_entries(context))
    ordered.extend(_anomaly_entries(anomalies))
    ordered.extend(_group_entries(groups))

    index: dict[str, dict[str, object]] = {}
    for position, entry in enumerate(ordered, start=1):
        entry["id"] = f"{EVIDENCE_ID_PREFIX}{position}"
        index[entry["id"]] = entry
    return index


# --- Public API -----------------------------------------------------------------


def build_investigation_context(
    df: pd.DataFrame,
    *,
    sensitivity: str = "medium",
    focus: dict[str, object] | None = None,
) -> dict[str, object]:
    """Assemble the complete aggregate-only investigation context.

    Runs KPIs, period comparison, performer rankings, metric contexts,
    anomaly detection, anomaly explanation, and grouping against ``df``,
    then packages every result together with a flat citable
    ``evidence_index`` and static narrative instructions.

    Args:
        df: Operational DataFrame following the canonical schema. It is
            never mutated.
        sensitivity: Passed through to anomaly detection; validated up
            front (``low``/``medium``/``high``).
        focus: Optional restriction over detected anomalies. Supported
            keys are ``metrics``, ``scopes``, ``entities``,
            ``date_start``, and ``date_end``; all provided filters are
            ANDed. ``None`` means no restriction. Never mutated.

    Returns:
        Dictionary with exactly the keys in
        ``agent.schemas.EXPECTED_CONTEXT_KEYS``::

            {
                "type": "investigation_context",
                "schema_version": "1.0",
                "parameters": {"sensitivity", "metrics", "focus"},
                "context": <analyze_metric_contexts output>,
                "kpis": <calculate_kpis output>,
                "period_comparison": <dict> | None,
                "top_performers": <calculate_top_performers output>,
                "bottom_performers": <calculate_bottom_performers output>,
                "anomalies": [...retained anomaly records...],
                "insights": [...one per retained anomaly...],
                "groups": {"groups": [...], "ungrouped_count": int},
                "evidence_index": {"E1": {...}, ...},
                "narrative_instructions": {...},
            }

    Raises:
        DataValidationError: If the dataset is unusable,
            ``sensitivity`` is unsupported, or ``focus`` violates its
            specification.
    """
    _validate_sensitivity(sensitivity)
    normalized_focus = _validate_focus(focus)

    kpis = calculate_kpis(df)
    period_comparison = _period_comparison_or_none(df)
    top_performers = calculate_top_performers(df)
    bottom_performers = calculate_bottom_performers(df)
    context = analyze_metric_contexts(df)

    detection = detect_anomalies(df, sensitivity=sensitivity)
    anomalies = [
        record for record in detection["anomalies"] if _in_focus(record, normalized_focus)
    ]

    insights = explain_anomalies(df, anomalies)["insights"]
    grouping = group_related_anomalies(anomalies)

    evidence_index = _build_evidence_index(
        kpis=kpis,
        period_comparison=period_comparison,
        top_performers=top_performers,
        bottom_performers=bottom_performers,
        context=context,
        anomalies=anomalies,
        groups=grouping["groups"],
    )

    return {
        "type": INVESTIGATION_CONTEXT_TYPE,
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "parameters": {
            "sensitivity": sensitivity,
            "metrics": sorted(SUPPORTED_METRICS),
            "focus": normalized_focus,
        },
        "context": context,
        "kpis": kpis,
        "period_comparison": period_comparison,
        "top_performers": top_performers,
        "bottom_performers": bottom_performers,
        "anomalies": anomalies,
        "insights": insights,
        "groups": grouping,
        "evidence_index": evidence_index,
        "narrative_instructions": dict(NARRATIVE_INSTRUCTIONS),
    }
