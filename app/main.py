from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config
from .db import init_db
from .routes import cron, web

app = FastAPI(title=config.APP_NAME)


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
    # For a browser page hitting a login-required route, send them to /login
    # instead of showing raw JSON. API/JSON callers still get JSON.
    if exc.status_code == 401 and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/login", status_code=303)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

# One-time schema init for serverless: set INIT_DB=true, deploy, hit /health, unset.
if os.getenv("INIT_DB", "").lower() == "true":
    init_db()

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.include_router(cron.router)
app.include_router(web.router)
