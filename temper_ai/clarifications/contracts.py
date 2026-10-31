"""Frozen M0 contracts for the clarification loop (Temper #204).

The one typed boundary that the requirements caller (M1), the Telegram receipt
adapter (M2) and the clarification store (M3) share. Pure and deterministic:
standard library only, no temper_ai import, and no file, environment, clock,
network, subprocess or database access, so a configs/ script may load this file
by path. Nothing here opens a reference.

It checks shape, binding and consistency. It authenticates nobody: a receipt is
only as true as the provider-pull ingress that built it (M2, under Security's
review). Every refusal is a ContractRefusal with one closed RefusalCode and the
label of the guard that fired. See docs/clarifications/contract.md.

Attribution is not authority. An event's actor.ref, an authorised
ResponderDecision and source_authority_ref record who answered, under which
responder policy, and under which authority the answer is kept. None of them is
authentication beyond the provider-pull ingress, owner consent, a requirement or
plan approval, an execution, spending or release approval, permission to resume
work, or permission to use a source. An accepted answer answers its one question
and authorises nothing else.
"""

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Callable, Collection, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, cast

__all__ = [
    "ACTION_KINDS",
    "APPEND_STATUSES",
    "CONTRACT",
    "DISPOSITIONS",
    "FOUNDATION_CONTRACT",
    "INGRESSES",
    "INTENTS",
    "MODEL_INGRESS",
    "PROFILE_CONTRACT",
    "RECEIPT_REF_SCHEME",
    "REFUSED_CODES",
    "RESPONDER_BASES",
    "RESPONDER_DECISIONS",
    "RETAINED_CODES",
    "TRANSPORTS",
    "UNVERIFIED_INGRESSES",
    "VALIDATION_STATUSES",
    "VERIFIED_INGRESS",
    "ActionIdentity",
    "ActionReceipt",
    "AppendResult",
    "CallerInput",
    "ConfirmedText",
    "ContractRefusal",
    "Presentation",
    "PresentationBinding",
    "ReceiptValidation",
    "RefusalCode",
    "ResponderDecision",
    "StreamKey",
    "TransportNamespace",
    "check_confirmation_precondition",
    "check_correction_precondition",
    "check_expected_revision",
    "check_reopen_precondition",
    "check_replay",
    "consumption_id",
    "event_id",
    "metadata_sha256",
    "question_id",
    "receipt_from_json",
    "receipt_json",
    "receipt_sha256",
    "validate_receipt",
]

CONTRACT = "temper_clarification_loop/v1"
FOUNDATION_CONTRACT = "context_profile_clarifications/v1"
PROFILE_CONTRACT = "context_profile/v2"
RECEIPT_REF_SCHEME = "clarification-receipt"

TRANSPORTS = ("telegram",)
VERIFIED_INGRESS = "provider_pull"
# Ways a "human" answer can reach the server without the provider vouching for
# the sender. Representable so a refusal can be kept; never accepted.
UNVERIFIED_INGRESSES = ("caller_label", "service_credential", "browser_hint", "inbox_row", "handler_dict")
MODEL_INGRESS = "model_output"
INGRESSES = (VERIFIED_INGRESS, *UNVERIFIED_INGRESSES, MODEL_INGRESS)
ACTION_KINDS = ("message", "callback")
INTENTS = ("answer", "correct", "reopen")
DISPOSITIONS = ("answered", "deferred", "unknown")
RESPONDER_DECISIONS = ("authorised", "denied")
# Membership of an allowed chat alone is never authority for this context.
RESPONDER_BASES = ("responder_policy", "chat_membership")
VALIDATION_STATUSES = ("accepted", "retained", "refused")
APPEND_STATUSES = ("applied", "retained", "refused")

_HEX64 = re.compile(r"[0-9a-f]{64}")
_STREAM_ID = re.compile(r"s-[0-9a-f]{64}")
_QUESTION_ID = re.compile(r"q-[0-9a-f]{64}")
_PRESENTATION_ID = re.compile(r"p-[0-9a-f]{64}")
_ACTION_KEY = re.compile(r"a-[0-9a-f]{64}")
# The #308 foundation's own event-ID and reference patterns, unchanged.
_EVENT_ID = re.compile(r"e-[A-Za-z0-9][A-Za-z0-9._:-]*")
_REF = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:[^\s\x00-\x20\x7f]+")
_OPAQUE_ID = re.compile(r"[A-Za-z0-9_.:-]+")  # a callback query ID: opaque by the provider's design
# Telegram, the only transport (TRANSPORTS), gives user, bot and message IDs as positive
# integers and chat IDs as signed ones. Their canonical decimal form keeps a username or a
# bot token (<digits>:<secret>) out of every ID. A second transport moves these per transport.
_TELEGRAM_ID = re.compile(r"[1-9][0-9]*")
_TELEGRAM_CHAT_ID = re.compile(r"-?[1-9][0-9]*")
# The actor.ref _actor_ref builds from an authenticated Telegram sender (Architecture S9).
_ACTOR_REF = re.compile(r"telegram-user:[1-9][0-9]*")
# What a person sees next to a question ("2", "#2", "Q2", "question 2."):
# a display position, never the question's identity.
_ORDINAL = re.compile(r"(?:#|q-?|question[ #-]?)?[0-9]+[.):]?", re.IGNORECASE)


class RefusalCode(StrEnum):
    """Closed codes. Adding, removing or renaming one is a contract change."""

    MALFORMED = "malformed"
    MISSING_ORIGINAL = "missing_original"
    MISSING_RECORD = "missing_record"
    MISSING_AUTHORITY = "missing_authority"
    MISSING_BINDING = "missing_binding"
    HASH_MISMATCH = "hash_mismatch"
    CROSS_CONTEXT = "cross_context"
    ORDINAL_AS_QUESTION_ID = "ordinal_as_question_id"
    UNKNOWN_QUESTION = "unknown_question"
    BINDING_MISMATCH = "binding_mismatch"
    TRANSPORT_MISMATCH = "transport_mismatch"
    UNVERIFIED_INGRESS = "unverified_ingress"
    MODEL_NOT_HUMAN = "model_not_human"
    BOT_SENDER = "bot_sender"
    FORWARDED_MESSAGE = "forwarded_message"
    RESPONDER_NOT_AUTHORISED = "responder_not_authorised"
    CONFIRMER_NOT_AUTHOR = "confirmer_not_author"
    CHANGED_BODY = "changed_body"
    REVISION_CONFLICT = "revision_conflict"
    # Retained: a well-formed receipt is kept as evidence, but nothing is applied.
    NO_EXPLICIT_DISPOSITION = "no_explicit_disposition"
    BLANK_TEXT = "blank_text"
    STALE_PRESENTATION = "stale_presentation"
    STALE_REOPEN = "stale_reopen"
    CROSS_ACTOR_CORRECTION = "cross_actor_correction"
    ALREADY_CONFIRMED = "already_confirmed"


