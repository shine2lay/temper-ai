"""Tests for WI-4: Prompt versioning in PromptEngine.

Tests hash determinism, render_with_metadata, render_file_with_metadata,
different vars produce same hash, different templates produce different hash.
"""

import pytest

from temper_ai.llm.prompts.engine import PromptEngine, _compute_template_hash


class TestComputeTemplateHash:
    """Test _compute_template_hash function."""

    def test_deterministic(self) -> None:
        """Same template always produces same hash."""
        h1 = _compute_template_hash("Hello {{name}}!")
        h2 = _compute_template_hash("Hello {{name}}!")
        assert h1 == h2

    def test_hash_length(self) -> None:
        """Hash is 16 hex characters."""
        h = _compute_template_hash("test template")
        assert len(h) == 16

    def test_different_templates_different_hashes(self) -> None:
        """Different templates produce different hashes."""
        h1 = _compute_template_hash("Hello {{name}}!")
        h2 = _compute_template_hash("Goodbye {{name}}!")
        assert h1 != h2

    def test_empty_template(self) -> None:
        """Empty template produces valid hash."""
        h = _compute_template_hash("")
        assert len(h) == 16

    def test_whitespace_matters(self) -> None:
        """Whitespace differences produce different hashes."""
        h1 = _compute_template_hash("Hello {{name}}")
        h2 = _compute_template_hash("Hello  {{name}}")
        assert h1 != h2


class TestRenderWithMetadata:
    """Test PromptEngine.render_with_metadata."""

    def test_returns_tuple(self) -> None:
        """Returns (rendered, hash, source) tuple."""
        engine = PromptEngine()
        rendered, template_hash, source = engine.render_with_metadata(
            "Hello {{name}}!", {"name": "World"}
        )
        assert rendered == "Hello World!"
        assert len(template_hash) == 16
        assert source == "inline"

    def test_same_template_different_vars_same_hash(self) -> None:
        """Same template with different variables produces same hash."""
        engine = PromptEngine()
        _, h1, _ = engine.render_with_metadata("Hello {{name}}!", {"name": "Alice"})
        _, h2, _ = engine.render_with_metadata("Hello {{name}}!", {"name": "Bob"})
        assert h1 == h2

    def test_different_templates_different_hashes(self) -> None:
        """Different templates produce different hashes."""
        engine = PromptEngine()
        _, h1, _ = engine.render_with_metadata("Hello {{name}}!", {"name": "Alice"})
        _, h2, _ = engine.render_with_metadata("Goodbye {{name}}!", {"name": "Alice"})
        assert h1 != h2

    def test_no_variables(self) -> None:
        """Works without variables."""
        engine = PromptEngine()
        rendered, template_hash, source = engine.render_with_metadata("Static prompt")
        assert rendered == "Static prompt"
        assert len(template_hash) == 16

    def test_hash_matches_standalone_function(self) -> None:
        """Hash from render_with_metadata matches _compute_template_hash."""
        engine = PromptEngine()
        template = "You are a {{role}} expert."
        _, h1, _ = engine.render_with_metadata(template, {"role": "Python"})
        h2 = _compute_template_hash(template)
        assert h1 == h2


class TestRenderFileWithMetadata:
    """Test PromptEngine.render_file_with_metadata."""

    def test_file_not_found_raises(self) -> None:
        """Missing template file raises PromptRenderError."""
        from temper_ai.llm.prompts.validation import PromptRenderError

        engine = PromptEngine()
        if engine.jinja_env is None:
            pytest.skip("No templates directory configured")
        with pytest.raises(PromptRenderError):
            engine.render_file_with_metadata("nonexistent_template.txt")

    def test_no_jinja_env_raises(self) -> None:
        """Missing jinja_env raises PromptRenderError."""
        from temper_ai.llm.prompts.validation import PromptRenderError

        engine = PromptEngine(templates_dir="/nonexistent/path")
        with pytest.raises(
            PromptRenderError, match="templates directory not configured"
        ):
            engine.render_file_with_metadata("test.txt")


class TestPromptEngineRender:
    """Tests for PromptEngine.render with inline templates."""

    def test_basic_template_rendering(self) -> None:
        """Plain template without variables renders as-is."""
        engine = PromptEngine()
        result = engine.render("Hello World!")
        assert result == "Hello World!"

    def test_variable_substitution(self) -> None:
        """Variable in template is substituted with provided value."""
        engine = PromptEngine()
        result = engine.render("Hello {{name}}!", {"name": "Alice"})
        assert result == "Hello Alice!"

    def test_missing_variable_raises_prompt_render_error(self) -> None:
        """Calling an undefined variable as a function raises PromptRenderError.

        Jinja2's Undefined.__call__() raises UndefinedError, which the engine
        wraps into PromptRenderError.
        """
        engine = PromptEngine()
        from temper_ai.llm.prompts.validation import PromptRenderError

        with pytest.raises(PromptRenderError):
            engine.render("{{ undefined_var() }}", {})

    def test_empty_variables_dict_no_placeholders(self) -> None:
        """Template without placeholders renders correctly with empty variables."""
        engine = PromptEngine()
        result = engine.render("Static text with no vars.", {})
        assert result == "Static text with no vars."


