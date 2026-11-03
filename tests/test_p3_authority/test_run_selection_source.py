"""P3 T5-O2: a run's selection is recorded at admission and read back by execution_uuid.

The writer is ``DbAdmissionTransport.install`` (the same insert and transaction as
the AdmissionRecord), fed by ``P3CandidateBindings.transport``; the reader is
``RunSelectionSource`` (temper_ai/p3_authority/run_selection_source.py), which
feeds ``DbSelectionSnapshotProvider`` and ``DbRequestHistoryProvider`` through
their existing ``bindings`` callable. Everything stays off by default.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, func, select

from temper_ai.api.caller import Caller
from temper_ai.config.admission_contract import (
    RESERVED_KEY,
    AdmissionRecord,
    AdmissionRefused,
    DescriptorAuthority,
    DispatchIdentity,
    canonical_bytes,
)
from temper_ai.config.admission_contract import RefusalCode as CandidateRefusalCode
from temper_ai.database import get_database, get_session
from temper_ai.p3_authority.candidate_bindings import (
    P3CandidateBindings,
    StaticCallerPeerProvider,
)
from temper_ai.p3_authority.contract import (
    AcceptedData,
    JobKey,
    PreDispatchJob,
    ProjectSelection,
    Refusal,
    RefusalCode,
    RetryKind,
    SelectedJob,
)
from temper_ai.p3_authority.registry import (
    AuthorityRegistryService,
    InMemoryIssuerVerifier,
    InMemoryPeerVerifier,
    SelectionSnapshot,
)
from temper_ai.p3_authority.run_selection_source import (
    STORED_SELECTION_FIELDS,
    RunSelectionSource,
    decode_run_selection,
    encode_admitted_selection,
    encode_run_selection,
)
from temper_ai.p3_authority.selection_snapshot import (
    DEFAULT_REQUEST_HISTORY_PROVIDER,
    DEFAULT_SELECTION_SNAPSHOT_PROVIDER,
    WRITES_ADMITTED,
    DbRequestHistoryProvider,
    DbSelectionSnapshotProvider,
    RunSelectionBinding,
)
from temper_ai.runner.admission import (
    ADMISSION_SELECTION_KEY,
    DbAdmissionTransport,
    preserve_metadata,
    protect_ordinary_update,
)
from temper_ai.runner.models import WorkflowRun
from tests.test_p3_authority._composition_fixtures import (
    PROCESS_RUN,
    PROCESS_SUBMIT,
    TRUSTED_NOW,
    FakePeer,
    make_populated_test_rig,
    make_pre_dispatch_job,
    make_verified_authority,
)
from tests.test_p3_authority.test_selection_snapshot import p3_db  # noqa: F401
from tests.test_runner.test_candidate_admission_integration import (
    AUTHOR,
    QUEUED_NONCE,
    WORKER,
    Case,
    EntryBindings,
)

pytestmark = pytest.mark.usefixtures("p3_db")

EXEC_UUID = "00000000-0000-4000-8000-000000000289"
OTHER_UUID = "00000000-0000-4000-8000-000000000290"


def _row(execution_uuid: str = EXEC_UUID) -> WorkflowRun | None:
    with get_session() as session:
        row = session.scalars(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_uuid)
        ).first()
        if row is not None:
            session.expunge(row)
        return row


def _row_count() -> int:
    with get_session() as session:
        return int(session.scalar(select(func.count()).select_from(WorkflowRun)) or 0)


def _metadata(execution_uuid: str = EXEC_UUID) -> Any:
    row = _row(execution_uuid)
    assert row is not None
    return row.spawner_metadata


def _stored_bytes(execution_uuid: str = EXEC_UUID) -> bytes:
    return canonical_bytes(_metadata(execution_uuid))


def _overwrite_selection(value: Any, execution_uuid: str = EXEC_UUID) -> None:
    """Test-only tamper: replace the stored selection bytes behind the transport."""
    with get_session() as session, session.begin():
        row = session.get(WorkflowRun, execution_uuid)
        assert row is not None
        row.spawner_metadata = {**row.spawner_metadata, ADMISSION_SELECTION_KEY: value}


class Admission:
    """A P3 candidate admission over the existing synthetic V1 primitives."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        execution_uuid: str = EXEC_UUID,
        prefix: str = "_o2",
        job_changes: Callable[[SelectedJob, Case], SelectedJob] | None = None,
    ) -> None:
        self.case = Case(tmp_path, prefix=prefix, execution=execution_uuid)
        self.entry = EntryBindings(self.case)
        self.rig = make_populated_test_rig()
        authority = self.entry.authority
        job = make_pre_dispatch_job(
            designated_workflow=self.case.workflow,
            execution_uuid=execution_uuid,
            selection_revision="sel-o2-1",
            selection=ProjectSelection(
                project_id="proj-o2",
                run_id=execution_uuid,
                kit_id="kit-o2",
                kit_sha256="6" * 64,
                build_sums_sha256="b" * 64,
                publication_ref=make_pre_dispatch_job().selection.publication_ref,
                publication_revision="pub-o2-1",
                build_ref=make_pre_dispatch_job().selection.build_ref,
            ),
            approved_descriptor_digest=authority.expected_descriptor_sha256,
            expected_source_digest=authority.expected_source_sha256,
        )
        self.job = job_changes(job, self.case) if job_changes is not None else job
        snapshot = SelectionSnapshot(
            snapshot_revision="snap-o2-1", jobs=(self.job,), verified_at=TRUSTED_NOW,
        )
        subject = snapshot.subject_for(self.job)
        for ref in (self.job.selector_issuer, *self.job.authority_refs):
            self.rig.issuer_verifier.register_authority(
                ref,
                make_verified_authority(
                    authority=ref,
                    subject=subject,
                    actors=frozenset({PROCESS_SUBMIT, PROCESS_RUN}),
                ),
                job=self.job,
            )
        self.rig.publisher.publish_snapshot(snapshot)
        self.p3 = P3CandidateBindings(
            registry=self.rig.composition.registry,
            caller_peer_provider=StaticCallerPeerProvider(
                submit_peers={(AUTHOR, self.case.workflow): self.rig.peer_submit},
                run_peers={execution_uuid: self.rig.peer_run},
            ),
            delegate_bindings=self.entry,
            designated_workflows=frozenset({self.case.workflow}),
        )
        self.case.store_rows()

    def submit(self, **changes: Any) -> str:
        return self.entry.submit(bindings=self.p3, **changes)

    def source(self, **kwargs: Any) -> RunSelectionSource:
        return RunSelectionSource(self.entry.store, **kwargs)


