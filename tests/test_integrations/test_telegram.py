"""The Telegram bot: who may use it, its commands, plain words (nothing
starts without a press), answering a run's questions in the chat, the
poller, and the TelegramSend agent tool."""

from __future__ import annotations

import itertools
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from temper_ai.integrations.notify import store as notify_store
from temper_ai.integrations.notify.config import ConfigWatcher as NotifyWatcher
from temper_ai.integrations.notify.loop import Notifier
from temper_ai.integrations.slack.answer import Answerer
from temper_ai.integrations.slack.picker import Pick
from temper_ai.integrations.slack.sender import SlackSender
from temper_ai.integrations.telegram import store
from temper_ai.integrations.telegram.client import TelegramError
from temper_ai.integrations.telegram.config import ConfigWatcher
from temper_ai.integrations.telegram.handlers import Handler
from temper_ai.integrations.telegram.poller import Poller
from temper_ai.integrations.telegram.sender import TelegramSender

from .conftest import OWNER, TG_BOT, TG_BOT_NAME, TG_GROUP, TG_OTHER, TG_OWNER
from .test_slack_answer import finish

SHINE = {"id": TG_OWNER, "is_bot": False, "first_name": "Shine", "username": "shine"}
STRANGER = {"id": TG_OTHER, "is_bot": False, "first_name": "Eve"}
PRIVATE = {"id": TG_OWNER, "type": "private", "first_name": "Shine"}
GROUP = {"id": TG_GROUP, "type": "group", "title": "Temper QA"}

QUESTIONS = [
    {"id": "size", "question": "How big?", "options": [{"label": "Small"}, {"label": "Large"}]},
    {"id": "parts", "question": "Which parts?", "multiSelect": True,
     "options": [{"label": "API"}, {"label": "UI"}, {"label": "Docs"}]},
    {"id": "avoid", "question": "Anything I should not touch?"},
]

_updates = itertools.count(1)
_messages = itertools.count(5000)


class FakePicker:
    def __init__(self, pick: Pick) -> None:
        self.result = pick
        self.asked: list[tuple[str, str]] = []

    def pick(self, request: str, conversation: str = "") -> Pick:
        self.asked.append((request, conversation))
        return self.result


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC) - timedelta(minutes=1)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def picker() -> FakePicker:
    return FakePicker(Pick(workflow="gate_demo", inputs={"topic": "weekly"}, reason="it asks before the end"))


@pytest.fixture
def bot(telegram, ops, notify_config, picker) -> Handler:
    return Handler(telegram, ConfigWatcher(), ops, picker=picker,  # type: ignore[arg-type]
                   answerer=Answerer(ops, timeout_s=0, sleep=lambda _s: None), bot=telegram.get_me(),
                   notify_config=NotifyWatcher(), sender=TelegramSender(telegram, ConfigWatcher()))  # type: ignore[arg-type]


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def notifier(slack, telegram, ops, notify_config, clock) -> Notifier:
    n = Notifier(NotifyWatcher(), ops, clock=clock)
    n.register(SlackSender(slack))
    n.register(TelegramSender(telegram, ConfigWatcher()))  # type: ignore[arg-type]
    assert n.tick() == []   # notices are on from a minute ago
    return n


def say(bot: Handler, text: str, chat: dict | None = None, user: dict | None = None,
        reply_to: dict | None = None) -> None:
    msg = {"message_id": next(_messages), "date": int(time.time()), "chat": chat or PRIVATE,
           "from": user or SHINE, "text": text}
    if reply_to is not None:
        msg["reply_to_message"] = reply_to
    bot.handle({"update_id": next(_updates), "message": msg})


def bot_message(sent: dict, chat: dict | None = None) -> dict:
    """A message the bot sent, as Telegram shows it in a reply or a press."""
    return {"message_id": sent["message_id"], "chat": chat or ({**PRIVATE, "id": sent["chat"]}),
            "from": {"id": TG_BOT, "is_bot": True, "username": TG_BOT_NAME}, "text": sent["text"]}


