"""Base tool interface — all tools inherit from this.

Keeps it simple: name, description, parameters schema, execute().
Extensible for future additions (Pydantic validation, config models, etc.)
without breaking existing tools.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """Result returned by every tool execution."""

    success: bool
    result: Any
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """Abstract base for all tools.

    Subclasses must set class attributes and implement execute().

    Attributes:
        name: Tool name as the LLM sees it (e.g., "Bash", "Write").
        description: What the tool does — shown to the LLM.
        parameters: JSON Schema dict describing the tool's parameters.
        modifies_state: Whether this tool changes external state. Used by
            future safety features (rollback snapshots, caching decisions).
        local_paths: Whether this tool's path-like parameters name files on
            THIS machine. The executor sandboxes path/file_path/directory/
            filename/output_path against the run's workspace_root, which is
            right for a tool that opens files here and wrong for a tool whose
            "path" means something elsewhere: an MCP tool's arguments are sent
            to a separate server process, where `path` may be a path inside a
            GitHub repo, or a path under that server's own configured roots in
            another container. Such a check cannot be correct across a process
            boundary — it resolves relative to *this* process's cwd — so those
            tools set this False and their path safety belongs to the server
            and its launch configuration. Safety policies still apply either way.
    """

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}
    modifies_state: bool = True
    local_paths: bool = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @abstractmethod
    def execute(self, **params: Any) -> ToolResult:
        """Execute the tool with the given parameters.

        Returns a ToolResult with success/failure, result data, and optional error.
        """

    def to_llm_schema(self) -> dict[str, Any]:
        """Generate OpenAI function calling schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
