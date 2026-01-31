"""
Background tasks for coordination service.

Handles periodic cleanup, monitoring, and maintenance tasks.
"""

import os
import signal
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class BackgroundTasks:
    """Manages background maintenance tasks."""

    def __init__(self, db, config: dict = None):
        """Initialize background tasks.

        Args:
            db: Database instance
            config: Configuration dictionary
        """
        self.db = db
        self.config = config or {}
        self.running = False
        self.threads = []

    def start(self):
        """Start all background tasks."""
        self.running = True

        # Start dead agent cleanup (every 60s)
        cleanup_thread = threading.Thread(
            target=self._run_periodic,
            args=(self._cleanup_dead_agents, 60),
            daemon=True
        )
        cleanup_thread.start()
        self.threads.append(cleanup_thread)

        # Start metrics aggregation (every 60s)
        metrics_thread = threading.Thread(
            target=self._run_periodic,
            args=(self._aggregate_metrics, 60),
            daemon=True
        )
        metrics_thread.start()
        self.threads.append(metrics_thread)

        # Start JSON export (every 300s for backward compatibility)
        export_thread = threading.Thread(
            target=self._run_periodic,
            args=(self._export_state, 300),
            daemon=True
        )
        export_thread.start()
        self.threads.append(export_thread)

        # Start database backup (every 3600s)
        backup_thread = threading.Thread(
            target=self._run_periodic,
            args=(self._backup_database, 3600),
            daemon=True
        )
        backup_thread.start()
        self.threads.append(backup_thread)

    def stop(self):
        """Stop all background tasks."""
        self.running = False

        # Wait for threads to finish
        for thread in self.threads:
            thread.join(timeout=5)

    def _run_periodic(self, task_func, interval_seconds: int):
        """Run a task periodically.

        Args:
            task_func: Task function to run
            interval_seconds: Interval in seconds
        """
        while self.running:
            try:
                task_func()
            except Exception as e:
                print(f"Background task error: {e}")

            # Sleep in small increments for faster shutdown
            for _ in range(interval_seconds):
                if not self.running:
                    break
                time.sleep(1)

    def _cleanup_dead_agents(self):
        """Clean up dead agents and orphaned resources."""
        # Get stale agents (no heartbeat in 5 minutes)
        timeout = self.config.get('agent_timeout', 300)
        stale_agents = self.db.get_stale_agents(timeout)

        for agent_id in stale_agents:
            try:
                # Check if process is still running
                agent = self.db.query_one(
                    "SELECT pid FROM agents WHERE id = ?",
                    (agent_id,)
                )

                if agent:
                    pid = agent['pid']
                    is_running = self._is_process_running(pid)

                    if not is_running:
                        print(f"Cleaning up dead agent: {agent_id} (PID {pid})")

                        # Log cleanup event
                        self.db.execute(
                            """
                            INSERT INTO event_log (event_type, entity_type, entity_id, triggered_by, reason)
                            VALUES ('agent_cleanup', 'agent', ?, 'system', 'Process not running')
                            """,
                            (agent_id,)
                        )

                        # Unregister agent (releases locks and tasks)
                        self.db.unregister_agent(agent_id)

            except Exception as e:
                print(f"Error cleaning up agent {agent_id}: {e}")

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is running.

        Args:
            pid: Process ID

        Returns:
            True if process is running
        """
        try:
            # Send signal 0 to check if process exists
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _aggregate_metrics(self):
        """Aggregate velocity and performance metrics."""
        try:
            # Count active entities
            active_agents = self.db.query_one(
                "SELECT COUNT(*) as count FROM agents"
            )['count']

            pending_tasks = self.db.query_one(
                "SELECT COUNT(*) as count FROM tasks WHERE status='pending'"
            )['count']

            in_progress_tasks = self.db.query_one(
                "SELECT COUNT(*) as count FROM tasks WHERE status='in_progress'"
            )['count']

            # Completed tasks today
            completed_today = self.db.query_one(
                """
                SELECT COUNT(*) as count FROM tasks
                WHERE status='completed' AND DATE(completed_at) = DATE('now')
                """
            )['count']

            # Average task duration (last 24 hours)
            avg_duration = self.db.query_one(
                """
                SELECT AVG(CAST((julianday(completed_at) - julianday(started_at)) * 1440 AS REAL)) as avg_mins
                FROM tasks
                WHERE status='completed' AND completed_at >= datetime('now', '-1 day')
                """
            )['avg_mins'] or 0

            # Tasks per hour (last 24 hours)
            tasks_per_hour = self.db.query_one(
                """
                SELECT COUNT(*) / 24.0 as rate FROM tasks
                WHERE status='completed' AND completed_at >= datetime('now', '-1 day')
                """
            )['rate'] or 0

            # Lock contention rate (locks that had to wait)
            lock_contention = self.db.query_one(
                """
                SELECT
                    CAST(SUM(contention_count) AS REAL) / NULLIF(SUM(lock_count), 0) as rate
                FROM file_lock_stats
                """
            )['rate'] or 0

            # Per-agent stats
            agent_stats = {}
            agents = self.db.query("SELECT id FROM agents")
            for agent in agents:
                agent_id = agent['id']
                completed = self.db.query_one(
                    """
                    SELECT COUNT(*) as count FROM tasks
                    WHERE owner = ? AND status='completed' AND completed_at >= datetime('now', '-1 day')
                    """,
                    (agent_id,)
                )['count']

                agent_stats[agent_id] = {
                    "completed_today": completed
                }

            # Insert metrics snapshot
            import json
            self.db.execute(
                """
                INSERT INTO metrics_snapshots (
                    active_agents, pending_tasks, in_progress_tasks, completed_tasks_today,
                    avg_task_duration_mins, tasks_per_hour, lock_contention_rate,
                    agent_stats
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    active_agents, pending_tasks, in_progress_tasks, completed_today,
                    round(avg_duration, 2), round(tasks_per_hour, 2), round(lock_contention, 4),
                    json.dumps(agent_stats)
                )
            )

        except Exception as e:
            print(f"Error aggregating metrics: {e}")

    def _export_state(self):
        """Export state to JSON for backward compatibility."""
        try:
            output_path = self.config.get('state_json_path', '.claude-coord/state.json')
            self.db.export_to_json(output_path)
        except Exception as e:
            print(f"Error exporting state: {e}")

    def _backup_database(self):
        """Create database backup."""
        try:
            # Create backups directory
            backup_dir = Path('.claude-coord/backups')
            backup_dir.mkdir(exist_ok=True)

            # Generate backup filename
            timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            backup_path = backup_dir / f"coordination-{timestamp}.db"

            # Copy database file
            import shutil
            shutil.copy2(self.db.db_path, backup_path)

            # Keep only last 7 days of backups
            cutoff = datetime.now() - timedelta(days=7)
            for backup_file in backup_dir.glob("coordination-*.db"):
                try:
                    # Extract timestamp from filename
                    parts = backup_file.stem.split('-')
                    if len(parts) >= 3:
                        file_date = datetime.strptime(
                            f"{parts[1]}-{parts[2]}",
                            "%Y%m%d-%H%M%S"
                        )
                        if file_date < cutoff:
                            backup_file.unlink()
                except Exception:
                    pass  # Skip files with invalid names

        except Exception as e:
            print(f"Error backing up database: {e}")
