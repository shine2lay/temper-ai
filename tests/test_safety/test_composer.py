"""Tests for PolicyComposer and policy composition layer.

Tests cover:
- Policy addition, removal, and ordering
- Sequential execution (fail-safe mode)
- Fail-fast mode with short-circuit
- Violation aggregation
- Async validation
- Exception handling
- CompositeValidationResult helper methods
"""
from typing import Any, Dict

import pytest

from temper_ai.safety.composition import CompositeValidationResult, PolicyComposer
from temper_ai.safety.interfaces import SafetyPolicy, SafetyViolation, ValidationResult, ViolationSeverity

# ============================================================================
# Mock Policies for Testing
# ============================================================================

class MockPolicy(SafetyPolicy):
    """Mock policy for testing with configurable behavior."""

    def __init__(
        self,
        name: str,
        priority: int = 100,
        violations: list = None,
        raise_exception: bool = False
    ):
        self._name = name
        self._priority = priority
        self._violations = violations or []
        self._raise_exception = raise_exception
        self.validate_called = False
        self.validate_async_called = False
        self.reported_violations = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def priority(self) -> int:
        return self._priority

    def validate(self, action: Dict[str, Any], context: Dict[str, Any]) -> ValidationResult:
        """Mock validation - returns configured violations."""
        self.validate_called = True

        if self._raise_exception:
            raise ValueError(f"Simulated error in {self.name}")

        violations = [
            SafetyViolation(
                policy_name=self.name,
                severity=v["severity"],
                message=v["message"],
                action=str(action),
                context=context
            )
            for v in self._violations
        ]

        return ValidationResult(
            valid=len(violations) == 0,
            violations=violations,
            policy_name=self.name
        )

    async def validate_async(self, action: Dict[str, Any], context: Dict[str, Any]) -> ValidationResult:
        """Async validation."""
        self.validate_async_called = True
        return self.validate(action, context)

    def report_violation(self, violation: SafetyViolation) -> None:
        """Track reported violations."""
        self.reported_violations.append(violation)


# ============================================================================
# Test PolicyComposer Initialization
# ============================================================================

class TestPolicyComposerInitialization:
    """Test PolicyComposer initialization."""

    def test_init_empty(self):
        """Test initialization with no policies."""
        composer = PolicyComposer()

        assert composer.policy_count() == 0
        assert composer.fail_fast is False
        assert composer.enable_reporting is True

    def test_init_with_policies(self):
        """Test initialization with initial policies."""
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


# ============================================================================
# Test Policy Management
# ============================================================================

class TestPolicyManagement:
    """Test adding, removing, and managing policies."""

    def test_add_policy(self):
        """Test adding a single policy."""
        composer = PolicyComposer()
        policy = MockPolicy("test_policy")

        composer.add_policy(policy)

        assert composer.policy_count() == 1
        assert composer.list_policies() == ["test_policy"]

    def test_add_duplicate_policy_raises_error(self):
        """Test that adding duplicate policy name raises error."""
        composer = PolicyComposer()
        policy1 = MockPolicy("same_name")
        policy2 = MockPolicy("same_name")

        composer.add_policy(policy1)

        with pytest.raises(ValueError, match="already exists"):
            composer.add_policy(policy2)

    def test_remove_policy(self):
        """Test removing a policy by name."""
        composer = PolicyComposer()
        policy = MockPolicy("test_policy")
        composer.add_policy(policy)

        result = composer.remove_policy("test_policy")

        assert result is True
        assert composer.policy_count() == 0

    def test_remove_nonexistent_policy(self):
        """Test removing nonexistent policy returns False."""
        composer = PolicyComposer()

        result = composer.remove_policy("nonexistent")

        assert result is False

    def test_get_policy(self):
        """Test retrieving a policy by name."""
        composer = PolicyComposer()
        policy = MockPolicy("test_policy")
        composer.add_policy(policy)

        retrieved = composer.get_policy("test_policy")

        assert retrieved is policy

    def test_get_nonexistent_policy(self):
        """Test retrieving nonexistent policy returns None."""
        composer = PolicyComposer()

        retrieved = composer.get_policy("nonexistent")

        assert retrieved is None

    def test_clear_policies(self):
        """Test clearing all policies."""
        composer = PolicyComposer()
        composer.add_policy(MockPolicy("policy1"))
        composer.add_policy(MockPolicy("policy2"))

        composer.clear_policies()

        assert composer.policy_count() == 0


