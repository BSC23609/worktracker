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

from .db import now_ist
from .digests import is_working_day
from .models import CADENCE_WEEKLY, Checklist, CheckpointStatus, User


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
