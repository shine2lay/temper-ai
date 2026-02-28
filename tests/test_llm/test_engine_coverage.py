"""Coverage tests for temper_ai/llm/prompts/engine.py.

Covers: PromptEngine init (no templates_dir, search-up), render,
render_file, cache clearing, error paths.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from temper_ai.llm.prompts.engine import PromptEngine
from temper_ai.llm.prompts.validation import PromptRenderError


class TestPromptEngineInit:
    def test_init_with_templates_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = PromptEngine(templates_dir=tmpdir)
            assert engine.jinja_env is not None

    def test_init_without_templates_dir(self) -> None:
        engine = PromptEngine(templates_dir="/nonexistent/path")
        assert engine.jinja_env is None

    def test_init_default_dir_search(self) -> None:
        engine = PromptEngine(templates_dir=None)
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


class TestPromptEngineClearCache:
    def test_clear_cache(self) -> None:
        engine = PromptEngine()
        engine.render("Hello!", {})
        engine.clear_cache()
        result = engine.render("Hello!", {})
        assert result == "Hello!"
