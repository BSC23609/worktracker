# Work Tracker (Task Master) — Bharat Steel Group

A task-allocation app on the same stack as the Metfraa Portal: **FastAPI + Vercel + Neon Postgres**,
WhatsApp reminders via **WATI**, email via **SMTP**, morning digests via **GitHub Actions**.

## What it does

- **Superadmins** (Gourav, Jeeva) allocate tasks to anyone — including each other — with a deadline.
  **General users** can raise tasks for themselves.
- **Recurring tasks.** Tick **Repetitive task** when raising one and set a frequency (daily, weekly on a
  chosen weekday, monthly on a chosen day, quarterly, half-yearly, yearly), a start date, an optional end
  date (blank = until stopped), and a deadline as days-from-start. It's stored as a *schedule*; the
  morning job materialises each occurrence as a normal task on the assignee's board as it falls due, and
  they mark each done. The board lists active schedules with a **Stop** button (already-created tasks stay).
- On raising a task, the assignee gets an **email + WhatsApp** reminder with the task and deadline.
- **Every morning (10:00 IST)** each person gets their pending-task list; each superadmin also gets a
  **consolidated** list of everyone's open tasks (overdue flagged). The digest is **skipped on Sundays
  and on any date in the Holiday Master** (superadmins manage these on the **Holidays** page). Recurring
  tasks are still generated daily, so they surface in the next working day's digest.
- If someone can't finish in time they enter a **reason** and a **new deadline**. The old
  deadline is **never overwritten** — the full history of every deadline and reason is kept on
  the task's detail page.
