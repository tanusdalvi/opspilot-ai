"""Append-only persistence and audit repository for OpsPilot AI (Phase 7).

Stores Phase 5 recommendation plans/records and Phase 6 review events in
SQLite (via SQLAlchemy) as an immutable audit trail.

Contract:

* Inputs are validated against the exact structural constants in
  ``agent.schemas`` before anything is written; unknown keys, wrong
  types, or unknown vocabulary fail closed with ``DataValidationError``.
* Writes are append-only: this module deliberately exposes no update or
  delete functions, so stored audit rows can never be rewritten.
* Persistence-level conflicts (e.g. a missing plan reference) raise
  ``DatabaseError``.
* Timestamps are caller-injected ISO-8601 strings normalized exactly as
  Phase 6 normalizes ``occurred_at``; omitted timestamps default to the
  current UTC time.
* Query results are plain dictionaries with deterministic ordering and
  exactly the same keys as the original structures — round-trips are
  lossless.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent.review_service import (
    KNOWN_REVIEW_STATUSES,
    _normalize_occurred_at,
    validate_reviewable_recommendation,
)
from agent.schemas import (
    EXPECTED_PLAN_KEYS,
    EXPECTED_REVIEW_EVENT_KEYS,
    EXPECTED_SOURCE_KEYS,
    EXPECTED_SUMMARY_KEYS,
    PERSISTENCE_SCHEMA_VERSION,
    RECOMMENDATION_KEYS,
    RECOMMENDATION_PLAN_TYPE,
    RECOMMENDATION_SCHEMA_VERSION,
    REVIEW_DECISIONS,
    REVIEW_EVENT_TYPE,
    VALID_REVIEW_TRANSITIONS,
)
from core.exceptions import DatabaseError, DataValidationError
from database.models import PlanRecord, RecommendationRecord, ReviewEventRecord


# --- validation helpers -----------------------------------------------------------------


def _require_mapping(value: object, label: str) -> dict:
    """Return ``value`` as a dict or raise ``DataValidationError``."""
    if not isinstance(value, dict):
        raise DataValidationError(f"{label} must be a dict; got {type(value).__name__}")
    return value


def _require_exact_keys(mapping: dict, expected: frozenset[str], label: str) -> None:
    """Require that ``mapping`` has exactly ``expected`` keys (strict contract)."""
    actual = set(mapping)
    if actual != set(expected):
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise DataValidationError(
            f"{label} keys mismatch; missing={missing}, unexpected={extra}"
        )


def _require_non_empty_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DataValidationError(f"{label} must be a non-empty string; got {value!r}")
    return value


def _require_int(value: object, label: str, minimum: int = 0) -> int:
    # bool is a subclass of int but is never a valid count here.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DataValidationError(f"{label} must be an int >= {minimum}; got {value!r}")
    return value


def _canonical_json(value: object, label: str) -> str:
    """Serialize ``value`` to canonical JSON text for stable storage."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise DataValidationError(f"{label} is not JSON-serializable: {exc}") from exc


def _validate_source_block(source: object) -> None:
    """Validate the plan's provenance block structure (Phase 5 contract)."""
    block = _require_mapping(source, "plan source")
    _require_exact_keys(block, EXPECTED_SOURCE_KEYS, "plan source")
    _require_int(block["anomaly_count"], "source.anomaly_count")
    _require_int(block["group_count"], "source.group_count")
    status = block["investigation_status"]
    if status is not None and not isinstance(status, str):
        raise DataValidationError(
            f"source.investigation_status must be a string or null; got {status!r}"
        )
    cited = block["cited_evidence_ids"]
    if not isinstance(cited, list) or not all(isinstance(item, str) for item in cited):
        raise DataValidationError(
            "source.cited_evidence_ids must be a list of strings"
        )


