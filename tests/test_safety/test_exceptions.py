"""Tests for safety system exception hierarchy.

Tests cover:
- Base SafetyViolationException creation and serialization
- Specific exception types (BlastRadiusViolation, etc.)
- Exception message formatting
- Conversion to/from SafetyViolation data models
- Metadata and remediation hints
"""

import pytest

from temper_ai.safety.exceptions import (
    AccessDeniedViolation,
    ActionPolicyViolation,
    BlastRadiusViolation,
    ForbiddenOperationViolation,
    RateLimitViolation,
    ResourceLimitViolation,
    SafetyViolationException,
)
from temper_ai.safety.interfaces import SafetyViolation, ViolationSeverity


class TestSafetyViolationException:
    """Tests for base SafetyViolationException class."""

    def test_create_exception(self):
        """Test creating basic safety violation exception."""
        exc = SafetyViolationException(
            policy_name="TestPolicy",
            severity=ViolationSeverity.HIGH,
            message="Test violation",
            action="test_action",
            context={"agent": "test_agent"},
        )

        assert exc.policy_name == "TestPolicy"
        assert exc.severity == ViolationSeverity.HIGH
        assert exc.message == "Test violation"
        assert exc.action == "test_action"
        assert exc.context == {"agent": "test_agent"}
        assert exc.remediation_hint is None
        assert exc.metadata == {}

    def test_exception_with_remediation(self):
        """Test exception with remediation hint."""
        exc = SafetyViolationException(
            policy_name="TestPolicy",
            severity=ViolationSeverity.MEDIUM,
            message="Rate limit exceeded",
            action="api_call",
            context={"agent": "researcher"},
            remediation_hint="Wait 60 seconds before retrying",
        )

        assert exc.remediation_hint == "Wait 60 seconds before retrying"

    def test_exception_with_metadata(self):
        """Test exception with custom metadata."""
        metadata = {"limit": 100, "current": 150, "retry_after": 60}

        exc = SafetyViolationException(
            policy_name="RateLimit",
            severity=ViolationSeverity.HIGH,
            message="Exceeded limit",
            action="api_call",
            context={},
            metadata=metadata,
        )

        assert exc.metadata == metadata

    def test_exception_str_formatting(self):
        """Test string representation of exception."""
        exc = SafetyViolationException(
            policy_name="TestPolicy",
            severity=ViolationSeverity.CRITICAL,
            message="Critical violation",
            action="dangerous_action",
            context={},
        )

        str_repr = str(exc)
        assert "[CRITICAL]" in str_repr
        assert "TestPolicy" in str_repr
        assert "Critical violation" in str_repr

    def test_exception_str_with_remediation(self):
        """Test string representation includes remediation hint."""
        exc = SafetyViolationException(
            policy_name="TestPolicy",
            severity=ViolationSeverity.HIGH,
            message="Test violation",
            action="test",
            context={},
            remediation_hint="Fix by doing X",
        )

        str_repr = str(exc)
        assert "Remediation: Fix by doing X" in str_repr

    def test_exception_repr(self):
        """Test repr output."""
        exc = SafetyViolationException(
            policy_name="TestPolicy",
            severity=ViolationSeverity.MEDIUM,
            message="Test message",
            action="test",
            context={},
        )

        repr_str = repr(exc)
        assert "SafetyViolationException" in repr_str
        assert "policy=TestPolicy" in repr_str
        assert "severity=MEDIUM" in repr_str
        assert "Test message" in repr_str

    def test_to_dict_serialization(self):
        """Test converting exception to dictionary."""
        exc = SafetyViolationException(
            policy_name="TestPolicy",
            severity=ViolationSeverity.HIGH,
            message="Test violation",
            action="test_action",
            context={"agent": "test", "stage": "research"},
            remediation_hint="Fix it",
            metadata={"key": "value"},
        )

        data = exc.to_dict()

        assert data["policy_name"] == "TestPolicy"
        assert data["severity"] == "HIGH"
        assert data["severity_value"] == 4
        assert data["message"] == "Test violation"
        assert data["action"] == "test_action"
        assert data["context"] == {"agent": "test", "stage": "research"}
        assert data["remediation_hint"] == "Fix it"
        assert data["metadata"] == {"key": "value"}
        assert "timestamp" in data

    def test_from_violation_conversion(self):
        """Test creating exception from SafetyViolation."""
        violation = SafetyViolation(
            policy_name="OriginalPolicy",
            severity=ViolationSeverity.CRITICAL,
            message="Original violation",
            action="original_action",
            context={"test": "data"},
            remediation_hint="Original hint",
            metadata={"original": "metadata"},
        )

        exc = SafetyViolationException.from_violation(violation)

        assert exc.policy_name == violation.policy_name
        assert exc.severity == violation.severity
        assert exc.message == violation.message
        assert exc.action == violation.action
        assert exc.context == violation.context
        assert exc.remediation_hint == violation.remediation_hint
        assert exc.metadata == violation.metadata

    def test_exception_wraps_violation(self):
        """Test that exception wraps SafetyViolation data model."""
        exc = SafetyViolationException(
            policy_name="TestPolicy",
            severity=ViolationSeverity.HIGH,
            message="Test",
            action="test",
            context={},
        )

        assert isinstance(exc.violation, SafetyViolation)
        assert exc.violation.policy_name == "TestPolicy"
        assert exc.violation.severity == ViolationSeverity.HIGH

    def test_exception_is_raiseable(self):
        """Test that exception can be raised and caught."""
        with pytest.raises(SafetyViolationException) as exc_info:
            raise SafetyViolationException(
                policy_name="TestPolicy",
                severity=ViolationSeverity.HIGH,
                message="Test violation",
                action="test",
                context={},
            )

        assert exc_info.value.policy_name == "TestPolicy"
        assert exc_info.value.severity == ViolationSeverity.HIGH


