"""Schema contracts for the agentic investigation layer.

Central location for every structural constant describing:

* Phase 4A — the evidence pack produced by
  ``agent.evidence.build_investigation_context`` (top-level keys, the
  parameter block, the focus-filter specification, evidence entry kinds
  and their per-kind fields, and the embedded narrative instructions).
* Phase 4B — the result contract returned by
  ``agent.investigator.investigate`` (statuses, exact top-level keys,
  narrative/finding/hypothesis/citation shapes, grounding-report shape,
  and the safe fallback narrative used when a generated narrative is
  rejected).

The module intentionally contains data descriptions only; all assembly
and validation logic lives in ``agent.evidence`` and
``agent.investigator``.
"""

from __future__ import annotations

# --- Pack identity -----------------------------------------------------------

INVESTIGATION_CONTEXT_TYPE: str = "investigation_context"

CONTEXT_SCHEMA_VERSION: str = "1.0"

# --- Top-level pack keys ------------------------------------------------------

EXPECTED_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "type",
        "schema_version",
        "parameters",
        "context",
        "kpis",
        "period_comparison",
        "top_performers",
        "bottom_performers",
        "anomalies",
        "insights",
        "groups",
        "evidence_index",
        "narrative_instructions",
    }
)

EXPECTED_PARAMETERS_KEYS: frozenset[str] = frozenset(
    {"sensitivity", "metrics", "focus"}
)

# --- Focus filter specification ------------------------------------------------

FOCUS_KEYS: frozenset[str] = frozenset(
    {"metrics", "scopes", "entities", "date_start", "date_end"}
)

FOCUS_SCOPES: frozenset[str] = frozenset({"daily", "region", "product"})

# --- Evidence index -------------------------------------------------------------

EVIDENCE_ID_PREFIX: str = "E"

EVIDENCE_KINDS: frozenset[str] = frozenset(
    {"kpi", "period_change", "performer", "correlation", "anomaly", "group"}
)

# Only correlations in these strength bands become citable evidence entries.
CITABLE_CORRELATION_STRENGTHS: frozenset[str] = frozenset({"moderate", "strong"})

# KPI fields promoted into evidence entries, in fixed assignment order.
EVIDENCE_KPI_FIELDS: tuple[str, ...] = (
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
)

# Period-comparison change fields promoted into evidence entries.
EVIDENCE_CHANGE_FIELDS: tuple[str, ...] = (
    "units_change_pct",
    "revenue_change_pct",
    "cost_change_pct",
    "profit_change_pct",
    "margin_change_pct",
    "lead_time_change_pct",
)

# Performer lists promoted into evidence entries, in fixed assignment order.
PERFORMER_LIST_ORDER: tuple[str, ...] = (
    "top_regions",
    "top_products",
    "bottom_regions",
    "bottom_products",
)

# Anomaly record fields copied into anomaly evidence entries.
ANOMALY_ENTRY_FIELDS: tuple[str, ...] = (
    "type",
    "scope",
    "metric",
    "entity",
    "date",
    "value",
    "expected_value",
    "deviation_pct",
    "score",
    "severity",
)

# Group fields copied into group evidence entries.
GROUP_ENTRY_FIELDS: tuple[str, ...] = (
    "group_id",
    "severity",
    "max_score",
    "member_count",
    "start_date",
    "end_date",
)

# --- Narrative instructions -------------------------------------------------------

NARRATIVE_INSTRUCTIONS: dict[str, object] = {
    "citation_format": "[E<id>]",
    "rules": (
        "Cite at least one evidence id for every operational claim.",
        "Only reference numbers that appear verbatim in this context.",
        "Use correlational language; never claim causation.",
        "Never invent dates, entities, metrics, scores, or values.",
    ),
}

# --- Investigation result (Phase 4B) -----------------------------------------------

INVESTIGATION_RESULT_TYPE: str = "investigation_result"

RESULT_SCHEMA_VERSION: str = "1.0"

# The only statuses ``investigate`` may ever return.
INVESTIGATION_STATUSES: frozenset[str] = frozenset(
    {"complete", "narrative_rejected"}
)

# Exact top-level keys of the public investigation result.
EXPECTED_RESULT_KEYS: frozenset[str] = frozenset(
    {
        "status",
        "evidence_pack",
        "narrative",
        "hypotheses",
        "citations",
        "grounding_report",
    }
)

# Exact keys of the narrative block and its finding entries.
EXPECTED_NARRATIVE_KEYS: frozenset[str] = frozenset(
    {"executive_summary", "key_findings", "operational_interpretation"}
)

EXPECTED_FINDING_KEYS: frozenset[str] = frozenset({"claim", "evidence_ids"})

# Exact keys of a hypothesis entry.
EXPECTED_HYPOTHESIS_KEYS: frozenset[str] = frozenset(
    {"hypothesis", "factor", "confidence", "evidence_ids"}
)

# Exact keys of a citation entry.
EXPECTED_CITATION_KEYS: frozenset[str] = frozenset({"evidence_id", "claim"})

# Exact keys of the grounding report.
EXPECTED_GROUNDING_REPORT_KEYS: frozenset[str] = frozenset(
    {
        "valid",
        "citation_errors",
        "numeric_errors",
        "causation_errors",
        "schema_errors",
        "unsupported_claims",
    }
)

# Safe minimal narrative used when every generated attempt fails grounding.
# It contains no operational facts, so it can never be "unsupported".
FALLBACK_NARRATIVE: dict[str, object] = {
    "executive_summary": (
        "The generated narrative failed grounding validation and was "
        "rejected; no narrative findings are reported. Review the "
        "deterministic evidence pack directly."
    ),
    "key_findings": [],
    "operational_interpretation": [],
}
