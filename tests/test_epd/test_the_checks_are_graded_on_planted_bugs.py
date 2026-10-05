"""epd_qa_grade: the build's two checks graded on bugs planted where the answer is known.

QA's seeded-defect test plants one known bug in each copy of a past change, runs the build's checks
on each copy (epd_qa_case: task_test, the repository's own CI, and task_verify, the browser check),
and scores what they caught (configs/epd/bin/qa_grade_score.py). A grade nobody can trust is worse
than none, so the scorer is held to its rules here on a fictional corner-shop app:

- a planted bug that task_test failed on is caught; a pass is a miss;
- task_verify catches a bug only when it failed AND what it saw names the bug's symptom: failing
  for another reason, or naming the symptom in a clause it marked met, is still a miss;
- any fail on a control is a false alarm;
- a skipped verdict or a check that never ran is a harness fault, listed apart and in no rate;
- two rounds side by side show where they disagree, down to a CI check that flipped (flaky).

The case's own steps (epd_qa_prepare, epd_qa_finish) run under /bin/sh on a git bundle made here,
as the script agent runs them, and the workflows are checked to fit together with the live agents.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import types
from pathlib import Path

import pytest
import yaml
from jinja2 import BaseLoader, ChainableUndefined
from jinja2.sandbox import SandboxedEnvironment

from temper_ai.agent.script_agent import (
    BARE_FILTER,
    ENV_FILTER,
    QUOTED_FILTER,
    _rewrite_interpolations,
    _ValueStash,
)
from temper_ai.config.helpers import substitute_env_vars

ROOT = Path(__file__).resolve().parents[2]
EPD = ROOT / "configs" / "epd"
SCORER = EPD / "bin" / "qa_grade_score.py"
CASE_WORKFLOW = EPD / "workflows" / "epd_qa_case.yaml"
GRADE_WORKFLOW = EPD / "workflows" / "epd_qa_grade.yaml"


def load(path: Path, name: str) -> types.ModuleType:
    """A helper script loaded as a module, without leaving bytecode next to it."""
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


score = load(SCORER, "qa_grade_score_under_test")


def served(path: Path) -> dict:
    """The config as the server hands it out (ConfigStore.get runs the env substitution)."""
    return substitute_env_vars(yaml.safe_load(path.read_text()))


def agent_config(name: str) -> dict:
    return served(EPD / "agents" / f"{name}.yaml")["agent"]


def run_step(name: str, cwd: Path, **values) -> tuple[int, dict | None, str]:
    """A script step rendered the way the script agent renders it, then run by /bin/sh."""
    cfg = agent_config(name)
    stash = _ValueStash()
    env = SandboxedEnvironment(loader=BaseLoader(), undefined=ChainableUndefined)
    env.filters[QUOTED_FILTER] = stash.quoted
    env.filters[BARE_FILTER] = stash.bare
    env.filters[ENV_FILTER] = stash.name
    script = env.from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render(**values)
    done = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=120, cwd=cwd,
                          env={**os.environ, **stash.env, "PYTHONDONTWRITEBYTECODE": "1"})
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    return done.returncode, (json.loads(lines[-1]) if lines else None), done.stdout + done.stderr


# ---- the fixture: a corner shop's corpus and two rounds of results --------------------------------

MANIFEST = {
    "name": "corner-shop-fixture",
    "project": "cornershop",
    "cases": [
        {"id": "p1", "control": False, "bet": "x1", "class": "boundary off-by-one", "expected": "either",
         "criterion": "the basket reads 'Total $12.00 for 3 items'",
         "symptom": "the basket reads 'Total $8.00 for 2 items'",
         "symptom_patterns": [r"total \$8\.00 for 2 items"], "same_value_match": r"basket total"},
        {"id": "p2", "control": False, "bet": "x2", "class": "changed label", "expected": "verify",
         "criterion": "the button reads 'Add to cart'", "symptom": "the button reads 'Add to basket'",
         "symptom_patterns": [r"add to basket"], "same_value_match": None},
        {"id": "p3", "control": False, "bet": "x1", "class": "swallowed error", "expected": "either",
         "criterion": "a failed payment says so", "symptom": "a failed payment shows nothing",
         "symptom_patterns": [r"payment"], "same_value_match": None},
        {"id": "c1", "control": True, "bet": "x2", "class": "control", "expected": "none",
         "criterion": "", "symptom": "", "symptom_patterns": [], "same_value_match": None},
    ],
}


def ci_part(verdict, seconds=60.0, **out):
    return {"status": "completed", "error": None, "seconds": seconds, "cost_usd": 0.0,
            "output": {"verdict": verdict, "summary": out.pop("summary", f"{verdict}"), **out}}


def verify_part(verdict, cost=3.0, **out):
    return {"status": "completed", "error": None, "seconds": 300.0, "cost_usd": cost, "why_not_run": None,
            "output": {"verdict": verdict, "summary": out.pop("summary", f"{verdict}"), "threshold_checks": [],
                       "unmet": [], "issues": [], "same_value_checks": [], **out}}


def result(cid, test=None, verify=None, asked=("test", "verify"), run_status="completed", run_error=None,
           cost=None, seconds=400.0):
    if cost is None:
        cost = sum((p or {}).get("cost_usd") or 0 for p in (test, verify))
    return {"case": cid, "run_id": f"run-{cid}", "run_status": run_status, "run_error": run_error,
            "run_seconds": seconds, "run_cost_usd": cost,
            "asked": {"test": "test" in asked, "verify": "verify" in asked}, "test": test, "verify": verify}


def round_a() -> dict:
    """p1 caught by both, p2 missed by both, p3 a harness fault in both, c1 clean."""
    return {
        "p1": result("p1", test=ci_part("fail", failures=[{"check": "unit tests", "failure": "test_total: 8.00 != 12.00"}],
                                          checks=[{"check": "lint", "result": "pass"}, {"check": "unit tests", "result": "fail"}]),
                     verify=verify_part("fail", threshold_checks=[
                         {"clause": "the basket reads 'Total $12.00 for 3 items'", "status": "unmet",
                          "evidence": "The basket says \u201cTotal\u00a0$8.00 for 2\u00a0items\u201d \u2014 one item short"}],
                         unmet=["the basket total: it shows $8.00"])),
        "p2": result("p2", test=ci_part("pass", checks=[{"check": "lint", "result": "pass"}]),
                     verify=verify_part("fail", threshold_checks=[
                         # The symptom is in the evidence of a clause marked met: the check saw it and let it go.
                         {"clause": "the button reads 'Add to cart'", "status": "met", "evidence": "the button reads Add to basket"},
                         {"clause": "the page loads", "status": "unmet", "evidence": "it took 9 s"}],
                         unmet=["the page loads: it took 9 s"])),
        "p3": result("p3", test=ci_part("skipped", summary="the CI file has no job to run"), verify=None,
                     run_status="failed", run_error="deploy failed: the stack did not come up"),
        "c1": result("c1", test=ci_part("pass", checks=[{"check": "lint", "result": "pass"}]), verify=verify_part("pass")),
    }


def round_b() -> dict:
    """Round A again, except p1's lint flipped, one more of p1's unit tests failed (in a check that
    failed both times) and the control's tests failed."""
    got = round_a()
    got["p1"]["test"]["output"]["checks"][0]["result"] = "fail"
    got["p1"]["test"]["output"]["failures"].append(
        {"check": "unit tests", "failure": "FAILED tests/test_stock.py::test_restock - AssertionError: ['shutting down']"})
    got["c1"]["test"] = ci_part("fail", failures=[{"check": "unit tests", "failure": "timed out"}],
                                  checks=[{"check": "lint", "result": "pass"}])
    return got


