"""LLM agent — uses LLM with Jinja2 prompt templates, tools, and memory.

All infrastructure comes from ExecutionContext at run time:
- LLM provider: context.get_llm(self.provider)
- Tools: context.tool_executor
- Memory: context.memory_service
- Events: context.event_recorder

Agent config drives per-call LLM behavior (model, temperature, etc.).
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from temper_ai.agent.base import AgentABC
from temper_ai.llm.models import CallContext, LLMRunResult
from temper_ai.llm.prompt_renderer import PromptRenderer
from temper_ai.llm.service import DEFAULT_MAX_CONTEXT_TOKENS, DEFAULT_MAX_MESSAGES, LLMService

DEFAULT_TOTAL_TIMEOUT = 300.0
from temper_ai.observability import EventType
from temper_ai.observability import record as _default_record
from temper_ai.shared.types import (
    AgentInterface,
    AgentResult,
    ExecutionContext,
    Status,
    TokenUsage,
)

logger = logging.getLogger(__name__)


class LLMAgent(AgentABC):
    """Agent that uses LLM with Jinja2 prompt templates, tools, and memory."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.provider = config.get("provider", "openai")
        self.model = config.get("model", "gpt-4o-mini")
        self.max_iterations = config.get("max_iterations", 10)
        self.token_budget = config.get("token_budget", 8000)
        self.prompt_renderer = PromptRenderer(
            token_counter=self._estimate_token_count,
        )

    def run(self, input_data: dict, context: ExecutionContext) -> AgentResult:
        """Execute the LLM agent pipeline.

        1. Recall memories (if memory enabled in config)
        2. Render prompt via PromptRenderer (Jinja2 template + variables)
        3. Get LLM provider from context
        4. Call LLM (tool-calling loop)
        5. Extract structured output (best-effort JSON parse)
        6. Store agent output to memory (mem0 extracts facts internally)
        7. Return AgentResult with all tracking data
        """
        start = time.monotonic()
        _record = context.event_recorder.record if context.event_recorder else _default_record
        agent_event_id = self._record_agent_started(_record, input_data, context)

        try:
            result = self._execute(input_data, context, agent_event_id)
            result.duration_seconds = round(time.monotonic() - start, 3)
            self._record_agent_completed(_record, result, agent_event_id, context)
            return result

        except Exception as e:  # noqa: broad-except
            duration = round(time.monotonic() - start, 3)
            _record(
                EventType.AGENT_FAILED,
                parent_id=agent_event_id,
                execution_id=context.run_id,
                status="failed",
                data={
                    "agent_name": self.name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "duration_seconds": duration,
                },
            )
            return AgentResult(
                status=Status.FAILED,
                output="",
                error=str(e),
                duration_seconds=duration,
            )

    def _record_agent_started(self, _record, input_data: dict, context: ExecutionContext) -> str:
        """Emit AGENT_STARTED event and return the event id."""
        return _record(
            EventType.AGENT_STARTED,
            parent_id=context.parent_event_id,
            execution_id=context.run_id,
            status="running",
            data={
                "agent_name": self.name,
                "node_path": context.node_path,
                "provider": self.provider,
                "model": self.model,
                "input_data": _truncate_input_data(input_data),
                "role": self.config.get("role"),
                "agent_config": {
                    "type": self.config.get("type", "llm"),
                    "provider": self.provider,
                    "model": self.model,
                    "role": self.config.get("role"),
                    "temperature": self.config.get("temperature"),
                    "max_tokens": self.config.get("max_tokens"),
                    "token_budget": self.token_budget,
                    "max_iterations": self.max_iterations,
                    "system_prompt": self.config.get("system_prompt", "")[:500],
                    "task_template": self.config.get("task_template", "")[:500],
                    "tools": self.config.get("tools", []),
                    "memory": self.config.get("memory"),
                },
            },
        )

    def _record_agent_completed(self, _record, result, agent_event_id: str, context: ExecutionContext) -> None:
        """Emit AGENT_COMPLETED event."""
        _record(
            EventType.AGENT_COMPLETED,
            parent_id=agent_event_id,
            execution_id=context.run_id,
            status="completed",
            data={
                "agent_name": self.name,
                "output": result.output[:5000] if result.output else "",
                "output_length": len(result.output),
                "has_structured_output": result.structured_output is not None,
                "structured_output": result.structured_output,
                "tokens": result.tokens.total_tokens,
                "cost_usd": result.cost_usd,
                "llm_calls": result.llm_calls,
                "tool_calls": result.tool_calls,
                "duration_seconds": result.duration_seconds,
            },
        )

    def _execute(
        self,
        input_data: dict,
        context: ExecutionContext,
        agent_event_id: str,
    ) -> AgentResult:
        """Core execution logic, separated for clean error handling."""
        memories = self._recall_memories(context)

        messages = self.prompt_renderer.render(
            agent_config=self.config,
            input_data=input_data,
            memories=memories,
            strategy_context=input_data.get("_strategy_context"),
            token_budget=self.token_budget,
        )

        llm_service = self._build_llm_service(context)
        call_context = self._build_call_context(context, agent_event_id, input_data)

        tools = self._get_tools(context)
        execute_tool = self._make_tool_executor(context) if tools else None

        stream_cb = context.stream_callback
        if not stream_cb and hasattr(context.event_recorder, 'broadcast_stream_chunk'):
            stream_cb = self._make_stream_callback(context, agent_event_id)

        # Build budget check callback so LLM service can check before each iteration
        # Respects skip_policies on the current node (e.g., script cleanup stages)
        budget_check = None
        te = context.tool_executor
        skip = set(context.skip_policies or [])
        if te and hasattr(te, 'policy_engine') and te.policy_engine and 'budget' not in skip:
            def _check_budget():
                from temper_ai.safety.base import ActionType
                ctx = {"run_cost_usd": te.run_cost_usd, "run_tokens": te.run_tokens}
                decision = te.policy_engine.evaluate(
                    ActionType.LLM_CALL, {"agent_name": self.config.get("name", "")}, ctx,
                )
                return decision.reason if decision.action == "deny" else None
            budget_check = _check_budget

        # Wire usage tracker so budget stays current between LLM iterations
        if budget_check and te:
            llm_service._usage_tracker = lambda cost, tokens: te.track_usage(cost, tokens)

        llm_result: LLMRunResult = llm_service.run(
            messages=messages,
            tools=tools or None,
            execute_tool=execute_tool,
            context=call_context,
            stream_callback=stream_cb,
            budget_check=budget_check,
        )

        if context.tool_executor and hasattr(context.tool_executor, 'track_usage'):
            context.tool_executor.track_usage(
                cost_usd=llm_result.cost,
                tokens=llm_result.tokens,
            )

        structured = _extract_structured_output(llm_result.output)
        memories_formed = self._store_memories(llm_result.output, context)

        return AgentResult(
            status=Status.FAILED if llm_result.error else Status.COMPLETED,
            output=llm_result.output,
            structured_output=structured,
            tokens=TokenUsage(total_tokens=llm_result.tokens),
            cost_usd=llm_result.cost,
            memories_formed=memories_formed,
            error=llm_result.error,
            llm_calls=llm_result.iterations,
            tool_calls=len(llm_result.tool_calls),
        )

    def _build_llm_service(self, context: ExecutionContext) -> LLMService:
        """Instantiate the LLMService for this agent's provider."""
        llm = context.get_llm(self.provider)
        return LLMService(
            provider=llm,
            max_iterations=self.max_iterations,
            max_messages=self.config.get("max_messages", DEFAULT_MAX_MESSAGES),
            total_timeout=float(self.config.get("total_timeout", DEFAULT_TOTAL_TIMEOUT)),
            max_context_tokens=self.config.get("max_context_tokens", DEFAULT_MAX_CONTEXT_TOKENS),
        )

    def _build_call_context(
        self, context: ExecutionContext, agent_event_id: str, input_data: dict | None = None,
    ) -> CallContext:
        """Build the CallContext for LLMService observability."""
        # Use workspace_path from input_data as cwd for providers that need it (Claude Code)
        cwd = (input_data or {}).get("workspace_path") or context.workspace_path
        return CallContext(
            execution_id=context.run_id,
            agent_event_id=agent_event_id,
            agent_name=self.name,
            node_path=context.node_path,
            event_recorder=(
                context.event_recorder.record if context.event_recorder else None
            ),
            cwd=cwd,
        )

    def _recall_memories(self, context: ExecutionContext) -> list[str]:
        """Recall relevant memories for this agent."""
        if not context.memory_service:
            return []
        if not self.config.get("memory", {}).get("enabled", False):
            return []
        scope = self._memory_scope(context)
        limit = self.config.get("memory", {}).get("recall_limit", 10)
        try:
            entries = context.memory_service.recall(self.name, scope, limit=limit)
            self._get_recorder(context)(
                EventType.MEMORY_RECALLED,
                execution_id=context.run_id,
                data={
                    "agent_name": self.name,
                    "scope": scope,
                    "count": len(entries),
                },
            )
            return entries
        except Exception as e:
            logger.warning("Memory recall failed for '%s': %s", self.name, e)
            return []

    def _store_memories(self, output: str, context: ExecutionContext) -> list[str]:
        """Store agent output to memory. Returns list of stored memory IDs."""
        if not context.memory_service:
            return []
        if not self.config.get("memory", {}).get("store_observations", False):
            return []
        scope = self._memory_scope(context)
        try:
            result = context.memory_service.store(
                self.name, scope, output,
                metadata={"run_id": context.run_id},
            )
            self._get_recorder(context)(
                EventType.MEMORY_STORED,
                execution_id=context.run_id,
                data={
                    "agent_name": self.name,
                    "scope": scope,
                },
            )
            return [result] if isinstance(result, str) and result else []
        except Exception as e:
            logger.warning("Memory store failed for '%s': %s", self.name, e)
            return []

    @staticmethod
    def _get_recorder(context: ExecutionContext):
        """Get event recorder — uses context.event_recorder if available, falls back to module-level."""
        return context.event_recorder.record if context.event_recorder else _default_record

    @staticmethod
    def _estimate_token_count(messages: list[dict]) -> int:
        """Rough token count estimate — ~4 chars per token."""
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return total_chars // 4

    @staticmethod
    def _make_stream_callback(context: ExecutionContext, agent_event_id: str):
        """Create a callback that broadcasts LLM stream chunks via WebSocket.

        The callback is invoked by the LLM provider for each token during streaming.
        Chunks are buffered and batch-delivered by the WebSocketManager.
        """
        broadcaster = context.event_recorder.broadcast_stream_chunk

        def on_chunk(chunk):
            content = getattr(chunk, "content", "")
            chunk_type = getattr(chunk, "chunk_type", "content")
            done = getattr(chunk, "done", False)
            if not content and not done:
                return
            try:
                broadcaster(
                    agent_id=agent_event_id,
                    content=content,
                    chunk_type=chunk_type,
                    done=done,
                )
            except Exception: # noqa
                pass  # Best-effort — never block LLM streaming  # noqa: B110

        return on_chunk

    def _memory_scope(self, context: ExecutionContext) -> str:
        """Build memory scope string from context."""
        if context.workspace_path:
            return f"project:{context.workspace_path}"
        return f"workflow:{context.workflow_name}"

    def _get_tools(self, context: ExecutionContext) -> list[dict[str, Any]]:
        """Get tool schemas for tools configured on this agent."""
        tool_names = self.config.get("tools", [])
        if not tool_names or not context.tool_executor:
            return []

        schemas = []
        for name in tool_names:
            tool = context.tool_executor.get_tool(name)
            if tool:
                schemas.append(tool.to_llm_schema())
            else:
                logger.warning(
                    "Tool '%s' configured for agent '%s' but not registered",
                    name, self.name,
                )
        return schemas

    def _make_tool_executor(self, context: ExecutionContext):
        """Create a tool executor function compatible with LLMService."""
        # Keep Delegate tool's context in sync with the agent's context
        delegate = context.tool_executor.get_tool("Delegate") if context.tool_executor else None
        if delegate and hasattr(delegate, "bind_context"):
            delegate.bind_context(context)

        def execute_tool(tool_name: str, params: dict[str, Any]) -> Any:
            result = context.tool_executor.execute(
                tool_name,
                params,
                context={
                    "parent_id": None,
                    "execution_id": context.run_id,
                    "skip_policies": context.skip_policies,
                },
            )
            return result.result if result.success else f"Error: {result.error}"
        return execute_tool

    def validate_config(self) -> list[str]:
        errors = super().validate_config()
        if not self.config.get("system_prompt") and not self.config.get("task_template"):
            errors.append("LLMAgent requires at least 'system_prompt' or 'task_template'")
        return errors

    def get_interface(self) -> AgentInterface:
        """Return declared inputs/outputs from config if present."""
        inputs = self.config.get("inputs", {})
        outputs = self.config.get("outputs", {})
        return AgentInterface(inputs=inputs, outputs=outputs)


