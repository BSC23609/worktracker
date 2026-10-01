"""Task lifecycle logic. Kept separate from routes so it is unit-testable.

INVARIANTS enforced here:
  * original_deadline is set once and never mutated.
  * Every deadline (incl. the first) has a row in task_deadlines.
  * Extending adds a NEW row; it never edits or deletes an older one.
  * current_deadline always equals the latest history row's date.
"""
from __future__ import annotations

from datetime import date, datetime
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
