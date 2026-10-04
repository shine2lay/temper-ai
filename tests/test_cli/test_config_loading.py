"""`temper validate` loads configs through the same loader as server and worker.

It used to carry its own copy of the load loop, with a per-file `logger.debug`
that the CLI never shows (its default level is WARNING). A broken workflow YAML
therefore produced a bare "not found" from `temper validate` with no mention of
the file. This pins the visibility.
"""

import logging
from types import SimpleNamespace

import pytest

from temper_ai.cli.main import _cmd_validate

IMPORTER_LOGGER = "temper_ai.config.importer"


def _write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


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
