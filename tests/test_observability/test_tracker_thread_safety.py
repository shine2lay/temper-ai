"""Tests for ExecutionTracker and SQLObservabilityBackend thread safety.

Verifies that concurrent access to ExecutionContext and session stacks
is properly isolated per-thread using contextvars and threading.local().
"""

import threading
from unittest.mock import MagicMock

from temper_ai.observability.tracker import ExecutionContext, ExecutionTracker


def _make_mock_backend():
    """Create a mock observability backend with session context."""
    backend = MagicMock()
    backend.get_session_context.return_value.__enter__ = MagicMock(return_value=MagicMock())
    backend.get_session_context.return_value.__exit__ = MagicMock(return_value=False)
    return backend


class TestContextIsolation:
    """Verify ExecutionContext is isolated per-thread."""

    def test_contexts_isolated_between_threads(self):
        """Two threads writing to context don't interfere with each other."""
        backend = _make_mock_backend()
        tracker = ExecutionTracker(backend=backend)

        thread_contexts = {}
        barrier = threading.Barrier(2)

        def set_context(thread_name, wf_id, stage_id, agent_id):
            barrier.wait()
            tracker.context.workflow_id = wf_id
            tracker.context.stage_id = stage_id
            tracker.context.agent_id = agent_id
            # Small yield to let other thread set its values
            threading.Event().wait(0.01)
            # Read back our own context
            thread_contexts[thread_name] = {
                "workflow_id": tracker.context.workflow_id,
                "stage_id": tracker.context.stage_id,
                "agent_id": tracker.context.agent_id,
            }

        t1 = threading.Thread(target=set_context, args=("t1", "wf-1", "st-1", "ag-1"))
        t2 = threading.Thread(target=set_context, args=("t2", "wf-2", "st-2", "ag-2"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert thread_contexts["t1"] == {"workflow_id": "wf-1", "stage_id": "st-1", "agent_id": "ag-1"}
        assert thread_contexts["t2"] == {"workflow_id": "wf-2", "stage_id": "st-2", "agent_id": "ag-2"}

    def test_main_thread_context_unaffected_by_child(self):
        """Child thread's context writes don't leak to main thread."""
        backend = _make_mock_backend()
        tracker = ExecutionTracker(backend=backend)

        tracker.context.workflow_id = "main-wf"

        def child():
            tracker.context.workflow_id = "child-wf"

        t = threading.Thread(target=child)
        t.start()
        t.join()

        assert tracker.context.workflow_id == "main-wf"

    def test_10_concurrent_threads_isolated(self):
        """10 concurrent threads each get their own context."""
        backend = _make_mock_backend()
        tracker = ExecutionTracker(backend=backend)

        results = {}
        barrier = threading.Barrier(10)

        def worker(idx):
            barrier.wait()
            tracker.context.workflow_id = f"wf-{idx}"
            tracker.context.stage_id = f"st-{idx}"
            # Small delay to increase chance of interleaving
            threading.Event().wait(0.005)
            results[idx] = (tracker.context.workflow_id, tracker.context.stage_id)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for i in range(10):
            assert results[i] == (f"wf-{i}", f"st-{i}"), f"Thread {i} context was corrupted"

    def test_context_setter_works(self):
        """Setting tracker.context to a new ExecutionContext works."""
        backend = _make_mock_backend()
        tracker = ExecutionTracker(backend=backend)

        new_ctx = ExecutionContext(workflow_id="test-wf", stage_id="test-st")
        tracker.context = new_ctx

        assert tracker.context.workflow_id == "test-wf"
        assert tracker.context.stage_id == "test-st"


class TestSessionStackIsolation:
    """Verify _session_stack is isolated per-thread."""

    def test_session_stacks_isolated_between_threads(self):
        """Two threads have independent session stacks."""
        backend = _make_mock_backend()
        tracker = ExecutionTracker(backend=backend)

        thread_stacks = {}
        barrier = threading.Barrier(2)

        def push_sessions(thread_name, count):
            barrier.wait()
            for i in range(count):
                tracker._session_stack.append(f"{thread_name}-session-{i}")
            thread_stacks[thread_name] = list(tracker._session_stack)

        t1 = threading.Thread(target=push_sessions, args=("t1", 3))
        t2 = threading.Thread(target=push_sessions, args=("t2", 2))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(thread_stacks["t1"]) == 3
        assert len(thread_stacks["t2"]) == 2
        assert all("t1" in s for s in thread_stacks["t1"])
        assert all("t2" in s for s in thread_stacks["t2"])

    def test_main_thread_stack_unaffected_by_child(self):
        """Child thread's session stack doesn't affect main thread."""
        backend = _make_mock_backend()
        tracker = ExecutionTracker(backend=backend)

        tracker._session_stack.append("main-session")

        def child():
            tracker._session_stack.append("child-session")
            assert len(tracker._session_stack) == 1

        t = threading.Thread(target=child)
        t.start()
        t.join()

        assert len(tracker._session_stack) == 1
        assert tracker._session_stack[0] == "main-session"


class TestSQLBackendSessionRemoved:
    """Verify SQLObservabilityBackend no longer uses session stack/standalone (C-02)."""

    def test_backend_no_session_stack(self):
        """SQL backend should not have _session_stack after C-02 refactor."""
        from temper_ai.observability.backends.sql_backend import SQLObservabilityBackend

        backend = SQLObservabilityBackend(buffer=False)
        assert not hasattr(backend, "_session_stack")
        assert not hasattr(backend, "_standalone_session")
        assert not hasattr(backend, "_local")


class TestConcurrentWorkflowTracking:
    """Integration test: concurrent workflows don't cross-contaminate."""

    def test_concurrent_workflow_context_isolation(self):
        """Multiple concurrent workflows maintain isolated contexts."""
        backend = _make_mock_backend()
        tracker = ExecutionTracker(backend=backend)

        errors = []
        barrier = threading.Barrier(5)

        def run_workflow(idx):
            try:
                barrier.wait()
                # Simulate entering a workflow context
                tracker.context.workflow_id = f"wf-{idx}"
                tracker.context.stage_id = f"st-{idx}"
                tracker.context.agent_id = f"ag-{idx}"

                # Simulate some work
                threading.Event().wait(0.01)

                # Verify context hasn't been corrupted
                assert tracker.context.workflow_id == f"wf-{idx}", \
                    f"Thread {idx}: workflow_id was {tracker.context.workflow_id}"
                assert tracker.context.stage_id == f"st-{idx}", \
                    f"Thread {idx}: stage_id was {tracker.context.stage_id}"
                assert tracker.context.agent_id == f"ag-{idx}", \
                    f"Thread {idx}: agent_id was {tracker.context.agent_id}"

                # Clean up
                tracker.context.workflow_id = None
                tracker.context.stage_id = None
                tracker.context.agent_id = None
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=run_workflow, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Context isolation errors: {errors}"
