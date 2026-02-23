"""Dict-based parameter objects to reduce high parameter counts in observability functions.

Uses Dict[str, Any] type aliases instead of TypedDict to allow constant-key indexing
(mypy requires string literals for TypedDict keys, which conflicts with extracted constants).
"""

from typing import Any

# Parameter bundle type aliases — use Dict[str, Any] for constant-key compatibility
LLMCallParams = dict[str, Any]
ToolCallParams = dict[str, Any]
WorkflowStartParams = dict[str, Any]
CollaborationEventParams = dict[str, Any]
SafetyViolationParams = dict[str, Any]
DecisionOutcomeParams = dict[str, Any]
AgentOutputParams = dict[str, Any]
StreamChunkParams = dict[str, Any]
StageEndParams = dict[str, Any]
