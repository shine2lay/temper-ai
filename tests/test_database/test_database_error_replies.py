"""What temper sends out about a database error carries its safe text, never its values.

Every site that turns a caught error into text leaving temper (an HTTP reply, an MCP
tool's error or result, a Slack or Telegram reply, a status's last error, a hook's or a
trigger's recorded outcome) is made to catch a real database error with a made-up
marker in its row (tests/test_database/made_up_database_errors.py). Its text is the
error's safe text (docs/database-error-text.md), never the marker. Stored copies (a
notice's failed detail, a trigger fire's detail) stay whole: they stay in the database.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from mcp.server.fastmcp.exceptions import ToolError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.testclient import TestClient

from temper_ai.api import hooks, routes, studio, team_routes
from temper_ai.api.http_error_reply import http_error_without_database_values
from temper_ai.integrations.inbox.service import Sweeper
from temper_ai.integrations.notify import loop as notify_loop
from temper_ai.integrations.notify import service as notify_service
from temper_ai.integrations.slack import door as slack_door
from temper_ai.integrations.slack import e2e as slack_e2e
from temper_ai.integrations.slack.handlers import Handler as SlackHandler
from temper_ai.integrations.slack.ops import OpsError, TemperOps
from temper_ai.integrations.slack.socket import SocketMode
from temper_ai.integrations.telegram.handlers import Handler as TelegramHandler
from temper_ai.integrations.telegram.poller import Poller
from temper_ai.mcp import server as mcp_server
from temper_ai.mcp.tools import TemperTools
from temper_ai.pi_agent import team_trials
from temper_ai.shared.database_error_text import (
    error_line_without_database_values,
    text_without_database_values,
)
from temper_ai.triggers import linear
from temper_ai.triggers import scheduler as trigger_scheduler
from tests.test_api.test_github_hooks import CONFIGS, labeled
from tests.test_api.test_linear_hooks import (
    COMMENT_RULE,
    RULE,
    _comment,
    _event,
    _record,
)
from tests.test_database.made_up_database_errors import MARKER, missing_name_error


@pytest.fixture
def err():
    return missing_name_error()


@pytest.fixture
def safe(err):
    """The error's safe text; the error's own text still carries the marker."""
    shown = text_without_database_values(err)
    assert MARKER in str(err) and MARKER not in shown
    return shown


@pytest.fixture
def line(err, safe):
    """A status's last error: the error's class and its safe text."""
    shown = error_line_without_database_values(err)
    assert shown == f"{type(err).__name__}: {safe}"
    return shown


def raising(exc: BaseException):
    def raise_it(*_args, **_kwargs):
        raise exc

    return raise_it


def http_error_from(err, status: int = 400, detail=None) -> HTTPException:
    """An HTTPException raised from ``err``, as a route raises one."""
    try:
        raise err
    except Exception as caught:
        try:
            raise HTTPException(status, detail=detail if detail is not None else f"could not save it: {caught}") from caught
        except HTTPException as http_error:
            return http_error


# -- HTTP replies --------------------------------------------------------------------


def test_an_http_error_raised_from_a_database_error_answers_with_its_safe_text(err, safe):
    """The handler the server puts on every HTTPException (temper_ai/server.py)."""
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, http_error_without_database_values)

    @app.get("/text")
    def text_detail():
        raise http_error_from(err)

    @app.get("/body")
    def body_detail():
        raise http_error_from(err, 409, {"message": f"could not save it: {err}", "kept": "yes"})

    @app.get("/plain")
    def plain():
        raise HTTPException(404, detail=f"no workflow {MARKER}", headers={"X-Kept": "1"})

    client = TestClient(app)
    reply = client.get("/text")
    assert (reply.status_code, reply.json()) == (400, {"detail": f"could not save it: {safe}"})
    reply = client.get("/body")
    assert (reply.status_code, reply.json()) == (409, {"detail": {"message": f"could not save it: {safe}", "kept": "yes"}})
    reply = client.get("/plain")  # no database error behind it: answered as it was
    assert (reply.status_code, reply.json(), reply.headers["x-kept"]) == (404, {"detail": f"no workflow {MARKER}"}, "1")
    assert client.get("/nowhere").json() == {"detail": "Not Found"}


def test_a_studio_check_that_fails_on_the_database_lists_the_safe_text(monkeypatch, err, safe):
    store = SimpleNamespace(put=raising(err), delete=lambda *_args: None)
    monkeypatch.setattr(studio, "_store", lambda: store)

    reply = studio.validate_config("workflow", studio.ConfigBody(config={"workflow": {"name": "w"}}))

    assert reply["errors"] == [safe]


def test_a_team_trial_start_refused_by_a_database_error_says_its_safe_text(monkeypatch, err, safe):
    monkeypatch.setattr(routes, "_start_run", raising(http_error_from(err)))
    monkeypatch.setattr(team_trials, "undo", lambda *_args: None)
    row = {"workflow": "w", "goal": "g", "execution_id": "e-1", "project": None, "trial_id": "t-1", "request_id": "r-1"}

    with pytest.raises(team_routes.TeamRefusal) as refused:
        team_routes._finish_start(None, row, None, notes=[], repeated=False)

    assert refused.value.body["problems"] == [{"field": None, "text": f"could not save it: {safe}"}]


# -- hooks ---------------------------------------------------------------------------


@pytest.fixture
def linear_rules(tmp_path, monkeypatch):
    folder = tmp_path / "triggers"
    folder.mkdir()
    (folder / "reply.yaml").write_text(RULE.format(name="reply", workflow="linear_reply", ignore_self="true"))
    (folder / "work_comment.yaml").write_text(COMMENT_RULE)
    monkeypatch.setattr(linear, "app_user_id", lambda: "temper-app")
    hooks.reset_state()
    yield tmp_path
    hooks.reset_state()


def test_a_linear_delivery_that_fails_records_the_safe_text(monkeypatch, err, safe):
    monkeypatch.setattr(hooks, "load_triggers", raising(err))

    record = hooks.dispatch(_event(), _record(_event()))

    assert record["outcome"] == f"error: {safe}"


@pytest.mark.parametrize("raised", ["database error", "HTTP error from it"])
def test_a_linear_rule_whose_start_fails_records_the_safe_text(raised, linear_rules, monkeypatch, err, safe):
    monkeypatch.setattr(routes, "start_run", raising(err if raised == "database error" else http_error_from(err)))

    record = hooks.dispatch(_event(), _record(_event()), config_dir=linear_rules)

    [run] = record["runs"]
    assert run["error"] == (safe if raised == "database error" else f"could not save it: {safe}")
    assert MARKER not in record["outcome"]


def test_a_linear_app_user_lookup_that_fails_records_the_safe_text(linear_rules, monkeypatch, err, safe):
    monkeypatch.setattr(linear, "app_user_id", raising(err))

    record = hooks.dispatch(_event(), _record(_event()), config_dir=linear_rules)

    assert record["outcome"] == f"skipped: could not ask Linear who temper's app user is ({safe})"


def test_a_linear_comment_whose_issue_cannot_be_read_records_the_safe_text(linear_rules, monkeypatch, err, safe):
    monkeypatch.setattr(linear, "enrich", raising(err))

    record = hooks.dispatch(_comment(), _record(_comment()), config_dir=linear_rules)

    assert record["outcome"] == f"skipped: could not read the comment's issue ({safe})"


def test_a_github_delivery_that_fails_records_the_safe_text(monkeypatch, err, safe):
    monkeypatch.setattr(hooks, "load_triggers", raising(err))

    record = hooks.github_dispatch(*labeled(), {"delivery": "d", "runs": []})

    assert record["outcome"] == f"error: {safe}"


@pytest.mark.parametrize("raised", ["database error", "HTTP error from it"])
def test_a_github_rule_whose_start_fails_records_the_safe_text(raised, monkeypatch, err, safe):
    monkeypatch.setattr(routes, "start_run", raising(err if raised == "database error" else http_error_from(err)))
    monkeypatch.setattr(hooks, "_run_still_going", lambda _eid: None)
    hooks.reset_state()

    record = hooks.github_dispatch(*labeled(), {"delivery": "d", "runs": []}, config_dir=CONFIGS)

    errors = [run["error"] for run in record["runs"] if "error" in run]
    assert errors and set(errors) == {safe if raised == "database error" else f"could not save it: {safe}"}
    assert MARKER not in record["outcome"]


# -- MCP -----------------------------------------------------------------------------


def test_an_mcp_tool_that_fails_on_the_database_answers_with_its_safe_text(monkeypatch, err, safe):
    monkeypatch.setattr(TemperTools, "list_workflows", raising(err))

    with pytest.raises(ToolError) as failed:
        asyncio.run(mcp_server.build_server().call_tool("list_workflows", {}))

    assert str(failed.value) == f"Error executing tool list_workflows: {safe}"


def test_waiting_for_a_run_that_fails_on_the_database_answers_with_its_safe_text(monkeypatch, err, safe):
    async def wait_for_run(self, execution_id, timeout_seconds=120.0):
        raise err

    monkeypatch.setattr(TemperTools, "wait_for_run", wait_for_run)

    with pytest.raises(ToolError) as failed:
        asyncio.run(mcp_server.build_server().call_tool("wait_for_run", {"execution_id": "e-1"}))

    assert str(failed.value) == f"Error executing tool wait_for_run: {safe}"


def test_an_mcp_tools_other_errors_pass_unchanged(monkeypatch):
    monkeypatch.setattr(TemperTools, "list_workflows", raising(ValueError(f"no such name {MARKER}")))

    with pytest.raises(ToolError) as failed:
        asyncio.run(mcp_server.build_server().call_tool("list_workflows", {}))

    assert str(failed.value) == f"Error executing tool list_workflows: no such name {MARKER}"


def test_a_workflow_whose_config_cannot_be_read_is_listed_with_the_safe_text(monkeypatch, err, safe):
    store = SimpleNamespace(list=lambda config_type: [{"name": "w"}], get=raising(err))
    monkeypatch.setattr(routes, "_state", lambda: SimpleNamespace(config_store=store))

    listed = TemperTools().list_workflows()

    assert [w["summary"] for w in listed["workflows"]] == [f"(config could not be read: {safe})"]


def test_events_that_cannot_be_read_answer_with_the_safe_text(monkeypatch, err, safe):
    from temper_ai.observability import recorder

    monkeypatch.setattr(recorder, "get_events", raising(err))

    assert TemperTools().get_events("e-1") == {"error": f"could not read events: {safe}"}


@pytest.mark.parametrize("detail", ["text", "body"])
def test_a_gate_approval_refused_by_a_database_error_answers_with_its_safe_text(detail, monkeypatch, err, safe):
    said = f"could not save it: {err}"
    monkeypatch.setattr(routes, "approve_gate", raising(http_error_from(err, 500, said if detail == "text" else {"message": said})))

    answer = TemperTools().approve_gate("e-1", "gate")

    assert answer["error"] == f"could not save it: {safe}" and answer["status"] == 500
    assert MARKER not in str(answer)


# -- triggers ------------------------------------------------------------------------


def test_a_trigger_whose_start_fails_says_the_safe_text_and_stores_the_whole_error(monkeypatch, err, safe, caplog):
    settled = []
    monkeypatch.setattr(trigger_scheduler, "claim", lambda name, key: 7)
    monkeypatch.setattr(trigger_scheduler, "settle", lambda *args: settled.append(args))
    monkeypatch.setattr(trigger_scheduler, "render_inputs", lambda trigger, event: {})
    plan = SimpleNamespace(trigger=SimpleNamespace(name="nightly", workflow="w"))

    with caplog.at_level("WARNING", logger=trigger_scheduler.__name__):
        decision = trigger_scheduler.Scheduler(start_run=raising(err))._fire(plan, "k", {})

    assert decision == {"trigger": "nightly", "key": "k", "outcome": "failed", "detail": safe}
    assert caplog.messages == [f"Trigger nightly could not start w: {safe}"]
    [(fire_id, status, stored)] = settled
    assert (fire_id, status, stored) == (7, "failed", str(err))


# -- Slack and Telegram --------------------------------------------------------------


@pytest.mark.parametrize("raised", ["database error", "HTTP error from it"])
def test_a_slack_or_telegram_command_that_fails_on_the_database_replies_with_the_safe_text(raised, monkeypatch, err, safe):
    """Both bots reply with an OpsError's text."""
    detail = None if raised == "database error" else {"message": f"could not save it: {err}"}
    monkeypatch.setattr(routes, "start_run", raising(err if detail is None else http_error_from(err, 400, detail)))

    with pytest.raises(OpsError) as failed:
        TemperOps().start("w", {})

    assert str(failed.value) == (safe if detail is None else f"could not save it: {safe}")


