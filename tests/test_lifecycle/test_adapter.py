"""Tests for lifecycle adapter — core adaptation logic."""

import copy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.lifecycle._schemas import (
    AdaptationAction,
    AdaptationRule,
    LifecycleProfile,
    ProjectCharacteristics,
    ProjectSize,
    RiskLevel,
)
from src.lifecycle.adapter import (
    LifecycleAdapter,
    _apply_add,
    _apply_modify,
    _apply_reorder,
    _apply_rules,
    _apply_skip,
    _evaluate_condition,
)
from src.lifecycle.classifier import ProjectClassifier
from src.lifecycle.profiles import ProfileRegistry
from src.lifecycle.store import LifecycleStore


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def store():
    return LifecycleStore(database_url="sqlite:///:memory:")


@pytest.fixture
def config_dir(tmp_path):
    profile_file = tmp_path / "lean.yaml"
    profile_file.write_text(
        "name: lean\n"
        "description: Lean profile\n"
        "rules:\n"
        "  - name: skip_design\n"
        "    action: skip\n"
        "    stage_name: design\n"
        "    condition: \"{{ size == 'small' and risk_level in ['low', 'medium'] }}\"\n"
        "    priority: 10\n"
        "enabled: true\n"
        "requires_approval: false\n"
        "source: manual\n"
    )
    return tmp_path


@pytest.fixture
def workflow_config():
    return {
        "workflow": {
            "name": "test_wf",
            "lifecycle": {"enabled": True, "profile": "lean"},
            "stages": [
                {"name": "triage", "stage_ref": "stages/triage.yaml"},
                {"name": "design", "stage_ref": "stages/design.yaml"},
                {"name": "implement", "stage_ref": "stages/impl.yaml"},
                {"name": "test", "stage_ref": "stages/test.yaml"},
            ],
        }
    }


@pytest.fixture
def adapter(config_dir, store):
    registry = ProfileRegistry(config_dir=config_dir, store=store)
    classifier = ProjectClassifier()
    return LifecycleAdapter(
        profile_registry=registry,
        classifier=classifier,
        store=store,
    )


# ── Rule Application Tests ──────────────────────────────────────────

class TestApplySkip:
    def test_skip_existing_stage(self):
        stages = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        rule = AdaptationRule(
            name="r", action=AdaptationAction.SKIP,
            stage_name="b", condition="{{ true }}",
        )
        result = _apply_skip(stages, rule)
        assert len(result) == 2
        assert all(s["name"] != "b" for s in result)

    def test_skip_nonexistent_stage(self):
        stages = [{"name": "a"}, {"name": "b"}]
        rule = AdaptationRule(
            name="r", action=AdaptationAction.SKIP,
            stage_name="z", condition="{{ true }}",
        )
        result = _apply_skip(stages, rule)
        assert len(result) == 2  # No change


class TestApplyAdd:
    def test_add_after(self):
        stages = [{"name": "a"}, {"name": "b"}]
        rule = AdaptationRule(
            name="r", action=AdaptationAction.ADD,
            stage_name="c", condition="{{ true }}",
            stage_ref="ref.yaml", insert_after="a",
        )
        result = _apply_add(stages, rule)
        assert len(result) == 3
        assert result[1]["name"] == "c"

    def test_add_before(self):
        stages = [{"name": "a"}, {"name": "b"}]
        rule = AdaptationRule(
            name="r", action=AdaptationAction.ADD,
            stage_name="c", condition="{{ true }}",
            stage_ref="ref.yaml", insert_before="b",
        )
        result = _apply_add(stages, rule)
        assert len(result) == 3
        assert result[1]["name"] == "c"

    def test_add_existing_stage_skips(self):
        stages = [{"name": "a"}, {"name": "b"}]
        rule = AdaptationRule(
            name="r", action=AdaptationAction.ADD,
            stage_name="a", condition="{{ true }}",
        )
        result = _apply_add(stages, rule)
        assert len(result) == 2  # No duplicate

    def test_add_appends_when_no_position(self):
        stages = [{"name": "a"}]
        rule = AdaptationRule(
            name="r", action=AdaptationAction.ADD,
            stage_name="b", condition="{{ true }}",
            stage_ref="ref.yaml",
        )
        result = _apply_add(stages, rule)
        assert result[-1]["name"] == "b"


