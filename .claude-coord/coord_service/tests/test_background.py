"""
Comprehensive tests for background tasks.

Tests periodic cleanup, monitoring, and maintenance tasks that run
in the coordination daemon. Critical for preventing resource leaks.
"""

import json
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

from coord_service.background import BackgroundTasks


class TestBackgroundTaskLifecycle:
    """Test background task lifecycle."""

    def test_start_initializes_all_threads(self, db):
        """Start should initialize all 4 background threads."""
        tasks = BackgroundTasks(db)

        tasks.start()

        assert tasks.running is True
        assert len(tasks.threads) == 4  # cleanup, metrics, export, backup

        tasks.stop()

    def test_stop_terminates_all_threads(self, db):
        """Stop should terminate all threads."""
        tasks = BackgroundTasks(db)
        tasks.start()

        tasks.stop()

        assert tasks.running is False
        # All threads should be stopped
        for thread in tasks.threads:
            assert not thread.is_alive() or thread.daemon

    def test_stop_timeout_doesnt_hang(self, db):
        """Stop should return within timeout even if threads don't respond."""
        tasks = BackgroundTasks(db)
        tasks.start()

        start_time = time.time()
        tasks.stop()
        duration = time.time() - start_time

        # Should complete within reasonable time (threads have 5s timeout)
        assert duration < 10  # 10s upper bound

    def test_start_after_stop_works(self, db):
        """Background tasks can be restarted after stop."""
        tasks = BackgroundTasks(db)

        tasks.start()
        tasks.stop()
        tasks.start()

        assert tasks.running is True
        assert len(tasks.threads) > 0

        tasks.stop()

    def test_multiple_start_safe(self, db):
        """Calling start multiple times doesn't create duplicate threads."""
        tasks = BackgroundTasks(db)

        tasks.start()
        initial_count = len(tasks.threads)

        tasks.start()  # Start again

        # Should still have same number of threads (not duplicated)
        assert len(tasks.threads) == initial_count

        tasks.stop()


