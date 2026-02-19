"""Integration tests using real template configs."""

from pathlib import Path

import yaml

from temper_ai.workflow.templates.generator import TemplateGenerator
from temper_ai.workflow.templates.registry import TemplateRegistry

CONFIGS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "configs"
TEMPLATES_DIR = CONFIGS_DIR / "templates"

# Product types that should exist in configs/templates/
EXPECTED_TYPES = ["web_app", "api", "data_pipeline", "cli_tool"]


class TestRealTemplateDiscovery:
    """Tests that real template configs are discoverable."""

    def test_all_product_types_present(self):
        registry = TemplateRegistry(templates_dir=TEMPLATES_DIR)
        templates = registry.list_templates()
        found_types = {t.product_type for t in templates}
        for pt in EXPECTED_TYPES:
            assert pt in found_types, f"Missing template: {pt}"

    def test_all_templates_validate(self):
        registry = TemplateRegistry(templates_dir=TEMPLATES_DIR)
        for pt in EXPECTED_TYPES:
            errors = registry.validate_template(pt)
            assert errors == [], f"Validation errors for {pt}: {errors}"

    def test_manifests_have_stages(self):
        registry = TemplateRegistry(templates_dir=TEMPLATES_DIR)
        for pt in EXPECTED_TYPES:
            manifest = registry.get_manifest(pt)
            assert len(manifest.stages) >= 1, f"{pt} has no stages"

    def test_manifests_have_required_inputs(self):
        registry = TemplateRegistry(templates_dir=TEMPLATES_DIR)
        for pt in EXPECTED_TYPES:
            manifest = registry.get_manifest(pt)
            assert len(manifest.required_inputs) >= 1, (
                f"{pt} has no required_inputs"
            )


class TestRealTemplateGeneration:
    """End-to-end generation from real templates."""

    def test_generate_api_project(self, tmp_path):
        registry = TemplateRegistry(templates_dir=TEMPLATES_DIR)
        gen = TemplateGenerator(registry=registry)

        result = gen.generate("api", "test_project", tmp_path)

        assert result.exists()
        with open(result) as f:
            data = yaml.safe_load(f)
        assert "test_project" in data["workflow"]["name"]
        assert "{{project_name}}" not in str(data)

    def test_generate_all_types(self, tmp_path):
        registry = TemplateRegistry(templates_dir=TEMPLATES_DIR)
        gen = TemplateGenerator(registry=registry)

        for pt in EXPECTED_TYPES:
            out = tmp_path / pt
            result = gen.generate(pt, "demo", out)
            assert result.exists()

            with open(result) as f:
                workflow = yaml.safe_load(f)
            assert "{{project_name}}" not in str(workflow)

            # Check stages and agents were generated
            assert (out / "stages").is_dir()
            assert (out / "agents").is_dir()
            stage_files = list((out / "stages").glob("*.yaml"))
            agent_files = list((out / "agents").glob("*.yaml"))
            assert len(stage_files) >= 1
            assert len(agent_files) >= 1
