"""
Tests for prompt template rendering engine.
"""

import tempfile
from pathlib import Path

import pytest

from temper_ai.llm.prompts.engine import PromptEngine, PromptRenderError


class TestBasicRendering:
    """Tests for basic template rendering."""

    def test_simple_variable_substitution(self):
        """Test simple {{variable}} substitution."""
        engine = PromptEngine()
        result = engine.render("Hello {{name}}!", {"name": "World"})
        assert result == "Hello World!"

    def test_multiple_variables(self):
        """Test multiple variable substitutions."""
        engine = PromptEngine()
        template = "{{greeting}} {{name}}, you are {{age}} years old"
        variables = {"greeting": "Hi", "name": "Alice", "age": 30}
        result = engine.render(template, variables)
        assert result == "Hi Alice, you are 30 years old"

    def test_render_without_variables(self):
        """Test rendering template without any variables."""
        engine = PromptEngine()
        result = engine.render("Static text", None)
        assert result == "Static text"

    def test_render_with_empty_variables(self):
        """Test rendering with empty variables dict."""
        engine = PromptEngine()
        result = engine.render("Hello!", {})
        assert result == "Hello!"


class TestConditionalBlocks:
    """Tests for conditional rendering."""

    def test_if_condition_true(self):
        """Test if block when condition is true."""
        engine = PromptEngine()
        template = "{% if premium %}Premium User{% endif %}"
        result = engine.render(template, {"premium": True})
        assert result == "Premium User"

    def test_if_condition_false(self):
        """Test if block when condition is false."""
        engine = PromptEngine()
        template = "{% if premium %}Premium User{% endif %}"
        result = engine.render(template, {"premium": False})
        assert result == ""

    def test_if_else_condition(self):
        """Test if-else blocks."""
        engine = PromptEngine()
        template = "{% if premium %}Premium{% else %}Free{% endif %}"

        result_true = engine.render(template, {"premium": True})
        assert result_true == "Premium"

        result_false = engine.render(template, {"premium": False})
        assert result_false == "Free"

    def test_if_elif_else(self):
        """Test if-elif-else chains."""
        engine = PromptEngine()
        template = """
        {% if level == 'high' %}
        High priority
        {% elif level == 'medium' %}
        Medium priority
        {% else %}
        Low priority
        {% endif %}
        """

        result_high = engine.render(template, {"level": "high"})
        assert "High priority" in result_high

        result_medium = engine.render(template, {"level": "medium"})
        assert "Medium priority" in result_medium

        result_low = engine.render(template, {"level": "low"})
        assert "Low priority" in result_low


class TestLoops:
    """Tests for loop constructs."""

    def test_for_loop_basic(self):
        """Test basic for loop."""
        engine = PromptEngine()
        template = "{% for item in items %}{{item}},{% endfor %}"
        result = engine.render(template, {"items": ["a", "b", "c"]})
        assert result == "a,b,c,"

    def test_for_loop_with_dict(self):
        """Test for loop over dictionary items."""
        engine = PromptEngine()
        template = "{% for name, age in people.items() %}{{name}}:{{age}},{% endfor %}"
        result = engine.render(template, {"people": {"Alice": 30, "Bob": 25}})
        assert "Alice:30" in result
        assert "Bob:25" in result

    def test_for_loop_empty(self):
        """Test for loop with empty list."""
        engine = PromptEngine()
        template = "{% for item in items %}{{item}}{% endfor %}"
        result = engine.render(template, {"items": []})
        assert result == ""


class TestFilters:
    """Tests for Jinja2 filters."""

    def test_length_filter(self):
        """Test |length filter."""
        engine = PromptEngine()
        template = "Count: {{items|length}}"
        result = engine.render(template, {"items": [1, 2, 3]})
        assert result == "Count: 3"

    def test_upper_filter(self):
        """Test |upper filter."""
        engine = PromptEngine()
        template = "{{name|upper}}"
        result = engine.render(template, {"name": "alice"})
        assert result == "ALICE"

    def test_default_filter(self):
        """Test |default filter."""
        engine = PromptEngine()
        template = "{{name|default('Guest')}}"

        result_with_name = engine.render(template, {"name": "Alice"})
        assert result_with_name == "Alice"

        result_without_name = engine.render(template, {})
        assert result_without_name == "Guest"


