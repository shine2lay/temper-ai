"""Tests for YAML config importer."""


import pytest

from temper_ai.config import ConfigStore
from temper_ai.config.importer import import_yaml


@pytest.fixture
def store():
    return ConfigStore()


class TestImportYaml:
    def test_import_agent_yaml(self, store, tmp_path):
        yaml_file = tmp_path / "test_agent.yaml"
        yaml_file.write_text("agent:\n  name: test_import\n  type: llm\n  system_prompt: hello\n")
        result = import_yaml(str(yaml_file), store)
        assert result["type"] == "agent"
        assert result["name"] == "test_import"

    def test_import_workflow_yaml(self, store, tmp_path):
        yaml_file = tmp_path / "test_wf.yaml"
        yaml_file.write_text("workflow:\n  name: test_wf\n  nodes: []\n")
        result = import_yaml(str(yaml_file), store)
        assert result["type"] == "workflow"
        assert result["name"] == "test_wf"

    def test_import_missing_name_raises(self, store, tmp_path):
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("agent:\n  type: llm\n")
        with pytest.raises(Exception):
            import_yaml(str(yaml_file), store)

    def test_import_unknown_type_raises(self, store, tmp_path):
        yaml_file = tmp_path / "unknown.yaml"
        yaml_file.write_text("foobar:\n  name: x\n")
        with pytest.raises(Exception):
            import_yaml(str(yaml_file), store)

    def test_imported_config_retrievable(self, store, tmp_path):
        yaml_file = tmp_path / "retrievable.yaml"
        yaml_file.write_text("agent:\n  name: retrievable_agent\n  type: llm\n")
        import_yaml(str(yaml_file), store)
        config = store.get("retrievable_agent", "agent")
        # Config may be nested or flat depending on store implementation
        assert config is not None

    def test_import_invalid_yaml_raises(self, store, tmp_path):
        yaml_file = tmp_path / "invalid.yaml"
        yaml_file.write_text("this: is: not: valid: yaml: {{{\n")
        with pytest.raises(Exception):
            import_yaml(str(yaml_file), store)
