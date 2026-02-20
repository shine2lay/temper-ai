"""Base class for external agent plugin adapters."""
from __future__ import annotations

import logging
import time
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional

if TYPE_CHECKING:
    from pathlib import Path
    from temper_ai.storage.schemas import AgentConfig

from temper_ai.agent.base_agent import BaseAgent, ExecutionContext
from temper_ai.agent.models.response import AgentResponse
from temper_ai.plugins.constants import PLUGIN_DEFAULT_TIMEOUT  # noqa: F401

logger = logging.getLogger(__name__)

# Common input keys to search for task description
_TASK_INPUT_KEYS = ("query", "task", "input", "question", "prompt", "message")


class ExternalAgentPlugin(BaseAgent):
    """Abstract base for external framework agent adapters.

    Follows ScriptAgent pattern: skips BaseAgent.__init__() since
    external agents don't need PromptEngine or LLM.
    """

    FRAMEWORK_NAME: ClassVar[str] = ""
    AGENT_TYPE: ClassVar[str] = ""
    REQUIRED_PACKAGE: ClassVar[str] = ""

    def __init__(self, config: AgentConfig) -> None:
        # Skip BaseAgent.__init__ — no LLM or PromptEngine needed
        self.config = config
        self.name = config.agent.name
        self.description = config.agent.description
        self.version = config.agent.version

        # Infrastructure attrs — set by _setup() at execution time
        self.tool_executor: Any = None
        self.tracker: Any = None
        self._observer: Any = None
        self._stream_callback: Any = None
        self._execution_context: Any = None

        self._external_agent: Any = None
        self._initialized = False

    def _get_plugin_config(self) -> Dict[str, Any]:
        """Extract plugin_config from agent config."""
        raw = getattr(self.config.agent, "plugin_config", None)
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        # PluginConfig pydantic model
        return raw.model_dump() if hasattr(raw, "model_dump") else {}

    @abstractmethod
    def _initialize_external_agent(self) -> None:
        """Initialize the external framework agent. Called lazily on first run."""

    @abstractmethod
    def _execute_external(self, input_data: Dict[str, Any]) -> str:
        """Execute the external agent and return string output."""

    @classmethod
    @abstractmethod
    def translate_config(cls, source_path: Path) -> List[Dict[str, Any]]:
        """Translate external framework config to Temper AI config dicts."""

    def _on_setup(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext],
    ) -> None:
        """Lazily initialize external agent on first execution."""
        if not self._initialized:
            self._initialize_external_agent()
            self._initialized = True

    def _run(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext],
        start_time: float,
    ) -> AgentResponse:
        """Execute external agent and wrap result as AgentResponse."""
        output = self._execute_external(input_data)
        return AgentResponse(
            output=output,
            reasoning=None,
            tool_calls=[],
            metadata={
                "framework": self.FRAMEWORK_NAME,
                "agent_type": self.AGENT_TYPE,
            },
            tokens=0,
            estimated_cost_usd=0.0,
            latency_seconds=time.time() - start_time,
        )

    def _on_error(
        self, error: Exception, start_time: float,
    ) -> Optional[AgentResponse]:
        """Handle plugin execution errors."""
        if isinstance(error, (ImportError, ValueError, RuntimeError, TimeoutError)):
            return self._build_error_response(error, start_time)
        return None

    def get_capabilities(self) -> Dict[str, Any]:
        """Get plugin agent capabilities."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "type": self.AGENT_TYPE,
            "framework": self.FRAMEWORK_NAME,
            "tools": [],
            "supports_streaming": False,
            "supports_multimodal": False,
        }

    def validate_config(self) -> bool:
        """Validate plugin agent configuration."""
        if not self.config.agent.name:
            raise ValueError("Agent name is required")
        return True

    @staticmethod
    def _extract_task_description(input_data: Dict[str, Any]) -> str:
        """Extract task description from input data."""
        for key in _TASK_INPUT_KEYS:
            if key in input_data and input_data[key]:
                return str(input_data[key])
        # Fall back to string representation of all values
        values = [str(v) for v in input_data.values() if v]
        return " ".join(values) if values else ""
