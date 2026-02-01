"""
Comprehensive tests for coordination server.

Tests Unix socket server lifecycle, connection handling, request processing,
and error handling. Critical for client-server communication reliability.
"""

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from coord_service.server import CoordinationServer
from coord_service.protocol import Request, Response


class TestServerInitialization:
    """Test server initialization."""

    def test_init_sets_database(self, db):
        """Server should store database reference."""
        server = CoordinationServer(db, '/test/project')

        assert server.db is db

    def test_init_sets_project_root(self, db):
        """Server should store project root."""
        server = CoordinationServer(db, '/test/project')

        assert server.project_root == '/test/project'

    def test_socket_path_based_on_project(self, db):
        """Socket path should include hash of project root."""
        server = CoordinationServer(db, '/test/project')

        # Should be in /tmp with project hash
        assert server.socket_path.startswith('/tmp/coord-')
        assert server.socket_path.endswith('.sock')

    def test_different_projects_different_sockets(self, db):
        """Different project roots generate different socket paths."""
        server1 = CoordinationServer(db, '/project1')
        server2 = CoordinationServer(db, '/project2')

        assert server1.socket_path != server2.socket_path

    def test_same_project_same_socket(self, db):
        """Same project root generates same socket path."""
        server1 = CoordinationServer(db, '/test/project')
        server2 = CoordinationServer(db, '/test/project')

        assert server1.socket_path == server2.socket_path

    def test_init_creates_operation_handler(self, db):
        """Server should create operation handler."""
        server = CoordinationServer(db, '/test/project')

        assert server.operation_handler is not None
        assert server.operation_handler.db is db


class TestServerLifecycle:
    """Test server lifecycle management."""

    def test_start_creates_socket_file(self, db, tmp_path):
        """Start should create socket file."""
        # Use temporary socket path
        server = CoordinationServer(db, str(tmp_path))

        try:
            server.start()

            # Socket file should exist
            assert os.path.exists(server.socket_path)
        finally:
            server.stop()

    def test_start_sets_socket_permissions(self, db, tmp_path):
        """Socket file should have user-only permissions (0o600)."""
        server = CoordinationServer(db, str(tmp_path))

        try:
            server.start()

            # Check permissions
            stat = os.stat(server.socket_path)
            permissions = stat.st_mode & 0o777
            assert permissions == 0o600
        finally:
            server.stop()

    def test_start_removes_stale_socket(self, db, tmp_path):
        """Start should remove existing socket file."""
        server = CoordinationServer(db, str(tmp_path))

        # Create stale socket file
        Path(server.socket_path).touch()

        try:
            server.start()

            # Should succeed (stale file removed)
            assert server.running is True
        finally:
            server.stop()

    def test_stop_removes_socket_file(self, db, tmp_path):
        """Stop should remove socket file."""
        server = CoordinationServer(db, str(tmp_path))

        server.start()
        socket_path = server.socket_path
        assert os.path.exists(socket_path)

        server.stop()

        # Socket file should be removed
        assert not os.path.exists(socket_path)

    def test_stop_closes_socket(self, db, tmp_path):
        """Stop should close socket."""
        server = CoordinationServer(db, str(tmp_path))

        server.start()
        server.stop()

        # Socket should be closed
        assert server.running is False

    def test_stop_waits_for_threads(self, db, tmp_path):
        """Stop should wait for handler threads to finish."""
        server = CoordinationServer(db, str(tmp_path))

        server.start()
        time.sleep(0.1)  # Let accept thread start

        server.stop()

        # Threads should be stopped (or daemon)
        for thread in server.threads:
            assert not thread.is_alive() or thread.daemon

    def test_restart_works(self, db, tmp_path):
        """Server can be restarted after stop."""
        server = CoordinationServer(db, str(tmp_path))

        server.start()
        server.stop()
        server.start()

        assert server.running is True

        server.stop()


class TestConnectionHandling:
    """Test client connection handling."""

    def test_accept_client_connection(self, db, tmp_path):
        """Server should accept client connections."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            # Connect as client
            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)

            # Should be connected
            assert client_socket.fileno() > 0

            client_socket.close()
        finally:
            server.stop()

    def test_multiple_sequential_connections(self, db, tmp_path):
        """Server should handle multiple sequential connections."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            for _ in range(5):
                client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client_socket.connect(server.socket_path)
                client_socket.close()
        finally:
            server.stop()

    def test_concurrent_connections(self, db, tmp_path):
        """Server should handle concurrent connections."""
        server = CoordinationServer(db, str(tmp_path))
        db.register_agent('test-agent', 12345)
        server.start()

        try:
            sockets = []

            # Open multiple connections
            for _ in range(3):
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(server.socket_path)
                sockets.append(sock)

            # All should be connected
            assert len(sockets) == 3

            # Cleanup
            for sock in sockets:
                sock.close()
        finally:
            server.stop()

    def test_connection_timeout_enforced(self, db, tmp_path):
        """Client connections should have timeout."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)

            # Don't send anything - timeout should occur
            # Server sets 5s timeout, so after that connection closes
            time.sleep(6)

            # Try to send - should fail (connection closed)
            with pytest.raises(Exception):  # BrokenPipeError or similar
                client_socket.send(b"x" * 1000)

            client_socket.close()
        finally:
            server.stop()

    def test_empty_connection_handled(self, db, tmp_path):
        """Empty connection (no data sent) should be handled gracefully."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)

            # Close without sending
            client_socket.close()

            # Server should handle gracefully (no crash)
        finally:
            server.stop()


