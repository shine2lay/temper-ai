"""T2 synthetic transport evidence, NOT T1/T3 composition or runtime authority.

Inputs/expected bytes use #192's literal fixtures and independent stdlib hashing;
no production normalizer manufactures the expected answers. No model or live DB.
The PG branches run in the normal remote test-postgres tier, never local PG.
"""
from __future__ import annotations

import argparse
import copy
import functools
import hashlib
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlmodel import select

from temper_ai.api.caller import Caller, acting_as, bound
from temper_ai.cli import run_workflow as worker
from temper_ai.cli.watch_queue import _claim_row, _stamp_handle, _unclaim
from temper_ai.config.admission_contract import (
    RESERVED_KEY,
    SUPPORTED_MODE,
    AdmissionRecord,
    AdmissionRefused,
    ContractCodec,
    DescriptorAuthority,
    FrozenJSON,
    RefusalCode,
    RootReadiness,
)
from temper_ai.database import get_database, get_session
from temper_ai.runner import admission as a
from temper_ai.runner.models import WorkflowRun
from temper_ai.runner.queue import queue_run, queue_run_in
from temper_ai.spawner.box_profile import BOUNDARY_ENV
from temper_ai.worker_proto import ProcessHandle as RunHandle
from temper_ai.worker_proto import SpawnerKind
from tests.test_config.test_candidate_admission_contract import (
    SCHEMA,
    dump,
    load,
    record_input,
)

EXECUTION = "00000000-0000-4000-8000-000000000001"
NATIVE_PROVENANCE = object()


def independent_hash(domain, value):
    return hashlib.sha256(b"temper-admission/v1\0" + domain + b"\0" + dump(value)).hexdigest()


class SyntheticBindings:
    """Test-only independently pinned fixture registry, never production authority."""

    def __init__(self, *, http=False):
        value = record_input(root=True)
        descriptor = json.loads(value["immutable"]["descriptor_json"])
        if http:
            # The transport documents this exact HTTP mapping, including defaults.
            # Literal expectation, deliberately not RunRequest.model_dump().
            descriptor["request_options_json"] = dump({
                "workflow": descriptor["workflow_name"],
                "workspace_path": descriptor["workspace_path"],
                "inputs": json.loads(descriptor["metadata_inputs_json"]),
                "notify": None,
            }).decode()
            descriptor["source"]["field_sets"]["request"] = ["inputs", "notify", "workflow", "workspace_path"]
            value["immutable"]["descriptor_json"] = dump(descriptor).decode()
            value["immutable"]["descriptor_sha256"] = independent_hash(b"descriptor", descriptor)
            value["immutable_sha256"] = independent_hash(b"immutable", value["immutable"])
        self.descriptor = descriptor
        self.queued = AdmissionRecord(dump(value))
        running = copy.deepcopy(value)
        running["dispatch"] = {
            "phase": "running", "running_attempt": 1,
            "previous_nonce": "00000000-0000-4000-8000-000000000002",
            "dispatch_nonce": "00000000-0000-4000-8000-000000000003",
            "worker_label": "synthetic-worker",
        }
        self.running = AdmissionRecord(dump(running))
        readiness = load("readiness.json")
        readiness["descriptor_sha256"] = value["immutable"]["descriptor_sha256"]
        self.ready = RootReadiness(dump(readiness))
        self.authority = DescriptorAuthority(
            value["immutable"]["descriptor_sha256"], independent_hash(b"source", descriptor["source"]),
            "synthetic-author", "synthetic-receipt",
        )
        self.source = FrozenJSON(dump(descriptor["source"]))
        self.store = a.DbAdmissionTransport(
            codec=ContractCodec(SCHEMA), authority=self.authority,
            current_source=lambda: self.source, installation=self, preparation=self,
            worker_identity=lambda: "synthetic-worker",
        )
        self.events = []
        self.trusted_preparation = NATIVE_PROVENANCE
        # The synthetic capture's graph: real, non-empty, no Pi step unless a test sets one.
        self.nodes = _plain_capture()

    def designated(self, name):
        return name == self.descriptor["workflow_name"]

    def authority_for_submit(self, caller, workflow_name):
        assert caller.label == "synthetic-author"
        if workflow_name != self.descriptor["workflow_name"]:
            from temper_ai.config.admission_contract import RefusalCode
            raise AdmissionRefused(RefusalCode.AUTHORITY)
        self.events.append("authority")
        return self.authority

    def authority_for_run(self, execution_uuid):
        assert execution_uuid == EXECUTION
        return self.authority

    def transport(self, authority):
        assert authority == self.authority
        return self.store

    def prepare(self, descriptor, *, request, transaction):
        assert descriptor.wire == dump(self.descriptor)
        assert request.wire == self.descriptor["request_options_json"].encode()
        assert transaction.get_bind() is get_database().engine
        self.events.append("prepare")
        return self.queued

    def verify_install(self, admission, *, transaction):
        self.events.append("verify-install")
        # synthetic fixture registry, not a raw capture/composition claim
        return admission.wire == self.queued.wire

    def captured_nodes(self, admission, *, transaction):
        assert admission.wire == self.queued.wire
        return self.nodes

    def verify_preparation(self, current, receipt, provenance, *, transaction):
        self.events.append("verify-preparation")
        return provenance is self.trusted_preparation

    def submit(self, **changes):
        kwargs = dict(
            descriptor_wire=dump(self.descriptor), caller=Caller(name="synthetic-author"),
            workflow_name=self.descriptor["workflow_name"],
            workspace_path=self.descriptor["workspace_path"],
            inputs=json.loads(self.descriptor["metadata_inputs_json"]),
            request=FrozenJSON(self.descriptor["request_options_json"].encode()),
            execution_id=None, mode=SUPPORTED_MODE, bindings=self,
        )
        return a.submit_candidate(**{**kwargs, **changes})

    def restore(self):
        return self.store.restore(execution_uuid=EXECUTION, authority=self.authority,
                                  mode=SUPPORTED_MODE)

    def dispatch(self):
        with get_session() as session:
            self.store.bind_dispatch(self.queued, self.running, transaction=session)

    def readiness(self, receipt=None, provenance=NATIVE_PROVENANCE):
        with get_session() as session:
            return self.store.bind_root_readiness(
                self.running, receipt or self.ready,
                verified_preparation=provenance, transaction=session,
            )


