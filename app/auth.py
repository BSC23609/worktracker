from __future__ import annotations

from typing import Optional

import hashlib
import hmac
import secrets

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models import ROLE_SUPERADMIN, User

_serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt="wt-session")
_otp_serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt="wt-otp")
_reset_serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt="wt-pwreset")


def _hash_tail(password_hash: str) -> str:
    return (password_hash or "")[-12:]


def generate_otp(length: int | None = None) -> str:
    n = length or config.OTP_LENGTH
    return "".join(secrets.choice("0123456789") for _ in range(n))


def _otp_fingerprint(otp: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), otp.encode(), hashlib.sha256).hexdigest()[:20]


def make_otp_cookie(user_id: int, otp: str, attempts: int) -> str:
    """Signed, expiring holder for an OTP challenge (stores a fingerprint, not the code)."""
    return _otp_serializer.dumps({"uid": user_id, "fp": _otp_fingerprint(otp), "n": attempts})


def read_otp_cookie(token: str) -> Optional[dict]:
    try:
        data = _otp_serializer.loads(token, max_age=config.OTP_TTL)
        return data if isinstance(data, dict) else None
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None


def otp_matches(data: dict, otp: str) -> bool:
    return bool(data) and hmac.compare_digest(data.get("fp", ""), _otp_fingerprint((otp or "").strip()))


def reissue_otp_cookie(data: dict, attempts: int) -> str:
    """Re-sign an existing OTP challenge with fewer attempts (same code fingerprint)."""
    return _otp_serializer.dumps({"uid": data["uid"], "fp": data["fp"], "n": attempts})


def make_reset_cookie(user: User) -> str:
    """Issued only after a correct OTP; authorises setting a new password. Single-use:
    it stops working once the password changes (hash tail no longer matches)."""
    return _reset_serializer.dumps({"uid": user.id, "h": _hash_tail(user.password_hash)})


def read_reset_cookie(db: Session, token: str) -> Optional[User]:
    try:
        data = _reset_serializer.loads(token, max_age=config.PWRESET_TTL)
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None
    user = db.get(User, data.get("uid")) if isinstance(data, dict) else None
    if not user or not user.active or data.get("h") != _hash_tail(user.password_hash):
        return None
    return user


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
    # No max_age here on purpose: the signature must not time-expire (that caused
    # periodic logouts from clock skew). The cookie's own Max-Age (180 days) is
    # what ends the session; logging out clears it.
    try:
        data = _serializer.loads(token)
        return int(data["uid"])
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None


def authenticate(db: Session, identifier: str, password: str) -> Optional[User]:
    ident = (identifier or "").strip()
    if not ident:
        return None
    # Match by email (case-insensitive) first, then by employee code.
    user = db.scalar(select(User).where(func.lower(User.email) == ident.lower()))
    if not user:
        user = db.scalar(select(User).where(func.upper(User.emp_code) == ident.upper()))
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
