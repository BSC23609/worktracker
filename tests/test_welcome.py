"""WhatsApp welcome message from the Master tab."""
from app import config, notifications
from app.models import User
from tests.conftest import login_as


def test_send_welcome_requires_superadmin(client, db):
    login_as(client, db, "ravi@bharatsteels.in")
    assert client.post("/master/send-welcome").status_code == 403


def test_send_welcome_warns_when_wati_off(client, db, monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_WHATSAPP_ENABLED", False)
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post("/master/send-welcome", follow_redirects=False)
    assert r.status_code == 303 and "err=" in r.headers["location"]


def test_send_welcome_all_only_to_whatsapp_users(client, db, monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_WHATSAPP_ENABLED", True)
    sent = []
    monkeypatch.setattr(notifications, "send_welcome",
                        lambda session, user: sent.append(user.name) or True)
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post("/master/send-welcome", follow_redirects=False)
    assert r.status_code == 303
    # conftest: only Gourav and Ravi have whatsapp numbers
    assert sorted(sent) == ["Gourav", "Ravi"]


def test_send_welcome_one(client, db, monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_WHATSAPP_ENABLED", True)
    sent = []
    monkeypatch.setattr(notifications, "send_welcome",
                        lambda session, user: sent.append(user.name) or True)
    ravi = db.query(User).filter_by(email="ravi@bharatsteels.in").one()
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post(f"/master/users/{ravi.id}/send-welcome", follow_redirects=False)
    assert r.status_code == 303 and sent == ["Ravi"]


def test_send_welcome_one_no_whatsapp(client, db, monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_WHATSAPP_ENABLED", True)
    priya = db.query(User).filter_by(email="priya@bharatsteels.in").one()  # no whatsapp in seed
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post(f"/master/users/{priya.id}/send-welcome", follow_redirects=False)
    assert "err=" in r.headers["location"]


def test_send_welcome_uses_configured_template(db, monkeypatch):
    captured = {}
    monkeypatch.setattr(config, "NOTIFY_WHATSAPP_ENABLED", True)
    monkeypatch.setattr(notifications, "send_whatsapp",
                        lambda session, *, to, template, params, kind, **k:
                        captured.update(template=template, params=params, kind=kind) or True)
    u = db.query(User).filter_by(email="gourav@bharatsteels.in").one()
    notifications.send_welcome(db, u)
    assert captured["template"] == config.WATI_TEMPLATE_WELCOME
    assert captured["params"] == [] and captured["kind"] == "welcome"