RETAINED_CODES = frozenset({
    RefusalCode.NO_EXPLICIT_DISPOSITION,
    RefusalCode.BLANK_TEXT,
    RefusalCode.STALE_PRESENTATION,
    RefusalCode.STALE_REOPEN,
    RefusalCode.CROSS_ACTOR_CORRECTION,
    RefusalCode.ALREADY_CONFIRMED,
})
REFUSED_CODES = frozenset(RefusalCode) - RETAINED_CODES


class ContractRefusal(ValueError):
    """A closed, repairable refusal. Nothing was built, changed or replaced."""

    def __init__(self, code: RefusalCode, guard: str, where: str = "") -> None:
        super().__init__(f"{code.value} [{guard}] {where}".rstrip())
        self.code = code
        self.guard = guard
        self.where = where


def _refuse_unless(ok: bool, code: RefusalCode, guard: str, where: str = "") -> None:
    """The one guard primitive. Each call site has its own literal guard label."""
    if not ok:
        raise ContractRefusal(code, guard, where)


# --- shapes -----------------------------------------------------------------


def _instance(value: object, kind: type, where: str) -> None:
    # Exact type: a subclass could carry extra state past the closed shape.
    _refuse_unless(type(value) is kind, RefusalCode.MALFORMED, "shape.instance", where)


def _text(value: object, where: str) -> str:
    """Exact text: any string that encodes as UTF-8, blank or not, never normalised."""
    _refuse_unless(type(value) is str, RefusalCode.MALFORMED, "shape.text", where)
    try:
        cast(str, value).encode("utf-8")
        encodable = True
    except UnicodeEncodeError:
        encodable = False
    _refuse_unless(encodable, RefusalCode.MALFORMED, "shape.utf8", where)
    return cast(str, value)


def _blank(text: str) -> bool:
    """Blank: every character is whitespace or an invisible format character (Unicode Cf).

    The #308 foundation's rule: a lone U+200B is blank, "a" + U+200B is not.
    """
    return all(char.isspace() or unicodedata.category(char) == "Cf" for char in text)


def _nonblank(value: object, where: str) -> str:
    text = _text(value, where)
    _refuse_unless(not _blank(text), RefusalCode.MALFORMED, "shape.nonblank", where)
    return text


def _match(value: object, pattern: re.Pattern[str], where: str) -> str:
    _refuse_unless(
        type(value) is str and pattern.fullmatch(cast(str, value)) is not None,
        RefusalCode.MALFORMED, "shape.pattern", where,
    )
    return cast(str, value)


def _opaque(value: object, where: str) -> str:
    return _match(value, _OPAQUE_ID, where)


def _telegram_id(value: object, where: str) -> str:
    """A Telegram user, bot or message ID: a positive integer in canonical decimal form."""
    return _match(value, _TELEGRAM_ID, where)


def _telegram_chat_id(value: object, where: str) -> str:
    """A Telegram chat ID: a signed integer in canonical decimal form."""
    return _match(value, _TELEGRAM_CHAT_ID, where)


def _event_ref(value: object, where: str) -> str:
    return _match(value, _EVENT_ID, where)


def _action_ref(value: object, where: str) -> str:
    return _match(value, _ACTION_KEY, where)


def _actor_refs(value: object, where: str) -> dict[str, str]:
    """Event ID -> actor.ref, as the store read them from the record.

    Each ref has the shape _actor_ref builds: a display name or another namespace is a
    store fault, refused, never taken for somebody else.
    """
    _refuse_unless(isinstance(value, Mapping), RefusalCode.MALFORMED, "shape.mapping", where)
    return {_event_ref(key, where): _match(ref, _ACTOR_REF, where) for key, ref in cast(Mapping, value).items()}


def _question_ref(value: object, where: str) -> str:
    """A full q- ID. A displayed ordinal is refused with its own code."""
    ordinal = type(value) is int or (
        type(value) is str
        and _QUESTION_ID.fullmatch(cast(str, value)) is None
        and _ORDINAL.fullmatch(cast(str, value)) is not None
    )
    _refuse_unless(not ordinal, RefusalCode.ORDINAL_AS_QUESTION_ID, "question.ordinal", where)
    return _match(value, _QUESTION_ID, where)


def _member(value: object, allowed: tuple[str, ...], where: str) -> str:
    _refuse_unless(type(value) is str and value in allowed, RefusalCode.MALFORMED, "shape.member", where)
    return cast(str, value)


def _integer(value: object, minimum: int, where: str) -> int:
    _refuse_unless(
        type(value) is int and cast(int, value) >= minimum, RefusalCode.MALFORMED, "shape.integer", where,
    )
    return cast(int, value)


def _flag(value: object, where: str) -> bool:
    _refuse_unless(type(value) is bool, RefusalCode.MALFORMED, "shape.flag", where)
    return cast(bool, value)


def _code(value: object, where: str) -> None:
    _refuse_unless(value is None or type(value) is RefusalCode, RefusalCode.MALFORMED, "shape.code", where)


def _string_tuple(value: object, item: Callable[[object, str], str], where: str) -> tuple[str, ...]:
    _refuse_unless(type(value) is tuple, RefusalCode.MALFORMED, "shape.tuple", where)
    items = tuple(item(entry, where) for entry in cast(tuple, value))
    _refuse_unless(len(set(items)) == len(items), RefusalCode.MALFORMED, "shape.unique", where)
    return items


def _string_set(value: object, item: Callable[[object, str], str], where: str) -> frozenset[str]:
    _refuse_unless(
        isinstance(value, Collection) and not isinstance(value, str | bytes),
        RefusalCode.MALFORMED, "shape.collection", where,
    )
    return frozenset(item(entry, where) for entry in cast(Collection[object], value))


def _closed(value: object, keys: frozenset[str], where: str) -> dict[str, Any]:
    _refuse_unless(
        type(value) is dict and set(cast(dict, value)) == keys, RefusalCode.MALFORMED, "shape.closed", where,
    )
    return cast(dict, value)


def _listed(value: object, where: str) -> tuple[Any, ...]:
    _refuse_unless(type(value) is list, RefusalCode.MALFORMED, "shape.list", where)
    return tuple(cast(list, value))


# --- JSON and digests -------------------------------------------------------


def _canonical(value: object) -> str:
    """The #308 foundation's canonical JSON: sorted keys, compact, Unicode kept.

    What json.dumps cannot encode within Python's own limits (an int past the
    int-to-string digit limit, nesting past the recursion limit) is refused as
    malformed, never raised as another error. No size limit of this module's own.
    """
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        encoded = True
    except (ValueError, RecursionError):
        text, encoded = "", False
    _refuse_unless(encoded, RefusalCode.MALFORMED, "json.encode", "canonical")
    return text


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest(identity: str, body: Mapping[str, object]) -> str:
    # The identity name separates the domains: no two kinds of ID can collide.
    return _sha256(_canonical({"contract": CONTRACT, "identity": identity, "body": body}))


