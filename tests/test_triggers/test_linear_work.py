"""linear_work, as shipped: which Linear events start it, and the repository table it works from.

The rules are the ones in configs/triggers, read from disk, so a rule edited into something that no
longer fires (or fires on temper's own comment) fails here. The repo step is the real script agent,
run by /bin/sh as the Bash tool runs it: it is the one step that turns the model's words into a
clone URL, so a repository it made up has to stop there.
"""

import re
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.config.helpers import substitute_env_vars
from temper_ai.tools.base import ToolResult
from temper_ai.triggers import linear
from temper_ai.triggers.rules import parse_trigger, render_inputs

ROOT = Path(__file__).resolve().parents[2]


def _rule(name: str):
    path = ROOT / "configs" / "triggers" / f"{name}.yaml"
    return parse_trigger(yaml.safe_load(path.read_text()), str(path))


def _label_put_on(labels=("temper",), before=()):
    return {
        "type": "Issue",
        "action": "update",
        "actor": {"id": "person-1", "type": "user"},
        "data": {"id": "iss-1", "identifier": "ROA-5",
                 "labels": [{"id": f"id-{n}", "name": n} for n in labels]},
        "updatedFrom": {"labelIds": [f"id-{n}" for n in before]},
    }


def _reply(labels=("temper",), actor_type="user"):
    """A person's comment, as the handler has it after enrich: the issue's labels at data.issue."""
    return {
        "type": "Comment",
        "action": "create",
        "actor": {"id": "person-1", "type": actor_type},
        "data": {"id": "com-1", "body": "yes, the fees column", "issueId": "iss-1", "userId": "person-1",
                 "issue": {"id": "iss-1", "identifier": "ROA-5",
                           "labels": [{"id": f"id-{n}", "name": n} for n in labels]}},
    }


class TestTheLabel:
    def test_putting_the_label_on_starts_the_work(self):
        rule = _rule("linear_work")
        assert rule.workflow == "linear_work"
        assert linear.matches(rule.on, _label_put_on(before=()))
        assert render_inputs(rule, _label_put_on()) == {"issue_id": "iss-1", "identifier": "ROA-5"}

    def test_a_later_edit_of_a_labelled_issue_does_not_start_it_again(self):
        assert not linear.matches(_rule("linear_work").on, _label_put_on(before=("temper",)))

    def test_another_label_does_not_start_it(self):
        assert not linear.matches(_rule("linear_work").on, _label_put_on(labels=("bug",)))


class TestAReply:
    def test_a_person_s_comment_on_a_temper_issue_continues_the_work(self):
        rule = _rule("linear_work_comment")
        assert rule.workflow == "linear_work"
        assert linear.matches(rule.on, _reply())
        assert render_inputs(rule, _reply()) == {"issue_id": "iss-1", "identifier": "ROA-5", "comment_id": "com-1"}

    def test_a_comment_on_an_issue_without_the_label_is_left_alone(self):
        assert not linear.matches(_rule("linear_work_comment").on, _reply(labels=("bug",)))

    def test_only_people_s_comments(self):
        assert not linear.matches(_rule("linear_work_comment").on, _reply(actor_type="integration"))

    def test_temper_s_own_comments_are_ignored(self):
        # temper's app user is a "user" to Linear too; ignore_self (on unless a rule turns it off) is
        # what keeps its own reply from starting another run.
        rule = _rule("linear_work_comment")
        assert rule.ignore_self
        own = _reply()
        own["actor"]["id"] = own["data"]["userId"] = "temper-app"
        assert linear.is_own(own, "temper-app")

    def test_the_first_reply_only_rule_is_gone(self):
        assert not (ROOT / "configs" / "triggers" / "linear_reply.yaml").exists()