# ============================================================================
# Test Policy Priority Ordering
# ============================================================================

class TestPolicyOrdering:
    """Test policies execute in priority order."""

    def test_policies_sorted_by_priority(self):
        """Test policies are automatically sorted by priority (highest first)."""
        composer = PolicyComposer()

        # Add policies in random priority order
        composer.add_policy(MockPolicy("low", priority=50))
        composer.add_policy(MockPolicy("high", priority=200))
        composer.add_policy(MockPolicy("medium", priority=100))

        # Should be sorted: high, medium, low
        policies = composer.list_policies()
        assert policies == ["high", "medium", "low"]

    def test_execution_order_matches_priority(self):
        """Test policies execute in priority order."""
        composer = PolicyComposer()

        policy_high = MockPolicy("high", priority=200)
        policy_low = MockPolicy("low", priority=50)

        composer.add_policy(policy_low)
        composer.add_policy(policy_high)

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        # Verify execution order
        assert result.execution_order == ["high", "low"]


# ============================================================================
# Test Sequential Validation (Fail-Safe Mode)
# ============================================================================

class TestSequentialValidation:
    """Test sequential execution of all policies (fail-safe mode)."""

    def test_all_policies_evaluated(self):
        """Test all policies are evaluated in fail-safe mode."""
        composer = PolicyComposer(fail_fast=False)

        policy1 = MockPolicy("policy1")
        policy2 = MockPolicy("policy2")
        policy3 = MockPolicy("policy3")

        composer.add_policy(policy1)
        composer.add_policy(policy2)
        composer.add_policy(policy3)

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        assert result.policies_evaluated == 3
        assert result.policies_skipped == 0
        assert policy1.validate_called
        assert policy2.validate_called
        assert policy3.validate_called

    def test_violations_aggregated(self):
        """Test violations from multiple policies are aggregated."""
        composer = PolicyComposer(fail_fast=False)

        # Policy 1: HIGH violation
        policy1 = MockPolicy("policy1", violations=[
            {"severity": ViolationSeverity.HIGH, "message": "High violation"}
        ])

        # Policy 2: MEDIUM violation
        policy2 = MockPolicy("policy2", violations=[
            {"severity": ViolationSeverity.MEDIUM, "message": "Medium violation"}
        ])

        composer.add_policy(policy1)
        composer.add_policy(policy2)

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) == 2
        assert result.violations[0].severity == ViolationSeverity.HIGH
        assert result.violations[1].severity == ViolationSeverity.MEDIUM

    def test_valid_when_no_violations(self):
        """Test result is valid when no policies report violations."""
        composer = PolicyComposer()

        # No violations configured
        composer.add_policy(MockPolicy("policy1"))
        composer.add_policy(MockPolicy("policy2"))

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        assert result.valid is True
        assert len(result.violations) == 0


# ============================================================================
# Test Fail-Fast Mode
# ============================================================================

