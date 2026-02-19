"""Backward-compatible checkpoint API.

DEPRECATED: This module is a compatibility shim. New code should import from:
- temper_ai.workflow.checkpoint_manager (CheckpointManager, CheckpointStrategy)
- temper_ai.workflow.checkpoint_backends (FileCheckpointBackend, CheckpointNotFoundError)

This shim delegates to checkpoint_manager.py and checkpoint_backends.py,
eliminating the duplicate implementation (code-high-dup-checkpoint-15).
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from temper_ai.workflow.checkpoint_backends import (
    CheckpointNotFoundError,
    FileCheckpointBackend,
)
from temper_ai.workflow.checkpoint_manager import (
    CheckpointManager as _NewCheckpointManager,
)
from temper_ai.workflow.domain_state import WorkflowDomainState


@dataclass
class CheckpointMetadata:
    """Metadata about a checkpoint (backward-compatible dataclass)."""

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


class CheckpointManager:
    """Backward-compatible CheckpointManager that delegates to the new implementation.

    DEPRECATED: Use temper_ai.workflow.checkpoint_manager.CheckpointManager directly.
    This wrapper preserves the old API (save_checkpoint(workflow_id, domain_state),
    resume(workflow_id), etc.) while delegating to the new backend-based system.
    """

    def __init__(
        self,
        storage: Optional[Any] = None,
        storage_path: str = "./checkpoints",
        backend: Optional[Any] = None,
        **kwargs: Any,
    ):
        """Initialize checkpoint manager.

        Args:
            storage: Legacy storage parameter (ignored, uses FileCheckpointBackend)
            storage_path: Path for file-based storage
            backend: Optional checkpoint backend (new API). If provided,
                     uses it directly instead of creating a FileCheckpointBackend.
            **kwargs: Additional keyword arguments forwarded to the new
                      CheckpointManager (e.g. strategy, max_checkpoints).
        """
        if backend is None:
            backend = FileCheckpointBackend(checkpoint_dir=storage_path)
        self._manager = _NewCheckpointManager(backend=backend, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Proxy unknown attributes to the underlying new CheckpointManager.

        This allows code using the new API (load_checkpoint, list_checkpoints,
        etc.) to work transparently through this backward-compatible wrapper.
        """
        return getattr(self._manager, name)

    def save_checkpoint(
        self,
        workflow_id_or_state: Any,
        domain_state: Optional[WorkflowDomainState] = None,
        **kwargs: Any,
    ) -> Any:
        """Save workflow checkpoint (supports both old and new calling conventions).

        Old API: save_checkpoint(workflow_id, domain_state) -> CheckpointMetadata
        New API: save_checkpoint(domain_state, ...) -> str (proxied to new manager)
        """
        # Detect calling convention: if first arg is a string, it's the old API
        if isinstance(workflow_id_or_state, str):
            workflow_id = workflow_id_or_state
            if domain_state is None:
                raise TypeError("domain_state is required when workflow_id is provided")
            # Delegate to backend and return CheckpointMetadata for backward compat
            self._manager.backend.save_checkpoint(
                workflow_id, domain_state, **kwargs
            )
            return CheckpointMetadata(
                workflow_id=workflow_id,
                created_at=datetime.now(UTC),
                current_stage=domain_state.current_stage,
                completed_stages=list(domain_state.stage_outputs.keys()),
            )
        else:
            # New manager API: save_checkpoint(domain_state, ...)
            return self._manager.save_checkpoint(workflow_id_or_state, **kwargs)

    def resume(self, workflow_id: str) -> WorkflowDomainState:
        """Resume workflow from checkpoint.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            WorkflowDomainState from checkpoint

        Raises:
            FileNotFoundError: If no checkpoint exists for workflow_id
        """
        try:
            return self._manager.load_checkpoint(workflow_id)
        except CheckpointNotFoundError:
            raise FileNotFoundError(f"No checkpoint found for workflow: {workflow_id}")

    def has_checkpoint(self, workflow_id: str) -> bool:
        """Check if checkpoint exists for workflow."""
        return self._manager.has_checkpoint(workflow_id)

    def delete_all_checkpoints(self, workflow_id: str) -> bool:
        """Delete all checkpoints for a workflow."""
        latest_id = self._manager.get_latest_checkpoint_id(workflow_id)
        if latest_id is None:
            return False

        # Delete all checkpoints for this workflow
        checkpoints = self._manager.list_checkpoints(workflow_id)
        deleted = False
        for cp in checkpoints:
            if self._manager.delete_checkpoint(workflow_id, cp["checkpoint_id"]):
                deleted = True
        return deleted

    def list_all(self) -> List[CheckpointMetadata]:
        """List all available checkpoints.

        Returns:
            List of checkpoint metadata
        """
        # The new backend is per-workflow; scan the checkpoint directory
        results: List[CheckpointMetadata] = []
        checkpoint_dir = self._manager.backend.checkpoint_dir  # type: ignore[attr-defined]
        if not checkpoint_dir.exists():
            return results

        for workflow_dir in checkpoint_dir.iterdir():
            if workflow_dir.is_dir():
                workflow_id = workflow_dir.name
                checkpoints = self._manager.list_checkpoints(workflow_id)
                for cp in checkpoints:
                    results.append(CheckpointMetadata(
                        workflow_id=workflow_id,
                        created_at=datetime.fromisoformat(cp["created_at"]),
                        current_stage=cp.get("stage", ""),
                        completed_stages=[],
                    ))
        return results

    def get_completed_stages(self, workflow_id: str) -> List[str]:
        """Get list of completed stages from checkpoint."""
        domain_state = self.resume(workflow_id)
        return list(domain_state.stage_outputs.keys())

    def should_skip_stage(
        self,
        workflow_id: str,
        stage_name: str
    ) -> bool:
        """Check if stage should be skipped on resume (already completed)."""
        if not self.has_checkpoint(workflow_id):
            return False

        try:
            completed_stages = self.get_completed_stages(workflow_id)
            return stage_name in completed_stages
        except Exception:
            return False


