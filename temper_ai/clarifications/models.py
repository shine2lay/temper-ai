"""What the clarification store keeps (Temper #207, plan #202 unit M3).

Seven additive tables, written only through ``ClarificationStore``
(store.py) and never edited by hand. Nothing here changes an existing table.

``clarification_streams``: one row per stream, a context namespace plus one
original brief (``StreamKey``). Its ``revision`` is the compare-and-set
revision: every change moves it by exactly 1, inside the same transaction
that writes the change, and only from the revision the change was computed
on. Its four counts move with every receipt, presentation, copy and
consumption kept for the stream, so a lost row shows even when nothing else
names it (a retained receipt, the newest presentation).

``clarification_revisions``: one immutable row per revision, holding that
revision's whole #308 foundation record, its digest and the digest of the
revision before it. The rows are the history: revision 1 is the first
record, and each later row adds exactly one event or one record change to
the row before it. A revision with no consumption row is the pending
consumption intent (``clarification_consumptions``).

``clarification_receipts``: one row per authenticated action identity
(``ActionIdentity.key``) whose receipt was applied or retained, with the
exact canonical receipt JSON (``contracts.receipt_json``), its digest and
the result returned for it. Only applied or retained receipts take a key:
a refused one never does (Security #176 N1).

``clarification_refusals``: a diagnostic row per refused attempt, kept under
the receipt's digest with its code and guard. It keeps no text and no
sender, and it never takes the action key.

``clarification_presentations`` and ``clarification_copies``: the persisted
presentations (one generation per question at a time) and the message IDs
each was delivered as. A receipt is validated only against these rows.

``clarification_consumptions``: one row per consumed (stream, revision,
supplement), keyed by ``contracts.consumption_id``, so a second consumption
of the same revision is a no-op.

Times carry UTC, like every other time temper stores (shared/clock.py).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from temper_ai.shared.clock import utcnow

__all__ = [
    "ClarificationConsumption",
    "ClarificationCopy",
    "ClarificationPresentation",
    "ClarificationReceipt",
    "ClarificationRefusal",
    "ClarificationRevision",
    "ClarificationStream",
    "TABLES",
]


class ClarificationStream(SQLModel, table=True):
    __tablename__ = "clarification_streams"

    stream_id: str = Field(primary_key=True)    # s-<sha256> of (namespace, brief_sha256)
    namespace: str
    brief_sha256: str
    source_authority_ref: str                    # fixed at creation; another authority is refused
    revision: int                                # moves by exactly 1, by compare-and-set only
    record_sha256: str                           # the latest revision's record digest
    receipt_count: int = 0                       # receipts kept: applied plus retained
    presentation_count: int = 0
    copy_count: int = 0
    consumption_count: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ClarificationRevision(SQLModel, table=True):
    __tablename__ = "clarification_revisions"

    stream_id: str = Field(primary_key=True)
    revision: int = Field(primary_key=True)      # 1, 2, 3... with no gap
    change: str                                  # record | event
    record_json: str = Field(sa_column=Column(Text, nullable=False))  # canonical foundation record
    record_sha256: str
    previous_record_sha256: str = ""             # "" for revision 1
    event_id: str | None = None                  # change == event: the one event it adds
    action_key: str | None = None                # change == event: the receipt that carried it
    created_at: datetime = Field(default_factory=utcnow)


class ClarificationReceipt(SQLModel, table=True):
    __tablename__ = "clarification_receipts"

    action_key: str = Field(primary_key=True)    # a-<sha256>: the immutable transport/action identity
    stream_id: str = Field(index=True)
    receipt_sha256: str = Field(index=True)
    receipt_json: str = Field(sa_column=Column(Text, nullable=False))  # exact canonical receipt
    status: str                                  # applied | retained
    code: str | None = None                      # retained: its closed code
    guard: str | None = None                     # retained: the guard that decided it
    event_id: str | None = None                  # applied: the event it added
    expected_revision: int                       # the revision it was decided on
    revision: int                                # applied: expected + 1; retained: expected
    created_at: datetime = Field(default_factory=utcnow)


class ClarificationRefusal(SQLModel, table=True):
    __tablename__ = "clarification_refusals"
    __table_args__ = (
        UniqueConstraint("receipt_sha256", "code", "guard", name="uq_clarification_refusal"),
    )

    id: int | None = Field(default=None, primary_key=True)
    receipt_sha256: str
    action_key: str = Field(index=True)          # never unique: a refusal holds no key
    stream_id: str = Field(index=True)           # the stream the receipt names; it may not exist
    code: str
    guard: str
    created_at: datetime = Field(default_factory=utcnow)


class ClarificationPresentation(SQLModel, table=True):
    __tablename__ = "clarification_presentations"
    __table_args__ = (
        UniqueConstraint("stream_id", "question_id", "generation", name="uq_clarification_presentation"),
    )

    presentation_id: str = Field(primary_key=True)  # p-<sha256> of the whole presentation
    stream_id: str = Field(index=True)
    namespace: str
    brief_sha256: str
    question_id: str
    metadata_sha256: str
    generation: int                              # 1, 2, 3... per question; the newest is current
    responder_policy_ref: str
    transport: str
    bot_id: str
    chat_id: str
    created_at: datetime = Field(default_factory=utcnow)


class ClarificationCopy(SQLModel, table=True):
    __tablename__ = "clarification_copies"

    presentation_id: str = Field(primary_key=True)
    message_id: str = Field(primary_key=True)    # a delivered copy of the presentation
    stream_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)


class ClarificationConsumption(SQLModel, table=True):
    __tablename__ = "clarification_consumptions"

    consumption_id: str = Field(primary_key=True)  # c-<sha256> of (stream, revision, supplement digest)
    stream_id: str = Field(index=True)
    revision: int
    supplement_sha256: str
    record_sha256: str
    created_at: datetime = Field(default_factory=utcnow)


# The store's tables, for code that creates or empties exactly these (tests).
TABLES = tuple(
    model.__table__  # type: ignore[union-attr]
    for model in (
        ClarificationStream, ClarificationRevision, ClarificationReceipt, ClarificationRefusal,
        ClarificationPresentation, ClarificationCopy, ClarificationConsumption,
    )
)
