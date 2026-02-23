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
    "RateLimiterPolicy": (
        "temper_ai.safety.rate_limiter",
        "RateLimiterPolicy",
    ),  # backward-compat alias
    "FileAccessPolicy": ("temper_ai.safety.file_access", "FileAccessPolicy"),
    "ForbiddenOperationsPolicy": (
        "temper_ai.safety.forbidden_operations",
        "ForbiddenOperationsPolicy",
    ),
    # Policy composition
    "PolicyComposer": ("temper_ai.safety.composition", "PolicyComposer"),
    "CompositeValidationResult": (
        "temper_ai.safety.composition",
        "CompositeValidationResult",
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
    # Circuit breakers and safety gates
    "CircuitBreaker": ("temper_ai.safety.circuit_breaker", "CircuitBreaker"),
    "CircuitBreakerState": ("temper_ai.safety.circuit_breaker", "CircuitBreakerState"),
    "CircuitBreakerOpen": ("temper_ai.safety.circuit_breaker", "CircuitBreakerOpen"),
    "CircuitBreakerMetrics": (
        "temper_ai.safety.circuit_breaker",
        "CircuitBreakerMetrics",
    ),
    "SafetyGate": ("temper_ai.safety.circuit_breaker", "SafetyGate"),
    "SafetyGateBlocked": ("temper_ai.safety.circuit_breaker", "SafetyGateBlocked"),
    "CircuitBreakerManager": (
        "temper_ai.safety.circuit_breaker",
        "CircuitBreakerManager",
    ),
    # Token bucket rate limiting
    "TokenBucket": ("temper_ai.safety.token_bucket", "TokenBucket"),
    "TokenBucketManager": ("temper_ai.safety.token_bucket", "TokenBucketManager"),
    "RateLimit": ("temper_ai.safety.token_bucket", "RateLimit"),
    "TokenBucketRateLimitPolicy": (
        "temper_ai.safety.policies.rate_limit_policy",
        "TokenBucketRateLimitPolicy",
    ),
    "RateLimitPolicy": (
        "temper_ai.safety.policies.rate_limit_policy",
        "RateLimitPolicy",
    ),  # backward-compat alias
    "RateLimitPolicyV2": (
        "temper_ai.safety.policies.rate_limit_policy",
        "RateLimitPolicy",
    ),  # backward-compat alias
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
    # Models (aliases for compatibility)
    "SafetyViolationModel": ("temper_ai.safety.interfaces", "SafetyViolation"),
    "ValidationResultModel": ("temper_ai.safety.interfaces", "ValidationResult"),
    "ViolationSeverityEnum": ("temper_ai.safety.interfaces", "ViolationSeverity"),
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


# Aliases that are deprecated and should emit warnings on first access.
_DEPRECATED_ALIASES = {
    "SafetyViolationModel": "SafetyViolation",
    "ValidationResultModel": "ValidationResult",
    "ViolationSeverityEnum": "ViolationSeverity",
    "RateLimitPolicyV2": "TokenBucketRateLimitPolicy",
    "RateLimiterPolicy": "WindowRateLimitPolicy",
    "RateLimitPolicy": "TokenBucketRateLimitPolicy",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        module_path, obj_name = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        obj = getattr(module, obj_name)
        if name in _DEPRECATED_ALIASES:
            import warnings

            canonical = _DEPRECATED_ALIASES[name]
            warnings.warn(
                f"'{name}' is deprecated, use '{canonical}' instead",
                DeprecationWarning,
                stacklevel=2,
            )
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
