# Coordination Service Architecture Options

## Current Architecture (File-Based)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Agent 1    │────▶│             │◀────│  Agent 2    │
└─────────────┘     │ state.json  │     └─────────────┘
                    │ + flock     │
┌─────────────┐     │             │     ┌─────────────┐
│  Agent 3    │────▶│             │◀────│  Test Suite │
└─────────────┘     └─────────────┘     └─────────────┘
                           ▲
                           │ (Can be overwritten!)
                           ▼
                    [File replaced]
```

**Problems:**
- File can be deleted/replaced entirely
- Lock contention with many agents
- No validation of writes
- No atomic multi-operation transactions
- Corruption risk if process crashes mid-write

---

## Option 1: Lightweight SQLite Service (RECOMMENDED)

```
┌─────────────┐     ┌──────────────────────────┐     ┌─────────────┐
│  Agent 1    │────▶│                          │◀────│  Agent 2    │
└─────────────┘     │  Coordination Service    │     └─────────────┘
                    │  (Unix Socket/HTTP)      │
┌─────────────┐     │                          │     ┌─────────────┐
│  Agent 3    │────▶│  ┌──────────────────┐    │◀────│  CLI Tools  │
└─────────────┘     │  │  SQLite DB       │    │     └─────────────┘
                    │  │  - tasks         │    │
                    │  │  - agents        │    │
                    │  │  - locks         │    │
                    │  │  - audit_log     │    │
                    │  └──────────────────┘    │
                    │                          │
                    │  Auto-backup to JSON     │
                    └──────────────────────────┘
```

**Benefits:**
- ✅ Single SQLite file (easy backup)
- ✅ ACID transactions (no corruption)
- ✅ No external dependencies
- ✅ Built-in query optimization
- ✅ Can run as daemon or on-demand
- ✅ Backward compatible (exports to JSON)

**Setup complexity:** Low (Python + SQLite built-in)

---

## Option 2: Redis Service (Fast & Simple)

```
┌─────────────┐     ┌──────────────────────────┐     ┌─────────────┐
│  Agent 1    │────▶│                          │◀────│  Agent 2    │
└─────────────┘     │  Coordination Service    │     └─────────────┘
                    │                          │
┌─────────────┐     │  ┌──────────────────┐    │     ┌─────────────┐
│  Agent 3    │────▶│  │  Redis           │    │◀────│  CLI Tools  │
└─────────────┘     │  │  - In-memory     │    │     └─────────────┘
                    │  │  - Persistence   │    │
                    │  │  - Pub/Sub       │    │
                    │  └──────────────────┘    │
                    │                          │
                    │  Real-time updates       │
                    └──────────────────────────┘
```

**Benefits:**
- ✅ Very fast (in-memory)
- ✅ Built-in pub/sub (real-time notifications)
- ✅ Atomic operations
- ✅ Simple data structures
- ✅ Auto-persistence

**Setup complexity:** Medium (requires Redis installation)

---

## Option 3: Hybrid (Service + JSON Compatibility)

```
┌─────────────┐     ┌──────────────────────────┐     ┌─────────────┐
│  Agent 1    │────▶│                          │◀────│  Agent 2    │
└─────────────┘     │  Coordination Service    │     └─────────────┘
                    │  (Unix Socket)           │
┌─────────────┐     │                          │     ┌─────────────┐
│  Agent 3    │────▶│  ┌──────────────────┐    │◀────│  Legacy     │
└─────────────┘     │  │  SQLite DB       │    │     │  JSON API   │
                    │  │  (Primary)       │    │     └─────────────┘
                    │  └──────────────────┘    │            │
                    │           │              │            │
                    │           ▼              │            ▼
                    │  ┌──────────────────┐    │     ┌────────────┐
                    │  │  state.json      │◀───┼─────│ Bash tools │
                    │  │  (Sync export)   │    │     │ (read-only)│
                    │  └──────────────────┘    │     └────────────┘
                    │                          │
                    └──────────────────────────┘
