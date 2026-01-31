"""Checkpoint storage backends for workflow state persistence.

Provides pluggable storage backends for saving and loading workflow checkpoints:
- FileCheckpointBackend: JSON files on disk (default, no dependencies)
- RedisCheckpointBackend: Redis storage (optional, for distributed systems)

Design:
- Abstract CheckpointBackend interface
- Each backend handles serialization/deserialization
- Checkpoints are identified by workflow_id + checkpoint_id
- Automatic checkpoint versioning and metadata

Example:
    >>> from src.compiler.checkpoint_backends import FileCheckpointBackend
    >>> from src.compiler.domain_state import WorkflowDomainState
    >>>
    >>> # Save checkpoint
    >>> backend = FileCheckpointBackend(checkpoint_dir="./checkpoints")
    >>> domain = WorkflowDomainState(workflow_id="wf-123", input="test")
    >>> checkpoint_id = backend.save_checkpoint("wf-123", domain)
    >>>
    >>> # Load checkpoint
    >>> loaded_domain = backend.load_checkpoint("wf-123", checkpoint_id)
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, cast
from pathlib import Path
import json
import time
from datetime import datetime, UTC

from src.compiler.domain_state import WorkflowDomainState


class CheckpointBackend(ABC):
    """Abstract base class for checkpoint storage backends.

    All checkpoint backends must implement:
    - save_checkpoint: Persist workflow domain state
    - load_checkpoint: Restore workflow domain state
    - list_checkpoints: List available checkpoints for a workflow
    - delete_checkpoint: Remove a checkpoint
    - get_latest_checkpoint: Get the most recent checkpoint

    Checkpoints are identified by:
    - workflow_id: Unique workflow execution ID
    - checkpoint_id: Unique checkpoint ID (auto-generated or specified)

    Checkpoint Structure:
        {
            "checkpoint_id": "cp-<timestamp>-<counter>",
            "workflow_id": "wf-123",
            "created_at": "2026-01-27T10:00:00Z",
            "stage": "research",  # Current stage when checkpointed
            "domain_state": {...},  # Serialized WorkflowDomainState
            "metadata": {...}  # Optional metadata
        }
    """

    @abstractmethod
    def save_checkpoint(
        self,
        workflow_id: str,
        domain_state: WorkflowDomainState,
        checkpoint_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Save a workflow checkpoint.

        Args:
            workflow_id: Unique workflow execution ID
            domain_state: Serializable domain state to checkpoint
            checkpoint_id: Optional checkpoint ID (auto-generated if not provided)
            metadata: Optional metadata to store with checkpoint

        Returns:
            Checkpoint ID of the saved checkpoint

        Example:
            >>> checkpoint_id = backend.save_checkpoint("wf-123", domain)
        """
        pass

    @abstractmethod
    def load_checkpoint(
        self,
        workflow_id: str,
        checkpoint_id: Optional[str] = None
    ) -> WorkflowDomainState:
        """Load a workflow checkpoint.

        Args:
            workflow_id: Unique workflow execution ID
            checkpoint_id: Checkpoint ID to load (latest if not specified)

        Returns:
            Restored WorkflowDomainState

        Raises:
            CheckpointNotFoundError: If checkpoint doesn't exist

        Example:
            >>> domain = backend.load_checkpoint("wf-123")  # Latest
            >>> domain = backend.load_checkpoint("wf-123", "cp-001")  # Specific
        """
        pass

    @abstractmethod
    def list_checkpoints(self, workflow_id: str) -> List[Dict[str, Any]]:
        """List all checkpoints for a workflow.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            List of checkpoint metadata dicts (sorted by created_at desc)

        Example:
            >>> checkpoints = backend.list_checkpoints("wf-123")
            >>> for cp in checkpoints:
            ...     print(f"{cp['checkpoint_id']}: {cp['stage']}")
        """
        pass

    @abstractmethod
    def delete_checkpoint(self, workflow_id: str, checkpoint_id: str) -> bool:
        """Delete a specific checkpoint.

        Args:
            workflow_id: Unique workflow execution ID
            checkpoint_id: Checkpoint ID to delete

        Returns:
            True if deleted, False if not found

        Example:
            >>> backend.delete_checkpoint("wf-123", "cp-001")
        """
        pass

    @abstractmethod
    def get_latest_checkpoint(self, workflow_id: str) -> Optional[str]:
        """Get the latest checkpoint ID for a workflow.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            Latest checkpoint ID, or None if no checkpoints exist

        Example:
            >>> latest_id = backend.get_latest_checkpoint("wf-123")
        """
        pass


