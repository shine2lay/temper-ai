"""V1 (#208): the composed raw-config-to-use seam, T1 + T2 + T3 running together.

Synthetic and model-free. Every expected value is a hand-written literal put
together with json and hashlib only; no loader, codec or engine output builds an
expectation. The clean case is also cross-checked against Architecture's A1
compiler (#311), unmodified. Matrix: VERIFICATION-MATRIX.json V01-V36 (sha256
991513e8...); see docs/candidate-admission-verification.md for the table.

TEST-ONLY injected bindings, never production authority: the designated workflow,
the authorized caller, the current-source measurement, the worker identity and the
preparer's readiness receipts (A2's job). Production designation and authority stay
unbound (A4) and keep refusing. The native sender is a counting sentinel; no model,
provider, network, second Temper, browser or local PostgreSQL is started here (the
remote test-postgres tier runs this same file on CI Postgres).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock

import pytest
from sqlmodel import select

from temper_ai.agent.admission_use import CandidateUse, VerifiedPreparation
from temper_ai.agent.single_call_agent import SingleCallAgent, _Attempt
from temper_ai.api.caller import Caller
from temper_ai.cli import run_workflow as worker
from temper_ai.cli.watch_queue import _claim_row, _stamp_handle
from temper_ai.config.admission_capture import RawCapture
from temper_ai.config.admission_contract import (
    SUPPORTED_MODE,
    AdmissionRefused,
    ContractCodec,
    DescriptorAuthority,
    DigestDomain,
    FrozenJSON,
    RefusalCode,
    canonical_bytes,
    digest,
)
from temper_ai.config.candidate_admission import (
    load_candidate,
    project_agent,
    project_graph,
    project_node,
)
from temper_ai.config.models import Config
from temper_ai.config.store import ConfigStore
from temper_ai.database import get_session
from temper_ai.observability.models import Event
from temper_ai.runner import admission as a
from temper_ai.runner.context import RunnerContext
from temper_ai.runner.models import WorkflowRun
from temper_ai.shared.types import ExecutionContext
from temper_ai.worker_proto import ProcessHandle, SpawnerKind
from tests.test_config.admission_cases import (
    NATIVE,
    NODE_DEFAULTS,
    NODE_KEYS,
    SOURCE,
    WORKFLOW_KEYS,
    expectation,
    hashed,
    raw_record,
    text,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "docs/schemas/candidate-admission-v1.schema.json").read_bytes()
LAYOUT = ROOT / "tests/test_config/fixtures/candidate_admission_v1/record-layout.json"
EXECUTION = "00000000-0000-4000-8000-000000000208"
QUEUED_NONCE = "00000000-0000-4000-8000-000000000002"
SLOTS = ("A1", "A2", "A3")
AUTHOR = "synthetic-author"
WORKER = "synthetic-worker"
LABEL = "synthetic"
PROMPT = b"synthetic fixture\n"
PRICES = b"{}"
# Approved script templates: only a declared scalar via the supported {{ name }}
# indirection, outside any quotes (the renderer moves the value into the env).
PREPARE = "printf '{\"prepared\":\"%s\"}\\n' {{ label }}"
RECEIPT = "printf '{\"receipt\":\"%s\"}\\n' {{ label }}"
SCRIPT_CLASS = "temper_ai.agent.script_agent.ScriptAgent"
NATIVE_CLASS = "temper_ai.agent.single_call_agent.SingleCallAgent"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def measure(path):
    value = os.stat(path, follow_symlinks=False)
    return {"path": str(path), "device": value.st_dev, "inode": value.st_ino,
            "uid": value.st_uid, "gid": value.st_gid, "mode": stat.S_IMODE(value.st_mode)}


def resolved(body):
    """One raw node body as the loader leaves it: declared fields over the defaults."""
    return copy.deepcopy(NODE_DEFAULTS) | copy.deepcopy(body)


class Case:
    """One hand-written synthetic admission: raw DB rows, literal descriptor, real roots.

    `approved` mutates the raw bodies BEFORE the oracle is written, so the authority
    signs the mutation and only a real check can refuse it. Mutating `case.raw` after
    construction instead leaves the oracle pinned: that is the database-only case.
    """

    def __init__(self, tmp_path, records=1, *, prefix="", execution=EXECUTION, approved=None,
                 descriptor_edit=None):
        self.execution = execution
        self.workflow = f"v208{prefix}"
        self.ws = tmp_path / f"ws{prefix}"
        self.ws.mkdir()
        self.parent = tmp_path / f"roots{prefix}"
        self.parent.mkdir(mode=0o700)
        self.names = [f"{prefix}r{i:02d}" for i in range(1, records + 1)]
        self.roots = {}
        for r in self.names:
            root = self.parent / r
            root.mkdir(mode=0o700)
            for name, data in (("input.txt", PROMPT), ("prices.json", PRICES)):
                (root / name).write_bytes(data)
                (root / name).chmod(0o600)
            self.roots[r] = root
        self.raw = {}
        top, prev = [], None
        for r in self.names:
            top.append({"name": r, "type": "stage", "ref": f"stages/{r}",
                        **({"depends_on": [prev]} if prev else {})})
            prev = r
            leaves = [{"name": "prepare", "agent": f"agents/{r}_prepare", "input_map": {"label": "input.label"}}]
            before = "prepare"
            for slot in SLOTS:
                leaves.append({"name": f"call_{slot}", "agent": f"agents/{r}_call_{slot}", "depends_on": [before]})
                before = f"call_{slot}"
            leaves.append({"name": "receipt", "agent": f"agents/{r}_receipt", "depends_on": [before],
                           "input_map": {"label": "input.label"}})
            self.raw[("stage", r)] = {"stage": {"name": r, "type": "stage", "nodes": leaves}}
            for kind, template in (("prepare", PREPARE), ("receipt", RECEIPT)):
                self.raw[("agent", f"{r}_{kind}")] = {"agent": {
                    "name": f"{r}_{kind}", "type": "script", "script_template": template, "strict_undefined": True}}
            for slot in SLOTS:
                self.raw[("agent", f"{r}_call_{slot}")] = {"agent": {
                    "name": f"{r}_call_{slot}", "type": "single_call", "provider": "anthropic",
                    "model": "claude-opus-5-5", "single_call": self.native(r, slot)}}
        self.raw[("workflow", self.workflow)] = {"workflow": {"name": self.workflow, "nodes": top}}
        if approved is not None:
            approved(self)
        self.descriptor = self.literal_descriptor()
        if descriptor_edit is not None:
            descriptor_edit(self.descriptor)

    def native(self, r, slot):
        root = self.roots[r]
        return copy.deepcopy(NATIVE) | {
            "output_root": str(root), "slot": slot, "prompt_path": str(root / "input.txt"),
            "prompt_bytes": len(PROMPT), "prompt_sha256": sha(PROMPT),
            "pricing_path": str(root / "prices.json"), "pricing_sha256": sha(PRICES)}

    def policy(self, r):
        return {"path": str(self.roots[r]), "permitted_parent": str(self.parent),
                "custody_receipt_id": "synthetic-only", "worker_label": WORKER, "mount_label": "synthetic",
                "creator_uid": os.getuid(), "creator_gid": os.getgid(), "worker_euid": os.geteuid(),
                "directory_mode": 0o700, "file_mode": 0o600, "lifetime_label": "test-only"}

    def raw_records(self):
        return [raw_record(kind, name, body) for (kind, name), body in sorted(self.raw.items())]

    def literal_descriptor(self):
        """The independent oracle: the raw bodies plus every effective default, by hand.

        Written from the rows themselves, never from a loader, codec or projection, so
        an approved mutation is reflected here and only a real check can refuse it.
        """
        top_nodes, inventory, positions, scripts = [], [], [], []
        variables = text({"label": LABEL, "workspace_path": str(self.ws), "run_id": self.execution})
        for top in self.raw[("workflow", self.workflow)]["workflow"]["nodes"]:
            r = top["name"]
            prefix, _, target = str(top.get("ref") or f"stages/{r}").partition("/")
            kind = {"stages": "stage", "workflows": "workflow"}.get(prefix, "stage")
            stage_body = self.raw.get((kind, target), {}).get(kind, {})
            leaves = [resolved(child) for child in stage_body.get("nodes", [])]
            # An explicit stage ref is resolved: the actual node carries its children.
            stage = resolved({k: v for k, v in top.items() if k != "ref"} | {"type": "stage", "nodes": leaves})
            top_nodes.append(stage)
            inventory.append({"path": [r], "node_json": text(stage), "factory": None})
            for leaf in leaves:
                agent_name = str(leaf.get("agent", "")).removeprefix("agents/")
                body = self.raw.get(("agent", agent_name), {}).get("agent")
                factory = None
                if body is not None and leaf.get("type") == "agent":
                    if body.get("type") == "script":
                        config = body | {"on_max_loops": "silent", "run_after_failure": False, "gate": False,
                                         "_KNOWN_FIELDS": NODE_KEYS}
                        factory = {"type": "script", "class_name": SCRIPT_CLASS, "config_json": text(config)}
                        scripts.append({"node_path": [r, leaf["name"]], "template_utf8": body["script_template"],
                                        "template_sha256": sha(body["script_template"].encode()),
                                        "variables_json": variables})
                    else:
                        factory = {"type": "single_call", "class_name": NATIVE_CLASS, "config_json": text(body)}
                        slot = body.get("single_call", {}).get("slot")
                        positions.append({"position_id": f"{r}-{slot}", "node_path": [r, leaf["name"]],
                                          "preparation_path": [r, "prepare"], "record_id": r,
                                          "variant_id": "v208", "call_id": slot, "slot": slot,
                                          "agent_config_json": text(body), "root_policy": self.policy(r)})
                inventory.append({"path": [r, leaf["name"]], "node_json": text(leaf), "factory": factory})
        workflow = {"name": self.workflow, "description": "", "version": "1.0", "nodes": top_nodes,
                    "inputs": None, "outputs": None, "safety": None, "memory": None, "defaults": None,
                    "on_failure": None, "notify": None, "starts_runs": False, "_KNOWN_FIELDS": WORKFLOW_KEYS}
        return {
            "format": "candidate-admission-descriptor/v1", "profile": "context-profile-admission/v1",
            "mode": "external-db-fresh", "candidate_identity": "v208-synthetic", "logical_run_id": "synthetic-only",
            "execution_uuid": self.execution, "workflow_name": self.workflow, "workspace_path": str(self.ws),
            "metadata_inputs_json": text({"label": LABEL}),
            "request_options_json": text({"mode": "external-db-fresh"}), "source": copy.deepcopy(SOURCE),
            "records": [expectation(r) for r in self.raw_records()],
            "graph": {"workflow_json": text(workflow), "nodes": inventory},
            "positions": positions, "scripts": scripts,
        }

    @property
    def authority(self):
        return DescriptorAuthority(hashed("descriptor", self.descriptor), hashed("source", self.descriptor["source"]),
                                   AUTHOR, "synthetic-receipt")

    def literal_queued_record(self):
        value = json.loads(LAYOUT.read_bytes())
        records = self.raw_records()
        value["immutable"].update(
            authorized_caller_label=AUTHOR, authority_receipt_id="synthetic-receipt",
            descriptor_json=text(self.descriptor), descriptor_sha256=hashed("descriptor", self.descriptor),
            effective_graph_sha256=hashed("graph", self.descriptor["graph"]),
            raw_closure_sha256=hashed("raw-closure", records), raw_records=records)
        value["immutable_sha256"] = hashed("immutable", value["immutable"])
        value["dispatch"] = {"phase": "queued", "dispatch_nonce": QUEUED_NONCE, "running_attempt": 0,
                             "previous_nonce": None, "worker_label": None}
        value["readiness"] = []
        return value

    def expected_claims(self):
        return sorted((str(self.roots[r]), slot, f"{r}-{slot}") for r in self.names for slot in SLOTS)

    def store_rows(self):
        with get_session() as session:
            for (kind, name), body in self.raw.items():
                session.add(Config(type=kind, name=name, schema_version="1.0", config=copy.deepcopy(body)))

    def rewrite_row(self, kind, name, body=None, *, schema_version=None, delete=False):
        """Change a stored row the way an outside writer would, after submission."""
        with get_session() as session:
            found = session.exec(select(Config).where(Config.type == kind, Config.name == name)).one()
            if delete:
                session.delete(found)
            else:
                if body is not None:
                    found.config = copy.deepcopy(body)
                if schema_version is not None:
                    found.schema_version = schema_version
                session.add(found)
            session.commit()


class Projection:
    """T3's ActualProjection, answered by T1's real projections of actual objects."""

    def __init__(self, source):
        self.source = source

    def graph(self, workflow, nodes):
        return project_graph(nodes, workflow, source=self.source)

    def node(self, config):
        return project_node(config, source=self.source)

    def agent(self, config):
        return project_agent(config)


class UseTransport:
    """T3's ProtectedUseTransport: T2's real locked generation, plus test-only A2 receipts."""

    def __init__(self, bindings):
        self.b = bindings

    def current_generation(self, binding, action):
        return self.b.store.current_generation(binding, action)

    def verify_preparation(self, binding, result, checkpoint_service, *, transaction):
        return self.b.preparer(binding, result, checkpoint_service)

    def bind_root_readiness(self, current, receipt, *, verified_preparation, transaction):
        return self.b.store.bind_root_readiness(current, receipt, verified_preparation=verified_preparation,
                                                transaction=transaction)


class EntryBindings:
    """TEST-ONLY typed CandidateBindings + T2 verifiers, built from real T1/T2/T3 code.

    Injected (synthetic, never live custody or authority): designation, the caller's
    authority, the current source, the worker identity and the preparer's receipts.
    """

    def __init__(self, case):
        self.case = case
        self.codec = ContractCodec(SCHEMA)
        self.authority = case.authority
        self.source = FrozenJSON(text(SOURCE).encode())
        self.store = a.DbAdmissionTransport(
            codec=self.codec, authority=self.authority, current_source=lambda: self.source,
            installation=self, preparation=self, worker_identity=lambda: WORKER)
        self.issued = []
        self.loaded = {}
        self.uses = []
        self.events = []
        self.runner = None
        self.after_load = None     # mutate the restored actual nodes before they run
        self.after_prepare = None  # change the world after the receipts were measured
        self.durable = True        # a preparer that does not promise durability (V27)

    # --- CandidateBindings -------------------------------------------------
    def designated(self, name):
        return name == self.case.workflow

    def authority_for_submit(self, caller, workflow_name):
        if caller.label != AUTHOR or workflow_name != self.case.workflow:
            raise AdmissionRefused(RefusalCode.AUTHORITY)
        return self.authority

    def authority_for_run(self, execution_uuid):
        if execution_uuid != self.case.execution:
            raise AdmissionRefused(RefusalCode.AUTHORITY)
        return self.authority

    def transport(self, authority):
        assert authority == self.authority
        return self.store

    def prepare(self, descriptor, *, request, transaction):
        """T1's real raw capture inside T2's install transaction, then the queued record."""
        self.events.append("capture")
        records = RawCapture(self.codec, self.authority, ConfigStore()).capture(descriptor, transaction=transaction)
        closure = self.codec.closure(descriptor, tuple(records))
        value = json.loads(LAYOUT.read_bytes())
        value["immutable"].update(
            authorized_caller_label=self.authority.authorized_caller_label,
            authority_receipt_id=self.authority.receipt_id,
            descriptor_json=descriptor.wire.decode(), descriptor_sha256=descriptor.sha256,
            effective_graph_sha256=digest(DigestDomain.GRAPH, canonical_bytes(descriptor.value()["graph"])),
            raw_closure_sha256=closure.sha256, raw_records=[r.value() for r in closure.records])
        value["immutable_sha256"] = digest(DigestDomain.IMMUTABLE, canonical_bytes(value["immutable"]))
        value["dispatch"] = {"phase": "queued", "dispatch_nonce": QUEUED_NONCE, "running_attempt": 0,
                             "previous_nonce": None, "worker_label": None}
        value["readiness"] = []
        return self.codec.record(canonical_bytes(value), self.authority)

    def bootstrap_snapshot(self, record):
        self.events.append("bootstrap")
        loader = Mock()
        loader.load_workflow.side_effect = AssertionError("mutable loader reached")
        self.runner = RunnerContext(config_store=object(), graph_loader=loader, llm_providers={},
                                    memory_service=None)
        return self.runner

    def load_snapshot(self, record, runner_ctx):
        self.events.append("snapshot")
        nodes, workflow, _ = self._load(record)
        self.loaded[record.value()["immutable"]["descriptor_sha256"]] = (nodes, workflow)
        if self.after_load is not None:
            self.after_load(nodes)
        return nodes, workflow

    def bind_context(self, record, context):
        nodes, workflow = self.loaded[record.value()["immutable"]["descriptor_sha256"]]
        use = CandidateUse(codec=self.codec, record=record, authority=self.authority,
                           projection=Projection(self.source), transport=UseTransport(self), workflow=workflow)
        self.uses.append(use)
        return replace(context, admission=use.binding((nodes[0].name,)), admission_hooks=use,
                       admission_required=True)

    # --- T2 InstallationVerifier / PreparationVerifier -----------------------
    def verify_install(self, admission, *, transaction):
        self._load(admission)
        return True

    def captured_nodes(self, admission, *, transaction):
        return self._load(admission)[0]

    def verify_preparation(self, current, receipt, provenance, *, transaction):
        return (type(provenance) is VerifiedPreparation and any(p is provenance for p in self.issued)
                and any(r.wire == receipt.wire for r in provenance.receipts))

    def _load(self, record):
        immutable = record.value()["immutable"]
        descriptor = self.codec.descriptor(immutable["descriptor_json"].encode(), self.authority)
        closure = self.codec.closure(descriptor, tuple(
            self.codec.raw_record(canonical_bytes(raw)) for raw in immutable["raw_records"]))
        return load_candidate(self.codec, descriptor, closure, authority=self.authority, source=self.source)

    # --- test-only A2 preparer: measures the real roots after the actual prepare ----
    def preparer(self, binding, result, checkpoint_service):
        path = ".".join(binding.node_path)
        saved = checkpoint_service.reconstruct().get(path)
        if saved is None or saved.structured_output != result.structured_output:
            raise AdmissionRefused(RefusalCode.READINESS)
        checkpoint = sha(canonical_bytes(result.structured_output))
        receipts = []
        for position in binding.descriptor.value()["positions"]:
            if tuple(position["preparation_path"]) != binding.node_path:
                continue
            native = json.loads(position["agent_config_json"])["single_call"]
            root = Path(position["root_policy"]["path"])
            files = [Path(native["prompt_path"]), Path(native["pricing_path"])]
            receipts.append(self.codec.readiness(canonical_bytes({
                "format": "candidate-root-readiness/v1", "preparation_path": position["preparation_path"],
                "position_id": position["position_id"], "descriptor_sha256": binding.descriptor.sha256,
                "graph_sha256": binding.graph_sha256, "execution_uuid": binding.dispatch.execution_uuid,
                "dispatch_nonce": binding.dispatch.dispatch_nonce,
                "running_attempt": binding.dispatch.running_attempt, "checkpoint_sha256": checkpoint,
                "root": measure(root), "parents": [measure(p) for p in reversed(root.parents) if str(p) != "/"],
                "files": [{"stat": measure(f), "length": f.stat().st_size, "sha256": sha(f.read_bytes())}
                          for f in files],
                "durable": self.durable})))
        verified = VerifiedPreparation(result, checkpoint, tuple(receipts))
        self.issued.append(verified)
        if self.after_prepare is not None:
            self.after_prepare(self, binding)
        return verified

    # --- entry points ------------------------------------------------------
    def submit(self, **changes):
        d = self.case.descriptor
        kwargs = dict(
            descriptor_wire=text(d).encode(), caller=Caller(name=AUTHOR), workflow_name=d["workflow_name"],
            workspace_path=d["workspace_path"], inputs=json.loads(d["metadata_inputs_json"]),
            request=FrozenJSON(d["request_options_json"].encode()), execution_id=None,
            mode=SUPPORTED_MODE, bindings=self)
        return a.submit_candidate(**{**kwargs, **changes})


class Counters:
    """Counts each boundary's effects; the sentinel is the only 'send'."""

    def __init__(self, monkeypatch):
        self.n = {k: 0 for k in ("raw_read", "store_get", "substitute", "guard_config", "expand", "factory",
                                 "process", "claim", "private_read", "send")}
        self.claims, self.sends, self.commands = [], [], []
        mp = monkeypatch
        from temper_ai.agent import single_call_agent as native
        from temper_ai.config import helpers
        from temper_ai.config import store as store_module
        from temper_ai.spawner import box_guard
        from temper_ai.stage import loader
        from temper_ai.tools import bash

        def counting(key, original):
            def wrapped(*args, **kwargs):
                self.n[key] += 1
                return original(*args, **kwargs)
            return wrapped
        mp.setattr(ConfigStore, "get_raw_record", counting("raw_read", ConfigStore.get_raw_record))
        mp.setattr(ConfigStore, "get", counting("store_get", ConfigStore.get))
        for module in (store_module, box_guard, helpers):
            mp.setattr(module, "substitute_env_vars", counting("substitute", module.substitute_env_vars))
        mp.setattr(box_guard.Guard, "config", counting("guard_config", box_guard.Guard.config))
        # The real GraphLoader always calls expand_templates; T1 refuses template
        # nodes before it, so the call must be the identity pass-through. Count
        # expansions actually performed (a new object back), and calls separately.
        original_expand = loader.expand_templates

        def expand(raw, inputs):
            self.n["expand_calls"] += 1
            before = copy.deepcopy(raw)
            out = original_expand(raw, inputs)
            if out != before or raw != before:
                self.n["expand"] += 1
            return out
        self.n["expand_calls"] = 0
        mp.setattr(loader, "expand_templates", expand)
        # Factory = create_agent, the one AgentNode calls (T3 checks it is exactly
        # that function, so both names get the same wrapper).
        import temper_ai.agent as agent_package
        from temper_ai.stage import agent_node
        original_factory = agent_package.create_agent
        self.on_factory = None    # called with the config the node hands the factory
        self.after_factory = None  # may replace the agent the factory returns

        def factory(config, *args, **kwargs):
            self.n["factory"] += 1
            if self.on_factory is not None:
                self.on_factory(config)
            agent = original_factory(config, *args, **kwargs)
            return agent if self.after_factory is None else self.after_factory(agent, config)
        mp.setattr(agent_package, "create_agent", factory)
        mp.setattr(agent_node, "create_agent", factory)
        original_run = bash._run_subprocess

        def run(command, *args, **kwargs):
            self.n["process"] += 1
            self.commands.append((command, dict(kwargs.get("extra_env") or {})))
            return original_run(command, *args, **kwargs)
        mp.setattr(bash, "_run_subprocess", run)
        original_new = native._new_file

        def exclusive(fd, name):
            self.n["claim"] += 1
            return original_new(fd, name)
        mp.setattr(native, "_new_file", exclusive)
        original_read = native._CandidateRoot.read

        def read(root, path, limit):
            self.n["private_read"] += 1
            return original_read(root, path, limit)
        mp.setattr(native._CandidateRoot, "read", read)

    def zero_transformed(self):
        return {k: self.n[k] for k in ("store_get", "substitute", "guard_config", "expand")}


