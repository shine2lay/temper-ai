"""Tests for YAML config importer."""


import pytest

from temper_ai.config import ConfigStore
from temper_ai.config.importer import import_config_tree, import_yaml


@pytest.fixture
def store():
    return ConfigStore()


def _write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


class TestImportConfigTree:
    """The shared bulk loader behind server and worker startup."""

    def test_imports_nested_configs(self, store, tmp_path):
        _write(tmp_path / "agents" / "a.yaml", "agent:\n  name: tree_a\n  type: llm\n")
        _write(tmp_path / "workflows" / "deep" / "w.yaml", "workflow:\n  name: tree_w\n  nodes: []\n")

        assert import_config_tree(tmp_path, store) == 2
        # Stored as the raw YAML, top-level type key included.
        assert store.get("tree_a", "agent")["agent"]["type"] == "llm"
        assert store.get("tree_w", "workflow")["workflow"]["nodes"] == []

    def test_skips_mcp_and_tool_yamls(self, store, tmp_path):
        """Those dirs hold non-config YAMLs; importing them would log noise on every boot."""
        _write(tmp_path / "agents" / "keep.yaml", "agent:\n  name: kept\n  type: llm\n")
        _write(tmp_path / "mcp_servers" / "notion.yaml", "name: notion\nurl: https://x\n")
        _write(tmp_path / "tools" / "bash.yaml", "name: bash\n")

        assert import_config_tree(tmp_path, store) == 1

    def test_one_bad_file_does_not_abort_the_rest(self, store, tmp_path):
        """A single broken YAML must not leave the process with zero configs."""
        _write(tmp_path / "ok1.yaml", "agent:\n  name: ok_one\n  type: llm\n")
        _write(tmp_path / "broken.yaml", "agent:\n  nope: [unclosed\n")
        _write(tmp_path / "noname.yaml", "agent:\n  type: llm\n")
        _write(tmp_path / "ok2.yaml", "agent:\n  name: ok_two\n  type: llm\n")

        assert import_config_tree(tmp_path, store) == 2
        assert store.get("ok_one", "agent")["agent"]["name"] == "ok_one"
        assert store.get("ok_two", "agent")["agent"]["name"] == "ok_two"

    def test_empty_dir_returns_zero(self, store, tmp_path):
        assert import_config_tree(tmp_path, store) == 0

    def test_skipped_file_is_reported_at_warning_level(self, store, tmp_path, caplog):
        """The CLI runs at WARNING by default; a debug line here is invisible there."""
        import logging

        broken = tmp_path / "workflows" / "broken.yaml"
        _write(broken, "workflow:\n  name: [unclosed\n")

        with caplog.at_level(logging.WARNING, logger="temper_ai.config.importer"):
            import_config_tree(tmp_path, store)

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1
        # The line must be actionable: which file, and why.
        message = warnings[0].getMessage()
        assert str(broken) in message
        assert "YAML parsing failed" in message
        assert "line 2" in message

    def test_warning_names_the_file_even_when_the_error_does_not(self, store, tmp_path, caplog):
        """A YAML syntax error happens to embed the path; a missing-name error doesn't.

        The log line must carry the path itself, or this case is unfindable.
        """
        import logging

        noname = tmp_path / "workflows" / "anonymous.yaml"
        _write(noname, "workflow:\n  nodes: []\n")

        with caplog.at_level(logging.WARNING, logger="temper_ai.config.importer"):
            import_config_tree(tmp_path, store)

        [record] = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert str(noname) in record.getMessage()
        assert "'name' field" in record.getMessage()

    def test_clean_tree_emits_no_warnings(self, store, tmp_path, caplog):
        """WARNING must mean something: a healthy boot stays quiet."""
        import logging

        _write(tmp_path / "agents" / "a.yaml", "agent:\n  name: quiet_a\n  type: llm\n")
        _write(tmp_path / "mcp_servers" / "x.yaml", "name: x\n")  # skipped by rule, not error

        with caplog.at_level(logging.WARNING, logger="temper_ai.config.importer"):
            import_config_tree(tmp_path, store)

        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


class TestTeamPageFiles:
    """M3 A1 and E7: the Team page's settings folder is not configs, and a team trial's
    configs are written by the Team page only."""

    def test_the_team_settings_folder_under_the_root_is_not_imported(self, store, tmp_path,
                                                                    caplog):
        import logging

        _write(tmp_path / "team" / "team.yaml", "project_roots: []\n")
        _write(tmp_path / "team" / "local" / "team.yaml", "project_roots: [/srv/x]\n")
        # Even a file there that looks like a config is settings, not a config.
        _write(tmp_path / "team" / "agent.yaml", "agent:\n  name: team_settings_a\n  type: llm\n")
        _write(tmp_path / "agents" / "kept.yaml", "agent:\n  name: kept_a1\n  type: llm\n")

        with caplog.at_level(logging.INFO, logger="temper_ai.config.importer"):
            assert import_config_tree(tmp_path, store) == 1
        assert store.get("kept_a1", "agent")
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("Not imported:" in r.getMessage() and "/team/" in r.getMessage()
                   for r in caplog.records)

    def test_a_team_folder_deeper_down_is_still_imported(self, store, tmp_path):
        """Skipped by where it sits under the root, never by a path part: NON_CONFIG_DIRS'
        rule would skip any folder named team anywhere."""
        _write(tmp_path / "agents" / "team" / "deep.yaml",
               "agent:\n  name: deep_team_a\n  type: llm\n")
        _write(tmp_path / "workflows" / "team" / "w.yaml",
               "workflow:\n  name: deep_team_w\n  nodes: []\n")

        assert import_config_tree(tmp_path, store) == 2
        assert store.get("deep_team_a", "agent")
        assert store.get("deep_team_w", "workflow")

    def test_config_files_lists_the_same_files_the_importer_reads(self, tmp_path):
        from temper_ai.config.importer import config_files

        for rel in ("team/team.yaml", "tools/t.yaml", "agents/team/a.yaml", "agents/b.yaml"):
            _write(tmp_path / rel, "agent:\n  name: x\n  type: llm\n")
        assert [p.relative_to(tmp_path).as_posix() for p in config_files(tmp_path)] == [
            "agents/b.yaml", "agents/team/a.yaml"]

    def test_a_file_with_a_team_trials_name_is_skipped_and_logged(self, store, tmp_path,
                                                                  caplog):
        import logging

        trial = tmp_path / "agents" / "trial.yaml"
        _write(trial, "agent:\n  name: team-trial-0123456789ab-design\n  type: pi\n")
        _write(tmp_path / "agents" / "kept.yaml", "agent:\n  name: kept_e7\n  type: llm\n")

        with caplog.at_level(logging.WARNING, logger="temper_ai.config.importer"):
            assert import_config_tree(tmp_path, store) == 1
        [record] = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert record.getMessage() == (
            f"Skipped config {trial}: 'team-trial-0123456789ab-design' is a team trial's name "
            "(team-trial-...), which only the Team page writes")

    def test_a_stored_trial_config_is_never_replaced_by_a_file(self, store, tmp_path):
        store.put("team-trial-0123456789ab", "workflow",
                  {"workflow": {"name": "team-trial-0123456789ab", "nodes": ["frozen"]}})
        _write(tmp_path / "workflows" / "t.yaml",
               "workflow:\n  name: team-trial-0123456789ab\n  nodes: []\n")

        import_config_tree(tmp_path, store)
        assert store.get("team-trial-0123456789ab", "workflow")["workflow"]["nodes"] == ["frozen"]


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
