"""Tool system — built-in tools, executor, and loader."""

from temper_ai.tools.add_node import AddNode
from temper_ai.tools.base import BaseTool, ToolResult
from temper_ai.tools.bash import Bash
from temper_ai.tools.calculator import Calculator
from temper_ai.tools.delegate import Delegate
from temper_ai.tools.edit import Edit
from temper_ai.tools.executor import ToolExecutor
from temper_ai.tools.git import Git
from temper_ai.tools.github_pr import OpenPullRequest
from temper_ai.tools.glob import Glob
from temper_ai.tools.grep import Grep
from temper_ai.tools.http import Http
from temper_ai.tools.linear_state import LinearMoveIssue
from temper_ai.tools.loader import load_tools
from temper_ai.tools.query_run_state import QueryRunState
from temper_ai.tools.read import Read
from temper_ai.tools.remove_node import RemoveNode
from temper_ai.tools.web_fetch import WebFetch
from temper_ai.tools.web_search import WebSearch
from temper_ai.tools.write import Write

# Static registry of all available tool classes.
# Adding a new tool: implement BaseTool, add it here.
#
# The file tools (Read/Write/Edit/Grep/Glob) carry pi's behaviours: bounded
# output with continuation hints, several edits per call, structured search.
# They replaced FileWriter/FileEdit/FileAppend, which had no reader at all —
# agents were shelling out to `cat`, which returns whole files.
TOOL_CLASSES: dict[str, type[BaseTool]] = {
    "AddNode": AddNode,
    "Bash": Bash,
    "Calculator": Calculator,
    "Delegate": Delegate,
    "Edit": Edit,
    "git": Git,
    "Glob": Glob,
    "Grep": Grep,
    "http": Http,
    "LinearMoveIssue": LinearMoveIssue,
    "OpenPullRequest": OpenPullRequest,
    "QueryRunState": QueryRunState,
    "Read": Read,
    "RemoveNode": RemoveNode,
    "WebFetch": WebFetch,
    "WebSearch": WebSearch,
    "Write": Write,
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
    "Edit",
    "Git",
    "Glob",
    "Grep",
    "Http",
    "Read",
    "TOOL_CLASSES",
    "ToolExecutor",
    "ToolResult",
    "WebFetch",
    "Write",
    "load_tools",
    "register_tool",
]
