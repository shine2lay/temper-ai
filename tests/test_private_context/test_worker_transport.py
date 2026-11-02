"""Process client/real middleware/key table with fake C1 custody and runner claim."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from sqlmodel import Session

from temper_ai.api import auth, run_tokens
from temper_ai.api.guard_models import RunPrivateKey
from temper_ai.api.private_authority_adapter import PrivateAuthorityAdapter
from temper_ai.api.private_worker_keys import close_private_key, open_private_key
from temper_ai.api.private_workers import create_worker_router
from temper_ai.private_context.authority import ProfileAuthority, RunAuthority
from temper_ai.private_context.client import PrivateWorkerClient
from temper_ai.private_context.contracts import (
    AttemptOutcome,
    PrivateLease,
    RunPrincipal,
    SendReservation,
)
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.wire import decode_registration
from temper_ai.runner.models import WorkflowRun

from . import ipd1
from .ipd1 import require
from .test_api_auth import exchange, safe_response
from .test_contracts import outcome
from .test_run_binding import request
from .transport_fakes import RecordingPorts, fake_key_sources


class RecordingWorker(RecordingPorts):
    def __init__(self):
        super().__init__()
        b = self.bound
        profile = ProfileAuthority(b.owner_principal, b.namespace, b.profile, b.profile_revision,
            b.workflow, b.workflow_revision, b.node_path, ipd1.schemas(), datetime(2099, 1, 1, tzinfo=UTC))
        self.authority = RunAuthority(profile, ipd1.RUN, 1, datetime(2099, 1, 1, tzinfo=UTC), False)
        self.adapter = PrivateAuthorityAdapter(run_reader_in=lambda session, run: self.authority,
            runner_claim_in=lambda session, run: self.authority)  # EXPLICIT FAKE runner claim.
        self.lease = None
        self.reservation = None

    def worker_bootstrap_in(self, session, execution_id, effect):
        authority = self.adapter.bootstrap_in(session, execution_id)
        require(run_tokens.held(execution_id, run_tokens.PRIVATE_CONTEXT) is None)
        effect(session, authority)
        require(run_tokens.held(execution_id, run_tokens.PRIVATE_CONTEXT) is None)
        return authority

    def worker_current_in(self, session, principal):
        return self.adapter.run_in(session, principal)

    def resolve(self, principal, execution_id, running_attempt, node_path, use):
        self.calls.append("resolve")
        self.lease = PrivateLease(lease_id=ipd1.REF, binding=self.bound,
            context=decode_registration(ipd1.registration().to_private_json()))
        return self.lease

    def worker_lease(self, principal, lease_id):
        if self.lease is None or lease_id != self.lease.lease_id:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return self.lease

    def reserve_send(self, lease, invocation_id, attempt_id, selected_slot):
        self.calls.append("reserve")
        self.reservation = SendReservation(lease_id=lease.lease_id, execution_id=ipd1.RUN,
            invocation_id=invocation_id, attempt_id=attempt_id, runner_generation=1,
            selected_slot=selected_slot, deadline_at=ipd1.EXPIRY)
        return self.reservation

    def worker_reservation(self, principal, invocation_id, attempt_id):
        r = self.reservation
        if r is None or (r.invocation_id, r.attempt_id) != (invocation_id, attempt_id):
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return r

    def finish_attempt(self, reservation, outcome_metadata):
        self.calls.append("finish")

    def publish(self, lease, invocation_id, validated):
        self.calls.append("publish")
        return self.draft_receipt()

    def release(self, lease, disposition):
        self.calls.append("release")
        lease.close()


@pytest.fixture
def worker(monkeypatch, transport_database):
    fake_key_sources(monkeypatch)
    ports = RecordingWorker()
    with transport_database[1]() as session:
        session.add(WorkflowRun(execution_id=ipd1.RUN, workflow_name=ports.bound.workflow,
                               inputs=request()["inputs"], workspace_path="", status="running"))
    try:
        yield ports
    finally:
        with run_tokens._lock:
            run_tokens._held.pop((run_tokens.PRIVATE_CONTEXT.table, ipd1.RUN), None)


def worker_app(ports):
    app = FastAPI()
    app.include_router(create_worker_router(lambda req: ports.boundary()))
    app.add_middleware(auth.CallerMiddleware)
    app.add_middleware(auth.TokenAuthMiddleware)
    return app


def test_combined_real_process_client_asgi_key_scope_and_cleanup(worker, transport_database):
    app = worker_app(worker)
    paths = []
    def send(req):
        paths.append(req.url.path)
        reply = exchange(app, path=req.url.path, raw=req.content,
                         key=req.headers["authorization"].removeprefix("Bearer "))
        return httpx.Response(reply[0], headers=reply[1], content=reply[2])
    open_private_key(ipd1.RUN, worker)
    client = PrivateWorkerClient(server_url="http://synthetic", execution_id=ipd1.RUN,
        runner_generation=1, timeout=httpx.Timeout(10), transport=httpx.MockTransport(send))
    principal = RunPrincipal(execution_id=ipd1.RUN, runner_generation=1, provenance="verified_private_worker_key")
    lease = client.resolve(principal, ipd1.RUN, 1, "draft")
    require(lease.open_private().open_private() == ipd1.registration().open_private())
    client.validate(lease)
    reservation = client.reserve_send(lease, ipd1.REF, ipd1.ATTEMPT, 0)
    client.finish_attempt(reservation, AttemptOutcome.model_validate(outcome()))
    receipt = client.publish(lease, ipd1.REF, ipd1.schemas().validate_draft(ipd1.draft().to_private_json()))
    require(receipt.execution_id == ipd1.RUN)
    client.release(lease, "completed")
    client.close()
    require(paths == ["/api/private-worker/" + op for op in
                       ["acquire", "validate", "reserve", "finish", "publish", "release"]])
    require(worker.calls == ["resolve", "reserve", "finish", "publish", "release"])
    close_private_key(ipd1.RUN)
    require(run_tokens.held(ipd1.RUN, run_tokens.PRIVATE_CONTEXT) is None)
    with Session(transport_database[0]) as session:
        require(session.get(RunPrivateKey, ipd1.RUN) is None)


@pytest.mark.parametrize("change", ["runner_generation", "namespace", "profile", "profile_revision",
    "workflow", "workflow_revision", "node_path", "revoked", "deadline_at", "credential_deadline",
    "future_deadline", "future_credential_deadline"])
def test_changed_current_scope_refuses_before_body(worker, change):
    open_private_key(ipd1.RUN, worker)
    raw = run_tokens.held(ipd1.RUN, run_tokens.PRIVATE_CONTEXT)
    if change == "future_deadline":
        worker.authority = replace(worker.authority, deadline_at=datetime(2098, 1, 1, tzinfo=UTC))
    elif change == "future_credential_deadline":
        worker.authority = replace(worker.authority, profile=replace(worker.authority.profile,
            credential_deadline=datetime(2098, 1, 1, tzinfo=UTC)))
    elif change in {"runner_generation", "revoked", "deadline_at"}:
        value = 2 if change == "runner_generation" else True if change == "revoked" else datetime(2000, 1, 1, tzinfo=UTC)
        worker.authority = replace(worker.authority, **{change: value})
    else:
        value = datetime(2000, 1, 1, tzinfo=UTC) if change == "credential_deadline" else "other"
        worker.authority = replace(worker.authority, profile=replace(worker.authority.profile, **{change: value}))
    reply = exchange(worker_app(worker), path="/api/private-worker/acquire",
                     raw=ipd1.registration().to_private_json(), key=raw)
    safe_response(reply, status=403)
    require(reply[3] == 0 and not worker.calls)


@pytest.mark.parametrize("path,method", [("/api/runs", "POST"), ("/api/github/token", "POST"),
    ("/api/private-contexts", "POST"), ("/api/private-worker/acquire-canary", "POST"),
    ("/api/private-worker/acquire/extra", "POST"), ("/api/private-worker/acquire", "GET")])
@pytest.mark.parametrize("guard", ["off", "record", "enforce"])
def test_worker_key_has_only_exact_worker_route_power(worker, monkeypatch, path, method, guard):
    monkeypatch.setenv("TEMPER_API_GUARD", guard)
    open_private_key(ipd1.RUN, worker)
    reply = exchange(worker_app(worker), path=path, method=method,
                     key=run_tokens.held(ipd1.RUN, run_tokens.PRIVATE_CONTEXT))
    safe_response(reply, status=403)
    require(reply[3] == 0 and not worker.calls)


def test_missing_table_no_fallback_no_held_key(worker, transport_database):
    RunPrivateKey.__table__.drop(transport_database[0])
    with pytest.raises(PrivateDraftFailure):
        open_private_key(ipd1.RUN, worker)
    require(run_tokens.held(ipd1.RUN, run_tokens.PRIVATE_CONTEXT) is None)
    reply = exchange(worker_app(worker), path="/api/private-worker/acquire", key="tpriv_synthetic")
    safe_response(reply, status=503)
    require(reply[3] == 0)


def test_failing_bootstrap_after_key_staging_rolls_back(worker, transport_database, monkeypatch):
    normal = worker.worker_bootstrap_in
    def fail(session, execution_id, effect):
        normal(session, execution_id, effect)
        raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
    monkeypatch.setattr(worker, "worker_bootstrap_in", fail)
    with pytest.raises(PrivateDraftFailure):
        open_private_key(ipd1.RUN, worker)
    require(run_tokens.held(ipd1.RUN, run_tokens.PRIVATE_CONTEXT) is None)
    with Session(transport_database[0]) as session:
        require(session.get(RunPrivateKey, ipd1.RUN) is None)


def test_missing_runner_claim_cannot_mint(worker, transport_database):
    worker.adapter = replace(worker.adapter, runner_claim_in=None)
    with pytest.raises(PrivateDraftFailure):
        open_private_key(ipd1.RUN, worker)
    with Session(transport_database[0]) as session:
        require(session.get(RunPrivateKey, ipd1.RUN) is None)


def test_generic_key_service_never_mints_private_key(worker):
    require(run_tokens._model(run_tokens.PRIVATE_CONTEXT) is RunPrivateKey)
    with pytest.raises(PrivateDraftFailure):
        run_tokens.open_for_run(ipd1.RUN, kind=run_tokens.PRIVATE_CONTEXT)
    with pytest.raises(ValueError):
        run_tokens._model(replace(run_tokens.STARTS_RUNS, table="not-real"))
    require(run_tokens.held(ipd1.RUN, run_tokens.PRIVATE_CONTEXT) is None)
