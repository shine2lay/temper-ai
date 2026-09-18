"""Tests for the HTTP tool.

These used to call httpbin.org. That made an unrelated third-party outage able
to fail the suite — and since the pre-commit hook runs pytest, a bad day at
httpbin blocked every commit in the repo (it returned 502 during this change).

They now run against a throwaway HTTP server started in-process on an ephemeral
port, so they are still *real* httpx round-trips through the real tool — status
parsing, truncation, timeout, connect error — with nothing outside the machine.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from temper_ai.tools.http import _MAX_RESPONSE_SIZE, Http


class _Handler(BaseHTTPRequestHandler):
    """Just enough of httpbin: /get, /post, /status/<code>, /delay/<s>, /big."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # keep pytest output clean
        pass

    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/get":
            self._send(200, b"hello from the test server")
        elif self.path.startswith("/status/"):
            self._send(int(self.path.rsplit("/", 1)[1]), b"status")
        elif self.path.startswith("/delay/"):
            # Longer than any timeout under test; the client gives up first.
            threading.Event().wait(float(self.path.rsplit("/", 1)[1]))
            self._send(200, b"late")
        elif self.path == "/big":
            self._send(200, b"x" * (_MAX_RESPONSE_SIZE + 500))
        else:
            self._send(404, b"not found")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self._send(200, b"echo:" + body)


@pytest.fixture(scope="module")
def server() -> Any:
    """A threading server on an ephemeral port (threading: /delay must not block others)."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    yield f"http://{host}:{port}"
    httpd.shutdown()
    httpd.server_close()


class TestHttpBasics:
    def test_get_request(self, server):
        result = Http(timeout=10).execute(method="GET", url=f"{server}/get")
        assert result.success
        assert "HTTP 200" in result.result
        assert "hello from the test server" in result.result

    def test_post_request(self, server):
        result = Http(timeout=10).execute(
            method="POST",
            url=f"{server}/post",
            body='{"test": true}',
            headers={"Content-Type": "application/json"},
        )
        assert result.success
        assert "HTTP 200" in result.result
        assert 'echo:{"test": true}' in result.result

    def test_404_returns_error(self, server):
        result = Http(timeout=10).execute(method="GET", url=f"{server}/status/404")
        assert not result.success
        assert "HTTP 404" in result.error

    def test_large_response_is_truncated(self, server):
        """Previously untestable without a cooperative remote."""
        result = Http(timeout=10).execute(method="GET", url=f"{server}/big")
        assert result.success
        assert "truncated" in result.result
        assert len(result.result) < _MAX_RESPONSE_SIZE + 500


class TestHttpSafety:
    def test_domain_allowlist_blocks(self):
        """Offline by construction: rejected before any request is made."""
        result = Http(allowed_domains=["example.com"]).execute(method="GET", url="https://evil.com/steal")
        assert not result.success
        assert "not in allowed" in result.error

    def test_domain_allowlist_allows(self, server):
        result = Http(allowed_domains=["127.0.0.1"], timeout=10).execute(method="GET", url=f"{server}/get")
        assert result.success

    def test_timeout(self, server):
        result = Http(timeout=1).execute(method="GET", url=f"{server}/delay/5")
        assert not result.success
        assert "timed out" in result.error

    def test_connection_error(self):
        """Port 1 on loopback: nothing listens, no network needed."""
        result = Http(timeout=2).execute(method="GET", url="http://127.0.0.1:1")
        assert not result.success
        assert "Connection failed" in result.error or "error" in result.error.lower()
