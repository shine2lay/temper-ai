"""T3 isolated consumer proofs, NOT T1/T2 integration or durable custody proof.

Expectations below are literal inventories. FakeProjector measures actual objects;
its output NEVER constructs the descriptor's expected answer. FakeTransport is a
locked, in-memory protocol adapter, deliberately not a database receipt.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from dataclasses import dataclass, fields, replace
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

import pytest

from temper_ai.agent import AGENT_TYPES
from temper_ai.agent.admission_use import CandidateUse, VerifiedPreparation
from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.agent.single_call_agent import SingleCallAgent, _Attempt
from temper_ai.config.admission_contract import (
    AdmissionRecord,
    AdmissionRefused,
    CandidateInvocationBinding,
    ContractCodec,
    DescriptorAuthority,
    FrozenJSON,
    RefusalCode,
    RootReadiness,
)
from temper_ai.shared.types import ExecutionContext, NodeResult, Status
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.models import NodeConfig, WorkflowConfig
from temper_ai.stage.stage_node import StageNode

ROOT = Path(__file__).resolve().parents[2]
WIRE = ROOT / "tests/test_config/fixtures/candidate_admission_v1"
RUN = "00000000-0000-4000-8000-000000000001"
NONCE = "00000000-0000-4000-8000-000000000003"
# Independent literal complete defaults, including the dataclass metadata field.
NODE_KEYS = "name type agent strategy strategy_config agents nodes ref depends_on condition loop_to max_loops loop_condition on_max_loops run_after_failure undoes on_failure required_files renamed_from timeout_seconds gate skip_policies input_map inputs outputs task_template system_prompt role model provider temperature max_tokens token_budget tools memory".split()
WORKFLOW_KEYS = "name description version nodes inputs outputs safety memory defaults on_failure notify starts_runs".split()
NODE_DEFAULT = {
    "name": "", "type": "agent", "agent": None, "strategy": None, "strategy_config": {}, "agents": None,
    "nodes": None, "ref": None, "depends_on": [], "condition": None, "loop_to": None,
    "max_loops": 1, "loop_condition": None, "on_max_loops": "silent", "run_after_failure": False,
    "undoes": None, "on_failure": None, "required_files": None, "renamed_from": None,
    "timeout_seconds": None, "gate": False, "skip_policies": None, "input_map": None,
    "inputs": None, "outputs": None, "task_template": None, "system_prompt": None, "role": None,
    "model": None, "provider": None, "temperature": None, "max_tokens": None,
    "token_budget": None, "tools": None, "memory": None, "_KNOWN_FIELDS": sorted(NODE_KEYS),
}
WORKFLOW_DEFAULT = {"name": "fixture", "description": "", "version": "1.0", "nodes": [],
                    "inputs": None, "outputs": None, "safety": None, "memory": None, "defaults": None,
                    "on_failure": None, "notify": None, "starts_runs": False, "_KNOWN_FIELDS": sorted(WORKFLOW_KEYS)}


def dump(value):
    # Fixtures use integers only; independent encoder, not production projection.
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def hashed(domain, data):
    return hashlib.sha256(b"temper-admission/v1\0" + domain.encode() + b"\0" + data).hexdigest()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def literal_node(name, **changes):
    return {**copy.deepcopy(NODE_DEFAULT), "name": name, **copy.deepcopy(changes)}


def measure(path):
    value = os.stat(path, follow_symlinks=False)
    return {"path": str(path), "device": value.st_dev, "inode": value.st_ino,
            "uid": value.st_uid, "gid": value.st_gid, "mode": stat.S_IMODE(value.st_mode)}


class FakeProjector:
    """Synthetic T1 protocol: measures dataclass fields, never expected literals."""

    def value(self, value):
        if isinstance(value, (NodeConfig, WorkflowConfig)):
            return {f.name: self.value(getattr(value, f.name)) for f in fields(value)}
        if type(value) is frozenset:
            return sorted(value)
        if type(value) is dict:
            return {k: self.value(v) for k, v in value.items()}
        if type(value) is list:
            return [self.value(v) for v in value]
        return value

    def node(self, config):
        return FrozenJSON(dump(self.value(config)))

    def agent(self, config):
        return FrozenJSON(dump(self.value(config)))

    def graph(self, workflow, nodes):
        inventory = []

        def walk(children, parent):
            for node in children:
                path = [*parent, node.name]
                factory = None
                if type(node) is AgentNode:
                    cls = AGENT_TYPES[node.agent_config["type"]]
                    factory = {"type": node.agent_config["type"], "class_name": f"{cls.__module__}.{cls.__name__}",
                               "config_json": self.agent(node.agent_config).wire.decode()}
                inventory.append({"path": path, "node_json": self.node(node.config).wire.decode(), "factory": factory})
                if type(node) is StageNode:
                    walk(node.child_nodes, path)
        walk(nodes, [])
        return FrozenJSON(dump({"workflow_json": self.node(workflow).wire.decode(), "nodes": inventory}))


class FakeEvents:
    def __init__(self):
        self.count = 0
        self.script_starts = 0

    def record(self, kind, **kwargs):
        self.count += 1
        if kwargs.get("data", {}).get("type") == "script":
            self.script_starts += 1
        return str(self.count)

    def update_event(self, *args, **kwargs):
        pass

    def record_script_log_rows(self, *args, **kwargs):
        pass


class FakeCheckpoint:
    def __init__(self):
        self.results = {}

    def save_node_completed(self, path, result):
        self.results[path] = result


class FakeTools:
    def __init__(self):
        self.calls = 0
        self.policy_engine = None

    def execute(self, *args, **kwargs):
        self.calls += 1
        return SimpleNamespace(result='{"prepared":true}', success=True, error=None, metadata={})

    def track_usage(self, *args):
        pass


class FakeTransport:
    """Synthetic serialization and identity witness; no actual durable database."""

    def __init__(self, record, receipts):
        self.record, self.receipts = record, receipts
        self.lock = RLock()
        self.inside = False
        self.claims = 0
        self.mutate = None
        self.fail_commit = False

    def current_generation(self, binding, action):
        with self.lock:
            before = self.record
            self.inside = True
            try:
                if self.mutate:
                    self.mutate()
                result = action(self.record, self)
                if self.fail_commit:
                    raise RuntimeError("synthetic_commit_failed")
                return result
            except BaseException:
                self.record = before
                raise
            finally:
                self.inside = False

    def verify_preparation(self, binding, result, checkpoint_service, *, transaction):
        assert transaction is self and self.inside
        assert checkpoint_service.results.get(".".join(binding.node_path)) is result
        return VerifiedPreparation(result, "a" * 64, self.receipts)

    def bind_root_readiness(self, current, receipt, *, verified_preparation, transaction):
        assert transaction is self and self.inside
        value = current.value()
        value["readiness"].append(receipt.value())
        self.record = AdmissionRecord(dump(value))
        return self.record


@dataclass
class TestContext(ExecutionContext):
    __test__ = False
    admission: CandidateInvocationBinding | None = None
    admission_hooks: object = None
    admission_required: bool = False


class Rig:
    def __init__(self, tmp_path, *, nested=False, native_metadata=False):
        self.base = tmp_path
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.root = tmp_path / "out"
        self.root.mkdir(mode=0o700)
        self.prompt = self.root / "input.txt"
        self.pricing = self.root / "prices.json"
        # Owned synthetic bytes, never an actual prompt/config/key/model body.
        self.prompt.write_bytes(b"synthetic fixture\n")
        self.pricing.write_bytes(b"{}")
        self.prompt.chmod(0o600)
        self.pricing.chmod(0o600)
        self.fixed = {"output_root": str(self.root), "slot": "A1", "prompt_path": str(self.prompt),
                      "prompt_bytes": 18, "prompt_sha256": sha(self.prompt.read_bytes()),
                      "pricing_path": str(self.pricing), "pricing_sha256": sha(b"{}")}
        self.script = {"name": "prepare", "type": "script", "script_template": "printf metadata", "timeout_seconds": 30}
        self.native = {"name": "call", "type": "single_call", "single_call": copy.deepcopy(self.fixed)}
        if native_metadata:
            self.native["_KNOWN_FIELDS"] = ["name", "single_call", "type"]
        p = literal_node("prepare", agent="prepare", input_map={})
        c = literal_node("call", agent="call", depends_on=["prepare"], input_map={})
        leaves = [p, c]
        top = [literal_node("outer", type="stage", nodes=leaves)] if nested else leaves
        workflow = {**copy.deepcopy(WORKFLOW_DEFAULT), "nodes": copy.deepcopy(top)}
        prefix = ["outer"] if nested else []
        inventory = []
        if nested:
            inventory.append({"path": ["outer"], "node_json": dump(top[0]).decode(), "factory": None})
        for name, node, config, cls in (("prepare", p, self.script, ScriptAgent), ("call", c, self.native, SingleCallAgent)):
            inventory.append({"path": [*prefix, name], "node_json": dump(node).decode(),
                              "factory": {"type": config["type"], "class_name": f"{cls.__module__}.{cls.__name__}",
                                          "config_json": dump(config).decode()}})
        d = json.loads((WIRE / "descriptor.json").read_bytes())
        d["graph"] = {"workflow_json": dump(workflow).decode(), "nodes": inventory}
        d["workspace_path"] = str(tmp_path)
        d["metadata_inputs_json"] = "{}"
        d["source"]["field_sets"]["workflow"] = sorted(workflow)
        d["source"]["field_sets"]["node"] = sorted(p)
        d["source"]["field_sets"]["native"] = sorted(self.fixed)
        policy = {"path": str(self.root), "permitted_parent": str(tmp_path), "custody_receipt_id": "synthetic-only",
                  "worker_label": "synthetic-worker", "mount_label": "synthetic", "creator_uid": os.getuid(),
                  "creator_gid": os.getgid(), "worker_euid": os.geteuid(), "directory_mode": 0o700,
                  "file_mode": 0o600, "lifetime_label": "test-only"}
        d["positions"][0].update(node_path=[*prefix, "call"], preparation_path=[*prefix, "prepare"],
                                 agent_config_json=dump(self.native).decode(), root_policy=policy)
        d["scripts"] = [{"node_path": [*prefix, "prepare"], "template_utf8": self.script["script_template"],
                         "template_sha256": sha(self.script["script_template"].encode()),
                         "variables_json": dump({"workspace_path": str(tmp_path), "run_id": RUN}).decode()}]
        self.authority = DescriptorAuthority(hashed("descriptor", dump(d)), hashed("source", dump(d["source"])),
                                             "synthetic-author", "synthetic-receipt")
        self.codec = ContractCodec((ROOT / "docs/schemas/candidate-admission-v1.schema.json").read_bytes())
        raw = [json.loads((WIRE / f"raw-{n}.json").read_bytes()) for n in ("call", "prepare", "workflow")]
        layout = json.loads((WIRE / "record-layout.json").read_bytes())
        immutable = layout["immutable"]
        immutable.update(descriptor_json=dump(d).decode(), descriptor_sha256=self.authority.expected_descriptor_sha256,
                         effective_graph_sha256=hashed("graph", dump(d["graph"])), raw_records=raw)
        layout["immutable_sha256"] = hashed("immutable", dump(immutable))
        layout["dispatch"] = {"phase": "running", "dispatch_nonce": NONCE, "previous_nonce": "00000000-0000-4000-8000-000000000002",
                              "running_attempt": 1, "worker_label": "synthetic-worker"}
        record = self.codec.record(dump(layout), self.authority)
        parents = list(reversed(self.root.parents))
        receipt = {"format": "candidate-root-readiness/v1", "preparation_path": [*prefix, "prepare"],
                   "position_id": "p01", "descriptor_sha256": self.authority.expected_descriptor_sha256,
                   "graph_sha256": immutable["effective_graph_sha256"], "execution_uuid": RUN, "dispatch_nonce": NONCE,
                   "running_attempt": 1, "checkpoint_sha256": "a" * 64, "root": measure(self.root),
                   "parents": [measure(p) for p in parents if str(p) != "/"],
                   "files": [{"stat": measure(p), "length": p.stat().st_size, "sha256": sha(p.read_bytes())}
                             for p in (self.prompt, self.pricing)], "durable": True}
        self.receipt = self.codec.readiness(dump(receipt))
        self.transport = FakeTransport(record, (self.receipt,))
        # Actual model construction, deliberately separate from the literal projection.
        if native_metadata:
            self.native["_KNOWN_FIELDS"] = frozenset(self.native["_KNOWN_FIELDS"])
        prepare = AgentNode(NodeConfig("prepare", agent="prepare", input_map={}), copy.deepcopy(self.script))
        call = AgentNode(NodeConfig("call", agent="call", depends_on=["prepare"], input_map={}), copy.deepcopy(self.native))
        self.leaves = [prepare, call]
        if nested:
            stage = StageNode(NodeConfig("outer", type="stage", nodes=[prepare.config, call.config]), self.leaves)
            self.nodes = [stage]
        else:
            self.nodes = self.leaves
        self.workflow = WorkflowConfig("fixture", nodes=[n.config for n in self.nodes])
        self.use = CandidateUse(codec=self.codec, record=record, authority=self.authority,
                                projection=FakeProjector(), transport=self.transport, workflow=self.workflow)
        self.events, self.tools, self.cp = FakeEvents(), FakeTools(), FakeCheckpoint()
        self.ctx = TestContext(RUN, "fixture", "", "", self.events, self.tools, workspace_path=str(tmp_path),
                               checkpoint_service=self.cp, admission=self.use.binding(("outer",) if nested else ("prepare",)),
                               admission_hooks=self.use, admission_required=True)
        self.prefix = prefix

    def execute(self, **kwargs):
        return execute_graph(self.nodes, {}, self.ctx, graph_name="fixture", is_workflow=True, **kwargs)

    def prepare_only(self):
        self.use.enter_graph(self.nodes, self.ctx, input_data={}, initial_outputs=None, resume_metadata=None,
                             workflow_outputs=None, is_workflow=True)
        parent = replace(self.ctx, node_path=".".join(self.prefix))
        node = self.leaves[0]
        result = NodeResult(Status.COMPLETED, output="metadata", structured_output={"prepared": True})
        self.use.returned(node, parent, result)
        self.cp.save_node_completed(".".join([*self.prefix, "prepare"]), result)
        self.use.checkpointed(node, parent, result)
        return result

    def native_context(self):
        path = (*self.prefix, "call")
        return replace(self.ctx, node_path=".".join(path), admission=self.use.binding(path), agent_name="call")


def fake_native_after_claim(monkeypatch, rig):
    def call(state):
        assert state.claimed and state.candidate_root is not None
        assert state.root == state.candidate_root.root
        assert os.fstat(state.root).st_ino == rig.receipt.value()["root"]["inode"]
        state.terminal = "COMPLETED"

    def persist(state):
        state.persisted = True  # Explicit synthetic persistence adapter, not durable proof.
    monkeypatch.setattr(_Attempt, "call", call)
    monkeypatch.setattr(_Attempt, "persist", persist)


@pytest.mark.parametrize("nested", [False, True])
def test_combined_actual_scheduler_factory_script_native_same_fd_happy_path(tmp_path, monkeypatch, nested):
    rig = Rig(tmp_path, nested=nested)
    fake_native_after_claim(monkeypatch, rig)
    from temper_ai.agent import single_call_agent as native
    original = native._new_file
    claims = []

    def exclusive(fd, name):
        assert rig.transport.inside
        claims.append((fd, os.fstat(fd).st_ino))
        return original(fd, name)
    monkeypatch.setattr(native, "_new_file", exclusive)
    result = rig.execute()
    assert result.status is Status.COMPLETED
    assert rig.tools.calls == 1 and rig.events.script_starts == 1
    assert len(claims) == 1 and (rig.root / "A1.claim").exists()
    assert rig.use.record.value()["readiness"] == [rig.receipt.value()]
    assert set(rig.cp.results) >= {".".join([*rig.prefix, "prepare"]), ".".join([*rig.prefix, "call"])}


@pytest.mark.parametrize("field,value", [("gate", True), ("depends_on", ["absent"]), ("max_loops", True),
                                           ("skip_policies", []), ("input_map", None), ("temperature", 0)])
def test_graph_mutation_refuses_before_topology_policy_events(tmp_path, monkeypatch, field, value):
    rig = Rig(tmp_path)
    setattr(rig.leaves[0].config, field, value)
    from temper_ai.stage import executor
    monkeypatch.setattr(executor, "topological_sort", lambda *_: pytest.fail("topology consumed drift"))
    with pytest.raises(AdmissionRefused):
        rig.execute()
    assert rig.events.count == rig.tools.calls == 0


@pytest.mark.parametrize("mutation", ["missing", "forged", "hooks", "designation", "workspace", "run", "known-type", "known-member", "nested"])
def test_binding_context_and_graph_loss_fail_closed(tmp_path, mutation):
    rig = Rig(tmp_path, nested=mutation == "nested")
    if mutation == "missing":
        rig.ctx.admission = None
    elif mutation == "forged":
        rig.ctx.admission = replace(rig.ctx.admission, graph_sha256="f" * 64)
    elif mutation == "hooks":
        rig.ctx.admission_hooks = object()
    elif mutation == "designation":
        rig.ctx.admission_required = 1
    elif mutation == "workspace":
        rig.ctx.workspace_path = "/different"
    elif mutation == "run":
        rig.ctx.run_id = "00000000-0000-4000-8000-000000000099"
    elif mutation == "known-type":
        rig.leaves[0].config._KNOWN_FIELDS = list(NODE_KEYS)
    elif mutation == "known-member":
        rig.leaves[0].config._KNOWN_FIELDS = frozenset(NODE_KEYS[:-1])
    else:
        rig.nodes[0].child_nodes = [rig.leaves[1], rig.leaves[0]]
    with pytest.raises(AdmissionRefused):
        rig.execute()
    assert rig.events.count == 0


def test_nested_sibling_binding_refuses_before_actual_factory(tmp_path, monkeypatch):
    rig = Rig(tmp_path, nested=True)
    rig.prepare_only()
    context = replace(rig.ctx, node_path="outer", admission=rig.use.binding(("outer", "call")))
    from temper_ai.stage import agent_node
    calls = []
    factory = agent_node.create_agent

    def counted(config):
        calls.append(1)
        return factory(config)
    monkeypatch.setattr(agent_node, "create_agent", counted)
    # Make the registry function identity legitimate; the binding must bite first.
    import temper_ai.agent
    monkeypatch.setattr(temper_ai.agent, "create_agent", counted)
    with pytest.raises(AdmissionRefused) as caught:
        rig.leaves[0].run({}, context)
    assert caught.value.code == RefusalCode.POSITION
    assert calls == [] and rig.events.count == rig.tools.calls == 0


@pytest.mark.parametrize("option", ["initial_outputs", "resume_metadata"])
def test_candidate_continuation_refused_before_checkpoint_restore(tmp_path, option):
    rig = Rig(tmp_path)
    with pytest.raises(AdmissionRefused) as caught:
        rig.execute(**{option: {}})
    assert caught.value.code == RefusalCode.MODE
    assert rig.events.count == 0


def test_legacy_dynamic_context_remains_legacy_at_real_script_consumer():
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.workspace_path, ctx.run_id, ctx.node_path = "/synthetic", RUN, "prepare"
    ctx.tool_executor = FakeTools()
    ctx.event_recorder = FakeEvents()
    result = ScriptAgent({"name": "prepare", "script_template": "printf metadata"}).run({}, ctx)
    assert result.status is Status.COMPLETED
    assert ctx.tool_executor.calls == 1 and ctx.event_recorder.script_starts == 1


@pytest.mark.parametrize("declared", ["required", "binding", "hooks", "invalid-marker"])
def test_dynamic_context_with_explicit_candidate_marker_refuses_before_script(declared):
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.workspace_path, ctx.run_id, ctx.node_path = "/synthetic", RUN, "prepare"
    ctx.tool_executor, ctx.event_recorder = FakeTools(), FakeEvents()
    if declared == "required":
        ctx.admission_required = True
    elif declared == "binding":
        ctx.admission = object()
    elif declared == "hooks":
        ctx.admission_hooks = object()
    else:
        ctx.admission_required = 1
    with pytest.raises(AdmissionRefused):
        ScriptAgent({"name": "prepare", "script_template": "printf metadata"}).run({}, ctx)
    assert ctx.tool_executor.calls == ctx.event_recorder.count == 0


def test_bound_node_cannot_be_run_with_stripped_legacy_context(tmp_path):
    rig = Rig(tmp_path)
    rig.prepare_only()
    legacy = ExecutionContext(RUN, "fixture", "", "", rig.events, rig.tools, workspace_path=str(tmp_path))
    with pytest.raises(AdmissionRefused):
        rig.leaves[0].run({}, legacy)
    assert rig.tools.calls == 0


@pytest.mark.parametrize("mutation", ["factory", "class", "config", "context", "extra", "metadata"])
def test_factory_invocation_guards_at_actual_factory_site(tmp_path, monkeypatch, mutation):
    rig = Rig(tmp_path)
    rig.prepare_only()
    node = rig.leaves[0]
    from temper_ai.stage import agent_node
    if mutation == "factory":
        monkeypatch.setattr(agent_node, "create_agent", lambda *_: pytest.fail("untrusted factory entered"))
    elif mutation == "class":
        monkeypatch.setitem(AGENT_TYPES, "script", SingleCallAgent)
    elif mutation == "config":
        node.agent_config["timeout_seconds"] = True
    elif mutation == "context":
        rig.ctx.node_path = "outer"
    elif mutation == "extra":
        node.agent_config["ignored"] = None
    else:
        node.agent_config["_KNOWN_FIELDS"] = frozenset({"wrong"})
    with pytest.raises(AdmissionRefused):
        node.run({}, rig.ctx)
    assert rig.tools.calls == rig.events.script_starts == 0


@pytest.mark.parametrize("mutation", ["template", "template-missing", "template-type", "variable", "workspace", "run", "alias", "body", "answer_path", "name", "cached-option"])
def test_script_refuses_before_log_rewrite_render_or_tool(tmp_path, monkeypatch, mutation):
    rig = Rig(tmp_path)
    binding = rig.use.binding(("prepare",))
    ctx = replace(rig.ctx, admission=binding, node_path="prepare")
    agent = ScriptAgent(copy.deepcopy(rig.script))
    data = {}
    if mutation == "template":
        agent.config["script_template"] += " "
    elif mutation == "template-missing":
        del agent.config["script_template"]
    elif mutation == "template-type":
        agent.config["script_template"] = None
    elif mutation in ("variable", "body", "answer_path"):
        data[mutation] = "synthetic-unadmitted"
    elif mutation == "name":
        agent.name = "unadmitted"
    elif mutation == "cached-option":
        agent.strict_undefined = True
    elif mutation == "workspace":
        data["workspace_path"] = "/other"
    elif mutation == "run":
        data["run_id"] = "other"
    else:
        shared = []
        data = {"a": shared, "b": shared}
    from temper_ai.agent import script_agent
    monkeypatch.setattr(script_agent, "_rewrite_interpolations", lambda *_: pytest.fail("rewrite before check"))
    with pytest.raises(AdmissionRefused) as caught:
        agent.run(data, ctx)
    assert str(caught.value) in {c.value for c in RefusalCode}
    assert caught.value.__suppress_context__
    assert rig.events.count == rig.tools.calls == 0


@pytest.mark.parametrize("mutation", ["fabricated", "failed", "checkpoint", "nonce", "position", "digest", "durable", "replacement"])
def test_preparation_requires_actual_result_and_verified_checkpoint(tmp_path, mutation):
    rig = Rig(tmp_path)
    rig.use.enter_graph(rig.nodes, rig.ctx, input_data={}, initial_outputs=None, resume_metadata=None,
                        workflow_outputs=None, is_workflow=True)
    node = rig.leaves[0]
    result = NodeResult(Status.COMPLETED, structured_output={"prepared": True})
    rig.use.returned(node, rig.ctx, result)
    rig.cp.save_node_completed("prepare", result)
    if mutation == "fabricated":
        result = NodeResult(Status.COMPLETED, structured_output={"prepared": True})
    elif mutation == "failed":
        result.status = Status.FAILED
        rig.use.checkpointed(node, rig.ctx, result)
        assert rig.use.record.value()["readiness"] == []
        return
    elif mutation == "replacement":
        result.structured_output["prepared"] = False
    else:
        r = rig.receipt.value()
        key, value = {"checkpoint": ("checkpoint_sha256", "b" * 64), "nonce": ("dispatch_nonce", RUN),
                      "position": ("position_id", "unknown"), "digest": ("graph_sha256", "c" * 64),
                      "durable": ("durable", False)}[mutation]
        r[key] = value
        # Deliberately bypass fixture validation: the actual consumer must
        # validate this untrusted synthetic adapter return before transition.
        rig.transport.receipts = (RootReadiness(dump(r)),)
    with pytest.raises(AdmissionRefused):
        rig.use.checkpointed(node, rig.ctx, result)
    assert rig.use.record.value()["readiness"] == []


def test_preparation_commit_failure_does_not_install_local_readiness(tmp_path):
    rig = Rig(tmp_path)
    rig.transport.fail_commit = True
    with pytest.raises(RuntimeError, match="synthetic_commit_failed"):
        rig.prepare_only()
    assert rig.use.record.value()["readiness"] == rig.transport.record.value()["readiness"] == []


def test_returned_agent_config_replacement_refused_before_run(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    rig.prepare_only()
    original = ScriptAgent.__init__

    def substituted(agent, config):
        original(agent, config)
        agent.config = {**config, "timeout_seconds": 31}
    monkeypatch.setattr(ScriptAgent, "__init__", substituted)
    monkeypatch.setattr(ScriptAgent, "run", lambda *_: pytest.fail("returned substituted agent ran"))
    with pytest.raises(AdmissionRefused):
        rig.leaves[0].run({}, rig.ctx)
    assert rig.events.count == rig.tools.calls == 0


def test_graph_object_replacement_before_enqueue_refuses(tmp_path):
    rig = Rig(tmp_path)
    rig.prepare_only()
    old = rig.leaves[1]
    rig.nodes[1] = AgentNode(copy.deepcopy(old.config), copy.deepcopy(old.agent_config))
    with pytest.raises(AdmissionRefused):
        rig.use.before_node(rig.leaves[0], rig.ctx)


def test_second_invocation_not_implicit_retry(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    rig.prepare_only()
    from temper_ai.shared.types import AgentResult
    calls = []

    def empty(*_):
        calls.append(1)
        return AgentResult(Status.FAILED, "", error="fixed_failure")
    monkeypatch.setattr(ScriptAgent, "run", empty)
    rig.leaves[0].run({}, rig.ctx)
    with pytest.raises(AdmissionRefused) as caught:
        rig.leaves[0].run({}, rig.ctx)
    assert caught.value.code == RefusalCode.MODE and len(calls) == 1


@pytest.mark.parametrize("consumer", ["parallel", "timeout"])
def test_each_actual_enqueue_rechecks_after_pool_entry(tmp_path, monkeypatch, consumer):
    rig = Rig(tmp_path)
    rig.prepare_only()
    from temper_ai.stage import executor

    class Pool:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            rig.leaves[0].config.input_map = None
            return self

        def __exit__(self, *args):
            pass

        def submit(self, *args):
            pytest.fail("mutated node enqueued")

    monkeypatch.setattr(executor, "ThreadPoolExecutor", Pool)
    with pytest.raises(AdmissionRefused):
        if consumer == "parallel":
            executor._execute_parallel_batch(rig.leaves, {}, {}, rig.ctx, None)
        else:
            executor._run_with_timeout(rig.leaves[0], {}, rig.ctx, 1)


def test_guard_removal_bites_for_pre_schedule_graph_and_pre_render_variables(tmp_path, monkeypatch):
    rig = Rig(tmp_path / "graph")
    rig.leaves[0].config.gate = True
    from temper_ai.stage import executor
    reached = []

    def topology(*_):
        reached.append(1)
        raise RuntimeError("synthetic_topology_sentinel")
    monkeypatch.setattr(executor, "topological_sort", topology)
    with pytest.raises(AdmissionRefused):
        rig.execute()
    assert reached == []
    monkeypatch.setattr(CandidateUse, "check_graph", lambda *a, **k: None)
    mutant = Rig(tmp_path / "graph-mutant")
    mutant.leaves[0].config.gate = True
    with pytest.raises(RuntimeError, match="synthetic_topology_sentinel"):
        mutant.execute()
    assert reached == [1]
    monkeypatch.undo()
    rig = Rig(tmp_path / "script")
    ctx = replace(rig.ctx, node_path="prepare")
    script = ScriptAgent(copy.deepcopy(rig.script))
    with pytest.raises(AdmissionRefused):
        script.run({"body": "unadmitted-synthetic"}, ctx)
    assert rig.tools.calls == 0
    monkeypatch.setattr(CandidateUse, "check_script", lambda *a, **k: None)
    result = script.run({"body": "unadmitted-synthetic"}, ctx)
    assert result.status is Status.COMPLETED and rig.tools.calls == 1