def sentinel_sender(monkeypatch, counters):
    """Fake send after the real claim: the same fd the readiness receipt measured."""

    def call(state):
        assert state.claimed and state.candidate_root is not None and state.root == state.candidate_root.root
        binding = state.context.admission
        fixed = state.fixed
        assert state.candidate_root.read(fixed["prompt_path"], fixed["prompt_bytes"]) == PROMPT
        counters.n["send"] += 1
        counters.sends.append((fixed["output_root"], fixed["slot"], binding.position_id,
                               os.fstat(state.root).st_ino))
        state.terminal = "COMPLETED"

    def persist(state):
        state.persisted = True  # Synthetic persistence adapter, not durable native proof.
    monkeypatch.setattr(_Attempt, "call", call)
    monkeypatch.setattr(_Attempt, "persist", persist)


def worker_harness(monkeypatch, tmp_path):
    """The actual worker entry, minus the box process plumbing (as T2's own tests)."""
    mutable_boot = Mock(side_effect=AssertionError("mutable bootstrap reached"))
    monkeypatch.setattr("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env", mutable_boot)
    monkeypatch.setattr("temper_ai.spawner.box_view.check_box", lambda: None)
    monkeypatch.setattr(worker, "_unboxed_under_sealed", lambda *_: None)
    monkeypatch.setattr(worker, "_install_signal_handlers", lambda *_: None)
    monkeypatch.setattr(worker, "_start_mcp_manager", Mock(side_effect=AssertionError("mutable MCP reached")))
    monkeypatch.setattr(worker, "_stop_mcp_manager", lambda *_: None)
    for path in ("temper_ai.streaming.RedisChunkNotifier",
                 "temper_ai.observability.jsonl_logger.JsonlNotifier",
                 "temper_ai.observability.webhook_notifier.WebhookNotifier"):
        monkeypatch.setattr(path, Mock())
    monkeypatch.setenv("TEMPER_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr("temper_ai.integrations.github.app.asks_server_for_tokens", lambda: False)
    return mutable_boot


def row(execution=EXECUTION):
    with get_session() as session:
        found = session.get(WorkflowRun, execution)
        return None if found is None else copy.deepcopy(found.model_dump())


def stored_record(execution=EXECUTION):
    return row(execution)["spawner_metadata"]["config_admission"]


def run_worker(b, execution=EXECUTION):
    return worker.cmd_run_workflow(argparse.Namespace(execution_id=execution), candidate_bindings=b)


def queue_and_claim(b, execution=EXECUTION):
    assert _claim_row(execution, candidate_bindings=b)
    _stamp_handle(execution, ProcessHandle(kind=SpawnerKind.subprocess, handle="worker:synthetic",
                                           metadata={"pid": 42}))


def submit_to_claim(tmp_path, monkeypatch, records=1):
    case = Case(tmp_path, records)
    case.store_rows()
    counters = Counters(monkeypatch)
    sentinel_sender(monkeypatch, counters)
    boot = worker_harness(monkeypatch, tmp_path)
    b = EntryBindings(case)
    assert b.submit() == EXECUTION
    queue_and_claim(b)
    code = run_worker(b)
    return case, counters, b, boot, code


def all_event_data(execution=EXECUTION):
    """Everything the run told its observers, as one blob to search."""
    with get_session() as session:
        return [copy.deepcopy(e.data) for e in session.exec(
            select(Event).where(Event.execution_id == execution)).all()]


def recorded_failures(execution=EXECUTION):
    """Every failure the run recorded, as the dashboard and the row show it.

    A refusal raised while the graph is entered ends the run itself; one raised
    inside a node ends that node, and the run row then carries no message of its
    own. Both surfaces are read here, so no control can pass on the wrong one.
    """
    found = row(execution) or {}
    messages = [found["error"]["message"]] if found.get("error") else []
    with get_session() as session:
        for event in session.exec(select(Event).where(Event.execution_id == execution)).all():
            data = event.data or {}
            for key in ("error", "message", "reason"):
                if data.get(key) and event.status in ("failed", "error", "cancelled"):
                    messages.append(str(data[key]))
    return messages


def submit_case(case):
    """Submit and queue one more case in an already patched environment."""
    case.store_rows()
    b = EntryBindings(case)
    assert b.submit() == case.execution
    queue_and_claim(b, case.execution)
    return b


def reject(call, code):
    with pytest.raises(AdmissionRefused) as err:
        call()
    assert err.value.code == code, err.value.code


# ---------------------------------------------------------------------------
# Opening combined happy path (V01, V12, V26) and the synthetic 14x3 (V02)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("records", [
    pytest.param(1, id="V01-tiny"),
    # Measured 414 s on the dev host: every use-site check re-projects the whole
    # actual graph and every generation fence re-verifies the whole record, so a
    # candidate run is quadratic in its graph (docs/candidate-admission-verification.md,
    # "Cost"). The marker is that measurement with room for slower CI runners.
    pytest.param(14, id="V02-14x3", marks=pytest.mark.timeout(1800)),
])
def test_submit_queue_worker_restore_schedule_factory_script_claim_happy_path(tmp_path, monkeypatch, records):
    case, counters, b, boot, code = submit_to_claim(tmp_path, monkeypatch, records)
    assert code == 0, row()
    assert row()["status"] == "completed"
    # B1: raw capture read exactly the descriptor's records, once each, at submit.
    assert counters.n["raw_read"] == len(case.raw)
    # Zero ordinary transformed lookups or substitution anywhere, worker included.
    assert counters.zero_transformed() == {"store_get": 0, "substitute": 0, "guard_config": 0, "expand": 0}
    boot.assert_not_called()
    b.runner.graph_loader.load_workflow.assert_not_called()
    # Stored bytes: the literal oracle's record, then one dispatch, then readiness.
    final = stored_record()
    literal = case.literal_queued_record()
    assert final["immutable"] == literal["immutable"]
    assert final["immutable_sha256"] == literal["immutable_sha256"]
    assert final["dispatch"]["phase"] == "running" and final["dispatch"]["running_attempt"] == 1
    assert final["dispatch"]["previous_nonce"] == QUEUED_NONCE
    assert final["dispatch"]["worker_label"] == WORKER
    # B5: one claim per (root, slot, position), on the receipt's exact root, then the sentinel.
    expected = case.expected_claims()
    assert len(expected) == 3 * records and len(set(expected)) == 3 * records
    assert sorted(s[:3] for s in counters.sends) == expected
    assert counters.n["claim"] == counters.n["send"] == 3 * records
    ready = {r["position_id"]: r for r in final["readiness"]}
    assert sorted(ready) == sorted(p for _, _, p in expected)
    for root, slot, position, inode in counters.sends:
        assert ready[position]["root"]["inode"] == inode == os.stat(root).st_ino
        assert (Path(root) / f"{slot}.claim").exists()
    # B4: factory and script for every leaf; each script rendered by indirection only.
    assert counters.n["factory"] == 5 * records
    assert counters.n["process"] == 2 * records
    for command, env in counters.commands:
        assert LABEL not in command and LABEL in env.values()
    # V02: each call ran after its own record's prepare; receipts measured per record.
    order = [s[2] for s in counters.sends]
    assert order == [p for _, _, p in sorted(expected, key=lambda t: (t[2][:-3], t[1]))]


