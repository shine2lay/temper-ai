"""Re-export shim — canonical module is src.workflow.engines.dynamic_engine.

'Native' was renamed to 'Dynamic' to better capture runtime edge routing,
negotiation, and dynamic parallelism capabilities. Old names are preserved
as aliases for backward compatibility.
"""
from src.workflow.engines.dynamic_engine import (  # noqa: F401
    DynamicCompiledWorkflow as NativeCompiledWorkflow,
    DynamicExecutionEngine as NativeExecutionEngine,
)

# Also export the canonical names
from src.workflow.engines.dynamic_engine import (  # noqa: F401
    DynamicCompiledWorkflow,
    DynamicExecutionEngine,
)

__all__ = [
    "NativeCompiledWorkflow",
    "NativeExecutionEngine",
    "DynamicCompiledWorkflow",
    "DynamicExecutionEngine",
]
