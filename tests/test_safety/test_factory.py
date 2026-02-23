"""Tests for safety stack factory — policy registry creation and safety stack.

Verifies that create_policy_registry() correctly loads and registers
built-in policies, and that create_safety_stack() selects the correct
approver based on environment.
"""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.safety.approval import ApprovalWorkflow, NoOpApprover
from temper_ai.safety.factory import (
    BUILTIN_POLICIES,
    _get_default_config,
    create_policy_registry,
    create_safety_stack,
)
from temper_ai.safety.policy_registry import PolicyRegistry
from temper_ai.tools.registry import ToolRegistry


class TestCreatePolicyRegistryWithDefaults:
    """Test create_policy_registry with default (empty) config."""

    def test_empty_config_returns_empty_registry(self):
        """Default config with no mappings returns empty registry."""
        config = _get_default_config()
        registry = create_policy_registry(config)
        assert isinstance(registry, PolicyRegistry)
        assert registry.policy_count() == 0

    def test_empty_dict_returns_empty_registry(self):
        """Completely empty dict returns empty registry."""
        registry = create_policy_registry({})
        assert registry.policy_count() == 0


class TestCreatePolicyRegistryWithMappings:
    """Test create_policy_registry with policy_mappings config."""

    def test_registers_single_policy(self):
        """Single policy in mappings is registered."""
        config = {
            "policy_mappings": {
                "file_write": ["secret_detection_policy"],
            },
        }
        registry = create_policy_registry(config)
        assert registry.policy_count() == 1
        assert registry.is_registered("secret_detection")

    def test_registers_multiple_policies(self):
        """Multiple policies across action types are registered."""
        config = {
            "policy_mappings": {
                "file_write": [
                    "secret_detection_policy",
                    "file_access_policy",
                ],
                "git_commit": [
                    "blast_radius_policy",
                    "forbidden_ops_policy",
                ],
            },
        }
        registry = create_policy_registry(config)
        assert registry.policy_count() == 4
        assert registry.is_registered("secret_detection")
        assert registry.is_registered("file_access")
        assert registry.is_registered("blast_radius")
        assert registry.is_registered("forbidden_operations")

    def test_policy_mapped_to_correct_action_types(self):
        """Policies are retrievable for their mapped action types."""
        config = {
            "policy_mappings": {
                "file_write": ["file_access_policy"],
                "file_read": ["file_access_policy"],
            },
        }
        registry = create_policy_registry(config)
        assert len(registry.get_policies_for_action("file_write")) == 1
        assert len(registry.get_policies_for_action("file_read")) == 1
        assert registry.get_policies_for_action("file_write")[0].name == "file_access"

    def test_shared_policy_registered_once(self):
        """A policy used in multiple action types is only instantiated once."""
        config = {
            "policy_mappings": {
                "file_write": ["secret_detection_policy"],
                "git_commit": ["secret_detection_policy"],
                "bash_command": ["secret_detection_policy"],
            },
        }
        registry = create_policy_registry(config)
        assert registry.policy_count() == 1
        # But it's available for all three action types
        for action_type in ["file_write", "git_commit", "bash_command"]:
            policies = registry.get_policies_for_action(action_type)
            assert len(policies) == 1
            assert policies[0].name == "secret_detection"


class TestGlobalPolicies:
    """Test global policy registration."""

    def test_global_policy_registered(self):
        """Policies in global_policies are registered globally."""
        config = {
            "global_policies": ["rate_limit_policy"],
        }
        registry = create_policy_registry(config)
        assert registry.policy_count() == 1
        assert registry.is_registered("rate_limit")

    def test_global_policy_applies_to_all_actions(self):
        """Global policies appear for any action type query."""
        config = {
            "global_policies": ["resource_limit_policy"],
        }
        registry = create_policy_registry(config)
        # Global policies should appear for arbitrary action types
        policies = registry.get_policies_for_action("file_write")
        assert len(policies) == 1
        assert policies[0].name == "resource_limit"

        policies = registry.get_policies_for_action("arbitrary_action")
        assert len(policies) == 1


class TestUnknownPolicies:
    """Test handling of unknown policy names."""

    def test_unknown_policy_skipped(self):
        """Unknown policy names are skipped (not registered)."""
        config = {
            "policy_mappings": {
                "file_write": [
                    "secret_detection_policy",
                    "nonexistent_policy",
                ],
            },
        }
        registry = create_policy_registry(config)
        assert registry.policy_count() == 1
        assert registry.is_registered("secret_detection")
        assert not registry.is_registered("nonexistent_policy")

    def test_all_unknown_policies_result_in_empty_registry(self):
        """Config with only unknown policies results in empty registry."""
        config = {
            "policy_mappings": {
                "file_write": ["imaginary_policy"],
            },
        }
        registry = create_policy_registry(config)
        assert registry.policy_count() == 0


