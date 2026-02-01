"""
Operation handlers for coordination commands.

Implements all coordination operations with validation and audit logging.
"""

import os
import time
import traceback
import uuid
from typing import Any, Dict, List

from .database import Database, LockConflictError
from .validator import StateValidator, ValidationErrors, InvariantViolations


class OperationHandler:
    """Handles coordination operations with validation and logging."""

    def __init__(self, db: Database):
        """Initialize handler.

        Args:
            db: Database instance
        """
        self.db = db
        self.validator = StateValidator(db)

    def execute(self, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an operation with validation and audit logging.

        Args:
            operation: Operation name
            params: Operation parameters

        Returns:
            Operation result

        Raises:
            Exception: If operation fails
        """
        correlation_id = str(uuid.uuid4())
        start_time = time.time()
        agent_id = params.get('agent_id')

        try:
            # Dispatch to operation handler
            method = getattr(self, f"op_{operation}", None)
            if not method:
                raise ValueError(f"Unknown operation: {operation}")

            # Execute operation
            result = method(params)

            # Log success
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.log_operation(
                correlation_id=correlation_id,
                operation=operation,
                agent_id=agent_id,
                request_params=params,
                success=True,
                duration_ms=duration_ms
            )

            # Validate invariants (post-operation)
            self.validator.validate_post_operation()

            return result

        except ValidationErrors as e:
            # Validation errors
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.log_operation(
                correlation_id=correlation_id,
                operation=operation,
                agent_id=agent_id,
                request_params=params,
                success=False,
                error_code="VALIDATION_ERROR",
                error_message=str(e),
                duration_ms=duration_ms
            )
            raise

        except Exception as e:
            # Other errors
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.log_operation(
                correlation_id=correlation_id,
                operation=operation,
                agent_id=agent_id,
                request_params=params,
                success=False,
                error_code=type(e).__name__,
                error_message=str(e),
                duration_ms=duration_ms,
                stack_trace=traceback.format_exc()
            )
            raise

    # Agent operations
    def op_register(self, params: Dict) -> Dict:
        """Register a new agent."""
        agent_id = params['agent_id']
        pid = params['pid']
        metadata = params.get('metadata', {})

        self.db.register_agent(agent_id, pid, metadata)

        return {"status": "registered", "agent_id": agent_id}

    def op_unregister(self, params: Dict) -> Dict:
        """Unregister an agent."""
        agent_id = params['agent_id']

        self.db.unregister_agent(agent_id)

        return {"status": "unregistered", "agent_id": agent_id}

    def op_heartbeat(self, params: Dict) -> Dict:
        """Update agent heartbeat."""
        agent_id = params['agent_id']

        self.db.update_heartbeat(agent_id)

        return {"status": "ok"}

    # Task operations
    def op_task_create(self, params: Dict) -> Dict:
        """Create a new task."""
        task_id = params['task_id']
        subject = params['subject']
        description = params['description']
        priority = params.get('priority', 3)
        active_form = params.get('active_form')
        spec_path = params.get('spec_path')
        metadata = params.get('metadata', {})

        # Validate task creation
        self.validator.validate_task_create(
            task_id, subject, description, priority, spec_path
        )

        # Create task
        self.db.create_task(
            task_id, subject, description, priority,
            active_form, spec_path, metadata
        )

        return {"status": "created", "task_id": task_id}

    def op_task_claim(self, params: Dict) -> Dict:
        """Claim a task."""
        agent_id = params['agent_id']
        task_id = params['task_id']

        # Validate claim
        self.validator.validate_task_claim(agent_id, task_id)

        # Claim task
        self.db.claim_task(task_id, agent_id)

        return {"status": "claimed", "task_id": task_id, "agent_id": agent_id}

    def op_task_complete(self, params: Dict) -> Dict:
        """Complete a task."""
        agent_id = params['agent_id']
        task_id = params['task_id']

        # Complete task
        self.db.complete_task(task_id, agent_id)

        return {"status": "completed", "task_id": task_id}

    def op_task_get(self, params: Dict) -> Dict:
        """Get task details."""
        task_id = params['task_id']

        task = self.db.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        return {"task": task}

    def op_task_list(self, params: Dict) -> Dict:
        """List available tasks."""
        limit = params.get('limit', 10)

        tasks = self.db.get_available_tasks(limit)

        return {"tasks": tasks}

    # Lock operations
    def op_lock_acquire(self, params: Dict) -> Dict:
        """Acquire a file lock."""
        agent_id = params['agent_id']
        file_path = params['file_path']

        # Validate lock acquisition
        self.validator.validate_lock_acquire(file_path, agent_id)

        # Acquire lock
        try:
            self.db.acquire_lock(file_path, agent_id)
        except LockConflictError as e:
            raise ValueError(str(e))

        return {"status": "locked", "file_path": file_path, "agent_id": agent_id}

    def op_lock_release(self, params: Dict) -> Dict:
        """Release a file lock."""
        agent_id = params['agent_id']
        file_path = params['file_path']

        # Release lock
        self.db.release_lock(file_path, agent_id)

        return {"status": "unlocked", "file_path": file_path}

    def op_lock_list(self, params: Dict) -> Dict:
        """List agent's locks."""
        agent_id = params['agent_id']

        locks = self.db.get_agent_locks(agent_id)

        return {"locks": locks}

    # Query operations
    def op_status(self, params: Dict) -> Dict:
        """Get service status."""
        # Count entities
        agents = self.db.query("SELECT COUNT(*) as count FROM agents")[0]['count']
        pending = self.db.query("SELECT COUNT(*) as count FROM tasks WHERE status='pending'")[0]['count']
        in_progress = self.db.query("SELECT COUNT(*) as count FROM tasks WHERE status='in_progress'")[0]['count']
        completed = self.db.query("SELECT COUNT(*) as count FROM tasks WHERE status='completed'")[0]['count']
        locks = self.db.query("SELECT COUNT(*) as count FROM locks")[0]['count']

        # Check for data corruption (tasks with completed_at but wrong status)
        corrupted_tasks = self.db.query(
            """
            SELECT id, status, completed_at
            FROM tasks
            WHERE completed_at IS NOT NULL AND status != 'completed'
            ORDER BY completed_at DESC
            LIMIT 10
            """
        )

        result = {
            "status": "running",
            "agents": agents,
            "tasks": {
                "pending": pending,
                "in_progress": in_progress,
                "completed": completed
            },
            "locks": locks
        }

        # Add corruption warning if found
        if corrupted_tasks:
            result["warnings"] = {
                "corrupted_tasks": len(corrupted_tasks),
                "message": f"Found {len(corrupted_tasks)} corrupted tasks (completed_at set but status != 'completed')",
                "sample_ids": [t['id'] for t in corrupted_tasks[:5]]
            }

        return result

    def op_velocity(self, params: Dict) -> Dict:
        """Get velocity metrics."""
        period = params.get('period', '1 hour')

        # Get recent completions
        query = """
            SELECT
                COUNT(*) as completed_count,
                AVG(CAST((julianday(completed_at) - julianday(started_at)) * 1440 AS REAL)) as avg_duration_mins
            FROM tasks
            WHERE status = 'completed'
              AND completed_at >= datetime('now', '-' || ?)
        """

        result = self.db.query_one(query, (period,))

        # Calculate tasks per hour
        if period.endswith('hour'):
            hours = int(period.split()[0])
        elif period.endswith('day'):
            hours = int(period.split()[0]) * 24
        else:
            hours = 1

        tasks_per_hour = (result['completed_count'] or 0) / max(hours, 1)

        return {
            "period": period,
            "completed_tasks": result['completed_count'] or 0,
            "avg_duration_mins": round(result['avg_duration_mins'] or 0, 1),
            "tasks_per_hour": round(tasks_per_hour, 1)
        }

    def op_file_hotspots(self, params: Dict) -> Dict:
        """Get file lock hotspots."""
        limit = params.get('limit', 10)

        hotspots = self.db.query(
            """
            SELECT
                file_path,
                lock_count,
                ROUND(avg_lock_duration_seconds / 60, 1) as avg_duration_mins,
                contention_count,
                last_locked_by
            FROM file_lock_stats
            ORDER BY lock_count DESC
            LIMIT ?
            """,
            (limit,)
        )

        return {
            "hotspots": [dict(row) for row in hotspots]
        }

    def op_task_timing(self, params: Dict) -> Dict:
        """Get task timing breakdown."""
        task_id = params['task_id']

        timing = self.db.query_one(
            "SELECT * FROM task_timing WHERE task_id = ?",
            (task_id,)
        )

        if not timing:
            raise ValueError(f"No timing data for task {task_id}")

        # Get files worked on
        files = self.db.query(
            """
            SELECT
                file_path,
                ROUND(lock_duration_seconds, 1) as lock_duration_secs
            FROM task_file_activity
            WHERE task_id = ?
            ORDER BY lock_duration_seconds DESC
            """,
            (task_id,)
        )

        return {
            "timing": dict(timing),
            "files": [dict(row) for row in files]
        }

    def op_export_json(self, params: Dict) -> Dict:
        """Export state to JSON file."""
        output_path = params.get('output_path', '.claude-coord/state.json')

        self.db.export_to_json(output_path)

        return {"status": "exported", "path": output_path}

    def op_import_json(self, params: Dict) -> Dict:
        """Import state from JSON file."""
        json_path = params['json_path']

        if not os.path.exists(json_path):
            raise ValueError(f"File not found: {json_path}")

        self.db.import_from_json(json_path)

        return {"status": "imported", "path": json_path}