- Tasks can carry **attachments** (any related documents). Files are stored in the database;
  each upload is capped at 4 MB (Vercel's request-body limit), up to 10 per task.
- A **Master** tab (superadmin only) **adds, edits and deletes** users and manages roles and
  WhatsApp numbers. A user tied to existing tasks can't be hard-deleted (it would orphan history);
  untick **Active** to disable them instead.
- People sign in with their **email or employee code** (either works). Email is optional — staff who
  have no email log in with their employee code; they still get WhatsApp reminders.
- **Forgot password via WhatsApp OTP.** The login page has **Forgot password?**: the user enters their
  email or emp code, a 6-digit code is sent to their WhatsApp (and email, if they have one), they enter
  it, then set a new password. Codes expire (default 10 min) and lock after 5 wrong tries. The code is
  held in a signed, expiring cookie — no database table, and the plain code is never stored. This reaches
  everyone, including the emp-code-only staff. Admin reset (Master tab) remains the fallback.
- **"Email login details"** (Master tab) emails the temporary password to staff who have an email; the
  emp-code-only staff sign in with the default password and their code, or use Forgot password.
- The superadmin board is a **consolidated** view: open tasks grouped per person, overdue flagged.

## The deadline-history design (the core requirement)

Each task carries a frozen `original_deadline` and a `current_deadline` (the latest). Every deadline —
the original and each revision — is a row in the `task_deadlines` table (`seq` 1, 2, 3…). Extending a
deadline **adds a row; it never edits or deletes an older one**, so the audit trail is complete.
The task detail page renders these as a timeline (Original → Revision → Current, each with its reason
and who set it).

## Layout

```
api/index.py              Vercel ASGI entry (imports app.main:app)
app/
  config.py               all settings from env vars
  db.py                   SQLAlchemy engine/session, IST helpers
  models.py               User, Task, TaskDeadline (history), NotificationLog
  auth.py                 bcrypt + signed-cookie sessions, role guards
  services.py             task lifecycle (create / extend / complete) — the invariant lives here
  notifications.py        SMTP + WATI senders (fail-soft, logged) + message rendering
  digests.py              daily per-user and consolidated digests (idempotent per day)
  routes/web.py           pages + form actions
  routes/cron.py          /health and the secret-protected /cron/daily-digests
  templates/ , static/    self-hosted UI (no CDN dependency)
scripts/init_db.py        create tables + seed the two superadmins
.github/workflows/        daily-digests.yml (08:00 IST cron)
tests/                    29 tests (deadline history, auth, notifications, full HTTP flow)
```

## Deploy

1. **Repo**: create `BSC23609/worktracker`, push this tree. Root Directory stays empty (Vercel reads `vercel.json`).
2. **Neon**: create a Postgres DB (Singapore). Copy the pooled connection string.
3. **Vercel env vars** (from `.env.example`): `DATABASE_URL`, `SECRET_KEY`, `BASE_URL`, the `SMTP_*`,
   the `WATI_*`, and `CRON_SECRET`.
4. **Create the schema + seed superadmins** — run once from the repo root with the Neon URL set:
   ```bash
   DATABASE_URL="postgresql+psycopg2://…?sslmode=require" python scripts/init_db.py
   ```
   (This is cleaner than the INIT_DB dance; `INIT_DB=true` at deploy time is available as a fallback.)
   Gourav and Jeeva are seeded as superadmins with the default password **`Bharat@123`**, forced to
   reset on first login. Everyone else is added from the **Master** tab.
5. **GitHub Actions** (morning digests): add repo secrets `BASE_URL` (e.g. `https://worktracker.…`) and
   `CRON_SECRET` (same value as Vercel). The workflow fires at 02:30 UTC = **08:00 IST** daily and can
   also be run manually from the Actions tab.

### Updating the schema later

`scripts/neon_setup.sql` is the full fresh-install script (schema + indexes + the whole roster) and
is idempotent. `scripts/add_emp_code.sql` and `scripts/add_recurring.sql` are one-time migrations for a
database created before those features (employee-code login, and recurring tasks, respectively) — each
adds only what's missing and leaves existing rows untouched. For any later model change you can re-run
`neon_setup.sql` or `scripts/init_db.py`; both only add what's missing.

## WATI templates to create (and get approved)

Create these three template messages in WATI with the parameter order below, then put their names in
the `WATI_TEMPLATE_*` env vars (defaults shown). Numbers like `{{1}}` are WATI's positional params.

| env var | default name | parameters (in order) |
|---|---|---|
| `WATI_TEMPLATE_NEW_TASK` | `wt_new_task` | `{{1}}` assignee name · `{{2}}` task title · `{{3}}` deadline · `{{4}}` raised by |
| `WATI_TEMPLATE_EMP_DIGEST` | `wt_daily_tasks` | `{{1}}` name · `{{2}}` open count · `{{3}}` overdue count |
| `WATI_TEMPLATE_ADMIN_DIGEST` | `wt_admin_summary` | `{{1}}` admin name · `{{2}}` open count · `{{3}}` overdue count |
| `WATI_TEMPLATE_OTP` | `wt_otp` | `{{1}}` the 6-digit code |
| `WATI_TEMPLATE_WELCOME` | `wt_welcome3` | *(no variables — static body)* |

For `wt_otp`, a simple body such as *"{{1}} is your Work Tracker verification code. It expires in 10
minutes."* works. WhatsApp's **Authentication** template category is the intended one for codes and is
the most reliable to get approved; a Utility template with the code as `{{1}}` also works. Until it's
approved, the code still goes out by **email** to anyone who has one.

`WATI_BASE_URL` has **no trailing slash** and includes the tenant id, e.g.
`https://live-mt-server.wati.io/1234567`. `WATI_TOKEN` is the Bearer token from WATI → API Docs.

Email and WhatsApp are each **optional and fail-soft**: leave `SMTP_*` or `WATI_*` blank to disable
that channel. A provider outage is logged to `notification_log` and never blocks a task action.

## Run locally

```bash
pip install -r requirements.txt
python scripts/init_db.py          # uses SQLite (worktracker.db) with no DATABASE_URL set
uvicorn app.main:app --reload      # http://localhost:8000  (login as gourav@bharatsteels.in / Bharat@123)
python -m pytest -q                # 29 tests
```
