"""Volatile custody, safe metadata, transaction composition and lifecycle."""
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, inspect, select
from sqlmodel import Session

from temper_ai.private_context.migration import TABLES, install_metadata
from temper_ai.private_context.models import (
    PrivateAttemptRow,
    PrivateContextRow,
    PrivateInvocationRow,
    PrivateRefusalRow,
)
from temper_ai.private_context.service import PrivateContextService
from temper_ai.private_context.wire import ContextRead

from . import ipd1
from .service_fixtures import Code, SyntheticAuthorityRow, outcome, refused
from .service_fixtures import harness as harness
from .test_corpus import child_result


def restart(h):
    h.service.close()
    h.service = PrivateContextService(store=h.store, authority=h.authority, clock=lambda: h.now)


@pytest.mark.parametrize("phase,code", [("registered", Code.CONTEXT_LOST), ("reserved", Code.SEND_AMBIGUOUS), ("complete", Code.RESULT_LOST), ("published", Code.RESULT_LOST)])
def test_restart_never_recovers_private_payload_or_resends(harness, phase, code):
    h = harness
    receipt, _ = h.bound()
    lease = h.lease()
    invocation = str(uuid4())
    if phase != "registered":
        reservation = h.service.reserve_send(lease, invocation, str(uuid4()), 0)
        if phase in {"complete", "published"}:
            h.service.finish_attempt(reservation, outcome("complete"))
        if phase == "published":
            h.service.publish(lease, invocation, h.authority.profile.schema.validate_draft(ipd1.draft().to_private_json()))
    restart(h)
    status = h.status(receipt)
    ipd1.require(status.state == "lost" and status.failure.code == code)
    refused(lambda: h.service.register(h.caller, h.context()), code)
    refused(lambda: h.lease(), code)
    refused(lambda: h.service.reserve_send(lease, invocation, str(uuid4()), 1), Code.SCOPE_DENIED)
    ipd1.require(not h.service.mailbox.contexts and not h.service.mailbox.results)
    ipd1.require(len(h.rows(PrivateInvocationRow)) == (0 if phase == "registered" else 1))


@pytest.mark.parametrize("http_status", [401, 403, 429, 529])
@pytest.mark.parametrize("first", ["status", "resolve"])
def test_refused_send_restart_reports_context_loss_in_either_read_order(harness, http_status, first):
    h = harness
    receipt, _ = h.bound()
    lease = h.lease()
    invocation = str(uuid4())
    reservation = h.service.reserve_send(lease, invocation, str(uuid4()), 0)
    h.service.finish_attempt(reservation, outcome("http_refused", http_status))
    restart(h)
    if first == "resolve":
        refused(lambda: h.lease(), Code.CONTEXT_LOST)
    status = h.status(receipt)
    ipd1.require(status.state == "lost" and status.failure.code == Code.CONTEXT_LOST)
    ipd1.require(status.failure.transmission == "refused")
    refused(lambda: h.lease(), Code.CONTEXT_LOST)
    refused(lambda: h.service.register(h.caller, h.context()), Code.CONTEXT_LOST)
    refused(lambda: h.service.replace(h.caller,
            ContextRead(context_ref=receipt.context_ref, context_version=1),
            h.context(application_attempt_id="replacement")), Code.SEND_AMBIGUOUS)
    refused(lambda: h.service.reserve_send(lease, invocation, str(uuid4()), 1), Code.SCOPE_DENIED)
    ipd1.require(len(h.rows(PrivateInvocationRow)) == len(h.rows(PrivateAttemptRow)) == 1)
    ipd1.require(h.rows(PrivateInvocationRow)[0].state == "refused")
    ipd1.require(not h.service.mailbox.contexts and not h.service.mailbox.results)


def test_explicit_replacement_only_before_any_reservation(harness):
    h = harness
    receipt, _ = h.bound()
    stale = h.lease()
    old = ContextRead(context_ref=receipt.context_ref, context_version=1)
    replacement = h.service.replace(h.caller, old, h.context(application_attempt_id="replacement"))
    ipd1.require(replacement.context_ref != receipt.context_ref and replacement.context_version == 2)
    ipd1.require(h.status(receipt).state == "cancelled")
    refused(lambda: h.service.reserve_send(stale, str(uuid4()), str(uuid4()), 0), Code.SCOPE_DENIED)
    lease = h.lease()
    ipd1.require(lease.binding.context_version == 2)
    reservation = h.service.reserve_send(lease, str(uuid4()), str(uuid4()), 0)
    h.service.finish_attempt(reservation, outcome("http_refused", 429))
    # A refusal still permanently forbids changing context beneath invocation.
    refused(lambda: h.service.replace(h.caller, ContextRead(context_ref=replacement.context_ref, context_version=2), h.context(application_attempt_id="third")), Code.SCOPE_DENIED)
    ipd1.require(len(h.rows(PrivateContextRow)) == 2)


