"""Tests for dynamic fan-out + fan-in convergence.

Phase 6: Dedup, converge signal, state copy per thread, predecessor
integration.
"""

from unittest.mock import MagicMock

from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.workflow.engines._dynamic_edge_helpers import (
    _dedup_targets,
    _execute_convergence,
    _follow_parallel_targets,
)
from temper_ai.workflow.engines.workflow_executor import (
    _normalize_dict_signal,
    _normalize_next_stage_signal,
    _run_parallel_stage_batch,
)

# ---------------------------------------------------------------------------
# Converge signal parsing
# ---------------------------------------------------------------------------


class TestConvergeSignalParsing:
    """Test _normalize_dict_signal with converge field."""

    def test_parallel_with_converge(self):
        """Parallel signal with converge passes through."""
        signal = {
            "mode": "parallel",
            "targets": [{"name": "B"}, {"name": "C"}],
            "converge": {"name": "D"},
        }
        result = _normalize_dict_signal(signal)

        assert result is not None
        assert result["mode"] == "parallel"
        assert len(result["targets"]) == 2
        assert result["converge"] == {"name": "D"}

    def test_parallel_without_converge(self):
        """Parallel signal without converge has no converge key."""
        signal = {
            "mode": "parallel",
            "targets": [{"name": "B"}],
        }
        result = _normalize_dict_signal(signal)

        assert result is not None
        assert "converge" not in result

    def test_converge_invalid_format_ignored(self):
        """Non-dict converge value is ignored."""
        signal = {
            "mode": "parallel",
            "targets": [{"name": "B"}],
            "converge": "not-a-dict",
        }
        result = _normalize_dict_signal(signal)

        assert result is not None
        assert "converge" not in result

    def test_converge_no_name_ignored(self):
        """Converge dict without name is ignored."""
        signal = {
            "mode": "parallel",
            "targets": [{"name": "B"}],
            "converge": {"inputs": {}},
        }
        result = _normalize_dict_signal(signal)

        assert result is not None
        assert "converge" not in result

    def test_sequential_signal_unchanged(self):
        """Sequential signals are unaffected by converge changes."""
        signal = {"name": "B", "inputs": {"x": 1}}
        result = _normalize_dict_signal(signal)

        assert result is not None
        assert result["mode"] == "sequential"


# ---------------------------------------------------------------------------
# Target deduplication
# ---------------------------------------------------------------------------


class TestDedupTargets:
    """Test _dedup_targets."""

    def test_dedup_removes_duplicates(self):
        """Duplicate target names are removed."""
        targets = [
            {"name": "B", "inputs": {}},
            {"name": "C", "inputs": {}},
            {"name": "B", "inputs": {"x": 1}},  # Duplicate
        ]
        stage_nodes = {"B": MagicMock(), "C": MagicMock()}
        result = _dedup_targets(targets, stage_nodes)

        names = [t["name"] for t in result]
        assert names == ["B", "C"]

    def test_dedup_filters_missing_nodes(self):
        """Targets not in stage_nodes are filtered out."""
        targets = [
            {"name": "B", "inputs": {}},
            {"name": "MISSING", "inputs": {}},
        ]
        stage_nodes = {"B": MagicMock()}
        result = _dedup_targets(targets, stage_nodes)

        assert len(result) == 1
        assert result[0]["name"] == "B"

    def test_dedup_empty_targets(self):
        """Empty targets returns empty list."""
        result = _dedup_targets([], {"B": MagicMock()})
        assert result == []

    def test_dedup_preserves_order(self):
        """First occurrence of each name is preserved."""
        targets = [
            {"name": "C", "inputs": {}},
            {"name": "B", "inputs": {}},
            {"name": "A", "inputs": {}},
        ]
        stage_nodes = {
            "A": MagicMock(),
            "B": MagicMock(),
            "C": MagicMock(),
        }
        result = _dedup_targets(targets, stage_nodes)

        names = [t["name"] for t in result]
        assert names == ["C", "B", "A"]


# ---------------------------------------------------------------------------
# State copy per thread
# ---------------------------------------------------------------------------