def test_expected_side_is_decoded_once_not_on_every_node_check(tmp_path, monkeypatch, record_property):
    """D2 bite: per-node work on the EXPECTED side must not grow with the graph.

    Every check still re-reads the actual objects; only what is a pure function
    of the immutable admitted bytes may be computed once. Doubling the graph may
    at most double the descriptor decodes (linear), never quadruple them.
    """
    from temper_ai.config import admission_contract as contract
    counters = Counters(monkeypatch)
    sentinel_sender(monkeypatch, counters)
    worker_harness(monkeypatch, tmp_path)
    original = contract.decode_canonical
    target = {"wire": None, "count": 0}

    def decode(data):
        if data == target["wire"]:
            target["count"] += 1
        return original(data)
    monkeypatch.setattr(contract, "decode_canonical", decode)
    counts = {}
    for records, execution in ((1, "00000000-0000-4000-8000-000000000211"),
                               (2, "00000000-0000-4000-8000-000000000212")):
        case = Case(tmp_path, records, prefix=f"d{records}", execution=execution)
        b = submit_case(case)
        target.update(wire=text(case.descriptor).encode(), count=0)
        assert run_worker(b, execution) == 0, row(execution)
        counts[records] = target["count"]
    record_property("descriptor_decodes_by_records", counts)
    assert counts[2] <= 2 * counts[1], counts


def test_clean_case_matches_architecture_a1_compiler_unmodified(tmp_path):
    """A1 (#311) compiles the same authoring input to exactly our literal wire bytes."""
    import importlib
    a1t = importlib.import_module("tests.test_config.test_context_profile_admission_compile")
    case = Case(tmp_path, 14)
    # A1's authoring form: the same values as JSON objects instead of CAJ-1 text.
    authoring = copy.deepcopy({k: v for k, v in case.descriptor.items() if k != "records"})
    for key in ("metadata_inputs_json", "request_options_json"):
        authoring[key] = json.loads(authoring[key])
    authoring["graph"]["workflow_json"] = json.loads(authoring["graph"]["workflow_json"])
    for node in authoring["graph"]["nodes"]:
        node["node_json"] = json.loads(node["node_json"])
        if node["factory"]:
            node["factory"]["config_json"] = json.loads(node["factory"]["config_json"])
    for position in authoring["positions"]:
        position["agent_config_json"] = json.loads(position["agent_config_json"])
    for script in authoring["scripts"]:
        script["variables_json"] = json.loads(script["variables_json"])
    raws = [r | {"config_json": json.loads(r["config_json"])} for r in case.raw_records()]
    compiled = a1t.subject.Compiler(a1t.CODEC_PATH, a1t.SCHEMA_PATH).compile(
        authoring, raws, a1t.approve(authoring, raws))
    assert compiled["descriptor.json"] == text(case.descriptor).encode()


# ---------------------------------------------------------------------------
# Frozen negative controls V03-V36.
#
# Every docstring quotes VERIFICATION-MATRIX.json (SHA256 991513e8faa890a717496
# be177c30dd91e57cd9ba7e9125bf5e19bdc1ff0a7f5) word for word. The refusal codes
# are the ones the composed seam actually produced; the code predicted before the
# first run, and every difference, is in docs/candidate-admission-verification.md.
# ---------------------------------------------------------------------------


def leaf(case, name, r=None):
    """One raw leaf node inside a stage row."""
    r = r or case.names[0]
    return next(n for n in case.raw[("stage", r)]["stage"]["nodes"] if n["name"] == name)


def agent_of(case, suffix, r=None):
    r = r or case.names[0]
    return case.raw[("agent", f"{r or case.names[0]}_{suffix}")]["agent"]


def child(nodes, name, top=0):
    """One actual loaded node, as the scheduler holds it."""
    return next(n for n in nodes[top].child_nodes if n.name == name)


def control(tmp_path, monkeypatch, *, approved=None, descriptor_edit=None, db=None, stored=None, records=1):
    """One synthetic admission, changed on the approved, database or stored side."""
    case = Case(tmp_path, records, approved=approved, descriptor_edit=descriptor_edit)
    if db is not None:
        db(case)
    case.store_rows()
    if stored is not None:
        stored(case)
    counters = Counters(monkeypatch)
    sentinel_sender(monkeypatch, counters)
    worker_harness(monkeypatch, tmp_path)
    return case, counters, EntryBindings(case)


def refused_at_submit(tmp_path, monkeypatch, code, **build):
    """Nothing reaches the queue: no run row, no transformed read, no factory, no claim."""
    case, counters, b = control(tmp_path, monkeypatch, **build)
    reject(b.submit, code)
    assert row() is None, "a refused submission must leave no run row behind"
    assert counters.zero_transformed() == {"store_get": 0, "substitute": 0, "guard_config": 0, "expand": 0}
    assert (counters.n["factory"], counters.n["claim"], counters.n["send"], counters.n["process"]) == (0, 0, 0, 0)
    return case, counters, b


def refused_in_run(tmp_path, monkeypatch, code, *, exit_code=1, after_load=None, after_prepare=None,
                   after_submit=None, on_factory=None, after_factory=None, **build):
    """Admitted, then refused on the actual use side: the run fails with the fixed code."""
    case, counters, b = control(tmp_path, monkeypatch, **build)
    b.after_load, b.after_prepare = after_load, after_prepare
    counters.on_factory, counters.after_factory = on_factory, after_factory
    assert b.submit() == EXECUTION
    if after_submit is not None:
        after_submit(case, b)
    queue_and_claim(b)
    assert run_worker(b) == exit_code
    if exit_code == 1:
        assert row()["status"] == "failed"
        assert code.value in recorded_failures(), recorded_failures()
    return case, counters, b


# --- B1: the database changed under an approved descriptor ------------------

def db_leaf_other_slot(case):
    leaf(case, "call_A1")["agent"] = f"agents/{case.names[0]}_call_A2"


def db_swap_native_maps(case):
    one, two = agent_of(case, "call_A1"), agent_of(case, "call_A2")
    one["single_call"], two["single_call"] = two["single_call"], one["single_call"]


def db_other_model(case):
    agent_of(case, "call_A1")["model"] = "claude-opus-5-6"


def db_other_family(case):
    agent_of(case, "call_A1")["single_call"]["family"] = "B"


def db_token_renamed(case):
    agent_of(case, "call_A1")["single_call"]["token"] = "other-name-not-secret"


def db_token_missing(case):
    del agent_of(case, "call_A1")["single_call"]["token"]


def db_token_null(case):
    agent_of(case, "call_A1")["single_call"]["token"] = None


def db_twin_prompt(case):
    """Another path holding exactly the admitted bytes, with the admitted length."""
    twin = case.ws / "twin.txt"
    twin.write_bytes(PROMPT)
    agent_of(case, "call_A1")["single_call"]["prompt_path"] = str(twin)


def db_other_digest(case):
    agent_of(case, "call_A1")["single_call"]["pricing_sha256"] = "9" * 64


def db_other_output_root(case):
    other = case.parent / "elsewhere"
    other.mkdir(mode=0o700)
    agent_of(case, "call_A1")["single_call"]["output_root"] = str(other)


def db_remove_node(case):
    case.raw[("stage", case.names[0])]["stage"]["nodes"].remove(leaf(case, "receipt"))


def db_duplicate_name(case):
    case.raw[("stage", case.names[0])]["stage"]["nodes"].append(copy.deepcopy(leaf(case, "call_A1")))


def db_other_dependency(case):
    leaf(case, "receipt")["depends_on"] = ["prepare"]


def db_timeout(case):
    leaf(case, "call_A1")["timeout_seconds"] = 5


def db_condition(case):
    leaf(case, "call_A1")["condition"] = "always"


def db_input_map(case):
    leaf(case, "call_A1")["input_map"] = {"label": "input.label"}


def db_on_failure(case):
    leaf(case, "call_A1")["on_failure"] = "prepare"


def db_outputs(case):
    leaf(case, "call_A1")["outputs"] = {"answer": "text"}


def db_missing_stage_row_same_name_workflow(case):
    """The stage row is deleted after approval and a workflow of that name exists."""
    r = case.names[0]
    body = case.raw.pop(("stage", r))["stage"]
    case.raw[("workflow", r)] = {"workflow": {"name": r, "nodes": body["nodes"]}}


def db_extra_referenced_record(case):
    """A new leaf pointing at a row the descriptor never admitted."""
    r = case.names[0]
    case.raw[("agent", f"{r}_extra")] = {"agent": {
        "name": f"{r}_extra", "type": "script", "script_template": PREPARE, "strict_undefined": True}}
    case.raw[("stage", r)]["stage"]["nodes"].append(
        {"name": "extra", "agent": f"agents/{r}_extra", "depends_on": ["receipt"]})


