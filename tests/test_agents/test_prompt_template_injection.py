"""Tests for SSTI prevention in PromptEngine.

Verifies that template injection attacks are blocked by:
1. ImmutableSandboxedEnvironment (no attribute mutation)
2. Variable type whitelist validation
3. Variable size limits
4. Recursive validation of nested structures
"""

import pytest
from src.agents.prompt_engine import PromptEngine, PromptRenderError


class TestVariableTypeValidation:
    """Verify that only allowed types can be passed as template variables."""

    def test_allows_string(self):
        engine = PromptEngine()
        result = engine.render("Hello {{name}}", {"name": "World"})
        assert result == "Hello World"

    def test_allows_int(self):
        engine = PromptEngine()
        result = engine.render("Count: {{n}}", {"n": 42})
        assert result == "Count: 42"

    def test_allows_float(self):
        engine = PromptEngine()
        result = engine.render("Pi: {{pi}}", {"pi": 3.14})
        assert result == "Pi: 3.14"

    def test_allows_bool(self):
        engine = PromptEngine()
        result = engine.render("{% if flag %}yes{% endif %}", {"flag": True})
        assert result == "yes"

    def test_allows_none(self):
        engine = PromptEngine()
        result = engine.render("{{val}}", {"val": None})
        assert result == "None"

    def test_allows_list(self):
        engine = PromptEngine()
        result = engine.render("{{items|length}}", {"items": [1, 2, 3]})
        assert result == "3"

    def test_allows_dict(self):
        engine = PromptEngine()
        result = engine.render("{{d.key}}", {"d": {"key": "value"}})
        assert result == "value"

    def test_allows_tuple(self):
        engine = PromptEngine()
        result = engine.render("{{t|length}}", {"t": (1, 2)})
        assert result == "2"

    def test_blocks_function(self):
        engine = PromptEngine()
        with pytest.raises(PromptRenderError, match="disallowed type.*function"):
            engine.render("{{fn}}", {"fn": lambda: "evil"})

    def test_blocks_class(self):
        engine = PromptEngine()

        class Evil:
            pass

        with pytest.raises(PromptRenderError, match="disallowed type"):
            engine.render("{{obj}}", {"obj": Evil()})

    def test_blocks_module(self):
        import os
        engine = PromptEngine()
        with pytest.raises(PromptRenderError, match="disallowed type.*module"):
            engine.render("{{m}}", {"m": os})

    def test_blocks_type_object(self):
        engine = PromptEngine()
        with pytest.raises(PromptRenderError, match="disallowed type"):
            engine.render("{{t}}", {"t": type})

    def test_blocks_builtin_function(self):
        engine = PromptEngine()
        with pytest.raises(PromptRenderError, match="disallowed type"):
            engine.render("{{fn}}", {"fn": print})


class TestVariableSizeLimits:
    """Verify that oversized variables are rejected."""

    def test_blocks_oversized_string(self):
        engine = PromptEngine()
        large_str = "x" * (PromptEngine.MAX_VAR_SIZE + 1)
        with pytest.raises(PromptRenderError, match="exceeds size limit"):
            engine.render("{{val}}", {"val": large_str})

    def test_allows_string_within_limit(self):
        engine = PromptEngine()
        ok_str = "x" * 1000
        result = engine.render("{{val|length}}", {"val": ok_str})
        assert result == "1000"

    def test_blocks_oversized_string_in_nested_dict(self):
        engine = PromptEngine()
        large_str = "x" * (PromptEngine.MAX_VAR_SIZE + 1)
        with pytest.raises(PromptRenderError, match="exceeds size limit"):
            engine.render("{{d}}", {"d": {"nested": large_str}})

    def test_blocks_oversized_string_in_list(self):
        engine = PromptEngine()
        large_str = "x" * (PromptEngine.MAX_VAR_SIZE + 1)
        with pytest.raises(PromptRenderError, match="exceeds size limit"):
            engine.render("{{items}}", {"items": [large_str]})


