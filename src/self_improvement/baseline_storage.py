"""
BaselineStorage for M5 Self-Improvement System.

Handles baseline profile persistence (file I/O, serialization, CRUD operations).
Extracted from PerformanceAnalyzer to follow Single Responsibility Principle.

Design Principles:
- File I/O isolated from analysis logic
- Security validation delegated to AgentPathValidator
- TOCTOU attack prevention (O_NOFOLLOW)
- Clear error messages
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import List, Optional

from src.self_improvement.data_models import AgentPerformanceProfile
from src.self_improvement.path_validator import AgentPathValidator

logger = logging.getLogger(__name__)

# File permissions for baseline storage
BASELINE_FILE_MODE = 0o644  # Read/write for owner, read-only for group/others


class BaselineStorageError(Exception):
    """Raised when baseline storage operations fail."""
    pass


class BaselineStorage:
    """
    Manages baseline profile persistence to filesystem.

    Responsibilities:
    - Store/retrieve/delete baseline profiles
    - List available baselines
    - Validate paths via AgentPathValidator
    - Prevent TOCTOU symlink attacks

    Example:
        >>> storage = BaselineStorage(Path(".baselines"))
        >>> storage.store(profile)
        >>> retrieved = storage.retrieve("my_agent")
        >>> storage.delete("my_agent")
    """

    def __init__(self, storage_path: Path):
        """
        Initialize baseline storage.

        Args:
            storage_path: Directory for baseline storage

        Raises:
            ValueError: If storage_path is a symlink
        """
        raw_path = Path(storage_path)

        # Reject symlinked storage directories to prevent escape attacks
        if raw_path.exists() and raw_path.is_symlink():
            raise ValueError("Baseline storage path must not be a symlink")

        self.storage_path = raw_path.resolve()
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Initialize path validator for this storage directory
        self.validator = AgentPathValidator(self.storage_path)

        logger.debug(f"Initialized BaselineStorage at {self.storage_path}")

    def store(
        self,
        profile: AgentPerformanceProfile,
        agent_name: Optional[str] = None
    ) -> AgentPerformanceProfile:
        """
        Store a baseline performance profile.

        Args:
            profile: AgentPerformanceProfile to store
            agent_name: Optional override agent name (defaults to profile.agent_name)

        Returns:
            The stored profile (with profile_id generated if missing)

        Raises:
            ValueError: If agent_name validation fails or mismatch
            BaselineStorageError: If storage operation fails

        Example:
            >>> profile = AgentPerformanceProfile(agent_name="my_agent", ...)
            >>> storage.store(profile)
        """
        # Determine agent name
        target_name = agent_name if agent_name is not None else profile.agent_name

        # Validate agent name mismatch
        if agent_name is not None and profile.agent_name != agent_name:
            raise ValueError(
                f"Profile agent_name '{profile.agent_name}' does not match "
                f"provided agent_name '{agent_name}'"
            )

        # Generate profile ID if not present
        if profile.profile_id is None:
            profile.profile_id = str(uuid.uuid4())

        # Get validated baseline file path
        baseline_file = self.validator.validate_and_resolve(target_name)

        try:
            # Use O_NOFOLLOW to prevent TOCTOU symlink attacks at write time
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, 'O_NOFOLLOW'):
                flags |= os.O_NOFOLLOW

            fd = os.open(str(baseline_file), flags, BASELINE_FILE_MODE)
            with os.fdopen(fd, 'w') as f:
                json.dump(profile.to_dict(), f, indent=2)

            logger.info(
                f"Stored baseline for {target_name}: "
                f"{profile.total_executions} executions, "
                f"window {profile.window_start} to {profile.window_end}"
            )

            return profile

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to store baseline for {target_name}: {e}")
            raise BaselineStorageError(f"Baseline storage failed: {e}") from e

    def retrieve(
        self,
        agent_name: str
    ) -> Optional[AgentPerformanceProfile]:
        """
        Retrieve a stored baseline performance profile.

        Args:
            agent_name: Name of agent

        Returns:
            AgentPerformanceProfile if baseline exists, None otherwise

        Raises:
            ValueError: If agent_name validation fails

        Example:
            >>> baseline = storage.retrieve("my_agent")
            >>> if baseline:
            ...     print(f"Baseline from {baseline.window_start}")
        """
        # Get validated baseline file path
        baseline_file = self.validator.validate_and_resolve(agent_name)

        if not baseline_file.exists():
            logger.debug(f"No stored baseline found for {agent_name}")
            return None

        try:
            # Use O_NOFOLLOW to prevent TOCTOU symlink attacks at read time
            flags = os.O_RDONLY
            if hasattr(os, 'O_NOFOLLOW'):
                flags |= os.O_NOFOLLOW

            fd = os.open(str(baseline_file), flags)
            with os.fdopen(fd, 'r') as f:
                data = json.load(f)

            profile = AgentPerformanceProfile.from_dict(data)

            logger.debug(
                f"Retrieved baseline for {agent_name}: "
                f"{profile.total_executions} executions"
            )

            return profile

        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"Failed to retrieve baseline for {agent_name}: {e}")
            return None

    def delete(
        self,
        agent_name: str
    ) -> bool:
        """
        Delete a stored baseline for an agent.

        Args:
            agent_name: Name of agent

        Returns:
            True if baseline was deleted, False if it didn't exist

        Raises:
            ValueError: If agent_name validation fails
            BaselineStorageError: If deletion fails

        Example:
            >>> storage.delete("my_agent")
            True
        """
        # Get validated baseline file path
        baseline_file = self.validator.validate_and_resolve(agent_name)

        if not baseline_file.exists():
            logger.debug(f"No baseline to delete for {agent_name}")
            return False

        try:
            # Re-check symlink immediately before delete to reduce TOCTOU window
            if baseline_file.is_symlink():
                raise ValueError("Invalid agent name: symlink detected")

            baseline_file.unlink()
            logger.info(f"Deleted baseline for {agent_name}")
            return True

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete baseline for {agent_name}: {e}")
            raise BaselineStorageError(f"Baseline deletion failed: {e}") from e

    def list_all(self) -> List[str]:
        """
        List all agent names with stored baselines.

        Returns:
            Sorted list of agent names

        Example:
            >>> agents = storage.list_all()
            >>> print(f"Found {len(agents)} baselines")
        """
        baselines = []

        for baseline_file in self.storage_path.glob("*_baseline.json"):
            # Extract agent name from filename (remove "_baseline.json")
            agent_name = baseline_file.stem.replace("_baseline", "")

            # Only include names that pass validation
            if self.validator.is_valid_agent_name(agent_name):
                baselines.append(agent_name)

        logger.debug(f"Found {len(baselines)} stored baselines")
        return sorted(baselines)

    def exists(self, agent_name: str) -> bool:
        """
        Check if a baseline exists for an agent.

        Args:
            agent_name: Name of agent

        Returns:
            True if baseline exists, False otherwise

        Raises:
            ValueError: If agent_name validation fails

        Example:
            >>> if storage.exists("my_agent"):
            ...     profile = storage.retrieve("my_agent")
        """
        baseline_file = self.validator.validate_and_resolve(agent_name)
        return baseline_file.exists()
