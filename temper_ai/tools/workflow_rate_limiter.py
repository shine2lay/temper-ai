"""Workflow-level rate limiter with sliding window (R0.9).

Shared across all tool executors in a workflow run. Thread-safe.
Cache hits bypass rate limiting.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

from temper_ai.shared.utils.exceptions import RateLimitError
from temper_ai.tools.workflow_rate_limiter_constants import (
    DEFAULT_MAX_RPM,
    DEFAULT_MAX_WAIT_SECONDS,
    SLIDING_WINDOW_SECONDS,
)

logger = logging.getLogger(__name__)


class WorkflowRateLimiter:
    """Sliding-window rate limiter shared across a workflow run.

    All tool executors within the same workflow share a single instance
    so that the aggregate call rate stays under ``max_rpm``.  Cache hits
    should **not** call :meth:`acquire` (handled by the executor helpers).
    """

    def __init__(
        self,
        max_rpm: int = DEFAULT_MAX_RPM,
        block_on_limit: bool = True,
        max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    ) -> None:
        self._max_rpm = max_rpm
        self._block_on_limit = block_on_limit
        self._max_wait_seconds = max_wait_seconds
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self) -> bool:
        """Acquire a rate-limit slot.

        If the window is full and ``block_on_limit`` is True, the caller
        blocks until capacity frees up (up to ``max_wait_seconds``).

        Returns:
            ``True`` when a slot is successfully acquired.

        Raises:
            RateLimitError: When the limit is exceeded and blocking
                either timed out or is disabled.
        """
        deadline = time.monotonic() + self._max_wait_seconds

        while True:
            with self._lock:
                self._cleanup_window()

                if len(self._timestamps) < self._max_rpm:
                    self._timestamps.append(time.time())
                    return True

            # Over limit
            if not self._block_on_limit:
                raise RateLimitError(
                    f"Workflow rate limit exceeded: {self._max_rpm} RPM"
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RateLimitError(
                    f"Workflow rate limit exceeded after waiting "
                    f"{self._max_wait_seconds}s: {self._max_rpm} RPM"
                )

            # Wait for the oldest entry to expire, capped by remaining budget
            with self._lock:
                if self._timestamps:
                    oldest = self._timestamps[0]
                    sleep_for = (oldest + SLIDING_WINDOW_SECONDS) - time.time()
                else:
                    sleep_for = 0.0

            sleep_for = max(sleep_for, 0.01)  # minimum sleep  # scanner: skip-magic
            sleep_for = min(sleep_for, remaining)
            time.sleep(sleep_for)  # intentional: rate-limit wait

    def get_usage(self) -> dict[str, Any]:
        """Return current rate-limit usage snapshot."""
        with self._lock:
            self._cleanup_window()
            current = len(self._timestamps)
            return {
                "max_rpm": self._max_rpm,
                "current_rpm": current,
                "remaining": self._max_rpm - current,
                "block_on_limit": self._block_on_limit,
                "max_wait_seconds": self._max_wait_seconds,
            }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _cleanup_window(self) -> None:
        """Remove timestamps older than the sliding window. Caller holds lock."""
        cutoff = time.time() - SLIDING_WINDOW_SECONDS
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
