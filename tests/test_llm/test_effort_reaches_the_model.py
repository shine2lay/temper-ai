"""An `effort:` line in an agent config has to reach the model.

For three months it did not. The Claude Code CLI has taken `--effort` for a
while, temper never passed it, and twenty agent configs asked for thinking that
was never requested: of ~52,900 model calls in thirty days, not one carried any
thinking text. Nothing failed, nothing warned; the setting simply was not a
setting.

So these tests are about the wire, not the intention: what the command line
says, what comes back out of a response, and \u2014 for a provider that cannot ask
for it \u2014 whether anyone is told.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

claude_code = pytest.importorskip(
    "local.providers.claude_code",
    reason="local/ provider is gitignored; present only in a working checkout",
)


def _command(monkeypatch, **provider_kwargs) -> list[str]:
    """The argv `complete()` would run, without running it.

    The CLI call is replaced at `subprocess.run`, which is the last point
    before the process exists: what is asserted is exactly what the tool would
    have been given.
    """
    seen: dict[str, list[str]] = {}

    def fake_run(cmd, **_kwargs):
        seen["cmd"] = list(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")

    monkeypatch.setattr(claude_code.subprocess, "run", fake_run)
    provider = claude_code.ClaudeCodeLLM(**provider_kwargs)
    provider.complete([{"role": "user", "content": "hi"}])
    return seen["cmd"]


class TestTheEffortSettingReachesTheCli:
    def test_the_configured_effort_is_on_the_command_line(self, monkeypatch):
        cmd = _command(monkeypatch, effort="high")
        assert "--effort" in cmd
        assert cmd[cmd.index("--effort") + 1] == "high"

    @pytest.mark.parametrize("level", ["low", "medium", "high", "xhigh", "max"])
    def test_every_level_the_cli_takes_is_passed_as_it_stands(self, monkeypatch, level):
        """temper's names and the CLI's are the same five words \u2014 no mapping to get wrong."""
        cmd = _command(monkeypatch, effort=level)
        assert cmd[cmd.index("--effort") + 1] == level

    def test_an_agent_that_asks_for_nothing_is_left_alone(self, monkeypatch):
        """No default, no extra spend: thinking is billed as output."""
        assert "--effort" not in _command(monkeypatch)

    def test_a_per_call_effort_beats_the_providers_own(self, monkeypatch):
        """A node's override is more specific than the process it runs in."""
        seen: dict[str, list[str]] = {}

        def fake_run(cmd, **_kwargs):
            seen["cmd"] = list(cmd)
            return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")

        monkeypatch.setattr(claude_code.subprocess, "run", fake_run)
        provider = claude_code.ClaudeCodeLLM(effort="low")
        provider.complete([{"role": "user", "content": "hi"}], effort="max")
        assert seen["cmd"][seen["cmd"].index("--effort") + 1] == "max"

    def test_a_typo_is_refused_rather_than_sent(self):
        """`effort: hihg` reaching the CLI would be a 2-minute failure per call."""
        with pytest.raises(ValueError, match="unknown effort"):
            claude_code.ClaudeCodeLLM(effort="hihg")

    def test_the_streaming_path_passes_it_too(self, monkeypatch):
        """A run's thinking cannot depend on whether anyone was watching."""
        provider = claude_code.ClaudeCodeLLM(effort="medium")
        assert provider._effort_args({}) == ["--effort", "medium"]
        assert provider._effort_args({"effort": "xhigh"}) == ["--effort", "xhigh"]


class TestThinkingComesBackFromACallNobodyWatched:
    """The non-streaming path recorded no thinking at all.

    `--output-format json` carries the answer and the bill and nothing else,
    so an agent that thought for a minute left no trace of it unless the run
    happened to be streamed. The stream's own format has the same result
    object as its last line, with the thinking blocks before it.
    """

    def _stream(self, *events: dict) -> str:
        return "\n".join(json.dumps(e) for e in events)

    def test_thinking_blocks_are_kept_with_the_answer(self):
        raw = self._stream(
            {"type": "assistant", "message": {"content": [
                {"type": "thinking", "thinking": "The config sets effort but the flag is missing."},
                {"type": "text", "text": "Fixed it."},
            ]}},
            {"type": "result", "result": "Fixed it.", "usage": {"output_tokens": 12}},
        )
        response = claude_code._parse_cli_output(raw, "sonnet")
        assert response.content == "Fixed it."
        assert response.reasoning == "The config sets effort but the flag is missing."

    def test_the_answer_is_not_polluted_with_the_thinking(self):
        """Two different claims: what it considered, and what it said."""
        raw = self._stream(
            {"type": "assistant", "message": {"content": [
                {"type": "thinking", "thinking": "Maybe the tests are wrong."},
                {"type": "text", "text": "The tests are right."},
            ]}},
            {"type": "result", "result": "The tests are right.", "usage": {}},
        )
        response = claude_code._parse_cli_output(raw, "sonnet")
        assert "Maybe the tests are wrong" not in response.content

    def test_a_call_that_did_not_think_carries_no_thinking(self):
        raw = self._stream(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "OK"}]}},
            {"type": "result", "result": "OK", "usage": {}},
        )
        assert claude_code._parse_cli_output(raw, "sonnet").reasoning is None

    def test_the_plain_json_shape_still_parses(self):
        """Older logs and any caller still asking for `--output-format json`."""
        response = claude_code._parse_cli_output(
            json.dumps({"result": "done", "usage": {"output_tokens": 3}}), "sonnet",
        )
        assert response.content == "done"

    def test_a_stream_cut_off_mid_answer_keeps_what_was_said(self):
        """No result line: a timeout or a kill. Losing the answer too would be worse."""
        raw = self._stream(
            {"type": "assistant", "message": {"content": [
                {"type": "thinking", "thinking": "Half a thought"},
            ]}},
        )
        response = claude_code._parse_cli_output(raw, "sonnet")
        assert response.reasoning == "Half a thought"

    def test_thinking_tokens_are_recorded_even_when_the_text_is_not(self):
        """The number that shows an effort setting changed something."""
        raw = json.dumps({
            "result": "ok",
            "usage": {"output_tokens": 40, "output_tokens_details": {"thinking_tokens": 31}},
        })
        response = claude_code._parse_cli_output(raw, "sonnet")
        assert response.raw_response["thinking_tokens"] == 31
