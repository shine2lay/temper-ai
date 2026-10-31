"""Durable delivery transactions inside ClarificationStore's persistence component.

Stream first, send second; no process-local lock and no network calls. The
stream CAS serializes all writes. A checked read after that write is the
admission snapshot, including changes that did not advance the revision.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, cast

from sqlmodel import Session, col, select

from temper_ai.clarifications.contracts import (
    REFUSED_CODES,
    RETAINED_CODES,
    ActionIdentity,
    ActionReceipt,
    AppendResult,
    ConfirmedText,
    ContractRefusal,
    Presentation,
    PresentationBinding,
    ReceiptValidation,
    RefusalCode,
    StreamKey,
    TransportNamespace,
    check_expected_revision,
    receipt_sha256,
)
from temper_ai.clarifications.delivery_models import (
    ClarificationDelivery,
    ClarificationIngress,
    ClarificationSend,
    IngressAppendResult,
)
from temper_ai.clarifications.models import (
    ClarificationCopy,
    ClarificationRefusal,
    ClarificationStream,
)
from temper_ai.clarifications.store import (
    ClarificationStore,
    _canonical,
    _copy_sha256,
    _encodable,
    _intact,
    _Loaded,
    _require,
    _Retry,
    _sha256,
)
from temper_ai.integrations.telegram.clarifications import (
    PulledIngress,
    Refusal,
    SendIntent,
    SendRecord,
)


def check_read_version(session: Session, stream_id: str, version: int | None) -> None:
    """A coherent multi-SELECT view includes non-revision attempt/delivery writes."""
    current = session.exec(select(ClarificationStream.state_version).where(
        col(ClarificationStream.stream_id) == stream_id,
    )).first()
    if current != version:
        raise _Retry


def _locked(store: ClarificationStore, session: Session, stream_id: str) -> _Loaded:
    before = store._existing(session, stream_id)
    try:
        store._cas(session, stream_id, before.revision, adds=None)
    except ContractRefusal as refusal:
        if refusal.code is not RefusalCode.REVISION_CONFLICT:
            raise
        raise _Retry from None  # the lock acquisition raced, not the caller's current-ack predicate
    # A preceding writer can change generation/copies/attempts without moving
    # revision. Refresh *after* obtaining the stream's database write lock.
    session.expire_all()
    return store._existing(session, stream_id)


def _intent_text(intent: SendIntent) -> str:
    _require(type(intent) is SendIntent, RefusalCode.MALFORMED, "send.type", "intent")
    _require(type(intent.presentation) is Presentation, RefusalCode.MALFORMED, "send.presentation_type", "intent")
    _require(type(intent.send_id) is str and bool(intent.send_id.strip()) and type(intent.text) is str
             and bool(intent.text.strip()), RefusalCode.MALFORMED, "send.text", "intent")
    _require(type(intent.payloads) is tuple and all(
        type(pair) is tuple and len(pair) == 2 and type(pair[0]) is str and bool(pair[0])
        and pair[1] in ("answered", "deferred", "unknown") for pair in intent.payloads
    ), RefusalCode.MALFORMED, "send.payloads", "intent.payloads")
    _require(intent.confirms is None or type(intent.confirms) is ConfirmedText,
             RefusalCode.MALFORMED, "send.confirms_type", "intent.confirms")
    _require((intent.confirms is None and intent.reply_to is None and not intent.payloads)
             or (intent.confirms is not None and intent.reply_to == intent.confirms.action.action_id
                 and bool(intent.payloads)), RefusalCode.BINDING_MISMATCH, "send.prompt", "intent")
    return _encodable(lambda: _canonical(asdict(intent)), "intent")


def _bound_intent(loaded: _Loaded, intent: SendIntent) -> bool:
    p = intent.presentation
    if loaded.presentations.get(p.presentation_id) != p:
        return False
    confirmed = intent.confirms
    if confirmed is None:
        return True
    typed = loaded.parsed.get(confirmed.action.key)
    return (typed is not None and typed.action == confirmed.action
            and typed.sender_id == confirmed.author_id and typed.text_sha256 == confirmed.text_sha256
            and typed.binding.presentation_id == p.presentation_id
            and typed.action.transport == p.transport and typed.action.chat_id == p.chat_id)


def _decode_intent(row: ClarificationSend, presentation: Presentation) -> SendIntent:
    fields = json.loads(row.intent_json)
    saved_presentation = fields.pop("presentation")
    if saved_presentation != asdict(presentation):
        raise ValueError("presentation binding differs")
    fields["payloads"] = tuple(tuple(pair) for pair in fields["payloads"])
    confirms = fields["confirms"]
    if confirms is not None:
        action = confirms["action"]
        fields["confirms"] = ConfirmedText(
            ActionIdentity(TransportNamespace(**action["transport"]), action["chat_id"], action["kind"],
                           action["action_id"]), confirms["author_id"], confirms["text_sha256"],
        )
    return SendIntent(presentation=presentation, **fields)


def _send_state(row: ClarificationSend) -> str:
    return _sha256(_canonical({name: getattr(row, name) for name in (
        "send_id", "stream_id", "presentation_id", "intent_sha256", "attempt_count", "message_id",
    )}))


def _delivery_digest(row: ClarificationDelivery) -> str:
    return _sha256(_canonical({name: getattr(row, name) for name in (
        "transport", "bot_id", "chat_id", "message_id", "stream_id", "send_id", "presentation_id",
    )}))


def _ingress_digest(row: ClarificationIngress) -> str:
    return _sha256(_canonical(row.model_dump(exclude={"ingress_id", "created_at"})))


def _result_text(result: AppendResult) -> str:
    return _canonical(asdict(result))


def check_delivery_history(store: ClarificationStore, session: Session, loaded: _Loaded,
                           history: dict[str, list[Any]]) -> None:
    """Extend the common loader, never return unchecked send/copy/result membership."""
    stream_id, row = loaded.stream_id, loaded.row
    for kind, count in (("sends", row.send_count), ("deliveries", row.delivery_count),
                        ("ingresses", row.ingress_count)):
        _intact(len(history[kind]) == count, stream_id, "delivery.count", f"{kind} count differs")
    sends: dict[str, SendRecord] = {}
    for saved in history["sends"]:
        presentation = loaded.presentations.get(saved.presentation_id)
        try:
            intent = _decode_intent(saved, presentation) if presentation is not None else None
            valid = (intent is not None and _intent_text(intent) == saved.intent_json
                     and intent.send_id == saved.send_id and _bound_intent(loaded, intent))
        except (ValueError, KeyError, TypeError, UnicodeError, ContractRefusal):
            valid = False
        _intact(valid, stream_id, "send.binding", "send intent does not name its saved presentation/typed receipt")
        _intact(_sha256(saved.intent_json) == saved.intent_sha256, stream_id, "send.digest", "send intent digest differs")
        _intact(type(saved.attempt_count) is int and saved.attempt_count >= 0 and saved.state_sha256 == _send_state(saved),
                stream_id, "send.state", "send state digest/count differs")
        sends[saved.send_id] = SendRecord(cast(SendIntent, intent), saved.attempt_count, saved.message_id)
    mappings: dict[tuple[str, str, str, str], str] = {}
    delivered: dict[str, set[str]] = {}
    for saved in history["deliveries"]:
        record = sends.get(saved.send_id)
        _intact(record is not None and saved.delivery_sha256 == _delivery_digest(saved),
                stream_id, "delivery.digest", "delivery intent/digest differs")
        p = cast(SendRecord, record).intent.presentation
        _intact((saved.transport, saved.bot_id, saved.chat_id, saved.presentation_id)
                == (p.transport.transport, p.transport.bot_id, p.chat_id, p.presentation_id)
                and saved.message_id in loaded.copies.get(p.presentation_id, frozenset()),
                stream_id, "delivery.copy", "delivery has no exact presentation copy")
        mappings[(saved.transport, saved.bot_id, saved.chat_id, saved.message_id)] = saved.send_id
        delivered.setdefault(saved.send_id, set()).add(saved.message_id)
    for send_id, record in sends.items():
        ids = delivered.get(send_id, set())
        _intact((record.message_id is None and not ids) or record.message_id in ids,
                stream_id, "delivery.representative", "representative and delivery set differ")
    for saved in history["ingresses"]:
        _intact(saved.ingress_id == _ingress_digest(saved), stream_id, "ingress.digest", "ingress linkage digest differs")
        capture = ((saved.capture_status == "accepted" and saved.capture_code is None and saved.capture_guard is None)
                   or (saved.capture_status in ("retained", "refused")
                       and saved.capture_code in (RETAINED_CODES if saved.capture_status == "retained" else REFUSED_CODES)
                       and bool(saved.capture_guard)))
        link = ((saved.receipt_sha256 is not None and saved.action_key is not None and saved.result_json is not None)
                or (saved.receipt_sha256 is None and saved.action_key is None and saved.result_json is None
                    and saved.result_guard is None and saved.refusal_id is None and saved.capture_status == "refused"
                    and (saved.diagnostic_code, saved.diagnostic_guard) == (saved.capture_code, saved.capture_guard)))
        _intact(capture and link, stream_id, "ingress.shape", "ingress is neither a linked result nor a no-receipt refusal")
        if saved.result_json is not None:
            try:
                fields = json.loads(saved.result_json)
                fields["code"] = None if fields["code"] is None else RefusalCode(fields["code"])
                result = AppendResult(**fields)
                valid = (_result_text(result) == saved.result_json and result.stream_id == stream_id
                         and (result.action_key, result.receipt_sha256) == (saved.action_key, saved.receipt_sha256))
            except (ValueError, TypeError, KeyError):
                valid = False
            _intact(valid, stream_id, "ingress.result_shape", "ingress result binding is invalid")
            if result.status == "refused":
                _intact(saved.refusal_id is not None and result.code == saved.diagnostic_code
                        and saved.result_guard == saved.diagnostic_guard,
                        stream_id, "ingress.refused_result", "refused result does not name its diagnostic")
            else:
                kept = loaded.receipts.get(result.action_key)
                receipt = loaded.parsed.get(result.action_key)
                _intact(kept is not None and receipt is not None and _result_text(store._result(kept)) == saved.result_json
                        and kept.guard == saved.result_guard and kept.receipt_sha256 == saved.receipt_sha256
                        and (receipt.action.transport.transport, receipt.action.transport.bot_id, receipt.update_id)
                        == (saved.transport, saved.bot_id, saved.update_id)
                        and saved.refusal_id is None and saved.diagnostic_code is None and saved.diagnostic_guard is None,
                        stream_id, "ingress.result", "ingress is not linked to the exact authoritative result")
        if saved.refusal_id is not None:
            diagnostic = session.get(ClarificationRefusal, saved.refusal_id)
            _intact(diagnostic is not None and (diagnostic.stream_id, diagnostic.receipt_sha256, diagnostic.action_key,
                    diagnostic.code, diagnostic.guard) == (stream_id, saved.receipt_sha256, saved.action_key,
                    saved.diagnostic_code, saved.diagnostic_guard),
                    stream_id, "ingress.refusal", "ingress diagnostic linkage differs")
    loaded.sends, loaded.deliveries = sends, mappings


def _has_send(session: Session, send_id: str) -> bool:
    """Check global uniqueness without reading another stream's intent/prompt body."""
    return session.exec(select(ClarificationSend.send_id).where(col(ClarificationSend.send_id) == send_id)).first() is not None


