"""LLM service — the tool-calling loop with full observability.

Orchestrates: call LLM -> parse tool calls -> execute tools -> inject results -> repeat.
Records events at every level: LLM calls, tool calls, and iteration summaries.
"""

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from temper_ai.llm.context import (
    CONTEXT_POLICIES,
    DEFAULT_CONTEXT_POLICY,
    ContextCompressor,
    ContextError,
)
from temper_ai.llm.context import (
    estimate_messages_tokens as _estimate_messages_tokens,
)
from temper_ai.llm.fallback import FallbackTarget, is_capacity_error
from temper_ai.llm.models import CallContext, LLMResponse, LLMRunResult
from temper_ai.llm.pricing import estimate_cost
from temper_ai.llm.provider_tools import make_provider_tool_recorder
from temper_ai.llm.providers.base import BaseLLM, StreamCallback
from temper_ai.llm.response_parser import extract_final_answer, parse_tool_calls
from temper_ai.llm.tool_execution import ToolExecutorFn, execute_tool_calls
from temper_ai.observability import EventType, record

logger = logging.getLogger(__name__)


def _describe(where: dict[str, str]) -> str:
    """provider/model, and the token when the calls are pinned to one."""
    text = f"{where['provider']}/{where['model']}"
    return f"{text} on {where['token']}" if where.get("token") else text


DEFAULT_MAX_ITERATIONS = 10
# A backstop against unbounded growth, not the working limit: `max_context_tokens`
# is what governs how much the model may remember, and `_enforce_context_limit`
# applies this window only when that budget is exceeded. At 50 it was the
# governor instead — a tool-using agent lost every file it had read about 24
# calls back and went looking for it again, plateauing at a fifth of its token
# budget and never converging (one planner: three passes over the same five
# files, 27 turns apart, 1.6M tokens).
DEFAULT_MAX_MESSAGES = 400
DEFAULT_MAX_CONTEXT_TOKENS = 120_000  # Conservative default — most models handle at least 128k
# The most of one tool result that reaches the model. 20k chars (~330 lines)
# was set for an uncached loop with a 120k window, where every token in context
# was re-billed at full price every turn and small was cheap. It never fired —
# the agents learned to slice instead — and that is what it cost: a planner read
# one 2,058-line file in seven separate sed ranges, seven LLM round-trips at
# ~14 s and ~$0.06 each, when carrying the whole file costs ~$0.015 a turn at
# the cached rate. With the prompt cache on, the round-trip is the expensive
# thing and a large result is not. Overflow is still handled: the context
# limiter trims tool results further when a run is actually over budget.
MAX_TOOL_RESULT_CHARS = 200_000  # ~50k tokens
WRAP_UP_TURNS = 3  # LLM turns left at which the model is told to stop exploring (per agent: wrap_up_turns)
CANCELLED_ERROR = "Cancelled: the run was stopped"


