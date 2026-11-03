# SPDX-License-Identifier: MIT
"""P3 candidate bindings composing authority selection with real V1 admission primitives.

Implements the existing ``temper_ai.runner.admission.CandidateBindings`` protocol
by verifying caller/execution authority through ``P3AuthorityRegistry`` and
delegating capture, installation/preparation verification, snapshot projection,
context binding, and ``external-db-fresh`` persistence to the existing V1
primitives in:

- ``temper_ai.runner.admission`` (``CandidateBindings``, ``DbAdmissionTransport``,
  ``InstallationVerifier``, ``PreparationVerifier``)
- ``temper_ai.config.admission_contract`` (``AdmissionRecord``, ``AdmissionRefused``,
  ``ApprovedCandidateDescriptor``, ``ContractCodec``, ``DescriptorAuthority``,
  ``DispatchIdentity``, ``FrozenJSON``, ``RefusalCode``, ``RootReadiness``)
- ``temper_ai.config.admission_capture`` (``ConfigStore``, ``RawCapture``)
- ``temper_ai.config.candidate_admission`` (``load_candidate``, ``project_agent``,
  ``project_graph``, ``project_node``)
- ``temper_ai.agent.admission_use`` (``ActualProjection``, ``CandidateUse``,
  ``ProtectedUseTransport``)

No P3 fields are added to the frozen candidate wire, and no second workflow
store/loader or fallback is introduced.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from temper_ai.agent.admission_use import (
    ActualProjection,
    CandidateUse,
    ProtectedUseTransport,
)
from temper_ai.api.caller import Caller
from temper_ai.config.admission_capture import ConfigStore, RawCapture
from temper_ai.config.admission_contract import (
    AdmissionRecord,
    AdmissionRefused,
    ApprovedCandidateDescriptor,
    ContractCodec,
    DescriptorAuthority,
    DispatchIdentity,
    FrozenJSON,
    canonical_bytes,
)
from temper_ai.config.admission_contract import (
    RefusalCode as CandidateRefusalCode,
)
from temper_ai.config.candidate_admission import load_candidate
from temper_ai.p3_authority.boundary_types import (
    ActualCreation,
    CurrentBinding,
    WindowBinding,
)
from temper_ai.p3_authority.references import AuthenticatedPeer
from temper_ai.p3_authority.refusals import Refusal, RefusalCode
from temper_ai.p3_authority.results import DecisionEvidence
from temper_ai.p3_authority.run_selection_source import encode_admitted_selection
from temper_ai.p3_authority.selection import (
    JobKey,
    PreDispatchJob,
    SelectedJob,
)
from temper_ai.p3_authority.service_ports import P3AuthorityRegistry
from temper_ai.runner.admission import (
    CandidateBindings,
    DbAdmissionTransport,
    InstallationVerifier,
    PreparationVerifier,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from temper_ai.runner.context import RunnerContext
    from temper_ai.shared.types import ExecutionContext
    from temper_ai.stage.models import WorkflowConfig
    from temper_ai.stage.node import Node


def _map_p3_refusal_to_candidate_code(code: RefusalCode) -> CandidateRefusalCode:
    if code in (
        RefusalCode.AUTHORITY_UNBOUND,
        RefusalCode.ISSUER_UNVERIFIED,
        RefusalCode.SUBJECT_MISMATCH,
        RefusalCode.SCOPE_MISMATCH,
        RefusalCode.CONDITIONS_UNMET,
        RefusalCode.AUTHORITY_EXPIRED,
        RefusalCode.AUTHORITY_REVOKED,
        RefusalCode.AUTHORITY_UNAVAILABLE,
        RefusalCode.PEER_UNVERIFIED,
        RefusalCode.OBSERVATION_NOT_AUTHORIZED,
        RefusalCode.RIGHTS_MISSING,
        RefusalCode.WRITES_DISABLED,
    ):
        return CandidateRefusalCode.AUTHORITY
    if code in (
        RefusalCode.ROUTE_UNSUPPORTED,
        RefusalCode.RUNTIME_CHANGED,
    ):
        return CandidateRefusalCode.MODE
    if code in (
        RefusalCode.SOURCE_CHANGED,
    ):
        return CandidateRefusalCode.SOURCE
    if code in (
        RefusalCode.CLOSURE_VERSION,
        RefusalCode.CLOSURE_INCOMPLETE,
        RefusalCode.CLOSURE_MISMATCH,
    ):
        return CandidateRefusalCode.CLOSURE
    if code in (
        RefusalCode.SELECTION_MISSING,
        RefusalCode.SELECTION_AMBIGUOUS,
        RefusalCode.SELECTION_FOREIGN,
        RefusalCode.SELECTION_CHANGED,
        RefusalCode.DISPATCH_CHANGED,
    ):
        return CandidateRefusalCode.LOOKUP
    if code in (
        RefusalCode.ROOT_MISMATCH,
    ):
        return CandidateRefusalCode.READINESS
    return CandidateRefusalCode.AUTHORITY


class P3CandidateAuthorityRefusal(AdmissionRefused):
    """``AdmissionRefused`` subclass carrying the exact P3 ``Refusal`` record."""

    def __init__(self, refusal: Refusal, message: str) -> None:
        super().__init__(_map_p3_refusal_to_candidate_code(refusal.code))
        self.p3_refusal = refusal
        self.p3_message = message


@runtime_checkable
class CallerPeerProvider(Protocol):
    """Independent resolver mapping a trusted ``Caller`` or execution UUID to an ``AuthenticatedPeer``."""

    def peer_for_submit(self, caller: Caller, workflow_name: str) -> AuthenticatedPeer | None: ...
    def peer_for_run(self, execution_uuid: str) -> AuthenticatedPeer | None: ...


class StaticCallerPeerProvider:
    """Explicit test-only caller-to-peer resolver."""

    def __init__(
        self,
        *,
        submit_peers: dict[tuple[str, str], AuthenticatedPeer] | None = None,
        run_peers: dict[str, AuthenticatedPeer] | None = None,
        default_peer: AuthenticatedPeer | None = None,
    ) -> None:
        self._submit_peers = dict(submit_peers or {})
        self._run_peers = dict(run_peers or {})
        self._default_peer = default_peer

    def peer_for_submit(self, caller: Caller, workflow_name: str) -> AuthenticatedPeer | None:
        if type(caller) is not Caller or not isinstance(workflow_name, str) or not workflow_name:
            return None
        key = (caller.label, workflow_name)
        if key in self._submit_peers:
            return self._submit_peers[key]
        return self._default_peer

    def peer_for_run(self, execution_uuid: str) -> AuthenticatedPeer | None:
        if not isinstance(execution_uuid, str) or not execution_uuid:
            return None
        if execution_uuid in self._run_peers:
            return self._run_peers[execution_uuid]
        return self._default_peer


class _RefusingMutableGraphLoader:
    """Refuses any attempt to reload from mutable YAML during snapshot execution."""

    def load_workflow(self, name: str, *args: Any, **kwargs: Any) -> Any:
        raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateCaptureAdapter:
    """Adapter binding existing V1 capture, projection, and transport primitives."""

    codec: ContractCodec
    config_store: ConfigStore
    current_source: Callable[[], FrozenJSON]
    worker_identity: Callable[[], str]
    expected_descriptor_sha256: str | Callable[[SelectedJob, str], str]
    expected_source_sha256: str | Callable[[SelectedJob, str], str]
    authorized_caller_label: str = "p3-authorized-caller"
    designated_workflows: frozenset[str] = frozenset({"designated_v1"})
    dispatch_identity: DispatchIdentity | Callable[[], DispatchIdentity] | None = None
    runner_context_builder: Callable[[AdmissionRecord], RunnerContext] | None = None
    record_builder: Callable[..., AdmissionRecord] | None = None
    projection: ActualProjection | None = None
    use_transport: ProtectedUseTransport | None = None
    sealed_variant: bool = False
    pi_containing: bool = False
    continuation_enabled: bool = False
    direct_bypass_allowed: bool = False

    def resolve_expected_descriptor_sha256(self, job: SelectedJob, workflow_name: str) -> str:
        if callable(self.expected_descriptor_sha256):
            return self.expected_descriptor_sha256(job, workflow_name)
        return self.expected_descriptor_sha256

    def resolve_expected_source_sha256(self, job: SelectedJob, workflow_name: str) -> str:
        if callable(self.expected_source_sha256):
            return self.expected_source_sha256(job, workflow_name)
        return self.expected_source_sha256

    def effective_dispatch_identity(self) -> DispatchIdentity:
        if callable(self.dispatch_identity):
            return self.dispatch_identity()
        if isinstance(self.dispatch_identity, DispatchIdentity):
            return self.dispatch_identity
        return DispatchIdentity(
            "00000000-0000-4000-8000-000000000000",
            "00000000-0000-4000-8000-000000000000",
            1,
        )

    def build_descriptor_authority(
        self,
        job: SelectedJob,
        *,
        workflow_name: str,
        caller: Caller | None = None,
        execution_uuid: str | None = None,
    ) -> DescriptorAuthority:
        if type(job) is not SelectedJob:
            raise TypeError("job must be SelectedJob")
        if getattr(job, "route", "external-db-fresh") != "external-db-fresh":
            raise AdmissionRefused(CandidateRefusalCode.MODE)
        if (
            self.sealed_variant
            or self.pi_containing
            or self.continuation_enabled
            or self.direct_bypass_allowed
        ):
            raise AdmissionRefused(CandidateRefusalCode.MODE)
        if workflow_name not in self.designated_workflows:
            raise AdmissionRefused(CandidateRefusalCode.MODE)

        desc_sha = self.resolve_expected_descriptor_sha256(job, workflow_name)
        src_sha = self.resolve_expected_source_sha256(job, workflow_name)
        if (
            job.approved_descriptor_digest != desc_sha
            or job.expected_source_digest != src_sha
        ):
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)

        key_id = (
            job.pre_dispatch_or_running_job.designated_workflow
            if isinstance(job.pre_dispatch_or_running_job, PreDispatchJob)
            else job.pre_dispatch_or_running_job.dispatch.execution_uuid
        )
        job_rev = job.pre_dispatch_or_running_job.job_revision
        caller_label = caller.label if caller is not None else self.authorized_caller_label
        return DescriptorAuthority(
            expected_descriptor_sha256=desc_sha,
            expected_source_sha256=src_sha,
            authorized_caller_label=caller_label,
            receipt_id=f"p3:{key_id}:{job_rev}:{job.selection_revision}",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordedCandidateAuthorityBinding:
    """Immutable audit record of a P3-verified candidate authority binding."""

    selected_job: SelectedJob
    evidence: DecisionEvidence
    descriptor_authority: DescriptorAuthority


class P3CandidateBindings(CandidateBindings):
    """P3-governed ``CandidateBindings`` delegating to real V1 admission primitives.

    Fails closed when ``registry``, ``caller_peer_provider``, or the underlying
    V1 admission primitives (``delegate_bindings`` or ``capture_adapter`` +
    ``session_factory`` + ``installation_verifier`` + ``preparation_verifier``)
    are absent. Never falls back to mutable workflow YAML or unverified state.
    """

    def __init__(
        self,
        *,
        registry: P3AuthorityRegistry | None = None,
        caller_peer_provider: CallerPeerProvider | None = None,
        delegate_bindings: CandidateBindings | None = None,
        session_factory: sessionmaker[Session] | Callable[[], Session] | None = None,
        capture_adapter: CandidateCaptureAdapter | None = None,
        installation_verifier: InstallationVerifier | None = None,
        preparation_verifier: PreparationVerifier | None = None,
        designated_workflows: frozenset[str] | None = None,
        default_dispatch_identity: DispatchIdentity | None = None,
    ) -> None:
        self._registry = registry
        self._caller_peer_provider = caller_peer_provider
        self._delegate_bindings = delegate_bindings
        self._session_factory = session_factory
        self._capture_adapter = capture_adapter
        self._installation_verifier = installation_verifier
        self._preparation_verifier = preparation_verifier
        self._designated_workflows = designated_workflows
        self._default_dispatch_identity = (
            default_dispatch_identity
            if default_dispatch_identity is not None
            else DispatchIdentity(
                "00000000-0000-4000-8000-000000000000",
                "00000000-0000-4000-8000-000000000000",
                1,
            )
        )
        self._run_dispatches: dict[str, DispatchIdentity] = {}
        self._recorded_submit_bindings: dict[str, RecordedCandidateAuthorityBinding] = {}
        self._recorded_run_bindings: dict[str, RecordedCandidateAuthorityBinding] = {}
        self._recorded_windows: dict[str, WindowBinding] = {}
        self._issued_authorities: list[DescriptorAuthority] = []
        self._last_authority: DescriptorAuthority | None = None

    @property
    def recorded_submit_bindings(self) -> dict[str, RecordedCandidateAuthorityBinding]:
        return dict(self._recorded_submit_bindings)

    @property
    def recorded_run_bindings(self) -> dict[str, RecordedCandidateAuthorityBinding]:
        return dict(self._recorded_run_bindings)

    @property
    def recorded_windows(self) -> dict[str, WindowBinding]:
        return dict(self._recorded_windows)

    def register_run_dispatch(
        self,
        execution_uuid: str,
        dispatch_identity: DispatchIdentity,
    ) -> None:
        if not isinstance(execution_uuid, str) or not execution_uuid:
            raise ValueError("execution_uuid must be a non-empty str")
        if type(dispatch_identity) is not DispatchIdentity:
            raise TypeError("dispatch_identity must be DispatchIdentity")
        self._run_dispatches[execution_uuid] = dispatch_identity

    def bind_created_execution(
        self,
        *,
        caller: Caller,
        workflow_name: str,
        current_binding: CurrentBinding,
        actual_creation: ActualCreation,
    ) -> WindowBinding:
        if self._registry is None or self._caller_peer_provider is None:
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        peer = self._caller_peer_provider.peer_for_submit(caller, workflow_name)
        if peer is None:
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        res = self._registry.bind_created(peer, current_binding, actual_creation)
        if isinstance(res, Refusal):
            raise P3CandidateAuthorityRefusal(
                res,
                f"P3 bind_created refused: {res.code.value}",
            )
        window = res.data
        target = current_binding.selected_job.pre_dispatch_or_running_job
        exec_uuid = (
            target.execution_uuid
            if isinstance(target, PreDispatchJob) and target.execution_uuid
            else target.dispatch.execution_uuid
            if isinstance(target, JobKey)
            else actual_creation.window_id
        )
        self._recorded_windows[exec_uuid] = window
        if isinstance(target, JobKey):
            self._run_dispatches[exec_uuid] = target.dispatch
        return window

    def designated(self, workflow_name: str) -> bool:
        if not isinstance(workflow_name, str) or not workflow_name:
            return False
        if self._designated_workflows is not None:
            return workflow_name in self._designated_workflows
        if self._delegate_bindings is not None:
            return bool(self._delegate_bindings.designated(workflow_name))
        if self._capture_adapter is not None:
            return workflow_name in self._capture_adapter.designated_workflows
        return False

    def _build_descriptor_authority(
        self,
        *,
        selected_job: SelectedJob,
        caller: Caller | None,
        workflow_name: str,
        execution_uuid: str | None = None,
    ) -> DescriptorAuthority:
        if self._delegate_bindings is not None:
            if caller is not None:
                auth = self._delegate_bindings.authority_for_submit(caller, workflow_name)
                self._last_authority = auth
                return auth
            if execution_uuid is not None:
                auth = self._delegate_bindings.authority_for_run(execution_uuid)
                self._last_authority = auth
                return auth
        if self._capture_adapter is None:
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        auth = self._capture_adapter.build_descriptor_authority(
            selected_job,
            workflow_name=workflow_name,
            caller=caller,
            execution_uuid=execution_uuid,
        )
        self._last_authority = auth
        return auth

    def authority_for_submit(
        self,
        caller: Caller,
        workflow_name: str,
    ) -> DescriptorAuthority:
        if type(caller) is not Caller or not isinstance(workflow_name, str) or not workflow_name:
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        if self._registry is None or self._caller_peer_provider is None:
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        if not self.designated(workflow_name):
            raise AdmissionRefused(CandidateRefusalCode.MODE)
        if self._capture_adapter is not None:
            if (
                self._capture_adapter.sealed_variant
                or self._capture_adapter.pi_containing
                or self._capture_adapter.continuation_enabled
                or self._capture_adapter.direct_bypass_allowed
            ):
                raise AdmissionRefused(CandidateRefusalCode.MODE)

        peer = self._caller_peer_provider.peer_for_submit(caller, workflow_name)
        if peer is None:
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)

        res = self._registry.for_submit(peer, workflow_name)
        if isinstance(res, Refusal):
            raise P3CandidateAuthorityRefusal(
                res,
                f"P3 authority_for_submit refused: {res.code.value}",
            )

        desc_auth = self._build_descriptor_authority(
            selected_job=res.data,
            caller=caller,
            workflow_name=workflow_name,
        )
        binding = RecordedCandidateAuthorityBinding(
            selected_job=res.data,
            evidence=res.evidence,
            descriptor_authority=desc_auth,
        )
        self._recorded_submit_bindings[workflow_name] = binding
        self._issued_authorities.append(desc_auth)
        return desc_auth

    def authority_for_run(self, execution_uuid: str) -> DescriptorAuthority:
        if not isinstance(execution_uuid, str) or not execution_uuid:
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        if self._registry is None or self._caller_peer_provider is None:
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        peer = self._caller_peer_provider.peer_for_run(execution_uuid)
        if peer is None:
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)

        dispatch_id = self._run_dispatches.get(
            execution_uuid,
            self._capture_adapter.effective_dispatch_identity()
            if self._capture_adapter is not None
            else self._default_dispatch_identity,
        )
        res = self._registry.for_run(peer, execution_uuid, dispatch_id)
        if isinstance(res, Refusal):
            raise P3CandidateAuthorityRefusal(
                res,
                f"P3 authority_for_run refused: {res.code.value}",
            )

        job = res.data
        workflow_name = (
            job.pre_dispatch_or_running_job.designated_workflow
            if isinstance(job.pre_dispatch_or_running_job, PreDispatchJob)
            else next(
                iter(self._recorded_submit_bindings.keys()),
                next(iter(self._capture_adapter.designated_workflows), "designated_v1")
                if self._capture_adapter is not None
                else "designated_v1",
            )
        )
        desc_auth = self._build_descriptor_authority(
            selected_job=job,
            caller=None,
            workflow_name=workflow_name,
            execution_uuid=execution_uuid,
        )
        binding = RecordedCandidateAuthorityBinding(
            selected_job=job,
            evidence=res.evidence,
            descriptor_authority=desc_auth,
        )
        self._recorded_run_bindings[execution_uuid] = binding
        self._issued_authorities.append(desc_auth)
        return desc_auth

    def transport(self, authority: DescriptorAuthority) -> DbAdmissionTransport:
        if type(authority) is not DescriptorAuthority or not any(
            authority == issued for issued in self._issued_authorities
        ):
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        self._last_authority = authority
        writer = self._admission_selection_writer(authority)
        if self._delegate_bindings is not None:
            delegated = self._delegate_bindings.transport(authority)
            if not isinstance(delegated, DbAdmissionTransport):
                raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
            return delegated.with_admission_selection(writer)
        if (
            self._capture_adapter is None
            or self._installation_verifier is None
            or self._preparation_verifier is None
        ):
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        return DbAdmissionTransport(
            codec=self._capture_adapter.codec,
            authority=authority,
            current_source=self._capture_adapter.current_source,
            installation=self._installation_verifier,
            preparation=self._preparation_verifier,
            worker_identity=self._capture_adapter.worker_identity,
            admission_selection=writer,
        )

    def _admission_selection_writer(
        self, authority: DescriptorAuthority,
    ) -> Callable[[AdmissionRecord], dict[str, Any]]:
        """The install-time writer of the job ``authority_for_submit`` selected for ``authority``.

        Every P3 install stores its selection (T5-O2): with no submit selection
        for this authority, or one that does not match the admitted record, the
        writer refuses and the admission rolls back with it.
        """
        selected = next(
            (
                recorded.selected_job
                for recorded in self._recorded_submit_bindings.values()
                if recorded.descriptor_authority == authority
            ),
            None,
        )

        def write(record: AdmissionRecord) -> dict[str, Any]:
            return encode_admitted_selection(selected, authority=authority, record=record)

        return write

    def prepare(
        self,
        descriptor: ApprovedCandidateDescriptor,
        *,
        request: FrozenJSON,
        transaction: Session,
    ) -> AdmissionRecord:
        if type(descriptor) is not ApprovedCandidateDescriptor:
            raise AdmissionRefused(CandidateRefusalCode.TYPE)
        if self._delegate_bindings is not None:
            return self._delegate_bindings.prepare(
                descriptor,
                request=request,
                transaction=transaction,
            )
        if self._capture_adapter is None or self._last_authority is None:
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        records = RawCapture(
            self._capture_adapter.codec,
            self._last_authority,
            self._capture_adapter.config_store,
        ).capture(descriptor, transaction=transaction)
        closure = self._capture_adapter.codec.closure(descriptor, tuple(records))
        load_candidate(
            self._capture_adapter.codec,
            descriptor,
            closure,
            authority=self._last_authority,
            source=self._capture_adapter.current_source(),
        )
        if self._capture_adapter.record_builder is None:
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        return self._capture_adapter.record_builder(
            descriptor,
            closure,
            request=request,
        )

    def bootstrap_snapshot(self, record: AdmissionRecord) -> RunnerContext:
        if self._delegate_bindings is not None:
            if type(record) is not AdmissionRecord:
                raise AdmissionRefused(CandidateRefusalCode.TYPE)
            return self._delegate_bindings.bootstrap_snapshot(record)
        if self._capture_adapter is None or self._last_authority is None:
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        if self._capture_adapter.runner_context_builder is not None:
            return self._capture_adapter.runner_context_builder(record)
        from temper_ai.runner.context import RunnerContext

        return RunnerContext(
            config_store=self._capture_adapter.config_store,
            graph_loader=_RefusingMutableGraphLoader(),  # type: ignore[arg-type]
            llm_providers={},
            memory_service=None,  # type: ignore[arg-type]
        )

    def load_snapshot(
        self,
        record: AdmissionRecord,
        runner_ctx: RunnerContext,
    ) -> tuple[list[Node], WorkflowConfig]:
        if type(record) is not AdmissionRecord:
            raise AdmissionRefused(CandidateRefusalCode.TYPE)
        if self._delegate_bindings is not None:
            return self._delegate_bindings.load_snapshot(record, runner_ctx)
        if self._capture_adapter is None or self._last_authority is None:
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        immutable = record.value()["immutable"]
        descriptor = self._capture_adapter.codec.descriptor(
            immutable["descriptor_json"].encode("utf-8"),
            self._last_authority,
        )
        closure = self._capture_adapter.codec.closure(
            descriptor,
            tuple(
                self._capture_adapter.codec.raw_record(canonical_bytes(raw))
                for raw in immutable["raw_records"]
            ),
        )
        nodes, workflow, _ = load_candidate(
            self._capture_adapter.codec,
            descriptor,
            closure,
            authority=self._last_authority,
            source=self._capture_adapter.current_source(),
        )
        return nodes, workflow

    def bind_context(
        self,
        record: AdmissionRecord,
        context: ExecutionContext,
    ) -> ExecutionContext:
        if type(record) is not AdmissionRecord:
            raise AdmissionRefused(CandidateRefusalCode.TYPE)
        if self._delegate_bindings is not None:
            return self._delegate_bindings.bind_context(record, context)
        if (
            self._capture_adapter is None
            or self._session_factory is None
            or self._last_authority is None
            or self._capture_adapter.projection is None
            or self._capture_adapter.use_transport is None
        ):
            raise AdmissionRefused(CandidateRefusalCode.AUTHORITY)
        nodes, workflow = self.load_snapshot(record, None)  # type: ignore[arg-type]
        if not nodes:
            raise AdmissionRefused(CandidateRefusalCode.GRAPH)
        use = CandidateUse(
            codec=self._capture_adapter.codec,
            record=record,
            authority=self._last_authority,
            projection=self._capture_adapter.projection,
            transport=self._capture_adapter.use_transport,
            workflow=workflow,
        )
        return replace(
            context,
            admission=use.binding((nodes[0].name,)),
            admission_hooks=use,
            admission_required=True,
        )


__all__ = [
    "CallerPeerProvider",
    "CandidateCaptureAdapter",
    "P3CandidateAuthorityRefusal",
    "P3CandidateBindings",
    "RecordedCandidateAuthorityBinding",
    "StaticCallerPeerProvider",
]

