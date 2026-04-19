"""Shared types that cross module boundaries.

Rule: if a type is only used within one module, it stays in that module.
Only types referenced by 2+ modules belong here.

These are pure data containers — no business logic methods.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    """Used by: agent, stage, api, observability."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TokenUsage:
    """Used by: agent, stage, llm, api."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class AgentResult:
    """Result from a single agent execution.

    Used by: agent, stage, api.
    """

    status: Status
    output: str
    structured_output: dict | None = None
    tokens: TokenUsage = field(default_factory=TokenUsage)
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    memories_formed: list[str] = field(default_factory=list)
    error: str | None = None
    llm_calls: int = 0
    tool_calls: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class NodeResult:
    """Result from any node (agent or stage). Uniform interface.

    Used by: stage executor, api, frontend.

    For agent nodes: agent_results has one entry.
    For stage nodes: agent_results has all agents that ran within.
    node_results has child node results (for nested stages).
    """

    status: Status
    output: str = ""
    structured_output: dict | None = None
    agent_results: list[AgentResult] = field(default_factory=list)
    node_results: dict[str, NodeResult] = field(default_factory=dict)
    cost_usd: float = 0.0
    total_tokens: int = 0
    duration_seconds: float = 0.0
    error: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ExecutionContext:
    """Execution metadata + infrastructure for agents.

    Agents pull what they need at run time. All infrastructure is set up
    by the runtime before agent execution begins.

    Used by: agent, stage executor.

    Agent identity (name, model, system_prompt) comes from agent config.
    Task assignment (task_template) can be overridden at the node level.
    """

    # Execution metadata
    run_id: str
    workflow_name: str
    node_path: str  # e.g., "review" or "review.security_check" (for nested)
    agent_name: str  # current agent (set per agent execution)

    # Infrastructure (agents pull these at run time)
    event_recorder: Any  # ObservabilityRecorder
    tool_executor: Any  # ToolExecutor
    memory_service: Any = None  # MemoryService (None if memory not configured)
    llm_providers: dict[str, Any] = field(default_factory=dict)  # provider_name -> BaseLLM
    stream_callback: Callable | None = None
    workspace_path: str | None = None
    parent_event_id: str | None = None  # Node event ID for agent event hierarchy
    cancel_event: Any = None  # threading.Event — set to cancel the workflow
    checkpoint_service: Any = None  # CheckpointService — persists execution state for resume
    gate_registry: Any = None  # dict[str, threading.Event] — gates waiting for approval
    graph_event_id: str | None = None  # Top-level workflow/stage event ID (for Delegate tool DAG parenting)
    skip_policies: list[str] | None = None  # Policy types to skip for the current node
    run_state: dict[str, Any] | None = None  # Live node_outputs dict (name -> NodeResult). Set by executor for introspection tools (QueryRunState, future dispatch).

    def get_llm(self, provider: str) -> Any:
        """Get LLM provider by name. Raises KeyError if not found."""
        if provider not in self.llm_providers:
            raise KeyError(
                f"LLM provider '{provider}' not configured. "
                f"Available: {list(self.llm_providers.keys())}"
            )
        return self.llm_providers[provider]


@dataclass
class AgentInterface:
    """Declares what an agent expects and produces.

    Used by: agent, stage (for validation).
    """

    inputs: dict[str, str] = field(default_factory=dict)  # name -> type
    outputs: dict[str, str] = field(default_factory=dict)  # name -> type
