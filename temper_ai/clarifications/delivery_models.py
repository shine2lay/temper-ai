"""Additive delivery/ingress rows in the clarification store's SAME database.

No provider calls, raw updates, second receipt history or authority defaults.
See docs/clarifications/delivery.md for the data/integrity inventory. Fresh
fixtures only: create_all does not migrate an existing pre-extension schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from temper_ai.clarifications.contracts import ActionReceipt, AppendResult
from temper_ai.shared.clock import utcnow


@dataclass(frozen=True, slots=True)
class IngressAppendResult:
    """The committed application decision, not the earlier capture validation."""

    result: AppendResult
    guard: str | None
    held: ActionReceipt | None
    new: bool


class ClarificationSend(SQLModel, table=True):
    __tablename__ = "clarification_sends"

    send_id: str = Field(primary_key=True)
    stream_id: str = Field(index=True)
    presentation_id: str = Field(index=True)
    intent_json: str = Field(sa_column=Column(Text, nullable=False))
    intent_sha256: str
    attempt_count: int = 0  # send admissions, not workflow run-generation attempts
    message_id: str | None = None
    state_sha256: str  # binds identity, immutable intent digest and mutable state
    created_at: datetime = Field(default_factory=utcnow)


class ClarificationDelivery(SQLModel, table=True):
    __tablename__ = "clarification_deliveries"

    transport: str = Field(primary_key=True)
    bot_id: str = Field(primary_key=True)
    chat_id: str = Field(primary_key=True)
    message_id: str = Field(primary_key=True)
    stream_id: str = Field(index=True)
    send_id: str = Field(index=True)
    presentation_id: str
    delivery_sha256: str
    created_at: datetime = Field(default_factory=utcnow)


class ClarificationIngress(SQLModel, table=True):
    __tablename__ = "clarification_ingresses"

    ingress_id: str = Field(primary_key=True)  # digest of all non-body observation/linkage fields
    stream_id: str = Field(index=True)
    transport: str
    bot_id: str
    update_id: int
    update_sha256: str | None = None
    offset: int | None = None
    receipt_sha256: str | None = None
    action_key: str | None = Field(default=None, index=True)  # NON-unique diagnostic linkage
    capture_status: str
    capture_code: str | None = None
    capture_guard: str | None = None
    result_json: str | None = None  # AppendResult only: never receipt/answer JSON
    result_guard: str | None = None
    refusal_id: int | None = None  # existing M3 diagnostic; None if no receipt was constructible
    diagnostic_code: str | None = None
    diagnostic_guard: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


TABLES = tuple(
    model.__table__  # type: ignore[union-attr]
    for model in (ClarificationSend, ClarificationDelivery, ClarificationIngress)
)
