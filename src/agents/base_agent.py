"""Base agent interface and data structures.

Defines the abstract BaseAgent class that all agent implementations must inherit from,
along with AgentResponse and ExecutionContext data classes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypedDict

if TYPE_CHECKING:
    from src.schemas import AgentConfig
from src.agents.constants import (
    BASE_CONFIDENCE,
    MIN_OUTPUT_LENGTH,
    MIN_REASONING_LENGTH,
    REASONING_BONUS,
    TOOL_FAILURE_MAJOR_PENALTY,
    TOOL_FAILURE_MINOR_PENALTY,
)
from src.constants.probabilities import CONFIDENCE_LOW, PROB_MEDIUM
from src.core.context import ExecutionContext  # canonical definition; re-exported here


def _tool_failure_penalty(tool_calls: List[Any]) -> float:
    """Calculate penalty for tool call failures.

    Returns a penalty value (0.0 if no penalty) based on the tool success rate.
    """
    if not tool_calls:
        return 0.0
    successful_calls = sum(1 for tc in tool_calls if tc.get('success', False))
    total_calls = len(tool_calls)
    if total_calls == 0:
        return 0.0
    tool_success_rate = successful_calls / total_calls
    if tool_success_rate < PROB_MEDIUM:
        return TOOL_FAILURE_MAJOR_PENALTY
    if tool_success_rate < BASE_CONFIDENCE:
        return TOOL_FAILURE_MINOR_PENALTY
    return 0.0


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
        """Calculate confidence score based on response quality.

        Factors considered:
        - Error presence: Major penalty
        - Output length: Very short outputs get penalty
        - Reasoning presence: Bonus for reasoning
        - Tool call success: Bonus if tools were used successfully

        Returns:
            Confidence score between 0.0 and 1.0
        """
        if self.error:
            return CONFIDENCE_LOW

        confidence = BASE_CONFIDENCE

        if len(self.output.strip()) < MIN_OUTPUT_LENGTH:
            confidence -= CONFIDENCE_LOW

        if self.reasoning and len(self.reasoning.strip()) > MIN_REASONING_LENGTH:
            confidence = min(BASE_CONFIDENCE, confidence + REASONING_BONUS)

        confidence -= _tool_failure_penalty(self.tool_calls)

        return max(0.0, min(BASE_CONFIDENCE, confidence))


class BaseAgent(ABC):
    """Abstract base class for all agents.

    All agent implementations must inherit from this class and implement
    the execute() method. This enables the "radical modularity" vision by
    allowing multiple agent types (standard, debate, human, custom).

    The agent should:
    1. Initialize from AgentConfig
    2. Create necessary dependencies (LLM provider, tools, prompt engine)
    3. Execute with input and return structured AgentResponse
    """

    def __init__(self, config: AgentConfig):
        """Initialize agent with configuration.

        Args:
            config: Agent configuration schema
        """
        self.config = config
        self.name = config.agent.name
        self.description = config.agent.description
        self.version = config.agent.version

    @abstractmethod
    def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None
    ) -> AgentResponse:
        """Execute agent with given input.

        This is the main entry point for agent execution. Implementations should:
        1. Render prompt with input data
        2. Call LLM and handle tool calls
        3. Execute tools as needed
        4. Return structured response

        Args:
            input_data: Input data for the agent (e.g., {"query": "...", "data": {...}})
            context: Optional execution context for tracking and environment

        Returns:
            AgentResponse with output, reasoning, tool calls, and metrics

        Raises:
            ValueError: If input_data is invalid
            RuntimeError: If execution fails
        """
        pass

    async def aexecute(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None
    ) -> AgentResponse:
        """Async execution (default wraps sync execute).

        Override for native async implementations.

        Args:
            input_data: Input data for the agent (e.g., {"query": "...", "data": {...}})
            context: Optional execution context for tracking and environment

        Returns:
            AgentResponse with output, reasoning, tool calls, and metrics

        Raises:
            ValueError: If input_data is invalid
            RuntimeError: If execution fails
        """
        import asyncio
        return await asyncio.to_thread(self.execute, input_data, context)

    @abstractmethod
    def get_capabilities(self) -> Dict[str, Any]:
        """Get agent capabilities and metadata.

        Returns a dict describing what this agent can do, what tools it has,
        what models it uses, etc. Useful for agent discovery and selection.

        Returns:
            Dict with capability information
        """
        pass

    def validate_config(self) -> bool:
        """Validate agent configuration.

        Checks that the agent config is valid and all required dependencies
        are available (e.g., LLM provider is accessible, tools exist).

        Returns:
            True if configuration is valid

        Raises:
            ValueError: If configuration is invalid
        """
        # Basic validation - subclasses can override for more checks
        if not self.config.agent.name:
            raise ValueError("Agent name is required")
        if not self.config.agent.inference:
            raise ValueError("Inference configuration is required")
        if not self.config.agent.prompt:
            raise ValueError("Prompt configuration is required")
        return True
