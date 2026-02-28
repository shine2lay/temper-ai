"""Tests for temper_ai/stage/_config_accessors.py.

Covers all accessor functions with Pydantic, nested dict, flat dict, and fallback cases.
"""

from temper_ai.stage._config_accessors import (
    get_collaboration,
    get_collaboration_inner_config,
    get_convergence,
    get_error_handling,
    get_execution_config,
    get_quality_gates,
    get_stage_agents,
    get_wall_clock_timeout,
    stage_config_to_dict,
)
from temper_ai.stage._schemas import (
    CollaborationConfig,
    StageConfig,
    StageConfigInner,
    StageErrorHandlingConfig,
    StageExecutionConfig,
)


def _make_pydantic_config(**overrides):
    """Create a StageConfig with optional overrides."""
    inner_kwargs = {
        "name": "test",
        "description": "desc",
        "agents": ["a1", "a2"],
    }
    inner_kwargs.update(overrides)
    return StageConfig(stage=StageConfigInner(**inner_kwargs))


class TestGetStageAgents:
    """Tests for get_stage_agents."""

    def test_pydantic_config(self):
        config = _make_pydantic_config()
        assert get_stage_agents(config) == ["a1", "a2"]

    def test_nested_dict(self):
        config = {"stage": {"agents": ["x", "y"]}}
        assert get_stage_agents(config) == ["x", "y"]

    def test_flat_dict(self):
        config = {"agents": ["z"]}
        assert get_stage_agents(config) == ["z"]

    def test_non_dict_returns_empty(self):
        assert get_stage_agents("not a config") == []

    def test_empty_dict_returns_empty(self):
        assert get_stage_agents({}) == []


class TestGetErrorHandling:
    """Tests for get_error_handling."""

    def test_pydantic_with_error_handling(self):
        config = _make_pydantic_config(
            error_handling=StageErrorHandlingConfig(on_agent_failure="skip_agent")
        )
        eh = get_error_handling(config)
        assert eh.on_agent_failure == "skip_agent"

    def test_pydantic_default_fallback(self):
        config = _make_pydantic_config()
        eh = get_error_handling(config)
        # Default when error_handling is present should be the model default
        assert isinstance(eh, StageErrorHandlingConfig)

    def test_dict_config(self):
        config = {"stage": {"error_handling": {"on_agent_failure": "halt_stage"}}}
        eh = get_error_handling(config)
        assert eh.on_agent_failure == "halt_stage"

    def test_missing_returns_default(self):
        eh = get_error_handling({})
        assert eh.on_agent_failure == "halt_stage"

    def test_non_dict_returns_default(self):
        eh = get_error_handling(42)
        assert isinstance(eh, StageErrorHandlingConfig)


class TestGetExecutionConfig:
    """Tests for get_execution_config."""

    def test_pydantic_config(self):
        config = _make_pydantic_config(
            execution=StageExecutionConfig(agent_mode="sequential", timeout_seconds=60)
        )
        result = get_execution_config(config)
        assert result["agent_mode"] == "sequential"
        assert result["timeout_seconds"] == 60

    def test_dict_config(self):
        config = {
            "stage": {"execution": {"agent_mode": "parallel", "timeout_seconds": 300}}
        }
        result = get_execution_config(config)
        assert result["agent_mode"] == "parallel"

    def test_empty_returns_empty_dict(self):
        assert get_execution_config({}) == {}

    def test_non_dict_returns_empty_dict(self):
        assert get_execution_config("invalid") == {}


class TestGetCollaboration:
    """Tests for get_collaboration."""

    def test_pydantic_config_with_collab(self):
        config = _make_pydantic_config(
            collaboration=CollaborationConfig(strategy="debate")
        )
        collab = get_collaboration(config)
        assert collab is not None
        assert collab.strategy == "debate"

    def test_pydantic_config_without_collab(self):
        config = _make_pydantic_config()
        assert get_collaboration(config) is None

    def test_dict_config(self):
        config = {"stage": {"collaboration": {"strategy": "vote"}}}
        collab = get_collaboration(config)
        assert collab["strategy"] == "vote"

    def test_non_dict_returns_none(self):
        assert get_collaboration(42) is None


class TestGetCollaborationInnerConfig:
    """Tests for get_collaboration_inner_config."""

    def test_nested_dict(self):
        config = {"stage": {"collaboration": {"config": {"key": "val"}}}}
        result = get_collaboration_inner_config(config)
        assert result == {"key": "val"}

    def test_flat_dict(self):
        config = {"collaboration": {"config": {"x": 1}}}
        result = get_collaboration_inner_config(config)
        assert result == {"x": 1}

    def test_missing_returns_empty(self):
        assert get_collaboration_inner_config({}) == {}

    def test_non_dict_returns_empty(self):
        assert get_collaboration_inner_config("nope") == {}


class TestGetConvergence:
    """Tests for get_convergence."""

    def test_pydantic_config(self):
        from temper_ai.stage._schemas import ConvergenceConfig

        config = _make_pydantic_config(convergence=ConvergenceConfig(enabled=True))
        conv = get_convergence(config)
        assert conv is not None
        assert conv.enabled is True

    def test_none_when_missing(self):
        config = _make_pydantic_config()
        assert get_convergence(config) is None

    def test_dict_config(self):
        config = {"stage": {"convergence": {"enabled": True}}}
        assert get_convergence(config)["enabled"] is True


class TestGetQualityGates:
    """Tests for get_quality_gates."""

    def test_dict_config(self):
        config = {"quality_gates": {"enabled": True, "min_confidence": 0.8}}
        result = get_quality_gates(config)
        assert result["enabled"] is True

    def test_empty_returns_empty(self):
        assert get_quality_gates({}) == {}

    def test_non_dict_returns_empty(self):
        assert get_quality_gates("invalid") == {}


class TestGetWallClockTimeout:
    """Tests for get_wall_clock_timeout."""

    def test_pydantic_config(self):
        config = _make_pydantic_config(
            execution=StageExecutionConfig(timeout_seconds=120)
        )
        assert get_wall_clock_timeout(config) == 120.0

    def test_dict_config(self):
        config = {"stage": {"execution": {"timeout_seconds": 300}}}
        assert get_wall_clock_timeout(config) == 300.0

    def test_default_fallback(self):
        from temper_ai.shared.constants.durations import SECONDS_PER_30_MINUTES

        assert get_wall_clock_timeout({}) == float(SECONDS_PER_30_MINUTES)

    def test_non_dict_default(self):
        from temper_ai.shared.constants.durations import SECONDS_PER_30_MINUTES

        assert get_wall_clock_timeout(42) == float(SECONDS_PER_30_MINUTES)


class TestStageConfigToDict:
    """Tests for stage_config_to_dict."""

    def test_pydantic_model_dump(self):
        config = _make_pydantic_config()
        result = stage_config_to_dict(config)
        assert isinstance(result, dict)
        assert "stage" in result

    def test_dict_passthrough(self):
        config = {"stage": {"name": "test"}}
        assert stage_config_to_dict(config) == config

    def test_non_dict_returns_empty(self):
        assert stage_config_to_dict(42) == {}
