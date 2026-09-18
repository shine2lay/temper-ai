"""A pool of interchangeable subscription tokens, with sticky assignment.

Several Claude subscriptions give several rate-limit windows. Spreading
calls across them multiplies the ceiling — but spreading *one agent's*
calls across them destroys the thing that makes a long tool-using run
affordable: Anthropic's server-side prompt cache is per credential, and a
run re-sends its whole transcript on every iteration. So the rule is

    rotate between agents, never within one.

`sticky_key` is what implements that: the same key always prefers the same
slot, so one agent's calls in one run stay on one token and hit a warm
cache, while a different agent (or a different run) hashes elsewhere and
uses a different quota.

A token that answers "rate limited" is cooled until its reset and skipped;
when every token is cooling the pool says so rather than handing back a
credential that is certain to fail. Cooldowns live at module scope so they
are shared by every provider instance in the process.

The Claude Code CLI provider (local/providers/claude_code.py) grew this
first, for the same reasons; this is that design made provider-agnostic so
the direct-API providers can have it too.
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# How long a token sits out when the provider gave no reset time.
DEFAULT_COOLDOWN_S = 15 * 60
# The shortest a cooling lasts, even when the named reset is already past.
# Zero would mean the retry picks the same limited token again and spends the
# next attempt learning what it just learned.
MIN_COOLDOWN_S = 5
# Added to a reset time the provider *did* give, so a clock skew of a few
# seconds doesn't put the token straight back into a limited state.
RESET_PAD_S = 30


def tokens_from_env(base: str, extra_suffixes: tuple[str, ...] = ("BACKUP",), limit: int = 10) -> list[str]:
    """Every token configured under `base`: BASE, BASE_BACKUP, BASE_2..BASE_9.

    Order is stable and duplicates are dropped, so the same env produces the
    same slot for the same sticky key on every process start.
    """
    names = [base, *[f"{base}_{s}" for s in extra_suffixes], *[f"{base}_{i}" for i in range(2, limit)]]
    found = [(os.environ.get(n) or "").strip() for n in names]
    return list(dict.fromkeys(t for t in found if t))


def sticky_key_from_kwargs(kwargs: dict) -> str | None:
    """The cache-locality key for one provider call, from what the engine forwards.

    1. `session_id` — providers that resume sessions pass a stable id.
    2. `{execution_id}-{agent_name}` — one agent within one run. Anthropic's
       cache TTL is minutes, so scoping to the run costs no real cache hits
       and spreads different agents across the pool.
    3. None — no locality; the caller gets a random available slot.
    """
    session_id = kwargs.get("session_id")
    if session_id:
        return str(session_id)
    run_id, agent_name = kwargs.get("execution_id"), kwargs.get("agent_name")
    if run_id and agent_name:
        return f"{run_id}-{agent_name}"
    return None


class PoolExhausted(RuntimeError):
    """Every token in the pool is cooling. Carries the soonest reset."""

    def __init__(self, size: int, reset_at: float | None):
        self.reset_at = reset_at
        when = _fmt(reset_at) if reset_at else "unknown"
        super().__init__(f"token pool exhausted — all {size} tokens cooling; soonest reset {when}")


def _fmt(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%d %H:%MZ")


@dataclass
class TokenPool:
    """Interchangeable credentials for one provider, with sticky assignment."""

    name: str
    tokens: list[str]
    _cooldown: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    #: Slot used by callers that give no sticky key. Chosen once, not per call:
    #: picking randomly each time spreads one conversation across every
    #: subscription, and each holds its own cache, so a run alternating between
    #: two accounts reads a prefix one turn stale and re-writes the rest. Seen
    #: on a probe: every other turn a full miss.
    _default_slot: int = field(default_factory=lambda: random.randrange(1 << 30))  # noqa: S311

    def __len__(self) -> int:
        return len(self.tokens)

    def index_of(self, token: str) -> int:
        """Slot number, for logging. Never log the token itself."""
        return self.tokens.index(token) if token in self.tokens else -1

    def available(self) -> list[str]:
        now = time.time()
        with self._lock:
            return [t for t in self.tokens if self._cooldown.get(t, 0.0) < now]

    def soonest_reset(self) -> float | None:
        now = time.time()
        with self._lock:
            pending = [u for u in self._cooldown.values() if u > now]
        return min(pending) if pending else None

    def pick(self, sticky_key: str | None = None) -> str:
        """The token this call should use.

        The sticky key's slot when it is available; any other available slot
        when it is not (a cooled favourite must not stall an entire run);
        `PoolExhausted` when none is.
        """
        if not self.tokens:
            raise PoolExhausted(0, None)
        available = self.available()

        if sticky_key and len(self.tokens) > 1:
            idx = int(hashlib.sha256(sticky_key.encode()).hexdigest(), 16) % len(self.tokens)
            preferred = self.tokens[idx]
            if preferred in available:
                return preferred
            logger.warning(
                "%s: sticky slot %d is cooling — failing over, prompt cache will be cold", self.name, idx,
            )

        if available:
            if not sticky_key:
                preferred = self.tokens[self._default_slot % len(self.tokens)]
                if preferred in available:
                    return preferred
            return random.choice(available)  # noqa: S311 - load spreading, not cryptography
        raise PoolExhausted(len(self.tokens), self.soonest_reset())

    def cool(self, token: str, *, until: float | None = None, reason: str = "rate limit") -> float:
        """Take a token out of rotation until `until` (default: a fixed wait)."""
        deadline = (until + RESET_PAD_S) if until else (time.time() + DEFAULT_COOLDOWN_S)
        deadline = max(deadline, time.time() + MIN_COOLDOWN_S)
        with self._lock:
            self._cooldown[token] = deadline
        logger.warning(
            "%s: slot %d cooled (%s) until %s — %d of %d still available",
            self.name, self.index_of(token), reason, _fmt(deadline),
            len(self.available()), len(self.tokens),
        )
        return deadline

    def clear_cooldowns(self) -> None:
        with self._lock:
            self._cooldown.clear()