class TestStateCopyPerThread:
    """Test that _run_parallel_stage_batch uses state copies."""

    def test_parallel_stages_get_independent_state(self):
        """Each parallel stage receives its own copy of state."""
        received_states = []

        def capture_state_node(name_prefix):
            def node_fn(state):
                received_states.append(id(state))
                return {
                    "stage_outputs": {
                        name_prefix: {"output": "done"},
                    },
                    "current_stage": name_prefix,
                }

            return node_fn

        stage_nodes = {
            "B": capture_state_node("B"),
            "C": capture_state_node("C"),
        }
        state = {
            StateKeys.STAGE_OUTPUTS: {},
            StateKeys.CURRENT_STAGE: "",
        }

        _run_parallel_stage_batch(["B", "C"], stage_nodes, state)

        # Each thread should get a different dict object
        assert len(received_states) == 2
        assert received_states[0] != received_states[1]

    def test_original_state_not_mutated_by_threads(self):
        """Original state dict is not mutated by parallel threads."""

        def mutating_node(state):
            state["injected_key"] = "mutated"
            return {
                "stage_outputs": {"s": {"output": "done"}},
                "current_stage": "s",
            }

        stage_nodes = {"s1": mutating_node}
        state = {
            StateKeys.STAGE_OUTPUTS: {},
            StateKeys.CURRENT_STAGE: "",
        }

        _run_parallel_stage_batch(["s1"], stage_nodes, state)

        # Original state should not have the injected key
        assert "injected_key" not in state


# ---------------------------------------------------------------------------
# Convergence execution
# ---------------------------------------------------------------------------


class TestExecuteConvergence:
    """Test _execute_convergence."""

    def test_convergence_stage_runs_once(self):
        """Convergence stage executes exactly once after branches."""
        calls = []

        def negotiate_fn(name, nodes, state, wf_config):
            calls.append(name)
            return state

        stage_nodes = {"D": MagicMock()}
        state = {StateKeys.STAGE_OUTPUTS: {}}

        state, hop_count = _execute_convergence(
            {"name": "D"},
            ["B", "C"],
            stage_nodes,
            state,
            {},
            0,
            negotiate_fn,
        )

        assert calls == ["D"]
        assert hop_count == 1

    def test_convergence_sets_predecessors(self):
        """Convergence records predecessors for PredecessorResolver."""

        def negotiate_fn(name, nodes, state, wf_config):
            return state

        stage_nodes = {"D": MagicMock()}
        state = {StateKeys.STAGE_OUTPUTS: {}}

        state, _ = _execute_convergence(
            {"name": "D"},
            ["B", "C"],
            stage_nodes,
            state,
            {},
            0,
            negotiate_fn,
        )

        assert state["_convergence_predecessors"]["D"] == ["B", "C"]

    def test_convergence_missing_node_skipped(self):
        """Missing convergence stage is skipped without error."""

        def negotiate_fn(name, nodes, state, wf_config):
            return state

        stage_nodes = {}  # D not present
        state = {StateKeys.STAGE_OUTPUTS: {}}

        state, hop_count = _execute_convergence(
            {"name": "D"},
            ["B", "C"],
            stage_nodes,
            state,
            {},
            0,
            negotiate_fn,
        )

        assert hop_count == 0
        assert "_convergence_predecessors" not in state

    def test_convergence_respects_max_hops(self):
        """Convergence does not run if hop limit reached."""
        calls = []

        def negotiate_fn(name, nodes, state, wf_config):
            calls.append(name)
            return state

        stage_nodes = {"D": MagicMock()}
        state = {StateKeys.STAGE_OUTPUTS: {}}

        from temper_ai.workflow.engines._dynamic_edge_helpers import (
            DEFAULT_MAX_DYNAMIC_HOPS,
        )

        state, hop_count = _execute_convergence(
            {"name": "D"},
            ["B"],
            stage_nodes,
            state,
            {},
            DEFAULT_MAX_DYNAMIC_HOPS,
            negotiate_fn,
        )

        assert calls == []
        assert hop_count == DEFAULT_MAX_DYNAMIC_HOPS


# ---------------------------------------------------------------------------
# Full parallel fan-out with convergence
# ---------------------------------------------------------------------------