class TestFailFastMode:
    """Test fail-fast mode with short-circuit evaluation."""

    def test_stops_on_first_violation(self):
        """Test fail-fast stops after first violation."""
        composer = PolicyComposer(fail_fast=True)

        # First policy has violation
        policy1 = MockPolicy("policy1", violations=[
            {"severity": ViolationSeverity.HIGH, "message": "First violation"}
        ])
        policy2 = MockPolicy("policy2")
        policy3 = MockPolicy("policy3")

        composer.add_policy(policy1)
        composer.add_policy(policy2)
        composer.add_policy(policy3)

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        # Only first policy should execute
        assert policy1.validate_called is True
        assert policy2.validate_called is False
        assert policy3.validate_called is False

        assert result.policies_evaluated == 1
        assert result.policies_skipped == 2

    def test_evaluates_all_when_no_violations(self):
        """Test fail-fast still evaluates all when no violations."""
        composer = PolicyComposer(fail_fast=True)

        policy1 = MockPolicy("policy1")  # No violations
        policy2 = MockPolicy("policy2")  # No violations

        composer.add_policy(policy1)
        composer.add_policy(policy2)

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        # All policies should execute when no violations
        assert result.policies_evaluated == 2
        assert result.policies_skipped == 0
        assert result.valid is True


# ============================================================================
# Test Violation Reporting
# ============================================================================

class TestViolationReporting:
    """Test violation reporting to policies."""

    def test_violations_reported_when_enabled(self):
        """Test violations are reported to policy when reporting enabled."""
        composer = PolicyComposer(enable_reporting=True)

        policy = MockPolicy("test_policy", violations=[
            {"severity": ViolationSeverity.HIGH, "message": "Test violation"}
        ])

        composer.add_policy(policy)

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        # Violation should be reported to policy
        assert len(policy.reported_violations) == 1
        assert policy.reported_violations[0].message == "Test violation"

    def test_violations_not_reported_when_disabled(self):
        """Test violations not reported when reporting disabled."""
        composer = PolicyComposer(enable_reporting=False)

        policy = MockPolicy("test_policy", violations=[
            {"severity": ViolationSeverity.HIGH, "message": "Test violation"}
        ])

        composer.add_policy(policy)

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        # No violations should be reported
        assert len(policy.reported_violations) == 0


# ============================================================================
# Test Exception Handling
# ============================================================================

class TestExceptionHandling:
    """Test handling of exceptions during policy evaluation."""

    def test_exception_converted_to_critical_violation(self):
        """Test exceptions during validation become CRITICAL violations."""
        composer = PolicyComposer()

        policy = MockPolicy("failing_policy", raise_exception=True)
        composer.add_policy(policy)

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.CRITICAL
        assert "Policy evaluation failed" in result.violations[0].message
        assert "failing_policy" in result.violations[0].policy_name

    def test_exception_includes_metadata(self):
        """Test exception violation includes metadata about error."""
        composer = PolicyComposer()

        policy = MockPolicy("failing_policy", raise_exception=True)
        composer.add_policy(policy)

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        violation = result.violations[0]
        assert "exception" in violation.metadata
        assert "exception_type" in violation.metadata
        assert violation.metadata["exception_type"] == "ValueError"

    def test_exception_reported_when_reporting_enabled(self):
        """Test exception violations are reported."""
        composer = PolicyComposer(enable_reporting=True)

        policy = MockPolicy("failing_policy", raise_exception=True)
        composer.add_policy(policy)

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        # Exception violation should be reported
        assert len(policy.reported_violations) == 1
        assert policy.reported_violations[0].severity == ViolationSeverity.CRITICAL

    def test_subsequent_policies_execute_after_exception(self):
        """Test other policies still execute after one throws exception."""
        composer = PolicyComposer(fail_fast=False)

        policy1 = MockPolicy("failing_policy", raise_exception=True)
        policy2 = MockPolicy("normal_policy")

        composer.add_policy(policy1)
        composer.add_policy(policy2)

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        # Both policies should execute
        assert result.policies_evaluated == 2
        assert policy2.validate_called is True


# ============================================================================
# Test Async Validation
# ============================================================================

