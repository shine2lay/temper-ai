"""Tests for stage/stage_node.py — the context boundary around a sub-graph.

The input gate is the seam where a referenced *workflow* differs from a referenced *stage*: they
declare their inputs in two different shapes, and only one of them was ever read here.
"""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.shared.types import ExecutionContext, NodeResult, Status
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.stage_node import StageNode


def _stage(**kwargs) -> StageNode:
    return StageNode(NodeConfig(name="child", type="stage", **kwargs), child_nodes=[])


def _context() -> ExecutionContext:
    # A real one: StageNode calls dataclasses.replace() on it, which a MagicMock cannot satisfy.
    return ExecutionContext(
        run_id="r", workflow_name="w", node_path="", agent_name="",
        event_recorder=MagicMock(), tool_executor=MagicMock(),
    )


def _run(stage: StageNode, input_data: dict) -> dict:
    """Run the stage with the sub-graph stubbed out, returning what reached it."""
    seen = {}

    def fake_execute(nodes, input_data, context, **kw):
        seen.update(input_data)
        return NodeResult(status=Status.COMPLETED, output="ok")

    with patch("temper_ai.stage.stage_node.execute_graph", side_effect=fake_execute):
        stage.run(input_data, _context())
    return seen


class TestInputGateUnderstandsBothDeclarationShapes:
    def test_stage_shape_maps_local_name_to_source_key(self):
        """`inputs: {goal: goal_text}` — the historical meaning, unchanged."""
        stage = _stage(inputs={"goal": "goal_text"})
        assert _run(stage, {"goal_text": "ship it", "other": "dropped"}) == {"goal": "ship it"}

    def test_workflow_shape_passes_the_field_through_by_its_own_name(self):
        """`inputs: {goal: {type: string}}` is a schema, not a source.

        Read as a source it became `input_data.get({...})` — TypeError: unhashable type: 'dict' —
        so a referenced workflow died in the gate before any of its nodes ran.
        """
        stage = _stage(inputs={"goal": {"type": "string", "required": True}})
        assert _run(stage, {"goal": "ship it", "other": "dropped"}) == {"goal": "ship it"}

    def test_the_two_shapes_can_be_mixed(self):
        stage = _stage(inputs={"goal": {"type": "string"}, "who": "author"})
        assert _run(stage, {"goal": "g", "author": "a"}) == {"goal": "g", "who": "a"}

    def test_no_declared_inputs_means_everything_flows_in(self):
        assert _run(_stage(), {"a": 1, "b": 2}) == {"a": 1, "b": 2}

    def test_an_optional_field_that_is_absent_is_simply_none(self):
        stage = _stage(inputs={"goal": {"type": "string"}, "note": {"type": "string"}})
        assert _run(stage, {"goal": "g"}) == {"goal": "g", "note": None}


class TestTheHumansApprovalCrossesTheBoundary:
    """`gate` is put there by the executor when a person approves the node, and it carries what they
    said — an edited invariant, a note, a condition. The parent never mapped it in, so a boundary
    that only passes declared fields drops exactly the part a human contributed."""

    def test_it_reaches_a_stage_that_declares_its_inputs(self):
        stage = _stage(inputs={"goal": {"type": "string"}})
        seen = _run(stage, {"goal": "g", "gate": {"approved": True, "note": "narrow it to exits"}})
        assert seen["gate"] == {"approved": True, "note": "narrow it to exits"}

    def test_it_reaches_a_stage_declared_the_old_way_too(self):
        stage = _stage(inputs={"goal": "goal_text"})
        seen = _run(stage, {"goal_text": "g", "gate": {"approved": True}})
        assert seen["gate"] == {"approved": True}

    def test_a_declared_gate_input_is_not_overwritten(self):
        """If a config declares `gate` itself, that mapping is the author's intent."""
        stage = _stage(inputs={"gate": "other_key"})
        assert _run(stage, {"other_key": "mine", "gate": {"approved": True}}) == {"gate": "mine"}

    def test_nothing_is_invented_when_there_was_no_gate(self):
        assert "gate" not in _run(_stage(inputs={"goal": {"type": "string"}}), {"goal": "g"})


