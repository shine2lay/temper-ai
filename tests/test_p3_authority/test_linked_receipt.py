"""T5-A2: a count uses only receipts the HostProvenance port authenticated.

Security #243 (REPORT.md sha256 611327de...) found before_count verifying the
counted row and its earlier row from the caller's own objects, behind class
gates that only the test double passed. Architecture's port ruling (RULING.md
sha256 476c21c4...) and #477's review settle the fix: the port answers
``verify_linked_receipt`` from its own chain, a D-5 row needs a verified D-1
predecessor, no provider class gate, members checked at composition.

The combined happy path comes first (rule bp-be8d76b9), then the edges. Every
new guard has a bite: the echoing adapter (wrong on purpose) shows which
refusals are the service's own, a source-fitness check flags planted code.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from typing import Any

import pytest

from temper_ai.api.caller import Caller
from temper_ai.p3_authority import _providers as providers_module
from temper_ai.p3_authority import service as service_module
from temper_ai.p3_authority._providers import (
    InMemoryHostObserver,
    InMemoryHostProvenance,
)
from temper_ai.p3_authority.boundary_types import (
    ActualCreation,
    ActualRequestAndReceipt,
    ImmutableRequestBinding,
    VerifiedReceiptBinding,
    WindowBinding,
)
from temper_ai.p3_authority.contract import (
    AcceptedData,
    HostObserver,
    HostProvenance,
    Refusal,
    RefusalCode,
    Result,
)
from temper_ai.p3_authority.host_ports import require_port_members
from temper_ai.p3_authority.host_provenance_conformance import (
    AdapterUnderTest,
    ConformanceTemplates,
    failed_outcomes,
    run_conformance,
)
from temper_ai.p3_authority.registry import default_effect_for_job
from temper_ai.p3_authority.service import compose_p3_authority
from tests.test_p3_authority._composition_fixtures import (
    DISPATCH_1,
    PROCESS_WORKER,
    WITNESS_1,
    WITNESS_2,
    FakeNativeRootObject,
    FakeWitness,
    PopulatedAuthorityTestRig,
    make_populated_test_rig,
    populate_boundary_happy_path_observations,
    publish_and_link_counted_receipt,
)
from tests.test_p3_authority._port_only_hosts import (
    EchoingHostProvenance,
    PortOnlyHostObserver,
    PortOnlyHostProvenance,
)

# -- driving a window to its count ------------------------------------------


def _d1_d5_window(
    *, host_provenance: Any = None
) -> tuple[PopulatedAuthorityTestRig, dict[str, Any], Any]:
    """A port-only rig whose window win-1 holds D-1 (linked) and D-5 (to count).

    Returns the rig, the observations and the checker's window binding.
    """
    rig = make_populated_test_rig(host_ports="port-only", host_provenance=host_provenance)
    obs = populate_boundary_happy_path_observations(
        rig, predecessor_row="D-1", counted_row="D-5"
    )
    rig.composition.service.register_allowed_rows(
        rig.running_job.selection_revision, {"D-1", "D-5"}
    )
    bindings = rig.composition.candidate_bindings
    bindings.authority_for_submit(Caller(name="p3-authorized-caller"), "designated_v1")
    bindings.register_run_dispatch(DISPATCH_1.execution_uuid, DISPATCH_1)
    bindings.authority_for_run(DISPATCH_1.execution_uuid)

    current = rig.composition.registry.check_current(
        rig.peer_checker,
        rig.running_job.selection_revision,
        "A_PRE_ARM",
        default_effect_for_job(rig.running_job, "A_PRE_ARM"),
    )
    assert isinstance(current, AcceptedData), current
    checker = rig.composition.service.before_checker(
        rig.peer_checker,
        WindowBinding(
            current=current.data,
            actual_creation=ActualCreation(
                window_id="win-1",
                object_identity=FakeNativeRootObject("fs:win-1"),
                creator=PROCESS_WORKER,
                birth=WITNESS_1,
            ),
        ),
        obs["host_obs_arm"],
        obs["worker_obs_arm"],
        obs["both_roots"],
        obs["cmp_arm"],
        obs["qa_recv"],
        obs["compat_recv"],
        obs["producer_binding"],
    )
    assert isinstance(checker, AcceptedData), checker
    return rig, obs, checker.data.binding


def _execute_row(
    rig: PopulatedAuthorityTestRig,
    obs: dict[str, Any],
    checker_binding: Any,
    *,
    row: str,
    key: Any,
    occurrence: Any,
) -> ImmutableRequestBinding:
    """Request, admit, record and execute one row; return its request binding."""
    svc = rig.composition.service
    request = svc.before_request(rig.peer_run, checker_binding, row, key, obs["cursors"])
    assert isinstance(request, AcceptedData), request
    admit = svc.before_admit(rig.peer_run, request.data.binding, obs["cursors"])
    assert isinstance(admit, AcceptedData), admit
    recorded = svc.record_admitted_occurrence(
        immutable_request_binding=request.data.binding,
        current_binding=admit.data.current,
        occurrence=occurrence,
        admission_witness=WITNESS_1,
    )
    assert isinstance(recorded, AcceptedData), recorded
    executed = svc.before_execute(
        rig.peer_run, recorded.data, obs["op_leg"], obs["cursors"]
    )
    assert isinstance(executed, AcceptedData), executed
    return request.data.binding


def _count(
    rig: PopulatedAuthorityTestRig,
    obs: dict[str, Any],
    request: ImmutableRequestBinding,
    publication: Any,
    provenance: Any,
) -> Result[Any]:
    return rig.composition.service.before_count(
        rig.peer_qa,
        ActualRequestAndReceipt(request=request, publication=publication),
        obs["p5_ass"],
        provenance,
        obs["cursors"],
        obs["qa_recv"],
    )


def _d5_ready_to_count(
    *, host_provenance: Any = None, link_counted: bool = True
) -> tuple[PopulatedAuthorityTestRig, dict[str, Any], ImmutableRequestBinding]:
    rig, obs, checker_binding = _d1_d5_window(host_provenance=host_provenance)
    if link_counted:
        publish_and_link_counted_receipt(rig, obs)
    request = _execute_row(
        rig, obs, checker_binding, row="D-5", key=obs["req_id"], occurrence=obs["occ_handle"]
    )
    return rig, obs, request


def _refusal_code(result: Result[Any]) -> RefusalCode | str:
    return result.code if isinstance(result, Refusal) else "ACCEPTED"


# -- the combined happy path --------------------------------------------------


def test_port_only_hosts_count_d1_then_d5_with_a_port_verified_predecessor() -> None:
    """Port-only adapters (no double, no port base): D-1 counts, then D-5 counts
    with the predecessor the port linked; receive and the join agree; writes off."""
    rig, obs, checker_binding = _d1_d5_window()
    svc = rig.composition.service
    join = rig.composition.host_join
    for adapter in (rig.host_provenance, rig.host_observer):
        mro = type(adapter).__mro__
        assert InMemoryHostProvenance not in mro and InMemoryHostObserver not in mro
        assert HostProvenance not in mro and HostObserver not in mro
    assert svc.writes_enabled is False

    # D-1: the window's first link; counted with no predecessor.
    d1_request = _execute_row(
        rig,
        obs,
        checker_binding,
        row="D-1",
        key=obs["pred_key"],
        occurrence=obs["pred_occ_handle"],
    )
    d1_count = _count(rig, obs, d1_request, obs["pred_pub"], obs["pred_prov"])
    assert isinstance(d1_count, AcceptedData), d1_count
    d1_receipt = d1_count.data.native_receiving
    assert type(d1_receipt) is getattr(
        VerifiedReceiptBinding, "__origin__", VerifiedReceiptBinding
    )
    assert d1_receipt.disposition == "verified"
    assert d1_receipt.provenance == obs["pred_prov"]
    assert d1_receipt.predecessor is None

    # D-5: linked after D-1 by the host; the join reads it, receive verifies it.
    publish_and_link_counted_receipt(rig, obs)
    occurrence = join.lookup_occurrence(rig.session_host, obs["req_id"])
    assert isinstance(occurrence, AcceptedData), occurrence
    published = join.verify_publication(
        rig.session_host, obs["req_id"], obs["raw_pub"], occurrence.data
    )
    assert isinstance(published, AcceptedData), published
    assert published.data == obs["prov"]
    received = join.receive(
        rig.session_host,
        obs["req_id"],
        published.data,
        replace(
            rig.examples["HostEffect"],
            selection=obs["sel_run"],
            boundary="C_PRE_EXECUTION",
            operation="launch",
        ),
    )
    assert isinstance(received, AcceptedData), received
    assert received.data.predecessor == obs["pred_prov"]

    d5_request = _execute_row(
        rig, obs, checker_binding, row="D-5", key=obs["req_id"], occurrence=obs["occ_handle"]
    )
    d5_count = _count(rig, obs, d5_request, obs["raw_pub"], obs["prov"])
    assert isinstance(d5_count, AcceptedData), d5_count
    d5_receipt = d5_count.data.native_receiving
    assert d5_receipt.disposition == "verified"
    assert d5_receipt.provenance == obs["prov"]
    assert d5_receipt.predecessor == obs["pred_prov"]
    assert d5_receipt.receiving == WITNESS_1
    assert d5_count.data.verdict == "PASS"
    assert svc.writes_enabled is False

    # Counted once: the same D-5 receipt does not count again.
    again = _count(rig, obs, d5_request, obs["raw_pub"], obs["prov"])
    assert _refusal_code(again) is RefusalCode.ALREADY_COUNTED


# -- the predecessor a D-5 names (M1, P1) -------------------------------------


def _planted(obs: dict[str, Any], rig: PopulatedAuthorityTestRig) -> Any:
    """A receipt the host published for an earlier D-1 but never linked."""
    key = replace(obs["pred_key"], request_id="req-planted")
    occurrence = replace(obs["pred_occ_handle"], key=key)
    publication = replace(obs["pred_pub"], occurrence=occurrence)
    planted = replace(obs["pred_prov"], operation_key=key, raw_publication=publication)
    rig.host_provenance.register_occurrence(key, occurrence, witness=WITNESS_1)
    rig.host_provenance.publish_receipt(
        planted, request_raw=obs["pred_req_bytes"], receipt_raw=obs["rec_bytes"]
    )
    return planted


def _tampered(obs: dict[str, Any], rig: PopulatedAuthorityTestRig) -> Any:
    receipt_ref = replace(obs["rec_raw_ref"], sha256="0" * 64)
    return replace(
        obs["pred_prov"],
        raw_publication=replace(obs["pred_pub"], receipt_raw_ref=receipt_ref),
    )


def _failed(obs: dict[str, Any], rig: PopulatedAuthorityTestRig) -> Any:
    occurrence = replace(obs["pred_occ_handle"], state="failed")
    return replace(
        obs["pred_prov"],
        raw_publication=replace(
            obs["pred_pub"], occurrence=occurrence, outcome="app-failure"
        ),
    )


def _foreign(obs: dict[str, Any], rig: PopulatedAuthorityTestRig) -> Any:
    key = replace(obs["pred_key"], selection=obs["sel_pre"])
    occurrence = replace(obs["pred_occ_handle"], key=key)
    return replace(
        obs["pred_prov"],
        operation_key=key,
        raw_publication=replace(obs["pred_pub"], occurrence=occurrence),
    )


def _other_row(obs: dict[str, Any], rig: PopulatedAuthorityTestRig) -> Any:
    key = replace(obs["pred_key"], row="R-1i")
    occurrence = replace(obs["pred_occ_handle"], key=key)
    return replace(
        obs["pred_prov"],
        operation_key=key,
        raw_publication=replace(obs["pred_pub"], occurrence=occurrence),
    )


def _lookalike_class(obs: dict[str, Any], rig: PopulatedAuthorityTestRig) -> Any:
    record = type(obs["pred_prov"])
    lookalike = type("LookalikeReceiptProvenance", (record,), {"__slots__": ()})
    return lookalike(
        **{name: getattr(obs["pred_prov"], name) for name in record.__dataclass_fields__}
    )


def _none(obs: dict[str, Any], rig: PopulatedAuthorityTestRig) -> Any:
    return None


BAD_PREDECESSORS = {
    # kind: (predecessor builder, refusal, the service's own check)
    "none": (_none, RefusalCode.PRIOR_MISSING, True),
    "failed": (_failed, RefusalCode.PRIOR_UNVERIFIED, True),
    "foreign": (_foreign, RefusalCode.PRIOR_FOREIGN, True),
    "other-row": (_other_row, RefusalCode.PRIOR_UNVERIFIED, True),
    "lookalike-class": (_lookalike_class, RefusalCode.PRIOR_UNVERIFIED, True),
    "planted-unlinked": (_planted, RefusalCode.PRIOR_UNVERIFIED, False),
    "tampered": (_tampered, RefusalCode.PRIOR_UNVERIFIED, False),
}


@pytest.mark.parametrize("kind", sorted(BAD_PREDECESSORS))
def test_d5_counts_only_after_the_predecessor_the_port_linked(kind: str) -> None:
    build, expected, _ = BAD_PREDECESSORS[kind]
    rig, obs, request = _d5_ready_to_count()
    provenance = replace(obs["prov"], predecessor=build(obs, rig))
    assert _refusal_code(_count(rig, obs, request, obs["raw_pub"], provenance)) is expected
    # The good receipt still counts afterwards: nothing above consumed it.
    ok = _count(rig, obs, request, obs["raw_pub"], obs["prov"])
    assert isinstance(ok, AcceptedData), ok


@pytest.mark.parametrize(
    "kind", sorted(kind for kind, (_, _, own) in BAD_PREDECESSORS.items() if own)
)
def test_service_refuses_a_bad_predecessor_even_when_the_port_echoes_it(kind: str) -> None:
    """Bite of the service's own predecessor checks: a port that accepts the
    caller's receipt (EchoingHostProvenance) still gets these refused."""
    build, expected, _ = BAD_PREDECESSORS[kind]
    rig, obs, request = _d5_ready_to_count(host_provenance=EchoingHostProvenance())
    provenance = replace(obs["prov"], predecessor=build(obs, rig))
    assert _refusal_code(_count(rig, obs, request, obs["raw_pub"], provenance)) is expected


