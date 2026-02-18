"""Tests for the FeedbackApplier."""

from unittest.mock import MagicMock, patch

import pytest

from src.autonomy.feedback_applier import FeedbackApplier, _parse_action


# ── Helpers ────────────────────────────────────────────────────────────

def _mock_recommendation(
    rec_id: str = "rec-001",
    pattern_id: str = "pat-001",
    config_path: str = "configs/agents/test.yaml",
    field_path: str = "model.temperature",
    current_value: str = "0.7",
    recommended_value: str = "0.5",
    status: str = "pending",
) -> MagicMock:
    """Create a mock TuneRecommendation."""
    rec = MagicMock()
    rec.id = rec_id
    rec.pattern_id = pattern_id
    rec.config_path = config_path
    rec.field_path = field_path
    rec.current_value = current_value
    rec.recommended_value = recommended_value
    rec.status = status
    return rec


def _mock_pattern(
    pattern_id: str = "pat-001",
    confidence: float = 0.9,
) -> MagicMock:
    """Create a mock LearnedPattern."""
    pat = MagicMock()
    pat.id = pattern_id
    pat.confidence = confidence
    return pat


_DEFAULT_GOAL_ACTIONS = ["configs/agents/test.yaml:model.temperature=0.5"]


def _mock_goal(
    goal_id: str = "goal-001",
    proposed_actions: list = None,
    risk_assessment: dict = None,
) -> MagicMock:
    """Create a mock GoalProposalRecord."""
    goal = MagicMock()
    goal.id = goal_id
    goal.proposed_actions = (
        proposed_actions if proposed_actions is not None else list(_DEFAULT_GOAL_ACTIONS)
    )
    goal.risk_assessment = risk_assessment if risk_assessment is not None else {"level": "low"}
    return goal


def _make_applier(
    learning_store: object = None,
    goal_store: object = None,
    safety_policy: object = None,
    max_auto_apply: int = 5,
) -> FeedbackApplier:
    """Create a FeedbackApplier with optional mocked dependencies."""
    return FeedbackApplier(
        learning_store=learning_store or MagicMock(),
        goal_store=goal_store,
        safety_policy=safety_policy,
        max_auto_apply=max_auto_apply,
    )


# ── Learning Recommendation Tests ─────────────────────────────────────

