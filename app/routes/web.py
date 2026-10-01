from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config, notifications
from ..auth import (
    authenticate,
    current_user,
    generate_otp,
    hash_password,
    make_otp_cookie,
    make_reset_cookie,
    make_session_token,
    otp_matches,
    read_otp_cookie,
    read_reset_cookie,
    reissue_otp_cookie,
    require_superadmin,
    require_user,
    verify_password,
)
from ..db import get_db, today_ist
from ..models import (OPEN_STATUSES, ROLE_SUPERADMIN, ROLES, WEEKDAYS, Holiday, Task,
                      TaskAttachment, TaskSchedule, User)
from ..services import (
    TaskError,
    add_attachment,
    all_open_tasks,
    complete_task,
    create_schedule,
    create_task,
    extend_deadline,
    generate_due_recurring_tasks,
    open_tasks_for,
    reopen_task,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_name"] = config.APP_NAME


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        raise TaskError("Please provide a valid date.")


def _flash(url: str, msg: str, ok: bool = True) -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    prefix = "ok" if ok else "err"
    from urllib.parse import quote
    return RedirectResponse(f"{url}{sep}{prefix}={quote(msg)}", status_code=303)


# ---- auth -----------------------------------------------------------------
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: Optional[User] = Depends(current_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/auth/login")
def login(request: Request, identifier: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    user = authenticate(db, identifier, password)
    if not user:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid credentials."},
            status_code=401,
        )
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(config.SESSION_COOKIE, make_session_token(user.id),
                    max_age=config.SESSION_MAX_AGE, httponly=True,
                    samesite="lax", secure=config.COOKIE_SECURE, path="/")
    return resp


@router.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(config.SESSION_COOKIE)
    return resp


# ---- forgot password via OTP ----------------------------------------------
OTP_COOKIE = "wt_otp"
RESET_COOKIE = "wt_pwreset"


@router.get("/forgot", response_class=HTMLResponse)
def forgot_page(request: Request):
    return templates.TemplateResponse(request, "forgot.html", {
        "ok": request.query_params.get("ok"), "err": request.query_params.get("err")})


@router.post("/forgot")
def forgot(request: Request, identifier: str = Form(...), db: Session = Depends(get_db)):
    ident = (identifier or "").strip()
    user = db.scalar(select(User).where(func.lower(User.email) == ident.lower()))
    if not user:
        user = db.scalar(select(User).where(func.upper(User.emp_code) == ident.upper()))

    resp = RedirectResponse("/verify-otp", status_code=303)
    # Always go to the OTP screen (don't reveal whether the account exists).
    if user and user.active and (user.whatsapp or user.email):
        otp = generate_otp()
        notifications.send_otp(db, user, otp)
        resp.set_cookie(OTP_COOKIE, make_otp_cookie(user.id, otp, config.OTP_MAX_ATTEMPTS),
                        max_age=config.OTP_TTL, httponly=True, samesite="lax")
    return resp


@router.get("/verify-otp", response_class=HTMLResponse)
def verify_otp_page(request: Request):
    return templates.TemplateResponse(request, "verify_otp.html", {
        "err": request.query_params.get("err")})


@router.post("/verify-otp")
def verify_otp(request: Request, otp: str = Form(...), db: Session = Depends(get_db)):
    token = request.cookies.get(OTP_COOKIE)
    data = read_otp_cookie(token) if token else None
    if not data:
        return _flash("/forgot", "That code has expired. Please request a new one.", ok=False)
    if not otp_matches(data, otp):
        attempts_left = int(data.get("n", 1)) - 1
        if attempts_left <= 0:
            resp = _flash("/forgot", "Too many incorrect attempts. Please request a new code.", ok=False)
            resp.delete_cookie(OTP_COOKIE)
            return resp
        # re-issue the challenge with the same code fingerprint but one fewer attempt
        resp = _flash("/verify-otp", f"Incorrect code. {attempts_left} attempt(s) left.", ok=False)
        resp.set_cookie(OTP_COOKIE, reissue_otp_cookie(data, attempts_left),
                        max_age=config.OTP_TTL, httponly=True, samesite="lax")
        return resp
    # correct code -> authorise a password reset and move on
    user = db.get(User, data["uid"])
    if not user or not user.active:
        return _flash("/forgot", "That code has expired. Please request a new one.", ok=False)
    resp = RedirectResponse("/reset-password", status_code=303)
    resp.delete_cookie(OTP_COOKIE)
    resp.set_cookie(RESET_COOKIE, make_reset_cookie(user),
                    max_age=config.PWRESET_TTL, httponly=True, samesite="lax")
    return resp


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(RESET_COOKIE)
    user = read_reset_cookie(db, token) if token else None
    return templates.TemplateResponse(request, "set_password.html", {
        "valid": user is not None, "name": user.name if user else None,
        "err": request.query_params.get("err")})


@router.post("/reset-password")
def reset_password_submit(request: Request, new: str = Form(...), confirm: str = Form(...),
                          db: Session = Depends(get_db)):
    token = request.cookies.get(RESET_COOKIE)
    user = read_reset_cookie(db, token) if token else None
    if not user:
        return _flash("/forgot", "Your session expired. Please start again.", ok=False)
    if len(new) < 6:
        return _flash("/reset-password", "Password must be at least 6 characters.", ok=False)
    if new != confirm:
        return _flash("/reset-password", "Passwords do not match.", ok=False)
    if new == config.DEFAULT_PASSWORD:
        return _flash("/reset-password", "Please choose a different password.", ok=False)
    user.password_hash = hash_password(new)
    user.must_reset = False
    db.commit()
    resp = _flash("/login", "Password updated. You can sign in now.")
    resp.delete_cookie(RESET_COOKIE)
    return resp


@router.get("/change-password", response_class=HTMLResponse)
def change_password_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse(request, "change_password.html", {"me": user})


@router.post("/change-password")
def change_password(request: Request, current: str = Form(...), new: str = Form(...),
                    confirm: str = Form(...), user: User = Depends(require_user),
                    db: Session = Depends(get_db)):
    if not verify_password(current, user.password_hash):
        return _flash("/change-password", "Current password is incorrect.", ok=False)
    if len(new) < 6:
        return _flash("/change-password", "New password must be at least 6 characters.", ok=False)
    if new != confirm:
        return _flash("/change-password", "New passwords do not match.", ok=False)
    if new == config.DEFAULT_PASSWORD:
        return _flash("/change-password", "Please choose a password other than the default.", ok=False)
    user.password_hash = hash_password(new)
    user.must_reset = False
    db.commit()
    return _flash("/", "Password updated.")


# ---- dashboard ------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db),
              user: Optional[User] = Depends(current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if user.must_reset:
        return RedirectResponse("/change-password", status_code=303)

    today = today_ist()
    if user.is_superadmin:
        tasks = all_open_tasks(db)
    else:
        tasks = open_tasks_for(db, user.id)

    overdue = [t for t in tasks if t.current_deadline < today]
    due_today = [t for t in tasks if t.current_deadline == today]

    # Consolidated view for superadmins: group open tasks by assignee.
    groups = []
    assignable = []
    if user.is_superadmin:
        by_person: dict[int, dict] = {}
        for t in tasks:
            g = by_person.setdefault(t.assigned_to_id,
                                     {"person": t.assignee, "tasks": [], "overdue": 0})
            g["tasks"].append(t)
            if t.current_deadline < today:
                g["overdue"] += 1
        groups = sorted(by_person.values(),
                        key=lambda g: (-g["overdue"], -len(g["tasks"]), g["person"].name))
        assignable = list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)))

    # Active recurring schedules the person can see (own/assigned, or all for superadmin).
    sched_stmt = select(TaskSchedule).where(TaskSchedule.active.is_(True))
    if not user.is_superadmin:
        sched_stmt = sched_stmt.where(
            (TaskSchedule.assigned_to_id == user.id) | (TaskSchedule.created_by_id == user.id))
    schedules = list(db.scalars(sched_stmt.order_by(TaskSchedule.created_at.desc())))

    return templates.TemplateResponse(request, "dashboard.html", {
        "me": user, "tasks": tasks, "today": today,
        "overdue": overdue, "due_today": due_today, "groups": groups,
        "people": groups, "assignable": assignable, "schedules": schedules,
        "weekdays": list(enumerate(WEEKDAYS)),
        "ok": request.query_params.get("ok"), "err": request.query_params.get("err"),
    })


