"""The fit and revenue evidence workflow (configs/workflows/pmf_evidence.yaml, product role) fits together.

It measures the mission's product-market-fit indicators for one product from a params file and four
CSV exports, and reports them apart: the survey's very-disappointed share, retention by cohort and
period, customer accounts paying the target price after refunds, and revenue (queue #13). Its
configs: setup, the model step, the check and finalize run in that order; the model step and the
check wait for setup to say measured; finalize runs on every path; script steps parse under /bin/sh;
the model step keeps Claude Code's own tools; every template variable is fed. Its kit
(pmf_evidence_assets/pmf_kit.py): every product-specific value is a required parameter with no
default; the nine fixed synthetic cases (benchmark/) measure exactly as expected.json says, which a
separately written calculation (independent.py) agrees with; the interpretation check catches each
planted defect; a failed check withholds the interpretation; the scorer (score.py) passes a sound
run and catches a wrong number or a fit claim. No model and no network: every input is synthetic.
"""

import ast
import copy
import csv
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
AGENTS = sorted(AGENTS_DIR.glob("pmf_evidence_*.yaml"))
ASSETS = AGENTS_DIR / "pmf_evidence_assets"
WORKFLOW = ROOT / "configs" / "workflows" / "pmf_evidence.yaml"
BENCH = Path(__file__).resolve().parent / "benchmark"
INJECTED = {"workspace_path", "run_id"}  # the agents add these to every template
ORDER = ["pmf_evidence_setup", "pmf_evidence_interpret", "pmf_evidence_check", "pmf_evidence_finalize"]
GATED = {"interpret", "check"}
MEASURED = {"source": "setup.structured.status", "operator": "equals", "value": "measured"}
STAGED = ("pmf_kit.py", "data_dictionary.md", "interpretation_contract.md")


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


kit = load(ASSETS / "pmf_kit.py", "pmf_evidence_kit")
construct = load(BENCH / "construct.py", "pmf_evidence_construct")
independent = load(BENCH / "independent.py", "pmf_evidence_independent")
scorer = load(BENCH / "score.py", "pmf_evidence_score")
EXPECTED = json.loads((BENCH / "expected.json").read_text())
CASES = {c["case"]: c for c in EXPECTED["cases"]}
MEASURED_CASES = [name for name, c in CASES.items() if c["expected_final_status"] != "blocked"]


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    folder = tmp_path_factory.mktemp("pmf_cases")
    construct.materialise(folder)
    return folder


def step(name, workspace, **values):
    """A script step rendered the way the script agent renders it and run by /bin/sh."""
    cfg = by_name(name)
    stash = _ValueStash()
    script = jinja(stash).from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render(
        workspace_path=str(workspace), **values)
    env = {**os.environ, **stash.env, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=60, cwd=workspace, env=env)


def last_json(stdout):
    return json.loads([line for line in stdout.splitlines() if line.startswith("{")][-1])


def setup_case(tmp_path, fixtures, case):
    """The real setup step on one case, staged as the launcher stages a server run."""
    workspace = tmp_path / "ws"
    shutil.copytree(ASSETS, workspace / "_assets")
    shutil.copytree(fixtures / case, workspace / "_case")
    done = step("pmf_evidence_setup", workspace, params_path=str(workspace / "_case" / "params.json"),
                data_dir=str(workspace / "_case"), assets_dir=str(workspace / "_assets"))
    assert done.returncode == 0, done.stderr
    return workspace, last_json(done.stdout)


def leaves(spec, prefix=""):
    for key, value in spec.items():
        if isinstance(value, dict):
            yield from leaves(value, prefix + key + ".")
        else:
            yield prefix + key


def codes(problems):
    return [p.split(" ", 1)[0] for p in problems]


# ---- the configs ---------------------------------------------------------------------------------


