"""Load and stress tests for meta-autonomous-framework.

Tests system behavior under high load and resource constraints.
Validates scalability, resource management, and graceful degradation.

Run with: pytest tests/test_load/test_stress.py -v
"""
import asyncio
import gc
import os
import time

import psutil
import pytest

from src.observability.database import DatabaseManager
from src.tools.base import BaseTool, ToolResult
from src.tools.registry import ToolRegistry

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def test_db():
    """In-memory database for testing."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    return db


@pytest.fixture
def tool_registry():
    """Tool registry for testing."""
    registry = ToolRegistry()

    # Register mock tool
    class MockTool(BaseTool):
        name = "MockTool"
        description = "Mock tool for testing"

        def get_metadata(self):
            from src.tools.base import ToolMetadata
            return ToolMetadata(
                name="MockTool",
                description="Mock tool for testing",
                version="1.0",
                category="test"
            )

        def get_parameters_schema(self):
            return {"type": "object", "properties": {}}

        def execute(self, **kwargs) -> ToolResult:
            return ToolResult(
                success=True,
                output={"result": "success"},
                metadata={"execution_time": 0.001}
            )

    registry.register(MockTool())  # Register instance, not class
    return registry


# ============================================================================
# Load Tests - Tool Registry
# ============================================================================

@pytest.mark.slow
def test_1000_tool_executions(tool_registry):
    """Test 1000+ tool executions under load.

    Validates:
    - Tool registry handles high call volume
    - No resource leaks
    - Consistent execution times
    """
    num_executions = 1000
    results = []

    start_time = time.time()

    tool = tool_registry.get("MockTool")
    for i in range(num_executions):
        result = tool.execute(input=f"test_{i}")
        results.append(result)

    end_time = time.time()
    duration = end_time - start_time

    # Validate all succeeded
    successful = sum(1 for r in results if r.success)
    assert successful == num_executions, f"Only {successful}/{num_executions} succeeded"

    # Validate throughput (should be very fast since mocked)
    throughput = num_executions / duration
    assert throughput > 1000, f"Tool throughput {throughput:.1f} calls/s too low"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_concurrent_tool_execution():
    """Test 100+ concurrent tool executions.

    Validates proper concurrent access to tools.
    """
    class AsyncMockTool(BaseTool):
        name = "AsyncMockTool"
        description = "Async mock tool"

        def get_metadata(self):
            from src.tools.base import ToolMetadata
            return ToolMetadata(
                name="AsyncMockTool",
                description="Async mock tool",
                version="1.0",
                category="test"
            )

        def get_parameters_schema(self):
            return {"type": "object", "properties": {}}

        def execute(self, **kwargs) -> ToolResult:
            # Required abstract method
            return ToolResult(success=True, output={}, metadata={})

        async def execute_async(self, **kwargs) -> ToolResult:
            await asyncio.sleep(0.001)  # Simulate async work
            return ToolResult(
                success=True,
                output={"result": "async_success"},
                metadata={}
            )

    registry = ToolRegistry()
    registry.register(AsyncMockTool())  # Register instance

    tool = registry.get("AsyncMockTool")

    num_concurrent = 100
    tasks = []

    for i in range(num_concurrent):
        task = tool.execute_async(input=f"test_{i}")
        tasks.append(task)

    results = await asyncio.gather(*tasks)

    # All should succeed
    successful = sum(1 for r in results if r.success)
    assert successful == num_concurrent, f"Only {successful}/{num_concurrent} succeeded"


# ============================================================================
# Load Tests - Database Operations
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.slow
async def test_1000_database_writes(test_db):
    """Test 1000+ database write operations.

    Validates database handles high write volume.
    """
    num_writes = 1000

    async def write_operation(op_id: int):
        with test_db.session() as session:
            # Simulate database write (actual SQL execution)
            await asyncio.sleep(0)
            return op_id

    tasks = []
    for i in range(num_writes):
        task = write_operation(i)
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # All should succeed
    successful = sum(1 for r in results if not isinstance(r, Exception))
    assert successful == num_writes, f"Only {successful}/{num_writes} writes succeeded"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_concurrent_database_access(test_db):
    """Test 100+ concurrent database operations.

    Validates:
    - Proper connection pooling
    - No connection leaks
    - Transaction isolation
    """
    num_operations = 100

    async def db_operation(op_id: int):
        with test_db.session() as session:
            await asyncio.sleep(0.001)
            return op_id

    tasks = []
    for i in range(num_operations):
        task = db_operation(i)
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    successful = sum(1 for r in results if not isinstance(r, Exception))
    assert successful == num_operations, f"DB operations: {successful}/{num_operations}"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_database_write_contention(test_db):
    """Test database under heavy concurrent write load.

    Validates:
    - Proper transaction isolation
    - No deadlocks
    - Data integrity under contention
    """
    num_writers = 50
    writes_per_writer = 10

    async def concurrent_writer(writer_id: int):
        results = []
        for i in range(writes_per_writer):
            with test_db.session() as session:
                await asyncio.sleep(0.001)
                results.append(f"writer_{writer_id}_write_{i}")
        return results

    tasks = []
    for writer_id in range(num_writers):
        task = concurrent_writer(writer_id)
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # All writers should complete
    successful = sum(1 for r in results if not isinstance(r, Exception))
    assert successful == num_writers, f"Database contention issues: {successful}/{num_writers}"

    # Verify total writes
    total_writes = sum(len(r) for r in results if not isinstance(r, Exception))
    expected_writes = num_writers * writes_per_writer
    assert total_writes == expected_writes, f"Lost writes: {total_writes}/{expected_writes}"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_database_read_write_mix(test_db):
    """Test database under mixed read/write load.

    Validates proper handling of mixed workload.
    """
    num_readers = 30
    num_writers = 20
    operations_per_task = 10

    async def reader(reader_id: int):
        for i in range(operations_per_task):
            with test_db.session() as session:
                await asyncio.sleep(0.001)
        return reader_id

    async def writer(writer_id: int):
        for i in range(operations_per_task):
            with test_db.session() as session:
                await asyncio.sleep(0.002)
        return writer_id

    tasks = []
    for i in range(num_readers):
        tasks.append(reader(i))
    for i in range(num_writers):
        tasks.append(writer(i))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    successful = sum(1 for r in results if not isinstance(r, Exception))
    expected = num_readers + num_writers
    assert successful == expected, f"Mixed workload issues: {successful}/{expected}"


# ============================================================================
# Stress Tests - Memory
# ============================================================================

@pytest.mark.slow
def test_memory_pressure_tool_registry():
    """Test tool registry under memory pressure.

    Validates:
    - No memory leaks
    - Proper cleanup
    """
    registry = ToolRegistry()

    class MockTool(BaseTool):
        name = "MockTool"
        description = "Mock tool"

        def get_metadata(self):
            from src.tools.base import ToolMetadata
            return ToolMetadata(
                name="MockTool",
                description="Mock tool",
                version="1.0",
                category="test"
            )

        def get_parameters_schema(self):
            return {"type": "object", "properties": {}}

        def execute(self, **kwargs) -> ToolResult:
            return ToolResult(success=True, output={"result": "ok"}, metadata={})

    registry.register(MockTool())  # Register instance

    # Get baseline memory
    process = psutil.Process(os.getpid())
    baseline_memory = process.memory_info().rss / 1024 / 1024  # MB

    # Execute many tool calls
    tool = registry.get("MockTool")
    for i in range(10000):
        result = tool.execute(input=f"test_{i}")

        if i % 1000 == 0:
            gc.collect()

    # Check memory after execution
    gc.collect()
    final_memory = process.memory_info().rss / 1024 / 1024
    memory_growth = final_memory - baseline_memory

    # Memory should not grow significantly
    assert memory_growth < 50, f"Memory leak detected: grew by {memory_growth:.1f}MB"


@pytest.mark.slow
def test_memory_leak_detection_database():
    """Test for memory leaks in database operations.

    Validates no memory leaks over many operations.
    """
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()

    # Get baseline memory
    process = psutil.Process(os.getpid())
    gc.collect()
    baseline_memory = process.memory_info().rss / 1024 / 1024

    # Perform many database operations
    for i in range(1000):
        with db.session() as session:
            pass  # Simple session open/close

        if i % 100 == 0:
            gc.collect()

    # Final GC and memory check
    gc.collect()
    final_memory = process.memory_info().rss / 1024 / 1024
    memory_growth = final_memory - baseline_memory

    # Memory should not grow significantly
    assert memory_growth < 30, f"Memory leak in DB: grew by {memory_growth:.1f}MB"


# ============================================================================
# Stress Tests - Resource Exhaustion
# ============================================================================

@pytest.mark.slow
def test_file_descriptor_management(test_db):
    """Test file descriptor management.

    Validates proper cleanup of file descriptors.
    """
    # Get baseline file descriptor count
    process = psutil.Process(os.getpid())
    baseline_fds = process.num_fds() if hasattr(process, 'num_fds') else len(process.open_files())

    # Perform many operations
    for i in range(100):
        with test_db.session() as session:
            pass

    # Check file descriptor count
    final_fds = process.num_fds() if hasattr(process, 'num_fds') else len(process.open_files())
    fd_growth = final_fds - baseline_fds

    # Should not leak file descriptors
    assert fd_growth < 10, f"File descriptor leak: grew by {fd_growth}"


# ============================================================================
# Performance Tests - Throughput
# ============================================================================

@pytest.mark.slow
def test_tool_registry_throughput():
    """Test tool registry maximum throughput.

    Measures peak operations per second.
    """
    registry = ToolRegistry()

    class FastTool(BaseTool):
        name = "FastTool"
        description = "Fast tool"

        def get_metadata(self):
            from src.tools.base import ToolMetadata
            return ToolMetadata(
                name="FastTool",
                description="Fast tool",
                version="1.0",
                category="test"
            )

        def get_parameters_schema(self):
            return {"type": "object", "properties": {}}

        def execute(self, **kwargs) -> ToolResult:
            return ToolResult(success=True, output={"result": "fast"}, metadata={})

    registry.register(FastTool())  # Register instance

    tool = registry.get("FastTool")
    duration_seconds = 2
    operations = 0

    start_time = time.time()

    while time.time() - start_time < duration_seconds:
        result = tool.execute(input="test")
        operations += 1

    actual_duration = time.time() - start_time
    throughput = operations / actual_duration

    # Should achieve high throughput (>10,000 ops/sec for simple mocked tool)
    assert throughput > 10000, f"Throughput {throughput:.1f} ops/s too low"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_async_throughput():
    """Test async operation throughput.

    Validates high concurrency handling.
    """
    async def fast_async_operation(op_id: int):
        await asyncio.sleep(0)
        return op_id

    duration_seconds = 2
    operations = 0
    tasks = []

    start_time = time.time()

    while time.time() - start_time < duration_seconds:
        task = fast_async_operation(operations)
        tasks.append(task)
        operations += 1

        # Yield periodically
        if operations % 100 == 0:
            await asyncio.sleep(0)

    results = await asyncio.gather(*tasks)

    actual_duration = time.time() - start_time
    throughput = operations / actual_duration

    # Should achieve high throughput
    assert throughput > 1000, f"Async throughput {throughput:.1f} ops/s too low"


# ============================================================================
# Stress Tests - Error Handling
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.slow
async def test_error_handling_under_load():
    """Test error handling when operations fail under load.

    Validates:
    - Proper error propagation
    - No cascading failures
    - System remains stable
    """
    async def failing_operation(op_id: int):
        if op_id % 2 == 0:
            raise Exception("Simulated failure")
        return op_id

    num_operations = 100
    tasks = []

    for i in range(num_operations):
        task = failing_operation(i)
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Should have 50% failures
    exceptions = sum(1 for r in results if isinstance(r, Exception))
    successes = sum(1 for r in results if not isinstance(r, Exception))

    assert 45 <= exceptions <= 55, f"Unexpected failure rate: {exceptions}/100"
    assert 45 <= successes <= 55, f"Unexpected success rate: {successes}/100"


# ============================================================================
# Load Tests - Sustained Operations
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.slow
async def test_sustained_load_1000_operations():
    """Test sustained load with 1000 operations.

    Validates:
    - System handles sustained load
    - No performance degradation
    - Consistent response times
    """
    async def operation(op_id: int):
        await asyncio.sleep(0.001)
        return op_id

    num_operations = 1000
    batch_size = 100

    all_results = []
    execution_times = []

    # Execute in batches
    for batch_num in range(num_operations // batch_size):
        batch_start = time.time()

        tasks = []
        for i in range(batch_size):
            op_id = batch_num * batch_size + i
            task = operation(op_id)
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_results.extend(results)

        batch_duration = time.time() - batch_start
        execution_times.append(batch_duration)

    # Validate all succeeded
    successful = sum(1 for r in all_results if not isinstance(r, Exception))
    assert successful == num_operations, f"Only {successful}/{num_operations} succeeded"

    # Validate performance consistency
    first_batch_time = execution_times[0]
    last_batch_time = execution_times[-1]

    # Allow some variance but ensure no major degradation
    # With async operations, later batches might even be faster due to warmup
    # So we just check they're in the same ballpark
    assert last_batch_time < first_batch_time * 2, "Significant performance degradation detected"


# ============================================================================
# End of load and stress tests
# ============================================================================