class ClarificationDeliveryStore:
    """The same store's transport ledger. Trusted supplied evidence only, never a history search."""

    def __init__(self, store: ClarificationStore) -> None:
        self.store = store

    def save_send(self, intent: SendIntent) -> SendRecord:
        text = _intent_text(intent)
        stream_id = intent.presentation.stream.stream_id

        def step(session: Session) -> SendRecord:
            loaded = _locked(self.store, session, stream_id)
            _require(_bound_intent(loaded, intent), RefusalCode.BINDING_MISMATCH, "send.binding", "intent")
            kept = loaded.sends.get(intent.send_id)
            if kept is not None:
                _require(kept.intent == intent, RefusalCode.CHANGED_BODY, "send.changed", "intent")
                session.rollback()
                return kept
            _require(not _has_send(session, intent.send_id), RefusalCode.CHANGED_BODY,
                     "send.changed", "intent")
            self.store._cas(session, stream_id, loaded.revision, adds="send")
            row = ClarificationSend(send_id=intent.send_id, stream_id=stream_id,
                                    presentation_id=intent.presentation.presentation_id,
                                    intent_json=text, intent_sha256=_sha256(text), state_sha256="")
            row.state_sha256 = _send_state(row)
            session.add(row)
            self.store._commit(session, lambda again: _has_send(again, intent.send_id))
            return SendRecord(intent)

        return self.store._attempt(step)

    def _send(self, session: Session, send_id: str, stream: StreamKey | None, *, lock: bool) -> _Loaded:
        # Scope-bound callers supply stream; never inspect another stream to
        # implement an adapter read or write. The unbound API is trusted storage.
        if stream is None:
            row = session.get(ClarificationSend, send_id)
            _require(row is not None, RefusalCode.MISSING_RECORD, "send.missing", "send_id")
            stream_id = cast(ClarificationSend, row).stream_id
        else:
            stream_id = self.store._stream_id(stream, "send.stream")
        loaded = _locked(self.store, session, stream_id) if lock else self.store._existing(session, stream_id)
        _require(send_id in loaded.sends, RefusalCode.MISSING_RECORD, "send.missing", "send_id")
        return loaded

    def start_attempt(self, send_id: str, *, expected_attempts: int, resend: bool,
                      stream: StreamKey | None = None) -> tuple[SendRecord, bool]:
        _require(type(expected_attempts) is int and expected_attempts >= 0 and type(resend) is bool,
                 RefusalCode.MALFORMED, "send.admission_input", "expected_attempts/resend")

        def step(session: Session) -> tuple[SendRecord, bool]:
            loaded = self._send(session, send_id, stream, lock=True)
            record = loaded.sends[send_id]
            p = record.intent.presentation
            delivered = send_id in loaded.deliveries.values()
            answered = p.question_id in self.store._protocol_view(loaded).answered
            eligible = (not delivered and record.attempts == expected_attempts and (record.attempts == 0 or resend)
                        and p.generation == loaded.generation(p.question_id) and not answered)
            if not eligible:
                session.rollback()  # even the lock's provisional touch is not committed
                return record, False
            row = cast(ClarificationSend, session.get(ClarificationSend, send_id))
            row.attempt_count += 1
            row.state_sha256 = _send_state(row)
            session.add(row)
            self.store._commit(session, lambda again: False)
            return SendRecord(record.intent, row.attempt_count, row.message_id), True

        return self.store._attempt(step)

    def record_delivery(self, send_id: str, message_id: str, *, stream: StreamKey | None = None) -> SendRecord:
        """Reconcile supplied verified evidence or one network completion; keep every ID.

        The embedding caller must establish evidence/authority. This operation
        does not claim a chat was searched or choose any real fallback policy.
        """
        def step(session: Session) -> SendRecord:
            loaded = self._send(session, send_id, stream, lock=True)
            record = loaded.sends[send_id]
            p = record.intent.presentation
            binding = PresentationBinding(loaded.stream_id, p.question_id, p.presentation_id, p.generation, message_id)
            key = (p.transport.transport, p.transport.bot_id, p.chat_id, message_id)
            held = session.get(ClarificationDelivery, key)
            if held is not None:
                _require(held.send_id == send_id and key in loaded.deliveries,
                         RefusalCode.BINDING_MISMATCH, "delivery.occupied", "message_id")
                session.rollback()
                return record
            if message_id not in loaded.copies.get(p.presentation_id, frozenset()):
                self.store._cas(session, loaded.stream_id, loaded.revision, adds="copy")
                copy = ClarificationCopy(presentation_id=binding.presentation_id, message_id=message_id,
                                         stream_id=loaded.stream_id)
                copy.copy_sha256 = _copy_sha256(copy)
                session.add(copy)
            self.store._cas(session, loaded.stream_id, loaded.revision, adds="delivery")
            delivery = ClarificationDelivery(transport=key[0], bot_id=key[1], chat_id=key[2], message_id=message_id,
                                             stream_id=loaded.stream_id, send_id=send_id,
                                             presentation_id=p.presentation_id, delivery_sha256="")
            delivery.delivery_sha256 = _delivery_digest(delivery)
            session.add(delivery)
            row = cast(ClarificationSend, session.get(ClarificationSend, send_id))
            row.message_id = message_id
            row.state_sha256 = _send_state(row)
            session.add(row)
            self.store._commit(session, lambda again: again.get(ClarificationDelivery, key) is not None)
            return SendRecord(record.intent, row.attempt_count, message_id)

        return self.store._attempt(step)

    def delivery(self, transport: TransportNamespace, chat_id: str, message_id: str,
                 *, stream: StreamKey | None = None) -> SendRecord | None:
        key = (transport.transport, transport.bot_id, chat_id, message_id)

        def step(session: Session) -> SendRecord | None:
            if stream is None:
                row = session.get(ClarificationDelivery, key)
                if row is None:
                    return None
                stream_id = row.stream_id
            else:
                stream_id = self.store._stream_id(stream, "delivery.stream")
            loaded = self.store._existing(session, stream_id)
            send_id = loaded.deliveries.get(key)
            return None if send_id is None else loaded.sends[send_id]

        return self.store._attempt(step)

    def send(self, send_id: str, *, stream: StreamKey) -> SendRecord:
        return self.store._attempt(lambda session: self._send(session, send_id, stream, lock=False).sends[send_id])


