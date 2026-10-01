from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, today_ist

# ---- roles & statuses (kept as plain strings for portability) -------------
ROLE_SUPERADMIN = "superadmin"
ROLE_USER = "user"
ROLES = (ROLE_SUPERADMIN, ROLE_USER)

STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
OPEN_STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS)

PRIORITIES = ("low", "medium", "high")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    whatsapp: Mapped[Optional[str]] = mapped_column(String(32), default=None)
    role: Mapped[str] = mapped_column(String(32), default=ROLE_USER)
    password_hash: Mapped[str] = mapped_column(String(255))
    must_reset: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def is_superadmin(self) -> bool:
        return self.role == ROLE_SUPERADMIN


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING, index=True)

    assigned_to_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    # original_deadline is frozen at creation and NEVER changes.
    # current_deadline mirrors the latest row in TaskDeadline for fast queries.
    original_deadline: Mapped[date] = mapped_column(Date)
    current_deadline: Mapped[date] = mapped_column(Date, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    completion_note: Mapped[Optional[str]] = mapped_column(Text, default=None)

    assignee: Mapped[User] = relationship(foreign_keys=[assigned_to_id])
    creator: Mapped[User] = relationship(foreign_keys=[created_by_id])
    deadlines: Mapped[list["TaskDeadline"]] = relationship(
        back_populates="task",
        order_by="TaskDeadline.seq",
        cascade="all, delete-orphan",
    )

    # ---- derived helpers --------------------------------------------------
    @property
    def is_self_raised(self) -> bool:
        return self.assigned_to_id == self.created_by_id

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def is_overdue(self) -> bool:
        return self.is_open and self.current_deadline < today_ist()

    @property
    def days_to_deadline(self) -> int:
        return (self.current_deadline - today_ist()).days

    @property
    def extension_count(self) -> int:
        # number of times the deadline was pushed (history rows beyond the original)
        return max(0, len(self.deadlines) - 1)


class TaskDeadline(Base):
    """Full deadline history. seq=1 is the original (reason is NULL).

    Every time an employee cannot finish in time they add a row here with a
    reason and a new date. The previous rows are kept forever -- this is the
    "old deadline also stays there" requirement.
    """

    __tablename__ = "task_deadlines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # 1,2,3...
    deadline: Mapped[date] = mapped_column(Date)
    reason: Mapped[Optional[str]] = mapped_column(Text, default=None)  # NULL for the original
    set_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped[Task] = relationship(back_populates="deadlines")
    set_by: Mapped[User] = relationship(foreign_keys=[set_by_id])

    @property
    def is_original(self) -> bool:
        return self.seq == 1


class NotificationLog(Base):
    """Audit of every notification, and the de-dupe key for daily digests."""

    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id"), default=None, index=True)
    kind: Mapped[str] = mapped_column(String(32))          # new_task | extension | completed | employee_digest | admin_digest
    channel: Mapped[str] = mapped_column(String(16))        # email | whatsapp
    recipient: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16))         # sent | failed | skipped
    detail: Mapped[Optional[str]] = mapped_column(Text, default=None)
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(120), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
