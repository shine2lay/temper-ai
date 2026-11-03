"""Tests for P3 T5 N5 ``PublicationCohortQAReceivingVerifier`` (row ``QA-T5-N5``)."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from p3_host_contracts import LifecycleKey, RawRef
from temper_ai.p3_authority import qa_receiving
from temper_ai.p3_authority.boundary_types import (
    ActualCreation,
    ActualRequestAndReceipt,
    CountDecision,
    WindowBinding,
)
from temper_ai.p3_authority.candidate_bindings import StaticCallerPeerProvider
from temper_ai.p3_authority.contract import (
    AcceptedData,
    Boundary,
    Phase,
    Refusal,
    RefusalCode,
    RetryKind,
)
from temper_ai.p3_authority.qa_receiving import (
    MappingPublicationCohortSource,
    OriginalExpectations,
    PublicationCohort,
    PublicationCohortMember,
    PublicationCohortQAReceivingVerifier,
)
from temper_ai.p3_authority.registry import default_effect_for_job
from temper_ai.p3_authority.service import compose_p3_authority
from tests.test_p3_authority._composition_fixtures import (
    DISPATCH_1,
    PROCESS_HOST,
    PROCESS_QA,
    PROCESS_WORKER,
    WITNESS_1,
    FakeNativeRootObject,
    FakeProcessRef,
    FakeQAReceiving,
    make_populated_test_rig,
    populate_boundary_happy_path_observations,
    publish_and_link_counted_receipt,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARCH_BIN = _REPO_ROOT / "configs" / "architecture" / "bin"
_TEST_BOUNDARIES: tuple[Boundary, ...] = ("A_PRE_ARM", "C_BEFORE_COUNT")


def _load_module_from_path(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def real_constants() -> dict[str, str]:
    """Load the pinned P3 expectations from configs/architecture/bin by file path."""
    p3_mod = _load_module_from_path(
        "first_app_p3", _ARCH_BIN / "first_app_p3.py"
    )
    rows_mod = _load_module_from_path(
        "first_app_p3_rows", _ARCH_BIN / "first_app_p3_rows.py"
    )
    binding_mod = _load_module_from_path(
        "ops_host_binding", _ARCH_BIN / "ops_host_binding.py"
    )
    return {
        "KIT_ID": p3_mod.KIT_ID,
        "KIT_SHA256": p3_mod.KIT_SHA256,
        "FINAL_SHA256": rows_mod.FINAL_SHA256,
        "PUBLICATION_SCHEMA": binding_mod.PUBLICATION_SCHEMA,
        "COHORT_SCHEMA": binding_mod.COHORT_SCHEMA,
    }


@pytest.fixture(scope="module")
def real_expectations(real_constants: dict[str, str]) -> OriginalExpectations:
    return OriginalExpectations(
        kit_id=real_constants["KIT_ID"],
        kit_sha256=real_constants["KIT_SHA256"],
        final_sha256=real_constants["FINAL_SHA256"],
        publication_schema=real_constants["PUBLICATION_SCHEMA"],
        cohort_schema=real_constants["COHORT_SCHEMA"],
    )


def _sha256_hex(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _make_raw_ref(path: str, label: str, *, byte_length: int = 128) -> RawRef:
    return RawRef(
        root_locator="root:qa-cohort-1",
        relative_path=path,
        byte_length=byte_length,
        sha256=_sha256_hex(label),
    )


@dataclass(frozen=True)
class CohortWorld:
    rig: Any
    obs: dict[str, Any]
    expectations: OriginalExpectations
    qa_receiving: FakeQAReceiving
    cohort: PublicationCohort
    chromium_member: PublicationCohortMember
    webkit_member: PublicationCohortMember
    host_d1_member: PublicationCohortMember
    host_d5_member: PublicationCohortMember


@pytest.fixture()
def cohort_world(real_expectations: OriginalExpectations) -> CohortWorld:
    rig = make_populated_test_rig(writes_enabled=True)
    obs = populate_boundary_happy_path_observations(rig)
    ex = rig.examples
    sel_run = obs["sel_run"]
    creator_inst = obs["creator_inst"]
    pub_schema = real_expectations.publication_schema

    chromium_key = LifecycleKey(
        selection=sel_run,
        launch_id="launch-chromium-1",
        operation_id="browser-chromium",
    )
    chromium_occ = replace(
        ex["OccurrenceHandle"],
        key=chromium_key,
        controller= None,
        witness=WITNESS_1,
        executing_processes=(creator_inst,),
        state="completed",
    )
    chromium_receipt = _make_raw_ref(
        "cohort/chromium-receipt.json", "chromium-receipt-v1"
    )
    chromium_request = _make_raw_ref(
        "cohort/chromium-request.json", "chromium-request-v1"
    )
    chromium_pub = replace(
        ex["RawPublication"],
        occurrence=chromium_occ,
        request_raw_ref=chromium_request,
        receipt_raw_ref=chromium_receipt,
        evidence_refs=(chromium_receipt,),
        outcome="success",
        cleanup_state="complete",
    )
    chromium_member = PublicationCohortMember(
        leg="chromium",
        publication=chromium_pub,
        publication_schema=pub_schema,
        inventory_receipt_sha256=chromium_receipt.sha256,
    )

    webkit_key = LifecycleKey(
        selection=sel_run,
        launch_id="launch-webkit-1",
        operation_id="browser-webkit",
    )
    webkit_occ = replace(
        ex["OccurrenceHandle"],
        key=webkit_key,
        controller=None,
        witness=WITNESS_1,
        executing_processes=(creator_inst,),
        state="completed",
    )
    webkit_receipt = _make_raw_ref("cohort/webkit-receipt.json", "webkit-receipt-v1")
    webkit_request = _make_raw_ref("cohort/webkit-request.json", "webkit-request-v1")
    webkit_pub = replace(
        ex["RawPublication"],
        occurrence=webkit_occ,
        request_raw_ref=webkit_request,
        receipt_raw_ref=webkit_receipt,
        evidence_refs=(webkit_receipt,),
        outcome="success",
        cleanup_state="complete",
    )
    webkit_member = PublicationCohortMember(
        leg="webkit",
        publication=webkit_pub,
        publication_schema=pub_schema,
        inventory_receipt_sha256=webkit_receipt.sha256,
    )

    d1_req_ref = _make_raw_ref("cohort/d1-request.json", "d1-request-v1")
    d1_rec_ref = _make_raw_ref("cohort/d1-receipt.json", "d1-receipt-v1")
    d1_bind_ref = _make_raw_ref("cohort/d1-binding.json", "d1-binding-v1")
    d1_key = replace(
        ex["RowKey"],
        selection=sel_run,
        window_id="win-1",
        binding_ref=d1_bind_ref,
        writer="checker",
        row="D-1",
        operation="crash",
        request_id="req-d1-1",
        sequence=1,
        request_raw_ref=d1_req_ref,
    )
    d1_occ = replace(
        ex["OccurrenceHandle"],
        key=d1_key,
        controller=PROCESS_HOST,
        witness=WITNESS_1,
        executing_processes=(creator_inst,),
        state="completed",
    )
    d1_pub = replace(
        obs["raw_pub"],
        occurrence=d1_occ,
        request_raw_ref=d1_req_ref,
        receipt_raw_ref=d1_rec_ref,
        evidence_refs=(d1_rec_ref,),
        outcome="success",
        cleanup_state="complete",
    )
    host_d1_member = PublicationCohortMember(
        leg="host_row",
        publication=d1_pub,
        publication_schema=pub_schema,
        inventory_receipt_sha256=d1_rec_ref.sha256,
    )

    d5_req_ref = _make_raw_ref("cohort/d5-request.json", "d5-request-v1")
    d5_rec_ref = _make_raw_ref("cohort/d5-receipt.json", "d5-receipt-v1")
    d5_bind_ref = _make_raw_ref("cohort/d5-binding.json", "d5-binding-v1")
    d5_key = replace(
        ex["RowKey"],
        selection=sel_run,
        window_id="win-1",
        binding_ref=d5_bind_ref,
        writer="checker",
        row="D-5",
        operation="start",
        request_id="req-d5-2",
        sequence=2,
        request_raw_ref=d5_req_ref,
    )
    d5_occ = replace(
        ex["OccurrenceHandle"],
        key=d5_key,
        controller=PROCESS_HOST,
        witness=WITNESS_1,
        executing_processes=(creator_inst,),
        state="completed",
    )
    d5_pub = replace(
        obs["raw_pub"],
        occurrence=d5_occ,
        request_raw_ref=d5_req_ref,
        receipt_raw_ref=d5_rec_ref,
        evidence_refs=(d5_rec_ref,),
        outcome="success",
        cleanup_state="complete",
    )
    host_d5_member = PublicationCohortMember(
        leg="host_row",
        publication=d5_pub,
        publication_schema=pub_schema,
        inventory_receipt_sha256=d5_rec_ref.sha256,
    )

    cohort = PublicationCohort(
        cohort_schema=real_expectations.cohort_schema,
        kit_id=real_expectations.kit_id,
        kit_sha256=real_expectations.kit_sha256,
        final_sha256=real_expectations.final_sha256,
        complete_publication=True,
        members=(
            chromium_member,
            webkit_member,
            host_d1_member,
            host_d5_member,
        ),
    )

    return CohortWorld(
        rig=rig,
        obs=obs,
        expectations=real_expectations,
        qa_receiving=obs["qa_recv"],
        cohort=cohort,
        chromium_member=chromium_member,
        webkit_member=webkit_member,
        host_d1_member=host_d1_member,
        host_d5_member=host_d5_member,
    )


def _make_verifier(
    world: CohortWorld,
    cohort: PublicationCohort | None,
) -> PublicationCohortQAReceivingVerifier:
    source = MappingPublicationCohortSource(
        {
            (
                world.qa_receiving.receiving_reference.digest,
                world.rig.running_job.selection_revision,
            ): cohort
        }
    )
    return PublicationCohortQAReceivingVerifier(
        cohort_source=source,
        expectations=world.expectations,
    )


def test_qa_receiving_module_import_purity_and_real_constants(
    real_constants: dict[str, str],
) -> None:
    """qa_receiving.py never imports configs/ or service.py and cold-imports cleanly."""
    assert real_constants["KIT_ID"] == "qa-project3-critical-32"
    assert len(real_constants["KIT_SHA256"]) == 64
    assert len(real_constants["FINAL_SHA256"]) == 64
    assert real_constants["PUBLICATION_SCHEMA"] == "qa-ops-host-publication/3"
    assert real_constants["COHORT_SCHEMA"] == "qa-ops-host-cohort-inventory/1"

    mod_path = _REPO_ROOT / "temper_ai" / "p3_authority" / "qa_receiving.py"
    tree = ast.parse(mod_path.read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.append(node.module)

    assert not any(
        name == "configs" or name.startswith("configs.") for name in imported_modules
    )
    assert "temper_ai.p3_authority.service" not in imported_modules

    probe = (
        "import socket, subprocess, temper_ai.p3_authority.qa_receiving as m; "
        "assert hasattr(m, 'PublicationCohortQAReceivingVerifier'); "
        "print('COLD_IMPORT_OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0
    assert "COLD_IMPORT_OK" in proc.stdout


def test_combined_happy_path_direct_and_composed_service(
    cohort_world: CohortWorld,
) -> None:
    """Full Chromium + WebKit + host-row cohort passes at before_checker & before_count,
    reaches CountDecision PASS through compose_p3_authority, and refuses ALREADY_COUNTED
    on a second before_count via EffectFenceProvider.mark_counted.
    """
    verifier = _make_verifier(cohort_world, cohort_world.cohort)
    assert verifier.expectations == cohort_world.expectations

    for boundary in _TEST_BOUNDARIES:
        assert (
            verifier.verify_qa_receiving(
                cohort_world.qa_receiving,
                selected_job=cohort_world.rig.running_job,
                boundary=boundary,
            )
            is None
        )

    rig = cohort_world.rig
    obs = cohort_world.obs
    caller_peer_provider = StaticCallerPeerProvider(
        submit_peers={("p3-authorized-caller", "designated_v1"): rig.peer_submit},
        run_peers={DISPATCH_1.execution_uuid: rig.peer_run},
    )
    composition = compose_p3_authority(
        snapshot_provider=rig.selection_provider,
        issuer_verifier=rig.issuer_verifier,
        peer_verifier=rig.peer_verifier,
        history_provider=rig.request_history_provider,
        caller_peer_provider=caller_peer_provider,
        session_factory=rig.v1_harness.session_factory,
        capture_adapter=rig.v1_harness.capture_adapter,
        installation_verifier=rig.v1_harness.installation_verifier,
        preparation_verifier=rig.v1_harness.preparation_verifier,
        designated_workflows=frozenset({"designated_v1"}),
        default_dispatch_identity=DISPATCH_1,
        host_observer=rig.host_observer,
        worker_observer=rig.worker_observer,
        root_observer=rig.root_observer,
        closure_comparator=rig.comparator,
        qa_receiving_verifier=verifier,
        effect_fence_provider=rig.effect_fence_provider,
        host_provenance=rig.host_provenance,
        host_session_peer_resolver=rig.host_session_peer_resolver,
        writes_enabled=True,
    )
    svc = composition.service
    svc.register_closure_inputs(
        selection_revision=rig.pre_dispatch_job.selection_revision,
        boundary="A_PRE_CREATE",
        reviewed_graph=obs["w_create"].reviewed,
        loaded_closure=obs["w_create"].observed,
        observation_epoch=obs["epoch"],
    )
    svc.register_closure_inputs(
        selection_revision=rig.running_job.selection_revision,
        boundary="A_PRE_ARM",
        reviewed_graph=obs["w_arm"].reviewed,
        loaded_closure=obs["w_arm"].observed,
        observation_epoch=obs["epoch"],
    )
    actual_creation = ActualCreation(
        window_id="win-1",
        object_identity=FakeNativeRootObject("fs:win-1"),
        creator=PROCESS_WORKER,
        birth=WITNESS_1,
    )
    cur_run_arm = composition.registry.check_current(
        rig.peer_checker,
        rig.running_job.selection_revision,
        "A_PRE_ARM",
        default_effect_for_job(rig.running_job, "A_PRE_ARM"),
    )
    assert isinstance(cur_run_arm, AcceptedData)
    composition.registry.bind_created(
        rig.peer_checker,
        cur_run_arm.data,
        actual_creation,
    )
    win_binding = WindowBinding(
        current=cur_run_arm.data,
        actual_creation=actual_creation,
    )

    checker_res = svc.before_checker(
        rig.peer_checker,
        win_binding,
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        obs["both_roots"],
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(checker_res, AcceptedData)

    req_res = svc.before_request(
        rig.peer_run,
        checker_res.data.binding,
        "row-1",
        obs["req_id"],
        obs["cursors"],
    )
    assert isinstance(req_res, AcceptedData)
    imm_req = req_res.data.binding

    admit_res = svc.before_admit(rig.peer_run, imm_req, obs["cursors"])
    assert isinstance(admit_res, AcceptedData)

    rec_occ = svc.record_admitted_occurrence(
        immutable_request_binding=imm_req,
        current_binding=admit_res.data.current,
        occurrence=obs["occ_handle"],
        admission_witness=WITNESS_1,
    )
    assert isinstance(rec_occ, AcceptedData)

    exec_res = svc.before_execute(
        rig.peer_run, rec_occ.data, obs["op_leg"], obs["cursors"]
    )
    assert isinstance(exec_res, AcceptedData)

    publish_and_link_counted_receipt(rig, obs)
    actual_req_and_rcpt = ActualRequestAndReceipt(
        request=imm_req,
        publication=obs["raw_pub"],
    )

    count_res = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        obs["prov"],
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(count_res, AcceptedData)
    assert isinstance(count_res.data, CountDecision)
    assert count_res.data.verdict == "PASS"
    assert count_res.data.qa_receiving == obs["qa_recv"]

    second_count_res = svc.before_count(
        rig.peer_qa,
        actual_req_and_rcpt,
        obs["p5_ass"],
        obs["prov"],
        obs["cursors"],
        obs["qa_recv"],
    )
    assert isinstance(second_count_res, Refusal)
    assert second_count_res.code is RefusalCode.ALREADY_COUNTED
    assert second_count_res.phase is Phase.C


def _build_bad_twins(
    world: CohortWorld,
) -> dict[str, tuple[Any, PublicationCohort | None, RefusalCode]]:
    """Build the 16 canonical one-change bad twins, one per check function."""
    clean = world.cohort
    qa_recv = world.qa_receiving

    # 1. _check_qa_receiving_fields: missing receiver process_registration
    bad_qa_recv = FakeQAReceiving(
        receiving_reference=qa_recv.receiving_reference,
        receiver=FakeProcessRef(""),
    )

    # 2. _check_cohort_present: no cohort returned by port
    no_cohort: PublicationCohort | None = None

    # 3. _check_chromium_leg_present: WebKit + host rows only
    webkit_only_cohort = replace(
        clean,
        members=(
            world.webkit_member,
            world.host_d1_member,
            world.host_d5_member,
        ),
    )

    # 4. _check_webkit_leg_present: Chromium + host rows only
    chromium_only_cohort = replace(
        clean,
        members=(
            world.chromium_member,
            world.host_d1_member,
            world.host_d5_member,
        ),
    )

    # 5. _check_host_row_present: browser legs only, no RowKey publication
    no_host_row_cohort = replace(
        clean,
        members=(world.chromium_member, world.webkit_member),
    )

    # 6. _check_unique_occurrence_keys: two members with identical OperationKey
    duplicate_key_cohort = replace(
        clean,
        members=(
            world.chromium_member,
            world.webkit_member,
            world.host_d1_member,
            world.host_d5_member,
            replace(world.host_d5_member),
        ),
    )

    # 7. _check_kit_id: wrong KIT_ID
    wrong_kit_id_cohort = replace(clean, kit_id="first-app-p3-kit-v999")

    # 8. _check_kit_sha256: wrong KIT_SHA256 (valid lowercase 64-hex)
    wrong_kit_sha_cohort = replace(clean, kit_sha256="a" * 64)

    # 9. _check_final_sha256: wrong FINAL_SHA256 (valid lowercase 64-hex)
    wrong_final_sha_cohort = replace(clean, final_sha256="b" * 64)

    # 10. _check_cohort_schema: wrong COHORT_SCHEMA
    wrong_cohort_schema = replace(
        clean, cohort_schema="temper.qa.p3_cohort_manifest.v999"
    )

    # 11. _check_publication_schema: wrong member PUBLICATION_SCHEMA
    wrong_pub_schema_member = replace(
        world.host_d1_member,
        publication_schema="temper.ops.host_row_publication.v999",
    )
    wrong_pub_schema_cohort = replace(
        clean,
        members=(
            world.chromium_member,
            world.webkit_member,
            wrong_pub_schema_member,
            world.host_d5_member,
        ),
    )

    # 12. _check_lowercase_digests: uppercase hex digest on member receipt & inventory
    upper_sha = world.chromium_member.publication.receipt_raw_ref.sha256.upper()
    upper_receipt_ref = replace(
        world.chromium_member.publication.receipt_raw_ref,
        sha256=upper_sha,
    )
    upper_member = replace(
        world.chromium_member,
        publication=replace(
            world.chromium_member.publication,
            receipt_raw_ref=upper_receipt_ref,
        ),
        inventory_receipt_sha256=upper_sha,
    )
    uppercase_digest_cohort = replace(
        clean,
        members=(
            upper_member,
            world.webkit_member,
            world.host_d1_member,
            world.host_d5_member,
        ),
    )

    # 13. _check_member_inventory_digests: receipt_raw_ref.sha256 != inventory_receipt_sha256
    mismatch_member = replace(
        world.webkit_member,
        inventory_receipt_sha256="c" * 64,
    )
    member_digest_mismatch_cohort = replace(
        clean,
        members=(
            world.chromium_member,
            mismatch_member,
            world.host_d1_member,
            world.host_d5_member,
        ),
    )

    # 14. _check_m02_complete_publication: cohort complete_publication=False
    m02_incomplete_cohort = replace(clean, complete_publication=False)

    # 15. _check_m02_member_certainty: uncertain member outcome
    uncertain_pub = replace(
        world.host_d1_member.publication,
        outcome="uncertain",
    )
    uncertain_member = replace(world.host_d1_member, publication=uncertain_pub)
    uncertain_member_cohort = replace(
        clean,
        members=(
            world.chromium_member,
            world.webkit_member,
            uncertain_member,
            world.host_d5_member,
        ),
    )

    # 16. _check_d1_before_d5: D-5 published before D-1
    d5_before_d1_cohort = replace(
        clean,
        members=(
            world.chromium_member,
            world.webkit_member,
            world.host_d5_member,
            world.host_d1_member,
        ),
    )

    return {
        "_check_qa_receiving_fields": (
            bad_qa_recv,
            clean,
            RefusalCode.QA_RECEIVING_MISSING,
        ),
        "_check_cohort_present": (
            qa_recv,
            no_cohort,
            RefusalCode.QA_RECEIVING_MISSING,
        ),
        "_check_chromium_leg_present": (
            qa_recv,
            webkit_only_cohort,
            RefusalCode.QA_RECEIVING_MISSING,
        ),
        "_check_webkit_leg_present": (
            qa_recv,
            chromium_only_cohort,
            RefusalCode.QA_RECEIVING_MISSING,
        ),
        "_check_host_row_present": (
            qa_recv,
            no_host_row_cohort,
            RefusalCode.QA_RECEIVING_MISSING,
        ),
        "_check_unique_occurrence_keys": (
            qa_recv,
            duplicate_key_cohort,
            RefusalCode.ALREADY_COUNTED,
        ),
        "_check_kit_id": (
            qa_recv,
            wrong_kit_id_cohort,
            RefusalCode.RESULT_UNVERIFIED,
        ),
        "_check_kit_sha256": (
            qa_recv,
            wrong_kit_sha_cohort,
            RefusalCode.RESULT_UNVERIFIED,
        ),
        "_check_final_sha256": (
            qa_recv,
            wrong_final_sha_cohort,
            RefusalCode.RESULT_UNVERIFIED,
        ),
        "_check_cohort_schema": (
            qa_recv,
            wrong_cohort_schema,
            RefusalCode.RESULT_UNVERIFIED,
        ),
        "_check_publication_schema": (
            qa_recv,
            wrong_pub_schema_cohort,
            RefusalCode.RESULT_UNVERIFIED,
        ),
        "_check_lowercase_digests": (
            qa_recv,
            uppercase_digest_cohort,
            RefusalCode.RESULT_UNVERIFIED,
        ),
        "_check_member_inventory_digests": (
            qa_recv,
            member_digest_mismatch_cohort,
            RefusalCode.RESULT_UNVERIFIED,
        ),
        "_check_m02_complete_publication": (
            qa_recv,
            m02_incomplete_cohort,
            RefusalCode.RESULT_UNVERIFIED,
        ),
        "_check_m02_member_certainty": (
            qa_recv,
            uncertain_member_cohort,
            RefusalCode.RESULT_UNVERIFIED,
        ),
        "_check_d1_before_d5": (
            qa_recv,
            d5_before_d1_cohort,
            RefusalCode.RESULT_UNVERIFIED,
        ),
    }


@pytest.mark.parametrize("boundary", ["A_PRE_ARM", "C_BEFORE_COUNT"])
def test_refusal_pairs_at_both_boundaries(
    cohort_world: CohortWorld,
    boundary: Boundary,
) -> None:
    """Every canonical bad twin refuses with its exact RefusalCode while its clean twin passes."""
    expected_phase = Phase.A if boundary == "A_PRE_ARM" else Phase.C
    clean_verifier = _make_verifier(cohort_world, cohort_world.cohort)
    assert (
        clean_verifier.verify_qa_receiving(
            cohort_world.qa_receiving,
            selected_job=cohort_world.rig.running_job,
            boundary=boundary,
        )
        is None
    )

    bad_twins = _build_bad_twins(cohort_world)
    for check_name, (recv_obj, cohort_obj, expected_code) in bad_twins.items():
        verifier = _make_verifier(cohort_world, cohort_obj)
        refusal = verifier.verify_qa_receiving(
            recv_obj,
            selected_job=cohort_world.rig.running_job,
            boundary=boundary,
        )
        assert isinstance(refusal, Refusal), f"{check_name} did not refuse"
        assert refusal.code is expected_code, f"{check_name} returned {refusal.code}"
        assert refusal.phase is expected_phase
        expected_retry = (
            RetryKind.SAME_BOUNDARY_AFTER_REPAIR
            if expected_code is RefusalCode.QA_RECEIVING_MISSING
            else RetryKind.NOT_APPLICABLE
        )
        assert refusal.retry_kind is expected_retry


def test_additional_edge_and_malformed_port_refusals(
    cohort_world: CohortWorld,
) -> None:
    """Test additional boundary values, bool-int traps, cleanup states, and malformed port outputs."""
    clean = cohort_world.cohort
    job = cohort_world.rig.running_job

    # Bool-as-int trap on complete_publication=1 (Python True == 1)
    bool_int_cohort = replace(clean, complete_publication=1)  # type: ignore[arg-type]
    res_bool_int = _make_verifier(
        cohort_world, bool_int_cohort
    ).verify_qa_receiving(
        cohort_world.qa_receiving,
        selected_job=job,
        boundary="A_PRE_ARM",
    )
    assert isinstance(res_bool_int, Refusal)
    assert res_bool_int.code is RefusalCode.RESULT_UNVERIFIED

    # Bool-as-int trap on receiving_reference.length=True
    @dataclass(frozen=True)
    class _BoolLengthRef:
        path: str = "qa/receiving-1.json"
        digest: str = "9" * 64
        length: int = True  # type: ignore[assignment]
        revision: str = "qa-rev-1"

    res_bool_len = _make_verifier(cohort_world, clean).verify_qa_receiving(
        FakeQAReceiving(
            receiving_reference=_BoolLengthRef(),  # type: ignore[arg-type]
            receiver=PROCESS_QA,
        ),
        selected_job=job,
        boundary="A_PRE_ARM",
    )
    assert isinstance(res_bool_len, Refusal)
    assert res_bool_len.code is RefusalCode.QA_RECEIVING_MISSING

    # Incomplete and uncertain cleanup states refuse RESULT_UNVERIFIED
    for bad_cleanup in ("incomplete", "uncertain"):
        bad_member = replace(
            cohort_world.host_d5_member,
            publication=replace(
                cohort_world.host_d5_member.publication,
                cleanup_state=bad_cleanup,  # type: ignore[arg-type]
            ),
        )
        bad_cohort = replace(
            clean,
            members=(
                cohort_world.chromium_member,
                cohort_world.webkit_member,
                cohort_world.host_d1_member,
                bad_member,
            ),
        )
        res = _make_verifier(cohort_world, bad_cohort).verify_qa_receiving(
            cohort_world.qa_receiving,
            selected_job=job,
            boundary="C_BEFORE_COUNT",
        )
        assert isinstance(res, Refusal)
        assert res.code is RefusalCode.RESULT_UNVERIFIED

    # D-5 without D-1 in cohort refuses RESULT_UNVERIFIED
    d5_alone_cohort = replace(
        clean,
        members=(
            cohort_world.chromium_member,
            cohort_world.webkit_member,
            cohort_world.host_d5_member,
        ),
    )
    res_d5_alone = _make_verifier(cohort_world, d5_alone_cohort).verify_qa_receiving(
        cohort_world.qa_receiving,
        selected_job=job,
        boundary="C_BEFORE_COUNT",
    )
    assert isinstance(res_d5_alone, Refusal)
    assert res_d5_alone.code is RefusalCode.RESULT_UNVERIFIED

    # Uppercase KIT_SHA256 or FINAL_SHA256 refuses RESULT_UNVERIFIED (no case-folding)
    for field_name in ("kit_sha256", "final_sha256"):
        upper_val = getattr(clean, field_name).upper()
        upper_cohort = replace(clean, **{field_name: upper_val})
        res_upper = _make_verifier(cohort_world, upper_cohort).verify_qa_receiving(
            cohort_world.qa_receiving,
            selected_job=job,
            boundary="A_PRE_ARM",
        )
        assert isinstance(res_upper, Refusal)
        assert res_upper.code is RefusalCode.RESULT_UNVERIFIED

    # Port raising an exception or returning malformed data returns Refusal, never raises
    class _RaisingSource:
        def load_cohort(self, receiving_reference: Any, *, selection_revision: str) -> Any:
            raise RuntimeError("disk read failed")

    raising_verifier = PublicationCohortQAReceivingVerifier(
        cohort_source=_RaisingSource(),
        expectations=cohort_world.expectations,
    )
    res_raised = raising_verifier.verify_qa_receiving(
        cohort_world.qa_receiving,
        selected_job=job,
        boundary="A_PRE_ARM",
    )
    assert isinstance(res_raised, Refusal)
    assert res_raised.code is RefusalCode.QA_RECEIVING_MISSING

    class _MalformedSource:
        def load_cohort(self, receiving_reference: Any, *, selection_revision: str) -> Any:
            return {"not": "a-dataclass"}

    malformed_verifier = PublicationCohortQAReceivingVerifier(
        cohort_source=_MalformedSource(),
        expectations=cohort_world.expectations,
    )
    res_malformed = malformed_verifier.verify_qa_receiving(
        cohort_world.qa_receiving,
        selected_job=job,
        boundary="C_BEFORE_COUNT",
    )
    assert isinstance(res_malformed, Refusal)
    assert res_malformed.code is RefusalCode.QA_RECEIVING_MISSING


def test_constructor_validation_fails_loud_on_bad_inputs(
    real_constants: dict[str, str],
    cohort_world: CohortWorld,
) -> None:
    """OriginalExpectations and PublicationCohortQAReceivingVerifier reject invalid inputs at construction."""
    valid_kwargs = {
        "kit_id": real_constants["KIT_ID"],
        "kit_sha256": real_constants["KIT_SHA256"],
        "final_sha256": real_constants["FINAL_SHA256"],
        "publication_schema": real_constants["PUBLICATION_SCHEMA"],
        "cohort_schema": real_constants["COHORT_SCHEMA"],
    }

    for str_field in ("kit_id", "publication_schema", "cohort_schema"):
        for bad_str in ("", "   ", f" {valid_kwargs[str_field]}", f"{valid_kwargs[str_field]} ", None, 123):
            with pytest.raises(ValueError):
                OriginalExpectations(**{**valid_kwargs, str_field: bad_str})  # type: ignore[arg-type]

    for sha_field in ("kit_sha256", "final_sha256"):
        for bad_sha in (
            "",
            "a" * 63,
            "a" * 65,
            "A" * 64,
            valid_kwargs[sha_field].upper(),
            "g" * 64,
            f" {valid_kwargs[sha_field]}",
            None,
            123,
        ):
            with pytest.raises(ValueError):
                OriginalExpectations(**{**valid_kwargs, sha_field: bad_sha})  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        MappingPublicationCohortSource(None)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        PublicationCohortQAReceivingVerifier(
            cohort_source=None,  # type: ignore[arg-type]
            expectations=cohort_world.expectations,
        )

    with pytest.raises(ValueError):
        PublicationCohortQAReceivingVerifier(
            cohort_source=MappingPublicationCohortSource({}),
            expectations=None,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("boundary", ["A_PRE_ARM", "C_BEFORE_COUNT"])
def test_exact_cohort_lookup_refuses_wrong_digest_and_wrong_selection_revision(
    cohort_world: CohortWorld,
    boundary: Boundary,
) -> None:
    """Exact (digest, selection_revision) lookup refuses (a) same path + different
    lowercase digest and (b) right digest + other selection_revision with
    QA_RECEIVING_MISSING at A_PRE_ARM and C_BEFORE_COUNT.
    """
    expected_phase = Phase.A if boundary == "A_PRE_ARM" else Phase.C
    verifier = _make_verifier(cohort_world, cohort_world.cohort)

    assert (
        verifier.verify_qa_receiving(
            cohort_world.qa_receiving,
            selected_job=cohort_world.rig.running_job,
            boundary=boundary,
        )
        is None
    )

    # (a) Same path + different valid lowercase 64-hex digest -> QA_RECEIVING_MISSING
    different_digest_ref = replace(
        cohort_world.qa_receiving.receiving_reference,
        digest="8" * 64,
    )
    assert (
        different_digest_ref.path
        == cohort_world.qa_receiving.receiving_reference.path
    )
    assert (
        different_digest_ref.digest
        != cohort_world.qa_receiving.receiving_reference.digest
    )
    same_path_other_digest_receiving = FakeQAReceiving(
        receiving_reference=different_digest_ref,
        receiver=cohort_world.qa_receiving.receiver,
    )
    refusal_a = verifier.verify_qa_receiving(
        same_path_other_digest_receiving,
        selected_job=cohort_world.rig.running_job,
        boundary=boundary,
    )
    assert isinstance(refusal_a, Refusal)
    assert refusal_a.code is RefusalCode.QA_RECEIVING_MISSING
    assert refusal_a.phase is expected_phase
    assert refusal_a.retry_kind is RetryKind.SAME_BOUNDARY_AFTER_REPAIR

    # (b) Right digest + other selection_revision -> QA_RECEIVING_MISSING
    other_selection_job = replace(
        cohort_world.rig.running_job,
        selection_revision="sel-other-rev-99",
    )
    assert (
        other_selection_job.selection_revision
        != cohort_world.rig.running_job.selection_revision
    )
    refusal_b = verifier.verify_qa_receiving(
        cohort_world.qa_receiving,
        selected_job=other_selection_job,
        boundary=boundary,
    )
    assert isinstance(refusal_b, Refusal)
    assert refusal_b.code is RefusalCode.QA_RECEIVING_MISSING
    assert refusal_b.phase is expected_phase
    assert refusal_b.retry_kind is RetryKind.SAME_BOUNDARY_AFTER_REPAIR


def test_mapping_cohort_source_constructor_rejects_fallback_and_invalid_mappings(
    cohort_world: CohortWorld,
) -> None:
    """MappingPublicationCohortSource rejects bare-digest, bare-path, (path, rev),
    3-tuple, uppercase-digest, whitespace-selection, and non-cohort-value mappings.
    """
    digest = cohort_world.qa_receiving.receiving_reference.digest
    path = cohort_world.qa_receiving.receiving_reference.path
    sel_rev = cohort_world.rig.running_job.selection_revision
    cohort = cohort_world.cohort

    # Valid exact-key mappings (PublicationCohort or None) succeed
    valid_source = MappingPublicationCohortSource({(digest, sel_rev): cohort})
    assert (
        valid_source.load_cohort(
            cohort_world.qa_receiving.receiving_reference,
            selection_revision=sel_rev,
        )
        == cohort
    )
    none_source = MappingPublicationCohortSource({(digest, sel_rev): None})
    assert (
        none_source.load_cohort(
            cohort_world.qa_receiving.receiving_reference,
            selection_revision=sel_rev,
        )
        is None
    )

    invalid_mappings: list[Any] = [
        {digest: cohort},  # bare-digest key
        {path: cohort},  # bare-path key
        {(path, sel_rev): cohort},  # (path, selection_revision) key
        {(digest, path, sel_rev): cohort},  # 3-tuple key
        {(digest,): cohort},  # 1-tuple key
        {("A" * 64, sel_rev): cohort},  # uppercase-digest key
        {(cohort.kit_sha256.upper(), sel_rev): cohort},  # mixed/uppercase-digest key
        {("a" * 63, sel_rev): cohort},  # short digest key
        {("g" * 64, sel_rev): cohort},  # non-hex digest key
        {(digest, ""): cohort},  # empty selection_revision
        {(digest, "   "): cohort},  # blank selection_revision
        {(digest, f" {sel_rev}"): cohort},  # leading whitespace selection_revision
        {(digest, f"{sel_rev} "): cohort},  # trailing whitespace selection_revision
        {(digest, sel_rev): {"not": "a-cohort"}},  # non-cohort dict value
        {(digest, sel_rev): "not-a-cohort"},  # non-cohort str value
        {(digest, sel_rev): 123},  # non-cohort int value
    ]
    for bad_mapping in invalid_mappings:
        with pytest.raises(ValueError):
            MappingPublicationCohortSource(bad_mapping)


def test_exact_cohort_lookup_bite_catches_legacy_fallback(
    cohort_world: CohortWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Monkeypatching MappingPublicationCohortSource.load_cohort with the 277555d3
    fallback lookup makes (a) same path + different digest and (b) right digest +
    other selection_revision wrongly return None while the clean twin still passes.
    """
    digest = cohort_world.qa_receiving.receiving_reference.digest
    path = cohort_world.qa_receiving.receiving_reference.path
    sel_rev = cohort_world.rig.running_job.selection_revision
    cohort = cohort_world.cohort

    source = MappingPublicationCohortSource({(digest, sel_rev): cohort})
    # Seed legacy fallback keys into the backing dict so only load_cohort's lookup
    # rule differs when monkeypatched.
    source._cohorts[(path, sel_rev)] = cohort  # type: ignore[index]
    source._cohorts[digest] = cohort  # type: ignore[index]
    source._cohorts[path] = cohort  # type: ignore[index]
    verifier = PublicationCohortQAReceivingVerifier(
        cohort_source=source,
        expectations=cohort_world.expectations,
    )

    same_path_other_digest_receiving = FakeQAReceiving(
        receiving_reference=replace(
            cohort_world.qa_receiving.receiving_reference,
            digest="8" * 64,
        ),
        receiver=cohort_world.qa_receiving.receiver,
    )
    other_selection_job = replace(
        cohort_world.rig.running_job,
        selection_revision="sel-other-rev-99",
    )

    # 1. With exact load_cohort active, clean twin passes and both (a) and (b) refuse.
    for boundary in _TEST_BOUNDARIES:
        assert (
            verifier.verify_qa_receiving(
                cohort_world.qa_receiving,
                selected_job=cohort_world.rig.running_job,
                boundary=boundary,
            )
            is None
        )
        pre_a = verifier.verify_qa_receiving(
            same_path_other_digest_receiving,
            selected_job=cohort_world.rig.running_job,
            boundary=boundary,
        )
        assert isinstance(pre_a, Refusal)
        assert pre_a.code is RefusalCode.QA_RECEIVING_MISSING

        pre_b = verifier.verify_qa_receiving(
            cohort_world.qa_receiving,
            selected_job=other_selection_job,
            boundary=boundary,
        )
        assert isinstance(pre_b, Refusal)
        assert pre_b.code is RefusalCode.QA_RECEIVING_MISSING

    # 2. Monkeypatch load_cohort with the 277555d3 fallback lookup.
    def _legacy_fallback_load_cohort(
        self: MappingPublicationCohortSource,
        receiving_reference: Any,
        *,
        selection_revision: str,
    ) -> PublicationCohort | None:
        ref_digest = getattr(receiving_reference, "digest", None)
        ref_path = getattr(receiving_reference, "path", None)
        for key in (
            (ref_digest, selection_revision),
            (ref_path, selection_revision),
            ref_digest,
            ref_path,
        ):
            if key in self._cohorts:
                return self._cohorts[key]  # type: ignore[index]
        return None

    monkeypatch.setattr(
        MappingPublicationCohortSource,
        "load_cohort",
        _legacy_fallback_load_cohort,
    )

    # 3. Clean twin still passes, and both (a) and (b) now wrongly return None.
    for boundary in _TEST_BOUNDARIES:
        assert (
            verifier.verify_qa_receiving(
                cohort_world.qa_receiving,
                selected_job=cohort_world.rig.running_job,
                boundary=boundary,
            )
            is None
        )
        assert (
            verifier.verify_qa_receiving(
                same_path_other_digest_receiving,
                selected_job=cohort_world.rig.running_job,
                boundary=boundary,
            )
            is None
        )
        assert (
            verifier.verify_qa_receiving(
                cohort_world.qa_receiving,
                selected_job=other_selection_job,
                boundary=boundary,
            )
            is None
        )


