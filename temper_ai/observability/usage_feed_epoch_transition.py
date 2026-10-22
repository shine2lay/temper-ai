"""Inert privileged protocol; no runtime caller or implemented Ops control adapter.

Every invocation requires a source-bound authority/head pin AND an external
verifier for actual OFF, durable settled quiescence and native Q/evidence. Typed
receipts alone cannot establish those facts or grant operation/release authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from sqlalchemy import select
from sqlalchemy.engine import Engine

from temper_ai.observability import usage_feed_epochs as core
from temper_ai.observability.usage_feed_cursor import (
    MAX_EPOCH,
    MAX_REVISION,
    CursorError,
    FinalRowAnchor,
    TargetCursor,
    canonical_uuid,
    encode_target_cursor,
)
from temper_ai.observability.usage_feed_epoch_journal import (
    EMPTY_HEAD,
    HostJournal,
    JournalError,
    JournalHead,
    JournalRecord,
    JournalSession,
    closed,
    digest,
    require_digest,
)

PAPER_SHA256 = "4b727b3f91821fbd1744697d48b4d9ea42e83d1ced2238d4adb13d69306dd18f"
PRINCIPAL = "usage-collector"
MAX_DB_PHASES = 8192
_NATIVE_ID = re.compile(r"[A-Za-z0-9._:\-]{1,128}", re.ASCII)
_OPAQUE = re.compile(r"[A-Za-z0-9_.-]{1,256}", re.ASCII)
Action = Literal["begin", "reconcile", "abandon"]


class HostProtocolError(JournalError):
    def __init__(self, code: str = "epoch-host-blocked") -> None:
        super().__init__(code)


def _check(condition: bool, code: str = "epoch-host-blocked") -> None:
    if not condition:
        raise HostProtocolError(code)


def _uuid(value: Any) -> str:
    try:
        return canonical_uuid(value)
    except CursorError:
        raise HostProtocolError() from None


def _number(value: Any, low: int = 0, high: int = MAX_EPOCH) -> None:
    _check(type(value) is int and low <= value <= high)


def _token(value: Any, domain: str) -> None:
    _check(type(value) is str and _OPAQUE.fullmatch(value) is not None
           and value.startswith(domain) and len(value) > len(domain))


def _refs(value: tuple[str, ...]) -> None:
    _check(type(value) is tuple and len(value) <= 64)
    for ref in value:
        require_digest(ref)
    _check(len(set(value)) == len(value))


def _parse_refs(value: Any) -> tuple[str, ...]:
    _check(type(value) is list)
    result = tuple(value)
    _refs(result)
    return result


def identity_payload(identity: core.PrivateIdentity | None) -> dict[str, Any] | None:
    return None if identity is None else {
        "system_identifier": identity.system_identifier, "database_oid": identity.database_oid,
        "insert_timeline": identity.insert_timeline}


def _identity(value: Any) -> core.PrivateIdentity | None:
    if value is None:
        return None
    row = closed(value, {"system_identifier", "database_oid", "insert_timeline"})
    try:
        return core.PrivateIdentity(**row)
    except core.EpochError:
        raise HostProtocolError() from None


@dataclass(frozen=True, repr=False)
class NativeWitness:
    instance: str
    event_id: str
    revision: int

    def __post_init__(self) -> None:
        _uuid(self.instance)
        _number(self.revision, high=MAX_REVISION)
        _check(type(self.event_id) is str and _NATIVE_ID.fullmatch(self.event_id) is not None)

    def payload(self) -> dict[str, Any]:
        return {"instance": self.instance, "event_id": self.event_id, "revision": self.revision}

    @classmethod
    def parse(cls, value: Any) -> NativeWitness:
        return cls(**closed(value, {"instance", "event_id", "revision"}))


@dataclass(frozen=True, repr=False)
class NativeCheckpoint:
    """FUTURE Ops authoritative atomic transaction + retained evidence references.

    Structure/equality are checked here; the external verifier MUST prove actual
    durable membership and G/W/header atomic linkage. This is not self-attestation.
    """

    transaction_id: str
    evidence_refs: tuple[str, ...]
    witness: NativeWitness | None

    def __post_init__(self) -> None:
        _uuid(self.transaction_id)
        _refs(self.evidence_refs)
        _check(self.witness is None or type(self.witness) is NativeWitness)
        _check(self.witness is None or bool(self.evidence_refs))

    def payload(self) -> dict[str, Any]:
        return {"transaction_id": self.transaction_id, "evidence_refs": list(self.evidence_refs),
                "witness": self.witness.payload() if self.witness else None}

    @classmethod
    def parse(cls, value: Any) -> NativeCheckpoint:
        row = closed(value, {"transaction_id", "evidence_refs", "witness"})
        return cls(row["transaction_id"], _parse_refs(row["evidence_refs"]),
                   NativeWitness.parse(row["witness"]) if row["witness"] is not None else None)


@dataclass(frozen=True, repr=False)
class QuiescentHeader:
    state_version: int
    logical_reader_id: str
    principal: str
    source_instance: str
    mode: str
    epoch: int
    transition_id: str
    generation: int
    progress: str
    g: str | None
    w: NativeWitness | None
    q: NativeCheckpoint
    target: str | None
    reached: bool
    prior_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _check(type(self.state_version) is int and self.state_version == 1 and self.mode == "QUIESCENT")
        _uuid(self.logical_reader_id)
        _uuid(self.source_instance)
        _uuid(self.transition_id)
        _check(self.principal == PRINCIPAL)
        _number(self.epoch, 1)
        _number(self.generation, 1)
        _check(type(self.q) is NativeCheckpoint and type(self.reached) is bool)
        _refs(self.prior_refs)
        if self.g is None:
            _check(self.w is None and self.q.witness is None and self.progress == "no-progress")
        else:
            # Only closed ROW-domain syntax, NEVER decode/build/resolve old G.
            _token(self.g, "r1.")
            _check(type(self.w) is NativeWitness and self.w.instance == self.source_instance
                   and self.q.witness == self.w and bool(self.q.evidence_refs) and self.progress == "committed")
        if self.target is not None:
            _token(self.target, "t1.")
        else:
            _check(self.reached)

    def payload(self) -> dict[str, Any]:
        return {"state_version": self.state_version, "logical_reader_id": self.logical_reader_id,
                "principal": self.principal, "source_instance": self.source_instance, "mode": self.mode,
                "epoch": self.epoch, "transition_id": self.transition_id, "generation": self.generation,
                "progress": self.progress, "g": self.g, "w": self.w.payload() if self.w else None,
                "q": self.q.payload(), "target": self.target, "reached": self.reached,
                "prior_refs": list(self.prior_refs)}

    @classmethod
    def parse(cls, value: Any) -> QuiescentHeader:
        row = closed(value, {"state_version", "logical_reader_id", "principal", "source_instance", "mode",
                            "epoch", "transition_id", "generation", "progress", "g", "w", "q", "target",
                            "reached", "prior_refs"})
        return cls(**{**row, "w": NativeWitness.parse(row["w"]) if row["w"] is not None else None,
                      "q": NativeCheckpoint.parse(row["q"]), "prior_refs": _parse_refs(row["prior_refs"])})


@dataclass(frozen=True, repr=False)
class VirginAdmission:
    state_version: int
    logical_reader_id: str
    principal: str
    source_instance: str
    mode: str
    generation: int
    admission_ref: str
    prior_issuance: str

    def __post_init__(self) -> None:
        _check(type(self.state_version) is int and self.state_version == 1
               and self.mode == "VIRGIN-ADMITTED" and self.prior_issuance == "none-attested")
        _uuid(self.logical_reader_id)
        _uuid(self.source_instance)
        _uuid(self.admission_ref)
        _number(self.generation, 1)
        _check(self.principal == PRINCIPAL)

    def payload(self) -> dict[str, Any]:
        return dict(state_version=self.state_version, logical_reader_id=self.logical_reader_id,
                    principal=self.principal, source_instance=self.source_instance, mode=self.mode,
                    generation=self.generation, admission_ref=self.admission_ref, prior_issuance=self.prior_issuance)

    @classmethod
    def parse(cls, value: Any) -> VirginAdmission:
        return cls(**closed(value, {"state_version", "logical_reader_id", "principal", "source_instance",
                                   "mode", "generation", "admission_ref", "prior_issuance"}))


@dataclass(frozen=True, repr=False)
class ClosedHandoff:
    """Closed fixture schema for future real OFF/settled-control receipts."""

    header: QuiescentHeader | VirginAdmission
    off_ref: str
    quiescence_ref: str
    header_digest: str
    server_admission: str = "OFF"
    registered_work: int = 0

    def __post_init__(self) -> None:
        _check(type(self.header) in (QuiescentHeader, VirginAdmission))
        _uuid(self.off_ref)
        _uuid(self.quiescence_ref)
        _check(self.server_admission == "OFF" and type(self.registered_work) is int and self.registered_work == 0)
        _check(require_digest(self.header_digest) == digest(self.header.payload()))

    def payload(self) -> dict[str, Any]:
        return {"header": self.header.payload(), "off_ref": self.off_ref, "quiescence_ref": self.quiescence_ref,
                "header_digest": self.header_digest, "server_admission": self.server_admission,
                "registered_work": self.registered_work}

    @classmethod
    def parse(cls, value: Any) -> ClosedHandoff:
        row = closed(value, {"header", "off_ref", "quiescence_ref", "header_digest", "server_admission", "registered_work"})
        _check(type(row["header"]) is dict)
        header = (VirginAdmission.parse(row["header"]) if row["header"].get("mode") == "VIRGIN-ADMITTED"
                  else QuiescentHeader.parse(row["header"]))
        return cls(**{**row, "header": header})


@dataclass(frozen=True, repr=False)
class HostAuthorization:
    transition_id: str
    source_instance: str
    logical_reader_id: str
    action: Action
    reason: core.Reason
    plan_ref: str
    consent_ref: str
    expected_head: JournalHead
    actor: str = core.HOST_ACTOR
    paper_sha256: str = PAPER_SHA256

    def __post_init__(self) -> None:
        for value in (self.transition_id, self.source_instance, self.logical_reader_id):
            _uuid(value)
        _check(self.action in ("begin", "reconcile", "abandon") and self.reason in ("activation", "restore", "migration")
               and self.actor == core.HOST_ACTOR and self.paper_sha256 == PAPER_SHA256)
        require_digest(self.plan_ref)
        require_digest(self.consent_ref)
        _check(type(self.expected_head) is JournalHead)

    def payload(self) -> dict[str, Any]:
        return {"transition_id": self.transition_id, "source_instance": self.source_instance,
                "logical_reader_id": self.logical_reader_id, "action": self.action, "reason": self.reason,
                "plan_ref": self.plan_ref, "consent_ref": self.consent_ref, "expected_head": self.expected_head.payload(),
                "actor": self.actor, "paper_sha256": self.paper_sha256}

    @classmethod
    def parse(cls, value: Any) -> HostAuthorization:
        row = closed(value, {"transition_id", "source_instance", "logical_reader_id", "action", "reason", "plan_ref",
                            "consent_ref", "expected_head", "actor", "paper_sha256"})
        return cls(**{**row, "expected_head": JournalHead.parse(row["expected_head"])})


class RequiredHostControls(Protocol):
    """NOT IMPLEMENTED for production: no guessed Ops methods or default pass.

    A future normally approved adapter must authenticate the authorization and
    head pin, enforce shared custody/approved location, verify the real registry
    OFF with handlers settled, verify persistent generation/admission/registered
    work settlement and exact settled header, and prove Q/evidence/G/W atomic
    links in the real authoritative storage. It must recheck on EVERY call and
    stay closed on restart/failure. The fixtures explicitly model this contract.
    """

    def verify(self, authorization: HostAuthorization, handoff: ClosedHandoff, journal_path: Path) -> None: ...


def _scope(authorization: HostAuthorization, handoff: ClosedHandoff) -> None:
    _check(authorization.source_instance == handoff.header.source_instance
           and authorization.logical_reader_id == handoff.header.logical_reader_id)


def _timestamp(value: datetime) -> str:
    _check(type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None)
    from datetime import UTC

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, repr=False)
class DatabasePhase:
    operation: core.EpochOperation
    phase: core.Phase
    created_at: str

    def __post_init__(self) -> None:
        _check(type(self.operation) is core.EpochOperation and self.phase in ("PREPARED", "READY"))
        try:
            _check(type(self.created_at) is str and self.created_at.endswith("Z")
                   and _timestamp(datetime.fromisoformat(self.created_at)) == self.created_at)
        except (ValueError, TypeError):
            raise HostProtocolError() from None

    def payload(self) -> dict[str, Any]:
        return {**self.operation.values(self.phase), "created_at": self.created_at}

    @classmethod
    def parse(cls, value: Any) -> DatabasePhase:
        row = closed(value, {"epoch", "phase", "transition_id", "source_instance", "system_identifier", "database_oid",
                            "insert_timeline", "basis", "actor", "reason", "target_seq", "target_event_id",
                            "target_revision", "created_at"})
        target_fields = (row["target_seq"], row["target_event_id"], row["target_revision"])
        try:
            target = None if target_fields == (None, None, None) else FinalRowAnchor(*target_fields)
            operation = core.EpochOperation(row["epoch"], row["transition_id"], row["source_instance"],
                core.PrivateIdentity(row["system_identifier"], row["database_oid"], row["insert_timeline"]),
                row["reason"], target, row["basis"], row["actor"])
            return cls(operation, row["phase"], row["created_at"])
        except (CursorError, core.EpochError):
            raise HostProtocolError() from None


def _target_token(operation: core.EpochOperation) -> str | None:
    return (encode_target_cursor(TargetCursor(operation.source_instance, operation.epoch, operation.target))
            if operation.target is not None else None)


@dataclass(frozen=True, repr=False)
class Intent:
    authorization: HostAuthorization
    handoff: ClosedHandoff
    epoch: int
    db_max: int
    host_max: int
    db_digest: str
    old_identity: core.PrivateIdentity | None
    new_identity: core.PrivateIdentity

    def __post_init__(self) -> None:
        _check(type(self.authorization) is HostAuthorization and type(self.handoff) is ClosedHandoff)
        _scope(self.authorization, self.handoff)
        _check(self.authorization.action == "begin")
        _number(self.db_max)
        _number(self.host_max)
        _number(self.epoch, 1)
        _check(self.epoch == 1 + max(self.db_max, self.host_max))
        require_digest(self.db_digest)
        _check(type(self.new_identity) is core.PrivateIdentity)
        virgin = type(self.handoff.header) is VirginAdmission
        _check((virgin and self.old_identity is None and self.db_max == self.host_max == 0
                and self.authorization.reason == "activation")
               or (not virgin and type(self.old_identity) is core.PrivateIdentity
                   and self.authorization.reason in ("restore", "migration")))

    def payload(self) -> dict[str, Any]:
        return {"authorization": self.authorization.payload(), "handoff": self.handoff.payload(), "epoch": self.epoch,
                "db_max": self.db_max, "host_max": self.host_max, "db_digest": self.db_digest,
                "old_identity": identity_payload(self.old_identity), "new_identity": identity_payload(self.new_identity)}

    @classmethod
    def parse(cls, value: Any) -> Intent:
        row = closed(value, {"authorization", "handoff", "epoch", "db_max", "host_max", "db_digest",
                            "old_identity", "new_identity"})
        new_identity = _identity(row["new_identity"])
        _check(new_identity is not None)
        assert new_identity is not None
        return cls(HostAuthorization.parse(row["authorization"]), ClosedHandoff.parse(row["handoff"]), row["epoch"],
                   row["db_max"], row["host_max"], row["db_digest"], _identity(row["old_identity"]), new_identity)

    def matches(self, operation: core.EpochOperation) -> bool:
        a = self.authorization
        return (operation.epoch == self.epoch and operation.transition_id == a.transition_id
                and operation.source_instance == a.source_instance and operation.identity == self.new_identity
                and operation.reason == a.reason and operation.actor == a.actor and operation.basis == core.IDENTITY_BASIS)


@dataclass(frozen=True, repr=False)
class PreparedReceipt:
    intent_checksum: str
    prepared: DatabasePhase
    target: str | None
    authorization: HostAuthorization

    def __post_init__(self) -> None:
        require_digest(self.intent_checksum)
        _check(type(self.prepared) is DatabasePhase and self.prepared.phase == "PREPARED"
               and type(self.authorization) is HostAuthorization)
        _check(self.target == _target_token(self.prepared.operation))

    def payload(self) -> dict[str, Any]:
        return {"intent_checksum": self.intent_checksum, "prepared": self.prepared.payload(),
                "target": self.target, "authorization": self.authorization.payload()}

    @classmethod
    def parse(cls, value: Any) -> PreparedReceipt:
        row = closed(value, {"intent_checksum", "prepared", "target", "authorization"})
        return cls(row["intent_checksum"], DatabasePhase.parse(row["prepared"]), row["target"],
                   HostAuthorization.parse(row["authorization"]))


@dataclass(frozen=True, repr=False)
class TransitionHistory:
    intent_record: JournalRecord
    intent: Intent
    receipt_record: JournalRecord | None = None
    receipt: PreparedReceipt | None = None
    terminal: JournalRecord | None = None


def _matching_authority(a: HostAuthorization, intent: Intent) -> None:
    first = intent.authorization
    _check(a.transition_id == first.transition_id and a.source_instance == first.source_instance
           and a.logical_reader_id == first.logical_reader_id and a.reason == first.reason)


def histories(records: tuple[JournalRecord, ...]) -> dict[str, TransitionHistory]:
    """Validate full closed phase grammar and immutable metadata, not just hashes."""
    result: dict[str, TransitionHistory] = {}
    heads = {0: EMPTY_HEAD}
    admission: ClosedHandoff | None = None
    maximum = 0
    for record in records:
        heads[record.sequence] = record.head
        data = record.data
        if record.kind == "ADMISSION":
            row = closed(data, {"handoff", "authorization"})
            handoff, a = ClosedHandoff.parse(row["handoff"]), HostAuthorization.parse(row["authorization"])
            _scope(a, handoff)
            _check(record.sequence == 1 and type(handoff.header) is VirginAdmission and a.action == "begin"
                   and a.reason == "activation" and a.expected_head == EMPTY_HEAD)
            admission = handoff
            _check(record.source_instance == handoff.header.source_instance)
            continue
        _check(admission is not None)
        assert admission is not None
        if record.kind == "INTENT":
            intent = Intent.parse(data)
            a = intent.authorization
            _check(a.source_instance == record.source_instance and a.transition_id not in result
                   and intent.host_max == maximum
                   and a.logical_reader_id == admission.header.logical_reader_id)
            _check(all(item.terminal is not None for item in result.values()))
            if isinstance(intent.handoff.header, VirginAdmission):
                _check(not result and intent.handoff == admission)
            else:
                old_header = intent.handoff.header
                old = result.get(old_header.transition_id)
                _check(old is not None and old.terminal is not None and old.terminal.kind == "COMPLETE"
                       and old.receipt is not None and old_header.target == old.receipt.target
                       and old.terminal.checksum in old_header.prior_refs
                       and old.intent.epoch == old_header.epoch and old.intent.new_identity == intent.old_identity)
            result[a.transition_id] = TransitionHistory(record, intent)
            maximum = intent.epoch
        else:
            row = data
            a = HostAuthorization.parse(row.get("authorization"))
            item = result.get(a.transition_id)
            _check(item is not None)
            assert item is not None
            _matching_authority(a, item.intent)
            _check(item.terminal is None)
            if record.kind == "PREPARED-RECEIPT":
                receipt = PreparedReceipt.parse(row)
                _check(item.receipt is None and a.action in ("begin", "reconcile")
                       and receipt.intent_checksum == item.intent_record.checksum
                       and item.intent.matches(receipt.prepared.operation))
                result[a.transition_id] = TransitionHistory(item.intent_record, item.intent, record, receipt)
            elif record.kind == "COMPLETE":
                row = closed(row, {"receipt_checksum", "ready", "authorization"})
                ready = DatabasePhase.parse(row["ready"])
                _check(a.action in ("begin", "reconcile") and item.receipt is not None
                       and item.receipt_record is not None and row["receipt_checksum"] == item.receipt_record.checksum
                       and ready.phase == "READY" and ready.operation == item.receipt.prepared.operation)
                result[a.transition_id] = TransitionHistory(item.intent_record, item.intent, item.receipt_record,
                                                           item.receipt, record)
            elif record.kind == "ABANDONED":
                row = closed(row, {"intent_checksum", "db_digest", "db_max", "observed_prepared",
                                   "receipt_checksum", "authorization"})
                _number(row["db_max"])
                require_digest(row["db_digest"])
                observed = DatabasePhase.parse(row["observed_prepared"]) if row["observed_prepared"] is not None else None
                _check(a.action == "abandon" and row["intent_checksum"] == item.intent_record.checksum
                       and row["receipt_checksum"] == (item.receipt_record.checksum if item.receipt_record else None))
                _check((observed is None and row["db_max"] < item.intent.epoch)
                       or (observed is not None and observed.phase == "PREPARED"
                           and item.intent.matches(observed.operation) and row["db_max"] == item.intent.epoch
                           and (item.receipt is None or observed == item.receipt.prepared)))
                result[a.transition_id] = TransitionHistory(item.intent_record, item.intent, item.receipt_record,
                                                           item.receipt, record)
            else:
                raise HostProtocolError()
        # Pin must name a prior exact retained head, never a future/rewritten suffix.
        _check(a.expected_head.sequence < record.sequence and heads.get(a.expected_head.sequence) == a.expected_head)
    return result


def validate_history(records: tuple[JournalRecord, ...]) -> None:
    histories(records)


@dataclass(frozen=True, repr=False)
class DatabaseView:
    source_instance: str
    identity: core.PrivateIdentity
    phases: tuple[DatabasePhase, ...]

    @property
    def maximum(self) -> int:
        return max((phase.operation.epoch for phase in self.phases), default=0)

    @property
    def checksum(self) -> str:
        return digest([phase.payload() for phase in self.phases])

    def operation_phases(self, intent: Intent) -> tuple[DatabasePhase | None, DatabasePhase | None]:
        matched = [p for p in self.phases if p.operation.transition_id == intent.authorization.transition_id
                   or p.operation.epoch == intent.epoch]
        _check(all(intent.matches(p.operation) for p in matched), "epoch-operation-mismatch")
        prepared = next((p for p in matched if p.phase == "PREPARED"), None)
        ready = next((p for p in matched if p.phase == "READY"), None)
        _check(ready is None or (prepared is not None and ready.operation == prepared.operation))
        return prepared, ready


class PostgresEpochStore:
    """Only real core fenced transactions; bounded actual rows, no old-G API."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _view(self, fence: core.EpochFence) -> DatabaseView:
        live = core.probe_primary_identity(fence.connection)
        source = core.read_source_instance(fence)
        rows = fence.connection.execute(select(core.EPOCHS).order_by(core.EPOCHS.c.epoch, core.EPOCHS.c.phase)
                                        .limit(MAX_DB_PHASES + 1)).mappings().all()
        _check(len(rows) <= MAX_DB_PHASES, "epoch-database-history-full")
        phases = tuple(DatabasePhase.parse({**row, "created_at": _timestamp(row["created_at"])}) for row in rows)
        by_epoch: dict[int, dict[str, core.EpochOperation]] = {}
        seen: dict[str, int] = {}
        for phase in phases:
            op = phase.operation
            _check(op.source_instance == source)
            _check(op.transition_id not in seen or seen[op.transition_id] == op.epoch)
            seen[op.transition_id] = op.epoch
            entry = by_epoch.setdefault(op.epoch, {})
            _check(phase.phase not in entry)
            entry[phase.phase] = op
        for entry in by_epoch.values():
            _check("PREPARED" in entry and ("READY" not in entry or entry["READY"] == entry["PREPARED"]))
        _check(core.probe_primary_identity(fence.connection) == live, "epoch-identity-changed")
        fence.require(host=True)
        return DatabaseView(source, live, phases)

    def snapshot(self) -> DatabaseView:
        with core.host_epoch_transaction(self.engine) as fence:
            return self._view(fence)

    def prepare(self, intent: Intent) -> None:
        with core.host_epoch_transaction(self.engine) as fence:
            current = self._view(fence)
            _check(current.source_instance == intent.authorization.source_instance and current.identity == intent.new_identity
                   and current.maximum == intent.db_max and current.checksum == intent.db_digest, "epoch-database-changed")
            core.append_prepared_epoch(fence, epoch=intent.epoch, transition_id=intent.authorization.transition_id,
                source_instance=intent.authorization.source_instance, expected_identity=intent.new_identity,
                expected_db_epoch=intent.db_max, reason=intent.authorization.reason)

    def ready(self, intent: Intent, receipt: PreparedReceipt) -> None:
        with core.host_epoch_transaction(self.engine) as fence:
            current = self._view(fence)
            _check(current.source_instance == intent.authorization.source_instance and current.identity == intent.new_identity
                   and current.maximum == intent.epoch, "epoch-database-changed")
            prepared, _ = current.operation_phases(intent)
            _check(prepared == receipt.prepared, "epoch-receipt-mismatch")
            core.append_ready_epoch(fence, receipt.prepared.operation)

    def validate_operation(self, intent: Intent) -> DatabaseView:
        with core.host_epoch_transaction(self.engine) as fence:
            current = self._view(fence)
            _check(current.source_instance == intent.authorization.source_instance and current.identity == intent.new_identity,
                   "epoch-database-changed")
            prepared, _ = current.operation_phases(intent)
            if prepared is not None:
                _check(current.maximum == intent.epoch, "epoch-operation-superseded")
                core.validate_fixed_target(fence, prepared.operation)
            return current


