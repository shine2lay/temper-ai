"""Static checker agent — runs pre_commands, then a single LLM synthesis call.

Unlike StandardAgent, StaticCheckerAgent has no tool-calling loop.
The only subprocess execution is via ``pre_commands``; the LLM receives
their output and produces a structured verdict.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from src.schemas import AgentConfig

from src.agents._pre_command_helpers import execute_pre_commands
from src.agents._standard_agent_helpers import (
    build_final_response as _build_final_response,
    make_stream_callback as _make_stream_callback,
    setup_execution as _setup_execution,
)
from src.agents.base_agent import AgentResponse, BaseAgent, ExecutionContext
from src.agents.cost_estimator import estimate_cost
from src.agents.llm import LLMError
from src.agents.llm.factory import create_llm_from_config
from src.agents.prompt_engine import PromptEngine
from src.agents.prompt_validation import PromptRenderError, _is_safe_template_value
from src.agents.response_parser import extract_final_answer, extract_reasoning
from src.utils.exceptions import sanitize_error_message

logger = logging.getLogger(__name__)


class StaticCheckerAgent(BaseAgent):
    """Agent that runs deterministic pre_commands and synthesises results via LLM.

    Execution flow:
    1. ``setup_execution()`` — sets up observer, stream callback, tracker
    2. ``execute_pre_commands()`` — runs each shell command with StreamEvent emission
    3. Render prompt with command_results injected
    4. Single LLM call (no tool-calling loop)
    5. Return ``AgentResponse``
    """

    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self.prompt_engine = PromptEngine()
        self.llm = create_llm_from_config(self.config.agent.inference)
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

    def _render_prompt(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None,
    ) -> str:
        prompt_config = self.config.agent.prompt

        filtered_input = {k: v for k, v in input_data.items() if _is_safe_template_value(v)}
        all_variables = {**filtered_input, **prompt_config.variables}

        if prompt_config.template:
            try:
                template = self.prompt_engine.render_file(
                    prompt_config.template, all_variables,
                )
            except (PromptRenderError, ValueError, KeyError, FileNotFoundError) as e:
                raise PromptRenderError(
                    f"Failed to render template file {prompt_config.template}: {e}"
                )
        elif prompt_config.inline:
            template = self.prompt_engine.render(prompt_config.inline, all_variables)
        else:
            raise ValueError("No prompt template or inline prompt configured")

        # Auto-inject string input context — exclude command_results (already
        # rendered via Jinja2 {{ command_results }} in the template above).
        _exclude_from_inject = frozenset({"command_results"})
        input_parts: List[str] = []
        for key, value in filtered_input.items():
            if value and isinstance(value, str) and key not in _exclude_from_inject:
                label = key.replace("_", " ").title()
                input_parts.append(f"## {label}\n{value}")
        if input_parts:
            template += "\n\n---\n\n# Input Context\n\n" + "\n\n".join(input_parts)

        return template

    # ------------------------------------------------------------------
    # Sync execution
    # ------------------------------------------------------------------

    def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None,
    ) -> AgentResponse:
        if input_data is None:
            raise ValueError("input_data cannot be None")
        if not isinstance(input_data, dict):
            raise TypeError(f"input_data must be a dictionary, got {type(input_data).__name__}")

        _setup_execution(self, input_data, context, async_mode=False)

        start_time = time.time()
        total_tokens = 0
        total_cost = 0.0

        try:
            # Run deterministic pre_commands with StreamEvent emission
            command_results = execute_pre_commands(self, input_data)
            if command_results is not None:
                input_data["command_results"] = command_results

            prompt = self._render_prompt(input_data, context)

            # Single LLM call — no tool-calling loop
            combined_cb = _make_stream_callback(self)
            if combined_cb:
                llm_response = self.llm.stream(prompt, on_chunk=combined_cb)
            else:
                llm_response = self.llm.complete(prompt)

            if llm_response.total_tokens:
                total_tokens += llm_response.total_tokens

            cost = estimate_cost(llm_response, fallback_model=getattr(self.llm, "model", "unknown"))
            total_cost += cost

            output = extract_final_answer(llm_response.content)
            reasoning = extract_reasoning(llm_response.content)

            # Prepend raw command results so downstream agents see
            # actual error details, not just the LLM's summary.
            raw_results = input_data.get("command_results", "")
            if raw_results and output:
                output = f"{raw_results}\n---\n{output}"
            elif raw_results:
                output = raw_results

            return _build_final_response(  # type: ignore[return-value]
                self,
                output=output,
                reasoning=reasoning,
                tool_calls=[],
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
            )

        except (LLMError, PromptRenderError, RuntimeError, ValueError, TimeoutError) as e:
            safe_msg = sanitize_error_message(str(e))
            logger.warning("StaticCheckerAgent execution error: %s", safe_msg, exc_info=True)
            return _build_final_response(  # type: ignore[return-value]
                self,
                output="",
                reasoning=None,
                tool_calls=[],
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
                error=f"Agent execution error: {safe_msg}",
            )

    # ------------------------------------------------------------------
    # Async execution
    # ------------------------------------------------------------------

    async def aexecute(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None,
    ) -> AgentResponse:
        if input_data is None:
            raise ValueError("input_data cannot be None")
        if not isinstance(input_data, dict):
            raise TypeError(f"input_data must be a dictionary, got {type(input_data).__name__}")

        _setup_execution(self, input_data, context, async_mode=True)

        start_time = time.time()
        total_tokens = 0
        total_cost = 0.0

        try:
            # pre_commands are sync subprocess calls — run in thread
            command_results = await asyncio.to_thread(execute_pre_commands, self, input_data)
            if command_results is not None:
                input_data["command_results"] = command_results

            prompt = self._render_prompt(input_data, context)

            combined_cb = _make_stream_callback(self)
            if combined_cb:
                llm_response = await self.llm.astream(prompt, on_chunk=combined_cb)
            else:
                llm_response = await self.llm.acomplete(prompt)

            if llm_response.total_tokens:
                total_tokens += llm_response.total_tokens

            cost = estimate_cost(llm_response, fallback_model=getattr(self.llm, "model", "unknown"))
            total_cost += cost

            output = extract_final_answer(llm_response.content)
            reasoning = extract_reasoning(llm_response.content)

            # Prepend raw command results so downstream agents see
            # actual error details, not just the LLM's summary.
            raw_results = input_data.get("command_results", "")
            if raw_results and output:
                output = f"{raw_results}\n---\n{output}"
            elif raw_results:
                output = raw_results

            return _build_final_response(  # type: ignore[return-value]
                self,
                output=output,
                reasoning=reasoning,
                tool_calls=[],
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
            )

        except (LLMError, PromptRenderError, RuntimeError, ValueError, TimeoutError) as e:
            safe_msg = sanitize_error_message(str(e))
            logger.warning("StaticCheckerAgent async execution error: %s", safe_msg, exc_info=True)
            return _build_final_response(  # type: ignore[return-value]
                self,
                output="",
                reasoning=None,
                tool_calls=[],
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
                error=f"Agent execution error: {safe_msg}",
            )

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def get_capabilities(self) -> Dict[str, Any]:
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