def _plain_json(value: object, where: str, ancestors: frozenset[int] | None = None) -> None:
    """Only finite, acyclic, UTF-8 JSON data: what canonical hashing can bind exactly."""
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        _refuse_unless(math.isfinite(cast(float, value)), RefusalCode.MALFORMED, "json.finite", where)
        return
    if type(value) is str:
        _text(value, where)
        return
    _refuse_unless(type(value) in (dict, list), RefusalCode.MALFORMED, "json.type", where)
    seen = ancestors or frozenset()
    _refuse_unless(id(value) not in seen, RefusalCode.MALFORMED, "json.cycle", where)
    inner = seen | {id(value)}
    if type(value) is dict:
        for key, item in cast(dict, value).items():
            _refuse_unless(type(key) is str, RefusalCode.MALFORMED, "json.key", where)
            _text(key, where)
            _plain_json(item, where, inner)
    else:
        for item in cast(list, value):
            _plain_json(item, where, inner)


def _json_object(value: object, where: str) -> dict[str, Any]:
    _refuse_unless(type(value) is dict, RefusalCode.MALFORMED, "json.object", where)
    try:
        _plain_json(value, where)
        walked = True
    except RecursionError:  # nesting past Python's own recursion limit
        walked = False
    _refuse_unless(walked, RefusalCode.MALFORMED, "json.data_depth", where)
    return cast(dict, value)


def _parse_object(text: object, where: str) -> dict[str, Any]:
    """Strict JSON: one object, no duplicate keys, no NaN or Infinity, valid UTF-8."""
    source = _text(text, where)
    duplicates: list[str] = []
    constants: list[str] = []

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        keys: set[str] = set()
        for key, _ in items:
            if key in keys:
                duplicates.append(key)
            keys.add(key)
        return dict(items)

    try:
        value: object = json.loads(source, object_pairs_hook=pairs, parse_constant=constants.append)
        failure = ""
    except RecursionError:  # nesting past the decoder's own recursion limit
        value, failure = None, "depth"
    except ValueError:
        value, failure = None, "syntax"
    _refuse_unless(failure != "depth", RefusalCode.MALFORMED, "json.decode_depth", where)
    _refuse_unless(failure == "", RefusalCode.MALFORMED, "json.syntax", where)
    _refuse_unless(not duplicates, RefusalCode.MALFORMED, "json.duplicate_key", where)
    _refuse_unless(not constants, RefusalCode.MALFORMED, "json.constant", where)
    return _json_object(value, where)


# --- identities ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StreamKey:
    """Record identity: one history per authority namespace and exact original brief."""

    namespace: str
    brief_sha256: str

    def __post_init__(self) -> None:
        _match(self.namespace, _REF, "stream.namespace")
        _match(self.brief_sha256, _HEX64, "stream.brief_sha256")

    @property
    def stream_id(self) -> str:
        """s- digest of namespace and brief hash: the store's unique stream key."""
        return "s-" + _digest("stream", {"namespace": self.namespace, "brief_sha256": self.brief_sha256})


@dataclass(frozen=True, slots=True)
class TransportNamespace:
    """Which provider, and which bot or service identity pulled the action from it."""

    transport: str
    bot_id: str

    def __post_init__(self) -> None:
        _member(self.transport, TRANSPORTS, "transport.transport")
        _telegram_id(self.bot_id, "transport.bot_id")  # the bot's numeric ID (getMe), never its token


@dataclass(frozen=True, slots=True)
class ActionIdentity:
    """Immutable transport/action identity. Its key is the store's unique receipt key."""

    transport: TransportNamespace
    chat_id: str
    kind: str
    action_id: str  # a message ID (numeric, unique per chat) or a callback query ID (opaque)

    def __post_init__(self) -> None:
        _instance(self.transport, TransportNamespace, "action.transport")
        _telegram_chat_id(self.chat_id, "action.chat_id")
        _member(self.kind, ACTION_KINDS, "action.kind")
        if self.kind == "message":
            _telegram_id(self.action_id, "action.action_id")
        else:
            _opaque(self.action_id, "action.callback_query_id")

    @property
    def key(self) -> str:
        """a- digest of the action identity alone: never text, time or retry count."""
        return "a-" + _digest("action", asdict(self))


@dataclass(frozen=True, slots=True)
class Presentation:
    """Server-owned binding of one question to its responder policy and chat.

    Persisted before sending and reused across retries. Delivered message
    copies are recorded apart from it; a displayed ordinal is never its ID.
    """

    stream: StreamKey
    question_id: str
    metadata_sha256: str
    generation: int
    responder_policy_ref: str
    transport: TransportNamespace
    chat_id: str

    def __post_init__(self) -> None:
        _instance(self.stream, StreamKey, "presentation.stream")
        _question_ref(self.question_id, "presentation.question_id")
        _match(self.metadata_sha256, _HEX64, "presentation.metadata_sha256")
        _integer(self.generation, 1, "presentation.generation")
        _match(self.responder_policy_ref, _REF, "presentation.responder_policy_ref")
        _instance(self.transport, TransportNamespace, "presentation.transport")
        _telegram_chat_id(self.chat_id, "presentation.chat_id")

    @property
    def presentation_id(self) -> str:
        return "p-" + _digest("presentation", {
            "stream_id": self.stream.stream_id,
            "question_id": self.question_id,
            "metadata_sha256": self.metadata_sha256,
            "generation": self.generation,
            "responder_policy_ref": self.responder_policy_ref,
            "transport": asdict(self.transport),
            "chat_id": self.chat_id,
        })


@dataclass(frozen=True, slots=True)
class PresentationBinding:
    """What an action answered: the delivered presentation copy it replied to or was pressed on."""

    stream_id: str
    question_id: str
    presentation_id: str
    generation: int
    message_id: str

    def __post_init__(self) -> None:
        _match(self.stream_id, _STREAM_ID, "binding.stream_id")
        _question_ref(self.question_id, "binding.question_id")
        _match(self.presentation_id, _PRESENTATION_ID, "binding.presentation_id")
        _integer(self.generation, 1, "binding.generation")
        _telegram_id(self.message_id, "binding.message_id")


@dataclass(frozen=True, slots=True)
class ResponderDecision:
    """The ingress's decision that this sender may answer, kept apart from display names; nothing more."""

    policy_ref: str
    sender_id: str
    decision: str
    basis: str

    def __post_init__(self) -> None:
        _match(self.policy_ref, _REF, "responder.policy_ref")
        _telegram_id(self.sender_id, "responder.sender_id")  # from.id, never a username
        _member(self.decision, RESPONDER_DECISIONS, "responder.decision")
        _member(self.basis, RESPONDER_BASES, "responder.basis")


