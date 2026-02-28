"""Tests for temper_ai/workflow/_runtime_helpers.py.

Covers:
- validate_file_size: within/exceeds limit
- validate_structure: delegates to validate_config_structure
- validate_schema: valid/invalid config
- check_required_inputs: none/present/missing
- resolve_path: absolute/relative/not found
- create_tracker: factory/bus/none
- emit_lifecycle_event: None bus no-op, valid bus
- load_workflow_config: happy path, all error paths
"""

from unittest.mock import MagicMock

import pytest

from temper_ai.shared.utils.exceptions import ConfigValidationError
from temper_ai.workflow._runtime_helpers import (
    check_required_inputs,
    create_tracker,
    emit_lifecycle_event,
    load_workflow_config,
    resolve_path,
    validate_file_size,
    validate_schema,
    validate_structure,
)

# ============================================================================
# validate_file_size
# ============================================================================


class TestValidateFileSize:
    """Tests for validate_file_size — rejects oversized config files."""

    def test_small_file_passes(self, tmp_path):
        """File within size limit passes validation."""
        f = tmp_path / "small.yaml"
        f.write_text("key: value\n")
        validate_file_size(f)  # Should not raise

    def test_oversized_file_raises(self, tmp_path):
        """File exceeding MAX_CONFIG_SIZE raises ConfigValidationError."""
        from temper_ai.workflow.security_limits import CONFIG_SECURITY

        f = tmp_path / "big.yaml"
        f.write_bytes(b"x" * (CONFIG_SECURITY.MAX_CONFIG_SIZE + 1))
        with pytest.raises(ConfigValidationError, match="Config file too large"):
            validate_file_size(f)


# ============================================================================
# validate_structure
# ============================================================================


class TestValidateStructure:
    """Tests for validate_structure — delegates to validate_config_structure."""

    def test_valid_structure(self, tmp_path):
        """Flat config passes structure validation."""
        validate_structure({"a": 1}, tmp_path / "f.yaml")  # Should not raise

    def test_deeply_nested_raises(self, tmp_path):
        """Excessively nested config raises ConfigValidationError."""
        from temper_ai.workflow.security_limits import CONFIG_SECURITY

        nested: dict = {}
        current = nested
        for _ in range(CONFIG_SECURITY.MAX_YAML_NESTING_DEPTH + 2):
            current["child"] = {}
            current = current["child"]

        with pytest.raises(ConfigValidationError, match="maximum nesting depth"):
            validate_structure(nested, tmp_path / "deep.yaml")


# ============================================================================
# validate_schema
# ============================================================================


class TestValidateSchema:
    """Tests for validate_schema — Pydantic validation of WorkflowConfig."""

    def test_valid_workflow_passes(self):
        """Minimal valid workflow config passes schema validation."""
        config = {
            "workflow": {
                "name": "test_wf",
                "description": "A test workflow",
                "stages": [
                    {"name": "stage1", "stage_ref": "my_stage"},
                ],
                "error_handling": {
                    "escalation_policy": "my_module.policy",
                },
            }
        }
        validate_schema(config)  # Should not raise

    def test_invalid_config_raises(self):
        """Invalid config raises ConfigValidationError."""
        with pytest.raises(
            ConfigValidationError, match="Workflow schema validation failed"
        ):
            validate_schema({"invalid": True})


# ============================================================================
# check_required_inputs
# ============================================================================


class TestCheckRequiredInputs:
    """Tests for check_required_inputs — missing required input detection."""

    def test_no_required_inputs(self):
        """Returns empty list when no required inputs defined."""
        result = check_required_inputs({"workflow": {}}, {"any": "input"})
        assert result == []

    def test_all_required_present(self):
        """Returns empty list when all required inputs provided."""
        config = {"workflow": {"inputs": {"required": ["a", "b"]}}}
        result = check_required_inputs(config, {"a": 1, "b": 2})
        assert result == []

    def test_some_missing(self):
        """Returns list of missing required input names."""
        config = {"workflow": {"inputs": {"required": ["a", "b", "c"]}}}
        result = check_required_inputs(config, {"a": 1})
        assert "b" in result
        assert "c" in result
        assert "a" not in result

    def test_empty_config(self):
        """Empty config returns empty list."""
        result = check_required_inputs({}, {})
        assert result == []

    def test_no_inputs_section(self):
        """Config without 'inputs' section returns empty list."""
        result = check_required_inputs({"workflow": {"name": "test"}}, {})
        assert result == []


# ============================================================================
# resolve_path
# ============================================================================


class TestResolvePath:
    """Tests for resolve_path — absolute, relative, not found."""

    def test_absolute_path_exists(self, tmp_path):
        """Returns absolute path when it exists."""
        f = tmp_path / "workflow.yaml"
        f.write_text("test")
        result = resolve_path(str(f), str(tmp_path))
        assert result == f

    def test_relative_in_config_root(self, tmp_path):
        """Resolves relative path against config_root."""
        f = tmp_path / "wf.yaml"
        f.write_text("test")
        result = resolve_path("wf.yaml", str(tmp_path))
        assert result == f

    def test_not_found_raises(self, tmp_path):
        """Raises FileNotFoundError when workflow file doesn't exist."""
        with pytest.raises(FileNotFoundError, match="Workflow file not found"):
            resolve_path("nonexistent.yaml", str(tmp_path))

    def test_relative_path_exists_directly(self, tmp_path, monkeypatch):
        """Falls back to checking path relative to cwd."""
        monkeypatch.chdir(tmp_path)
        f = tmp_path / "local.yaml"
        f.write_text("test")
        # config_root doesn't contain the file, but cwd does
        other = tmp_path / "other"
        other.mkdir()
        result = resolve_path("local.yaml", str(other))
        # The function returns the relative path when found in cwd
        assert result.resolve() == f.resolve()


