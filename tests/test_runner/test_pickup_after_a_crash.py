"""Which runs a start-up picks back up by itself, and which it leaves alone.

Picking a run up starts real agents and spends real money, so the rule has to be
shy: the tests below are mostly about what it must *not* touch. The rule itself
(``choose``) reads and writes nothing, so it can be asked every awkward question
here without a database, a workflow or a box.
"""

import logging
from datetime import timedelta

import pytest
from fastapi import HTTPException

from temper_ai.checkpoint.models import Checkpoint
from temper_ai.database.session import get_session
from temper_ai.observability.models import Event
from temper_ai.observability.reconcile import reconcile_and_report
from temper_ai.runner import holds, pickup
from temper_ai.runner.models import WorkflowRun
from temper_ai.runner.pickup import Candidate, choose
from temper_ai.shared.clock import utcnow

NOW = utcnow()


def _candidate(execution_id="run-1", **kw) -> Candidate:
    """A run cut off ten minutes ago that nothing is wrong with."""
    fields = {
        "workflow_name": "epd_task",
        "event_id": f"ev-{execution_id}",
        "status_before": "running",
        "last_active_at": NOW - timedelta(minutes=10),
        "has_checkpoints": True,
    }
    fields.update(kw)
    return Candidate(execution_id=execution_id, **fields)


def _why(candidate: Candidate) -> str:
    """The one reason this run was left alone."""
    picks = choose([candidate], now=NOW)
    assert not picks.picked, f"expected {candidate.execution_id} to be left alone"
    return picks.left[0].why


class TestWhatComesBack:
    def test_a_run_cut_off_moments_ago_is_picked_up(self):
        picks = choose([_candidate()], now=NOW)

        assert [c.execution_id for c in picks.picked] == ["run-1"]
        assert not picks.left
        assert "picking up where it stopped" in picks.picked[0].why

    def test_a_run_holding_its_clean_ups_is_picked_up(self):
        """The setup it needs is exactly what the hold is keeping alive."""
        picks = choose([_candidate(hold_status="waiting")], now=NOW)

        assert [c.execution_id for c in picks.picked] == ["run-1"]

    def test_a_run_queued_when_the_crash_came_is_picked_up(self):
        picks = choose([_candidate(status_before="queued")], now=NOW)

        assert [c.execution_id for c in picks.picked] == ["run-1"]

    def test_right_up_to_the_edge_of_the_window(self):
        just_inside = _candidate(last_active_at=NOW - timedelta(hours=11, minutes=59))

        assert choose([just_inside], now=NOW).picked

    def test_the_oldest_comes_back_first(self):
        """So a boot storm resumes in the order the work was lost."""
        picks = choose([
            _candidate("newer", last_active_at=NOW - timedelta(minutes=5)),
            _candidate("older", last_active_at=NOW - timedelta(minutes=50)),
        ], now=NOW)

        assert [c.execution_id for c in picks.picked] == ["older", "newer"]


