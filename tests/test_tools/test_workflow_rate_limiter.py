"""Tests for workflow-level rate limiting (R0.9)."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.shared.utils.exceptions import RateLimitError
from temper_ai.tools.workflow_rate_limiter import WorkflowRateLimiter
from temper_ai.tools.workflow_rate_limiter_constants import (
    DEFAULT_MAX_RPM,
    DEFAULT_MAX_WAIT_SECONDS,
    SLIDING_WINDOW_SECONDS,
)
from temper_ai.tools._executor_helpers import check_workflow_rate_limit


# ---------------------------------------------------------------------------
# WorkflowRateLimiter unit tests
# ---------------------------------------------------------------------------

class TestWorkflowRateLimiter:

    def test_acquire_under_limit(self) -> None:
        limiter = WorkflowRateLimiter(max_rpm=10)
        assert limiter.acquire() is True

    def test_acquire_tracks_usage(self) -> None:
        limiter = WorkflowRateLimiter(max_rpm=10)
        limiter.acquire()
        limiter.acquire()
        usage = limiter.get_usage()
        assert usage["current_rpm"] == 2
        assert usage["remaining"] == 8

    def test_acquire_raises_when_non_blocking(self) -> None:
        limiter = WorkflowRateLimiter(max_rpm=2, block_on_limit=False)
        limiter.acquire()
        limiter.acquire()
        with pytest.raises(RateLimitError, match="Workflow rate limit exceeded"):
            limiter.acquire()

    def test_acquire_blocks_until_capacity(self) -> None:
        limiter = WorkflowRateLimiter(max_rpm=2, block_on_limit=True, max_wait_seconds=5.0)

        # Fill up the window
        limiter.acquire()
        limiter.acquire()

        # Shift oldest timestamp to be almost expired
        with limiter._lock:
            if limiter._timestamps:
                limiter._timestamps[0] = time.time() - SLIDING_WINDOW_SECONDS + 0.05

        # Should succeed after brief wait
        start = time.monotonic()
        assert limiter.acquire() is True
        elapsed = time.monotonic() - start
        assert elapsed < 2.0  # should not take long

    def test_acquire_timeout_raises(self) -> None:
        limiter = WorkflowRateLimiter(max_rpm=1, block_on_limit=True, max_wait_seconds=0.1)
        limiter.acquire()
        with pytest.raises(RateLimitError, match="after waiting"):
            limiter.acquire()

    def test_get_usage_defaults(self) -> None:
        limiter = WorkflowRateLimiter()
        usage = limiter.get_usage()
        assert usage["max_rpm"] == DEFAULT_MAX_RPM
        assert usage["current_rpm"] == 0
        assert usage["remaining"] == DEFAULT_MAX_RPM
        assert usage["block_on_limit"] is True

    def test_sliding_window_cleanup(self) -> None:
        limiter = WorkflowRateLimiter(max_rpm=5)
        # Add some timestamps and simulate time passing
        limiter.acquire()
        limiter.acquire()

        # Artificially age all timestamps
        with limiter._lock:
            aged = time.time() - SLIDING_WINDOW_SECONDS - 1
            limiter._timestamps.clear()
            limiter._timestamps.append(aged)
            limiter._timestamps.append(aged)

        usage = limiter.get_usage()
        assert usage["current_rpm"] == 0  # aged out

    def test_thread_safety(self) -> None:
        limiter = WorkflowRateLimiter(max_rpm=100, block_on_limit=False)
        errors: list[str] = []
        acquired_count = threading.atomic = 0  # noqa: we track manually
        lock = threading.Lock()
        count = 0
        barrier = threading.Barrier(10)

        def worker() -> None:
            nonlocal count
            try:
                barrier.wait(timeout=5)
                for _ in range(8):
                    limiter.acquire()
                    with lock:
                        count += 1
            except (RateLimitError, threading.BrokenBarrierError) as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # Some might have hit the limit, but no crashes
        usage = limiter.get_usage()
        assert usage["current_rpm"] <= 100

    def test_default_constants(self) -> None:
        assert DEFAULT_MAX_RPM == 60
        assert DEFAULT_MAX_WAIT_SECONDS == 60.0
        assert SLIDING_WINDOW_SECONDS == 60.0

    def test_max_rpm_one(self) -> None:
        limiter = WorkflowRateLimiter(max_rpm=1, block_on_limit=False)
        assert limiter.acquire() is True
        with pytest.raises(RateLimitError):
            limiter.acquire()

    def test_get_usage_after_block_on_limit_false(self) -> None:
        limiter = WorkflowRateLimiter(max_rpm=3, block_on_limit=False)
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()
        usage = limiter.get_usage()
        assert usage["remaining"] == 0


# ---------------------------------------------------------------------------
# check_workflow_rate_limit helper
# ---------------------------------------------------------------------------

class TestCheckWorkflowRateLimit:

    def test_noop_when_no_limiter(self) -> None:
        executor = MagicMock()
        executor.workflow_rate_limiter = None
        check_workflow_rate_limit(executor)
        assert executor.workflow_rate_limiter is None  # unchanged, no error

    def test_calls_acquire_when_limiter_present(self) -> None:
        limiter = MagicMock()
        executor = MagicMock()
        executor.workflow_rate_limiter = limiter
        check_workflow_rate_limit(executor)
        limiter.acquire.assert_called_once()

    def test_propagates_rate_limit_error(self) -> None:
        limiter = MagicMock()
        limiter.acquire.side_effect = RateLimitError("limit hit")
        executor = MagicMock()
        executor.workflow_rate_limiter = limiter
        with pytest.raises(RateLimitError, match="limit hit"):
            check_workflow_rate_limit(executor)
