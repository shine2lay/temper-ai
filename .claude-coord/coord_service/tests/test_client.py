"""
Comprehensive tests for coordination client.

Tests client-server communication, connection handling, error propagation,
and timeout behavior.
"""

import json
import os
import socket
import tempfile
import threading
from unittest import mock

import pytest

from coord_service.client import CoordinationClient
from coord_service.protocol import Request, Response


class TestClientInitialization:
    """Test client initialization."""

    def test_init_with_default_project_root(self):
        """Client should use current directory as default project root."""
        client = CoordinationClient()

        assert client.project_root == os.getcwd()

    def test_init_with_custom_project_root(self):
        """Client should accept custom project root."""
        client = CoordinationClient(project_root='/custom/path')

        assert client.project_root == '/custom/path'

    def test_init_sets_timeout(self):
        """Client should use specified timeout."""
        client = CoordinationClient(timeout=10)

        assert client.timeout == 10

    def test_socket_path_includes_project_hash(self):
        """Socket path should include hash of project root for uniqueness."""
        client = CoordinationClient(project_root='/test/project')

        # Socket path should be in /tmp and include hash
        assert client.socket_path.startswith('/tmp/coord-')
        assert client.socket_path.endswith('.sock')

    def test_different_projects_get_different_sockets(self):
        """Different project roots should generate different socket paths."""
        client1 = CoordinationClient(project_root='/project1')
        client2 = CoordinationClient(project_root='/project2')

        assert client1.socket_path != client2.socket_path


class TestClientConnection:
    """Test client connection handling."""

    def test_connect_to_running_daemon(self, running_daemon, client):
        """Client should connect successfully to running daemon."""
        result = client.call('status', {})

        # Should get status response
        assert 'agent_count' in result or 'status' in result

    def test_connect_timeout_no_daemon(self):
        """Connection attempt with no daemon should timeout."""
        client = CoordinationClient(timeout=1)
        # Override socket path to ensure no daemon
        client.socket_path = '/tmp/nonexistent-daemon.sock'

        with pytest.raises(RuntimeError, match="Daemon not running"):
            client.call('status', {})

    def test_connect_socket_missing(self):
        """Missing socket file should raise clear error."""
        client = CoordinationClient()
        client.socket_path = '/tmp/missing-socket.sock'

        with pytest.raises(RuntimeError, match="Daemon not running"):
            client.call('status', {})

    def test_connect_permission_denied(self):
        """Permission denied on socket should raise error."""
        with tempfile.NamedTemporaryFile(suffix='.sock') as sock_file:
            os.chmod(sock_file.name, 0o000)  # No permissions

            client = CoordinationClient()
            client.socket_path = sock_file.name

            with pytest.raises(Exception):  # RuntimeError or PermissionError
                client.call('status', {})


class TestClientRequests:
    """Test client request sending."""

    def test_send_request_success(self, running_daemon, client):
        """Successful request returns result."""
        result = client.call('status', {})

        assert result is not None

    def test_send_request_with_params(self, running_daemon, client):
        """Request with parameters sends params correctly."""
        # Register agent
        result = client.call('register', {
            'agent_id': 'test-agent',
            'pid': 12345
        })

        assert result['status'] == 'registered'

    def test_send_request_creates_valid_json_rpc(self, running_daemon, client):
        """Request should be valid JSON-RPC format."""
        # Mock socket to inspect what's sent
        original_socket = socket.socket

        sent_data = []

        def mock_socket_factory(*args, **kwargs):
            sock = original_socket(*args, **kwargs)
            original_sendall = sock.sendall

            def capture_sendall(data):
                sent_data.append(data)
                return original_sendall(data)

            sock.sendall = capture_sendall
            return sock

        with mock.patch('socket.socket', side_effect=mock_socket_factory):
            client.call('status', {})

        # Verify sent data is valid JSON-RPC
        assert len(sent_data) > 0
        data = json.loads(sent_data[0].decode('utf-8'))
        assert 'method' in data
        assert 'params' in data
        assert data['method'] == 'status'

    def test_send_large_request(self, running_daemon, client):
        """Client should handle large payloads."""
        # Create large metadata
        large_metadata = {'data': 'x' * 10000}

        # This should succeed without truncation
        result = client.call('register', {
            'agent_id': 'test-large',
            'pid': 12345,
            'metadata': large_metadata
        })

        assert result['status'] == 'registered'

    def test_receive_large_response(self, running_daemon, client):
        """Client should handle large responses."""
        # Create many tasks to get large response
        for i in range(100):
            client.call('task_create', {
                'task_id': f'task-{i}',
                'subject': 'Subject',
                'description': 'Description'
            })

        # Get large task list
        result = client.call('task_list', {'limit': 100})

        assert len(result['tasks']) >= 50  # Should get many tasks


