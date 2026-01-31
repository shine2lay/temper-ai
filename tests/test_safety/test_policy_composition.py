"""Tests for safety policy composition layer."""
import pytest
from unittest.mock import Mock

from src.safety.composition import PolicyComposer, CompositeValidationResult
from src.safety.interfaces import (
    SafetyPolicy,
    ValidationResult,
    SafetyViolation,
    ViolationSeverity
)


class MockPolicy(SafetyPolicy):
    """Mock policy for testing."""

    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        priority: int = 100,
        valid: bool = True,
        violations: list = None
    ):
        self._name = name
        self._version = version
        self._priority = priority
        self._valid = valid
        self._violations = violations or []
        self.validate_called = False
        self.validate_async_called = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    @property
    def priority(self) -> int:
        return self._priority

    def validate(self, action, context) -> ValidationResult:
        self.validate_called = True
        return ValidationResult(
            valid=self._valid,
            violations=self._violations,
            policy_name=self._name
        )

    async def validate_async(self, action, context) -> ValidationResult:
        self.validate_async_called = True
        return self.validate(action, context)


class TestPolicyComposerInitialization:
    """Test PolicyComposer initialization."""

    def test_init_empty(self):
        """Test initialization with no policies."""
        composer = PolicyComposer()

        assert composer.policy_count() == 0
        assert composer.fail_fast is False
        assert composer.enable_reporting is True

    def test_init_with_policies(self):
        """Test initialization with policies list."""
        policy1 = MockPolicy("policy1")
        policy2 = MockPolicy("policy2")

        composer = PolicyComposer(policies=[policy1, policy2])

        assert composer.policy_count() == 2
        assert "policy1" in composer.list_policies()
        assert "policy2" in composer.list_policies()

    def test_init_with_fail_fast(self):
        """Test initialization with fail_fast mode."""
        composer = PolicyComposer(fail_fast=True)

        assert composer.fail_fast is True

    def test_init_with_reporting_disabled(self):
        """Test initialization with reporting disabled."""
        composer = PolicyComposer(enable_reporting=False)

        assert composer.enable_reporting is False


class TestPolicyManagement:
    """Test adding, removing, and retrieving policies."""

    def test_add_policy(self):
        """Test adding a policy."""
        composer = PolicyComposer()
        policy = MockPolicy("test_policy")

        composer.add_policy(policy)

        assert composer.policy_count() == 1
        assert "test_policy" in composer.list_policies()

    def test_add_duplicate_policy_raises_error(self):
        """Test that adding duplicate policy name raises error."""
        composer = PolicyComposer()
        policy1 = MockPolicy("same_name")
        policy2 = MockPolicy("same_name")

        composer.add_policy(policy1)

        with pytest.raises(ValueError, match="already exists"):
            composer.add_policy(policy2)

    def test_remove_policy(self):
        """Test removing a policy."""
        composer = PolicyComposer()
        policy = MockPolicy("test_policy")
        composer.add_policy(policy)

        removed = composer.remove_policy("test_policy")

        assert removed is True
        assert composer.policy_count() == 0
        assert "test_policy" not in composer.list_policies()

    def test_remove_nonexistent_policy(self):
        """Test removing policy that doesn't exist."""
        composer = PolicyComposer()

        removed = composer.remove_policy("nonexistent")

        assert removed is False

    def test_get_policy(self):
        """Test retrieving a policy by name."""
        composer = PolicyComposer()
        policy = MockPolicy("test_policy")
        composer.add_policy(policy)

        retrieved = composer.get_policy("test_policy")

        assert retrieved is policy

    def test_get_nonexistent_policy(self):
        """Test retrieving policy that doesn't exist."""
        composer = PolicyComposer()

        retrieved = composer.get_policy("nonexistent")

        assert retrieved is None

    def test_list_policies(self):
        """Test listing all policies."""
        composer = PolicyComposer()
        composer.add_policy(MockPolicy("policy1"))
        composer.add_policy(MockPolicy("policy2"))
        composer.add_policy(MockPolicy("policy3"))

        policies = composer.list_policies()

        assert len(policies) == 3
        assert "policy1" in policies
        assert "policy2" in policies
        assert "policy3" in policies

    def test_clear_policies(self):
        """Test clearing all policies."""
        composer = PolicyComposer()
        composer.add_policy(MockPolicy("policy1"))
        composer.add_policy(MockPolicy("policy2"))

        composer.clear_policies()

        assert composer.policy_count() == 0
        assert composer.list_policies() == []


