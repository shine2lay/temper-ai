"""Tests for ConvergenceDetector."""

import pytest

from src.learning.convergence import ConvergenceDetector
from src.learning.models import MiningRun
from src.learning.store import LearningStore

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture()
def store() -> LearningStore:
    return LearningStore(database_url=MEMORY_DB)


def _add_runs(store: LearningStore, novelty_scores: list) -> None:
    for i, score in enumerate(novelty_scores):
        store.save_mining_run(MiningRun(id=f"r{i}", novelty_score=score))


class TestConvergenceDetector:
    def test_not_converged_high_novelty(self, store: LearningStore) -> None:
        _add_runs(store, [0.8, 0.7, 0.9])
        detector = ConvergenceDetector(store)
        assert not detector.is_converged()

    def test_converged_low_novelty(self, store: LearningStore) -> None:
        _add_runs(store, [0.05, 0.03, 0.02])
        detector = ConvergenceDetector(store)
        assert detector.is_converged()

    def test_insufficient_data(self, store: LearningStore) -> None:
        _add_runs(store, [0.01])
        detector = ConvergenceDetector(store)
        assert not detector.is_converged()

    def test_get_trend_empty(self, store: LearningStore) -> None:
        detector = ConvergenceDetector(store)
        trend = detector.get_trend()
        assert trend["data_points"] == 0
        assert trend["scores"] == []

    def test_get_trend_with_data(self, store: LearningStore) -> None:
        _add_runs(store, [0.5, 0.3])
        detector = ConvergenceDetector(store)
        trend = detector.get_trend()
        assert trend["data_points"] == 2
        assert trend["moving_average"] == 0.4