class TestBlastRadiusViolation:
    """Tests for BlastRadiusViolation exception."""

    def test_create_blast_radius_violation(self):
        """Test creating blast radius violation."""
        exc = BlastRadiusViolation(
            policy_name="BlastRadiusPolicy",
            message="Too many files modified",
            action="bulk_edit",
            context={"agent": "coder"},
            metadata={"files": 50, "limit": 10},
        )

        assert exc.policy_name == "BlastRadiusPolicy"
        assert exc.severity == ViolationSeverity.HIGH
        assert exc.message == "Too many files modified"
        assert exc.metadata["files"] == 50
        assert exc.metadata["limit"] == 10

    def test_default_remediation_hint(self):
        """Test blast radius has default remediation hint."""
        exc = BlastRadiusViolation(
            policy_name="BlastRadiusPolicy",
            message="Exceeds limits",
            action="bulk_change",
            context={},
        )

        assert exc.remediation_hint == "Reduce the scope of changes"

    def test_custom_remediation_hint(self):
        """Test custom remediation overrides default."""
        exc = BlastRadiusViolation(
            policy_name="BlastRadiusPolicy",
            message="Too large",
            action="commit",
            context={},
            remediation_hint="Split into 3 smaller commits",
        )

        assert exc.remediation_hint == "Split into 3 smaller commits"

    def test_inheritance(self):
        """Test that BlastRadiusViolation inherits from base."""
        exc = BlastRadiusViolation(
            policy_name="Test", message="Test", action="test", context={}
        )

        assert isinstance(exc, SafetyViolationException)
        assert isinstance(exc, Exception)


class TestActionPolicyViolation:
    """Tests for ActionPolicyViolation exception."""

    def test_create_action_policy_violation(self):
        """Test creating action policy violation."""
        exc = ActionPolicyViolation(
            policy_name="ActionPolicy",
            message="Forbidden tool",
            action="execute_shell('rm -rf /')",
            context={"agent": "untrusted"},
            metadata={"tool": "execute_shell", "reason": "destructive"},
        )

        assert exc.policy_name == "ActionPolicy"
        assert exc.severity == ViolationSeverity.CRITICAL
        assert "Forbidden tool" in exc.message
        assert exc.metadata["tool"] == "execute_shell"

    def test_critical_severity(self):
        """Test action policy violations are CRITICAL."""
        exc = ActionPolicyViolation(
            policy_name="ActionPolicy", message="Test", action="test", context={}
        )

        assert exc.severity == ViolationSeverity.CRITICAL

    def test_default_remediation(self):
        """Test default remediation hint."""
        exc = ActionPolicyViolation(
            policy_name="ActionPolicy", message="Test", action="test", context={}
        )

        assert exc.remediation_hint == "Review action policy constraints"


