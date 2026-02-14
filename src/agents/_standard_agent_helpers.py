"""Helper functions extracted from StandardAgent to reduce class size.

These are internal implementation details and should not be imported directly.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from src.agents.standard_agent import StandardAgent

from src.agents.constants import (
    ERROR_MSG_TOOL_PREFIX,
    FALLBACK_UNKNOWN_VALUE,
    OUTPUT_PREVIEW_LENGTH,
)
from src.agents.cost_estimator import estimate_cost
from src.agents.llm import (
    AnthropicLLM,
    OllamaLLM,
    OpenAILLM,
)
from src.agents.response_parser import (
    extract_final_answer,
    extract_reasoning,
    parse_tool_calls,
    sanitize_tool_output,
)
from src.agents.tool_keys import ToolKeys
from src.utils.exceptions import (
    ConfigValidationError,
    ToolExecutionError,
    ToolNotFoundError,
    sanitize_error_message,
)

logger = logging.getLogger(__name__)


@dataclass
class ResponseBuildData:
    """Bundle parameters for building final response (reduces 9 params to 1)."""
    output: str
    reasoning: Optional[str]
    tool_calls: List[Dict[str, Any]]
    tokens: int
    cost: float
    start_time: float
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Tool execution helpers
# ---------------------------------------------------------------------------

def execute_tool_calls(
    agent: "StandardAgent",
    tool_calls: List[Dict[str, Any]],
    get_tool_executor_fn: Callable[[], concurrent.futures.ThreadPoolExecutor],
) -> List[Dict[str, Any]]:
    """Execute a list of tool calls (parallel if independent, sequential if dependent)."""
    if not isinstance(tool_calls, list):
        raise TypeError(f"tool_calls must be a list, got {type(tool_calls).__name__}")

    for i, tool_call in enumerate(tool_calls):
        if not isinstance(tool_call, dict):
            raise TypeError(f"tool_call at index {i} must be a dictionary, got {type(tool_call).__name__}")

    if len(tool_calls) <= 1:
        return [execute_single_tool(agent, tool_call) for tool_call in tool_calls]

    parallel_enabled = getattr(agent.config.agent.safety, "parallel_tool_calls", True)

    if not parallel_enabled:
        return [execute_single_tool(agent, tool_call) for tool_call in tool_calls]

    tool_results: List[Any] = [None] * len(tool_calls)

    future_to_index = {
        get_tool_executor_fn().submit(execute_single_tool, agent, tool_call): i
        for i, tool_call in enumerate(tool_calls)
    }

    for future in concurrent.futures.as_completed(future_to_index):
        index = future_to_index[future]
        try:
            result = future.result()
            tool_results[index] = result
        except (ToolExecutionError, ToolNotFoundError, TimeoutError, RuntimeError) as e:
            logger.error(f"Tool execution failed in parallel mode: {e}")
            tool_results[index] = {
                ToolKeys.NAME: tool_calls[index].get(ToolKeys.NAME, FALLBACK_UNKNOWN_VALUE),
                ToolKeys.PARAMETERS: tool_calls[index].get(ToolKeys.PARAMETERS, {}),
                ToolKeys.SUCCESS: False,
                ToolKeys.RESULT: None,
                ToolKeys.ERROR: f"Parallel execution error: {str(e)}"
            }

    return tool_results


def _check_safety_mode_blocking(
    agent: "StandardAgent",
    tool_name: str,
    tool_params: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Check if safety mode blocks execution. Returns error dict or None."""
    safety = agent.config.agent.safety

    if safety.mode == "require_approval":
        return {
            ToolKeys.NAME: tool_name,
            ToolKeys.PARAMETERS: tool_params,
            ToolKeys.RESULT: None,
            ToolKeys.ERROR: f"{ERROR_MSG_TOOL_PREFIX}{tool_name}' blocked: safety mode is 'require_approval'",
            ToolKeys.SUCCESS: False
        }

    if tool_name in safety.require_approval_for_tools:
        return {
            "name": tool_name,
            "parameters": tool_params,
            "result": None,
            "error": f"{ERROR_MSG_TOOL_PREFIX}{tool_name}' requires approval before execution",
            "success": False
        }

    if safety.mode == "dry_run":
        return {
            ToolKeys.NAME: tool_name,
            ToolKeys.PARAMETERS: tool_params,
            ToolKeys.RESULT: f"[DRY RUN] {ERROR_MSG_TOOL_PREFIX}{tool_name}' would be executed with parameters: {tool_params}",
            ToolKeys.ERROR: None,
            ToolKeys.SUCCESS: True
        }

    return None


