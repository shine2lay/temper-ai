"""Owned source-contract checks, not native permission or effect enforcement.

The opening combined test joins actual canonical supplier records with explicit
test-only providers. Constructor values are not a replacement compatibility
corpus, authenticated evidence or proof of runtime effect enforcement.
"""

import inspect
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, dataclass, fields, replace
from enum import StrEnum
from pathlib import Path
from typing import Literal, TypeVar, get_args, get_origin, get_type_hints

import pytest

import p3_host_contracts as host
import p3_source_closure as source
from configs.architecture.bin import ops_host_source_comparison as source_facade
from temper_ai.config.admission_contract import DispatchIdentity
from temper_ai.p3_authority import contract
from temper_ai.p3_authority.references import (
    AuthenticatedPeer,
    NativeProcessRef,
    NativeSession,
    NativeSubject,
    PermissionHandle,
)
from temper_ai.p3_authority.refusals import (
    DECISION_SCHEMA,
    AdmissionState,
    EffectState,
    Phase,
    Refusal,
    RefusalCode,
    RetryKind,
    SequenceUse,
)
from temper_ai.p3_authority.results import AcceptedData, Boundary, DecisionEvidence
from temper_ai.p3_authority.selection import (
    AuthorityRef,
    CalibrationSelection,
    CompatibilityProfile,
    ImmutableReference,
    JobKey,
    ProjectSelection,
    SelectedJob,
    SelectedOperation,
)
from tests.test_architecture.ops_host_n3_cases import bad_twin, clean_world, wire
from tests.test_p3_host_contracts.examples import examples as host_examples


@dataclass(frozen=True)
class _Reference:
    path: str
    digest: str
    length: int
    revision: str


@dataclass(frozen=True)
class _FutureScope:
    selected_scope_reference: str
    subject_kind: Literal["future"] = "future"


@dataclass(frozen=True)
class _Evidence:
    """Explicit test-only implementation; no authenticated production origin."""

    selected_job: SelectedJob
    authority_revisions: tuple[AuthorityRef, ...]
    window: NativeSubject | None
    processes: tuple[NativeProcessRef, ...]
    effect: SelectedOperation
    phase: Phase
    boundary: Boundary
    source: ImmutableReference
    closure: ImmutableReference
    compatibility: CompatibilityProfile
    receiving: tuple[ImmutableReference, ...]
    schema: Literal["p3-native-decision/1"] = "p3-native-decision/1"


def _refusal() -> Refusal:
    return Refusal(
        code=RefusalCode.AUTHORITY_UNAVAILABLE,
        phase=Phase.C,
        retry_kind=RetryKind.SAME_BOUNDARY_AFTER_REPAIR,
        admission_state=AdmissionState.NOT_ADMITTED,
        effect_state=EffectState.NONE,
        sequence_use=SequenceUse.UNUSED,
    )


