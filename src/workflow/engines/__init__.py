"""Native execution engine package.

Provides a Python-native workflow execution engine as an alternative to LangGraph.
The native engine supports all current features (sequential, parallel, conditional,
loop) plus input negotiation between stages and agents.

Components:
- NativeExecutionEngine: ExecutionEngine implementation
- NativeCompiledWorkflow: CompiledWorkflow wrapper
- WorkflowExecutor: DAG-aware stage execution loop
- ThreadPoolParallelRunner: ParallelRunner using concurrent.futures
"""

from src.workflow.engines.native_engine import (  # noqa: F401
    NativeCompiledWorkflow,
    NativeExecutionEngine,
)
from src.workflow.engines.native_runner import ThreadPoolParallelRunner  # noqa: F401
from src.workflow.engines.workflow_executor import WorkflowExecutor  # noqa: F401
