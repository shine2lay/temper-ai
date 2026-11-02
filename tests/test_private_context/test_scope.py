"""C1 actual service: happy case first, exact authority/scope refusal twins."""
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlmodel import Session

from temper_ai.private_context.contracts import (
    CallerPrincipal,
    PrivateLease,
    RunPrincipal,
)
from temper_ai.private_context.models import (
    PrivateAttemptRow,
    PrivateContextRow,
    PrivateRefusalRow,
)
from temper_ai.private_context.schema import ValidatedDraft
from temper_ai.private_context.wire import ContextRead, ResultRead

from . import ipd1
from .service_fixtures import Code, outcome, refused
from .service_fixtures import harness as harness


def test_service_combined_happy_case(harness):
    h = harness
    receipt, binding = h.bound()
    ipd1.require(binding.execution_id == ipd1.RUN)
    equal = h.service.register(h.caller, h.context())
    ipd1.require(equal == receipt)
    retry = h.service.bind(h.caller, receipt.context_ref, 1, str(uuid4()), "profile-v1")
    ipd1.require(retry.execution_id == ipd1.RUN)
    lease = h.lease()
    invocation = str(uuid4())
    first = h.service.reserve_send(lease, invocation, str(uuid4()), 0)
    h.service.finish_attempt(first, outcome("http_refused", 429))
    second = h.service.reserve_send(lease, invocation, str(uuid4()), 1)
    h.service.finish_attempt(second, outcome("complete"))
    private = h.authority.profile.schema.validate_draft(ipd1.draft().to_private_json())
    draft = h.service.publish(lease, invocation, private)
    read = ResultRead(context_ref=receipt.context_ref, execution_id=ipd1.RUN, draft_ref=draft.draft_ref)
    result1 = h.service.result(h.caller, read)
    result2 = h.service.result(h.caller, read)
    ipd1.require(result1.to_private_json() == result2.to_private_json())
    result1.close()
    ipd1.require(result2.open_private()["draft"] == ipd1.draft().open_private())
    # The app's durable commit is external; this checks only receipt/ack custody.
    h.service.ack(h.caller, read)
    h.service.ack(h.caller, read)
    ipd1.require(h.status(receipt).state == "acknowledged")
    refused(lambda: h.service.result(h.caller, read), Code.RESULT_LOST)
    refused(lambda: h.lease(), Code.RESULT_LOST)
    ipd1.require(len(h.rows(PrivateAttemptRow)) == 2)
    ipd1.require(not h.service.mailbox.contexts and not h.service.mailbox.results)


@pytest.mark.parametrize("kind", ["caller", "worker", "missing-adapter", "missing-config"])
def test_no_provenance_no_payload_or_binding(harness, kind):
    h = harness
    if kind == "caller":
        forged = CallerPrincipal(**h.caller.model_dump())
        refused(lambda: h.service.register(forged, h.context()), Code.UNAUTHENTICATED)
    elif kind == "worker":
        forged = RunPrincipal(**h.principal.model_dump())
        refused(lambda: h.service.resolve(forged, ipd1.RUN, 1, "writer"), Code.UNAUTHENTICATED)
    elif kind == "missing-adapter":
        h.service.authority = None
        refused(lambda: h.service.register(h.caller, h.context()), Code.CONTEXT_UNAVAILABLE)
    else:
        h.change(enabled=False)
        refused(lambda: h.service.register(h.caller, h.context()), Code.CONTEXT_UNAVAILABLE)
    ipd1.require(len(h.rows(PrivateContextRow)) == 0)
    ipd1.require(not h.service.mailbox.contexts)
    ipd1.require(len(h.rows(PrivateRefusalRow)) == 0)


