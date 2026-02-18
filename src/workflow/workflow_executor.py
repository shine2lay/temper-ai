"""Workflow executor for running compiled LangGraph workflows.

Wraps compiled StateGraph and provides execution interface with observability.
Supports checkpoint/resume capability for fault tolerance and long-running workflows.
"""
import dataclasses
import logging
from typing import Any, Dict, Iterator, Optional, cast

from langgraph.graph import StateGraph

from src.workflow.checkpoint_manager import CheckpointManager
from src.workflow.domain_state import WorkflowDomainState
from src.workflow.state_manager import initialize_state

logger = logging.getLogger(__name__)


def _save_checkpoint_on_interval(
    checkpoint_manager: Any,
    final_state: Any,
    tracker: Optional[Any],
    stage_count: int,
    stage_name: str,
    workflow_id: str
) -> None:
    """Save checkpoint and track event."""
    import dataclasses

    from src.workflow.domain_state import WorkflowDomainState

    domain_fields = {f.name for f in dataclasses.fields(WorkflowDomainState)}
    domain_dict = {k: v for k, v in final_state.items() if k in domain_fields}
    domain_state = WorkflowDomainState.from_dict(domain_dict)

    checkpoint_manager.save_checkpoint(domain_state)

    if tracker:
        tracker.log_event(
            "checkpoint_saved",
            {
                "workflow_id": workflow_id,
                "stage": stage_name,
                "stage_count": stage_count
            }
        )


def _save_checkpoint_on_error(
    checkpoint_manager: Any,
    final_state: Any,
    tracker: Optional[Any],
    workflow_id: str,
    error: Exception,
    stage_count: int
) -> None:
    """Save checkpoint on error and log."""
    import dataclasses

    from src.workflow.domain_state import WorkflowDomainState

    try:
        domain_fields = {f.name for f in dataclasses.fields(WorkflowDomainState)}
        domain_dict = {k: v for k, v in final_state.items() if k in domain_fields}
        domain_state = WorkflowDomainState.from_dict(domain_dict)

        checkpoint_manager.save_checkpoint(domain_state)

        if tracker:
            tracker.log_event(
                "checkpoint_saved_on_error",
                {
                    "workflow_id": workflow_id,
                    "error": str(error),
                    "stage_count": stage_count
                }
            )
    except Exception as checkpoint_error:
        logger.error(
            "Failed to save checkpoint for workflow %s: %s",
            workflow_id,
            checkpoint_error,
            exc_info=True
        )
        if tracker:
            tracker.log_event(
                "checkpoint_save_failed",
                {"error": str(checkpoint_error)}
            )


