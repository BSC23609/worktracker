"""Email (SMTP) + WhatsApp (WATI) delivery.

Design rules (mirroring the Metfraa Portal):
  * Every send is FAIL-SOFT -- a provider outage returns False, never raises,
    so the task action that triggered it still succeeds.
  * Every attempt is written to NotificationLog (sent / failed / skipped).
  * Message *rendering* is pure and separate from *sending* so tests can assert
    content with no network.
"""
from __future__ import annotations

import smtplib
import ssl
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests
from sqlalchemy.orm import Session

from . import config
from .models import NotificationLog, Task, User

IST_FMT = "%d-%b-%Y"


def _d(d: date) -> str:
    return d.strftime(IST_FMT)


def normalise_whatsapp(raw: Optional[str]) -> Optional[str]:
    """Return digits only with a country code. '9500680093' -> '919500680093'."""
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None
    if len(digits) == 10:
        digits = config.WATI_DEFAULT_CC + digits
    return digits


# ---------------------------------------------------------------------------
# Message rendering (pure)
# ---------------------------------------------------------------------------
def render_new_task(task: Task) -> tuple[str, str, list[str]]:
    """Return (email_subject, email_body, wati_params) for a newly raised task."""
    subject = f"[Task] {task.title} — due {_d(task.current_deadline)}"
    body = (
        f"Hi {task.assignee.name},\n\n"
        f"A task has been assigned to you.\n\n"
        f"Task      : {task.title}\n"
        f"Details   : {task.description or '-'}\n"
        f"Priority  : {task.priority.title()}\n"
        f"Deadline  : {_d(task.current_deadline)}\n"
        f"Raised by : {task.creator.name}\n\n"
        f"Open it here: {config.BASE_URL}/tasks/{task.id}\n\n"
        f"— {config.SMTP_FROM_NAME}"
    )
    # WATI template params, in order: {{1}}=name {{2}}=title {{3}}=deadline {{4}}=raised_by
    params = [task.assignee.name, task.title, _d(task.current_deadline), task.creator.name]
    return subject, body, params


def render_employee_digest(user: User, tasks: list[Task], today: date) -> tuple[str, str, list[str]]:
    overdue = [t for t in tasks if t.current_deadline < today]
    subject = f"Your pending tasks ({len(tasks)}) — {_d(today)}"
    lines = [f"Hi {user.name},", "", f"You have {len(tasks)} pending task(s) as of {_d(today)}:", ""]
    for t in tasks:
        flag = "  ⚠ OVERDUE" if t.current_deadline < today else ""
        lines.append(f"• {t.title} — due {_d(t.current_deadline)}{flag}")
    if not tasks:
        lines.append("Nothing pending. 🎉")
    lines += ["", f"View all: {config.BASE_URL}/", "", f"— {config.SMTP_FROM_NAME}"]
    body = "\n".join(lines)
    params = [user.name, str(len(tasks)), str(len(overdue))]
    return subject, body, params


def render_admin_digest(admin: User, tasks: list[Task], today: date) -> tuple[str, str, list[str]]:
    overdue = [t for t in tasks if t.current_deadline < today]
    by_person: dict[str, list[Task]] = {}
    for t in tasks:
        by_person.setdefault(t.assignee.name, []).append(t)
    subject = f"Team task summary — {len(tasks)} open, {len(overdue)} overdue — {_d(today)}"
    lines = [
        f"Hi {admin.name},", "",
        f"Consolidated status as of {_d(today)}:",
        f"  Open tasks   : {len(tasks)}",
        f"  Overdue      : {len(overdue)}",
        f"  People        : {len(by_person)}",
        "",
    ]
    for person, items in sorted(by_person.items()):
        od = sum(1 for t in items if t.current_deadline < today)
        lines.append(f"{person} — {len(items)} open ({od} overdue):")
        for t in items:
            flag = "  ⚠" if t.current_deadline < today else ""
            lines.append(f"    • {t.title} — due {_d(t.current_deadline)}{flag}")
        lines.append("")
    lines += [f"Full board: {config.BASE_URL}/", "", f"— {config.SMTP_FROM_NAME}"]
    body = "\n".join(lines)
    params = [admin.name, str(len(tasks)), str(len(overdue))]
    return subject, body, params


# ---------------------------------------------------------------------------
# Senders (impure) — fail-soft, always logged
# ---------------------------------------------------------------------------
def _log(db: Session, *, task_id, kind, channel, recipient, status, detail=None, dedupe_key=None):
    db.add(NotificationLog(
        task_id=task_id, kind=kind, channel=channel, recipient=recipient or "-",
        status=status, detail=(detail or "")[:1000], dedupe_key=dedupe_key,
    ))


