"""
Tests for configuration management and merging.

Tests deep merge logic, security validation, and Pydantic schema validation.
"""

import pytest

from temper_ai.experimentation.config_manager import (
    PROTECTED_CONFIG_FIELDS,
    ConfigManager,
    ExperimentConfigValidationError,
    SecurityViolationError,
    merge_agent_config,
    merge_stage_config,
    merge_workflow_config,
)


class TestDeepMerge:
    """Test deep merge functionality."""

    def test_simple_merge(self):
        """Test simple key override."""
        manager = ConfigManager()

        base = {"a": 1, "b": 2}
        overrides = {"b": 3, "c": 4}

        result = manager.merge_config(base, overrides, validate_protected=False)

        assert result == {"a": 1, "b": 3, "c": 4}
        # Original base should be unchanged
        assert base == {"a": 1, "b": 2}

    def test_nested_merge(self):
        """Test nested dictionary merge."""
        manager = ConfigManager()

        base = {
            "agent": {
                "model": "gpt-4",
                "temperature": 0.7,
                "max_tokens": 2048
            },
            "timeout": 30
        }
        overrides = {
            "agent": {
                "temperature": 0.9,
                "top_p": 0.95
            }
        }

        result = manager.merge_config(base, overrides, validate_protected=False)

        assert result == {
            "agent": {
                "model": "gpt-4",
                "temperature": 0.9,  # Overridden
                "max_tokens": 2048,  # Preserved
                "top_p": 0.95  # Added
            },
            "timeout": 30  # Preserved
        }

    def test_deep_nested_merge(self):
        """Test deeply nested merge (3+ levels)."""
        manager = ConfigManager()

        base = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": "original",
                        "keep": "preserved"
                    }
                }
            }
        }
        overrides = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": "overridden"
                    }
                }
            }
        }

        result = manager.merge_config(base, overrides, validate_protected=False)

        assert result["level1"]["level2"]["level3"]["value"] == "overridden"
        assert result["level1"]["level2"]["level3"]["keep"] == "preserved"

    def test_merge_replaces_non_dict(self):
        """Test that non-dict values are replaced, not merged."""
        manager = ConfigManager()

        base = {"config": {"value": [1, 2, 3]}}
        overrides = {"config": {"value": [4, 5]}}

        result = manager.merge_config(base, overrides, validate_protected=False)

        # List should be replaced, not merged
        assert result["config"]["value"] == [4, 5]

    def test_merge_empty_overrides(self):
        """Test merge with empty overrides."""
        manager = ConfigManager()

        base = {"a": 1, "b": 2}
        overrides = {}

        result = manager.merge_config(base, overrides, validate_protected=False)

        assert result == base

    def test_merge_empty_base(self):
        """Test merge with empty base."""
        manager = ConfigManager()

        base = {}
        overrides = {"a": 1, "b": 2}

        result = manager.merge_config(base, overrides, validate_protected=False)

        assert result == overrides


class TestSecurityValidation:
    """Test security validation for protected fields."""

    def test_protected_field_api_key(self):
        """Test that api_key override is blocked."""
        manager = ConfigManager()

        base = {"model": "gpt-4"}
        overrides = {"api_key": "sk-secret"}

        with pytest.raises(SecurityViolationError, match="api_key"):
            manager.merge_config(base, overrides, validate_protected=True)

    def test_protected_field_secret(self):
        """Test that secret override is blocked."""
        manager = ConfigManager()

        base = {"model": "gpt-4"}
        overrides = {"secret": "my-secret"}

        with pytest.raises(SecurityViolationError, match="secret"):
            manager.merge_config(base, overrides)

    def test_protected_field_nested(self):
        """Test that nested protected field is blocked."""
        manager = ConfigManager()

        base = {"config": {"model": "gpt-4"}}
        overrides = {"config": {"api_key_ref": "secret-ref"}}

        with pytest.raises(SecurityViolationError, match="api_key_ref"):
            manager.merge_config(base, overrides)

    def test_protected_field_deep_nested(self):
        """Test that deeply nested protected field is blocked."""
        manager = ConfigManager()

        base = {}
        overrides = {
            "level1": {
                "level2": {
                    "password": "secret123"
                }
            }
        }

        with pytest.raises(SecurityViolationError, match="password"):
            manager.merge_config(base, overrides)

    def test_all_protected_fields(self):
        """Test all default protected fields are blocked."""
        manager = ConfigManager()
        base = {}

        for field in PROTECTED_CONFIG_FIELDS:
            overrides = {field: "value"}

            with pytest.raises(SecurityViolationError):
                manager.merge_config(base, overrides)

    def test_bypass_protection(self):
        """Test that validation can be bypassed if needed."""
        manager = ConfigManager()

        base = {}
        overrides = {"api_key": "sk-secret"}

        # Should work when validation disabled
        result = manager.merge_config(base, overrides, validate_protected=False)

        assert result["api_key"] == "sk-secret"

    def test_custom_protected_fields(self):
        """Test custom protected field set."""
        manager = ConfigManager(protected_fields={"custom_field"})

        base = {}
        overrides = {"custom_field": "value"}

        with pytest.raises(SecurityViolationError, match="custom_field"):
            manager.merge_config(base, overrides)

    def test_safe_fields_allowed(self):
        """Test that non-protected fields are allowed."""
        manager = ConfigManager()

        base = {}
        overrides = {
            "model": "gpt-4",
            "temperature": 0.9,
            "max_tokens": 4096,
            "custom_setting": "value"
        }

        # Should not raise
        result = manager.merge_config(base, overrides)

        assert result == overrides


