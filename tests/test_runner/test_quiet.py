"""The quiet-run rule: which runs are worth saying something about.

The point of these tests is the four-way choice. A run that ended says
nothing, a run waiting for a person is healthy however long it waits, and
only a run still marked running with nothing new for longer than its
threshold is quiet.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from temper_ai.runner import quiet
from temper_ai.runner.quiet import (
    DEFAULT_AFTER,
    DONE,
    HEALTHY,
    QUIET,
    WAITING,
    Run,
    how_long,
    last_step_label,
    look,
    looks,
    parse_after,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def run(**kw) -> Run:
    base = {"execution_id": "e1", "workflow_name": "epd_loop", "status": "running",
            "last_activity_at": NOW - timedelta(minutes=5)}
    return Run(**{**base, **kw})


# ─── the four states ──────────────────────────────────────────────────────


def test_a_run_that_wrote_something_recently_is_healthy():
    assert look(run(last_activity_at=NOW - timedelta(minutes=5)), now=NOW).state == HEALTHY


def test_silent_past_the_threshold_is_quiet():
    verdict = look(run(last_activity_at=NOW - timedelta(hours=2, minutes=14)), now=NOW)
    assert verdict.state == QUIET
    assert verdict.quiet
    assert verdict.how_long == "2h 14m"
    assert verdict.idle == timedelta(hours=2, minutes=14)


def test_exactly_at_the_threshold_counts_as_quiet():
    """Not "more than 30 minutes": 30 minutes of nothing is already quiet."""
    assert look(run(last_activity_at=NOW - DEFAULT_AFTER), now=NOW).state == QUIET
    assert look(run(last_activity_at=NOW - DEFAULT_AFTER + timedelta(seconds=1)),
                now=NOW).state == HEALTHY


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "interrupted"])
def test_a_run_that_ended_is_never_quiet(status):
    """However long ago it ended -- there is nothing to chase."""
    verdict = look(run(status=status, last_activity_at=NOW - timedelta(days=3)), now=NOW)
    assert verdict.state == DONE
    assert not verdict.quiet
    assert verdict.idle is None


def test_waiting_for_a_person_is_not_quiet():
    """A gate is the run doing its job. Ten hours at a gate is still waiting."""
    verdict = look(run(at_a_gate=True, last_activity_at=NOW - timedelta(hours=10)), now=NOW)
    assert verdict.state == WAITING
    assert not verdict.quiet
    assert verdict.how_long == "10h"


def test_the_listing_status_waiting_is_believed_too():
    """Callers that have the status but not the gate flag get it right."""
    verdict = look(run(status="waiting", last_activity_at=NOW - timedelta(hours=10)), now=NOW)
    assert verdict.state == WAITING


def test_a_run_that_has_not_started_is_left_alone():
    assert look(run(status="queued", last_activity_at=None), now=NOW).state == HEALTHY


def test_nothing_known_about_it_means_nothing_is_said():
    """No events and no start time: temper will not guess."""
    verdict = look(run(last_activity_at=None, started_at=None), now=NOW)
    assert verdict.state == HEALTHY
    assert verdict.idle is None


def test_a_run_with_no_events_is_judged_from_when_it_started():
    """A run that died before writing anything is still a quiet run."""
    verdict = look(run(last_activity_at=None, started_at=NOW - timedelta(hours=3)), now=NOW)
    assert verdict.state == QUIET
    assert verdict.how_long == "3h"


# ─── the threshold ────────────────────────────────────────────────────────


def test_the_workflow_sets_its_own_threshold():
    """Two hours of quiet is a normal deploy step for EPD..."""
    patient = run(after=timedelta(hours=4), last_activity_at=NOW - timedelta(hours=2))
    assert look(patient, now=NOW).state == HEALTHY


def test_and_a_short_threshold_makes_a_short_silence_quiet():
    """...and alarming in a workflow that should take a minute."""
    brisk = run(after=timedelta(minutes=2), last_activity_at=NOW - timedelta(minutes=5))
    verdict = look(brisk, now=NOW)
    assert verdict.state == QUIET
    assert verdict.after == timedelta(minutes=2)


def test_without_one_the_default_applies():
    assert look(run(), now=NOW).after == DEFAULT_AFTER
    assert DEFAULT_AFTER == timedelta(minutes=30)


def test_a_caller_may_pass_its_own_default():
    """Notify's stuck_after, so the page and the message say the same thing."""
    verdict = look(run(last_activity_at=NOW - timedelta(minutes=40)), now=NOW,
                   default_after=timedelta(minutes=45))
    assert verdict.state == HEALTHY
    assert verdict.after == timedelta(minutes=45)