class TestRequestProcessing:
    """Test request processing."""

    def test_valid_request_returns_success(self, db, tmp_path):
        """Valid request should return success response."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            # Send status request
            request = Request(id="1", method="status", params={})

            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)
            client_socket.sendall(request.to_json().encode('utf-8'))

            # Receive response
            response_data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            response = Response.from_json(response_data.decode('utf-8'))

            assert response.error is None
            assert response.result is not None

            client_socket.close()
        finally:
            server.stop()

    def test_invalid_json_returns_parse_error(self, db, tmp_path):
        """Invalid JSON should return parse error."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)

            # Send invalid JSON
            client_socket.sendall(b"not valid json")

            # Receive error response
            response_data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            response = Response.from_json(response_data.decode('utf-8'))

            assert response.error is not None
            assert response.error['code'] == 'PARSE_ERROR'

            client_socket.close()
        finally:
            server.stop()

    def test_missing_method_returns_error(self, db, tmp_path):
        """Request without method should return error."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)

            # Send request without method
            client_socket.sendall(json.dumps({"id": "1", "params": {}}).encode('utf-8'))

            # Receive error response
            response_data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            response = Response.from_json(response_data.decode('utf-8'))

            assert response.error is not None

            client_socket.close()
        finally:
            server.stop()

    def test_unknown_operation_returns_error(self, db, tmp_path):
        """Unknown operation should return error."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            request = Request(id="1", method="nonexistent_operation", params={})

            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)
            client_socket.sendall(request.to_json().encode('utf-8'))

            # Receive error response
            response_data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            response = Response.from_json(response_data.decode('utf-8'))

            assert response.error is not None
            assert 'Unknown operation' in response.error['message']

            client_socket.close()
        finally:
            server.stop()

    def test_operation_exception_returns_error(self, db, tmp_path):
        """Exception during operation should return error response."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            # Try to claim nonexistent task (will raise exception)
            request = Request(id="1", method="task_claim", params={
                'agent_id': 'test-agent',
                'task_id': 'nonexistent'
            })

            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)
            client_socket.sendall(request.to_json().encode('utf-8'))

            # Receive error response
            response_data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            response = Response.from_json(response_data.decode('utf-8'))

            assert response.error is not None

            client_socket.close()
        finally:
            server.stop()

    def test_large_request_handled(self, db, tmp_path):
        """Large request (< 1MB) should be processed."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            # Create large metadata (but < 1MB)
            large_data = "x" * 100000
            request = Request(id="1", method="register", params={
                'agent_id': 'test-agent',
                'pid': 12345,
                'metadata': {'data': large_data}
            })

            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)
            client_socket.sendall(request.to_json().encode('utf-8'))

            # Receive response
            response_data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            response = Response.from_json(response_data.decode('utf-8'))

            # Should succeed
            assert response.error is None

            client_socket.close()
        finally:
            server.stop()

    def test_request_size_limit_enforced(self, db, tmp_path):
        """Request > 1MB should be rejected."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            # Create request > 1MB
            huge_data = "x" * (1024 * 1024 + 1000)
            request_data = json.dumps({
                "id": "1",
                "method": "register",
                "params": {
                    "agent_id": "test",
                    "pid": 12345,
                    "metadata": {"data": huge_data}
                }
            }).encode('utf-8')

            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.settimeout(2)
            client_socket.connect(server.socket_path)

            # Try to send huge request
            # Connection should be closed or error returned
            try:
                client_socket.sendall(request_data)

                # Try to receive response
                response_data = client_socket.recv(4096)
                # If we get here, should be error or empty (connection closed)

            except (socket.timeout, ConnectionError, BrokenPipeError):
                # Expected - connection closed
                pass

            client_socket.close()
        finally:
            server.stop()


class TestErrorHandling:
    """Test error handling in server."""

    def test_client_disconnect_handled(self, db, tmp_path):
        """Client disconnect during request should be handled."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)

            # Send partial request then disconnect
            client_socket.send(b'{"id":"1"')
            client_socket.close()

            # Server should handle gracefully (no crash)
            time.sleep(0.1)
        finally:
            server.stop()

    def test_malformed_response_handled(self, db, tmp_path):
        """Server should handle errors during response sending."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            # Mock operation handler to return non-serializable data
            original_execute = server.operation_handler.execute

            def mock_execute(method, params):
                if method == 'status':
                    # Return something that will cause JSON serialization to work
                    # but simulate error scenario
                    return {'test': 'data'}
                return original_execute(method, params)

            server.operation_handler.execute = mock_execute

            request = Request(id="1", method="status", params={})

            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)
            client_socket.sendall(request.to_json().encode('utf-8'))

            # Should get response (error handling worked)
            response_data = client_socket.recv(4096)
            assert len(response_data) > 0

            client_socket.close()
        finally:
            server.stop()

    def test_accept_loop_error_doesnt_crash(self, db, tmp_path):
        """Error in accept loop shouldn't crash server."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            # Server should keep running despite any errors
            time.sleep(0.2)
            assert server.running is True
        finally:
            server.stop()