def _validate_summary_block(summary: object) -> None:
    """Validate the plan's summary block structure (Phase 5 contract)."""
    block = _require_mapping(summary, "plan summary")
    _require_exact_keys(block, EXPECTED_SUMMARY_KEYS, "plan summary")
    _require_int(block["total_count"], "summary.total_count")
    for key in ("by_priority", "by_action_type"):
        counts = _require_mapping(block[key], f"summary.{key}")
        for name, count in counts.items():
            if not isinstance(name, str):
                raise DataValidationError(f"summary.{key} labels must be strings")
            _require_int(count, f"summary.{key}[{name!r}]")


# --- public validation ------------------------------------------------------------------


def validate_plan(plan: object) -> None:
    """Validate a Phase 5 recommendation plan against the storage contract.

    Checks the exact plan keys, the plan type/schema markers, the source
    and summary blocks, and every contained recommendation record (via
    the shared Phase 6 validator). Duplicate recommendation ids within a
    single plan are rejected because they would violate the audit store's
    per-plan identity constraint.

    Raises:
        DataValidationError: On any structural violation.
    """
    body = _require_mapping(plan, "plan")
    _require_exact_keys(body, EXPECTED_PLAN_KEYS, "plan")
    if body["type"] != RECOMMENDATION_PLAN_TYPE:
        raise DataValidationError(
            f"plan.type must be {RECOMMENDATION_PLAN_TYPE!r}; got {body['type']!r}"
        )
    if body["schema_version"] != RECOMMENDATION_SCHEMA_VERSION:
        raise DataValidationError(
            f"plan.schema_version must be {RECOMMENDATION_SCHEMA_VERSION!r}; "
            f"got {body['schema_version']!r}"
        )
    parameters = body["parameters"]
    if not isinstance(parameters, dict):
        raise DataValidationError(
            f"plan.parameters must be a dict; got {type(parameters).__name__}"
        )
    _canonical_json(parameters, "plan.parameters")
    _validate_source_block(body["source"])
    _validate_summary_block(body["summary"])
    recommendations = body["recommendations"]
    if not isinstance(recommendations, list):
        raise DataValidationError(
            f"plan.recommendations must be a list; got {type(recommendations).__name__}"
        )
    seen_ids: set[str] = set()
    for record in recommendations:
        validate_reviewable_recommendation(record)
        record_id = record["recommendation_id"]  # type: ignore[index]
        if record_id in seen_ids:
            raise DataValidationError(
                f"plan contains duplicate recommendation_id {record_id!r}"
            )
        seen_ids.add(record_id)


def validate_review_event(event: object) -> None:
    """Validate a structured Phase 6 review event against the audit contract.

    Re-validates the event's lifecycle semantics (defense-in-depth):
    ``(previous_status, decision)`` must map through
    ``VALID_REVIEW_TRANSITIONS`` to exactly ``new_status``, which keeps
    terminal states (APPROVED/REJECTED) protected even if a caller hands
    over an event that never passed through ``agent.review_service``.

    Raises:
        DataValidationError: On any structural or semantic violation.
    """
    body = _require_mapping(event, "review event")
    _require_exact_keys(body, EXPECTED_REVIEW_EVENT_KEYS, "review event")
    if body["event_type"] != REVIEW_EVENT_TYPE:
        raise DataValidationError(
            f"event_type must be {REVIEW_EVENT_TYPE!r}; got {body['event_type']!r}"
        )
    _require_non_empty_str(body["recommendation_id"], "recommendation_id")
    _require_non_empty_str(body["reviewer_id"], "reviewer_id")
    previous = body["previous_status"]
    new_status = body["new_status"]
    for label, status in (("previous_status", previous), ("new_status", new_status)):
        if status not in KNOWN_REVIEW_STATUSES:
            raise DataValidationError(
                f"{label} must be one of {sorted(KNOWN_REVIEW_STATUSES)}; got {status!r}"
            )
    decision = body["decision"]
    if decision not in REVIEW_DECISIONS:
        raise DataValidationError(
            f"decision must be one of {sorted(REVIEW_DECISIONS)}; got {decision!r}"
        )
    expected_new = VALID_REVIEW_TRANSITIONS.get((previous, decision))
    if expected_new is None:
        raise DataValidationError(
            f"illegal review transition: {previous!r} + {decision!r} is not a "
            "valid combination"
        )
    if new_status != expected_new:
        raise DataValidationError(
            f"transition {previous!r} + {decision!r} must lead to "
            f"{expected_new!r}; got {new_status!r}"
        )
    comment = body["comment"]
    if comment is not None and not isinstance(comment, str):
        raise DataValidationError(f"comment must be a string or null; got {comment!r}")
    _normalize_occurred_at(body["occurred_at"])