class TestRateLimitViolation:
    """Tests for RateLimitViolation exception."""

    def test_create_rate_limit_violation(self):
        """Test creating rate limit violation."""
        exc = RateLimitViolation(
            policy_name="RateLimiter",
            message="API rate limit exceeded",
            action="api_call",
            context={"agent": "researcher"},
            metadata={
                "current_rate": 100,
                "limit": 50,
                "window": "1h",
                "retry_after": 30,
            },
        )

        assert exc.policy_name == "RateLimiter"
        assert exc.severity == ViolationSeverity.MEDIUM
        assert exc.metadata["current_rate"] == 100
        assert exc.metadata["limit"] == 50
        assert exc.metadata["retry_after"] == 30

    def test_medium_severity(self):
        """Test rate limit violations are MEDIUM severity."""
        exc = RateLimitViolation(
            policy_name="RateLimiter", message="Test", action="test", context={}
        )

        assert exc.severity == ViolationSeverity.MEDIUM

    def test_default_remediation(self):
        """Test default remediation hint."""
        exc = RateLimitViolation(
            policy_name="RateLimiter", message="Test", action="test", context={}
        )

        assert "Reduce request rate" in exc.remediation_hint


class TestResourceLimitViolation:
    """Tests for ResourceLimitViolation exception."""

    def test_create_resource_limit_violation(self):
        """Test creating resource limit violation."""
        exc = ResourceLimitViolation(
            policy_name="ResourceLimiter",
            message="Memory limit exceeded",
            action="load_data",
            context={"agent": "analyst"},
            metadata={
                "resource": "memory",
                "current": 950,
                "requested": 100,
                "limit": 1024,
            },
        )

        assert exc.policy_name == "ResourceLimiter"
        assert exc.severity == ViolationSeverity.HIGH
        assert exc.metadata["resource"] == "memory"
        assert exc.metadata["current"] == 950

    def test_high_severity(self):
        """Test resource violations are HIGH severity."""
        exc = ResourceLimitViolation(
            policy_name="ResourceLimiter", message="Test", action="test", context={}
        )

        assert exc.severity == ViolationSeverity.HIGH


class TestForbiddenOperationViolation:
    """Tests for ForbiddenOperationViolation exception."""

    def test_create_forbidden_operation_violation(self):
        """Test creating forbidden operation violation."""
        exc = ForbiddenOperationViolation(
            policy_name="ForbiddenOps",
            message="Secret access forbidden",
            action="os.getenv('API_KEY')",
            context={"agent": "untrusted"},
            metadata={"operation": "secret_access", "pattern": "API_KEY"},
        )

        assert exc.policy_name == "ForbiddenOps"
        assert exc.severity == ViolationSeverity.CRITICAL
        assert exc.metadata["operation"] == "secret_access"

    def test_critical_severity(self):
        """Test forbidden operations are CRITICAL."""
        exc = ForbiddenOperationViolation(
            policy_name="ForbiddenOps", message="Test", action="test", context={}
        )

        assert exc.severity == ViolationSeverity.CRITICAL


class TestAccessDeniedViolation:
    """Tests for AccessDeniedViolation exception."""

    def test_create_access_denied_violation(self):
        """Test creating access denied violation."""
        exc = AccessDeniedViolation(
            policy_name="FileAccessPolicy",
            message="Access to /etc/passwd denied",
            action="read_file(/etc/passwd)",
            context={"agent": "researcher"},
            metadata={"path": "/etc/passwd", "allowed_paths": ["/project/*"]},
        )

        assert exc.policy_name == "FileAccessPolicy"
        assert exc.severity == ViolationSeverity.CRITICAL
        assert exc.metadata["path"] == "/etc/passwd"
        assert exc.metadata["allowed_paths"] == ["/project/*"]

    def test_critical_severity(self):
        """Test access denied is CRITICAL."""
        exc = AccessDeniedViolation(
            policy_name="FileAccessPolicy", message="Test", action="test", context={}
        )

        assert exc.severity == ViolationSeverity.CRITICAL