class LLMService:
    """Orchestrates the LLM tool-calling loop.

    Calls the provider, parses tool calls, executes tools, injects results,
    and repeats until the LLM produces a final response or max iterations hit.
    Records observability events at every step.
    """

    def __init__(
        self,
        provider: BaseLLM,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        total_timeout: float = 300.0,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        context_policy: str = DEFAULT_CONTEXT_POLICY,
        wrap_up_turns: int = WRAP_UP_TURNS,
        fallbacks: list[FallbackTarget] | None = None,
        resolve_llm: Callable[[str], BaseLLM] | None = None,
        token: str | None = None,
    ) -> None:
        if context_policy not in CONTEXT_POLICIES:
            raise ValueError(
                f"context_policy must be one of {', '.join(CONTEXT_POLICIES)}, not {context_policy!r}"
            )
        self.provider = provider
        # The agent's own provider, which `provider` returns to at the start of
        # every run: a fallback lasts for the run it was needed in.
        self._own_provider = provider
        # Where a call goes when the model in use is out of capacity, in order
        # (see temper_ai.llm.fallback). `resolve_llm` turns a provider name into
        # the configured provider; without it only the agent's own provider can
        # be fallen back to.
        self.fallbacks = list(fallbacks or [])
        self._resolve_llm = resolve_llm
        # The one token the agent's own calls go out on (`token:` in its
        # config), taking them out of the provider's rotation. None rotates.
        self._own_token = token
        self._active_fallback: FallbackTarget | None = None
        self._fallback_queue: list[FallbackTarget] = []
        self._check_tokens()
        self.max_iterations = max_iterations
        # How many LLM turns before the cap the model is told to wrap up. Three
        # is enough for a reader to answer from what it has; an agent that must
        # leave a worktree in a committed state needs room to test and commit,
        # and says so in its config.
        self.wrap_up_turns = max(1, int(wrap_up_turns))
        self.max_messages = max_messages
        self.total_timeout = total_timeout  # Overall timeout for the entire run loop
        self.max_context_tokens = max_context_tokens
        # What happens when the transcript outgrows max_context_tokens — see
        # temper_ai.llm.context. "compress" (the default) hands the model ref
        # tags and a compress tool and lets it write the summaries itself;
        # "truncate" is the mechanical trim below.
        self.context_policy = context_policy

    def run(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        execute_tool: ToolExecutorFn | None = None,
        context: CallContext | None = None,
        stream_callback: StreamCallback | None = None,
        budget_check: Any | None = None,
    ) -> LLMRunResult:
        """Run the LLM tool-calling loop."""
        # Store per-run state so helpers don't need many parameters
        self._ctx = context or CallContext()
        self._record = self._ctx.event_recorder or record
        self._messages = messages
        # The context tools ride along with the agent's own. A run without
        # tools makes one provider call and returns — there is nothing to
        # compact — and a prompt that never carried tools should not start
        # carrying four: the model may answer them instead of the task, and a
        # provider that never saw a tools parameter may not accept one.
        self._compressor = (
            ContextCompressor(self.max_context_tokens)
            if self.context_policy == "compress" and tools
            else None
        )
        self._tools = (list(tools or []) + self._compressor.tools()) if self._compressor else tools
        self._execute_tool = execute_tool
        self._stream_callback = stream_callback
        self._all_tool_calls: list[dict[str, Any]] = []
        self._total_tokens = 0
        self._total_cost = 0.0
        self._response: LLMResponse | None = None
        self._run_start = time.monotonic()
        self._budget_check = budget_check
        self._usage_tracker = None
        self.provider = self._own_provider
        self._active_fallback = None
        self._fallback_queue = list(self.fallbacks)

        for iteration in range(1, self.max_iterations + 1):
            # A stopped run makes no further calls. Checked here, before every
            # call, and not only between nodes: an agent that keeps calling
            # tools can run for an hour, and until it ended on its own the only
            # way to stop it was to restart the server, which kills every run.
            if self._ctx.cancel_event is not None and self._ctx.cancel_event.is_set():
                logger.info("'%s' stopped before call %d: the run was cancelled",
                            self._ctx.agent_name, iteration)
                output = extract_final_answer(self._response) if self._response else ""
                return self._build_result(iteration - 1, output=output, error=CANCELLED_ERROR)

            # Check budget before each LLM call
            if self._budget_check:
                denial = self._budget_check()
                if denial:
                    # The policy's reason usually names the cap already, so
                    # prefixing unconditionally produced "Budget exceeded:
                    # Budget exceeded: $0.0173 >= $0.000001".
                    reason = str(denial)
                    return self._build_result(
                        iteration - 1,
                        error=reason if reason.lower().startswith("budget")
                        else f"Budget exceeded: {reason}",
                    )

            result = self._run_iteration(iteration)
            if result is not None:
                return result

        return self._build_max_iterations_result()

    def _run_iteration(self, iteration: int) -> LLMRunResult | None:
        """Run one iteration of the tool-calling loop. Returns result if done, None to continue."""
        self._iteration = iteration
        elapsed = time.monotonic() - self._run_start
        if elapsed > self.total_timeout:
            logger.warning("LLM run timeout after %.0fs for '%s'", elapsed, self._ctx.agent_name)
            return self._build_result(iteration - 1, error=f"LLM run timed out after {elapsed:.0f}s")

        llm_event_id, self._response, iter_cost = self._call_llm(iteration)
        self._total_tokens += self._response.total_tokens or 0
        self._total_cost += iter_cost

        # Report usage so budget tracking stays current between iterations
        if self._budget_check and hasattr(self, '_usage_tracker') and self._usage_tracker:
            self._usage_tracker(iter_cost, self._response.total_tokens or 0)

        tool_calls = parse_tool_calls(self._response)
        if not tool_calls:
            self._record_iteration(iteration, "final_response", 0)
            output = extract_final_answer(self._response)
            error = None
            if not output.strip() and self._response.finish_reason == "max_tokens":
                # A truncated answer arrives as an empty one. Said plainly it is
                # a configuration fault with an obvious fix; said as "empty
                # output" the node just runs the whole exploration again and is
                # truncated again at the same place.
                error = (
                    "Response hit max_tokens before any text was returned. Raise the agent's "
                    "provider_config.max_tokens."
                )
                logger.warning("'%s': %s", self._ctx.agent_name, error)
            return self._build_result(iteration, output=output, error=error)

        if self._execute_tool is None and any(not self._is_context_tool(tc["name"]) for tc in tool_calls):
            return self._handle_no_executor(iteration, tool_calls)

        self._execute_and_inject_tools(tool_calls, llm_event_id)
        self._record_iteration(
            iteration, "tool_calls", len(tool_calls), tool_calls=tool_calls,
        )
        return None  # continue loop

    def _call_llm(self, iteration: int) -> tuple[str, LLMResponse, float]:
        """Call the LLM provider and record events. Returns (event_id, response, cost).

        Cost precedence:
          0. Cached input is priced as cached when the provider reports it — a
             tool-using loop re-sends its transcript every turn, so most of a
             long run's input is a cache read at a tenth of the rate. Billing
             it as fresh input overstated these runs roughly tenfold.
          1. Provider's authoritative `raw_response.total_cost_usd` if present
             (e.g. Claude Code reports the actual Anthropic-billed cost with
             cache-read / cache-write discounts applied).
          2. Fallback to `estimate_cost()` which multiplies prompt_tokens by
             the full input rate — over-estimates when cache hits are common,
             but is the best we can do when the provider doesn't report cost.
        """
        while True:
            event_id = self._record_llm_started(iteration)
            try:
                response = self._invoke_provider(llm_event_id=event_id)
            except Exception as e:  # noqa: BLE001
                self._record_llm_failed(iteration, e)
                if is_capacity_error(e) and self._fall_back(e):
                    continue  # the same call, to the next model on the list
                raise
            return self._account_for(event_id, response, iteration)

    def _account_for(self, event_id: str, response: LLMResponse, iteration: int) -> tuple[str, LLMResponse, float]:
        """Price a completed call and record it. Returns (event_id, response, cost)."""
        try:
            raw = response.raw_response or {}
            provider_cost = raw.get("total_cost_usd")
            def estimate() -> float:
                return estimate_cost(
                    response.model, response.prompt_tokens,
                    response.completion_tokens, response.total_tokens,
                    cached_prompt_tokens=response.cached_prompt_tokens,
                    cache_write_tokens=response.cache_write_tokens,
                )

            if provider_cost is not None:
                try:
                    cost = float(provider_cost)
                except (TypeError, ValueError):
                    cost = estimate()
            else:
                cost = estimate()
            self._record_llm_completed(event_id, response, cost, iteration)
            return event_id, response, cost
        except Exception as e:  # noqa: BLE001
            self._record_llm_failed(iteration, e)
            raise

    def _invoke_provider(self, llm_event_id: str | None = None) -> LLMResponse:
        """Call the LLM provider (stream or complete).

        Applies the context policy first. Under "truncate" the transcript is
        trimmed in place when over the limit; under "compress" it is never
        touched — the provider gets a view with compressed ranges hidden and
        ref tags rendered.
        """
        if self._compressor is not None:
            # Once _nudge_to_finish has told the model to answer, the context
            # nudge stays quiet: the two would ask for different next turns.
            wire = self._compressor.prepare(
                self._messages,
                wrapping_up=self.max_iterations - self._iteration + 1 <= self.wrap_up_turns,
            )
        else:
            _enforce_context_limit(self._messages, self.max_context_tokens, self.max_messages)
            wire = self._messages
            # Debug: verify user message survived trimming
            roles = [m.get("role") for m in self._messages]
            if "user" not in roles:
                logger.error(
                    "BUG: No user message after context trimming! Roles: %s (total: %d msgs)",
                    roles[:10], len(self._messages),
                )

        kwargs: dict[str, Any] = {}
        if self._tools:
            kwargs["tools"] = self._tools
        if self._ctx.cwd:
            kwargs["cwd"] = self._ctx.cwd
        model = self._requested_model()
        if model:
            kwargs["model"] = model
        if self._ctx.session_id:
            kwargs["session_id"] = self._ctx.session_id
        # Forward (execution_id, agent_name) for provider-side token-pool
        # routing. The claude_code provider builds a sticky_key from these
        # when session_id isn't set (most non-sprint workflows) so each
        # agent within a workflow run pins to a deterministic token —
        # spreads load across the pool while keeping prompt-cache hits
        # within a single agent's calls in the same run.
        if self._ctx.execution_id:
            kwargs["execution_id"] = self._ctx.execution_id
        if self._ctx.agent_name:
            kwargs["agent_name"] = self._ctx.agent_name
        # Forward any provider-specific config from the agent YAML. Opaque to
        # the service — each provider reads whichever keys it understands and
        # ignores the rest. Named kwargs above win on collision.
        for key, value in self._provider_config().items():
            kwargs.setdefault(key, value)
        # The token the call is pinned to, if any. Set after provider_config so
        # a `token` there cannot pin a call that _check_tokens never saw.
        kwargs.pop("token", None)
        token = self._requested_token()
        if token:
            kwargs["token"] = token
        # A provider that executes tools itself (Claude Code runs Bash,
        # WebSearch and every MCP server it is given inside its own process)
        # reports each one through this callback, and it lands in the event
        # log in the same shape as a tool temper ran — otherwise a run that
        # made five MCP calls says "Tool Calls 0".
        kwargs["on_tool_event"] = make_provider_tool_recorder(
            self._record,
            execution_id=self._ctx.execution_id,
            agent_event_id=self._ctx.agent_event_id,
            agent_name=self._ctx.agent_name,
            node_path=self._ctx.node_path,
            parent_id=llm_event_id,
            provider_name=self.provider.provider_name,
        )
        if self._stream_callback:
            return self.provider.stream(wire, on_chunk=self._stream_callback, **kwargs)
        return self.provider.complete(wire, **kwargs)

    # -- fallback -----------------------------------------------------------

    def _requested_model(self) -> str | None:
        """The model this call asks for; None leaves it to the provider's default."""
        if self._active_fallback is not None:
            return self._entry_model(self._active_fallback, self.provider)
        return self._ctx.model

    def _entry_model(self, target: FallbackTarget, llm: BaseLLM) -> str | None:
        """The model a fallback entry asks for on `llm`, the provider it resolved to.

        The entry's own, when it names one. Otherwise, on the agent's own
        provider, the agent's model -- an entry naming only a token is the same
        model on another account -- and on any other provider its default: the
        agent's model would not exist there.
        """
        if target.model:
            return target.model
        return self._ctx.model if llm is self._own_provider else None

    def _model_in_use(self) -> str:
        return self._requested_model() or self.provider.model

    def _requested_token(self) -> str | None:
        """The token this call is pinned to; None lets the provider rotate.

        On a fallback it is the entry's, never the agent's: the agent's account
        is typically the one that just ran out.
        """
        if self._active_fallback is not None:
            return self._active_fallback.token
        return self._own_token

    def _where(self) -> dict[str, str]:
        """Where calls are going now, for events and logs. Names a token, never holds one."""
        where = {"provider": self.provider.provider_name, "model": self._model_in_use()}
        token = self._requested_token()
        if token:
            where["token"] = token
        return where

    def _check_tokens(self) -> None:
        """Refuse to start on a token name that cannot mean anything.

        A misspelt account would otherwise surface only when a limit is hit --
        for a fallback entry possibly days in, and then as an entry passed
        over. An entry whose provider is not configured here is left to be
        passed over when it is reached, as before.
        """
        if self._own_token:
            self._own_provider.check_token(self._own_token)
        for i, target in enumerate(self.fallbacks):
            if not target.token:
                continue
            try:
                llm = self._own_provider if target.provider is None else self._resolve(target.provider)
            except KeyError:
                continue
            try:
                llm.check_token(target.token)
            except ValueError as e:
                raise ValueError(f"fallback[{i}]: {e}") from None

    def _provider_config(self) -> dict[str, Any]:
        """The provider_config for this call.

        On the agent's own provider it is the agent's, with the active
        fallback's laid over it. On another provider it is the fallback's
        alone: the agent's was written for a provider it is no longer
        talking to, and a key both understand -- `effort`, say -- need not
        mean the same thing to both.
        """
        fallback = self._active_fallback
        config: dict[str, Any] = {}
        if self.provider is self._own_provider:
            config.update(self._ctx.provider_config or {})
        if fallback is not None and fallback.provider_config:
            config.update(fallback.provider_config)
        return config

    def _fall_back(self, exc: Exception) -> bool:
        """Move to the next usable entry of the fallback list. False when none is left.

        An entry is passed over when its provider is not configured here, or
        when the agent works with tools and the provider cannot offer them --
        running on would "succeed" without doing the work -- or when it names
        the model and token already in use, or a token already known to be
        limited for its model. The move lasts for the rest of this run:
        switching back would cost the new model's warm prompt cache, and the
        limit that caused it resets in hours or days, not between turns.
        """
        was = self._where()
        skipped: list[dict[str, str]] = []
        while self._fallback_queue:
            target = self._fallback_queue.pop(0)
            label = target.describe(self._own_provider.provider_name)
            try:
                llm = self._own_provider if target.provider is None else self._resolve(target.provider)
            except KeyError as missing:
                skipped.append({"fallback": label, "reason": f"provider not configured: {missing}"})
                continue
            if self._tools and not getattr(llm, "SUPPORTS_TOOLS", True):
                skipped.append({"fallback": label, "reason": "provider cannot offer tools"})
                continue
            model = self._entry_model(target, llm) or llm.model
            # From here the entry is named by what it would actually ask for:
            # one that names only a token is the agent's model, not a default.
            label = _describe({"provider": llm.provider_name, "model": model, "token": target.token or ""})
            if llm is self.provider and model == was["model"] and target.token == was.get("token"):
                skipped.append({"fallback": label, "reason": "already in use"})
                continue
            if target.token:
                until = llm.token_cooling_until(target.token, model)
                if until:
                    when = datetime.fromtimestamp(until, tz=UTC).strftime("%Y-%m-%d %H:%MZ")
                    skipped.append({"fallback": label,
                                    "reason": f"{target.token} is rate limited for {model} until {when}"})
                    continue
            self.provider, self._active_fallback = llm, target
            now = self._where()
            logger.warning("'%s': %s is out of capacity, falling back to %s: %s",
                           self._ctx.agent_name, _describe(was), _describe(now), str(exc)[:200])
            self._record_fallback(was, now, exc, skipped)
            return True
        logger.error("'%s': %s is out of capacity and no fallback is left%s",
                     self._ctx.agent_name, _describe(was),
                     f" ({len(skipped)} passed over)" if skipped else "")
        if self.fallbacks:
            self._record_fallback(was, None, exc, skipped)
        return False

    def _resolve(self, provider_name: str) -> BaseLLM:
        if self._resolve_llm is None:
            raise KeyError(provider_name)
        return self._resolve_llm(provider_name)

    def _record_fallback(self, was: dict, now: dict | None, exc: Exception,
                         skipped: list[dict[str, str]]) -> None:
        self._record(
            EventType.LLM_FALLBACK, parent_id=self._ctx.agent_event_id,
            execution_id=self._ctx.execution_id,
            status="completed" if now else "failed",
            data={"agent_name": self._ctx.agent_name, "node_path": self._ctx.node_path,
                  "iteration": self._iteration, "from": was, "to": now,
                  "reason": str(exc)[:500], "error_type": type(exc).__name__,
                  "skipped": skipped, "remaining": len(self._fallback_queue)})

    def _is_context_tool(self, name: str) -> bool:
        return self._compressor is not None and self._compressor.handles(name)

    def _execute_and_inject_tools(self, tool_calls: list[dict], llm_event_id: str) -> None:
        """Execute tools, track results, inject into messages.

        Context tools (compress, decompress, …) never reach the tool executor:
        they act on this service's own transcript, so they run here, through
        the same recording path as any other tool so every summary the model
        writes is in the event log.
        """
        assert self._response is not None  # noqa: B101
        tool_results: list[dict] = []
        for tc in tool_calls:
            executor = self._context_tool_runner(tc) if self._is_context_tool(tc["name"]) else self._execute_tool
            assert executor is not None  # noqa: B101
            tool_results.extend(execute_tool_calls(
                tool_calls=[tc], execute_tool=executor,
                context=self._ctx, llm_call_event_id=llm_event_id,
            ))
        for tc, tr in zip(tool_calls, tool_results, strict=False):
            self._all_tool_calls.append({
                "name": tc["name"], "arguments": tc["arguments"],
                "result": tr["result"], "success": tr["success"],
            })
        _inject_tool_results(self._messages, self._response, tool_calls, tool_results)
        _nudge_to_finish(self._messages, self._iteration, self.max_iterations, self.wrap_up_turns)
        # No window here: _enforce_context_limit runs before every provider call
        # and trims by token budget, which is the measure that matters. Trimming
        # by message count after every tool round threw away work the model was
        # nowhere near out of room to keep.

    def _context_tool_runner(self, tc: dict) -> ToolExecutorFn:
        """An executor for one context tool call, bound to this transcript."""
        assert self._compressor is not None  # noqa: B101
        compressor = self._compressor

        def run(name: str, arguments: dict) -> str:
            try:
                return compressor.execute(name, arguments, self._messages, tool_call_id=tc["id"])
            except ContextError as e:
                # A bad range is the model's mistake to correct, not a failure
                # of the run: hand the reason back as the tool result.
                return f"Error: {e}"

        return run

    def _handle_no_executor(self, iteration: int, tool_calls: list[dict]) -> LLMRunResult:
        """Handle case where LLM requests tools but no executor is available."""
        logger.error("LLM returned %d tool calls but no execute_tool provided", len(tool_calls))
        self._record(EventType.LLM_NO_EXECUTOR, parent_id=self._ctx.agent_event_id,
                     execution_id=self._ctx.execution_id, status="failed",
                     data={"agent_name": self._ctx.agent_name, "iteration": iteration,
                           "tool_calls_requested": [tc["name"] for tc in tool_calls]})
        return self._build_result(iteration, error="Tool calls requested but no tool executor available")

    def _build_result(self, iterations: int, output: str = "", error: str | None = None) -> LLMRunResult:
        return LLMRunResult(output=output, tool_calls=self._all_tool_calls,
                            tokens=self._total_tokens, cost=round(self._total_cost, 6),
                            iterations=iterations, error=error)

    def _build_max_iterations_result(self) -> LLMRunResult:
        logger.warning("Hit max iterations (%d) for '%s'", self.max_iterations, self._ctx.agent_name)
        self._record(EventType.LLM_MAX_ITERATIONS, parent_id=self._ctx.agent_event_id,
                     execution_id=self._ctx.execution_id, status="failed",
                     data={"agent_name": self._ctx.agent_name, "max_iterations": self.max_iterations,
                           "total_tokens": self._total_tokens, "total_cost": round(self._total_cost, 6)})
        output = extract_final_answer(self._response) if self._response else ""
        return self._build_result(self.max_iterations, output=output,
                                  error=f"Reached max iterations ({self.max_iterations})")

    def _record_llm_started(self, iteration: int) -> str:
        return self._record(
            EventType.LLM_CALL_STARTED, parent_id=self._ctx.agent_event_id,
            execution_id=self._ctx.execution_id, status="running",
            data={"agent_name": self._ctx.agent_name, "node_path": self._ctx.node_path,
                  "model": self._model_in_use(), "provider": self.provider.provider_name,
                  "token": self._requested_token(),
                  "temperature": self.provider.temperature, "max_tokens": self.provider.max_tokens,
                  "iteration": iteration, "message_count": len(self._messages),
                  "messages": self._messages,
                  "tools_available": len(self._tools) if self._tools else 0,
                  "streaming": self._stream_callback is not None})

    def _record_llm_completed(self, event_id: str, response: LLMResponse, cost: float, iteration: int) -> None:
        self._record(
            EventType.LLM_CALL_COMPLETED, parent_id=self._ctx.agent_event_id,
            execution_id=self._ctx.execution_id, status="completed",
            data={"model": response.model, "prompt_tokens": response.prompt_tokens,
                  "completion_tokens": response.completion_tokens, "total_tokens": response.total_tokens,
                  # Recorded so a run's bill can be read back: without these a
                  # cached loop and an uncached one look identical in the log.
                  "cached_prompt_tokens": response.cached_prompt_tokens,
                  "cache_write_tokens": response.cache_write_tokens,
                  "latency_ms": response.latency_ms, "finish_reason": response.finish_reason,
                  "cost_usd": cost, "has_tool_calls": bool(response.tool_calls),
                  "tool_calls_requested": [{"name": tc.get("name"), "id": tc.get("id")}
                                           for tc in (response.tool_calls or [])] or None,
                  "iteration": iteration, "response_content": response.content,
                  "reasoning": response.reasoning,
                  "context": self._context_sent()})

    def _context_sent(self) -> dict[str, Any]:
        """The harness's side of the call just made: which context policy
        applied and, under compress, what the model was actually sent — how
        full the view was, whether it was asked to compress, what was hidden.
        `policy` is the one that applied, so `truncate` also for a compress
        agent that ran without tools.
        """
        if self._compressor is None or self._compressor.sent is None:
            return {"policy": "truncate"}
        sent = self._compressor.sent
        return {
            "policy": "compress", "limit": self.max_context_tokens, "tokens": sent.tokens,
            "nudged": sent.nudged, "hid": list(sent.hid), "blocks": sent.blocks,
            "hidden": sent.hidden, "wrapping_up": sent.wrapping_up,
        }

    def _record_llm_failed(self, iteration: int, exc: Exception) -> None:
        self._record(
            EventType.LLM_CALL_FAILED, parent_id=self._ctx.agent_event_id,
            execution_id=self._ctx.execution_id, status="failed",
            data={"model": self._model_in_use(), "provider": self.provider.provider_name,
                  "token": self._requested_token(),
                  "iteration": iteration, "error_type": type(exc).__name__,
                  "error": str(exc)[:500], "agent_name": self._ctx.agent_name})

    def _record_iteration(
        self,
        iteration: int,
        action: str,
        tool_count: int,
        tool_calls: list[dict] | None = None,
    ) -> None:
        """Record an iteration summary event.

        When tool_calls are provided, capture name + truncated arguments so
        forensic consumers (JSONL log readers, post-run analysis scripts)
        can reconstruct what each agent actually invoked. Without this, the
        event-store loses the call detail — only the count survives, and
        the rich detail in Redis Stream chunks ages out via TTL.
        """
        data: dict[str, Any] = {
            "agent_name": self._ctx.agent_name,
            "node_path": self._ctx.node_path,
            "iteration": iteration,
            "action": action,
            "tool_count": tool_count,
            "total_tokens_so_far": self._total_tokens,
        }
        if tool_calls:
            data["tool_calls"] = [_summarize_tool_call(tc) for tc in tool_calls]
        self._record(
            EventType.LLM_ITERATION,
            parent_id=self._ctx.agent_event_id,
            execution_id=self._ctx.execution_id,
            data=data,
        )


