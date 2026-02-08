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
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

logger = logging.getLogger(__name__)

from src.compiler.domain_state import WorkflowDomainState
from src.constants.durations import TIMEOUT_SHORT
from src.constants.limits import MAX_SHORT_STRING_LENGTH
from src.utils.exceptions import ConfigurationError, ErrorCode


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


class CheckpointNotFoundError(ConfigurationError):
    """Raised when a checkpoint cannot be found."""

    def __init__(self, message: str, **kwargs):
        super().__init__(
            message=message,
            error_code=ErrorCode.CONFIG_NOT_FOUND,
            **kwargs
        )


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

    def __init__(self, checkpoint_dir: str = "./checkpoints", hmac_key: Optional[str] = None):
        """Initialize file-based checkpoint backend.

        Args:
            checkpoint_dir: Directory to store checkpoint files
            hmac_key: Secret key for HMAC integrity verification.
                      If not provided, reads from CHECKPOINT_HMAC_KEY env var.
                      If env var is also unset, generates a random key and
                      logs a warning (integrity cannot survive restarts).
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0  # Counter for unique IDs within same millisecond

        # M-10: HMAC integrity verification for checkpoint files
        if hmac_key is not None:
            self._hmac_key = hmac_key.encode() if isinstance(hmac_key, str) else hmac_key
        else:
            env_key = os.environ.get("CHECKPOINT_HMAC_KEY")
            # H-22: Require CHECKPOINT_HMAC_KEY in production
            is_production = os.environ.get("ENVIRONMENT", "").lower() == "production"

            if env_key:
                self._hmac_key = env_key.encode()
            elif is_production:
                raise ValueError(
                    "CHECKPOINT_HMAC_KEY environment variable is required in production. "
                    "Generate with: python -c 'import secrets; print(secrets.token_hex(32))'"
                )
            else:
                self._hmac_key = secrets.token_bytes(32)
                logger.warning(
                    "CHECKPOINT_HMAC_KEY not set. Generated ephemeral HMAC key. "
                    "Checkpoint integrity verification will not survive process restarts. "
                    "Set CHECKPOINT_HMAC_KEY environment variable for persistent integrity."
                )

    def _compute_hmac(self, data: bytes) -> str:
        """Compute HMAC-SHA256 of checkpoint data.

        Args:
            data: Raw checkpoint bytes to authenticate.

        Returns:
            Hex-encoded HMAC digest.
        """
        return hmac.new(self._hmac_key, data, hashlib.sha256).hexdigest()

    def _verify_hmac(self, data: bytes, expected_hmac: str) -> bool:
        """Verify HMAC-SHA256 of checkpoint data using constant-time comparison.

        Args:
            data: Raw checkpoint bytes.
            expected_hmac: Hex-encoded HMAC digest to verify against.

        Returns:
            True if HMAC is valid, False otherwise.
        """
        actual = hmac.new(self._hmac_key, data, hashlib.sha256).hexdigest()
        return hmac.compare_digest(actual, expected_hmac)

    @staticmethod
    def _sanitize_id(id_value: str, id_type: str = "identifier") -> str:
        """Sanitize an ID to prevent path traversal attacks.

        Args:
            id_value: The ID to sanitize (workflow_id or checkpoint_id)
            id_type: Label for error messages

        Returns:
            Sanitized ID containing only [A-Za-z0-9_-]

        Raises:
            ValueError: If ID is empty, contains null bytes, exceeds length,
                        or has no valid characters after sanitization
        """
        if not id_value or not isinstance(id_value, str):
            raise ValueError(f"{id_type} must be a non-empty string")
        if '\x00' in id_value:
            raise ValueError(f"{id_type} contains null bytes")
        if len(id_value) > MAX_SHORT_STRING_LENGTH:
            raise ValueError(f"{id_type} exceeds maximum length of {MAX_SHORT_STRING_LENGTH} characters")
        sanitized = re.sub(r'[^A-Za-z0-9_-]', '_', id_value)
        if not sanitized:
            raise ValueError(f"{id_type} contains no valid characters after sanitization")
        return sanitized

    def _verify_path_containment(self, resolved_path: Path) -> None:
        """Verify that a resolved path stays within checkpoint_dir.

        Raises:
            ValueError: If resolved_path escapes the checkpoint directory
        """
        resolved_parent = self.checkpoint_dir.resolve()
        try:
            resolved_path.relative_to(resolved_parent)
        except ValueError:
            raise ValueError(
                f"Path traversal detected: {resolved_path} is outside "
                f"allowed directory {resolved_parent}"
            )

    def _get_workflow_dir(self, workflow_id: str) -> Path:
        """Get checkpoint directory for a workflow with path traversal protection."""
        safe_id = self._sanitize_id(workflow_id, "workflow_id")
        workflow_dir = self.checkpoint_dir / safe_id
        resolved = workflow_dir.resolve(strict=False)
        self._verify_path_containment(resolved)
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    def _generate_checkpoint_id(self) -> str:
        """Generate a unique checkpoint ID with cryptographic randomness.

        Uses timestamp for ordering + counter for uniqueness within millisecond
        + secrets.token_hex for cryptographic randomness to prevent enumeration.

        Returns:
            Checkpoint ID in format: cp-{timestamp}-{counter}-{random}
            Example: cp-1706745600000-1-a3f2d9
        """
        timestamp = int(time.time() * 1000)  # Millisecond precision
        self._counter += 1
        random_suffix = secrets.token_hex(6)  # 12 hex chars (48 bits of entropy)
        return f"cp-{timestamp}-{self._counter}-{random_suffix}"

    def _get_checkpoint_path(self, workflow_id: str, checkpoint_id: str) -> Path:
        """Get file path for a checkpoint with path traversal protection."""
        workflow_dir = self._get_workflow_dir(workflow_id)
        safe_cp_id = self._sanitize_id(checkpoint_id, "checkpoint_id")
        checkpoint_path = workflow_dir / f"{safe_cp_id}.json"
        resolved = checkpoint_path.resolve(strict=False)
        self._verify_path_containment(resolved)
        return resolved

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

        # M-10: Compute HMAC over the serialized checkpoint data for integrity
        checkpoint_json = json.dumps(checkpoint_data, indent=2)
        checkpoint_hmac = self._compute_hmac(checkpoint_json.encode())

        # Wrap checkpoint with HMAC envelope
        envelope = {
            "hmac": checkpoint_hmac,
            "data": checkpoint_data,
        }

        # Atomic write: write to temp file then os.replace() to target path.
        # os.replace() is atomic on POSIX, preventing partial/corrupted checkpoint
        # files from concurrent writes or crashes mid-write.
        checkpoint_path = self._get_checkpoint_path(workflow_id, checkpoint_id)
        fd, tmp_path = tempfile.mkstemp(
            dir=checkpoint_path.parent,
            suffix='.tmp',
            prefix='.cp-'
        )
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(envelope, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, checkpoint_path)
        except BaseException:
            # Clean up temp file on any failure (including KeyboardInterrupt)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

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
            raw = json.load(f)

        # M-10: HMAC integrity verification.
        # New-format files have {"hmac": ..., "data": ...} envelope.
        # Old-format files (pre-HMAC) have checkpoint_data directly at top level.
        if "hmac" in raw and "data" in raw:
            # New format — verify integrity before deserializing
            checkpoint_data = raw["data"]
            stored_hmac = raw["hmac"]
            canonical_json = json.dumps(checkpoint_data, indent=2).encode()
            if not self._verify_hmac(canonical_json, stored_hmac):
                raise CheckpointNotFoundError(
                    f"Checkpoint {checkpoint_id} for workflow {workflow_id} "
                    "failed HMAC integrity verification (possible tampering)"
                )
        else:
            # Legacy checkpoint without HMAC — allow loading with warning
            checkpoint_data = raw
            logger.warning(
                "Loading checkpoint %s without HMAC verification "
                "(legacy format). Re-save to add integrity protection.",
                checkpoint_id,
            )

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
                raw = json.load(f)
                # Handle both HMAC envelope and legacy formats
                checkpoint_data = raw.get("data", raw) if "hmac" in raw else raw
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

        CO-05: Uses file modification time to find the latest file, then
        reads only that single file instead of loading ALL checkpoint files.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            Latest checkpoint ID, or None if no checkpoints exist
        """
        workflow_dir = self._get_workflow_dir(workflow_id)
        checkpoint_files = list(workflow_dir.glob("cp-*.json"))
        if not checkpoint_files:
            return None
        # Use file modification time to find the latest checkpoint
        latest_file = max(checkpoint_files, key=lambda f: f.stat().st_mtime)
        # Read only the latest file to extract the canonical checkpoint_id
        with open(latest_file, 'r') as f:
            raw = json.load(f)
        # Handle both HMAC envelope and legacy formats
        data = raw.get("data", raw) if "hmac" in raw else raw
        return cast(str, data["checkpoint_id"])


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

        self.redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=TIMEOUT_SHORT,
            socket_timeout=TIMEOUT_SHORT,
        )
        self.ttl = ttl

    @staticmethod
    def _sanitize_id(value: str) -> str:
        """Sanitize IDs for use in Redis keys (CO-04)."""
        import re as _re
        return _re.sub(r'[^a-zA-Z0-9_\-.]', '_', value)

    def _generate_checkpoint_id(self) -> str:
        """Generate a unique checkpoint ID (CO-07: uuid4 prevents collisions)."""
        import uuid
        return f"cp-{uuid.uuid4().hex[:16]}"

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

        # CO-04: Sanitize IDs for Redis key safety
        safe_wf = self._sanitize_id(workflow_id)
        safe_cp = self._sanitize_id(checkpoint_id)

        # CO-08: Atomic save using pipeline (SET + ZADD)
        key = f"checkpoint:{safe_wf}:{safe_cp}"
        index_key = f"checkpoint_index:{safe_wf}"
        timestamp = time.time()

        pipe = self.redis_client.pipeline(transaction=True)
        pipe.set(key, json.dumps(checkpoint_data), ex=self.ttl)
        pipe.zadd(index_key, {checkpoint_id: timestamp})
        # CO-09: Set TTL on the index sorted set so it doesn't leak memory.
        # Use 2x the checkpoint TTL to ensure index outlives its entries.
        pipe.expire(index_key, self.ttl * 2)
        pipe.execute()

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

        # Load from Redis (CO-04: sanitize IDs)
        safe_wf = self._sanitize_id(workflow_id)
        safe_cp = self._sanitize_id(checkpoint_id)
        key = f"checkpoint:{safe_wf}:{safe_cp}"
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
        safe_wf = self._sanitize_id(workflow_id)
        index_key = f"checkpoint_index:{safe_wf}"
        # Get all checkpoint IDs (sorted by score descending)
        checkpoint_ids = self.redis_client.zrevrange(index_key, 0, -1)

        # CO-06: Use pipeline to batch-fetch all checkpoint data in a single
        # round-trip instead of N+1 individual GET calls.
        if not checkpoint_ids:
            return []

        keys = [
            f"checkpoint:{safe_wf}:{self._sanitize_id(cp_id)}"
            for cp_id in checkpoint_ids
        ]
        results = self.redis_client.mget(keys)

        checkpoints = []
        for data in results:
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
        # CO-04: Sanitize IDs; CO-08: Atomic delete
        safe_wf = self._sanitize_id(workflow_id)
        safe_cp = self._sanitize_id(checkpoint_id)
        key = f"checkpoint:{safe_wf}:{safe_cp}"
        index_key = f"checkpoint_index:{safe_wf}"

        pipe = self.redis_client.pipeline(transaction=True)
        pipe.delete(key)
        pipe.zrem(index_key, checkpoint_id)
        results = pipe.execute()

        return cast(bool, results[0] > 0)

    def get_latest_checkpoint(self, workflow_id: str) -> Optional[str]:
        """Get the latest checkpoint ID for a workflow from Redis.

        Args:
            workflow_id: Unique workflow execution ID

        Returns:
            Latest checkpoint ID, or None if no checkpoints exist
        """
        index_key = f"checkpoint_index:{self._sanitize_id(workflow_id)}"
        # Get the highest-scored item (most recent)
        checkpoint_ids = self.redis_client.zrevrange(index_key, 0, 0)
        if checkpoint_ids:
            return cast(str, checkpoint_ids[0])
        return None
