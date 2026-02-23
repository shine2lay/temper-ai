"""Integration tests for ObservabilityBuffer.

Tests buffer performance, query reduction, and flush strategies.
"""

import time
from datetime import datetime

import pytest

from temper_ai.observability.buffer import (
    ObservabilityBuffer,
)


class TestBufferQueryReduction:
    """Tests for database query reduction via buffering."""

    def test_observability_buffer_reduces_queries_significantly(self):
        """Test that buffering reduces DB queries by >85% for 100 events."""
        # Track query count
        query_count = 0

        def mock_flush_callback(llm_calls, tool_calls, agent_metrics):
            nonlocal query_count
            # Simulate batch operations (1 query per batch)
            if llm_calls:
                query_count += 1  # Batch INSERT for LLM calls
            if tool_calls:
                query_count += 1  # Batch INSERT for tool calls
            if agent_metrics:
                query_count += 1  # Batch UPDATE for agent metrics

        # Create buffer with small flush size to force batching
        buffer = ObservabilityBuffer(
            flush_size=10,  # Flush every 10 items
            flush_interval=10.0,  # Long interval to test size-based flush
            auto_flush=False,  # Manual control for testing
        )
        buffer.set_flush_callback(mock_flush_callback)

        # Buffer 100 LLM calls
        for i in range(100):
            buffer.buffer_llm_call(
                llm_call_id=f"llm-{i}",
                agent_id=f"agent-{i % 5}",  # 5 different agents
                provider="openai",
                model="gpt-4",
                prompt=f"test prompt {i}",
                response=f"test response {i}",
                prompt_tokens=50,
                completion_tokens=100,
                latency_ms=500,
                estimated_cost_usd=0.002,
                start_time=datetime.now(),
            )

        # Final flush for remaining items
        buffer.flush()

        # Without buffering: 100 events = 200 queries (1 INSERT + 1 UPDATE per event)
        # With buffering: 100 events = 30 queries (10 batches × 3 queries per batch)
        # Query reduction: (200 - 30) / 200 = 85%
        assert (
            query_count <= 30
        ), f"Expected ≤30 queries for 100 events with buffering, got {query_count}"

        # Verify >85% reduction
        non_buffered_queries = 200  # 100 INSERT + 100 UPDATE
        reduction_percent = (
            (non_buffered_queries - query_count) / non_buffered_queries
        ) * 100
        assert (
            reduction_percent >= 85
        ), f"Expected ≥85% query reduction, got {reduction_percent:.1f}%"

    def test_buffer_mixed_operations_query_count(self):
        """Test query count for mixed LLM and tool calls."""
        query_count = 0

        def mock_flush_callback(llm_calls, tool_calls, agent_metrics):
            nonlocal query_count
            if llm_calls:
                query_count += 1
            if tool_calls:
                query_count += 1
            if agent_metrics:
                query_count += 1

        buffer = ObservabilityBuffer(
            flush_size=20, flush_interval=10.0, auto_flush=False
        )
        buffer.set_flush_callback(mock_flush_callback)

        # Buffer 50 LLM calls + 50 tool calls
        for i in range(50):
            buffer.buffer_llm_call(
                llm_call_id=f"llm-{i}",
                agent_id="agent-1",
                provider="openai",
                model="gpt-4",
                prompt="test",
                response="test",
                prompt_tokens=50,
                completion_tokens=100,
                latency_ms=500,
                estimated_cost_usd=0.002,
                start_time=datetime.now(),
            )

            buffer.buffer_tool_call(
                tool_execution_id=f"tool-{i}",
                agent_id="agent-1",
                tool_name="calculator",
                input_params={"x": i},
                output_data={"result": i * 2},
                start_time=datetime.now(),
                duration_seconds=0.5,
            )

        buffer.flush()

        # With flush_size=20, we expect: 100 items / 20 = 5 flushes
        # Each flush: 3 queries (llm_calls, tool_calls, agent_metrics)
        # Total: 5 × 3 = 15 queries
        assert (
            query_count <= 18
        ), f"Expected ≤18 queries for 100 mixed events, got {query_count}"

    def test_buffer_without_callback_logs_warning(self, caplog):
        """Test that buffer without flush callback logs warning."""
        buffer = ObservabilityBuffer(auto_flush=False)
        # No callback set

        buffer.buffer_llm_call(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="test",
            prompt_tokens=50,
            completion_tokens=100,
            latency_ms=500,
            estimated_cost_usd=0.002,
            start_time=datetime.now(),
        )

        buffer.flush()

        # Should log warning about missing callback
        assert any("No flush callback" in record.message for record in caplog.records)


