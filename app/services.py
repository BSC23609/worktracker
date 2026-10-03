"""Task lifecycle logic. Kept separate from routes so it is unit-testable.

INVARIANTS enforced here:
  * original_deadline is set once and never mutated.
  * Every deadline (incl. the first) has a row in task_deadlines.
  * Extending adds a NEW row; it never edits or deletes an older one.
  * current_deadline always equals the latest history row's date.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import now_ist, today_ist
from .models import (
    OPEN_STATUSES,
    ROLE_SUPERADMIN,
    STATUS_COMPLETED,
    STATUS_PENDING,
    Task,
    TaskDeadline,
    User,
)


class TaskError(Exception):
    """Raised on an invalid lifecycle operation (mapped to HTTP 400 by routes)."""


def create_task(
    db: Session,
    *,
    created_by: User,
    assigned_to: User,
    title: str,
    deadline: date,
    description: str = "",
    priority: str = "medium",
    commit: bool = True,
) -> Task:
    title = (title or "").strip()
    if not title:
        raise TaskError("Title is required.")
    if deadline < today_ist():
        raise TaskError("Deadline cannot be in the past.")

    # Authorisation: a general user may only raise tasks for themselves.
    if created_by.role != ROLE_SUPERADMIN and assigned_to.id != created_by.id:
        raise TaskError("You can only raise tasks for yourself.")
    if not assigned_to.active:
        raise TaskError("Cannot assign to an inactive user.")

    task = Task(
        title=title,
        description=(description or "").strip() or None,
        priority=priority if priority in ("low", "medium", "high") else "medium",
        status=STATUS_PENDING,
        assigned_to_id=assigned_to.id,
        created_by_id=created_by.id,
        original_deadline=deadline,
        current_deadline=deadline,
    )
    db.add(task)
    db.flush()  # get task.id

    db.add(
        TaskDeadline(
            task_id=task.id,
            seq=1,
            deadline=deadline,
            reason=None,  # original has no reason
            set_by_id=created_by.id,
        )
    )
    if commit:
        db.commit()
        db.refresh(task)
    return task


def extend_deadline(
    db: Session,
    *,
    task: Task,
    actor: User,
    new_deadline: date,
    reason: str,
    commit: bool = True,
) -> Task:
    """Add a new deadline, keeping every previous one on record."""
    reason = (reason or "").strip()
    if not reason:
        raise TaskError("A reason is required to change the deadline.")
    if task.status == STATUS_COMPLETED:
        raise TaskError("This task is already completed.")
    # Only the assignee (or a superadmin) may move the deadline.
    if actor.id != task.assigned_to_id and actor.role != ROLE_SUPERADMIN:
        raise TaskError("Only the assignee can revise this deadline.")
    if new_deadline <= task.current_deadline:
        raise TaskError("The new deadline must be later than the current one.")

    next_seq = (db.scalar(
        select(func.max(TaskDeadline.seq)).where(TaskDeadline.task_id == task.id)
    ) or 0) + 1

    db.add(
        TaskDeadline(
            task_id=task.id,
            seq=next_seq,
            deadline=new_deadline,
            reason=reason,
            set_by_id=actor.id,
        )
    )
    task.current_deadline = new_deadline  # original_deadline untouched by design
    if task.status not in OPEN_STATUSES:
        task.status = STATUS_PENDING
    if commit:
        db.commit()
        db.refresh(task)
    return task


def _can_manage(task: Task, actor: User) -> bool:
    """Edit/delete is for the person who assigned the task (its creator), or a superadmin."""
    return actor.id == task.created_by_id or actor.role == ROLE_SUPERADMIN


def edit_task(
    db: Session, *, task: Task, actor: User, title: str, description: str = "",
    priority: str = "medium", new_deadline: Optional[date] = None, commit: bool = True,
) -> Task:
    if not _can_manage(task, actor):
        raise TaskError("Only the person who assigned this task can edit it.")
    title = (title or "").strip()
    if not title:
        raise TaskError("Title is required.")
    task.title = title
    task.description = (description or "").strip() or None
    if priority in ("low", "medium", "high"):
        task.priority = priority
    # A deadline edit is a correction, not a logged revision: update the current
    # deadline and the latest history row in place (keep its seq/reason).
    # Self-raised tasks can't have their deadline edited here — that would let
    # people silently move their own deadline; they must use the logged "revise" flow.
    if new_deadline and not task.is_self_raised and new_deadline != task.current_deadline:
        rows = sorted(task.deadlines, key=lambda d: d.seq)
        if rows:
            rows[-1].deadline = new_deadline
        task.current_deadline = new_deadline
        if len(rows) <= 1:
            task.original_deadline = new_deadline  # still the original, keep them aligned
    if commit:
        db.commit()
        db.refresh(task)
    return task


def delete_task(db: Session, *, task: Task, actor: User, commit: bool = True) -> None:
    if not _can_manage(task, actor):
        raise TaskError("Only the person who assigned this task can delete it.")
    from .models import NotificationLog, TaskAttachment
    db.query(TaskAttachment).filter(TaskAttachment.task_id == task.id).delete()
    db.query(NotificationLog).filter(NotificationLog.task_id == task.id)\
        .update({"task_id": None}, synchronize_session=False)
    db.delete(task)  # deadlines cascade via the relationship
    if commit:
        db.commit()


def complete_task(
    db: Session, *, task: Task, actor: User, note: str = "", commit: bool = True
) -> Task:
    if actor.id != task.assigned_to_id and actor.role != ROLE_SUPERADMIN:
        raise TaskError("Only the assignee can mark this done.")
    if task.status == STATUS_COMPLETED:
        return task
    task.status = STATUS_COMPLETED
    task.completed_at = now_ist()
    task.completion_note = (note or "").strip() or None
    if commit:
        db.commit()
        db.refresh(task)
    return task


def reopen_task(db: Session, *, task: Task, actor: User, commit: bool = True) -> Task:
    if actor.role != ROLE_SUPERADMIN:
        raise TaskError("Only a superadmin can reopen a task.")
    task.status = STATUS_PENDING
    task.completed_at = None
    task.completion_note = None
    if commit:
        db.commit()
        db.refresh(task)
    return task


# ---- query helpers used by UI and digests ---------------------------------
def add_attachment(
    db: Session, *, task: Task, actor: User, filename: str, content_type: str,
    data: bytes, commit: bool = True,
) -> "TaskAttachment":
    from . import config
    from .models import TaskAttachment

    if actor.id != task.assigned_to_id and actor.id != task.created_by_id and actor.role != ROLE_SUPERADMIN:
        raise TaskError("You can't attach files to this task.")
    if not data:
        raise TaskError("The file is empty.")
    if len(data) > config.MAX_UPLOAD_BYTES:
        mb = config.MAX_UPLOAD_BYTES / (1024 * 1024)
        raise TaskError(f"File is too large. Maximum size is {mb:.0f} MB.")
    current = db.scalar(select(func.count()).select_from(TaskAttachment)
                        .where(TaskAttachment.task_id == task.id)) or 0
    if current >= config.MAX_ATTACHMENTS_PER_TASK:
        raise TaskError(f"A task can have at most {config.MAX_ATTACHMENTS_PER_TASK} attachments.")

    att = TaskAttachment(
        task_id=task.id,
        filename=(filename or "file")[:255],
        content_type=(content_type or "application/octet-stream")[:120],
        size=len(data),
        data=data,
        uploaded_by_id=actor.id,
    )
    db.add(att)
    if commit:
        db.commit()
        db.refresh(att)
    return att


# ---- recurring schedules --------------------------------------------------
import calendar as _calendar
from dateutil.relativedelta import relativedelta

from .models import (  # noqa: E402
    FREQUENCIES,
    FREQ_DAILY,
    FREQ_MONTHLY,
    FREQ_WEEKLY,
    TaskSchedule,
)

_MONTH_STEP = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}


def _clamp(year: int, month: int, day: int) -> date:
    last = _calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def schedule_occurrences(sch: TaskSchedule, until: date):
    """Yield occurrence dates from start_date through min(until, end_date)."""
    start = sch.start_date
    last = min(until, sch.end_date) if sch.end_date else until
    if last < start:
        return
    freq = sch.frequency
    guard = 0
    if freq == FREQ_DAILY:
        d = start
        while d <= last and guard < 5000:
            yield d
            d += timedelta(days=1)
            guard += 1
    elif freq == FREQ_WEEKLY:
        target = sch.day_of_week if sch.day_of_week is not None else start.weekday()
        d = start + timedelta(days=(target - start.weekday()) % 7)
        while d <= last and guard < 3000:
            yield d
            d += timedelta(days=7)
            guard += 1
    elif freq == FREQ_MONTHLY:
        anchor = sch.day_of_month or start.day
        m = date(start.year, start.month, 1)
        while m <= last and guard < 1200:
            occ = _clamp(m.year, m.month, anchor)
            if start <= occ <= last:
                yield occ
            m += relativedelta(months=1)
            guard += 1
    else:  # quarterly / half_yearly / yearly — anchor on the start date
        step = _MONTH_STEP[freq]
        i = 0
        while guard < 600:
            occ = start + relativedelta(months=step * i)
            if occ > last:
                break
            yield occ
            i += 1
            guard += 1


def create_schedule(
    db: Session, *, created_by: User, assigned_to: User, title: str, frequency: str,
    start_date: date, end_date: Optional[date] = None, day_of_week: Optional[int] = None,
    day_of_month: Optional[int] = None, deadline_offset_days: int = 0,
    description: str = "", priority: str = "medium", commit: bool = True,
) -> TaskSchedule:
    title = (title or "").strip()
    if not title:
        raise TaskError("Title is required.")
    if frequency not in FREQUENCIES:
        raise TaskError("Please choose a valid frequency.")
    if end_date and end_date < start_date:
        raise TaskError("End date cannot be before the start date.")
    if deadline_offset_days < 0:
        raise TaskError("Deadline days cannot be negative.")
    if created_by.role != ROLE_SUPERADMIN and assigned_to.id != created_by.id:
        raise TaskError("You can only set up recurring tasks for yourself.")
    if frequency == FREQ_WEEKLY and day_of_week is None:
        raise TaskError("Please choose which day of the week.")
    if frequency == FREQ_MONTHLY and not day_of_month:
        raise TaskError("Please choose which day of the month.")

    sch = TaskSchedule(
        title=title, description=(description or "").strip() or None,
        priority=priority if priority in ("low", "medium", "high") else "medium",
        assigned_to_id=assigned_to.id, created_by_id=created_by.id,
        frequency=frequency, start_date=start_date, end_date=end_date,
        day_of_week=day_of_week if frequency == FREQ_WEEKLY else None,
        day_of_month=day_of_month if frequency == FREQ_MONTHLY else None,
        deadline_offset_days=deadline_offset_days, active=True,
    )
    db.add(sch)
    if commit:
        db.commit()
        db.refresh(sch)
    return sch


def _instantiate(db: Session, sch: TaskSchedule, occ: date) -> Task:
    deadline = occ + timedelta(days=sch.deadline_offset_days)
    task = Task(
        title=sch.title, description=sch.description, priority=sch.priority,
        status=STATUS_PENDING, assigned_to_id=sch.assigned_to_id,
        created_by_id=sch.created_by_id, original_deadline=deadline,
        current_deadline=deadline, schedule_id=sch.id, occurrence_date=occ,
    )
    db.add(task)
    db.flush()
    db.add(TaskDeadline(task_id=task.id, seq=1, deadline=deadline, reason=None,
                        set_by_id=sch.created_by_id))
    return task


def generate_due_recurring_tasks(db: Session, *, on: date | None = None) -> int:
    """Create task instances for all occurrences due on/before `on` that don't
    exist yet. Idempotent. Returns the number of instances created."""
    today = on or today_ist()
    created = 0
    schedules = list(db.scalars(select(TaskSchedule).where(TaskSchedule.active.is_(True))))
    for sch in schedules:
        for occ in schedule_occurrences(sch, until=today):
            if sch.last_generated_date and occ <= sch.last_generated_date:
                continue
            exists = db.scalar(select(Task.id).where(
                Task.schedule_id == sch.id, Task.occurrence_date == occ))
            if exists:
                continue
            _instantiate(db, sch, occ)
            created += 1
        sch.last_generated_date = today
    db.commit()
    return created


def open_tasks_for(db: Session, user_id: int) -> list[Task]:
    stmt = (
        select(Task)
        .where(Task.assigned_to_id == user_id, Task.status.in_(OPEN_STATUSES))
        .order_by(Task.current_deadline.asc(), Task.id.asc())
    )
    return list(db.scalars(stmt))


def all_open_tasks(db: Session) -> list[Task]:
    stmt = (
        select(Task)
        .where(Task.status.in_(OPEN_STATUSES))
        .order_by(Task.current_deadline.asc(), Task.id.asc())
    )
    return list(db.scalars(stmt))