@pytest.mark.parametrize("field", ["owner_principal", "namespace", "profile", "profile_revision", "workflow", "workflow_revision", "node_path"])
@pytest.mark.parametrize("change", ["prefix", "suffix"])
def test_each_bound_scope_is_exact(harness, field, change):
    h = harness
    h.bound()
    old = getattr(h.authority.profile, field)
    new = "other." + old if change == "prefix" else old + ".other"
    h.authority.profile = replace(h.authority.profile, **{field: new})
    # Match the requested node to current config so the durable row-scope guard,
    # not the earlier argument-node guard, must reject a changed node binding.
    require_scope_refusal(h)
    rows = h.rows(PrivateRefusalRow)
    ipd1.require(len(rows) == 1 and rows[0].code == "scope_denied")
    ipd1.require(not h.service.mailbox.leases)


def require_scope_refusal(h):
    refused(lambda: h.service.resolve(h.principal, ipd1.RUN, 1, h.authority.profile.node_path), Code.SCOPE_DENIED)


@pytest.mark.parametrize("field", ["owner_principal", "namespace", "profile", "profile_revision", "workflow", "workflow_revision", "node_path"])
@pytest.mark.parametrize("mutation", ["drop", "prefix", "contains"])
def test_durable_scope_refusal_bites_removed_and_loosened_matches(harness, monkeypatch, field, mutation):
    from temper_ai.private_context import scope
    from temper_ai.private_context.errors import PrivateDraftFailure
    h = harness
    h.bound()
    old = getattr(h.authority.profile, field)
    changed = old + ".other" if mutation != "contains" else "other." + old + ".other"
    h.authority.profile = replace(h.authority.profile, **{field: changed})
    def mutant(row, profile):
        for name, value in scope.profile_fields(profile).items():
            saved = getattr(row, name)
            if name == field and (mutation == "drop" or (mutation == "prefix" and value.startswith(saved)) or (mutation == "contains" and saved in value)):
                continue
            if saved != value:
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
    monkeypatch.setattr(scope, "row_scope", mutant)
    with pytest.raises(AssertionError, match="^contract$"):
        require_scope_refusal(h)


@pytest.mark.parametrize("field", ["context_schema", "result_schema", "schema_revision"])
def test_schema_bindings_rechecked(harness, field):
    h = harness
    receipt, _ = h.bound()
    with Session(h.engine) as session, session.begin():
        h.store.fence_in(session)
        row = session.get(PrivateContextRow, receipt.context_ref)
        setattr(row, field, getattr(row, field) + ".other")
        session.add(row)
    refused(lambda: h.lease(), Code.SCOPE_DENIED)
    ipd1.require(len(h.rows(PrivateRefusalRow)) == 1)


@pytest.mark.parametrize("change", ["execution", "generation", "node-prefix", "node-suffix", "use"])
def test_resolve_arguments_do_not_confer_scope(harness, change):
    h = harness
    h.bound()
    args = dict(execution_id=ipd1.RUN, running_attempt=1, node_path="writer", use="draft")
    args.update({"execution": {"execution_id": str(uuid4())}, "generation": {"running_attempt": 2}, "node-prefix": {"node_path": "other.writer"}, "node-suffix": {"node_path": "writer.other"}, "use": {"use": "other"}}[change])
    refused(lambda: h.service.resolve(h.principal, **args), Code.SCOPE_DENIED)
    ipd1.require(len(h.rows(PrivateRefusalRow)) == 1)


@pytest.mark.parametrize("change,code", [("generation", Code.SCOPE_DENIED), ("revoked", Code.CANCELLED), ("deadline", Code.SCOPE_DENIED), ("credential", Code.UNAUTHENTICATED)])
def test_recheck_after_lease_before_send(harness, change, code):
    h = harness
    h.bound()
    lease = h.lease()
    if change == "generation":
        h.change(generation=2)
    elif change == "revoked":
        h.change(revoked=True)
    elif change == "deadline":
        h.change(deadline="2089-01-01T00:00:00Z")
    else:
        h.authority.profile = replace(h.authority.profile, credential_deadline=h.now)
    refused(lambda: h.service.reserve_send(lease, str(uuid4()), str(uuid4()), 0), code)
    ipd1.require(len(h.rows(PrivateAttemptRow)) == 0)