# ---- task actions ---------------------------------------------------------
@router.post("/tasks/create")
def create(request: Request, title: str = Form(...), deadline: str = Form(""),
           description: str = Form(""), priority: str = Form("medium"),
           assigned_to_id: Optional[int] = Form(None),
           attachments: list[UploadFile] = File(default=[]),
           repetitive: Optional[str] = Form(None),
           frequency: str = Form("daily"), start_date: str = Form(""), end_date: str = Form(""),
           day_of_week: str = Form(""), day_of_month: str = Form(""),
           deadline_offset: str = Form("0"),
           user: User = Depends(require_user), db: Session = Depends(get_db)):
    def _int_or_none(s):
        s = (s or "").strip()
        return int(s) if s.isdigit() else None
    try:
        if user.is_superadmin and assigned_to_id:
            assignee = db.get(User, int(assigned_to_id))
            if not assignee:
                raise TaskError("Selected user not found.")
        else:
            assignee = user
        if not assignee.active:
            raise TaskError("Cannot assign to an inactive user.")

        if repetitive == "on":
            sch = create_schedule(
                db, created_by=user, assigned_to=assignee, title=title, frequency=frequency,
                start_date=_parse_date(start_date), end_date=_parse_date(end_date) if end_date else None,
                day_of_week=_int_or_none(day_of_week), day_of_month=_int_or_none(day_of_month),
                deadline_offset_days=_int_or_none(deadline_offset) or 0,
                description=description, priority=priority)
            n = generate_due_recurring_tasks(db)  # create any instances already due
            who = "yourself" if sch.assigned_to_id == user.id else assignee.name
            extra = f" {n} due instance(s) added now." if n else ""
            return _flash("/", f"Recurring task set up for {who} ({sch.frequency_label}).{extra}")

        # one-off task
        task = create_task(db, created_by=user, assigned_to=assignee, title=title,
                           deadline=_parse_date(deadline), description=description, priority=priority)
        n_files = _save_uploads(db, task, user, attachments)
    except TaskError as e:
        return _flash("/", str(e), ok=False)
    notifications.notify_new_task(db, task)
    who = "yourself" if task.is_self_raised else task.assignee.name
    extra = f" {n_files} file(s) attached." if n_files else ""
    return _flash("/", f"Task raised for {who}. Reminder sent.{extra}")


