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


class TestDebateTopology:
    def _debaters(self, *names):
        return [{"name": n, "type": "llm"} for n in names]

    def test_default_3_rounds_with_default_synthesizer(self):
        # 2 debaters + last-as-synthesizer + 3 rounds = 2*3 + 1 = 7 nodes
        agents = self._debaters("pm", "engineer", "synth")
        nodes = build_topology("debate", agents)
        assert len(nodes) == 7

        names = [n.name for n in nodes]
        assert "pm__r1" in names
        assert "pm__r2" in names
        assert "pm__r3" in names
        assert "engineer__r1" in names
        assert "engineer__r3" in names
        assert "synth" in names  # synthesizer keeps its plain name

    def test_explicit_synthesizer_role(self):
        agents = [
            {"name": "pm"},
            {"name": "designer"},
            {"name": "engineer"},
            {"name": "prd_writer", "role": "synthesizer"},
        ]
        nodes = build_topology("debate", agents, {"rounds": 2})
        # 3 debaters * 2 rounds + 1 synth = 7
        assert len(nodes) == 7
        synth = next(n for n in nodes if n.name == "prd_writer")
        assert synth.agent_config.get("_receives_strategy_context") is True

    def test_round_1_has_no_deps(self):
        agents = self._debaters("a", "b", "synth")
        nodes = build_topology("debate", agents, {"rounds": 2})
        r1 = [n for n in nodes if n.name.endswith("__r1")]
        for n in r1:
            assert n.depends_on == []

    def test_round_2_depends_on_all_of_round_1(self):
        agents = self._debaters("a", "b", "synth")
        nodes = build_topology("debate", agents, {"rounds": 3})
        r2 = [n for n in nodes if n.name.endswith("__r2")]
        for n in r2:
            assert set(n.depends_on) == {"a__r1", "b__r1"}

    def test_round_3_depends_on_all_of_round_2(self):
        agents = self._debaters("a", "b", "synth")
        nodes = build_topology("debate", agents, {"rounds": 3})
        r3 = [n for n in nodes if n.name.endswith("__r3")]
        for n in r3:
            assert set(n.depends_on) == {"a__r2", "b__r2"}

    def test_round_2_plus_receives_strategy_context(self):
        agents = self._debaters("a", "b", "synth")
        nodes = build_topology("debate", agents, {"rounds": 3})
        for n in nodes:
            if n.name.endswith("__r1"):
                # Round 1: no strategy context, opening positions
                assert not n.agent_config.get("_receives_strategy_context")
            elif n.name.endswith("__r2") or n.name.endswith("__r3"):
                # Later rounds: see prior round via strategy context
                assert n.agent_config.get("_receives_strategy_context") is True

    def test_synthesizer_depends_on_every_round(self):
        agents = self._debaters("a", "b", "synth")
        nodes = build_topology("debate", agents, {"rounds": 3})
        synth = next(n for n in nodes if n.name == "synth")
        # 2 debaters * 3 rounds = 6 dependency nodes
        assert len(synth.depends_on) == 6
        assert set(synth.depends_on) == {
            "a__r1", "b__r1", "a__r2", "b__r2", "a__r3", "b__r3",
        }

    def test_synthesizer_receives_strategy_context(self):
        agents = self._debaters("a", "b", "synth")
        nodes = build_topology("debate", agents)
        synth = next(n for n in nodes if n.name == "synth")
        assert synth.agent_config.get("_receives_strategy_context") is True

    def test_rounds_1_is_legal_degenerate(self):
        # rounds=1 reduces to "everyone writes once, synthesizer reads".
        # Effectively the same shape as the leader pattern.
        agents = self._debaters("a", "b", "synth")
        nodes = build_topology("debate", agents, {"rounds": 1})
        assert len(nodes) == 3  # 2 debaters + synth
        synth = next(n for n in nodes if n.name == "synth")
        assert set(synth.depends_on) == {"a__r1", "b__r1"}

    def test_rounds_zero_raises(self):
        agents = self._debaters("a", "b", "synth")
        with pytest.raises(ValidationError, match="rounds >= 1"):
            build_topology("debate", agents, {"rounds": 0})

    def test_validation_requires_3_agents(self):
        with pytest.raises(ValidationError, match="at least 3"):
            build_topology("debate", self._debaters("only_two", "wow"))

    def test_validation_multiple_synthesizers_rejected(self):
        agents = [
            {"name": "a", "role": "synthesizer"},
            {"name": "b", "role": "synthesizer"},
            {"name": "c"},
        ]
        with pytest.raises(ValidationError, match="at most one synthesizer"):
            build_topology("debate", agents)

    def test_default_rounds_is_3(self):
        agents = self._debaters("a", "b", "synth")
        # Don't pass strategy_config — should default to 3 rounds
        nodes = build_topology("debate", agents)
        assert len(nodes) == 2 * 3 + 1  # 2 debaters * 3 rounds + synth


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
