"""A loop rewind hands the trigger's result to the node it rewinds to.

epd_task's review node loops back to implement with
``review_findings: review.structured.findings``. On the first pass review has
not run, so that input is unresolved. On the rewind the executor clears every
output from implement's batch onward — review's included — so the value has to
come from ``loop_feedback``, where ``_handle_loop`` preserved the triggering
result. Nothing else in the suite performs a real rewind, and two live runs
approved on the first pass, so this is where that path is proven.
"""

import threading
from unittest.mock import MagicMock

import pytest

from temper_ai.shared.types import (
    AgentResult,
    ExecutionContext,
    NodeResult,
    Status,
    TokenUsage,
)
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.models import NodeConfig


def _context() -> ExecutionContext:
    recorder = MagicMock()
    recorder.record.return_value = "evt-1"
    return ExecutionContext(
        run_id="run-1",
        workflow_name="test",
        node_path="",
        agent_name="",
        event_recorder=recorder,
        tool_executor=MagicMock(),
    )


def _result(output: str, structured: dict) -> NodeResult:
    return NodeResult(
        status=Status.COMPLETED,
        output=output,
        structured_output=structured,
        agent_results=[
            AgentResult(
                status=Status.COMPLETED,
                output=output,
                tokens=TokenUsage(total_tokens=10),
                cost_usd=0.01,
                llm_calls=2,
                tool_calls=3,
            )
        ],
        cost_usd=0.01,
        total_tokens=10,
    )


def _node(name: str, results: list[NodeResult], **config) -> AgentNode:
    """An agent node whose successive runs return ``results`` in order."""
    node = AgentNode(NodeConfig(name=name, **config), {"name": name, "type": "llm"})
    node.run = MagicMock(side_effect=results)
    return node


REQUEST_CHANGES = {
    "source": "review.structured.verdict",
    "operator": "equals",
    "value": "request_changes",
}
FINDINGS = [{"severity": "blocker", "where": "a.ts:12", "what": "guard removed", "fix": "restore it"}]


def _inputs(node: AgentNode) -> list[dict]:
    return [call.args[0] for call in node.run.call_args_list]


class TestLoopCostAccounting:
    """A rewind clears the outputs of every node from the loop target onward.

    Those attempts still cost money and burned tokens, so the run total has to
    count them. Summing only the results that survive in node_outputs reports
    the last attempt of each node and silently discards the rest — which is
    what live run 25a8f9f2 did, showing $0.91 against $2.86 of real spend.
    """

    def _looping_graph(self) -> tuple[AgentNode, AgentNode]:
        implement = _node(
            "implement",
            [_result("first attempt", {"commit": "aaa"}), _result("fix", {"commit": "bbb"})],
            input_map={"review_findings": "review.structured.findings"},
        )
        review = _node(
            "review",
            [
                _result("r1", {"verdict": "request_changes", "findings": FINDINGS}),
                _result("r2", {"verdict": "approve", "findings": []}),
            ],
            depends_on=["implement"],
            loop_to="implement",
            max_loops=2,
            loop_condition=REQUEST_CHANGES,
        )
        return implement, review

    def test_the_total_counts_every_attempt_not_just_the_survivors(self):
        implement, review = self._looping_graph()

        result = execute_graph([implement, review], {}, _context(), graph_name="test")

        # Four node executions happened at $0.01 / 10 tokens each.
        assert implement.run.call_count == 2
        assert review.run.call_count == 2
        assert result.cost_usd == pytest.approx(0.04)
        assert result.total_tokens == 40

    def test_the_workflow_event_reports_the_same_total(self):
        """The UI reads the event, not the return value; they must agree."""
        implement, review = self._looping_graph()
        ctx = _context()

        result = execute_graph([implement, review], {}, ctx, graph_name="test")

        completions = [
            call.kwargs["data"]
            for call in ctx.event_recorder.update_event.call_args_list
            if call.kwargs.get("data", {}).get("cost_usd") is not None
        ]
        assert completions, "no completion event carried a cost"
        assert completions[-1]["cost_usd"] == pytest.approx(result.cost_usd)
        assert completions[-1]["total_tokens"] == result.total_tokens

    def test_discarded_call_counts_are_published_for_the_api_to_add(self):
        """The API counts calls from the node tree, which keeps one entry per
        name and so cannot see a discarded attempt. It gets their share here.
        """
        implement, review = self._looping_graph()
        ctx = _context()

        execute_graph([implement, review], {}, ctx, graph_name="test")

        data = [
            c.kwargs["data"]
            for c in ctx.event_recorder.update_event.call_args_list
            if "retired_llm_calls" in c.kwargs.get("data", {})
        ]
        assert data, "the workflow event did not carry the discarded attempts"
        # Two attempts were thrown away, one agent each, at 2 llm / 3 tool calls.
        assert data[-1]["retired_llm_calls"] == 4
        assert data[-1]["retired_tool_calls"] == 6

    def test_a_cancelled_run_still_reports_what_the_loop_spent(self):
        """Cancelling is often a reaction to a loop burning money, so this is
        the case where the total most needs to be true. The early-return path
        builds its own NodeResult and has to account the same way.
        """
        implement, review = self._looping_graph()
        ctx = _context()
        ctx.cancel_event = threading.Event()
        # Let the first pass and the rewind happen, then cancel before the
        # second attempt's outputs can replace what was discarded.
        original = implement.run.side_effect

        def _cancel_on_rerun(*args, **kwargs):
            result = next(original)
            if implement.run.call_count >= 2:
                ctx.cancel_event.set()
            return result

        implement.run.side_effect = _cancel_on_rerun

        result = execute_graph([implement, review], {}, ctx, graph_name="test")

        assert result.status is Status.CANCELLED
        # implement ×2 + review ×1 all ran and were paid for.
        assert result.cost_usd == pytest.approx(0.03)
        assert result.total_tokens == 30

    def test_a_run_without_a_rewind_is_unchanged(self):
        """Guards the fix against double-counting when nothing is discarded."""
        implement = _node("implement", [_result("done", {})])
        review = _node(
            "review",
            [_result("r", {"verdict": "approve", "findings": []})],
            depends_on=["implement"],
            loop_to="implement",
            max_loops=2,
            loop_condition=REQUEST_CHANGES,
        )

        ctx = _context()
        result = execute_graph([implement, review], {}, ctx, graph_name="test")

        assert result.cost_usd == pytest.approx(0.02)
        assert result.total_tokens == 20
        # Nothing was discarded, so the API's own count must stand alone.
        assert all(
            "retired_llm_calls" not in (c.kwargs.get("data") or {})
            for c in ctx.event_recorder.update_event.call_args_list
        )


