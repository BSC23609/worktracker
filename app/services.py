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

from datetime import timezone

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


# Window within which an identical task from the same person counts as an
# accidental double-submit (e.g. clicking "Raise task" two or three times).
DEDUPE_WINDOW_SECONDS = 120


def _recent_duplicate(
    db: Session, *, created_by_id: int, assigned_to_id: int, title: str, deadline: date,
) -> Optional[Task]:
    """Return a just-created, still-open task identical to the one about to be
    raised, if one exists inside DEDUPE_WINDOW_SECONDS. Guards against
    double/triple-clicks creating two or three copies of the same task."""
    row = db.scalar(
        select(Task)
        .where(
            Task.created_by_id == created_by_id,
            Task.assigned_to_id == assigned_to_id,
            func.lower(Task.title) == title.lower(),
            Task.current_deadline == deadline,
            Task.status.in_(OPEN_STATUSES),
            Task.schedule_id.is_(None),
        )
        .order_by(Task.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    created = row.created_at
    if created is None:
        return row  # created in a racing transaction moments ago
    now = now_ist()
    # created_at may be naive (SQLite) or tz-aware (Postgres); normalise both.
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
    if (now - created).total_seconds() <= DEDUPE_WINDOW_SECONDS:
        return row
    return None


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

    # Double-submit guard: if the same person just raised an identical task,
    # return that one instead of making a duplicate. (_deduped lets the caller
    # know not to re-notify / re-upload.)
    existing = _recent_duplicate(
        db, created_by_id=created_by.id, assigned_to_id=assigned_to.id,
        title=title, deadline=deadline,
    )
    if existing is not None:
        existing._deduped = True
        return existing

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
    task._deduped = False
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


def _clone_task_for(db: Session, src: Task, assignee_id: int, actor: User) -> Task:
    """Make a fresh copy of `src` for another person. Used when a task is
    handed to several people at once. The copy starts at the source's current
    deadline (even if that's already past) so an in-flight task can be shared."""
    dl = src.current_deadline
    task = Task(
        title=src.title, description=src.description, priority=src.priority,
        status=STATUS_PENDING, assigned_to_id=assignee_id, created_by_id=actor.id,
        original_deadline=dl, current_deadline=dl,
    )
    db.add(task)
    db.flush()
    db.add(TaskDeadline(task_id=task.id, seq=1, deadline=dl, reason=None, set_by_id=actor.id))
    return task


def reassign_task(
    db: Session, *, task: Task, actor: User, assignee_ids: list[int], commit: bool = True,
) -> list[Task]:
    """Reassign `task` to one or more people.

    The FIRST person ticked becomes this task's assignee; every additional
    person gets their own copy of the task. Returns the list of tasks whose
    assignee is newly set (so the caller can send each a 'new task' notice) --
    an empty list means nothing actually changed.
    """
    if not _can_manage(task, actor):
        raise TaskError("Only the person who assigned this task can reassign it.")
    if task.status == STATUS_COMPLETED:
        raise TaskError("A completed task can't be reassigned. Reopen it first.")

    ids: list[int] = []
    seen: set[int] = set()
    for i in assignee_ids:
        if i and i not in seen:
            seen.add(i)
            ids.append(i)
    if not ids:
        raise TaskError("Select at least one person to assign to.")

    targets = [db.get(User, i) for i in ids]
    targets = [u for u in targets if u is not None]
    if not targets:
        raise TaskError("Select at least one valid person.")
    for u in targets:
        if not u.active:
            raise TaskError(f"{u.name} is inactive and can't be assigned.")
        # A non-superadmin can only ever hold their own tasks.
        if u.id != actor.id and actor.role != ROLE_SUPERADMIN:
            raise TaskError("Only a superadmin can assign tasks to other people.")

    notify: list[Task] = []
    primary = targets[0]
    if task.assigned_to_id != primary.id:
        task.assigned_to_id = primary.id
        notify.append(task)

    for u in targets[1:]:
        if u.id == task.assigned_to_id:
            continue  # already holds this very task
        # Don't create a second identical open copy for someone who has one.
        dup = _recent_duplicate(db, created_by_id=actor.id, assigned_to_id=u.id,
                                title=task.title, deadline=task.current_deadline)
        if dup is not None:
            continue
        notify.append(_clone_task_for(db, task, u.id, actor))

    if commit:
        db.commit()
        for t in notify:
            db.refresh(t)
    return notify


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
        targets = sorted(set(sch.weekday_list)) or [start.weekday()]
        dates = set()
        for t in targets:
            d = start + timedelta(days=(t - start.weekday()) % 7)
            while d <= last:
                dates.add(d)
                d += timedelta(days=7)
        for d in sorted(dates):
            yield d
    elif freq == FREQ_MONTHLY:
        anchors = sorted(set(sch.monthday_list)) or [start.day]
        m = date(start.year, start.month, 1)
        while m <= last and guard < 1200:
            for dd in anchors:
                occ = _clamp(m.year, m.month, dd)
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
    start_date: date, end_date: Optional[date] = None,
    days_of_week: Optional[list[int]] = None, days_of_month: Optional[list[int]] = None,
    deadline_offset_days: int = 0, description: str = "", priority: str = "medium",
    commit: bool = True,
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

    dow = sorted({d for d in (days_of_week or []) if 0 <= d <= 6})
    dom = sorted({d for d in (days_of_month or []) if 1 <= d <= 31})
    if frequency == FREQ_WEEKLY and not dow:
        raise TaskError("Please choose at least one day of the week.")
    if frequency == FREQ_MONTHLY and not dom:
        raise TaskError("Please choose at least one day of the month (1-31).")

    sch = TaskSchedule(
        title=title, description=(description or "").strip() or None,
        priority=priority if priority in ("low", "medium", "high") else "medium",
        assigned_to_id=assigned_to.id, created_by_id=created_by.id,
        frequency=frequency, start_date=start_date, end_date=end_date,
        days_of_week=",".join(str(d) for d in dow) if frequency == FREQ_WEEKLY else None,
        days_of_month=",".join(str(d) for d in dom) if frequency == FREQ_MONTHLY else None,
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


def completed_tasks_for(db: Session, user_id: int, limit: int = 50) -> list[Task]:
    stmt = (
        select(Task)
        .where(Task.assigned_to_id == user_id, Task.status == STATUS_COMPLETED)
        .order_by(Task.completed_at.desc(), Task.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def all_completed_tasks(db: Session, limit: int = 50) -> list[Task]:
    stmt = (
        select(Task)
        .where(Task.status == STATUS_COMPLETED)
        .order_by(Task.completed_at.desc(), Task.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))
