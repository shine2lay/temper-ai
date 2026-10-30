"""Clarification answers over Telegram (M2): temper_ai/integrations/telegram/clarifications.py.

The combined clean path comes first, through the fake provider edge
(FakeTelegram) and a fake store; then every refusal and crash point; then the
default-off regression. Every guard has its own bite: test_every_guard_bites
changes the guard's line in an in-memory copy of the module (never the file),
and the guard's case must then fail.

These fakes prove that the code enforces provenance. They are not evidence of
a live human.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import itertools
import json
import re
import sys
import time
import types
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

import temper_ai
from temper_ai.clarifications.contracts import (
    ActionIdentity,
    ConfirmedText,
    ContractRefusal,
    Presentation,
    RefusalCode,
    StreamKey,
    TransportNamespace,
    metadata_sha256,
    question_id,
    receipt_sha256,
)
from temper_ai.integrations.inbox import store as inbox_store
from temper_ai.integrations.notify.config import ConfigWatcher as NotifyWatcher
from temper_ai.integrations.slack.answer import Answerer
from temper_ai.integrations.slack.picker import Pick
from temper_ai.integrations.telegram import clarifications as edge_module
from temper_ai.integrations.telegram import poller as poller_module
from temper_ai.integrations.telegram import store as telegram_store
from temper_ai.integrations.telegram.client import TelegramError
from temper_ai.integrations.telegram.config import ConfigWatcher
from temper_ai.integrations.telegram.handlers import Handler
from temper_ai.integrations.telegram.sender import TelegramSender
from temper_ai.integrations.telegram.service import TelegramService

from .conftest import TG_BOT, TG_GROUP, TG_OTHER, TG_OWNER, FakeTelegram

# Synthetic data only: no real responder list, chat or answer.
BRIEF_SHA = hashlib.sha256(b"A synthetic brief for the Telegram clarification tests.\n").hexdigest()
UNKNOWN = {
    "question": "Must it work offline?", "why_it_matters": "Changes storage and sync.",
    "decisions_affected": ["client storage"], "material": True, "field": "constraints",
}
UNKNOWN_2 = {
    "question": "Who may approve refunds?", "why_it_matters": "Changes roles and audit.",
    "decisions_affected": ["permissions"], "material": False, "field": "goals",
}
NAMESPACE = "temper-clarify:synthetic/telegram-edge"
POLICY = "responder-policy:synthetic/telegram-edge"
BOT = TransportNamespace("telegram", str(TG_BOT))
QUESTION = "Must it work offline?\nReply to this message with your answer."
EXACT = "  Yes: offline first.\r\nSync later \u2014 caf\u00e9 \u6771\u4eac \U0001f642  "
ELSEWHERE = -5000000009  # another group the bot is in


def digest(update: dict[str, Any]) -> str:
    """The ingress digest as documented: SHA-256 of the update's canonical ASCII JSON."""
    body = json.dumps(update, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(body.encode("ascii")).hexdigest()


class FakeStore:
    """The store protocol in memory. Each call is logged with the poll offset at that moment.

    ``fail`` names a method that raises, as a store that is down would. It is
    lenient about order (a send with no kept intent is logged, not refused), so
    the edge's own order is what the tests check.
    """

    def __init__(self, module: types.ModuleType) -> None:
        self.M = module
        self.sends: dict[str, Any] = {}
        self.delivered: dict[tuple[TransportNamespace, str, str], str] = {}
        self.generations: dict[tuple[str, str], int] = {}
        self.questions: dict[str, frozenset[str]] = {}
        self.done: set[tuple[str, str]] = set()
        self.held: dict[str, tuple[Any, Any, Any]] = {}
        self.refused: list[Any] = []
        self.log: list[tuple[str, str | None]] = []
        self.fail: str | None = None
        self.any_bot = False  # a broken store that ignores which bot a delivery came from

    def note(self, name: str) -> None:
        self.log.append((name, telegram_store.get_state(poller_module.OFFSET_KEY)))
        if self.fail == name:
            raise RuntimeError(f"the store is down ({name})")

    def ask(self, presentation: Presentation) -> None:
        """The latest record asks this question, at this generation."""
        stream = presentation.stream.stream_id
        self.generations[(stream, presentation.question_id)] = presentation.generation
        self.questions[stream] = self.questions.get(stream, frozenset()) | {presentation.question_id}

    def save_send(self, intent: Any) -> Any:
        self.note("save_send")
        return self.sends.setdefault(intent.send_id, self.M.SendRecord(intent))

    def start_attempt(self, send_id: str) -> Any:
        self.note("start_attempt")
        if send_id in self.sends:
            self.sends[send_id] = replace(self.sends[send_id], attempts=self.sends[send_id].attempts + 1)
        return self.sends.get(send_id)

    def record_delivery(self, send_id: str, message_id: str) -> Any:
        self.note("record_delivery")
        if send_id in self.sends:
            record = self.sends[send_id] = replace(self.sends[send_id], message_id=message_id)
            presentation = record.intent.presentation
            self.delivered[(presentation.transport, presentation.chat_id, message_id)] = send_id
        return self.sends.get(send_id)

    def delivery(self, transport: TransportNamespace, chat_id: str, message_id: str) -> Any:
        self.note("delivery")
        for (bot, chat, message), send_id in self.delivered.items():
            if (bot == transport or self.any_bot) and (chat, message) == (chat_id, message_id):
                return self.sends[send_id]
        return None

    def copies(self, presentation_id: str) -> frozenset[str]:
        return frozenset(record.message_id for record in self.sends.values() if record.message_id is not None
                         and record.intent.presentation.presentation_id == presentation_id)

    def current_generation(self, stream_id: str, question_id: str) -> int:
        return self.generations[(stream_id, question_id)]

    def question_ids(self, stream_id: str) -> frozenset[str]:
        return self.questions.get(stream_id, frozenset())

    def answered(self, stream_id: str, question_id: str) -> bool:
        return (stream_id, question_id) in self.done

    def receipt(self, action_key: str) -> Any:
        held = self.held.get(action_key)
        return held[1] if held is not None else None

    def keep_receipt(self, ingress: Any, receipt: Any, validation: Any) -> tuple[Any, bool]:
        self.note("keep_receipt")
        key = receipt.action.key
        if key in self.held:
            return self.held[key][1], False
        self.held[key] = (ingress, receipt, validation)
        return receipt, True

    def keep_refusal(self, refusal: Any) -> None:
        self.note("keep_refusal")
        self.refused.append(refusal)


class FakePolicy:
    """Who may answer, as (policy, chat, sender) triples. Injected and synthetic."""

    def __init__(self) -> None:
        self.allowed = {(POLICY, str(TG_GROUP), str(TG_OWNER)), (POLICY, str(TG_OWNER), str(TG_OWNER))}
        self.calls: list[tuple[str, str, str]] = []
        self.answer: object = None  # when set, the answer whoever asks
        self.fail = False

    def decide(self, *, policy_ref: str, chat_id: str, sender_id: str) -> object:
        self.calls.append((policy_ref, chat_id, sender_id))
        if self.fail:
            raise RuntimeError("the responder policy is down")
        if self.answer is not None:
            return self.answer
        return "authorised" if (policy_ref, chat_id, sender_id) in self.allowed else "denied"


class _Picker:
    """Picks a synthetic workflow for an ordinary message; never a model."""

    def pick(self, request: str, conversation: str = "") -> Pick:
        return Pick(workflow="gate_demo", inputs={"topic": "weekly"}, reason="synthetic")


class World:
    """One bot: the fake provider, a fake store and policy, the edge and the server's poller."""

    def __init__(self, telegram: FakeTelegram, M: types.ModuleType = edge_module,
                 P: types.ModuleType = poller_module) -> None:
        self.telegram, self.M, self.P = telegram, M, P
        self.store = FakeStore(M)
        self.policy = FakePolicy()
        self.edge = M.ClarificationEdge(telegram, self.store, self.policy)
        self.got: list[Any] = []
        self.poller = P.Poller(telegram, self.got.append, timeout=0, accept=TelegramService.save,
                               skip=TelegramService.save_skipped, clarifications=self.edge)
        self.ack_fails = False
        self._updates = itertools.count(1)
        self._messages = itertools.count(5000)
        self._queries = itertools.count(1)
        send, answer = telegram.send, telegram.answer_callback

        def logged_send(*args: Any, **kwargs: Any) -> dict[str, Any]:
            self.store.note("client.send")
            return send(*args, **kwargs)

        def logged_answer(callback_id: str, text: str = "", alert: bool = False) -> None:
            self.store.note("client.answer_callback")
            if self.ack_fails:
                raise TelegramError("answerCallbackQuery", 400, "Bad Request: query is too old")
            answer(callback_id, text, alert)

        telegram.send = logged_send  # type: ignore[method-assign]
        telegram.answer_callback = logged_answer  # type: ignore[method-assign]

    # --- presenting ---------------------------------------------------------------

    def presentation(self, unknown: dict[str, Any] = UNKNOWN, *, generation: int = 1, chat: int = TG_GROUP,
                     bot: TransportNamespace = BOT, metadata: dict[str, Any] | None = None) -> Presentation:
        return Presentation(
            stream=StreamKey(NAMESPACE, BRIEF_SHA), question_id=question_id(BRIEF_SHA, unknown),
            metadata_sha256=metadata_sha256(unknown if metadata is None else metadata), generation=generation,
            responder_policy_ref=POLICY, transport=bot, chat_id=str(chat),
        )

    def ask(self, unknown: dict[str, Any] = UNKNOWN, *, generation: int = 1,
            chat: int = TG_GROUP) -> tuple[Presentation, int]:
        """Present a question the latest record asks; returns it and its delivered message ID."""
        presentation = self.presentation(unknown, generation=generation, chat=chat)
        self.store.ask(presentation)
        result = self.edge.present(presentation, unknown, QUESTION)
        assert (result.state, result.send_id) == ("sent", presentation.presentation_id)
        return presentation, int(result.message_id)

    # --- what Telegram hands the bot ------------------------------------------------

    @staticmethod
    def chat(chat_id: int) -> dict[str, Any]:
        if chat_id > 0:
            return {"id": chat_id, "type": "private", "first_name": "Synthetic"}
        return {"id": chat_id, "type": "supergroup", "title": "Synthetic group"}

    @staticmethod
    def user(user_id: int, is_bot: bool = False) -> dict[str, Any]:
        return {"id": user_id, "is_bot": is_bot, "first_name": "Synthetic"}

    def add(self, update: dict[str, Any]) -> dict[str, Any]:
        update = {"update_id": next(self._updates), **update}
        self.telegram.updates.append(update)
        return update

    def message(self, text: Any, *, user: int = TG_OWNER, chat: int = TG_GROUP, is_bot: bool = False,
                date: int | None = None, **extra: Any) -> dict[str, Any]:
        message: dict[str, Any] = {"message_id": next(self._messages), "date": date or int(time.time()),
                                   "chat": self.chat(chat), "from": self.user(user, is_bot)}
        if text is not None:
            message["text"] = text
        message.update(extra)
        return self.add({"message": message})

    def reply(self, to: int, text: Any, *, chat: int = TG_GROUP, replied_chat: int | None = None,
              **kwargs: Any) -> dict[str, Any]:
        replied = {"message_id": to, "date": int(time.time()), "chat": self.chat(replied_chat or chat),
                   "from": self.user(TG_BOT, True), "text": "(a message the bot sent)"}
        return self.message(text, chat=chat, reply_to_message=replied, **kwargs)

    def press(self, on: int, data: str | None, *, user: int = TG_OWNER, chat: int = TG_GROUP) -> dict[str, Any]:
        query: dict[str, Any] = {
            "id": f"cq{next(self._queries)}", "from": self.user(user), "chat_instance": "-1",
            "message": {"message_id": on, "date": int(time.time()), "chat": self.chat(chat),
                        "from": self.user(TG_BOT, True), "text": "(a message the bot sent)"},
        }
        if data is not None:
            query["data"] = data
        return self.add({"callback_query": query})

    # --- looking --------------------------------------------------------------------

    def poll(self) -> int:
        """One getUpdates through the server's poller. Checks that nothing was kept,
        sent or acknowledged after the offset moved."""
        start = self.offset()
        mark = len(self.store.log)
        handed = self.poller.poll_once()
        late = [entry for entry in self.store.log[mark:] if entry[1] != start]
        assert late == [], f"done after the offset moved: {late}"
        return handed

    def offset(self) -> str | None:
        return telegram_store.get_state(self.P.OFFSET_KEY)

    def rewind(self, update: dict[str, Any]) -> None:
        """Telegram sends this update, and the ones after it, again."""
        telegram_store.set_state(self.P.OFFSET_KEY, str(update["update_id"]))

    def store_calls(self) -> list[str]:
        return [name for name, _ in self.store.log if not name.startswith("client.")]

    def prompts(self) -> list[dict[str, Any]]:
        return [sent for sent in self.telegram.sent if sent["keyboard"]]

    @staticmethod
    def key(update: dict[str, Any]) -> str:
        if "message" in update:
            message = update["message"]
            return ActionIdentity(BOT, str(message["chat"]["id"]), "message", str(message["message_id"])).key
        query = update["callback_query"]
        return ActionIdentity(BOT, str(query["message"]["chat"]["id"]), "callback", query["id"]).key

    def held(self, update: dict[str, Any]) -> tuple[Any, Any, Any]:
        """(ingress, receipt, verdict) held under the update's action key."""
        key = self.key(update)
        assert key in self.store.held, f"nothing held for update {update['update_id']}"
        return self.store.held[key]

    def refusals(self) -> list[tuple[RefusalCode, str]]:
        return [(refusal.code, refusal.guard) for refusal in self.store.refused]

    def refusal(self) -> Any:
        assert len(self.store.refused) == 1, self.refusals()
        return self.store.refused[0]


# --- the combined clean path ----------------------------------------------------------


def test_clean_path_typed_reply_then_own_press_keeps_the_exact_words(telegram, M=edge_module, P=poller_module):
    """Ask, a typed reply, the prompt, the author's own press: accepted with the words exactly as typed."""
    w = World(telegram, M, P)
    presentation, question = w.ask()
    assert [name for name, _ in w.store.log] == ["save_send", "start_attempt", "client.send", "record_delivery"]
    asked = telegram.sent[-1]
    assert (asked["text"], asked["keyboard"], asked["force_reply"]) == (QUESTION, None, M.ANSWER_HINT)

    typed = w.reply(question, EXACT)
    assert w.poll() == 0  # nothing went the ordinary way
    ingress, receipt, verdict = w.held(typed)
    assert ingress == M.PulledIngress(BOT, typed["update_id"], digest(typed), None)
    assert (receipt.ingress, receipt.text) == ("provider_pull", EXACT)
    assert receipt.text_sha256 == hashlib.sha256(EXACT.encode()).hexdigest()
    assert (receipt.binding.presentation_id, receipt.binding.message_id) == (presentation.presentation_id, str(question))
    assert (verdict.status, verdict.code) == ("retained", RefusalCode.NO_EXPLICIT_DISPOSITION)
    prompt = telegram.sent[-1]
    assert prompt["reply_to"] == typed["message"]["message_id"]
    assert [button["callback_data"] for button in prompt["keyboard"][0]] == [
        "clar:answered", "clar:deferred", "clar:unknown"]
    assert w.offset() == str(typed["update_id"] + 1)

    press = w.press(prompt["message_id"], "clar:answered")
    assert w.poll() == 0
    ingress, pressed, verdict = w.held(press)
    assert ingress == M.PulledIngress(BOT, press["update_id"], digest(press), typed["update_id"] + 1)
    confirmed = ConfirmedText(receipt.action, receipt.sender_id, receipt.text_sha256)
    assert (pressed.confirms, pressed.callback_data) == (confirmed, "clar:answered")
    assert verdict.status == "accepted" and verdict.receipt_sha256 == receipt_sha256(pressed)
    event = verdict.event()
    assert (event["kind"], event["answer"], event["disposition"]) == ("answer", EXACT, "answered")
    assert event["question_id"] == presentation.question_id
    assert event["actor"] == {"kind": "human", "ref": f"telegram-user:{TG_OWNER}"}
    assert event["source"] == {"kind": "human_response", "ref": f"clarification-receipt:{verdict.receipt_sha256}"}
    assert telegram.callbacks == [(press["callback_query"]["id"], "Received.", False)]
    assert w.policy.calls == [(POLICY, str(TG_GROUP), str(TG_OWNER))] * 2
    assert w.edge.counts == {"accepted": 1, "retained": 1, "refused": 0, "repeat": 0}
    assert w.got == [] and w.offset() == str(press["update_id"] + 1)
    assert inbox_store.find("telegram", str(typed["update_id"])) is None
    assert inbox_store.find("telegram", str(press["update_id"])) is None


# --- exact words ------------------------------------------------------------------------


def test_words_are_kept_exactly_as_typed(telegram, M=edge_module, P=poller_module):
    """No strip, no normalisation: spaces, line ends, combining marks, joiners and direction marks stay."""
    w = World(telegram, M, P)
    _, question = w.ask()
    texts = [" leading", "trailing\t", "line\r\nends\n", "e\u0301 is not \u00e9", "\u00a0no-break\u00a0",
             "\U0001f469\u200d\U0001f469\u200d\U0001f467 joined", "\u202eright to left", "x" * M.TEXT_MAX]
    replies = [w.reply(question, text) for text in texts]
    w.poll()
    for update, text in zip(replies, texts, strict=True):
        _, receipt, verdict = w.held(update)
        assert receipt.text == text and receipt.text_sha256 == hashlib.sha256(text.encode()).hexdigest()
        assert verdict.code == RefusalCode.NO_EXPLICIT_DISPOSITION
    assert len(w.prompts()) == len(texts)


def test_overlong_words_are_refused_at_the_edge(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    long = w.reply(question, "x" * (M.TEXT_MAX + 1))
    assert w.poll() == 0
    refusal = w.refusal()
    assert (refusal.code, refusal.guard, refusal.receipt) == (RefusalCode.MALFORMED, "ingress.text_size", None)
    assert refusal.ingress.update_id == long["update_id"] and not w.store.held and not w.prompts()


def test_words_with_no_utf8_form_are_refused_never_repaired(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    w.reply(question, "half \ud83d a face")
    w.reply(question, 12345)
    w.poll()
    assert w.refusals() == [(RefusalCode.MALFORMED, "shape.utf8"), (RefusalCode.MALFORMED, "shape.text")]
    assert not w.store.held and not w.prompts()


def test_a_reply_with_no_words_is_kept_but_never_prompted(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    sticker = w.reply(question, None, sticker={"file_id": "synthetic", "file_unique_id": "s", "type": "regular",
                                               "width": 1, "height": 1, "is_animated": False, "is_video": False})
    blank = w.reply(question, " \u200b\n\ufeff")
    w.poll()
    assert (w.held(sticker)[1].text, w.held(blank)[1].text) == ("", " \u200b\n\ufeff")
    assert {w.held(update)[2].code for update in (sticker, blank)} == {RefusalCode.NO_EXPLICIT_DISPOSITION}
    assert w.prompts() == []


# --- provenance: only the server's own pull -------------------------------------------


def test_only_objects_from_the_servers_own_pull_can_be_claimed(telegram, M=edge_module, P=poller_module):
    """A dict that looks pulled, or says it was, is refused; so is a hand-made batch or another client's pull."""
    w = World(telegram, M, P)
    _, question = w.ask()
    typed = w.reply(question, EXACT)
    batch = w.edge.pull(telegram, None, timeout=0, allowed=P.ALLOWED)
    labelled = {**copy.deepcopy(typed), "source": "provider_pull", "ingress": "provider_pull"}
    for forged in (copy.deepcopy(typed), labelled):
        with pytest.raises(ContractRefusal) as refused:
            batch.claim(forged)
        assert (refused.value.code, refused.value.guard) == (RefusalCode.UNVERIFIED_INGRESS, "edge.pulled")
    with pytest.raises(ContractRefusal) as refused:
        M.PulledBatch(object(), w.edge, BOT, None, [typed])
    assert (refused.value.code, refused.value.guard) == (RefusalCode.UNVERIFIED_INGRESS, "edge.batch")
    with pytest.raises(ContractRefusal) as refused:
        w.edge.pull(FakeTelegram(), None, timeout=0, allowed=P.ALLOWED)
    assert (refused.value.code, refused.value.guard) == (RefusalCode.TRANSPORT_MISMATCH, "edge.client")
    assert w.store_calls() == ["save_send", "start_attempt", "record_delivery"]  # nothing reached the store
    assert batch.claim(batch.updates[0]) is True and w.held(typed)[1].text == EXACT


def test_handler_dicts_and_inbox_rows_never_reach_the_edge(telegram, ops, notify_config, M=edge_module,
                                                           P=poller_module):
    """Handler.handle, TelegramService.save and an inbox row (what the events replay API re-runs, with a
    service key or not) take the ordinary way with the very same updates; only the pull keeps them."""
    w = World(telegram, M, P)
    _, question = w.ask(chat=TG_OWNER)
    direct = w.reply(question, EXACT, chat=TG_OWNER)
    saved = w.reply(question, "Yes", chat=TG_OWNER)
    handler = Handler(telegram, ConfigWatcher(), ops, picker=_Picker(),  # type: ignore[arg-type]
                      answerer=Answerer(ops, timeout_s=0, sleep=lambda _s: None), bot=telegram.get_me(),
                      notify_config=NotifyWatcher(), sender=TelegramSender(telegram, ConfigWatcher()))
    before = w.store_calls()
    handler.handle(copy.deepcopy(direct))
    event_id = TelegramService.save(copy.deepcopy(saved))
    assert event_id is not None
    handler.handle_saved(inbox_store.get(event_id))
    assert w.store_calls() == before and not w.store.held and not w.store.refused
    assert w.poll() == 0
    assert (w.held(direct)[1].text, w.held(saved)[1].text) == (EXACT, "Yes")


def test_no_other_door_into_the_edge():
    """Only a pulled batch's claim takes an update; no method takes a receipt, a label or a row.
    Edited messages are never pulled, so a typed answer cannot change after it is kept."""
    assert {name for name in vars(edge_module.ClarificationEdge) if not name.startswith("_")} == {
        "namespace", "status", "pull", "present"}
    assert {name for name in vars(edge_module.PulledBatch) if not name.startswith("_")} == {"claim"}
    assert "edited_message" not in poller_module.ALLOWED


def test_the_bot_comes_from_the_providers_getme(telegram, M=edge_module, P=poller_module):
    telegram.get_me = lambda: {"id": str(TG_BOT), "is_bot": True}  # type: ignore[method-assign]
    edge = M.ClarificationEdge(telegram, FakeStore(M), FakePolicy())
    with pytest.raises(ContractRefusal):
        edge.pull(telegram, None, timeout=0, allowed=P.ALLOWED)


def test_an_oversized_or_unencodable_update_is_refused_with_its_ingress(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    big = w.reply(question, "Yes")
    big["message"]["reply_to_message"]["text"] = "x" * M.UPDATE_MAX
    nan = w.reply(question, "Yes")
    nan["message"]["reply_to_message"]["x"] = float("nan")
    assert w.poll() == 0
    assert w.refusals() == [(RefusalCode.MALFORMED, "ingress.size")] * 2
    first, second = w.store.refused
    assert first.ingress == M.PulledIngress(BOT, big["update_id"], digest(big), None) and first.receipt is None
    assert (second.ingress.update_id, second.ingress.update_sha256) == (nan["update_id"], None)
    assert not w.store.held and not w.prompts() and w.offset() == str(nan["update_id"] + 1)


def test_a_sender_without_a_numeric_id_is_refused(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    text_id = w.reply(question, "Yes")
    text_id["message"]["from"]["id"] = str(TG_OWNER)
    nobody = w.reply(question, "Yes")
    del nobody["message"]["from"]
    w.poll()
    assert w.refusals() == [(RefusalCode.MALFORMED, "ingress.sender")] * 2
    assert not w.store.held and w.policy.calls == []


def test_overlong_button_data_is_refused(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    w.reply(question, "Yes")
    w.poll()
    prompt = w.prompts()[-1]["message_id"]
    longest = w.press(prompt, "d" * M.CALLBACK_DATA_MAX)
    too_long = w.press(prompt, "d" * (M.CALLBACK_DATA_MAX + 1))
    w.poll()
    assert w.held(longest)[2].code == RefusalCode.NO_EXPLICIT_DISPOSITION
    assert w.refusals() == [(RefusalCode.MALFORMED, "ingress.callback_size")]
    assert w.key(too_long) not in w.store.held


def test_bot_senders_are_refused_and_a_missing_flag_counts_as_a_bot(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    bot = w.reply(question, "Yes", is_bot=True)
    unflagged = w.reply(question, "Yes")
    del unflagged["message"]["from"]["is_bot"]
    w.poll()
    assert w.refusals() == [(RefusalCode.BOT_SENDER, "provenance.bot")] * 2
    assert [refusal.ingress.update_id for refusal in w.store.refused] == [bot["update_id"], unflagged["update_id"]]
    assert not w.store.held and not w.prompts()


COPY_VALUES: dict[str, Any] = {
    "forward_origin": {"type": "hidden_user", "sender_user_name": "Someone", "date": 1},
    "forward_from": {"id": TG_OTHER, "is_bot": False, "first_name": "Synthetic"},
    "forward_from_chat": {"id": ELSEWHERE, "type": "channel", "title": "Synthetic"},
    "forward_from_message_id": 7, "forward_signature": "Someone", "forward_sender_name": "Someone",
    "forward_date": 1, "is_automatic_forward": True,
    "via_bot": {"id": TG_BOT + 1, "is_bot": True, "first_name": "Inline"},
    "sender_chat": {"id": ELSEWHERE, "type": "channel", "title": "Synthetic"},
}


@pytest.mark.parametrize("marker", edge_module.COPY_MARKERS)
def test_forwarded_or_copied_words_are_refused(telegram, marker, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    w.reply(question, "Yes", **{marker: COPY_VALUES[marker]})
    w.poll()
    assert w.refusals() == [(RefusalCode.FORWARDED_MESSAGE, "provenance.forwarded")]
    assert not w.store.held and not w.prompts()


def test_a_member_without_responder_authority_is_refused(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    w.reply(question, "Yes", user=TG_OTHER)
    w.poll()
    assert w.refusals() == [(RefusalCode.RESPONDER_NOT_AUTHORISED, "responder.decision")]
    assert w.refusal().receipt.responder.decision == "denied"
    assert w.policy.calls == [(POLICY, str(TG_GROUP), str(TG_OTHER))]
    assert not w.store.held and not w.prompts()


@pytest.mark.parametrize("answer", [True, 1, "yes", "Authorised", "authorised ", type("S", (str,), {})("authorised")])
def test_only_the_exact_policy_answer_authorises(telegram, answer, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    w.policy.answer = answer
    w.reply(question, "Yes")
    w.poll()
    assert w.refusals() == [(RefusalCode.RESPONDER_NOT_AUTHORISED, "responder.decision")]


def test_an_answer_given_in_another_chat_is_refused(telegram, M=edge_module, P=poller_module):
    """A crafted reply that names the question's message from a different chat."""
    w = World(telegram, M, P)
    _, question = w.ask()
    w.policy.allowed.add((POLICY, str(ELSEWHERE), str(TG_OWNER)))
    w.reply(question, "Yes", chat=ELSEWHERE, replied_chat=TG_GROUP)
    w.poll()
    assert w.refusals() == [(RefusalCode.TRANSPORT_MISMATCH, "provenance.chat")]
    assert w.refusal().receipt.action.chat_id == str(ELSEWHERE)


def test_a_delivery_from_another_bot_is_refused(telegram, M=edge_module, P=poller_module):
    """A store that ignores the bot hands back another bot's delivery: the action stays this bot's and is refused."""
    w = World(telegram, M, P)
    other = TransportNamespace("telegram", str(TG_BOT + 1))
    presentation = w.presentation(bot=other)
    w.store.ask(presentation)
    intent = M.SendIntent(send_id=presentation.presentation_id, presentation=presentation, text=QUESTION)
    w.store.sends[intent.send_id] = M.SendRecord(intent, attempts=1, message_id="900")
    w.store.delivered[(other, str(TG_GROUP), "900")] = intent.send_id
    w.store.any_bot = True
    w.reply(900, "Yes")
    w.poll()
    assert w.refusals() == [(RefusalCode.TRANSPORT_MISMATCH, "provenance.transport")]
    assert w.refusal().receipt.action.transport == BOT


# --- binding: the persisted presentation, never "the current question" -----------------


def test_a_message_that_replies_to_nothing_is_never_bound_to_the_last_question(telegram, M=edge_module,
                                                                               P=poller_module):
    w = World(telegram, M, P)
    w.ask()
    w.message("Yes, offline first.")
    assert w.poll() == 1  # the ordinary way, unchanged
    assert w.store_calls() == ["save_send", "start_attempt", "record_delivery"]
    assert not w.store.held and not w.store.refused


def test_a_reply_or_press_for_an_older_generation_stays_unapplied_and_bound_to_it(telegram, M=edge_module,
                                                                                  P=poller_module):
    w = World(telegram, M, P)
    first, question = w.ask()
    w.reply(question, "Yes")
    w.poll()
    prompt = w.prompts()[-1]["message_id"]
    w.ask(generation=2)
    late_press = w.press(prompt, "clar:answered")
    late_reply = w.reply(question, "Yes, offline first.")
    w.poll()
    for update in (late_press, late_reply):
        _, receipt, verdict = w.held(update)
        assert (verdict.status, verdict.code) == ("retained", RefusalCode.STALE_PRESENTATION)
        assert (receipt.binding.presentation_id, receipt.binding.generation) == (first.presentation_id, 1)
    assert len(w.prompts()) == 1  # nothing is asked again for an old copy
    assert telegram.callbacks == [(late_press["callback_query"]["id"], "Not applied.", False)]


def test_a_reply_to_a_retired_question_is_refused_and_kept_as_a_diagnostic(telegram, M=edge_module,
                                                                           P=poller_module):
    w = World(telegram, M, P)
    presentation, question = w.ask()
    w.store.questions[presentation.stream.stream_id] = frozenset()  # the latest record no longer asks it
    typed = w.reply(question, "Yes")
    w.poll()
    refusal = w.refusal()
    assert (refusal.code, refusal.guard) == (RefusalCode.UNKNOWN_QUESTION, "binding.known_question")
    assert refusal.receipt.text == "Yes" and refusal.receipt_sha256 == receipt_sha256(refusal.receipt)
    assert w.key(typed) not in w.store.held and not w.prompts()


# --- disposition: explicit only ---------------------------------------------------------


def test_typed_words_never_choose_how_they_count(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    words = ["yes", "answered", "This is my answer", "clar:answered", "I don't know", "1"]
    replies = [w.reply(question, text) for text in words]
    w.poll()
    for update in replies:
        _, receipt, verdict = w.held(update)
        assert receipt.disposition is None and verdict.code == RefusalCode.NO_EXPLICIT_DISPOSITION
    assert [prompt["reply_to"] for prompt in w.prompts()] == [update["message"]["message_id"] for update in replies]


def test_only_the_exact_button_data_chooses(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    w.reply(question, "Yes")
    w.poll()
    prompt = w.prompts()[-1]["message_id"]
    presses = [w.press(prompt, data) for data in
               (" clar:answered", "CLAR:ANSWERED", "clar:answered\n", "answered", "", None)]
    w.poll()
    for update in presses:
        _, receipt, verdict = w.held(update)
        assert receipt.disposition is None and verdict.code == RefusalCode.NO_EXPLICIT_DISPOSITION
    assert [ack[1] for ack in telegram.callbacks] == ["Not applied."] * len(presses)


def test_a_press_on_the_question_itself_chooses_nothing(telegram, M=edge_module, P=poller_module):
    """The question has no buttons: data pressed on it (crafted) is kept with no disposition."""
    w = World(telegram, M, P)
    _, question = w.ask()
    press = w.press(question, "clar:answered")
    w.poll()
    _, receipt, verdict = w.held(press)
    assert (receipt.disposition, receipt.confirms) == (None, None)
    assert (verdict.status, verdict.code) == ("retained", RefusalCode.NO_EXPLICIT_DISPOSITION)


def test_only_the_author_can_confirm_their_words(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    w.policy.allowed.add((POLICY, str(TG_GROUP), str(TG_OTHER)))
    _, question = w.ask()
    w.reply(question, "Yes")
    w.poll()
    press = w.press(w.prompts()[-1]["message_id"], "clar:answered", user=TG_OTHER)
    w.poll()
    refusal = w.refusal()
    assert (refusal.code, refusal.guard) == (RefusalCode.CONFIRMER_NOT_AUTHOR, "confirm.author")
    assert w.key(press) not in w.store.held
    assert telegram.callbacks == [(press["callback_query"]["id"], "Not applied.", False)]


# --- action keys: replays, changed bodies, refusals ----------------------------------


def test_a_refused_receipt_never_takes_the_action_key(telegram, M=edge_module, P=poller_module):
    """Security #176 N1: a refusal is kept as a diagnostic only, so the same action can still count later."""
    w = World(telegram, M, P)
    _, question = w.ask()
    w.policy.allowed.clear()
    typed = w.reply(question, "Yes")
    w.poll()
    assert w.refusals() == [(RefusalCode.RESPONDER_NOT_AUTHORISED, "responder.decision")] and not w.store.held
    w.policy.allowed.add((POLICY, str(TG_GROUP), str(TG_OWNER)))
    w.rewind(typed)
    w.poll()
    assert w.held(typed)[2].code == RefusalCode.NO_EXPLICIT_DISPOSITION
    assert len(w.store.refused) == 1 and w.edge.counts["repeat"] == 0


def test_a_changed_body_under_a_held_key_is_refused_and_the_held_words_stay(telegram, M=edge_module,
                                                                           P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    typed = w.reply(question, "Yes")
    w.poll()
    press = w.press(w.prompts()[-1]["message_id"], "clar:deferred")
    w.poll()
    w.add({"callback_query": {**copy.deepcopy(press["callback_query"]), "data": "clar:answered"}})
    w.poll()
    assert w.refusals() == [(RefusalCode.CHANGED_BODY, "replay.body")]
    assert w.refusal().receipt.callback_data == "clar:answered"
    assert w.held(press)[2].event()["disposition"] == "deferred"
    w.add({"message": {**copy.deepcopy(typed["message"]), "text": "No"}})
    w.poll()
    assert w.refusals() == [(RefusalCode.CHANGED_BODY, "replay.body")] * 2
    assert w.store.refused[-1].receipt.text == "No" and w.held(typed)[1].text == "Yes"
    assert len(w.prompts()) == 1
    assert [ack[1] for ack in telegram.callbacks] == ["Received.", "Not applied."]


def test_a_prompt_kept_with_other_words_is_left_as_kept_and_never_stops_the_poller(telegram, M=edge_module,
                                                                                   P=poller_module):
    """Say an older release kept the prompt with other words: on redelivery the reply is a repeat,
    nothing new goes out, the offset still moves, and the mismatch is noted."""
    w = World(telegram, M, P)
    _, question = w.ask()
    typed = w.reply(question, "Yes")
    w.poll()
    send_id = next(key for key, record in w.store.sends.items() if record.intent.reply_to is not None)
    kept = w.store.sends[send_id]
    w.store.sends[send_id] = replace(kept, intent=replace(kept.intent, text="An older prompt."))
    w.rewind(typed)
    try:
        w.poll()
    except ContractRefusal as refusal:
        pytest.fail(f"the poller stopped on a kept prompt: {refusal}")
    assert w.offset() == str(typed["update_id"] + 1) and w.edge.counts["repeat"] == 1
    assert len(w.prompts()) == 1 and "(send.changed)" in (w.edge.last_error or "")


def test_a_refused_typed_reply_gets_no_prompt(telegram, M=edge_module, P=poller_module):
    """Words changed under a held blank reply are refused, so nothing asks how they count."""
    w = World(telegram, M, P)
    _, question = w.ask()
    blank = w.reply(question, " ")
    w.poll()
    w.add({"message": {**copy.deepcopy(blank["message"]), "text": "Yes"}})
    w.poll()
    assert w.refusals() == [(RefusalCode.CHANGED_BODY, "replay.body")]
    assert w.prompts() == []


def test_a_redelivered_update_is_a_repeat_and_nothing_goes_out_twice(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    typed = w.reply(question, "Yes")
    w.poll()
    w.rewind(typed)
    w.poll()
    assert len(w.prompts()) == 1 and w.edge.counts["repeat"] == 1
    press = w.press(w.prompts()[-1]["message_id"], "clar:deferred")
    w.poll()
    w.rewind(press)
    w.poll()
    assert w.held(press)[2].event()["disposition"] == "deferred"
    assert w.edge.counts == {"accepted": 1, "retained": 1, "refused": 0, "repeat": 2}
    assert [ack[1] for ack in telegram.callbacks] == ["Received.", "Received."]


# --- crash points: kept before the offset moves or anything is acknowledged ------------


@pytest.mark.parametrize("fail", ["delivery", "keep_receipt", "save_send", "start_attempt", "record_delivery"])
def test_a_store_error_keeps_the_offset_and_the_update_comes_again(telegram, fail, M=edge_module, P=poller_module):
    """Nothing is acknowledged while a reply or its prompt is not kept; Telegram sends it again,
    and its prompt still goes out at most once."""
    w = World(telegram, M, P)
    _, question = w.ask()
    typed = w.reply(question, "Yes, offline first.")
    w.store.fail = fail
    with pytest.raises(RuntimeError):
        w.poller.poll_once()
    assert w.offset() is None
    w.store.fail = None
    assert w.poll() == 0 and w.offset() == str(typed["update_id"] + 1)
    assert w.held(typed)[1].text == "Yes, offline first." and len(w.prompts()) == 1


def test_a_refusal_that_cannot_be_kept_keeps_the_offset(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    w.reply(question, "Yes", is_bot=True)
    w.store.fail = "keep_refusal"
    with pytest.raises(RuntimeError):
        w.poller.poll_once()
    assert w.offset() is None and not w.store.refused
    w.store.fail = None
    w.poll()
    assert w.refusals() == [(RefusalCode.BOT_SENDER, "provenance.bot")]


def test_a_policy_error_keeps_the_offset(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    typed = w.reply(question, "Yes")
    w.policy.fail = True
    with pytest.raises(RuntimeError):
        w.poller.poll_once()
    assert w.offset() is None and not w.store.held and not w.store.refused
    w.policy.fail = False
    w.poll()
    assert w.held(typed)[2].code == RefusalCode.NO_EXPLICIT_DISPOSITION


def test_a_press_is_acknowledged_only_once_it_is_kept(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    w.reply(question, "Yes")
    w.poll()
    press = w.press(w.prompts()[-1]["message_id"], "clar:answered")
    w.store.fail = "keep_receipt"
    with pytest.raises(RuntimeError):
        w.poller.poll_once()
    assert telegram.callbacks == []
    w.store.fail = None
    w.poll()
    assert telegram.callbacks == [(press["callback_query"]["id"], "Received.", False)]


def test_provider_errors_on_a_prompt_or_an_ack_are_noted_and_the_receipt_stays(telegram, M=edge_module,
                                                                               P=poller_module):
    w = World(telegram, M, P)
    _, question = w.ask()
    telegram.forbidden.add(TG_GROUP)
    typed = w.reply(question, "Yes")
    assert w.poll() == 0 and w.offset() == str(typed["update_id"] + 1)
    assert w.held(typed)[2].code == RefusalCode.NO_EXPLICIT_DISPOSITION
    prompts = [record for record in w.store.sends.values() if record.intent.reply_to is not None]
    assert [record.state for record in prompts] == ["uncertain"]
    assert (w.edge.last_error or "").startswith("send c-")
    telegram.forbidden.clear()
    w.reply(question, "Yes, offline first.")  # a new reply gets its own prompt
    w.poll()
    w.ack_fails = True
    press = w.press(w.prompts()[-1]["message_id"], "clar:answered")
    w.poll()
    assert w.held(press)[2].status == "accepted"
    assert "could not answer a press" in (w.edge.last_error or "")
    assert w.offset() == str(press["update_id"] + 1)


# --- sending the question: intent first, the same identity on every retry -------------


def test_the_question_intent_is_kept_before_it_is_sent(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    w.ask()
    assert [name for name, _ in w.store.log] == ["save_send", "start_attempt", "client.send", "record_delivery"]


def test_send_retries_keep_the_same_presentation(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    presentation = w.presentation()
    w.store.ask(presentation)
    telegram.forbidden.add(TG_GROUP)
    first = w.edge.present(presentation, UNKNOWN, QUESTION)
    assert (first.state, first.send_id) == ("uncertain", presentation.presentation_id)
    assert (first.error or "").startswith("TelegramError")
    telegram.forbidden.clear()
    again = w.edge.present(presentation, UNKNOWN, QUESTION)
    assert again.state == "uncertain" and telegram.sent == []  # never sent again on its own
    retried = w.edge.present(presentation, UNKNOWN, QUESTION, resend=True)
    assert (retried.state, retried.send_id) == ("sent", presentation.presentation_id)
    assert list(w.store.sends) == [presentation.presentation_id]  # one intent: no new question or presentation
    assert w.store.sends[presentation.presentation_id].attempts == 2
    assert w.store.copies(presentation.presentation_id) == {retried.message_id}
    assert w.edge.present(presentation, UNKNOWN, QUESTION, resend=True).state == "delivered"
    assert len(telegram.sent) == 1
    with pytest.raises(ContractRefusal) as refused:
        w.edge.present(presentation, UNKNOWN, QUESTION + " Please answer.")
    assert (refused.value.code, refused.value.guard) == (RefusalCode.CHANGED_BODY, "send.changed")


def test_a_crash_after_the_send_is_surfaced_and_reconciled_for_that_presentation(telegram, M=edge_module,
                                                                                 P=poller_module):
    """No exactly-once claim: the lost copy is shown as uncertain and sent again only on purpose,
    under the same presentation; a reply to the copy whose ID was never kept goes the ordinary way."""
    w = World(telegram, M, P)
    presentation = w.presentation()
    w.store.ask(presentation)
    w.store.fail = "record_delivery"
    with pytest.raises(RuntimeError):
        w.edge.present(presentation, UNKNOWN, QUESTION)
    w.store.fail = None
    lost = telegram.sent[0]["message_id"]
    assert w.edge.present(presentation, UNKNOWN, QUESTION).state == "uncertain" and len(telegram.sent) == 1
    w.reply(lost, "Yes")
    assert w.poll() == 1 and not w.store.held
    retried = w.edge.present(presentation, UNKNOWN, QUESTION, resend=True)
    assert (retried.state, retried.send_id) == ("sent", presentation.presentation_id)
    assert list(w.store.sends) == [presentation.presentation_id]


def test_a_crash_before_the_send_sends_once_on_retry(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    presentation = w.presentation()
    w.store.ask(presentation)
    w.store.fail = "start_attempt"
    with pytest.raises(RuntimeError):
        w.edge.present(presentation, UNKNOWN, QUESTION)
    assert telegram.sent == [] and w.store.sends[presentation.presentation_id].state == "pending"
    w.store.fail = None
    assert w.edge.present(presentation, UNKNOWN, QUESTION).state == "sent" and len(telegram.sent) == 1


def test_an_answered_question_is_not_sent(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    presentation = w.presentation()
    w.store.ask(presentation)
    w.store.done.add((presentation.stream.stream_id, presentation.question_id))
    result = w.edge.present(presentation, UNKNOWN, QUESTION)
    assert (result.state, result.send_id) == ("answered", presentation.presentation_id)
    assert w.store.log == [] and telegram.sent == []


def test_only_the_current_generation_is_sent(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    old = w.presentation(generation=1)
    w.store.ask(w.presentation(generation=2))
    assert w.edge.present(old, UNKNOWN, QUESTION).state == "not_current"
    assert w.store.log == [] and telegram.sent == []


def test_a_presentation_must_match_its_bot_question_and_metadata(telegram, M=edge_module, P=poller_module):
    w = World(telegram, M, P)
    cases = [
        (w.presentation(bot=TransportNamespace("telegram", str(TG_BOT + 1))), UNKNOWN,
         RefusalCode.TRANSPORT_MISMATCH, "present.transport"),
        (w.presentation(), UNKNOWN_2, RefusalCode.BINDING_MISMATCH, "present.question"),
        (w.presentation(metadata=UNKNOWN_2), UNKNOWN, RefusalCode.HASH_MISMATCH, "present.metadata"),
    ]
    for presentation, unknown, code, guard in cases:
        w.store.ask(presentation)
        with pytest.raises(ContractRefusal) as refused:
            w.edge.present(presentation, unknown, QUESTION)
        assert (refused.value.code, refused.value.guard) == (code, guard)
    assert w.store.log == [] and telegram.sent == []


def test_question_text_must_fit_one_message_and_say_something(telegram, M=edge_module, P=poller_module):
    """Telegram counts UTF-16 code units: 2049 emoji are 4098 units, one too many twice over."""
    w = World(telegram, M, P)
    presentation = w.presentation()
    w.store.ask(presentation)
    for text in ["\U0001f642" * (M.TEXT_MAX // 2 + 1), " \u200b\n", "half \ud83d a face", None]:
        with pytest.raises(ContractRefusal) as refused:
            w.edge.present(presentation, UNKNOWN, text)
        assert (refused.value.code, refused.value.guard) == (RefusalCode.MALFORMED, "present.text")
    assert w.store.log == [] and telegram.sent == []
    assert w.edge.present(presentation, UNKNOWN, "\U0001f642" * (M.TEXT_MAX // 2)).state == "sent"


# --- off by default ---------------------------------------------------------------------


def test_off_by_default_and_bound_nowhere_in_the_server():
    assert inspect.signature(poller_module.Poller).parameters["clarifications"].default is None
    assert inspect.signature(TelegramService).parameters["clarifications"].default is None
    builders = []
    for path in sorted(Path(temper_ai.__file__).parent.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "ClarificationEdge" not in source:
            continue  # cannot build one without naming it; parsing every file is too slow
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if name == "ClarificationEdge":
                    builders.append(str(path))
    assert builders == []


def ordinary(w: World) -> list[dict[str, Any]]:
    """Updates the edge must leave alone: none replies to, or presses on, a message it delivered."""
    return [
        w.message("hello", chat=TG_OWNER),
        w.reply(424242, "a reply to an ordinary message", chat=TG_OWNER),
        w.press(424243, "run:synthetic", chat=TG_OWNER),
        w.add({"my_chat_member": {"chat": w.chat(TG_GROUP), "from": w.user(TG_OWNER), "date": int(time.time()),
                                  "old_chat_member": {"status": "left", "user": w.user(TG_BOT, True)},
                                  "new_chat_member": {"status": "member", "user": w.user(TG_BOT, True)}}}),
        w.message("an old message", chat=TG_OWNER, date=int(time.time()) - 3600),
    ]


def test_feature_off_ordinary_updates_go_on_as_before(telegram, M=edge_module, P=poller_module):
    """The edge bound with nothing delivered changes nothing: the same updates are handed on, skipped
    and saved as by a poller without it, and the edge only looks."""
    w = World(telegram, M, P)
    plain_got: list[Any] = []
    plain = P.Poller(telegram, plain_got.append, timeout=0, accept=TelegramService.save,
                     skip=TelegramService.save_skipped)
    assert plain.clarifications is None
    first = ordinary(w)
    handed_without = plain.poll_once()
    second = ordinary(w)
    handed_with = w.poll()
    assert handed_without == handed_with == 4 and plain.skipped == w.poller.skipped == 1
    assert len(plain_got) == len(w.got) == 4 and w.offset() == str(second[-1]["update_id"] + 1)
    for before, after in zip(first, second, strict=True):
        row_before = inbox_store.find("telegram", str(before["update_id"]))
        row_after = inbox_store.find("telegram", str(after["update_id"]))
        assert row_before is not None and row_after is not None
        assert (row_before.kind, row_before.status) == (row_after.kind, row_after.status)
    assert w.store_calls() == ["delivery", "delivery"]
    assert w.edge.counts == dict.fromkeys(("accepted", "retained", "refused", "repeat"), 0)
    assert telegram.callbacks == [] and telegram.sent == []


# --- every guard bites ------------------------------------------------------------------


@dataclass(frozen=True)
class Bite:
    """One guard: the line that holds it, how the bite changes it, and the case that must then fail."""

    name: str
    module: str  # "edge" (clarifications.py) or "poller" (poller.py)
    old: str
    new: str
    case: Callable[..., None]


def _with(test: Callable[..., None], *args: Any) -> Callable[..., None]:
    return lambda telegram, M, P: test(telegram, *args, M, P)


EDGE, POLLER = "edge", "poller"
BITES = [
    Bite("pulled-object", EDGE, "        if not any(update is pulled for pulled in self.updates):",
         "        if False:", test_only_objects_from_the_servers_own_pull_can_be_claimed),
    Bite("batch-token", EDGE, "        if token is not _PULL:", "        if False:",
         test_only_objects_from_the_servers_own_pull_can_be_claimed),
    Bite("pull-client", EDGE, "        if client is not self.client:", "        if False:",
         test_only_objects_from_the_servers_own_pull_can_be_claimed),
    Bite("getme-bot", EDGE, "str(bot_id) if type(bot_id) is int else repr(bot_id)", "str(bot_id)",
         test_the_bot_comes_from_the_providers_getme),
    Bite("update-size", EDGE, "            if body is None or len(body) > UPDATE_MAX:", "            if body is None:",
         test_an_oversized_or_unencodable_update_is_refused_with_its_ingress),
    Bite("ingress-digest", EDGE,
         '        digest = hashlib.sha256(body.encode("ascii")).hexdigest() if body is not None else None',
         "        digest = None", test_clean_path_typed_reply_then_own_press_keeps_the_exact_words),
    Bite("sender-id", EDGE, "    if type(sender_id) is not int or sender_id <= 0:", "    if sender_id is None:",
         test_a_sender_without_a_numeric_id_is_refused),
    Bite("exact-text", EDGE, '            text = body["text"] if "text" in body else ""  # exact, never stripped',
         '            text = (body["text"] if "text" in body else "").strip()',
         test_words_are_kept_exactly_as_typed),
    Bite("text-size", EDGE, "            if type(text) is str and len(text) > TEXT_MAX:", "            if False:",
         test_overlong_words_are_refused_at_the_edge),
    Bite("callback-size", EDGE,
         '            if type(data) is str and len(data.encode("utf-8", "surrogatepass")) > CALLBACK_DATA_MAX:',
         "            if False:", test_overlong_button_data_is_refused),
    Bite("forwarded", EDGE,
         "            forwarded = any(body.get(marker) is not None for marker in COPY_MARKERS)",
         "            forwarded = False", _with(test_forwarded_or_copied_words_are_refused, "forward_origin")),
    Bite("bot-sender", EDGE, 'sender_is_bot=sender.get("is_bot") is not False,', "sender_is_bot=False,",
         test_bot_senders_are_refused_and_a_missing_flag_counts_as_a_bot),
    Bite("bot-fail-closed", EDGE, 'sender_is_bot=sender.get("is_bot") is not False,',
         'sender_is_bot=sender.get("is_bot") is True,', test_bot_senders_are_refused_and_a_missing_flag_counts_as_a_bot),
    Bite("policy-errors-raise", EDGE,
         "        decided = self.policy.decide(\n"
         "            policy_ref=presentation.responder_policy_ref, chat_id=target.chat_id, sender_id=sender_id,\n"
         "        )",
         "        try:\n"
         "            decided = self.policy.decide(\n"
         "                policy_ref=presentation.responder_policy_ref, chat_id=target.chat_id, sender_id=sender_id)\n"
         "        except RuntimeError:\n"
         '            decided = "denied"',
         test_a_policy_error_keeps_the_offset),
    Bite("responder-decision", EDGE,
         'decision="authorised" if type(decided) is str and decided == "authorised" else "denied",',
         'decision="authorised",', test_a_member_without_responder_authority_is_refused),
    Bite("responder-exact", EDGE,
         'decision="authorised" if type(decided) is str and decided == "authorised" else "denied",',
         'decision="authorised" if decided else "denied",', _with(test_only_the_exact_policy_answer_authorises, True)),
    Bite("action-chat", EDGE, "ActionIdentity(namespace, target.chat_id, target.kind,",
         "ActionIdentity(namespace, target.target_chat, target.kind,", test_an_answer_given_in_another_chat_is_refused),
    Bite("action-bot", EDGE, "ActionIdentity(namespace, target.chat_id, target.kind,",
         "ActionIdentity(presentation.transport, target.chat_id, target.kind,",
         test_a_delivery_from_another_bot_is_refused),
    Bite("binding-generation", EDGE, "                generation=presentation.generation,\n",
         "                generation=self.store.current_generation(presentation.stream.stream_id,"
         " presentation.question_id),\n",
         test_a_reply_or_press_for_an_older_generation_stays_unapplied_and_bound_to_it),
    Bite("current-generation", EDGE,
         "            current_generation=self.store.current_generation(presentation.stream.stream_id,"
         " presentation.question_id),",
         "            current_generation=presentation.generation,",
         test_a_reply_or_press_for_an_older_generation_stays_unapplied_and_bound_to_it),
    Bite("known-questions", EDGE, "            question_ids=self.store.question_ids(presentation.stream.stream_id),",
         "            question_ids=frozenset({presentation.question_id}),",
         test_a_reply_to_a_retired_question_is_refused_and_kept_as_a_diagnostic),
    Bite("confirmed-lookup", EDGE,
         "            confirmed=self.store.receipt(confirms.action.key) if confirms is not None else None,",
         "            confirmed=None,", test_clean_path_typed_reply_then_own_press_keeps_the_exact_words),
    Bite("persisted-confirms", EDGE,
         "            confirms = record.intent.confirms  # the persisted prompt says which reply a press confirms",
         "            confirms = None", test_clean_path_typed_reply_then_own_press_keeps_the_exact_words),
    Bite("persisted-payloads", EDGE, "dict(record.intent.payloads).get(data)", "dict(PAYLOADS).get(data)",
         test_a_press_on_the_question_itself_chooses_nothing),
    Bite("exact-data", EDGE, "dict(record.intent.payloads).get(data)",
         "dict(record.intent.payloads).get(data.strip().lower())", test_only_the_exact_button_data_chooses),
    Bite("typed-no-disposition", EDGE, '            action_id = body.get("message_id")\n',
         '            action_id = body.get("message_id")\n'
         '            disposition = "answered" if text == "yes" else None\n',
         test_typed_words_never_choose_how_they_count),
    Bite("refused-no-key", EDGE, '        if validation.status == "refused":', "        if False:",
         test_a_refused_receipt_never_takes_the_action_key),
    Bite("replay-check", EDGE, "                same = check_replay(held, receipt)", "                same = True",
         test_a_changed_body_under_a_held_key_is_refused_and_the_held_words_stay),
    Bite("prompt-only-if-kept", EDGE, '        elif (kept in ("retained", "repeat") and', "        elif (True and",
         test_a_refused_typed_reply_gets_no_prompt),
    Bite("kept-prompt-not-wedged", EDGE,
         "            except ContractRefusal as refusal:  # kept before with other words (an older release): left as kept",
         "            except ZeroDivisionError as refusal:",
         test_a_prompt_kept_with_other_words_is_left_as_kept_and_never_stops_the_poller),
    Bite("prompt-not-blank", EDGE, "\n              and not _blank(receipt.text)):", "):",
         test_a_reply_with_no_words_is_kept_but_never_prompted),
    Bite("ack-after-keep", EDGE, "        kept = self._keep(ingress, receipt, validation)\n",
         '        if target.kind == "callback":\n'
         '            self._answer(receipt.action.action_id, "Received.")\n'
         "        kept = self._keep(ingress, receipt, validation)\n",
         test_a_press_is_acknowledged_only_once_it_is_kept),
    Bite("keep-errors-raise", EDGE, "        kept = self._keep(ingress, receipt, validation)\n",
         "        try:\n"
         "            kept = self._keep(ingress, receipt, validation)\n"
         "        except RuntimeError:\n"
         "            return True\n",
         _with(test_a_store_error_keeps_the_offset_and_the_update_comes_again, "keep_receipt")),
    Bite("ack-says-applied", EDGE,
         '            received = kept in ("accepted", "repeat") and validation.status == "accepted"',
         "            received = True", test_only_the_author_can_confirm_their_words),
    Bite("unbound-ordinary", EDGE, "        if record is None:\n            return False",
         "        if record is None:\n            return True", test_feature_off_ordinary_updates_go_on_as_before),
    Bite("intent-before-send", EDGE, "        return self._send(intent, self._save(intent), resend=resend)",
         "        sent = self._send(intent, SendRecord(intent), resend=resend)\n"
         "        self._save(intent)\n"
         "        return sent",
         test_the_question_intent_is_kept_before_it_is_sent),
    Bite("changed-send", EDGE, "        if record.intent != intent:", "        if False:",
         test_send_retries_keep_the_same_presentation),
    Bite("delivered-once", EDGE, '        if record.message_id is not None:\n            return SendResult("delivered"',
         '        if False:\n            return SendResult("delivered"', test_send_retries_keep_the_same_presentation),
    Bite("uncertain-not-resent", EDGE, "        if record.attempts and not resend:", "        if False:",
         test_send_retries_keep_the_same_presentation),
    Bite("answered-not-sent", EDGE, "        if self.store.answered(stream_id, presentation.question_id):",
         "        if False:", test_an_answered_question_is_not_sent),
    Bite("current-only-sent", EDGE,
         "        if presentation.generation != self.store.current_generation(stream_id, presentation.question_id):",
         "        if False:", test_only_the_current_generation_is_sent),
    Bite("present-bot", EDGE, "        if presentation.transport != self.namespace:", "        if False:",
         test_a_presentation_must_match_its_bot_question_and_metadata),
    Bite("present-question", EDGE,
         "        if question_id(presentation.stream.brief_sha256, unknown) != presentation.question_id:",
         "        if False:", test_a_presentation_must_match_its_bot_question_and_metadata),
    Bite("present-metadata", EDGE, "        if metadata_sha256(unknown) != presentation.metadata_sha256:",
         "        if False:", test_a_presentation_must_match_its_bot_question_and_metadata),
    Bite("present-text-length", EDGE, "units is None or units > TEXT_MAX or _blank(text)",
         "units is None or _blank(text)", test_question_text_must_fit_one_message_and_say_something),
    Bite("present-text-blank", EDGE, "units is None or units > TEXT_MAX or _blank(text)",
         "units is None or units > TEXT_MAX", test_question_text_must_fit_one_message_and_say_something),
    Bite("present-text-utf16", EDGE, "        units = _utf16_units(text) if type(text) is str else None",
         "        units = len(text) if type(text) is str else None",
         test_question_text_must_fit_one_message_and_say_something),
    Bite("pull-through-edge", POLLER,
         "        if self.clarifications is not None:\n            batch = self.clarifications.pull(",
         "        if False:\n            batch = self.clarifications.pull(",
         test_clean_path_typed_reply_then_own_press_keeps_the_exact_words),
    Bite("claimed-not-ordinary", POLLER,
         "                    continue  # a clarification answer, kept before the offset moves",
         "                    pass", test_clean_path_typed_reply_then_own_press_keeps_the_exact_words),
    Bite("offset-after-keep", POLLER, "        saved: list[Any] = []\n",
         "        store.set_state(OFFSET_KEY, str(top))\n        saved: list[Any] = []\n",
         test_clean_path_typed_reply_then_own_press_keeps_the_exact_words),
    Bite("offset-stays-on-error", POLLER,
         "        if failed is None:\n            store.set_state(OFFSET_KEY, str(top))",
         "        if True:\n            store.set_state(OFFSET_KEY, str(top))",
         _with(test_a_store_error_keeps_the_offset_and_the_update_comes_again, "keep_receipt")),
]

# Each refusal the edge raises itself, by its guard label, and the bite that removes it.
LABEL_BITES = {
    "edge.pulled": "pulled-object", "edge.batch": "batch-token", "edge.client": "pull-client",
    "ingress.size": "update-size", "ingress.sender": "sender-id", "ingress.text_size": "text-size",
    "ingress.callback_size": "callback-size", "present.transport": "present-bot",
    "present.question": "present-question", "present.metadata": "present-metadata",
    "present.text": "present-text-length", "send.changed": "changed-send",
}


def _mutant(module: types.ModuleType, old: str, new: str) -> types.ModuleType:
    """An in-memory copy of the module with one line changed; the file is never touched."""
    source = inspect.getsource(module)
    assert source.count(old) == 1, f"a bite's line must be found exactly once: {old!r}"
    name = f"{module.__name__}__bite"
    mutant = types.ModuleType(name)
    mutant.__file__ = module.__file__
    sys.modules[name] = mutant  # dataclasses look their module up while the classes are made
    try:
        exec(compile(source.replace(old, new), f"<bite of {module.__name__}>", "exec"), mutant.__dict__)
    finally:
        del sys.modules[name]
    return mutant


def test_every_refusal_label_in_the_edge_has_a_bite():
    labels = set(re.findall(r'ContractRefusal\(RefusalCode\.\w+, "([a-z_.]+)"', inspect.getsource(edge_module)))
    assert labels == set(LABEL_BITES)
    names = [bite.name for bite in BITES]
    assert len(names) == len(set(names)) and set(LABEL_BITES.values()) <= set(names)


@pytest.mark.parametrize("bite", BITES, ids=[bite.name for bite in BITES])
def test_every_guard_bites(telegram, bite):
    """The guard's case passes on the real module (its own test) and fails once the line is changed."""
    edge, poller = edge_module, poller_module
    if bite.module == EDGE:
        edge = _mutant(edge_module, bite.old, bite.new)
    else:
        poller = _mutant(poller_module, bite.old, bite.new)
    with pytest.raises((AssertionError, pytest.fail.Exception)):  # the case's own check fails, nothing else
        bite.case(telegram, edge, poller)
