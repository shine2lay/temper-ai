"""
Timeout testing helpers for integration tests.

Provides tools, agents, and utilities for testing timeout propagation
across system layers (Tool → Agent → Stage → Workflow).
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from temper_ai.agent.base_agent import AgentResponse
from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)
from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult


@dataclass
class ResourceTracker:
    """Track resource allocations/releases for leak detection."""

    tool_files_opened: int = 0
    tool_files_closed: int = 0
    agent_connections_opened: int = 0
    agent_connections_closed: int = 0
    stage_executors_created: int = 0
    stage_executors_shutdown: int = 0
    workflow_state_allocated: int = 0
    workflow_state_freed: int = 0

    def reset(self):
        """Reset all counters."""
        self.tool_files_opened = 0
        self.tool_files_closed = 0
        self.agent_connections_opened = 0
        self.agent_connections_closed = 0
        self.stage_executors_created = 0
        self.stage_executors_shutdown = 0
        self.workflow_state_allocated = 0
        self.workflow_state_freed = 0

    def validate_no_leaks(self):
        """Validate no resource leaks occurred."""
        errors = []

        if self.tool_files_opened != self.tool_files_closed:
            errors.append(
                f"FILE LEAK! Opened {self.tool_files_opened}, "
                f"closed {self.tool_files_closed}"
            )

        if self.agent_connections_opened != self.agent_connections_closed:
            errors.append(
                f"CONNECTION LEAK! Opened {self.agent_connections_opened}, "
                f"closed {self.agent_connections_closed}"
            )

        if self.stage_executors_created != self.stage_executors_shutdown:
            errors.append(
                f"EXECUTOR LEAK! Created {self.stage_executors_created}, "
                f"shutdown {self.stage_executors_shutdown}"
            )

        if self.workflow_state_allocated != self.workflow_state_freed:
            errors.append(
                f"STATE LEAK! Allocated {self.workflow_state_allocated}, "
                f"freed {self.workflow_state_freed}"
            )

        if errors:
            raise AssertionError("Resource leaks detected:\n" + "\n".join(errors))


class SlowTool(BaseTool):
    """Tool that sleeps for a configurable duration (for timeout testing)."""

    def __init__(self, sleep_seconds: float = 60.0, name: str = "SlowTool"):
        self.sleep_seconds = sleep_seconds
        self._name = name
        self._description = f"A tool that sleeps for {sleep_seconds}s"
        # Initialize parent without calling it (to avoid metadata validation issues)
        self.config = {}
        self._metadata = self.get_metadata()

    def get_metadata(self) -> ToolMetadata:
        """Return tool metadata."""
        return ToolMetadata(
            name=self._name,
            description=self._description,
            version="1.0",
            category="testing",
            requires_network=False,
            requires_credentials=False,
            modifies_state=False,
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        """Return JSON schema for tool parameters."""
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> ToolResult:
        """Execute by sleeping for configured duration."""
        await asyncio.sleep(self.sleep_seconds)
        return ToolResult(
            success=True,
            result=f"Slept for {self.sleep_seconds}s",
            metadata={"sleep_duration": self.sleep_seconds},
        )


class ResourceTrackingTool(BaseTool):
    """Tool that tracks resource allocation/release for leak detection."""

    def __init__(
        self,
        tracker: ResourceTracker,
        sleep_seconds: float = 60.0,
        name: str = "ResourceTrackingTool",
    ):
        self.tracker = tracker
        self.sleep_seconds = sleep_seconds
        self._name = name
        self._description = "A tool that tracks resource allocation"
        # Initialize parent without calling it
        self.config = {}
        self._metadata = self.get_metadata()

    def get_metadata(self) -> ToolMetadata:
        """Return tool metadata."""
        return ToolMetadata(
            name=self._name,
            description=self._description,
            version="1.0",
            category="testing",
            requires_network=False,
            requires_credentials=False,
            modifies_state=False,
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        """Return JSON schema for tool parameters."""
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> ToolResult:
        """Execute with resource tracking."""
        # Acquire resource
        self.tracker.tool_files_opened += 1
        try:
            await asyncio.sleep(self.sleep_seconds)
            return ToolResult(success=True, result="done")
        finally:
            # Release resource
            self.tracker.tool_files_closed += 1


class TimeoutTrackingAgent:
    """Agent that tracks cleanup times for concurrency testing."""

    def __init__(self, agent_id: str, cleanup_times: list, sleep_seconds: float = 60.0):
        self.agent_id = agent_id
        self.cleanup_times = cleanup_times
        self.sleep_seconds = sleep_seconds
        self.config = type(
            "obj",
            (object,),
            {"agent": type("obj", (object,), {"timeout_seconds": None})()},
        )()

    async def execute(self, input_data: dict[str, Any]) -> AgentResponse:
        """Execute with cleanup tracking."""
        try:
            await asyncio.sleep(self.sleep_seconds)
            return AgentResponse(output="done", metadata={})
        finally:
            # Track cleanup time
            self.cleanup_times.append(
                {"agent_id": self.agent_id, "cleanup_time": time.time()}
            )


class ResourceTrackingAgent:
    """Agent that tracks connection open/close for leak detection."""

    def __init__(
        self,
        tracker: ResourceTracker,
        tool: BaseTool | None = None,
        sleep_seconds: float = 60.0,
    ):
        self.tracker = tracker
        self.tool = tool
        self.sleep_seconds = sleep_seconds
        self.config = type(
            "obj",
            (object,),
            {"agent": type("obj", (object,), {"timeout_seconds": None})()},
        )()

    async def execute(self, input_data: dict[str, Any]) -> AgentResponse:
        """Execute with connection tracking."""
        # Open connection
        self.tracker.agent_connections_opened += 1
        try:
            if self.tool:
                # Call tool (may timeout)
                result = await self.tool.execute()
                return AgentResponse(output=result.result, metadata=result.metadata)
            else:
                await asyncio.sleep(self.sleep_seconds)
                return AgentResponse(output="done", metadata={})
        finally:
            # Close connection
            self.tracker.agent_connections_closed += 1


def create_agent_config(
    name: str = "test_agent",
    timeout_seconds: int | None = None,
    tools: list | None = None,
) -> AgentConfig:
    """
    Create test agent configuration with optional timeout.

    Args:
        name: Agent name
        timeout_seconds: Agent execution timeout (None = no timeout)
        tools: List of tool names to include

    Returns:
        AgentConfig instance
    """
    return AgentConfig(
        agent=AgentConfigInner(
            name=name,
            description=f"Test agent: {name}",
            version="1.0",
            type="standard",
            prompt=PromptConfig(inline="You are a test agent. {{input}}"),
            inference=InferenceConfig(
                provider="ollama",
                model="llama2",
                base_url="http://localhost:11434",
                temperature=0.7,
                max_tokens=2048,
            ),
            tools=tools or [],
            timeout_seconds=timeout_seconds,
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
        )
    )


# Timeout configuration presets for testing
TIMEOUT_CONFIGS = {
    "fast": {
        "tool": 2.0,
        "agent": 1.5,
        "stage": 1.0,
        "workflow": 0.8,  # Shortest - should win
    },
    "medium": {
        "tool": 50.0,
        "agent": 40.0,
        "stage": 30.0,
        "workflow": 12.0,  # Shortest - should win
    },
    "slow": {
        "tool": 120.0,
        "agent": 90.0,
        "stage": 60.0,
        "workflow": 30.0,  # Shortest - should win
    },
}
