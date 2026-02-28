"""Tests for schema utilities and BaseTool in temper_ai/tools/base.py."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from temper_ai.tools.base import (
    BaseTool,
    ToolMetadata,
    ToolResult,
    _check_json_schema_type,
    _clean_schema_property,
    _pydantic_to_llm_schema,
    _resolve_schema_ref,
    _simplify_schema_any_of,
)

# ---------------------------------------------------------------------------
# Concrete subclasses for testing
# ---------------------------------------------------------------------------


class _DummyTool(BaseTool):
    """Minimal tool using JSON-schema validation (no params_model)."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(name="dummy", description="A test tool")

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, result="ok")

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        }


class _DummyPydanticTool(BaseTool):
    """Tool with a Pydantic params_model."""

    class _Params(BaseModel):
        x: str
        y: int = 0

    params_model = _Params

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(name="pydantic_dummy", description="Pydantic param tool")

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, result="ok")


class _ErrorTool(BaseTool):
    """Tool whose execute() raises RuntimeError."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(name="error_tool", description="Raises errors")

    def execute(self, **kwargs: Any) -> ToolResult:
        raise RuntimeError("something broke")

    def get_parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}


class _ConfigTool(BaseTool):
    """Tool with a config_model."""

    class _Config(BaseModel):
        timeout: int = 30
        retries: int = 3

    config_model = _Config

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(name="config_tool", description="Has config model")

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, result="ok")

    def get_parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}


# ---------------------------------------------------------------------------
# TestPydanticToLlmSchema
# ---------------------------------------------------------------------------


class TestPydanticToLlmSchema:
    def test_converts_simple_model_properties(self):
        class M(BaseModel):
            name: str

        schema = _pydantic_to_llm_schema(M)
        assert "properties" in schema
        assert "name" in schema["properties"]

    def test_strips_root_title(self):
        class M(BaseModel):
            x: str

        schema = _pydantic_to_llm_schema(M)
        assert "title" not in schema

    def test_strips_root_description(self):
        class M(BaseModel):
            """A model with description."""

            x: str

        schema = _pydantic_to_llm_schema(M)
        assert "description" not in schema

    def test_handles_defs_by_removing_them(self):
        class Inner(BaseModel):
            val: int

        class Outer(BaseModel):
            inner: Inner

        schema = _pydantic_to_llm_schema(Outer)
        assert "$defs" not in schema

    def test_required_fields_preserved(self):
        class M(BaseModel):
            required_field: str
            optional_field: str = "default"

        schema = _pydantic_to_llm_schema(M)
        assert "required" in schema
        assert "required_field" in schema["required"]


# ---------------------------------------------------------------------------
# TestResolveSchemaRef
# ---------------------------------------------------------------------------


class TestResolveSchemaRef:
    def test_resolves_ref_to_definition(self):
        defs = {"MyType": {"type": "string", "title": "MyType"}}
        prop = {"$ref": "#/$defs/MyType"}
        result = _resolve_schema_ref(prop, defs)
        assert result["type"] == "string"

    def test_preserves_description_override(self):
        defs = {"MyType": {"type": "string"}}
        prop = {"$ref": "#/$defs/MyType", "description": "overridden desc"}
        result = _resolve_schema_ref(prop, defs)
        assert result["description"] == "overridden desc"

    def test_preserves_default_override(self):
        defs = {"MyType": {"type": "integer"}}
        prop = {"$ref": "#/$defs/MyType", "default": 42}
        result = _resolve_schema_ref(prop, defs)
        assert result["default"] == 42

    def test_missing_ref_returns_prop_as_is(self):
        defs = {}
        prop = {"$ref": "#/$defs/NonExistent", "type": "string"}
        result = _resolve_schema_ref(prop, defs)
        assert result == prop


# ---------------------------------------------------------------------------
# TestSimplifySchemaAnyOf
# ---------------------------------------------------------------------------


class TestSimplifySchemaAnyOf:
    def test_simplifies_optional_x_to_x(self):
        prop = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        result = _simplify_schema_any_of(prop)
        assert result == {"type": "string"}

    def test_leaves_multi_non_null_types_as_is(self):
        prop = {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]}
        result = _simplify_schema_any_of(prop)
        assert "anyOf" in result

    def test_preserves_outer_keys_on_simplification(self):
        prop = {
            "anyOf": [{"type": "integer"}, {"type": "null"}],
            "description": "A number",
        }
        result = _simplify_schema_any_of(prop)
        assert result.get("description") == "A number"
        assert result.get("type") == "integer"

    def test_two_non_null_types_left_unchanged(self):
        prop = {"anyOf": [{"type": "string"}, {"type": "number"}]}
        result = _simplify_schema_any_of(prop)
        assert "anyOf" in result


# ---------------------------------------------------------------------------
# TestCleanSchemaProperty
# ---------------------------------------------------------------------------


class TestCleanSchemaProperty:
    def test_strips_title(self):
        prop = {"type": "string", "title": "SomeTitle"}
        result = _clean_schema_property(prop, {})
        assert "title" not in result

    def test_removes_none_default(self):
        prop = {"type": "string", "default": None}
        result = _clean_schema_property(prop, {})
        assert "default" not in result

    def test_preserves_non_none_default(self):
        prop = {"type": "integer", "default": 42}
        result = _clean_schema_property(prop, {})
        assert result["default"] == 42

    def test_resolves_ref(self):
        defs = {"StrType": {"type": "string"}}
        prop = {"$ref": "#/$defs/StrType"}
        result = _clean_schema_property(prop, defs)
        assert result["type"] == "string"

    def test_simplifies_optional_anyof(self):
        prop = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
        result = _clean_schema_property(prop, {})
        assert "anyOf" not in result
        assert result.get("type") == "integer"


# ---------------------------------------------------------------------------
# TestCheckJsonSchemaType
# ---------------------------------------------------------------------------


class TestCheckJsonSchemaType:
    def test_string_type_matches_str(self):
        assert _check_json_schema_type("hello", "string") is True

    def test_string_type_rejects_int(self):
        assert _check_json_schema_type(42, "string") is False

    def test_number_type_matches_int(self):
        assert _check_json_schema_type(5, "number") is True

    def test_number_type_matches_float(self):
        assert _check_json_schema_type(3.14, "number") is True

    def test_integer_type_matches_int(self):
        assert _check_json_schema_type(7, "integer") is True

    def test_integer_type_rejects_float(self):
        assert _check_json_schema_type(3.14, "integer") is False

    def test_boolean_type_matches_bool(self):
        assert _check_json_schema_type(True, "boolean") is True

    def test_array_type_matches_list(self):
        assert _check_json_schema_type([1, 2, 3], "array") is True

    def test_object_type_matches_dict(self):
        assert _check_json_schema_type({"a": 1}, "object") is True

    def test_unknown_type_returns_true(self):
        assert _check_json_schema_type("anything", "unknown_type") is True


# ---------------------------------------------------------------------------
# TestBaseTool
# ---------------------------------------------------------------------------


class TestBaseTool:
    def test_safe_execute_success(self):
        tool = _DummyTool()
        result = tool.safe_execute(x="hello")
        assert result.success is True
        assert result.result == "ok"

    def test_safe_execute_catches_runtime_error(self):
        tool = _ErrorTool()
        result = tool.safe_execute()
        assert result.success is False
        assert result.error is not None

    def test_safe_execute_catches_validation_error(self):
        tool = _DummyTool()
        # Missing required param 'x'
        result = tool.safe_execute()
        assert result.success is False
        assert result.error is not None

    def test_validate_params_with_pydantic_model_valid(self):
        tool = _DummyPydanticTool()
        result = tool.validate_params({"x": "hello"})
        assert result.valid is True
        assert result.errors == []

    def test_validate_params_with_pydantic_model_invalid_missing(self):
        tool = _DummyPydanticTool()
        result = tool.validate_params({})  # missing required 'x'
        assert result.valid is False
        assert len(result.errors) > 0

    def test_validate_with_json_schema_required_missing(self):
        tool = _DummyTool()
        result = tool._validate_with_json_schema({})
        assert result.valid is False
        assert any("x" in e for e in result.errors)

    def test_validate_with_json_schema_type_mismatch(self):
        tool = _DummyTool()
        result = tool._validate_with_json_schema({"x": 123})  # x should be string
        assert result.valid is False

    def test_validate_with_json_schema_unknown_param(self):
        tool = _DummyTool()
        result = tool._validate_with_json_schema({"x": "ok", "unknown": "val"})
        assert result.valid is False
        assert any("unknown" in e for e in result.errors)

    def test_to_llm_schema_structure(self):
        tool = _DummyTool()
        schema = tool.to_llm_schema()
        assert schema["type"] == "function"
        assert "function" in schema
        assert schema["function"]["name"] == "dummy"
        assert "parameters" in schema["function"]

    def test_validate_config_skips_internal_keys(self):
        tool = _ConfigTool(config={"_internal": "skip", "timeout": 10})
        result = tool.validate_config()
        assert result.valid is True

    def test_validate_config_skips_jinja2_templates(self):
        tool = _ConfigTool(config={"timeout": "{{ env_var }}", "retries": 3})
        result = tool.validate_config()
        assert result.valid is True

    def test_get_typed_config_returns_model_instance(self):
        tool = _ConfigTool(config={"timeout": 60, "retries": 5})
        typed = tool.get_typed_config()
        assert typed is not None
        assert typed.timeout == 60
        assert typed.retries == 5

    def test_get_typed_config_none_when_no_config_model(self):
        tool = _DummyTool()
        result = tool.get_typed_config()
        assert result is None
