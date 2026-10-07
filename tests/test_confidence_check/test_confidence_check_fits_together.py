"""The confidence check (configs/workflows/confidence_check.yaml, product role, queue #32) fits together.

It reads one idea's saved research and, for value, viability, feasibility, usability and serving
barriers, lists cited evidence, sets each level by a fixed rule (money or behaviour from the buyer >
independent public evidence > words), names the cheapest next upfront test, and ends ready or not
ready to shape. Here: the configs run in that order and are fed every value they use; the method
stays frozen; setup stops at no cost on a bad input; the check applies the fixed rule, the gate and
the next-test pick; a claim in our own notes never raises a level; an owner-supplied record does; a
quote not in its file is dropped and flagged; a part an account limit stopped fails the run by name.
No model and no network: every part's output here is hand-written.
"""

import ast
import hashlib
import json
import os
import shutil
import subprocess
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
AGENTS = sorted(AGENTS_DIR.glob("confidence_*.yaml"))
ASSETS = AGENTS_DIR / "confidence_check_assets"
WORKFLOW = ROOT / "configs" / "workflows" / "confidence_check.yaml"
INJECTED = {"workspace_path", "run_id"}  # the script agent adds these to every template
PARTS = ("value", "viability", "feasibility", "usability", "serving", "breakers")
# Frozen before the check's first run (product results/2026-10-06-confidence-32/criteria.md): a
# change to the method is a new version, landed on purpose with a new hash.
FROZEN = {
    "configs/agents/confidence_check_assets/method.md": "0c94fc7a1e4acecc5447eda03c0b0d1610170446e071e3c34c8912481b75a93d",
}
LIMIT = "You've hit your session limit \u00b7 resets 10:50pm (UTC)"
DONE = '```json\n{"status": "completed"}\n```'
PAGE_PRICE = ("Pricing. Appeal letters cost $5 per letter for billing teams, with no contract and no setup fee. "
              "Most billers send twenty to forty appeals a month.")
PAGE_RATE = ("Of the 1.2 million prior authorization denials that were appealed in 2023, 81.7 percent were "
             "partially or fully overturned on appeal, according to the public data.")
OWNER_DEPOSITS = ("date,buyer,amount_usd,status\n2026-10-01,Northside Billing LLC (billing company),200,paid deposit\n"
                  "2026-10-02,Lakeview Medical Billing (billing company),200,paid deposit\n")
NOTES = ("# Desk check report\n\nD1 (fatal): billing companies must already pay for appeal help, or the price fails.\n"
         "D2 (fatal): no rival already sells one denial queue across many clients with drafting.\n"
         "Lawful route (non-fatal): a BAA chain with each client.\n"
         "Three billing companies have already prepaid for the first year of the service.\n")


def served(path):
    """The config as the server hands it out (ConfigStore.get runs the env substitution)."""
    return substitute_env_vars(yaml.safe_load(path.read_text()))


def agent(path):
    return served(path)["agent"]


def by_name(name):
    return agent(AGENTS_DIR / f"{name}.yaml")


def workflow():
    return served(WORKFLOW)["workflow"]


def nodes():
    return {n["name"]: n for n in workflow()["nodes"]}


def templates_of(cfg):
    if cfg.get("type") == "script":
        return [cfg["script_template"]]
    return [cfg["task_template"], cfg.get("system_prompt", "")]


def jinja(stash=None):
    env = SandboxedEnvironment(loader=BaseLoader(), undefined=ChainableUndefined)
    stash = stash if stash is not None else _ValueStash()
    env.filters[QUOTED_FILTER] = stash.quoted
    env.filters[BARE_FILTER] = stash.bare
    env.filters[ENV_FILTER] = stash.name
    return env


def step(name, workspace, **values):
    """A script step rendered the way the script agent renders it and run by /bin/sh."""
    cfg = by_name(name)
    stash = _ValueStash()
    script = jinja(stash).from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render(
        workspace_path=str(workspace), **values)
    env = {**os.environ, **stash.env, "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=120, cwd=workspace, env=env)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def state(workspace):
    return workspace / "state" / "confidence"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=1))


