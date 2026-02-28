"""Tests for _dialogue_helpers module.

Covers all helper functions extracted from DialogueOrchestrator:
- _count_weighted_votes
- _calculate_merit_confidence
- _detect_merit_conflicts
- _build_merit_metadata
- get_merit_weights
- build_merit_weighted_reasoning
- merit_weighted_synthesis
- curate_recent
- curate_relevant
- calculate_exact_match_convergence
"""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.agent.strategies._dialogue_helpers import (
    _build_merit_metadata,
    _calculate_merit_confidence,
    _count_weighted_votes,
    _detect_merit_conflicts,
    build_merit_weighted_reasoning,
    calculate_exact_match_convergence,
    curate_recent,
    curate_relevant,
    get_merit_weights,
    merit_weighted_synthesis,
)
from temper_ai.agent.strategies.base import AgentOutput, Conflict, SynthesisResult
from temper_ai.shared.constants.probabilities import PROB_MEDIUM


def _ao(name, decision, confidence=0.8, reasoning="reason"):
    """Create an AgentOutput for testing."""
    return AgentOutput(
        agent_name=name,
        decision=decision,
        reasoning=reasoning,
        confidence=confidence,
        metadata={},
    )


def _hist(round_num, agent, reasoning="reason"):
    """Create a dialogue history entry for testing."""
    return {"round": round_num, "agent": agent, "reasoning": reasoning}


# ---------------------------------------------------------------------------
# _count_weighted_votes
# ---------------------------------------------------------------------------


class TestCountWeightedVotes:
    def test_single_agent_vote(self):
        """Vote weight = merit_weight * confidence."""
        outputs = [_ao("a", "yes", confidence=0.5)]
        weights = {"a": 2.0}
        result = _count_weighted_votes(outputs, weights)
        assert result == {"yes": pytest.approx(1.0)}

    def test_two_agents_same_decision_accumulate(self):
        """Votes for same decision accumulate."""
        outputs = [_ao("a", "yes", confidence=1.0), _ao("b", "yes", confidence=1.0)]
        weights = {"a": 1.0, "b": 1.0}
        result = _count_weighted_votes(outputs, weights)
        assert result == {"yes": pytest.approx(2.0)}

    def test_two_agents_different_decisions(self):
        """Different decisions produce separate tallies."""
        outputs = [_ao("a", "yes", confidence=1.0), _ao("b", "no", confidence=1.0)]
        weights = {"a": 1.0, "b": 1.0}
        result = _count_weighted_votes(outputs, weights)
        assert result["yes"] == pytest.approx(1.0)
        assert result["no"] == pytest.approx(1.0)

    def test_missing_agent_in_weights_defaults_to_1(self):
        """Agent absent from weights dict defaults weight to 1.0."""
        outputs = [_ao("unknown", "yes", confidence=0.6)]
        result = _count_weighted_votes(outputs, {})
        assert result == {"yes": pytest.approx(0.6)}


# ---------------------------------------------------------------------------
# _calculate_merit_confidence
# ---------------------------------------------------------------------------


