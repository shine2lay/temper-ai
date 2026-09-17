"""The webhook fires on the right events, and never harms the run.

The failure mode that matters is not a missed notification — it is a
finished workflow being disturbed because an endpoint was slow or wrong.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from temper_ai.observability.webhook_notifier import WebhookNotifier, configured_url


class _Handler(BaseHTTPRequestHandler):
    received: list = []
    status = 200
    fail_times = 0

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).received.append(body)
        if type(self).fail_times > 0:
            type(self).fail_times -= 1
            self.send_response(500)
        else:
            self.send_response(type(self).status)
        self.end_headers()

    def log_message(self, *args):  # silence the test server
        pass


@pytest.fixture
def endpoint():
    _Handler.received = []
    _Handler.status = 200
    _Handler.fail_times = 0
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/hook", _Handler
    server.shutdown()


def _finish(notifier, execution_id, *, status="completed", **data):
    """Drive the sequence this engine actually produces.

    A run emits workflow.started and later *updates* that event's status;
    there is no workflow.completed event. Tests that invented one passed
    while the feature did nothing in a real run.
    """
    notifier.notify_event(execution_id, "workflow.started", {"event_id": "root-1", **data})
    notifier.notify_event(
        execution_id, "event.updated", {"event_id": "root-1", "status": status, **data}
    )


def test_posts_on_completion_with_what_a_receiver_needs(endpoint):
    url, handler = endpoint
    _finish(
        WebhookNotifier(url, blocking=True),
        "run-1",
        name="nightly", duration_seconds=12.5, cost_usd=0.42, total_tokens=1000,
    )
    assert len(handler.received) == 1
    body = handler.received[0]
    assert body["status"] == "completed"
    # The receiver sees an outcome, not our internal update mechanism.
    assert body["event"] == "workflow.completed"
    assert body["execution_id"] == "run-1"
    assert body["workflow"] == "nightly"
    assert body["duration_seconds"] == 12.5
    assert body["total_cost_usd"] == 0.42


def test_carries_the_error_on_failure(endpoint):
    url, handler = endpoint
    _finish(WebhookNotifier(url, blocking=True), "run-2", status="failed",
            name="nightly", error="boom")
    assert handler.received[0]["event"] == "workflow.failed"
    assert handler.received[0]["status"] == "failed"
    assert handler.received[0]["error"] == "boom"


def test_ignores_the_hundreds_of_events_that_are_not_outcomes(endpoint):
    url, handler = endpoint
    notifier = WebhookNotifier(url, blocking=True)
    notifier.notify_event("run-3", "workflow.started", {"event_id": "root-1"})
    for event in ("agent.started", "llm.call.completed", "stage.started"):
        notifier.notify_event("run-3", event, {"status": "completed"})
    # A node event updating its own status must not be read as the run ending.
    notifier.notify_event("run-3", "event.updated", {"event_id": "some-node", "status": "completed"})
    assert handler.received == []


def test_retries_a_server_error_then_succeeds(endpoint):
    url, handler = endpoint
    handler.fail_times = 2
    _finish(WebhookNotifier(url, blocking=True), "run-4")
    assert len(handler.received) == 3, "should have retried twice before succeeding"


def test_does_not_retry_a_rejection(endpoint):
    """4xx is a configuration problem; repeating it just makes noise."""
    url, handler = endpoint
    handler.status = 400
    _finish(WebhookNotifier(url, blocking=True), "run-5")
    assert len(handler.received) == 1


def test_an_unreachable_endpoint_does_not_raise():
    """A finished run must not be disturbed because nobody answered."""
    notifier = WebhookNotifier("http://127.0.0.1:1/never", blocking=True)
    _finish(notifier, "run-6")  # must not raise
    notifier.cleanup("run-6")


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("TEMPER_WEBHOOK_URL", raising=False)
    assert configured_url() is None
    assert WebhookNotifier().enabled is False


def test_a_non_http_url_is_refused(monkeypatch):
    monkeypatch.setenv("TEMPER_WEBHOOK_URL", "file:///etc/passwd")
    assert configured_url() is None


def test_fires_once_even_if_the_root_event_updates_again(endpoint):
    url, handler = endpoint
    notifier = WebhookNotifier(url, blocking=True)
    _finish(notifier, "run-7", name="nightly")
    notifier.notify_event("run-7", "event.updated", {"event_id": "root-1", "status": "completed"})
    assert len(handler.received) == 1
