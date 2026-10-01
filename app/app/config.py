"""Central configuration, all via environment variables.

Nothing secret is hard-coded. For local dev / tests the defaults fall back to
SQLite and disabled notifications so the app runs with zero setup.
"""
from __future__ import annotations

import os
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# ---- Database -------------------------------------------------------------
# Neon in production, e.g. postgresql+psycopg2://user:pass@host/db?sslmode=require
# SQLite file locally / in tests.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./worktracker.db")

# ---- Auth / sessions ------------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-change-me")
SESSION_COOKIE = "wt_session"
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", str(60 * 60 * 24 * 180)))  # 180 days
DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD", "Bharat@123")

# ---- App identity ---------------------------------------------------------
APP_NAME = os.getenv("APP_NAME", "Work Tracker")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

# Attachments are stored in the DB. Vercel caps a request body at ~4.5 MB,
# so keep per-file uploads under that.
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(4 * 1024 * 1024)))  # 4 MB
MAX_ATTACHMENTS_PER_TASK = int(os.getenv("MAX_ATTACHMENTS_PER_TASK", "10"))

# ---- Email (SMTP) ---------------------------------------------------------
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "info@bharatsteels.in")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Bharat Steel Group - Work Tracker")

# ---- WhatsApp (WATI) ------------------------------------------------------
# WATI tenant base, e.g. https://live-mt-server.wati.io/<tenantId>  (no trailing slash)
WATI_BASE_URL = os.getenv("WATI_BASE_URL", "").rstrip("/")
WATI_TOKEN = os.getenv("WATI_TOKEN", "")  # the long Bearer token from WATI > API Docs
# Names of the three message templates you create & get approved in WATI.
WATI_TEMPLATE_NEW_TASK = os.getenv("WATI_TEMPLATE_NEW_TASK", "wt_new_task")
WATI_TEMPLATE_EMP_DIGEST = os.getenv("WATI_TEMPLATE_EMP_DIGEST", "wt_daily_tasks")
WATI_TEMPLATE_ADMIN_DIGEST = os.getenv("WATI_TEMPLATE_ADMIN_DIGEST", "wt_admin_summary")
WATI_BROADCAST_NAME = os.getenv("WATI_BROADCAST_NAME", "worktracker")
WATI_DEFAULT_CC = os.getenv("WATI_DEFAULT_CC", "91")  # country code prepended to 10-digit numbers

# ---- Cron protection ------------------------------------------------------
CRON_SECRET = os.getenv("CRON_SECRET", "dev-cron-secret")

NOTIFY_EMAIL_ENABLED = bool(SMTP_HOST)
NOTIFY_WHATSAPP_ENABLED = bool(WATI_BASE_URL and WATI_TOKEN)
