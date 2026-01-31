-- Coordination Service Database Schema
-- Version: 1.0.0

-- Agents table: Registered agents
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    pid INTEGER NOT NULL,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT  -- JSON for extensibility
);

CREATE INDEX IF NOT EXISTS idx_agent_heartbeat ON agents(last_heartbeat);

-- Tasks table: Task registry
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    description TEXT NOT NULL,
    active_form TEXT,
    priority INTEGER NOT NULL DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, in_progress, completed, deleted
    owner TEXT,  -- agent_id
    spec_path TEXT,  -- Path to task spec file
    metadata TEXT,  -- JSON

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    FOREIGN KEY (owner) REFERENCES agents(id) ON DELETE SET NULL,
    CHECK (status IN ('pending', 'in_progress', 'completed', 'deleted')),
    CHECK (priority BETWEEN 1 AND 5)
);

CREATE INDEX IF NOT EXISTS idx_task_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_task_owner ON tasks(owner);
CREATE INDEX IF NOT EXISTS idx_task_priority ON tasks(priority);

-- Locks table: File locks
CREATE TABLE IF NOT EXISTS locks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    owner TEXT NOT NULL,  -- agent_id
    acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,  -- JSON

    FOREIGN KEY (owner) REFERENCES agents(id) ON DELETE CASCADE,
    UNIQUE(file_path, owner)
);

CREATE INDEX IF NOT EXISTS idx_lock_file ON locks(file_path);
CREATE INDEX IF NOT EXISTS idx_lock_owner ON locks(owner);

-- Audit log: All operations
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    correlation_id TEXT NOT NULL,

    -- Operation context
    operation TEXT NOT NULL,
    agent_id TEXT,
    entity_type TEXT,
    entity_id TEXT,

    -- Request details
    request_params TEXT,  -- JSON

    -- Outcome
    success BOOLEAN,
    error_code TEXT,
    error_message TEXT,

    -- Performance
    duration_ms INTEGER,

    -- Stack trace for errors
    stack_trace TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_log(correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_errors ON audit_log(success, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_operation ON audit_log(operation, timestamp DESC);

-- Event log: State changes
CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    correlation_id TEXT,

    -- Event details
    event_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,

    -- State change
    old_value TEXT,  -- JSON snapshot before
    new_value TEXT,  -- JSON snapshot after

    -- Context
    triggered_by TEXT,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_event_timestamp ON event_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_event_type ON event_log(event_type);

-- Velocity events: Fine-grained tracking
CREATE TABLE IF NOT EXISTS velocity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    agent_id TEXT,
    task_id TEXT,
    duration_seconds REAL,
    metadata TEXT  -- JSON
);

CREATE INDEX IF NOT EXISTS idx_velocity_timestamp ON velocity_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_velocity_type ON velocity_events(event_type);
CREATE INDEX IF NOT EXISTS idx_velocity_agent ON velocity_events(agent_id);

-- Metrics snapshots: Aggregated metrics
CREATE TABLE IF NOT EXISTS metrics_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- System metrics
    active_agents INTEGER,
    pending_tasks INTEGER,
    in_progress_tasks INTEGER,
    completed_tasks_today INTEGER,

    -- Performance metrics
    avg_task_duration_mins REAL,
    tasks_per_hour REAL,
    lock_contention_rate REAL,

    -- Agent/task breakdown (JSON)
    agent_stats TEXT,
    task_type_stats TEXT
);

CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics_snapshots(timestamp DESC);

-- File lock statistics
CREATE TABLE IF NOT EXISTS file_lock_stats (
    file_path TEXT PRIMARY KEY,
    lock_count INTEGER DEFAULT 0,
    total_lock_duration_seconds REAL DEFAULT 0,
    avg_lock_duration_seconds REAL,
    last_locked_at TIMESTAMP,
    last_locked_by TEXT,
    contention_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_file_lock_count ON file_lock_stats(lock_count DESC);
CREATE INDEX IF NOT EXISTS idx_file_contention ON file_lock_stats(contention_count DESC);

-- Task file activity
CREATE TABLE IF NOT EXISTS task_file_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    lock_acquired_at TIMESTAMP,
    lock_released_at TIMESTAMP,
    lock_duration_seconds REAL,
    operation_type TEXT,

    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_task_files ON task_file_activity(task_id);
CREATE INDEX IF NOT EXISTS idx_file_tasks ON task_file_activity(file_path);

-- Task timing breakdown
CREATE TABLE IF NOT EXISTS task_timing (
    task_id TEXT PRIMARY KEY,
    created_at TIMESTAMP,
    claimed_at TIMESTAMP,
    first_lock_at TIMESTAMP,
    last_unlock_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- Derived metrics
    wait_time_seconds REAL,
    work_time_seconds REAL,
    active_time_seconds REAL,
    idle_time_seconds REAL,

    -- File activity
    files_locked INTEGER,
    files_modified INTEGER,
    total_edits INTEGER,

    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

-- Performance traces
CREATE TABLE IF NOT EXISTS performance_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    correlation_id TEXT,

    operation TEXT NOT NULL,
    duration_ms INTEGER,

    -- Performance breakdown
    db_query_ms INTEGER,
    validation_ms INTEGER,
    lock_wait_ms INTEGER,

    queries_executed INTEGER,
    slow_queries TEXT  -- JSON
);

CREATE INDEX IF NOT EXISTS idx_perf_duration ON performance_traces(duration_ms DESC);
CREATE INDEX IF NOT EXISTS idx_perf_operation ON performance_traces(operation);

-- Error snapshots: Full context on errors
CREATE TABLE IF NOT EXISTS error_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    correlation_id TEXT,

    error_code TEXT,
    error_message TEXT,
    stack_trace TEXT,

    -- Full state snapshot
    state_snapshot TEXT,  -- JSON

    -- System context
    active_agents INTEGER,
    pending_tasks INTEGER,
    memory_usage_mb REAL,
    database_size_mb REAL
);

CREATE INDEX IF NOT EXISTS idx_error_timestamp ON error_snapshots(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_error_code ON error_snapshots(error_code);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
