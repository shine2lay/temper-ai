"""
Observability hooks for automatic execution tracking.

Provides decorators and utilities for hooking into agent execution
and automatically tracking to the observability database.
"""
import inspect
import threading
from functools import wraps
from typing import Any, Callable, Dict, Optional, cast

from src.observability.tracker import ExecutionTracker

# Global tracker instance (OB-06: double-check locking for thread safety)
_global_tracker: Optional[ExecutionTracker] = None
_tracker_lock = threading.Lock()


def get_tracker() -> ExecutionTracker:
    """
    Get the global execution tracker.

    Returns:
        ExecutionTracker instance

    Example:
        >>> tracker = get_tracker()
        >>> with tracker.track_workflow("test", {}) as wf_id:
        ...     pass
    """
    global _global_tracker
    if _global_tracker is None:
        with _tracker_lock:
            if _global_tracker is None:
                _global_tracker = ExecutionTracker()
    return _global_tracker


def set_tracker(tracker: ExecutionTracker) -> None:
    """
    Set custom global tracker (for testing).

    Args:
        tracker: ExecutionTracker instance
    """
    global _global_tracker
    _global_tracker = tracker


def reset_tracker() -> None:
    """Reset global tracker to None (for testing)."""
    global _global_tracker
    _global_tracker = None


