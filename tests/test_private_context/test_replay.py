"""Ordered real-transaction races, durable refusal retries and crash cuts.

The same cases run on SQLite and the throwaway PostgreSQL tier. Thread outputs
are closed codes, never exception text or private operands. No provider exists.
"""
import os
import sys
from pathlib import Path
from threading import Event, Thread, current_thread
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlmodel import Session

from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.models import (
    PrivateAttemptRow,
    PrivateContextRow,
    PrivateInvocationRow,
)
from temper_ai.private_context.service import PrivateContextService
from temper_ai.private_context.wire import ContextRead

from . import ipd1
from .service_fixtures import Code, outcome, refused
from .service_fixtures import harness as harness
from .test_corpus import child_result


def ordered(h, first, second, monkeypatch):
    """Second tries actual DB fence before first is released. No sleep ordering."""
    locked, attempted, release = Event(), Event(), Event()
    acquired_second = Event()
    results = {}
    original = h.store.fence_in

    def fence(session):
        name = current_thread().name
        if name == "private-second":
            attempted.set()
        original(session)
        if name == "private-first" and not locked.is_set():
            locked.set()
            ipd1.require(release.wait(10))
        elif name == "private-second":
            acquired_second.set()

    def run(name, operation):
        try:
            results[name] = ("ok", operation())
        except PrivateDraftFailure as failure:
            results[name] = (failure.code.value, None)
        except Exception:
            results[name] = ("unexpected", None)

    monkeypatch.setattr(h.store, "fence_in", fence)
    threads = [Thread(name="private-first", target=run, args=("first", first)),
               Thread(name="private-second", target=run, args=("second", second))]
    try:
        threads[0].start()
        ipd1.require(locked.wait(10))
        threads[1].start()
        ipd1.require(attempted.wait(10))
        # The second MUST NOT enter its authority/effect while the first owns
        # the durable fence, regardless of Python mailbox sharing.
        ipd1.require(not acquired_second.wait(0.1))
    finally:
        release.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(10)
        monkeypatch.setattr(h.store, "fence_in", original)
    ipd1.require(all(not thread.is_alive() for thread in threads))
    ipd1.require(set(results) == {"first", "second"})
    ipd1.require(all(value[0] != "unexpected" for value in results.values()))
    return results["first"], results["second"]


def peer(h):
    # Different volatile mutex: the database fence, not a Python global lock,
    # must order these service instances. This is only a test's known snapshot.
    service = PrivateContextService(store=h.store, authority=h.authority, clock=lambda: h.now)
    for ref, context in h.service.mailbox.contexts.items():
        service.mailbox.contexts[ref] = h.context(**context.open_private())
    return service


def test_duplicate_registration_and_bind_queue_identity(harness, monkeypatch):
    h = harness
    first, second = ordered(h, lambda: h.service.register(h.caller, h.context()),
                            lambda: h.service.register(h.caller, h.context()), monkeypatch)
    ipd1.require(first[0] == second[0] == "ok" and first[1] == second[1])
    receipt = first[1]
    first, second = ordered(h, lambda: h.service.bind(h.caller, receipt.context_ref, 1, ipd1.RUN, "profile-v1"),
                            lambda: h.service.bind(h.caller, receipt.context_ref, 1, str(uuid4()), "profile-v1"), monkeypatch)
    ipd1.require(first[0] == second[0] == "ok")
    ipd1.require(first[1].execution_id == second[1].execution_id == ipd1.RUN)
    ipd1.require(len(h.rows(PrivateContextRow)) == 1)


@pytest.mark.parametrize("retry", [False, True])
def test_concurrent_reservation_has_exactly_one_possible_send(harness, monkeypatch, retry):
    h = harness
    h.bound()
    lease = h.lease()
    other = peer(h)
    second_lease = other.resolve(h.principal, ipd1.RUN, 1, "writer")
    invocation = str(uuid4())
    if retry:
        original = h.service.reserve_send(lease, invocation, str(uuid4()), 0)
        h.service.finish_attempt(original, outcome("http_refused", 429))
    first, second = ordered(h, lambda: h.service.reserve_send(lease, invocation, str(uuid4()), 1),
                            lambda: other.reserve_send(second_lease, invocation, str(uuid4()), 2), monkeypatch)
    ipd1.require(first[0] == "ok" and second[0] == Code.SEND_AMBIGUOUS.value)
    ipd1.require(len(h.rows(PrivateInvocationRow)) == 1)
    ipd1.require(len(h.rows(PrivateAttemptRow)) == (2 if retry else 1))
    other.close()


