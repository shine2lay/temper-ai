"""env_for_agent_tool: what an agent's tool process (CLI, Bash, script, git) may see.

Values here are fakes; what is checked is which NAMES reach the process.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from temper_ai.shared import agent_env
from temper_ai.shared.agent_env import env_for_agent_tool

SERVER = {
    "PATH": "/usr/bin", "HOME": "/app", "LANG": "C.UTF-8", "LC_CTYPE": "C.UTF-8", "TZ": "UTC",
    "HTTPS_PROXY": "http://proxy", "TEMPER_RUN_CONTAINER": "temper-run-x",
    "WORKSPACE_DIR": "/ws", "TEMPER_API": "http://server:8420",
    "TEMPER_DATABASE_URL": "postgresql://fake", "DATABASE_URL": "postgresql://fake",
    "TEMPER_SECRET_KEY": "fake", "TEMPER_REDIS_URL": "redis://fake",
    "OPENAI_API_KEY": "fake", "OPENAI_OAUTH_TOKEN": "fake", "ANTHROPIC_API_KEY": "fake",
    "CLAUDE_CODE_OAUTH_TOKEN": "fake-0", "CLAUDE_CODE_OAUTH_TOKEN_2": "fake-2",
    "NOTION_TOKEN": "fake", "SLACK_BOT_TOKEN": "fake", "GITHUB_APP_PRIVATE_KEY": "fake",
    "UNLISTED_SETTING": "x",
}
NEVER = {"TEMPER_DATABASE_URL", "DATABASE_URL", "TEMPER_SECRET_KEY", "TEMPER_REDIS_URL",
         "OPENAI_API_KEY", "OPENAI_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN_2",
         "NOTION_TOKEN", "SLACK_BOT_TOKEN", "GITHUB_APP_PRIVATE_KEY"}

LIST = """
box_env:
  - names: [PATH, HOME, LANG, TZ, HTTPS_PROXY]
    why: basics
    agent_tools: true
  - names: [WORKSPACE_DIR, TEMPER_API]
    why: scripts
    agent_tools: true
  - names: [TEMPER_DATABASE_URL, DATABASE_URL, TEMPER_SECRET_KEY, TEMPER_REDIS_URL, OPENAI_API_KEY,
            OPENAI_OAUTH_TOKEN, ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN, CLAUDE_CODE_OAUTH_TOKEN_2,
            NOTION_TOKEN, UNLISTED_SETTING]
    why: the box's process only
"""


@pytest.fixture
def configs(tmp_path, monkeypatch):
    (tmp_path / "boxes").mkdir()
    (tmp_path / "boxes" / "env.yaml").write_text(LIST)
    monkeypatch.setenv("TEMPER_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("TEMPER_BOX_ENV", raising=False)
    agent_env._cache.clear()
    return tmp_path


def test_leaves_out_db_secret_key_and_every_provider(configs):
    env = env_for_agent_tool(environ=SERVER)
    assert not NEVER & set(env)
    assert "UNLISTED_SETTING" not in env  # listed for the process, not for tools
    assert set(env) == {"PATH", "HOME", "LANG", "LC_CTYPE", "TZ", "HTTPS_PROXY",
                        "TEMPER_RUN_CONTAINER", "WORKSPACE_DIR", "TEMPER_API"}


def test_keeps_the_one_slot_credential_and_explicit_variables(configs):
    env = env_for_agent_tool(environ=SERVER,
                             credential={"CLAUDE_CODE_OAUTH_TOKEN": "fake-2"},
                             extra={"TEMPER_V1": "data", "TEMPER_PYTHON": "/py"})
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "fake-2"
    assert "CLAUDE_CODE_OAUTH_TOKEN_2" not in env
    assert env["TEMPER_V1"] == "data" and env["TEMPER_PYTHON"] == "/py"


def test_never_gives_the_database_url_even_when_listed_for_tools(configs, monkeypatch):
    # The loader refuses this, but even a list that slipped through never hands it out.
    monkeypatch.setattr(agent_env, "_agent_tool_names",
                        lambda _d: frozenset({"TEMPER_DATABASE_URL", "TEMPER_SECRET_KEY"}))
    env = env_for_agent_tool(environ=SERVER)
    assert not {"TEMPER_DATABASE_URL", "TEMPER_SECRET_KEY"} & set(env)


def test_a_broken_list_gives_only_the_base_names(configs, caplog):
    (configs / "boxes" / "env.yaml").write_text("box_env: [\n")
    agent_env._cache.clear()
    env = env_for_agent_tool(environ=SERVER)
    assert set(env) == {"PATH", "HOME", "LANG", "LC_CTYPE", "TZ", "HTTPS_PROXY", "TEMPER_RUN_CONTAINER"}
    assert "base environment" in caplog.text


def test_inherit_falls_back_to_the_old_deny_list(configs):
    env = env_for_agent_tool(environ={**SERVER, "TEMPER_BOX_ENV": "inherit"})
    assert "UNLISTED_SETTING" in env
    assert not NEVER & set(env)


def test_the_list_is_read_again_when_it_changes(configs):
    assert "WORKSPACE_DIR" in env_for_agent_tool(environ=SERVER)
    path = configs / "boxes" / "env.yaml"
    path.write_text(LIST.replace("[WORKSPACE_DIR, TEMPER_API]", "[TEMPER_API]"))
    import os
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 5))
    assert "WORKSPACE_DIR" not in env_for_agent_tool(environ=SERVER)


# --- every spawn site passes the scrubbed environment ----------------------

@pytest.fixture
def server_environ(configs, monkeypatch):
    for name, value in SERVER.items():
        monkeypatch.setenv(name, value)
    return configs


def test_the_bash_tool_s_shell_sees_no_secret(server_environ):
    from temper_ai.tools.bash import Bash

    result = Bash().execute(command="env")
    assert result.success
    names = {line.split("=", 1)[0] for line in str(result.result).splitlines() if "=" in line}
    assert not NEVER & names
    assert "UNLISTED_SETTING" not in names
    assert "WORKSPACE_DIR" in names


def test_a_script_step_gets_its_values_and_no_secret(server_environ):
    from temper_ai.tools.bash import _safe_env

    env = _safe_env({"TEMPER_V1": "x"})
    assert env["TEMPER_V1"] == "x"
    assert not NEVER & set(env)


def test_git_runs_with_the_scrubbed_env(server_environ, monkeypatch, tmp_path):
    from temper_ai.tools import git as git_tool

    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(git_tool.subprocess, "run", fake_run)
    git_tool.Git(workspace=str(tmp_path))._run_git(["git", "status"], "status")
    assert seen.get("env") is not None and not NEVER & set(seen["env"])


def test_open_pull_request_s_git_gets_the_scrubbed_env(server_environ, tmp_path):
    from temper_ai.tools.github_pr import _clean_git_env

    env = _clean_git_env(str(tmp_path))
    assert not NEVER & set(env)
    assert env["HOME"] == str(tmp_path)


def test_pi_s_docker_cli_gets_only_home_lang_and_a_fixed_path(server_environ):
    from temper_ai.pi_agent import box as pi_box

    assert set(pi_box.DOCKER_ENV_KEYS) <= {"HOME", "LANG"}
    src = Path(pi_box.__file__).read_text()
    # every docker call in the Pi box builds its env from DOCKER_ENV_KEYS, never os.environ wholesale
    assert "os.environ.copy()" not in src and "**os.environ" not in src
