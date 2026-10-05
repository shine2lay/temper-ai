"""The positioning grader (configs/workflows/positioning_grade.yaml, Product marketing) fits together.

It grades one positioning document (positioning_grade_assets/FORMAT.md) for soundness against its
own evidence folder (marketing queue #1): a script checks the sections, the label lines, the
messaging hierarchy's shape, positioning.json against section 6, every citation's file and
verbatim quote, the numbers in cited lines, hype words and sentence length; a model review judges
Dunford's five components, the pillars, whether each quote says what its line claims and plain
words; the report step counts only findings whose passages are verbatim in the files and sets
pass, revise or unknown per criterion P1-P8. Here: the configs run in that order, the scripts
parse under /bin/sh and are fed every value they use, the review keeps Claude Code's own tools and
works from the files only; the benchmark stays frozen and the checker alone finds what
expected.json says; the checker catches each kind of format defect on a sound document; the
report refuses findings it cannot verify, leads it cannot resolve, grades from another run and
documents changed while grading; score.py applies expected.json's matching rule. No model and no
network: every review here is a hand-written review.json.
"""

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
ORDER = ["positioning_grade_check", "positioning_reviewer", "positioning_grade_report"]
AGENTS = [AGENTS_DIR / f"{name}.yaml" for name in ORDER]
ASSETS = AGENTS_DIR / "positioning_grade_assets"
WORKFLOW = ROOT / "configs" / "workflows" / "positioning_grade.yaml"
BENCH = Path(__file__).resolve().parent / "benchmark"
INJECTED = {"workspace_path", "run_id"}  # the script agent adds these to every template
CHECKED = {"source": "check.structured.status", "operator": "equals", "value": "checked"}
CRITERIA = ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8")
# Frozen before the grader's first test run (2026-10-04; the bar is benchmark/expected.json's "bar").
FROZEN = {
    "tests/test_positioning_grade/benchmark/expected.json": "afd98675d8e569425a50581ea8473f3de189b66e21802e55bd7f9469017c3489",
    "tests/test_positioning_grade/benchmark/mutations.json": "7a95f6458a144a5469bd21b8e961a4e71d3694c9d8b9982e52db3b9e0124c998",
    "tests/test_positioning_grade/benchmark/build.py": "9922d325691ed417e56b8125f2a005c0cff6758169c7d51366a06870e225f5df",
    "tests/test_positioning_grade/benchmark/sources/c1/positioning.md": "991bca67338aec20aaa169cfd8865298c4eabbaf975d6eccd4130aa05e3c01dc",
    "tests/test_positioning_grade/benchmark/sources/c1/positioning.json": "642b015af0a1878cebf97b04475a1acfc2487cec6a7bc56992e4b15ef2c7ee13",
    "tests/test_positioning_grade/benchmark/sources/c2/positioning.md": "fd64b6878d3338b5a2a320a98f421fa498ec5552aff5fc575a5c04eba8ad748c",
    "tests/test_positioning_grade/benchmark/sources/c2/positioning.json": "bfb44ecfc0d4cd8f95b632c347d343e360a01deaa8753478b14054e68b3618cb",
}
EVIDENCE_DIGEST = "1adb1290dabb059f9f85b84dedd0b21ecbad58d1441db1bf56919b034906e450"  # every evidence file, by path
CONTROL = "q7tn"  # C1


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


bench = load(BENCH / "build.py", "positioning_grade_bench")
scorer = load(BENCH / "score.py", "positioning_grade_score")
checker = bench.load_checker()
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


def stage(tmp_path, key=CONTROL):
    """One benchmark case staged as a trial stages it: the assets in _assets, the case at the top."""
    workspace = tmp_path / key
    (workspace / "_assets").mkdir(parents=True)
    for name in ("check_positioning.py", "rubric.md", "FORMAT.md"):
        shutil.copyfile(ASSETS / name, workspace / "_assets" / name)
    for rel, data in bench.case_files(CASES[key]).items():
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return workspace


def check(workspace, run_id="run-1", **values):
    values = {"assets_dir": str(workspace / "_assets"), "run_id": run_id, **values}
    done = step("positioning_grade_check", workspace, **values)
    assert done.returncode == 0, done.stderr
    return last_json(done.stdout)


def report(workspace, run_id="run-1"):
    done = step("positioning_grade_report", workspace, run_id=run_id)
    assert done.returncode == 0, done.stderr
    return last_json(done.stdout)


def grade_dir(workspace):
    return workspace / "state" / "positioning_grade"


