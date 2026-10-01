"""What temper does with a slash command, a button click, a mention or a DM."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from temper_ai.integrations.notify import store as notify_store
from temper_ai.integrations.slack import store
from temper_ai.integrations.slack.access import parse_config as parse_access
from temper_ai.integrations.slack.answer import ANSWER_WORKFLOW, Answerer
from temper_ai.integrations.slack.blocks import ANSWER as ANSWER_BUTTON
from temper_ai.integrations.slack.blocks import APPROVE, CANCEL, CONFIRM, REJECT, STOP
from temper_ai.integrations.slack.config import ConfigWatcher
from temper_ai.integrations.slack.handlers import Handler
from temper_ai.integrations.slack.picker import Pick
from temper_ai.integrations.slack.socket import SocketMode

from .conftest import OTHER, OWNER, FakeAccess
from .test_slack_answer import finish

CHANNEL = "C0ASKED01"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


class FakePicker:
    def __init__(self, pick: Pick) -> None:
        self.result = pick
        self.asked: list[tuple[str, str]] = []
        self.allowed: Any = "not asked"

    def pick(self, request: str, conversation: str = "", allowed=None) -> Pick:
        self.asked.append((request, conversation))
        self.allowed = allowed
        return self.result


@pytest.fixture
def picker() -> FakePicker:
    return FakePicker(Pick(workflow="gate_demo", inputs={"topic": "weekly"}, reason="it asks before the end",
                           execution_id="pick0001-x"))


@pytest.fixture
def handler(slack, ops, slack_config, picker) -> Handler:
    return Handler(slack, ConfigWatcher(), ops, picker=picker, bot_user="UBOT",
                   answerer=Answerer(ops, timeout_s=0, sleep=lambda _s: None), access=FakeAccess())


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


def gate_message(slack, ops, eid: str = "run-1", event: str = "ev-1", questions: list | None = None) -> dict:
    """A question as the notify loop posts it (one copy, sent)."""
    from temper_ai.integrations.slack import blocks

    ops.add_run(eid, "gate_demo", "running", NOW)
    ops.alive.add(eid)
    ops.add_gate(event, eid, "approve_step", NOW, questions=questions)
    msg = blocks.gate({"id": eid, "workflow": "gate_demo"},
                      {"node_name": "approve_step", "event_id": event, "questions": questions or []})
    answer = slack.post(f"D{OWNER}", msg["text"], msg["blocks"])
    copy = notify_store.claim(f"q:{event}", "question", eid, "slack", f"D{OWNER}", node="approve_step",
                              event_id=event)
    assert copy is not None
    notify_store.mark(copy.id, "sent", ref=f"D{OWNER}:{answer['ts']}")
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

    def test_answer_opens_a_form_and_its_answers_reach_the_gate(self, handler, slack, ops):
        questions = [
            {"id": "size", "question": "How big?", "options": [{"label": "Small"}, {"label": "Large"}]},
            {"id": "parts", "question": "Which parts?", "multiSelect": True,
             "options": [{"label": "API"}, {"label": "UI"}, {"label": "Docs"}]},
            {"id": "name", "question": "What should it be called?"},
        ]
        msg = gate_message(slack, ops, questions=questions)
        value = button_value(msg, ANSWER_BUTTON)
        handler.handle({"type": "interactive", "payload": {
            "type": "block_actions", "trigger_id": "trig-1", "user": {"id": OWNER, "username": "shine"},
            "channel": {"id": msg["channel"]}, "container": {"message_ts": msg["ts"]},
            "message": {"ts": msg["ts"], "text": msg["text"], "blocks": msg.get("blocks")},
            "actions": [{"action_id": ANSWER_BUTTON, "value": value}]}})
        assert ops.answers == [] and len(slack.views) == 1
        view = slack.views[0]["view"]
        assert slack.views[0]["trigger_id"] == "trig-1"
        ids = [b.get("block_id") for b in view["blocks"] if b.get("type") == "input"]
        assert {"q0", "q1", "q2c", "response"} <= set(ids)

        # Sent: the choice, two of the three parts, a typed name and a note.
        handler.handle({"type": "interactive", "payload": {
            "type": "view_submission", "user": {"id": OWNER, "username": "shine"},
            "view": {"id": "V1", "hash": "h1", "callback_id": view["callback_id"],
                     "private_metadata": view["private_metadata"],
                     "state": {"values": {
                         "q0": {"v": {"selected_option": {"value": "1"}}},
                         "q1": {"v": {"selected_options": [{"value": "0"}, {"value": "2"}]}},
                         "q2c": {"v": {"value": "Blue Heron"}},
                         "response": {"v": {"value": "looks right"}}}}}}})
        assert ops.approved == [("run-1", "approve_step")]
        got = ops.answers[0]
        assert {a["id"]: (a["selected"], a["custom"]) for a in got["answers"]} == {
            "size": (["Large"], ""), "parts": (["API", "Docs"], ""), "name": ([], "Blue Heron")}
        assert got["response"] == "looks right" and got["by"] == "shine (Slack)"
        # The question message loses its buttons and says who answered.
        update = slack.updates[-1]
        assert update["ts"] == msg["ts"] and "Approved by" in str(update["blocks"])
        assert not any(b.get("type") == "actions" for b in update["blocks"])

    def test_a_form_sent_twice_answers_once(self, handler, slack, ops):
        questions = [{"id": "name", "question": "Name?"}]
        msg = gate_message(slack, ops, questions=questions)
        from temper_ai.integrations.slack import blocks as slack_blocks

        view = slack_blocks.answer_form({"id": "run-1", "workflow": "gate_demo"},
                                        {"node_name": "approve_step", "event_id": "ev-1", "questions": questions},
                                        msg["channel"], msg["ts"])
        payload = {"type": "view_submission", "user": {"id": OWNER, "username": "shine"},
                   "view": {"id": "V2", "hash": "h2", "callback_id": view["callback_id"],
                            "private_metadata": view["private_metadata"],
                            "state": {"values": {"q0c": {"v": {"value": "Kestrel"}}}}}}
        handler.handle({"type": "interactive", "payload": payload})
        handler.handle({"type": "interactive", "payload": payload})
        assert len(ops.answers) == 1 and ops.answers[0]["answers"][0]["custom"] == "Kestrel"

    def test_a_form_for_a_gate_answered_elsewhere_changes_nothing(self, handler, slack, ops):
        questions = [{"id": "name", "question": "Name?"}]
        msg = gate_message(slack, ops, questions=questions)
        ops.approve("run-1", "approve_step", by="ana (dashboard)")   # answered in the dashboard first
        click(handler, ANSWER_BUTTON, button_value(msg, ANSWER_BUTTON), msg)
        assert slack.views == [] and len(ops.answers) == 1
        assert "Already approved" in str(slack.updates[-1]["blocks"])

    def test_stop_button_on_a_stuck_notice(self, handler, slack, ops):
        ops.add_run("run-q", "trigger_probe", "running", NOW)
        msg = slack.post(f"D{OWNER}", "quiet", [])
        msg = slack.posts[-1]
        click(handler, STOP, {"run": "run-q"}, msg)
        assert ops.cancelled[0][0] == "run-q" and "Stopping" in str(slack.updates[-1]["blocks"])


def mention(handler: Handler, text: str, channel: str = CHANNEL, ts: str = "1790000100.000001",
            thread_ts: str | None = None, kind: str = "app_mention", event_id: str = "Ev1",
            user: str = OWNER, **extra) -> None:
    event = {"type": kind, "user": user, "text": text, "channel": channel, "ts": ts, **extra}
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


ANSWER = "Looking.\n<answer>*Yes.* `backend/trips/routes.py` serves `/ics`.</answer>"


class TestQuestions:
    def test_ask_answers_in_the_channel_for_everyone(self, handler, slack, ops):
        finish(ops, ANSWER)
        slash(handler, "ask can roamee's app export a trip?")
        assert ops.started == [(ANSWER_WORKFLOW, {"question": "can roamee's app export a trip?", "conversation": ""})]
        first, last = slack.responses[0], slack.responses[-1]
        assert first["response_type"] == "ephemeral" and "Reading the code" in first["text"]
        assert last["response_type"] == "in_channel"
        shown = json.dumps(last["blocks"])
        assert "backend/trips/routes.py" in shown and f"<@{OWNER}> asked" in shown and "Looking." not in shown
        assert [a["action"] for a in store.actions()].count("ask") == 1

    def test_run_repo_answer_is_the_same_as_ask(self, handler, slack, ops):
        ops.entries.append({"name": ANSWER_WORKFLOW, "description": "Answer a question about the repos.",
                            "inputs": {"question": {"type": "string", "required": True},
                                       "conversation": {"type": "string", "required": False}}})
        finish(ops, ANSWER)
        slash(handler, 'run repo_answer question="does rollcall trade crypto?"')
        assert ops.started[0][1]["question"] == "does rollcall trade crypto?"
        assert slack.responses[-1]["response_type"] == "in_channel" and slack.posts == []  # no run thread

    def test_a_failed_answer_is_told_only_to_the_asker(self, handler, slack, ops):
        finish(ops, status="failed", why="failed at answer: out of credit")
        slash(handler, "ask where are alerts sent?")
        last = slack.responses[-1]
        assert last["response_type"] == "ephemeral" and "out of credit" in last["text"]

    def test_ask_without_a_question_starts_nothing(self, handler, slack, ops):
        slash(handler, "ask")
        assert ops.started == [] and "Ask what?" in said(slack)

    def test_a_question_in_plain_words_is_answered_in_place(self, handler, slack, ops, picker):
        picker.result = Pick(workflow=ANSWER_WORKFLOW, inputs={"question": "Can roamee export a trip?"})
        finish(ops, ANSWER)
        mention(handler, "<@UBOT> can it export a trip?")
        assert ops.started == [(ANSWER_WORKFLOW, {"question": "Can roamee export a trip?", "conversation": ""})]
        placeholder, answer = slack.posts[0], slack.updates[-1]
        assert answer["ts"] == placeholder["ts"] and slack.buttons(answer) == []
        assert "backend/trips/routes.py" in json.dumps(answer["blocks"])

    def test_a_question_in_a_thread_carries_the_conversation(self, handler, slack, ops, picker):
        picker.result = Pick(workflow=ANSWER_WORKFLOW, inputs={})  # no rewrite: the words as sent
        finish(ops, ANSWER)
        slack.threads[(CHANNEL, "1790000100.000001")] = [
            {"ts": "1790000100.000001", "user": OWNER, "text": "<@UBOT> tell me about roamee trips"}]
        mention(handler, "<@UBOT> can they be exported?", ts="1790000100.000003", thread_ts="1790000100.000001",
                event_id="Ev5")
        question, conversation = ops.started[0][1]["question"], ops.started[0][1]["conversation"]
        assert question == "can they be exported?" and "roamee trips" in conversation

    def test_a_failed_answer_in_a_thread_says_so_there(self, handler, slack, ops, picker):
        picker.result = Pick(workflow=ANSWER_WORKFLOW, inputs={"question": "q?"})
        finish(ops, status="failed", why="boom")
        mention(handler, "<@UBOT> q?")
        assert "boom" in slack.updates[-1]["text"]


# -- who may do what, at every way in ------------------------------------------------

STRANGER = "U0NOONE03"
#: OTHER is in a role with one patch: a workflow of its own, pinned inputs,
#: and only their own runs. STRANGER is in no role at all.
RULES = parse_access({"access": {
    "owner": OWNER,
    "default": "readonly",
    "repositories": ["rollcall", "roamee", "temper-ai"],
    "people": {OTHER: {"role": "patch", "name": "lomit"}},
    "roles": {
        "readonly": {"commands": ["help", "list", "search", "ask"], "workflows": ["repo_answer"],
                     "runs": "none", "gates": "none"},
        "patch": {"commands": ["help", "list", "search", "status", "ask", "run", "pick", "stop", "gate"],
                  "workflows": ["repo_answer", "gate_demo", "trigger_probe"],
                  "force": {"gate_demo": {"topic": "roamee"}},
                  "repos": ["roamee"], "auto": ["trigger_probe"], "runs": "own", "gates": "own"},
    },
}})


@pytest.fixture
def fenced(slack, ops, slack_config, picker) -> Handler:
    """A handler with real access rules in force."""
    return Handler(slack, ConfigWatcher(), ops, picker=picker, bot_user="UBOT",
                   answerer=Answerer(ops, timeout_s=0, sleep=lambda _s: None),
                   access=FakeAccess(RULES))


def refused(slack) -> bool:
    return ":lock: Sorry" in said(slack)


class TestSlashCommandsAreFenced:
    def test_a_stranger_cannot_run_anything(self, fenced, slack, ops):
        slash(fenced, "run gate_demo topic=weekly", user=STRANGER)
        assert ops.started == [] and refused(slack)
        assert slack.posts == [], "nothing is posted and nobody is told"

    def test_a_role_cannot_run_a_workflow_it_does_not_have(self, fenced, slack, ops):
        slash(fenced, "run mystery", user=OTHER)
        assert ops.started == [] and refused(slack)

    def test_the_forced_inputs_win_over_what_was_typed(self, fenced, slack, ops):
        slash(fenced, "run gate_demo topic=rollcall rounds=2", user=OTHER)
        assert ops.started == [("gate_demo", {"rounds": 2, "topic": "roamee"})]

    def test_a_forced_input_counts_as_given(self, fenced, slack, ops):
        # topic is required and was not typed; the role supplies it.
        slash(fenced, "run gate_demo", user=OTHER)
        assert ops.started == [("gate_demo", {"topic": "roamee"})]

    def test_the_owner_keeps_everything(self, fenced, slack, ops):
        slash(fenced, "run mystery")
        assert ops.started == [("mystery", {})]

    def test_a_stranger_cannot_stop_a_run(self, fenced, slack, ops):
        slash(fenced, "run gate_demo topic=weekly")          # the owner's run
        eid = ops.recent()[0]["id"]
        slash(fenced, f"stop {eid[:8]}", user=STRANGER)
        assert ops.cancelled == [] and refused(slack)

    def test_a_role_cannot_stop_someone_elses_run(self, fenced, slack, ops):
        slash(fenced, "run gate_demo topic=weekly")          # the owner's run
        eid = ops.recent()[0]["id"]
        slash(fenced, f"stop {eid[:8]}", user=OTHER)
        assert ops.cancelled == [] and "isn't yours" in said(slack)

    def test_but_can_stop_its_own(self, fenced, slack, ops):
        slash(fenced, "run gate_demo topic=weekly", user=OTHER)
        eid = ops.recent()[0]["id"]
        slash(fenced, f"stop {eid[:8]}", user=OTHER)
        assert [c[0] for c in ops.cancelled] == [eid]

    def test_status_shows_only_its_own_runs(self, fenced, slack, ops):
        slash(fenced, "run gate_demo topic=weekly")          # the owner's
        slash(fenced, "run gate_demo topic=weekly", user=OTHER)
        mine = ops.recent()[1]["id"] if ops.recent()[0]["id"] != ops.started else ops.recent()[-1]["id"]
        slack.responses.clear()
        slash(fenced, "status", user=OTHER)
        shown = said(slack)
        assert mine[:8] in shown
        assert sum(r["id"][:8] in shown for r in ops.recent()) == 1, "only one run is theirs"

    def test_the_owner_sees_every_run(self, fenced, slack, ops):
        slash(fenced, "run gate_demo topic=weekly")
        slash(fenced, "run gate_demo topic=weekly", user=OTHER)
        slack.responses.clear()
        slash(fenced, "status")
        assert sum(r["id"][:8] in said(slack) for r in ops.recent()) == 2

    def test_a_stranger_may_still_ask_and_list(self, fenced, slack, ops):
        slash(fenced, "list", user=STRANGER)
        assert not refused(slack)
        slash(fenced, "search gate", user=STRANGER)
        assert not refused(slack)

    def test_help_is_everyones(self, fenced, slack):
        slash(fenced, "", user=STRANGER)
        assert "/temper search" in said(slack)

    def test_a_refusal_leaves_a_trace_but_sends_nothing(self, fenced, slack, ops):
        slash(fenced, "run gate_demo topic=weekly", user=STRANGER)
        logged = [a for a in store.actions() if a["action"] == "refused"]
        assert len(logged) == 1 and logged[0]["user_id"] == STRANGER and "run" in logged[0]["detail"]
        assert slack.posts == [], "a refusal is answered to them alone; nothing is posted"


class TestGateButtonsAreFenced:
    def test_a_stranger_pressing_approve_does_nothing(self, fenced, slack, ops):
        msg = gate_message(slack, ops)
        click(fenced, APPROVE, button_value(msg, APPROVE), msg, user=STRANGER)
        assert ops.approved == [] and slack.updates == [], "the message is left as it was"
        assert ":lock: Sorry" in json.dumps(slack.responses[-1])

    def test_a_role_cannot_answer_someone_elses_gate(self, fenced, slack, ops):
        slash(fenced, "run gate_demo topic=weekly")          # the owner's run
        eid = ops.recent()[0]["id"]
        msg = gate_message(slack, ops, eid=eid, event="ev-own")
        click(fenced, REJECT, button_value(msg, REJECT), msg, user=OTHER)
        assert ops.cancelled == [] and ":lock: Sorry" in json.dumps(slack.responses[-1])

    def test_but_can_answer_the_gate_of_its_own_run(self, fenced, slack, ops):
        slash(fenced, "run gate_demo topic=weekly", user=OTHER)
        eid = ops.recent()[0]["id"]
        msg = gate_message(slack, ops, eid=eid, event="ev-mine")
        click(fenced, APPROVE, button_value(msg, APPROVE), msg, user=OTHER)
        assert ops.approved == [(eid, "approve_step")]

    def test_the_owner_answers_anyones(self, fenced, slack, ops):
        slash(fenced, "run gate_demo topic=weekly", user=OTHER)
        eid = ops.recent()[0]["id"]
        msg = gate_message(slack, ops, eid=eid, event="ev-theirs")
        click(fenced, APPROVE, button_value(msg, APPROVE), msg)
        assert ops.approved == [(eid, "approve_step")]


class TestTheStartItButtonIsFenced:
    def proposal(self, handler, slack, user=OTHER) -> dict:
        mention(handler, "<@UBOT> do the approval demo", user=user)
        placeholder = slack.posts[-1]
        return {**placeholder, **slack.updates[-1]}

    def test_a_stranger_cannot_start_a_proposal(self, fenced, slack, ops):
        msg = self.proposal(fenced, slack)
        click(fenced, CONFIRM, button_value(msg, CONFIRM), msg, user=STRANGER)
        assert ops.started == [] and ":lock: Sorry" in json.dumps(slack.responses[-1])

    def test_a_proposal_built_for_someone_else_is_not_theirs_to_start(self, fenced, slack, ops):
        msg = self.proposal(fenced, slack, user=OWNER)
        click(fenced, CONFIRM, button_value(msg, CONFIRM), msg, user=OTHER)
        assert ops.started == [] and "isn't yours" in json.dumps(slack.responses[-1])

    def test_its_own_proposal_starts_with_the_forced_inputs_on(self, fenced, slack, ops):
        msg = self.proposal(fenced, slack)
        click(fenced, CONFIRM, button_value(msg, CONFIRM), msg, user=OTHER)
        assert ops.started == [("gate_demo", {"topic": "roamee"})]

    def test_cancel_is_fenced_too(self, fenced, slack, ops):
        msg = self.proposal(fenced, slack)
        before = len(slack.updates)
        click(fenced, CANCEL, button_value(msg, CANCEL), msg, user=STRANGER)
        assert len(slack.updates) == before, "the proposal is left as it was"


class TestPlainWordsAreFenced:
    def test_a_stranger_who_wants_a_run_gets_one_line_and_nothing_else(self, fenced, slack, ops, picker):
        mention(fenced, "<@UBOT> do the approval demo", user=STRANGER)
        # readonly may ask, so the interpreter runs with only the question
        # workflow in front of it; it cannot propose anything else.
        assert picker.allowed == (ANSWER_WORKFLOW,)
        assert ops.started == []
        assert ":lock: Sorry" in str(slack.updates[-1]["blocks"])

    def test_someone_with_no_role_at_all_is_not_worth_a_pick_run(self, slack, ops, slack_config, picker):
        shut = parse_access({"access": {"owner": OWNER, "roles": {"r": {"commands": ["help"]}}, "default": "r"}})
        handler = Handler(slack, ConfigWatcher(), ops, picker=picker, bot_user="UBOT",
                         answerer=Answerer(ops, timeout_s=0, sleep=lambda _s: None), access=FakeAccess(shut))
        mention(handler, "<@UBOT> do the approval demo", user=STRANGER)
        assert picker.asked == [], "no run is started to tell someone no"
        assert ":lock: Sorry" in str(slack.posts[-1]["blocks"])

    def test_the_interpreter_sees_only_the_roles_workflows(self, fenced, slack, ops, picker):
        mention(fenced, "<@UBOT> do the approval demo", user=OTHER)
        assert picker.allowed == ("repo_answer", "gate_demo", "trigger_probe")

    def test_the_owners_interpreter_sees_every_workflow(self, fenced, slack, ops, picker):
        mention(fenced, "<@UBOT> do the approval demo")
        assert picker.allowed is None

    def test_the_forced_inputs_are_on_the_proposal(self, fenced, slack, ops, picker):
        # Whatever the interpreter filled in — here somebody else's repository
        # — the role's own value goes on afterwards. (Asking for it in so many
        # words never gets this far: see TestAskingIsFenced.)
        picker.result = Pick(workflow="gate_demo", inputs={"topic": "rollcall", "rounds": 2},
                             reason="it asks first", execution_id="pick0001-x")
        mention(fenced, "<@UBOT> do the approval demo", user=OTHER)
        value = json.loads(button_value({**slack.posts[-1], **slack.updates[-1]}, CONFIRM))
        assert value["inputs"] == {"topic": "roamee", "rounds": 2}

    def test_a_picked_workflow_the_role_may_not_use_is_refused(self, fenced, slack, ops, picker):
        picker.result = Pick(workflow="mystery", inputs={}, reason="", execution_id="pick0002-x")
        mention(fenced, "<@UBOT> do the mystery one", user=OTHER)
        assert ops.started == [] and ":lock: Sorry" in str(slack.updates[-1]["blocks"])

    def test_a_safe_workflow_starts_at_once_and_says_so(self, fenced, slack, ops, picker):
        picker.result = Pick(workflow="trigger_probe", inputs={"note": "hi"}, reason="it only echoes",
                             execution_id="pick0003-x")
        mention(fenced, "<@UBOT> echo hi", user=OTHER)
        assert ops.started == [("trigger_probe", {"note": "hi"})]
        shown = str(slack.updates[-1]["blocks"])
        assert "trigger_probe" in shown and "note" in shown
        assert CONFIRM not in shown, "nothing left to press"
        eid = ops.recent()[0]["id"]
        assert store.actions()[0]["action"] == "auto" and store.started_by(eid) == OTHER

    def test_an_unsafe_one_still_waits_for_a_click(self, fenced, slack, ops, picker):
        mention(fenced, "<@UBOT> do the approval demo", user=OTHER)
        assert ops.started == [] and CONFIRM in str(slack.updates[-1]["blocks"])


class TestAskingIsFenced:
    def test_a_role_only_asks_about_its_own_repos(self, fenced, slack, ops):
        slash(fenced, "ask what does roamee do", user=OTHER)
        assert ops.started[0][0] == ANSWER_WORKFLOW
        assert ops.started[0][1]["repos"] == "roamee"

    def test_the_owner_asks_about_all_of_them(self, fenced, slack, ops):
        slash(fenced, "ask what does rollcall do")
        assert "repos" not in ops.started[0][1]

    def test_a_question_about_another_repository_gets_one_line_and_no_run(self, fenced, slack, ops):
        slash(fenced, "ask how does rollcall roll a call", user=OTHER)
        assert ops.started == [], "nothing is started to say no"
        assert refused(slack) and slack.posts == [], "one line in the thread, nobody told"

    def test_plain_words_about_another_repository_never_reach_the_interpreter(
            self, fenced, slack, ops, picker):
        mention(fenced, "<@UBOT> have a look at rollcall's option chain", user=OTHER)
        assert picker.asked == [], "not even the run that reads the request"
        assert ops.started == [] and ":lock: Sorry" in str(slack.posts[-1]["blocks"])

    def test_its_own_repository_still_goes_through(self, fenced, slack, ops, picker):
        mention(fenced, "<@UBOT> what does roamee do about hotels?", user=OTHER)
        assert picker.asked, "a request about their own repository is read as usual"

    def test_the_owner_may_ask_about_any_of_them(self, fenced, slack, ops, picker):
        mention(fenced, "<@UBOT> have a look at rollcall's option chain")
        assert picker.asked and ":lock: Sorry" not in str(slack.posts[-1]["blocks"])

    def test_an_unlisted_person_may_still_ask_about_any_of_them(self, fenced, slack, ops):
        slash(fenced, "ask what does rollcall do", user=STRANGER)
        assert ops.started and ops.started[0][0] == ANSWER_WORKFLOW


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

    def test_each_envelope_is_saved_before_its_ack(self):
        ws = FakeSocket([{"type": "hello"},
                         {"type": "slash_commands", "envelope_id": "E1", "payload": {"text": "list"}},
                         {"type": "slash_commands", "envelope_id": "E2", "payload": {"text": "list"}},
                         {"type": "slash_commands", "envelope_id": "E3", "payload": {"text": "list"}},
                         {"type": "disconnect"}])
        acked_when_saved: list[int] = []

        def accept(envelope: dict):
            acked_when_saved.append(len(ws.sent))
            if envelope["envelope_id"] == "E2":
                return None  # had it already: acked, not handled again
            if envelope["envelope_id"] == "E3":
                raise RuntimeError("database gone")  # handled unsaved rather than lost
            return 7

        got: list = []
        sock = SocketMode(lambda: "wss://x", got.append, connect=lambda url: ws, accept=accept)
        assert sock.run_once() is True
        assert acked_when_saved == [0, 1, 2]
        assert [m["envelope_id"] for m in ws.sent] == ["E1", "E2", "E3"]
        assert got[0] == 7 and got[1]["envelope_id"] == "E3" and len(got) == 2


class TestInbox:
    """Envelopes kept in the event inbox and handled from there."""

    @pytest.fixture
    def saved(self, handler):
        from temper_ai.integrations.inbox import service as inbox
        from temper_ai.integrations.slack.handlers import EXPIRES_S

        inbox.register("slack", handler.handle_saved, expires_after_s=EXPIRES_S)
        yield inbox
        inbox.unregister("slack")

    def test_kept_without_the_token_and_a_message_is_one_event(self):
        from temper_ai.integrations.inbox import store as inbox_store
        from temper_ai.integrations.slack.service import SlackService

        slash_env = {"type": "slash_commands", "envelope_id": "E1",
                     "payload": {"command": "/temper", "text": "ask why", "token": "legacy-secret",
                                 "channel_id": CHANNEL}}
        event_id = SlackService.save(slash_env)
        row = inbox_store.get(event_id)
        assert (row.delivery, row.kind, row.subject) == ("env:E1", "/temper ask", CHANNEL)
        assert "token" not in row.payload["payload"] and "legacy-secret" not in json.dumps(row.payload)
        assert SlackService.save(slash_env) is None  # Slack sent it again

        event = {"type": "app_mention", "channel": "D1", "ts": "1790000100.000001", "text": "hi"}
        first = SlackService.save({"type": "events_api", "envelope_id": "E2",
                                   "payload": {"event_id": "Ev1", "event": event}})
        again = SlackService.save({"type": "events_api", "envelope_id": "E3",  # the same message as a DM
                                   "payload": {"event_id": "Ev2", "event": {**event, "type": "message"}}})
        assert first and again is None

    def test_handled_from_the_inbox(self, saved, handler, slack):
        from temper_ai.integrations.slack.service import SlackService

        event_id = SlackService.save({"type": "slash_commands", "envelope_id": "E1", "payload": {
            "command": "/temper", "text": "help", "user_id": OWNER, "channel_id": CHANNEL,
            "response_url": "https://hooks.slack.test/r"}})
        assert saved.process(event_id) == "done"
        assert saved.store.get(event_id).outcome == "handled /temper help"
        assert slack.responses  # it answered

    def test_a_failed_message_is_tried_again_not_taken_for_a_repeat(self, saved, handler, monkeypatch):
        from temper_ai.integrations.slack.service import SlackService

        calls = []

        def flaky(event):
            calls.append(event["text"])
            if len(calls) == 1:
                raise RuntimeError("slack blinked")

        monkeypatch.setattr(handler, "message", flaky)
        event_id = SlackService.save({"type": "events_api", "envelope_id": "E1", "payload": {
            "event_id": "Ev1", "event": {"type": "app_mention", "channel": CHANNEL, "ts": "1.1", "text": "hi"}}})
        assert saved.process(event_id) == "failed"
        row = saved.store.get(event_id)
        assert saved.process(event_id, now=row.next_try_at) == "done"
        assert calls == ["hi", "hi"]

    def test_an_envelope_over_30_minutes_old_expires_instead(self, saved, handler, slack):
        from datetime import timedelta

        from temper_ai.integrations.inbox import store as inbox_store

        old, _ = inbox_store.save("slack", "env:E9", kind="/temper help", status="failed", payload={
            "type": "slash_commands", "payload": {"command": "/temper", "text": "help", "user_id": OWNER,
                                                  "channel_id": CHANNEL, "response_url": "https://x"}},
            received_at=datetime.now(UTC) - timedelta(minutes=31))
        assert saved.process(old.id) == "expired"
        assert not slack.responses
        assert saved.store.get(old.id).outcome == "expired: not handled within 30 min"
        ok, why = saved.replay(old.id)
        assert not ok and "expired" in why


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