class TestApplyLearningRecommendations:
    """Tests for apply_learning_recommendations."""

    @patch("src.autonomy.feedback_applier.AuditLogger")
    @patch("src.learning.auto_tune.AutoTuneEngine")
    def test_applies_eligible_recommendations(
        self, MockEngine: MagicMock, MockAudit: MagicMock
    ) -> None:
        store = MagicMock()
        rec = _mock_recommendation()
        pattern = _mock_pattern(confidence=0.9)

        store.list_recommendations.return_value = [rec]
        store.get_pattern.return_value = pattern
        MockEngine.return_value.apply_recommendations.return_value = [
            {"id": "rec-001", "status": "applied", "config_path": "c.yaml", "field_path": "f"}
        ]

        applier = FeedbackApplier(learning_store=store)
        results = applier.apply_learning_recommendations(min_confidence=0.8)

        assert len(results) == 1
        assert results[0]["status"] == "applied"

    @patch("src.learning.auto_tune.AutoTuneEngine")
    def test_filters_low_confidence(self, MockEngine: MagicMock) -> None:
        store = MagicMock()
        rec = _mock_recommendation(pattern_id="pat-low")
        low_pattern = _mock_pattern(pattern_id="pat-low", confidence=0.3)

        store.list_recommendations.return_value = [rec]
        store.get_pattern.return_value = low_pattern

        applier = FeedbackApplier(learning_store=store)
        results = applier.apply_learning_recommendations(min_confidence=0.8)

        assert results == []
        MockEngine.return_value.apply_recommendations.assert_not_called()

    @patch("src.learning.auto_tune.AutoTuneEngine")
    def test_filters_missing_pattern(self, MockEngine: MagicMock) -> None:
        store = MagicMock()
        rec = _mock_recommendation(pattern_id="pat-gone")
        store.list_recommendations.return_value = [rec]
        store.get_pattern.return_value = None

        applier = FeedbackApplier(learning_store=store)
        results = applier.apply_learning_recommendations()

        assert results == []

    @patch("src.learning.auto_tune.AutoTuneEngine")
    def test_respects_max_auto_apply(self, MockEngine: MagicMock) -> None:
        store = MagicMock()
        recs = [_mock_recommendation(rec_id=f"rec-{i}", pattern_id=f"pat-{i}") for i in range(10)]
        patterns = {f"pat-{i}": _mock_pattern(pattern_id=f"pat-{i}", confidence=0.95) for i in range(10)}

        store.list_recommendations.return_value = recs
        store.get_pattern.side_effect = lambda pid: patterns.get(pid)
        MockEngine.return_value.apply_recommendations.return_value = [
            {"id": f"rec-{i}", "status": "applied"} for i in range(2)
        ]

        applier = FeedbackApplier(learning_store=store, max_auto_apply=2)
        applier.apply_learning_recommendations()

        # Engine should only receive 2 rec_ids
        call_args = MockEngine.return_value.apply_recommendations.call_args
        assert len(call_args[0][0]) == 2

    @patch("src.learning.auto_tune.AutoTuneEngine")
    def test_dry_run_uses_preview(self, MockEngine: MagicMock) -> None:
        store = MagicMock()
        rec = _mock_recommendation()
        pattern = _mock_pattern(confidence=0.95)

        store.list_recommendations.return_value = [rec]
        store.get_pattern.return_value = pattern
        MockEngine.return_value.preview_changes.return_value = [
            {"id": "rec-001", "status": "preview"}
        ]

        applier = FeedbackApplier(learning_store=store)
        results = applier.apply_learning_recommendations(dry_run=True)

        assert len(results) == 1
        assert results[0]["status"] == "preview"
        MockEngine.return_value.apply_recommendations.assert_not_called()

    @patch("src.learning.auto_tune.AutoTuneEngine")
    def test_no_pending_returns_empty(self, MockEngine: MagicMock) -> None:
        store = MagicMock()
        store.list_recommendations.return_value = []

        applier = FeedbackApplier(learning_store=store)
        results = applier.apply_learning_recommendations()

        assert results == []

    @patch("src.autonomy.feedback_applier.AuditLogger")
    @patch("src.learning.auto_tune.AutoTuneEngine")
    def test_mixed_confidence_filters_correctly(
        self, MockEngine: MagicMock, MockAudit: MagicMock
    ) -> None:
        store = MagicMock()
        high_rec = _mock_recommendation(rec_id="high", pattern_id="pat-high")
        low_rec = _mock_recommendation(rec_id="low", pattern_id="pat-low")

        store.list_recommendations.return_value = [high_rec, low_rec]

        def get_pattern(pid: str) -> MagicMock:
            if pid == "pat-high":
                return _mock_pattern(pattern_id=pid, confidence=0.95)
            return _mock_pattern(pattern_id=pid, confidence=0.3)

        store.get_pattern.side_effect = get_pattern
        MockEngine.return_value.apply_recommendations.return_value = [
            {"id": "high", "status": "applied"}
        ]

        applier = FeedbackApplier(learning_store=store)
        results = applier.apply_learning_recommendations(min_confidence=0.8)

        # Only the high-confidence rec should be passed to the engine
        call_args = MockEngine.return_value.apply_recommendations.call_args
        assert call_args[0][0] == ["high"]

    @patch("src.learning.auto_tune.AutoTuneEngine")
    def test_custom_confidence_threshold(self, MockEngine: MagicMock) -> None:
        store = MagicMock()
        rec = _mock_recommendation()
        pattern = _mock_pattern(confidence=0.6)

        store.list_recommendations.return_value = [rec]
        store.get_pattern.return_value = pattern

        applier = FeedbackApplier(learning_store=store)

        # 0.5 threshold — should include the 0.6 confidence pattern
        MockEngine.return_value.apply_recommendations.return_value = [
            {"id": "rec-001", "status": "applied"}
        ]
        results = applier.apply_learning_recommendations(min_confidence=0.5)
        assert len(results) == 1

    @patch("src.learning.auto_tune.AutoTuneEngine")
    def test_exact_confidence_boundary(self, MockEngine: MagicMock) -> None:
        store = MagicMock()
        rec = _mock_recommendation()
        pattern = _mock_pattern(confidence=0.8)

        store.list_recommendations.return_value = [rec]
        store.get_pattern.return_value = pattern
        MockEngine.return_value.apply_recommendations.return_value = [
            {"id": "rec-001", "status": "applied"}
        ]

        applier = FeedbackApplier(learning_store=store)
        results = applier.apply_learning_recommendations(min_confidence=0.8)
        assert len(results) == 1


