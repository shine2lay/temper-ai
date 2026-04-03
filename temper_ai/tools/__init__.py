"""Tool system — built-in tools, executor, and loader."""

from temper_ai.tools.base import BaseTool, ToolResult
from temper_ai.tools.bash import Bash
from temper_ai.tools.calculator import Calculator
from temper_ai.tools.delegate import Delegate
from temper_ai.tools.executor import ToolExecutor
from temper_ai.tools.file_writer import FileWriter
from temper_ai.tools.git import Git
from temper_ai.tools.http import Http
from temper_ai.tools.loader import load_tools

# Static registry of all available tool classes.
# Adding a new tool: implement BaseTool, add it here.
TOOL_CLASSES: dict[str, type[BaseTool]] = {
    "Bash": Bash,
    "Calculator": Calculator,
    "Delegate": Delegate,
    "FileWriter": FileWriter,
    "git": Git,
    "http": Http,
}

def register_tool(name: str, cls: type[BaseTool]) -> None:
    """Register a custom tool class.

    Args:
        name: Tool name agents will reference (e.g., "WebSearch").
        cls: Tool class (must subclass BaseTool).
    """
    TOOL_CLASSES[name] = cls


__all__ = [
    "BaseTool",
    "Bash",
    "Calculator",
    "FileWriter",
    "Git",
    "Http",
    "TOOL_CLASSES",
    "ToolExecutor",
    "ToolResult",
    "load_tools",
    "register_tool",
]
