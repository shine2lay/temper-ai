# Coordination Service Architecture

## Overview

The coordination service is a **centralized daemon** that manages multi-agent collaboration using **SQLite + Unix sockets**. It provides ACID-compliant task management, file locking, and observability for concurrent agent workflows.

**Status:** ✅ **IMPLEMENTED** (Milestone 4)

## Architecture Diagram

```
┌─────────────┐     ┌──────────────────────────┐     ┌─────────────┐
│  Agent 1    │────▶│                          │◀────│  Agent 2    │
└─────────────┘     │  Coordination Daemon     │     └─────────────┘
                    │  (Unix Socket)           │
┌─────────────┐     │                          │     ┌─────────────┐
│  Agent 3    │────▶│  ┌──────────────────┐    │◀────│  CLI Tools  │
└─────────────┘     │  │  SQLite DB       │    │     └─────────────┘
                    │  │  - tasks (17     │    │
                    │  │    tables)       │    │
                    │  │  - agents        │    │
                    │  │  - locks         │    │
                    │  │  - velocity      │    │
                    │  │  - metrics       │    │
                    │  └──────────────────┘    │
                    │                          │
                    │  Performance:            │
                    │  < 100ms per operation   │
                    └──────────────────────────┘
```

## Components

### 1. Coordination Daemon (`daemon.py`)

**Location:** `.claude-coord/daemon/`

**Purpose:** Background service that manages SQLite database and serves requests

**Features:**
- Unix socket server (`.claude-coord/coord.sock`)
- SQLite connection pooling
- Automatic crash recovery
- Graceful shutdown handling
- PID file management

**Startup:**
```bash
# Auto-started by coord CLI if not running
coord register $CLAUDE_AGENT_ID $$
```

### 2. Client Library (`client.py`)

**Purpose:** Python API for agents to communicate with daemon

**Methods:**
- `register_agent()` - Register agent session
- `heartbeat()` - Keep agent alive
- `task_create()` - Create new task
- `task_claim()` - Claim task for work
- `lock_file()` - Acquire file lock
- `velocity()` - Get task velocity metrics

**Example:**
```python
from .claude_coord.client import CoordinationClient

client = CoordinationClient()
client.register_agent("agent-1", process_id=1234)
client.task_claim("agent-1", "task-123")
```

### 3. CLI Tool (`coord`)

**Location:** `.claude-coord/bin/coord`

**Purpose:** Command-line interface for agents and humans

**Command Categories:**
- **Agent:** `register`, `heartbeat`, `unregister`
- **Tasks:** `task-create`, `task-list`, `task-claim`, `task-complete`
- **Locks:** `lock`, `unlock`, `lock-all`, `my-locks`
- **Observability:** `status`, `velocity`, `file-hotspots`, `task-timing`
- **Dependencies:** `task-deps`, `task-add-dep`, `task-remove-dep`

**Example:**
```bash
coord task-create test-med-api-1 "API Tests" "Test all API endpoints"
coord task-claim $CLAUDE_AGENT_ID test-med-api-1
```

### 4. Database (`coordination.db`)

**Technology:** SQLite 3.31+

**Schema:** 17 tables (see `schema.sql`)

**Key Tables:**
- `agents` - Active agent sessions
- `tasks` - Task specifications and status
- `task_dependencies` - Dependency graph
- `file_locks` - File locking state
- `velocity_events` - Task completion tracking
- `metrics_snapshots` - Observability data
- `validation_rules` - Task validation config

**Location:** `.claude-coord/coordination.db`

## Communication Protocol

### Unix Socket

**Path:** `.claude-coord/coord.sock`

**Format:** JSON messages over Unix domain socket

**Request:**
```json
{
  "action": "task_claim",
  "agent_id": "agent-1",
  "task_id": "test-med-api-1"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "task": {...},
    "claimed_at": "2026-02-01T14:07:00Z"
  }
}
```

**Error Response:**
```json
{
  "success": false,
  "error": "Task already claimed by agent-2"
}
```

## Performance Characteristics

**Measured Performance** (M4 validation):
- **Agent registration:** < 50ms
- **Task creation:** < 80ms
- **Task claim:** < 60ms
- **File lock:** < 40ms
- **Velocity query:** < 100ms

