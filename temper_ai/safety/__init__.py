"""Safety system for policy enforcement and validation.

This package provides the foundational interfaces and base classes for
implementing safety policies in Temper AI.

Key components:
- SafetyPolicy: Abstract interface for all safety policies
- BaseSafetyPolicy: Base implementation with composition support
- SafetyViolation: Represents policy violations
- ValidationResult: Result of policy validation
- ViolationSeverity: Severity levels for violations

Example usage:
    >>> from temper_ai.safety import BaseSafetyPolicy, ValidationResult, ViolationSeverity
    >>> from temper_ai.safety import SafetyViolation
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

from typing import Any

# Lazy-loading: imports are deferred until first access to reduce startup cost.
# Map attribute names to (module_path, object_name) for lazy resolution.
_LAZY_IMPORTS = {
    # Core interfaces (temper_ai.safety.interfaces)
    "SafetyPolicy": ("temper_ai.safety.interfaces", "SafetyPolicy"),
    "Validator": ("temper_ai.safety.interfaces", "Validator"),
    "SafetyViolation": ("temper_ai.safety.interfaces", "SafetyViolation"),
    "ValidationResult": ("temper_ai.safety.interfaces", "ValidationResult"),
    "ViolationSeverity": ("temper_ai.safety.interfaces", "ViolationSeverity"),
    # Base implementation
    "BaseSafetyPolicy": ("temper_ai.safety.base", "BaseSafetyPolicy"),
    # Concrete policies
    "BlastRadiusPolicy": ("temper_ai.safety.blast_radius", "BlastRadiusPolicy"),
    "SecretDetectionPolicy": (
        "temper_ai.safety.secret_detection",
        "SecretDetectionPolicy",
    ),
    "WindowRateLimitPolicy": ("temper_ai.safety.rate_limiter", "WindowRateLimitPolicy"),
    "FileAccessPolicy": ("temper_ai.safety.file_access", "FileAccessPolicy"),
    "ForbiddenOperationsPolicy": (
        "temper_ai.safety.forbidden_operations",
        "ForbiddenOperationsPolicy",
    ),
    # Approval workflow
    "ApprovalWorkflow": ("temper_ai.safety.approval", "ApprovalWorkflow"),
    "ApprovalRequest": ("temper_ai.safety.approval", "ApprovalRequest"),
    "ApprovalStatus": ("temper_ai.safety.approval", "ApprovalStatus"),
    # Action Policy Engine
    "ActionPolicyEngine": (
        "temper_ai.safety.action_policy_engine",
        "ActionPolicyEngine",
    ),
    "PolicyExecutionContext": (
        "temper_ai.safety.action_policy_engine",
        "PolicyExecutionContext",
    ),
    "EnforcementResult": ("temper_ai.safety.action_policy_engine", "EnforcementResult"),
    # Policy Registry
    "PolicyRegistry": ("temper_ai.safety.policy_registry", "PolicyRegistry"),
    # Rollback mechanism
    "RollbackManager": ("temper_ai.safety.rollback", "RollbackManager"),
    "RollbackSnapshot": ("temper_ai.safety.rollback", "RollbackSnapshot"),
    "RollbackResult": ("temper_ai.safety.rollback", "RollbackResult"),
    "RollbackStatus": ("temper_ai.safety.rollback", "RollbackStatus"),
    "RollbackStrategy": ("temper_ai.safety.rollback", "RollbackStrategy"),
    "FileRollbackStrategy": ("temper_ai.safety.rollback", "FileRollbackStrategy"),
    "StateRollbackStrategy": ("temper_ai.safety.rollback", "StateRollbackStrategy"),
    "CompositeRollbackStrategy": (
        "temper_ai.safety.rollback",
        "CompositeRollbackStrategy",
    ),
    # Token bucket rate limiting
    "TokenBucket": ("temper_ai.safety.token_bucket", "TokenBucket"),
    "TokenBucketManager": ("temper_ai.safety.token_bucket", "TokenBucketManager"),
    "RateLimit": ("temper_ai.safety.token_bucket", "RateLimit"),
    "TokenBucketRateLimitPolicy": (
        "temper_ai.safety.policies.rate_limit_policy",
        "TokenBucketRateLimitPolicy",
    ),
    # Resource consumption limits
    "ResourceLimitPolicy": (
        "temper_ai.safety.policies.resource_limit_policy",
        "ResourceLimitPolicy",
    ),
    # Service mixin
    "SafetyServiceMixin": ("temper_ai.safety.service_mixin", "SafetyServiceMixin"),
    # Exceptions
    "SafetyViolationException": (
        "temper_ai.safety.exceptions",
        "SafetyViolationException",
    ),
    "BlastRadiusViolation": ("temper_ai.safety.exceptions", "BlastRadiusViolation"),
    "ActionPolicyViolation": ("temper_ai.safety.exceptions", "ActionPolicyViolation"),
    "RateLimitViolation": ("temper_ai.safety.exceptions", "RateLimitViolation"),
    "ResourceLimitViolation": ("temper_ai.safety.exceptions", "ResourceLimitViolation"),
    "ForbiddenOperationViolation": (
        "temper_ai.safety.exceptions",
        "ForbiddenOperationViolation",
    ),
    "AccessDeniedViolation": ("temper_ai.safety.exceptions", "AccessDeniedViolation"),
    # LLM Security boundary protocols
    "PromptInjectionDetectorProtocol": (
        "temper_ai.safety.interfaces",
        "PromptInjectionDetectorProtocol",
    ),
    "OutputSanitizerProtocol": (
        "temper_ai.safety.interfaces",
        "OutputSanitizerProtocol",
    ),
    "LLMRateLimiterProtocol": ("temper_ai.safety.interfaces", "LLMRateLimiterProtocol"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        module_path, obj_name = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        obj = getattr(module, obj_name)
        # Cache in module namespace for subsequent fast access
        globals()[name] = obj
        return obj
    raise AttributeError(f"module 'temper_ai.safety' has no attribute {name!r}")


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
    "WindowRateLimitPolicy",
    "FileAccessPolicy",
    "ForbiddenOperationsPolicy",
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
    # Token bucket rate limiting
    "TokenBucket",
    "TokenBucketManager",
    "RateLimit",
    "TokenBucketRateLimitPolicy",
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
    # LLM Security boundary protocols
    "PromptInjectionDetectorProtocol",
    "OutputSanitizerProtocol",
    "LLMRateLimiterProtocol",
]

__version__ = "1.0.0"
