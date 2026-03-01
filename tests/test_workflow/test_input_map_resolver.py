"""Tests for InputMapResolver and decoupled stage I/O.

Covers:
- input_map resolution (workflow refs, stage refs, structured/raw)
- Dynamic inputs override input_map
- Passthrough mode bypass
- Required input errors when missing from input_map
- Optional input defaults when not in input_map
- Convergence input_map from parallel branches
- Backward compat: SourceResolver fallback when no input_map
- NodeBuilder._find_input_map extraction
- Same stage reused with different input_map in two workflows
"""

import pytest

from temper_ai.workflow.context_provider import (
    _STAGE_INPUT_MAP_KEY,
    ContextResolutionError,
    InputMapResolver,
    PredecessorResolver,
    _get_input_default,
    _is_passthrough,
)

# ── Helpers ────────────────────────────────────────────────────────

# Use string literals for state keys to avoid circular import
# (stage.executors.__init__ → _parallel_helpers → context_provider)
_WORKFLOW_INPUTS = "workflow_inputs"
_STAGE_OUTPUTS = "stage_outputs"
_TRACKER = "tracker"
_CONFIG_LOADER = "config_loader"
_WORKFLOW_ID = "workflow_id"
_TOOL_REGISTRY = "tool_registry"
_DYNAMIC_INPUTS = "_dynamic_inputs"


def _make_state(**kwargs):
    """Build a minimal workflow state."""
    return {
        _WORKFLOW_INPUTS: kwargs.get("workflow_inputs", {}),
        _STAGE_OUTPUTS: kwargs.get("stage_outputs", {}),
        _TRACKER: None,
        _CONFIG_LOADER: None,
        _WORKFLOW_ID: "test-wf",
    }


def _make_stage_config(inputs=None, name="test_stage", passthrough=False):
    """Build a minimal stage config dict."""
    config = {"stage": {"name": name, "agents": ["a1"]}}
    if inputs is not None:
        config["stage"]["inputs"] = inputs
    if passthrough:
        config["stage"]["passthrough"] = True
    return config


# ── InputMapResolver: input_map resolution ─────────────────────────


class TestInputMapResolverBasic:
    """Tests for InputMapResolver with workflow-level input_map."""

    def test_workflow_source_via_input_map(self):
        """input_map maps input to workflow.X — resolves from workflow_inputs."""
        resolver = InputMapResolver()
        state = _make_state(workflow_inputs={"question": "How does it work?"})
        state[_STAGE_INPUT_MAP_KEY] = {"question": "workflow.question"}
        config = _make_stage_config(
            inputs={"question": {"type": "string", "required": True}},
        )
        result = resolver.resolve(config, state)
        assert result["question"] == "How does it work?"
        assert result["_context_meta"]["mode"] == "input-map"

    def test_stage_source_via_input_map(self):
        """input_map maps input to <stage>.<field> — resolves from stage_outputs."""
        resolver = InputMapResolver()
        state = _make_state(
            stage_outputs={
                "analyze": {
                    "structured": {},
                    "raw": {},
                    "output": "Analysis result",
                },
            },
        )
        state[_STAGE_INPUT_MAP_KEY] = {"analysis": "analyze.output"}
        config = _make_stage_config(
            inputs={"analysis": {"type": "string", "required": True}},
        )
        result = resolver.resolve(config, state)
        assert result["analysis"] == "Analysis result"

    def test_structured_source_via_input_map(self):
        """input_map maps to <stage>.structured.<field>."""
        resolver = InputMapResolver()
        state = _make_state(
            stage_outputs={
                "ctx_analyze": {
                    "structured": {"severity": "high"},
                    "raw": {"severity": "low"},
                },
            },
        )
        state[_STAGE_INPUT_MAP_KEY] = {"severity": "ctx_analyze.structured.severity"}
        config = _make_stage_config(
            inputs={"severity": {"type": "string", "required": True}},
        )
        result = resolver.resolve(config, state)
        assert result["severity"] == "high"

    def test_raw_source_via_input_map(self):
        """input_map maps to <stage>.raw.<field>."""
        resolver = InputMapResolver()
        state = _make_state(
            stage_outputs={
                "ctx_analyze": {
                    "structured": {"severity": "high"},
                    "raw": {"severity": "low"},
                },
            },
        )
        state[_STAGE_INPUT_MAP_KEY] = {"severity": "ctx_analyze.raw.severity"}
        config = _make_stage_config(
            inputs={"severity": {"type": "string", "required": True}},
        )
        result = resolver.resolve(config, state)
        assert result["severity"] == "low"

    def test_multiple_inputs_via_input_map(self):
        """input_map with multiple entries resolves each independently."""
        resolver = InputMapResolver()
        state = _make_state(
            workflow_inputs={"question": "test?"},
            stage_outputs={
                "analyze": {
                    "structured": {"confidence": 0.9},
                    "raw": {},
                    "output": "done",
                },
            },
        )
        state[_STAGE_INPUT_MAP_KEY] = {
            "question": "workflow.question",
            "analysis": "analyze.output",
            "confidence": "analyze.structured.confidence",
        }
        config = _make_stage_config(
            inputs={
                "question": {"type": "string", "required": True},
                "analysis": {"type": "string", "required": True},
                "confidence": {"type": "number", "required": True},
            },
        )
        result = resolver.resolve(config, state)
        assert result["question"] == "test?"
        assert result["analysis"] == "done"
        assert result["confidence"] == 0.9

    def test_input_map_recorded_in_context_meta(self):
        """_context_meta includes the input_map used."""
        resolver = InputMapResolver()
        state = _make_state(workflow_inputs={"q": "hello"})
        state[_STAGE_INPUT_MAP_KEY] = {"q": "workflow.q"}
        config = _make_stage_config(inputs={"q": {"type": "string", "required": True}})
        result = resolver.resolve(config, state)
        meta = result["_context_meta"]
        assert meta["mode"] == "input-map"
        assert meta["input_map"] == {"q": "workflow.q"}

    def test_infrastructure_keys_included(self):
        """Infrastructure keys are always copied into resolved context."""
        resolver = InputMapResolver()
        state = _make_state(workflow_inputs={"q": "x"})
        state[_STAGE_INPUT_MAP_KEY] = {"q": "workflow.q"}
        state[_TRACKER] = "mock_tracker"
        state[_TOOL_REGISTRY] = "mock_registry"
        config = _make_stage_config(inputs={"q": {"type": "string", "required": True}})
        result = resolver.resolve(config, state)
        assert result[_TRACKER] == "mock_tracker"
        assert result[_TOOL_REGISTRY] == "mock_registry"


