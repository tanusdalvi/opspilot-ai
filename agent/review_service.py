"""Human review & approval workflow for OpsPilot AI (Phase 6).

Implements the controlled human decision layer between Phase 5
recommendation generation and any future execution. Every
recommendation produced by ``agent.recommendation_service`` enters this
workflow as ``status=PENDING`` with ``requires_human_review=True`` and
can only leave PENDING through an explicit reviewer decision recorded
as a structured, auditable review event.

Policies
--------
* **Human-in-the-loop is mandatory**: nothing in this module ever moves
  a recommendation to APPROVED (or any other state) without an explicit
  caller-supplied reviewer identity and decision. There is no
  auto-approval and no auto-execution; EXECUTED is deliberately absent
  from the state machine.
* **Explicit state machine**: the only permitted transitions are those
  in ``agent.schemas.VALID_REVIEW_TRANSITIONS`` —
  ``PENDING -> APPROVED/REJECTED/CHANGES_REQUESTED`` and
  ``CHANGES_REQUESTED -> PENDING`` (the approved revision loop).
  APPROVED and REJECTED are terminal. Invalid transitions fail closed
  with ``DataValidationError``.
* **Workflow change only**: a review decision deep-copies the
  recommendation and changes exactly one field — ``status``. Identity,
  scoring, provenance, evidence references, presentation text, and the
  ``requires_human_review`` gate flag are never altered.
* **Auditable events**: every accepted decision produces an event with
  the exact keys in ``EXPECTED_REVIEW_EVENT_KEYS``: what was reviewed,
  who reviewed it, what was decided, when it happened, the optional
  comment, and the previous/new statuses.
* **Deterministic**: identical inputs (including a pinned
  ``occurred_at`` timestamp) always produce identical outputs. When the
  caller omits ``occurred_at``, the current UTC time is recorded in a
  single normalized ISO-8601 format so audit trails stay consistent.
* **No persistence**: events are plain dictionaries returned to the
  caller. Storage belongs to Phase 7.

The service is pure apart from the documented UTC-now fallback for
omitted timestamps: no global mutable state, no I/O, no LLM.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

from agent.schemas import (
    EXPECTED_REVIEW_EVENT_KEYS,
    RECOMMENDATION_CHANGES_REQUESTED,
    REVIEW_DECISIONS,
    REVIEW_EVENT_TYPE,
    RECOMMENDATION_KEYS,
    VALID_REVIEW_TRANSITIONS,
)
from core.constants import (
    RECOMMENDATION_PENDING,
    RECOMMENDATION_APPROVED,
    RECOMMENDATION_REJECTED,
)
from core.exceptions import DataValidationError

# Statuses a reviewable recommendation may legally carry while inside
# the workflow (APPROVED/REJECTED records may still be validated, e.g.
# to prove they are terminal, but cannot be reviewed further).
KNOWN_REVIEW_STATUSES = frozenset(
    {
        RECOMMENDATION_PENDING,
        RECOMMENDATION_APPROVED,
        RECOMMENDATION_REJECTED,
        RECOMMENDATION_CHANGES_REQUESTED,
    }
)


# --- Recommendation validation ----------------------------------------------------


def validate_reviewable_recommendation(recommendation: object) -> None:
    """Validate that ``recommendation`` can take part in the workflow.

    The record must satisfy the exact Phase 5 public contract (all 17
    keys, no extras), carry a non-empty string ``recommendation_id``,
    hold a known workflow status, and keep the mandatory human-review
    gate raised. Fail closed on every violation.

    Raises:
        DataValidationError: On any structural or semantic violation.
    """
    if not isinstance(recommendation, dict):
        raise DataValidationError(
            "recommendation must be a dictionary; got "
            f"{type(recommendation).__name__}"
        )
    missing = sorted(set(RECOMMENDATION_KEYS) - set(recommendation))
    unexpected = sorted(set(recommendation) - set(RECOMMENDATION_KEYS))
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append(f"missing key(s): {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected key(s): {', '.join(unexpected)}")
        raise DataValidationError(
            "Malformed recommendation record: " + "; ".join(details)
        )
    recommendation_id = recommendation["recommendation_id"]
    if not isinstance(recommendation_id, str) or not recommendation_id.strip():
        raise DataValidationError(
            f"recommendation['recommendation_id'] must be a non-empty "
            f"string; got {recommendation_id!r}"
        )
    status = recommendation["status"]
    if not isinstance(status, str) or status not in KNOWN_REVIEW_STATUSES:
        raise DataValidationError(
            f"recommendation['status'] must be one of "
            f"{sorted(KNOWN_REVIEW_STATUSES)}; got {status!r}"
        )
    if recommendation["requires_human_review"] is not True:
        raise DataValidationError(
            "recommendation is not reviewable: requires_human_review must "
            f"be True; got {recommendation['requires_human_review']!r}"
        )


# --- Transition validation ------------------------------------------------------------


def validate_review_transition(current_status: object, decision: object) -> str:
    """Resolve ``(current_status, decision)`` through the state machine.

    Args:
        current_status: The recommendation's status before the decision.
        decision: One of the closed ``REVIEW_DECISIONS`` vocabulary.

    Returns:
        The resulting status. Pure function; raises instead of guessing.

    Raises:
        DataValidationError: If the decision is malformed or the
            transition is not part of the approved state machine
            (including decisions on terminal states and any attempt to
            move a recommendation to EXECUTED through this service).
    """
    if not isinstance(decision, str) or decision not in REVIEW_DECISIONS:
        raise DataValidationError(
            f"decision must be one of {sorted(REVIEW_DECISIONS)}; got "
            f"{decision!r}"
        )
    if not isinstance(current_status, str):
        raise DataValidationError(
            f"current_status must be a string; got {type(current_status).__name__}"
        )
    new_status = VALID_REVIEW_TRANSITIONS.get((current_status, decision))
    if new_status is None:
        raise DataValidationError(
            f"invalid review transition: {current_status} + {decision} is "
            f"not permitted; valid transitions are "
            f"{sorted(f'{src} + {dec} -> {dst}' for (src, dec), dst in VALID_REVIEW_TRANSITIONS.items())}"
        )
    return new_status


# --- Review event construction -----------------------------------------------------------


def _normalize_comment(comment: object) -> str | None:
    """Type-check the optional reviewer comment without altering content."""
    if comment is None:
        return None
    if isinstance(comment, str):
        return comment
    raise DataValidationError(
        f"comment must be a string or None; got {type(comment).__name__}"
    )


def _normalize_occurred_at(occurred_at: object) -> str:
    """Normalize the event timestamp into one ISO-8601 representation.

    ``None`` falls back to the current UTC time; otherwise the value
    must parse as ISO-8601 and is re-serialized so every event carries
    an identically formatted stamp.
    """
    if occurred_at is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(occurred_at, str):
        try:
            parsed = datetime.fromisoformat(occurred_at)
        except ValueError:
            raise DataValidationError(
                f"occurred_at must be an ISO-8601 timestamp; got {occurred_at!r}"
            ) from None
        return parsed.isoformat()
    raise DataValidationError(
        f"occurred_at must be an ISO-8601 string or None; got "
        f"{type(occurred_at).__name__}"
    )


def create_review_event(
    *,
    recommendation_id: object,
    reviewer_id: object,
    previous_status: object,
    new_status: object,
    decision: object,
    comment: object = None,
    occurred_at: object = None,
) -> dict[str, object]:
    """Build one structured, immutable-by-convention review event.

    Pure constructor with full validation; see
    ``agent.schemas.EXPECTED_REVIEW_EVENT_KEYS`` for the exact shape.

    Raises:
        DataValidationError: On missing/invalid reviewer or
            recommendation identities, malformed decisions/statuses, or
            unparseable timestamps.
    """
    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        raise DataValidationError(
            f"reviewer_id must be a non-empty string; got {reviewer_id!r}"
        )
    if not isinstance(recommendation_id, str) or not recommendation_id.strip():
        raise DataValidationError(
            f"recommendation_id must be a non-empty string; got "
            f"{recommendation_id!r}"
        )
    for name, value in (
        ("previous_status", previous_status),
        ("new_status", new_status),
    ):
        if not isinstance(value, str) or not value:
            raise DataValidationError(
                f"{name} must be a non-empty string; got {value!r}"
            )
    if decision not in REVIEW_DECISIONS:
        raise DataValidationError(
            f"decision must be one of {sorted(REVIEW_DECISIONS)}; got {decision!r}"
        )

    event: dict[str, object] = {
        "event_type": REVIEW_EVENT_TYPE,
        "recommendation_id": recommendation_id.strip(),
        "reviewer_id": reviewer_id.strip(),
        "previous_status": previous_status,
        "new_status": new_status,
        "decision": decision,
        "comment": _normalize_comment(comment),
        "occurred_at": _normalize_occurred_at(occurred_at),
    }
    assert set(event) == set(EXPECTED_REVIEW_EVENT_KEYS)
    return event


# --- Review operations ------------------------------------------------------------------------


def review_recommendation(
    recommendation: dict,
    *,
    decision: str,
    reviewer_id: str,
    comment: str | None = None,
    occurred_at: str | None = None,
) -> tuple[dict, dict]:
    """Apply one explicit human decision to one recommendation.

    The input record is never mutated: a deep copy is returned with
    exactly one field changed — ``status``, resolved strictly through
    the approved state machine — together with the structured review
    event describing the decision.

    Args:
        recommendation: A Phase 5 recommendation record.
        decision: One of ``APPROVE`` / ``REJECT`` / ``REQUEST_CHANGES``
            / ``RESUBMIT``.
        reviewer_id: Non-empty caller-supplied reviewer identity.
        comment: Optional free-text context for the audit trail; never
            influences scores or evidence strength.
        occurred_at: Optional ISO-8601 timestamp; defaults to UTC now.

    Returns:
        ``(updated_recommendation, review_event)``

    Raises:
        DataValidationError: On invalid recommendations, reviewer
            identities, decisions, timestamps, or transitions.
    """
    validate_reviewable_recommendation(recommendation)
    previous_status = recommendation["status"]
    new_status = validate_review_transition(previous_status, decision)
    event = create_review_event(
        recommendation_id=recommendation["recommendation_id"],
        reviewer_id=reviewer_id,
        previous_status=previous_status,
        new_status=new_status,
        decision=decision,
        comment=comment,
        occurred_at=occurred_at,
    )
    updated = copy.deepcopy(recommendation)
    updated["status"] = new_status
    return updated, event


def approve_recommendation(
    recommendation: dict,
    *,
    reviewer_id: str,
    comment: str | None = None,
    occurred_at: str | None = None,
) -> tuple[dict, dict]:
    """Approve a PENDING recommendation (``PENDING -> APPROVED``)."""
    return review_recommendation(
        recommendation,
        decision="APPROVE",
        reviewer_id=reviewer_id,
        comment=comment,
        occurred_at=occurred_at,
    )


def reject_recommendation(
    recommendation: dict,
    *,
    reviewer_id: str,
    comment: str | None = None,
    occurred_at: str | None = None,
) -> tuple[dict, dict]:
    """Reject a PENDING recommendation (``PENDING -> REJECTED``).

    The comment stays optional: the approved design does not mandate a
    rejection reason, so none is invented here.
    """
    return review_recommendation(
        recommendation,
        decision="REJECT",
        reviewer_id=reviewer_id,
        comment=comment,
        occurred_at=occurred_at,
    )


def request_changes(
    recommendation: dict,
    *,
    reviewer_id: str,
    comment: str | None = None,
    occurred_at: str | None = None,
) -> tuple[dict, dict]:
    """Send a PENDING recommendation back for revision
    (``PENDING -> CHANGES_REQUESTED``).

    The revision itself is out of scope: this module never rewrites
    recommendation content. Once a revised version exists, RESUBMIT
    returns it to PENDING for a fresh review.
    """
    return review_recommendation(
        recommendation,
        decision="REQUEST_CHANGES",
        reviewer_id=reviewer_id,
        comment=comment,
        occurred_at=occurred_at,
    )


def resubmit_recommendation(
    recommendation: dict,
    *,
    reviewer_id: str,
    comment: str | None = None,
    occurred_at: str | None = None,
) -> tuple[dict, dict]:
    """Return a revised recommendation to the review queue
    (``CHANGES_REQUESTED -> PENDING``)."""
    return review_recommendation(
        recommendation,
        decision="RESUBMIT",
        reviewer_id=reviewer_id,
        comment=comment,
        occurred_at=occurred_at,
    )
