"""Stage config accessor functions.

Encapsulates dual-path config access (Pydantic StageConfig vs dict)
into single-call accessors, replacing ~20 inline branches scattered
across executor files.

Each accessor handles three formats:
1. Pydantic StageConfig (hasattr stage_config, 'stage')
2. Nested dict: {"stage": {"agents": [...]}}
3. Flat dict: {"agents": [...]}
"""

from typing import Any

from temper_ai.shared.utils.config_helpers import get_nested_value


def get_stage_agents(stage_config: Any) -> list:
    """Extract agents list from stage config.

    Args:
        stage_config: StageConfig, nested dict, or flat dict

    Returns:
        List of agent references
    """
    if hasattr(stage_config, "stage"):
        return list(stage_config.stage.agents)
    if isinstance(stage_config, dict):
        agents = get_nested_value(stage_config, "stage.agents")
        if agents is not None:
            return list(agents)
        return list(stage_config.get("agents", []))
    return []


def get_error_handling(stage_config: Any) -> Any:
    """Extract error handling config from stage config.

    Args:
        stage_config: StageConfig or dict

    Returns:
        StageErrorHandlingConfig instance (always non-None)
    """
    from temper_ai.stage._schemas import StageErrorHandlingConfig

    if hasattr(stage_config, "stage"):
        if (
            hasattr(stage_config.stage, "error_handling")
            and stage_config.stage.error_handling
        ):
            return stage_config.stage.error_handling
        return StageErrorHandlingConfig(on_agent_failure="halt_stage")

    if isinstance(stage_config, dict):
        error_dict = get_nested_value(stage_config, "stage.error_handling")
        if error_dict:
            return StageErrorHandlingConfig(**error_dict)

    return StageErrorHandlingConfig(on_agent_failure="halt_stage")


def get_execution_config(stage_config: Any) -> dict[str, Any]:
    """Extract execution config from stage config.

    Args:
        stage_config: StageConfig or dict

    Returns:
        Execution config dict (timeout_seconds, agent_mode, etc.)
    """
    if hasattr(stage_config, "stage") and hasattr(stage_config.stage, "execution"):
        exec_cfg = stage_config.stage.execution
        if hasattr(exec_cfg, "model_dump"):
            result: dict[str, Any] = exec_cfg.model_dump()
            return result
        return {}

    if isinstance(stage_config, dict):
        result2: dict[str, Any] = (
            get_nested_value(stage_config, "stage.execution") or {}
        )
        return result2

    return {}


def get_collaboration(stage_config: Any) -> Any:
    """Extract collaboration config from stage config.

    Args:
        stage_config: StageConfig or dict

    Returns:
        CollaborationConfig or dict or None
    """
    if hasattr(stage_config, "stage") and hasattr(stage_config.stage, "collaboration"):
        return stage_config.stage.collaboration
    if isinstance(stage_config, dict):
        return get_nested_value(stage_config, "stage.collaboration")
    return None


def get_collaboration_inner_config(stage_config: Any) -> dict[str, Any]:
    """Extract the inner .config subfield from collaboration config.

    Handles nested "stage.collaboration.config" and flat
    "collaboration.config" formats.

    Args:
        stage_config: StageConfig or dict

    Returns:
        Collaboration inner config dict
    """
    stage_dict = stage_config if isinstance(stage_config, dict) else {}
    collab = stage_dict.get("collaboration")
    if collab is None:
        inner = stage_dict.get("stage", {})
        collab = inner.get("collaboration", {}) if isinstance(inner, dict) else {}
    return collab.get("config", {}) if isinstance(collab, dict) else {}


def get_convergence(stage_config: Any) -> Any:
    """Extract convergence config from stage config.

    Args:
        stage_config: StageConfig or dict

    Returns:
        ConvergenceConfig or dict or None
    """
    if hasattr(stage_config, "stage") and hasattr(stage_config.stage, "convergence"):
        return stage_config.stage.convergence
    if isinstance(stage_config, dict):
        return get_nested_value(stage_config, "stage.convergence")
    return None


def get_quality_gates(stage_config: Any) -> dict[str, Any]:
    """Extract quality gates config from stage config.

    Args:
        stage_config: StageConfig or dict

    Returns:
        Quality gates config dict (enabled, min_confidence, etc.)
    """
    if hasattr(stage_config, "quality_gates") and stage_config.quality_gates:
        qg = stage_config.quality_gates
        if hasattr(qg, "model_dump"):
            result: dict[str, Any] = qg.model_dump()
            return result
        return {}

    stage_dict = stage_config if isinstance(stage_config, dict) else {}
    result2: dict[str, Any] = stage_dict.get("quality_gates", {})
    return result2


def get_wall_clock_timeout(stage_config: Any) -> float:
    """Extract wall-clock timeout from stage execution config.

    Args:
        stage_config: StageConfig or dict

    Returns:
        Timeout in seconds
    """
    from temper_ai.shared.constants.durations import SECONDS_PER_30_MINUTES

    if hasattr(stage_config, "stage") and hasattr(stage_config.stage, "execution"):
        return float(
            getattr(
                stage_config.stage.execution, "timeout_seconds", SECONDS_PER_30_MINUTES
            )
        )
    if isinstance(stage_config, dict):
        exec_cfg = get_nested_value(stage_config, "stage.execution") or {}
        return float(exec_cfg.get("timeout_seconds", SECONDS_PER_30_MINUTES))
    return float(SECONDS_PER_30_MINUTES)


def stage_config_to_dict(stage_config: Any) -> dict[str, Any]:
    """Convert stage config to dict (model_dump or pass-through).

    Args:
        stage_config: StageConfig or dict

    Returns:
        Dict representation
    """
    if hasattr(stage_config, "model_dump"):
        result: dict[str, Any] = stage_config.model_dump()
        return result
    if isinstance(stage_config, dict):
        return stage_config
    return {}