def _assert_binding_is_job(binding: RunSelectionBinding, job: SelectedJob, authority: DescriptorAuthority) -> None:
    target = job.pre_dispatch_or_running_job
    assert isinstance(target, PreDispatchJob)
    assert binding.execution_uuid == target.execution_uuid
    assert binding.authority == authority
    assert binding.job_revision == target.job_revision
    assert binding.selection_revision == job.selection_revision
    assert binding.selector_issuer == job.selector_issuer
    assert binding.selection == job.selection
    assert binding.reviewed_closure_ref == job.reviewed_closure_ref
    assert binding.compatibility_profile == job.compatibility_profile
    assert binding.authorized_operations == job.authorized_operations
    assert binding.conditions == job.conditions
    assert binding.authority_refs == job.authority_refs
    assert binding.expected_dispatch is None


def _write_watch() -> tuple[list[str], Callable[[], None]]:
    engine = get_database().engine
    writes: list[str] = []

    def on_execute(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        verb = statement.lstrip().split(" ", 1)[0].upper()
        if verb in {"INSERT", "UPDATE", "DELETE", "REPLACE", "ALTER", "DROP", "CREATE"}:
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", on_execute)
    return writes, lambda: event.remove(engine, "before_cursor_execute", on_execute)


# --- happy path -------------------------------------------------------------

def test_combined_admission_records_selection_and_source_feeds_both_providers(
    tmp_path: Path,
) -> None:
    """submit_candidate with P3CandidateBindings commits admission + selection
    together; RunSelectionSource returns the admitted selection; the snapshot
    provider (explicit test clock) and history provider read it read-only."""
    assert WRITES_ADMITTED is False
    assert DEFAULT_SELECTION_SNAPSHOT_PROVIDER is None
    assert DEFAULT_REQUEST_HISTORY_PROVIDER is None

    adm = Admission(tmp_path)
    assert adm.submit() == EXEC_UUID
    # The writer rode on a copy: the delegate's own transport stays writer-free.
    assert adm.entry.store.admission_selection is None

    row = _row()
    assert row is not None and row.status == "queued"
    assert set(row.spawner_metadata) == {RESERVED_KEY, ADMISSION_SELECTION_KEY}
    stored = row.spawner_metadata[ADMISSION_SELECTION_KEY]
    assert stored == encode_run_selection(adm.job)
    # Only the selection-specific fields; no AdmissionRecord field copied.
    assert set(stored) == STORED_SELECTION_FIELDS == {
        "selection", "selection_revision", "selector_issuer", "job_revision",
        "reviewed_closure_ref", "compatibility_profile", "authorized_operations",
        "conditions", "authority_refs", "expected_dispatch",
    }
    record_fields = set(row.spawner_metadata[RESERVED_KEY]["immutable"])
    assert not (STORED_SELECTION_FIELDS & record_fields)
    assert not {"execution_uuid", "descriptor_sha256", "source_sha256", "workflow_name",
                "authorized_caller_label", "authority_receipt_id"} & set(stored)

    source = adm.source(authority_for_run=adm.entry.authority_for_run)
    writes, stop = _write_watch()
    before = _stored_bytes()
    try:
        binding = source.binding_for(EXEC_UUID)
        assert isinstance(binding, RunSelectionBinding)
        _assert_binding_is_job(binding, adm.job, adm.entry.authority)
        assert source.accepted_bindings() == (binding,)

        snapshot_provider = DbSelectionSnapshotProvider(
            adm.entry.store, bindings=source.accepted_bindings, verified_at=TRUSTED_NOW,
        )
        history_provider = DbRequestHistoryProvider(
            adm.entry.store, bindings=source.accepted_bindings,
        )
        snapshot = snapshot_provider.read_snapshot()
        assert snapshot is not None and snapshot.verified_at == TRUSTED_NOW
        assert len(snapshot.jobs) == 1
        job = snapshot.jobs[0]
        assert job.selection_revision == adm.job.selection_revision
        assert job.selection == adm.job.selection
        assert job.pre_dispatch_or_running_job == adm.job.pre_dispatch_or_running_job
        assert history_provider._run_has_valid_admission_envelope(EXEC_UUID) is True

        peer_submit = FakePeer("peer-submit-o2", process=PROCESS_SUBMIT)
        issuer = InMemoryIssuerVerifier()
        service = AuthorityRegistryService(
            snapshot_provider=snapshot_provider,
            issuer_verifier=issuer,
            peer_verifier=InMemoryPeerVerifier(allowed_peers=(peer_submit,)),
            history_provider=history_provider,
        )
        subject = snapshot.subject_for(job)
        for ref in (job.selector_issuer, *job.authority_refs):
            issuer.register_authority(
                ref,
                make_verified_authority(authority=ref, subject=subject,
                                        actors=frozenset({PROCESS_SUBMIT, PROCESS_RUN})),
                job=job,
            )
        submitted = service.for_submit(peer_submit, adm.case.workflow)
        assert isinstance(submitted, AcceptedData)
        assert submitted.data.selection_revision == adm.job.selection_revision
    finally:
        stop()
    assert writes == []
    assert _stored_bytes() == before


# --- missing, non-P3, unavailable --------------------------------------------

def test_missing_selection_refuses_and_non_p3_admission_is_unchanged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    case = Case(tmp_path, prefix="_o2np", execution=EXEC_UUID)
    entry = EntryBindings(case)
    case.store_rows()
    assert entry.submit() == EXEC_UUID  # plain CandidateBindings: no writer
    row = _row()
    assert row is not None and set(row.spawner_metadata) == {RESERVED_KEY}
    assert entry.store.admission_selection is None
    with pytest.raises(AdmissionRefused) as not_callable:
        entry.store.with_admission_selection(None)  # type: ignore[arg-type]
    assert not_callable.value.code is CandidateRefusalCode.TYPE

    # An ordinary run row with no metadata at all.
    with get_session() as session, session.begin():
        session.add(WorkflowRun(execution_id=OTHER_UUID, workflow_name="plain",
                                workspace_path=str(tmp_path), status="queued"))
    with get_session() as session, session.begin():
        plain = session.get(WorkflowRun, OTHER_UUID)
        assert plain is not None
        plain.spawner_metadata = None  # type: ignore[assignment]
    assert _metadata(OTHER_UUID) is None

    source = RunSelectionSource(entry.store)
    for uuid in (EXEC_UUID, OTHER_UUID, "00000000-0000-4000-8000-000000000299", "", object(), None):
        refused = source.binding_for(uuid)
        assert isinstance(refused, Refusal)
        assert refused.code is RefusalCode.SELECTION_MISSING
        assert refused.retry_kind is RetryKind.SAME_BOUNDARY_AFTER_REPAIR
    with caplog.at_level("WARNING", logger="temper_ai.p3_authority.run_selection_source"):
        assert source.accepted_bindings() == ()
        assert RunSelectionSource(None).accepted_bindings() == ()
    assert "Run selection refused" not in caplog.text  # runs with no selection: skipped

    unavailable = RunSelectionSource(None).binding_for(EXEC_UUID)
    assert isinstance(unavailable, Refusal)
    assert unavailable.code is RefusalCode.AUTHORITY_UNAVAILABLE


def test_source_refuses_a_row_whose_admission_record_fails_the_transport_check(
    tmp_path: Path,
) -> None:
    adm = Admission(tmp_path)
    adm.submit()
    other_authority = replace(adm.entry.authority, receipt_id="receipt-other")
    refused = adm.source(authority_for_run=lambda uuid: other_authority).binding_for(EXEC_UUID)
    assert isinstance(refused, Refusal) and refused.code is RefusalCode.SELECTION_MISSING

    def refusing(uuid: str) -> DescriptorAuthority:
        raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)

    refused = adm.source(authority_for_run=refusing).binding_for(EXEC_UUID)
    assert isinstance(refused, Refusal) and refused.code is RefusalCode.SELECTION_MISSING

    # Tampered admission record (same selection) -> the row check refuses.
    with get_session() as session, session.begin():
        row = session.get(WorkflowRun, EXEC_UUID)
        assert row is not None
        meta = copy.deepcopy(row.spawner_metadata)
        meta[RESERVED_KEY]["immutable"]["authorized_caller_label"] = "someone-else"
        row.spawner_metadata = meta
    refused = adm.source().binding_for(EXEC_UUID)
    assert isinstance(refused, Refusal) and refused.code is RefusalCode.SELECTION_MISSING


