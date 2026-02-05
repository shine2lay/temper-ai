"""Tests for safety policy interfaces and base classes.

Tests cover:
- ViolationSeverity comparisons
- SafetyViolation dataclass
- ValidationResult helpers
- SafetyPolicy interface compliance
- BaseSafetyPolicy composition
- SafetyServiceMixin functionality
"""
import pytest
from datetime import datetime
from src.safety import (
    SafetyPolicy,
    BaseSafetyPolicy,
    SafetyViolation,
    ValidationResult,
    ViolationSeverity,
    Validator
)
from src.core.service import Service
from src.safety.service_mixin import SafetyServiceMixin


# ============================================
# VIOLATION SEVERITY TESTS
# ============================================

class TestViolationSeverity:
    """Tests for ViolationSeverity enum."""

    def test_severity_values(self):
        """Test severity value ordering."""
        assert ViolationSeverity.CRITICAL.value == 5
        assert ViolationSeverity.HIGH.value == 4
        assert ViolationSeverity.MEDIUM.value == 3
        assert ViolationSeverity.LOW.value == 2
        assert ViolationSeverity.INFO.value == 1

    def test_severity_comparisons_less_than(self):
        """Test less than comparisons."""
        assert ViolationSeverity.INFO < ViolationSeverity.LOW
        assert ViolationSeverity.LOW < ViolationSeverity.MEDIUM
        assert ViolationSeverity.MEDIUM < ViolationSeverity.HIGH
        assert ViolationSeverity.HIGH < ViolationSeverity.CRITICAL

    def test_severity_comparisons_greater_than(self):
        """Test greater than comparisons."""
        assert ViolationSeverity.CRITICAL > ViolationSeverity.HIGH
        assert ViolationSeverity.HIGH > ViolationSeverity.MEDIUM
        assert ViolationSeverity.MEDIUM > ViolationSeverity.LOW
        assert ViolationSeverity.LOW > ViolationSeverity.INFO

    def test_severity_comparisons_equals(self):
        """Test equality comparisons."""
        assert ViolationSeverity.HIGH == ViolationSeverity.HIGH
        assert not (ViolationSeverity.HIGH == ViolationSeverity.CRITICAL)

    def test_severity_comparisons_less_equal(self):
        """Test less than or equal comparisons."""
        assert ViolationSeverity.INFO <= ViolationSeverity.LOW
        assert ViolationSeverity.HIGH <= ViolationSeverity.HIGH

    def test_severity_comparisons_greater_equal(self):
        """Test greater than or equal comparisons."""
        assert ViolationSeverity.CRITICAL >= ViolationSeverity.HIGH
        assert ViolationSeverity.HIGH >= ViolationSeverity.HIGH


# ============================================
# SAFETY VIOLATION TESTS
# ============================================

class TestSafetyViolation:
    """Tests for SafetyViolation dataclass."""

    def test_violation_creation(self):
        """Test basic violation creation."""
        violation = SafetyViolation(
            policy_name="test_policy",
            severity=ViolationSeverity.HIGH,
            message="Test violation",
            action="test_action",
            context={"agent": "test"}
        )
        assert violation.policy_name == "test_policy"
        assert violation.severity == ViolationSeverity.HIGH
        assert violation.message == "Test violation"
        assert violation.action == "test_action"
        assert violation.context == {"agent": "test"}
        assert violation.remediation_hint is None
        assert violation.metadata == {}

    def test_violation_with_optional_fields(self):
        """Test violation with all optional fields."""
        violation = SafetyViolation(
            policy_name="test_policy",
            severity=ViolationSeverity.CRITICAL,
            message="Critical error",
            action="dangerous_action",
            context={},
            timestamp="2026-01-26T10:00:00Z",
            remediation_hint="Fix by doing X",
            metadata={"extra": "data"}
        )
        assert violation.remediation_hint == "Fix by doing X"
        assert violation.metadata == {"extra": "data"}
        assert violation.timestamp == "2026-01-26T10:00:00Z"

    def test_violation_auto_timestamp(self):
        """Test that timestamp is auto-generated if not provided."""
        violation = SafetyViolation(
            policy_name="test",
            severity=ViolationSeverity.INFO,
            message="test",
            action="test",
            context={}
        )
        # Should have ISO format timestamp ending with Z
        assert violation.timestamp.endswith("Z")
        assert len(violation.timestamp) > 10

    def test_violation_to_dict(self):
        """Test conversion to dictionary."""
        violation = SafetyViolation(
            policy_name="test_policy",
            severity=ViolationSeverity.MEDIUM,
            message="Test message",
            action="test_action",
            context={"key": "value"},
            remediation_hint="hint"
        )
        d = violation.to_dict()
        assert d["policy_name"] == "test_policy"
        assert d["severity"] == "MEDIUM"
        assert d["severity_value"] == 3
        assert d["message"] == "Test message"
        assert d["action"] == "test_action"
        assert d["context"] == {"key": "value"}
        assert d["remediation_hint"] == "hint"


