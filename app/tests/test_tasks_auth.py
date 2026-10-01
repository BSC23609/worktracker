from datetime import timedelta

import pytest

from app.db import today_ist
from app.models import User
from app.services import TaskError, complete_task, create_task


def _u(db, email):
    return db.query(User).filter_by(email=email).one()


def test_general_user_can_self_raise(db):
    ravi = _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=ravi, assigned_to=ravi, title="My own task",
                    deadline=today_ist() + timedelta(days=2))
    assert t.is_self_raised is True
    assert t.assigned_to_id == ravi.id == t.created_by_id


def test_general_user_cannot_assign_to_others(db):
    ravi = _u(db, "ravi@bharatsteels.in")
    priya = _u(db, "priya@bharatsteels.in")
    with pytest.raises(TaskError, match="only raise tasks for yourself"):
        create_task(db, created_by=ravi, assigned_to=priya, title="Not allowed",
                    deadline=today_ist() + timedelta(days=2))


def test_superadmin_can_assign_to_anyone_including_other_admin(db):
    gourav = _u(db, "gourav@bharatsteels.in")
    jeeva = _u(db, "jeeva@bharatsteels.in")
    ravi = _u(db, "ravi@bharatsteels.in")
    t1 = create_task(db, created_by=gourav, assigned_to=ravi, title="A",
                     deadline=today_ist() + timedelta(days=2))
    t2 = create_task(db, created_by=gourav, assigned_to=jeeva, title="B",
                     deadline=today_ist() + timedelta(days=2))
    assert t1.assigned_to_id == ravi.id
    assert t2.assigned_to_id == jeeva.id and t2.is_self_raised is False


def test_cannot_create_with_past_deadline(db):
    gourav = _u(db, "gourav@bharatsteels.in")
    ravi = _u(db, "ravi@bharatsteels.in")
    with pytest.raises(TaskError, match="past"):
        create_task(db, created_by=gourav, assigned_to=ravi, title="late",
                    deadline=today_ist() - timedelta(days=1))


def test_title_required(db):
    gourav = _u(db, "gourav@bharatsteels.in")
    ravi = _u(db, "ravi@bharatsteels.in")
    with pytest.raises(TaskError, match="Title"):
        create_task(db, created_by=gourav, assigned_to=ravi, title="   ",
                    deadline=today_ist() + timedelta(days=2))


def test_only_assignee_or_admin_completes(db):
    gourav = _u(db, "gourav@bharatsteels.in")
    ravi = _u(db, "ravi@bharatsteels.in")
    priya = _u(db, "priya@bharatsteels.in")
    t = create_task(db, created_by=gourav, assigned_to=ravi, title="C",
                    deadline=today_ist() + timedelta(days=2))
    with pytest.raises(TaskError, match="assignee"):
        complete_task(db, task=t, actor=priya)
    complete_task(db, task=t, actor=ravi, note="done")
    assert t.status == "completed" and t.completion_note == "done"


def test_overdue_derivation(db):
    gourav = _u(db, "gourav@bharatsteels.in")
    ravi = _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=gourav, assigned_to=ravi, title="D",
                    deadline=today_ist() + timedelta(days=1))
    assert t.is_overdue is False
    # force past deadline then re-check
    t.current_deadline = today_ist() - timedelta(days=1)
    assert t.is_overdue is True
    complete_task(db, task=t, actor=ravi)
    assert t.is_overdue is False  # completed tasks are never "overdue"
