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
from temper_ai.llm.service import LLMService
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

        # Record agent start (parent_event_id links to the node event in the graph)
        _record = context.event_recorder.record if context.event_recorder else _default_record
        agent_event_id = _record(
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

        try:
            result = self._execute(input_data, context, agent_event_id)

            # Record agent completion
            duration = time.monotonic() - start
            result.duration_seconds = round(duration, 3)
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
            return result

        except Exception as e:  # noqa: broad-except
            duration = time.monotonic() - start
            _record(
                EventType.AGENT_FAILED,
                parent_id=agent_event_id,
                execution_id=context.run_id,
                status="failed",
                data={
                    "agent_name": self.name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "duration_seconds": round(duration, 3),
                },
            )
            return AgentResult(
                status=Status.FAILED,
                output="",
                error=str(e),
                duration_seconds=round(duration, 3),
            )

    def _execute(
        self,
        input_data: dict,
        context: ExecutionContext,
        agent_event_id: str,
    ) -> AgentResult:
        """Core execution logic, separated for clean error handling."""
        # 1. Recall memories
        memories = self._recall_memories(context)

        # 2. Render prompt
        messages = self.prompt_renderer.render(
            agent_config=self.config,
            input_data=input_data,
            memories=memories,
            strategy_context=input_data.get("_strategy_context"),
            token_budget=self.token_budget,
        )

        # 3. Get LLM from context
        llm = context.get_llm(self.provider)

        # 4. LLM call with tool loop
        llm_service = LLMService(
            provider=llm,
            max_iterations=self.max_iterations,
        )

        call_context = CallContext(
            execution_id=context.run_id,
            agent_event_id=agent_event_id,
            agent_name=self.name,
            node_path=context.node_path,
            event_recorder=(
                context.event_recorder.record if context.event_recorder else None
            ),
        )

        tools = self._get_tools(context)
        execute_tool = self._make_tool_executor(context) if tools else None

        # Wire stream callback: broadcast LLM tokens via WebSocket in real-time
        stream_cb = context.stream_callback
        if not stream_cb and hasattr(context.event_recorder, 'broadcast_stream_chunk'):
            stream_cb = self._make_stream_callback(context, agent_event_id)

        llm_result: LLMRunResult = llm_service.run(
            messages=messages,
            tools=tools or None,
            execute_tool=execute_tool,
            context=call_context,
            stream_callback=stream_cb,
        )

        # 5. Track usage for budget policy enforcement
        if context.tool_executor and hasattr(context.tool_executor, 'track_usage'):
            context.tool_executor.track_usage(
                cost_usd=llm_result.cost,
                tokens=llm_result.tokens,
            )

        # 6. Extract structured output (best-effort)
        structured = _extract_structured_output(llm_result.output)

        # 6. Store to memory
        memories_formed = self._store_memories(llm_result.output, context)

        # 7. Build AgentResult
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
        def execute_tool(tool_name: str, params: dict[str, Any]) -> Any:
            result = context.tool_executor.execute(
                tool_name,
                params,
                context={
                    "parent_id": None,
                    "execution_id": context.run_id,
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

    # Try 1: Full text is valid JSON
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    # Try 2: Extract from markdown code blocks
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if code_block:
        try:
            parsed = json.loads(code_block.group(1))
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # Try 3: Find first {...} in text
    brace_start = text.find("{")
    if brace_start >= 0:
        # Find matching closing brace
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[brace_start : i + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except (json.JSONDecodeError, TypeError):
                        pass
                    break

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
