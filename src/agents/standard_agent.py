"""Standard agent implementation with LLM and tool execution.

StandardAgent is the default agent type that executes a multi-turn loop:
1. Render prompt with input
2. Call LLM
3. Parse tool calls from LLM response
4. Execute tools
5. Inject tool results back into prompt
6. Repeat until no more tool calls or max iterations reached
"""
from __future__ import annotations

import json
import logging
import time
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from datetime import datetime, timezone

if TYPE_CHECKING:
    from src.compiler.schemas import AgentConfig

from src.agents.base_agent import BaseAgent, AgentResponse, ExecutionContext
from src.agents.llm_providers import (
    BaseLLM,
    OllamaLLM,
    OpenAILLM,
    AnthropicLLM,
    LLMResponse,
    LLMError,
    LLMProvider
)
from src.agents.prompt_engine import PromptEngine, PromptRenderError
from src.agents.llm_factory import create_llm_provider
from src.agents.cost_estimator import estimate_cost
from src.agents.response_parser import (
    parse_tool_calls,
    sanitize_tool_output,
    extract_final_answer,
    extract_reasoning,
    TOOL_CALL_TAG,
    ANSWER_TAG,
    REASONING_TAGS,
    TOOL_CALL_PATTERN,
    ANSWER_PATTERN,
    REASONING_PATTERNS,
    _TOOL_RESULT_SANITIZE_PATTERN,
)
from src.agents.agent_observer import AgentObserver
from src.tools.registry import ToolRegistry
from src.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Re-export constants for backward compatibility
_SANITIZE_TAGS = [TOOL_CALL_TAG, ANSWER_TAG] + REASONING_TAGS

# Note: Cost estimation constants removed - now using config/model_pricing.yaml
# See src/agents/pricing.py for pricing configuration

# Default port numbers for LLM providers (kept for backward compatibility)
OLLAMA_DEFAULT_PORT = 11434


def validate_input_data(
    input_data: Any,
    context: Optional[ExecutionContext] = None
) -> None:
    """Validate input_data and context parameters.

    Args:
        input_data: Input data dictionary to validate
        context: Optional execution context to validate

    Raises:
        ValueError: If input_data is None
        TypeError: If input_data is not a dictionary or context is invalid
    """
    if input_data is None:
        raise ValueError("input_data cannot be None")

    if not isinstance(input_data, dict):
        raise TypeError(
            f"input_data must be a dictionary, got {type(input_data).__name__}"
        )

    if context is not None and not isinstance(context, ExecutionContext):
        raise TypeError(
            f"context must be an ExecutionContext instance, got {type(context).__name__}"
        )


