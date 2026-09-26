"""The CLI's config loading goes through the same loader as server and worker.

Both `_load_configs` (behind `temper run`) and `_cmd_validate` used to carry
their own copy of the load loop, with a per-file `logger.debug` that the CLI
never shows (its default level is WARNING). A broken workflow YAML therefore
produced a bare "not found" from `temper validate` with no mention of the
file. These pin the delegation and the visibility.
"""

import logging
from types import SimpleNamespace

import pytest

from temper_ai.cli.main import _cmd_validate, _load_configs
from temper_ai.config import ConfigStore

IMPORTER_LOGGER = "temper_ai.config.importer"


def _write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


class TestLoadConfigs:
    def test_loads_configs_from_dir(self, tmp_path):
        _write(tmp_path / "agents" / "a.yaml", "agent:\n  name: cli_loaded\n  type: llm\n")

        _load_configs(str(tmp_path))

        assert ConfigStore().get("cli_loaded", "agent")["agent"]["type"] == "llm"

    def test_missing_dir_is_a_noop(self, tmp_path):
        _load_configs(str(tmp_path / "does_not_exist"))  # must not raise

    def test_broken_file_is_visible_and_others_still_load(self, tmp_path, caplog):
        good = tmp_path / "agents" / "good.yaml"
        broken = tmp_path / "agents" / "broken.yaml"
        _write(good, "agent:\n  name: cli_good\n  type: llm\n")
        _write(broken, "agent:\n  name: [unclosed\n")

        with caplog.at_level(logging.WARNING, logger=IMPORTER_LOGGER):
            _load_configs(str(tmp_path))

        assert ConfigStore().get("cli_good", "agent")["agent"]["name"] == "cli_good"
        messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(str(broken) in m for m in messages)


class TestValidateSurfacesYamlErrors:
    def test_broken_workflow_yaml_names_the_file(self, tmp_path, caplog, capsys):
        """`temper validate` must say *which file* is broken and *why*, not just 'not found'."""
        broken = tmp_path / "workflows" / "my_wf.yaml"
        _write(broken, "workflow:\n  name: my_wf\n  nodes: [unclosed\n")

        args = SimpleNamespace(workflow="my_wf", config_dir=str(tmp_path), input=[])

        with caplog.at_level(logging.WARNING, logger=IMPORTER_LOGGER):
            with pytest.raises(SystemExit) as exc_info:
                _cmd_validate(args)

        assert exc_info.value.code == 1
        # The actionable line: path plus the parse error.
        messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(str(broken) in m and "YAML parsing failed" in m for m in messages)
        assert "Validation failed" in capsys.readouterr().err

    def test_valid_workflow_prints_valid_and_nodes(self, tmp_path, capsys, monkeypatch):
        _write(
            tmp_path / "agents" / "echo.yaml",
            "agent:\n  name: val_echo\n  type: script\n  script: echo '{}'\n",
        )
        _write(
            tmp_path / "workflows" / "val_wf.yaml",
            "workflow:\n"
            "  name: val_wf\n"
            "  nodes:\n"
            "    - name: first\n"
            "      type: agent\n"
            "      agent: val_echo\n"
            "    - name: second\n"
            "      type: agent\n"
            "      agent: val_echo\n"
            "      depends_on: [first]\n",
        )
        monkeypatch.setattr("temper_ai.server._init_llm_providers", lambda: {})

        _cmd_validate(SimpleNamespace(workflow="val_wf", config_dir=str(tmp_path), input=[]))

        out = capsys.readouterr().out
        assert "Workflow 'val_wf' is valid" in out
        assert "Nodes: 2" in out
        assert out.index("first (agent)") < out.index("second (agent)")
