"""
CLI client for coordination service.

Communicates with daemon via Unix socket.
"""

import hashlib
import json
import os
import socket
import sys
from typing import Any, Dict

from .protocol import Request, Response


class CoordinationClient:
    """Client for communicating with coordination daemon."""

    def __init__(self, project_root: str = None, timeout: int = 5):
        """Initialize client.

        Args:
            project_root: Project root directory
            timeout: Request timeout in seconds
        """
        self.project_root = project_root or os.getcwd()
        self.timeout = timeout

        # Generate socket path
        project_hash = hashlib.sha256(self.project_root.encode()).hexdigest()[:8]
        self.socket_path = f"/tmp/coord-{project_hash}.sock"

    def call(self, method: str, params: Dict[str, Any] = None) -> Any:
        """Call a daemon method.

        Args:
            method: Method name
            params: Method parameters

        Returns:
            Method result

        Raises:
            Exception: If call fails
        """
        # Create request
        request = Request(method=method, params=params or {})

        # Connect to daemon
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect(self.socket_path)
        except (FileNotFoundError, ConnectionRefusedError):
            raise RuntimeError("Daemon not running. Start with: coord-service start")
        except socket.timeout:
            raise RuntimeError("Connection timeout. Is daemon hung?")

        try:
            # Send request
            sock.sendall(request.to_json().encode('utf-8'))

            # Receive response
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk

            # Parse response
            response = Response.from_json(data.decode('utf-8'))

            if response.error:
                error_msg = response.error['message']
                error_data = response.error.get('data', {})

                # Format validation errors nicely
                if 'validation_errors' in error_data:
                    errors = error_data['validation_errors']
                    if len(errors) == 1:
                        err = errors[0]
                        raise RuntimeError(f"{err['message']}\nHint: {err.get('hint', 'N/A')}")
                    else:
                        lines = [f"{len(errors)} validation errors:"]
                        for i, err in enumerate(errors, 1):
                            lines.append(f"  {i}. {err['code']}: {err['message']}")
                            if err.get('hint'):
                                lines.append(f"     Hint: {err['hint']}")
                        raise RuntimeError('\n'.join(lines))

                raise RuntimeError(error_msg)

            return response.result

        finally:
            sock.close()


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Coordination client')

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Register agent
    register_parser = subparsers.add_parser('register', help='Register agent')
    register_parser.add_argument('agent_id', help='Agent ID')
    register_parser.add_argument('--pid', type=int, default=os.getpid(), help='Process ID')

    # Unregister agent
    unregister_parser = subparsers.add_parser('unregister', help='Unregister agent')
    unregister_parser.add_argument('agent_id', help='Agent ID')

    # Create task
    task_add_parser = subparsers.add_parser('task-add', help='Create task')
    task_add_parser.add_argument('task_id', help='Task ID')
    task_add_parser.add_argument('subject', help='Task subject')
    task_add_parser.add_argument('--description', default='', help='Task description')
    task_add_parser.add_argument('--priority', type=int, default=3, help='Priority (1-5)')
    task_add_parser.add_argument('--spec', help='Spec file path')

    # Claim task
    task_claim_parser = subparsers.add_parser('task-claim', help='Claim task')
    task_claim_parser.add_argument('agent_id', help='Agent ID')
    task_claim_parser.add_argument('task_id', help='Task ID')

    # Complete task
    task_complete_parser = subparsers.add_parser('task-complete', help='Complete task')
    task_complete_parser.add_argument('agent_id', help='Agent ID')
    task_complete_parser.add_argument('task_id', help='Task ID')

    # Get task
    task_get_parser = subparsers.add_parser('task-get', help='Get task')
    task_get_parser.add_argument('task_id', help='Task ID')

    # List tasks
    task_list_parser = subparsers.add_parser('task-list', help='List tasks')
    task_list_parser.add_argument('--limit', type=int, default=10, help='Max tasks')

    # Lock file
    lock_parser = subparsers.add_parser('lock', help='Lock file')
    lock_parser.add_argument('agent_id', help='Agent ID')
    lock_parser.add_argument('file_path', help='File path')

    # Unlock file
    unlock_parser = subparsers.add_parser('unlock', help='Unlock file')
    unlock_parser.add_argument('agent_id', help='Agent ID')
    unlock_parser.add_argument('file_path', help='File path')

    # Status
    status_parser = subparsers.add_parser('status', help='Get status')

    # Velocity
    velocity_parser = subparsers.add_parser('velocity', help='Get velocity metrics')
    velocity_parser.add_argument('--period', default='1 hour', help='Time period')

    # File hotspots
    hotspots_parser = subparsers.add_parser('file-hotspots', help='Get file lock hotspots')
    hotspots_parser.add_argument('--limit', type=int, default=10, help='Max files')

    # Task timing
    timing_parser = subparsers.add_parser('task-timing', help='Get task timing')
    timing_parser.add_argument('task_id', help='Task ID')

    # Export state
    export_parser = subparsers.add_parser('export', help='Export state to JSON')
    export_parser.add_argument('--output', default='.claude-coord/state.json', help='Output path')

    # Import state
    import_parser = subparsers.add_parser('import', help='Import state from JSON')
    import_parser.add_argument('json_path', help='JSON file path')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    client = CoordinationClient()

    try:
        # Dispatch to appropriate method
        if args.command == 'register':
            result = client.call('register', {
                'agent_id': args.agent_id,
                'pid': args.pid
            })
            print(f"Agent registered: {args.agent_id}")

        elif args.command == 'unregister':
            result = client.call('unregister', {
                'agent_id': args.agent_id
            })
            print(f"Agent unregistered: {args.agent_id}")

        elif args.command == 'task-add':
            result = client.call('task_create', {
                'task_id': args.task_id,
                'subject': args.subject,
                'description': args.description,
                'priority': args.priority,
                'spec_path': args.spec
            })
            print(f"Task created: {args.task_id}")

        elif args.command == 'task-claim':
            result = client.call('task_claim', {
                'agent_id': args.agent_id,
                'task_id': args.task_id
            })
            print(f"Task claimed: {args.task_id}")

        elif args.command == 'task-complete':
            result = client.call('task_complete', {
                'agent_id': args.agent_id,
                'task_id': args.task_id
            })
            print(f"Task completed: {args.task_id}")

        elif args.command == 'task-get':
            result = client.call('task_get', {
                'task_id': args.task_id
            })
            task = result['task']
            print(json.dumps(task, indent=2))

        elif args.command == 'task-list':
            result = client.call('task_list', {
                'limit': args.limit
            })
            tasks = result['tasks']
            if tasks:
                print(f"Available tasks ({len(tasks)}):")
                for task in tasks:
                    print(f"  [{task['priority']}] {task['id']}: {task['subject']}")
            else:
                print("No available tasks")

        elif args.command == 'lock':
            result = client.call('lock_acquire', {
                'agent_id': args.agent_id,
                'file_path': args.file_path
            })
            print(f"Locked: {args.file_path}")

        elif args.command == 'unlock':
            result = client.call('lock_release', {
                'agent_id': args.agent_id,
                'file_path': args.file_path
            })
            print(f"Unlocked: {args.file_path}")

        elif args.command == 'status':
            result = client.call('status', {})
            print(f"Status: {result['status']}")
            print(f"Agents: {result['agents']}")
            print(f"Tasks: {result['tasks']}")
            print(f"Locks: {result['locks']}")

        elif args.command == 'velocity':
            result = client.call('velocity', {
                'period': args.period
            })
            print(f"Velocity Report ({args.period}):")
            print(f"  Completed tasks: {result['completed_tasks']}")
            print(f"  Avg duration: {result['avg_duration_mins']} minutes")
            print(f"  Tasks/hour: {result['tasks_per_hour']}")

        elif args.command == 'file-hotspots':
            result = client.call('file_hotspots', {
                'limit': args.limit
            })
            hotspots = result['hotspots']
            if hotspots:
                print("File Lock Hotspots:")
                print(f"{'File':<50} {'Locks':<8} {'Avg Duration':<15} {'Contention'}")
                print("-" * 80)
                for hs in hotspots:
                    print(f"{hs['file_path']:<50} {hs['lock_count']:<8} {hs['avg_duration_mins']:<15} {hs['contention_count']}")
            else:
                print("No file lock data")

        elif args.command == 'task-timing':
            result = client.call('task_timing', {
                'task_id': args.task_id
            })
            timing = result['timing']
            files = result['files']

            print(f"Task Timing: {args.task_id}")
            print(f"  Created: {timing.get('created_at', 'N/A')}")
            print(f"  Claimed: {timing.get('claimed_at', 'N/A')}")
            print(f"  Completed: {timing.get('completed_at', 'N/A')}")
            print(f"  Wait time: {timing.get('wait_time_seconds', 0):.1f}s")
            print(f"  Work time: {timing.get('work_time_seconds', 0):.1f}s")
            print(f"  Active time: {timing.get('active_time_seconds', 0):.1f}s")
            print(f"  Idle time: {timing.get('idle_time_seconds', 0):.1f}s")
            print(f"\nFiles worked on:")
            for f in files:
                print(f"  - {f['file_path']} ({f['lock_duration_secs']}s)")

        elif args.command == 'export':
            result = client.call('export_json', {
                'output_path': args.output
            })
            print(f"State exported to: {args.output}")

        elif args.command == 'import':
            result = client.call('import_json', {
                'json_path': args.json_path
            })
            print(f"State imported from: {args.json_path}")

    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
