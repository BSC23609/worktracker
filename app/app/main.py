from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config
from .db import init_db
from .routes import cron, web

app = FastAPI(title=config.APP_NAME)

# One-time schema init for serverless: set INIT_DB=true, deploy, hit /health, unset.
if os.getenv("INIT_DB", "").lower() == "true":
    init_db()

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.include_router(cron.router)
app.include_router(web.router)
