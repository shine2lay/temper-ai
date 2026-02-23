"""Base agent interface and data structures.

Defines the abstract BaseAgent class that all agent implementations must inherit from,
along with AgentResponse and ExecutionContext data classes.

BaseAgent provides a template method pattern for execute():
  execute() → _validate_input → _setup → _on_setup → _run → _on_after_run
with error handling via _on_error / _build_error_response.

Subclasses implement _run() (the core logic) and optionally override hooks.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from temper_ai.storage.schemas import AgentConfig
from temper_ai.agent.models.response import AgentResponse, ToolCallRecord  # noqa: F401
from temper_ai.agent.utils.constants import OUTPUT_PREVIEW_LENGTH
from temper_ai.llm.prompts.engine import PromptEngine
from temper_ai.llm.providers.factory import create_llm_from_config
from temper_ai.shared.core.context import (
    ExecutionContext,  # canonical definition; re-exported here
)
from temper_ai.tools.loader import (
    apply_tool_config,
    ensure_tools_discovered,
    resolve_tool_config_templates,
    resolve_tool_spec,
)
from temper_ai.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def _register_mcp_tools(
    mcp_configs: list | None,
    registry: ToolRegistry,
) -> Any:
    """Register MCP tools from configured servers into the tool registry.

    Returns the MCPManager instance (caller should keep a reference for cleanup),
    or None if mcp_configs is empty / the mcp package is not installed.
    """
    if not mcp_configs:
        return None
    try:
        from temper_ai.mcp.manager import MCPManager

        manager = MCPManager(mcp_configs)
        tools = manager.connect_all()
        for tool in tools:
            registry.register(tool, allow_override=False)
        logger.info(
            "Registered %d MCP tools from %d servers",
            len(tools),
            len(mcp_configs),
        )
        return manager
    except ImportError:
        logger.warning(
            "MCP servers configured but 'mcp' package not installed. "
            "Install with: pip install 'temper-ai[mcp]'"
        )
        return None


def _sync_tool_configs_to_executor(
    agent_registry: ToolRegistry,
    tool_executor: Any,
    agent_name: str,
) -> None:
    """Sync agent tool configs to the tool_executor's registry.

    The safety-stack ToolExecutor has its own ToolRegistry with default
    tool instances (no agent-specific configs). This function copies the
    resolved configs from the agent's tools to matching tools in the
    executor's registry so that runtime config (e.g. allowed_root) is
    respected during execution.
    """
    exec_registry = getattr(tool_executor, "registry", None)
    if exec_registry is None:
        return
    try:
        agent_tools = agent_registry.get_all_tools()
    except (AttributeError, TypeError):
        return
    for tool_name, agent_tool in agent_tools.items():
        agent_config = getattr(agent_tool, "config", None)
        if not agent_config or not isinstance(agent_config, dict):
            continue
        # Skip internal keys
        config_to_sync = {
            k: v for k, v in agent_config.items() if not k.startswith("_")
        }
        if not config_to_sync:
            continue
        exec_tool = exec_registry.get(tool_name)
        if exec_tool is not None:
            apply_tool_config(exec_tool, tool_name, config_to_sync)


def load_tools_from_config(
    registry: Any,
    configured_tools: list[Any],
) -> None:
    """Load specific tools from configuration into *registry*."""
    ensure_tools_discovered(registry)
    available_tools = registry.list_tools()

    configured_names: set[str] = set()
    for tool_spec in configured_tools:
        tool_name, tool_config = resolve_tool_spec(tool_spec)
        tool_instance = registry.get(tool_name)

        if tool_instance is None:
            raise ValueError(
                f"Unknown tool '{tool_name}'. Available tools: {available_tools}\n"
                f"To add a new tool, create a BaseTool subclass in src/tools/"
            )

        configured_names.add(tool_name)
        apply_tool_config(tool_instance, tool_name, tool_config)

    for name in set(registry.list_tools()) - configured_names:
        registry.unregister(name)


class BaseAgent(ABC):
    """Abstract base class for all agents with template method pattern.

    Provides shared infrastructure (PromptEngine, LLM, observer, stream callback)
    and a template method execute() that calls hooks around the abstract _run().

    Subclasses must implement:
    - _run(input_data, context, start_time) → AgentResponse
    - get_capabilities() → Dict

    Optional hooks (no-op defaults):
    - _on_setup(input_data, context)
    - _on_before_run(input_data, context) → input_data
    - _on_after_run(result) → result
    - _on_error(error, start_time) → Optional[AgentResponse]
    """

    def __init__(self, config: AgentConfig):
        """Initialize agent with configuration, prompt engine, and LLM."""
        self.config = config
        self.name = config.agent.name
        self.description = config.agent.description
        self.version = config.agent.version

        self.prompt_engine = PromptEngine()
        if config.agent.inference is None:
            raise ValueError(f"Agent '{config.agent.name}' requires inference config")
        self.llm = create_llm_from_config(config.agent.inference)

        # Infrastructure attributes — set by _setup() at execution time
        self.tool_executor: Any = None
        self.tracker: Any = None
        self._observer: Any = None
        self._stream_callback: Any = None
        self._execution_context: Any = None
        self._mcp_manager: Any = None

    # ------------------------------------------------------------------
    # Template method: execute()
    # ------------------------------------------------------------------

    def execute(
        self, input_data: dict[str, Any], context: ExecutionContext | None = None
    ) -> AgentResponse:
        """Execute agent using template method pattern.

        Orchestrates: validate → setup → hooks → _run() → error handling.
        Subclasses implement _run() for their core logic.
        """
        self._validate_input(input_data, context)
        self._setup(input_data, context)
        self._on_setup(input_data, context)
        start_time = time.time()
        try:
            input_data = self._on_before_run(input_data, context)
            result = self._run(input_data, context, start_time)
            return self._on_after_run(result)
        except (
            Exception
        ) as e:  # noqa: BLE001 -- template method catch-all routes to _on_error hook
            custom = self._on_error(e, start_time)
            if custom is not None:
                return custom
            return self._build_error_response(e, start_time)

    @abstractmethod
    def _run(
        self,
        input_data: dict[str, Any],
        context: ExecutionContext | None,
        start_time: float,
    ) -> AgentResponse:
        """Core execution logic — subclasses implement this.

        Args:
            input_data: Validated input data dictionary
            context: Optional execution context
            start_time: time.time() when execute() started

        Returns:
            AgentResponse with output, reasoning, tool calls, and metrics
        """

    async def aexecute(
        self, input_data: dict[str, Any], context: ExecutionContext | None = None
    ) -> AgentResponse:
        """Async template method — mirrors execute() but calls _arun().

        Orchestrates: validate → setup → hooks → _arun() → error handling.
        Subclasses implement _arun() for native async logic.
        """
        self._validate_input(input_data, context)
        self._setup(input_data, context, async_mode=True)
        self._on_setup(input_data, context)
        start_time = time.time()
        try:
            input_data = self._on_before_run(input_data, context)
            result = await self._arun(input_data, context, start_time)
            return self._on_after_run(result)
        except (
            Exception
        ) as e:  # noqa: BLE001 -- template method catch-all routes to _on_error hook
            custom = self._on_error(e, start_time)
            if custom is not None:
                return custom
            return self._build_error_response(e, start_time, async_mode=True)

    async def _arun(
        self,
        input_data: dict[str, Any],
        context: ExecutionContext | None,
        start_time: float,
    ) -> AgentResponse:
        """Async core logic — default wraps sync _run() in a thread.

        Override for native async implementations (e.g., async LLM calls).
        """
        import asyncio

        return await asyncio.to_thread(self._run, input_data, context, start_time)

    @abstractmethod
    def get_capabilities(self) -> dict[str, Any]:
        """Get agent capabilities and metadata."""

    # ------------------------------------------------------------------
    # Hooks (no-op defaults — subclasses can override)
    # ------------------------------------------------------------------

    def _on_setup(
        self,
        input_data: dict[str, Any],
        context: ExecutionContext | None,
    ) -> None:
        """Hook called after _setup(), before _run(). Override for custom setup."""

    def _on_before_run(
        self,
        input_data: dict[str, Any],
        context: ExecutionContext | None,
    ) -> dict[str, Any]:
        """Hook called before _run(). Can modify input_data. Must return input_data."""
        return input_data

    def _on_after_run(self, result: AgentResponse) -> AgentResponse:
        """Hook called after _run() succeeds. Can modify result. Must return result."""
        return result

    def _on_error(self, error: Exception, start_time: float) -> AgentResponse | None:
        """Hook called on _run() error. Return AgentResponse to override default."""
        return None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_input(
        self,
        input_data: Any,
        context: ExecutionContext | None = None,
    ) -> None:
        """Validate input_data and context parameters."""
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

    def validate_config(self) -> bool:
        """Validate agent configuration."""
        if not self.config.agent.name:
            raise ValueError("Agent name is required")
        if not self.config.agent.inference:
            raise ValueError("Inference configuration is required")
        if not self.config.agent.prompt:
            raise ValueError("Prompt configuration is required")
        return True

    # ------------------------------------------------------------------
    # Execution setup
    # ------------------------------------------------------------------

    def _setup(
        self,
        input_data: dict[str, Any],
        context: ExecutionContext | None,
        async_mode: bool = False,
    ) -> None:
        """Common setup for sync and async execute paths."""
        from temper_ai.agent.utils.agent_observer import AgentObserver
        from temper_ai.tools.executor import ToolExecutor

        self._execution_context = context
        _tool_executor = input_data.get("tool_executor", None)
        if _tool_executor is not None:
            if not isinstance(_tool_executor, ToolExecutor):
                raise TypeError(
                    f"tool_executor must be a ToolExecutor instance, "
                    f"got {type(_tool_executor).__name__}"
                )
        self.tool_executor = _tool_executor
        self.tracker = input_data.get("tracker", None)
        self._observer = AgentObserver(self.tracker, self._execution_context)
        _stream_cb = input_data.get("stream_callback", None)
        if _stream_cb is not None and hasattr(_stream_cb, "make_callback"):
            self._stream_callback = _stream_cb.make_callback(self.name)
        else:
            self._stream_callback = _stream_cb

        agent_registry = getattr(self, "tool_registry", None)
        resolve_tool_config_templates(agent_registry, input_data, self.name)
        # Sync resolved tool configs to tool_executor's registry (the safety
        # stack has its own tool instances that lack agent-specific configs)
        if self.tool_executor is not None and agent_registry is not None:
            _sync_tool_configs_to_executor(
                agent_registry,
                self.tool_executor,
                self.name,
            )

        logger.info(
            "[%s] Starting %sexecution", self.name, "async " if async_mode else ""
        )

    # ------------------------------------------------------------------
    # Response building
    # ------------------------------------------------------------------

    def _build_response(
        self,
        output: str,
        reasoning: str | None,
        tool_calls: list[dict[str, Any]],
        tokens: int,
        cost: float,
        start_time: float,
        error: str | None = None,
    ) -> AgentResponse:
        """Build final AgentResponse with logging."""
        duration = time.time() - start_time
        output_preview = (
            (output[:OUTPUT_PREVIEW_LENGTH].replace("\n", " ").strip() + "...")
            if len(output) > OUTPUT_PREVIEW_LENGTH
            else output.replace("\n", " ").strip()
        )
        logger.info(
            "[%s] Execution complete (%d tokens, $%.4f, %.1fs) → %s",
            self.name,
            tokens,
            cost,
            duration,
            output_preview or "(empty)",
        )
        return AgentResponse(
            output=output,
            reasoning=reasoning,
            tool_calls=tool_calls,  # type: ignore[arg-type]
            tokens=tokens,
            estimated_cost_usd=cost,
            latency_seconds=time.time() - start_time,
            error=error,
        )

    def _build_error_response(
        self,
        error: Exception,
        start_time: float,
        tool_calls: list[dict[str, Any]] | None = None,
        total_tokens: int = 0,
        total_cost: float = 0.0,
        async_mode: bool = False,
    ) -> AgentResponse:
        """Build error response for agent execution failures."""
        from temper_ai.shared.utils.exceptions import sanitize_error_message

        safe_msg = sanitize_error_message(str(error))
        label = "Agent async execution error" if async_mode else "Agent execution error"
        logger.warning("%s: %s", label, safe_msg, exc_info=True)
        return self._build_response(
            output="",
            reasoning=None,
            tool_calls=tool_calls or [],
            tokens=total_tokens,
            cost=total_cost,
            start_time=start_time,
            error=f"Agent execution error: {safe_msg}",
        )

    # ------------------------------------------------------------------
    # Stream callback
    # ------------------------------------------------------------------

    def _make_stream_callback(self) -> Callable | None:
        """Create a combined stream callback for CLI display and observability."""
        user_cb = getattr(self, "_stream_callback", None)
        observer = getattr(self, "_observer", None)
        has_observer = observer is not None and observer.active

        if user_cb is None and not has_observer:
            return None

        def combined_callback(chunk: Any) -> None:
            """Forward stream chunk to user callback and observability."""
            if user_cb is not None:
                try:
                    user_cb(chunk)
                except (
                    Exception
                ):  # noqa: BLE001 -- streaming display must not disrupt execution
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
                except (
                    Exception
                ):  # noqa: BLE001 -- streaming event must not disrupt execution
                    pass

        return combined_callback

    # ------------------------------------------------------------------
    # Prompt rendering (shared base template logic)
    # ------------------------------------------------------------------

    def _render_template(
        self,
        input_data: dict[str, Any],
    ) -> str:
        """Render the base template with variables."""
        from temper_ai.llm.prompts.validation import (
            PromptRenderError,
            _is_safe_template_value,
        )

        prompt_config = self.config.agent.prompt
        if prompt_config is None:
            raise ValueError("No prompt configured for this agent")
        filtered_input = {
            k: v for k, v in input_data.items() if _is_safe_template_value(v)
        }
        all_variables = {**filtered_input, **prompt_config.variables}

        if prompt_config.template:
            try:
                return self.prompt_engine.render_file(
                    prompt_config.template, all_variables
                )
            except (PromptRenderError, ValueError, KeyError, FileNotFoundError) as e:
                raise PromptRenderError(
                    f"Failed to render template file {prompt_config.template}: {e}"
                )
        elif prompt_config.inline:
            return self.prompt_engine.render(prompt_config.inline, all_variables)
        else:
            raise ValueError("No prompt template or inline prompt configured")

    def _inject_input_context(
        self,
        template: str,
        input_data: dict[str, Any],
        exclude_keys: frozenset[str] = frozenset(),
    ) -> str:
        """Auto-inject string input context into template.

        Appends each string value from input_data as a labeled section,
        skipping keys in exclude_keys and non-safe template values.
        """
        from temper_ai.llm.prompts.validation import _is_safe_template_value

        input_parts: list[str] = []
        for key, value in input_data.items():
            if not _is_safe_template_value(value):
                continue
            if value and isinstance(value, str) and key not in exclude_keys:
                label = key.replace("_", " ").title()
                input_parts.append(f"## {label}\n{value}")

        if input_parts:
            return (
                template + "\n\n---\n\n# Input Context\n\n" + "\n\n".join(input_parts)
            )
        return template

    # ------------------------------------------------------------------
    # Tool registry creation (subclasses opt in)
    # ------------------------------------------------------------------

    def _create_tool_registry(self) -> ToolRegistry:
        """Create tool registry and load configured tools.

        Subclasses call this in __init__ if they need a tool registry.
        BaseAgent does NOT call this by default.
        """
        registry = ToolRegistry(auto_discover=False)
        configured_tools = self.config.agent.tools

        if configured_tools is None:
            registry.auto_discover()
        elif configured_tools:
            load_tools_from_config(registry, configured_tools)

        # Register MCP tools if configured (R1a)
        self._mcp_manager = _register_mcp_tools(
            getattr(self.config.agent, "mcp_servers", None),
            registry,
        )

        return registry
