from datetime import timedelta

from app import notifications
from app.db import today_ist
from app.digests import run_daily_digests
from app.models import NotificationLog, User
from app.notifications import normalise_whatsapp, render_admin_digest, render_new_task
from app.services import create_task, extend_deadline


def _u(db, email):
    return db.query(User).filter_by(email=email).one()


def test_normalise_whatsapp():
    assert normalise_whatsapp("9500680093") == "919500680093"
    assert normalise_whatsapp("91 95006 80093") == "919500680093"
    assert normalise_whatsapp("+91-9500680093") == "919500680093"
    assert normalise_whatsapp("") is None
    assert normalise_whatsapp(None) is None


def test_render_new_task_contains_deadline_and_params(db):
    g, r = _u(db, "gourav@bharatsteels.in"), _u(db, "ravi@bharatsteels.in")
    d = today_ist() + timedelta(days=4)
    t = create_task(db, created_by=g, assigned_to=r, title="GST recon", deadline=d)
    subject, body, params = render_new_task(t)
    assert "GST recon" in subject and d.strftime("%d-%b-%Y") in subject
    assert "Ravi" in body and "Gourav" in body
    assert params == ["Ravi", "GST recon", d.strftime("%d-%b-%Y"), "Gourav"]


def test_admin_digest_groups_and_counts_overdue(db):
    g, r = _u(db, "gourav@bharatsteels.in"), _u(db, "ravi@bharatsteels.in")
    priya = _u(db, "priya@bharatsteels.in")
    create_task(db, created_by=g, assigned_to=r, title="On time",
                deadline=today_ist() + timedelta(days=3))
    overdue = create_task(db, created_by=g, assigned_to=r, title="Late",
                          deadline=today_ist() + timedelta(days=1))
    overdue.current_deadline = today_ist() - timedelta(days=2)
    create_task(db, created_by=g, assigned_to=priya, title="Priya task",
                deadline=today_ist() + timedelta(days=5))
    db.commit()

    from app.services import all_open_tasks
    subject, body, params = render_admin_digest(g, all_open_tasks(db), today_ist())
    assert "Ravi" in body and "Priya" in body
    assert params[1] == "3"   # 3 open
    assert params[2] == "1"   # 1 overdue


def test_daily_digest_is_idempotent_per_day(db, monkeypatch):
    """Running the cron twice in a day must not re-send what already went out."""
    g, r = _u(db, "gourav@bharatsteels.in"), _u(db, "ravi@bharatsteels.in")
    create_task(db, created_by=g, assigned_to=r, title="T",
                deadline=today_ist() + timedelta(days=2))

    # simulate a working email channel so sends are recorded as "sent"
    monkeypatch.setattr(notifications.config, "NOTIFY_EMAIL_ENABLED", True)
    monkeypatch.setattr(notifications, "send_email",
                        _fake_sender(db, channel="email"))

    first = run_daily_digests(db)
    # 4 users each get an employee digest; 2 superadmins also get an admin digest
    assert first["employee_sent"] == 4
    assert first["admin_sent"] == 2

    second = run_daily_digests(db)
    assert second["employee_sent"] == 0 and second["employee_skipped"] == 4
    assert second["admin_sent"] == 0 and second["admin_skipped"] == 2

    # force=True overrides the dedupe
    forced = run_daily_digests(db, force=True)
    assert forced["employee_sent"] == 4 and forced["admin_sent"] == 2


def _fake_sender(db, channel):
    def _send(session, *, to, subject, body, kind, task_id=None, dedupe_key=None):
        session.add(NotificationLog(task_id=task_id, kind=kind, channel=channel,
                                    recipient=to or "-", status="sent" if to else "skipped",
                                    dedupe_key=dedupe_key))
        return bool(to)
    return _send


def test_extension_logs_history_only_no_crash_without_providers(db):
    """With notifications disabled, nothing should raise."""
    g, r = _u(db, "gourav@bharatsteels.in"), _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=g, assigned_to=r, title="T",
                    deadline=today_ist() + timedelta(days=2))
    notifications.notify_new_task(db, t)  # providers off -> logged as skipped, no raise
    logs = db.query(NotificationLog).filter_by(task_id=t.id, kind="new_task").all()
    assert len(logs) == 2  # one email + one whatsapp attempt, both skipped
    assert all(l.status == "skipped" for l in logs)
