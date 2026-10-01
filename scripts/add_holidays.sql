-- Work Tracker: add the Holiday Master table. Run ONCE in Neon. Safe to re-run.

CREATE TABLE IF NOT EXISTS holidays (
	id SERIAL NOT NULL, 
	day DATE NOT NULL, 
	label VARCHAR(200), 
	created_by_id INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(created_by_id) REFERENCES users (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_holidays_day ON holidays (day);
