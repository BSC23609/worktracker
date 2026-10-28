"""Group single sign-on: the group portal hands the person over with a one-minute token."""
import os
import time

import jwt

SECRET = "group-test-secret"


def _tok(sub, aud="worktracker", secret=SECRET, exp=60, email=None):
    now = int(time.time())
    return jwt.encode({"iss": "bsg-hub", "aud": aud, "sub": sub, "email": email, "name": "x",
                       "iat": now, "exp": now + exp}, secret, algorithm="HS256")


def test_group_sso(client, db, monkeypatch):
    monkeypatch.setenv("GROUP_SSO_SECRET", SECRET)
    r = client.get("/auth/sso", params={"token": _tok("Ravi@BharatSteels.in"), "next": "/"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    who = client.get("/whoami").json()
    assert who["logged_in"] and who["email"] == "ravi@bharatsteels.in"

    client.cookies.clear()
    assert client.get("/auth/sso", params={"token": _tok("x", email="priya@bharatsteels.in")}, follow_redirects=False).status_code == 303
    for bad in (_tok("ravi@bharatsteels.in", aud="qms"), _tok("ravi@bharatsteels.in", secret="nope"),
                _tok("ravi@bharatsteels.in", exp=-120), _tok("ghost@bharatsteels.in")):
        client.cookies.clear()
        assert client.get("/auth/sso", params={"token": bad}, follow_redirects=False).status_code == 401
    r = client.get("/auth/sso", params={"token": _tok("ravi@bharatsteels.in"), "next": "//evil.com"}, follow_redirects=False)
    assert r.headers["location"] == "/"
    monkeypatch.delenv("GROUP_SSO_SECRET")
    assert "not set up" in client.get("/auth/sso", params={"token": _tok("ravi@bharatsteels.in")}).text
