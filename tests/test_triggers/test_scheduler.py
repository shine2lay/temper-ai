"""Schedules, run-finished and stuck-run triggers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from temper_ai.triggers import scheduler as sched
from temper_ai.triggers.cron import Cron, CronError, parse_duration
from temper_ai.triggers.rules import TriggerConfigError, parse_trigger

T0 = datetime(2026, 9, 28, 16, 0, tzinfo=UTC)  # Monday 09:00 Pacific (PDT)


def _rule(tmp_path: Path, name: str, body: str) -> Path:
    folder = tmp_path / "triggers"
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.yaml").write_text(body)
    return tmp_path


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Starter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, workflow: str, inputs: dict) -> str:
        self.calls.append((workflow, inputs))
        return f"exec-{len(self.calls):04d}-0000"


@pytest.fixture
def quiet(monkeypatch):
    """No runs anywhere unless a test says so."""
    monkeypatch.setattr(sched, "_still_going", lambda eid: None)
    monkeypatch.setattr(sched, "_runs", lambda status=None: [])
    monkeypatch.setattr(sched, "_run_inputs", lambda eid: {})
    monkeypatch.setattr(sched, "_last_activity", lambda eid: None)


# -- cron -------------------------------------------------------------------


class TestCron:
    def test_weekday_morning(self):
        c = Cron.parse("0 9 * * 1-5")
        assert c.matches(datetime(2026, 9, 28, 9, 0))      # Monday
        assert not c.matches(datetime(2026, 9, 27, 9, 0))  # Sunday
        assert not c.matches(datetime(2026, 9, 28, 9, 1))

    def test_steps_lists_and_sunday_as_7(self):
        c = Cron.parse("*/15 8-10,14 * * 7")
        assert c.matches(datetime(2026, 9, 27, 14, 45))
        assert not c.matches(datetime(2026, 9, 27, 14, 50))
        assert not c.matches(datetime(2026, 9, 27, 11, 0))

    def test_either_day_field_matches_when_both_are_set(self):
        c = Cron.parse("0 0 1 * 1")  # the 1st, or any Monday
        assert c.matches(datetime(2026, 10, 1, 0, 0))   # Thursday the 1st
        assert c.matches(datetime(2026, 9, 28, 0, 0))   # a Monday

    @pytest.mark.parametrize("bad", ["", "* * * *", "60 * * * *", "* 24 * * *", "*/0 * * * *", "a * * * *", "5-1 * * * *"])
    def test_rejects(self, bad):
        with pytest.raises(CronError):
            Cron.parse(bad)

    def test_durations(self):
        assert parse_duration("30m") == 1800
        assert parse_duration("2h") == 7200
        assert parse_duration(90) == 90
        for bad in ("0m", "soon", "5 minutes", -1):
            with pytest.raises(CronError):
                parse_duration(bad)


# -- rule checking ------------------------------------------------------------


class TestPlan:
    def _t(self, source, on):
        return parse_trigger({"trigger": {"name": "r", "source": source, "on": on, "workflow": "w"}})

    def test_schedule_needs_one_of_cron_or_every(self):
        with pytest.raises(TriggerConfigError):
            sched.plan(self._t("schedule", {"timezone": "UTC"}))
        with pytest.raises(TriggerConfigError):
            sched.plan(self._t("schedule", {"cron": "* * * * *", "every": "5m"}))

    def test_bad_zone_and_cron_are_config_errors(self):
        with pytest.raises(TriggerConfigError, match="time zone"):
            sched.plan(self._t("schedule", {"cron": "0 9 * * *", "timezone": "Mars/Base"}))
        with pytest.raises(TriggerConfigError):
            sched.plan(self._t("schedule", {"cron": "0 25 * * *"}))

    def test_run_rule(self):
        p = sched.plan(self._t("run", {"workflow": ["a", "b"], "status": "any", "inputs": {"bet": "b019"}}))
        assert p.workflows == {"a", "b"}
        assert p.statuses == set(sched.END_STATES)
        assert p.inputs == (("bet", "b019"),)
        with pytest.raises(TriggerConfigError, match="status"):
            sched.plan(self._t("run", {"workflow": "a", "status": "done"}))
        with pytest.raises(TriggerConfigError, match="workflow"):
            sched.plan(self._t("run", {"status": "completed"}))

    def test_stuck_needs_after(self):
        with pytest.raises(TriggerConfigError, match="after"):
            sched.plan(self._t("stuck", {"workflow": "a"}))

    def test_a_bad_rule_is_skipped_not_fatal(self, tmp_path):
        _rule(tmp_path, "bad", "trigger: {name: bad, source: schedule, on: {cron: nope}, workflow: w}")
        _rule(tmp_path, "good", "trigger: {name: good, source: schedule, on: {every: 5m}, workflow: w}")
        assert [p.trigger.name for p in sched.load_plans(tmp_path)] == ["good"]

    def test_disabled_and_linear_rules_are_not_the_schedulers(self, tmp_path):
        _rule(tmp_path, "off", "trigger: {name: off, source: schedule, enabled: false, on: {every: 5m}, workflow: w}")
        _rule(tmp_path, "lin", "trigger: {name: lin, source: linear, on: {type: Issue}, workflow: w}")
        assert sched.load_plans(tmp_path) == []


# -- schedules ------------------------------------------------------------------


CRON_RULE = """
trigger:
  name: digest
  source: schedule
  on: {cron: "0 9 * * 1-5", timezone: America/Los_Angeles}
  workflow: digest
  inputs: {day: "{{ due[:10] }}"}
