"""Tests for routing function factories."""

from langgraph.graph import END

from temper_ai.workflow.condition_evaluator import ConditionEvaluator
from temper_ai.workflow.routing_functions import (
    create_conditional_router,
    create_loop_router,
)


class FakeStageRef:
    """Minimal stage reference for testing."""

    def __init__(
        self,
        name,
        conditional=False,
        condition=None,
        skip_if=None,
        loops_back_to=None,
        max_loops=2,
    ):
        self.name = name
        self.conditional = conditional
        self.condition = condition
        self.skip_if = skip_if
        self.loops_back_to = loops_back_to
        self.max_loops = max_loops


class TestConditionalRouter:
    """Tests for create_conditional_router()."""

    def setup_method(self):
        self.evaluator = ConditionEvaluator()

    def test_executes_when_condition_true(self):
        ref = FakeStageRef("fix", condition="{{ should_fix }}")
        router = create_conditional_router(
            ref,
            "next_stage",
            1,
            [FakeStageRef("test"), ref],
            self.evaluator,
        )
        result = router({"should_fix": True})
        assert result == "fix"

    def test_skips_when_condition_false(self):
        ref = FakeStageRef("fix", condition="{{ should_fix }}")
        router = create_conditional_router(
            ref,
            "next_stage",
            1,
            [FakeStageRef("test"), ref],
            self.evaluator,
        )
        result = router({"should_fix": False})
        assert result == "next_stage"

    def test_skips_to_end_when_last_stage(self):
        ref = FakeStageRef("fix", condition="{{ should_fix }}")
        router = create_conditional_router(
            ref,
            None,
            1,
            [FakeStageRef("test"), ref],
            self.evaluator,
        )
        result = router({"should_fix": False})
        assert result == END

    def test_skip_if_true_skips(self):
        ref = FakeStageRef("optional", skip_if="{{ skip }}")
        router = create_conditional_router(
            ref,
            "next_stage",
            0,
            [ref],
            self.evaluator,
        )
        result = router({"skip": True})
        assert result == "next_stage"

    def test_skip_if_false_executes(self):
        ref = FakeStageRef("optional", skip_if="{{ skip }}")
        router = create_conditional_router(
            ref,
            "next_stage",
            0,
            [ref],
            self.evaluator,
        )
        result = router({"skip": False})
        assert result == "optional"

    def test_default_condition_executes_on_failure(self):
        """When conditional=True but no condition, default checks previous stage."""
        ref = FakeStageRef("fix", conditional=True)
        stages = [FakeStageRef("test"), ref]
        router = create_conditional_router(
            ref,
            None,
            1,
            stages,
            self.evaluator,
        )
        state = {"stage_outputs": {"test": {"stage_status": "failed"}}}
        result = router(state)
        assert result == "fix"

    def test_default_condition_skips_on_success(self):
        ref = FakeStageRef("fix", conditional=True)
        stages = [FakeStageRef("test"), ref]
        router = create_conditional_router(
            ref,
            None,
            1,
            stages,
            self.evaluator,
        )
        state = {"stage_outputs": {"test": {"stage_status": "success"}}}
        result = router(state)
        assert result == END


class TestLoopRouter:
    """Tests for create_loop_router().

    Note: In production, the loop gate node increments stage_loop_counts
    BEFORE the router runs. Tests provide pre-incremented counts.
    """

    def setup_method(self):
        self.evaluator = ConditionEvaluator()

    def test_loops_when_under_max_and_condition_true(self):
        ref = FakeStageRef("fix", loops_back_to="test", max_loops=3)
        router = create_loop_router(ref, "after_fix", self.evaluator)
        state = {
            "stage_outputs": {"fix": {"stage_status": "failed"}},
            "stage_loop_counts": {"fix": 1},  # gate already incremented
        }
        result = router(state)
        assert result == "test"

    def test_exits_at_max_loops(self):
        ref = FakeStageRef("fix", loops_back_to="test", max_loops=3)
        router = create_loop_router(ref, "after_fix", self.evaluator)
        state = {
            "stage_outputs": {"fix": {"stage_status": "failed"}},
            "stage_loop_counts": {"fix": 4},  # gate incremented past max
        }
        result = router(state)
        assert result == "after_fix"

    def test_exits_when_condition_false(self):
        ref = FakeStageRef("fix", loops_back_to="test", max_loops=3)
        router = create_loop_router(ref, "after_fix", self.evaluator)
        state = {
            "stage_outputs": {"fix": {"stage_status": "success"}},
            "stage_loop_counts": {"fix": 1},
        }
        result = router(state)
        assert result == "after_fix"

    def test_exits_to_end_when_no_next_stage(self):
        ref = FakeStageRef("fix", loops_back_to="test", max_loops=3)
        router = create_loop_router(ref, None, self.evaluator)
        state = {
            "stage_outputs": {"fix": {"stage_status": "success"}},
            "stage_loop_counts": {"fix": 1},
        }
        result = router(state)
        assert result == END

    def test_loops_when_count_equals_max(self):
        """count == max_loops means exactly max iterations done, should exit."""
        ref = FakeStageRef("fix", loops_back_to="test", max_loops=2)
        router = create_loop_router(ref, "after_fix", self.evaluator)
        state = {
            "stage_outputs": {"fix": {"stage_status": "failed"}},
            "stage_loop_counts": {"fix": 2},
        }
        result = router(state)
        # count=2, max=2 → 2 <= 2, condition met → loop
        assert result == "test"

    def test_exits_when_count_exceeds_max(self):
        """count > max_loops → exit."""
        ref = FakeStageRef("fix", loops_back_to="test", max_loops=2)
        router = create_loop_router(ref, "after_fix", self.evaluator)
        state = {
            "stage_outputs": {"fix": {"stage_status": "failed"}},
            "stage_loop_counts": {"fix": 3},
        }
        result = router(state)
        assert result == "after_fix"

    def test_missing_loop_counts_key(self):
        """State without stage_loop_counts should still work (count=0)."""
        ref = FakeStageRef("fix", loops_back_to="test", max_loops=3)
        router = create_loop_router(ref, "after_fix", self.evaluator)
        state = {
            "stage_outputs": {"fix": {"stage_status": "failed"}},
        }
        result = router(state)
        assert result == "test"

    def test_custom_condition(self):
        ref = FakeStageRef(
            "fix",
            loops_back_to="test",
            max_loops=3,
            condition="{{ stage_outputs.fix.errors|length > 0 }}",
        )
        router = create_loop_router(ref, "after_fix", self.evaluator)

        state_with_errors = {
            "stage_outputs": {"fix": {"errors": ["err1"]}},
            "stage_loop_counts": {"fix": 1},
        }
        assert router(state_with_errors) == "test"

        state_no_errors = {
            "stage_outputs": {"fix": {"errors": []}},
            "stage_loop_counts": {"fix": 1},
        }
        assert router(state_no_errors) == "after_fix"
