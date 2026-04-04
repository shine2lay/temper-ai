"""Topology generators — convert strategy name + agents into node layouts.

Strategies are NOT a separate execution layer. They're functions that generate
a list of AgentNodes with appropriate depends_on and input wiring. The graph
executor runs the generated topology the same way it runs any graph.

Usage:
    nodes = build_topology("parallel", agent_configs)
    nodes = build_topology("leader", agent_configs)
    nodes = build_topology("sequential", agent_configs)
"""

from __future__ import annotations

from typing import Callable

from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.exceptions import TopologyError, ValidationError
from temper_ai.stage.models import NodeConfig

# Type alias for topology generator functions
TopologyGenerator = Callable[[list[dict], dict], list[AgentNode]]


def build_topology(
    strategy: str,
    agent_configs: list[dict],
    strategy_config: dict | None = None,
) -> list[AgentNode]:
    """Generate node topology from strategy name and agent list.

    Args:
        strategy: Strategy name ("parallel", "sequential", "leader").
        agent_configs: List of resolved agent config dicts.
        strategy_config: Optional strategy-specific config.

    Returns:
        List of AgentNodes with depends_on set according to the strategy pattern.

    Raises:
        TopologyError: Unknown strategy name.
        ValidationError: Strategy requirements not met.
    """
    if strategy not in _GENERATORS:
        raise TopologyError(
            f"Unknown strategy: '{strategy}'. Available: {list(_GENERATORS.keys())}"
        )

    generator = _GENERATORS[strategy]
    errors = _VALIDATORS.get(strategy, lambda _: [])(agent_configs)
    if errors:
        raise ValidationError(
            f"Strategy '{strategy}' validation failed: {'; '.join(errors)}"
        )

    return generator(agent_configs, strategy_config or {})


def _parallel_topology(agent_configs: list[dict], config: dict) -> list[AgentNode]:
    """All agents run independently. No depends_on between them.

    The graph executor detects they're independent and runs them concurrently.
    """
    nodes = []
    for conf in agent_configs:
        node_config = NodeConfig(name=conf["name"], type="agent")
        nodes.append(AgentNode(node_config, conf))
    return nodes


def _sequential_topology(agent_configs: list[dict], config: dict) -> list[AgentNode]:
    """Linear chain. Each agent depends on the previous.

    Each agent receives the full parent input_data plus an auto-injected
    ``other_agents`` field containing its predecessor's output. No input_map
    is set so that parent-level fields (e.g. workspace_path) flow through.
    """
    nodes = []
    for i, conf in enumerate(agent_configs):
        deps = [agent_configs[i - 1]["name"]] if i > 0 else []
        node_config = NodeConfig(
            name=conf["name"],
            type="agent",
            depends_on=deps,
        )
        nodes.append(AgentNode(node_config, conf))
    return nodes


def _leader_topology(agent_configs: list[dict], config: dict) -> list[AgentNode]:
    """Workers run in parallel, leader synthesizes their outputs.

    Leader is identified by role: leader in config. Default: last agent.
    Workers' outputs are combined into leader's _strategy_context.
    """
    leader_conf = None
    worker_confs = []

    for conf in agent_configs:
        if conf.get("role") == "leader":
            leader_conf = conf
        else:
            worker_confs.append(conf)

    if leader_conf is None:
        # Default: last agent is leader
        leader_conf = agent_configs[-1]
        worker_confs = agent_configs[:-1]

    # Workers: no deps between them (parallel)
    worker_nodes = []
    for conf in worker_confs:
        node_config = NodeConfig(name=conf["name"], type="agent")
        worker_nodes.append(AgentNode(node_config, conf))

    # Leader: depends on all workers
    worker_names = [w.name for w in worker_nodes]
    leader_node_config = NodeConfig(
        name=leader_conf["name"],
        type="agent",
        depends_on=worker_names,
    )
    # Mark for strategy context injection
    leader_conf = {**leader_conf, "_receives_strategy_context": True}
    leader_node = AgentNode(leader_node_config, leader_conf)

    return worker_nodes + [leader_node]


# --- Validation ---


def _validate_parallel(agent_configs: list[dict]) -> list[str]:
    errors = []
    if len(agent_configs) < 2:
        errors.append("Parallel strategy needs at least 2 agents")
    return errors


def _validate_sequential(agent_configs: list[dict]) -> list[str]:
    errors = []
    if len(agent_configs) < 2:
        errors.append("Sequential strategy needs at least 2 agents")
    return errors


def _validate_leader(agent_configs: list[dict]) -> list[str]:
    errors = []
    if len(agent_configs) < 2:
        errors.append("Leader strategy needs at least 2 agents (1 leader + 1 worker)")
    leaders = [a for a in agent_configs if a.get("role") == "leader"]
    if len(leaders) > 1:
        errors.append(
            f"Leader strategy requires exactly one leader, found {len(leaders)}"
        )
    return errors


# --- Registries ---

_GENERATORS: dict[str, TopologyGenerator] = {
    "parallel": _parallel_topology,
    "sequential": _sequential_topology,
    "leader": _leader_topology,
}

_VALIDATORS: dict[str, Callable[[list[dict]], list[str]]] = {
    "parallel": _validate_parallel,
    "sequential": _validate_sequential,
    "leader": _validate_leader,
}


def register_topology(name: str, generator: TopologyGenerator,
                      validator: Callable[[list[dict]], list[str]] | None = None):
    """Register a custom topology generator (e.g., debate, iterative)."""
    _GENERATORS[name] = generator
    if validator:
        _VALIDATORS[name] = validator
