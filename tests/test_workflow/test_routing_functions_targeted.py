"""Targeted tests for workflow/routing_functions.py to improve coverage from 80% to 90%+.

Covers missing lines: 106-109 (_always_router), 183-185, 199-203 (_to_dict variants).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from langgraph.graph import END

from temper_ai.workflow.condition_evaluator import ConditionEvaluator
from temper_ai.workflow.routing_functions import (
    _get_loop_counts,
    _ref_attr,
    _to_dict,
    create_conditional_router,
    create_loop_router,
)

# ---------------------------------------------------------------------------
# _ref_attr
# ---------------------------------------------------------------------------


class TestRefAttr:
    def test_dict_returns_value(self):
        assert _ref_attr({"key": "val"}, "key") == "val"

    def test_dict_returns_default_when_missing(self):
        assert _ref_attr({"other": "val"}, "key", "default") == "default"

    def test_object_returns_attr(self):
        obj = SimpleNamespace(name="stage1")
        assert _ref_attr(obj, "name") == "stage1"

    def test_object_returns_default_when_missing(self):
        obj = SimpleNamespace()
        assert _ref_attr(obj, "nonexistent", "fallback") == "fallback"


# ---------------------------------------------------------------------------
# _to_dict
# ---------------------------------------------------------------------------


class TestToDict:
    def test_dict_returns_same(self):
        d = {"key": "val", "num": 42}
        result = _to_dict(d)
        assert result == d

    def test_object_with_to_dict_uses_it(self):
        class ObjWithToDict:
            def to_dict(self):
                return {"from_to_dict": True}

        obj = ObjWithToDict()
        result = _to_dict(obj)
        assert result == {"from_to_dict": True}

    def test_object_with_dict_uses_it(self):
        class ObjWithDictAttr:
            def __init__(self):
                self.x = 1
                self.y = 2

        obj = ObjWithDictAttr()
        result = _to_dict(obj)
        assert "x" in result
        assert result["x"] == 1

    def test_unknown_type_returns_empty_dict(self):
        # An object that has neither to_dict nor __dict__
        class NoDict:
            __slots__ = ()

        obj = NoDict()
        result = _to_dict(obj)
        assert result == {}


# ---------------------------------------------------------------------------
# _get_loop_counts
# ---------------------------------------------------------------------------


class TestGetLoopCounts:
    def test_dict_state_returns_counts(self):
        from temper_ai.stage.executors.state_keys import StateKeys

        state = {StateKeys.STAGE_LOOP_COUNTS: {"stage1": 3}}
        result = _get_loop_counts(state)
        assert result == {"stage1": 3}

    def test_dict_state_missing_key_returns_empty(self):
        result = _get_loop_counts({})
        assert result == {}

    def test_object_with_loop_counts_attr(self):
        from temper_ai.stage.executors.state_keys import StateKeys

        obj = SimpleNamespace(**{StateKeys.STAGE_LOOP_COUNTS: {"a": 2}})
        result = _get_loop_counts(obj)
        assert result == {"a": 2}

    def test_object_without_loop_counts_returns_empty(self):
        obj = SimpleNamespace(other_attr=1)
        result = _get_loop_counts(obj)
        assert result == {}

    def test_object_with_none_loop_counts_returns_empty(self):
        from temper_ai.stage.executors.state_keys import StateKeys

        obj = SimpleNamespace(**{StateKeys.STAGE_LOOP_COUNTS: None})
        result = _get_loop_counts(obj)
        assert result == {}


# ---------------------------------------------------------------------------
# create_conditional_router — _always_router path (no condition)
# ---------------------------------------------------------------------------


class TestCreateConditionalRouterAlways:
    def test_no_condition_no_stages_always_executes(self):
        evaluator = ConditionEvaluator()
        # Empty all_stages means no default condition — should use _always_router
        stage_ref = {"name": "stage2"}
        all_stages = []

        router = create_conditional_router(
            stage_ref, "stage3", 0, all_stages, evaluator
        )
        result = router({"some": "state"})
        assert result == "stage2"

    def test_string_stage_ref_uses_ref_as_name(self):
        evaluator = ConditionEvaluator()
        # A string stage_ref => target_name = the string itself
        router = create_conditional_router("stage2", "stage3", 0, [], evaluator)
        result = router({})
        assert result == "stage2"

    def test_default_condition_from_previous_stage(self):
        evaluator = ConditionEvaluator()
        # Index 1 with a previous stage that could have failed
        stage_ref = {"name": "fix_stage", "conditional": True}
        all_stages = [
            {"name": "research"},
            stage_ref,
        ]
        router = create_conditional_router(
            stage_ref, "next_stage", 1, all_stages, evaluator
        )
        # Router should be callable
        assert callable(router)


# ---------------------------------------------------------------------------
# create_conditional_router — skip_if path
# ---------------------------------------------------------------------------


class TestCreateConditionalRouterSkipIf:
    def test_skip_if_true_returns_skip_target(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = True

        stage_ref = {"name": "optional_stage", "skip_if": "always_skip"}
        router = create_conditional_router(stage_ref, "next_stage", 1, [], evaluator)
        result = router({"state": "data"})
        assert result == "next_stage"

    def test_skip_if_false_executes_stage(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = False

        stage_ref = {"name": "optional_stage", "skip_if": "never_skip"}
        router = create_conditional_router(stage_ref, "next_stage", 1, [], evaluator)
        result = router({"state": "data"})
        assert result == "optional_stage"

    def test_skip_if_none_skip_target_uses_end(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = True

        stage_ref = {"name": "optional_stage", "skip_if": "always"}
        # next_stage=None maps to END
        router = create_conditional_router(stage_ref, None, 1, [], evaluator)
        result = router({})
        assert result == END


# ---------------------------------------------------------------------------
# create_conditional_router — condition path
# ---------------------------------------------------------------------------


class TestCreateConditionalRouterCondition:
    def test_condition_true_executes_stage(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = True

        stage_ref = {"name": "conditional_stage", "condition": "x > 0"}
        router = create_conditional_router(stage_ref, "next", 1, [], evaluator)
        result = router({"x": 5})
        assert result == "conditional_stage"

    def test_condition_false_skips_stage(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = False

        stage_ref = {"name": "conditional_stage", "condition": "x > 0"}
        router = create_conditional_router(stage_ref, "next", 1, [], evaluator)
        result = router({"x": -1})
        assert result == "next"


# ---------------------------------------------------------------------------
# create_loop_router
# ---------------------------------------------------------------------------


class TestCreateLoopRouter:
    def test_loops_when_condition_met(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = True

        stage_ref = {
            "name": "loop_stage",
            "loops_back_to": "start_stage",
            "max_loops": 3,
        }
        router = create_loop_router(stage_ref, "exit_stage", evaluator)

        from temper_ai.stage.executors.state_keys import StateKeys

        state = {StateKeys.STAGE_LOOP_COUNTS: {"loop_stage": 1}}
        result = router(state)
        assert result == "start_stage"

    def test_exits_when_condition_not_met(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = False

        stage_ref = {
            "name": "loop_stage",
            "loops_back_to": "start_stage",
            "max_loops": 3,
        }
        router = create_loop_router(stage_ref, "exit_stage", evaluator)

        state = {}
        result = router(state)
        assert result == "exit_stage"

    def test_exits_when_max_loops_exceeded(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = True

        stage_ref = {
            "name": "loop_stage",
            "loops_back_to": "start_stage",
            "max_loops": 2,
        }
        router = create_loop_router(stage_ref, "exit_stage", evaluator)

        from temper_ai.stage.executors.state_keys import StateKeys

        # count is 2, max_loops is 2, so 2 >= 2 → exit
        state = {StateKeys.STAGE_LOOP_COUNTS: {"loop_stage": 2}}
        result = router(state)
        assert result == "exit_stage"

    def test_multi_exit_targets_list(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = False  # exit path

        stage_ref = {
            "name": "loop_stage",
            "loops_back_to": "start",
            "max_loops": 2,
        }
        router = create_loop_router(stage_ref, ["exit1", "exit2"], evaluator)

        state = {}
        result = router(state)
        # Multi-exit returns list
        assert result == ["exit1", "exit2"]

    def test_multi_exit_with_none_resolved_to_end(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = False

        stage_ref = {
            "name": "loop_stage",
            "loops_back_to": "start",
            "max_loops": 2,
        }
        router = create_loop_router(stage_ref, [None, "other"], evaluator)

        state = {}
        result = router(state)
        assert result == [END, "other"]

    def test_loop_exit_none_resolved_to_end(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = False

        stage_ref = {
            "name": "loop_stage",
            "loops_back_to": "start",
            "max_loops": 2,
        }
        router = create_loop_router(stage_ref, None, evaluator)

        state = {}
        result = router(state)
        assert result == END

    def test_explicit_loop_condition_used(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = True

        stage_ref = {
            "name": "loop_stage",
            "loops_back_to": "start",
            "max_loops": 5,
            "loop_condition": "my_custom_condition",
        }
        router = create_loop_router(stage_ref, "exit", evaluator)
        state = {}
        router(state)
        # Should call evaluate with the explicit loop condition
        evaluator.evaluate.assert_called()

    def test_str_stage_ref_uses_ref_as_source_name(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = False

        stage_ref = SimpleNamespace(
            name="loop_stage",
            loops_back_to="start",
            max_loops=2,
            condition=None,
            loop_condition=None,
        )
        router = create_loop_router(stage_ref, "exit", evaluator)
        state = {}
        result = router(state)
        assert result == "exit"

    def test_loop_max_exceeded_with_multi_exit(self):
        evaluator = MagicMock()
        evaluator.evaluate.return_value = True  # would loop, but exceeded max

        stage_ref = {
            "name": "ls",
            "loops_back_to": "start",
            "max_loops": 1,
        }
        router = create_loop_router(stage_ref, ["e1", "e2"], evaluator)

        from temper_ai.stage.executors.state_keys import StateKeys

        state = {StateKeys.STAGE_LOOP_COUNTS: {"ls": 2}}
        result = router(state)
        assert result == ["e1", "e2"]