class TestBufferFlushStrategies:
    """Tests for different buffer flush strategies."""

    def test_size_based_flush_triggers_automatically(self):
        """Test that buffer flushes when size limit is reached."""
        flush_count = 0

        def mock_flush_callback(llm_calls, tool_calls, agent_metrics):
            nonlocal flush_count
            flush_count += 1

        buffer = ObservabilityBuffer(
            flush_size=10,  # Small size for testing
            flush_interval=10.0,
            auto_flush=False,
        )
        buffer.set_flush_callback(mock_flush_callback)

        # Add 25 items (should trigger 2 flushes at 10 and 20)
        for i in range(25):
            buffer.buffer_llm_call(
                llm_call_id=f"llm-{i}",
                agent_id="agent-1",
                provider="openai",
                model="gpt-4",
                prompt="test",
                response="test",
                prompt_tokens=50,
                completion_tokens=100,
                latency_ms=500,
                estimated_cost_usd=0.002,
                start_time=datetime.now(),
            )

        # Verify automatic flushes occurred
        assert (
            flush_count == 2
        ), f"Expected 2 automatic flushes (at 10, 20), got {flush_count}"

        # Verify remaining items in buffer
        stats = buffer.get_stats()
        assert (
            stats["llm_calls_buffered"] == 5
        ), f"Expected 5 items in buffer after auto-flushes, got {stats['llm_calls_buffered']}"

    def test_time_based_flush_with_auto_flush(self):
        """Test that buffer flushes automatically after time interval."""
        flush_count = 0

        def mock_flush_callback(llm_calls, tool_calls, agent_metrics):
            nonlocal flush_count
            flush_count += 1

        # Create buffer with short flush interval
        buffer = ObservabilityBuffer(
            flush_size=1000,  # Large size to prevent size-based flush
            flush_interval=0.2,  # 200ms interval
            auto_flush=True,  # Enable auto-flush thread
        )
        buffer.set_flush_callback(mock_flush_callback)

        try:
            # Add a few items
            for i in range(5):
                buffer.buffer_llm_call(
                    llm_call_id=f"llm-{i}",
                    agent_id="agent-1",
                    provider="openai",
                    model="gpt-4",
                    prompt="test",
                    response="test",
                    prompt_tokens=50,
                    completion_tokens=100,
                    latency_ms=500,
                    estimated_cost_usd=0.002,
                    start_time=datetime.now(),
                )

            # Wait for auto-flush (200ms interval + margin)
            time.sleep(0.5)

            # Verify time-based flush occurred
            assert (
                flush_count >= 1
            ), f"Expected at least 1 time-based flush after 500ms, got {flush_count}"

        finally:
            buffer.stop()

    def test_manual_flush_clears_buffer(self):
        """Test that manual flush clears all buffered items."""
        flush_count = 0
        flushed_items = []

        def mock_flush_callback(llm_calls, tool_calls, agent_metrics):
            nonlocal flush_count
            flush_count += 1
            flushed_items.append(
                {
                    "llm_calls": len(llm_calls),
                    "tool_calls": len(tool_calls),
                    "agent_metrics": len(agent_metrics),
                }
            )

        buffer = ObservabilityBuffer(
            flush_size=1000,  # Large size to prevent auto-flush
            flush_interval=10.0,
            auto_flush=False,
        )
        buffer.set_flush_callback(mock_flush_callback)

        # Add items
        for i in range(15):
            buffer.buffer_llm_call(
                llm_call_id=f"llm-{i}",
                agent_id="agent-1",
                provider="openai",
                model="gpt-4",
                prompt="test",
                response="test",
                prompt_tokens=50,
                completion_tokens=100,
                latency_ms=500,
                estimated_cost_usd=0.002,
                start_time=datetime.now(),
            )

        # Manual flush
        buffer.flush()

        # Verify flush occurred
        assert flush_count == 1
        assert flushed_items[0]["llm_calls"] == 15

        # Verify buffer is empty
        stats = buffer.get_stats()
        assert stats["total_buffered"] == 0, "Buffer should be empty after flush"


