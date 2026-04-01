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

    # LLM calls
    LLM_CALL_STARTED = "llm.call.started"
    LLM_CALL_COMPLETED = "llm.call.completed"
    LLM_CALL_FAILED = "llm.call.failed"

    # LLM iterations (loop summary)
    LLM_ITERATION = "llm.iteration"
    LLM_MAX_ITERATIONS = "llm.max_iterations"
    LLM_NO_EXECUTOR = "llm.no_executor"
    LLM_RETRY = "llm.retry"

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