class TestCalculateMeritConfidence:
    def test_no_supporters_returns_prob_medium(self):
        """No agents support winning decision → returns PROB_MEDIUM fallback."""
        outputs = [_ao("a", "no")]
        result = _calculate_merit_confidence(outputs, "yes", 1.0, {"a": 1.0})
        assert result == PROB_MEDIUM

    def test_single_supporter_formula(self):
        """confidence = decision_support * agent_confidence (single supporter, weight=1)."""
        outputs = [_ao("a", "yes", confidence=0.8)]
        result = _calculate_merit_confidence(outputs, "yes", 0.9, {"a": 1.0})
        # weighted_conf = 0.8*1.0 = 0.8, weight_sum = 1.0, avg = 0.8
        # result = 0.9 * 0.8 = 0.72
        assert result == pytest.approx(0.72)

    def test_multiple_supporters_weighted_average(self):
        """Weighted average confidence from multiple supporters."""
        outputs = [
            _ao("a", "yes", confidence=1.0),
            _ao("b", "yes", confidence=0.5),
            _ao("c", "no", confidence=0.9),
        ]
        weights = {"a": 2.0, "b": 1.0, "c": 1.0}
        decision_support = 0.75
        result = _calculate_merit_confidence(outputs, "yes", decision_support, weights)
        # supporters: a (conf=1.0, w=2.0), b (conf=0.5, w=1.0)
        # weighted_conf = 1.0*2.0 + 0.5*1.0 = 2.5
        # weight_sum = 2.0 + 1.0 = 3.0
        # avg_conf = 2.5/3.0
        # result = 0.75 * (2.5/3.0)
        expected = 0.75 * (2.5 / 3.0)
        assert result == pytest.approx(expected)

    def test_decision_support_scales_confidence(self):
        """Higher decision_support produces higher confidence."""
        outputs = [_ao("a", "yes", confidence=1.0)]
        low = _calculate_merit_confidence(outputs, "yes", 0.5, {"a": 1.0})
        high = _calculate_merit_confidence(outputs, "yes", 1.0, {"a": 1.0})
        assert high > low


# ---------------------------------------------------------------------------
# _detect_merit_conflicts
# ---------------------------------------------------------------------------


class TestDetectMeritConflicts:
    def test_single_decision_no_conflict(self):
        """No conflict when all agents agree."""
        outputs = [_ao("a", "yes"), _ao("b", "yes")]
        weighted_votes = {"yes": 2.0}
        result = _detect_merit_conflicts(outputs, "yes", 1.0, weighted_votes)
        assert result == []

    def test_multiple_decisions_produces_conflict(self):
        """Two decisions → one Conflict object returned."""
        outputs = [_ao("a", "yes"), _ao("b", "no")]
        weighted_votes = {"yes": 1.0, "no": 1.0}
        result = _detect_merit_conflicts(outputs, "yes", 0.5, weighted_votes)
        assert len(result) == 1
        assert isinstance(result[0], Conflict)

    def test_disagreement_score_is_one_minus_support(self):
        """Conflict disagreement_score = 1.0 - decision_support."""
        outputs = [_ao("a", "yes"), _ao("b", "no")]
        weighted_votes = {"yes": 3.0, "no": 1.0}
        decision_support = 0.75
        result = _detect_merit_conflicts(
            outputs, "yes", decision_support, weighted_votes
        )
        assert result[0].disagreement_score == pytest.approx(1.0 - decision_support)

    def test_conflict_context_includes_weighted_votes(self):
        """Conflict context contains the weighted_votes dict."""
        outputs = [_ao("a", "yes"), _ao("b", "no")]
        weighted_votes = {"yes": 2.0, "no": 1.0}
        result = _detect_merit_conflicts(outputs, "yes", 0.67, weighted_votes)
        assert "weighted_votes" in result[0].context
        assert result[0].context["weighted_votes"] == weighted_votes


# ---------------------------------------------------------------------------
# _build_merit_metadata
# ---------------------------------------------------------------------------


