"""Tests for temper_ai/llm/prompts/validation.py.

Covers template variable validation:
- TemplateVariableValidator.validate_variables: type checks, size limits, nesting depth
- _is_safe_template_value: allowlist-based type safety check
"""

import pytest

from temper_ai.llm.prompts.validation import (
    PromptRenderError,
    TemplateVariableValidator,
    _is_safe_template_value,
)


class TestTemplateVariableValidator:
    """Tests for TemplateVariableValidator.validate_variables."""

    def setup_method(self):
        self.validator = TemplateVariableValidator()

    def test_string_variable_passes(self):
        """String variables are accepted without error."""
        self.validator.validate_variables({"name": "Alice"})

    def test_int_variable_passes(self):
        """Integer variables are accepted without error."""
        self.validator.validate_variables({"count": 42})

    def test_float_variable_passes(self):
        """Float variables are accepted without error."""
        self.validator.validate_variables({"ratio": 3.14})

    def test_bool_variable_passes(self):
        """Boolean variables are accepted without error."""
        self.validator.validate_variables({"flag": True})

    def test_none_variable_passes(self):
        """None variables are accepted without error."""
        self.validator.validate_variables({"opt": None})

    def test_list_variable_passes(self):
        """List variables with safe values are accepted."""
        self.validator.validate_variables({"items": [1, "two", 3.0]})

    def test_dict_variable_passes(self):
        """Dict variables with string keys and safe values are accepted."""
        self.validator.validate_variables({"data": {"key": "value"}})

    def test_tuple_variable_passes(self):
        """Tuple variables with safe values are accepted."""
        self.validator.validate_variables({"coords": (1.0, 2.0)})

    def test_empty_dict_variable_passes(self):
        """Empty dict variable is accepted."""
        self.validator.validate_variables({"empty": {}})

    def test_empty_list_variable_passes(self):
        """Empty list variable is accepted."""
        self.validator.validate_variables({"items": []})

    def test_mixed_nested_structure_passes(self):
        """Nested list/dict/tuple mix with safe values is accepted."""
        self.validator.validate_variables(
            {"data": {"list": [1, 2, (3, 4)], "nested": {"k": "v"}}}
        )

    def test_function_raises(self):
        """Function objects are rejected with PromptRenderError."""
        with pytest.raises(PromptRenderError):
            self.validator.validate_variables({"fn": lambda x: x})

    def test_class_instance_raises(self):
        """Arbitrary class instances are rejected with PromptRenderError."""

        class MyObj:
            pass

        with pytest.raises(PromptRenderError):
            self.validator.validate_variables({"obj": MyObj()})

    def test_module_raises(self):
        """Module objects are rejected with PromptRenderError."""
        import os

        with pytest.raises(PromptRenderError):
            self.validator.validate_variables({"mod": os})

    def test_string_exceeding_size_limit_raises(self):
        """String exceeding ~1MB size limit raises PromptRenderError."""
        max_size = TemplateVariableValidator.MAX_VAR_SIZE
        big_string = "a" * (max_size + 1)
        with pytest.raises(PromptRenderError):
            self.validator.validate_variables({"big": big_string})

    def test_string_at_size_limit_passes(self):
        """String exactly at the size limit is accepted."""
        max_size = TemplateVariableValidator.MAX_VAR_SIZE
        ok_string = "a" * max_size
        self.validator.validate_variables({"ok": ok_string})

    def test_nesting_depth_too_deep_raises(self):
        """Nesting depth exceeding limit (>20) raises PromptRenderError."""
        # Build 22 levels of nested dicts to exceed the depth=20 limit
        nested = "leaf"
        for _ in range(22):
            nested = {"key": nested}
        with pytest.raises(PromptRenderError):
            self.validator.validate_variables({"deep": nested})

    def test_nesting_depth_at_limit_passes(self):
        """Nesting depth at the limit (=20 levels) is accepted."""
        # 19 wraps so the leaf is at depth=20 (not >20), which should pass
        nested = "leaf"
        for _ in range(19):
            nested = {"key": nested}
        self.validator.validate_variables({"ok": nested})

    def test_dict_with_non_string_key_passes_top_level(self):
        """Dict value with non-string keys passes validate_variables (only values are checked recursively).

        Note: _is_safe_template_value rejects non-string keys, but
        TemplateVariableValidator._validate_value only recurses over values,
        not keys — so integer-keyed dicts pass at this level.
        """
        # The validator only validates values in nested dicts, not keys
        self.validator.validate_variables({"myvar": {1: "hello"}})

    def test_empty_variables_dict_passes(self):
        """Empty variables dict causes no validation errors."""
        self.validator.validate_variables({})


class TestIsSafeTemplateValue:
    """Tests for _is_safe_template_value standalone function."""

    def test_none_is_safe(self):
        """None is a safe template value."""
        assert _is_safe_template_value(None) is True

    def test_string_is_safe(self):
        """String is a safe template value."""
        assert _is_safe_template_value("hello") is True

    def test_int_is_safe(self):
        """Integer is a safe template value."""
        assert _is_safe_template_value(42) is True

    def test_float_is_safe(self):
        """Float is a safe template value."""
        assert _is_safe_template_value(3.14) is True

    def test_bool_is_safe(self):
        """Boolean is a safe template value."""
        assert _is_safe_template_value(True) is True

    def test_list_of_primitives_is_safe(self):
        """List containing only primitives is safe."""
        assert _is_safe_template_value([1, "two", 3.0, None]) is True

    def test_nested_list_is_safe(self):
        """Nested list with safe values is safe."""
        assert _is_safe_template_value([[1, 2], [3, 4]]) is True

    def test_dict_with_string_keys_is_safe(self):
        """Dict with string keys and safe values is safe."""
        assert _is_safe_template_value({"a": 1, "b": "two"}) is True

    def test_tuple_of_primitives_is_safe(self):
        """Tuple containing only primitives is safe."""
        assert _is_safe_template_value((1, 2, 3)) is True

    def test_nested_dict_is_safe(self):
        """Nested dict with string keys and safe values is safe."""
        assert _is_safe_template_value({"outer": {"inner": 42}}) is True

    def test_function_is_not_safe(self):
        """Function objects are not safe template values."""
        assert _is_safe_template_value(lambda x: x) is False

    def test_class_instance_is_not_safe(self):
        """Arbitrary class instances are not safe template values."""

        class Foo:
            pass

        assert _is_safe_template_value(Foo()) is False

    def test_dict_with_non_string_key_is_not_safe(self):
        """Dict with non-string keys is not safe (key check is applied)."""
        assert _is_safe_template_value({1: "value"}) is False

    def test_nested_unsafe_value_is_not_safe(self):
        """List containing an unsafe value (lambda) is not safe."""
        assert _is_safe_template_value([1, 2, lambda x: x]) is False

    def test_nested_dict_with_unsafe_value_is_not_safe(self):
        """Dict with an unsafe nested value is not safe."""

        class Obj:
            pass

        assert _is_safe_template_value({"key": Obj()}) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