def press(bot: Handler, sent: dict, data: str, user: dict | None = None, chat: dict | None = None) -> None:
    bot.handle({"update_id": next(_updates), "callback_query": {
        "id": f"cb{next(_updates)}", "from": user or SHINE, "data": data, "message": bot_message(sent, chat)}})


def data_of(telegram, sent: dict, starts: str) -> str:
    """The callback data of the button whose label starts with ``starts``,
    on the message as it is now (its latest edit)."""
    keyboard = sent["keyboard"]
    for e in telegram.edits + telegram.markups:
        if e["message_id"] == sent["message_id"] and e["chat"] == sent["chat"] and e.get("keyboard") is not None:
            keyboard = e["keyboard"]
    for label, data in telegram.buttons(keyboard):
        if label.lstrip("⬜☑️🔘 ").startswith(starts) or label.startswith(starts):
            return data
    raise AssertionError(f"no button {starts!r} in {telegram.buttons(keyboard)}")


def pressable(keyboard: list | None) -> list[str]:
    """The buttons that still do something (link buttons only open temper)."""
    return [b["text"] for row in keyboard or [] for b in row if "callback_data" in b]


def texts(telegram, chat: int = TG_OWNER) -> list[str]:
    return [m["text"] for m in telegram.sent if m["chat"] == chat]


# -- who may use it ---------------------------------------------------------------------


class TestWhoMayUseIt:
    def test_the_owner_is_answered_and_anyone_else_is_not_but_is_listed(self, bot, telegram):
        say(bot, "/help")
        assert "/run" in telegram.last(TG_OWNER)["text"]
        say(bot, "/help", chat={"id": TG_OTHER, "type": "private"}, user=STRANGER)
        say(bot, "run everything", chat={"id": TG_OTHER, "type": "private"}, user=STRANGER)
        assert texts(telegram, TG_OTHER) == []
        refused = store.chats("refused")
        assert [c["chat_id"] for c in refused] == [TG_OTHER] and refused[0]["tries"] == 2

    def test_added_to_a_group_by_the_owner_it_stays_and_says_hello(self, bot, telegram):
        bot.handle({"update_id": next(_updates), "my_chat_member": {
            "chat": GROUP, "from": SHINE, "old_chat_member": {"status": "left"},
            "new_chat_member": {"status": "member", "user": {"id": TG_BOT}}}})
        assert telegram.left == [] and "/help" in telegram.last(TG_GROUP)["text"]
        assert store.chat(TG_GROUP)["status"] == "allowed"
        say(bot, "/status", chat=GROUP, user=STRANGER)   # anyone in an allowed group
        assert "No runs are going" in telegram.last(TG_GROUP)["text"]

    def test_added_by_anyone_else_it_leaves_at_once(self, bot, telegram):
        bot.handle({"update_id": next(_updates), "my_chat_member": {
            "chat": GROUP, "from": STRANGER, "old_chat_member": {"status": "left"},
            "new_chat_member": {"status": "member", "user": {"id": TG_BOT}}}})
        assert telegram.left == [TG_GROUP] and texts(telegram, TG_GROUP) == []
        assert store.chat(TG_GROUP)["status"] == "left"

    def test_a_group_with_no_owner_in_it_is_left_when_it_talks(self, bot, telegram):
        say(bot, f"@{TG_BOT_NAME} hi", chat=GROUP, user=STRANGER)
        assert telegram.left == [TG_GROUP] and texts(telegram, TG_GROUP) == []

    def test_a_group_the_owner_is_in_may_use_it(self, bot, telegram):
        telegram.members[(TG_GROUP, TG_OWNER)] = "member"
        say(bot, f"/status@{TG_BOT_NAME}", chat=GROUP, user=STRANGER)
        assert "No runs are going" in telegram.last(TG_GROUP)["text"] and telegram.left == []

    def test_in_a_group_it_hears_only_commands_mentions_and_replies_to_it(self, bot, telegram, picker):
        telegram.members[(TG_GROUP, TG_OWNER)] = "member"
        say(bot, "what a day", chat=GROUP)
        say(bot, "/help@some_other_bot", chat=GROUP)
        assert texts(telegram, TG_GROUP) == [] and picker.asked == []
        say(bot, f"@{TG_BOT_NAME} run the weekly report", chat=GROUP)
        assert picker.asked == [("run the weekly report", "")]


