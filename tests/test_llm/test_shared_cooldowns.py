"""A rate limit one temper process finds is seen by every other.

Each run starts in a box of its own, so a limit one run found must not be
found again by the next: that costs a refused call per account per run, and
a failover after the prompt cache has already gone cold. These tests stand
two processes (two SharedCooldowns, as two boxes would have) on one fake
Redis, and check that the list fails open when Redis is not there.
"""

from __future__ import annotations

import time

import pytest

from temper_ai.llm import shared_cooldowns
from temper_ai.llm.shared_cooldowns import (
    KEY_PREFIX,
    PULL_EVERY_S,
    RETRY_AFTER_S,
    SharedCooldowns,
    fingerprint,
)
from temper_ai.llm.token_pool import PoolExhausted, TokenPool

TOKENS = ["sk-ant-oat-first", "sk-ant-oat-second"]


class FakeRedis:
    """The sorted-set calls the shared list makes, kept in memory."""

    def __init__(self) -> None:
        self.sets: dict[str, dict[str, float]] = {}
        self.reads = 0

    def zadd(self, key, mapping, gt=False):
        members = self.sets.setdefault(key, {})
        for member, score in mapping.items():
            if not gt or member not in members or score > members[member]:
                members[member] = score

    def zremrangebyscore(self, key, low, high):
        members = self.sets.get(key, {})
        for member in [m for m, s in members.items() if float(low) <= s <= float(high)]:
            del members[member]

    def expire(self, key, seconds):
        pass

    def zrangebyscore(self, key, low, high, withscores=False):
        self.reads += 1
        rows = sorted(
            ((m, s) for m, s in self.sets.get(key, {}).items() if float(low) <= s <= float(high)),
            key=lambda row: row[1],
        )
        return rows if withscores else [m for m, _ in rows]

    def delete(self, key):
        self.sets.pop(key, None)


class DeadRedis:
    """A Redis that never answers."""

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise ConnectionError("Redis is not answering")
        return fail


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


def _process(redis, **kwargs) -> SharedCooldowns:
    """One temper process's view of the shared list (a run's box, the server)."""
    return SharedCooldowns("redis://fake", connect=lambda _url: redis, **kwargs)


def _new_box(redis) -> TokenPool:
    """A process that has learned nothing yet, with the pool the provider makes."""
    shared_cooldowns.use(_process(redis))
    return TokenPool(name="anthropic-oauth", tokens=list(TOKENS))


