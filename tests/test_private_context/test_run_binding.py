"""Normal queue with recording composition; no claim of concrete C1 atomicity."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime

import pytest
from sqlmodel import Session, select

from temper_ai.api.caller import Caller, bound
from temper_ai.api.guard_models import RunPrivateKey
from temper_ai.api.private_identity import (
    bound_verified_named_key,
    require_private_caller_provenance,
)
from temper_ai.private_context.composition import BindingAdmission
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.runtime import configure_private_boundary
from temper_ai.private_context.wire import VERSION
from temper_ai.runner.models import WorkflowRun
from temper_ai.runner.private_context_binding import (
    private_lifecycle,
    submit_private_start,
)
from temper_ai.runner.queue import queue_run_in

from . import ipd1
from .ipd1 import require
from .transport_fakes import SYNTHETIC_KEY, RecordingPorts, fake_key_sources


def request():
    return {"workflow": "synthetic-workflow", "inputs": {"private_context": {
        "version": VERSION, "context_ref": ipd1.REF, "context_version": 1}}}


@contextmanager
def authenticated():
    caller = Caller(name="owner-1", source="synthetic", request_id="synthetic", via="synthetic")
    with bound(caller), bound_verified_named_key(caller, SYNTHETIC_KEY):
        yield


class RecordingAdmission(RecordingPorts):
    created = False
    fail_after_queue = False

    def bind_and_queue_in(self, session, caller, context_ref, context_version,
                          execution_id, profile_revision, queue):
        require_private_caller_provenance(caller)
        if self.created:
            return BindingAdmission(self.bound, False)
        queue(session, execution_id)
        if self.fail_after_queue:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        require(session.get(WorkflowRun, execution_id) is not None)
        self.bound = self.bound.model_copy(update={"execution_id": execution_id})
        self.created = True
        return BindingAdmission(self.bound, True)

    def binding_for_run(self, execution_id, authorize):
        authorize(self.bound.owner_principal, self.bound.namespace, self.bound.profile)
        if execution_id != self.bound.execution_id:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return self.bound

    def lifecycle_in(self, session, caller, execution_id, action, effect):
        require_private_caller_provenance(caller)
        if action == "fork":
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        next_binding = self.bound.model_copy(update={"runner_generation": self.bound.runner_generation + 1} if action == "resume"
                                            else {"revoked": True})
        effect(session, next_binding)
        self.bound = next_binding
        return next_binding


@pytest.fixture
def admission(monkeypatch, transport_database):
    fake_key_sources(monkeypatch)
    ports = RecordingAdmission()
    configure_private_boundary(ports.boundary())
    try:
        yield ports
    finally:
        configure_private_boundary(None)


def test_combined_normal_start_retry_resume_cancel_and_ordinary_parity(admission, transport_database):
    engine, sessions = transport_database
    with authenticated():
        run = submit_private_start(request(), mode="external", execution_id=ipd1.RUN)
        retry = submit_private_start(request(), mode="external", execution_id=ipd1.ATTEMPT)
        require(run == retry == ipd1.RUN and admission.calls == ["dispatch"])
        with sessions() as session:
            row = session.get(WorkflowRun, run)
            require(row.status == "queued" and row.inputs == request()["inputs"])
            row.status = "failed"
            session.add(row)
        current = private_lifecycle(run, "resume", {}, mode="external")
        require(current.runner_generation == 2 and admission.calls == ["dispatch", "dispatch"])
        private_lifecycle(run, "cancel", {}, mode="external")
        with pytest.raises(PrivateDraftFailure):
            private_lifecycle(run, "fork", {}, mode="external")
    with sessions() as session:
        require(session.get(WorkflowRun, run).cancel_requested)
        queue_run_in(session, ipd1.DRAFT, "ordinary", None, {"safe": 1})
    with Session(engine) as session:
        require(session.get(WorkflowRun, ipd1.DRAFT).inputs == {"safe": 1})


@pytest.mark.parametrize("mode", ["external", "subprocess", "inprocess"])
def test_queue_effect_rolls_back_if_composition_fails(admission, transport_database, mode):
    admission.fail_after_queue = True
    with authenticated(), pytest.raises(PrivateDraftFailure):
        submit_private_start(request(), mode=mode, execution_id=ipd1.RUN)
    with Session(transport_database[0]) as session:
        require(session.get(WorkflowRun, ipd1.RUN) is None and not admission.calls)


@pytest.mark.parametrize("change", ["workflow", "workspace_path", "rerun", "inputs", "version"])
def test_closed_private_start_before_generic_writes(admission, transport_database, change):
    value = request()
    if change == "workflow":
        value["workflow"] += "-canary"
    elif change == "inputs":
        value["inputs"]["payload"] = "not-permitted"
    elif change == "version":
        value["inputs"]["private_context"]["version"] += "-canary"
    else:
        value[change] = None
    with authenticated(), pytest.raises(PrivateDraftFailure):
        submit_private_start(value, mode="external")
    with Session(transport_database[0]) as session:
        require(not list(session.exec(select(WorkflowRun))) and not admission.calls)


def test_direct_queue_cannot_bypass_binding_and_rolls_back_earlier_write(admission, transport_database):
    _, sessions = transport_database
    with pytest.raises(PrivateDraftFailure), sessions() as session:
        queue_run_in(session, ipd1.DRAFT, "ordinary", None, {})
        queue_run_in(session, ipd1.RUN, "synthetic-workflow", None, request()["inputs"])
    with sessions() as session:
        require(not list(session.exec(select(WorkflowRun))))


def test_existing_private_row_cannot_erase_marker(admission, transport_database):
    _, sessions = transport_database
    with authenticated():
        submit_private_start(request(), mode="external", execution_id=ipd1.RUN)
    with sessions() as session:
        row = session.get(WorkflowRun, ipd1.RUN)
        row.status = "failed"
        session.add(row)
    with pytest.raises(PrivateDraftFailure), sessions() as session:
        queue_run_in(session, ipd1.RUN, "ordinary-renamed", None, {})
    with sessions() as session:
        require(session.get(WorkflowRun, ipd1.RUN).inputs == request()["inputs"])


@pytest.mark.parametrize("action", ["resume", "fork", "cancel"])
def test_lifecycle_overrides_have_no_effect(admission, transport_database, action):
    with authenticated():
        submit_private_start(request(), mode="external", execution_id=ipd1.RUN)
        with pytest.raises(PrivateDraftFailure):
            private_lifecycle(ipd1.RUN, action, {"workflow": "other"}, mode="external")
    require(admission.calls == ["dispatch"] and not admission.bound.revoked)


def staged_key(binding):
    return RunPrivateKey(execution_id=binding.execution_id, token_hash="synthetic-key-hash",
        owner_principal=binding.owner_principal, namespace=binding.namespace, profile=binding.profile,
        profile_revision=binding.profile_revision, workflow_name=binding.workflow,
        workflow_revision=binding.workflow_revision, node_path=binding.node_path, use=binding.use,
        runner_generation=binding.runner_generation, expires_at=datetime.fromisoformat(binding.deadline_at))


@pytest.mark.parametrize("field", ["execution_id", "context_ref", "context_version", "owner_principal",
    "namespace", "profile", "profile_revision", "workflow", "workflow_revision", "node_path", "use",
    "context_schema", "result_schema", "schema_revision", "revoked", "expires_at", "deadline_at"])
def test_changed_admission_binding_rolls_back_staged_queue(admission, transport_database, monkeypatch, field):
    original = admission.bind_and_queue_in
    def changed(*args):
        admitted = original(*args)
        value = (True if field == "revoked" else 2 if field == "context_version" else
                 "2000-01-01T00:00:00Z" if field.endswith("_at") else "changed-canary")
        return BindingAdmission(admitted.binding.model_copy(update={field: value}), admitted.created)
    monkeypatch.setattr(admission, "bind_and_queue_in", changed)
    with authenticated(), pytest.raises(PrivateDraftFailure):
        submit_private_start(request(), mode="external", execution_id=ipd1.RUN)
    with Session(transport_database[0]) as session:
        require(session.get(WorkflowRun, ipd1.RUN) is None and not admission.calls)


@pytest.mark.parametrize("action", ["resume", "cancel"])
@pytest.mark.parametrize("change", ["generation", "revocation", "scope", "deadline", "send_state"])
def test_lifecycle_exact_transition_before_normal_or_key_effect(admission, transport_database, monkeypatch,
                                                               action, change):
    _, sessions = transport_database
    with authenticated():
        submit_private_start(request(), mode="external", execution_id=ipd1.RUN)
    previous = admission.bound
    with sessions() as session:
        row = session.get(WorkflowRun, ipd1.RUN)
        row.status = "failed"
        session.add(row)
        session.add(staged_key(previous))
    def corrupted(session, caller, execution_id, action, effect):
        updates = {"runner_generation": previous.runner_generation + (1 if action == "resume" else 0),
                   "revoked": action == "cancel"}
        if change == "generation":
            updates["runner_generation"] += 1
        elif change == "revocation":
            updates["revoked"] = action != "cancel"
        elif change == "scope":
            updates["namespace"] = previous.namespace + "-canary"
        elif change == "deadline":
            updates["deadline_at"] = "2098-01-01T00:00:00Z"
        else:
            updates["attempt_state"] = "ambiguous"
        result = previous.model_copy(update=updates)
        effect(session, result)
        return result
    monkeypatch.setattr(admission, "lifecycle_in", corrupted)
    with authenticated(), pytest.raises(PrivateDraftFailure):
        private_lifecycle(ipd1.RUN, action, {}, mode="external")
    with sessions() as session:
        row = session.get(WorkflowRun, ipd1.RUN)
        require(row.status == "failed" and not row.cancel_requested)
        require(session.get(RunPrivateKey, ipd1.RUN).token_hash == "synthetic-key-hash")
    require(admission.calls == ["dispatch"])


@pytest.mark.parametrize("action", ["resume", "cancel"])
def test_lifecycle_post_effect_failure_rolls_back_normal_run_and_key(admission, transport_database,
                                                                   monkeypatch, action):
    _, sessions = transport_database
    with authenticated():
        submit_private_start(request(), mode="external", execution_id=ipd1.RUN)
    with sessions() as session:
        row = session.get(WorkflowRun, ipd1.RUN)
        row.status = "failed"
        session.add(row)
        session.add(staged_key(admission.bound))
    original = admission.lifecycle_in
    def fail(*args):
        original(*args)
        raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
    monkeypatch.setattr(admission, "lifecycle_in", fail)
    with authenticated(), pytest.raises(PrivateDraftFailure):
        private_lifecycle(ipd1.RUN, action, {}, mode="external")
    with sessions() as session:
        row = session.get(WorkflowRun, ipd1.RUN)
        require(row.status == "failed" and not row.cancel_requested)
        require(session.get(RunPrivateKey, ipd1.RUN) is not None)
    # RecordingPorts is volatile and deliberately makes no rollback/custody claim.
    require(admission.calls == ["dispatch"])


def test_absent_dispatcher_refuses_before_queue(admission, transport_database):
    configure_private_boundary(replace(admission.boundary(), prepare_dispatch=lambda mode: None))
    with authenticated(), pytest.raises(PrivateDraftFailure):
        submit_private_start(request(), mode="external")
    with Session(transport_database[0]) as session:
        require(not list(session.exec(select(WorkflowRun))))


@pytest.mark.parametrize("action", ["start", "resume", "cancel"])
def test_outer_commit_failure_keeps_queue_and_key_unchanged(admission, transport_database, monkeypatch, action):
    from temper_ai import database

    engine, sessions = transport_database
    if action != "start":
        with authenticated():
            submit_private_start(request(), mode="external", execution_id=ipd1.RUN)
        with sessions() as session:
            row = session.get(WorkflowRun, ipd1.RUN)
            row.status = "failed"
            session.add(row)
            session.add(staged_key(admission.bound))
    previous_calls = list(admission.calls)

    @contextmanager
    def failed_commit():
        with Session(engine) as session:
            yield session
            session.flush()
            raise RuntimeError("synthetic commit refusal")

    monkeypatch.setattr(database, "get_session", failed_commit)
    with authenticated(), pytest.raises(RuntimeError, match="synthetic commit refusal"):
        if action == "start":
            submit_private_start(request(), mode="external", execution_id=ipd1.RUN)
        else:
            private_lifecycle(ipd1.RUN, action, {}, mode="external")
    with sessions() as session:
        row = session.get(WorkflowRun, ipd1.RUN)
        if action == "start":
            require(row is None)
        else:
            require(row.status == "failed" and not row.cancel_requested)
            require(session.get(RunPrivateKey, ipd1.RUN).token_hash == "synthetic-key-hash")
    require(admission.calls == previous_calls)


@pytest.mark.parametrize("field", ["expires_at", "deadline_at"])
@pytest.mark.parametrize("relation", ["past", "equal", "future"])
@pytest.mark.parametrize("retry", [False, True])
def test_actual_wire_timestamp_boundaries_and_retry(admission, transport_database, monkeypatch,
                                                   field, relation, retry):
    from datetime import UTC

    from temper_ai.private_context.contracts import PrivateBinding
    from temper_ai.runner import private_context_binding as boundary_module

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2040, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(boundary_module, "datetime", FixedClock)
    if retry:
        with authenticated():
            submit_private_start(request(), mode="external", execution_id=ipd1.RUN)
    chosen = {"past": "2039-12-31T23:59:59Z", "equal": "2040-01-01T00:00:00Z",
              "future": "2040-01-01T00:00:01Z"}[relation]
    # The actual A model validates string-valued UTC fields. No datetime fake.
    admission.bound = PrivateBinding.model_validate({
        **admission.bound.model_dump(exclude_unset=True), field: chosen})
    with authenticated():
        if relation == "future":
            run = submit_private_start(request(), mode="external", execution_id=ipd1.RUN)
            same = submit_private_start(request(), mode="external", execution_id=ipd1.ATTEMPT)
            require(run == same == ipd1.RUN)
        else:
            with pytest.raises(PrivateDraftFailure):
                submit_private_start(request(), mode="external", execution_id=ipd1.RUN)
    with Session(transport_database[0]) as session:
        require((session.get(WorkflowRun, ipd1.RUN) is not None) == (retry or relation == "future"))
    require(admission.calls == (["dispatch"] if retry or relation == "future" else []))


@pytest.mark.parametrize("invalid", ["2040-01-01T00:00:00", "2040-01-01T00:00:00+01:00",
                                     "2040-01-01 00:00:00Z", "not-a-time"])
def test_binding_time_reuses_strict_wire_validation(invalid):
    from temper_ai.runner.private_context_binding import _binding_time

    with pytest.raises(PrivateDraftFailure):
        _binding_time(invalid)