```

**Benefits:**
- ✅ Best of both worlds
- ✅ Existing bash tools still work (read-only)
- ✅ Service handles all writes
- ✅ Gradual migration path

---

## Recommended: Option 1 (SQLite Service)

### Why SQLite?

1. **Zero external dependencies** - Built into Python
2. **Single file** - Easy to backup/restore
3. **ACID transactions** - Can't corrupt state
4. **Fast enough** - Handles thousands of tasks easily
5. **SQL power** - Complex queries when needed
6. **Portable** - Works everywhere

### Service Architecture

```python
# Coordination Service (daemon)
class CoordinationService:
    def __init__(self, db_path="coordination.db"):
        self.db = sqlite3.connect(db_path)
        self.init_schema()

    def start(self):
        # Option A: Unix socket (local only)
        self.socket = socket.socket(socket.AF_UNIX)

        # Option B: HTTP API (can be remote)
        self.app = FastAPI()

    # API methods
    def task_add(self, task_id, subject, ...):
        with self.db.transaction():
            # Atomic operation
            # Audit logged automatically
            # Can't be corrupted

    def task_claim(self, agent_id, task_id):
        with self.db.transaction():
            # Check task available
            # Check agent registered
            # Claim atomically
            # Release old locks
```

### Schema

```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL,
    priority INTEGER,
    owner TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    pid INTEGER,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE locks (
    file_path TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    agent_id TEXT,
    details TEXT
);
```

---

## Implementation Plan

### Phase 1: Core Service (Week 1)
- [ ] SQLite schema
- [ ] Service daemon (start/stop)
- [ ] Basic API (task CRUD, agent registration)
- [ ] Unix socket communication

### Phase 2: Migration (Week 1)
- [ ] Import from state.json
- [ ] Export to state.json (for compatibility)
- [ ] Wrapper for bash commands
- [ ] Test suite compatibility

### Phase 3: Advanced Features (Week 2)
- [ ] HTTP API (optional remote access)
- [ ] Real-time notifications
- [ ] Advanced queries
- [ ] Performance monitoring

### Phase 4: Polish (Week 2)
- [ ] Auto-backup
- [ ] Health checks
- [ ] Documentation
- [ ] Migration guide

---

## Usage Comparison

### Current (File-based)
```bash
# Start session
.claude-coord/claude-coord.sh task-add "my-task" "subject"
.claude-coord/claude-coord.sh task-claim agent-123 my-task

# Risk: File can be overwritten by any process
```

### With Service
```bash
# Start service (once per session)
coord-service start

# Use same commands (via service)
coord task-add "my-task" "subject"
coord task-claim agent-123 my-task

# Benefits:
# - Service validates all operations
# - Database prevents corruption
# - Audit trail automatic
# - Can rollback any operation
```

---

## Session Workflow

### Current
```bash
.claude-coord/session-start.sh
# Creates snapshot, shows status
```

### With Service
```bash
coord-service start
# Starts daemon, loads state, checks health, ready

coord status
# Shows stats via service API
```

---

## Decision Matrix

| Feature | File-Based | SQLite Service | Redis Service |
|---------|-----------|----------------|---------------|
| **Setup complexity** | ✅ None | ✅ Low | ⚠️ Medium |
| **External deps** | ✅ None | ✅ None | ❌ Redis |
| **Corruption risk** | ❌ High | ✅ None | ✅ Low |
| **Concurrent agents** | ⚠️ Limited | ✅ Excellent | ✅ Excellent |
| **Backup/restore** | ⚠️ Manual | ✅ Simple | ✅ Simple |
| **Query power** | ❌ None | ✅ SQL | ⚠️ Limited |
| **Memory usage** | ✅ Tiny | ✅ Small | ⚠️ Higher |
| **Performance** | ⚠️ Slow | ✅ Fast | ✅ Very fast |
| **Audit trail** | ⚠️ Manual | ✅ Built-in | ⚠️ Manual |
| **Remote access** | ❌ No | ✅ Optional | ✅ Yes |

---

## My Recommendation

**Start with SQLite Service (Option 1)**

Why:
1. Solves your immediate problem (prevents overwrites)
2. No new dependencies
3. Easy to implement (2-3 days)
4. Can always upgrade to Redis later if needed
5. Backward compatible with existing tools

**Not overkill because:**
- You already have coordination complexity
- Multi-agent system needs proper coordination
- State loss has already happened twice
- Service simplifies rather than complicates

---

## Next Steps

If you want to proceed:

1. **Prototype** (2 hours)
   - Basic SQLite schema
   - Simple service daemon
   - Proof of concept

2. **Test** (1 hour)
   - Import current state.json
   - Run a few operations
   - Validate it works

3. **Decide** (Based on results)
   - Keep if it solves problems
   - Rollback if too complex

Want me to build the prototype?
