"""The product-shaping workflow (configs/workflows/shape_mvp.yaml, product role) fits together.

It turns an evidenced opportunity into a bounded first-version pitch (Shape Up: problem, appetite,
solution, rabbit holes, no-gos) with checkable success criteria and a verification plan, keeping
every open assumption (queue #11). Its configs: setup, the three model steps, the check, the grade
and finalize run in that order; the model steps, the check and the grade wait for setup to say
ready_to_shape; finalize runs on every path; script steps parse under /bin/sh; the model steps keep
Claude Code's own tools; every template variable is fed. Its checker (shape_mvp_assets/check_shape.py):
the input contract blocks each missing critical input and says what would unblock it, and turns
missing owner values into owner-input gaps; the pitch checks pass a valid pitch and catch each
planted defect; finalize takes the most conservative status. The fixed benchmark (benchmark/)
materialises seven cases whose inputs never say what is expected of them. No model and no network:
every input is synthetic or a saved benchmark file.
"""

import copy
import json
import os
import re
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
AGENTS = sorted(AGENTS_DIR.glob("shape_mvp_*.yaml"))
ASSETS = AGENTS_DIR / "shape_mvp_assets"
WORKFLOW = ROOT / "configs" / "workflows" / "shape_mvp.yaml"
BENCH = Path(__file__).resolve().parent / "benchmark"
INJECTED = {"workspace_path", "run_id"}  # the agents add these to every template
ORDER = ["shape_mvp_setup", "shape_mvp_draft", "shape_mvp_critique", "shape_mvp_revise", "shape_mvp_check",
         "shape_mvp_grade", "shape_mvp_finalize"]
GATED = {"draft", "critique", "revise", "check", "grade"}
READY = {"source": "setup.structured.status", "operator": "equals", "value": "ready_to_shape"}


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


checker = load(ASSETS / "check_shape.py", "shape_mvp_check")
bench = load(BENCH / "build.py", "shape_mvp_bench")
scorer = load(BENCH / "score.py", "shape_mvp_score")
CASES = {c["case"]: bench.load_case(c["file"]) for c in bench.cases()}


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


def setup_case(tmp_path, data):
    """The real setup step on one opportunity, staged as the launcher stages it."""
    workspace = tmp_path / "ws"
    (workspace / "_assets").mkdir(parents=True)
    for name in ("check_shape.py", "contract.md"):
        (workspace / "_assets" / name).write_text((ASSETS / name).read_text())
    (workspace / "_assets" / "opportunity.json").write_text(json.dumps(data))
    done = step("shape_mvp_setup", workspace, opportunity_path=str(workspace / "_assets" / "opportunity.json"),
                assets_dir=str(workspace / "_assets"))
    assert done.returncode == 0, done.stderr
    return workspace, last_json(done.stdout)


# ---- the configs ---------------------------------------------------------------------------------


def test_the_workflow_runs_setup_the_model_steps_the_check_the_grade_and_finalize():
    assert {p.stem for p in AGENTS} == {agent(p)["name"] for p in AGENTS}, "each agent file is named after its agent"
    nodes = workflow()["nodes"]
    assert [n["agent"] for n in nodes] == ORDER
    assert set(ORDER) == {p.stem for p in AGENTS}, "the workflow runs every shaping agent"
    for before, after in zip(nodes, nodes[1:], strict=False):
        assert after["depends_on"] == [before["name"]], "one step at a time, in order"
    for node in nodes:
        if node["name"] in GATED:
            assert node.get("condition") == READY, f"{node['name']} must wait for an input setup accepted"
        else:
            assert "condition" not in node, f"{node['name']} runs on every path"
    assert nodes[-1]["name"] == "finalize" and nodes[-1].get("run_after_failure") is True


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
def test_the_model_steps_keep_claude_codes_own_tools(path):
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


def test_the_workflow_outputs_name_fields_setup_and_finalize_print(tmp_path):
    workspace, setup_out = setup_case(tmp_path, CASES["F1"])
    final = step("shape_mvp_finalize", workspace)
    assert final.returncode == 0, final.stderr
    printed = {"setup": set(setup_out), "finalize": set(last_json(final.stdout))}
    for ref in workflow()["outputs"].values():
        node, _, field = ref.partition(".structured.")
        assert field in printed.get(node, set()), f"{ref}: {node} never prints `{field}`"
    fallback = re.search(r"echo '(\{.*\})'", by_name("shape_mvp_finalize")["script_template"])
    assert fallback, "finalize no longer says what happened when setup did not finish"
    assert set(json.loads(fallback.group(1))) == printed["finalize"], "the fallback prints what finalize prints"