class TestLoopFeedback:
    def test_rewound_node_receives_the_triggers_structured_output(self):
        implement = _node(
            "implement",
            [_result("first attempt", {"commit": "aaa"}), _result("fix", {"commit": "bbb"})],
            input_map={"review_findings": "review.structured.findings"},
        )
        review = _node(
            "review",
            [
                _result("r1", {"verdict": "request_changes", "findings": FINDINGS}),
                _result("r2", {"verdict": "approve", "findings": []}),
            ],
            depends_on=["implement"],
            input_map={"implement_report": "implement.output"},
            loop_to="implement",
            max_loops=2,
            loop_condition=REQUEST_CHANGES,
        )

        result = execute_graph([implement, review], {}, _context(), graph_name="test")

        assert result.status == Status.COMPLETED
        assert implement.run.call_count == 2
        assert review.run.call_count == 2

        first, second = _inputs(implement)
        # Review has not run yet: nothing to resolve, and nothing invented.
        assert first.get("review_findings") is None
        # After the rewind review's output is cleared; the findings arrive from loop_feedback.
        assert second["review_findings"] == FINDINGS

        # Review's second round sees the fix, not the first attempt.
        assert [i["implement_report"] for i in _inputs(review)] == ["first attempt", "fix"]

    def test_max_loops_counts_the_triggers_runs_and_silent_completes(self):
        """max_loops=2 is one fix round: two reviews, two implements, then the
        graph completes on the last verdict — the shape of live run 25a8f9f2."""
        rejected = [_result("r", {"verdict": "request_changes", "findings": FINDINGS}) for _ in range(3)]
        implement = _node(
            "implement",
            [_result("a", {}), _result("b", {}), _result("c", {})],
            input_map={"review_findings": "review.structured.findings"},
        )
        review = _node(
            "review",
            rejected,
            depends_on=["implement"],
            loop_to="implement",
            max_loops=2,
            loop_condition=REQUEST_CHANGES,
            on_max_loops="silent",
        )

        result = execute_graph([implement, review], {}, _context(), graph_name="test")

        assert result.status == Status.COMPLETED
        assert implement.run.call_count == 2
        assert review.run.call_count == 2
        assert _inputs(implement)[1]["review_findings"] == FINDINGS

    def test_default_max_loops_never_rewinds(self):
        """The default max_loops=1 stops at the first trigger: the loop_to is inert."""
        implement = _node("implement", [_result("a", {})])
        review = _node(
            "review",
            [_result("r", {"verdict": "request_changes", "findings": FINDINGS})],
            depends_on=["implement"],
            loop_to="implement",
            loop_condition=REQUEST_CHANGES,
        )

        result = execute_graph([implement, review], {}, _context(), graph_name="test")

        assert result.status == Status.COMPLETED
        assert implement.run.call_count == 1
        assert review.run.call_count == 1
