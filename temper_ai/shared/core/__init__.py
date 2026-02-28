"""Core framework components.

This package contains foundational components used throughout the framework:
- Circuit breakers for fault tolerance
- Context management for execution state
- Protocol definitions for common patterns
- Service utilities
"""


# Lazy imports to avoid circular dependencies
def __getattr__(name: str) -> type:
    if name == "CircuitBreaker":
        from temper_ai.shared.core.circuit_breaker import CircuitBreaker

        return CircuitBreaker
    elif name == "ExecutionContext":
        from temper_ai.shared.core.context import ExecutionContext

        return ExecutionContext
    raise AttributeError(f"module 'temper_ai.shared.core' has no attribute {name!r}")


__all__ = [
    "CircuitBreaker",
    "ExecutionContext",
]
