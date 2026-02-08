"""Helper functions extracted from StandardAgent to reduce class size.

These are internal implementation details and should not be imported directly.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from src.agents.standard_agent import StandardAgent

from src.agents.constants import OUTPUT_PREVIEW_LENGTH
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
from src.utils.exceptions import (
    ConfigValidationError,
    ToolExecutionError,
    ToolNotFoundError,
    sanitize_error_message,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool execution helpers
# ---------------------------------------------------------------------------

def execute_tool_calls(
    agent: StandardAgent,
    tool_calls: List[Dict[str, Any]],
    get_tool_executor_fn,
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
                "name": tool_calls[index].get("name", "unknown"),
                "parameters": tool_calls[index].get("parameters", {}),
                "success": False,
                "result": None,
                "error": f"Parallel execution error: {str(e)}"
            }

    return tool_results


def execute_single_tool(agent: StandardAgent, tool_call: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a single tool call."""
    if not isinstance(tool_call, dict):
        raise TypeError(f"tool_call must be a dictionary, got {type(tool_call).__name__}")

    if "name" not in tool_call:
        raise ValueError("tool_call must contain 'name' field")

    tool_name = tool_call.get("name")
    tool_params = tool_call.get("parameters", tool_call.get("arguments", {}))

    if not isinstance(tool_name, str):
        raise TypeError(f"tool_call 'name' must be a string, got {type(tool_name).__name__}")

    if not isinstance(tool_params, dict):
        raise TypeError(f"tool_call 'parameters' must be a dictionary, got {type(tool_params).__name__}")

    # Defense-in-depth: Agent-level SafetyConfig pre-checks before tool execution.
    safety = agent.config.agent.safety

    if safety.mode == "require_approval":
        return {
            "name": tool_name,
            "parameters": tool_params,
            "result": None,
            "error": f"Tool '{tool_name}' blocked: safety mode is 'require_approval'",
            "success": False
        }

    if tool_name in safety.require_approval_for_tools:
        return {
            "name": tool_name,
            "parameters": tool_params,
            "result": None,
            "error": f"Tool '{tool_name}' requires approval before execution",
            "success": False
        }

    if safety.mode == "dry_run":
        return {
            "name": tool_name,
            "parameters": tool_params,
            "result": f"[DRY RUN] Tool '{tool_name}' would be executed with parameters: {tool_params}",
            "error": None,
            "success": True
        }

    # Route through ToolExecutor (safety-integrated execution)
    if hasattr(agent, 'tool_executor') and agent.tool_executor is not None:
        return execute_via_tool_executor(agent, tool_name, tool_params)

    # SECURITY: No silent fallback
    logger.critical(
        "SECURITY: No tool_executor configured for agent '%s'. "
        "Tool '%s' execution blocked to prevent safety bypass.",
        agent.name, tool_name
    )
    return {
        "name": tool_name,
        "parameters": tool_params,
        "result": None,
        "error": (
            f"Tool '{tool_name}' execution blocked: no tool_executor configured. "
            f"The safety stack is required for tool execution."
        ),
        "success": False
    }


