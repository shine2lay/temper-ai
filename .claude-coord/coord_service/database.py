"""
Database layer for coordination service.

Provides SQLite database access with connection pooling, transactions,
and state import/export functionality.
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Thread-local storage for connections
_thread_local = threading.local()


class Database:
    """Thread-safe SQLite database wrapper with connection pooling."""

    def __init__(self, db_path: str):
        """Initialize database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._lock = threading.Lock()
        self._initialized = False

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(_thread_local, 'conn'):
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level=None  # Autocommit mode for explicit transactions
            )
            # Enable WAL mode for better concurrency
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")

            # Row factory for dict-like access
            conn.row_factory = sqlite3.Row

            _thread_local.conn = conn

        return _thread_local.conn

    def initialize(self):
        """Initialize database schema."""
        with self._lock:
            if self._initialized:
                return

            schema_path = Path(__file__).parent / "schema.sql"
            with open(schema_path) as f:
                schema_sql = f.read()

            conn = self._get_connection()
            conn.executescript(schema_sql)

            # Apply v2 schema (dependencies)
            schema_v2_path = Path(__file__).parent / "schema_v2_dependencies.sql"
            if schema_v2_path.exists():
                with open(schema_v2_path) as f:
                    schema_v2_sql = f.read()
                conn.executescript(schema_v2_sql)

            self._initialized = True

    @contextmanager
    def transaction(self):
        """Context manager for database transactions.

        Provides ACID guarantees - commits on success, rolls back on exception.
        """
        conn = self._get_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def query(self, sql: str, params: Tuple = ()) -> List[sqlite3.Row]:
        """Execute a SELECT query.

        Args:
            sql: SQL query
            params: Query parameters

        Returns:
            List of row objects
        """
        conn = self._get_connection()
        cursor = conn.execute(sql, params)
        return cursor.fetchall()

    def query_one(self, sql: str, params: Tuple = ()) -> Optional[sqlite3.Row]:
        """Execute a SELECT query expecting single result.

        Args:
            sql: SQL query
            params: Query parameters

        Returns:
            Single row or None
        """
        results = self.query(sql, params)
        return results[0] if results else None

    def execute(self, sql: str, params: Tuple = ()) -> int:
        """Execute an INSERT, UPDATE, or DELETE query.

        Args:
            sql: SQL query
            params: Query parameters

        Returns:
            Number of affected rows
        """
        conn = self._get_connection()
        cursor = conn.execute(sql, params)
        return cursor.rowcount

    # Agent operations
    def agent_exists(self, agent_id: str) -> bool:
        """Check if agent is registered."""
        row = self.query_one("SELECT 1 FROM agents WHERE id = ?", (agent_id,))
        return row is not None

    def register_agent(self, agent_id: str, pid: int, metadata: Dict = None):
        """Register a new agent."""
        with self.transaction():
            self.execute(
                "INSERT INTO agents (id, pid, metadata) VALUES (?, ?, ?)",
                (agent_id, pid, json.dumps(metadata or {}))
            )

    def unregister_agent(self, agent_id: str):
        """Unregister an agent."""
        with self.transaction():
            # Release all locks
            self.execute("DELETE FROM locks WHERE owner = ?", (agent_id,))
            # Release any claimed task (but NOT completed tasks)
            self.execute(
                "UPDATE tasks SET status = 'pending', owner = NULL WHERE owner = ? AND status != 'completed'",
                (agent_id,)
            )
            # Delete agent
            self.execute("DELETE FROM agents WHERE id = ?", (agent_id,))

    def update_heartbeat(self, agent_id: str):
        """Update agent's heartbeat timestamp."""
        self.execute(
            "UPDATE agents SET last_heartbeat = CURRENT_TIMESTAMP WHERE id = ?",
            (agent_id,)
        )

    def get_stale_agents(self, timeout_seconds: int = 300) -> List[str]:
        """Get agents with stale heartbeats.

        Args:
            timeout_seconds: Heartbeat timeout in seconds

        Returns:
            List of stale agent IDs
        """
        rows = self.query(
            """
            SELECT id FROM agents
            WHERE datetime(last_heartbeat, '+' || ? || ' seconds') < datetime('now')
            """,
            (timeout_seconds,)
        )
        return [row['id'] for row in rows]

    # Task operations
    def task_exists(self, task_id: str) -> bool:
        """Check if task exists."""
        row = self.query_one(
            "SELECT 1 FROM tasks WHERE id = ? AND status != 'deleted'",
            (task_id,)
        )
        return row is not None

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task by ID with dependencies."""
        row = self.query_one(
            "SELECT * FROM tasks WHERE id = ? AND status != 'deleted'",
            (task_id,)
        )

        if not row:
            return None

        task = dict(row)

        # Add dependency information
        task['depends_on'] = self.get_task_dependencies(task_id)
        task['blocks'] = self.get_task_dependents(task_id)

        return task

    def create_task(
        self,
        task_id: str,
        subject: str,
        description: str,
        priority: int = 2,
        active_form: str = None,
        spec_path: str = None,
        metadata: Dict = None,
        depends_on: List[str] = None
    ):
        """Create a new task with optional dependencies.

        Args:
            task_id: Unique task identifier
            subject: Task subject/title
            description: Detailed description
            priority: Priority level (0-3, where 0 is highest, default 2)
            active_form: Active form for UI display
            spec_path: Path to task specification file
            metadata: Additional metadata
            depends_on: List of task IDs this task depends on
        """
        with self.transaction() as conn:
            # Create task
            conn.execute(
                """
                INSERT INTO tasks (id, subject, description, priority, active_form, spec_path, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, subject, description, priority, active_form, spec_path, json.dumps(metadata or {}))
            )

            # Initialize task timing
            conn.execute(
                "INSERT INTO task_timing (task_id, created_at) VALUES (?, CURRENT_TIMESTAMP)",
                (task_id,)
            )

            # Add dependencies if provided
            if depends_on:
                for dep_task_id in depends_on:
                    # Check for circular dependencies
                    if self._would_create_cycle(task_id, dep_task_id):
                        raise ValueError(
                            f"Cannot add dependency on {dep_task_id}: "
                            f"would create circular dependency with {task_id}"
                        )

                    # Add dependency
                    conn.execute(
                        "INSERT INTO task_dependencies (task_id, depends_on) VALUES (?, ?)",
                        (task_id, dep_task_id)
                    )

    def claim_task(self, task_id: str, agent_id: str):
        """Claim a task for an agent."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status = 'in_progress', owner = ?, started_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'pending' AND completed_at IS NULL
                """,
                (agent_id, task_id)
            )

            # Verify the update succeeded
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Cannot claim task {task_id}: either task doesn't exist, "
                    f"is not pending, or is already claimed/completed"
                )

            # Update task timing
            conn.execute(
                "UPDATE task_timing SET claimed_at = CURRENT_TIMESTAMP WHERE task_id = ?",
                (task_id,)
            )

    def complete_task(self, task_id: str, agent_id: str):
        """Mark task as completed."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status = 'completed', completed_at = CURRENT_TIMESTAMP
                WHERE id = ? AND owner = ?
                """,
                (task_id, agent_id)
            )

            # Verify the update succeeded
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Cannot complete task {task_id}: either task doesn't exist, "
                    f"is not owned by agent {agent_id}, or is already completed"
                )

            # Update task timing
            conn.execute(
                "UPDATE task_timing SET completed_at = CURRENT_TIMESTAMP WHERE task_id = ?",
                (task_id,)
            )

    def get_available_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get available (pending) tasks with no unsatisfied dependencies.

        Args:
            limit: Maximum number of tasks to return

        Returns:
            List of available tasks (pending, not blocked by dependencies)
        """
        rows = self.query(
            """
            SELECT t.* FROM tasks t
            WHERE t.status = 'pending'
              AND t.completed_at IS NULL
              AND NOT EXISTS (
                  -- Check if task has any dependencies on incomplete tasks
                  SELECT 1 FROM task_dependencies d
                  JOIN tasks dep_task ON d.depends_on = dep_task.id
                  WHERE d.task_id = t.id
                    AND dep_task.status != 'completed'
              )
            ORDER BY t.priority ASC, t.created_at ASC
            LIMIT ?
            """,
            (limit,)
        )
        return [dict(row) for row in rows]

    def get_agent_task(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent's current in_progress task."""
        row = self.query_one(
            "SELECT * FROM tasks WHERE owner = ? AND status = 'in_progress'",
            (agent_id,)
        )
        return dict(row) if row else None

    # Task dependency operations
    def add_dependency(self, task_id: str, depends_on: str):
        """Add a task dependency.

        Args:
            task_id: The task that has the dependency
            depends_on: The task it depends on (must complete first)

        Raises:
            ValueError: If dependency would create a cycle
        """
        with self.transaction() as conn:
            # Check for circular dependencies
            if self._would_create_cycle(task_id, depends_on):
                raise ValueError(
                    f"Cannot add dependency: would create circular dependency "
                    f"between {task_id} and {depends_on}"
                )

            # Insert dependency
            conn.execute(
                """
                INSERT OR IGNORE INTO task_dependencies (task_id, depends_on)
                VALUES (?, ?)
                """,
                (task_id, depends_on)
            )

    def remove_dependency(self, task_id: str, depends_on: str):
        """Remove a task dependency.

        Args:
            task_id: The task that has the dependency
            depends_on: The dependency to remove
        """
        self.execute(
            "DELETE FROM task_dependencies WHERE task_id = ? AND depends_on = ?",
            (task_id, depends_on)
        )

    def get_task_dependencies(self, task_id: str) -> List[str]:
        """Get list of tasks that this task depends on.

        Args:
            task_id: Task ID

        Returns:
            List of task IDs that must complete before this task
        """
        rows = self.query(
            "SELECT depends_on FROM task_dependencies WHERE task_id = ?",
            (task_id,)
        )
        return [row['depends_on'] for row in rows]

    def get_task_dependents(self, task_id: str) -> List[str]:
        """Get list of tasks that depend on this task.

        Args:
            task_id: Task ID

        Returns:
            List of task IDs that are waiting for this task to complete
        """
        rows = self.query(
            "SELECT task_id FROM task_dependencies WHERE depends_on = ?",
            (task_id,)
        )
        return [row['task_id'] for row in rows]

    def get_blocked_tasks(self) -> List[Dict[str, Any]]:
        """Get all tasks that are blocked by dependencies.

        Returns:
            List of pending tasks with incomplete dependencies
        """
        rows = self.query(
            """
            SELECT DISTINCT t.*, COUNT(d.depends_on) as blocked_by_count
            FROM tasks t
            JOIN task_dependencies d ON t.id = d.task_id
            JOIN tasks dep_task ON d.depends_on = dep_task.id
            WHERE t.status = 'pending'
              AND dep_task.status != 'completed'
            GROUP BY t.id
            ORDER BY t.priority ASC, t.created_at ASC
            """
        )
        return [dict(row) for row in rows]

    def _would_create_cycle(self, task_id: str, depends_on: str) -> bool:
        """Check if adding a dependency would create a cycle.

        Uses depth-first search to detect cycles.

        Args:
            task_id: Task to add dependency to
            depends_on: Task it would depend on

        Returns:
            True if adding this dependency would create a cycle
        """
        # If depends_on task depends on task_id (directly or indirectly),
        # adding task_id -> depends_on would create a cycle

        visited = set()
        stack = [depends_on]

        while stack:
            current = stack.pop()

            if current == task_id:
                return True  # Found a cycle

            if current in visited:
                continue

            visited.add(current)

            # Get all dependencies of current task
            deps = self.get_task_dependencies(current)
            stack.extend(deps)

        return False

    # Lock operations
    def acquire_lock(self, file_path: str, agent_id: str):
        """Acquire a file lock."""
        with self.transaction() as conn:
            # Check if file is already locked by another agent
            existing = conn.execute(
                "SELECT owner FROM locks WHERE file_path = ? AND owner != ?",
                (file_path, agent_id)
            ).fetchone()

            if existing:
                raise LockConflictError(
                    f"File {file_path} is locked by {existing['owner']}"
                )

            # Insert or update lock
            conn.execute(
                """
                INSERT INTO locks (file_path, owner)
                VALUES (?, ?)
                ON CONFLICT(file_path, owner) DO UPDATE SET acquired_at = CURRENT_TIMESTAMP
                """,
                (file_path, agent_id)
            )

            # Update file lock stats
            conn.execute(
                """
                INSERT INTO file_lock_stats (file_path, lock_count, last_locked_at, last_locked_by)
                VALUES (?, 1, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    lock_count = lock_count + 1,
                    last_locked_at = CURRENT_TIMESTAMP,
                    last_locked_by = ?
                """,
                (file_path, agent_id, agent_id)
            )

            # Track task file activity
            task = self.get_agent_task(agent_id)
            if task:
                conn.execute(
                    """
                    INSERT INTO task_file_activity (task_id, file_path, lock_acquired_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    """,
                    (task['id'], file_path)
                )

                # Update task timing (first lock)
                conn.execute(
                    """
                    UPDATE task_timing
                    SET first_lock_at = CURRENT_TIMESTAMP
                    WHERE task_id = ? AND first_lock_at IS NULL
                    """,
                    (task['id'],)
                )

    def release_lock(self, file_path: str, agent_id: str):
        """Release a file lock."""
        with self.transaction() as conn:
            # Get lock info
            lock = conn.execute(
                "SELECT acquired_at FROM locks WHERE file_path = ? AND owner = ?",
                (file_path, agent_id)
            ).fetchone()

            if not lock:
                return  # Lock doesn't exist, silently succeed

            # Calculate duration
            acquired_at = datetime.fromisoformat(lock['acquired_at'])
            duration = (datetime.now() - acquired_at).total_seconds()

            # Delete lock
            conn.execute(
                "DELETE FROM locks WHERE file_path = ? AND owner = ?",
                (file_path, agent_id)
            )

            # Update file lock stats
            conn.execute(
                """
                UPDATE file_lock_stats
                SET total_lock_duration_seconds = total_lock_duration_seconds + ?,
                    avg_lock_duration_seconds = (total_lock_duration_seconds + ?) / lock_count
                WHERE file_path = ?
                """,
                (duration, duration, file_path)
            )

            # Update task file activity
            task = self.get_agent_task(agent_id)
            if task:
                conn.execute(
                    """
                    UPDATE task_file_activity
                    SET lock_released_at = CURRENT_TIMESTAMP,
                        lock_duration_seconds = ?
                    WHERE task_id = ? AND file_path = ? AND lock_released_at IS NULL
                    """,
                    (duration, task['id'], file_path)
                )

                # Update task timing (last unlock)
                conn.execute(
                    """
                    UPDATE task_timing
                    SET last_unlock_at = CURRENT_TIMESTAMP
                    WHERE task_id = ?
                    """,
                    (task['id'],)
                )

    def get_file_locks(self, file_path: str) -> List[str]:
        """Get list of agents holding locks on a file."""
        rows = self.query(
            "SELECT owner FROM locks WHERE file_path = ?",
            (file_path,)
        )
        return [row['owner'] for row in rows]

    def get_agent_locks(self, agent_id: str) -> List[str]:
        """Get list of files locked by an agent."""
        rows = self.query(
            "SELECT file_path FROM locks WHERE owner = ?",
            (agent_id,)
        )
        return [row['file_path'] for row in rows]

    # Audit logging
    def log_operation(
        self,
        correlation_id: str,
        operation: str,
        agent_id: str = None,
        entity_type: str = None,
        entity_id: str = None,
        request_params: Dict = None,
        success: bool = True,
        error_code: str = None,
        error_message: str = None,
        duration_ms: int = None,
        stack_trace: str = None
    ):
        """Log an operation to the audit log."""
        self.execute(
            """
            INSERT INTO audit_log (
                correlation_id, operation, agent_id, entity_type, entity_id,
                request_params, success, error_code, error_message,
                duration_ms, stack_trace
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                correlation_id, operation, agent_id, entity_type, entity_id,
                json.dumps(request_params or {}), success, error_code, error_message,
                duration_ms, stack_trace
            )
        )

    # State import/export
    def export_to_json(self, output_path: str):
        """Export current state to JSON file (backward compatibility)."""
        state = {
            "agents": {},
            "locks": {},
            "tasks": {}
        }

        # Export agents
        agents = self.query("SELECT * FROM agents")
        for agent in agents:
            state["agents"][agent['id']] = {
                "pid": agent['pid'],
                "registered_at": agent['registered_at'],
                "last_heartbeat": agent['last_heartbeat']
            }

        # Export locks
        locks = self.query("SELECT * FROM locks")
        for lock in locks:
            if lock['file_path'] not in state["locks"]:
                state["locks"][lock['file_path']] = []
            state["locks"][lock['file_path']].append({
                "owner": lock['owner'],
                "acquired_at": lock['acquired_at']
            })

        # Export tasks
        tasks = self.query("SELECT * FROM tasks WHERE status != 'deleted'")
        for task in tasks:
            state["tasks"][task['id']] = {
                "subject": task['subject'],
                "description": task['description'],
                "activeForm": task['active_form'],
                "priority": task['priority'],
                "status": task['status'],
                "owner": task['owner'],
                "created_at": task['created_at'],
                "started_at": task['started_at'],
                "completed_at": task['completed_at']
            }

        # Write atomically
        tmp_path = output_path + ".tmp"
        with open(tmp_path, 'w') as f:
            json.dump(state, f, indent=2)
        os.rename(tmp_path, output_path)

    def import_from_json(self, json_path: str):
        """
        Import state from JSON file with validation.

        SECURITY FIX (code-crit-unsafe-deserial-09): Added type validation
        and data sanitization to prevent corruption from malformed JSON.

        Args:
            json_path: Path to JSON file to import

        Raises:
            ValueError: If JSON structure or data types are invalid
        """
        with open(json_path) as f:
            state = json.load(f)

        # Validate top-level structure
        if not isinstance(state, dict):
            raise ValueError("JSON must be a dictionary")

        # Validate agents structure
        agents_data = state.get("agents", {})
        if not isinstance(agents_data, dict):
            raise ValueError("'agents' must be a dictionary")

        for agent_id, agent_data in agents_data.items():
            if not isinstance(agent_id, str):
                raise ValueError(f"Agent ID must be string, got {type(agent_id).__name__}")
            if not isinstance(agent_data, dict):
                raise ValueError(f"Agent data must be dict, got {type(agent_data).__name__}")
            if 'pid' not in agent_data:
                raise ValueError(f"Agent {agent_id} missing required field 'pid'")
            if not isinstance(agent_data['pid'], int) or agent_data['pid'] <= 0:
                raise ValueError(f"Agent {agent_id} pid must be positive integer")

        # Validate tasks structure
        tasks_data = state.get("tasks", {})
        if not isinstance(tasks_data, dict):
            raise ValueError("'tasks' must be a dictionary")

        for task_id, task_data in tasks_data.items():
            if not isinstance(task_id, str):
                raise ValueError(f"Task ID must be string, got {type(task_id).__name__}")
            if not isinstance(task_data, dict):
                raise ValueError(f"Task data must be dict, got {type(task_data).__name__}")
            if 'subject' not in task_data:
                raise ValueError(f"Task {task_id} missing required field 'subject'")
            if 'description' not in task_data:
                raise ValueError(f"Task {task_id} missing required field 'description'")

        # Validate locks structure
        locks_data = state.get("locks", {})
        if not isinstance(locks_data, dict):
            raise ValueError("'locks' must be a dictionary")

        with self.transaction() as conn:
            # Import agents
            for agent_id, agent_data in state.get("agents", {}).items():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO agents (id, pid, registered_at, last_heartbeat)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        agent_id,
                        agent_data['pid'],
                        agent_data.get('registered_at'),
                        agent_data.get('last_heartbeat')
                    )
                )

            # Import tasks
            agents_in_db = set(state.get("agents", {}).keys())
            for task_id, task_data in state.get("tasks", {}).items():
                # Set owner to NULL if agent doesn't exist
                owner = task_data.get('owner')
                if owner and owner not in agents_in_db:
                    owner = None

                # Set status to pending if owner is NULL (task was in_progress but agent is gone)
                status = task_data.get('status', 'pending')
                if status == 'in_progress' and not owner:
                    status = 'pending'

                conn.execute(
                    """
                    INSERT OR REPLACE INTO tasks (
                        id, subject, description, active_form, priority, status, owner,
                        created_at, started_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        task_data['subject'],
                        task_data['description'],
                        task_data.get('activeForm'),
                        task_data.get('priority', 3),
                        status,
                        owner,
                        task_data.get('created_at'),
                        task_data.get('started_at'),
                        task_data.get('completed_at')
                    )
                )

            # Import locks
            for file_path, lock_list in state.get("locks", {}).items():
                for lock_data in lock_list:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO locks (file_path, owner, acquired_at)
                        VALUES (?, ?, ?)
                        """,
                        (
                            file_path,
                            lock_data['owner'],
                            lock_data.get('acquired_at')
                        )
                    )


class LockConflictError(Exception):
    """Raised when a lock cannot be acquired due to conflict."""
    pass
