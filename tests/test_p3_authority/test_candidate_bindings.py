"""Unit and real V1 integration tests for ``temper_ai.p3_authority.candidate_bindings`` (#262).

Proves that ``P3CandidateBindings`` and ``CandidateCaptureAdapter``:
1. Implement the exact ``temper_ai.runner.admission.CandidateBindings`` protocol
   and delegate capture, install, rollback, snapshot restore, context binding,
   and ``external-db-fresh`` persistence to the real V1 primitives.
2. Enforce independent P3 authority selection/verification on ``authority_for_submit``,
   ``authority_for_run``, and ``bind_created_execution`` without reading authority
   claims from candidate workflow dictionaries or widening the frozen wire schema.
3. Refuse unsupported sealed, Pi-containing, continuation, and direct-bypass
   variants as well as missing providers, unverified peers, changed dispatches,
   and mismatched descriptor/source digests.
4. Keep ``temper_ai.runner.admission.DEFAULT_CANDIDATE_BINDINGS`` unchanged and inert.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from temper_ai.api.caller import Caller
from temper_ai.config.admission_contract import (
    AdmissionRefused,
    DescriptorAuthority,
    DispatchIdentity,
)
from temper_ai.config.admission_contract import (
    RefusalCode as CandidateRefusalCode,
)
from temper_ai.database import get_session
from temper_ai.p3_authority.boundary_types import ActualCreation, CurrentBinding
from temper_ai.p3_authority.candidate_bindings import (
    P3CandidateAuthorityRefusal,
    P3CandidateBindings,
    StaticCallerPeerProvider,
)
from temper_ai.p3_authority.contract import (
    Phase,
    RefusalCode,
)
from temper_ai.p3_authority.registry import (
    SelectionSnapshot,
    default_effect_for_job,
)
from temper_ai.runner.admission import (
    DbAdmissionTransport,
    is_designated,
)
from temper_ai.shared.types import ExecutionContext
from tests.test_p3_authority._composition_fixtures import (
    AUTHORITY_REF_1,
    DISPATCH_1,
    DISPATCH_2,
    PROCESS_RUN,
    PROCESS_SUBMIT,
    TRUSTED_NOW,
    FakeNativeRootObject,
    FakeWitness,
    make_populated_test_rig,
    make_pre_dispatch_job,
    make_running_job,
    make_verified_authority,
)
from tests.test_runner.test_candidate_admission_integration import (
    AUTHOR,
    Case,
    EntryBindings,
)


def test_default_production_candidate_bindings_unchanged_and_inert() -> None:
    assert is_designated("designated_v1", None) is False

    empty = P3CandidateBindings()
    assert empty.designated("designated_v1") is False
    assert empty.designated("") is False
    assert empty.designated(None) is False  # type: ignore[arg-type]

    caller = Caller(name="p3-authorized-caller")
    with pytest.raises(AdmissionRefused) as exc_submit:
        empty.authority_for_submit(caller, "designated_v1")
    assert exc_submit.value.code is CandidateRefusalCode.AUTHORITY

    with pytest.raises(AdmissionRefused) as exc_run:
        empty.authority_for_run(DISPATCH_1.execution_uuid)
    assert exc_run.value.code is CandidateRefusalCode.AUTHORITY


def test_combined_v1_capture_install_snapshot_and_context_happy_path(
    tmp_path: Path,
) -> None:
    case = Case(tmp_path)
    entry = EntryBindings(case)
    rig = make_populated_test_rig()

    desc_sha = entry.authority.expected_descriptor_sha256
    src_sha = entry.authority.expected_source_sha256
    dispatch = DispatchIdentity(
        execution_uuid=case.execution,
        dispatch_nonce="00000000-0000-4000-8000-000000000003",
        running_attempt=1,
    )
    pre_job = make_pre_dispatch_job(
        designated_workflow=case.workflow,
        execution_uuid=case.execution,
        selection_revision="sel-v208-pre",
        approved_descriptor_digest=desc_sha,
        expected_source_digest=src_sha,
    )
    run_job = make_running_job(
        dispatch=dispatch,
        selection_revision="sel-v208-run",
        approved_descriptor_digest=desc_sha,
        expected_source_digest=src_sha,
    )
    snapshot = SelectionSnapshot(
        snapshot_revision="snap-v208-1",
        jobs=(pre_job, run_job),
        verified_at=TRUSTED_NOW,
    )
    for job in (pre_job, run_job):
        subj = snapshot.subject_for(job)
        for ref in (job.selector_issuer, *job.authority_refs):
            rig.issuer_verifier.register_authority(
                ref,
                make_verified_authority(
                    authority=ref,
                    subject=subj,
                    actors=frozenset({PROCESS_SUBMIT, PROCESS_RUN}),
                ),
                job=job,
            )
    rig.publisher.publish_snapshot(snapshot)

    caller = Caller(name=AUTHOR)
    caller_peers = StaticCallerPeerProvider(
        submit_peers={(AUTHOR, case.workflow): rig.peer_submit},
        run_peers={case.execution: rig.peer_run},
    )
    p3_bindings = P3CandidateBindings(
        registry=rig.composition.registry,
        caller_peer_provider=caller_peers,
        delegate_bindings=entry,
        designated_workflows=frozenset({case.workflow}),
        default_dispatch_identity=dispatch,
    )
    p3_bindings.register_run_dispatch(case.execution, dispatch)

    assert p3_bindings.designated(case.workflow) is True
    assert p3_bindings.designated("other_workflow") is False

    submit_auth = p3_bindings.authority_for_submit(caller, case.workflow)
    assert submit_auth == entry.authority
    assert case.workflow in p3_bindings.recorded_submit_bindings
    assert (
        p3_bindings.recorded_submit_bindings[case.workflow].selected_job
        == pre_job
    )

    transport = p3_bindings.transport(submit_auth)
    assert isinstance(transport, DbAdmissionTransport)

    case.store_rows()
    descriptor = entry.codec.descriptor(
        bytes( entry.codec.descriptor(
            entry.case.literal_queued_record()["immutable"]["descriptor_json"].encode(),
            submit_auth,
        ).wire ),
        submit_auth,
    )
    with get_session() as session:
        with session.begin():
            record = p3_bindings.prepare(
                descriptor,
                request={"workflow_name": case.workflow},
                transaction=session,
            )
            assert record.value()["immutable"]["descriptor_sha256"] == desc_sha
            transport.install(admission=record, transaction=session)

    current_binding = CurrentBinding(
        selected_job=pre_job,
        authority_revisions=pre_job.authority_refs,
        boundary="A_PRE_ARM",
        intended_effect=default_effect_for_job(pre_job, "A_PRE_ARM"),
    )
    actual_creation = ActualCreation(
        window_id="win-v208-1",
        creator=PROCESS_SUBMIT,
        object_identity=FakeNativeRootObject("obj-v208-1"),
        birth=FakeWitness("wit-v208-1"),
    )
    window = p3_bindings.bind_created_execution(
        caller=caller,
        workflow_name=case.workflow,
        current_binding=current_binding,
        actual_creation=actual_creation,
    )
    assert window.actual_creation == actual_creation
    assert p3_bindings.recorded_windows[case.execution] == window

    run_auth = p3_bindings.authority_for_run(case.execution)
    assert run_auth == entry.authority
    assert case.execution in p3_bindings.recorded_run_bindings
    assert p3_bindings.recorded_run_bindings[case.execution].selected_job == run_job

    from temper_ai.config.admission_contract import AdmissionRecord, canonical_bytes

    proposal = record.value()
    proposal["dispatch"] = {
        "phase": "running",
        "running_attempt": 1,
        "previous_nonce": proposal["dispatch"]["dispatch_nonce"],
        "dispatch_nonce": dispatch.dispatch_nonce,
        "worker_label": transport.worker_identity(),
    }
    running_proposal = AdmissionRecord(canonical_bytes(proposal))
    with get_session() as session:
        with session.begin():
            transport.bind_dispatch(record, running_proposal, transaction=session)

    running_record = transport.restore(
        execution_uuid=case.execution,
        authority=run_auth,
        mode="external-db-fresh",
    )

    runner_ctx = p3_bindings.bootstrap_snapshot(running_record)
    with pytest.raises(AssertionError, match="mutable loader reached"):
        runner_ctx.graph_loader.load_workflow(case.workflow)

    nodes, workflow = p3_bindings.load_snapshot(running_record, runner_ctx)
    assert workflow.name == case.workflow
    assert len(nodes) == 1

    exec_ctx = ExecutionContext(
        run_id=case.execution,
        workflow_name=case.workflow,
        node_path="n",
        agent_name="a",
        event_recorder=object(),  # type: ignore[arg-type]
        tool_executor=object(),  # type: ignore[arg-type]
        workspace_path=case.ws,
    )
    bound_ctx = p3_bindings.bind_context(running_record, exec_ctx)
    assert bound_ctx.admission_required is True
    assert bound_ctx.admission is not None
    assert bound_ctx.admission_hooks is not None


def test_direct_capture_adapter_and_variant_refusal_twins() -> None:
    rig = make_populated_test_rig()
    bindings = rig.composition.candidate_bindings
    caller = Caller(name="p3-authorized-caller")

    assert bindings.designated("designated_v1") is True
    assert bindings.designated("undesignated_v1") is False

    auth = bindings.authority_for_submit(caller, "designated_v1")
    assert isinstance(auth, DescriptorAuthority)
    assert auth.expected_descriptor_sha256 == rig.v1_harness.expected_descriptor_sha256
    assert auth.expected_source_sha256 == rig.v1_harness.expected_source_sha256

    bindings.register_run_dispatch(DISPATCH_1.execution_uuid, DISPATCH_1)
    run_auth = bindings.authority_for_run(DISPATCH_1.execution_uuid)
    assert run_auth.expected_descriptor_sha256 == auth.expected_descriptor_sha256

    transport = bindings.transport(auth)
    assert isinstance(transport, DbAdmissionTransport)

    runner_ctx = bindings.bootstrap_snapshot(object())  # type: ignore[arg-type]
    with pytest.raises(AdmissionRefused) as exc_mutable:
        runner_ctx.graph_loader.load_workflow("designated_v1")
    assert exc_mutable.value.code is CandidateRefusalCode.AUTHORITY

    # Variant refusals: sealed, Pi-containing, continuation, direct bypass
    for flag in (
        "sealed_variant",
        "pi_containing",
        "continuation_enabled",
        "direct_bypass_allowed",
    ):
        bad_adapter = replace(rig.v1_harness.capture_adapter, **{flag: True})
        bad_bindings = P3CandidateBindings(
            registry=rig.composition.registry,
            caller_peer_provider=StaticCallerPeerProvider(
                default_peer=rig.peer_submit,
            ),
            session_factory=rig.v1_harness.session_factory,
            capture_adapter=bad_adapter,
            installation_verifier=rig.v1_harness.installation_verifier,
            preparation_verifier=rig.v1_harness.preparation_verifier,
            designated_workflows=frozenset({"designated_v1"}),
            default_dispatch_identity=DISPATCH_1,
        )
        bad_bindings.register_run_dispatch(DISPATCH_1.execution_uuid, DISPATCH_1)
        with pytest.raises(AdmissionRefused) as exc_sub:
            bad_bindings.authority_for_submit(caller, "designated_v1")
        assert exc_sub.value.code is CandidateRefusalCode.MODE

        with pytest.raises(AdmissionRefused) as exc_run:
            bad_bindings.authority_for_run(DISPATCH_1.execution_uuid)
        assert exc_run.value.code is CandidateRefusalCode.MODE


def test_candidate_bindings_registry_and_digest_mismatch_refusal_twins() -> None:
    rig = make_populated_test_rig()
    bindings = rig.composition.candidate_bindings
    caller = Caller(name="p3-authorized-caller")

    # Non-designated workflow refuses with MODE
    with pytest.raises(AdmissionRefused) as exc_mode:
        bindings.authority_for_submit(caller, "non_designated")
    assert exc_mode.value.code is CandidateRefusalCode.MODE

    # Unmapped caller refuses with AUTHORITY
    with pytest.raises(AdmissionRefused) as exc_caller:
        bindings.authority_for_submit(Caller(name="unknown-caller"), "designated_v1")
    assert exc_caller.value.code is CandidateRefusalCode.AUTHORITY

    # Invalid caller type or empty workflow
    with pytest.raises(AdmissionRefused) as exc_bad_caller:
        bindings.authority_for_submit("not-a-caller", "designated_v1")  # type: ignore[arg-type]
    assert exc_bad_caller.value.code is CandidateRefusalCode.AUTHORITY

    with pytest.raises(AdmissionRefused) as exc_empty_run:
        bindings.authority_for_run("")
    assert exc_empty_run.value.code is CandidateRefusalCode.AUTHORITY

    # Wrong dispatch registered for execution -> P3CandidateAuthorityRefusal(DISPATCH_CHANGED -> LOOKUP)
    bindings.register_run_dispatch(DISPATCH_1.execution_uuid, DISPATCH_2)
    with pytest.raises(P3CandidateAuthorityRefusal) as exc_disp:
        bindings.authority_for_run(DISPATCH_1.execution_uuid)
    assert exc_disp.value.code is CandidateRefusalCode.LOOKUP
    assert exc_disp.value.p3_refusal.code is RefusalCode.DISPATCH_CHANGED
    assert exc_disp.value.p3_refusal.phase is Phase.A

    # Restore valid dispatch, then revoke authority -> P3CandidateAuthorityRefusal(AUTHORITY_REVOKED -> AUTHORITY)
    bindings.register_run_dispatch(DISPATCH_1.execution_uuid, DISPATCH_1)
    rig.issuer_verifier.set_revoked(AUTHORITY_REF_1, True)
    with pytest.raises(P3CandidateAuthorityRefusal) as exc_rev:
        bindings.authority_for_submit(caller, "designated_v1")
    assert exc_rev.value.code is CandidateRefusalCode.AUTHORITY
    assert exc_rev.value.p3_refusal.code is RefusalCode.AUTHORITY_REVOKED
    rig.issuer_verifier.set_revoked(AUTHORITY_REF_1, False)

    # Descriptor digest mismatch between SelectedJob and CandidateCaptureAdapter -> AUTHORITY
    bad_desc_adapter = replace(
        rig.v1_harness.capture_adapter,
        expected_descriptor_sha256="f" * 64,
    )
    bad_desc_bindings = P3CandidateBindings(
        registry=rig.composition.registry,
        caller_peer_provider=StaticCallerPeerProvider(default_peer=rig.peer_submit),
        session_factory=rig.v1_harness.session_factory,
        capture_adapter=bad_desc_adapter,
        installation_verifier=rig.v1_harness.installation_verifier,
        preparation_verifier=rig.v1_harness.preparation_verifier,
        designated_workflows=frozenset({"designated_v1"}),
    )
    with pytest.raises(AdmissionRefused) as exc_desc:
        bad_desc_bindings.authority_for_submit(caller, "designated_v1")
    assert exc_desc.value.code is CandidateRefusalCode.AUTHORITY

    # Foreign DescriptorAuthority rejected by transport()
    foreign_auth = DescriptorAuthority(
        expected_descriptor_sha256="9" * 64,
        expected_source_sha256="8" * 64,
        authorized_caller_label="foreign",
        receipt_id="foreign-receipt",
    )
    with pytest.raises(AdmissionRefused) as exc_foreign:
        bindings.transport(foreign_auth)
    assert exc_foreign.value.code is CandidateRefusalCode.AUTHORITY


def test_transactional_install_rollback_and_claim_fence_sqlite_and_pg(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    record_property: pytest.RecordProperty,
) -> None:
    """Prove transactional rollback, duplicate-install arbitration, and row-fence
    claim_if_current guarantees on both SQLite and real throwaway Postgres (tests/pgtier.py),
    with zero verifier/RPC calls while holding the DB claim lock.
    """
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event

    from sqlalchemy.exc import OperationalError
    from sqlmodel import select

    from temper_ai.config.admission_contract import AdmissionRecord, canonical_bytes
    from temper_ai.database import get_database, init_database, reset_database
    from temper_ai.runner.models import WorkflowRun
    from tests.conftest import TEST_DATABASE_URL
    from tests.pgtier import database_tier_url, truncate_everything

    pg_url = database_tier_url(None)
    if pg_url:
        reset_database()
        init_database(pg_url)
        truncate_everything()
        request.node.stash[TEST_DATABASE_URL] = pg_url
        record_property("concurrency_evidence", "actual PostgreSQL")
    else:
        sqlite_url = f"sqlite:///{tmp_path / 'p3_candidate_fence.db'}"
        reset_database()
        init_database(sqlite_url)
        request.node.stash[TEST_DATABASE_URL] = sqlite_url
        record_property("concurrency_evidence", "local SQLite counterpart")

    case = Case(tmp_path)
    entry = EntryBindings(case)
    rig = make_populated_test_rig()

    desc_sha = entry.authority.expected_descriptor_sha256
    src_sha = entry.authority.expected_source_sha256
    dispatch = DispatchIdentity(
        execution_uuid=case.execution,
        dispatch_nonce="00000000-0000-4000-8000-000000000003",
        running_attempt=1,
    )
    pre_job = make_pre_dispatch_job(
        designated_workflow=case.workflow,
        execution_uuid=case.execution,
        selection_revision="sel-fence-pre",
        approved_descriptor_digest=desc_sha,
        expected_source_digest=src_sha,
    )
    run_job = make_running_job(
        dispatch=dispatch,
        selection_revision="sel-fence-run",
        approved_descriptor_digest=desc_sha,
        expected_source_digest=src_sha,
    )
    snapshot = SelectionSnapshot(
        snapshot_revision="snap-fence-1",
        jobs=(pre_job, run_job),
        verified_at=TRUSTED_NOW,
    )
    for job in (pre_job, run_job):
        subj = snapshot.subject_for(job)
        for ref in (job.selector_issuer, *job.authority_refs):
            rig.issuer_verifier.register_authority(
                ref,
                make_verified_authority(
                    authority=ref,
                    subject=subj,
                    actors=frozenset({PROCESS_SUBMIT, PROCESS_RUN}),
                ),
                job=job,
            )
    rig.publisher.publish_snapshot(snapshot)

    caller = Caller(name=AUTHOR)
    caller_peers = StaticCallerPeerProvider(
        submit_peers={(AUTHOR, case.workflow): rig.peer_submit},
        run_peers={case.execution: rig.peer_run},
    )
    p3_bindings = P3CandidateBindings(
        registry=rig.composition.registry,
        caller_peer_provider=caller_peers,
        delegate_bindings=entry,
        designated_workflows=frozenset({case.workflow}),
        default_dispatch_identity=dispatch,
    )
    p3_bindings.register_run_dispatch(case.execution, dispatch)

    submit_auth = p3_bindings.authority_for_submit(caller, case.workflow)
    transport = p3_bindings.transport(submit_auth)
    case.store_rows()

    descriptor = entry.codec.descriptor(
        bytes(
            entry.codec.descriptor(
                entry.case.literal_queued_record()["immutable"]["descriptor_json"].encode(),
                submit_auth,
            ).wire
        ),
        submit_auth,
    )
    with get_session() as session:
        with session.begin():
            record = p3_bindings.prepare(
                descriptor,
                request={"workflow_name": case.workflow},
                transaction=session,
            )

    # 1. Transactional rollback on failed verify_install leaves no installed admission
    orig_verify_install = entry.verify_install

    def _fail_install(*_args: object, **_kwargs: object) -> bool:
        return False

    entry.verify_install = _fail_install
    with pytest.raises(AdmissionRefused):
        with get_session() as session:
            with session.begin():
                transport.install(admission=record, transaction=session)
    entry.verify_install = orig_verify_install

    # 2. Install arbitration (concurrent race on real PG; sequential duplicate on SQLite)
    if get_database().engine.dialect.name == "postgresql":
        both_validated = Barrier(2, timeout=10)

        def _barrier_verify(*args: object, **kwargs: object) -> bool:
            res = orig_verify_install(*args, **kwargs)
            both_validated.wait()
            return res

        entry.verify_install = _barrier_verify

        def _attempt_install() -> str:
            try:
                with get_session() as session:
                    transport.install(admission=record, transaction=session)
                return "installed"
            except AdmissionRefused:
                return "collision"

        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = [pool.submit(_attempt_install) for _ in range(2)]
            outcomes = sorted(f.result(timeout=15) for f in futs)
        assert outcomes == ["collision", "installed"]
        entry.verify_install = orig_verify_install
    else:
        with get_session() as session:
            with session.begin():
                transport.install(admission=record, transaction=session)
        with pytest.raises(AdmissionRefused):
            with get_session() as session:
                with session.begin():
                    transport.install(admission=record, transaction=session)

    # 3. Bind dispatch and verify claim_if_current holds row lock with zero verifier/network calls
    proposal = record.value()
    proposal["dispatch"] = {
        "phase": "running",
        "running_attempt": 1,
        "previous_nonce": proposal["dispatch"]["dispatch_nonce"],
        "dispatch_nonce": dispatch.dispatch_nonce,
        "worker_label": transport.worker_identity(),
    }
    running_proposal = AdmissionRecord(canonical_bytes(proposal))
    with get_session() as session:
        with session.begin():
            transport.bind_dispatch(record, running_proposal, transaction=session)

    run_auth = p3_bindings.authority_for_run(case.execution)
    running_record = transport.restore(
        execution_uuid=case.execution,
        authority=run_auth,
        mode="external-db-fresh",
    )

    import json

    from temper_ai.runner import admission as adm_mod
    from tests.test_runner import test_candidate_admission_integration as tcai

    pos = case.descriptor["positions"][0]
    native = json.loads(pos["agent_config_json"])["single_call"]
    root_path = Path(pos["root_policy"]["path"])
    files = [Path(native["prompt_path"]), Path(native["pricing_path"])]
    readiness_receipt = entry.codec.readiness(
        canonical_bytes(
            {
                "format": "candidate-root-readiness/v1",
                "preparation_path": pos["preparation_path"],
                "position_id": pos["position_id"],
                "descriptor_sha256": desc_sha,
                "graph_sha256": running_record.value()["immutable"][
                    "effective_graph_sha256"
                ],
                "execution_uuid": case.execution,
                "dispatch_nonce": dispatch.dispatch_nonce,
                "running_attempt": 1,
                "checkpoint_sha256": "3" * 64,
                "root": tcai.measure(root_path),
                "parents": [
                    tcai.measure(p)
                    for p in reversed(root_path.parents)
                    if str(p) != "/"
                ],
                "files": [
                    {
                        "stat": tcai.measure(f),
                        "length": f.stat().st_size,
                        "sha256": tcai.sha(f.read_bytes()),
                    }
                    for f in files
                ],
                "durable": True,
            }
        )
    )
    entry.verify_preparation = lambda *a, **kw: True  # type: ignore[method-assign]
    with get_session() as session:
        ready = transport.bind_root_readiness(
            running_record,
            readiness_receipt,
            verified_preparation=object(),
            transaction=session,
        )

    verifier_calls_under_lock = 0
    orig_issuer_verify = rig.issuer_verifier.verify

    def _spy_issuer_verify(*args: object, **kwargs: object):
        nonlocal verifier_calls_under_lock
        verifier_calls_under_lock += 1
        return orig_issuer_verify(*args, **kwargs)

    rig.issuer_verifier.verify = _spy_issuer_verify  # type: ignore[method-assign]

    if get_database().engine.dialect.name == "postgresql":
        entered, leave = Event(), Event()

        def _claim_callback() -> str:
            entered.set()
            assert leave.wait(10)
            return "claimed-exclusively"

        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(transport.claim_if_current, ready, _claim_callback)
            assert entered.wait(10)
            try:
                with pytest.raises(OperationalError) as pg_err:
                    with get_session() as session:
                        session.exec(
                            select(WorkflowRun)
                            .where(WorkflowRun.execution_id == case.execution)
                            .with_for_update(nowait=True)
                        ).one()
                assert getattr(pg_err.value.orig, "pgcode", None) == "55P03"
            finally:
                leave.set()
            assert fut.result(timeout=10) == "claimed-exclusively"
    else:
        assert (
            transport.claim_if_current(ready, lambda: "claimed-sqlite")
            == "claimed-sqlite"
        )

    # Zero issuer verifier / RPC calls occurred while holding the DB claim lock
    assert verifier_calls_under_lock == 0

    # 4. Mid-boundary cancellation invalidates subsequent claim_if_current without running callback
    with get_session() as session:
        row = adm_mod.locked_run(session, case.execution)
        row.cancel_requested = True
        session.add(row)
        session.commit()

    callback_ran = False

    def _never_run() -> str:
        nonlocal callback_ran
        callback_ran = True
        return "unexpected"

    with pytest.raises(AdmissionRefused):
        transport.claim_if_current(ready, _never_run)
    assert callback_ran is False