class TestARequiredInputIsCheckedWhereItIsNamed:
    """Downstream, a missing required input is a blank in some agent's prompt and a run that fails
    somewhere unable to explain why. Here, the stage and the field are both known."""

    def test_it_names_the_stage_and_the_field(self):
        stage = _stage(inputs={"goal": {"type": "string", "required": True}})
        with pytest.raises(ValueError, match="child.*missing required input.*goal"):
            _run(stage, {"unrelated": "x"})

    def test_it_lists_every_missing_field_not_just_the_first(self):
        stage = _stage(inputs={
            "goal": {"type": "string", "required": True},
            "repo": {"type": "string", "required": True},
            "note": {"type": "string"},
        })
        with pytest.raises(ValueError, match="goal, repo"):
            _run(stage, {})

    def test_it_says_how_to_fix_it(self):
        stage = _stage(inputs={"goal": {"type": "string", "required": True}})
        with pytest.raises(ValueError, match="input_map"):
            _run(stage, {})

    def test_nothing_runs_when_a_required_input_is_missing(self):
        stage = _stage(inputs={"goal": {"type": "string", "required": True}})
        with patch("temper_ai.stage.stage_node.execute_graph") as ex:
            with pytest.raises(ValueError):
                stage.run({}, _context())
            assert not ex.called

    def test_an_empty_string_is_a_value_not_an_absence(self):
        """`required` means supplied, not truthy: a deliberately empty note must pass."""
        stage = _stage(inputs={"note": {"type": "string", "required": True}})
        assert _run(stage, {"note": ""}) == {"note": ""}


class TestOutputsSpeakTwoLanguages:
    """A referenced workflow's `outputs:` name nodes inside it; a stage's name fields of its own
    result. Reading the first as the second yields a full set of keys, all None — a silent empty
    handoff, which is how a downstream agent ends up writing to nowhere."""

    @staticmethod
    def _stage_with_children(outputs: dict, child_names=("report",)) -> StageNode:
        children = [MagicMock(name=n) for n in child_names]
        for c, n in zip(children, child_names, strict=True):
            c.name = n
        return StageNode(
            NodeConfig(name="report", type="stage", outputs=outputs), child_nodes=list(children)
        )

    def _run_capturing(self, stage: StageNode, sub_result: NodeResult) -> tuple[dict, NodeResult]:
        passed = {}

        def fake_execute(nodes, input_data, context, **kw):
            passed.update(kw)
            return sub_result

        with patch("temper_ai.stage.stage_node.execute_graph", side_effect=fake_execute):
            result = stage.run({}, _context())
        return passed, result

    def test_a_workflows_outputs_are_handed_to_the_sub_graph_to_resolve(self):
        stage = self._stage_with_children({"report_path": "report.structured.report_path"})
        passed, _ = self._run_capturing(stage, NodeResult(status=Status.COMPLETED, output="ok"))
        assert passed["workflow_outputs"] == {"report_path": "report.structured.report_path"}

    def test_what_the_sub_graph_resolved_survives_the_boundary(self):
        """The bug: this came out {'report_path': None} and the next stage got nothing."""
        stage = self._stage_with_children({"report_path": "report.structured.report_path"})
        resolved = NodeResult(
            status=Status.COMPLETED, output="ok",
            structured_output={"report_path": "/w/bets/b003/report.md"},
        )
        _, result = self._run_capturing(stage, resolved)
        assert result.structured_output == {"report_path": "/w/bets/b003/report.md"}

    def test_a_stages_own_language_still_projects_its_result(self):
        stage = self._stage_with_children({"verdict": "structured.verdict"})
        resolved = NodeResult(
            status=Status.COMPLETED, output="ok",
            structured_output={"verdict": "approve", "noise": "dropped"},
        )
        passed, result = self._run_capturing(stage, resolved)
        assert passed.get("workflow_outputs") is None
        assert result.structured_output == {"verdict": "approve"}

    def test_the_two_can_be_mixed_in_one_node(self):
        stage = self._stage_with_children(
            {"report_path": "report.structured.report_path", "cost": "cost_usd"}
        )
        resolved = NodeResult(
            status=Status.COMPLETED, output="ok", cost_usd=1.5,
            structured_output={"report_path": "/w/report.md"},
        )
        _, result = self._run_capturing(stage, resolved)
        assert result.structured_output == {"report_path": "/w/report.md", "cost": 1.5}