class TestApplyReorder:
    def test_move_after(self):
        stages = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        rule = AdaptationRule(
            name="r", action=AdaptationAction.REORDER,
            stage_name="a", condition="{{ true }}",
            move_after="b",
        )
        result = _apply_reorder(stages, rule)
        names = [s["name"] for s in result]
        assert names == ["b", "a", "c"]

    def test_move_before(self):
        stages = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        rule = AdaptationRule(
            name="r", action=AdaptationAction.REORDER,
            stage_name="c", condition="{{ true }}",
            move_before="a",
        )
        result = _apply_reorder(stages, rule)
        names = [s["name"] for s in result]
        assert names == ["c", "a", "b"]

    def test_reorder_nonexistent_stage(self):
        stages = [{"name": "a"}, {"name": "b"}]
        rule = AdaptationRule(
            name="r", action=AdaptationAction.REORDER,
            stage_name="z", condition="{{ true }}",
        )
        result = _apply_reorder(stages, rule)
        assert len(result) == 2  # No change


class TestApplyModify:
    def test_modify_stage(self):
        stages = [{"name": "a", "timeout": 60}]
        rule = AdaptationRule(
            name="r", action=AdaptationAction.MODIFY,
            stage_name="a", condition="{{ true }}",
            modifications={"timeout": 120},
        )
        result = _apply_modify(stages, rule)
        assert result[0]["timeout"] == 120

    def test_modify_nonexistent(self):
        stages = [{"name": "a"}]
        rule = AdaptationRule(
            name="r", action=AdaptationAction.MODIFY,
            stage_name="z", condition="{{ true }}",
            modifications={"foo": "bar"},
        )
        result = _apply_modify(stages, rule)
        assert len(result) == 1  # No change


class TestEvaluateCondition:
    def test_true_condition(self):
        from jinja2.sandbox import ImmutableSandboxedEnvironment
        env = ImmutableSandboxedEnvironment()
        assert _evaluate_condition(env, "{{ size == 'small' }}", {"size": "small"}) is True

    def test_false_condition(self):
        from jinja2.sandbox import ImmutableSandboxedEnvironment
        env = ImmutableSandboxedEnvironment()
        assert _evaluate_condition(env, "{{ size == 'small' }}", {"size": "large"}) is False

    def test_invalid_condition(self):
        from jinja2.sandbox import ImmutableSandboxedEnvironment
        env = ImmutableSandboxedEnvironment()
        assert _evaluate_condition(env, "{{ undefined_func() }}", {}) is False


class TestApplyRules:
    def test_skip_rule_applied(self):
        stages = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        rules = [AdaptationRule(
            name="skip_b", action=AdaptationAction.SKIP,
            stage_name="b", condition="{{ flag }}",
        )]
        chars = ProjectCharacteristics()
        result = _apply_rules(stages, rules, chars, {"flag": True})
        names = [s["name"] for s in result]
        assert "b" not in names

    def test_condition_false_skips_rule(self):
        stages = [{"name": "a"}, {"name": "b"}]
        rules = [AdaptationRule(
            name="skip_b", action=AdaptationAction.SKIP,
            stage_name="b", condition="{{ flag }}",
        )]
        chars = ProjectCharacteristics()
        result = _apply_rules(stages, rules, chars, {"flag": False})
        assert len(result) == 2

    def test_priority_ordering(self):
        stages = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        rules = [
            AdaptationRule(
                name="skip_a", action=AdaptationAction.SKIP,
                stage_name="a", condition="{{ true }}", priority=1,
            ),
            AdaptationRule(
                name="skip_c", action=AdaptationAction.SKIP,
                stage_name="c", condition="{{ true }}", priority=10,
            ),
        ]
        chars = ProjectCharacteristics()
        result = _apply_rules(stages, rules, chars, {})
        # Both should be applied (priority just orders them)
        assert len(result) == 1
        assert result[0]["name"] == "b"