def test_port_check_is_what_refuses_planted_and_tampered_predecessors() -> None:
    """Bite of M1: these pass the service's shape checks, so only the port's
    answer from its own chain refuses them (an echoing port lets them count)."""
    for kind in ("planted-unlinked", "tampered"):
        build, _, _ = BAD_PREDECESSORS[kind]
        rig, obs, request = _d5_ready_to_count(host_provenance=EchoingHostProvenance())
        provenance = replace(obs["prov"], predecessor=build(obs, rig))
        assert isinstance(
            _count(rig, obs, request, obs["raw_pub"], provenance), AcceptedData
        ), kind


def _with_predecessor_key(obs: dict[str, Any], **changes: Any) -> Any:
    key = replace(obs["pred_key"], **changes)
    occurrence = replace(obs["pred_occ_handle"], key=key)
    return replace(
        obs["pred_prov"],
        operation_key=key,
        raw_publication=replace(obs["pred_pub"], occurrence=occurrence),
    )


def _with_predecessor_publication(obs: dict[str, Any], **changes: Any) -> Any:
    return replace(obs["pred_prov"], raw_publication=replace(obs["pred_pub"], **changes))


def _with_predecessor_occurrence(obs: dict[str, Any], **changes: Any) -> Any:
    occurrence = replace(obs["pred_occ_handle"], **changes)
    return _with_predecessor_publication(obs, occurrence=occurrence)