# --- malformed stored selection ---------------------------------------------

def _mutations() -> dict[str, Callable[[dict[str, Any]], Any]]:
    def set_path(path: tuple[Any, ...], value: Any) -> Callable[[dict[str, Any]], Any]:
        def mutate(stored: dict[str, Any]) -> Any:
            target = stored
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            return stored
        return mutate

    def drop(key: str) -> Callable[[dict[str, Any]], Any]:
        def mutate(stored: dict[str, Any]) -> Any:
            del stored[key]
            return stored
        return mutate

    def reorder_operations(stored: dict[str, Any]) -> Any:
        stored["authorized_operations"] = list(reversed(stored["authorized_operations"]))
        return stored

    def duplicate_operation(stored: dict[str, Any]) -> Any:
        stored["authorized_operations"] = stored["authorized_operations"] + stored["authorized_operations"][:1]
        return stored

    foreign_dispatch = {
        "execution_uuid": OTHER_UUID,
        "dispatch_nonce": "00000000-0000-4000-8000-000000000291",
        "running_attempt": 1,
    }
    cases: dict[str, Callable[[dict[str, Any]], Any]] = {
        "not an object": lambda stored: "selection",
        "null": lambda stored: None,
        "extra key": set_path(("signature",), "x"),
        "copied record field": set_path(("descriptor_sha256",), "0" * 64),
        "dispatch for another run": set_path(("expected_dispatch",), foreign_dispatch),
        "dispatch attempt zero": set_path(("expected_dispatch",), {**foreign_dispatch, "execution_uuid": EXEC_UUID, "running_attempt": 0}),
        "empty selection_revision": set_path(("selection_revision",), ""),
        "int selection_revision": set_path(("selection_revision",), 1),
        "empty job_revision": set_path(("job_revision",), ""),
        "dispatch attempt bool": set_path(("expected_dispatch",), {**foreign_dispatch, "execution_uuid": EXEC_UUID, "running_attempt": True}),
        "dispatch nonce not a uuid": set_path(("expected_dispatch",), {**foreign_dispatch, "execution_uuid": EXEC_UUID, "dispatch_nonce": "nonce"}),
        "selection not an object": set_path(("selection",), "project"),
        "unknown selection kind": set_path(("selection", "kind"), "other"),
        "selection extra key": set_path(("selection", "route"), "x"),
        "selector issuer missing id": set_path(("selector_issuer", "issuer_id"), ""),
        "closure length zero": set_path(("reviewed_closure_ref", "length"), 0),
        "closure length bool": set_path(("reviewed_closure_ref", "length"), True),
        "closure length text": set_path(("reviewed_closure_ref", "length"), "128"),
        "profile inspect": set_path(("compatibility_profile", "inspect"), "/3"),
        "profile corpus": set_path(("compatibility_profile", "corpus"), "other/1"),
        "operations not a list": set_path(("authorized_operations",), {}),
        "operations unsorted": reorder_operations,
        "operations duplicated": duplicate_operation,
        "condition missing id": set_path(("conditions", 0, "condition_id"), ""),
        "authority refs not a list": set_path(("authority_refs",), "ref"),
    }
    for key in sorted(STORED_SELECTION_FIELDS):
        cases[f"missing {key}"] = drop(key)
    return cases