# ── Goal Translation Tests ────────────────────────────────────────────

class TestTranslateGoalToRecommendations:
    """Tests for translate_goal_to_recommendations."""

    def test_parses_valid_action(self) -> None:
        goal = _mock_goal(
            proposed_actions=["configs/agents/test.yaml:model.temperature=0.5"]
        )
        applier = _make_applier()
        results = applier.translate_goal_to_recommendations(goal)

        assert len(results) == 1
        assert results[0]["status"] == "translated"
        assert results[0]["config_path"] == "configs/agents/test.yaml"
        assert results[0]["field_path"] == "model.temperature"
        assert results[0]["new_value"] == "0.5"

    def test_unparseable_action(self) -> None:
        goal = _mock_goal(
            proposed_actions=["some free-form text recommendation"]
        )
        applier = _make_applier()
        results = applier.translate_goal_to_recommendations(goal)

        assert len(results) == 1
        assert results[0]["status"] == "unparseable"
        assert results[0]["raw_action"] == "some free-form text recommendation"

    def test_mixed_actions(self) -> None:
        goal = _mock_goal(
            proposed_actions=[
                "configs/a.yaml:field=val",
                "not a parseable action",
                "configs/b.yaml:x.y=z",
            ]
        )
        applier = _make_applier()
        results = applier.translate_goal_to_recommendations(goal)

        assert len(results) == 3
        assert results[0]["status"] == "translated"
        assert results[1]["status"] == "unparseable"
        assert results[2]["status"] == "translated"  # noqa: scanner: skip-magic

    def test_empty_actions(self) -> None:
        goal = _mock_goal(proposed_actions=[])
        applier = _make_applier()
        results = applier.translate_goal_to_recommendations(goal)
        assert results == []

    def test_action_with_equals_in_value(self) -> None:
        goal = _mock_goal(
            proposed_actions=["configs/a.yaml:key=val=with=equals"]
        )
        applier = _make_applier()
        results = applier.translate_goal_to_recommendations(goal)

        assert len(results) == 1
        assert results[0]["new_value"] == "val=with=equals"

    def test_action_with_spaces(self) -> None:
        goal = _mock_goal(
            proposed_actions=["  configs/a.yaml : key.path = some value  "]
        )
        applier = _make_applier()
        results = applier.translate_goal_to_recommendations(goal)

        assert len(results) == 1
        assert results[0]["config_path"] == "configs/a.yaml"
        assert results[0]["field_path"] == "key.path"
        assert results[0]["new_value"] == "some value"


# ── Goal Application Tests ────────────────────────────────────────────

