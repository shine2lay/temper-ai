"""`resume` goes on where the run stopped (queue task 9, 2026-09-27).

A resumed bet used to be forked at the checkpoint before its failed stage, so the build ran again
whole -- plan, build and every review -- when only its deploy had failed or a restart had cut its
review short: hours and $15-30 each time. temper now goes on inside a stage from the stage's own
last finished step (temper_ai/stage/restore.py), so the driver forks at the run's latest checkpoint
instead, and keeps the build's claim on the task: the build goes on, it does not start over.

It still starts the stage over when there is nothing to go on from: a build that ended at its round
cap (the run completed), a plan (planned again against a new snapshot), or a stage the owner names.
"""

import subprocess

from tests.test_epd import test_epd_loop

# The driver, loaded with its state in a temporary directory: test_epd_loop's fixture, by name.
L = test_epd_loop.L

STARTED = "2026-09-23T03:44:04+00:00"
# The old run's checkpoints: the plan, then the build's steps; its deploy failed at 9.
CHECKPOINTS = [
    ("tasks.tasks", "completed"),
    ("tasks", "completed"),
    ("turn", "completed"),
    ("build.claim", "completed"),
    ("build.implement", "completed"),
    ("build.test", "completed"),
    ("build.review", "completed"),
    ("build.verify", "completed"),
    ("build.environment.stack_up", "completed"),
    ("build.environment.deploy", "failed"),
]


def _resume(L, monkeypatch, *, status="failed", error="1 node(s) failed: build/environment/deploy",
            nodes=(("tasks", "completed"), ("turn", "completed"), ("build", "completed")),
            checkpoints=CHECKPOINTS, at=None):
    test_epd_loop.propose(L)
    st = L.load_state("b001")
    st.update(status="running", plan_started=STARTED)
    st["stages"]["loop"] = {"_run_id": "run-1"}
    L.save_state(st)
    L.ledger_upsert("b001", status="running")
    monkeypatch.setattr(L, "get_run", lambda rid: {
        "status": status, "error_message": error,
        "nodes": [{"name": n, "status": s} for n, s in nodes],
    })
    monkeypatch.setattr(L, "checkpoints", lambda rid: [
        {"node_name": n, "status": s, "sequence": i} for i, (n, s) in enumerate(checkpoints)
    ])
    commands = []

    def in_server(cmd):
        commands.append(cmd)
        # the claim on the task is held by the old run; the worktree is clean
        out = "run-1" if "claims/" in cmd and "python3" in cmd else "0" if "wc -l" in cmd else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(L, "in_server", in_server)
    monkeypatch.setattr(L, "loop_inputs", lambda bet_id, planning=True: {"bet_id": bet_id})
    forks = []
    monkeypatch.setattr(L, "fork_run", lambda *a: forks.append(a) or "run-2")
    L.cmd_resume(at=at, bet="b001")
    assert len(forks) == 1
    loop = L.load_state("b001")["stages"]["loop"]
    return forks[0], loop, commands


def _claim_cleared(commands) -> bool:
    return any(c.startswith("rm -f") and "claims/" in c for c in commands)


def _moved(L) -> bool:
    return L.load_state("b001")["plan_started"] != STARTED


class TestItGoesOn:
    def test_a_build_whose_deploy_failed_is_forked_at_its_latest_checkpoint(self, L, monkeypatch):
        fork, loop, commands = _resume(L, monkeypatch)
        source, seq = fork[0], fork[1]
        assert (source, seq) == ("run-1", len(CHECKPOINTS) - 1)
        assert loop["_went_on"] is True and loop["_fork_sequence"] == seq
        # the build goes on: it keeps its claim on the task and its place in the line
        assert not _claim_cleared(commands)
        assert not _moved(L)

    def test_a_build_cut_short_by_a_restart_goes_on_too(self, L, monkeypatch):
        """An interrupted run names no failed stage: the one that was running is the build."""
        interrupted = CHECKPOINTS[:7]  # the restart came during the verify step
        fork, loop, _ = _resume(L, monkeypatch, error="Server restarted while the run was active",
                                nodes=(("tasks", "completed"), ("turn", "completed")),
                                checkpoints=interrupted)
        assert fork[1] == len(interrupted) - 1
        assert loop["_went_on"] is True

    def test_a_failed_ship_goes_on_from_the_ship(self, L, monkeypatch):
        """Stages after the build go on the same way: what failed runs again, and what follows."""
        ship = [*CHECKPOINTS[:-1], ("build", "completed"), ("ship", "failed")]
        fork, loop, _ = _resume(L, monkeypatch, error="1 node(s) failed: ship", checkpoints=ship,
                                nodes=(("tasks", "completed"), ("build", "completed"), ("ship", "failed")))
        assert fork[1] == len(ship) - 1 and loop["_went_on"] is True


class TestItStartsTheStageOver:
    def test_when_the_owner_names_the_stage(self, L, monkeypatch):
        fork, loop, commands = _resume(L, monkeypatch, at="build")
        assert fork[1] == 1  # after `tasks`
        assert loop["_went_on"] is False
        assert _claim_cleared(commands)
        assert _moved(L)  # a build again goes to the back of the line, as before

    def test_when_the_build_ended_at_its_round_cap(self, L, monkeypatch):
        """The run completed: every step finished, so going on would build nothing new."""
        fork, loop, _ = _resume(
            L, monkeypatch, status="completed", error="",
            nodes=(("tasks", "completed"), ("build", "completed"), ("ship", "skipped")))
        assert fork[1] == 1 and loop["_went_on"] is False

    def test_when_the_plan_failed(self, L, monkeypatch):
        """A plan is made again against what the build would start from now."""
        plan = [("tasks.tasks", "completed"), ("tasks.check", "failed")]
        fork, loop, _ = _resume(L, monkeypatch, error="1 node(s) failed: tasks/check", checkpoints=plan,
                                nodes=(("tasks", "failed"),))
        assert fork[1] == 0 and loop["_went_on"] is False

    def test_when_the_run_left_no_checkpoints_of_its_own(self, L, monkeypatch):
        """A fork that stopped before it wrote any: the old choice, the checkpoint before the
        stage, in the run it was forked from."""
        test_epd_loop.propose(L)
        st = L.load_state("b001")
        st.update(status="running", plan_started=STARTED)
        st["stages"]["loop"] = {"_run_id": "run-2", "_forked_from": "run-1"}
        L.save_state(st)
        L.ledger_upsert("b001", status="running")
        monkeypatch.setattr(L, "get_run", lambda rid: {
            "status": "failed", "error_message": "Server restarted while the run was active",
            "nodes": [{"name": "tasks", "status": "completed"}]})
        monkeypatch.setattr(L, "checkpoints", lambda rid: [] if rid == "run-2" else [
            {"node_name": n, "status": s, "sequence": i} for i, (n, s) in enumerate(CHECKPOINTS)])
        monkeypatch.setattr(L, "in_server",
                            lambda cmd: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""))
        monkeypatch.setattr(L, "loop_inputs", lambda bet_id, planning=True: {"bet_id": bet_id})
        forks = []
        monkeypatch.setattr(L, "fork_run", lambda *a: forks.append(a) or "run-3")
        L.cmd_resume(bet="b001")
        assert forks[0][:2] == ("run-1", 1)
        assert L.load_state("b001")["stages"]["loop"]["_went_on"] is False