class TestWhatIsLeftAlone:
    def test_a_cancelled_run_is_never_picked_up(self):
        assert _why(_candidate(cancelled=True)) == "it was cancelled"

    def test_a_run_waiting_for_a_person_is_left_to_wait(self):
        """It is not lost: answering the gate carries it on by itself."""
        assert "waiting for an answer" in _why(_candidate(status_before="waiting"))

    def test_a_run_someone_gave_up_on_is_left_alone(self):
        why = _why(_candidate(hold_status="released", hold_ended_by="give_up"))

        assert "gave up" in why

    def test_a_run_whose_setup_was_let_go_at_its_deadline_is_left_alone(self):
        why = _why(_candidate(hold_status="released", hold_ended_by="deadline"))

        assert "let go at its deadline" in why

    def test_a_run_whose_clean_ups_have_run_is_left_alone(self):
        assert "clean-ups have already run" in _why(_candidate(hold_status="done"))

    def test_a_run_a_later_attempt_took_over_is_left_to_it(self):
        left = _candidate("run-1", hold_status="taken_over", hold_ended_by="another-run")

        assert "took it over" in _why(left)

    def test_a_run_that_took_its_own_hold_over_is_still_picked_up(self):
        """Every resume takes its own hold over; that is not somebody else owning it."""
        again = _candidate("run-1", hold_status="taken_over", hold_ended_by="run-1", pickups=1)

        assert choose([again], now=NOW).picked

    def test_a_run_older_than_the_window_is_left_alone(self):
        why = _why(_candidate(last_active_at=NOW - timedelta(hours=12, minutes=1)))

        assert "12 hours" in why

    def test_a_run_of_unknown_age_is_left_alone(self):
        assert "longer ago than" in _why(_candidate(last_active_at=None))

    def test_a_run_picked_up_twice_already_is_left_alone(self):
        """Twice and dead again is a crash loop, not an accident."""
        why = _why(_candidate(pickups=2))

        assert "picked it up 2 times already" in why
        assert "needs a person" in why

    def test_a_run_picked_up_once_still_gets_another_go(self):
        assert choose([_candidate(pickups=1)], now=NOW).picked

    def test_a_run_with_nothing_saved_is_left_alone(self):
        assert _why(_candidate(has_checkpoints=False)) == "nothing was saved to pick up from"

    def test_a_run_whose_workflow_cannot_be_named_is_left_alone(self):
        assert "which workflow" in _why(_candidate(workflow_name=""))

    def test_being_cancelled_beats_every_other_reason(self):
        """The reason given is the one a person would give first."""
        why = _why(_candidate(cancelled=True, pickups=5, has_checkpoints=False,
                              last_active_at=NOW - timedelta(days=3)))

        assert why == "it was cancelled"


class TestTheWindowAndTheLimitCanBeMoved:
    def test_a_shorter_window(self):
        picks = choose([_candidate()], now=NOW, window=timedelta(minutes=5))

        assert not picks.picked

    def test_a_higher_limit(self):
        picks = choose([_candidate(pickups=2)], now=NOW, max_pickups=3)

        assert picks.picked


class TestTheMessage:
    def test_nothing_is_said_when_there_was_nothing_to_decide(self):
        assert choose([], now=NOW).message() == ""

    def test_it_lists_what_came_back_and_what_did_not(self):
        picks = choose([
            _candidate("aaaaaaaa-1111"),
            _candidate("bbbbbbbb-2222", cancelled=True),
            _candidate("cccccccc-3333", workflow_name="nightly", pickups=2),
        ], now=NOW)

        text = picks.message()

        assert "picked 1 run back up" in text
        assert "Picked up:\n• epd_task aaaaaaaa" in text
        assert "• epd_task bbbbbbbb — it was cancelled" in text
        assert "• nightly cccccccc — temper picked it up 2 times already" in text
        # One line each, and every run named exactly once.
        assert len([ln for ln in text.splitlines() if ln.startswith("•")]) == 3

    def test_it_says_so_when_everything_was_left_alone(self):
        picks = choose([_candidate(cancelled=True)], now=NOW)

        assert "nothing was picked up" in picks.message()

    def test_a_run_link_is_added_when_there_is_a_dashboard(self):
        picks = choose([_candidate("dddddddd-4444")], now=NOW)

        text = picks.message(run_url=lambda i: f"https://temper.example/app/workflow/{i}")

        assert "https://temper.example/app/workflow/dddddddd-4444" in text