def row_snapshot():
    with get_session() as session:
        row = session.get(WorkflowRun, EXECUTION)
        return None if row is None else copy.deepcopy(row.model_dump())


def reject(call, code=None):
    with pytest.raises(AdmissionRefused) as err:
        call()
    if code is not None:
        assert err.value.code == code


def test_combined_install_queue_restore_dispatch_writers_readiness_native_claim():
    b = SyntheticBindings()
    assert b.submit() == EXECUTION
    assert b.events == ["authority", "prepare", "verify-install"]
    assert row_snapshot()["attempts"] == 0
    assert row_snapshot()["status"] == "queued"
    assert _claim_row(EXECUTION, candidate_bindings=b)
    assert not _claim_row(EXECUTION, candidate_bindings=b)
    handle = RunHandle(kind=SpawnerKind.subprocess, handle="worker:synthetic", metadata={"pid": 42})
    _stamp_handle(EXECUTION, handle)
    assert b.restore().wire == b.queued.wire
    b.dispatch()
    assert row_snapshot()["attempts"] == 1
    assert row_snapshot()["status"] == "running"
    assert b.restore().wire == b.running.wire
    _stamp_handle(EXECUTION, handle)
    worker._update_run_row(EXECUTION, spawner_metadata={"observation": [1]})
    assert b.restore().wire == b.running.wire
    assert b.store.preserve(b.running, {"ordinary": None}).wire == b.running.wire
    ready = b.readiness()
    expected = b.running.value()
    expected["readiness"] = [b.ready.value()]
    assert ready.wire == dump(expected)
    assert b.readiness().wire == ready.wire  # exact replay is idempotent
    assert b.restore().wire == ready.wire
    exclusive_claim = Mock(return_value="claimed-once")
    assert b.store.claim_if_current(ready, exclusive_claim) == "claimed-once"
    exclusive_claim.assert_called_once_with()
    # Generic terminal writers preserve the complete slot; no resume becomes valid.
    worker._update_run_row(EXECUTION, status="completed")
    assert dump(row_snapshot()["spawner_metadata"][RESERVED_KEY]) == ready.wire
    reject(lambda: b.store.claim_if_current(ready, exclusive_claim))
    assert exclusive_claim.call_count == 1


