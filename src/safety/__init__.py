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

# Lazy-loading: imports are deferred until first access to reduce startup cost.
# Map attribute names to (module_path, object_name) for lazy resolution.
_LAZY_IMPORTS = {
    # Core interfaces (src.safety.interfaces)
    "SafetyPolicy": ("src.safety.interfaces", "SafetyPolicy"),
    "Validator": ("src.safety.interfaces", "Validator"),
    "SafetyViolation": ("src.safety.interfaces", "SafetyViolation"),
    "ValidationResult": ("src.safety.interfaces", "ValidationResult"),
    "ViolationSeverity": ("src.safety.interfaces", "ViolationSeverity"),
    # Base implementation
    "BaseSafetyPolicy": ("src.safety.base", "BaseSafetyPolicy"),
    # Concrete policies
    "BlastRadiusPolicy": ("src.safety.blast_radius", "BlastRadiusPolicy"),
    "SecretDetectionPolicy": ("src.safety.secret_detection", "SecretDetectionPolicy"),
    "WindowRateLimitPolicy": ("src.safety.rate_limiter", "WindowRateLimitPolicy"),
    "RateLimiterPolicy": ("src.safety.rate_limiter", "RateLimiterPolicy"),  # backward-compat alias
    "FileAccessPolicy": ("src.safety.file_access", "FileAccessPolicy"),
    "ForbiddenOperationsPolicy": ("src.safety.forbidden_operations", "ForbiddenOperationsPolicy"),
    # Policy composition
    "PolicyComposer": ("src.safety.composition", "PolicyComposer"),
    "CompositeValidationResult": ("src.safety.composition", "CompositeValidationResult"),
    # Approval workflow
    "ApprovalWorkflow": ("src.safety.approval", "ApprovalWorkflow"),
    "ApprovalRequest": ("src.safety.approval", "ApprovalRequest"),
    "ApprovalStatus": ("src.safety.approval", "ApprovalStatus"),
    # Action Policy Engine
    "ActionPolicyEngine": ("src.safety.action_policy_engine", "ActionPolicyEngine"),
    "PolicyExecutionContext": ("src.safety.action_policy_engine", "PolicyExecutionContext"),
    "EnforcementResult": ("src.safety.action_policy_engine", "EnforcementResult"),
    # Policy Registry
    "PolicyRegistry": ("src.safety.policy_registry", "PolicyRegistry"),
    # Rollback mechanism
    "RollbackManager": ("src.safety.rollback", "RollbackManager"),
    "RollbackSnapshot": ("src.safety.rollback", "RollbackSnapshot"),
    "RollbackResult": ("src.safety.rollback", "RollbackResult"),
    "RollbackStatus": ("src.safety.rollback", "RollbackStatus"),
    "RollbackStrategy": ("src.safety.rollback", "RollbackStrategy"),
    "FileRollbackStrategy": ("src.safety.rollback", "FileRollbackStrategy"),
    "StateRollbackStrategy": ("src.safety.rollback", "StateRollbackStrategy"),
    "CompositeRollbackStrategy": ("src.safety.rollback", "CompositeRollbackStrategy"),
    # Circuit breakers and safety gates
    "CircuitBreaker": ("src.safety.circuit_breaker", "CircuitBreaker"),
    "CircuitBreakerState": ("src.safety.circuit_breaker", "CircuitBreakerState"),
    "CircuitBreakerOpen": ("src.safety.circuit_breaker", "CircuitBreakerOpen"),
    "CircuitBreakerMetrics": ("src.safety.circuit_breaker", "CircuitBreakerMetrics"),
    "SafetyGate": ("src.safety.circuit_breaker", "SafetyGate"),
    "SafetyGateBlocked": ("src.safety.circuit_breaker", "SafetyGateBlocked"),
    "CircuitBreakerManager": ("src.safety.circuit_breaker", "CircuitBreakerManager"),
    # Token bucket rate limiting
    "TokenBucket": ("src.safety.token_bucket", "TokenBucket"),
    "TokenBucketManager": ("src.safety.token_bucket", "TokenBucketManager"),
    "RateLimit": ("src.safety.token_bucket", "RateLimit"),
    "TokenBucketRateLimitPolicy": ("src.safety.policies.rate_limit_policy", "TokenBucketRateLimitPolicy"),
    "RateLimitPolicy": ("src.safety.policies.rate_limit_policy", "RateLimitPolicy"),  # backward-compat alias
    "RateLimitPolicyV2": ("src.safety.policies.rate_limit_policy", "RateLimitPolicy"),  # backward-compat alias
    # Resource consumption limits
    "ResourceLimitPolicy": ("src.safety.policies.resource_limit_policy", "ResourceLimitPolicy"),
    # Service mixin
    "SafetyServiceMixin": ("src.safety.service_mixin", "SafetyServiceMixin"),
    # Exceptions
    "SafetyViolationException": ("src.safety.exceptions", "SafetyViolationException"),
    "BlastRadiusViolation": ("src.safety.exceptions", "BlastRadiusViolation"),
    "ActionPolicyViolation": ("src.safety.exceptions", "ActionPolicyViolation"),
    "RateLimitViolation": ("src.safety.exceptions", "RateLimitViolation"),
    "ResourceLimitViolation": ("src.safety.exceptions", "ResourceLimitViolation"),
    "ForbiddenOperationViolation": ("src.safety.exceptions", "ForbiddenOperationViolation"),
    "AccessDeniedViolation": ("src.safety.exceptions", "AccessDeniedViolation"),
    # Models (aliases for compatibility)
    "SafetyViolationModel": ("src.safety.interfaces", "SafetyViolation"),
    "ValidationResultModel": ("src.safety.interfaces", "ValidationResult"),
    "ViolationSeverityEnum": ("src.safety.interfaces", "ViolationSeverity"),
    # LLM Security boundary protocols
    "PromptInjectionDetectorProtocol": ("src.safety.interfaces", "PromptInjectionDetectorProtocol"),
    "OutputSanitizerProtocol": ("src.safety.interfaces", "OutputSanitizerProtocol"),
    "LLMRateLimiterProtocol": ("src.safety.interfaces", "LLMRateLimiterProtocol"),
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


def __getattr__(name: str):
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
    raise AttributeError(f"module 'src.safety' has no attribute {name!r}")


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