# ============================================
# VALIDATION RESULT TESTS
# ============================================

class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_validation_result_valid(self):
        """Test valid validation result."""
        result = ValidationResult(valid=True, policy_name="test")
        assert result.valid is True
        assert result.violations == []
        assert result.metadata == {}
        assert result.policy_name == "test"

    def test_validation_result_invalid(self):
        """Test invalid validation result with violations."""
        violation = SafetyViolation(
            policy_name="test",
            severity=ViolationSeverity.HIGH,
            message="error",
            action="action",
            context={}
        )
        result = ValidationResult(
            valid=False,
            violations=[violation],
            metadata={"reason": "test"},
            policy_name="test"
        )
        assert result.valid is False
        assert len(result.violations) == 1
        assert result.metadata["reason"] == "test"

    def test_has_critical_violations(self):
        """Test has_critical_violations() helper."""
        critical_violation = SafetyViolation(
            policy_name="test",
            severity=ViolationSeverity.CRITICAL,
            message="critical",
            action="action",
            context={}
        )
        high_violation = SafetyViolation(
            policy_name="test",
            severity=ViolationSeverity.HIGH,
            message="high",
            action="action",
            context={}
        )

        # Result with CRITICAL
        result1 = ValidationResult(
            valid=False,
            violations=[critical_violation],
            policy_name="test"
        )
        assert result1.has_critical_violations() is True

        # Result without CRITICAL
        result2 = ValidationResult(
            valid=False,
            violations=[high_violation],
            policy_name="test"
        )
        assert result2.has_critical_violations() is False

    def test_has_blocking_violations(self):
        """Test has_blocking_violations() helper."""
        high_violation = SafetyViolation(
            policy_name="test",
            severity=ViolationSeverity.HIGH,
            message="high",
            action="action",
            context={}
        )
        medium_violation = SafetyViolation(
            policy_name="test",
            severity=ViolationSeverity.MEDIUM,
            message="medium",
            action="action",
            context={}
        )

        # Result with HIGH (blocking)
        result1 = ValidationResult(
            valid=False,
            violations=[high_violation],
            policy_name="test"
        )
        assert result1.has_blocking_violations() is True

        # Result with only MEDIUM (not blocking)
        result2 = ValidationResult(
            valid=True,
            violations=[medium_violation],
            policy_name="test"
        )
        assert result2.has_blocking_violations() is False

    def test_get_violations_by_severity(self):
        """Test filtering violations by severity."""
        violations = [
            SafetyViolation(
                policy_name="test",
                severity=ViolationSeverity.CRITICAL,
                message="c",
                action="a",
                context={}
            ),
            SafetyViolation(
                policy_name="test",
                severity=ViolationSeverity.HIGH,
                message="h",
                action="a",
                context={}
            ),
            SafetyViolation(
                policy_name="test",
                severity=ViolationSeverity.HIGH,
                message="h2",
                action="a",
                context={}
            )
        ]
        result = ValidationResult(valid=False, violations=violations, policy_name="test")

        critical = result.get_violations_by_severity(ViolationSeverity.CRITICAL)
        assert len(critical) == 1
        assert critical[0].message == "c"

        high = result.get_violations_by_severity(ViolationSeverity.HIGH)
        assert len(high) == 2

        medium = result.get_violations_by_severity(ViolationSeverity.MEDIUM)
        assert len(medium) == 0


