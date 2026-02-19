"""Dict-based parameter objects to reduce high parameter counts in observability functions.

Uses Dict[str, Any] type aliases instead of TypedDict to allow constant-key indexing
(mypy requires string literals for TypedDict keys, which conflicts with extracted constants).
"""
from typing import Any, Dict

# Parameter bundle type aliases — use Dict[str, Any] for constant-key compatibility
LLMCallParams = Dict[str, Any]
ToolCallParams = Dict[str, Any]
WorkflowStartParams = Dict[str, Any]
CollaborationEventParams = Dict[str, Any]
SafetyViolationParams = Dict[str, Any]
DecisionOutcomeParams = Dict[str, Any]
AgentOutputParams = Dict[str, Any]
StreamChunkParams = Dict[str, Any]
StageEndParams = Dict[str, Any]
