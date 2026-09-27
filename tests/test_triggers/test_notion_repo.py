"""notion_work's repo step: the repo table, and one branch per task page.

The branch (epd_task's slug of task_name) is named after the page's whole id.
It once used the first 8 characters, but pages made around the same time
share their first 12, so two tasks landed on one branch and one pull request,
and the second task's run reverted the first one's change.
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
REPO_AGENT = ROOT / "configs" / "agents" / "notion_repo.yaml"

# Two real task pages from the live test, made a minute apart.
PAGE_A = "3e84cb8f-6eaa-81af-8096-e437340bdf80"
PAGE_B = "3e84cb8f-6eaa-81fc-af2c-c504959de72a"


def run_repo(repo, page_id=PAGE_A):
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name = "t", "repo", "notion_repo"
    ctx.workspace_path = None

    def execute(_tool, args, **_kw):
        env = {"PATH": "/usr/bin:/bin", "HOME": tempfile.gettempdir(), **args["env"]}
        done = subprocess.run(args["command"], shell=True, capture_output=True, text=True, env=env, timeout=60)
        return ToolResult(success=done.returncode == 0, result=done.stdout, error=done.stderr)

    ctx.tool_executor.execute.side_effect = execute
    config = substitute_env_vars(yaml.safe_load(REPO_AGENT.read_text()))["agent"]
    result = ScriptAgent(config=config).run({"repo": repo, "page_id": page_id}, ctx)
    return result.status.value, result.structured_output, str(result.error or "") + str(result.output or "")


def test_temper_ai_is_cut_from_master():
    status, out, _ = run_repo("temper-ai")
    assert status == "completed"
    assert out == {"status": "ready", "repo": "shine2lay/temper-ai",
                   "repo_url": "https://github.com/shine2lay/temper-ai.git",
                   "base_branch": "master", "task_name": "notion 3e84cb8f6eaa81af8096e437340bdf80"}


def test_roamee_is_cut_from_staging():
    status, out, _ = run_repo("roamee")
    assert status == "completed"
    assert (out["repo"], out["base_branch"]) == ("shine2lay/roamee", "staging")


def test_two_pages_made_together_get_two_branches():
    _, a, _ = run_repo("temper-ai", PAGE_A)
    _, b, _ = run_repo("temper-ai", PAGE_B)
    assert a["task_name"] != b["task_name"]


def test_the_same_page_keeps_its_branch_with_or_without_dashes():
    _, dashed, _ = run_repo("temper-ai", PAGE_B)
    _, bare, _ = run_repo("temper-ai", PAGE_B.replace("-", "").upper())
    assert dashed["task_name"] == bare["task_name"]


@pytest.mark.parametrize("page_id", ["", None, "3e84cb8f", "3e84cb8f-6eaa-81af-8096-e437340bdf8z",
                                     "3e84cb8f; echo hi"])
def test_a_page_id_that_is_not_a_notion_id_stops_here(page_id):
    status, _, text = run_repo("temper-ai", page_id)
    assert status == "failed"
    assert "is not a Notion page id" in text


@pytest.mark.parametrize("repo", ["rollcall", "", None, "roamee; echo hi"])
def test_a_repository_not_in_the_table_stops_here(repo):
    status, _, text = run_repo(repo)
    assert status == "failed"
    assert "no repository is set up" in text
