"""OAuth state storage.

Provides in-memory state storage for OAuth flows with:
- Automatic TTL expiration
- Atomic get-and-delete operations (one-time use)

Security Features:
- State tokens are single-use (deleted after validation)
- Automatic expiration after 10 minutes
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any

from temper_ai.auth.constants import FIELD_EXPIRES_AT
from temper_ai.shared.constants.durations import SECONDS_PER_10_MINUTES
from temper_ai.shared.constants.limits import (
    PERCENT_20,
    PERCENT_80,
    THRESHOLD_MASSIVE_COUNT,
)

logger = logging.getLogger(__name__)

# In-memory storage limits
MAX_ENTRIES_MULTIPLIER = 5  # Multiplier for max entries calculation

# Logging constants
STATE_TOKEN_LOG_LENGTH = 8  # Number of characters to show in logs for state tokens


class StateStore(ABC):
    """Abstract base class for state storage implementations."""

    @abstractmethod
    async def set_state(
        self,
        state: str,
        data: dict[str, Any],
        ttl_seconds: int = SECONDS_PER_10_MINUTES,
    ) -> None:
        """Store state data with TTL.

        Args:
            state: State token
            data: State data (user_id, provider, code_verifier, etc.)
            ttl_seconds: Time to live in seconds (default: 10 minutes)
        """
        ...

    @abstractmethod
    async def get_state(self, state: str) -> dict[str, Any] | None:
        """Retrieve and delete state data (one-time use).

        Args:
            state: State token

        Returns:
            State data or None if expired/not found
        """
        ...

    @abstractmethod
    async def delete_state(self, state: str) -> bool:
        """Delete state data.

        Args:
            state: State token

        Returns:
            True if deleted, False if not found
        """
        ...

    async def close(self) -> None:  # noqa: B027
        """Clean up resources."""
        pass

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Clean up expired state tokens.

        Returns:
            Number of expired states cleaned up
        """
        ...


class InMemoryStateStore(StateStore):
    """In-memory state storage.

    Note:
    - No persistence across restarts
    - Not suitable for distributed deployments
    - Manual cleanup required (no automatic TTL)
    """

    MAX_ENTRIES = THRESHOLD_MASSIVE_COUNT * MAX_ENTRIES_MULTIPLIER  # 50000

    def __init__(self, max_entries: int | None = None):
        """Initialize in-memory state storage.

        Args:
            max_entries: Maximum number of entries before auto-cleanup (default: 50000)
        """
        self._store: dict[str, dict[str, Any]] = {}
        self._max_entries = max_entries if max_entries is not None else self.MAX_ENTRIES
        self._lock = asyncio.Lock()

    async def set_state(
        self, state: str, data: dict[str, Any], ttl_seconds: int | None = None
    ) -> None:
        """Store state data with expiration time."""
        if ttl_seconds is None:
            ttl_seconds = SECONDS_PER_10_MINUTES

        async with self._lock:
            # Auto-cleanup when 80% full to prevent unbounded memory growth
            if len(self._store) >= int(self._max_entries * (PERCENT_80 / 100)):
                await self._cleanup_expired_unlocked()
                # If still over limit after cleanup, remove oldest 20%
                if len(self._store) >= self._max_entries:
                    self._evict_oldest()

            data_with_expiry = {
                **data,
                FIELD_EXPIRES_AT: (
                    datetime.now(UTC) + timedelta(seconds=ttl_seconds)
                ).isoformat(),
            }
            self._store[state] = data_with_expiry
        # SEC-14: Truncate state token in logs to prevent exposure
        logger.debug(
            f"Stored state: {state[:STATE_TOKEN_LOG_LENGTH]}... (TTL: {ttl_seconds}s)"
        )

    async def get_state(self, state: str) -> dict[str, Any] | None:
        """Retrieve and delete state data (one-time use).

        Uses asyncio.Lock + dict.pop() for atomic get-and-delete to prevent
        concurrent callbacks from consuming the same state token twice (AU-02).
        """
        async with self._lock:
            data = self._store.pop(state, None)

        if data is None:
            return None

        # Check expiration
        expires_at = datetime.fromisoformat(data[FIELD_EXPIRES_AT])
        if datetime.now(UTC) > expires_at:
            return None

        # Remove expires_at before returning
        data_copy = data.copy()
        del data_copy[FIELD_EXPIRES_AT]

        return data_copy

    async def delete_state(self, state: str) -> bool:
        """Delete state data."""
        async with self._lock:
            if state in self._store:
                del self._store[state]
                return True
            return False

    async def _cleanup_expired_unlocked(self) -> int:
        """Clean up expired states (must be called while holding self._lock).

        Returns:
            Number of states cleaned up
        """
        now = datetime.now(UTC)
        expired_keys = [
            state
            for state, data in self._store.items()
            if now > datetime.fromisoformat(data[FIELD_EXPIRES_AT])
        ]

        for key in expired_keys:
            del self._store[key]

        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired states")

        return len(expired_keys)

    async def cleanup_expired(self) -> int:
        """Clean up expired states (manual cleanup for in-memory store).

        Returns:
            Number of states cleaned up
        """
        async with self._lock:
            return await self._cleanup_expired_unlocked()

    def _evict_oldest(self) -> None:
        """Evict oldest 20% of entries when store exceeds max_entries."""
        to_remove = max(1, len(self._store) * PERCENT_20 // 100)
        # Sort by expires_at to remove the oldest entries first
        sorted_keys = sorted(
            self._store.keys(),
            key=lambda k: self._store[k].get(FIELD_EXPIRES_AT, ""),
        )
        for key in sorted_keys[:to_remove]:
            del self._store[key]
        logger.info(f"Evicted {to_remove} oldest state entries (size limit)")


def create_state_store() -> StateStore:
    """Factory function to create a state store.

    Returns:
        InMemoryStateStore instance
    """
    return InMemoryStateStore()
