"""SQLAlchemy schema.

Phase 1 uses a single generic `records` table keyed by (type, id), rather than
one bespoke table per domain model. Every persisted object is a Pydantic
model with an `id`; job/project scoping columns are extracted for indexed
lookups, and the full object is stored as JSON. This is an intentional
simplification: none of the phase-1 entities need relational joins or
column-level queries yet, and normalizing them now would be schema designed
for hypothetical future queries. When a later phase needs real query
patterns (e.g. "all findings above confidence X across projects"), promote
that type to its own table then.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, JSON, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Record(Base):
    __tablename__ = "records"

    type: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_records_type_job", "type", "job_id"),
        Index("ix_records_type_project", "type", "project_id"),
    )


def create_all(engine) -> None:
    Base.metadata.create_all(engine)
