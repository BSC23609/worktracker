-- Work Tracker: per-admin opt-out of the consolidated (admin) digest.
-- Run ONCE in the Neon SQL Editor. Safe to re-run. Existing superadmins default to receiving it.
ALTER TABLE users ADD COLUMN IF NOT EXISTS wants_admin_digest BOOLEAN NOT NULL DEFAULT true;
