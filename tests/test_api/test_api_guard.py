"""The write guard (docs/api-access.md): who may change state, and the record of who did.

Covers the three modes, named keys (hashed, re-read without a restart), the MCP side
door, the in-process ways in naming themselves, a run's own key, and the decision
record.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from temper_ai.api import api_keys, caller, run_tokens
from temper_ai.api.app_state import AppState
from temper_ai.api.routes import init_app_state
from temper_ai.config import ConfigStore
from temper_ai.memory import InMemoryStore, MemoryService
from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import get_event, record
from temper_ai.stage.loader import GraphLoader

RUN = "run-guard-1"
OWNER_KEY = "tk_owner-test-key-0123456789"
CI_KEY = "tk_ci-test-key-0123456789"


@pytest.fixture
def state():
    store = ConfigStore()
    st = AppState(
        config_store=store,
        graph_loader=GraphLoader(store),
        llm_providers={"mock": MagicMock()},
        memory_service=MemoryService(InMemoryStore()),
    )
    init_app_state(st)
    return st


@pytest.fixture
def keys_file(tmp_path, monkeypatch):
    path = tmp_path / "keys.json"
    _write_keys(path, {"owner-dashboard": OWNER_KEY, "temper-ci": CI_KEY})
    monkeypatch.setenv(api_keys.KEYS_FILE_ENV_VAR, str(path))
    api_keys._reset_for_tests()
    caller._reset_for_tests()
    run_tokens._reset_for_tests()
    yield path
    api_keys._reset_for_tests()
    caller._reset_for_tests()
    run_tokens._reset_for_tests()


@pytest.fixture
def client(state, keys_file):
    from temper_ai.server import app

    return TestClient(app)


def _write_keys(path: Path, raw_by_name: dict[str, str]) -> None:
    path.write_text(json.dumps({"keys": {n: api_keys.hash_key(v) for n, v in raw_by_name.items()}}))
    # A later write within the same mtime tick must still look new to the reload check.
    stamp = time.time() + len(raw_by_name) + (path.stat().st_mtime_ns % 7)
    os.utime(path, (stamp, stamp))


def _record_waiting(node_name="decide", execution_id=RUN):
    return record(
        EventType.STAGE_STARTED,
        data={"name": node_name, "type": "agent", "gate": True, "gate_status": "waiting"},
        execution_id=execution_id,
        status="waiting",
    )


def _approve(client, *, key: str | None = None, node="decide", body=None):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return client.post(f"/api/runs/{RUN}/approve/{node}", json=body or {"response": "yes"}, headers=headers)


def _gate_status(event_id: str) -> str:
    return str((get_event(event_id) or {}).get("data", {}).get("gate_status"))


# --- modes ---------------------------------------------------------------------------------


class TestModes:
    def test_off_lets_an_unknown_caller_through(self, client, monkeypatch):
        monkeypatch.setenv("TEMPER_API_GUARD", "off")
        ev = _record_waiting()

        assert _approve(client).status_code == 200
        assert _gate_status(ev) == "approved"

    def test_off_is_the_default(self, monkeypatch):
        monkeypatch.delenv("TEMPER_API_GUARD", raising=False)
        assert caller.guard_mode() == "off"

    def test_an_unknown_value_counts_as_record(self):
        assert caller.guard_mode({"TEMPER_API_GUARD": "enforced"}) == "record"

    def test_record_lets_it_through_logs_one_line_and_counts_it(self, client, monkeypatch, caplog):
        monkeypatch.setenv("TEMPER_API_GUARD", "record")
        ev = _record_waiting()

        with caplog.at_level(logging.WARNING, logger="temper_ai.api.caller"):
            assert _approve(client).status_code == 200

        assert _gate_status(ev) == "approved"
        lines = [r.getMessage() for r in caplog.records if "api guard" in r.getMessage()]
        assert len(lines) == 1
        assert "unknown caller" in lines[0] and "approve" in lines[0] and RUN in lines[0]
        seen = client.get("/api/guard").json()
        assert any(row["caller"] is None and row["action"] == "approve" for row in seen["seen"])

    def test_enforce_refuses_an_unknown_caller_and_the_wait_stays_open(self, client, monkeypatch):
        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        ev = _record_waiting()

        reply = _approve(client)

        assert reply.status_code == 401
        assert _gate_status(ev) == "waiting"

    @pytest.mark.parametrize("call", [
        ("POST", f"/api/runs/{RUN}/cancel", {"reason": "x"}),
        ("POST", f"/api/runs/{RUN}/resume", {}),
        ("POST", f"/api/runs/{RUN}/cleanup", None),
        ("POST", "/api/runs/fork", {"source_execution_id": RUN, "sequence": 1, "workflow": "w"}),
        ("POST", "/api/runs", {"workflow": "nothing_here"}),
        ("POST", "/api/studio/configs/workflow/x", {"config": {}}),
        ("DELETE", "/api/studio/configs/workflow/x", None),
        ("POST", "/api/triggers/tick", None),
        ("POST", "/api/events/1/replay", None),
        ("POST", "/api/github/token", {"repo": "o/r"}),
    ])
    def test_enforce_refuses_every_write_route_without_a_key(self, client, monkeypatch, call):
        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        method, path, body = call

        reply = client.request(method, path, json=body)

        assert reply.status_code == 401, (path, reply.text)

    def test_reads_stay_open_in_enforce(self, client, monkeypatch):
        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        _record_waiting()

        assert client.get(f"/api/runs/{RUN}/gates").status_code == 200
        assert client.get("/api/runtime-config").json()["writes_need_key"] is True


# --- named keys ----------------------------------------------------------------------------


class TestNamedKeys:
    def test_the_right_key_passes_under_its_name(self, client, monkeypatch):
        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        ev = _record_waiting()

        assert _approve(client, key=OWNER_KEY).status_code == 200

        data = get_event(ev)["data"]
        assert data["gate_status"] == "approved"
        assert data["gate_decided_by"] == "owner-dashboard"
        assert data["gate_caller"] == "owner-dashboard"

    def test_a_wrong_key_is_refused(self, client, monkeypatch):
        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        ev = _record_waiting()

        assert _approve(client, key="tk_not-a-key").status_code == 401
        assert _gate_status(ev) == "waiting"

    def test_a_key_in_the_url_does_not_count(self, client, monkeypatch):
        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        _record_waiting()

        reply = client.post(f"/api/runs/{RUN}/approve/decide?token={OWNER_KEY}", json={"response": "y"})

        assert reply.status_code == 401

    def test_a_removed_name_stops_working_with_no_restart(self, client, monkeypatch, keys_file):
        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        _record_waiting()
        assert api_keys.identify_key(CI_KEY) == "temper-ci"

        _write_keys(keys_file, {"owner-dashboard": OWNER_KEY})

        assert api_keys.identify_key(CI_KEY) is None
        assert _approve(client, key=CI_KEY).status_code == 401

    def test_the_file_holds_hashes_only_and_a_raw_value_is_rejected(self):
        keys, problems = api_keys.parse_keys(json.dumps({"keys": {"pi": OWNER_KEY}}))
        assert keys == {} and problems

    def test_a_key_may_not_pose_as_a_name_the_server_gives(self):
        h = api_keys.hash_key("x")
        keys, problems = api_keys.parse_keys(json.dumps({"keys": {"slack:U1": h, "server": h, "box:r": h}}))
        assert keys == {} and len(problems) == 3

    def test_client_key_reads_the_key_file_first(self, tmp_path):
        key_file = tmp_path / "k"
        key_file.write_text(OWNER_KEY + "\n")
        env = {"TEMPER_API_KEY_FILE": str(key_file), "TEMPER_RUN_TOKEN": "trun_x", "TEMPER_API_TOKEN": "t"}

        assert api_keys.client_key(env) == OWNER_KEY
        assert api_keys.client_key({"TEMPER_RUN_TOKEN": "trun_x", "TEMPER_API_TOKEN": "t"}) == "trun_x"
        assert api_keys.client_key({}) is None


# --- the MCP side door -----------------------------------------------------------------------


class TestMcpSideDoor:
    def test_an_mcp_approve_with_no_caller_is_refused_like_its_route(self, state, keys_file, monkeypatch):
        from temper_ai.mcp.tools import TemperTools

        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        ev = _record_waiting()

        reply = TemperTools().approve_gate(RUN, "decide", "yes")

        assert reply["status"] == 401
        assert _gate_status(ev) == "waiting"

    def test_an_mcp_cancel_and_start_with_no_caller_are_refused(self, state, keys_file, monkeypatch):
        from temper_ai.mcp.tools import TemperTools

        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        tools = TemperTools()

        for call in (lambda: tools.cancel_run(RUN), lambda: tools.run_workflow("smoke_test")):
            with pytest.raises(caller.CallerRefused):
                call()

    def test_an_mcp_tool_sent_with_a_key_runs_as_that_key(self, state, keys_file, monkeypatch):
        """What _off_loop does: the caller of the request the call came in on, bound on its thread."""
        from temper_ai.mcp import server as mcp_server
        from temper_ai.mcp.tools import TemperTools

        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        ev = _record_waiting()
        sent_by = caller.Caller(name="pi", source="172.21.0.1", via="POST /mcp")

        reply = mcp_server._run_as(sent_by, lambda: TemperTools().approve_gate(RUN, "decide", "yes"))

        assert reply.get("status") != 401
        data = get_event(ev)["data"]
        assert data["gate_caller"] == "pi" and data["gate_decided_by"] == "MCP"

    def test_the_mcp_caller_comes_from_the_request_scope(self, monkeypatch):
        from temper_ai.api.auth import SCOPE_CALLER_KEY
        from temper_ai.mcp import server as mcp_server

        sent_by = caller.Caller(name="pi", source="10.0.0.1", via="POST /mcp")
        request = MagicMock()
        request.scope = {SCOPE_CALLER_KEY: sent_by}
        ctx = MagicMock()
        ctx.request = request
        from mcp.server.lowlevel.server import request_ctx

        token = request_ctx.set(ctx)
        try:
            found = mcp_server._caller_of_this_call("cancel_run")
        finally:
            request_ctx.reset(token)
        assert found.name == "pi" and found.source == "10.0.0.1" and found.via == "mcp cancel_run"


# --- in-process ways in name themselves ------------------------------------------------------


class TestInProcessNames:
    def test_slack_acts_as_the_person(self, monkeypatch):
        from temper_ai.integrations.slack.handlers import Handler

        seen = []
        h = Handler.__new__(Handler)
        monkeypatch.setattr(Handler, "_handle", lambda self, env: seen.append(caller.current_caller()))

        h.handle({"type": "interactive", "payload": {"user": {"id": "U123"}}})
        h.handle({"type": "slash_commands", "payload": {"user_id": "U456"}})

        assert [c.name for c in seen] == ["slack:U123", "slack:U456"]
        assert caller.current_caller() is None

    def test_telegram_acts_as_the_person(self, monkeypatch):
        from temper_ai.integrations.telegram.handlers import Handler

        seen = []
        h = Handler.__new__(Handler)
        monkeypatch.setattr(Handler, "_handle", lambda self, upd: seen.append(caller.current_caller()))

        h.handle({"update_id": 1, "callback_query": {"from": {"id": 42}}})

        assert seen[0].name == "telegram:42"

    @pytest.mark.parametrize(("source", "name"), [
        ("linear", "hook:linear"), ("notion", "hook:notion"), ("github", "hook:github"),
        ("slack", "slack"), ("telegram", "telegram"),
    ])
    def test_an_inbox_source_acts_under_its_name(self, source, name):
        from temper_ai.integrations.inbox.service import caller_name_for

        assert caller_name_for(source) == name

    def test_a_named_in_process_caller_passes_enforce(self, state, keys_file, monkeypatch):
        from temper_ai.api.routes import GateApproval, approve_gate

        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        ev = _record_waiting()

        with caller.acting_as("slack:U123", via="slack"):
            approve_gate(RUN, "decide", GateApproval(response="ok", by="Shine (Slack)"))

        data = get_event(ev)["data"]
        assert data["gate_decided_by"] == "Shine (Slack)" and data["gate_caller"] == "slack:U123"
        assert data["gate_caller_from"] == "in-process"

    def test_an_unnamed_in_process_call_is_refused_in_enforce(self, state, keys_file, monkeypatch):
        from temper_ai.api.routes import GateApproval, approve_gate

        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        ev = _record_waiting()

        with pytest.raises(caller.CallerRefused):
            approve_gate(RUN, "decide", GateApproval(response="ok"))
        assert _gate_status(ev) == "waiting"

    @pytest.mark.parametrize("answerer", [None, "owner-dashboard"])
    def test_carrying_a_parked_run_on_is_named_and_passes_enforce(self, state, keys_file,
                                                                  monkeypatch, answerer):
        """The run's own thread and start-up carry a run on after an answer with no one
        bound: that is "carry-on" (allowed); inside an answer it stays the answerer."""
        from temper_ai.api import routes

        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        seen = []

        def fake_resume(execution_id, body, *, answered_parked_only):
            seen.append((caller.current_caller().name, answered_parked_only))
            return {"execution_id": execution_id}

        monkeypatch.setattr(routes, "_resume_run", fake_resume)
        if answerer is None:
            routes.resume_answered_parked_run(RUN)
        else:
            with caller.bound(caller.Caller(name=answerer, source="10.0.0.2")):
                routes.resume_answered_parked_run(RUN)
        assert seen == [(answerer or "carry-on", True)]


# --- a run's own key ----------------------------------------------------------------------


def _running(execution_id: str, status: str = "running") -> None:
    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        row = session.get(WorkflowRun, execution_id)
        if row is None:
            row = WorkflowRun(execution_id=execution_id, workflow_name="dispatcher", status=status,
                              workspace_path="/tmp/ws")  # noqa: S108 - a stored string, never touched
        row.status = status
        session.add(row)


class TestRunKey:
    def test_it_may_start_and_fork_but_not_answer_cancel_resume_or_clean_up(self, client, monkeypatch):
        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        _running("box-run-1")
        key = run_tokens.open_for_run("box-run-1", "dispatcher")
        ev = _record_waiting()
        bearer = {"Authorization": f"Bearer {key}"}

        assert _approve(client, key=key).status_code == 403
        assert client.post(f"/api/runs/{RUN}/cancel", json={}, headers=bearer).status_code == 403
        assert client.post(f"/api/runs/{RUN}/resume", json={}, headers=bearer).status_code == 403
        assert client.post(f"/api/runs/{RUN}/cleanup", headers=bearer).status_code == 403
        assert _gate_status(ev) == "waiting"
        # Starting gets past the guard (and then finds no such workflow).
        started = client.post("/api/runs", json={"workflow": "nothing_here"}, headers=bearer)
        assert started.status_code not in (401, 403)
        forked = client.post("/api/runs/fork", headers=bearer,
                             json={"source_execution_id": RUN, "sequence": 1, "workflow": "nothing_here"})
        assert forked.status_code not in (401, 403)

    def test_it_names_its_run(self, keys_file):
        _running("box-run-2")
        key = run_tokens.open_for_run("box-run-2", "dispatcher")

        assert run_tokens.identify_run_token(key) == "box-run-2"

    def test_it_dies_with_its_run(self, keys_file):
        _running("box-run-3")
        key = run_tokens.open_for_run("box-run-3", "dispatcher")
        run_tokens.close_for_run("box-run-3")

        assert run_tokens.identify_run_token(key) is None
        assert run_tokens.held("box-run-3") is None

    def test_a_finished_run_s_key_does_not_count_even_if_its_row_stayed(self, keys_file):
        _running("box-run-4")
        key = run_tokens.open_for_run("box-run-4", "dispatcher")
        _running("box-run-4", status="completed")

        assert run_tokens.identify_run_token(key) is None

    def test_the_key_is_not_in_the_process_environment(self, keys_file):
        _running("box-run-5")
        run_tokens.open_for_run("box-run-5", "dispatcher")

        assert run_tokens.ENV_NAME not in os.environ

    def test_a_script_step_gets_it_and_an_agent_tool_never_does(self, keys_file):
        from temper_ai.agent.script_agent import _run_key_env
        from temper_ai.shared.agent_env import env_for_agent_tool

        _running("box-run-6")
        key = run_tokens.open_for_run("box-run-6", "dispatcher")
        context = MagicMock()
        context.run_id = "box-run-6"

        assert _run_key_env(context) == {run_tokens.ENV_NAME: key}
        assert run_tokens.ENV_NAME not in env_for_agent_tool(environ={run_tokens.ENV_NAME: key, "PATH": "/bin"})

    def test_a_run_without_starts_runs_gets_no_key(self, keys_file):
        from temper_ai.agent.script_agent import _run_key_env

        context = MagicMock()
        context.run_id = "box-run-7"
        assert _run_key_env(context) == {}

    def test_starts_runs_only_counts_a_literal_true(self):
        from temper_ai.stage.models import WorkflowConfig

        base = {"name": "w", "nodes": []}
        assert WorkflowConfig.from_dict({**base, "starts_runs": True}).starts_runs is True
        assert WorkflowConfig.from_dict({**base, "starts_runs": "true"}).starts_runs is False
        assert WorkflowConfig.from_dict(base).starts_runs is False


# --- the record ---------------------------------------------------------------------------


class TestRecord:
    def test_a_decision_records_caller_source_and_request_id(self, client, monkeypatch):
        monkeypatch.setenv("TEMPER_API_GUARD", "record")
        ev = _record_waiting()

        client.post(f"/api/runs/{RUN}/approve/decide", json={"response": "yes"},
                    headers={"Authorization": f"Bearer {OWNER_KEY}", "X-Request-ID": "req-77"})

        data = get_event(ev)["data"]
        assert data["gate_caller"] == "owner-dashboard"
        assert data["gate_caller_request_id"] == "req-77"
        assert data["gate_caller_from"]
        row = client.get(f"/api/runs/{RUN}/decisions").json()["decisions"][0]
        assert row["caller"] == "owner-dashboard" and row["decided_by"] == "owner-dashboard"

    def test_an_old_decision_without_the_fields_still_reads(self, client):
        record(EventType.STAGE_STARTED, execution_id=RUN, status="approved",
               data={"name": "decide", "type": "agent", "gate": True, "gate_status": "approved",
                     "gate_decided_at": "2026-09-21T10:00:00+00:00"})

        rows = client.get(f"/api/runs/{RUN}/decisions").json()["decisions"]

        assert rows and rows[0]["caller"] is None and rows[0]["decided_by"] is None

    def test_a_cancel_records_who_with_the_run(self, client, monkeypatch):
        from temper_ai.observability.recorder import get_events

        monkeypatch.setenv("TEMPER_API_GUARD", "record")
        caller.record_action(RUN, "cancel", caller.Caller(name="temper-ci", source="127.0.0.1"),
                             reason="testing")

        rows = get_events(execution_id=RUN, type_prefixes=("caller.action",), limit=10)
        assert rows[0]["data"]["action"] == "cancel" and rows[0]["data"]["caller"] == "temper-ci"


# --- the edge -----------------------------------------------------------------------------


class TestEdge:
    def test_loopback_is_the_server_only_when_runs_happen_elsewhere(self, monkeypatch):
        from temper_ai.api import auth

        monkeypatch.setattr(auth.os.path, "exists", lambda p: p == "/.dockerenv")
        monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
        assert auth.identify_caller_name(None, "127.0.0.1") == "server"
        assert auth.identify_caller_name(None, "172.21.0.1") is None
        monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")
        assert auth.identify_caller_name(None, "127.0.0.1") is None

    @pytest.mark.parametrize(("headers", "row", "says"), [
        ({"Sec-Fetch-Mode": "cors"}, "?browser", "unknown caller (browser)"),
        ({}, None, "unknown caller action"),
    ])
    def test_record_counts_an_unknown_browser_apart(self, client, monkeypatch, caplog, headers, row, says):
        """The dashboard without its key looks like this in record mode; it is a hint only."""
        monkeypatch.setenv("TEMPER_API_GUARD", "record")
        _record_waiting()

        with caplog.at_level(logging.WARNING, logger="temper_ai.api.caller"):
            client.post(f"/api/runs/{RUN}/approve/decide", json={"response": "yes"}, headers=headers)

        lines = [r.getMessage() for r in caplog.records if "api guard" in r.getMessage()]
        assert len(lines) == 1 and says in lines[0]
        seen = client.get("/api/guard").json()["seen"]
        assert [r["caller"] for r in seen if r["action"] == "approve"] == [row]

    def test_a_browser_hint_never_gets_past_enforce(self, client, monkeypatch):
        monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
        ev = _record_waiting()

        response = client.post(f"/api/runs/{RUN}/approve/decide", json={"response": "yes"},
                               headers={"Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"})

        assert response.status_code == 401
        assert _gate_status(ev) == "waiting"

    def test_the_shared_token_does_not_name_a_writer(self, monkeypatch, keys_file):
        """Every box's own process carries TEMPER_API_TOKEN, so it can't vouch for a write."""
        from temper_ai.api import auth

        monkeypatch.setenv("TEMPER_API_TOKEN", "shared-test-token-0123456789")
        assert auth.identify("shared-test-token-0123456789") == "shared"
        assert auth.identify_caller_name("shared-test-token-0123456789", "172.21.0.6") is None
        assert auth.identify_caller_name(OWNER_KEY, "172.21.0.6") == "owner-dashboard"


# --- temper check and the key helper --------------------------------------------------------


class TestCheckAndHelper:
    def test_temper_check_flags_a_starts_runs_that_is_not_true_or_false(self, tmp_path, keys_file):
        from temper_ai.cli.check import check_api_guard

        wf = tmp_path / "workflows"
        wf.mkdir()
        (wf / "a.yaml").write_text("workflow:\n  name: a\n  starts_runs: true\n  nodes: []\n")
        (wf / "b.yaml").write_text("workflow:\n  name: b\n  starts_runs: \"yes\"\n  nodes: []\n")

        holders, problems = check_api_guard(tmp_path)

        assert holders == ["a"]
        assert any("starts_runs" in p and "b.yaml" in p for p in problems)

    def test_the_helper_writes_the_key_to_its_own_file_and_only_a_hash_to_the_server(self, tmp_path):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "api_key_script", Path(__file__).resolve().parents[2] / "scripts" / "api_key.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        keys, key_dir = tmp_path / "srv" / "keys.json", tmp_path / "keys"

        assert mod.add("autopilot", keys, key_dir) == 0
        raw = (key_dir / "autopilot.key").read_text().strip()
        assert oct((key_dir / "autopilot.key").stat().st_mode & 0o777) == "0o600"
        assert raw not in keys.read_text()
        assert json.loads(keys.read_text())["keys"]["autopilot"] == api_keys.hash_key(raw)

        mod.remove("autopilot", keys, key_dir)
        assert json.loads(keys.read_text())["keys"] == {}
        assert not (key_dir / "autopilot.key").exists()