def test_combined_owned_selection_result_and_refusal_contract() -> None:
    # Real candidate identity, not a copied P3 dispatch grammar.
    dispatch = DispatchIdentity(
        execution_uuid="00000000-0000-4000-8000-000000000001",
        dispatch_nonce="00000000-0000-4000-8000-000000000002",
        running_attempt=1,
    )
    reference = _Reference("synthetic/publication", "0" * 64, 17, "publication-r1")
    authority = AuthorityRef(issuer_id="test-only", record_id="record", authority_revision="a1")
    project = ProjectSelection(
        project_id="project", run_id="domain-run-not-execution-uuid",
        kit_id="kit", kit_sha256="1" * 64, build_sums_sha256="2" * 64,
        publication_ref=reference, publication_revision="publication-r1", build_ref=reference,
    )
    profile = CompatibilityProfile(
        decision=DECISION_SCHEMA,
        reviewed_graph="p3-reviewed-source-graph/1",
        loaded_envelope="p3-reviewed-loaded-closure/1",
        comparator="reviewed-test-only-comparator-revision",
        observation="reviewed-test-only-observer-revision",
        inspect="/2", caller="reviewed-test-only-caller-revision",
        corpus="ops-host-compat-corpus/1", receiving="test-only-receiving-revision",
    )
    operation = SelectedOperation(domain="test-only-lifecycle", operation="create-arm", revision="o1")
    job = SelectedJob(
        pre_dispatch_or_running_job=JobKey(dispatch=dispatch, job_revision="j1"),
        selector_issuer=authority, selection_revision="s1", selection=project,
        approved_descriptor_digest="3" * 64, expected_source_digest="4" * 64,
        reviewed_closure_ref=reference, compatibility_profile=profile,
        authorized_operations=frozenset({operation}), conditions=(), authority_refs=(authority,),
    )
    evidence: DecisionEvidence = _Evidence(
        selected_job=job, authority_revisions=(authority,),
        window=_FutureScope("selected-new-leaf"), processes=(), effect=operation,
        phase=Phase.A, boundary="A_PRE_CREATE", source=reference,
        closure=reference, compatibility=profile, receiving=(),
    )
    result = AcceptedData(data=job, evidence=evidence)
    refused = _refusal()

    assert result.data is job
    assert result.evidence.selected_job is job
    assert job.pre_dispatch_or_running_job.dispatch is dispatch
    assert project.run_id != dispatch.execution_uuid
    assert job.route == "external-db-fresh"
    assert result.evidence.window.subject_kind == "future"
    assert refused.counted is False
    assert refused.schema == DECISION_SCHEMA
    assert refused.sequence_use is SequenceUse.UNUSED
    assert get_type_hints(AcceptedData)["evidence"] is DecisionEvidence
    assert get_type_hints(JobKey)["dispatch"] is DispatchIdentity
    assert profile.reviewed_graph != profile.loaded_envelope != profile.decision
    assert profile.corpus == "ops-host-compat-corpus/1"

    calibration = CalibrationSelection(
        manifest_ref=reference, entry_id="explicit-entry", calibration_run="explicit-run",
        round="explicit-round", copy_identity="explicit-copy", expected_draft_kit=reference,
        build_sums_sha256="5" * 64, publication_ref=reference,
        publication_revision="publication-r1", build_ref=reference,
        selected_runtime_profile="explicit-runtime",
    )
    selected_calibration = replace(job, selection=calibration, selection_revision="s2")
    assert selected_calibration.selection.kind == "calibration"
    assert selected_calibration.selection.manifest_ref is reference
    assert selected_calibration.selection.entry_id == "explicit-entry"
    assert job.selection is project  # Old immutable selection is not rewritten.
    _exercise_host_contract(evidence)


def test_refusal_vocabulary_is_the_exact_adopted_domain() -> None:
    expected = {
        "authority_unbound", "issuer_unverified", "subject_mismatch", "scope_mismatch",
        "conditions_unmet", "authority_expired", "authority_revoked", "authority_unavailable",
        "selection_missing", "selection_ambiguous", "selection_foreign", "selection_changed",
        "route_unsupported", "dispatch_changed", "peer_unverified", "runtime_changed",
        "root_mismatch", "observation_not_authorized", "rights_missing", "source_changed",
        "closure_version", "closure_incomplete", "closure_mismatch", "observation_gap",
        "qa_receiving_missing", "compatibility_unqualified", "prior_missing", "prior_foreign",
        "prior_unverified", "window_ineligible", "result_unverified", "already_counted",
        "writes_disabled",
    }
    assert {code.value for code in RefusalCode} == expected
    for code in RefusalCode:
        assert replace(_refusal(), code=code).code is code


_ENUM_FIELDS = (
    ("code", RefusalCode.AUTHORITY_UNAVAILABLE),
    ("phase", Phase.C),
    ("retry_kind", RetryKind.SAME_BOUNDARY_AFTER_REPAIR),
    ("admission_state", AdmissionState.NOT_ADMITTED),
    ("effect_state", EffectState.NONE),
    ("sequence_use", SequenceUse.UNUSED),
)


@pytest.mark.parametrize("name,value", _ENUM_FIELDS)
@pytest.mark.parametrize("poison", ["plain", "suffix", "prefix", "foreign"])
def test_every_closed_field_rejects_non_exact_values(name: str, value: StrEnum, poison: str) -> None:
    # Canaries are after allowed text too: prefix/contains matching must fail.
    invalid = {
        "plain": value.value,
        "suffix": value.value + " PRIVATE_CANARY",
        "prefix": "PRIVATE_CANARY " + value.value,
        "foreign": StrEnum("ForeignDomain", {"SAME": value.value}).SAME,
    }[poison]
    with pytest.raises(ValueError) as caught:
        replace(_refusal(), **{name: invalid})
    assert str(caught.value) == "p3_contract_field_type"
    assert "PRIVATE_CANARY" not in str(caught.value)