class TestAsyncValidation:
    """Test asynchronous validation."""

    @pytest.mark.asyncio
    async def test_async_validation_basic(self):
        """Test basic async validation."""
        composer = PolicyComposer()

        policy = MockPolicy("async_policy")
        composer.add_policy(policy)

        result = await composer.validate_async(
            action={"tool": "test"},
            context={}
        )

        assert policy.validate_async_called is True
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_async_violations_aggregated(self):
        """Test async validation aggregates violations."""
        composer = PolicyComposer()

        policy1 = MockPolicy("policy1", violations=[
            {"severity": ViolationSeverity.HIGH, "message": "Violation 1"}
        ])
        policy2 = MockPolicy("policy2", violations=[
            {"severity": ViolationSeverity.MEDIUM, "message": "Violation 2"}
        ])

        composer.add_policy(policy1)
        composer.add_policy(policy2)

        result = await composer.validate_async(
            action={"tool": "test"},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) == 2

    @pytest.mark.asyncio
    async def test_async_fail_fast(self):
        """Test async validation respects fail-fast mode."""
        composer = PolicyComposer(fail_fast=True)

        policy1 = MockPolicy("policy1", violations=[
            {"severity": ViolationSeverity.HIGH, "message": "First violation"}
        ])
        policy2 = MockPolicy("policy2")

        composer.add_policy(policy1)
        composer.add_policy(policy2)

        result = await composer.validate_async(
            action={"tool": "test"},
            context={}
        )

        # Should stop after first policy
        assert result.policies_evaluated == 1
        assert result.policies_skipped == 1


# ============================================================================
# Test CompositeValidationResult
# ============================================================================

class TestCompositeValidationResult:
    """Test CompositeValidationResult helper methods."""

    def test_has_critical_violations(self):
        """Test has_critical_violations() detects CRITICAL severity."""
        violations = [
            SafetyViolation(
                policy_name="test",
                severity=ViolationSeverity.CRITICAL,
                message="Critical",
                action="test",
                context={}
            )
        ]

        result = CompositeValidationResult(valid=False, violations=violations)

        assert result.has_critical_violations() is True

    def test_has_blocking_violations(self):
        """Test has_blocking_violations() detects HIGH+ severity."""
        violations = [
            SafetyViolation(
                policy_name="test",
                severity=ViolationSeverity.HIGH,
                message="High",
                action="test",
                context={}
            )
        ]

        result = CompositeValidationResult(valid=False, violations=violations)

        assert result.has_blocking_violations() is True

    def test_has_blocking_violations_includes_critical(self):
        """Test has_blocking_violations() includes CRITICAL."""
        violations = [
            SafetyViolation(
                policy_name="test",
                severity=ViolationSeverity.CRITICAL,
                message="Critical",
                action="test",
                context={}
            )
        ]

        result = CompositeValidationResult(valid=False, violations=violations)

        assert result.has_blocking_violations() is True

    def test_get_violations_by_severity(self):
        """Test getting violations filtered by severity."""
        violations = [
            SafetyViolation(
                policy_name="p1",
                severity=ViolationSeverity.CRITICAL,
                message="Critical",
                action="test",
                context={}
            ),
            SafetyViolation(
                policy_name="p2",
                severity=ViolationSeverity.MEDIUM,
                message="Medium",
                action="test",
                context={}
            ),
            SafetyViolation(
                policy_name="p3",
                severity=ViolationSeverity.CRITICAL,
                message="Critical 2",
                action="test",
                context={}
            ),
        ]

        result = CompositeValidationResult(valid=False, violations=violations)

        critical = result.get_violations_by_severity(ViolationSeverity.CRITICAL)
        assert len(critical) == 2

        medium = result.get_violations_by_severity(ViolationSeverity.MEDIUM)
        assert len(medium) == 1

    def test_get_violations_by_policy(self):
        """Test getting violations filtered by policy name."""
        violations = [
            SafetyViolation(
                policy_name="policy1",
                severity=ViolationSeverity.HIGH,
                message="V1",
                action="test",
                context={}
            ),
            SafetyViolation(
                policy_name="policy2",
                severity=ViolationSeverity.MEDIUM,
                message="V2",
                action="test",
                context={}
            ),
            SafetyViolation(
                policy_name="policy1",
                severity=ViolationSeverity.LOW,
                message="V3",
                action="test",
                context={}
            ),
        ]

        result = CompositeValidationResult(valid=False, violations=violations)

        policy1_violations = result.get_violations_by_policy("policy1")
        assert len(policy1_violations) == 2

        policy2_violations = result.get_violations_by_policy("policy2")
        assert len(policy2_violations) == 1

    def test_to_dict(self):
        """Test to_dict() serialization."""
        violations = [
            SafetyViolation(
                policy_name="test",
                severity=ViolationSeverity.HIGH,
                message="Test violation",
                action="test_action",
                context={}
            )
        ]

        result = CompositeValidationResult(
            valid=False,
            violations=violations,
            policies_evaluated=2,
            policies_skipped=1,
            execution_order=["policy1", "policy2"],
            metadata={"test": "value"}
        )

        result_dict = result.to_dict()

        assert result_dict["valid"] is False
        assert len(result_dict["violations"]) == 1
        assert result_dict["policies_evaluated"] == 2
        assert result_dict["policies_skipped"] == 1
        assert result_dict["execution_order"] == ["policy1", "policy2"]
        assert result_dict["metadata"] == {"test": "value"}
        assert "has_critical_violations" in result_dict
        assert "has_blocking_violations" in result_dict


