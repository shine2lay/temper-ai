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
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from temper_ai.storage.schemas import AgentConfig

from temper_ai.agent.base_agent import AgentResponse, BaseAgent, ExecutionContext
from temper_ai.agent.utils.constants import DEFAULT_MAX_DIALOGUE_CONTEXT_CHARS, PROMPT_PREVIEW_LENGTH
from temper_ai.llm.prompts.validation import PromptRenderError, _is_safe_template_value
from temper_ai.llm.service import LLMRunResult, LLMService
from temper_ai.memory._schemas import MemoryScope
from temper_ai.memory.constants import MEMORY_QUERY_MAX_CHARS
from temper_ai.memory.service import MemoryService
from temper_ai.shared.utils.exceptions import (
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

        self._memory_service: Optional[MemoryService] = None

        self.validate_config()

    def _run(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext],
        start_time: float,
    ) -> AgentResponse:
        """Execute multi-turn tool-calling loop via LLMService."""
        prompt = self._prepare_prompt(input_data, context)
        kwargs = self._llm_kwargs(prompt, start_time)
        messages = self._build_messages_from_history(input_data, prompt)
        if messages is not None:
            kwargs["messages"] = messages
        result = self.llm_service.run(**kwargs)
        response = self._convert_result(result, start_time)
        response.metadata["_rendered_prompt"] = prompt
        response.metadata["_user_message"] = result.user_message
        response.metadata["_assistant_message"] = result.assistant_message
        return response

    async def _arun(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext],
        start_time: float,
    ) -> AgentResponse:
        """Async multi-turn tool-calling loop via LLMService."""
        prompt = self._prepare_prompt(input_data, context)
        kwargs = self._llm_kwargs(prompt, start_time)
        messages = self._build_messages_from_history(input_data, prompt)
        if messages is not None:
            kwargs["messages"] = messages
        result = await self.llm_service.arun(**kwargs)
        response = self._convert_result(result, start_time)
        response.metadata["_rendered_prompt"] = prompt
        response.metadata["_user_message"] = result.user_message
        response.metadata["_assistant_message"] = result.assistant_message
        return response

    @staticmethod
    def _build_messages_from_history(
        input_data: Dict[str, Any], current_prompt: str,
    ) -> Optional[list]:
        """Build multi-turn messages list from conversation history.

        Returns None when no history is present (single-turn mode).
        """
        history = input_data.get("_conversation_history")
        if history is None or len(history) == 0:
            return None
        messages: list = history.to_message_list()
        messages.append({"role": "user", "content": current_prompt})
        return messages

    def _prepare_prompt(self, input_data: Dict[str, Any], context: Optional[ExecutionContext]) -> str:
        """Render prompt, store as system prompt, and log preview."""
        prompt = self._build_prompt(input_data, context)
        self._system_prompt = prompt
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
            response = self._build_response(
                output=error.last_output,
                reasoning=error.last_reasoning,
                tool_calls=error.tool_calls,
                tokens=error.tokens,
                cost=error.cost,
                start_time=start_time,
                error=str(error),
            )
            response.metadata = {"iterations": error.iterations}
            return response
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

        from temper_ai.llm.prompts.dialogue_formatter import (
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
        template = self._inject_memory_context(template, input_data, context)

        return template

    def _get_memory_service(self) -> MemoryService:
        """Lazy-create and cache the MemoryService instance."""
        if self._memory_service is None:
            mem_cfg = self.config.agent.memory
            self._memory_service = MemoryService(provider_name=mem_cfg.provider)
        return self._memory_service

    def _build_memory_scope(self, context: Optional[ExecutionContext] = None) -> MemoryScope:
        """Build a MemoryScope from agent config and execution context."""
        mem_cfg = self.config.agent.memory
        workflow_name = ""
        if context and context.metadata:
            workflow_name = context.metadata.get("workflow_name", "")
        return self._get_memory_service().build_scope(
            tenant_id=mem_cfg.tenant_id,
            workflow_name=workflow_name,
            agent_name=self.name,
            namespace=mem_cfg.memory_namespace,
        )

    def _inject_memory_context(
        self,
        template: str,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None,
    ) -> str:
        """Inject relevant memories into the prompt template.

        Returns template unchanged if memory is disabled or on error.
        """
        if not self.config.agent.memory.enabled:
            return template

        try:
            mem_cfg = self.config.agent.memory
            svc = self._get_memory_service()
            scope = self._build_memory_scope(context)
            query = self._extract_memory_query(input_data)
            shared_ns = getattr(mem_cfg, "shared_namespace", None)

            if shared_ns:
                shared_scope = svc.build_shared_scope(scope, shared_ns)
                memory_text = svc.retrieve_with_shared(
                    scope, shared_scope, query,
                    retrieval_k=mem_cfg.retrieval_k,
                    relevance_threshold=mem_cfg.relevance_threshold,
                    decay_factor=mem_cfg.decay_factor,
                )
            else:
                memory_text = svc.retrieve_context(
                    scope, query,
                    retrieval_k=mem_cfg.retrieval_k,
                    relevance_threshold=mem_cfg.relevance_threshold,
                    decay_factor=mem_cfg.decay_factor,
                )

            if memory_text:
                template += "\n\n---\n\n" + memory_text

            # Retrieve procedural memories (learned best practices)
            try:
                procedural_text = svc.retrieve_procedural_context(
                    scope, query,
                    retrieval_k=mem_cfg.retrieval_k,
                    relevance_threshold=mem_cfg.relevance_threshold,
                )
                if procedural_text:
                    template += "\n\n" + procedural_text
            except (ValueError, TypeError, KeyError, RuntimeError, OSError, ImportError) as exc:
                logger.warning("Procedural memory injection failed for agent %s: %s", self.name, exc)
        except (ValueError, TypeError, KeyError, RuntimeError, OSError, ImportError) as exc:
            logger.warning("Memory injection failed for agent %s: %s", self.name, exc)

        return template

    def _extract_memory_query(self, input_data: Dict[str, Any]) -> str:
        """Build a query string from input_data string values (truncated to 500 chars)."""
        parts = [str(v) for v in input_data.values() if isinstance(v, str)]
        return " ".join(parts)[:MEMORY_QUERY_MAX_CHARS]

    def _on_after_run(self, result: AgentResponse) -> AgentResponse:
        """Store execution output as episodic memory after run."""
        if not self.config.agent.memory.enabled:
            return result

        try:
            mem_cfg = self.config.agent.memory
            scope = self._build_memory_scope(self._execution_context)
            output_text = result.output or ""
            if output_text:
                svc = self._get_memory_service()
                svc.store_episodic(
                    scope,
                    content=output_text,
                    metadata={"agent_name": self.name},
                    max_episodes=mem_cfg.max_episodes,
                )
                self._maybe_extract_procedural(svc, scope, output_text, mem_cfg)
                self._maybe_store_shared(svc, scope, output_text, mem_cfg)
        except (ValueError, TypeError, KeyError, RuntimeError, OSError, ImportError) as exc:
            logger.warning("Memory storage failed for agent %s: %s", self.name, exc)

        return result

    def _maybe_extract_procedural(
        self, svc: MemoryService, scope: MemoryScope,
        output_text: str, mem_cfg: Any,
    ) -> None:
        """Auto-extract procedural patterns when configured."""
        if not getattr(mem_cfg, "auto_extract_procedural", False):
            return
        try:
            from temper_ai.memory.extractors import extract_procedural_patterns

            llm_fn = lambda prompt: self.llm.complete(prompt).content  # noqa: E731
            patterns = extract_procedural_patterns(output_text, llm_fn)
            for pattern in patterns:
                svc.store_procedural(
                    scope, pattern,
                    metadata={"agent_name": self.name, "source": "auto_extract"},
                )
        except (ValueError, TypeError, RuntimeError, OSError, ImportError) as exc:
            logger.warning("Procedural extraction failed for agent %s: %s", self.name, exc)

    def _maybe_store_shared(
        self, svc: MemoryService, scope: MemoryScope,
        output_text: str, mem_cfg: Any,
    ) -> None:
        """Store memory in shared namespace when configured."""
        shared_ns = getattr(mem_cfg, "shared_namespace", None)
        if not shared_ns:
            return
        try:
            shared_scope = svc.build_shared_scope(scope, shared_ns)
            svc.store_episodic(
                shared_scope, output_text,
                metadata={"source_agent": self.name},
            )
        except (ValueError, TypeError, RuntimeError, OSError, ImportError) as exc:
            logger.warning("Shared memory storage failed for agent %s: %s", self.name, exc)

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