_PREDECESSOR_SHAPES = {
    # name: (predecessor builder, the service's own answer)
    "good": (lambda obs: obs["pred_prov"], None),
    "not-a-receipt": (lambda obs: object(), RefusalCode.PRIOR_UNVERIFIED),
    "foreign-selection": (
        lambda obs: _with_predecessor_key(obs, selection=obs["sel_pre"]),
        RefusalCode.PRIOR_FOREIGN,
    ),
    "other-window": (
        lambda obs: _with_predecessor_key(obs, window_id="win-2"),
        RefusalCode.PRIOR_FOREIGN,
    ),
    "other-writer": (
        lambda obs: _with_predecessor_key(obs, writer="other-writer"),
        RefusalCode.PRIOR_FOREIGN,
    ),
    "not-earlier": (
        lambda obs: _with_predecessor_key(obs, sequence=obs["req_id"].sequence),
        RefusalCode.PRIOR_UNVERIFIED,
    ),
    "same-request": (
        lambda obs: _with_predecessor_key(obs, request_id=obs["req_id"].request_id),
        RefusalCode.PRIOR_UNVERIFIED,
    ),
    "incomplete": (
        lambda obs: replace(obs["pred_prov"], state="incomplete"),
        RefusalCode.PRIOR_UNVERIFIED,
    ),
    "failed-outcome": (
        lambda obs: _with_predecessor_publication(obs, outcome="app-failure"),
        RefusalCode.PRIOR_UNVERIFIED,
    ),
    "cleanup-pending": (
        lambda obs: _with_predecessor_publication(obs, cleanup_state="incomplete"),
        RefusalCode.PRIOR_UNVERIFIED,
    ),
    "occurrence-failed": (
        lambda obs: _with_predecessor_occurrence(obs, state="failed"),
        RefusalCode.PRIOR_UNVERIFIED,
    ),
    "occurrence-of-another-key": (
        lambda obs: _with_predecessor_occurrence(obs, key=obs["req_id"]),
        RefusalCode.PRIOR_UNVERIFIED,
    ),
}


