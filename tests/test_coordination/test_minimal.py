"""Minimal test to debug daemon issues."""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

coord_service_path = Path(__file__).parent.parent.parent / '.claude-coord'
sys.path.insert(0, str(coord_service_path))

from coord_service.client import CoordinationClient
from coord_service.daemon import CoordinationDaemon


class TestMinimal(unittest.TestCase):
    """Minimal daemon test."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.coord_dir = Path(self.test_dir) / '.claude-coord'
        self.coord_dir.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_simple_start_stop(self):
        """Test simple daemon start and stop."""
        print("\n1. Creating daemon...")
        daemon = CoordinationDaemon(self.test_dir)

        print("2. Starting daemon in thread...")
        thread = threading.Thread(
            target=daemon.start,
            kwargs={'daemonize': False},
            daemon=True
        )
        thread.start()
        time.sleep(2)

        print("3. Checking if running...")
        is_running = daemon.is_running()
        print(f"   Daemon running: {is_running}")
        self.assertTrue(is_running)

        print("4. Creating client...")
        client = CoordinationClient(self.test_dir)

        print("5. Registering agent...")
        result = client.call('register', {'agent_id': 'test-agent', 'pid': os.getpid()})
        print(f"   Register result: {result}")
        self.assertEqual(result['status'], 'registered')

        print("6. Cleaning up daemon...")
        daemon.cleanup()
        time.sleep(1)

        print("7. Checking if stopped...")
        is_running_after = daemon.is_running()
        print(f"   Daemon running after cleanup: {is_running_after}")
        self.assertFalse(is_running_after)

        print("8. Test complete!")


if __name__ == '__main__':
    unittest.main(verbosity=2)