class TestPolicyConfig:
    """Test that policy_config is passed to policy constructors."""

    def test_policy_config_applied(self):
        """Config from policy_config section is passed to constructor."""
        config = {
            "policy_mappings": {
                "file_write": ["blast_radius_policy"],
            },
            "policy_config": {
                "blast_radius_policy": {
                    "max_files_per_commit": 50,
                },
            },
        }
        registry = create_policy_registry(config)
        policy = registry.get_policy("blast_radius")
        assert policy is not None

    def test_nested_dict_config_filtered(self):
        """Nested dicts in policy_config are filtered out for BaseSafetyPolicy."""
        config = {
            "policy_mappings": {
                "file_write": ["rate_limit_policy"],
            },
            "policy_config": {
                "rate_limit_policy": {
                    "limits": {"file_write": "100/min"},  # Nested dict — filtered
                    "per_agent": True,  # Flat value — passed through
                },
            },
        }
        # Should not raise even though config has nested dict
        registry = create_policy_registry(config)
        assert registry.policy_count() == 1
        assert registry.is_registered("rate_limit")


class TestBuiltinPoliciesMapping:
    """Test the BUILTIN_POLICIES mapping."""

    def test_all_builtin_policies_instantiable(self):
        """Every entry in BUILTIN_POLICIES can be instantiated."""
        for name, cls in BUILTIN_POLICIES.items():
            instance = cls(config={})
            assert instance.name, f"Policy {name} has no name"

    def test_expected_policies_present(self):
        """Expected core policies are in the mapping."""
        expected = {
            "secret_detection_policy",
            "file_access_policy",
            "forbidden_ops_policy",
            "blast_radius_policy",
            "rate_limit_policy",
            "resource_limit_policy",
        }
        assert expected.issubset(set(BUILTIN_POLICIES.keys()))


class TestRealYAMLConfig:
    """Test with the actual action_policies.yaml config file."""

    def test_real_config_loads_policies(self):
        """Loading the real YAML config registers multiple policies."""
        from temper_ai.safety.factory import load_safety_config

        config = load_safety_config()
        registry = create_policy_registry(config)
        # Should register at least 4 policies (P0 critical ones)
        assert registry.policy_count() >= 4
        # Core security policies must be present
        assert registry.is_registered("secret_detection")
        assert registry.is_registered("file_access")
        assert registry.is_registered("forbidden_operations")
        assert registry.is_registered("blast_radius")

    def test_real_config_covers_file_write_actions(self):
        """Real config has policies for file_write action type."""
        from temper_ai.safety.factory import load_safety_config

        config = load_safety_config()
        registry = create_policy_registry(config)
        policies = registry.get_policies_for_action("file_write")
        assert (
            len(policies) >= 3
        )  # At least file_access, forbidden_ops, secret_detection


class TestApproverSelection:
    """Test that create_safety_stack selects the correct approver by environment."""

    @pytest.fixture
    def mock_tool_registry(self):
        return MagicMock(spec=ToolRegistry)

    def test_development_uses_noop_approver(self, mock_tool_registry):
        """Development environment uses NoOpApprover."""
        executor = create_safety_stack(mock_tool_registry, environment="development")
        assert isinstance(executor.approval_workflow, NoOpApprover)

    def test_staging_uses_real_approver(self, mock_tool_registry):
        """Staging environment uses real ApprovalWorkflow."""
        executor = create_safety_stack(mock_tool_registry, environment="staging")
        assert isinstance(executor.approval_workflow, ApprovalWorkflow)
        assert not isinstance(executor.approval_workflow, NoOpApprover)

    def test_production_uses_real_approver(self, mock_tool_registry):
        """Production environment uses real ApprovalWorkflow."""
        executor = create_safety_stack(mock_tool_registry, environment="production")
        assert isinstance(executor.approval_workflow, ApprovalWorkflow)
        assert not isinstance(executor.approval_workflow, NoOpApprover)

    def test_explicit_noop_opt_in_for_nondev(self, mock_tool_registry):
        """Explicit approval_mode=noop allows NoOpApprover in any environment."""
        with patch("temper_ai.safety.factory.load_safety_config") as mock_load:
            mock_load.return_value = {
                **_get_default_config(),
                "approval_mode": "noop",
            }
            executor = create_safety_stack(mock_tool_registry, environment="production")
        assert isinstance(executor.approval_workflow, NoOpApprover)

    def test_unknown_environment_uses_real_approver(self, mock_tool_registry):
        """Unknown environment defaults to real ApprovalWorkflow."""
        executor = create_safety_stack(mock_tool_registry, environment="custom_env")
        assert isinstance(executor.approval_workflow, ApprovalWorkflow)
        assert not isinstance(executor.approval_workflow, NoOpApprover)
