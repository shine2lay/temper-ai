"""
Comprehensive daemon crash recovery tests.

Tests daemon behavior during crashes, restarts, and recovery scenarios.
Critical for ensuring no data loss and consistent agent operation.
"""

import os
import signal
import tempfile
import threading
import time
import unittest
from pathlib import Path
import sys

# Add coord_service to path
coord_service_path = Path(__file__).parent.parent.parent / '.claude-coord'
sys.path.insert(0, str(coord_service_path))

from coord_service.daemon import CoordinationDaemon
from coord_service.client import CoordinationClient
from coord_service.database import Database


class TestDaemonCrashRecovery(unittest.TestCase):
    """Test daemon crash scenarios and recovery."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.coord_dir = Path(self.test_dir) / '.claude-coord'
        self.coord_dir.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def crash_daemon(self, daemon, sig=signal.SIGKILL):
        """Helper to crash daemon with signal."""
        daemon_pid = daemon._read_pid()
        if daemon_pid:
            os.kill(daemon_pid, sig)
            time.sleep(0.5)
        return daemon_pid

    def restart_daemon(self, wait_time=1.0):
        """Helper to restart daemon cleanly."""
        daemon = CoordinationDaemon(self.test_dir)
        thread = threading.Thread(
            target=daemon.start,
            kwargs={'daemonize': False},
            daemon=True
        )
        thread.start()
        time.sleep(wait_time)
        return daemon, thread

    def validate_db_state(self):
        """Validate database invariants."""
        db_path = Path(self.test_dir) / '.claude-coord' / 'coordination.db'
        db = Database(str(db_path))
        db.initialize()

        errors = []

        # Check 1: No completed_at without status=completed
        invalid = db.query(
            "SELECT id FROM tasks WHERE completed_at IS NOT NULL AND status != 'completed'"
        )
        if invalid:
            errors.append(f"Tasks with completed_at but wrong status: {[r['id'] for r in invalid]}")

        # Check 2: In-progress tasks have owner
        orphaned = db.query(
            "SELECT id FROM tasks WHERE status = 'in_progress' AND owner IS NULL"
        )
        if orphaned:
            errors.append(f"In-progress tasks without owner: {[r['id'] for r in orphaned]}")

        # Check 3: Foreign key integrity
        fk_errors = db.query("PRAGMA foreign_key_check")
        if fk_errors:
            errors.append(f"Foreign key violations: {len(fk_errors)}")

        return errors

    def test_daemon_crash_during_task_execution(self):
        """Task state must persist across daemon crash during execution.

        Verifies:
        - Task remains in 'in_progress' state
        - Task ownership preserved
        - Task timestamps intact
        - Agent can resume work after restart
        """
        # Start daemon
        daemon, daemon_thread = self.restart_daemon()

        # Create client and register agent
        client = CoordinationClient(self.test_dir)
        client.call('register', {'agent_id': 'agent-1', 'pid': os.getpid()})

        # Create and claim task
        client.call('task_create', {
            'task_id': 'test-med-crash-01',
            'subject': 'Test crash recovery',
            'description': 'Task during crash',
            'priority': 2
        })

        client.call('task_claim', {
            'agent_id': 'agent-1',
            'task_id': 'test-med-crash-01'
        })

        # Get task details to capture started_at
        task_result = client.call('task_get', {'task_id': 'test-med-crash-01'})
        started_at = task_result['task']['started_at']

        # Simulate crash
        self.crash_daemon(daemon)

        # Verify daemon stopped
        self.assertFalse(daemon.is_running())

        # Restart daemon
        daemon2, daemon_thread2 = self.restart_daemon()

        # Verify task state persisted
        client2 = CoordinationClient(self.test_dir)
        client2.call('register', {'agent_id': 'agent-1', 'pid': os.getpid()})

        task_result = client2.call('task_get', {'task_id': 'test-med-crash-01'})

        # CRITICAL ASSERTIONS
        self.assertEqual(task_result['task']['status'], 'in_progress',
                        "Task status must remain in_progress after crash")
        self.assertEqual(task_result['task']['owner'], 'agent-1',
                        "Task ownership must persist")
        self.assertEqual(task_result['task']['started_at'], started_at,
                        "Task started_at timestamp must not change")
        self.assertIsNone(task_result['task']['completed_at'],
                         "Task must not have completed_at")

        # Verify agent can complete task after recovery
        complete_result = client2.call('task_complete', {
            'agent_id': 'agent-1',
            'task_id': 'test-med-crash-01'
        })
        self.assertEqual(complete_result['status'], 'completed')

        daemon2.cleanup()

    def test_file_locks_released_on_daemon_crash(self):
        """File locks must be released or reclaimable after daemon crash."""
        daemon, daemon_thread = self.restart_daemon()

        client = CoordinationClient(self.test_dir)
        client.call('register', {'agent_id': 'agent-1', 'pid': os.getpid()})

        # Acquire file lock
        lock_result = client.call('lock_acquire', {
            'agent_id': 'agent-1',
            'file_path': '/test/important.py'
        })
        self.assertEqual(lock_result['status'], 'locked')

        # Crash daemon
        self.crash_daemon(daemon)

        # Restart daemon
        daemon2, daemon_thread2 = self.restart_daemon()

        # Different agent should be able to acquire lock
        client2 = CoordinationClient(self.test_dir)
        client2.call('register', {'agent_id': 'agent-2', 'pid': os.getpid() + 1})

        # CRITICAL ASSERTION: Lock must be available
        lock_result2 = client2.call('lock_acquire', {
            'agent_id': 'agent-2',
            'file_path': '/test/important.py'
        })
        self.assertEqual(lock_result2['status'], 'locked',
                        "File lock must be reclaimable after daemon crash")

        # Verify database consistency
        db = Database(str(Path(self.test_dir) / '.claude-coord' / 'coordination.db'))
        db.initialize()

        locks = db.query("SELECT * FROM file_locks WHERE file_path = ?",
                        ('/test/important.py',))

        # Should only have one active lock (agent-2)
        active_locks = [l for l in locks]
        self.assertEqual(len(active_locks), 1, "Only one active lock should exist")
        self.assertEqual(active_locks[0]['agent_id'], 'agent-2')

        daemon2.cleanup()

    def test_agent_reconnection_after_graceful_restart(self):
        """Agents must successfully reconnect after graceful daemon restart."""
        daemon, daemon_thread = self.restart_daemon()

        client = CoordinationClient(self.test_dir)

        # Register agent
        reg_result = client.call('register', {
            'agent_id': 'persistent-agent',
            'pid': 12345
        })
        self.assertEqual(reg_result['status'], 'registered')

        # Create task
        client.call('task_create', {
            'task_id': 'test-med-reconnect-01',
            'subject': 'Test reconnection',
            'description': 'Task before restart',
            'priority': 2
        })

        # Graceful shutdown
        daemon.cleanup()
        time.sleep(0.5)

        # Restart daemon
        daemon2, daemon_thread2 = self.restart_daemon()

        # Agent re-registers
        client2 = CoordinationClient(self.test_dir)
        reconnect_result = client2.call('register', {
            'agent_id': 'persistent-agent',
            'pid': 54321
        })

        # CRITICAL ASSERTIONS
        self.assertEqual(reconnect_result['status'], 'registered',
                        "Agent must successfully re-register")

        # Verify agent can access tasks
        task_result = client2.call('task_get', {'task_id': 'test-med-reconnect-01'})
        self.assertEqual(task_result['task']['id'], 'test-med-reconnect-01')

        # Verify agent can claim task
        claim_result = client2.call('task_claim', {
            'agent_id': 'persistent-agent',
            'task_id': 'test-med-reconnect-01'
        })
        self.assertEqual(claim_result['status'], 'claimed')

        daemon2.cleanup()

    def test_database_wal_recovery_after_crash(self):
        """SQLite WAL mode must recover database state after crash."""
        daemon, daemon_thread = self.restart_daemon()

        client = CoordinationClient(self.test_dir)
        client.call('register', {'agent_id': 'agent-1', 'pid': os.getpid()})

        # Create multiple tasks
        task_ids = []
        for i in range(5):
            task_id = f'test-med-wal-{i:02d}'
            client.call('task_create', {
                'task_id': task_id,
                'subject': f'Test WAL recovery {i}',
                'description': 'Task for WAL test',
                'priority': 2
            })
            task_ids.append(task_id)

        # Claim some tasks
        for i in range(3):
            client.call('task_claim', {
                'agent_id': 'agent-1',
                'task_id': task_ids[i]
            })

        # Complete one task
        client.call('task_complete', {
            'agent_id': 'agent-1',
            'task_id': task_ids[0]
        })

        # Crash during active transaction load
        self.crash_daemon(daemon)

        # Check database directly
        db_path = Path(self.test_dir) / '.claude-coord' / 'coordination.db'
        db = Database(str(db_path))
        db.initialize()

        # Verify all tasks present
        tasks = db.query("SELECT id, status FROM tasks WHERE id LIKE 'test-med-wal-%'")
        self.assertEqual(len(tasks), 5, "All tasks must be in database")

        # Verify completed task status
        completed = [t for t in tasks if t['id'] == task_ids[0]]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]['status'], 'completed',
                        "Completed task status must persist")

        # Verify in-progress tasks
        in_progress = [t for t in tasks if t['status'] == 'in_progress']
        self.assertEqual(len(in_progress), 2, "Two in-progress tasks expected")

        # Verify pending tasks
        pending = [t for t in tasks if t['status'] == 'pending']
        self.assertEqual(len(pending), 2, "Two pending tasks expected")

        # Restart daemon and verify continued operation
        daemon2, daemon_thread2 = self.restart_daemon()

        client2 = CoordinationClient(self.test_dir)
        client2.call('register', {'agent_id': 'agent-1', 'pid': os.getpid()})

        # Complete another task to verify write operations work
        complete_result = client2.call('task_complete', {
            'agent_id': 'agent-1',
            'task_id': task_ids[1]
        })
        self.assertEqual(complete_result['status'], 'completed')

        daemon2.cleanup()

    def test_multiple_consecutive_crashes(self):
        """Daemon must recover correctly after multiple crashes."""
        client = CoordinationClient(self.test_dir)

        # Track task states across crashes
        task_states = []

        for crash_num in range(3):
            # Start daemon
            daemon, daemon_thread = self.restart_daemon()

            # Register agent
            client.call('register', {
                'agent_id': f'agent-{crash_num}',
                'pid': os.getpid() + crash_num
            })

            # Create and modify tasks
            task_id = f'test-med-multicrash-{crash_num:02d}'
            client.call('task_create', {
                'task_id': task_id,
                'subject': f'Crash test {crash_num}',
                'description': 'Multi-crash test',
                'priority': 2
            })

            # Claim task
            claim_result = client.call('task_claim', {
                'agent_id': f'agent-{crash_num}',
                'task_id': task_id
            })

            task_states.append({
                'crash_num': crash_num,
                'task_id': task_id,
                'status': 'in_progress',
                'owner': f'agent-{crash_num}'
            })

            # Crash daemon
            self.crash_daemon(daemon)

        # Final restart - verify all state consistent
        daemon_final, daemon_thread_final = self.restart_daemon()

        # Verify all tasks in correct state
        client_final = CoordinationClient(self.test_dir)
        client_final.call('register', {
            'agent_id': 'verifier',
            'pid': os.getpid() + 100
        })

        for expected in task_states:
            task_result = client_final.call('task_get', {
                'task_id': expected['task_id']
            })

            # CRITICAL ASSERTIONS
            self.assertEqual(task_result['task']['status'], expected['status'],
                           f"Task {expected['task_id']} status incorrect")
            self.assertEqual(task_result['task']['owner'], expected['owner'],
                           f"Task {expected['task_id']} owner incorrect")

        # Verify database integrity
        db = Database(str(Path(self.test_dir) / '.claude-coord' / 'coordination.db'))
        db.initialize()

        tasks = db.query("SELECT * FROM tasks WHERE id LIKE 'test-med-multicrash-%'")
        self.assertEqual(len(tasks), 3, "All tasks must persist")

        for task in tasks:
            if task['status'] == 'in_progress':
                self.assertIsNotNone(task['owner'], "In-progress task must have owner")
                self.assertIsNotNone(task['started_at'], "In-progress task must have started_at")
            self.assertIsNone(task['completed_at'], "No task should be completed")

        daemon_final.cleanup()

    def test_stale_pid_file_detection(self):
        """Stale PID files must be detected and cleaned up."""
        daemon, daemon_thread = self.restart_daemon()
        pid_file = daemon.pid_file

        # Get PID
        daemon_pid = daemon._read_pid()
        self.assertIsNotNone(daemon_pid)
        self.assertTrue(daemon.is_running())

        # Kill daemon ungracefully
        self.crash_daemon(daemon)

        # PID file still exists but process is dead
        self.assertTrue(pid_file.exists(), "PID file should still exist")

        # CRITICAL ASSERTION: is_running() detects stale PID
        running = daemon.is_running()
        self.assertFalse(running, "is_running() must return False for stale PID")

        # Start new daemon - should work despite stale PID
        daemon2, daemon_thread2 = self.restart_daemon()

        # Verify new daemon running
        self.assertTrue(daemon2.is_running(), "New daemon must start successfully")

        new_pid = daemon2._read_pid()
        self.assertNotEqual(new_pid, daemon_pid, "New daemon must have different PID")
        self.assertGreater(new_pid, 0, "PID must be valid")

        daemon2.cleanup()


class TestDaemonEdgeCases(unittest.TestCase):
    """Test daemon edge cases and stress scenarios."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.coord_dir = Path(self.test_dir) / '.claude-coord'
        self.coord_dir.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def crash_daemon(self, daemon, sig=signal.SIGKILL):
        """Helper to crash daemon."""
        daemon_pid = daemon._read_pid()
        if daemon_pid:
            os.kill(daemon_pid, sig)
            time.sleep(0.5)
        return daemon_pid

    def restart_daemon(self, wait_time=1.0):
        """Helper to restart daemon."""
        daemon = CoordinationDaemon(self.test_dir)
        thread = threading.Thread(
            target=daemon.start,
            kwargs={'daemonize': False},
            daemon=True
        )
        thread.start()
        time.sleep(wait_time)
        return daemon, thread

    def test_rapid_daemon_restart_cycle(self):
        """Daemon must handle rapid start/stop cycles gracefully."""
        for i in range(5):
            daemon, daemon_thread = self.restart_daemon(wait_time=0.5)
            self.assertTrue(daemon.is_running())

            daemon.cleanup()
            time.sleep(0.3)
            self.assertFalse(daemon.is_running())

        # Final startup should work
        daemon_final, daemon_thread_final = self.restart_daemon()
        self.assertTrue(daemon_final.is_running())

        # Verify functionality
        client = CoordinationClient(self.test_dir)
        result = client.call('register', {
            'agent_id': 'test-agent',
            'pid': os.getpid()
        })
        self.assertEqual(result['status'], 'registered')

        daemon_final.cleanup()

    def test_database_integrity_after_crash(self):
        """Database must pass all integrity checks after crash."""
        daemon, daemon_thread = self.restart_daemon()
        client = CoordinationClient(self.test_dir)

        # Create complex state
        for i in range(3):
            agent_id = f'agent-{i}'
            client.call('register', {
                'agent_id': agent_id,
                'pid': os.getpid() + i
            })

            for j in range(2):
                task_id = f'test-med-integrity-{i}-{j}'
                client.call('task_create', {
                    'task_id': task_id,
                    'subject': f'Integrity test {i}-{j}',
                    'description': 'Complex state test',
                    'priority': 2
                })

                if j == 0:
                    client.call('task_claim', {
                        'agent_id': agent_id,
                        'task_id': task_id
                    })

        # Crash daemon
        self.crash_daemon(daemon)

        # Run integrity checks
        db = Database(str(Path(self.test_dir) / '.claude-coord' / 'coordination.db'))
        db.initialize()

        # Check foreign key integrity
        result = db.query("PRAGMA foreign_key_check")
        self.assertEqual(len(result), 0, "No foreign key violations")

        # Check task status consistency
        inconsistent = db.query(
            "SELECT * FROM tasks WHERE status = 'completed' AND completed_at IS NULL"
        )
        self.assertEqual(len(inconsistent), 0, "No status inconsistencies")

        # Check task ownership consistency
        bad_ownership = db.query(
            "SELECT * FROM tasks WHERE status = 'in_progress' AND owner IS NULL"
        )
        self.assertEqual(len(bad_ownership), 0, "In-progress tasks must have owner")

        # Restart should work
        daemon2, daemon_thread2 = self.restart_daemon()
        self.assertTrue(daemon2.is_running())

        daemon2.cleanup()


if __name__ == '__main__':
    unittest.main()
