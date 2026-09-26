"""/temper parsing, input types, workflow search and the config file."""

from __future__ import annotations

import pytest

from temper_ai.config.search import search_workflows
from temper_ai.integrations.slack import blocks
from temper_ai.integrations.slack.commands import coerce_inputs, parse
from temper_ai.integrations.slack.config import (
    ConfigWatcher,
    SlackConfigError,
    config_path,
    load_config,
    parse_config,
)

from .conftest import OWNER


class TestParse:
    def test_run_with_inputs_quotes_and_smart_quotes(self):
        cmd = parse('run gate_demo topic=“weekly summary” rounds=2 note="a b"')
        assert (cmd.verb, cmd.workflow, cmd.error) == ("run", "gate_demo", "")
        assert cmd.inputs == {"topic": "weekly summary", "rounds": "2", "note": "a b"}

    def test_slack_links_become_plain_urls(self):
        cmd = parse("run fetch url=<https://example.com/a|example.com/a>")
        assert cmd.inputs == {"url": "https://example.com/a"}

    @pytest.mark.parametrize("text,verb", [("", "help"), ("help", "help"), ("ls", "list"), ("find pdf", "search"),
                                           ("runs", "status"), ("start x", "run"), ("cancel 3f2a9c1e", "stop")])
    def test_verbs_and_aliases(self, text, verb):
        assert parse(text).verb == verb

    def test_unknown_verb_is_help_with_the_word(self):
        cmd = parse("trigger_probe note=hi")
        assert cmd.verb == "help" and "don't know" in cmd.error and cmd.workflow == "trigger_probe"

    @pytest.mark.parametrize("text", ["run", "run wf note", "run wf a=1 a=2", "stop", "stop nope!", "search",
                                      "status a b", 'run wf note="open'])
    def test_mistakes_are_explained_not_run(self, text):
        assert parse(text).error

    def test_status_with_and_without_id(self):
        assert parse("status").run_id == ""
        assert parse("status 3F2A9C1E").run_id == "3f2a9c1e"

    def test_list_and_search_keep_their_words(self):
        assert parse("list linear").query == "linear"
        assert parse("search grade the plan").query == "grade the plan"


class TestCoerce:
    DECLARED = {"n": {"type": "integer", "required": True}, "on": {"type": "boolean"},
                "tags": {"type": "array"}, "cfg": {"type": "object"}, "name": {"type": "string"},
                "later": {"type": "string", "required": True, "default": "x"}}

    def test_types(self):
        out, problems = coerce_inputs({"n": "3", "on": "yes", "tags": "a, b", "cfg": '{"k": 1}', "name": "7"},
                                      self.DECLARED)
        assert problems == []
        assert out == {"n": 3, "on": True, "tags": ["a", "b"], "cfg": {"k": 1}, "name": "7"}

    def test_json_list(self):
        assert coerce_inputs({"n": "1", "tags": '["x", 2]'}, self.DECLARED)[0]["tags"] == ["x", 2]

    def test_problems_stop_the_start(self):
        _, problems = coerce_inputs({"n": "three", "on": "maybe", "typo": "1"}, self.DECLARED)
        text = " ".join(problems)
        assert "`n` should be integer" in text and "`on` should be boolean" in text and "`typo`" in text

    def test_missing_required_without_default(self):
        _, problems = coerce_inputs({}, self.DECLARED)
        assert problems == ["missing required input(s): `n`"]

    def test_workflow_with_no_declared_inputs_takes_anything(self):
        assert coerce_inputs({"x": "1"}, {}) == ({"x": "1"}, [])


ENTRIES = [
    {"name": "linear_reply", "description": "Answer a Linear issue with a comment.", "inputs": {}},
    {"name": "plan_grade", "description": "Grade a written plan against the rubric.",
     "inputs": {"issue": {"type": "string", "required": True, "description": "the Linear issue to read"}}},
    {"name": "summarise", "description": "", "inputs": {}},
]


class TestSearch:
    def test_name_hits_rank_first(self):
        names = [r["name"] for r in search_workflows("linear", entries=ENTRIES)["results"]]
        assert names == ["linear_reply", "plan_grade"]  # plan_grade only matches in an input description

    def test_description_words(self):
        found = search_workflows("grade my plan", entries=ENTRIES)
        assert found["results"][0]["name"] == "plan_grade" and found["results"][0]["matched"]

    def test_empty_query_lists_all_and_flags_undescribed(self):
        found = search_workflows("", entries=ENTRIES)
        assert [r["name"] for r in found["results"]] == ["linear_reply", "plan_grade", "summarise"]
        assert found["undescribed"] == ["summarise"] and found["total"] == 3

    def test_no_match(self):
        assert search_workflows("kubernetes", entries=ENTRIES)["results"] == []


