"""Tests for autonomy schemas."""

import pytest

from src.safety.autonomy.schemas import AutonomyConfig, AutonomyLevel


class TestAutonomyLevel:
    """Tests for AutonomyLevel enum."""

    def test_ordering(self) -> None:
        """Levels should be ordered from most to least supervised."""
        assert AutonomyLevel.SUPERVISED < AutonomyLevel.SPOT_CHECKED
        assert AutonomyLevel.SPOT_CHECKED < AutonomyLevel.RISK_GATED
        assert AutonomyLevel.RISK_GATED < AutonomyLevel.AUTONOMOUS
        assert AutonomyLevel.AUTONOMOUS < AutonomyLevel.STRATEGIC

    def test_values(self) -> None:
        """Levels have sequential integer values."""
        assert AutonomyLevel.SUPERVISED == 0
        assert AutonomyLevel.STRATEGIC == 4

    def test_from_int(self) -> None:
        """Can create level from integer."""
        assert AutonomyLevel(0) == AutonomyLevel.SUPERVISED
        assert AutonomyLevel(4) == AutonomyLevel.STRATEGIC

    def test_invalid_value(self) -> None:
        """Invalid integer raises ValueError."""
        with pytest.raises(ValueError):
            AutonomyLevel(99)


class TestAutonomyConfig:
    """Tests for AutonomyConfig model."""

    def test_defaults(self) -> None:
        """Default config is disabled and supervised."""
        cfg = AutonomyConfig()
        assert cfg.enabled is False
        assert cfg.level == AutonomyLevel.SUPERVISED
        assert cfg.allow_escalation is True
        assert cfg.max_level == AutonomyLevel.RISK_GATED
        assert cfg.shadow_mode is True
        assert cfg.budget_usd is None
        assert cfg.spot_check_rate == 0.10

    def test_enabled(self) -> None:
        """Can enable autonomy."""
        cfg = AutonomyConfig(enabled=True, level=AutonomyLevel.SPOT_CHECKED)
        assert cfg.enabled is True
        assert cfg.level == AutonomyLevel.SPOT_CHECKED

    def test_budget(self) -> None:
        """Can set budget."""
        cfg = AutonomyConfig(budget_usd=50.0)
        assert cfg.budget_usd == 50.0

    def test_spot_check_rate_validation(self) -> None:
        """Spot check rate must be 0-1."""
        with pytest.raises(ValueError):
            AutonomyConfig(spot_check_rate=1.5)
        with pytest.raises(ValueError):
            AutonomyConfig(spot_check_rate=-0.1)

    def test_backward_compat_agent_config(self) -> None:
        """AgentConfigInner works without autonomy key."""
        from src.storage.schemas.agent_config import AgentConfigInner

        config = AgentConfigInner(
            name="test",
            description="test agent",
            prompt={"inline": "test prompt"},
            inference={"provider": "ollama", "model": "test"},
            error_handling={},
        )
        assert config.autonomy is None

    def test_agent_config_with_autonomy(self) -> None:
        """AgentConfigInner parses autonomy dict."""
        from src.storage.schemas.agent_config import AgentConfigInner

        config = AgentConfigInner(
            name="test",
            description="test agent",
            prompt={"inline": "test prompt"},
            inference={"provider": "ollama", "model": "test"},
            error_handling={},
            autonomy={"enabled": True, "level": 1},
        )
        assert config.autonomy is not None
        assert config.autonomy.enabled is True
        assert config.autonomy.level == AutonomyLevel.SPOT_CHECKED