def test_install_outer_rollback_collision_and_owned_bytes():
    b = SyntheticBindings()
    with pytest.raises(RuntimeError, match="rollback"):
        with get_session() as session:
            b.store.install(admission=b.queued, transaction=session)
            raise RuntimeError("rollback")
    assert row_snapshot() is None
    b.submit()
    before = row_snapshot()
    reject(b.submit)
    assert row_snapshot() == before
    changed = b.queued.value()
    changed["dispatch"]["dispatch_nonce"] = "00000000-0000-4000-8000-000000000099"
    assert b.restore().wire == b.queued.wire
    ordinary = {"child": []}
    kept = a.preserve_metadata(before["spawner_metadata"], ordinary)
    ordinary["child"].append(1)
    kept[RESERVED_KEY]["dispatch"]["phase"] = "bad"
    assert b.restore().wire == b.queued.wire
    assert kept["child"] == []


@pytest.mark.parametrize("operation", ["install", "dispatch", "readiness"])
def test_frozen_object_transaction_requires_actual_session(operation):
    b = SyntheticBindings()
    calls = {
        "install": lambda: b.store.install(admission=b.queued, transaction=object()),
        "dispatch": lambda: b.store.bind_dispatch(b.queued, b.running, transaction=object()),
        "readiness": lambda: b.store.bind_root_readiness(
            b.running, b.ready, verified_preparation=NATIVE_PROVENANCE, transaction=object()),
    }
    reject(calls[operation])
    assert row_snapshot() is None


@pytest.mark.parametrize("field,value", [
    ("execution_id", "user-run-id"), ("workflow_name", "renamed"),
    ("workspace_path", "/elsewhere"), ("inputs", {"changed": True}),
    ("request", FrozenJSON(b'{"changed":true}')), ("mode", "resume"),
    ("mode", "sealed"), ("mode", "inprocess"), ("mode", "direct"),
    ("caller", None), ("bindings", None),
])
def test_ingress_rejects_changes_before_prepare(field, value):
    b = SyntheticBindings()
    reject(lambda: b.submit(**{field: value}))
    assert "prepare" not in b.events
    assert row_snapshot() is None


@pytest.mark.parametrize("what", ["pin", "source", "receipt", "label", "current-source", "unverified", "raw-type"])
def test_authority_source_and_installation_are_not_self_certified(what):
    b = SyntheticBindings()
    if what == "pin":
        b.store.authority = replace(b.authority, expected_descriptor_sha256="f" * 64)
    elif what == "source":
        b.store.authority = replace(b.authority, expected_source_sha256="f" * 64)
    elif what == "receipt":
        b.store.authority = replace(b.authority, receipt_id="forged")
    elif what == "label":
        b.store.authority = replace(b.authority, authorized_caller_label="forged")
    elif what == "current-source":
        b.source = FrozenJSON(b'{"changed":true}')
    elif what == "unverified":
        b.store.installation = None
    record = b.queued.value() if what == "raw-type" else b.queued
    with get_session() as session:
        reject(lambda: b.store.install(admission=record, transaction=session))
    assert row_snapshot() is None


@pytest.mark.parametrize("extra", [{RESERVED_KEY: None}, {RESERVED_KEY: {}}, {RESERVED_KEY: record_input(root=True)}])
@pytest.mark.parametrize("writer", ["queue", "queue-transaction", "handle", "worker", "preserve"])
def test_every_ordinary_metadata_writer_rejects_reserved_name(extra, writer):
    b = SyntheticBindings()
    b.submit()
    before = row_snapshot()
    if writer == "queue":
        reject(lambda: queue_run(EXECUTION, "wire-fixture", None, {}, extra=extra))
    elif writer == "queue-transaction":
        with get_session() as session:
            reject(lambda: queue_run_in(session, EXECUTION, "wire-fixture", None, {}, extra=extra))
    elif writer == "handle":
        reject(lambda: _stamp_handle(EXECUTION, RunHandle(
            kind=SpawnerKind.subprocess, handle="x", metadata=extra)))
    elif writer == "worker":
        reject(lambda: worker._update_run_row(EXECUTION, spawner_metadata=extra))
    else:
        reject(lambda: b.store.preserve(b.queued, extra))
    assert row_snapshot() == before


