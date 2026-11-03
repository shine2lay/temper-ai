"""Tests for P3 T5-N2 selection_snapshot.py over DbAdmissionTransport."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, func, select

from p3_host_contracts.publication import RowKey
from temper_ai.config.admission_contract import (
    RESERVED_KEY,
    AdmissionRecord,
    DescriptorAuthority,
    DispatchIdentity,
    canonical_bytes,
)
from temper_ai.database import (
    get_database,
    get_session,
    init_database,
    reset_database,
)
from temper_ai.p3_authority.contract import (
    AcceptedData,
    ActualCreation,
    AdmissionState,
    CalibrationSelection,
    JobKey,
    PreDispatchJob,
    ProjectSelection,
    Refusal,
    RefusalCode,
    SelectedJob,
    Selection,
)
from temper_ai.p3_authority.host_types import (
    HostCalibrationSelection,
    HostProjectSelection,
    RawRef,
    SelectedHostJob,
)
from temper_ai.p3_authority.registry import (
    AuthorityRegistryService,
    InMemoryIssuerVerifier,
    InMemoryPeerVerifier,
    PriorRequestHistory,
    default_effect_for_job,
)
from temper_ai.p3_authority.selection_snapshot import (
    DEFAULT_REQUEST_HISTORY_PROVIDER,
    DEFAULT_SELECTION_SNAPSHOT_PROVIDER,
    SUPPORTED_SELECTION_ROUTE,
    WRITES_ADMITTED,
    DbRequestHistoryProvider,
    DbSelectionSnapshotProvider,
    HostSelectionHandle,
    RequestHistoryEntry,
    RunSelectionBinding,
    project_selected_host_job,
    verify_boundary_transition,
)
from temper_ai.runner.models import WorkflowRun
from tests.test_p3_authority._composition_fixtures import (
    ALL_OPERATIONS,
    AUTHORITY_REF_1,
    COMPAT_PROFILE_1,
    CONDITION_1,
    PROCESS_RUN,
    PROCESS_SUBMIT,
    REF_BINDING,
    REF_CLOSURE,
    REF_KIT,
    REF_MANIFEST,
    SELECTOR_ISSUER_REF,
    TRUSTED_NOW,
    FakeNativeRootObject,
    FakePeer,
    FakeWitness,
    make_verified_authority,
)
from tests.test_runner.test_candidate_admission_integration import (
    QUEUED_NONCE,
    WORKER,
    Case,
    EntryBindings,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


@pytest.fixture
def p3_db(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[None]:
    from tests.conftest import TEST_DATABASE_URL
    from tests.pgtier import database_tier_url, truncate_everything

    pg_url = database_tier_url(None)
    if pg_url:
        reset_database()
        init_database(pg_url)
        truncate_everything()
        request.node.stash[TEST_DATABASE_URL] = pg_url
    else:
        sqlite_url = f"sqlite:///{tmp_path / 'p3_n2.db'}"
        reset_database()
        init_database(sqlite_url)
        request.node.stash[TEST_DATABASE_URL] = sqlite_url
    yield
    reset_database()


def _install_queued_case(
    tmp_path: Path,
    *,
    prefix: str = "",
    execution_uuid: str = "00000000-0000-4000-8000-000000000284",
) -> tuple[Case, EntryBindings, AdmissionRecord, str, str]:
    case = Case(tmp_path, prefix=prefix, execution=execution_uuid)
    entry = EntryBindings(case)
    case.store_rows()
    queued_val = case.literal_queued_record()
    queued_rec = entry.codec.record(
        canonical_bytes(queued_val),
        entry.authority,
    )
    with get_session() as session:
        with session.begin():
            entry.store.install(admission=queued_rec, transaction=session)
    desc_sha = entry.authority.expected_descriptor_sha256
    source_sha = entry.authority.expected_source_sha256
    return case, entry, queued_rec, desc_sha, source_sha


def _claim_running_case(
    entry: EntryBindings,
    queued_rec: AdmissionRecord,
    *,
    dispatch_nonce: str = "00000000-0000-4000-8000-000000000285",
    running_attempt: int = 1,
) -> tuple[AdmissionRecord, DispatchIdentity]:
    running_val = copy.deepcopy(queued_rec.value())
    running_val["dispatch"] = {
        "phase": "running",
        "dispatch_nonce": dispatch_nonce,
        "running_attempt": running_attempt,
        "previous_nonce": QUEUED_NONCE,
        "worker_label": WORKER,
    }
    running_rec = entry.codec.record(
        canonical_bytes(running_val),
        entry.authority,
    )
    with get_session() as session:
        with session.begin():
            entry.store.bind_dispatch(
                queued_rec,
                running_rec,
                transaction=session,
            )
    dispatch_id = DispatchIdentity(
        execution_uuid=entry.case.execution,
        dispatch_nonce=dispatch_nonce,
        running_attempt=running_attempt,
    )
    return running_rec, dispatch_id


def _project_selection(
    *,
    project_id: str = "proj-alpha",
    run_id: str = "run-alpha-1",
    kit_id: str = "kit-alpha",
) -> ProjectSelection:
    return ProjectSelection(
        project_id=project_id,
        run_id=run_id,
        kit_id=kit_id,
        kit_sha256=_sha(f"kit:{kit_id}"),
        build_sums_sha256=_sha(f"sums:{project_id}"),
        publication_ref=REF_BINDING,
        publication_revision="pub-rev-001",
        build_ref=REF_KIT,
    )


def _calibration_selection(
    *,
    entry_id: str = "cal-entry-1",
    calibration_run: str = "cal-run-1",
) -> CalibrationSelection:
    return CalibrationSelection(
        manifest_ref=REF_MANIFEST,
        entry_id=entry_id,
        calibration_run=calibration_run,
        round="round-1",
        copy_identity="copy-1",
        expected_draft_kit=REF_KIT,
        build_sums_sha256=_sha(f"cal-sums:{entry_id}"),
        publication_ref=REF_BINDING,
        publication_revision="pub-cal-001",
        build_ref=REF_KIT,
        selected_runtime_profile="profile-cal-1",
    )


def _make_binding(
    execution_uuid: str,
    authority: DescriptorAuthority,
    *,
    selection_revision: str = "sel-rev-001",
    job_revision: str = "job-rev-001",
    selection: Selection | None = None,
    expected_dispatch: DispatchIdentity | None = None,
    route: str = SUPPORTED_SELECTION_ROUTE,
) -> RunSelectionBinding:
    sel = selection or _project_selection(run_id=execution_uuid)
    return RunSelectionBinding(
        execution_uuid=execution_uuid,
        authority=authority,
        job_revision=job_revision,
        selection_revision=selection_revision,
        selector_issuer=SELECTOR_ISSUER_REF,
        selection=sel,
        reviewed_closure_ref=REF_CLOSURE,
        compatibility_profile=COMPAT_PROFILE_1,
        authorized_operations=ALL_OPERATIONS,
        conditions=(CONDITION_1,),
        authority_refs=(AUTHORITY_REF_1,),
        expected_dispatch=expected_dispatch,
        route=route,
        creator_launch_id=f"launch:{execution_uuid}",
    )


def _register_job_authorities(
    verifier: InMemoryIssuerVerifier,
    snapshot: Any,
    job: SelectedJob,
) -> None:
    subj = snapshot.subject_for(job)
    for ref in (job.selector_issuer, *job.authority_refs):
        verifier.register_authority(
            ref,
            make_verified_authority(
                authority=ref,
                subject=subj,
                actors=frozenset({PROCESS_SUBMIT, PROCESS_RUN}),
            ),
            job=job,
        )


def _row_count() -> int:
    with get_session() as session:
        return int(
            session.scalar(select(func.count()).select_from(WorkflowRun)) or 0
        )


def test_combined_happy_path_submit_run_check_bind_and_host_join(
    p3_db: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Combined happy path: inert defaults, AuthorityRegistryService with
    DbSelectionSnapshotProvider + DbRequestHistoryProvider through for_submit,
    for_run, check_current, bind_created -> AcceptedData[WindowBinding],
    matching SelectedJob and SelectedHostJob, ignoring spoofed flags/env,
    and issuing zero DB writes.
    """
    assert WRITES_ADMITTED is False
    assert DEFAULT_SELECTION_SNAPSHOT_PROVIDER is None
    assert DEFAULT_REQUEST_HISTORY_PROVIDER is None

    monkeypatch.setenv("P3_PROJECT_ID", "env-spoofed-project")
    monkeypatch.setenv("P3_KIT_ID", "env-spoofed-kit")
    monkeypatch.setenv("P3_ROUTE", "env-spoofed-route")

    exec_uuid = "11111111-2222-4333-8444-555555555555"
    case, entry, queued_rec, desc_sha, source_sha = _install_queued_case(
        tmp_path,
        prefix="_hp",
        execution_uuid=exec_uuid,
    )
    workflow_name = case.workflow
    transport = entry.store
    active_bindings: list[RunSelectionBinding] = [
        _make_binding(
            exec_uuid,
            entry.authority,
        )
    ]
    snapshot_provider = DbSelectionSnapshotProvider(
        transport,
        bindings=lambda: active_bindings,
        verified_at=TRUSTED_NOW,
    )
    history_provider = DbRequestHistoryProvider(
        transport,
        bindings=lambda: active_bindings,
    )
    peer = FakePeer("peer-submit", process=PROCESS_SUBMIT)
    peer_run = FakePeer("peer-run", process=PROCESS_RUN)
    peer_verifier = InMemoryPeerVerifier(allowed_peers=(peer, peer_run))
    issuer_verifier = InMemoryIssuerVerifier()
    service = AuthorityRegistryService(
        snapshot_provider=snapshot_provider,
        issuer_verifier=issuer_verifier,
        peer_verifier=peer_verifier,
        history_provider=history_provider,
    )

    snap_pre = snapshot_provider.read_snapshot()
    assert snap_pre is not None and len(snap_pre.jobs) == 1
    _register_job_authorities(issuer_verifier, snap_pre, snap_pre.jobs[0])

    # 1. for_submit (pre-dispatch queued run)
    submit_res = service.for_submit(peer, workflow_name)
    assert isinstance(submit_res, AcceptedData)
    submitted_job = submit_res.data
    assert isinstance(submitted_job.pre_dispatch_or_running_job, PreDispatchJob)
    assert submitted_job.pre_dispatch_or_running_job.execution_uuid == exec_uuid
    assert isinstance(submitted_job.selection, ProjectSelection)
    assert submitted_job.selection.project_id == "proj-alpha"
    assert submitted_job.selection.kit_id == "kit-alpha"
    assert submitted_job.route == "external-db-fresh"

    # Transition run in DB to claimed/running with DispatchIdentity
    dispatch_nonce = "00000000-0000-4000-8000-000000000285"
    _, dispatch_id = _claim_running_case(
        entry,
        queued_rec,
        dispatch_nonce=dispatch_nonce,
        running_attempt=1,
    )
    active_bindings[0] = _make_binding(
        exec_uuid,
        entry.authority,
        expected_dispatch=dispatch_id,
    )

    eng = get_database().engine
    write_statements: list[str] = []

    def _on_execute(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        verb = statement.lstrip().split(" ", 1)[0].upper()
        if verb in {"INSERT", "UPDATE", "DELETE", "REPLACE", "ALTER", "DROP", "CREATE"}:
            write_statements.append(statement)

    before_rows = _row_count()
    event.listen(eng, "before_cursor_execute", _on_execute)
    try:
        snap_run = snapshot_provider.read_snapshot()
        assert snap_run is not None and len(snap_run.jobs) == 1
        _register_job_authorities(issuer_verifier, snap_run, snap_run.jobs[0])

        # 2. for_run
        run_res = service.for_run(peer_run, exec_uuid, dispatch_id)
        assert isinstance(run_res, AcceptedData)
        running_job = run_res.data
        assert isinstance(running_job.pre_dispatch_or_running_job, JobKey)
        assert running_job.pre_dispatch_or_running_job.dispatch == dispatch_id
        assert running_job.selection_revision == submitted_job.selection_revision

        # Boundary continuity from for_submit -> for_run
        trans_res = verify_boundary_transition(submitted_job, running_job)
        assert isinstance(trans_res, AcceptedData)

        # 3. check_current
        binding_raw_ref = RawRef(
            root_locator="root://binding",
            relative_path=REF_BINDING.path,
            byte_length=REF_BINDING.length,
            sha256=REF_BINDING.digest,
        )
        req_id = RowKey(
            selection=HostSelectionHandle(
                selection_reference=f"sel:{exec_uuid}",
                selection_revision=running_job.selection_revision,
            ),
            window_id="win-001",
            binding_ref=binding_raw_ref,
            writer=SELECTOR_ISSUER_REF.issuer_id,
            row="row-default",
            operation="create",
            request_id="req-001",
            sequence=1,
            request_raw_ref=binding_raw_ref,
        )
        effect = default_effect_for_job(running_job, "A_PRE_CREATE")
        current_res = service.check_current(
            peer_run,
            running_job.selection_revision,
            "A_PRE_CREATE",
            effect,
            request_identity=req_id,
        )
        assert isinstance(current_res, AcceptedData)
        current_binding = current_res.data

        # 4. bind_created -> AcceptedData[WindowBinding]
        actual_creation = ActualCreation(
            window_id="win-001",
            object_identity=FakeNativeRootObject("obj-win-001"),
            creator=PROCESS_RUN,
            birth=FakeWitness("wit-win-001"),
        )
        bind_res = service.bind_created(
            peer_run,
            current_binding,
            actual_creation,
        )
        assert isinstance(bind_res, AcceptedData)
        assert bind_res.data.actual_creation.window_id == "win-001"
        assert bind_res.data.current.selected_job == running_job

        # 5. Join & verify SelectedHostJob against SelectedJob
        join_res = snapshot_provider.join_host_job(
            running_job,
            prior_job=submitted_job,
        )
        assert isinstance(join_res, AcceptedData)
        host_job: SelectedHostJob = join_res.data
        assert host_job.job_id == exec_uuid
        assert host_job.attempt_id == f"{dispatch_nonce}:1"
        assert host_job.publication_id == "pub-rev-001"
        assert isinstance(host_job.route, HostProjectSelection)
        assert host_job.route.project_id == "proj-alpha"
        assert host_job.route.kit_ref.sha256 == running_job.selection.kit_sha256
        assert host_job.caller.entrypoint == "external-db-fresh"
        assert host_job.caller.runtime_route == "temper-dev"
        assert host_job.caller.writer == SELECTOR_ISSUER_REF.issuer_id
    finally:
        event.remove(eng, "before_cursor_execute", _on_execute)

    assert write_statements == []
    assert _row_count() == before_rows


def test_refusal_selection_missing_when_db_row_absent(
    p3_db: None,
    tmp_path: Path,
) -> None:
    """Missing snapshot / missing DB run row -> SELECTION_MISSING."""
    missing_uuid = "22222222-3333-4444-8555-666666666666"
    case, entry, _, _, _ = _install_queued_case(
        tmp_path,
        prefix="_missing",
        execution_uuid="22222222-3333-4444-8555-666666666660",
    )
    binding = _make_binding(missing_uuid, entry.authority)
    snapshot_provider = DbSelectionSnapshotProvider(
        entry.store,
        bindings=(binding,),
        verified_at=TRUSTED_NOW,
    )
    peer = FakePeer("peer-submit", process=PROCESS_SUBMIT)
    service = AuthorityRegistryService(
        snapshot_provider=snapshot_provider,
        issuer_verifier=InMemoryIssuerVerifier(),
        peer_verifier=InMemoryPeerVerifier(allowed_peers=(peer,)),
        history_provider=DbRequestHistoryProvider(entry.store, bindings=(binding,)),
    )

    submit_res = service.for_submit(peer, case.workflow)
    assert isinstance(submit_res, Refusal)
    assert submit_res.code == RefusalCode.SELECTION_MISSING

    dispatch_id = DispatchIdentity(
        execution_uuid=missing_uuid,
        dispatch_nonce="00000000-0000-4000-8000-000000000286",
        running_attempt=1,
    )
    run_res = service.for_run(peer, missing_uuid, dispatch_id)
    assert isinstance(run_res, Refusal)
    assert run_res.code == RefusalCode.SELECTION_MISSING


def test_refusal_selection_ambiguous_on_competing_selections(
    p3_db: None,
    tmp_path: Path,
) -> None:
    """Competing active selections for the same workflow -> SELECTION_AMBIGUOUS."""
    uuid_a = "33333333-4444-4555-8666-777777777771"
    case_a, entry_a, _, _, _ = _install_queued_case(
        tmp_path,
        prefix="_amb_a",
        execution_uuid=uuid_a,
    )
    b1 = _make_binding(uuid_a, entry_a.authority, selection_revision="sel-amb-1")
    b2 = _make_binding(uuid_a, entry_a.authority, selection_revision="sel-amb-2")
    snapshot_provider = DbSelectionSnapshotProvider(
        entry_a.store,
        bindings=(b1, b2),
        verified_at=TRUSTED_NOW,
    )
    peer = FakePeer("peer-submit", process=PROCESS_SUBMIT)
    issuer_verifier = InMemoryIssuerVerifier()
    snap = snapshot_provider.read_snapshot()
    assert snap is not None and len(snap.jobs) == 2
    for job in snap.jobs:
        _register_job_authorities(issuer_verifier, snap, job)

    service = AuthorityRegistryService(
        snapshot_provider=snapshot_provider,
        issuer_verifier=issuer_verifier,
        peer_verifier=InMemoryPeerVerifier(allowed_peers=(peer,)),
        history_provider=DbRequestHistoryProvider(entry_a.store, bindings=(b1, b2)),
    )
    res = service.for_submit(peer, case_a.workflow)
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.SELECTION_AMBIGUOUS


def test_refusal_selection_foreign_on_foreign_run_project_or_kit(
    p3_db: None,
    tmp_path: Path,
) -> None:
    """Foreign run/project/kit -> SELECTION_FOREIGN across service and host join."""
    exec_uuid = "44444444-5555-4666-8777-888888888888"
    case, entry, queued_rec, _, _ = _install_queued_case(
        tmp_path,
        prefix="_foreign",
        execution_uuid=exec_uuid,
    )
    _, dispatch_id = _claim_running_case(
        entry,
        queued_rec,
        dispatch_nonce="00000000-0000-4000-8000-000000000287",
        running_attempt=1,
    )
    binding = _make_binding(
        exec_uuid,
        entry.authority,
        expected_dispatch=dispatch_id,
    )
    snapshot_provider = DbSelectionSnapshotProvider(
        entry.store,
        bindings=(binding,),
        verified_at=TRUSTED_NOW,
    )
    peer_run = FakePeer("peer-run", process=PROCESS_RUN)
    issuer_verifier = InMemoryIssuerVerifier()
    snap = snapshot_provider.read_snapshot()
    assert snap is not None and len(snap.jobs) == 1
    running_job = snap.jobs[0]
    _register_job_authorities(issuer_verifier, snap, running_job)

    service = AuthorityRegistryService(
        snapshot_provider=snapshot_provider,
        issuer_verifier=issuer_verifier,
        peer_verifier=InMemoryPeerVerifier(allowed_peers=(peer_run,)),
        history_provider=DbRequestHistoryProvider(entry.store, bindings=(binding,)),
    )
    foreign_req = RowKey(
        selection=HostSelectionHandle(
            selection_reference="sel:foreign",
            selection_revision="sel-rev-foreign",
        ),
        window_id="win-foreign",
        binding_ref=RawRef("root://b", "b.json", 64, REF_BINDING.digest),
        writer=SELECTOR_ISSUER_REF.issuer_id,
        row="row-default",
        operation="create",
        request_id="req-foreign",
        sequence=1,
        request_raw_ref=RawRef("root://b", "b.json", 64, REF_BINDING.digest),
    )
    effect = default_effect_for_job(running_job, "A_PRE_CREATE")
    check_res = service.check_current(
        peer_run,
        running_job.selection_revision,
        "A_PRE_CREATE",
        effect,
        request_identity=foreign_req,
    )
    assert isinstance(check_res, Refusal)
    assert check_res.code == RefusalCode.SELECTION_FOREIGN

    # Foreign kit_sha256 in candidate SelectedHostJob -> SELECTION_FOREIGN
    good_host = project_selected_host_job(running_job, binding=binding)
    assert isinstance(good_host.route, HostProjectSelection)
    foreign_kit_route = HostProjectSelection(
        project_id=good_host.route.project_id,
        kit_ref=RawRef(
            root_locator=good_host.route.kit_ref.root_locator,
            relative_path=good_host.route.kit_ref.relative_path,
            byte_length=64,
            sha256=_sha("foreign-kit-digest"),
        ),
        expected_binding_ref=good_host.route.expected_binding_ref,
    )
    foreign_host = SelectedHostJob(
        selection=good_host.selection,
        job_id=good_host.job_id,
        attempt_id=good_host.attempt_id,
        publication_id=good_host.publication_id,
        build_ref=good_host.build_ref,
        route=foreign_kit_route,
        creator_launch_id=good_host.creator_launch_id,
        caller=good_host.caller,
    )
    join_foreign_kit = snapshot_provider.join_host_job(
        running_job,
        candidate_host_job=foreign_host,
    )
    assert isinstance(join_foreign_kit, Refusal)
    assert join_foreign_kit.code == RefusalCode.SELECTION_FOREIGN


def test_refusal_selection_changed_and_guard_bite_revision_drift(
    p3_db: None,
    tmp_path: Path,
) -> None:
    """Selection drift between for_submit/for_run/check_current -> SELECTION_CHANGED."""
    exec_uuid = "55555555-6666-4777-8888-999999999999"
    case, entry, queued_rec, _, _ = _install_queued_case(
        tmp_path,
        prefix="_chg",
        execution_uuid=exec_uuid,
    )
    active_bindings: list[RunSelectionBinding] = [
        _make_binding(exec_uuid, entry.authority, selection_revision="sel-rev-v1")
    ]
    snapshot_provider = DbSelectionSnapshotProvider(
        entry.store,
        bindings=lambda: active_bindings,
        verified_at=TRUSTED_NOW,
    )
    peer = FakePeer("peer-submit", process=PROCESS_SUBMIT)
    peer_run = FakePeer("peer-run", process=PROCESS_RUN)
    issuer_verifier = InMemoryIssuerVerifier()
    service = AuthorityRegistryService(
        snapshot_provider=snapshot_provider,
        issuer_verifier=issuer_verifier,
        peer_verifier=InMemoryPeerVerifier(allowed_peers=(peer, peer_run)),
        history_provider=DbRequestHistoryProvider(
            entry.store, bindings=lambda: active_bindings
        ),
    )

    snap_pre = snapshot_provider.read_snapshot()
    assert snap_pre is not None and len(snap_pre.jobs) == 1
    _register_job_authorities(issuer_verifier, snap_pre, snap_pre.jobs[0])
    submit_res = service.for_submit(peer, case.workflow)
    assert isinstance(submit_res, AcceptedData)
    submitted_job = submit_res.data

    _, dispatch_id = _claim_running_case(
        entry,
        queued_rec,
        dispatch_nonce="00000000-0000-4000-8000-000000000288",
        running_attempt=1,
    )
    active_bindings[0] = _make_binding(
        exec_uuid,
        entry.authority,
        selection_revision="sel-rev-v1",
        expected_dispatch=dispatch_id,
    )
    snap_run = snapshot_provider.read_snapshot()
    assert snap_run is not None and len(snap_run.jobs) == 1
    _register_job_authorities(issuer_verifier, snap_run, snap_run.jobs[0])
    run_res = service.for_run(peer_run, exec_uuid, dispatch_id)
    assert isinstance(run_res, AcceptedData)
    running_job = run_res.data

    # Now drift the descriptor in the DB row while keeping binding pinned to old authority
    with get_session() as session:
        row = session.scalars(
            select(WorkflowRun).where(WorkflowRun.execution_id == exec_uuid)
        ).one()
        session.delete(row)
        session.flush()
    _, entry_v2, queued_v2, _, _ = _install_queued_case(
        tmp_path,
        prefix="_chg_v2",
        execution_uuid=exec_uuid,
    )
    _claim_running_case(
        entry_v2,
        queued_v2,
        dispatch_nonce="00000000-0000-4000-8000-000000000288",
        running_attempt=1,
    )

    # Transport uses v2 codec/authority/source to decode the row, while binding.approved_descriptor_digest
    # stays pinned to v1 -> _selection_revision_matches detects drift!
    entry.store.authority = entry_v2.store.authority
    entry.store.codec = entry_v2.store.codec
    entry.store.current_source = entry_v2.store.current_source
    entry.store.installation = entry_v2.store.installation
    entry.store.preparation = entry_v2.store.preparation
    effect = default_effect_for_job(running_job, "A_PRE_CREATE")
    check_res = service.check_current(
        peer_run,
        running_job.selection_revision,
        "A_PRE_CREATE",
        effect,
    )
    assert isinstance(check_res, Refusal)
    assert check_res.code == RefusalCode.SELECTION_CHANGED

    # Boundary transition check across drifted SelectedJob revisions -> SELECTION_CHANGED
    drifted_snap = snapshot_provider.read_snapshot()
    assert drifted_snap is not None and len(drifted_snap.jobs) == 1
    drifted_job = drifted_snap.jobs[0]
    trans_res = verify_boundary_transition(submitted_job, drifted_job)
    assert isinstance(trans_res, Refusal)
    assert trans_res.code == RefusalCode.SELECTION_CHANGED

    join_res = snapshot_provider.join_host_job(drifted_job, prior_job=submitted_job)
    assert isinstance(join_res, Refusal)
    assert join_res.code == RefusalCode.SELECTION_CHANGED


def test_refusal_route_unsupported_and_guard_bite_unverified_route(
    p3_db: None,
    tmp_path: Path,
) -> None:
    """Unsupported / unverified route -> ROUTE_UNSUPPORTED."""
    exec_uuid = "66666666-7777-4888-8999-aaaaaaaaaaaa"
    case, entry, _, _, _ = _install_queued_case(
        tmp_path,
        prefix="_route",
        execution_uuid=exec_uuid,
    )
    bad_binding = _make_binding(
        exec_uuid,
        entry.authority,
        route="legacy-env-flag-route",
    )
    snapshot_provider = DbSelectionSnapshotProvider(
        entry.store,
        bindings=(bad_binding,),
        verified_at=TRUSTED_NOW,
    )
    peer = FakePeer("peer-submit", process=PROCESS_SUBMIT)
    issuer_verifier = InMemoryIssuerVerifier()
    snap = snapshot_provider.read_snapshot()
    assert snap is not None and len(snap.jobs) == 1
    _register_job_authorities(issuer_verifier, snap, snap.jobs[0])

    service = AuthorityRegistryService(
        snapshot_provider=snapshot_provider,
        issuer_verifier=issuer_verifier,
        peer_verifier=InMemoryPeerVerifier(allowed_peers=(peer,)),
        history_provider=DbRequestHistoryProvider(
            entry.store, bindings=(bad_binding,)
        ),
    )
    submit_res = service.for_submit(peer, case.workflow)
    assert isinstance(submit_res, Refusal)
    assert submit_res.code == RefusalCode.ROUTE_UNSUPPORTED

    join_res = snapshot_provider.join_host_job(snap.jobs[0])
    assert isinstance(join_res, Refusal)
    assert join_res.code == RefusalCode.ROUTE_UNSUPPORTED


def test_refusal_dispatch_changed_and_guard_bite_dispatch_equality(
    p3_db: None,
    tmp_path: Path,
) -> None:
    """DispatchIdentity changed in DB after claim -> DISPATCH_CHANGED."""
    exec_uuid = "77777777-8888-4999-8aaa-bbbbbbbbbbbb"
    _, entry, queued_rec, _, _ = _install_queued_case(
        tmp_path,
        prefix="_disp",
        execution_uuid=exec_uuid,
    )
    _, claim_1 = _claim_running_case(
        entry,
        queued_rec,
        dispatch_nonce="00000000-0000-4000-8000-000000000291",
        running_attempt=1,
    )
    binding = _make_binding(
        exec_uuid,
        entry.authority,
        expected_dispatch=claim_1,
    )
    snapshot_provider = DbSelectionSnapshotProvider(
        entry.store,
        bindings=(binding,),
        verified_at=TRUSTED_NOW,
    )
    peer_run = FakePeer("peer-run", process=PROCESS_RUN)
    issuer_verifier = InMemoryIssuerVerifier()
    snap_1 = snapshot_provider.read_snapshot()
    assert snap_1 is not None and len(snap_1.jobs) == 1
    job_claim_1 = snap_1.jobs[0]
    _register_job_authorities(issuer_verifier, snap_1, job_claim_1)

    service = AuthorityRegistryService(
        snapshot_provider=snapshot_provider,
        issuer_verifier=issuer_verifier,
        peer_verifier=InMemoryPeerVerifier(allowed_peers=(peer_run,)),
        history_provider=DbRequestHistoryProvider(entry.store, bindings=(binding,)),
    )

    # DB row advances to a new claim (new nonce) while binding/caller hold claim_1
    with get_session() as session:
        row = session.scalars(
            select(WorkflowRun).where(WorkflowRun.execution_id == exec_uuid)
        ).one()
        row.status = "queued"
        row.attempts = 0
        row.spawner_metadata = {RESERVED_KEY: queued_rec.value()}
        session.flush()
    _claim_running_case(
        entry,
        queued_rec,
        dispatch_nonce="00000000-0000-4000-8000-000000000292",
        running_attempt=1,
    )

    run_res = service.for_run(peer_run, exec_uuid, claim_1)
    assert isinstance(run_res, Refusal)
    assert run_res.code == RefusalCode.DISPATCH_CHANGED

    join_res = snapshot_provider.join_host_job(job_claim_1)
    assert isinstance(join_res, Refusal)
    assert join_res.code == RefusalCode.DISPATCH_CHANGED


def test_calibration_selection_and_request_history_envelope(
    p3_db: None,
    tmp_path: Path,
) -> None:
    """CalibrationSelection projects HostCalibrationSelection and RequestHistoryProvider
    returns recorded history only when the DB admission envelope is valid.
    """
    exec_uuid = "88888888-9999-4aaa-8bbb-cccccccccccc"
    _, entry, queued_rec, _, _ = _install_queued_case(
        tmp_path,
        prefix="_cal",
        execution_uuid=exec_uuid,
    )
    _, dispatch_id = _claim_running_case(
        entry,
        queued_rec,
        dispatch_nonce="00000000-0000-4000-8000-000000000293",
        running_attempt=1,
    )
    cal_binding = _make_binding(
        exec_uuid,
        entry.authority,
        selection=_calibration_selection(),
        expected_dispatch=dispatch_id,
    )
    snapshot_provider = DbSelectionSnapshotProvider(
        entry.store,
        bindings=(cal_binding,),
        verified_at=TRUSTED_NOW,
    )
    snap = snapshot_provider.read_snapshot()
    assert snap is not None and len(snap.jobs) == 1
    cal_job = snap.jobs[0]
    join_res = snapshot_provider.join_host_job(cal_job)
    assert isinstance(join_res, AcceptedData)
    assert isinstance(join_res.data.route, HostCalibrationSelection)
    assert join_res.data.route.entry_id == "cal-entry-1"
    assert join_res.data.route.calibration_run == "cal-run-1"
    assert join_res.data.route.copy_id == "copy-1"

    binding_raw_ref = RawRef("root://b", "b.json", 64, REF_BINDING.digest)
    req_id = RowKey(
        selection=HostSelectionHandle(
            selection_reference=f"sel:{exec_uuid}",
            selection_revision=cal_job.selection_revision,
        ),
        window_id="win-cal",
        binding_ref=binding_raw_ref,
        writer=SELECTOR_ISSUER_REF.issuer_id,
        row="row-default",
        operation="create",
        request_id="req-cal",
        sequence=1,
        request_raw_ref=binding_raw_ref,
    )
    expected_hist = PriorRequestHistory(admission_state=AdmissionState.ALREADY_ADMITTED)
    hist_provider = DbRequestHistoryProvider(
        entry.store,
        entries=(
            RequestHistoryEntry(
                request_identity=req_id,
                execution_uuid=exec_uuid,
                history=expected_hist,
            ),
        ),
        bindings=(cal_binding,),
    )
    assert hist_provider.lookup_history(req_id) == expected_hist


