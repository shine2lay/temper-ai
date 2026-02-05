"""Safety system for policy enforcement and validation.

This package provides the foundational interfaces and base classes for
implementing safety policies in the meta-autonomous framework.

Key components:
- SafetyPolicy: Abstract interface for all safety policies
- BaseSafetyPolicy: Base implementation with composition support
- SafetyViolation: Represents policy violations
- ValidationResult: Result of policy validation
- ViolationSeverity: Severity levels for violations

Example usage:
    >>> from src.safety import BaseSafetyPolicy, ValidationResult, ViolationSeverity
    >>> from src.safety import SafetyViolation
    >>>
    >>> class MyPolicy(BaseSafetyPolicy):
    ...     @property
    ...     def name(self) -> str:
    ...         return "my_custom_policy"
    ...
    ...     @property
    ...     def version(self) -> str:
    ...         return "1.0.0"
    ...
    ...     def _validate_impl(self, action, context):
    ...         # Custom validation logic
    ...         if action.get("forbidden"):
    ...             return ValidationResult(
    ...                 valid=False,
    ...                 violations=[SafetyViolation(
    ...                     policy_name=self.name,
    ...                     severity=ViolationSeverity.HIGH,
    ...                     message="Forbidden action detected",
    ...                     action=str(action),
    ...                     context=context
    ...                 )],
    ...                 policy_name=self.name
    ...             )
    ...         return ValidationResult(valid=True, policy_name=self.name)
"""

from src.safety.interfaces import (
    SafetyPolicy,
    Validator,
    SafetyViolation,
    ValidationResult,
    ViolationSeverity
)
from src.safety.base import BaseSafetyPolicy
from src.safety.blast_radius import BlastRadiusPolicy
from src.safety.secret_detection import SecretDetectionPolicy
from src.safety.rate_limiter import RateLimiterPolicy
from src.safety.file_access import FileAccessPolicy

# Policy composition
from src.safety.composition import (
    PolicyComposer,
    CompositeValidationResult
)

# Approval workflow
from src.safety.approval import (
    ApprovalWorkflow,
    ApprovalRequest,
    ApprovalStatus
)

# Action Policy Engine
from src.safety.action_policy_engine import (
    ActionPolicyEngine,
    PolicyExecutionContext,
    EnforcementResult
)

# Policy Registry
from src.safety.policy_registry import PolicyRegistry

# Forbidden Operations
from src.safety.forbidden_operations import ForbiddenOperationsPolicy

# Rollback mechanism
from src.safety.rollback import (
    RollbackManager,
    RollbackSnapshot,
    RollbackResult,
    RollbackStatus,
    RollbackStrategy,
    FileRollbackStrategy,
    StateRollbackStrategy,
    CompositeRollbackStrategy
)

# Circuit breakers and safety gates
from src.safety.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
    CircuitBreakerOpen,
    CircuitBreakerMetrics,
    SafetyGate,
    SafetyGateBlocked,
    CircuitBreakerManager
)

# Token bucket rate limiting
from src.safety.token_bucket import TokenBucket, TokenBucketManager, RateLimit
from src.safety.policies.rate_limit_policy import RateLimitPolicy as RateLimitPolicyV2

# Resource consumption limits
from src.safety.policies.resource_limit_policy import ResourceLimitPolicy

# Service mixin
from src.safety.service_mixin import SafetyServiceMixin

# Exception hierarchy
from src.safety.exceptions import (
    SafetyViolationException,
    BlastRadiusViolation,
    ActionPolicyViolation,
    RateLimitViolation,
    ResourceLimitViolation,
    ForbiddenOperationViolation,
    AccessDeniedViolation,
)

# Models (re-export from interfaces for convenience)
from src.safety.models import (
    SafetyViolation as SafetyViolationModel,
    ValidationResult as ValidationResultModel,
    ViolationSeverity as ViolationSeverityEnum,
)

__all__ = [
    # Core interfaces
    "SafetyPolicy",
    "Validator",

    # Data structures
    "SafetyViolation",
    "ValidationResult",
    "ViolationSeverity",

    # Base implementations
    "BaseSafetyPolicy",

    # Concrete policies
    "BlastRadiusPolicy",
    "SecretDetectionPolicy",
    "RateLimiterPolicy",
    "FileAccessPolicy",
    "ForbiddenOperationsPolicy",

    # Policy composition
    "PolicyComposer",
    "CompositeValidationResult",

    # Action Policy Engine
    "ActionPolicyEngine",
    "PolicyExecutionContext",
    "EnforcementResult",

    # Policy Registry
    "PolicyRegistry",

    # Approval workflow
    "ApprovalWorkflow",
    "ApprovalRequest",
    "ApprovalStatus",

    # Rollback mechanism
    "RollbackManager",
    "RollbackSnapshot",
    "RollbackResult",
    "RollbackStatus",
    "RollbackStrategy",
    "FileRollbackStrategy",
    "StateRollbackStrategy",
    "CompositeRollbackStrategy",

    # Circuit breakers and safety gates
    "CircuitBreaker",
    "CircuitBreakerState",
    "CircuitBreakerOpen",
    "CircuitBreakerMetrics",
    "SafetyGate",
    "SafetyGateBlocked",
    "CircuitBreakerManager",

    # Token bucket rate limiting
    "TokenBucket",
    "TokenBucketManager",
    "RateLimit",
    "RateLimitPolicyV2",

    # Resource consumption limits
    "ResourceLimitPolicy",

    # Service mixin
    "SafetyServiceMixin",

    # Exceptions
    "SafetyViolationException",
    "BlastRadiusViolation",
    "ActionPolicyViolation",
    "RateLimitViolation",
    "ResourceLimitViolation",
    "ForbiddenOperationViolation",
    "AccessDeniedViolation",

    # Models (aliases for compatibility)
    "SafetyViolationModel",
    "ValidationResultModel",
    "ViolationSeverityEnum",
]

__version__ = "1.0.0"
