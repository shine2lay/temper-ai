"""The signal_harvest quality grader (configs/workflows/signal_grade.yaml, product role) fits together.

It grades one finished signal_harvest report for soundness against its own evidence (queue #12):
a script recomputes the scorecard's cells, totals, overall confidence, ranking and candidate and
required-player coverage and traces its figures, quotes and URLs to the lens files; a model review
resolves the leads the script left and looks for attribution, blocked-source, scope and competitor
defects; finalize counts only findings whose passages are verbatim in the files and sets pass,
revise or unknown per criterion Q1-Q6. Here: the configs run in that order, the scripts parse under
/bin/sh and are fed every value they use, the review keeps Claude Code's own tools; the rubric and
the benchmark stay frozen; the checker reproduces every row of the five retained reports and finds
the planted table defects; finalize refuses findings it cannot verify, leads it cannot resolve,
grades from another run and reports changed while grading; score.py applies expected.json's
matching rule; a lens that left no usable output (its file missing, empty or an account-limit
message, or its final answer such a message, queue #23) is named and the grade never passes.
No model and no network: every review here is a hand-written review.json.
"""

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import types
from pathlib import Path

import pytest
import yaml
from jinja2 import BaseLoader, ChainableUndefined, meta
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
AGENTS_DIR = ROOT / "configs" / "agents"
AGENTS = sorted(AGENTS_DIR.glob("signal_grade_*.yaml"))
ASSETS = AGENTS_DIR / "signal_grade_assets"
WORKFLOW = ROOT / "configs" / "workflows" / "signal_grade.yaml"
HARVEST = ROOT / "configs" / "workflows" / "signal_harvest.yaml"
BENCH = Path(__file__).resolve().parent / "benchmark"
INJECTED = {"workspace_path", "run_id"}  # the script agent adds these to every template
ORDER = ["signal_grade_setup", "signal_grade_review", "signal_grade_finalize"]
CHECKED = {"source": "setup.structured.status", "operator": "equals", "value": "checked"}
# Frozen before the grader's first test run (results/2026-10-04-signal-grade-12/criteria.md).
FROZEN = {
    "configs/agents/signal_grade_assets/rubric.md": "c1ebfe5c52fef0e58d86a9b507d0f68e2f92c40cf38ead61c61270d141f6ac2b",
    "tests/test_signal_grade/benchmark/expected.json": "4834dfe0293d905d3951d0e9f462cdcc7f137aabad02c33ffccc882e864b4b94",
    "tests/test_signal_grade/benchmark/mutations.json": "0803a194577a8bb31642139042720872100bea022db02aab216b9356fff128bc",
    "tests/test_signal_grade/benchmark/SOURCES.json": "f7ff1379cf2c46496809e6e4a3359c90690a6c7cf8ace63413cefe588533fa57",
    "tests/test_signal_grade/benchmark/build.py": "37dd46ec14f5d7fece47995a1cbc0b60721c2dae3cf29374ddf1646a844adb18",
}
CONTROLS = {"r3kx": 4, "w2hc": 4, "f9mb": 7, "n6vs": 4, "b7ye": 4}  # key: table rows
# signal_harvest hands the quality check each lens's final answer (queue #23).
LENS_ANSWERS = {"search_answer": "signal_search", "money_answer": "signal_jobs", "pain_answer": "signal_pain",
                "competitors_answer": "signal_competitors"}
LIMIT = "You've hit your session limit \u00b7 resets 10:50pm (UTC)"
# What the Claude provider returns as an answer when its call failed (finish_reason "error", not read yet).
TIMED_OUT = "Error: Claude Code CLI timed out"
STREAM_ENDED = "[claude_code error] stream ended with no result event: " + " | ".join(["node: stderr line"] * 40)


def unwired_default(template, name):
    """Left unfed, the value arrives as __unwired__ (an answer the workflow could not find), never as text."""
    return f"{name} is string else '__unwired__'" in template


