from datetime import timedelta

import pytest

from app import config
from app.db import today_ist
from app.models import Task, TaskAttachment, User
from app.services import TaskError, add_attachment, create_task
from tests.conftest import login_as


def _future(n):
    return (today_ist() + timedelta(days=n)).isoformat()


def _u(db, email):
    return db.query(User).filter_by(email=email).one()


# ---- service level --------------------------------------------------------
def test_add_attachment_stores_bytes(db):
    g, r = _u(db, "gourav@bharatsteels.in"), _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=g, assigned_to=r, title="With file",
                    deadline=today_ist() + timedelta(days=3))
    att = add_attachment(db, task=t, actor=g, filename="spec.pdf",
                         content_type="application/pdf", data=b"%PDF-1.4 hello")
    assert att.id and att.size == len(b"%PDF-1.4 hello")
    assert att.filename == "spec.pdf" and att.content_type == "application/pdf"


def test_attachment_rejects_oversize(db, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 10)
    g, r = _u(db, "gourav@bharatsteels.in"), _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=g, assigned_to=r, title="Big",
                    deadline=today_ist() + timedelta(days=3))
    with pytest.raises(TaskError, match="too large"):
        add_attachment(db, task=t, actor=g, filename="big.bin",
                       content_type="application/octet-stream", data=b"x" * 50)


def test_attachment_outsider_blocked(db):
    g, r = _u(db, "gourav@bharatsteels.in"), _u(db, "ravi@bharatsteels.in")
    priya = _u(db, "priya@bharatsteels.in")
    t = create_task(db, created_by=g, assigned_to=r, title="Private",
                    deadline=today_ist() + timedelta(days=3))
    with pytest.raises(TaskError, match="can't attach"):
        add_attachment(db, task=t, actor=priya, filename="x.txt",
                       content_type="text/plain", data=b"hi")


# ---- HTTP level -----------------------------------------------------------
def test_create_with_attachment_and_download(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    ravi = _u(db, "ravi@bharatsteels.in")
    r = client.post("/tasks/create",
                    data={"title": "Has doc", "assigned_to_ids": [str(ravi.id)],
                          "deadline": _future(4), "priority": "medium"},
                    files=[("attachments", ("plan.txt", b"attached-content", "text/plain"))],
                    follow_redirects=False)
    assert r.status_code == 303
    t = db.query(Task).filter_by(title="Has doc").one()
    atts = db.query(TaskAttachment).filter_by(task_id=t.id).all()
    assert len(atts) == 1 and atts[0].filename == "plan.txt"

    # assignee can download and gets the exact bytes
    login_as(client, db, "ravi@bharatsteels.in")
    dl = client.get(f"/tasks/{t.id}/attachments/{atts[0].id}")
    assert dl.status_code == 200 and dl.content == b"attached-content"
    assert "attachment" in dl.headers["content-disposition"]


def test_add_attachment_to_existing_task_via_http(client, db):
    login_as(client, db, "ravi@bharatsteels.in")
    ravi = _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=ravi, assigned_to=ravi, title="Self doc",
                    deadline=today_ist() + timedelta(days=3))
    r = client.post(f"/tasks/{t.id}/attachments",
                    files=[("attachments", ("a.txt", b"one", "text/plain")),
                           ("attachments", ("b.txt", b"two", "text/plain"))],
                    follow_redirects=False)
    assert r.status_code == 303
    assert db.query(TaskAttachment).filter_by(task_id=t.id).count() == 2


def test_outsider_cannot_download_attachment(client, db):
    g = login_as(client, db, "gourav@bharatsteels.in")
    ravi = _u(db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=g, assigned_to=ravi, title="Secret",
                    deadline=today_ist() + timedelta(days=3))
    att = add_attachment(db, task=t, actor=g, filename="s.txt",
                         content_type="text/plain", data=b"secret")
    login_as(client, db, "priya@bharatsteels.in")
    assert client.get(f"/tasks/{t.id}/attachments/{att.id}").status_code == 403


def test_delete_attachment(client, db):
    ravi = login_as(client, db, "ravi@bharatsteels.in")
    t = create_task(db, created_by=ravi, assigned_to=ravi, title="Del doc",
                    deadline=today_ist() + timedelta(days=3))
    att = add_attachment(db, task=t, actor=ravi, filename="d.txt",
                         content_type="text/plain", data=b"bye")
    r = client.post(f"/tasks/{t.id}/attachments/{att.id}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert db.query(TaskAttachment).filter_by(task_id=t.id).count() == 0


# ---- user deletion --------------------------------------------------------
def test_delete_user_without_tasks(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    client.post("/master/users/create", data={
        "name": "Temp", "email": "temp@bharatsteels.in", "whatsapp": "", "role": "user"})
    u = _u(db, "temp@bharatsteels.in")
    r = client.post(f"/master/users/{u.id}/delete", follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    assert db.query(User).filter_by(email="temp@bharatsteels.in").first() is None


def test_cannot_delete_user_with_tasks(client, db):
    g = login_as(client, db, "gourav@bharatsteels.in")
    ravi = _u(db, "ravi@bharatsteels.in")
    create_task(db, created_by=g, assigned_to=ravi, title="keeps ravi",
                deadline=today_ist() + timedelta(days=3))
    r = client.post(f"/master/users/{ravi.id}/delete", follow_redirects=False)
    assert r.status_code == 303 and "err=" in r.headers["location"]
    assert db.query(User).filter_by(id=ravi.id).first() is not None


def test_cannot_delete_self(client, db):
    gourav = _u(db, "gourav@bharatsteels.in")
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post(f"/master/users/{gourav.id}/delete", follow_redirects=False)
    assert "err=" in r.headers["location"]
    assert db.query(User).filter_by(id=gourav.id).first() is not None