class CheckpointNotFoundError(Exception):
    """Raised when a checkpoint cannot be found."""
    pass


class FileCheckpointBackend(CheckpointBackend):
    """File-based checkpoint storage using JSON files.

    Stores checkpoints as JSON files in a directory structure:
        checkpoint_dir/
            <workflow_id>/
                cp-<timestamp>-001.json
                cp-<timestamp>-002.json
                ...

    Features:
    - No external dependencies (pure Python)
    - Human-readable JSON format
    - Simple file-based versioning
    - Automatic directory creation

    Example:
        >>> backend = FileCheckpointBackend(checkpoint_dir="./checkpoints")
        >>> checkpoint_id = backend.save_checkpoint("wf-123", domain)
        >>> domain = backend.load_checkpoint("wf-123", checkpoint_id)
    """

    def __init__(self, checkpoint_dir: str = "./checkpoints"):
        """Initialize file-based checkpoint backend.

        Args:
            checkpoint_dir: Directory to store checkpoint files
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0  # Counter for unique IDs within same millisecond

    def _get_workflow_dir(self, workflow_id: str) -> Path:
        """Get checkpoint directory for a workflow."""
        workflow_dir = self.checkpoint_dir / workflow_id
        workflow_dir.mkdir(parents=True, exist_ok=True)
        return workflow_dir

    def _generate_checkpoint_id(self) -> str:
        """Generate a unique checkpoint ID."""
        timestamp = int(time.time() * 1000)  # Millisecond precision
        self._counter += 1
        return f"cp-{timestamp}-{self._counter}"

    def _get_checkpoint_path(self, workflow_id: str, checkpoint_id: str) -> Path:
        """Get file path for a checkpoint."""
        return self._get_workflow_dir(workflow_id) / f"{checkpoint_id}.json"

    def save_checkpoint(
        self,
        workflow_id: str,
        domain_state: WorkflowDomainState,
        checkpoint_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Save checkpoint to JSON file.

        Args:
            workflow_id: Unique workflow execution ID
            domain_state: Serializable domain state to checkpoint
            checkpoint_id: Optional checkpoint ID (auto-generated if not provided)
            metadata: Optional metadata to store with checkpoint

        Returns:
            Checkpoint ID of the saved checkpoint
        """
        # Generate checkpoint ID if not provided
        if checkpoint_id is None:
            checkpoint_id = self._generate_checkpoint_id()

        # Build checkpoint data structure
        checkpoint_data = {
            "checkpoint_id": checkpoint_id,
            "workflow_id": workflow_id,
            "created_at": datetime.now(UTC).isoformat(),
            "stage": domain_state.current_stage,
            "domain_state": domain_state.to_dict(exclude_none=True),
            "metadata": metadata or {}
        }

        # Write to file
        checkpoint_path = self._get_checkpoint_path(workflow_id, checkpoint_id)
        with open(checkpoint_path, 'w') as f:
            json.dump(checkpoint_data, f, indent=2)

        return checkpoint_id

    def load_checkpoint(
        self,
        workflow_id: str,
        checkpoint_id: Optional[str] = None
    ) -> WorkflowDomainState:
        """Load checkpoint from JSON file.

        Args:
            workflow_id: Unique workflow execution ID
            checkpoint_id: Checkpoint ID to load (latest if not specified)

        Returns:
            Restored WorkflowDomainState

        Raises:
            CheckpointNotFoundError: If checkpoint doesn't exist
        """
        # Get checkpoint ID if not specified
        if checkpoint_id is None:
            checkpoint_id = self.get_latest_checkpoint(workflow_id)
            if checkpoint_id is None:
                raise CheckpointNotFoundError(
                    f"No checkpoints found for workflow {workflow_id}"
                )

        # Read checkpoint file
        checkpoint_path = self._get_checkpoint_path(workflow_id, checkpoint_id)
        if not checkpoint_path.exists():
            raise CheckpointNotFoundError(
                f"Checkpoint {checkpoint_id} not found for workflow {workflow_id}"
            )

        with open(checkpoint_path, 'r') as f:
            checkpoint_data = json.load(f)

        # Restore domain state
        return WorkflowDomainState.from_dict(checkpoint_data["domain_state"])

    def list_checkpoints(self, workflow_id: str) -> List[Dict[str, Any]]:
        """List all checkpoints for a workflow.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            List of checkpoint metadata dicts (sorted by created_at desc)
        """
        workflow_dir = self._get_workflow_dir(workflow_id)
        checkpoints = []

        for checkpoint_file in workflow_dir.glob("cp-*.json"):
            with open(checkpoint_file, 'r') as f:
                checkpoint_data = json.load(f)
                checkpoints.append({
                    "checkpoint_id": checkpoint_data["checkpoint_id"],
                    "created_at": checkpoint_data["created_at"],
                    "stage": checkpoint_data["stage"],
                    "metadata": checkpoint_data.get("metadata", {})
                })

        # Sort by created_at descending (newest first)
        checkpoints.sort(key=lambda x: x["created_at"], reverse=True)
        return checkpoints

    def delete_checkpoint(self, workflow_id: str, checkpoint_id: str) -> bool:
        """Delete a specific checkpoint file.

        Args:
            workflow_id: Unique workflow execution ID
            checkpoint_id: Checkpoint ID to delete

        Returns:
            True if deleted, False if not found
        """
        checkpoint_path = self._get_checkpoint_path(workflow_id, checkpoint_id)
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            return True
        return False

    def get_latest_checkpoint(self, workflow_id: str) -> Optional[str]:
        """Get the latest checkpoint ID for a workflow.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            Latest checkpoint ID, or None if no checkpoints exist
        """
        checkpoints = self.list_checkpoints(workflow_id)
        if checkpoints:
            return cast(str, checkpoints[0]["checkpoint_id"])  # First is newest
        return None


