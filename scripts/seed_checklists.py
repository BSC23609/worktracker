"""Seed the Daily Checks areas + checkpoints from the DAILY_CHECKPOINTS sheet.

Idempotent: an area is matched by name; if it already exists it is left as-is
(so your later edits are never overwritten). Run after the tables exist:

    DATABASE_URL="postgresql+psycopg2://..." python scripts/seed_checklists.py

(You can also do this without a shell via the one-time /admin/migrate URL —
 see the deploy notes.)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.checks import seed_default_checklists  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402


def main():
    init_db()
    db = SessionLocal()
    result = seed_default_checklists(db)
    print(f"Areas created this run: {result['areas_created']} (total {result['areas_total']}). "
          f"Checkpoints created: {result['checkpoints_created']} (total {result['checkpoints_total']}).")
    db.close()


if __name__ == "__main__":
    main()