class TestBuildMeritMetadata:
    def test_all_required_keys_present(self):
        """Metadata has all expected keys."""
        outputs = [_ao("a", "yes"), _ao("b", "no")]
        metadata = _build_merit_metadata(
            outputs, "yes", 0.5, {"a": 1.0, "b": 1.0}, {"yes": 1.0, "no": 1.0}
        )
        for key in (
            "total_agents",
            "decision_support",
            "merit_weights",
            "weighted_votes",
            "supporters",
            "dissenters",
        ):
            assert key in metadata

    def test_supporters_only_include_winners(self):
        """Supporters list contains only agents that chose winning decision."""
        outputs = [_ao("a", "yes"), _ao("b", "yes"), _ao("c", "no")]
        metadata = _build_merit_metadata(
            outputs, "yes", 0.67, {"a": 1.0, "b": 1.0, "c": 1.0}, {}
        )
        assert set(metadata["supporters"]) == {"a", "b"}

    def test_dissenters_exclude_winners(self):
        """Dissenters list contains agents that chose different decisions."""
        outputs = [_ao("a", "yes"), _ao("b", "no"), _ao("c", "no")]
        metadata = _build_merit_metadata(
            outputs, "yes", 0.33, {"a": 1.0, "b": 1.0, "c": 1.0}, {}
        )
        assert set(metadata["dissenters"]) == {"b", "c"}

    def test_total_agents_count(self):
        """total_agents equals the number of agent outputs."""
        outputs = [_ao("a", "yes"), _ao("b", "no"), _ao("c", "yes")]
        metadata = _build_merit_metadata(outputs, "yes", 0.67, {}, {})
        assert metadata["total_agents"] == 3

    def test_decision_support_stored(self):
        """decision_support value is stored verbatim."""
        outputs = [_ao("a", "yes")]
        metadata = _build_merit_metadata(outputs, "yes", 0.9, {}, {})
        assert metadata["decision_support"] == 0.9


# ---------------------------------------------------------------------------
# get_merit_weights
# ---------------------------------------------------------------------------


class TestGetMeritWeights:
    def test_import_error_returns_equal_weights(self):
        """When sqlmodel is not available, returns 1.0 for each agent."""
        outputs = [_ao("a", "yes"), _ao("b", "no")]
        with patch.dict("sys.modules", {"sqlmodel": None}):
            result = get_merit_weights(outputs, None)
        assert result == {"a": 1.0, "b": 1.0}

    def test_no_backend_returns_equal_weights(self):
        """When tracker.backend is falsy, returns 1.0 for each agent."""
        outputs = [_ao("a", "yes")]
        mock_sqlmodel = MagicMock()
        mock_tracker = MagicMock()
        mock_tracker.backend = None
        mock_obs = MagicMock()
        mock_obs.ExecutionTracker.return_value = mock_tracker
        with patch.dict(
            "sys.modules",
            {"sqlmodel": mock_sqlmodel, "temper_ai.observability": mock_obs},
        ):
            result = get_merit_weights(outputs, None)
        assert result == {"a": 1.0}

    def test_expertise_score_used_when_available(self):
        """expertise_score is used as merit weight when present."""
        outputs = [_ao("agent1", "yes")]
        mock_sqlmodel = MagicMock()
        mock_merit = MagicMock()
        mock_merit.expertise_score = 0.85
        mock_merit.success_rate = 0.70

        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = mock_merit
        mock_backend = MagicMock()
        mock_backend.get_session_context.return_value.__enter__.return_value = (
            mock_session
        )
        mock_backend.get_session_context.return_value.__exit__.return_value = False
        mock_tracker = MagicMock()
        mock_tracker.backend = mock_backend

        mock_obs = MagicMock()
        mock_obs.ExecutionTracker.return_value = mock_tracker
        with patch.dict(
            "sys.modules",
            {"sqlmodel": mock_sqlmodel, "temper_ai.observability": mock_obs},
        ):
            result = get_merit_weights(outputs, "test_domain")
        assert result == {"agent1": pytest.approx(0.85)}

    def test_success_rate_used_when_no_expertise_score(self):
        """success_rate is used when expertise_score is None."""
        outputs = [_ao("agent1", "yes")]
        mock_sqlmodel = MagicMock()
        mock_merit = MagicMock()
        mock_merit.expertise_score = None
        mock_merit.success_rate = 0.70

        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = mock_merit
        mock_backend = MagicMock()
        mock_backend.get_session_context.return_value.__enter__.return_value = (
            mock_session
        )
        mock_backend.get_session_context.return_value.__exit__.return_value = False
        mock_tracker = MagicMock()
        mock_tracker.backend = mock_backend

        mock_obs = MagicMock()
        mock_obs.ExecutionTracker.return_value = mock_tracker
        with patch.dict(
            "sys.modules",
            {"sqlmodel": mock_sqlmodel, "temper_ai.observability": mock_obs},
        ):
            result = get_merit_weights(outputs, "test_domain")
        assert result == {"agent1": pytest.approx(0.70)}

    def test_no_merit_score_uses_prob_medium(self):
        """Agent with no DB record uses PROB_MEDIUM as neutral weight."""
        outputs = [_ao("agent1", "yes")]
        mock_sqlmodel = MagicMock()
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = None  # no record
        mock_backend = MagicMock()
        mock_backend.get_session_context.return_value.__enter__.return_value = (
            mock_session
        )
        mock_backend.get_session_context.return_value.__exit__.return_value = False
        mock_tracker = MagicMock()
        mock_tracker.backend = mock_backend

        mock_obs = MagicMock()
        mock_obs.ExecutionTracker.return_value = mock_tracker
        with patch.dict(
            "sys.modules",
            {"sqlmodel": mock_sqlmodel, "temper_ai.observability": mock_obs},
        ):
            result = get_merit_weights(outputs, None)
        assert result == {"agent1": pytest.approx(PROB_MEDIUM)}