def test_issued_custody_not_constructed_lease_or_reservation(harness):
    h = harness
    h.bound()
    lease = h.lease()
    forged = PrivateLease(lease_id=lease.lease_id, binding=lease.binding, context=h.context())
    refused(lambda: h.service.reserve_send(forged, str(uuid4()), str(uuid4()), 0), Code.SCOPE_DENIED)
    reservation = h.service.reserve_send(lease, str(uuid4()), str(uuid4()), 0)
    refused(lambda: h.service.finish_attempt(reservation.model_copy(), outcome("complete")), Code.SCOPE_DENIED)
    h.service.finish_attempt(reservation, outcome("complete"))


def test_mutable_lease_fields_never_rebind_captured_authority(harness):
    h = harness
    h.bound()
    lease = h.lease()
    lease_id = lease.lease_id
    lease.binding = lease.binding.model_copy(update={"context_ref": str(uuid4()), "runner_generation": 999})
    lease.lease_id = str(uuid4())
    reservation = h.service.reserve_send(lease, str(uuid4()), str(uuid4()), 0)
    ipd1.require(reservation.lease_id == lease_id and reservation.runner_generation == 1)


@pytest.mark.parametrize("field", ["context_ref", "execution_id", "draft_ref"])
def test_result_exact_read_tuple(harness, field):
    h = harness
    _, _, read = h.complete()
    bad = ResultRead(**{**read.model_dump(), field: str(uuid4())})
    refused(lambda: h.service.result(h.caller, bad), Code.SCOPE_DENIED)
    refused(lambda: h.service.ack(h.caller, bad), Code.SCOPE_DENIED)
    ipd1.require(len(h.rows(PrivateRefusalRow)) == 2)
    h.service.result(h.caller, read)


def test_source_schema_revalidated_at_publication(harness):
    h = harness
    h.bound()
    lease = h.lease()
    invocation = str(uuid4())
    reservation = h.service.reserve_send(lease, invocation, str(uuid4()), 0)
    h.service.finish_attempt(reservation, outcome("complete"))
    forged = ValidatedDraft(b'{"reply":"synthetic"}')
    refused(lambda: h.service.publish(lease, invocation, forged), Code.OUTPUT_INVALID)
    ipd1.require(not h.service.mailbox.results)
    ipd1.require(len(h.rows(PrivateRefusalRow)) == 1)


def test_registration_bytes_schema_and_deadline_twins(harness):
    h = harness
    receipt = h.service.register(h.caller, h.context())
    refused(lambda: h.service.register(h.caller, h.context(context={"extra": True})), Code.CONTEXT_CONFLICT)
    refused(lambda: h.service.register(h.caller, h.context(application_attempt_id="bad-schema", context={"extra": True})), Code.CONTEXT_INVALID)
    refused(lambda: h.service.register(h.caller, h.context(application_attempt_id="expired", expires_at=h.now.isoformat())), Code.CONTEXT_EXPIRED)
    h.now += timedelta(days=1)
    ipd1.require(h.status(receipt).state == "registered")
    refused(lambda: h.service.status(h.caller, ContextRead(context_ref=receipt.context_ref, context_version=2)), Code.SCOPE_DENIED)
    ipd1.require(len(h.rows(PrivateRefusalRow)) == 4)


def test_outcome_revalidated_not_trusted_by_type(harness, recwarn):
    h = harness
    h.bound()
    lease = h.lease()
    reservation = h.service.reserve_send(lease, str(uuid4()), str(uuid4()), 0)
    forged = outcome("complete").model_copy(update={"http_status": ipd1.canaries()[0].decode()})
    refused(lambda: h.service.finish_attempt(reservation, forged), Code.CONTEXT_INVALID)
    ipd1.require(h.rows(PrivateAttemptRow)[0].outcome_metadata is None)
    ipd1.require(ipd1.scan({ipd1.Surface.ERROR: repr(list(recwarn))}).clean)