def _summarize_tool_call(tc: dict) -> dict:
    """Compact representation of a tool call for forensic event logs.

    Keeps the name + id (so consumers can correlate with stream chunks) and
    a JSON-serialized + truncated `arguments` blob. Truncation matters: a
    single Bash tool_call can carry tens of KB of file content (Edit/Write
    tools), and we don't want every iteration event in the JSONL log to
    blow past line-buffer thresholds. The full content remains available
    in the Redis chunk stream for live debugging.
    """
    name = tc.get("name") or tc.get("tool_name") or "?"
    args = tc.get("arguments")
    try:
        args_repr = json.dumps(args, default=str)
    except (TypeError, ValueError):
        args_repr = repr(args)
    if len(args_repr) > 1000:
        args_repr = args_repr[:1000] + "…(truncated)"
    return {"name": name, "id": tc.get("id"), "arguments": args_repr}


def _inject_tool_results(
    messages: list[dict],
    response: LLMResponse,
    tool_calls: list[dict],
    tool_results: list[dict],
) -> None:
    """Append the assistant's tool-call message and tool result messages."""
    # Assistant message with tool calls (OpenAI format)
    assistant_msg: dict[str, Any] = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": (
                        json.dumps(tc["arguments"])
                        if isinstance(tc["arguments"], dict)
                        else str(tc["arguments"])
                    ),
                },
            }
            for tc in tool_calls
        ],
    }
    # Always include content field — some models (Qwen3, Kimi K2) mishandle
    # tool-call messages without an explicit content field, causing tool-calling loops.
    assistant_msg["content"] = response.content or ""
    messages.append(assistant_msg)

    # One tool-result message per tool call (truncate large results)
    for tr in tool_results:
        content = tr["result"]
        if len(content) > MAX_TOOL_RESULT_CHARS:
            content = content[:MAX_TOOL_RESULT_CHARS] + f"\n\n... [truncated from {len(tr['result'])} chars]"
        messages.append({
            "role": "tool",
            "tool_call_id": tr["tool_call_id"],
            "content": content,
        })


