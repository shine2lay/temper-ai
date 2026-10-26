"""Protected candidate run transport. No production authority adapter is installed.

The public codec/types are data, not capabilities. A composed caller boundary must
supply independently authenticated authority, current source facts and the T1/T3
verifiers. This module never manufactures those from a request or a stored record.
Old binaries do not gain these fences; see docs/candidate-admission-lifecycle.md.
"""
from __future__ import annotations

import copy
import logging
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from temper_ai.config.admission_contract import (
    RESERVED_KEY,
    AdmissionRecord,
    AdmissionRefused,
    ContractCodec,
    DescriptorAuthority,
    FrozenJSON,
    RefusalCode,
    RootReadiness,
    canonical_bytes,
    check_dispatch_transition,
    check_preserved,
    check_readiness_transition,
    decode_canonical,
    require_custody,
    require_mode,
    require_source,
)
from temper_ai.database import get_session
from temper_ai.runner.lanes import lane_for
from temper_ai.runner.models import WorkflowRun
from temper_ai.shared.clock import utcnow

if TYPE_CHECKING:
    from temper_ai.api.caller import Caller
    from temper_ai.config.admission_contract import ApprovedCandidateDescriptor
    from temper_ai.runner.context import RunnerContext
    from temper_ai.shared.types import ExecutionContext
    from temper_ai.stage.models import WorkflowConfig
    from temper_ai.stage.node import Node

logger = logging.getLogger(__name__)
T = TypeVar("T")


class CandidateBindings(Protocol):
    """Injected composition boundary, not installed by this source candidate.

    authority_for_submit/authority_for_run read an independently authorized
    registry, NEVER pins/provenance supplied by candidate wire. prepare supplies
    T1's verified raw capture; bootstrap/load/bind_context supply T1/T3 snapshots.
    Synthetic implementations exercise transport only, not composed enforcement.
    """

    def designated(self, workflow_name: str) -> bool: ...
    def authority_for_submit(self, caller: Caller, workflow_name: str) -> DescriptorAuthority: ...
    def authority_for_run(self, execution_uuid: str) -> DescriptorAuthority: ...
    def transport(self, authority: DescriptorAuthority) -> DbAdmissionTransport: ...
    def prepare(self, descriptor: ApprovedCandidateDescriptor, *, request: FrozenJSON,
                transaction: Session) -> AdmissionRecord: ...
    def bootstrap_snapshot(self, record: AdmissionRecord) -> RunnerContext: ...
    def load_snapshot(self, record: AdmissionRecord, runner_ctx: RunnerContext) -> tuple[list[Node], WorkflowConfig]: ...
    def bind_context(self, record: AdmissionRecord, context: ExecutionContext) -> ExecutionContext: ...


def submit_candidate(*, descriptor_wire: bytes, caller: Caller | None,
                     workflow_name: str, workspace_path: str | None,
                     inputs: dict, request: FrozenJSON, execution_id: str | None,
                     mode: str, bindings: CandidateBindings | None) -> str:
    """Authorized external-fresh ingress, prior to ordinary graph/default loading."""
    require_mode(mode)
    if bindings is None or caller is None or not caller.name:
        raise AdmissionRefused(RefusalCode.AUTHORITY)
    authority = bindings.authority_for_submit(caller, workflow_name)
    if authority.authorized_caller_label != caller.label:
        raise AdmissionRefused(RefusalCode.AUTHORITY)
    transport = bindings.transport(authority)
    descriptor = transport.codec.descriptor(descriptor_wire, authority)
    d = descriptor.value()
    if (workflow_name != d["workflow_name"] or workspace_path != d["workspace_path"]
            or canonical_bytes(inputs) != d["metadata_inputs_json"].encode("utf-8")
            or request.wire != d["request_options_json"].encode("utf-8")
            or (execution_id is not None and execution_id != d["execution_uuid"])):
        raise AdmissionRefused(RefusalCode.PROTECTED)
    with get_session() as session:
        admission = bindings.prepare(descriptor, request=request, transaction=session)
        # prepare cannot substitute another descriptor, even if its factory bound
        # another transport authority by mistake.
        if admission.value()["immutable"]["descriptor_json"].encode("utf-8") != descriptor.wire:
            raise AdmissionRefused(RefusalCode.AUTHORITY)
        transport.install(admission=admission, transaction=session)
    return d["execution_uuid"]


def is_designated(workflow_name: str, bindings: CandidateBindings | None) -> bool:
    return bindings is not None and bindings.designated(workflow_name)


