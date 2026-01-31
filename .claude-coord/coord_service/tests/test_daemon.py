"""
Tests for coordination daemon.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from coord_service.database import Database
from coord_service.daemon import CoordinationDaemon
from coord_service.client import CoordinationClient
from coord_service.validator import ValidationErrors


class TestCoordinationDaemon(unittest.TestCase):
    """Test coordination daemon functionality."""

    def setUp(self):
        """Set up test environment."""
        # Create temporary directory
        self.test_dir = tempfile.mkdtemp()
        self.coord_dir = Path(self.test_dir) / '.claude-coord'
        self.coord_dir.mkdir()

        # Create daemon
        self.daemon = CoordinationDaemon(self.test_dir)

        # Start daemon in foreground
        import threading
        self.daemon_thread = threading.Thread(
            target=self.daemon.start,
            kwargs={'daemonize': False},
            daemon=True
        )
        self.daemon_thread.start()

        # Wait for daemon to start
        time.sleep(1)

        # Create client
        self.client = CoordinationClient(self.test_dir)

    def tearDown(self):
        """Clean up test environment."""
        # Stop daemon
        if self.daemon:
            self.daemon.cleanup()

        # Clean up temp directory
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_agent_registration(self):
        """Test agent registration."""
        result = self.client.call('register', {
            'agent_id': 'test-agent',
            'pid': os.getpid()
        })

        self.assertEqual(result['status'], 'registered')
        self.assertEqual(result['agent_id'], 'test-agent')

    def test_task_creation_validation(self):
        """Test task creation validation."""
        # Invalid task ID
        with self.assertRaises(RuntimeError) as ctx:
            self.client.call('task_create', {
                'task_id': 'InvalidTask',
                'subject': 'Test task',
                'description': 'Description',
                'priority': 1
            })

        self.assertIn('naming convention', str(ctx.exception))

        # Valid task ID
        result = self.client.call('task_create', {
            'task_id': 'test-high-validation-01',
            'subject': 'Test validation feature',
            'description': 'Ensure validation works correctly',
            'priority': 2
        })

        self.assertEqual(result['status'], 'created')

    def test_task_claim(self):
        """Test task claim workflow."""
        # Register agent
        self.client.call('register', {
            'agent_id': 'test-agent',
            'pid': os.getpid()
        })

        # Create task
        self.client.call('task_create', {
            'task_id': 'test-med-workflow-01',
            'subject': 'Test workflow',
            'description': 'Test',
            'priority': 3
        })

        # Claim task
        result = self.client.call('task_claim', {
            'agent_id': 'test-agent',
            'task_id': 'test-med-workflow-01'
        })

        self.assertEqual(result['status'], 'claimed')

        # Cannot claim again
        with self.assertRaises(RuntimeError) as ctx:
            self.client.call('task_claim', {
                'agent_id': 'test-agent',
                'task_id': 'test-med-workflow-01'
            })

        self.assertIn('unavailable', str(ctx.exception).lower())

    def test_file_locking(self):
        """Test file locking."""
        # Register agents
        self.client.call('register', {
            'agent_id': 'agent-1',
            'pid': os.getpid()
        })

        self.client.call('register', {
            'agent_id': 'agent-2',
            'pid': os.getpid() + 1
        })

        # Agent 1 locks file
        self.client.call('lock_acquire', {
            'agent_id': 'agent-1',
            'file_path': 'test.py'
        })

        # Agent 2 cannot lock same file
        with self.assertRaises(RuntimeError) as ctx:
            self.client.call('lock_acquire', {
                'agent_id': 'agent-2',
                'file_path': 'test.py'
            })

        self.assertIn('locked', str(ctx.exception).lower())

        # Agent 1 unlocks
        self.client.call('lock_release', {
            'agent_id': 'agent-1',
            'file_path': 'test.py'
        })

        # Now agent 2 can lock
        result = self.client.call('lock_acquire', {
            'agent_id': 'agent-2',
            'file_path': 'test.py'
        })

        self.assertEqual(result['status'], 'locked')

    def test_velocity_tracking(self):
        """Test velocity metrics tracking."""
        # Register agent
        self.client.call('register', {
            'agent_id': 'test-agent',
            'pid': os.getpid()
        })

        # Create and complete tasks
        for i in range(3):
            task_id = f'test-low-perf-{i:02d}'
            self.client.call('task_create', {
                'task_id': task_id,
                'subject': f'Performance test {i}',
                'description': 'Test',
                'priority': 4
            })

            self.client.call('task_claim', {
                'agent_id': 'test-agent',
                'task_id': task_id
            })

            self.client.call('task_complete', {
                'agent_id': 'test-agent',
                'task_id': task_id
            })

        # Get velocity metrics
        result = self.client.call('velocity', {
            'period': '1 hour'
        })

        self.assertEqual(result['completed_tasks'], 3)
        self.assertGreater(result['tasks_per_hour'], 0)

    def test_state_export_import(self):
        """Test state export and import."""
        # Register agent
        self.client.call('register', {
            'agent_id': 'test-agent',
            'pid': os.getpid()
        })

        # Create task
        self.client.call('task_create', {
            'task_id': 'test-low-export-01',
            'subject': 'Test export',
            'description': 'Test',
            'priority': 4
        })

        # Export state
        export_path = str(Path(self.test_dir) / 'exported.json')
        self.client.call('export_json', {
            'output_path': export_path
        })

        # Verify export file
        self.assertTrue(os.path.exists(export_path))

        with open(export_path) as f:
            state = json.load(f)

        self.assertIn('agents', state)
        self.assertIn('tasks', state)
        self.assertIn('test-agent', state['agents'])
        self.assertIn('test-low-export-01', state['tasks'])


if __name__ == '__main__':
    unittest.main()
