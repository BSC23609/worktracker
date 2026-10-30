"""Daily Checks — shared trainee checkpoint checklist."""
from datetime import date

from app.checks import checklist_view, item_due_on, save_checklist
from app.db import today_ist
from app.models import Checklist, CheckpointItem, CheckpointStatus, Holiday, User
from tests.conftest import login_as

TUE = date(2026, 1, 6)   # a Tuesday (working day)
MON = date(2026, 1, 5)   # a Monday


def _u(db, email):
    return db.query(User).filter_by(email=email).one()


def _seed(db):
    cl = Checklist(name="QMS", link="qms.bharatsteels.in", login_hint="BSC/119",
                   owner_label="Priya", sort_order=1, active=True)
    db.add(cl); db.flush()
    d1 = CheckpointItem(checklist_id=cl.id, seq=1, text="Coil inward entries",
                        action="Inform dispatch", cadence="daily", active=True)
    d2 = CheckpointItem(checklist_id=cl.id, seq=2, text="Weekly credit check",
                        action=None, cadence="weekly", active=True)
    db.add_all([d1, d2]); db.commit()
    db.refresh(cl); db.refresh(d1); db.refresh(d2)
    return cl, d1, d2


# ---- cadence --------------------------------------------------------------
def test_item_due_on_cadence():
    assert item_due_on("daily", TUE, True) is True
    assert item_due_on("weekly", TUE, True) is False      # weekly hides on non-Monday
    assert item_due_on("weekly", MON, True) is True        # shows on Monday
    assert item_due_on("daily", TUE, False) is False       # non-working day


def test_view_shows_daily_hides_weekly_on_tuesday(db):
    _seed(db)
    areas, working = checklist_view(db, TUE)
    assert working is True
    assert len(areas) == 1
    rows = areas[0]["rows"]
    assert len(rows) == 1 and rows[0]["item"].text == "Coil inward entries"


def test_view_shows_weekly_on_monday(db):
    _seed(db)
    areas, _ = checklist_view(db, MON)
    texts = {r["item"].text for r in areas[0]["rows"]}
    assert texts == {"Coil inward entries", "Weekly credit check"}


def test_non_working_day_has_nothing_due(db):
    _seed(db)
    db.add(Holiday(day=TUE, label="Test holiday")); db.commit()
    areas, working = checklist_view(db, TUE)
    assert working is False and areas == []


# ---- shared completion (the "cover when on leave" requirement) ------------
def test_tick_is_shared_between_trainees(db):
    cl, d1, _ = _seed(db)
    ravi, priya = _u(db, "ravi@bharatsteels.in"), _u(db, "priya@bharatsteels.in")

    # Ravi ticks the daily item
    save_checklist(db, checklist_id=cl.id, d=TUE, actor=ravi, done_ids={d1.id}, notes={})
    areas, _ = checklist_view(db, TUE)
    assert areas[0]["done"] == 1

    # Priya opens the SAME shared checklist and sees it already done, then adds a note
    save_checklist(db, checklist_id=cl.id, d=TUE, actor=priya,
                   done_ids={d1.id}, notes={d1.id: "all good"})
    rows = db.query(CheckpointStatus).filter_by(item_id=d1.id, on_date=TUE).all()
    assert len(rows) == 1                      # one shared row, not one per person
    assert rows[0].done is True
    assert rows[0].note == "all good"
    assert rows[0].marked_by_id == priya.id    # latest saver owns it


def test_unticking_sets_not_done(db):
    cl, d1, _ = _seed(db)
    ravi = _u(db, "ravi@bharatsteels.in")
    save_checklist(db, checklist_id=cl.id, d=TUE, actor=ravi, done_ids={d1.id}, notes={})
    save_checklist(db, checklist_id=cl.id, d=TUE, actor=ravi, done_ids=set(), notes={})
    st = db.query(CheckpointStatus).filter_by(item_id=d1.id, on_date=TUE).one()
    assert st.done is False


# ---- HTTP -----------------------------------------------------------------
def test_checks_visible_only_to_trainees_and_superadmins(client, db):
    _seed(db)
    # a general user WITHOUT the Daily Checks flag cannot see it
    login_as(client, db, "ravi@bharatsteels.in")
    assert client.get("/checks").status_code == 403
    # flag Ravi as a trainee -> now allowed
    ravi = _u(db, "ravi@bharatsteels.in")
    ravi.can_daily_checks = True
    db.commit()
    assert client.get("/checks").status_code == 200
    # superadmins always have access, no flag needed
    login_as(client, db, "gourav@bharatsteels.in")
    assert client.get("/checks").status_code == 200


def test_unflagged_user_cannot_save_checks(client, db):
    cl, d1, _ = _seed(db)
    login_as(client, db, "priya@bharatsteels.in")   # no flag
    r = client.post(f"/checks/{cl.id}/save", data={"done": [str(d1.id)]},
                    follow_redirects=False)
    assert r.status_code == 403


def test_save_via_http_as_superadmin_backdated(client, db):
    cl, d1, _ = _seed(db)
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post(f"/checks/{cl.id}/save",
                    data={"d": TUE.isoformat(), "done": [str(d1.id)],
                          f"note_{d1.id}": "checked"}, follow_redirects=False)
    assert r.status_code == 303
    st = db.query(CheckpointStatus).filter_by(item_id=d1.id, on_date=TUE).one()
    assert st.done is True and st.note == "checked"


def test_manage_is_superadmin_only(client, db):
    login_as(client, db, "ravi@bharatsteels.in")
    assert client.get("/checks/manage").status_code == 403
    login_as(client, db, "gourav@bharatsteels.in")
    assert client.get("/checks/manage").status_code == 200


def test_admin_migrate_requires_secret(client):
    assert client.get("/admin/migrate").status_code == 401
    assert client.get("/admin/migrate?key=wrong").status_code == 401


def test_admin_migrate_seeds_default_checklists(client, db):
    r = client.get("/admin/migrate?key=test-cron")
    assert r.status_code == 200
    body = r.json()
    assert body["migrated"] is True
    assert body["seed"]["checkpoints_total"] == 24
    assert db.query(Checklist).filter_by(name="QMS").count() == 1
    assert db.query(CheckpointItem).count() == 24


def test_manage_create_area_and_item(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    client.post("/checks/manage/area/create", data={
        "name": "Dispatch", "link": "mis.bharatsteels.in", "login_hint": "jeeva@bharatsteels.in",
        "owner_label": "Subashree", "sort_order": "2"}, follow_redirects=False)
    cl = db.query(Checklist).filter_by(name="Dispatch").one()
    client.post("/checks/manage/item/create", data={
        "checklist_id": str(cl.id), "text": "Check inbound coils",
        "action": "Inform dispatch", "cadence": "daily"}, follow_redirects=False)
    items = db.query(CheckpointItem).filter_by(checklist_id=cl.id).all()
    assert len(items) == 1 and items[0].text == "Check inbound coils" and items[0].seq == 1