# ── Adapter Integration Tests ───────────────────────────────────────

class TestLifecycleAdapter:
    def test_no_adaptation_when_no_profile(self, store):
        registry = ProfileRegistry(
            config_dir=Path("/nonexistent"), store=store
        )
        classifier = ProjectClassifier()
        adapter = LifecycleAdapter(
            profile_registry=registry, classifier=classifier,
        )
        config = {"workflow": {"stages": [{"name": "a"}]}}
        result = adapter.adapt(config, {})
        assert result["workflow"]["stages"] == [{"name": "a"}]

    def test_deep_copy_preserves_original(self, adapter, workflow_config):
        original = copy.deepcopy(workflow_config)
        adapter.adapt(workflow_config, {"size": "small", "risk_level": "low"})
        assert workflow_config == original

    def test_small_project_skips_design(self, adapter, workflow_config):
        result = adapter.adapt(
            workflow_config,
            {"size": "small", "risk_level": "low"},
        )
        stage_names = [s["name"] for s in result["workflow"]["stages"]]
        assert "design" not in stage_names
        assert "triage" in stage_names

    def test_large_project_keeps_design(self, adapter, workflow_config):
        result = adapter.adapt(
            workflow_config,
            {"size": "large", "risk_level": "high"},
        )
        stage_names = [s["name"] for s in result["workflow"]["stages"]]
        assert "design" in stage_names

    def test_all_stages_removed_raises(self, store, tmp_path):
        profile_file = tmp_path / "aggressive.yaml"
        profile_file.write_text(
            "name: aggressive\n"
            "rules:\n"
            "  - name: skip_all\n"
            "    action: skip\n"
            "    stage_name: only_stage\n"
            "    condition: \"{{ true }}\"\n"
            "enabled: true\n"
            "requires_approval: false\n"
        )
        registry = ProfileRegistry(config_dir=tmp_path, store=store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
        )
        config = {
            "workflow": {
                "lifecycle": {"enabled": True, "profile": "aggressive"},
                "stages": [{"name": "only_stage"}],
            }
        }
        with pytest.raises(ValueError, match="remove all stages"):
            adapter.adapt(config, {})

    @patch("src.lifecycle.adapter._check_emergency_stop", return_value=False)
    def test_emergency_stop_returns_original(self, mock_stop, adapter, workflow_config):
        result = adapter.adapt(workflow_config, {"size": "small", "risk_level": "low"})
        # Should return original (no adaptation)
        assert len(result["workflow"]["stages"]) == 4

    def test_autonomy_blocks_profile(self, config_dir, store):
        mock_manager = MagicMock()
        mock_manager.get_level.return_value = 0  # SUPERVISED
        registry = ProfileRegistry(config_dir=config_dir, store=store)
        # Make the profile require approval
        profile_file = config_dir / "lean.yaml"
        profile_file.write_text(
            "name: lean\n"
            "description: Lean\n"
            "rules:\n"
            "  - name: skip_design\n"
            "    action: skip\n"
            "    stage_name: design\n"
            "    condition: \"{{ true }}\"\n"
            "enabled: true\n"
            "requires_approval: true\n"
            "min_autonomy_level: 2\n"
        )
        registry = ProfileRegistry(config_dir=config_dir, store=store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
            autonomy_manager=mock_manager,
        )
        config = {
            "workflow": {
                "lifecycle": {"enabled": True, "profile": "lean"},
                "stages": [{"name": "design"}, {"name": "impl"}],
            }
        }
        result = adapter.adapt(config, {})
        # Should not adapt (autonomy blocked)
        assert len(result["workflow"]["stages"]) == 2

    def test_records_adaptation(self, adapter, store, workflow_config):
        adapter.adapt(
            workflow_config,
            {"size": "small", "risk_level": "low"},
        )
        records = store.list_adaptations()
        assert len(records) == 1
        assert records[0].profile_name == "lean"