@pytest.mark.parametrize("key,value", [
    ("workflow_name", "renamed"), ("workspace_path", "/new"), ("inputs", {"bad": 1}),
    ("execution_id", "user-id"), ("attempts", 2), ("status", "running"), ("status", "queued"),
])
def test_generic_worker_cannot_change_identity_or_generation(key, value):
    b = SyntheticBindings()
    b.submit()
    before = row_snapshot()
    if key == "execution_id":
        with get_session() as session:
            reject(lambda: a.protect_ordinary_update(session.get(WorkflowRun, EXECUTION), {key: value}))
    else:
        reject(lambda: worker._update_run_row(EXECUTION, **{key: value}))
    assert row_snapshot() == before


@pytest.mark.parametrize("key,value", [
    ("workflow_name", "renamed"), ("workspace_path", "/new"), ("inputs", {"bad": 1}),
    ("attempts", 2), ("status", "running"), ("cancel_requested", True),
    ("spawner_metadata", {"start": "resume"}), ("spawner_metadata", {"only": []}),
    ("spawner_metadata", {"rerun": []}), ("spawner_metadata", {"lane": "pi"}),
])
def test_restoration_detects_row_drift_including_reclassification(key, value):
    b = SyntheticBindings()
    b.submit()
    with get_session() as session:
        row = session.get(WorkflowRun, EXECUTION)
        setattr(row, key, {**row.spawner_metadata, **value} if key == "spawner_metadata" else value)
        session.add(row)
    reject(b.restore)
    reject(lambda: a.refuse_legacy_entry(EXECUTION))


def _captured_graph(root, *, pi):
    """A real resolved graph (the existing loader), with or without a Pi step."""
    from temper_ai.cli.check import _FileConfigs
    from temper_ai.stage.loader import GraphLoader

    (root / "agents").mkdir()
    (root / "agents" / "step.yaml").write_text(
        "agent:\n  name: step\n  type: script\n  script: echo done\n")
    (root / "agents" / "pi_talk.yaml").write_text(
        "agent:\n  name: pi_talk\n  type: pi\n  role: scout\n  provider: openai-codex\n"
        "  model: gpt-6.1-sol\n")
    (root / "workflows").mkdir()
    (root / "workflows" / "captured.yaml").write_text(
        "workflow:\n  name: captured\n  nodes:\n    - name: brief\n      type: agent\n      agent: step\n"
        + ("    - name: talk\n      type: agent\n      agent: pi_talk\n      depends_on: [brief]\n"
           if pi else ""))
    nodes, _ = GraphLoader(_FileConfigs(root)).load_workflow("captured")  # type: ignore[arg-type]
    return tuple(nodes)


@functools.cache
def _plain_capture():
    """SyntheticBindings' default capture: the real loader's graph, one script step, no Pi."""
    with tempfile.TemporaryDirectory() as root:
        return _captured_graph(Path(root), pi=False)


@pytest.mark.parametrize("pi", [True, False])
def test_install_refuses_a_pi_run_before_writing_and_writes_main_lane_rows_unmarked(tmp_path, pi):
    b = SyntheticBindings()
    b.nodes = _captured_graph(tmp_path, pi=pi)
    if pi:
        reject(b.submit, RefusalCode.MODE)
        assert row_snapshot() is None
    else:
        assert b.submit() == EXECUTION
        assert "lane" not in row_snapshot()["spawner_metadata"]


def test_install_refuses_an_empty_capture_before_writing():
    b = SyntheticBindings()
    b.nodes = ()
    reject(b.submit, RefusalCode.AUTHORITY)
    assert b.events[-1] == "verify-install"  # refused after the verifier passed, at the capture
    assert row_snapshot() is None


def test_before_the_server_starts_nothing_is_bound_and_candidate_rows_still_refuse(monkeypatch):
    """Pre-lifespan (no app state): ordinary helpers go ahead; row presence still refuses."""
    from temper_ai.api import routes

    monkeypatch.setattr(routes, "_app_state", None)
    assert routes._candidate_bindings() is None
    routes._refuse_candidate_entry(workflow="ordinary")
    b = SyntheticBindings()
    b.submit()
    with pytest.raises(HTTPException) as error:
        routes._refuse_candidate_entry(execution_id=EXECUTION)
    assert (error.value.status_code, error.value.detail) == (409, RefusalCode.MODE.value)


