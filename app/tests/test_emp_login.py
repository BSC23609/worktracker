"""Login by email OR employee code, incl. users with no email."""
from app.auth import authenticate, hash_password
from app.models import User
from tests.conftest import login_as


def _mk(db, **kw):
    kw.setdefault("password_hash", hash_password("Secret#1"))
    kw.setdefault("name", "X")
    u = User(**kw)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_login_by_email(db):
    _mk(db, email="a@bharatsteels.in", emp_code="BSC/900")
    assert authenticate(db, "a@bharatsteels.in", "Secret#1") is not None
    assert authenticate(db, "A@BHARATSTEELS.IN", "Secret#1") is not None  # case-insensitive
    assert authenticate(db, "a@bharatsteels.in", "wrong") is None


def test_login_by_emp_code(db):
    _mk(db, email="b@bharatsteels.in", emp_code="BSC/901")
    assert authenticate(db, "BSC/901", "Secret#1") is not None
    assert authenticate(db, "bsc/901", "Secret#1") is not None  # case-insensitive


def test_no_email_user_logs_in_by_code_only(db):
    u = _mk(db, email=None, emp_code="BSC/902", name="No Mail")
    assert u.email is None
    assert authenticate(db, "BSC/902", "Secret#1") is not None
    assert authenticate(db, "", "Secret#1") is None  # empty identifier rejected


def test_inactive_user_cannot_login(db):
    _mk(db, email=None, emp_code="BSC/903", active=False)
    assert authenticate(db, "BSC/903", "Secret#1") is None


def test_create_user_emp_code_only_via_master(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post("/master/users/create", data={
        "name": "Code Only", "email": "", "emp_code": "bsc/950",
        "whatsapp": "9000000001", "role": "user"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    u = db.query(User).filter_by(emp_code="BSC/950").one()  # stored upper-cased
    assert u.email is None and u.whatsapp == "919000000001" and u.must_reset is True


def test_create_user_requires_email_or_code(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    r = client.post("/master/users/create", data={
        "name": "Nobody", "email": "", "emp_code": "", "role": "user"},
        follow_redirects=False)
    assert "err=" in r.headers["location"]
    assert db.query(User).filter_by(name="Nobody").first() is None


def test_duplicate_emp_code_rejected(client, db):
    login_as(client, db, "gourav@bharatsteels.in")
    _mk(db, email="c@bharatsteels.in", emp_code="BSC/960")
    r = client.post("/master/users/create", data={
        "name": "Clash", "email": "d@bharatsteels.in", "emp_code": "BSC/960",
        "role": "user"}, follow_redirects=False)
    assert "err=" in r.headers["location"]
    assert db.query(User).filter_by(name="Clash").first() is None