@router.post("/schedules/{schedule_id}/stop")
def stop_schedule(schedule_id: int, user: User = Depends(require_user),
                  db: Session = Depends(get_db)):
    sch = db.get(TaskSchedule, schedule_id)
    if not sch:
        raise HTTPException(404, "Schedule not found")
    if not (user.is_superadmin or sch.created_by_id == user.id or sch.assigned_to_id == user.id):
        raise HTTPException(403, "Not your schedule")
    sch.active = False
    db.commit()
    return _flash("/", "Recurring task stopped. Already-created tasks are kept.")


def _save_uploads(db: Session, task: Task, user: User, uploads: list[UploadFile]) -> int:
    """Read and store any non-empty uploaded files. Returns count saved."""
    saved = 0
    for f in uploads or []:
        if not f or not f.filename:
            continue
        data = f.file.read()
        if not data:
            continue
        add_attachment(db, task=task, actor=user, filename=f.filename,
                       content_type=f.content_type or "application/octet-stream",
                       data=data, commit=False)
        saved += 1
    if saved:
        db.commit()
    return saved


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(task_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_user)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if not user.is_superadmin and task.assigned_to_id != user.id and task.created_by_id != user.id:
        raise HTTPException(403, "Not your task")
    attachments = list(db.scalars(
        select(TaskAttachment).where(TaskAttachment.task_id == task.id)
        .order_by(TaskAttachment.created_at)))
    return templates.TemplateResponse(request, "task_detail.html", {
        "me": user, "task": task, "today": today_ist(), "attachments": attachments,
        "can_act": user.is_superadmin or task.assigned_to_id == user.id,
        "ok": request.query_params.get("ok"), "err": request.query_params.get("err"),
    })


def _task_or_404(db, task_id):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


def _can_see_task(user, task) -> bool:
    return user.is_superadmin or task.assigned_to_id == user.id or task.created_by_id == user.id


