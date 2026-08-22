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
* Phase 5 — the plan contract returned by
  ``agent.recommendation_service.generate_recommendations`` (plan/source/
  summary key sets, the exact 17-field recommendation record, the closed
  action-type vocabulary, and priority band edges).
* Phase 6 — the human review workflow contract used by
  ``agent.review_service`` (the extra review status, the closed decision
  vocabulary, the explicit valid-transition table, and the structured
  review-event shape).
* Phase 7 — the persistence & audit contract implemented by the
  ``database`` package (SQLite via SQLAlchemy: connection, models,
  repository) which stores Phase 5 recommendation plans and records and
  Phase 6 review events as an append-only audit trail.

The module intentionally contains data descriptions only; all assembly
and validation logic lives in ``agent.evidence``,
``agent.investigator``, ``agent.recommendation_service``, and
``agent.review_service``.
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

# --- Recommendation plan (Phase 5) ---------------------------------------------------

RECOMMENDATION_PLAN_TYPE: str = "recommendation_plan"

RECOMMENDATION_SCHEMA_VERSION: str = "1.0"

# Exact top-level keys of the public recommendation plan.
EXPECTED_PLAN_KEYS: frozenset[str] = frozenset(
    {
        "type",
        "schema_version",
        "parameters",
        "source",
        "recommendations",
        "summary",
    }
)

# Exact keys of the plan's provenance block.
EXPECTED_SOURCE_KEYS: frozenset[str] = frozenset(
    {
        "anomaly_count",
        "group_count",
        "investigation_status",
        "cited_evidence_ids",
    }
)

# Exact keys of the plan's summary block.
EXPECTED_SUMMARY_KEYS: frozenset[str] = frozenset(
    {"total_count", "by_priority", "by_action_type"}
)

# Exact keys of a single recommendation record.
RECOMMENDATION_KEYS: frozenset[str] = frozenset(
    {
        "recommendation_id",
        "priority",
        "priority_score",
        "action_type",
        "title",
        "description",
        "scope",
        "target_entity",
        "target_metric",
        "date_window",
        "source_factors",
        "source_anomaly_indices",
        "source_group_ids",
        "evidence_ids",
        "evidence_strength",
        "requires_human_review",
        "status",
    }
)

# Closed vocabulary of deterministic playbook action types.
ACTION_TYPES: frozenset[str] = frozenset(
    {
        "demand_capacity_review",
        "revenue_operations_review",
        "cost_variance_review",
        "supplier_escalation_review",
        "fulfillment_bottleneck_review",
        "pricing_margin_review",
        "entity_performance_review",
        "manual_investigation",
    }
)

# Priority labels reuse the shared severity vocabulary for cross-layer
# consistency with anomaly records and groups.
PRIORITY_LABELS: frozenset[str] = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})

# Inclusive minimum priority scores for each label; identical edges to the
# anomaly severity bands so both layers rank on one shared scale.
PRIORITY_CRITICAL_MIN_SCORE: float = 85.0
PRIORITY_HIGH_MIN_SCORE: float = 70.0
PRIORITY_MEDIUM_MIN_SCORE: float = 50.0

DATE_WINDOW_KEYS: frozenset[str] = frozenset({"start", "end"})

# --- Human review workflow (Phase 6) ---------------------------------------------------

# PENDING, APPROVED, and REJECTED live in core.constants (reserved since
# Phase 1); only the revision-loop status is new here.
RECOMMENDATION_CHANGES_REQUESTED: str = "CHANGES_REQUESTED"

# Closed vocabulary of explicit reviewer decisions.
REVIEW_DECISIONS: frozenset[str] = frozenset(
    {"APPROVE", "REJECT", "REQUEST_CHANGES", "RESUBMIT"}
)

# Structured review events record what happened without ever replacing
# the reviewed recommendation.
REVIEW_EVENT_TYPE: str = "recommendation_review"

EXPECTED_REVIEW_EVENT_KEYS: frozenset[str] = frozenset(
    {
        "event_type",
        "recommendation_id",
        "reviewer_id",
        "previous_status",
        "new_status",
        "decision",
        "comment",
        "occurred_at",
    }
)

# Explicit state machine: (current_status, decision) -> new_status.
# Status strings mirror core.constants' reserved recommendation statuses.
# APPROVED and REJECTED are terminal; EXECUTED intentionally does not
# exist in this table because Phase 6 never executes anything. The
# RESUBMIT edge implements the approved CHANGES_REQUESTED -> PENDING
# revision loop (a revised recommendation returns for review).
VALID_REVIEW_TRANSITIONS: dict[tuple[str, str], str] = {
    ("PENDING", "APPROVE"): "APPROVED",
    ("PENDING", "REJECT"): "REJECTED",
    ("PENDING", "REQUEST_CHANGES"): RECOMMENDATION_CHANGES_REQUESTED,
    (RECOMMENDATION_CHANGES_REQUESTED, "RESUBMIT"): "PENDING",
}

# --- Persistence & audit store (Phase 7) ------------------------------------------------

# Version of the persistence contract implemented by the ``database``
# package (SQLite via SQLAlchemy). Stored plans, recommendations, and
# review events are exact snapshots of the Phase 5/6 structures already
# described above; this version covers the storage layout only.
PERSISTENCE_SCHEMA_VERSION: str = "1.0"