# ---------------------------------------------------------------------------
# build_merit_weighted_reasoning
# ---------------------------------------------------------------------------


class TestBuildMeritWeightedReasoning:
    def test_contains_decision_and_support(self):
        """Reasoning string mentions the winning decision and support %."""
        outputs = [_ao("a", "yes")]
        result = build_merit_weighted_reasoning(
            "yes", 0.8, outputs, {"a": 1.0}, {"yes": 1.0}
        )
        assert "yes" in result
        assert "80.0%" in result

    def test_supporter_names_include_merit(self):
        """Supporter section lists agent names with merit value."""
        outputs = [_ao("alpha", "yes")]
        result = build_merit_weighted_reasoning(
            "yes", 1.0, outputs, {"alpha": 0.75}, {"yes": 1.0}
        )
        assert "alpha" in result
        assert "0.75" in result

    def test_multiple_decisions_include_vote_breakdown(self):
        """When multiple decisions exist, a vote breakdown section appears."""
        outputs = [_ao("a", "yes"), _ao("b", "no")]
        result = build_merit_weighted_reasoning(
            "yes", 0.6, outputs, {"a": 1.0, "b": 1.0}, {"yes": 0.8, "no": 0.4}
        )
        assert "breakdown" in result.lower() or "weighted vote" in result.lower()
        assert "no" in result

    def test_single_decision_no_breakdown_section(self):
        """Single decision → no 'Weighted vote breakdown' section."""
        outputs = [_ao("a", "yes"), _ao("b", "yes")]
        result = build_merit_weighted_reasoning(
            "yes", 1.0, outputs, {"a": 1.0, "b": 1.0}, {"yes": 2.0}
        )
        assert "breakdown" not in result.lower()


# ---------------------------------------------------------------------------
# merit_weighted_synthesis
# ---------------------------------------------------------------------------


