"""
Coordination daemon lifecycle management.

Handles daemon start, stop, restart, and status operations.
"""

import atexit
import os
import signal
import sys
import time
from pathlib import Path

from .background import BackgroundTasks
from .database import Database
from .server import CoordinationServer


class CoordinationDaemon:
    """Manages coordination daemon lifecycle."""

    def __init__(self, project_root: str = None):
        """Initialize daemon.

        Args:
            project_root: Project root directory
        """
        self.project_root = project_root or os.getcwd()

        # Paths
        self.coord_dir = Path(self.project_root) / '.claude-coord'
        self.db_path = self.coord_dir / 'coordination.db'
        self.pid_file = self.coord_dir / 'daemon.pid'

        # Components
        self.db: Database = None
        self.server: CoordinationServer = None
        self.background: BackgroundTasks = None

    def start(self, daemonize: bool = True):
        """Start the daemon.

        Args:
            daemonize: Whether to run as background daemon
        """
        # Check if already running
        if self.is_running():
            pid = self._read_pid()
            print(f"Daemon already running (PID {pid})")
            return

        if daemonize:
            # Fork to background
            pid = os.fork()
            if pid > 0:
                # Parent process
                print(f"Daemon started (PID {pid})")
                sys.exit(0)

            # Child process continues
            os.setsid()  # Create new session

        # Initialize database
        self.db = Database(str(self.db_path))
        self.db.initialize()

        # Start server
        self.server = CoordinationServer(self.db, self.project_root)
        self.server.start()

        # Start background tasks
        self.background = BackgroundTasks(self.db, config={
            'agent_timeout': 300,  # 5 minutes
            'state_json_path': str(self.coord_dir / 'state.json')
        })
        self.background.start()

        # Write PID file
        self._write_pid(os.getpid())

        # Register cleanup handlers
        atexit.register(self.cleanup)
        signal.signal(signal.SIGTERM, lambda sig, frame: self.cleanup())
        signal.signal(signal.SIGINT, lambda sig, frame: self.cleanup())

        print(f"Coordination daemon running (PID {os.getpid()})")
        print(f"Socket: {self.server.socket_path}")

        if daemonize:
            # Keep running
            while self.server.running:
                time.sleep(1)

    def stop(self):
        """Stop the daemon."""
        if not self.is_running():
            print("Daemon not running")
            return

        pid = self._read_pid()

        try:
            # Send SIGTERM
            os.kill(pid, signal.SIGTERM)

            # Wait for process to exit (up to 10s)
            for _ in range(100):
                try:
                    os.kill(pid, 0)  # Check if still running
                    time.sleep(0.1)
                except OSError:
                    break  # Process exited

            print("Daemon stopped")

        except OSError as e:
            print(f"Error stopping daemon: {e}")

        finally:
            # Remove PID file
            if self.pid_file.exists():
                self.pid_file.unlink()

    def restart(self):
        """Restart the daemon."""
        self.stop()
        time.sleep(1)
        self.start()

    def status(self) -> dict:
        """Get daemon status.

        Returns:
            Status dictionary
        """
        if not self.is_running():
            return {
                "running": False,
                "message": "Daemon not running"
            }

        pid = self._read_pid()

        return {
            "running": True,
            "pid": pid,
            "message": f"Daemon running (PID {pid})"
        }

    def is_running(self) -> bool:
        """Check if daemon is running.

        Returns:
            True if daemon is running
        """
        if not self.pid_file.exists():
            return False

        pid = self._read_pid()
        if pid is None:
            return False

        try:
            # Check if process exists
            os.kill(pid, 0)
            return True
        except OSError:
            # Process doesn't exist, remove stale PID file
            self.pid_file.unlink()
            return False

    def cleanup(self):
        """Cleanup on exit."""
        if self.background:
            self.background.stop()

        if self.server:
            self.server.stop()

        if self.pid_file.exists():
            self.pid_file.unlink()

    def _write_pid(self, pid: int):
        """Write PID to file.

        Args:
            pid: Process ID
        """
        self.pid_file.write_text(str(pid))

    def _read_pid(self) -> int:
        """Read PID from file.

        Returns:
            Process ID or None
        """
        try:
            return int(self.pid_file.read_text().strip())
        except Exception:
            return None


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Coordination daemon')
    parser.add_argument('command', choices=['start', 'stop', 'restart', 'status'])
    parser.add_argument('--foreground', action='store_true', help='Run in foreground')
    parser.add_argument('--project-root', help='Project root directory')

    args = parser.parse_args()

    daemon = CoordinationDaemon(project_root=args.project_root)

    if args.command == 'start':
        daemon.start(daemonize=not args.foreground)
    elif args.command == 'stop':
        daemon.stop()
    elif args.command == 'restart':
        daemon.restart()
    elif args.command == 'status':
        status = daemon.status()
        print(status['message'])
        sys.exit(0 if status['running'] else 1)


if __name__ == '__main__':
    main()