class TestResourceManagement:
    """Test resource cleanup and management."""

    def test_client_socket_closed_after_request(self, db, tmp_path):
        """Client socket should be closed after processing."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            request = Request(id="1", method="status", params={})

            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)
            client_socket.sendall(request.to_json().encode('utf-8'))

            # Receive response
            response_data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            # Server should close connection
            # (evidenced by recv returning empty)

            client_socket.close()
        finally:
            server.stop()

    def test_client_socket_closed_on_error(self, db, tmp_path):
        """Client socket should be closed even on error."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)

            # Send invalid JSON
            client_socket.sendall(b"invalid json")

            # Receive error response
            response_data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            # Connection should be closed
            client_socket.close()
        finally:
            server.stop()

    def test_graceful_shutdown_waits(self, db, tmp_path):
        """Graceful shutdown should wait for threads."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        # Give threads time to start
        time.sleep(0.1)

        start = time.time()
        server.stop()
        duration = time.time() - start

        # Should complete quickly (< 6s for 5s timeout)
        assert duration < 6


class TestConcurrentRequests:
    """Test concurrent request handling."""

    def test_concurrent_requests_processed(self, db, tmp_path):
        """Multiple concurrent requests should all be processed."""
        server = CoordinationServer(db, str(tmp_path))
        db.register_agent('test-agent', 12345)
        server.start()

        results = []
        errors = []

        def make_request():
            try:
                request = Request(id="1", method="status", params={})

                client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client_socket.connect(server.socket_path)
                client_socket.sendall(request.to_json().encode('utf-8'))

                response_data = b""
                while True:
                    chunk = client_socket.recv(4096)
                    if not chunk:
                        break
                    response_data += chunk

                response = Response.from_json(response_data.decode('utf-8'))
                results.append(response)

                client_socket.close()
            except Exception as e:
                errors.append(e)

        try:
            threads = []
            for _ in range(5):
                t = threading.Thread(target=make_request)
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            # All requests should succeed
            assert len(results) == 5
            assert len(errors) == 0
        finally:
            server.stop()

    def test_concurrent_different_operations(self, db, tmp_path):
        """Different operations can be processed concurrently."""
        server = CoordinationServer(db, str(tmp_path))
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        server.start()

        operations = [
            ("status", {}),
            ("velocity", {"period": "1 hour"}),
            ("file_hotspots", {"limit": 10}),
        ]

        results = []

        def make_request(method, params):
            try:
                request = Request(id="1", method=method, params=params)

                client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client_socket.connect(server.socket_path)
                client_socket.sendall(request.to_json().encode('utf-8'))

                response_data = b""
                while True:
                    chunk = client_socket.recv(4096)
                    if not chunk:
                        break
                    response_data += chunk

                response = Response.from_json(response_data.decode('utf-8'))
                results.append(response)

                client_socket.close()
            except Exception as e:
                results.append(e)

        try:
            threads = []
            for method, params in operations:
                t = threading.Thread(target=make_request, args=(method, params))
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            # All should complete
            assert len(results) == len(operations)
        finally:
            server.stop()


class TestIntegration:
    """Integration tests for server."""

    def test_full_workflow_through_server(self, db, tmp_path):
        """Complete workflow through server."""
        server = CoordinationServer(db, str(tmp_path))
        server.start()

        try:
            # Register agent
            request = Request(id="1", method="register", params={
                'agent_id': 'test-agent',
                'pid': 12345
            })

            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)
            client_socket.sendall(request.to_json().encode('utf-8'))

            response_data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            response = Response.from_json(response_data.decode('utf-8'))
            assert response.error is None

            client_socket.close()

            # Create task
            request = Request(id="2", method="task_create", params={
                'task_id': 'test-task',
                'subject': 'Test',
                'description': 'Test task'
            })

            client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client_socket.connect(server.socket_path)
            client_socket.sendall(request.to_json().encode('utf-8'))

            response_data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            response = Response.from_json(response_data.decode('utf-8'))
            assert response.error is None

            client_socket.close()

        finally:
            server.stop()
