"""Checkpoint/resume functionality for workflow execution.

This module provides checkpoint/resume capabilities by leveraging the domain
state/infrastructure separation from M3.2-05.

Key Concepts:
- Checkpoints contain ONLY serializable domain state (WorkflowDomainState)
- Infrastructure (ExecutionContext) is recreated on resume, not checkpointed
- Supports partial resume: skip completed stages when resuming
- Multiple storage backends: file, database, S3, etc.

Example:
    >>> # Save checkpoint during execution
    >>> manager = CheckpointManager(storage_path="./checkpoints")
    >>> manager.save_checkpoint(workflow_id="wf-123", domain_state)
    >>>
    >>> # Resume from checkpoint
    >>> domain_state = manager.load_checkpoint("wf-123")
    >>> context = ExecutionContext(...)  # Recreate infrastructure
    >>> # Continue execution from where it left off
"""
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, Any, Optional, List

from src.compiler.domain_state import WorkflowDomainState


@dataclass
class CheckpointMetadata:
    """Metadata about a checkpoint.

    Attributes:
        workflow_id: Unique workflow execution ID
        created_at: When checkpoint was created
        current_stage: Stage that was executing when checkpointed
        completed_stages: List of stages that completed
        version: Checkpoint format version
        file_path: Path to checkpoint file (if file-based)
        size_bytes: Checkpoint size in bytes
    """

    workflow_id: str
    created_at: datetime
    current_stage: str
    completed_stages: List[str]
    version: str = "1.0"
    file_path: Optional[str] = None
    size_bytes: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "workflow_id": self.workflow_id,
            "created_at": self.created_at.isoformat(),
            "current_stage": self.current_stage,
            "completed_stages": self.completed_stages,
            "version": self.version,
            "file_path": self.file_path,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CheckpointMetadata':
        """Create from dictionary."""
        data = data.copy()
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


class CheckpointStorage(ABC):
    """Abstract base class for checkpoint storage backends."""

    @abstractmethod
    def save(
        self,
        workflow_id: str,
        domain_state: WorkflowDomainState
    ) -> CheckpointMetadata:
        """Save checkpoint.

        Args:
            workflow_id: Unique workflow execution ID
            domain_state: Domain state to checkpoint

        Returns:
            CheckpointMetadata about saved checkpoint
        """
        pass

    @abstractmethod
    def load(self, workflow_id: str) -> Optional[WorkflowDomainState]:
        """Load checkpoint.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            WorkflowDomainState if checkpoint exists, None otherwise
        """
        pass

    @abstractmethod
    def exists(self, workflow_id: str) -> bool:
        """Check if checkpoint exists.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            True if checkpoint exists
        """
        pass

    @abstractmethod
    def delete(self, workflow_id: str) -> bool:
        """Delete checkpoint.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            True if checkpoint was deleted
        """
        pass

    @abstractmethod
    def list_checkpoints(self) -> List[CheckpointMetadata]:
        """List all available checkpoints.

        Returns:
            List of checkpoint metadata
        """
        pass