def test_an_inbox_sweep_that_fails_on_the_database_keeps_the_safe_line(err, line):
    sweeper = Sweeper(interval_s=0)
    sweeper.sweep_once = raising(err)
    sweeper.stop()

    sweeper._loop()

    assert sweeper.last_error == line


def _notifier() -> notify_loop.Notifier:
    return notify_loop.Notifier(config=SimpleNamespace(get=lambda: None), ops=SimpleNamespace(recent=lambda: []),
                                tick_s=0)


def test_a_notify_tick_that_fails_on_the_database_keeps_the_safe_line(err, line):
    notifier = _notifier()

    def tick():
        notifier._stop.set()
        raise err

    notifier.tick = tick

    notifier._loop()

    assert notifier.last_error == line


def test_a_notify_check_that_fails_on_the_database_keeps_the_safe_text(monkeypatch, err, safe):
    notifier = _notifier()
    notifier._migrated = True
    for step in ("_team_waits", "_close_answered", "_nudges", "_ends", "_stuck", "_release"):
        setattr(notifier, step, lambda *_args: [])
    notifier._questions = raising(err)

    assert notifier.tick() == []

    assert notifier.last_error == f"questions: {safe}"


@pytest.fixture
def marked(monkeypatch):
    marks = []
    monkeypatch.setattr(notify_loop.store, "mark", lambda copy_id, status, **kw: marks.append((copy_id, status, kw)))
    return marks