class TestMeritWeightedSynthesis:
    def _synthesize(self, outputs, weights, domain=None):
        """Helper: run synthesis with mocked get_merit_weights."""
        with patch(
            "temper_ai.agent.strategies._dialogue_helpers.get_merit_weights",
            return_value=weights,
        ):
            return merit_weighted_synthesis(outputs, domain)

    def test_unanimous_decision_no_conflicts(self):
        """All agents agree → correct decision, empty conflicts list."""
        outputs = [_ao("a", "yes"), _ao("b", "yes"), _ao("c", "yes")]
        weights = {"a": 1.0, "b": 1.0, "c": 1.0}
        result = self._synthesize(outputs, weights)
        assert result.decision == "yes"
        assert result.conflicts == []

    def test_majority_wins(self):
        """Majority decision wins over minority."""
        outputs = [_ao("a", "yes"), _ao("b", "yes"), _ao("c", "no")]
        weights = {"a": 1.0, "b": 1.0, "c": 1.0}
        result = self._synthesize(outputs, weights)
        assert result.decision == "yes"

    def test_merit_weights_influence_outcome(self):
        """High-merit minority agent can override low-merit majority."""
        outputs = [
            _ao("expert", "no", confidence=1.0),
            _ao("novice1", "yes", confidence=0.5),
            _ao("novice2", "yes", confidence=0.5),
        ]
        # expert has weight=5.0, novices have weight=0.5 each
        # expert vote: 5.0 * 1.0 = 5.0
        # novice votes: 0.5*0.5 + 0.5*0.5 = 0.5
        weights = {"expert": 5.0, "novice1": 0.5, "novice2": 0.5}
        result = self._synthesize(outputs, weights)
        assert result.decision == "no"

    def test_method_is_merit_weighted(self):
        """Synthesis method field is 'merit_weighted'."""
        outputs = [_ao("a", "yes")]
        result = self._synthesize(outputs, {"a": 1.0})
        assert result.method == "merit_weighted"

    def test_vote_counts_match_agent_counts(self):
        """votes dict counts how many agents chose each decision."""
        outputs = [_ao("a", "yes"), _ao("b", "yes"), _ao("c", "no")]
        weights = {"a": 1.0, "b": 1.0, "c": 1.0}
        result = self._synthesize(outputs, weights)
        assert result.votes["yes"] == 2
        assert result.votes["no"] == 1

    def test_conflict_detected_on_disagreement(self):
        """Disagreement between agents produces at least one Conflict."""
        outputs = [_ao("a", "yes"), _ao("b", "no")]
        weights = {"a": 1.0, "b": 1.0}
        result = self._synthesize(outputs, weights)
        assert len(result.conflicts) >= 1

    def test_returns_synthesis_result_instance(self):
        """Return type is SynthesisResult."""
        outputs = [_ao("a", "yes")]
        result = self._synthesize(outputs, {"a": 1.0})
        assert isinstance(result, SynthesisResult)


# ---------------------------------------------------------------------------
# curate_recent
# ---------------------------------------------------------------------------


class TestCurateRecent:
    def test_empty_history_returns_empty(self):
        """Empty input → empty output."""
        assert curate_recent([], 5) == []

    def test_all_rounds_within_window(self):
        """All rounds returned when window >= total rounds."""
        history = [_hist(1, "a"), _hist(2, "b")]
        result = curate_recent(history, 5)
        assert len(result) == 2

    def test_window_smaller_returns_recent_only(self):
        """Entries from early rounds excluded when window is smaller."""
        history = [_hist(1, "a"), _hist(2, "b"), _hist(3, "c")]
        result = curate_recent(history, 2)
        rounds_in_result = {e["round"] for e in result}
        assert 1 not in rounds_in_result
        assert 2 in rounds_in_result
        assert 3 in rounds_in_result

    def test_multiple_entries_per_round_all_included(self):
        """All entries in a included round are returned, not just one."""
        history = [_hist(1, "a"), _hist(1, "b"), _hist(1, "c")]
        result = curate_recent(history, 1)
        assert len(result) == 3

    def test_window_size_one_returns_last_round_only(self):
        """Window of 1 returns only the most recent round's entries."""
        history = [_hist(1, "a"), _hist(2, "a"), _hist(3, "a")]
        result = curate_recent(history, 1)
        assert all(e["round"] == 3 for e in result)


# ---------------------------------------------------------------------------
# curate_relevant
# ---------------------------------------------------------------------------