def served(path):
    """The config as the server hands it out (ConfigStore.get runs the env substitution)."""
    return substitute_env_vars(yaml.safe_load(path.read_text()))


def agent(path):
    return served(path)["agent"]


def by_name(name):
    return agent(AGENTS_DIR / f"{name}.yaml")


def workflow():
    return served(WORKFLOW)["workflow"]


def templates_of(cfg):
    if cfg.get("type") == "script":
        return [cfg["script_template"]]
    return [cfg["task_template"], cfg.get("system_prompt", "")]


def jinja(stash=None):
    """Jinja as the script agent sets it up, with its value filters."""
    env = SandboxedEnvironment(loader=BaseLoader(), undefined=ChainableUndefined)
    stash = stash if stash is not None else _ValueStash()
    env.filters[QUOTED_FILTER] = stash.quoted
    env.filters[BARE_FILTER] = stash.bare
    env.filters[ENV_FILTER] = stash.name
    return env


def load(path, name):
    """A helper script loaded as a module, without leaving bytecode next to it."""
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


bench = load(BENCH / "build.py", "signal_grade_bench")
scorer = load(BENCH / "score.py", "signal_grade_score")
CASES = {c["key"]: c for c in bench.cases()}


def step(name, workspace, **values):
    """A script step rendered the way the script agent renders it and run by /bin/sh."""
    cfg = by_name(name)
    stash = _ValueStash()
    script = jinja(stash).from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render(
        workspace_path=str(workspace), **values)
    env = {**os.environ, **stash.env, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=120, cwd=workspace, env=env)


def last_json(stdout):
    return json.loads([line for line in stdout.splitlines() if line.startswith("{")][-1])


def stage(tmp_path, key):
    """One benchmark case staged as the launcher stages it: assets in _assets, the report in _case."""
    workspace = tmp_path / key
    (workspace / "_assets").mkdir(parents=True)
    for name in ("check_signal.py", "rubric.md"):
        shutil.copyfile(ASSETS / name, workspace / "_assets" / name)
    for rel, data in bench.case_files(CASES[key]).items():
        target = workspace / "_case" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return workspace


def setup(workspace, run_id="run-1", **values):
    values = {"report": str(workspace / "_case"), "shortlist_path": str(workspace / "_case" / "shortlist.txt"),
              "assets_dir": str(workspace / "_assets"), "run_id": run_id, **values}
    done = step("signal_grade_setup", workspace, **values)
    assert done.returncode == 0, done.stderr
    return last_json(done.stdout)


def finalize(workspace, run_id="run-1"):
    done = step("signal_grade_finalize", workspace, run_id=run_id)
    assert done.returncode == 0, done.stderr
    return last_json(done.stdout)


def grade_dir(workspace):
    return workspace / "state" / "signal_grade"


def check_of(workspace):
    return json.loads((grade_dir(workspace) / "check.json").read_text())


def quality_of(workspace):
    return json.loads((grade_dir(workspace) / "quality.json").read_text())


def write_review(workspace, review):
    (grade_dir(workspace) / "review.json").write_text(json.dumps(review))


