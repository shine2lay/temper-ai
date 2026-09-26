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

A cooling is per *model family*, because the subscription's weekly ceiling
is. Cooling the credential outright is what it used to do, and it cost four
days: the build loops spent the fable allowance, every slot was marked cooled
until the weekly reset, and opus -- with its own untouched allowance on the
same accounts -- was then refused without a request being made. The reverse
mistake is cheap by comparison: a limit that really is account-wide (the
shared five-hour window) costs one rejected request per family before that
family is cooled too.

A token can also be asked for by name, which takes it out of the rotation for
that call: an agent or a fallback entry that says `token: wai2shine` goes out
on that account and no other (see temper_ai.llm.fallback). The name is the
account's, set beside the token in the environment --

    CLAUDE_CODE_OAUTH_TOKEN_2=sk-ant-oat01-...
    CLAUDE_CODE_OAUTH_TOKEN_2_ACCOUNT=wai2shine

-- or the variable's own name when no account is given. The account name also
stands in for "slot 2" in what the pool logs.

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

# Model names that carry their own subscription ceiling. Matched as substrings so
# a dated or point-released id (claude-opus-4-5-20250101, claude-fable-5-1) lands
# in the same bucket as the bare name.
KNOWN_FAMILIES = ("opus", "sonnet", "haiku", "fable")
# The bucket for a cooling that names no model: it blocks the credential for every
# family. Used when the caller cannot say which model was refused, where guessing
# wrong would hand back a credential that is certain to fail.
ANY_MODEL = "*"


def model_family(model: str | None) -> str:
    """The ceiling a model draws on. Unknown ids get a bucket of their own."""
    if not model:
        return ANY_MODEL
    lowered = model.lower()
    return next((f for f in KNOWN_FAMILIES if f in lowered), lowered)


# Beside a token's variable, the account it belongs to: CLAUDE_CODE_OAUTH_TOKEN_2
# is named by CLAUDE_CODE_OAUTH_TOKEN_2_ACCOUNT. Not a secret.
ACCOUNT_SUFFIX = "_ACCOUNT"


@dataclass(frozen=True)
class NamedToken:
    """One configured token: the variable it came from and the account it is."""

    variable: str
    token: str
    account: str | None = None

    @property
    def label(self) -> str:
        """What logs and events call it. Never the token."""
        return self.account or self.variable


def named_tokens_from_env(base: str, extra_suffixes: tuple[str, ...] = ("BACKUP",),
                          limit: int = 10) -> list[NamedToken]:
    """Every token configured under `base`: BASE, BASE_BACKUP, BASE_2..BASE_9.

    Order is stable and duplicates are dropped (the first variable holding a
    token keeps it), so the same env produces the same slot for the same
    sticky key on every process start.
    """
    names = [base, *[f"{base}_{s}" for s in extra_suffixes], *[f"{base}_{i}" for i in range(2, limit)]]
    found: dict[str, NamedToken] = {}
    for name in names:
        token = (os.environ.get(name) or "").strip()
        if token and token not in found:
            account = (os.environ.get(name + ACCOUNT_SUFFIX) or "").strip() or None
            found[token] = NamedToken(variable=name, token=token, account=account)
    return list(found.values())


def tokens_from_env(base: str, extra_suffixes: tuple[str, ...] = ("BACKUP",), limit: int = 10) -> list[str]:
    """The tokens of `named_tokens_from_env`, without their names."""
    return [n.token for n in named_tokens_from_env(base, extra_suffixes, limit)]


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


class TokenCooling(PoolExhausted):
    """The one token a call was pinned to is out for this model.

    A PoolExhausted because it means the same thing to the caller -- no
    capacity here, go elsewhere -- only the pool it speaks for is one token.
    """

    def __init__(self, label: str, model: str | None, reset_at: float | None, detail: str = ""):
        RuntimeError.__init__(
            self,
            f"token {label} is rate limited for {model_family(model)}"
            f" until {_fmt(reset_at) if reset_at else 'unknown'}" + (f": {detail}" if detail else ""),
        )
        self.reset_at = reset_at
        self.label = label


def _fmt(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%d %H:%MZ")


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="seconds")


