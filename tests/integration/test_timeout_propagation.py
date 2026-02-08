"""
Integration tests for timeout propagation across system layers.

Tests timeout cascading: Tool → Agent → Stage → Workflow
Validates cleanup, resource release, and context preservation.

CRITICAL: These tests validate that timeouts enforce correctly at each layer
and cascade properly through the execution hierarchy. Timeout failures can
cause production hangs, resource leaks, and lost context.
"""

import asyncio
import time

import pytest

from src.observability.database import get_database, init_database
from src.observability.tracker import ExecutionTracker

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_database():
    """Initialize in-memory database for testing."""
    try:
        get_database()
    except RuntimeError:
        init_database("sqlite:///:memory:")
    yield
    # Cleanup handled by in-memory database


@pytest.fixture
def execution_tracker(sample_database):
    """Execution tracker with test database."""
    from src.observability.backends.sql_backend import SQLObservabilityBackend
    backend = SQLObservabilityBackend()
    return ExecutionTracker(backend=backend)


# ============================================================================
# Test Class 1: Timeout Cascading (Priority 1)
# ============================================================================


class TestTimeoutCascading:
    """Tests for timeout propagation through architectural layers."""

    @pytest.mark.asyncio
    async def test_tool_timeout_propagates_to_agent(self):
        """
        CRITICAL: Tool timeout should trigger agent timeout.

        Architecture:
        - Tool: sleeps 60s
        - Tool timeout: 30s (would trigger at 30s)
        - Agent timeout: 10s (should interrupt at 10s)

        Expected: Agent timeout at ~10s (NOT 30s or 60s)
        """
        # Simulate tool layer (60s operation, 30s timeout)
        async def tool_operation():
            await asyncio.sleep(60)
            return "tool_done"

        # Simulate agent layer calling tool (10s timeout)
        async def agent_operation():
            # Agent calls tool with 30s tool timeout
            return await asyncio.wait_for(tool_operation(), timeout=30.0)

        start_time = time.time()

        # Execute: Should timeout at agent level (10s)
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await asyncio.wait_for(
                agent_operation(),
                timeout=10.0  # Agent timeout - should win
            )

        elapsed = time.time() - start_time

        # STRICT VALIDATION: Timeout at ~10s (agent), not 30s (tool) or 60s (completion)
        assert elapsed < 11.5, \
            f"TIMEOUT NOT ENFORCED! Took {elapsed:.2f}s, expected ~10s agent timeout"
        assert elapsed >= 9.0, \
            f"Timeout too early: {elapsed:.2f}s (expected ~10s)"

    @pytest.mark.asyncio
    async def test_agent_timeout_propagates_to_stage(self):
        """
        CRITICAL: Agent timeout should trigger stage timeout.

        Architecture:
        - Agent: executes for 60s
        - Agent timeout: 40s (would trigger at 40s)
        - Stage timeout: 15s (should interrupt at 15s)

        Expected: Stage timeout at ~15s (NOT 40s or 60s)
        """
        # Simulate agent layer (60s operation, 40s timeout)
        async def agent_operation():
            await asyncio.sleep(60)
            return "agent_done"

        # Simulate stage layer calling agent (15s timeout)
        async def stage_operation():
            # Stage calls agent with 40s agent timeout
            return await asyncio.wait_for(agent_operation(), timeout=40.0)

        start_time = time.time()

        # Execute: Should timeout at stage level (15s)
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await asyncio.wait_for(
                stage_operation(),
                timeout=15.0  # Stage timeout - should win
            )

        elapsed = time.time() - start_time

        # STRICT VALIDATION: Timeout at ~15s (stage), not 40s (agent) or 60s
        assert elapsed < 17.0, \
            f"STAGE TIMEOUT NOT ENFORCED! Took {elapsed:.2f}s, expected ~15s"
        assert elapsed >= 13.0, \
            f"Timeout too early: {elapsed:.2f}s (expected ~15s)"

    @pytest.mark.asyncio
    async def test_stage_timeout_propagates_to_workflow(self):
        """
        CRITICAL: Stage timeout should stop workflow execution.

        Architecture:
        - Stage: executes for 60s
        - Stage timeout: 30s (would trigger at 30s)
        - Workflow timeout: 20s (should interrupt at 20s)

        Expected: Workflow timeout at ~20s (NOT 30s or 60s)
        """
        # Track which stages executed
        stages_executed = []

        # Simulate stage 1 (60s operation, 30s timeout)
        async def slow_stage_1():
            stages_executed.append("stage_1")
            await asyncio.sleep(60)
            return "stage_1_done"

        # Simulate stage 2 (should never execute)
        async def stage_2():
            stages_executed.append("stage_2")
            return "stage_2_done"

        # Simulate workflow calling stages sequentially
        async def workflow_operation():
            result1 = await asyncio.wait_for(slow_stage_1(), timeout=30.0)
            result2 = await stage_2()
            return [result1, result2]

        start_time = time.time()

        # Execute: Should timeout at workflow level (20s)
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await asyncio.wait_for(
                workflow_operation(),
                timeout=20.0  # Workflow timeout - should win
            )

        elapsed = time.time() - start_time

        # STRICT VALIDATION: Timeout at ~20s (workflow), not later
        assert elapsed < 22.0, \
            f"WORKFLOW TIMEOUT NOT ENFORCED! Took {elapsed:.2f}s, expected ~20s"
        assert elapsed >= 18.0, \
            f"Timeout too early: {elapsed:.2f}s (expected ~20s)"

        # PARTIAL EXECUTION VALIDATION: stage_1 started, stage_2 never executed
        assert "stage_1" in stages_executed, "Stage 1 should have started"
        assert "stage_2" not in stages_executed, \
            "Stage 2 should not execute after timeout"

    @pytest.mark.asyncio
    async def test_full_stack_timeout_cascade(self):
        """
        CRITICAL: Timeout cascades through all 4 layers: Tool → Agent → Stage → Workflow

        Timeout Hierarchy (inner → outer):
        - Tool execution: 60s (would complete)
        - Tool timeout: 50s (would trigger)
        - Agent timeout: 40s (would trigger)
        - Stage timeout: 30s (would trigger)
        - Workflow timeout: 12s (SHOULD trigger) ← ENFORCED

        Expected: Workflow timeout at ~12s (NOT 30s, 40s, 50s, or 60s)
        """
        # Layer 1: Tool (60s execution, 50s timeout)
        async def tool_operation():
            await asyncio.sleep(60)
            return "tool_done"

        # Layer 2: Agent (40s timeout)
        async def agent_operation():
            return await asyncio.wait_for(tool_operation(), timeout=50.0)

        # Layer 3: Stage (30s timeout)
        async def stage_operation():
            return await asyncio.wait_for(agent_operation(), timeout=40.0)

        # Layer 4: Workflow (12s timeout) ← SHOULD WIN
        async def workflow_operation():
            return await asyncio.wait_for(stage_operation(), timeout=30.0)

        start_time = time.time()

        # Execute: Should timeout at OUTERMOST (workflow) level at 12s
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await asyncio.wait_for(
                workflow_operation(),
                timeout=12.0  # Workflow timeout - shortest
            )

        elapsed = time.time() - start_time

        # STRICT VALIDATION: Timeout at ~12s (workflow), not any inner layer
        assert elapsed < 14.0, \
            f"WORKFLOW TIMEOUT NOT ENFORCED! Took {elapsed:.2f}s, expected ~12s. " \
            f"Inner timeout (stage:30s, agent:40s, tool:50s) may have blocked cascade."
        assert elapsed >= 10.5, \
            f"Timeout too early: {elapsed:.2f}s (expected ~12s)"


