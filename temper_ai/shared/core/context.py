"""Canonical ExecutionContext for the meta-autonomous framework.

This module provides the single authoritative ExecutionContext class used
across the entire codebase. It consolidates fields from previously separate
definitions in base_agent, exceptions, tracker, and domain_state modules.

Usage:
    >>> from temper_ai.shared.core.context import ExecutionContext
    >>> ctx = ExecutionContext(workflow_id="wf-123", agent_id="agent-1")
    >>> ctx.to_dict()
    {'workflow_id': 'wf-123', 'stage_id': None, 'agent_id': 'agent-1', ...}
"""

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ExecutionContext:
    """Canonical ExecutionContext for agent/stage/workflow tracking.

    This is the single authoritative definition of ExecutionContext used
    across the entire framework. All modules that need an execution context
    should import from ``temper_ai.shared.core.context``.

    Note: This is distinct from ``InfrastructureContext`` in
    ``temper_ai.workflow.domain_state``, which holds non-serializable
    infrastructure components (tracker, tool_registry, etc.).

    Provides environment and tracking information used by agents, error
    handlers, observability trackers, and LLM cache isolation.

    Attributes:
        workflow_id: ID of the workflow execution.
        stage_id: ID of the current pipeline stage.
        agent_id: ID of the executing agent.
        session_id: Session ID for multi-turn conversations and cache isolation.
        user_id: User ID for user-specific context and cache isolation.
        tool_name: Name of the tool being executed (used in error context).
        metadata: Additional contextual key-value pairs.
    """

    workflow_id: Optional[str] = None
    stage_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    tool_name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def execution_mode(self) -> str:
        """Return 'project' if workflow_id is set, else 'desk'."""
        return "project" if self.workflow_id else "desk"

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to a plain dictionary."""
        return {
            "workflow_id": self.workflow_id,
            "stage_id": self.stage_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "tool_name": self.tool_name,
            "metadata": self.metadata,
        }

    def copy(self) -> "ExecutionContext":
        """Return a shallow copy of this context."""
        return ExecutionContext(
            workflow_id=self.workflow_id,
            stage_id=self.stage_id,
            agent_id=self.agent_id,
            session_id=self.session_id,
            user_id=self.user_id,
            tool_name=self.tool_name,
            metadata=dict(self.metadata),
        )

    def __repr__(self) -> str:
        parts = []
        if self.workflow_id:
            parts.append(f"workflow={self.workflow_id}")
        if self.stage_id:
            parts.append(f"stage={self.stage_id}")
        if self.agent_id:
            parts.append(f"agent={self.agent_id}")
        if self.session_id:
            parts.append(f"session={self.session_id}")
        if self.user_id:
            parts.append(f"user={self.user_id}")
        if self.tool_name:
            parts.append(f"tool={self.tool_name}")
        return f"ExecutionContext({', '.join(parts)})"


# Module-level ContextVar shared between tracker and logging.
# The tracker sets this during track_workflow/stage/agent context managers.
# The ExecutionContextFilter reads it to inject fields into log records.
current_execution_context: ContextVar[ExecutionContext] = ContextVar(
    "current_execution_context"
)
