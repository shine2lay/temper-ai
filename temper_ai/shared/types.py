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
    CANCELLED = "cancelled"


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
    graph_loader: Any = None  # GraphLoader — used by dispatch to materialize dispatched node dicts into Node instances. Set by routes/CLI before execute_graph.
    dispatch_limits: Any = None  # DispatchLimits — per-workflow safety caps. Resolved from workflow defaults by routes/CLI; None means use module defaults.
    dispatch_state: Any = None  # DispatchRunState — per-run bookkeeping for cap enforcement. Seeded by executor on first dispatch.

    def __post_init__(self) -> None:
        # The run's tool executor learns the run's cancel flag here: every run
        # builds its context once (API, worker, CLI) and every node runs on a
        # copy of it. A stopped run then starts no tool call and kills a
        # command still running (see ToolExecutor.cancel_event). Only an
        # executor that has the attribute and no flag yet is given one.
        te = self.tool_executor
        if self.cancel_event is not None and te is not None \
                and getattr(te, "cancel_event", False) is None:
            te.cancel_event = self.cancel_event

    def get_llm(self, provider: str | None) -> Any:
        """Get an LLM provider by name, or the default one.

        `provider` is None when neither the agent nor the workflow names
        one, in which case whatever is configured is used — see
        resolve_provider. An explicitly named provider is never silently
        swapped for another: asking for one model and being billed for a
        different one is worse than failing.
        """
        if provider is None:
            provider = self.resolve_provider()
        if provider not in self.llm_providers:
            raise KeyError(
                f"LLM provider '{provider}' not configured. "
                f"Available: {list(self.llm_providers.keys())}. "
                f"Remove the `provider:` line to use whichever is "
                f"configured, or set TEMPER_DEFAULT_PROVIDER."
            )
        return self.llm_providers[provider]

    def resolve_provider(self) -> str:
        """Which provider to use when a workflow does not name one.

        Shipped workflows used to hard-code `provider: openai`, so every
        example failed on an install configured for anything else. They now
        leave it out and land here.

        TEMPER_DEFAULT_PROVIDER wins; otherwise the first configured
        provider in a fixed preference order, so the choice is
        reproducible rather than dependent on dictionary order.
        """
        import os

        available = list(self.llm_providers)
        if not available:
            raise KeyError(
                "No LLM provider is configured. Set one of OPENAI_API_KEY, "
                "ANTHROPIC_API_KEY, GEMINI_API_KEY, OLLAMA_BASE_URL or "
                "VLLM_BASE_URL."
            )

        preferred = os.environ.get("TEMPER_DEFAULT_PROVIDER", "").strip()
        if preferred:
            if preferred not in available:
                raise KeyError(
                    f"TEMPER_DEFAULT_PROVIDER is '{preferred}', which is not "
                    f"configured. Available: {available}"
                )
            return preferred

        for candidate in PROVIDER_PREFERENCE:
            if candidate in available:
                return candidate
        return available[0]


# Hosted providers first: a local endpoint (ollama, vllm) is often
# configured by a stray environment variable while nothing is listening on
# it, which fails as a connection refused rather than a clear message.
PROVIDER_PREFERENCE = (
    "claude",
    "anthropic",
    "openai",
    "gemini",
    "ollama",
    "vllm",
)


@dataclass
class AgentInterface:
    """Declares what an agent expects and produces.

    Used by: agent, stage (for validation).
    """

    inputs: dict[str, str] = field(default_factory=dict)  # name -> type
    outputs: dict[str, str] = field(default_factory=dict)  # name -> type
