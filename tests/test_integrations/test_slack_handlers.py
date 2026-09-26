"""What temper does with a slash command, a button click, a mention or a DM."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from temper_ai.integrations.slack import store
from temper_ai.integrations.slack.blocks import APPROVE, CANCEL, CONFIRM, REJECT, STOP
from temper_ai.integrations.slack.config import ConfigWatcher
from temper_ai.integrations.slack.handlers import Handler
from temper_ai.integrations.slack.notifier import GATE
from temper_ai.integrations.slack.picker import Pick
from temper_ai.integrations.slack.socket import SocketMode
from temper_ai.triggers.scheduler import claim, settle

from .conftest import OTHER, OWNER

CHANNEL = "C0ASKED01"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


class FakePicker:
    def __init__(self, pick: Pick) -> None:
        self.result = pick
        self.asked: list[tuple[str, str]] = []

    def pick(self, request: str, conversation: str = "") -> Pick:
        self.asked.append((request, conversation))
        return self.result


@pytest.fixture
def picker() -> FakePicker:
    return FakePicker(Pick(workflow="gate_demo", inputs={"topic": "weekly"}, reason="it asks before the end",
                           execution_id="pick0001-x"))


@pytest.fixture
def handler(slack, ops, slack_config, picker) -> Handler:
    return Handler(slack, ConfigWatcher(), ops, picker=picker, bot_user="UBOT")


def slash(handler: Handler, text: str, user: str = OWNER, channel: str = CHANNEL) -> None:
    handler.handle({"type": "slash_commands", "payload": {
        "text": text, "user_id": user, "user_name": "shine", "channel_id": channel,
        "response_url": "https://hooks.slack.test/r"}})


def click(handler: Handler, action_id: str, value: dict | str, message: dict, user: str = OWNER) -> None:
    handler.handle({"type": "interactive", "payload": {
        "type": "block_actions", "user": {"id": user, "username": "shine"},
        "channel": {"id": message["channel"]}, "container": {"message_ts": message["ts"]},
        "message": {"ts": message["ts"], "text": message["text"], "blocks": message.get("blocks")},
        "response_url": "https://hooks.slack.test/click",
        "actions": [{"action_id": action_id, "value": value if isinstance(value, str) else json.dumps(value)}]}})


def said(slack) -> str:
    return json.dumps(slack.responses[-1])


def button_value(message: dict, action_id: str) -> str:
    for block in message.get("blocks") or []:
        for element in block.get("elements") or []:
            if element.get("action_id") == action_id:
                return element["value"]
    raise AssertionError(f"no {action_id} button")


class TestSlashCommands:
    def test_run_starts_it_and_posts_its_thread_here(self, handler, slack, ops):
        slash(handler, "run gate_demo topic=weekly rounds=2")
        assert ops.started == [("gate_demo", {"topic": "weekly", "rounds": 2})]
        eid = ops.recent()[0]["id"]
        header = slack.posts[0]
        assert header["channel"] == CHANNEL and header["thread_ts"] is None
        assert f"<@{OWNER}>" in str(header["blocks"]) and "topic" in str(header["blocks"])
        assert store.thread_for(eid, CHANNEL) == header["ts"]
        assert store.threads_of(eid, origin_only=True) == [(CHANNEL, header["ts"])]
        assert store.actions()[0]["action"] == "run" and store.actions()[0]["user_id"] == OWNER
        assert slack.responses == []  # the header is the answer

    def test_where_temper_cannot_post_the_thread_goes_to_the_dm(self, handler, slack, ops):
        slack.forbidden.add(CHANNEL)
        slash(handler, "run trigger_probe note=hi")
        assert slack.posts[0]["channel"] == f"D{OWNER}"
        assert "in our DM" in said(slack)

    def test_unknown_workflow_suggests_near_names(self, handler, slack, ops):
        slash(handler, "run gate note=x")
        assert ops.started == [] and "no workflow `gate`" in said(slack) and "gate_demo" in said(slack)

    def test_bad_inputs_are_explained_and_nothing_starts(self, handler, slack, ops):
        slash(handler, "run gate_demo rounds=two")
        assert ops.started == []
        text = said(slack)
        assert "Not started" in text and "`rounds` should be integer" in text and "`topic`" in text

    def test_a_failed_start_is_reported(self, handler, slack, ops):
        ops.start_error = "Failed to load workflow config"
        slash(handler, "run trigger_probe")
        assert "Failed to load workflow config" in said(slack) and slack.posts == []

    def test_list_and_search(self, handler, slack):
        slash(handler, "list")
        text = said(slack)
        assert all(n in text for n in ("trigger_probe", "gate_demo", "mystery")) and "no description" in text
        slash(handler, "search approve")
        text = said(slack)
        assert "gate_demo" in text and "trigger_probe" not in text

    def test_status_of_one_run_and_of_everything_going(self, handler, slack, ops):
        ops.add_run("3f2a9c1e-aaaa", "trigger_probe", "running", NOW)
        ops.add_run("77777777-bbbb", "trigger_probe", "completed", NOW)
        slash(handler, "status")
        assert "3f2a9c1e" in said(slack) and "77777777" not in said(slack)
        slash(handler, "status 7777")
        assert "completed" in said(slack)
        slash(handler, "status abcdef12")
        assert "No recent run" in said(slack)

    def test_stop_cancels_and_notes_it_in_the_thread(self, handler, slack, ops):
        slash(handler, "run trigger_probe")
        eid = ops.recent()[0]["id"]
        slash(handler, f"stop {eid[:8]}")
        assert ops.cancelled == [(eid, "Stopped in Slack by shine")]
        assert slack.posts[-1]["thread_ts"] == slack.posts[0]["ts"] and "Stop requested" in slack.posts[-1]["text"]
        slash(handler, f"stop {eid[:8]}")
        assert "already cancelled" in said(slack) and len(ops.cancelled) == 1

    def test_help_and_typos(self, handler, slack):
        slash(handler, "")
        assert "/temper search" in said(slack)
        slash(handler, "trigger_probe note=hi")
        assert "don't know" in said(slack) and "/temper run trigger_probe" in said(slack)


def gate_message(slack, ops, eid: str = "run-1", event: str = "ev-1") -> dict:
    """A gate notice as the notifier posts it (claimed under slack:gate)."""
    from temper_ai.integrations.slack import blocks

    ops.add_run(eid, "gate_demo", "running", NOW)
    ops.alive.add(eid)
    ops.add_gate(event, eid, "approve_step", NOW)
    msg = blocks.gate({"id": eid, "workflow": "gate_demo"}, {"node_name": "approve_step", "event_id": event})
    answer = slack.post(f"D{OWNER}", msg["text"], msg["blocks"])
    fire = claim(GATE, event, outcome="posting")
    settle(fire, "posted", f"D{OWNER}:{answer['ts']}", execution_id=eid)
    return slack.posts[-1]


class TestGateButtons:
    def test_approve_resumes_the_run_and_closes_the_message(self, handler, slack, ops):
        msg = gate_message(slack, ops)
        click(handler, APPROVE, button_value(msg, APPROVE), msg)
        assert ops.approved == [("run-1", "approve_step")] and ops.resumed == []
        update = slack.updates[-1]
        assert update["ts"] == msg["ts"] and f"Approved by <@{OWNER}>" in str(update["blocks"])
        assert not any(b.get("type") == "actions" for b in update["blocks"])
        assert store.actions()[0]["action"] == "approve"

    def test_a_double_click_does_nothing_twice(self, handler, slack, ops):
        msg = gate_message(slack, ops)
        click(handler, APPROVE, button_value(msg, APPROVE), msg)
        click(handler, APPROVE, button_value(msg, APPROVE), msg)
        assert len(ops.approved) == 1 and len(store.actions()) == 1

    def test_a_click_after_someone_else_answered_says_so(self, handler, slack, ops):
        msg = gate_message(slack, ops)
        ops.approve("run-1", "approve_step")  # answered in the dashboard first
        click(handler, REJECT, button_value(msg, REJECT), msg, user=OTHER)
        assert ops.cancelled == [] and "Already approved" in str(slack.updates[-1]["blocks"])

    def test_reject_stops_the_run(self, handler, slack, ops):
        msg = gate_message(slack, ops)
        click(handler, REJECT, button_value(msg, REJECT), msg)
        assert ops.cancelled == [("run-1", "Rejected in Slack by shine")]
        assert "Rejected by" in str(slack.updates[-1]["blocks"])

    def test_approve_after_a_restart_resumes_the_run(self, handler, slack, ops):
        msg = gate_message(slack, ops)
        ops.alive.discard("run-1")  # temper restarted; nothing waits on the gate in memory
        click(handler, APPROVE, button_value(msg, APPROVE), msg)
        assert ops.resumed == ["run-1"] and "resumed" in str(slack.updates[-1]["blocks"])

    def test_stop_button_on_a_stuck_notice(self, handler, slack, ops):
        ops.add_run("run-q", "trigger_probe", "running", NOW)
        msg = slack.post(f"D{OWNER}", "quiet", [])
        msg = slack.posts[-1]
        click(handler, STOP, {"run": "run-q"}, msg)
        assert ops.cancelled[0][0] == "run-q" and "Stopping" in str(slack.updates[-1]["blocks"])


def mention(handler: Handler, text: str, channel: str = CHANNEL, ts: str = "1790000100.000001",
            thread_ts: str | None = None, kind: str = "app_mention", event_id: str = "Ev1", **extra) -> None:
    event = {"type": kind, "user": OWNER, "text": text, "channel": channel, "ts": ts, **extra}
    if thread_ts:
        event["thread_ts"] = thread_ts
    handler.handle({"type": "events_api", "payload": {"event_id": event_id, "event": event}})


class TestMentions:
    def test_proposes_then_starts_only_on_confirm(self, handler, slack, ops, picker):
        mention(handler, "<@UBOT> run the approval demo about weekly")
        assert picker.asked == [("run the approval demo about weekly", "")]
        assert ops.started == []
        placeholder = slack.posts[0]
        assert placeholder["thread_ts"] == "1790000100.000001"
        proposal = slack.updates[-1]
        assert proposal["ts"] == placeholder["ts"] and "Start gate_demo?" == proposal["text"]
        msg = {**placeholder, **proposal}
        click(handler, CONFIRM, button_value(msg, CONFIRM), msg)
        assert ops.started == [("gate_demo", {"topic": "weekly"})]
        eid = ops.recent()[0]["id"]
        assert store.thread_for(eid, CHANNEL) == placeholder["ts"]  # the proposal became the run's header
        assert "started by" in str(slack.updates[-1]["blocks"])
        # A message event carries only the user's id; the log names the person.
        picks = [a for a in store.actions() if a["action"] == "pick"]
        assert picks and picks[0]["user_name"] == "shine"

    def test_cancel_starts_nothing(self, handler, slack, ops):
        mention(handler, "<@UBOT> run the approval demo")
        msg = {**slack.posts[0], **slack.updates[-1]}
        click(handler, CANCEL, button_value(msg, CANCEL), msg)
        assert ops.started == [] and "nothing was started" in str(slack.updates[-1]["blocks"])

    def test_no_fitting_workflow_asks_for_more(self, handler, slack, ops, picker):
        picker.result = Pick(workflow=None, question="Which repo should I look at?")
        mention(handler, "<@UBOT> fix it")
        assert "Which repo" in slack.updates[-1]["text"] and ops.started == []

    def test_missing_inputs_are_asked_about_not_guessed(self, handler, slack, picker):
        picker.result = Pick(workflow="gate_demo", question="What topic?", problems=["missing required input(s): `topic`"])
        mention(handler, "<@UBOT> run the gate demo")
        assert "I'd use *gate_demo*, but: What topic?" in slack.updates[-1]["text"]

    def test_a_reply_in_the_thread_carries_the_conversation(self, handler, slack, picker):
        slack.threads[(CHANNEL, "1790000100.000001")] = [
            {"ts": "1790000100.000001", "user": OWNER, "text": "<@UBOT> fix it"},
            {"ts": "1790000100.000002", "bot_id": "B1", "user": "UBOT", "text": "Which repo?"}]
        mention(handler, "<@UBOT> temper-ai", ts="1790000100.000003", thread_ts="1790000100.000001",
                event_id="Ev2")
        request, conversation = picker.asked[0]
        assert request == "temper-ai" and "fix it" in conversation and "Which repo?" in conversation

    def test_dms_work_and_retries_and_bots_are_ignored(self, handler, slack, picker):
        mention(handler, "grade the plan", channel="D0DM00001", kind="message", channel_type="im")
        mention(handler, "grade the plan", channel="D0DM00001", kind="message", channel_type="im")  # retry
        mention(handler, "hello", channel="D0DM00001", kind="message", channel_type="im", ts="2.0",
                event_id="Ev3", bot_id="B1")
        mention(handler, "in a channel", kind="message", channel_type="channel", ts="3.0", event_id="Ev4")
        assert len(picker.asked) == 1

    def test_a_bare_mention_gets_help(self, handler, slack, picker):
        mention(handler, "<@UBOT>")
        assert picker.asked == [] and "/temper" in str(slack.posts[0]["blocks"])


class FakeSocket:
    def __init__(self, messages: list) -> None:
        self.messages = list(messages)
        self.sent: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def recv(self, timeout: float | None = None):
        item = self.messages.pop(0)
        if isinstance(item, BaseException):
            raise item
        return json.dumps(item)

    def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


class TestSocket:
    def test_acks_each_envelope_before_handling_and_reconnects_on_request(self):
        got: list[dict] = []
        ws = FakeSocket([{"type": "hello", "debug_info": {"host": "h"}}, TimeoutError(),
                         {"type": "slash_commands", "envelope_id": "E1", "payload": {"text": "list"}},
                         {"type": "disconnect", "reason": "refresh_requested"}])

        def on_envelope(envelope: dict) -> None:
            assert ws.sent == [{"envelope_id": "E1"}]  # acked first
            got.append(envelope)

        sock = SocketMode(lambda: "wss://x", on_envelope, connect=lambda url: ws)
        assert sock.run_once() is True
        assert [e["envelope_id"] for e in got] == ["E1"] and sock.connects == 1 and sock.envelopes == 1

    def test_a_handler_error_does_not_drop_the_connection(self):
        ws = FakeSocket([{"type": "hello"}, {"type": "events_api", "envelope_id": "E1", "payload": {}},
                         {"type": "events_api", "envelope_id": "E2", "payload": {}}, {"type": "disconnect"}])

        def boom(envelope: dict) -> None:
            raise RuntimeError("bad handler")

        sock = SocketMode(lambda: "wss://x", boom, connect=lambda url: ws)
        assert sock.run_once() is True and [m["envelope_id"] for m in ws.sent] == ["E1", "E2"]


class TestService:
    def test_off_in_tests_and_without_tokens(self, monkeypatch):
        from temper_ai.integrations.slack import service

        assert service.why_off() == "TEMPER_SLACK is off" and service.start_slack() is None
        monkeypatch.setenv("TEMPER_SLACK", "1")
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
        assert "SLACK_BOT_TOKEN and SLACK_APP_TOKEN not set" == service.why_off()
        assert service.start_slack() is None and service.status()["running"] is False

    def test_a_broken_start_never_stops_the_server(self, monkeypatch):
        from temper_ai.integrations.slack import service

        monkeypatch.setenv("TEMPER_SLACK", "1")
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")

        def broken(*a, **k):
            raise RuntimeError("no network")

        monkeypatch.setattr(service, "SlackService", broken)
        assert service.start_slack() is None
