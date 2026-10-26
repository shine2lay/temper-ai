"""Synthetic snapshot/worker seams and guard deletion controls for T2 only."""
from __future__ import annotations

import argparse
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from temper_ai.config.admission_contract import (
    CandidateInvocationBinding,
    DispatchIdentity,
    FrozenJSON,
)
from temper_ai.runner.context import RunnerContext
from temper_ai.stage.models import WorkflowConfig
from tests.test_runner.test_candidate_admission_transport import (
    EXECUTION,
    SyntheticBindings,
    a,
    dump,
    get_session,
    reject,
    row_snapshot,
    worker,
)


def snapshot_context(b, monkeypatch):
    """No providers, tools, or model calls. These are NOT T1/T3 implementations."""
    from temper_ai.runner import execute

    graph = Mock()
    graph.load_workflow.side_effect = AssertionError("mutable loader reached")
    runner = RunnerContext(config_store=object(), graph_loader=graph, llm_providers={}, memory_service=None)
    monkeypatch.setattr(execute, "TOOL_CLASSES", {})
    monkeypatch.setattr(execute, "ToolExecutor", Mock())
    monkeypatch.setattr(execute, "bind_delegate_tool", lambda *_: None)
    monkeypatch.setattr("temper_ai.integrations.github.app.asks_server_for_tokens", lambda: False)
    observed = []

    def load_snapshot(record, runner_ctx):
        assert record.wire == b.running.wire
        assert runner_ctx is runner
        observed.append("snapshot")
        return [], WorkflowConfig(name=b.descriptor["workflow_name"])

    def bind_context(record, context):
        observed.append("bind-context")
        immutable = record.value()["immutable"]
        descriptor = b.store.codec.descriptor(dump(b.descriptor), b.authority)
        closure = b.store.codec.closure(descriptor, tuple(
            b.store.codec.raw_record(dump(raw)) for raw in immutable["raw_records"]))
        context.admission = CandidateInvocationBinding(
            descriptor=descriptor, closure=closure, graph_sha256=immutable["effective_graph_sha256"],
            dispatch=DispatchIdentity(EXECUTION, record.value()["dispatch"]["dispatch_nonce"], 1),
            node_path=("synthetic-root",), position_id=None, expected_node=FrozenJSON(b'{}'),
            expected_agent=None, readiness=None,
        )
        return context

    def graph_observer(nodes, inputs, context, **kwargs):
        assert context.admission.dispatch.execution_uuid == EXECUTION
        observed.append("execute-synthetic")
        return SimpleNamespace(status="completed", cost_usd=0.0, total_tokens=0)

    b.load_snapshot = load_snapshot
    b.bind_context = bind_context
    monkeypatch.setattr(execute, "execute_graph", graph_observer)
    return runner, graph, observed


def test_snapshot_execution_uses_frozen_context_never_legacy_loader(monkeypatch):
    from temper_ai.runner.execute import execute_workflow

    b = SyntheticBindings()
    b.submit()
    b.dispatch()
    runner, graph, observed = snapshot_context(b, monkeypatch)
    result = execute_workflow(
        workflow_name=b.descriptor["workflow_name"], inputs=row_snapshot()["inputs"],
        workspace_path=b.descriptor["workspace_path"], execution_id=EXECUTION,
        runner_ctx=runner, admission_record=b.running, candidate_bindings=b,
    )
    assert result.exit_code == 0
    assert observed == ["snapshot", "bind-context", "execute-synthetic"]
    graph.load_workflow.assert_not_called()


@pytest.mark.parametrize("change", [
    "no-bindings", "no-context-binding", "dispatch", "closure", "graph", "workspace", "run-id",
    "resume", "replay", "rerun", "cleanup", "workflow", "inputs", "request-workspace", "stale",
])
def test_snapshot_entry_rejects_unbound_changed_or_continuation_before_execution(monkeypatch, change):
    from temper_ai.runner.execute import execute_workflow

    b = SyntheticBindings()
    b.submit()
    b.dispatch()
    runner, graph, observed = snapshot_context(b, monkeypatch)
    kwargs = dict(
        workflow_name=b.descriptor["workflow_name"], inputs=row_snapshot()["inputs"],
        workspace_path=b.descriptor["workspace_path"], execution_id=EXECUTION,
        runner_ctx=runner, admission_record=b.running, candidate_bindings=b,
    )
    if change == "no-bindings":
        kwargs["candidate_bindings"] = None
    elif change == "resume":
        kwargs["initial_outputs"] = {}
    elif change == "replay":
        kwargs["replay_dispatch_history"] = True
    elif change == "rerun":
        kwargs["rerun"] = ["prepare"]
    elif change == "cleanup":
        kwargs["run_only"] = ["cleanup"]
    elif change == "workflow":
        kwargs["workflow_name"] = "renamed"
    elif change == "inputs":
        kwargs["inputs"] = {"changed": True}
    elif change == "request-workspace":
        kwargs["workspace_path"] = "/elsewhere"
    elif change == "stale":
        kwargs["admission_record"] = b.queued
    else:
        original = b.bind_context

        def wrong(record, context):
            context = original(record, context)
            if change == "no-context-binding":
                context.admission = None
            elif change == "dispatch":
                context.admission = replace(context.admission, dispatch=DispatchIdentity(
                    EXECUTION, "00000000-0000-4000-8000-000000000099", 1))
            elif change == "graph":
                context.admission = replace(context.admission, graph_sha256="f" * 64)
            elif change == "closure":
                from temper_ai.config.admission_contract import RawClosure
                context.admission = replace(context.admission, closure=RawClosure(()))
            elif change == "workspace":
                context.workspace_path = "/elsewhere"
            elif change == "run-id":
                context.run_id = "user-run-id"
            return context

        b.bind_context = wrong
    reject(lambda: execute_workflow(**kwargs))
    assert "execute-synthetic" not in observed
    graph.load_workflow.assert_not_called()


