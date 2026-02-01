# ADR-0011: Observability and Velocity Tracking

[🏠 Home](../../README.md) > [📚 Docs](../INDEX.md) > [ADRs](./README.md) > ADR-0011

---

**Date:** 2026-01-30
**Status:** Accepted
**Deciders:** Framework Core Team
**Tags:** observability, metrics, velocity, M4

---

## Context

Multi-agent coordination without observability is like flying blind. We needed answers to:

**Key Questions:**
- How fast are agents completing tasks?
- Which files are causing lock contention?
- Where are agents spending time (pending vs in-progress vs waiting)?
- Are agents getting faster or slower over time?
- Which tasks are blocking others?

**Problems Without Observability:**
- No visibility into system performance
- Cannot identify bottlenecks
- Difficult to optimize workflows
- No data for capacity planning
- Hard to debug coordination issues

---

## Decision Drivers

- **Actionable Metrics:** Data that drives decisions
- **Low Overhead:** < 5% performance impact
- **Real-time:** Current state, not just historical
- **Simple Queries:** Easy to access and understand
- **Automatic:** No manual tracking required

---

## Considered Options

### Option 1: No Observability

**Description:** Just log events, manual analysis

**Pros:**
- No implementation needed
- Zero overhead

**Cons:**
- No metrics or insights
- Cannot optimize system
- Difficult debugging
- No trend analysis

**Effort:** None

---

### Option 2: External Metrics System (Prometheus, Grafana)

**Description:** Send metrics to external monitoring stack

**Pros:**
- Industry standard
- Rich visualization
- Long-term storage
- Advanced querying

**Cons:**
- Requires external services
- Deployment complexity
- Overkill for local development
- Network overhead

**Effort:** High

---

### Option 3: Built-in SQLite Metrics

**Description:** Store metrics in coordination database, expose via CLI

**Pros:**
- Zero external dependencies
- Same database as coordination
- Fast local queries
- Simple deployment
- Built-in to coordination daemon

**Cons:**
- Limited visualization (CLI only)
- Not ideal for production monitoring
- Database growth over time

**Effort:** Medium

---

## Decision Outcome

**Chosen Option:** Option 3: Built-in SQLite Metrics (with migration path)

**Justification:**

For M4 single-machine scope, built-in metrics are perfect:
- Developers get immediate feedback via CLI
- Zero deployment complexity
- Fast queries (same database)
- Can add external metrics in M5+ without breaking existing

**Migration Path:**
- M4: SQLite + CLI (development)
- M5: Add Prometheus export (production)
- Both can coexist (SQLite for local, Prometheus for prod)

---

## Consequences

### Positive

- ✅ Immediate observability (no setup)
- ✅ Fast queries (< 100ms)
- ✅ No external dependencies
- ✅ Data co-located with coordination
- ✅ Simple CLI access

### Negative

- ❌ CLI-only visualization (no dashboards)
- ❌ Database growth (need cleanup strategy)
- ❌ Not ideal for distributed systems (M5+)

### Neutral

- Can add external metrics later
- Good for development, adequate for small production
- Metrics stored same lifetime as tasks

---

## Implementation Notes

**Metrics Tables:**

```sql
-- Task completion events
CREATE TABLE velocity_events (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,  -- task_completed, task_claimed
    agent_id TEXT,
    task_id TEXT,
    duration_seconds REAL,
    metadata TEXT  -- JSON
);

-- File lock statistics
CREATE TABLE file_lock_stats (
    file_path TEXT PRIMARY KEY,
    lock_count INTEGER DEFAULT 0,
    total_lock_duration_seconds REAL DEFAULT 0,
    last_locked_at TIMESTAMP,
    last_locked_by TEXT
);

-- Task timing breakdown
CREATE TABLE task_timing (
    task_id TEXT PRIMARY KEY,
    created_at TIMESTAMP,
    claimed_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    time_pending_seconds REAL,
    time_in_progress_seconds REAL,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

-- Periodic snapshots
CREATE TABLE metrics_snapshots (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_tasks INTEGER,
    pending_tasks INTEGER,
    in_progress_tasks INTEGER,
    completed_tasks INTEGER,
    active_agents INTEGER,
    avg_task_duration_seconds REAL
);
```

**CLI Commands:**

```bash
# Task completion velocity
coord velocity --period '1 hour'
# Output: 15 tasks/hour, avg 4.2 minutes/task

# File lock hotspots
coord file-hotspots --limit 10
# Output: Most frequently locked files

# Task timing breakdown
coord task-timing code-crit-auth-1
# Output:
#   Pending: 5 minutes
#   In Progress: 20 minutes
#   Total: 25 minutes

# System status
coord status
# Output: Active agents, task counts, velocity
```

**Automatic Tracking:**

All coordination operations automatically emit events:
- Task creation → velocity_events
- Task claim → task_timing.claimed_at
- Task complete → velocity_events + task_timing.completed_at
- File lock → file_lock_stats updated
- Heartbeat → agent status updated

**Performance Impact:**

Measured overhead:
- Event insertion: < 5ms
- Query velocity: < 100ms
- File hotspots: < 50ms
- Total impact: < 2% of operation time

**Action Items:**
- [x] Add metrics tables to schema
- [x] Implement event tracking
- [x] Build CLI commands
- [x] Add automatic cleanup (30-day retention)
- [x] Document metrics usage
- [x] Test performance impact

---

## Related Decisions

- [ADR-0008: Coordination Daemon](./0008-coordination-daemon-architecture.md) - Provides database
- [ADR-0004: Observability Database Schema](./0004-observability-database-schema.md) - Framework observability

---

## References

- [Coordination README](../../.claude-coord/README.md) - CLI documentation
- [SERVICE_ARCHITECTURE.md](../../.claude-coord/SERVICE_ARCHITECTURE.md) - Observability section
- [Four Golden Signals](https://sre.google/sre-book/monitoring-distributed-systems/) - Google SRE

---

## Update History

| Date | Author | Change |
|------|--------|--------|
| 2026-01-30 | Framework Team | Initial implementation |
| 2026-02-01 | Documentation Team | ADR documentation |