def test_refusal_cannot_gain_schema_fields_counting_or_mutable_history() -> None:
    refused = _refusal()
    for changes in ({"schema": "other/1"}, {"counted": True}, {"unknown": "untrusted"}):
        with pytest.raises((ValueError, TypeError)):
            replace(refused, **changes)
    with pytest.raises(FrozenInstanceError):
        refused.sequence_use = SequenceUse.USED
    required = {item.name for item in fields(Refusal) if item.init}
    assert required == {name for name, _ in _ENUM_FIELDS}
    with pytest.raises(TypeError):
        Refusal(code=RefusalCode.AUTHORITY_UNAVAILABLE)


def test_refusal_preserves_distinct_admission_effect_and_sequence_history() -> None:
    unused = _refusal()
    used = replace(
        unused, admission_state=AdmissionState.ALREADY_ADMITTED,
        effect_state=EffectState.ADMITTED_ONLY, sequence_use=SequenceUse.USED,
    )
    uncertain = replace(
        used, effect_state=EffectState.UNCERTAIN, sequence_use=SequenceUse.UNKNOWN,
    )
    partial_creation = replace(
        unused, phase=Phase.A, effect_state=EffectState.PARTIAL,
        sequence_use=SequenceUse.NOT_APPLICABLE,
    )
    assert (unused.sequence_use, used.sequence_use, uncertain.sequence_use) == (
        SequenceUse.UNUSED, SequenceUse.USED, SequenceUse.UNKNOWN,
    )
    assert partial_creation.admission_state is AdmissionState.NOT_ADMITTED
    assert partial_creation.effect_state is EffectState.PARTIAL
    assert partial_creation.sequence_use is SequenceUse.NOT_APPLICABLE
    assert all(item.counted is False for item in (unused, used, uncertain, partial_creation))
    assert unused.effect_state is EffectState.NONE  # Later state never rewrites history.


