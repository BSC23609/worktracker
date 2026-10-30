"""Seed the Daily Checks areas + checkpoints from the DAILY_CHECKPOINTS sheet.

Idempotent: an area is matched by name; if it already exists it is left as-is
(so your later edits are never overwritten). Run after the tables exist:

    DATABASE_URL="postgresql+psycopg2://..." python scripts/seed_checklists.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Checklist, CheckpointItem  # noqa: E402

D, W = "daily", "weekly"

# (name, link, login_hint, owner_label, [ (text, action, cadence), ... ])
AREAS = [
    ("Tickets", "app.bharatsteels.in", "BSC/119", "Subashree", [
        ("Check for any open tickets", "Inform the assigned person to close / take action", D),
        ("Gatepass - check for any unreturned gatepass", "Ask HR and close it", D),
    ]),
    ("QMS", "qms.bharatsteels.in", "BSC/119", "Priya", [
        ("Coil Inward - check if entries are made for the previous date", "Inform Dispatch personnel if not done", D),
        ("CTL Inspection - check if entries are made for the previous date", "Inform Quality personnel if not done", D),
        ("Shearing Inspection - check if entries are made for the previous date", "Inform Quality personnel if not done", D),
        ("Pre-delivery Dispatch - check if entries are made for the previous date", "Inform Dispatch personnel if not done", D),
        ("Maintenance - check for any dues", "Check with the assigned user and close it", D),
        ("OneDrive - reports, PDFs and photos are getting saved properly", "Fix any formatting / alignment errors then and there", D),
    ]),
    ("MIS", "mis.bharatsteels.in", "jeeva@bharatsteels.in", "Subashree", [
        ("Check if daily Email and WhatsApp reminders are flowing", "Fix the issue", D),
        ("Check if the previous day's entries are made", "Fix the issue", D),
        ("Track average weighbridge and billing time", "See if there is any improvement", D),
    ]),
    ("ATS", "ats.thebharatsteelgroup.com", "jeeva@bharatsteels.in", "Priya", [
        ("Check for open roles", None, D),
        ("Connect with HRs and make sure all open roles are added in the app", None, D),
        ("Ensure recruitment strictly flows via the app only", None, D),
        ("Ensure HRs properly utilise the app", None, D),
        ("Check if resumes are saved in OneDrive properly", None, D),
    ]),
    ("Metfraa", "app.metfraa.com", "MET-ADMIN", "Subashree", [
        ("EHS entries", None, D),
        ("Gatepass - still unreturned", None, D),
        ("Plant Operations - check if the previous day's daily entries are done", None, D),
        ("Maintenance - check all logs and registers", None, D),
    ]),
    ("Sales", "trainer.bharatsteels.in", "jeeva@bharatsteels.in", "Priya", [
        ("Check in OneDrive if calls are getting saved", None, D),
        ("Check if the previous day's files are getting analysed", None, D),
        ("Check Claude Console credits and Sarvam credits", "Weekly once, on Mondays", W),
    ]),
    ("IT", None, None, "Priya", [
        ("Ensure all assets are up to date", "Check with IT", W),
    ]),
]


def main():
    init_db()
    db = SessionLocal()
    created_areas = created_items = 0
    for order, (name, link, login, owner, items) in enumerate(AREAS, start=1):
        cl = db.scalar(select(Checklist).where(func.lower(Checklist.name) == name.lower()))
        if cl:
            continue  # already seeded — leave it (and any edits) alone
        cl = Checklist(name=name, link=link, login_hint=login, owner_label=owner,
                       sort_order=order, active=True)
        db.add(cl)
        db.flush()
        created_areas += 1
        for seq, (text, action, cadence) in enumerate(items, start=1):
            db.add(CheckpointItem(checklist_id=cl.id, seq=seq, text=text,
                                  action=action, cadence=cadence, active=True))
            created_items += 1
    db.commit()
    total_a = db.scalar(select(func.count()).select_from(Checklist))
    total_i = db.scalar(select(func.count()).select_from(CheckpointItem))
    print(f"Areas created this run: {created_areas} (total {total_a}). "
          f"Checkpoints created: {created_items} (total {total_i}).")
    db.close()


if __name__ == "__main__":
    main()