class TestApplyApprovedGoals:
    """Tests for apply_approved_goals."""

    def test_no_goal_store_returns_empty(self) -> None:
        applier = FeedbackApplier(
            learning_store=MagicMock(), goal_store=None
        )
        results = applier.apply_approved_goals()
        assert results == []

    @patch("src.autonomy.feedback_applier.AuditLogger")
    def test_applies_approved_goals(self, MockAudit: MagicMock) -> None:
        goal_store = MagicMock()
        goal = _mock_goal(
            proposed_actions=["configs/a.yaml:model.temp=0.3"]
        )
        goal_store.list_proposals.return_value = [goal]

        applier = FeedbackApplier(
            learning_store=MagicMock(), goal_store=goal_store
        )
        results = applier.apply_approved_goals()

        assert len(results) == 1
        assert results[0]["status"] == "applied"

    @patch("src.autonomy.feedback_applier.AuditLogger")
    def test_respects_max_auto_apply(self, MockAudit: MagicMock) -> None:
        goal_store = MagicMock()
        goals = [
            _mock_goal(
                goal_id=f"g-{i}",
                proposed_actions=[f"configs/a.yaml:key{i}=val{i}"],
            )
            for i in range(10)
        ]
        goal_store.list_proposals.return_value = goals

        applier = FeedbackApplier(
            learning_store=MagicMock(),
            goal_store=goal_store,
            max_auto_apply=3,
        )
        results = applier.apply_approved_goals()

        applied = [r for r in results if r.get("status") == "applied"]
        assert len(applied) == 3

    def test_safety_policy_blocks_high_risk(self) -> None:
        goal_store = MagicMock()
        high_risk_goal = _mock_goal(
            goal_id="risky",
            proposed_actions=["configs/a.yaml:key=val"],
            risk_assessment={"level": "high"},
        )
        goal_store.list_proposals.return_value = [high_risk_goal]

        applier = FeedbackApplier(
            learning_store=MagicMock(),
            goal_store=goal_store,
            safety_policy=MagicMock(),  # non-None triggers safety check
        )
        results = applier.apply_approved_goals()

        assert len(results) == 1
        assert results[0]["status"] == "blocked_by_safety"

    def test_safety_policy_blocks_critical_risk(self) -> None:
        goal_store = MagicMock()
        critical_goal = _mock_goal(
            goal_id="critical",
            proposed_actions=["configs/a.yaml:key=val"],
            risk_assessment={"level": "critical"},
        )
        goal_store.list_proposals.return_value = [critical_goal]

        applier = FeedbackApplier(
            learning_store=MagicMock(),
            goal_store=goal_store,
            safety_policy=MagicMock(),
        )
        results = applier.apply_approved_goals()

        assert len(results) == 1
        assert results[0]["status"] == "blocked_by_safety"

    @patch("src.autonomy.feedback_applier.AuditLogger")
    def test_safety_policy_allows_low_risk(self, MockAudit: MagicMock) -> None:
        goal_store = MagicMock()
        low_risk_goal = _mock_goal(
            goal_id="safe",
            proposed_actions=["configs/a.yaml:key=val"],
            risk_assessment={"level": "low"},
        )
        goal_store.list_proposals.return_value = [low_risk_goal]

        applier = FeedbackApplier(
            learning_store=MagicMock(),
            goal_store=goal_store,
            safety_policy=MagicMock(),
        )
        results = applier.apply_approved_goals()

        assert len(results) == 1
        assert results[0]["status"] == "applied"

    @patch("src.autonomy.feedback_applier.AuditLogger")
    def test_safety_policy_allows_medium_risk(self, MockAudit: MagicMock) -> None:
        goal_store = MagicMock()
        goal = _mock_goal(
            goal_id="med",
            proposed_actions=["configs/a.yaml:key=val"],
            risk_assessment={"level": "medium"},
        )
        goal_store.list_proposals.return_value = [goal]

        applier = FeedbackApplier(
            learning_store=MagicMock(),
            goal_store=goal_store,
            safety_policy=MagicMock(),
        )
        results = applier.apply_approved_goals()

        assert len(results) == 1
        assert results[0]["status"] == "applied"

    def test_no_safety_policy_allows_all(self) -> None:
        goal_store = MagicMock()
        goal = _mock_goal(
            proposed_actions=["configs/a.yaml:key=val"],
            risk_assessment={"level": "high"},
        )
        goal_store.list_proposals.return_value = [goal]

        applier = FeedbackApplier(
            learning_store=MagicMock(),
            goal_store=goal_store,
            safety_policy=None,
        )
        results = applier.apply_approved_goals()

        # Without a safety policy, even high-risk goals are allowed
        applied = [r for r in results if r.get("status") == "applied"]
        assert len(applied) == 1

    def test_unparseable_actions_not_applied(self) -> None:
        goal_store = MagicMock()
        goal = _mock_goal(
            proposed_actions=["some vague action"]
        )
        goal_store.list_proposals.return_value = [goal]

        applier = FeedbackApplier(
            learning_store=MagicMock(), goal_store=goal_store
        )
        results = applier.apply_approved_goals()

        assert len(results) == 1
        assert results[0]["status"] == "unparseable"


