-- Work Tracker - one-time Neon setup (safe to re-run; idempotent)
-- Paste into the Neon SQL Editor and Run. Creates tables+indexes and seeds superadmins.

-- ===== TABLES =====
CREATE TABLE IF NOT EXISTS users (
	id SERIAL NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	whatsapp VARCHAR(32), 
	role VARCHAR(32) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	must_reset BOOLEAN NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS tasks (
	id SERIAL NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	description TEXT, 
	priority VARCHAR(16) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	assigned_to_id INTEGER NOT NULL, 
	created_by_id INTEGER NOT NULL, 
	original_deadline DATE NOT NULL, 
	current_deadline DATE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	completion_note TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(assigned_to_id) REFERENCES users (id), 
	FOREIGN KEY(created_by_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS notification_log (
	id SERIAL NOT NULL, 
	task_id INTEGER, 
	kind VARCHAR(32) NOT NULL, 
	channel VARCHAR(16) NOT NULL, 
	recipient VARCHAR(255) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	detail TEXT, 
	dedupe_key VARCHAR(120), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id)
);

CREATE TABLE IF NOT EXISTS task_attachments (
	id SERIAL NOT NULL, 
	task_id INTEGER NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	content_type VARCHAR(120) NOT NULL, 
	size INTEGER NOT NULL, 
	data BYTEA NOT NULL, 
	uploaded_by_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id), 
	FOREIGN KEY(uploaded_by_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS task_deadlines (
	id SERIAL NOT NULL, 
	task_id INTEGER NOT NULL, 
	seq INTEGER NOT NULL, 
	deadline DATE NOT NULL, 
	reason TEXT, 
	set_by_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id), 
	FOREIGN KEY(set_by_id) REFERENCES users (id)
);

-- ===== INDEXES =====
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);
CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks (status);
CREATE INDEX IF NOT EXISTS ix_tasks_assigned_to_id ON tasks (assigned_to_id);
CREATE INDEX IF NOT EXISTS ix_tasks_created_by_id ON tasks (created_by_id);
CREATE INDEX IF NOT EXISTS ix_tasks_current_deadline ON tasks (current_deadline);
CREATE INDEX IF NOT EXISTS ix_notification_log_dedupe_key ON notification_log (dedupe_key);
CREATE INDEX IF NOT EXISTS ix_notification_log_task_id ON notification_log (task_id);
CREATE INDEX IF NOT EXISTS ix_task_attachments_task_id ON task_attachments (task_id);
CREATE INDEX IF NOT EXISTS ix_task_deadlines_task_id ON task_deadlines (task_id);

-- ===== SEED SUPERADMINS (password: Bharat@123) =====
INSERT INTO users (email, name, role, password_hash, must_reset, active) VALUES ('gourav@bharatsteels.in', 'Gourav Saraf', 'superadmin', '$2b$12$Uln2nCVMbZAv5rEmqCFijORN8aKTYjAevfV6unorF7KJLXXXqJ7Qy', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (email, name, role, password_hash, must_reset, active) VALUES ('jeeva@bharatsteels.in', 'Jeeva', 'superadmin', '$2b$12$Uln2nCVMbZAv5rEmqCFijORN8aKTYjAevfV6unorF7KJLXXXqJ7Qy', true, true) ON CONFLICT (email) DO NOTHING;