def _ingress_fields(ingress: PulledIngress) -> dict[str, Any]:
    _require(type(ingress) is PulledIngress and type(ingress.transport) is TransportNamespace,
             RefusalCode.MALFORMED, "ingress.type", "ingress")
    _require(type(ingress.update_id) is int and ingress.update_id >= 0
             and (ingress.offset is None or type(ingress.offset) is int),
             RefusalCode.MALFORMED, "ingress.numbers", "ingress")
    digest = ingress.update_sha256
    _require(digest is None or (type(digest) is str and len(digest) == 64
                               and all(c in "0123456789abcdef" for c in digest)),
             RefusalCode.MALFORMED, "ingress.update_digest", "ingress")
    return {"transport": ingress.transport.transport, "bot_id": ingress.transport.bot_id,
            "update_id": ingress.update_id, "update_sha256": digest, "offset": ingress.offset}


def _capture(ingress: PulledIngress, receipt: ActionReceipt, validation: ReceiptValidation) -> tuple[dict[str, Any], str]:
    fields = _ingress_fields(ingress)
    _require(type(receipt) is ActionReceipt and type(validation) is ReceiptValidation,
             RefusalCode.MALFORMED, "ingress.receipt_type", "receipt/validation")
    digest = _encodable(lambda: receipt_sha256(receipt), "receipt")
    _require(ingress.transport == receipt.action.transport and ingress.update_id == receipt.update_id
             and validation.receipt_sha256 == digest,
             RefusalCode.BINDING_MISMATCH, "ingress.receipt", "receipt/validation")
    return fields, digest


