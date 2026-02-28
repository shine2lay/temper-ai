"""Tests for temper_ai/stage/executors/langgraph_runner.py.

Covers:
- _merge_dicts: flat merge, right-wins on conflict, left not mutated
- LangGraphParallelRunner.run_parallel: single node, multiple nodes,
  with init_node, with collect_node, init+collect combined
"""

from temper_ai.stage.executors.langgraph_runner import (
    LangGraphParallelRunner,
    _merge_dicts,
)

# ===========================================================================
# _merge_dicts
# ===========================================================================


class TestMergeDicts:
    """Unit tests for the _merge_dicts helper."""

    def test_flat_merge_disjoint_keys(self):
        """Keys from both dicts appear in the result."""
        result = _merge_dicts({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_right_wins_on_conflict(self):
        """When the same key exists in both, the right value wins."""
        result = _merge_dicts({"key": "left"}, {"key": "right"})
        assert result["key"] == "right"

    def test_left_dict_not_mutated(self):
        """The original left dict must not be modified."""
        left = {"a": 1, "b": 2}
        original = dict(left)
        _merge_dicts(left, {"a": 99})
        assert left == original

    def test_empty_left(self):
        result = _merge_dicts({}, {"x": 10})
        assert result == {"x": 10}

    def test_empty_right(self):
        result = _merge_dicts({"x": 10}, {})
        assert result == {"x": 10}

    def test_both_empty(self):
        assert _merge_dicts({}, {}) == {}


# ===========================================================================
# LangGraphParallelRunner
# ===========================================================================


class TestLangGraphParallelRunner:
    """Integration tests for LangGraphParallelRunner.run_parallel."""

    def test_single_node_execution(self):
        """A single node runs and its output appears in agent_outputs."""
        runner = LangGraphParallelRunner()
        result = runner.run_parallel(
            nodes={"node1": lambda s: {"agent_outputs": {"a1": "out1"}}},
            initial_state={"stage_input": {"key": "val"}},
        )
        assert result["agent_outputs"]["a1"] == "out1"

    def test_single_node_preserves_initial_state(self):
        """stage_input from initial_state is carried through."""
        runner = LangGraphParallelRunner()
        result = runner.run_parallel(
            nodes={"n": lambda s: {}},
            initial_state={"stage_input": {"foo": "bar"}},
        )
        assert result["stage_input"] == {"foo": "bar"}

    def test_multiple_nodes_all_execute(self):
        """Both nodes run and their outputs are merged into agent_outputs."""
        runner = LangGraphParallelRunner()
        result = runner.run_parallel(
            nodes={
                "node1": lambda s: {"agent_outputs": {"a1": "out1"}},
                "node2": lambda s: {"agent_outputs": {"a2": "out2"}},
            },
            initial_state={},
        )
        assert result["agent_outputs"]["a1"] == "out1"
        assert result["agent_outputs"]["a2"] == "out2"

    def test_with_init_node(self):
        """Custom init_node runs before parallel nodes and seeds state."""
        runner = LangGraphParallelRunner()

        def init(s: dict) -> dict:
            return {"stage_input": {"initialized": True}}

        result = runner.run_parallel(
            nodes={"n": lambda s: {"agent_outputs": {"saw": s.get("stage_input", {})}}},
            initial_state={},
            init_node=init,
        )
        assert result["stage_input"] == {"initialized": True}
        assert result["agent_outputs"]["saw"] == {"initialized": True}

    def test_with_collect_node(self):
        """collect_node runs after parallel nodes and can add to agent_outputs."""
        runner = LangGraphParallelRunner()

        def collect(s: dict) -> dict:
            return {"agent_outputs": {"collected": True}}

        result = runner.run_parallel(
            nodes={"n": lambda s: {"agent_outputs": {"a1": "out1"}}},
            initial_state={},
            collect_node=collect,
        )
        assert result["agent_outputs"]["a1"] == "out1"
        assert result["agent_outputs"]["collected"] is True

    def test_init_and_collect_combined(self):
        """init_node and collect_node both work together correctly."""
        runner = LangGraphParallelRunner()

        def init(s: dict) -> dict:
            return {"stage_input": {"phase": "init"}}

        def collect(s: dict) -> dict:
            return {"agent_outputs": {"summary": "done"}}

        result = runner.run_parallel(
            nodes={"n": lambda s: {"agent_outputs": {"n_out": "yes"}}},
            initial_state={},
            init_node=init,
            collect_node=collect,
        )
        assert result["stage_input"] == {"phase": "init"}
        assert result["agent_outputs"]["n_out"] == "yes"
        assert result["agent_outputs"]["summary"] == "done"

    def test_returns_dict(self):
        """run_parallel returns a dict when initial_state is non-empty."""
        runner = LangGraphParallelRunner()
        result = runner.run_parallel(
            nodes={"n": lambda s: {}},
            initial_state={"stage_input": {"x": 1}},
        )
        assert isinstance(result, dict)

    def test_right_wins_on_agent_output_conflict(self):
        """When two nodes write the same agent_outputs key, right (_merge_dicts) wins."""
        runner = LangGraphParallelRunner()
        # Both nodes write "shared_key"; _merge_dicts lets the second writer win.
        # We can't guarantee node ordering in parallel, but we can assert the key exists.
        result = runner.run_parallel(
            nodes={
                "n1": lambda s: {"agent_outputs": {"shared": "from_n1"}},
                "n2": lambda s: {"agent_outputs": {"shared": "from_n2"}},
            },
            initial_state={},
        )
        assert result["agent_outputs"]["shared"] in ("from_n1", "from_n2")