def test_actual_worker_restores_then_bootstraps_snapshot_then_atomic_dispatch(monkeypatch, tmp_path):
    from temper_ai.runner.execute import ExecuteResult

    b = SyntheticBindings()
    b.submit()
    observed = []
    mutable_boot = Mock(side_effect=AssertionError("mutable bootstrap reached"))
    monkeypatch.setattr("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env", mutable_boot)
    monkeypatch.setattr("temper_ai.spawner.box_view.check_box", lambda: None)
    monkeypatch.setattr(worker, "_unboxed_under_sealed", lambda *_: None)
    monkeypatch.setattr(worker, "_install_signal_handlers", lambda *_: None)
    mcp = Mock(side_effect=AssertionError("mutable MCP bootstrap reached"))
    monkeypatch.setattr(worker, "_start_mcp_manager", mcp)
    monkeypatch.setattr(worker, "_stop_mcp_manager", lambda *_: None)
    for path in ("temper_ai.streaming.RedisChunkNotifier",
                 "temper_ai.observability.jsonl_logger.JsonlNotifier",
                 "temper_ai.observability.webhook_notifier.WebhookNotifier"):
        monkeypatch.setattr(path, Mock())
    monkeypatch.setenv("TEMPER_LOG_DIR", str(tmp_path))
    runner = SimpleNamespace()

    def bootstrap_snapshot(record):
        assert record.wire == b.queued.wire
        assert row_snapshot()["status"] == "queued"
        observed.append("restored-before-bootstrap")
        return runner

    def execute(**kw):
        record = kw["admission_record"]
        assert record.wire == b.restore().wire
        assert kw["runner_ctx"] is runner and kw["candidate_bindings"] is b
        dispatch = record.value()["dispatch"]
        assert dispatch["running_attempt"] == 1
        assert dispatch["previous_nonce"] == b.queued.value()["dispatch"]["dispatch_nonce"]
        assert dispatch["dispatch_nonce"] != dispatch["previous_nonce"]
        assert kw["rerun"] is None and kw["initial_outputs"] is None
        observed.append("atomic-dispatch-before-execute")
        return ExecuteResult(exit_code=0, status="completed")

    b.bootstrap_snapshot = bootstrap_snapshot
    monkeypatch.setattr("temper_ai.runner.execute.execute_workflow", execute)
    assert worker.cmd_run_workflow(argparse.Namespace(execution_id=EXECUTION), candidate_bindings=b) == 0
    assert observed == ["restored-before-bootstrap", "atomic-dispatch-before-execute"]
    mutable_boot.assert_not_called()
    mcp.assert_not_called()


def test_dispatch_guard_deletion_makes_literal_previous_nonce_control_fail(monkeypatch):
    """Execute one guard-deletion mutant in memory; don't edit production sources."""
    from temper_ai.config.admission_contract import AdmissionRecord

    b = SyntheticBindings()
    b.submit()
    wrong = b.running.value()
    wrong["dispatch"]["previous_nonce"] = "00000000-0000-4000-8000-000000000099"
    mutant_input = AdmissionRecord(dump(wrong))
    with get_session() as session:
        reject(lambda: b.store.bind_dispatch(b.queued, mutant_input, transaction=session))
    monkeypatch.setattr(a, "check_dispatch_transition", lambda *_: None)
    with get_session() as session:
        with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
            reject(lambda: b.store.bind_dispatch(b.queued, mutant_input, transaction=session))


def test_extra_guard_deletion_makes_equal_null_reserved_control_fail(monkeypatch):
    a.preserve_metadata({"config_admission": None}, {})
    reject(lambda: a.preserve_metadata({}, {"config_admission": None}))
    monkeypatch.setattr(a, "refuse_reserved_extra", lambda *_: None)
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        reject(lambda: a.preserve_metadata({}, {"config_admission": None}))