@pytest.mark.parametrize("step", ["dispatch", "readiness"])
def test_a_marked_row_is_refused_before_any_dispatch_or_readiness_write(step):
    b = SyntheticBindings()
    b.submit()
    if step == "readiness":
        b.dispatch()
    with get_session() as session:
        row = session.get(WorkflowRun, EXECUTION)
        row.spawner_metadata = {**row.spawner_metadata, "lane": "pi"}
        session.add(row)
    before = row_snapshot()
    reject(b.dispatch if step == "dispatch" else b.readiness, RefusalCode.MODE)
    assert row_snapshot() == before


@pytest.mark.parametrize("key,value", [
    ("running_attempt", 2), ("worker_label", "different-worker"),
    ("dispatch_nonce", "00000000-0000-4000-8000-000000000002"),
    ("previous_nonce", "00000000-0000-4000-8000-000000000099"),
])
def test_dispatch_cas_nonce_attempt_and_worker_bites(key, value):
    b = SyntheticBindings()
    b.submit()
    bad = b.running.value()
    bad["dispatch"][key] = value
    with get_session() as session:
        reject(lambda: b.store.bind_dispatch(b.queued, AdmissionRecord(dump(bad)), transaction=session))
    assert b.restore().wire == b.queued.wire


def test_stale_dispatch_and_changed_readiness_or_forged_preparation_refuse():
    b = SyntheticBindings()
    b.submit()
    b.dispatch()
    reject(b.dispatch)
    reject(lambda: b.readiness(provenance=True))
    reject(lambda: b.readiness(provenance=object()))
    assert b.restore().wire == b.running.wire
    ready = b.readiness()
    changed = b.ready.value()
    changed["root"]["inode"] += 1
    reject(lambda: b.readiness(RootReadiness(dump(changed))))
    assert b.restore().wire == ready.wire
    callback = Mock()
    reject(lambda: b.store.claim_if_current(b.queued, callback))
    callback.assert_not_called()
    b.source = FrozenJSON(b'{"changed":true}')
    reject(lambda: b.store.claim_if_current(ready, callback))
    callback.assert_not_called()


@pytest.mark.parametrize("stored", [None, {}, {"format": "future-version"}])
def test_rollback_tombstone_recognizes_presence_not_name_or_validity(stored):
    with get_session() as session:
        session.add(WorkflowRun(execution_id=EXECUTION, workflow_name="ordinary-after-rename",
                                workspace_path="/synthetic/ordinary", inputs={},
                                spawner_metadata={RESERVED_KEY: stored}))
    reject(lambda: a.refuse_legacy_entry(EXECUTION, supported_code=False))
    reject(lambda: queue_run(EXECUTION, "ordinary-after-rename", None, {}))
    _stamp_handle(EXECUTION, RunHandle(kind=SpawnerKind.subprocess, handle="x", metadata={}))
    assert row_snapshot()["spawner_metadata"][RESERVED_KEY] == stored
    reject(lambda: _claim_row(EXECUTION))


def test_unbound_watcher_refuses_and_pre_execution_busy_unclaim_preserves():
    b = SyntheticBindings()
    b.submit()
    reject(lambda: _claim_row(EXECUTION))
    assert _claim_row(EXECUTION, candidate_bindings=b)
    _unclaim(EXECUTION)
    assert b.restore().wire == b.queued.wire
    assert _claim_row(EXECUTION, candidate_bindings=b)
    b.dispatch()
    with get_session() as session:
        row = session.get(WorkflowRun, EXECUTION)
        row.spawner_kind = None
        session.add(row)
    reject(lambda: _claim_row(EXECUTION, candidate_bindings=b))