# -- commands ---------------------------------------------------------------------------


class TestCommands:
    def test_run_starts_it_and_its_messages_reply_here(self, bot, telegram, ops):
        say(bot, "/run gate_demo topic=\"weekly summary\" rounds=2")
        assert ops.started == [("gate_demo", {"topic": "weekly summary", "rounds": 2})]
        eid = next(iter(ops.runs))
        started = telegram.last(TG_OWNER)
        assert "started by Shine" in started["text"]
        assert store.threads_of(eid, origin_only=True) == [(TG_OWNER, started["message_id"])]
        assert store.actions()[0]["action"] == "run"

    def test_bad_runs_start_nothing_and_say_why(self, bot, telegram, ops):
        say(bot, "/run nope")
        assert "There is no workflow" in telegram.last(TG_OWNER)["text"]
        say(bot, "/run gate_demo rounds=two")
        assert "Not started" in telegram.last(TG_OWNER)["text"] and ops.started == []

    def test_list_search_status_and_stop(self, bot, telegram, ops):
        say(bot, "/list")
        assert "gate_demo" in telegram.last(TG_OWNER)["text"] and "trigger_probe" in telegram.last(TG_OWNER)["text"]
        say(bot, "/search approve")
        assert "gate_demo" in telegram.last(TG_OWNER)["text"]
        ops.add_run("abcdef12-3456", "trigger_probe", "running", datetime.now(UTC))
        say(bot, "/status")
        assert "trigger_probe" in telegram.last(TG_OWNER)["text"]
        say(bot, "/status abcdef12")
        assert "running" in telegram.last(TG_OWNER)["text"]
        say(bot, "/stop abcdef12")
        assert ops.cancelled == [("abcdef12-3456", "Stopped in Telegram by Shine")]
        assert "Stopping" in telegram.last(TG_OWNER)["text"]

    def test_ask_answers_a_question_about_the_code(self, bot, telegram, ops):
        finish(ops, "Looking.\n<answer>*Yes.* `backend/trips/routes.py` serves `/ics`.</answer>")
        say(bot, "/ask does roamee export calendars?")
        placeholder = next(m for m in telegram.sent if "Reading the code" in m["text"])
        answer = [e for e in telegram.edits if e["message_id"] == placeholder["message_id"]][-1]
        assert "backend/trips/routes.py" in answer["text"] and "<answer>" not in answer["text"]
        assert ops.started[0][0] == "repo_answer"

    def test_ask_with_no_question_and_typos_are_explained(self, bot, telegram, ops):
        say(bot, "/ask")
        say(bot, "/strat")
        assert ops.started == [] and all("⚠️" in t for t in texts(telegram)[-2:])


# -- plain words ---------------------------------------------------------------------------