# --- row mapping ------------------------------------------------------------------------


def _recommendation_row_values(record: dict, plan_id: int | None) -> dict[str, Any]:
    """Map a validated recommendation dict onto model column values."""
    window = record["date_window"]
    return {
        "plan_id": plan_id,
        "recommendation_id": record["recommendation_id"],
        "priority": record["priority"],
        "priority_score": float(record["priority_score"]),
        "action_type": record["action_type"],
        "title": record["title"],
        "description": record["description"],
        "scope": record["scope"],
        "target_entity": record["target_entity"],
        "target_metric": record["target_metric"],
        "date_window_json": (
            None if window is None else _canonical_json(window, "date_window")
        ),
        "source_factors_json": _canonical_json(record["source_factors"], "source_factors"),
        "source_anomaly_indices_json": _canonical_json(
            record["source_anomaly_indices"], "source_anomaly_indices"
        ),
        "source_group_ids_json": _canonical_json(
            record["source_group_ids"], "source_group_ids"
        ),
        "evidence_ids_json": _canonical_json(record["evidence_ids"], "evidence_ids"),
        "evidence_strength": float(record["evidence_strength"]),
        "requires_human_review": bool(record["requires_human_review"]),
        "status": record["status"],
    }


def _row_to_recommendation(row: RecommendationRecord) -> dict:
    """Reconstruct the exact 17-key Phase 5 record from a stored row."""
    window_text = row.date_window_json
    return {
        "recommendation_id": row.recommendation_id,
        "priority": row.priority,
        "priority_score": float(row.priority_score),
        "action_type": row.action_type,
        "title": row.title,
        "description": row.description,
        "scope": row.scope,
        "target_entity": row.target_entity,
        "target_metric": row.target_metric,
        "date_window": None if window_text is None else json.loads(window_text),
        "source_factors": json.loads(row.source_factors_json),
        "source_anomaly_indices": json.loads(row.source_anomaly_indices_json),
        "source_group_ids": json.loads(row.source_group_ids_json),
        "evidence_ids": json.loads(row.evidence_ids_json),
        "evidence_strength": float(row.evidence_strength),
        "requires_human_review": bool(row.requires_human_review),
        "status": row.status,
    }


def _row_to_event(row: ReviewEventRecord) -> dict:
    """Reconstruct the exact 8-key Phase 6 event from a stored row."""
    return {
        "event_type": row.event_type,
        "recommendation_id": row.recommendation_id,
        "reviewer_id": row.reviewer_id,
        "previous_status": row.previous_status,
        "new_status": row.new_status,
        "decision": row.decision,
        "comment": row.comment,
        "occurred_at": row.occurred_at,
    }


# --- write path (append-only) -------------------------------------------------------------


def record_plan(engine: Engine, plan: object, *, recorded_at: object = None) -> int:
    """Persist a complete Phase 5 recommendation plan as an audit record.

    Stores the plan's provenance blocks plus one immutable snapshot row
    per contained recommendation in a single transaction.

    Args:
        engine: SQLAlchemy engine created by ``database.connection``.
        plan: The exact plan structure produced by
            ``agent.recommendation_service.generate_recommendations``.
        recorded_at: Optional ISO-8601 timestamp for the audit row;
            defaults to the current UTC time (same normalization rule
            as Phase 6 events).

    Returns:
        The generated plan row id (positive int).

    Raises:
        DataValidationError: If the plan violates the storage contract.
        DatabaseError: On persistence-level failures.
    """
    validate_plan(plan)
    body = _require_mapping(plan, "plan")
    timestamp = _normalize_occurred_at(recorded_at)
    try:
        with Session(engine) as session, session.begin():
            row = PlanRecord(
                recorded_at=timestamp,
                storage_schema_version=PERSISTENCE_SCHEMA_VERSION,
                schema_version=str(body["schema_version"]),
                plan_type=str(body["type"]),
                parameters_json=_canonical_json(body["parameters"], "plan.parameters"),
                source_json=_canonical_json(body["source"], "plan.source"),
                summary_json=_canonical_json(body["summary"], "plan.summary"),
            )
            session.add(row)
            session.flush()
            for record in body["recommendations"]:
                session.add(
                    RecommendationRecord(
                        **_recommendation_row_values(record, row.id)
                    )
                )
            return int(row.id)
    except IntegrityError as exc:
        raise DatabaseError(f"failed to persist recommendation plan: {exc}") from exc