@pytest.mark.parametrize("change,code", [
    pytest.param(db_leaf_other_slot, RefusalCode.DIGEST, id="V03-valid-A1-becomes-valid-A2"),
    pytest.param(db_swap_native_maps, RefusalCode.DIGEST, id="V04-swap-two-per-call-maps"),
    pytest.param(db_other_model, RefusalCode.DIGEST, id="V05-other-model"),
    pytest.param(db_other_family, RefusalCode.DIGEST, id="V05-other-family"),
    pytest.param(db_token_renamed, RefusalCode.DIGEST, id="V06-token-renamed"),
    pytest.param(db_token_missing, RefusalCode.DIGEST, id="V06-token-missing"),
    pytest.param(db_token_null, RefusalCode.DIGEST, id="V06-token-null"),
    pytest.param(db_twin_prompt, RefusalCode.DIGEST, id="V07-other-path-same-bytes"),
    pytest.param(db_other_digest, RefusalCode.DIGEST, id="V08-other-64-hex-digest"),
    pytest.param(db_other_output_root, RefusalCode.DIGEST, id="V08-other-output-root"),
    pytest.param(db_remove_node, RefusalCode.DIGEST, id="V15-remove-a-node"),
    pytest.param(db_duplicate_name, RefusalCode.DIGEST, id="V15-duplicate-node-name"),
    pytest.param(db_other_dependency, RefusalCode.DIGEST, id="V15-change-dependency"),
    pytest.param(db_timeout, RefusalCode.DIGEST, id="V15-change-timeout"),
    pytest.param(db_condition, RefusalCode.DIGEST, id="V15-change-condition"),
    pytest.param(db_on_failure, RefusalCode.DIGEST, id="V15-change-on-failure"),
    pytest.param(db_outputs, RefusalCode.DIGEST, id="V15-change-outputs"),
    pytest.param(db_input_map, RefusalCode.DIGEST, id="V13-unapproved-input-map"),
    pytest.param(db_extra_referenced_record, RefusalCode.DIGEST, id="V15-extra-referenced-record"),
    pytest.param(db_missing_stage_row_same_name_workflow, RefusalCode.LOOKUP, id="V16-missing-stage-row"),
])
def test_database_row_differs_from_the_approved_descriptor(tmp_path, monkeypatch, change, code):
    """V03-V08, V13, V15, V16: REFUSE pinned raw digest ... zero wrong claim; the
    deleted stage row is never served by a same-name workflow."""
    refused_at_submit(tmp_path, monkeypatch, code, db=change)


def test_v18_row_schema_version_changes_between_approval_and_capture(tmp_path, monkeypatch):
    """V18: Capture one transaction and compare every exact record digest; no mixed
    closure passes; mismatch refuses."""
    refused_at_submit(tmp_path, monkeypatch, RefusalCode.CLOSURE,
                      stored=lambda case: case.rewrite_row(
                          "agent", f"{case.names[0]}_call_A1", schema_version="2.0"))


def test_v18_row_changes_during_the_capture_transaction(tmp_path, monkeypatch):
    """V18: a row rewritten mid-capture cannot produce a mixed closure."""
    case, counters, b = control(tmp_path, monkeypatch)
    original = ConfigStore.get_raw_record
    seen = []

    def changing(self, name, kind, **kwargs):
        body, version = original(self, name, kind, **kwargs)
        seen.append((kind, name))
        if len(seen) == 3:  # a later row changes while the earlier ones are already read
            body = copy.deepcopy(body)
            body[kind]["model"] = "claude-opus-5-6"
        return body, version
    monkeypatch.setattr(ConfigStore, "get_raw_record", changing)
    reject(b.submit, RefusalCode.DIGEST)
    assert row() is None


# --- B1: the approved descriptor itself carries prohibited raw content -------

def ok_marker_in_model(case):
    agent_of(case, "call_A1")["model"] = "${TEMPER_MODEL}"


def ok_marker_in_path(case):
    agent_of(case, "call_A1")["single_call"]["prompt_path"] = "${HOME}/input.txt"


def ok_marker_in_token(case):
    agent_of(case, "call_A1")["single_call"]["token"] = "${ANTHROPIC_TOKEN}"


def ok_marker_in_identifier(case):
    agent_of(case, "call_A1")["single_call"]["binding_id"] = "${BINDING}"


def ok_marker_in_list(case):
    leaf(case, "receipt")["depends_on"] = ["call_A3", "${HOME}"]


def ok_marker_in_key(case):
    leaf(case, "call_A1")["input_map"] = {"${HOME}": "input.label"}


def ok_marker_in_on_failure(case):
    leaf(case, "call_A1")["on_failure"] = "${HOME}"


def ok_marker_in_workflow_defaults(case):
    case.raw[("workflow", case.workflow)]["workflow"]["defaults"] = {"model": "${HOME}"}


def ok_marker_in_script_elsewhere(case):
    agent_of(case, "prepare")["description"] = "{{ label }}"


def ok_jinja_in_model(case):
    agent_of(case, "call_A1")["model"] = "{{ label }}"


def ok_dynamic_ref(case):
    """The interpolated name even exists as a row, so only the scan can refuse it."""
    case.raw[("agent", "{{ label }}")] = {"agent": {
        "name": "{{ label }}", "type": "script", "script_template": PREPARE, "strict_undefined": True}}
    leaf(case, "call_A1")["agent"] = "agents/{{ label }}"


def ok_template_node(case):
    leaf(case, "call_A1")["type"] = "template"


def ok_strategy_node(case):
    leaf(case, "call_A1")["strategy"] = "parallel"


def ok_extra_placeholder(case):
    agent_of(case, "prepare")["script_template"] = PREPARE.replace("{{ label }}", "{{ secret }}")


def ok_template_filter(case):
    agent_of(case, "prepare")["script_template"] = PREPARE.replace("{{ label }}", "{{ label | upper }}")


def ok_unknown_node_field(case):
    leaf(case, "call_A1")["surprise"] = "1"


def ok_known_fields_key(case):
    agent_of(case, "call_A1")["_KNOWN_FIELDS"] = "all"


def ok_body_renamed(case):
    agent_of(case, "prepare")["name"] = "renamed"


def ok_unqualified_ref(case):
    leaf(case, "call_A1")["agent"] = f"{case.names[0]}_call_A1"


def ok_slash_alias_ref(case):
    """The aliased name exists as a row too: the ref grammar is what refuses."""
    r = case.names[0]
    case.raw[("agent", f"sub/{r}_call_A1")] = copy.deepcopy(case.raw[("agent", f"{r}_call_A1")])
    case.raw[("agent", f"sub/{r}_call_A1")]["agent"]["name"] = f"sub/{r}_call_A1"
    leaf(case, "call_A1")["agent"] = f"agents/sub/{r}_call_A1"


def ok_workflow_defaults_as_stage(case):
    """A workflow used as a stage, carrying a workflow-only default."""
    r = case.names[0]
    body = case.raw.pop(("stage", r))["stage"]
    case.raw[("workflow", "sub")] = {"workflow": {
        "name": "sub", "defaults": {"model": "claude-opus-5-5"}, "nodes": body["nodes"]}}
    case.raw[("workflow", case.workflow)]["workflow"]["nodes"][0]["ref"] = "workflows/sub"


def ok_cycle(case):
    r = case.names[0]
    case.raw[("stage", r)]["stage"]["nodes"].append({"name": "again", "type": "stage", "ref": f"stages/{r}"})


def ok_unreachable_record(case):
    r = case.names[0]
    case.raw[("agent", f"{r}_orphan")] = {"agent": {
        "name": f"{r}_orphan", "type": "script", "script_template": PREPARE, "strict_undefined": True}}


def ok_extra_inline_model_node(case):
    """An extra node that would call a model inline, with no admitted agent row."""
    case.raw[("stage", case.names[0])]["stage"]["nodes"].append(
        {"name": "extra_model", "model": "claude-opus-5-5", "provider": "anthropic",
         "system_prompt": "synthetic", "depends_on": ["receipt"]})


def ok_extra_tool_node(case):
    """An extra node that reuses an admitted script agent and adds a tool to it."""
    r = case.names[0]
    case.raw[("stage", r)]["stage"]["nodes"].append(
        {"name": "extra_tool", "agent": f"agents/{r}_prepare", "tools": ["bash"], "depends_on": ["receipt"]})


def prohibited(key, value):
    """One raw node declaring an engine behaviour a candidate may not carry."""
    def change(case):
        leaf(case, "call_A1")[key] = value
    change.__name__ = f"ok_node_{key}"
    return change


@pytest.mark.parametrize("change,code,reads_raw", [
    pytest.param(ok_marker_in_model, RefusalCode.SCHEMA, True, id="V09-marker-in-model"),
    pytest.param(ok_marker_in_path, RefusalCode.SCHEMA, True, id="V09-marker-in-path"),
    pytest.param(ok_marker_in_token, RefusalCode.SCHEMA, True, id="V09-marker-in-token"),
    pytest.param(ok_marker_in_identifier, RefusalCode.SCHEMA, True, id="V09-marker-in-id"),
    pytest.param(ok_marker_in_list, RefusalCode.SCHEMA, True, id="V09-marker-in-nested-list"),
    pytest.param(ok_marker_in_key, RefusalCode.SCHEMA, True, id="V09-marker-in-dict-key"),
    pytest.param(ok_marker_in_on_failure, RefusalCode.SCHEMA, True, id="V10-marker-in-on-failure"),
    pytest.param(ok_marker_in_workflow_defaults, RefusalCode.SCHEMA, True, id="V10-marker-in-workflow-defaults"),
    pytest.param(ok_marker_in_script_elsewhere, RefusalCode.SCHEMA, True, id="V10-template-text-in-other-key"),
    # A field the engine has no meaning for is not in the source's node field set,
    # so the contract refuses the wire before any row is read.
    pytest.param(ok_unknown_node_field, RefusalCode.FIELDS, False, id="V10-unknown-extra-field"),
    pytest.param(ok_known_fields_key, RefusalCode.FIELDS, True, id="V10-known-fields-key"),
    pytest.param(ok_jinja_in_model, RefusalCode.SCHEMA, True, id="V11-jinja-in-non-script-field"),
    # An interpolated or aliased record name is not a name the wire schema allows.
    pytest.param(ok_dynamic_ref, RefusalCode.SCHEMA, False, id="V11-inline-dynamic-ref"),
    # A node type the engine has no factory for cannot be written into a consistent
    # descriptor at all: the contract refuses the wire before any row is read.
    pytest.param(ok_template_node, RefusalCode.GRAPH, False, id="V11-template-node-type"),
    pytest.param(ok_strategy_node, RefusalCode.SCHEMA, True, id="V11-dispatch-node"),
    pytest.param(prohibited("strategy_config", {}), RefusalCode.SCHEMA, True, id="V11-dispatch-config"),
    pytest.param(prohibited("agents", []), RefusalCode.SCHEMA, True, id="V11-dispatch-agents"),
    # A node that names a model but no factory: the contract's node/factory agreement
    # refuses the wire before any row is read.
    pytest.param(ok_extra_inline_model_node, RefusalCode.GRAPH, False, id="V11-extra-inline-model-node"),
    pytest.param(ok_extra_tool_node, RefusalCode.SCHEMA, True, id="V11-extra-tool-node"),
    pytest.param(ok_extra_placeholder, RefusalCode.SCHEMA, True, id="V13-extra-placeholder"),
    pytest.param(ok_template_filter, RefusalCode.SCHEMA, True, id="V13-template-filter"),
    # Raw-profile eligibility is checked before loading, not by a later graph mismatch.
    pytest.param(prohibited("tools", []), RefusalCode.SCHEMA, True, id="V14-node-tools-empty-list"),
    pytest.param(prohibited("memory", {}), RefusalCode.SCHEMA, True, id="V14-node-memory-empty-object"),
    pytest.param(ok_workflow_defaults_as_stage, RefusalCode.SCHEMA, True, id="V14-workflow-default-override"),
    pytest.param(ok_body_renamed, RefusalCode.CLOSURE, True, id="V15-body-name-not-its-key"),
    pytest.param(ok_unreachable_record, RefusalCode.CLOSURE, True, id="V15-unreachable-admitted-record"),
    pytest.param(ok_unqualified_ref, RefusalCode.CLOSURE, True, id="V16-unqualified-ref"),
    pytest.param(ok_slash_alias_ref, RefusalCode.SCHEMA, False, id="V16-slash-alias-ref"),
    pytest.param(ok_cycle, RefusalCode.CLOSURE, True, id="V21-cyclic-raw-input"),
])
def test_approved_descriptor_carrying_prohibited_raw_content(tmp_path, monkeypatch, change, code, reads_raw):
    """V09-V16, V21: REFUSE before substitute_env_vars/Guard.config/GraphLoader; zero
    environment access attributable to candidate resolution. REFUSE prohibited raw
    presence even where loader would ignore; no global loader-policy change.

    The authority signs the change, so a stale digest cannot refuse it. reads_raw
    distinguishes the contract's early wire refusal from the raw-capture boundary.
    The otherwise-valid profile controls below additionally prove that removing the
    raw check would actually admit prohibited content with the same descriptor.
    Every value here is well typed; malformed types have separate T1 controls.
    """
    _, counters, _ = refused_at_submit(tmp_path, monkeypatch, code, approved=change)
    assert (counters.n["raw_read"] > 0) is reads_raw