@pytest.mark.parametrize("name", sorted(_mutations()))
def test_each_malformed_stored_field_refuses(
    tmp_path: Path, name: str, caplog: pytest.LogCaptureFixture,
) -> None:
    adm = Admission(tmp_path)
    adm.submit()
    good = _metadata()[ADMISSION_SELECTION_KEY]
    assert len(good["authorized_operations"]) > 1  # the order and duplicate cases bite
    bad = _mutations()[name](copy.deepcopy(good))
    # The dispatch's run is checked against the row by the source, not the decoder.
    assert (decode_run_selection(bad) is None) is (name != "dispatch for another run")
    _overwrite_selection(bad)
    refused = adm.source().binding_for(EXEC_UUID)
    assert isinstance(refused, Refusal)
    assert refused.code is RefusalCode.SELECTION_MISSING
    assert refused.retry_kind is RetryKind.NEW_BINDING_REQUIRED
    caplog.clear()
    with caplog.at_level("WARNING", logger="temper_ai.p3_authority.run_selection_source"):
        assert adm.source().accepted_bindings() == ()
    assert f"Run selection refused for {EXEC_UUID}: selection_missing" in caplog.text


def test_finished_runs_are_not_current_selections(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    adm = Admission(tmp_path)
    adm.submit()
    with get_session() as session, session.begin():
        row = session.get(WorkflowRun, EXEC_UUID)
        assert row is not None
        row.status = "completed"
    with caplog.at_level("WARNING", logger="temper_ai.p3_authority.run_selection_source"):
        assert adm.source().accepted_bindings() == ()
    assert "Run selection refused" not in caplog.text
    refused = adm.source().binding_for(EXEC_UUID)
    assert isinstance(refused, Refusal) and refused.code is RefusalCode.SELECTION_MISSING


def test_stored_running_dispatch_for_this_run_is_accepted(tmp_path: Path) -> None:
    adm = Admission(tmp_path)
    adm.submit()
    good = copy.deepcopy(_metadata()[ADMISSION_SELECTION_KEY])
    dispatch = {"execution_uuid": EXEC_UUID, "dispatch_nonce": QUEUED_NONCE, "running_attempt": 1}
    good["expected_dispatch"] = dispatch
    fields = decode_run_selection(good)
    assert fields is not None
    assert fields["expected_dispatch"] == DispatchIdentity(EXEC_UUID, QUEUED_NONCE, 1)
    _overwrite_selection(good)
    binding = adm.source().binding_for(EXEC_UUID)
    assert isinstance(binding, RunSelectionBinding)
    assert binding.expected_dispatch == DispatchIdentity(EXEC_UUID, QUEUED_NONCE, 1)


# --- once and immutable -----------------------------------------------------

def test_second_admission_is_refused_and_stored_bytes_stay(tmp_path: Path) -> None:
    adm = Admission(tmp_path)
    adm.submit()
    before = _stored_bytes()
    with pytest.raises(AdmissionRefused) as again:
        adm.submit()
    assert again.value.code is CandidateRefusalCode.PROTECTED
    assert _stored_bytes() == before

    record = AdmissionRecord(canonical_bytes(_metadata()[RESERVED_KEY]))
    transport = adm.p3.transport(adm.entry.authority)
    with pytest.raises(AdmissionRefused) as direct:
        with get_session() as session, session.begin():
            transport.install(admission=adm.entry.codec.record(record.wire, adm.entry.authority),
                              transaction=session)
    assert direct.value.code is CandidateRefusalCode.PROTECTED
    assert _stored_bytes() == before
    assert _row_count() == 1


def test_ordinary_metadata_writers_cannot_replace_the_selection(tmp_path: Path) -> None:
    adm = Admission(tmp_path)
    adm.submit()
    row = _row()
    assert row is not None
    for extra in ({ADMISSION_SELECTION_KEY: {}}, {ADMISSION_SELECTION_KEY: row.spawner_metadata[ADMISSION_SELECTION_KEY]}):
        with pytest.raises(AdmissionRefused) as refused:
            preserve_metadata(row.spawner_metadata, extra)
        assert refused.value.code is CandidateRefusalCode.PROTECTED
        with pytest.raises(AdmissionRefused):
            protect_ordinary_update(row, {"spawner_metadata": extra})
        with pytest.raises(AdmissionRefused):
            adm.entry.store.preserve(
                AdmissionRecord(canonical_bytes(row.spawner_metadata[RESERVED_KEY])), extra,
            )
    assert preserve_metadata(row.spawner_metadata, {"note": "x"})[ADMISSION_SELECTION_KEY] == (
        row.spawner_metadata[ADMISSION_SELECTION_KEY]
    )


def test_dispatch_bind_keeps_the_selection_bytes(tmp_path: Path) -> None:
    adm = Admission(tmp_path)
    adm.submit()
    before = canonical_bytes(_metadata()[ADMISSION_SELECTION_KEY])
    queued = adm.entry.codec.record(canonical_bytes(_metadata()[RESERVED_KEY]), adm.entry.authority)
    running = copy.deepcopy(queued.value())
    running["dispatch"] = {
        "phase": "running",
        "dispatch_nonce": "00000000-0000-4000-8000-000000000292",
        "running_attempt": 1,
        "previous_nonce": QUEUED_NONCE,
        "worker_label": WORKER,
    }
    with get_session() as session, session.begin():
        adm.entry.store.bind_dispatch(
            queued, adm.entry.codec.record(canonical_bytes(running), adm.entry.authority),
            transaction=session,
        )
    row = _row()
    assert row is not None and row.status == "running"
    assert canonical_bytes(row.spawner_metadata[ADMISSION_SELECTION_KEY]) == before
    binding = adm.source().binding_for(EXEC_UUID)
    assert isinstance(binding, RunSelectionBinding)
    _assert_binding_is_job(binding, adm.job, adm.entry.authority)


# --- same transaction -------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    ["other execution_uuid", "other workflow", "other descriptor digest",
     "approved digest not the record's", "approved digest not the authority's",
     "other source digest", "other source pin", "running job"],
)
def test_writer_refuses_a_selection_not_for_this_admission(tmp_path: Path, name: str) -> None:
    """Each condition of encode_admitted_selection has a case only it refuses."""
    adm = Admission(tmp_path)
    target = adm.job.pre_dispatch_or_running_job
    assert isinstance(target, PreDispatchJob)
    zero = "0" * 64
    pinned = adm.entry.authority
    changed, authority = {
        "other execution_uuid": (replace(adm.job, pre_dispatch_or_running_job=replace(target, execution_uuid=OTHER_UUID)), pinned),
        "other workflow": (replace(adm.job, pre_dispatch_or_running_job=replace(target, designated_workflow="other_wf")), pinned),
        "other descriptor digest": (replace(adm.job, pre_dispatch_or_running_job=replace(target, descriptor_digest=zero)), pinned),
        "approved digest not the record's": (
            replace(adm.job, approved_descriptor_digest=zero),
            replace(pinned, expected_descriptor_sha256=zero),
        ),
        "approved digest not the authority's": (adm.job, replace(pinned, expected_descriptor_sha256=zero)),
        "other source digest": (replace(adm.job, expected_source_digest=zero), pinned),
        "other source pin": (adm.job, replace(pinned, expected_source_sha256=zero)),
        "running job": (replace(adm.job, pre_dispatch_or_running_job=JobKey(
            dispatch=DispatchIdentity(EXEC_UUID, QUEUED_NONCE, 1), job_revision="job-rev-1",
        )), pinned),
    }[name]

    submitted_record: list[AdmissionRecord] = []
    original_install = DbAdmissionTransport.install

    def capture(self: DbAdmissionTransport, *, admission: AdmissionRecord, transaction: object) -> None:
        submitted_record.append(admission)
        original_install(self, admission=admission, transaction=transaction)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(DbAdmissionTransport, "install", capture)
        adm.submit()
    assert _row_count() == 1
    record = submitted_record[0]
    with pytest.raises(AdmissionRefused) as refused:
        encode_admitted_selection(changed, authority=authority, record=record)
    assert refused.value.code is CandidateRefusalCode.LOOKUP
    assert encode_admitted_selection(adm.job, authority=pinned, record=record) == encode_run_selection(adm.job)