def record_recommendation(
    engine: Engine,
    recommendation: object,
    *,
    plan_id: int | None = None,
    recorded_at: object = None,
) -> int:
    """Append a single recommendation snapshot to the audit store.

    Args:
        engine: SQLAlchemy engine.
        recommendation: An exact 17-key Phase 5 record.
        plan_id: Optional existing plan row id to link the snapshot to.
        recorded_at: Unused placeholder kept for signature symmetry;
            snapshots inherit their timestamp context from plans and
            review events.

    Returns:
        The generated recommendation row id.

    Raises:
        DataValidationError: If the record is malformed or ``plan_id``
            is not a positive integer.
        DatabaseError: If ``plan_id`` does not exist or the insert fails.
    """
    validate_reviewable_recommendation(recommendation)
    if not isinstance(recommendation, dict):  # defensive; validator guarantees
        raise DataValidationError("recommendation must be a dict")
    if plan_id is not None and (
        isinstance(plan_id, bool) or not isinstance(plan_id, int) or plan_id < 1
    ):
        raise DataValidationError(f"plan_id must be a positive int or None; got {plan_id!r}")
    del recorded_at  # intentionally unused; see docstring
    try:
        with Session(engine) as session, session.begin():
            if plan_id is not None:
                exists = session.get(PlanRecord, plan_id)
                if exists is None:
                    raise DatabaseError(f"plan_id {plan_id} does not exist")
            row = RecommendationRecord(**_recommendation_row_values(recommendation, plan_id))
            session.add(row)
            session.flush()
            return int(row.id)
    except IntegrityError as exc:
        raise DatabaseError(f"failed to persist recommendation snapshot: {exc}") from exc


def record_review_event(engine: Engine, event: object) -> int:
    """Persist one structured review event verbatim.

    Args:
        engine: SQLAlchemy engine.
        event: The exact 8-key event produced by Phase 6's
            ``create_review_event``.

    Returns:
        The generated event row id.

    Raises:
        DataValidationError: If the event violates the audit contract.
        DatabaseError: On persistence-level failures.
    """
    validate_review_event(event)
    body = _require_mapping(event, "review event")
    try:
        with Session(engine) as session, session.begin():
            row = ReviewEventRecord(
                event_type=str(body["event_type"]),
                recommendation_id=str(body["recommendation_id"]),
                reviewer_id=str(body["reviewer_id"]),
                previous_status=str(body["previous_status"]),
                new_status=str(body["new_status"]),
                decision=str(body["decision"]),
                comment=body["comment"],
                occurred_at=_normalize_occurred_at(body["occurred_at"]),
            )
            session.add(row)
            session.flush()
            return int(row.id)
    except IntegrityError as exc:
        raise DatabaseError(f"failed to persist review event: {exc}") from exc