def execute_via_tool_executor(
    agent: StandardAgent,
    tool_name: str,
    tool_params: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute tool through the safety-integrated ToolExecutor."""
    tool_start_time = time.time()
    try:
        result = agent.tool_executor.execute(tool_name, tool_params)
        duration_seconds = time.time() - tool_start_time
        logger.info(
            "[%s] Tool '%s' %s (%.1fs)",
            agent.name, tool_name,
            "succeeded" if result.success else "failed",
            duration_seconds,
        )

        agent._observer.track_tool_call(
            tool_name=tool_name,
            input_params=tool_params,
            output_data={"result": result.result} if result.success else {},
            duration_seconds=duration_seconds,
            status="success" if result.success else "failed",
            error_message=result.error if not result.success else None
        )

        return {
            "name": tool_name,
            "parameters": tool_params,
            "result": result.result if result.success else None,
            "error": result.error if not result.success else None,
            "success": result.success
        }
    except (ToolExecutionError, ToolNotFoundError, TimeoutError, RuntimeError) as e:
        duration_seconds = time.time() - tool_start_time

        agent._observer.track_tool_call(
            tool_name=tool_name,
            input_params=tool_params,
            output_data={},
            duration_seconds=duration_seconds,
            status="failed",
            error_message=f"Tool execution error: {str(e)}"
        )

        return {
            "name": tool_name,
            "parameters": tool_params,
            "result": None,
            "error": f"Tool execution error: {str(e)}",
            "success": False
        }


# ---------------------------------------------------------------------------
# Prompt / tool-schema helpers
# ---------------------------------------------------------------------------

def get_cached_tool_schemas(agent: StandardAgent) -> Optional[str]:
    """Get cached tool schemas or build and cache them."""
    tools_dict = agent.tool_registry.get_all_tools()
    if not tools_dict:
        return None

    current_version = len(tools_dict)
    if agent._cached_tool_schemas is not None and agent._tool_registry_version == current_version:
        return agent._cached_tool_schemas

    tool_schemas = [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.get_parameters_schema()
        }
        for tool in tools_dict.values()
    ]
    tools_section = "\n\nAvailable Tools:\n" + json.dumps(tool_schemas, indent=2)

    agent._cached_tool_schemas = tools_section
    agent._tool_registry_version = current_version

    return tools_section


def get_native_tool_definitions(agent: StandardAgent) -> Optional[List[Dict[str, Any]]]:
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
            "name": tool.name,
            "description": tool.description,
            "parameters": schema,
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


def inject_tool_results(
    agent: StandardAgent,
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

    results_parts = ["\n\nTool Results:\n"]
    for result in tool_results:
        results_parts.append(f"\nTool: {result['name']}\n")
        results_parts.append(f"Parameters: {json.dumps(result['parameters'])}\n")
        if result['success']:
            safe_result = sanitize_tool_output(str(result['result']))

            if len(safe_result) > max_tool_result_size:
                original_size = len(safe_result)
                safe_result = safe_result[:max_tool_result_size]
                safe_result += f"\n[truncated — {original_size:,} total chars, showing first {max_tool_result_size:,}]"

            results_parts.append(f"Result: {safe_result}\n")
        else:
            safe_error = sanitize_tool_output(str(result['error']))

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

    results_text = ''.join(results_parts)

    # Build this iteration's turn text
    turn_text = "\n\nAssistant: " + llm_response + results_text

    # Append to conversation history
    if not hasattr(agent, '_conversation_turns'):
        agent._conversation_turns = []
    agent._conversation_turns.append(turn_text)

    # Use the pinned system prompt (set in execute())
    system_prompt = getattr(agent, '_system_prompt', original_prompt)

    # Build full prompt with sliding window
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

    # If we dropped any turns, add a truncation marker and count
    dropped_count = len(agent._conversation_turns) - len(included_turns)
    truncation_marker = ""
    if dropped_count > 0:
        truncation_marker = f"\n\n[...{dropped_count} earlier iteration(s) omitted for brevity...]\n"

    # Re-sanitize the assembled turns
    assembled_turns = truncation_marker + ''.join(included_turns)
    assembled_turns = sanitize_tool_output(assembled_turns)

    # M-48: Prune old turns to free memory
    if dropped_count > 0:
        agent._conversation_turns = included_turns

    return system_prompt + assembled_turns + suffix


# ---------------------------------------------------------------------------
# Response building
# ---------------------------------------------------------------------------

def build_final_response(
    agent: StandardAgent,
    output: str,
    reasoning: Optional[str],
    tool_calls: List[Dict[str, Any]],
    tokens: int,
    cost: float,
    start_time: float,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Build final AgentResponse."""
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
        tool_calls=tool_calls,
        tokens=tokens,
        estimated_cost_usd=cost,
        latency_seconds=time.time() - start_time,
        error=error,
        metadata=metadata or {}
    )