def _nudge_to_finish(
    messages: list[dict], iteration: int, max_iterations: int, wrap_up_turns: int = WRAP_UP_TURNS,
) -> None:
    """Tell the model the iteration budget is nearly spent, on the last tool result.

    Without this a model that is still reading at the cap is cut off with no
    answer at all — the whole exploration is lost (seen live: a planner spent
    40 iterations and 570k tokens and returned nothing). Appended to the tool
    result rather than as a user message so the transcript stays a valid
    tool-call sequence for every provider.

    ``wrap_up_turns`` is how early the first warning comes. The default suits
    an agent that answers from what it has read; one whose answer is a
    committed worktree is warned earlier (seen live: an implementer told at
    three turns left replied with twenty files uncommitted, and the deploy
    step refused the dirty tree).
    """
    left = max_iterations - iteration  # LLM calls that can still happen
    if left > wrap_up_turns or left < 1 or not messages or messages[-1].get("role") != "tool":
        return
    if left == 1:
        note = "Your next reply is the last one the iteration budget allows. It must be your final answer, with no tool calls."
    elif left > WRAP_UP_TURNS:
        # An early warning, asked for by the agent's config: the turns left are
        # for finishing what is in hand (test, commit), not for starting more.
        note = (
            f"You have {left} LLM turns left before the iteration budget ({max_iterations}) is spent. "
            "Start nothing new; use them to bring what is in hand to a state you can hand over, then reply."
        )
    else:
        note = (
            f"You have {left} LLM turns left before the iteration budget ({max_iterations}) is spent. "
            "Stop exploring and produce your final answer now, from what you already know."
        )
    messages[-1]["content"] = f"{messages[-1]['content']}\n\n[iteration budget] {note}"


