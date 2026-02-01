-- Schema v2: Task Dependencies
-- Migration to add task dependency tracking

-- Task dependencies: tracks which tasks depend on which
CREATE TABLE IF NOT EXISTS task_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,           -- The task that has a dependency
    depends_on TEXT NOT NULL,        -- The task it depends on (must complete first)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on) REFERENCES tasks(id) ON DELETE CASCADE,
    UNIQUE(task_id, depends_on),
    CHECK (task_id != depends_on)    -- Prevent self-dependencies
);

CREATE INDEX IF NOT EXISTS idx_dep_task ON task_dependencies(task_id);
CREATE INDEX IF NOT EXISTS idx_dep_depends ON task_dependencies(depends_on);

-- Update schema version
INSERT OR IGNORE INTO schema_version (version) VALUES (2);
