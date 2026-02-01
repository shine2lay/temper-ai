# Coordination Service - Daemon Implementation

## Architecture

```
┌─────────────────────────────────────────┐
│  Coordination Service Daemon            │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │  Main Process                     │  │
│  │  - SQLite connection pool         │  │
│  │  - Health monitor                 │  │
│  │  - Auto-cleanup (dead agents)     │  │
│  │  - Periodic backups               │  │
│  └───────────────────────────────────┘  │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │  Unix Socket Server               │  │
│  │  /tmp/coord-service.sock          │  │
│  │  - Fast local communication       │  │
│  │  - No network overhead            │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘

**Current:** Unix socket only (single machine)
**Future:** HTTP API planned for multi-machine (M5+)
         │                    │
         ▼                    ▼
   [coordination.db]    [PID file]
```

## Database Schema

The coordination service uses **SQLite** with **15 core tables** plus observability and audit tables.

### Core Tables

| Table | Purpose |
|-------|---------|
| `agents` | Active agent sessions with heartbeat tracking |
| `tasks` | Task specifications, status, and ownership |
| `task_dependencies` | Dependency graph (blocks/blockedBy relationships) |
| `locks` | File locking state per agent |
| `schema_version` | Database migration tracking |

### Observability Tables

| Table | Purpose |
|-------|---------|
| `velocity_events` | Task completion events for velocity tracking |
| `metrics_snapshots` | Periodic metric snapshots |
| `task_timing` | Time spent in each task state |
| `task_file_activity` | File operations per task |
| `file_lock_stats` | Lock contention metrics |
| `performance_traces` | Operation performance profiling |

### Audit Tables

| Table | Purpose |
|-------|---------|
| `audit_log` | All operations with correlation IDs |
| `event_log` | State change events with before/after snapshots |
| `error_snapshots` | Error context for debugging |

### Auto-generated

| Table | Purpose |
|-------|---------|
| `sqlite_sequence` | Auto-increment tracking (SQLite internal) |

**Total:** 15 application tables + 1 SQLite internal

### Schema Access

To view the full schema:
```bash
sqlite3 .claude-coord/coordination.db ".schema"
```

To export schema to file:
```bash
sqlite3 .claude-coord/coordination.db ".schema" > schema.sql
```

### Key Features

- **ACID Transactions:** All operations wrapped in transactions
- **Foreign Keys:** Enforced relationships (ON DELETE CASCADE for locks)
- **Indexes:** Optimized for common queries (status, owner, timestamp)
- **WAL Mode:** Write-Ahead Logging for crash recovery
- **Check Constraints:** Data validation at DB level

## Daemon Lifecycle

### Startup

```python
class CoordinationDaemon:
    def start(self, background=False):
        # 1. Check if already running
        if self.is_running():
            print("Service already running")
            return

        # 2. Initialize database
        self.db = Database("coordination.db")
        self.db.migrate()

        # 3. Recover from crashes
        self.recover_orphaned_tasks()

        # 4. Start socket server
        self.socket = UnixSocketServer("/tmp/coord-service.sock")

        # 5. Start background tasks
        self.start_background_tasks()

        # 6. Write PID file
        with open("/tmp/coord-service.pid", "w") as f:
            f.write(str(os.getpid()))

        # 7. Daemonize if requested
        if background:
            self.daemonize()

        # 8. Enter main loop
        self.run()
```

### Running

```python
def run(self):
    """Main service loop"""
    print("Coordination service started")
    print(f"  Socket: {self.socket_path}")
    print(f"  Database: {self.db_path}")
    print(f"  PID: {os.getpid()}")

    while self.running:
        # Handle requests
        for client in self.socket.accept():
            self.handle_request(client)

        # Background maintenance
        if time.time() - self.last_cleanup > 60:
            self.cleanup_dead_agents()
            self.last_cleanup = time.time()

        # Auto-backup
        if time.time() - self.last_backup > 3600:
            self.backup_database()
            self.last_backup = time.time()
```

### Shutdown

```python
def stop(self):
    """Graceful shutdown"""
    print("Stopping coordination service...")

    # 1. Stop accepting new connections
    self.running = False

    # 2. Wait for active requests to complete
    self.wait_for_active_requests(timeout=5)

    # 3. Close database connections
    self.db.close()

    # 4. Remove socket file
    os.unlink(self.socket_path)

    # 5. Remove PID file
    os.unlink("/tmp/coord-service.pid")

    print("Service stopped")
```