@dataclass(frozen=True, slots=True)
class ConfirmedText:
    """A callback's link to the earlier typed message whose exact text it confirms."""

    action: ActionIdentity
    author_id: str
    text_sha256: str

    def __post_init__(self) -> None:
        _instance(self.action, ActionIdentity, "confirms.action")
        _refuse_unless(self.action.kind == "message", RefusalCode.MALFORMED, "confirms.kind", "confirms.action.kind")
        _telegram_id(self.author_id, "confirms.author_id")
        _match(self.text_sha256, _HEX64, "confirms.text_sha256")


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    """One person's transport action exactly as the ingress received it.

    Its canonical JSON (receipt_json) is the immutable sidecar a foundation
    event's source.ref points to. Text is exact: never stripped or reformatted.
    """

    ingress: str
    action: ActionIdentity
    update_id: int
    sender_id: str
    sender_is_bot: bool
    forwarded: bool
    text: str
    text_sha256: str
    binding: PresentationBinding
    responder: ResponderDecision
    intent: str
    disposition: str | None = None
    callback_data: str | None = None  # a callback's exact provider payload, kept as evidence
    supersedes: tuple[str, ...] = ()
    reason: str | None = None
    confirms: ConfirmedText | None = None
    seen_revision: int | None = None
    seen_active_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _member(self.ingress, INGRESSES, "receipt.ingress")
        _instance(self.action, ActionIdentity, "receipt.action")
        _integer(self.update_id, 0, "receipt.update_id")
        _telegram_id(self.sender_id, "receipt.sender_id")
        _flag(self.sender_is_bot, "receipt.sender_is_bot")
        _flag(self.forwarded, "receipt.forwarded")
        text = _text(self.text, "receipt.text")
        _match(self.text_sha256, _HEX64, "receipt.text_sha256")
        _refuse_unless(
            _sha256(text) == self.text_sha256, RefusalCode.HASH_MISMATCH, "receipt.text_sha256", "receipt.text_sha256",
        )
        _instance(self.binding, PresentationBinding, "receipt.binding")
        _instance(self.responder, ResponderDecision, "receipt.responder")
        _member(self.intent, INTENTS, "receipt.intent")
        if self.disposition is not None:
            _member(self.disposition, DISPOSITIONS, "receipt.disposition")
        if self.callback_data is not None:
            _text(self.callback_data, "receipt.callback_data")
        _string_tuple(self.supersedes, _event_ref, "receipt.supersedes")
        if self.reason is not None:
            _nonblank(self.reason, "receipt.reason")
        if self.confirms is not None:
            _instance(self.confirms, ConfirmedText, "receipt.confirms")
        if self.seen_revision is not None:
            _integer(self.seen_revision, 0, "receipt.seen_revision")
        _string_tuple(self.seen_active_event_ids, _event_ref, "receipt.seen_active_event_ids")
        kind, intent = self.action.kind, self.intent
        _refuse_unless(kind == "message" or text == "", RefusalCode.MALFORMED, "receipt.callback_text", "receipt.text")
        _refuse_unless(
            (kind == "callback") == (self.callback_data is not None), RefusalCode.MALFORMED, "receipt.callback_payload",
            "receipt.callback_data",
        )
        _refuse_unless(
            self.confirms is None or kind == "callback", RefusalCode.MALFORMED, "receipt.confirms_callback", "receipt.confirms",
        )
        _refuse_unless(
            self.confirms is None or intent != "reopen", RefusalCode.MALFORMED, "receipt.confirms_intent", "receipt.confirms",
        )
        _refuse_unless(
            intent != "correct" or bool(self.supersedes), RefusalCode.MALFORMED, "receipt.correct_targets", "receipt.supersedes",
        )
        _refuse_unless(
            intent == "correct" or not self.supersedes, RefusalCode.MALFORMED, "receipt.targets_correct", "receipt.supersedes",
        )
        _refuse_unless(
            intent == "answer" or self.reason is not None, RefusalCode.MALFORMED, "receipt.reason_required", "receipt.reason",
        )
        _refuse_unless(
            intent != "reopen" or self.disposition is None, RefusalCode.MALFORMED, "receipt.reopen_disposition",
            "receipt.disposition",
        )
        _refuse_unless(
            intent != "reopen" or self.seen_revision is not None, RefusalCode.MALFORMED, "receipt.reopen_snapshot",
            "receipt.seen_revision",
        )
        _refuse_unless(
            intent == "reopen" or (self.seen_revision is None and not self.seen_active_event_ids),
            RefusalCode.MALFORMED, "receipt.snapshot_reopen", "receipt.seen_revision",
        )


# --- the caller's input boundary ----------------------------------------------