class TestPickingThemUp:
    """The side of it that acts: one at a time, stamped, and never fatal."""

    def _marked(self, *ids):
        return [{"execution_id": i, "event_id": f"ev-{i}", "workflow_name": "wf",
                 "status_before": "running", "timestamp": NOW - timedelta(minutes=5)}
                for i in ids]

    @pytest.fixture(autouse=True)
    def _facts(self, monkeypatch):
        """Stand in for the database reads; the acting itself is what is under test here."""
        monkeypatch.setattr(pickup, "SETTLE_S", 0.0)
        monkeypatch.setattr(pickup, "cut_off_by_this_stop",
                            lambda marked, since=None, lane=None: list(marked))
        monkeypatch.setattr(pickup, "candidates_from",
                            lambda marked: [_candidate(str(m["execution_id"])) for m in marked])
        monkeypatch.setattr(pickup, "_stamp_attempt", lambda event_id, attempt: None)

    def test_each_run_is_resumed_once_with_a_gap_between_them(self):
        started, gaps = [], []
        picks = pickup.pick_up_interrupted(
            self._marked("run-a", "run-b", "run-c"),
            resume=started.append, tell=lambda text: True, sleep=gaps.append,
        )

        assert started == ["run-a", "run-b", "run-c"]
        assert len(picks.picked) == 3
        # A gap before every resume but the first.
        assert gaps == [pickup.GAP_S, pickup.GAP_S]

    def test_one_run_that_cannot_start_does_not_stop_the_others(self):
        def resume(execution_id):
            if execution_id == "run-b":
                raise RuntimeError("its box would not start")

        told = []
        picks = pickup.pick_up_interrupted(
            self._marked("run-a", "run-b", "run-c"),
            resume=resume, tell=told.append, sleep=lambda s: None,
        )

        assert [c.execution_id for c in picks.picked] == ["run-a", "run-c"]
        assert [c.execution_id for c in picks.failed] == ["run-b"]
        assert "Could not be started again:" in told[0]
        assert "its box would not start" in told[0]

    def test_a_run_someone_else_carries_on_is_left_alone_without_alarm(self, caplog):
        """F3 (L3): Resume's 409 says someone else is carrying the run on already (Resume
        pressed at the same moment, an answer, another start-up). That is expected: said at
        INFO with no traceback, and the run is listed as left alone, not as failed."""
        def resume(execution_id):
            raise HTTPException(status_code=409,
                                detail=f"Execution '{execution_id}' is already being carried on")

        told = []
        with caplog.at_level(logging.INFO, logger="temper_ai.runner.pickup"):
            picks = pickup.pick_up_interrupted(
                self._marked("run-a"), resume=resume, tell=told.append, sleep=lambda s: None,
            )

        assert picks.picked == [] and picks.failed == []
        assert [(c.execution_id, c.why) for c in picks.left] == [
            ("run-a", "already being carried on")]
        said = [r for r in caplog.records if r.name == "temper_ai.runner.pickup"]
        assert [r.getMessage() for r in said if r.levelno >= logging.WARNING] == []
        assert all(r.exc_info is None for r in said)
        assert any(r.levelno == logging.INFO
                   and r.getMessage() == "Left run-a (epd_task) alone: already being carried on"
                   for r in said)
        assert "Left alone:" in told[0] and "already being carried on" in told[0]

    def test_any_other_refusal_or_failure_is_still_an_error_with_its_traceback(self, caplog):
        def resume(execution_id):
            if execution_id == "run-a":
                raise HTTPException(status_code=400, detail="no checkpoints to resume from")
            raise RuntimeError("its box would not start")

        with caplog.at_level(logging.INFO, logger="temper_ai.runner.pickup"):
            picks = pickup.pick_up_interrupted(
                self._marked("run-a", "run-b"), resume=resume, tell=lambda text: True,
                sleep=lambda s: None,
            )

        assert [c.execution_id for c in picks.failed] == ["run-a", "run-b"]
        errors = [r for r in caplog.records
                  if r.name == "temper_ai.runner.pickup" and r.levelno == logging.ERROR]
        assert [r.getMessage().split(":")[0] for r in errors] == [
            "Could not pick run-a back up", "Could not pick run-b back up"]
        assert all(r.exc_info is not None for r in errors)

    def test_the_attempt_is_written_down_before_it_is_started(self, monkeypatch):
        """The count has to survive the next crash, so it is stamped first."""
        order = []
        monkeypatch.setattr(pickup, "_stamp_attempt",
                            lambda event_id, attempt: order.append(("stamp", event_id, attempt)))
        pickup.pick_up_interrupted(
            self._marked("run-a"), resume=lambda i: order.append(("resume", i)),
            tell=lambda t: True, sleep=lambda s: None,
        )

        assert order == [("stamp", "ev-run-a", 1), ("resume", "run-a")]

    def test_one_message_goes_out_for_the_whole_boot(self):
        told = []
        pickup.pick_up_interrupted(
            self._marked("run-a", "run-b"), resume=lambda i: None,
            tell=told.append, sleep=lambda s: None,
        )

        assert len(told) == 1

    def test_nothing_is_said_when_there_was_nothing_to_pick_up(self):
        told = []
        pickup.pick_up_interrupted([], resume=lambda i: None, tell=told.append,
                                   sleep=lambda s: None)

        assert told == []

    def test_it_can_be_switched_off(self, monkeypatch):
        monkeypatch.setenv(pickup.SWITCH_ENV, "0")
        started, told = [], []

        picks = pickup.pick_up_interrupted(self._marked("run-a"), resume=started.append,
                                           tell=told.append, sleep=lambda s: None)

        assert (started, told, picks.picked) == ([], [], [])

    def test_a_broken_message_does_not_lose_the_runs(self):
        """The work has already happened; a failed DM must not undo it."""
        started = []

        def tell(text):
            raise RuntimeError("Slack is down")

        picks = pickup.pick_up_interrupted(self._marked("run-a"), resume=started.append,
                                           tell=tell, sleep=lambda s: None)

        assert started == ["run-a"]
        assert len(picks.picked) == 1