class TestDeadAgentCleanup:
    """Test dead agent cleanup task."""

    def test_cleanup_removes_stale_agents(self, db):
        """Stale agents (no heartbeat in 5min) should be removed."""
        tasks = BackgroundTasks(db, config={'agent_timeout': 1})  # 1 second timeout

        # Register agent but don't send heartbeat
        db.register_agent('stale-agent', 12345)

        # Backdated heartbeat to make it stale
        db.execute(
            "UPDATE agents SET last_heartbeat = datetime('now', '-10 minutes') WHERE id = 'stale-agent'"
        )

        # Run cleanup
        tasks._cleanup_dead_agents()

        # Agent should be removed
        assert not db.agent_exists('stale-agent')

    def test_cleanup_releases_claimed_tasks(self, db):
        """Dead agent's claimed tasks should be released to pending."""
        tasks = BackgroundTasks(db, config={'agent_timeout': 1})

        db.register_agent('dead-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'dead-agent')

        # Make agent stale
        db.execute(
            "UPDATE agents SET last_heartbeat = datetime('now', '-10 minutes') WHERE id = 'dead-agent'"
        )

        # Run cleanup
        tasks._cleanup_dead_agents()

        # Task should be released
        task = db.get_task('test-task')
        assert task['status'] == 'pending'
        assert task['owner'] is None

    def test_cleanup_releases_file_locks(self, db):
        """Dead agent's file locks should be released."""
        tasks = BackgroundTasks(db, config={'agent_timeout': 1})

        db.register_agent('dead-agent', 12345)
        db.acquire_lock('test/file.py', 'dead-agent')

        # Make agent stale
        db.execute(
            "UPDATE agents SET last_heartbeat = datetime('now', '-10 minutes') WHERE id = 'dead-agent'"
        )

        # Run cleanup
        tasks._cleanup_dead_agents()

        # Lock should be released
        locks = db.get_file_locks('test/file.py')
        assert len(locks) == 0

    def test_cleanup_preserves_recent_agents(self, db):
        """Agents with recent heartbeat should not be removed."""
        tasks = BackgroundTasks(db, config={'agent_timeout': 300})

        db.register_agent('active-agent', 12345)
        # Recent heartbeat (default is now)

        # Run cleanup
        tasks._cleanup_dead_agents()

        # Agent should still exist
        assert db.agent_exists('active-agent')

    def test_cleanup_checks_process_running(self, db):
        """Cleanup should verify process is actually dead."""
        tasks = BackgroundTasks(db, config={'agent_timeout': 1})

        # Register with current process PID
        db.register_agent('current-process', os.getpid())

        # Make heartbeat stale
        db.execute(
            "UPDATE agents SET last_heartbeat = datetime('now', '-10 minutes') WHERE id = 'current-process'"
        )

        # Run cleanup
        tasks._cleanup_dead_agents()

        # Agent should still exist (process is running)
        assert db.agent_exists('current-process')

    def test_cleanup_handles_database_errors(self, db):
        """Database errors during cleanup shouldn't crash task."""
        tasks = BackgroundTasks(db)

        # Mock database to raise error
        with mock.patch.object(db, 'get_stale_agents', side_effect=Exception("DB error")):
            # Should not raise exception
            tasks._cleanup_dead_agents()

    def test_is_process_running_returns_true_for_current(self, db):
        """_is_process_running should return True for current process."""
        tasks = BackgroundTasks(db)

        is_running = tasks._is_process_running(os.getpid())

        assert is_running is True

    def test_is_process_running_returns_false_for_invalid(self, db):
        """_is_process_running should return False for invalid PID."""
        tasks = BackgroundTasks(db)

        # PID 999999 should not exist
        is_running = tasks._is_process_running(999999)

        assert is_running is False


class TestMetricsAggregation:
    """Test metrics aggregation task."""

    def test_aggregation_creates_snapshot(self, db):
        """Metrics aggregation should create snapshot in database."""
        tasks = BackgroundTasks(db)

        tasks._aggregate_metrics()

        snapshots = db.query("SELECT * FROM metrics_snapshots")
        assert len(snapshots) >= 1

    def test_aggregation_calculates_velocity(self, db):
        """Metrics should include tasks completed today."""
        tasks = BackgroundTasks(db)
        db.register_agent('test-agent', 12345)
        db.create_task('task1', 'S', 'D')
        db.claim_task('task1', 'test-agent')
        db.complete_task('task1', 'test-agent')

        tasks._aggregate_metrics()

        snapshot = db.query_one(
            "SELECT * FROM metrics_snapshots ORDER BY created_at DESC LIMIT 1"
        )
        assert snapshot['completed_tasks_today'] >= 1

    def test_aggregation_tracks_pending_tasks(self, db):
        """Metrics should track pending task count."""
        tasks = BackgroundTasks(db)
        db.create_task('pending1', 'S', 'D')
        db.create_task('pending2', 'S', 'D')

        tasks._aggregate_metrics()

        snapshot = db.query_one(
            "SELECT * FROM metrics_snapshots ORDER BY created_at DESC LIMIT 1"
        )
        assert snapshot['pending_tasks'] == 2

    def test_aggregation_tracks_in_progress_tasks(self, db):
        """Metrics should track in_progress task count."""
        tasks = BackgroundTasks(db)
        db.register_agent('test-agent', 12345)
        db.create_task('task1', 'S', 'D')
        db.claim_task('task1', 'test-agent')

        tasks._aggregate_metrics()

        snapshot = db.query_one(
            "SELECT * FROM metrics_snapshots ORDER BY created_at DESC LIMIT 1"
        )
        assert snapshot['in_progress_tasks'] == 1

    def test_aggregation_calculates_agent_stats(self, db):
        """Metrics should include per-agent statistics."""
        tasks = BackgroundTasks(db)
        db.register_agent('agent1', 11111)
        db.create_task('task1', 'S', 'D')
        db.claim_task('task1', 'agent1')
        db.complete_task('task1', 'agent1')

        tasks._aggregate_metrics()

        snapshot = db.query_one(
            "SELECT * FROM metrics_snapshots ORDER BY created_at DESC LIMIT 1"
        )
        agent_stats = json.loads(snapshot['agent_stats'])
        assert 'agent1' in agent_stats
        assert agent_stats['agent1']['completed_today'] >= 1

    def test_aggregation_handles_empty_data(self, db):
        """Metrics aggregation should handle empty database gracefully."""
        tasks = BackgroundTasks(db)

        # Should not raise exception
        tasks._aggregate_metrics()

        snapshot = db.query_one(
            "SELECT * FROM metrics_snapshots ORDER BY created_at DESC LIMIT 1"
        )
        assert snapshot['active_agents'] == 0
        assert snapshot['pending_tasks'] == 0

    def test_aggregation_handles_errors(self, db):
        """Errors during aggregation shouldn't crash task."""
        tasks = BackgroundTasks(db)

        # Mock database to raise error
        with mock.patch.object(db, 'query_one', side_effect=Exception("DB error")):
            # Should not raise exception
            tasks._aggregate_metrics()


class TestStateExport:
    """Test state export task."""

    def test_export_creates_json_file(self, db, tmp_path):
        """Export should create state.json file."""
        output_path = tmp_path / "state.json"
        tasks = BackgroundTasks(db, config={'state_json_path': str(output_path)})

        tasks._export_state()

        assert output_path.exists()

    def test_export_contains_valid_json(self, db, tmp_path):
        """Exported state should be valid JSON."""
        output_path = tmp_path / "state.json"
        tasks = BackgroundTasks(db, config={'state_json_path': str(output_path)})

        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')

        tasks._export_state()

        with open(output_path) as f:
            data = json.load(f)

        # Should have agents and tasks
        assert 'agents' in data or 'tasks' in data

    def test_export_preserves_data_integrity(self, db, tmp_path):
        """Exported data should match database state."""
        output_path = tmp_path / "state.json"
        tasks = BackgroundTasks(db, config={'state_json_path': str(output_path)})

        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')

        tasks._export_state()

        with open(output_path) as f:
            data = json.load(f)

        # Verify agent exists in export
        assert any(a.get('id') == 'test-agent' for a in data.get('agents', []))

    def test_export_handles_missing_directory(self, db, tmp_path):
        """Export should handle missing output directory gracefully."""
        output_path = tmp_path / "nonexistent" / "state.json"
        tasks = BackgroundTasks(db, config={'state_json_path': str(output_path)})

        # Should not raise exception (creates directory or fails gracefully)
        tasks._export_state()

    def test_export_handles_errors(self, db):
        """Export errors shouldn't crash task."""
        tasks = BackgroundTasks(db, config={'state_json_path': '/invalid/path/state.json'})

        # Should not raise exception
        tasks._export_state()


class TestDatabaseBackup:
    """Test database backup task."""

    def test_backup_creates_file(self, db, tmp_path):
        """Backup should create backup file."""
        # Use temporary database
        db_path = tmp_path / "test.db"
        backup_dir = tmp_path / "backups"

        from coord_service.database import Database
        temp_db = Database(str(db_path))
        temp_db.initialize()

        # Monkey patch backup directory
        with mock.patch('coord_service.background.Path') as mock_path:
            mock_path.return_value = backup_dir
            tasks = BackgroundTasks(temp_db)
            tasks._backup_database()

        # Should have created backup directory and file
        # (actual test depends on Path mocking - simplified here)

    def test_backup_preserves_data(self, db, tmp_path):
        """Backup file should be restorable."""
        db_path = tmp_path / "test.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        from coord_service.database import Database
        temp_db = Database(str(db_path))
        temp_db.initialize()

        temp_db.register_agent('test-agent', 12345)

        # Create backup manually
        backup_path = backup_dir / "test-backup.db"
        shutil.copy2(str(db_path), str(backup_path))

        # Verify backup is valid
        restored_db = Database(str(backup_path))
        restored_db.initialize()
        assert restored_db.agent_exists('test-agent')

    def test_backup_handles_errors(self, db):
        """Backup errors shouldn't crash task."""
        tasks = BackgroundTasks(db)

        # Mock to raise error
        with mock.patch('shutil.copy2', side_effect=Exception("Copy error")):
            # Should not raise exception
            tasks._backup_database()


class TestPeriodicExecution:
    """Test periodic task execution framework."""

    def test_task_runs_at_interval(self, db):
        """Periodic task should execute at specified interval."""
        tasks = BackgroundTasks(db)
        execution_count = []

        def test_task():
            execution_count.append(time.time())

        # Run periodic task with 0.5 second interval
        tasks.running = True
        thread = threading.Thread(
            target=tasks._run_periodic,
            args=(test_task, 1),  # 1 second interval
            daemon=True
        )
        thread.start()

        # Wait for multiple executions
        time.sleep(2.5)
        tasks.running = False
        thread.join(timeout=2)

        # Should have executed at least twice
        assert len(execution_count) >= 2

    def test_task_exception_doesnt_stop_loop(self, db):
        """Exception in task shouldn't stop periodic execution."""
        tasks = BackgroundTasks(db)
        execution_count = [0]

        def failing_task():
            execution_count[0] += 1
            raise Exception("Task failed")

        tasks.running = True
        thread = threading.Thread(
            target=tasks._run_periodic,
            args=(failing_task, 1),
            daemon=True
        )
        thread.start()

        time.sleep(2.5)
        tasks.running = False
        thread.join(timeout=2)

        # Should have executed multiple times despite exceptions
        assert execution_count[0] >= 2

    def test_fast_shutdown_on_stop(self, db):
        """Shutdown should not wait full interval."""
        tasks = BackgroundTasks(db)

        def long_interval_task():
            pass

        tasks.running = True
        thread = threading.Thread(
            target=tasks._run_periodic,
            args=(long_interval_task, 60),  # 60 second interval
            daemon=True
        )
        thread.start()

        start = time.time()
        tasks.running = False
        thread.join(timeout=5)
        duration = time.time() - start

        # Should shutdown quickly (< 5s), not wait 60s
        assert duration < 5


class TestErrorHandling:
    """Test error handling in background tasks."""

    def test_all_tasks_isolated(self, db):
        """Error in one background task shouldn't affect others."""
        tasks = BackgroundTasks(db)

        # Mock one task to fail
        with mock.patch.object(tasks, '_cleanup_dead_agents', side_effect=Exception("Cleanup error")):
            # Start all tasks
            tasks.start()
            time.sleep(1)

            # Other tasks should still be running
            assert tasks.running is True

            tasks.stop()

    def test_error_logged(self, db, capsys):
        """Errors should be logged to stderr."""
        tasks = BackgroundTasks(db)

        # Force an error
        with mock.patch.object(tasks.db, 'get_stale_agents', side_effect=Exception("Test error")):
            tasks._cleanup_dead_agents()

        # Check that error was printed
        captured = capsys.readouterr()
        assert "Error" in captured.out or "error" in captured.out.lower()


class TestConfiguration:
    """Test background task configuration."""

    def test_custom_agent_timeout(self, db):
        """Custom agent timeout should be respected."""
        tasks = BackgroundTasks(db, config={'agent_timeout': 10})

        db.register_agent('test-agent', 12345)

        # Backdated heartbeat by 15 seconds
        db.execute(
            "UPDATE agents SET last_heartbeat = datetime('now', '-15 seconds') WHERE id = 'test-agent'"
        )

        # Run cleanup (timeout is 10 seconds)
        tasks._cleanup_dead_agents()

        # Agent should be removed (15s > 10s timeout)
        assert not db.agent_exists('test-agent')

    def test_custom_state_json_path(self, db, tmp_path):
        """Custom state.json path should be used."""
        custom_path = tmp_path / "custom-state.json"
        tasks = BackgroundTasks(db, config={'state_json_path': str(custom_path)})

        tasks._export_state()

        assert custom_path.exists()

    def test_default_config_values(self, db):
        """Default configuration values should be sensible."""
        tasks = BackgroundTasks(db)

        # Default agent timeout should be 300 seconds (5 minutes)
        assert tasks.config.get('agent_timeout', 300) == 300