def staged(tmp_path, owner=False, run_id="run-1", extra=None, **values):
    """A fresh run workspace with the assets and the research staged, after the setup step."""
    workspace = tmp_path / "ws"
    (workspace / "_assets").mkdir(parents=True)
    for name in ("check_confidence.py", "method.md"):
        shutil.copyfile(ASSETS / name, workspace / "_assets" / name)
    research = workspace / "_research"
    write(research / "desk" / "report.md", NOTES)
    write(research / "desk" / "pages" / "price.txt", PAGE_PRICE)
    write(research / "signal" / "data" / "rates.txt", PAGE_RATE)
    write(research / "empty.md", "")
    if owner:
        write(research / "owner" / "deposits.csv", OWNER_DEPOSITS)
    for rel, text in (extra or {}).items():
        write(research / rel, text)
    values = {"idea": "Billing companies: one denial queue across clients plus appeal letters, about $20 an appeal.",
              "research_dir": str(research), "assets_dir": str(workspace / "_assets"), "run_id": run_id, **values}
    return workspace, step("confidence_setup", workspace, **values)


def line(eid, file, quote, cls, direction="for", target_buyer=True, specific=True, venue=None):
    out = {"id": eid, "file": file, "quote": quote, "class": cls, "target_buyer": target_buyer,
           "specific": specific, "direction": direction, "says": "a test line"}
    if venue:
        out["venue"] = venue
    return out


PRICE = "Appeal letters cost $5 per letter for billing teams, with no contract"
RATE = "81.7 percent were partially or fully overturned on appeal"
PREPAID = "Three billing companies have already prepaid for the first year of the service."


def sound_parts(workspace, viability_lines=None, unsupported=None):
    """Hand-written part outputs that meet the method: value medium, viability low, rest as noted."""
    p = state(workspace) / "parts"
    base = {"question": "q", "unsupported": [], "reason": "r", "open": []}
    write(p / "value.json", {**base, "part": "value", "level": "medium", "evidence": [
        line("E1", "research/signal/data/rates.txt", RATE, "independent")],
        "tests": [{"id": "T1", "test": "read four rival pages", "kind": "runnable", "needs": "free desk read",
                   "cost_usd": 8, "cost_note": "", "yields": "independent",
                   "targets": [{"item": "value", "settle": "partly"}]}]})
    write(p / "viability.json", {**base, "part": "viability", "level": "low",
                                 "unsupported": unsupported or [],
                                 "evidence": viability_lines or [
                                     line("E1", "research/desk/pages/price.txt", PRICE, "independent", "against")],
                                 "tests": [{"id": "T1", "test": "biller time logs", "kind": "needs_owner",
                                            "tier": "contact", "yields": "independent",
                                            "needs": "contact with billers", "cost_usd": 0, "cost_note": "2 weeks",
                                            "targets": [{"item": "viability", "settle": "yes"}]}]})
    write(p / "feasibility.json", {**base, "part": "feasibility", "level": "medium", "evidence": [
        line("E1", "research/signal/data/rates.txt", "1.2 million prior authorization denials that were appealed in 2023",
             "independent")], "tests": []})
    write(p / "usability.json", {**base, "part": "usability", "level": "unknown", "evidence": [], "tests": []})
    write(p / "serving.json", {**base, "part": "serving", "level": "unknown", "evidence": [], "tests": [],
                               "barriers": [{"id": "B1", "barrier": "BAA chain", "type": "legal_compliance",
                                             "severity": "heavy", "evidence": [], "reason": "r"}]})
    write(p / "breakers.json", {**base, "part": "breakers", "level": "unknown", "evidence": [
        line("E1", "research/desk/pages/price.txt", PRICE, "independent")],
        "breakers": [
            {"id": "D1", "text": "billing companies already pay for appeal help", "risk": "viability", "status": "pass",
             "origin": "research", "evidence": ["E1"], "reason": "a $5 price page", "written": {
                 "file": "research/desk/report.md", "quote": "billing companies must already pay for appeal help"}},
            {"id": "D2", "text": "no rival sells one queue across clients", "risk": "value", "status": "open",
             "origin": "research", "evidence": [], "reason": "pages unread", "written": {
                 "file": "research/desk/report.md", "quote": "no rival already sells one denial queue across many clients"}}],
        "tests": [
            {"id": "T1", "test": "biller interviews about rivals", "kind": "needs_owner", "needs": "contact",
             "tier": "contact", "yields": "words",
             "cost_usd": 0, "cost_note": "", "targets": [{"item": "D2", "settle": "yes"}]},
            {"id": "T2", "test": "read the four unread rival pages", "kind": "runnable", "needs": "free desk read",
             "yields": "independent",
             "cost_usd": 10, "cost_note": "one desk_check run", "targets": [{"item": "d2", "settle": "yes"}]}]})


def check(workspace, run_id="run-1", **answers):
    values = {f"{part}_answer": DONE for part in PARTS}
    values.update(answers)
    return step("confidence_final", workspace, run_id=run_id, **values)