# ---- the fixed benchmark ------------------------------------------------------------------------


def test_the_benchmark_is_fixed_and_never_tells_a_run_what_is_expected(tmp_path):
    first = bench.materialise(tmp_path / "a")
    assert first == bench.materialise(tmp_path / "b"), "the same files every time"
    assert sorted(first) == sorted(CASES) == ["F1", "F2", "F3", "G1", "R1", "R2", "R3"]
    for name, data in CASES.items():
        flat = json.dumps(data).lower()
        for tell in ("expected", "planted", "should block", "should be blocked", "must also", "benchmark case f",
                     "derive_from"):
            assert tell not in flat or tell == "benchmark case f" and name in ("F1", "F3"), f"{name} input says {tell!r}"
    with pytest.raises(SystemExit):
        (tmp_path / "a" / "R1.json").write_text("{}")
        bench.materialise(tmp_path / "a")


def differences(a, b):
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def test_each_planted_case_differs_from_its_control_only_where_its_derivation_says():
    assert differences(CASES["R1"], CASES["F1"]) == ["appetite", "fixture", "id"]
    assert differences(CASES["R2"], CASES["F3"]) == ["fixture", "id", "proposed_solution", "title"]
    assert differences(CASES["G1"], CASES["F2"]) == ["evidence", "id", "open_unknowns"]


def test_setup_sorts_the_benchmark_inputs_as_the_bar_expects(tmp_path):
    gaps = {"OG-target_price", "OG-success_bar"}
    for case in bench.cases():
        workspace, out = setup_case(tmp_path / case["case"], CASES[case["case"]])
        saved = json.loads((workspace / "state/shape/setup.json").read_text())
        codes = {p["code"] for p in saved["problems"]}
        if case["blocked_at"] == "setup":
            assert out["status"] == "blocked" and codes == set(case["setup_problem_codes"]), case["case"]
        else:
            assert out["status"] == "ready_to_shape" and not codes, (case["case"], saved["problems"])
        assert {g["id"] for g in saved["owner_input_gaps"]} == (set() if case["case"] in ("G1", "F2") else gaps)


# ---- the input contract -------------------------------------------------------------------------


def mutate(data, path, value):
    out = copy.deepcopy(data)
    *parents, last = path.split(".")
    node = out
    for key in parents:
        node = node[int(key)] if isinstance(node, list) else node[key]
    if value is DROP:
        del node[last]
    elif isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value
    return out


DROP = object()
CRITICAL = [
    ("schema", "shape_mvp.opportunity/0", "schema"),
    ("id", DROP, "id"),
    ("title", "TBD", "title"),
    ("buyer", DROP, "buyer"),
    ("buyer", "TBD", "buyer"),
    ("job", "unknown", "job"),
    ("job", "", "job"),
    ("appetite", DROP, "appetite"),
    ("appetite", None, "appetite"),
    ("appetite.time_weeks", 0, "appetite"),
    ("appetite.time_weeks", "TBD", "appetite"),
    ("appetite.builders", 0, "appetite"),
    ("appetite.source", "guess", "appetite"),
    ("evidence", [], "evidence"),
    ("evidence", [{"id": "E1", "kind": "assertion", "party": "interested", "claim": "Shops want this.",
                   "quote": "", "source": "proposer"}], "evidence"),
    ("evidence.0.source", "", "evidence"),
    ("constraints", [], "constraints"),
    ("constraints.0.source", "n/a", "constraints"),
    ("upstream_status", DROP, "upstream_status"),
    ("upstream_status.state", "maybe", "upstream_status"),
    ("upstream_status.state", "killed", "upstream_killed"),
]


@pytest.mark.parametrize(("path", "value", "code"), CRITICAL, ids=lambda v: v if isinstance(v, str) else None)
def test_the_contract_blocks_each_missing_critical_input_and_says_what_unblocks_it(path, value, code):
    setup = checker.check_input(mutate(CASES["G1"], path, value))
    assert setup["status"] == "blocked"
    assert code in {p["code"] for p in setup["problems"]}
    assert all(p["unblock"] for p in setup["problems"]), "every block says what would unblock it"


