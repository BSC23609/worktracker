-- Work Tracker: full fresh-install setup (schema + indexes + roster). Idempotent.

-- ===== TABLES =====
CREATE TABLE IF NOT EXISTS users (
	id SERIAL NOT NULL, 
	emp_code VARCHAR(40), 
	email VARCHAR(255), 
	name VARCHAR(255) NOT NULL, 
	whatsapp VARCHAR(32), 
	role VARCHAR(32) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	must_reset BOOLEAN NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS holidays (
	id SERIAL NOT NULL, 
	day DATE NOT NULL, 
	label VARCHAR(200), 
	created_by_id INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(created_by_id) REFERENCES users (id)
);

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
	schedule_id INTEGER, 
	occurrence_date DATE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(assigned_to_id) REFERENCES users (id), 
	FOREIGN KEY(created_by_id) REFERENCES users (id), 
	FOREIGN KEY(schedule_id) REFERENCES task_schedules (id)
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
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_emp_code ON users (emp_code);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);
CREATE UNIQUE INDEX IF NOT EXISTS ix_holidays_day ON holidays (day);
CREATE INDEX IF NOT EXISTS ix_task_schedules_assigned_to_id ON task_schedules (assigned_to_id);
CREATE INDEX IF NOT EXISTS ix_task_schedules_active ON task_schedules (active);
CREATE INDEX IF NOT EXISTS ix_tasks_created_by_id ON tasks (created_by_id);
CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks (status);
CREATE INDEX IF NOT EXISTS ix_tasks_schedule_id ON tasks (schedule_id);
CREATE INDEX IF NOT EXISTS ix_tasks_assigned_to_id ON tasks (assigned_to_id);
CREATE INDEX IF NOT EXISTS ix_tasks_current_deadline ON tasks (current_deadline);
CREATE INDEX IF NOT EXISTS ix_notification_log_task_id ON notification_log (task_id);
CREATE INDEX IF NOT EXISTS ix_notification_log_dedupe_key ON notification_log (dedupe_key);
CREATE INDEX IF NOT EXISTS ix_task_attachments_task_id ON task_attachments (task_id);
CREATE INDEX IF NOT EXISTS ix_task_deadlines_task_id ON task_deadlines (task_id);

-- ===== ROSTER (default password: Bharat@123) =====
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('BSC/003', 'purchase@bharatsteels.in', 'MURKESH M.P.R', '919444085020', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, name, whatsapp, role, password_hash, must_reset, active) VALUES ('BSC/004', 'NALLASIVAM D', '919444085018', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (emp_code) DO NOTHING;
INSERT INTO users (emp_code, name, whatsapp, role, password_hash, must_reset, active) VALUES ('BSC/005', 'PARAMAGURU S', '919444085015', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (emp_code) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('BSC/006', 'baktha@bharatsteels.in', 'BAKTHAVACHALAM C', '919444085016', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, name, whatsapp, role, password_hash, must_reset, active) VALUES ('BSC/012', 'VENKATESH PRASAD DOBA', '917200006787', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (emp_code) DO NOTHING;
INSERT INTO users (emp_code, name, whatsapp, role, password_hash, must_reset, active) VALUES ('BSC/017', 'SHIVAM SHROFF', '919884384261', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (emp_code) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('BSC/074', 'connect@bharatsteels.in', 'SUSMITHA AVULA', '916281867026', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('BSC/098', 'kannan@bharatsteels.in', 'KANNAN K', '919840299625', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('BSC/119', 'jeeva@bharatsteels.in', 'JEEVABHARATHY S', '917395956648', 'superadmin', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('BSC/136', 'sap@bharatsteels.in', 'NAGASUBRAMANIAN N', '919894174741', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('BSC/160', 'hr@bharatsteels.in', 'RAJASEKAR', '918825849418', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('CEO', 'gourav@bharatsteels.in', 'GOURAV SARAF', '919884696666', 'superadmin', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('CMD', 'cmd@bharatsteels.in', 'GOVERDHAN AGARWAL', '919444088086', 'superadmin', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('G2S/058', 'ganapathy@bharatsteels.in', 'GANAPATHY P', '919840630463', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('TECH', 'inspace_it@bharatsteels.in', 'MOHAN', '919384819376', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('MET106', 'accounts@metfraa.com', 'BALAJI M', '918637466998', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('MET66', 'admin@metfraa.com', 'BODAPATI SHEELA HEPSIBAH GRACE', '919963315234', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('MET110', 'vp@metfraa.com', 'KALAI BRINDHA M P', '919600068189', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('MET51', 'khajasheriff.m@metfraa.com', 'KHAJA SHERIFF', '917010507589', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('MET78', 'nirmal@metfraa.com', 'NIRMAL KUMAR BALAKRISHNAN', '919840485801', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('MET64', 'thangaraj@metfraa.com', 'P. THANGARAJ', '919994086097', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('MET92', 'varadharaj@metfraa.com', 'VARATHARAJ NAVANEETHAN', '919790249180', 'user', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
INSERT INTO users (emp_code, email, name, whatsapp, role, password_hash, must_reset, active) VALUES ('MET-MD', 'arasu@metfraa.com', 'VELARASU', '919787720731', 'superadmin', '$2b$12$JETPo9cnmr7cLKU69Mk9mu6vRmbqljX2d14UoaulTJP.NQ2SpjY/6', true, true) ON CONFLICT (email) DO NOTHING;
