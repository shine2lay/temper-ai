"""Checkpoint manager for workflow state persistence and recovery.

Provides high-level checkpoint management for long-running workflows:
- Automatic checkpoint saving after each stage
- Checkpoint loading for workflow resume
- Configurable checkpoint frequency
- Multiple storage backend support

Design:
- Uses CheckpointBackend abstraction for storage
- Integrates with StateManager and WorkflowExecutor
- Supports checkpoint strategies (every stage, periodic, manual)
- Automatic cleanup of old checkpoints

Example:
    >>> from src.compiler.checkpoint_manager import CheckpointManager
    >>> from src.compiler.checkpoint_backends import FileCheckpointBackend
    >>> from src.compiler.domain_state import WorkflowDomainState
    >>>
    >>> # Initialize manager
    >>> backend = FileCheckpointBackend(checkpoint_dir="./checkpoints")
    >>> manager = CheckpointManager(backend=backend)
    >>>
    >>> # Save checkpoint
    >>> domain = WorkflowDomainState(workflow_id="wf-123", input="test")
    >>> domain.set_stage_output("research", {"findings": ["data"]})
    >>> checkpoint_id = manager.save_checkpoint(domain)
    >>>
    >>> # Resume from checkpoint
    >>> restored_domain = manager.load_checkpoint("wf-123")
    >>> print(restored_domain.stage_outputs)  # {"research": {"findings": ["data"]}}
"""
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from src.compiler.checkpoint_backends import (
    CheckpointBackend,
    CheckpointNotFoundError,
    FileCheckpointBackend,
)
from src.compiler.domain_state import WorkflowDomainState
from src.utils.exceptions import ConfigurationError, ErrorCode

logger = logging.getLogger(__name__)


class CheckpointStrategy(Enum):
    """Checkpoint save strategies.

    Determines when checkpoints are automatically saved:
    - EVERY_STAGE: Save after each stage completes
    - PERIODIC: Save at fixed time intervals
    - MANUAL: Only save when explicitly requested
    - DISABLED: No automatic checkpointing
    """
    EVERY_STAGE = "every_stage"
    PERIODIC = "periodic"
    MANUAL = "manual"
    DISABLED = "disabled"


