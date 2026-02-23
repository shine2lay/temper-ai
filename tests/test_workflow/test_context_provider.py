"""Tests for stage-level context management: schemas, provider, and resolver."""

import pytest

from temper_ai.workflow.context_provider import (
    ContextResolutionError,
    PassthroughResolver,
    SourceResolver,
)
from temper_ai.workflow.context_schemas import (
    StageInputDeclaration,
    StageOutputDeclaration,
    parse_stage_inputs,
    parse_stage_outputs,
)

# ── Schema Tests ────────────────────────────────────────────────────


class TestStageInputDeclaration:
    """Tests for StageInputDeclaration validation."""

    def test_valid_workflow_source(self):
        decl = StageInputDeclaration(source="workflow.suggestion_text")
        assert decl.source == "workflow.suggestion_text"
        assert decl.required is True

    def test_valid_stage_source(self):
        decl = StageInputDeclaration(source="vcs_triage.final_decision")
        assert decl.source == "vcs_triage.final_decision"

    def test_valid_structured_source(self):
        decl = StageInputDeclaration(source="vcs_triage.structured.priority")
        assert decl.source == "vcs_triage.structured.priority"

    def test_valid_raw_source(self):
        decl = StageInputDeclaration(source="vcs_triage.raw.output")
        assert decl.source == "vcs_triage.raw.output"

    def test_valid_nested_path(self):
        decl = StageInputDeclaration(source="workflow.config.nested_field")
        assert decl.source == "workflow.config.nested_field"

    def test_invalid_source_no_field(self):
        with pytest.raises(ValueError, match="Invalid source format"):
            StageInputDeclaration(source="workflow")

    def test_invalid_source_empty(self):
        with pytest.raises(ValueError, match="Invalid source format"):
            StageInputDeclaration(source="")

    def test_invalid_source_bad_chars(self):
        with pytest.raises(ValueError, match="Invalid source format"):
            StageInputDeclaration(source="work flow.field")

    def test_optional_with_default(self):
        decl = StageInputDeclaration(
            source="workflow.optional_field",
            required=False,
            default="fallback",
        )
        assert decl.required is False
        assert decl.default == "fallback"


class TestStageOutputDeclaration:
    """Tests for StageOutputDeclaration."""

    def test_default_type_is_string(self):
        decl = StageOutputDeclaration()
        assert decl.type == "string"

    def test_all_types_valid(self):
        for t in ("string", "list", "dict", "number", "boolean", "any"):
            decl = StageOutputDeclaration(type=t)
            assert decl.type == t

    def test_with_description(self):
        decl = StageOutputDeclaration(type="string", description="Final decision")
        assert decl.description == "Final decision"


class TestParseStageInputs:
    """Tests for parse_stage_inputs()."""

    def test_none_returns_none(self):
        assert parse_stage_inputs(None) is None

    def test_empty_dict_returns_none(self):
        # No source keys → old documentation-only format → passthrough
        result = parse_stage_inputs({"field1": {"type": "string"}})
        assert result is None

    def test_old_format_without_source_returns_none(self):
        raw = {
            "suggestion_text": {"type": "string", "required": True},
            "workspace_path": {"type": "string", "required": True},
        }
        assert parse_stage_inputs(raw) is None

    def test_new_format_with_source(self):
        raw = {
            "suggestion_text": {
                "source": "workflow.suggestion_text",
                "required": True,
            },
            "triage_decision": {
                "source": "vcs_triage.final_decision",
                "required": True,
            },
        }
        result = parse_stage_inputs(raw)
        assert result is not None
        assert len(result) == 2
        assert result["suggestion_text"].source == "workflow.suggestion_text"
        assert result["triage_decision"].source == "vcs_triage.final_decision"

    def test_mixed_format_skips_old_entries(self):
        raw = {
            "suggestion_text": {
                "source": "workflow.suggestion_text",
                "required": True,
            },
            "old_docs_field": {"type": "string", "required": True},
        }
        result = parse_stage_inputs(raw)
        assert result is not None
        assert len(result) == 1
        assert "suggestion_text" in result
        assert "old_docs_field" not in result


class TestParseStageOutputs:
    """Tests for parse_stage_outputs()."""

    def test_none_returns_empty(self):
        assert parse_stage_outputs(None) == {}

    def test_empty_returns_empty(self):
        assert parse_stage_outputs({}) == {}

    def test_valid_outputs(self):
        raw = {
            "final_decision": {
                "type": "string",
                "description": "Approved or rejected",
            },
            "priority": {"type": "string"},
        }
        result = parse_stage_outputs(raw)
        assert len(result) == 2
        assert result["final_decision"].type == "string"
        assert result["priority"].type == "string"


# ── SourceResolver Tests ────────────────────────────────────────────


