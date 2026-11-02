"""Actual C1 facade with explicit synthetic authenticated adapters/callbacks.

These are not real HTTP/key/runner integration proofs; E owns those joins.
"""
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlmodel import Session

from temper_ai.private_context.composition_service import PrivateContextComposition
from temper_ai.private_context.contracts import CallerPrincipal, RunPrincipal
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.models import PrivateContextRow, PrivateInvocationRow

from . import ipd1
from .service_fixtures import Code, SyntheticAuthorityRow, outcome, refused
from .service_fixtures import harness as harness
from .test_replay import ordered


def enqueue(session, execution_id):
    ipd1.require(execution_id == ipd1.RUN)
    row = session.get(SyntheticAuthorityRow, 1)
    row.queued += 1
    session.add(row)
    session.flush()


def transition(session, binding, *, cancel=False):
    row = session.get(SyntheticAuthorityRow, 1)
    if cancel:
        row.revoked = True
    else:
        row.queued = 1
    row.key_generation = 0
    session.add(row)
    session.flush()


def composition(h):
    h.authority.canonical_lifecycle = True
    return PrivateContextComposition(h.service)


def test_combined_composition_queue_retry_bootstrap_handles_and_lifecycle(harness):
    h = harness
    c = composition(h)
    h.authority.require_queued = True
    receipt = h.service.register(h.caller, h.context())
    with Session(h.engine) as session, session.begin():
        admitted = c.bind_and_queue_in(session, h.caller, receipt.context_ref, 1, ipd1.RUN, "profile-v1", enqueue)
        ipd1.require(admitted.created)
    with Session(h.engine) as session, session.begin():
        retry = c.bind_and_queue_in(session, h.caller, receipt.context_ref, 1, str(uuid4()), "profile-v1", enqueue)
        ipd1.require(not retry.created and retry.binding == admitted.binding)
    ipd1.require(h.rows(SyntheticAuthorityRow)[0].queued == 1)
    def authorize(owner, namespace, profile):
        ipd1.require((owner, namespace, profile) == ("owner-1", "scope-1", "synthetic-reply-v1"))
        return h.caller
    ipd1.require(c.caller_for_context(receipt.context_ref, authorize) is h.caller)
    ipd1.require(c.binding_for_run(ipd1.RUN, authorize) == admitted.binding)
    def issue(session, authority):
        row = session.get(SyntheticAuthorityRow, 1)
        row.key_generation = authority.runner_generation
        session.add(row)
        session.flush()
    with Session(h.engine) as session, session.begin():
        c.worker_bootstrap_in(session, ipd1.RUN, issue)
    lease = h.lease()
    ipd1.require(c.worker_lease(h.principal, lease.lease_id) is lease)
    reservation = h.service.reserve_send(lease, str(uuid4()), str(uuid4()), 0)
    ipd1.require(c.worker_reservation(h.principal, reservation.invocation_id, reservation.attempt_id) is reservation)
    # Resume preserves possible-send evidence and invalidates old access handles.
    with Session(h.engine) as session, session.begin():
        resumed = c.lifecycle_in(session, h.caller, ipd1.RUN, "resume", transition)
    ipd1.require(resumed.runner_generation == 2 and resumed.attempt_state == "reserved")
    ipd1.require(h.rows(SyntheticAuthorityRow)[0].key_generation == 0)
    refused(lambda: c.worker_lease(h.principal, lease.lease_id), Code.SCOPE_DENIED)
    h.authority.principal = RunPrincipal(execution_id=ipd1.RUN, runner_generation=2, provenance="verified_private_worker_key")
    refused(lambda: h.service.resolve(h.authority.principal, ipd1.RUN, 2, "writer"), Code.SEND_AMBIGUOUS)
    with Session(h.engine) as session, session.begin():
        c.lifecycle_in(session, h.caller, ipd1.RUN, "cancel", lambda s, b: transition(s, b, cancel=True))
    ipd1.require(h.status(receipt).state == "cancelled")
    ipd1.require(len(h.rows(PrivateInvocationRow)) == 1)


