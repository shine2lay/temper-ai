"""Observability backend implementations."""
from typing import Any

from .prometheus_backend import PrometheusObservabilityBackend
from .s3_backend import S3ObservabilityBackend
from .sql_backend import SQLObservabilityBackend

# Lazy imports for optional backends
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "CompositeBackend": (".composite_backend", "CompositeBackend"),
    "OTelBackend": (".otel_backend", "OTelBackend"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        import importlib

        module_path, attr = _LAZY_IMPORTS[name]
        mod = importlib.import_module(module_path, __name__)
        val = getattr(mod, attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "SQLObservabilityBackend",
    "PrometheusObservabilityBackend",
    "S3ObservabilityBackend",
    "CompositeBackend",
    "OTelBackend",
]