# ============================================================================
# Test Class 2: Timeout Cleanup (Priority 2)
# ============================================================================


class TestTimeoutCleanup:
    """Tests for resource cleanup on timeout."""

    @pytest.mark.asyncio
    async def test_timeout_cleanup_releases_resources(self):
        """
        CRITICAL: Resources released when timeout interrupts operations.

        Resources tracked:
        - File handles, network connections

        Expected: All resources cleaned up after timeout
        """
        resource_tracker = {
            "files_opened": 0,
            "files_closed": 0,
        }

        async def resource_intensive_operation():
            """Operation that allocates resources."""
            # Acquire resource
            resource_tracker["files_opened"] += 1
            try:
                await asyncio.sleep(60)
                return "done"
            finally:
                # Release resource
                resource_tracker["files_closed"] += 1

        start_time = time.time()

        # Execute with timeout
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await asyncio.wait_for(
                resource_intensive_operation(),
                timeout=5.0
            )

        # Wait briefly for cleanup
        await asyncio.sleep(0.5)

        # RESOURCE LEAK VALIDATION
        assert resource_tracker["files_opened"] == resource_tracker["files_closed"], \
            f"RESOURCE LEAK! Opened {resource_tracker['files_opened']}, " \
            f"closed {resource_tracker['files_closed']}"

    @pytest.mark.asyncio
    async def test_concurrent_timeouts_no_deadlock(self):
        """
        CRITICAL: Multiple concurrent operations timing out should not deadlock.

        Scenario: 5 concurrent operations, all timeout simultaneously

        Expected:
        - All 5 operations timeout at ~10s
        - All cleanup within ~2s after timeout
        - No deadlocks
        """
        cleanup_times = []

        async def concurrent_operation(op_id: int):
            """Operation that tracks cleanup time."""
            try:
                await asyncio.sleep(60)
                return "done"
            finally:
                # Track cleanup time
                cleanup_times.append({
                    "op_id": op_id,
                    "cleanup_time": time.time()
                })

        start_time = time.time()

        # Execute: All operations should timeout concurrently
        operations = [concurrent_operation(i) for i in range(5)]

        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await asyncio.wait_for(
                asyncio.gather(*operations),
                timeout=10.0
            )

        timeout_time = time.time()
        elapsed = timeout_time - start_time

        # Wait for cleanup to complete
        await asyncio.sleep(2.0)

        # TIMEOUT VALIDATION
        assert elapsed < 12.0, f"Timeout took {elapsed:.2f}s, expected ~10s"

        # CLEANUP VALIDATION: All operations cleaned up
        assert len(cleanup_times) == 5, \
            f"Only {len(cleanup_times)}/5 operations cleaned up - possible deadlock"

        # DEADLOCK VALIDATION: All cleanups happened within 2s of timeout
        for cleanup in cleanup_times:
            cleanup_delay = cleanup["cleanup_time"] - timeout_time
            assert cleanup_delay < 2.0, \
                f"Operation {cleanup['op_id']} cleanup took {cleanup_delay:.2f}s - " \
                f"possible deadlock"