# --- B0/B1: the caller, not the content ------------------------------------

def test_v32_changed_manifest_with_its_own_digest_is_not_its_own_authority(tmp_path, monkeypatch):
    """V32: AUTHORITY; no self-issued authority accepted."""
    case, counters, b = control(tmp_path, monkeypatch)
    changed = copy.deepcopy(case.descriptor)
    # The caller drops records from the manifest and offers the wire it computed
    # itself; only the issued receipt is unchanged.
    changed["records"] = [r for r in changed["records"] if r["kind"] != "agent"]
    reject(lambda: b.submit(descriptor_wire=text(changed).encode()), RefusalCode.AUTHORITY)
    assert row() is None and counters.n["raw_read"] == 0


@pytest.mark.parametrize("changes", [
    pytest.param({"execution_id": "00000000-0000-4000-8000-000000000224"},
                 id="V24-preselected-execution-id"),
    pytest.param({"inputs": {"label": LABEL, "run_id": EXECUTION}}, id="V24-inputs-override-run-id"),
    pytest.param({"workspace_path": "/tmp"}, id="V24-workspace-override"),
])
def test_v24_the_caller_cannot_preselect_protected_run_state(tmp_path, monkeypatch, changes):
    """V24: PROTECTED at submit; protected keys never caller-supplied."""
    case, counters, b = control(tmp_path, monkeypatch)
    reject(lambda: b.submit(**changes), RefusalCode.PROTECTED)
    assert row() is None
    assert (counters.n["factory"], counters.n["claim"], counters.n["send"]) == (0, 0, 0)


DEFAULTED_INPUTS = {"label": {"type": "string"}, "extra": {"type": "string", "default": "filled"}}


def declare_defaulted_input(case):
    case.raw[("workflow", case.workflow)]["workflow"]["inputs"] = copy.deepcopy(DEFAULTED_INPUTS)


def inputs_oracle(*, complete):
    """The workflow's declared inputs in the oracle; the caller's inputs complete or not."""
    def edit(descriptor):
        workflow = json.loads(descriptor["graph"]["workflow_json"])
        workflow["inputs"] = copy.deepcopy(DEFAULTED_INPUTS)
        descriptor["graph"]["workflow_json"] = text(workflow)
        if complete:
            descriptor["metadata_inputs_json"] = text({"label": LABEL, "extra": "filled"})
    return edit


def test_v24_explicit_complete_inputs_are_admitted(tmp_path, monkeypatch):
    """V24 twin: the same declared defaulted input, given explicitly, is admitted, so
    the oracle describes this workflow faithfully and only the filling can refuse below."""
    case, counters, b = control(tmp_path, monkeypatch, approved=declare_defaulted_input,
                                descriptor_edit=inputs_oracle(complete=True))
    assert b.submit() == EXECUTION


def test_v24_caller_inputs_completed_by_filled_defaults_refuse(tmp_path, monkeypatch):
    """V24: REFUSE at input admission when a declared default would fill the caller's
    inputs: the admitted inputs must be the complete inputs the run uses."""
    refused_at_submit(tmp_path, monkeypatch, RefusalCode.GRAPH, approved=declare_defaulted_input,
                      descriptor_edit=inputs_oracle(complete=False))


def guarded(monkeypatch, data=b""):
    """A real (empty) Guard object made current, without starting any box."""
    from temper_ai.spawner import box_guard
    guard = box_guard.Guard.__new__(box_guard.Guard)
    monkeypatch.setattr(box_guard.Guard, "raw_config_record",
                        lambda self, name, kind: (f"configs/{kind}s/{name}.yaml", data))
    monkeypatch.setattr(box_guard, "active", lambda: guard)
    return guard


@pytest.mark.parametrize("data", [
    pytest.param(b"", id="V19-classified-box"),
    pytest.param(b"name: r01_call_A1\nmodel: ${HOME}\n", id="V19-classified-file-with-env-marker"),
    pytest.param(b"name: r01_call_A1\nmodel: other\n", id="V19-classified-file-other-bytes"),
])
def test_v19_a_database_capture_under_a_classified_box_refuses(tmp_path, monkeypatch, data):
    """V19: capture_classified_record + descriptor origin db-only -> MODE; no DB fallback.

    A v1 descriptor admits database rows only, so under a classified box the capture
    refuses at the mode boundary before it reads anything: neither the database nor
    the sealed file, whatever that file holds.
    """
    from temper_ai.spawner import box_guard
    guarded(monkeypatch, data)
    reads = []
    monkeypatch.setattr(box_guard.Guard, "raw_config_record",
                        lambda self, name, kind: reads.append((kind, name)) or (f"configs/{kind}s/{name}.yaml", data))
    _, counters, _ = refused_at_submit(tmp_path, monkeypatch, RefusalCode.MODE)
    assert reads == [] and counters.n["raw_read"] == 0


@pytest.mark.parametrize("data,code", [
    pytest.param(b"name: a\ntype: script\nx: &anchor 1\ny: *anchor\n", RefusalCode.ALIAS, id="V21-yaml-alias"),
    pytest.param(b"name: a\nname: b\n", RefusalCode.DUPLICATE, id="V21-duplicate-key"),
    pytest.param(b"[1, 2]\n", RefusalCode.TYPE, id="V21-not-a-mapping"),
    pytest.param(b"name: a\nschema_version: '2.0'\n", RefusalCode.VERSION, id="V19-unsupported-version"),
])
def test_v19_v21_classified_bytes_are_parsed_without_sharing(tmp_path, monkeypatch, data, code):
    """V19/V21: the classified capture owns its parse; aliases and duplicates refuse."""
    from temper_ai.config.admission_capture import capture_classified_record
    guard = guarded(monkeypatch, data)
    reject(lambda: capture_classified_record(ContractCodec(SCHEMA), guard=guard, name="a",
                                             config_type="agent", launch_id="synthetic-launch"), code)


def test_v19_only_the_active_guard_may_capture_classified_bytes(tmp_path, monkeypatch):
    """V19: no DB fallback and no capture from a guard that is not the current one."""
    from temper_ai.config.admission_capture import capture_classified_record
    from temper_ai.spawner import box_guard
    guard = guarded(monkeypatch, b"name: a\n")
    monkeypatch.setattr(box_guard, "active", lambda: None)
    reject(lambda: capture_classified_record(ContractCodec(SCHEMA), guard=guard, name="a",
                                             config_type="agent", launch_id="synthetic-launch"),
           RefusalCode.ORIGIN)


# --- B2/B3: the world changes after an admitted run has started -------------

def set_meta(execution=EXECUTION, *, workflow=None, drop_admission=False, slot=None, **extra):
    """An outside writer changes the queued row the way the server would."""
    with get_session() as session:
        found = session.get(WorkflowRun, execution)
        meta = copy.deepcopy(found.spawner_metadata or {})
        meta.update(extra)
        if drop_admission:
            meta.pop("config_admission", None)
        if slot is not None:
            slot(meta["config_admission"])
        found.spawner_metadata = meta
        if workflow is not None:
            found.workflow_name = workflow
        session.add(found)
        session.commit()


def test_v17_v28_rows_change_after_submit_and_the_run_keeps_the_snapshot(tmp_path, monkeypatch, capsys):
    """V17/V28: run completes with original snapshot; ConfigStore.get 0 during worker.
    A second worker after completion is refused."""
    case, counters, b = control(tmp_path, monkeypatch)
    assert b.submit() == EXECUTION
    captured = counters.n["raw_read"]
    r = case.names[0]
    other = copy.deepcopy(case.raw[("agent", f"{r}_call_A1")])
    other["agent"]["single_call"]["model"] = "claude-opus-5-6"
    case.rewrite_row("agent", f"{r}_call_A1", other)
    case.rewrite_row("stage", r, delete=True)   # the row the graph came from is gone
    queue_and_claim(b)
    assert run_worker(b) == 0, row()
    assert row()["status"] == "completed"
    assert counters.n["raw_read"] == captured, "the worker read configuration again"
    assert counters.zero_transformed() == {"store_get": 0, "substitute": 0, "guard_config": 0, "expand": 0}
    assert counters.n["send"] == 3 and len(counters.sends) == 3
    final = stored_record()
    assert final["immutable"] == case.literal_queued_record()["immutable"]
    # V28: the same worker entry again, after the run completed.
    assert run_worker(b) == worker.BOX_REFUSED_EXIT
    assert capsys.readouterr().err.strip().endswith(f"candidate refused: {RefusalCode.GENERATION.value}")
    assert stored_record() == final and counters.n["send"] == 3


def test_v17_a_same_name_reimport_after_submit_is_never_read(tmp_path, monkeypatch):
    """V17: DB workflow/stage/agent/default rows re-imported under the same names after
    submission (as a bootstrap import would): the run continues on the original owned
    snapshot, with zero execution-path reads."""
    case, counters, b = control(tmp_path, monkeypatch)
    assert b.submit() == EXECUTION
    captured = counters.n["raw_read"]
    for (kind, name), body in list(case.raw.items()):
        changed = copy.deepcopy(body)
        changed[kind]["description"] = "re-imported"
        if kind == "workflow":
            changed[kind]["defaults"] = {"model": "claude-opus-5-6"}
        case.rewrite_row(kind, name, delete=True)
        with get_session() as session:
            session.add(Config(type=kind, name=name, schema_version="1.0", config=changed))
            session.commit()
    queue_and_claim(b)
    assert run_worker(b) == 0, recorded_failures()
    assert counters.n["raw_read"] == captured, "the worker read configuration again"
    assert counters.zero_transformed() == {"store_get": 0, "substitute": 0, "guard_config": 0, "expand": 0}
    assert sorted(s[:3] for s in counters.sends) == case.expected_claims()
    assert stored_record()["immutable"] == case.literal_queued_record()["immutable"]


def test_v21_source_objects_changed_after_capture_change_nothing(tmp_path, monkeypatch):
    """V21: External aliases cannot alter owned canonical bytes: every object the
    store handed to the capture is changed afterwards, and the run is unchanged."""
    case, counters, b = control(tmp_path, monkeypatch)
    original = ConfigStore.get_raw_record
    handed = []

    def keeping(self, name, kind, **kwargs):
        body, version = original(self, name, kind, **kwargs)
        handed.append(body)
        return body, version
    monkeypatch.setattr(ConfigStore, "get_raw_record", keeping)
    assert b.submit() == EXECUTION
    assert len(handed) == len(case.raw)
    for body in handed:
        inner = next(iter(body.values()))
        inner["name"] = "changed"
        for node in inner.get("nodes", []):
            node.setdefault("depends_on", []).append("changed")
        if "single_call" in inner:
            inner["single_call"]["slot"] = "A3"
    queue_and_claim(b)
    assert run_worker(b) == 0, recorded_failures()
    assert stored_record()["immutable"] == case.literal_queued_record()["immutable"]
    assert sorted(s[:3] for s in counters.sends) == case.expected_claims()


def test_v21_a_shared_nested_alias_in_a_raw_body_refuses(tmp_path, monkeypatch):
    """V21: aliased raw input rejects under the closed capture grammar rather than
    retaining identity: two nodes of one row share one (equal) mapping object."""
    case, counters, b = control(tmp_path, monkeypatch)
    original = ConfigStore.get_raw_record

    def aliasing(self, name, kind, **kwargs):
        body, version = original(self, name, kind, **kwargs)
        if kind == "stage":
            nodes = {n["name"]: n for n in body["stage"]["nodes"]}
            nodes["receipt"]["input_map"] = nodes["prepare"]["input_map"]
        return body, version
    monkeypatch.setattr(ConfigStore, "get_raw_record", aliasing)
    reject(b.submit, RefusalCode.ALIAS)
    assert row() is None


def test_v20_a_candidate_under_a_sealed_box_refuses_at_worker_entry(tmp_path, monkeypatch, capsys):
    """V20: MODE at worker entry before graph/claim; no candidate path under a sealed box."""
    case, counters, b = control(tmp_path, monkeypatch)
    assert b.submit() == EXECUTION
    queue_and_claim(b)
    monkeypatch.setattr("temper_ai.spawner.box_view.check_box", lambda: {"boundary": "sealed"})
    assert run_worker(b) == worker.BOX_REFUSED_EXIT
    assert capsys.readouterr().err.strip().endswith(f"candidate refused: {RefusalCode.MODE.value}")
    assert (counters.n["factory"], counters.n["claim"], counters.n["send"]) == (0, 0, 0)


def test_v29_a_candidate_row_carrying_resume_or_rerun_refuses(tmp_path, monkeypatch, capsys):
    """V29: MODE; fork/resume API fenced for candidates."""
    case, counters, b = control(tmp_path, monkeypatch)
    assert b.submit() == EXECUTION
    queue_and_claim(b)
    set_meta(start={"from": "checkpoint"})
    assert run_worker(b) == worker.BOX_REFUSED_EXIT
    assert capsys.readouterr().err.strip().endswith(f"candidate refused: {RefusalCode.MODE.value}")
    assert (counters.n["factory"], counters.n["claim"], counters.n["send"]) == (0, 0, 0)