def test_candidate_claim_refuses_status_moved_on_and_dropping_the_check_bites(monkeypatch):
    """Record phase still queued, row status moved on: the locked claim must refuse."""
    import inspect
    import types

    b = SyntheticBindings()
    b.submit()
    with get_session() as session:
        row = session.get(WorkflowRun, EXECUTION)
        row.status = "cancelled"
        session.add(row)
    reject(lambda: _claim_row(EXECUTION, candidate_bindings=b), RefusalCode.GENERATION)
    assert (row_snapshot()["spawner_kind"], row_snapshot()["spawner_handle"]) == (None, None)
    # Bite: the same module with only the status/phase comparison removed lets
    # the claim take the row; nothing else in the claim stops it.
    source = inspect.getsource(a)
    guard = 'row.status != dispatch["phase"] or '
    assert source.count(guard) == 1
    mutant = types.ModuleType("admission_without_status_check")
    exec(compile(source.replace(guard, "", 1), a.__file__, "exec"), mutant.__dict__)
    monkeypatch.setattr(a.DbAdmissionTransport, "_row_record", mutant.DbAdmissionTransport._row_record)
    assert _claim_row(EXECUTION, candidate_bindings=b)


def test_legacy_run_unchanged_and_reserved_extra_refuses_on_new_row():
    queue_run("legacy", "ordinary", None, {}, extra={"ordinary": 1})
    assert _claim_row("legacy")
    a.refuse_legacy_entry("legacy")
    _stamp_handle("legacy", RunHandle(kind=SpawnerKind.subprocess, handle="x", metadata={"pid": 42}))
    worker._update_run_row("legacy", status="running", attempts=1)
    with get_session() as session:
        row = session.get(WorkflowRun, "legacy")
        assert row.spawner_metadata["ordinary"] == 1
        assert row.spawner_metadata["pid"] == 42
    reject(lambda: queue_run("new", "ordinary", None, {}, extra={RESERVED_KEY: None}))


def test_direct_spawn_stamp_keeps_fresh_identity_and_never_drops_reserved_record(monkeypatch):
    """Ordinary direct stamp is the original replace; a slot present at stamp fails closed."""
    from temper_ai.api import routes

    monkeypatch.setattr(routes, "_state", lambda: SimpleNamespace())
    stored = {"unknown": "future-version"}
    inject = {"slot": False}

    class Spawner:
        def spawn(self, execution_id):
            # The box may write before the stamp; the slot here simulates a writer
            # that cannot exist, to prove the stamp would not erase it.
            with get_session() as session:
                row = session.get(WorkflowRun, execution_id)
                meta = {**row.spawner_metadata, "box_profile": {"kept": 1}, "stale": 1}
                if inject["slot"]:
                    meta[RESERVED_KEY] = stored
                row.spawner_metadata = meta
                session.add(row)
            return RunHandle(kind=SpawnerKind.subprocess, handle="direct",
                             metadata={"execution_id": execution_id})

    monkeypatch.setattr("temper_ai.spawner.get_spawner", lambda: Spawner())
    body = routes.RunRequest(workflow="ordinary")
    config = SimpleNamespace(name="ordinary")
    routes._start_run_subprocess("direct-ordinary", body, config)
    with get_session() as session:
        row = session.get(WorkflowRun, "direct-ordinary")
        assert (row.spawner_kind, row.spawner_handle) == ("subprocess", "direct")
        assert row.spawner_metadata["box_profile"] == {"kept": 1}
        assert row.spawner_metadata["execution_id"] == "direct-ordinary"
        assert "stale" not in row.spawner_metadata  # fresh identity, not a merge
    inject["slot"] = True
    with pytest.raises(HTTPException) as refused:
        routes._start_run_subprocess("direct-reserved", body, config)
    assert refused.value.status_code == 409
    with get_session() as session:
        row = session.get(WorkflowRun, "direct-reserved")
        assert row.spawner_metadata[RESERVED_KEY] == stored
        assert row.spawner_handle is None
    # Deletion bite: without the presence check the fresh-identity replace drops it.
    monkeypatch.setattr(a, "refuse_legacy_row", lambda *_: None)
    routes._start_run_subprocess("direct-bite", body, config)
    with get_session() as session:
        assert RESERVED_KEY not in session.get(WorkflowRun, "direct-bite").spawner_metadata


def test_handle_stamp_guard_deletion_lets_spawner_metadata_replace_record(monkeypatch):
    b = SyntheticBindings()
    b.submit()
    forged = RunHandle(kind=SpawnerKind.subprocess, handle="x", metadata={RESERVED_KEY: None})
    reject(lambda: _stamp_handle(EXECUTION, forged))
    assert b.restore().wire == b.queued.wire
    monkeypatch.setattr(a, "refuse_reserved_extra", lambda *_: None)
    _stamp_handle(EXECUTION, forged)
    assert row_snapshot()["spawner_metadata"][RESERVED_KEY] is None