# ============================================
# SAFETY POLICY INTERFACE TESTS
# ============================================

class TestSafetyPolicy:
    """Tests for SafetyPolicy abstract interface."""

    def test_cannot_instantiate_abstract_policy(self):
        """Test that SafetyPolicy cannot be instantiated directly."""
        with pytest.raises(TypeError):
            SafetyPolicy()

    def test_concrete_policy_implementation(self):
        """Test that concrete policy implementations work."""
        class TestPolicy(SafetyPolicy):
            @property
            def name(self) -> str:
                return "test_policy"

            @property
            def version(self) -> str:
                return "1.0.0"

            def validate(self, action, context):
                return ValidationResult(valid=True, policy_name=self.name)

        policy = TestPolicy()
        assert policy.name == "test_policy"
        assert policy.version == "1.0.0"
        assert policy.priority == 100  # default
        assert policy.description == "Safety policy: test_policy"

        result = policy.validate({}, {})
        assert result.valid is True

    def test_custom_priority(self):
        """Test policy with custom priority."""
        class HighPriorityPolicy(SafetyPolicy):
            @property
            def name(self) -> str:
                return "high_priority"

            @property
            def version(self) -> str:
                return "1.0.0"

            @property
            def priority(self) -> int:
                return 500

            def validate(self, action, context):
                return ValidationResult(valid=True, policy_name=self.name)

        policy = HighPriorityPolicy()
        assert policy.priority == 500

    def test_custom_description(self):
        """Test policy with custom description."""
        class DescribedPolicy(SafetyPolicy):
            @property
            def name(self) -> str:
                return "described"

            @property
            def version(self) -> str:
                return "1.0.0"

            @property
            def description(self) -> str:
                return "A custom description"

            def validate(self, action, context):
                return ValidationResult(valid=True, policy_name=self.name)

        policy = DescribedPolicy()
        assert policy.description == "A custom description"


# ============================================
# BASE SAFETY POLICY TESTS
# ============================================