class TestBetweenProcesses:
    def test_a_limit_one_run_found_is_skipped_by_the_next(self, redis):
        first_run = _new_box(redis)
        limited = first_run.pick("run-1-planner")
        first_run.cool(limited, reason="rate limit")

        next_run = _new_box(redis)
        assert next_run.cooling_until(limited) is not None
        other = next(t for t in TOKENS if t != limited)
        assert {next_run.pick(f"run-2-agent-{i}") for i in range(20)} == {other}

    def test_a_limit_on_one_model_family_stays_on_that_family(self, redis):
        first_run = _new_box(redis)
        first_run.cool(TOKENS[0], model="claude-opus-4-1", reason="weekly opus limit")

        next_run = _new_box(redis)
        assert next_run.cooling_until(TOKENS[0], model="claude-opus-4-1") is not None
        assert next_run.cooling_until(TOKENS[0], model="claude-sonnet-4-5") is None

    def test_every_account_limited_elsewhere_exhausts_the_pool_here(self, redis):
        first_run = _new_box(redis)
        for token in TOKENS:
            first_run.cool(token, until=time.time() + 3600)

        with pytest.raises(PoolExhausted) as exhausted:
            _new_box(redis).pick("run-2-planner")
        assert exhausted.value.reset_at is not None

    def test_the_pools_page_shows_limits_other_processes_found(self, redis):
        _new_box(redis).cool(TOKENS[1])
        state = _new_box(redis).state()
        assert all(family["available"] == 1 for family in state.values())

    def test_clearing_a_pool_clears_it_for_every_process(self, redis):
        first_run = _new_box(redis)
        first_run.cool(TOKENS[0])
        first_run.clear_cooldowns()
        assert _new_box(redis).cooling_until(TOKENS[0]) is None

    def test_a_run_that_parks_for_the_allowance_leaves_the_shared_list_alone(self, redis):
        """Waiting out a limit is not the same as forgetting it.

        A parked run does nothing to the shared list: the limits it waits for
        stay on it, at the times they were found, so every other process still
        skips those accounts while it sleeps. Clearing them early would send
        every run in every box straight back into the same refusal.
        """
        import threading

        from temper_ai.llm import allowance

        pool = _new_box(redis)
        for token in TOKENS:
            pool.cool(token, until=time.time() + 3600)
        before = {key: round(until) for key, until in shared_cooldowns.pull("anthropic-oauth").items()}
        assert before                      # the limits are on the list to begin with

        allowance.sleep_until(time.time() - 1)                 # a park, start to finish
        allowance.sleep_until(time.time() - 1, stop=threading.Event())

        after = {key: round(until) for key, until in shared_cooldowns.pull("anthropic-oauth").items()}
        assert after == before
        assert _new_box(redis).cooling_until(TOKENS[0]) is not None

    def test_a_later_reset_is_never_shortened_by_an_earlier_one(self, redis):
        store = _process(redis)
        store.push("pool", "*", TOKENS[0], until=time.time() + 7200)
        store.push("pool", "*", TOKENS[0], until=time.time() + 60)
        (until,) = _process(redis).pull("pool").values()
        assert until > time.time() + 7000

    def test_a_longer_limit_known_here_stays(self, redis):
        box = _new_box(redis)
        box._cooldown[("*", TOKENS[0])] = time.time() + 7200  # known here only
        _process(redis).push("anthropic-oauth", "*", TOKENS[0], until=time.time() + 60)
        assert box.cooling_until(TOKENS[0]) > time.time() + 7000


class TestWhatGoesToRedis:
    def test_only_a_fingerprint_of_the_token_never_the_token(self, redis):
        _new_box(redis).cool(TOKENS[0])
        stored = redis.sets[KEY_PREFIX + "anthropic-oauth"]
        assert list(stored) == [f"*|{fingerprint(TOKENS[0])}"]
        assert TOKENS[0] not in repr(redis.sets)

    def test_ended_limits_are_not_read_back(self, redis):
        store = _process(redis)
        store.push("pool", "*", TOKENS[0], until=time.time() - 1)
        assert _process(redis).pull("pool") == {}

    def test_redis_is_asked_at_most_once_a_second_per_pool(self, redis):
        now = [1000.0]
        store = _process(redis, clock=lambda: now[0])
        store.pull("pool")
        store.pull("pool")
        assert redis.reads == 1
        now[0] += PULL_EVERY_S
        store.pull("pool")
        assert redis.reads == 2


class TestFailsOpen:
    def test_without_redis_each_process_keeps_its_own(self):
        shared_cooldowns.use(SharedCooldowns(None))
        first = TokenPool(name="anthropic-oauth", tokens=list(TOKENS))
        first.cool(TOKENS[0])
        assert first.cooling_until(TOKENS[0]) is not None

        shared_cooldowns.use(SharedCooldowns(None))
        assert TokenPool(name="anthropic-oauth", tokens=list(TOKENS)).cooling_until(TOKENS[0]) is None

    def test_a_redis_that_does_not_answer_never_breaks_a_call(self):
        shared_cooldowns.use(_process(DeadRedis()))
        pool = TokenPool(name="anthropic-oauth", tokens=list(TOKENS))
        pool.cool(TOKENS[0])
        assert pool.pick("run-1-planner") == TOKENS[1]
        pool.clear_cooldowns()

    def test_a_redis_that_went_away_is_left_alone_for_a_while(self):
        now = [1000.0]
        connects = []

        def connect(url):
            connects.append(url)
            raise ConnectionError("refused")

        store = SharedCooldowns("redis://fake", connect=connect, clock=lambda: now[0])
        store.push("pool", "*", TOKENS[0], until=2000.0)
        assert store.pull("pool") == {}
        assert len(connects) == 1
        now[0] += RETRY_AFTER_S
        store.pull("pool")
        assert len(connects) == 2
