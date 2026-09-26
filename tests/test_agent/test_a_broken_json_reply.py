"""A reply whose JSON does not parse is repaired, asked for again once, and failing that fails.

b012 on 2026-09-25 (run 94f7b2ae): the pitch check quoted the page inside its JSON strings
without escaping the quotes ("reads "−$120.00", "−$2.00" and so on"), json.loads refused
it, the agent completed with no structured output, and the write/check loop read "no
verdict" as "stop". fixtures/b012_check_reply.txt is that reply, word for word.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from temper_ai.agent import llm_agent
from temper_ai.agent.llm_agent import _extract_structured_output
from temper_ai.llm.models import LLMRunResult
from temper_ai.shared.types import Status
from tests.test_agent.test_llm_agent import _make_agent, _make_context

B012 = (Path(__file__).parent / "fixtures" / "b012_check_reply.txt").read_text(encoding="utf-8")
BROKEN = 'The pitch goes back.\n\n```json\n{"verdict": revise, "issues": []}\n```'


def test_b012s_check_reply_is_read_after_a_repair():
    got = _extract_structured_output(B012)

    assert got is not None
    assert got["verdict"] == "revise"
    assert [i["where"] for i in got["issues"]] == ["criterion 1", "criterion 2", "solution", "solution"]
    assert got["issues"][0]["what"].startswith(
        'The To close cell prints the buyback as a negative amount, so on a working build it reads '
        '"−$120.00", "−$2.00" and so on.')
    # code quoted in a string, with a quote just before a brace, stays in the string
    assert 'RollCall does not know ${one ? "its" : "their"} strike' in got["issues"][3]["evidence"]
    assert got["threshold_matches"] is True


@pytest.mark.parametrize("text, want", [
    ('{"a": "line one\nline two"}', {"a": "line one\nline two"}),       # a raw line break
    ('{"a": [1, 2,], "b": "c",}', {"a": [1, 2], "b": "c"}),              # trailing commas
    ('{"xs": ["say "hi" now", "b"]}', {"xs": ['say "hi" now', "b"]}),   # quotes in a list item
    ('{"a": "label \\"Risk: high\\" here"}', {"a": 'label "Risk: high" here'}),  # already fine
], ids=["line-break", "trailing-commas", "quotes-in-a-list", "already-fine"])
def test_the_repair_fixes_what_models_get_wrong(text, want):
    assert _extract_structured_output(text) == want


@pytest.mark.parametrize("text, tried", [
    (B012, True),                                          # ends in a ```json block
    ('Done.\n{"verdict": "ready"}', True),                 # ends in a bare object
    ("No JSON here, just prose.", False),
    ('It said {"a": 1} and then went on to talk.', False),  # JSON mid-reply is not the answer
    ('```json\n[1, 2, 3]\n```', False),                    # a list is not an object
], ids=["b012", "bare-object", "prose", "json-mid-reply", "a-list"])
def test_which_replies_end_in_an_answer_given_as_json(text, tried):
    assert llm_agent._reply_tried_json(text) is tried


@patch("temper_ai.agent.llm_agent.LLMService")
def test_one_more_turn_when_the_repair_cannot_read_it(MockLLMService):
    service = MockLLMService.return_value
    service.run.side_effect = [
        LLMRunResult(output=BROKEN, tokens=100, cost=0.10, iterations=3),
        LLMRunResult(output='{"verdict": "revise", "issues": []}', tokens=20, cost=0.02, iterations=1),
    ]
    ctx = _make_context()
    result = _make_agent().run({"task": "check"}, ctx)

    assert result.status == Status.COMPLETED
    assert result.structured_output == {"verdict": "revise", "issues": []}
    assert result.output == BROKEN                       # the reply stays the agent's output
    assert result.cost_usd == pytest.approx(0.12)
    assert result.tokens.total_tokens == 120
    assert result.llm_calls == 4
    again = service.run.call_args_list[1].kwargs
    assert again["tools"] is None
    [ask] = again["messages"]
    assert ask["role"] == "user" and BROKEN in ask["content"]
    assert "Expecting value" in ask["content"]           # it is told why the JSON did not parse
    ctx.tool_executor.track_usage.assert_any_call(cost_usd=0.02, tokens=20)


@patch("temper_ai.agent.llm_agent.LLMService")
def test_the_agent_fails_when_the_second_reply_is_broken_too(MockLLMService):
    MockLLMService.return_value.run.side_effect = [
        LLMRunResult(output=BROKEN, tokens=100, cost=0.10, iterations=1),
        LLMRunResult(output='{"verdict": revise}', tokens=20, cost=0.02, iterations=1),
    ]
    result = _make_agent().run({"task": "check"}, _make_context())

    assert result.status == Status.FAILED
    assert result.structured_output is None
    assert "does not parse, even after a repair and one more turn" in result.error


@patch("temper_ai.agent.llm_agent.LLMService")
def test_the_agent_fails_when_the_second_call_does(MockLLMService):
    MockLLMService.return_value.run.side_effect = [
        LLMRunResult(output=BROKEN, tokens=100, cost=0.10, iterations=1),
        LLMRunResult(output="", error="Budget exceeded: $10.00 >= $10.00", iterations=0),
    ]
    result = _make_agent().run({"task": "check"}, _make_context())

    assert result.status == Status.FAILED
    assert "Budget exceeded" in result.error


@patch("temper_ai.agent.llm_agent.LLMService")
def test_a_reply_that_gives_no_json_is_left_as_it_was(MockLLMService):
    MockLLMService.return_value.run.return_value = LLMRunResult(
        output="I wrote the plan to .epd/plan.md.", tokens=10, cost=0.01, iterations=1)
    result = _make_agent().run({"task": "plan"}, _make_context())

    assert result.status == Status.COMPLETED
    assert result.structured_output is None
    assert MockLLMService.return_value.run.call_count == 1