class TestBaseSafetyPolicy:
    """Tests for BaseSafetyPolicy implementation."""

    def test_base_policy_initialization(self):
        """Test BaseSafetyPolicy initialization."""
        class TestPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "test"

            @property
            def version(self) -> str:
                return "1.0.0"

        policy = TestPolicy({"key": "value"})
        assert policy.config == {"key": "value"}
        assert policy.get_child_policies() == []

    def test_add_child_policy(self):
        """Test adding child policies."""
        class ParentPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "parent"

            @property
            def version(self) -> str:
                return "1.0.0"

        class ChildPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "child"

            @property
            def version(self) -> str:
                return "1.0.0"

        parent = ParentPolicy({})
        child = ChildPolicy({})
        parent.add_child_policy(child)

        children = parent.get_child_policies()
        assert len(children) == 1
        assert children[0].name == "child"

    def test_child_policy_priority_ordering(self):
        """Test that child policies are sorted by priority."""
        class ParentPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "parent"

            @property
            def version(self) -> str:
                return "1.0.0"

        class LowPriorityPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "low"

            @property
            def version(self) -> str:
                return "1.0.0"

            @property
            def priority(self) -> int:
                return 50

        class HighPriorityPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "high"

            @property
            def version(self) -> str:
                return "1.0.0"

            @property
            def priority(self) -> int:
                return 200

        parent = ParentPolicy({})
        low = LowPriorityPolicy({})
        high = HighPriorityPolicy({})

        # Add in reverse priority order
        parent.add_child_policy(low)
        parent.add_child_policy(high)

        children = parent.get_child_policies()
        assert children[0].name == "high"  # Higher priority first
        assert children[1].name == "low"

    def test_validate_composition(self):
        """Test validation with child policy composition."""
        class AlwaysValidPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "always_valid"

            @property
            def version(self) -> str:
                return "1.0.0"

            def _validate_impl(self, action, context):
                return ValidationResult(valid=True, policy_name=self.name)

        class AlwaysInvalidPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "always_invalid"

            @property
            def version(self) -> str:
                return "1.0.0"

            def _validate_impl(self, action, context):
                return ValidationResult(
                    valid=False,
                    violations=[
                        SafetyViolation(
                            policy_name=self.name,
                            severity=ViolationSeverity.HIGH,
                            message="Invalid",
                            action=str(action),
                            context=context
                        )
                    ],
                    policy_name=self.name
                )

        parent = AlwaysValidPolicy({})
        child = AlwaysInvalidPolicy({})
        parent.add_child_policy(child)

        result = parent.validate({}, {})
        # Should be invalid because child is invalid
        assert result.valid is False
        assert len(result.violations) == 1
        assert result.violations[0].policy_name == "always_invalid"

    def test_short_circuit_on_critical(self):
        """Test that CRITICAL violations short-circuit evaluation."""
        class CriticalPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "critical"

            @property
            def version(self) -> str:
                return "1.0.0"

            def _validate_impl(self, action, context):
                return ValidationResult(
                    valid=False,
                    violations=[
                        SafetyViolation(
                            policy_name=self.name,
                            severity=ViolationSeverity.CRITICAL,
                            message="Critical error",
                            action=str(action),
                            context=context
                        )
                    ],
                    policy_name=self.name
                )

        class NeverCalledPolicy(BaseSafetyPolicy):
            def __init__(self, config):
                super().__init__(config)
                self.called = False

            @property
            def name(self) -> str:
                return "never_called"

            @property
            def version(self) -> str:
                return "1.0.0"

            def _validate_impl(self, action, context):
                self.called = True
                return ValidationResult(valid=True, policy_name=self.name)

        parent = NeverCalledPolicy({})
        critical = CriticalPolicy({})
        critical._priority = 200  # Ensure critical runs first
        parent.add_child_policy(critical)

        result = parent.validate({}, {})
        assert result.metadata.get("short_circuit") is True
        assert parent.called is False  # Parent validation never called

    @pytest.mark.asyncio
    async def test_async_validation(self):
        """Test async validation."""
        class AsyncPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "async"

            @property
            def version(self) -> str:
                return "1.0.0"

            async def _validate_async_impl(self, action, context):
                # Simulate async operation
                return ValidationResult(valid=True, policy_name=self.name)

        policy = AsyncPolicy({})
        result = await policy.validate_async({}, {})
        assert result.valid is True


# ============================================
# SAFETY SERVICE MIXIN TESTS
# ============================================

class TestSafetyServiceMixin:
    """Tests for SafetyServiceMixin."""

    def test_service_mixin_initialization(self):
        """Test service mixin initialization."""
        class TestService(Service, SafetyServiceMixin):
            @property
            def name(self) -> str:
                return "test_service"

        service = TestService()
        assert service.get_policies() == []

    def test_register_policy(self):
        """Test registering policies."""
        class TestService(Service, SafetyServiceMixin):
            @property
            def name(self) -> str:
                return "test_service"

        class TestPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "test"

            @property
            def version(self) -> str:
                return "1.0.0"

        service = TestService()
        policy = TestPolicy({})
        service.register_policy(policy)

        policies = service.get_policies()
        assert len(policies) == 1
        assert policies[0].name == "test"

    def test_validate_action(self):
        """Test action validation through service."""
        class TestService(Service, SafetyServiceMixin):
            @property
            def name(self) -> str:
                return "test_service"

        class RejectAllPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "reject_all"

            @property
            def version(self) -> str:
                return "1.0.0"

            def _validate_impl(self, action, context):
                return ValidationResult(
                    valid=False,
                    violations=[
                        SafetyViolation(
                            policy_name=self.name,
                            severity=ViolationSeverity.HIGH,
                            message="Rejected",
                            action=str(action),
                            context=context
                        )
                    ],
                    policy_name=self.name
                )

        service = TestService()
        policy = RejectAllPolicy({})
        service.register_policy(policy)

        result = service.validate_action({}, {})
        assert result.valid is False
        assert len(result.violations) == 1

    def test_handle_violations_no_exception(self):
        """Test handling violations without raising exception."""
        class TestService(Service, SafetyServiceMixin):
            @property
            def name(self) -> str:
                return "test"

        service = TestService()
        violation = SafetyViolation(
            policy_name="test",
            severity=ViolationSeverity.LOW,
            message="Low severity",
            action="action",
            context={}
        )

        # Should not raise
        service.handle_violations([violation], raise_exception=True)

    def test_handle_violations_raises_on_high(self):
        """Test that HIGH violations raise exception."""
        class TestService(Service, SafetyServiceMixin):
            @property
            def name(self) -> str:
                return "test"

        service = TestService()
        violation = SafetyViolation(
            policy_name="test",
            severity=ViolationSeverity.HIGH,
            message="High severity",
            action="action",
            context={}
        )

        with pytest.raises(RuntimeError, match="HIGH safety violation"):
            service.handle_violations([violation], raise_exception=True)

    def test_handle_violations_raises_on_critical(self):
        """Test that CRITICAL violations raise exception."""
        class TestService(Service, SafetyServiceMixin):
            @property
            def name(self) -> str:
                return "test"

        service = TestService()
        violation = SafetyViolation(
            policy_name="test",
            severity=ViolationSeverity.CRITICAL,
            message="Critical error",
            action="action",
            context={}
        )

        with pytest.raises(RuntimeError, match="CRITICAL safety violation"):
            service.handle_violations([violation], raise_exception=True)

    @pytest.mark.asyncio
    async def test_validate_action_async(self):
        """Test async action validation."""
        class TestService(Service, SafetyServiceMixin):
            @property
            def name(self) -> str:
                return "test_service"

        class AsyncPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "async_policy"

            @property
            def version(self) -> str:
                return "1.0.0"

            async def _validate_async_impl(self, action, context):
                return ValidationResult(valid=True, policy_name=self.name)

        service = TestService()
        policy = AsyncPolicy({})
        service.register_policy(policy)

        result = await service.validate_action_async({}, {})
        assert result.valid is True


