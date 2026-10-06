"""The box's allow-list (configs/boxes/env.yaml): what loads, and what it refuses."""

from __future__ import annotations

from pathlib import Path

import pytest

from temper_ai.cli.check import check
from temper_ai.integrations.github.secret import SERVER_ONLY
from temper_ai.shared.box_env import (
    BoxEnvError,
    box_env_mode,
    check_box_env,
    load_box_env,
    looks_secret,
)

REPO_CONFIGS = Path(__file__).resolve().parents[2] / "configs"


def _write(root: Path, text: str, local: str | None = None) -> Path:
    boxes = root / "boxes"
    boxes.mkdir(parents=True, exist_ok=True)
    (boxes / "env.yaml").write_text(text)
    if local is not None:
        (boxes / "local").mkdir(exist_ok=True)
        (boxes / "local" / "env.yaml").write_text(local)
    return root


BASIC = """
box_env:
  - names: [PATH, HOME]
    why: every process
    agent_tools: true
  - names: [TEMPER_DATABASE_URL]
    why: the runner records the run
"""


def test_tracked_and_local_lists_load_together(tmp_path):
    _write(tmp_path, BASIC, local="box_env:\n  - names: [PENPOT_URL]\n    why: design steps\n")
    env = load_box_env(tmp_path)
    assert env.names == {"PATH", "HOME", "TEMPER_DATABASE_URL", "PENPOT_URL"}
    assert env.agent_tools == {"PATH", "HOME"}
    assert len(env.files) == 2


@pytest.mark.parametrize("name", sorted(SERVER_ONLY))
def test_the_github_app_s_keys_can_never_be_listed(tmp_path, name):
    _write(tmp_path, BASIC, local=f"box_env:\n  - names: [{name}]\n    why: tempting\n")
    with pytest.raises(BoxEnvError, match=f"{name} stays in the server"):
        load_box_env(tmp_path)


@pytest.mark.parametrize("name", ["TEMPER_PI_AGENT", "TEMPER_PI_BOX_CONFIG"])
@pytest.mark.parametrize("where", ["tracked", "local"])
def test_the_pi_switch_and_box_config_can_never_be_listed(tmp_path, name, where):
    """M4 SW-42: Pi steps never run in a run box, so neither file may list Pi's own settings."""
    group = f"box_env:\n  - names: [{name}]\n    why: tempting\n"
    if where == "tracked":
        _write(tmp_path, group)
    else:
        _write(tmp_path, BASIC, local=group)
    with pytest.raises(BoxEnvError, match=f"{name} is Pi's own setting and can never be listed"):
        load_box_env(tmp_path)


@pytest.mark.parametrize("name", ["TEMPER_DATABASE_URL", "TEMPER_SECRET_KEY", "SLACK_BOT_TOKEN",
                                  "PENPOT_AGENT_PASSWORD", "OPENAI_API_KEY", "LINEAR_CLIENT_SECRET"])
def test_a_secret_is_never_for_agent_tools(tmp_path, name):
    _write(tmp_path, f"box_env:\n  - names: [{name}]\n    why: x\n    agent_tools: true\n")
    with pytest.raises(BoxEnvError, match="holds a secret"):
        load_box_env(tmp_path)


@pytest.mark.parametrize("text, said", [
    ("box_env:\n  - names: [PATH]\n", "why is required"),
    ("box_env:\n  - names: []\n    why: x\n", "non-empty list"),
    ("box_env:\n  - names: [PATH]\n    why: x\n    tools: true\n", "unknown key"),
    ("box_env:\n  - names: [\"NOT A NAME\"]\n    why: x\n", "is not a variable name"),
    ("boxes:\n  - names: [PATH]\n", "one key, box_env"),
    ("box_env:\n  - names: [PATH]\n    why: x\n  - names: [PATH]\n    why: y\n", "listed again"),
    ("box_env: [\n", "cannot be read"),
])
def test_a_malformed_list_says_what_is_wrong(tmp_path, text, said):
    _write(tmp_path, text)
    with pytest.raises(BoxEnvError, match=said):
        load_box_env(tmp_path)


def test_a_name_listed_in_both_files_is_an_error(tmp_path):
    _write(tmp_path, BASIC, local="box_env:\n  - names: [PATH]\n    why: again\n")
    with pytest.raises(BoxEnvError, match="PATH is listed again"):
        load_box_env(tmp_path)


def test_the_tracked_list_must_exist(tmp_path):
    (tmp_path / "boxes" / "local").mkdir(parents=True)
    (tmp_path / "boxes" / "local" / "env.yaml").write_text("box_env: []\n")
    with pytest.raises(BoxEnvError, match="missing"):
        load_box_env(tmp_path)


def test_the_switch_is_list_unless_it_says_inherit():
    assert box_env_mode({}) == "list"
    assert box_env_mode({"TEMPER_BOX_ENV": "list"}) == "list"
    assert box_env_mode({"TEMPER_BOX_ENV": " Inherit "}) == "inherit"
    assert box_env_mode({"TEMPER_BOX_ENV": "all"}) == "list"


def test_looks_secret_by_name():
    for name in ("TEMPER_DATABASE_URL", "TEMPER_SECRET_KEY", "X_TOKEN", "Y_PASSWORD", "Z_API_KEY"):
        assert looks_secret(name)
    for name in ("PATH", "WORKSPACE_DIR", "TEMPER_API", "PENPOT_URL"):
        assert not looks_secret(name)


def test_the_committed_list_loads_and_drops_what_only_the_server_reads():
    env = load_box_env(REPO_CONFIGS)
    for dropped in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "TELEGRAM_BOT_TOKEN",
                    "GITHUB_APP_WEBHOOK_SECRET", "LINEAR_WEBHOOK_SECRET", "NOTION_WEBHOOK_SECRET",
                    "TEMPER_SLACK_TEST_TOKEN", "INTERNAL_API_TOKEN", "TEMPER_API_TOKENS_FILE",
                    "TEMPER_SPAWNER", "TEMPER_EXECUTION_MODE",
                    # M4 SW-42: Pi steps never run in a run box
                    "TEMPER_PI_AGENT", "TEMPER_PI_BOX_CONFIG"):
        assert not env.allows(dropped), dropped
    assert {"PATH", "HOME", "WORKSPACE_DIR", "TEMPER_API"} <= env.agent_tools
    assert not {"TEMPER_DATABASE_URL", "TEMPER_SECRET_KEY"} & env.agent_tools


def test_temper_check_names_a_broken_list(tmp_path, capsys):
    _write(tmp_path, "box_env:\n  - names: [GITHUB_APP_PRIVATE_KEY]\n    why: tempting\n")
    files, problems = check_box_env(tmp_path)
    assert files and problems and "can never be listed" in problems[0]
    assert check(tmp_path) == 1
    assert "problem(s) in the box allow-list" in capsys.readouterr().out


def test_temper_check_passes_a_good_list_and_a_folder_without_one(tmp_path, capsys):
    assert check_box_env(tmp_path) == ([], [])
    _write(tmp_path, BASIC)
    assert check(tmp_path) == 0
    assert "the box allow-list loads" in capsys.readouterr().out