@router.post("/tasks/{task_id}/attachments")
def add_task_attachment(task_id: int, attachments: list[UploadFile] = File(default=[]),
                        user: User = Depends(require_user), db: Session = Depends(get_db)):
    task = _task_or_404(db, task_id)
    if not _can_see_task(user, task):
        raise HTTPException(403, "Not your task")
    try:
        n = _save_uploads(db, task, user, attachments)
    except TaskError as e:
        return _flash(f"/tasks/{task_id}", str(e), ok=False)
    if not n:
        return _flash(f"/tasks/{task_id}", "No file selected.", ok=False)
    return _flash(f"/tasks/{task_id}", f"{n} file(s) attached.")


@router.get("/tasks/{task_id}/attachments/{att_id}")
def download_attachment(task_id: int, att_id: int, user: User = Depends(require_user),
                        db: Session = Depends(get_db)):
    task = _task_or_404(db, task_id)
    if not _can_see_task(user, task):
        raise HTTPException(403, "Not your task")
    att = db.get(TaskAttachment, att_id)
    if not att or att.task_id != task_id:
        raise HTTPException(404, "Attachment not found")
    from urllib.parse import quote
    disp = f'attachment; filename*=UTF-8\'\'{quote(att.filename)}'
    return StreamingResponse(io.BytesIO(att.data), media_type=att.content_type,
                             headers={"Content-Disposition": disp})


@router.post("/tasks/{task_id}/attachments/{att_id}/delete")
def delete_attachment(task_id: int, att_id: int, user: User = Depends(require_user),
                      db: Session = Depends(get_db)):
    task = _task_or_404(db, task_id)
    att = db.get(TaskAttachment, att_id)
    if not att or att.task_id != task_id:
        raise HTTPException(404, "Attachment not found")
    # uploader, task creator, assignee, or any superadmin may remove
    if not (user.is_superadmin or att.uploaded_by_id == user.id
            or task.assigned_to_id == user.id or task.created_by_id == user.id):
        raise HTTPException(403, "Not allowed")
    db.delete(att)
    db.commit()
    return _flash(f"/tasks/{task_id}", "Attachment removed.")


