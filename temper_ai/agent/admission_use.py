"""Candidate-only checks at consumers, not an admission authority or a loader.

V1 supplies the T1 projector and T2 protected transaction/checkpoint adapter.
Neither Python constructors nor test adapters establish caller/custody authority.
No provider work belongs in a protected claim callback.
"""
from __future__ import annotations

import hashlib
import inspect
import os
import stat
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from threading import RLock
from typing import TYPE_CHECKING, Any, NoReturn, Protocol, TypeVar, cast

from temper_ai.agent.base import AgentABC
from temper_ai.config.admission_contract import (
    AdmissionContext,
    AdmissionRecord,
    AdmissionRefused,
    CandidateInvocationBinding,
    ContractCodec,
    DescriptorAuthority,
    DigestDomain,
    DispatchIdentity,
    FrozenJSON,
    OpenedRoot,
    RefusalCode,
    RootReadiness,
    canonical_bytes,
    check_readiness_transition,
    digest,
)
from temper_ai.shared.types import ExecutionContext, NodeResult, Status

if TYPE_CHECKING:
    from temper_ai.stage.models import WorkflowConfig

T = TypeVar("T")


def refuse(code: RefusalCode) -> NoReturn:
    raise AdmissionRefused(code) from None


class ActualProjection(Protocol):
    """T1 owns complete field projection, including defaults and typed frozensets."""

    def graph(self, workflow: object, nodes: list[Any]) -> FrozenJSON: ...
    def node(self, config: object) -> FrozenJSON: ...
    def agent(self, config: dict) -> FrozenJSON: ...


@dataclass(frozen=True)
class VerifiedPreparation:
    """Adapter receipt, not a capability. T2 verifies durable checkpoint origin."""

    result: NodeResult
    checkpoint_sha256: str
    receipts: tuple[RootReadiness, ...]


class ProtectedUseTransport(Protocol):
    """T2 keeps the current-generation lock across action, including O_EXCL.

    The action receives a verified current record and its transaction. Exceptions
    roll back metadata, NEVER undo an already-created filesystem claim.
    """

    def current_generation(self, binding: CandidateInvocationBinding,
                           action: Callable[[AdmissionRecord, object], T]) -> T: ...
    def verify_preparation(self, binding: CandidateInvocationBinding, result: NodeResult,
                           checkpoint_service: object, *, transaction: object) -> VerifiedPreparation: ...
    def bind_root_readiness(self, current: AdmissionRecord, receipt: RootReadiness,
                           *, verified_preparation: object, transaction: object) -> AdmissionRecord: ...


def _declared_attribute(subject: object, name: str, default: object = None) -> Any:
    """Do not let a legacy object's dynamic missing-attribute fallback opt in."""
    try:
        inspect.getattr_static(subject, name)
    except AttributeError:
        return default
    return getattr(subject, name)


def hooks_for(context: object, subject: object = None) -> CandidateUse | None:
    """Missing/forged context cannot turn an already-bound consumer into legacy."""
    hooks = _declared_attribute(context, "admission_hooks")
    binding = _declared_attribute(context, "admission")
    marker = _declared_attribute(subject, "_candidate_use")
    designated = _declared_attribute(context, "admission_required", False)
    if type(designated) is not bool:
        refuse(RefusalCode.TYPE)
    if not (designated or hooks is not None or binding is not None or marker is not None):
        return None
    if type(hooks) is not CandidateUse or type(binding) is not CandidateInvocationBinding:
        refuse(RefusalCode.MISSING)
    if marker is not None and marker is not hooks:
        refuse(RefusalCode.MISSING)
    hooks.check_binding(binding)
    return hooks


def stat_identity(path: str, fd: int) -> FrozenJSON:
    value = os.fstat(fd)
    return FrozenJSON(canonical_bytes({
        "path": path, "device": value.st_dev, "inode": value.st_ino,
        "uid": value.st_uid, "gid": value.st_gid, "mode": stat.S_IMODE(value.st_mode),
    }))