class TestPolicyPrioritization:
    """Test policy execution order based on priority."""

    def test_policies_sorted_by_priority(self):
        """Test that policies execute in priority order."""
        composer = PolicyComposer()

        # Add policies in random order with different priorities
        composer.add_policy(MockPolicy("low_priority", priority=10))
        composer.add_policy(MockPolicy("high_priority", priority=1000))
        composer.add_policy(MockPolicy("medium_priority", priority=500))

        policies = composer.list_policies()

        # Should be sorted highest priority first
        assert policies[0] == "high_priority"
        assert policies[1] == "medium_priority"
        assert policies[2] == "low_priority"

    def test_execution_order_matches_priority(self):
        """Test that validation executes in priority order."""
        composer = PolicyComposer()
        composer.add_policy(MockPolicy("priority_100", priority=100))
        composer.add_policy(MockPolicy("priority_200", priority=200))
        composer.add_policy(MockPolicy("priority_50", priority=50))

        result = composer.validate({}, {})

        # Execution order should match priority
        assert result.execution_order == ["priority_200", "priority_100", "priority_50"]


class TestValidation:
    """Test validation functionality."""

    def test_validate_all_policies_pass(self):
        """Test validation when all policies pass."""
        composer = PolicyComposer()
        composer.add_policy(MockPolicy("policy1", valid=True))
        composer.add_policy(MockPolicy("policy2", valid=True))

        result = composer.validate(
            action={"tool": "test"},
            context={"agent": "test"}
        )

        assert result.valid is True
        assert len(result.violations) == 0
        assert result.policies_evaluated == 2
        assert result.policies_skipped == 0

    def test_validate_one_policy_fails(self):
        """Test validation when one policy fails."""
        violation = SafetyViolation(
            policy_name="policy2",
            severity=ViolationSeverity.HIGH,
            message="Test violation",
            action="test",
            context={}
        )

        composer = PolicyComposer()
        composer.add_policy(MockPolicy("policy1", valid=True))
        composer.add_policy(MockPolicy("policy2", valid=False, violations=[violation]))

        result = composer.validate({}, {})

        assert result.valid is False
        assert len(result.violations) == 1
        assert result.violations[0].policy_name == "policy2"
        assert result.policies_evaluated == 2

    def test_validate_multiple_violations(self):
        """Test validation with multiple violations from different policies."""
        violation1 = SafetyViolation(
            policy_name="policy1",
            severity=ViolationSeverity.HIGH,
            message="Violation 1",
            action="test",
            context={}
        )
        violation2 = SafetyViolation(
            policy_name="policy2",
            severity=ViolationSeverity.CRITICAL,
            message="Violation 2",
            action="test",
            context={}
        )

        composer = PolicyComposer()
        composer.add_policy(MockPolicy("policy1", valid=False, violations=[violation1]))
        composer.add_policy(MockPolicy("policy2", valid=False, violations=[violation2]))

        result = composer.validate({}, {})

        assert result.valid is False
        assert len(result.violations) == 2
        assert result.has_critical_violations() is True
        assert result.has_blocking_violations() is True

    def test_validate_fail_fast_mode(self):
        """Test that fail-fast mode stops on first violation."""
        violation = SafetyViolation(
            policy_name="high_priority",
            severity=ViolationSeverity.HIGH,
            message="First violation",
            action="test",
            context={}
        )

        composer = PolicyComposer(fail_fast=True)
        composer.add_policy(MockPolicy("high_priority", priority=200, valid=False, violations=[violation]))
        composer.add_policy(MockPolicy("low_priority", priority=100, valid=True))

        result = composer.validate({}, {})

        assert result.valid is False
        assert len(result.violations) == 1
        assert result.policies_evaluated == 1  # Only evaluated first policy
        assert result.policies_skipped == 1    # Skipped second policy

    def test_validate_no_policies(self):
        """Test validation with no policies (should pass)."""
        composer = PolicyComposer()

        result = composer.validate({}, {})

        assert result.valid is True
        assert len(result.violations) == 0
        assert result.policies_evaluated == 0

    def test_policies_called_with_correct_arguments(self):
        """Test that policies receive correct action and context."""
        policy = MockPolicy("test_policy")
        composer = PolicyComposer()
        composer.add_policy(policy)

        action = {"tool": "test_tool", "args": {"param": "value"}}
        context = {"agent": "test_agent", "stage": "test_stage"}

        composer.validate(action, context)

        assert policy.validate_called is True

    def test_policy_exception_creates_critical_violation(self):
        """Test that policy exceptions are caught and converted to violations."""
        class FailingPolicy(MockPolicy):
            def validate(self, action, context):
                raise RuntimeError("Policy failed")

        composer = PolicyComposer()
        composer.add_policy(FailingPolicy("failing_policy"))

        result = composer.validate({}, {})

        assert result.valid is False
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.CRITICAL
        assert "Policy evaluation failed" in result.violations[0].message