class TestFollowParallelWithConvergence:
    """Integration tests for parallel fan-out + convergence."""

    def test_parallel_with_converge_field(self):
        """Full flow: parallel fan-out → convergence stage."""
        execution_order = []

        def make_node(name):
            def node_fn(state):
                execution_order.append(("node", name))
                return {
                    "stage_outputs": {name: {"output": f"{name}_done"}},
                    "current_stage": name,
                }

            return node_fn

        def negotiate_fn(name, nodes, state, wf_config):
            execution_order.append(("negotiate", name))
            result = nodes[name](state)
            stage_outputs = state.get(StateKeys.STAGE_OUTPUTS, {})
            stage_outputs.update(result.get("stage_outputs", {}))
            state[StateKeys.STAGE_OUTPUTS] = stage_outputs
            return state

        stage_nodes = {
            "B": make_node("B"),
            "C": make_node("C"),
            "D": make_node("D"),
        }
        targets = [
            {"name": "B", "inputs": {}},
            {"name": "C", "inputs": {}},
        ]
        state = {StateKeys.STAGE_OUTPUTS: {}}

        signal = {
            "targets": targets,
            "mode": "parallel",
            "converge": {"name": "D"},
        }
        state, hop_count = _follow_parallel_targets(
            signal,
            stage_nodes,
            state,
            {},
            0,
            negotiate_fn,
        )

        # D should be in execution order (negotiate)
        negotiate_names = [n for t, n in execution_order if t == "negotiate"]
        assert "D" in negotiate_names

        # Convergence predecessors set
        assert state["_convergence_predecessors"]["D"] == ["B", "C"]

        # B and C outputs present
        assert "B" in state[StateKeys.STAGE_OUTPUTS]
        assert "C" in state[StateKeys.STAGE_OUTPUTS]

    def test_parallel_dedup_prevents_double_execution(self):
        """Duplicate targets in parallel signal run only once."""
        call_count = {}

        def make_node(name):
            def node_fn(state):
                call_count[name] = call_count.get(name, 0) + 1
                return {
                    "stage_outputs": {name: {"output": "done"}},
                    "current_stage": name,
                }

            return node_fn

        def negotiate_fn(name, nodes, state, wf_config):
            return state

        stage_nodes = {
            "B": make_node("B"),
            "C": make_node("C"),
        }
        targets = [
            {"name": "B", "inputs": {}},
            {"name": "B", "inputs": {}},  # Duplicate
            {"name": "C", "inputs": {}},
        ]
        state = {StateKeys.STAGE_OUTPUTS: {}}
        signal = {"targets": targets, "mode": "parallel"}

        _follow_parallel_targets(
            signal,
            stage_nodes,
            state,
            {},
            0,
            negotiate_fn,
        )

        # B should only run once (deduped)
        assert call_count.get("B", 0) <= 1


# ---------------------------------------------------------------------------
# PredecessorResolver integration with convergence
# ---------------------------------------------------------------------------


class TestConvergencePredecessorIntegration:
    """Test PredecessorResolver uses _convergence_predecessors."""

    def test_predecessor_resolver_uses_convergence(self):
        """PredecessorResolver picks up _convergence_predecessors."""
        from temper_ai.workflow.context_provider import PredecessorResolver

        resolver = PredecessorResolver()
        dag = MagicMock()
        dag.predecessors = {"D": []}  # DAG says no predecessors
        resolver.set_dag(dag)

        state = {
            StateKeys.WORKFLOW_INPUTS: {},
            StateKeys.STAGE_OUTPUTS: {
                "B": {"output": "from_B"},
                "C": {"output": "from_C"},
            },
            "_convergence_predecessors": {
                "D": ["B", "C"],
            },
        }

        result = resolver.resolve({"stage": {"name": "D"}}, state)

        assert "B" in result
        assert "C" in result
        assert result["_context_meta"]["predecessors"] == ["B", "C"]


# ---------------------------------------------------------------------------
# Signal normalization with converge (via _normalize_next_stage_signal)
# ---------------------------------------------------------------------------


class TestNormalizeSignalConverge:
    """Test _normalize_next_stage_signal passes converge through."""

    def test_list_signal_no_converge(self):
        """List signals don't have converge."""
        result = _normalize_next_stage_signal([{"name": "B"}])
        assert result is not None
        assert "converge" not in result

    def test_dict_parallel_converge_roundtrip(self):
        """Dict parallel signal with converge survives normalization."""
        raw = {
            "mode": "parallel",
            "targets": [{"name": "B"}, {"name": "C"}],
            "converge": {"name": "D"},
        }
        result = _normalize_next_stage_signal(raw)
        assert result is not None
        assert result["converge"] == {"name": "D"}
