"""Helpers for resolving per-agent input maps.

Resolves ``agent_input_map`` entries from stage config, mapping each agent's
declared inputs to concrete values from stage inputs or prior agent outputs.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_agent_inputs(
    agent_name: str,
    agent_interface: dict[str, Any],
    agent_input_map: dict[str, str],
    stage_inputs: dict[str, Any],
    prior_agent_outputs: dict[str, Any],
) -> dict[str, Any]:
    """Resolve agent inputs from an agent_input_map.

    Evaluates each source reference in the agent_input_map and builds a dict
    of resolved values keyed by the agent's declared input names.

    Args:
        agent_name: Name of the agent being resolved.
        agent_interface: Agent interface dict with ``inputs`` key containing
            AgentIODeclaration objects (from ``get_interface()``).
        agent_input_map: Mapping of input_name → source reference string.
        stage_inputs: Resolved stage input values.
        prior_agent_outputs: Dict of agent_name → output_data dict from
            prior agents in this stage.

    Returns:
        Dict of resolved input values keyed by input name.

    Raises:
        ValueError: If a required input has no source and no default.
    """
    declared_inputs = agent_interface.get("inputs", {})
    resolved: dict[str, Any] = {}

    for input_name, source_ref in agent_input_map.items():
        value = _resolve_source(source_ref, stage_inputs, prior_agent_outputs)
        if value is not None:
            resolved[input_name] = value
        else:
            logger.warning(
                "Agent '%s': source '%s' for input '%s' resolved to None",
                agent_name,
                source_ref,
                input_name,
            )

    # Check for required inputs not covered by agent_input_map
    for input_name, decl in declared_inputs.items():
        if input_name in resolved:
            continue
        default = getattr(decl, "default", None)
        if default is not None:
            resolved[input_name] = default
            continue
        required = getattr(decl, "required", True)
        if required:
            raise ValueError(
                f"Agent '{agent_name}': required input '{input_name}' "
                f"has no mapping in agent_input_map and no default"
            )

    return resolved


def _resolve_source(
    source_ref: str,
    stage_inputs: dict[str, Any],
    prior_agent_outputs: dict[str, Any],
) -> Any:
    """Resolve a single source reference to a concrete value.

    Supported source reference formats:
    - ``stage.<field>`` — field from resolved stage inputs
    - ``<agent>.output`` — prior agent's raw text output
    - ``<agent>.structured.<field>`` — field from prior agent's structured data

    Args:
        source_ref: Source reference string.
        stage_inputs: Resolved stage input values.
        prior_agent_outputs: Dict of agent_name → output_data dict.

    Returns:
        Resolved value, or None if not found.
    """
    parts = source_ref.split(".", maxsplit=2)

    if len(parts) < 2:
        logger.warning("Invalid source reference: '%s'", source_ref)
        return None

    prefix = parts[0]
    field = parts[1]

    # stage.<field>
    if prefix == "stage":
        return stage_inputs.get(field)

    # <agent>.output
    agent_data = prior_agent_outputs.get(prefix)
    if agent_data is None:
        return None

    if field == "output":
        return agent_data.get("output")

    # <agent>.structured.<field>
    if field == "structured" and len(parts) == 3:
        structured_field = parts[2]
        # Try script_outputs first (from ScriptAgent ::output directives)
        script_outputs = agent_data.get("script_outputs", {})
        if structured_field in script_outputs:
            return script_outputs[structured_field]
        # Try JSON-parsed structured data
        structured = agent_data.get("structured", {})
        return structured.get(structured_field)

    return None


def get_agent_input_map_for_agent(
    stage_config: Any,
    agent_name: str,
) -> dict[str, str] | None:
    """Extract agent_input_map for a specific agent from stage config.

    Args:
        stage_config: Stage config (StageConfig or dict).
        agent_name: Agent name to look up.

    Returns:
        Agent's input map dict, or None if not defined.
    """
    if stage_config is None:
        return None

    # Handle StageConfig object
    inner = getattr(stage_config, "stage", stage_config)
    if hasattr(inner, "agent_input_map"):
        aim = inner.agent_input_map
        if aim and agent_name in aim:
            return aim[agent_name]
        return None

    # Handle raw dict
    if isinstance(inner, dict):
        aim = inner.get("agent_input_map")
        if aim and agent_name in aim:
            return aim[agent_name]

    return None


def validate_agent_outputs(
    agent_name: str,
    agent_interface: dict[str, Any],
    output_data: dict[str, Any],
) -> dict[str, Any]:
    """Validate and extract declared outputs from agent output data.

    Checks agent output_data against the agent's declared output interface.
    Logs warnings for missing declared outputs.

    Args:
        agent_name: Name of the agent.
        agent_interface: Agent interface dict with ``outputs`` key.
        output_data: Agent's output_data dict (from _build_success_result).

    Returns:
        Dict of extracted output values matching declared outputs.
    """
    declared_outputs = agent_interface.get("outputs", {})
    if not declared_outputs:
        return {}

    # Potential sources of structured output
    script_outputs = output_data.get("script_outputs", {})
    structured = output_data.get("structured", {})
    raw_output = output_data.get("output", "")

    extracted: dict[str, Any] = {}
    for name, decl in declared_outputs.items():
        if name in script_outputs:
            extracted[name] = script_outputs[name]
        elif name in structured:
            extracted[name] = structured[name]
        elif name == "output" or (len(declared_outputs) == 1 and raw_output):
            # Single output declaration maps to raw output
            extracted[name] = raw_output
        else:
            logger.warning(
                "Agent '%s' declared output '%s' but did not produce it",
                agent_name,
                name,
            )

    return extracted