def test_explicit_replacement_after_pre_send_context_loss(harness):
    h = harness
    receipt, _ = h.bound()
    restart(h)
    ipd1.require(h.status(receipt).failure.code == Code.CONTEXT_LOST)
    new = h.service.replace(h.caller, ContextRead(context_ref=receipt.context_ref, context_version=1), h.context(application_attempt_id="recovery"))
    ipd1.require(h.lease().binding.context_ref == new.context_ref)


@pytest.mark.parametrize("action", ["delete", "cancel", "expire", "release"])
def test_terminal_lifecycle_drops_custody(harness, action):
    h = harness
    receipt, lease, read = h.complete()
    if action == "delete":
        h.service.delete(h.caller, receipt.context_ref)
    elif action == "cancel":
        h.service.cancel(h.principal)
    elif action == "expire":
        h.now = datetime(2099, 1, 1, tzinfo=UTC)
        ipd1.require(h.service.expire() == 1)
        ipd1.require(h.service.expire() == 0)
    else:
        h.service.release(lease, "failed")
    ipd1.require(not h.service.mailbox.contexts and not h.service.mailbox.results and not h.service.mailbox.leases and not h.service.mailbox.reservations)
    refused(lambda: lease.open_private(), Code.CONTEXT_LOST)
    if action != "expire":
        refused(lambda: h.service.result(h.caller, read), Code.CANCELLED)
    ipd1.require(len(h.rows(PrivateInvocationRow)) == 1)


def test_completed_release_keeps_repeatable_mailbox_until_ack(harness):
    h = harness
    receipt, lease, read = h.complete()
    h.service.release(lease, "completed")
    ipd1.require(not h.service.mailbox.contexts and not h.service.mailbox.leases)
    ipd1.require(h.status(receipt).state == "ready")
    h.service.result(h.caller, read)
    h.service.ack(h.caller, read)
    ipd1.require(not h.service.mailbox.results)


def test_composed_bind_never_commits_unrelated_writes_on_refusal(harness):
    h = harness
    receipt = h.service.register(h.caller, h.context())
    session = Session(h.engine)
    try:
        h.store.fence_in(session)
        state = session.get(SyntheticAuthorityRow, 1)
        state.generation = 99  # Unrelated caller-owned pending write.
        refused(lambda: h.service.bind_in(session, h.caller, receipt.context_ref, 2, ipd1.RUN, "profile-v1"), Code.SCOPE_DENIED)
        ipd1.require(session.in_transaction() and session.is_modified(state))
        session.rollback()
    finally:
        session.close()
    h.service.record_binding_refusal(h.caller, Code.SCOPE_DENIED)
    ipd1.require(h.rows(SyntheticAuthorityRow)[0].generation == 1)
    ipd1.require(h.rows(PrivateContextRow)[0].execution_id is None)
    ipd1.require(len(h.rows(PrivateRefusalRow)) == 1)
    with Session(h.engine) as session, session.begin():
        h.store.fence_in(session)
        binding = h.service.bind_in(session, h.caller, receipt.context_ref, 1, ipd1.RUN, "profile-v1")
        ipd1.require(binding.execution_id == ipd1.RUN)
    ipd1.require(h.lease().binding.execution_id == ipd1.RUN)


def test_metadata_has_no_private_bytes_or_content_columns(harness):
    h = harness
    h.complete()
    with h.engine.connect() as connection:
        rows = [list(connection.execute(select(table)).mappings()) for table in TABLES]
    ipd1.require(ipd1.scan({ipd1.Surface.EXPORT: repr(rows)}).clean)
    prohibited = {"payload", "digest", "context", "draft", "provider_text", "prompt", "image", "content"}
    columns = {column["name"] for table in TABLES for column in inspect(h.engine).get_columns(table.name)}
    ipd1.require(not columns.intersection(prohibited))
    private_objects = (h.service, h.service.mailbox, h.authority.profile, h.service.mailbox.contexts)
    ipd1.require(ipd1.scan({ipd1.Surface.ERROR: repr(private_objects)}).clean)


