"""Tests for buffer retry logic and dead-letter queue."""

from datetime import UTC, datetime

from temper_ai.observability.buffer import ObservabilityBuffer


class TestBufferRetryLogic:
    """Test retry logic with max_retries enforcement."""

    def test_retry_logic_success_after_failures(self):
        """Test items are retried up to max_retries and eventually succeed."""
        buffer = ObservabilityBuffer(max_retries=3, auto_flush=False)

        failure_count = 0

        def failing_flush(llm_calls, tool_calls, agent_metrics):
            nonlocal failure_count
            failure_count += 1
            if failure_count <= 2:
                raise Exception("Temporary failure")
            # Succeed on 3rd try

        buffer.set_flush_callback(failing_flush)
        buffer.buffer_llm_call(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="response",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            start_time=datetime.now(UTC),
        )

        # Flush 1 - Fail (both llm_call and agent_metric go to retry queue)
        buffer.flush()
        assert len(buffer.retry_queue) == 2  # llm_call + agent_metric
        assert all(item.retry_count == 1 for item in buffer.retry_queue)

        # Flush 2 - Fail
        buffer.flush()
        assert len(buffer.retry_queue) == 2
        assert all(item.retry_count == 2 for item in buffer.retry_queue)

        # Flush 3 - Success
        buffer.flush()
        assert len(buffer.retry_queue) == 0
        assert len(buffer.dead_letter_queue) == 0

    def test_dlq_after_max_retries(self):
        """Test items move to DLQ after exceeding max retries."""
        buffer = ObservabilityBuffer(max_retries=3, auto_flush=False)

        def always_fail(llm_calls, tool_calls, agent_metrics):
            raise Exception("Permanent failure")

        buffer.set_flush_callback(always_fail)
        buffer.buffer_llm_call(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="response",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            start_time=datetime.now(UTC),
        )

        # Try 4 times (initial + 3 retries = retry_count reaches 4, which is > max_retries)
        for _i in range(4):
            buffer.flush()

        assert len(buffer.retry_queue) == 0
        assert len(buffer.dead_letter_queue) == 2  # llm_call + agent_metric
        assert all(item.retry_count == 4 for item in buffer.dead_letter_queue)

    def test_deduplication_prevents_double_buffering(self):
        """Test duplicate items are not re-buffered."""
        buffer = ObservabilityBuffer(max_retries=3, auto_flush=False)

        fail_once = True
        flushed_calls = []

        def fail_then_succeed(llm_calls, tool_calls, agent_metrics):
            nonlocal fail_once
            flushed_calls.append(len(llm_calls))
            if fail_once:
                fail_once = False
                raise Exception("Temporary failure")

        buffer.set_flush_callback(fail_then_succeed)

        # Buffer same item (simulating duplicate tracking)
        buffer.buffer_llm_call(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="response",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            start_time=datetime.now(UTC),
        )

        buffer.flush()  # Fail - goes to retry queue
        assert len(buffer.retry_queue) == 2  # llm_call + agent_metric

        # Try to buffer again (should be deduplicated via pending_ids)
        buffer.buffer_llm_call(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="response",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            start_time=datetime.now(UTC),
        )

        buffer.flush()  # Success
        assert len(buffer.retry_queue) == 0

        # Should only flush 1 item, not 2 (deduplication worked)
        assert flushed_calls == [1, 1]

    def test_agent_metrics_merge_on_retry(self):
        """Test agent metrics are merged, not duplicated."""
        buffer = ObservabilityBuffer(max_retries=3, auto_flush=False)

        fail_once = True
        flushed_metrics = []

        def fail_then_succeed(llm_calls, tool_calls, agent_metrics):
            nonlocal fail_once
            flushed_metrics.append(dict(agent_metrics))
            if fail_once:
                fail_once = False
                raise Exception("Temporary failure")

        buffer.set_flush_callback(fail_then_succeed)

        # Add LLM call (creates metrics)
        buffer.buffer_llm_call(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="response",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            start_time=datetime.now(UTC),
        )

        buffer.flush()  # Fail - metrics in retry queue

        # Add another LLM call for same agent
        buffer.buffer_llm_call(
            llm_call_id="llm-2",
            agent_id="agent-1",
            provider="openai",
            model="gpt-4",
            prompt="test2",
            response="response2",
            prompt_tokens=20,
            completion_tokens=10,
            latency_ms=100,
            estimated_cost_usd=0.02,
            start_time=datetime.now(UTC),
        )

        buffer.flush()  # Success - should have merged metrics

        # Verify metrics were merged: 30 prompt tokens, 15 completion tokens
        agent_metrics = flushed_metrics[1]["agent-1"]
        assert agent_metrics.prompt_tokens == 30
        assert agent_metrics.completion_tokens == 15
        assert agent_metrics.num_llm_calls == 2

    def test_dlq_callback_invoked(self):
        """Test DLQ callback is invoked when items move to DLQ."""
        buffer = ObservabilityBuffer(max_retries=1, auto_flush=False)

        dlq_items = []
        buffer.set_dlq_callback(lambda item: dlq_items.append(item))

        def always_fail(llm_calls, tool_calls, agent_metrics):
            raise Exception("Permanent failure")

        buffer.set_flush_callback(always_fail)
        buffer.buffer_llm_call(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="response",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            start_time=datetime.now(UTC),
        )

        buffer.flush()  # Fail 1
        buffer.flush()  # Fail 2 -> DLQ

        assert len(dlq_items) == 2  # llm_call + agent_metric
        # Find the LLM call item
        llm_dlq = next(item for item in dlq_items if item.item_type == "llm_call")
        assert llm_dlq.item_id == "llm-1"
        assert llm_dlq.retry_count == 2

    def test_stats_include_retry_and_dlq_metrics(self):
        """Test get_stats includes retry queue and DLQ size."""
        buffer = ObservabilityBuffer(max_retries=3, auto_flush=False)

        def always_fail(llm_calls, tool_calls, agent_metrics):
            raise Exception("Permanent failure")

        buffer.set_flush_callback(always_fail)
        buffer.buffer_llm_call(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="response",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            start_time=datetime.now(UTC),
        )

        buffer.flush()  # Fail - goes to retry queue

        stats = buffer.get_stats()
        assert stats["retry_queue_size"] == 2  # llm_call + agent_metric
        assert stats["dlq_size"] == 0
        assert stats["max_retries"] == 3

        # Exhaust retries
        for _ in range(3):
            buffer.flush()

        stats = buffer.get_stats()
        assert stats["retry_queue_size"] == 0
        assert stats["dlq_size"] == 2  # llm_call + agent_metric

    def test_dlq_management_methods(self):
        """Test DLQ management API methods."""
        buffer = ObservabilityBuffer(max_retries=1, auto_flush=False)

        def always_fail(llm_calls, tool_calls, agent_metrics):
            raise Exception("Permanent failure")

        buffer.set_flush_callback(always_fail)
        buffer.buffer_llm_call(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="response",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            start_time=datetime.now(UTC),
        )

        # Move to DLQ
        for _ in range(2):
            buffer.flush()

        # Test get_dlq_items
        dlq_items = buffer.get_dlq_items()
        assert len(dlq_items) == 2  # llm_call + agent_metric
        llm_item = next(item for item in dlq_items if item.item_type == "llm_call")
        assert llm_item.item_id == "llm-1"

        # Test clear_dlq
        count = buffer.clear_dlq()
        assert count == 2
        assert len(buffer.get_dlq_items()) == 0

    def test_multiple_item_types_in_retry_queue(self):
        """Test retry queue handles multiple item types correctly."""
        buffer = ObservabilityBuffer(max_retries=3, auto_flush=False)

        fail_count = 0

        def fail_twice(llm_calls, tool_calls, agent_metrics):
            nonlocal fail_count
            fail_count += 1
            if fail_count <= 2:
                raise Exception("Temporary failure")

        buffer.set_flush_callback(fail_twice)

        # Buffer different item types
        buffer.buffer_llm_call(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="response",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            start_time=datetime.now(UTC),
        )

        buffer.buffer_tool_call(
            tool_execution_id="tool-1",
            agent_id="agent-1",
            tool_name="calculator",
            input_params={"a": 1, "b": 2},
            output_data={"result": 3},
            start_time=datetime.now(UTC),
            duration_seconds=0.5,
        )

        buffer.flush()  # Fail 1
        assert len(buffer.retry_queue) == 3  # llm_call + tool_call + agent_metric

        buffer.flush()  # Fail 2
        assert len(buffer.retry_queue) == 3

        buffer.flush()  # Success
        assert len(buffer.retry_queue) == 0
        assert len(buffer.dead_letter_queue) == 0

    def test_dlq_disabled(self):
        """Test behavior when DLQ is disabled."""
        buffer = ObservabilityBuffer(max_retries=1, enable_dlq=False, auto_flush=False)

        def always_fail(llm_calls, tool_calls, agent_metrics):
            raise Exception("Permanent failure")

        buffer.set_flush_callback(always_fail)
        buffer.buffer_llm_call(
            llm_call_id="llm-1",
            agent_id="agent-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="response",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            start_time=datetime.now(UTC),
        )

        # Exhaust retries
        for _ in range(2):
            buffer.flush()

        # Item should be removed from retry queue but not added to DLQ
        assert len(buffer.retry_queue) == 0
        assert len(buffer.dead_letter_queue) == 0  # DLQ disabled
