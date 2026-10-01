from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..digests import run_daily_digests
from ..models import User

router = APIRouter()


def _check_secret(key: str | None, header: str | None) -> None:
    supplied = key or header
    if supplied != config.CRON_SECRET:
        raise HTTPException(status_code=401, detail="Bad cron secret")


@router.get("/health")
def health(db: Session = Depends(get_db)):
    user_count = db.scalar(select(func.count()).select_from(User))
    return {
        "status": "ok",
        "users": user_count,
        "email": config.NOTIFY_EMAIL_ENABLED,
        "whatsapp": config.NOTIFY_WHATSAPP_ENABLED,
    }


@router.post("/cron/daily-digests")
def daily_digests(key: str | None = Query(None),
                  x_cron_key: str | None = Header(None),
                  force: bool = Query(False),
                  db: Session = Depends(get_db)):
    """Called by GitHub Actions every morning (IST). Protected by a shared secret."""
    _check_secret(key, x_cron_key)
    return run_daily_digests(db, force=force)