def test_the_workflows_own_threshold_beats_the_callers_default():
    verdict = look(run(after=timedelta(minutes=10), last_activity_at=NOW - timedelta(minutes=20)),
                   now=NOW, default_after=timedelta(hours=6))
    assert verdict.state == QUIET


@pytest.mark.parametrize("written,expected", [
    ("45m", timedelta(minutes=45)),
    ("2h", timedelta(hours=2)),
    (900, timedelta(minutes=15)),
    (None, None),
    ("", None),
    (False, None),
    ("soon", None),          # not a duration: the default stands
    ("0m", None),            # zero is not a threshold
])
def test_quiet_after_as_written_in_a_workflow(written, expected):
    assert parse_after(written, where="a_workflow") == expected


# ─── saying it in words ───────────────────────────────────────────────────


@pytest.mark.parametrize("span,words", [
    (timedelta(seconds=30), "under a minute"),
    (timedelta(minutes=45), "45m"),
    (timedelta(hours=2, minutes=14), "2h 14m"),
    (timedelta(hours=3), "3h"),
    (timedelta(days=1, hours=4), "1d 4h"),
    (timedelta(days=2), "2d"),
    (None, "an unknown time"),
])
def test_how_long_in_words(span, words):
    assert how_long(span) == words


@pytest.mark.parametrize("last_activity,at_a_gate", [
    (timedelta(seconds=40), False),   # quiet, only just
    (timedelta(seconds=10), True),    # waiting, only just
])
def test_a_short_span_still_reads_as_a_length(last_activity, at_a_gate):
    """Every span goes after "for" or before "so far", so it must be one.

    A gate spends its first minute in this branch every single time, and
    said "is waiting on you, just now so far".
    """
    verdict = look(run(last_activity_at=NOW - last_activity,
                       at_a_gate=at_a_gate, after=timedelta(seconds=30)), now=NOW)

    assert verdict.how_long == "under a minute"
    assert "just now" not in verdict.sentence("epd_loop")


def test_the_sentence_says_how_long_and_what_it_was_doing():
    verdict = look(run(last_activity_at=NOW - timedelta(hours=2, minutes=14),
                       last_step="deploy · running a tool"), now=NOW)
    said = verdict.sentence("epd_loop")
    assert "quiet for 2h 14m" in said
    assert "deploy · running a tool" in said
    assert "epd_loop" in said


def test_a_waiting_run_is_described_as_waiting_on_you():
    said = look(run(at_a_gate=True, last_activity_at=NOW - timedelta(hours=1)), now=NOW).sentence()
    assert "waiting on you" in said


@pytest.mark.parametrize("event,data,status,expected", [
    ("tool.call.started", {"node_name": "deploy", "tool_name": "bash"}, "running", "deploy · running bash"),
    ("llm.call.started", {"agent_name": "planner"}, "running", "planner · thinking"),
    ("stage.started", {"node_name": "approve", "gate": True}, "waiting", "approve · waiting for an OK"),
    ("stage.completed", {"node_name": "build"}, "completed", "build · finished"),
    ("workflow.started", {}, "running", "started"),
    ("something.new", {"node_name": "x"}, "", "x · something.new"),
])
def test_the_last_thing_it_did_in_words(event, data, status, expected):
    assert last_step_label(event, data, status) == expected


# ─── many at once ─────────────────────────────────────────────────────────


def test_looks_judges_a_whole_listing():
    verdicts = looks([
        Run(execution_id="fine", last_activity_at=NOW - timedelta(minutes=1)),
        Run(execution_id="gone", status="completed"),
        Run(execution_id="gate", at_a_gate=True, last_activity_at=NOW - timedelta(hours=9)),
        Run(execution_id="dead", last_activity_at=NOW - timedelta(hours=10)),
    ], now=NOW)
    assert {k: v.state for k, v in verdicts.items()} == {
        "fine": HEALTHY, "gone": DONE, "gate": WAITING, "dead": QUIET,
    }


def test_the_rule_reads_nothing_and_changes_nothing(monkeypatch):
    """It is a pure function: no database, so the page can call it per row."""
    def explode(*a, **k):
        raise AssertionError("the rule must not touch the database")

    monkeypatch.setattr(quiet, "_read_quiet_after", explode)
    assert look(run(last_activity_at=NOW - timedelta(hours=1)), now=NOW).state == QUIET