# ============================================================================
# create_tracker
# ============================================================================


class TestCreateTracker:
    """Tests for create_tracker — factory, bus, default."""

    def test_with_factory(self):
        """Creates tracker from factory backend."""
        mock_backend = MagicMock()
        factory = MagicMock(return_value=mock_backend)
        tracker = create_tracker(factory)
        factory.assert_called_once()
        assert tracker is not None

    def test_factory_returns_none_with_bus(self):
        """Falls through to event_bus when factory returns None."""
        factory = MagicMock(return_value=None)
        mock_bus = MagicMock()
        tracker = create_tracker(factory, event_bus=mock_bus)
        assert tracker is not None

    def test_with_event_bus_only(self):
        """Creates tracker from event bus when no factory."""
        mock_bus = MagicMock()
        tracker = create_tracker(None, event_bus=mock_bus)
        assert tracker is not None

    def test_no_factory_no_bus(self):
        """Creates default tracker when no factory or bus."""
        tracker = create_tracker(None)
        assert tracker is not None


# ============================================================================
# emit_lifecycle_event
# ============================================================================


class TestEmitLifecycleEvent:
    """Tests for emit_lifecycle_event — None bus no-op, valid bus emits."""

    def test_none_bus_noop(self):
        """Does nothing when event_bus is None."""
        # Should not raise
        emit_lifecycle_event(None, "wf-1", "config_loaded", {"key": "val"})

    def test_valid_bus_emits(self):
        """Emits ObservabilityEvent on valid bus."""
        mock_bus = MagicMock()
        emit_lifecycle_event(mock_bus, "wf-1", "config_loaded", {"key": "val"})
        mock_bus.emit.assert_called_once()
        event = mock_bus.emit.call_args[0][0]
        assert event.event_type == "config_loaded"
        assert event.workflow_id == "wf-1"

    def test_event_data_passed(self):
        """Event data dict is included in emitted event."""
        mock_bus = MagicMock()
        data = {"stage_count": 3}
        emit_lifecycle_event(mock_bus, "wf-2", "config_loaded", data)
        event = mock_bus.emit.call_args[0][0]
        assert event.data["stage_count"] == 3


# ============================================================================
# load_workflow_config
# ============================================================================


class TestLoadWorkflowConfig:
    """Tests for load_workflow_config — end-to-end workflow loading."""

    def _write_valid_workflow(self, tmp_path):
        """Helper to write a minimal valid workflow YAML."""
        f = tmp_path / "test.yaml"
        f.write_text(
            "workflow:\n"
            "  name: test_wf\n"
            "  description: A test workflow\n"
            "  stages:\n"
            "    - name: stage1\n"
            "      stage_ref: my_stage\n"
            "  error_handling:\n"
            "    escalation_policy: my_module.policy\n"
        )
        return f

    def test_happy_path(self, tmp_path):
        """Loads valid workflow and returns config + inputs tuple."""
        self._write_valid_workflow(tmp_path)
        mock_bus = MagicMock()
        config, inputs = load_workflow_config(
            "test.yaml", str(tmp_path), mock_bus, "wf-1"
        )
        assert config["workflow"]["name"] == "test_wf"
        assert inputs == {}

    def test_with_input_data(self, tmp_path):
        """Input data dict is returned in the tuple."""
        self._write_valid_workflow(tmp_path)
        config, inputs = load_workflow_config(
            "test.yaml", str(tmp_path), None, "wf-1", input_data={"key": "val"}
        )
        assert inputs == {"key": "val"}

    def test_file_not_found(self, tmp_path):
        """Raises FileNotFoundError for missing workflow file."""
        with pytest.raises(FileNotFoundError):
            load_workflow_config("missing.yaml", str(tmp_path), None, "wf-1")

    def test_invalid_yaml_raises(self, tmp_path):
        """Raises ConfigValidationError for unparseable YAML."""
        f = tmp_path / "bad.yaml"
        f.write_text(":\n  {{invalid}}\n  : :")
        with pytest.raises(ConfigValidationError, match="YAML parsing failed"):
            load_workflow_config("bad.yaml", str(tmp_path), None, "wf-1")

    def test_empty_file_raises(self, tmp_path):
        """Raises ConfigValidationError for empty YAML file."""
        f = tmp_path / "empty.yaml"
        f.write_text("")
        with pytest.raises(ConfigValidationError, match="Empty workflow file"):
            load_workflow_config("empty.yaml", str(tmp_path), None, "wf-1")

    def test_non_mapping_raises(self, tmp_path):
        """Raises ValueError when YAML is a list instead of mapping."""
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_workflow_config("list.yaml", str(tmp_path), None, "wf-1")

    def test_lifecycle_event_emitted(self, tmp_path):
        """Emits EVENT_CONFIG_LOADED event on success."""
        self._write_valid_workflow(tmp_path)
        mock_bus = MagicMock()
        load_workflow_config("test.yaml", str(tmp_path), mock_bus, "wf-1")
        mock_bus.emit.assert_called_once()
        event = mock_bus.emit.call_args[0][0]
        assert "workflow_path" in event.data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
