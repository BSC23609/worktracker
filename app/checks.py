"""Daily Checks — the trainees' shared checkpoint checklist.

Design:
  * One shared checklist per working day. Every trainee sees every area and
    anyone can tick any item (so leave is covered automatically).
  * Items have a cadence: daily (every working day) or weekly (Mondays).
  * Sundays and Holiday-Master dates are non-working — nothing is due.
  * A tick is one shared row per (item, date); the latest saver owns it.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from sqlalchemy import func

from .db import now_ist
from .digests import is_working_day
from .models import (CADENCE_DAILY, CADENCE_WEEKLY, Checklist, CheckpointItem,
                     CheckpointStatus, User)


_D, _W = CADENCE_DAILY, CADENCE_WEEKLY

# The default checklist taken from the DAILY_CHECKPOINTS sheet.
# (name, link, login_hint, owner_label, [(text, action, cadence), ...])
DEFAULT_AREAS = [
    ("Tickets", "app.bharatsteels.in", "BSC/119", "Subashree", [
        ("Check for any open tickets", "Inform the assigned person to close / take action", _D),
        ("Gatepass - check for any unreturned gatepass", "Ask HR and close it", _D),
    ]),
    ("QMS", "qms.bharatsteels.in", "BSC/119", "Priya", [
        ("Coil Inward - check if entries are made for the previous date", "Inform Dispatch personnel if not done", _D),
        ("CTL Inspection - check if entries are made for the previous date", "Inform Quality personnel if not done", _D),
        ("Shearing Inspection - check if entries are made for the previous date", "Inform Quality personnel if not done", _D),
        ("Pre-delivery Dispatch - check if entries are made for the previous date", "Inform Dispatch personnel if not done", _D),
        ("Maintenance - check for any dues", "Check with the assigned user and close it", _D),
        ("OneDrive - reports, PDFs and photos are getting saved properly", "Fix any formatting / alignment errors then and there", _D),
    ]),
    ("MIS", "mis.bharatsteels.in", "jeeva@bharatsteels.in", "Subashree", [
        ("Check if daily Email and WhatsApp reminders are flowing", "Fix the issue", _D),
        ("Check if the previous day's entries are made", "Fix the issue", _D),
        ("Track average weighbridge and billing time", "See if there is any improvement", _D),
    ]),
    ("ATS", "ats.thebharatsteelgroup.com", "jeeva@bharatsteels.in", "Priya", [
        ("Check for open roles", None, _D),
        ("Connect with HRs and make sure all open roles are added in the app", None, _D),
        ("Ensure recruitment strictly flows via the app only", None, _D),
        ("Ensure HRs properly utilise the app", None, _D),
        ("Check if resumes are saved in OneDrive properly", None, _D),
    ]),
    ("Metfraa", "app.metfraa.com", "MET-ADMIN", "Subashree", [
        ("EHS entries", None, _D),
        ("Gatepass - still unreturned", None, _D),
        ("Plant Operations - check if the previous day's daily entries are done", None, _D),
        ("Maintenance - check all logs and registers", None, _D),
    ]),
    ("Sales", "trainer.bharatsteels.in", "jeeva@bharatsteels.in", "Priya", [
        ("Check in OneDrive if calls are getting saved", None, _D),
        ("Check if the previous day's files are getting analysed", None, _D),
        ("Check Claude Console credits and Sarvam credits", "Weekly once, on Mondays", _W),
    ]),
    ("IT", None, None, "Priya", [
        ("Ensure all assets are up to date", "Check with IT", _W),
    ]),
]


def seed_default_checklists(db: Session) -> dict:
    """Create the default areas + checkpoints if missing. Idempotent: an area
    already present (matched by name) is left untouched, edits and all."""
    created_a = created_i = 0
    for order, (name, link, login, owner, items) in enumerate(DEFAULT_AREAS, start=1):
        cl = db.scalar(select(Checklist).where(func.lower(Checklist.name) == name.lower()))
        if cl:
            continue
        cl = Checklist(name=name, link=link, login_hint=login, owner_label=owner,
                       sort_order=order, active=True)
        db.add(cl)
        db.flush()
        created_a += 1
        for seq, (text, action, cadence) in enumerate(items, start=1):
            db.add(CheckpointItem(checklist_id=cl.id, seq=seq, text=text,
                                  action=action, cadence=cadence, active=True))
            created_i += 1
    db.commit()
    return {"areas_created": created_a, "checkpoints_created": created_i,
            "areas_total": db.scalar(select(func.count()).select_from(Checklist)),
            "checkpoints_total": db.scalar(select(func.count()).select_from(CheckpointItem))}


def item_due_on(cadence: str, d: date, working: bool) -> bool:
    """Is an item of this cadence due on date d?"""
    if not working:
        return False
    if cadence == CADENCE_WEEKLY:
        return d.weekday() == 0  # Monday (Mon=0 .. Sun=6)
    return True  # daily


def checklist_view(db: Session, d: date):
    """Return (areas, working) for date d.

    areas = [{checklist, rows:[{item, status}], done, total}] for every active
    area that has at least one item due on d.
    """
    working = is_working_day(db, d)
    checklists = list(db.scalars(
        select(Checklist).where(Checklist.active.is_(True))
        .order_by(Checklist.sort_order, Checklist.id)))
    status_by_item = {s.item_id: s for s in db.scalars(
        select(CheckpointStatus).where(CheckpointStatus.on_date == d))}

    areas = []
    for cl in checklists:
        rows = []
        for it in cl.items:
            if not it.active or not item_due_on(it.cadence, d, working):
                continue
            rows.append({"item": it, "status": status_by_item.get(it.id)})
        if rows:
            done = sum(1 for r in rows if r["status"] and r["status"].done)
            areas.append({"checklist": cl, "rows": rows, "done": done, "total": len(rows)})
    return areas, working


def save_checklist(db: Session, *, checklist_id: int, d: date, actor: User,
                   done_ids: set[int], notes: dict[int, str], commit: bool = True) -> int:
    """Upsert the tick/note for every active, due item of one area on date d."""
    working = is_working_day(db, d)
    cl = db.get(Checklist, checklist_id)
    if cl is None:
        return 0
    existing = {s.item_id: s for s in db.scalars(
        select(CheckpointStatus).where(CheckpointStatus.on_date == d))}
    n = 0
    for it in cl.items:
        if not it.active or not item_due_on(it.cadence, d, working):
            continue
        st = existing.get(it.id)
        if st is None:
            st = CheckpointStatus(item_id=it.id, on_date=d)
            db.add(st)
        st.done = it.id in done_ids
        st.note = (notes.get(it.id) or "").strip() or None
        st.marked_by_id = actor.id
        st.marked_at = now_ist()
        n += 1
    if commit:
        db.commit()
    return n