@pytest.mark.parametrize("shape", sorted(_PREDECESSOR_SHAPES))
def test_service_checks_the_named_predecessor_of_a_non_continuation_row(
    shape: str,
) -> None:
    """Bite of each of the service's own predecessor checks, on a row with no
    continuation rule (so ``REQUIRED_PREDECESSOR_ROW`` cannot answer instead)."""
    _, obs, _ = _d1_d5_window()
    build, expected = _PREDECESSOR_SHAPES[shape]
    key = replace(obs["req_id"], row="D-1")
    revision = key.selection.selection_revision
    code = service_module._caller_predecessor_refusal_code(key, build(obs), revision)
    assert code is expected


def test_tainted_window_refuses_the_count() -> None:
    rig, obs, request = _d5_ready_to_count()
    rig.host_provenance.taint_window(rig.running_job.selection_revision, "win-1")
    result = _count(rig, obs, request, obs["raw_pub"], obs["prov"])
    assert _refusal_code(result) is RefusalCode.WINDOW_INELIGIBLE


# -- the counted row's own receipt (P2) ---------------------------------------


def test_counted_row_the_port_never_linked_is_refused() -> None:
    rig, obs, request = _d5_ready_to_count(link_counted=False)
    result = _count(rig, obs, request, obs["raw_pub"], obs["prov"])
    assert _refusal_code(result) is RefusalCode.RESULT_UNVERIFIED