# ── Audit Integration Tests ───────────────────────────────────────────

class TestFeedbackApplierAudit:
    """Tests for audit logging in FeedbackApplier."""

    @patch("src.learning.auto_tune.AutoTuneEngine")
    def test_learning_apply_creates_audit_entries(
        self, MockEngine: MagicMock, tmp_path
    ) -> None:
        store = MagicMock()
        rec = _mock_recommendation()
        pattern = _mock_pattern(confidence=0.95)

        store.list_recommendations.return_value = [rec]
        store.get_pattern.return_value = pattern
        MockEngine.return_value.apply_recommendations.return_value = [
            {
                "id": "rec-001",
                "status": "applied",
                "config_path": "configs/agents/test.yaml",
                "field_path": "model.temperature",
                "current_value": "0.7",
                "recommended_value": "0.5",
            }
        ]

        applier = FeedbackApplier(learning_store=store)
        # Replace internal audit logger with one using tmp_path
        from src.autonomy.audit import AuditLogger
        applier._audit = AuditLogger(base_dir=str(tmp_path / "audit"))

        results = applier.apply_learning_recommendations()
        assert results[0]["status"] == "applied"

        entries = applier._audit.get_entries()
        assert len(entries) == 1
        assert entries[0].action_type == "learning_recommendation"
        assert entries[0].source_id == "rec-001"

    def test_goal_apply_creates_audit_entries(self, tmp_path) -> None:
        goal_store = MagicMock()
        goal = _mock_goal(
            proposed_actions=["configs/a.yaml:key=val"]
        )
        goal_store.list_proposals.return_value = [goal]

        applier = FeedbackApplier(
            learning_store=MagicMock(), goal_store=goal_store
        )
        from src.autonomy.audit import AuditLogger
        applier._audit = AuditLogger(base_dir=str(tmp_path / "audit"))

        applier.apply_approved_goals()

        entries = applier._audit.get_entries()
        assert len(entries) == 1
        assert entries[0].action_type == "goal_application"
        assert entries[0].source_id == "goal-001"


# ── Error Handling / Graceful Degradation ─────────────────────────────

class TestFeedbackApplierErrorHandling:
    """Tests for graceful degradation."""

    @patch("src.learning.auto_tune.AutoTuneEngine")
    def test_engine_exception_propagates(self, MockEngine: MagicMock) -> None:
        store = MagicMock()
        rec = _mock_recommendation()
        pattern = _mock_pattern(confidence=0.95)

        store.list_recommendations.return_value = [rec]
        store.get_pattern.return_value = pattern
        MockEngine.return_value.apply_recommendations.side_effect = RuntimeError("engine boom")

        applier = FeedbackApplier(learning_store=store)
        with pytest.raises(RuntimeError, match="engine boom"):
            applier.apply_learning_recommendations()

    def test_goal_store_exception_propagates(self) -> None:
        goal_store = MagicMock()
        goal_store.list_proposals.side_effect = RuntimeError("db error")

        applier = FeedbackApplier(
            learning_store=MagicMock(), goal_store=goal_store
        )
        with pytest.raises(RuntimeError, match="db error"):
            applier.apply_approved_goals()