def test_v29_a_fork_that_copies_the_admission_is_not_admitted(tmp_path, monkeypatch):
    """V29: a fork that copies the old admission to a new run needs its own externally
    admitted identity: even an authority that would vouch for the new run does not
    turn the copied record into an admission for it."""
    fork = "00000000-0000-4000-8000-000000000229"
    case, counters, b = control(tmp_path, monkeypatch)
    assert b.submit() == EXECUTION
    with get_session() as session:
        copied = session.get(WorkflowRun, EXECUTION).model_dump()
        copied["execution_id"] = fork
        session.add(WorkflowRun(**copied))
        session.commit()
    b.authority_for_run = lambda execution_uuid: b.authority
    reject(lambda: _claim_row(fork, candidate_bindings=b), RefusalCode.PROTECTED)
    assert (counters.n["factory"], counters.n["claim"], counters.n["send"]) == (0, 0, 0)


def test_v34_a_designated_workflow_without_an_admission_refuses(tmp_path, monkeypatch, capsys):
    """V34: MISSING; ordinary non-designated run unchanged."""
    case, counters, b = control(tmp_path, monkeypatch)
    boot = worker_harness(monkeypatch, tmp_path)
    assert b.submit() == EXECUTION
    queue_and_claim(b)
    set_meta(drop_admission=True)
    assert run_worker(b) == worker.BOX_REFUSED_EXIT
    assert capsys.readouterr().err.strip().endswith(f"candidate refused: {RefusalCode.MISSING.value}")
    boot.assert_not_called()
    # The same row, not designated: the ordinary path runs, and only the harness's
    # own mutable-bootstrap guard stops it.
    set_meta(workflow="ordinary-workflow")
    assert run_worker(b) == 2
    boot.assert_called_once()


def test_v31_an_outside_writer_cannot_replace_the_queued_record(tmp_path, monkeypatch, capsys):
    """V31: refused; original record kept."""
    case, counters, b = control(tmp_path, monkeypatch)
    assert b.submit() == EXECUTION
    before = stored_record()
    handle = ProcessHandle(kind=SpawnerKind.subprocess, handle="worker:synthetic",
                           metadata={"pid": 42, "config_admission": {"phase": "running"}})
    reject(lambda: _stamp_handle(EXECUTION, handle), RefusalCode.PROTECTED)
    assert stored_record() == before
    queue_and_claim(b)
    set_meta(slot=lambda record: record.update(format="candidate-admission-record/v2"))
    changed = stored_record()
    assert run_worker(b) == worker.BOX_REFUSED_EXIT
    assert capsys.readouterr().err.strip().endswith(f"candidate refused: {RefusalCode.VERSION.value}")
    assert stored_record() == changed, "a refused restore rewrote the record"
    assert (counters.n["factory"], counters.n["claim"], counters.n["send"]) == (0, 0, 0)


# --- B3/B4: the actual objects change under the use site --------------------

def load_mutation(change):
    """Change the restored actual graph before the scheduler ever walks it."""
    def after_load(nodes):
        change(nodes)
    return after_load


def mutate_slot(nodes):
    child(nodes, "call_A1").agent_config["single_call"]["slot"] = "A2"


def swap_native_maps(nodes):
    a1, a2 = child(nodes, "call_A1"), child(nodes, "call_A2")
    a1.agent_config, a2.agent_config = a2.agent_config, a1.agent_config


def drop_node(nodes):
    nodes[0].child_nodes = [n for n in nodes[0].child_nodes if n.name != "call_A3"]


def change_dependency(nodes):
    # The admitted chain is prepare -> A1 -> A2 -> A3 -> receipt; cutting one link
    # is a real change, which setting the dependency it already has would not be.
    child(nodes, "call_A3").config.depends_on = []


def rename_node(nodes):
    child(nodes, "call_A3").config.name = "call_A1"


@pytest.mark.parametrize("change", [
    pytest.param(mutate_slot, id="V03-slot-changed-after-resolution"),
    pytest.param(swap_native_maps, id="V04-maps-swapped-after-resolution"),
    pytest.param(drop_node, id="V15-node-removed-after-resolution"),
    pytest.param(change_dependency, id="V15-dependency-changed-after-resolution"),
    pytest.param(rename_node, id="V15-duplicate-name-after-resolution"),
])
def test_the_resolved_tree_is_mutated_after_the_load(tmp_path, monkeypatch, change):
    """V03/V04/V15: post-resolution actual change -> GRAPH before topology; zero claim."""
    case, counters, b = refused_in_run(tmp_path, monkeypatch, RefusalCode.GRAPH,
                                       after_load=load_mutation(change))
    assert (counters.n["factory"], counters.n["claim"], counters.n["send"]) == (0, 0, 0)


def test_v22_agent_config_changed_after_the_node_check_refuses_before_the_factory(tmp_path, monkeypatch):
    """V22: refuse before factory; create_agent 0 for node."""
    original = CandidateUse.node_context

    def node_context(self, node, context):
        ctx = original(self, node, context)
        if node.name == "prepare":
            node.agent_config = {**node.agent_config, "script_template": RECEIPT}
        return ctx
    monkeypatch.setattr(CandidateUse, "node_context", node_context)
    # The node check runs again inside before_factory and sees the whole actual
    # graph, so a changed agent config is a changed graph: GRAPH, not FIELDS.
    case, counters, b = refused_in_run(tmp_path, monkeypatch, RefusalCode.GRAPH)
    assert (counters.n["factory"], counters.n["claim"], counters.n["send"]) == (0, 0, 0)


def test_v24_a_sibling_capability_in_the_context_refuses(tmp_path, monkeypatch):
    """V24: sibling capability in context -> POSITION at B4."""
    original = CandidateUse.node_context

    def node_context(self, node, context):
        ctx = original(self, node, context)
        if node.name == "call_A2":
            sibling = self.binding((*tuple(context.node_path.split(".")), "call_A1"))
            return replace(ctx, admission=sibling)
        return ctx
    monkeypatch.setattr(CandidateUse, "node_context", node_context)
    case, counters, b = refused_in_run(tmp_path, monkeypatch, RefusalCode.POSITION)
    assert counters.n["send"] == 1, "only the first position may have sent"


def test_v24_a_wrong_valid_node_path_in_the_context_refuses(tmp_path, monkeypatch):
    """V24: a wrong but valid actual node path refuses at B4 actual use.

    The node is looked up under the path its context claims, and the node being run
    is not the admitted node at that path: GRAPH, one check before POSITION.
    """
    original = CandidateUse.node_context

    def node_context(self, node, context):
        ctx = original(self, node, context)
        if node.name == "call_A2":
            return replace(ctx, node_path=ctx.node_path.rsplit(".", 1)[0] + ".call_A1")
        return ctx
    monkeypatch.setattr(CandidateUse, "node_context", node_context)
    case, counters, b = refused_in_run(tmp_path, monkeypatch, RefusalCode.GRAPH)
    assert counters.n["send"] == 1, "only the first position may have sent"


def test_v22_a_sibling_nested_mapping_changed_before_the_factory_refuses(tmp_path, monkeypatch):
    """V22: a sibling's nested mapping changed in place between validation and the
    factory refuses before the factory: the check re-reads the whole actual graph."""
    original = CandidateUse.node_context

    def node_context(self, node, context):
        ctx = original(self, node, context)
        if node.name == "call_A1":
            sibling = next(n for n in self._nodes[0].child_nodes if n.name == "call_A2")
            sibling.agent_config["single_call"]["slot"] = "A3"
        return ctx
    monkeypatch.setattr(CandidateUse, "node_context", node_context)
    case, counters, b = refused_in_run(tmp_path, monkeypatch, RefusalCode.GRAPH)
    # Only prepare's factory ran (before the change); call_A1 never reached its own.
    assert (counters.n["factory"], counters.n["claim"], counters.n["send"]) == (1, 0, 0)


def wrong_class(agent, config):
    return agent if config.get("type") != "single_call" else object()


def changed_config(agent, config):
    if config.get("type") == "single_call":
        agent.config = {**agent.config, "model": "claude-opus-5-6"}
    return agent


@pytest.mark.parametrize("after", [
    pytest.param(wrong_class, id="V23-factory-returns-another-class"),
    pytest.param(changed_config, id="V23-factory-changed-the-agent-config"),
])
def test_v23_the_factory_result_is_checked_before_the_agent_runs(tmp_path, monkeypatch, after):
    """V23: after_factory refuse; zero claim."""
    case, counters, b = refused_in_run(tmp_path, monkeypatch, RefusalCode.FIELDS, after_factory=after)
    assert (counters.n["claim"], counters.n["send"]) == (0, 0)


def test_v23_a_retained_agent_config_changed_before_entry_refuses_at_the_claim(tmp_path, monkeypatch):
    """V23: retained agent config changed before entry -> FIELDS at claim_slot; zero claim."""
    original = SingleCallAgent.run

    def run(self, *args, **kwargs):
        self.config = {**self.config, "model": "claude-opus-5-6"}
        return original(self, *args, **kwargs)
    monkeypatch.setattr(SingleCallAgent, "run", run)
    case, counters, b = refused_in_run(tmp_path, monkeypatch, RefusalCode.FIELDS)
    assert (counters.n["claim"], counters.n["send"]) == (0, 0)


# --- B5: readiness, generation and the claim --------------------------------

def chmod_roots(b, binding):
    for position in binding.descriptor.value()["positions"]:
        if tuple(position["preparation_path"]) == binding.node_path:
            os.chmod(position["root_policy"]["path"], 0o750)


def replace_root(b, binding):
    for position in binding.descriptor.value()["positions"]:
        if tuple(position["preparation_path"]) != binding.node_path:
            continue
        root = Path(position["root_policy"]["path"])
        moved = root.with_name(root.name + "-old")
        if moved.exists():
            continue   # the positions of one record share the one root
        os.rename(root, moved)
        root.mkdir(mode=0o700)
        for item in moved.iterdir():
            (root / item.name).write_bytes(item.read_bytes())
            (root / item.name).chmod(0o600)


def symlink_parent(b, binding):
    """The roots' parent becomes a symlink to the same directory: every path still resolves."""
    parent = b.case.parent
    if parent.is_symlink():
        return
    moved = parent.with_name(parent.name + "-moved")
    os.rename(parent, moved)
    parent.symlink_to(moved, target_is_directory=True)


@pytest.mark.parametrize("after_prepare", [
    pytest.param(chmod_roots, id="V25-root-mode-changed-after-readiness"),
    pytest.param(replace_root, id="V25-root-replaced-after-readiness"),
    pytest.param(symlink_parent, id="V25-symlink-parent-after-readiness"),
])
def test_v25_the_root_changes_between_readiness_and_the_claim(tmp_path, monkeypatch, after_prepare):
    """V25: READINESS at B5, claims 0, sends 0."""
    case, counters, b = refused_in_run(tmp_path, monkeypatch, RefusalCode.READINESS,
                                       after_prepare=after_prepare)
    assert (counters.n["claim"], counters.n["send"]) == (0, 0)


def test_v27_a_preparer_that_does_not_promise_durability_refuses(tmp_path, monkeypatch):
    """V27: missing receipt / durable False -> READINESS; no claim on an unpromised root.

    The contract refuses one step earlier than the matrix predicted: a receipt that
    does not promise durability is not a readiness receipt at all, so it is refused
    where it is decoded (SCHEMA) and never reaches the readiness comparison.
    """
    case, counters, b = control(tmp_path, monkeypatch)
    b.durable = False
    assert b.submit() == EXECUTION
    queue_and_claim(b)
    assert run_worker(b) == 1
    assert RefusalCode.SCHEMA.value in recorded_failures(), recorded_failures()
    assert (counters.n["claim"], counters.n["send"]) == (0, 0)


def test_v27_an_existing_slot_claim_is_never_taken_again(tmp_path, monkeypatch):
    """V27: prior slot claim file exists -> no new claim, no send, old claim kept."""
    case, counters, b = control(tmp_path, monkeypatch)
    root = Path(case.roots[case.names[0]])
    for slot in SLOTS:
        (root / f"{slot}.claim").write_bytes(b"an older claim")
    assert b.submit() == EXECUTION
    queue_and_claim(b)
    assert run_worker(b) == 1
    assert row()["status"] == "failed"
    assert counters.n["send"] == 0
    for slot in SLOTS:
        assert (root / f"{slot}.claim").read_bytes() == b"an older claim"


def drop_receipts(verified, b):
    return replace(verified, receipts=())


def stale_receipts(verified, b):
    """Receipts measured for the queued generation, not the running one."""
    return replace(verified, receipts=tuple(
        b.codec.readiness(canonical_bytes(r.value() | {"dispatch_nonce": QUEUED_NONCE}))
        for r in verified.receipts))