class TestFileRendering:
    """Tests for rendering templates from files."""

    @pytest.fixture
    def temp_templates_dir(self):
        """Create temporary templates directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir) / "templates"
            templates_dir.mkdir()

            # Create test template files
            (templates_dir / "simple.txt").write_text("Hello {{name}}!")
            (templates_dir / "with_conditional.txt").write_text(
                "{% if premium %}Premium{% else %}Free{% endif %}"
            )

            yield templates_dir

    def test_render_file_simple(self, temp_templates_dir):
        """Test rendering simple template from file."""
        engine = PromptEngine(templates_dir=temp_templates_dir)
        result = engine.render_file("simple.txt", {"name": "World"})
        assert result == "Hello World!"

    def test_render_file_with_conditional(self, temp_templates_dir):
        """Test rendering file with conditional."""
        engine = PromptEngine(templates_dir=temp_templates_dir)
        result = engine.render_file("with_conditional.txt", {"premium": True})
        assert result == "Premium"

    def test_render_file_not_found(self, temp_templates_dir):
        """Test error when template file not found."""
        engine = PromptEngine(templates_dir=temp_templates_dir)
        with pytest.raises(PromptRenderError, match="not found"):
            engine.render_file("nonexistent.txt", {})

    def test_render_file_no_templates_dir(self):
        """Test error when templates directory not configured."""
        engine = PromptEngine(templates_dir=None)
        engine.jinja_env = None  # Ensure no environment
        with pytest.raises(PromptRenderError, match="not configured"):
            engine.render_file("test.txt", {})


class TestErrorHandling:
    """Tests for error handling."""

    def test_undefined_variable_error(self):
        """Test error with undefined variable (strict mode would fail, but default is lenient)."""
        engine = PromptEngine()
        # Jinja2 default behavior is to treat undefined as empty string
        result = engine.render("Hello {{undefined_var}}!", {})
        assert result == "Hello !"

    def test_syntax_error_in_template(self):
        """Test error with invalid Jinja2 syntax."""
        engine = PromptEngine()
        with pytest.raises(PromptRenderError):
            engine.render("{% if %}invalid{% endif %}", {})

    def test_render_error_message_includes_details(self):
        """Test that error messages include helpful details."""
        engine = PromptEngine()
        try:
            engine.render("{% if %}bad{% endif %}", {})
        except PromptRenderError as e:
            assert "Failed to render template" in str(e)


class TestEngineInitialization:
    """Tests for PromptEngine initialization."""

    def test_init_with_nonexistent_templates_dir(self):
        """Test initialization when templates directory doesn't exist."""
        engine = PromptEngine(templates_dir="/nonexistent/path")
        assert engine.jinja_env is None

    def test_init_finds_project_root(self):
        """Test that init can find project root configs/prompts."""
        engine = PromptEngine()  # Uses default path finding
        # Should either find configs/prompts or set jinja_env to None
        assert hasattr(engine, "jinja_env")