class TestTriageStatesTheRealBaseBranches:
    """Triage answers "which branch do you work from?" out of its prompt: it must match the table.

    Without the facts it guessed ("main", on a branch named like Linear's), and the table in
    linear_repo is what the build really uses. A drift between the two is a wrong answer.
    """

    def test_each_repo_base_in_the_table_is_the_one_triage_states(self):
        script = yaml.safe_load((ROOT / "configs" / "agents" / "linear_repo.yaml").read_text())[
            "agent"]["script_template"]
        table = dict(re.findall(r"FULL=shine2lay/([\w-]+);[^\n]*BASE=(\w+)", script))
        assert table == {"roamee": "staging", "temper-ai": "master"}
        prompt = yaml.safe_load((ROOT / "configs" / "agents" / "linear_triage.yaml").read_text())[
            "agent"]["system_prompt"]
        stated = " ".join(prompt.split())
        for repo, base in table.items():
            assert re.search(rf"{repo}: (work is )?cut from `{base}`", stated), repo


# ---- the workflow -------------------------------------------------------------------------------

WORKFLOW = ROOT / "configs" / "workflows" / "linear_work.yaml"
GO = {"source": "triage.structured.decision", "operator": "equals", "value": "go"}


class TestOnlyGoGoesPastTriage:
    """An ask, an answer or a none from triage ends the run there.

    The engine skips a node for its own condition only: a node whose dependency was skipped still
    runs. So each step after triage carries the go condition itself. Without it on the build, every
    question triage asked started the build with no repository and marked the run failed.
    """

    @pytest.mark.parametrize("step", ["repo", "build", "report"])
    def test_each_step_after_triage_runs_only_on_go(self, step):
        nodes = {n["name"]: n for n in yaml.safe_load(WORKFLOW.read_text())["workflow"]["nodes"]}
        assert nodes[step].get("condition") == GO


# ---- the repo step ------------------------------------------------------------------------------

REPO_AGENT = ROOT / "configs" / "agents" / "linear_repo.yaml"


def run_repo(repo, identifier="ROA-5"):
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name = "t", "repo", "linear_repo"
    ctx.workspace_path = None

    def execute(_tool, args, **_kw):
        env = {"PATH": "/usr/bin:/bin", "HOME": tempfile.gettempdir(), **args["env"]}
        done = subprocess.run(args["command"], shell=True, capture_output=True, text=True, env=env, timeout=60)
        return ToolResult(success=done.returncode == 0, result=done.stdout, error=done.stderr)

    ctx.tool_executor.execute.side_effect = execute
    config = substitute_env_vars(yaml.safe_load(REPO_AGENT.read_text()))["agent"]
    result = ScriptAgent(config=config).run({"repo": repo, "identifier": identifier}, ctx)
    return result.status.value, result.structured_output, str(result.error or "") + str(result.output or "")


class TestTheRepoTable:
    @pytest.mark.parametrize("repo", ["roamee", "shine2lay/roamee"])
    def test_roamee_is_cut_from_staging_over_its_deploy_key(self, repo):
        status, out, _ = run_repo(repo)
        assert status == "completed"
        assert out == {"status": "ready", "repo": "shine2lay/roamee",
                       "repo_url": "git@github.com:shine2lay/roamee.git",
                       "base_branch": "staging", "task_name": "linear ROA-5"}

    def test_temper_ai_is_cut_from_master_over_https(self):
        status, out, _ = run_repo("temper-ai")
        assert status == "completed"
        assert out["repo_url"] == "https://github.com/shine2lay/temper-ai.git"
        assert out["base_branch"] == "master"

    @pytest.mark.parametrize("repo", ["rollcall", "shine2lay/other", "", None, "roamee; rm -rf /"])
    def test_a_repository_not_in_the_table_stops_here(self, repo):
        status, _, text = run_repo(repo)
        assert status == "failed"
        assert "no repository is set up" in text

    @pytest.mark.parametrize("identifier", ["", None, "ROA 5", "ROA-5;x", "../ROA-5"])
    def test_an_identifier_unlike_roa_5_stops_here(self, identifier):
        status, _, text = run_repo("roamee", identifier)
        assert status == "failed"
        assert "is not like ROA-5" in text
