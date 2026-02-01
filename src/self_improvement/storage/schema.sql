-- M5 Self-Improvement Experiment Schema
-- Version: 1.0.0
-- Database: SQLite 3.38.0+
-- Requirements:
--   - JSON1 extension (--enable-json1, default in most distributions)
--   - PRAGMA foreign_keys = ON (must be enabled for cascade deletes to work)
-- Purpose: Track A/B/C/D experiments testing different agent configurations

-- CRITICAL: Enable foreign key constraints (disabled by default in SQLite)
PRAGMA foreign_keys = ON;

-- =====================================================
-- M5 Experiments Table
-- =====================================================
-- NOTE: Prefixed with m5_ to avoid collision with existing experiments table
-- in src/experimentation/models.py
CREATE TABLE IF NOT EXISTS m5_experiments (
    -- Primary Key
    id TEXT PRIMARY KEY,

    -- Experiment Identity
    agent_name TEXT NOT NULL,
    proposal_id TEXT,

    -- Status & Lifecycle
    status TEXT NOT NULL DEFAULT 'running',

    -- Configuration (JSON storage for flexibility, validated via CHECK)
    -- SQLite stores JSON as TEXT internally
    control_config TEXT NOT NULL,        -- JSON string: {"model": "llama3.1:8b", ...}
    variant_configs TEXT NOT NULL,       -- JSON array: [{"model": "phi3:mini"}, ...]

    -- Metadata
    description TEXT NOT NULL,           -- Required for tracking/debugging
    hypothesis TEXT,                     -- Optional formal hypothesis
    extra_metadata TEXT,                 -- JSON object or NULL

    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,

    -- Constraints
    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    CHECK (json_valid(control_config)),
    CHECK (json_valid(variant_configs)),
    CHECK (json_type(variant_configs) = 'array'),
    CHECK (json_array_length(variant_configs) > 0),
    CHECK (json_array_length(variant_configs) <= 10),
    CHECK (json_valid(extra_metadata) OR extra_metadata IS NULL)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_m5_experiments_agent_name
    ON m5_experiments(agent_name);

CREATE INDEX IF NOT EXISTS idx_m5_experiments_status
    ON m5_experiments(status);

CREATE INDEX IF NOT EXISTS idx_m5_experiments_created_at
    ON m5_experiments(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_m5_experiments_proposal
    ON m5_experiments(proposal_id);

-- Composite index for active experiments by agent
-- Supports queries: WHERE agent_name = ? AND status = ? ORDER BY created_at
-- Also supports: WHERE agent_name = ? (partial index usage)
CREATE INDEX IF NOT EXISTS idx_m5_experiments_agent_status
    ON m5_experiments(agent_name, status, created_at DESC);

-- =====================================================
-- M5 Experiment Results Table
-- =====================================================
-- PERFORMANCE NOTES:
-- - Expected growth: ~1000-10000 rows per experiment
-- - Total dataset: Potentially millions of rows across all experiments
-- - Retention: Consider archiving completed experiments > 90 days old
CREATE TABLE IF NOT EXISTS m5_experiment_results (
    -- Primary Key
    id TEXT PRIMARY KEY,

    -- Foreign Keys
    experiment_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,

    -- Variant Assignment
    variant_id TEXT NOT NULL,

    -- Performance Metrics
    quality_score REAL,
    speed_seconds REAL,
    cost_usd REAL,
    success BOOLEAN,

    -- Additional Metrics (JSON for extensibility)
    extra_metrics TEXT,                  -- JSON object or NULL

    -- Metadata
    recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    FOREIGN KEY (experiment_id) REFERENCES m5_experiments(id) ON DELETE CASCADE,
    CHECK (quality_score IS NULL OR (quality_score >= 0.0 AND quality_score <= 1.0)),
    CHECK (speed_seconds IS NULL OR speed_seconds >= 0.0),
    CHECK (cost_usd IS NULL OR cost_usd >= 0.0),
    -- Flexible variant_id pattern: 'control' or 'variant_N' where N is 0-99
    CHECK (variant_id = 'control' OR (variant_id GLOB 'variant_[0-9]' OR variant_id GLOB 'variant_[0-9][0-9]')),
    CHECK (json_valid(extra_metrics) OR extra_metrics IS NULL)
);

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_m5_experiment_results_experiment
    ON m5_experiment_results(experiment_id);

CREATE INDEX IF NOT EXISTS idx_m5_experiment_results_variant
    ON m5_experiment_results(experiment_id, variant_id);

CREATE INDEX IF NOT EXISTS idx_m5_experiment_results_execution
    ON m5_experiment_results(execution_id);

CREATE INDEX IF NOT EXISTS idx_m5_experiment_results_recorded
    ON m5_experiment_results(recorded_at DESC);

-- Composite index for statistical analysis
-- Covering index enables fast stats queries without table lookups
CREATE INDEX IF NOT EXISTS idx_m5_experiment_results_analysis
    ON m5_experiment_results(experiment_id, variant_id, quality_score, speed_seconds);

-- Composite index for time-windowed analysis per experiment
-- Supports queries: WHERE experiment_id = ? AND recorded_at >= ? AND recorded_at < ?
CREATE INDEX IF NOT EXISTS idx_m5_experiment_results_time_window
    ON m5_experiment_results(experiment_id, recorded_at DESC);

-- =====================================================
-- M5 Experiment Variants Table (Optional Enhancement)
-- =====================================================
-- Purpose: Track metadata about each variant within an experiment
-- Contains denormalized aggregates for fast dashboard queries
--
-- IMPORTANT: Aggregated metrics are denormalized caches updated by application code.
-- Update strategy: Recalculated via trigger after each m5_experiment_results INSERT
-- DO NOT query these for real-time analysis - use m5_experiment_results directly.

CREATE TABLE IF NOT EXISTS m5_experiment_variants (
    -- Primary Key
    id TEXT PRIMARY KEY,

    -- Foreign Key
    experiment_id TEXT NOT NULL,

    -- Variant Identity
    variant_id TEXT NOT NULL,
    name TEXT,
    description TEXT,

    -- Configuration
    config TEXT NOT NULL,                -- JSON string
    is_control BOOLEAN NOT NULL DEFAULT 0,

    -- Traffic Allocation (per-variant, should sum to 1.0 across all variants)
    -- Example: 4 variants each get 0.25 = 100% total traffic
    -- Application code MUST validate sum(traffic_allocation) = 1.0 before experiment start
    traffic_allocation REAL NOT NULL DEFAULT 0.25,

    -- Aggregated Metrics (cached for performance)
    -- Updated by trigger after each m5_experiment_results INSERT
    total_executions INTEGER NOT NULL DEFAULT 0,
    successful_executions INTEGER NOT NULL DEFAULT 0,
    failed_executions INTEGER NOT NULL DEFAULT 0,

    -- Statistical Summaries (updated by trigger)
    avg_quality_score REAL,
    avg_speed_seconds REAL,
    avg_cost_usd REAL,

    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    FOREIGN KEY (experiment_id) REFERENCES m5_experiments(id) ON DELETE CASCADE,
    UNIQUE (experiment_id, variant_id),
    CHECK (json_valid(config)),
    CHECK (traffic_allocation >= 0.0 AND traffic_allocation <= 1.0),
    -- Match variant_id pattern from m5_experiment_results
    CHECK (variant_id = 'control' OR (variant_id GLOB 'variant_[0-9]' OR variant_id GLOB 'variant_[0-9][0-9]'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_m5_variants_experiment
    ON m5_experiment_variants(experiment_id);

CREATE INDEX IF NOT EXISTS idx_m5_variants_control
    ON m5_experiment_variants(experiment_id, is_control);

-- =====================================================
-- Schema Version Tracking
-- =====================================================
CREATE TABLE IF NOT EXISTS m5_schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

INSERT OR IGNORE INTO m5_schema_version (version, description)
VALUES (1, 'Initial M5 experiment schema: m5_experiments, m5_experiment_results, m5_experiment_variants');

-- =====================================================
-- Triggers for Maintaining Denormalized Aggregates
-- =====================================================

-- Automatically update variant aggregates when new results are recorded
CREATE TRIGGER IF NOT EXISTS update_m5_variant_aggregates
AFTER INSERT ON m5_experiment_results
FOR EACH ROW
BEGIN
    UPDATE m5_experiment_variants
    SET
        total_executions = total_executions + 1,
        successful_executions = successful_executions + CASE WHEN NEW.success = 1 THEN 1 ELSE 0 END,
        failed_executions = failed_executions + CASE WHEN NEW.success = 0 THEN 1 ELSE 0 END,
        avg_quality_score = (
            SELECT AVG(quality_score)
            FROM m5_experiment_results
            WHERE experiment_id = NEW.experiment_id
              AND variant_id = NEW.variant_id
        ),
        avg_speed_seconds = (
            SELECT AVG(speed_seconds)
            FROM m5_experiment_results
            WHERE experiment_id = NEW.experiment_id
              AND variant_id = NEW.variant_id
        ),
        avg_cost_usd = (
            SELECT AVG(cost_usd)
            FROM m5_experiment_results
            WHERE experiment_id = NEW.experiment_id
              AND variant_id = NEW.variant_id
        ),
        updated_at = CURRENT_TIMESTAMP
    WHERE experiment_id = NEW.experiment_id
      AND variant_id = NEW.variant_id;
END;