def write_round(folder: Path, results: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for cid, r in results.items():
        (folder / f"{cid}.json").write_text(json.dumps(r))
    return folder


# ---- the rules ------------------------------------------------------------------------------------


def test_each_check_is_scored_by_its_own_rule():
    g = score.grade(MANIFEST, [round_a()])
    s = g["summary"]
    assert (s["planted"], s["controls"]) == (3, 1)
    for check in ("test", "verify", "together"):
        t = s[check]
        assert (t["caught"], t["missed"], t["faults"]) == (["p1"], ["p2"], ["p3"]), check
        assert t["catch_rate"] == 0.5, "a harness fault is in no rate"
        assert (t["false_alarms"], t["clean_controls"]) == ([], ["c1"]), check
    rows = {r["id"]: r for r in g["cases"]}
    assert rows["p1"]["test"]["new_failures"][0]["check"] == "unit tests"
    matched = rows["p1"]["verify"]["matched"]
    assert matched and matched[0]["where"] == "threshold_checks[0].evidence", "curly quotes and dashes are made plain"
    assert rows["p2"]["verify"]["outcome"] == "missed" and rows["p2"]["verify"]["failed_for_another_reason"]
    faults = {(f["case"], f["check"]): f["why"] for f in s["harness_faults"]}
    assert faults == {("p3", "task_test"): "verdict skipped: the CI file has no job to run",
                      ("p3", "task_verify"): "task_verify never ran (run failed: deploy failed: the stack did not come up)"}
    assert s["surprises"] == ["p2: task_verify missed a bug it was expected to see (it failed for another reason)"]
    assert s["cost_usd"] == 9.0 and s["seconds"] == 1600.0


def test_any_fail_on_a_control_is_a_false_alarm_and_never_a_catch():
    s = score.grade(MANIFEST, [round_b()])["summary"]
    assert s["test"]["false_alarms"] == ["c1"] and s["test"]["clean_controls"] == []
    assert s["together"]["false_alarms"] == ["c1"]
    assert s["verify"]["clean_controls"] == ["c1"]
    assert s["test"]["catch_rate"] == 0.5, "a control counts in no catch rate"


def test_the_symptom_must_be_in_what_the_check_found_wrong():
    case = MANIFEST["cases"][0]
    seen = {"verdict": "fail", "threshold_checks": [], "unmet": [], "issues": [],
            "same_value_checks": [{"what": "Basket total on the basket and the checkout", "build": "agree",
                                   "build_values": [{"screen": "/basket", "value": "Total $8.00 for 2 items"}]}]}
    assert score.symptom_matches(case, seen) == [], "a figure the check found agreeing is not a finding"
    seen["same_value_checks"][0]["build"] = "differ"
    found = score.symptom_matches(case, seen)
    assert {m["by"] for m in found} == {r"total \$8\.00 for 2 items", "same_value_match"}
    seen["same_value_checks"] = []
    seen["issues"] = [{"where": "/basket", "what": "Total $8.00 for 2 items, one short"}]
    assert score.symptom_matches(case, seen) == [], "an issue is a note beside the verdict, not a finding"
    seen["unmet"] = ["The basket shows the total of every item: Total $8.00 for 2 items, one short"]
    assert [m["where"] for m in score.symptom_matches(case, seen)] == ["unmet[0]"]


def test_what_the_browser_check_failed_beside_the_planted_bug_is_shown():
    got = round_a()
    unmet = got["p1"]["verify"]["output"]["unmet"]
    unmet[:] = ["the basket total: Total $8.00 for 2 items"]
    assert score.grade(MANIFEST, [got])["summary"]["verify_found_beside"] == []
    unmet.append("the menu lists 'Example basket', which should not show")
    g = score.grade(MANIFEST, [got])
    p1 = {r["id"]: r for r in g["cases"]}["p1"]
    assert p1["verify"]["outcome"] == "caught", "a line beside the symptom does not undo the catch"
    assert p1["verify"]["also_unmet"] == ["the menu lists 'Example basket', which should not show"]
    assert g["summary"]["verify_found_beside"] == [{"case": "p1", "lines": 1}]
    md = score.render(g, ["a"], None)
    assert "- p1: 1 unmet line\n" in md
    assert "  - also unmet, no symptom pattern names it: the menu lists 'Example basket'" in md


def test_one_round_for_each_check_is_graded_together():
    tests_only = {cid: dict(r, asked={"test": True, "verify": False}, verify=None, run_cost_usd=0.0,
                            run_seconds=600.0) for cid, r in round_a().items()}
    verify_only = {cid: dict(r, asked={"test": False, "verify": True}, test=None, run_id=f"v-{cid}",
                             run_cost_usd=3.0, run_seconds=300.0) for cid, r in round_a().items()}
    g = score.grade(MANIFEST, [tests_only, verify_only])
    rows = {r["id"]: r for r in g["cases"]}
    assert rows["p1"]["test"]["run_id"] == "run-p1" and rows["p1"]["verify"]["run_id"] == "v-p1"
    assert g["summary"]["together"]["caught"] == ["p1"]
    assert (rows["p1"]["run_cost_usd"], rows["p1"]["run_seconds"]) == (3.0, 900.0), "a case costs both its runs"
    assert (g["summary"]["cost_usd"], g["summary"]["seconds"]) == (12.0, 3600.0)
    alone = score.grade(MANIFEST, [tests_only])["summary"]
    assert (alone["cost_usd"], alone["seconds"]) == (0.0, 2400.0), "one run is counted once"
    assert alone["verify"]["not_run"] == ["p1", "p2", "p3"] and alone["verify"]["catch_rate"] is None
    assert alone["together"]["caught"] == ["p1"] and alone["together"]["missed"] == [], \
        "missed together only when both checks ran and both missed"


def test_a_replaced_case_is_listed_and_never_scored():
    why = "equivalent mutant: the change it planted was saved anyway"
    manifest = dict(MANIFEST, replaced=[{"id": "p0", "why": why, "replaced_by": "p2"}])
    g = score.grade(manifest, [dict(round_a(), p0=result("p0", test=ci_part("pass")))])
    assert g["summary"]["replaced"] == [{"id": "p0", "why": why, "replaced_by": "p2"}]
    assert "p0" not in [r["id"] for r in g["cases"]] and g["summary"]["planted"] == 3
    assert f"- p0, replaced by p2: {why}" in score.render(g, ["a"], None)
    assert "## Replaced before scoring (not counted)\n\n- none" in score.render(score.grade(MANIFEST, [round_a()]), ["a"], None)
    with pytest.raises(ValueError, match="both counts and replaces p1"):
        score.grade(dict(MANIFEST, replaced=[{"id": "p1", "why": why}]), [round_a()])


def test_a_pattern_added_after_a_run_is_listed_in_the_grade():
    change = {"case": "p2", "added": "add to basket", "when": "after run run-p2",
              "why": "the check quoted the written symptom in other words"}
    g = score.grade(dict(MANIFEST, pattern_changes=[change]), [round_a()])
    assert g["summary"]["pattern_changes"] == [change]
    md = score.render(g, ["a"], None)
    assert '- p2: added "add to basket" (after run run-p2): the check quoted the written symptom' in md
    assert "## Symptom patterns added after a run\n\n- none" in score.render(score.grade(MANIFEST, [round_a()]), ["a"], None)


def test_two_rounds_side_by_side_show_what_is_not_stable(tmp_path):
    a = write_round(tmp_path / "a", round_a())
    b = write_round(tmp_path / "b", round_b())
    out = tmp_path / "grade"
    g = score.main(["--manifest", str(write_manifest(tmp_path)), "--results", str(a), "--out", str(out),
                    "--compare", str(b)])
    c = g["compare"]
    assert (c["agree"], c["disagree"]) == (3, 1)
    assert [r["id"] for r in c["cases"] if not r["agree"]] == ["c1"]
    assert c["flaky_candidates"] == [{"check": "lint", "cases": ["p1"]}]
    assert c["flaky_tests"] == [{"test": "unit tests: FAILED tests/test_stock.py::test_restock", "cases": ["p1"]},
                                 {"test": "unit tests: timed out", "cases": ["c1"]}]
    md = (out / "grade.md").read_text()
    assert "3 of 4 cases agree" in md and "- lint: p1" in md
    assert "new failure only in the other round: unit tests: FAILED tests/test_stock.py::test_restock" in md
    assert "- unit tests: FAILED tests/test_stock.py::test_restock: p1" in md


def write_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(MANIFEST))
    return path