def execute_single_tool(agent: "StandardAgent", tool_call: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a single tool call."""
    if not isinstance(tool_call, dict):
        raise TypeError(f"tool_call must be a dictionary, got {type(tool_call).__name__}")

    if ToolKeys.NAME not in tool_call:
        raise ValueError("tool_call must contain 'name' field")

    tool_name = tool_call.get(ToolKeys.NAME)
    tool_params = tool_call.get(ToolKeys.PARAMETERS, tool_call.get("arguments", {}))

    if not isinstance(tool_name, str):
        raise TypeError(f"tool_call 'name' must be a string, got {type(tool_name).__name__}")

    if not isinstance(tool_params, dict):
        raise TypeError(f"tool_call 'parameters' must be a dictionary, got {type(tool_params).__name__}")

    # Defense-in-depth: Agent-level SafetyConfig pre-checks before tool execution.
    safety_block = _check_safety_mode_blocking(agent, tool_name, tool_params)
    if safety_block is not None:
        return safety_block

    # Route through ToolExecutor (safety-integrated execution)
    if hasattr(agent, 'tool_executor') and agent.tool_executor is not None:
        return execute_via_tool_executor(agent, tool_name, tool_params)

    # SECURITY: No silent fallback
    logger.critical(
        "SECURITY: No tool_executor configured for agent '%s'. "
        f"{ERROR_MSG_TOOL_PREFIX}%s' execution blocked to prevent safety bypass.",
        agent.name, tool_name
    )
    return {
        ToolKeys.NAME: tool_name,
        ToolKeys.PARAMETERS: tool_params,
        ToolKeys.RESULT: None,
        ToolKeys.ERROR: (
            f"{ERROR_MSG_TOOL_PREFIX}{tool_name}' execution blocked: no tool_executor configured. "
            f"The safety stack is required for tool execution."
        ),
        ToolKeys.SUCCESS: False
    }


def _build_tool_result_dict(
    tool_name: str,
    tool_params: Dict[str, Any],
    success: bool,
    result: Any = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """Build standardized tool result dictionary."""
    return {
        ToolKeys.NAME: tool_name,
        ToolKeys.PARAMETERS: tool_params,
        ToolKeys.RESULT: result if success else None,
        ToolKeys.ERROR: error if not success else None,
        ToolKeys.SUCCESS: success
    }


def execute_via_tool_executor(
    agent: "StandardAgent",
    tool_name: str,
    tool_params: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute tool through the safety-integrated ToolExecutor."""
    tool_start_time = time.time()
    try:
        result = agent.tool_executor.execute(tool_name, tool_params)  # type: ignore[attr-defined]
        duration_seconds = time.time() - tool_start_time
        logger.info(
            "[%s] Tool '%s' %s (%.1fs)",
            agent.name, tool_name,
            "succeeded" if result.success else "failed",
            duration_seconds,
        )
        agent._observer.track_tool_call(  # type: ignore[attr-defined]
            tool_name=tool_name,
            input_params=tool_params,
            output_data={"result": result.result} if result.success else {},
            duration_seconds=duration_seconds,
            status="success" if result.success else "failed",
            error_message=result.error if not result.success else None
        )
        return _build_tool_result_dict(tool_name, tool_params, result.success, result.result, result.error)
    except (ToolExecutionError, ToolNotFoundError, TimeoutError, RuntimeError) as e:
        duration_seconds = time.time() - tool_start_time
        error_msg = f"Tool execution error: {str(e)}"
        agent._observer.track_tool_call(  # type: ignore[attr-defined]
            tool_name=tool_name,
            input_params=tool_params,
            output_data={},
            duration_seconds=duration_seconds,
            status="failed",
            error_message=error_msg
        )
        return _build_tool_result_dict(tool_name, tool_params, False, None, error_msg)


# ---------------------------------------------------------------------------
# Prompt / tool-schema helpers
# ---------------------------------------------------------------------------

def get_cached_tool_schemas(agent: "StandardAgent") -> Optional[str]:
    """Get cached tool schemas or build and cache them."""
    tools_dict = agent.tool_registry.get_all_tools()
    if not tools_dict:
        return None

    current_version = len(tools_dict)
    if agent._cached_tool_schemas is not None and agent._tool_registry_version == current_version:
        return agent._cached_tool_schemas

    tool_schemas = [
        {
            ToolKeys.NAME: tool.name,
            "description": tool.description,
            ToolKeys.PARAMETERS: tool.get_parameters_schema()
        }
        for tool in tools_dict.values()
    ]
    tools_section = (
        "\n\n## Available Tools\n"
        "You can call tools by writing a tool_call block. "
        "To call a tool, use EXACTLY this format:\n"
        "<tool_call>\n"
        '{"name": "<tool_name>", "parameters": {<parameters>}}\n'
        "</tool_call>\n\n"
        "You may call multiple tools. Wait for tool results before continuing.\n\n"
        + json.dumps(tool_schemas, indent=2)
    )

    agent._cached_tool_schemas = tools_section
    agent._tool_registry_version = current_version

    return tools_section


def get_native_tool_definitions(agent: "StandardAgent") -> Optional[List[Dict[str, Any]]]:
    """Build native tool definitions for providers that support them.

    M-20: Results are cached and only recomputed when the tool registry
    contents change (detected via a hash of tool names).
    """
    if not isinstance(agent.llm, (OllamaLLM, OpenAILLM, AnthropicLLM)):
        return None

    tools_dict = agent.tool_registry.get_all_tools()
    if not tools_dict:
        return None

    # Check cache validity using a hash of sorted tool names
    tool_names_key = ",".join(sorted(tools_dict.keys()))
    current_hash = hashlib.sha256(tool_names_key.encode()).hexdigest()

    if (
        agent._cached_native_tool_defs is not None
        and agent._cached_native_tool_defs_hash == current_hash
    ):
        return agent._cached_native_tool_defs

    native_tools = []
    for tool in tools_dict.values():
        schema = tool.get_parameters_schema()

        function_def = {
            ToolKeys.NAME: tool.name,
            "description": tool.description,
            ToolKeys.PARAMETERS: schema,
        }

        result_schema = tool.get_result_schema()
        if result_schema:
            function_def["description"] = (
                f"{tool.description}\n\n"
                f"Result schema: {json.dumps(result_schema, indent=2)}"
            )

        native_tools.append({
            "type": "function",
            "function": function_def,
        })

    result = native_tools if native_tools else None
    agent._cached_native_tool_defs = result
    agent._cached_native_tool_defs_hash = current_hash
    return result


def _format_tool_results_text(
    tool_results: List[Dict[str, Any]],
    max_tool_result_size: int,
    remaining_tool_calls: Optional[int] = None,
) -> str:
    """Format tool results into text for prompt injection.

    Args:
        tool_results: List of tool result dicts with NAME, PARAMETERS, SUCCESS, RESULT/ERROR
        max_tool_result_size: Maximum chars per tool result (truncate if exceeded)
        remaining_tool_calls: Optional remaining budget to display

    Returns:
        Formatted tool results text
    """
    results_parts = ["\n\nTool Results:\n"]
    for result in tool_results:
        results_parts.append(f"\nTool: {result[ToolKeys.NAME]}\n")
        results_parts.append(f"Parameters: {json.dumps(result[ToolKeys.PARAMETERS])}\n")

        if result[ToolKeys.SUCCESS]:
            safe_result = sanitize_tool_output(str(result[ToolKeys.RESULT]))
            if len(safe_result) > max_tool_result_size:
                original_size = len(safe_result)
                safe_result = safe_result[:max_tool_result_size]
                safe_result += f"\n[truncated — {original_size:,} total chars, showing first {max_tool_result_size:,}]"
            results_parts.append(f"Result: {safe_result}\n")
        else:
            safe_error = sanitize_tool_output(str(result[ToolKeys.ERROR]))
            if len(safe_error) > max_tool_result_size:
                original_size = len(safe_error)
                safe_error = safe_error[:max_tool_result_size]
                safe_error += f"\n[truncated — {original_size:,} total chars, showing first {max_tool_result_size:,}]"
            results_parts.append(f"Error: {safe_error}\n")

    if remaining_tool_calls is not None:
        if remaining_tool_calls > 0:
            results_parts.append(
                f"\n[System Info: You have {remaining_tool_calls} tool call(s) remaining in your budget.]\n"
            )
        else:
            results_parts.append(
                "\n[System Info: This is your last tool call. Budget exhausted after this iteration.]\n"
            )

    return ''.join(results_parts)


def _apply_sliding_window(
    agent: "StandardAgent",
    system_prompt: str,
    max_prompt_length: int,
) -> str:
    """Apply sliding window to conversation turns to fit within max_prompt_length.

    Args:
        agent: Agent instance with _conversation_turns attribute
        system_prompt: System prompt to prepend
        max_prompt_length: Maximum total prompt length

    Returns:
        Full prompt with system_prompt + included turns + suffix
    """
    suffix = "\n\nPlease continue:"
    budget = max_prompt_length - len(system_prompt) - len(suffix)

    if budget <= 0:
        # System prompt itself exceeds budget; include only most recent turn
        recent_turn = sanitize_tool_output(agent._conversation_turns[-1])
        return system_prompt + recent_turn + suffix

    # Include as many recent turns as fit within the budget
    included_turns: List[str] = []
    total_turn_chars = 0
    for turn in reversed(agent._conversation_turns):
        if total_turn_chars + len(turn) > budget:
            break
        included_turns.append(turn)
        total_turn_chars += len(turn)

    included_turns.reverse()

    # Add truncation marker if we dropped turns
    dropped_count = len(agent._conversation_turns) - len(included_turns)
    truncation_marker = ""
    if dropped_count > 0:
        truncation_marker = f"\n\n[...{dropped_count} earlier iteration(s) omitted for brevity...]\n"

    # NOTE: Do NOT re-sanitize assembled turns. Tool results are already
    # sanitized individually. Re-sanitizing escapes the LLM's own <tool_call> tags
    # (→ &lt;tool_call&gt;), breaking parse_tool_calls() and halting the tool-calling loop.
    assembled_turns = truncation_marker + ''.join(included_turns)

    # M-48: Prune old turns to free memory
    if dropped_count > 0:
        agent._conversation_turns = included_turns

    return system_prompt + assembled_turns + suffix


def inject_tool_results(
    agent: "StandardAgent",
    original_prompt: str,
    llm_response: str,
    tool_results: List[Dict[str, Any]],
    remaining_tool_calls: Optional[int] = None,
) -> str:
    """Inject tool results into prompt for next iteration.

    Uses a sliding-window approach (C-01) to prevent unbounded prompt growth.
    """
    max_tool_result_size = agent.config.agent.safety.max_tool_result_size
    max_prompt_length = agent.config.agent.safety.max_prompt_length

    # Format tool results
    results_text = _format_tool_results_text(tool_results, max_tool_result_size, remaining_tool_calls)

    # Build this iteration's turn text
    turn_text = "\n\nAssistant: " + llm_response + results_text

    # Append to conversation history
    if not hasattr(agent, '_conversation_turns'):
        agent._conversation_turns = []
    agent._conversation_turns.append(turn_text)

    # Use the pinned system prompt (set in execute())
    system_prompt = getattr(agent, '_system_prompt', original_prompt)

    # Apply sliding window and return full prompt
    return _apply_sliding_window(agent, system_prompt, max_prompt_length)


# ---------------------------------------------------------------------------
# Response building
# ---------------------------------------------------------------------------

def build_final_response(
    agent: "StandardAgent",
    output: str,
    reasoning: Optional[str],
    tool_calls: List[Dict[str, Any]],
    tokens: int,
    cost: float,
    start_time: float,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Any:  # Return type must be Any to avoid circular import issues with AgentResponse
    """Build final AgentResponse.

    Note: Maintains backward-compatible signature. Consider using
    ResponseBuildData for new code to bundle parameters.
    """
    from src.agents.base_agent import AgentResponse

    duration = time.time() - start_time
    output_preview = (output[:OUTPUT_PREVIEW_LENGTH].replace('\n', ' ').strip() + "...") if len(output) > OUTPUT_PREVIEW_LENGTH else output.replace('\n', ' ').strip()
    logger.info(
        "[%s] Execution complete (%d tokens, $%.4f, %.1fs) → %s",
        agent.name, tokens, cost, duration, output_preview or "(empty)",
    )
    return AgentResponse(
        output=output,
        reasoning=reasoning,
        tool_calls=tool_calls,  # type: ignore[arg-type]  # Dict structure differs from ToolCallRecord
        tokens=tokens,
        estimated_cost_usd=cost,
        latency_seconds=time.time() - start_time,
        error=error,
        metadata=metadata or {}
    )


# ---------------------------------------------------------------------------
# Safety validation (shared between sync and async iteration paths)
# ---------------------------------------------------------------------------

def _build_policy_context(agent: "StandardAgent", inf_config: Any, prompt: str) -> Any:
    """Build PolicyExecutionContext for safety validation."""
    from src.safety.action_policy_engine import PolicyExecutionContext

    ctx = getattr(agent, '_execution_context', None)
    agent_id = ctx.agent_id if ctx and ctx.agent_id else agent.config.agent.name
    workflow_id = ctx.workflow_id if ctx and ctx.workflow_id else FALLBACK_UNKNOWN_VALUE
    stage_id = ctx.stage_id if ctx and ctx.stage_id else FALLBACK_UNKNOWN_VALUE

    return PolicyExecutionContext(
        agent_id=agent_id,
        workflow_id=workflow_id,
        stage_id=stage_id,
        action_type="llm_call",
        action_data={"model": inf_config.model}
    )


def _validate_action_with_policy(
    agent: "StandardAgent",
    inf_config: Any,
    prompt: str,
) -> Optional[str]:
    """Validate LLM call with policy engine. Returns violation message or None."""
    policy_context = _build_policy_context(agent, inf_config, prompt)

    validation_result = agent.tool_executor.policy_engine.validate_action_sync(
        action={"type": "llm_call", "model": inf_config.model, "prompt_length": len(prompt)},
        context=policy_context
    )

    if not validation_result.allowed:
        return "; ".join(v.message for v in validation_result.violations)

    return None


def validate_safety_for_llm_call(
    agent: "StandardAgent",
    inf_config: Any,
    prompt: str,
    tool_calls_made: List[Dict[str, Any]],
    total_tokens: int,
    total_cost: float,
    start_time: float
) -> Optional[Dict[str, Any]]:
    """Run safety validation for an LLM call. Returns error dict or None."""
    if not (hasattr(agent, 'tool_executor') and agent.tool_executor is not None):
        return None

    if agent.tool_executor.policy_engine is None:
        return None

    try:
        violations_msg = _validate_action_with_policy(agent, inf_config, prompt)

        if violations_msg:
            logger.warning(f"LLM call blocked by safety policy: {violations_msg}")
            return {
                "complete": True,
                "response": build_final_response(
                    agent,
                    output="",
                    reasoning=None,
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    start_time=start_time,
                    error=f"LLM call blocked by safety policy: {violations_msg}"
                )
            }
    except (ConfigValidationError, ValueError, RuntimeError) as e:
        logger.error(
            "LLM call safety validation failed (fail-closed): %s",
            e, exc_info=True
        )
        return {
            "complete": True,
            "response": build_final_response(
                agent,
                output="",
                reasoning=None,
                tool_calls=tool_calls_made,
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
                error=f"Safety validation error (fail-closed): {sanitize_error_message(str(e))}"
            )
        }
    return None


def track_llm_call(
    agent: "StandardAgent",
    inf_config: Any,
    prompt: str,
    llm_response: Any,
    cost: float
) -> None:
    """Track an LLM call via the observer."""
    agent._observer.track_llm_call(  # type: ignore[attr-defined]
        provider=inf_config.provider,
        model=inf_config.model,
        prompt=prompt,
        response=llm_response.content,
        prompt_tokens=llm_response.prompt_tokens or 0,
        completion_tokens=llm_response.completion_tokens or 0,
        latency_ms=int(llm_response.latency_ms) if hasattr(llm_response, 'latency_ms') and llm_response.latency_ms else 0,
        estimated_cost_usd=cost,
        temperature=inf_config.temperature,
        max_tokens=inf_config.max_tokens,
        status="success"
    )


def track_failed_llm_call(
    agent: "StandardAgent",
    inf_config: Any,
    prompt: str,
    error: Exception,
    attempt: int,
    max_attempts: int,
) -> None:
    """Track a failed LLM call via the observer.

    Records failed/timed-out LLM calls so they appear in observability
    data even when no successful response was returned.
    """
    error_msg = sanitize_error_message(str(error))
    agent._observer.track_llm_call(  # type: ignore[attr-defined]
        provider=inf_config.provider,
        model=inf_config.model,
        prompt=prompt,
        response="",
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=0,
        estimated_cost_usd=0.0,
        temperature=inf_config.temperature,
        max_tokens=inf_config.max_tokens,
        status="failed",
        error_message=f"[attempt {attempt}/{max_attempts}] {error_msg}",
    )


@dataclass
class LLMProcessingContext:
    """Context for processing LLM responses (reduces 9 params to 1)."""
    agent: "StandardAgent"
    llm_response: Any
    tool_calls_made: List[Dict[str, Any]]
    total_tokens: int
    total_cost: float
    start_time: float
    prompt: str
    max_iterations: Optional[int]
    get_tool_executor_fn: Callable[[], concurrent.futures.ThreadPoolExecutor]


def _build_no_tools_response(ctx: LLMProcessingContext) -> Dict[str, Any]:
    """Build response when no tool calls are present."""
    return {
        "complete": True,
        "response": build_final_response(
            ctx.agent,
            output=extract_final_answer(ctx.llm_response.content),
            reasoning=extract_reasoning(ctx.llm_response.content),
            tool_calls=ctx.tool_calls_made,
            tokens=ctx.total_tokens,
            cost=ctx.total_cost,
            start_time=ctx.start_time,
            error=None
        )
    }


def _execute_and_inject_tools(ctx: LLMProcessingContext, tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Execute tool calls and build continuation response."""
    tool_results = execute_tool_calls(ctx.agent, tool_calls, ctx.get_tool_executor_fn)
    ctx.tool_calls_made.extend(tool_results)

    remaining_budget = None
    if ctx.max_iterations is not None:
        remaining_budget = ctx.max_iterations - len(ctx.tool_calls_made)

    next_prompt = inject_tool_results(
        ctx.agent, ctx.prompt, ctx.llm_response.content, tool_results,
        remaining_tool_calls=remaining_budget
    )

    return {
        "complete": False,
        "llm_response": ctx.llm_response,
        "next_prompt": next_prompt,
        "total_tokens": ctx.total_tokens,
        "total_cost": ctx.total_cost,
        "tool_calls_made": ctx.tool_calls_made
    }


def process_llm_response(
    agent: "StandardAgent",
    llm_response: Any,
    tool_calls_made: List[Dict[str, Any]],
    total_tokens: int,
    total_cost: float,
    start_time: float,
    prompt: str,
    max_iterations: Optional[int],
    get_tool_executor_fn: Callable[[], concurrent.futures.ThreadPoolExecutor]
) -> Dict[str, Any]:
    """Process LLM response: parse tool calls, execute if any, build result dict."""
    ctx = LLMProcessingContext(
        agent=agent,
        llm_response=llm_response,
        tool_calls_made=tool_calls_made,
        total_tokens=total_tokens,
        total_cost=total_cost,
        start_time=start_time,
        prompt=prompt,
        max_iterations=max_iterations,
        get_tool_executor_fn=get_tool_executor_fn
    )

    # Parse tool calls
    tool_calls = parse_tool_calls(llm_response.content)

    if tool_calls:
        tool_names = ", ".join(tc.get(ToolKeys.NAME, "?") for tc in tool_calls)
        logger.info("[%s] Calling %d tool(s): %s", agent.name, len(tool_calls), tool_names)
        return _execute_and_inject_tools(ctx, tool_calls)

    return _build_no_tools_response(ctx)


# ---------------------------------------------------------------------------
# Execution setup
# ---------------------------------------------------------------------------

def setup_execution(
    agent: "StandardAgent",
    input_data: Dict[str, Any],
    context: Any,
    async_mode: bool = False
) -> None:
    """Common setup for sync and async execute paths."""
    from src.agents.agent_observer import AgentObserver
    from src.tools.executor import ToolExecutor

    agent._execution_context = context  # type: ignore[attr-defined]
    _tool_executor = input_data.get('tool_executor', None)
    if _tool_executor is not None:
        if not isinstance(_tool_executor, ToolExecutor):
            raise TypeError(
                f"tool_executor must be a ToolExecutor instance, "
                f"got {type(_tool_executor).__name__}"
            )
    agent.tool_executor = _tool_executor  # type: ignore[attr-defined]
    agent.tracker = input_data.get('tracker', None)  # type: ignore[attr-defined]
    agent._observer = AgentObserver(agent.tracker, agent._execution_context)  # type: ignore[attr-defined]
    # stream_callback may be a StreamDisplay instance (multi-agent) or a plain callable
    _stream_cb = input_data.get('stream_callback', None)
    if _stream_cb is not None and hasattr(_stream_cb, 'make_callback'):
        # StreamDisplay: create per-agent callback so each agent gets its own panel
        agent._stream_callback = _stream_cb.make_callback(agent.name)  # type: ignore[attr-defined]
    else:
        agent._stream_callback = _stream_cb  # type: ignore[attr-defined]

    # Render Jinja2 templates in tool configs now that input_data is available.
    # Tool configs may contain {{ workspace_path }} etc. that need resolving.
    _resolve_tool_config_templates(agent, input_data)

    logger.info("[%s] Starting %sexecution", agent.name, "async " if async_mode else "")


def _resolve_tool_config_templates(
    agent: "StandardAgent",
    input_data: Dict[str, Any],
) -> None:
    """Render Jinja2 template strings in tool config values using input_data.

    Tool configs are loaded at agent init time (before input_data is available),
    so any ``{{ variable }}`` references remain as literal strings. This function
    resolves them at execution time when input_data provides the actual values.
    """
    registry = getattr(agent, "tool_registry", None)
    if registry is None:
        return

    try:
        tools_dict = registry.get_all_tools()
    except (AttributeError, TypeError):
        return
    if not tools_dict:
        return

    for tool in tools_dict.values():
        if not hasattr(tool, "config") or not isinstance(tool.config, dict):
            continue

        changed = False
        for key, value in tool.config.items():
            if isinstance(value, str) and "{{" in value:
                rendered = _render_template_value(value, input_data)
                if rendered != value:
                    tool.config[key] = rendered
                    changed = True
            elif isinstance(value, list):
                # Lists (e.g. allowed_commands) don't need template rendering
                continue

        if changed:
            logger.debug(
                "[%s] Resolved tool config templates for %s: %s",
                agent.name,
                getattr(tool, "name", type(tool).__name__),
                {k: v for k, v in tool.config.items() if not k.startswith("_")},
            )


def _render_template_value(template: str, variables: Dict[str, Any]) -> str:
    """Render a single Jinja2 template string with the given variables.

    Uses a minimal approach: simple {{ var }} substitution without importing
    the full Jinja2 engine, to keep this lightweight.
    """
    import re
    result = template
    for match in re.finditer(r"\{\{\s*(\w+)\s*\}\}", template):
        var_name = match.group(1)
        if var_name in variables:
            result = result.replace(match.group(0), str(variables[var_name]))
    return result


def make_stream_callback(agent: "StandardAgent") -> Optional[Callable]:
    """Create a combined stream callback for CLI display and observability.

    Returns None if neither user callback nor observer is available,
    which triggers non-streaming fallback in the caller.
    """
    user_cb = getattr(agent, '_stream_callback', None)
    observer = getattr(agent, '_observer', None)
    has_observer = observer is not None and observer.active

    if user_cb is None and not has_observer:
        return None

    def combined_callback(chunk: Any) -> None:
        """Forward stream chunks to user callback and observer."""
        if user_cb is not None:
            try:
                user_cb(chunk)
            except Exception:  # noqa: BLE001 -- streaming display must not disrupt execution
                pass
        if has_observer and observer is not None:
            try:
                observer.emit_stream_chunk(
                    content=chunk.content,
                    chunk_type=chunk.chunk_type,
                    done=chunk.done,
                    model=chunk.model,
                    prompt_tokens=chunk.prompt_tokens,
                    completion_tokens=chunk.completion_tokens,
                )
            except Exception:  # noqa: BLE001 -- streaming event must not disrupt execution
                pass

    return combined_callback


def estimate_cost_for_response(agent: "StandardAgent", llm_response: Any) -> float:
    """Estimate cost for an LLM response."""
    return estimate_cost(llm_response, fallback_model=getattr(agent.llm, 'model', FALLBACK_UNKNOWN_VALUE))
