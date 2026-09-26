"""Notices: which runs get one, where it goes, one thread per run, never twice."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from temper_ai.integrations.slack import store
from temper_ai.integrations.slack.blocks import APPROVE, REJECT, STOP
from temper_ai.integrations.slack.config import ConfigWatcher
from temper_ai.integrations.slack.notifier import Notifier, RunPoster

from .conftest import OWNER

T0 = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
DM = f"D{OWNER}"
RUNS = "C0RUNS001"


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def notifier(slack, ops, slack_config, clock) -> Notifier:
    n = Notifier(RunPoster(slack), ConfigWatcher(), ops, clock=clock)
    assert n.tick() == []  # switching on: records "Slack is on from now"
    return n


def _minutes(n: int) -> datetime:
    return T0 + timedelta(minutes=n)


class TestGates:
    def test_a_waiting_gate_posts_buttons_to_the_dm_once(self, notifier, slack, ops, clock):
        ops.add_run("run-1", "gate_demo", "running", _minutes(1))
        ops.alive.add("run-1")
        ops.add_gate("ev-1", "run-1", "approve_step", _minutes(2))
        clock.now = _minutes(3)
        sent = notifier.tick()
        assert [s["kind"] for s in sent] == ["gate"]
        post = slack.posts[0]
        assert post["channel"] == DM and post["broadcast"] is True
        assert "waiting for approval at approve_step" in post["text"]
        assert slack.buttons(post)[:2] == [APPROVE, REJECT]
        assert notifier.tick() == [] and len(slack.posts) == 1

    def test_the_same_node_gating_again_is_a_new_notice(self, notifier, slack, ops, clock):
        ops.add_run("run-1", "gate_demo", "running", _minutes(1))
        ops.add_gate("ev-1", "run-1", "approve_step", _minutes(2))
        clock.now = _minutes(3)
        notifier.tick()
        ops.approve("run-1", "approve_step")
        ops.add_gate("ev-2", "run-1", "approve_step", _minutes(4))
        clock.now = _minutes(5)
        notifier.tick()
        gate_posts = [p for p in slack.posts if "waiting for approval" in p["text"]]
        assert len(gate_posts) == 2
        assert gate_posts[1]["thread_ts"] == gate_posts[0]["ts"]  # same run, same thread

    def test_gates_from_before_slack_was_on_are_history(self, slack, ops, slack_config, clock):
        ops.add_run("old", "gate_demo", "running", T0 - timedelta(hours=2))
        ops.add_gate("ev-old", "old", "approve_step", T0 - timedelta(hours=1))
        n = Notifier(RunPoster(slack), ConfigWatcher(), ops, clock=clock)
        assert n.tick() == [] and slack.posts == []

    def test_a_gate_answered_in_the_dashboard_loses_its_buttons(self, notifier, slack, ops, clock):
        ops.add_run("run-1", "gate_demo", "running", _minutes(1))
        ops.add_gate("ev-1", "run-1", "approve_step", _minutes(2))
        clock.now = _minutes(3)
        notifier.tick()
        ops.approve("run-1", "approve_step")  # clicked in the web UI, not Slack
        clock.now = _minutes(4)
        closed = notifier.tick()
        assert {"kind": "gate_closed", "execution_id": "run-1", "verdict": "approved"} in closed
        update = slack.updates[-1]
        assert update["ts"] == slack.posts[0]["ts"] and "Approved in temper" in str(update["blocks"])
        assert not any(b.get("type") == "actions" for b in update["blocks"])
        # The header says what happened, not that it is still waiting.
        header = update["blocks"][0]["text"]["text"]
        assert "was waiting for an OK before" in header and "is waiting" not in header
        assert not [c for c in notifier.tick() if c["kind"] == "gate_closed"]  # closed once

    def test_a_workflow_turned_off_gets_no_gate_notice(self, notifier, slack, ops, clock):
        ops.add_run("run-p", "slack_pick", "running", _minutes(1))
        ops.add_gate("ev-p", "run-p", "x", _minutes(2))
        clock.now = _minutes(3)
        assert notifier.tick() == [] and slack.posts == []


class TestEnds:
    def test_failed_goes_to_dm_and_channel_finished_to_channel(self, notifier, slack, ops, clock):
        ops.add_run("run-f", "trigger_probe", "failed", _minutes(1), _minutes(2), failure_summary="boom")
        ops.add_run("run-c", "trigger_probe", "completed", _minutes(1), _minutes(2), output="done")
        clock.now = _minutes(3)
        sent = {s["execution_id"]: s for s in notifier.tick()}
        assert sent["run-f"]["kind"] == "failed" and sent["run-c"]["kind"] == "finished"
        where = {(p["channel"], p["text"].split(" ")[0], p["text"].split(" ")[2]) for p in slack.posts}
        assert where == {(DM, "trigger_probe", "failed"), (RUNS, "trigger_probe", "failed"),
                         (RUNS, "trigger_probe", "completed")}
        failed = [p for p in slack.posts if "failed" in p["text"]]
        assert all(p["broadcast"] for p in failed) and "boom" in str(failed[0]["blocks"])
        assert notifier.tick() == []

    def test_per_workflow_off_and_quiet_workflows(self, notifier, slack, ops, clock):
        ops.add_run("run-n", "noisy", "completed", _minutes(1), _minutes(2))
        ops.add_run("run-p", "slack_pick", "failed", _minutes(1), _minutes(2))
        clock.now = _minutes(3)
        assert notifier.tick() == [] and slack.posts == []

    def test_a_resumed_run_that_ends_again_is_news_again(self, notifier, slack, ops, clock):
        ops.add_run("run-f", "trigger_probe", "failed", _minutes(1), _minutes(2))
        clock.now = _minutes(3)
        notifier.tick()
        ops.add_run("run-f", "trigger_probe", "failed", _minutes(1), _minutes(5))
        clock.now = _minutes(6)
        assert [s["kind"] for s in notifier.tick()] == ["failed"]
        dm_posts = [p for p in slack.posts if p["channel"] == DM]
        assert dm_posts[1]["thread_ts"] == dm_posts[0]["ts"]

    def test_a_run_started_from_slack_hears_back_in_its_thread(self, notifier, slack, ops, clock):
        ops.add_run("run-s", "noisy", "completed", _minutes(1), _minutes(2))
        store.save_thread("run-s", "C0ASKED01", "1790000000.999999", origin=True)
        clock.now = _minutes(3)
        notifier.tick()
        assert [(p["channel"], p["thread_ts"]) for p in slack.posts] == [("C0ASKED01", "1790000000.999999")]

    def test_a_run_stopped_from_slack_says_who_stopped_it(self, notifier, slack, ops, clock):
        # The stop kills the running step, whose error would otherwise read as
        # the reason the run ended.
        ops.add_run("run-x", "trigger_probe", "cancelled", _minutes(1), _minutes(2),
                    failure_summary="failed at nap: killed")
        store.log_action(OWNER, "shine", "stop", "run-x", "from Slack")
        clock.now = _minutes(3)
        notifier.tick()
        body = str(slack.posts[0]["blocks"])
        assert f"Stopped in Slack by <@{OWNER}>" in body and "killed" not in body

    def test_a_run_cancelled_elsewhere_names_no_one(self, notifier, slack, ops, clock):
        ops.add_run("run-y", "trigger_probe", "cancelled", _minutes(1), _minutes(2))
        clock.now = _minutes(3)
        notifier.tick()
        assert "Stopped in Slack" not in str(slack.posts[0]["blocks"])

    def test_one_bad_channel_does_not_stop_the_dm(self, notifier, slack, ops, clock):
        slack.forbidden.add(RUNS)
        ops.add_run("run-f", "trigger_probe", "failed", _minutes(1), _minutes(2))
        clock.now = _minutes(3)
        sent = notifier.tick()[0]
        assert [c for c, _ in sent["posted"]] == [DM]
        assert "not_in_channel" in sent["errors"][0]


class TestFailureReason:
    """The run's own error only counts failed steps; the step's agent holds
    the sentence that says what went wrong."""

    def test_the_failed_steps_own_error_replaces_the_count(self, monkeypatch):
        from temper_ai.api import data_service
        from temper_ai.integrations.slack.ops import TemperOps
        from temper_ai.mcp.tools import TemperTools

        monkeypatch.setattr(TemperTools, "get_run", lambda self, eid, max_chars=2000: {
            "status": "failed", "failure_summary": "1 node(s) failed: nap"})
        monkeypatch.setattr(data_service, "get_workflow_execution", lambda eid: {"nodes": [
            {"name": "ok", "status": "completed"},
            {"name": "outer", "status": "failed", "child_nodes": [
                {"name": "nap", "status": "failed",
                 "agent": {"error_message": "Command timed out after 5s"}}]},
        ]})
        summary = TemperOps().summary("run-1")
        assert "failed at nap: Command timed out after 5s" in summary["failure_summary"]
        assert "1 node(s) failed" not in summary["failure_summary"]

    def test_a_run_that_did_not_fail_keeps_its_summary(self, monkeypatch):
        from temper_ai.api import data_service
        from temper_ai.integrations.slack.ops import TemperOps
        from temper_ai.mcp.tools import TemperTools

        monkeypatch.setattr(TemperTools, "get_run", lambda self, eid, max_chars=2000: {"status": "completed"})
        monkeypatch.setattr(data_service, "get_workflow_execution", lambda eid: {"nodes": []})
        assert "failure_summary" not in TemperOps().summary("run-2")


class TestStuck:
    def test_quiet_past_the_limit_posts_once_per_quiet_spell(self, notifier, slack, ops, clock):
        ops.add_run("run-q", "trigger_probe", "running", _minutes(1))
        ops.activity["run-q"] = _minutes(1)
        clock.now = _minutes(20)
        assert notifier.tick() == []
        clock.now = _minutes(35)
        sent = notifier.tick()
        assert [s["kind"] for s in sent] == ["stuck"]
        post = slack.posts[0]
        assert "quiet for 34 min" in post["text"] and STOP in slack.buttons(post)
        clock.now = _minutes(50)
        assert notifier.tick() == []
        ops.activity["run-q"] = _minutes(55)  # it moved, then went quiet again
        clock.now = _minutes(90)
        assert [s["kind"] for s in notifier.tick()] == ["stuck"]

    def test_a_run_that_ends_takes_the_stop_button_off_its_quiet_notice(self, notifier, slack, ops, clock):
        ops.add_run("run-q", "trigger_probe", "running", _minutes(1))
        ops.activity["run-q"] = _minutes(1)
        clock.now = _minutes(35)
        notifier.tick()
        quiet = slack.posts[0]
        assert STOP in slack.buttons(quiet)
        ops.add_run("run-q", "trigger_probe", "completed", _minutes(1), _minutes(40))
        clock.now = _minutes(41)
        notifier.tick()
        closed = [u for u in slack.updates if u["ts"] == quiet["ts"]]
        assert closed and "went quiet, then ended completed" in closed[-1]["text"]
        assert not any(b.get("type") == "actions" for b in closed[-1]["blocks"])
        before = len(slack.updates)
        clock.now = _minutes(45)
        notifier.tick()
        assert len(slack.updates) == before  # closed once

    def test_runs_quiet_since_before_slack_was_on_are_left_alone(self, notifier, slack, ops, clock):
        ops.add_run("run-old", "trigger_probe", "running", T0 - timedelta(hours=3))
        ops.activity["run-old"] = T0 - timedelta(hours=3)
        clock.now = _minutes(5)
        assert notifier.tick() == []
