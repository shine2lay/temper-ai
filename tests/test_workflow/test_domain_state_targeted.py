"""Targeted tests for workflow/domain_state.py to improve coverage from 88% to 90%+.

Covers missing lines: 292, 316, 320, 324, 342->346, 346->348, 348->352,
352->356, 356->360, 361, 417->419, 419->421, 422, 424.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from temper_ai.workflow.domain_state import (
    InfrastructureContext,
    WorkflowDomainState,
    create_initial_domain_state,
    merge_domain_states,
)


class TestWorkflowDomainStateValidation:
    def test_validate_valid_state(self):
        state = WorkflowDomainState(workflow_id="wf-abc123")
        is_valid, errors = state.validate()
        assert is_valid
        assert errors == []

    def test_validate_invalid_workflow_id(self):
        state = WorkflowDomainState()
        # Manually set invalid workflow_id (bypassing __post_init__ normalization)
        object.__setattr__(state, "workflow_id", "bad-id-no-prefix")
        is_valid, errors = state.validate()
        assert not is_valid
        assert any("workflow_id" in e for e in errors)

    def test_validate_missing_version(self):
        state = WorkflowDomainState()
        object.__setattr__(state, "version", "")
        is_valid, errors = state.validate()
        assert not is_valid
        assert any("version" in e for e in errors)


class TestWorkflowDomainStateCopy:
    def test_copy_creates_independent_instance(self):
        state = WorkflowDomainState(
            workflow_id="wf-abc123",
            stage_outputs={"s1": "output"},
            metadata={"key": "val"},
            workflow_inputs={"x": 1},
            stage_loop_counts={"a": 2},
            conversation_histories={"c": []},
            focus_areas=["area1"],
        )
        copy = state.copy()

        assert copy.workflow_id == state.workflow_id
        assert copy is not state

    def test_copy_deep_copies_stage_outputs(self):
        state = WorkflowDomainState(stage_outputs={"s1": {"nested": [1, 2, 3]}})
        copy = state.copy()
        copy.stage_outputs["s1"]["nested"].append(4)
        # Original should not be modified
        assert len(state.stage_outputs["s1"]["nested"]) == 3

    def test_copy_deep_copies_metadata(self):
        state = WorkflowDomainState(metadata={"a": [1, 2]})
        copy = state.copy()
        copy.metadata["a"].append(3)
        assert len(state.metadata["a"]) == 2

    def test_copy_deep_copies_workflow_inputs(self):
        state = WorkflowDomainState(workflow_inputs={"items": [1, 2]})
        copy = state.copy()
        copy.workflow_inputs["items"].append(3)
        assert len(state.workflow_inputs["items"]) == 2

    def test_copy_deep_copies_stage_loop_counts(self):
        state = WorkflowDomainState(stage_loop_counts={"stage1": 3})
        copy = state.copy()
        copy.stage_loop_counts["stage1"] = 99
        assert state.stage_loop_counts["stage1"] == 3

    def test_copy_deep_copies_conversation_histories(self):
        state = WorkflowDomainState(conversation_histories={"h": [{"role": "user"}]})
        copy = state.copy()
        copy.conversation_histories["h"].append({"role": "assistant"})
        assert len(state.conversation_histories["h"]) == 1

    def test_copy_copies_focus_areas_list(self):
        state = WorkflowDomainState(focus_areas=["tech", "finance"])
        copy = state.copy()
        copy.focus_areas.append("health")
        assert len(state.focus_areas) == 2

    def test_copy_with_none_focus_areas(self):
        state = WorkflowDomainState(focus_areas=None)
        copy = state.copy()
        assert copy.focus_areas is None


class TestWorkflowDomainStatePostInit:
    def test_focus_areas_non_list_converted(self):
        state = WorkflowDomainState(focus_areas="single_area")  # type: ignore
        assert isinstance(state.focus_areas, list)
        assert state.focus_areas == ["single_area"]

    def test_workflow_id_prefix_added_if_missing(self):
        state = WorkflowDomainState(workflow_id="my-custom-id")
        assert state.workflow_id.startswith("wf-")

    def test_stage_outputs_non_dict_converted(self):
        state = WorkflowDomainState.__new__(WorkflowDomainState)
        # Simulate bad stage_outputs
        object.__setattr__(state, "stage_outputs", "not-a-dict")
        object.__setattr__(state, "workflow_id", "wf-test")
        object.__setattr__(state, "focus_areas", None)
        state.__post_init__()
        assert isinstance(state.stage_outputs, dict)


class TestWorkflowDomainStateFromDict:
    def test_from_dict_preserves_known_fields(self):
        data = {
            "workflow_id": "wf-abc123",
            "current_stage": "s1",
            "stage_outputs": {"s1": "r1"},
        }
        state = WorkflowDomainState.from_dict(data)
        assert state.workflow_id == "wf-abc123"
        assert state.current_stage == "s1"

    def test_from_dict_unknown_fields_stored_in_workflow_inputs(self):
        data = {
            "workflow_id": "wf-abc123",
            "custom_field": "custom_value",
        }
        state = WorkflowDomainState.from_dict(data)
        assert state.workflow_inputs.get("custom_field") == "custom_value"

    def test_from_dict_merges_extra_with_existing_workflow_inputs(self):
        data = {
            "workflow_id": "wf-abc123",
            "workflow_inputs": {"existing": "val"},
            "extra_key": "extra_val",
        }
        state = WorkflowDomainState.from_dict(data)
        assert state.workflow_inputs.get("existing") == "val"
        assert state.workflow_inputs.get("extra_key") == "extra_val"

    def test_from_dict_datetime_string_parsed(self):
        dt = datetime(2024, 1, 1, tzinfo=UTC)
        data = {
            "workflow_id": "wf-abc123",
            "created_at": dt.isoformat(),
        }
        state = WorkflowDomainState.from_dict(data)
        assert isinstance(state.created_at, datetime)


class TestWorkflowDomainStateToDict:
    def test_to_dict_exclude_none(self):
        state = WorkflowDomainState(topic=None, depth=None)
        d = state.to_dict(exclude_none=True)
        assert "topic" not in d
        assert "depth" not in d

    def test_to_dict_includes_all_by_default(self):
        state = WorkflowDomainState(topic=None)
        d = state.to_dict(exclude_none=False)
        assert "topic" in d

    def test_to_dict_datetime_serialized(self):
        state = WorkflowDomainState()
        d = state.to_dict()
        assert isinstance(d["created_at"], str)


class TestInfrastructureContext:
    def test_repr_empty(self):
        ctx = InfrastructureContext()
        r = repr(ctx)
        assert "InfrastructureContext" in r
        assert "components=[]" in r

    def test_repr_with_components(self):
        ctx = InfrastructureContext(
            tracker=MagicMock(),
            tool_registry=MagicMock(),
        )
        r = repr(ctx)
        assert "tracker" in r
        assert "tool_registry" in r

    def test_all_fields_optional(self):
        ctx = InfrastructureContext()
        assert ctx.tracker is None
        assert ctx.tool_registry is None
        assert ctx.config_loader is None
        assert ctx.visualizer is None


class TestCreateInitialDomainState:
    def test_creates_with_kwargs(self):
        state = create_initial_domain_state(
            topic="AI", input="some input", depth="deep"
        )
        assert state.topic == "AI"
        assert state.input == "some input"
        assert state.depth == "deep"

    def test_workflow_id_auto_generated(self):
        state = create_initial_domain_state()
        assert state.workflow_id.startswith("wf-")


class TestMergeDomainStates:
    def test_merge_updates_field(self):
        base = WorkflowDomainState(current_stage="s1", topic="original")
        updated = merge_domain_states(base, {"topic": "updated"})
        assert updated.topic == "updated"
        assert updated.current_stage == "s1"

    def test_merge_does_not_modify_base(self):
        base = WorkflowDomainState(topic="original")
        merge_domain_states(base, {"topic": "changed"})
        assert base.topic == "original"


class TestExecutionContextDeprecation:
    def test_importing_execution_context_deprecated(self):
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from temper_ai.workflow.domain_state import ExecutionContext  # noqa: F401

            assert len(w) >= 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()

    def test_execution_context_is_infrastructure_context(self):
        import warnings

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            from temper_ai.workflow.domain_state import ExecutionContext

        assert ExecutionContext is InfrastructureContext

    def test_unknown_attr_raises_attribute_error(self):

        import temper_ai.workflow.domain_state as mod

        with pytest.raises(AttributeError):
            _ = mod.NonExistentAttribute  # type: ignore
