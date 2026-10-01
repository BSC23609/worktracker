import os
import sys
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite://")  # overridden below anyway
os.environ.setdefault("CRON_SECRET", "test-cron")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import config  # noqa: E402
from app.auth import hash_password, make_session_token  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ROLE_SUPERADMIN, ROLE_USER, User  # noqa: E402


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = TestSession()

    # seed: 2 superadmins + 2 general users
    users = [
        User(name="Gourav", email="gourav@bharatsteels.in", role=ROLE_SUPERADMIN,
             whatsapp="919500680093", password_hash=hash_password("x"), must_reset=False),
        User(name="Jeeva", email="jeeva@bharatsteels.in", role=ROLE_SUPERADMIN,
             password_hash=hash_password("x"), must_reset=False),
        User(name="Ravi", email="ravi@bharatsteels.in", role=ROLE_USER,
             whatsapp="9876543210", password_hash=hash_password("x"), must_reset=False),
        User(name="Priya", email="priya@bharatsteels.in", role=ROLE_USER,
             password_hash=hash_password("x"), must_reset=False),
    ]
    session.add_all(users)
    session.commit()
    for u in users:
        session.refresh(u)

    yield session
    session.close()


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    from fastapi.testclient import TestClient
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def login_as(client, db, email):
    user = next(u for u in db.query(User).all() if u.email == email)
    client.cookies.set(config.SESSION_COOKIE, make_session_token(user.id))
    return user
