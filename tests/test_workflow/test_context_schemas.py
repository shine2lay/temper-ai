"""Tests for context_schemas module — _SOURCE_PATTERN, StageInputDeclaration,
StageOutputDeclaration, parse_stage_inputs, and parse_stage_outputs."""

import pytest
from pydantic import ValidationError

from temper_ai.workflow.context_schemas import (
    _SOURCE_PATTERN,
    StageInputDeclaration,
    StageOutputDeclaration,
    parse_stage_inputs,
    parse_stage_outputs,
)


class TestSourcePattern:
    """Tests for _SOURCE_PATTERN regex — valid and invalid source strings."""

    def test_workflow_field(self):
        """workflow.<field> is the simplest valid format."""
        assert _SOURCE_PATTERN.match("workflow.suggestion_text") is not None

    def test_stage_field(self):
        """<stage>.<field> is a basic valid source."""
        assert _SOURCE_PATTERN.match("vcs_triage.final_decision") is not None

    def test_stage_structured_compartment(self):
        """<stage>.structured.<field> uses the optional compartment."""
        assert _SOURCE_PATTERN.match("my_stage.structured.result") is not None

    def test_stage_raw_compartment(self):
        """<stage>.raw.<field> uses the optional raw compartment."""
        assert _SOURCE_PATTERN.match("my_stage.raw.output") is not None

    def test_nested_field_segments(self):
        """Multiple dot-separated field segments after stage name are allowed."""
        assert _SOURCE_PATTERN.match("my_stage.nested.deep.field") is not None

    def test_underscore_stage_name(self):
        """Stage names may start with an underscore."""
        assert _SOURCE_PATTERN.match("_my_stage.field") is not None

    def test_alphanumeric_field_name(self):
        """Field names may contain digits after the first char."""
        assert _SOURCE_PATTERN.match("stage.field123") is not None

    def test_invalid_no_field_segment(self):
        """'workflow' alone has no field segment — invalid."""
        assert _SOURCE_PATTERN.match("workflow") is None

    def test_invalid_numeric_stage_start(self):
        """Stage names cannot start with a digit."""
        assert _SOURCE_PATTERN.match("123stage.field") is None

    def test_invalid_empty_string(self):
        assert _SOURCE_PATTERN.match("") is None

    def test_invalid_leading_dot(self):
        """Cannot start with a dot."""
        assert _SOURCE_PATTERN.match(".field") is None

    def test_invalid_double_dot(self):
        """Double dots produce an empty segment — invalid."""
        assert _SOURCE_PATTERN.match("stage..field") is None

    def test_invalid_trailing_dot(self):
        """Trailing dot produces no terminal field segment."""
        assert _SOURCE_PATTERN.match("stage.field.") is None


class TestStageInputDeclaration:
    """Tests for StageInputDeclaration Pydantic model construction and validation."""

    def test_minimal_valid(self):
        """Only source is required; remaining fields have safe defaults."""
        decl = StageInputDeclaration(source="workflow.suggestion_text")
        assert decl.source == "workflow.suggestion_text"
        assert decl.required is True
        assert decl.default is None
        assert decl.description is None

    def test_full_construction(self):
        decl = StageInputDeclaration(
            source="vcs_triage.final_decision",
            required=False,
            default="approved",
            description="Decision from the triage stage",
        )
        assert decl.source == "vcs_triage.final_decision"
        assert decl.required is False
        assert decl.default == "approved"
        assert decl.description == "Decision from the triage stage"

    def test_structured_compartment_source(self):
        decl = StageInputDeclaration(source="stage.structured.result")
        assert decl.source == "stage.structured.result"

    def test_raw_compartment_source(self):
        decl = StageInputDeclaration(source="stage.raw.output")
        assert decl.source == "stage.raw.output"

    def test_default_accepts_any_type(self):
        """default field is typed Any — accepts dicts, lists, etc."""
        decl = StageInputDeclaration(source="workflow.data", default={"key": "val"})
        assert decl.default == {"key": "val"}

    def test_invalid_source_no_field(self):
        """Source without a field segment should fail validation."""
        with pytest.raises(ValidationError):
            StageInputDeclaration(source="workflow")

    def test_invalid_source_empty(self):
        with pytest.raises(ValidationError):
            StageInputDeclaration(source="")

    def test_invalid_source_numeric_start(self):
        with pytest.raises(ValidationError):
            StageInputDeclaration(source="123stage.field")

    def test_invalid_source_double_dot(self):
        with pytest.raises(ValidationError):
            StageInputDeclaration(source="stage..field")

    def test_error_message_contains_format_hint(self):
        """Validation error should mention the expected format."""
        with pytest.raises(ValidationError) as exc_info:
            StageInputDeclaration(source="bad")
        assert "workflow" in str(exc_info.value)


