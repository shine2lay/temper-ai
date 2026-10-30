"""Clarification answers over Telegram: the one real-human receipt path (M2).

A clarification question goes out as one plain message for a persisted
Presentation (temper_ai/clarifications/contracts.py). A person answers by
replying to that message. The bot then asks, in a reply to their words, how
the reply counts (answered, deferred, unknown) with three buttons; a press by
the same person confirms that one typed message. Nothing is inferred from
the words: a typed reply alone is kept, with no disposition, and applies
nothing.

Only the server's own getUpdates call can lead to a receipt.
ClarificationEdge.pull makes that call and returns a PulledBatch, and
PulledBatch.claim takes only the update objects that call returned. It claims
an update only when it replies to, or presses a button on, a message this
edge delivered for a persisted presentation; everything else goes the
ordinary way, unchanged. Handler.handle, TelegramService.save, inbox rows,
the events replay API and caller-supplied dicts or labels have no route here.

For each claimed update the edge keeps, before the poller moves the offset
and before anything is acknowledged or sent: the ingress record (the bot, the
update ID and a digest of the update exactly as decoded; never names) with
the receipt and M0's verdict on it (validate_receipt). An accepted or
retained receipt holds its action key: an exact replay is a repeat and a
changed body under the same key is refused. A refused receipt is kept as a
diagnostic under its own digest and never takes an action key. Errors from
the store or the responder policy are raised, so the offset stays and
Telegram sends the update again.

The edge only keeps receipts. Applying an accepted answer to the record,
with its revision check, is the store's step (M3), bound by the caller (M4).

Off unless bound: Poller and TelegramService take ``clarifications=None``,
and nothing in the server binds an edge. See docs/clarifications/telegram.md.
"""

from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from temper_ai.clarifications.contracts import (
    ActionIdentity,
    ActionReceipt,
    ConfirmedText,
    ContractRefusal,
    Presentation,
    PresentationBinding,
    ReceiptValidation,
    RefusalCode,
    ResponderDecision,
    TransportNamespace,
    check_replay,
    metadata_sha256,
    question_id,
    receipt_sha256,
    validate_receipt,
)

logger = logging.getLogger(__name__)

TRANSPORT = "telegram"
TEXT_MAX = 4096  # Telegram's limit for one message, in UTF-16 code units
CALLBACK_DATA_MAX = 64  # Telegram's limit for a button's data, in bytes
UPDATE_MAX = 256 * 1024  # one claimed update as canonical ASCII JSON; genuine ones stay well below
PAYLOADS: tuple[tuple[str, str], ...] = (
    ("clar:answered", "answered"),
    ("clar:deferred", "deferred"),
    ("clar:unknown", "unknown"),
)
LABELS = {"answered": "This is my answer", "deferred": "Answer later", "unknown": "I don't know"}
PROMPT_TEXT = "How does your reply count? Only your own press counts, and only for the reply above."
ANSWER_HINT = "Reply to this message"
# Words that are not the sender's own: forwards, automatic forwards from a linked
# channel, messages composed through an inline bot, and messages sent as a chat.
COPY_MARKERS = (
    "forward_origin", "forward_from", "forward_from_chat", "forward_from_message_id", "forward_signature",
    "forward_sender_name", "forward_date", "is_automatic_forward", "via_bot", "sender_chat",
)

_PULL = object()  # only ClarificationEdge.pull can build a PulledBatch


@dataclass(frozen=True, slots=True)
class PulledIngress:
    """Where one claimed update came from: the bot's own getUpdates call. IDs and a digest, never names."""

    transport: TransportNamespace
    update_id: int
    update_sha256: str | None  # SHA-256 of the update's canonical JSON as decoded; None if it has none
    offset: int | None  # the getUpdates offset it came back for