def test_a_killed_idea_the_owner_reopened_is_not_blocked_for_its_kill():
    data = mutate(CASES["R3"], "upstream_status.reopened", {"by": "owner", "date": "2026-10-03", "why": "new evidence"})
    assert "upstream_killed" not in {p["code"] for p in checker.check_input(data)["problems"]}


def test_missing_owner_values_become_gaps_and_are_never_filled_in():
    setup = checker.check_input(mutate(CASES["G1"], "owner_inputs", DROP))
    assert setup["status"] == "ready_to_shape"
    assert {g["id"] for g in setup["owner_input_gaps"]} == {"OG-target_price", "OG-success_bar"}
    assert not [v for v in setup["fixture_values"] if v.startswith(("target_price", "success_bar"))]


def test_test_fixture_values_are_labelled_and_a_good_input_has_no_problems():
    setup = checker.check_input(CASES["G1"])
    assert setup["status"] == "ready_to_shape" and not setup["problems"]
    assert setup["capacity"] == 2.0
    for label in ("appetite: 2 weeks x 1 builder(s)", "target_price: $29 per shop per month", "proposed solution"):
        assert label in setup["fixture_values"]


# ---- the pitch checks ---------------------------------------------------------------------------


def good_pitch(setup):
    """A valid shaped pitch for the good control (G1), written by hand."""
    return {
        "schema": "shape_mvp.pitch/1", "case_id": "g1-bookshop-returns-check", "status": "shaped",
        "problem": {"statement": "Owner-managers of small independent bookshops match each month's returns against "
                                 "suppliers' credit notes by hand and miss short or missing credits.",
                    "evidence_ids": ["E1", "E2", "E3"]},
        "appetite": {"time_weeks": 2, "builders": 1, "source": "test_fixture"},
        "appetite_note": "Two builder-weeks hold CSV matching, a mismatch list and query drafts; nothing else.",
        "upstream_status": {"state": "open", "note": "No upstream screening (test data)."},
        "solution": {
            "summary": "Upload the returns CSV and the credit-note CSVs, see what is missing or short, approve a "
                       "query per supplier.",
            "elements": [
                {"id": "S1", "name": "Upload and match", "does": "Match returns to credit notes by returns "
                 "authorisation number and ISBN", "estimate_builder_weeks": 0.8, "from_features": ["P1"],
                 "evidence_ids": ["E5", "E6"], "assumption_ids": ["A1", "A3"]},
                {"id": "S2", "name": "Mismatch list", "does": "List missing and short credits per supplier",
                 "estimate_builder_weeks": 0.4, "from_features": ["P2"], "evidence_ids": [], "assumption_ids": []},
                {"id": "S3", "name": "Query drafts", "does": "Draft one query per supplier for approval",
                 "estimate_builder_weeks": 0.6, "from_features": ["P3"], "evidence_ids": ["E4"],
                 "assumption_ids": []},
            ],
            "human_steps": ["The owner-manager edits, approves and sends each query from their own email."],
        },
        "scope_cuts": [],
        "rabbit_holes": [{"id": "RH1", "risk": "Credit notes that come only as PDF", "patch": "CSV only; PDF-only "
                          "suppliers are listed for manual entry", "evidence_ids": ["E5"]}],
        "no_gos": [{"item": "Point-of-sale or distributor integrations", "why": "Constraint C3"},
                   {"item": "Sending anything automatically", "why": "Constraint C2"}],
        "claims": [{"id": "C1", "text": "Most responding shops reconcile by hand", "support": "supported",
                    "evidence_ids": ["E1"], "quote": "71% of responding shops reconcile returns credits by hand"}],
        "assumptions": [
            {"id": "A1", "text": "Enough suppliers send CSV credit notes", "risk": "feasibility", "fatal": False,
             "from_unknowns": ["U1"], "evidence_ids": ["E5"], "test": "V1"},
            {"id": "A2", "text": "Shops pay the target price", "risk": "viability", "fatal": False,
             "from_unknowns": ["U2"], "evidence_ids": [], "test": "V2"},
            {"id": "A3", "text": "The CSV layouts stay stable", "risk": "feasibility", "fatal": False,
             "from_unknowns": ["U3"], "evidence_ids": ["E5"], "test": "V1"},
        ],
        "prerequisites": [{"id": "PR1", "kind": "data_access", "text": "Sample CSV files from both distributors",
                           "status": "unresolved", "blocks": "build", "evidence_ids": ["E5"], "from_unknowns": []}],
        "success_criteria": [{"id": "M1", "metric": "Pilot shops finishing a month's check in under half their "
                              "current time", "method": "Time each pilot shop's check against its own report",
                              "threshold": "4 of 6 shops", "horizon": "6 weeks", "threshold_source": "test_fixture",
                              "owner_input_gap": None}],
        "verification_plan": [
            {"id": "V1", "order": 1, "tests": ["A1", "A3"], "method": "Desk review of the documented CSV layouts",
             "pass_if": "Both layouts carry the matching keys", "kill_if": "Neither does", "effort": "1 day, builder",
             "cost": "free", "needs_owner_approval": False},
            {"id": "V2", "order": 2, "tests": ["A2"], "method": "Paid pilot with six shops", "pass_if": "4 of 6 pay",
             "kill_if": "Fewer than 2 pay", "effort": "6 weeks, owner", "cost": "paid", "needs_owner_approval": True},
        ],
        "owner_input_gaps": [],
        "fixture_values": list(setup["fixture_values"]),
        "critique_responses": [{"critique_id": "K1", "action": "accepted", "note": "Added RH1."}],
    }


