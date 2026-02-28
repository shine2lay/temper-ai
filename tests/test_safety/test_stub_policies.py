"""Tests for temper_ai/safety/stub_policies.py."""

from temper_ai.safety.stub_policies import ApprovalWorkflowPolicy, CircuitBreakerPolicy


class TestApprovalWorkflowPolicy:
    def setup_method(self):
        self.policy = ApprovalWorkflowPolicy(config={})

    def test_name(self):
        assert self.policy.name == "approval_workflow_policy"

    def test_version(self):
        assert self.policy.version == "0.1.0"

    def test_validate_always_allows(self):
        result = self.policy._validate_impl(action={}, context={})
        assert result.valid is True
        assert result.violations == []

    def test_validate_with_any_action(self):
        action = {"tool": "bash", "command": "ls /", "risk": "high"}
        context = {"agent": "researcher", "session": "abc123"}
        result = self.policy._validate_impl(action=action, context=context)
        assert result.valid is True
        assert result.violations == []


class TestCircuitBreakerPolicy:
    def setup_method(self):
        self.policy = CircuitBreakerPolicy(config={})

    def test_name(self):
        assert self.policy.name == "circuit_breaker_policy"

    def test_version(self):
        assert self.policy.version == "0.1.0"

    def test_validate_always_allows(self):
        result = self.policy._validate_impl(action={}, context={})
        assert result.valid is True
        assert result.violations == []

    def test_validate_with_any_action(self):
        action = {"provider": "anthropic", "model": "claude-opus-4-6", "tokens": 1000}
        context = {"request_id": "req-xyz", "retries": 3}
        result = self.policy._validate_impl(action=action, context=context)
        assert result.valid is True
        assert result.violations == []