class TestNestedValidation:
    """Verify that nested structures are recursively validated."""

    def test_blocks_function_in_dict(self):
        engine = PromptEngine()
        with pytest.raises(PromptRenderError, match="disallowed type"):
            engine.render("{{d}}", {"d": {"fn": lambda: "evil"}})

    def test_blocks_function_in_list(self):
        engine = PromptEngine()
        with pytest.raises(PromptRenderError, match="disallowed type"):
            engine.render("{{items}}", {"items": [1, 2, lambda: "evil"]})

    def test_blocks_deeply_nested_function(self):
        engine = PromptEngine()
        nested = {"a": {"b": {"c": [lambda: "evil"]}}}
        with pytest.raises(PromptRenderError, match="disallowed type"):
            engine.render("{{d}}", {"d": nested})

    def test_blocks_excessive_nesting_depth(self):
        engine = PromptEngine()
        # Build a dict nested >20 levels deep
        d: dict = {}
        current = d
        for i in range(25):
            current["level"] = {}
            current = current["level"]
        current["leaf"] = "value"

        with pytest.raises(PromptRenderError, match="excessive nesting depth"):
            engine.render("{{d}}", {"d": d})


class TestSSTIPayloads:
    """Verify common SSTI payloads are blocked by the sandbox."""

    def test_config_access_blocked(self):
        """{{config}} should not expose any configuration."""
        engine = PromptEngine()
        # config is not a variable, so it renders as empty or raises
        result = engine.render("{{config}}", {})
        # config is undefined, renders as empty string
        assert "config" not in result or result == ""

    def test_class_access_blocked(self):
        """''.__class__ should not expose class info in sandbox."""
        engine = PromptEngine()
        # ImmutableSandboxedEnvironment blocks __class__ access, renders as empty
        result = engine.render("{{''.__class__}}", {})
        assert "<class" not in result

    def test_mro_access_blocked(self):
        """__mro__ chain access should be blocked."""
        engine = PromptEngine()
        with pytest.raises(PromptRenderError):
            engine.render("{{''.__class__.__mro__}}", {})

    def test_subclasses_access_blocked(self):
        """__subclasses__() should be blocked."""
        engine = PromptEngine()
        with pytest.raises(PromptRenderError):
            engine.render("{{''.__class__.__mro__[1].__subclasses__()}}", {})

    def test_globals_access_blocked(self):
        """__globals__ should not expose any data."""
        engine = PromptEngine()
        # lipsum is undefined in our env, so it renders as empty
        result = engine.render("{{lipsum.__globals__}}", {})
        assert "__builtins__" not in result

    def test_init_globals_blocked(self):
        """__init__.__globals__ should be blocked."""
        engine = PromptEngine()
        with pytest.raises(PromptRenderError):
            engine.render("{{cycler.__init__.__globals__}}", {})

    def test_import_blocked(self):
        """Import statement in template should be blocked."""
        engine = PromptEngine()
        with pytest.raises(PromptRenderError):
            engine.render("{% import os %}{{os.system('id')}}", {})

    def test_os_popen_via_mro_blocked(self):
        """Accessing os.popen through MRO should be blocked."""
        engine = PromptEngine()
        payload = "{{''.__class__.__mro__[2].__subclasses__()[40]('/etc/passwd').read()}}"
        with pytest.raises(PromptRenderError):
            engine.render(payload, {})


class TestImmutableSandbox:
    """Verify ImmutableSandboxedEnvironment prevents attribute mutation."""

    def test_cannot_mutate_list_via_template(self):
        """Template should not be able to modify passed-in list."""
        engine = PromptEngine()
        items = [1, 2, 3]
        # ImmutableSandboxedEnvironment blocks calls to mutating methods
        with pytest.raises(PromptRenderError):
            engine.render("{{items.append(4)}}", {"items": items})
        assert items == [1, 2, 3]  # Original unmodified

    def test_cannot_mutate_dict_via_template(self):
        """Template should not be able to modify passed-in dict."""
        engine = PromptEngine()
        d = {"key": "value"}
        with pytest.raises(PromptRenderError):
            engine.render("{{d.update({'evil': 'payload'})}}", {"d": d})
        assert "evil" not in d  # Original unmodified