class TestPlainWords:
    def test_a_suggestion_starts_only_when_start_is_pressed_and_only_once(self, bot, telegram, ops, picker):
        say(bot, "run the weekly thing")
        proposal = telegram.last(TG_OWNER)
        latest = telegram.edits[-1]
        assert "gate_demo" in latest["text"] and ops.started == []
        buttons = [label for label, _ in telegram.buttons(latest["keyboard"])]
        assert buttons == ["▶️ Start", "Cancel"]
        start = telegram.buttons(latest["keyboard"])[0][1]
        press(bot, proposal, start)
        press(bot, proposal, start)
        assert ops.started == [("gate_demo", {"topic": "weekly"})]
        assert telegram.callbacks[-1][1] == "Already started."
        eid = next(iter(ops.runs))
        assert store.threads_of(eid, origin_only=True) == [(TG_OWNER, proposal["message_id"])]

    def test_cancel_starts_nothing(self, bot, telegram, ops):
        say(bot, "run the weekly thing")
        proposal = telegram.last(TG_OWNER)
        cancel = telegram.buttons(telegram.edits[-1]["keyboard"])[1][1]
        press(bot, proposal, cancel)
        start = telegram.buttons(telegram.edits[-2]["keyboard"])[0][1]
        press(bot, proposal, start)
        assert ops.started == [] and "Cancelled by Shine" in telegram.edits[-1]["text"]

    def test_nothing_fits_so_it_asks_and_a_reply_carries_the_conversation(self, bot, telegram, picker):
        picker.result = Pick(workflow=None, question="Which report do you mean?")
        say(bot, "do the thing")
        asked = telegram.last(TG_OWNER)
        assert "Which report" in telegram.edits[-1]["text"]
        say(bot, "the weekly one", reply_to=bot_message({**asked, "text": telegram.edits[-1]["text"]}))
        assert picker.asked[-1][0] == "the weekly one" and "Which report" in picker.asked[-1][1]


# -- answering a run's questions -------------------------------------------------------------


def start_and_gate(bot, telegram, ops, notifier, clock, questions=QUESTIONS) -> tuple[str, dict]:
    """/run in Telegram, the run gates, the loop asks: (run id, question message)."""
    say(bot, "/run gate_demo topic=weekly")
    eid = next(iter(ops.runs))
    ops.add_gate("ev-1", eid, "approve_step", clock.now + timedelta(seconds=30), questions=questions)
    clock.now += timedelta(minutes=1)
    notifier.tick()
    return eid, telegram.last(TG_OWNER)


