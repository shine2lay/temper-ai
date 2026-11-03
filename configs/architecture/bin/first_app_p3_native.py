"""Disabled native-boundary consumer and result join for Project 3 (#125 / T4).

Consumes the canonical supplier exports delivered by:
- Systems #71 (`p3_source_closure` and `configs/architecture/bin/ops_host_source_comparison.py`):
  `LoadedClosureEnvelope`, `N3Coverage`, `N3Gap`, `N3ObservationEpoch`, `N3SourceEpoch`,
  `NativeClosureExpectation`, `ReviewedSourceGraph`, `SourceClosureComparison`,
  `VerifiedClosureOrigins`, `compare_loaded_source`, `validate_loaded_envelope`,
  `validate_reviewed_graph`.
- Ops #751 (`p3_host_contracts`):
  `RawRef`, `ProjectSelection`, `CalibrationSelection`, `CallerSelection`,
  `SelectedHostJob`, `ProcessInstance`, `RootScope`, `RootBinding`,
  `ObservationScope`, `HostObservation`, `HostCoverage`, `HostEffect`,
  `EffectLease`, `LifecycleKey`, `RowKey`, `OperationKey`, `OccurrenceHandle`,
  `RawPublication`, `ReceiptProvenance`, `HostClosureJoin`.
- Temper #261 (`temper_ai.p3_authority.contract`):
  `DECISION_SCHEMA`, `AcceptedData`, `Refusal`, `RefusalCode`, `Result`, `Phase`,
  `RetryKind`, `AdmissionState`, `EffectState`, `SequenceUse`, `P3AuthorityRegistry`,
  `P3NativeBoundary`, `NativeHostJoin`, `WorkerObserver`, `RootObserver`,
  `CreateArmDecision`, `CheckerDecision`, `RequestDecision`, `AdmissionDecision`,
  `ExecutionDecision`, `CountDecision`, `VerifiedReceiptBinding`, `NativeReceive`,
  `WindowBinding`, `CheckerBinding`, `ImmutableRequestBinding`, `AdmittedRequestBinding`,
  `WorkerObservation`, `RootObservation`, `BothRootObservations`,
  `CurrentObservationCursors`, `ActualRequestAndReceipt`, `P5Assessment`, `QAReceiving`.
- Temper #262 (`temper_ai.p3_authority.service`, `registry`, `candidate_bindings`, `_providers`,
  and `temper_ai.runner.admission`):
  `DEFAULT_CANDIDATE_BINDINGS`, `P3AuthorityComposition`, `P3AuthorityService`,
  `NativeHostJoinAdapter`, `compose_p3_authority`, `AuthorityRegistryService`,
  `P3CandidateBindings`, `SystemsSourceClosureComparator`.
- Temper #263 (`temper_ai.p3_authority.worker_observation`, `child_registration`,
  `coverage_bookkeeping`, `launch_adapters`):
  `WorkerObservationAdapter`, `RootOwnerVsActorAssertion`, `ChildRegistrationTable`,
  `CoverageBookkeeper`, `DockerLaunchObservationAdapter`, `EarlyBootstrapObservationHook`,
  `RunnerBootstrapObservationHook`, `WORKER_OBSERVATION_COMPAT_CORPUS_ID`,
  `EXISTING_TEMPER_SEAM_GUARANTEES`, `refuse_existing_seam_as_complete_coverage`,
  `build_worker_observation_compat_cases`, `validate_compatibility_profile`.

Posture invariants:
- `WRITES_ADMITTED` remains `False` (`first_app_p3_host.WRITES_ADMITTED is False`).
- `DEFAULT_CANDIDATE_BINDINGS`, `DEFAULT_NATIVE_BOUNDARY`, `DEFAULT_NATIVE_HOST_JOIN`,
  and `DEFAULT_WORKER_OBSERVER` remain `None`.
- All N1-N8 native obligations remain `UNRESOLVED`; R-1, R-1i, D-1, D-5 remain
  `UNQUALIFIED`; P5 remains `UNTRUSTED`.
- Guard-off calls short-circuit before inspecting caller inputs, clocks, sleeps,
  filesystems, or supplier services.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

_BIN_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BIN_DIR.parents[2]
for _entry in (str(_BIN_DIR), str(_REPO_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import first_app_p3_host as host_wire  # noqa: E402
import ops_host_source_comparison as ops_closure  # noqa: E402

import p3_host_contracts as host_contracts  # noqa: E402
import p3_source_closure as source_closure  # noqa: E402
from temper_ai.p3_authority import (  # noqa: E402
    _providers as authority_providers,
)
from temper_ai.p3_authority import (  # noqa: E402
    candidate_bindings as authority_candidate_bindings,
)
from temper_ai.p3_authority import (  # noqa: E402
    child_registration as authority_child_registration,
)
from temper_ai.p3_authority import (  # noqa: E402
    contract as authority_contract,
)
from temper_ai.p3_authority import (  # noqa: E402
    coverage_bookkeeping as authority_coverage_bookkeeping,
)
from temper_ai.p3_authority import (  # noqa: E402
    launch_adapters as authority_launch_adapters,
)
from temper_ai.p3_authority import (  # noqa: E402
    registry as authority_registry,
)
from temper_ai.p3_authority.contract import (  # noqa: E402
    DECISION_SCHEMA,
    AcceptedData,
    ActualCreation,
    ActualRequestAndReceipt,
    AdmissionDecision,
    AdmissionState,
    AdmittedRequestBinding,
    AuthenticatedPeer,
    BothRootObservations,
    CheckerDecision,
    CompatibilityReceiving,
    CountDecision,
    CreateArmDecision,
    CurrentObservationCursors,
    EffectState,
    ExecutionDecision,
    HostCalibrationSelection,
    HostEffect,
    HostObservation,
    HostProjectSelection,
    LoadedClosureEnvelope,
    N3Coverage,
    N3Gap,
    N3ObservationEpoch,
    N3SourceEpoch,
    NativeClosureExpectation,
    NativeHostJoin,
    NativeProcessRef,
    NativeRootObject,
    NativeSession,
    NativeWitness,
    ObservationGrant,
    OccurrenceHandle,
    OperationLeg,
    P3NativeBoundary,
    P5Assessment,
    Phase,
    QAReceiving,
    RawPublication,
    RawRef,
    ReceiptProducerBinding,
    Refusal,
    RefusalCode,
    RequestDecision,
    RequestIdentity,
    Result,
    RetryKind,
    ReviewedSourceGraph,
    RootBinding,
    SelectedJob,
    SequenceUse,
    SourceClosureComparison,
    VerifiedClosureOrigins,
    VerifiedReceiptBinding,
    WindowBinding,
    WorkerObservation,
    compare_loaded_source,
    validate_loaded_envelope,
    validate_reviewed_graph,
)
from temper_ai.p3_authority.service import (  # noqa: E402
    NativeHostJoinAdapter,
    P3AuthorityComposition,
    P3AuthorityService,
    compose_p3_authority,
)
from temper_ai.p3_authority.worker_observation import (  # noqa: E402
    EXISTING_TEMPER_SEAM_GUARANTEES,
    WORKER_OBSERVATION_COMPAT_CORPUS_ID,
    RootOwnerVsActorAssertion,
    WorkerObservationAdapter,
    build_worker_observation_compat_cases,
    refuse_existing_seam_as_complete_coverage,
    validate_compatibility_profile,
)
from temper_ai.runner import admission as runner_admission  # noqa: E402
from temper_ai.runner.admission import (  # noqa: E402
    CandidateBindings,
    is_designated,
)

WRITES_ADMITTED: Final[bool] = False
DEFAULT_CANDIDATE_BINDINGS: Final[CandidateBindings | None] = None
DEFAULT_NATIVE_BOUNDARY: Final[None] = None
DEFAULT_NATIVE_HOST_JOIN: Final[None] = None
DEFAULT_WORKER_OBSERVER: Final[None] = None

CANONICAL_N1_TO_N8_CODES: Final[tuple[str, ...]] = (
    "N1",
    "N2",
    "N3",
    "N4",
    "N5",
    "N6",
    "N7",
    "N8",
)

CANONICAL_NATIVE_OBLIGATION_DESCRIPTIONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "N1": "Authority: transaction-bound caller, binding, worker, and bootstrap authority verification",
        "N2": "Process roots: BothRootObservations (publication and host_evidence) and ProcessInstance lineage",
        "N3": "Source closure: NativeClosureExpectation, VerifiedClosureOrigins, and SourceClosureComparison",
        "N4": "Host effects: RequestDecision, AdmissionDecision, AdmittedRequestBinding, and ExecutionDecision fence",
        "N5": "Publication: RawPublication, ReceiptProvenance, and VerifiedReceiptBinding (NativeReceive) custody",
        "N6": "Provenance and cursors: CurrentObservationCursors, QAReceiving, and CompatibilityReceiving gate",
        "N7": "Worker runtime observation: WorkerObservation, ChildRegistrationTable, and CoverageBookkeeper",
        "N8": "Candidate selection: SelectedJob, WindowBinding, and CheckerBinding immutability",
    }
)

UNRESOLVED_NATIVE_OBLIGATIONS: Final[Mapping[str, str]] = MappingProxyType(
    {code: "UNRESOLVED" for code in CANONICAL_N1_TO_N8_CODES}
)

SUPPLIER_ARTIFACTS: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        "systems_71": MappingProxyType(
            {
                "commit": "bfef9a61727819673fcb5df2a4f179d4c184f435",
                "package": "p3_source_closure",
                "reexport": "configs/architecture/bin/ops_host_source_comparison.py",
            }
        ),
        "ops_751": MappingProxyType(
            {
                "commit": "e30562b1244020638f671964272c47abb0a83c60",
                "package": "p3_host_contracts",
            }
        ),
        "temper_261": MappingProxyType(
            {
                "commit": "6363983af8dc9013e5326c59df76a900ee0c2f47",
                "module": "temper_ai.p3_authority.contract",
                "handoff": "/home/shinelay/company-lab/temper/p3-authority-contract/HANDOFF.md",
            }
        ),
        "temper_262": MappingProxyType(
            {
                "commit": "172fd7fe3f45fc7816df4947e0c5db0b07abf7b2",
                "module": "temper_ai.p3_authority.service",
                "handoff": "/home/shinelay/company-lab/temper/p3-authority-composition/HANDOFF.md",
            }
        ),
        "temper_263": MappingProxyType(
            {
                "commit": "4310ca7f090780c805ad3276ab1716586a512c01",
                "module": "temper_ai.p3_authority.worker_observation",
                "handoff": "/home/shinelay/company-lab/temper/p3-worker-observation/HANDOFF.md",
                "corpus_registration": "/home/shinelay/company-lab/temper/p3-worker-observation/CORPUS-REGISTRATION.md",
                "corpus_registration_sha256": "1407ca93454b73867497a95efb6a29961e8c9474c007f2758bc4a7672904a6fd",
                "ops_760_corpus_commit": "57a1988bba9b3bef65fa161fd188fae292300b92",
            }
        ),
    }
)


@dataclass(frozen=True)
class NativeBoundaryStatus:
    """Immutable snapshot of the disabled T4 native boundary posture."""

    writes_admitted: bool
    default_candidate_bindings_active: bool
    default_native_boundary_active: bool
    default_native_host_join_active: bool
    default_worker_observer_active: bool
    supplier_contract_bound: bool
    supplier_service_bound: bool
    supplier_worker_observation_bound: bool
    supplier_closure_bound: bool
    worker_compat_corpus_id: str
    native_obligations: Mapping[str, str]
    r1_status: str
    r1i_status: str
    d1_status: str
    d5_status: str
    p5_trust_posture: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "writes_admitted": self.writes_admitted,
            "default_candidate_bindings_active": self.default_candidate_bindings_active,
            "default_native_boundary_active": self.default_native_boundary_active,
            "default_native_host_join_active": self.default_native_host_join_active,
            "default_worker_observer_active": self.default_worker_observer_active,
            "supplier_contract_bound": self.supplier_contract_bound,
            "supplier_service_bound": self.supplier_service_bound,
            "supplier_worker_observation_bound": self.supplier_worker_observation_bound,
            "supplier_closure_bound": self.supplier_closure_bound,
            "worker_compat_corpus_id": self.worker_compat_corpus_id,
            "native_obligations": dict(self.native_obligations),
            "r1_status": self.r1_status,
            "r1i_status": self.r1i_status,
            "d1_status": self.d1_status,
            "d5_status": self.d5_status,
            "p5_trust_posture": self.p5_trust_posture,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class NativeJoinedHostEvaluation:
    """Result of joining supplier authority, closure, and worker-observation outcomes for a host row."""

    row: str
    status: str
    writes_admitted: bool
    default_candidate_bindings_active: bool
    boundary_mode: str
    authority_accepted: bool
    closure_accepted: bool
    worker_observation_accepted: bool
    roots_observation_accepted: bool
    native_receive_accepted: bool
    count_eligible: bool
    inner_count_decision: CountDecision | None
    refusals: tuple[Refusal, ...]
    refusal_codes: tuple[str, ...]
    refusal_phases: tuple[str, ...]
    closure_disposition: str | None
    closure_reasons: tuple[str, ...]
    reasons: tuple[str, ...]
    native_obligations: Mapping[str, str]
    r1_status: str
    r1i_status: str
    d1_status: str
    d5_status: str
    p5_trust_posture: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "status": self.status,
            "writes_admitted": self.writes_admitted,
            "default_candidate_bindings_active": self.default_candidate_bindings_active,
            "boundary_mode": self.boundary_mode,
            "authority_accepted": self.authority_accepted,
            "closure_accepted": self.closure_accepted,
            "worker_observation_accepted": self.worker_observation_accepted,
            "roots_observation_accepted": self.roots_observation_accepted,
            "native_receive_accepted": self.native_receive_accepted,
            "count_eligible": self.count_eligible,
            "inner_count_decision": (
                None
                if self.inner_count_decision is None
                else {
                    "verdict": self.inner_count_decision.verdict,
                    "idempotency_identity": self.inner_count_decision.idempotency_identity,
                }
            ),
            "refusal_codes": list(self.refusal_codes),
            "refusal_phases": list(self.refusal_phases),
            "closure_disposition": self.closure_disposition,
            "closure_reasons": list(self.closure_reasons),
            "reasons": list(self.reasons),
            "native_obligations": dict(self.native_obligations),
            "r1_status": self.r1_status,
            "r1i_status": self.r1i_status,
            "d1_status": self.d1_status,
            "d5_status": self.d5_status,
            "p5_trust_posture": self.p5_trust_posture,
        }


def verify_canonical_supplier_bindings() -> dict[str, bool]:
    """Fail-loud verification that all supplier exports resolve to exact canonical types without stubs."""
    if host_wire.WRITES_ADMITTED is not False or WRITES_ADMITTED is not False:
        raise RuntimeError("WRITES_ADMITTED must remain False in disabled T4 posture")
    if (
        getattr(runner_admission, "DEFAULT_CANDIDATE_BINDINGS", None) is not None
        or DEFAULT_CANDIDATE_BINDINGS is not None
        or is_designated("designated_v1", DEFAULT_CANDIDATE_BINDINGS) is not False
    ):
        raise RuntimeError("DEFAULT_CANDIDATE_BINDINGS must remain None in disabled T4 posture")
    if host_wire.DEFAULT_CANDIDATE_BINDINGS is not None:
        raise RuntimeError("first_app_p3_host.DEFAULT_CANDIDATE_BINDINGS must remain None")

    host_contract_identity = (
        RawRef is host_contracts.RawRef
        and HostProjectSelection is host_contracts.ProjectSelection
        and HostCalibrationSelection is host_contracts.CalibrationSelection
    )
    if not host_contract_identity:
        raise TypeError("temper_ai.p3_authority.contract host records diverged from p3_host_contracts")

    closure_identity = (
        NativeClosureExpectation is source_closure.NativeClosureExpectation
        and NativeClosureExpectation is ops_closure.NativeClosureExpectation
        and VerifiedClosureOrigins is source_closure.VerifiedClosureOrigins
        and VerifiedClosureOrigins is ops_closure.VerifiedClosureOrigins
        and LoadedClosureEnvelope is source_closure.LoadedClosureEnvelope
        and LoadedClosureEnvelope is ops_closure.LoadedClosureEnvelope
        and ReviewedSourceGraph is source_closure.ReviewedSourceGraph
        and ReviewedSourceGraph is ops_closure.ReviewedSourceGraph
        and SourceClosureComparison is source_closure.SourceClosureComparison
        and SourceClosureComparison is ops_closure.SourceClosureComparison
        and N3Coverage is source_closure.N3Coverage
        and N3Gap is source_closure.N3Gap
        and N3ObservationEpoch is source_closure.N3ObservationEpoch
        and N3SourceEpoch is source_closure.N3SourceEpoch
        and compare_loaded_source is source_closure.compare_loaded_source
        and ops_closure.compare_loaded_source is source_closure.compare_loaded_source
        and validate_loaded_envelope is source_closure.validate_loaded_envelope
        and validate_reviewed_graph is source_closure.validate_reviewed_graph
    )
    if not closure_identity:
        raise TypeError("p3_source_closure / ops_host_source_comparison / contract closure types diverged")

    service_identity = (
        callable(P3AuthorityService)
        and callable(NativeHostJoinAdapter)
        and callable(compose_p3_authority)
        and callable(authority_registry.AuthorityRegistryService)
        and callable(authority_providers.SystemsSourceClosureComparator)
        and callable(authority_candidate_bindings.P3CandidateBindings)
    )
    if not service_identity:
        raise TypeError("temper_ai.p3_authority.service composition exports unavailable")

    worker_identity = (
        callable(WorkerObservationAdapter)
        and callable(authority_child_registration.ChildRegistrationRegistry)
        and callable(authority_coverage_bookkeeping.CoverageBookkeeper)
        and callable(authority_launch_adapters.DockerLaunchObservationAdapter)
        and callable(authority_launch_adapters.EarlyBootstrapObservationHook)
        and callable(authority_launch_adapters.RunnerBootstrapObservationHook)
    )
    if not worker_identity:
        raise TypeError("temper_ai.p3_authority.worker_observation exports unavailable")

    compat_cases = build_worker_observation_compat_cases()
    if len(compat_cases) != 12:
        raise ValueError(f"Expected 12 worker observation compatibility cases, got {len(compat_cases)}")
    valid_profile = authority_contract.CompatibilityProfile(
        decision=DECISION_SCHEMA,
        reviewed_graph="p3-reviewed-source-graph/1",
        loaded_envelope="p3-reviewed-loaded-closure/1",
        comparator="p3-source-closure/1",
        observation="p3-worker-observation/1",
        caller="p3-caller/1",
        receiving="p3-qa-receiving/1",
        inspect="/1",
        corpus=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
    )
    compat_err = validate_compatibility_profile(valid_profile, "B_PRE_REQUEST")
    if compat_err is not None:
        raise ValueError(f"worker observation compatibility profile invalid: {compat_err!r}")

    seam_refusal = refuse_existing_seam_as_complete_coverage(
        "box_profile.closure",
        boundary="B_PRE_REQUEST",
    )
    if not isinstance(seam_refusal, Refusal) or seam_refusal.code is not RefusalCode.CLOSURE_INCOMPLETE:
        raise ValueError("refuse_existing_seam_as_complete_coverage must refuse with CLOSURE_INCOMPLETE")

    return {
        "host_contract_identity": host_contract_identity,
        "closure_identity": closure_identity,
        "service_identity": service_identity,
        "worker_identity": worker_identity,
        "worker_compat_profile_valid": True,
    }


def inspect_disabled_native_boundary() -> NativeBoundaryStatus:
    """Return the deterministic disabled native boundary posture without side effects."""
    checks = verify_canonical_supplier_bindings()
    return NativeBoundaryStatus(
        writes_admitted=host_wire.WRITES_ADMITTED,
        default_candidate_bindings_active=DEFAULT_CANDIDATE_BINDINGS is not None,
        default_native_boundary_active=DEFAULT_NATIVE_BOUNDARY is not None,
        default_native_host_join_active=DEFAULT_NATIVE_HOST_JOIN is not None,
        default_worker_observer_active=DEFAULT_WORKER_OBSERVER is not None,
        supplier_contract_bound=checks["host_contract_identity"],
        supplier_service_bound=checks["service_identity"],
        supplier_worker_observation_bound=checks["worker_identity"],
        supplier_closure_bound=checks["closure_identity"],
        worker_compat_corpus_id=WORKER_OBSERVATION_COMPAT_CORPUS_ID,
        native_obligations=UNRESOLVED_NATIVE_OBLIGATIONS,
        r1_status="UNQUALIFIED",
        r1i_status="UNQUALIFIED",
        d1_status="UNQUALIFIED",
        d5_status="UNQUALIFIED",
        p5_trust_posture="UNTRUSTED",
        reasons=(
            host_wire.WRITES_OFF,
            "DEFAULT_CANDIDATE_BINDINGS is None; no live native authority, closure, or worker observer is installed",
            "N1-N8 native obligations remain UNRESOLVED; R-1, R-1i, D-1, D-5 remain UNQUALIFIED; P5 remains UNTRUSTED",
        ),
    )


def compose_disabled_consumer_service(**kwargs: Any) -> P3AuthorityComposition:
    """Compose a disabled P3AuthorityComposition (`writes_enabled=False`) over canonical #262 providers.

    Fails loud if a caller attempts to pass `writes_enabled=True`.
    """
    if kwargs.get("writes_enabled") is True:
        raise ValueError("T4 disabled native consumer forbids writes_enabled=True")
    kwargs["writes_enabled"] = False
    return compose_p3_authority(**kwargs)


async def join_native_host_row(
    host: Any,
    row: Any,
    *,
    native_boundary: P3NativeBoundary | None = None,
    clock: Any = host_wire.utc_now,
    sleep: Any = asyncio.sleep,
) -> dict[str, Any]:
    """Guard-first consumer entry: refuses immediately while WRITES_ADMITTED is False without touching inputs."""
    if not host_wire.WRITES_ADMITTED:
        return {
            "status": "BLOCKED",
            "reasons": [host_wire.WRITES_OFF],
            "writer": host_wire.WRITER,
            "count_eligible": False,
            "native_obligations": dict(UNRESOLVED_NATIVE_OBLIGATIONS),
        }
    return await join_admitted_host_row(
        host,
        row,
        native_boundary=native_boundary,
        clock=clock,
        sleep=sleep,
    )


async def join_admitted_host_row(
    host: Any,
    row: Any,
    *,
    native_boundary: P3NativeBoundary | None = None,
    clock: Any = host_wire.utc_now,
    sleep: Any = asyncio.sleep,
) -> dict[str, Any]:
    """Fail-closed backup even if called directly: refuses when writes are off or native boundary is absent."""
    if not host_wire.WRITES_ADMITTED:
        return {
            "status": "BLOCKED",
            "reasons": [host_wire.WRITES_OFF],
            "writer": host_wire.WRITER,
            "count_eligible": False,
            "native_obligations": dict(UNRESOLVED_NATIVE_OBLIGATIONS),
        }
    if not isinstance(row, str) or row not in host_wire.HOST_ROWS:
        return {
            "status": "BLOCKED",
            "reasons": [f"{row!r} is not a checker host row"],
            "writer": host_wire.WRITER,
            "count_eligible": False,
            "native_obligations": dict(UNRESOLVED_NATIVE_OBLIGATIONS),
        }
    if native_boundary is None:
        return {
            "status": "BLOCKED",
            "reasons": ["native boundary provider is not installed (DEFAULT_NATIVE_BOUNDARY is None)"],
            "writer": host_wire.WRITER,
            "count_eligible": False,
            "native_obligations": dict(UNRESOLVED_NATIVE_OBLIGATIONS),
        }
    wire = await host_wire.run_row(host, row, clock=clock, sleep=sleep)
    out = dict(wire)
    out["count_eligible"] = False
    out["native_obligations"] = dict(UNRESOLVED_NATIVE_OBLIGATIONS)
    if out.get("status") == "PASS":
        out["status"] = "UNQUALIFIED"
    return out


def _validate_boundary_result(
    result: Any,
    expected_data_type: type[Any],
    stage_name: str,
) -> tuple[Any | None, Refusal | None]:
    """Validate that a supplier Result[T] is either AcceptedData[expected_data_type] or Refusal."""
    if isinstance(result, Refusal):
        if result.schema != DECISION_SCHEMA or result.counted is not False:
            raise ValueError(f"{stage_name}: invalid Refusal schema/counted posture")
        return None, result
    if isinstance(result, AcceptedData):
        data = result.data
        if not isinstance(data, expected_data_type):
            raise TypeError(
                f"{stage_name}: expected AcceptedData[{expected_data_type.__name__}], "
                f"got AcceptedData[{type(data).__name__}]"
            )
        if getattr(result.evidence, "schema", None) != DECISION_SCHEMA:
            raise ValueError(f"{stage_name}: AcceptedData.evidence.schema must be {DECISION_SCHEMA!r}")
        return data, None
    raise TypeError(
        f"{stage_name}: expected Result[{expected_data_type.__name__}] (AcceptedData | Refusal), "
        f"got {type(result).__name__}"
    )


def join_offline_supplier_results(
    *,
    row: str,
    create_result: Result[CreateArmDecision],
    checker_result: Result[CheckerDecision],
    request_result: Result[RequestDecision],
    admit_result: Result[AdmissionDecision],
    execute_result: Result[ExecutionDecision],
    closure_comparison: SourceClosureComparison,
    worker_observation_result: Result[WorkerObservation],
    roots_observation_result: Result[BothRootObservations],
    native_receive_result: Result[VerifiedReceiptBinding] | None = None,
    count_result: Result[CountDecision] | None = None,
) -> NativeJoinedHostEvaluation:
    """Join canonical #261/#262/#263/#71 supplier results in offline conformance evaluation.

    - Validates exact canonical types at every seam (`AcceptedData`, `Refusal`,
      `CreateArmDecision`, `CheckerDecision`, `RequestDecision`, `AdmissionDecision`,
      `ExecutionDecision`, `SourceClosureComparison`, `WorkerObservation`,
      `BothRootObservations`, `VerifiedReceiptBinding`, `CountDecision`).
    - Propagates all refusal codes, phases, and source-closure gaps.
    - Never emits `status == "PASS"` or `count_eligible == True` while `WRITES_ADMITTED` is `False`
      and N1-N8 obligations remain `UNRESOLVED`.
    """
    if not isinstance(row, str) or row not in host_wire.HOST_ROWS:
        raise ValueError(f"row must be one of {host_wire.HOST_ROWS!r}, got {row!r}")
    if not isinstance(closure_comparison, SourceClosureComparison):
        raise TypeError(
            f"closure_comparison must be SourceClosureComparison, got {type(closure_comparison).__name__}"
        )

    refusals: list[Refusal] = []
    refusal_codes: list[str] = []
    refusal_phases: list[str] = []
    reasons: list[str] = []

    def _record_refusal(stage: str, refusal: Refusal) -> None:
        refusals.append(refusal)
        refusal_codes.append(refusal.code.value)
        refusal_phases.append(refusal.phase.value)
        reasons.append(
            f"{stage} refused (phase={refusal.phase.value}, code={refusal.code.value}, "
            f"admission={refusal.admission_state.value}, effect={refusal.effect_state.value}, "
            f"seq={refusal.sequence_use.value})"
        )

    create_data, create_ref = _validate_boundary_result(create_result, CreateArmDecision, "before_create")
    if create_ref is not None:
        _record_refusal("before_create", create_ref)

    checker_data, checker_ref = _validate_boundary_result(checker_result, CheckerDecision, "before_checker")
    if checker_ref is not None:
        _record_refusal("before_checker", checker_ref)

    req_data, req_ref = _validate_boundary_result(request_result, RequestDecision, "before_request")
    if req_ref is not None:
        _record_refusal("before_request", req_ref)

    admit_data, admit_ref = _validate_boundary_result(admit_result, AdmissionDecision, "before_admit")
    if admit_ref is not None:
        _record_refusal("before_admit", admit_ref)

    exec_data, exec_ref = _validate_boundary_result(execute_result, ExecutionDecision, "before_execute")
    if exec_ref is not None:
        _record_refusal("before_execute", exec_ref)

    worker_data, worker_ref = _validate_boundary_result(
        worker_observation_result, WorkerObservation, "worker_observation"
    )
    if worker_ref is not None:
        _record_refusal("worker_observation", worker_ref)

    roots_data, roots_ref = _validate_boundary_result(
        roots_observation_result, BothRootObservations, "roots_observation"
    )
    if roots_ref is not None:
        _record_refusal("roots_observation", roots_ref)

    recv_data: VerifiedReceiptBinding | None = None
    recv_ref: Refusal | None = None
    if native_receive_result is not None:
        recv_data, recv_ref = _validate_boundary_result(
            native_receive_result, VerifiedReceiptBinding, "native_receive"
        )
        if recv_ref is not None:
            _record_refusal("native_receive", recv_ref)

    inner_count_decision: CountDecision | None = None
    count_ref: Refusal | None = None
    if count_result is not None:
        inner_count_decision, count_ref = _validate_boundary_result(
            count_result, CountDecision, "before_count"
        )
        if count_ref is not None:
            _record_refusal("before_count", count_ref)
        elif inner_count_decision is not None and inner_count_decision.verdict != "PASS":
            reasons.append(f"before_count verdict={inner_count_decision.verdict}")

    closure_reasons = tuple(closure_comparison.reasons)
    for creason in closure_reasons:
        if not isinstance(creason, str):
            raise TypeError(f"Expected str in closure_comparison.reasons, got {type(creason).__name__}")
        reasons.append(f"source_closure reason: {creason}")

    closure_accepted = closure_comparison.disposition == "MATCH" and len(closure_reasons) == 0
    if not closure_accepted and not closure_reasons:
        reasons.append(f"source_closure disposition={closure_comparison.disposition}")

    authority_accepted = (
        create_data is not None
        and checker_data is not None
        and req_data is not None
        and admit_data is not None
        and exec_data is not None
        and recv_ref is None
        and count_ref is None
    )
    worker_accepted = worker_data is not None
    roots_accepted = roots_data is not None
    receive_accepted = recv_data is not None

    if not (authority_accepted and closure_accepted and worker_accepted and roots_accepted and receive_accepted):
        status = "BLOCKED"
    else:
        status = "UNQUALIFIED"
        reasons.append(
            "P5 assessment: offline supplier join evaluated under disabled T4 posture "
            "(WRITES_ADMITTED=False, N1-N8 UNRESOLVED, P5 UNTRUSTED); not counted"
        )

    return NativeJoinedHostEvaluation(
        row=row,
        status=status,
        writes_admitted=host_wire.WRITES_ADMITTED,
        default_candidate_bindings_active=DEFAULT_CANDIDATE_BINDINGS is not None,
        boundary_mode="offline_injected_join",
        authority_accepted=authority_accepted,
        closure_accepted=closure_accepted,
        worker_observation_accepted=worker_accepted,
        roots_observation_accepted=roots_accepted,
        native_receive_accepted=receive_accepted,
        count_eligible=False,
        inner_count_decision=inner_count_decision,
        refusals=tuple(refusals),
        refusal_codes=tuple(refusal_codes),
        refusal_phases=tuple(refusal_phases),
        closure_disposition=closure_comparison.disposition,
        closure_reasons=closure_reasons,
        reasons=tuple(reasons),
        native_obligations=UNRESOLVED_NATIVE_OBLIGATIONS,
        r1_status="UNQUALIFIED",
        r1i_status="UNQUALIFIED",
        d1_status="UNQUALIFIED",
        d5_status="UNQUALIFIED",
        p5_trust_posture="UNTRUSTED",
    )


def evaluate_offline_native_join(
    *,
    row: str,
    service: P3AuthorityService,
    host_join: NativeHostJoin,
    worker_observer: WorkerObservationAdapter,
    peer_worker: AuthenticatedPeer,
    peer_checker: AuthenticatedPeer,
    peer_run: AuthenticatedPeer,
    peer_qa: AuthenticatedPeer,
    session_host: NativeSession,
    pre_dispatch_job: SelectedJob,
    running_job: SelectedJob,
    creator_observation: HostObservation,
    parent_root_binding: RootBinding,
    bootstrap_comparison: SourceClosureComparison,
    window_id: str,
    window_object_identity: NativeRootObject,
    window_birth_witness: NativeWitness,
    host_observation_arm: HostObservation,
    worker_observation_grant: ObservationGrant,
    worker_observation_job: SelectedJob | None = None,
    both_roots_observation: BothRootObservations,
    both_roots_actor: NativeProcessRef | None = None,
    both_roots_assertions: tuple[RootOwnerVsActorAssertion, ...] = (),
    checker_worker_observation: WorkerObservation | None = None,
    checker_both_roots_observation: BothRootObservations | None = None,
    closure_comparison_arm: SourceClosureComparison,
    qa_receiving: QAReceiving,
    compatibility_receiving: CompatibilityReceiving,
    receipt_producer_binding: ReceiptProducerBinding,
    request_identity: RequestIdentity,
    observation_cursors: CurrentObservationCursors,
    occurrence_handle: OccurrenceHandle,
    admission_witness: NativeWitness,
    operation_leg: OperationLeg,
    raw_publication: RawPublication,
    receive_effect: HostEffect,
    p5_assessment: P5Assessment,
) -> NativeJoinedHostEvaluation:
    """Execute a complete offline consumer join across #261/#262/#263/#71 supplier ports without live side effects."""
    if not isinstance(service, P3AuthorityService):
        raise TypeError(f"service must be a P3AuthorityService, got {type(service).__name__}")
    if not isinstance(worker_observer, WorkerObservationAdapter):
        raise TypeError(
            f"worker_observer must be a WorkerObservationAdapter, got {type(worker_observer).__name__}"
        )

    eff_worker_job = worker_observation_job if worker_observation_job is not None else running_job
    worker_obs_res = worker_observer.observe(
        worker_observation_grant,
        eff_worker_job,
        worker_observation_grant.boundary,
    )
    if isinstance(worker_obs_res, AcceptedData):
        actor_ref = (
            both_roots_actor
            if both_roots_actor is not None
            else both_roots_observation.publication.binding.actor_instance
        )
        roots_obs_res = worker_observer.root_observer.verify_both_roots(
            both_roots_observation,
            actor_instance=actor_ref,
            root_owner_assertions=both_roots_assertions,
            boundary=both_roots_observation.publication.observation_boundary,
            evidence=worker_obs_res.evidence,
        )
    else:
        roots_obs_res = worker_obs_res

    create_res = service.before_create(
        peer_worker,
        pre_dispatch_job,
        creator_observation,
        parent_root_binding,
        bootstrap_comparison,
    )

    checker_res: Result[CheckerDecision]
    if (
        isinstance(create_res, AcceptedData)
        and isinstance(worker_obs_res, AcceptedData)
        and isinstance(roots_obs_res, AcceptedData)
    ):
        reg = getattr(service, "registry", None) or getattr(service, "_registry", None)
        if reg is None:
            raise TypeError("service does not expose a P3AuthorityRegistry")
        cur_arm = reg.check_current(
            peer_checker,
            running_job.selection_revision,
            "A_PRE_ARM",
            authority_registry.default_effect_for_job(running_job, "A_PRE_ARM"),
        )
        if isinstance(cur_arm, AcceptedData):
            win_binding = WindowBinding(
                current=cur_arm.data,
                actual_creation=ActualCreation(
                    window_id=window_id,
                    object_identity=window_object_identity,
                    creator=create_res.data.creator,
                    birth=window_birth_witness,
                ),
            )
            checker_res = service.before_checker(
                peer_checker,
                win_binding,
                host_observation_arm,
                checker_worker_observation
                if checker_worker_observation is not None
                else worker_obs_res.data,
                checker_both_roots_observation
                if checker_both_roots_observation is not None
                else roots_obs_res.data,
                closure_comparison_arm,
                qa_receiving,
                compatibility_receiving,
                receipt_producer_binding,
            )
        else:
            checker_res = cur_arm
    elif isinstance(create_res, Refusal):
        checker_res = create_res
    elif isinstance(worker_obs_res, Refusal):
        checker_res = worker_obs_res
    else:
        assert isinstance(roots_obs_res, Refusal)
        checker_res = roots_obs_res

    req_res: Result[RequestDecision]
    if isinstance(checker_res, AcceptedData):
        req_row = getattr(request_identity, "row", row)
        req_res = service.before_request(
            peer_run,
            checker_res.data.binding,
            req_row if isinstance(req_row, str) else row,
            request_identity,
            observation_cursors,
        )
    else:
        req_res = checker_res

    admit_res: Result[AdmissionDecision]
    admitted_binding: AdmittedRequestBinding | None = None
    if isinstance(req_res, AcceptedData):
        admit_res = service.before_admit(
            peer_run,
            req_res.data.binding,
            observation_cursors,
        )
        if isinstance(admit_res, AcceptedData):
            rec_occ = service.record_admitted_occurrence(
                immutable_request_binding=req_res.data.binding,
                current_binding=admit_res.data.current,
                occurrence=occurrence_handle,
                admission_witness=admission_witness,
            )
            if isinstance(rec_occ, AcceptedData):
                admitted_binding = rec_occ.data
            else:
                admit_res = rec_occ
    else:
        admit_res = req_res

    exec_res: Result[ExecutionDecision]
    if isinstance(admit_res, AcceptedData) and admitted_binding is not None:
        exec_res = service.before_execute(
            peer_run,
            admitted_binding,
            operation_leg,
            observation_cursors,
        )
    else:
        assert isinstance(admit_res, Refusal)
        exec_res = admit_res

    recv_res: Result[VerifiedReceiptBinding] | None = None
    count_res: Result[CountDecision] | None = None
    if isinstance(exec_res, AcceptedData) and isinstance(req_res, AcceptedData):
        occ_lookup = host_join.lookup_occurrence(session_host, request_identity)
        if isinstance(occ_lookup, AcceptedData):
            pub_ver = host_join.verify_publication(
                session_host,
                request_identity,
                raw_publication,
                occ_lookup.data,
            )
            if isinstance(pub_ver, AcceptedData):
                recv_res = host_join.receive(
                    session_host,
                    request_identity,
                    pub_ver.data,
                    receive_effect,
                )
                if isinstance(recv_res, AcceptedData):
                    actual_req_and_rcpt = ActualRequestAndReceipt(
                        request=req_res.data.binding,
                        publication=raw_publication,
                    )
                    count_res = service.before_count(
                        peer_qa,
                        actual_req_and_rcpt,
                        p5_assessment,
                        pub_ver.data,
                        observation_cursors,
                        qa_receiving,
                    )
            else:
                recv_res = pub_ver
        else:
            recv_res = occ_lookup

    return join_offline_supplier_results(
        row=row,
        create_result=create_res,
        checker_result=checker_res,
        request_result=req_res,
        admit_result=admit_res,
        execute_result=exec_res,
        closure_comparison=closure_comparison_arm,
        worker_observation_result=worker_obs_res,
        roots_observation_result=roots_obs_res,
        native_receive_result=recv_res,
        count_result=count_res,
    )


