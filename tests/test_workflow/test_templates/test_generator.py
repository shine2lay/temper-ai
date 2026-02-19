"""Tests for TemplateGenerator."""

import yaml
import pytest

from temper_ai.workflow.templates._schemas import TemplateManifest, TemplateQualityGates
from temper_ai.workflow.templates.generator import (
    TemplateGenerator,
    _replace_placeholder,
    _apply_inference_overrides,
)
from temper_ai.workflow.templates.registry import TemplateRegistry

# ── Helpers ──────────────────────────────────────────────────────────

MANIFEST_DATA = {
    "product_type": "api",
    "name": "Test API",
    "description": "Test API template",
    "version": "1.0",
    "required_inputs": ["project_description"],
    "stages": ["design", "test"],
    "tags": ["api"],
    "quality_gates": {
        "enabled": True,
        "min_confidence": 0.75,
        "require_citations": True,
        "on_failure": "retry_stage",
        "max_retries": 3,
        "custom_checks": ["schema_validation"],
    },
    "default_inference": {
        "provider": "vllm",
        "model": "qwen3-next",
        "base_url": "http://localhost:8000",
    },
}

WORKFLOW_TEMPLATE = {
    "workflow": {
        "name": "{{project_name}}_api",
        "description": "API for {{project_name}}",
        "stages": [
            {
                "name": "design",
                "stage_ref": "configs/stages/{{project_name}}_api_design.yaml",
            },
        ],
        "error_handling": {
            "on_stage_failure": "halt",
            "max_stage_retries": 2,
            "escalation_policy": "GracefulDegradation",
            "enable_rollback": True,
        },
    },
}

STAGE_TEMPLATE = {
    "stage": {
        "name": "{{project_name}}_api_design",
        "agents": ["{{project_name}}_api_designer"],
        "quality_gates": {
            "enabled": True,
            "min_confidence": 0.75,
        },
    },
}

AGENT_TEMPLATE = {
    "agent": {
        "name": "{{project_name}}_api_designer",
        "type": "standard",
        "inference": {
            "provider": "vllm",
            "model": "qwen3-next",
            "base_url": "http://localhost:8000",
        },
        "tools": [],
    },
}


def _setup_template(tmp_path):
    """Create a complete template directory for testing."""
    tpl_dir = tmp_path / "templates" / "api"
    tpl_dir.mkdir(parents=True)
    stages_dir = tpl_dir / "stages"
    agents_dir = tpl_dir / "agents"
    stages_dir.mkdir()
    agents_dir.mkdir()

    with open(tpl_dir / "manifest.yaml", "w") as f:
        yaml.dump(MANIFEST_DATA, f)
    with open(tpl_dir / "workflow.yaml", "w") as f:
        yaml.dump(WORKFLOW_TEMPLATE, f)
    with open(stages_dir / "design.yaml", "w") as f:
        yaml.dump(STAGE_TEMPLATE, f)
    with open(agents_dir / "api_designer.yaml", "w") as f:
        yaml.dump(AGENT_TEMPLATE, f)

    return tmp_path / "templates"


# ── Unit Tests: _replace_placeholder ─────────────────────────────────


class TestReplacePlaceholder:
    """Tests for _replace_placeholder."""

    def test_string_replacement(self):
        result = _replace_placeholder("{{project_name}}_api", "myproj")
        assert result == "myproj_api"

    def test_nested_dict(self):
        data = {"name": "{{project_name}}_api", "inner": {"ref": "{{project_name}}_ref"}}
        result = _replace_placeholder(data, "myproj")
        assert result["name"] == "myproj_api"
        assert result["inner"]["ref"] == "myproj_ref"

    def test_list_replacement(self):
        data = ["{{project_name}}_a", "{{project_name}}_b"]
        result = _replace_placeholder(data, "myproj")
        assert result == ["myproj_a", "myproj_b"]

    def test_non_string_passthrough(self):
        assert _replace_placeholder(42, "myproj") == 42
        assert _replace_placeholder(True, "myproj") is True
        assert _replace_placeholder(None, "myproj") is None

    def test_no_placeholder(self):
        assert _replace_placeholder("plain text", "myproj") == "plain text"


# ── Unit Tests: _apply_inference_overrides ───────────────────────────