class StandardAgent(BaseAgent):
    """Standard agent with LLM and tool execution loop.

    This is the primary agent implementation that handles:
    - Prompt rendering from templates
    - LLM inference with retry logic
    - Tool calling (function calling) parsing and execution
    - Multi-turn conversation for complex tasks
    - Token usage and cost tracking
    """

    def __init__(self, config: AgentConfig):
        """Initialize standard agent from configuration."""
        super().__init__(config)

        self.prompt_engine = PromptEngine()
        self.llm = create_llm_provider(self.config.agent.inference)
        self.tool_registry = self._create_tool_registry()

        # Initialize prompt caching
        self._cached_tool_schemas: Optional[str] = None
        self._tool_registry_version: int = 0

        self.validate_config()

    def _create_tool_registry(self) -> ToolRegistry:
        """Create tool registry and load configured tools."""
        registry = ToolRegistry(auto_discover=False)

        configured_tools = self.config.agent.tools

        if not configured_tools:
            registry.auto_discover()
        else:
            self._load_tools_from_config(registry, configured_tools)

        return registry

    def _load_tools_from_config(
        self,
        registry: ToolRegistry,
        configured_tools: List[Any]
    ) -> None:
        """Load specific tools from configuration."""
        if len(registry.list_tools()) == 0:
            discovered_count = registry.auto_discover()
            if discovered_count == 0:
                logger.warning(
                    "No tools discovered via auto-discovery. "
                    "Check that src/tools/ contains valid BaseTool subclasses."
                )

        available_tools = registry.list_tools()

        for tool_spec in configured_tools:
            tool_name: str
            tool_config: Dict[str, Any]
            if isinstance(tool_spec, str):
                tool_name = tool_spec
                tool_config = {}
            else:
                tool_name = tool_spec.name
                tool_config = tool_spec.config if hasattr(tool_spec, 'config') else {}

            tool_instance = registry.get(tool_name)

            if tool_instance is None:
                raise ValueError(
                    f"Unknown tool '{tool_name}'. Available tools: {available_tools}\n"
                    f"To add a new tool, create a BaseTool subclass in src/tools/"
                )

            if tool_config:
                logger.debug(f"Tool config provided for {tool_name}: {tool_config}")

    def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None
    ) -> AgentResponse:
        """Execute agent with input data.

        Main execution loop:
        1. Render prompt with input
        2. Call LLM
        3. Parse tool calls
        4. Execute tools
        5. Inject results and repeat
        6. Return final response
        """
        validate_input_data(input_data, context)

        self._execution_context = context
        self.tool_executor = input_data.get('tool_executor', None)
        self.tracker = input_data.get('tracker', None)
        self._observer = AgentObserver(self.tracker, self._execution_context)
        logger.info("[%s] Starting execution", self.name)

        start_time = time.time()
        tool_calls_made: list[dict[str, Any]] = []
        total_tokens = 0
        total_cost = 0.0
        llm_response = None

        try:
            prompt = self._render_prompt(input_data, context)

            max_iterations = self.config.agent.safety.max_tool_calls_per_execution
            max_execution_time = self.config.agent.safety.max_execution_time_seconds

            for iteration in range(max_iterations):
                elapsed = time.time() - start_time
                if elapsed >= max_execution_time:
                    return self._build_final_response(
                        output=llm_response.content if llm_response else "",
                        reasoning=extract_reasoning(llm_response.content) if llm_response else None,
                        tool_calls=tool_calls_made,
                        tokens=total_tokens,
                        cost=total_cost,
                        start_time=start_time,
                        error=f"Execution time limit exceeded ({max_execution_time}s)",
                        metadata={"elapsed_seconds": elapsed, "iteration": iteration}
                    )

                iteration_result = self._execute_iteration(
                    prompt, total_tokens, total_cost, tool_calls_made, start_time, max_iterations
                )

                if iteration_result["complete"]:
                    return iteration_result["response"]  # type: ignore[no-any-return]

                llm_response = iteration_result["llm_response"]
                prompt = iteration_result["next_prompt"]
                total_tokens = iteration_result["total_tokens"]
                total_cost = iteration_result["total_cost"]
                tool_calls_made = iteration_result["tool_calls_made"]

            return self._build_final_response(
                output=llm_response.content if llm_response else "",
                reasoning=extract_reasoning(llm_response.content) if llm_response else None,
                tool_calls=tool_calls_made,
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
                error="Max tool calling iterations reached",
                metadata={"iterations": max_iterations}
            )

        except Exception as e:
            logger.warning("Agent execution error: %s", str(e), exc_info=True)
            return self._build_final_response(
                output="",
                reasoning=None,
                tool_calls=tool_calls_made,
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
                error=f"Agent execution error: {str(e)}"
            )

    def _execute_iteration(
        self,
        prompt: str,
        total_tokens: int,
        total_cost: float,
        tool_calls_made: List[Dict[str, Any]],
        start_time: float,
        max_iterations: Optional[int] = None
    ) -> Dict[str, Any]:
        """Execute single iteration of the tool calling loop."""
        inf_config = self.config.agent.inference
        max_agent_retries = inf_config.max_retries
        retry_delay = float(inf_config.retry_delay_seconds)

        # Safety validation for LLM calls (if policy engine available)
        if hasattr(self, 'tool_executor') and self.tool_executor is not None:
            if self.tool_executor.policy_engine is not None:
                try:
                    from src.safety.action_policy_engine import PolicyExecutionContext

                    ctx = getattr(self, '_execution_context', None)
                    agent_id = ctx.agent_id if ctx and ctx.agent_id else self.config.agent.name
                    workflow_id = ctx.workflow_id if ctx and ctx.workflow_id else "unknown"
                    stage_id = ctx.stage_id if ctx and ctx.stage_id else "unknown"

                    validation_result = self.tool_executor.policy_engine.validate_action_sync(
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
                            "response": self._build_final_response(
                                output="",
                                reasoning=None,
                                tool_calls=tool_calls_made,
                                tokens=total_tokens,
                                cost=total_cost,
                                start_time=start_time,
                                error=f"LLM call blocked by safety policy: {violations_msg}"
                            )
                        }
                except Exception as e:
                    logger.warning(f"LLM call safety validation error: {e}")

        # Call LLM with agent-level retries
        llm_response = None
        last_error = None

        for attempt in range(max_agent_retries + 1):
            try:
                llm_kwargs: Dict[str, Any] = {}
                native_tools = self._get_native_tool_definitions()
                if native_tools:
                    llm_kwargs["tools"] = native_tools
                llm_response = self.llm.complete(prompt, **llm_kwargs)
                logger.info(
                    "[%s] LLM responded (%s tokens)",
                    self.name,
                    llm_response.total_tokens or "?",
                )
                break
            except LLMError as e:
                last_error = e
                if attempt < max_agent_retries:
                    backoff_delay = retry_delay * (2.0 ** attempt)
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1, max_agent_retries + 1, str(e), backoff_delay
                    )
                    time.sleep(backoff_delay)
                else:
                    logger.error(
                        "LLM call failed after %d attempts: %s",
                        max_agent_retries + 1, str(e), exc_info=True
                    )

        if llm_response is None:
            return {
                "complete": True,
                "response": self._build_final_response(
                    output="",
                    reasoning=None,
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    start_time=start_time,
                    error=f"LLM call failed after {max_agent_retries + 1} attempts: {str(last_error)}"
                )
            }

        # Track tokens and cost
        if llm_response.total_tokens:
            total_tokens += llm_response.total_tokens
        total_cost += self._estimate_cost(llm_response)

        # Track LLM call via observer
        self._observer.track_llm_call(
            provider=inf_config.provider,
            model=inf_config.model,
            prompt=prompt,
            response=llm_response.content,
            prompt_tokens=llm_response.prompt_tokens or 0,
            completion_tokens=llm_response.completion_tokens or 0,
            latency_ms=int(llm_response.latency_ms) if hasattr(llm_response, 'latency_ms') and llm_response.latency_ms else 0,
            estimated_cost_usd=self._estimate_cost(llm_response),
            temperature=inf_config.temperature,
            max_tokens=inf_config.max_tokens,
            status="success"
        )

        # Parse tool calls
        tool_calls = parse_tool_calls(llm_response.content)

        if tool_calls:
            tool_names = ", ".join(tc.get("name", "?") for tc in tool_calls)
            logger.info("[%s] Calling %d tool(s): %s", self.name, len(tool_calls), tool_names)

        if not tool_calls:
            return {
                "complete": True,
                "response": self._build_final_response(
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
        tool_results = self._execute_tool_calls(tool_calls)
        tool_calls_made.extend(tool_results)

        remaining_budget = None
        if max_iterations is not None:
            remaining_budget = max_iterations - len(tool_calls_made)

        next_prompt = self._inject_tool_results(
            prompt, llm_response.content, tool_results,
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

    def _execute_tool_calls(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute a list of tool calls (parallel if independent, sequential if dependent)."""
        if not isinstance(tool_calls, list):
            raise TypeError(f"tool_calls must be a list, got {type(tool_calls).__name__}")

        for i, tool_call in enumerate(tool_calls):
            if not isinstance(tool_call, dict):
                raise TypeError(f"tool_call at index {i} must be a dictionary, got {type(tool_call).__name__}")

        if len(tool_calls) <= 1:
            return [self._execute_single_tool(tool_call) for tool_call in tool_calls]

        parallel_enabled = getattr(self.config.agent.safety, "parallel_tool_calls", True)

        if not parallel_enabled:
            return [self._execute_single_tool(tool_call) for tool_call in tool_calls]

        import concurrent.futures

        tool_results = [None] * len(tool_calls)

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tool_calls), 4)) as executor:
            future_to_index = {
                executor.submit(self._execute_single_tool, tool_call): i
                for i, tool_call in enumerate(tool_calls)
            }

            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result = future.result()
                    tool_results[index] = result
                except Exception as e:
                    logger.error(f"Tool execution failed in parallel mode: {e}")
                    tool_results[index] = {
                        "name": tool_calls[index].get("name", "unknown"),
                        "parameters": tool_calls[index].get("parameters", {}),
                        "success": False,
                        "result": None,
                        "error": f"Parallel execution error: {str(e)}"
                    }

        return tool_results

    def _execute_single_tool(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
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
        # These run regardless of whether tool_executor is configured.
        safety = self.config.agent.safety

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
        if hasattr(self, 'tool_executor') and self.tool_executor is not None:
            return self._execute_via_tool_executor(tool_name, tool_params)

        # SECURITY: No silent fallback — tool_executor is required for safe execution.
        # Without it, the full safety stack (PolicyRegistry, ActionPolicyEngine,
        # ApprovalWorkflow, RollbackManager) is bypassed.
        logger.critical(
            "SECURITY: No tool_executor configured for agent '%s'. "
            "Tool '%s' execution blocked to prevent safety bypass.",
            self.name, tool_name
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

    def _execute_via_tool_executor(self, tool_name: str, tool_params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute tool through the safety-integrated ToolExecutor."""
        tool_start_time = time.time()
        try:
            result = self.tool_executor.execute(tool_name, tool_params)
            duration_seconds = time.time() - tool_start_time
            logger.info(
                "[%s] Tool '%s' %s (%.1fs)",
                self.name, tool_name,
                "succeeded" if result.success else "failed",
                duration_seconds,
            )

            self._observer.track_tool_call(
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
        except Exception as e:
            duration_seconds = time.time() - tool_start_time

            self._observer.track_tool_call(
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

    def _build_final_response(
        self,
        output: str,
        reasoning: Optional[str],
        tool_calls: List[Dict[str, Any]],
        tokens: int,
        cost: float,
        start_time: float,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AgentResponse:
        """Build final AgentResponse."""
        duration = time.time() - start_time
        logger.info(
            "[%s] Execution complete (%d tokens, $%.4f, %.1fs)",
            self.name, tokens, cost, duration,
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

    def _render_prompt(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None
    ) -> str:
        """Render prompt template with input data and tools."""
        validate_input_data(input_data, context)

        prompt_config = self.config.agent.prompt

        internal_vars = {'tracker', 'config_loader', 'tool_registry', 'workflow_id', 'tool_executor'}
        filtered_input = {k: v for k, v in input_data.items() if k not in internal_vars}

        all_variables = {**filtered_input, **prompt_config.variables}

        if prompt_config.template:
            try:
                template = self.prompt_engine.render_file(
                    prompt_config.template,
                    all_variables
                )
            except Exception as e:
                raise PromptRenderError(
                    f"Failed to render template file {prompt_config.template}: {e}"
                )
        elif prompt_config.inline:
            template = self.prompt_engine.render(
                prompt_config.inline,
                all_variables
            )
        else:
            raise ValueError("No prompt template or inline prompt configured")

        if not self._get_native_tool_definitions():
            tools_section = self._get_cached_tool_schemas()
            if tools_section:
                template += tools_section

        return template

    def _get_cached_tool_schemas(self) -> Optional[str]:
        """Get cached tool schemas or build and cache them."""
        tools_dict = self.tool_registry.get_all_tools()
        if not tools_dict:
            return None

        current_version = len(tools_dict)
        if self._cached_tool_schemas is not None and self._tool_registry_version == current_version:
            return self._cached_tool_schemas

        tool_schemas = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.get_parameters_schema()
            }
            for tool in tools_dict.values()
        ]
        tools_section = "\n\nAvailable Tools:\n" + json.dumps(tool_schemas, indent=2)

        self._cached_tool_schemas = tools_section
        self._tool_registry_version = current_version

        return tools_section

    def _get_native_tool_definitions(self) -> Optional[List[Dict[str, Any]]]:
        """Build native tool definitions for providers that support them."""
        if not isinstance(self.llm, (OllamaLLM, OpenAILLM, AnthropicLLM)):
            return None

        tools_dict = self.tool_registry.get_all_tools()
        if not tools_dict:
            return None

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

        return native_tools if native_tools else None

    # Delegate to extracted modules for backward compatibility
    def _parse_tool_calls(self, llm_response: str) -> List[Dict[str, Any]]:
        return parse_tool_calls(llm_response)

    @staticmethod
    def _sanitize_tool_output(text: str) -> str:
        return sanitize_tool_output(text)

    def _extract_final_answer(self, llm_response: str) -> str:
        return extract_final_answer(llm_response)

    def _extract_reasoning(self, llm_response: str) -> Optional[str]:
        return extract_reasoning(llm_response)

    def _estimate_cost(self, llm_response: LLMResponse) -> float:
        return estimate_cost(llm_response, fallback_model=getattr(self.llm, 'model', 'unknown'))

    def _inject_tool_results(
        self,
        original_prompt: str,
        llm_response: str,
        tool_results: List[Dict[str, Any]],
        remaining_tool_calls: Optional[int] = None
    ) -> str:
        """Inject tool results into prompt for next iteration."""
        MAX_TOOL_RESULT_SIZE = 10_000

        results_parts = ["\n\nTool Results:\n"]
        for result in tool_results:
            results_parts.append(f"\nTool: {result['name']}\n")
            results_parts.append(f"Parameters: {json.dumps(result['parameters'])}\n")
            if result['success']:
                safe_result = sanitize_tool_output(str(result['result']))

                if len(safe_result) > MAX_TOOL_RESULT_SIZE:
                    original_size = len(safe_result)
                    safe_result = safe_result[:MAX_TOOL_RESULT_SIZE]
                    safe_result += f"\n[truncated — {original_size:,} total chars, showing first {MAX_TOOL_RESULT_SIZE:,}]"

                results_parts.append(f"Result: {safe_result}\n")
            else:
                safe_error = sanitize_tool_output(str(result['error']))

                if len(safe_error) > MAX_TOOL_RESULT_SIZE:
                    original_size = len(safe_error)
                    safe_error = safe_error[:MAX_TOOL_RESULT_SIZE]
                    safe_error += f"\n[truncated — {original_size:,} total chars, showing first {MAX_TOOL_RESULT_SIZE:,}]"

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

        MAX_PROMPT_CHARS = 100_000
        new_prompt = original_prompt + "\n\nAssistant: " + llm_response + results_text + "\n\nPlease continue:"
        if len(new_prompt) > MAX_PROMPT_CHARS:
            new_prompt = "...(truncated)...\n" + new_prompt[-MAX_PROMPT_CHARS:]
        return new_prompt

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
            "supports_streaming": False,
            "supports_multimodal": False
        }