@pytest.mark.parametrize(
    "check_name",
    [
        "_check_qa_receiving_fields",
        "_check_cohort_present",
        "_check_chromium_leg_present",
        "_check_webkit_leg_present",
        "_check_host_row_present",
        "_check_unique_occurrence_keys",
        "_check_kit_id",
        "_check_kit_sha256",
        "_check_final_sha256",
        "_check_cohort_schema",
        "_check_publication_schema",
        "_check_lowercase_digests",
        "_check_member_inventory_digests",
        "_check_m02_complete_publication",
        "_check_m02_member_certainty",
        "_check_d1_before_d5",
    ],
)
def test_each_check_bite_is_isolated_and_load_bearing(
    cohort_world: CohortWorld,
    monkeypatch: pytest.MonkeyPatch,
    check_name: str,
) -> None:
    """Swapping exactly one check function for a pass makes its own must-catch case
    wrongly return None at both boundaries while all other 15 must-catch cases still refuse.
    """
    bad_twins = _build_bad_twins(cohort_world)
    assert check_name in bad_twins

    own_recv, own_cohort, own_expected_code = bad_twins[check_name]
    own_verifier = _make_verifier(cohort_world, own_cohort)

    # 1. With check active, own must-catch case refuses at both boundaries.
    for boundary in _TEST_BOUNDARIES:
        pre_refusal = own_verifier.verify_qa_receiving(
            own_recv,
            selected_job=cohort_world.rig.running_job,
            boundary=boundary,
        )
        assert isinstance(pre_refusal, Refusal)
        assert pre_refusal.code is own_expected_code

    # 2. Swap ONLY `check_name` for a pass in memory.
    monkeypatch.setattr(qa_receiving, check_name, lambda *a, **kw: True)

    # 3. Own must-catch case now wrongly passes (returns None) at both boundaries.
    for boundary in _TEST_BOUNDARIES:
        bitten_result = own_verifier.verify_qa_receiving(
            own_recv,
            selected_job=cohort_world.rig.running_job,
            boundary=boundary,
        )
        assert bitten_result is None, (
            f"{check_name} was masked at {boundary}: {bitten_result!r}"
        )

    # 4. Every other check's must-catch case still refuses with its expected code.
    for other_name, (other_recv, other_cohort, other_code) in bad_twins.items():
        if other_name == check_name:
            continue
        other_verifier = _make_verifier(cohort_world, other_cohort)
        for boundary in _TEST_BOUNDARIES:
            other_refusal = other_verifier.verify_qa_receiving(
                other_recv,
                selected_job=cohort_world.rig.running_job,
                boundary=boundary,
            )
            assert isinstance(other_refusal, Refusal), (
                f"Removing {check_name} broke {other_name} at {boundary}"
            )
            assert other_refusal.code is other_code