# ============================================================================
# Test Integration Scenarios
# ============================================================================

class TestIntegration:
    """Test realistic composition scenarios."""

    def test_p0_p1_p2_priority_cascade(self):
        """Test P0 (critical) policies execute before P1/P2."""
        composer = PolicyComposer(fail_fast=False)

        p2_policy = MockPolicy("optimization", priority=50)  # P2
        p1_policy = MockPolicy("validation", priority=100)  # P1
        p0_policy = MockPolicy("security", priority=200)    # P0

        # Add in random order
        composer.add_policy(p1_policy)
        composer.add_policy(p2_policy)
        composer.add_policy(p0_policy)

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        # Should execute in priority order: P0, P1, P2
        assert result.execution_order == ["security", "validation", "optimization"]

    def test_critical_violation_detection_pipeline(self):
        """Test pipeline detects and reports critical violations."""
        composer = PolicyComposer(fail_fast=True, enable_reporting=True)

        # Security policy detects CRITICAL violation
        security_policy = MockPolicy("security", priority=200, violations=[
            {"severity": ViolationSeverity.CRITICAL, "message": "Security breach detected"}
        ])

        # Other policies won't run (fail-fast)
        rate_limit_policy = MockPolicy("rate_limit", priority=150)
        validation_policy = MockPolicy("validation", priority=100)

        composer.add_policy(security_policy)
        composer.add_policy(rate_limit_policy)
        composer.add_policy(validation_policy)

        result = composer.validate(
            action={"tool": "dangerous_operation"},
            context={"agent": "untrusted"}
        )

        # Should fail fast on critical violation
        assert result.valid is False
        assert result.has_critical_violations() is True
        assert result.has_blocking_violations() is True
        assert result.policies_evaluated == 1
        assert result.policies_skipped == 2

        # Violation should be reported
        assert len(security_policy.reported_violations) == 1


# ============================================================================
# Test Edge Cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_composer_validation(self):
        """Test validation with no policies succeeds."""
        composer = PolicyComposer()

        result = composer.validate(
            action={"tool": "test"},
            context={}
        )

        assert result.valid is True
        assert len(result.violations) == 0
        assert result.policies_evaluated == 0

    def test_repr(self):
        """Test string representation."""
        composer = PolicyComposer(fail_fast=True, enable_reporting=False)
        composer.add_policy(MockPolicy("test"))

        repr_str = repr(composer)

        assert "PolicyComposer" in repr_str
        assert "policies=1" in repr_str
        assert "fail_fast=True" in repr_str
        assert "reporting_enabled=False" in repr_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
