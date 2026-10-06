"""arch_land_check's model-free parts on a tiny fixture repo: the host intake, the facts step and the assembly.

System architecture's land check (configs/architecture/, queue #23, 2026-10-04) drafts a land check of a
big temper branch. Its mechanical half needs no model: the intake builds a case folder from a recorded
check, arch_land_facts runs the eight mechanical checks on it, arch_land_assemble turns facts + review +
challenge into draft.json. These tests run the real scripts the way the worker does (ScriptAgent, /bin/sh)
on a two-commit fixture repo, clean and with one planted fault each, and parse every script agent of the
department with sh -n (one apostrophe inside a single-quoted python3 -c program stops the shell).
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from jinja2 import BaseLoader, ChainableUndefined
from jinja2.sandbox import SandboxedEnvironment

from temper_ai.agent.script_agent import (
    BARE_FILTER,
    ENV_FILTER,
    QUOTED_FILTER,
    ScriptAgent,
    _rewrite_interpolations,
    _ValueStash,
)
from temper_ai.config.helpers import substitute_env_vars
from temper_ai.tools.base import ToolResult

ROOT = Path(__file__).resolve().parents[2]
ARCH = ROOT / "configs" / "architecture"
AGENTS = ARCH / "agents"
INTAKE = ARCH / "bin" / "land_check_intake.py"
CHECK_TIME = "2030-01-01T12:00:00-08:00"  # after every file the fixture writes


def served_config(path: Path) -> dict:
    """The agent config as the server hands it out (ConfigStore.get runs the env substitution)."""
    return substitute_env_vars(yaml.safe_load(path.read_text()))["agent"]


SCRIPT_AGENTS = sorted(p for p in AGENTS.glob("*.yaml") if served_config(p).get("type") == "script")


def test_the_department_script_agents_are_all_found():
    names = {p.stem for p in SCRIPT_AGENTS}
    assert {"arch_land_facts", "arch_land_assemble", "arch_land_grade_compare", "arch_land_grade_score"} <= names


@pytest.mark.parametrize("path", SCRIPT_AGENTS, ids=lambda p: p.stem)
def test_every_architecture_script_agent_parses_under_sh(path):
    config = served_config(path)
    stash = _ValueStash()
    env = SandboxedEnvironment(loader=BaseLoader(), undefined=ChainableUndefined)
    env.policies["json.dumps_kwargs"] = {"sort_keys": True, "default": lambda _undefined: None}
    env.filters[QUOTED_FILTER] = stash.quoted
    env.filters[BARE_FILTER] = stash.bare
    env.filters[ENV_FILTER] = stash.name
    script = env.from_string(_rewrite_interpolations(config["script_template"], config["name"])).render()
    done = subprocess.run(["sh", "-n", "-c", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, f"{path.name} does not parse under /bin/sh: {done.stderr.strip()}"


def run_agent(name: str, inputs: dict) -> tuple[str, dict | None, str]:
    """The real agent and the real script, run by /bin/sh as the Bash tool runs it."""
    config = served_config(AGENTS / f"{name}.yaml")
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name = "t", name, name
    ctx.workspace_path = None

    def execute(_tool, args, **_kw):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tempfile.gettempdir(),
               "LAND_CHECK_PY": sys.executable, **args["env"]}
        done = subprocess.run(args["command"], shell=True, capture_output=True, text=True, env=env, timeout=300)
        return ToolResult(success=done.returncode == 0, result=done.stdout, error=done.stderr)

    ctx.tool_executor.execute.side_effect = execute
    result = ScriptAgent(config=config).run(inputs, ctx)
    return result.status.value, result.structured_output, str(result.error or "") + str(result.output or "")


# ---- the fixture: a two-commit branch on a one-commit master, its evidence and a recorded check ---------

def sh(*cmd: str, cwd: Path) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


SWITCH = '''import os

SWITCH_ENV = "FIXTURE_SWITCH"


def enabled():
    return os.environ.get(SWITCH_ENV, "{default}").strip().lower() in ("1", "true", "on", "yes")
'''


def make_repo(repo: Path, switch_default: str) -> dict:
    repo.mkdir()
    sh("git", "init", "-q", "-b", "master", cwd=repo)
    sh("git", "config", "user.name", "t", cwd=repo)
    sh("git", "config", "user.email", "t@localhost", cwd=repo)
    write(repo / "temper_ai" / "__init__.py", "")
    write(repo / "temper_ai" / "fixture" / "__init__.py", SWITCH.format(default=""))
    write(repo / "docs" / "departments.md", "# Departments\n")
    sh("git", "add", "-A", cwd=repo)
    sh("git", "commit", "-q", "-m", "base", cwd=repo)
    base = sh("git", "rev-parse", "HEAD", cwd=repo)
    sh("git", "checkout", "-q", "-b", "feature", cwd=repo)
    write(repo / "temper_ai" / "fixture" / "__init__.py", SWITCH.format(default=switch_default) + "\nVALUE = 2\n")
    write(repo / "configs" / "fixture" / "agents" / "fixture_agent.yaml", "agent:\n  name: fixture_agent\n")
    write(repo / "docs" / "departments.md", "# Departments\n| fixture_agent | the fixture |\n")
    sh("git", "add", "-A", cwd=repo)
    sh("git", "commit", "-q", "-m", "feature: value two, switched off", cwd=repo)
    write(repo / "tests" / "test_fixture.py", "def test_value_is_two():\n    assert True\n")
    sh("git", "add", "-A", cwd=repo)
    sh("git", "commit", "-q", "-m", "feature: its test", cwd=repo)
    head = sh("git", "rev-parse", "HEAD", cwd=repo)
    return {"base": base, "head": head, "tree": sh("git", "rev-parse", "HEAD^{tree}", cwd=repo),
            "patch_id": sh("sh", "-c", f"git diff {base} {head} | git patch-id --stable", cwd=repo).split()[0]}


def make_case(tmp: Path, switch_default: str = "", red_green: dict | None = None) -> dict:
    repo = tmp / "repo"
    ids = make_repo(repo, switch_default)
    proofs = tmp / "proofs"
    result = {"tested_tree": {"commit": ids["head"], "tree": ids["tree"], "clean": True}, "passed": True,
              "worker_image": {"image": "sha256:fixture"}, "pi_version": "0.0.1",
              "checklist": [{"item": "the value is two", "tests": {"tests/test_fixture.py::test_value_is_two":
                                                                  {"tests-sqlite": "passed"}}}]}
    if red_green:  # a red-green proof, recorded the way C7 recorded it (suite -> outcome)
        result["checklist"][0]["fail_before_pass_after"] = {"tests/test_fixture.py::test_value_is_two": red_green}
    write(proofs / "FIX" / "result.json", json.dumps(result))
    digest = hashlib.sha256((proofs / "FIX" / "result.json").read_bytes()).hexdigest()
    check = {"schema_version": 1, "written": CHECK_TIME, "land": True,
             "decision": "Land: the fixture branch is what its evidence tested, and its switch stays off by default.",
             "findings": [{"id": "C1", "severity": "pass", "result": "pass", "what": "the value is two"}],
             "landing_conditions": ["Land exactly the checked commits."],
             "bindings_for_later_tasks": ["#99: keep the value at two when the switch goes on"],
             "residual_risks": []}
    write(proofs / "FIX" / "architecture-check.json", json.dumps(check))
    mechanical = {"head": ids["head"], "tree": ids["tree"], "base": ids["base"], "master_at_check": ids["base"],
                  "commit_count": 2, "files": 4, "combined_patch_id": ids["patch_id"], "clean": True,
                  "master_overlap": []}
    cases = {"proofs_root": str(proofs),
             "switch": {"env": "FIXTURE_SWITCH", "module": "temper_ai/fixture/__init__.py",
                        "probe": "temper_ai.fixture:enabled", "on_values": ["1", "true", "on", "yes"]},
             "never_copy": ["architecture-check", "landed.json", "rebase-question"],
             "real": {"FIX": {"check": "FIX/architecture-check.json", "branch": "feature", "head": ids["head"],
                              "master_at_check": ids["base"], "what": "a fixture branch",
                              "inputs": [{"path": "FIX/result.json", "digest": digest},
                                         {"path": "FIX/architecture-check.json"}],
                              "evidence": ["FIX/result.json"],
                              "bindings_from": {"kind": "checklist", "file": "FIX/result.json", "list": "checklist",
                                                "claim": "item", "tests": "tests"},
                              "expected_mechanical": mechanical,
                              "asks": {"true": [], "false": [], "merge": {}},
                              "invented_must_fix": {"place": "tests/test_fixture.py", "what": "deleted", "fix": "restore"}}},
             "seeded": {}, "stretch": {}}
    write(tmp / "cases.json", json.dumps(cases))
    ws = tmp / "ws"
    done = subprocess.run([sys.executable, str(INTAKE), "--case", "FIX", "--workspaces", str(ws), "--repo", str(repo),
                           "--cases", str(tmp / "cases.json")], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    leak = subprocess.run([sys.executable, str(INTAKE), "--leak-check", "--workspaces", str(ws), "--repo", str(repo),
                           "--cases", str(tmp / "cases.json")], capture_output=True, text=True, timeout=120)
    return {"ids": ids, "case": ws / "land-check" / "FIX", "grade": ws / "land-check-grade" / "FIX",
            "leak": leak, "mechanical": mechanical}


@pytest.fixture
def case(tmp_path):
    return make_case(tmp_path)


def test_the_intake_copies_inputs_but_never_an_answer(case):
    folder = case["case"]
    assert (folder / "proof" / "FIX" / "result.json").is_file()
    assert not list(folder.rglob("architecture-check*")), "the recorded check reached the case folder"
    assert not list(folder.rglob("expected.json"))
    assert (case["grade"] / "expected.json").is_file()
    req = json.loads((folder / "request.md").read_text().split("```json", 1)[1].split("```", 1)[0])
    assert req["head"] == case["ids"]["head"]
    assert [d["path"] for d in req["dropped_inputs"]] == ["proof/FIX/architecture-check.json"]
    assert req["bindings"][0]["tests"] == ["tests/test_fixture.py::test_value_is_two"]
    assert (folder / "rubric.md").is_file() and (folder / "scratch").is_dir()
    refs = sh("git", "for-each-ref", "--format=%(refname)", cwd=folder / "code").split()
    assert sorted(refs) == ["refs/heads/feature", "refs/heads/master"]
    assert case["leak"].returncode == 0, case["leak"].stdout


def test_the_facts_step_passes_a_clean_branch_and_states_it_exactly(case):
    status, out, said = run_agent("arch_land_facts", {"case_dir": str(case["case"])})
    assert status == "completed", said
    facts = json.loads((case["case"] / "scratch" / "facts.json").read_text())
    assert out["all_passed"] and facts["failed_checks"] == [], json.dumps(facts["checks"], indent=1)
    assert set(facts["checks"]) == {"commit_identity", "clean_worktree", "master_overlap", "input_digests",
                                    "evidence_binding", "binding_tests", "switch_off", "department_rows"}
    branch, want = facts["branch"], case["mechanical"]
    for key in ("head", "tree", "base", "master_at_check", "commit_count", "combined_patch_id"):
        assert branch[key] == want[key], key
    assert branch["file_count"] == 4
    assert (case["case"] / "scratch" / "diff.patch").read_text().startswith("diff --git ")


def fail_of(case_dir: Path) -> list[str]:
    status, out, said = run_agent("arch_land_facts", {"case_dir": str(case_dir)})
    assert status == "completed", said
    return out["failed_checks"]


def test_a_dirty_tree_fails_only_clean_worktree(case):
    with open(case["case"] / "code" / "temper_ai" / "fixture" / "__init__.py", "a") as f:
        f.write("VALUE = 3\n")
    assert fail_of(case["case"]) == ["clean_worktree"]


def test_an_input_changed_after_its_digest_fails_only_input_digests(case):
    path = case["case"] / "proof" / "FIX" / "result.json"
    path.write_text(path.read_text().replace('"pi_version": "0.0.1"', '"pi_version": "0.0.2"'))
    assert fail_of(case["case"]) == ["input_digests"]


def test_a_switch_that_defaults_on_fails_only_switch_off(tmp_path):
    seeded = make_case(tmp_path, switch_default="1")
    assert fail_of(seeded["case"]) == ["switch_off"]


def test_red_runs_of_a_red_green_proof_do_not_count_against_the_head(tmp_path):
    # C7's false block: the named test fails on master by design and passes on the head.
    proved = make_case(tmp_path, red_green={"master-sqlite": "failed", "fix-sqlite": "passed"})
    assert fail_of(proved["case"]) == []
    facts = json.loads((proved["case"] / "scratch" / "facts.json").read_text())
    entry = facts["checks"]["binding_tests"]["bindings"][0]["tests"][0]
    assert "problem" not in entry and "red runs of a red-green proof" in entry["note"]
    assert "master-sqlite" in entry["note"]


def test_a_failed_run_of_the_head_inside_a_red_green_proof_still_fails_binding_tests(tmp_path):
    proved = make_case(tmp_path, red_green={"master-sqlite": "failed", "fix-sqlite": "failed"})
    assert fail_of(proved["case"]) == ["binding_tests"]


def write_review(case_dir: Path, severity: str, challenge_result: str) -> None:
    scratch = case_dir / "scratch"
    finding = {"id": "F1", "severity": severity, "place": "temper_ai/fixture/__init__.py:8",
               "risk": "VALUE is set at import", "why_here": "x", "fix": "y", "owner": "#99", "evidence": "the diff"}
    review = {"schema_version": 1, "land_proposed": severity != "must-fix", "decision": "Review.",
              "core_files_outside_slice": [], "findings": [finding], "verified": [{"what": "switch off", "how": "facts"}],
              "landing_conditions": ["Land exactly the checked commits."],
              "bindings_for_later_tasks": [{"task": "#99", "binding": "keep the value", "why": "x", "source": "proof"}],
              "follow_ups": [], "residual_risks": [], "not_covered": []}
    challenge = {"schema_version": 1, "verdicts": [{"id": "F1", "result": challenge_result, "severity": severity,
                                                    "reason": "r", "evidence": "e"}],
                 "added": [], "plan_review": [], "land_proposed": True, "decision": "Challenge."}
    (scratch / "review.json").write_text(json.dumps(review))
    (scratch / "challenge.json").write_text(json.dumps(challenge))


def assemble(case: dict) -> dict:
    status, out, said = run_agent("arch_land_assemble", {"case_dir": str(case["case"]), "label": "FIX", "run_id": "t1"})
    assert status == "completed", said
    draft = json.loads((case["case"] / "draft.json").read_text())
    assert out["land"] == draft["land"]
    assert (case["case"] / "draft.md").is_file()
    return draft


def test_assembly_lands_a_clean_branch_whose_only_finding_is_a_follow_up(case):
    run_agent("arch_land_facts", {"case_dir": str(case["case"])})
    write_review(case["case"], "follow-up", "stands")
    draft = assemble(case)
    assert draft["schema_version"] == 1 and draft["land"] is True
    assert draft["by"].startswith("arch_land_check draft, run t1")
    assert draft["branch"]["head"] == case["ids"]["head"]
    assert draft["mechanical"]["failed_checks"] == []


def test_assembly_blocks_on_a_must_fix_the_challenge_left_standing(case):
    run_agent("arch_land_facts", {"case_dir": str(case["case"])})
    write_review(case["case"], "must-fix", "stands")
    assert assemble(case)["land"] is False


def test_assembly_lands_when_the_challenge_refutes_the_only_must_fix(case):
    run_agent("arch_land_facts", {"case_dir": str(case["case"])})
    write_review(case["case"], "must-fix", "refuted")
    assert assemble(case)["land"] is True


def test_assembly_blocks_and_names_a_failed_mechanical_check(case):
    with open(case["case"] / "code" / "temper_ai" / "fixture" / "__init__.py", "a") as f:
        f.write("VALUE = 3\n")
    run_agent("arch_land_facts", {"case_dir": str(case["case"])})
    write_review(case["case"], "follow-up", "stands")
    draft = assemble(case)
    assert draft["land"] is False and draft["mechanical"]["failed_checks"] == ["clean_worktree"]