@dataclass
class TokenPool:
    """Interchangeable credentials for one provider, with sticky assignment."""

    name: str
    tokens: list[str]
    #: What each token is called in logs, by position (its account name). Slots
    #: without one are called "slot N".
    labels: list[str] = field(default_factory=list)
    #: (model family, token) -> when that pairing may be used again. Keyed by family
    #: because the weekly ceiling is; see the module docstring.
    _cooldown: dict[tuple[str, str], float] = field(default_factory=dict)
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

    def label_of(self, token: str) -> str:
        """The token's account name, or its slot number. Never the token itself."""
        idx = self.index_of(token)
        if 0 <= idx < len(self.labels) and self.labels[idx]:
            return self.labels[idx]
        return f"slot {idx}"

    def cooling_until(self, token: str, model: str | None = None) -> float | None:
        """When this token is usable for this model again; None when it is now."""
        with self._lock:
            until = self._blocked_until(token, model_family(model))
        return until if until > time.time() else None

    def _blocked_until(self, token: str, family: str) -> float:
        """When this token is usable for this family again. Caller holds the lock.

        Asking about no particular model asks about all of them: the answer covers every
        ceiling the token is known to be against, so a limited credential never reads as
        healthy just because the caller did not say what it wanted it for. Asking about one
        family consults that family and any cooling that named no model, which stands for
        the whole account.
        """
        if family == ANY_MODEL:
            return max((u for (_, t), u in self._cooldown.items() if t == token), default=0.0)
        return max(self._cooldown.get((family, token), 0.0),
                   self._cooldown.get((ANY_MODEL, token), 0.0))

    def available(self, model: str | None = None) -> list[str]:
        """Tokens usable for this model. Without one, tokens usable for anything."""
        family, now = model_family(model), time.time()
        with self._lock:
            return [t for t in self.tokens if self._blocked_until(t, family) < now]

    def soonest_reset(self, model: str | None = None) -> float | None:
        family, now = model_family(model), time.time()
        with self._lock:
            pending = [u for t in self.tokens if (u := self._blocked_until(t, family)) > now]
        return min(pending) if pending else None

    def pick(self, sticky_key: str | None = None, model: str | None = None) -> str:
        """The token this call should use.

        The sticky key's slot when it is available; any other available slot
        when it is not (a cooled favourite must not stall an entire run);
        `PoolExhausted` when none is. Availability is per model: a slot spent
        on one model family is still the right slot for another.
        """
        if not self.tokens:
            raise PoolExhausted(0, None)
        available = self.available(model)

        if sticky_key and len(self.tokens) > 1:
            idx = int(hashlib.sha256(sticky_key.encode()).hexdigest(), 16) % len(self.tokens)
            preferred = self.tokens[idx]
            if preferred in available:
                return preferred
            logger.warning(
                "%s: sticky %s is cooling — failing over, prompt cache will be cold",
                self.name, self.label_of(preferred),
            )

        if available:
            if not sticky_key:
                preferred = self.tokens[self._default_slot % len(self.tokens)]
                if preferred in available:
                    return preferred
            return random.choice(available)  # noqa: S311 - load spreading, not cryptography
        raise PoolExhausted(len(self.tokens), self.soonest_reset(model))

    def cool(self, token: str, *, until: float | None = None, reason: str = "rate limit",
             model: str | None = None) -> float:
        """Take a token out of rotation for `model`'s family until `until`.

        Without a model the cooling covers every family, which is the safe reading
        of a refusal we cannot attribute -- but it is the expensive one, so callers
        that know which model was refused should say.
        """
        family = model_family(model)
        deadline = (until + RESET_PAD_S) if until else (time.time() + DEFAULT_COOLDOWN_S)
        deadline = max(deadline, time.time() + MIN_COOLDOWN_S)
        with self._lock:
            self._cooldown[(family, token)] = deadline
        logger.warning(
            "%s: %s cooled for %s (%s) until %s — %d of %d still available for %s",
            self.name, self.label_of(token), family, reason, _fmt(deadline),
            len(self.available(model)), len(self.tokens), family,
        )
        return deadline

    def state(self) -> dict[str, dict]:
        """What the pool can serve now, per model family (GET /api/pools). Labels and times, never a token.

        Every known family is listed, and any other one something cooled. Per family: the slots,
        each with ``cooling_until`` (ISO UTC; None when it can be used now), how many are
        ``available``, and ``soonest_reset``, the earliest cooling to end (None when none is on).
        A caller about to start long work asks this first: with no slot available for its model
        the work stops at its first call (b009 on 2026-09-24, "token pool exhausted").
        """
        now = time.time()
        with self._lock:
            others = sorted({f for f, _ in self._cooldown} - set(KNOWN_FAMILIES) - {ANY_MODEL})
            out: dict[str, dict] = {}
            for family in (*KNOWN_FAMILIES, *others):
                untils = [self._blocked_until(t, family) for t in self.tokens]
                pending = [u for u in untils if u > now]
                out[family] = {
                    "size": len(self.tokens),
                    "available": len(untils) - len(pending),
                    "soonest_reset": _iso(min(pending)) if pending else None,
                    "slots": [{"label": self.label_of(t), "cooling_until": _iso(u) if u > now else None}
                              for t, u in zip(self.tokens, untils, strict=True)],
                }
        return out

    def clear_cooldowns(self) -> None:
        with self._lock:
            self._cooldown.clear()
