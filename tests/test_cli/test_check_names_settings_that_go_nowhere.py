"""`temper check` \u2014 a setting that is read and dropped must say so.

The `effort:` line went nowhere on the Claude Code provider for three months.
What made that possible was not the missing flag, which is one line, but that
nothing anywhere compared what a config asked for against what its provider
could do. These tests are about that comparison: it names the agent, it names
the provider, and it fails loudly enough to sit in a gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from temper_ai.cli.check import check, check_effort
from temper_ai.llm.effort import EFFORT_LEVELS, normalise, unhonoured


def _agent(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(body)
    return path


class TestAnEffortThatGoesNowhereIsNamed:
    def test_a_provider_without_an_effort_dial_is_reported(self, tmp_path):
        _agent(tmp_path, "thinker", """
agent:
  name: thinker
  type: llm
  provider: ollama
  provider_config:
    effort: high
""")
        seen, problems = check_effort(tmp_path)
        assert seen == 1
        assert len(problems) == 1
        # Both halves of the answer: who asked, and who cannot.
        assert "thinker" in problems[0]
        assert "ollama" in problems[0]
        assert "high" in problems[0]

    def test_a_provider_that_takes_it_is_not_reported(self, tmp_path):
        _agent(tmp_path, "thinker", """
agent:
  name: thinker
  type: llm
  provider: anthropic
  provider_config:
    effort: high
""")
        assert check_effort(tmp_path)[1] == []

    def test_an_agent_that_asks_for_nothing_is_not_reported(self, tmp_path):
        _agent(tmp_path, "plain", """
agent:
  name: plain
  type: llm
  provider: ollama
""")
        assert check_effort(tmp_path)[1] == []

    def test_a_level_only_the_cli_has_is_reported_on_the_api_provider(self, tmp_path):
        """`xhigh` is a CLI step with no API equivalent \u2014 asking for it there
        would arrive as something else, which is the silent drop again."""
        _agent(tmp_path, "over", """
agent:
  name: over
  type: llm
  provider: anthropic
  provider_config:
    effort: xhigh
""")
        problems = check_effort(tmp_path)[1]
        assert len(problems) == 1
        assert "xhigh" in problems[0]

    def test_a_fallback_entrys_effort_is_checked_too(self, tmp_path):
        """A fallback is where a run spends its hours once the first account
        is out; a setting dropped there is dropped where nobody is looking."""
        _agent(tmp_path, "failover", """
agent:
  name: failover
  type: llm
  provider: anthropic
  provider_config:
    effort: high
  fallback:
    - provider: ollama
      model: qwen
      provider_config:
        effort: high
""")
        problems = check_effort(tmp_path)[1]
        assert len(problems) == 1
        assert "ollama" in problems[0]

    def test_a_broken_yaml_does_not_hide_the_others(self, tmp_path):
        (tmp_path / "broken.yaml").write_text("agent: [unclosed\n")
        _agent(tmp_path, "thinker", """
agent:
  name: thinker
  type: llm
  provider: ollama
  provider_config:
    effort: max
""")
        assert len(check_effort(tmp_path)[1]) == 1

    def test_configs_are_found_in_subdirectories(self, tmp_path):
        nested = tmp_path / "agents" / "research"
        nested.mkdir(parents=True)
        (nested / "deep.yaml").write_text("""
agent:
  name: deep
  type: llm
  provider: ollama
  provider_config:
    effort: max
""")
        seen, problems = check_effort(tmp_path)
        assert seen == 1 and len(problems) == 1


class TestTheCommandItself:
    def test_it_fails_when_a_setting_goes_nowhere(self, tmp_path, capsys):
        _agent(tmp_path, "thinker", """
agent:
  name: thinker
  type: llm
  provider: ollama
  provider_config:
    effort: high
""")
        assert check(tmp_path) == 1
        out = capsys.readouterr().out
        assert "thinker" in out and "ollama" in out

    def test_it_passes_when_every_setting_lands(self, tmp_path, capsys):
        # `anthropic`, not `claude`: the CLI provider is installed per machine
        # (it lives in the gitignored local/ tree), so a test that named it
        # would pass here and fail in CI for a reason that has nothing to do
        # with what it is checking.
        _agent(tmp_path, "thinker", """
agent:
  name: thinker
  type: llm
  provider: anthropic
  provider_config:
    effort: high
""")
        assert check(tmp_path) == 0
        assert "every effort setting reaches" in capsys.readouterr().out

    def test_a_provider_this_install_does_not_have_is_said_out_loud(self, tmp_path, capsys):
        """Not the same as "no effort dial", and not something to pass over.

        Providers are installed per machine. A config aimed at one this install
        has never heard of cannot be checked either way, so the check says so
        and fails rather than reporting that all is well.
        """
        _agent(tmp_path, "thinker", """
agent:
  name: thinker
  type: llm
  provider: a_provider_nobody_installed
  provider_config:
    effort: max
""")
        assert check(tmp_path) == 1
        out = capsys.readouterr().out
        assert "not configured in this install" in out and "thinker" in out

    def test_it_says_what_each_provider_can_do(self, tmp_path, capsys):
        """So the answer to \"then where do I put this agent?\" is on screen."""
        check(tmp_path)
        out = capsys.readouterr().out
        assert "anthropic" in out and "low, medium, high, max" in out
        assert "no effort dial" in out  # and which ones have none


class TestTheEffortVocabulary:
    def test_the_levels_are_the_ones_the_cli_takes(self):
        assert EFFORT_LEVELS == ("low", "medium", "high", "xhigh", "max")

    @pytest.mark.parametrize("given,want", [
        ("HIGH", "high"), (" high ", "high"), (None, None), ("", None),
    ])
    def test_a_level_is_read_forgivingly(self, given, want):
        assert normalise(given) == want

    def test_a_typo_is_refused(self):
        with pytest.raises(ValueError, match="unknown effort"):
            normalise("higher")

    def test_the_message_says_what_the_provider_can_do_instead(self):
        message = unhonoured("anthropic", ("low", "medium", "high", "max"), "xhigh")
        assert "anthropic" in message and "low, medium, high, max" in message
