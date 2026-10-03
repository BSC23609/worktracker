"""On completion, notify the configured recipient (default Gourav) by email + WhatsApp."""
from datetime import timedelta

from app import config, notifications
from app.db import today_ist
from app.models import Task, User
from app.services import create_task


def _u(db, email):
    return db.query(User).filter_by(email=email).one()


def _recorder(monkeypatch):
    rec = {"email": [], "wa": []}
    monkeypatch.setattr(config, "NOTIFY_EMAIL_ENABLED", True)
    monkeypatch.setattr(config, "NOTIFY_WHATSAPP_ENABLED", True)
    monkeypatch.setattr(notifications, "send_email",
                        lambda s, *, to, subject, body, kind, dedupe_key=None, task_id=None:
                        rec["email"].append((kind, to)) or True)
    monkeypatch.setattr(notifications, "send_whatsapp",
                        lambda s, *, to, template, params, kind, dedupe_key=None, task_id=None:
                        rec["wa"].append((kind, template, to, params)) or True)
    return rec


def test_completion_notifies_gourav(client, db, monkeypatch):
    monkeypatch.setattr(config, "COMPLETION_NOTIFY_EMAIL", "gourav@bharatsteels.in")
    rec = _recorder(monkeypatch)
    g = _u(db, "gourav@bharatsteels.in")
    ravi = _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=g, assigned_to=ravi, title="Ship it",
                    deadline=today_ist() + timedelta(days=2))
    # Ravi completes it via HTTP
    from tests.conftest import login_as
    login_as(client, db, "ravi@bharatsteels.in")
    r = client.post(f"/tasks/{t.id}/complete", data={"note": "done"}, follow_redirects=False)
    assert r.status_code == 303
    # Gourav got an email + WhatsApp with the task-done template
    assert ("task_done", "gourav@bharatsteels.in") in rec["email"]
    wa = [x for x in rec["wa"] if x[0] == "task_done"]
    assert wa and wa[0][1] == config.WATI_TEMPLATE_TASK_DONE
    assert wa[0][2] == g.whatsapp
    assert wa[0][3][0] == "Ship it" and wa[0][3][1] == "Ravi"  # title, assignee


def test_no_self_notify_when_recipient_completes_own(client, db, monkeypatch):
    monkeypatch.setattr(config, "COMPLETION_NOTIFY_EMAIL", "gourav@bharatsteels.in")
    rec = _recorder(monkeypatch)
    g = _u(db, "gourav@bharatsteels.in")
    t = create_task(db, created_by=g, assigned_to=g, title="Gourav's own",
                    deadline=today_ist() + timedelta(days=2))
    from tests.conftest import login_as
    login_as(client, db, "gourav@bharatsteels.in")
    client.post(f"/tasks/{t.id}/complete", follow_redirects=False)
    assert rec["email"] == [] and rec["wa"] == []   # no self-notification


def test_render_includes_late_status(db):
    g, ravi = _u(db, "gourav@bharatsteels.in"), _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=g, assigned_to=ravi, title="X",
                    deadline=today_ist() + timedelta(days=1))
    from app.services import complete_task
    # force the deadline into the past so completion is "late"
    t.current_deadline = today_ist() - timedelta(days=3)
    complete_task(db, task=t, actor=ravi)
    subject, body, params = notifications.render_task_completed(t)
    assert "X" in subject and "Ravi" in body
    assert "late" in params[3]