class TestCurateRelevant:
    def test_no_agent_name_falls_back_to_recent(self):
        """Without agent_name, delegates to curate_recent strategy."""
        history = [_hist(1, "x"), _hist(2, "y"), _hist(3, "z")]
        result = curate_relevant(history, None, 2)
        rounds = {e["round"] for e in result}
        # Should include only last 2 rounds (2 and 3)
        assert 1 not in rounds
        assert 2 in rounds
        assert 3 in rounds

    def test_agents_own_entries_included(self):
        """Agent's own history entries from previous rounds are included."""
        history = [
            _hist(1, "alpha"),
            _hist(1, "beta"),
            _hist(2, "alpha"),
            _hist(2, "beta"),
            _hist(3, "alpha"),
            _hist(3, "beta"),
        ]
        result = curate_relevant(history, "alpha", 10)
        alpha_entries = [e for e in result if e["agent"] == "alpha"]
        assert len(alpha_entries) >= 2

    def test_latest_round_always_included(self):
        """All entries from the latest round are always included."""
        history = [
            _hist(1, "a"),
            _hist(2, "b"),
            _hist(3, "c"),  # latest round
            _hist(3, "d"),
        ]
        result = curate_relevant(history, "a", 1)
        latest_entries = [e for e in result if e["round"] == 3]
        assert len(latest_entries) == 2

    def test_agent_name_in_reasoning_included(self):
        """Entries where agent_name appears in reasoning are included."""
        history = [
            _hist(1, "other", reasoning="alpha did something interesting"),
            _hist(2, "alpha"),
            _hist(3, "other"),  # latest round
        ]
        result = curate_relevant(history, "alpha", 10)
        round1_entries = [e for e in result if e["round"] == 1]
        assert len(round1_entries) == 1

    def test_too_few_relevant_falls_back_to_recent(self):
        """Fewer than 2 relevant entries triggers fallback to recent strategy."""
        history = [
            _hist(1, "stranger"),
            _hist(2, "stranger"),
            _hist(3, "stranger"),
        ]
        # "alpha" never appears in agent or reasoning, so relevance = only round 3
        # That's 1 entry, which triggers fallback (window=2)
        result = curate_relevant(history, "alpha", 2)
        rounds = {e["round"] for e in result}
        # After fallback: last 2 rounds = 2 and 3
        assert 1 not in rounds
        assert 2 in rounds

    def test_empty_history_returns_empty(self):
        """Empty history → empty output regardless of agent_name."""
        assert curate_relevant([], "alpha", 5) == []


# ---------------------------------------------------------------------------
# calculate_exact_match_convergence
# ---------------------------------------------------------------------------


class TestCalculateExactMatchConvergence:
    def test_identical_outputs_returns_one(self):
        """Perfect convergence when all agents keep same decision."""
        prev = [_ao("a", "yes"), _ao("b", "no")]
        curr = [_ao("a", "yes"), _ao("b", "no")]
        assert calculate_exact_match_convergence(curr, prev) == pytest.approx(1.0)

    def test_all_changed_returns_zero(self):
        """No convergence when all decisions changed."""
        prev = [_ao("a", "yes"), _ao("b", "yes")]
        curr = [_ao("a", "no"), _ao("b", "no")]
        assert calculate_exact_match_convergence(curr, prev) == pytest.approx(0.0)

    def test_no_common_agents_returns_zero(self):
        """No common agents → convergence is 0.0."""
        prev = [_ao("a", "yes")]
        curr = [_ao("b", "yes")]
        assert calculate_exact_match_convergence(curr, prev) == pytest.approx(0.0)

    def test_partial_match(self):
        """Half of common agents unchanged → 0.5 convergence."""
        prev = [_ao("a", "yes"), _ao("b", "no")]
        curr = [_ao("a", "yes"), _ao("b", "yes")]
        assert calculate_exact_match_convergence(curr, prev) == pytest.approx(0.5)

    def test_empty_outputs_return_zero(self):
        """Empty lists → no common agents → 0.0."""
        assert calculate_exact_match_convergence([], []) == pytest.approx(0.0)
