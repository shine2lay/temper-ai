"""The wait on a failed run's clean-ups: writing it down, ending it, and who ends it.

The point of the wait is that the dev stack and the worktree the failed step was standing on
are still there when the run is picked up again. So the wait has to survive a temper restart
(it is a row, not something in memory), it has to end exactly once (a deadline coming round
while someone presses Give up must not run the clean-ups twice), and a newer attempt of the
same run has to be able to take it over -- otherwise an old deadline tears down the setup the
new attempt is using.
"""

from datetime import UTC, datetime, timedelta

from temper_ai.runner import holds


def _record(execution_id="run-1", *, deadline=None, paths=None, workflow="wf"):
    holds.record(
        execution_id,
        workflow_name=workflow,
        workspace_path="/tmp/ws",
        inputs={"task": "x"},
        held=paths or [{"path": "teardown", "undoes": ["setup"]}],
        deadline=deadline or datetime.now(UTC) + timedelta(hours=24),
        stopped_at="work",
        stop_reason="it failed",
    )


class TestWritingItDown:
    def test_a_wait_is_there_to_be_read_back(self):
        _record("run-written")

        waiting = holds.waiting("run-written")

        assert waiting is not None
        assert waiting["cleanups"] == [{"path": "teardown", "undoes": ["setup"]}]
        assert waiting["workflow_name"] == "wf"
        assert waiting["inputs"] == {"task": "x"}
        assert waiting["stopped_at"] == "work"

    def test_it_says_how_long_is_left(self):
        _record("run-left", deadline=datetime.now(UTC) + timedelta(hours=2))

        assert 7100 < holds.waiting("run-left")["seconds_left"] < 7300

    def test_nothing_held_writes_nothing(self):
        holds.record("run-empty", workflow_name="wf", workspace_path=None, inputs={},
                     held=[], deadline=datetime.now(UTC) + timedelta(hours=1))

        assert holds.waiting("run-empty") is None

    def test_a_later_attempt_replaces_the_wait_of_the_one_before(self):
        _record("run-again", paths=[{"path": "a", "undoes": ["x"]}])
        _record("run-again", paths=[{"path": "b", "undoes": ["y"]}])

        assert holds.waiting("run-again")["cleanups"] == [{"path": "b", "undoes": ["y"]}]


class TestEndingIt:
    def test_give_up_ends_it_and_hands_back_what_was_waiting(self):
        _record("run-giveup")

        ended = holds.end("run-giveup", "released", by="give_up")

        assert ended["cleanups"][0]["path"] == "teardown"
        assert holds.waiting("run-giveup") is None

    def test_it_can_only_be_ended_once(self):
        """The deadline coming round while someone presses Give up: one of them wins."""
        _record("run-once")

        first = holds.end("run-once", "released", by="give_up")
        second = holds.end("run-once", "released", by="deadline")

        assert first is not None
        assert second is None

    def test_finishing_the_run_ends_it(self):
        _record("run-finished")

        holds.finish("run-finished")

        assert holds.waiting("run-finished") is None

    def test_a_run_holding_nothing_has_nothing_to_end(self):
        assert holds.end("run-never", "released", by="give_up") is None


class TestTheDeadline:
    def test_one_that_has_passed_is_due(self):
        _record("run-due", deadline=datetime.now(UTC) - timedelta(minutes=1))

        assert "run-due" in [h["execution_id"] for h in holds.due()]

    def test_one_with_time_left_is_not(self):
        _record("run-not-due", deadline=datetime.now(UTC) + timedelta(hours=5))

        assert "run-not-due" not in [h["execution_id"] for h in holds.due()]

    def test_one_already_ended_is_not_due_however_old(self):
        _record("run-old", deadline=datetime.now(UTC) - timedelta(days=3))
        holds.end("run-old", "released", by="give_up")

        assert "run-old" not in [h["execution_id"] for h in holds.due()]

    def test_a_restart_does_not_lose_it(self):
        """Nothing is kept in memory: a fresh read finds the wait and its deadline."""
        _record("run-restart", deadline=datetime.now(UTC) + timedelta(hours=3))

        # what the server does on startup, with nothing carried over
        still_waiting = holds.waiting("run-restart")

        assert still_waiting is not None
        assert still_waiting["deadline"] is not None


class TestALaterAttemptTakesItOver:
    def test_a_fork_takes_the_wait_over(self):
        _record("run-source")

        holds.take_over("run-source", by="run-fork")

        assert holds.waiting("run-source") is None

    def test_the_old_deadline_cannot_tear_down_what_the_new_attempt_uses(self):
        _record("run-source-2", deadline=datetime.now(UTC) - timedelta(minutes=5))
        holds.take_over("run-source-2", by="run-fork-2")

        assert "run-source-2" not in [h["execution_id"] for h in holds.due()]