@pytest.mark.parametrize("cancel_first", [False, True])
def test_publication_cancel_orders_never_expose_after_cancel(harness, monkeypatch, cancel_first):
    h = harness
    receipt, _ = h.bound()
    lease = h.lease()
    invocation = str(uuid4())
    reservation = h.service.reserve_send(lease, invocation, str(uuid4()), 0)
    h.service.finish_attempt(reservation, outcome("complete"))
    def publish():
        return h.service.publish(lease, invocation, h.authority.profile.schema.validate_draft(ipd1.draft().to_private_json()))
    def cancel():
        return h.service.cancel(h.principal)
    first, second = ordered(h, cancel if cancel_first else publish,
                            publish if cancel_first else cancel, monkeypatch)
    ipd1.require(first[0] == "ok")
    ipd1.require(second[0] == (Code.SCOPE_DENIED.value if cancel_first else "ok"))
    ipd1.require(h.status(receipt).state == "cancelled" and not h.service.mailbox.results)


@pytest.mark.parametrize("ack_first", [False, True])
def test_read_ack_orders(harness, monkeypatch, ack_first):
    h = harness
    _, _, read = h.complete()
    def get():
        return h.service.result(h.caller, read)
    def ack():
        return h.service.ack(h.caller, read)
    first, second = ordered(h, ack if ack_first else get, get if ack_first else ack, monkeypatch)
    ipd1.require(first[0] == "ok")
    ipd1.require(second[0] == (Code.RESULT_LOST.value if ack_first else "ok"))
    ipd1.require(not h.service.mailbox.results)
    # A private copy already delivered cannot be retracted by ack.
    if not ack_first:
        ipd1.require(first[1].to_private_json() == ipd1.encode_private(first[1].open_private()))
        first[1].close()


@pytest.mark.parametrize("replace_first", [False, True])
def test_replacement_resolve_orders_close_stale_lease(harness, monkeypatch, replace_first):
    h = harness
    receipt, _ = h.bound()
    def replace():
        return h.service.replace(h.caller, ContextRead(context_ref=receipt.context_ref, context_version=1), h.context(application_attempt_id="replacement"))
    def resolve():
        return h.lease()
    first, second = ordered(h, replace if replace_first else resolve,
                            resolve if replace_first else replace, monkeypatch)
    ipd1.require(first[0] == second[0] == "ok")
    lease = second[1] if replace_first else first[1]
    if replace_first:
        ipd1.require(lease.binding.context_version == 2)
    else:
        refused(lambda: lease.open_private(), Code.CONTEXT_LOST)
        refused(lambda: h.service.reserve_send(lease, str(uuid4()), str(uuid4()), 0), Code.SCOPE_DENIED)


@pytest.mark.parametrize("revoke_first", [False, True])
def test_independent_authority_revocation_and_effect_orders(harness, monkeypatch, revoke_first):
    h = harness
    h.bound()
    lease = h.lease()
    def reserve():
        return h.service.reserve_send(lease, str(uuid4()), str(uuid4()), 0)
    def revoke():
        return h.change(revoked=True)
    first, second = ordered(h, revoke if revoke_first else reserve,
                            reserve if revoke_first else revoke, monkeypatch)
    ipd1.require(first[0] == "ok")
    ipd1.require(second[0] == (Code.CANCELLED.value if revoke_first else "ok"))
    ipd1.require(len(h.rows(PrivateAttemptRow)) == (0 if revoke_first else 1))
    refused(lambda: h.service.reserve_send(lease, str(uuid4()), str(uuid4()), 1), Code.CANCELLED)


@pytest.mark.parametrize("phase,status,allowed", [("reserved", None, False), ("streaming", None, False), ("complete", None, False), ("http_refused", 400, False), ("http_refused", 413, False), ("http_refused", 401, True), ("http_refused", 403, True), ("http_refused", 429, True), ("http_refused", 529, True)])
def test_only_committed_explicit_pre_stream_refusal_permits_next_attempt(harness, phase, status, allowed):
    h = harness
    h.bound()
    lease = h.lease()
    invocation = str(uuid4())
    reservation = h.service.reserve_send(lease, invocation, str(uuid4()), 0)
    h.service.finish_attempt(reservation, outcome(phase, status))
    def operation():
        return h.service.reserve_send(lease, invocation, str(uuid4()), 1)
    if allowed:
        operation()
    else:
        refused(operation, Code.SEND_AMBIGUOUS)
    ipd1.require(len(h.rows(PrivateAttemptRow)) == (2 if allowed else 1))
    refused(lambda: h.service.reserve_send(lease, str(uuid4()), str(uuid4()), 2), Code.SEND_AMBIGUOUS)