def test_the_workflow_runs_setup_the_model_step_the_check_and_finalize():
    assert {p.stem for p in AGENTS} == {agent(p)["name"] for p in AGENTS}, "each agent file is named after its agent"
    nodes = workflow()["nodes"]
    assert [n["agent"] for n in nodes] == ORDER
    assert set(ORDER) == {p.stem for p in AGENTS}, "the workflow runs every pmf_evidence agent"
    for before, after in zip(nodes, nodes[1:], strict=False):
        assert after["depends_on"] == [before["name"]], "one step at a time, in order"
    for node in nodes:
        if node["name"] in GATED:
            assert node.get("condition") == MEASURED, f"{node['name']} must wait for an input setup measured"
        else:
            assert "condition" not in node, f"{node['name']} runs on every path"
    assert nodes[-1]["name"] == "finalize" and nodes[-1].get("run_after_failure") is True


def test_the_targets_and_data_are_required_inputs_with_no_default():
    inputs = workflow()["inputs"]
    for name in ("params_path", "data_dir"):
        assert inputs[name]["required"] is True and "default" not in inputs[name]
    assert inputs["assets_dir"]["default"] == "/app/configs/agents/pmf_evidence_assets"


@pytest.mark.parametrize("path", [p for p in AGENTS if agent(p).get("type") == "script"], ids=lambda p: p.stem)
def test_every_script_step_parses_under_sh(path):
    cfg = agent(path)
    script = jinja().from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render()
    done = subprocess.run(["sh", "-n", "-c", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, f"{path.name} does not parse under /bin/sh: {done.stderr.strip()}"


@pytest.mark.parametrize("path", [*AGENTS, WORKFLOW], ids=lambda p: p.stem)
def test_no_file_holds_the_config_stores_env_syntax(path):
    assert "${" not in path.read_text(), "the config store would substitute it as an env var"


@pytest.mark.parametrize("path", [p for p in AGENTS if agent(p).get("type") != "script"], ids=lambda p: p.stem)
def test_the_model_step_keeps_claude_codes_own_tools(path):
    cfg = agent(path)
    assert cfg["provider"] == "claude"
    assert "tools" not in cfg, "provider claude refuses temper tool schemas; it uses its own Bash/Read/Write tools"


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


def test_the_product_launcher_starts_pmf_evidence_as_a_live_workflow():
    """docs/product-runs.md starts it by name; the launcher refuses a name outside its LIVE set."""
    tree = ast.parse((ROOT / "configs" / "product" / "bin" / "server_run.py").read_text())
    live = next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["LIVE"])
    assert "pmf_evidence" in live
    assert "start.sh $JOB pmf_evidence" in (ROOT / "docs" / "product-runs.md").read_text()


def test_every_kit_file_has_a_product_ownership_row():
    section = (ROOT / "docs" / "departments.md").read_text().split("### product (", 1)[1].split("\n### ", 1)[0]
    assets = sorted(p for p in ASSETS.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    for path in [WORKFLOW, *AGENTS, *assets]:
        rel = path.relative_to(ROOT / "configs").as_posix()
        assert f"| `{rel}` |" in section, f"{rel} has no product ownership row"
    assert int(section.split(")", 1)[0]) == section.count("\n| `"), "the product heading counts its rows"


def test_the_workflow_outputs_name_fields_setup_and_finalize_print(tmp_path, fixtures):
    workspace, setup_out = setup_case(tmp_path, fixtures, "P1")
    final = step("pmf_evidence_finalize", workspace)
    assert final.returncode == 0, final.stderr
    printed = {"setup": set(setup_out), "finalize": set(last_json(final.stdout))}
    for ref in workflow()["outputs"].values():
        node, _, field = ref.partition(".structured.")
        assert field in printed.get(node, set()), f"{ref}: {node} never prints `{field}`"
    fallback = re.search(r"echo '(\{.*\})'", by_name("pmf_evidence_finalize")["script_template"])
    assert fallback, "finalize no longer says what happened when setup did not finish"
    assert set(json.loads(fallback.group(1))) == printed["finalize"], "the fallback prints what finalize prints"


# ---- the fixed benchmark ------------------------------------------------------------------------


def test_the_benchmark_is_fixed_and_never_tells_a_run_what_is_expected(tmp_path, fixtures):
    assert construct.materialise(tmp_path / "again") == construct.materialise(fixtures), "the same bytes every time"
    assert sorted(CASES) == ["D1", "E1", "F1", "I1", "L1", "N1", "P1", "R1", "S1"]
    for name, case in CASES.items():
        folder = fixtures / case["dir"]
        assert {p.name for p in folder.iterdir()} == set(case["sha256"])
        for filename, digest in case["sha256"].items():
            assert scorer.sha256(folder / filename) == digest, f"{name}/{filename} is not the frozen fixture"
            text = (folder / filename).read_text().lower()
            for tell in ("expected", "planted", "should", "pmf_evidence.benchmark"):
                assert tell not in text, f"{name}/{filename} says {tell!r}"
        params = json.loads((folder / "params.json").read_text())
        if name != "P1":
            assert params["data_label"] == "synthetic", f"{name} is made up and must say so"


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_kit_measures_each_case_as_expected(name, fixtures):
    case = CASES[name]
    folder = fixtures / case["dir"]
    _, problems, metrics, _ = kit.evaluate(folder / "params.json", folder)
    if case["expected_final_status"] == "blocked":
        assert metrics is None
        assert sorted([p["code"], p["field"]] for p in problems) == case["setup_problems"]
        return
    assert problems == []
    fails = []
    scorer.check_metrics(case, metrics, fails)
    assert fails == []


@pytest.mark.parametrize("name", MEASURED_CASES)
def test_a_separately_written_calculation_agrees_with_expected(name, fixtures):
    case = CASES[name]
    got = independent.compute(fixtures / case["dir"])
    for key in ("expected_final_status", "verdict", "files", "survey", "retention", "payment", "revenue"):
        assert got[key] == case[key], f"{name}: independent.py differs from expected.json on {key}"


# ---- the input contract ---------------------------------------------------------------------------


def test_an_all_null_params_template_lists_every_required_parameter():
    template = json.loads((ASSETS / "templates" / "params.json").read_text())
    found = sorted([p["code"], p["field"]] for p in kit.validate_params(template))
    assert found == sorted(["missing_param", f] for f in leaves(kit.PARAMS) if f != "schema")


@pytest.mark.parametrize("field", list(leaves(kit.PARAMS)))
def test_each_parameter_left_out_or_null_blocks_with_its_own_problem_and_no_default(field, fixtures):
    base = json.loads((fixtures / "N1" / "params.json").read_text())
    *path, last = field.split(".")
    for value in ("left out", None):
        params = copy.deepcopy(base)
        holder = params
        for part in path:
            holder = holder[part]
        if value is None:
            holder[last] = None
        else:
            del holder[last]
        assert [[p["code"], p["field"]] for p in kit.validate_params(params)] == [["missing_param", field]]


def test_the_survey_bar_is_the_missions_fixed_40_percent():
    assert kit.SURVEY_BAR == kit.Fraction(2, 5)
    assert "40" not in json.dumps(kit.PARAMS), "the 40% bar is not a parameter a run could lower"


def test_missing_files_columns_and_folders_block_before_anything_is_measured(tmp_path, fixtures):
    folder = tmp_path / "case"
    shutil.copytree(fixtures / "N1", folder)
    (folder / "survey.csv").unlink()
    with open(folder / "payments.csv") as handle:
        rows = list(csv.reader(handle))
    with open(folder / "payments.csv", "w", newline="") as handle:
        csv.writer(handle).writerows([row[:-1] for row in rows])
    (folder / "users.csv").write_text("")
    _, problems, metrics, _ = kit.evaluate(folder / "params.json", folder)
    assert metrics is None
    found = {(p["code"], p["field"]) for p in problems}
    assert ("missing_file", "survey.csv") in found
    assert any(code == "missing_column" and field.startswith("payments.csv") for code, field in found)
    assert any(code == "unreadable_file" and field.startswith("users.csv") for code, field in found)


def test_setup_blocks_a_missing_data_folder_and_names_it(tmp_path, fixtures):
    workspace = tmp_path / "ws"
    shutil.copytree(ASSETS, workspace / "_assets")
    shutil.copytree(fixtures / "N1", workspace / "_case")
    done = step("pmf_evidence_setup", workspace, params_path=str(workspace / "_case" / "params.json"),
                data_dir=str(workspace / "nowhere"), assets_dir=str(workspace / "_assets"))
    assert done.returncode == 0, done.stderr
    out = last_json(done.stdout)
    assert out["status"] == "blocked" and any(p.startswith("missing_input") for p in out["problems"])


def test_empty_exports_give_undefined_shares_and_no_data_not_a_failure(fixtures):
    _, _, metrics, _ = kit.evaluate(fixtures / "E1" / "params.json", fixtures / "E1")
    assert metrics["survey"]["share_pct"] is None and metrics["survey"]["interval_pct"] is None
    for section in kit.INDICATORS:
        assert metrics[section]["status"] == "insufficient_evidence" and metrics[section]["reasons"] == ["no_data"]


def test_censored_periods_leave_the_denominator_and_never_count_as_lost(fixtures):
    _, _, metrics, _ = kit.evaluate(fixtures / "N1" / "params.json", fixtures / "N1")
    retention = metrics["retention"]
    assert retention["users"] == 60
    assert list(retention["curve"][8]) == [8, 30, 16], "N1's later cohort is not observed for period 8 yet"
    _, _, metrics, _ = kit.evaluate(fixtures / "I1" / "params.json", fixtures / "I1")
    assert metrics["retention"]["status"] == "insufficient_evidence"
    assert metrics["retention"]["reasons"] == ["too_few_periods"]
    assert metrics["retention"]["adequate_on"] == CASES["I1"]["retention"]["adequate_on"]


def test_the_report_and_facts_show_retention_by_cohort_and_period(fixtures):
    """Every cohort's period shares, with numerator and denominator, so a cohort comparison is traceable."""
    params, _, metrics, rejected = kit.evaluate(fixtures / "L1" / "params.json", fixtures / "L1")
    facts = kit.build_facts(params, metrics)
    cohorts = next(f["text"] for f in facts if f["about"] == "retention cohorts")
    report = kit.report(params, metrics, facts, rejected, None, "revise", [])
    assert "| Period | 2026-01 (30 users) | 2026-02 (30 users) |" in report
    assert "| 7 | 16 of 30 (53.3%) | 16 of 30 (53.3%) |" in report
    assert "| 11 | 7 of 30 (23.3%) | not yet observed |" in report
    assert "2026-01: 30 users, 12 full periods observed: period 0: 30 of 30 (100.0%)" in cohorts
    assert "period 11: 7 of 30 (23.3%); 2026-02: 30 users, 8 full periods observed" in cohorts
    assert cohorts.endswith("period 7: 16 of 30 (53.3%).")
    for co in metrics["retention"]["cohorts"]:
        for k, n, a in co["curve"]:
            assert f"period {k}: {a} of {n} (" in cohorts


def test_counts_take_the_singular_for_one(fixtures):
    params, _, metrics, _ = kit.evaluate(fixtures / "F1" / "params.json", fixtures / "F1")
    sample = next(f["text"] for f in kit.build_facts(params, metrics) if f["about"] == "survey sample")
    assert "at least 1 trip_booked event in the 365 days" in sample
    params, _, metrics, _ = kit.evaluate(fixtures / "D1" / "params.json", fixtures / "D1")
    texts = [f["text"] for f in kit.build_facts(params, metrics)]
    assert any("1 exact duplicate row dropped" in t for t in texts)
    assert any("1 repeat answer set aside" in t for t in texts)
    assert kit.count(1, "row") == "1 row" and kit.count(0, "row") == "0 rows" and kit.count(2, "row") == "2 rows"


def test_a_share_said_to_hold_over_periods_must_be_that_share_in_each(fixtures):
    """In N1 the 2026-01 cohort dips to 50.0% in period 10, so "53.3% from period 3 on" is wrong for it."""
    retention = kit.evaluate(fixtures / "N1" / "params.json", fixtures / "N1")[2]["retention"]
    wrong = {
        "2026-01 holds at 53.3% from period 3 to period 11.": "periods 3 to 11 of cohort 2026-01, but period 10 is "
                                                             "50.0% (15 of 30)",
        "2026-01 and 2026-02 each hold at 53.3% from period 3.": "period 3 on of cohort 2026-01, but period 10",
        "Both cohorts go 100.0%, 80.0%, 80.0%, then 53.3% from period 3 on.": "period 3 on of the curve, but period "
                                                                              "10 is 50.0% (15 of 30)",
        "It drops to 53.3% in period 3, then holds at 53.3% through period 11.": "periods 3 to 11 of the curve",
        "2026-02 holds at 53.3% from period 3 to period 9.": "period 8 is not observed; period 9 is not observed",
        "Periods 9 and 10 hold at 16 of 30 (53.3%).": "periods 9 and 10 of the curve, but period 10 is 50.0%",
    }
    for text, said in wrong.items():
        found = kit.span_claims(text, retention)
        assert len(found) == 1 and said in found[0], (text, found)
    right = ["2026-02 holds at 53.3% from period 3 to period 7; 2026-01 dips to 50.0% in period 10.",
             "It drops to 53.3% in period 3, then holds at 53.3% through period 11 (50.0% in period 10).",
             "It is 80.0% in periods 1 and 2, then holds at 53.3% through period 9.",
             "The share went from 53.3% to 50.0% over periods 9 to 10.",
             "It held at 53.3% between period 3 and period 9, and the last share is 53.3%.",
             "From period 0: 60 of 60 (100.0%) to period 1: 48 of 60 (80.0%)."]
    for text in right:
        assert kit.span_claims(text, retention) == [], text
    rhythm = kit.evaluate(fixtures / "F1" / "params.json", fixtures / "F1")[2]["retention"]
    assert kit.span_claims("Both sit at 28 of 40 (70.0%) in every period after period 0.", rhythm) == []
    assert kit.span_claims("Both sit at 28 of 40 (70.0%) in every period from period 0.", rhythm)


def test_the_data_dictionary_and_templates_cover_every_parameter_and_column():
    dictionary = (ASSETS / "data_dictionary.md").read_text()
    for field in leaves(kit.PARAMS):
        assert f"`{field}`" in dictionary or f"`{field.split('.')[-1]}`" in dictionary, f"{field} is not described"
    for name, (_, columns) in kit.FILES.items():
        header = (ASSETS / "templates" / f"{name}.csv").read_text().strip()
        assert header.split(",") == list(columns), f"templates/{name}.csv is not the {name} export's header"
        assert f"`{','.join(columns)}`" in dictionary, f"the {name} export's columns are not described"
    survey = (ASSETS / "survey_template.md").read_text()
    assert "How would you feel if you could no longer use" in survey
    assert all(answer.capitalize() in survey for answer in kit.ANSWERS)


# ---- the interpretation check -------------------------------------------------------------------

S1_READING = {
    "schema": "pmf_evidence.interpretation/1",
    "summary": [
        {"text": "Synthetic data: nothing here is evidence about any product. Only the survey indicator is met; "
                 "retention and payment are not judged yet, so the verdict is fit_not_shown and the survey alone "
                 "never shows product-market fit.", "facts": ["F17"]},
    ],
    "indicators": {
        "survey": {"status": "met", "statements": [
            {"text": "18 of 40 eligible respondents (45.0%) were very disappointed, at the 40% bar with the minimum "
                     "40 eligible respondents; the 95% interval runs from 30.7% to 60.2%.", "facts": ["F8"]}]},
        "retention": {"status": "insufficient_evidence", "statements": [
            {"text": "Only 3 adequate periods are observed and 6 are needed; period 6 can be judged on 2026-03-22 at "
                     "the earliest.", "facts": ["F13"]}]},
        "payment": {"status": "insufficient_evidence", "statements": [
            {"text": "4 accounts paid the target price so far; the horizon runs to 2026-04-30 and 10 are needed.",
             "facts": ["F14"]}]},
        "revenue": {"status": "insufficient_evidence", "statements": [
            {"text": "Net collected 189.12 against a 2000.00 target; 3 promises worth 147.00 are not money.",
             "facts": ["F15", "F16"]}]},
    },
    "data_quality": [],
    "next_tests": [
        {"id": "T1", "indicator": "retention", "kind": "wait_and_remeasure",
         "test": "Re-run the kit on an export covering to 2026-03-22.",
         "pass_rule": "At least 6 adequate periods; drop at most 5 percentage points over the last 3; last at least "
                      "30.0%.", "when": "2026-03-22", "needs_owner_approval": False, "facts": ["F13"]},
        {"id": "T2", "indicator": "payment", "kind": "wait_and_remeasure", "test": "Re-run after the horizon ends.",
         "pass_rule": "At least 10 accounts at 49.00 USD after refunds.", "when": "after 2026-04-30",
         "needs_owner_approval": False, "facts": ["F14"]},
        {"id": "T3", "indicator": "revenue", "kind": "wait_and_remeasure", "test": "Re-run after the horizon ends.",
         "pass_rule": "Net collected at least 2000.00 USD.", "when": "after 2026-04-30", "needs_owner_approval": False,
         "facts": ["F15"]},
    ],
    "limitations": [],
}


@pytest.fixture
def s1(tmp_path, fixtures):
    workspace, out = setup_case(tmp_path, fixtures, "S1")
    assert out["status"] == "measured"
    return workspace


def write_reading(workspace, reading):
    (workspace / "state" / "pmf" / "interpretation.json").write_text(json.dumps(reading, indent=1))


def check_and_finalize(workspace):
    check = step("pmf_evidence_check", workspace)
    assert check.returncode == 0, check.stderr
    final = step("pmf_evidence_finalize", workspace)
    assert final.returncode == 0, final.stderr
    return last_json(check.stdout), last_json(final.stdout)


def test_a_sound_reading_ends_reported_and_the_scorer_passes_it(s1):
    write_reading(s1, S1_READING)
    check, final = check_and_finalize(s1)
    assert check == {"status": "pass", "problems": []}
    assert final["final_status"] == "reported" and final["verdict"] == "fit_not_shown"
    report = (s1 / "state" / "pmf" / "REPORT.md").read_text()
    assert EXPECTED["report_phrases"]["fit_rule"] in report and EXPECTED["report_phrases"]["synthetic"] in report
    assert scorer.score("S1", s1) == []


def plant(change):
    def apply(reading):
        reading = copy.deepcopy(reading)
        change(reading)
        return reading
    return apply


PLANTED = {
    "untraced_number": plant(lambda r: r["indicators"]["survey"]["statements"][0].update(
        text="18 of 41 eligible respondents were very disappointed.")),
    "unknown_fact": plant(lambda r: r["indicators"]["payment"]["statements"][0].update(facts=["F99"])),
    "fit_claim": plant(lambda r: r["summary"].append(
        {"text": "This product has reached product-market fit.", "facts": ["F17"]})),
    "synthetic": plant(lambda r: r["summary"][0].update(text="Only the survey indicator is met.")),
    "status": plant(lambda r: r["indicators"]["retention"].update(status="not_met")),
    "coverage": plant(lambda r: r.update(next_tests=r["next_tests"][1:])),
    "owner_approval": plant(lambda r: r["next_tests"][0].update(kind="survey")),
    "when": plant(lambda r: r["next_tests"][0].update(when="later")),
    "order": plant(lambda r: r["next_tests"].insert(0, {
        "id": "T4", "indicator": "survey", "kind": "analysis", "test": "Re-read the survey answers.",
        "pass_rule": "At least 40% very disappointed.", "when": "now", "needs_owner_approval": False,
        "facts": ["F8"]})),
    "limit_text": plant(lambda r: r["limitations"].append(
        {"text": "You've hit your limit before finishing.", "facts": ["F17"]})),
    "span_claim": plant(lambda r: r["indicators"]["retention"]["statements"].append(
        {"text": "The share holds at 100.0% from period 0 to period 3.", "facts": ["F10"]})),
    "shape": plant(lambda r: r.update(verdict="fit")),
}


@pytest.mark.parametrize("code", sorted(PLANTED))
def test_the_check_catches_each_planted_defect(s1, code):
    write_reading(s1, PLANTED[code](S1_READING))
    check, final = check_and_finalize(s1)
    assert check["status"] == "revise" and code in codes(check["problems"]), check["problems"]
    assert final["final_status"] == "revise"


def test_a_failed_check_withholds_the_reading_and_keeps_the_measurements(s1):
    write_reading(s1, PLANTED["fit_claim"](S1_READING))
    _, final = check_and_finalize(s1)
    report = (s1 / "state" / "pmf" / "REPORT.md").read_text()
    assert final["final_status"] == "revise" and final["verdict"] == "fit_not_shown"
    kept = [line for line in report.splitlines() if not line.startswith("- fit_claim")]
    assert not any("reached product-market fit" in line for line in kept), "only the problem line may quote it"
    assert "## Interpretation" not in report and "| eligible respondents | 40 |" in report


def test_a_missing_model_step_ends_revise_not_reported(s1):
    final = step("pmf_evidence_finalize", s1)
    out = last_json(final.stdout)
    assert out["final_status"] == "revise"
    assert any(p.startswith("missing interpretation") for p in out["problems"])
    assert any(p.startswith("missing check") for p in out["problems"])


def test_a_blocked_setup_ends_blocked_without_a_model_step(tmp_path, fixtures):
    workspace, out = setup_case(tmp_path, fixtures, "P1")
    assert out["status"] == "blocked"
    assert sorted(p.split(":")[0].split(" ", 1) for p in out["problems"]) == CASES["P1"]["setup_problems"]
    final = last_json(step("pmf_evidence_finalize", workspace).stdout)
    assert final["final_status"] == "blocked" and final["verdict"] == "not_measured"
    assert not (workspace / "state" / "pmf" / "metrics.json").exists()
    assert scorer.score("P1", workspace) == []


def test_setup_refuses_a_used_workspace_and_finalize_then_reports_blocked(tmp_path, fixtures):
    workspace, _ = setup_case(tmp_path, fixtures, "S1")
    again = step("pmf_evidence_setup", workspace, params_path=str(workspace / "_case" / "params.json"),
                 data_dir=str(workspace / "_case"), assets_dir=str(workspace / "_assets"))
    assert again.returncode != 0 and "fresh workspace" in again.stderr
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    final = last_json(step("pmf_evidence_finalize", fresh).stdout)
    assert final["final_status"] == "blocked" and final["problems"][0].startswith("setup did not finish")


# ---- the scorer -----------------------------------------------------------------------------------


def test_the_scorer_catches_a_wrong_number_and_a_fit_claim(s1):
    write_reading(s1, S1_READING)
    check_and_finalize(s1)
    pmf = s1 / "state" / "pmf"
    metrics = json.loads((pmf / "metrics.json").read_text())
    metrics["retention"]["adequate_periods"] = 4
    (pmf / "metrics.json").write_text(json.dumps(metrics))
    report = pmf / "REPORT.md"
    report.write_text(report.read_text() + "\nThe product has product-market fit.\n")
    fails = scorer.score("S1", s1)
    assert any(f.startswith("B1: retention.adequate_periods") for f in fails)
    assert any(f.startswith("B4: fit claims in REPORT.md") for f in fails)


def test_the_scorer_rejects_a_run_on_inputs_other_than_the_frozen_fixture(s1):
    write_reading(s1, S1_READING)
    check_and_finalize(s1)
    users = s1 / "state" / "pmf" / "input" / "data" / "users.csv"
    users.write_text(users.read_text() + "u-extra,a-extra,2026-02-01\n")
    assert "inputs: users.csv is not the frozen fixture (sha256 differs)" in scorer.score("S1", s1)