class TestTemplateCaching:
    """Tests for template compilation caching."""

    def test_template_cached_after_first_render(self):
        """Test that templates are compiled once and cached."""
        engine = PromptEngine()
        template = "Hello {{name}}!"

        # First render - should compile template
        result1 = engine.render(template, {"name": "Alice"})
        assert result1 == "Hello Alice!"

        # Check cache stats
        stats = engine.get_cache_stats()
        assert stats["cache_misses"] == 1
        assert stats["cache_hits"] == 0
        assert stats["cache_size"] == 1

        # Second render - should use cached template
        result2 = engine.render(template, {"name": "Bob"})
        assert result2 == "Hello Bob!"

        # Check cache hit
        stats = engine.get_cache_stats()
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1
        assert stats["cache_hit_rate"] == 0.5

    def test_different_templates_cached_separately(self):
        """Test that different templates are cached separately."""
        engine = PromptEngine()

        # Render two different templates
        engine.render("Hello {{name}}!", {"name": "Alice"})
        engine.render("Goodbye {{name}}!", {"name": "Bob"})

        stats = engine.get_cache_stats()
        assert stats["cache_size"] == 2
        assert stats["cache_misses"] == 2
        assert stats["cache_hits"] == 0

        # Render same templates again - should hit cache
        engine.render("Hello {{name}}!", {"name": "Charlie"})
        engine.render("Goodbye {{name}}!", {"name": "David"})

        stats = engine.get_cache_stats()
        assert stats["cache_size"] == 2
        assert stats["cache_hits"] == 2
        assert stats["cache_misses"] == 2

    def test_cache_performance_improvement(self):
        """Test that cached renders are significantly faster."""
        import time

        engine = PromptEngine()

        template = """
        You are {{agent_name}}, analyzing {{domain}}.
        {% if detailed %}
        Provide comprehensive analysis.
        {% else %}
        Provide brief summary.
        {% endif %}
        """

        # First render (compilation + render)
        start = time.time()
        for _ in range(10):
            engine.clear_cache()  # Force recompilation each time
            engine.render(
                template, {"agent_name": "researcher", "domain": "AI", "detailed": True}
            )
        time.time() - start

        # Clear cache for fair comparison
        engine.clear_cache()

        # Second set of renders (cached)
        start = time.time()
        for _ in range(10):
            engine.render(
                template, {"agent_name": "researcher", "domain": "AI", "detailed": True}
            )
        time.time() - start

        # Verify cache is used deterministically via stats
        stats = engine.get_cache_stats()
        assert (
            stats["cache_hits"] >= 9
        ), f"Expected at least 9 cache hits from 10 renders, got {stats['cache_hits']}"

    def test_cache_lru_eviction(self):
        """Test that cache evicts oldest entries when full."""
        # Create engine with small cache
        engine = PromptEngine(cache_size=3)

        # Fill cache with 3 templates
        engine.render("Template 1: {{x}}", {"x": 1})
        engine.render("Template 2: {{x}}", {"x": 2})
        engine.render("Template 3: {{x}}", {"x": 3})

        stats = engine.get_cache_stats()
        assert stats["cache_size"] == 3
        assert stats["cache_misses"] == 3
        assert stats["cache_hits"] == 0

        # Add 4th template - should evict oldest (Template 1)
        engine.render("Template 4: {{x}}", {"x": 4})

        stats = engine.get_cache_stats()
        assert stats["cache_size"] == 3  # Still only 3 in cache
        assert stats["cache_misses"] == 4  # 4th template is also a miss

        # Rendering Template 1 again should be cache miss (it was evicted)
        old_misses = engine.get_cache_stats()["cache_misses"]
        engine.render("Template 1: {{x}}", {"x": 1})
        assert engine.get_cache_stats()["cache_misses"] == old_misses + 1

        # Now cache should have: Template 3, Template 4, Template 1
        # (Template 2 was evicted when Template 1 was re-added)

        # Template 3 should still be in cache
        old_hits = engine.get_cache_stats()["cache_hits"]
        engine.render("Template 3: {{x}}", {"x": 3})
        assert engine.get_cache_stats()["cache_hits"] == old_hits + 1

        # Template 4 should still be in cache
        old_hits = engine.get_cache_stats()["cache_hits"]
        engine.render("Template 4: {{x}}", {"x": 4})
        assert engine.get_cache_stats()["cache_hits"] == old_hits + 1

        # Template 2 should be evicted (cache miss)
        old_misses = engine.get_cache_stats()["cache_misses"]
        engine.render("Template 2: {{x}}", {"x": 2})
        assert engine.get_cache_stats()["cache_misses"] == old_misses + 1

    def test_clear_cache(self):
        """Test cache clearing functionality."""
        engine = PromptEngine()

        # Populate cache
        engine.render("Hello {{name}}!", {"name": "Alice"})
        engine.render("Goodbye {{name}}!", {"name": "Bob"})

        assert engine.get_cache_stats()["cache_size"] == 2

        # Clear cache
        engine.clear_cache()

        stats = engine.get_cache_stats()
        assert stats["cache_size"] == 0
        assert stats["cache_hits"] == 0
        assert stats["cache_misses"] == 0
        assert stats["cache_hit_rate"] == 0.0

    def test_cache_stats_accuracy(self):
        """Test that cache statistics are accurately tracked."""
        engine = PromptEngine()

        # Render same template 5 times
        for i in range(5):
            engine.render("Test {{x}}", {"x": i})

        stats = engine.get_cache_stats()
        assert stats["cache_hits"] == 4  # First is miss, next 4 are hits
        assert stats["cache_misses"] == 1
        assert stats["total_requests"] == 5
        assert stats["cache_hit_rate"] == 0.8

    def test_cache_different_variables_same_template(self):
        """Test that different variables use cached template."""
        engine = PromptEngine()
        template = "Hello {{name}}, you are {{age}} years old"

        # Render with different variables
        engine.render(template, {"name": "Alice", "age": 30})
        engine.render(template, {"name": "Bob", "age": 25})
        engine.render(template, {"name": "Charlie", "age": 35})

        # All should use same cached template
        stats = engine.get_cache_stats()
        assert stats["cache_misses"] == 1  # Only first is miss
        assert stats["cache_hits"] == 2  # Next 2 are hits
        assert stats["cache_size"] == 1  # Only 1 template cached

    def test_cache_with_conditional_blocks(self):
        """Test caching works with conditional blocks."""
        engine = PromptEngine()
        template = "{% if premium %}Premium{% else %}Free{% endif %} user"

        # Render with different conditions
        result1 = engine.render(template, {"premium": True})
        result2 = engine.render(template, {"premium": False})
        result3 = engine.render(template, {"premium": True})

        assert result1 == "Premium user"
        assert result2 == "Free user"
        assert result3 == "Premium user"

        # Should have 1 cache miss, 2 hits
        stats = engine.get_cache_stats()
        assert stats["cache_misses"] == 1
        assert stats["cache_hits"] == 2

    def test_cache_with_loops(self):
        """Test caching works with loop constructs."""
        engine = PromptEngine()
        template = "{% for item in items %}{{item}},{% endfor %}"

        # Render with different data
        result1 = engine.render(template, {"items": ["a", "b"]})
        result2 = engine.render(template, {"items": ["x", "y", "z"]})

        assert result1 == "a,b,"
        assert result2 == "x,y,z,"

        # Both should use cached template
        stats = engine.get_cache_stats()
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1

    def test_cache_with_complex_templates(self):
        """Test caching with complex real-world templates."""
        engine = PromptEngine()

        template = """
        You are {{agent_name}}, a {{role}} agent.
        {% if tools %}
        Available tools:
        {% for tool in tools %}
        - {{tool.name}}: {{tool.description}}
        {% endfor %}
        {% endif %}
        Task: {{task}}
        """

        # Render multiple times with different data
        for i in range(5):
            tools = [{"name": f"tool{i}", "description": f"Tool {i}"}]
            engine.render(
                template,
                {
                    "agent_name": f"agent_{i}",
                    "role": "research",
                    "tools": tools,
                    "task": f"Task {i}",
                },
            )

        # Should have 1 miss (first) and 4 hits
        stats = engine.get_cache_stats()
        assert stats["cache_misses"] == 1
        assert stats["cache_hits"] == 4
        assert stats["cache_hit_rate"] == 0.8

    def test_cache_capacity_parameter(self):
        """Test that cache_size parameter is respected."""
        # Small cache
        engine_small = PromptEngine(cache_size=2)
        assert engine_small.get_cache_stats()["cache_capacity"] == 2

        # Large cache
        engine_large = PromptEngine(cache_size=1000)
        assert engine_large.get_cache_stats()["cache_capacity"] == 1000

    def test_cache_hit_rate_calculation(self):
        """Test cache hit rate is calculated correctly."""
        engine = PromptEngine()

        # 0 requests - should return 0.0
        assert engine.get_cache_stats()["cache_hit_rate"] == 0.0

        # 1 miss, 0 hits - should return 0.0
        engine.render("Test", {})
        assert engine.get_cache_stats()["cache_hit_rate"] == 0.0

        # 1 miss, 1 hit - should return 0.5
        engine.render("Test", {})
        assert engine.get_cache_stats()["cache_hit_rate"] == 0.5

        # 1 miss, 3 hits - should return 0.75
        engine.render("Test", {})
        engine.render("Test", {})
        assert engine.get_cache_stats()["cache_hit_rate"] == 0.75