class TestBufferOverflow:
    """Tests for buffer overflow and edge cases."""

    def test_buffer_handles_large_batch(self):
        """Test buffer can handle large batches of events."""
        flush_count = 0
        total_flushed = 0

        def mock_flush_callback(llm_calls, tool_calls, agent_metrics):
            nonlocal flush_count, total_flushed
            flush_count += 1
            total_flushed += len(llm_calls) + len(tool_calls)

        buffer = ObservabilityBuffer(
            flush_size=50, flush_interval=10.0, auto_flush=False
        )
        buffer.set_flush_callback(mock_flush_callback)

        # Add 500 events
        for i in range(500):
            buffer.buffer_llm_call(
                llm_call_id=f"llm-{i}",
                agent_id=f"agent-{i % 10}",
                provider="openai",
                model="gpt-4",
                prompt="test",
                response="test",
                prompt_tokens=50,
                completion_tokens=100,
                latency_ms=500,
                estimated_cost_usd=0.002,
                start_time=datetime.now(),
            )

        buffer.flush()

        # Verify all events were flushed
        assert total_flushed == 500, f"Expected 500 events flushed, got {total_flushed}"

        # Verify multiple batches
        assert flush_count == 10, f"Expected 10 flushes (500/50), got {flush_count}"

    def test_buffer_overflow_with_concurrent_operations(self):
        """Test buffer handles concurrent additions during flush."""
        import threading

        flush_count = 0
        lock = threading.Lock()

        def mock_flush_callback(llm_calls, tool_calls, agent_metrics):
            nonlocal flush_count
            with lock:
                flush_count += 1
            # Simulate slow flush
            time.sleep(0.01)

        buffer = ObservabilityBuffer(
            flush_size=10, flush_interval=10.0, auto_flush=False
        )
        buffer.set_flush_callback(mock_flush_callback)

        # Add items from multiple threads
        def add_items(thread_id):
            for i in range(20):
                buffer.buffer_llm_call(
                    llm_call_id=f"llm-{thread_id}-{i}",
                    agent_id=f"agent-{thread_id}",
                    provider="openai",
                    model="gpt-4",
                    prompt="test",
                    response="test",
                    prompt_tokens=50,
                    completion_tokens=100,
                    latency_ms=500,
                    estimated_cost_usd=0.002,
                    start_time=datetime.now(),
                )

        threads = []
        for i in range(5):
            thread = threading.Thread(target=add_items, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        buffer.flush()

        # Verify flushes occurred (5 threads × 20 items = 100 items / 10 = 10 flushes)
        assert flush_count >= 10, f"Expected at least 10 flushes, got {flush_count}"

    def test_empty_buffer_flush_does_nothing(self):
        """Test that flushing empty buffer doesn't call callback."""
        flush_count = 0

        def mock_flush_callback(llm_calls, tool_calls, agent_metrics):
            nonlocal flush_count
            flush_count += 1

        buffer = ObservabilityBuffer(auto_flush=False)
        buffer.set_flush_callback(mock_flush_callback)

        # Flush empty buffer
        buffer.flush()
        buffer.flush()
        buffer.flush()

        # Callback should not be called for empty flushes
        assert flush_count == 0, "Flush callback should not be called for empty buffer"


class TestBufferStatistics:
    """Tests for buffer statistics and monitoring."""

    def test_get_stats_returns_accurate_counts(self):
        """Test that get_stats returns accurate buffer statistics."""
        buffer = ObservabilityBuffer(
            flush_size=100, flush_interval=1.0, auto_flush=False
        )
        buffer.set_flush_callback(lambda *args: None)

        # Initially empty
        stats = buffer.get_stats()
        assert stats["llm_calls_buffered"] == 0
        assert stats["tool_calls_buffered"] == 0
        assert stats["total_buffered"] == 0

        # Add some items
        for i in range(10):
            buffer.buffer_llm_call(
                llm_call_id=f"llm-{i}",
                agent_id="agent-1",
                provider="openai",
                model="gpt-4",
                prompt="test",
                response="test",
                prompt_tokens=50,
                completion_tokens=100,
                latency_ms=500,
                estimated_cost_usd=0.002,
                start_time=datetime.now(),
            )

        for i in range(5):
            buffer.buffer_tool_call(
                tool_execution_id=f"tool-{i}",
                agent_id="agent-1",
                tool_name="calculator",
                input_params={"x": i},
                output_data={"result": i * 2},
                start_time=datetime.now(),
                duration_seconds=0.5,
            )

        # Check stats
        stats = buffer.get_stats()
        assert stats["llm_calls_buffered"] == 10
        assert stats["tool_calls_buffered"] == 5
        assert stats["total_buffered"] == 15
        assert stats["flush_size"] == 100
        assert stats["flush_interval"] == 1.0

    def test_stats_reset_after_flush(self):
        """Test that buffer stats reset after flush."""
        buffer = ObservabilityBuffer(auto_flush=False)
        buffer.set_flush_callback(lambda *args: None)

        # Add items
        for i in range(20):
            buffer.buffer_llm_call(
                llm_call_id=f"llm-{i}",
                agent_id="agent-1",
                provider="openai",
                model="gpt-4",
                prompt="test",
                response="test",
                prompt_tokens=50,
                completion_tokens=100,
                latency_ms=500,
                estimated_cost_usd=0.002,
                start_time=datetime.now(),
            )

        # Verify items are buffered
        stats_before = buffer.get_stats()
        assert stats_before["total_buffered"] == 20

        # Flush
        buffer.flush()

        # Verify buffer is empty
        stats_after = buffer.get_stats()
        assert stats_after["total_buffered"] == 0
        assert stats_after["llm_calls_buffered"] == 0


class TestBufferContextManager:
    """Tests for buffer context manager functionality."""

    def test_buffer_as_context_manager_flushes_on_exit(self):
        """Test that buffer flushes when used as context manager."""
        flush_count = 0

        def mock_flush_callback(llm_calls, tool_calls, agent_metrics):
            nonlocal flush_count
            flush_count += 1

        with ObservabilityBuffer(auto_flush=False) as buffer:
            buffer.set_flush_callback(mock_flush_callback)

            # Add items
            for i in range(10):
                buffer.buffer_llm_call(
                    llm_call_id=f"llm-{i}",
                    agent_id="agent-1",
                    provider="openai",
                    model="gpt-4",
                    prompt="test",
                    response="test",
                    prompt_tokens=50,
                    completion_tokens=100,
                    latency_ms=500,
                    estimated_cost_usd=0.002,
                    start_time=datetime.now(),
                )

        # Context manager should flush on exit
        assert flush_count == 1, "Context manager should flush on exit"

    def test_buffer_context_manager_flushes_even_on_exception(self):
        """Test that buffer flushes even if exception occurs."""
        flush_count = 0

        def mock_flush_callback(llm_calls, tool_calls, agent_metrics):
            nonlocal flush_count
            flush_count += 1

        try:
            with ObservabilityBuffer(auto_flush=False) as buffer:
                buffer.set_flush_callback(mock_flush_callback)

                buffer.buffer_llm_call(
                    llm_call_id="llm-1",
                    agent_id="agent-1",
                    provider="openai",
                    model="gpt-4",
                    prompt="test",
                    response="test",
                    prompt_tokens=50,
                    completion_tokens=100,
                    latency_ms=500,
                    estimated_cost_usd=0.002,
                    start_time=datetime.now(),
                )

                # Raise exception
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Buffer should still flush despite exception
        assert flush_count == 1, "Buffer should flush even when exception occurs"


class TestBufferErrorHandling:
    """Tests for buffer error handling."""

    def test_buffer_retries_failed_flush(self, caplog):
        """Test that buffer re-buffers items when flush fails."""
        flush_attempts = []

        def failing_flush_callback(llm_calls, tool_calls, agent_metrics):
            attempt_num = len(flush_attempts) + 1
            flush_attempts.append(attempt_num)
            if attempt_num == 1:
                raise Exception("Simulated flush failure")
            # Succeed on second attempt

        buffer = ObservabilityBuffer(auto_flush=False)
        buffer.set_flush_callback(failing_flush_callback)

        # Add items
        buffer.buffer_llm_call(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="test",
            prompt_tokens=50,
            completion_tokens=100,
            latency_ms=500,
            estimated_cost_usd=0.002,
            start_time=datetime.now(),
        )

        # First flush (will fail and items go to retry queue)
        buffer.flush()

        # Verify error was logged
        assert any(
            "Error flushing buffer" in record.message for record in caplog.records
        )

        # After failed flush, items move to retry queue (not main buffer)
        stats = buffer.get_stats()
        assert (
            stats["retry_queue_size"] >= 1
        ), "Items should be in retry queue after failed flush"

        # Second flush (will succeed, retrying from retry queue)
        buffer.flush()

        # Verify retry queue is cleared after successful flush
        stats = buffer.get_stats()
        assert (
            stats["retry_queue_size"] == 0
        ), "Retry queue should be cleared after successful flush"

        assert (
            len(flush_attempts) == 2
        ), f"Should have attempted flush twice, got {len(flush_attempts)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