COPY = SimpleNamespace(id=3, kind="end", execution_id="e-1-0000", via="slack", target="C1")


def test_a_notice_that_fails_on_the_database_answers_with_the_safe_text_and_stores_it_whole(marked, err, safe):
    notifier = _notifier()
    notifier.senders = {"slack": SimpleNamespace(send=raising(err))}

    result = notifier._send(COPY, notice=None)

    assert result["error"] == safe
    assert marked == [(3, "failed", {"detail": f"{type(err).__name__}: {err}"})]


def test_a_team_alert_that_fails_on_the_database_answers_with_the_safe_text(marked, err, safe):
    notifier = _notifier()
    notifier.senders = {"slack": SimpleNamespace(send_team_wait=raising(err))}
    alert = SimpleNamespace(execution_id="e-1-0000", reason="a question", url="https://example.invalid/team")

    result = notifier._send_team_wait(COPY, alert)

    assert result["error"] == safe


def test_the_notify_status_shows_the_safe_text_when_its_counts_fail(monkeypatch, err, safe):
    notifier = SimpleNamespace(config=SimpleNamespace(get=lambda: SimpleNamespace(path="p", places={}), error=None),
                               senders={}, last_tick_at=None, last_error=None, sent=0, held=0)
    monkeypatch.setattr(notify_service, "_notifier", notifier)
    monkeypatch.setattr(notify_service.store, "counts", raising(err))

    assert notify_service.status()["copies"] == {"error": safe}