# ── InputMapResolver: defaults and errors ──────────────────────────


class TestInputMapResolverDefaults:
    """Tests for default values and error handling in InputMapResolver."""

    def test_optional_input_uses_default_when_source_missing(self):
        """Optional input in input_map with missing source uses stage default."""
        resolver = InputMapResolver()
        state = _make_state()  # No workflow_inputs, no stage_outputs
        state[_STAGE_INPUT_MAP_KEY] = {"feedback": "workflow.feedback"}
        config = _make_stage_config(
            inputs={
                "feedback": {
                    "type": "string",
                    "required": False,
                    "default": "no feedback",
                },
            },
        )
        result = resolver.resolve(config, state)
        assert result["feedback"] == "no feedback"
        assert "feedback" in result["_context_meta"]["defaults_used"]

    def test_required_input_raises_when_source_missing(self):
        """Required input in input_map raises ContextResolutionError when source missing."""
        resolver = InputMapResolver()
        state = _make_state()
        state[_STAGE_INPUT_MAP_KEY] = {"question": "workflow.question"}
        config = _make_stage_config(
            inputs={"question": {"type": "string", "required": True}},
            name="my_stage",
        )
        with pytest.raises(ContextResolutionError, match="question"):
            resolver.resolve(config, state)

    def test_declared_input_not_in_input_map_uses_default(self):
        """Declared optional input NOT in input_map gets its default."""
        resolver = InputMapResolver()
        state = _make_state(workflow_inputs={"q": "hello"})
        state[_STAGE_INPUT_MAP_KEY] = {"q": "workflow.q"}
        config = _make_stage_config(
            inputs={
                "q": {"type": "string", "required": True},
                "extra": {"type": "string", "required": False, "default": "fallback"},
            },
        )
        result = resolver.resolve(config, state)
        assert result["q"] == "hello"
        assert result["extra"] == "fallback"
        assert "extra" in result["_context_meta"]["defaults_used"]

    def test_required_input_not_in_input_map_raises(self):
        """Required input declared in stage but missing from input_map raises."""
        resolver = InputMapResolver()
        state = _make_state(workflow_inputs={"q": "hello"})
        state[_STAGE_INPUT_MAP_KEY] = {"q": "workflow.q"}
        config = _make_stage_config(
            inputs={
                "q": {"type": "string", "required": True},
                "missing_required": {"type": "string", "required": True},
            },
            name="my_stage",
        )
        with pytest.raises(ContextResolutionError, match="missing_required"):
            resolver.resolve(config, state)

    def test_required_input_with_default_not_in_map_uses_default(self):
        """Required input with a default value, not in input_map, uses default."""
        resolver = InputMapResolver()
        state = _make_state(workflow_inputs={"q": "hello"})
        state[_STAGE_INPUT_MAP_KEY] = {"q": "workflow.q"}
        config = _make_stage_config(
            inputs={
                "q": {"type": "string", "required": True},
                "has_default": {"type": "string", "required": True, "default": "ok"},
            },
        )
        result = resolver.resolve(config, state)
        assert result["has_default"] == "ok"


