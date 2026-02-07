"""
Circuit breaker pattern for LLM provider resilience.

.. deprecated::
    This module re-exports the unified circuit breaker from
    ``src.core.circuit_breaker``.  Import directly from
    ``src.core.circuit_breaker`` instead.
"""
import importlib
import warnings

_SHIM_EXPORTS = {
    "CircuitBreaker": "src.core.circuit_breaker",
    "CircuitBreakerConfig": "src.core.circuit_breaker",
    "CircuitBreakerError": "src.core.circuit_breaker",
    "CircuitBreakerMetrics": "src.core.circuit_breaker",
    "CircuitState": "src.core.circuit_breaker",
    "StateStorage": "src.core.circuit_breaker",
}

__all__ = list(_SHIM_EXPORTS.keys())


def __getattr__(name: str):
    if name in _SHIM_EXPORTS:
        warnings.warn(
            f"Importing {name} from src.llm.circuit_breaker is deprecated. "
            f"Import from src.core.circuit_breaker instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        mod = importlib.import_module(_SHIM_EXPORTS[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