class TestTheWayItStartsThemAgain:
    """Not its own resume: the one the Resume button uses."""

    def test_it_goes_through_the_same_door_as_the_button(self, monkeypatch):
        asked = []
        monkeypatch.setattr("temper_ai.api.routes.resume_run",
                            lambda execution_id, body: asked.append((execution_id, body)))

        pickup._resume_through_the_button("run-door")

        [(execution_id, body)] = asked
        assert execution_id == "run-door"
        # No steps ticked to rerun: exactly what the engine works out by itself.
        assert body.rerun == []

    def test_the_thread_does_the_work_and_start_up_does_not_wait(self, monkeypatch):
        started = []
        monkeypatch.setattr(pickup, "SETTLE_S", 0.0)
        monkeypatch.setattr(pickup, "cut_off_by_this_stop",
                            lambda marked, since=None, lane=None: list(marked))
        monkeypatch.setattr(pickup, "candidates_from",
                            lambda marked: [_candidate("run-thread")])
        monkeypatch.setattr(pickup, "_stamp_attempt", lambda event_id, attempt: None)
        monkeypatch.setattr(pickup, "_resume_through_the_button", started.append)
        monkeypatch.setattr(pickup, "_tell_owner", lambda text: True)

        thread = pickup.pick_up_in_the_background([{"execution_id": "run-thread"}])

        assert thread is not None
        thread.join(timeout=10)
        assert started == ["run-thread"]

    def test_it_still_looks_when_start_up_marked_nothing(self, monkeypatch):
        """Live, the lost runs are the ones whose boxes died -- the marking sees none of them."""
        looked = []
        monkeypatch.setattr(pickup, "SETTLE_S", 0.0)
        monkeypatch.setattr(pickup, "cut_off_by_this_stop",
                            lambda marked, since=None, lane=None: looked.append(list(marked)) or [])

        thread = pickup.pick_up_in_the_background([])

        assert thread is not None
        thread.join(timeout=10)
        assert looked == [[]]

    def test_switched_off_starts_no_thread(self, monkeypatch):
        monkeypatch.setenv(pickup.SWITCH_ENV, "0")

        assert pickup.pick_up_in_the_background([{"execution_id": "run-off"}]) is None

    def test_it_waits_for_the_dust_to_settle_before_looking(self, monkeypatch):
        """The reaper ends the runs whose boxes died; looking first would see none of them."""
        order = []
        monkeypatch.setattr(pickup, "cut_off_by_this_stop",
                            lambda marked, since=None, lane=None: order.append("looked") or [])

        pickup.pick_up_interrupted([], settle_s=42, sleep=lambda s: order.append(f"waited {s}"))

        assert order == ["waited 42", "looked"]


