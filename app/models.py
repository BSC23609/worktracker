from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
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

FREQ_DAILY = "daily"
FREQ_WEEKLY = "weekly"
FREQ_MONTHLY = "monthly"
FREQ_QUARTERLY = "quarterly"
FREQ_HALF_YEARLY = "half_yearly"
FREQ_YEARLY = "yearly"
FREQUENCIES = (FREQ_DAILY, FREQ_WEEKLY, FREQ_MONTHLY, FREQ_QUARTERLY, FREQ_HALF_YEARLY, FREQ_YEARLY)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    emp_code: Mapped[Optional[str]] = mapped_column(String(40), unique=True, index=True, default=None)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, default=None)
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

    # Set when this task was generated from a recurring schedule.
    schedule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("task_schedules.id"),
                                                       default=None, index=True)
    occurrence_date: Mapped[Optional[date]] = mapped_column(Date, default=None)

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


class TaskAttachment(Base):
    """A document attached to a task. Stored in the DB (no disk on serverless)."""

    __tablename__ = "task_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped["Task"] = relationship(foreign_keys=[task_id])
    uploaded_by: Mapped[User] = relationship(foreign_keys=[uploaded_by_id])

    @property
    def size_kb(self) -> int:
        return max(1, round(self.size / 1024))


class TaskSchedule(Base):
    """A recurring-task rule. The daily job generates Task instances from it."""

    __tablename__ = "task_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    priority: Mapped[str] = mapped_column(String(16), default="medium")

    assigned_to_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    frequency: Mapped[str] = mapped_column(String(20))         # daily|weekly|monthly|quarterly|half_yearly|yearly
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date, default=None)  # None = until stopped
    day_of_week: Mapped[Optional[int]] = mapped_column(Integer, default=None)   # 0=Mon..6=Sun (weekly)
    day_of_month: Mapped[Optional[int]] = mapped_column(Integer, default=None)  # 1..31 (monthly)
    deadline_offset_days: Mapped[int] = mapped_column(Integer, default=0)

    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_generated_date: Mapped[Optional[date]] = mapped_column(Date, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    assignee: Mapped[User] = relationship(foreign_keys=[assigned_to_id])
    creator: Mapped[User] = relationship(foreign_keys=[created_by_id])

    @property
    def frequency_label(self) -> str:
        if self.frequency == "weekly" and self.day_of_week is not None:
            return f"Weekly ({WEEKDAYS[self.day_of_week]})"
        if self.frequency == "monthly" and self.day_of_month:
            return f"Monthly (day {self.day_of_month})"
        return {
            "daily": "Every day", "quarterly": "Quarterly",
            "half_yearly": "Half-yearly", "yearly": "Yearly",
        }.get(self.frequency, self.frequency.replace("_", " ").title())

    @property
    def summary(self) -> str:
        span = self.start_date.strftime("%d-%b-%Y")
        span += " onward" if not self.end_date else f" to {self.end_date.strftime('%d-%b-%Y')}"
        due = "same day" if self.deadline_offset_days == 0 else f"+{self.deadline_offset_days}d to finish"
        return f"{self.frequency_label} · {span} · {due}"


class Holiday(Base):
    """A non-working date fed in by a superadmin. Daily digests skip these (and Sundays)."""

    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, unique=True, index=True)
    label: Mapped[Optional[str]] = mapped_column(String(200), default=None)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