def test_counted_receipt_that_differs_from_the_linked_one_is_refused() -> None:
    rig, obs, request = _d5_ready_to_count()
    altered = replace(obs["prov"], producer_instance=obs["checker_inst"])
    result = _count(rig, obs, request, obs["raw_pub"], altered)
    assert _refusal_code(result) is RefusalCode.RESULT_UNVERIFIED


def test_a_caller_built_verified_binding_is_never_a_receipt() -> None:
    rig, obs, request = _d5_ready_to_count()
    caller_built = obs["caller_built_binding"]
    assert caller_built.disposition == "verified"
    counted = _count(rig, obs, request, obs["raw_pub"], caller_built)
    assert _refusal_code(counted) is RefusalCode.RESULT_UNVERIFIED
    received = rig.composition.host_join.receive(
        rig.session_host,
        obs["req_id"],
        caller_built,
        replace(
            rig.examples["HostEffect"],
            selection=obs["sel_run"],
            boundary="C_PRE_EXECUTION",
            operation="launch",
        ),
    )
    assert isinstance(received, Refusal), received


class _LookalikeBindingPort(EchoingHostProvenance):
    """Answers with a subclass of VerifiedReceiptBinding (not the exact class)."""

    def verify_linked_receipt(self, key: Any, provenance: Any, boundary: Any) -> Any:
        answer = super().verify_linked_receipt(key, provenance, boundary)
        binding = answer.data
        record = type(binding)
        lookalike = type("LookalikeBinding", (record,), {"__slots__": ()})
        return replace(
            answer,
            data=lookalike(
                **{name: getattr(binding, name) for name in record.__dataclass_fields__}
            ),
        )


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("none", "ACCEPTED"),
        ("not-verified", RefusalCode.RESULT_UNVERIFIED),
        ("other-selection", RefusalCode.RESULT_UNVERIFIED),
        ("other-key", RefusalCode.RESULT_UNVERIFIED),
        ("receiving-without-witness", RefusalCode.RESULT_UNVERIFIED),
        ("other-publication", RefusalCode.RESULT_UNVERIFIED),
        ("other-provenance", RefusalCode.RESULT_UNVERIFIED),
        ("other-occurrence", RefusalCode.RESULT_UNVERIFIED),
        ("predecessor-dropped", RefusalCode.PRIOR_UNVERIFIED),
        ("lookalike-class", RefusalCode.RESULT_UNVERIFIED),
    ],
)
def test_port_binding_must_be_for_exactly_the_counted_receipt(
    change: str, expected: RefusalCode | str
) -> None:
    """Bite of the service's check on the port's answer (ruling C4)."""
    probe_rig, probe_obs, _ = _d1_d5_window()
    changes: dict[str, Any] = {
        "none": {},
        "not-verified": {"disposition": "unverified"},
        "other-selection": {"selection": probe_obs["sel_pre"]},
        "other-key": {"operation_key": probe_obs["pred_key"]},
        "receiving-without-witness": {"receiving": FakeWitness("")},
        "other-publication": {"publication": probe_obs["pred_pub"]},
        "other-provenance": {
            "provenance": replace(probe_obs["prov"], occurrence_witness=WITNESS_2)
        },
        "other-occurrence": {"occurrence": probe_obs["pred_occ_handle"]},
        "predecessor-dropped": {"predecessor": None},
        "lookalike-class": {},
    }[change]
    port = (
        _LookalikeBindingPort()
        if change == "lookalike-class"
        else EchoingHostProvenance(**changes)
    )
    rig, obs, request = _d5_ready_to_count(host_provenance=port)
    assert _refusal_code(_count(rig, obs, request, obs["raw_pub"], obs["prov"])) == expected


