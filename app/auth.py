from __future__ import annotations

from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models import ROLE_SUPERADMIN, User

_serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt="wt-session")


def _enc(raw: str) -> bytes:
    # bcrypt caps at 72 bytes; encode then truncate defensively.
    return raw.encode("utf-8")[:72]


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(_enc(raw), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_enc(raw), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def make_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str) -> Optional[int]:
    try:
        data = _serializer.loads(token, max_age=config.SESSION_MAX_AGE)
        return int(data["uid"])
    except (BadSignature, KeyError, ValueError, TypeError):
        return None


def authenticate(db: Session, email: str, password: str) -> Optional[User]:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user or not user.active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


# ---- dependencies ---------------------------------------------------------
def current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    token = request.cookies.get(config.SESSION_COOKIE)
    if not token:
        return None
    uid = read_session_token(token)
    if uid is None:
        return None
    user = db.get(User, uid)
    if user and user.active:
        return user
    return None


def require_user(user: Optional[User] = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
    return user


def require_superadmin(user: User = Depends(require_user)) -> User:
    if user.role != ROLE_SUPERADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin only")
    return user
