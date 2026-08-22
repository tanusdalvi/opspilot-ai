"""Deterministic playbook registry for the Phase 5 recommendation engine.

Pure data and template helpers only: factor/profile-to-action mappings,
scoring constants, human-readable action phrases, and metric labels. No
I/O, no randomness, no wall-clock time, no LLM. The matching/scoring/
deduplication logic lives in ``agent.recommendation_service``.

Design notes
------------
* Factor labels mirror the Phase 3B insight vocabulary exactly
  (``volume``/``monetary``/``cost``/``supply``/``price_margin`` plus the
  ``unattributed`` fallback). Unknown future labels degrade gracefully
  to ``UNKNOWN_FACTOR_FALLBACK_ACTION``.
* Peer-profile labels mirror the Phase 3B profiles
  (``volume_driven``/``efficiency_driven``/``mixed``).
* The approved design intentionally contains **no trend priority bonus**:
  trend context never affects priority, action selection, or strength.
* Every number used in scoring is an explicit constant below so tests
  can recompute expected values independently.
"""

from __future__ import annotations

from core.constants import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
)

# --- Action mappings -----------------------------------------------------------

# Insight factor label -> playbook action type (exact 3B vocabulary).
FACTOR_ACTION_MAP: dict[str, str] = {
    "volume": "demand_capacity_review",
    "monetary": "revenue_operations_review",
    "cost": "cost_variance_review",
    "supply": "supplier_escalation_review",
    "price_margin": "pricing_margin_review",
    "unattributed": "manual_investigation",
}

# Peer profile -> playbook action type (entity-scope anomalies).
PROFILE_ACTION_MAP: dict[str, str] = {
    "volume_driven": "demand_capacity_review",
    "efficiency_driven": "fulfillment_bottleneck_review",
    "mixed": "entity_performance_review",
}

# Structurally valid but unknown factor labels fall back here instead of
# failing, keeping forward compatibility with future insight rules.
UNKNOWN_FACTOR_FALLBACK_ACTION: str = "manual_investigation"

# --- Scoring constants -----------------------------------------------------------

# Urgency floor contributed by the anomaly/group severity.
PRIORITY_BASE_POINTS: dict[str, float] = {
    SEVERITY_CRITICAL: 40.0,
    SEVERITY_HIGH: 30.0,
    SEVERITY_MEDIUM: 20.0,
    SEVERITY_LOW: 10.0,
}

# Bonus for the primary factor's normalized alignment strength (0..1).
FACTOR_STRENGTH_BONUS_WEIGHT: float = 25.0

# Bonus for corroborating anomaly signals beyond the first one; grows in
# MAX_CORROBORATION_STEPS equal steps up to the full weight.
CORROBORATION_BONUS_WEIGHT: float = 15.0
MAX_CORROBORATION_STEPS: int = 3

# Localization-verdict bonuses (daily-scope insights).
CONCENTRATION_BONUS_POINTS: dict[str, float] = {
    "localized": 10.0,
    "concentrated": 6.0,
}

# Entity outliers substitute a peer-ratio test for localization: at or
# above this ratio against the peer median the signal counts as
# concentrated and earns PEER_CONCENTRATION_BONUS_POINTS.
PEER_RATIO_CONCENTRATION_THRESHOLD: float = 2.0
PEER_CONCENTRATION_BONUS_POINTS: float = 10.0

# evidence_strength blend weights (sum to 1.0): factor support, detector
# score, corroboration fraction, and concentration flag.
EVIDENCE_STRENGTH_FACTOR_WEIGHT: float = 0.50
EVIDENCE_STRENGTH_SCORE_WEIGHT: float = 0.25
EVIDENCE_STRENGTH_CORROBORATION_WEIGHT: float = 0.15
EVIDENCE_STRENGTH_CONCENTRATION_WEIGHT: float = 0.10

# At most one factor candidate plus one profile candidate per insight.
MAX_CANDIDATES_PER_INSIGHT: int = 2

# --- Presentation templates --------------------------------------------------------

# Lowercase action phrase per action type; titles capitalize these.
ACTION_PHRASES: dict[str, str] = {
    "demand_capacity_review": "review demand and capacity planning",
    "revenue_operations_review": "review revenue operations",
    "cost_variance_review": "review cost variance drivers",
    "supplier_escalation_review": "review supplier escalation options",
    "fulfillment_bottleneck_review": "review fulfillment bottlenecks",
    "pricing_margin_review": "review pricing and margin policy",
    "entity_performance_review": "review overall performance profile",
    "manual_investigation": "request targeted operational investigation",
}

# Human-readable metric labels for titles/descriptions.
METRIC_LABELS: dict[str, str] = {
    "units_sold": "unit sales",
    "revenue": "revenue",
    "cost": "cost",
    "lead_time_days": "lead times",
}


def metric_label(metric: object) -> str:
    """Human label for a supported metric; unknown values pass through."""
    key = str(metric)
    return METRIC_LABELS.get(key, key)


def action_phrase(action_type: str) -> str:
    """Lowercase action phrase for a known action type."""
    return ACTION_PHRASES.get(action_type, action_type.replace("_", " "))