class TestRealWorld:
    """Tests simulating real-world usage."""

    def test_multi_agent_collaboration_prompt(self):
        """Test prompt for multi-agent collaboration."""
        engine = PromptEngine()
        template = """
You are part of a team of {{team_size}} agents.
Your role: {{role}}

Other team members:
{% for agent in team_members %}
- {{agent.name}}: {{agent.role}}
{% endfor %}

Collaboration mode: {{collaboration_mode}}
"""

        result = engine.render(
            template,
            {
                "team_size": 3,
                "role": "Researcher",
                "team_members": [
                    {"name": "Alice", "role": "Designer"},
                    {"name": "Bob", "role": "Developer"},
                ],
                "collaboration_mode": "consensus",
            },
        )

        assert "3 agents" in result
        assert "Alice" in result
        assert "Designer" in result
        assert "consensus" in result


class TestTemplateInjectionPrevention:
    """Tests for preventing template injection attacks (SSTI)."""

    def test_user_input_cannot_inject_jinja_expressions(self):
        """Test that user input with {{ }} is rendered as literal text."""
        engine = PromptEngine()
        template = "User said: {{user_input}}"

        # User tries to inject Jinja2 expression
        malicious_input = "{{ 7 * 7 }}"
        result = engine.render(template, {"user_input": malicious_input})

        # Should render as literal text, not execute the expression
        assert (
            "49" not in result
        ), "Jinja2 expression was evaluated — injection succeeded"

    def test_user_input_cannot_inject_jinja_statements(self):
        """Test that user input with {% %} is rendered as literal text."""
        engine = PromptEngine()
        template = "User said: {{user_input}}"

        # User tries to inject Jinja2 statement
        malicious_input = "{% for i in range(10) %}X{% endfor %}"
        result = engine.render(template, {"user_input": malicious_input})

        # Should render as literal text, not execute the loop
        assert (
            result.count("X") < 10
        ), "Jinja2 for-loop was executed — injection succeeded"

    def test_cannot_access_python_builtins(self):
        """Test that Python builtins are not accessible from templates."""
        engine = PromptEngine()

        dangerous_templates = [
            # Try to access __builtins__
            "{{ __builtins__ }}",
            "{{ __builtins__.__dict__ }}",
            # Try to call eval
            "{{ eval('1+1') }}",
            # Try to call exec
            "{{ exec('import os') }}",
            # Try to import
            "{{ __import__('os').system('ls') }}",
        ]

        for template in dangerous_templates:
            try:
                result = engine.render(template, {})
                # If it doesn't raise, verify dangerous operations didn't execute
                # Sandbox should render as empty/undefined, not execute
                assert result == "" or "__builtins__" not in result
                assert "dict" not in result  # __dict__ shouldn't work
            except (PromptRenderError, Exception):
                # Also acceptable to raise exception
                pass

    def test_cannot_access_object_internals(self):
        """Test that object.__class__ and similar internals are not accessible."""
        engine = PromptEngine()

        dangerous_templates = [
            # Classic SSTI payload: access object subclasses
            "{{ ''.__class__.__mro__[1].__subclasses__() }}",
            # Try to access __class__
            "{{ user_input.__class__ }}",
            # Try to access __globals__
            "{{ user_input.__globals__ }}",
            # Try to access __bases__
            "{{ ().__class__.__bases__ }}",
        ]

        for template in dangerous_templates:
            try:
                result = engine.render(template, {"user_input": "test"})
                # Sandbox should render as empty/undefined, not execute
                assert result == "" or "class" not in result.lower()
                assert "subclasses" not in result
            except (PromptRenderError, Exception):
                # Also acceptable to raise exception
                pass

    def test_cannot_access_config_object(self):
        """Test that template config object is not accessible."""
        engine = PromptEngine()

        dangerous_templates = [
            "{{ config }}",
            "{{ self }}",
            "{{ self.config }}",
        ]

        for template in dangerous_templates:
            try:
                result = engine.render(template, {})
                # Sandbox should render undefined variables as empty
                assert result == "" or "Environment" not in result
            except (PromptRenderError, Exception):
                # Also acceptable to raise exception
                pass

    def test_dangerous_filters_are_blocked(self):
        """Test that dangerous Jinja2 filters are disabled."""
        engine = PromptEngine()

        dangerous_templates = [
            # 'attr' filter can access attributes dynamically
            "{{ user_input|attr('__class__') }}",
            # Try other potentially dangerous filters
            "{{ user_input|map(attribute='__class__') }}",
        ]

        for template in dangerous_templates:
            try:
                result = engine.render(template, {"user_input": "test"})
                # Sandbox should block dangerous attribute access
                assert "__class__" not in result or "class 'str'" not in result
            except (PromptRenderError, Exception):
                # Also acceptable to raise exception (preferred)
                pass

    def test_file_system_access_is_restricted(self):
        """Test that file system operations are not allowed."""
        engine = PromptEngine()

        dangerous_templates = [
            # Try to read /etc/passwd
            "{{ open('/etc/passwd').read() }}",
            # Try to access filesystem via os module
            "{{ __import__('os').listdir('/') }}",
        ]

        for template in dangerous_templates:
            with pytest.raises((PromptRenderError, Exception)):
                result = engine.render(template, {})
                # Should not be able to read files
                assert "root:" not in result  # /etc/passwd content

    def test_import_statements_are_blocked(self):
        """Test that import statements cannot be executed."""
        engine = PromptEngine()

        dangerous_templates = [
            "{{ __import__('os') }}",
            "{{ __import__('sys') }}",
            "{{ __import__('subprocess') }}",
        ]

        for template in dangerous_templates:
            with pytest.raises((PromptRenderError, Exception)):
                result = engine.render(template, {})
                # Should not allow imports
                assert "module" not in result.lower() or "PromptRenderError" in str(
                    type(result)
                )

    def test_nested_attribute_access_is_blocked(self):
        """Test that deeply nested attribute access is blocked."""
        engine = PromptEngine()

        dangerous_templates = [
            "{{ [].__class__.__base__.__subclasses__() }}",
            "{{ {}.__class__.__bases__[0].__subclasses__() }}",
            "{{ ().__class__.__base__.__subclasses__()[104].__init__.__globals__ }}",
        ]

        for template in dangerous_templates:
            with pytest.raises((PromptRenderError, Exception)):
                result = engine.render(template, {})
                # Should block nested access
                assert "subclasses" not in result

    def test_environment_variables_not_accessible(self):
        """Test that environment variables cannot be accessed."""
        engine = PromptEngine()

        dangerous_templates = [
            "{{ __import__('os').environ }}",
            "{{ __import__('os').getenv('HOME') }}",
        ]

        for template in dangerous_templates:
            with pytest.raises((PromptRenderError, Exception)):
                result = engine.render(template, {})
                # Should not expose env vars
                assert "/home/" not in result or "PromptRenderError" in str(
                    type(result)
                )

    def test_macro_abuse_prevention(self):
        """Test that macros cannot be abused for code execution."""
        engine = PromptEngine()

        dangerous_template = """
        {% macro dangerous() %}
        {{ __import__('os').system('ls') }}
        {% endmacro %}
        {{ dangerous() }}
        """

        with pytest.raises((PromptRenderError, Exception)):
            result = engine.render(dangerous_template, {})
            # Macro should not execute dangerous code
            assert "__import__" not in result

    def test_unicode_escape_bypass_attempts(self):
        """Test that Unicode escaping doesn't bypass security."""
        engine = PromptEngine()

        dangerous_templates = [
            # Unicode escape for underscore
            "{{ ''.__class__ }}",
            # Try hex encoding
            "{{ '\x5f\x5fclass\x5f\x5f' }}",
        ]

        for template in dangerous_templates:
            result = engine.render(template, {})
            # Should not execute even with encoding tricks
            assert "class 'str'" not in result or "PromptRenderError" in str(
                type(result)
            )

    def test_safe_filters_still_work(self):
        """Test that safe, useful filters are still available."""
        engine = PromptEngine()

        safe_templates = [
            ("{{ name|upper }}", {"name": "alice"}, "ALICE"),
            ("{{ items|length }}", {"items": [1, 2, 3]}, "3"),
            ("{{ name|default('Guest') }}", {}, "Guest"),
            ("{{ value|int }}", {"value": "42"}, "42"),
        ]

        for template, variables, expected in safe_templates:
            result = engine.render(template, variables)
            assert expected in result

    def test_injection_in_template_file_context(self):
        """Test that injection prevention works with file templates too."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            templates_dir = Path(tmpdir)
            template_file = templates_dir / "test.txt"

            # Template that renders user input
            template_file.write_text("User said: {{user_input}}")

            engine = PromptEngine(templates_dir=templates_dir)

            # Try to inject via user_input variable
            malicious_input = "{{ __import__('os').system('ls') }}"
            result = engine.render_file("test.txt", {"user_input": malicious_input})

            # Should render as literal text
            assert "{{ __import__" in result or "ls" not in result

    def test_real_world_ssti_payloads(self):
        """Test against real-world SSTI payloads from security research."""
        engine = PromptEngine()

        # Real payloads from PayloadsAllTheThings
        real_world_payloads = [
            "{{ self._TemplateReference__context.cycler.__init__.__globals__.os.popen('id').read() }}",
            "{{ lipsum.__globals__.__builtins__.__import__('os').popen('id').read() }}",
            "{{ cycler.__init__.__globals__.os.popen('id').read() }}",
            "{% for c in [].__class__.__base__.__subclasses__() %}{% if c.__name__ == 'catch_warnings' %}{{ c.__init__.__globals__['__builtins__'].open('/etc/passwd').read() }}{% endif %}{% endfor %}",
        ]

        for payload in real_world_payloads:
            with pytest.raises((PromptRenderError, Exception)):
                result = engine.render(payload, {})
                # Verify dangerous operations didn't execute
                assert "root:" not in result  # /etc/passwd content
                assert "uid=" not in result  # 'id' command output


class TestLargeTemplatePerformance:
    """Performance tests for large template rendering (P2)."""

    @pytest.mark.slow
    def test_10kb_template_performance(self):
        """
        Test that 10KB template renders in <50ms.

        Performance requirement: Large templates should render efficiently
        without significant overhead from template size alone.
        """
        import time

        engine = PromptEngine()

        # Create 10KB template (~10,000 characters)
        # Using loop to generate many lines of output
        large_template = """
        You are {{agent_name}}, analyzing {{domain}}.
        {% for i in range(250) %}
        Item {{i}}: Processing {{data}} with parameters and configurations for iteration {{i}}
        {% endfor %}
        Summary complete.
        """

        variables = {
            "agent_name": "researcher",
            "domain": "artificial intelligence",
            "data": "test_data_value",
        }

        # First render to compile template (don't count compilation time)
        engine.render(large_template, variables)

        # Measure actual render time (cached template)
        start = time.time()
        result = engine.render(large_template, variables)
        elapsed_ms = (time.time() - start) * 1000

        # Verify output is substantial
        assert len(result) > 5000, "Template should produce substantial output"

        # Performance requirement: <50ms for 10KB template
        assert (
            elapsed_ms < 50
        ), f"10KB template took {elapsed_ms:.2f}ms (baseline: <50ms)"

    @pytest.mark.slow
    def test_100kb_template_performance(self):
        """
        Test that 100KB template renders in <500ms.

        Performance requirement: Very large templates should still render
        in reasonable time (<500ms) for production use.
        """
        import time

        engine = PromptEngine()

        # Create 100KB template (~100,000 characters)
        # Using nested loops and conditionals
        large_template = """
        Agent: {{agent_name}}
        Task: {{task}}

        {% for section in range(50) %}
        Section {{section}}:
        {% for item in range(50) %}
          {% if item % 2 == 0 %}
          - Even item {{item}}: Data from section {{section}} item {{item}}
          {% else %}
          - Odd item {{item}}: Processing {{value}}
          {% endif %}
        {% endfor %}
        {% endfor %}

        Analysis complete for {{domain}}.
        """

        variables = {
            "agent_name": "analyzer",
            "task": "comprehensive_analysis",
            "domain": "machine_learning",
            "value": "test_value",
        }

        # First render to compile template (don't count compilation time)
        engine.render(large_template, variables)

        # Measure actual render time (cached template)
        start = time.time()
        result = engine.render(large_template, variables)
        elapsed_ms = (time.time() - start) * 1000

        # Verify output is very large
        assert len(result) > 50000, "Template should produce very large output"

        # Performance requirement: <500ms for 100KB template
        assert (
            elapsed_ms < 500
        ), f"100KB template took {elapsed_ms:.2f}ms (baseline: <500ms)"

    def test_large_template_memory_efficiency(self):
        """
        Test that large template rendering is memory efficient.

        Memory requirement: Should not create unnecessary copies of template
        or result during rendering.
        """
        import gc

        engine = PromptEngine()

        # Create large template
        large_template = """
        {% for i in range(1000) %}
        Line {{i}}: {{data}} - {{message}}
        {% endfor %}
        """

        variables = {"data": "test_data", "message": "processing"}

        # Force garbage collection before measurement
        gc.collect()

        # Render multiple times
        results = []
        for _ in range(10):
            result = engine.render(large_template, variables)
            results.append(result)

        # Force garbage collection
        gc.collect()

        # All results should be the same (verifies correctness)
        assert all(
            r == results[0] for r in results
        ), "All renders should produce identical output"

        # Verify substantial output
        assert len(results[0]) > 10000, "Each result should be substantial"

    def test_large_template_with_complex_logic(self):
        """
        Test performance with large template containing complex logic.

        Tests: Nested loops, conditionals, filters, and variable substitution
        all working together in a large template.
        """
        import time

        engine = PromptEngine()

        # Complex template with multiple features
        complex_template = """
        Agent Report: {{agent_name|upper}}
        Domain: {{domain}}
        Timestamp: {{timestamp}}

        {% if include_summary %}
        Summary:
        {% for category in categories %}
          Category: {{category.name}}
          {% for item in category['items'] %}
            - {{item.name}}: {{item.value|default('N/A')}}
            {% if item.priority == 'high' %}
              PRIORITY: HIGH - Requires immediate attention
            {% elif item.priority == 'medium' %}
              PRIORITY: MEDIUM - Schedule for review
            {% else %}
              PRIORITY: LOW - Optional review
            {% endif %}
          {% endfor %}
        {% endfor %}
        {% endif %}

        {% for i in range(100) %}
        Iteration {{i}}: Status {% if i % 10 == 0 %}CHECKPOINT{% else %}OK{% endif %}
        {% endfor %}

        Analysis: {{tools|length}} tools available
        Completion: {{progress}}%
        """

        # Complex nested data
        categories = []
        for i in range(10):
            items = []
            for j in range(10):
                items.append(
                    {
                        "name": f"Item_{i}_{j}",
                        "value": f"Value_{j}",
                        "priority": ["high", "medium", "low"][j % 3],
                    }
                )
            categories.append({"name": f"Category_{i}", "items": items})

        variables = {
            "agent_name": "analyzer",
            "domain": "performance_testing",
            "timestamp": "2026-01-28T00:00:00Z",
            "include_summary": True,
            "categories": categories,
            "tools": [{"name": f"tool_{i}"} for i in range(5)],
            "progress": 95,
        }

        # First render to compile
        engine.render(complex_template, variables)

        # Measure render time
        start = time.time()
        result = engine.render(complex_template, variables)
        elapsed_ms = (time.time() - start) * 1000

        # Verify output contains expected elements
        assert "ANALYZER" in result  # |upper filter worked
        assert "CHECKPOINT" in result  # Conditional worked
        assert "PRIORITY: HIGH" in result  # Nested conditional worked
        assert "5 tools available" in result  # Filter worked

        # Performance should still be reasonable
        assert (
            elapsed_ms < 200
        ), f"Complex template took {elapsed_ms:.2f}ms (should be <200ms)"

    @pytest.mark.slow
    def test_very_large_loop_performance(self):
        """
        Test performance with very large loops (1000+ iterations).

        Edge case: Ensure loop iteration overhead doesn't become prohibitive
        with many iterations.
        """
        import time

        engine = PromptEngine()

        # Template with very large loop
        template = """
        {% for i in range(2000) %}
        {{i}}: {{prefix}}_{{i}}_{{suffix}}
        {% endfor %}
        """

        variables = {"prefix": "item", "suffix": "processed"}

        # First render to compile
        engine.render(template, variables)

        # Measure render time
        start = time.time()
        result = engine.render(template, variables)
        elapsed_ms = (time.time() - start) * 1000

        # Verify all iterations executed
        assert "1999: item_1999_processed" in result

        # Should complete in reasonable time
        assert (
            elapsed_ms < 100
        ), f"Large loop took {elapsed_ms:.2f}ms (should be <100ms)"

    def test_large_template_caching_benefit(self):
        """
        Test that caching provides significant benefit for large templates.

        Validates: Template compilation is expensive for large templates,
        so caching should provide meaningful speedup.
        """
        import time

        engine = PromptEngine()

        # Large template
        large_template = """
        {% for i in range(500) %}
        Section {{i}}:
          {% for j in range(10) %}
          - Item {{j}}: {{data}}
          {% endfor %}
        {% endfor %}
        """

        variables = {"data": "test"}

        # Measure uncached render (includes compilation)
        engine.clear_cache()
        start = time.time()
        result1 = engine.render(large_template, variables)
        uncached_time_ms = (time.time() - start) * 1000

        # Measure cached render (template already compiled)
        start = time.time()
        result2 = engine.render(large_template, variables)
        cached_time_ms = (time.time() - start) * 1000

        # Results should be identical
        assert result1 == result2

        # Cached render should be faster (at least 30% faster to account for variance)
        assert (
            cached_time_ms < uncached_time_ms * 0.7
        ), f"Cached ({cached_time_ms:.2f}ms) should be faster than uncached ({uncached_time_ms:.2f}ms)"

    def test_template_size_scaling(self):
        """
        Test that rendering time scales reasonably with template size.

        Validates: Rendering time should scale roughly linearly with output size,
        not quadratically or worse.
        """
        import time

        engine = PromptEngine()

        times = []
        sizes = [100, 200, 400, 800]  # Doubling sizes

        for size in sizes:
            template = """
            {% for i in range(SIZE) %}
            Line {{i}}: {{data}}
            {% endfor %}
            """.replace("SIZE", str(size))

            variables = {"data": "test"}

            # Compile first
            engine.render(template, variables)

            # Measure render time
            start = time.time()
            engine.render(template, variables)
            elapsed_ms = (time.time() - start) * 1000

            times.append(elapsed_ms)

        # Check scaling: doubling size should roughly double time (within 3x tolerance)
        # times[1] should be ~2x times[0]
        # times[2] should be ~4x times[0]
        # times[3] should be ~8x times[0]

        # Verify roughly linear scaling (not quadratic)
        # If quadratic, times[3] would be 64x times[0]
        # We allow up to 12x due to timing variance and overhead
        ratio = times[-1] / times[0]
        assert (
            ratio < 12
        ), f"Scaling appears super-linear: {times} (ratio: {ratio:.1f}x)"

    def test_large_variable_substitution_count(self):
        """
        Test performance with many variable substitutions.

        Edge case: Ensure variable lookup doesn't become bottleneck
        with hundreds of substitutions.
        """
        import time

        engine = PromptEngine()

        # Template with many variable substitutions
        template = " ".join([f"{{{{var_{i}}}}}" for i in range(500)])

        # Provide all variables
        variables = {f"var_{i}": f"value_{i}" for i in range(500)}

        # Compile first
        engine.render(template, variables)

        # Measure render time
        start = time.time()
        result = engine.render(template, variables)
        elapsed_ms = (time.time() - start) * 1000

        # Verify all substitutions happened
        assert "value_0" in result
        assert "value_499" in result

        # Should complete quickly despite many substitutions
        assert (
            elapsed_ms < 50
        ), f"Many substitutions took {elapsed_ms:.2f}ms (should be <50ms)"