def record_review(
    engine: Engine,
    updated_recommendation: object,
    event: object,
) -> tuple[int, int]:
    """Record one completed Phase 6 review atomically.

    Persists both outputs of ``review_recommendation`` — the updated
    recommendation snapshot (append-only; earlier snapshots are kept)
    and its structured review event — in a single transaction after
    verifying they describe the same lifecycle step.

    Args:
        engine: SQLAlchemy engine.
        updated_recommendation: The reviewed copy returned by Phase 6.
        event: Its matching structured review event.

    Returns:
        Tuple ``(recommendation_row_id, event_row_id)``.

    Raises:
        DataValidationError: If either object is malformed or they are
            inconsistent with each other.
        DatabaseError: On persistence-level failures.
    """
    validate_reviewable_recommendation(updated_recommendation)
    validate_review_event(event)
    record = _require_mapping(updated_recommendation, "updated recommendation")
    body = _require_mapping(event, "review event")
    if record["recommendation_id"] != body["recommendation_id"]:
        raise DataValidationError(
            f"review event targets {body['recommendation_id']!r} but the "
            f"snapshot is {record['recommendation_id']!r}"
        )
    if record["status"] != body["new_status"]:
        raise DataValidationError(
            f"snapshot status {record['status']!r} does not match event "
            f"new_status {body['new_status']!r}"
        )
    try:
        with Session(engine) as session, session.begin():
            rec_row = RecommendationRecord(**_recommendation_row_values(record, None))
            session.add(rec_row)
            session.flush()
            evt_row = ReviewEventRecord(
                event_type=str(body["event_type"]),
                recommendation_id=str(body["recommendation_id"]),
                reviewer_id=str(body["reviewer_id"]),
                previous_status=str(body["previous_status"]),
                new_status=str(body["new_status"]),
                decision=str(body["decision"]),
                comment=body["comment"],
                occurred_at=_normalize_occurred_at(body["occurred_at"]),
            )
            session.add(evt_row)
            session.flush()
            return int(rec_row.id), int(evt_row.id)
    except IntegrityError as exc:
        raise DatabaseError(f"failed to persist review outcome: {exc}") from exc


# --- read path (deterministic queries) ----------------------------------------------------


def _parse_json_column(raw: object, label: str) -> dict:
    """Parse one stored canonical JSON column into a plain dict.

    Persisted plan provenance was written through :func:`_canonical_json`,
    so any deviation here means the stored row is corrupted; reads fail
    closed with ``DataValidationError`` instead of fabricating content.
    """
    if not isinstance(raw, str) or not raw:
        raise DataValidationError(f"stored {label} is missing or empty")
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DataValidationError(f"stored {label} is corrupted") from exc
    if not isinstance(parsed, dict):
        raise DataValidationError(f"stored {label} is corrupted")
    return parsed


def _plan_row_to_dict(row: PlanRecord) -> dict[str, Any]:
    """Project one ``PlanRecord`` onto its public provenance dictionary."""
    return {
        "plan_id": int(row.id),
        "recorded_at": str(row.recorded_at),
        "storage_schema_version": str(row.storage_schema_version),
        "schema_version": str(row.schema_version),
        "plan_type": str(row.plan_type),
        "parameters": _parse_json_column(row.parameters_json, "plan parameters"),
        "source": _parse_json_column(row.source_json, "plan source"),
        "summary": _parse_json_column(row.summary_json, "plan summary"),
    }


def list_plans(engine: Engine) -> list[dict]:
    """Return every stored plan's provenance ordered by insertion.

    Each entry carries the plan identity/timestamps, its stored
    ``parameters``, ``source``, and ``summary`` blocks, and the number of
    recommendation snapshots recorded under it (``recommendation_count``).
    Results are deterministic: plans ascending by id.

    Raises:
        DataValidationError: If any stored plan block is corrupted.
    """
    with Session(engine) as session:
        rows = session.scalars(select(PlanRecord).order_by(PlanRecord.id.asc())).all()
        count_rows = session.execute(
            select(RecommendationRecord.plan_id, func.count())
            .where(RecommendationRecord.plan_id.isnot(None))
            .group_by(RecommendationRecord.plan_id)
        ).all()
    counts = {int(plan_id): int(total) for plan_id, total in count_rows}
    plans = [_plan_row_to_dict(row) for row in rows]
    for plan in plans:
        plan["recommendation_count"] = counts.get(int(plan["plan_id"]), 0)
    return plans


