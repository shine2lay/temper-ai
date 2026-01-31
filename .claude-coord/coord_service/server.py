"""
Unix socket server for coordination service.

Handles client connections and request processing.
"""

import hashlib
import json
import os
import socket
import threading
from pathlib import Path
from typing import Optional

from .operations import OperationHandler
from .protocol import Request, Response, ParseError, InvalidRequest


class CoordinationServer:
    """Unix socket server for coordination requests."""

    def __init__(self, db, project_root: str):
        """Initialize server.

        Args:
            db: Database instance
            project_root: Project root directory
        """
        self.db = db
        self.operation_handler = OperationHandler(db)
        self.project_root = project_root

        # Generate socket path based on project
        project_hash = hashlib.sha256(project_root.encode()).hexdigest()[:8]
        self.socket_path = f"/tmp/coord-{project_hash}.sock"

        self.socket: Optional[socket.socket] = None
        self.running = False
        self.threads = []

    def start(self):
        """Start the server."""
        # Remove existing socket file
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        # Create Unix socket
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(self.socket_path)
        self.socket.listen(5)

        # Set permissions (user only)
        os.chmod(self.socket_path, 0o600)

        self.running = True

        # Start accepting connections
        accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        accept_thread.start()
        self.threads.append(accept_thread)

    def stop(self):
        """Stop the server."""
        self.running = False

        if self.socket:
            self.socket.close()

        # Remove socket file
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        # Wait for threads
        for thread in self.threads:
            thread.join(timeout=5)

    def _accept_loop(self):
        """Accept client connections."""
        while self.running:
            try:
                client_socket, _ = self.socket.accept()

                # Handle client in new thread
                handler_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket,),
                    daemon=True
                )
                handler_thread.start()
                self.threads.append(handler_thread)

            except Exception as e:
                if self.running:
                    print(f"Error accepting connection: {e}")

    def _handle_client(self, client_socket: socket.socket):
        """Handle a client connection.

        Args:
            client_socket: Client socket
        """
        try:
            # Receive request (up to 1MB)
            # Read until we have a complete JSON message
            client_socket.settimeout(5.0)  # 5 second timeout
            data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                data += chunk
                if len(data) > 1024 * 1024:  # 1MB limit
                    raise ValueError("Request too large")

                # Try to parse as JSON - if successful, we have complete message
                try:
                    data.decode('utf-8')
                    import json as json_module
                    json_module.loads(data.decode('utf-8'))
                    # Successfully parsed - we have complete message
                    break
                except (json_module.JSONDecodeError, UnicodeDecodeError):
                    # Need more data
                    continue

            if not data:
                return

            # Parse request
            try:
                request = Request.from_json(data.decode('utf-8'))
            except json.JSONDecodeError as e:
                response = Response.create_error(
                    "parse_error",
                    "PARSE_ERROR",
                    f"Invalid JSON: {e}"
                )
                client_socket.sendall(response.to_json().encode('utf-8'))
                return
            except Exception as e:
                response = Response.create_error(
                    "invalid_request",
                    "INVALID_REQUEST",
                    str(e)
                )
                client_socket.sendall(response.to_json().encode('utf-8'))
                return

            # Execute operation
            try:
                result = self.operation_handler.execute(
                    request.method,
                    request.params
                )
                response = Response.success(request.id, result)

            except Exception as e:
                response = Response.create_error(
                    request.id,
                    type(e).__name__,
                    str(e),
                    data=getattr(e, 'to_dict', lambda: {})()
                )

            # Send response
            client_socket.sendall(response.to_json().encode('utf-8'))

        except Exception as e:
            print(f"Error handling client: {e}")

        finally:
            client_socket.close()