# ============================================
# EDGE CASE TESTS
# ============================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_severity_comparison_with_non_severity(self):
        """Test that comparing severity with non-severity returns NotImplemented."""
        severity = ViolationSeverity.HIGH
        # These should return NotImplemented (not raise error)
        assert severity.__lt__(5) == NotImplemented
        assert severity.__le__(5) == NotImplemented
        assert severity.__gt__(5) == NotImplemented
        assert severity.__ge__(5) == NotImplemented

    def test_safety_policy_report_violation_default(self):
        """Test default report_violation does nothing."""
        class TestPolicy(SafetyPolicy):
            @property
            def name(self) -> str:
                return "test"

            @property
            def version(self) -> str:
                return "1.0.0"

            def validate(self, action, context):
                return ValidationResult(valid=True, policy_name=self.name)

        policy = TestPolicy()
        violation = SafetyViolation(
            policy_name="test",
            severity=ViolationSeverity.INFO,
            message="test",
            action="action",
            context={}
        )
        # Should not raise
        policy.report_violation(violation)

    def test_validator_interface(self):
        """Test Validator interface."""
        class TestValidator(Validator):
            def validate(self, value, context):
                return ValidationResult(valid=True, policy_name="validator")

        validator = TestValidator()
        result = validator.validate("test", {})
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_base_policy_async_short_circuit(self):
        """Test async validation short-circuits on CRITICAL."""
        class CriticalAsyncPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "critical_async"

            @property
            def version(self) -> str:
                return "1.0.0"

            async def _validate_async_impl(self, action, context):
                return ValidationResult(
                    valid=False,
                    violations=[
                        SafetyViolation(
                            policy_name=self.name,
                            severity=ViolationSeverity.CRITICAL,
                            message="Critical",
                            action=str(action),
                            context=context
                        )
                    ],
                    policy_name=self.name
                )

        class NeverCalledAsync(BaseSafetyPolicy):
            def __init__(self, config):
                super().__init__(config)
                self.called = False

            @property
            def name(self) -> str:
                return "never_called"

            @property
            def version(self) -> str:
                return "1.0.0"

            async def _validate_async_impl(self, action, context):
                self.called = True
                return ValidationResult(valid=True, policy_name=self.name)

        parent = NeverCalledAsync({})
        critical = CriticalAsyncPolicy({})
        parent.add_child_policy(critical)

        result = await parent.validate_async({}, {})
        assert result.metadata.get("short_circuit") is True
        assert parent.called is False

    def test_service_base_class(self):
        """Test Service base class methods."""
        class TestService(Service):
            @property
            def name(self) -> str:
                return "test"

        service = TestService()
        # These should not raise (default implementations)
        service.initialize()
        service.shutdown()

    def test_metadata_no_override(self):
        """Test that child metadata doesn't override parent metadata."""
        class ParentPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "parent"

            @property
            def version(self) -> str:
                return "1.0.0"

            def _validate_impl(self, action, context):
                return ValidationResult(
                    valid=True,
                    metadata={"shared_key": "parent_value"},
                    policy_name=self.name
                )

        class ChildPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "child"

            @property
            def version(self) -> str:
                return "1.0.0"

            def _validate_impl(self, action, context):
                return ValidationResult(
                    valid=True,
                    metadata={"shared_key": "child_value"},
                    policy_name=self.name
                )

        parent = ParentPolicy({})
        child = ChildPolicy({})
        parent.add_child_policy(child)

        result = parent.validate({}, {})
        # Child metadata should be prefixed, not override parent
        assert result.metadata["shared_key"] == "parent_value"

    def test_base_policy_default_validate_impl(self):
        """Test default _validate_impl returns valid."""
        class MinimalPolicy(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "minimal"

            @property
            def version(self) -> str:
                return "1.0.0"

        policy = MinimalPolicy({})

        # Call internal method directly (not overridden, so uses default)
        result = policy._validate_impl({}, {})
        assert result.valid is True
        assert len(result.violations) == 0

    @pytest.mark.asyncio
    async def test_base_policy_default_async_validate_impl(self):
        """Test default _validate_async_impl calls sync version."""
        class TestPolicy(BaseSafetyPolicy):
            def __init__(self, config):
                super().__init__(config)
                self.sync_called = False

            @property
            def name(self) -> str:
                return "test"

            @property
            def version(self) -> str:
                return "1.0.0"

            def _validate_impl(self, action, context):
                self.sync_called = True
                return ValidationResult(valid=True, policy_name=self.name)

        policy = TestPolicy({})
        result = await policy._validate_async_impl({}, {})
        assert policy.sync_called is True
        assert result.valid is True

    def test_service_mixin_handle_violations_no_raise(self):
        """Test handle_violations with raise_exception=False."""
        class TestService(Service, SafetyServiceMixin):
            @property
            def name(self) -> str:
                return "test"

        service = TestService()
        violation = SafetyViolation(
            policy_name="test",
            severity=ViolationSeverity.CRITICAL,
            message="Critical",
            action="action",
            context={}
        )

        # Should not raise when raise_exception=False
        service.handle_violations([violation], raise_exception=False)

    def test_service_mixin_handle_empty_violations(self):
        """Test handle_violations with empty list."""
        class TestService(Service, SafetyServiceMixin):
            @property
            def name(self) -> str:
                return "test"

        service = TestService()
        # Should not raise with empty list
        service.handle_violations([])

    def test_validation_with_metadata_merge(self):
        """Test that metadata from child and parent are merged correctly."""
        class ChildWithMetadata(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "child"

            @property
            def version(self) -> str:
                return "1.0.0"

            def _validate_impl(self, action, context):
                return ValidationResult(
                    valid=True,
                    metadata={"child_key": "child_value", "common": "from_child"},
                    policy_name=self.name
                )

        class ParentWithMetadata(BaseSafetyPolicy):
            @property
            def name(self) -> str:
                return "parent"

            @property
            def version(self) -> str:
                return "1.0.0"

            def _validate_impl(self, action, context):
                return ValidationResult(
                    valid=True,
                    metadata={"parent_key": "parent_value", "common": "from_parent"},
                    policy_name=self.name
                )

        parent = ParentWithMetadata({})
        child = ChildWithMetadata({})
        parent.add_child_policy(child)

        result = parent.validate({}, {})
        # Parent metadata should take precedence for "common" key
        assert result.metadata["common"] == "from_parent"
        assert result.metadata["parent_key"] == "parent_value"
        # Child metadata should be prefixed
        assert "child_child_child_key" in result.metadata
