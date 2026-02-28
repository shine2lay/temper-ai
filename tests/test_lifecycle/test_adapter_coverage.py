"""Targeted tests for uncovered paths in lifecycle/adapter.py.

Covers lines: 103-111, 168, 182, 188, 210-225, 232-233, 251, 268-269,
              300-305, 359-360, 365-370, 409, 453-457
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.lifecycle._schemas import (
    AdaptationAction,
    AdaptationRule,
    LifecycleProfile,
    ProjectCharacteristics,
)
from temper_ai.lifecycle.adapter import (
    LifecycleAdapter,
    _apply_add,
    _apply_reorder,
    _apply_rules,
    _check_emergency_stop,
    _get_applied_rule_names,
)
from temper_ai.lifecycle.classifier import ProjectClassifier
from temper_ai.lifecycle.profiles import ProfileRegistry
from temper_ai.lifecycle.store import LifecycleStore

# ── Shared fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def store():
    return LifecycleStore(database_url="sqlite:///:memory:")


@pytest.fixture
def simple_config_dir(tmp_path):
    """Config dir with a lean profile that requires_approval=False."""
    profile_file = tmp_path / "lean.yaml"
    profile_file.write_text(
        "name: lean\n"
        "description: Lean profile\n"
        "rules:\n"
        "  - name: skip_design\n"
        "    action: skip\n"
        "    stage_name: design\n"
        "    condition: \"{{ size == 'small' }}\"\n"
        "    priority: 10\n"
        "enabled: true\n"
        "requires_approval: false\n"
        "source: manual\n"
    )
    return tmp_path


@pytest.fixture
def four_stage_config():
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


# ── Lines 103-111: experimenter path in _resolve_profile ──────────────────


class TestResolveProfileWithExperimenter:
    """Covers lines 102-111: experimenter.get_adapted_profile integration."""

    def test_experimenter_returns_adapted_profile(
        self, simple_config_dir, store, four_stage_config
    ):
        """Line 103-107, 111: experimenter returns a profile variant."""
        mock_experimenter = MagicMock()
        adapted_profile = LifecycleProfile(
            name="lean_variant",
            rules=[
                AdaptationRule(
                    name="skip_design",
                    action=AdaptationAction.SKIP,
                    stage_name="design",
                    condition="{{ true }}",
                )
            ],
            requires_approval=False,
        )
        mock_experimenter.get_adapted_profile.return_value = adapted_profile

        registry = ProfileRegistry(config_dir=simple_config_dir, store=store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
            store=store,
            experimenter=mock_experimenter,
        )

        config = {
            "workflow": {
                "name": "exp_wf",
                "lifecycle": {
                    "enabled": True,
                    "profile": "lean",
                    "experiment_id": "exp-001",
                },
                "stages": [
                    {"name": "design"},
                    {"name": "implement"},
                    {"name": "test"},
                ],
            }
        }

        result = adapter.adapt(config, {"size": "small", "risk_level": "low"})
        stage_names = [s["name"] for s in result["workflow"]["stages"]]
        assert "design" not in stage_names
        mock_experimenter.get_adapted_profile.assert_called_once()

    def test_experimenter_returns_none_control_group(self, simple_config_dir, store):
        """Lines 108-110: experimenter returns None → no adaptation (control group)."""
        mock_experimenter = MagicMock()
        mock_experimenter.get_adapted_profile.return_value = None

        registry = ProfileRegistry(config_dir=simple_config_dir, store=store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
            experimenter=mock_experimenter,
        )

        config = {
            "workflow": {
                "name": "exp_wf",
                "lifecycle": {
                    "enabled": True,
                    "profile": "lean",
                    "experiment_id": "exp-002",
                },
                "stages": [
                    {"name": "design"},
                    {"name": "implement"},
                ],
            }
        }

        result = adapter.adapt(config, {})
        # Control group: no adaptation, stages unchanged
        assert len(result["workflow"]["stages"]) == 2

    def test_experimenter_called_with_workflow_id(self, simple_config_dir, store):
        """Line 105: workflow_id passed to experimenter."""
        mock_experimenter = MagicMock()
        mock_experimenter.get_adapted_profile.return_value = None

        registry = ProfileRegistry(config_dir=simple_config_dir, store=store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
            experimenter=mock_experimenter,
        )

        config = {
            "workflow": {
                "lifecycle": {
                    "profile": "lean",
                    "experiment_id": "exp-003",
                },
                "stages": [{"name": "s1"}, {"name": "s2"}],
            }
        }

        adapter.adapt(config, {}, workflow_id="explicit-wf-id")
        call_args = mock_experimenter.get_adapted_profile.call_args
        assert call_args[0][1] == "explicit-wf-id"

    def test_experimenter_called_with_empty_workflow_id_when_none(
        self, simple_config_dir, store
    ):
        """Line 105: workflow_id or '' when workflow_id is None."""
        mock_experimenter = MagicMock()
        mock_experimenter.get_adapted_profile.return_value = None

        registry = ProfileRegistry(config_dir=simple_config_dir, store=store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
            experimenter=mock_experimenter,
        )

        config = {
            "workflow": {
                "lifecycle": {
                    "profile": "lean",
                    "experiment_id": "exp-004",
                },
                "stages": [{"name": "s1"}, {"name": "s2"}],
            }
        }

        adapter.adapt(config, {}, workflow_id=None)
        call_args = mock_experimenter.get_adapted_profile.call_args
        # workflow_id=None → or "" = ""
        assert call_args[0][1] == ""


# ── Line 168: auto_classify=False returns empty ProjectCharacteristics ─────


class TestClassifyAutoClassifyFalse:
    """Covers line 168: auto_classify=False path in _classify."""

    def test_auto_classify_false_returns_defaults(self, simple_config_dir, store):
        """Line 168: When auto_classify=False, skip classifier, return defaults."""
        registry = ProfileRegistry(config_dir=simple_config_dir, store=store)
        mock_classifier = MagicMock()
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=mock_classifier,
        )

        config = {
            "workflow": {
                "lifecycle": {
                    "profile": "lean",
                    "auto_classify": False,
                },
                "stages": [{"name": "s1"}, {"name": "s2"}],
            }
        }

        adapter.adapt(config, {"size": "small", "risk_level": "low"})
        # Classifier should NOT be called when auto_classify=False
        mock_classifier.classify.assert_not_called()


# ── Line 182: _select_profile warns when named profile not found ───────────


class TestSelectProfileNotFound:
    """Covers line 182: warning when named profile is not in registry."""

    def test_named_profile_not_found_logs_warning(self, store):
        """Lines 181-183: registry.get_profile returns None → warning logged."""
        registry = ProfileRegistry(config_dir=Path("/nonexistent"), store=store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
        )

        config = {
            "workflow": {
                "lifecycle": {"profile": "nonexistent_profile"},
                "stages": [{"name": "s1"}, {"name": "s2"}],
            }
        }

        with patch("temper_ai.lifecycle.adapter.logger") as mock_logger:
            result = adapter.adapt(config, {})
            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "Named profile not found" in warning_msg

        # No adaptation applied
        assert len(result["workflow"]["stages"]) == 2


# ── Line 188: auto-match returns first profile ─────────────────────────────


class TestSelectProfileAutoMatch:
    """Covers line 188: auto-match returns matched[0]."""

    def test_auto_match_selects_first_profile(self, store, tmp_path):
        """Lines 186-188: when no explicit profile, use auto-match result."""
        profile_file = tmp_path / "auto.yaml"
        profile_file.write_text(
            "name: auto_match\n"
            "rules:\n"
            "  - name: skip_x\n"
            "    action: skip\n"
            "    stage_name: x\n"
            '    condition: "{{ true }}"\n'
            "enabled: true\n"
            "requires_approval: false\n"
        )
        registry = ProfileRegistry(config_dir=tmp_path, store=store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
            store=store,
        )

        # No explicit profile in lifecycle config
        config = {
            "workflow": {
                "name": "auto_wf",
                "lifecycle": {"enabled": True},
                "stages": [{"name": "x"}, {"name": "y"}],
            }
        }

        result = adapter.adapt(config, {})
        stage_names = [s["name"] for s in result["workflow"]["stages"]]
        assert "x" not in stage_names
        assert "y" in stage_names


# ── Lines 210-225: _check_autonomy with autonomy_manager ──────────────────


class TestCheckAutonomyWithManager:
    """Covers lines 210-225: autonomy_manager integration in _check_autonomy."""

    def _make_adapter(
        self, config_dir, store, autonomy_manager, profile_overrides=None
    ):
        profile_file = config_dir / "lean.yaml"
        overrides = {
            "name": "lean",
            "rules": (
                "  - name: skip_design\n"
                "    action: skip\n"
                "    stage_name: design\n"
                '    condition: "{{ true }}"\n'
            ),
            "requires_approval": "false",
            "min_autonomy_level": 0,
            "source": "manual",
        }
        if profile_overrides:
            overrides.update(profile_overrides)
        profile_file.write_text(
            f"name: {overrides['name']}\n"
            "rules:\n"
            f"{overrides['rules']}"
            "enabled: true\n"
            f"requires_approval: {overrides['requires_approval']}\n"
            f"min_autonomy_level: {overrides['min_autonomy_level']}\n"
            f"source: {overrides['source']}\n"
        )
        registry = ProfileRegistry(config_dir=config_dir, store=store)
        return LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
            autonomy_manager=autonomy_manager,
        )

    def test_critical_risk_requires_strategic_level_blocked(self, store, tmp_path):
        """Lines 212-214: CRITICAL risk requires level>=4 — blocked at level 3."""
        mock_manager = MagicMock()
        mock_manager.get_level.return_value = 3  # Below STRATEGIC(4)

        adapter = self._make_adapter(tmp_path, store, mock_manager)

        config = {
            "workflow": {
                "lifecycle": {"profile": "lean"},
                "stages": [{"name": "design"}, {"name": "impl"}],
            }
        }
        # CRITICAL risk with level 3 should block adaptation
        result = adapter.adapt(config, {"risk_level": "critical"})
        assert len(result["workflow"]["stages"]) == 2  # No adaptation

    def test_critical_risk_allowed_at_strategic_level(self, store, tmp_path):
        """Lines 212-214: CRITICAL risk passes at level>=4."""
        mock_manager = MagicMock()
        mock_manager.get_level.return_value = 4  # STRATEGIC

        adapter = self._make_adapter(tmp_path, store, mock_manager)

        config = {
            "workflow": {
                "lifecycle": {"profile": "lean"},
                "stages": [{"name": "design"}, {"name": "impl"}],
            }
        }
        result = adapter.adapt(config, {"risk_level": "critical"})
        # Adaptation applied (design removed)
        stage_names = [s["name"] for s in result["workflow"]["stages"]]
        assert "design" not in stage_names

    def test_non_manual_source_requires_risk_gated(self, store, tmp_path):
        """Lines 215-217: non-manual source requires level>=2."""
        mock_manager = MagicMock()
        mock_manager.get_level.return_value = 1  # Below RISK_GATED(2)

        # Profile with source=learned
        profile_overrides = {"source": "learned", "min_autonomy_level": 0}
        adapter = self._make_adapter(tmp_path, store, mock_manager, profile_overrides)

        config = {
            "workflow": {
                "lifecycle": {"profile": "lean"},
                "stages": [{"name": "design"}, {"name": "impl"}],
            }
        }
        result = adapter.adapt(config, {})
        assert len(result["workflow"]["stages"]) == 2  # Blocked

    def test_non_manual_source_allowed_at_risk_gated(self, store, tmp_path):
        """Lines 215-217: non-manual source passes at level>=2."""
        mock_manager = MagicMock()
        mock_manager.get_level.return_value = 2  # RISK_GATED

        profile_overrides = {"source": "learned", "min_autonomy_level": 0}
        adapter = self._make_adapter(tmp_path, store, mock_manager, profile_overrides)

        config = {
            "workflow": {
                "lifecycle": {"profile": "lean"},
                "stages": [{"name": "design"}, {"name": "impl"}],
            }
        }
        result = adapter.adapt(config, {})
        stage_names = [s["name"] for s in result["workflow"]["stages"]]
        assert "design" not in stage_names

    def test_min_autonomy_level_not_met_blocks(self, store, tmp_path):
        """Lines 206-207: min_autonomy_level check fails."""
        mock_manager = MagicMock()
        mock_manager.get_level.return_value = 1

        profile_overrides = {"min_autonomy_level": 3, "requires_approval": "true"}
        adapter = self._make_adapter(tmp_path, store, mock_manager, profile_overrides)

        config = {
            "workflow": {
                "lifecycle": {"profile": "lean"},
                "stages": [{"name": "design"}, {"name": "impl"}],
            }
        }
        result = adapter.adapt(config, {})
        assert len(result["workflow"]["stages"]) == 2  # Blocked

    def test_autonomy_manager_exception_falls_back(self, store, tmp_path):
        """Lines 220-225: autonomy_manager raises → fallback to requires_approval."""
        mock_manager = MagicMock()
        mock_manager.get_level.side_effect = RuntimeError("manager error")

        # Profile with requires_approval=False → fallback allows it
        adapter = self._make_adapter(tmp_path, store, mock_manager)

        config = {
            "workflow": {
                "lifecycle": {"profile": "lean"},
                "stages": [{"name": "design"}, {"name": "impl"}],
            }
        }
        result = adapter.adapt(config, {})
        # requires_approval=false → not profile.requires_approval → True → allow
        stage_names = [s["name"] for s in result["workflow"]["stages"]]
        assert "design" not in stage_names

    def test_autonomy_manager_exception_blocks_requires_approval_profile(
        self, store, tmp_path
    ):
        """Lines 220-225: exception + requires_approval=True → blocked."""
        mock_manager = MagicMock()
        mock_manager.get_level.side_effect = RuntimeError("manager error")

        profile_overrides = {"requires_approval": "true"}
        adapter = self._make_adapter(tmp_path, store, mock_manager, profile_overrides)

        config = {
            "workflow": {
                "lifecycle": {"profile": "lean"},
                "stages": [{"name": "design"}, {"name": "impl"}],
            }
        }
        result = adapter.adapt(config, {})
        assert len(result["workflow"]["stages"]) == 2  # Blocked (requires approval)

    def test_manual_source_returns_true_regardless(self, store, tmp_path):
        """Line 219: manual source passes all gates at sufficient level."""
        mock_manager = MagicMock()
        mock_manager.get_level.return_value = 5

        adapter = self._make_adapter(tmp_path, store, mock_manager)

        config = {
            "workflow": {
                "lifecycle": {"profile": "lean"},
                "stages": [{"name": "design"}, {"name": "impl"}],
            }
        }
        result = adapter.adapt(config, {})
        stage_names = [s["name"] for s in result["workflow"]["stages"]]
        assert "design" not in stage_names


# ── Lines 232-233: _get_history_context with history analyzer ─────────────


class TestGetHistoryContext:
    """Covers lines 232-233: history analyzer integration."""

    def test_history_context_populated_from_analyzer(self, simple_config_dir, store):
        """Lines 232-233: when history_analyzer set, context includes history data."""
        mock_history = MagicMock()
        from temper_ai.lifecycle._schemas import StageMetrics

        mock_history.get_stage_metrics.return_value = {
            "design": StageMetrics(
                stage_name="design",
                avg_duration=10.5,
                success_rate=0.9,
                run_count=50,
            )
        }

        registry = ProfileRegistry(config_dir=simple_config_dir, store=store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
            history_analyzer=mock_history,
        )

        config = {
            "workflow": {
                "name": "hist_wf",
                "lifecycle": {"profile": "lean"},
                "stages": [{"name": "design"}, {"name": "impl"}],
            }
        }

        adapter.adapt(config, {})
        mock_history.get_stage_metrics.assert_called_once_with("hist_wf")

    def test_history_none_returns_empty_context(self, simple_config_dir, store):
        """Line 229-230: history=None → empty context dict."""
        registry = ProfileRegistry(config_dir=simple_config_dir, store=store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
            history_analyzer=None,
        )

        config = {
            "workflow": {
                "name": "no_hist_wf",
                "lifecycle": {"profile": "lean"},
                "stages": [{"name": "design"}, {"name": "impl"}],
            }
        }

        # Should complete without error
        result = adapter.adapt(config, {})
        assert result is not None


# ── Line 251: _record_adaptation with store (experiment fields) ───────────


class TestRecordAdaptationWithExperiment:
    """Covers line 251: store.save_adaptation called with experiment fields."""

    def test_record_stores_experiment_id_and_variant(self, simple_config_dir, store):
        """Lines 251, 263-264: experiment_id and variant saved in adaptation record."""
        registry = ProfileRegistry(config_dir=simple_config_dir, store=store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
            store=store,
        )

        config = {
            "workflow": {
                "name": "record_wf",
                "lifecycle": {
                    "profile": "lean",
                    "experiment_id": "exp-xyz",
                    "experiment_variant": "variant_b",
                },
                "stages": [
                    {"name": "design"},
                    {"name": "impl"},
                    {"name": "test"},
                ],
            }
        }

        adapter.adapt(config, {"size": "small", "risk_level": "low"})
        records = store.list_adaptations()
        assert len(records) == 1
        assert records[0].experiment_id == "exp-xyz"
        assert records[0].experiment_variant == "variant_b"


# ── Lines 268-269: _record_adaptation store exception swallowed ────────────


class TestRecordAdaptationStoreFailure:
    """Covers lines 268-269: exception during save_adaptation is swallowed."""

    def test_store_save_failure_does_not_raise(self, simple_config_dir):
        """Lines 268-269: BLE001 catch — store failure is non-fatal."""
        mock_store = MagicMock()
        mock_store.save_adaptation.side_effect = RuntimeError("DB failure")

        registry = ProfileRegistry(config_dir=simple_config_dir, store=mock_store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
            store=mock_store,
        )

        config = {
            "workflow": {
                "lifecycle": {"profile": "lean"},
                "stages": [{"name": "design"}, {"name": "impl"}],
            }
        }

        # Should not raise even though store fails
        result = adapter.adapt(config, {})
        assert result is not None
        mock_store.save_adaptation.assert_called_once()


# ── Lines 300-305: _apply_rules with ADD, REORDER, MODIFY actions ─────────


class TestApplyRulesAllActions:
    """Covers lines 300-305: ADD, REORDER, MODIFY dispatch in _apply_rules."""

    def test_add_action_dispatched(self):
        """Line 301: ADD action path in _apply_rules."""
        stages = [{"name": "a"}, {"name": "b"}]
        rules = [
            AdaptationRule(
                name="add_c",
                action=AdaptationAction.ADD,
                stage_name="c",
                condition="{{ true }}",
                stage_ref="c.yaml",
            )
        ]
        chars = ProjectCharacteristics()
        result = _apply_rules(stages, rules, chars, {})
        assert len(result) == 3
        assert result[-1]["name"] == "c"

    def test_reorder_action_dispatched(self):
        """Line 303: REORDER action path in _apply_rules."""
        stages = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        rules = [
            AdaptationRule(
                name="reorder_c",
                action=AdaptationAction.REORDER,
                stage_name="c",
                condition="{{ true }}",
                move_before="a",
            )
        ]
        chars = ProjectCharacteristics()
        result = _apply_rules(stages, rules, chars, {})
        assert result[0]["name"] == "c"

    def test_modify_action_dispatched(self):
        """Line 305: MODIFY action path in _apply_rules."""
        stages = [{"name": "a", "timeout": 30}]
        rules = [
            AdaptationRule(
                name="mod_a",
                action=AdaptationAction.MODIFY,
                stage_name="a",
                condition="{{ true }}",
                modifications={"timeout": 90},
            )
        ]
        chars = ProjectCharacteristics()
        result = _apply_rules(stages, rules, chars, {})
        assert result[0]["timeout"] == 90


# ── Lines 359-360, 365-370: _apply_add insert_after/before not found ──────


class TestApplyAddPositionNotFound:
    """Covers lines 359-360, 365-370: insert_after/before targets not in list."""

    def test_insert_after_target_not_found_appends(self):
        """Lines 359-360 (branch): insert_after target not found → append."""
        stages = [{"name": "a"}, {"name": "b"}]
        rule = AdaptationRule(
            name="r",
            action=AdaptationAction.ADD,
            stage_name="new",
            condition="{{ true }}",
            stage_ref="new.yaml",
            insert_after="nonexistent",
        )
        result = _apply_add(stages, rule)
        assert len(result) == 3
        # Appended to end because target not found
        assert result[-1]["name"] == "new"

    def test_insert_before_target_not_found_appends(self):
        """Lines 365-370 (branch): insert_before target not found → append."""
        stages = [{"name": "a"}, {"name": "b"}]
        rule = AdaptationRule(
            name="r",
            action=AdaptationAction.ADD,
            stage_name="new",
            condition="{{ true }}",
            stage_ref="new.yaml",
            insert_before="nonexistent",
        )
        result = _apply_add(stages, rule)
        assert len(result) == 3
        assert result[-1]["name"] == "new"

    def test_insert_after_found_sets_correct_index(self):
        """Lines 359-362: insert_after found at index i → inserted at i+1."""
        stages = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        rule = AdaptationRule(
            name="r",
            action=AdaptationAction.ADD,
            stage_name="new",
            condition="{{ true }}",
            stage_ref="new.yaml",
            insert_after="b",
        )
        result = _apply_add(stages, rule)
        # Should be: a, b, new, c
        assert result[2]["name"] == "new"


# ── Line 409: _apply_reorder move_before fallback ─────────────────────────


class TestApplyReorderMoveBeforeFallback:
    """Covers line 409: _apply_reorder move_before fallback when move_after not found."""

    def test_move_after_not_found_falls_back_to_move_before(self):
        """Lines 403-409: move_after not found → try move_before."""
        stages = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        rule = AdaptationRule(
            name="r",
            action=AdaptationAction.REORDER,
            stage_name="c",
            condition="{{ true }}",
            move_after="nonexistent",
            move_before="b",
        )
        result = _apply_reorder(stages, rule)
        names = [s["name"] for s in result]
        # c should be before b
        assert names.index("c") < names.index("b")

    def test_both_targets_not_found_appends_to_end(self):
        """Lines 408-409: neither move_after nor move_before found → append."""
        stages = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        rule = AdaptationRule(
            name="r",
            action=AdaptationAction.REORDER,
            stage_name="a",
            condition="{{ true }}",
            move_after="nonexistent1",
            move_before="nonexistent2",
        )
        result = _apply_reorder(stages, rule)
        names = [s["name"] for s in result]
        assert names[-1] == "a"


# ── Lines 453-457: _check_emergency_stop exception handling ───────────────


class TestCheckEmergencyStop:
    """Covers lines 453-457: exception handling in _check_emergency_stop."""

    def test_emergency_stop_returns_true_on_import_error(self):
        """Line 453-454: ImportError → return True (proceed)."""
        with patch.dict(
            "sys.modules", {"temper_ai.safety.autonomy.emergency_stop": None}
        ):
            result = _check_emergency_stop()
            assert result is True

    def test_emergency_stop_returns_true_on_controller_exception(self):
        """Lines 455-457: controller raises exception → return True."""
        mock_controller = MagicMock()
        mock_controller.is_active.side_effect = RuntimeError("controller error")

        with patch(
            "temper_ai.lifecycle.adapter._check_emergency_stop",
            wraps=_check_emergency_stop,
        ):
            with patch(
                "temper_ai.safety.autonomy.emergency_stop.EmergencyStopController",
                return_value=mock_controller,
            ):
                # Trigger via a fresh import context
                import importlib

                import temper_ai.lifecycle.adapter as adapter_mod

                importlib.reload(adapter_mod)
                # Patch the controller inside the reloaded module
                with patch.object(
                    mock_controller, "is_active", side_effect=RuntimeError("err")
                ):
                    result = adapter_mod._check_emergency_stop()
                    # Should return True on exception
                    assert result is True

    def test_emergency_stop_false_when_active(self):
        """Lines 451-452: controller.is_active() → True → returns False."""
        mock_controller = MagicMock()
        mock_controller.is_active.return_value = True

        with patch(
            "temper_ai.safety.autonomy.emergency_stop.EmergencyStopController",
            return_value=mock_controller,
        ):
            import importlib

            import temper_ai.lifecycle.adapter as adapter_mod

            importlib.reload(adapter_mod)
            result = adapter_mod._check_emergency_stop()
            assert result is False

    def test_emergency_stop_true_when_not_active(self):
        """Lines 451-452: controller.is_active() → False → returns True."""
        mock_controller = MagicMock()
        mock_controller.is_active.return_value = False

        with patch(
            "temper_ai.safety.autonomy.emergency_stop.EmergencyStopController",
            return_value=mock_controller,
        ):
            import importlib

            import temper_ai.lifecycle.adapter as adapter_mod

            importlib.reload(adapter_mod)
            result = adapter_mod._check_emergency_stop()
            assert result is True


# ── _get_applied_rule_names: same names returns [] ────────────────────────


class TestGetAppliedRuleNames:
    """Covers the no-change branch in _get_applied_rule_names."""

    def test_same_names_returns_empty(self):
        """Line 439-440: original == adapted → empty list."""
        rules = [
            AdaptationRule(
                name="r1",
                action=AdaptationAction.SKIP,
                stage_name="x",
                condition="{{ true }}",
            )
        ]
        result = _get_applied_rule_names(rules, ["a", "b"], ["a", "b"])
        assert result == []

    def test_different_names_returns_rule_names(self):
        """Line 441: original != adapted → rule names list."""
        rules = [
            AdaptationRule(
                name="skip_b",
                action=AdaptationAction.SKIP,
                stage_name="b",
                condition="{{ true }}",
            )
        ]
        result = _get_applied_rule_names(rules, ["a", "b"], ["a"])
        assert result == ["skip_b"]
