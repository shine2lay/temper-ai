"""Minimal crash test."""

import os
import signal
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


class TestCrashMinimal(unittest.TestCase):
    """Minimal crash test."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.coord_dir = Path(self.test_dir) / '.claude-coord'
        self.coord_dir.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_crash_and_restart(self):
        """Test daemon crash and restart."""
        print("\n1. Starting first daemon...")
        daemon1 = CoordinationDaemon(self.test_dir)
        thread1 = threading.Thread(
            target=daemon1.start,
            kwargs={'daemonize': False},
            daemon=True
        )
        thread1.start()
        time.sleep(2)

        self.assertTrue(daemon1.is_running())
        pid1 = daemon1._read_pid()
        print(f"   Daemon 1 PID: {pid1}")

        print("2. Crashing daemon with SIGKILL...")
        os.kill(pid1, signal.SIGKILL)
        time.sleep(1)

        print("3. Checking if stopped...")
        is_running = daemon1.is_running()
        print(f"   Daemon running after crash: {is_running}")
        self.assertFalse(is_running)

        print("4. Starting second daemon (recovery)...")
        daemon2 = CoordinationDaemon(self.test_dir)
        thread2 = threading.Thread(
            target=daemon2.start,
            kwargs={'daemonize': False},
            daemon=True
        )
        thread2.start()
        time.sleep(2)

        print("5. Checking if restarted...")
        is_running2 = daemon2.is_running()
        print(f"   Daemon 2 running: {is_running2}")
        self.assertTrue(is_running2)

        pid2 = daemon2._read_pid()
        print(f"   Daemon 2 PID: {pid2}")
        self.assertNotEqual(pid1, pid2)

        print("6. Testing functionality after restart...")
        client = CoordinationClient(self.test_dir)
        result = client.call('register', {'agent_id': 'test-agent', 'pid': os.getpid()})
        print(f"   Register result: {result}")
        self.assertEqual(result['status'], 'registered')

        print("7. Cleanup...")
        daemon2.cleanup()
        time.sleep(1)

        print("8. Test complete!")


if __name__ == '__main__':
    unittest.main(verbosity=2)