@dataclass(frozen=True, slots=True)
class CallerInput:
    """What the requirements caller is handed: data, never paths, and nothing it opens.

    A missing original or prior record, or any hash that does not match, is a
    repairable refusal. It is never replaced by an empty history.
    """

    stream: StreamKey
    original_text: str | None
    original_sha256: str
    candidate_json: str
    candidate_sha256: str
    candidate_ref: str
    candidate_brief_sha256: str | None  # the brief digest recorded with the candidate's packet or run
    prior_revision: int
    prior_record_json: str | None
    prior_record_sha256: str | None
    question_ids: tuple[str, ...]
    source_authority_ref: str | None
    transport: TransportNamespace
    chat_id: str
    responder_policy_ref: str
    affected_decisions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _instance(self.stream, StreamKey, "caller.stream")
        _refuse_unless(
            self.original_text is not None, RefusalCode.MISSING_ORIGINAL, "caller.original_missing", "caller.original_text",
        )
        original = _text(self.original_text, "caller.original_text")
        _match(self.original_sha256, _HEX64, "caller.original_sha256")
        _refuse_unless(
            _sha256(original) == self.original_sha256, RefusalCode.HASH_MISMATCH, "caller.original_hash",
            "caller.original_sha256",
        )
        _refuse_unless(
            self.stream.brief_sha256 == self.original_sha256, RefusalCode.HASH_MISMATCH, "caller.stream_brief",
            "caller.stream.brief_sha256",
        )
        candidate_text = _text(self.candidate_json, "caller.candidate_json")
        _match(self.candidate_sha256, _HEX64, "caller.candidate_sha256")
        _refuse_unless(
            _sha256(candidate_text) == self.candidate_sha256, RefusalCode.HASH_MISMATCH, "caller.candidate_hash",
            "caller.candidate_sha256",
        )
        _match(self.candidate_ref, _REF, "caller.candidate_ref")
        candidate = _parse_object(candidate_text, "caller.candidate_json")
        _refuse_unless(
            candidate.get("contract") == PROFILE_CONTRACT, RefusalCode.MALFORMED, "caller.candidate_contract",
            "caller.candidate_json.contract",
        )
        # The candidate is bound to this brief by the digest recorded with its run, by its own
        # brief_sha256, or both; each one present must match, and an unbound candidate is refused.
        if self.candidate_brief_sha256 is not None:
            _match(self.candidate_brief_sha256, _HEX64, "caller.candidate_brief_sha256")
            _refuse_unless(
                self.candidate_brief_sha256 == self.original_sha256, RefusalCode.HASH_MISMATCH, "caller.candidate_run_brief",
                "caller.candidate_brief_sha256",
            )
        _refuse_unless(
            "brief_sha256" not in candidate or candidate["brief_sha256"] == self.original_sha256,
            RefusalCode.HASH_MISMATCH, "caller.candidate_brief", "caller.candidate_json.brief_sha256",
        )
        _refuse_unless(
            self.candidate_brief_sha256 is not None or "brief_sha256" in candidate, RefusalCode.MISSING_BINDING,
            "caller.candidate_bound", "caller.candidate_brief_sha256",
        )
        _integer(self.prior_revision, 0, "caller.prior_revision")
        _refuse_unless(
            self.prior_revision == 0 or self.prior_record_json is not None, RefusalCode.MISSING_RECORD,
            "caller.record_missing", "caller.prior_record_json",
        )
        _refuse_unless(
            self.prior_revision > 0 or (self.prior_record_json is None and self.prior_record_sha256 is None),
            RefusalCode.MALFORMED, "caller.record_unexpected", "caller.prior_record_json",
        )
        if self.prior_record_json is not None:
            record_text = _text(self.prior_record_json, "caller.prior_record_json")
            _match(self.prior_record_sha256, _HEX64, "caller.prior_record_sha256")
            _refuse_unless(
                _sha256(record_text) == self.prior_record_sha256, RefusalCode.HASH_MISMATCH, "caller.record_hash",
                "caller.prior_record_sha256",
            )
            record = _parse_object(record_text, "caller.prior_record_json")
            _refuse_unless(
                record.get("contract") == FOUNDATION_CONTRACT, RefusalCode.MALFORMED, "caller.record_contract",
                "caller.prior_record_json.contract",
            )
            _refuse_unless(
                record.get("brief_sha256") == self.original_sha256, RefusalCode.HASH_MISMATCH, "caller.record_brief",
                "caller.prior_record_json.brief_sha256",
            )
        _string_tuple(self.question_ids, _question_ref, "caller.question_ids")
        _string_tuple(self.affected_decisions, _nonblank, "caller.affected_decisions")
        _refuse_unless(
            self.source_authority_ref is not None, RefusalCode.MISSING_AUTHORITY, "caller.authority_missing",
            "caller.source_authority_ref",
        )
        _match(self.source_authority_ref, _REF, "caller.source_authority_ref")
        _instance(self.transport, TransportNamespace, "caller.transport")
        _telegram_chat_id(self.chat_id, "caller.chat_id")
        _match(self.responder_policy_ref, _REF, "caller.responder_policy_ref")

    def candidate(self) -> dict[str, Any]:
        """A fresh parse of the exact candidate text (already checked)."""
        return _parse_object(self.candidate_json, "caller.candidate_json")

    def prior_record(self) -> dict[str, Any] | None:
        """A fresh parse of the exact prior record text, or None for a first creation."""
        if self.prior_record_json is None:
            return None
        return _parse_object(self.prior_record_json, "caller.prior_record_json")

    def presentation(self, question_id: str, metadata_sha256: str, generation: int) -> Presentation:
        """A presentation for one selected question, bound to this caller's stream and responders."""
        _question_ref(question_id, "caller.presentation.question_id")
        _refuse_unless(
            question_id in self.question_ids, RefusalCode.UNKNOWN_QUESTION, "caller.question_selected",
            "caller.presentation.question_id",
        )
        return Presentation(
            stream=self.stream, question_id=question_id, metadata_sha256=metadata_sha256, generation=generation,
            responder_policy_ref=self.responder_policy_ref, transport=self.transport, chat_id=self.chat_id,
        )


# --- results ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReceiptValidation:
    """The result of validating one receipt. Only "accepted" carries a human event.

    retained: a well-formed receipt is kept as evidence and nothing is applied.
    refused: the receipt is rejected; only this diagnostic is kept.
    """

    status: str
    receipt_sha256: str
    code: RefusalCode | None = None
    guard: str | None = None
    event_id: str | None = None
    event_json: str | None = None

    def __post_init__(self) -> None:
        _member(self.status, VALIDATION_STATUSES, "validation.status")
        _match(self.receipt_sha256, _HEX64, "validation.receipt_sha256")
        _code(self.code, "validation.code")
        if self.guard is not None:
            _nonblank(self.guard, "validation.guard")
        if self.event_id is not None:
            _event_ref(self.event_id, "validation.event_id")
        accepted = self.status == "accepted"
        _refuse_unless(
            not accepted or (self.code is None and self.guard is None and self.event_id is not None
                             and self.event_json is not None),
            RefusalCode.MALFORMED, "validation.accepted", "validation",
        )
        _refuse_unless(
            accepted or (self.code is not None and self.guard is not None and self.event_id is None
                         and self.event_json is None),
            RefusalCode.MALFORMED, "validation.unaccepted", "validation",
        )
        _refuse_unless(
            self.status != "retained" or self.code in RETAINED_CODES, RefusalCode.MALFORMED, "validation.retained_code",
            "validation.code",
        )
        _refuse_unless(
            self.status != "refused" or self.code in REFUSED_CODES, RefusalCode.MALFORMED, "validation.refused_code",
            "validation.code",
        )
        if self.event_json is not None:
            event = _parse_object(self.event_json, "validation.event_json")
            actor = event.get("actor")
            _refuse_unless(
                event.get("event_id") == self.event_id, RefusalCode.HASH_MISMATCH, "validation.event_id",
                "validation.event_json.event_id",
            )
            _refuse_unless(
                event.get("source") == {"kind": "human_response", "ref": f"{RECEIPT_REF_SCHEME}:{self.receipt_sha256}"},
                RefusalCode.HASH_MISMATCH, "validation.event_source", "validation.event_json.source",
            )
            _refuse_unless(
                type(actor) is dict and actor.get("kind") == "human", RefusalCode.MODEL_NOT_HUMAN,
                "validation.event_human", "validation.event_json.actor",
            )
            _refuse_unless(
                _canonical(event) == self.event_json, RefusalCode.MALFORMED, "validation.event_canonical",
                "validation.event_json",
            )

    def event(self) -> dict[str, Any] | None:
        """A fresh copy of the foundation event, or None unless accepted."""
        if self.event_json is None:
            return None
        return _parse_object(self.event_json, "validation.event_json")


