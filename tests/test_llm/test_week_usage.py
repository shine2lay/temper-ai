"""An account near its week line is moved away from before it refuses (temper queue #66).

Picks are sticky: an agent's account comes from a hash of the run and the agent, and a resumed
run keeps its run id, so it puts every agent back on the same accounts. On 2026-10-06 one of them
was at 95% of its week, and a run had to be forked by hand instead of resumed. The pickers now
skip an account at or above the week line while another has room, and otherwise pick exactly as
before. Every rate-limit event here is made up for the test.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time

import pytest

from temper_ai.llm import week_usage
from temper_ai.llm.token_pool import PoolExhausted, TokenPool
from temper_ai.llm.week_usage import WeekUsage, figures_in_event

TOKENS = ["tok-first", "tok-second", "tok-third"]
LABELS = ["shinelay", "aungshine", "wai2shine"]
DAY = 24 * 3600


def a_pool() -> TokenPool:
    return TokenPool(name="anthropic-oauth", tokens=list(TOKENS), labels=list(LABELS))


def todays_slot(key: str) -> str:
    """The pick as it was before the week line: the sticky key's hashed slot."""
    return TOKENS[int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(TOKENS)]


def keys_on(token: str, count: int = 20) -> list[str]:
    """Sticky keys (run id and agent) whose slot is this token."""
    found = [f"run-{i}-agent" for i in range(2000) if todays_slot(f"run-{i}-agent") == token]
    return found[:count]


def at(label: str, used: float, *, resets_in: float | None = 2 * DAY, kind: str = "seven_day",
       seen_ago: float = 0.0) -> None:
    now = time.time()
    week_usage.store().note(label, kind, used, None if resets_in is None else now + resets_in,
                            seen_at=now - seen_ago)


def an_event(seven_day: float | None = None, *, kind: str = "five_hour", used: float | None = None,
             resets: float | None = None) -> dict:
    """A made-up claude CLI rate-limit event."""
    soon = int(time.time()) + 3 * DAY
    windows: dict = {"five_hour": {"utilization": 0.3, "resetsAt": int(time.time()) + 3600}}
    if seven_day is not None:
        windows["seven_day"] = {"utilization": seven_day, "resetsAt": resets or soon}
    info: dict = {"status": "allowed", "rateLimitType": kind, "resetsAt": resets or soon,
                  "isUsingOverage": False, "unifiedWindows": windows}
    if used is not None:
        info.update(status="allowed_warning", utilization=used, surpassedThreshold=0.75)
    return {"type": "rate_limit_event", "rate_limit_info": info, "session_id": "s-1"}


