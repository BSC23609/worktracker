"""Multi-assignee tasks + edit/delete by the creator."""
from datetime import timedelta

import pytest

from app.db import today_ist
from app.models import NotificationLog, Task, TaskAttachment, User
from app.services import (
    TaskError,
    add_attachment,
    create_task,
    delete_task,
    edit_task,
)
from tests.conftest import login_as


def _u(db, email):
    return db.query(User).filter_by(email=email).one()


def _future(n):
    return (today_ist() + timedelta(days=n)).isoformat()


# ---- multi-assign ---------------------------------------------------------
def test_superadmin_assigns_to_multiple_people(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    ravi = _u(db, "ravi@bharatsteels.in")
    priya = _u(db, "priya@bharatsteels.in")
    r = client.post("/tasks/create", data={
        "title": "Stock count", "priority": "high", "deadline": _future(3),
        "assigned_to_ids": [str(ravi.id), str(priya.id)]}, follow_redirects=False)
    assert r.status_code == 303
    tasks = db.query(Task).filter_by(title="Stock count").all()
    assert len(tasks) == 2
    assert {t.assigned_to_id for t in tasks} == {ravi.id, priya.id}
    # each is independent — completing one leaves the other open
    assert all(t.status == "pending" for t in tasks)


def test_general_user_multi_ignored_self_only(client, db):
    login_as(client, db, "ravi@bharatsteels.in")
    priya = _u(db, "priya@bharatsteels.in")
    r = client.post("/tasks/create", data={
        "title": "My own", "deadline": _future(2),
        "assigned_to_ids": [str(priya.id)]}, follow_redirects=False)
    assert r.status_code == 303
    t = db.query(Task).filter_by(title="My own").one()
    assert t.assigned_to_id == _u(db, "ravi@bharatsteels.in").id  # self, not priya


def test_recurring_multi_assign_creates_a_schedule_each(client, db):
    from app.models import TaskSchedule
    login_as(client, db, "gourav@bharatsteels.in")
    ravi, priya = _u(db, "ravi@bharatsteels.in"), _u(db, "priya@bharatsteels.in")
    r = client.post("/tasks/create", data={
        "title": "Daily report", "priority": "medium",
        "assigned_to_ids": [str(ravi.id), str(priya.id)],
        "repetitive": "on", "frequency": "daily", "start_date": today_ist().isoformat(),
        "end_date": "", "deadline_offset": "0"}, follow_redirects=False)
    assert r.status_code == 303
    schedules = db.query(TaskSchedule).filter_by(title="Daily report").all()
    assert {s.assigned_to_id for s in schedules} == {ravi.id, priya.id}


# ---- edit -----------------------------------------------------------------
def test_creator_can_edit(db):
    g, r = _u(db, "gourav@bharatsteels.in"), _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=g, assigned_to=r, title="Old", deadline=today_ist() + timedelta(days=5))
    edit_task(db, task=t, actor=g, title="New title", description="ctx", priority="high")
    assert t.title == "New title" and t.priority == "high" and t.description == "ctx"


def test_assignee_cannot_edit(db):
    g, r = _u(db, "gourav@bharatsteels.in"), _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=g, assigned_to=r, title="X", deadline=today_ist() + timedelta(days=5))
    with pytest.raises(TaskError, match="assigned this task"):
        edit_task(db, task=t, actor=r, title="hacked", priority="low")


def test_edit_deadline_is_a_correction_not_a_revision(db):
    g, r = _u(db, "gourav@bharatsteels.in"), _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=g, assigned_to=r, title="X", deadline=today_ist() + timedelta(days=5))
    new = today_ist() + timedelta(days=8)
    edit_task(db, task=t, actor=g, title="X", new_deadline=new)
    assert t.current_deadline == new and t.original_deadline == new  # realigned, still one row
    assert len(t.deadlines) == 1


def test_self_raised_editable_by_that_person(db):
    r = _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=r, assigned_to=r, title="Mine", deadline=today_ist() + timedelta(days=2))
    edit_task(db, task=t, actor=r, title="Mine edited", priority="low")
    assert t.title == "Mine edited"


# ---- delete ---------------------------------------------------------------
def test_creator_can_delete_and_cleans_up(db):
    g, r = _u(db, "gourav@bharatsteels.in"), _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=g, assigned_to=r, title="ToDelete", deadline=today_ist() + timedelta(days=2))
    add_attachment(db, task=t, actor=g, filename="f.txt", content_type="text/plain", data=b"hi")
    db.add(NotificationLog(task_id=t.id, kind="new_task", channel="email", recipient="x", status="sent"))
    db.commit()
    tid = t.id
    delete_task(db, task=t, actor=g)
    assert db.get(Task, tid) is None
    assert db.query(TaskAttachment).filter_by(task_id=tid).count() == 0
    # the notification log survives but is detached from the deleted task
    assert db.query(NotificationLog).filter_by(task_id=tid).count() == 0


def test_assignee_cannot_delete(db):
    g, r = _u(db, "gourav@bharatsteels.in"), _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=g, assigned_to=r, title="X", deadline=today_ist() + timedelta(days=2))
    with pytest.raises(TaskError, match="assigned this task"):
        delete_task(db, task=t, actor=r)


def test_delete_via_http_by_creator(client, db):
    ravi = login_as(client, db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=ravi, assigned_to=ravi, title="Self del", deadline=today_ist() + timedelta(days=2))
    r = client.post(f"/tasks/{t.id}/delete", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/")
    assert db.get(Task, t.id) is None