class TestExceptionHierarchy:
    """Tests for exception hierarchy and inheritance."""

    def test_all_inherit_from_base(self):
        """Test that all specific exceptions inherit from base."""
        base_exc = SafetyViolationException(
            policy_name="Test",
            severity=ViolationSeverity.HIGH,
            message="Test",
            action="test",
            context={},
        )

        blast_exc = BlastRadiusViolation(
            policy_name="Test", message="Test", action="test", context={}
        )

        action_exc = ActionPolicyViolation(
            policy_name="Test", message="Test", action="test", context={}
        )

        rate_exc = RateLimitViolation(
            policy_name="Test", message="Test", action="test", context={}
        )

        resource_exc = ResourceLimitViolation(
            policy_name="Test", message="Test", action="test", context={}
        )

        forbidden_exc = ForbiddenOperationViolation(
            policy_name="Test", message="Test", action="test", context={}
        )

        access_exc = AccessDeniedViolation(
            policy_name="Test", message="Test", action="test", context={}
        )

        # All should be instances of SafetyViolationException
        assert isinstance(blast_exc, SafetyViolationException)
        assert isinstance(action_exc, SafetyViolationException)
        assert isinstance(rate_exc, SafetyViolationException)
        assert isinstance(resource_exc, SafetyViolationException)
        assert isinstance(forbidden_exc, SafetyViolationException)
        assert isinstance(access_exc, SafetyViolationException)

    def test_catch_specific_exception(self):
        """Test catching specific exception types."""
        with pytest.raises(BlastRadiusViolation):
            raise BlastRadiusViolation(
                policy_name="Test", message="Test", action="test", context={}
            )

    def test_catch_base_exception(self):
        """Test catching via base exception class."""
        with pytest.raises(SafetyViolationException):
            raise ActionPolicyViolation(
                policy_name="Test", message="Test", action="test", context={}
            )


class TestExceptionSerialization:
    """Tests for exception serialization and observability integration."""

    def test_serialization_preserves_data(self):
        """Test that serialization preserves all data."""
        exc = SafetyViolationException(
            policy_name="TestPolicy",
            severity=ViolationSeverity.HIGH,
            message="Test violation",
            action="test_action",
            context={"agent": "test", "key": "value"},
            remediation_hint="Fix it",
            metadata={"meta": "data"},
        )

        data = exc.to_dict()

        # Create new exception from same data
        exc2 = SafetyViolationException(
            policy_name=data["policy_name"],
            severity=ViolationSeverity[data["severity"]],
            message=data["message"],
            action=data["action"],
            context=data["context"],
            remediation_hint=data["remediation_hint"],
            metadata=data["metadata"],
        )

        assert exc2.policy_name == exc.policy_name
        assert exc2.severity == exc.severity
        assert exc2.message == exc.message
        assert exc2.context == exc.context

    def test_json_serializable(self):
        """Test that to_dict() output is JSON-serializable."""
        import json

        exc = SafetyViolationException(
            policy_name="TestPolicy",
            severity=ViolationSeverity.CRITICAL,
            message="Test",
            action="test",
            context={"key": "value"},
            metadata={"num": 123, "str": "text"},
        )

        data = exc.to_dict()

        # Should not raise exception
        json_str = json.dumps(data)
        reconstructed = json.loads(json_str)

        assert reconstructed["policy_name"] == "TestPolicy"
        assert reconstructed["severity"] == "CRITICAL"


class TestExceptionMessages:
    """Tests for exception message clarity and remediation hints."""

    def test_clear_error_messages(self):
        """Test that error messages are clear and actionable."""
        exc = BlastRadiusViolation(
            policy_name="BlastRadius",
            message="Attempted to modify 50 files (limit: 10)",
            action="bulk_commit",
            context={},
            remediation_hint="Split changes into 5 separate commits",
        )

        assert "50 files" in exc.message
        assert "limit: 10" in exc.message
        assert "Split changes" in exc.remediation_hint

    def test_remediation_hints_are_actionable(self):
        """Test that remediation hints provide concrete steps."""
        exc = RateLimitViolation(
            policy_name="RateLimit",
            message="Rate limit exceeded",
            action="api_call",
            context={},
            remediation_hint="Wait 60 seconds before retrying",
        )

        # Should include specific time
        assert "60 seconds" in exc.remediation_hint
