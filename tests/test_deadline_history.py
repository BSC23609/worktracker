"""The heart of the spec: extending a deadline must KEEP the old one."""
from datetime import timedelta

import pytest

from app.db import today_ist
from app.models import STATUS_COMPLETED, User
from app.services import TaskError, complete_task, create_task, extend_deadline


def _users(db):
    g = db.query(User).filter_by(email="gourav@bharatsteels.in").one()
    r = db.query(User).filter_by(email="ravi@bharatsteels.in").one()
    return g, r


def test_create_sets_original_and_one_history_row(db):
    g, r = _users(db)
    d = today_ist() + timedelta(days=5)
    t = create_task(db, created_by=g, assigned_to=r, title="Audit", deadline=d)
    assert t.original_deadline == d
    assert t.current_deadline == d
    assert len(t.deadlines) == 1
    assert t.deadlines[0].seq == 1
    assert t.deadlines[0].reason is None          # original has no reason
    assert t.extension_count == 0


def test_extend_keeps_old_deadline_and_adds_new(db):
    g, r = _users(db)
    d1 = today_ist() + timedelta(days=3)
    d2 = today_ist() + timedelta(days=10)
    t = create_task(db, created_by=g, assigned_to=r, title="Report", deadline=d1)

    extend_deadline(db, task=t, actor=r, new_deadline=d2, reason="Awaiting vendor data")

    # original is frozen, current moved, BOTH rows exist
    assert t.original_deadline == d1
    assert t.current_deadline == d2
    assert len(t.deadlines) == 2
    assert [dl.deadline for dl in t.deadlines] == [d1, d2]   # old one still there
    assert t.deadlines[0].reason is None
    assert t.deadlines[1].reason == "Awaiting vendor data"
    assert t.deadlines[1].set_by_id == r.id
    assert t.extension_count == 1


def test_multiple_extensions_accumulate_in_order(db):
    g, r = _users(db)
    base = today_ist()
    t = create_task(db, created_by=g, assigned_to=r, title="Multi",
                    deadline=base + timedelta(days=2))
    extend_deadline(db, task=t, actor=r, new_deadline=base + timedelta(days=6), reason="r1")
    extend_deadline(db, task=t, actor=r, new_deadline=base + timedelta(days=9), reason="r2")
    extend_deadline(db, task=t, actor=r, new_deadline=base + timedelta(days=14), reason="r3")

    assert len(t.deadlines) == 4
    assert [dl.seq for dl in t.deadlines] == [1, 2, 3, 4]
    assert [dl.reason for dl in t.deadlines] == [None, "r1", "r2", "r3"]
    assert t.original_deadline == base + timedelta(days=2)   # never changed
    assert t.current_deadline == base + timedelta(days=14)
    assert t.extension_count == 3


def test_extend_requires_reason(db):
    g, r = _users(db)
    t = create_task(db, created_by=g, assigned_to=r, title="X",
                    deadline=today_ist() + timedelta(days=2))
    with pytest.raises(TaskError, match="reason"):
        extend_deadline(db, task=t, actor=r, new_deadline=today_ist() + timedelta(days=5), reason="  ")
    assert len(t.deadlines) == 1  # nothing added


def test_new_deadline_must_be_later(db):
    g, r = _users(db)
    t = create_task(db, created_by=g, assigned_to=r, title="X",
                    deadline=today_ist() + timedelta(days=5))
    with pytest.raises(TaskError, match="later"):
        extend_deadline(db, task=t, actor=r, new_deadline=today_ist() + timedelta(days=5),
                        reason="same date")
    with pytest.raises(TaskError, match="later"):
        extend_deadline(db, task=t, actor=r, new_deadline=today_ist() + timedelta(days=1),
                        reason="earlier")


def test_cannot_extend_completed_task(db):
    g, r = _users(db)
    t = create_task(db, created_by=g, assigned_to=r, title="X",
                    deadline=today_ist() + timedelta(days=5))
    complete_task(db, task=t, actor=r)
    assert t.status == STATUS_COMPLETED
    with pytest.raises(TaskError, match="completed"):
        extend_deadline(db, task=t, actor=r, new_deadline=today_ist() + timedelta(days=9),
                        reason="too late")


def test_only_assignee_or_admin_can_extend(db):
    g, r = _users(db)
    priya = db.query(User).filter_by(email="priya@bharatsteels.in").one()
    t = create_task(db, created_by=g, assigned_to=r, title="X",
                    deadline=today_ist() + timedelta(days=5))
    with pytest.raises(TaskError, match="assignee"):
        extend_deadline(db, task=t, actor=priya, new_deadline=today_ist() + timedelta(days=9),
                        reason="not mine")
    # superadmin may
    extend_deadline(db, task=t, actor=g, new_deadline=today_ist() + timedelta(days=9), reason="ok")
    assert t.extension_count == 1
