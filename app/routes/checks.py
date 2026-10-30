from __future__ import annotations

from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..auth import require_checks_access, require_superadmin
from ..checks import checklist_view, save_checklist
from ..db import get_db, today_ist
from ..models import CADENCES, Checklist, CheckpointItem, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_name"] = config.APP_NAME


def _flash(url: str, msg: str, ok: bool = True) -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    prefix = "ok" if ok else "err"
    return RedirectResponse(f"{url}{sep}{prefix}={quote(msg)}", status_code=303)


def _parse_date(s: str) -> date:
    return datetime.strptime((s or "").strip(), "%Y-%m-%d").date()


# ---- trainee / superadmin daily view --------------------------------------
@router.get("/checks", response_class=HTMLResponse)
def checks_page(request: Request, d: str | None = None,
                user: User = Depends(require_checks_access), db: Session = Depends(get_db)):
    # Trainees always see today; only a superadmin may look at another date.
    day = today_ist()
    if user.is_superadmin and d:
        try:
            day = _parse_date(d)
        except ValueError:
            day = today_ist()
    areas, working = checklist_view(db, day)
    total = sum(a["total"] for a in areas)
    done = sum(a["done"] for a in areas)
    return templates.TemplateResponse(request, "checks.html", {
        "me": user, "areas": areas, "working": working, "day": day,
        "today": today_ist(), "total": total, "done": done,
        "ok": request.query_params.get("ok"), "err": request.query_params.get("err"),
    })


@router.post("/checks/{checklist_id}/save")
async def checks_save(checklist_id: int, request: Request,
                      user: User = Depends(require_checks_access), db: Session = Depends(get_db)):
    form = await request.form()
    day = today_ist()
    if user.is_superadmin and form.get("d"):
        try:
            day = _parse_date(form["d"])
        except ValueError:
            day = today_ist()
    done_ids = {int(v) for v in form.getlist("done") if str(v).isdigit()}
    notes = {int(k[5:]): v for k, v in form.items()
             if k.startswith("note_") and k[5:].isdigit()}
    save_checklist(db, checklist_id=checklist_id, d=day, actor=user,
                   done_ids=done_ids, notes=notes)
    back = "/checks"
    if user.is_superadmin and form.get("d"):
        back += f"?d={day.isoformat()}"
    return _flash(back, "Saved.")


# ---- manage (superadmin) --------------------------------------------------
@router.get("/checks/manage", response_class=HTMLResponse)
def checks_manage(request: Request, user: User = Depends(require_superadmin),
                  db: Session = Depends(get_db)):
    checklists = list(db.scalars(
        select(Checklist).order_by(Checklist.active.desc(), Checklist.sort_order, Checklist.id)))
    return templates.TemplateResponse(request, "checks_manage.html", {
        "me": user, "checklists": checklists, "cadences": CADENCES,
        "ok": request.query_params.get("ok"), "err": request.query_params.get("err"),
    })


@router.post("/checks/manage/seed-defaults")
def seed_defaults(admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    from ..checks import seed_default_checklists
    r = seed_default_checklists(db)
    if r["areas_created"] == 0:
        return _flash("/checks/manage", "The default checklist is already loaded — nothing to add.")
    return _flash("/checks/manage",
                  f"Loaded {r['areas_created']} area(s) and {r['checkpoints_created']} checkpoint(s).")


@router.post("/checks/manage/area/create")
def area_create(name: str = Form(...), link: str = Form(""), login_hint: str = Form(""),
                owner_label: str = Form(""), sort_order: str = Form("0"),
                admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    if not name.strip():
        return _flash("/checks/manage", "Area name is required.", ok=False)
    order = int(sort_order) if sort_order.strip().lstrip("-").isdigit() else 0
    db.add(Checklist(name=name.strip(), link=link.strip() or None,
                     login_hint=login_hint.strip() or None,
                     owner_label=owner_label.strip() or None, sort_order=order, active=True))
    db.commit()
    return _flash("/checks/manage", f"Area '{name.strip()}' added.")


@router.post("/checks/manage/area/{area_id}/update")
def area_update(area_id: int, name: str = Form(...), link: str = Form(""),
                login_hint: str = Form(""), owner_label: str = Form(""),
                sort_order: str = Form("0"), active: str = Form("off"),
                admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    cl = db.get(Checklist, area_id)
    if not cl:
        return _flash("/checks/manage", "Area not found.", ok=False)
    cl.name = name.strip() or cl.name
    cl.link = link.strip() or None
    cl.login_hint = login_hint.strip() or None
    cl.owner_label = owner_label.strip() or None
    cl.sort_order = int(sort_order) if sort_order.strip().lstrip("-").isdigit() else cl.sort_order
    cl.active = (active == "on")
    db.commit()
    return _flash("/checks/manage", f"{cl.name} updated.")


@router.post("/checks/manage/item/create")
def item_create(checklist_id: int = Form(...), text: str = Form(...), action: str = Form(""),
                cadence: str = Form("daily"),
                admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    cl = db.get(Checklist, checklist_id)
    if not cl:
        return _flash("/checks/manage", "Area not found.", ok=False)
    if not text.strip():
        return _flash("/checks/manage", "Checkpoint text is required.", ok=False)
    next_seq = (db.scalar(select(func.max(CheckpointItem.seq))
                          .where(CheckpointItem.checklist_id == cl.id)) or 0) + 1
    db.add(CheckpointItem(checklist_id=cl.id, seq=next_seq, text=text.strip(),
                          action=action.strip() or None,
                          cadence=cadence if cadence in CADENCES else "daily", active=True))
    db.commit()
    return _flash("/checks/manage", "Checkpoint added.")


@router.post("/checks/manage/item/{item_id}/update")
def item_update(item_id: int, text: str = Form(...), action: str = Form(""),
                cadence: str = Form("daily"), active: str = Form("off"),
                admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    it = db.get(CheckpointItem, item_id)
    if not it:
        return _flash("/checks/manage", "Checkpoint not found.", ok=False)
    it.text = text.strip() or it.text
    it.action = action.strip() or None
    it.cadence = cadence if cadence in CADENCES else it.cadence
    it.active = (active == "on")
    db.commit()
    return _flash("/checks/manage", "Checkpoint updated.")


@router.post("/checks/manage/item/{item_id}/delete")
def item_delete(item_id: int, admin: User = Depends(require_superadmin),
                db: Session = Depends(get_db)):
    it = db.get(CheckpointItem, item_id)
    if it:
        it.active = False  # soft-delete: keep history intact
        db.commit()
    return _flash("/checks/manage", "Checkpoint removed.")
