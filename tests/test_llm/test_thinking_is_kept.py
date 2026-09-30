"""Thinking that happens has to be readable afterwards.

An effort setting buys two different things, and temper was only ever asking
for the first: that the model thinks, and that it says what it thought.
Measured on opus-5-5, `effort: low` alone spent 134 output tokens on an
eleven-character answer and returned one empty thinking block \u2014 paid for,
unreadable. Asking for a summary as well returned 273 characters of it.

The other half is where that text ends up. It is carried on the response as
`reasoning`, recorded with the model call that produced it, and read back into
the page as `thinking` \u2014 whether or not anyone was watching the run happen.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from temper_ai.llm.providers.anthropic import (
    _NO_VISIBLE_THINKING,
    _apply_thinking_control,
    _parse_response,
    _thinking_rejected,
)


def _block(**fields):
    return SimpleNamespace(**fields)


def _response(*content, stop_reason="end_turn"):
    return SimpleNamespace(
        content=list(content),
        stop_reason=stop_reason,
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )


class TestACallThatWasNotStreamedKeepsItsThinking:
    """The gap that made 52,900 calls carry nothing.

    Only the streaming path ever set `reasoning`, so whether a run recorded
    its thinking depended on how it happened to be started \u2014 a detail of the
    caller, not of the agent.
    """

    def test_thinking_blocks_become_the_calls_reasoning(self):
        response = _parse_response(
            _response(
                _block(type="thinking", thinking="The flag is missing from the command."),
                _block(type="text", text="Added it."),
            ),
            model="claude-opus-5-5",
        )
        assert response.reasoning == "The flag is missing from the command."
        assert response.content == "Added it."

    def test_thinking_is_never_mixed_into_the_answer(self):
        """What a model considered and what it said are different claims."""
        response = _parse_response(
            _response(
                _block(type="thinking", thinking="Maybe the tests are wrong."),
                _block(type="text", text="The tests are right."),
            ),
            model="claude-opus-5-5",
        )
        assert "Maybe the tests are wrong" not in response.content

    def test_several_thinking_blocks_are_kept_in_order(self):
        response = _parse_response(
            _response(
                _block(type="thinking", thinking="First."),
                _block(type="text", text="Answer."),
                _block(type="thinking", thinking="Second."),
            ),
            model="claude-opus-5-5",
        )
        assert response.reasoning == "First.\n\nSecond."

    def test_a_call_without_thinking_carries_none(self):
        """No empty string standing in for absence: the page draws a section
        for a call that thought, and must not draw one for a call that did not."""
        response = _parse_response(_response(_block(type="text", text="OK")),
                                   model="claude-opus-5-5")
        assert response.reasoning is None

    def test_an_empty_thinking_block_is_not_thinking(self):
        """What `effort` alone returns: billed, and with nothing in it."""
        response = _parse_response(
            _response(_block(type="thinking", thinking=""), _block(type="text", text="OK")),
            model="claude-opus-5-5",
        )
        assert response.reasoning is None


class TestTheModelIsAskedToShowItsThinking:
    def test_effort_asks_for_a_readable_summary_as_well(self):
        kwargs: dict = {"model": "claude-opus-5-5", "temperature": 0.7}
        _apply_thinking_control(kwargs, "claude-opus-5-5", effort="low", budget=None)
        assert kwargs["output_config"] == {"effort": "low"}
        assert kwargs["thinking"]["display"] == "summarized"

    def test_sampling_is_dropped_because_thinking_forbids_it(self):
        """The API refuses any temperature but 1 once thinking is on; an agent
        config that set 0.7 did not mean to forbid thinking."""
        kwargs: dict = {"model": "claude-opus-5-5", "temperature": 0.7}
        _apply_thinking_control(kwargs, "claude-opus-5-5", effort="high", budget=None)
        assert "temperature" not in kwargs

    def test_an_agent_that_asked_for_nothing_is_left_alone(self):
        """No default thinking anywhere: it is billed as output."""
        kwargs: dict = {"model": "claude-opus-5-5", "temperature": 0.7}
        _apply_thinking_control(kwargs, "claude-opus-5-5", effort=None, budget=None)
        assert "thinking" not in kwargs and "output_config" not in kwargs
        assert kwargs["temperature"] == 0.7

    def test_a_model_that_refused_the_knob_is_not_asked_again(self):
        """One refusal teaches the process; the answer matters more than the knob."""
        _NO_VISIBLE_THINKING.add("claude-opus-5-5")
        try:
            kwargs: dict = {"model": "claude-opus-5-5"}
            _apply_thinking_control(kwargs, "claude-opus-5-5", effort="low", budget=None)
            # The effort still goes \u2014 it is the thinking that happens. Only the
            # request to see it is dropped, and only for this model.
            assert kwargs["output_config"] == {"effort": "low"}
            assert "thinking" not in kwargs
        finally:
            _NO_VISIBLE_THINKING.discard("claude-opus-5-5")


class TestOnlyARefusalOfThatKnobCountsAsOne:
    """A retry that drops a knob must not swallow a real failure."""

    def _error(self, status: int, message: str) -> Exception:
        exc = Exception(message)
        exc.status_code = status  # type: ignore[attr-defined]
        return exc

    def test_a_400_naming_thinking_counts(self):
        assert _thinking_rejected(self._error(400, "thinking: unexpected parameter"))

    def test_a_rate_limit_does_not(self):
        assert not _thinking_rejected(self._error(429, "rate limit exceeded"))

    def test_an_overload_does_not(self):
        assert not _thinking_rejected(self._error(529, "overloaded"))

    def test_a_400_about_something_else_does_not(self):
        assert not _thinking_rejected(self._error(400, "max_tokens is too large"))


@pytest.mark.parametrize("blocks,expected", [
    ([("thinking", "a"), ("text", "b")], "a"),
    ([("text", "b")], None),
])
def test_both_providers_agree_on_what_reasoning_means(blocks, expected):
    """The Claude Code CLI and the API put thinking in the same field, so the
    page has one thing to read and one thing to draw."""
    claude_code = pytest.importorskip(
        "local.providers.claude_code",
        reason="local/ provider is gitignored; present only in a working checkout",
    )
    import json

    lines = [json.dumps({"type": "assistant", "message": {"content": [
        {"type": t, t: v} for t, v in blocks
    ]}}), json.dumps({"type": "result", "result": "b", "usage": {}})]
    cli = claude_code._parse_cli_output("\n".join(lines), "sonnet")

    api = _parse_response(
        _response(*[_block(type=t, **{t: v}) for t, v in blocks]),
        model="claude-opus-5-5",
    )
    assert cli.reasoning == expected
    assert api.reasoning == expected