def test_encoders_refuse_what_they_cannot_store(tmp_path: Path) -> None:
    adm = Admission(tmp_path)
    with pytest.raises(AdmissionRefused) as not_a_job:
        encode_run_selection(None)  # type: ignore[arg-type]
    assert not_a_job.value.code is CandidateRefusalCode.LOOKUP
    with pytest.raises(AdmissionRefused) as unreadable:
        encode_run_selection(replace(adm.job, selection_revision=""))
    assert unreadable.value.code is CandidateRefusalCode.LOOKUP
    with pytest.raises(AdmissionRefused) as not_a_record:
        encode_admitted_selection(adm.job, authority=adm.entry.authority, record=None)  # type: ignore[arg-type]
    assert not_a_record.value.code is CandidateRefusalCode.LOOKUP


def test_writer_uses_the_selection_of_this_authority(tmp_path: Path) -> None:
    """Another authority's recorded selection, recorded first, is never the one stored."""
    adm = Admission(tmp_path)
    adm.p3.authority_for_submit(Caller(name=AUTHOR), adm.case.workflow)
    mine = adm.p3._recorded_submit_bindings[adm.case.workflow]  # noqa: SLF001
    target = adm.job.pre_dispatch_or_running_job
    assert isinstance(target, PreDispatchJob)
    theirs = replace(
        mine,
        selected_job=replace(adm.job, pre_dispatch_or_running_job=replace(target, execution_uuid=OTHER_UUID)),
        descriptor_authority=replace(adm.entry.authority, receipt_id="receipt-other"),
    )
    adm.p3._recorded_submit_bindings = {"other_wf": theirs, adm.case.workflow: mine}  # noqa: SLF001
    assert adm.submit() == EXEC_UUID
    assert _metadata()[ADMISSION_SELECTION_KEY] == encode_run_selection(adm.job)


