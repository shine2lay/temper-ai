"""github_work's repo step: where the work happens, from the signed event only.

Pinned: an issue's work goes on branch temper-issue-N cut from the default
branch; a change asked on temper's own pull request updates that same
branch; someone else's pull request gets its own branch cut from theirs; a
fork's pull request is refused; roamee's work goes into staging and nowhere
else; a private repository is cloned over ssh (its deploy key), a public one
over https; and nothing odd in a value can reach the shell.
"""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.config.helpers import substitute_env_vars
from temper_ai.tools.base import ToolResult

ROOT = Path(__file__).resolve().parents[2]
REPO_AGENT = ROOT / "configs" / "agents" / "github_repo.yaml"
REPO = "shine2lay/temper-ai"


def run_repo(**given):
    inputs = {"repo": REPO, "number": "12", "kind": "issue", "default_branch": "master", "private": "false",
              "head_ref": "", "head_repo": "", "base_ref": ""}
    inputs.update(given)
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name = "t", "repo", "github_repo"
    ctx.workspace_path = None

    def execute(_tool, args, **_kw):
        env = {"PATH": "/usr/bin:/bin", "HOME": tempfile.gettempdir(), **args["env"]}
        done = subprocess.run(args["command"], shell=True, capture_output=True, text=True, env=env, timeout=60)
        return ToolResult(success=done.returncode == 0, result=done.stdout, error=done.stderr)

    ctx.tool_executor.execute.side_effect = execute
    config = substitute_env_vars(yaml.safe_load(REPO_AGENT.read_text()))["agent"]
    result = ScriptAgent(config=config).run(inputs, ctx)
    return result.status.value, result.structured_output, str(result.error or "") + str(result.output or "")


def test_an_issue_is_worked_on_its_own_branch_from_the_default_branch():
    status, out, _ = run_repo()
    assert status == "completed"
    assert out == {"status": "ready", "repo": REPO, "repo_url": f"https://github.com/{REPO}.git",
                   "base_branch": "master", "task_name": "temper issue 12", "number": "12"}


def test_a_private_repository_is_cloned_with_its_deploy_key():
    _, out, _ = run_repo(private="true")
    assert out["repo_url"] == f"git@github.com:{REPO}.git"


def test_roamee_s_work_goes_into_staging():
    _, out, _ = run_repo(repo="shine2lay/roamee", default_branch="master")
    assert (out["base_branch"], out["task_name"]) == ("staging", "temper issue 12")


def test_a_change_asked_on_temper_s_own_pull_request_updates_its_branch():
    status, out, _ = run_repo(kind="pull", number="13", head_ref="temper-issue-12", head_repo=REPO,
                              base_ref="master")
    assert status == "completed"
    assert (out["task_name"], out["base_branch"]) == ("temper issue 12", "master")


def test_someone_else_s_pull_request_gets_a_branch_cut_from_theirs():
    _, out, _ = run_repo(kind="pull", number="7", head_ref="add-page", head_repo=REPO, base_ref="master")
    assert (out["task_name"], out["base_branch"]) == ("temper pr 7", "add-page")


def test_a_fork_s_pull_request_is_refused():
    status, _, text = run_repo(kind="pull", number="7", head_ref="add-page", head_repo="stranger/temper-ai",
                               base_ref="master")
    assert status == "failed"
    assert "in another repository (stranger/temper-ai)" in text


def test_a_roamee_pull_request_not_into_staging_is_refused():
    status, _, text = run_repo(repo="shine2lay/roamee", kind="pull", number="7", head_ref="feature",
                               head_repo="shine2lay/roamee", base_ref="staging")
    # someone else's PR: the work is cut from (and goes into) their branch, which is not staging
    assert status == "failed"
    assert "go into staging" in text


def test_temper_s_own_roamee_pull_request_into_staging_is_fine():
    status, out, _ = run_repo(repo="shine2lay/roamee", kind="pull", number="8", head_ref="temper-issue-3",
                              head_repo="shine2lay/roamee", base_ref="staging")
    assert status == "completed"
    assert (out["task_name"], out["base_branch"]) == ("temper issue 3", "staging")


def test_inputs_not_given_are_not_the_word_none():
    status, out, _ = run_repo(default_branch=None, private=None, head_ref=None, head_repo=None, base_ref=None)
    assert status == "completed"
    assert (out["base_branch"], out["repo_url"]) == ("", f"https://github.com/{REPO}.git")


@pytest.mark.parametrize("repo", ["", None, "temper-ai", "a/b/c", "../x", "shine2lay/temper-ai; echo hi",
                                  "shine2lay/$(id)"])
def test_not_a_repository(repo):
    status, _, text = run_repo(repo=repo)
    assert status == "failed"
    assert "is not an owner/name repository" in text


@pytest.mark.parametrize("number", ["", None, "12a", "-1", "12; echo hi"])
def test_not_a_number(number):
    status, _, text = run_repo(number=number)
    assert status == "failed"
    assert "is not an issue or pull request number" in text


@pytest.mark.parametrize("head_ref", ["", "-x", "a..b", "a b", "$(id)"])
def test_a_pull_request_branch_that_is_not_a_branch_name(head_ref):
    status, _, _ = run_repo(kind="pull", number="7", head_ref=head_ref, head_repo=REPO, base_ref="master")
    assert status == "failed"
