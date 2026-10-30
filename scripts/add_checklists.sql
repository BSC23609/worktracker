-- Daily Checks tables. Idempotent — safe to run repeatedly on Neon/Postgres.
-- (On a fresh deploy you can instead set INIT_DB=true once; create_all makes
--  these tables automatically and never touches existing ones.)

CREATE TABLE IF NOT EXISTS checklists (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(120) NOT NULL,
    link        VARCHAR(255),
    login_hint  VARCHAR(120),
    owner_label VARCHAR(120),
    sort_order  INTEGER NOT NULL DEFAULT 0,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_checklists_sort_order ON checklists (sort_order);
CREATE INDEX IF NOT EXISTS ix_checklists_active     ON checklists (active);

CREATE TABLE IF NOT EXISTS checkpoint_items (
    id           SERIAL PRIMARY KEY,
    checklist_id INTEGER NOT NULL REFERENCES checklists(id),
    seq          INTEGER NOT NULL DEFAULT 1,
    text         TEXT NOT NULL,
    action       TEXT,
    cadence      VARCHAR(16) NOT NULL DEFAULT 'daily',
    active       BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_checkpoint_items_checklist_id ON checkpoint_items (checklist_id);
CREATE INDEX IF NOT EXISTS ix_checkpoint_items_active       ON checkpoint_items (active);

CREATE TABLE IF NOT EXISTS checkpoint_status (
    id           SERIAL PRIMARY KEY,
    item_id      INTEGER NOT NULL REFERENCES checkpoint_items(id),
    on_date      DATE NOT NULL,
    done         BOOLEAN NOT NULL DEFAULT FALSE,
    note         TEXT,
    marked_by_id INTEGER REFERENCES users(id),
    marked_at    TIMESTAMPTZ,
    CONSTRAINT uq_checkpoint_item_date UNIQUE (item_id, on_date)
);
CREATE INDEX IF NOT EXISTS ix_checkpoint_status_item_id ON checkpoint_status (item_id);
CREATE INDEX IF NOT EXISTS ix_checkpoint_status_on_date ON checkpoint_status (on_date);
