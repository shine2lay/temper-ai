"""Tests for MiningOrchestrator."""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.learning.models import (
    PATTERN_AGENT_PERFORMANCE,
    STATUS_COMPLETED,
    LearnedPattern,
)
from temper_ai.learning.orchestrator import MiningOrchestrator, _calc_novelty, _pattern_key
from temper_ai.learning.store import LearningStore

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture()
def store() -> LearningStore:
    return LearningStore(database_url=MEMORY_DB)


def _make_pattern(title: str = "Test") -> LearnedPattern:
    return LearnedPattern(
        id="p1",
        pattern_type=PATTERN_AGENT_PERFORMANCE,
        title=title,
        description="desc",
        evidence={},
        confidence=0.8,
        impact_score=0.5,
    )


class TestOrchestrator:
    def test_run_mining_with_mock_miners(self, store: LearningStore) -> None:
        mock_miner = MagicMock()
        mock_miner.pattern_type = PATTERN_AGENT_PERFORMANCE
        mock_miner.mine.return_value = [_make_pattern("Slow agent")]

        orch = MiningOrchestrator(store=store, miners=[mock_miner])
        run = orch.run_mining()

        assert run.status == STATUS_COMPLETED
        assert run.patterns_found == 1
        assert run.patterns_new == 1
        mock_miner.mine.assert_called_once()

    def test_deduplication(self, store: LearningStore) -> None:
        # Pre-save a pattern
        store.save_pattern(_make_pattern("Slow agent"))

        mock_miner = MagicMock()
        mock_miner.pattern_type = PATTERN_AGENT_PERFORMANCE
        mock_miner.mine.return_value = [_make_pattern("Slow agent")]

        orch = MiningOrchestrator(store=store, miners=[mock_miner])
        run = orch.run_mining()

        assert run.patterns_found == 1
        assert run.patterns_new == 0  # deduped

    def test_miner_failure_handled(self, store: LearningStore) -> None:
        bad_miner = MagicMock()
        bad_miner.pattern_type = "bad"
        bad_miner.mine.side_effect = RuntimeError("boom")

        orch = MiningOrchestrator(store=store, miners=[bad_miner])
        run = orch.run_mining()

        assert run.status == STATUS_COMPLETED
        assert run.patterns_found == 0
        assert "error" in str(run.miner_stats.get("bad", ""))

    def test_memory_publish(self, store: LearningStore) -> None:
        mock_memory = MagicMock()

        mock_miner = MagicMock()
        mock_miner.pattern_type = PATTERN_AGENT_PERFORMANCE
        mock_miner.mine.return_value = [_make_pattern("New pattern")]

        orch = MiningOrchestrator(store=store, miners=[mock_miner], memory_service=mock_memory)
        orch.run_mining()

        mock_memory.store.assert_called_once()

    def test_novelty_score(self, store: LearningStore) -> None:
        mock_miner = MagicMock()
        mock_miner.pattern_type = PATTERN_AGENT_PERFORMANCE
        mock_miner.mine.return_value = [
            _make_pattern("P1"),
            _make_pattern("P2"),
        ]

        orch = MiningOrchestrator(store=store, miners=[mock_miner])
        run = orch.run_mining()
        # Both are new, so novelty = 2/2 = 1.0
        assert run.novelty_score == 1.0


class TestHelpers:
    def test_pattern_key_deterministic(self) -> None:
        p = _make_pattern("Hello")
        assert _pattern_key(p) == _pattern_key(p)

    def test_calc_novelty_zero_total(self) -> None:
        assert _calc_novelty(0, 0) == 0.0

    def test_calc_novelty_all_new(self) -> None:
        assert _calc_novelty(10, 10) == 1.0  # noqa

    def test_calc_novelty_half(self) -> None:
        assert _calc_novelty(10, 5) == 0.5  # noqa
