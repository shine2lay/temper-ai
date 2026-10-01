"""The roamee_answer workflow and its agent, read as they are on disk.

Pinned: it is two steps (the shared read-only copy of roamee, then the
answer); it copies roamee and nothing else; the answerer has exactly the
tools it is meant to have, all of them read-only; it must name its sources
and must refuse to print a secret; and `/temper ask` sends roamee's
questions to it while leaving the other two repositories where they were.

Nothing here starts a run, reaches a container or asks a model.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from temper_ai.integrations.notify.loop import QUIET_WORKFLOWS
from temper_ai.integrations.slack.answer import ANSWER_WORKFLOW, ROAMEE_WORKFLOW
from temper_ai.tools import TOOL_CLASSES

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "configs" / "workflows" / "roamee_answer.yaml"
AGENT = ROOT / "configs" / "agents" / "roamee_answer.yaml"
REPO_ANSWER = ROOT / "configs" / "workflows" / "repo_answer.yaml"
ACCESS = ROOT / "configs" / "slack" / "access.yaml"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def workflow() -> dict:
    raw = load(WORKFLOW)
    return raw.get("workflow", raw)


def agent() -> dict:
    raw = load(AGENT)
    return raw.get("agent", raw)


def nodes() -> dict[str, dict]:
    return {n["name"]: n for n in workflow()["nodes"]}


def said() -> str:
    """What the answerer is told, on one line: a sentence that wraps in the
    file still reads as one sentence here."""
    return " ".join(agent()["system_prompt"].split())


class TestTheWorkflow:
    def test_it_is_the_two_steps_it_says_it_is(self):
        found = workflow()
        assert found["name"] == ROAMEE_WORKFLOW
        assert [n["name"] for n in found["nodes"]] == ["code", "answer"]
        assert found["nodes"][1]["depends_on"] == ["code"]
        assert found["outputs"]["answer"] == "answer.output"

    def test_it_takes_a_question_and_a_thread_and_nothing_else(self):
        found = workflow()
        assert set(found["inputs"]) == {"question", "conversation"}
        assert found["inputs"]["question"]["required"] is True
        assert found["inputs"]["conversation"].get("required", False) is False

    def test_it_copies_roamee_and_no_other_repository(self):
        code = nodes()["code"]
        assert code["agent"] == "repo_copies"
        assert code["input_map"]["only"] == "roamee"
        answer = nodes()["answer"]
        assert answer["agent"] == "roamee_answer"
        # The answerer reads the folder the copies step hands it, so Read,
        # Grep and Glob cannot wander into another repository's copy.
        assert answer["input_map"]["workspace_path"] == "code.structured.workspace"

    def test_the_answer_node_is_the_one_slack_reads(self):
        from temper_ai.integrations.slack.answer import ANSWER_NODE

        assert ANSWER_NODE in nodes()

    def test_it_posts_no_notices_of_its_own(self):
        assert ROAMEE_WORKFLOW in QUIET_WORKFLOWS


class TestTheAnswerer:
    def test_every_tool_it_has_is_one_that_only_reads(self):
        names = [t if isinstance(t, str) else t["name"] for t in agent()["tools"]]
        assert names[:6] == ["Read", "Grep", "Glob", "RoameeStack", "RoameeData", "RoameeWork"]
        for name in names:
            tool = TOOL_CLASSES.get(name)
            if tool is None:          # Notion's come from its MCP server
                assert name.startswith("Notion")
                continue
            assert tool.modifies_state is False, f"{name} can change something"

    def test_it_has_no_way_to_run_a_command_or_write_a_file(self):
        names = {t if isinstance(t, str) else t["name"] for t in agent()["tools"]}
        assert not (names & {"Bash", "Write", "Edit", "MultiEdit", "Shell", "Docker", "Python",
                             "GitHubComment", "GitHubReview", "LinearUpdate", "Delegate"})

    def test_it_costs_what_an_answer_costs(self):
        found = agent()
        assert found["model"] == load(REPO_ANSWER.parent.parent / "agents" / "repo_answer.yaml")["agent"]["model"]
        assert found["provider_config"]["effort"] == "medium"
        assert found["max_iterations"] <= 20
        assert found["total_timeout"] <= 420

    def test_it_must_say_where_every_fact_came_from(self):
        prompt = said()
        assert "Read:" in prompt
        assert "roamee staging <commit>" in prompt

    def test_it_must_never_print_a_secret_and_must_admit_what_it_cannot_find(self):
        prompt = said().lower()
        assert "never print a key" in prompt
        assert "connection string" in prompt
        assert "i couldn't find that" in prompt
        assert "never guess" in prompt

    def test_it_knows_it_is_roamees_and_nobody_elses(self):
        prompt = said().lower()
        assert "rollcall" in prompt and "temper-ai" in prompt
        assert "only answer questions about roamee" in prompt


class TestTheDoorInSlack:
    def test_the_other_two_repositories_are_left_where_they_were(self):
        found = load(REPO_ANSWER)
        found = found.get("workflow", found)
        assert found["name"] == ANSWER_WORKFLOW
        assert [n["name"] for n in found["nodes"]] == ["repos", "answer"]
        assert "roamee" not in str(found.get("nodes")[0].get("input_map", {}))

    def test_the_roamee_role_may_use_it_without_a_click(self):
        roles = load(ACCESS)["access"]["roles"]
        assert ROAMEE_WORKFLOW in roles["roamee"]["workflows"]
        assert ROAMEE_WORKFLOW in roles["roamee"]["auto"]
        assert roles["roamee"]["repos"] == ["roamee"]
        assert ROAMEE_WORKFLOW in roles["readonly"]["workflows"]