@dataclass(frozen=True, slots=True)
class Refusal:
    """A refused claimed update, kept as a diagnostic. It never holds an action key."""

    ingress: PulledIngress
    code: RefusalCode
    guard: str
    receipt: ActionReceipt | None = None  # None when no receipt could be built
    receipt_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class SendIntent:
    """One message the edge delivers for a presentation, kept before any send.

    The question itself (send_id is the presentation ID) or the prompt that asks
    how one typed reply counts (send_id from that reply's action key). A retry
    reuses it unchanged; a different body under the same ID is refused.
    """

    send_id: str
    presentation: Presentation
    text: str
    reply_to: str | None = None
    payloads: tuple[tuple[str, str], ...] = ()  # (exact button data, disposition) a press may carry
    confirms: ConfirmedText | None = None  # the typed reply a prompt's press confirms


@dataclass(frozen=True, slots=True)
class SendRecord:
    """A kept send intent: attempts started, and the message ID once Telegram returned one."""

    intent: SendIntent
    attempts: int = 0
    message_id: str | None = None

    @property
    def state(self) -> str:
        if self.message_id is not None:
            return "delivered"
        return "uncertain" if self.attempts else "pending"


@dataclass(frozen=True, slots=True)
class SendResult:
    """What one send did: sent, delivered before, uncertain, or skipped (answered, not_current)."""

    state: str
    send_id: str
    message_id: str | None = None
    error: str | None = None


class ResponderPolicy(Protocol):
    """Who may answer under a presentation's responder policy. Injected: no list lives in this module."""

    def decide(self, *, policy_ref: str, chat_id: str, sender_id: str) -> str:
        """Exactly "authorised" lets this sender answer here; any other value denies."""
        ...


class ClarificationStore(Protocol):
    """What the edge needs from durable storage; each call is one transaction.

    Implemented by the clarification store (M3) as bound by the caller (M4); a
    fake in the tests. The current generation and the record's questions come
    from the record, never from what was sent.
    """

    def save_send(self, intent: SendIntent) -> SendRecord:
        """Keep the intent if its send_id is new; return the record held under that ID."""
        ...

    def start_attempt(self, send_id: str) -> SendRecord:
        """Count one more send attempt, before the provider is called."""
        ...

    def record_delivery(self, send_id: str, message_id: str) -> SendRecord:
        """Keep the message ID Telegram returned: from now on it is a copy of the presentation."""
        ...

    def delivery(self, transport: TransportNamespace, chat_id: str, message_id: str) -> SendRecord | None:
        """The send whose delivered message this is, for this bot and chat."""
        ...

    def copies(self, presentation_id: str) -> frozenset[str]:
        """Message IDs delivered for the presentation: the question and its prompts."""
        ...

    def current_generation(self, stream_id: str, question_id: str) -> int:
        ...

    def question_ids(self, stream_id: str) -> frozenset[str]:
        ...

    def answered(self, stream_id: str, question_id: str) -> bool:
        """True when the record already holds an applied answer, so the question is not asked again."""
        ...

    def receipt(self, action_key: str) -> ActionReceipt | None:
        ...

    def keep_receipt(
        self, ingress: PulledIngress, receipt: ActionReceipt, validation: ReceiptValidation,
    ) -> tuple[ActionReceipt, bool]:
        """Keep an accepted or retained receipt under its action key unless one is held.

        Returns the receipt held under the key and whether this call kept it.
        """
        ...

    def keep_refusal(self, refusal: Refusal) -> None:
        ...


@dataclass(frozen=True, slots=True)
class _Target:
    kind: str  # message | callback
    update: dict[str, Any]
    update_id: int
    chat_id: str  # where the action happened
    target_chat: str  # chat of the message replied to or pressed on
    target_id: str  # that message's ID
    body: dict[str, Any]  # the message or the callback query


def _chat(message: Mapping[str, Any]) -> str | None:
    chat = message.get("chat")
    chat_id = chat.get("id") if isinstance(chat, Mapping) else None
    return str(chat_id) if type(chat_id) is int and chat_id != 0 else None


