"""Coverage tests for temper_ai/llm/prompts/engine.py.

Covers: PromptEngine init (no templates_dir, search-up), render_file,
render_with_metadata, render_file_with_metadata, _compute_template_hash,
cache stats, clear cache, error paths.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from temper_ai.llm.prompts.engine import PromptEngine, _compute_template_hash
from temper_ai.llm.prompts.validation import PromptRenderError


class TestComputeTemplateHash:
    def test_deterministic(self) -> None:
        h1 = _compute_template_hash("Hello {{name}}!")
        h2 = _compute_template_hash("Hello {{name}}!")
        assert h1 == h2

    def test_different_templates_different_hash(self) -> None:
        h1 = _compute_template_hash("Hello {{name}}!")
        h2 = _compute_template_hash("Goodbye {{name}}!")
        assert h1 != h2

    def test_hash_length(self) -> None:
        h = _compute_template_hash("test")
        assert len(h) == 16


class TestPromptEngineInit:
    def test_init_with_templates_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = PromptEngine(templates_dir=tmpdir)
            assert engine.jinja_env is not None

    def test_init_without_templates_dir(self) -> None:
        engine = PromptEngine(templates_dir="/nonexistent/path")
        assert engine.jinja_env is None

    def test_init_default_dir_search(self) -> None:
        # When templates_dir is None, it searches for configs/prompts
        engine = PromptEngine(templates_dir=None)
        # May or may not find it depending on cwd
        assert engine is not None


class TestPromptEngineRender:
    def test_render_simple(self) -> None:
        engine = PromptEngine()
        result = engine.render("Hello {{name}}!", {"name": "World"})
        assert result == "Hello World!"

    def test_render_no_variables(self) -> None:
        engine = PromptEngine()
        result = engine.render("No variables here.")
        assert result == "No variables here."

    def test_render_error(self) -> None:
        engine = PromptEngine()
        with pytest.raises(PromptRenderError):
            engine.render("{% if %}bad{% endif %}", {})


class TestPromptEngineRenderFile:
    def test_render_file_no_env(self) -> None:
        engine = PromptEngine(templates_dir="/nonexistent/path")
        with pytest.raises(PromptRenderError, match="not configured"):
            engine.render_file("test.txt", {})

    def test_render_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = PromptEngine(templates_dir=tmpdir)
            with pytest.raises(PromptRenderError, match="not found"):
                engine.render_file("nonexistent.txt", {})

    def test_render_file_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "hello.txt")
            with open(template_path, "w") as f:
                f.write("Hello {{name}}!")
            engine = PromptEngine(templates_dir=tmpdir)
            result = engine.render_file("hello.txt", {"name": "World"})
            assert result == "Hello World!"


class TestPromptEngineRenderWithMetadata:
    def test_render_with_metadata(self) -> None:
        engine = PromptEngine()
        text, hash_val, source = engine.render_with_metadata(
            "Hello {{name}}!", {"name": "World"}
        )
        assert text == "Hello World!"
        assert len(hash_val) == 16
        assert source == "inline"


class TestPromptEngineRenderFileWithMetadata:
    def test_no_env_raises(self) -> None:
        engine = PromptEngine(templates_dir="/nonexistent/path")
        with pytest.raises(PromptRenderError, match="not configured"):
            engine.render_file_with_metadata("test.txt", {})

    def test_not_found_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = PromptEngine(templates_dir=tmpdir)
            with pytest.raises(PromptRenderError, match="not found"):
                engine.render_file_with_metadata("missing.txt", {})

    def test_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "meta.txt")
            with open(template_path, "w") as f:
                f.write("Hi {{name}}!")
            engine = PromptEngine(templates_dir=tmpdir)
            text, hash_val, tpath = engine.render_file_with_metadata(
                "meta.txt", {"name": "Bob"}
            )
            assert text == "Hi Bob!"
            assert len(hash_val) == 16
            assert tpath == "meta.txt"


class TestPromptEngineCacheStats:
    def test_cache_stats(self) -> None:
        engine = PromptEngine()
        engine.render("Hello!", {})
        stats = engine.get_cache_stats()
        assert "cache_size" in stats

    def test_clear_cache(self) -> None:
        engine = PromptEngine()
        engine.render("Hello!", {})
        engine.clear_cache()
        stats = engine.get_cache_stats()
        assert stats["cache_size"] == 0
