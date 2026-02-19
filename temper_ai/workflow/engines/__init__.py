"""Workflow execution engine package.

Provides execution engines:
- DynamicExecutionEngine: Python-native with negotiation and dynamic routing
- LangGraphExecutionEngine: LangGraph-based StateGraph execution
- WorkflowExecutor: DAG-aware stage execution loop
- ThreadPoolParallelRunner: ParallelRunner using concurrent.futures

Legacy aliases:
- NativeExecutionEngine → DynamicExecutionEngine
- NativeCompiledWorkflow → DynamicCompiledWorkflow
"""

from temper_ai.workflow.engines.dynamic_engine import (  # noqa: F401
    DynamicCompiledWorkflow,
    DynamicExecutionEngine,
)
from temper_ai.workflow.engines.dynamic_runner import ThreadPoolParallelRunner  # noqa: F401
from temper_ai.workflow.engines.langgraph_compiler import LangGraphCompiler  # noqa: F401
from temper_ai.workflow.engines.langgraph_engine import (  # noqa: F401
    LangGraphCompiledWorkflow,
    LangGraphExecutionEngine,
)
from temper_ai.workflow.engines.workflow_executor import WorkflowExecutor  # noqa: F401

# Legacy aliases
NativeCompiledWorkflow = DynamicCompiledWorkflow  # noqa: F401
NativeExecutionEngine = DynamicExecutionEngine  # noqa: F401