def _stage_ingress(store: ClarificationStore, session: Session, stream_id: str, fields: dict[str, Any],
                   *, receipt: ActionReceipt | None, digest: str | None, capture_status: str,
                   capture_code: RefusalCode | None, capture_guard: str | None,
                   outcome: IngressAppendResult | None, diagnostic: tuple[RefusalCode, str] | None) -> bool:
    refusal_id = None
    if receipt is not None and diagnostic is not None:
        # Flush the staged refusal (never commit it alone) to obtain its identity.
        session.flush()
        refusal_id = session.exec(select(ClarificationRefusal.id).where(
            col(ClarificationRefusal.receipt_sha256) == digest,
            col(ClarificationRefusal.code) == diagnostic[0].value,
            col(ClarificationRefusal.guard) == diagnostic[1],
        )).one()
    row = ClarificationIngress(
        ingress_id="", stream_id=stream_id, **fields, receipt_sha256=digest,
        action_key=None if receipt is None else receipt.action.key,
        capture_status=capture_status, capture_code=None if capture_code is None else capture_code.value,
        capture_guard=capture_guard, result_json=None if outcome is None else _result_text(outcome.result),
        result_guard=None if outcome is None else outcome.guard, refusal_id=refusal_id,
        diagnostic_code=None if diagnostic is None else diagnostic[0].value,
        diagnostic_guard=None if diagnostic is None else diagnostic[1],
    )
    row.ingress_id = _ingress_digest(row)
    if session.get(ClarificationIngress, row.ingress_id) is None:
        revision = cast(int, store._revision(session, stream_id))
        store._cas(session, stream_id, revision, adds="ingress")
        session.add(row)
        return True
    return False


