"""Core protocol definitions for framework-wide interfaces.

This module provides Protocol definitions for execution infrastructure,
enabling type checking and structural subtyping without tight coupling
between components.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import (
    Any,
    Protocol,
    runtime_checkable,
)


@runtime_checkable
class TrackerProtocol(Protocol):
    """Minimal interface for an execution tracker."""

    @contextmanager
    def track_stage(
        self,
        stage_name: str,
        stage_config: dict[str, Any],
        workflow_id: str,
        input_data: dict[str, Any],
    ) -> Iterator[str]:
        """Track stage execution."""
        ...

    @contextmanager
    def track_agent(
        self,
        agent_name: str,
        agent_config: dict[str, Any],
        stage_id: str,
        input_data: dict[str, Any],
    ) -> Iterator[str]:
        """Track agent execution."""
        ...

    def set_agent_output(
        self,
        agent_id: str,
        output_data: dict[str, Any],
        reasoning: str | None = None,
        total_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
        num_llm_calls: int = 0,
        num_tool_calls: int = 0,
    ) -> None:
        """Set agent output."""
        ...

    def track_collaboration_event(
        self,
        event_type: str,
        stage_name: str,
        agents: list[str],
        decision: str | None,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Track collaboration event."""
        ...


@runtime_checkable
class DomainToolRegistryProtocol(Protocol):
    """Minimal interface for a tool registry in domain state context."""

    def get(self, name: str, version: str | None = None) -> Any:
        """Get tool by name and optional version."""
        ...


@runtime_checkable
class ConfigLoaderProtocol(Protocol):
    """Minimal interface for a configuration loader."""

    def load_agent(self, agent_name: str) -> dict[str, Any]:
        """Load agent configuration by name."""
        ...

    def load_stage(self, stage_name: str) -> dict[str, Any]:
        """Load stage configuration by name."""
        ...


@runtime_checkable
class VisualizerProtocol(Protocol):
    """Minimal interface for a workflow visualizer."""

    def update(self, state: dict[str, Any]) -> None:
        """Update visualizer with workflow state."""
        ...
