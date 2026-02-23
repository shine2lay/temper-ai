"""Re-export shim — canonical module is temper_ai.workflow.engines.dynamic_engine.

'Native' was renamed to 'Dynamic' to better capture runtime edge routing,
negotiation, and dynamic parallelism capabilities. Old names are preserved
as aliases for backward compatibility.
"""

# Also export the canonical names
from temper_ai.workflow.engines.dynamic_engine import (  # noqa: F401
    DynamicCompiledWorkflow,
    DynamicExecutionEngine,
)
from temper_ai.workflow.engines.dynamic_engine import (  # noqa: F401
    DynamicCompiledWorkflow as NativeCompiledWorkflow,
)
from temper_ai.workflow.engines.dynamic_engine import (
    DynamicExecutionEngine as NativeExecutionEngine,
)

__all__ = [
    "NativeCompiledWorkflow",
    "NativeExecutionEngine",
    "DynamicCompiledWorkflow",
    "DynamicExecutionEngine",
]