# ─── the facts, from the database ─────────────────────────────────────────


def write_event(execution_id: str, kind: str, at: datetime, *, status: str = "running",
                data: dict | None = None) -> None:
    from temper_ai.database import get_session
    from temper_ai.observability.models import Event

    with get_session() as session:
        session.add(Event(type=kind, execution_id=execution_id, status=status,
                          data=data or {}, timestamp=at))
        session.commit()


class TestWhatEachRunLastDid:
    def test_the_newest_event_of_each_run_with_what_it_was(self):
        write_event("a", "stage.started", NOW - timedelta(hours=4), data={"name": "build"})
        write_event("a", "tool.call.started", NOW - timedelta(hours=2),
                    data={"node_name": "deploy", "tool_name": "bash"})
        write_event("b", "llm.call.started", NOW - timedelta(minutes=1), data={"agent_name": "planner"})

        seen = quiet.activity_of(["a", "b", "never-ran"])

        assert seen["a"].at == NOW - timedelta(hours=2)
        assert seen["a"].step == "deploy · running bash"
        assert seen["b"].step == "planner · thinking"
        assert "never-ran" not in seen        # no events: nothing claimed about it

    def test_no_ids_no_query(self):
        assert quiet.activity_of([]) == {}

    def test_a_listing_is_judged_from_what_the_database_says(self):
        write_event("stalled", "stage.started", NOW - timedelta(hours=3), data={"name": "deploy"})
        write_event("busy", "llm.call.started", NOW - timedelta(minutes=2), data={"agent_name": "coder"})

        verdicts = quiet.verdicts_for(
            [{"id": "stalled", "workflow_name": "epd_loop", "status": "running"},
             {"id": "busy", "workflow_name": "epd_loop", "status": "running"},
             {"id": "done", "workflow_name": "epd_loop", "status": "completed"}],
            now=NOW,
        )

        assert verdicts["stalled"].state == QUIET
        assert verdicts["stalled"].last_step == "deploy · started"
        assert verdicts["busy"].state == HEALTHY
        assert verdicts["done"].state == DONE

    def test_a_workflows_own_threshold_is_read_from_its_config(self):
        """The shape a real config file has: everything under ``workflow:``.

        This went live reading only the top level, so every workflow's own
        quiet_after read as "nothing here" and silently fell back to the
        45-minute default. The first test of it used a flat dict nobody
        writes, and passed.
        """
        from temper_ai.config.store import ConfigStore

        ConfigStore().put("slow_build", "workflow",
                          {"workflow": {"name": "slow_build", "quiet_after": "4h",
                                        "nodes": []}})
        quiet.forget_thresholds()
        write_event("slow", "stage.started", NOW - timedelta(hours=3), data={"name": "deploy"})

        verdicts = quiet.verdicts_for(
            [{"id": "slow", "workflow_name": "slow_build", "status": "running"}], now=NOW)

        assert verdicts["slow"].state == HEALTHY
        assert verdicts["slow"].after == timedelta(hours=4)

    def test_a_threshold_written_without_the_wrapper_is_read_too(self):
        """Some callers hand the body over already unwrapped."""
        from temper_ai.config.store import ConfigStore

        ConfigStore().put("flat_build", "workflow",
                          {"name": "flat_build", "quiet_after": "4h", "nodes": []})
        quiet.forget_thresholds()

        assert quiet.after_for("flat_build") == timedelta(hours=4)

    def test_a_workflow_that_says_nothing_gets_the_default(self):
        quiet.forget_thresholds()
        assert quiet.after_for("no_such_workflow") == DEFAULT_AFTER
        assert quiet.after_for("no_such_workflow", timedelta(minutes=45)) == timedelta(minutes=45)

    def test_the_threshold_is_not_read_again_for_every_run(self):
        """A listing of 300 runs must not be 300 config reads."""
        calls: list[str] = []
        quiet.forget_thresholds()

        original = quiet._read_quiet_after
        try:
            quiet._read_quiet_after = lambda name: (calls.append(name), None)[1]  # type: ignore[assignment]
            for _ in range(5):
                quiet.after_for("epd_loop")
        finally:
            quiet._read_quiet_after = original  # type: ignore[assignment]

        assert calls == ["epd_loop"]