class FakeHashRedis:
    """The hash calls the week figures make, kept in memory: one Redis for several processes."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.reads = 0

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    def hgetall(self, key):
        self.reads += 1
        return dict(self.hashes.get(key, {}))

    def expire(self, key, seconds):
        pass

    def delete(self, key):
        self.hashes.pop(key, None)


class DeadRedis:
    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise ConnectionError("Redis is not answering")
        return fail


def a_process(redis, clock=time.time) -> WeekUsage:
    return WeekUsage("redis://fake", connect=lambda url: redis, clock=clock)


# -- reading the event ------------------------------------------------------------------------

def test_the_event_gives_its_weekly_figure_and_nothing_else():
    reset = int(time.time()) + 3 * DAY
    assert figures_in_event(an_event(0.42, resets=reset)) == [("seven_day", 0.42, float(reset))]
    assert figures_in_event(an_event()) == []  # only the five-hour window: nothing weekly


def test_a_single_model_week_is_kept_too_and_the_highest_decides():
    figures = dict((kind, used) for kind, used, _ in
                   figures_in_event(an_event(0.6, kind="seven_day_opus", used=0.97)))
    assert figures == {"seven_day": 0.6, "seven_day_opus": 0.97}
    week_usage.note_event("shinelay", an_event(0.6, kind="seven_day_opus", used=0.97))
    top = week_usage.highest("shinelay")
    assert (top.kind, top.used) == ("seven_day_opus", 0.97)


def test_percentages_and_milliseconds_are_read_as_shares_and_seconds():
    reset = time.time() + DAY
    event = an_event(95, resets=int(reset * 1000))
    [(kind, used, resets)] = figures_in_event(event)
    assert (kind, used) == ("seven_day", 0.95)
    assert abs(resets - reset) < 1


def test_other_lines_and_broken_figures_give_nothing():
    assert figures_in_event({"type": "assistant", "message": {}}) == []
    assert figures_in_event({"type": "rate_limit_event"}) == []
    broken = an_event(0.5)
    broken["rate_limit_info"]["unifiedWindows"]["seven_day"]["utilization"] = "lots"
    assert figures_in_event(broken) == []
    assert week_usage.note_event(None, an_event(0.99)) == []  # no account to keep it under


# -- the pick -------------------------------------------------------------------------------------

def test_with_no_account_over_the_line_every_agent_keeps_todays_slot():
    pool = a_pool()
    at("shinelay", 0.5)
    at("aungshine", 0.89)
    keys = [f"run-{i}-agent-{i % 7}" for i in range(300)]
    assert all(pool.pick(k) == todays_slot(k) for k in keys)


def test_an_account_over_the_line_moves_its_agents_and_only_them():
    pool = a_pool()
    at("shinelay", 0.95)
    for key in keys_on("tok-first"):
        assert pool.pick(key) in ("tok-second", "tok-third")
    for key in keys_on("tok-second") + keys_on("tok-third"):
        assert pool.pick(key) == todays_slot(key)


def test_a_resumed_run_moves_off_the_account_and_stays_on_one():
    pool = a_pool()
    run_id = "4f0c2a9e-resumed"
    agent = next(a for a in (f"agent_{i}" for i in range(500))
                 if todays_slot(f"{run_id}-{a}") == "tok-first")
    key = f"{run_id}-{agent}"
    assert pool.pick(key) == "tok-first"  # the first time round
    at("shinelay", 0.95)
    moved = pool.pick(key)  # the resume: same run id, same agent
    assert moved != "tok-first"
    assert {pool.pick(key) for _ in range(100)} == {moved}


def test_every_account_over_the_line_picks_as_before():
    pool = a_pool()
    for label in LABELS:
        at(label, 0.95)
    keys = [f"run-{i}-agent" for i in range(100)]
    assert all(pool.pick(k) == todays_slot(k) for k in keys)


@pytest.mark.parametrize("figure", [
    {"used": 0.95, "resets_in": -60},                    # its week already reset
    {"used": 0.95, "resets_in": None, "seen_ago": 3 * 3600},  # no reset named, seen 3 h ago
    {"used": 0.85},                                       # under the line
    {"used": 0.97, "kind": "five_hour"},                  # not a weekly kind
])
def test_unknown_old_or_under_figures_pick_as_before(figure):
    pool = a_pool()
    at("shinelay", **figure)
    assert all(pool.pick(k) == "tok-first" for k in keys_on("tok-first"))


def test_a_figure_without_a_reset_holds_for_two_hours():
    pool = a_pool()
    at("shinelay", 0.95, resets_in=None, seen_ago=3600)
    assert all(pool.pick(k) != "tok-first" for k in keys_on("tok-first"))


def test_failover_is_stable_per_agent_and_spread_between_agents():
    pool = a_pool()
    pool.cool("tok-first", until=time.time() + 3600, model="claude-opus-5-5")
    keys = keys_on("tok-first", 60)
    for key in keys[:5]:
        assert len({pool.pick(key, model="claude-opus-5-5") for _ in range(100)}) == 1
    went = {pool.pick(k, model="claude-opus-5-5") for k in keys}
    assert went == {"tok-second", "tok-third"}  # spread, not all onto one account

    at("shinelay", 0.95)  # the same holds when the line, not a cooling, moves them
    pool.clear_cooldowns()
    for key in keys[:5]:
        assert len({pool.pick(key) for _ in range(100)}) == 1


def test_cooled_and_dropped_accounts_stay_out():
    pool = a_pool()
    at("shinelay", 0.95)
    pool.cool("tok-second", until=time.time() + 3600)
    assert all(pool.pick(k) == "tok-third" for k in keys_on("tok-first"))
    # The only account left is over the line: it is still used, as before.
    pool.cool("tok-third", until=time.time() + 3600)
    assert all(pool.pick(k) == "tok-first" for k in keys_on("tok-first"))
    pool.cool("tok-first", until=time.time() + 3600)
    with pytest.raises(PoolExhausted):
        pool.pick("run-1-agent")


def test_an_account_over_the_line_is_not_where_others_fail_over_to():
    pool = a_pool()
    pool.cool("tok-first", until=time.time() + 3600)
    at("aungshine", 0.95)
    assert all(pool.pick(k) == "tok-third" for k in keys_on("tok-first"))


def test_a_pick_without_a_sticky_key_keeps_off_an_account_over_the_line():
    pool = a_pool()
    at(LABELS[pool._default_slot % len(TOKENS)], 0.95)
    first = TOKENS[pool._default_slot % len(TOKENS)]
    picks = {pool.pick() for _ in range(50)}
    assert len(picks) == 1 and first not in picks


def test_a_moved_pick_logs_one_warning_with_the_account_and_its_figure(caplog):
    pool = a_pool()
    at("shinelay", 0.95)
    key = keys_on("tok-first")[0]
    with caplog.at_level(logging.WARNING, logger="temper_ai.llm.week_usage"):
        pool.pick(key)
    lines = [r.getMessage() for r in caplog.records if "week line" in r.getMessage()]
    assert len(lines) == 1
    assert "shinelay at 95% of seven_day" in lines[0]
    assert not any(t in lines[0] for t in TOKENS)


def test_no_warning_when_the_line_moves_nothing(caplog):
    pool = a_pool()
    at("aungshine", 0.95)
    with caplog.at_level(logging.WARNING, logger="temper_ai.llm.week_usage"):
        for key in keys_on("tok-first") + keys_on("tok-third"):
            pool.pick(key)
        for label in LABELS:
            at(label, 0.99)  # every account over: nothing to move to
        for key in keys_on("tok-second"):
            pool.pick(key)
    assert not [r for r in caplog.records if "week line" in r.getMessage()]


# -- shared between processes ---------------------------------------------------------------------

def test_a_figure_one_process_saw_steers_another_through_redis():
    redis = FakeHashRedis()
    box = a_process(redis)
    week_usage.use(box)
    week_usage.note_event("shinelay", an_event(0.96))
    assert not any("tok" in field for field in redis.hashes[week_usage.KEY])

    week_usage.use(a_process(redis))  # another process: the server, or the next run's box
    assert week_usage.over_line("shinelay").used == 0.96
    pool = a_pool()
    assert all(pool.pick(k) != "tok-first" for k in keys_on("tok-first"))


def test_redis_is_read_at_most_every_few_seconds():
    redis, now = FakeHashRedis(), [1000.0]
    process = a_process(redis, clock=lambda: now[0])
    for _ in range(50):
        process.figures()
    assert redis.reads == 1
    a_process(redis).note("aungshine", "seven_day", 0.93, resets_at=time.time() + DAY)
    assert not [f for f in process.figures() if f.label == "aungshine"]  # not looked yet
    now[0] += week_usage.PULL_EVERY_S
    assert [f.used for f in process.figures() if f.label == "aungshine"] == [0.93]


def test_a_redis_that_does_not_answer_leaves_each_process_its_own():
    process = a_process(DeadRedis())
    week_usage.use(process)
    week_usage.note_event("shinelay", an_event(0.95))
    assert week_usage.over_line("shinelay").used == 0.95


# -- the line -------------------------------------------------------------------------------------

def test_the_line_is_read_from_yaml_and_a_local_copy_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(week_usage, "LINE_RECHECK_S", 0.0)
    assert week_usage.week_line(tmp_path) == week_usage.DEFAULT_LINE == 0.90
    (tmp_path / "pools").mkdir()
    tracked = tmp_path / "pools" / "pools.yaml"
    tracked.write_text("pools:\n  week_line: 0.8\n")
    assert week_usage.week_line(tmp_path) == 0.8
    tracked.write_text("pools:\n  week_line: 0.75\n")
    os.utime(tracked, (time.time() + 5, time.time() + 5))
    assert week_usage.week_line(tmp_path) == 0.75  # a change is read without a restart
    (tmp_path / "pools" / "local").mkdir()
    (tmp_path / "pools" / "local" / "pools.yaml").write_text("pools:\n  week_line: 0.7\n")
    assert week_usage.week_line(tmp_path) == 0.7


@pytest.mark.parametrize("value", ["lots", 0, -0.5, 250, "[1, 2]"])
def test_a_line_that_is_not_a_share_of_a_week_falls_back_to_the_default(tmp_path, value):
    (tmp_path / "pools").mkdir()
    (tmp_path / "pools" / "pools.yaml").write_text(f"pools:\n  week_line: {value}\n")
    assert week_usage.week_line(tmp_path) == week_usage.DEFAULT_LINE


def test_the_tracked_line_is_ninety_percent():
    assert week_usage.week_line() == 0.90
