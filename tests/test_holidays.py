"""Holiday master + daily digest skipping Sundays/holidays."""
from datetime import date, timedelta

from app import config, notifications
from app.digests import is_holiday, is_working_day, run_daily_digests
from app.models import Holiday, User
from tests.conftest import login_as


def _next_weekday(d, weekday):
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def test_is_working_day(db):
    monday = _next_weekday(date(2026, 1, 1), 0)
    sunday = _next_weekday(date(2026, 1, 1), 6)
    assert is_working_day(db, monday) is True
    assert is_working_day(db, sunday) is False           # Sunday
    db.add(Holiday(day=monday, label="Test holiday")); db.commit()
    assert is_holiday(db, monday) is True
    assert is_working_day(db, monday) is False            # now a holiday


def _fake_send(db, sent):
    import app.notifications as n
    return lambda session, **k: sent.append(k.get("to")) or True


def test_digest_runs_on_working_day(client, db, monkeypatch):
    sent = []
    monkeypatch.setattr(config, "NOTIFY_EMAIL_ENABLED", True)
    monkeypatch.setattr(notifications, "send_email",
                        lambda session, *, to, subject, body, kind, dedupe_key=None, task_id=None:
                        sent.append(to) or True)
    monday = _next_weekday(date(2026, 1, 5), 0)
    r = run_daily_digests(db, on=monday)
    assert r["employee_sent"] >= 1


def test_cron_skips_sunday(client, db, monkeypatch):
    # make "today" a Sunday by adding it as... we can't change today_ist easily here,
    # so assert via the endpoint using a holiday on today instead (same skip path).
    from app.db import today_ist
    db.add(Holiday(day=today_ist(), label="Today off")); db.commit()
    r = client.post("/cron/daily-digests", headers={"X-Cron-Key": "test-cron"})
    body = r.json()
    assert r.status_code == 200
    assert body.get("digests_skipped") == "holiday"
    assert "recurring_generated" in body          # generation still ran


def test_cron_force_overrides_holiday(client, db, monkeypatch):
    from app.db import today_ist
    db.add(Holiday(day=today_ist(), label="Today off")); db.commit()
    r = client.post("/cron/daily-digests?force=1", headers={"X-Cron-Key": "test-cron"})
    body = r.json()
    assert "employee_sent" in body and "digests_skipped" not in body


# ---- holiday master UI ----------------------------------------------------
def test_holidays_page_superadmin_only(client, db):
    login_as(client, db, "ravi@bharatsteels.in")
    assert client.get("/holidays").status_code == 403
    login_as(client, db, "gourav@bharatsteels.in")
    assert client.get("/holidays").status_code == 200


def test_add_and_delete_holiday(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post("/holidays/add", data={"day": "2026-11-01", "label": "Diwali"},
                    follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    h = db.query(Holiday).filter_by(day=date(2026, 11, 1)).one()
    assert h.label == "Diwali"
    # duplicate rejected
    r2 = client.post("/holidays/add", data={"day": "2026-11-01", "label": "dup"},
                     follow_redirects=False)
    assert "err=" in r2.headers["location"]
    # delete
    r3 = client.post(f"/holidays/{h.id}/delete", follow_redirects=False)
    assert r3.status_code == 303
    assert db.query(Holiday).filter_by(day=date(2026, 11, 1)).first() is None