@pytest.mark.parametrize("change,code", [("revoked", Code.CANCELLED), ("run-expiry", Code.CONTEXT_EXPIRED), ("context-expiry", Code.CONTEXT_EXPIRED)])
def test_duplicate_ack_rechecks_validity(harness, change, code):
    h = harness
    receipt, _, read = h.complete()
    h.service.ack(h.caller, read)
    h.service.ack(h.caller, read)
    if change == "revoked":
        h.change(revoked=True)
    elif change == "run-expiry":
        h.now = datetime(2098, 1, 1, tzinfo=UTC)
    else:
        with Session(h.engine) as session, session.begin():
            h.store.fence_in(session)
            row = session.get(PrivateContextRow, receipt.context_ref)
            row.expires_at = h.now.isoformat()
            session.add(row)
    refused(lambda: h.service.ack(h.caller, read), code)
    ipd1.require(len(h.rows(PrivateRefusalRow)) == 1)


def test_additive_install_preserves_existing_rows_and_fence(harness):
    h = harness
    existing = Table("synthetic_existing_private_install", MetaData(), Column("id", Integer, primary_key=True))
    existing.create(h.engine, checkfirst=True)
    with h.engine.begin() as connection:
        connection.execute(existing.insert().values(id=1))
    receipt, _ = h.bound()
    install_metadata(h.engine)
    install_metadata(h.engine)
    with h.engine.connect() as connection:
        ipd1.require(connection.execute(select(existing.c.id)).scalar_one() == 1)
    ipd1.require(h.status(receipt).state == "bound")
    ipd1.require(len(h.rows(PrivateContextRow)) == 1)


@pytest.mark.parametrize("mutant", [False, True], ids=["fixed-service-failure", "leaking-negative-control"])
def test_actual_service_failure_is_safe_at_verbose_level(tmp_path, mutant):
    target = tmp_path / "test_private_failure.py"
    target.write_text(
        "from sqlmodel import create_engine\n"
        "from tests.test_private_context import ipd1\n"
        "from tests.test_private_context.service_fixtures import Harness\n"
        "from temper_ai.private_context.wire import ContextRead\n"
        "def test_failure(tmp_path):\n"
        "    h = Harness(create_engine('sqlite:///' + str(tmp_path / 'private.sqlite'), hide_parameters=True))\n"
        "    receipt, _ = h.bound()\n"
        "    def fail(*args):\n"
        "        raise RuntimeError(ipd1.canaries()[0].decode())\n"
        "    h.store.refusal_in = fail\n"
        + ("    fail()\n" if mutant else
           "    h.service.status(h.caller, ContextRead(context_ref=receipt.context_ref, context_version=2))\n"),
        encoding="utf-8",
    )
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    junit = tmp_path / "report.xml"
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONPATH": str(Path(__file__).resolve().parents[2].parent)}
    code, output = child_result([sys.executable, "-m", "pytest", "-c", str(config), "-vv", "--tb=long", f"--junitxml={junit}", str(target)], env)
    ipd1.require(code == 1)
    report = ipd1.scan({ipd1.Surface.ERROR: output, ipd1.Surface.EXPORT: junit.read_bytes()})
    ipd1.require(report.clean is not mutant)


def test_authenticated_refusal_once_and_refusal_write_failure_is_unavailable(harness, monkeypatch):
    h = harness
    receipt, _ = h.bound()
    wrong = ContextRead(context_ref=receipt.context_ref, context_version=999)
    refused(lambda: h.service.status(h.caller, wrong), Code.SCOPE_DENIED)
    ipd1.require(len(h.rows(PrivateRefusalRow)) == 1)
    def fail(*args):
        raise RuntimeError("sensitive diagnostic withheld")
    monkeypatch.setattr(h.store, "refusal_in", fail)
    refused(lambda: h.service.status(h.caller, wrong), Code.CONTEXT_UNAVAILABLE)
    ipd1.require(len(h.rows(PrivateRefusalRow)) == 1)
    ipd1.require(not h.service.mailbox.contexts)