def append_with_ingress(store: ClarificationStore, ingress: PulledIngress, receipt: ActionReceipt,
                        validation: ReceiptValidation) -> IngressAppendResult:
    fields, digest = _capture(ingress, receipt, validation)
    stream_id = receipt.binding.stream_id

    def step(session: Session) -> IngressAppendResult:
        _locked(store, session, stream_id)
        outcome = store._append(session, receipt, digest, restrict_replay_to_receipt_stream=True)
        diagnostic = ((cast(RefusalCode, outcome.result.code), cast(str, outcome.guard))
                      if outcome.result.status == "refused" else None)
        added = _stage_ingress(store, session, stream_id, fields, receipt=receipt, digest=digest,
                               capture_status=validation.status, capture_code=validation.code,
                               capture_guard=validation.guard, outcome=outcome, diagnostic=diagnostic)
        if not added and not outcome.new:
            session.rollback()
        else:
            store._commit_receipt(session, outcome)
        return outcome

    return store._attempt(step)


def keep_refusal(store: ClarificationStore, stream: StreamKey, refusal: Refusal) -> None:
    _require(type(refusal) is Refusal and type(refusal.code) is RefusalCode and refusal.code in REFUSED_CODES
             and type(refusal.guard) is str
             and bool(refusal.guard.strip()), RefusalCode.MALFORMED, "ingress.refusal_type", "refusal")
    fields = _ingress_fields(refusal.ingress)
    receipt = refusal.receipt
    digest = refusal.receipt_sha256
    if receipt is not None:
        digest = _encodable(lambda: receipt_sha256(receipt), "receipt")
        _require(refusal.receipt_sha256 == digest and receipt.binding.stream_id == stream.stream_id
                 and receipt.action.transport == refusal.ingress.transport and receipt.update_id == refusal.ingress.update_id,
                 RefusalCode.BINDING_MISMATCH, "ingress.refusal_receipt", "refusal")
    else:
        _require(digest is None, RefusalCode.MALFORMED, "ingress.refusal_digest", "refusal")

    def step(session: Session) -> None:
        loaded = _locked(store, session, stream.stream_id)
        # The typed final-refusal bridge calls M2's existing _refuse. Do not
        # re-label its original capture verdict or add a second observation.
        observed = session.exec(select(ClarificationIngress).where(
            col(ClarificationIngress.stream_id) == stream.stream_id,
        )).all()
        if any(all(getattr(r, key) == value for key, value in fields.items())
               and r.receipt_sha256 == digest and r.diagnostic_code == refusal.code.value
               and r.diagnostic_guard == refusal.guard for r in observed):
            session.rollback()
            return
        outcome = None if receipt is None else store._refuse(
            session, receipt, cast(str, digest), loaded.stream_id, loaded.revision, refusal.code, refusal.guard,
        )
        _stage_ingress(store, session, loaded.stream_id, fields, receipt=receipt, digest=digest,
                       capture_status="refused", capture_code=refusal.code, capture_guard=refusal.guard,
                       outcome=outcome, diagnostic=(refusal.code, refusal.guard))
        store._commit(session, lambda again: False)

    store._attempt(step)


def mark_current_consumed(store: ClarificationStore, stream: StreamKey, *, revision: int,
                          record_sha256: str, identity: str, original_brief: str) -> bool:
    stream_id = store._stream_id(stream, "mark_current_consumed.stream")

    def step(session: Session) -> bool:
        loaded = _locked(store, session, stream_id)
        supplement = store._composed(loaded, revision, original_brief)
        _require(record_sha256 == supplement.record_sha256 and identity == supplement.consumption_id,
                 RefusalCode.HASH_MISMATCH, "consume.identity", "record_sha256/consumption_id")
        if supplement.consumed:
            session.rollback()
            return False
        check_expected_revision(revision, loaded.revision)
        return store._record_consumption(session, loaded, supplement)

    return store._attempt(step, retry_revision_conflict=False)
