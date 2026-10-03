-- Work Tracker: allow multiple days per week/month on recurring schedules.
-- Run ONCE in the Neon SQL Editor. Safe to re-run. Existing schedules keep working.
ALTER TABLE task_schedules ADD COLUMN IF NOT EXISTS days_of_week VARCHAR(40);
ALTER TABLE task_schedules ADD COLUMN IF NOT EXISTS days_of_month VARCHAR(120);
