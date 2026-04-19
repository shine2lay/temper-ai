"""Tests for environment variable substitution in configs."""

import os

import pytest

from temper_ai.config.helpers import ConfigValidationError, substitute_env_vars


class TestSubstituteEnvVarsExtended:
    def test_simple_substitution(self):
        os.environ["TEST_SUB_VAR"] = "hello"
        result = substitute_env_vars("${TEST_SUB_VAR}")
        assert result == "hello"
        del os.environ["TEST_SUB_VAR"]

    def test_default_value(self):
        os.environ.pop("TEST_SUB_MISSING", None)
        result = substitute_env_vars("${TEST_SUB_MISSING:fallback}")
        assert result == "fallback"

    def test_missing_no_default_raises(self):
        os.environ.pop("TEST_SUB_REQUIRED", None)
        with pytest.raises(ConfigValidationError):
            substitute_env_vars("${TEST_SUB_REQUIRED}")

    def test_nested_dict(self):
        os.environ["TEST_SUB_NESTED"] = "nested_val"
        result = substitute_env_vars({"key": "${TEST_SUB_NESTED}"})
        assert result["key"] == "nested_val"
        del os.environ["TEST_SUB_NESTED"]

    def test_nested_list(self):
        os.environ["TEST_SUB_LIST"] = "list_val"
        result = substitute_env_vars(["${TEST_SUB_LIST}", "plain"])
        assert result[0] == "list_val"
        assert result[1] == "plain"
        del os.environ["TEST_SUB_LIST"]

    def test_non_string_passthrough(self):
        assert substitute_env_vars(42) == 42
        assert substitute_env_vars(True) is True
        assert substitute_env_vars(None) is None

    def test_multiple_vars_in_string(self):
        os.environ["TEST_A"] = "foo"
        os.environ["TEST_B"] = "bar"
        result = substitute_env_vars("${TEST_A}-${TEST_B}")
        assert result == "foo-bar"
        del os.environ["TEST_A"]
        del os.environ["TEST_B"]

    def test_default_with_colon(self):
        os.environ.pop("TEST_SUB_COLON", None)
        result = substitute_env_vars("${TEST_SUB_COLON:http://localhost:8080}")
        assert result == "http://localhost:8080"

    def test_oversized_env_var(self):
        os.environ["TEST_SUB_BIG"] = "x" * 10001
        with pytest.raises(ConfigValidationError):
            substitute_env_vars("${TEST_SUB_BIG}")
        del os.environ["TEST_SUB_BIG"]