class CandidateUse:
    """One running generation. Expectations own bytes; actual objects stay actual."""

    def __init__(self, *, codec: ContractCodec, record: AdmissionRecord,
                 authority: DescriptorAuthority, projection: ActualProjection,
                 transport: ProtectedUseTransport, workflow: WorkflowConfig) -> None:
        self.codec, self.authority = codec, authority
        self.record = codec.record(record.wire, authority)
        value = self.record.value()
        if value["dispatch"]["phase"] != "running":
            refuse(RefusalCode.GENERATION)
        immutable = value["immutable"]
        self.descriptor = codec.descriptor(immutable["descriptor_json"].encode(), authority)
        self.closure = codec.closure(self.descriptor, tuple(
            codec.raw_record(canonical_bytes(r)) for r in immutable["raw_records"]))
        self.graph_sha256 = immutable["effective_graph_sha256"]
        self.dispatch = DispatchIdentity(self.descriptor.value()["execution_uuid"],
                                         value["dispatch"]["dispatch_nonce"],
                                         value["dispatch"]["running_attempt"])
        self.projection, self.transport, self.workflow = projection, transport, workflow
        self._nodes: list[Any] | None = None
        self._objects: dict[tuple[str, ...], Any] = {}
        self._results: dict[tuple[str, ...], tuple[NodeResult, bytes]] = {}
        self._invoked: set[tuple[str, ...]] = set()
        self._lock = RLock()

    def binding(self, path: tuple[str, ...]) -> CandidateInvocationBinding:
        d = self.descriptor.value()
        node = next((n for n in d["graph"]["nodes"] if tuple(n["path"]) == path), None)
        if node is None:
            refuse(RefusalCode.GRAPH)
        position = next((p for p in d["positions"] if tuple(p["node_path"]) == path), None)
        ready = next((r for r in self.record.value()["readiness"]
                      if position is not None and r["position_id"] == position["position_id"]), None)
        return CandidateInvocationBinding(
            self.descriptor, self.closure, self.graph_sha256, self.dispatch, path,
            position["position_id"] if position else None,
            FrozenJSON(node["node_json"].encode()),
            FrozenJSON(node["factory"]["config_json"].encode()) if node["factory"] else None,
            self.codec.readiness(canonical_bytes(ready)) if ready else None,
        )

    def check_binding(self, binding: CandidateInvocationBinding) -> None:
        if type(binding) is not CandidateInvocationBinding or binding != self.binding(binding.node_path):
            refuse(RefusalCode.PROTECTED)

    def check_context(self, binding: CandidateInvocationBinding, context: AdmissionContext,
                      *, parent: bool = False) -> None:
        self.check_binding(binding)
        expected_path = binding.node_path[:-1] if parent else binding.node_path
        d = self.descriptor.value()
        if (context.admission != binding or context.run_id != d["execution_uuid"]
                or context.node_path != ".".join(expected_path)
                or context.workspace_path != d["workspace_path"]):
            refuse(RefusalCode.POSITION)

    def check_graph(self, *, binding: CandidateInvocationBinding, actual_graph: FrozenJSON) -> None:
        self.check_binding(binding)
        if (actual_graph.wire != canonical_bytes(self.descriptor.value()["graph"])
                or digest(DigestDomain.GRAPH, actual_graph.wire) != self.graph_sha256):
            refuse(RefusalCode.GRAPH)

    def _metadata(self, actual: object, expected: FrozenJSON) -> None:
        values = actual if type(actual) is dict else vars(actual)
        if "_KNOWN_FIELDS" in values:
            members = values["_KNOWN_FIELDS"]
            if (type(members) is not frozenset or any(type(v) is not str for v in members)
                    or sorted(members) != expected.value().get("_KNOWN_FIELDS")):
                refuse(RefusalCode.FIELDS)
        elif "_KNOWN_FIELDS" in expected.value():
            refuse(RefusalCode.FIELDS)

    def _walk(self, nodes: list[Any], prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
        from temper_ai.stage.agent_node import AgentNode
        from temper_ai.stage.stage_node import StageNode

        if type(nodes) is not list:
            refuse(RefusalCode.GRAPH)
        result: dict[tuple[str, ...], Any] = {}
        seen: set[int] = set()

        def visit(children: list[Any], parent: tuple[str, ...]) -> None:
            if type(children) is not list:
                refuse(RefusalCode.GRAPH)
            for node in children:
                if (type(node) not in (AgentNode, StageNode) or id(node) in seen
                        or node.name != node.config.name or type(node.name) is not str):
                    refuse(RefusalCode.GRAPH)
                seen.add(id(node))
                path = (*parent, node.name)
                if path in result or type(node.config._KNOWN_FIELDS) is not frozenset:
                    refuse(RefusalCode.FIELDS)
                self._metadata(node.config, self.binding(path).expected_node)
                result[path] = node
                if type(node) is StageNode:
                    visit(node.child_nodes, path)
        visit(nodes, prefix)
        return result

    def enter_graph(self, nodes: list[Any], context: ExecutionContext, *, input_data: dict,
                    initial_outputs: object, resume_metadata: object,
                    workflow_outputs: object, is_workflow: bool) -> None:
        binding = cast(AdmissionContext, context).admission
        if binding is None:
            refuse(RefusalCode.MISSING)
        if (initial_outputs is not None or resume_metadata is not None
                or getattr(context, "restore", None) is not None or getattr(context, "run_only", None) is not None):
            refuse(RefusalCode.MODE)
        d = self.descriptor.value()
        if context.run_id != d["execution_uuid"] or context.workspace_path != d["workspace_path"]:
            refuse(RefusalCode.POSITION)
        if self._nodes is None:
            if context.node_path or not is_workflow:
                refuse(RefusalCode.GRAPH)
            if canonical_bytes(input_data) != d["metadata_inputs_json"].encode():
                refuse(RefusalCode.PROTECTED)
            self._nodes = nodes
        elif not context.node_path or is_workflow:
            refuse(RefusalCode.MODE)
        objects = self._walk(self._nodes)
        self._metadata(self.workflow, FrozenJSON(d["graph"]["workflow_json"].encode()))
        actual = self.projection.graph(self.workflow, self._nodes)
        self.check_graph(binding=binding, actual_graph=actual)
        if self._objects and any(objects.get(p) is not n for p, n in self._objects.items()):
            refuse(RefusalCode.GRAPH)
        self._objects = objects
        if context.node_path:
            parent = objects.get(tuple(context.node_path.split(".")))
            if parent is None or nodes is not getattr(parent, "child_nodes", None):
                refuse(RefusalCode.GRAPH)
            self.check_context(binding, cast(AdmissionContext, context))
        # Pin output policy too: the executor consumes this separate argument.
        if is_workflow and canonical_bytes(workflow_outputs) != canonical_bytes(self.workflow.outputs):
            refuse(RefusalCode.GRAPH)
        for node in objects.values():
            node.__dict__["_candidate_use"] = self

    def before_node(self, node: Any, context: ExecutionContext) -> CandidateInvocationBinding:
        path = (*tuple(filter(None, context.node_path.split("."))), node.name)
        if self._nodes is None or self._objects.get(path) is not node:
            refuse(RefusalCode.GRAPH)
        binding = self.binding(path)
        # Check the complete current graph again before policy/input/dependency reads.
        objects = self._walk(self._nodes)
        if set(objects) != set(self._objects) or any(objects[p] is not n for p, n in self._objects.items()):
            refuse(RefusalCode.GRAPH)
        self.check_graph(binding=binding, actual_graph=self.projection.graph(self.workflow, self._nodes))
        if self.projection.node(node.config) != binding.expected_node:
            refuse(RefusalCode.GRAPH)
        current = cast(AdmissionContext, context).admission
        if current is None:
            refuse(RefusalCode.MISSING)
        self.check_binding(current)
        parent_path = tuple(context.node_path.split(".")) if context.node_path else ()
        if parent_path and current.node_path not in (parent_path, path):
            refuse(RefusalCode.POSITION)
        if context.run_id != self.dispatch.execution_uuid or context.workspace_path != self.descriptor.value()["workspace_path"]:
            refuse(RefusalCode.POSITION)
        return binding

    def begin_invocation(self, binding: CandidateInvocationBinding) -> None:
        with self._lock:
            if binding.node_path in self._invoked:
                refuse(RefusalCode.MODE)
            self._invoked.add(binding.node_path)

    def node_context(self, node: Any, context: ExecutionContext) -> ExecutionContext:
        binding = self.before_node(node, context)
        changes: dict[str, Any] = {"admission": binding}
        return replace(context, **changes)  # T1 owns the production context field.

    def invocation(self, *, binding: CandidateInvocationBinding, actual_context: AdmissionContext,
                   actual_node: FrozenJSON, actual_agent: FrozenJSON | None) -> CandidateInvocationBinding:
        self.check_context(binding, actual_context)
        if actual_node != binding.expected_node or actual_agent != binding.expected_agent:
            refuse(RefusalCode.FIELDS)
        # New owned immutable values, not aliases of the caller's dicts.
        return self.binding(binding.node_path)

    def before_factory(self, node: Any, context: ExecutionContext, factory: object,
                       agent_class: object) -> tuple[dict, ExecutionContext]:
        from temper_ai.agent import create_agent
        from temper_ai.agent.script_agent import ScriptAgent
        from temper_ai.agent.single_call_agent import SingleCallAgent

        binding = self.before_node(node, context)
        expected_class = {"script": ScriptAgent, "single_call": SingleCallAgent}.get(node.agent_config.get("type"))
        if factory is not create_agent or agent_class is not expected_class or expected_class is None:
            refuse(RefusalCode.FIELDS)
        expected = next(n for n in self.descriptor.value()["graph"]["nodes"] if tuple(n["path"]) == binding.node_path)
        if expected["factory"]["class_name"] != f"{expected_class.__module__}.{expected_class.__name__}":
            refuse(RefusalCode.FIELDS)
        if binding.expected_agent is None:
            refuse(RefusalCode.FIELDS)
        self._metadata(node.agent_config, binding.expected_agent)
        config = deepcopy(node.agent_config)
        changes: dict[str, Any] = {"admission": binding, "node_path": ".".join(binding.node_path),
                                   "agent_name": config.get("name", "")}
        ctx = replace(context, **changes)
        self.invocation(binding=binding, actual_context=cast(AdmissionContext, ctx),
                        actual_node=self.projection.node(node.config), actual_agent=self.projection.agent(config))
        self.begin_invocation(binding)
        return config, ctx

    def after_factory(self, node: Any, agent: AgentABC, context: ExecutionContext, intended: type[AgentABC]) -> None:
        binding = cast(AdmissionContext, context).admission
        if binding is None or type(agent) is not intended or agent.name != agent.config.get("name"):
            refuse(RefusalCode.FIELDS)
        if binding.expected_agent is None:
            refuse(RefusalCode.FIELDS)
        self._metadata(agent.config, binding.expected_agent)
        self.invocation(binding=binding, actual_context=cast(AdmissionContext, context),
                        actual_node=self.projection.node(node.config), actual_agent=self.projection.agent(agent.config))
        agent.__dict__["_candidate_use"] = self

    def check_script(self, *, binding: CandidateInvocationBinding, template: bytes, variables: FrozenJSON) -> None:
        self.check_binding(binding)
        script = next((s for s in self.descriptor.value()["scripts"] if tuple(s["node_path"]) == binding.node_path), None)
        if (script is None or type(template) is not bytes
                or script["template_utf8"].encode() != template
                or hashlib.sha256(template).hexdigest() != script["template_sha256"]
                or variables.wire != script["variables_json"].encode()):
            refuse(RefusalCode.FIELDS)

    def script_inputs(self, agent: Any, context: ExecutionContext, template: object, variables: dict) -> dict:
        binding = cast(AdmissionContext, context).admission
        if binding is None:
            refuse(RefusalCode.MISSING)
        self.check_context(binding, cast(AdmissionContext, context))
        if type(template) is not str:
            refuse(RefusalCode.FIELDS)
        if (binding.expected_agent is None or self.projection.agent(agent.config) != binding.expected_agent
                or agent.name != agent.config.get("name")
                or agent.strict_undefined is not bool(agent.config.get("strict_undefined", False))):
            refuse(RefusalCode.FIELDS)
        self._metadata(agent.config, binding.expected_agent)
        frozen = FrozenJSON(canonical_bytes(variables))
        self.check_script(binding=binding, template=template.encode("utf-8"), variables=frozen)
        return frozen.value()

    def returned(self, node: Any, context: ExecutionContext, result: NodeResult) -> None:
        binding = self.before_node(node, context)
        if any(tuple(p["preparation_path"]) == binding.node_path for p in self.descriptor.value()["positions"]):
            # Only the scheduler calls here with the actual returned NodeResult.
            with self._lock:
                if binding.node_path in self._results:
                    refuse(RefusalCode.READINESS)
                self._results[binding.node_path] = (result, canonical_bytes(result.structured_output))

    def checkpointed(self, node: Any, context: ExecutionContext, result: NodeResult) -> None:
        binding = self.before_node(node, context)
        positions = [p for p in self.descriptor.value()["positions"] if tuple(p["preparation_path"]) == binding.node_path]
        if not positions or result.status is not Status.COMPLETED:
            return
        with self._lock:
            saved = self._results.get(binding.node_path)
            if (saved is None or saved[0] is not result or saved[1] != canonical_bytes(result.structured_output)
                    or context.checkpoint_service is None):
                refuse(RefusalCode.READINESS)

            def bind(current: AdmissionRecord, transaction: object) -> AdmissionRecord:
                current = self._current(current)
                verified = self.transport.verify_preparation(binding, result, context.checkpoint_service, transaction=transaction)
                if (type(verified) is not VerifiedPreparation or verified.result is not result
                        or type(verified.receipts) is not tuple
                        or sorted(r.value()["position_id"] for r in verified.receipts) != sorted(p["position_id"] for p in positions)):
                    refuse(RefusalCode.READINESS)
                for receipt in verified.receipts:
                    receipt = self.codec.readiness(receipt.wire)
                    if (receipt.value()["checkpoint_sha256"] != verified.checkpoint_sha256
                            or not receipt.value()["durable"]):
                        refuse(RefusalCode.READINESS)
                    after = self.transport.bind_root_readiness(current, receipt,
                                                               verified_preparation=verified, transaction=transaction)
                    after = self.codec.record(after.wire, self.authority)
                    check_readiness_transition(current, after, receipt)
                    current = after
                return current
            # Local readiness advances only after the protected transaction commits.
            self.record = self.transport.current_generation(binding, bind)

    def _current(self, current: AdmissionRecord) -> AdmissionRecord:
        checked = self.codec.record(current.wire, self.authority)
        a, b = checked.value(), self.record.value()
        if a["immutable_sha256"] != b["immutable_sha256"] or canonical_bytes(a["dispatch"]) != canonical_bytes(b["dispatch"]):
            refuse(RefusalCode.GENERATION)
        # No stale/regressed or replaced readiness; other positions may have advanced.
        for receipt in b["readiness"]:
            if receipt not in a["readiness"]:
                refuse(RefusalCode.READINESS)
        return checked

    def check_native_config(self, binding: CandidateInvocationBinding, config: dict) -> FrozenJSON:
        if binding.expected_agent is None:
            refuse(RefusalCode.FIELDS)
        self._metadata(config, binding.expected_agent)
        actual = self.projection.agent(config)
        if actual != binding.expected_agent:
            refuse(RefusalCode.FIELDS)
        return actual

    def authorize_and_claim(self, *, binding: CandidateInvocationBinding, root: OpenedRoot,
                            actual_config: FrozenJSON, actual_context: AdmissionContext,
                            claim: Callable[[], T]) -> T:
        self.check_context(binding, actual_context)
        if actual_config != binding.expected_agent or binding.readiness is None:
            refuse(RefusalCode.READINESS)

        def checked_claim(current: AdmissionRecord, transaction: object) -> T:
            checked = self._current(current)
            self.check_context(binding, actual_context)
            receipt = binding.readiness
            if receipt is None or receipt.value() not in checked.value()["readiness"]:
                refuse(RefusalCode.READINESS)
            ready = receipt.value()
            position = next(p for p in self.descriptor.value()["positions"] if p["position_id"] == binding.position_id)
            policy = position["root_policy"]
            if (not ready["durable"] or policy is None or os.geteuid() != policy["worker_euid"]
                    or stat_identity(policy["path"], root.fd).wire != canonical_bytes(ready["root"])
                    or not stat.S_ISDIR(os.fstat(root.fd).st_mode)
                    or [v.value() for v in root.traversal] != ready["parents"]):
                refuse(RefusalCode.READINESS)
            # Native attempt validates required file fds just before this callback;
            # callback performs ONLY its existing exclusive claim allocation.
            return claim()
        return self.transport.current_generation(binding, checked_claim)