class TestQuestions:
    def test_asked_under_the_run_in_telegram_and_nowhere_else(self, bot, telegram, slack, ops, notifier, clock):
        eid, question = start_and_gate(bot, telegram, ops, notifier, clock)
        started = next(m for m in telegram.sent if "started by" in m["text"])
        assert question["reply_to"] == started["message_id"] and slack.posts == []
        assert "How big?" in question["text"] and not question["quiet"]
        labels = [label for label, _ in telegram.buttons(question["keyboard"])]
        assert labels[:2] == ["Small", "Large"] and "✅ Approve" in labels and "⛔ Reject" in labels

    def test_choices_picks_and_a_typed_answer_reach_the_next_step(self, bot, telegram, slack, ops, notifier, clock):
        eid, question = start_and_gate(bot, telegram, ops, notifier, clock)
        press(bot, question, data_of(telegram, question, "Large"))      # moves on to question 2
        press(bot, question, data_of(telegram, question, "API"))
        press(bot, question, data_of(telegram, question, "Docs"))
        press(bot, question, data_of(telegram, question, "UI"))
        press(bot, question, data_of(telegram, question, "UI"))         # and off again
        press(bot, question, data_of(telegram, question, "Next"))
        press(bot, question, data_of(telegram, question, "✏️ Type"))
        prompt = telegram.last(TG_OWNER)
        assert prompt["force_reply"] and prompt["reply_to"] == question["message_id"]
        say(bot, "the billing code", reply_to=bot_message(prompt))
        assert "Noted as your answer to question 3" in telegram.last(TG_OWNER)["text"]
        assert ops.answers == []                                         # nothing until Approve
        press(bot, question, data_of(telegram, question, "✅ Approve"))
        got = ops.answers[0]
        assert {a["id"]: (a["selected"], a["custom"]) for a in got["answers"]} == {
            "size": (["Large"], ""), "parts": (["API", "Docs"], ""), "avoid": ([], "the billing code")}
        assert got["by"] == "Shine (Telegram)" and ops.approved == [(eid, "approve_step")]
        closed = telegram.edits[-1]
        assert closed["message_id"] == question["message_id"] and not pressable(closed["keyboard"])
        assert "Approved by Shine in Telegram" in closed["text"] and "the billing code" in closed["text"]

    def test_a_reply_to_the_question_itself_is_a_typed_answer(self, bot, telegram, ops, notifier, clock):
        eid, question = start_and_gate(bot, telegram, ops, notifier, clock,
                                       questions=[{"id": "why", "question": "Why now?"}])
        say(bot, "because it is Friday", reply_to=bot_message(question))
        press(bot, question, data_of(telegram, question, "✅ Approve"))
        assert ops.answers[0]["answers"] == [
            {"id": "why", "question": "Why now?", "selected": [], "custom": "because it is Friday"}]

    def test_reject_asks_once_more_then_stops_the_run(self, bot, telegram, ops, notifier, clock):
        eid, question = start_and_gate(bot, telegram, ops, notifier, clock)
        press(bot, question, data_of(telegram, question, "⛔ Reject"))
        assert ops.cancelled == [] and "Sure?" in telegram.edits[-1]["text"]
        press(bot, question, data_of(telegram, question, "⛔ Yes"))
        assert ops.cancelled == [(eid, "Rejected in Telegram by Shine")]
        assert not pressable(telegram.edits[-1]["keyboard"]) and "Rejected" in telegram.edits[-1]["text"]

    def test_answered_in_telegram_closes_the_slack_copy(self, bot, telegram, slack, ops, notifier, clock):
        say(bot, "/run gate_demo topic=weekly")
        eid = next(iter(ops.runs))
        notify_store.save_run_settings(eid, {"question": ["origin", "slack"]})
        ops.add_gate("ev-1", eid, "approve_step", clock.now + timedelta(seconds=30), questions=QUESTIONS[:1])
        clock.now += timedelta(minutes=1)
        notifier.tick()
        question = telegram.last(TG_OWNER)
        assert [p["channel"] for p in slack.posts] == [f"D{OWNER}"]
        press(bot, question, data_of(telegram, question, "Small"))
        press(bot, question, data_of(telegram, question, "✅ Approve"))
        clock.now += timedelta(seconds=20)
        notifier.tick()
        update = slack.updates[-1]
        assert update["ts"] == slack.posts[0]["ts"] and "Shine" in str(update) and "Telegram" in str(update)
        assert not any(b.get("type") == "actions" for b in update["blocks"])

    def test_answered_in_the_dashboard_first_the_press_changes_nothing(self, bot, telegram, ops, notifier, clock):
        eid, question = start_and_gate(bot, telegram, ops, notifier, clock)
        ops.approve(eid, "approve_step", by="ana (dashboard)")
        press(bot, question, data_of(telegram, question, "Small"))
        assert telegram.callbacks[-1][1] == "This was already answered." and len(ops.answers) == 1
        assert not pressable(telegram.edits[-1]["keyboard"]) and "ana" in telegram.edits[-1]["text"]

    def test_after_a_restart_approve_resumes_the_run(self, bot, telegram, ops, notifier, clock):
        eid, question = start_and_gate(bot, telegram, ops, notifier, clock)
        ops.alive.discard(eid)
        press(bot, question, data_of(telegram, question, "✅ Approve"))
        assert ops.resumed == [eid] and "resumed" in telegram.edits[-1]["text"].lower()

    def test_a_stranger_cannot_press_and_old_buttons_are_refused(self, bot, telegram, ops, notifier, clock):
        eid, question = start_and_gate(bot, telegram, ops, notifier, clock)
        press(bot, {**question, "chat": TG_OTHER}, data_of(telegram, question, "✅ Approve"),
              user=STRANGER, chat={"id": TG_OTHER, "type": "private"})
        assert telegram.callbacks[-1][1] == "Not allowed here." and ops.answers == []
        press(bot, {**question, "message_id": 1}, data_of(telegram, question, "✅ Approve"))
        assert telegram.callbacks[-1][1] == "That button is out of date." and ops.answers == []

    def test_the_stop_button_on_a_quiet_run_asks_then_stops(self, bot, telegram, ops, notify_config):
        ops.add_run("run-q", "trigger_probe", "running", datetime.now(UTC))
        copy = notify_store.claim("stuck:run-q@x", "stuck", "run-q", "telegram", str(TG_OWNER))
        assert copy is not None
        sent = telegram.send(TG_OWNER, "quiet", keyboard=[[{"text": "⏹ Stop run", "callback_data": f"s:{copy.id}"}]])
        notify_store.mark(copy.id, "sent", ref=f"{TG_OWNER}:{sent['message_id']}")
        message = {**telegram.last(TG_OWNER)}
        press(bot, message, f"s:{copy.id}")
        assert ops.cancelled == [] and telegram.callbacks[-1][1] == "Stop this run?"
        press(bot, message, f"s:{copy.id}:y")
        assert ops.cancelled == [("run-q", "Stopped in Telegram by Shine")]


