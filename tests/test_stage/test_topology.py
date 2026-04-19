"""Tests for stage/topology.py — strategy topology generators."""

import pytest

from temper_ai.stage.exceptions import TopologyError, ValidationError
from temper_ai.stage.topology import (
    build_topology,
    register_topology,
)


def _agents(*names):
    """Helper to create agent config dicts."""
    return [{"name": n, "type": "llm"} for n in names]


class TestParallelTopology:
    def test_generates_independent_nodes(self):
        nodes = build_topology("parallel", _agents("a", "b", "c"))
        assert len(nodes) == 3
        for node in nodes:
            assert node.depends_on == []

    def test_preserves_agent_names(self):
        nodes = build_topology("parallel", _agents("coder_a", "coder_b"))
        names = [n.name for n in nodes]
        assert names == ["coder_a", "coder_b"]

    def test_validation_requires_two_agents(self):
        with pytest.raises(ValidationError, match="at least 2"):
            build_topology("parallel", _agents("lonely"))


class TestSequentialTopology:
    def test_generates_linear_chain(self):
        nodes = build_topology("sequential", _agents("a", "b", "c"))
        assert len(nodes) == 3
        assert nodes[0].depends_on == []
        assert nodes[1].depends_on == ["a"]
        assert nodes[2].depends_on == ["b"]

    def test_no_input_map_on_subsequent(self):
        """Subsequent agents have no input_map so parent data flows through."""
        nodes = build_topology("sequential", _agents("first", "second"))
        assert nodes[1].config.input_map is None

    def test_first_node_no_input_map(self):
        nodes = build_topology("sequential", _agents("a", "b"))
        assert nodes[0].config.input_map is None

    def test_validation_requires_two_agents(self):
        with pytest.raises(ValidationError, match="at least 2"):
            build_topology("sequential", _agents("lonely"))


class TestLeaderTopology:
    def test_leader_by_role(self):
        agents = [
            {"name": "worker1"},
            {"name": "worker2"},
            {"name": "decider", "role": "leader"},
        ]
        nodes = build_topology("leader", agents)
        assert len(nodes) == 3

        # Workers first (no deps)
        workers = [n for n in nodes if n.name != "decider"]
        assert all(n.depends_on == [] for n in workers)

        # Leader last (depends on workers)
        leader = next(n for n in nodes if n.name == "decider")
        assert set(leader.depends_on) == {"worker1", "worker2"}

    def test_default_leader_is_last(self):
        agents = _agents("a", "b", "c")
        nodes = build_topology("leader", agents)

        leader = nodes[-1]
        assert leader.name == "c"
        assert set(leader.depends_on) == {"a", "b"}

    def test_leader_receives_strategy_context(self):
        agents = [
            {"name": "w1"},
            {"name": "lead", "role": "leader"},
        ]
        nodes = build_topology("leader", agents)
        leader = next(n for n in nodes if n.name == "lead")
        assert leader.agent_config.get("_receives_strategy_context") is True

    def test_workers_dont_receive_strategy_context(self):
        agents = [
            {"name": "w1"},
            {"name": "w2"},
            {"name": "lead", "role": "leader"},
        ]
        nodes = build_topology("leader", agents)
        workers = [n for n in nodes if n.name != "lead"]
        for w in workers:
            assert not w.agent_config.get("_receives_strategy_context")

    def test_validation_requires_two_agents(self):
        with pytest.raises(ValidationError, match="at least 2"):
            build_topology("leader", _agents("lonely"))

    def test_validation_multiple_leaders(self):
        agents = [
            {"name": "a", "role": "leader"},
            {"name": "b", "role": "leader"},
        ]
        with pytest.raises(ValidationError, match="exactly one leader"):
            build_topology("leader", agents)


class TestUnknownStrategy:
    def test_raises_topology_error(self):
        with pytest.raises(TopologyError, match="Unknown strategy"):
            build_topology("nonexistent", _agents("a", "b"))


class TestRegisterTopology:
    def test_register_custom_topology(self):
        def custom_topo(agents, config):
            from temper_ai.stage.agent_node import AgentNode
            from temper_ai.stage.models import NodeConfig
            return [AgentNode(NodeConfig(name=a["name"]), a) for a in agents]

        register_topology("custom", custom_topo)
        nodes = build_topology("custom", _agents("x", "y"))
        assert len(nodes) == 2

    def test_register_with_validator(self):
        def always_fail_validator(agents):
            return ["Custom validation failed"]

        def noop_topo(agents, config):
            return []

        register_topology("strict", noop_topo, always_fail_validator)
        with pytest.raises(ValidationError, match="Custom validation failed"):
            build_topology("strict", _agents("a"))
