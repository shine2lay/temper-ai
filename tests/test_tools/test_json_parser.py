"""Tests for the JSONParserTool."""
import json

import pytest

from temper_ai.tools.json_parser import JSONParserTool


@pytest.fixture
def tool():
    return JSONParserTool()


def test_metadata(tool):
    meta = tool.get_metadata()
    assert meta.name == "JSONParser"
    assert meta.requires_network is False
    assert meta.modifies_state is False
    assert meta.category == "utility"


def test_parse_valid(tool):
    result = tool.execute(data='{"name": "Alice", "age": 30}', operation="parse")
    assert result.success is True
    assert result.result == {"name": "Alice", "age": 30}


def test_parse_invalid(tool):
    result = tool.execute(data="not valid json {", operation="parse")
    assert result.success is False
    assert result.error is not None
    assert "invalid json" in result.error.lower()


def test_extract_dot_path(tool):
    data = json.dumps({"user": {"name": "Bob", "role": "admin"}})
    result = tool.execute(data=data, operation="extract", path="user.name")
    assert result.success is True
    assert result.result == "Bob"


def test_extract_array_index(tool):
    data = json.dumps({"items": ["alpha", "beta", "gamma"]})
    result = tool.execute(data=data, operation="extract", path="items.1")
    assert result.success is True
    assert result.result == "beta"


def test_extract_nested_array(tool):
    data = json.dumps({"users": [{"name": "Alice"}, {"name": "Bob"}]})
    result = tool.execute(data=data, operation="extract", path="users.0.name")
    assert result.success is True
    assert result.result == "Alice"


def test_extract_missing_path(tool):
    data = json.dumps({"a": 1})
    result = tool.execute(data=data, operation="extract", path="b.c")
    assert result.success is False
    assert result.error is not None


def test_extract_missing_path_param(tool):
    result = tool.execute(data='{"x": 1}', operation="extract")
    assert result.success is False
    assert "path" in result.error.lower()


def test_validate_valid_json(tool):
    result = tool.execute(data='{"ok": true}', operation="validate")
    assert result.success is True
    assert result.result["valid"] is True


def test_validate_invalid_json(tool):
    result = tool.execute(data="broken{", operation="validate")
    assert result.success is False
    assert result.result["valid"] is False


def test_validate_with_required_keys(tool):
    data = json.dumps({"name": "Alice"})
    result = tool.execute(data=data, operation="validate", schema={"required": ["name", "age"]})
    assert result.success is False
    assert "age" in result.error


def test_format(tool):
    data = '{"b":2,"a":1}'
    result = tool.execute(data=data, operation="format")
    assert result.success is True
    assert isinstance(result.result, str)
    # Should be pretty-printed
    assert "\n" in result.result
    parsed_back = json.loads(result.result)
    assert parsed_back == {"b": 2, "a": 1}


def test_invalid_operation(tool):
    result = tool.execute(data='{"x":1}', operation="unknown")
    assert result.success is False
    assert "invalid operation" in result.error.lower()
