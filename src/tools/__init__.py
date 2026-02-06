"""
Tools module for Meta-Autonomous Framework.

Provides tool registry, executor, and base classes for tool implementation.
"""
from src.tools.base import (
    BaseTool,
    ToolMetadata,
    ToolParameter,
    ToolResult,
)
from src.tools.bash import Bash
from src.tools.executor import (
    ToolExecutor,
)
from src.tools.registry import (  # type: ignore[attr-defined]
    ToolRegistry,
    ToolRegistryError,
)
from src.utils.exceptions import ToolExecutionError

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
