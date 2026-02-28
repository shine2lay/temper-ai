"""Tests for temper_ai/stage/executors/state_keys.py.

Covers:
- StateKeys constant values are strings
- NON_SERIALIZABLE_KEYS frozenset content
- RESERVED_UNWRAP_KEYS frozenset content
"""

from temper_ai.stage.executors.state_keys import StateKeys


class TestStateKeyConstants:
    """Tests for StateKeys string constants."""

    def test_top_level_keys_are_strings(self):
        """Top-level state keys are all strings."""
        keys = [
            StateKeys.STAGE_OUTPUTS,
            StateKeys.CURRENT_STAGE,
            StateKeys.WORKFLOW_ID,
            StateKeys.WORKFLOW_INPUTS,
            StateKeys.TRACKER,
            StateKeys.TOOL_REGISTRY,
            StateKeys.CONFIG_LOADER,
        ]
        for key in keys:
            assert isinstance(key, str), f"{key} is not a string"

    def test_agent_result_keys_are_strings(self):
        """Agent result keys are all strings."""
        keys = [
            StateKeys.AGENT_NAME,
            StateKeys.OUTPUT_DATA,
            StateKeys.STATUS,
            StateKeys.METRICS,
        ]
        for key in keys:
            assert isinstance(key, str)

    def test_expected_key_values(self):
        """Key values match expected strings."""
        assert StateKeys.STAGE_OUTPUTS == "stage_outputs"
        assert StateKeys.WORKFLOW_ID == "workflow_id"
        assert StateKeys.TRACKER == "tracker"
        assert StateKeys.ERRORS == "errors"
        assert StateKeys.CONFIDENCE == "confidence"

    def test_special_marker_keys(self):
        """Special marker keys have expected values."""
        assert StateKeys.AGGREGATE_METRICS_KEY == "__aggregate_metrics__"
        assert StateKeys.SKIP_TO_END == "_skip_to_end"
        assert StateKeys.DYNAMIC_INPUTS == "_dynamic_inputs"


class TestNonSerializableKeys:
    """Tests for NON_SERIALIZABLE_KEYS frozenset."""

    def test_is_frozenset(self):
        """NON_SERIALIZABLE_KEYS is a frozenset."""
        assert isinstance(StateKeys.NON_SERIALIZABLE_KEYS, frozenset)

    def test_contains_expected_keys(self):
        """Contains keys that should not be serialized."""
        expected = {"tracker", "tool_registry", "config_loader", "tool_executor"}
        assert expected.issubset(StateKeys.NON_SERIALIZABLE_KEYS)

    def test_does_not_contain_user_keys(self):
        """Does not contain user-visible state keys."""
        user_keys = {"stage_outputs", "workflow_id", "workflow_inputs", "errors"}
        for key in user_keys:
            assert key not in StateKeys.NON_SERIALIZABLE_KEYS


class TestReservedUnwrapKeys:
    """Tests for RESERVED_UNWRAP_KEYS frozenset."""

    def test_is_frozenset(self):
        """RESERVED_UNWRAP_KEYS is a frozenset."""
        assert isinstance(StateKeys.RESERVED_UNWRAP_KEYS, frozenset)

    def test_contains_expected_keys(self):
        """Contains keys that should be reserved during unwrap."""
        expected = {"stage_outputs", "current_stage", "workflow_id", "tracker"}
        assert expected.issubset(StateKeys.RESERVED_UNWRAP_KEYS)

    def test_tracker_in_both_sets(self):
        """Tracker key appears in both frozensets."""
        assert "tracker" in StateKeys.NON_SERIALIZABLE_KEYS
        assert "tracker" in StateKeys.RESERVED_UNWRAP_KEYS