class TestSourceResolver:
    """Tests for SourceResolver."""

    def _make_state(self, **kwargs):
        """Build a minimal workflow state."""
        return {
            "workflow_inputs": kwargs.get("workflow_inputs", {}),
            "stage_outputs": kwargs.get("stage_outputs", {}),
            "tracker": None,
            "config_loader": None,
            "workflow_id": "test",
        }

    def _make_stage_config(self, inputs=None, name="test_stage"):
        """Build a minimal stage config dict."""
        config = {"stage": {"name": name, "agents": ["a1"]}}
        if inputs is not None:
            config["stage"]["inputs"] = inputs
        return config

    def test_no_inputs_delegates_to_passthrough(self):
        resolver = SourceResolver()
        state = self._make_state(
            workflow_inputs={"topic": "test"},
        )
        config = self._make_stage_config(inputs=None)
        result = resolver.resolve(config, state)
        # Passthrough should unwrap workflow_inputs
        assert result.get("topic") == "test"

    def test_workflow_source_resolution(self):
        resolver = SourceResolver()
        state = self._make_state(
            workflow_inputs={"suggestion_text": "Add button"},
        )
        config = self._make_stage_config(
            inputs={
                "suggestion_text": {
                    "source": "workflow.suggestion_text",
                    "required": True,
                },
            }
        )
        result = resolver.resolve(config, state)
        assert result["suggestion_text"] == "Add button"

    def test_stage_source_top_level_compat(self):
        resolver = SourceResolver()
        state = self._make_state(
            stage_outputs={
                "vcs_triage": {
                    "structured": {},
                    "raw": {},
                    "decision": "APPROVE",
                    "stage_status": "completed",
                },
            },
        )
        config = self._make_stage_config(
            inputs={
                "triage_decision": {
                    "source": "vcs_triage.decision",
                    "required": True,
                },
            }
        )
        result = resolver.resolve(config, state)
        assert result["triage_decision"] == "APPROVE"

    def test_stage_source_structured_first(self):
        resolver = SourceResolver()
        state = self._make_state(
            stage_outputs={
                "vcs_triage": {
                    "structured": {"priority": "high"},
                    "raw": {"priority": "medium"},
                    "priority": "low",
                },
            },
        )
        config = self._make_stage_config(
            inputs={
                "priority": {
                    "source": "vcs_triage.priority",
                    "required": True,
                },
            }
        )
        result = resolver.resolve(config, state)
        # Should prefer structured
        assert result["priority"] == "high"

    def test_stage_source_explicit_structured(self):
        resolver = SourceResolver()
        state = self._make_state(
            stage_outputs={
                "vcs_triage": {
                    "structured": {"priority": "high"},
                    "raw": {"priority": "medium"},
                },
            },
        )
        config = self._make_stage_config(
            inputs={
                "priority": {
                    "source": "vcs_triage.structured.priority",
                    "required": True,
                },
            }
        )
        result = resolver.resolve(config, state)
        assert result["priority"] == "high"

    def test_stage_source_explicit_raw(self):
        resolver = SourceResolver()
        state = self._make_state(
            stage_outputs={
                "vcs_triage": {
                    "structured": {"priority": "high"},
                    "raw": {"priority": "medium"},
                },
            },
        )
        config = self._make_stage_config(
            inputs={
                "priority": {
                    "source": "vcs_triage.raw.priority",
                    "required": True,
                },
            }
        )
        result = resolver.resolve(config, state)
        assert result["priority"] == "medium"

    def test_missing_required_raises(self):
        resolver = SourceResolver()
        state = self._make_state()
        config = self._make_stage_config(
            inputs={
                "missing_field": {
                    "source": "workflow.nonexistent",
                    "required": True,
                },
            }
        )
        with pytest.raises(ContextResolutionError, match="missing_field"):
            resolver.resolve(config, state)

    def test_optional_uses_default(self):
        resolver = SourceResolver()
        state = self._make_state()
        config = self._make_stage_config(
            inputs={
                "optional_field": {
                    "source": "workflow.nonexistent",
                    "required": False,
                    "default": "fallback_value",
                },
            }
        )
        result = resolver.resolve(config, state)
        assert result["optional_field"] == "fallback_value"

    def test_infrastructure_keys_included(self):
        resolver = SourceResolver()
        state = self._make_state(
            workflow_inputs={"text": "hello"},
        )
        state["tracker"] = "mock_tracker"
        state["show_details"] = True
        config = self._make_stage_config(
            inputs={
                "text": {"source": "workflow.text", "required": True},
            }
        )
        result = resolver.resolve(config, state)
        assert result["text"] == "hello"
        assert result.get("tracker") == "mock_tracker"
        assert result.get("show_details") is True

    def test_fallback_chain_structured_to_raw_to_toplevel(self):
        """When structured is empty, should fall through to raw, then top-level."""
        resolver = SourceResolver()
        state = self._make_state(
            stage_outputs={
                "stage_a": {
                    "structured": {},
                    "raw": {},
                    "output": "top-level-output",
                },
            },
        )
        config = self._make_stage_config(
            inputs={
                "data": {"source": "stage_a.output", "required": True},
            }
        )
        result = resolver.resolve(config, state)
        assert result["data"] == "top-level-output"


# ── PassthroughResolver Tests ───────────────────────────────────────


class TestPassthroughResolver:
    """Tests for PassthroughResolver (legacy behavior)."""

    def test_unwraps_workflow_inputs(self):
        resolver = PassthroughResolver()
        state = {
            "workflow_inputs": {"topic": "test", "depth": "deep"},
            "stage_outputs": {},
            "tracker": None,
        }
        result = resolver.resolve(None, state)
        assert result["topic"] == "test"
        assert result["depth"] == "deep"

    def test_does_not_overwrite_reserved_keys(self):
        resolver = PassthroughResolver()
        state = {
            "workflow_inputs": {"stage_outputs": "should_not_overwrite"},
            "stage_outputs": {"real": "data"},
            "tracker": "mock",
        }
        result = resolver.resolve(None, state)
        assert result["stage_outputs"] == {"real": "data"}
        assert result["tracker"] == "mock"

    def test_preserves_all_state_keys(self):
        resolver = PassthroughResolver()
        state = {
            "workflow_inputs": {},
            "stage_outputs": {"s1": {"output": "x"}},
            "workflow_id": "wf-1",
            "tracker": None,
        }
        result = resolver.resolve(None, state)
        assert result["workflow_id"] == "wf-1"
        assert result["stage_outputs"] == {"s1": {"output": "x"}}
