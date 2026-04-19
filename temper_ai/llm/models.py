"""LLM data models — responses, results, and caller context."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""

    content: str | None
    model: str
    provider: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None
    finish_reason: str | None = None  # "stop", "tool_calls", "length"
    reasoning: str | None = None  # thinking/reasoning content (if model supports it)
    tool_calls: list[dict[str, Any]] | None = None
    raw_response: dict[str, Any] | None = None


@dataclass
class LLMStreamChunk:
    """A single chunk from a streaming LLM response."""

    content: str
    done: bool
    chunk_type: str = "content"  # "content" or "thinking"
    finish_reason: str | None = None
    model: str | None = None


@dataclass
class LLMRunResult:
    """Result of a complete LLM service run (potentially multi-iteration)."""

    output: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens: int = 0
    cost: float = 0.0
    iterations: int = 0
    error: str | None = None


@dataclass
class CallContext:
    """Caller identity — threaded through every event recorded by the LLM service.

    event_recorder: optional recorder that routes events to both DB and WebSocket.
    When set, all LLM/tool events go through this instead of the module-level record().
    """

    execution_id: str | None = None
    agent_event_id: str | None = None  # parent_id for events from this service
    agent_name: str | None = None
    node_path: str | None = None
    event_recorder: Callable | None = None  # record() compatible callable
    cwd: str | None = None  # Working directory for providers that need it (e.g., Claude Code)
    model: str | None = None  # Per-call model override (e.g., "opus" vs "sonnet")
    # Opaque dict of provider-specific kwargs. Core never inspects these keys —
    # the agent YAML opts in via `provider_config: {key: value}`, and only the
    # matching provider reads them. Lets gitignored providers (e.g. Claude Code
    # in local/) add features without naming them in core.
    provider_config: dict | None = None