def test_actual_api_opt_in_routes_before_loader_and_preserves_selected_uuid(monkeypatch):
    from temper_ai.api import routes

    b = SyntheticBindings(http=True)
    graph = Mock()
    graph.load_workflow.side_effect = AssertionError("mutable loader reached")
    monkeypatch.setattr(routes, "_state", lambda: SimpleNamespace(candidate_bindings=b, graph_loader=graph))
    monkeypatch.setattr(routes, "_execution_mode", lambda: "external")
    monkeypatch.delenv(BOUNDARY_ENV, raising=False)
    body = routes.RunRequest(**json.loads(b.descriptor["request_options_json"]),
                             admission=dump(b.descriptor).decode())
    with acting_as("synthetic-author"):
        response = routes._start_run(body)
    assert response.execution_id == EXECUTION and response.status == "queued"
    graph.load_workflow.assert_not_called()
    assert b.restore().wire == b.queued.wire


# Expected refusal per case, so no case can pass for another case's reason.
API_REFUSALS = {"no-binding": RefusalCode.AUTHORITY, "anonymous": RefusalCode.AUTHORITY,
                "designated-no-record": RefusalCode.MISSING, "sealed": RefusalCode.MODE,
                "subprocess": RefusalCode.MODE, "inprocess": RefusalCode.MODE}


@pytest.mark.parametrize("kind", list(API_REFUSALS))
def test_api_unbound_or_unsupported_candidate_never_transforms(monkeypatch, kind):
    from temper_ai.api import routes

    b = SyntheticBindings(http=True)
    graph = Mock()
    graph.load_workflow.side_effect = AssertionError("mutable loader reached")
    bindings = None if kind == "no-binding" else b
    monkeypatch.setattr(routes, "_state", lambda: SimpleNamespace(candidate_bindings=bindings, graph_loader=graph))
    monkeypatch.setattr(routes, "_execution_mode", lambda: kind if kind in ("subprocess", "inprocess") else "external")
    monkeypatch.setenv(BOUNDARY_ENV, "sealed" if kind == "sealed" else "legacy")
    body = routes.RunRequest(**json.loads(b.descriptor["request_options_json"]),
                             admission=None if kind == "designated-no-record" else dump(b.descriptor).decode())
    with bound(Caller(name=None if kind == "anonymous" else "synthetic-author")):
        with pytest.raises(HTTPException) as error:
            routes._start_run(body)
    assert (error.value.status_code, error.value.detail) == (409, API_REFUSALS[kind].value)
    assert row_snapshot() is None
    graph.load_workflow.assert_not_called()


@pytest.mark.parametrize("entry", [
    "preview", "resume", "fork", "release-cleanup", "cleanup-execution", "direct-spawn", "direct-queue",
    "inprocess", "inprocess-now", "checkpoint", "checkpoint-now", "execute", "worker",
])
def test_actual_entries_refuse_reserved_row_before_legacy_loading(monkeypatch, entry):
    from temper_ai.api import routes
    from temper_ai.runner.execute import execute_workflow

    b = SyntheticBindings()
    b.submit()
    # Rename and remove classification. Slot presence must still stop legacy routes.
    with get_session() as session:
        row = session.get(WorkflowRun, EXECUTION)
        row.workflow_name = "now-ordinary"
        session.add(row)
    graph = Mock()
    graph.load_workflow.side_effect = AssertionError("mutable loader reached")
    monkeypatch.setattr(routes, "_state", lambda: SimpleNamespace(graph_loader=graph))
    monkeypatch.setattr("temper_ai.spawner.box_view.check_box", lambda: None)
    monkeypatch.setattr(worker, "_unboxed_under_sealed", lambda *_: None)
    boot = Mock(side_effect=AssertionError("bootstrap reached"))
    monkeypatch.setattr("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env", boot)
    body = routes.RunRequest(workflow="now-ordinary")
    calls = {
        "preview": lambda: routes._plan_for(EXECUTION, None, []),
        "resume": lambda: routes._resume_run(EXECUTION),
        "fork": lambda: routes._fork_run(routes.ForkRequest(
            source_execution_id=EXECUTION, workflow="now-ordinary", sequence=0)),
        "release-cleanup": lambda: routes._release_cleanups(EXECUTION),
        "cleanup-execution": lambda: routes._queue_cleanup_pass(
            {"execution_id": EXECUTION, "workflow_name": "now-ordinary"}),
        "direct-spawn": lambda: routes._start_run_subprocess(EXECUTION, body, SimpleNamespace(name="now-ordinary")),
        "direct-queue": lambda: routes._start_run_external(EXECUTION, body, SimpleNamespace(name="now-ordinary")),
        "inprocess": lambda: routes._run_workflow([], {}, None, "now-ordinary", EXECUTION),
        "inprocess-now": lambda: routes._run_workflow_now([], {}, None, "now-ordinary", EXECUTION),
        "checkpoint": lambda: routes._run_workflow_with_checkpoints([], {}, None, "now-ordinary", EXECUTION, {}),
        "checkpoint-now": lambda: routes._run_workflow_with_checkpoints_now([], {}, None, "now-ordinary", EXECUTION, {}),
        "execute": lambda: execute_workflow(workflow_name="now-ordinary", inputs={},
                                             workspace_path=None, execution_id=EXECUTION,
                                             runner_ctx=SimpleNamespace(graph_loader=graph)),
    }
    if entry == "worker":
        assert worker.cmd_run_workflow(argparse.Namespace(execution_id=EXECUTION)) == worker.BOX_REFUSED_EXIT
    else:
        with pytest.raises((HTTPException, AdmissionRefused)) as refused:
            calls[entry]()
        if isinstance(refused.value, HTTPException):
            assert refused.value.status_code == 409
    graph.load_workflow.assert_not_called()
    boot.assert_not_called()