CRITIQUE = {"items": [{"id": "K1", "area": "risks", "severity": "must_fix", "finding": "PDF credit notes missed",
                       "evidence_ids": ["E5"], "suggested_change": "Add a rabbit hole"},
                      {"id": "K2", "area": "labels", "severity": "note", "finding": "fine", "evidence_ids": []}],
            "status_view": "agree", "summary": "sound"}


@pytest.fixture
def g1():
    inp = copy.deepcopy(CASES["G1"])
    setup = checker.check_input(inp)
    return inp, setup


def codes(pitch, inp, setup, stage="final", critique=CRITIQUE):
    return [p["code"] for p in checker.check_pitch(pitch, inp, setup, stage, critique)]


def test_a_valid_pitch_passes_and_renders_appetite_before_solution(g1):
    inp, setup = g1
    pitch = good_pitch(setup)
    assert checker.check_pitch(pitch, inp, setup, "final", CRITIQUE) == []
    md = checker.render_pitch(pitch, inp, setup)
    assert checker.section_order_ok(md)
    assert md.index("## Problem") < md.index("## Appetite") < md.index("## Solution") < md.index("## Rabbit holes") \
        < md.index("## No-gos")
    assert "TEST FIXTURE" in md and checker.NOT_APPROVAL in md


def edit(fn):
    def apply(pitch):
        fn(pitch)
        return pitch
    return apply


PLANTED = [
    ("D1", edit(lambda p: p.update(schema="shape_mvp.pitch/0"))),
    ("D1", edit(lambda p: p.update(case_id="another-case"))),
    ("D1", edit(lambda p: p.update(status="ready"))),
    ("D2", edit(lambda p: p["appetite"].update(time_weeks=3))),
    ("D2", edit(lambda p: p["appetite"].update(source="owner"))),
    ("D3", edit(lambda p: p["solution"]["elements"][1].update(estimate_builder_weeks=0))),
    ("D3", edit(lambda p: p["solution"]["elements"][0].update(estimate_builder_weeks=1.5))),
    ("D4", edit(lambda p: p["problem"].update(evidence_ids=["E9"]))),
    ("D4", edit(lambda p: p["claims"][0].update(quote="81% of responding shops reconcile returns credits by hand"))),
    ("D4", edit(lambda p: p["claims"][0].update(evidence_ids=[]))),
    ("D5", edit(lambda p: p["assumptions"].pop(1) and p["verification_plan"][1].update(tests=["A1"]))),
    ("D5", edit(lambda p: p["prerequisites"][0].update(status="resolved", evidence_ids=[]))),
    ("D6", edit(lambda p: p["assumptions"][0].update(test="V9"))),
    ("D6", edit(lambda p: p["verification_plan"][0].update(kill_if=""))),
    ("D6", edit(lambda p: p["verification_plan"][1].update(needs_owner_approval=False))),
    ("D6", edit(lambda p: p["verification_plan"][1].update(order=1))),
    ("D7", edit(lambda p: p["success_criteria"][0].update(threshold="most shops"))),
    ("D7", edit(lambda p: p["success_criteria"][0].update(horizon="soon"))),
    ("D7", edit(lambda p: p["success_criteria"][0].update(threshold_source="owner"))),
    ("D7", edit(lambda p: p["success_criteria"][0].update(threshold_source="proposed"))),
    ("D9", edit(lambda p: p.update(fixture_values=[]))),
    ("D10", edit(lambda p: p["upstream_status"].update(state="validated"))),
    ("D11", edit(lambda p: p["solution"]["elements"][2].update(from_features=[]))),
    ("D12", edit(lambda p: p.update(rabbit_holes=[]))),
    ("D12", edit(lambda p: p.update(no_gos=[]))),
    ("D12", edit(lambda p: p.update(success_criteria=[]))),
    ("D12", edit(lambda p: p.update(prerequisites=[]))),
    ("D13", edit(lambda p: p.update(critique_responses=[]))),
]