@pytest.mark.parametrize("revoked", [False, True])
def test_retry_checks_actual_run_revocation_before_admission(harness, revoked):
    h = harness
    c = composition(h)
    receipt, binding = h.bound()
    h.change(revoked=revoked)
    ipd1.require(not h.rows(PrivateContextRow)[0].revoked)
    calls = []
    def retry():
        with Session(h.engine) as session, session.begin():
            return c.bind_and_queue_in(session, h.caller, receipt.context_ref, 1,
                                       str(uuid4()), "profile-v1",
                                       lambda session, execution: calls.append(execution))
    if revoked:
        refused(retry, Code.CANCELLED)
    else:
        admitted = retry()
        ipd1.require(not admitted.created and admitted.binding == binding)
    ipd1.require(not calls and h.rows(SyntheticAuthorityRow)[0].queued == 0)
    ipd1.require(len(h.rows(PrivateContextRow)) == 1)


def test_concurrent_new_retry_queues_exactly_once(harness, monkeypatch):
    h = harness
    c = composition(h)
    receipt = h.service.register(h.caller, h.context())
    h.authority.require_queued = True
    def call(execution):
        with Session(h.engine) as session, session.begin():
            return c.bind_and_queue_in(session, h.caller, receipt.context_ref, 1, execution, "profile-v1", enqueue)
    first, second = ordered(h, lambda: call(ipd1.RUN), lambda: call(str(uuid4())), monkeypatch)
    ipd1.require(first[0] == second[0] == "ok")
    ipd1.require(first[1].created and not second[1].created)
    ipd1.require(first[1].binding.execution_id == second[1].binding.execution_id == ipd1.RUN)
    ipd1.require(h.rows(SyntheticAuthorityRow)[0].queued == 1)


@pytest.mark.parametrize("fault", ["callback", "final-scope", "missing-staged-run", "wrong-version"])
def test_queue_refusal_rolls_back_all_caller_owned_writes(harness, fault):
    h = harness
    c = composition(h)
    receipt = h.service.register(h.caller, h.context())
    h.authority.require_queued = True
    original_profile = h.authority.profile
    def callback(session, execution):
        if fault != "missing-staged-run":
            enqueue(session, execution)
        if fault == "callback":
            raise RuntimeError("fixed injected callback fault")
        if fault == "final-scope":
            h.authority.profile = replace(original_profile, node_path="other.writer")
    code = None
    try:
        with Session(h.engine) as session, session.begin():
            h.store.fence_in(session)
            previous = session.get(SyntheticAuthorityRow, 1)
            previous.key_generation = 99
            session.add(previous)
            c.bind_and_queue_in(session, h.caller, receipt.context_ref, 2 if fault == "wrong-version" else 1, ipd1.RUN, "profile-v1", callback)
    except PrivateDraftFailure as failure:
        code = failure.code
        ipd1.require(failure.__context__ is None)
    finally:
        h.authority.profile = original_profile
    ipd1.require(code == (Code.SCOPE_DENIED if fault in {"final-scope", "wrong-version"} else Code.CONTEXT_UNAVAILABLE))
    ipd1.require(h.rows(SyntheticAuthorityRow)[0].queued == 0)
    ipd1.require(h.rows(SyntheticAuthorityRow)[0].key_generation == 0)
    ipd1.require(h.rows(PrivateContextRow)[0].execution_id is None)
    h.service.record_binding_refusal(h.caller, code)


@pytest.mark.parametrize("fault", ["missing-claim", "wrong-run", "callback", "changed-generation"])
def test_bootstrap_failure_never_commits_key(harness, fault):
    h = harness
    h.bound()
    c = composition(h)
    if fault == "missing-claim":
        h.authority.claim_enabled = False
    def issue(session, authority):
        row = session.get(SyntheticAuthorityRow, 1)
        row.key_generation = 1
        if fault == "changed-generation":
            binding = h.store.execution_in(session, ipd1.RUN)
            binding.runner_generation += 1
            session.add(binding)
        session.add(row)
        session.flush()
        if fault == "callback":
            raise RuntimeError("fixed callback fault")
    code = None
    try:
        with Session(h.engine) as session, session.begin():
            c.worker_bootstrap_in(session, str(uuid4()) if fault == "wrong-run" else ipd1.RUN, issue)
    except PrivateDraftFailure as failure:
        code = failure.code
    ipd1.require(code == (Code.SCOPE_DENIED if fault in {"wrong-run", "changed-generation"} else Code.CONTEXT_UNAVAILABLE))
    ipd1.require(h.rows(SyntheticAuthorityRow)[0].key_generation == 0)


