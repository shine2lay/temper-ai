"""Tests for RunStore persistent run history."""

from datetime import UTC, datetime

import pytest

from temper_ai.interfaces.server.models import ServerRun
from temper_ai.interfaces.server.run_store import RunStore


def _make_run(
    execution_id: str = "exec-001",
    status: str = "pending",
    workflow_name: str = "test-wf",
) -> ServerRun:
    """Create a ServerRun for testing."""
    return ServerRun(
        execution_id=execution_id,
        workflow_path="workflows/test.yaml",
        workflow_name=workflow_name,
        status=status,
        created_at=datetime.now(UTC),
    )


class TestServerRunModel:
    """Test ServerRun model."""

    def test_fields(self) -> None:
        run = _make_run()
        assert run.execution_id == "exec-001"
        assert run.status == "pending"
        assert run.workflow_name == "test-wf"
        assert run.error_message is None
        assert run.result_summary is None

    def test_to_dict(self) -> None:
        run = _make_run()
        d = run.to_dict()
        assert d["execution_id"] == "exec-001"
        assert d["status"] == "pending"
        assert "created_at" in d


class TestRunStore:
    """Test RunStore CRUD operations."""

    @pytest.fixture
    def store(self) -> RunStore:
        """In-memory RunStore."""
        return RunStore(database_url="sqlite:///:memory:")

    def test_save_and_get(self, store: RunStore) -> None:
        run = _make_run()
        store.save_run(run)
        retrieved = store.get_run("exec-001")
        assert retrieved is not None
        assert retrieved.execution_id == "exec-001"
        assert retrieved.workflow_name == "test-wf"

    def test_get_nonexistent(self, store: RunStore) -> None:
        assert store.get_run("nonexistent") is None

    def test_list_empty(self, store: RunStore) -> None:
        runs = store.list_runs()
        assert runs == []

    def test_list_with_status_filter(self, store: RunStore) -> None:
        store.save_run(_make_run("exec-1", "completed"))
        store.save_run(_make_run("exec-2", "failed"))
        store.save_run(_make_run("exec-3", "completed"))

        completed = store.list_runs(status="completed")
        assert len(completed) == 2
        assert all(r.status == "completed" for r in completed)

        failed = store.list_runs(status="failed")
        assert len(failed) == 1

    def test_list_ordering(self, store: RunStore) -> None:
        """Runs are returned newest-first."""
        store.save_run(_make_run("exec-1", "completed"))
        store.save_run(_make_run("exec-2", "completed"))
        runs = store.list_runs()
        assert len(runs) == 2
        # Most recently inserted should be first (newest-first ordering)
        assert runs[0].execution_id == "exec-2"
        assert runs[1].execution_id == "exec-1"

    def test_update_status(self, store: RunStore) -> None:
        store.save_run(_make_run("exec-1", "pending"))
        updated = store.update_status(
            "exec-1",
            "completed",
            completed_at=datetime.now(UTC),
            workflow_id="wf-abc",
        )
        assert updated is True

        run = store.get_run("exec-1")
        assert run is not None
        assert run.status == "completed"
        assert run.workflow_id == "wf-abc"

    def test_update_nonexistent(self, store: RunStore) -> None:
        assert store.update_status("nope", "failed") is False

    def test_limit_offset(self, store: RunStore) -> None:
        for i in range(5):
            store.save_run(_make_run(f"exec-{i}", "completed"))

        page1 = store.list_runs(limit=2, offset=0)
        assert len(page1) == 2

        page2 = store.list_runs(limit=2, offset=2)
        assert len(page2) == 2

        page3 = store.list_runs(limit=2, offset=4)
        assert len(page3) == 1

    def test_save_with_input_data(self, store: RunStore) -> None:
        run = _make_run()
        run.input_data = {"topic": "AI safety"}
        store.save_run(run)

        retrieved = store.get_run("exec-001")
        assert retrieved is not None
        assert retrieved.input_data == {"topic": "AI safety"}

    def test_save_with_result_summary(self, store: RunStore) -> None:
        run = _make_run()
        run.result_summary = {"output": "analysis complete"}
        store.save_run(run)

        retrieved = store.get_run("exec-001")
        assert retrieved is not None
        assert retrieved.result_summary == {"output": "analysis complete"}