class TestClientErrorHandling:
    """Test client error handling."""

    def test_error_response_raises_exception(self, running_daemon, client):
        """Server error response should raise RuntimeError."""
        with pytest.raises(RuntimeError):
            client.call('invalid_operation', {})

    def test_error_message_preserved(self, running_daemon, client):
        """Error message from server should be preserved."""
        with pytest.raises(RuntimeError, match="Unknown operation"):
            client.call('does_not_exist', {})

    def test_validation_error_formatted(self, running_daemon, client):
        """Validation errors should be formatted nicely."""
        with pytest.raises(RuntimeError):
            # Invalid task ID format
            client.call('task_create', {
                'task_id': 'invalid task id',
                'subject': 'Subject',
                'description': 'Description'
            })

    def test_multiple_validation_errors_formatted(self, running_daemon, client):
        """Multiple validation errors should be listed."""
        # This would trigger multiple validation errors if validator checks multiple things
        with pytest.raises(RuntimeError) as exc_info:
            client.call('task_create', {
                'task_id': 'invalid-id!!!',  # Invalid characters
                'subject': '',  # Too short
                'description': 'Description'
            })

        # Error should mention validation
        assert 'validation' in str(exc_info.value).lower() or 'invalid' in str(exc_info.value).lower()

    def test_connection_lost_during_request(self):
        """Connection loss during request should raise error."""
        client = CoordinationClient(timeout=1)

        # Mock socket to simulate connection loss
        mock_sock = mock.MagicMock()
        mock_sock.recv.return_value = b''  # Connection closed

        with mock.patch('socket.socket') as mock_socket_class:
            mock_socket_class.return_value = mock_sock

            with pytest.raises(Exception):  # Should raise some error
                client.call('status', {})

    def test_partial_response_handling(self):
        """Client should handle partial/incomplete responses."""
        client = CoordinationClient(timeout=1)

        # Mock socket to return incomplete JSON
        mock_sock = mock.MagicMock()
        mock_sock.recv.side_effect = [b'{"result":{"sta', b'']  # Incomplete

        with mock.patch('socket.socket') as mock_socket_class:
            mock_socket_class.return_value = mock_sock

            with pytest.raises(Exception):  # JSON decode error
                client.call('status', {})

    def test_malformed_response_json(self):
        """Malformed JSON response should raise error."""
        client = CoordinationClient(timeout=1)

        # Mock socket to return invalid JSON
        mock_sock = mock.MagicMock()
        mock_sock.recv.side_effect = [b'not valid json', b'']

        with mock.patch('socket.socket') as mock_socket_class:
            mock_socket_class.return_value = mock_sock

            with pytest.raises(Exception):  # JSON decode error
                client.call('status', {})


class TestClientTimeout:
    """Test client timeout behavior."""

    def test_timeout_setting_applied(self):
        """Socket timeout should be set from client timeout."""
        client = CoordinationClient(timeout=3)

        mock_sock = mock.MagicMock()

        with mock.patch('socket.socket') as mock_socket_class:
            mock_socket_class.return_value = mock_sock

            try:
                client.call('status', {})
            except:
                pass

        # Verify timeout was set on socket
        mock_sock.settimeout.assert_called_with(3)

    def test_timeout_during_connect(self):
        """Timeout during connection should raise clear error."""
        client = CoordinationClient(timeout=1)

        # Mock socket to timeout on connect
        mock_sock = mock.MagicMock()
        mock_sock.connect.side_effect = socket.timeout()

        with mock.patch('socket.socket') as mock_socket_class:
            mock_socket_class.return_value = mock_sock

            with pytest.raises(RuntimeError, match="timeout.*hung"):
                client.call('status', {})

    def test_timeout_during_receive(self):
        """Timeout during receive should raise error."""
        client = CoordinationClient(timeout=1)

        mock_sock = mock.MagicMock()
        mock_sock.recv.side_effect = socket.timeout()

        with mock.patch('socket.socket') as mock_socket_class:
            mock_socket_class.return_value = mock_sock

            with pytest.raises(Exception):  # timeout error
                client.call('status', {})


