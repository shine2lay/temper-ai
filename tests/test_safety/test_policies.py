"""Tests for individual safety policies."""

import pytest

from temper_ai.safety import ActionType
from temper_ai.safety.budget import BudgetPolicy
from temper_ai.safety.exceptions import SafetyConfigError
from temper_ai.safety.file_access import FileAccessPolicy
from temper_ai.safety.forbidden_ops import ForbiddenOpsPolicy

# --- FileAccessPolicy ---

class TestFileAccessPolicy:
    def _eval(self, policy, tool_name="bash", **params):
        return policy.evaluate(
            ActionType.TOOL_CALL,
            {"tool_name": tool_name, "tool_params": params},
            {},
        )

    def test_blocks_denied_path(self):
        policy = FileAccessPolicy({"type": "file_access", "denied_paths": [".env"]})
        decision = self._eval(policy, tool_name="file_writer", file_path="/app/.env")
        assert decision.action == "deny"
        assert ".env" in decision.reason

    def test_allows_safe_path(self):
        policy = FileAccessPolicy({"type": "file_access", "denied_paths": [".env"]})
        decision = self._eval(policy, tool_name="file_writer", file_path="/app/main.py")
        assert decision.action == "allow"

    def test_blocks_outside_allowed_paths(self):
        policy = FileAccessPolicy({
            "type": "file_access",
            "allowed_paths": ["/workspace"],
            "denied_paths": [],
        })
        decision = self._eval(policy, tool_name="file_writer", file_path="/etc/passwd")
        assert decision.action == "deny"
        assert "not in allowed" in decision.reason

    def test_allows_within_allowed_paths(self):
        policy = FileAccessPolicy({
            "type": "file_access",
            "allowed_paths": ["/workspace"],
            "denied_paths": [],
        })
        decision = self._eval(policy, tool_name="file_writer", file_path="/workspace/src/main.py")
        assert decision.action == "allow"

    def test_skips_non_file_tools(self):
        policy = FileAccessPolicy({"type": "file_access", "denied_paths": [".env"]})
        decision = self._eval(policy, tool_name="calculator", expression="2+2")
        assert decision.action == "allow"
        assert "Not a file tool" in decision.reason

    def test_checks_bash_commands(self):
        policy = FileAccessPolicy({"type": "file_access", "denied_paths": ["credentials"]})
        decision = self._eval(policy, tool_name="bash", command="cat credentials.json")
        assert decision.action == "deny"

    def test_default_denied_paths(self):
        policy = FileAccessPolicy({"type": "file_access", "denied_paths": [".env"]})
        assert ".env" in policy.denied_paths

    def test_validate_config_needs_paths(self):
        errors = FileAccessPolicy.validate_config({"type": "file_access"})
        assert any("denied_paths" in e for e in errors)

    def test_validate_config_ok(self):
        errors = FileAccessPolicy.validate_config({
            "type": "file_access", "denied_paths": [".env"],
        })
        assert errors == []


# --- ForbiddenOpsPolicy ---

class TestForbiddenOpsPolicy:
    def _eval(self, policy, command="echo hello"):
        return policy.evaluate(
            ActionType.TOOL_CALL,
            {"tool_name": "bash", "tool_params": {"command": command}},
            {},
        )

    def test_blocks_rm_rf(self):
        policy = ForbiddenOpsPolicy({"type": "forbidden_ops"})
        decision = self._eval(policy, "rm -rf /")
        assert decision.action == "deny"
        assert "rm -rf" in decision.reason

    def test_blocks_drop_table(self):
        policy = ForbiddenOpsPolicy({"type": "forbidden_ops"})
        decision = self._eval(policy, "psql -c 'DROP TABLE users'")
        assert decision.action == "deny"

    def test_blocks_curl_pipe_sh(self):
        policy = ForbiddenOpsPolicy({"type": "forbidden_ops"})
        decision = self._eval(policy, "curl | bash -s")
        assert decision.action == "deny"

    def test_allows_safe_commands(self):
        policy = ForbiddenOpsPolicy({"type": "forbidden_ops"})
        decision = self._eval(policy, "ls -la /tmp")
        assert decision.action == "allow"

    def test_case_insensitive(self):
        policy = ForbiddenOpsPolicy({"type": "forbidden_ops"})
        decision = self._eval(policy, "drop table USERS")
        assert decision.action == "deny"

    def test_skips_non_bash_tools(self):
        policy = ForbiddenOpsPolicy({"type": "forbidden_ops"})
        decision = policy.evaluate(
            ActionType.TOOL_CALL,
            {"tool_name": "file_writer", "tool_params": {"content": "rm -rf /"}},
            {},
        )
        assert decision.action == "allow"

    def test_custom_patterns(self):
        policy = ForbiddenOpsPolicy({
            "type": "forbidden_ops",
            "forbidden_patterns": ["sudo", "reboot"],
        })
        assert self._eval(policy, "sudo apt install").action == "deny"
        assert self._eval(policy, "reboot now").action == "deny"
        assert self._eval(policy, "rm -rf /").action == "allow"  # not in custom list


