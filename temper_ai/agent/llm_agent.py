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
from temper_ai.agent.exceptions import ToolsNotRegisteredError
from temper_ai.llm.context import DEFAULT_CONTEXT_POLICY
from temper_ai.llm.fallback import parse_fallback, parse_token
from temper_ai.llm.models import CallContext, LLMRunResult
from temper_ai.llm.prompt_renderer import PromptRenderer
from temper_ai.llm.service import (
    DEFAULT_MAX_CONTEXT_TOKENS,
    DEFAULT_MAX_MESSAGES,
    WRAP_UP_TURNS,
    LLMService,
)
from temper_ai.observability import EventType
from temper_ai.observability import record as _default_record
from temper_ai.shared.types import (
    AgentInterface,
    AgentResult,
    ExecutionContext,
    Status,
    TokenUsage,
)

DEFAULT_TOTAL_TIMEOUT = 300.0

logger = logging.getLogger(__name__)


class LLMAgent(AgentABC):
    """Agent that uses LLM with Jinja2 prompt templates, tools, and memory."""

    def __init__(self, config: dict):
        super().__init__(config)
        # None means "whatever is configured" (resolved per run by the
        # execution context). Defaulting to openai here made every shipped
        # workflow fail on an install without an OpenAI key.
        self.provider = config.get("provider") or None
        self.model = config.get("model") or None
        # Where a call goes when this agent's model is out of capacity
        # (temper_ai.llm.fallback). A malformed list fails here, before any
        # call is made, rather than on the day a limit is finally hit.
        self.fallbacks = parse_fallback(config.get("fallback"))
        # The one token this agent's calls go out on -- an account name, or
        # the variable holding it -- instead of the provider's rotation.
        self.token = parse_token(config.get("token"))
        self.max_iterations = config.get("max_iterations", 10)
        # Default to None (no budget enforcement) rather than 8000. The 8000
        # default was silently truncating LLM inputs to ~1000 chars per field
        # via prompt_renderer, breaking agents (e.g. planners/allocators) whose
        # inputs legitimately span tens of thousands of tokens. If budget
        # enforcement is wanted, opt in explicitly via config; the default is
        # "send what you've got."
        self.token_budget = config.get("token_budget", None)
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

        except Exception as e:  # noqa: BLE001
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
                    "system_prompt": self.config.get("system_prompt", ""),
                    "task_template": self.config.get("task_template", ""),
                    "tools": self.config.get("tools", []),
                    "memory": self.config.get("memory"),
                },
            },
        )

    def _record_agent_completed(self, _record, result, agent_event_id: str, context: ExecutionContext) -> None:
        """Emit the agent's terminal event, completed or failed.

        An agent can finish without raising and still have failed — a
        budget policy denying the call is the usual way. Recording that as
        AGENT_COMPLETED/completed left the run showing a node that failed
        for no stated reason: empty output, no error, nothing in the UI to
        explain why. The result's own status decides.
        """
        failed = getattr(result, "status", None) == Status.FAILED or bool(result.error)
        _record(
            EventType.AGENT_FAILED if failed else EventType.AGENT_COMPLETED,
            parent_id=agent_event_id,
            execution_id=context.run_id,
            status="failed" if failed else "completed",
            data={
                "agent_name": self.name,
                **({"error": result.error} if result.error else {}),
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

        # Same as for script agents: `{{ workspace_path }}` in a prompt or
        # task_template should resolve to the run's workspace rather than
        # silently rendering empty.
        render_input = dict(input_data)
        if context.workspace_path and not render_input.get("workspace_path"):
            render_input["workspace_path"] = context.workspace_path

        messages = self.prompt_renderer.render(
            agent_config=self.config,
            input_data=render_input,
            memories=memories,
            strategy_context=input_data.get("_strategy_context"),
            token_budget=self.token_budget,
        )

        llm_service = self._build_llm_service(context)
        call_context = self._build_call_context(context, agent_event_id, input_data)

        tools = self._get_tools(context)
        execute_tool = self._make_tool_executor(context, input_data) if tools else None

        # An agent that declares tools against a provider that cannot offer
        # them runs without them and still reports success — a workflow
        # whose whole job is to delegate or mutate the graph then completes
        # having done nothing of the sort.
        if tools and not getattr(llm_service.provider, "SUPPORTS_TOOLS", True):
            declared = [t.get("name") or t.get("function", {}).get("name") for t in tools]
            message = (
                f"provider '{getattr(llm_service.provider, 'PROVIDER_NAME', '?')}' "
                f"does not support tool calls; {declared} were not offered to the model"
            )
            logger.warning("Agent '%s': %s", self.name, message)
            record = (
                context.event_recorder.record if context.event_recorder else None
            )
            if record:
                record(
                    EventType.LLM_NO_EXECUTOR,
                    parent_id=agent_event_id,
                    execution_id=context.run_id,
                    status="skipped",
                    data={"agent_name": self.name, "tools_unavailable": declared,
                          "reason": message},
                )

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

        # Wire usage tracker so budget stays current between LLM iterations.
        # _usage_tracker is declared None by default; attaching a callable here
        # is the documented hook, so we ignore the type reassignment.
        if budget_check and te:
            llm_service._usage_tracker = lambda cost, tokens: te.track_usage(cost, tokens)  # type: ignore[assignment]

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

        structured, parse_error, repaired = _extract_structured_output_detailed(llm_result.output)
        cost, tokens, iterations = llm_result.cost, llm_result.tokens, llm_result.iterations
        metadata: dict = {}
        if repaired:
            self._record_output_event(
                context, agent_event_id, EventType.AGENT_OUTPUT_REPAIRED,
                "completed", parse_error, "repaired",
            )
        elif structured is None and parse_error and not llm_result.error:
            # Almost-JSON the quote repair could not save: one more turn to
            # correct it, rather than an answer silently stored as null.
            retry_msgs = list(messages) + [
                {"role": "assistant", "content": llm_result.output},
                {"role": "user", "content": (
                    f"Your last answer wasn't valid JSON: `{parse_error}`. "
                    "Reply with only the corrected JSON."
                )},
            ]
            retry_result: LLMRunResult = llm_service.run(
                messages=retry_msgs,
                tools=None,
                execute_tool=None,
                context=call_context,
                budget_check=budget_check,
            )
            if context.tool_executor and hasattr(context.tool_executor, 'track_usage'):
                context.tool_executor.track_usage(
                    cost_usd=retry_result.cost,
                    tokens=retry_result.tokens,
                )
            cost += retry_result.cost
            tokens += retry_result.tokens
            iterations += retry_result.iterations
            retried, retry_error, _ = (
                (None, retry_result.error, False) if retry_result.error
                else _extract_structured_output_detailed(retry_result.output)
            )
            if retried is not None:
                structured = retried
                self._record_output_event(
                    context, agent_event_id, EventType.AGENT_OUTPUT_RETRY,
                    "completed", parse_error, "retry_ok",
                )
            else:
                metadata["structured_parse_error"] = retry_error or parse_error
                self._record_output_event(
                    context, agent_event_id, EventType.AGENT_OUTPUT_RETRY,
                    "failed", parse_error, "retry_failed",
                )
        memories_formed = self._store_memories(llm_result.output, context)

        return AgentResult(
            status=Status.FAILED if llm_result.error else Status.COMPLETED,
            output=llm_result.output,
            structured_output=structured,
            tokens=TokenUsage(total_tokens=tokens),
            cost_usd=cost,
            memories_formed=memories_formed,
            error=llm_result.error,
            llm_calls=iterations,
            tool_calls=len(llm_result.tool_calls),
            metadata=metadata,
        )

    def _record_output_event(
        self,
        context: ExecutionContext,
        agent_event_id: str,
        event_type: EventType,
        status: str,
        parse_error: str | None,
        outcome: str,
    ) -> None:
        """Record a repair or retry of the agent's JSON answer, with the original parse error."""
        logger.warning(
            "Agent '%s': structured output %s (parse error: %s)", self.name, outcome, parse_error,
        )
        if not context.event_recorder:
            return
        context.event_recorder.record(
            event_type,
            parent_id=agent_event_id,
            execution_id=context.run_id,
            status=status,
            data={"agent_name": self.name, "parse_error": parse_error, "outcome": outcome},
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
            context_policy=self.config.get("context_policy", DEFAULT_CONTEXT_POLICY),
            # How many turns before max_iterations the model is told to wrap up
            # (default 3). An agent whose reply must leave a committed worktree
            # sets this higher: it needs turns to test and commit, not just to answer.
            wrap_up_turns=int(self.config.get("wrap_up_turns", WRAP_UP_TURNS)),
            fallbacks=self.fallbacks,
            token=self.token,
            # A fallback names its provider; an unconfigured one raises KeyError,
            # and the service passes that entry over.
            resolve_llm=context.get_llm,
        )

    def _build_call_context(
        self, context: ExecutionContext, agent_event_id: str, input_data: dict | None = None,
    ) -> CallContext:
        """Build the CallContext for LLMService observability."""
        # Use workspace_path from input_data as cwd for providers that need it (Claude Code)
        cwd = (input_data or {}).get("workspace_path") or context.workspace_path
        session_id = (input_data or {}).get("session_id")
        return CallContext(
            execution_id=context.run_id,
            agent_event_id=agent_event_id,
            agent_name=self.name,
            node_path=context.node_path,
            event_recorder=(
                context.event_recorder.record if context.event_recorder else None
            ),
            cwd=cwd,
            model=self.model,
            session_id=session_id,
            # Opaque provider-specific config passed through to the LLM
            # provider. Agent YAML opts in via `provider_config: {...}`.
            # Core doesn't know what keys mean — the provider does.
            provider_config=self.config.get("provider_config"),
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

    def _declared_tools(self) -> list[str]:
        """Tool names this agent's config declares.

        The single source of truth for BOTH what the model is shown (_get_tools)
        and what it may execute (the executor view from _scoped_executor) — read
        in one place so the two can never disagree. Entries are bare names or
        ``{name: ..., config: ...}`` (the loader's spec form).
        """
        names: list[str] = []
        for spec in self.config.get("tools", []) or []:
            if isinstance(spec, str):
                name = spec
            elif isinstance(spec, dict):
                name = str(spec.get("name") or "")
            else:
                name = str(getattr(spec, "name", "") or "")
            if name:
                names.append(name)
        return names

    def _get_tools(self, context: ExecutionContext) -> list[dict[str, Any]]:
        """Get tool schemas for tools configured on this agent."""
        tool_names = self._declared_tools()
        te = context.tool_executor
        if not tool_names or not te:
            return []

        schemas = []
        missing = []
        for name in tool_names:
            tool = te.get_tool(name)
            if tool:
                schemas.append(tool.to_llm_schema())
            else:
                missing.append(name)
        if missing:
            # A warning was not enough. An agent that asked for a browser and
            # was handed nothing still answered: it described three user walks
            # through a product it had never loaded, in the voice of someone
            # who had, and the run recorded them as evidence. Whatever is
            # missing, the agent cannot do the job it was configured to do,
            # and the cheapest moment to say so is before the first token.
            raise ToolsNotRegisteredError(
                f"Agent '{self.name}' is configured with {len(missing)} tool(s) that are "
                f"not registered: {', '.join(missing)}.\n"
                f"Registered here: {', '.join(te.tool_names()) or '(none)'}\n"
                f"An MCP tool (name.tool) is bound from the agent configs a run collects "
                f"before it starts; a nested agent's tools are only found if the collector "
                f"walks into stages (Node.agent_configs)."
            )
        return schemas

    def _make_tool_executor(self, context: ExecutionContext, input_data: dict | None = None):
        """Create a tool executor function compatible with LLMService.

        Binds the execution context to any declared tool that has
        ``bind_context`` (Delegate runs sub-agents, QueryRunState reads live
        node_outputs, …), then returns the callback the model's tool calls go
        through.

        Every call also names this node's workspace — its ``workspace_path``
        input (a worktree another node made, mapped in the workflow), else the
        run's. The executor confines the tools to it; the same value is the cwd
        the Claude Code provider gets (see _build_call_context), so what the
        model reads and writes is the same tree whichever way it works.

        Every call declares this agent's tools, so the executor refuses a name
        the agent did not declare — _get_tools only controls what the model is
        *shown*, and a name it was not shown can still reach it (hallucinated, or
        planted in a tool result). Shown and declared come from the same
        ``_declared_tools()``, so they cannot drift. Nothing is written back into
        ``context``: Delegate copies it to sub-agents that declare their own
        tools, and ScriptAgent declares its own.

        The model answers with the name it was shown, which for an MCP tool is
        not the name anything here uses (``playwright__browser_navigate`` on the
        wire, ``playwright.browser_navigate`` in configs and the registry — see
        BaseTool.llm_name). The map back is built from the same declared list, so
        a tool that was never shown has no way in through it either.
        """
        te = context.tool_executor
        allowed = tuple(self._declared_tools())
        workspace = _node_workspace(input_data, context)
        by_llm_name: dict[str, str] = {}
        if te is not None:
            for tool_name in allowed:
                tool = te.get_tool(tool_name)
                if tool is None:
                    continue
                if hasattr(tool, "bind_context"):
                    tool.bind_context(context)
                wire = getattr(tool, "llm_name", tool_name)
                if wire != tool_name:
                    by_llm_name[wire] = tool_name

        def execute_tool(tool_name: str, params: dict[str, Any]) -> Any:
            # A leading underscore marks a parameter the harness sets and a model never
            # does: `_skip_allowlist` is how a script agent's author-written command
            # skips the command allowlist and earns the longer script timeout
            # (tools/bash.py). The schema a model is shown does not offer it, but a
            # model can still send it, and Bash.execute(**params) would honour it.
            if isinstance(params, dict):
                params = {k: v for k, v in params.items() if not str(k).startswith("_")}
            result = te.execute(
                by_llm_name.get(tool_name, tool_name),
                params,
                allowed_tools=allowed,
                workspace=workspace,
                context={
                    "parent_id": None,
                    "execution_id": context.run_id,
                    "skip_policies": context.skip_policies,
                    "agent_name": self.name,
                    # Which instance, not which config: two nodes can run this
                    # same agent at the same time, and a tool with per-caller
                    # state (an MCP browser session) must not be shared between
                    # them. See tools/executor.caller_key.
                    "node_path": context.node_path,
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


def _node_workspace(input_data: dict | None, context: ExecutionContext) -> str | None:
    """The directory a node's tools work in: its ``workspace_path`` input, else the run's."""
    own = (input_data or {}).get("workspace_path")
    if isinstance(own, str) and own.strip():
        return own.strip()
    return context.workspace_path or None


def _extract_structured_output(text: str) -> dict | None:
    """Best-effort JSON extraction from LLM output.

    Tries in order:
    1. Parse entire text as JSON
    2. Extract from ```json ... ``` code blocks
    3. Find first { ... } or [ ... ] in the text
    4. The same three again after escaping stray quotes inside strings
    """
    return _extract_structured_output_detailed(text)[0]


def _extract_structured_output_detailed(text: str) -> tuple[dict | None, str | None, bool]:
    """Extract a JSON dict from LLM output, saying why when it cannot.

    Returns ``(parsed, parse_error, repaired)``. ``parse_error`` is the last
    ``json.loads`` message when the text looked like JSON and did not parse
    (None when there was nothing JSON-shaped to try, or when it parsed).
    ``repaired`` is True when the dict came back only after
    ``_repair_unescaped_quotes``. The b012 checker wrote
    ``"notes": "total shows "−$120.00" not +$120"``, and dropping the whole
    answer for two quotes ended its loop without a verdict.
    """
    if not text:
        return None, None, False

    candidates = _json_candidates(text)
    errors: list[str] = []
    for candidate in candidates:
        parsed = _try_parse_json(candidate, errors)
        if parsed is not None:
            return parsed, None, False
    if not errors:
        # Valid JSON that is not a dict (e.g. a list), or nothing JSON-shaped.
        return None, None, False

    for candidate in candidates:
        repaired = _repair_unescaped_quotes(candidate)
        if repaired == candidate:
            continue
        parsed = _try_parse_json(repaired, [])
        if parsed is not None:
            return parsed, errors[0], True
    return None, errors[-1], False


def _json_candidates(text: str) -> list[str]:
    """The substrings that look like a JSON object: whole text, fence body, first balanced brace.

    Only these count as "looked like JSON": prose with no object in it has no
    parse error to report, and must not cost a retry turn.
    """
    found = [text, _code_block_body(text), _first_brace_span(text)]
    return [c for c in found if c is not None and c.strip().startswith("{")]


def _repair_unescaped_quotes(s: str) -> str:
    """Escape straight quotes inside JSON strings that do not close them.

    Inside a string, a ``"`` closes it only when the next non-space character
    is one of ``, : } ]`` or the end of the text; any other ``"`` is taken as
    part of the value and becomes ``\\"``. Existing ``\\`` escapes are kept.
    This is the only repair: trailing commas, single quotes and the like are
    left for the retry turn.
    """
    out: list[str] = []
    in_string = False
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if not in_string:
            if ch == '"':
                in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(s[i : i + 2])
            i += 2
            continue
        if ch == '"':
            rest = s[i + 1 :].lstrip()
            if not rest or rest[0] in ",:}]":
                in_string = False
                out.append(ch)
            else:
                out.append('\\"')
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _try_parse_json(text: str, errors: list[str] | None = None) -> dict | None:
    """Try parsing the entire text as JSON dict; a decode error is appended to ``errors``."""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError as exc:
        if errors is not None:
            errors.append(str(exc))
    except TypeError:
        pass
    return None


def _code_block_body(text: str) -> str | None:
    """The body of the first markdown ```json ... ``` code block, if any."""
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    return code_block.group(1) if code_block else None


def _first_brace_span(text: str) -> str | None:
    """The first balanced {...} substring of the text, if any."""
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
                return text[brace_start : i + 1]

    return None


def _truncate_input_data(input_data: dict[str, Any], max_value_len: int = 200_000) -> dict[str, Any]:
    """Sanitize input data values for event storage.

    Bumped from 500 chars to 200k (2026-05-01). The 500-char cap was making
    the temper workflow API near-useless for debugging anything with
    realistic JSON inputs — a 28k-token allocator prompt would show as
    `{"places_by_city_json": "{... [34491 chars total]"}` in the API
    response, blocking any post-mortem analysis. 200k matches a reasonable
    upper bound for inputs we'd realistically pass; truly enormous
    payloads still get clipped so the event store doesn't blow up.

    Strips internal fields (prefixed with _). List clipping (>10 items)
    kept as-is for the same reason — most lists are short and a 10-item
    sample is enough for debugging.
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