"""


class TestSchedule:
    def test_first_sight_starts_the_clock_and_fires_at_the_due_time(self, tmp_path, quiet):
        root = _rule(tmp_path, "digest", CRON_RULE)
        clock, starter = Clock(T0 - timedelta(minutes=10)), Starter()
        s = sched.Scheduler(root, start_run=starter, clock=clock)
        assert s.tick() == []                      # first sight
        clock.now = T0 - timedelta(minutes=1)
        assert s.tick() == []                      # not yet due
        clock.now = T0 + timedelta(seconds=20)
        [d] = s.tick()
        assert d["outcome"] == "started"
        assert starter.calls == [("digest", {"day": "2026-09-28"})]
        clock.now = T0 + timedelta(seconds=50)
        assert s.tick() == []                      # the same due time never fires twice

    def test_a_new_rule_does_not_fire_for_a_time_before_it_existed(self, tmp_path, quiet):
        root = _rule(tmp_path, "digest", CRON_RULE)
        starter = Starter()
        s = sched.Scheduler(root, start_run=starter, clock=Clock(T0 + timedelta(minutes=1)))
        s.tick()
        s.tick()
        assert starter.calls == []

    def test_missed_while_down_is_skipped_and_recorded(self, tmp_path, quiet):
        root = _rule(tmp_path, "digest", CRON_RULE)
        clock, starter = Clock(T0 - timedelta(hours=1)), Starter()
        s = sched.Scheduler(root, start_run=starter, clock=clock)
        s.tick()
        clock.now = T0 + timedelta(days=1, hours=2)  # down over two 9 AMs
        [d] = s.tick()
        assert starter.calls == []
        assert d["outcome"] == "skipped"
        assert "missed" in d["detail"] and "2026-09-29T09:00:00-07:00" in d["detail"]
        assert "1 earlier" in d["detail"]
        assert sched.history("digest")[0]["outcome"] == "skipped"

    def test_catch_up_runs_the_latest_missed_time_once(self, tmp_path, quiet):
        root = _rule(tmp_path, "digest", CRON_RULE.replace("timezone:", "catch_up: true, timezone:"))
        clock, starter = Clock(T0 - timedelta(hours=1)), Starter()
        s = sched.Scheduler(root, start_run=starter, clock=clock)
        s.tick()
        clock.now = T0 + timedelta(days=1, hours=2)
        s.tick()
        s.tick()
        assert starter.calls == [("digest", {"day": "2026-09-29"})]

    def test_skips_while_the_previous_run_is_still_going(self, tmp_path, quiet, monkeypatch):
        root = _rule(tmp_path, "every", "trigger: {name: every, source: schedule, on: {every: 10m}, workflow: w}")
        clock, starter = Clock(T0), Starter()
        s = sched.Scheduler(root, start_run=starter, clock=clock)
        s.tick()
        clock.now = T0 + timedelta(minutes=10, seconds=5)
        s.tick()
        assert len(starter.calls) == 1
        monkeypatch.setattr(sched, "_still_going", lambda eid: eid)
        clock.now = T0 + timedelta(minutes=20, seconds=5)
        [d] = s.tick()
        assert d["outcome"] == "skipped" and "still going" in d["detail"]
        assert len(starter.calls) == 1

    def test_a_start_that_fails_is_recorded_not_retried(self, tmp_path, quiet):
        root = _rule(tmp_path, "every", "trigger: {name: every, source: schedule, on: {every: 10m}, workflow: nope}")

        def refuse(workflow, inputs):
            raise RuntimeError("workflow config 'nope' not found")

        clock = Clock(T0)
        s = sched.Scheduler(root, start_run=refuse, clock=clock)
        s.tick()
        clock.now = T0 + timedelta(minutes=10, seconds=1)
        [d] = s.tick()
        assert d["outcome"] == "failed" and "not found" in d["detail"]
        assert s.tick() == []

    def test_last_due_across_a_dst_change(self):
        p = sched.plan(parse_trigger({"trigger": {"name": "r", "source": "schedule", "workflow": "w",
                                                   "on": {"cron": "0 9 * * *", "timezone": "America/Los_Angeles"}}}))
        # 2026-11-01: clocks go back; 9 AM Pacific is 17:00 UTC after the change.
        since = datetime(2026, 11, 1, 16, 30, tzinfo=UTC)
        due, count = sched.last_due(p, since, datetime(2026, 11, 1, 17, 0, 30, tzinfo=UTC), since)
        assert due == datetime(2026, 11, 1, 17, 0, tzinfo=UTC) and count == 1

    def test_describe_shows_next_due(self, tmp_path):
        root = _rule(tmp_path, "digest", CRON_RULE)
        [entry] = sched.describe(root, now=T0 + timedelta(minutes=1))
        assert entry["next_due"] == "2026-09-29T09:00:00-07:00"


# -- after a run ------------------------------------------------------------------


RUN_RULE = """
trigger:
  name: b022_after_b019
  source: run
  on: {workflow: epd_loop, status: completed, inputs: {bet: b019}}
  workflow: epd_loop
  inputs: {bet: b022, after: "{{ run.id }}"}