class FileCheckpointStorage:
    """Backward-compatible wrapper around FileCheckpointBackend.

    DEPRECATED: Use FileCheckpointBackend from temper_ai.workflow.checkpoint_backends.
    Maps old API (save/load/exists/delete) to new backend API.
    """

    def __init__(self, storage_path: str = "./checkpoints"):
        self._backend = FileCheckpointBackend(checkpoint_dir=storage_path)
        self.storage_path = self._backend.checkpoint_dir

    def save(
        self,
        workflow_id: str,
        domain_state: WorkflowDomainState
    ) -> CheckpointMetadata:
        """Save checkpoint (delegates to FileCheckpointBackend)."""
        checkpoint_id = self._backend.save_checkpoint(workflow_id, domain_state)
        return CheckpointMetadata(
            workflow_id=workflow_id,
            created_at=datetime.now(UTC),
            current_stage=domain_state.current_stage,
            completed_stages=list(domain_state.stage_outputs.keys()),
            file_path=str(self._backend._get_checkpoint_path(workflow_id, checkpoint_id)),
            size_bytes=self._backend._get_checkpoint_path(workflow_id, checkpoint_id).stat().st_size,
        )

    def load(self, workflow_id: str) -> Optional[WorkflowDomainState]:
        """Load latest checkpoint."""
        try:
            return self._backend.load_checkpoint(workflow_id)
        except CheckpointNotFoundError:
            return None

    def exists(self, workflow_id: str) -> bool:
        """Check if checkpoint exists."""
        return self._backend.get_latest_checkpoint(workflow_id) is not None

    def delete(self, workflow_id: str) -> bool:
        """Delete all checkpoints for workflow."""
        checkpoints = self._backend.list_checkpoints(workflow_id)
        if not checkpoints:
            return False
        for cp in checkpoints:
            self._backend.delete_checkpoint(workflow_id, cp["checkpoint_id"])
        return True

    def list_checkpoints(self) -> List[CheckpointMetadata]:
        """List all checkpoints across all workflows."""
        results: List[CheckpointMetadata] = []
        if not self.storage_path.exists():
            return results
        for workflow_dir in self.storage_path.iterdir():
            if workflow_dir.is_dir():
                workflow_id = workflow_dir.name
                checkpoints = self._backend.list_checkpoints(workflow_id)
                for cp in checkpoints:
                    results.append(CheckpointMetadata(
                        workflow_id=workflow_id,
                        created_at=datetime.fromisoformat(cp["created_at"]),
                        current_stage=cp.get("stage", ""),
                        completed_stages=[],
                    ))
        return results