def _enforce_context_limit(messages: list[dict], max_tokens: int, max_messages: int) -> None:
    """Trim messages to stay under the context token limit.

    Strategy (in order):
    1. Apply message window (keep system + recent N)
    2. Truncate large tool results to 5000 chars
    3. If still over, truncate tool results to 2000 chars
    4. If still over, apply tighter message window (keep system + last 10)
    """
    est = _estimate_messages_tokens(messages)
    if est <= max_tokens:
        return

    # Step 1: apply normal message window
    _apply_message_window(messages, max_messages)
    est = _estimate_messages_tokens(messages)
    if est <= max_tokens:
        return

    # Step 2: truncate large tool results
    _truncate_tool_results(messages, 5000)
    est = _estimate_messages_tokens(messages)
    if est <= max_tokens:
        return

    # Step 3: more aggressive truncation
    _truncate_tool_results(messages, 2000)
    est = _estimate_messages_tokens(messages)
    if est <= max_tokens:
        return

    # Step 4: tight message window
    _apply_message_window(messages, 10)
    _truncate_tool_results(messages, 1000)

    est = _estimate_messages_tokens(messages)
    if est > max_tokens:
        logger.warning(
            "Context still exceeds limit after all trimming: ~%d tokens (limit %d). "
            "Proceeding anyway — provider may reject.",
            est, max_tokens,
        )