def test_the_grade_is_the_same_every_time_and_names_what_the_workflow_reads(tmp_path, capsys):
    a = write_round(tmp_path / "a", round_a())
    first, second = tmp_path / "one", tmp_path / "two"
    for out in (first, second):
        score.main(["--manifest", str(write_manifest(tmp_path)), "--results", str(a), "--out", str(out),
                    "--compare", str(a)])
    brief = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    one, two = (json.loads((d / "grade.json").read_text()) for d in (first, second))
    one.pop("scored_at"), two.pop("scored_at")
    assert one == two
    md = (first / "grade.md").read_text()
    for line in ("| task_test | 1 | 1 | 1 | 0 | 1 of 2 (50%) |", "| task_verify | 1 | 1 | 1 | 0 | 1 of 2 (50%) |",
                 "| the two together | 1 | 1 | 1 | 0 | 1 of 2 (50%) |", "- p3 task_test: verdict skipped",
                 "Total: $9.00, 26.7 min of run time."):
        assert line in md, line
    outputs = served(GRADE_WORKFLOW)["workflow"]["outputs"]
    fields = {src.split(".", 2)[2] for src in outputs.values()}
    assert fields <= set(brief), f"epd_qa_grade reads fields the scorer never prints: {fields - set(brief)}"


def test_the_scorer_says_why_it_cannot_grade(tmp_path):
    bad = dict(MANIFEST, cases=MANIFEST["cases"] + [MANIFEST["cases"][0]])
    with pytest.raises(ValueError, match="names a case twice"):
        score.grade(bad, [{}])
    with pytest.raises(SystemExit, match="no result folder"):
        score.main(["--manifest", str(write_manifest(tmp_path)), "--results", str(tmp_path / "none"),
                    "--out", str(tmp_path / "out")])