# ── InputMapResolver: dynamic inputs override ─────────────────────


class TestInputMapResolverDynamic:
    """Tests for dynamic input override in InputMapResolver."""

    def test_dynamic_inputs_override_input_map(self):
        """DYNAMIC_INPUTS in state takes priority over input_map."""
        resolver = InputMapResolver()
        state = _make_state(workflow_inputs={"q": "from-workflow"})
        state[_STAGE_INPUT_MAP_KEY] = {"q": "workflow.q"}
        state[_DYNAMIC_INPUTS] = {
            "q": "from-dynamic",
            "extra": "dynamic-extra",
        }
        config = _make_stage_config(
            inputs={"q": {"type": "string", "required": True}},
        )
        result = resolver.resolve(config, state)
        assert result["q"] == "from-dynamic"
        assert result["extra"] == "dynamic-extra"
        assert result["_context_meta"]["mode"] == "dynamic"

    def test_dynamic_inputs_without_input_map(self):
        """DYNAMIC_INPUTS works even without input_map in state."""
        resolver = InputMapResolver()
        state = _make_state()
        state[_DYNAMIC_INPUTS] = {"data": "dynamic-data"}
        config = _make_stage_config()
        result = resolver.resolve(config, state)
        assert result["data"] == "dynamic-data"
        assert result["_context_meta"]["mode"] == "dynamic"


# ── InputMapResolver: passthrough mode ────────────────────────────


class TestInputMapResolverPassthrough:
    """Tests for passthrough mode in InputMapResolver."""

    def test_passthrough_returns_full_state(self):
        """passthrough: true returns full state even with input_map."""
        resolver = InputMapResolver()
        state = _make_state(
            workflow_inputs={"topic": "test"},
        )
        state[_STAGE_INPUT_MAP_KEY] = {"topic": "workflow.topic"}
        config = _make_stage_config(passthrough=True)
        result = resolver.resolve(config, state)
        assert result["_context_meta"]["mode"] == "passthrough"
        assert result["topic"] == "test"

    def test_passthrough_ignores_dynamic_inputs(self):
        """passthrough: true takes priority over dynamic inputs."""
        resolver = InputMapResolver()
        state = _make_state(workflow_inputs={"x": "from-wf"})
        state[_DYNAMIC_INPUTS] = {"x": "from-dynamic"}
        config = _make_stage_config(passthrough=True)
        result = resolver.resolve(config, state)
        assert result["_context_meta"]["mode"] == "passthrough"
        assert result["x"] == "from-wf"


# ── InputMapResolver: backward compat ─────────────────────────────


class TestInputMapResolverBackwardCompat:
    """Tests for SourceResolver fallback when no input_map."""

    def test_no_input_map_delegates_to_source_resolver(self):
        """Without input_map in state, falls back to SourceResolver."""
        resolver = InputMapResolver()
        state = _make_state(
            workflow_inputs={"suggestion_text": "Add button"},
        )
        config = _make_stage_config(
            inputs={
                "suggestion_text": {
                    "source": "workflow.suggestion_text",
                    "required": True,
                },
            },
        )
        result = resolver.resolve(config, state)
        assert result["suggestion_text"] == "Add button"
        assert result["_context_meta"]["mode"] == "source-resolved"

    def test_no_input_map_no_inputs_delegates_to_passthrough(self):
        """Without input_map and no stage inputs, falls through to passthrough."""
        resolver = InputMapResolver()
        state = _make_state(workflow_inputs={"topic": "testing"})
        config = _make_stage_config(inputs=None)
        result = resolver.resolve(config, state)
        assert result.get("topic") == "testing"
        assert result["_context_meta"]["mode"] == "passthrough"

    def test_empty_input_map_delegates_to_source_resolver(self):
        """Empty input_map (falsy) falls back to SourceResolver."""
        resolver = InputMapResolver()
        state = _make_state(workflow_inputs={"q": "hello"})
        state[_STAGE_INPUT_MAP_KEY] = {}  # empty
        config = _make_stage_config(
            inputs={
                "q": {"source": "workflow.q", "required": True},
            },
        )
        result = resolver.resolve(config, state)
        assert result["q"] == "hello"
        assert result["_context_meta"]["mode"] == "source-resolved"


