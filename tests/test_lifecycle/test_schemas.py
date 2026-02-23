"""Tests for lifecycle schemas."""

import pytest
from pydantic import ValidationError

from temper_ai.lifecycle._schemas import (
    AdaptationAction,
    AdaptationRecord,
    AdaptationRule,
    LifecycleConfig,
    LifecycleProfile,
    ProjectCharacteristics,
    ProjectSize,
    RiskLevel,
)


class TestProjectCharacteristics:
    """Tests for ProjectCharacteristics schema."""

    def test_defaults(self):
        chars = ProjectCharacteristics()
        assert chars.size == ProjectSize.MEDIUM
        assert chars.risk_level == RiskLevel.MEDIUM
        assert chars.estimated_complexity == 0.5
        assert chars.is_prototype is False
        assert chars.tags == []

    def test_custom_values(self):
        chars = ProjectCharacteristics(
            size=ProjectSize.SMALL,
            risk_level=RiskLevel.CRITICAL,
            estimated_complexity=0.9,
            is_prototype=True,
            tags=["security", "payments"],
        )
        assert chars.size == ProjectSize.SMALL
        assert chars.risk_level == RiskLevel.CRITICAL
        assert chars.tags == ["security", "payments"]

    def test_complexity_bounds(self):
        with pytest.raises(ValidationError):
            ProjectCharacteristics(estimated_complexity=1.5)
        with pytest.raises(ValidationError):
            ProjectCharacteristics(estimated_complexity=-0.1)


class TestAdaptationRule:
    """Tests for AdaptationRule schema."""

    def test_skip_rule(self):
        rule = AdaptationRule(
            name="skip_design",
            action=AdaptationAction.SKIP,
            stage_name="design",
            condition="{{ size == 'small' }}",
        )
        assert rule.action == AdaptationAction.SKIP
        assert rule.priority == 0

    def test_add_rule(self):
        rule = AdaptationRule(
            name="add_security",
            action=AdaptationAction.ADD,
            stage_name="security_review",
            condition="{{ risk_level == 'high' }}",
            stage_ref="configs/stages/security.yaml",
            insert_after="implement",
        )
        assert rule.stage_ref == "configs/stages/security.yaml"
        assert rule.insert_after == "implement"


class TestLifecycleProfile:
    """Tests for LifecycleProfile schema."""

    def test_defaults(self):
        profile = LifecycleProfile(name="test", description="A test")
        assert profile.enabled is True
        assert profile.source == "manual"
        assert profile.confidence == 1.0
        assert profile.min_autonomy_level == 0
        assert profile.requires_approval is True

    def test_with_rules(self):
        profile = LifecycleProfile(
            name="lean",
            description="Lean profile",
            rules=[
                AdaptationRule(
                    name="r1",
                    action=AdaptationAction.SKIP,
                    stage_name="design",
                    condition="{{ size == 'small' }}",
                ),
            ],
        )
        assert len(profile.rules) == 1


class TestLifecycleConfig:
    """Tests for LifecycleConfig schema."""

    def test_defaults(self):
        cfg = LifecycleConfig()
        assert cfg.enabled is False
        assert cfg.profile is None
        assert cfg.auto_classify is True
        assert cfg.experiment_id is None

    def test_enabled_with_profile(self):
        cfg = LifecycleConfig(enabled=True, profile="lean")
        assert cfg.enabled is True
        assert cfg.profile == "lean"


class TestAdaptationRecord:
    """Tests for AdaptationRecord schema."""

    def test_basic_record(self):
        record = AdaptationRecord(
            workflow_id="wf-123",
            profile_name="lean",
            characteristics=ProjectCharacteristics(),
            rules_applied=["skip_design"],
            stages_original=["triage", "design", "implement"],
            stages_adapted=["triage", "implement"],
        )
        assert record.workflow_id == "wf-123"
        assert len(record.rules_applied) == 1