class FileCheckpointStorage(CheckpointStorage):
    """File-based checkpoint storage.

    Saves checkpoints as JSON files in a directory.

    Example:
        >>> storage = FileCheckpointStorage("./checkpoints")
        >>> metadata = storage.save("wf-123", domain_state)
        >>> restored = storage.load("wf-123")
    """

    def __init__(self, storage_path: str = "./checkpoints"):
        """Initialize file storage.

        Args:
            storage_path: Directory for checkpoint files
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _get_checkpoint_path(self, workflow_id: str) -> Path:
        """Get file path for workflow checkpoint.

        Args:
            workflow_id: Workflow execution ID

        Returns:
            Path to checkpoint file
        """
        # Sanitize workflow_id for filename
        safe_id = workflow_id.replace("/", "_").replace("\\", "_")
        return self.storage_path / f"{safe_id}.checkpoint.json"

    def _get_metadata_path(self, workflow_id: str) -> Path:
        """Get file path for checkpoint metadata.

        Args:
            workflow_id: Workflow execution ID

        Returns:
            Path to metadata file
        """
        safe_id = workflow_id.replace("/", "_").replace("\\", "_")
        return self.storage_path / f"{safe_id}.metadata.json"

    def save(
        self,
        workflow_id: str,
        domain_state: WorkflowDomainState
    ) -> CheckpointMetadata:
        """Save checkpoint to file.

        Args:
            workflow_id: Unique workflow execution ID
            domain_state: Domain state to checkpoint

        Returns:
            CheckpointMetadata about saved checkpoint

        Raises:
            IOError: If checkpoint cannot be saved
        """
        checkpoint_path = self._get_checkpoint_path(workflow_id)
        metadata_path = self._get_metadata_path(workflow_id)

        try:
            # Serialize domain state
            checkpoint_data = domain_state.to_dict()

            # Write checkpoint file
            with open(checkpoint_path, 'w') as f:
                json.dump(checkpoint_data, f, indent=2)

            # Create metadata
            metadata = CheckpointMetadata(
                workflow_id=workflow_id,
                created_at=datetime.now(UTC),
                current_stage=domain_state.current_stage,
                completed_stages=list(domain_state.stage_outputs.keys()),
                file_path=str(checkpoint_path),
                size_bytes=checkpoint_path.stat().st_size,
            )

            # Write metadata file
            with open(metadata_path, 'w') as f:
                json.dump(metadata.to_dict(), f, indent=2)

            return metadata

        except Exception as e:
            raise IOError(f"Failed to save checkpoint for {workflow_id}: {e}") from e

    def load(self, workflow_id: str) -> Optional[WorkflowDomainState]:
        """Load checkpoint from file.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            WorkflowDomainState if checkpoint exists, None otherwise

        Raises:
            IOError: If checkpoint exists but cannot be loaded
        """
        checkpoint_path = self._get_checkpoint_path(workflow_id)

        if not checkpoint_path.exists():
            return None

        try:
            with open(checkpoint_path, 'r') as f:
                checkpoint_data = json.load(f)

            return WorkflowDomainState.from_dict(checkpoint_data)

        except Exception as e:
            raise IOError(f"Failed to load checkpoint for {workflow_id}: {e}") from e

    def exists(self, workflow_id: str) -> bool:
        """Check if checkpoint file exists.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            True if checkpoint exists
        """
        return self._get_checkpoint_path(workflow_id).exists()

    def delete(self, workflow_id: str) -> bool:
        """Delete checkpoint files.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            True if checkpoint was deleted
        """
        checkpoint_path = self._get_checkpoint_path(workflow_id)
        metadata_path = self._get_metadata_path(workflow_id)

        deleted = False

        if checkpoint_path.exists():
            checkpoint_path.unlink()
            deleted = True

        if metadata_path.exists():
            metadata_path.unlink()

        return deleted

    def list_checkpoints(self) -> List[CheckpointMetadata]:
        """List all checkpoint metadata files.

        Returns:
            List of checkpoint metadata
        """
        checkpoints = []

        for metadata_file in self.storage_path.glob("*.metadata.json"):
            try:
                with open(metadata_file, 'r') as f:
                    metadata_dict = json.load(f)
                    metadata = CheckpointMetadata.from_dict(metadata_dict)
                    checkpoints.append(metadata)
            except Exception:
                # Skip corrupted metadata files
                continue

        return checkpoints


class CheckpointManager:
    """High-level checkpoint/resume manager.

    Provides convenience methods for checkpoint operations and integrates
    with workflow execution.

    Example:
        >>> manager = CheckpointManager()
        >>>
        >>> # During execution: save checkpoint
        >>> manager.save_checkpoint("wf-123", domain_state)
        >>>
        >>> # On resume: load checkpoint
        >>> if manager.has_checkpoint("wf-123"):
        ...     domain_state = manager.resume("wf-123")
        ...     context = ExecutionContext(...)  # Recreate infrastructure
    """

    def __init__(
        self,
        storage: Optional[CheckpointStorage] = None,
        storage_path: str = "./checkpoints"
    ):
        """Initialize checkpoint manager.

        Args:
            storage: Checkpoint storage backend (default: FileCheckpointStorage)
            storage_path: Path for file-based storage (if storage not provided)
        """
        self.storage = storage or FileCheckpointStorage(storage_path)

    def save_checkpoint(
        self,
        workflow_id: str,
        domain_state: WorkflowDomainState
    ) -> CheckpointMetadata:
        """Save workflow checkpoint.

        Args:
            workflow_id: Unique workflow execution ID
            domain_state: Domain state to checkpoint

        Returns:
            CheckpointMetadata about saved checkpoint
        """
        return self.storage.save(workflow_id, domain_state)

    def resume(self, workflow_id: str) -> WorkflowDomainState:
        """Resume workflow from checkpoint.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            WorkflowDomainState from checkpoint

        Raises:
            FileNotFoundError: If no checkpoint exists for workflow_id
        """
        domain_state = self.storage.load(workflow_id)

        if domain_state is None:
            raise FileNotFoundError(f"No checkpoint found for workflow: {workflow_id}")

        return domain_state

    def has_checkpoint(self, workflow_id: str) -> bool:
        """Check if checkpoint exists for workflow.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            True if checkpoint exists
        """
        return self.storage.exists(workflow_id)

    def delete_checkpoint(self, workflow_id: str) -> bool:
        """Delete workflow checkpoint.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            True if checkpoint was deleted
        """
        return self.storage.delete(workflow_id)

    def list_all(self) -> List[CheckpointMetadata]:
        """List all available checkpoints.

        Returns:
            List of checkpoint metadata
        """
        return self.storage.list_checkpoints()

    def get_completed_stages(self, workflow_id: str) -> List[str]:
        """Get list of completed stages from checkpoint.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            List of completed stage names

        Raises:
            FileNotFoundError: If no checkpoint exists
        """
        domain_state = self.resume(workflow_id)
        return list(domain_state.stage_outputs.keys())

    def should_skip_stage(
        self,
        workflow_id: str,
        stage_name: str
    ) -> bool:
        """Check if stage should be skipped on resume (already completed).

        Args:
            workflow_id: Unique workflow execution ID
            stage_name: Stage to check

        Returns:
            True if stage is already completed in checkpoint
        """
        if not self.has_checkpoint(workflow_id):
            return False

        try:
            completed_stages = self.get_completed_stages(workflow_id)
            return stage_name in completed_stages
        except Exception:
            return False
