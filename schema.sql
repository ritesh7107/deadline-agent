-- Three tables. course is a string; a courses table would be structure
-- nothing in the brief asks for.

CREATE TABLE IF NOT EXISTS messages (
  id          INTEGER PRIMARY KEY,
  raw_text    TEXT NOT NULL,
  source      TEXT NOT NULL,          -- whatsapp | email | class | lms
  sender_role TEXT NOT NULL,          -- professor | ta | student | system
  received_at TEXT NOT NULL,          -- ISO8601
  body_hash   TEXT NOT NULL UNIQUE,   -- re-ingesting the corpus is a no-op
  outcome     TEXT,                   -- created | updated | duplicate | ignored
  note        TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
  id                 INTEGER PRIMARY KEY,
  title              TEXT NOT NULL,
  course             TEXT,
  kind               TEXT,            -- assignment | quiz | exam | project | lab | registration | other
  due_at             TEXT,            -- ISO date, or NULL when genuinely unknown
  due_precision      TEXT NOT NULL DEFAULT 'unknown',  -- exact | date_only | unknown
  due_authority      INTEGER,         -- authority score of whoever set due_at
  due_source         TEXT,            -- human label for that source
  weightage          TEXT,
  status             TEXT NOT NULL DEFAULT 'open',
  needs_confirmation INTEGER NOT NULL DEFAULT 0,
  confirm_reason     TEXT,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL
);

-- Audit trail AND the "show both versions" mechanism. One table, two jobs.
CREATE TABLE IF NOT EXISTS task_events (
  id         INTEGER PRIMARY KEY,
  task_id    INTEGER NOT NULL REFERENCES tasks(id),
  message_id INTEGER REFERENCES messages(id),
  field      TEXT NOT NULL,
  old_value  TEXT,
  new_value  TEXT,
  source     TEXT,
  authority  INTEGER,
  reason     TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_course ON tasks(course, status);
CREATE INDEX IF NOT EXISTS idx_events_task  ON task_events(task_id);