def test_a_slack_test_entrys_fake_whose_event_cannot_be_read_shows_the_safe_line(monkeypatch, err, line):
    from temper_ai.integrations.inbox import store as inbox_store

    fake = SimpleNamespace(event_id=5, brief=lambda: {"id": "f-1"})
    monkeypatch.setattr(inbox_store, "get", raising(err))

    shown = slack_door.show("f-1", fakes=SimpleNamespace(get=lambda fake_id: fake))

    assert shown == {"id": "f-1", "event": {"error": line}}


def test_a_slack_check_that_fails_on_the_database_reports_the_safe_line(err, line):
    said: list[str] = []
    door = SimpleNamespace(info=lambda: {"on": True, "channel_id": "C1", "channel": "tests", "user": "U1", "bot_user": "B1"})
    tester = slack_e2e.Tester(door, slack=None, say=said.append)
    tester.check_ask = raising(err)

    [result] = tester.run(only=["ask"])

    assert result.detail == line
    assert MARKER not in "\n".join(said)


@pytest.mark.parametrize("handler_class", [SlackHandler, TelegramHandler], ids=["slack", "telegram"])
def test_a_bot_message_that_fails_on_the_database_keeps_the_safe_line(handler_class, err, line):
    fake = SimpleNamespace()
    handler = (SlackHandler(client=None, config=None, ops=fake, picker=fake, answerer=fake, access=fake)
               if handler_class is SlackHandler
               else TelegramHandler(client=None, config=None, ops=fake, picker=fake, answerer=fake,
                                    notify_config=fake, sender=fake))
    try:
        handler.handle = raising(err)
        with pytest.raises(type(err)):
            handler.handle_saved(SimpleNamespace(payload={}))
        assert handler.last_error == line

        handler.last_error = None
        handler._safe({})
        assert handler.last_error == line
    finally:
        handler.shutdown()


def test_a_slack_connection_that_fails_on_the_database_keeps_the_safe_line(err, line):
    socket = SocketMode(open_url=lambda: "", on_envelope=lambda _envelope: None, sleep=lambda _s: None)

    def run_once():
        socket.stop()
        raise err

    socket.run_once = run_once

    socket._loop()

    assert socket.last_error == line


def test_a_telegram_poll_that_fails_on_the_database_keeps_the_safe_line(err, line):
    poller = Poller(client=None, submit=None, sleep=lambda _s: None)

    def poll_once():
        poller.stop()
        raise err

    poller.poll_once = poll_once

    poller._loop()

    assert poller.last_error == line
