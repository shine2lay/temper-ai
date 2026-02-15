"""Standard agent implementation with LLM and tool execution.

StandardAgent is the default agent type that executes a multi-turn loop:
1. Render prompt with input
2. Call LLM (via LLMService)
3. Parse tool calls from LLM response
4. Execute tools
5. Inject tool results back into prompt
6. Repeat until no more tool calls or max iterations reached
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from src.schemas import AgentConfig

from src.agents.base_agent import AgentResponse, BaseAgent, ExecutionContext
from src.agents.utils.constants import DEFAULT_MAX_DIALOGUE_CONTEXT_CHARS, PROMPT_PREVIEW_LENGTH
from src.prompts.validation import PromptRenderError, _is_safe_template_value
from src.llm.service import LLMRunResult, LLMService
from src.utils.exceptions import (
    ConfigValidationError,
    LLMError,
    MaxIterationsError,
    ToolExecutionError,
)

logger = logging.getLogger(__name__)

# Keys excluded from input context injection (handled by interaction mode logic)
_MODE_CONTEXT_KEYS = frozenset({
    "interaction_mode", "mode_instruction", "debate_framing",
})


class StandardAgent(BaseAgent):
    """Standard agent with LLM and tool execution loop.

    This is the primary agent implementation that handles:
    - Prompt rendering from templates
    - LLM inference with retry logic (via LLMService)
    - Tool calling (function calling) parsing and execution
    - Multi-turn conversation for complex tasks
    - Token usage and cost tracking
    """

    def __init__(self, config: AgentConfig):
        """Initialize standard agent from configuration."""
        super().__init__(config)

        self.tool_registry = self._create_tool_registry()

        # LLMService owns the LLM call lifecycle
        self.llm_service = LLMService(
            llm=self.llm,
            inference_config=config.agent.inference,
        )

        self.validate_config()

    def _run(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext],
        start_time: float,
    ) -> AgentResponse:
        """Execute multi-turn tool-calling loop via LLMService."""
        prompt = self._prepare_prompt(input_data, context)
        result = self.llm_service.run(**self._llm_kwargs(prompt, start_time))
        return self._convert_result(result, start_time)

    async def _arun(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext],
        start_time: float,
    ) -> AgentResponse:
        """Async multi-turn tool-calling loop via LLMService."""
        prompt = self._prepare_prompt(input_data, context)
        result = await self.llm_service.arun(**self._llm_kwargs(prompt, start_time))
        return self._convert_result(result, start_time)

    def _prepare_prompt(self, input_data: Dict[str, Any], context: Optional[ExecutionContext]) -> str:
        """Render prompt, store as system prompt, and log preview."""
        prompt = self._build_prompt(input_data, context)
        self._system_prompt = prompt  # type: ignore[attr-defined]
        preview = prompt[-PROMPT_PREVIEW_LENGTH:].replace('\n', ' ').strip()
        logger.info("[%s] Prompt ready (%d chars) ...%s", self.name, len(prompt), preview)
        return prompt

    def _llm_kwargs(self, prompt: str, start_time: float) -> Dict[str, Any]:
        """Build kwargs shared between sync run() and async arun()."""
        tools = list(self.tool_registry.get_all_tools().values())
        return dict(
            prompt=prompt,
            tools=tools if tools else None,
            tool_executor=self.tool_executor,
            observer=self._observer,
            stream_callback=self._make_stream_callback(),
            safety_config=self.config.agent.safety,
            agent_name=self.name,
            max_iterations=self.config.agent.safety.max_tool_calls_per_execution,
            max_execution_time=self.config.agent.safety.max_execution_time_seconds,
            start_time=start_time,
        )

    def _on_error(
        self, error: Exception, start_time: float
    ) -> Optional[AgentResponse]:
        """Handle expected execution errors with accumulated metrics."""
        if isinstance(error, MaxIterationsError):
            return self._build_response(
                output=error.last_output,
                reasoning=error.last_reasoning,
                tool_calls=error.tool_calls,
                tokens=error.tokens,
                cost=error.cost,
                start_time=start_time,
                error=str(error),
                metadata={"iterations": error.iterations},
            )
        if isinstance(error, (LLMError, ToolExecutionError, PromptRenderError,
                              ConfigValidationError, RuntimeError, ValueError,
                              TimeoutError)):
            return self._build_error_response(error, start_time)
        return None

    def _convert_result(self, result: LLMRunResult, start_time: float) -> AgentResponse:
        """Convert LLMRunResult to AgentResponse."""
        return self._build_response(
            output=result.output,
            reasoning=result.reasoning,
            tool_calls=result.tool_calls,
            tokens=result.tokens,
            cost=result.cost,
            start_time=start_time,
            error=result.error,
        )

    def _inject_dialogue_context(self, template: str, input_data: Dict[str, Any]) -> str:
        """Auto-inject dialogue history and stage agent outputs."""
        if not getattr(self.config.agent, 'dialogue_aware', True):
            return template

        from src.prompts.dialogue_formatter import (
            format_dialogue_history,
            format_stage_agent_outputs,
        )
        filtered_input = {k: v for k, v in input_data.items() if _is_safe_template_value(v)}
        max_chars = getattr(self.config.agent, 'max_dialogue_context_chars', DEFAULT_MAX_DIALOGUE_CONTEXT_CHARS)

        dialogue_history = filtered_input.get("dialogue_history")
        if dialogue_history and isinstance(dialogue_history, list):
            formatted = format_dialogue_history(dialogue_history, max_chars)
            if formatted:
                template += "\n\n---\n\n" + formatted

        stage_agents = filtered_input.get("current_stage_agents")
        if stage_agents and isinstance(stage_agents, dict):
            formatted = format_stage_agent_outputs(stage_agents, max_chars // 2)
            if formatted:
                template += "\n\n---\n\n" + formatted

        return template

    def _build_prompt(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None
    ) -> str:
        """Render prompt template with input data.

        Tool schemas are handled by LLMService — this only renders the
        base template with input context and dialogue context.
        """
        template = self._render_template(input_data)
        template = self._inject_input_context(template, input_data, _MODE_CONTEXT_KEYS)
        template = self._inject_dialogue_context(template, input_data)

        return template

    def get_capabilities(self) -> Dict[str, Any]:
        """Get agent capabilities."""
        tools_list = self.tool_registry.list_tools()
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "type": "standard",
            "llm_provider": self.config.agent.inference.provider,
            "llm_model": self.config.agent.inference.model,
            "tools": tools_list,
            "max_tool_calls": self.config.agent.safety.max_tool_calls_per_execution,
            "supports_streaming": True,
            "supports_multimodal": False
        }
