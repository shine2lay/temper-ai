"""The notify loop: which questions and notices go where (origin, a
workflow's own ``notify:``, the fallback), sent once each, held in quiet
hours, nudged, and closed everywhere once answered."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from temper_ai.integrations.notify import store as notify_store
from temper_ai.integrations.notify.config import ConfigWatcher, parse_block
from temper_ai.integrations.notify.loop import Notifier
from temper_ai.integrations.slack import store
from temper_ai.integrations.slack.blocks import APPROVE, REJECT, STOP
from temper_ai.integrations.slack.sender import SlackSender
from temper_ai.integrations.telegram import store as tg_store
from temper_ai.integrations.telegram.config import ConfigWatcher as TelegramConfig
from temper_ai.integrations.telegram.sender import TelegramSender

from .conftest import NOTIFY_YAML, OWNER, TG_GROUP, TG_OWNER, FakeTelegram

# 12:00 UTC is 5 AM in Los Angeles.
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


def make_notifier(slack, telegram, ops, clock) -> Notifier:
    n = Notifier(ConfigWatcher(), ops, clock=clock)
    n.register(SlackSender(slack))
    n.register(TelegramSender(telegram, TelegramConfig()))  # type: ignore[arg-type]
    return n


@pytest.fixture
def notifier(slack, telegram, ops, notify_config, clock) -> Notifier:
    n = make_notifier(slack, telegram, ops, clock)
    assert n.tick() == []  # switching on: records "notices are on from now"
    return n


def _minutes(n: int) -> datetime:
    return T0 + timedelta(minutes=n)


def gate(ops, eid: str = "run-1", event: str = "ev-1", at: int = 2, workflow: str = "gate_demo",
         node: str = "approve_step") -> None:
    ops.add_run(eid, workflow, "running", _minutes(1))
    ops.alive.add(eid)
    ops.add_gate(event, eid, node, _minutes(at),
                 questions=[{"id": "q1", "question": "Which one?", "options": [{"label": "A"}, {"label": "B"}]}])


def slack_sent(slack) -> list[tuple[str, str]]:
    return [(p["channel"], p["text"]) for p in slack.posts]


class TestQuestions:
    def test_a_question_with_no_origin_goes_to_the_fallback_once(self, notifier, slack, telegram, ops, clock):
        gate(ops)
        clock.now = _minutes(3)
        sent = notifier.tick()
        assert [(s["kind"], s["via"], s["target"]) for s in sent] == [("question", "slack", DM)]
        post = slack.posts[0]
        assert post["channel"] == DM and "approve_step" in post["text"]
        assert slack.buttons(post)[:3] == ["gate_answer", APPROVE, REJECT]
        assert telegram.sent == []
        assert notifier.tick() == [] and len(slack.posts) == 1

    def test_the_same_node_gating_again_is_a_new_notice_in_the_same_thread(self, notifier, slack, ops, clock):
        gate(ops)
        clock.now = _minutes(3)
        notifier.tick()
        ops.approve("run-1", "approve_step")
        ops.add_gate("ev-2", "run-1", "approve_step", _minutes(4))
        clock.now = _minutes(5)
        notifier.tick()
        asks = [p for p in slack.posts if "approve_step" in p["text"]]
        assert len(asks) == 2
        assert asks[1]["thread_ts"] == asks[0]["ts"]

    def test_questions_from_before_notices_were_on_are_history(self, slack, telegram, ops, notify_config, clock):
        ops.add_run("old", "gate_demo", "running", T0 - timedelta(hours=2))
        ops.add_gate("ev-old", "old", "approve_step", T0 - timedelta(hours=1))
        n = make_notifier(slack, telegram, ops, clock)
        assert n.tick() == [] and slack.posts == []

    def test_a_question_answered_in_the_dashboard_closes_everywhere(self, notifier, slack, telegram, ops, clock):
        gate(ops)
        notify_store.save_run_settings("run-1", {"question": ["slack", "telegram"]})
        clock.now = _minutes(3)
        assert len(notifier.tick()) == 2
        ops.approve("run-1", "approve_step", by="Shine")   # clicked in temper's dashboard
        clock.now = _minutes(4)
        closed = notifier.tick()
        assert {"kind": "question_closed", "execution_id": "run-1", "verdict": "approved"} in closed
        update = slack.updates[-1]
        assert update["ts"] == slack.posts[0]["ts"] and "Approved by Shine in temper" in str(update["blocks"])
        assert not any(b.get("type") == "actions" for b in update["blocks"])
        header = update["blocks"][0]["text"]["text"]
        assert "was waiting for an OK before" in header and "is waiting" not in header
        edit = telegram.edits[-1]
        assert edit["message_id"] == telegram.sent[0]["message_id"]
        assert "Approved by Shine in temper" in edit["text"]
        assert all("callback_data" not in b for row in edit["keyboard"] or [] for b in row)
        assert not [c for c in notifier.tick() if c["kind"] == "question_closed"]  # closed once

    def test_a_workflow_turned_off_gets_no_question(self, notifier, slack, ops, clock):
        gate(ops, "run-p", "ev-p", workflow="slack_pick")
        clock.now = _minutes(3)
        assert notifier.tick() == [] and slack.posts == []


class TestWhere:
    def test_a_run_started_from_telegram_is_asked_there_and_nowhere_else(self, notifier, slack, telegram,
                                                                          ops, clock):
        gate(ops)
        tg_store.save_thread("run-1", TG_OWNER, 55, origin=True)
        clock.now = _minutes(3)
        sent = notifier.tick()
        assert [(s["via"], s["target"]) for s in sent] == [("telegram", str(TG_OWNER))]
        msg = telegram.sent[0]
        assert msg["chat"] == TG_OWNER and msg["reply_to"] == 55
        assert "waiting for your OK before <b>approve_step</b>" in msg["text"]
        labels = [label for label, _ in telegram.buttons(msg["keyboard"])]
        assert labels[:2] == ["A", "B"] and "✅ Approve" in labels and "⛔ Reject" in labels
        assert slack.posts == []

    def test_a_run_started_from_slack_hears_back_in_its_thread(self, notifier, slack, telegram, ops, clock):
        ops.add_run("run-s", "noisy2", "completed", _minutes(1), _minutes(2))
        store.save_thread("run-s", "C0ASKED01", "1790000000.999999", origin=True)
        clock.now = _minutes(3)
        notifier.tick()
        assert [(p["channel"], p["thread_ts"]) for p in slack.posts] == [("C0ASKED01", "1790000000.999999")]
        assert telegram.sent == []

    def test_the_workflow_file_decides(self, notifier, slack, telegram, ops, clock, monkeypatch):
        block = parse_block({"question": ["origin", "telegram"], "failed": "telegram", "finished": "slack"})
        monkeypatch.setattr(notifier, "workflow_block", lambda wf: block if wf == "picky" else None)
        gate(ops, "run-q", "ev-q", workflow="picky")
        ops.add_run("run-f", "picky", "failed", _minutes(1), _minutes(2), failure_summary="boom")
        ops.add_run("run-c", "picky", "completed", _minutes(1), _minutes(2))
        clock.now = _minutes(3)
        sent = {(s["execution_id"], s["via"], s["target"]) for s in notifier.tick()}
        assert sent == {("run-q", "telegram", str(TG_OWNER)), ("run-f", "telegram", str(TG_OWNER)),
                        ("run-c", "slack", DM)}

    def test_a_runs_own_setting_beats_the_workflow_file(self, notifier, slack, telegram, ops, clock, monkeypatch):
        monkeypatch.setattr(notifier, "workflow_block", lambda wf: parse_block({"finished": "slack"}))
        ops.add_run("run-c", "picky", "completed", _minutes(1), _minutes(2))
        notify_store.save_run_settings("run-c", {"finished": "qa-group"})
        clock.now = _minutes(3)
        assert [(s["via"], s["target"]) for s in notifier.tick()] == [("telegram", str(TG_GROUP))]

    def test_one_place_named_twice_gets_one_message(self, notifier, slack, telegram, ops, clock):
        gate(ops)
        tg_store.save_thread("run-1", TG_OWNER, 55, origin=True)
        notify_store.save_run_settings("run-1", {"question": ["origin", "telegram", "slack", "slack"]})
        clock.now = _minutes(3)
        sent = notifier.tick()
        assert sorted((s["via"], s["target"]) for s in sent) == [("slack", DM), ("telegram", str(TG_OWNER))]
        assert len(telegram.sent) == 1 and len(slack.posts) == 1

    def test_off_for_one_run(self, notifier, slack, ops, clock):
        ops.add_run("run-c", "trigger_probe", "completed", _minutes(1), _minutes(2))
        notify_store.save_run_settings("run-c", {"question": [], "stuck": [], "failed": [], "finished": []})
        clock.now = _minutes(3)
        assert notifier.tick() == [] and slack.posts == []


class TestEnds:
    def test_failed_goes_to_dm_and_channel_finished_to_channel(self, notifier, slack, ops, clock):
        ops.add_run("run-f", "trigger_probe", "failed", _minutes(1), _minutes(2), failure_summary="boom")
        ops.add_run("run-c", "trigger_probe", "completed", _minutes(1), _minutes(2), output="done")
        clock.now = _minutes(3)
        sent = notifier.tick()
        assert sorted((s["execution_id"], s["kind"], s["target"]) for s in sent) == [
            ("run-c", "finished", RUNS), ("run-f", "failed", RUNS), ("run-f", "failed", DM)]
        failed = [p for p in slack.posts if "failed" in p["text"]]
        assert "boom" in str(failed[0]["blocks"])
        assert notifier.tick() == []

    def test_a_run_resumed_after_a_restart_is_not_failed(self, notifier, slack, ops, clock):
        # A restart marks the waiting run interrupted; it is resumed a moment later.
        ops.add_run("run-r", "trigger_probe", "interrupted", _minutes(1))
        clock.now = _minutes(2)
        assert notifier.tick() == []
        ops.add_run("run-r", "trigger_probe", "running", _minutes(2))
        clock.now = _minutes(10)
        assert notifier.tick() == [] and slack.posts == []

    def test_a_run_still_interrupted_after_a_while_failed(self, notifier, slack, ops, clock):
        ops.add_run("run-i", "trigger_probe", "interrupted", _minutes(1))
        clock.now = _minutes(2)
        assert notifier.tick() == []
        clock.now = _minutes(6)
        assert notifier.tick() == []
        clock.now = _minutes(7)
        sent = notifier.tick()
        assert sorted((s["execution_id"], s["kind"]) for s in sent) == [("run-i", "failed"), ("run-i", "failed")]
        assert notifier.tick() == []

    def test_per_workflow_off_and_quiet_workflows(self, notifier, slack, ops, clock):
        ops.add_run("run-n", "noisy", "completed", _minutes(1), _minutes(2))
        ops.add_run("run-p", "slack_pick", "failed", _minutes(1), _minutes(2))
        ops.add_run("run-a", "repo_answer", "completed", _minutes(1), _minutes(2))
        clock.now = _minutes(3)
        assert notifier.tick() == [] and slack.posts == []

    def test_a_resumed_run_that_ends_again_is_news_again(self, notifier, slack, ops, clock):
        ops.add_run("run-f", "trigger_probe", "failed", _minutes(1), _minutes(2))
        clock.now = _minutes(3)
        notifier.tick()
        ops.add_run("run-f", "trigger_probe", "failed", _minutes(1), _minutes(5))
        clock.now = _minutes(6)
        assert {s["kind"] for s in notifier.tick()} == {"failed"}
        dm_posts = [p for p in slack.posts if p["channel"] == DM]
        assert dm_posts[1]["thread_ts"] == dm_posts[0]["ts"]

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

    def test_a_run_stopped_from_telegram_says_who_stopped_it(self, notifier, slack, telegram, ops, clock):
        ops.add_run("run-x", "trigger_probe", "cancelled", _minutes(1), _minutes(2))
        tg_store.save_thread("run-x", TG_OWNER, 77, origin=True)
        tg_store.log_action(TG_OWNER, "Shine", "stop", "run-x", "from Telegram")
        clock.now = _minutes(3)
        notifier.tick()
        assert "Stopped in Telegram by Shine" in telegram.sent[0]["text"]
        assert telegram.sent[0]["quiet"] is True    # a finished run makes no sound

    def test_a_run_cancelled_elsewhere_names_no_one(self, notifier, slack, ops, clock):
        ops.add_run("run-y", "trigger_probe", "cancelled", _minutes(1), _minutes(2))
        clock.now = _minutes(3)
        notifier.tick()
        assert "Stopped in" not in str(slack.posts[0]["blocks"])

    def test_one_bad_channel_does_not_stop_the_dm(self, notifier, slack, ops, clock):
        slack.forbidden.add(RUNS)
        ops.add_run("run-f", "trigger_probe", "failed", _minutes(1), _minutes(2))
        clock.now = _minutes(3)
        sent = {s["target"]: s for s in notifier.tick()}
        assert "ref" in sent[DM] and "not_in_channel" in sent[RUNS]["error"]
        assert notify_store.copies(execution_id="run-f", statuses=("failed",))[0].target == RUNS


class TestQuietHours:
    QUIET = NOTIFY_YAML.replace(
        "  agents: [telegram]",
        '  quiet_hours: {from: "22:00", to: "07:00", zone: America/Los_Angeles}\n  agents: [telegram]')

    def test_a_finished_notice_waits_for_the_morning_but_a_question_still_pings(
            self, notifier, notify_config, slack, ops, clock):
        notify_config(self.QUIET)
        ops.add_run("run-c", "trigger_probe", "completed", _minutes(1), _minutes(2))
        gate(ops)
        clock.now = _minutes(3)                      # 5:03 AM in Los Angeles
        sent = notifier.tick()
        held = [s for s in sent if "held_until" in s]
        assert [(s["kind"], s["target"]) for s in held] == [("finished", RUNS)]
        assert held[0]["held_until"].startswith("2026-09-26T07:00:00-07:00")
        assert [p["channel"] for p in slack.posts] == [DM]           # only the question
        clock.now = _minutes(90)                     # 6:30: still quiet
        assert notifier.tick() == []
        clock.now = datetime(2026, 9, 26, 14, 1, tzinfo=UTC)          # 7:01
        released = notifier.tick()
        assert [(s["kind"], s["target"]) for s in released if "ref" in s] == [("finished", RUNS)]
        assert notifier.tick() == []

    def test_a_workflow_can_turn_quiet_hours_off(self, notifier, notify_config, slack, ops, clock, monkeypatch):
        notify_config(self.QUIET)
        monkeypatch.setattr(notifier, "workflow_block", lambda wf: parse_block({"quiet_hours": "off"}))
        ops.add_run("run-c", "urgent", "completed", _minutes(1), _minutes(2))
        clock.now = _minutes(3)
        assert [s["target"] for s in notifier.tick() if "ref" in s] == [RUNS]

    def test_a_question_answered_while_held_is_never_sent(self, notifier, notify_config, slack, ops, clock):
        notify_config(self.QUIET.replace("zone: America/Los_Angeles}", "zone: America/Los_Angeles, still_ping: []}"))
        gate(ops)
        clock.now = _minutes(3)
        assert [s["kind"] for s in notifier.tick() if "held_until" in s] == ["question"]
        ops.approve("run-1", "approve_step")
        notifier.tick()
        ops.activity["run-1"] = datetime(2026, 9, 26, 14, 0, tzinfo=UTC)   # the run went on
        clock.now = datetime(2026, 9, 26, 14, 1, tzinfo=UTC)
        notifier.tick()
        assert slack.posts == []
        assert notify_store.copies(execution_id="run-1", statuses=("closed",))[0].kind == "question"


class TestNudges:
    NUDGE = NOTIFY_YAML.replace("  agents: [telegram]", "  nudge: {after: 2m, to: telegram}\n  agents: [telegram]")

    def test_an_unanswered_question_is_sent_once_more_and_closed_everywhere(
            self, notifier, notify_config, slack, telegram, ops, clock):
        notify_config(self.NUDGE)
        gate(ops)
        clock.now = _minutes(3)
        notifier.tick()
        assert len(slack.posts) == 1 and telegram.sent == []
        clock.now = _minutes(4)
        assert notifier.tick() == []                  # not yet 2 minutes
        clock.now = _minutes(6)
        nudged = notifier.tick()
        assert [(s["via"], s["target"]) for s in nudged] == [("telegram", str(TG_OWNER))]
        assert "Nobody has answered this for 2 min" in telegram.sent[0]["text"]
        clock.now = _minutes(20)
        assert notifier.tick() == []                  # once
        ops.approve("run-1", "approve_step", by="Shine (Telegram)")
        notifier.tick()
        assert "Approved by Shine in Telegram" in str(slack.updates[-1]["blocks"])
        assert "Approved by Shine in Telegram" in telegram.edits[-1]["text"]

    def test_no_nudge_once_answered(self, notifier, notify_config, telegram, ops, clock):
        notify_config(self.NUDGE)
        gate(ops)
        clock.now = _minutes(3)
        notifier.tick()
        ops.approve("run-1", "approve_step")
        clock.now = _minutes(10)
        notifier.tick()
        assert telegram.sent == []


class TestRestart:
    def test_a_new_server_sends_nothing_twice(self, notifier, slack, telegram, ops, clock):
        gate(ops)
        ops.add_run("run-f", "trigger_probe", "failed", _minutes(1), _minutes(2))
        clock.now = _minutes(3)
        first = notifier.tick()
        assert len(first) == 3
        again = make_notifier(slack, telegram, ops, clock)   # the server restarted
        clock.now = _minutes(4)
        assert again.tick() == [] and len(slack.posts) == 3

    def test_a_question_answered_while_down_is_closed_when_it_comes_back(self, notifier, slack, telegram,
                                                                          ops, clock):
        gate(ops)
        clock.now = _minutes(3)
        notifier.tick()
        ops.approve("run-1", "approve_step", by="Shine")
        again = make_notifier(slack, telegram, ops, clock)
        clock.now = _minutes(30)
        assert [c["kind"] for c in again.tick()] == ["question_closed"]
        assert "Approved by Shine" in str(slack.updates[-1]["blocks"])

    def test_a_resumed_run_asking_again_keeps_its_message(self, notifier, slack, ops, clock):
        gate(ops)
        clock.now = _minutes(3)
        notifier.tick()
        # After a restart the run is resumed and waits at the same step again,
        # as a new event (the old one was never answered): its message now
        # answers that one.
        ops.gates.clear()
        ops.add_gate("ev-1b", "run-1", "approve_step", _minutes(10))
        clock.now = _minutes(11)
        assert notifier.tick() == [] and len(slack.posts) == 1
        (copy,) = notify_store.copies(execution_id="run-1", kind="question")
        assert copy.event_id == "ev-1b" and copy.key == "q:ev-1b"


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

    def test_a_run_that_ends_takes_the_stop_button_off_its_quiet_notice(self, notifier, slack, telegram,
                                                                         ops, clock):
        ops.add_run("run-q", "trigger_probe", "running", _minutes(1))
        ops.activity["run-q"] = _minutes(1)
        notify_store.save_run_settings("run-q", {"stuck": ["slack", "telegram"], "finished": "off"})
        clock.now = _minutes(35)
        notifier.tick()
        quiet = slack.posts[0]
        assert STOP in slack.buttons(quiet)
        assert any(label.startswith("⏹") for label, _ in FakeTelegram.buttons(telegram.sent[0]["keyboard"]))
        ops.add_run("run-q", "trigger_probe", "completed", _minutes(1), _minutes(40))
        clock.now = _minutes(41)
        notifier.tick()
        closed = [u for u in slack.updates if u["ts"] == quiet["ts"]]
        assert closed and "went quiet, then ended (completed)" in closed[-1]["text"]
        assert not any(b.get("type") == "actions" for b in closed[-1]["blocks"])
        assert "it has since ended" in telegram.edits[-1]["text"]
        before = len(slack.updates)
        clock.now = _minutes(45)
        notifier.tick()
        assert len(slack.updates) == before  # closed once

    def test_runs_quiet_since_before_notices_were_on_are_left_alone(self, notifier, slack, ops, clock):
        ops.add_run("run-old", "trigger_probe", "running", T0 - timedelta(hours=3))
        ops.activity["run-old"] = T0 - timedelta(hours=3)
        clock.now = _minutes(5)
        assert notifier.tick() == []

    def test_a_second_check_over_the_same_quiet_run_says_nothing_again(self, notifier, slack, ops, clock):
        """A quiet run stays quiet; asking again must not ask again."""
        ops.add_run("run-q", "trigger_probe", "running", _minutes(1))
        ops.activity["run-q"] = _minutes(1)
        clock.now = _minutes(35)
        assert [s["kind"] for s in notifier.tick()] == ["stuck"]
        for later in (36, 40, 120):
            clock.now = _minutes(later)
            assert notifier.tick() == []
        assert len(slack.posts) == 1

    def test_a_run_that_comes_back_to_life_clears_the_mark(self, notifier, slack, ops, clock):
        """New activity ends the quiet spell: nothing is repeated about it."""
        ops.add_run("run-q", "trigger_probe", "running", _minutes(1))
        ops.activity["run-q"] = _minutes(1)
        clock.now = _minutes(35)
        assert [s["kind"] for s in notifier.tick()] == ["stuck"]
        ops.activity["run-q"] = _minutes(36)      # it moved again by itself
        clock.now = _minutes(40)
        assert notifier.tick() == []
        assert len(slack.posts) == 1

    def test_a_workflow_may_ask_to_be_left_quiet_for_longer(self, notifier, slack, ops, clock):
        """``quiet_after`` in the workflow: a long step is normal for this one."""
        from temper_ai.config.store import ConfigStore
        from temper_ai.runner import quiet as quiet_rule

        ConfigStore().put("slow_build", "workflow",
                          {"name": "slow_build", "quiet_after": "2h", "nodes": []})
        quiet_rule.forget_thresholds()
        ops.add_run("run-slow", "slow_build", "running", _minutes(1))
        ops.activity["run-slow"] = _minutes(1)
        clock.now = _minutes(50)            # past the shared 45m, inside its own 2h
        assert notifier.tick() == []
        clock.now = _minutes(130)
        assert [s["kind"] for s in notifier.tick()] == ["stuck"]

    def test_a_workflow_may_ask_to_be_chased_sooner(self, notifier, slack, ops, clock):
        from temper_ai.config.store import ConfigStore
        from temper_ai.runner import quiet as quiet_rule

        ConfigStore().put("brisk", "workflow", {"name": "brisk", "quiet_after": "5m", "nodes": []})
        quiet_rule.forget_thresholds()
        ops.add_run("run-brisk", "brisk", "running", _minutes(1))
        ops.activity["run-brisk"] = _minutes(1)
        clock.now = _minutes(10)            # nowhere near the shared 45m
        assert [s["kind"] for s in notifier.tick()] == ["stuck"]

    def test_a_run_waiting_on_a_person_is_never_called_quiet(self, notifier, slack, ops, clock):
        """Ten hours at a gate is the run doing its job, not a run gone quiet."""
        gate(ops, eid="run-gate", event="ev-gate", at=1)
        clock.now = _minutes(600)
        kinds = [s["kind"] for s in notifier.tick()]
        assert "stuck" not in kinds
