# ADR-0008: Coordination Daemon Architecture

[🏠 Home](../../README.md) > [📚 Docs](../INDEX.md) > [ADRs](./README.md) > ADR-0008

---

**Date:** 2026-01-27
**Status:** Accepted
**Deciders:** Framework Core Team
**Tags:** architecture, multi-agent, coordination, M4

---

## Context

Multi-agent workflows require coordination to prevent conflicts and ensure correct execution order. Initial file-based coordination using JSON + flock had several critical issues:

**Problems with File-Based Coordination:**
- File corruption risk (process crashes mid-write)
- Lock contention with many agents
- No atomic multi-operation transactions
- No validation of writes
- File could be deleted/replaced entirely
- Difficult observability and debugging

**Key Questions:**
- How do we enable safe concurrent agent execution?
- How do we prevent race conditions and data corruption?
- How do we make the system observable and debuggable?
- What's the simplest solution that works?

---

## Decision Drivers

- **Reliability:** ACID transactions to prevent corruption
- **Performance:** < 100ms per operation target
- **Simplicity:** No complex distributed systems for M4
- **Observability:** Built-in metrics and tracking
- **Single-machine scope:** Acceptable for M4 (multi-machine in M5+)
- **Easy deployment:** Minimal external dependencies

---

## Considered Options

### Option 1: Continue with File-Based (JSON + flock)

**Description:** Keep current file-based system, add more error handling

**Pros:**
- No changes needed
- Simple to understand
- No daemon process

**Cons:**
- Cannot solve fundamental corruption issues
- No ACID transactions possible
- Lock contention worsens with scale
- Limited observability
- Race conditions unfixable

**Effort:** Low

---

### Option 2: SQLite Daemon with Unix Socket

**Description:** Centralized daemon using SQLite for data + Unix socket for IPC

**Pros:**
- ACID transactions (prevents corruption)
- < 100ms operations (measured)
- Single file database (easy backup)
- Built-in query capabilities
- Excellent Python support
- Battle-tested reliability

**Cons:**
- Requires daemon process
- Single machine only (acceptable for M4)
- Slightly more complex

**Effort:** Medium

---

### Option 3: PostgreSQL/Redis External Service

**Description:** Use external database or cache service

**Pros:**
- Production-ready multi-machine support
- High scalability
- Rich feature set

**Cons:**
- Requires external service (deployment complexity)
- Overkill for M4 single-machine use case
- Higher latency than Unix socket
- More failure modes

**Effort:** High

---

## Decision Outcome

**Chosen Option:** Option 2: SQLite Daemon with Unix Socket

**Justification:**

1. **ACID Transactions:** SQLite provides true ACID guarantees, eliminating corruption
2. **Performance:** Measured < 100ms per operation (meets requirements)
3. **Simplicity:** Single process, single database file, minimal dependencies
4. **Observability:** Can track all operations in database with audit logs
5. **Right-sized:** Perfect for M4 single-machine scope, migration path to multi-machine in M5

**Key Features Implemented:**
- SQLite with WAL mode (concurrent reads)
- Unix domain socket (faster than HTTP for local)
- Automatic daemon startup
- Heartbeat-based cleanup
- Comprehensive audit logging

---

## Consequences

### Positive

- ✅ Zero data corruption (ACID transactions)
- ✅ Fast operations (< 100ms measured)
- ✅ Full observability (all operations logged)
- ✅ Automatic crash recovery
- ✅ Simple deployment (single daemon)
- ✅ Easy backup (single .db file)

### Negative

- ❌ Requires daemon process (auto-starts, but adds complexity)
- ❌ Single machine only for M4 (multi-machine requires HTTP API in M5)
- ❌ Unix socket not available on all platforms (though works on Mac/Linux)

### Neutral

- Database file grows over time (need cleanup strategy)
- Daemon needs PID file management
- Requires graceful shutdown handling

---

## Implementation Notes

**Architecture:**
```
.claude-coord/
├── daemon/
│   ├── daemon.py          # Main daemon process
│   ├── server.py          # Unix socket server
│   ├── client.py          # Python client library
│   └── operations.py      # Database operations
├── bin/
│   └── coord              # CLI tool
├── coordination.db        # SQLite database
└── coord.sock             # Unix socket
```

**Deployment:**
- Daemon auto-starts on first `coord` command
- PID file prevents multiple instances
- Graceful shutdown on SIGTERM
- WAL mode enabled for crash recovery

**Performance Characteristics (Measured):**
- Agent registration: < 50ms
- Task creation: < 80ms
- Task claim: < 60ms
- File lock: < 40ms
- Velocity query: < 100ms

**Action Items:**
- [x] Implement daemon core
- [x] Add Unix socket server
- [x] Create Python client library
- [x] Build CLI tool (`coord`)
- [x] Add observability hooks
- [x] Write comprehensive tests
- [x] Document API and usage

---

## Related Decisions

- [ADR-0009: Task Dependency System](./0009-task-dependency-system.md) - Builds on this daemon
- [ADR-0010: Task Validation System](./0010-task-validation-system.md) - Uses daemon for validation
- [ADR-0011: Observability Tracking](./0011-observability-tracking.md) - Leverages daemon's database

---

## References

- [SQLite Documentation](https://www.sqlite.org/docs.html)
- [WAL Mode](https://www.sqlite.org/wal.html)
- [Unix Domain Sockets](https://man7.org/linux/man-pages/man7/unix.7.html)
- [SERVICE_ARCHITECTURE.md](../../.claude-coord/SERVICE_ARCHITECTURE.md) - Implementation details

---

## Update History

| Date | Author | Change |
|------|--------|--------|
| 2026-01-27 | Framework Team | Initial implementation |
| 2026-02-01 | Documentation Team | ADR documentation |
