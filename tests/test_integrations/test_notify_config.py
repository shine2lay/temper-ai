"""The notify file, a workflow's own notify: block, and the Telegram file."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from temper_ai.integrations.notify.config import (
    ORIGIN,
    ConfigWatcher,
    NotifyConfigError,
    QuietHours,
    load_config,
    parse_block,
    parse_config,
)
from temper_ai.integrations.telegram.config import TelegramConfigError
from temper_ai.integrations.telegram.config import parse_config as parse_telegram

ROOT = Path(__file__).resolve().parents[2]

FILE = {
    "dashboard_url": "https://temper.test",
    "places": {
        "slack": {"slack": {"dm": "U0OWNER01"}},
        "runs": {"slack": {"channel": "C0RUNS001"}},
        "telegram": {"telegram": 8000000001},
        "team": {"telegram": -5000000001},
    },
    "defaults": {"question": ORIGIN, "failed": [ORIGIN, "telegram"]},
    "fallback": {"question": "slack", "failed": "slack", "finished": "runs", "stuck": "slack"},
    "workflows": {"slack_pick": "off", "nightly": {"finished": "team"}},
    "quiet_hours": {"from": "22:00", "to": "07:00", "zone": "America/Los_Angeles"},
    "nudge": {"after": "30m", "to": "telegram"},
    "agents": ["telegram", "team"],
}


def cfg():
    return parse_config({"notify": FILE})


class TestRoutes:
    def test_the_most_specific_setting_wins_one_kind_at_a_time(self):
        c = cfg()
        workflow_file = parse_block({"failed": "slack"})
        run = parse_block({"finished": "off"})
        assert c.route("question", "x") == (ORIGIN,)
        assert c.route("failed", "x") == (ORIGIN, "telegram")          # defaults
        assert c.route("finished", "nightly") == ("team",)             # this file, per workflow
        assert c.route("failed", "nightly", workflow_file) == ("slack",)  # the workflow file
        assert c.route("finished", "nightly", workflow_file, run) == ()   # the run's own
        assert c.route("stuck", "nightly", workflow_file, run) == (ORIGIN,)  # named nowhere
        assert all(c.route(k, "slack_pick") == () for k in ("question", "stuck", "failed", "finished"))

    def test_a_route_is_origin_a_place_a_list_or_off_and_never_an_id(self):
        assert parse_block({"question": [ORIGIN, "telegram", "telegram"]}).routes["question"] == (ORIGIN, "telegram")
        assert parse_block("off").routes == {k: () for k in ("question", "stuck", "failed", "finished")}
        for bad in ("U0OWNER01", "C0RUNS001", 8000000001, "#runs", {"dm": "U0OWNER01"}):
            with pytest.raises(NotifyConfigError, match="place name"):
                parse_block({"failed": bad})

    def test_links_and_agent_places(self):
        c = cfg()
        assert c.run_url("abc") == "https://temper.test/app/workflow/abc"
        assert sorted(c.agent_places("telegram")) == ["team", "telegram"] and c.agent_places("slack") == {}


class TestQuietAndNudge:
    def test_quiet_hours_cross_midnight_and_end_in_the_morning(self):
        quiet = cfg().quiet_hours("x")
        assert isinstance(quiet, QuietHours)
        night = datetime(2026, 9, 27, 6, 30, tzinfo=UTC)     # 23:30 PDT
        day = datetime(2026, 9, 26, 20, 0, tzinfo=UTC)       # 13:00 PDT
        assert quiet.covers(night) and not quiet.covers(day)
        assert quiet.holds("question", night) is None        # questions still ping
        until = quiet.holds("finished", night)
        assert until is not None and until.astimezone(UTC) == datetime(2026, 9, 27, 14, 0, tzinfo=UTC)
        assert quiet.holds("finished", day) is None

    def test_a_workflow_or_run_can_turn_them_off(self):
        c = cfg()
        off = parse_block({"quiet_hours": "off", "nudge": "off"})
        assert c.quiet_hours("x", off) is None and c.nudge("x", off) is None
        nudge = c.nudge("x")
        assert nudge is not None and nudge.after == timedelta(minutes=30) and nudge.to == ("telegram",)

    def test_an_unquoted_time_still_reads_right(self):
        # YAML 1.1 reads an unquoted 22:00 as 1320 (minutes).
        raw = yaml.safe_load("quiet_hours: {from: 22:00, to: 07:00}")
        block = parse_block(raw)
        assert isinstance(block.quiet_hours, QuietHours)
        assert f"{block.quiet_hours.start:%H:%M}-{block.quiet_hours.end:%H:%M}" == "22:00-07:00"

    @pytest.mark.parametrize("body,needle", [
        ({"quiet_hours": {"from": "22:00"}}, "needs both"),
        ({"quiet_hours": {"from": "25:00", "to": "07:00"}}, "not a time"),
        ({"quiet_hours": {"from": "22:00", "to": "07:00", "zone": "Mars/Base"}}, "time zone"),
        ({"quiet_hours": {"from": "22:00", "to": "07:00", "still_ping": ["done"]}}, "unknown kind"),
        ({"nudge": {"after": "30m"}}, "needs to"),
        ({"nudge": {"after": "30m", "to": ORIGIN}}, "somewhere else"),
        ({"nudge": {"after": "soon", "to": "slack"}}, "nudge.after"),
        ({"done": "slack"}, "unknown key"),
    ])
    def test_mistakes_are_named(self, body, needle):
        with pytest.raises(NotifyConfigError, match=needle):
            parse_block(body)


class TestTheFile:
    @pytest.mark.parametrize("change,needle", [
        ({"places": {"slack": {"slack": {"dm": "bob"}}}}, "user id"),
        ({"places": {"x": {"telegram": "@me"}}}, "chat id"),
        ({"places": {"x": {"email": "a@b"}}}, "unknown kind of place"),
        ({"places": {ORIGIN: {"telegram": 1}}}, "not origin"),
        ({"defaults": {"failed": "pager"}}, "no place named pager"),
        ({"workflows": {"w": {"nudge": {"after": "5m", "to": "pager"}}}}, "no place named pager"),
        ({"fallback": {"failed": ORIGIN}}, "no origin"),
        ({"fallback": {"done": "slack"}}, "unknown kind"),
        ({"agents": ["pager"]}, "no place named pager"),
        ({"dashboard_url": "temper.local"}, "dashboard_url"),
        ({"colour": "red"}, "unknown key"),
    ])
    def test_mistakes_are_named(self, change, needle):
        with pytest.raises(NotifyConfigError, match=needle):
            parse_config({"notify": {**FILE, **change}})

    def test_the_local_file_wins_and_a_broken_change_keeps_the_last_good_one(self, tmp_path):
        import os
        import time

        (tmp_path / "notify" / "local").mkdir(parents=True)
        (tmp_path / "notify" / "notify.yaml").write_text("notify:\n  defaults: {failed: off}\n")
        local = tmp_path / "notify" / "local" / "notify.yaml"
        local.write_text(yaml.safe_dump({"notify": FILE}))
        watcher = ConfigWatcher(tmp_path)
        assert watcher.get().path == str(local) and "telegram" in watcher.get().places

        local.write_text("notify:\n  places: {x: {telegram: nope}}\n")
        os.utime(local, (time.time() + 5, time.time() + 5))
        assert "telegram" in watcher.get().places
        assert watcher.error and "chat id" in watcher.error

    def test_no_file_sends_only_to_origin(self, tmp_path):
        c = load_config(tmp_path)
        assert c.places == {} and c.route("failed", "x") == (ORIGIN,) and c.fallback == {}

    def test_the_tracked_files_parse(self):
        tracked = parse_config(yaml.safe_load((ROOT / "configs/notify/notify.yaml").read_text()))
        assert tracked.places == {}
        assert all(tracked.route(k, "slack_pick") == () for k in ("question", "failed"))
        assert tracked.route("question", "repo_answer") == ()
        telegram = parse_telegram(yaml.safe_load((ROOT / "configs/telegram/telegram.yaml").read_text()))
        assert telegram.owners == frozenset() and telegram.zone


class TestWorkflowFiles:
    def test_a_bad_notify_block_fails_the_import(self, tmp_path):
        from temper_ai.config.helpers import ConfigValidationError
        from temper_ai.config.importer import parse_yaml

        path = tmp_path / "w.yaml"
        path.write_text("workflow:\n  name: w\n  notify: {failed: U0OWNER01}\n  nodes: []\n")
        with pytest.raises(ConfigValidationError, match="place name"):
            parse_yaml(path)
        path.write_text("workflow:\n  name: w\n  notify: {question: [origin, telegram], finished: off}\n"
                        "  nodes: []\n")
        assert parse_yaml(path)

    def test_the_probe_workflow_asks_three_kinds_of_question(self):
        raw = yaml.safe_load((ROOT / "configs/workflows/notify_probe.yaml").read_text())
        body = raw["workflow"]
        gates = [n for n in body["nodes"] if n.get("gate")]
        assert [g["name"] for g in gates] == ["decide"]
        ask = next(n for n in body["nodes"] if n["name"] == "ask")
        script = yaml.safe_load((ROOT / "configs/agents" / f"{ask['agent']}.yaml").read_text())
        text = str(script)
        assert "multi_select" in text and '"options"' in text and "Anything I should not touch" in text

    def test_every_workflow_names_only_places_the_tracked_file_or_origin_knows(self):
        from temper_ai.cli.notify_check import workflow_blocks

        for name, _path, raw in workflow_blocks(ROOT / "configs"):
            assert parse_block(raw, name).names() <= set(FILE["places"]), name


class TestTelegramFile:
    def test_owners_groups_and_zone(self):
        c = parse_telegram({"telegram": {"owners": [8000000001], "groups": ["-5000000001"], "zone": "Europe/Paris"}})
        assert c.owners == {8000000001} and c.groups == {-5000000001} and c.zone == "Europe/Paris"

    @pytest.mark.parametrize("body,needle", [
        ({"owners": ["me"]}, "not a Telegram id"),
        ({"groups": [5000000001]}, "negative"),
        ({"zone": "Mars/Base"}, "time zone"),
        ({"admins": [1]}, "unknown key"),
    ])
    def test_mistakes_are_named(self, body, needle):
        with pytest.raises(TelegramConfigError, match=needle):
            parse_telegram({"telegram": body})