def test_cli_validation_designation_refuses_before_bootstrap(monkeypatch):
    from temper_ai.cli import main

    b = SyntheticBindings()
    boot = Mock(side_effect=AssertionError("bootstrap reached"))
    monkeypatch.setattr("temper_ai.config.ConfigStore", boot)
    with pytest.raises(SystemExit):
        main._cmd_validate(argparse.Namespace(workflow=b.descriptor["workflow_name"]), candidate_bindings=b)
    boot.assert_not_called()


def test_remote_pg_atomic_absent_install_collision(record_property):
    """PK arbitrates absent-row race on actual remote PG; SQLite isn't this proof."""
    if get_database().engine.dialect.name != "postgresql":
        record_property("concurrency_evidence", "not collected: local SQLite")
        return
    record_property("concurrency_evidence", "actual PostgreSQL")
    b = SyntheticBindings()
    both_validated = Barrier(2, timeout=10)
    original = b.verify_install

    def verify(*args, **kwargs):
        result = original(*args, **kwargs)
        both_validated.wait()
        return result

    b.verify_install = verify

    def install():
        try:
            with get_session() as session:
                b.store.install(admission=b.queued, transaction=session)
            return "installed"
        except AdmissionRefused:
            return "collision"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(install) for _ in range(2)]
        assert sorted(f.result(timeout=15) for f in futures) == ["collision", "installed"]
    assert b.restore().wire == b.queued.wire


def test_remote_pg_generation_lock_held_through_native_claim(record_property):
    """NOWAIT competitor must fail until exclusive callback finishes: lock bite."""
    if get_database().engine.dialect.name != "postgresql":
        record_property("concurrency_evidence", "not collected: local SQLite")
        return
    record_property("concurrency_evidence", "actual PostgreSQL")
    b = SyntheticBindings()
    b.submit()
    b.dispatch()
    ready = b.readiness()
    entered, leave = Event(), Event()

    def claim_only():
        entered.set()
        assert leave.wait(10)
        return "exclusive-claim-only"

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(b.store.claim_if_current, ready, claim_only)
        assert entered.wait(10)
        try:
            with pytest.raises(OperationalError) as error:
                with get_session() as session:
                    session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == EXECUTION)
                                 .with_for_update(nowait=True)).one()
            assert getattr(error.value.orig, "pgcode", None) == "55P03"
        finally:
            leave.set()
        assert result.result(timeout=10) == "exclusive-claim-only"
    with get_session() as session:
        row = a.locked_run(session, EXECUTION)
        row.cancel_requested = True
        session.add(row)
    callback = Mock()
    reject(lambda: b.store.claim_if_current(ready, callback))
    callback.assert_not_called()