def send_email(db: Session, *, to: str, subject: str, body: str, kind: str,
               task_id=None, dedupe_key=None) -> bool:
    if not config.NOTIFY_EMAIL_ENABLED:
        _log(db, task_id=task_id, kind=kind, channel="email", recipient=to,
             status="skipped", detail="SMTP not configured", dedupe_key=dedupe_key)
        return False
    if not to:
        _log(db, task_id=task_id, kind=kind, channel="email", recipient="-",
             status="skipped", detail="no recipient", dedupe_key=dedupe_key)
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = f"{config.SMTP_FROM_NAME} <{config.SMTP_FROM}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        ctx = ssl.create_default_context()
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.starttls(context=ctx)
            if config.SMTP_USER:
                s.login(config.SMTP_USER, config.SMTP_PASS)
            s.sendmail(config.SMTP_FROM, [to], msg.as_string())
        _log(db, task_id=task_id, kind=kind, channel="email", recipient=to,
             status="sent", dedupe_key=dedupe_key)
        return True
    except Exception as exc:  # noqa: BLE001 - fail-soft by design
        _log(db, task_id=task_id, kind=kind, channel="email", recipient=to,
             status="failed", detail=repr(exc), dedupe_key=dedupe_key)
        return False


def send_whatsapp(db: Session, *, to: Optional[str], template: str, params: list[str],
                  kind: str, task_id=None, dedupe_key=None) -> bool:
    number = normalise_whatsapp(to)
    if not config.NOTIFY_WHATSAPP_ENABLED:
        _log(db, task_id=task_id, kind=kind, channel="whatsapp", recipient=number or "-",
             status="skipped", detail="WATI not configured", dedupe_key=dedupe_key)
        return False
    if not number:
        _log(db, task_id=task_id, kind=kind, channel="whatsapp", recipient="-",
             status="skipped", detail="no whatsapp number", dedupe_key=dedupe_key)
        return False
    try:
        url = f"{config.WATI_BASE_URL}/api/v1/sendTemplateMessage"
        payload = {
            "template_name": template,
            "broadcast_name": config.WATI_BROADCAST_NAME,
            "parameters": [{"name": str(i + 1), "value": v} for i, v in enumerate(params)],
        }
        resp = requests.post(
            url,
            params={"whatsappNumber": number},
            json=payload,
            headers={"Authorization": f"Bearer {config.WATI_TOKEN}",
                     "Content-Type": "application/json"},
            timeout=20,
        )
        ok = resp.status_code < 400 and (resp.json().get("result") is not False
                                         if resp.headers.get("content-type", "").startswith("application/json") else True)
        _log(db, task_id=task_id, kind=kind, channel="whatsapp", recipient=number,
             status="sent" if ok else "failed",
             detail=None if ok else f"HTTP {resp.status_code}: {resp.text[:300]}",
             dedupe_key=dedupe_key)
        return ok
    except Exception as exc:  # noqa: BLE001
        _log(db, task_id=task_id, kind=kind, channel="whatsapp", recipient=number,
             status="failed", detail=repr(exc), dedupe_key=dedupe_key)
        return False


def render_credentials(user: User) -> tuple[str, str]:
    """Login-details email for a user (sent from the Master tab)."""
    ids = []
    if user.email:
        ids.append(f"  Email      : {user.email}")
    if user.emp_code:
        ids.append(f"  Emp code   : {user.emp_code}")
    id_block = "\n".join(ids) or "  (ask your admin)"
    if user.must_reset:
        pw = (f"  Temporary password: {config.DEFAULT_PASSWORD}\n"
              f"  You'll be asked to set your own password on first sign-in.")
    else:
        pw = ("  Use the password you already set. If you've forgotten it, "
              "ask an admin to reset it.")
    subject = "Your Work Tracker login details"
    body = (
        f"Hi {user.name},\n\n"
        f"You have access to the Bharat Steel Group Work Tracker.\n\n"
        f"Open it here:\n  {config.BASE_URL}\n\n"
        f"Sign in with your email or employee code:\n{id_block}\n\n"
        f"{pw}\n\n"
        f"— {config.SMTP_FROM_NAME}"
    )
    return subject, body


def notify_new_task(db: Session, task: Task) -> None:
    subject, body, params = render_new_task(task)
    send_email(db, to=task.assignee.email, subject=subject, body=body,
               kind="new_task", task_id=task.id)
    send_whatsapp(db, to=task.assignee.whatsapp, template=config.WATI_TEMPLATE_NEW_TASK,
                  params=params, kind="new_task", task_id=task.id)
    db.commit()