def test_own_transport_also_stores_the_selection() -> None:
    """P3CandidateBindings without a delegate builds its own transport: it carries the writer too."""
    rig = make_populated_test_rig()
    bindings = rig.composition.candidate_bindings
    assert isinstance(bindings, P3CandidateBindings) and bindings._delegate_bindings is None  # noqa: SLF001
    authority = bindings.authority_for_submit(Caller(name="p3-authorized-caller"), "designated_v1")
    transport = bindings.transport(authority)
    assert isinstance(transport, DbAdmissionTransport)
    assert transport.admission_selection is not None
    with pytest.raises(AdmissionRefused) as refused:
        transport.admission_selection(None)  # type: ignore[arg-type]
    assert refused.value.code is CandidateRefusalCode.LOOKUP


def test_writer_refusal_rolls_the_admission_back(tmp_path: Path) -> None:
    adm = Admission(
        tmp_path,
        job_changes=lambda job, case: replace(
            job,
            pre_dispatch_or_running_job=replace(job.pre_dispatch_or_running_job, execution_uuid=OTHER_UUID),
        ),
    )
    with pytest.raises(AdmissionRefused) as refused:
        adm.submit()
    assert refused.value.code is CandidateRefusalCode.LOOKUP
    assert _row_count() == 0


@pytest.mark.parametrize("bad", ["not a mapping", {"value": float("nan")}, {1: "x"}])
def test_malformed_writer_output_refuses_and_rolls_back(tmp_path: Path, bad: Any) -> None:
    adm = Admission(tmp_path)
    original = adm.p3.transport

    def bad_transport(authority: DescriptorAuthority) -> DbAdmissionTransport:
        return original(authority).with_admission_selection(lambda record: bad)

    adm.p3.transport = bad_transport  # type: ignore[method-assign]
    with pytest.raises(AdmissionRefused) as refused:
        adm.submit()
    assert refused.value.code in (
        CandidateRefusalCode.TYPE, CandidateRefusalCode.CANONICAL, CandidateRefusalCode.NONFINITE,
    )
    assert _row_count() == 0