def result(workspace):
    return json.loads((state(workspace) / "confidence.json").read_text())


@pytest.fixture
def sound(tmp_path):
    workspace, out = staged(tmp_path)
    assert out["status"] == "ready", out
    sound_parts(workspace)
    return workspace


# ---- the configs ---------------------------------------------------------------------------------


def test_the_workflow_runs_setup_then_six_parts_side_by_side_then_final():
    assert {p.stem for p in AGENTS} == {agent(p)["name"] for p in AGENTS}, "each agent file is named after its agent"
    n = nodes()
    assert list(n) == ["setup", *PARTS, "final"]
    assert {node["agent"] for node in n.values()} == {p.stem for p in AGENTS}
    ready = {"source": "setup.structured.status", "operator": "equals", "value": "ready"}
    assert "depends_on" not in n["setup"] and "condition" not in n["setup"]
    for part in PARTS:
        node = n[part]
        assert node["agent"] == "confidence_rater" and node["input_map"] == {"part": part}
        assert node["depends_on"] == ["setup"] and node["condition"] == ready, "the six parts run side by side"
    assert n["final"]["depends_on"] == list(PARTS) and n["final"]["run_after_failure"] is True
    assert "condition" not in n["final"], "the final check runs on every path"
    assert n["final"]["input_map"] == {f"{part}_answer": f"{part}.output" for part in PARTS}


