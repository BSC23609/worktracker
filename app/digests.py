from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, notifications
from .db import today_ist
from .models import NotificationLog, ROLE_SUPERADMIN, User
from .services import all_open_tasks, open_tasks_for


def _already_sent(db: Session, dedupe_key: str) -> bool:
    row = db.scalar(
        select(NotificationLog.id).where(
            NotificationLog.dedupe_key == dedupe_key,
            NotificationLog.status == "sent",
        )
    )
    return row is not None


def run_daily_digests(db: Session, *, on: date | None = None, force: bool = False) -> dict:
    """Send each active user their pending list and each superadmin the
    consolidated list. Idempotent per calendar day via dedupe_key."""
    today = on or today_ist()
    day = today.isoformat()
    summary = {"date": day, "employee_sent": 0, "employee_skipped": 0,
               "admin_sent": 0, "admin_skipped": 0}

    users = list(db.scalars(select(User).where(User.active.is_(True))))

    # 1) per-employee pending list
    for user in users:
        key = f"emp:{user.id}:{day}"
        if not force and _already_sent(db, key):
            summary["employee_skipped"] += 1
            continue
        tasks = open_tasks_for(db, user.id)
        subject, body, params = notifications.render_employee_digest(user, tasks, today)
        sent_e = notifications.send_email(db, to=user.email, subject=subject, body=body,
                                          kind="employee_digest", dedupe_key=key)
        sent_w = notifications.send_whatsapp(db, to=user.whatsapp,
                                             template=config.WATI_TEMPLATE_EMP_DIGEST,
                                             params=params, kind="employee_digest",
                                             dedupe_key=key)
        summary["employee_sent" if (sent_e or sent_w) else "employee_skipped"] += 1

    # 2) consolidated list to every superadmin
    open_all = all_open_tasks(db)
    for admin in [u for u in users if u.role == ROLE_SUPERADMIN]:
        key = f"adm:{admin.id}:{day}"
        if not force and _already_sent(db, key):
            summary["admin_skipped"] += 1
            continue
        subject, body, params = notifications.render_admin_digest(admin, open_all, today)
        sent_e = notifications.send_email(db, to=admin.email, subject=subject, body=body,
                                          kind="admin_digest", dedupe_key=key)
        sent_w = notifications.send_whatsapp(db, to=admin.whatsapp,
                                             template=config.WATI_TEMPLATE_ADMIN_DIGEST,
                                             params=params, kind="admin_digest",
                                             dedupe_key=key)
        summary["admin_sent" if (sent_e or sent_w) else "admin_skipped"] += 1

    db.commit()
    return summary