def track_workflow(
    workflow_name: Optional[str] = None,
    get_config: Optional[Callable[..., Dict[str, Any]]] = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to track workflow execution.

    Args:
        workflow_name: Workflow name (or extract from function name)
        get_config: Function to get workflow config from args

    Example:
        >>> @track_workflow("my_workflow")
        ... def run_workflow(config):
        ...     return "result"
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        """Apply workflow tracking to function."""
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Execute function with workflow tracking."""
            name = workflow_name or func.__name__
            config = {}
            if get_config:
                config = get_config(*args, **kwargs)
            elif args:
                config = args[0] if isinstance(args[0], dict) else {}

            tracker = get_tracker()
            with tracker.track_workflow(name, config) as workflow_id:
                # Inject workflow_id into kwargs if function accepts it as a parameter
                if 'workflow_id' in inspect.signature(func).parameters:
                    kwargs['workflow_id'] = workflow_id

                result = func(*args, **kwargs)
                return result

        return wrapper
    return decorator


def track_stage(
    stage_name: Optional[str] = None,
    get_config: Optional[Callable[..., Dict[str, Any]]] = None,
    workflow_id_param: str = "workflow_id"
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to track stage execution.

    Args:
        stage_name: Stage name (or extract from function name)
        get_config: Function to get stage config from args
        workflow_id_param: Name of workflow_id parameter

    Example:
        >>> @track_stage("research_stage")
        ... def run_stage(config, workflow_id):
        ...     return "result"
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        """Apply stage tracking to function."""
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Execute function with stage tracking."""
            name = stage_name or func.__name__
            config = {}
            if get_config:
                config = get_config(*args, **kwargs)
            elif args:
                config = args[0] if isinstance(args[0], dict) else {}

            # Get workflow_id from kwargs or args
            workflow_id = kwargs.get(workflow_id_param)
            if not workflow_id and args and len(args) > 1:
                workflow_id = args[1]

            tracker = get_tracker()
            with tracker.track_stage(name, config, cast(str, workflow_id)) as stage_id:
                # Inject stage_id into kwargs if function accepts it as a parameter
                if 'stage_id' in inspect.signature(func).parameters:
                    kwargs['stage_id'] = stage_id

                result = func(*args, **kwargs)
                return result

        return wrapper
    return decorator


def track_agent(
    agent_name: Optional[str] = None,
    get_config: Optional[Callable[..., Dict[str, Any]]] = None,
    stage_id_param: str = "stage_id"
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to track agent execution.

    Args:
        agent_name: Agent name (or extract from function name)
        get_config: Function to get agent config from args
        stage_id_param: Name of stage_id parameter

    Example:
        >>> @track_agent("researcher")
        ... def run_agent(config, stage_id):
        ...     return "result"
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        """Apply agent tracking to function."""
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Execute function with agent tracking."""
            name = agent_name or func.__name__
            config = {}
            if get_config:
                config = get_config(*args, **kwargs)
            elif args:
                config = args[0] if isinstance(args[0], dict) else {}

            # Get stage_id from kwargs or args
            stage_id = kwargs.get(stage_id_param)
            if not stage_id and args and len(args) > 1:
                stage_id = args[1]

            tracker = get_tracker()
            with tracker.track_agent(name, config, cast(str, stage_id)) as agent_id:
                # Inject agent_id into kwargs if function accepts it as a parameter
                if 'agent_id' in inspect.signature(func).parameters:
                    kwargs['agent_id'] = agent_id

                result = func(*args, **kwargs)
                return result

        return wrapper
    return decorator


class ExecutionHook:
    """
    Hook for manually tracking execution events.

    Provides manual control over tracking without decorators.

    Example:
        >>> hook = ExecutionHook()
        >>> hook.start_workflow("test", {})
        'workflow-id-123'
        >>> hook.start_agent("researcher", {}, "stage-id-456")
        'agent-id-789'
        >>> hook.log_llm_call("agent-id-789", ...)
        >>> hook.end_agent("agent-id-789")
        >>> hook.end_workflow("workflow-id-123")
    """

    def __init__(self, tracker: Optional[ExecutionTracker] = None):
        """
        Initialize execution hook.

        Args:
            tracker: ExecutionTracker instance (or use global)
        """
        self.tracker = tracker or get_tracker()
        self._active_contexts: Dict[str, Any] = {}

    def start_workflow(
        self,
        workflow_name: str,
        workflow_config: Dict[str, Any],
        **kwargs: Any
    ) -> str:
        """
        Start tracking workflow.

        Args:
            workflow_name: Workflow name
            workflow_config: Workflow configuration
            **kwargs: Additional tracking parameters

        Returns:
            workflow_id: UUID of workflow execution
        """
        ctx = self.tracker.track_workflow(workflow_name, workflow_config, **kwargs)
        workflow_id = ctx.__enter__()
        self._active_contexts[workflow_id] = ctx
        return workflow_id

    def end_workflow(self, workflow_id: str, error: Optional[Exception] = None) -> None:
        """
        End tracking workflow.

        Args:
            workflow_id: Workflow execution ID
            error: Exception if workflow failed
        """
        ctx = self._active_contexts.pop(workflow_id, None)
        if ctx:
            if error:
                # OB-07: Pass the real traceback so stack traces are preserved.
                ctx.__exit__(type(error), error, error.__traceback__)
            else:
                ctx.__exit__(None, None, None)

    def start_stage(
        self,
        stage_name: str,
        stage_config: Dict[str, Any],
        workflow_id: str,
        input_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Start tracking stage.

        Args:
            stage_name: Stage name
            stage_config: Stage configuration
            workflow_id: Parent workflow ID
            input_data: Stage input data

        Returns:
            stage_id: UUID of stage execution
        """
        ctx = self.tracker.track_stage(stage_name, stage_config, workflow_id, input_data)
        stage_id = ctx.__enter__()
        self._active_contexts[stage_id] = ctx
        return stage_id

    def end_stage(self, stage_id: str, error: Optional[Exception] = None) -> None:
        """
        End tracking stage.

        Args:
            stage_id: Stage execution ID
            error: Exception if stage failed
        """
        ctx = self._active_contexts.pop(stage_id, None)
        if ctx:
            if error:
                ctx.__exit__(type(error), error, None)
            else:
                ctx.__exit__(None, None, None)

    def start_agent(
        self,
        agent_name: str,
        agent_config: Dict[str, Any],
        stage_id: str,
        input_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Start tracking agent.

        Args:
            agent_name: Agent name
            agent_config: Agent configuration
            stage_id: Parent stage ID
            input_data: Agent input data

        Returns:
            agent_id: UUID of agent execution
        """
        ctx = self.tracker.track_agent(agent_name, agent_config, stage_id, input_data)
        agent_id = ctx.__enter__()
        self._active_contexts[agent_id] = ctx
        return agent_id

    def end_agent(self, agent_id: str, error: Optional[Exception] = None) -> None:
        """
        End tracking agent.

        Args:
            agent_id: Agent execution ID
            error: Exception if agent failed
        """
        ctx = self._active_contexts.pop(agent_id, None)
        if ctx:
            if error:
                ctx.__exit__(type(error), error, None)
            else:
                ctx.__exit__(None, None, None)

    def log_llm_call(
        self,
        agent_id: str,
        provider: str,
        model: str,
        prompt: str,
        response: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        cost: float
    ) -> str:
        """
        Log LLM call.

        Args:
            agent_id: Parent agent ID
            provider: LLM provider
            model: Model name
            prompt: Input prompt
            response: LLM response
            prompt_tokens: Prompt tokens
            completion_tokens: Completion tokens
            latency_ms: Latency in ms
            cost: Estimated cost in USD

        Returns:
            llm_call_id: UUID of LLM call
        """
        return self.tracker.track_llm_call(
            agent_id,
            provider,
            model,
            prompt,
            response,
            prompt_tokens,
            completion_tokens,
            latency_ms,
            cost
        )

    def log_tool_call(
        self,
        agent_id: str,
        tool_name: str,
        input_params: Dict[str, Any],
        output_data: Dict[str, Any],
        duration: float,
        status: str = "success"
    ) -> str:
        """
        Log tool execution.

        Args:
            agent_id: Parent agent ID
            tool_name: Tool name
            input_params: Tool input
            output_data: Tool output
            duration: Execution duration in seconds
            status: Execution status

        Returns:
            tool_execution_id: UUID of tool execution
        """
        return self.tracker.track_tool_call(
            agent_id,
            tool_name,
            input_params,
            output_data,
            duration,
            status
        )
