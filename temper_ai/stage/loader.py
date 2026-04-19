"""Graph loader — resolves YAML configs into executable node trees.

Handles:
- Agent ref resolution (loads agent config from config store)
- Node-level overrides merged on top of agent config
- Strategy shorthand → topology generation
- Ref loading for reusable stages
- Validation (circular deps, missing refs, mutually exclusive fields)
"""

from __future__ import annotations

import logging
from typing import Any

from temper_ai.config.store import ConfigStore
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.exceptions import LoaderError, ValidationError
from temper_ai.stage.models import NodeConfig, WorkflowConfig
from temper_ai.stage.node import Node
from temper_ai.stage.stage_node import StageNode
from temper_ai.stage.template_expansion import (
    TemplateExpansionError,
    expand_templates,
)
from temper_ai.stage.topology import build_topology

logger = logging.getLogger(__name__)

# Fields that are node-level concerns (not agent overrides)
_NODE_FIELDS = {
    "name", "type", "agent", "strategy", "strategy_config", "agents", "nodes",
    "ref", "depends_on", "condition", "loop_to", "max_loops", "input_map",
    "inputs", "outputs",
}


class GraphLoader:
    """Load and resolve graph configs into executable node trees."""

    def __init__(self, config_store: ConfigStore | None = None):
        self.config_store = config_store
        self._defaults: dict = {}  # Workflow-level defaults (provider, model, etc.)

    def load_workflow(
        self,
        workflow_ref: str,
        inputs: dict[str, Any] | None = None,
    ) -> tuple[list[Node], WorkflowConfig]:
        """Load a workflow config and return resolved nodes + config.

        Args:
            workflow_ref: Config name (looked up in config store) or raw config dict.
            inputs: Workflow inputs (the POST body's `inputs` field). Required
                only if the workflow uses `type: template` nodes; otherwise
                may be None.

        Returns:
            Tuple of (resolved_nodes, workflow_config).

        Raises:
            LoaderError: Config not found, invalid, or template expansion failed.
            ValidationError: Config fails validation.
        """
        raw = self._load_config(workflow_ref, "workflow")
        try:
            raw = expand_templates(raw, inputs)
        except TemplateExpansionError as exc:
            raise LoaderError(f"template expansion failed: {exc}") from exc
        config = WorkflowConfig.from_dict(raw)

        # Store workflow defaults so agent resolution can apply them as fallbacks
        self._defaults = config.defaults or {}

        nodes = self._resolve_nodes(config.nodes)
        errors = self._validate(nodes)
        if errors:
            raise ValidationError(
                f"Workflow '{config.name}' validation failed:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        return nodes, config

    def _resolve_nodes(self, node_configs: list[NodeConfig]) -> list[Node]:
        """Resolve a list of NodeConfigs into executable Nodes."""
        nodes = []
        for nc in node_configs:
            node = self._resolve_node(nc)
            nodes.append(node)
        return nodes

    def _resolve_node(self, nc: NodeConfig) -> Node:
        """Resolve a single NodeConfig into an executable Node.

        Handles:
        - type=agent: resolve agent ref, merge overrides → AgentNode
        - type=stage + strategy: resolve agent refs → build_topology → StageNode
        - type=stage + nodes: recursively resolve child nodes → StageNode
        - type=stage + ref: load referenced config → StageNode
        """
        # Load from ref if specified
        if nc.ref:
            nc = self._resolve_ref(nc)

        if nc.type == "agent":
            return self._resolve_agent_node(nc)
        elif nc.type == "stage":
            return self._resolve_stage_node(nc)
        else:
            raise LoaderError(f"Unknown node type: '{nc.type}' for node '{nc.name}'")

    def _resolve_agent_node(self, nc: NodeConfig) -> AgentNode:
        """Resolve an agent node: load agent config, merge overrides."""
        agent_config = self._resolve_agent_config(nc)
        return AgentNode(nc, agent_config)

    def _resolve_stage_node(self, nc: NodeConfig) -> StageNode:
        """Resolve a stage node: either strategy+agents or explicit nodes."""
        # Validate mutual exclusivity
        has_agents = nc.agents is not None
        has_nodes = nc.nodes is not None

        if has_agents and has_nodes:
            raise ValidationError(
                f"Stage '{nc.name}' has both 'agents' and 'nodes'. "
                "Use agents + strategy OR nodes, not both."
            )
        if not has_agents and not has_nodes:
            raise ValidationError(
                f"Stage '{nc.name}' needs either 'agents' + 'strategy' or 'nodes'."
            )

        if has_agents:
            return self._resolve_strategy_stage(nc)
        else:
            return self._resolve_explicit_stage(nc)

    def _resolve_strategy_stage(self, nc: NodeConfig) -> StageNode:
        """Resolve a stage with strategy shorthand (strategy + agents list)."""
        if not nc.strategy:
            raise ValidationError(
                f"Stage '{nc.name}' has 'agents' but no 'strategy'. "
                "Specify a strategy (parallel, sequential, leader)."
            )

        # Resolve each agent ref to a full config dict
        agent_configs = []
        assert nc.agents is not None  # guaranteed by caller check # noqa: B101
        for agent_ref in nc.agents:
            if isinstance(agent_ref, str):
                agent_config = {**self._defaults, **self._load_agent_config(agent_ref)}
            elif isinstance(agent_ref, dict):
                # Inline agent config or ref with overrides
                if "agent" in agent_ref or "ref" in agent_ref:
                    ref = agent_ref.get("agent") or agent_ref.get("ref") or ""
                    base = self._load_agent_config(ref)
                    overrides = {
                        k: v for k, v in agent_ref.items()
                        if k not in ("agent", "ref")
                    }
                    agent_config = {**self._defaults, **base, **overrides}
                else:
                    agent_config = {**self._defaults, **agent_ref}
            else:
                raise LoaderError(
                    f"Invalid agent entry in stage '{nc.name}': {agent_ref}"
                )

            # Ensure agent has a name
            if "name" not in agent_config:
                agent_config["name"] = agent_config.get(
                    "name", agent_ref if isinstance(agent_ref, str) else "unnamed"
                )
            agent_configs.append(agent_config)

        # Generate topology from strategy
        child_nodes: list[Node] = list(build_topology(nc.strategy, agent_configs, nc.strategy_config))
        return StageNode(nc, child_nodes)

    def _resolve_explicit_stage(self, nc: NodeConfig) -> StageNode:
        """Resolve a stage with explicit child nodes."""
        assert nc.nodes is not None  # guaranteed by caller check # noqa: B101
        child_nodes = self._resolve_nodes(nc.nodes)
        return StageNode(nc, child_nodes)

    def _resolve_ref(self, nc: NodeConfig) -> NodeConfig:
        """Load a referenced config and merge with node-level overrides.

        Only fields explicitly set on the node (not defaults) override the ref.
        We detect this by comparing against a fresh default NodeConfig.
        """
        assert nc.ref is not None  # guaranteed by caller # noqa: B101
        ref_config = self._load_config(nc.ref, "stage")
        merged_data = dict(ref_config)

        # Compare against defaults to find explicitly-set fields
        defaults = NodeConfig(name=nc.name)
        skip_fields = {"ref", "name"}

        for field_name in vars(nc):
            if field_name in skip_fields:
                continue
            value = getattr(nc, field_name)
            default_value = getattr(defaults, field_name, None)
            # Only override if the value differs from the default
            if value != default_value and value is not None:
                merged_data[field_name] = value

        # Always keep the node's name
        merged_data["name"] = nc.name

        return NodeConfig.from_dict(merged_data)

    def _resolve_agent_config(self, nc: NodeConfig) -> dict:
        """Load agent config by ref, merge node-level overrides.

        Merge order (last wins): workflow defaults → agent config → node overrides.
        Agent ref provides identity (name, system_prompt, model, tools, memory).
        Node-level overrides provide task (task_template, model override, etc.).
        """
        if nc.agent:
            base = self._load_agent_config(nc.agent)
        else:
            base = {}

        # Extract node-level overrides (everything that's not a node-structural field)
        overrides = {}
        for field_name, value in vars(nc).items():
            if value is not None and field_name not in _NODE_FIELDS:
                overrides[field_name] = value

        # Merge: workflow defaults (lowest) → agent config → node overrides (highest)
        merged = {**self._defaults, **base, **overrides}

        # Ensure name
        if "name" not in merged:
            merged["name"] = nc.name

        return merged

    def _load_agent_config(self, ref: str) -> dict:
        """Load an agent config from the config store."""
        if not self.config_store:
            raise LoaderError(
                f"Cannot resolve agent ref '{ref}': no config store available"
            )

        # Extract name from ref path (e.g., "agents/planner" → name="planner")
        name = ref.split("/")[-1] if "/" in ref else ref
        try:
            raw = self.config_store.get(name, "agent")
            return _unwrap_config(raw, "agent")
        except LoaderError:
            raise
        except Exception as exc:
            raise LoaderError(f"Failed to load agent config '{ref}': {exc}") from exc

    def _load_config(self, ref: str, config_type: str) -> dict:
        """Load a config from the config store."""
        if not self.config_store:
            raise LoaderError(
                f"Cannot resolve ref '{ref}': no config store available"
            )

        name = ref.split("/")[-1] if "/" in ref else ref
        try:
            raw = self.config_store.get(name, config_type)
            return _unwrap_config(raw, config_type)
        except LoaderError:
            raise
        except Exception as exc:
            raise LoaderError(f"Failed to load {config_type} config '{ref}': {exc}") from exc

    def _validate(self, nodes: list[Node]) -> list[str]:
        """Validate a resolved node tree. Returns list of errors."""
        errors = []
        node_names = {node.name for node in nodes}

        for node in nodes:
            # Check depends_on targets exist
            for dep in node.depends_on:
                if dep not in node_names:
                    errors.append(
                        f"Node '{node.name}' depends on '{dep}' which doesn't exist"
                    )

            # Check loop_to target exists
            if node.loop_to and node.loop_to not in node_names:
                errors.append(
                    f"Node '{node.name}' loop_to target '{node.loop_to}' doesn't exist"
                )

            # Check condition sources reference valid nodes
            if node.condition:
                source = node.condition.get("source", "")
                source_node = source.split(".")[0] if "." in source else ""
                if source_node and source_node not in node_names:
                    errors.append(
                        f"Node '{node.name}' condition references '{source_node}' "
                        f"which doesn't exist"
                    )

            # Check loop_condition sources reference valid nodes
            if node.loop_condition:
                source = node.loop_condition.get("source", "")
                source_node = source.split(".")[0] if "." in source else ""
                if source_node and source_node not in node_names:
                    errors.append(
                        f"Node '{node.name}' loop_condition references '{source_node}' "
                        f"which doesn't exist"
                    )

            # Check input_map source references
            if node.config.input_map:
                for local_name, source in node.config.input_map.items():
                    parts = source.split(".")
                    if len(parts) < 2:
                        errors.append(
                            f"Node '{node.name}' input_map '{local_name}' has invalid "
                            f"source '{source}' (expected 'node_name.field')"
                        )
                        continue
                    source_node = parts[0]
                    if source_node not in ("workflow", "input") and source_node not in node_names:
                        errors.append(
                            f"Node '{node.name}' input_map '{local_name}' references "
                            f"'{source_node}' which doesn't exist. "
                            f"Available nodes: {sorted(node_names)}"
                        )

            # Validate child nodes recursively (for StageNodes)
            if isinstance(node, StageNode):
                child_errors = self._validate(node.child_nodes)
                errors.extend(child_errors)

        return errors


def _unwrap_config(raw: dict, config_type: str) -> dict:
    """Unwrap a config stored with a type key wrapper.

    The YAML importer stores configs as {"agent": {...inner...}} or
    {"workflow": {...inner...}}. The loader needs the inner dict.

    If the config doesn't have the wrapper (e.g., stored directly via
    ConfigStore.put()), return it as-is.
    """
    if config_type in raw and isinstance(raw[config_type], dict):
        return raw[config_type]
    return raw
