-- Work Tracker: add recurring-task support. Run ONCE in the Neon SQL Editor. Safe to re-run.

-- 1) new table for recurring schedules
CREATE TABLE IF NOT EXISTS task_schedules (
	id SERIAL NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	description TEXT, 
	priority VARCHAR(16) NOT NULL, 
	assigned_to_id INTEGER NOT NULL, 
	created_by_id INTEGER NOT NULL, 
	frequency VARCHAR(20) NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE, 
	day_of_week INTEGER, 
	day_of_month INTEGER, 
	deadline_offset_days INTEGER NOT NULL, 
	active BOOLEAN NOT NULL, 
	last_generated_date DATE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(assigned_to_id) REFERENCES users (id), 
	FOREIGN KEY(created_by_id) REFERENCES users (id)
);

-- 2) link columns on tasks
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS schedule_id INTEGER;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS occurrence_date DATE;

-- 3) indexes
CREATE INDEX IF NOT EXISTS ix_task_schedules_active ON task_schedules (active);
CREATE INDEX IF NOT EXISTS ix_task_schedules_assigned_to_id ON task_schedules (assigned_to_id);
CREATE INDEX IF NOT EXISTS ix_tasks_schedule_id ON tasks (schedule_id);