def test_scope_lookup_never_accepts_constructed_principal(harness):
    h = harness
    receipt, _ = h.bound()
    c = composition(h)
    forged = CallerPrincipal(**h.caller.model_dump())
    refused(lambda: c.caller_for_context(receipt.context_ref, lambda *args: forged), Code.UNAUTHENTICATED)
    refused(lambda: c.binding_for_run(ipd1.RUN, lambda *args: forged), Code.UNAUTHENTICATED)


def test_fork_and_missing_post_effect_authority_refuse_without_implicit_success(harness, monkeypatch):
    h = harness
    h.bound()
    c = composition(h)
    calls = []
    original = h.authority.binding_in
    missing = False
    def binding_in(*args):
        if missing:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        return original(*args)
    monkeypatch.setattr(h.authority, "binding_in", binding_in)
    def effect(session, binding):
        nonlocal missing
        calls.append(True)
        missing = True
    for action in ("fork", "resume", "cancel"):
        missing = False
        with Session(h.engine) as session:
            refused(lambda: c.lifecycle_in(session, h.caller, ipd1.RUN, action, effect), Code.SCOPE_DENIED if action == "fork" else Code.CONTEXT_UNAVAILABLE)
            session.rollback()
    ipd1.require(len(calls) == 2)
    ipd1.require(h.rows(PrivateContextRow)[0].runner_generation == 1)


def test_new_authenticated_request_rebinds_only_existing_exact_custody(harness):
    h = harness
    h.bound()
    lease = h.lease()
    c = composition(h)
    next_request = RunPrincipal(**h.principal.model_dump())
    refused(lambda: c.worker_lease(next_request, lease.lease_id), Code.UNAUTHENTICATED)
    h.authority.principal = next_request  # Explicitly issued by this fake adapter.
    ipd1.require(c.worker_lease(next_request, lease.lease_id) is lease)
    reservation = h.service.reserve_send(lease, str(uuid4()), str(uuid4()), 0)
    third = RunPrincipal(**next_request.model_dump())
    h.authority.principal = third
    refused(lambda: c.worker_reservation(third, str(uuid4()), reservation.attempt_id), Code.SCOPE_DENIED)
    ipd1.require(c.worker_reservation(third, reservation.invocation_id, reservation.attempt_id) is reservation)
    h.service.finish_attempt(reservation, outcome("complete"))
    refused(lambda: c.worker_lease(third, str(uuid4())), Code.SCOPE_DENIED)


@pytest.mark.parametrize("stale_first", [False, True])
def test_resume_checks_expected_generation_under_fence(harness, monkeypatch, stale_first):
    h = harness
    h.bound()
    c = composition(h)
    def resume(expected):
        def effect(session, binding):
            if binding.runner_generation != expected + 1:
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            transition(session, binding)
        with Session(h.engine) as session, session.begin():
            return c.lifecycle_in(session, h.caller, ipd1.RUN, "resume", effect)
    first, second = ordered(h, lambda: resume(0 if stale_first else 1),
                            lambda: resume(1 if stale_first else 0), monkeypatch)
    ipd1.require(first[0] == (Code.SCOPE_DENIED.value if stale_first else "ok"))
    ipd1.require(second[0] == ("ok" if stale_first else Code.SCOPE_DENIED.value))
    ipd1.require(h.rows(PrivateContextRow)[0].runner_generation == 2)
    # No second-generation writer in the injected normal-run callback.
    ipd1.require(h.rows(SyntheticAuthorityRow)[0].generation == 1)


def test_concurrent_same_generation_resume_increments_only_once(harness, monkeypatch):
    h = harness
    h.bound()
    c = composition(h)
    def resume():
        def effect(session, binding):
            if binding.runner_generation != 2:
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            transition(session, binding)
        with Session(h.engine) as session, session.begin():
            return c.lifecycle_in(session, h.caller, ipd1.RUN, "resume", effect)
    first, second = ordered(h, resume, resume, monkeypatch)
    ipd1.require(first[0] == "ok" and second[0] == Code.SCOPE_DENIED.value)
    ipd1.require(h.rows(PrivateContextRow)[0].runner_generation == 2)


