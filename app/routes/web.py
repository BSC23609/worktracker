from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, notifications
from ..auth import (
    authenticate,
    current_user,
    hash_password,
    make_session_token,
    require_superadmin,
    require_user,
    verify_password,
)
from ..db import get_db, today_ist
from ..models import OPEN_STATUSES, ROLE_SUPERADMIN, ROLES, Task, User
from ..services import (
    TaskError,
    all_open_tasks,
    complete_task,
    create_task,
    extend_deadline,
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
def login(request: Request, email: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    user = authenticate(db, email, password)
    if not user:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid email or password."},
            status_code=401,
        )
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(config.SESSION_COOKIE, make_session_token(user.id),
                    max_age=config.SESSION_MAX_AGE, httponly=True, samesite="lax")
    return resp


@router.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(config.SESSION_COOKIE)
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
    people = sorted({t.assignee for t in tasks}, key=lambda u: u.name) if user.is_superadmin else []
    assignable = []
    if user.is_superadmin:
        assignable = list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)))

    return templates.TemplateResponse(request, "dashboard.html", {
        "me": user, "tasks": tasks, "today": today,
        "overdue": overdue, "due_today": due_today, "people": people,
        "assignable": assignable, "ok": request.query_params.get("ok"),
        "err": request.query_params.get("err"),
    })


# ---- task actions ---------------------------------------------------------
@router.post("/tasks/create")
def create(request: Request, title: str = Form(...), deadline: str = Form(...),
           description: str = Form(""), priority: str = Form("medium"),
           assigned_to_id: Optional[int] = Form(None),
           user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        if user.is_superadmin and assigned_to_id:
            assignee = db.get(User, int(assigned_to_id))
            if not assignee:
                raise TaskError("Selected user not found.")
        else:
            assignee = user  # general user -> self; superadmin with no selection -> self
        task = create_task(db, created_by=user, assigned_to=assignee, title=title,
                           deadline=_parse_date(deadline), description=description,
                           priority=priority)
    except TaskError as e:
        return _flash("/", str(e), ok=False)
    notifications.notify_new_task(db, task)
    who = "yourself" if task.is_self_raised else task.assignee.name
    return _flash("/", f"Task raised for {who}. Reminder sent.")


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(task_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_user)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if not user.is_superadmin and task.assigned_to_id != user.id and task.created_by_id != user.id:
        raise HTTPException(403, "Not your task")
    return templates.TemplateResponse(request, "task_detail.html", {
        "me": user, "task": task, "today": today_ist(),
        "can_act": user.is_superadmin or task.assigned_to_id == user.id,
        "ok": request.query_params.get("ok"), "err": request.query_params.get("err"),
    })


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
def create_user(name: str = Form(...), email: str = Form(...), whatsapp: str = Form(""),
                role: str = Form("user"), admin: User = Depends(require_superadmin),
                db: Session = Depends(get_db)):
    email = email.strip().lower()
    if not name.strip() or not email:
        return _flash("/master", "Name and email are required.", ok=False)
    if role not in ROLES:
        role = "user"
    if db.scalar(select(User).where(User.email == email)):
        return _flash("/master", "A user with that email already exists.", ok=False)
    db.add(User(name=name.strip(), email=email,
                whatsapp=notifications.normalise_whatsapp(whatsapp),
                role=role, password_hash=hash_password(config.DEFAULT_PASSWORD),
                must_reset=True, active=True))
    db.commit()
    return _flash("/master", f"User added. Default password is '{config.DEFAULT_PASSWORD}'.")


@router.post("/master/users/{user_id}/update")
def update_user(user_id: int, name: str = Form(...), whatsapp: str = Form(""),
                role: str = Form("user"), active: str = Form("on"),
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
    u.name = name.strip() or u.name
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