# ── InputMapResolver: DAG wiring ──────────────────────────────────


class TestInputMapResolverDAG:
    """Tests for DAG wiring through InputMapResolver."""

    def test_set_dag_forwards_to_predecessor(self):
        """set_dag() forwards to PredecessorResolver."""
        predecessor = PredecessorResolver()
        resolver = InputMapResolver(fallback=predecessor)
        assert resolver._predecessor is predecessor

        mock_dag = object()
        resolver.set_dag(mock_dag)
        assert predecessor._dag is mock_dag

    def test_set_dag_no_predecessor_is_noop(self):
        """set_dag() is a no-op when no PredecessorResolver."""
        resolver = InputMapResolver()
        resolver.set_dag(object())  # Should not raise

    def test_isinstance_context_provider(self):
        """InputMapResolver satisfies the ContextProvider protocol."""
        from temper_ai.workflow.context_provider import ContextProvider

        resolver = InputMapResolver()
        assert isinstance(resolver, ContextProvider)


# ── _is_passthrough helper ────────────────────────────────────────


class TestIsPassthrough:
    """Tests for _is_passthrough helper."""

    def test_dict_with_passthrough_true(self):
        config = {"stage": {"name": "s", "passthrough": True}}
        assert _is_passthrough(config) is True

    def test_dict_without_passthrough(self):
        config = {"stage": {"name": "s"}}
        assert _is_passthrough(config) is False

    def test_dict_passthrough_false(self):
        config = {"stage": {"name": "s", "passthrough": False}}
        assert _is_passthrough(config) is False

    def test_flat_dict(self):
        config = {"name": "s", "passthrough": True}
        assert _is_passthrough(config) is True

    def test_object_with_stage_attr(self):
        class MockStage:
            passthrough = True

        class MockConfig:
            stage = MockStage()

        assert _is_passthrough(MockConfig()) is True

    def test_object_without_passthrough(self):
        class MockStage:
            pass

        class MockConfig:
            stage = MockStage()

        assert _is_passthrough(MockConfig()) is False


# ── _get_input_default helper ─────────────────────────────────────


class TestGetInputDefault:
    """Tests for _get_input_default helper."""

    def test_unknown_input_treated_as_required(self):
        default, required = _get_input_default({}, "missing")
        assert default is None
        assert required is True

    def test_non_dict_decl_treated_as_required(self):
        default, required = _get_input_default({"x": "not-a-dict"}, "x")
        assert default is None
        assert required is True

    def test_required_input(self):
        default, required = _get_input_default(
            {"x": {"type": "string", "required": True}}, "x"
        )
        assert default is None
        assert required is True

    def test_optional_with_default(self):
        default, required = _get_input_default(
            {"x": {"type": "string", "required": False, "default": "fallback"}}, "x"
        )
        assert default == "fallback"
        assert required is False

    def test_optional_no_default(self):
        default, required = _get_input_default(
            {"x": {"type": "string", "required": False}}, "x"
        )
        assert default is None
        assert required is False


# ── NodeBuilder._find_input_map ───────────────────────────────────


class TestNodeBuilderFindInputMap:
    """Tests for NodeBuilder._find_input_map extraction."""

    def _make_builder(self):
        from unittest.mock import MagicMock

        from temper_ai.workflow.node_builder import NodeBuilder

        return NodeBuilder(
            config_loader=MagicMock(),
            tool_registry=MagicMock(),
            executors={"sequential": MagicMock()},
        )

    def test_finds_input_map_from_dict_config(self):
        builder = self._make_builder()
        wf = {
            "workflow": {
                "stages": [
                    {
                        "name": "analyze",
                        "stage_ref": "configs/stages/analyze.yaml",
                        "input_map": {"question": "workflow.question"},
                    },
                ],
            },
        }
        result = builder._find_input_map("analyze", wf)
        assert result == {"question": "workflow.question"}

    def test_returns_none_when_no_input_map(self):
        builder = self._make_builder()
        wf = {
            "workflow": {
                "stages": [
                    {"name": "analyze", "stage_ref": "configs/stages/analyze.yaml"},
                ],
            },
        }
        result = builder._find_input_map("analyze", wf)
        assert result is None

    def test_returns_none_for_empty_input_map(self):
        builder = self._make_builder()
        wf = {
            "workflow": {
                "stages": [
                    {"name": "analyze", "input_map": {}},
                ],
            },
        }
        result = builder._find_input_map("analyze", wf)
        assert result is None

    def test_returns_none_for_unknown_stage(self):
        builder = self._make_builder()
        wf = {
            "workflow": {
                "stages": [
                    {"name": "analyze", "input_map": {"q": "workflow.q"}},
                ],
            },
        }
        result = builder._find_input_map("nonexistent", wf)
        assert result is None

    def test_finds_input_map_from_object_config(self):
        """Handles Pydantic-like workflow config with .workflow.stages."""
        builder = self._make_builder()

        class MockStageRef:
            def __init__(self, name, input_map=None):
                self.name = name
                self.input_map = input_map

        class MockWorkflow:
            stages = [
                MockStageRef("s1", input_map={"x": "workflow.x"}),
                MockStageRef("s2"),
            ]

        class MockConfig:
            workflow = MockWorkflow()

        assert builder._find_input_map("s1", MockConfig()) == {"x": "workflow.x"}
        assert builder._find_input_map("s2", MockConfig()) is None

    def test_finds_input_map_flat_dict(self):
        """Handles workflow config without nested 'workflow' key."""
        builder = self._make_builder()
        wf = {
            "stages": [
                {"name": "s1", "input_map": {"a": "workflow.a"}},
            ],
        }
        result = builder._find_input_map("s1", wf)
        assert result == {"a": "workflow.a"}