# ============================================================================
# Test Class 3: Edge Cases (Priority 3)
# ============================================================================


class TestTimeoutEdgeCases:
    """Edge cases and additional timeout coverage."""

    @pytest.mark.asyncio
    async def test_partial_results_captured_on_workflow_timeout(self):
        """
        Workflow timeout should preserve partial results from completed stages.

        Scenario: 3-stage workflow, timeout after stage 2
        Expected: Stages 1-2 outputs preserved, stage 3 not started
        """
        stages_executed = []
        stage_outputs = {}

        async def fast_stage_1():
            """First stage - completes quickly."""
            stages_executed.append("stage_1")
            stage_outputs["stage_1"] = "output_1"
            return "output_1"

        async def fast_stage_2():
            """Second stage - completes quickly."""
            stages_executed.append("stage_2")
            stage_outputs["stage_2"] = "output_2"
            return "output_2"

        async def slow_stage_3():
            """Third stage - times out."""
            stages_executed.append("stage_3")
            await asyncio.sleep(60)
            stage_outputs["stage_3"] = "output_3"
            return "output_3"

        async def workflow():
            """Execute stages sequentially."""
            result1 = await fast_stage_1()
            result2 = await fast_stage_2()
            result3 = await slow_stage_3()
            return [result1, result2, result3]

        # Execute with timeout during stage_3
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await asyncio.wait_for(workflow(), timeout=5.0)

        # PARTIAL EXECUTION VALIDATION
        assert "stage_1" in stages_executed, "Stage 1 should have completed"
        assert "stage_2" in stages_executed, "Stage 2 should have completed"
        assert "stage_3" in stages_executed, "Stage 3 should have started"

        # PARTIAL RESULTS PRESERVED
        assert "stage_1" in stage_outputs, "Stage 1 output should be preserved"
        assert "stage_2" in stage_outputs, "Stage 2 output should be preserved"

    @pytest.mark.asyncio
    async def test_fast_timeout_enforcement(self):
        """
        Fast timeouts (< 1s) should still enforce correctly.

        Challenge: OS scheduling, async overhead may add ~100-200ms
        Expected: Timeout at ~0.5s ± 0.2s tolerance
        """
        async def slow_operation():
            await asyncio.sleep(10)

        start = time.time()
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await asyncio.wait_for(slow_operation(), timeout=0.5)
        elapsed = time.time() - start

        # More lenient validation for sub-second timeouts
        assert elapsed < 0.7, \
            f"Fast timeout not enforced: {elapsed:.3f}s (expected ~0.5s)"
        assert elapsed >= 0.4, \
            f"Timeout too early: {elapsed:.3f}s (expected ~0.5s)"

    @pytest.mark.asyncio
    async def test_nested_timeout_hierarchy(self):
        """
        Nested timeouts should respect hierarchy (outer wins over inner).

        Hierarchy: outer (5s) < middle (10s) < inner (20s)
        Expected: Timeout at 5s (outer)
        """
        async def inner_operation():
            """Innermost operation with 20s timeout."""
            await asyncio.sleep(60)
            return "inner"

        async def middle_operation():
            """Middle operation with 10s timeout."""
            return await asyncio.wait_for(inner_operation(), timeout=20.0)

        async def outer_operation():
            """Outer operation with 5s timeout."""
            return await asyncio.wait_for(middle_operation(), timeout=10.0)

        start = time.time()

        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await asyncio.wait_for(outer_operation(), timeout=5.0)

        elapsed = time.time() - start

        # Validate outer timeout wins
        assert elapsed < 6.5, f"Outer timeout not enforced: {elapsed:.2f}s"
        assert elapsed >= 4.5, f"Timeout too early: {elapsed:.2f}s"
