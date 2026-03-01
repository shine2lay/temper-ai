"""Unified pre-compile validation for workflow configurations.

Provides ``validate_schemas()`` and ``validate_agent_io()`` — the two
compile-time checks that were previously inside each engine's ``compile()``.

These are pure functions that take a config_loader and workflow_config dict,
validate everything, and return errors.  The runtime calls them from
``validate_all()`` alongside the existing reference validation.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_schemas(
    workflow_config: dict[str, Any],
    config_loader: Any,
    errors: list[str],
) -> None:
    """Validate stage and agent configs against Pydantic schemas.

    Loads each stage and its agents, validates against ``StageConfig`` /
    ``AgentConfig`` schemas.  Schema warnings are logged but do **not**
    produce hard errors — only load failures are appended to *errors*.
    """
    from pydantic import ValidationError

    from temper_ai.stage._schemas import StageConfig
    from temper_ai.storage.schemas.agent_config import AgentConfig
    from temper_ai.workflow.constants import (
        ERROR_MSG_AGENT_PREFIX,
        ERROR_MSG_STAGE_PREFIX,
    )
    from temper_ai.workflow.engines.langgraph_compiler import (
        _extract_agents_from_stage,
    )
    from temper_ai.workflow.utils import extract_agent_name

    stages = workflow_config.get("workflow", {}).get("stages", [])

    for stage_entry in stages:
        stage_name = _extract_stage_name_from_entry(stage_entry)
        if not stage_name:
            continue

        # --- Load & validate stage config ---
        try:
            stage_config = config_loader.load_stage(stage_name)
        except Exception as exc:
            errors.append(
                f"{ERROR_MSG_STAGE_PREFIX}{stage_name}': "
                f"Failed to load config - {exc}"
            )
            continue

        if isinstance(stage_config, dict):
            try:
                StageConfig(**stage_config)
            except ValidationError as exc:
                logger.warning(
                    "%s%s': Config schema warnings - %s",
                    ERROR_MSG_STAGE_PREFIX,
                    stage_name,
                    exc,
                )

        # --- Load & validate agent configs ---
        agents = _extract_agents_from_stage(stage_config)
        for agent_ref in agents:
            agent_name = extract_agent_name(agent_ref)
            try:
                agent_config = config_loader.load_agent(agent_name)
            except Exception as exc:
                errors.append(
                    f"{ERROR_MSG_AGENT_PREFIX}{agent_name}' in stage "
                    f"'{stage_name}': Failed to load config - {exc}"
                )
                continue

            if isinstance(agent_config, dict):
                try:
                    AgentConfig(**agent_config)
                except ValidationError as exc:
                    logger.warning(
                        "%s%s' in stage '%s': Config schema warnings - %s",
                        ERROR_MSG_AGENT_PREFIX,
                        agent_name,
                        stage_name,
                        exc,
                    )


def validate_agent_io(
    workflow_config: dict[str, Any],
    config_loader: Any,
    errors: list[str],
) -> None:
    """Validate agent I/O declarations and wiring within each stage.

    Checks required inputs, type compatibility between agents, and stage
    output coverage.  Skips agents without declarations (backward compatible).
    """
    from temper_ai.agent.utils.agent_factory import AgentFactory
    from temper_ai.workflow.engines._validation_helpers import (
        validate_agent_io_for_stage,
    )
    from temper_ai.workflow.engines.langgraph_compiler import (
        _extract_agents_from_stage,
    )
    from temper_ai.workflow.utils import extract_agent_name

    stages = workflow_config.get("workflow", {}).get("stages", [])

    for stage_entry in stages:
        stage_name = _extract_stage_name_from_entry(stage_entry)
        if not stage_name:
            continue

        try:
            stage_config = config_loader.load_stage(stage_name)
        except Exception:
            continue  # load failure already reported by validate_schemas

        agents = _extract_agents_from_stage(stage_config)
        if not agents:
            continue

        # Collect agent I/O interfaces
        agent_interfaces: dict[str, dict[str, Any]] = {}
        for agent_ref in agents:
            agent_name = extract_agent_name(agent_ref)
            try:
                interface = AgentFactory.get_interface(agent_name, config_loader)
                agent_interfaces[agent_name] = interface
            except Exception:
                continue  # load failure already reported

        if not agent_interfaces:
            continue

        # Extract stage-level I/O for cross-reference
        stage_dict = (
            stage_config
            if isinstance(stage_config, dict)
            else stage_config.model_dump()
        )
        stage_inner = stage_dict.get("stage", stage_dict)
        stage_inputs_raw = stage_inner.get("inputs") or {}
        stage_outputs_raw = stage_inner.get("outputs") or {}

        validate_agent_io_for_stage(
            agent_interfaces,
            stage_name,
            stage_inputs_raw,
            stage_outputs_raw,
            errors,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_stage_name_from_entry(stage_entry: Any) -> str | None:
    """Extract the bare stage name from a workflow stage entry.

    Handles dicts (``{"name": "...", "stage_ref": "..."}``), strings,
    and Pydantic models.
    """
    import os.path as _osp

    if isinstance(stage_entry, str):
        return _osp.splitext(_osp.basename(stage_entry))[0]

    if isinstance(stage_entry, dict):
        raw = (
            stage_entry.get("name")
            or stage_entry.get("stage_ref")
            or stage_entry.get("config_path")
        )
        if raw:
            return _osp.splitext(_osp.basename(raw))[0]
        return None

    # Pydantic model
    raw = getattr(stage_entry, "name", None) or getattr(stage_entry, "stage_name", None)
    if raw:
        return _osp.splitext(_osp.basename(raw))[0]
    return None
