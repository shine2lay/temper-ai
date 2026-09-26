"""Event type definitions for the observability system.

Callers use these enums for autocomplete and typo prevention.
The database stores them as plain strings.
"""

from enum import StrEnum


class EventType(StrEnum):
    """Event types recorded during workflow execution."""

    # Workflow lifecycle
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"

    # Stage lifecycle
    STAGE_STARTED = "stage.started"
    STAGE_COMPLETED = "stage.completed"
    STAGE_FAILED = "stage.failed"

    # Agent lifecycle
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    # An agent's almost-JSON answer: parsed after escaping stray quotes
    # (repaired), or after one more turn asking for corrected JSON (retry;
    # status failed when that did not parse either). data.parse_error is the
    # original json error, so how often answers need saving can be counted.
    AGENT_OUTPUT_REPAIRED = "agent.output.repaired"
    AGENT_OUTPUT_RETRY = "agent.output.retry"

    # LLM calls
    LLM_CALL_STARTED = "llm.call.started"
    LLM_CALL_COMPLETED = "llm.call.completed"
    LLM_CALL_FAILED = "llm.call.failed"

    # LLM iterations (loop summary)
    LLM_ITERATION = "llm.iteration"
    LLM_MAX_ITERATIONS = "llm.max_iterations"
    LLM_NO_EXECUTOR = "llm.no_executor"
    LLM_RETRY = "llm.retry"
    # A model out of capacity handed the call to the next entry of the agent's
    # fallback list (temper_ai.llm.fallback); status failed when none was left.
    LLM_FALLBACK = "llm.fallback"

    # Tool calls (from LLM service layer)
    TOOL_CALL_STARTED = "tool.call.started"
    TOOL_CALL_COMPLETED = "tool.call.completed"
    TOOL_CALL_FAILED = "tool.call.failed"

    # Tool executor events
    TOOL_BLOCKED = "tool.blocked"
    TOOL_TIMEOUT = "tool.timeout"
    TOOL_UNKNOWN = "tool.unknown"

    # Safety
    SAFETY_POLICY_TRIGGERED = "safety.policy.triggered"

    # Memory
    MEMORY_RECALLED = "memory.recalled"
    MEMORY_STORED = "memory.stored"

    # Streaming
    LLM_STREAM_CHUNK = "llm.stream.chunk"

    # Runtime dispatch — dynamic DAG mutation (see stage/dispatch.py)
    DISPATCH_APPLIED = "dispatch.applied"
    DISPATCH_CAP_EXCEEDED = "dispatch.cap_exceeded"
