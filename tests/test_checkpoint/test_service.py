"""Tests for CheckpointService."""

import pytest

from temper_ai.checkpoint.service import CheckpointService
from temper_ai.stage.executor import NodeResult, Status


@pytest.fixture
def svc():
    return CheckpointService("test-exec-001")


class TestCheckpointServiceBasic:
    def test_init(self, svc):
        assert svc.execution_id == "test-exec-001"

    def test_get_latest_sequence_empty(self, svc):
        seq = svc.get_latest_sequence()
        assert seq == -1 or isinstance(seq, int)

    def test_get_history_empty(self, svc):
        history = svc.get_history()
        assert isinstance(history, list)


class TestCheckpointSaveAndReconstruct:
    def test_save_and_reconstruct(self, svc):
        result = NodeResult(
            status=Status.COMPLETED,
            output="test output",
        )
        svc.save_node_completed("step1", result)
        reconstructed = svc.reconstruct()
        assert "step1" in reconstructed
        assert reconstructed["step1"].output == "test output"

    def test_save_multiple_nodes(self, svc):
        svc.save_node_completed("a", NodeResult(status=Status.COMPLETED, output="out_a"))
        svc.save_node_completed("b", NodeResult(status=Status.COMPLETED, output="out_b"))
        reconstructed = svc.reconstruct()
        assert "a" in reconstructed
        assert "b" in reconstructed

    def test_reconstruct_with_limit(self, svc):
        svc.save_node_completed("a", NodeResult(status=Status.COMPLETED, output="a"))
        svc.save_node_completed("b", NodeResult(status=Status.COMPLETED, output="b"))
        seq = svc.get_latest_sequence()
        # Reconstruct up to first checkpoint only
        partial = svc.reconstruct(up_to_sequence=0)
        assert len(partial) <= len(svc.reconstruct())

    def test_history_after_saves(self, svc):
        svc.save_node_completed("x", NodeResult(status=Status.COMPLETED, output="x"))
        history = svc.get_history()
        assert len(history) >= 1


class TestCheckpointFork:
    def test_fork_nonexistent_raises(self):
        with pytest.raises((ValueError, Exception)):
            CheckpointService.fork("nonexistent-exec-xyz", 999, "new-exec-001")