def check_of(workspace):
    return json.loads((grade_dir(workspace) / "check.json").read_text())


def quality_of(workspace):
    return json.loads((grade_dir(workspace) / "quality.json").read_text())


def write_review(workspace, review):
    (grade_dir(workspace) / "review.json").write_text(json.dumps(review))


def all_ok(check_result, findings=(), **criteria):
    """A review that resolves every lead ok and passes every criterion not given."""
    return {"findings": list(findings),
            "leads": [{"id": lead["id"], "resolution": "ok", "note": "fine"} for lead in check_result["leads"]],
            "criteria": {c: {"status": criteria.get(c, "pass"), "note": "checked"} for c in CRITERIA},
            "limitations": ["hand-written test review"]}


WHITEBOARD = "The whiteboard: the chef writes the prep list each morning and guesses the amounts from last week's sales."
FINDING = {"id": "R1", "criterion": "P1", "kind": "test", "severity": "material", "claim": WHITEBOARD,
           "problem": "a hand-written finding", "passages": [{"file": "positioning.md", "text": WHITEBOARD}]}


# ---- the configs ---------------------------------------------------------------------------------


def test_the_workflow_runs_check_then_the_review_then_report():
    assert all(agent(p)["name"] == p.stem for p in AGENTS), "each agent file is named after its agent"
    nodes = workflow()["nodes"]
    assert [n["agent"] for n in nodes] == ORDER
    assert [n["name"] for n in nodes] == ["check", "review", "report"]
    for before, after in zip(nodes, nodes[1:], strict=False):
        assert after["depends_on"] == [before["name"]], "one step at a time, in order"
    assert nodes[1].get("condition") == CHECKED, "the review waits for a document the script could check"
    assert "condition" not in nodes[0] and "condition" not in nodes[2]
    assert nodes[2].get("run_after_failure") is True


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
    cfg = by_name("positioning_reviewer")
    assert cfg["provider"] == "claude"
    assert "tools" not in cfg, "provider claude refuses temper tool schemas; it uses its own Bash/Read/Write tools"
    prompt = cfg["system_prompt"]
    for rule in ("do not browse the web", "never propose new wording",
                 "Write only state/positioning_grade/review.json", "verify --dry-run", "rubric.md", "stretch test"):
        assert rule in prompt, f"the review prompt lost {rule!r}"


def test_every_template_variable_is_fed_by_the_workflow():
    env = jinja()
    wf = workflow()
    for node in wf["nodes"]:
        fed = set(node.get("input_map") or {})
        for value in (node.get("input_map") or {}).values():
            assert value.startswith("input.") and value.split(".", 1)[1] in wf["inputs"], f"{value} is not an input"
        for template in templates_of(by_name(node["agent"])):
            used = meta.find_undeclared_variables(env.parse(template))
            assert used <= fed | INJECTED, f"{node['agent']} uses {sorted(used - fed - INJECTED)} that the workflow never passes"


def test_the_workflow_outputs_name_fields_check_and_report_print(tmp_path):
    workspace = stage(tmp_path)
    printed_check = check(workspace)
    write_review(workspace, all_ok(check_of(workspace)))
    printed_report = report(workspace)
    printed = {"check": set(printed_check), "report": set(printed_report)}
    for ref in workflow()["outputs"].values():
        node, _, field = ref.partition(".structured.")
        assert field in printed.get(node, set()), f"{ref}: {node} never prints `{field}`"
    stopped = check(stage(tmp_path / "none"), document="nowhere.md")
    assert set(stopped) == printed["check"], "a check that stops prints what a check prints"
    fallback = report(stage(tmp_path / "unset"))
    assert set(fallback) == printed["report"], "report without a grade prints what a grade prints"


def test_departments_names_the_grader_and_its_owner():
    text = (ROOT / "docs" / "departments.md").read_text()
    for name in ("positioning_grade", "positioning_reviewer", "positioning_grade_assets"):
        assert name in text, f"docs/departments.md does not list {name}"


# ---- the frozen benchmark -----------------------------------------------------------------------


