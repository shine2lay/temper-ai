"""Tests for LangGraphWorkflowState to_dict() cache safety.

Verifies that to_dict() returns independent copies so callers
cannot corrupt the internal cache by mutating the returned dict.
"""

from src.workflow.langgraph_state import LangGraphWorkflowState


class TestToDictCacheMutationSafety:
    """Verify that mutating returned dicts does not corrupt the cache."""

    def test_mutate_returned_dict_does_not_affect_next_call(self):
        """Mutating returned dict should not change subsequent to_dict() results."""
        state = LangGraphWorkflowState(topic="test")

        d1 = state.to_dict()
        d1["topic"] = "CORRUPTED"
        d1["injected_key"] = "bad_value"

        d2 = state.to_dict()
        assert d2["topic"] == "test"
        assert "injected_key" not in d2

    def test_mutate_returned_dict_exclude_internal(self):
        """Same protection applies when exclude_internal=True."""
        state = LangGraphWorkflowState(topic="safe")

        d1 = state.to_dict(exclude_internal=True)
        d1["topic"] = "CORRUPTED"
        d1["extra"] = 123

        d2 = state.to_dict(exclude_internal=True)
        assert d2["topic"] == "safe"
        assert "extra" not in d2

    def test_two_callers_get_independent_dicts(self):
        """Two callers should receive independent dict objects."""
        state = LangGraphWorkflowState(topic="original")

        d1 = state.to_dict()
        d2 = state.to_dict()

        assert d1 is not d2
        assert d1 == d2

        d1["topic"] = "changed_by_caller_1"
        assert d2["topic"] == "original"

    def test_two_callers_exclude_internal_independent(self):
        """Independent dicts for exclude_internal=True path."""
        state = LangGraphWorkflowState(topic="original")

        d1 = state.to_dict(exclude_internal=True)
        d2 = state.to_dict(exclude_internal=True)

        assert d1 is not d2
        assert d1 == d2

        d1["topic"] = "changed"
        assert d2["topic"] == "original"

    def test_delete_key_from_returned_dict_no_effect(self):
        """Deleting a key from returned dict should not affect cache."""
        state = LangGraphWorkflowState(topic="keep_me")

        d1 = state.to_dict()
        del d1["topic"]

        d2 = state.to_dict()
        assert "topic" in d2
        assert d2["topic"] == "keep_me"

    def test_cache_invalidated_on_field_change(self):
        """Modifying state field should invalidate cache and return new data."""
        state = LangGraphWorkflowState(topic="v1")

        d1 = state.to_dict()
        assert d1["topic"] == "v1"

        state.topic = "v2"

        d2 = state.to_dict()
        assert d2["topic"] == "v2"

    def test_cache_invalidated_exclude_internal_on_field_change(self):
        """Field change invalidates exclude_internal cache too."""
        state = LangGraphWorkflowState(depth="shallow")

        d1 = state.to_dict(exclude_internal=True)
        assert d1["depth"] == "shallow"

        state.depth = "deep"

        d2 = state.to_dict(exclude_internal=True)
        assert d2["depth"] == "deep"

    def test_mixed_calls_no_cross_contamination(self):
        """Calls with different exclude_internal values don't cross-contaminate."""
        state = LangGraphWorkflowState(topic="mix", tracker="my_tracker")

        full = state.to_dict(exclude_internal=False)
        partial = state.to_dict(exclude_internal=True)

        assert "tracker" in full
        assert "tracker" not in partial

        # Mutate one, check the other
        full["topic"] = "CORRUPTED"
        partial_again = state.to_dict(exclude_internal=True)
        assert partial_again["topic"] == "mix"

    def test_to_typed_dict_also_safe(self):
        """to_typed_dict() delegates to to_dict() and should also be safe."""
        state = LangGraphWorkflowState(topic="typed")

        d1 = state.to_typed_dict()
        d1["topic"] = "CORRUPTED"

        d2 = state.to_typed_dict()
        assert d2["topic"] == "typed"


class TestToDictExcludeInternal:
    """Verify exclude_internal correctly filters infrastructure fields."""

    def test_exclude_internal_removes_infrastructure(self):
        state = LangGraphWorkflowState(
            topic="test",
            tracker="t",
            tool_registry="r",
            config_loader="c",
            visualizer="v",
        )
        d = state.to_dict(exclude_internal=True)
        for key in ("tracker", "tool_registry", "config_loader", "visualizer"):
            assert key not in d

    def test_include_internal_keeps_infrastructure(self):
        state = LangGraphWorkflowState(
            tracker="t",
            tool_registry="r",
            config_loader="c",
            visualizer="v",
        )
        d = state.to_dict(exclude_internal=False)
        for key in ("tracker", "tool_registry", "config_loader", "visualizer"):
            assert key in d


class TestPostInit:
    """Verify __post_init__ validation logic."""

    def test_focus_areas_coerced_to_list(self):
        state = LangGraphWorkflowState(focus_areas="single")  # type: ignore
        assert state.focus_areas == ["single"]

    def test_workflow_id_prefix_added(self):
        state = LangGraphWorkflowState(workflow_id="abc123")
        assert state.workflow_id == "wf-abc123"

    def test_workflow_id_prefix_not_doubled(self):
        state = LangGraphWorkflowState(workflow_id="wf-abc123")
        assert state.workflow_id == "wf-abc123"

    def test_invalid_stage_outputs_reset(self):
        state = LangGraphWorkflowState(stage_outputs="not_a_dict")  # type: ignore
        assert state.stage_outputs == {}
