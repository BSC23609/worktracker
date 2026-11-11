"""Daily Checks — the trainees' shared checkpoint checklist.

Design:
  * One shared checklist per working day. Every trainee sees every area and
    anyone can tick any item (so leave is covered automatically).
  * Items have a cadence: daily (every working day) or weekly (Mondays).
  * Sundays and Holiday-Master dates are non-working — nothing is due.
  * A tick is one shared row per (item, date); the latest saver owns it.
"""
from __future__ import annotations

from datetime import date, timedelta, timezone
from html import escape as esc

from sqlalchemy import select
from sqlalchemy.orm import Session

from sqlalchemy import func

from . import config
from .db import now_ist, today_ist
from .digests import is_working_day
from .models import (CADENCE_DAILY, CADENCE_WEEKLY, Checklist, CheckpointItem,
                     CheckpointStatus, User)


def fmt_ist(dt, fmt: str = "%d-%b %H:%M") -> str:
    """Format a datetime in IST. Postgres hands timestamps back in UTC, so a
    stored IST moment must be converted before display. Naive values are
    treated as UTC."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(config.IST).strftime(fmt)


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


# ---- weekly report --------------------------------------------------------
def _week_bounds(on: date) -> tuple[date, date]:
    """Monday .. the given day (inclusive). `on` is normally the Saturday it runs."""
    start = on - timedelta(days=on.weekday())  # Monday of that week
    return start, on


def _collect_week(db: Session, start: date, end: date):
    """Walk the week and gather the figures the report needs."""
    day_rows = []          # (label, done, total, pending)
    area_tot: dict[str, list[int]] = {}
    issues = []            # (day_label, area, checkpoint, kind, note)  kind: 'notdone'|'note'
    week_done = week_total = working_days = 0

    d = start
    while d <= end:
        areas, working = checklist_view(db, d)
        if working and areas:
            working_days += 1
            day_done = sum(a["done"] for a in areas)
            day_total = sum(a["total"] for a in areas)
            week_done += day_done
            week_total += day_total
            day_rows.append((d.strftime("%a %d-%b"), day_done, day_total, day_total - day_done))
            for a in areas:
                name = a["checklist"].name
                agg = area_tot.setdefault(name, [0, 0])
                agg[0] += a["done"]
                agg[1] += a["total"]
                for r in a["rows"]:
                    st = r["status"]
                    if st is None or not st.done:
                        issues.append((d.strftime("%a %d-%b"), name, r["item"].text,
                                       "notdone", (st.note if st else None)))
                    elif st.note:
                        issues.append((d.strftime("%a %d-%b"), name, r["item"].text,
                                       "note", st.note))
        d += timedelta(days=1)

    area_rows = [(n, dn, tt) for n, (dn, tt) in sorted(area_tot.items())]
    return day_rows, area_rows, issues, week_done, week_total, working_days


def build_weekly_report(db: Session, on: date | None = None) -> tuple[str, str, str, dict]:
    """Build the weekly Daily Checks report for the week up to `on` (normally the
    Saturday it runs). Returns (subject, text_body, html_body, stats)."""
    on = on or today_ist()
    start, end = _week_bounds(on)
    day_rows, area_rows, issues, done, total, wdays = _collect_week(db, start, end)
    pct = round(done / total * 100) if total else 0
    week_lbl = f"{start.strftime('%d-%b')} to {end.strftime('%d-%b-%Y')}"
    subject = f"Daily Checks — Weekly Report ({start.strftime('%d-%b')} to {end.strftime('%d-%b')})"

    # ---- plain-text fallback ----
    L = ["Daily Checks — Weekly Report", f"Week: {week_lbl}", "",
         f"OVERALL: {done} of {total} checkpoints done across {wdays} working day(s) ({pct}%).",
         "", "By day:"]
    L += [f"  {lbl} : {dn}/{tt} done" + (f" ({p} pending)" if p else "")
          for (lbl, dn, tt, p) in day_rows] or ["  (nothing due this week)"]
    L += ["", "By area:"]
    L += [f"  {n:<10} {dn}/{tt}" for (n, dn, tt) in area_rows] or ["  —"]
    L += ["", "Pending / issues this week:"]
    L += [f"  {dl} — {ar} — {cp} : " + ("NOT DONE" if k == "notdone" else "")
          + (f"note: {nt}" if nt else ("" if k == "notdone" else ""))
          for (dl, ar, cp, k, nt) in issues] or ["  None — every checkpoint was completed."]
    L += ["", f"— {config.APP_NAME}, {config.BASE_URL}"]
    text = "\n".join(L)

    # ---- HTML (tables) ----
    pct_color = "#15803d" if pct >= 90 else ("#b45309" if pct >= 70 else "#b00020")
    th = "background:#0A2B66;color:#fff;text-align:left;padding:7px 10px;border:1px solid #0A2B66;font-size:13px"
    td = "padding:6px 10px;border:1px solid #e3e6ea;font-size:13px"
    tbl = "border-collapse:collapse;width:100%;margin:6px 0 20px"

    def _day_tr(i, r):
        lbl, dn, tt, p = r
        bg = "background:#f6f8fb" if i % 2 else ""
        pend = (f'<span style="color:#b00020;font-weight:bold">{p}</span>' if p
                else '<span style="color:#15803d">0</span>')
        return (f'<tr style="{bg}"><td style="{td}">{esc(lbl)}</td>'
                f'<td style="{td}">{dn}</td><td style="{td}">{tt}</td><td style="{td}">{pend}</td></tr>')

    def _area_tr(i, r):
        n, dn, tt = r
        bg = "background:#f6f8fb" if i % 2 else ""
        ok = dn == tt
        val = f'<span style="color:{"#15803d" if ok else "#b45309"};font-weight:bold">{dn}/{tt}</span>'
        return f'<tr style="{bg}"><td style="{td}">{esc(n)}</td><td style="{td}">{val}</td></tr>'

    def _issue_tr(i, r):
        dl, ar, cp, k, nt = r
        bg = "background:#f6f8fb" if i % 2 else ""
        if k == "notdone":
            status = '<span style="color:#b00020;font-weight:bold">Not done</span>'
            if nt:
                status += f'<br><span style="color:#555">{esc(nt)}</span>'
        else:
            status = f'<span style="color:#b45309">Note:</span> {esc(nt)}'
        return (f'<tr style="{bg}"><td style="{td};white-space:nowrap">{esc(dl)}</td>'
                f'<td style="{td}">{esc(ar)}</td><td style="{td}">{esc(cp)}</td>'
                f'<td style="{td}">{status}</td></tr>')

    day_html = "".join(_day_tr(i, r) for i, r in enumerate(day_rows)) or \
        f'<tr><td style="{td}" colspan="4">Nothing due this week</td></tr>'
    area_html = "".join(_area_tr(i, r) for i, r in enumerate(area_rows)) or \
        f'<tr><td style="{td}" colspan="2">—</td></tr>'
    if issues:
        issue_block = (
            f'<h3 style="color:#0A2B66;margin:18px 0 2px">Pending / issues ({len(issues)})</h3>'
            f'<table style="{tbl}"><thead><tr>'
            f'<th style="{th}">Day</th><th style="{th}">Area</th>'
            f'<th style="{th}">Checkpoint</th><th style="{th}">Status</th></tr></thead>'
            f'<tbody>{"".join(_issue_tr(i, r) for i, r in enumerate(issues))}</tbody></table>')
    else:
        issue_block = ('<h3 style="color:#0A2B66;margin:18px 0 2px">Pending / issues</h3>'
                       '<p style="color:#15803d;font-size:14px">None — every checkpoint was completed. 🎉</p>')

    html = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;color:#1E1D1D;max-width:720px;margin:0 auto;padding:4px">
  <h2 style="color:#0A2B66;margin:0 0 2px">Daily Checks — Weekly Report</h2>
  <p style="margin:0 0 12px;color:#666;font-size:13px">Week: {esc(week_lbl)}</p>
  <p style="font-size:15px;margin:0 0 6px">
    <strong>{done} / {total}</strong> checkpoints done across {wdays} working day(s)
    &nbsp;&middot;&nbsp; <strong style="color:{pct_color}">{pct}%</strong>
  </p>
  <h3 style="color:#0A2B66;margin:18px 0 2px">By day</h3>
  <table style="{tbl}"><thead><tr>
    <th style="{th}">Day</th><th style="{th}">Done</th><th style="{th}">Total</th><th style="{th}">Pending</th>
  </tr></thead><tbody>{day_html}</tbody></table>
  <h3 style="color:#0A2B66;margin:18px 0 2px">By area</h3>
  <table style="{tbl}"><thead><tr>
    <th style="{th}">Area</th><th style="{th}">Done / Total</th>
  </tr></thead><tbody>{area_html}</tbody></table>
  {issue_block}
  <p style="color:#999;font-size:12px;margin-top:18px">— {esc(config.APP_NAME)} &middot; <a href="{config.BASE_URL}" style="color:#0A2B66">{esc(config.BASE_URL)}</a></p>
</div>"""

    stats = {"week_start": start.isoformat(), "week_end": end.isoformat(),
             "done": done, "total": total, "working_days": wdays, "pending": total - done}
    return subject, text, html, stats


def send_weekly_report(db: Session, *, on: date | None = None, force: bool = False) -> dict:
    """Email the weekly Daily Checks report (HTML table) to CHECKS_REPORT_EMAIL.

    Idempotent per week: whichever trigger fires first that week sends it; later
    triggers that week are no-ops (so it is safe to fire from the daily cron and
    a dedicated Saturday job at once)."""
    from . import notifications
    from .digests import _already_sent
    on = on or today_ist()
    subject, text, html, stats = build_weekly_report(db, on)
    key = f"weekly_checks:{stats['week_start']}"
    if not force and _already_sent(db, key):
        return {"report": "weekly_checks", "skipped": "already sent this week", **stats}
    to = config.CHECKS_REPORT_EMAIL
    sent = notifications.send_email(db, to=to, subject=subject, body=text, html=html,
                                    kind="weekly_checks_report", dedupe_key=key)
    db.commit()
    return {"report": "weekly_checks", "recipient": to, "email_sent": sent, **stats}
