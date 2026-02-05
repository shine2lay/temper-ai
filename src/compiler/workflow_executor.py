"""Workflow executor for running compiled LangGraph workflows.

Wraps compiled StateGraph and provides execution interface with observability.
Supports checkpoint/resume capability for fault tolerance and long-running workflows.
"""
import dataclasses
from typing import Dict, Any, Optional, Iterator, cast
from langgraph.graph import StateGraph

from src.compiler.state_manager import StateManager
from src.compiler.checkpoint import CheckpointManager
from src.compiler.domain_state import WorkflowDomainState, InfrastructureContext


class WorkflowExecutor:
    """Executes compiled workflows with observability.

    Wraps the compiled StateGraph and provides convenience methods
    for execution with state initialization and tracking.

    Example:
        >>> executor = WorkflowExecutor(compiled_graph, tracker=tracker)
        >>> result = executor.execute({"input": "data"})
    """

    def __init__(
        self,
        graph: StateGraph[Any],
        tracker: Optional[Any] = None,
        state_manager: Optional[StateManager] = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
        enable_checkpoints: bool = False
    ) -> None:
        """Initialize executor.

        Args:
            graph: Compiled StateGraph from LangGraphCompiler
            tracker: ExecutionTracker for observability (optional)
            state_manager: StateManager for state initialization (optional)
            checkpoint_manager: CheckpointManager for checkpoint/resume (optional)
            enable_checkpoints: Enable automatic checkpointing (default: False)
        """
        self.graph = graph
        self.tracker = tracker
        self.state_manager = state_manager or StateManager()
        self.checkpoint_manager = checkpoint_manager
        self.enable_checkpoints = enable_checkpoints

        # Initialize checkpoint manager if checkpoints enabled but not provided
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
        state = self.state_manager.initialize_state(
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
        state = self.state_manager.initialize_state(
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
        state = self.state_manager.initialize_state(
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
            >>> executor = WorkflowExecutor(graph, enable_checkpoints=True)
            >>> result = executor.execute_with_checkpoints(
            ...     {"topic": "AI safety"},
            ...     workflow_id="wf-123"
            ... )
        """
        if self.checkpoint_manager is None:
            raise RuntimeError("Checkpoint manager not configured. Set enable_checkpoints=True or provide checkpoint_manager")

        # Prepare initial state
        state = self.state_manager.initialize_state(
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
                        domain_state = self._extract_domain_state(final_state)
                        self.checkpoint_manager.save_checkpoint(
                            domain_state.workflow_id,
                            domain_state
                        )

                        if self.tracker:
                            self.tracker.log_event(
                                "checkpoint_saved",
                                {
                                    "workflow_id": domain_state.workflow_id,
                                    "stage": stage_name,
                                    "stage_count": stage_count
                                }
                            )

            # Ensure we have a final state
            if final_state is None:
                raise RuntimeError("Workflow execution produced no output")

            # Save final checkpoint
            domain_state = self._extract_domain_state(final_state)
            self.checkpoint_manager.save_checkpoint(
                domain_state.workflow_id,
                domain_state
            )

            return cast(Dict[str, Any], final_state)

        except Exception as e:
            # On error, save checkpoint at failure point if we have state
            if final_state is not None:
                try:
                    domain_state = self._extract_domain_state(final_state)
                    self.checkpoint_manager.save_checkpoint(
                        domain_state.workflow_id,
                        domain_state
                    )
                    if self.tracker:
                        self.tracker.log_event(
                            "checkpoint_saved_on_error",
                            {
                                "workflow_id": domain_state.workflow_id,
                                "error": str(e),
                                "stage_count": stage_count
                            }
                        )
                except Exception as checkpoint_error:
                    # Log but don't mask original error
                    if self.tracker:
                        self.tracker.log_event(
                            "checkpoint_save_failed",
                            {"error": str(checkpoint_error)}
                        )

            # Re-raise original error
            raise

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
            >>> executor = WorkflowExecutor(graph, enable_checkpoints=True)
            >>> result = executor.resume_from_checkpoint("wf-123")
        """
        if self.checkpoint_manager is None:
            raise RuntimeError("Checkpoint manager not configured")

        # Load checkpoint
        domain_state = self.checkpoint_manager.resume(workflow_id)

        if self.tracker:
            self.tracker.log_event(
                "checkpoint_resumed",
                {
                    "workflow_id": workflow_id,
                    "current_stage": domain_state.current_stage,
                    "completed_stages": list(domain_state.stage_outputs.keys())
                }
            )

        # Merge additional input if provided
        if input_data:
            for key, value in input_data.items():
                if not hasattr(domain_state, key) or getattr(domain_state, key) is None:
                    setattr(domain_state, key, value)

        # Convert to state dict for execution
        state_dict = domain_state.to_dict()

        # Add infrastructure to state dict (WorkflowState compatibility)
        if self.tracker:
            state_dict["tracker"] = self.tracker

        # Continue execution using streaming with checkpoints
        # LangGraph will skip already-completed stages automatically
        # because they check stage_outputs and skip if present
        final_state = None
        stage_count = len(domain_state.stage_outputs)

        try:
            for chunk in self.graph.stream(state_dict):  # type: ignore[attr-defined]
                if chunk:
                    stage_name = list(chunk.keys())[0]
                    final_state = chunk[stage_name]
                    stage_count += 1

                    # Checkpoint after each new stage
                    domain_state_updated = self._extract_domain_state(final_state)
                    self.checkpoint_manager.save_checkpoint(
                        domain_state_updated.workflow_id,
                        domain_state_updated
                    )

            if final_state is None:
                # No new stages executed - workflow was already complete
                if self.tracker:
                    self.tracker.log_event(
                        "workflow_already_complete",
                        {"workflow_id": workflow_id}
                    )
                return state_dict

            # Save final checkpoint
            final_domain_state = self._extract_domain_state(final_state)
            self.checkpoint_manager.save_checkpoint(
                final_domain_state.workflow_id,
                final_domain_state
            )

            return cast(Dict[str, Any], final_state)

        except Exception as e:
            # On error, checkpoint at failure point
            if final_state is not None:
                try:
                    domain_state_updated = self._extract_domain_state(final_state)
                    self.checkpoint_manager.save_checkpoint(
                        domain_state_updated.workflow_id,
                        domain_state_updated
                    )
                except Exception:
                    pass  # Don't mask original error
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
