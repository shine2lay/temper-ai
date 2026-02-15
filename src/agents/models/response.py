"""Agent response data structures.

Defines AgentResponse (returned by agent execution) and ToolCallRecord
(structured record of a single tool invocation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypedDict

from src.agents.utils.constants import (
    BASE_CONFIDENCE,
    MIN_OUTPUT_LENGTH,
    MIN_REASONING_LENGTH,
    REASONING_BONUS,
    TOOL_FAILURE_MAJOR_PENALTY,
    TOOL_FAILURE_MINOR_PENALTY,
)
from src.constants.probabilities import CONFIDENCE_LOW, PROB_MEDIUM


class ToolCallRecord(TypedDict):
    """Structured record of a single tool call made during agent execution.

    Core fields (tool_name, arguments, result) are required.
    Optional fields: success, duration_seconds.

    Attributes:
        tool_name: Name of the tool that was called
        arguments: Arguments passed to the tool
        result: String result returned by the tool
        success: Whether the tool call succeeded
        duration_seconds: Time taken for the tool call
    """
    tool_name: str
    arguments: Dict[str, Any]
    result: str
    success: bool
    duration_seconds: float


@dataclass
class AgentResponse:
    """Response from agent execution.

    Attributes:
        output: Final text output from the agent
        reasoning: Extracted reasoning/thought process
        tool_calls: List of tool calls made during execution
        metadata: Additional execution metadata
        tokens: Total tokens used (prompt + completion)
        estimated_cost_usd: Estimated cost in USD
        latency_seconds: Execution time in seconds
        error: Error message if execution failed
        confidence: Confidence score (0.0 to 1.0), auto-calculated if not provided
    """
    output: str
    reasoning: Optional[str] = None
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_seconds: float = 0.0
    error: Optional[str] = None
    confidence: Optional[float] = None

    def __post_init__(self) -> None:
        """Calculate confidence if not explicitly provided."""
        if self.confidence is None:
            self.confidence = self._calculate_confidence()

    def _calculate_confidence(self) -> float:
        """Calculate confidence score based on response quality."""
        if self.error:
            return CONFIDENCE_LOW

        confidence = BASE_CONFIDENCE

        if len(self.output.strip()) < MIN_OUTPUT_LENGTH:
            confidence -= CONFIDENCE_LOW

        if self.reasoning and len(self.reasoning.strip()) > MIN_REASONING_LENGTH:
            confidence = min(BASE_CONFIDENCE, confidence + REASONING_BONUS)

        confidence -= self._tool_failure_penalty(self.tool_calls)

        return max(0.0, min(BASE_CONFIDENCE, confidence))

    @staticmethod
    def _tool_failure_penalty(tool_calls: List[Any]) -> float:
        """Calculate penalty for tool call failures."""
        if not tool_calls:
            return 0.0
        successful = sum(1 for tc in tool_calls if tc.get('success', False))
        total = len(tool_calls)
        if total == 0:
            return 0.0
        rate = successful / total
        if rate < PROB_MEDIUM:
            return TOOL_FAILURE_MAJOR_PENALTY
        if rate < BASE_CONFIDENCE:
            return TOOL_FAILURE_MINOR_PENALTY
        return 0.0
