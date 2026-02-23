"""Tests for GoalProposer."""

from unittest.mock import MagicMock

import pytest

from temper_ai.goals._schemas import (
    EffortLevel,
    GoalProposal,
    GoalRiskLevel,
    GoalType,
    ImpactEstimate,
    RiskAssessment,
)
from temper_ai.goals.models import GoalProposalRecord
from temper_ai.goals.proposer import GoalProposer, _dedup_key
from temper_ai.goals.store import GoalStore

MEMORY_DB = "sqlite:///:memory:"


def _make_proposal(title="Test Proposal", goal_type=GoalType.COST_REDUCTION):
    return GoalProposal(
        goal_type=goal_type,
        title=title,
        description="Test description",
        effort_estimate=EffortLevel.SMALL,
        risk_assessment=RiskAssessment(level=GoalRiskLevel.LOW),
        expected_impacts=[
            ImpactEstimate(
                metric_name="cost",
                current_value=10.0,
                expected_value=5.0,
                improvement_pct=50.0,
                confidence=0.8,
            )
        ],
        proposed_actions=["Do something"],
    )


@pytest.fixture
def store():
    return GoalStore(database_url=MEMORY_DB)


class TestGoalProposer:
    def test_generate_with_no_analyzers(self, store):
        proposer = GoalProposer(store=store)
        results = proposer.generate_proposals()
        assert results == []

    def test_generate_with_analyzer(self, store):
        analyzer = MagicMock()
        analyzer.analyzer_type = "test"
        analyzer.analyze.return_value = [_make_proposal()]
        proposer = GoalProposer(store=store, analyzers=[analyzer])
        results = proposer.generate_proposals()
        assert len(results) == 1
        assert results[0].goal_type == "cost_reduction"
        assert results[0].priority_score > 0

    def test_deduplication(self, store):
        # Pre-populate store with existing active proposal
        existing = GoalProposalRecord(
            id="gp-existing",
            goal_type="cost_reduction",
            title="Test Proposal",
            description="Existing",
            status="proposed",
        )
        store.save_proposal(existing)
        analyzer = MagicMock()
        analyzer.analyzer_type = "test"
        analyzer.analyze.return_value = [_make_proposal("Test Proposal")]
        proposer = GoalProposer(store=store, analyzers=[analyzer])
        results = proposer.generate_proposals()
        assert len(results) == 0  # Deduplicated

    def test_dedup_allows_different_titles(self, store):
        analyzer = MagicMock()
        analyzer.analyzer_type = "test"
        analyzer.analyze.return_value = [
            _make_proposal("Proposal A"),
            _make_proposal("Proposal B"),
        ]
        proposer = GoalProposer(store=store, analyzers=[analyzer])
        results = proposer.generate_proposals()
        assert len(results) == 2

    def test_scoring(self, store):
        proposer = GoalProposer(store=store)
        proposal = _make_proposal()
        score = proposer._score_proposal(proposal)
        assert 0 <= score <= 1

    def test_scoring_high_impact(self, store):
        proposer = GoalProposer(store=store)
        high = _make_proposal()
        high.expected_impacts[0].improvement_pct = 90.0
        high.expected_impacts[0].confidence = 0.9
        low = _make_proposal()
        low.expected_impacts[0].improvement_pct = 5.0
        low.expected_impacts[0].confidence = 0.3
        assert proposer._score_proposal(high) > proposer._score_proposal(low)

    def test_analyzer_failure_caught(self, store):
        good = MagicMock()
        good.analyzer_type = "good"
        good.analyze.return_value = [_make_proposal()]
        bad = MagicMock()
        bad.analyzer_type = "bad"
        bad.analyze.side_effect = RuntimeError("boom")
        proposer = GoalProposer(store=store, analyzers=[bad, good])
        results = proposer.generate_proposals()
        assert len(results) == 1  # Good analyzer's result still persisted

    def test_to_record(self, store):
        proposer = GoalProposer(store=store)
        proposal = _make_proposal()
        proposal.priority_score = 0.5
        record = proposer._to_record(proposal)
        assert record.id.startswith("gp-")
        assert record.goal_type == "cost_reduction"
        assert record.priority_score == 0.5

    def test_enrich_with_patterns_no_store(self, store):
        proposer = GoalProposer(store=store, learning_store=None)
        proposal = _make_proposal()
        proposer._enrich_with_patterns(proposal)
        assert proposal.evidence.pattern_ids == []

    def test_batch_dedup_within_batch(self, store):
        analyzer = MagicMock()
        analyzer.analyzer_type = "test"
        analyzer.analyze.return_value = [
            _make_proposal("Same Title"),
            _make_proposal("Same Title"),
        ]
        proposer = GoalProposer(store=store, analyzers=[analyzer])
        results = proposer.generate_proposals()
        assert len(results) == 1

    def test_persisted_to_store(self, store):
        analyzer = MagicMock()
        analyzer.analyzer_type = "test"
        analyzer.analyze.return_value = [_make_proposal()]
        proposer = GoalProposer(store=store, analyzers=[analyzer])
        proposer.generate_proposals()
        all_proposals = store.list_proposals()
        assert len(all_proposals) == 1


class TestDedupKey:
    def test_deterministic(self):
        k1 = _dedup_key("cost_reduction", "Reduce costs")
        k2 = _dedup_key("cost_reduction", "Reduce costs")
        assert k1 == k2

    def test_different_for_different_inputs(self):
        k1 = _dedup_key("cost_reduction", "A")
        k2 = _dedup_key("cost_reduction", "B")
        assert k1 != k2