# -- verify_publication (the join's link step) --------------------------------


class _SkewedBindPort(PortOnlyHostProvenance):
    """Links like the double, then answers with ``skew`` applied to its receipt."""

    def __init__(self) -> None:
        super().__init__()
        self.skew: Any = lambda receipt: receipt

    def bind_publication(
        self, session: Any, occurrence: Any, publication: Any, witness: Any
    ) -> Any:
        answer = super().bind_publication(session, occurrence, publication, witness)
        if isinstance(answer, AcceptedData):
            return replace(answer, data=self.skew(answer.data))
        return answer


@pytest.mark.parametrize(
    ("skew", "expected"),
    [
        ("none", "ACCEPTED"),
        ("lookalike-class", RefusalCode.RESULT_UNVERIFIED),
        ("other-key", RefusalCode.RESULT_UNVERIFIED),
        ("other-publication", RefusalCode.RESULT_UNVERIFIED),
    ],
)
def test_verify_publication_answers_only_the_receipt_for_this_publication(
    skew: str, expected: RefusalCode | str
) -> None:
    port = _SkewedBindPort()
    rig, obs, _ = _d5_ready_to_count(host_provenance=port)
    port.skew = {
        "none": lambda receipt: receipt,
        "lookalike-class": lambda receipt: _lookalike_class({"pred_prov": receipt}, rig),
        "other-key": lambda receipt: replace(receipt, operation_key=obs["pred_key"]),
        "other-publication": lambda receipt: replace(
            receipt, raw_publication=obs["pred_pub"]
        ),
    }[skew]
    result = rig.composition.host_join.verify_publication(
        rig.session_host, obs["req_id"], obs["raw_pub"], WITNESS_1
    )
    assert _refusal_code(result) == expected


# -- receive (the join's linked-receipt read) ---------------------------------


def _effect(rig: PopulatedAuthorityTestRig, obs: dict[str, Any], boundary: str) -> Any:
    return replace(
        rig.examples["HostEffect"],
        selection=obs["sel_run"],
        boundary=boundary,
        operation="launch",
    )


def test_receive_answers_only_linked_receipts_at_linked_boundaries() -> None:
    rig, obs, _ = _d5_ready_to_count()
    join = rig.composition.host_join
    ok = join.receive(
        rig.session_host, obs["req_id"], obs["prov"], _effect(rig, obs, "C_BEFORE_COUNT")
    )
    assert isinstance(ok, AcceptedData), ok
    assert ok.data.predecessor == obs["pred_prov"]

    outside = join.receive(
        rig.session_host, obs["req_id"], obs["prov"], _effect(rig, obs, "B_PRE_REQUEST")
    )
    assert _refusal_code(outside) is RefusalCode.SCOPE_MISMATCH

    no_predecessor = join.receive(
        rig.session_host,
        obs["req_id"],
        replace(obs["prov"], predecessor=None),
        _effect(rig, obs, "C_PRE_EXECUTION"),
    )
    assert _refusal_code(no_predecessor) is RefusalCode.PRIOR_MISSING

    planted = join.receive(
        rig.session_host,
        obs["req_id"],
        replace(obs["prov"], predecessor=_planted(obs, rig)),
        _effect(rig, obs, "C_PRE_EXECUTION"),
    )
    assert _refusal_code(planted) is RefusalCode.PRIOR_UNVERIFIED