class TestGoalCompletionAfterApply:
    """Tests that goals are marked as completed after successful application."""

    @patch("src.autonomy.feedback_applier.AuditLogger")
    def test_goal_marked_completed_after_apply(self, MockAudit: MagicMock) -> None:
        goal_store = MagicMock()
        goal = _mock_goal(
            goal_id="goal-complete",
            proposed_actions=["configs/a.yaml:model.temp=0.3"],
        )
        goal_store.list_proposals.return_value = [goal]

        applier = FeedbackApplier(
            learning_store=MagicMock(), goal_store=goal_store,
        )
        results = applier.apply_approved_goals()

        assert len(results) == 1
        assert results[0]["status"] == "applied"
        goal_store.update_proposal_status.assert_called_once_with(
            "goal-complete", "completed",
        )

    def test_goal_not_marked_completed_if_unparseable(self) -> None:
        goal_store = MagicMock()
        goal = _mock_goal(
            goal_id="goal-unparse",
            proposed_actions=["some vague action"],
        )
        goal_store.list_proposals.return_value = [goal]

        applier = FeedbackApplier(
            learning_store=MagicMock(), goal_store=goal_store,
        )
        results = applier.apply_approved_goals()

        assert results[0]["status"] == "unparseable"
        goal_store.update_proposal_status.assert_not_called()

    @patch("src.autonomy.feedback_applier.AuditLogger")
    def test_goal_completion_failure_does_not_crash(self, MockAudit: MagicMock) -> None:
        goal_store = MagicMock()
        goal = _mock_goal(
            goal_id="goal-fail",
            proposed_actions=["configs/a.yaml:key=val"],
        )
        goal_store.list_proposals.return_value = [goal]
        goal_store.update_proposal_status.side_effect = RuntimeError("db error")

        applier = FeedbackApplier(
            learning_store=MagicMock(), goal_store=goal_store,
        )
        # Should not raise despite the status update failing
        results = applier.apply_approved_goals()
        assert len(results) == 1
        assert results[0]["status"] == "applied"

    def test_safety_check_exception_blocks_goal(self) -> None:
        goal_store = MagicMock()
        goal = _mock_goal()
        # Make risk_assessment raise on attribute access to trigger exception path
        type(goal).risk_assessment = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("corrupt data"))
        )
        goal_store.list_proposals.return_value = [goal]

        applier = FeedbackApplier(
            learning_store=MagicMock(),
            goal_store=goal_store,
            safety_policy=MagicMock(),
        )
        results = applier.apply_approved_goals()
        assert len(results) == 1
        assert results[0]["status"] == "blocked_by_safety"


# ── _parse_action Tests ───────────────────────────────────────────────

class TestParseAction:
    """Tests for the _parse_action helper."""

    def test_valid_format(self) -> None:
        result = _parse_action("configs/a.yaml:model.temp=0.5")
        assert result is not None
        assert result["config_path"] == "configs/a.yaml"
        assert result["field_path"] == "model.temp"
        assert result["new_value"] == "0.5"

    def test_missing_equals(self) -> None:
        assert _parse_action("configs/a.yaml:model.temp") is None

    def test_missing_colon(self) -> None:
        assert _parse_action("no_colon_here=val") is None

    def test_empty_string(self) -> None:
        assert _parse_action("") is None

    def test_equals_in_value(self) -> None:
        result = _parse_action("c.yaml:key=a=b=c")
        assert result is not None
        assert result["new_value"] == "a=b=c"