class TestWhatTheRuleIsToldAboutEachRun:
    """``candidates_from`` reads the run's own story out of the database.

    The rule above is only as good as these facts, and they are the part that
    breaks quietly when a column is renamed.
    """

    def _interrupted(self, execution_id="run-db", *, minutes_ago=10, name="epd_task",
                     status="running", data=None, stamped=0):
        """A run marked interrupted by a start-up, with what temper knows about it."""
        when = utcnow() - timedelta(minutes=minutes_ago)
        with get_session() as s:
            body = {"name": name, **(data or {})}
            if stamped:
                body[pickup.STAMP] = {"at": when.isoformat(), "attempt": stamped}
            s.add(Event(id=f"ev-{execution_id}", type="workflow.started",
                        execution_id=execution_id, status="interrupted",
                        data=body, timestamp=when))
            s.commit()
        return {"execution_id": execution_id, "event_id": f"ev-{execution_id}",
                "workflow_name": name, "status_before": status, "timestamp": when}

    def _checkpoint(self, execution_id):
        with get_session() as s:
            s.add(Checkpoint(execution_id=execution_id, sequence=0, event_type="node_completed",
                             node_name="work", status="completed"))
            s.commit()

    def test_a_run_with_a_checkpoint_and_nothing_against_it_is_picked_up(self):
        marked = self._interrupted("run-ok")
        self._checkpoint("run-ok")

        assert choose(pickup.candidates_from([marked])).picked

    def test_a_run_with_no_checkpoints_is_left_alone(self):
        marked = self._interrupted("run-bare")

        [candidate] = pickup.candidates_from([marked])

        assert candidate.has_checkpoints is False

    def test_a_run_whose_row_says_cancelled_is_left_alone(self):
        marked = self._interrupted("run-stopped")
        self._checkpoint("run-stopped")
        with get_session() as s:
            s.add(WorkflowRun(execution_id="run-stopped", workflow_name="epd_task",
                              workspace_path="/tmp/ws", status="cancelled"))
            s.commit()

        assert not choose(pickup.candidates_from([marked])).picked

    def test_a_run_a_cancel_was_on_its_way_to_is_left_alone(self):
        """Cancel pressed, crash before the run noticed: the ask still counts."""
        marked = self._interrupted("run-cancelling")
        self._checkpoint("run-cancelling")
        with get_session() as s:
            s.add(WorkflowRun(execution_id="run-cancelling", workflow_name="epd_task",
                              workspace_path="/tmp/ws", status="running",
                              cancel_requested=True))
            s.commit()

        assert _why(pickup.candidates_from([marked])[0]) == "it was cancelled"

    def test_a_run_whose_gate_was_rejected_is_left_alone(self):
        marked = self._interrupted("run-refused")
        self._checkpoint("run-refused")
        with get_session() as s:
            s.add(Event(id="ev-gate", type="gate.waiting", execution_id="run-refused",
                        status="rejected", data={"gate_status": "rejected"},
                        timestamp=utcnow() - timedelta(minutes=11)))
            s.commit()

        assert _why(pickup.candidates_from([marked])[0]) == "it was cancelled"

    def test_the_hold_on_its_clean_ups_comes_through(self):
        marked = self._interrupted("run-held")
        holds.record("run-held", workflow_name="epd_task", workspace_path="/tmp/ws",
                     inputs={}, held=[{"path": "teardown", "undoes": ["setup"]}],
                     deadline=utcnow() + timedelta(hours=24), stopped_at="work",
                     stop_reason="it stopped")
        holds.end("run-held", "released", by="give_up")

        [candidate] = pickup.candidates_from([marked])

        assert (candidate.hold_status, candidate.hold_ended_by) == ("released", "give_up")

    def test_the_pick_ups_temper_already_made_are_counted(self):
        marked = self._interrupted("run-twice", stamped=1)
        self._checkpoint("run-twice")
        # A second attempt of the same run, also picked up and also interrupted.
        with get_session() as s:
            s.add(Event(id="ev-run-twice-2", type="workflow.started",
                        execution_id="run-twice", status="interrupted",
                        data={"name": "epd_task", pickup.STAMP: {"attempt": 2}},
                        timestamp=utcnow() - timedelta(minutes=5)))
            s.commit()

        [candidate] = pickup.candidates_from([marked])

        assert candidate.pickups == 2
        assert "2 times already" in _why(candidate)

    def test_age_is_measured_from_the_last_thing_the_run_did(self):
        """A run started 20 hours ago but alive 5 minutes ago is fresh."""
        marked = self._interrupted("run-long", minutes_ago=20 * 60)
        self._checkpoint("run-long")
        with get_session() as s:
            s.add(Event(id="ev-long-step", type="agent.completed", execution_id="run-long",
                        status="completed", data={},
                        timestamp=utcnow() - timedelta(minutes=5)))
            s.commit()

        assert choose(pickup.candidates_from([marked])).picked

    def test_a_stamp_is_written_where_the_next_start_up_will_find_it(self):
        self._interrupted("run-stamp")

        pickup._stamp_attempt("ev-run-stamp", 1)

        with get_session() as s:
            assert s.get(Event, "ev-run-stamp").data[pickup.STAMP]["attempt"] == 1