def test_refused_admission_leaves_no_selection(tmp_path: Path) -> None:
    adm = Admission(tmp_path)
    adm.entry.verify_install = lambda admission, *, transaction: False  # type: ignore[method-assign]
    with pytest.raises(AdmissionRefused) as refused:
        adm.submit()
    assert refused.value.code is CandidateRefusalCode.AUTHORITY
    assert _row_count() == 0


def test_no_submit_selection_for_the_authority_refuses(tmp_path: Path) -> None:
    adm = Admission(tmp_path)
    record_holder: list[AdmissionRecord] = []
    original_install = DbAdmissionTransport.install

    def capture(self: DbAdmissionTransport, *, admission: AdmissionRecord, transaction: object) -> None:
        record_holder.append(admission)
        original_install(self, admission=admission, transaction=transaction)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(DbAdmissionTransport, "install", capture)
        adm.submit()
    with pytest.raises(AdmissionRefused) as refused:
        encode_admitted_selection(None, authority=adm.entry.authority, record=record_holder[0])
    assert refused.value.code is CandidateRefusalCode.LOOKUP

    class OtherTransportDelegate(EntryBindings):
        def transport(self, authority: DescriptorAuthority) -> Any:
            return object()

    (tmp_path / "other").mkdir()
    other = Admission(tmp_path / "other", execution_uuid=OTHER_UUID, prefix="_o2b")
    other.p3._delegate_bindings = OtherTransportDelegate(other.case)  # noqa: SLF001
    authority = other.p3.authority_for_submit(Caller(name=AUTHOR), other.case.workflow)
    with pytest.raises(AdmissionRefused) as not_transport:
        other.p3.transport(authority)
    assert not_transport.value.code is CandidateRefusalCode.AUTHORITY