def _positive(value: object) -> str | None:
    return str(value) if type(value) is int and value > 0 else None


def _target(update: object) -> _Target | None:
    """The message an update replies to or presses on, or None when it does neither."""
    if not isinstance(update, dict):
        return None
    update_id = update.get("update_id")
    if type(update_id) is not int or update_id < 0:
        return None
    message = update.get("message")
    if isinstance(message, dict):
        replied = message.get("reply_to_message")
        if not isinstance(replied, dict):
            return None  # not a reply: never bound to whatever was asked last
        chat = _chat(message)
        target_chat = _chat(replied) if "chat" in replied else chat
        target_id = _positive(replied.get("message_id"))
        if chat is None or target_chat is None or target_id is None:
            return None
        return _Target("message", update, update_id, chat, target_chat, target_id, message)
    query = update.get("callback_query")
    if isinstance(query, dict):
        pressed = query.get("message")
        if not isinstance(pressed, dict):
            return None  # an inline-mode button has no chat: never one of ours
        chat = _chat(pressed)
        target_id = _positive(pressed.get("message_id"))
        if chat is None or target_id is None:
            return None
        return _Target("callback", update, update_id, chat, chat, target_id, query)
    return None


def _canonical_update(update: Mapping[str, Any]) -> str | None:
    """The update's canonical JSON as decoded (ASCII, so a lone surrogate still has a form)."""
    try:
        return json.dumps(update, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return None


def _sender_id(body: Mapping[str, Any]) -> str:
    sender = body.get("from")
    sender_id = sender.get("id") if isinstance(sender, dict) else None
    if type(sender_id) is not int or sender_id <= 0:
        raise ContractRefusal(RefusalCode.MALFORMED, "ingress.sender", "from.id")
    return str(sender_id)


def _sha256_text(text: object) -> str:
    """SHA-256 of the text's UTF-8 bytes. Text that is not a string, or has no UTF-8
    form, is refused by the receipt's own shape check before this digest is compared."""
    raw = text.encode("utf-8", "surrogatepass") if type(text) is str else b""
    return hashlib.sha256(raw).hexdigest()


def _blank(text: str) -> bool:
    """M0's blank rule (contracts._blank): only whitespace or invisible format characters."""
    return all(char.isspace() or unicodedata.category(char) == "Cf" for char in text)


def _utf16_units(text: str) -> int | None:
    """Length as Telegram counts it; None for text with no UTF-8 form (a lone surrogate)."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _prompt_id(action: ActionIdentity) -> str:
    return "c-" + hashlib.sha256(f"prompt\n{action.key}".encode()).hexdigest()


def _keyboard(payloads: tuple[tuple[str, str], ...]) -> list[list[dict[str, str]]]:
    return [[{"text": LABELS[disposition], "callback_data": data} for data, disposition in payloads]]


class PulledBatch:
    """The updates one getUpdates call returned. Only these objects can be claimed."""

    def __init__(self, token: object, edge: ClarificationEdge, namespace: TransportNamespace,
                 offset: int | None, updates: list[Any]) -> None:
        if token is not _PULL:
            raise ContractRefusal(RefusalCode.UNVERIFIED_INGRESS, "edge.batch", "PulledBatch")
        self.namespace = namespace
        self.offset = offset
        self.updates = updates
        self._edge = edge

    def claim(self, update: object) -> bool:
        """Keep a clarification action from this pull; False leaves the update to the ordinary path.

        The poller calls it for each update before it moves the offset. A kept
        press is then answered, and a kept typed reply gets its prompt (intent
        kept first); a provider error there is noted, never raised, and a
        repeat never sends a prompt twice. Store and policy errors are raised.
        An object this pull did not return is refused, whatever it holds.
        """
        if not any(update is pulled for pulled in self.updates):
            raise ContractRefusal(RefusalCode.UNVERIFIED_INGRESS, "edge.pulled", "update")
        return self._edge._claim(self, update)


class ClarificationEdge:
    """The Telegram getUpdates edge for clarification answers. See the module docstring."""

    def __init__(self, client: Any, store: ClarificationStore, policy: ResponderPolicy) -> None:
        self.client = client
        self.store = store
        self.policy = policy
        self.counts = {"accepted": 0, "retained": 0, "refused": 0, "repeat": 0}
        self.last_error: str | None = None
        self._namespace: TransportNamespace | None = None

    @property
    def namespace(self) -> TransportNamespace:
        """The bot this edge pulls and sends as, from the provider's own getMe; never configured."""
        if self._namespace is None:
            me = self.client.get_me() or {}
            bot_id = me.get("id")
            self._namespace = TransportNamespace(TRANSPORT, str(bot_id) if type(bot_id) is int else repr(bot_id))
        return self._namespace

    def status(self) -> dict[str, Any]:
        bot = self._namespace.bot_id if self._namespace is not None else None
        return {"bot": bot, **self.counts, "last_error": self.last_error}

    def pull(self, client: Any, offset: int | None, *, timeout: int, allowed: list[str]) -> PulledBatch:
        """The one getUpdates call whose updates may become receipts. client: the poller's own."""
        if client is not self.client:
            raise ContractRefusal(RefusalCode.TRANSPORT_MISMATCH, "edge.client", "client")
        namespace = self.namespace
        updates = self.client.get_updates(offset, timeout=timeout, allowed=allowed)
        return PulledBatch(_PULL, self, namespace, offset, list(updates or []))

    # --- receiving ----------------------------------------------------------------

    def _claim(self, batch: PulledBatch, update: object) -> bool:
        target = _target(update)
        if target is None:
            return False
        record = self.store.delivery(batch.namespace, target.target_chat, target.target_id)
        if record is None:
            return False
        body = _canonical_update(target.update)
        digest = hashlib.sha256(body.encode("ascii")).hexdigest() if body is not None else None
        ingress = PulledIngress(batch.namespace, target.update_id, digest, batch.offset)
        presentation = record.intent.presentation
        try:
            if body is None or len(body) > UPDATE_MAX:
                raise ContractRefusal(RefusalCode.MALFORMED, "ingress.size", "update")
            sender_id = _sender_id(target.body)
        except ContractRefusal as refusal:
            self._refuse(Refusal(ingress, refusal.code, refusal.guard))
            return True
        decided = self.policy.decide(
            policy_ref=presentation.responder_policy_ref, chat_id=target.chat_id, sender_id=sender_id,
        )
        responder = ResponderDecision(
            policy_ref=presentation.responder_policy_ref,
            sender_id=sender_id,
            decision="authorised" if type(decided) is str and decided == "authorised" else "denied",
            basis="responder_policy",
        )
        try:
            receipt = self._receipt(batch.namespace, target, record, sender_id, responder)
        except ContractRefusal as refusal:
            self._refuse(Refusal(ingress, refusal.code, refusal.guard))
            return True
        confirms = receipt.confirms
        validation = validate_receipt(
            receipt,
            presentation=presentation,
            copies=self.store.copies(presentation.presentation_id),
            current_generation=self.store.current_generation(presentation.stream.stream_id, presentation.question_id),
            question_ids=self.store.question_ids(presentation.stream.stream_id),
            confirmed=self.store.receipt(confirms.action.key) if confirms is not None else None,
        )
        kept = self._keep(ingress, receipt, validation)
        if target.kind == "callback":
            received = kept in ("accepted", "repeat") and validation.status == "accepted"
            self._answer(receipt.action.action_id, "Received." if received else "Not applied.")
        elif (kept in ("retained", "repeat") and validation.code == RefusalCode.NO_EXPLICIT_DISPOSITION
              and not _blank(receipt.text)):
            intent = SendIntent(
                send_id=_prompt_id(receipt.action),
                presentation=presentation,
                text=PROMPT_TEXT,
                reply_to=receipt.action.action_id,
                payloads=PAYLOADS,
                confirms=ConfirmedText(receipt.action, receipt.sender_id, receipt.text_sha256),
            )
            try:
                self._send(intent, self._save(intent), resend=False)  # a repeat finds it kept: never sent twice
            except ContractRefusal as refusal:  # kept before with other words (an older release): left as kept
                self._note(f"prompt {intent.send_id[:14]} not sent ({refusal.guard})")
        return True

    def _receipt(self, namespace: TransportNamespace, target: _Target, record: SendRecord, sender_id: str,
                 responder: ResponderDecision) -> ActionReceipt:
        """The receipt exactly as pulled. Raises ContractRefusal when the update cannot be one."""
        body = target.body
        presentation = record.intent.presentation
        text: Any = ""
        data: Any = None
        disposition: str | None = None
        confirms: ConfirmedText | None = None
        action_id: Any
        if target.kind == "message":
            text = body["text"] if "text" in body else ""  # exact, never stripped
            if type(text) is str and len(text) > TEXT_MAX:
                raise ContractRefusal(RefusalCode.MALFORMED, "ingress.text_size", "message.text")
            action_id = body.get("message_id")
            forwarded = any(body.get(marker) is not None for marker in COPY_MARKERS)
        else:
            data = body["data"] if "data" in body else ""  # exact provider payload, kept as evidence
            if type(data) is str and len(data.encode("utf-8", "surrogatepass")) > CALLBACK_DATA_MAX:
                raise ContractRefusal(RefusalCode.MALFORMED, "ingress.callback_size", "callback_query.data")
            confirms = record.intent.confirms  # the persisted prompt says which reply a press confirms
            if type(data) is str:
                disposition = dict(record.intent.payloads).get(data)  # exact data only, never inferred
            action_id = body.get("id")
            forwarded = False
        sender = cast(dict[str, Any], body["from"])
        return ActionReceipt(
            ingress="provider_pull",
            action=ActionIdentity(namespace, target.chat_id, target.kind,
                                  str(action_id) if type(action_id) is int else action_id),
            update_id=target.update_id,
            sender_id=sender_id,
            sender_is_bot=sender.get("is_bot") is not False,  # missing counts as a bot: fail closed
            forwarded=forwarded,
            text=text,
            text_sha256=_sha256_text(text),
            binding=PresentationBinding(
                stream_id=presentation.stream.stream_id,
                question_id=presentation.question_id,
                presentation_id=presentation.presentation_id,
                generation=presentation.generation,
                message_id=target.target_id,
            ),
            responder=responder,
            intent="answer",
            disposition=disposition,
            callback_data=data,
            confirms=confirms,
        )

    def _keep(self, ingress: PulledIngress, receipt: ActionReceipt, validation: ReceiptValidation) -> str:
        """Keep one judged receipt; returns accepted, retained, refused or repeat."""
        if validation.status == "refused":
            code, guard = cast(RefusalCode, validation.code), cast(str, validation.guard)
            self._refuse(Refusal(ingress, code, guard, receipt, validation.receipt_sha256))
            return "refused"
        held, new = self.store.keep_receipt(ingress, receipt, validation)
        if not new:
            try:
                same = check_replay(held, receipt)
            except ContractRefusal as refusal:
                self._refuse(Refusal(ingress, refusal.code, refusal.guard, receipt, receipt_sha256(receipt)))
                return "refused"
            if not same:
                raise RuntimeError("the store returned a receipt held under another action key")
            self.counts["repeat"] += 1
            return "repeat"
        verdict = validation.status  # a counter key read first: this edge writes no run row's status
        self.counts[verdict] += 1
        logger.info("Telegram clarification: %s receipt %s (%s)", verdict, validation.receipt_sha256[:12],
                    validation.code or "event " + str(validation.event_id))
        return verdict

    def _refuse(self, refusal: Refusal) -> None:
        self.store.keep_refusal(refusal)
        self.counts["refused"] += 1
        logger.info("Telegram clarification: refused update %s (%s [%s])", refusal.ingress.update_id,
                    refusal.code, refusal.guard)

    def _answer(self, callback_id: str, text: str) -> None:
        try:
            self.client.answer_callback(callback_id, text)
        except Exception as exc:  # noqa: BLE001 - only the little notice is lost; the receipt is kept
            self._note(f"could not answer a press: {type(exc).__name__}: {exc}")

    def _note(self, error: str) -> None:
        self.last_error = error
        logger.warning("Telegram clarification: %s", error)

    # --- sending -----------------------------------------------------------------

    def present(self, presentation: Presentation, unknown: Mapping[str, object], text: str, *,
                resend: bool = False) -> SendResult:
        """Send one question for its persisted presentation, keeping the intent first.

        The same presentation keeps its ID on every retry: no new question or
        presentation is ever made here. An answered question or a generation that
        is not current is not sent. An earlier attempt with no recorded message is
        "uncertain" and is sent again only with resend=True, once someone has
        checked the chat: there is no exactly-once claim.
        """
        if presentation.transport != self.namespace:
            raise ContractRefusal(RefusalCode.TRANSPORT_MISMATCH, "present.transport", "presentation.transport")
        if question_id(presentation.stream.brief_sha256, unknown) != presentation.question_id:
            raise ContractRefusal(RefusalCode.BINDING_MISMATCH, "present.question", "presentation.question_id")
        if metadata_sha256(unknown) != presentation.metadata_sha256:
            raise ContractRefusal(RefusalCode.HASH_MISMATCH, "present.metadata", "presentation.metadata_sha256")
        units = _utf16_units(text) if type(text) is str else None
        if units is None or units > TEXT_MAX or _blank(text):
            raise ContractRefusal(RefusalCode.MALFORMED, "present.text", "text")
        stream_id = presentation.stream.stream_id
        if self.store.answered(stream_id, presentation.question_id):
            return SendResult("answered", presentation.presentation_id)
        if presentation.generation != self.store.current_generation(stream_id, presentation.question_id):
            return SendResult("not_current", presentation.presentation_id)
        intent = SendIntent(send_id=presentation.presentation_id, presentation=presentation, text=text)
        return self._send(intent, self._save(intent), resend=resend)

    def _save(self, intent: SendIntent) -> SendRecord:
        record = self.store.save_send(intent)
        if record.intent != intent:
            raise ContractRefusal(RefusalCode.CHANGED_BODY, "send.changed", "send.intent")
        return record

    def _send(self, intent: SendIntent, record: SendRecord, *, resend: bool) -> SendResult:
        if record.message_id is not None:
            return SendResult("delivered", intent.send_id, record.message_id)
        if record.attempts and not resend:
            return SendResult("uncertain", intent.send_id)
        self.store.start_attempt(intent.send_id)
        try:
            sent = self.client.send(
                int(intent.presentation.chat_id), intent.text,
                reply_to=int(intent.reply_to) if intent.reply_to is not None else None,
                keyboard=_keyboard(intent.payloads) if intent.payloads else None,
                force_reply=None if intent.payloads else ANSWER_HINT,
                html=False,
            )
        except Exception as exc:  # noqa: BLE001 - it may or may not have arrived: shown, never guessed
            error = f"{type(exc).__name__}: {exc}"
            self._note(f"send {intent.send_id[:14]} uncertain: {error}")
            return SendResult("uncertain", intent.send_id, error=error)
        message_id = _positive((sent or {}).get("message_id"))
        if message_id is None:
            return SendResult("uncertain", intent.send_id, error="Telegram returned no message ID")
        self.store.record_delivery(intent.send_id, message_id)
        return SendResult("sent", intent.send_id, message_id)
