"""The HTTP fixture must finish its handlers before another test captures stderr."""

import contextlib
import http.client
import io
import queue
import socket
import sys
import threading
from http.server import ThreadingHTTPServer

import pytest

from tests.test_tools import test_http


def _wait(event: threading.Event) -> None:
    assert event.wait(10), "lifecycle handshake did not arrive"


@pytest.mark.parametrize(
    ("handler_fails", "close_generator"),
    [(False, False), (True, False), (True, True)],
    ids=["clean-concurrent-requests", "handler-error", "interrupted-fixture"],
)
def test_http_fixture_finishes_before_the_next_stderr_capture(
    monkeypatch, handler_fails, close_generator,
):
    """One combined clean path, then the same lifetime with a real reported error.

    Join-entry handshakes (not sleeps) distinguish an accept loop from its
    request threads. The synthetic error uses socketserver's real handle_error;
    only its type/phase and banner presence are inspected, never its traceback.
    """
    handler_entered = threading.Event()
    release_handler = threading.Event()
    release_accept = threading.Event()
    progress: queue.Queue[str] = queue.Queue()
    joins = []
    request_threads = []
    request_sockets = []
    accept_threads = []
    errors = []
    teardown_errors = []
    servers = []
    phase = "owner"

    def observe_join(thread, kind):
        original = thread.join

        def join(timeout=None):
            joins.append(kind)
            progress.put(kind)
            original(timeout)

        monkeypatch.setattr(thread, "join", join)
        return original

    class DelayedHandler(test_http._Handler):
        def _send(self, code, body):
            if body == b"late":
                observe_join(threading.current_thread(), "request_join")
                handler_entered.set()
                _wait(release_handler)
                if handler_fails:
                    raise BrokenPipeError("synthetic disconnected client")
            super()._send(code, body)

    class ObservedServer(ThreadingHTTPServer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            servers.append(self)

        def serve_forever(self):
            thread = threading.current_thread()
            accept_threads.append((thread, observe_join(thread, "accept_join")))
            super().serve_forever()
            # shutdown() has returned, but this thread has not. The fixture
            # must join it too; waiting for the accept loop alone is not a join.
            _wait(release_accept)

        def process_request_thread(self, request, client_address):
            thread = threading.current_thread()
            request_threads.append((thread, thread.join))
            request_sockets.append(request)
            super().process_request_thread(request, client_address)

        def handle_error(self, request, client_address):
            errors.append((sys.exc_info()[0].__name__, phase))
            super().handle_error(request, client_address)

    monkeypatch.setattr(test_http, "ThreadingHTTPServer", ObservedServer)
    monkeypatch.setattr(test_http, "_Handler", DelayedHandler)
    fixture = test_http.server.__wrapped__()
    owner_stderr, next_stderr = io.StringIO(), io.StringIO()
    teardown = None
    delayed = None
    try:
        with contextlib.redirect_stderr(owner_stderr):
            next(fixture)
            server = servers[0]
            address = server.server_address
            delayed = socket.create_connection(address, timeout=10)
            delayed.sendall(b"GET /delay/0 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
            _wait(handler_entered)

            # A held handler must not block unrelated requests.
            with contextlib.closing(http.client.HTTPConnection(*address, timeout=10)) as other:
                other.request("GET", "/get", headers={"Connection": "close"})
                response = other.getresponse()
                assert response.status == 200
                assert response.read() == b"hello from the test server"

            def finish_fixture():
                try:
                    if close_generator:
                        fixture.close()
                    else:
                        assert next(fixture, None) is None
                except Exception as error:
                    teardown_errors.append(type(error).__name__)
                finally:
                    progress.put("teardown_returned")

            teardown = threading.Thread(target=finish_fixture)
            teardown.start()
            first = progress.get(timeout=10)
            if first == "request_join":
                release_handler.set()
                second = progress.get(timeout=10)
            else:
                # Broken lifetime: let teardown finish while the handler stays
                # held, then release that handler in the next test's capture.
                second = first
            release_accept.set()
            if second != "teardown_returned":
                assert progress.get(timeout=10) == "teardown_returned"
            teardown.join(10)
            alive_after_teardown = [
                thread.is_alive() for thread, _ in request_threads + accept_threads
            ]
            sockets_open_after_teardown = [sock.fileno() != -1 for sock in request_sockets]
            listener_open_after_teardown = server.socket.fileno() != -1

        with contextlib.redirect_stderr(next_stderr):
            phase = "next_capture"
            release_handler.set()
            for _, join in request_threads:
                join(10)
            # Also clean up the original fixture/mutations that skipped teardown.
            server.shutdown()
            server.server_close()
            for _, join in accept_threads:
                join(10)

        # Report metadata only on a failure, not captured exception material.
        owner_reported = "Exception occurred during processing of request from" in owner_stderr.getvalue()
        next_was_empty = not next_stderr.getvalue()
        assert next_was_empty, "handler error escaped into the following stderr capture"
        assert owner_reported is handler_fails
        assert errors == ([("BrokenPipeError", "owner")] if handler_fails else [])
        assert first == "request_join", "teardown did not wait for its active handler"
        assert second == "accept_join", "teardown did not join its serving thread"
        assert not any(alive_after_teardown)
        assert not any(sockets_open_after_teardown)
        assert not listener_open_after_teardown
        assert not teardown_errors
        assert not teardown.is_alive()
        assert joins[:2] == ["request_join", "accept_join"]
        received = b"".join(iter(lambda: delayed.recv(1024), b""))
        if handler_fails:
            assert not received
        else:
            assert received.endswith(b"late")
    finally:
        release_handler.set()
        release_accept.set()
        if delayed is not None:
            delayed.close()
        for server in servers:
            server.shutdown()
            server.server_close()
        for _, join in request_threads + accept_threads:
            join(10)
        if teardown is not None:
            teardown.join(10)
        fixture.close()