class CompiledGraphRunner:
    """Executes compiled workflows with observability.

    Wraps the compiled StateGraph and provides convenience methods
    for execution with state initialization and tracking.

    Example:
        >>> executor = CompiledGraphRunner(compiled_graph, tracker=tracker)
        >>> result = executor.execute({"input": "data"})
    """

    def __init__(
        self,
        graph: StateGraph[Any],
        tracker: Optional[Any] = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
        enable_checkpoints: bool = False
    ) -> None:
        """Initialize executor.

        Args:
            graph: Compiled StateGraph from LangGraphCompiler
            tracker: ExecutionTracker for observability (optional)
            checkpoint_manager: CheckpointManager for checkpoint/resume (optional)
            enable_checkpoints: Enable automatic checkpointing (default: False)
        """
        self.graph = graph
        self.tracker = tracker
        self.checkpoint_manager = checkpoint_manager
        self.enable_checkpoints = enable_checkpoints

        # Initialize checkpoint manager if checkpoints enabled but not provided.
        # NOTE: The default CheckpointManager may use SQLite with StaticPool
        # (via src.observability.database). StaticPool with SQLite is
        # development-only. In production, use a proper connection pool
        # (e.g., PostgreSQL with pool_size settings). StaticPool shares a
        # single connection across all threads, which is sufficient for
        # testing but will cause contention under load.
        if enable_checkpoints and checkpoint_manager is None:
            self.checkpoint_manager = CheckpointManager()

    def execute(
        self,
        input_data: Dict[str, Any],
        workflow_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute workflow with given input.

        Synchronously executes the compiled workflow graph with the provided
        input data. Initializes workflow state, invokes the graph, and returns
        the final state with all stage outputs.

        Args:
            input_data: Input data for workflow (e.g., {"topic": "AI safety"})
            workflow_id: Optional workflow execution ID for tracking

        Returns:
            Final workflow state dict with stage outputs

        Example:
            >>> result = executor.execute(
            ...     input_data={"topic": "quantum computing"},
            ...     workflow_id="wf-custom-123"
            ... )
            >>> print(result["stage_outputs"]["research"])
        """
        # Prepare initial state using state manager
        state = initialize_state(
            input_data=input_data,
            workflow_id=workflow_id,
            tracker=self.tracker
        )

        # Execute graph
        result = self.graph.invoke(state)  # type: ignore[attr-defined]

        return cast(Dict[str, Any], result)

    async def execute_async(
        self,
        input_data: Dict[str, Any],
        workflow_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute workflow asynchronously.

        Asynchronously executes the compiled workflow graph. Useful for
        long-running workflows or when integrating with async frameworks.

        Args:
            input_data: Input data for workflow
            workflow_id: Optional workflow execution ID for tracking

        Returns:
            Final workflow state dict with stage outputs

        Example:
            >>> result = await executor.execute_async(
            ...     input_data={"topic": "climate change"},
            ...     workflow_id="wf-async-456"
            ... )
        """
        # Prepare initial state using state manager
        state = initialize_state(
            input_data=input_data,
            workflow_id=workflow_id,
            tracker=self.tracker
        )

        # Execute graph asynchronously
        result = await self.graph.ainvoke(state)  # type: ignore[attr-defined]

        return cast(Dict[str, Any], result)

    def stream(
        self,
        input_data: Dict[str, Any],
        workflow_id: Optional[str] = None
    ) -> Iterator[Any]:
        """Stream workflow execution for real-time updates.

        Yields intermediate states as the workflow executes, allowing
        for real-time monitoring and progress updates.

        Args:
            input_data: Input data for workflow
            workflow_id: Optional workflow execution ID

        Yields:
            Intermediate workflow states during execution

        Example:
            >>> for state in executor.stream({"topic": "robotics"}):
            ...     print(f"Current stage: {state.get('current_stage')}")
        """
        # Prepare initial state
        state = initialize_state(
            input_data=input_data,
            workflow_id=workflow_id,
            tracker=self.tracker
        )

        # Stream execution
        for chunk in self.graph.stream(state):  # type: ignore[attr-defined]
            yield chunk

    def execute_with_checkpoints(
        self,
        input_data: Dict[str, Any],
        workflow_id: Optional[str] = None,
        checkpoint_interval: int = 1
    ) -> Dict[str, Any]:
        """Execute workflow with automatic checkpointing.

        Saves checkpoints at regular intervals during execution. If execution
        is interrupted, it can be resumed from the last checkpoint.

        Args:
            input_data: Input data for workflow
            workflow_id: Optional workflow execution ID
            checkpoint_interval: Save checkpoint after this many stages (default: 1)

        Returns:
            Final workflow state dict

        Example:
            >>> # Enable checkpoints and execute
            >>> executor = CompiledGraphRunner(graph, enable_checkpoints=True)
            >>> result = executor.execute_with_checkpoints(
            ...     {"topic": "AI safety"},
            ...     workflow_id="wf-123"
            ... )
        """
        if self.checkpoint_manager is None:
            raise RuntimeError("Checkpoint manager not configured. Set enable_checkpoints=True or provide checkpoint_manager")

        # Prepare initial state
        state = initialize_state(
            input_data=input_data,
            workflow_id=workflow_id,
            tracker=self.tracker
        )

        # Execute with streaming checkpoints
        final_state = None
        stage_count = 0

        try:
            for chunk in self.graph.stream(state):  # type: ignore[attr-defined]
                # chunk format: {stage_name: updated_state}
                # Update final state with latest chunk
                if chunk:
                    # Get the updated state from the chunk
                    # (chunk is dict with single key = stage name)
                    stage_name = list(chunk.keys())[0]
                    final_state = chunk[stage_name]
                    stage_count += 1

                    # Checkpoint after checkpoint_interval stages
                    if stage_count % checkpoint_interval == 0:
                        _save_checkpoint_on_interval(
                            self.checkpoint_manager, final_state, self.tracker,
                            stage_count, stage_name,
                            final_state.get("workflow_id", "unknown")
                        )

            # Ensure we have a final state
            if final_state is None:
                raise RuntimeError("Workflow execution produced no output")

            # Save final checkpoint
            domain_state = self._extract_domain_state(final_state)
            self.checkpoint_manager.save_checkpoint(
                domain_state
            )

            return cast(Dict[str, Any], final_state)

        except Exception as e:
            # On error, save checkpoint at failure point if we have state
            if final_state is not None:
                _save_checkpoint_on_error(
                    self.checkpoint_manager, final_state, self.tracker,
                    final_state.get("workflow_id", "unknown"), e, stage_count
                )

            # Re-raise original error
            raise

    def _load_and_prepare_checkpoint(
        self,
        workflow_id: str,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> tuple[Any, Dict[str, Any]]:
        """Load checkpoint, merge input, and return (domain_state, state_dict)."""
        if self.checkpoint_manager is None:
            raise ValueError("checkpoint_manager required for checkpoint loading")
        domain_state = self.checkpoint_manager.load_checkpoint(workflow_id)

        if self.tracker:
            self.tracker.log_event(
                "checkpoint_resumed",
                {
                    "workflow_id": workflow_id,
                    "current_stage": domain_state.current_stage,
                    "completed_stages": list(domain_state.stage_outputs.keys())
                }
            )

        if input_data:
            for key, value in input_data.items():
                if not hasattr(domain_state, key) or getattr(domain_state, key) is None:
                    setattr(domain_state, key, value)

        state_dict = domain_state.to_dict()
        if self.tracker:
            state_dict["tracker"] = self.tracker

        return domain_state, state_dict

    def _stream_with_checkpoints(
        self,
        state_dict: Dict[str, Any],
        workflow_id: str,
        state_holder: list,
    ) -> Optional[Dict[str, Any]]:
        """Stream graph execution, saving checkpoints after each stage.

        Updates state_holder[0] with the latest state for error recovery.
        Returns final state or None.
        """
        if self.checkpoint_manager is None:
            raise ValueError("checkpoint_manager required for checkpoint streaming")
        for chunk in self.graph.stream(state_dict):  # type: ignore[attr-defined]
            if chunk:
                stage_name = list(chunk.keys())[0]
                state_holder[0] = chunk[stage_name]
                domain_state_updated = self._extract_domain_state(state_holder[0])
                self.checkpoint_manager.save_checkpoint(domain_state_updated)
        result: Optional[Dict[str, Any]] = state_holder[0]
        return result

    def resume_from_checkpoint(
        self,
        workflow_id: str,
        input_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Resume workflow execution from checkpoint.

        Loads workflow state from checkpoint and continues execution
        from where it left off. Completed stages are skipped.

        Args:
            workflow_id: Workflow execution ID to resume
            input_data: Optional additional input data (merged with checkpoint)

        Returns:
            Final workflow state dict

        Raises:
            FileNotFoundError: If no checkpoint exists for workflow_id
            RuntimeError: If checkpoint manager not configured

        Example:
            >>> # Resume interrupted workflow
            >>> executor = CompiledGraphRunner(graph, enable_checkpoints=True)
            >>> result = executor.resume_from_checkpoint("wf-123")
        """
        if self.checkpoint_manager is None:
            raise RuntimeError("Checkpoint manager not configured")

        domain_state, state_dict = self._load_and_prepare_checkpoint(workflow_id, input_data)

        state_holder: list = [None]
        try:
            final_state = self._stream_with_checkpoints(state_dict, workflow_id, state_holder)

            if final_state is None:
                if self.tracker:
                    self.tracker.log_event(
                        "workflow_already_complete",
                        {"workflow_id": workflow_id}
                    )
                return state_dict

            final_domain_state = self._extract_domain_state(final_state)
            self.checkpoint_manager.save_checkpoint(final_domain_state)
            return final_state

        except Exception:
            if state_holder[0] is not None:
                try:
                    domain_state_updated = self._extract_domain_state(state_holder[0])
                    self.checkpoint_manager.save_checkpoint(domain_state_updated)
                except Exception as checkpoint_error:
                    logger.error(
                        "Failed to save checkpoint for workflow %s: %s",
                        workflow_id,
                        checkpoint_error,
                        exc_info=True
                    )
            raise

    def _extract_domain_state(self, state_dict: Dict[str, Any]) -> WorkflowDomainState:
        """Extract domain state from workflow state dict.

        Filters out infrastructure components and creates WorkflowDomainState.

        Args:
            state_dict: Workflow state dictionary (may include infrastructure)

        Returns:
            WorkflowDomainState containing only serializable domain data
        """
        # Filter to domain fields only (derived from WorkflowDomainState dataclass)
        domain_fields = {f.name for f in dataclasses.fields(WorkflowDomainState)}

        domain_dict = {
            k: v for k, v in state_dict.items()
            if k in domain_fields
        }

        return WorkflowDomainState.from_dict(domain_dict)

    def execute_with_optimization(
        self,
        input_data: Dict[str, Any],
        optimization_config: Any,
        workflow_id: Optional[str] = None,
        llm: Optional[Any] = None,
        experiment_service: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Execute with optimization pipeline.

        Falls through to execute() if optimization is disabled or
        has no pipeline steps configured.

        Args:
            input_data: Input data for workflow
            optimization_config: OptimizationConfig instance
            workflow_id: Optional workflow execution ID
            llm: LLM instance for LLM-based evaluators
            experiment_service: ExperimentService for tuning optimizer

        Returns:
            Final workflow state dict (best output from optimization)
        """
        from src.improvement._schemas import OptimizationConfig
        from src.improvement.engine import OptimizationEngine

        if not isinstance(optimization_config, OptimizationConfig):
            return self.execute(input_data, workflow_id)

        if not optimization_config.enabled or not optimization_config.pipeline:
            return self.execute(input_data, workflow_id)

        engine = OptimizationEngine(
            config=optimization_config,
            llm=llm,
            experiment_service=experiment_service,
        )

        result = engine.run(runner=self, input_data=input_data)
        return result.output


# Backward-compat alias (renamed to avoid naming collision with engines/workflow_executor.py)
WorkflowExecutor = CompiledGraphRunner