class InstallationVerifier(Protocol):
    """Trusted T1/caller adapter: capture/graph/request/custody in this transaction.

    Not a request boolean or an echo of codec validation. A real adapter remains
    V1 work; an absent adapter refuses, and synthetic adapters prove only T2.
    """

    def verify_install(self, admission: AdmissionRecord, *, transaction: Session) -> bool: ...

    def captured_nodes(self, admission: AdmissionRecord, *, transaction: Session) -> Iterable[Node]:
        """The verified capture's resolved graph, never a load by mutable name.

        Non-empty; the same graph load_snapshot runs. An empty capture is refused.
        """
        ...


class PreparationVerifier(Protocol):
    """T3 verifies successful engine NodeResult + durable checkpoint provenance."""

    def verify_preparation(self, current: AdmissionRecord, receipt: RootReadiness,
                           provenance: object, *, transaction: Session) -> bool: ...


def has_admission(metadata: Mapping[str, Any] | None) -> bool:
    """Presence, not truthiness or version: malformed/null records fence too."""
    return metadata is not None and RESERVED_KEY in metadata


def refuse_reserved_extra(extra: Mapping[str, Any] | None) -> None:
    if has_admission(extra):
        raise AdmissionRefused(RefusalCode.PROTECTED)


def preserve_metadata(current: Mapping[str, Any] | None,
                      extra: Mapping[str, Any]) -> dict[str, Any]:
    """Merge only ordinary metadata. Own copies; even an equal reserved extra refuses.

    Deliberately version-agnostic so a rollback tombstone keeps unknown bytes too.
    Typed dispatch/readiness transitions do NOT pass through this ordinary writer.
    """
    if not isinstance(extra, Mapping):
        raise AdmissionRefused(RefusalCode.TYPE)
    refuse_reserved_extra(extra)
    return copy.deepcopy({**(current or {}), **extra})


def refuse_legacy_row(row: WorkflowRun | None) -> None:
    if row is not None and has_admission(row.spawner_metadata):
        raise AdmissionRefused(RefusalCode.MODE)


def refuse_legacy_entry(execution_id: str | None = None, *,
                        designated_candidate: bool = False,
                        supported_code: bool = True) -> None:
    """Pre-load tombstone for unsupported entries, independent of workflow names.

    Classification must come from the trusted raw/caller boundary, not a candidate
    declaring itself ordinary. Missing classification composition is not supplied
    by this helper. Presence on the row always wins over a rename/reclassification.
    """
    if execution_id is not None:
        with get_session() as session:
            row = session.get(WorkflowRun, execution_id)
            if row is not None and has_admission(row.spawner_metadata):
                code = RefusalCode.MODE if supported_code else RefusalCode.ROLLBACK
                raise AdmissionRefused(code)
    if designated_candidate:
        raise AdmissionRefused(RefusalCode.MISSING)


def protect_ordinary_update(row: WorkflowRun, fields: Mapping[str, Any]) -> dict[str, Any]:
    """Generic worker patch cannot mutate admission identity/generation or replace JSON."""
    values = dict(fields)
    if "spawner_metadata" in values:
        values["spawner_metadata"] = preserve_metadata(row.spawner_metadata, values["spawner_metadata"])
    if has_admission(row.spawner_metadata):
        for key in ("execution_id", "workflow_name", "workspace_path", "inputs", "attempts"):
            if key in values and canonical_bytes(values[key]) != canonical_bytes(getattr(row, key)):
                raise AdmissionRefused(RefusalCode.PROTECTED)
        if "status" in values and values["status"] in ("queued", "running", "waiting"):
            raise AdmissionRefused(RefusalCode.GENERATION)
    return values


def require_session(transaction: object) -> Session:
    if not isinstance(transaction, Session):
        raise AdmissionRefused(RefusalCode.TYPE)
    return transaction


def locked_run(transaction: object, execution_uuid: str) -> WorkflowRun | None:
    """Fresh FOR UPDATE row, held until the caller's transaction ends.

    SQLite ignores FOR UPDATE. A same-value UPDATE first obtains its write lock;
    PostgreSQL uses its native row lock. No commit here, and no process-only lock
    substituted for PostgreSQL. All transport decisions use this same fence.
    """
    transaction = require_session(transaction)
    if transaction.get_bind().dialect.name == "sqlite":
        transaction.exec(update(WorkflowRun).where(
            col(WorkflowRun.execution_id) == execution_uuid,
        ).values(execution_id=WorkflowRun.execution_id))
    return transaction.exec(
        select(WorkflowRun).where(WorkflowRun.execution_id == execution_uuid)
        .with_for_update().execution_options(populate_existing=True),
    ).first()