@pytest.mark.parametrize("change", [
    pytest.param(drop_receipts, id="V27-missing-receipt"),
    pytest.param(stale_receipts, id="V27-stale-receipt"),
])
def test_v27_a_missing_or_stale_receipt_refuses(tmp_path, monkeypatch, change):
    """V27: missing/stale receipt -> REFUSE new claim/send."""
    original = EntryBindings.preparer

    def preparer(self, binding, result, checkpoint_service):
        verified = change(original(self, binding, result, checkpoint_service), self)
        self.issued.append(verified)
        return verified
    monkeypatch.setattr(EntryBindings, "preparer", preparer)
    case, counters, b = refused_in_run(tmp_path, monkeypatch, RefusalCode.READINESS)
    assert (counters.n["claim"], counters.n["send"]) == (0, 0)


class WorkerDied(BaseException):
    """The worker process dies mid-run: nothing in the engine may catch this."""


def test_v28_a_worker_that_dies_mid_run_is_not_replayed(tmp_path, monkeypatch, capsys):
    """V28: completed leaves not replayed: the same worker entry after the worker died
    mid-run refuses, sends nothing again and leaves the claims as they were.

    The second entry proposes a new dispatch generation, but the record still holds
    the readiness the dead worker bound under its own generation, and the contract
    refuses a record whose readiness belongs to another generation: the roots are
    not trusted again (READINESS at worker entry, before anything loads).
    """
    case, counters, b = control(tmp_path, monkeypatch)
    send = _Attempt.call

    def dying(state):
        if counters.n["send"] == 1:
            raise WorkerDied()
        send(state)
    monkeypatch.setattr(_Attempt, "call", dying)
    assert b.submit() == EXECUTION
    queue_and_claim(b)
    with pytest.raises(WorkerDied):
        run_worker(b)
    root = Path(case.roots[case.names[0]])
    claims = sorted(p.name for p in root.glob("*.claim"))
    record = stored_record()
    assert record["readiness"] and all(
        r["dispatch_nonce"] == record["dispatch"]["dispatch_nonce"] for r in record["readiness"])
    capsys.readouterr()
    assert run_worker(b) == worker.BOX_REFUSED_EXIT
    assert capsys.readouterr().err.strip().endswith(f"candidate refused: {RefusalCode.READINESS.value}")
    assert counters.n["send"] == 1, "a completed leaf was sent again"
    assert claims == ["A1.claim", "A2.claim"]
    assert sorted(p.name for p in root.glob("*.claim")) == claims
    assert stored_record() == record


def bump_dispatch(b, binding):
    """A replacement generation becomes current while this one is preparing."""
    set_meta(slot=lambda record: record["dispatch"].update(
        dispatch_nonce="00000000-0000-4000-8000-000000000099", running_attempt=2,
        previous_nonce=record["dispatch"]["dispatch_nonce"]))


def test_v30_a_replacement_generation_becomes_current_mid_run(tmp_path, monkeypatch):
    """V30: GENERATION at claim, claims 0; the stale worker binds nothing."""
    case, counters, b = refused_in_run(tmp_path, monkeypatch, RefusalCode.GENERATION,
                                       after_prepare=bump_dispatch)
    assert (counters.n["claim"], counters.n["send"]) == (0, 0)
    assert stored_record()["readiness"] == [], "a stale generation wrote readiness"


def test_v36_a_native_failure_after_the_claim_is_honest_and_final(tmp_path, monkeypatch):
    """V36: FAILED honestly, claim stays, sends 0, no retry."""
    case, counters, b = control(tmp_path, monkeypatch)
    calls = []

    def failing(state):
        calls.append(state.fixed["slot"])
        raise RuntimeError("synthetic authentication failure")
    monkeypatch.setattr(_Attempt, "call", failing)
    assert b.submit() == EXECUTION
    queue_and_claim(b)
    assert run_worker(b) == 1
    assert row()["status"] == "failed"
    assert counters.n["send"] == 0 and calls == [SLOTS[0]], "the failed slot was tried again"
    root = Path(case.roots[case.names[0]])
    assert (root / f"{SLOTS[0]}.claim").exists(), "the claim was given back after a failure"
    assert not (root / f"{SLOTS[1]}.claim").exists()


def test_v33_two_admissions_in_one_process_share_nothing(tmp_path, monkeypatch):
    """V33: separate fresh loaders/contexts, own roots/configs only."""
    other = "00000000-0000-4000-8000-000000000233"
    case, counters, b = control(tmp_path, monkeypatch)
    assert b.submit() == EXECUTION
    queue_and_claim(b)
    assert run_worker(b) == 0, row()
    second = Case(tmp_path, 1, prefix="s", execution=other)
    b2 = submit_case(second)
    assert run_worker(b2, other) == 0, row(other)
    assert b.runner is not b2.runner and b.uses[0] is not b2.uses[0]
    first_roots = {s[0] for s in counters.sends[:3]}
    second_roots = {s[0] for s in counters.sends[3:]}
    assert first_roots and second_roots and not (first_roots & second_roots)
    assert sorted(s[:3] for s in counters.sends[:3]) == case.expected_claims()
    assert sorted(s[:3] for s in counters.sends[3:]) == second.expected_claims()


def test_v33_overlapping_snapshot_loads_ignore_the_same_legacy_loader(tmp_path, monkeypatch):
    """V33: overlap the actual B2 loads, not database transactions on SQLite's one fd.

    Both admissions receive the same old RunnerContext and its aliased mutable
    defaults/overrides. A barrier inside the real snapshot loader proves both
    loads are in flight together. Actual graph projections are checked against
    the two independently written literal descriptors, never against one another.
    Whole submit-to-claim isolation is checked by the preceding sequential case.
    """
    from temper_ai.config import candidate_admission as candidate
    from temper_ai.stage.loader import GraphLoader

    first, counters, left = control(tmp_path, monkeypatch)
    assert left.submit() == first.execution
    second = Case(tmp_path, 1, prefix="parallel", execution="00000000-0000-4000-8000-000000000234")
    second.store_rows()
    right = EntryBindings(second)
    assert right.submit() == second.execution
    records = [b.codec.record(canonical_bytes(stored_record(b.case.execution)), b.authority)
               for b in (left, right)]
    captured = counters.n["raw_read"]

    old_store = Mock()
    old_store.get.side_effect = AssertionError("shared mutable store reached")
    old_loader = GraphLoader(old_store)
    old_loader._defaults = old_loader._overrides = {"model": "unadmitted-shared-model"}
    old_loader.load_workflow = Mock(side_effect=AssertionError("shared mutable loader reached"))
    shared = RunnerContext(config_store=old_store, graph_loader=old_loader, llm_providers={},
                           memory_service=None)
    entered = {}
    overlap = Barrier(2, timeout=30)
    original = candidate._SnapshotLoader.load_workflow

    def load(loader, workflow_name, *args, **kwargs):
        entered[workflow_name] = loader
        overlap.wait()
        return original(loader, workflow_name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(candidate._SnapshotLoader, "load_workflow", load)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(b.load_snapshot, record, shared)
                       for b, record in zip((left, right), records, strict=True)]
            actual = [future.result() for future in futures]

    assert set(entered) == {first.workflow, second.workflow}
    loaders = [entered[c.workflow] for c in (first, second)]
    assert loaders[0] is not loaders[1]
    assert loaders[0].config_store is not loaders[1].config_store
    assert loaders[0]._defaults is not loaders[1]._defaults
    assert loaders[0]._overrides is not loaders[1]._overrides
    for b, (nodes, workflow) in zip((left, right), actual, strict=True):
        assert project_graph(nodes, workflow, source=b.source).wire == text(b.case.descriptor["graph"]).encode()
    assert actual[0][0][0] is not actual[1][0][0]
    assert actual[0][1] is not actual[1][1]
    old_store.get.assert_not_called()
    old_loader.load_workflow.assert_not_called()
    assert counters.n["raw_read"] == captured
    assert counters.zero_transformed() == {"store_get": 0, "substitute": 0, "guard_config": 0, "expand": 0}
    assert (counters.n["factory"], counters.n["claim"], counters.n["send"]) == (0, 0, 0)


# ---------------------------------------------------------------------------
# Bites for V1's own glue edits (docs/candidate-admission-verification.md)
# ---------------------------------------------------------------------------

def ordinary_context(**fields):
    """A context as any ordinary run builds it, plus whatever a case sets."""
    return ExecutionContext(run_id=EXECUTION, workflow_name="w", node_path="n", agent_name="a",
                            event_recorder=Mock(), tool_executor=Mock(), **fields)


def test_g1_the_runtime_only_admission_fields_are_typed_exactly(tmp_path, monkeypatch):
    """Glue G1 bite: the context's admission triplet is typed, never duck-typed.

    T1 declared `admission` alone; T3's use-site checks also read `admission_hooks`
    and `admission_required`, so V1 added both with T1's exact-type rule. Without a
    check, a look-alike hooks object or a truthy non-bool would reach the use site.
    An ordinary context sets none of the three and stays untouched.
    """
    plain = ordinary_context()
    assert (plain.admission, plain.admission_hooks, plain.admission_required) == (None, None, False)
    reject(lambda: ordinary_context(admission=object()), RefusalCode.TYPE)
    reject(lambda: ordinary_context(admission_hooks=object()), RefusalCode.TYPE)
    reject(lambda: ordinary_context(admission_required=1), RefusalCode.TYPE)


def test_g2_the_generation_fence_compares_the_whole_stored_generation(tmp_path, monkeypatch):
    """Glue G2 bite: each part of the binding is compared with what is stored.

    T3 asks T2 for "the record that is current now", and acts on it under the row
    lock. Dropping any one comparison lets a stale or foreign binding bind
    readiness or authorize a claim on a generation that is not its own. The phase
    comparison cannot be isolated: the contract only accepts a queued record with
    running_attempt 0, and a binding's attempt is always >= 1, so the attempt
    comparison already covers it; it stays as defence in depth.
    """
    other = "00000000-0000-4000-8000-000000000233"
    case, counters, b = control(tmp_path, monkeypatch)
    # A whole second admission, so the stale bindings below are real typed
    # objects: the binding itself refuses anything else with TYPE.
    second = Case(tmp_path, 1, prefix="g", execution=other)
    b2 = submit_case(second)
    assert run_worker(b2, other) == 0, recorded_failures(other)
    foreign = b2.uses[0].binding((second.names[0],))
    checked = []

    def probe(_config):
        """Runs mid-run, between nodes: the generation is current right now."""
        if checked:
            return
        mine = b.uses[0].binding((case.names[0],))
        # The action is handed the record held under the row lock, as stored.
        held = b.store.current_generation(mine, lambda record, session: record.value()["dispatch"])
        assert held == stored_record()["dispatch"] and held["phase"] == "running"
        reject(lambda: b.store.current_generation(mine.descriptor, lambda *_: None), RefusalCode.TYPE)
        for stale in (replace(mine, dispatch=replace(mine.dispatch, dispatch_nonce=QUEUED_NONCE)),
                      replace(mine, dispatch=replace(mine.dispatch, running_attempt=2)),
                      replace(mine, descriptor=foreign.descriptor),
                      replace(mine, closure=foreign.closure),
                      replace(mine, graph_sha256=foreign.graph_sha256)):
            reject(lambda binding=stale: b.store.current_generation(binding, lambda *_: None),
                   RefusalCode.GENERATION)
        checked.append(mine.position_id)

    counters.on_factory = probe
    assert b.submit() == EXECUTION
    queue_and_claim(b)
    assert run_worker(b) == 0, recorded_failures()
    assert checked, "the fence was never probed"


