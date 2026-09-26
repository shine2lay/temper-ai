"""A loop that cannot read its verdict fails, instead of ending as if the verdict said stop.

b012 on 2026-09-25: the pitch check's JSON did not parse, so its verdict was missing. The
loop condition `check.structured.verdict == revise` came out false, the write/check loop
ended after one pass, and the run went on to complete as if the check had passed the pitch.
"""

from unittest.mock import MagicMock

from temper_ai.shared.types import AgentResult, NodeResult, Status, TokenUsage
from temper_ai.stage.executor import execute_graph
from tests.test_stage.test_executor import _make_agent_node, _make_context

REVISE = {"source": "check.structured.verdict", "operator": "equals", "value": "revise"}


def _replies(*structured):
    return [
        NodeResult(status=Status.COMPLETED, output=f"pass {i}", structured_output=so,
                   agent_results=[AgentResult(status=Status.COMPLETED, output="r",
                                              tokens=TokenUsage(total_tokens=10), cost_usd=0.01)],
                   cost_usd=0.01, total_tokens=10)
        for i, so in enumerate(structured, 1)
    ]


def _graph(*check_says, condition=REVISE):
    write = _make_agent_node("write")
    check = _make_agent_node("check", depends_on=["write"], loop_to="write", max_loops=3)
    check.config.loop_condition = condition
    check.run = MagicMock(side_effect=_replies(*check_says))
    after = _make_agent_node("after", depends_on=["check"])
    return write, check, after


def test_a_check_with_no_verdict_fails_the_run_instead_of_ending_the_loop():
    write, check, after = _graph(None)
    ctx = _make_context()
    result = execute_graph([write, check, after], {}, ctx, graph_name="g", is_workflow=True)

    got = result.node_results["check"]
    assert got.status == Status.FAILED
    assert got.error == ("it gave no check.structured.verdict, "
                         "so its loop cannot tell whether to go round again")
    assert write.run.call_count == 1 and check.run.call_count == 1  # no other pass for it
    assert after.run.call_count == 0                                 # nothing goes on as if it had passed
    assert result.status == Status.FAILED
    assert "check" in (result.error or "")
    # the node's own event says so, not only the run's
    ctx.event_recorder.update_event.assert_any_call(
        "evt-123", status="failed", data={"error": got.error})


def test_a_verdict_of_empty_text_is_no_verdict_either():
    write, check, after = _graph({"verdict": "  "})
    result = execute_graph([write, check, after], {}, _make_context(), graph_name="g", is_workflow=True)

    assert result.node_results["check"].status == Status.FAILED
    assert after.run.call_count == 0


def test_a_readable_verdict_still_loops_and_then_goes_on():
    write, check, after = _graph({"verdict": "revise"}, {"verdict": "ready"})
    result = execute_graph([write, check, after], {}, _make_context(), graph_name="g", is_workflow=True)

    assert write.run.call_count == 2 and check.run.call_count == 2
    assert after.run.call_count == 1
    assert result.status == Status.COMPLETED


def test_an_exists_condition_takes_a_missing_value_as_its_answer():
    exists = {"source": "check.structured.retry", "operator": "exists"}
    write, check, after = _graph({"verdict": "ready"}, condition=exists)
    result = execute_graph([write, check, after], {}, _make_context(), graph_name="g", is_workflow=True)

    assert result.node_results["check"].status == Status.COMPLETED
    assert after.run.call_count == 1
