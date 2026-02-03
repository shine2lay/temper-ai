"""
Tools module for Meta-Autonomous Framework.

Provides tool registry, executor, and base classes for tool implementation.
"""
from src.tools.base import (
    BaseTool,
    ToolParameter,
    ToolMetadata,
    ToolResult,
)
from src.tools.registry import (  # type: ignore[attr-defined]
    ToolRegistry,
    ToolRegistryError,
)
from src.tools.executor import (
    ToolExecutor,
    ToolExecutionError,
)
from src.tools.bash import Bash

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