def test_the_benchmark_is_frozen_and_the_checker_alone_finds_what_it_says():
    for rel, digest in FROZEN.items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, f"{rel} moved: the bar is frozen"
    evidence, digest = BENCH / "evidence", hashlib.sha256()
    for path in sorted(p for p in evidence.rglob("*") if p.is_file()):
        digest.update(path.relative_to(evidence).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    assert digest.hexdigest() == EVIDENCE_DIGEST, "the evidence folder moved: the bar is frozen"
    assert bench.check() == 0, "a mutation no longer applies, or the checker differs from expected.json"
    version = re.search(r"positioning_grade/\d+", (ASSETS / "rubric.md").read_text()).group(0)
    assert version == checker.RUBRIC_VERSION
    assert checker.FORMAT_VERSION in (ASSETS / "FORMAT.md").read_text()


def test_the_benchmark_builds_ten_cases_that_never_say_what_is_expected(tmp_path):
    first = bench.materialise(tmp_path / "a")
    assert first == bench.materialise(tmp_path / "b"), "the same files every time"
    assert len(first) == 10 and set(first) == set(CASES)
    labels = {c["case"] for c in CASES.values()} | {"mutant", "mutation", "control", "expected", "defect"}
    for key, files in first.items():
        assert {"positioning.md", "positioning.json"} <= set(files)
        assert any(rel.startswith("evidence/") for rel in files)
        for rel in files:
            text = (tmp_path / "a" / key / rel).read_text().lower()
            for label in labels:
                assert not re.search(rf"\b{re.escape(label.lower())}\b", rel.lower()), f"{key}/{rel} names {label}"
            assert "expected.json" not in text and "mutations.json" not in text, f"{key}/{rel} points at the answers"
    evidence = {rel: digest for rel, digest in first[CONTROL].items() if rel.startswith("evidence/")}
    for files in first.values():
        assert {rel: d for rel, d in files.items() if rel.startswith("evidence/")} == evidence, "one evidence folder"


# ---- the checker ---------------------------------------------------------------------------------


def lint(tmp_path, old="", new="", count=1):
    """The checker's (criterion, kind) findings and lead types on C1 with one edit applied."""
    workspace = stage(tmp_path)
    doc = workspace / "positioning.md"
    if old:
        text = doc.read_text()
        assert text.count(old) >= 1, f"C1 no longer holds {old!r}"
        doc.write_text(text.replace(old, new, count))
    result = checker.run_check(doc, workspace / "positioning.json", workspace / "evidence")
    return {(f["criterion"], f["kind"]) for f in result["findings"]}, [lead["type"] for lead in result["leads"]], result


@pytest.mark.parametrize("key", ["q7tn", "h3wd"], ids=["C1", "C2"])
def test_both_controls_are_clean_for_the_checker(tmp_path, key):
    workspace = stage(tmp_path, key)
    result = checker.run_check(workspace / "positioning.md", workspace / "positioning.json", workspace / "evidence")
    assert result["findings"] == [] and result["problems"] == []
    assert result["leads"], "the evidence's limits and plans reach the review as leads"
    assert 3 <= len(result["hierarchy"]["pillars"]) <= 4


EDITS = {
    "number_mismatch": ("fell from 35 minutes to 12. [", "fell from 35 minutes to 10. [", ("P7", "number_mismatch")),
    "quote_not_found": ('nobody reads the notebook."]', 'nobody ever reads the notebook."]', ("P7", "quote_not_found")),
    "missing_file": ('interviews/jonas-bistro.md: "Prep lists go out', 'interviews/jonas.md: "Prep lists go out',
                     ("P7", "missing_file")),
    "uncited": ("\n## 3. Value and proof", "- Kettlemark also tracks deliveries.\n\n## 3. Value and proof",
                ("P7", "uncited")),
    "hype_word": ("- Prep lists in minutes:", "- Revolutionary prep lists in minutes:", ("P8", "hype_word")),
    "long_sentence": ("\n## 3. Value and proof",
                      "- " + " ".join(["kitchens"] * 34) + " plan prep by hand. (assumption)\n\n## 3. Value and proof",
                      ("P8", "long_sentence")),
    "section_title": ("## 5. Market category", "## 5. Category", ("P5", "section_title")),
    "json_mismatch": ("### Pillar 1: Throw out less food", "### Pillar 1: Throw out much less food",
                      ("P6", "json_mismatch")),
}


@pytest.mark.parametrize("name", sorted(EDITS))
def test_the_checker_finds_each_kind_of_format_defect(tmp_path, name):
    old, new, want = EDITS[name]
    found, _, _ = lint(tmp_path, old, new)
    assert found == {want}, f"{name}: expected only {want}, got {sorted(found)}"


def test_a_quote_shortened_with_dots_is_a_lead_not_a_defect(tmp_path):
    full = '"Every morning I write the prep list on the whiteboard by the walk-in. I guess from what we sold last week."'
    found, leads, _ = lint(tmp_path, full, '"Every morning I write the prep list ... from what we sold last week."')
    assert found == set() and "elided_quote" in leads
    found, _, _ = lint(tmp_path / "short", full, '"Every morning ... last week."')
    assert found == {("P7", "quote_not_found")}, "a part kept around ... needs three words"


def test_the_checker_reads_numbers_the_way_a_reader_does():
    assert checker.numbers_in("$1,200 a month, 7.90% and 12x") == ["1200", "7.9", "12"]
    assert checker.numbers_in("twelve of the fourteen", words=True) == ["12", "14"]
    assert checker.Doc("f", "one  “two”\nthree").find('one "two" three') == 1


# ---- the check and report steps ------------------------------------------------------------------


def test_a_sound_document_with_a_passing_review_passes(tmp_path):
    workspace = stage(tmp_path)
    assert check(workspace)["status"] == "checked"
    setup = json.loads((grade_dir(workspace) / "setup.json").read_text())
    assert setup["evidence"] == "evidence" and setup["evidence_from"] == "Evidence: line"
    for name in ("check_positioning.py", "rubric.md", "FORMAT.md"):
        assert (grade_dir(workspace) / name).read_bytes() == (ASSETS / name).read_bytes()
    write_review(workspace, all_ok(check_of(workspace)))
    out = report(workspace)
    assert out["quality_status"] == "pass" and set(out["criteria"].values()) == {"pass"}
    quality = quality_of(workspace)
    assert quality["integrity"]["unchanged"] and quality["rubric"] == checker.RUBRIC_VERSION
    assert (grade_dir(workspace) / "quality.md").read_text().startswith("# Positioning quality: PASS")


def test_an_input_the_run_did_not_give_is_empty_not_the_text_none(tmp_path):
    """The server passes an input the run did not give as None (signal_grade's run 1b7aef1a)."""
    workspace = stage(tmp_path)
    assert check(workspace, document=None, positioning_json=None, evidence=None)["status"] == "checked"
    setup = json.loads((grade_dir(workspace) / "setup.json").read_text())
    assert setup["document"] == "positioning.md" and setup["positioning_json"] == "positioning.json"
    nested = stage(tmp_path / "nested")
    (nested / "doc").mkdir()
    for name in ("positioning.md", "positioning.json", "evidence"):
        (nested / name).rename(nested / "doc" / name)
    text = (nested / "doc" / "positioning.md").read_text().replace("Evidence: evidence\n", "")
    (nested / "doc" / "positioning.md").write_text(text)
    assert check(nested, document="doc/positioning.md")["status"] == "checked"
    assert json.loads((grade_dir(nested) / "setup.json").read_text())["evidence"] == "doc/evidence"


def test_the_check_stops_without_a_document_or_evidence_or_in_a_used_folder(tmp_path):
    assert check(stage(tmp_path / "a"), document="nowhere.md")["status"] == "not_checked"
    assert check(stage(tmp_path / "b"), evidence="nowhere")["status"] == "not_checked"
    assert check(stage(tmp_path / "c"), document="/etc/hostname")["status"] == "not_checked"
    assert check(stage(tmp_path / "d"), document="../x/positioning.md")["status"] == "not_checked"
    used = stage(tmp_path / "e")
    assert check(used)["status"] == "checked"
    again = check(used)
    assert again["status"] == "not_checked" and "fresh workspace" in again["problems"][0]


def test_the_report_counts_only_findings_it_can_verify(tmp_path):
    workspace = stage(tmp_path)
    check(workspace)
    bad = [
        {**FINDING, "id": "R2", "passages": [{"file": "positioning.md", "text": "words that are not there at all"}]},
        {**FINDING, "id": "R3", "passages": [{"file": "evidence/interviews/rosa-taqueria.md",
                                               "text": "Every morning I write the prep list"}]},
        {**FINDING, "id": "R4", "absent": "The whiteboard"},
        {**FINDING, "id": "S9"},
        {**FINDING, "id": "R5", "criterion": "Q1"},
        {**FINDING, "id": "R6", "passages": [{"file": "elsewhere.md", "text": WHITEBOARD}]},
    ]
    write_review(workspace, all_ok(check_of(workspace), findings=bad))
    out = report(workspace)
    quality = quality_of(workspace)
    assert {f["id"] for f in quality["unverified"]} == {"R2", "R3", "R4", "S9", "R5", "R6"}
    assert out["quality_status"] == "pass" and out["unverified"] == 6, "unverified findings never count"


def test_a_verified_material_finding_sets_revise_and_a_minor_one_does_not(tmp_path):
    workspace = stage(tmp_path)
    check(workspace)
    minor = {**FINDING, "id": "R2", "criterion": "P3", "severity": "minor"}
    write_review(workspace, all_ok(check_of(workspace), findings=[FINDING, minor], P1="revise"))
    out = report(workspace)
    assert out["quality_status"] == "revise" and out["criteria"]["P1"] == "revise"
    assert out["criteria"]["P3"] == "pass" and out["findings"] == 1
    assert quality_of(workspace)["criteria"]["P3"]["minor"] == ["R2"]
    case = CASES["z5kc"]  # M1: P1 is labelled; its marker must sit in a counted document passage
    assert scorer.marked_findings({**case, "markers": ["the chef writes the prep list"]}, quality_of(workspace)) == ["R1"]


def test_unresolved_leads_unsupported_revise_and_a_spent_account_are_unknown(tmp_path):
    workspace = stage(tmp_path)
    check(workspace)
    review = all_ok(check_of(workspace), P2="revise")
    review["leads"] = review["leads"][1:]
    write_review(workspace, review)
    out = report(workspace)
    assert out["quality_status"] == "unknown"
    assert out["criteria"]["P2"] == "unknown", "revise with no verified finding is not a revise"
    first_lead = check_of(workspace)["leads"][0]
    assert out["criteria"][first_lead["criterion"]] == "unknown", "an unresolved lead leaves its criterion unknown"
    (grade_dir(workspace) / "review.json").write_text("You've hit your usage limit. Try again later.")
    assert set(report(workspace)["criteria"].values()) == {"unknown"}


def test_a_grade_from_another_run_or_none_is_unknown(tmp_path):
    workspace = stage(tmp_path)
    check(workspace, run_id="run-1")
    write_review(workspace, all_ok(check_of(workspace)))
    other = report(workspace, run_id="run-2")
    assert other["quality_status"] == "unknown" and "another run" in other["problems"][0]
    assert report(stage(tmp_path / "none"))["quality_status"] == "unknown"


def test_grading_never_changes_the_document_and_says_so_if_it_did(tmp_path):
    workspace = stage(tmp_path)
    check(workspace)
    write_review(workspace, all_ok(check_of(workspace)))
    doc = workspace / "positioning.md"
    doc.write_text(doc.read_text() + "\nAn edit made while grading.\n")
    out = report(workspace)
    assert out["quality_status"] == "unknown" and not quality_of(workspace)["integrity"]["unchanged"]
    assert any("changed during grading" in p for p in out["problems"])


# ---- the score --------------------------------------------------------------------------------------


def quality(statuses, findings=(), unchanged=True):
    return {"status": "revise" if "revise" in statuses.values() else "pass", "files": {"doc": "positioning.md"},
            "criteria": {c: {"status": statuses.get(c, "pass")} for c in CRITERIA}, "findings": list(findings),
            "integrity": {"unchanged": unchanged}}


def test_score_applies_the_matching_rule():
    m1 = CASES["z5kc"]
    marked = {"id": "R1", "criterion": m1["labelled"], "severity": "material", "verified": True,
              "passages": [{"file": "positioning.md", "text": m1["markers"][0]}]}
    assert scorer.score_case("z5kc", quality({"P1": "revise"}, [marked]))["ok"]
    assert not scorer.score_case("z5kc", quality({"P1": "revise"}, [{**marked, "severity": "minor"}]))["ok"]
    assert not scorer.score_case("z5kc", quality({"P1": "revise"}, [{**marked, "passages": [
        {"file": "positioning.md", "text": "somewhere else"}]}]))["ok"], "the finding must quote the planted defect"
    assert scorer.score_case("z5kc", quality({"P1": "revise", "P3": "revise"}, [marked]))["ok"], "one false revise"
    two = scorer.score_case("z5kc", quality({"P1": "revise", "P3": "revise", "P5": "revise"}, [marked]))
    assert not two["ok"] and two["false_revise"] == ["P3", "P5"]
    assert scorer.score_case(CONTROL, quality({}))["ok"]
    assert not scorer.score_case(CONTROL, quality({"P7": "revise"}))["ok"]
    assert not scorer.score_case(CONTROL, quality({}, unchanged=False))["ok"]
    assert not scorer.score_case(CONTROL, None)["ok"]
