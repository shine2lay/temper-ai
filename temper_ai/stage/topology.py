"""Topology generators — convert strategy name + agents into node layouts.

Strategies are NOT a separate execution layer. They're functions that generate
a list of AgentNodes with appropriate depends_on and input wiring. The graph
executor runs the generated topology the same way it runs any graph.

Usage:
    nodes = build_topology("parallel", agent_configs)
    nodes = build_topology("leader", agent_configs)
    nodes = build_topology("sequential", agent_configs)

A strategy may also generate a node of its own (the Pi team strategy, registered only with
``TEMPER_PI_AGENT`` on, generates one team node), and may register a run-start check: the
loader runs it when a run starts, before any node, and the run does not start if it finds a
problem (see ``GraphLoader.load_workflow(..., run_start=True)``).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.exceptions import TopologyError, ValidationError
from temper_ai.stage.models import NodeConfig, WorkflowConfig
from temper_ai.stage.node import Node

# Type alias for topology generator functions
TopologyGenerator = Callable[[list[dict], dict], Sequence[Node]]
#: A strategy's check: ``(agent_configs)`` or ``(agent_configs, strategy_config)`` -> errors.
TopologyValidator = Callable[..., list[str]]


@dataclass(frozen=True)
class RunStart:
    """One strategy stage as its run-start check sees it, read only: the stage, its members'
    resolved agent configs, the workflow and the run's inputs. A member whose agent config
    could not be loaded is in ``unloaded`` (its name -> the loader's error), not in
    ``agent_configs``."""

    stage: NodeConfig
    agent_configs: list[dict]
    workflow: WorkflowConfig
    inputs: dict
    unloaded: dict[str, str] = field(default_factory=dict)


#: A strategy's run-start check: every problem with the stage, as plain texts.
RunStartCheck = Callable[[RunStart], list[str]]


def build_topology(
    strategy: str,
    agent_configs: list[dict],
    strategy_config: dict | None = None,
) -> list[Node]:
    """Generate node topology from strategy name and agent list.

    Args:
        strategy: Strategy name ("parallel", "sequential", "leader").
        agent_configs: List of resolved agent config dicts.
        strategy_config: Optional strategy-specific config.

    Returns:
        List of nodes (AgentNodes for the built-in strategies) with depends_on set according
        to the strategy pattern.

    Raises:
        TopologyError: Unknown strategy name.
        ValidationError: Strategy requirements not met.
    """
    if strategy not in _GENERATORS:
        raise TopologyError(
            f"Unknown strategy: '{strategy}'. Available: {list(_GENERATORS.keys())}"
        )

    generator = _GENERATORS[strategy]
    errors = _run_validator(_VALIDATORS.get(strategy, lambda _: []), agent_configs,
                            strategy_config or {})
    if errors:
        raise ValidationError(
            f"Strategy '{strategy}' validation failed: {'; '.join(errors)}"
        )

    return list(generator(agent_configs, strategy_config or {}))


def _run_validator(validator: TopologyValidator, agent_configs: list[dict],
                   strategy_config: dict) -> list[str]:
    """Call a strategy's check; one that takes two arguments also gets the strategy_config."""
    try:
        params = list(inspect.signature(validator).parameters.values())
    except (TypeError, ValueError):
        return validator(agent_configs)
    positional = [p for p in params
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)]
    if len(positional) >= 2 or any(p.kind == p.VAR_POSITIONAL for p in positional):
        return validator(agent_configs, strategy_config)
    return validator(agent_configs)


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

_VALIDATORS: dict[str, TopologyValidator] = {
    "parallel": _validate_parallel,
    "sequential": _validate_sequential,
    "leader": _validate_leader,
}

_RUN_START_CHECKS: dict[str, RunStartCheck] = {}


def register_topology(name: str, generator: TopologyGenerator,
                      validator: TopologyValidator | None = None,
                      run_start_check: RunStartCheck | None = None):
    """Register a custom topology generator (e.g., debate, iterative)."""
    _GENERATORS[name] = generator
    if validator:
        _VALIDATORS[name] = validator
    if run_start_check:
        _RUN_START_CHECKS[name] = run_start_check


def available_strategies() -> list[str]:
    """The strategy names a stage can use, in registration order."""
    return list(_GENERATORS)


#: The strategies the loader's "Specify a strategy" hint names: the built-in three and, once
#: registered, team. Other registered topologies were never named there and still are not.
_NAMED_STRATEGIES = ("parallel", "sequential", "leader", "team")


def named_strategies() -> list[str]:
    """The strategies a stage's "Specify a strategy" hint names (see ``_NAMED_STRATEGIES``)."""
    return [name for name in _NAMED_STRATEGIES if name in _GENERATORS]


def run_start_check(strategy: str) -> RunStartCheck | None:
    """The strategy's run-start check, if it registered one."""
    return _RUN_START_CHECKS.get(strategy)


def run_start_options() -> dict:
    """The ``load_workflow`` keywords for a run that is starting: ``run_start=True`` once a
    strategy has registered a run-start check, else none, so that with no such strategy (the
    Pi switch off) the call is exactly what it was."""
    return {"run_start": True} if _RUN_START_CHECKS else {}


# The Pi team strategy registers itself only when its switch (TEMPER_PI_AGENT) is on.
from temper_ai.pi_agent import register_team_if_enabled as _register_team  # noqa: E402

_register_team()