def all_ok(check, criteria_note="checked"):
    """A review that resolves every lead ok and passes every criterion."""
    return {"findings": [], "leads": [{"id": lead["id"], "resolution": "ok", "why": "other", "note": "fine"}
                                      for lead in check["leads"]],
            "criteria": {c: {"status": "pass", "note": criteria_note} for c in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6")},
            "limitations": ["hand-written test review"]}


# ---- the configs ---------------------------------------------------------------------------------


def test_the_workflow_runs_setup_then_the_review_then_finalize():
    assert {p.stem for p in AGENTS} == {agent(p)["name"] for p in AGENTS}, "each agent file is named after its agent"
    nodes = workflow()["nodes"]
    assert [n["agent"] for n in nodes] == ORDER
    assert set(ORDER) == {p.stem for p in AGENTS}, "the workflow runs every grading agent"
    for before, after in zip(nodes, nodes[1:], strict=False):
        assert after["depends_on"] == [before["name"]], "one step at a time, in order"
    assert nodes[1].get("condition") == CHECKED, "the review waits for a report the script could check"
    assert "condition" not in nodes[0] and "condition" not in nodes[2]
    assert nodes[2]["name"] == "finalize" and nodes[2].get("run_after_failure") is True


@pytest.mark.parametrize("path", [p for p in AGENTS if agent(p).get("type") == "script"], ids=lambda p: p.stem)
def test_every_script_step_parses_under_sh(path):
    cfg = agent(path)
    script = jinja().from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render()
    done = subprocess.run(["sh", "-n", "-c", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, f"{path.name} does not parse under /bin/sh: {done.stderr.strip()}"


@pytest.mark.parametrize("path", [*AGENTS, WORKFLOW], ids=lambda p: p.stem)
def test_no_file_holds_the_config_stores_env_syntax(path):
    assert "${" not in path.read_text(), "the config store would substitute it as an env var"


def test_the_review_keeps_claude_codes_own_tools_and_works_from_the_files_only():
    cfg = by_name("signal_grade_review")
    assert cfg["provider"] == "claude"
    assert "tools" not in cfg, "provider claude refuses temper tool schemas; it uses its own Bash/Read/Write tools"
    prompt = cfg["system_prompt"]
    for rule in ("do not browse the web", "Never rescore", "Write only state/signal_grade/review.json",
                 "verify --dry-run", "rubric.md"):
        assert rule in prompt, f"the review prompt lost {rule!r}"


def test_the_product_launcher_starts_signal_grade_as_a_live_workflow():
    """docs/product-runs.md starts it by name; the launcher refuses a name outside its LIVE set."""
    tree = ast.parse((ROOT / "configs" / "product" / "bin" / "server_run.py").read_text())
    live = next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["LIVE"])
    assert {"signal_grade", "signal_harvest"} <= live
    assert "start.sh $JOB signal_grade" in (ROOT / "docs" / "product-runs.md").read_text()


def test_every_template_variable_is_fed_by_the_workflow():
    env = jinja()
    wf = workflow()
    for node in wf["nodes"]:
        fed = set(node.get("input_map") or {})
        for value in (node.get("input_map") or {}).values():
            assert value.startswith("input.") and value.split(".", 1)[1] in wf["inputs"], f"{value} is not an input"
        for template in templates_of(by_name(node["agent"])):
            used = {v for v in meta.find_undeclared_variables(env.parse(template)) if not unwired_default(template, v)}
            assert used <= fed | INJECTED, f"{node['agent']} uses {sorted(used - fed - INJECTED)} that the workflow never passes"


def test_signal_harvest_grades_its_report_after_the_unchanged_research():
    harvest = served(HARVEST)["workflow"]
    synthesize, *quality = harvest["nodes"]
    assert synthesize == {
        "name": "synthesize", "type": "stage", "strategy": "leader", "input_map": {"shortlist": "input.shortlist"},
        "agents": [{"agent": "signal_search"}, {"agent": "signal_jobs"}, {"agent": "signal_pain"},
                   {"agent": "signal_competitors"}, {"agent": "signal_synthesize", "role": "leader"}],
    }, "the four lenses and the synthesizer run as they did before the grade was added"
    for name, ref in {"scorecard_path": "synthesize.structured.scorecard_path", "ranking": "synthesize.structured.ranking",
                      "recommend_advance": "synthesize.structured.recommend_advance"}.items():
        assert harvest["outputs"][name] == ref, "the research outputs keep their contract"
    assert harvest["inputs"]["shortlist"]["required"] is True
    assert [n["agent"] for n in quality] == ORDER, "the same three steps as signal_grade, after the synthesizer"
    assert quality[0]["depends_on"] == ["synthesize"]
    for before, after in zip(quality, quality[1:], strict=False):
        assert after["depends_on"] == [before["name"]]
    assert quality[1]["condition"] == {**CHECKED, "source": f"{quality[0]['name']}.structured.status"}
    assert quality[2].get("run_after_failure") is True and "condition" not in quality[2]
    printed = {quality[0]["name"]: "setup", quality[2]["name"]: "finalize"}
    grade_outputs = set(workflow()["outputs"].values())
    for name in ("quality_status", "quality_path", "quality_criteria"):
        node, _, field = harvest["outputs"][name].partition(".structured.")
        assert f"{printed[node]}.structured.{field}" in grade_outputs, f"{name} names a field finalize prints"
    answers = {name: f"synthesize.{lens}.output" for name, lens in LENS_ANSWERS.items()}
    assert {k: v for k, v in quality[0]["input_map"].items() if k in answers} == answers, "setup gets each lens's answer"
    lenses = {a["agent"] for a in synthesize["agents"] if a.get("role") != "leader"}
    assert set(LENS_ANSWERS.values()) == lenses
    env = jinja()
    for node in quality:
        fed = node.get("input_map") or {}
        for value in fed.values():
            if value in answers.values():
                continue  # a lens's final answer, from the stage the check waits for
            assert value.startswith("input.") and value.split(".", 1)[1] in harvest["inputs"], f"{value} is not an input"
        for template in templates_of(by_name(node["agent"])):
            for used in meta.find_undeclared_variables(env.parse(template)) - set(fed) - INJECTED:
                # Left unfed, a value renders as an empty string through `(x or '')`, never as text.
                assert f"({used} or '')" in template, f"{node['agent']} needs {used} fed or defaulted"


def test_an_input_the_run_did_not_give_is_empty_not_the_text_none(tmp_path):
    """The server passes an input the run did not give as None: the first benchmark run (1b7aef1a)
    wrote the text 'None' as its shortlist and left candidate coverage unknown."""
    workspace = stage(tmp_path, "r3kx")
    assert setup(workspace, shortlist=None)["status"] == "checked"
    assert json.loads((grade_dir(workspace) / "setup.json").read_text())["shortlist"].startswith("shortlist_path")
    check = check_of(workspace)
    assert check["candidates"]["shortlist"] and "Q1" not in check["unknown"]
    fallback = stage(tmp_path / "fallback", "r3kx")
    (fallback / "state").mkdir()
    for name in ("signal_scorecard.md", "signal"):
        (fallback / "_case" / name).rename(fallback / "state" / name)
    out = setup(fallback, report=None, shortlist_path=None, shortlist=(fallback / "_case" / "shortlist.txt").read_text())
    assert out["status"] == "checked", "no report given -> state/, where signal_harvest writes it"
    assert json.loads((grade_dir(fallback) / "setup.json").read_text())["report_dir"] == "state"


def test_the_workflow_outputs_name_fields_setup_and_finalize_print(tmp_path):
    workspace = stage(tmp_path, "w2hc")
    printed_setup = setup(workspace)
    write_review(workspace, all_ok(check_of(workspace)))
    printed_final = finalize(workspace)
    printed = {"setup": set(printed_setup), "finalize": set(printed_final)}
    for ref in workflow()["outputs"].values():
        node, _, field = ref.partition(".structured.")
        assert field in printed.get(node, set()), f"{ref}: {node} never prints `{field}`"
    stopped = setup(stage(tmp_path / "none", "w2hc"), report="nowhere")
    assert set(stopped) == printed["setup"], "a setup that stops prints what a check prints"
    fallback = finalize(stage(tmp_path / "unset", "w2hc"))
    assert set(fallback) == printed["finalize"], "finalize without a grade prints what a grade prints"


# ---- the frozen bar and the fixed benchmark -----------------------------------------------------


def test_the_rubric_and_the_benchmark_are_frozen():
    for rel, digest in FROZEN.items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, f"{rel} moved: the bar is frozen"
    bench.check_sources()  # the frozen copies match SOURCES.json and every mutation applies exactly
    rubric_version = re.search(r"signal_grade/\d+", (ASSETS / "rubric.md").read_text()).group(0)
    assert f'RUBRIC_VERSION = "{rubric_version}"' in (ASSETS / "check_signal.py").read_text()


def test_the_benchmark_builds_nine_reports_that_never_say_what_is_expected(tmp_path):
    first = bench.materialise(tmp_path / "a")
    assert first == bench.materialise(tmp_path / "b"), "the same files every time"
    assert sorted(first) == sorted(CASES) and len(CASES) == 9
    tells = re.compile(r"planted|mutant|mutation|benchmark|signal_grade|expected\.json|\bD1[0-3]?\b", re.I)
    for key, case in CASES.items():
        base = bench.case_files({**case, "mutant": None})
        files = bench.case_files(case)
        assert set(files) == set(base)
        changed = sorted(rel for rel in files if files[rel] != base[rel])
        assert changed == (["signal_scorecard.md"] if case["mutant"] else []), "only a mutant's scorecard changes"
        added = set(tells.findall(files["signal_scorecard.md"].decode())) - set(
            tells.findall(base["signal_scorecard.md"].decode()))
        assert not added, f"{key} tells the grader {added}"
    with pytest.raises(SystemExit):
        (tmp_path / "a" / "r3kx" / "signal_scorecard.md").write_text("changed")
        bench.materialise(tmp_path / "a")


# ---- the deterministic check --------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(CONTROLS), ids=lambda k: CASES[k]["case"])
def test_the_check_reproduces_every_row_of_the_retained_reports(tmp_path, key):
    workspace = stage(tmp_path, key)
    out = setup(workspace)
    assert out["status"] == "checked" and not out["problems"]
    check = check_of(workspace)
    assert len(check["rows"]) == CONTROLS[key]
    assert [r["id"] for r in check["rows"] if r["problems"]] == [], "a retained report's arithmetic reproduces"
    assert all(e["problems"] == [] for e in check["arithmetic"])
    assert not check["unknown"], "every criterion the script reads can be checked"
    findings = [(f["criterion"], f["candidate"], f["kind"]) for f in check["findings"]]
    want_missing = CASES[key]["expect"]["players_missing"]
    if want_missing:
        assert findings == [("Q6", "*", "missing_player")]
        assert sorted(check["players"]["missing"]) == sorted(want_missing)
    else:
        assert findings == [], "no allegation against a sound table"
        assert (check["players"] or {}).get("missing") == want_missing


def test_the_check_finds_the_planted_table_defects_and_leaves_leads_for_the_rest(tmp_path):
    found = {}
    for key in ("p8dn", "x4qa", "u1gr"):
        workspace = stage(tmp_path, key)
        assert setup(workspace)["status"] == "checked"
        found[key] = check_of(workspace)
    kinds = {key: sorted({(f["criterion"], f["candidate"], f["kind"]) for f in c["findings"]}) for key, c in found.items()}
    assert kinds["p8dn"] == [("Q2", "A", "arithmetic"), ("Q2", "A0", "confidence")]
    assert kinds["x4qa"] == [("Q1", "7", "missing_candidate")]
    assert kinds["u1gr"] == [("Q1", "V2", "duplicate"), ("Q2", "V3", "arithmetic")]
    leads = {key: c["leads"] for key, c in found.items()}
    assert any(lead["type"] == "untraced_figure" and lead["candidate"] == "B" and "74.2%" in lead["text"]
               for lead in leads["p8dn"]), "an unsupported figure is a lead for the review"
    assert any(lead["type"] == "untraced_quote" and lead["candidate"] == "V3" and "spreadsheet" in lead["text"]
               for lead in leads["u1gr"]), "an unsupported quote is a lead for the review"
    assert any(lead["criterion"] == "Q4" and "G2" in lead["text"] for lead in leads["x4qa"])


# ---- finalize -----------------------------------------------------------------------------------


def test_finalize_counts_only_findings_it_can_verify(tmp_path):
    workspace = stage(tmp_path, "w2hc")
    setup(workspace)
    review = all_ok(check_of(workspace))
    review["findings"] = [
        {"id": "R1", "criterion": "Q3", "candidate": "2", "kind": "misattributed", "severity": "material",
         "claim": "x", "problem": "a passage the files do not hold",
         "passages": [{"file": "state/signal_scorecard.md", "text": "this sentence is in no file at all"},
                      {"file": "state/signal/pain.md", "text": "nor is this one anywhere"}]},
        {"id": "R2", "criterion": "Q3", "candidate": "REFERENCE", "kind": "unsupported", "severity": "material",
         "claim": "x", "problem": "a figure alleged absent that the search lens holds", "absent": "54%",
         "passages": [{"file": "signal_scorecard.md", "text": "IRF prior-auth requests denied **54% overall**"}]},
        {"id": "R4", "criterion": "Q3", "candidate": "REFERENCE", "kind": "unsupported", "severity": "material",
         "claim": "x", "problem": "a figure alleged absent that the report never states", "absent": "57.4%",
         "passages": [{"file": "signal_scorecard.md", "text": "REFERENCE"}]},
        {"id": "R3", "criterion": "Q5", "candidate": "1", "kind": "denominator", "severity": "material",
         "claim": "x", "problem": "cites the scorecard only, no lens passage", "passages": [
             {"file": "signal_scorecard.md", "text": "| search"}]},
    ]
    write_review(workspace, review)
    out = finalize(workspace)
    q = quality_of(workspace)
    assert out["quality_status"] == "pass" and out["findings"] == 0 and out["unverified"] == 4
    assert {f["id"] for f in q["unverified"]} == {"R1", "R2", "R3", "R4"}
    why = {f["id"]: " ".join(f["why"]) for f in q["unverified"]}
    assert "is in" in why["R2"] and "no cited scorecard passage states" in why["R4"]
    assert q["findings"] == [] and q["integrity"]["unchanged"] is True and q["limitations"]
    assert (grade_dir(workspace) / "quality.md").is_file()


def test_a_verified_finding_sets_revise_and_an_unresolved_lead_sets_unknown(tmp_path):
    workspace = stage(tmp_path, "p8dn")
    setup(workspace)
    check = check_of(workspace)
    lead = next(x for x in check["leads"] if x["type"] == "untraced_figure" and "74.2%" in x["text"])
    review = all_ok(check)
    review["findings"] = [{"id": "R1", "criterion": "Q3", "candidate": "B", "kind": "unsupported",
                           "severity": "material", "claim": "74.2% initial denial rate",
                           "problem": "no lens file has 74.2%", "absent": "74.2%",
                           "passages": [{"file": "signal_scorecard.md", "text": "74.2% initial denial rate"}]}]
    review["leads"] = [r if r["id"] != lead["id"] else {"id": lead["id"], "resolution": "finding", "finding": "R1"}
                       for r in review["leads"]]
    q5 = next(x for x in check["leads"] if x["criterion"] == "Q5")
    review["leads"] = [r for r in review["leads"] if r["id"] != q5["id"]]
    write_review(workspace, review)
    out = finalize(workspace)
    assert out["quality_status"] == "revise"
    assert out["criteria"]["Q2"] == "revise", "the script's own arithmetic and confidence findings count"
    assert out["criteria"]["Q3"] == "revise" and out["criteria"]["Q5"] == "unknown"
    q = quality_of(workspace)
    assert next(x for x in q["leads"] if x["id"] == lead["id"])["resolution"] == "finding"
    assert q5["id"] in q["criteria"]["Q5"]["unresolved_leads"]


def test_a_derived_figure_needs_a_computation_that_holds(tmp_path):
    results = {}
    for expression in ("0.90/1.54", "0.50/1.54"):
        workspace = stage(tmp_path / expression.replace("/", "_"), "w2hc")
        setup(workspace)
        check = check_of(workspace)
        lead = next(x for x in check["leads"] if x["type"] == "untraced_figure" and "58%" in x["text"])
        review = all_ok(check)
        review["leads"] = [r if r["id"] != lead["id"] else
                           {"id": lead["id"], "resolution": "ok", "why": "derived", "expression": expression,
                            "note": "share of the report's own weighted score"} for r in review["leads"]]
        write_review(workspace, review)
        results[expression] = (finalize(workspace), next(x for x in quality_of(workspace)["leads"] if x["id"] == lead["id"]))
    assert results["0.90/1.54"][0]["criteria"]["Q3"] == "pass" and results["0.90/1.54"][1]["resolution"] == "ok"
    assert results["0.50/1.54"][0]["criteria"]["Q3"] == "unknown" and results["0.50/1.54"][1]["resolution"] == "unresolved"


def test_a_review_that_says_revise_without_a_verified_finding_is_unknown(tmp_path):
    workspace = stage(tmp_path, "r3kx")
    setup(workspace)
    review = all_ok(check_of(workspace))
    review["criteria"]["Q6"] = {"status": "revise", "note": "says so, shows nothing"}
    write_review(workspace, review)
    assert finalize(workspace)["criteria"]["Q6"] == "unknown"


def test_grading_never_changes_the_report_and_says_so_if_it_did(tmp_path):
    workspace = stage(tmp_path, "r3kx")
    setup(workspace)
    write_review(workspace, all_ok(check_of(workspace)))
    with (workspace / "_case" / "signal_scorecard.md").open("a") as handle:
        handle.write("\nedited while grading\n")
    out = finalize(workspace)
    q = quality_of(workspace)
    assert out["quality_status"] != "pass" and q["integrity"]["unchanged"] is False
    assert any("changed during grading" in p for p in out["problems"])


def test_setup_stops_without_a_report_or_in_a_used_grading_folder(tmp_path):
    workspace = stage(tmp_path, "r3kx")
    stopped = setup(workspace, report="nowhere")
    assert stopped["status"] != "checked"
    assert finalize(workspace)["quality_status"] == "unknown"
    other = stage(tmp_path / "used", "r3kx")
    assert setup(other)["status"] == "checked"
    again = setup(other, run_id="run-2")
    assert again["status"] == "not_checked" and "already holds a grade" in again["problems"][0]


def test_a_grade_from_another_run_or_a_spent_account_is_not_a_pass(tmp_path):
    workspace = stage(tmp_path, "r3kx")
    setup(workspace, run_id="run-1")
    write_review(workspace, all_ok(check_of(workspace)))
    other = finalize(workspace, run_id="run-2")
    assert other["quality_status"] == "unknown" and "another run" in other["problems"][0]
    spent = stage(tmp_path / "spent", "r3kx")
    setup(spent)
    (grade_dir(spent) / "review.json").write_text("You've hit your session limit · resets 3am")
    out = finalize(spent)
    assert out["quality_status"] == "unknown"
    assert all(out["criteria"][c] == "unknown" for c in ("Q3", "Q4", "Q5", "Q6"))


# ---- a lens that left no usable output (queue #23) ----------------------------------------------


LOST_LENS = [
    ("nothing lost", "r3kx", lambda case: None, {}, None),
    ("the competitors file gone", "r3kx", lambda case: (case / "signal" / "competitors.md").unlink(), {},
     "competitors lens left no usable output: "),
    ("the pain file a limit message", "r3kx", lambda case: (case / "signal" / "pain.md").write_text(LIMIT + "\n"),
     {}, "pain lens left no usable output: "),
    ("the search file empty", "w2hc", lambda case: (case / "signal" / "search.md").write_text(""), {},
     "search lens left no usable output: "),
    ("the spend file gone", "b7ye", lambda case: (case / "signal" / "spend.md").unlink(), {},
     "money lens left no usable output: "),
    ("the money answer a limit message", "r3kx", lambda case: None,
     {"money_answer": LIMIT, "search_answer": '```json\n{"status": "completed", "note": "rate limit hit once"}\n```',
      "pain_answer": None}, "money lens left no usable output: its final answer is an account-limit or error message"),
    ("the pain file a CLI timeout", "w2hc", lambda case: (case / "signal" / "pain.md").write_text(TIMED_OUT + "\n"),
     {}, "pain lens left no usable output: "),
    ("the competitors answer a failed call", "r3kx", lambda case: None, {"competitors_answer": STREAM_ENDED},
     "competitors lens left no usable output: its final answer is an account-limit or error message"),
]


@pytest.mark.parametrize(("key", "lose", "answers", "problem"), [x[1:] for x in LOST_LENS], ids=[x[0] for x in LOST_LENS])
def test_a_lens_that_left_no_usable_output_is_named_and_the_grade_never_passes(tmp_path, key, lose, answers, problem):
    workspace = stage(tmp_path, key)
    lose(workspace / "_case")
    out = setup(workspace, **answers)
    assert out["status"] == "checked", "the review still runs on what the report holds"
    check = check_of(workspace)
    write_review(workspace, all_ok(check))
    final = finalize(workspace)
    if problem is None:
        assert set(check["parts"].values()) == {"ok"} and check["answers_checked"] == []
        assert final["quality_status"] == "pass"
        return
    lens = problem.split()[0]
    assert [p for p in check["problems"] if "left no usable output" in p][0].startswith(problem), check["problems"]
    assert [s for s, why in check["parts"].items() if why != "ok"] == [lens]
    assert problem in check["unknown"]["Q3"], "its evidence could not be traced: Q3 is unknown"
    assert final["quality_status"] != "pass" and final["criteria"]["Q3"] != "pass"
    assert any(p.startswith(problem) for p in final["problems"]), final["problems"]
    if answers:
        passed = [s for s in ("search", "money", "pain", "competitors") if answers.get(f"{s}_answer")]
        assert check["answers_checked"] == passed, "an answer the workflow could not find is left out"


# ---- score.py -----------------------------------------------------------------------------------


def test_score_applies_the_matching_rule(tmp_path):
    mutant = stage(tmp_path, "p8dn")
    setup(mutant)
    write_review(mutant, all_ok(check_of(mutant)))
    finalize(mutant)
    result = scorer.score_case(CASES["p8dn"], mutant)
    detected = {r["id"]: r["detected"] for r in result["required"]}
    assert detected == {"D1": True, "D2": True, "D3": False, "D4": False}, "the script's findings detect D1 and D2"
    assert result["ok_mechanical"] is False and result["problems"] == []

    control = stage(tmp_path / "control", "w2hc")
    setup(control)
    review = all_ok(check_of(control))
    review["findings"] = [{"id": "R1", "criterion": "Q4", "candidate": "REFERENCE", "kind": "unknown_as_absence",
                           "severity": "material", "claim": "x", "problem": "an allegation the bar forbids",
                           "passages": [{"file": "signal_scorecard.md", "text": "REFERENCE"},
                                        {"file": "pain.md", "text": "REFERENCE"}]}]
    write_review(control, review)
    assert finalize(control)["quality_status"] == "revise"
    result = scorer.score_case(CASES["w2hc"], control)
    assert [f["forbidden"] for f in result["forbidden"]] == [["F3"]]
    assert result["status_ok"] is False and result["ok_mechanical"] is False
    (control / "_case" / "signal" / "pain.md").write_text("changed")
    assert any("differs from the frozen case" in p for p in scorer.score_case(CASES["w2hc"], control)["problems"])