__all__ = [
    "CANONICAL_N1_TO_N8_CODES",
    "CANONICAL_NATIVE_OBLIGATION_DESCRIPTIONS",
    "DECISION_SCHEMA",
    "DEFAULT_CANDIDATE_BINDINGS",
    "DEFAULT_NATIVE_BOUNDARY",
    "DEFAULT_NATIVE_HOST_JOIN",
    "DEFAULT_WORKER_OBSERVER",
    "EXISTING_TEMPER_SEAM_GUARANTEES",
    "SUPPLIER_ARTIFACTS",
    "UNRESOLVED_NATIVE_OBLIGATIONS",
    "WORKER_OBSERVATION_COMPAT_CORPUS_ID",
    "WRITES_ADMITTED",
    "AcceptedData",
    "AdmissionState",
    "EffectState",
    "NativeBoundaryStatus",
    "NativeJoinedHostEvaluation",
    "Phase",
    "Refusal",
    "RefusalCode",
    "Result",
    "RetryKind",
    "SequenceUse",
    "compose_disabled_consumer_service",
    "evaluate_offline_native_join",
    "inspect_disabled_native_boundary",
    "join_admitted_host_row",
    "join_native_host_row",
    "join_offline_supplier_results",
    "verify_canonical_supplier_bindings",
]
