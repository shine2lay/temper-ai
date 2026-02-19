"""Integration tests for lifecycle module."""

from pathlib import Path

import pytest

from temper_ai.lifecycle._schemas import (
    AdaptationAction,
    AdaptationRule,
    LifecycleProfile,
    ProjectCharacteristics,
    ProjectSize,
    RiskLevel,
)
from temper_ai.lifecycle.adapter import LifecycleAdapter, _apply_rules
from temper_ai.lifecycle.classifier import ProjectClassifier
from temper_ai.lifecycle.profiles import ProfileRegistry
from temper_ai.lifecycle.store import LifecycleStore


@pytest.fixture
def store():
    return LifecycleStore(database_url="sqlite:///:memory:")


@pytest.fixture
def full_workflow_config():
    return {
        "workflow": {
            "name": "integration_test",
            "lifecycle": {"enabled": True, "profile": "lean"},
            "stages": [
                {"name": "triage", "stage_ref": "stages/triage.yaml"},
                {"name": "design", "stage_ref": "stages/design.yaml"},
                {"name": "implement", "stage_ref": "stages/impl.yaml"},
                {"name": "security_review", "stage_ref": "stages/security.yaml"},
                {"name": "test", "stage_ref": "stages/test.yaml"},
            ],
        }
    }


class TestEndToEnd:
    """End-to-end integration tests."""

    def test_small_low_risk_project(self, tmp_path, store, full_workflow_config):
        """Small low-risk project skips design and security review."""
        profile_file = tmp_path / "lean.yaml"
        profile_file.write_text(
            "name: lean\n"
            "description: Lean\n"
            "rules:\n"
            "  - name: skip_design\n"
            "    action: skip\n"
            "    stage_name: design\n"
            "    condition: \"{{ size == 'small' and risk_level in ['low', 'medium'] }}\"\n"
            "    priority: 10\n"
            "  - name: skip_security_low\n"
            "    action: skip\n"
            "    stage_name: security_review\n"
            "    condition: \"{{ risk_level == 'low' }}\"\n"
            "    priority: 5\n"
            "enabled: true\n"
            "requires_approval: false\n"
        )
        registry = ProfileRegistry(config_dir=tmp_path, store=store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
            store=store,
        )

        result = adapter.adapt(
            full_workflow_config,
            {"size": "small", "risk_level": "low"},
        )
        names = [s["name"] for s in result["workflow"]["stages"]]
        assert "design" not in names
        assert "security_review" not in names
        assert "triage" in names
        assert "implement" in names
        assert "test" in names

    def test_large_critical_project_unchanged(self, tmp_path, store, full_workflow_config):
        """Large critical project should NOT have stages skipped by lean profile."""
        profile_file = tmp_path / "lean.yaml"
        profile_file.write_text(
            "name: lean\n"
            "description: Lean\n"
            "rules:\n"
            "  - name: skip_design\n"
            "    action: skip\n"
            "    stage_name: design\n"
            "    condition: \"{{ size == 'small' }}\"\n"
            "enabled: true\n"
            "requires_approval: false\n"
        )
        registry = ProfileRegistry(config_dir=tmp_path, store=store)
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=ProjectClassifier(),
            store=store,
        )

        result = adapter.adapt(
            full_workflow_config,
            {"size": "large", "risk_level": "critical"},
        )
        names = [s["name"] for s in result["workflow"]["stages"]]
        assert len(names) == 5  # All stages preserved

    def test_lifecycle_config_schema_integration(self):
        """LifecycleConfig integrates with WorkflowConfigInner."""
        from temper_ai.workflow._schemas import WorkflowConfigInner

        # Should accept lifecycle field
        config = WorkflowConfigInner(
            name="test",
            description="test",
            stages=[{"name": "s1", "stage_ref": "stages/s1.yaml"}],
            error_handling={
                "on_stage_failure": "halt",
                "escalation_policy": "temper_ai.safety.stub",
            },
            lifecycle={"enabled": True, "profile": "lean"},
        )
        assert config.lifecycle.enabled is True
        assert config.lifecycle.profile == "lean"

    def test_lifecycle_config_defaults(self):
        """LifecycleConfig defaults to disabled."""
        from temper_ai.workflow._schemas import WorkflowConfigInner

        config = WorkflowConfigInner(
            name="test",
            description="test",
            stages=[{"name": "s1", "stage_ref": "stages/s1.yaml"}],
            error_handling={
                "on_stage_failure": "halt",
                "escalation_policy": "temper_ai.safety.stub",
            },
        )
        assert config.lifecycle.enabled is False