class TestFromTheMarkingToTheRule:
    """What the marking hands over is what the rule can read."""

    def test_a_marked_run_arrives_with_its_name_and_the_status_it_had(self):
        with get_session() as s:
            s.add(Event(id="ev-handover", type="workflow.started",
                        execution_id="run-handover", status="waiting",
                        data={"name": "epd_task"},
                        timestamp=utcnow() - timedelta(minutes=30)))
            s.commit()

        [marked] = reconcile_and_report(started_before=utcnow())

        assert marked["execution_id"] == "run-handover"
        assert marked["workflow_name"] == "epd_task"
        assert marked["status_before"] == "waiting"
        # And the rule can act on it without asking anything else.
        assert "waiting for an answer" in _why(pickup.candidates_from([marked])[0])

    def test_an_ordinary_restart_hands_over_nothing(self):
        assert reconcile_and_report(started_before=utcnow()) == []


class TestTheRunsWhoseBoxesDied:
    """Live, temper hands each run to its own box -- and that is where they die.

    A box run outlives a restart of the server, so the marking must not touch it, and does
    not. When the box died too, the worker's reaper finds it gone seconds after coming back
    and ends the run itself. Those are the runs a restart has to pick up, and they only
    exist a little *after* start-up -- which is why the pick-up waits before it looks.
    """

    def _reaped(self, execution_id, *, completed_ago=timedelta(seconds=5),
                row_status="orphaned", event_status="interrupted", name="epd_build"):
        """A run whose box was found dead: the row and the event the reaper writes."""
        with get_session() as s:
            s.add(WorkflowRun(execution_id=execution_id, workflow_name=name,
                              workspace_path="/tmp/ws", status=row_status,
                              spawner_kind="docker", spawner_handle=f"temper-run-{execution_id}",
                              completed_at=utcnow() - completed_ago))
            s.add(Event(id=f"ev-{execution_id}", type="workflow.started",
                        execution_id=execution_id, status=event_status,
                        data={"name": name, "error": "reaped: worker process gone"},
                        timestamp=utcnow() - timedelta(minutes=20)))
            s.commit()

    def test_a_run_whose_box_died_with_the_stack_is_found(self):
        self._reaped("run-boxed")

        [found] = pickup.cut_off_by_this_stop([], since=utcnow() - timedelta(minutes=1))

        assert found["execution_id"] == "run-boxed"
        assert found["workflow_name"] == "epd_build"
        assert found["event_id"] == "ev-run-boxed"
        assert found["status_before"] == "running"

    def test_a_box_that_died_during_the_last_uptime_is_not_this_restarts_business(self):
        """It was already dead and already seen; a restart does not re-open old graves."""
        self._reaped("run-old-box", completed_ago=timedelta(hours=3))

        assert pickup.cut_off_by_this_stop([], since=utcnow() - timedelta(minutes=1)) == []

    def test_a_box_buried_on_the_way_down_still_counts_as_this_stop(self):
        """A stack going down is not instant: the reaper can bury a box before it goes.

        Seen for real: both boxes were killed at 05:27:59 and the reaper, still up, wrote
        them down two seconds before the server itself stopped. Measuring strictly from
        the new process's start would leave exactly the runs this is meant to save.
        """
        self._reaped("run-last-gasp", completed_ago=timedelta(minutes=2))
        with get_session() as s:
            s.add(Checkpoint(execution_id="run-last-gasp", sequence=0,
                             event_type="node_completed", node_name="build", status="completed"))
            s.commit()
        picked = []

        pickup.pick_up_interrupted([], since=utcnow(), settle_s=0, sleep=lambda s: None,
                                   resume=picked.append, tell=lambda t: True)

        assert picked == ["run-last-gasp"]

    def test_a_run_still_going_in_its_box_is_left_alone(self):
        """The whole reason the marking skips box runs: they survive the restart."""
        self._reaped("run-alive", row_status="running", event_status="running")

        assert pickup.cut_off_by_this_stop([], since=utcnow() - timedelta(minutes=1)) == []

    def test_a_box_run_that_ended_any_other_way_is_left_alone(self):
        for execution_id, row, event in [("run-done", "completed", "completed"),
                                         ("run-stopped-box", "cancelled", "cancelled"),
                                         ("run-failed-box", "failed", "failed")]:
            self._reaped(execution_id, row_status=row, event_status=event)

        assert pickup.cut_off_by_this_stop([], since=utcnow() - timedelta(minutes=1)) == []

    def test_the_marking_and_the_reaper_are_one_list_without_repeats(self):
        self._reaped("run-boxed")
        marked = {"execution_id": "run-inprocess", "event_id": "ev-x",
                  "workflow_name": "epd_task", "status_before": "running",
                  "timestamp": utcnow() - timedelta(minutes=8)}
        also_marked = {"execution_id": "run-boxed", "event_id": "ev-run-boxed",
                       "workflow_name": "epd_build", "status_before": "running",
                       "timestamp": utcnow() - timedelta(minutes=20)}

        found = pickup.cut_off_by_this_stop([marked, also_marked],
                                            since=utcnow() - timedelta(minutes=1))

        assert sorted(str(f["execution_id"]) for f in found) == ["run-boxed", "run-inprocess"]

    def test_a_reaped_run_goes_through_the_rule_like_any_other(self):
        self._reaped("run-boxed")
        with get_session() as s:
            s.add(Checkpoint(execution_id="run-boxed", sequence=0, event_type="node_completed",
                             node_name="build", status="completed"))
            s.commit()

        picks = choose(pickup.candidates_from(
            pickup.cut_off_by_this_stop([], since=utcnow() - timedelta(minutes=1))))

        assert [c.execution_id for c in picks.picked] == ["run-boxed"]
