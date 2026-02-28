"""Tests for temper_ai/auth/ws_tickets.py."""

import time

import pytest

import temper_ai.auth.ws_tickets as ws_mod
from temper_ai.auth.api_key_auth import AuthContext
from temper_ai.auth.ws_tickets import (
    TICKET_PREFIX,
    cleanup_expired,
    generate_ws_ticket,
    validate_ws_ticket,
)


@pytest.fixture(autouse=True)
def clear_ticket_store():
    """Isolate tests by clearing global ticket store before and after each test."""
    ws_mod._store.clear()
    yield
    ws_mod._store.clear()


def _make_ctx(user_id: str = "user-1") -> AuthContext:
    return AuthContext(
        user_id=user_id,
        tenant_id="tenant-1",
        role="viewer",
        api_key_id="key-1",
    )


# --- generate_ws_ticket ---


def test_generate_ws_ticket_has_prefix():
    ctx = _make_ctx()
    ticket = generate_ws_ticket(ctx)
    assert ticket.startswith(TICKET_PREFIX)


def test_generate_ws_ticket_stored_in_store():
    ctx = _make_ctx()
    ticket = generate_ws_ticket(ctx)
    assert ticket in ws_mod._store


def test_generate_ws_ticket_unique():
    ctx = _make_ctx()
    t1 = generate_ws_ticket(ctx)
    t2 = generate_ws_ticket(ctx)
    assert t1 != t2


def test_generate_ws_ticket_stores_correct_ctx():
    ctx = _make_ctx(user_id="special-user")
    ticket = generate_ws_ticket(ctx)
    assert ws_mod._store[ticket].ctx is ctx


# --- validate_ws_ticket ---


def test_validate_ws_ticket_returns_ctx():
    ctx = _make_ctx()
    ticket = generate_ws_ticket(ctx)
    result = validate_ws_ticket(ticket)
    assert result is ctx


def test_validate_ws_ticket_consumes_ticket():
    ctx = _make_ctx()
    ticket = generate_ws_ticket(ctx)
    validate_ws_ticket(ticket)
    # Second call must return None — ticket was consumed
    assert validate_ws_ticket(ticket) is None


def test_validate_ws_ticket_unknown_ticket():
    result = validate_ws_ticket("wst_nonexistent_ticket_xyz")
    assert result is None


def test_validate_ws_ticket_expired():
    ctx = _make_ctx()
    ticket = generate_ws_ticket(ctx)
    # Force expiry by setting expires_at in the past
    ws_mod._store[ticket].expires_at = time.monotonic() - 1.0
    result = validate_ws_ticket(ticket)
    assert result is None


# --- cleanup_expired ---


def test_cleanup_expired_removes_expired():
    ctx = _make_ctx()
    ticket = generate_ws_ticket(ctx)
    ws_mod._store[ticket].expires_at = time.monotonic() - 1.0
    count = cleanup_expired()
    assert count == 1
    assert ticket not in ws_mod._store


def test_cleanup_expired_keeps_valid():
    ctx = _make_ctx()
    ticket = generate_ws_ticket(ctx)
    count = cleanup_expired()
    assert count == 0
    assert ticket in ws_mod._store


def test_cleanup_expired_mixed():
    expired_ticket = generate_ws_ticket(_make_ctx("expired-user"))
    valid_ticket = generate_ws_ticket(_make_ctx("valid-user"))
    ws_mod._store[expired_ticket].expires_at = time.monotonic() - 1.0

    count = cleanup_expired()

    assert count == 1
    assert expired_ticket not in ws_mod._store
    assert valid_ticket in ws_mod._store


def test_cleanup_expired_empty_store():
    count = cleanup_expired()
    assert count == 0