@dataclass(frozen=True, slots=True)
class AppendResult:
    """What one append attempt did to one stream, decided inside one transaction.

    An identical replay returns the stored result unchanged. revision is the
    stream's revision after the attempt: one more than expected when applied,
    unchanged otherwise, and different from expected on a CAS conflict.
    """

    status: str
    stream_id: str
    action_key: str
    receipt_sha256: str
    expected_revision: int
    revision: int
    event_id: str | None = None
    code: RefusalCode | None = None

    def __post_init__(self) -> None:
        _member(self.status, APPEND_STATUSES, "append.status")
        _match(self.stream_id, _STREAM_ID, "append.stream_id")
        _match(self.action_key, _ACTION_KEY, "append.action_key")
        _match(self.receipt_sha256, _HEX64, "append.receipt_sha256")
        _integer(self.expected_revision, 0, "append.expected_revision")
        _integer(self.revision, 0, "append.revision")
        if self.event_id is not None:
            _event_ref(self.event_id, "append.event_id")
        _code(self.code, "append.code")
        applied = self.status == "applied"
        _refuse_unless(
            not applied or (self.code is None and self.event_id is not None
                            and self.revision == self.expected_revision + 1),
            RefusalCode.MALFORMED, "append.applied", "append",
        )
        _refuse_unless(
            applied or (self.code is not None and self.event_id is None), RefusalCode.MALFORMED, "append.unapplied",
            "append",
        )
        _refuse_unless(
            self.status != "retained" or self.code in RETAINED_CODES, RefusalCode.MALFORMED, "append.retained_code",
            "append.code",
        )
        _refuse_unless(
            self.status != "refused" or self.code in REFUSED_CODES, RefusalCode.MALFORMED, "append.refused_code",
            "append.code",
        )
        _refuse_unless(
            self.code != RefusalCode.REVISION_CONFLICT or self.revision != self.expected_revision,
            RefusalCode.MALFORMED, "append.conflict_revision", "append.revision",
        )
        _refuse_unless(
            applied or self.code == RefusalCode.REVISION_CONFLICT or self.revision == self.expected_revision,
            RefusalCode.MALFORMED, "append.unchanged_revision", "append.revision",
        )


# --- pure functions -----------------------------------------------------------


def question_id(brief_sha256: str, unknown: Mapping[str, object]) -> str:
    """The #308 foundation's q- ID: brief hash plus the exact unknown metadata.

    No namespace: the namespace lives in the StreamKey. Equal to the
    foundation's own derivation for the same input.
    """
    _match(brief_sha256, _HEX64, "question_id.brief_sha256")
    metadata = _json_object(unknown, "question_id.unknown")
    return "q-" + _sha256(_canonical({"contract": FOUNDATION_CONTRACT, "brief_sha256": brief_sha256, "unknown": metadata}))


def metadata_sha256(unknown: Mapping[str, object]) -> str:
    """Digest of one question's exact unknown metadata, as a presentation binds it."""
    return _sha256(_canonical(_json_object(unknown, "metadata_sha256.unknown")))


def receipt_json(receipt: ActionReceipt) -> str:
    """The exact sidecar text: canonical JSON of the whole receipt."""
    _instance(receipt, ActionReceipt, "receipt_json.receipt")
    return _canonical({"contract": CONTRACT, "receipt": asdict(receipt)})


def receipt_sha256(receipt: ActionReceipt) -> str:
    """SHA-256 of the sidecar text; source.ref is clarification-receipt:<this>."""
    return _sha256(receipt_json(receipt))


_TRANSPORT_FIELDS = frozenset({"transport", "bot_id"})
_ACTION_FIELDS = frozenset({"transport", "chat_id", "kind", "action_id"})
_BINDING_FIELDS = frozenset({"stream_id", "question_id", "presentation_id", "generation", "message_id"})
_RESPONDER_FIELDS = frozenset({"policy_ref", "sender_id", "decision", "basis"})
_CONFIRMS_FIELDS = frozenset({"action", "author_id", "text_sha256"})
_RECEIPT_FIELDS = frozenset({
    "ingress", "action", "update_id", "sender_id", "sender_is_bot", "forwarded", "text", "text_sha256",
    "binding", "responder", "intent", "disposition", "callback_data", "supersedes", "reason", "confirms",
    "seen_revision", "seen_active_event_ids",
})


def _action_from(value: object, where: str) -> ActionIdentity:
    data = _closed(value, _ACTION_FIELDS, where)
    transport = _closed(data["transport"], _TRANSPORT_FIELDS, where + ".transport")
    return ActionIdentity(
        transport=TransportNamespace(transport=transport["transport"], bot_id=transport["bot_id"]),
        chat_id=data["chat_id"], kind=data["kind"], action_id=data["action_id"],
    )


def receipt_from_json(text: str) -> ActionReceipt:
    """Decode a stored sidecar. Refuses anything but the exact canonical text."""
    data = _closed(_parse_object(text, "sidecar"), frozenset({"contract", "receipt"}), "sidecar")
    _refuse_unless(data["contract"] == CONTRACT, RefusalCode.MALFORMED, "sidecar.contract", "sidecar.contract")
    body = _closed(data["receipt"], _RECEIPT_FIELDS, "sidecar.receipt")
    binding = _closed(body["binding"], _BINDING_FIELDS, "sidecar.receipt.binding")
    responder = _closed(body["responder"], _RESPONDER_FIELDS, "sidecar.receipt.responder")
    confirms = None
    if body["confirms"] is not None:
        link = _closed(body["confirms"], _CONFIRMS_FIELDS, "sidecar.receipt.confirms")
        confirms = ConfirmedText(
            action=_action_from(link["action"], "sidecar.receipt.confirms.action"),
            author_id=link["author_id"], text_sha256=link["text_sha256"],
        )
    receipt = ActionReceipt(
        ingress=body["ingress"],
        action=_action_from(body["action"], "sidecar.receipt.action"),
        update_id=body["update_id"],
        sender_id=body["sender_id"],
        sender_is_bot=body["sender_is_bot"],
        forwarded=body["forwarded"],
        text=body["text"],
        text_sha256=body["text_sha256"],
        binding=PresentationBinding(**binding),
        responder=ResponderDecision(**responder),
        intent=body["intent"],
        disposition=body["disposition"],
        callback_data=body["callback_data"],
        supersedes=_listed(body["supersedes"], "sidecar.receipt.supersedes"),
        reason=body["reason"],
        confirms=confirms,
        seen_revision=body["seen_revision"],
        seen_active_event_ids=_listed(body["seen_active_event_ids"], "sidecar.receipt.seen_active_event_ids"),
    )
    _refuse_unless(receipt_json(receipt) == text, RefusalCode.MALFORMED, "sidecar.canonical", "sidecar")
    return receipt