def _extract_structured_output(text: str) -> dict | None:
    """Best-effort JSON extraction from LLM output.

    Tries in order:
    1. Parse entire text as JSON
    2. Extract from ```json ... ``` code blocks
    3. Find first { ... } or [ ... ] in the text
    """
    if not text:
        return None

    parsed = _try_parse_json(text)
    if parsed is not None:
        return parsed

    parsed = _try_parse_code_block(text)
    if parsed is not None:
        return parsed

    return _try_parse_first_brace(text)


def _try_parse_json(text: str) -> dict | None:
    """Try parsing the entire text as JSON dict."""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _try_parse_code_block(text: str) -> dict | None:
    """Try extracting JSON from a markdown ```json ... ``` code block."""
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if not code_block:
        return None
    try:
        parsed = json.loads(code_block.group(1))
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _try_parse_first_brace(text: str) -> dict | None:
    """Try extracting the first balanced {...} substring and parsing it as JSON."""
    brace_start = text.find("{")
    if brace_start < 0:
        return None

    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return _try_parse_json(text[brace_start : i + 1])

    return None


def _truncate_input_data(input_data: dict[str, Any], max_value_len: int = 500) -> dict[str, Any]:
    """Truncate input data values for event storage.

    Keeps keys and structure but truncates long string values.
    Strips internal fields (prefixed with _).
    """
    truncated: dict[str, Any] = {}
    for key, value in input_data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, str) and len(value) > max_value_len:
            truncated[key] = value[:max_value_len] + f"... [{len(value)} chars total]"
        elif isinstance(value, dict):
            truncated[key] = _truncate_input_data(value, max_value_len)
        elif isinstance(value, list) and len(value) > 10:
            truncated[key] = value[:10]
        else:
            truncated[key] = value
    return truncated
