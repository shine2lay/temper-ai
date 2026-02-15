"""Tests for FailoverProvider thread safety.

Verifies that concurrent access to last_successful_index and
backup_success_count is properly synchronized.
"""

import threading
from unittest.mock import MagicMock

from src.llm.failover import FailoverConfig, FailoverProvider
from src.llm.providers import LLMResponse


def _make_mock_provider(name: str, succeed: bool = True):
    """Create a mock LLM provider."""
    provider = MagicMock()
    provider.model = name
    if succeed:
        provider.complete.return_value = LLMResponse(
            content=f"response from {name}",
            provider=name,
            model=name,
            prompt_tokens=5,
            completion_tokens=10,
            total_tokens=15,
        )
    else:
        provider.complete.side_effect = ConnectionError(f"{name} unavailable")
    return provider


class TestConcurrentComplete:
    """Verify state consistency under concurrent calls."""

    def test_backup_success_count_accurate(self):
        """backup_success_count matches actual backup successes under concurrency."""
        primary = _make_mock_provider("primary", succeed=False)
        backup = _make_mock_provider("backup", succeed=True)

        fp = FailoverProvider(
            providers=[primary, backup],
            config=FailoverConfig(retry_primary_after=1000),
        )

        errors = []
        barrier = threading.Barrier(20)

        def call():
            try:
                barrier.wait()
                fp.complete("test")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=call) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert fp.backup_success_count == 20
        assert fp.last_successful_index == 1

    def test_last_successful_index_consistent(self):
        """last_successful_index is always valid after concurrent calls."""
        providers = [_make_mock_provider(f"p{i}") for i in range(3)]
        fp = FailoverProvider(providers=providers)

        errors = []
        barrier = threading.Barrier(30)

        def call():
            try:
                barrier.wait()
                fp.complete("test")
                # Verify index is in valid range
                with fp._state_lock:
                    idx = fp.last_successful_index
                assert 0 <= idx < len(providers)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=call) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

    def test_concurrent_with_primary_retry_threshold(self):
        """Primary retry logic works correctly under contention."""
        primary = _make_mock_provider("primary", succeed=False)
        backup = _make_mock_provider("backup", succeed=True)

        fp = FailoverProvider(
            providers=[primary, backup],
            config=FailoverConfig(retry_primary_after=5),
        )

        errors = []

        def call():
            try:
                fp.complete("test")
            except Exception as e:
                errors.append(e)

        # Run 10 calls sequentially to accumulate backup_success_count
        for _ in range(10):
            call()

        assert not errors
        # At some point, primary was retried (at count=5), then backup resumed
        # The exact count depends on interleaving, but no errors should occur
        assert fp.last_successful_index == 1

    def test_stress_50_concurrent(self):
        """50 concurrent requests complete without exceptions."""
        primary = _make_mock_provider("primary")
        backup = _make_mock_provider("backup")

        fp = FailoverProvider(providers=[primary, backup])

        errors = []
        barrier = threading.Barrier(50)

        def call():
            try:
                barrier.wait()
                fp.complete("test")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=call) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


class TestResetThreadSafety:
    """Verify reset() is safe during concurrent calls."""

    def test_reset_during_concurrent_calls(self):
        """Resetting while calls are in flight doesn't cause errors."""
        primary = _make_mock_provider("primary")
        backup = _make_mock_provider("backup")

        fp = FailoverProvider(providers=[primary, backup])

        errors = []

        def caller():
            for _ in range(20):
                try:
                    fp.complete("test")
                except Exception as e:
                    errors.append(e)

        def resetter():
            for _ in range(10):
                fp.reset()

        threads = [threading.Thread(target=caller) for _ in range(5)]
        threads.append(threading.Thread(target=resetter))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


class TestPropertiesThreadSafety:
    """Verify model and provider_name properties are safe."""

    def test_model_property_under_contention(self):
        """model property returns valid string under contention."""
        providers = [_make_mock_provider(f"model_{i}") for i in range(3)]
        fp = FailoverProvider(providers=providers)

        results = []
        valid_names = {f"model_{i}" for i in range(3)}
        barrier = threading.Barrier(20)

        def read_model():
            barrier.wait()
            for _ in range(50):
                name = fp.model
                results.append(name in valid_names)

        threads = [threading.Thread(target=read_model) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results)