## Communication Protocols

### Unix Socket (Default - Fastest)

```python
# Client side
import socket
import json

def call_service(command, **kwargs):
    sock = socket.socket(socket.AF_UNIX)
    sock.connect("/tmp/coord-service.sock")

    request = json.dumps({"command": command, "args": kwargs})
    sock.send(request.encode())

    response = sock.recv(4096)
    return json.loads(response)

# Usage
result = call_service("task_add", task_id="my-task", subject="Fix bug")
```

### HTTP API (Future Enhancement - M5+)

**Status:** Not yet implemented. Currently Unix socket only.

**Planned for M5:**
```python
# Future: Start with HTTP enabled
coord-service start --http --port 8765

# Future: Client can use REST API
curl http://localhost:8765/tasks
curl -X POST http://localhost:8765/tasks \
  -d '{"id": "my-task", "subject": "Fix bug"}'
```

**Current workaround:** All agents must run on same machine and use Unix socket.

## Process Management

### Manual (Simple)

```bash
#!/bin/bash
# coord-service CLI wrapper

case "$1" in
    start)
        if [ -f /tmp/coord-service.pid ]; then
            echo "Service already running"
            exit 1
        fi
        python3 -m coord_service.daemon --daemon
        ;;

    stop)
        if [ ! -f /tmp/coord-service.pid ]; then
            echo "Service not running"
            exit 1
        fi
        kill $(cat /tmp/coord-service.pid)
        ;;

    restart)
        $0 stop
        sleep 1
        $0 start
        ;;

    status)
        if [ -f /tmp/coord-service.pid ]; then
            PID=$(cat /tmp/coord-service.pid)
            if kill -0 $PID 2>/dev/null; then
                echo "Service running (PID: $PID)"
                exit 0
            else
                echo "Stale PID file"
                exit 1
            fi
        else
            echo "Service not running"
            exit 1
        fi
        ;;
esac
```

### systemd (Production)

```ini
# /etc/systemd/system/coord-service.service

[Unit]
Description=Coordination Service for Multi-Agent Framework
After=network.target

[Service]
Type=simple
User=shinelay
WorkingDirectory=/home/shinelay/meta-autonomous-framework/.claude-coord
ExecStart=/usr/bin/python3 -m coord_service.daemon
ExecStop=/bin/kill -TERM $MAINPID
Restart=on-failure
RestartSec=5

# Security hardening
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### Supervisor (Alternative)

```ini
# /etc/supervisor/conf.d/coord-service.conf

[program:coord-service]
command=/usr/bin/python3 -m coord_service.daemon
directory=/home/shinelay/meta-autonomous-framework/.claude-coord
user=shinelay
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/coord-service.log
```

## Background Tasks

The daemon runs periodic maintenance tasks:

```python
class BackgroundTasks:
    """Background maintenance tasks"""

    def __init__(self, service):
        self.service = service
        self.tasks = [
            (60, self.cleanup_dead_agents),      # Every minute
            (300, self.cleanup_old_locks),       # Every 5 minutes
            (3600, self.backup_database),        # Every hour
            (3600, self.vacuum_database),        # Every hour
        ]

    def cleanup_dead_agents(self):
        """Remove agents that haven't sent heartbeat"""
        cutoff = time.time() - 300  # 5 minutes
        dead = self.service.db.query(
            "SELECT id FROM agents WHERE last_heartbeat < ?",
            (cutoff,)
        )
        for agent_id in dead:
            self.service.unregister_agent(agent_id)

    def cleanup_old_locks(self):
        """Release locks from dead agents"""
        # Locks held by unregistered agents
        orphaned = self.service.db.query("""
            SELECT file_path FROM locks
            WHERE agent_id NOT IN (SELECT id FROM agents)
        """)
        for path in orphaned:
            self.service.release_lock(path)

    def backup_database(self):
        """Create database backup"""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"backups/db/coordination-{timestamp}.db"
        self.service.db.backup(backup_path)

    def vacuum_database(self):
        """Optimize database"""
        self.service.db.execute("VACUUM")