class DbAdmissionTransport:
    """Frozen AdmissionTransport implementation, bound to externally obtained pins.

    Construction is dependency injection, NOT authentication. No production caller
    constructs this yet. The ingress adapter must use the existing Caller checks
    plus independently provisioned expected pins/receipt; a caller label alone is
    insufficient. Current source is independently measured on each operation.
    """

    def __init__(self, *, codec: ContractCodec, authority: DescriptorAuthority,
                 current_source: Callable[[], FrozenJSON],
                 installation: InstallationVerifier | None = None,
                 preparation: PreparationVerifier | None = None,
                 worker_identity: Callable[[], str] | None = None):
        self.codec = codec
        self.authority = authority
        self.current_source = current_source
        self.installation = installation
        self.preparation = preparation
        self.worker_identity = worker_identity

    def _checked(self, record: AdmissionRecord) -> AdmissionRecord:
        if type(record) is not AdmissionRecord:
            raise AdmissionRefused(RefusalCode.TYPE)
        checked = self.codec.record(record.wire, self.authority)
        descriptor = self.codec.descriptor(
            checked.value()["immutable"]["descriptor_json"].encode("utf-8"), self.authority,
        )
        require_source(descriptor, self.current_source())
        require_custody(descriptor)
        return checked

    def _descriptor(self, record: AdmissionRecord) -> dict[str, Any]:
        return decode_canonical(record.value()["immutable"]["descriptor_json"].encode("utf-8"))

    def _row_record(self, row: WorkflowRun | None) -> AdmissionRecord:
        if row is None or not has_admission(row.spawner_metadata):
            raise AdmissionRefused(RefusalCode.MISSING)
        record = self._checked(AdmissionRecord(canonical_bytes(row.spawner_metadata[RESERVED_KEY])))
        descriptor = self._descriptor(record)
        dispatch = record.value()["dispatch"]
        if (row.execution_id != descriptor["execution_uuid"]
                or row.workflow_name != descriptor["workflow_name"]
                or row.workspace_path != descriptor["workspace_path"]
                or canonical_bytes(row.inputs) != descriptor["metadata_inputs_json"].encode("utf-8")):
            raise AdmissionRefused(RefusalCode.PROTECTED)
        if (row.status != dispatch["phase"] or row.attempts != dispatch["running_attempt"]
                or row.cancel_requested):
            raise AdmissionRefused(RefusalCode.GENERATION)
        # Fresh only, never resume/fork/rerun/cleanup/replacement or the Pi lane.
        if any(key in row.spawner_metadata for key in ("start", "rerun", "only", "lane")):
            raise AdmissionRefused(RefusalCode.MODE)
        return record

    def _locked_record(self, transaction: object, execution_uuid: str) -> tuple[WorkflowRun, AdmissionRecord]:
        row = locked_run(transaction, execution_uuid)
        if row is None:
            raise AdmissionRefused(RefusalCode.MISSING)
        return row, self._row_record(row)

    def install(self, *, admission: AdmissionRecord, transaction: object) -> None:
        transaction = require_session(transaction)
        checked = self._checked(admission)
        descriptor = self._descriptor(checked)
        if checked.value()["dispatch"]["phase"] != "queued":
            raise AdmissionRefused(RefusalCode.GENERATION)
        if locked_run(transaction, descriptor["execution_uuid"]) is not None:
            raise AdmissionRefused(RefusalCode.PROTECTED)
        if (self.installation is None or self.installation.verify_install(
                checked, transaction=transaction) is not True):
            raise AdmissionRefused(RefusalCode.AUTHORITY)
        # Main-lane rows only, written with no mark: an unmarked Pi run would be claimed by
        # the main watcher. The existing lane decision, on the verified capture's graph;
        # an empty capture would read as main lane whatever the real graph is: refused.
        nodes = tuple(self.installation.captured_nodes(checked, transaction=transaction))
        if not nodes:
            raise AdmissionRefused(RefusalCode.AUTHORITY)
        if lane_for(nodes) is not None:
            raise AdmissionRefused(RefusalCode.MODE)
        # The PK, not a SELECT alone, arbitrates two installs of an absent row.
        # A savepoint translates collision without silently aborting the outer work.
        try:
            with transaction.begin_nested():
                transaction.add(WorkflowRun(
                    execution_id=descriptor["execution_uuid"],
                    workflow_name=descriptor["workflow_name"],
                    workspace_path=descriptor["workspace_path"],
                    inputs=decode_canonical(descriptor["metadata_inputs_json"].encode("utf-8")),
                    status="queued",
                    spawner_metadata={RESERVED_KEY: checked.value()},
                ))
                transaction.flush()
        except IntegrityError:
            raise AdmissionRefused(RefusalCode.PROTECTED) from None
        logger.info("Candidate admission installed (queued, attempt 0)")

    def restore(self, *, execution_uuid: str, authority: DescriptorAuthority,
                mode: str) -> AdmissionRecord:
        require_mode(mode)
        if authority != self.authority:
            raise AdmissionRefused(RefusalCode.AUTHORITY)
        with get_session() as session:
            _, record = self._locked_record(session, execution_uuid)
        logger.info("Candidate admission restored from protected snapshot")
        return record

    def preserve(self, current: AdmissionRecord, extra: Mapping[str, Any]) -> AdmissionRecord:
        refuse_reserved_extra(extra)
        return self._checked(current)

    def bind_dispatch(self, current: AdmissionRecord, proposed: AdmissionRecord, *,
                      transaction: object) -> None:
        transaction = require_session(transaction)
        before, after = self._checked(current), self._checked(proposed)
        check_dispatch_transition(before, after)
        worker_label = None if self.worker_identity is None else self.worker_identity()
        if (worker_label is None
                or after.value()["dispatch"]["worker_label"] != worker_label
                or any(p["root_policy"]["worker_label"] != worker_label
                       for p in self._descriptor(after)["positions"])):
            raise AdmissionRefused(RefusalCode.GENERATION)
        row, held = self._locked_record(transaction, self._descriptor(before)["execution_uuid"])
        check_preserved(before, held)
        row.spawner_metadata = {**row.spawner_metadata, RESERVED_KEY: after.value()}
        row.status = "running"
        row.attempts = 1
        row.started_at = utcnow()
        transaction.add(row)
        transaction.flush()
        logger.info("Candidate admission dispatch bound (running, attempt 1)")

    def bind_root_readiness(self, current: AdmissionRecord, receipt: RootReadiness, *,
                            verified_preparation: object, transaction: object) -> AdmissionRecord:
        transaction = require_session(transaction)
        before = self._checked(current)
        if type(receipt) is not RootReadiness:
            raise AdmissionRefused(RefusalCode.TYPE)
        receipt = self.codec.readiness(receipt.wire)
        row, held = self._locked_record(transaction, self._descriptor(before)["execution_uuid"])
        # Other positions may have completed since the caller's snapshot. Only their
        # readiness may differ; merge while locked, preserving every one of them.
        b, h = before.value(), held.value()
        if canonical_bytes({k: v for k, v in b.items() if k != "readiness"}) != canonical_bytes(
                {k: v for k, v in h.items() if k != "readiness"}):
            raise AdmissionRefused(RefusalCode.GENERATION)
        if (self.preparation is None or self.preparation.verify_preparation(
                held, receipt, verified_preparation, transaction=transaction) is not True):
            raise AdmissionRefused(RefusalCode.READINESS)
        proposal = held.value()
        if not any(r["position_id"] == receipt.value()["position_id"] for r in proposal["readiness"]):
            proposal["readiness"].append(receipt.value())
        after = self._checked(AdmissionRecord(canonical_bytes(proposal)))
        check_readiness_transition(held, after, receipt)
        row.spawner_metadata = {**row.spawner_metadata, RESERVED_KEY: after.value()}
        transaction.add(row)
        transaction.flush()
        logger.info("Candidate admission readiness bound (compare-once)")
        return after

    def claim_if_current(self, current: AdmissionRecord, claim: Callable[[], T]) -> T:
        """Hold row fence through native EXCLUSIVE CLAIM ONLY; never a network send.

        T3 must do same-fd/context/config/readiness verification before supplying
        the native callback. Native single-use claim/single-send stays authoritative.
        No arbitrary callback is made safe merely by being passed to this method.
        """
        before = self._checked(current)
        with get_session() as session:
            _, held = self._locked_record(session, self._descriptor(before)["execution_uuid"])
            check_preserved(before, held)
            if before.value()["dispatch"]["phase"] != "running":
                raise AdmissionRefused(RefusalCode.GENERATION)
            result = claim()
            logger.info("Candidate admission current generation fenced native claim")
            return result
