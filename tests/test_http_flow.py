from datetime import timedelta

from app.db import today_ist
from app.models import Task, User
from tests.conftest import login_as


def _future(n):
    return (today_ist() + timedelta(days=n)).isoformat()


def test_login_required_redirects(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_browser_401_redirects_to_login(client):
    # a browser (Accept: text/html) hitting a protected page with no session
    r = client.get("/master", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_api_401_stays_json(client):
    r = client.get("/master", headers={"Accept": "application/json"}, follow_redirects=False)
    assert r.status_code == 401 and r.json()["detail"] == "Login required"


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_pwa_assets_served(client):
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    assert client.get("/favicon.ico").status_code == 200
    man = client.get("/static/manifest.webmanifest")
    assert man.status_code == 200 and client.get("/static/icons/icon-192.png").status_code == 200


def test_superadmin_assigns_and_employee_sees_it(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    ravi = db.query(User).filter_by(email="ravi@bharatsteels.in").one()
    r = client.post("/tasks/create", data={
        "title": "Reconcile NMDC ledger", "description": "Sept", "priority": "high",
        "assigned_to_ids": [str(ravi.id)], "deadline": _future(5),
    }, follow_redirects=False)
    assert r.status_code == 303
    task = db.query(Task).filter_by(title="Reconcile NMDC ledger").one()
    assert task.assigned_to_id == ravi.id

    # Ravi logs in and sees exactly his task on the board
    login_as(client, db, "ravi@bharatsteels.in")
    board = client.get("/")
    assert "Reconcile NMDC ledger" in board.text


def test_employee_self_raise_via_http(client, db):
    login_as(client, db, "priya@bharatsteels.in")
    r = client.post("/tasks/create", data={
        "title": "Prepare my weekly plan", "deadline": _future(2), "priority": "medium",
    }, follow_redirects=False)
    assert r.status_code == 303
    t = db.query(Task).filter_by(title="Prepare my weekly plan").one()
    assert t.is_self_raised is True


def test_extend_via_http_keeps_history(client, db):
    g = login_as(client, db, "gourav@bharatsteels.in")
    ravi = db.query(User).filter_by(email="ravi@bharatsteels.in").one()
    client.post("/tasks/create", data={
        "title": "HTTP extend", "assigned_to_ids": [str(ravi.id)], "deadline": _future(3),
    })
    task = db.query(Task).filter_by(title="HTTP extend").one()

    login_as(client, db, "ravi@bharatsteels.in")
    r = client.post(f"/tasks/{task.id}/extend",
                    data={"new_deadline": _future(9), "reason": "Material delayed"},
                    follow_redirects=False)
    assert r.status_code == 303
    db.refresh(task)
    assert len(task.deadlines) == 2
    assert task.original_deadline.isoformat() == _future(3)
    assert task.current_deadline.isoformat() == _future(9)

    # the detail page shows both deadlines and the reason
    page = client.get(f"/tasks/{task.id}")
    assert "Material delayed" in page.text
    assert "Original" in page.text and "Current" in page.text


def test_completed_tasks_show_on_board(client, db):
    from app.services import complete_task, create_task
    g = login_as(client, db, "gourav@bharatsteels.in")
    ravi = db.query(User).filter_by(email="ravi@bharatsteels.in").one()
    t = create_task(db, created_by=g, assigned_to=ravi, title="Finished job",
                    deadline=today_ist() + timedelta(days=2))
    complete_task(db, task=t, actor=ravi, note="done")
    # superadmin board shows the completed task (all)
    assert "Finished job" in client.get("/").text
    # the assignee sees their own completed task
    login_as(client, db, "ravi@bharatsteels.in")
    assert "Finished job" in client.get("/").text
    # another general user does NOT see it
    login_as(client, db, "priya@bharatsteels.in")
    assert "Finished job" not in client.get("/").text


def test_employee_cannot_open_others_task(client, db):
    g = login_as(client, db, "gourav@bharatsteels.in")
    ravi = db.query(User).filter_by(email="ravi@bharatsteels.in").one()
    client.post("/tasks/create", data={
        "title": "Ravi only", "assigned_to_ids": [str(ravi.id)], "deadline": _future(3)})
    task = db.query(Task).filter_by(title="Ravi only").one()
    login_as(client, db, "priya@bharatsteels.in")
    r = client.get(f"/tasks/{task.id}")
    assert r.status_code == 403


def test_master_tab_superadmin_only(client, db):
    login_as(client, db, "ravi@bharatsteels.in")
    assert client.get("/master").status_code == 403
    login_as(client, db, "gourav@bharatsteels.in")
    assert client.get("/master").status_code == 200


def test_master_create_user(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post("/master/users/create", data={
        "name": "New Staff", "email": "newstaff@bharatsteels.in",
        "whatsapp": "9000000000", "role": "user"}, follow_redirects=False)
    assert r.status_code == 303
    u = db.query(User).filter_by(email="newstaff@bharatsteels.in").one()
    assert u.whatsapp == "919000000000" and u.must_reset is True


def test_cannot_remove_last_superadmin(client, db):
    # demote Jeeva first (ok, Gourav remains), then try to demote Gourav (blocked)
    login_as(client, db, "gourav@bharatsteels.in")
    jeeva = db.query(User).filter_by(email="jeeva@bharatsteels.in").one()
    gourav = db.query(User).filter_by(email="gourav@bharatsteels.in").one()
    client.post(f"/master/users/{jeeva.id}/update",
                data={"name": "Jeeva", "role": "user", "active": "on"})
    db.refresh(jeeva); assert jeeva.role == "user"
    r = client.post(f"/master/users/{gourav.id}/update",
                    data={"name": "Gourav", "role": "user", "active": "on"},
                    follow_redirects=False)
    db.refresh(gourav)
    assert gourav.role == "superadmin"  # blocked
    assert "err=" in r.headers["location"]


def test_cron_requires_secret(client):
    assert client.post("/cron/daily-digests").status_code == 401
    assert client.post("/cron/daily-digests?key=wrong").status_code == 401
    ok = client.post("/cron/daily-digests", headers={"X-Cron-Key": "test-cron"})
    assert ok.status_code == 200 and "employee_sent" in ok.json()