def test_the_score_step_runs_no_script_outside_the_epd_bin_folder(tmp_path):
    for scorer in ("/tmp/qa_grade_score.py", "/app/configs/epd/bin/../../../etc/x.py"):
        code, out, _ = run_step("epd_qa_score", tmp_path, manifest="m.json", results="r", out="o", scorer=scorer)
        assert code == 1 and out["status"] == "failed", scorer


# ---- one case, laid out and cleared away -----------------------------------------------------------


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def corpus(tmp_path):
    """A shop repository: a clean merged change, one planted bug on it, one control, as a bundle."""
    repo = tmp_path / "shop"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "price.py").write_text("def total(items):\n    return sum(i['price'] for i in items)\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the merged change")
    clean = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "qa-seed/p1")
    (repo / "price.py").write_text("def total(items):\n    return sum(i['price'] for i in items[1:])\n")
    git(repo, "commit", "-q", "-am", "qa case p1")
    case = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "qa-seed/c1", clean)
    git(repo, "commit", "-q", "--allow-empty", "-m", "qa case c1")
    git(repo, "branch", "-q", "qa-seed/bad", clean)
    bundle = tmp_path / "work" / "corpus.bundle"
    bundle.parent.mkdir()
    git(repo, "bundle", "create", str(bundle), "--branches")
    return {"bundle": str(bundle), "clean": clean, "case": case, "work": tmp_path / "work"}