@pytest.mark.parametrize("status,allowed", [(401, False), (403, False), (429, False), (529, True)])
def test_refused_slot_policy(harness, status, allowed):
    h = harness
    h.bound()
    lease = h.lease()
    invocation = str(uuid4())
    reservation = h.service.reserve_send(lease, invocation, str(uuid4()), 0)
    h.service.finish_attempt(reservation, outcome("http_refused", status))
    def again():
        return h.service.reserve_send(lease, invocation, str(uuid4()), 0)
    if allowed:
        again()
    else:
        refused(again, Code.SCOPE_DENIED)


@pytest.mark.parametrize("phase", ["reserved", "refused"])
def test_abrupt_process_exit_preserves_send_history_not_buffers(harness, phase):
    h = harness
    code = (
        "import os\n"
        "from datetime import UTC, datetime\n"
        "from uuid import uuid4\n"
        "from sqlmodel import create_engine\n"
        "from tests.test_private_context import ipd1\n"
        "from tests.test_private_context.service_fixtures import SyntheticAuthority, outcome\n"
        "from temper_ai.private_context.service import PrivateContextService\n"
        "from temper_ai.private_context.store import MetadataStore\n"
        "from temper_ai.private_context.wire import RegisterContext\n"
        "authority = SyntheticAuthority()\n"
        "service = PrivateContextService(store=MetadataStore(create_engine(os.environ['SYNTHETIC_DATABASE'], hide_parameters=True)), authority=authority, clock=lambda: datetime(2090,1,1,tzinfo=UTC))\n"
        "receipt = service.register(authority.caller, RegisterContext(ipd1.registration().to_private_json()))\n"
        "service.bind(authority.caller, receipt.context_ref, 1, ipd1.RUN, 'profile-v1')\n"
        "lease = service.resolve(authority.principal, ipd1.RUN, 1, 'writer')\n"
        "reservation = service.reserve_send(lease, str(uuid4()), str(uuid4()), 0)\n"
        + ("service.finish_attempt(reservation, outcome('http_refused', 429))\n" if phase == "refused" else "")
        + "os._exit(73)\n"
    )
    env = {**os.environ, "SYNTHETIC_DATABASE": h.engine.url.render_as_string(hide_password=False), "PYTHONPATH": str(Path(__file__).resolve().parents[2].parent)}
    status, output = child_result([sys.executable, "-c", code], env)
    ipd1.require(status == 73)
    ipd1.require(ipd1.scan({ipd1.Surface.ERROR: output}).clean)
    rows = h.rows(PrivateInvocationRow)
    ipd1.require(len(rows) == 1 and rows[0].state == phase)
    ipd1.require(len(h.rows(PrivateAttemptRow)) == 1)
    refused(lambda: h.lease(), Code.SEND_AMBIGUOUS if phase == "reserved" else Code.CONTEXT_LOST)
    refused(lambda: h.service.register(h.caller, h.context()), Code.CONTEXT_LOST)
    ipd1.require(not h.service.mailbox.contexts)


@pytest.mark.parametrize("cut", ["before", "after"])
def test_refusal_commit_loss_never_releases_a_next_send(harness, cut):
    h = harness
    h.bound()
    lease = h.lease()
    invocation = str(uuid4())
    reservation = h.service.reserve_send(lease, invocation, str(uuid4()), 0)
    # before_commit must exclude the nested savepoint; after_commit is the
    # actual outer commit acknowledgement cut, not a fake rolled-back write.
    def fail(session):
        if session.bind is h.engine and not session.in_nested_transaction():
            raise RuntimeError("fixed injected commit fault")
    event.listen(Session, "before_commit" if cut == "before" else "after_commit", fail)
    try:
        refused(lambda: h.service.finish_attempt(reservation, outcome("http_refused", 429)), Code.CONTEXT_UNAVAILABLE)
    finally:
        event.remove(Session, "before_commit" if cut == "before" else "after_commit", fail)
    ipd1.require(not h.service.mailbox.contexts)
    state = h.rows(PrivateInvocationRow)[0].state
    ipd1.require(state == ("reserved" if cut == "before" else "refused"))
    refused(lambda: h.service.reserve_send(lease, invocation, str(uuid4()), 1), Code.SCOPE_DENIED)
    # Restart gives no old snapshot or equivalent registration, even when the
    # refusal actually committed but the observer lost its acknowledgement.
    refused(lambda: h.service.register(h.caller, h.context()), Code.CONTEXT_LOST)
    ipd1.require(len(h.rows(PrivateAttemptRow)) == 1)
