"""
Tools module for Temper AI.

Provides tool registry, executor, and base classes for tool implementation.
"""

from temper_ai.shared.utils.exceptions import ToolExecutionError
from temper_ai.tools.base import (
    BaseTool,
    ToolMetadata,
    ToolResult,
)
from temper_ai.tools.bash import Bash
from temper_ai.tools.calculator import Calculator
from temper_ai.tools.executor import (
    ToolExecutor,
)
from temper_ai.tools.file_writer import FileWriter
from temper_ai.tools.git_tool import GitTool
from temper_ai.tools.http_client import HTTPClientTool
from temper_ai.tools.json_parser import JSONParserTool
from temper_ai.tools.registry import (
    ToolRegistry,
    ToolRegistryError,
)
from temper_ai.tools.web_scraper import WebScraper
from temper_ai.tools.web_search import WebSearch

# Static tool registry: name → class.
# Add new tools here when implementing them.
TOOL_CLASSES: dict[str, type[BaseTool]] = {
    "Bash": Bash,
    "Calculator": Calculator,
    "FileWriter": FileWriter,
    "Git": GitTool,
    "HTTPClient": HTTPClientTool,
    "JSONParser": JSONParserTool,
    "WebScraper": WebScraper,
    "WebSearch": WebSearch,
}

__all__ = [
    # Base classes
    "BaseTool",
    "ToolMetadata",
    "ToolResult",
    # Registry
    "ToolRegistry",
    "ToolRegistryError",
    "TOOL_CLASSES",
    # Executor
    "ToolExecutor",
    "ToolExecutionError",
    # Tools
    "Bash",
    "Calculator",
    "FileWriter",
    "GitTool",
    "HTTPClientTool",
    "JSONParserTool",
    "WebScraper",
    "WebSearch",
]