def event_id(receipt: ActionReceipt) -> str:
    """e- digest of the immutable action identity plus its question binding.

    Never the response text, disposition, update ID, time or retry count: an
    exact replay keeps its ID, a changed body under the same identity is
    refused by check_replay, and two different actions with equal text differ.
    """
    _instance(receipt, ActionReceipt, "event_id.receipt")
    binding = receipt.binding
    return "e-" + _digest("event", {
        "action": asdict(receipt.action),
        "binding": {
            "stream_id": binding.stream_id,
            "question_id": binding.question_id,
            "presentation_id": binding.presentation_id,
        },
    })


def _check_action(receipt: ActionReceipt, presentation: Presentation, copies: frozenset[str]) -> None:
    """Provenance, responder authority and binding of one action to its presentation."""
    _refuse_unless(receipt.ingress != MODEL_INGRESS, RefusalCode.MODEL_NOT_HUMAN, "provenance.model", "receipt.ingress")
    _refuse_unless(
        receipt.ingress == VERIFIED_INGRESS, RefusalCode.UNVERIFIED_INGRESS, "provenance.ingress", "receipt.ingress",
    )
    _refuse_unless(not receipt.sender_is_bot, RefusalCode.BOT_SENDER, "provenance.bot", "receipt.sender_is_bot")
    _refuse_unless(not receipt.forwarded, RefusalCode.FORWARDED_MESSAGE, "provenance.forwarded", "receipt.forwarded")
    _refuse_unless(
        receipt.action.transport == presentation.transport, RefusalCode.TRANSPORT_MISMATCH, "provenance.transport",
        "receipt.action.transport",
    )
    _refuse_unless(
        receipt.action.chat_id == presentation.chat_id, RefusalCode.TRANSPORT_MISMATCH, "provenance.chat",
        "receipt.action.chat_id",
    )
    responder = receipt.responder
    _refuse_unless(
        responder.sender_id == receipt.sender_id, RefusalCode.RESPONDER_NOT_AUTHORISED, "responder.subject",
        "receipt.responder.sender_id",
    )
    _refuse_unless(
        responder.policy_ref == presentation.responder_policy_ref, RefusalCode.RESPONDER_NOT_AUTHORISED,
        "responder.policy", "receipt.responder.policy_ref",
    )
    _refuse_unless(
        responder.basis == "responder_policy", RefusalCode.RESPONDER_NOT_AUTHORISED, "responder.basis",
        "receipt.responder.basis",
    )
    _refuse_unless(
        responder.decision == "authorised", RefusalCode.RESPONDER_NOT_AUTHORISED, "responder.decision",
        "receipt.responder.decision",
    )
    binding = receipt.binding
    _refuse_unless(
        binding.stream_id == presentation.stream.stream_id, RefusalCode.CROSS_CONTEXT, "binding.stream",
        "receipt.binding.stream_id",
    )
    _refuse_unless(
        binding.question_id == presentation.question_id, RefusalCode.BINDING_MISMATCH, "binding.question",
        "receipt.binding.question_id",
    )
    _refuse_unless(
        binding.presentation_id == presentation.presentation_id, RefusalCode.BINDING_MISMATCH, "binding.presentation",
        "receipt.binding.presentation_id",
    )
    _refuse_unless(
        binding.generation == presentation.generation, RefusalCode.BINDING_MISMATCH, "binding.generation",
        "receipt.binding.generation",
    )
    _refuse_unless(binding.message_id in copies, RefusalCode.BINDING_MISMATCH, "binding.copy", "receipt.binding.message_id")


def _check_receipt(
    receipt: ActionReceipt,
    presentation: Presentation,
    copies: frozenset[str],
    current_generation: int,
    question_ids: frozenset[str],
    confirmed: ActionReceipt | None,
) -> str:
    """Every receipt check before an event may exist; returns the exact answer text."""
    _check_action(receipt, presentation, copies)
    _refuse_unless(
        presentation.question_id in question_ids, RefusalCode.UNKNOWN_QUESTION, "binding.known_question",
        "presentation.question_id",
    )
    _refuse_unless(
        presentation.generation <= current_generation, RefusalCode.BINDING_MISMATCH, "binding.future_generation",
        "presentation.generation",
    )
    _refuse_unless(
        presentation.generation == current_generation, RefusalCode.STALE_PRESENTATION, "binding.stale",
        "presentation.generation",
    )
    text = receipt.text
    confirms = receipt.confirms
    _refuse_unless(confirms is None or confirmed is not None, RefusalCode.MISSING_RECORD, "confirm.missing", "confirmed")
    _refuse_unless(confirms is not None or confirmed is None, RefusalCode.MALFORMED, "confirm.unexpected", "confirmed")
    if confirms is not None and confirmed is not None:
        _check_action(confirmed, presentation, copies)
        _refuse_unless(
            confirmed.action == confirms.action, RefusalCode.BINDING_MISMATCH, "confirm.identity", "receipt.confirms.action",
        )
        _refuse_unless(
            confirmed.text_sha256 == confirms.text_sha256, RefusalCode.HASH_MISMATCH, "confirm.digest",
            "receipt.confirms.text_sha256",
        )
        _refuse_unless(
            confirmed.sender_id == confirms.author_id, RefusalCode.BINDING_MISMATCH, "confirm.author_recorded",
            "receipt.confirms.author_id",
        )
        # A later confirmer never becomes the author of somebody else's text.
        _refuse_unless(
            receipt.sender_id == confirmed.sender_id, RefusalCode.CONFIRMER_NOT_AUTHOR, "confirm.author",
            "receipt.sender_id",
        )
        text = confirmed.text
    if receipt.intent != "reopen":
        _refuse_unless(
            receipt.disposition is not None, RefusalCode.NO_EXPLICIT_DISPOSITION, "disposition.explicit",
            "receipt.disposition",
        )
        _refuse_unless(not _blank(text), RefusalCode.BLANK_TEXT, "text.blank", "receipt.text")
    return text


def _actor_ref(receipt: ActionReceipt) -> str:
    """The event's actor.ref: the authenticated sender in the transport's namespace."""
    return f"{receipt.action.transport.transport}-user:{receipt.sender_id}"


def _event(receipt: ActionReceipt, question: str, text: str) -> dict[str, object]:
    """The #308 foundation event for an accepted receipt (closed schema, unchanged)."""
    event: dict[str, object] = {
        "event_id": event_id(receipt),
        "question_id": question,
        "actor": {"kind": "human", "ref": _actor_ref(receipt)},
        "source": {"kind": "human_response", "ref": f"{RECEIPT_REF_SCHEME}:{receipt_sha256(receipt)}"},
    }
    if receipt.intent == "reopen":
        event.update(kind="reopen", reason=receipt.reason)
    else:
        event.update(kind="answer", answer=text, disposition=receipt.disposition, supersedes=list(receipt.supersedes))
        if receipt.reason is not None:
            event["reason"] = receipt.reason
    return event