class TestConfigDiff:
    """Test configuration diff generation."""

    def test_diff_simple_change(self):
        """Test diff with simple value change."""
        manager = ConfigManager()

        base = {"a": 1, "b": 2}
        variant = {"a": 5, "b": 2}

        diff = manager.get_config_diff(base, variant)

        assert diff == {"a": {"old": 1, "new": 5}}

    def test_diff_added_key(self):
        """Test diff with added key."""
        manager = ConfigManager()

        base = {"a": 1}
        variant = {"a": 1, "b": 2}

        diff = manager.get_config_diff(base, variant)

        assert diff == {"b": {"added": 2}}

    def test_diff_nested_change(self):
        """Test diff with nested change."""
        manager = ConfigManager()

        base = {"config": {"temperature": 0.7, "model": "gpt-4"}}
        variant = {"config": {"temperature": 0.9, "model": "gpt-4"}}

        diff = manager.get_config_diff(base, variant)

        assert diff == {"config": {"temperature": {"old": 0.7, "new": 0.9}}}

    def test_diff_no_changes(self):
        """Test diff with no changes."""
        manager = ConfigManager()

        base = {"a": 1, "b": 2}
        variant = {"a": 1, "b": 2}

        diff = manager.get_config_diff(base, variant)

        assert diff == {}


class TestConvenienceFunctions:
    """Test convenience merge functions."""

    def test_merge_agent_config(self):
        """Test agent config merge convenience function."""
        base = {
            "name": "researcher",
            "model": "gpt-4",
            "inference": {"temperature": 0.7}
        }
        overrides = {
            "inference": {"temperature": 0.9, "max_tokens": 4096}
        }

        result = merge_agent_config(base, overrides)

        assert result["inference"]["temperature"] == 0.9
        assert result["inference"]["max_tokens"] == 4096
        assert result["model"] == "gpt-4"

    def test_merge_stage_config(self):
        """Test stage config merge convenience function."""
        base = {
            "name": "research",
            "agents": ["researcher", "analyzer"]
        }
        overrides = {
            "agents": ["researcher", "analyzer", "synthesizer"]
        }

        result = merge_stage_config(base, overrides)

        assert result["agents"] == ["researcher", "analyzer", "synthesizer"]

    def test_merge_workflow_config(self):
        """Test workflow config merge convenience function."""
        base = {
            "name": "research_workflow",
            "stages": ["research", "analyze"]
        }
        overrides = {
            "optimization_target": "speed"
        }

        result = merge_workflow_config(base, overrides)

        assert result["optimization_target"] == "speed"
        assert result["stages"] == ["research", "analyze"]


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_merge_with_none_values(self):
        """Test merge with None values."""
        manager = ConfigManager()

        base = {"a": 1, "b": None}
        overrides = {"a": None, "c": 3}

        result = manager.merge_config(base, overrides, validate_protected=False)

        assert result == {"a": None, "b": None, "c": 3}

    def test_merge_with_boolean(self):
        """Test merge with boolean values."""
        manager = ConfigManager()

        base = {"enabled": True, "verbose": False}
        overrides = {"enabled": False}

        result = manager.merge_config(base, overrides, validate_protected=False)

        assert result["enabled"] is False
        assert result["verbose"] is False

    def test_merge_preserves_types(self):
        """Test that merge preserves value types."""
        manager = ConfigManager()

        base = {"int": 1, "float": 1.5, "str": "text", "bool": True, "list": [1, 2]}
        overrides = {"int": 2}

        result = manager.merge_config(base, overrides, validate_protected=False)

        assert isinstance(result["int"], int)
        assert isinstance(result["float"], float)
        assert isinstance(result["str"], str)
        assert isinstance(result["bool"], bool)
        assert isinstance(result["list"], list)

    def test_merge_complex_config(self):
        """Test merge with realistic complex config."""
        manager = ConfigManager()

        base = {
            "workflow": {
                "name": "research_workflow",
                "version": "1.0",
                "stages": {
                    "research": {
                        "agents": ["researcher"],
                        "collaboration": "sequential",
                        "config": {
                            "model": "gpt-4",
                            "temperature": 0.7,
                            "max_tokens": 2048
                        }
                    }
                }
            }
        }
        overrides = {
            "workflow": {
                "stages": {
                    "research": {
                        "config": {
                            "temperature": 0.9,
                            "top_p": 0.95
                        }
                    }
                }
            }
        }

        result = manager.merge_config(base, overrides, validate_protected=False)

        # Check deep merge worked correctly
        research_config = result["workflow"]["stages"]["research"]["config"]
        assert research_config["temperature"] == 0.9  # Overridden
        assert research_config["max_tokens"] == 2048  # Preserved
        assert research_config["top_p"] == 0.95  # Added
        assert result["workflow"]["stages"]["research"]["agents"] == ["researcher"]  # Preserved


