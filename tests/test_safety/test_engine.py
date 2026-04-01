"""Tests for PolicyEngine — the safety evaluation orchestrator."""

import pytest

from temper_ai.safety import ActionType, PolicyEngine, PolicyDecision, BasePolicy
from temper_ai.safety.engine import POLICY_REGISTRY, register_policy
from temper_ai.safety.exceptions import SafetyConfigError


class TestPolicyEngine:
    def test_empty_engine_allows_all(self):
        engine = PolicyEngine()
        decision = engine.evaluate(ActionType.TOOL_CALL, {}, {})
        assert decision.action == "allow"

    def test_single_allow_policy(self):
        class AlwaysAllow(BasePolicy):
            action_types = [ActionType.TOOL_CALL]
            @classmethod
            def validate_config(cls, config):
                return []
            def evaluate(self, action_type, action_data, context):
                return PolicyDecision(action="allow", reason="ok", policy_name="test")

        engine = PolicyEngine([AlwaysAllow({"type": "test"})])
        decision = engine.evaluate(ActionType.TOOL_CALL, {}, {})
        assert decision.action == "allow"

    def test_first_deny_wins(self):
        class DenyPolicy(BasePolicy):
            action_types = [ActionType.TOOL_CALL]
            @classmethod
            def validate_config(cls, config):
                return []
            def evaluate(self, action_type, action_data, context):
                return PolicyDecision(action="deny", reason="nope", policy_name="denier")

        class AllowPolicy(BasePolicy):
            action_types = [ActionType.TOOL_CALL]
            @classmethod
            def validate_config(cls, config):
                return []
            def evaluate(self, action_type, action_data, context):
                return PolicyDecision(action="allow", reason="ok", policy_name="allower")

        engine = PolicyEngine([
            AllowPolicy({"type": "test"}),
            DenyPolicy({"type": "test"}),
        ])
        decision = engine.evaluate(ActionType.TOOL_CALL, {}, {})
        assert decision.action == "deny"
        assert decision.policy_name == "denier"

    def test_skips_disabled_policies(self):
        class DenyPolicy(BasePolicy):
            action_types = [ActionType.TOOL_CALL]
            @classmethod
            def validate_config(cls, config):
                return []
            def evaluate(self, action_type, action_data, context):
                return PolicyDecision(action="deny", reason="nope", policy_name="test")

        policy = DenyPolicy({"type": "test", "enabled": False})
        engine = PolicyEngine([policy])
        decision = engine.evaluate(ActionType.TOOL_CALL, {}, {})
        assert decision.action == "allow"  # skipped because disabled

    def test_skips_wrong_action_type(self):
        class WorkflowOnly(BasePolicy):
            action_types = [ActionType.WORKFLOW_START]
            @classmethod
            def validate_config(cls, config):
                return []
            def evaluate(self, action_type, action_data, context):
                return PolicyDecision(action="deny", reason="no workflows", policy_name="test")

        engine = PolicyEngine([WorkflowOnly({"type": "test"})])
        # Should skip because action_type is TOOL_CALL, not WORKFLOW_START
        decision = engine.evaluate(ActionType.TOOL_CALL, {}, {})
        assert decision.action == "allow"

    def test_add_policy(self):
        engine = PolicyEngine()
        assert len(engine.policies) == 0

        class TestPolicy(BasePolicy):
            action_types = [ActionType.TOOL_CALL]
            @classmethod
            def validate_config(cls, config):
                return []
            def evaluate(self, action_type, action_data, context):
                return PolicyDecision(action="allow", reason="ok", policy_name="test")

        engine.add_policy(TestPolicy({"type": "test"}))
        assert len(engine.policies) == 1


class TestFromConfig:
    def test_loads_registered_policies(self):
        engine = PolicyEngine.from_config({
            "policies": [
                {"type": "forbidden_ops"},
            ],
        })
        assert len(engine.policies) == 1

    def test_unknown_type_raises(self):
        with pytest.raises(SafetyConfigError, match="Unknown policy type"):
            PolicyEngine.from_config({
                "policies": [{"type": "nonexistent"}],
            })

    def test_missing_type_raises(self):
        with pytest.raises(SafetyConfigError, match="missing 'type'"):
            PolicyEngine.from_config({
                "policies": [{"denied_paths": [".env"]}],
            })

    def test_invalid_config_raises(self):
        with pytest.raises(SafetyConfigError):
            PolicyEngine.from_config({
                "policies": [{"type": "budget"}],  # missing max_cost/max_tokens
            })

    def test_multiple_policies(self):
        engine = PolicyEngine.from_config({
            "policies": [
                {"type": "file_access", "denied_paths": [".env"]},
                {"type": "forbidden_ops"},
                {"type": "budget", "max_cost_usd": 1.0},
            ],
        })
        assert len(engine.policies) == 3


class TestValidateConfig:
    def test_valid_config(self):
        errors = PolicyEngine.validate_config({
            "policies": [
                {"type": "file_access", "denied_paths": [".env"]},
                {"type": "forbidden_ops"},
                {"type": "budget", "max_cost_usd": 1.0},
            ],
        })
        assert errors == []

    def test_unknown_type(self):
        errors = PolicyEngine.validate_config({
            "policies": [{"type": "does_not_exist"}],
        })
        assert any("unknown type" in e.lower() for e in errors)

    def test_missing_type(self):
        errors = PolicyEngine.validate_config({
            "policies": [{"denied_paths": [".env"]}],
        })
        assert any("missing" in e.lower() for e in errors)

    def test_invalid_policy_config(self):
        errors = PolicyEngine.validate_config({
            "policies": [{"type": "budget"}],  # missing limits
        })
        assert len(errors) > 0


class TestActionCoverage:
    def test_warns_unused_policy(self):
        # Register a test policy that only handles AGENT_OUTPUT
        class OutputOnly(BasePolicy):
            action_types = [ActionType.AGENT_OUTPUT]
            @classmethod
            def validate_config(cls, config):
                return []
            def evaluate(self, action_type, action_data, context):
                return PolicyDecision(action="allow", reason="ok", policy_name="test")

        register_policy("output_only", OutputOnly)
        try:
            warnings = PolicyEngine.validate_action_coverage(
                {"policies": [{"type": "output_only"}]},
                wired_action_types={ActionType.TOOL_CALL},
            )
            assert len(warnings) == 1
            assert "never run" in warnings[0]
        finally:
            # Clean up
            del POLICY_REGISTRY["output_only"]

    def test_no_warning_for_matching_policy(self):
        warnings = PolicyEngine.validate_action_coverage(
            {"policies": [{"type": "file_access", "denied_paths": [".env"]}]},
            wired_action_types={ActionType.TOOL_CALL},
        )
        assert warnings == []


class TestRegisterPolicy:
    def test_register_custom_policy(self):
        class CustomPolicy(BasePolicy):
            action_types = [ActionType.TOOL_CALL]
            @classmethod
            def validate_config(cls, config):
                return []
            def evaluate(self, action_type, action_data, context):
                return PolicyDecision(action="deny", reason="custom", policy_name="custom")

        register_policy("custom_test", CustomPolicy)
        try:
            assert "custom_test" in POLICY_REGISTRY
            engine = PolicyEngine.from_config({"policies": [{"type": "custom_test"}]})
            decision = engine.evaluate(ActionType.TOOL_CALL, {}, {})
            assert decision.action == "deny"
        finally:
            del POLICY_REGISTRY["custom_test"]
