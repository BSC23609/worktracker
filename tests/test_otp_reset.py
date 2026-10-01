"""Forgot password via WhatsApp OTP -> enter code -> set new password."""
from app import notifications
from app.auth import (
    authenticate,
    generate_otp,
    hash_password,
    make_otp_cookie,
    make_reset_cookie,
    otp_matches,
    read_otp_cookie,
    read_reset_cookie,
)
from app.models import User


def _u(db, email):
    return db.query(User).filter_by(email=email).one()


# ---- unit: cookies --------------------------------------------------------
def test_generate_otp_shape():
    otp = generate_otp()
    assert otp.isdigit() and len(otp) == 6


def test_otp_cookie_roundtrip_and_match():
    tok = make_otp_cookie(7, "123456", 5)
    data = read_otp_cookie(tok)
    assert data["uid"] == 7 and data["n"] == 5
    assert otp_matches(data, "123456") is True
    assert otp_matches(data, "000000") is False
    # the plaintext code is NOT stored in the cookie payload
    assert "123456" not in str(data)


def test_reset_cookie_single_use(db):
    u = _u(db, "ravi@bharatsteels.in")
    tok = make_reset_cookie(u)
    assert read_reset_cookie(db, tok).id == u.id
    u.password_hash = hash_password("Changed#1")
    db.commit()
    assert read_reset_cookie(db, tok) is None   # stops working once password changes


# ---- HTTP flow ------------------------------------------------------------
def _capture_otp(monkeypatch):
    box = {}
    monkeypatch.setattr(notifications, "send_otp",
                        lambda session, user, otp: box.update(otp=otp, uid=user.id) or True)
    return box


def test_full_forgot_flow(client, db, monkeypatch):
    box = _capture_otp(monkeypatch)
    u = _u(db, "priya@bharatsteels.in")
    u.must_reset = True
    db.commit()

    r = client.post("/forgot", data={"identifier": "priya@bharatsteels.in"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/verify-otp"
    assert "otp" in box  # a code was generated and sent

    r2 = client.post("/verify-otp", data={"otp": box["otp"]}, follow_redirects=False)
    assert r2.status_code == 303 and r2.headers["location"] == "/reset-password"

    r3 = client.post("/reset-password", data={"new": "FreshPass#9", "confirm": "FreshPass#9"},
                     follow_redirects=False)
    assert r3.status_code == 303 and r3.headers["location"].startswith("/login")
    db.refresh(u)
    assert u.must_reset is False
    assert authenticate(db, "priya@bharatsteels.in", "FreshPass#9") is not None


def test_wrong_otp_decrements_then_blocks(client, db, monkeypatch):
    box = _capture_otp(monkeypatch)
    client.post("/forgot", data={"identifier": "ravi@bharatsteels.in"})
    # wrong code -> error with attempts left, still on verify page
    r = client.post("/verify-otp", data={"otp": "000000"}, follow_redirects=False)
    assert "err=" in r.headers["location"] and r.headers["location"].startswith("/verify-otp")
    # exhaust remaining attempts
    for _ in range(5):
        r = client.post("/verify-otp", data={"otp": "000000"}, follow_redirects=False)
    assert r.headers["location"].startswith("/forgot")  # blocked, sent back to request a new code


def test_correct_otp_after_a_wrong_one(client, db, monkeypatch):
    box = _capture_otp(monkeypatch)
    client.post("/forgot", data={"identifier": "ravi@bharatsteels.in"})
    client.post("/verify-otp", data={"otp": "999999"}, follow_redirects=False)  # one wrong
    r = client.post("/verify-otp", data={"otp": box["otp"]}, follow_redirects=False)
    assert r.headers["location"] == "/reset-password"  # correct code still accepted


def test_forgot_unknown_user_sends_nothing(client, db, monkeypatch):
    box = _capture_otp(monkeypatch)
    r = client.post("/forgot", data={"identifier": "ghost@nowhere.in"}, follow_redirects=False)
    assert r.headers["location"] == "/verify-otp"   # same screen, no enumeration
    assert box == {}                                # but no code sent
    # and entering anything fails (no challenge cookie)
    r2 = client.post("/verify-otp", data={"otp": "123456"}, follow_redirects=False)
    assert r2.headers["location"].startswith("/forgot")


def test_forgot_by_emp_code(client, db, monkeypatch):
    box = _capture_otp(monkeypatch)
    db.add(User(name="Code Only", emp_code="BSC/981", whatsapp="919000000003",
                password_hash=hash_password("x"), role="user", active=True))
    db.commit()
    client.post("/forgot", data={"identifier": "bsc/981"}, follow_redirects=False)
    u = db.query(User).filter_by(emp_code="BSC/981").one()
    assert box.get("uid") == u.id


def test_reset_password_without_otp_is_blocked(client, db):
    # hitting reset-password with no verified cookie must not allow a change
    r = client.post("/reset-password", data={"new": "Hacker#1", "confirm": "Hacker#1"},
                    follow_redirects=False)
    assert r.headers["location"].startswith("/forgot")