def _truncate_tool_results(messages: list[dict], max_chars: int) -> None:
    """Truncate tool result message content to max_chars."""
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("content"):
            content = msg["content"]
            if len(content) > max_chars:
                msg["content"] = content[:max_chars] + f"\n\n... [truncated from {len(content)} chars]"


def _apply_message_window(messages: list[dict], max_messages: int) -> None:
    """Keep the first message (system prompt) and the most recent messages.

    Prevents unbounded message growth in long tool-calling loops.
    Ensures tool-call pairs (assistant + tool results) are never split,
    which would cause the API to reject orphaned tool_call_ids.
    """
    if len(messages) <= max_messages:
        return

    # Keep system + first user message (required by chat templates) + recent tail
    # Find the first user message index
    first_user_idx = next((i for i, m in enumerate(messages) if m.get("role") == "user"), None)
    prefix_end = (first_user_idx + 1) if first_user_idx is not None else 1
    prefix = messages[:prefix_end]

    tail = messages[-(max_messages - prefix_end):]

    # If tail starts with orphaned tool result messages, skip them
    # to find a clean turn boundary
    start = 0
    while start < len(tail) and tail[start].get("role") == "tool":
        start += 1

    keep = prefix + tail[start:]
    messages.clear()
    messages.extend(keep)