class CheckpointManager:
    """High-level checkpoint management for workflows.

    Manages checkpoint lifecycle:
    - Saving: Automatic or manual checkpoint creation
    - Loading: Resume workflows from checkpoints
    - Cleanup: Remove old checkpoints based on retention policy
    - Validation: Ensure checkpoint integrity

    Integration Points:
    - StateManager: Provides domain state to checkpoint
    - WorkflowExecutor: Triggers checkpoints after stages
    - CheckpointBackend: Handles actual storage

    Example:
        >>> # Create manager with file backend
        >>> manager = CheckpointManager()  # Uses default file backend
        >>>
        >>> # Save checkpoint
        >>> domain = WorkflowDomainState(workflow_id="wf-123")
        >>> checkpoint_id = manager.save_checkpoint(domain)
        >>>
        >>> # Resume workflow
        >>> restored_domain = manager.load_checkpoint("wf-123")
        >>> print(f"Resuming from stage: {restored_domain.current_stage}")
    """

    def __init__(
        self,
        backend: Optional[CheckpointBackend] = None,
        strategy: CheckpointStrategy = CheckpointStrategy.EVERY_STAGE,
        max_checkpoints: int = 10,
        periodic_interval: int = 300  # 5 minutes
    ):
        """Initialize checkpoint manager.

        Args:
            backend: Checkpoint storage backend (default: FileCheckpointBackend)
            strategy: When to save checkpoints automatically
            max_checkpoints: Maximum checkpoints to keep per workflow
            periodic_interval: Seconds between periodic checkpoints
        """
        self.backend = backend or FileCheckpointBackend()
        self.strategy = strategy
        self.max_checkpoints = max_checkpoints
        self.periodic_interval = periodic_interval

        # Callback hooks for checkpoint lifecycle events
        self.on_checkpoint_saved: Optional[Callable[[str, str], None]] = None
        self.on_checkpoint_loaded: Optional[Callable[[str, str], None]] = None
        self.on_checkpoint_failed: Optional[Callable[[str, Exception], None]] = None

    def save_checkpoint(
        self,
        domain_state: WorkflowDomainState,
        checkpoint_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        force: bool = False
    ) -> str:
        """Save a workflow checkpoint.

        Args:
            domain_state: Serializable domain state to checkpoint
            checkpoint_id: Optional checkpoint ID (auto-generated if not provided)
            metadata: Optional metadata to store with checkpoint
            force: Force save even if strategy is DISABLED

        Returns:
            Checkpoint ID of the saved checkpoint

        Raises:
            CheckpointSaveError: If checkpoint save fails

        Example:
            >>> domain = WorkflowDomainState(workflow_id="wf-123")
            >>> domain.set_stage_output("research", {"data": "value"})
            >>> checkpoint_id = manager.save_checkpoint(domain)
        """
        # Check if checkpointing is enabled
        if self.strategy == CheckpointStrategy.DISABLED and not force:
            logger.debug(
                f"Checkpoint skipped for workflow {domain_state.workflow_id}: "
                "strategy is DISABLED"
            )
            return ""

        try:
            # Add checkpoint metadata
            checkpoint_metadata = metadata or {}
            checkpoint_metadata.update({
                "strategy": self.strategy.value,
                "stage": domain_state.current_stage,
                "num_stages_completed": len(domain_state.stage_outputs)
            })

            # Save checkpoint via backend
            saved_checkpoint_id = self.backend.save_checkpoint(
                workflow_id=domain_state.workflow_id,
                domain_state=domain_state,
                checkpoint_id=checkpoint_id,
                metadata=checkpoint_metadata
            )

            logger.info(
                f"Checkpoint saved: workflow={domain_state.workflow_id}, "
                f"checkpoint={saved_checkpoint_id}, stage={domain_state.current_stage}"
            )

            # Trigger callback
            if self.on_checkpoint_saved:
                self.on_checkpoint_saved(domain_state.workflow_id, saved_checkpoint_id)

            # Cleanup old checkpoints
            self._cleanup_old_checkpoints(domain_state.workflow_id)

            return saved_checkpoint_id

        except Exception as e:
            logger.error(
                f"Failed to save checkpoint for workflow {domain_state.workflow_id}: {e}"
            )
            if self.on_checkpoint_failed:
                self.on_checkpoint_failed(domain_state.workflow_id, e)
            raise CheckpointSaveError(
                f"Checkpoint save failed for {domain_state.workflow_id}: {e}"
            ) from e

    def load_checkpoint(
        self,
        workflow_id: str,
        checkpoint_id: Optional[str] = None
    ) -> WorkflowDomainState:
        """Load a workflow checkpoint for resume.

        Args:
            workflow_id: Unique workflow execution ID
            checkpoint_id: Checkpoint ID to load (latest if not specified)

        Returns:
            Restored WorkflowDomainState

        Raises:
            CheckpointNotFoundError: If checkpoint doesn't exist
            CheckpointLoadError: If checkpoint load fails

        Example:
            >>> # Load latest checkpoint
            >>> domain = manager.load_checkpoint("wf-123")
            >>>
            >>> # Load specific checkpoint
            >>> domain = manager.load_checkpoint("wf-123", "cp-001")
        """
        try:
            # Load checkpoint via backend
            domain_state = self.backend.load_checkpoint(workflow_id, checkpoint_id)

            logger.info(
                f"Checkpoint loaded: workflow={workflow_id}, "
                f"checkpoint={checkpoint_id or 'latest'}, "
                f"stage={domain_state.current_stage}"
            )

            # Trigger callback
            if self.on_checkpoint_loaded:
                self.on_checkpoint_loaded(workflow_id, checkpoint_id or "latest")

            return domain_state

        except CheckpointNotFoundError:
            raise

        except Exception as e:
            logger.error(f"Failed to load checkpoint for workflow {workflow_id}: {e}")
            if self.on_checkpoint_failed:
                self.on_checkpoint_failed(workflow_id, e)
            raise CheckpointLoadError(
                f"Checkpoint load failed for {workflow_id}: {e}"
            ) from e

    def should_checkpoint(self, stage_name: str, elapsed_time: float = 0) -> bool:
        """Determine if a checkpoint should be saved.

        Args:
            stage_name: Name of the stage that just completed
            elapsed_time: Seconds since last checkpoint

        Returns:
            True if checkpoint should be saved

        Example:
            >>> if manager.should_checkpoint("research"):
            ...     manager.save_checkpoint(domain)
        """
        if self.strategy == CheckpointStrategy.DISABLED:
            return False

        if self.strategy == CheckpointStrategy.EVERY_STAGE:
            return True

        if self.strategy == CheckpointStrategy.PERIODIC:
            return elapsed_time >= self.periodic_interval

        # MANUAL strategy requires explicit save_checkpoint calls
        return False

    def list_checkpoints(self, workflow_id: str) -> List[Dict[str, Any]]:
        """List all checkpoints for a workflow.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            List of checkpoint metadata dicts

        Example:
            >>> checkpoints = manager.list_checkpoints("wf-123")
            >>> for cp in checkpoints:
            ...     print(f"{cp['checkpoint_id']}: {cp['stage']}")
        """
        return self.backend.list_checkpoints(workflow_id)

    def delete_checkpoint(self, workflow_id: str, checkpoint_id: str) -> bool:
        """Delete a specific checkpoint.

        Args:
            workflow_id: Unique workflow execution ID
            checkpoint_id: Checkpoint ID to delete

        Returns:
            True if deleted, False if not found

        Example:
            >>> manager.delete_checkpoint("wf-123", "cp-001")
        """
        success = self.backend.delete_checkpoint(workflow_id, checkpoint_id)
        if success:
            logger.info(f"Checkpoint deleted: workflow={workflow_id}, checkpoint={checkpoint_id}")
        return success

    def get_latest_checkpoint_id(self, workflow_id: str) -> Optional[str]:
        """Get the latest checkpoint ID for a workflow.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            Latest checkpoint ID, or None if no checkpoints exist

        Example:
            >>> latest_id = manager.get_latest_checkpoint_id("wf-123")
            >>> if latest_id:
            ...     domain = manager.load_checkpoint("wf-123", latest_id)
        """
        return self.backend.get_latest_checkpoint(workflow_id)

    def has_checkpoint(self, workflow_id: str) -> bool:
        """Check if a workflow has any checkpoints.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            True if checkpoints exist

        Example:
            >>> if manager.has_checkpoint("wf-123"):
            ...     print("Can resume workflow")
        """
        return self.get_latest_checkpoint_id(workflow_id) is not None

    def _cleanup_old_checkpoints(self, workflow_id: str) -> None:
        """Remove old checkpoints beyond max_checkpoints limit.

        Args:
            workflow_id: Unique workflow execution ID
        """
        if self.max_checkpoints <= 0:
            return  # No limit

        checkpoints = self.list_checkpoints(workflow_id)

        if len(checkpoints) > self.max_checkpoints:
            # Delete oldest checkpoints (list is sorted newest first)
            to_delete = checkpoints[self.max_checkpoints:]
            for cp in to_delete:
                self.delete_checkpoint(workflow_id, cp["checkpoint_id"])
                logger.debug(
                    f"Cleaned up old checkpoint: workflow={workflow_id}, "
                    f"checkpoint={cp['checkpoint_id']}"
                )


