"""Re-export shim — canonical module is src.workflow.engines.dynamic_runner.

Old name preserved for backward compatibility.
"""
from src.workflow.engines.dynamic_runner import (  # noqa: F401
    ThreadPoolParallelRunner,
    _merge_dicts,
    DEFAULT_MAX_WORKERS,
)

__all__ = [
    "ThreadPoolParallelRunner",
    "_merge_dicts",
    "DEFAULT_MAX_WORKERS",
]