"""


def _run(eid, status="completed", workflow="epd_loop", end=None):
    return {"id": eid, "workflow_name": workflow, "status": status,
            "start_time": (end or T0).isoformat(), "end_time": (end or T0).isoformat()}


class TestAfterRun:
    def test_fires_once_for_the_matching_finished_run(self, tmp_path, quiet, monkeypatch):
        root = _rule(tmp_path, "r", RUN_RULE)
        clock, starter = Clock(T0), Starter()
        s = sched.Scheduler(root, start_run=starter, clock=clock)
        s.tick()  # first sight
        later = T0 + timedelta(minutes=5)
        runs = [_run("run-b019", end=later), _run("run-b020", end=later),
                _run("run-fail", status="failed", end=later), _run("run-other", workflow="x", end=later)]
        inputs = {"run-b019": {"bet": "b019"}, "run-b020": {"bet": "b020"},
                  "run-fail": {"bet": "b019"}, "run-other": {"bet": "b019"}}
        monkeypatch.setattr(sched, "_runs", lambda status=None: runs)
        monkeypatch.setattr(sched, "_run_inputs", lambda eid: inputs[eid])
        clock.now = later + timedelta(seconds=30)
        [d] = s.tick()
        assert d["key"] == "run-b019"
        assert starter.calls == [("epd_loop", {"bet": "b022", "after": "run-b019"})]
        assert s.tick() == []

    def test_ignores_runs_that_ended_before_the_rule_existed(self, tmp_path, quiet, monkeypatch):
        root = _rule(tmp_path, "r", RUN_RULE)
        monkeypatch.setattr(sched, "_runs", lambda status=None: [_run("old", end=T0 - timedelta(hours=1))])
        monkeypatch.setattr(sched, "_run_inputs", lambda eid: {"bet": "b019"})
        starter = Starter()
        sched.Scheduler(root, start_run=starter, clock=Clock(T0)).tick()
        assert starter.calls == []


# -- stuck -------------------------------------------------------------------------


STUCK_RULE = """
trigger:
  name: stuck
  source: stuck
  on: {after: 45m}
  workflow: notify
  inputs: {run_id: "{{ run.id }}", idle: "{{ run.idle_minutes }}"}
"""


class TestStuck:
    def test_alerts_once_for_a_quiet_run(self, tmp_path, quiet, monkeypatch):
        root = _rule(tmp_path, "s", STUCK_RULE)
        monkeypatch.setattr(sched, "_runs", lambda status=None: [
            _run("quiet", status="running"), _run("busy", status="running")] if status == "running" else [])
        activity = {"quiet": T0 - timedelta(minutes=50), "busy": T0 - timedelta(minutes=2)}
        monkeypatch.setattr(sched, "_last_activity", lambda eid: activity[eid])
        starter = Starter()
        s = sched.Scheduler(root, start_run=starter, clock=Clock(T0))
        s.tick()
        s.tick()
        assert starter.calls == [("notify", {"run_id": "quiet", "idle": "50"})]

    def test_gate_parked_runs_are_not_stuck_unless_asked(self, tmp_path, quiet, monkeypatch):
        root = _rule(tmp_path, "s", STUCK_RULE)
        monkeypatch.setattr(sched, "_runs", lambda status=None: [_run("gate", status="waiting")] if status == "waiting" else [])
        monkeypatch.setattr(sched, "_last_activity", lambda eid: T0 - timedelta(hours=5))
        starter = Starter()
        sched.Scheduler(root, start_run=starter, clock=Clock(T0)).tick()
        assert starter.calls == []
        _rule(tmp_path, "s", STUCK_RULE.replace("{after: 45m}", "{after: 45m, waiting: true}"))
        sched.Scheduler(root, start_run=starter, clock=Clock(T0)).tick()
        assert [c[1]["run_id"] for c in starter.calls] == ["gate"]


class TestStorage:
    def test_one_decision_per_occasion(self):
        assert sched.claim("r", "k") is not None
        assert sched.claim("r", "k") is None
        assert sched.claim("r2", "k") is not None
