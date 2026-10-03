"""Recurring task schedules: occurrence maths, generation, HTTP flow."""
from datetime import date, timedelta

import pytest

from app.db import today_ist
from app.models import Task, TaskSchedule, User
from app.services import (
    TaskError,
    create_schedule,
    generate_due_recurring_tasks,
    schedule_occurrences,
)
from tests.conftest import login_as


def _u(db, email):
    return db.query(User).filter_by(email=email).one()


def _sched(db, **kw):
    g = _u(db, "gourav@bharatsteels.in")
    r = _u(db, "ravi@bharatsteels.in")
    kw.setdefault("created_by", g)
    kw.setdefault("assigned_to", r)
    kw.setdefault("title", "Recurring")
    return create_schedule(db, **kw)


# ---- occurrence maths -----------------------------------------------------
def test_daily_occurrences(db):
    s = _sched(db, frequency="daily", start_date=date(2026, 1, 1), end_date=date(2026, 1, 5))
    occ = list(schedule_occurrences(s, until=date(2026, 1, 31)))
    assert len(occ) == 5 and occ[0] == date(2026, 1, 1) and occ[-1] == date(2026, 1, 5)


def test_weekly_lands_on_chosen_day(db):
    s = _sched(db, frequency="weekly", start_date=date(2026, 1, 1),
               end_date=date(2026, 1, 31), day_of_week=2)  # Wednesday
    occ = list(schedule_occurrences(s, until=date(2026, 1, 31)))
    assert occ and all(d.weekday() == 2 for d in occ)


def test_monthly_clamps_short_months(db):
    s = _sched(db, frequency="monthly", start_date=date(2026, 1, 15),
               end_date=date(2026, 4, 30), day_of_month=31)
    occ = list(schedule_occurrences(s, until=date(2026, 4, 30)))
    assert occ == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_quarterly_steps_three_months(db):
    s = _sched(db, frequency="quarterly", start_date=date(2026, 1, 10), end_date=date(2026, 12, 31))
    occ = list(schedule_occurrences(s, until=date(2026, 12, 31)))
    assert occ == [date(2026, 1, 10), date(2026, 4, 10), date(2026, 7, 10), date(2026, 10, 10)]


def test_yearly_and_open_ended(db):
    s = _sched(db, frequency="yearly", start_date=date(2026, 3, 1), end_date=None)
    occ = list(schedule_occurrences(s, until=date(2029, 1, 1)))
    assert occ == [date(2026, 3, 1), date(2027, 3, 1), date(2028, 3, 1)]


# ---- validation -----------------------------------------------------------
def test_weekly_requires_day_of_week(db):
    with pytest.raises(TaskError, match="day of the week"):
        _sched(db, frequency="weekly", start_date=date(2026, 1, 1))


def test_monthly_requires_day_of_month(db):
    with pytest.raises(TaskError, match="day of the month"):
        _sched(db, frequency="monthly", start_date=date(2026, 1, 1))


def test_end_before_start_rejected(db):
    with pytest.raises(TaskError, match="End date"):
        _sched(db, frequency="daily", start_date=date(2026, 1, 10), end_date=date(2026, 1, 1))


def test_general_user_cannot_schedule_for_others(db):
    ravi, priya = _u(db, "ravi@bharatsteels.in"), _u(db, "priya@bharatsteels.in")
    with pytest.raises(TaskError, match="only set up recurring tasks for yourself"):
        create_schedule(db, created_by=ravi, assigned_to=priya, title="X",
                        frequency="daily", start_date=date(2026, 1, 1))


# ---- generation -----------------------------------------------------------
def test_generation_is_idempotent_and_sets_deadline(db):
    s = _sched(db, frequency="daily", start_date=date(2026, 1, 1),
               end_date=date(2026, 1, 10), deadline_offset_days=2)
    n1 = generate_due_recurring_tasks(db, on=date(2026, 1, 3))
    n2 = generate_due_recurring_tasks(db, on=date(2026, 1, 3))
    assert n1 == 3 and n2 == 0
    tasks = db.query(Task).filter_by(schedule_id=s.id).order_by(Task.occurrence_date).all()
    assert [t.occurrence_date for t in tasks] == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
    # deadline = occurrence + 2 days
    assert all(t.current_deadline == t.occurrence_date + timedelta(days=2) for t in tasks)
    # each instance has its original deadline frozen + one history row
    assert all(len(t.deadlines) == 1 for t in tasks)


def test_generation_advances_as_time_passes(db):
    s = _sched(db, frequency="daily", start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
    assert generate_due_recurring_tasks(db, on=date(2026, 1, 2)) == 2
    assert generate_due_recurring_tasks(db, on=date(2026, 1, 4)) == 2  # 3rd + 4th
    assert db.query(Task).filter_by(schedule_id=s.id).count() == 4


# ---- HTTP flow ------------------------------------------------------------
def test_create_recurring_via_http(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    ravi = _u(db, "ravi@bharatsteels.in")
    today = today_ist().isoformat()
    r = client.post("/tasks/create", data={
        "title": "Daily production report", "assigned_to_ids": [str(ravi.id)], "priority": "medium",
        "repetitive": "on", "frequency": "daily", "start_date": today, "end_date": "",
        "deadline_offset": "0"}, follow_redirects=False)
    assert r.status_code == 303
    sch = db.query(TaskSchedule).filter_by(title="Daily production report").one()
    assert sch.frequency == "daily" and sch.assigned_to_id == ravi.id
    # one instance (today) was generated immediately
    assert db.query(Task).filter_by(schedule_id=sch.id).count() == 1


def test_stop_schedule(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    s = _sched(db, frequency="daily", start_date=today_ist())
    r = client.post(f"/schedules/{s.id}/stop", follow_redirects=False)
    assert r.status_code == 303
    db.refresh(s)
    assert s.active is False


def test_non_owner_cannot_stop(client, db):
    g = _u(db, "gourav@bharatsteels.in")
    priya = _u(db, "priya@bharatsteels.in")
    ravi = _u(db, "ravi@bharatsteels.in")
    s = create_schedule(db, created_by=g, assigned_to=ravi, title="X",
                        frequency="daily", start_date=today_ist())
    login_as(client, db, "priya@bharatsteels.in")
    assert client.post(f"/schedules/{s.id}/stop").status_code == 403