@dataclass(frozen=True)
class ClosedOutcome:
    transition_id: str
    epoch: int
    status: str
    head: JournalHead
    server_admission: str = "OFF"
    collector_mode: str = "QUIESCENT"
    release: str = "NOT-AUTHORIZED"


class HostEpochProtocol:
    """Explicit start/reconcile/abandon only; no retry loop, timer or release."""

    def __init__(self, journal: HostJournal, database: PostgresEpochStore, controls: RequiredHostControls) -> None:
        _check(journal.validator is validate_history, "epoch-journal-validator-required")
        self.journal, self.database, self.controls = journal, database, controls

    def _verify(self, a: HostAuthorization, handoff: ClosedHandoff) -> None:
        _scope(a, handoff)
        _check(a.source_instance == self.journal.source_instance)
        # No default adapter. An absent/failed API is a closed prerequisite, not
        # a fabricated pass or a receipt that grants operational permission.
        try:
            self.controls.verify(a, handoff, self.journal.path)
        except Exception:
            raise HostProtocolError("epoch-control-unavailable") from None

    def start(self, a: HostAuthorization, handoff: ClosedHandoff) -> ClosedOutcome:
        _check(a.action == "begin")
        self._verify(a, handoff)
        virgin = type(handoff.header) is VirginAdmission
        with self.journal.locked(a.expected_head, virgin=virgin) as session:
            self._verify(a, handoff)
            session.confirm_history()
            if not session.records:
                _check(virgin)
                session.append("ADMISSION", {"handoff": handoff.payload(), "authorization": a.payload()})
            history = histories(session.records)
            _check(a.transition_id not in history and all(h.terminal is not None for h in history.values()))
            view = self.database.snapshot()
            _check(view.source_instance == a.source_instance)
            maximum = max((h.intent.epoch for h in history.values()), default=0)
            _check(max(view.maximum, maximum) < MAX_EPOCH, "epoch-exhausted")
            old_identity = None
            if type(handoff.header) is QuiescentHeader:
                old = history.get(handoff.header.transition_id)
                _check(old is not None and old.terminal is not None and old.terminal.kind == "COMPLETE"
                       and old.intent.epoch == handoff.header.epoch, "epoch-consumed-history-missing")
                assert old is not None
                old_identity = old.intent.new_identity
            else:
                _check(not history and not view.phases, "epoch-not-virgin")
            intent = Intent(a, handoff, 1 + max(view.maximum, maximum), view.maximum, maximum,
                            view.checksum, old_identity, view.identity)
            session.append("INTENT", intent.payload())  # reservation burns BEFORE any DB mutation
            return self._advance(session, a, intent)

    def reconcile(self, a: HostAuthorization, handoff: ClosedHandoff) -> ClosedOutcome:
        _check(a.action == "reconcile")
        self._verify(a, handoff)
        with self.journal.locked(a.expected_head) as session:
            item = self._existing(session, a, handoff)
            session.confirm_history()  # explicit approved exact-head resynchronization, not repair
            if item.terminal is not None:
                _check(item.terminal.kind == "COMPLETE", "epoch-operation-abandoned")
                actual = self._read_exact_ready(item.intent, item.receipt)
                _check(actual == DatabasePhase.parse(item.terminal.data["ready"]), "epoch-history-diverged")
                self._verify(a, handoff)
                return ClosedOutcome(a.transition_id, item.intent.epoch, "COMPLETE", session.head)
            return self._advance(session, a, item.intent)

    def abandon(self, a: HostAuthorization, handoff: ClosedHandoff) -> ClosedOutcome:
        _check(a.action == "abandon")
        self._verify(a, handoff)
        with self.journal.locked(a.expected_head) as session:
            item = self._existing(session, a, handoff)
            _check(item.terminal is None, "epoch-operation-terminal")
            session.confirm_history()
            view = self.database.validate_operation(item.intent)
            prepared, ready = view.operation_phases(item.intent)
            # Retire only a conclusively absent operation or exact PREPARED
            # without READY. Retain all DB phases, reservations and receipts;
            # a distinct separately authorized operation must reserve a higher E.
            _check(ready is None and ((prepared is None and view.maximum < item.intent.epoch)
                   or (prepared is not None and view.maximum == item.intent.epoch
                       and (item.receipt is None or prepared == item.receipt.prepared))),
                   "epoch-operation-not-abandonable")
            self._verify(a, handoff)
            session.append("ABANDONED", {"intent_checksum": item.intent_record.checksum,
                "db_digest": view.checksum, "db_max": view.maximum,
                "observed_prepared": prepared.payload() if prepared else None,
                "receipt_checksum": item.receipt_record.checksum if item.receipt_record else None,
                "authorization": a.payload()})
            return ClosedOutcome(a.transition_id, item.intent.epoch, "ABANDONED", session.head)

    def _existing(self, session: JournalSession, a: HostAuthorization, handoff: ClosedHandoff) -> TransitionHistory:
        item = histories(session.records).get(a.transition_id)
        _check(item is not None, "epoch-operation-missing")
        assert item is not None
        _matching_authority(a, item.intent)
        _check(item.intent.handoff == handoff, "epoch-handoff-changed")
        self._verify(a, handoff)
        return item

    def _prepared(self, intent: Intent) -> tuple[DatabasePhase | None, DatabasePhase | None]:
        view = self.database.validate_operation(intent)
        return view.operation_phases(intent)

    def _read_exact_ready(self, intent: Intent, receipt: PreparedReceipt | None) -> DatabasePhase:
        _check(receipt is not None, "epoch-receipt-missing")
        assert receipt is not None
        prepared, ready = self._prepared(intent)
        _check(prepared == receipt.prepared and ready is not None and ready.operation == prepared.operation,
               "epoch-history-diverged")
        assert ready is not None
        return ready

    def _advance(self, session: JournalSession, a: HostAuthorization, intent: Intent) -> ClosedOutcome:
        self._verify(a, intent.handoff)
        item = histories(session.records)[a.transition_id]
        prepared, ready = self._prepared(intent)
        if item.receipt is None:
            _check(ready is None, "epoch-receipt-missing")
            if prepared is None:
                # Unknown commit is NOT presumed rolled back: a fresh exact
                # readback must confirm absence and the immutable original basis.
                self.database.prepare(intent)
                prepared, ready = self._prepared(intent)
            _check(prepared is not None and ready is None, "epoch-prepared-missing")
            assert prepared is not None
            self._verify(a, intent.handoff)
            receipt = PreparedReceipt(item.intent_record.checksum, prepared, _target_token(prepared.operation), a)
            session.append("PREPARED-RECEIPT", receipt.payload())
            item = histories(session.records)[a.transition_id]
        _check(item.receipt is not None and item.receipt_record is not None, "epoch-receipt-missing")
        assert item.receipt is not None and item.receipt_record is not None
        self._verify(a, intent.handoff)
        prepared, ready = self._prepared(intent)
        _check(prepared == item.receipt.prepared, "epoch-receipt-mismatch")
        if ready is None:
            # The session contains only fully written, fsynced records. A plain
            # in-memory PreparedReceipt cannot take this path on its own.
            self.database.ready(intent, item.receipt)
        actual = self._read_exact_ready(intent, item.receipt)
        self._verify(a, intent.handoff)
        session.append("COMPLETE", {"receipt_checksum": item.receipt_record.checksum,
                                   "ready": actual.payload(), "authorization": a.payload()})
        return ClosedOutcome(a.transition_id, intent.epoch, "COMPLETE", session.head)
