"""
Circuit breaker pattern for LLM provider resilience.

This module re-exports the unified circuit breaker from src.core.circuit_breaker.
All classes and functionality are preserved — see src/core/circuit_breaker.py for
the canonical implementation.
"""
from src.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerMetrics,
    CircuitState,
    StateStorage,
)

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerError",
    "CircuitBreakerMetrics",
    "CircuitState",
    "StateStorage",
]
