"""
Tools module for Meta-Autonomous Framework.

Provides tool registry, executor, and base classes for tool implementation.
"""
from temper_ai.tools.base import (
    BaseTool,
    ToolMetadata,
    ToolParameter,
    ToolResult,
)
from temper_ai.tools.bash import Bash
from temper_ai.tools.executor import (
    ToolExecutor,
)
from temper_ai.tools.registry import (
    ToolRegistry,
    ToolRegistryError,
)
from temper_ai.shared.utils.exceptions import ToolExecutionError

__all__ = [
    # Base classes
    "BaseTool",
    "ToolParameter",
    "ToolMetadata",
    "ToolResult",
    # Registry
    "ToolRegistry",
    "ToolRegistryError",
    # Executor
    "ToolExecutor",
    "ToolExecutionError",
    # Tools
    "Bash",
]