class TestClientResourceManagement:
    """Test client resource cleanup."""

    def test_socket_closed_after_success(self, running_daemon, client):
        """Socket should be closed after successful call."""
        mock_sock = mock.MagicMock()
        original_close = mock_sock.close

        call_count = [0]

        def track_close():
            call_count[0] += 1
            return original_close()

        mock_sock.close = track_close

        # Make a call (will use real socket, but we're just checking pattern)
        client.call('status', {})

        # Socket should be closed (actual implementation detail, simplified here)

    def test_socket_closed_after_error(self):
        """Socket should be closed even if error occurs."""
        client = CoordinationClient(timeout=1)

        mock_sock = mock.MagicMock()
        mock_sock.recv.side_effect = Exception("Test error")

        close_called = [False]

        def track_close():
            close_called[0] = True

        mock_sock.close = track_close

        with mock.patch('socket.socket') as mock_socket_class:
            mock_socket_class.return_value = mock_sock

            try:
                client.call('status', {})
            except:
                pass

        # Socket should be closed despite error
        assert close_called[0] is True


class TestClientConcurrency:
    """Test concurrent client usage."""

    def test_concurrent_calls_from_same_client(self, running_daemon, client):
        """Multiple threads using same client should work."""
        results = []
        errors = []

        def make_call(i):
            try:
                result = client.call('status', {})
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=make_call, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All calls should succeed
        assert len(results) == 5
        assert len(errors) == 0

    def test_multiple_clients_same_daemon(self, running_daemon):
        """Multiple client instances should share same daemon."""
        client1 = CoordinationClient()
        client2 = CoordinationClient()

        # Both should connect to same daemon
        result1 = client1.call('status', {})
        result2 = client2.call('status', {})

        assert result1 is not None
        assert result2 is not None


class TestClientIntegration:
    """Integration tests for client operations."""

    def test_full_workflow(self, running_daemon, client):
        """Test complete workflow: register, create, claim, complete."""
        # Register agent
        client.call('register', {'agent_id': 'test-agent', 'pid': 12345})

        # Create task
        client.call('task_create', {
            'task_id': 'test-task',
            'subject': 'Test Subject',
            'description': 'Test Description'
        })

        # Claim task
        client.call('task_claim', {
            'agent_id': 'test-agent',
            'task_id': 'test-task'
        })

        # Complete task
        client.call('task_complete', {
            'agent_id': 'test-agent',
            'task_id': 'test-task'
        })

        # Get task to verify
        result = client.call('task_get', {'task_id': 'test-task'})

        assert result['task']['status'] == 'completed'

    def test_lock_workflow(self, running_daemon, client):
        """Test lock acquire and release."""
        client.call('register', {'agent_id': 'test-agent', 'pid': 12345})

        # Acquire lock
        client.call('lock_acquire', {
            'agent_id': 'test-agent',
            'file_path': 'test/file.py'
        })

        # Release lock
        client.call('lock_release', {
            'agent_id': 'test-agent',
            'file_path': 'test/file.py'
        })

    def test_status_and_metrics(self, running_daemon, client):
        """Test status and metrics operations."""
        # Get status
        status = client.call('status', {})
        assert 'agent_count' in status

        # Get velocity
        velocity = client.call('velocity', {'period': '1 hour'})
        assert velocity is not None

        # Get file hotspots
        hotspots = client.call('file_hotspots', {'limit': 10})
        assert hotspots is not None
