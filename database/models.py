"""SQLAlchemy models for the OpsPilot AI audit store (Phase 7).

Three append-only tables mirror the existing Phase 5/6 structures
verbatim — no new business vocabulary is invented here:

* ``recommendation_plans`` — one row per persisted Phase 5 plan, keeping
  its provenance blocks (``parameters``, ``source``, ``summary``) as
  canonical JSON.
* ``recommendations`` — one immutable snapshot row per stored Phase 5
  recommendation record (all 17 contract fields). The same
  ``recommendation_id`` may legitimately appear in several snapshots
  over its lifecycle; identity within one plan is unique.
* ``review_events`` — one row per structured Phase 6 review event,
  stored exactly as produced.

There are intentionally no UPDATE or DELETE paths anywhere in this
package: the audit trail is append-only. List and JSON fields use
canonical JSON text columns so round-trips stay explicit and stable.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for every OpsPilot AI table."""


class PlanRecord(Base):
    """One persisted Phase 5 recommendation plan."""

    __tablename__ = "recommendation_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recorded_at: Mapped[str] = mapped_column(String, nullable=False)
    storage_schema_version: Mapped[str] = mapped_column(String, nullable=False)
    schema_version: Mapped[str] = mapped_column(String, nullable=False)
    plan_type: Mapped[str] = mapped_column(String, nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_json: Mapped[str] = mapped_column(Text, nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)


class RecommendationRecord(Base):
    """One immutable snapshot of a single Phase 5 recommendation."""

    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "recommendation_id",
            name="uq_recommendations_plan_recommendation",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("recommendation_plans.id"), nullable=True
    )
    recommendation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, nullable=False)
    action_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False)
    target_entity: Mapped[str | None] = mapped_column(String, nullable=True)
    target_metric: Mapped[str | None] = mapped_column(String, nullable=True)
    date_window_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_factors_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_anomaly_indices_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_group_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_strength: Mapped[float] = mapped_column(Float, nullable=False)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)


class ReviewEventRecord(Base):
    """One persisted Phase 6 review event, verbatim."""

    __tablename__ = "review_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    recommendation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reviewer_id: Mapped[str] = mapped_column(String, nullable=False)
    previous_status: Mapped[str] = mapped_column(String, nullable=False)
    new_status: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[str] = mapped_column(String, nullable=False)
