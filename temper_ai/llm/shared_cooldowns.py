"""Rate-limit coolings shared by every temper process that uses the same accounts.

A limited account should be found once. Runs each start in a box of their
own now, and a box that learned every limit again by itself would spend a
refused call per account (and per model family) per run -- and fail over
late, after the prompt cache had already gone cold. So a cooling one
process finds is written here, and every process reads the others' before
it picks a token.

Kept in Redis ($TEMPER_REDIS_URL, else $REDIS_URL), which the server, the
worker and every run box can reach. One sorted set per pool: the member is
``"<model family>|<token fingerprint>"`` and the score is when the cooling
ends. Never a token itself, only a short hash of it.

Everything here fails open. Without Redis, or while it does not answer,
each process keeps its own coolings as it always has; a Redis that went
away is tried again after a pause, not on every call.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

KEY_PREFIX = "temper:cooldowns:"
# How often a process looks at the others' coolings. A call made in the
# second after another process found a limit may still go to that account
# once; that costs one refused call, which is what the pool handles anyway.
PULL_EVERY_S = 1.0
# After Redis failed to answer, how long to go without it before trying again.
RETRY_AFTER_S = 30.0
# Redis drops a pool's set when nothing has cooled in it for this long: the
# longest cooling there is (a weekly limit) plus a day.
KEEP_S = 8 * 24 * 3600
# A Redis that is slow to answer must not stall a provider call.
SOCKET_TIMEOUT_S = 0.5


def fingerprint(token: str) -> str:
    """What stands for a token in Redis. Enough to tell a pool's tokens apart."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def redis_url() -> str | None:
    return os.environ.get("TEMPER_REDIS_URL") or os.environ.get("REDIS_URL") or None


def _connect(url: str) -> Any:
    import redis

    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_timeout=SOCKET_TIMEOUT_S,
        socket_connect_timeout=SOCKET_TIMEOUT_S,
    )


class SharedCooldowns:
    """The shared list for one Redis. Thread-safe; every method fails open."""

    def __init__(
        self,
        url: str | None,
        *,
        connect: Callable[[str], Any] = _connect,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._url = url
        self._connect = connect
        self._clock = clock
        self._client: Any = None
        self._down_until = 0.0
        self._lock = threading.Lock()
        #: pool -> (when read, {(family, fingerprint): until})
        self._seen: dict[str, tuple[float, dict[tuple[str, str], float]]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def push(self, pool: str, family: str, token: str, until: float) -> None:
        """Tell every process that this token is out for this family until `until`."""
        member, key = f"{family}|{fingerprint(token)}", KEY_PREFIX + pool
        with self._lock:
            seen = self._seen.get(pool)
            if seen is not None and until > seen[1].get((family, fingerprint(token)), 0.0):
                seen[1][(family, fingerprint(token))] = until
        client = self._usable_client()
        if client is None:
            return
        try:
            # GT: a later reset never gets shortened by an earlier one.
            client.zadd(key, {member: until}, gt=True)
            client.zremrangebyscore(key, "-inf", self._clock())
            client.expire(key, KEEP_S)
        except Exception as exc:  # noqa: BLE001 - fail open
            self._went_down(exc)

    def pull(self, pool: str) -> dict[tuple[str, str], float]:
        """Coolings still on for this pool: {(family, fingerprint): until}.

        Read from Redis at most every PULL_EVERY_S per pool; in between, the
        last answer. Empty when there is no Redis to ask.
        """
        now = self._clock()
        with self._lock:
            seen = self._seen.get(pool)
            if seen is not None and now - seen[0] < PULL_EVERY_S:
                return {k: u for k, u in seen[1].items() if u > now}
        client = self._usable_client()
        if client is None:
            return {} if seen is None else {k: u for k, u in seen[1].items() if u > now}
        try:
            rows = client.zrangebyscore(KEY_PREFIX + pool, now, "+inf", withscores=True)
        except Exception as exc:  # noqa: BLE001 - fail open
            self._went_down(exc)
            return {} if seen is None else {k: u for k, u in seen[1].items() if u > now}
        found: dict[tuple[str, str], float] = {}
        for member, score in rows:
            family, _, fp = str(member).rpartition("|")
            if family and fp:
                found[(family, fp)] = float(score)
        with self._lock:
            self._seen[pool] = (now, found)
        return dict(found)

    def clear(self, pool: str) -> None:
        with self._lock:
            self._seen.pop(pool, None)
        client = self._usable_client()
        if client is None:
            return
        try:
            client.delete(KEY_PREFIX + pool)
        except Exception as exc:  # noqa: BLE001 - fail open
            self._went_down(exc)

    def _usable_client(self) -> Any:
        if not self._url or self._clock() < self._down_until:
            return None
        if self._client is None:
            try:
                self._client = self._connect(self._url)
            except Exception as exc:  # noqa: BLE001 - fail open
                self._went_down(exc)
                return None
        return self._client

    def _went_down(self, exc: Exception) -> None:
        if self._clock() >= self._down_until:
            logger.warning(
                "Shared rate limits: Redis did not answer (%s); this process keeps its own "
                "for %ds", exc, int(RETRY_AFTER_S),
            )
        self._down_until = self._clock() + RETRY_AFTER_S


_store: SharedCooldowns | None = None
_store_lock = threading.Lock()


def store() -> SharedCooldowns:
    """This process's shared list, set up from the environment on first use."""
    global _store
    with _store_lock:
        if _store is None:
            _store = SharedCooldowns(redis_url())
        return _store


def use(new_store: SharedCooldowns | None) -> None:
    """Swap the process's list (tests); None sets it up from the environment again."""
    global _store
    with _store_lock:
        _store = new_store


def push(pool: str, family: str, token: str, until: float) -> None:
    store().push(pool, family, token, until)


def pull(pool: str) -> dict[tuple[str, str], float]:
    return store().pull(pool)


def clear(pool: str) -> None:
    store().clear(pool)


def for_tokens(pool: str, tokens: list[str]) -> dict[tuple[str, str], float]:
    """The coolings still on for these tokens, from every process: {(family, token): until}.

    The caller folds them into its own, keeping whichever ends later.
    """
    shared = pull(pool)
    if not shared:
        return {}
    by_fingerprint = {fingerprint(t): t for t in tokens}
    return {
        (family, by_fingerprint[fp]): until
        for (family, fp), until in shared.items()
        if fp in by_fingerprint
    }