# -- the poller ------------------------------------------------------------------------------


class TestPoller:
    def test_hands_on_new_updates_once_and_skips_stale_ones(self, telegram):
        now = time.time()
        telegram.updates = [
            {"update_id": 10, "message": {"date": int(now - 3600), "text": "old"}},
            {"update_id": 11, "message": {"date": int(now), "text": "new"}},
            {"update_id": 12, "callback_query": {"id": "c"}},
        ]
        got: list[dict] = []
        poller = Poller(telegram, got.append, timeout=0)   # type: ignore[arg-type]
        assert poller.poll_once() == 2 and [u["update_id"] for u in got] == [11, 12]
        assert poller.skipped == 1 and store.get_state("offset") == "13"
        assert poller.poll_once() == 0 and len(got) == 2

    def test_a_second_process_is_reported_not_fought(self):
        class Busy:
            def get_updates(self, *a, **k):
                raise TelegramError("getUpdates", 409, "Conflict: terminated by other getUpdates request")

        poller = Poller(Busy(), lambda u: None, sleep=lambda _s: poller.stop())   # type: ignore[arg-type]
        poller._loop()
        assert poller.conflict and "409" in (poller.last_error or "")

    def test_off_in_tests_and_without_a_token(self, monkeypatch):
        from temper_ai.integrations.telegram import service

        monkeypatch.setenv("TEMPER_TELEGRAM", "0")
        assert service.start_telegram() is None
        monkeypatch.setenv("TEMPER_TELEGRAM", "1")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        assert service.start_telegram() is None


# -- the agent tool --------------------------------------------------------------------------


class TestTelegramSend:
    @pytest.fixture
    def tool(self, telegram, notify_config, monkeypatch):
        from temper_ai.integrations.telegram import client as client_mod
        from temper_ai.tools.telegram import TelegramSend

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test")
        monkeypatch.setattr(client_mod, "TelegramClient", lambda *a, **k: telegram)
        t = TelegramSend()
        t.bind_context(SimpleNamespace(run_id="run-7"))
        return t

    def test_posts_to_the_runs_own_chat_under_its_first_message(self, tool, telegram):
        store.save_thread("run-7", TG_GROUP, 55, origin=True)
        result = tool.execute(to="origin", text="*Done*: 3 files")
        assert result.success and telegram.last()["chat"] == TG_GROUP and telegram.last()["reply_to"] == 55
        assert "<b>Done</b>" in telegram.last()["text"]

    def test_posts_to_a_place_agents_may_use(self, tool, telegram):
        assert tool.execute(to="telegram", text="hello").success
        assert telegram.last()["chat"] == TG_OWNER

    def test_refuses_anywhere_else(self, tool, telegram):
        for to in ("qa-group", str(TG_OWNER), "slack"):
            result = tool.execute(to=to, text="hello")
            assert not result.success and "may not send" in (result.error or "")
        no_origin = tool.execute(to="origin", text="hello")
        assert not no_origin.success and "not started from Telegram" in (no_origin.error or "")
        assert telegram.sent == []