class TestParseStageInputs:
    """Tests for parse_stage_inputs() helper function."""

    def test_none_input_returns_none(self):
        """None signals legacy passthrough mode."""
        assert parse_stage_inputs(None) is None

    def test_docs_only_entries_return_none(self):
        """Entries without a 'source' key are documentation-only — passthrough."""
        raw = {"my_input": {"type": "string", "description": "Some doc"}}
        assert parse_stage_inputs(raw) is None

    def test_empty_dict_returns_none(self):
        """An empty dict has no source refs — treated as passthrough."""
        assert parse_stage_inputs({}) is None

    def test_single_source_ref(self):
        raw = {"suggestion_text": {"source": "workflow.suggestion_text"}}
        result = parse_stage_inputs(raw)
        assert result is not None
        assert "suggestion_text" in result
        assert isinstance(result["suggestion_text"], StageInputDeclaration)

    def test_multiple_source_refs(self):
        raw = {
            "suggestion_text": {"source": "workflow.suggestion_text"},
            "triage_decision": {
                "source": "vcs_triage.final_decision",
                "required": True,
            },
        }
        result = parse_stage_inputs(raw)
        assert result is not None
        assert "suggestion_text" in result
        assert "triage_decision" in result

    def test_mixed_source_and_docs_entries(self):
        """Docs-only entries are skipped; sourced entries are included."""
        raw = {
            "sourced": {"source": "workflow.field"},
            "docs_only": {"type": "string", "description": "doc only"},
        }
        result = parse_stage_inputs(raw)
        assert result is not None
        assert "sourced" in result
        assert "docs_only" not in result

    def test_optional_fields_propagated(self):
        raw = {
            "my_key": {
                "source": "stage.field",
                "required": False,
                "default": "fallback",
                "description": "A field",
            }
        }
        result = parse_stage_inputs(raw)
        assert result is not None
        decl = result["my_key"]
        assert decl.required is False
        assert decl.default == "fallback"
        assert decl.description == "A field"

    def test_invalid_source_format_raises(self):
        """Invalid source format inside a valid dict should propagate as ValueError."""
        raw = {"bad": {"source": "bad_format_no_field"}}
        with pytest.raises((ValueError, Exception)):
            parse_stage_inputs(raw)


class TestParseStageOutputs:
    """Tests for parse_stage_outputs() helper function."""

    def test_none_returns_empty_dict(self):
        assert parse_stage_outputs(None) == {}

    def test_empty_dict_returns_empty(self):
        assert parse_stage_outputs({}) == {}

    def test_valid_single_entry(self):
        raw = {
            "final_decision": {"type": "string", "description": "Approved or rejected"}
        }
        result = parse_stage_outputs(raw)
        assert "final_decision" in result
        assert isinstance(result["final_decision"], StageOutputDeclaration)
        assert result["final_decision"].type == "string"
        assert result["final_decision"].description == "Approved or rejected"

    def test_non_dict_value_is_skipped(self):
        """Non-dict values (old docs-only format) should be silently skipped."""
        raw = {
            "dict_entry": {"type": "number"},
            "str_entry": "just a string",
        }
        result = parse_stage_outputs(raw)
        assert "dict_entry" in result
        assert "str_entry" not in result

    def test_all_valid_output_types(self):
        raw = {
            "a": {"type": "string"},
            "b": {"type": "list"},
            "c": {"type": "dict"},
            "d": {"type": "number"},
            "e": {"type": "boolean"},
            "f": {"type": "any"},
        }
        result = parse_stage_outputs(raw)
        assert len(result) == 6
        assert result["a"].type == "string"
        assert result["b"].type == "list"
        assert result["c"].type == "dict"
        assert result["d"].type == "number"
        assert result["e"].type == "boolean"
        assert result["f"].type == "any"

    def test_default_type_is_string(self):
        """StageOutputDeclaration defaults type to 'string' when omitted."""
        raw = {"field": {}}
        result = parse_stage_outputs(raw)
        assert result["field"].type == "string"

    def test_invalid_output_type_raises(self):
        """Invalid Literal value for type should raise a ValidationError."""
        raw = {"field": {"type": "integer"}}
        with pytest.raises(ValidationError):
            parse_stage_outputs(raw)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