def prepare(corpus, case_id, branch, **extra):
    values = {"bundle": corpus["bundle"], "project": "cornershop", "case_id": case_id, "case_branch": branch,
              "clean_commit": corpus["clean"], "case_commit": None, "run_test": True, "run_verify": False,
              "work_root": None} | extra
    return run_step("epd_qa_prepare", corpus["work"], **values)


def test_a_case_is_laid_out_on_its_own_commit_beside_the_clean_one(corpus):
    code, out, log = prepare(corpus, "p1", "qa-seed/p1", case_commit=corpus["case"][:12])
    assert code == 0, log
    repo = Path(out["workspace_path"])
    assert git(repo, "rev-parse", "HEAD") == out["head"] == corpus["case"]
    assert out["clean_commit"] == corpus["clean"] and out["files_changed"] == 1
    assert git(repo, "merge-base", "HEAD", out["clean_commit"]) == corpus["clean"], "task_test's base resolves"
    assert Path(out["case_root"]).parent == corpus["work"] / "cases"
    assert (out["run_test"], out["run_verify"], out["repo_url"]) == (True, False, None)


def test_the_browser_path_gets_a_bare_copy_and_nothing_leaves_the_machine(corpus):
    code, out, log = prepare(corpus, "p1", "qa-seed/p1", run_verify=True, run_test=False)
    assert code == 0, log
    remote = Path(out["case_root"]) / "remote" / "cornershop.git"
    assert out["repo_url"] == f"file://{remote}" and out["base_branch"] == "qa-seed/p1"
    assert git(remote, "rev-parse", "refs/heads/qa-seed/p1") == corpus["case"]
    assert Path(out["workspaces_root"]).is_dir() and out["claim_name"] == "qa p1"


@pytest.mark.parametrize("branch, extra, why", [
    ("qa-seed/none", {}, "the bundle has no branch qa-seed/none"),
    ("qa-seed/bad", {}, "is the clean commit itself"),
    ("qa-seed/p1", {"case_commit": "0" * 40}, "is not in the bundle"),
    ("qa-seed/p1", {"run_test": False}, "nothing to run"),
    ("qa-seed/p1", {"case_id": "p1;rm"}, "case_id must be"),
])
def test_a_case_that_cannot_be_laid_out_fails_loud_and_leaves_nothing(corpus, branch, extra, why):
    code, out, log = prepare(corpus, extra.pop("case_id", "p1"), branch, **extra)
    assert code == 1 and out["status"] == "failed" and why in out["error"], log
    cases = corpus["work"] / "cases"
    assert not cases.exists() or not any(cases.iterdir()), "a failed case leaves no folder behind"


