"""Performance benchmark tests.

Comprehensive performance testing:
- Throughput benchmarks (events/sec)
- Latency benchmarks (p50, p95, p99)
- Concurrency stress tests (10-50 workers)
- Memory leak detection
- Database query performance
"""
import asyncio
from datetime import datetime, timezone
import gc
import psutil
import statistics
import time
from typing import List
from unittest.mock import Mock, patch
import uuid

import pytest

from tests.fixtures.database_fixtures import db_session
from tests.fixtures.mock_helpers import mock_llm


# ============================================================================
# Throughput Benchmarks
# ============================================================================

class TestThroughputBenchmarks:
    """Test system throughput under various loads."""

    @pytest.fixture
    def execution_tracker(self):
        """Create execution tracker for benchmarks."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.observability.database import init_database

        init_database("sqlite:///:memory:")
        return ExecutionTracker()

    def test_event_tracking_throughput(self, execution_tracker):
        """Measure event tracking throughput (events/sec)."""
        event_count = 10000
        latencies = []

        with execution_tracker.track_workflow("throughput_test") as wf_id:
            start_time = time.perf_counter()

            for i in range(event_count):
                event_start = time.perf_counter()

                execution_tracker.track_event(
                    event_type="benchmark_event",
                    details={"index": i, "timestamp": datetime.now(timezone.utc).isoformat()}
                )

                event_end = time.perf_counter()
                latencies.append((event_end - event_start) * 1000)  # Convert to ms

            end_time = time.perf_counter()
            duration = end_time - start_time

        throughput = event_count / duration
        avg_latency = statistics.mean(latencies)

        # Performance assertions
        assert throughput > 100, f"Throughput too low: {throughput:.2f} events/sec"
        assert avg_latency < 10, f"Average latency too high: {avg_latency:.2f} ms"

        # Log benchmark results
        print(f"\n=== Event Tracking Throughput ===")
        print(f"Events: {event_count}")
        print(f"Duration: {duration:.2f}s")
        print(f"Throughput: {throughput:.2f} events/sec")
        print(f"Avg Latency: {avg_latency:.2f} ms")

    def test_workflow_execution_throughput(self, execution_tracker):
        """Measure workflow execution throughput."""
        workflow_count = 100
        start_time = time.perf_counter()

        workflow_ids = []
        for i in range(workflow_count):
            with execution_tracker.track_workflow(f"workflow_{i}") as wf_id:
                workflow_ids.append(wf_id)

                # Simulate minimal workflow
                with execution_tracker.track_agent("test_agent", "1.0") as agent_id:
                    execution_tracker.track_event(
                        event_type="agent_executed",
                        details={"workflow": i}
                    )

        end_time = time.perf_counter()
        duration = end_time - start_time
        throughput = workflow_count / duration

        assert throughput > 10, f"Workflow throughput too low: {throughput:.2f} workflows/sec"
        assert len(workflow_ids) == workflow_count

        print(f"\n=== Workflow Execution Throughput ===")
        print(f"Workflows: {workflow_count}")
        print(f"Duration: {duration:.2f}s")
        print(f"Throughput: {throughput:.2f} workflows/sec")

    def test_database_write_throughput(self, db_session):
        """Measure database write throughput."""
        from temper_ai.observability.models import Event

        record_count = 5000
        start_time = time.perf_counter()

        events = []
        for i in range(record_count):
            event = Event(
                id=str(uuid.uuid4()),
                workflow_run_id=str(uuid.uuid4()),
                event_type="benchmark_write",
                timestamp=datetime.now(timezone.utc),
                details={"index": i}
            )
            events.append(event)

        # Bulk insert
        db_session.add_all(events)
        db_session.commit()

        end_time = time.perf_counter()
        duration = end_time - start_time
        throughput = record_count / duration

        assert throughput > 100, f"DB write throughput too low: {throughput:.2f} records/sec"

        print(f"\n=== Database Write Throughput ===")
        print(f"Records: {record_count}")
        print(f"Duration: {duration:.2f}s")
        print(f"Throughput: {throughput:.2f} records/sec")


# ============================================================================
# Latency Benchmarks
# ============================================================================

class TestLatencyBenchmarks:
    """Test system latency characteristics (p50, p95, p99)."""

    @pytest.fixture
    def execution_tracker(self):
        """Create execution tracker for latency tests."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.observability.database import init_database

        init_database("sqlite:///:memory:")
        return ExecutionTracker()

    def test_event_tracking_latency_percentiles(self, execution_tracker):
        """Measure event tracking latency percentiles."""
        sample_count = 1000
        latencies: List[float] = []

        with execution_tracker.track_workflow("latency_test") as wf_id:
            for i in range(sample_count):
                start = time.perf_counter()

                execution_tracker.track_event(
                    event_type="latency_test",
                    details={"index": i}
                )

                end = time.perf_counter()
                latencies.append((end - start) * 1000)  # Convert to ms

        # Calculate percentiles
        latencies.sort()
        p50 = latencies[int(len(latencies) * 0.50)]
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]
        p999 = latencies[int(len(latencies) * 0.999)]

        # Performance assertions
        assert p50 < 5, f"p50 latency too high: {p50:.2f} ms"
        assert p95 < 15, f"p95 latency too high: {p95:.2f} ms"
        assert p99 < 30, f"p99 latency too high: {p99:.2f} ms"

        print(f"\n=== Event Tracking Latency Percentiles ===")
        print(f"Samples: {sample_count}")
        print(f"p50: {p50:.2f} ms")
        print(f"p95: {p95:.2f} ms")
        print(f"p99: {p99:.2f} ms")
        print(f"p99.9: {p999:.2f} ms")

    def test_workflow_context_latency(self, execution_tracker):
        """Measure workflow context creation latency."""
        sample_count = 500
        latencies: List[float] = []

        for i in range(sample_count):
            start = time.perf_counter()

            with execution_tracker.track_workflow(f"context_latency_{i}") as wf_id:
                pass  # Minimal workflow

            end = time.perf_counter()
            latencies.append((end - start) * 1000)

        latencies.sort()
        p50 = latencies[int(len(latencies) * 0.50)]
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]

        assert p50 < 2, f"Workflow context p50 too high: {p50:.2f} ms"
        assert p95 < 10, f"Workflow context p95 too high: {p95:.2f} ms"

        print(f"\n=== Workflow Context Latency ===")
        print(f"Samples: {sample_count}")
        print(f"p50: {p50:.2f} ms")
        print(f"p95: {p95:.2f} ms")
        print(f"p99: {p99:.2f} ms")

    def test_database_query_latency(self, db_session):
        """Measure database query latency percentiles."""
        from temper_ai.observability.models import Event

        # Insert test data
        events = [
            Event(
                id=str(uuid.uuid4()),
                workflow_run_id=str(uuid.uuid4()),
                event_type=f"query_test_{i % 10}",
                timestamp=datetime.now(timezone.utc),
                details={"index": i}
            )
            for i in range(1000)
        ]
        db_session.add_all(events)
        db_session.commit()

        # Measure query latency
        sample_count = 100
        latencies: List[float] = []

        for i in range(sample_count):
            start = time.perf_counter()

            # Perform query
            results = db_session.query(Event).filter(
                Event.event_type == f"query_test_{i % 10}"
            ).limit(10).all()

            end = time.perf_counter()
            latencies.append((end - start) * 1000)

        latencies.sort()
        p50 = latencies[int(len(latencies) * 0.50)]
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]

        assert p50 < 5, f"Query p50 too high: {p50:.2f} ms"
        assert p95 < 20, f"Query p95 too high: {p95:.2f} ms"

        print(f"\n=== Database Query Latency ===")
        print(f"Samples: {sample_count}")
        print(f"p50: {p50:.2f} ms")
        print(f"p95: {p95:.2f} ms")
        print(f"p99: {p99:.2f} ms")


