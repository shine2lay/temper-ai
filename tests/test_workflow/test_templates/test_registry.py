"""Tests for TemplateRegistry."""

import pytest
import yaml

from src.workflow.templates._schemas import TemplateManifest
from src.workflow.templates.registry import (
    MANIFEST_FILENAME,
    TemplateNotFoundError,
    TemplateRegistry,
)

# ── Helpers ──────────────────────────────────────────────────────────

MINIMAL_MANIFEST = {
    "product_type": "api",
    "name": "Test API",
    "description": "Test API template",
    "version": "1.0",
    "stages": ["design", "test"],
    "tags": ["api"],
    "default_inference": {
        "provider": "vllm",
        "model": "qwen3-next",
        "base_url": "http://localhost:8000",
    },
}


def _create_template(tmp_path, product_type, manifest_data=None):
    """Create a minimal template directory for testing."""
    tpl_dir = tmp_path / product_type
    tpl_dir.mkdir()
    (tpl_dir / "stages").mkdir()
    (tpl_dir / "agents").mkdir()
    (tpl_dir / "workflow.yaml").write_text("workflow: {}")

    data = dict(manifest_data or MINIMAL_MANIFEST)
    data["product_type"] = product_type
    with open(tpl_dir / MANIFEST_FILENAME, "w") as f:
        yaml.dump(data, f)
    return tpl_dir


# ── Tests ────────────────────────────────────────────────────────────


class TestTemplateRegistryListTemplates:
    """Tests for list_templates."""

    def test_empty_dir(self, tmp_path):
        registry = TemplateRegistry(templates_dir=tmp_path)
        assert registry.list_templates() == []

    def test_nonexistent_dir(self, tmp_path):
        registry = TemplateRegistry(templates_dir=tmp_path / "missing")
        assert registry.list_templates() == []

    def test_discovers_templates(self, tmp_path):
        _create_template(tmp_path, "api")
        _create_template(tmp_path, "cli_tool", {
            **MINIMAL_MANIFEST, "name": "CLI Tool",
        })
        registry = TemplateRegistry(templates_dir=tmp_path)
        templates = registry.list_templates()
        assert len(templates) == 2
        types = {t.product_type for t in templates}
        assert types == {"api", "cli_tool"}

    def test_skips_non_directories(self, tmp_path):
        _create_template(tmp_path, "api")
        (tmp_path / "readme.txt").write_text("not a template")
        registry = TemplateRegistry(templates_dir=tmp_path)
        assert len(registry.list_templates()) == 1

    def test_skips_dirs_without_manifest(self, tmp_path):
        _create_template(tmp_path, "api")
        (tmp_path / "bad_template").mkdir()
        registry = TemplateRegistry(templates_dir=tmp_path)
        assert len(registry.list_templates()) == 1


class TestTemplateRegistryGetManifest:
    """Tests for get_manifest."""

    def test_returns_manifest(self, tmp_path):
        _create_template(tmp_path, "api")
        registry = TemplateRegistry(templates_dir=tmp_path)
        manifest = registry.get_manifest("api")
        assert isinstance(manifest, TemplateManifest)
        assert manifest.product_type == "api"

    def test_caches_result(self, tmp_path):
        _create_template(tmp_path, "api")
        registry = TemplateRegistry(templates_dir=tmp_path)
        m1 = registry.get_manifest("api")
        m2 = registry.get_manifest("api")
        assert m1 is m2

    def test_missing_template_raises(self, tmp_path):
        registry = TemplateRegistry(templates_dir=tmp_path)
        with pytest.raises(TemplateNotFoundError):
            registry.get_manifest("nonexistent")

    def test_missing_manifest_file_raises(self, tmp_path):
        (tmp_path / "api").mkdir()
        registry = TemplateRegistry(templates_dir=tmp_path)
        with pytest.raises(TemplateNotFoundError):
            registry.get_manifest("api")


class TestTemplateRegistryGetTemplateDir:
    """Tests for get_template_dir."""

    def test_returns_path(self, tmp_path):
        _create_template(tmp_path, "api")
        registry = TemplateRegistry(templates_dir=tmp_path)
        result = registry.get_template_dir("api")
        assert result == tmp_path / "api"

    def test_missing_raises(self, tmp_path):
        registry = TemplateRegistry(templates_dir=tmp_path)
        with pytest.raises(TemplateNotFoundError):
            registry.get_template_dir("nonexistent")


class TestTemplateRegistryValidate:
    """Tests for validate_template."""

    def test_valid_template(self, tmp_path):
        _create_template(tmp_path, "api")
        registry = TemplateRegistry(templates_dir=tmp_path)
        errors = registry.validate_template("api")
        assert errors == []

    def test_missing_dir(self, tmp_path):
        registry = TemplateRegistry(templates_dir=tmp_path)
        errors = registry.validate_template("missing")
        assert len(errors) == 1
        assert "missing" in errors[0].lower()

    def test_missing_subdirs(self, tmp_path):
        tpl_dir = tmp_path / "api"
        tpl_dir.mkdir()
        (tpl_dir / MANIFEST_FILENAME).write_text("product_type: api")
        (tpl_dir / "workflow.yaml").write_text("workflow: {}")
        registry = TemplateRegistry(templates_dir=tmp_path)
        errors = registry.validate_template("api")
        assert len(errors) == 2  # stages + agents dirs missing

    def test_missing_workflow(self, tmp_path):
        tpl_dir = tmp_path / "api"
        tpl_dir.mkdir()
        (tpl_dir / MANIFEST_FILENAME).write_text("product_type: api")
        (tpl_dir / "stages").mkdir()
        (tpl_dir / "agents").mkdir()
        registry = TemplateRegistry(templates_dir=tmp_path)
        errors = registry.validate_template("api")
        assert any("workflow" in e.lower() for e in errors)
