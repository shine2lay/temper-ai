"""The clarification store: one revision-checked history per stream (Temper #207, plan #202 unit M3).

The tables are in models.py; docs/clarifications/storage.md says how they
are used. In short:

- One stream per context namespace and original brief (contracts.StreamKey).
  Its history is a chain of immutable revisions, each a whole, valid #308
  foundation record that adds exactly one event or one record change to the
  revision before it.
- Every change is one transaction per attempt, in this order: read the
  stream and its whole history and check it; check the receipt's identity
  and content against what is kept; validate its binding; append its event
  to the LATEST record; then compare-and-set the stream's revision from the
  revision all of that was decided on, insert the revision (which is also
  the pending-consumption intent) and the receipt, and commit. A method
  returns only after its commit. An attempt that loses a race is rolled back
  and decided again on the new latest record: nothing is ever written from a
  stale snapshot.
- Only an applied or retained receipt occupies the unique authoritative action
  key. A refusal keeps linkable diagnostic identifiers (including a non-unique
  action-key digest), but never occupies that receipt key (Security #176 N1).
- An identical replay returns the kept result and changes nothing. The same
  action key with other content is refused (changed_body); history is
  unchanged.
- Detected history inconsistencies raise ClarificationIntegrityError, never
  a fresh record. Checks cover records, receipts, immutable saved results,
  delivered-copy tuples, links and counts, not every stored field:
  source-authority refs and timestamps can change undetected. Refusal
  diagnostics are outside the history checks.
  DB writers are trusted; unkeyed digests cannot authenticate a consistent
  rewrite, complete deletion or rollback. See the storage guide's inventory.

The store opens no reference, signals and resumes nothing, and keeps nothing
outside its tables. D3: no real answer may be kept here before the owner's
retention decision; its tests use synthetic data only.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

from sqlalchemy import Engine, func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from temper_ai.clarifications.contracts import (
    FOUNDATION_CONTRACT,
    RECEIPT_REF_SCHEME,
    RETAINED_CODES,
    VERIFIED_INGRESS,
    ActionReceipt,
    AppendResult,
    CallerInput,
    ContractRefusal,
    Presentation,
    PresentationBinding,
    RefusalCode,
    StreamKey,
    TransportNamespace,
    check_confirmation_precondition,
    check_correction_precondition,
    check_expected_revision,
    check_reopen_precondition,
    check_replay,
    consumption_id,
    metadata_sha256,
    receipt_from_json,
    receipt_json,
    receipt_sha256,
    validate_receipt,
)
from temper_ai.clarifications.delivery_models import (
    ClarificationDelivery,
    ClarificationIngress,
    ClarificationSend,
    IngressAppendResult,
)
from temper_ai.clarifications.models import (
    ClarificationConsumption,
    ClarificationCopy,
    ClarificationPresentation,
    ClarificationReceipt,
    ClarificationRefusal,
    ClarificationRevision,
    ClarificationStream,
)
from temper_ai.shared.clock import utcnow

__all__ = [
    "FOUNDATION_PATH",
    "ClarificationIntegrityError",
    "ClarificationStore",
    "RecordResult",
    "StoredStream",
    "Supplement",
    "load_foundation",
]

if TYPE_CHECKING:
    from temper_ai.clarifications.contracts import ReceiptValidation
    from temper_ai.integrations.telegram.clarifications import PulledIngress, SendRecord

T = TypeVar("T")
_RowKind = Literal["receipt", "presentation", "copy", "consumption", "send", "delivery", "ingress"]

FOUNDATION_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "architecture" / "bin" / "context_profile_clarifications.py"
)


class ClarificationIntegrityError(RuntimeError):
    """A history consistency check failed. Never answered with a fresh record.

    guard names the check that failed; detail names the exact revision,
    receipt or row, so the accountable lead can recover it. Nothing was
    written. This is not authentication of DB writers or all-field damage
    detection; docs/clarifications/storage.md inventories unchecked metadata.
    """

    def __init__(self, stream_id: str, guard: str, detail: str) -> None:
        super().__init__(f"{stream_id}: {detail} [{guard}]")
        self.stream_id = stream_id
        self.guard = guard
        self.detail = detail


class _Retry(Exception):
    """Another writer committed between this attempt's reads and its write: decide again."""


@dataclass(frozen=True, slots=True)
class RecordResult:
    """The stream's latest record after merge_candidate. changed: this call added a revision."""

    stream_id: str
    revision: int
    record_json: str
    record_sha256: str
    changed: bool


@dataclass(frozen=True, slots=True)
class StoredStream:
    """A stream as recovered after a restart, its whole history checked first."""

    stream: StreamKey
    source_authority_ref: str
    revision: int
    record_json: str
    record_sha256: str
    presentations: tuple[Presentation, ...]  # each presented question's current generation, by question ID
    copies: tuple[PresentationBinding, ...]  # the delivered copies of those presentations
    pending_revision: int | None             # the latest revision, while nothing has consumed it

    def record(self) -> dict[str, Any]:
        """A fresh parse of the latest record."""
        return cast(dict[str, Any], json.loads(self.record_json))


@dataclass(frozen=True, slots=True)
class ProtocolView:
    """Detached checked protocol state, including retired presentation membership."""

    source_authority_ref: str
    question_ids: frozenset[str]
    answered: frozenset[str]
    presentations: tuple[Presentation, ...]
    copies: tuple[PresentationBinding, ...]
    receipts: tuple[ActionReceipt, ...]


@dataclass(frozen=True, slots=True)
class Supplement:
    """One revision's supplement as the foundation composes it, with its consumption identity."""

    stream_id: str
    revision: int
    consumption_id: str
    supplement_sha256: str
    record_sha256: str
    original_brief: str
    supplement: str
    source_mapping: dict[str, Any]
    consumed: bool


def _canonical(value: object) -> str:
    """The canonical JSON M0 and the foundation both use: what every digest here is over."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require(ok: bool, code: RefusalCode, guard: str, where: str) -> None:
    """The store's refusal primitive: a closed M0 code; nothing was written."""
    if not ok:
        raise ContractRefusal(code, guard, where)


def _intact(ok: bool, stream_id: str, guard: str, detail: str) -> None:
    """The store's integrity primitive: a specified consistency check failed."""
    if not ok:
        raise ClarificationIntegrityError(stream_id, guard, detail)


def _encodable(compute: Callable[[], T], where: str) -> T:
    """Compute an ID or digest; text that has no UTF-8 form (a lone surrogate) is malformed."""
    try:
        return compute()
    except UnicodeEncodeError as error:
        raise ContractRefusal(RefusalCode.MALFORMED, "store.utf8", where) from error


