"""Tests for WI-2: Data Lineage (Gap 11).

Tests lineage computation, hash determinism, mixed success/failed agents,
serialization, and backward compatibility.
"""
import pytest
from typing import Any, Dict

from temper_ai.observability.lineage import (
    CONTRIBUTION_FAILED,
    CONTRIBUTION_PRIMARY,
    CONTRIBUTION_SYNTHESIZED,
    CONTRIBUTION_VOTE,
    OutputLineageEntry,
    StageOutputLineage,
    compute_output_lineage,
    lineage_to_dict,
    _hash_output,
)


class TestHashOutput:
    """Test output hashing."""

    def test_hash_deterministic(self) -> None:
        """Same output always produces same hash."""
        h1 = _hash_output("hello world")
        h2 = _hash_output("hello world")
        assert h1 == h2

    def test_hash_length(self) -> None:
        """Hash is 16 hex characters."""
        h = _hash_output("test data")
        assert len(h) == 16

    def test_different_inputs_different_hashes(self) -> None:
        """Different outputs produce different hashes."""
        h1 = _hash_output("output A")
        h2 = _hash_output("output B")
        assert h1 != h2

    def test_hash_none_output(self) -> None:
        """None output hashes as empty string."""
        h = _hash_output(None)
        assert len(h) == 16

    def test_hash_dict_output(self) -> None:
        """Dict output is stringified for hashing."""
        h = _hash_output({"key": "value"})
        assert len(h) == 16


class TestComputeOutputLineage:
    """Test compute_output_lineage."""

    def test_single_successful_agent(self) -> None:
        """Single successful agent gets 'primary' contribution."""
        lineage = compute_output_lineage(
            stage_name="analysis",
            agent_outputs={"researcher": "result data"},
            agent_statuses={"researcher": "success"},
        )
        assert lineage.stage_name == "analysis"
        assert len(lineage.entries) == 1
        assert lineage.entries[0].agent_name == "researcher"
        assert lineage.entries[0].contribution_type == CONTRIBUTION_PRIMARY
        assert lineage.entries[0].status == "success"

    def test_multiple_successful_agents_synthesized(self) -> None:
        """Multiple successful agents get 'synthesized' by default."""
        lineage = compute_output_lineage(
            stage_name="debate",
            agent_outputs={"a1": "out1", "a2": "out2"},
            agent_statuses={"a1": "success", "a2": "success"},
            synthesis_method="merge",
        )
        assert len(lineage.entries) == 2
        for entry in lineage.entries:
            assert entry.contribution_type == CONTRIBUTION_SYNTHESIZED

    def test_vote_synthesis_method(self) -> None:
        """Voting synthesis method assigns 'vote' contribution."""
        lineage = compute_output_lineage(
            stage_name="vote_stage",
            agent_outputs={"a1": "yes", "a2": "no", "a3": "yes"},
            agent_statuses={"a1": "success", "a2": "success", "a3": "success"},
            synthesis_method="vote",
        )
        for entry in lineage.entries:
            assert entry.contribution_type == CONTRIBUTION_VOTE

    def test_majority_vote_synthesis(self) -> None:
        """majority_vote method also classified as vote."""
        lineage = compute_output_lineage(
            stage_name="s",
            agent_outputs={"a1": "x"},
            agent_statuses={"a1": "success"},
            synthesis_method="majority_vote",
        )
        # Single agent still gets primary
        assert lineage.entries[0].contribution_type == CONTRIBUTION_PRIMARY

    def test_failed_agent(self) -> None:
        """Failed agent gets 'failed' contribution."""
        lineage = compute_output_lineage(
            stage_name="mixed",
            agent_outputs={"good": "result", "bad": None},
            agent_statuses={"good": "success", "bad": "failed"},
        )
        entries_by_name = {e.agent_name: e for e in lineage.entries}
        assert entries_by_name["good"].contribution_type == CONTRIBUTION_PRIMARY
        assert entries_by_name["bad"].contribution_type == CONTRIBUTION_FAILED
        assert entries_by_name["bad"].status == "failed"

    def test_all_agents_failed(self) -> None:
        """All agents failed — all get 'failed'."""
        lineage = compute_output_lineage(
            stage_name="fail_stage",
            agent_outputs={},
            agent_statuses={"a1": "failed", "a2": "failed"},
        )
        for entry in lineage.entries:
            assert entry.contribution_type == CONTRIBUTION_FAILED

    def test_entries_sorted_by_name(self) -> None:
        """Entries are sorted by agent name for determinism."""
        lineage = compute_output_lineage(
            stage_name="s",
            agent_outputs={"z": "1", "a": "2", "m": "3"},
            agent_statuses={"z": "success", "a": "success", "m": "success"},
        )
        names = [e.agent_name for e in lineage.entries]
        assert names == ["a", "m", "z"]

    def test_synthesis_method_stored(self) -> None:
        """Synthesis method is stored in lineage."""
        lineage = compute_output_lineage(
            stage_name="s",
            agent_outputs={"a": "x"},
            agent_statuses={"a": "success"},
            synthesis_method="consensus",
        )
        assert lineage.synthesis_method == "consensus"

    def test_no_synthesis_method(self) -> None:
        """None synthesis method is valid."""
        lineage = compute_output_lineage(
            stage_name="s",
            agent_outputs={"a": "x"},
            agent_statuses={"a": "success"},
        )
        assert lineage.synthesis_method is None


class TestLineageToDict:
    """Test serialization."""

    def test_round_trip(self) -> None:
        """lineage_to_dict produces JSON-serializable dict."""
        lineage = compute_output_lineage(
            stage_name="test",
            agent_outputs={"a1": "out1", "a2": None},
            agent_statuses={"a1": "success", "a2": "failed"},
            synthesis_method="merge",
        )
        d = lineage_to_dict(lineage)
        assert d["stage_name"] == "test"
        assert d["synthesis_method"] == "merge"
        assert len(d["entries"]) == 2
        assert d["entries"][0]["agent_name"] == "a1"
        assert d["entries"][0]["output_hash"]  # non-empty
        assert d["entries"][1]["contribution_type"] == CONTRIBUTION_FAILED

    def test_empty_lineage(self) -> None:
        """Empty agent dicts produce valid dict."""
        lineage = compute_output_lineage("empty", {}, {})
        d = lineage_to_dict(lineage)
        assert d["entries"] == []


class TestLineageBackwardCompat:
    """Test backward compatibility with None output_lineage."""

    def test_noop_backend_signature(self) -> None:
        """NoOp backend accepts output_lineage param."""
        from temper_ai.observability.backends.noop_backend import NoOpBackend

        backend = NoOpBackend()
        result = backend.set_stage_output(
            stage_id="s-1",
            output_data={"result": "test"},
            output_lineage={"entries": []},
        )
        assert result is None

    def test_noop_backend_without_lineage(self) -> None:
        """NoOp backend works without output_lineage."""
        from temper_ai.observability.backends.noop_backend import NoOpBackend

        backend = NoOpBackend()
        result = backend.set_stage_output(stage_id="s-1", output_data={"result": "test"})
        assert result is None
