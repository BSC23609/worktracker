"""'Email login details' from the Master tab."""
from app import config, notifications
from app.auth import hash_password
from app.models import User
from tests.conftest import login_as


def test_send_credentials_requires_superadmin(client, db):
    login_as(client, db, "ravi@bharatsteels.in")
    assert client.post("/master/send-credentials").status_code == 403


def test_send_credentials_warns_when_email_off(client, db, monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_EMAIL_ENABLED", False)
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post("/master/send-credentials", follow_redirects=False)
    assert r.status_code == 303 and "err=" in r.headers["location"]


def test_send_credentials_to_all(client, db, monkeypatch):
    sent = []
    monkeypatch.setattr(config, "NOTIFY_EMAIL_ENABLED", True)
    monkeypatch.setattr(notifications, "send_email",
                        lambda session, *, to, subject, body, kind, **k: sent.append(to) or True)
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post("/master/send-credentials", follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    # conftest seeds 4 active users, all with email
    assert len(sent) == 4


def test_send_credentials_skips_no_email_user(client, db, monkeypatch):
    # add a no-email user; it should be reported as skipped, not emailed
    db.add(User(name="No Mail", emp_code="BSC/990", password_hash=hash_password("x"),
                role="user", active=True))
    db.commit()
    sent = []
    monkeypatch.setattr(config, "NOTIFY_EMAIL_ENABLED", True)
    monkeypatch.setattr(notifications, "send_email",
                        lambda session, *, to, subject, body, kind, **k: sent.append(to) or True)
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post("/master/send-credentials", follow_redirects=False)
    assert len(sent) == 4  # the no-email user is not emailed
    assert "no%20email" in r.headers["location"] or "no email" in r.headers["location"]


def test_send_credentials_one_user(client, db, monkeypatch):
    sent = []
    monkeypatch.setattr(config, "NOTIFY_EMAIL_ENABLED", True)
    monkeypatch.setattr(notifications, "send_email",
                        lambda session, *, to, subject, body, kind, **k: sent.append(to) or True)
    ravi = db.query(User).filter_by(email="ravi@bharatsteels.in").one()
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post(f"/master/users/{ravi.id}/send-credentials", follow_redirects=False)
    assert r.status_code == 303 and sent == ["ravi@bharatsteels.in"]


def test_credentials_body_mentions_identifier_and_temp_password(db):
    u = User(name="Temp User", email="t@bharatsteels.in", emp_code="BSC/991",
             password_hash=hash_password("x"), role="user", must_reset=True, active=True)
    subject, body = notifications.render_credentials(u)
    assert "Work Tracker" in subject
    assert "t@bharatsteels.in" in body and "BSC/991" in body
    assert config.DEFAULT_PASSWORD in body  # temp password included for must_reset users