@pytest.mark.parametrize("path", [p for p in AGENTS if agent(p).get("type") == "script"], ids=lambda p: p.stem)
def test_every_script_step_parses_under_sh(path):
    cfg = agent(path)
    script = jinja().from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render()
    done = subprocess.run(["sh", "-n", "-c", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, f"{path.name} does not parse under /bin/sh: {done.stderr.strip()}"


@pytest.mark.parametrize("path", [*AGENTS, WORKFLOW], ids=lambda p: p.stem)
def test_no_file_holds_the_config_stores_env_syntax(path):
    assert "${" not in path.read_text(), "the config store would substitute it as an env var"


def test_every_template_variable_is_fed_by_the_workflow():
    env = jinja()
    wf = workflow()
    for name, node in nodes().items():
        fed = node.get("input_map") or {}
        for value in fed.values():
            head, _, field = value.partition(".")
            if head == "input":
                assert field in wf["inputs"], f"{name}: {value} is not an input"
            elif field == "output":
                assert head in node.get("depends_on", []), f"{name}: {value} is not from a step it waits for"
            else:
                assert value in PARTS, f"{name}: {value} is neither an input, a step's answer nor a part"
        for template in templates_of(by_name(node["agent"])):
            for used in meta.find_undeclared_variables(env.parse(template)) - set(fed) - INJECTED:
                # Unfed, a value renders empty through `(x or '')` or as __unwired__, never as text.
                assert f"({used} or '')" in template or f"{used} is string else '__unwired__'" in template, (
                    f"{node['agent']} needs {used} fed or defaulted")


def test_the_part_keeps_claude_codes_own_tools_and_the_rules():
    cfg = by_name("confidence_rater")
    assert cfg["type"] == "llm" and cfg["provider"] == "claude"
    assert "tools" not in cfg, "provider claude refuses temper tool schemas; it uses its own tools"
    text = cfg["system_prompt"] + cfg["task_template"]
    for rule in ("Do not use WebSearch or WebFetch", "check_confidence.py quote", "method.md", "{{ part }}",
                 "unsupported", "Accuracy is never a wedge", "Never invent evidence"):
        assert rule in text, f"confidence_rater lost {rule!r}"


def test_the_method_is_frozen():
    for rel, sha in FROZEN.items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == sha, f"{rel} changed: a new method version"


def test_the_workflow_outputs_name_fields_the_final_step_prints(sound):
    printed = set(check(sound))
    for ref in workflow()["outputs"].values():
        node, _, field = ref.partition(".structured.")
        assert node == "final" and field in printed, f"{ref}: the final step never prints `{field}`"
    script = by_name("confidence_final")["script_template"]
    fallback = json.loads(script.split("echo '", 1)[1].split("'\n", 1)[0])
    assert set(fallback) == printed, "the fallback prints what the check prints"


def test_every_config_has_a_product_ownership_row():
    section = (ROOT / "docs" / "departments.md").read_text().split("### product (", 1)[1].split("\n### ", 1)[0]
    assets = sorted(p for p in ASSETS.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    for path in [WORKFLOW, *AGENTS, *assets]:
        rel = path.relative_to(ROOT / "configs").as_posix()
        assert f"| `{rel}` |" in section, f"{rel} has no product ownership row"
    assert int(section.split(")", 1)[0]) == section.count("\n| `"), "the product heading counts its rows"


def test_the_product_launcher_starts_confidence_check_as_a_live_workflow():
    tree = ast.parse((ROOT / "configs" / "product" / "bin" / "server_run.py").read_text())
    live = next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["LIVE"])
    assert "confidence_check" in live
    assert "start.sh $JOB confidence_check" in (ROOT / "docs" / "product-runs.md").read_text()


# ---- setup ---------------------------------------------------------------------------------------


def test_setup_stages_the_method_and_research_and_sets_each_files_kind(tmp_path):
    workspace, out = staged(tmp_path, owner=True)
    assert out == {"status": "ready", "files": 4, "kinds": {"source": 2, "owner": 1, "notes": 1}, "problems": []}
    root = state(workspace)
    for name in ("check_confidence.py", "method.md"):
        assert (root / name).read_bytes() == (ASSETS / name).read_bytes()
    kinds = {f["file"]: f["kind"] for f in json.loads((root / "manifest.json").read_text())["files"]}
    assert kinds == {"research/desk/report.md": "notes", "research/desk/pages/price.txt": "source",
                     "research/signal/data/rates.txt": "source", "research/owner/deposits.csv": "owner"}
    assert (root / "research" / "owner" / "deposits.csv").read_text() == OWNER_DEPOSITS
    text = (root / "input.md").read_text()
    for bit in ("one denial queue across clients", "research/owner/deposits.csv", "research/desk/pages/: 1 files",
                "(none given: the breakers part finds them in the research)", "### Not copied\n\n- empty.md: empty"):
        assert bit in text


def test_setup_stops_at_no_cost_naming_every_problem(tmp_path):
    _, out = staged(tmp_path, idea=None, research_dir="no-such-folder")
    assert out["status"] == "not_ready" and out["files"] == 0
    assert any("no idea given" in p for p in out["problems"])
    assert any("no-such-folder is not a folder" in p for p in out["problems"])


@pytest.mark.parametrize("change, problem", [
    ({"research_dir": "/etc"}, "outside the run workspace"),
    ({"research_dir": ""}, "no research_dir given"),
    ({"idea": "  "}, "no idea given"),
])
def test_setup_stops_on_a_bad_input(tmp_path, change, problem):
    _, out = staged(tmp_path, **change)
    assert out["status"] == "not_ready" and problem in " ".join(out["problems"])


def test_setup_refuses_a_workspace_that_already_holds_a_check(sound):
    out = step("confidence_setup", sound, idea="x", research_dir=str(sound / "_research"),
               assets_dir=str(sound / "_assets"))
    assert out["status"] == "not_ready" and "already holds a check" in out["problems"][0]


def test_an_input_the_run_did_not_give_is_empty_not_the_text_none(tmp_path):
    workspace, out = staged(tmp_path, deal_breakers=None)
    assert out["status"] == "ready"
    assert "None" not in (state(workspace) / "input.md").read_text()


# ---- the check: rule, gate, next test ------------------------------------------------------------


def test_a_sound_check_passes_and_applies_the_rule_the_gate_and_the_pick(sound):
    out = check(sound)
    assert out["status"] == "pass", out["problems"]
    assert out["levels"] == {"value": "medium", "viability": "low", "feasibility": "medium",
                             "usability": "unknown", "serving": "unknown"}
    assert out["verdict"] == "not_ready" and out["deal_breakers"] == {"open": ["D2"], "failed": []}
    # rule 1: a test that settles an open deal-breaker; least effort (runnable before contact).
    assert out["next_test"]["part"] == "breakers" and out["next_test"]["id"] == "T2"
    report = (state(sound) / "report.md").read_text()
    for bit in ("NOT READY to shape", "viability is low", "deal-breaker D2 is open", "Ready gate (default",
                "rule 1: a test settles an open deal-breaker", "| D1 |", "**pass**"):
        assert bit in report


def test_without_a_settling_test_the_pick_moves_the_most_blocking_items(sound):
    p = state(sound) / "parts" / "breakers.json"
    data = json.loads(p.read_text())
    data["tests"] = []
    write(p, data)
    out = check(sound)
    assert out["next_test"]["part"] == "viability" and out["next_test"]["id"] == "T1"


@pytest.mark.parametrize("repeats, rule", [("independent", "rule 2"), ("money", "rule 2"), ("words", "rule 1"), (None, "rule 1")])
def test_a_repeat_of_an_unknown_test_settles_nothing_unless_it_climbs_the_ladder(sound, repeats, rule):
    p = state(sound) / "parts" / "breakers.json"
    data = json.loads(p.read_text())
    for t in data["tests"]:
        t["repeats"] = repeats
        t["yields"] = "independent"
    write(p, data)
    check(sound)
    assert result(sound)["pick_rule"].startswith(rule)
    if rule == "rule 2":
        assert "a repeat at the same rung" in (state(sound) / "report.md").read_text()


def test_a_repeat_that_climbs_the_ladder_can_still_settle(sound):
    p = state(sound) / "parts" / "breakers.json"
    data = json.loads(p.read_text())
    for t in data["tests"]:
        t["repeats"] = "independent"
        t["yields"] = "behaviour"
    write(p, data)
    check(sound)
    assert result(sound)["pick_rule"].startswith("rule 1")


def test_a_test_that_yields_only_words_cannot_settle_a_deal_breaker(sound):
    p = state(sound) / "parts" / "breakers.json"
    data = json.loads(p.read_text())
    for t in data["tests"]:
        t["yields"] = "words"
    write(p, data)
    check(sound)
    assert result(sound)["pick_rule"].startswith("rule 2")


def split_viability(tmp_path, net):
    workspace, _ = staged(tmp_path)
    sound_parts(workspace, viability_lines=[
        line("E1", "research/desk/pages/price.txt", PRICE, "independent", "against"),
        line("E2", "research/signal/data/rates.txt", RATE, "independent")])
    p = state(workspace) / "parts" / "viability.json"
    data = json.loads(p.read_text())
    data["level"] = "medium" if (net or {}).get("answer") == "yes" else "low"
    if net is not None:
        data["net"] = net
    write(p, data)
    return workspace, check(workspace)


def test_split_evidence_the_part_reads_as_yes_is_medium_and_marked_contested(tmp_path):
    workspace, out = split_viability(tmp_path, {"answer": "yes", "decisive": ["E2"], "why": "the payer's rate"})
    assert out["levels"]["viability"] == "medium" and out["status"] == "pass", out["problems"]
    assert result(workspace)["contested"] == ["viability"]
    assert "**medium** (contested)" in (state(workspace) / "report.md").read_text()


def test_split_evidence_the_part_reads_as_no_is_low(tmp_path):
    _, out = split_viability(tmp_path, {"answer": "no", "decisive": ["E1"], "why": "a cheaper rival"})
    assert out["levels"]["viability"] == "low" and out["status"] == "pass", out["problems"]


@pytest.mark.parametrize("net", [None, {"answer": "maybe", "decisive": ["E2"]},
                                 {"answer": "yes", "decisive": ["E1"]}])
def test_split_evidence_without_a_sound_net_is_low_and_a_problem(tmp_path, net):
    _, out = split_viability(tmp_path, net)
    assert out["levels"]["viability"] == "low" and out["status"] == "flagged"
    assert any("evidence is split" in x for x in out["problems"])


def test_a_higher_ranked_context_line_does_not_move_the_tie_a_split_is_read_at(tmp_path):
    workspace, _ = staged(tmp_path, owner=True)
    sound_parts(workspace, viability_lines=[
        line("E1", "research/desk/pages/price.txt", PRICE, "independent", "against"),
        line("E2", "research/signal/data/rates.txt", RATE, "independent"),
        line("E3", "research/owner/deposits.csv", "2026-10-01,Northside Billing LLC (billing company),200,paid deposit",
             "money", "context")])
    p = state(workspace) / "parts" / "viability.json"
    data = json.loads(p.read_text())
    data["level"], data["net"] = "medium", {"answer": "yes", "decisive": ["E2"], "why": "the payer's rate"}
    write(p, data)
    out = check(workspace)
    assert out["levels"]["viability"] == "medium" and out["status"] == "pass", out["problems"]
    assert result(workspace)["contested"] == ["viability"]


def test_setup_lists_the_owners_own_words(tmp_path):
    workspace, _ = staged(tmp_path, extra={"travel/owner-input.md": OWNER_WORDS})
    text = (state(workspace) / "input.md").read_text()
    words = text.split("### The owner's own words")[1].split("###")[0]
    assert "research/travel/owner-input.md" in words and "research/desk/report.md" not in words


def test_free_first_then_the_buyers_own_behaviour_before_a_desk_read(sound):
    p = state(sound) / "parts"
    breakers = json.loads((p / "breakers.json").read_text())
    breakers["tests"] = []
    write(p / "breakers.json", breakers)
    viability = json.loads((p / "viability.json").read_text())
    viability["tests"] += [
        {"id": "T2", "test": "desk read of price pages", "kind": "runnable", "needs": "free desk read",
         "yields": "independent", "cost_usd": 8, "cost_note": "", "targets": [{"item": "viability", "settle": "partly"}]},
        {"id": "T3", "test": "ask the owner for his live quiz counts", "kind": "needs_owner", "tier": "owner_data",
         "yields": "behaviour", "needs": "owner's counts", "cost_usd": 0, "cost_note": "asking",
         "targets": [{"item": "viability", "settle": "partly"}]}]
    write(p / "viability.json", viability)
    # T1 (contact) moves more, but free tests come first; among them the buyer's own behaviour wins.
    assert check(sound)["next_test"]["id"] == "T3"
    viability["tests"] = viability["tests"][:2]
    write(p / "viability.json", viability)
    out = check(sound, run_id="run-2")
    assert out["next_test"]["id"] == "T2" and out["next_test"]["tier"] is None
    assert "least effort" in (state(sound) / "report.md").read_text()


def test_a_needs_owner_test_without_a_tier_is_a_problem_and_sorts_as_paid(sound):
    p = state(sound) / "parts" / "viability.json"
    data = json.loads(p.read_text())
    del data["tests"][0]["tier"]
    del data["tests"][0]["yields"]
    write(p, data)
    out = check(sound)
    assert out["status"] == "flagged"
    assert any("tier None" in x for x in out["problems"]) and any("yields None" in x for x in out["problems"])


PAIN_A = "I spend every Friday night rebuilding the denial list for each client by hand"
PAIN_B = "chasing the same denials through six payer portals is eating my whole week"
PAIN_PAGES = {"forum/pages/hn.txt": f"Comment: {PAIN_A}. Anyone else?",
              "forum/pages/reddit.txt": f"Post: honestly {PAIN_B}, send help"}


def pain_value(workspace, venues):
    sound_parts(workspace)
    p = state(workspace) / "parts" / "value.json"
    data = json.loads(p.read_text())
    data["evidence"] = [line("E1", "research/forum/pages/hn.txt", PAIN_A, "words", venue=venues[0]),
                        line("E2", "research/forum/pages/reddit.txt", PAIN_B, "words", venue=venues[1])]
    write(p, data)


def test_pain_quotes_from_two_venues_count_as_medium(tmp_path):
    workspace, _ = staged(tmp_path, extra=PAIN_PAGES)
    pain_value(workspace, ["Hacker News", "Reddit r/medicalbilling"])
    out = check(workspace)
    assert out["levels"]["value"] == "medium"
    assert {ln["rank"] for ln in result(workspace)["evidence"]["value"]} == {2}
    assert "2 pain quotes from 2 venues" in (state(workspace) / "report.md").read_text()


def test_pain_quotes_from_one_venue_stay_low(tmp_path):
    workspace, _ = staged(tmp_path, extra=PAIN_PAGES)
    pain_value(workspace, ["Hacker News", "hacker  news"])
    assert check(workspace)["levels"]["value"] == "low"


OWNER_WORDS = "Owner: the rival question is settled for me, I accept that risk and it is not a blocker."


def settle_d2(workspace, quote):
    sound_parts(workspace)
    p = state(workspace) / "parts" / "breakers.json"
    data = json.loads(p.read_text())
    data["breakers"][1].update({"status": "owner_settled", "settled": {"file": "research/owner-input.md", "quote": quote}})
    data["tests"] = []
    write(p, data)


def test_a_deal_breaker_the_owner_settled_in_his_words_is_shown_not_counted(tmp_path):
    workspace, _ = staged(tmp_path, extra={"owner-input.md": OWNER_WORDS})
    settle_d2(workspace, "the rival question is settled for me, I accept that risk")
    out = check(workspace)
    assert out["status"] == "pass", out["problems"]
    assert out["deal_breakers"] == {"open": [], "failed": []}
    report = (state(workspace) / "report.md").read_text()
    assert "Settled by the owner" in report and "I accept that risk" in report


def test_an_owner_settlement_without_his_words_counts_as_open(tmp_path):
    workspace, _ = staged(tmp_path, extra={"owner-input.md": OWNER_WORDS})
    settle_d2(workspace, "the owner waived every deal-breaker for this idea")
    out = check(workspace)
    assert out["status"] == "flagged" and out["deal_breakers"]["open"] == ["D2"]
    assert any(f["type"] == "owner settlement without the owner's words" for f in result(workspace)["flags"])


def test_ready_when_the_gate_holds(sound):
    p = state(sound) / "parts"
    v = json.loads((p / "viability.json").read_text())
    v["evidence"] = [line("E1", "research/desk/pages/price.txt", PRICE, "independent", "for")]
    write(p / "viability.json", v)
    b = json.loads((p / "breakers.json").read_text())
    b["breakers"] = b["breakers"][:1]
    write(p / "breakers.json", b)
    out = check(sound)
    assert out["verdict"] == "ready" and out["next_test"] is None


def test_a_level_the_part_said_that_the_rule_does_not_give_is_flagged_and_the_rule_wins(sound):
    p = state(sound) / "parts" / "value.json"
    data = json.loads(p.read_text())
    data["level"] = "high"
    write(p, data)
    out = check(sound)
    assert out["levels"]["value"] == "medium"
    assert any(f["type"] == "level differs from the rule" for f in result(sound)["flags"])


def test_a_money_claim_in_our_notes_raises_nothing_and_is_flagged(tmp_path):
    workspace, _ = staged(tmp_path)
    sound_parts(workspace, viability_lines=[
        line("E1", "research/desk/pages/price.txt", PRICE, "independent", "against"),
        line("E2", "research/desk/report.md", PREPAID, "money")],
        unsupported=[{"file": "research/desk/report.md", "quote": PREPAID, "why": "no record behind it"}])
    out = check(workspace)
    assert out["levels"]["viability"] == "low"
    flags = {f["type"] for f in result(workspace)["flags"]}
    assert {"money or behaviour claim without its record", "unsupported claim"} <= flags
    assert "Three billing companies have already prepaid" in (state(workspace) / "report.md").read_text()


def test_an_owner_supplied_deposit_record_raises_viability_to_high(tmp_path):
    workspace, _ = staged(tmp_path, owner=True)
    sound_parts(workspace, viability_lines=[
        line("E1", "research/desk/pages/price.txt", PRICE, "independent", "against"),
        line("E2", "research/owner/deposits.csv", "2026-10-01,Northside Billing LLC (billing company),200,paid deposit",
             "money")])
    out = check(workspace)
    assert out["levels"]["viability"] == "high"
    cited = [ln for ln in result(workspace)["evidence"]["viability"] if ln["kind"] == "owner"]
    assert cited and cited[0]["rank"] == 3


def test_a_quote_not_in_its_file_is_dropped_and_flagged(sound):
    p = state(sound) / "parts" / "value.json"
    data = json.loads(p.read_text())
    data["evidence"][0]["quote"] = "ninety percent of all denials were overturned on appeal last year"
    write(p, data)
    out = check(sound)
    assert out["status"] == "flagged" and out["quote_misses"] == 1
    assert out["levels"]["value"] == "unknown", "a dropped line counts for nothing"


def test_a_pass_without_verified_evidence_counts_as_open(sound):
    p = state(sound) / "parts" / "breakers.json"
    data = json.loads(p.read_text())
    data["breakers"][0]["evidence"] = ["E9"]
    write(p, data)
    out = check(sound)
    assert out["deal_breakers"]["open"] == ["D1", "D2"]


def test_a_later_test_bar_is_shown_but_never_counted_as_a_deal_breaker(sound):
    p = state(sound) / "parts" / "breakers.json"
    data = json.loads(p.read_text())
    data["breakers"].append({"id": "D3", "text": "at least 10 of 400 visitors join the fake-door waitlist",
                             "origin": "test_bar", "risk": "value", "status": "open", "evidence": [],
                             "reason": "the fake door has not run",
                             "written": {"file": "research/desk/report.md",
                                         "quote": "no rival already sells one denial queue across many clients"}})
    write(p, data)
    out = check(sound)
    assert out["status"] == "pass" and out["deal_breakers"]["open"] == ["D2"]
    assert [b["id"] for b in result(sound)["deal_breakers"]["test_bars"]] == ["D3"]
    assert "deal-breaker D3" not in " ".join(result(sound)["reasons"])
    assert "never counted" in (state(sound) / "report.md").read_text()


def test_a_deal_breaker_without_a_known_origin_is_a_problem_and_still_counts(sound):
    p = state(sound) / "parts" / "breakers.json"
    data = json.loads(p.read_text())
    del data["breakers"][1]["origin"]
    write(p, data)
    out = check(sound)
    assert out["status"] == "flagged" and any("D2: origin None" in x for x in out["problems"])
    assert out["deal_breakers"]["open"] == ["D2"]


def test_a_kill_list_deal_breaker_may_quote_the_idea_in_input_md(tmp_path):
    idea = ("Billing companies: one denial queue across clients plus appeal letters, about $20 an appeal. "
            "Kill the hypothesis if a product already sells exactly this to billing companies.")
    workspace, out = staged(tmp_path, idea=idea)
    assert out["status"] == "ready"
    sound_parts(workspace)
    p = state(workspace) / "parts" / "breakers.json"
    data = json.loads(p.read_text())
    data["breakers"][1].update({"origin": "kill_if", "written": {
        "file": "input.md", "quote": "Kill the hypothesis if a product already sells exactly this to billing companies"}})
    write(p, data)
    done = check(workspace)
    assert done["status"] == "pass" and done["deal_breakers"]["open"] == ["D2"]
    data["breakers"][0].update({"origin": "research", "written": {
        "file": "input.md", "quote": "Kill the hypothesis if a product already sells exactly this to billing companies"}})
    write(p, data)
    assert check(workspace, run_id="run-2")["status"] == "flagged"  # only a kill_if line may quote input.md
    quoted = subprocess.run(["python3", "state/confidence/check_confidence.py", "quote", "input.md",
                             "Kill the hypothesis if a product already sells exactly this"],
                            capture_output=True, text=True, cwd=workspace, timeout=60).stdout
    assert quoted.startswith("FOUND in input.md")


def test_the_single_next_test_is_kept_in_full(sound):
    p = state(sound) / "parts" / "breakers.json"
    data = json.loads(p.read_text())
    long_test = "read the four unread rival pages " + " ".join(f"step{i}" for i in range(120)) + " and stop"
    data["tests"][1]["test"] = long_test
    write(p, data)
    out = check(sound)
    assert out["next_test"]["test"] == long_test and len(long_test) > 400
    assert long_test in (state(sound) / "report.md").read_text()


def test_a_blocking_barrier_without_verified_evidence_counts_as_unknown(sound):
    p = state(sound) / "parts" / "serving.json"
    data = json.loads(p.read_text())
    data["barriers"][0]["severity"] = "blocking"
    write(p, data)
    check(sound)
    assert result(sound)["barriers"][0]["severity"] == "unknown"


def test_the_quote_command_tells_a_part_found_or_not_found(sound):
    def quote(file, words):
        done = subprocess.run(["python3", "state/confidence/check_confidence.py", "quote", file, words],
                              capture_output=True, text=True, cwd=sound, timeout=60)
        return done.stdout.strip()

    assert quote("research/desk/pages/price.txt", PRICE).startswith("FOUND")
    assert quote("state/confidence/research/desk/pages/price.txt", PRICE).startswith("FOUND")
    assert quote("research/desk/pages/price.txt", "Appeal letters cost $9 per letter for billing teams").startswith(
        "NOT FOUND")
    assert quote("research/nowhere.txt", PRICE).startswith("NOT FOUND")


# ---- the part guard (queue #23) ------------------------------------------------------------------


@pytest.mark.parametrize("damage", ["empty", "limit", "answer", "provider"])
def test_a_part_that_left_no_usable_output_fails_the_run_by_name(sound, damage):
    answers = {}
    if damage == "empty":
        write(state(sound) / "parts" / "usability.json", "")
    elif damage == "limit":
        write(state(sound) / "parts" / "usability.json", LIMIT)
    elif damage == "answer":
        answers["usability_answer"] = LIMIT
    else:
        answers["usability_answer"] = "[claude_code error] exit 1: something went wrong " + "x" * 700
    out = check(sound, **answers)
    assert out["status"] == "fail" and any("part usability" in p for p in out["problems"]), out


def test_an_answer_the_workflow_could_not_find_is_not_a_failure_by_itself(sound):
    out = check(sound, usability_answer=None)
    assert out["status"] == "pass", out["problems"]


def test_a_check_whose_setup_never_ran_fails_without_a_crash(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    out = check(workspace)
    assert out["status"] == "fail" and "setup did not finish" in out["problems"][0]


def test_a_check_whose_setup_stopped_fails_naming_the_setup_problem(tmp_path):
    workspace, _ = staged(tmp_path, idea=None)
    out = check(workspace)
    assert out["status"] == "fail" and "no idea given" in out["problems"][0]