def test_receive_refuses_what_the_service_itself_checks_when_the_port_echoes() -> None:
    """Bites of receive's own checks: boundary, predecessor and the port's binding."""
    rig, obs, _ = _d5_ready_to_count(host_provenance=EchoingHostProvenance())
    join = rig.composition.host_join
    ok = join.receive(
        rig.session_host, obs["req_id"], obs["prov"], _effect(rig, obs, "C_BEFORE_COUNT")
    )
    assert isinstance(ok, AcceptedData), ok
    outside = join.receive(
        rig.session_host, obs["req_id"], obs["prov"], _effect(rig, obs, "B_PRE_REQUEST")
    )
    assert _refusal_code(outside) is RefusalCode.SCOPE_MISMATCH
    no_predecessor = join.receive(
        rig.session_host,
        obs["req_id"],
        replace(obs["prov"], predecessor=None),
        _effect(rig, obs, "C_BEFORE_COUNT"),
    )
    assert _refusal_code(no_predecessor) is RefusalCode.PRIOR_MISSING

    rig, obs, _ = _d5_ready_to_count(
        host_provenance=EchoingHostProvenance(disposition="unverified")
    )
    unverified = rig.composition.host_join.receive(
        rig.session_host, obs["req_id"], obs["prov"], _effect(rig, obs, "C_BEFORE_COUNT")
    )
    assert _refusal_code(unverified) is RefusalCode.RESULT_UNVERIFIED


def test_receive_of_a_row_the_port_never_linked_is_refused() -> None:
    rig, obs, _ = _d5_ready_to_count(link_counted=False)
    result = rig.composition.host_join.receive(
        rig.session_host, obs["req_id"], obs["prov"], _effect(rig, obs, "C_PRE_EXECUTION")
    )
    assert _refusal_code(result) is RefusalCode.RESULT_UNVERIFIED


def test_double_never_verifies_a_lifecycle_key() -> None:
    """Lifecycle keys have no window chain, so no linked receipt (not PRIOR_MISSING)."""
    rig, obs, _ = _d5_ready_to_count(host_provenance=InMemoryHostProvenance())
    lifecycle_key = rig.examples["LifecycleKey"]
    provenance = replace(obs["prov"], operation_key=lifecycle_key)
    result = rig.host_provenance.verify_linked_receipt(
        lifecycle_key, provenance, "C_BEFORE_COUNT"
    )
    assert _refusal_code(result) is RefusalCode.RESULT_UNVERIFIED


# -- composition: members, not classes (P3, #477) -----------------------------


class _WithoutMember:
    """Wraps an adapter and hides one of its members."""

    def __init__(self, adapter: object, hidden: str) -> None:
        for name in dir(type(adapter)):
            if not name.startswith("_") and name != hidden:
                setattr(self, name, getattr(adapter, name))


@pytest.mark.parametrize(
    ("role", "hidden"),
    [
        ("host_provenance", "verify_linked_receipt"),
        ("host_provenance", "bind_publication"),
        ("host_observer", "finish_witness"),
        ("host_observer", "lookup_observation"),
    ],
)
def test_composition_refuses_a_host_adapter_missing_a_port_member(
    role: str, hidden: str
) -> None:
    adapter = PortOnlyHostProvenance() if role == "host_provenance" else PortOnlyHostObserver()
    port = HostProvenance if role == "host_provenance" else HostObserver
    with pytest.raises(TypeError, match=rf"{role} lacks {port.__name__} members: {hidden}$"):
        compose_p3_authority(**{role: _WithoutMember(adapter, hidden)})
    compose_p3_authority(**{role: _WithoutMember(adapter, "register_evidence")})


