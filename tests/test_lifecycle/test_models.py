"""Tests for temper_ai.lifecycle.models SQLModel tables."""

from datetime import datetime

from temper_ai.lifecycle.models import (
    STATUS_DISABLED,
    STATUS_ENABLED,
    LifecycleAdaptation,
    LifecycleProfileRecord,
)


class TestStatusConstants:
    def test_status_enabled_value(self):
        assert STATUS_ENABLED == "enabled"

    def test_status_disabled_value(self):
        assert STATUS_DISABLED == "disabled"

    def test_statuses_distinct(self):
        assert STATUS_ENABLED != STATUS_DISABLED


class TestLifecycleAdaptation:
    def _make_adaptation(self, **kwargs):
        defaults = {
            "id": "adapt-001",
            "workflow_id": "wf-abc",
            "profile_name": "lean",
        }
        defaults.update(kwargs)
        return LifecycleAdaptation(**defaults)

    def test_required_fields(self):
        a = self._make_adaptation()
        assert a.id == "adapt-001"
        assert a.workflow_id == "wf-abc"
        assert a.profile_name == "lean"

    def test_default_characteristics_empty(self):
        a = self._make_adaptation()
        assert a.characteristics == {}

    def test_default_rules_applied_empty(self):
        a = self._make_adaptation()
        assert a.rules_applied == []

    def test_default_stages_original_empty(self):
        a = self._make_adaptation()
        assert a.stages_original == []

    def test_default_stages_adapted_empty(self):
        a = self._make_adaptation()
        assert a.stages_adapted == []

    def test_default_experiment_id_none(self):
        a = self._make_adaptation()
        assert a.experiment_id is None

    def test_default_experiment_variant_none(self):
        a = self._make_adaptation()
        assert a.experiment_variant is None

    def test_created_at_auto_populated(self):
        a = self._make_adaptation()
        assert isinstance(a.created_at, datetime)

    def test_custom_characteristics(self):
        chars = {"size": "small", "risk_level": "low"}
        a = self._make_adaptation(characteristics=chars)
        assert a.characteristics["size"] == "small"

    def test_custom_rules_applied(self):
        rules = ["skip_design", "add_security"]
        a = self._make_adaptation(rules_applied=rules)
        assert len(a.rules_applied) == 2
        assert "skip_design" in a.rules_applied

    def test_custom_stages_original(self):
        stages = ["triage", "design", "implement"]
        a = self._make_adaptation(stages_original=stages)
        assert a.stages_original == ["triage", "design", "implement"]

    def test_custom_stages_adapted(self):
        stages = ["triage", "implement"]
        a = self._make_adaptation(stages_adapted=stages)
        assert a.stages_adapted == ["triage", "implement"]

    def test_stages_reduced(self):
        a = self._make_adaptation(
            stages_original=["a", "b", "c"],
            stages_adapted=["a", "c"],
        )
        assert len(a.stages_adapted) < len(a.stages_original)

    def test_experiment_fields_set(self):
        a = self._make_adaptation(experiment_id="exp-001", experiment_variant="control")
        assert a.experiment_id == "exp-001"
        assert a.experiment_variant == "control"

    def test_tablename(self):
        assert LifecycleAdaptation.__tablename__ == "lifecycle_adaptations"

    def test_instances_are_independent(self):
        a1 = self._make_adaptation(id="a1")
        a2 = self._make_adaptation(id="a2")
        a2.rules_applied.append("extra_rule")
        assert a1.rules_applied == []


class TestLifecycleProfileRecord:
    def _make_profile(self, **kwargs):
        defaults = {"id": "prof-001", "name": "lean"}
        defaults.update(kwargs)
        return LifecycleProfileRecord(**defaults)

    def test_required_fields(self):
        p = self._make_profile()
        assert p.id == "prof-001"
        assert p.name == "lean"

    def test_default_description_empty(self):
        p = self._make_profile()
        assert p.description == ""

    def test_default_version(self):
        p = self._make_profile()
        assert p.version == "1.0"

    def test_default_product_types_empty(self):
        p = self._make_profile()
        assert p.product_types == []

    def test_default_rules_empty(self):
        p = self._make_profile()
        assert p.rules == []

    def test_default_enabled_true(self):
        p = self._make_profile()
        assert p.enabled is True

    def test_default_source_manual(self):
        p = self._make_profile()
        assert p.source == "manual"

    def test_default_confidence_one(self):
        p = self._make_profile()
        assert p.confidence == 1.0

    def test_default_min_autonomy_level_zero(self):
        p = self._make_profile()
        assert p.min_autonomy_level == 0

    def test_default_requires_approval_true(self):
        p = self._make_profile()
        assert p.requires_approval is True

    def test_created_at_auto_populated(self):
        p = self._make_profile()
        assert isinstance(p.created_at, datetime)

    def test_default_updated_at_none(self):
        p = self._make_profile()
        assert p.updated_at is None

    def test_custom_description(self):
        p = self._make_profile(description="A lean workflow profile")
        assert p.description == "A lean workflow profile"

    def test_custom_product_types(self):
        p = self._make_profile(product_types=["api", "batch"])
        assert "api" in p.product_types

    def test_custom_rules(self):
        rules = [{"name": "skip_design", "action": "skip", "stage_name": "design"}]
        p = self._make_profile(rules=rules)
        assert len(p.rules) == 1

    def test_disabled_profile(self):
        p = self._make_profile(enabled=False)
        assert p.enabled is False

    def test_learned_source(self):
        p = self._make_profile(source="learned", confidence=0.8)
        assert p.source == "learned"
        assert p.confidence == 0.8

    def test_updated_at_set(self):
        ts = datetime(2026, 2, 15, 10, 0, 0)
        p = self._make_profile(updated_at=ts)
        assert p.updated_at == ts

    def test_min_autonomy_level_custom(self):
        p = self._make_profile(min_autonomy_level=2)
        assert p.min_autonomy_level == 2

    def test_requires_approval_false(self):
        p = self._make_profile(requires_approval=False)
        assert p.requires_approval is False

    def test_tablename(self):
        assert LifecycleProfileRecord.__tablename__ == "lifecycle_profiles"