class TestPromptEngineRenderFile:
    """Tests for PromptEngine.render_file with file-based templates."""

    def test_file_not_found_raises_prompt_render_error(self) -> None:
        """Requesting a non-existent template file raises PromptRenderError."""
        from temper_ai.llm.prompts.validation import PromptRenderError

        engine = PromptEngine()
        if engine.jinja_env is None:
            pytest.skip("No templates directory configured")
        with pytest.raises(PromptRenderError):
            engine.render_file("nonexistent_template_xyz.txt")

    def test_no_templates_dir_raises_prompt_render_error(self) -> None:
        """Engine with no templates dir raises PromptRenderError on render_file."""
        from temper_ai.llm.prompts.validation import PromptRenderError

        engine = PromptEngine(templates_dir="/nonexistent/path")
        with pytest.raises(
            PromptRenderError, match="templates directory not configured"
        ):
            engine.render_file("test.txt")


class TestPromptEngineCacheManagement:
    """Tests for PromptEngine cache statistics and management."""

    def test_get_cache_stats_returns_expected_keys(self) -> None:
        """get_cache_stats returns dict with all required statistics keys."""
        engine = PromptEngine()
        stats = engine.get_cache_stats()
        expected_keys = {
            "cache_hits",
            "cache_misses",
            "cache_size",
            "cache_hit_rate",
            "total_requests",
            "cache_capacity",
        }
        assert expected_keys.issubset(stats.keys())

    def test_clear_cache_resets_stats_to_zero(self) -> None:
        """clear_cache resets hit/miss counters and empties the cache."""
        engine = PromptEngine()
        engine.render("Hello {{name}}!", {"name": "Alice"})
        engine.clear_cache()
        stats = engine.get_cache_stats()
        assert stats["cache_hits"] == 0
        assert stats["cache_misses"] == 0
        assert stats["cache_size"] == 0

    def test_render_same_template_twice_increments_cache_hits(self) -> None:
        """Rendering the same template twice results in one cache hit."""
        engine = PromptEngine()
        engine.render("Hello {{name}}!", {"name": "First"})
        engine.render("Hello {{name}}!", {"name": "Second"})
        stats = engine.get_cache_stats()
        assert stats["cache_hits"] >= 1


class TestTemplateCacheManager:
    """Tests for TemplateCacheManager standalone behavior."""

    def _make_env(self):
        from jinja2.sandbox import ImmutableSandboxedEnvironment

        return ImmutableSandboxedEnvironment()

    def test_cache_hit_on_second_call(self) -> None:
        """Same template string produces a cache hit on the second call."""
        from temper_ai.llm.prompts.cache import TemplateCacheManager

        env = self._make_env()
        cache = TemplateCacheManager(cache_size=10)
        cache.get_or_compile("Hello {{name}}!", env)
        cache.get_or_compile("Hello {{name}}!", env)
        stats = cache.get_cache_stats()
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1

    def test_fifo_eviction_at_capacity(self) -> None:
        """First template is evicted when cache is full (FIFO)."""
        from temper_ai.llm.prompts.cache import TemplateCacheManager

        env = self._make_env()
        cache = TemplateCacheManager(cache_size=2)
        cache.get_or_compile("template_one", env)
        cache.get_or_compile("template_two", env)
        cache.get_or_compile("template_three", env)  # evicts template_one
        stats = cache.get_cache_stats()
        assert stats["cache_size"] == 2
        # Re-fetching evicted template causes a new miss
        cache.get_or_compile("template_one", env)
        stats = cache.get_cache_stats()
        assert stats["cache_misses"] == 4  # 3 initial + 1 re-compile of evicted

    def test_stats_tracking(self) -> None:
        """Cache stats correctly track hits, misses, and total_requests."""
        from temper_ai.llm.prompts.cache import TemplateCacheManager

        env = self._make_env()
        cache = TemplateCacheManager(cache_size=10)
        cache.get_or_compile("t1", env)  # miss
        cache.get_or_compile("t2", env)  # miss
        cache.get_or_compile("t1", env)  # hit
        stats = cache.get_cache_stats()
        assert stats["cache_misses"] == 2
        assert stats["cache_hits"] == 1
        assert stats["total_requests"] == 3
        assert stats["cache_hit_rate"] == pytest.approx(1 / 3)
