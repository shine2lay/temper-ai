"""Core framework components.

This package contains foundational components used throughout the framework:
- Circuit breakers for fault tolerance
- Context management for execution state
- Protocol definitions for common patterns
- Service utilities
"""
from src.core.protocols import (
    PolicyRegistry,
    Registry,
    StrategyRegistry,
    ToolRegistry,
)

# Lazy imports to avoid circular dependencies
def __getattr__(name: str):
    if name == "CircuitBreaker":
        from src.core.circuit_breaker import CircuitBreaker
        return CircuitBreaker
    elif name == "ExecutionContext":
        from src.core.context import ExecutionContext
        return ExecutionContext
    raise AttributeError(f"module 'src.core' has no attribute {name!r}")

__all__ = [
    "CircuitBreaker",
    "ExecutionContext",
    "Registry",
    "PolicyRegistry",
    "StrategyRegistry",
    "ToolRegistry",
]