# --- clock ------------------------------------------------------------------

def test_no_verified_at_gives_no_snapshot_and_registry_refuses(tmp_path: Path) -> None:
    import temper_ai.p3_authority.selection_snapshot as snapshot_module

    assert not hasattr(snapshot_module, "_DEFAULT_VERIFIED_AT")
    adm = Admission(tmp_path)
    adm.submit()
    source = adm.source()
    provider = DbSelectionSnapshotProvider(adm.entry.store, bindings=source.accepted_bindings)
    assert provider.read_snapshot() is None
    peer = FakePeer("peer-submit-clock", process=PROCESS_SUBMIT)
    service = AuthorityRegistryService(
        snapshot_provider=provider,
        issuer_verifier=InMemoryIssuerVerifier(),
        peer_verifier=InMemoryPeerVerifier(allowed_peers=(peer,)),
        history_provider=DbRequestHistoryProvider(adm.entry.store, bindings=source.accepted_bindings),
    )
    refused = service.for_submit(peer, adm.case.workflow)
    assert isinstance(refused, Refusal)
    assert refused.code is RefusalCode.AUTHORITY_UNAVAILABLE
    with_clock = DbSelectionSnapshotProvider(
        adm.entry.store, bindings=source.accepted_bindings, verified_at=TRUSTED_NOW,
    )
    snapshot = with_clock.read_snapshot()
    assert snapshot is not None and len(snapshot.jobs) == 1