**Scalability:**
- **Agents:** Tested with 10 concurrent agents
- **Tasks:** Handles 1000+ tasks efficiently
- **Database:** Single SQLite file, ~10MB for 500 tasks
- **Lock contention:** Automatic retry with exponential backoff

## Deployment Model

### Development

```bash
# Daemon auto-starts on first coord command
coord register $CLAUDE_AGENT_ID $$
```

### Production

```bash
# Manual daemon start
.claude-coord/bin/coord-daemon start

# Check daemon status
coord status

# Stop daemon
.claude-coord/bin/coord-daemon stop
```

### Multi-Machine (Future)

- Currently: Single machine only (Unix socket)
- Future: HTTP API for multi-machine coordination
- Migration path: Socket ↔ HTTP transparent to clients

## Reliability Features

### ACID Transactions

All database operations use SQLite transactions:
- **Atomic:** Task claim checks + update in single transaction
- **Consistent:** Foreign key constraints enforced
- **Isolated:** Serializable isolation level
- **Durable:** WAL mode with fsync

### Crash Recovery

- SQLite WAL mode enables automatic recovery
- Agent heartbeats detect crashed agents
- Orphaned locks auto-released after timeout
- Task dependencies remain intact

### File Locking Safety

- Prevents race conditions in multi-agent edits
- Atomic `lock-all` for multiple files
- Automatic deadlock detection
- Lock holder tracked by agent ID

## Observability

### Metrics

**Velocity Tracking:**
```bash
coord velocity --period '1 hour'
# Output: 15 tasks/hour, avg 4.2 minutes/task
```

**File Hotspots:**
```bash
coord file-hotspots --limit 5
# Shows most frequently locked files
```

**Task Timing:**
```bash
coord task-timing test-med-api-1
# Shows time in each state (pending → in_progress → completed)
```

### Logging

- Daemon logs: `.claude-coord/daemon.log`
- Client errors: Propagated to agent stderr
- SQL queries: DEBUG level logging

## Troubleshooting

### Daemon Not Running

```bash
# Check if running
coord status

# Manually start
.claude-coord/bin/coord-daemon start

# Check logs
tail -f .claude-coord/daemon.log
```

### Database Locked

```bash
# Check for active agents
coord status

# Force unlock (caution)
rm .claude-coord/coordination.db-wal
```

### Socket Connection Refused

```bash
# Check socket exists
ls -la .claude-coord/coord.sock

# Restart daemon
.claude-coord/bin/coord-daemon restart
```

## Design Decisions

### Why SQLite?

- ✅ Single file (easy backup/restore)
- ✅ ACID transactions (no corruption)
- ✅ No separate database server
- ✅ < 100ms operations
- ✅ Battle-tested reliability

### Why Unix Socket?

- ✅ Faster than HTTP (no network stack)
- ✅ File permissions for security
- ✅ Local-only (prevents remote exploits)
- ❌ Limits to single machine (acceptable for M4)

### Why Daemon (vs File-Based)?

- ✅ Prevents file corruption
- ✅ Atomic operations
- ✅ Centralized validation
- ✅ Observability hooks
- ❌ Slightly more complex (but < 1000 LOC)

## Future Enhancements

**M5+ Roadmap:**
1. **HTTP API** - Multi-machine coordination
2. **WebSocket** - Real-time agent updates
3. **Distributed SQLite** - Replication across machines
4. **GraphQL API** - Flexible queries for dashboards

**Migration Strategy:**
- Add HTTP alongside Unix socket
- Clients auto-detect and prefer Unix socket
- Seamless fallback to HTTP for remote agents

---

## See Also

- [DAEMON_FOR_SKILLS.md](./DAEMON_FOR_SKILLS.md) - Usage guide for skill development
- [DEPENDENCY_GUIDE.md](./DEPENDENCY_GUIDE.md) - Task dependency system
- [VALIDATION_SYSTEM.md](./VALIDATION_SYSTEM.md) - Task validation rules
- [schema.sql](./schema.sql) - Full database schema
- [README.md](./README.md) - CLI reference

---

**Last Updated:** 2026-02-01
**Status:** Production-ready (M4 complete)
