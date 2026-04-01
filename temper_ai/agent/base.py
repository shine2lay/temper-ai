"""Base agent interface — all agent types inherit from this.

Minimal base class. No LLM, no tools, no memory in base.
Constructor takes only config. All infrastructure comes from
ExecutionContext at run time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from temper_ai.shared.types import AgentInterface, AgentResult, ExecutionContext


class AgentABC(ABC):
    """Minimal base class for all agents."""

    def __init__(self, config: dict):
        self.config = config
        self.name = config["name"]
        self.description = config.get("description", "")

    @abstractmethod
    def run(self, input_data: dict, context: ExecutionContext) -> AgentResult:
        """Execute the agent's task. Must be implemented by subclasses."""

    def validate_config(self) -> list[str]:
        """Return list of config validation errors. Empty = valid."""
        errors = []
        if not self.config.get("name"):
            errors.append("Agent config must have 'name'")
        return errors

    def get_interface(self) -> AgentInterface:
        """Return declared inputs/outputs. Override for typed agents."""
        return AgentInterface(inputs={}, outputs={})
