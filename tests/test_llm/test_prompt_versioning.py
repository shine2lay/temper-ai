"""Tests for WI-4: Prompt versioning in PromptEngine.

Tests hash determinism, render_with_metadata, render_file_with_metadata,
different vars produce same hash, different templates produce different hash.
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        with pytest.raises(PromptRenderError, match="templates directory not configured"):
            engine.render_file_with_metadata("test.txt")