class TestApplyInferenceOverrides:
    """Tests for _apply_inference_overrides."""

    def test_overrides_provider(self):
        agent = {"agent": {"inference": {"provider": "vllm", "model": "m1"}}}
        result = _apply_inference_overrides(agent, {"provider": "ollama"})
        assert result["agent"]["inference"]["provider"] == "ollama"
        assert result["agent"]["inference"]["model"] == "m1"

    def test_overrides_multiple(self):
        agent = {"agent": {"inference": {"provider": "vllm", "model": "m1", "base_url": "http://a"}}}
        result = _apply_inference_overrides(
            agent, {"model": "m2", "base_url": "http://b"},
        )
        assert result["agent"]["inference"]["provider"] == "vllm"
        assert result["agent"]["inference"]["model"] == "m2"
        assert result["agent"]["inference"]["base_url"] == "http://b"

    def test_does_not_mutate_original(self):
        agent = {"agent": {"inference": {"provider": "vllm"}}}
        _apply_inference_overrides(agent, {"provider": "ollama"})
        assert agent["agent"]["inference"]["provider"] == "vllm"

    def test_non_dict_passthrough(self):
        assert _apply_inference_overrides("str", {}) == "str"


# ── Integration Tests: TemplateGenerator ─────────────────────────────


class TestTemplateGeneratorGenerate:
    """Tests for TemplateGenerator.generate."""

    def test_generates_workflow_file(self, tmp_path):
        templates_dir = _setup_template(tmp_path)
        registry = TemplateRegistry(templates_dir=templates_dir)
        gen = TemplateGenerator(registry=registry)

        output = tmp_path / "output"
        result = gen.generate("api", "myproj", output)

        assert result.exists()
        assert result.name == "myproj_workflow.yaml"
        with open(result) as f:
            data = yaml.safe_load(f)
        assert data["workflow"]["name"] == "myproj_api"

    def test_stamps_stage_refs(self, tmp_path):
        templates_dir = _setup_template(tmp_path)
        registry = TemplateRegistry(templates_dir=templates_dir)
        gen = TemplateGenerator(registry=registry)

        output = tmp_path / "output"
        gen.generate("api", "myproj", output)

        workflow_path = output / "workflows" / "myproj_workflow.yaml"
        with open(workflow_path) as f:
            data = yaml.safe_load(f)
        stage_ref = data["workflow"]["stages"][0]["stage_ref"]
        assert "myproj" in stage_ref
        assert "{{project_name}}" not in stage_ref

    def test_stamps_stage_files(self, tmp_path):
        templates_dir = _setup_template(tmp_path)
        registry = TemplateRegistry(templates_dir=templates_dir)
        gen = TemplateGenerator(registry=registry)

        output = tmp_path / "output"
        gen.generate("api", "myproj", output)

        stage_path = output / "stages" / "design.yaml"
        assert stage_path.exists()
        with open(stage_path) as f:
            data = yaml.safe_load(f)
        assert data["stage"]["name"] == "myproj_api_design"
        assert "{{project_name}}" not in str(data)

    def test_stamps_agent_files(self, tmp_path):
        templates_dir = _setup_template(tmp_path)
        registry = TemplateRegistry(templates_dir=templates_dir)
        gen = TemplateGenerator(registry=registry)

        output = tmp_path / "output"
        gen.generate("api", "myproj", output)

        agent_path = output / "agents" / "api_designer.yaml"
        assert agent_path.exists()
        with open(agent_path) as f:
            data = yaml.safe_load(f)
        assert data["agent"]["name"] == "myproj_api_designer"

    def test_inference_overrides(self, tmp_path):
        templates_dir = _setup_template(tmp_path)
        registry = TemplateRegistry(templates_dir=templates_dir)
        gen = TemplateGenerator(registry=registry)

        output = tmp_path / "output"
        gen.generate(
            "api", "myproj", output,
            inference_overrides={"provider": "ollama", "model": "llama3"},
        )

        agent_path = output / "agents" / "api_designer.yaml"
        with open(agent_path) as f:
            data = yaml.safe_load(f)
        assert data["agent"]["inference"]["provider"] == "ollama"
        assert data["agent"]["inference"]["model"] == "llama3"

    def test_quality_gates_applied_to_stages(self, tmp_path):
        templates_dir = _setup_template(tmp_path)
        registry = TemplateRegistry(templates_dir=templates_dir)
        gen = TemplateGenerator(registry=registry)

        output = tmp_path / "output"
        gen.generate("api", "myproj", output)

        stage_path = output / "stages" / "design.yaml"
        with open(stage_path) as f:
            data = yaml.safe_load(f)
        qg = data["stage"]["quality_gates"]
        assert qg["enabled"] is True
        assert qg["min_confidence"] == 0.75

    def test_creates_output_subdirs(self, tmp_path):
        templates_dir = _setup_template(tmp_path)
        registry = TemplateRegistry(templates_dir=templates_dir)
        gen = TemplateGenerator(registry=registry)

        output = tmp_path / "output"
        gen.generate("api", "myproj", output)

        assert (output / "workflows").is_dir()
        assert (output / "stages").is_dir()
        assert (output / "agents").is_dir()