def get_plan(engine: Engine, plan_id: object) -> dict | None:
    """Return the complete stored provenance for one plan, or ``None``.

    The result includes the full provenance blocks plus every immutable
    recommendation snapshot recorded under the plan (exact 17-key Phase 5
    records), ordered by insertion. Review events are keyed by
    recommendation id rather than plan id and are therefore retrieved
    separately via :func:`list_review_events`.

    Args:
        engine: SQLAlchemy engine created by ``database.connection``.
        plan_id: Positive integer plan row id.

    Raises:
        DataValidationError: If ``plan_id`` is malformed or any stored
            block belonging to the plan is corrupted.
    """
    if isinstance(plan_id, bool) or not isinstance(plan_id, int) or plan_id < 1:
        raise DataValidationError(f"plan_id must be a positive int; got {plan_id!r}")
    with Session(engine) as session:
        row = session.get(PlanRecord, plan_id)
        if row is None:
            return None
        plan = _plan_row_to_dict(row)
        stmt = (
            select(RecommendationRecord)
            .where(RecommendationRecord.plan_id == plan_id)
            .order_by(RecommendationRecord.id.asc())
        )
        plan["recommendations"] = [
            _row_to_recommendation(snapshot)
            for snapshot in session.scalars(stmt).all()
        ]
    return plan


def get_latest_recommendation(engine: Engine, recommendation_id: object) -> dict | None:
    """Return the newest stored snapshot for ``recommendation_id``, or None.

    Args:
        engine: SQLAlchemy engine.
        recommendation_id: Non-empty string identifier.

    Returns:
        A plain dict with exactly the 17 Phase 5 keys, or ``None`` when
        no snapshot exists.
    """
    rid = _require_non_empty_str(recommendation_id, "recommendation_id")
    stmt = (
        select(RecommendationRecord)
        .where(RecommendationRecord.recommendation_id == rid)
        .order_by(RecommendationRecord.id.desc())
        .limit(1)
    )
    with Session(engine) as session:
        row = session.scalars(stmt).first()
        return None if row is None else _row_to_recommendation(row)


def list_recommendations(engine: Engine) -> list[dict]:
    """Return every stored recommendation snapshot ordered by insertion."""
    stmt = select(RecommendationRecord).order_by(RecommendationRecord.id.asc())
    with Session(engine) as session:
        rows = session.scalars(stmt).all()
        return [_row_to_recommendation(row) for row in rows]


def list_review_events(engine: Engine, *, recommendation_id: object = None) -> list[dict]:
    """Return stored review events ordered by insertion.

    Args:
        engine: SQLAlchemy engine.
        recommendation_id: Optional non-empty string filter.

    Returns:
        Plain dicts with exactly the 8 Phase 6 event keys.
    """
    stmt = select(ReviewEventRecord).order_by(ReviewEventRecord.id.asc())
    if recommendation_id is not None:
        rid = _require_non_empty_str(recommendation_id, "recommendation_id")
        stmt = stmt.where(ReviewEventRecord.recommendation_id == rid)
    with Session(engine) as session:
        rows = session.scalars(stmt).all()
        return [_row_to_event(row) for row in rows]


def count_plans(engine: Engine) -> int:
    """Return the number of persisted plans."""
    with Session(engine) as session:
        return int(session.scalar(select(func.count()).select_from(PlanRecord)) or 0)


def count_recommendations(engine: Engine) -> int:
    """Return the number of persisted recommendation snapshots."""
    with Session(engine) as session:
        return int(
            session.scalar(select(func.count()).select_from(RecommendationRecord)) or 0
        )


def count_review_events(engine: Engine) -> int:
    """Return the number of persisted review events."""
    with Session(engine) as session:
        return int(
            session.scalar(select(func.count()).select_from(ReviewEventRecord)) or 0
        )


__all__ = [
    "count_plans",
    "count_recommendations",
    "count_review_events",
    "get_latest_recommendation",
    "get_plan",
    "list_plans",
    "list_recommendations",
    "list_review_events",
    "record_plan",
    "record_recommendation",
    "record_review",
    "record_review_event",
    "validate_plan",
    "validate_review_event",
]