def _metadata(question: dict[str, Any]) -> dict[str, Any]:
    """A record question's unknown metadata: everything but its ID."""
    return {key: value for key, value in question.items() if key != "question_id"}


def _saved_result_sha256(row: ClarificationReceipt) -> str:
    """Bind every immutable decision field and its receipt identity, not mutable metadata or DB writers."""
    return _sha256(_canonical({
        "action_key": row.action_key, "stream_id": row.stream_id, "receipt_sha256": row.receipt_sha256,
        "status": row.status, "code": row.code, "guard": row.guard, "event_id": row.event_id,
        "expected_revision": row.expected_revision, "revision": row.revision,
    }))


def _copy_sha256(row: ClarificationCopy) -> str:
    """The immutable delivered-copy tuple; checked before this membership can validate a receipt."""
    return _sha256(_canonical({
        "presentation_id": row.presentation_id, "message_id": row.message_id, "stream_id": row.stream_id,
    }))


def load_foundation(path: Path = FOUNDATION_PATH) -> ModuleType:
    """Import the #308 foundation module from its file under configs/ (not a package).

    Refuses (ImportError) a module that is not the foundation contract M0 binds to.
    """
    spec = importlib.util.spec_from_file_location("temper_clarifications_foundation", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"no clarification foundation at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if getattr(module, "CONTRACT", None) != FOUNDATION_CONTRACT:
        raise ImportError(f"{path} is not {FOUNDATION_CONTRACT}")
    return module


@cache
def _shared_foundation() -> ModuleType:
    return load_foundation()


@dataclass(frozen=True, slots=True)
class _ReceiptOwner:
    """Metadata-only ownership projection; replay routing must not read a foreign body."""

    stream_id: str


@dataclass(slots=True)
class _Loaded:
    """One stream as read and checked inside one attempt."""

    row: ClarificationStream
    stream: StreamKey
    revisions: list[ClarificationRevision]
    records: list[dict[str, Any]]                # records[i] is revision i + 1
    receipts: dict[str, ClarificationReceipt]    # by action key
    parsed: dict[str, ActionReceipt]             # the same receipts, parsed from their exact JSON
    presentations: dict[str, Presentation]       # by presentation ID
    copies: dict[str, frozenset[str]]            # message IDs by presentation ID
    consumed: frozenset[str]                     # consumption IDs
    consumed_revisions: frozenset[int]
    sends: dict[str, SendRecord] = field(default_factory=dict)
    deliveries: dict[tuple[str, str, str, str], str] = field(default_factory=dict)

    @property
    def stream_id(self) -> str:
        return self.row.stream_id

    @property
    def revision(self) -> int:
        return self.row.revision

    @property
    def record(self) -> dict[str, Any]:
        return self.records[-1]

    def question_ids(self) -> tuple[str, ...]:
        return tuple(question["question_id"] for question in self.record["questions"])

    def question(self, question_id: str) -> dict[str, Any] | None:
        return next((q for q in self.record["questions"] if q["question_id"] == question_id), None)

    def generation(self, question_id: str) -> int:
        """The question's current presentation generation; 0 before its first."""
        return max((p.generation for p in self.presentations.values() if p.question_id == question_id), default=0)

    def answer_actors(self, question_id: str) -> dict[str, str]:
        """Every human answer event of one question, with its actor: what a correction may name."""
        return {
            event["event_id"]: event["actor"]["ref"] for event in self.record["events"]
            if event["question_id"] == question_id and event["kind"] == "answer" and event["actor"]["kind"] == "human"
        }

    def confirmed_actions(self) -> frozenset[str]:
        """Typed messages whose text was already applied: directly, or by an applied press confirming it."""
        done = set()
        for key, row in self.receipts.items():
            if row.status != "applied":
                continue
            receipt = self.parsed[key]
            if receipt.confirms is not None:
                done.add(receipt.confirms.action.key)
            elif receipt.action.kind == "message":
                done.add(key)
        return frozenset(done)


class ClarificationStore:
    """Keeps clarification streams in temper's database, one revision-checked history each.

    Every public method runs in one transaction per attempt and returns only
    after its commit, or after deciding that nothing needs writing. An attempt
    that loses a race is rolled back and decided again on the latest committed
    state, for as long as other writers keep committing: each retry means
    another change landed first.
    """

    def __init__(self, engine: Engine, *, foundation: ModuleType | None = None) -> None:
        self._engine = engine
        self._foundation = foundation if foundation is not None else _shared_foundation()

    # --- public -----------------------------------------------------------------

    def merge_candidate(self, caller: CallerInput) -> RecordResult:
        """Create the stream's record from a candidate, or merge the candidate's new questions into its LATEST record.

        Merging onto the latest record, never onto the caller's older prior
        one, is what keeps a slow caller from writing a stale snapshot: the
        foundation's create_record only ever adds questions and keeps every
        event. Refused, with nothing written: a prior revision the stream
        never had, or one claimed for a stream that does not exist
        (missing_record); a prior record whose digest is not that stored
        revision's (hash_mismatch); another source authority (cross_context);
        a candidate the foundation refuses (malformed).
        """
        _require(type(caller) is CallerInput, RefusalCode.MALFORMED, "store.caller_type", "merge_candidate.caller")

        def stored_text() -> str:  # everything the stream row keeps from the caller must have a UTF-8 form
            _sha256(cast(str, caller.source_authority_ref))
            return caller.stream.stream_id

        stream_id = _encodable(stored_text, "merge_candidate.caller")
        return self._attempt(lambda session: self._merge_candidate(session, caller, stream_id))

    def save_presentation(self, presentation: Presentation) -> bool:
        """Persist a presentation before it is sent. True when it was new; the same one again changes nothing.

        A question's generations are 1, 2, 3...: saving generation g + 1
        retires generation g, and late answers to g are retained as stale.
        """
        _require(
            type(presentation) is Presentation, RefusalCode.MALFORMED, "store.presentation_type",
            "save_presentation.presentation",
        )
        presentation_id = _encodable(lambda: presentation.presentation_id, "save_presentation.presentation")
        return self._attempt(lambda session: self._save_presentation(session, presentation, presentation_id))

    def record_copy(self, binding: PresentationBinding) -> bool:
        """Record that a saved presentation was delivered as one transport message. True when new."""
        _require(type(binding) is PresentationBinding, RefusalCode.MALFORMED, "store.binding_type", "record_copy.binding")
        return self._attempt(lambda session: self._record_copy(session, binding))

    def append_receipt(self, receipt: ActionReceipt) -> AppendResult:
        """Validate one authenticated receipt against the kept stream and keep it, in one transaction.

        applied: its human event was appended to the LATEST record as revision
        N + 1, together with the receipt, by the transaction that moved the
        revision. retained: kept under its action key as evidence; nothing
        applied. refused: a diagnostic with linkable IDs, not receipt text;
        the authoritative key stays free. A receipt whose key is already kept gets the kept result back
        when identical (a replay) and is refused as changed_body otherwise.
        """
        _require(type(receipt) is ActionReceipt, RefusalCode.MALFORMED, "store.receipt_type", "append_receipt.receipt")
        digest = _encodable(lambda: receipt_sha256(receipt), "append_receipt.receipt")
        return self._attempt(lambda session: self._append_committed(session, receipt, digest)).result

    def append_receipt_with_ingress(
        self, ingress: PulledIngress, receipt: ActionReceipt, validation: ReceiptValidation,
    ) -> IngressAppendResult:
        """Commit the current-state append decision and non-body pull linkage together.

        Capture validation is evidence, not a command. Refused outcomes contain
        no held receipt; callers must not describe them as successful replays.
        """
        from temper_ai.clarifications.delivery_store import append_with_ingress

        return append_with_ingress(self, ingress, receipt, validation)

    def protocol_view(self, stream: StreamKey) -> ProtocolView:
        """Checked questions, receipts and ALL historical presentations/copies, without a write."""
        stream_id = self._stream_id(stream, "protocol_view.stream")
        return self._attempt(lambda session: self._protocol_view(self._existing(session, stream_id)))

    def mark_current_consumed(
        self, stream: StreamKey, *, revision: int, record_sha256: str,
        consumption_id: str, original_brief: str,
    ) -> bool:
        """Exact kept ack first; otherwise require the current revision and exact identities."""
        from temper_ai.clarifications.delivery_store import mark_current_consumed

        return mark_current_consumed(
            self, stream, revision=revision, record_sha256=record_sha256,
            identity=consumption_id, original_brief=original_brief,
        )

    def load(self, stream: StreamKey) -> StoredStream | None:
        """Recover a stream with history consistency checks. None: no authoritative/history rows remain.

        Detected inconsistencies raise ClarificationIntegrityError, not an
        empty stream. Complete deletion is indistinguishable from no creation;
        unchecked metadata and consistent rewrites/rollbacks are not authenticated.
        """
        stream_id = self._stream_id(stream, "load.stream")
        return self._attempt(lambda session: self._recover(session, stream_id))

    def supplement(self, stream: StreamKey, *, revision: int, original_brief: str) -> Supplement:
        """Compose one revision's supplement and its consumption identity. Writes and signals nothing."""
        stream_id = self._stream_id(stream, "supplement.stream")
        return self._attempt(lambda session: self._composed(self._existing(session, stream_id), revision, original_brief))

    def mark_consumed(self, stream: StreamKey, *, revision: int, original_brief: str) -> bool:
        """Record that one revision's supplement was consumed. True the first time; a repeat changes nothing.

        Keeping an answer never resumes anything: the consumer decides, and this records only that it did.
        """
        stream_id = self._stream_id(stream, "mark_consumed.stream")
        return self._attempt(lambda session: self._mark_consumed(session, stream_id, revision, original_brief))

    # --- transactions -------------------------------------------------------------

    def _attempt(self, step: Callable[[Session], T], *, retry_revision_conflict: bool = True) -> T:
        """Run one step in a fresh session until it commits or decides; a lost race is decided again."""
        while True:
            with Session(self._engine, expire_on_commit=False) as session:
                try:
                    return step(session)
                except _Retry:
                    session.rollback()
                except ContractRefusal as refusal:
                    if not retry_revision_conflict:
                        raise
                    if refusal.code is not RefusalCode.REVISION_CONFLICT:
                        raise
                    session.rollback()

    def _cas(
        self, session: Session, stream_id: str, expected: int, *, adds: _RowKind | None,
        revision: int | None = None, record_sha256: str | None = None,
    ) -> None:
        """Compare-and-set: change the stream row only while it is at the revision the decision was made on.

        A record change or an event moves the row to revision, naming the new
        record's digest; a touch keeps both. adds is the kind of row the same
        transaction adds, so that count moves in this one write. Every column
        it sets is named here, so a reader (or a writer scan) sees all it can
        change. It is the transaction's first write, so the database's own row
        or write lock orders it against every other writer. A miss rolls back,
        and check_expected_revision turns another writer's move into
        revision_conflict: the attempt is decided again on the new record.
        The loaded stream row is left as it was read (synchronize_session off):
        everything after the compare-and-set still describes the revision the
        decision was made on.
        """
        stream = ClarificationStream

        def count(kind: _RowKind, column: Any) -> Any:
            return column + 1 if adds == kind else column

        statement = update(stream).where(
            col(stream.stream_id) == stream_id, col(stream.revision) == expected,
        ).values(
            revision=expected if revision is None else revision,
            record_sha256=col(stream.record_sha256) if record_sha256 is None else record_sha256,
            updated_at=utcnow(),
            receipt_count=count("receipt", col(stream.receipt_count)),
            presentation_count=count("presentation", col(stream.presentation_count)),
            copy_count=count("copy", col(stream.copy_count)),
            consumption_count=count("consumption", col(stream.consumption_count)),
            send_count=count("send", col(stream.send_count)),
            delivery_count=count("delivery", col(stream.delivery_count)),
            ingress_count=count("ingress", col(stream.ingress_count)),
            state_version=col(stream.state_version) + 1,
        ).execution_options(synchronize_session=False)
        if session.exec(statement).rowcount == 1:  # type: ignore[call-overload]
            return
        session.rollback()
        committed = self._revision(session, stream_id)
        if committed is None:
            raise _Retry  # the row is gone: the next read reports what is missing
        check_expected_revision(expected, committed)
        raise ClarificationIntegrityError(
            stream_id, "stream.cas", f"the stream row is at revision {expected} but did not take the change",
        )

    @staticmethod
    def _commit(session: Session, explained: Callable[[Session], bool]) -> None:
        """Commit. A unique-key clash that another writer's commit explains is rolled back and decided again."""
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            if not explained(session):
                raise
            raise _Retry from None

    def _fence(self, session: Session, stream_id: str, question_id: str, generation: int) -> None:
        """After the compare-and-set: a presentation saved since the decision was read makes it stale."""
        if self._generation(session, stream_id, question_id) != generation:
            raise _Retry

    def _create(self, session: Session, caller: CallerInput, stream_id: str, record: dict[str, Any]) -> RecordResult:
        """First creation: the stream row's unique key settles a race; the loser merges onto the winner's record."""
        text = _canonical(record)
        digest = _sha256(text)
        session.add(ClarificationStream(
            stream_id=stream_id, namespace=caller.stream.namespace, brief_sha256=caller.stream.brief_sha256,
            source_authority_ref=cast(str, caller.source_authority_ref), revision=1, record_sha256=digest,
        ))
        session.add(ClarificationRevision(
            stream_id=stream_id, revision=1, change="record", record_json=text, record_sha256=digest,
        ))
        self._commit(session, lambda again: self._revision(again, stream_id) is not None)
        return RecordResult(stream_id, 1, text, digest, changed=True)

    def _add_revision(
        self, session: Session, loaded: _Loaded, record: dict[str, Any], *, change: str,
        event_id: str | None = None, action_key: str | None = None, adds: _RowKind | None = None,
    ) -> ClarificationRevision:
        text = _canonical(record)
        digest = _sha256(text)
        revision = loaded.revision + 1
        previous = loaded.row.record_sha256  # the record this one extends, read before the row moves
        self._cas(session, loaded.stream_id, loaded.revision, adds=adds, revision=revision, record_sha256=digest)
        row = ClarificationRevision(
            stream_id=loaded.stream_id, revision=revision, change=change, record_json=text, record_sha256=digest,
            previous_record_sha256=previous, event_id=event_id, action_key=action_key,
        )
        session.add(row)
        return row

    # --- steps ----------------------------------------------------------------------

    def _merge_candidate(self, session: Session, caller: CallerInput, stream_id: str) -> RecordResult:
        loaded = self._load(session, stream_id)
        if loaded is None:
            _require(caller.prior_revision == 0, RefusalCode.MISSING_RECORD, "store.record_missing", "caller.prior_revision")
            return self._create(session, caller, stream_id, self._candidate_record(caller, None))
        _require(
            caller.source_authority_ref == loaded.row.source_authority_ref, RefusalCode.CROSS_CONTEXT, "store.authority",
            "caller.source_authority_ref",
        )
        _require(
            caller.prior_revision <= loaded.revision, RefusalCode.MISSING_RECORD, "store.prior_revision",
            "caller.prior_revision",
        )
        _require(
            caller.prior_revision == 0
            or loaded.revisions[caller.prior_revision - 1].record_sha256 == caller.prior_record_sha256,
            RefusalCode.HASH_MISMATCH, "store.prior_record", "caller.prior_record_sha256",
        )
        record = self._candidate_record(caller, loaded.record)
        if record == loaded.record:
            latest = loaded.revisions[-1]
            return RecordResult(stream_id, loaded.revision, latest.record_json, latest.record_sha256, changed=False)
        row = self._add_revision(session, loaded, record, change="record")
        self._commit(session, lambda again: self._revision(again, stream_id) != loaded.revision)
        return RecordResult(stream_id, row.revision, row.record_json, row.record_sha256, changed=True)

    def _candidate_record(self, caller: CallerInput, previous: dict[str, Any] | None) -> dict[str, Any]:
        try:
            record = self._foundation.create_record(caller.candidate(), cast(str, caller.original_text), previous=previous)
        except self._foundation.ClarificationError as error:
            raise ContractRefusal(RefusalCode.MALFORMED, "store.candidate", "caller.candidate_json") from error
        return cast(dict[str, Any], record)

    def _save_presentation(self, session: Session, presentation: Presentation, presentation_id: str) -> bool:
        stream_id = presentation.stream.stream_id
        loaded = self._load(session, stream_id)
        if loaded is None:
            raise ContractRefusal(RefusalCode.MISSING_RECORD, "presentation.stream", "presentation.stream")
        question = loaded.question(presentation.question_id)
        if question is None:
            raise ContractRefusal(RefusalCode.UNKNOWN_QUESTION, "presentation.question", "presentation.question_id")
        _require(
            metadata_sha256(_metadata(question)) == presentation.metadata_sha256, RefusalCode.HASH_MISMATCH,
            "presentation.metadata", "presentation.metadata_sha256",
        )
        if presentation_id in loaded.presentations:
            return False
        current = loaded.generation(presentation.question_id)
        _require(
            presentation.generation == current + 1, RefusalCode.BINDING_MISMATCH, "presentation.generation",
            "presentation.generation",
        )
        self._cas(session, stream_id, loaded.revision, adds="presentation")
        session.add(ClarificationPresentation(
            presentation_id=presentation_id, stream_id=stream_id, namespace=presentation.stream.namespace,
            brief_sha256=presentation.stream.brief_sha256, question_id=presentation.question_id,
            metadata_sha256=presentation.metadata_sha256, generation=presentation.generation,
            responder_policy_ref=presentation.responder_policy_ref, transport=presentation.transport.transport,
            bot_id=presentation.transport.bot_id, chat_id=presentation.chat_id,
        ))
        self._commit(session, lambda again: self._generation(again, stream_id, presentation.question_id) != current)
        return True

    def _record_copy(self, session: Session, binding: PresentationBinding) -> bool:
        loaded = self._load(session, binding.stream_id)
        presentation = None if loaded is None else loaded.presentations.get(binding.presentation_id)
        if loaded is None or presentation is None:
            raise ContractRefusal(RefusalCode.MISSING_RECORD, "copy.presentation", "binding.presentation_id")
        _require(
            presentation.question_id == binding.question_id and presentation.generation == binding.generation,
            RefusalCode.BINDING_MISMATCH, "copy.binding", "binding",
        )
        if binding.message_id in loaded.copies.get(binding.presentation_id, frozenset()):
            return False
        self._cas(session, binding.stream_id, loaded.revision, adds="copy")
        row = ClarificationCopy(
            presentation_id=binding.presentation_id, message_id=binding.message_id, stream_id=binding.stream_id,
        )
        row.copy_sha256 = _copy_sha256(row)
        session.add(row)
        key = (binding.presentation_id, binding.message_id)
        self._commit(session, lambda again: again.get(ClarificationCopy, key, populate_existing=True) is not None)
        return True

    def _append_committed(self, session: Session, receipt: ActionReceipt, digest: str) -> IngressAppendResult:
        outcome = self._append(session, receipt, digest)
        self._commit_receipt(session, outcome)
        return outcome

    def _commit_receipt(self, session: Session, outcome: IngressAppendResult) -> None:
        result = outcome.result
        if result.status == "refused":
            self._commit(session, lambda again: self._diagnosed(
                again, result.receipt_sha256, cast(RefusalCode, result.code), cast(str, outcome.guard),
            ))
        else:
            self._commit(session, lambda again: self._moved(
                again, result.stream_id, result.action_key, result.expected_revision,
            ))

    def _append(self, session: Session, receipt: ActionReceipt, digest: str, *,
                restrict_replay_to_receipt_stream: bool = False) -> IngressAppendResult:
        """Stage one append decision; scoped ingress never loads a foreign replay's body/history."""
        key = receipt.action.key
        owner = session.exec(select(ClarificationReceipt.stream_id).where(
            col(ClarificationReceipt.action_key) == key,
        )).first()
        kept = _ReceiptOwner(owner) if owner is not None else None
        if kept is not None:
            if restrict_replay_to_receipt_stream and kept.stream_id != receipt.binding.stream_id:
                bound = self._existing(session, receipt.binding.stream_id)
                return self._refuse(session, receipt, digest, bound.stream_id, bound.revision,
                                    RefusalCode.CROSS_CONTEXT, "replay.stream")
            return self._replay(session, kept.stream_id, receipt, digest)
        stream_id = receipt.binding.stream_id
        loaded = self._load(session, stream_id)
        if loaded is None:
            return self._refuse(session, receipt, digest, stream_id, 0, RefusalCode.MISSING_RECORD, "store.stream")
        if key in loaded.receipts:
            raise _Retry  # kept between the two reads: answer it as a replay
        presentation = loaded.presentations.get(receipt.binding.presentation_id)
        if presentation is None:
            return self._refuse(
                session, receipt, digest, stream_id, loaded.revision, RefusalCode.BINDING_MISMATCH, "store.presentation",
            )
        question = presentation.question_id
        generation = loaded.generation(question)
        confirmed = None if receipt.confirms is None else loaded.parsed.get(receipt.confirms.action.key)
        validation = validate_receipt(
            receipt, presentation=presentation, copies=loaded.copies.get(presentation.presentation_id, frozenset()),
            current_generation=generation, question_ids=loaded.question_ids(), confirmed=confirmed,
        )
        if validation.status != "accepted":
            code, guard = cast(RefusalCode, validation.code), cast(str, validation.guard)
            if validation.status == "retained":
                refusal = self._precondition_refusal(loaded, receipt, question)
                if refusal is not None and refusal.code is RefusalCode.MISSING_RECORD:
                    code, guard = refusal.code, refusal.guard
        else:
            refusal = self._precondition_refusal(loaded, receipt, question)
            if refusal is None:
                return self._apply(session, loaded, receipt, digest, cast(dict[str, Any], validation.event()),
                                   question, generation)
            code, guard = refusal.code, refusal.guard
        if code in RETAINED_CODES:
            return self._retain(session, loaded, receipt, digest, code, guard, question, generation)
        return self._refuse(session, receipt, digest, stream_id, loaded.revision, code, guard)

    def _precondition_refusal(self, loaded: _Loaded, receipt: ActionReceipt, question: str) -> ContractRefusal | None:
        """Kept-state checks after accepted or retention-eligible validation, never after a refusal.

        Correction comes first (presses included, Architecture N2), then
        confirmation-once, then reopen revision/active set. For accepted
        validation the first refusal decides the outcome. For retained
        validation only an unknown correction target (missing_record) replaces
        the original outcome; other retained evidence keeps its prior code.
        M0 checks all targets for existence before checking their actors.
        """
        try:
            if receipt.intent == "correct":
                check_correction_precondition(receipt, answer_actors=loaded.answer_actors(question))
            if receipt.confirms is not None:
                check_confirmation_precondition(receipt, confirmed_actions=loaded.confirmed_actions())
            if receipt.intent == "reopen":
                check_reopen_precondition(
                    receipt, revision=loaded.revision, active_event_ids=self._active(loaded.record, question),
                )
        except ContractRefusal as refusal:
            return refusal
        return None

    def _active(self, record: dict[str, Any], question: str) -> list[str]:
        for state in self._foundation.project_states(record):
            if state["question_id"] == question:
                return cast(list[str], state["active_event_ids"])
        return []

    def _apply(
        self, session: Session, loaded: _Loaded, receipt: ActionReceipt, digest: str, event: dict[str, Any],
        question: str, generation: int,
    ) -> IngressAppendResult:
        try:
            record = self._foundation.append_event(loaded.record, event)
        except self._foundation.ClarificationError:
            return self._refuse(
                session, receipt, digest, loaded.stream_id, loaded.revision, RefusalCode.MALFORMED, "store.foundation",
            )
        _intact(
            record == {**loaded.record, "events": [*loaded.record["events"], event]}, loaded.stream_id,
            "store.event_added", f"the foundation did not add exactly event {event['event_id']} to the latest record",
        )
        key = receipt.action.key
        expected = loaded.revision
        self._add_revision(
            session, loaded, record, change="event", event_id=event["event_id"], action_key=key, adds="receipt",
        )
        self._fence(session, loaded.stream_id, question, generation)
        row = ClarificationReceipt(
            action_key=key, stream_id=loaded.stream_id, receipt_sha256=digest, receipt_json=receipt_json(receipt),
            status="applied", event_id=event["event_id"], expected_revision=expected, revision=expected + 1,
        )
        row.result_sha256 = _saved_result_sha256(row)
        session.add(row)
        return IngressAppendResult(self._result(row), row.guard, receipt, True)

    def _retain(
        self, session: Session, loaded: _Loaded, receipt: ActionReceipt, digest: str, code: RefusalCode, guard: str,
        question: str, generation: int,
    ) -> IngressAppendResult:
        """Keep a retained receipt, decided on the committed revision: the touch below is its compare-and-set."""
        key = receipt.action.key
        expected = loaded.revision
        self._cas(session, loaded.stream_id, expected, adds="receipt")
        self._fence(session, loaded.stream_id, question, generation)
        row = ClarificationReceipt(
            action_key=key, stream_id=loaded.stream_id, receipt_sha256=digest, receipt_json=receipt_json(receipt),
            status="retained", code=code.value, guard=guard, expected_revision=expected, revision=expected,
        )
        row.result_sha256 = _saved_result_sha256(row)
        session.add(row)
        return IngressAppendResult(self._result(row), row.guard, receipt, True)

    def _refuse(
        self, session: Session, receipt: ActionReceipt, digest: str, stream_id: str, revision: int,
        code: RefusalCode, guard: str,
    ) -> IngressAppendResult:
        """Keep linkable diagnostics: row ID, receipt/action-key digests, stream ID, code, guard and time.

        No receipt JSON, answer text or sender column. The action key is a
        non-unique index here, never occupation of the authoritative receipt key.
        """
        result = AppendResult(
            status="refused", stream_id=stream_id, action_key=receipt.action.key, receipt_sha256=digest,
            expected_revision=revision, revision=revision, code=code,
        )
        if not self._diagnosed(session, digest, code, guard):
            session.add(ClarificationRefusal(
                receipt_sha256=digest, action_key=receipt.action.key, stream_id=stream_id, code=code.value, guard=guard,
            ))
        return IngressAppendResult(result, guard, None, False)

    def _replay(self, session: Session, stream_id: str, receipt: ActionReceipt, digest: str) -> IngressAppendResult:
        loaded = self._load(session, stream_id)
        kept = None if loaded is None else loaded.receipts.get(receipt.action.key)
        if loaded is None or kept is None:
            raise _Retry  # gone between the two reads: the next read reports it
        try:
            check_replay(loaded.parsed[kept.action_key], receipt)
        except ContractRefusal as refusal:
            if refusal.code is not RefusalCode.CHANGED_BODY:
                raise
            return self._refuse(session, receipt, digest, stream_id, loaded.revision, refusal.code, refusal.guard)
        return IngressAppendResult(self._result(kept), kept.guard, loaded.parsed[kept.action_key], False)

    def _protocol_view(self, loaded: _Loaded) -> ProtocolView:
        return ProtocolView(
            source_authority_ref=loaded.row.source_authority_ref,
            question_ids=frozenset(loaded.question_ids()),
            answered=frozenset(state["question_id"] for state in self._foundation.project_states(loaded.record)
                               if state["state"] == "answered"),
            presentations=tuple(loaded.presentations.values()),
            copies=tuple(PresentationBinding(
                stream_id=loaded.stream_id, question_id=p.question_id, presentation_id=p.presentation_id,
                generation=p.generation, message_id=message_id,
            ) for p in loaded.presentations.values() for message_id in sorted(loaded.copies.get(p.presentation_id, ()))),
            receipts=tuple(loaded.parsed.values()),
        )

    def _recover(self, session: Session, stream_id: str) -> StoredStream | None:
        loaded = self._load(session, stream_id)
        if loaded is None:
            return None
        current = {
            p.question_id: p for p in loaded.presentations.values() if p.generation == loaded.generation(p.question_id)
        }
        presentations = tuple(current[question] for question in sorted(current))
        copies = tuple(
            PresentationBinding(
                stream_id=stream_id, question_id=p.question_id, presentation_id=p.presentation_id,
                generation=p.generation, message_id=message_id,
            )
            for p in presentations for message_id in sorted(loaded.copies.get(p.presentation_id, ()), key=int)
        )
        latest = loaded.revisions[-1]
        return StoredStream(
            stream=loaded.stream, source_authority_ref=loaded.row.source_authority_ref, revision=loaded.revision,
            record_json=latest.record_json, record_sha256=latest.record_sha256, presentations=presentations,
            copies=copies, pending_revision=None if loaded.revision in loaded.consumed_revisions else loaded.revision,
        )

    def _composed(self, loaded: _Loaded, revision: int, original_brief: str) -> Supplement:
        _require(
            type(revision) is int and 1 <= revision <= loaded.revision, RefusalCode.MISSING_RECORD, "consume.revision",
            "revision",
        )
        _require(type(original_brief) is str, RefusalCode.MALFORMED, "consume.brief_type", "original_brief")
        _require(
            _encodable(lambda: _sha256(original_brief), "original_brief") == loaded.row.brief_sha256,
            RefusalCode.HASH_MISMATCH, "consume.brief", "original_brief",
        )
        kept = loaded.revisions[revision - 1]
        composed = self._foundation.compose_supplement(loaded.records[revision - 1], original_brief)
        mapping = cast(dict[str, Any], composed["source_mapping"])
        _intact(
            mapping["record_sha256"] == kept.record_sha256, loaded.stream_id, "consume.record",
            f"revision {revision}'s supplement names another record than the one kept",
        )
        identity = consumption_id(loaded.stream_id, revision, mapping["supplement_sha256"])
        return Supplement(
            stream_id=loaded.stream_id, revision=revision, consumption_id=identity,
            supplement_sha256=mapping["supplement_sha256"], record_sha256=kept.record_sha256,
            original_brief=original_brief, supplement=composed["supplement"], source_mapping=mapping,
            consumed=identity in loaded.consumed,
        )

    def _mark_consumed(self, session: Session, stream_id: str, revision: int, original_brief: str) -> bool:
        loaded = self._existing(session, stream_id)
        supplement = self._composed(loaded, revision, original_brief)
        if supplement.consumed:
            return False
        return self._record_consumption(session, loaded, supplement)

    def _record_consumption(self, session: Session, loaded: _Loaded, supplement: Supplement) -> bool:
        stream_id, revision = loaded.stream_id, supplement.revision
        self._cas(session, stream_id, loaded.revision, adds="consumption")
        session.add(ClarificationConsumption(
            consumption_id=supplement.consumption_id, stream_id=stream_id, revision=revision,
            supplement_sha256=supplement.supplement_sha256, record_sha256=supplement.record_sha256,
        ))
        identity = supplement.consumption_id
        self._commit(
            session, lambda again: again.get(ClarificationConsumption, identity, populate_existing=True) is not None,
        )
        return True

    # --- reading and checking ---------------------------------------------------------

    @staticmethod
    def _stream_id(stream: StreamKey, where: str) -> str:
        _require(type(stream) is StreamKey, RefusalCode.MALFORMED, "store.stream_type", where)
        return _encodable(lambda: stream.stream_id, where)

    def _existing(self, session: Session, stream_id: str) -> _Loaded:
        loaded = self._load(session, stream_id)
        if loaded is None:
            raise ContractRefusal(RefusalCode.MISSING_RECORD, "consume.stream", "stream")
        return loaded

    @staticmethod
    def _revision(session: Session, stream_id: str) -> int | None:
        return session.exec(
            select(ClarificationStream.revision).where(col(ClarificationStream.stream_id) == stream_id)
        ).first()

    @staticmethod
    def _generation(session: Session, stream_id: str, question_id: str) -> int:
        latest = session.exec(
            select(func.max(ClarificationPresentation.generation)).where(
                col(ClarificationPresentation.stream_id) == stream_id,
                col(ClarificationPresentation.question_id) == question_id,
            )
        ).one()
        return int(latest or 0)

    def _moved(self, session: Session, stream_id: str, key: str, expected: int) -> bool:
        """A clash is explained when another writer kept this key or moved the stream."""
        kept = session.exec(select(ClarificationReceipt.action_key).where(
            col(ClarificationReceipt.action_key) == key,
        )).first() is not None
        return kept or self._revision(session, stream_id) != expected

    @staticmethod
    def _diagnosed(session: Session, digest: str, code: RefusalCode, guard: str) -> bool:
        return session.exec(select(ClarificationRefusal.id).where(
            col(ClarificationRefusal.receipt_sha256) == digest, col(ClarificationRefusal.code) == code.value,
            col(ClarificationRefusal.guard) == guard,
        )).first() is not None

    @staticmethod
    def _result(row: ClarificationReceipt) -> AppendResult:
        return AppendResult(
            status=row.status, stream_id=row.stream_id, action_key=row.action_key, receipt_sha256=row.receipt_sha256,
            expected_revision=row.expected_revision, revision=row.revision, event_id=row.event_id,
            code=None if row.code is None else RefusalCode(row.code),
        )

    def _history(self, session: Session, stream_id: str) -> dict[str, list[Any]]:
        """Every row kept for one stream, read after its stream row."""
        def rows(model: Any) -> list[Any]:
            return list(session.exec(select(model).where(col(model.stream_id) == stream_id)).all())
        return {
            "revisions": sorted(rows(ClarificationRevision), key=lambda row: row.revision),
            "receipts": rows(ClarificationReceipt),
            "presentations": rows(ClarificationPresentation),
            "copies": rows(ClarificationCopy),
            "consumptions": rows(ClarificationConsumption),
            "sends": rows(ClarificationSend),
            "deliveries": rows(ClarificationDelivery),
            "ingresses": rows(ClarificationIngress),
        }

    def _load(self, session: Session, stream_id: str) -> _Loaded | None:
        """Read one stream and check history consistency, not authenticity against DB writers.

        The reads are separate statements, not one snapshot, so a writer may
        commit between them: rows that look ahead of the stream row read first
        are read again before they are called damage.
        """
        row = session.get(ClarificationStream, stream_id, populate_existing=True)
        version = None if row is None else row.state_version
        history = self._history(session, stream_id)
        if row is None:
            if not any(history.values()):
                return None
            if self._revision(session, stream_id) is not None:
                raise _Retry  # created between the two reads
            raise ClarificationIntegrityError(stream_id, "stream.missing", "the stream row is missing; " + ", ".join(
                f"{len(rows)} {kind}" for kind, rows in history.items()) + " remain")
        seen = (row.revision, row.record_sha256, row.receipt_count, row.presentation_count, row.copy_count,
                row.consumption_count)
        newest = max((item.revision for item in [*history["revisions"], *history["receipts"]]), default=0)
        counts = zip(seen[2:], [history[kind] for kind in ("receipts", "presentations", "copies", "consumptions")],
                     strict=True)
        if newest > row.revision or any(len(rows) > count for count, rows in counts):
            again = session.get(ClarificationStream, stream_id, populate_existing=True)
            if again is None or (again.revision, again.record_sha256, again.receipt_count, again.presentation_count,
                                 again.copy_count, again.consumption_count) != seen:
                raise _Retry  # another writer committed between the reads
            raise ClarificationIntegrityError(
                stream_id, "history.ahead", f"rows go past the stream row (revision {row.revision}, counts {seen[2:]})",
            )
        # Counts catch loss; version also fences changed attempts/representatives
        # that do not change a count or revision between these separate SELECTs.
        from temper_ai.clarifications.delivery_store import (
            check_delivery_history,
            check_read_version,
        )

        check_read_version(session, stream_id, version)
        loaded = self._checked(row, history)
        check_delivery_history(self, session, loaded, history)
        return loaded

    def _checked(self, row: ClarificationStream, history: dict[str, list[Any]]) -> _Loaded:
        stream_id = row.stream_id
        try:
            stream = StreamKey(namespace=row.namespace, brief_sha256=row.brief_sha256)
            same = stream.stream_id == stream_id
        except (ContractRefusal, UnicodeEncodeError):
            same = False
        _intact(same, stream_id, "stream.identity", "the stream row's namespace and brief do not give its ID")
        revisions: list[ClarificationRevision] = history["revisions"]
        records = self._checked_records(row, revisions)
        presentations = self._checked_presentations(row, stream, records[-1], history["presentations"])
        copies: dict[str, set[str]] = {}
        _intact(len(history["copies"]) == row.copy_count, stream_id, "copy.count",
                f"{row.copy_count} copies were kept, {len(history['copies'])} remain")
        for copy in history["copies"]:
            _intact(copy.presentation_id in presentations, stream_id, "copy.identity",
                    f"copy {copy.message_id} names presentation {copy.presentation_id}, which is not kept")
            _intact(copy.copy_sha256 == _copy_sha256(copy), stream_id, "copy.digest",
                    "a delivered-copy tuple does not match its saved digest")
            copies.setdefault(copy.presentation_id, set()).add(copy.message_id)
        receipts, parsed = self._checked_receipts(row, history["receipts"])
        self._checked_events(row, revisions, records, receipts, parsed, presentations, copies)
        consumptions: list[ClarificationConsumption] = history["consumptions"]
        _intact(len(consumptions) == row.consumption_count, stream_id, "consumption.count",
                f"{row.consumption_count} consumptions were kept, {len(consumptions)} remain")
        for consumption in consumptions:
            try:
                same = (1 <= consumption.revision <= row.revision
                        and consumption.record_sha256 == revisions[consumption.revision - 1].record_sha256
                        and consumption.consumption_id == consumption_id(
                            stream_id, consumption.revision, consumption.supplement_sha256))
            except ContractRefusal:
                same = False
            _intact(same, stream_id, "consumption.identity",
                    f"consumption {consumption.consumption_id} does not name a kept revision's supplement")
        return _Loaded(
            row=row, stream=stream, revisions=revisions, records=records, receipts=receipts, parsed=parsed,
            presentations=presentations, copies={key: frozenset(ids) for key, ids in copies.items()},
            consumed=frozenset(c.consumption_id for c in consumptions),
            consumed_revisions=frozenset(c.revision for c in consumptions),
        )

    def _checked_records(self, row: ClarificationStream, revisions: list[ClarificationRevision]) -> list[dict[str, Any]]:
        stream_id = row.stream_id
        numbers = [revision.revision for revision in revisions]
        wanted = list(range(1, row.revision + 1))
        _intact(row.revision >= 1 and numbers == wanted, stream_id, "history.revisions",
                f"revisions kept {numbers}, the stream row names 1..{row.revision}; "
                f"missing {sorted(set(wanted) - set(numbers))}")
        records: list[dict[str, Any]] = []
        previous_sha = ""
        for revision in revisions:
            number = revision.revision
            _intact(_sha256(revision.record_json) == revision.record_sha256, stream_id, "history.digest",
                    f"revision {number}'s record does not match its digest")
            _intact(revision.previous_record_sha256 == previous_sha, stream_id, "history.chain",
                    f"revision {number} does not follow revision {number - 1}")
            record = self._kept_record(stream_id, number, revision.record_json, row.brief_sha256)
            self._check_step(stream_id, revision, records[-1] if records else None, record)
            records.append(record)
            previous_sha = revision.record_sha256
        _intact(previous_sha == row.record_sha256, stream_id, "history.latest",
                f"the stream row does not name revision {row.revision}'s record")
        return records

    def _kept_record(self, stream_id: str, number: int, text: str, brief_sha256: str) -> dict[str, Any]:
        try:
            record = json.loads(text)
            canonical = type(record) is dict and _canonical(record) == text
        except ValueError:
            canonical = False
        _intact(canonical, stream_id, "history.json", f"revision {number}'s record is not canonical JSON")
        try:
            self._foundation.validate_record(record)
        except self._foundation.ClarificationError as error:
            raise ClarificationIntegrityError(
                stream_id, "history.record", f"revision {number}'s record is not valid: {error}",
            ) from error
        _intact(record["brief_sha256"] == brief_sha256, stream_id, "history.brief",
                f"revision {number}'s record is for another brief")
        return cast(dict[str, Any], record)

    @staticmethod
    def _check_step(
        stream_id: str, revision: ClarificationRevision, previous: dict[str, Any] | None, record: dict[str, Any],
    ) -> None:
        """Each revision adds exactly what it says to the one before it: a record change or one event."""
        number = revision.revision
        no_event = revision.event_id is None and revision.action_key is None
        if previous is None:
            _intact(revision.change == "record" and no_event and record["events"] == [], stream_id, "history.first",
                    "revision 1 is not a new record")
            return
        if revision.change == "record":
            kept = all(question in record["questions"] for question in previous["questions"])
            _intact(no_event and kept and record["events"] == previous["events"] and record != previous, stream_id,
                    "history.record_step", f"revision {number} is not the record change it claims")
            return
        events = record["events"]
        _intact(
            revision.change == "event" and revision.action_key is not None
            and record["questions"] == previous["questions"] and len(events) == len(previous["events"]) + 1
            and events[:-1] == previous["events"] and events[-1]["event_id"] == revision.event_id,
            stream_id, "history.event_step", f"revision {number} does not add exactly its one event",
        )

    def _checked_presentations(
        self, row: ClarificationStream, stream: StreamKey, record: dict[str, Any],
        rows: list[ClarificationPresentation],
    ) -> dict[str, Presentation]:
        stream_id = row.stream_id
        _intact(len(rows) == row.presentation_count, stream_id, "presentation.count",
                f"{row.presentation_count} presentations were kept, {len(rows)} remain")
        questions = {question["question_id"]: question for question in record["questions"]}
        built: dict[str, Presentation] = {}
        for kept in rows:
            question = questions.get(kept.question_id)
            try:
                presentation = Presentation(
                    stream=stream, question_id=kept.question_id, metadata_sha256=kept.metadata_sha256,
                    generation=kept.generation, responder_policy_ref=kept.responder_policy_ref,
                    transport=TransportNamespace(transport=kept.transport, bot_id=kept.bot_id), chat_id=kept.chat_id,
                )
                same = (presentation.presentation_id == kept.presentation_id and question is not None
                        and metadata_sha256(_metadata(question)) == kept.metadata_sha256
                        and (kept.namespace, kept.brief_sha256) == (row.namespace, row.brief_sha256))
            except (ContractRefusal, UnicodeEncodeError):
                same = False
            _intact(same, stream_id, "presentation.identity",
                    f"presentation {kept.presentation_id} is not the presentation its row names")
            built[kept.presentation_id] = presentation
        return built

    def _checked_receipts(
        self, row: ClarificationStream, rows: list[ClarificationReceipt],
    ) -> tuple[dict[str, ClarificationReceipt], dict[str, ActionReceipt]]:
        stream_id = row.stream_id
        _intact(len(rows) == row.receipt_count, stream_id, "receipt.count",
                f"{row.receipt_count} receipts were kept, {len(rows)} remain")
        receipts: dict[str, ClarificationReceipt] = {}
        parsed: dict[str, ActionReceipt] = {}
        for kept in rows:
            key = kept.action_key
            _intact(_sha256(kept.receipt_json) == kept.receipt_sha256, stream_id, "receipt.digest",
                    f"receipt {key} does not match its digest")
            try:
                receipt = receipt_from_json(kept.receipt_json)
                result = self._result(kept)
            except ValueError as error:  # ContractRefusal included
                raise ClarificationIntegrityError(
                    stream_id, "receipt.sidecar", f"receipt {key} is not a kept receipt: {error}",
                ) from error
            _intact(
                receipt.action.key == key and receipt.binding.stream_id == stream_id
                and receipt.ingress == VERIFIED_INGRESS and result.status != "refused", stream_id, "receipt.identity",
                f"receipt {key} is not the receipt its row names",
            )
            _intact(kept.result_sha256 == _saved_result_sha256(kept), stream_id, "receipt.result",
                    f"receipt {key}'s saved decision does not match its result digest")
            receipts[key] = kept
            parsed[key] = receipt
        return receipts, parsed

    @staticmethod
    def _checked_events(
        row: ClarificationStream, revisions: list[ClarificationRevision], records: list[dict[str, Any]],
        receipts: dict[str, ClarificationReceipt], parsed: dict[str, ActionReceipt],
        presentations: dict[str, Presentation], copies: dict[str, set[str]],
    ) -> None:
        """Every event is exactly what its kept receipt gives, and every applied receipt has its event."""
        stream_id = row.stream_id
        event_keys = set()
        for revision in revisions:
            if revision.change != "event":
                continue
            key = cast(str, revision.action_key)
            event_keys.add(key)
            kept = receipts.get(key)
            _intact(kept is not None and kept.status == "applied", stream_id, "receipt.missing",
                    f"revision {revision.revision}'s receipt {key} is missing")
            receipt = parsed[key]
            record = records[revision.revision - 1]
            presentation = presentations.get(receipt.binding.presentation_id)
            expected = None
            if presentation is not None:  # the event validate_receipt gave when it was current
                confirmed = None if receipt.confirms is None else parsed.get(receipt.confirms.action.key)
                try:
                    expected = validate_receipt(
                        receipt, presentation=presentation, copies=copies.get(presentation.presentation_id, set()),
                        current_generation=presentation.generation,
                        question_ids=[question["question_id"] for question in record["questions"]],
                        confirmed=confirmed,
                    ).event()
                except ContractRefusal:
                    expected = None
            event = record["events"][-1]
            _intact(cast(ClarificationReceipt, kept).event_id == event["event_id"], stream_id,
                    "receipt.event_identity", f"receipt {key}'s saved event identity differs from its committed event")
            _intact(
                cast(ClarificationReceipt, kept).revision == revision.revision and expected == event
                and event["source"]["ref"] == f"{RECEIPT_REF_SCHEME}:{cast(ClarificationReceipt, kept).receipt_sha256}",
                stream_id, "receipt.event", f"revision {revision.revision}'s event is not what receipt {key} gives",
            )
        applied = {key for key, kept in receipts.items() if kept.status == "applied"}
        _intact(applied == event_keys, stream_id, "receipt.applied",
                f"applied receipts with no revision: {sorted(applied - event_keys)}")
