"""Configuration models for the stage module.

These are internal to the stage module — they represent the resolved,
validated config ready for execution. YAML parsing produces these.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class NodeConfig:
    """Configuration for a single node in a graph.

    A node is either:
    - type="agent": leaf node, has `agent` ref + optional overrides
    - type="stage": composite node, has `nodes` (explicit) OR `agents` + `strategy` (shorthand)

    These are mutually exclusive:
    - agents + strategy: shorthand — topology generated from strategy name
    - nodes: explicit — user defines exact topology with depends_on

    Having both agents and nodes is a validation error.
    """

    name: str
    type: str = "agent"  # "agent" or "stage"

    # Agent node fields
    agent: str | None = None  # Agent config ref (e.g., "agents/planner")

    # Stage node fields (mutually exclusive: agents+strategy OR nodes)
    strategy: str | None = None  # Topology generator name (parallel, leader, sequential)
    strategy_config: dict = field(default_factory=dict)
    agents: list[str | dict] | None = None  # Agent refs for strategy shorthand
    nodes: list[NodeConfig] | None = None  # Explicit child nodes

    # Reference to saved config
    ref: str | None = None  # Load config by ref (e.g., "stages/code_review")

    # DAG fields
    depends_on: list[str] = field(default_factory=list)
    condition: dict | None = None  # {"source": "x.y", "operator": "equals", "value": "z"}
    loop_to: str | None = None  # Re-execute target node on failure
    max_loops: int = 1
    loop_condition: dict | None = None  # {"source": "x.structured.y", "operator": "equals", "value": "FAIL"}

    # Timeout and gates
    timeout_seconds: int | None = None  # Wall-clock timeout for this node (default: no limit)
    gate: bool = False  # If True, pause before executing and wait for human approval


    # Input/output mapping
    input_map: dict[str, str] | None = None  # {"local_name": "source_node.field"}

    # Context boundary (opt-in)
    inputs: dict[str, str] | None = None  # Declared inputs (input gate)
    outputs: dict[str, str] | None = None  # Declared outputs (output gate)

    # Agent overrides (when type=agent, these override the agent config)
    task_template: str | None = None
    system_prompt: str | None = None
    role: str | None = None
    model: str | None = None
    provider: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    token_budget: int | None = None
    tools: list[str] | None = None
    memory: dict | None = None

    # All known fields for typo detection in from_dict()
    _KNOWN_FIELDS: frozenset = frozenset({
        "name", "type", "agent", "strategy", "strategy_config", "agents",
        "nodes", "ref", "depends_on", "condition", "loop_to", "max_loops",
        "loop_condition", "timeout_seconds", "gate",
        "input_map", "inputs", "outputs",
        "task_template",
        "system_prompt", "role", "model", "provider", "temperature",
        "max_tokens", "token_budget", "tools", "memory",
    })

    @classmethod
    def from_dict(cls, data: dict) -> NodeConfig:
        """Create NodeConfig from a raw dict (parsed YAML)."""
        # Warn on unknown keys (catches typos like "dependson" or "stratgey")
        unknown = set(data.keys()) - cls._KNOWN_FIELDS
        if unknown:
            node_name = data.get("name", "<unnamed>")
            logger.warning(
                "Node '%s' has unknown fields: %s — these will be ignored. "
                "Check for typos.",
                node_name, sorted(unknown),
            )

        nodes_data = data.get("nodes")
        nodes = None
        if nodes_data:
            nodes = [NodeConfig.from_dict(n) if isinstance(n, dict) else n for n in nodes_data]

        return cls(
            name=data["name"],
            type=data.get("type", "agent"),
            agent=data.get("agent"),
            strategy=data.get("strategy"),
            strategy_config=data.get("strategy_config", {}),
            agents=data.get("agents"),
            nodes=nodes,
            ref=data.get("ref"),
            depends_on=data.get("depends_on", []),
            condition=data.get("condition"),
            loop_to=data.get("loop_to"),
            max_loops=data.get("max_loops", 1),
            loop_condition=data.get("loop_condition"),
            timeout_seconds=data.get("timeout_seconds"),
            gate=data.get("gate", False),
            input_map=data.get("input_map"),
            inputs=data.get("inputs"),
            outputs=data.get("outputs"),
            task_template=data.get("task_template"),
            system_prompt=data.get("system_prompt"),
            role=data.get("role"),
            model=data.get("model"),
            provider=data.get("provider"),
            temperature=data.get("temperature"),
            max_tokens=data.get("max_tokens"),
            token_budget=data.get("token_budget"),
            tools=data.get("tools"),
            memory=data.get("memory"),
        )


@dataclass
class WorkflowConfig:
    """Top-level workflow configuration (loaded from YAML).

    A workflow is itself a graph — same structure as a stage,
    but with additional top-level fields (inputs, safety, memory, providers).
    """

    name: str
    description: str = ""
    version: str = "1.0"
    nodes: list[NodeConfig] = field(default_factory=list)

    # Workflow-level declarations
    inputs: dict | None = None  # Workflow input schema
    outputs: dict[str, str] | None = None  # Workflow output mapping (key → source ref)
    safety: dict | None = None  # Safety policy config
    memory: dict | None = None  # Memory config
    defaults: dict | None = None  # Default model, provider, etc.

    _KNOWN_FIELDS: frozenset = frozenset({
        "name", "description", "version", "nodes",
        "inputs", "outputs", "safety", "memory", "defaults",
    })

    @classmethod
    def from_dict(cls, data: dict) -> WorkflowConfig:
        """Create WorkflowConfig from a raw dict (parsed YAML)."""
        unknown = set(data.keys()) - cls._KNOWN_FIELDS
        if unknown:
            wf_name = data.get("name", "<unnamed>")
            logger.warning(
                "Workflow '%s' has unknown fields: %s — these will be ignored. "
                "Check for typos.",
                wf_name, sorted(unknown),
            )

        nodes_data = data.get("nodes", [])
        nodes = [NodeConfig.from_dict(n) for n in nodes_data]

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            nodes=nodes,
            inputs=data.get("inputs"),
            outputs=data.get("outputs"),
            safety=data.get("safety"),
            memory=data.get("memory"),
            defaults=data.get("defaults"),
        )