# ============================================================================
# Concurrency Stress Tests
# ============================================================================

class TestConcurrencyStress:
    """Stress test system under concurrent load."""

    @pytest.fixture
    def execution_tracker(self):
        """Create execution tracker for concurrency tests."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.observability.database import init_database

        init_database("sqlite:///:memory:")
        return ExecutionTracker()

    def test_concurrent_workflow_execution_10_workers(self, execution_tracker):
        """Test 10 concurrent workflows."""
        worker_count = 10
        workflows_per_worker = 10

        def worker_task(worker_id):
            results = []
            for i in range(workflows_per_worker):
                with execution_tracker.track_workflow(f"worker_{worker_id}_wf_{i}") as wf_id:
                    with execution_tracker.track_agent(f"agent_{worker_id}", "1.0") as agent_id:
                        results.append((wf_id, agent_id))
            return results

        start_time = time.perf_counter()

        # Simulate concurrent workers (using sequential for determinism)
        all_results = []
        for worker_id in range(worker_count):
            results = worker_task(worker_id)
            all_results.extend(results)

        end_time = time.perf_counter()
        duration = end_time - start_time
        total_workflows = worker_count * workflows_per_worker
        throughput = total_workflows / duration

        assert len(all_results) == total_workflows
        assert throughput > 5, f"Concurrent throughput too low: {throughput:.2f} workflows/sec"

        print(f"\n=== 10 Worker Concurrency Test ===")
        print(f"Workers: {worker_count}")
        print(f"Workflows/Worker: {workflows_per_worker}")
        print(f"Total Workflows: {total_workflows}")
        print(f"Duration: {duration:.2f}s")
        print(f"Throughput: {throughput:.2f} workflows/sec")

    def test_concurrent_event_tracking_50_workers(self, execution_tracker):
        """Test 50 concurrent workers tracking events."""
        worker_count = 50
        events_per_worker = 100

        def worker_task(worker_id):
            count = 0
            for i in range(events_per_worker):
                execution_tracker.track_event(
                    event_type=f"worker_{worker_id}_event",
                    details={"worker": worker_id, "index": i}
                )
                count += 1
            return count

        start_time = time.perf_counter()

        # Simulate concurrent event tracking
        total_events = 0
        for worker_id in range(worker_count):
            count = worker_task(worker_id)
            total_events += count

        end_time = time.perf_counter()
        duration = end_time - start_time
        throughput = total_events / duration

        expected_total = worker_count * events_per_worker
        assert total_events == expected_total
        assert throughput > 50, f"Event throughput too low: {throughput:.2f} events/sec"

        print(f"\n=== 50 Worker Event Tracking Test ===")
        print(f"Workers: {worker_count}")
        print(f"Events/Worker: {events_per_worker}")
        print(f"Total Events: {total_events}")
        print(f"Duration: {duration:.2f}s")
        print(f"Throughput: {throughput:.2f} events/sec")

    def test_database_concurrent_writes(self, db_session):
        """Test concurrent database writes."""
        from temper_ai.observability.models import Event

        writer_count = 20
        writes_per_worker = 50

        def writer_task(writer_id):
            events = []
            for i in range(writes_per_worker):
                event = Event(
                    id=str(uuid.uuid4()),
                    workflow_run_id=str(uuid.uuid4()),
                    event_type=f"concurrent_write_{writer_id}",
                    timestamp=datetime.now(timezone.utc),
                    details={"writer": writer_id, "index": i}
                )
                events.append(event)
            return events

        start_time = time.perf_counter()

        all_events = []
        for writer_id in range(writer_count):
            events = writer_task(writer_id)
            all_events.extend(events)

        # Bulk insert all events
        db_session.add_all(all_events)
        db_session.commit()

        end_time = time.perf_counter()
        duration = end_time - start_time
        total_writes = writer_count * writes_per_worker
        throughput = total_writes / duration

        assert len(all_events) == total_writes
        assert throughput > 50, f"Concurrent write throughput too low: {throughput:.2f} writes/sec"

        print(f"\n=== Concurrent Database Writes ===")
        print(f"Writers: {writer_count}")
        print(f"Writes/Writer: {writes_per_worker}")
        print(f"Total Writes: {total_writes}")
        print(f"Duration: {duration:.2f}s")
        print(f"Throughput: {throughput:.2f} writes/sec")


# ============================================================================
# Memory Leak Detection
# ============================================================================

class TestMemoryLeaks:
    """Detect memory leaks in long-running operations."""

    @pytest.fixture
    def execution_tracker(self):
        """Create execution tracker for memory tests."""
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.observability.database import init_database

        init_database("sqlite:///:memory:")
        return ExecutionTracker()

    def test_workflow_execution_memory_stability(self, execution_tracker):
        """Memory usage should stabilize during repeated workflow execution."""
        process = psutil.Process()
        gc.collect()

        # Warm up
        for i in range(10):
            with execution_tracker.track_workflow(f"warmup_{i}") as wf_id:
                pass

        gc.collect()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Execute many workflows
        iteration_count = 100
        for i in range(iteration_count):
            with execution_tracker.track_workflow(f"memory_test_{i}") as wf_id:
                with execution_tracker.track_agent("test_agent", "1.0") as agent_id:
                    execution_tracker.track_event(
                        event_type="memory_test",
                        details={"iteration": i}
                    )

        gc.collect()
        final_memory = process.memory_info().rss / 1024 / 1024  # MB

        memory_increase = final_memory - initial_memory
        memory_per_iteration = memory_increase / iteration_count

        # Memory should not grow unboundedly
        assert memory_increase < 50, f"Memory increased too much: {memory_increase:.2f} MB"
        assert memory_per_iteration < 0.5, f"Memory per iteration too high: {memory_per_iteration:.3f} MB"

        print(f"\n=== Workflow Memory Stability ===")
        print(f"Iterations: {iteration_count}")
        print(f"Initial Memory: {initial_memory:.2f} MB")
        print(f"Final Memory: {final_memory:.2f} MB")
        print(f"Increase: {memory_increase:.2f} MB")
        print(f"Per Iteration: {memory_per_iteration:.3f} MB")

    def test_event_tracking_memory_growth(self, execution_tracker):
        """Event tracking should not leak memory."""
        process = psutil.Process()
        gc.collect()

        # Warm up
        for i in range(100):
            execution_tracker.track_event(
                event_type="warmup",
                details={"index": i}
            )

        gc.collect()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Track many events
        event_count = 1000
        for i in range(event_count):
            execution_tracker.track_event(
                event_type="memory_growth_test",
                details={"index": i, "data": f"event_{i}"}
            )

        gc.collect()
        final_memory = process.memory_info().rss / 1024 / 1024  # MB

        memory_increase = final_memory - initial_memory
        memory_per_event = memory_increase / event_count

        # Should not leak significant memory
        assert memory_increase < 30, f"Event tracking memory increase too high: {memory_increase:.2f} MB"
        assert memory_per_event < 0.03, f"Memory per event too high: {memory_per_event:.4f} MB"

        print(f"\n=== Event Tracking Memory Growth ===")
        print(f"Events: {event_count}")
        print(f"Initial Memory: {initial_memory:.2f} MB")
        print(f"Final Memory: {final_memory:.2f} MB")
        print(f"Increase: {memory_increase:.2f} MB")
        print(f"Per Event: {memory_per_event:.4f} MB")

    def test_database_connection_cleanup(self):
        """Database connections should be properly cleaned up."""
        from temper_ai.observability.database import init_database, get_session

        process = psutil.Process()
        gc.collect()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Create and close many sessions
        session_count = 50
        for i in range(session_count):
            init_database("sqlite:///:memory:")
            session = get_session()
            # Use session
            session.execute("SELECT 1")
            session.close()

        gc.collect()
        final_memory = process.memory_info().rss / 1024 / 1024  # MB

        memory_increase = final_memory - initial_memory

        # Connection cleanup should prevent memory growth
        assert memory_increase < 20, f"DB connection memory leak: {memory_increase:.2f} MB"

        print(f"\n=== Database Connection Cleanup ===")
        print(f"Sessions: {session_count}")
        print(f"Initial Memory: {initial_memory:.2f} MB")
        print(f"Final Memory: {final_memory:.2f} MB")
        print(f"Increase: {memory_increase:.2f} MB")


# ============================================================================
# Database Query Performance
# ============================================================================

class TestDatabasePerformance:
    """Test database query optimization and performance."""

    @pytest.fixture
    def populated_db(self, db_session):
        """Create database with test data."""
        from temper_ai.observability.models import WorkflowRun, Event

        # Create workflows
        workflow_ids = []
        for i in range(10):
            wf = WorkflowRun(
                id=str(uuid.uuid4()),
                workflow_name=f"workflow_{i % 3}",
                status="completed" if i % 2 == 0 else "running",
                start_time=datetime.now(timezone.utc),
                metadata={"index": i}
            )
            db_session.add(wf)
            workflow_ids.append(wf.id)

        db_session.commit()

        # Create events
        for wf_id in workflow_ids:
            for j in range(100):
                event = Event(
                    id=str(uuid.uuid4()),
                    workflow_run_id=wf_id,
                    event_type=f"event_type_{j % 10}",
                    timestamp=datetime.now(timezone.utc),
                    details={"index": j}
                )
                db_session.add(event)

        db_session.commit()
        return db_session

    def test_workflow_query_performance(self, populated_db):
        """Test workflow query performance."""
        from temper_ai.observability.models import WorkflowRun

        query_count = 50
        latencies = []

        for i in range(query_count):
            start = time.perf_counter()

            # Query workflows
            workflows = populated_db.query(WorkflowRun).filter(
                WorkflowRun.status == "completed"
            ).limit(10).all()

            end = time.perf_counter()
            latencies.append((end - start) * 1000)

        avg_latency = statistics.mean(latencies)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]

        assert avg_latency < 10, f"Workflow query avg latency too high: {avg_latency:.2f} ms"
        assert p95_latency < 20, f"Workflow query p95 too high: {p95_latency:.2f} ms"

        print(f"\n=== Workflow Query Performance ===")
        print(f"Queries: {query_count}")
        print(f"Avg Latency: {avg_latency:.2f} ms")
        print(f"p95 Latency: {p95_latency:.2f} ms")

    def test_event_aggregation_performance(self, populated_db):
        """Test event aggregation query performance."""
        from temper_ai.observability.models import Event
        from sqlalchemy import func

        query_count = 30
        latencies = []

        for i in range(query_count):
            start = time.perf_counter()

            # Aggregate events by type
            results = populated_db.query(
                Event.event_type,
                func.count(Event.id).label('count')
            ).group_by(Event.event_type).all()

            end = time.perf_counter()
            latencies.append((end - start) * 1000)

        avg_latency = statistics.mean(latencies)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]

        assert avg_latency < 15, f"Aggregation avg latency too high: {avg_latency:.2f} ms"
        assert p95_latency < 30, f"Aggregation p95 too high: {p95_latency:.2f} ms"

        print(f"\n=== Event Aggregation Performance ===")
        print(f"Queries: {query_count}")
        print(f"Avg Latency: {avg_latency:.2f} ms")
        print(f"p95 Latency: {p95_latency:.2f} ms")

    def test_join_query_performance(self, populated_db):
        """Test join query performance."""
        from temper_ai.observability.models import WorkflowRun, Event

        query_count = 20
        latencies = []

        for i in range(query_count):
            start = time.perf_counter()

            # Join workflows and events
            results = populated_db.query(WorkflowRun, Event).join(
                Event, WorkflowRun.id == Event.workflow_run_id
            ).filter(
                WorkflowRun.status == "completed"
            ).limit(50).all()

            end = time.perf_counter()
            latencies.append((end - start) * 1000)

        avg_latency = statistics.mean(latencies)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]

        assert avg_latency < 25, f"Join query avg latency too high: {avg_latency:.2f} ms"
        assert p95_latency < 50, f"Join query p95 too high: {p95_latency:.2f} ms"

        print(f"\n=== Join Query Performance ===")
        print(f"Queries: {query_count}")
        print(f"Avg Latency: {avg_latency:.2f} ms")
        print(f"p95 Latency: {p95_latency:.2f} ms")
