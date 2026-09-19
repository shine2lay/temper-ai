"""A loop rewind hands the trigger's result to the node it rewinds to.

epd_task's review node loops back to implement with
``review_findings: review.structured.findings``. On the first pass review has
not run, so that input is unresolved. On the rewind the executor clears every
output from implement's batch onward — review's included — so the value has to
come from ``loop_feedback``, where ``_handle_loop`` preserved the triggering
result. Nothing else in the suite performs a real rewind, and two live runs
approved on the first pass, so this is where that path is proven.
"""

from unittest.mock import MagicMock

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