def test_supplier_exports_and_consumer_signatures_have_one_identity() -> None:
    exports = (
        "ReviewedSourceGraph", "LoadedClosureEnvelope", "NativeClosureExpectation",
        "VerifiedClosureOrigins", "SourceClosureComparison", "N3SourceEpoch",
        "N3ObservationEpoch", "N3Coverage", "N3Gap", "validate_reviewed_graph",
        "validate_loaded_envelope", "compare_loaded_source",
    )
    for name in exports:
        assert getattr(contract, name) is getattr(source, name)
        assert getattr(source_facade, name) is getattr(source, name)
    hints = get_type_hints(contract.compare_loaded_source)
    assert hints == {
        "reviewed": source.ReviewedSourceGraph,
        "observed": source.LoadedClosureEnvelope,
        "expected": source.NativeClosureExpectation,
        "verified": source.VerifiedClosureOrigins,
        "return": source.SourceClosureComparison,
    }
    params = inspect.signature(contract.compare_loaded_source).parameters
    assert params["expected"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["verified"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["expected"].default is inspect.Parameter.empty
    assert params["verified"].default is inspect.Parameter.empty
    required_fields = {
        source.ReviewedSourceGraph: {"graph", "content"},
        source.LoadedClosureEnvelope: {"envelope", "content"},
        source.NativeClosureExpectation: {
            "binding", "boundary", "reviewed_graph", "review_ref", "processes", "legacy_links",
        },
        source.VerifiedClosureOrigins: {
            "reviewed_bytes", "observed_bytes", "expectation", "validity_checkpoint", "facts",
        },
        source.SourceClosureComparison: {
            "disposition", "reasons", "binding", "boundary", "reviewed_graph", "frontiers",
        },
        source.N3SourceEpoch: {"reviewed_graph", "review_ref", "selection_revision"},
        source.N3ObservationEpoch: {"instance", "collector_ref", "frontier"},
    }
    for record, expected_fields in required_fields.items():
        assert {field.name for field in fields(record)} == expected_fields
        assert expected_fields <= get_type_hints(record).keys()
        assert record.__module__ == "p3_source_closure.records"
    assert contract.Boundary is source.records.BoundaryPhase


def test_supplier_comparison_reuses_additive_cases_without_rewriting_oracles() -> None:
    # Supplier's already-registered extension values, not a second corpus.
    clean = clean_world("N3-08")
    graph = contract.validate_reviewed_graph(wire(clean.reviewed.graph))
    envelope = contract.validate_loaded_envelope(wire(clean.observed.envelope))
    compared = contract.compare_loaded_source(
        graph, envelope, expected=clean.expected, verified=clean.verified,
    )
    assert type(graph) is source.ReviewedSourceGraph
    assert type(envelope) is source.LoadedClosureEnvelope
    assert type(compared) is source.SourceClosureComparison
    assert compared.disposition == "MATCH"
    assert len(compared.frontiers) >= 2  # Independent host and worker profiles.
    assert compared.binding is clean.expected.binding
    assert compared.boundary is clean.expected.boundary

    bad = bad_twin("N3-08", clean)
    refused = contract.compare_loaded_source(
        bad.reviewed, bad.observed, expected=bad.expected, verified=bad.verified,
    )
    assert refused.disposition == "UNKNOWN"
    assert "SEQUENCE_GAP" in refused.reasons
    assert clean.observed == envelope  # Original remains intact.

    absent = source.VerifiedClosureOrigins(None, None, None, None, ())
    unknown = contract.compare_loaded_source(graph, envelope, expected=clean.expected, verified=absent)
    assert unknown.disposition == "UNKNOWN"
    assert "REVIEW_ORIGIN" in unknown.reasons
    assert "OBSERVER_ORIGIN" in unknown.reasons
    # MATCH is deliberately not an AcceptedData/count/permission result.
    assert not isinstance(compared, AcceptedData)

    process = clean.observed.envelope.process_observations[0]
    frontier = clean.expected.processes[0].frontier
    source_epoch = contract.N3SourceEpoch(
        clean.expected.reviewed_graph, clean.expected.review_ref,
        clean.expected.binding.selection_revision,
    )
    observation_epoch = contract.N3ObservationEpoch(process.instance, process.collector_ref, frontier)
    assert source_epoch.reviewed_graph is clean.expected.reviewed_graph
    assert observation_epoch.frontier is frontier
    assert observation_epoch.instance is process.instance


_SUPPLIER_IMPORT_PROBE = '''
import json
import sys

# Audit only real operational contact attempts; ordinary Python code loading is
# allowed. No private files/env are supplied. This is not an isolation sandbox.
def audit(event, args):
    if event in {"socket.connect", "socket.bind", "subprocess.Popen", "os.system", "sqlite3.connect"}:
        raise RuntimeError("unexpected_operational_contact")
sys.addaudithook(audit)

import p3_source_closure as leaf
import p3_host_contracts as host
if any(name == "temper_ai" or name.startswith("temper_ai.") for name in sys.modules):
    raise RuntimeError("supplier_reverse_import")

# Patch the actual third-party contact/engine/client paths before importing the
# consumer, including names captured by later from-imports.
import httpx
import sqlalchemy
import sqlalchemy.orm
import sqlmodel

def refuse(*args, **kwargs):
    raise RuntimeError("unexpected_operational_contact")
httpx.Client.__init__ = refuse
httpx.AsyncClient.__init__ = refuse
httpx.Client.send = refuse
httpx.AsyncClient.send = refuse
sqlalchemy.create_engine = refuse
sqlmodel.create_engine = refuse
sqlalchemy.orm.Session.__init__ = refuse
sqlmodel.Session.__init__ = refuse

from temper_ai.p3_authority import contract
for name in ("ReviewedSourceGraph", "LoadedClosureEnvelope", "NativeClosureExpectation",
             "VerifiedClosureOrigins", "SourceClosureComparison", "N3SourceEpoch",
             "N3ObservationEpoch", "N3Coverage", "N3Gap", "compare_loaded_source",
             "validate_reviewed_graph", "validate_loaded_envelope"):
    if getattr(contract, name) is not getattr(leaf, name):
        raise RuntimeError("supplier_identity_changed")
for name in ("temper_ai.p3_authority.service", "temper_ai.p3_authority.registry",
             "temper_ai.api.routes", "temper_ai.runner.admission"):
    if name in sys.modules:
        raise RuntimeError("unexpected_consumer_composition")

from typing import get_origin, get_type_hints
for name in ("SelectedHostJob", "HostObservation", "HostCoverage", "RootBinding",
             "EffectLease", "OccurrenceHandle", "RawPublication", "ReceiptProvenance"):
    if get_origin(getattr(contract, name)) is not getattr(host, name):
        raise RuntimeError("host_identity_changed")
for port in (contract.NativeHostJoin, contract.P3AuthorityRegistry,
             contract.P3NativeBoundary, contract.WorkerObserver, contract.RootObserver):
    for name in port.__abstractmethods__:
        get_type_hints(getattr(port, name))

# Test-only fixture transfer: only Systems' actual decoder/records are used.
# These synthetic verified values are not accepted from production wire input.
from p3_source_closure.parsing import decode_record
synthetic = json.loads(sys.stdin.read())
reviewed = contract.validate_reviewed_graph(synthetic["reviewed"])
observed = contract.validate_loaded_envelope(synthetic["observed"])
expected = decode_record(synthetic["expected"], leaf.NativeClosureExpectation)
verified = decode_record(synthetic["verified"], leaf.VerifiedClosureOrigins)
matched = contract.compare_loaded_source(reviewed, observed, expected=expected, verified=verified)
unknown = contract.compare_loaded_source(
    reviewed, observed, expected=expected,
    verified=leaf.VerifiedClosureOrigins(None, None, None, None, ()),
)
if matched.disposition != "MATCH" or unknown.disposition != "UNKNOWN":
    raise RuntimeError("synthetic_supplier_result_changed")
'''


def test_supplier_fresh_interpreter_import_has_no_operational_contact(tmp_path: Path) -> None:
    clean = clean_world()
    synthetic = json.dumps({
        "reviewed": wire(clean.reviewed.graph), "observed": wire(clean.observed.envelope),
        "expected": wire(clean.expected), "verified": wire(clean.verified),
    }).encode("ascii")
    child = subprocess.run(
        [sys.executable, "-I", "-c", _SUPPLIER_IMPORT_PROBE],
        cwd=tmp_path, env={}, input=synthetic, capture_output=True, check=False,
    )
    # Never assert on CompletedProcess/child output/argv: pytest -vv leaks it.
    returncode = child.returncode
    assert returncode == 0


@pytest.mark.parametrize("reference", [AuthenticatedPeer, NativeSession, PermissionHandle])
def test_service_references_are_abstract_not_local_capability_factories(reference: type) -> None:
    with pytest.raises(TypeError):
        reference()


_T = TypeVar("_T")


@dataclass(frozen=True)
class _Permission:
    observation_permission: str


@dataclass(frozen=True)
class _Watch:
    observation_session: str
    permission: PermissionHandle


@dataclass(frozen=True)
class _Witness:
    witness_reference: str


@dataclass(frozen=True)
class _ProcessRef:
    process_registration: str


@dataclass(frozen=True)
class _Peer:
    peer_registration: str
    process: NativeProcessRef


@dataclass(frozen=True)
class _Session:
    peer: AuthenticatedPeer
    session_reference: str


@dataclass(frozen=True)
class _TestHostProvider(contract.NativeHostJoin):
    """Explicit SOURCE fixture provider, never installed or authenticated.

    All replies and refusal history are supplied by the test. No default-ready
    provider or runtime policy is implemented by this fixture.
    """

    evidence: DecisionEvidence
    selected: contract.SelectedHostJob
    permission: PermissionHandle
    watch: contract.ObservationSession
    observation: contract.HostObservation
    lease: contract.EffectLease
    witness: contract.NativeWitness
    provenance: contract.ReceiptProvenance
    received: contract.NativeReceive
    refusal: Refusal | None

    def _reply(self, value: _T) -> contract.Result[_T]:
        return self.refusal if self.refusal is not None else AcceptedData(data=value, evidence=self.evidence)

    def select_host_job(self, session: NativeSession) -> contract.Result[contract.SelectedHostJob]:
        return self._reply(self.selected)

    def permit_observation(
        self, session: NativeSession, scope: contract.ObservationScope,
    ) -> contract.Result[PermissionHandle]:
        return self._reply(self.permission)

    def open_observation(
        self, permission: PermissionHandle, scope: contract.ObservationScope,
    ) -> contract.Result[contract.ObservationSession]:
        return self._reply(self.watch)

    def observe(
        self, session: contract.ObservationSession, boundary: contract.HostEffect,
    ) -> contract.Result[contract.HostObservation]:
        return self._reply(self.observation)

    def recheck_effect(
        self, session: contract.ObservationSession, effect: contract.HostEffect,
        coverage: contract.HostCoverage,
    ) -> contract.Result[contract.EffectLease]:
        return self._reply(self.lease)

    def witness_event(
        self, session: contract.ObservationSession, key: contract.OperationKey,
        boundary: contract.HostEffect,
    ) -> contract.Result[contract.NativeWitness]:
        return self._reply(self.witness)

    def lookup_occurrence(
        self, session: NativeSession, key: contract.OperationKey,
    ) -> contract.Result[contract.NativeWitness]:
        return self._reply(self.witness)

    def verify_publication(
        self, session: NativeSession, key: contract.OperationKey,
        publication: contract.RawPublication, witness: contract.NativeWitness,
    ) -> contract.Result[contract.ReceiptProvenance]:
        return self._reply(self.provenance)

    def receive(
        self, session: NativeSession, key: contract.OperationKey,
        provenance: contract.ReceiptProvenance, boundary: contract.HostEffect,
    ) -> contract.Result[contract.NativeReceive]:
        return self._reply(self.received)


def _exercise_host_contract(evidence: DecisionEvidence) -> None:
    # Reuse supplied synthetic recipes, not another corpus/oracle. Their native
    # placeholders are intentionally UNVERIFIED data, never permission inputs.
    values = host_examples()
    world = clean_world()
    source_epoch = source.N3SourceEpoch(
        world.expected.reviewed_graph, world.expected.review_ref,
        world.expected.binding.selection_revision,
    )
    process = world.observed.envelope.process_observations[0]
    observation_epoch = source.N3ObservationEpoch(
        process.instance, process.collector_ref, world.expected.processes[0].frontier,
    )
    observed = replace(
        values["HostObservation"], observed=world.observed,
        source_epoch=source_epoch, observation_epoch=observation_epoch,
        coverage="launch", gaps=(),
    )
    selected = replace(
        values["SelectedHostJob"], caller=replace(
            values["CallerSelection"], source_review_ref=world.reviewed,
            runtime_route="external-db-fresh",
        ),
    )
    permission = _Permission("test-only-collection")
    watch = _Watch("test-only-session", permission)
    witness = _Witness("test-only-captured-event")
    provenance = values["ReceiptProvenance"]
    publication = values["RawPublication"]
    key = values["LifecycleKey"]
    received = contract.VerifiedReceiptBinding(
        selection=selected.selection, operation_key=key,
        occurrence=values["OccurrenceHandle"], provenance=provenance,
        publication=publication, receiving=witness, predecessor=None,
        disposition="verified",
    )
    provider: contract.NativeHostJoin = _TestHostProvider(
        evidence, selected, permission, watch, observed, values["EffectLease"],
        witness, provenance, received, None,
    )
    # Explicit test-only channel shape; never authenticated by construction.
    session = _Session(_Peer("test-peer", _ProcessRef("test-process")), "test-session")
    scope, effect, coverage = values["ObservationScope"], values["HostEffect"], values["HostCoverage"]
    replies = (
        provider.select_host_job(session), provider.permit_observation(session, scope),
        provider.open_observation(permission, scope), provider.observe(watch, effect),
        provider.recheck_effect(watch, effect, coverage),
        provider.witness_event(watch, key, effect), provider.lookup_occurrence(session, key),
        provider.verify_publication(session, key, publication, witness),
        provider.receive(session, key, provenance, effect),
    )
    assert tuple(reply.data for reply in replies) == (
        selected, permission, watch, observed, values["EffectLease"], witness,
        witness, provenance, received,
    )
    assert all(reply.evidence is evidence for reply in replies)
    assert type(replies[0].data) is host.SelectedHostJob
    assert type(replies[3].data) is host.HostObservation
    assert replies[3].data.observed is world.observed
    assert replies[-1].data is received
    assert not isinstance(received, contract.CountDecision)
    unavailable = replace(provider, refusal=_refusal())
    assert unavailable.select_host_job(session).code is RefusalCode.AUTHORITY_UNAVAILABLE
    assert unavailable.receive(session, key, provenance, effect).counted is False


_HOST_PORTS = {
    "select_host_job": {"session": contract.NativeSession, "return": contract.Result[contract.SelectedHostJob]},
    "permit_observation": {"session": contract.NativeSession, "scope": contract.ObservationScope, "return": contract.Result[contract.PermissionHandle]},
    "open_observation": {"permission": contract.PermissionHandle, "scope": contract.ObservationScope, "return": contract.Result[contract.ObservationSession]},
    "observe": {"session": contract.ObservationSession, "boundary": contract.HostEffect, "return": contract.Result[contract.HostObservation]},
    "recheck_effect": {"session": contract.ObservationSession, "effect": contract.HostEffect, "coverage": contract.HostCoverage, "return": contract.Result[contract.EffectLease]},
    "witness_event": {"session": contract.ObservationSession, "key": contract.OperationKey, "boundary": contract.HostEffect, "return": contract.Result[contract.NativeWitness]},
    "lookup_occurrence": {"session": contract.NativeSession, "key": contract.OperationKey, "return": contract.Result[contract.NativeWitness]},
    "verify_publication": {"session": contract.NativeSession, "key": contract.OperationKey, "publication": contract.RawPublication, "witness": contract.NativeWitness, "return": contract.Result[contract.ReceiptProvenance]},
    "receive": {"session": contract.NativeSession, "key": contract.OperationKey, "provenance": contract.ReceiptProvenance, "boundary": contract.HostEffect, "return": contract.Result[contract.NativeReceive]},
}


def test_all_nine_host_ports_are_exact_abstract_and_resolvable() -> None:
    assert contract.NativeHostJoin.__abstractmethods__ == _HOST_PORTS.keys()
    for name, expected in _HOST_PORTS.items():
        method = getattr(contract.NativeHostJoin, name)
        assert get_type_hints(method) == expected
        assert set(inspect.signature(method).parameters) == {"self", *expected.keys()} - {"return"}
        assert method.__isabstractmethod__ is True
    class MissingProvider(contract.NativeHostJoin):
        pass
    with pytest.raises(TypeError):
        MissingProvider()
    assert not getattr(contract.NativeHostJoin, "_is_runtime_protocol", False)


def test_host_generics_use_all_canonical_roles_without_foreign_copies() -> None:
    from temper_ai.p3_authority import host_types

    roles = {
        "SelectionT": contract.NativeSelection, "WitnessT": contract.NativeWitness,
        "AdmissionT": contract.NativeAdmission, "ProcessT": contract.NativeProcessRef,
        "BirthT": contract.NativeBirthIdentity, "ContainerT": contract.NativeContainerIdentity,
        "RootObjectT": contract.NativeRootObject, "SubjectT": contract.NativeSubject,
        "TargetT": contract.NativeEffectTarget, "GrantT": contract.NativeGrantRef,
        "IntervalT": contract.NativeInterval, "FieldsT": contract.NativeObservationFields,
        "EventRangeT": contract.NativeEventRange, "DisarmT": contract.NativeDisarmRelation,
        "WatchT": contract.ObservationSession, "ReviewedT": source.ReviewedSourceGraph,
        "ObservedT": source.LoadedClosureEnvelope, "ComparisonT": source.SourceClosureComparison,
        "SourceEpochT": source.N3SourceEpoch, "ObservationEpochT": source.N3ObservationEpoch,
        "CoverageT": source.N3Coverage, "GapT": source.N3Gap,
    }
    seen = set()
    for name in host.__all__:
        if name == "OperationKey":
            assert get_args(contract.OperationKey) == (contract.LifecycleKey, contract.RowKey)
            continue
        exported = "Host" + name if name in {"ProjectSelection", "CalibrationSelection"} else name
        actual, original = getattr(host_types, exported), getattr(host, name)
        assert getattr(contract, exported) is actual
        assert (get_origin(actual) or actual) is original
        parameters = getattr(original, "__parameters__", ())
        assert get_args(actual) == tuple(roles[p.__name__] for p in parameters)
        seen.update(p.__name__ for p in parameters)
    assert seen == roles.keys()


def test_service_ports_keep_phase_effect_receiving_and_count_distinct() -> None:
    expected_ports = {
        contract.IssuerVerifier: {"verify"},
        contract.P3AuthorityRegistry: {"for_submit", "for_run", "check_current", "bind_created"},
        contract.P3NativeBoundary: {"before_create", "before_checker", "before_request", "before_admit", "before_execute", "before_count"},
        contract.WorkerObserver: {"observe"}, contract.RootObserver: {"observe"},
        contract.HostObserver: {
            "lookup_observation", "observe", "begin", "checkpoint", "before_effect",
            "finish", "finish_witness",
        },
        contract.HostProvenance: {
            "note_admission", "note_effect", "bind_publication", "verify_linked_receipt",
            "lookup_occurrence_handle", "lookup_witness",
        },
        contract.SharedN3: {"compare"},
    }
    for port, methods in expected_ports.items():
        assert port.__abstractmethods__ == methods
        for name in methods:
            method = getattr(port, name)
            hints = get_type_hints(method)
            assert set(hints) == set(inspect.signature(method).parameters) - {"self"} | {"return"}
            assert "Any" not in str(hints)
            assert method.__isabstractmethod__ is True
    hints = get_type_hints(contract.P3NativeBoundary.before_checker)
    assert hints["host_observation"] == contract.HostObservation
    assert hints["worker_observation"] is contract.WorkerObservation
    assert hints["both_root_observations"] is contract.BothRootObservations
    assert get_type_hints(contract.P3NativeBoundary.before_count)["return"] == contract.Result[contract.CountDecision]
    assert contract.NativeReceive is contract.VerifiedReceiptBinding
    assert contract.NativeReceive is not contract.CountDecision
    assert contract.RequestIdentity == contract.RowKey
    assert "actual_creation" in get_type_hints(contract.WindowBinding)
    assert get_type_hints(contract.ActualCreation)["object_identity"] is contract.NativeRootObject
    assert get_type_hints(contract.OperationLeg)["target"] is contract.ExistingSubject
    assert get_type_hints(contract.DecisionEvidence.window.fget)["return"] == contract.NativeSubject | None


def test_prior_history_and_failure_data_do_not_become_count_permission() -> None:
    values = host_examples()
    prior_key = replace(values["RowKey"], row="D-1", request_id="prior", sequence=1)
    next_key = replace(prior_key, row="D-5", request_id="next", sequence=2)
    prior_occurrence = replace(
        values["OccurrenceHandle"], key=prior_key, state="failed",
        controller=values["OccurrenceHandle"].admitting_process,
    )
    prior_publication = replace(
        values["RawPublication"], occurrence=prior_occurrence,
        request_raw_ref=prior_key.request_raw_ref, outcome="app-failure",
        window_ref=values["RawRef"], numbered_log_ref=values["RawRef"],
        current_row_ref=values["RawRef"],
    )
    prior = replace(
        values["ReceiptProvenance"], operation_key=prior_key,
        raw_publication=prior_publication,
    )
    following = replace(prior, operation_key=next_key, predecessor=prior)
    assert following.predecessor is prior
    assert prior.raw_publication.outcome == "app-failure"
    assert following.operation_key.sequence > prior.operation_key.sequence
    assert following.operation_key.request_id != prior.operation_key.request_id
    assert prior.operation_key.window_id == following.operation_key.window_id
    assert prior.operation_key.writer == following.operation_key.writer
    assert not isinstance(prior, contract.CountDecision)
    # Constructors preserve supplied uncertainty; they are NOT prior validators.
    uncertain = replace(following, state="uncertain")
    assert uncertain.predecessor is prior
    assert uncertain.state == "uncertain"
    assert _refusal().counted is False


@pytest.mark.parametrize("name,value", _ENUM_FIELDS)
@pytest.mark.parametrize("mutation", ["drop", "prefix", "contains"])
def test_every_refusal_guard_has_deletion_and_loosening_bites(
    monkeypatch: pytest.MonkeyPatch, name: str, value: StrEnum, mutation: str,
) -> None:
    original = Refusal.__post_init__

    def mutated(record: Refusal) -> None:
        supplied = getattr(record, name)
        bypass = mutation == "drop" or (
            isinstance(supplied, str) and (
                supplied.startswith(value.value) if mutation == "prefix" else value.value in supplied
            )
        )
        if bypass:
            object.__setattr__(record, name, value)
        try:
            original(record)
        finally:
            object.__setattr__(record, name, supplied)

    monkeypatch.setattr(Refusal, "__post_init__", mutated)
    # Semantic mutation of exactly one field guard. The ORIGINAL negative case
    # must fail, not merely a separately invented mutant-check assertion.
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_every_closed_field_rejects_non_exact_values(name, value, "suffix")


@pytest.mark.parametrize("unsafe", [False, True])
def test_child_failure_privacy_canary_at_verbose_level(tmp_path: Path, unsafe: bool) -> None:
    canary = "CONTRACT_PRIVATE_CHILD_OUTPUT_" + "Z" * 60
    check = "assert child.returncode == 0" if unsafe else "code = child.returncode; assert code == 0"
    fixture = tmp_path / "test_child_failure.py"
    fixture.write_text(
        "import os, subprocess\n"
        "def test_child():\n"
        "    secret = os.environ['P3_CONTRACT_TEST_CANARY']\n"
        "    child = subprocess.CompletedProcess([secret], 9, secret, secret)\n"
        f"    {check}\n"
    )
    child = subprocess.run(
        [sys.executable, "-m", "pytest", "-vv", "-p", "no:cacheprovider", str(fixture)],
        cwd=tmp_path, env={**os.environ, "P3_CONTRACT_TEST_CANARY": canary},
        capture_output=True, check=False,
    )
    code = child.returncode
    leaked = canary.encode() in child.stdout + child.stderr
    assert code == 1
    assert leaked is unsafe
