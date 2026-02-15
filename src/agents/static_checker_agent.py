"""Static checker agent — runs pre_commands, then a single LLM synthesis call.

Unlike StandardAgent, StaticCheckerAgent has no tool-calling loop.
The only subprocess execution is via ``pre_commands``; the LLM receives
their output and produces a structured verdict.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from src.schemas import AgentConfig

from src.agents.utils._pre_command_helpers import execute_pre_commands
from src.agents.base_agent import AgentResponse, BaseAgent, ExecutionContext
from src.utils.exceptions import LLMError
from src.prompts.validation import PromptRenderError
from src.llm.service import LLMService

logger = logging.getLogger(__name__)

# Keys excluded from auto-injection (already present via Jinja2 template rendering)
_EXCLUDE_FROM_INJECT = frozenset({"command_results"})


class StaticCheckerAgent(BaseAgent):
    """Agent that runs deterministic pre_commands and synthesises results via LLM.

    Execution flow:
    1. ``_setup()`` — sets up observer, stream callback, tracker (via BaseAgent)
    2. ``execute_pre_commands()`` — runs each shell command with StreamEvent emission
    3. Render prompt with command_results injected
    4. Single LLM call (no tool-calling loop) via LLMService
    5. Return ``AgentResponse``
    """

    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self.llm_service = LLMService(
            llm=self.llm,
            inference_config=config.agent.inference,
        )
        self.validate_config()

    def validate_config(self) -> bool:
        """Validate that pre_commands are configured (required for this type)."""
        super().validate_config()
        pre_commands = getattr(self.config.agent, "pre_commands", None)
        if not pre_commands:
            raise ValueError(
                f"StaticCheckerAgent '{self.name}' requires at least one pre_command"
            )
        return True

    # ------------------------------------------------------------------
    # Prompt rendering (simplified — no tool schemas, no dialogue)
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None,
    ) -> str:
        template = self._render_template(input_data)
        template = self._inject_input_context(template, input_data, _EXCLUDE_FROM_INJECT)
        return template

    # ------------------------------------------------------------------
    # Core execution (_run replaces execute)
    # ------------------------------------------------------------------

    def _run(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext],
        start_time: float,
    ) -> AgentResponse:
        """Run pre_commands, render prompt, call LLM once, return response."""
        command_results = execute_pre_commands(self, input_data)
        if command_results is not None:
            input_data["command_results"] = command_results

        prompt = self._build_prompt(input_data, context)
        result = self.llm_service.run(
            prompt,
            tools=None,
            observer=self._observer,
            stream_callback=self._make_stream_callback(),
            agent_name=self.name,
        )
        return self._build_checker_response(result, input_data, start_time)

    async def _arun(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext],
        start_time: float,
    ) -> AgentResponse:
        """Async: pre_commands in thread, then async LLM call."""
        # pre_commands are sync subprocess calls — run in thread
        command_results = await asyncio.to_thread(execute_pre_commands, self, input_data)
        if command_results is not None:
            input_data["command_results"] = command_results

        prompt = self._build_prompt(input_data, context)
        result = await self.llm_service.arun(
            prompt,
            tools=None,
            observer=self._observer,
            stream_callback=self._make_stream_callback(),
            agent_name=self.name,
        )
        return self._build_checker_response(result, input_data, start_time)

    def _build_checker_response(self, result: Any, input_data: Dict[str, Any], start_time: float) -> AgentResponse:
        """Build response, prepending raw command results for downstream agents."""
        output = result.output
        raw_results = input_data.get("command_results", "")
        if raw_results and output:
            output = f"{raw_results}\n---\n{output}"
        elif raw_results:
            output = raw_results

        return self._build_response(
            output=output,
            reasoning=result.reasoning,
            tool_calls=[],
            tokens=result.tokens,
            cost=result.cost,
            start_time=start_time,
            error=result.error,
        )

    def _on_error(
        self, error: Exception, start_time: float
    ) -> Optional[AgentResponse]:
        """Handle expected execution errors."""
        if isinstance(error, (LLMError, PromptRenderError, RuntimeError,
                              ValueError, TimeoutError)):
            return self._build_error_response(error, start_time)
        return None

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def get_capabilities(self) -> Dict[str, Any]:
        """Get agent capabilities and configuration."""
        pre_commands = getattr(self.config.agent, "pre_commands", []) or []
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "type": "static_checker",
            "llm_provider": self.config.agent.inference.provider,
            "llm_model": self.config.agent.inference.model,
            "tools": [],
            "pre_commands": [cmd.name for cmd in pre_commands],
            "supports_streaming": True,
            "supports_multimodal": False,
        }