@pytest.mark.parametrize("cancel_first", [False, True])
def test_canonical_cancel_and_bootstrap_both_orders(harness, monkeypatch, cancel_first):
    h = harness
    h.bound()
    c = composition(h)
    def cancel():
        with Session(h.engine) as session, session.begin():
            return c.lifecycle_in(session, h.caller, ipd1.RUN, "cancel", lambda s, b: transition(s, b, cancel=True))
    def bootstrap():
        def issue(session, authority):
            row = session.get(SyntheticAuthorityRow, 1)
            row.key_generation = authority.runner_generation
            session.add(row)
        with Session(h.engine) as session, session.begin():
            return c.worker_bootstrap_in(session, ipd1.RUN, issue)
    first, second = ordered(h, cancel if cancel_first else bootstrap,
                            bootstrap if cancel_first else cancel, monkeypatch)
    ipd1.require(first[0] == "ok")
    ipd1.require(second[0] == (Code.CANCELLED.value if cancel_first else "ok"))
    ipd1.require(h.rows(PrivateContextRow)[0].revoked)
    ipd1.require(h.rows(SyntheticAuthorityRow)[0].key_generation == 0)


@pytest.mark.parametrize("action", ["resume", "cancel"])
@pytest.mark.parametrize("fault", ["callback", "flush", "postcheck", "metadata", "commit"])
def test_lifecycle_rolls_back_canonical_and_normal_state(harness, monkeypatch, action, fault):
    from sqlalchemy import event
    h = harness
    receipt, _ = h.bound()
    h.change(key_generation=7)
    c = composition(h)
    flush = Session.flush
    armed = False
    def fail_flush(session, *args, **kwargs):
        if armed and session.bind is h.engine:
            raise RuntimeError("fixed flush fault")
        return flush(session, *args, **kwargs)
    if fault == "flush":
        monkeypatch.setattr(Session, "flush", fail_flush)
    def effect(session, binding):
        nonlocal armed
        transition(session, binding, cancel=action == "cancel")
        if fault == "callback":
            raise RuntimeError("fixed callback fault")
        if fault == "flush":
            armed = True
        if fault == "postcheck":
            row = session.get(SyntheticAuthorityRow, 1)
            row.enabled = False
            session.add(row)
        if fault == "metadata":
            row = h.store.execution_in(session, ipd1.RUN)
            row.failure_code = "context_lost"
            session.add(row)
    def call():
        with Session(h.engine) as session, session.begin():
            return c.lifecycle_in(session, h.caller, ipd1.RUN, action, effect)
    def fail_commit(session):
        if session.bind is h.engine:
            raise RuntimeError("fixed commit fault")
    if fault == "commit":
        event.listen(Session, "before_commit", fail_commit)
    try:
        if fault == "commit":
            with pytest.raises(RuntimeError, match="^fixed commit fault$"):
                call()
        else:
            refused(call, Code.SCOPE_DENIED if fault == "metadata" else Code.CONTEXT_UNAVAILABLE)
    finally:
        armed = False
        if fault == "commit":
            event.remove(Session, "before_commit", fail_commit)
    private = h.rows(PrivateContextRow)[0]
    normal = h.rows(SyntheticAuthorityRow)[0]
    ipd1.require(private.runner_generation == 1 and not private.revoked and private.failure_code is None)
    ipd1.require(normal.key_generation == 7 and normal.enabled and not normal.revoked and normal.queued == 0)
    if fault in {"callback", "flush"} or (fault == "commit" and action == "cancel"):
        # Durable rollback does not resurrect already-dropped volatile data.
        refused(lambda: h.service.register(h.caller, h.context()), Code.CONTEXT_LOST)
    else:
        ipd1.require(h.status(receipt).state == "bound")


@pytest.mark.parametrize("lost", [False, True])
def test_resume_retains_terminal_result_or_honest_loss(harness, lost):
    h = harness
    receipt, lease, read = h.complete()
    c = composition(h)
    before = h.rows(PrivateInvocationRow)[0].model_dump()
    if lost:
        h.service.mailbox.results.pop(receipt.context_ref).close()
        ipd1.require(h.status(receipt).state == "lost")
    def call():
        with Session(h.engine) as session, session.begin():
            return c.lifecycle_in(session, h.caller, ipd1.RUN, "resume", transition)
    if lost:
        refused(call, Code.RESULT_LOST)
        ipd1.require(h.rows(PrivateContextRow)[0].runner_generation == 1)
    else:
        resumed = call()
        ipd1.require(resumed.runner_generation == 2 and resumed.attempt_state == "complete")
        result = h.service.result(h.caller, read)
        ipd1.require(result.open_private()["draft"] == ipd1.draft().open_private())
        refused(lambda: h.service.reserve_send(lease, str(uuid4()), str(uuid4()), 0), Code.SCOPE_DENIED)
    ipd1.require(h.rows(PrivateInvocationRow)[0].model_dump() == before)
