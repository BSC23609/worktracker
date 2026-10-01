"""Create tables and seed the two superadmins. Idempotent.

Run once after setting DATABASE_URL (locally or against Neon):
    DATABASE_URL="postgresql+psycopg2://..." python scripts/init_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app import config  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import ROLE_SUPERADMIN, User  # noqa: E402

SEED_SUPERADMINS = [
    ("Gourav Saraf", "gourav@bharatsteels.in"),
    ("Jeeva", "jeeva@bharatsteels.in"),
]


def main():
    init_db()
    db = SessionLocal()
    created = 0
    for name, email in SEED_SUPERADMINS:
        if not db.scalar(select(User).where(User.email == email)):
            db.add(User(name=name, email=email, role=ROLE_SUPERADMIN,
                        password_hash=hash_password(config.DEFAULT_PASSWORD),
                        must_reset=True, active=True))
            created += 1
    db.commit()
    total = db.scalar(select(__import__("sqlalchemy").func.count()).select_from(User))
    print(f"Schema ready. Superadmins created this run: {created}. Total users: {total}.")
    print(f"Default password: {config.DEFAULT_PASSWORD} (must be changed on first login).")
    db.close()


if __name__ == "__main__":
    main()