@pytest.mark.parametrize(("code", "plant"), PLANTED, ids=[f"{c}-{i}" for i, (c, _) in enumerate(PLANTED)])
def test_the_checker_catches_each_planted_defect(g1, code, plant):
    inp, setup = g1
    found = codes(plant(good_pitch(setup)), inp, setup)
    assert code in found, f"expected {code}, got {found}"


def test_a_fatal_unknown_must_stay_fatal(g1):
    inp, _ = g1
    inp = mutate(inp, "open_unknowns.1.fatal", True)
    setup = checker.check_input(inp)
    assert "D5" in codes(good_pitch(setup), inp, setup)
    pitch = good_pitch(setup)
    pitch["assumptions"][1]["fatal"] = True
    assert "D5" not in codes(pitch, inp, setup)


def fatal_order_problems(pitch, inp, setup):
    return [p["message"] for p in checker.check_pitch(pitch, inp, setup, "final", CRITIQUE)
            if p["code"] == "D6" and p["message"].startswith("fatal unknown")]


def test_each_fatal_unknown_is_tested_within_the_first_steps(g1):
    inp, _ = g1
    inp = mutate(inp, "open_unknowns.1.fatal", True)  # one fatal unknown: tested within the first 2 steps
    setup = checker.check_input(inp)
    pitch = good_pitch(setup)
    pitch["assumptions"][1]["fatal"] = True
    assert fatal_order_problems(pitch, inp, setup) == [], "step 2 is early enough"
    pitch["verification_plan"][1]["order"] = 3
    pitch["verification_plan"].insert(1, {"id": "V3", "order": 2, "tests": ["A3"], "method": "Desk review of a "
                                       "second CSV sample", "pass_if": "Keys stable", "kill_if": "Keys change",
                                       "effort": "1 day, builder", "cost": "free", "needs_owner_approval": False})
    late = fatal_order_problems(pitch, inp, setup)
    assert len(late) == 1 and "fatal unknown U2" in late[0] and "first tested at step 3" in late[0]
    pitch["verification_plan"][0]["tests"].append("A2")  # a free desk test of it first; the paid pilot can follow
    assert fatal_order_problems(pitch, inp, setup) == []


def test_every_owner_gap_setup_found_is_carried(g1):
    inp, _ = g1
    inp = mutate(inp, "owner_inputs", DROP)
    setup = checker.check_input(inp)
    pitch = good_pitch(setup)
    pitch["success_criteria"][0].update(threshold_source="proposed", owner_input_gap="OG-success_bar")
    assert "D8" in codes(pitch, inp, setup)
    pitch["owner_input_gaps"] = copy.deepcopy(setup["owner_input_gaps"])
    assert codes(pitch, inp, setup) == []


def test_the_draft_stage_does_not_ask_for_critique_responses(g1):
    inp, setup = g1
    pitch = good_pitch(setup)
    pitch["critique_responses"] = []
    assert codes(pitch, inp, setup, stage="draft", critique=None) == []


def blocked_record(setup):
    return {"schema": "shape_mvp.pitch/1", "case_id": "f2-bookshop-returns-check", "status": "blocked",
            "problem": {"statement": "The evidence is about chain finance teams, not independent shops.",
                        "evidence_ids": ["E1", "E3"]},
            "appetite": {"time_weeks": 2, "builders": 1, "source": "test_fixture"},
            "upstream_status": {"state": "open"},
            "solution": {"summary": "", "elements": [], "human_steps": []},
            "claims": [{"id": "C1", "text": "Chain finance teams have the problem", "support": "supported",
                        "evidence_ids": ["E1"]}],
            "blocked": {"reasons": ["No supplied evidence shows the problem for independent shops (E1 is chains, "
                                    "E3 is the proposer's belief)."],
                        "unblock_needs": ["Evidence from independent shops: a survey or interviews."],
                        "evidence_ids": ["E1", "E3"]},
            "fixture_values": list(setup["fixture_values"]), "critique_responses": []}