@router.post("/tasks/{task_id}/extend")
def extend(task_id: int, new_deadline: str = Form(...), reason: str = Form(...),
           user: User = Depends(require_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    try:
        extend_deadline(db, task=task, actor=user, new_deadline=_parse_date(new_deadline),
                        reason=reason)
    except TaskError as e:
        return _flash(f"/tasks/{task_id}", str(e), ok=False)
    return _flash(f"/tasks/{task_id}", "Deadline revised. The earlier deadline is kept on record.")


@router.post("/tasks/{task_id}/complete")
def complete(task_id: int, note: str = Form(""), user: User = Depends(require_user),
             db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    try:
        complete_task(db, task=task, actor=user, note=note)
    except TaskError as e:
        return _flash(f"/tasks/{task_id}", str(e), ok=False)
    return _flash(f"/tasks/{task_id}", "Marked as completed.")


@router.post("/tasks/{task_id}/reopen")
def reopen(task_id: int, user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    try:
        reopen_task(db, task=task, actor=user)
    except TaskError as e:
        return _flash(f"/tasks/{task_id}", str(e), ok=False)
    return _flash(f"/tasks/{task_id}", "Task reopened.")


@router.post("/master/send-credentials")
def send_credentials_all(admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    if not config.NOTIFY_EMAIL_ENABLED:
        return _flash("/master", "Email isn't configured yet (set the SMTP_* variables), "
                                 "so no credentials were sent.", ok=False)
    users = list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)))
    with_email = [u for u in users if u.email]
    no_email = [u for u in users if not u.email]
    sent = failed = 0
    for u in with_email:
        subject, body = notifications.render_credentials(u)
        if notifications.send_email(db, to=u.email, subject=subject, body=body, kind="credentials"):
            sent += 1
        else:
            failed += 1
    db.commit()
    msg = f"Login details emailed to {sent} user(s)."
    if failed:
        msg += f" {failed} failed to send."
    if no_email:
        msg += f" {len(no_email)} have no email — share their code + password directly."
    return _flash("/master", msg, ok=(failed == 0))


@router.post("/master/users/{user_id}/send-credentials")
def send_credentials_one(user_id: int, admin: User = Depends(require_superadmin),
                         db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        return _flash("/master", "User not found.", ok=False)
    if not u.email:
        return _flash("/master", f"{u.name} has no email — share their code + password directly.", ok=False)
    if not config.NOTIFY_EMAIL_ENABLED:
        return _flash("/master", "Email isn't configured yet (set the SMTP_* variables).", ok=False)
    subject, body = notifications.render_credentials(u)
    ok = notifications.send_email(db, to=u.email, subject=subject, body=body, kind="credentials")
    db.commit()
    return _flash("/master", f"Login details emailed to {u.name}." if ok
                  else f"Could not send to {u.name} (check SMTP settings).", ok=ok)


@router.post("/master/send-welcome")
def send_welcome_all(admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    if not config.NOTIFY_WHATSAPP_ENABLED:
        return _flash("/master", "WhatsApp (WATI) isn't configured, so no welcome messages "
                                 "were sent.", ok=False)
    users = list(db.scalars(select(User).where(User.active.is_(True))))
    with_wa = [u for u in users if u.whatsapp]
    sent = 0
    for u in with_wa:
        if notifications.send_welcome(db, u):
            sent += 1
    no_wa = len(users) - len(with_wa)
    msg = f"Welcome message sent to {sent} of {len(with_wa)} user(s)."
    if no_wa:
        msg += f" {no_wa} have no WhatsApp number."
    return _flash("/master", msg, ok=(sent == len(with_wa)))


@router.post("/master/users/{user_id}/send-welcome")
def send_welcome_one(user_id: int, admin: User = Depends(require_superadmin),
                     db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        return _flash("/master", "User not found.", ok=False)
    if not u.whatsapp:
        return _flash("/master", f"{u.name} has no WhatsApp number.", ok=False)
    if not config.NOTIFY_WHATSAPP_ENABLED:
        return _flash("/master", "WhatsApp (WATI) isn't configured.", ok=False)
    ok = notifications.send_welcome(db, u)
    return _flash("/master", f"Welcome message sent to {u.name}." if ok
                  else f"Couldn't send to {u.name} (check WATI settings).", ok=ok)


# ---- master tab (superadmin) ----------------------------------------------
@router.get("/master", response_class=HTMLResponse)
def master(request: Request, db: Session = Depends(get_db),
           user: User = Depends(require_superadmin)):
    users = list(db.scalars(select(User).order_by(User.active.desc(), User.name)))
    return templates.TemplateResponse(request, "master.html", {
        "me": user, "users": users, "roles": ROLES,
        "default_password": config.DEFAULT_PASSWORD,
        "ok": request.query_params.get("ok"), "err": request.query_params.get("err"),
    })


@router.post("/master/users/create")
def create_user(name: str = Form(...), email: str = Form(""), emp_code: str = Form(""),
                whatsapp: str = Form(""), role: str = Form("user"),
                admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    email = email.strip().lower()
    emp_code = emp_code.strip().upper()
    if not name.strip():
        return _flash("/master", "Name is required.", ok=False)
    if not email and not emp_code:
        return _flash("/master", "Give an email or an employee code so they can log in.", ok=False)
    if role not in ROLES:
        role = "user"
    if email and db.scalar(select(User).where(func.lower(User.email) == email)):
        return _flash("/master", "A user with that email already exists.", ok=False)
    if emp_code and db.scalar(select(User).where(func.upper(User.emp_code) == emp_code)):
        return _flash("/master", "A user with that employee code already exists.", ok=False)
    db.add(User(name=name.strip(), email=email or None, emp_code=emp_code or None,
                whatsapp=notifications.normalise_whatsapp(whatsapp),
                role=role, password_hash=hash_password(config.DEFAULT_PASSWORD),
                must_reset=True, active=True))
    db.commit()
    who = email or emp_code
    return _flash("/master", f"User added ({who}). Default password is '{config.DEFAULT_PASSWORD}'.")


@router.post("/master/users/{user_id}/update")
def update_user(user_id: int, name: str = Form(...), emp_code: str = Form(""),
                whatsapp: str = Form(""), role: str = Form("user"), active: str = Form("off"),
                admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        return _flash("/master", "User not found.", ok=False)
    # Don't let the last active superadmin lose the role / be deactivated.
    is_demote = (u.role == ROLE_SUPERADMIN and role != ROLE_SUPERADMIN)
    is_deactivate = (u.active and active != "on")
    if (is_demote or is_deactivate) and u.role == ROLE_SUPERADMIN:
        others = db.scalar(select(User).where(User.role == ROLE_SUPERADMIN,
                                              User.active.is_(True), User.id != u.id))
        if not others:
            return _flash("/master", "At least one active superadmin must remain.", ok=False)
    emp_code = emp_code.strip().upper()
    if emp_code:
        clash = db.scalar(select(User).where(func.upper(User.emp_code) == emp_code, User.id != u.id))
        if clash:
            return _flash("/master", "That employee code is already in use.", ok=False)
    if not emp_code and not u.email:
        return _flash("/master", "This user has no email, so an employee code is required.", ok=False)
    u.name = name.strip() or u.name
    u.emp_code = emp_code or None
    u.whatsapp = notifications.normalise_whatsapp(whatsapp)
    u.role = role if role in ROLES else u.role
    u.active = (active == "on")
    db.commit()
    return _flash("/master", f"{u.name} updated.")


@router.post("/master/users/{user_id}/reset-password")
def reset_password(user_id: int, admin: User = Depends(require_superadmin),
                   db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        return _flash("/master", "User not found.", ok=False)
    u.password_hash = hash_password(config.DEFAULT_PASSWORD)
    u.must_reset = True
    db.commit()
    return _flash("/master", f"{u.name}'s password reset to '{config.DEFAULT_PASSWORD}'.")


@router.post("/master/users/{user_id}/delete")
def delete_user(user_id: int, admin: User = Depends(require_superadmin),
                db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        return _flash("/master", "User not found.", ok=False)
    if u.id == admin.id:
        return _flash("/master", "You can't delete your own account.", ok=False)
    if u.role == ROLE_SUPERADMIN:
        others = db.scalar(select(User).where(User.role == ROLE_SUPERADMIN,
                                              User.active.is_(True), User.id != u.id))
        if not others:
            return _flash("/master", "At least one active superadmin must remain.", ok=False)
    # A user tied to tasks can't be hard-deleted (it would orphan history).
    linked = db.scalar(select(func.count()).select_from(Task)
                       .where((Task.assigned_to_id == u.id) | (Task.created_by_id == u.id)))
    if linked:
        return _flash("/master",
                      f"{u.name} has {linked} task(s) on record, so can't be deleted. "
                      f"Untick 'Active' to disable the account instead.", ok=False)
    name = u.name
    db.delete(u)
    db.commit()
    return _flash("/master", f"{name} deleted.")


# ---- holiday master (superadmin) ------------------------------------------
@router.get("/holidays", response_class=HTMLResponse)
def holidays_page(request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require_superadmin)):
    today = today_ist()
    items = list(db.scalars(select(Holiday).order_by(Holiday.day.desc())))
    upcoming = [h for h in items if h.day >= today]
    past = [h for h in items if h.day < today]
    return templates.TemplateResponse(request, "holidays.html", {
        "me": user, "today": today, "upcoming": upcoming, "past": past,
        "ok": request.query_params.get("ok"), "err": request.query_params.get("err"),
    })


@router.post("/holidays/add")
def holiday_add(day: str = Form(...), label: str = Form(""),
                admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    try:
        d = _parse_date(day)
    except TaskError as e:
        return _flash("/holidays", str(e), ok=False)
    if db.scalar(select(Holiday).where(Holiday.day == d)):
        return _flash("/holidays", "That date is already marked as a holiday.", ok=False)
    db.add(Holiday(day=d, label=label.strip() or None, created_by_id=admin.id))
    db.commit()
    return _flash("/holidays", f"Holiday added for {d.strftime('%d-%b-%Y')}.")


@router.post("/holidays/{holiday_id}/delete")
def holiday_delete(holiday_id: int, admin: User = Depends(require_superadmin),
                   db: Session = Depends(get_db)):
    h = db.get(Holiday, holiday_id)
    if h:
        db.delete(h)
        db.commit()
    return _flash("/holidays", "Holiday removed.")
