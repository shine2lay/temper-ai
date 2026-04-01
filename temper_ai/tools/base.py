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
        name: Tool name as the LLM sees it (e.g., "Bash", "FileWriter").
        description: What the tool does — shown to the LLM.
        parameters: JSON Schema dict describing the tool's parameters.
        modifies_state: Whether this tool changes external state. Used by
            future safety features (rollback snapshots, caching decisions).
    """

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}
    modifies_state: bool = True

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