def test_the_last_step_keeps_the_reports_and_removes_only_the_case(corpus, tmp_path):
    code, out, log = prepare(corpus, "c1", "qa-seed/c1")
    assert code == 0, log
    epd = Path(out["workspace_path"]) / ".epd"
    (epd / "tests").mkdir(parents=True)
    (epd / "tests.md").write_text("# Tests: pass\n")
    (epd / "tests" / "unit.log").write_text("ok\n")
    keep = tmp_path / "reports" / "c1"
    code, done, log = run_step("epd_qa_finish", tmp_path, case_root=out["case_root"], test_tree=out["workspace_path"],
                               verify_worktree=None, keep_reports_in=str(keep), keep=None)
    assert code == 0, log
    assert (keep / "test" / "tests.md").read_text() == "# Tests: pass\n" and (keep / "test" / "tests" / "unit.log").exists()
    assert done["removed"] is True and done["kept"] == ["test"] and not Path(out["case_root"]).exists()
    assert Path(corpus["bundle"]).exists()
    code, done, log = run_step("epd_qa_finish", tmp_path, case_root=str(tmp_path), test_tree=None,
                               verify_worktree=None, keep_reports_in=None, keep=None)
    assert code == 0 and done["removed"] is False and tmp_path.exists(), "only a folder prepare made is removed"


# ---- the workflows fit together with the live agents ----------------------------------------------


def ancestors(nodes: dict, name: str) -> set:
    seen, todo = set(), list(nodes[name].get("depends_on") or [])
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo += nodes[n].get("depends_on") or []
    return seen


def printed_fields(agent_name: str) -> str:
    return (EPD / "agents" / f"{agent_name}.yaml").read_text()


@pytest.mark.parametrize("path", [CASE_WORKFLOW, GRADE_WORKFLOW], ids=lambda p: p.stem)
def test_every_step_reads_only_what_runs_before_it(path):
    wf = served(path)["workflow"]
    nodes = {n["name"]: n for n in wf["nodes"]}
    inputs = set(wf["inputs"])
    for name, node in nodes.items():
        assert (EPD / "agents" / f"{node['agent']}.yaml").is_file(), f"{name}: no agent {node['agent']}"
        sources = list((node.get("input_map") or {}).values())
        if node.get("condition"):
            sources.append(node["condition"]["source"])
        for src in sources:
            head, _, rest = src.partition(".")
            if head == "input":
                assert rest in inputs, f"{name} reads input {rest}, which the workflow does not take"
                continue
            assert head in ancestors(nodes, name), f"{name} reads {head}, which does not run before it"
            field = rest.split(".", 1)[1]
            assert re.search(rf"\b{re.escape(field)}\b", printed_fields(nodes[head]["agent"])), \
                f"{name} reads {src}, a field {nodes[head]['agent']} never mentions"
    for out, src in wf["outputs"].items():
        assert src.split(".")[0] in nodes, f"output {out} names no step"


def test_the_case_runs_the_live_checks_unchanged():
    nodes = {n["name"]: n for n in served(CASE_WORKFLOW)["workflow"]["nodes"]}
    assert nodes["test"]["agent"] == "task_test" and nodes["verify"]["agent"] == "task_verify"
    assert nodes["test"]["input_map"]["base_branch"] == "prepare.structured.clean_commit"
    for name in ("claim", "worktree", "stack_detect", "stack_up", "deploy", "verify", "stack_down"):
        assert nodes[name].get("condition"), f"{name} runs only on the browser path"
    assert "task_cleanup" not in {n["agent"] for n in nodes.values()}, "the case's own folder goes, not a branch"
    assert nodes["finish"]["run_after_failure"] and nodes["stack_down"]["run_after_failure"]


def test_departments_names_the_grader_and_its_parts():
    text = (ROOT / "docs" / "departments.md").read_text()
    for name in ("epd_qa_grade", "epd_qa_case", "epd_qa_prepare", "epd_qa_finish", "epd_qa_score", "qa_grade_score.py"):
        assert name in text, f"docs/departments.md does not list {name}"