```

## Health Monitoring

```python
class HealthMonitor:
    """Service health monitoring"""

    def check_health(self):
        """Return health status"""
        return {
            "status": "healthy",
            "uptime": time.time() - self.start_time,
            "database": self.check_database(),
            "socket": self.check_socket(),
            "agents": self.count_active_agents(),
            "tasks": self.count_pending_tasks(),
            "memory": self.get_memory_usage(),
        }

    def check_database(self):
        """Verify database is accessible"""
        try:
            self.db.execute("SELECT 1")
            return {"status": "ok", "size": os.path.getsize(self.db_path)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def check_socket(self):
        """Verify socket is listening"""
        return {
            "path": self.socket_path,
            "exists": os.path.exists(self.socket_path),
            "connections": len(self.active_connections),
        }
```

## Crash Recovery

```python
def recover_from_crash(self):
    """Recover state after unclean shutdown"""

    print("Checking for crash recovery...")

    # 1. Check for stale PID file
    if os.path.exists(self.pid_file):
        old_pid = int(open(self.pid_file).read())
        if not self.is_process_running(old_pid):
            print(f"  Removing stale PID file (old PID: {old_pid})")
            os.unlink(self.pid_file)

    # 2. Check for stale socket
    if os.path.exists(self.socket_path):
        try:
            # Try to connect to see if it's really dead
            test_sock = socket.socket(socket.AF_UNIX)
            test_sock.connect(self.socket_path)
            test_sock.close()
            raise Exception("Service already running")
        except socket.error:
            # Socket exists but no one listening
            print(f"  Removing stale socket: {self.socket_path}")
            os.unlink(self.socket_path)

    # 3. Recover orphaned tasks
    orphaned = self.db.query("""
        SELECT id FROM tasks
        WHERE status = 'in_progress'
        AND owner NOT IN (SELECT id FROM agents)
    """)
    if orphaned:
        print(f"  Found {len(orphaned)} orphaned tasks, releasing...")
        for task_id in orphaned:
            self.db.execute(
                "UPDATE tasks SET status='pending', owner=NULL WHERE id=?",
                (task_id,)
            )

    # 4. Clear all locks (they're all stale after crash)
    lock_count = self.db.execute("DELETE FROM locks").rowcount
    if lock_count > 0:
        print(f"  Cleared {lock_count} stale locks")

    print("Recovery complete")
```

## Usage Examples

### Session-based (Start when you work)

```bash
# session-start.sh
echo "Starting coordination service..."
coord-service start

# Check it's running
coord-service status

# Use it
coord task-list
coord task-claim agent-123 my-task

# When done (or let it auto-shutdown after idle)
coord-service stop
```

### Always-on (systemd)

```bash
# Setup once
sudo cp coord-service.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable coord-service
sudo systemctl start coord-service

# Use anytime
coord task-list
coord task-claim agent-123 my-task

# Service runs forever, survives reboots
```

### Development mode (foreground)

```bash
# Run in terminal (see logs)
coord-service start --foreground --verbose

# In another terminal
coord task-list
```

## Auto-shutdown on Idle

```python
class IdleMonitor:
    """Automatically shutdown if idle"""

    def __init__(self, timeout=3600):
        self.timeout = timeout  # 1 hour
        self.last_activity = time.time()

    def mark_activity(self):
        self.last_activity = time.time()

    def check_idle(self):
        idle_time = time.time() - self.last_activity
        if idle_time > self.timeout:
            if self.no_active_agents():
                print(f"Idle for {idle_time}s, shutting down...")
                self.service.stop()
```

## Logging

```python
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('.claude-coord/coord-service.log'),
        logging.StreamHandler()
    ]
)

# Usage
logging.info("Service started")
logging.warning("Dead agent detected: agent-123")
logging.error("Database connection failed")
```

## Comparison: Daemon vs On-demand

| Aspect | Daemon | On-demand |
|--------|--------|-----------|
| **Startup time** | Instant (already running) | 1-2 seconds each time |
| **Resource usage** | ~10-20MB RAM constant | 0 when not in use |
| **Crash recovery** | Auto-restart (systemd) | Manual restart needed |
| **Multi-session** | Shared state across sessions | Separate state per session |
| **Recommended for** | Production, always-on systems | Development, occasional use |

## My Recommendation for You

**Hybrid approach:**
```bash
# session-start.sh
if ! coord-service status >/dev/null 2>&1; then
    echo "Starting coordination service..."
    coord-service start --daemon --auto-shutdown 3600
fi
```

This:
- ✅ Starts automatically if not running
- ✅ Runs as daemon (background)
- ✅ Auto-shuts down after 1 hour idle
- ✅ No manual management needed
- ✅ Minimal resource usage

Want me to build this?
