"""Scope-bound implementation of M2's entire synchronous durable store port.

Construction performs no I/O. The embedding application supplies authority,
stream and references; none is discovered or granted here. This is a trusted
Python binding, not a sandbox or a real retention/reconciliation policy.
"""

from __future__ import annotations

from typing import Literal, cast

from temper_ai.clarifications.caller_contracts import ClarificationAuthority
from temper_ai.clarifications.contracts import (
    ActionReceipt,
    Presentation,
    ReceiptValidation,
    RefusalCode,
    StreamKey,
    TransportNamespace,
)
from temper_ai.clarifications.delivery_store import (
    ClarificationDeliveryStore,
    keep_refusal,
)
from temper_ai.clarifications.store import ClarificationStore, ProtocolView, _require
from temper_ai.integrations.telegram.clarifications import (
    PulledIngress,
    ReceiptApplicationRefusal,
    Refusal,
    SendIntent,
    SendRecord,
)


class TelegramClarificationStore:
    """One explicitly authorized stream; reads and writes use the same checked store."""

    def __init__(self, store: ClarificationStore, delivery: ClarificationDeliveryStore, *,
                 authority: ClarificationAuthority, stream: StreamKey,
                 source_authority_ref: str, responder_policy_ref: str) -> None:
        _require(authority is not None and callable(getattr(authority, "require", None)),
                 RefusalCode.MISSING_AUTHORITY, "telegram_store.authority", "authority")
        _require(type(stream) is StreamKey and type(source_authority_ref) is str and bool(source_authority_ref)
                 and type(responder_policy_ref) is str and bool(responder_policy_ref),
                 RefusalCode.MISSING_BINDING, "telegram_store.binding", "stream/references")
        _require(delivery.store is store, RefusalCode.CROSS_CONTEXT, "telegram_store.same_store", "delivery")
        self.store, self.ledger, self.authority = store, delivery, authority
        self.stream = stream
        self.source_authority_ref, self.responder_policy_ref = source_authority_ref, responder_policy_ref

    def _view(self, *operations: Literal["read", "write", "send", "acknowledge"]) -> ProtocolView:
        for operation in ("read", *operations):
            self.authority.require(operation=operation, stream=self.stream,
                                   source_authority_ref=self.source_authority_ref,
                                   responder_policy_ref=self.responder_policy_ref)
        view = self.store.protocol_view(self.stream)
        _require(view.source_authority_ref == self.source_authority_ref,
                 RefusalCode.CROSS_CONTEXT, "telegram_store.source", "source_authority_ref")
        return view

    def _stream(self, stream_id: str) -> None:
        _require(stream_id == self.stream.stream_id, RefusalCode.CROSS_CONTEXT,
                 "telegram_store.stream", "stream_id")

    def _presentation(self, presentation: Presentation) -> None:
        self._stream(presentation.stream.stream_id)
        _require(presentation.responder_policy_ref == self.responder_policy_ref,
                 RefusalCode.CROSS_CONTEXT, "telegram_store.policy", "responder_policy_ref")

    def _receipt_scope(self, view: ProtocolView, receipt: ActionReceipt) -> None:
        self._stream(receipt.binding.stream_id)
        presentation = next((p for p in view.presentations if p.presentation_id == receipt.binding.presentation_id), None)
        _require(presentation is not None, RefusalCode.MISSING_BINDING,
                 "telegram_store.presentation", "presentation_id")
        self._presentation(cast(Presentation, presentation))

    def save_send(self, intent: SendIntent) -> SendRecord:
        self._view("write", "send")
        self._presentation(intent.presentation)
        return self.ledger.save_send(intent)

    def start_attempt(self, send_id: str, *, expected_attempts: int, resend: bool) -> tuple[SendRecord, bool]:
        self._view("write", "send")
        self._presentation(self.ledger.send(send_id, stream=self.stream).intent.presentation)
        return self.ledger.start_attempt(send_id, expected_attempts=expected_attempts, resend=resend, stream=self.stream)

    def record_delivery(self, send_id: str, message_id: str) -> SendRecord:
        """Supplied verified completion/reconciliation only; no history lookup or implied grant."""
        self._view("write", "send")
        self._presentation(self.ledger.send(send_id, stream=self.stream).intent.presentation)
        return self.ledger.record_delivery(send_id, message_id, stream=self.stream)

    def delivery(self, transport: TransportNamespace, chat_id: str, message_id: str) -> SendRecord | None:
        self._view()
        found = self.ledger.delivery(transport, chat_id, message_id, stream=self.stream)
        if found is not None:
            self._presentation(found.intent.presentation)
        return found

    def copies(self, presentation_id: str) -> frozenset[str]:
        view = self._view()
        presentation = next((p for p in view.presentations if p.presentation_id == presentation_id), None)
        if presentation is None:
            return frozenset()
        self._presentation(presentation)
        return frozenset(c.message_id for c in view.copies if c.presentation_id == presentation_id)

    def current_generation(self, stream_id: str, question_id: str) -> int:
        self._stream(stream_id)
        view = self._view()
        return max((p.generation for p in view.presentations if p.question_id == question_id), default=0)

    def question_ids(self, stream_id: str) -> frozenset[str]:
        self._stream(stream_id)
        return self._view().question_ids

    def answered(self, stream_id: str, question_id: str) -> bool:
        self._stream(stream_id)
        return question_id in self._view().answered

    def receipt(self, action_key: str) -> ActionReceipt | None:
        view = self._view()
        found = next((r for r in view.receipts if r.action.key == action_key), None)
        if found is not None:
            self._receipt_scope(view, found)
        return found

    def keep_receipt(self, ingress: PulledIngress, receipt: ActionReceipt,
                     validation: ReceiptValidation) -> tuple[ActionReceipt, bool]:
        view = self._view("write")
        self._receipt_scope(view, receipt)
        outcome = self.store.append_receipt_with_ingress(ingress, receipt, validation)
        if outcome.result.status == "refused":
            # Raised only after the store returned its committed diagnostic.
            raise ReceiptApplicationRefusal(cast(RefusalCode, outcome.result.code),
                                            cast(str, outcome.guard), "receipt.application")
        return cast(ActionReceipt, outcome.held), outcome.new

    def keep_refusal(self, refusal: Refusal) -> None:
        view = self._view("write")
        if refusal.receipt is not None:
            self._receipt_scope(view, refusal.receipt)
        _require(any(p.transport == refusal.ingress.transport and p.responder_policy_ref == self.responder_policy_ref
                     for p in view.presentations), RefusalCode.TRANSPORT_MISMATCH,
                 "telegram_store.ingress", "ingress.transport")
        keep_refusal(self.store, self.stream, refusal)