class CheckpointSaveError(ConfigurationError):
    """Raised when checkpoint save fails."""

    def __init__(self, message: str, **kwargs):
        super().__init__(
            message=message,
            error_code=ErrorCode.CONFIG_INVALID,
            **kwargs
        )


class CheckpointLoadError(ConfigurationError):
    """Raised when checkpoint load fails."""

    def __init__(self, message: str, **kwargs):
        super().__init__(
            message=message,
            error_code=ErrorCode.CONFIG_INVALID,
            **kwargs
        )


def create_checkpoint_manager(
    backend_type: str = "file",
    **backend_kwargs: Any
) -> CheckpointManager:
    """Factory function to create CheckpointManager with specified backend.

    Args:
        backend_type: Backend type ("file" or "redis")
        **backend_kwargs: Backend-specific configuration

    Returns:
        Configured CheckpointManager

    Example:
        >>> # File backend
        >>> manager = create_checkpoint_manager(
        ...     backend_type="file",
        ...     checkpoint_dir="./checkpoints"
        ... )
        >>>
        >>> # Redis backend
        >>> manager = create_checkpoint_manager(
        ...     backend_type="redis",
        ...     redis_url="redis://localhost:6379"
        ... )
    """
    if backend_type == "file":
        from src.compiler.checkpoint_backends import FileCheckpointBackend
        backend = FileCheckpointBackend(**backend_kwargs)
    elif backend_type == "redis":
        from src.compiler.checkpoint_backends import RedisCheckpointBackend
        backend = RedisCheckpointBackend(**backend_kwargs)  # type: ignore[assignment]
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")

    return CheckpointManager(backend=backend)
