"""Tests for prompt rendering and cache management.

Tests PromptEngine rendering, file rendering, cache clearing,
and TemplateCacheManager statistics.
"""

import pytest

from temper_ai.llm.prompts.engine import PromptEngine
from temper_ai.llm.prompts.validation import PromptRenderError


class TestPromptEngineRender:
    def test_basic_template_rendering(self) -> None:
        engine = PromptEngine()
        result = engine.render("Hello World!")
        assert result == "Hello World!"

    def test_variable_substitution(self) -> None:
        engine = PromptEngine()
        result = engine.render("Hello {{name}}!", {"name": "Alice"})
        assert result == "Hello Alice!"

    def test_missing_variable_call_raises(self) -> None:
        engine = PromptEngine()
        with pytest.raises(PromptRenderError):
            engine.render("{{ undefined_var() }}", {})

    def test_empty_variables_dict_no_placeholders(self) -> None:
        engine = PromptEngine()
        result = engine.render("Static text with no vars.", {})
        assert result == "Static text with no vars."


class TestPromptEngineRenderFile:
    def test_file_not_found_raises(self) -> None:
        engine = PromptEngine()
        if engine.jinja_env is None:
            pytest.skip("No templates directory configured")
        with pytest.raises(PromptRenderError):
            engine.render_file("nonexistent_template_xyz.txt")

    def test_no_templates_dir_raises(self) -> None:
        engine = PromptEngine(templates_dir="/nonexistent/path")
        with pytest.raises(
            PromptRenderError, match="templates directory not configured"
        ):
            engine.render_file("test.txt")


class TestPromptEngineClearCache:
    def test_clear_cache_allows_rerender(self) -> None:
        engine = PromptEngine()
        engine.render("Hello {{name}}!", {"name": "Alice"})
        engine.clear_cache()
        result = engine.render("Hello {{name}}!", {"name": "Bob"})
        assert result == "Hello Bob!"


class TestTemplateCacheManager:
    def _make_env(self):
        from jinja2.sandbox import ImmutableSandboxedEnvironment

        return ImmutableSandboxedEnvironment()

    def test_cache_hit_on_second_call(self) -> None:
        from temper_ai.llm.prompts.cache import TemplateCacheManager

        env = self._make_env()
        cache = TemplateCacheManager(cache_size=10)
        cache.get_or_compile("Hello {{name}}!", env)
        cache.get_or_compile("Hello {{name}}!", env)
        stats = cache.get_cache_stats()
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1

    def test_fifo_eviction_at_capacity(self) -> None:
        from temper_ai.llm.prompts.cache import TemplateCacheManager

        env = self._make_env()
        cache = TemplateCacheManager(cache_size=2)
        cache.get_or_compile("template_one", env)
        cache.get_or_compile("template_two", env)
        cache.get_or_compile("template_three", env)
        stats = cache.get_cache_stats()
        assert stats["cache_size"] == 2

    def test_stats_tracking(self) -> None:
        from temper_ai.llm.prompts.cache import TemplateCacheManager

        env = self._make_env()
        cache = TemplateCacheManager(cache_size=10)
        cache.get_or_compile("t1", env)
        cache.get_or_compile("t2", env)
        cache.get_or_compile("t1", env)
        stats = cache.get_cache_stats()
        assert stats["cache_misses"] == 2
        assert stats["cache_hits"] == 1
        assert stats["total_requests"] == 3
        assert stats["cache_hit_rate"] == pytest.approx(1 / 3)

    def test_clear_cache_resets(self) -> None:
        from temper_ai.llm.prompts.cache import TemplateCacheManager

        env = self._make_env()
        cache = TemplateCacheManager(cache_size=10)
        cache.get_or_compile("t1", env)
        cache.clear_cache()
        stats = cache.get_cache_stats()
        assert stats["cache_hits"] == 0
        assert stats["cache_misses"] == 0
        assert stats["cache_size"] == 0
