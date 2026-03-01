"""Short-lived WebSocket ticket store.

Clients exchange an API key for a one-time ticket via REST,
then connect to WebSocket with that ticket. This prevents
API keys from leaking into server logs, browser history, and proxy logs.
"""

import secrets
import threading
import time
from dataclasses import dataclass

from temper_ai.auth.api_key_auth import AuthContext

TICKET_PREFIX = "wst_"
TICKET_TTL_SECONDS = 30
TICKET_RANDOM_BYTES = 24
_CLEANUP_INTERVAL = 60  # seconds


@dataclass
class _TicketEntry:
    ctx: AuthContext
    expires_at: float


_store: dict[str, _TicketEntry] = {}
_lock = threading.Lock()


def generate_ws_ticket(ctx: AuthContext) -> str:
    """Create a short-lived WebSocket ticket for the given auth context."""
    ticket_id = f"{TICKET_PREFIX}{secrets.token_urlsafe(TICKET_RANDOM_BYTES)}"
    entry = _TicketEntry(ctx=ctx, expires_at=time.monotonic() + TICKET_TTL_SECONDS)
    with _lock:
        _store[ticket_id] = entry
    return ticket_id


def validate_ws_ticket(ticket: str) -> AuthContext | None:
    """Validate and consume a WebSocket ticket. Returns AuthContext or None."""
    with _lock:
        entry = _store.pop(ticket, None)
    if entry is None:
        return None
    if time.monotonic() > entry.expires_at:
        return None
    return entry.ctx