def test_require_port_members_needs_a_port() -> None:
    with pytest.raises(TypeError, match="not a port with abstract members"):
        require_port_members(PortOnlyHostProvenance(), object, role="host_provenance")


# -- the conformance kit: the double, a port-only adapter and a wrong one ------


def _templates() -> ConformanceTemplates:
    rig = make_populated_test_rig()
    obs = populate_boundary_happy_path_observations(rig)
    return ConformanceTemplates(
        session=rig.session_host,
        receipt=obs["pred_prov"],
        evidence=rig.evidence_by_revision[rig.running_job.selection_revision],
        other_witness=WITNESS_2,
        foreign_selection=obs["sel_pre"],
    )


def _adapter(make: Any) -> Any:
    def factory() -> AdapterUnderTest:
        adapter = make()
        return AdapterUnderTest(port=adapter, feed=adapter)

    return factory


def test_conformance_kit_passes_the_double_and_a_port_only_adapter() -> None:
    templates = _templates()
    for make in (InMemoryHostProvenance, PortOnlyHostProvenance):
        outcomes = run_conformance(_adapter(make), templates)
        assert failed_outcomes(outcomes) == (), make.__name__
        assert len({outcome.name for outcome in outcomes}) == len(outcomes)


class _IgnoresTaint(PortOnlyHostProvenance):
    def taint_window(self, selection_revision: str, window_id: str) -> None:
        return None


def test_conformance_kit_fails_adapters_that_trust_the_caller_or_ignore_taint() -> None:
    templates = _templates()
    echoing = {
        outcome.name
        for outcome in failed_outcomes(
            run_conformance(_adapter(EchoingHostProvenance), templates)
        )
    }
    assert {
        "published-never-linked",
        "caller-names-predecessor-none-linked",
        "caller-predecessor-tampered",
        "caller-receipt-tampered",
        "window-tainted-after-link",
        "receipt-bytes-differ",
    } <= echoing, echoing
    ignoring = {
        outcome.name
        for outcome in failed_outcomes(run_conformance(_adapter(_IgnoresTaint), templates))
    }
    assert ignoring == {"window-tainted-after-link", "window-tainted-before-link"}


# -- source fitness of service.py (ruling: P3, P-2) ---------------------------


_PROVIDER_CLASS_NAMES = frozenset(
    name for name in dir(providers_module) if name.startswith("InMemory")
)
_JOIN_READS_WITHOUT_LOOKUPS = ("before_count", "receive", "verify_publication")


def _fitness_findings(source: str) -> list[str]:
    """Each place where service source breaks the ruling's fitness rules."""
    findings = []
    if "VerifiedReceiptBinding(" in source:
        findings.append("constructs VerifiedReceiptBinding")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("isinstance", "issubclass")
            and len(node.args) == 2
        ):
            names = {n.id for n in ast.walk(node.args[1]) if isinstance(n, ast.Name)}
            names |= {n.attr for n in ast.walk(node.args[1]) if isinstance(n, ast.Attribute)}
            for name in sorted(names & _PROVIDER_CLASS_NAMES):
                findings.append(f"line {node.lineno}: {node.func.id} against {name}")
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in _JOIN_READS_WITHOUT_LOOKUPS
        ):
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in ("lookup_occurrence_handle", "lookup_witness")
                ):
                    findings.append(f"{node.name} calls {call.func.attr}")
    return findings


def test_service_source_has_no_provider_class_gate_and_no_built_receipt() -> None:
    assert _fitness_findings(inspect.getsource(service_module)) == []


def test_fitness_check_flags_each_planted_breach() -> None:
    planted = '''
class S:
    def before_count(self, key):
        if isinstance(self._host_provenance, InMemoryHostProvenance):
            return VerifiedReceiptBinding(selection=key)
        return self._host_provenance.lookup_witness(key)

    def receive(self, key):
        if not isinstance(self._host_observer, (_p.InMemoryHostObserver, int)):
            return self._host_provenance.lookup_occurrence_handle(key)
'''
    assert sorted(_fitness_findings(planted)) == sorted(
        [
            "constructs VerifiedReceiptBinding",
            "line 4: isinstance against InMemoryHostProvenance",
            "before_count calls lookup_witness",
            "line 9: isinstance against InMemoryHostObserver",
            "receive calls lookup_occurrence_handle",
        ]
    )