def validate_receipt(
    receipt: ActionReceipt,
    *,
    presentation: Presentation,
    copies: Collection[str],
    current_generation: int,
    question_ids: Collection[str],
    confirmed: ActionReceipt | None = None,
) -> ReceiptValidation:
    """Every receipt check before any human event exists.

    It never compares with stored receipts, active answers or the stream's revision:
    the store calls check_replay, check_reopen_precondition,
    check_correction_precondition, check_confirmation_precondition and
    check_expected_revision for those.

    presentation: the persisted presentation the action is bound to. copies:
    transport message IDs delivered for it. current_generation: the latest
    generation for its question. question_ids: questions of the latest record.
    confirmed: the earlier typed message a callback confirms. Wrongly typed
    arguments raise ContractRefusal; everything about the action itself is a
    result: accepted (with the event), retained or refused. A receipt with no
    canonical form (an int past Python's digit limit) raises too: it has no
    digest to keep.
    """
    _instance(receipt, ActionReceipt, "validate.receipt")
    _instance(presentation, Presentation, "validate.presentation")
    copy_ids = _string_set(copies, _telegram_id, "validate.copies")
    _integer(current_generation, 1, "validate.current_generation")
    known = _string_set(question_ids, _question_ref, "validate.question_ids")
    if confirmed is not None:
        _instance(confirmed, ActionReceipt, "validate.confirmed")
    digest = receipt_sha256(receipt)
    try:
        text = _check_receipt(receipt, presentation, copy_ids, current_generation, known, confirmed)
    except ContractRefusal as refusal:
        status = "retained" if refusal.code in RETAINED_CODES else "refused"
        return ReceiptValidation(status=status, receipt_sha256=digest, code=refusal.code, guard=refusal.guard)
    event = _event(receipt, presentation.question_id, text)
    return ReceiptValidation(
        status="accepted", receipt_sha256=digest, event_id=cast(str, event["event_id"]), event_json=_canonical(event),
    )


def check_replay(stored: ActionReceipt, incoming: ActionReceipt) -> bool:
    """True for an exact replay, False for a different action; a changed body is refused.

    Only a provider-pull receipt (accepted or retained) holds an action key. A stored
    receipt from any other ingress is refused, never compared, so an unverified or
    model claim on a genuine action's key cannot turn the real answer away.
    """
    _instance(stored, ActionReceipt, "replay.stored")
    _instance(incoming, ActionReceipt, "replay.incoming")
    _refuse_unless(
        stored.ingress == VERIFIED_INGRESS, RefusalCode.MALFORMED, "replay.stored_verified", "replay.stored",
    )
    if stored.action.key != incoming.action.key:
        return False
    _refuse_unless(receipt_json(stored) == receipt_json(incoming), RefusalCode.CHANGED_BODY, "replay.body", "receipt")
    return True


def check_reopen_precondition(receipt: ActionReceipt, *, revision: int, active_event_ids: Collection[str]) -> None:
    """Refuse a reopen whose displayed snapshot no longer holds (STALE_REOPEN, retained).

    The snapshot is the question's active answer set the person saw; an answer
    they never saw is not swept away by their reopen.
    """
    _instance(receipt, ActionReceipt, "reopen.receipt")
    _refuse_unless(receipt.intent == "reopen", RefusalCode.MALFORMED, "reopen.intent", "receipt.intent")
    current = _integer(revision, 0, "reopen.current_revision")
    active = _string_set(active_event_ids, _event_ref, "reopen.active_event_ids")
    seen = receipt.seen_revision
    _refuse_unless(
        seen is not None and seen <= current, RefusalCode.STALE_REOPEN, "reopen.revision", "receipt.seen_revision",
    )
    _refuse_unless(
        frozenset(receipt.seen_active_event_ids) == active, RefusalCode.STALE_REOPEN, "reopen.active_set",
        "receipt.seen_active_event_ids",
    )


def check_correction_precondition(receipt: ActionReceipt, *, answer_actors: Mapping[str, str]) -> None:
    """Refuse a correction of somebody else's answer (CROSS_ACTOR_CORRECTION, retained).

    answer_actors: the actor.ref of each stored answer to the receipt's question, by
    event ID. A correction supersedes only its sender's own answers. Another person's
    answer changes only through a reopen (with a reason, against the answers the person
    saw) and then a new answer; two people's differing answers stay conflicting. A
    named answer the store does not have is missing, never assumed, whatever else the
    correction names; the order of supersedes never changes the outcome.
    """
    _instance(receipt, ActionReceipt, "correction.receipt")
    _refuse_unless(receipt.intent == "correct", RefusalCode.MALFORMED, "correction.intent", "receipt.intent")
    actors = _actor_refs(answer_actors, "correction.answer_actors")
    _refuse_unless(
        all(superseded in actors for superseded in receipt.supersedes), RefusalCode.MISSING_RECORD,
        "correction.known", "receipt.supersedes",
    )
    sender = _actor_ref(receipt)
    _refuse_unless(
        all(actors[superseded] == sender for superseded in receipt.supersedes), RefusalCode.CROSS_ACTOR_CORRECTION,
        "correction.same_actor", "receipt.supersedes",
    )


def check_confirmation_precondition(receipt: ActionReceipt, *, confirmed_actions: Collection[str]) -> None:
    """Refuse a second event from one typed message (ALREADY_CONFIRMED, retained).

    confirmed_actions: the action keys of the typed messages that already gave an event
    in this stream, applied directly or through a button press. One typed message gives
    at most one event, whatever disposition a later press carries; a change of mind is a
    correction.
    """
    _instance(receipt, ActionReceipt, "confirmation.receipt")
    confirms = receipt.confirms
    _refuse_unless(confirms is not None, RefusalCode.MALFORMED, "confirmation.confirms", "receipt.confirms")
    done = _string_set(confirmed_actions, _action_ref, "confirmation.confirmed_actions")
    _refuse_unless(
        cast(ConfirmedText, confirms).action.key not in done, RefusalCode.ALREADY_CONFIRMED, "confirmation.once",
        "receipt.confirms.action",
    )


def check_expected_revision(expected: int, current: int) -> None:
    """The CAS predicate: refuse when the stream moved (an ordinary append reloads and recomputes)."""
    _integer(expected, 0, "cas.expected")
    _integer(current, 0, "cas.current")
    _refuse_unless(expected == current, RefusalCode.REVISION_CONFLICT, "cas.revision", "expected_revision")


def consumption_id(stream_id: str, revision: int, supplement_sha256: str) -> str:
    """c- digest of (stream, committed revision, supplement digest): consume each at most once."""
    _match(stream_id, _STREAM_ID, "consumption.stream_id")
    _integer(revision, 1, "consumption.revision")
    _match(supplement_sha256, _HEX64, "consumption.supplement_sha256")
    return "c-" + _digest(
        "consumption", {"stream_id": stream_id, "revision": revision, "supplement_sha256": supplement_sha256},
    )
