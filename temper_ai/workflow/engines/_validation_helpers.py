"""Compile-time validation helpers for agent I/O declarations.

Provides type compatibility checking and agent I/O validation
used during ``DynamicExecutionEngine.compile()``.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Type compatibility matrix: target_type → set of compatible source types.
# "any" is compatible with everything in both directions.
_TYPE_COMPAT: dict[str, frozenset[str]] = {
    "any": frozenset({"string", "list", "dict", "number", "boolean", "any"}),
    "string": frozenset({"string", "any"}),
    "list": frozenset({"list", "any"}),
    "dict": frozenset({"dict", "any"}),
    "number": frozenset({"number", "any"}),
    "boolean": frozenset({"boolean", "any"}),
}


def check_type_compatibility(source_type: str, target_type: str) -> bool:
    """Check if a source type is compatible with a target type.

    Args:
        source_type: Type produced by the source (agent output or stage input).
        target_type: Type expected by the target (agent input).

    Returns:
        True if compatible.
    """
    return source_type in _TYPE_COMPAT.get(target_type, {target_type})


def validate_agent_io_types(
    producer_name: str,
    producer_outputs: dict[str, Any],
    consumer_name: str,
    consumer_inputs: dict[str, Any],
    errors: list[str],
    stage_name: str,
) -> None:
    """Validate type compatibility between producer outputs and consumer inputs.

    Only checks fields that appear in both producer's outputs and consumer's
    inputs (name-matched). Appends type mismatch errors to ``errors`` list.

    Args:
        producer_name: Name of the producing agent.
        producer_outputs: Dict of output name → AgentIODeclaration.
        consumer_name: Name of the consuming agent.
        consumer_inputs: Dict of input name → AgentIODeclaration.
        errors: Error list to append to.
        stage_name: Stage name for error messages.
    """
    for input_name, input_decl in consumer_inputs.items():
        if input_name in producer_outputs:
            output_decl = producer_outputs[input_name]
            source_type = getattr(output_decl, "type", "any")
            target_type = getattr(input_decl, "type", "any")
            if not check_type_compatibility(source_type, target_type):
                errors.append(
                    f"Stage '{stage_name}': type mismatch — "
                    f"agent '{producer_name}' produces '{input_name}' "
                    f"as {source_type} but agent '{consumer_name}' "
                    f"expects {target_type}"
                )


def validate_agent_io_for_stage(
    agent_interfaces: dict[str, dict[str, Any]],
    stage_name: str,
    stage_inputs_raw: dict[str, Any],
    stage_outputs_raw: dict[str, Any],
    errors: list[str],
) -> None:
    """Validate agent I/O declarations within a stage.

    Checks:
    1. Required agent inputs can be satisfied (by stage inputs or prior agents)
    2. Type compatibility between agent outputs → agent inputs
    3. Stage output coverage (warning if no agent produces a declared stage output)

    Args:
        agent_interfaces: Dict of agent_name → interface dict (from get_interface).
        stage_name: Stage name for error messages.
        stage_inputs_raw: Raw stage inputs dict (field names available to agents).
        stage_outputs_raw: Raw stage outputs dict (what the stage promises).
        errors: Error list to append validation errors to.
    """
    stage_input_names = set(stage_inputs_raw.keys())
    agent_names = list(agent_interfaces.keys())

    for agent_name, interface in agent_interfaces.items():
        declared_inputs = interface.get("inputs", {})
        declared_outputs = interface.get("outputs", {})

        if not declared_inputs and not declared_outputs:
            continue  # no declarations, skip validation

        # --- Validate required inputs ---
        prior_agent_names = set(agent_names[: agent_names.index(agent_name)])

        for input_name, decl in declared_inputs.items():
            if not getattr(decl, "required", True):
                continue
            if getattr(decl, "default", None) is not None:
                continue
            # Check if stage provides this input
            if input_name in stage_input_names:
                continue
            # Check if any prior agent could provide it (by output name match)
            provided_by_prior = False
            for prior_name in prior_agent_names:
                prior_outputs = agent_interfaces.get(prior_name, {}).get("outputs", {})
                if input_name in prior_outputs:
                    provided_by_prior = True
                    break
            if not provided_by_prior:
                errors.append(
                    f"Agent '{agent_name}' in stage '{stage_name}': "
                    f"required input '{input_name}' has no source "
                    f"(not in stage inputs and no prior agent produces it)"
                )

        # --- Type compatibility with prior agents ---
        for prior_name in prior_agent_names:
            prior_outputs = agent_interfaces.get(prior_name, {}).get("outputs", {})
            if prior_outputs and declared_inputs:
                validate_agent_io_types(
                    prior_name,
                    prior_outputs,
                    agent_name,
                    declared_inputs,
                    errors,
                    stage_name,
                )

    # --- Stage output coverage ---
    for output_name in stage_outputs_raw:
        produced = False
        for a_interface in agent_interfaces.values():
            if output_name in a_interface.get("outputs", {}):
                produced = True
                break
        if not produced:
            # Warning, not error — stage output might come from synthesis
            logger.warning(
                "Stage '%s' declares output '%s' but no agent produces it "
                "(may come from synthesis)",
                stage_name,
                output_name,
            )
