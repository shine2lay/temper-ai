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
        from temper_ai.agent._r0_pipeline_helpers import (
            apply_context_management, apply_guardrails,
            apply_reasoning, validate_and_retry_output,
        )

        prompt = self._prepare_prompt(input_data, context)
        if self.config.agent.reasoning.enabled:
            prompt = apply_reasoning(self.llm_service, self.config, prompt)
        if self.config.agent.context_management.enabled:
            prompt = apply_context_management(self.config, prompt)
        kwargs = self._llm_kwargs(prompt, start_time)
        messages = self._build_messages_from_history(input_data, prompt)
        if messages is not None:
            kwargs["messages"] = messages
        result = self.llm_service.run(**kwargs)
        if self.config.agent.output_schema and self.config.agent.output_schema.json_schema:
            result = validate_and_retry_output(self.llm_service, self.config, result, prompt, kwargs)
        if self.config.agent.output_guardrails.enabled:
            result = apply_guardrails(self.llm_service, self.config, result, prompt, kwargs)
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
        from temper_ai.agent._r0_pipeline_helpers import (
            aapply_guardrails, apply_context_management,
            apply_reasoning, avalidate_and_retry_output,
        )

        prompt = self._prepare_prompt(input_data, context)
        if self.config.agent.reasoning.enabled:
            prompt = apply_reasoning(self.llm_service, self.config, prompt)
        if self.config.agent.context_management.enabled:
            prompt = apply_context_management(self.config, prompt)
        kwargs = self._llm_kwargs(prompt, start_time)
        messages = self._build_messages_from_history(input_data, prompt)
        if messages is not None:
            kwargs["messages"] = messages
        result = await self.llm_service.arun(**kwargs)
        if self.config.agent.output_schema and self.config.agent.output_schema.json_schema:
            result = await avalidate_and_retry_output(self.llm_service, self.config, result, prompt, kwargs)
        if self.config.agent.output_guardrails.enabled:
            result = await aapply_guardrails(self.llm_service, self.config, result, prompt, kwargs)
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
        template = self._inject_optimization_context(template)
        template = self._inject_persistent_context(template, context)

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
        scope = self._get_memory_service().build_scope(
            tenant_id=mem_cfg.tenant_id,
            workflow_name=workflow_name,
            agent_name=self.name,
            namespace=mem_cfg.memory_namespace,
        )
        if getattr(self.config.agent, "persistent", False):
            from temper_ai.registry.constants import PERSISTENT_NAMESPACE_PREFIX

            scope = MemoryScope(
                tenant_id=scope.tenant_id,
                workflow_name="",
                agent_name=scope.agent_name,
                namespace=f"{PERSISTENT_NAMESPACE_PREFIX}{self.config.agent.name}",
                agent_id=getattr(self.config.agent, "agent_id", None),
            )
        return scope

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

    def _inject_persistent_context(self, prompt: str, context: Optional[ExecutionContext]) -> str:
        """Inject persistent agent context into prompt (M9)."""
        if not getattr(self.config.agent, "persistent", False):
            return prompt

        from temper_ai.agent._m9_context_helpers import (
            detect_execution_mode,
            inject_cross_pollination_context,
            inject_execution_mode_context,
            inject_project_goal_context,
        )

        ctx_dict: Dict[str, Any] = {}
        if context:
            ctx_dict = {"workflow_id": context.workflow_id}

        mode = detect_execution_mode(ctx_dict)
        prompt = inject_execution_mode_context(prompt, mode)

        agent_id = getattr(self.config.agent, "agent_id", None)
        if agent_id:
            from temper_ai.goals.agent_goals import AgentGoalService

            goal_service = AgentGoalService()
            prompt = inject_project_goal_context(prompt, agent_id, goal_service)

        cross_config = getattr(self.config.agent, "cross_pollination", None)
        if cross_config and self._memory_service:
            query = ""
            prompt = inject_cross_pollination_context(
                prompt, cross_config, self._memory_service, query
            )

        return prompt

    def _inject_optimization_context(self, template: str) -> str:
        """Inject DSPy-optimized prompt sections if available."""
        opt_cfg = getattr(self.config.agent, "prompt_optimization", None)
        if opt_cfg is None or not getattr(opt_cfg, "enabled", False):
            return template
        try:
            from temper_ai.optimization.prompt_adapter import DSPyPromptAdapter
            from temper_ai.optimization.program_store import CompiledProgramStore

            store = CompiledProgramStore(store_dir=opt_cfg.program_store_dir)
            adapter = DSPyPromptAdapter(store=store)
            return adapter.augment_prompt(
                agent_name=self.name,
                rendered_prompt=template,
                max_demos=opt_cfg.max_demos,
            )
        except ImportError:
            logger.debug("DSPy not installed, skipping prompt optimization")
            return template
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
            logger.warning("Prompt optimization injection failed: %s", exc)
            return template

    def _extract_memory_query(self, input_data: Dict[str, Any]) -> str:
        """Build a query string from input_data string values (truncated to 500 chars)."""
        parts = [str(v) for v in input_data.values() if isinstance(v, str)]
        return " ".join(parts)[:MEMORY_QUERY_MAX_CHARS]

    def _on_after_run(self, result: AgentResponse) -> AgentResponse:
        """Store execution output as episodic memory after run."""
        if self.config.agent.memory.enabled:
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

        self._maybe_publish_persistent_output(result)
        return result

    def _maybe_publish_persistent_output(self, result: AgentResponse) -> None:
        """Publish agent output to cross-pollination namespace when configured (M9)."""
        if not getattr(self.config.agent, "persistent", False):
            return
        cross_config = getattr(self.config.agent, "cross_pollination", None)
        if not cross_config or not getattr(cross_config, "publish_output", False):
            return
        output_text = result.output or ""
        if not output_text:
            return
        try:
            from temper_ai.memory.cross_pollination import publish_knowledge

            publish_knowledge(
                agent_name=self.config.agent.name,
                content=output_text,
                memory_service=self._get_memory_service(),
            )
        except (ValueError, TypeError, KeyError, RuntimeError, OSError, ImportError):
            logger.debug("Failed to publish agent output", exc_info=True)

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
            "llm_provider": self.config.agent.inference.provider if self.config.agent.inference else "none",
            "llm_model": self.config.agent.inference.model if self.config.agent.inference else "none",
            "tools": tools_list,
            "max_tool_calls": self.config.agent.safety.max_tool_calls_per_execution,
            "supports_streaming": True,
            "supports_multimodal": False
        }
