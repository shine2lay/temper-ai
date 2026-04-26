"""Topology generators — convert strategy name + agents into node layouts.

Strategies are NOT a separate execution layer. They're functions that generate
a list of AgentNodes with appropriate depends_on and input wiring. The graph
executor runs the generated topology the same way it runs any graph.

Usage:
    nodes = build_topology("parallel", agent_configs)
    nodes = build_topology("leader", agent_configs)
    nodes = build_topology("sequential", agent_configs)
    nodes = build_topology("debate", agent_configs, {"rounds": 3})
"""

from __future__ import annotations

from collections.abc import Callable

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


def _debate_topology(agent_configs: list[dict], config: dict) -> list[AgentNode]:
    """Multi-round debate. N debaters speak per round seeing the previous
    round's transcripts; a synthesizer reads the whole debate and produces
    the unified output.

    Synthesizer is identified by `role: synthesizer` on the agent config.
    Default: last agent in the list. All others are debaters.

    Topology for D debaters × R rounds (with R=3 here):

        round 1:  d1__r1, d2__r1, d3__r1     no deps, run in parallel
        round 2:  d1__r2, d2__r2, d3__r2     each depends on ALL of round 1
        round 3:  d1__r3, d2__r3, d3__r3     each depends on ALL of round 2
        final:    synth                       depends on ALL nodes (every round)

    Each debater node from round 2 onwards receives the previous round's
    transcripts via `_strategy_context` (the renderer surfaces this as
    `{{ other_agents }}` in the agent's task_template). Round-1 debaters
    have no `_strategy_context` so the template's else branch fires —
    they produce an opening position.

    The synthesizer depends on every debate node so its `_strategy_context`
    contains the full transcript across all rounds, labeled per node
    (`[d1__r1]: ...`, `[d1__r2]: ...`, etc.).

    strategy_config:
        rounds: int (default 3) — number of debate rounds; must be >= 1
    """
    rounds = int(config.get("rounds", 3))
    if rounds < 1:
        raise ValidationError(
            f"Debate strategy requires rounds >= 1, got {rounds}"
        )

    # Identify synthesizer: explicit role, else last agent in list.
    synth_conf = None
    debater_confs: list[dict] = []
    for conf in agent_configs:
        if conf.get("role") == "synthesizer":
            synth_conf = conf
        else:
            debater_confs.append(conf)
    if synth_conf is None:
        synth_conf = agent_configs[-1]
        debater_confs = agent_configs[:-1]

    nodes: list[AgentNode] = []
    prev_round_names: list[str] = []
    all_round_names: list[str] = []

    for round_idx in range(1, rounds + 1):
        this_round_names: list[str] = []
        for d_conf in debater_confs:
            node_name = f"{d_conf['name']}__r{round_idx}"
            # Round 1: no deps. Later rounds: depend on all of previous round
            # so their outputs are gathered into _strategy_context.
            deps = list(prev_round_names)
            node_config = NodeConfig(
                name=node_name,
                type="agent",
                depends_on=deps,
            )
            agent_conf = d_conf
            if round_idx > 1:
                agent_conf = {**d_conf, "_receives_strategy_context": True}
            nodes.append(AgentNode(node_config, agent_conf))
            this_round_names.append(node_name)
        all_round_names.extend(this_round_names)
        prev_round_names = this_round_names

    # Synthesizer depends on every debate node so its _strategy_context
    # contains every round, not just the last.
    synth_node_config = NodeConfig(
        name=synth_conf["name"],
        type="agent",
        depends_on=list(all_round_names),
    )
    synth_agent_conf = {**synth_conf, "_receives_strategy_context": True}
    nodes.append(AgentNode(synth_node_config, synth_agent_conf))

    return nodes


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


def _validate_debate(agent_configs: list[dict]) -> list[str]:
    errors = []
    # 2 debaters + 1 synthesizer = 3 minimum. With <2 debaters there's
    # nothing to debate; with no synthesizer there's no consolidated output.
    if len(agent_configs) < 3:
        errors.append(
            "Debate strategy needs at least 3 agents (>= 2 debaters + 1 synthesizer)"
        )
    synthesizers = [a for a in agent_configs if a.get("role") == "synthesizer"]
    if len(synthesizers) > 1:
        errors.append(
            f"Debate strategy requires at most one synthesizer, found {len(synthesizers)}"
        )
    return errors


# --- Registries ---

_GENERATORS: dict[str, TopologyGenerator] = {
    "parallel": _parallel_topology,
    "sequential": _sequential_topology,
    "leader": _leader_topology,
    "debate": _debate_topology,
}

_VALIDATORS: dict[str, Callable[[list[dict]], list[str]]] = {
    "parallel": _validate_parallel,
    "sequential": _validate_sequential,
    "leader": _validate_leader,
    "debate": _validate_debate,
}


def register_topology(name: str, generator: TopologyGenerator,
                      validator: Callable[[list[dict]], list[str]] | None = None):
    """Register a custom topology generator (e.g., debate, iterative)."""
    _GENERATORS[name] = generator
    if validator:
        _VALIDATORS[name] = validator