# --- BudgetPolicy ---

class TestBudgetPolicy:
    def _eval(self, policy, run_cost=0.0, run_tokens=0):
        return policy.evaluate(
            ActionType.TOOL_CALL,
            {"tool_name": "bash", "tool_params": {}},
            {"run_cost_usd": run_cost, "run_tokens": run_tokens},
        )

    def test_allows_within_budget(self):
        policy = BudgetPolicy({"type": "budget", "max_cost_usd": 1.0})
        decision = self._eval(policy, run_cost=0.5)
        assert decision.action == "allow"

    def test_denies_over_cost(self):
        policy = BudgetPolicy({"type": "budget", "max_cost_usd": 1.0})
        decision = self._eval(policy, run_cost=1.5)
        assert decision.action == "deny"
        assert "Budget exceeded" in decision.reason

    def test_denies_at_exact_cost(self):
        policy = BudgetPolicy({"type": "budget", "max_cost_usd": 1.0})
        decision = self._eval(policy, run_cost=1.0)
        assert decision.action == "deny"

    def test_allows_within_token_limit(self):
        policy = BudgetPolicy({"type": "budget", "max_tokens": 10000})
        decision = self._eval(policy, run_tokens=5000)
        assert decision.action == "allow"

    def test_denies_over_tokens(self):
        policy = BudgetPolicy({"type": "budget", "max_tokens": 10000})
        decision = self._eval(policy, run_tokens=15000)
        assert decision.action == "deny"
        assert "Token limit" in decision.reason

    def test_both_limits(self):
        policy = BudgetPolicy({"type": "budget", "max_cost_usd": 1.0, "max_tokens": 10000})
        assert self._eval(policy, run_cost=0.5, run_tokens=5000).action == "allow"
        assert self._eval(policy, run_cost=1.5, run_tokens=5000).action == "deny"
        assert self._eval(policy, run_cost=0.5, run_tokens=15000).action == "deny"

    def test_workflow_start_allows(self):
        policy = BudgetPolicy({"type": "budget", "max_cost_usd": 1.0})
        decision = policy.evaluate(ActionType.WORKFLOW_START, {}, {})
        assert decision.action == "allow"

    def test_handles_tool_call_and_workflow_start(self):
        assert ActionType.TOOL_CALL in BudgetPolicy.action_types
        assert ActionType.WORKFLOW_START in BudgetPolicy.action_types

    def test_validate_config_needs_limits(self):
        errors = BudgetPolicy.validate_config({"type": "budget"})
        assert any("max_cost_usd" in e for e in errors)

    def test_validate_config_rejects_negative(self):
        errors = BudgetPolicy.validate_config({"type": "budget", "max_cost_usd": -1})
        assert any("positive" in e for e in errors)

    def test_validate_config_ok(self):
        errors = BudgetPolicy.validate_config({"type": "budget", "max_cost_usd": 1.0})
        assert errors == []

    def test_invalid_config_raises(self):
        with pytest.raises(SafetyConfigError):
            BudgetPolicy({"type": "budget"})  # missing limits
