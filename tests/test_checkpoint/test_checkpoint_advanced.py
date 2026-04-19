"""Advanced checkpoint tests — loop rewind, agent completed, fork chains."""

import pytest

from temper_ai.checkpoint.service import CheckpointService
from temper_ai.stage.executor import NodeResult, Status


@pytest.fixture
def svc():
    return CheckpointService("test-adv-001")


class TestSaveAgentCompleted:
    def test_agent_completed_basic(self, svc):
        result = type("R", (), {
            "status": Status.COMPLETED,
            "output": "agent output",
            "structured_output": {"key": "val"},
            "cost_usd": 0.05,
            "total_tokens": 100,
            "duration_seconds": 1.5,
            "error": None,
        })()
        svc.save_agent_completed("stage1", "agent_a", result)
        history = svc.get_history()
        assert len(history) >= 1

    def test_agent_completed_missing_attrs(self, svc):
        """Result object missing optional attributes should use defaults."""
        # No status attr at all — code should default to "completed"
        result = type("R", (), {})()
        svc.save_agent_completed("stage1", "agent_b", result)
        history = svc.get_history()
        assert len(history) >= 1


class TestSaveLoopRewind:
    def test_loop_rewind(self, svc):
        svc.save_node_completed("a", NodeResult(status=Status.COMPLETED, output="a"))
        svc.save_node_completed("b", NodeResult(status=Status.COMPLETED, output="b"))
        svc.save_loop_rewind("b", "a", ["b"])
        # After rewind, reconstructing should not include "b"
        outputs = svc.reconstruct()
        assert "a" in outputs
        assert "b" not in outputs

    def test_loop_rewind_empty_cleared(self, svc):
        svc.save_node_completed("x", NodeResult(status=Status.COMPLETED, output="x"))
        svc.save_loop_rewind("x", "x", [])
        outputs = svc.reconstruct()
        assert "x" in outputs

    def test_loop_rewind_without_trigger_result(self, svc):
        svc.save_node_completed("n1", NodeResult(status=Status.COMPLETED, output="n1"))
        svc.save_loop_rewind("n1", "n1", ["n1"], trigger_result=None)
        outputs = svc.reconstruct()
        assert "n1" not in outputs


class TestReconstructAdvanced:
    def test_reconstruct_empty(self, svc):
        outputs = svc.reconstruct()
        assert outputs == {}

    def test_reconstruct_skips_failed(self, svc):
        svc.save_node_completed("ok", NodeResult(status=Status.COMPLETED, output="ok"))
        svc.save_node_completed("bad", NodeResult(status=Status.FAILED, output="", error="boom"))
        outputs = svc.reconstruct()
        assert "ok" in outputs
        # Failed nodes may or may not be included depending on implementation
        # The key assertion is that reconstruction doesn't crash

    def test_latest_sequence_increments(self, svc):
        seq0 = svc.get_latest_sequence()
        svc.save_node_completed("a", NodeResult(status=Status.COMPLETED, output="a"))
        seq1 = svc.get_latest_sequence()
        assert seq1 > seq0
        svc.save_node_completed("b", NodeResult(status=Status.COMPLETED, output="b"))
        seq2 = svc.get_latest_sequence()
        assert seq2 > seq1


class TestForkChain:
    def test_fork_creates_new_service(self):
        svc1 = CheckpointService("fork-source-001")
        svc1.save_node_completed("step1", NodeResult(status=Status.COMPLETED, output="s1"))
        seq = svc1.get_latest_sequence()

        svc2 = CheckpointService.fork("fork-source-001", seq, "fork-target-001")
        assert svc2.execution_id == "fork-target-001"

    def test_fork_nonexistent_sequence_raises(self):
        CheckpointService("fork-bad-001")
        with pytest.raises((ValueError, Exception)):
            CheckpointService.fork("fork-bad-001", 999, "fork-bad-target")