@pytest.mark.parametrize("scope,key,value,code", [
    pytest.param("node", "tools", None, RefusalCode.SCHEMA, id="V14-node-tools-null"),
    pytest.param("node", "tools", [], RefusalCode.SCHEMA, id="V14-node-tools-empty"),
    pytest.param("node", "tools", ["bash"], RefusalCode.SCHEMA, id="V14-node-tools-nonempty"),
    pytest.param("node", "memory", None, RefusalCode.SCHEMA, id="V14-node-memory-null"),
    pytest.param("node", "memory", {}, RefusalCode.SCHEMA, id="V14-node-memory-empty"),
    pytest.param("node", "memory", {"enabled": True}, RefusalCode.SCHEMA, id="V14-node-memory-nonempty"),
    pytest.param("node", "fallback", None, RefusalCode.FIELDS, id="V14-node-fallback-null"),
    pytest.param("node", "fallback", [], RefusalCode.FIELDS, id="V14-node-fallback-list"),
    pytest.param("node", "fallback", {}, RefusalCode.FIELDS, id="V14-node-fallback-object"),
    pytest.param("node", "fallback", [{"model": "other"}], RefusalCode.FIELDS, id="V14-node-fallback-nonempty"),
    pytest.param("workflow", "memory", None, RefusalCode.SCHEMA, id="V14-workflow-memory-null"),
    pytest.param("workflow", "memory", {}, RefusalCode.SCHEMA, id="V14-workflow-memory-empty"),
    pytest.param("workflow", "memory", {"enabled": True}, RefusalCode.SCHEMA, id="V14-workflow-memory-nonempty"),
    pytest.param("workflow", "fallback", None, RefusalCode.FIELDS, id="V14-workflow-fallback-null"),
    pytest.param("workflow", "fallback", [], RefusalCode.FIELDS, id="V14-workflow-fallback-list"),
    pytest.param("workflow", "fallback", {}, RefusalCode.FIELDS, id="V14-workflow-fallback-object"),
    pytest.param("defaults", "fallback", None, RefusalCode.FIELDS, id="V14-default-fallback-null"),
    pytest.param("defaults", "fallback", [], RefusalCode.FIELDS, id="V14-default-fallback-list"),
    pytest.param("defaults", "fallback", {}, RefusalCode.FIELDS, id="V14-default-fallback-object"),
    pytest.param("defaults", "fallback", [{"model": "other"}], RefusalCode.FIELDS, id="V14-default-fallback-nonempty"),
    pytest.param("override", "tools", None, RefusalCode.SCHEMA, id="V14-override-tools-null"),
    pytest.param("override", "memory", None, RefusalCode.SCHEMA, id="V14-override-memory-null"),
    pytest.param("loop", "loop_to", "prepare", RefusalCode.SCHEMA, id="V11-real-loop"),
    pytest.param("loop", "loop_to", "", RefusalCode.SCHEMA, id="V11-empty-loop-target"),
])
def test_raw_profile_otherwise_valid_approved_controls(tmp_path, monkeypatch, scope, key, value, code):
    """The literal V11/V14 refusal must be at B1, before any expansion/factory.

    The descriptor includes all effective defaults and settings independently.
    Disabling only the raw stage must then admit the SAME bytes; a stale digest,
    unrelated type failure or incorrect graph oracle cannot masquerade as proof.
    This mutation ends at queue submission: no worker, claim, or real sender runs.
    """
    from temper_ai.config import candidate_admission as candidate

    def declare(case):
        workflow = case.raw[("workflow", case.workflow)]["workflow"]
        if scope == "node":
            target = leaf(case, "prepare")
        elif scope == "loop":
            target = leaf(case, "call_A1")
            target["max_loops"] = 2
        elif scope == "override":
            target = workflow["nodes"][0]
        else:
            target = workflow.setdefault("defaults", {}) if scope == "defaults" else workflow
        target[key] = copy.deepcopy(value)

    def expected(d):
        # Literal effective settings for this fixture, NOT loader/compiler output.
        graph = d["graph"]
        workflow = json.loads(graph["workflow_json"])
        if scope == "workflow" and key == "memory":
            workflow[key] = value
        elif scope == "defaults":
            workflow["defaults"] = {key: value}
            for node in graph["nodes"]:
                if node["factory"] and node["factory"]["type"] == "script":
                    config = json.loads(node["factory"]["config_json"])
                    config[key] = value
                    node["factory"]["config_json"] = text(config)
        elif scope == "node":
            prepare = next(n for n in graph["nodes"] if n["path"][-1] == "prepare")
            if key == "fallback":
                # Unknown to NodeConfig: absent from the effective projection,
                # but still present, signed and forbidden in the raw snapshot.
                node = json.loads(prepare["node_json"])
                del node[key]
                prepare["node_json"] = text(node)
                stage = json.loads(graph["nodes"][0]["node_json"])
                del stage["nodes"][0][key]
                graph["nodes"][0]["node_json"] = text(stage)
                del workflow["nodes"][0]["nodes"][0][key]
            elif value is not None:
                config = json.loads(prepare["factory"]["config_json"])
                config[key] = value
                prepare["factory"]["config_json"] = text(config)
        graph["workflow_json"] = text(workflow)

    case, counters, b = refused_at_submit(tmp_path, monkeypatch, code,
                                          approved=declare, descriptor_edit=expected)
    assert counters.n["raw_read"] == len(case.raw)
    assert counters.n["expand_calls"] == 0
    monkeypatch.setattr(candidate, "validate_raw", lambda *args: None)
    assert b.submit() == EXECUTION, "this control must be otherwise valid, not a graph mismatch"
    assert stored_record()["immutable"] == case.literal_queued_record()["immutable"]
    assert counters.n["expand_calls"] > 0
    assert (counters.n["factory"], counters.n["claim"], counters.n["send"], counters.n["process"]) == (0, 0, 0, 0)


@pytest.mark.parametrize("key,value", [
    pytest.param("on_failure", "hold", id="pinned-on-failure-hold"),
    pytest.param("on_failure", "cleanup", id="pinned-on-failure-cleanup"),
    pytest.param("on_failure", None, id="pinned-on-failure-null"),
    pytest.param("loop_to", None, id="no-loop-target"),
    pytest.param("max_loops", 1, id="default-count-without-target"),
    pytest.param("max_loops", 2, id="count-without-target"),
    pytest.param("undoes", ["prepare"], id="pinned-cleanup"),
    pytest.param("gate", False, id="pinned-gate-false"),
    pytest.param("gate", True, id="pinned-gate-true"),
    pytest.param("renamed_from", ["old_call"], id="pinned-rename"),
])
def test_supported_node_policy_is_pinned_in_the_approved_descriptor(
        tmp_path, monkeypatch, key, value):
    """V11/V14 clean twin: on_failure/undoes are cleanup, not LLM fallback.

    Absent tools/memory/fallback keys and an absent/null loop target are eligible.
    Ordinary node policies remain in the full literal projection, never dropped
    from comparison. Architecture's ruling preserves these cases, not raw memory.
    """
    def declare(case):
        leaf(case, "call_A1")[key] = value

    case, counters, b = control(tmp_path, monkeypatch, approved=declare)
    assert b.submit() == EXECUTION
    admitted = json.loads(stored_record()["immutable"]["descriptor_json"])
    node = next(n for n in admitted["graph"]["nodes"] if n["path"][-1].endswith("call_A1"))
    assert json.loads(node["node_json"])[key] == value
    # The raw presence itself was admitted, exactly as declared (pinned by its digest).
    stage = next(r for r in stored_record()["immutable"]["raw_records"] if r["kind"] == "stage")
    declared = next(n for n in json.loads(stage["config_json"])["stage"]["nodes"] if n["name"] == "call_A1")
    assert key in declared and declared[key] == value
    assert {"tools", "memory", "fallback"}.isdisjoint(declared)


@pytest.mark.parametrize("key,value", [
    ("on_failure", "cleanup"), ("undoes", ["prepare"]), ("gate", True), ("renamed_from", ["old_call"]),
])
def test_v15_supported_policies_cannot_mutate_after_approval(tmp_path, monkeypatch, key, value):
    refused_at_submit(tmp_path, monkeypatch, RefusalCode.DIGEST, db=prohibited(key, value))


def test_v35_diagnostics_carry_only_fixed_code_values(tmp_path, monkeypatch, capsys):
    """V35: run error/log/stderr/events contain only fixed code values, no body values."""
    case, counters, b = refused_in_run(tmp_path, monkeypatch, RefusalCode.GENERATION,
                                       after_prepare=bump_dispatch)
    # Config body values, not run values: the run's own inputs and outputs (the
    # label the workflow was started with) belong in its diagnostics.
    bodies = [PROMPT.decode(), PREPARE, RECEIPT, str(case.roots[case.names[0]]),
              case.native(case.names[0], "A1")["prompt_path"],
              case.raw[("agent", f"{case.names[0]}_call_A1")]["agent"]["model"]]
    written = capsys.readouterr()
    places = {"stderr": written.err, "stdout": written.out,
              "error": json.dumps(row()["error"]), "events": json.dumps(all_event_data())}
    for path in sorted((tmp_path / "logs").rglob("*")):
        if path.is_file():
            places[str(path)] = path.read_text(errors="replace")
    for where, written_text in places.items():
        for body in bodies:
            assert body not in written_text, f"{where} carries a body value"
    # One fixed code and no other; what else is recorded is the engine's ordinary
    # summary of how many nodes failed, which names nodes and no body value.
    recorded = recorded_failures()
    assert {m for m in recorded if m in {c.value for c in RefusalCode}} == {RefusalCode.GENERATION.value}
    assert RefusalCode.GENERATION.value in recorded


# ---------------------------------------------------------------------------
# Carried from T2's handoff: S3 (Architecture #321) and S4 (Architecture #325)
# ---------------------------------------------------------------------------

def test_s3_the_lane_check_at_install_reads_the_graph_the_run_loads(tmp_path, monkeypatch):
    """S3: captured_nodes comes from the same verified capture bytes load_snapshot runs.

    T2 decides the lane at install on the adapter's captured_nodes, and refuses a
    Pi graph there (an unmarked Pi row would be claimed by the main watcher). That
    decision is only as good as the graph it reads: here the graph the lane check
    saw at submit and the graph the worker ran are both exactly the approved
    literal graph, read from the same stored record.
    """
    seen = []
    original = a.lane_for

    def lane_for(nodes):
        nodes = tuple(nodes)
        seen.append(nodes)
        return original(nodes)
    monkeypatch.setattr(a, "lane_for", lane_for)
    case, counters, b = control(tmp_path, monkeypatch, records=2)
    assert b.submit() == EXECUTION
    queue_and_claim(b)
    assert run_worker(b) == 0, recorded_failures()
    assert len(seen) == 1, "the lane is decided once, at install"
    run_nodes, workflow = b.loaded[stored_record()["immutable"]["descriptor_sha256"]]
    approved = canonical_bytes(case.descriptor["graph"])
    assert project_graph(list(seen[0]), workflow, source=b.source).wire == approved
    assert project_graph(run_nodes, workflow, source=b.source).wire == approved


PI_STEP = {"type": "pi", "role": "scout", "provider": "openai-codex", "model": "gpt-6.1-sol"}


def pi_call(case):
    """call_A1 becomes a Pi step, written as T2's own Pi capture writes one."""
    name = f"{case.names[0]}_call_A1"
    case.raw[("agent", name)] = {"agent": {"name": name, **PI_STEP}}


def pi_factory(descriptor):
    """The oracle written faithfully for a Pi step: the Pi factory, no native position."""
    node = next(n for n in descriptor["graph"]["nodes"] if n["path"][-1] == "call_A1")
    node["factory"] = node["factory"] | {"type": "pi", "class_name": "temper_ai.pi_agent.host.PiHost"}
    native_label(descriptor)


def native_label(descriptor):
    """No native position for the Pi step; its factory keeps whatever label it has."""
    descriptor["positions"] = [p for p in descriptor["positions"] if p["node_path"][-1] != "call_A1"]


def db_pi_call(case):
    pi_call(case)


@pytest.mark.parametrize("build,code,captured", [
    # The database row became a Pi step after approval: T1's pinned raw digest.
    pytest.param({"db": db_pi_call}, RefusalCode.DIGEST, True, id="S3-database-row-becomes-pi"),
    # The authority signed a Pi step, written faithfully: the wire schema's factory
    # types are script and single_call only.
    pytest.param({"approved": pi_call, "descriptor_edit": pi_factory}, RefusalCode.SCHEMA, False,
                 id="S3-approved-pi-step"),
    # The authority signed a Pi config under a native factory label: the contract's
    # factory/config agreement.
    pytest.param({"approved": pi_call, "descriptor_edit": native_label}, RefusalCode.GRAPH, False,
                 id="S3-approved-pi-under-native-label"),
])
def test_s3_a_pi_capture_is_refused_through_the_real_adapter(tmp_path, monkeypatch, build, code, captured):
    """S3: a Pi capture never reaches the queue through the real adapter.

    It is refused before T2's install, by the contract or by T1's capture, so the
    install's own lane check is a second line the real adapter cannot reach with
    a Pi graph; S4 pins that line on its own.
    """
    case, counters, b = refused_at_submit(tmp_path, monkeypatch, code, **build)
    assert ("capture" in b.events) is captured
    assert counters.n["raw_read"] == (len(case.raw) if captured else 0)


def _install_in_a_committing_caller(b):
    """install called directly, in a session that catches the refusal and then commits."""
    with get_session() as session:
        with pytest.raises(AdmissionRefused) as err:
            b.store.install(admission=b.queued, transaction=session)
    return err.value.code


@pytest.mark.parametrize("pi,code", [
    pytest.param(False, RefusalCode.AUTHORITY, id="S4-empty-capture"),
    pytest.param(True, RefusalCode.MODE, id="S4-pi-graph"),
])
def test_s4_install_refuses_before_the_insert_even_when_the_caller_commits(tmp_path, pi, code):
    """S4: both install refusals come before the insert, not just before a rollback.

    Through submit_candidate any refusal rolls the whole session back, so a check
    moved after the insert would still write nothing there. A caller that catches
    the refusal and commits (a batch that skips refused candidates) would commit
    that row. T2's synthetic captured graphs, since the real adapter cannot
    produce a Pi graph (S3 above); Architecture's template probe_test_zz_arch325.py.
    """
    from tests.test_runner.test_candidate_admission_transport import (
        SyntheticBindings,
        _captured_graph,
        row_snapshot,
    )
    b = SyntheticBindings()
    b.nodes = _captured_graph(tmp_path, pi=True) if pi else ()
    assert _install_in_a_committing_caller(b) == code
    assert b.events[-1] == "verify-install"
    assert row_snapshot() is None
