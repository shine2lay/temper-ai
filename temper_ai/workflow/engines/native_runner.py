"""Re-export shim — canonical module is temper_ai.workflow.engines.dynamic_runner.

Old name preserved for backward compatibility.
"""

from temper_ai.workflow.engines.dynamic_runner import (  # noqa: F401
    DEFAULT_MAX_WORKERS,
    ThreadPoolParallelRunner,
    _merge_dicts,
)

__all__ = [
    "ThreadPoolParallelRunner",
    "_merge_dicts",
    "DEFAULT_MAX_WORKERS",
]