class TestAsyncValidation:
    """Test asynchronous validation."""

    @pytest.mark.asyncio
    async def test_validate_async_all_pass(self):
        """Test async validation when all policies pass."""
        composer = PolicyComposer()
        composer.add_policy(MockPolicy("policy1", valid=True))
        composer.add_policy(MockPolicy("policy2", valid=True))

        result = await composer.validate_async({}, {})

        assert result.valid is True
        assert len(result.violations) == 0
        assert result.policies_evaluated == 2

    @pytest.mark.asyncio
    async def test_validate_async_with_violations(self):
        """Test async validation with violations."""
        violation = SafetyViolation(
            policy_name="policy1",
            severity=ViolationSeverity.HIGH,
            message="Async violation",
            action="test",
            context={}
        )

        composer = PolicyComposer()
        composer.add_policy(MockPolicy("policy1", valid=False, violations=[violation]))

        result = await composer.validate_async({}, {})

        assert result.valid is False
        assert len(result.violations) == 1

    @pytest.mark.asyncio
    async def test_validate_async_fail_fast(self):
        """Test async fail-fast mode."""
        violation = SafetyViolation(
            policy_name="policy1",
            severity=ViolationSeverity.HIGH,
            message="Stop here",
            action="test",
            context={}
        )

        composer = PolicyComposer(fail_fast=True)
        composer.add_policy(MockPolicy("policy1", priority=200, valid=False, violations=[violation]))
        composer.add_policy(MockPolicy("policy2", priority=100, valid=True))

        result = await composer.validate_async({}, {})

        assert result.policies_evaluated == 1
        assert result.policies_skipped == 1


class TestCompositeValidationResult:
    """Test CompositeValidationResult helper methods."""

    def test_has_critical_violations(self):
        """Test checking for critical violations."""
        result = CompositeValidationResult(
            valid=False,
            violations=[
                SafetyViolation(
                    policy_name="test",
                    severity=ViolationSeverity.CRITICAL,
                    message="Critical",
                    action="test",
                    context={}
                )
            ]
        )

        assert result.has_critical_violations() is True

    def test_has_blocking_violations(self):
        """Test checking for blocking violations (HIGH or CRITICAL)."""
        result = CompositeValidationResult(
            valid=False,
            violations=[
                SafetyViolation(
                    policy_name="test",
                    severity=ViolationSeverity.HIGH,
                    message="High",
                    action="test",
                    context={}
                )
            ]
        )

        assert result.has_blocking_violations() is True

    def test_get_violations_by_severity(self):
        """Test filtering violations by severity."""
        violations = [
            SafetyViolation(
                policy_name="test",
                severity=ViolationSeverity.CRITICAL,
                message="Critical",
                action="test",
                context={}
            ),
            SafetyViolation(
                policy_name="test",
                severity=ViolationSeverity.MEDIUM,
                message="Medium",
                action="test",
                context={}
            )
        ]

        result = CompositeValidationResult(valid=False, violations=violations)

        critical = result.get_violations_by_severity(ViolationSeverity.CRITICAL)
        assert len(critical) == 1
        assert critical[0].severity == ViolationSeverity.CRITICAL

    def test_get_violations_by_policy(self):
        """Test filtering violations by policy name."""
        violations = [
            SafetyViolation(
                policy_name="policy1",
                severity=ViolationSeverity.HIGH,
                message="From policy1",
                action="test",
                context={}
            ),
            SafetyViolation(
                policy_name="policy2",
                severity=ViolationSeverity.HIGH,
                message="From policy2",
                action="test",
                context={}
            )
        ]

        result = CompositeValidationResult(valid=False, violations=violations)

        policy1_violations = result.get_violations_by_policy("policy1")
        assert len(policy1_violations) == 1
        assert policy1_violations[0].policy_name == "policy1"

    def test_to_dict(self):
        """Test serialization to dictionary."""
        result = CompositeValidationResult(
            valid=True,
            violations=[],
            policies_evaluated=3,
            policies_skipped=0,
            execution_order=["policy1", "policy2", "policy3"]
        )

        result_dict = result.to_dict()

        assert result_dict["valid"] is True
        assert result_dict["policies_evaluated"] == 3
        assert result_dict["policies_skipped"] == 0
        assert result_dict["execution_order"] == ["policy1", "policy2", "policy3"]
        assert result_dict["has_critical_violations"] is False
        assert result_dict["has_blocking_violations"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
