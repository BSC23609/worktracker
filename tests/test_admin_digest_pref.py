"""Per-admin opt-out of the consolidated (admin) digest."""
from app import config, notifications
from app.digests import run_daily_digests
from app.models import User
from tests.conftest import login_as


def _sent_recorder(db, monkeypatch):
    rec = {"email": [], "whatsapp": []}
    monkeypatch.setattr(config, "NOTIFY_EMAIL_ENABLED", True)
    monkeypatch.setattr(config, "NOTIFY_WHATSAPP_ENABLED", True)
    monkeypatch.setattr(notifications, "send_email",
                        lambda session, *, to, subject, body, kind, dedupe_key=None, task_id=None:
                        rec["email"].append((kind, to)) or True)
    monkeypatch.setattr(notifications, "send_whatsapp",
                        lambda session, *, to, template, params, kind, dedupe_key=None, task_id=None:
                        rec["whatsapp"].append((kind, to)) or True)
    return rec


def test_admin_digest_skipped_for_opted_out_admin(db, monkeypatch):
    # default: both superadmins get the admin digest
    gourav = db.query(User).filter_by(email="gourav@bharatsteels.in").one()
    gourav.wants_admin_digest = False      # opt Gourav out
    db.commit()
    rec = _sent_recorder(db, monkeypatch)
    r = run_daily_digests(db)
    assert r["admin_sent"] == 1 and r["admin_skipped"] == 1
    admin_recipients = [to for (kind, to) in rec["email"] if kind == "admin_digest"]
    assert "gourav@bharatsteels.in" not in admin_recipients
    assert "jeeva@bharatsteels.in" in admin_recipients
    # Gourav still gets his own employee digest
    emp_recipients = [to for (kind, to) in rec["email"] if kind == "employee_digest"]
    assert "gourav@bharatsteels.in" in emp_recipients


def test_default_is_enabled(db):
    jeeva = db.query(User).filter_by(email="jeeva@bharatsteels.in").one()
    assert jeeva.wants_admin_digest is True


def test_master_toggle_off_admin_digest(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    jeeva = db.query(User).filter_by(email="jeeva@bharatsteels.in").one()
    # submit the edit form WITHOUT wants_admin_digest (unchecked) -> turns it off
    r = client.post(f"/master/users/{jeeva.id}/update", data={
        "name": "Jeeva", "emp_code": "BSC/119", "whatsapp": "",
        "role": "superadmin", "active": "on"}, follow_redirects=False)
    assert r.status_code == 303
    db.refresh(jeeva)
    assert jeeva.wants_admin_digest is False
    # turn it back on (checkbox present -> "on")
    client.post(f"/master/users/{jeeva.id}/update", data={
        "name": "Jeeva", "emp_code": "BSC/119", "whatsapp": "",
        "role": "superadmin", "active": "on", "wants_admin_digest": "on"})
    db.refresh(jeeva)
    assert jeeva.wants_admin_digest is True


def test_toggling_general_user_does_not_change_their_flag(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    ravi = db.query(User).filter_by(email="ravi@bharatsteels.in").one()
    assert ravi.wants_admin_digest is True
    # editing a general user (no admin-digest checkbox rendered) leaves it untouched
    client.post(f"/master/users/{ravi.id}/update", data={
        "name": "Ravi", "emp_code": "", "whatsapp": "9876543210",
        "role": "user", "active": "on"})
    db.refresh(ravi)
    assert ravi.wants_admin_digest is True