class TestConfig:
    def test_routes_and_overrides(self, slack_config):
        cfg = load_config()
        assert cfg.route("gate", "anything").users == (OWNER,)
        assert cfg.route("finished", "noisy").channels == ()
        assert cfg.route("failed", "noisy").channels == ("C0RUNS001",)
        assert not cfg.route("gate", "slack_pick")
        assert cfg.run_url("abc") == "https://temper.test/app/workflow/abc"
        assert cfg.agent_may_post(OWNER) and cfg.agent_may_post("C0RUNS001") and not cfg.agent_may_post("C0OTHER01")

    @pytest.mark.parametrize("body,needle", [
        ({"notify": {"gate": {"dm": "bob"}}}, "user id"),
        ({"notify": {"gate": {"channel": "general"}}}, "channel id"),
        ({"notify": {"done": {"dm": OWNER}}}, "unknown kind"),
        ({"notify": {"gate": {"email": "a@b"}}}, "unknown key"),
        ({"stuck_after": "soon"}, "stuck_after"),
        ({"dashboard_url": "temper.local"}, "dashboard_url"),
        ({"colour": "red"}, "unknown key"),
    ])
    def test_mistakes_are_named(self, body, needle):
        with pytest.raises(SlackConfigError, match=needle):
            parse_config({"slack": body})

    def test_local_file_wins(self, tmp_path, slack_config):
        local = tmp_path / "slack" / "local"
        local.mkdir()
        (local / "slack.yaml").write_text("slack:\n  notify:\n    gate: off\n")
        assert config_path() == local / "slack.yaml"
        assert not load_config().route("gate", "x")

    def test_watcher_keeps_the_last_good_config(self, tmp_path, slack_config):
        watcher = ConfigWatcher()
        assert watcher.get().route("gate", "x").users == (OWNER,)
        import os
        import time

        path = tmp_path / "slack" / "slack.yaml"
        path.write_text("slack:\n  notify:\n    gate: {dm: nobody}\n")
        os.utime(path, (time.time() + 5, time.time() + 5))
        assert watcher.get().route("gate", "x").users == (OWNER,)
        assert watcher.error and "user id" in watcher.error

    def test_no_file_sends_nothing(self, tmp_path, monkeypatch):
        from temper_ai.integrations.slack import config as config_mod

        monkeypatch.setattr(config_mod, "default_config_dir", lambda: tmp_path)
        assert config_path() is None and not load_config().route("failed", "x")

    def test_the_tracked_file_parses_and_sends_nothing(self):
        from pathlib import Path

        import yaml

        tracked = Path(__file__).resolve().parents[2] / "configs" / "slack" / "slack.yaml"
        cfg = parse_config(yaml.safe_load(tracked.read_text()))
        assert not any(cfg.route(k, "x") for k in ("gate", "stuck", "failed", "finished"))


class TestHowRunsRead:
    """Small wording rules found by reading the messages in Slack."""

    def test_a_run_under_a_second_is_not_0s(self):
        assert blocks.duration(0.4) == "under 1s" and blocks.duration(75) == "1m 15s"

    def test_a_run_with_no_model_calls_shows_no_cost(self):
        assert blocks.cost(0) == "" and blocks.cost(0.004) == "$0.0040" and blocks.cost(1.5) == "$1.50"

    def test_a_wrapped_description_is_cut_at_a_sentence_or_a_whole_word(self):
        # Under the limit, a description that YAML wrapped comes back whole, on one line.
        wrapped = "Audit fixture (2026-09-13). Structured output, condition\n  branching, field-level input_map."
        assert blocks.gist(wrapped) == \
            "Audit fixture (2026-09-13). Structured output, condition branching, field-level input_map."
        one_sentence = "word " * 60
        cut = blocks.gist(one_sentence)
        assert cut.endswith("word…") and len(cut) <= 161
        assert blocks.gist("First sentence is long enough to stop at here. " + "x " * 80) == \
            "First sentence is long enough to stop at here."
        assert blocks.gist(None) == ""