def test_a_blocked_record_passes_and_needs_reasons_unblock_needs_and_no_solution():
    inp = copy.deepcopy(CASES["F2"])
    setup = checker.check_input(inp)
    record = blocked_record(setup)
    assert codes(record, inp, setup, critique={"items": []}) == []
    for plant in (lambda r: r["blocked"].update(reasons=[]), lambda r: r["blocked"].update(unblock_needs=["TBD"]),
                  lambda r: r["solution"].update(elements=[{"id": "S1", "estimate_builder_weeks": 1}]),
                  lambda r: r["blocked"].update(evidence_ids=["E42"])):
        broken = copy.deepcopy(record)
        plant(broken)
        assert set(codes(broken, inp, setup, critique={"items": []})) & {"B", "D4"}


# ---- the whole script path and the final status ------------------------------------------------


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


GRADE = {"verdict": "pass", "status_view": "agree", "issues": [],
         "criteria": [{"id": f"G{n}", "met": True, "applies": True, "note": "ok"} for n in range(1, 9)]}


def model_steps(workspace, pitch, grade=GRADE):
    shape = workspace / "state/shape"
    write(shape / "draft/pitch.json", pitch)
    write(shape / "critique.json", CRITIQUE)
    write(shape / "pitch.json", pitch)
    check = step("shape_mvp_check", workspace)
    assert check.returncode == 0, check.stderr
    write(shape / "grade.json", grade)
    return last_json(check.stdout)


def finalize(workspace):
    done = step("shape_mvp_finalize", workspace)
    assert done.returncode == 0, done.stderr
    return last_json(done.stdout), json.loads((workspace / "state/shape/result.json").read_text())


def test_a_sound_run_ends_shaped_with_its_pitch_rendered(tmp_path):
    workspace, setup = setup_case(tmp_path, CASES["G1"])
    saved = json.loads((workspace / "state/shape/setup.json").read_text())
    assert model_steps(workspace, good_pitch(saved))["verdict"] == "pass"
    out, result = finalize(workspace)
    assert out["final_status"] == result["final_status"] == "shaped", result["problems"]
    md = (workspace / "state/shape/pitch.md").read_text()
    assert checker.section_order_ok(md) and checker.NOT_APPROVAL in md
    assert "Shaping note: Two builder-weeks" in md, "the model's appetite note is labelled as its own"
    score = scorer.score_case(next(c for c in bench.cases() if c["case"] == "G1"), workspace)
    assert score["fails"] == [], score
    report = (workspace / "state/shape/RESULT.md").read_text()
    assert "## Pitch in brief" in report and "Fit: 1.8 of 2.0 builder-weeks in 3 element(s)" in report
    assert "Files: state/shape/pitch.md, state/shape/check.json." in report, "it names only files that exist"


def test_the_result_lists_the_owner_decisions_the_pitch_raises(tmp_path):
    workspace, _ = setup_case(tmp_path, CASES["G1"])
    saved = json.loads((workspace / "state/shape/setup.json").read_text())
    pitch = good_pitch(saved)
    pitch["owner_input_gaps"] = [{"id": "OG-contact_approval", "needed": "Approval to contact six pilot shops",
                                  "why": "Constraint C1"}]
    model_steps(workspace, pitch)
    out, result = finalize(workspace)
    assert out["final_status"] == "shaped", result["problems"]
    assert [g["id"] for g in result["owner_questions"]] == ["OG-contact_approval"]
    report = (workspace / "state/shape/RESULT.md").read_text()
    assert "## Owner decisions the pitch raises\n- OG-contact_approval: Approval to contact six pilot shops" in report


def test_a_setup_block_ends_blocked_without_any_model_step(tmp_path):
    workspace, setup = setup_case(tmp_path, CASES["F1"])
    assert setup["status"] == "blocked"
    out, result = finalize(workspace)
    assert out["final_status"] == "blocked" and any("appetite" in r for r in result["reasons"])
    assert result["unblock_needs"], "a block says what would unblock it"
    assert "Files: state/shape/pitch.md." in (workspace / "state/shape/RESULT.md").read_text(), "no grade to point to"
    score = scorer.score_case(next(c for c in bench.cases() if c["case"] == "F1"), workspace)
    assert score["fails"] == [], score


