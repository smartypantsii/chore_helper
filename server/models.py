from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from server.db import Base

IN_PROGRESS = "in_progress"
PENDING_APPROVAL = "pending_approval"
APPROVED = "approved"
RETURNED = "returned"
CANCELLED = "cancelled"

DAILY = "daily"
EXTRA = "extra"

OPEN_STATES = (IN_PROGRESS, RETURNED)
COMPLETE_FOR_EXTRAS = (PENDING_APPROVAL, APPROVED)
CLAIMED_STATES = (IN_PROGRESS, PENDING_APPROVAL, APPROVED, RETURNED)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Parent(Base):
    __tablename__ = "parents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))


class Child(Base):
    __tablename__ = "children"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64))
    age: Mapped[int] = mapped_column(Integer)
    pin_hash: Mapped[str] = mapped_column(String(256))


class PoolEntry(Base):
    __tablename__ = "pool_entries"
    __table_args__ = (UniqueConstraint("day", "kind", "chore_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(16))
    chore_id: Mapped[str] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"), index=True)
    chore_id: Mapped[str] = mapped_column(String(64))
    day: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(32), index=True)
    stars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    return_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ManagedChore(Base):
    __tablename__ = "managed_chores"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(32), default="living")
    kind: Mapped[str] = mapped_column(String(16), default="daily")
    min_age: Mapped[int] = mapped_column(Integer, default=4)
    minutes: Mapped[int] = mapped_column(Integer, default=5)
    stars: Mapped[int] = mapped_column(Integer, default=5)
    grown_up_required: Mapped[bool] = mapped_column(Boolean, default=False)
    materials_json: Mapped[str] = mapped_column(Text, default="[]")
    steps_json: Mapped[str] = mapped_column(Text, default="[]")
    done_when_json: Mapped[str] = mapped_column(Text, default="[]")
    cover_image: Mapped[str | None] = mapped_column(String(256), nullable=True)
    demo_video: Mapped[str | None] = mapped_column(String(256), nullable=True)
    parent_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(16), default="custom")


class ChildChore(Base):
    __tablename__ = "child_chores"
    __table_args__ = (UniqueConstraint("child_id", "chore_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"), index=True)
    chore_id: Mapped[str] = mapped_column(ForeignKey("managed_chores.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="daily")
    stars: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


REQUESTED = "requested"
DENIED = "denied"


class ManagedReward(Base):
    __tablename__ = "managed_rewards"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    stars: Mapped[int] = mapped_column(Integer)
    min_age: Mapped[int] = mapped_column(Integer, default=4)
    emoji: Mapped[str] = mapped_column(String(16), default="★")
    season: Mapped[str | None] = mapped_column(String(32), nullable=True)
    grown_up_required: Mapped[bool] = mapped_column(Boolean, default=True)
    parent_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(16), default="custom")


class Redemption(Base):
    __tablename__ = "redemptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"), index=True)
    reward_id: Mapped[str] = mapped_column(String(64))
    stars: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(32), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"), index=True)
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("assignments.id"), unique=True, nullable=True
    )
    redemption_id: Mapped[int | None] = mapped_column(
        ForeignKey("redemptions.id"), unique=True, nullable=True
    )
    stars: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
