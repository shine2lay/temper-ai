"""Tests for StudioService extracted validation and I/O helpers."""

from pathlib import Path

import pytest
import yaml

from temper_ai.interfaces.dashboard._studio_validation_helpers import (
    get_db_model,
    load_raw_config,
    write_config,
)


class TestLoadRawConfig:
    """Tests for load_raw_config()."""

    def test_loads_valid_yaml_mapping(self, tmp_path: Path) -> None:
        """Returns parsed dict from a valid YAML file."""
        dir_map = {"workflows": "workflows"}
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "my-wf.yaml").write_text("name: my-wf\nversion: 1\n")

        result = load_raw_config("workflows", "my-wf", tmp_path, dir_map)
        assert result == {"name": "my-wf", "version": 1}

    def test_raises_file_not_found_when_missing(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError when YAML file does not exist."""
        dir_map = {"workflows": "workflows"}
        (tmp_path / "workflows").mkdir()

        with pytest.raises(FileNotFoundError, match="Config not found"):
            load_raw_config("workflows", "missing", tmp_path, dir_map)

    def test_error_message_includes_type_and_name(self, tmp_path: Path) -> None:
        """FileNotFoundError message includes config type and name."""
        dir_map = {"stages": "stages"}
        (tmp_path / "stages").mkdir()

        with pytest.raises(FileNotFoundError, match="stages/nonexistent"):
            load_raw_config("stages", "nonexistent", tmp_path, dir_map)

    def test_raises_value_error_for_yaml_list(self, tmp_path: Path) -> None:
        """Raises ValueError when YAML root is a list, not a mapping."""
        dir_map = {"tools": "tools"}
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "list-tool.yaml").write_text("- item1\n- item2\n")

        with pytest.raises(ValueError, match="not a valid YAML mapping"):
            load_raw_config("tools", "list-tool", tmp_path, dir_map)

    def test_raises_value_error_for_yaml_scalar(self, tmp_path: Path) -> None:
        """Raises ValueError when YAML root is a scalar string."""
        dir_map = {"agents": "agents"}
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "bad.yaml").write_text("just a string\n")

        with pytest.raises(ValueError, match="not a valid YAML mapping"):
            load_raw_config("agents", "bad", tmp_path, dir_map)

    def test_handles_nested_dict(self, tmp_path: Path) -> None:
        """Returns deeply nested dicts from YAML."""
        dir_map = {"agents": "agents"}
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        data = {"agent": {"model": "gpt-4", "tools": ["bash", "search"]}}
        (agents_dir / "my-agent.yaml").write_text(yaml.safe_dump(data))

        result = load_raw_config("agents", "my-agent", tmp_path, dir_map)
        assert result["agent"]["model"] == "gpt-4"
        assert result["agent"]["tools"] == ["bash", "search"]

    def test_resolves_subdir_from_dir_map(self, tmp_path: Path) -> None:
        """Uses dir_map to locate the correct subdirectory."""
        dir_map = {"stages": "stage_configs"}
        stage_dir = tmp_path / "stage_configs"
        stage_dir.mkdir()
        (stage_dir / "my-stage.yaml").write_text("name: my-stage\n")

        result = load_raw_config("stages", "my-stage", tmp_path, dir_map)
        assert result["name"] == "my-stage"

    def test_reads_utf8_content(self, tmp_path: Path) -> None:
        """Reads YAML files with UTF-8 encoded content."""
        dir_map = {"workflows": "workflows"}
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "unicode.yaml").write_text(
            "description: héllo wörld\n", encoding="utf-8"
        )

        result = load_raw_config("workflows", "unicode", tmp_path, dir_map)
        assert result["description"] == "héllo wörld"


class TestWriteConfig:
    """Tests for write_config()."""

    def test_writes_yaml_file(self, tmp_path: Path) -> None:
        """Creates a YAML file at the given path."""
        file_path = tmp_path / "output.yaml"
        data = {"name": "test", "value": 42}
        write_config(file_path, data)

        assert file_path.exists()

    def test_written_content_is_valid_yaml(self, tmp_path: Path) -> None:
        """Written file contains valid YAML that round-trips correctly."""
        file_path = tmp_path / "config.yaml"
        data = {"key": "value", "number": 99}
        write_config(file_path, data)

        loaded = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        assert loaded == data

    def test_creates_missing_parent_directories(self, tmp_path: Path) -> None:
        """Creates parent directories that don't yet exist."""
        file_path = tmp_path / "a" / "b" / "c" / "config.yaml"
        write_config(file_path, {"x": 1})

        assert file_path.exists()

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        """Replaces an existing file with new content."""
        file_path = tmp_path / "config.yaml"
        file_path.write_text("old: content\n")

        write_config(file_path, {"new": "content"})

        loaded = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        assert loaded == {"new": "content"}

    def test_writes_nested_dict(self, tmp_path: Path) -> None:
        """Correctly serializes nested dictionaries."""
        file_path = tmp_path / "nested.yaml"
        data = {"outer": {"inner": {"deep": True}}}
        write_config(file_path, data)

        loaded = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        assert loaded["outer"]["inner"]["deep"] is True

    def test_utf8_encoding(self, tmp_path: Path) -> None:
        """Written file round-trips unicode content correctly."""
        file_path = tmp_path / "unicode.yaml"
        write_config(file_path, {"text": "héllo wörld"})

        # yaml.safe_dump may escape non-ASCII, but round-trip should work
        loaded = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        assert loaded["text"] == "héllo wörld"

    def test_writes_list_values(self, tmp_path: Path) -> None:
        """Correctly serializes dict with list values."""
        file_path = tmp_path / "list.yaml"
        data = {"items": ["a", "b", "c"]}
        write_config(file_path, data)

        loaded = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        assert loaded == data

    def test_empty_dict_produces_empty_yaml(self, tmp_path: Path) -> None:
        """Empty dict produces a file (may be empty or null YAML)."""
        file_path = tmp_path / "empty.yaml"
        write_config(file_path, {})

        assert file_path.exists()
        content = file_path.read_text(encoding="utf-8")
        # yaml.safe_dump({}) produces "{}\n" or "null\n" — either is acceptable
        loaded = yaml.safe_load(content)
        assert loaded is None or loaded == {}


class TestGetDbModel:
    """Tests for get_db_model()."""

    def test_workflows_returns_model_class(self) -> None:
        """Returns a class for 'workflows' config type."""
        model = get_db_model("workflows")
        assert model is not None
        assert isinstance(model, type)

    def test_stages_returns_model_class(self) -> None:
        """Returns a class for 'stages' config type."""
        model = get_db_model("stages")
        assert model is not None
        assert isinstance(model, type)

    def test_agents_returns_model_class(self) -> None:
        """Returns a class for 'agents' config type."""
        model = get_db_model("agents")
        assert model is not None
        assert isinstance(model, type)

    def test_raises_for_tools(self) -> None:
        """Raises ValueError for 'tools' (no DB model)."""
        with pytest.raises(ValueError, match="does not have a DB-backed model"):
            get_db_model("tools")

    def test_raises_for_unknown_type(self) -> None:
        """Raises ValueError for arbitrary unknown config types."""
        with pytest.raises(ValueError):
            get_db_model("unknown_xyz")

    def test_raises_for_empty_string(self) -> None:
        """Raises ValueError for empty string config type."""
        with pytest.raises(ValueError):
            get_db_model("")

    def test_workflows_model_name(self) -> None:
        """Returned model class name references Workflow."""
        model = get_db_model("workflows")
        assert "Workflow" in model.__name__

    def test_stages_model_name(self) -> None:
        """Returned model class name references Stage."""
        model = get_db_model("stages")
        assert "Stage" in model.__name__

    def test_agents_model_name(self) -> None:
        """Returned model class name references Agent."""
        model = get_db_model("agents")
        assert "Agent" in model.__name__