class TestApplyOverridesSafely:
    """Test the all-in-one safe apply method."""

    def test_apply_overrides_safely_success(self):
        """Test safe apply with valid config."""
        manager = ConfigManager()

        base = {"model": "gpt-4", "temperature": 0.7}
        overrides = {"temperature": 0.9}

        result = manager.apply_overrides_safely(base, overrides)

        assert result["temperature"] == 0.9

    def test_apply_overrides_safely_security_violation(self):
        """Test safe apply with security violation."""
        manager = ConfigManager()

        base = {"model": "gpt-4"}
        overrides = {"api_key": "sk-secret"}

        with pytest.raises(SecurityViolationError):
            manager.apply_overrides_safely(base, overrides)

    def test_apply_overrides_safely_with_schema(self):
        """Test safe apply with Pydantic schema validation."""
        from pydantic import BaseModel

        class AgentConfig(BaseModel):
            model: str
            temperature: float

        manager = ConfigManager()

        base = {"model": "gpt-4", "temperature": 0.7}
        overrides = {"temperature": 0.9}

        # Should pass validation
        result = manager.apply_overrides_safely(
            base, overrides,
            schema_class=AgentConfig
        )

        assert result["temperature"] == 0.9

    def test_apply_overrides_safely_invalid_schema(self):
        """Test safe apply with invalid config against schema."""
        from pydantic import BaseModel

        class AgentConfig(BaseModel):
            model: str
            temperature: float

        manager = ConfigManager()

        base = {"model": "gpt-4"}
        overrides = {"temperature": "invalid"}  # Should be float

        with pytest.raises(ExperimentConfigValidationError):
            manager.apply_overrides_safely(
                base, overrides,
                schema_class=AgentConfig
            )


class TestExtractOverrides:
    """Test extract_overrides_from_variant function."""

    def test_extract_config_overrides_key(self):
        """Test extracting from config_overrides key."""
        from temper_ai.experimentation.config_manager import extract_overrides_from_variant

        variant = {
            "name": "variant_a",
            "config_overrides": {"temperature": 0.9}
        }

        overrides = extract_overrides_from_variant(variant)
        assert overrides == {"temperature": 0.9}

    def test_extract_config_key(self):
        """Test extracting from config key."""
        from temper_ai.experimentation.config_manager import extract_overrides_from_variant

        variant = {
            "name": "variant_a",
            "config": {"temperature": 0.9}
        }

        overrides = extract_overrides_from_variant(variant)
        assert overrides == {"temperature": 0.9}

    def test_extract_overrides_key(self):
        """Test extracting from overrides key."""
        from temper_ai.experimentation.config_manager import extract_overrides_from_variant

        variant = {
            "name": "variant_a",
            "overrides": {"temperature": 0.9}
        }

        overrides = extract_overrides_from_variant(variant)
        assert overrides == {"temperature": 0.9}

    def test_extract_no_known_key(self):
        """Test extracting when no known key exists - returns entire dict."""
        from temper_ai.experimentation.config_manager import extract_overrides_from_variant

        variant = {
            "temperature": 0.9,
            "max_tokens": 4096,
        }

        overrides = extract_overrides_from_variant(variant)
        assert overrides == {"temperature": 0.9, "max_tokens": 4096}

    def test_extract_priority(self):
        """Test that config_overrides has priority over other keys."""
        from temper_ai.experimentation.config_manager import extract_overrides_from_variant

        variant = {
            "name": "variant_a",
            "config_overrides": {"temperature": 0.9},
            "config": {"temperature": 0.7},  # Should be ignored
        }

        overrides = extract_overrides_from_variant(variant)
        assert overrides == {"temperature": 0.9}
