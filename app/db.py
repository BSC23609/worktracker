from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

# SQLite needs check_same_thread off; Postgres ignores connect_args.
_connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    connect_args=_connect_args,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def now_ist() -> datetime:
    return datetime.now(config.IST)


def today_ist() -> date:
    return now_ist().date()


def init_db() -> None:
    """Idempotent create-all. Safe to run repeatedly."""
    from . import models  # noqa: F401  (register mappers)
    Base.metadata.create_all(bind=engine)