# ---------------------------------------------------------------------------
# Safety validation (shared between sync and async iteration paths)
# ---------------------------------------------------------------------------

def validate_safety_for_llm_call(agent: StandardAgent, inf_config, prompt, tool_calls_made, total_tokens, total_cost, start_time):
    """Run safety validation for an LLM call. Returns error dict or None."""
    if hasattr(agent, 'tool_executor') and agent.tool_executor is not None:
        if agent.tool_executor.policy_engine is not None:
            try:
                from src.safety.action_policy_engine import PolicyExecutionContext

                ctx = getattr(agent, '_execution_context', None)
                agent_id = ctx.agent_id if ctx and ctx.agent_id else agent.config.agent.name
                workflow_id = ctx.workflow_id if ctx and ctx.workflow_id else "unknown"
                stage_id = ctx.stage_id if ctx and ctx.stage_id else "unknown"

                validation_result = agent.tool_executor.policy_engine.validate_action_sync(
                    action={"type": "llm_call", "model": inf_config.model, "prompt_length": len(prompt)},
                    context=PolicyExecutionContext(
                        agent_id=agent_id,
                        workflow_id=workflow_id,
                        stage_id=stage_id,
                        action_type="llm_call",
                        action_data={"model": inf_config.model}
                    )
                )

                if not validation_result.allowed:
                    violations_msg = "; ".join(v.message for v in validation_result.violations)
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


def track_llm_call(agent: StandardAgent, inf_config, prompt, llm_response, cost):
    """Track an LLM call via the observer."""
    agent._observer.track_llm_call(
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


def process_llm_response(agent: StandardAgent, llm_response, tool_calls_made, total_tokens, total_cost, start_time, prompt, max_iterations, get_tool_executor_fn):
    """Process LLM response: parse tool calls, execute if any, build result dict."""
    # Parse tool calls
    tool_calls = parse_tool_calls(llm_response.content)

    if tool_calls:
        tool_names = ", ".join(tc.get("name", "?") for tc in tool_calls)
        logger.info("[%s] Calling %d tool(s): %s", agent.name, len(tool_calls), tool_names)

    if not tool_calls:
        return {
            "complete": True,
            "response": build_final_response(
                agent,
                output=extract_final_answer(llm_response.content),
                reasoning=extract_reasoning(llm_response.content),
                tool_calls=tool_calls_made,
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
                error=None
            )
        }

    # Execute tools
    tool_results = execute_tool_calls(agent, tool_calls, get_tool_executor_fn)
    tool_calls_made.extend(tool_results)

    remaining_budget = None
    if max_iterations is not None:
        remaining_budget = max_iterations - len(tool_calls_made)

    next_prompt = inject_tool_results(
        agent, prompt, llm_response.content, tool_results,
        remaining_tool_calls=remaining_budget
    )

    return {
        "complete": False,
        "llm_response": llm_response,
        "next_prompt": next_prompt,
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "tool_calls_made": tool_calls_made
    }


# ---------------------------------------------------------------------------
# Execution setup
# ---------------------------------------------------------------------------

def setup_execution(agent: StandardAgent, input_data, context, async_mode=False):
    """Common setup for sync and async execute paths."""
    from src.agents.agent_observer import AgentObserver
    from src.tools.executor import ToolExecutor

    agent._execution_context = context
    _tool_executor = input_data.get('tool_executor', None)
    if _tool_executor is not None:
        if not isinstance(_tool_executor, ToolExecutor):
            raise TypeError(
                f"tool_executor must be a ToolExecutor instance, "
                f"got {type(_tool_executor).__name__}"
            )
    agent.tool_executor = _tool_executor
    agent.tracker = input_data.get('tracker', None)
    agent._observer = AgentObserver(agent.tracker, agent._execution_context)
    logger.info("[%s] Starting %sexecution", agent.name, "async " if async_mode else "")


def estimate_cost_for_response(agent: StandardAgent, llm_response):
    """Estimate cost for an LLM response."""
    return estimate_cost(llm_response, fallback_model=getattr(agent.llm, 'model', 'unknown'))