def test_source_guard_deletion_makes_current_source_control_fail(monkeypatch):
    b = SyntheticBindings()
    b.submit()
    b.source = FrozenJSON(b'{"changed":true}')
    reject(b.restore)
    monkeypatch.setattr(a, "require_source", lambda *_: None)
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        reject(b.restore)


_ADMISSION = "temper_ai/runner/admission.py"
_BOX = "temper_ai/cli/run_workflow.py"
_SLOT_STORE = "row.spawner_metadata = {**row.spawner_metadata, RESERVED_KEY: after.value()}"
# Each store behind one of T2's four census entries: (id, path, scope, form, literal
# store, its census fields). Every field-site gets its own missing/count/unlisted bite.
T2_STORES = [
    ("box-handle", _BOX, "cmd_run_workflow", "attribute",
     "row.spawner_handle = own_generation.handle", ("spawner_handle",)),
    ("install-insert", _ADMISSION, "DbAdmissionTransport.install", "insert", "WorkflowRun(",
     ("attempts", "spawner_handle", "spawner_kind", "spawner_metadata", "status")),
    ("dispatch-status", _ADMISSION, "DbAdmissionTransport.bind_dispatch", "attribute",
     'row.status = "running"', ("status",)),
    ("dispatch-attempts", _ADMISSION, "DbAdmissionTransport.bind_dispatch", "attribute",
     "row.attempts = 1", ("attempts",)),
    ("dispatch-slot", _ADMISSION, "DbAdmissionTransport.bind_dispatch", "attribute",
     _SLOT_STORE, ("spawner_metadata",)),
    ("readiness-slot", _ADMISSION, "DbAdmissionTransport.bind_root_readiness", "attribute",
     _SLOT_STORE, ("spawner_metadata",)),
]


def _in_scope(census, sources, path, scope, old, new):
    """Change one literal store inside one function only (stores repeat across scopes)."""
    import ast

    segment = ast.get_source_segment(sources[path], census.Module(path, sources[path]).function(scope))
    assert segment is not None and segment.count(old) == 1, f"{scope}: {old!r} is not one store"
    return sources[path].replace(segment, segment.replace(old, new, 1), 1)


@pytest.mark.parametrize("mutation", ["missing", "count", "unlisted"])
@pytest.mark.parametrize(("case", "path", "scope", "form", "store", "fields"), T2_STORES,
                         ids=[s[0] for s in T2_STORES])
def test_shared_writer_census_bites_each_t2_store(monkeypatch, case, path, scope, form, store,
                                                  fields, mutation):
    """Own controls for each T2 census entry; the scanner itself stays untouched.

    missing: the store is gone; count: a second store in the same scope; unlisted:
    the inventory no longer names it. Each must fail on exactly these sites.
    """
    from tests.test_runner import test_writer_scan as census

    sources = census._sources()
    modules = census._modules(sources)
    census._assert_t9(modules)  # A broken baseline cannot masquerade as a bite.
    if mutation == "missing":
        new = "dict(" if form == "insert" else "pass"
        modules[path] = census.Module(path, _in_scope(census, sources, path, scope, store, new))
    elif mutation == "count":
        new = "WorkflowRun() and WorkflowRun(" if form == "insert" else f"{store}; {store}"
        modules[path] = census.Module(path, _in_scope(census, sources, path, scope, store, new))
    else:
        [key] = [k for k in census.RUN_WRITERS if k[:3] == (path, scope, form) and set(fields) <= set(k[3])]
        kept = tuple(f for f in key[3] if f not in fields)
        writers = {k: v for k, v in census.RUN_WRITERS.items() if k != key}
        if kept:
            writers[(*key[:3], kept)] = census.RUN_WRITERS[key]
        monkeypatch.setattr(census, "RUN_WRITERS", writers)
    with pytest.raises(AssertionError, match="unknown or missing writer") as caught:
        census._assert_t9(modules)
    extra, missing = str(caught.value).splitlines()[0].split("; missing=", 1)
    for field in fields:
        site = repr(census.Site(path, scope, form, field))
        assert site in (missing if mutation == "missing" else extra), (case, mutation, field)
        assert site not in (extra if mutation == "missing" else missing), (case, mutation, field)


def test_shared_writer_census_catches_unreviewed_candidate_module():
    from tests.test_runner import test_writer_scan as census

    modules = census._modules(census._sources())
    census._assert_t9(modules)
    unknown = "temper_ai/runner/unreviewed_candidate_writer.py"
    assert unknown not in modules
    modules[unknown] = census.Module(unknown, "def write(row):\n    row.status = 'running'\n")
    with pytest.raises(AssertionError, match="unknown or missing writer"):
        census._assert_t9(modules)
