-- Add the "Daily Checks access" flag to users. Idempotent (Neon/Postgres).
ALTER TABLE users ADD COLUMN IF NOT EXISTS can_daily_checks BOOLEAN NOT NULL DEFAULT FALSE;