class RedisCheckpointBackend(CheckpointBackend):
    """Redis-based checkpoint storage (optional, for distributed systems).

    Stores checkpoints in Redis with:
    - Key pattern: checkpoint:{workflow_id}:{checkpoint_id}
    - Metadata index: checkpoint_index:{workflow_id} (sorted set by timestamp)
    - Automatic expiration support

    Features:
    - Fast distributed access
    - Atomic operations
    - Optional TTL for automatic cleanup
    - Suitable for multi-worker deployments

    Requirements:
    - redis Python package
    - Running Redis server

    Example:
        >>> backend = RedisCheckpointBackend(redis_url="redis://localhost:6379")
        >>> checkpoint_id = backend.save_checkpoint("wf-123", domain)
        >>> domain = backend.load_checkpoint("wf-123", checkpoint_id)
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        ttl: Optional[int] = None
    ):
        """Initialize Redis-based checkpoint backend.

        Args:
            redis_url: Redis connection URL
            ttl: Optional time-to-live in seconds for checkpoints
        """
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "Redis backend requires 'redis' package. "
                "Install with: pip install redis"
            )

        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self.ttl = ttl

    def _generate_checkpoint_id(self) -> str:
        """Generate a unique checkpoint ID."""
        timestamp = int(time.time() * 1000)
        return f"cp-{timestamp}"

    def save_checkpoint(
        self,
        workflow_id: str,
        domain_state: WorkflowDomainState,
        checkpoint_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Save checkpoint to Redis.

        Args:
            workflow_id: Unique workflow execution ID
            domain_state: Serializable domain state to checkpoint
            checkpoint_id: Optional checkpoint ID (auto-generated if not provided)
            metadata: Optional metadata to store with checkpoint

        Returns:
            Checkpoint ID of the saved checkpoint
        """
        # Generate checkpoint ID if not provided
        if checkpoint_id is None:
            checkpoint_id = self._generate_checkpoint_id()

        # Build checkpoint data
        checkpoint_data = {
            "checkpoint_id": checkpoint_id,
            "workflow_id": workflow_id,
            "created_at": datetime.now(UTC).isoformat(),
            "stage": domain_state.current_stage,
            "domain_state": domain_state.to_dict(exclude_none=True),
            "metadata": metadata or {}
        }

        # Save to Redis
        key = f"checkpoint:{workflow_id}:{checkpoint_id}"
        self.redis_client.set(key, json.dumps(checkpoint_data), ex=self.ttl)

        # Add to index (sorted set by timestamp)
        index_key = f"checkpoint_index:{workflow_id}"
        timestamp = time.time()
        self.redis_client.zadd(index_key, {checkpoint_id: timestamp})

        return checkpoint_id

    def load_checkpoint(
        self,
        workflow_id: str,
        checkpoint_id: Optional[str] = None
    ) -> WorkflowDomainState:
        """Load checkpoint from Redis.

        Args:
            workflow_id: Unique workflow execution ID
            checkpoint_id: Checkpoint ID to load (latest if not specified)

        Returns:
            Restored WorkflowDomainState

        Raises:
            CheckpointNotFoundError: If checkpoint doesn't exist
        """
        # Get checkpoint ID if not specified
        if checkpoint_id is None:
            checkpoint_id = self.get_latest_checkpoint(workflow_id)
            if checkpoint_id is None:
                raise CheckpointNotFoundError(
                    f"No checkpoints found for workflow {workflow_id}"
                )

        # Load from Redis
        key = f"checkpoint:{workflow_id}:{checkpoint_id}"
        data = self.redis_client.get(key)

        if data is None:
            raise CheckpointNotFoundError(
                f"Checkpoint {checkpoint_id} not found for workflow {workflow_id}"
            )

        checkpoint_data = json.loads(data)
        return WorkflowDomainState.from_dict(checkpoint_data["domain_state"])

    def list_checkpoints(self, workflow_id: str) -> List[Dict[str, Any]]:
        """List all checkpoints for a workflow from Redis.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            List of checkpoint metadata dicts (sorted by created_at desc)
        """
        index_key = f"checkpoint_index:{workflow_id}"
        # Get all checkpoint IDs (sorted by score descending)
        checkpoint_ids = self.redis_client.zrevrange(index_key, 0, -1)

        checkpoints = []
        for cp_id in checkpoint_ids:
            key = f"checkpoint:{workflow_id}:{cp_id}"
            data = self.redis_client.get(key)
            if data:
                checkpoint_data = json.loads(data)
                checkpoints.append({
                    "checkpoint_id": checkpoint_data["checkpoint_id"],
                    "created_at": checkpoint_data["created_at"],
                    "stage": checkpoint_data["stage"],
                    "metadata": checkpoint_data.get("metadata", {})
                })

        return checkpoints

    def delete_checkpoint(self, workflow_id: str, checkpoint_id: str) -> bool:
        """Delete a specific checkpoint from Redis.

        Args:
            workflow_id: Unique workflow execution ID
            checkpoint_id: Checkpoint ID to delete

        Returns:
            True if deleted, False if not found
        """
        key = f"checkpoint:{workflow_id}:{checkpoint_id}"
        result = self.redis_client.delete(key)

        # Remove from index
        index_key = f"checkpoint_index:{workflow_id}"
        self.redis_client.zrem(index_key, checkpoint_id)

        return cast(bool, result > 0)

    def get_latest_checkpoint(self, workflow_id: str) -> Optional[str]:
        """Get the latest checkpoint ID for a workflow from Redis.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            Latest checkpoint ID, or None if no checkpoints exist
        """
        index_key = f"checkpoint_index:{workflow_id}"
        # Get the highest-scored item (most recent)
        checkpoint_ids = self.redis_client.zrevrange(index_key, 0, 0)
        if checkpoint_ids:
            return cast(str, checkpoint_ids[0])
        return None