def test_setup_refuses_a_used_workspace_and_finalize_then_reports_blocked(tmp_path):
    workspace, _ = setup_case(tmp_path, CASES["G1"])
    again = step("shape_mvp_setup", workspace, opportunity_path=str(workspace / "_assets/opportunity.json"),
                 assets_dir=str(workspace / "_assets"))
    assert again.returncode != 0 and "fresh workspace" in again.stderr
    bare = tmp_path / "bare"
    bare.mkdir()
    done = step("shape_mvp_finalize", bare)
    assert last_json(done.stdout)["final_status"] == "blocked"


def worse(name):
    def apply(workspace, pitch, grade):
        shape = workspace / "state/shape"
        if name == "check fails":
            pitch["rabbit_holes"] = []
        if name == "grade revises":
            grade = {**grade, "verdict": "revise", "issues": ["G5: an invented price"]}
        if name == "grade disagrees":
            grade = {**grade, "status_view": "should_block"}
        if name == "grade skips a criterion":
            grade = {**grade, "criteria": grade["criteria"][:-1]}
        if name == "grade leaves a criterion unmet":
            grade = {**grade, "criteria": [{**c, "met": c["id"] != "G6"} for c in grade["criteria"]]}
        model_steps(workspace, pitch, grade)
        if name == "a step wrote nothing":
            (shape / "critique.json").unlink()
        if name == "usage-limit text":
            (shape / "critique.md").write_text("You've hit your limit · resets 5am")
        if name == "model left it at revise":
            write(shape / "pitch.json", {**pitch, "status": "revise"})
    return apply


@pytest.mark.parametrize("name", ["check fails", "grade revises", "grade disagrees", "grade skips a criterion",
                                  "grade leaves a criterion unmet", "a step wrote nothing", "usage-limit text",
                                  "model left it at revise"])
def test_anything_short_of_a_whole_pass_ends_revise(tmp_path, name):
    workspace, _ = setup_case(tmp_path, CASES["G1"])
    saved = json.loads((workspace / "state/shape/setup.json").read_text())
    worse(name)(workspace, good_pitch(saved), copy.deepcopy(GRADE))
    out, result = finalize(workspace)
    assert out["final_status"] == "revise", (name, result)
    assert result["problems"], "a revise says why"


def test_the_score_counts_a_fatal_unknown_as_tested_early_only_if_an_early_step_lists_it(tmp_path):
    case = {"case": "R1", "id": "r1", "expected_final_status": "shaped", "blocked_at": None, "fatal_unknowns": ["U1"]}
    shape = tmp_path / "state/shape"
    write(shape / "result.json", {"final_status": "shaped", "case_id": "r1"})
    write(shape / "setup.json", {"status": "ready_to_shape", "capacity": 6.0})
    write(shape / "check.json", {"verdict": "pass"})
    write(shape / "grade.json", {"verdict": "pass", "status_view": "agree"})
    steps = [{"id": f"V{n}", "order": n, "tests": []} for n in (1, 2, 3)]
    pitch = {"status": "shaped", "solution": {"elements": [{"estimate_builder_weeks": 1}]}, "verification_plan": steps,
             "assumptions": [{"id": "A1", "fatal": True, "from_unknowns": ["U1"], "test": "V3"}]}
    write(shape / "pitch.json", pitch)
    assert scorer.score_case(case, tmp_path)["fails"] == ["fatal unknown U1 is not tested within the first 2 steps"]
    steps[0]["tests"] = ["A1"]  # a first step that tests it, with the decisive test still third
    write(shape / "pitch.json", pitch)
    assert scorer.score_case(case, tmp_path)["fails"] == []


def test_a_model_block_stays_blocked_whatever_the_grade_says(tmp_path):
    workspace, _ = setup_case(tmp_path, CASES["F2"])
    saved = json.loads((workspace / "state/shape/setup.json").read_text())
    record = blocked_record(saved)
    assert model_steps(workspace, record)["verdict"] == "pass"
    out, result = finalize(workspace)
    assert out["final_status"] == "blocked" and result["reasons"] and result["unblock_needs"]
    score = scorer.score_case(next(c for c in bench.cases() if c["case"] == "F2"), workspace)
    assert score["fails"] == [], score
    write(workspace / "state/shape/grade.json", {**GRADE, "status_view": "should_shape"})
    assert finalize(workspace)[0]["final_status"] == "blocked", "the most conservative status wins"
