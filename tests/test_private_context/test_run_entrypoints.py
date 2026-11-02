"""Actual route/MCP entrypoints; recording ports prove orchestration, not C1 custody."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlmodel import Session, select

from temper_ai.api import auth, routes
from temper_ai.api.caller import Caller, bound
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.private_json import encode_private
from temper_ai.runner.models import WorkflowRun

from . import ipd1
from .ipd1 import require
from .test_api_auth import exchange, safe_response
from .test_run_binding import request


@pytest.mark.parametrize("mode", ["external", "subprocess", "inprocess"])
def test_real_http_start_and_resume_share_preparation(admission, transport_database, monkeypatch, mode):
    actions = []
    monkeypatch.setenv("TEMPER_API_GUARD", "off")
    monkeypatch.setattr(routes, "_execution_mode", lambda: mode)
    monkeypatch.setattr(routes, "_state", lambda: SimpleNamespace(running={}))
    monkeypatch.setattr(routes, "_note_event_run", lambda *args: None)
    monkeypatch.setattr(routes, "record_action", lambda *args, **kw: actions.append(args[1]))
    app = FastAPI()
    app.include_router(routes.router)
    app.add_middleware(auth.CallerMiddleware)
    app.add_middleware(auth.TokenAuthMiddleware)
    first = exchange(app, path="/api/runs", raw=encode_private(request()))
    safe_response(first)
    run = admission.bound.execution_id
    second = exchange(app, path="/api/runs", raw=encode_private(request()))
    safe_response(second)
    require(first[2] == second[2] and admission.calls == ["dispatch"])
    with transport_database[1]() as session:
        row = session.get(WorkflowRun, run)
        row.status = "failed"
        session.add(row)
    safe_response(exchange(app, path=f"/api/runs/{run}/resume"))
    safe_response(exchange(app, path=f"/api/runs/{run}/cancel"))
    require(actions == ["start", "start", "resume", "cancel"])
    require(admission.calls == ["dispatch", "dispatch"])
    before = tuple(actions)
    forbidden = request() | {"notify": {"private": "not-allowed"}}
    safe_response(exchange(app, path="/api/runs", raw=encode_private(forbidden)), status=400)
    safe_response(exchange(app, path="/api/runs/fork", raw=encode_private(
        {"source_execution_id": run, "workflow": "ordinary", "sequence": 0})), status=403)
    require(tuple(actions) == before)


@pytest.mark.parametrize("entry", ["external", "subprocess", "inprocess", "inprocess-now", "fork"])
def test_legacy_execution_entrypoints_refuse_before_effects(admission, transport_database, monkeypatch, entry):
    monkeypatch.setattr(routes, "_state", lambda: SimpleNamespace(candidate_bindings={}))
    body = routes.RunRequest(**request())
    with pytest.raises(PrivateDraftFailure):
        if entry == "external":
            routes._start_run_external(ipd1.RUN, body, SimpleNamespace(name=body.workflow))
        elif entry == "subprocess":
            routes._start_run_subprocess(ipd1.RUN, body, SimpleNamespace(name=body.workflow))
        elif entry == "fork":
            routes._fork_run(routes.ForkRequest(source_execution_id=ipd1.RUN, sequence=0,
                                               workflow=body.workflow, inputs=body.inputs))
        else:
            target = routes._run_workflow if entry == "inprocess" else routes._run_workflow_now
            target([], body.inputs, None, body.workflow, ipd1.RUN)
    with Session(transport_database[0]) as session:
        require(not list(session.exec(select(WorkflowRun))) and not admission.calls)


def test_mcp_and_constructed_internal_caller_cannot_bypass(admission, transport_database, monkeypatch):
    from temper_ai.mcp.tools import TemperTools

    monkeypatch.setenv("TEMPER_API_GUARD", "off")
    monkeypatch.setattr(routes, "_execution_mode", lambda: "external")
    caller = Caller(name="owner-1", source="127.0.0.1", request_id="synthetic", via="mcp")
    with bound(caller), pytest.raises(PrivateDraftFailure):
        routes._start_run(routes.RunRequest(**request()))
    with bound(caller), pytest.raises(PrivateDraftFailure):
        TemperTools().run_workflow(**request())
    with Session(transport_database[0]) as session:
        require(not list(session.exec(select(WorkflowRun))) and not admission.calls)