# ── Integration: same stage reused with different input_map ───────


class TestReusableStageIntegration:
    """Test same stage config used in two workflows with different input_map."""

    def test_same_stage_different_input_map(self):
        """Same stage config receives different inputs based on workflow input_map."""
        resolver = InputMapResolver()

        # Stage config with two required inputs (no source refs)
        stage_config = _make_stage_config(
            inputs={
                "text": {"type": "string", "required": True},
                "context": {"type": "string", "required": False, "default": "none"},
            },
            name="generic_analyzer",
        )

        # Workflow A: maps text from workflow input, context from stage output
        state_a = _make_state(
            workflow_inputs={"user_text": "Hello from workflow A"},
            stage_outputs={
                "prior": {"structured": {}, "raw": {}, "output": "prior context A"}
            },
        )
        state_a[_STAGE_INPUT_MAP_KEY] = {
            "text": "workflow.user_text",
            "context": "prior.output",
        }

        result_a = resolver.resolve(stage_config, state_a)
        assert result_a["text"] == "Hello from workflow A"
        assert result_a["context"] == "prior context A"

        # Workflow B: maps text from a different stage, no context mapping
        state_b = _make_state(
            stage_outputs={
                "extractor": {"structured": {}, "raw": {}, "output": "extracted text"}
            },
        )
        state_b[_STAGE_INPUT_MAP_KEY] = {
            "text": "extractor.output",
        }

        result_b = resolver.resolve(stage_config, state_b)
        assert result_b["text"] == "extracted text"
        assert result_b["context"] == "none"  # default


# ── Convergence input_map ─────────────────────────────────────────


class TestConvergenceInputMap:
    """Tests for convergence stage input_map from parallel branches."""

    def test_convergence_input_map_resolves_from_branches(self):
        """Convergence input_map resolves from parallel branch outputs."""
        resolver = InputMapResolver()
        state = _make_state(
            stage_outputs={
                "branch_a": {
                    "structured": {"score": 0.8},
                    "raw": {},
                    "output": "result A",
                },
                "branch_b": {
                    "structured": {"score": 0.6},
                    "raw": {},
                    "output": "result B",
                },
            },
        )
        state[_STAGE_INPUT_MAP_KEY] = {
            "result_a": "branch_a.output",
            "result_b": "branch_b.output",
            "score_a": "branch_a.structured.score",
            "score_b": "branch_b.structured.score",
        }
        config = _make_stage_config(
            inputs={
                "result_a": {"type": "string", "required": True},
                "result_b": {"type": "string", "required": True},
                "score_a": {"type": "number", "required": True},
                "score_b": {"type": "number", "required": True},
            },
            name="convergence_stage",
        )
        result = resolver.resolve(config, state)
        assert result["result_a"] == "result A"
        assert result["result_b"] == "result B"
        assert result["score_a"] == 0.8
        assert result["score_b"] == 0.6


# ── _STAGE_INPUT_MAP_KEY constant ─────────────────────────────────


class TestStageInputMapKey:
    """Verify the state key constant matches between modules."""

    def test_key_matches_state_keys(self):
        from temper_ai.stage.executors.state_keys import StateKeys

        assert _STAGE_INPUT_MAP_KEY == StateKeys.STAGE_INPUT_MAP

    def test_key_value(self):
        assert _STAGE_INPUT_MAP_KEY == "_stage_input_map"
