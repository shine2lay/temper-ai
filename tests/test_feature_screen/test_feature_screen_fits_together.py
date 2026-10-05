"""The feature screen (configs/workflows/feature_screen.yaml, product role, queue #26) fits together.

It turns one product's evidence into 8-12 candidate features, rates every candidate on the owner's
three tests (would people see it within seconds, do the big players already give it away free,
does it fix one of the idea's real problems) and a build check, ranks them by a fixed rule and
designs the cheapest tests for the top three. Here: the configs run in that order and are fed
every value they use; the known-taken cases reach the check only; the method stays frozen; the
rank step applies the fixed rule; the check passes a sound screen and fails each kind of defect
(a planted case not taken, a quote not on its saved page, a rating its sub-scores do not give, a
part an account limit stopped, a tampered ranking, an incomplete or unmarked test design).
No model and no network: every part's output here is hand-written.
"""

import ast
import hashlib
import json
import os
import re
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
AGENTS = sorted(AGENTS_DIR.glob("feature_screen_*.yaml"))
ASSETS = AGENTS_DIR / "feature_screen_assets"
WORKFLOW = ROOT / "configs" / "workflows" / "feature_screen.yaml"
INJECTED = {"workspace_path", "run_id"}  # the script agent adds these to every template
LENSES = ("newness", "taken", "problem", "build")
# Frozen before the screen's first run (product research/feature-screen/BAR.md): a change to the
# method is a new version, landed on purpose with a new hash.
FROZEN = {
    "configs/agents/feature_screen_assets/method.md": "465694db63090922d435df248d63e1ae6678400c4e59eaa5cb2f0c8d4f1640c1",
}
LIMIT = "You've hit your session limit \u00b7 resets 10:50pm (UTC)"
DONE = '```json\n{"status": "completed"}\n```'
PAGE = {
    "https://example.com/rival-reels": "Rival Trips. Paste a link to any travel reel and we turn it into a full trip plan, "
                                       "free for every traveler since 2024. Sign up free.",
    "https://news.example.org/planners": "News. Every big booking site now ships a free AI itinerary planner inside "
                                         "its app, with day-by-day plans in seconds.",
    "https://example.com/invites": "Case study. Each group trip invite brought 2.1 new sign-ups on average across "
                                   "the first year of the shared planning board.",
}
REPORT = ("# Evidence\n\nTravelers want somewhere new that fits them, not another generic list.\n"
          "Free planners are bundled everywhere by the big booking sites.\n"
          "Revenue per active user is small at $0.16-$8.32 a year.\n")


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


def screen(workspace):
    return workspace / "state" / "feature"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=1))


def save_page(workspace, url, text, http="200"):
    """A page as cite.py keeps it: first line its metadata, then the text."""
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt"
    write(screen(workspace) / "pages" / name, json.dumps({"url": url, "http": http}) + "\n" + text)


def staged(tmp_path, run_id="run-1", **values):
    """A fresh run workspace with the assets and the evidence staged, after the setup step."""
    workspace = tmp_path / "ws"
    (workspace / "_assets").mkdir(parents=True)
    for name in ("check_features.py", "cite.py", "method.md"):
        shutil.copyfile(ASSETS / name, workspace / "_assets" / name)
    write(workspace / "_evidence" / "README.md", "Read REPORT.md first.\n")
    write(workspace / "_evidence" / "REPORT.md", REPORT)
    values = {"idea": "A matcher that suggests places new to you that fit you.",
              "problems": "Reaching travelers cheaply; earning per user ($0.16-$8.32 a year).",
              "evidence_dir": str(workspace / "_evidence"), "seeds": "S1: Trip from a pasted travel reel\nS2: Places like one you love",
              "players": "Google, Expedia, Booking", "build_on": "46 place scores", "assets_dir": str(workspace / "_assets"),
              "run_id": run_id, **values}
    return workspace, step("feature_screen_setup", workspace, **values)


# Ratings for the sound screen: (newness sub, taken rating, problem sub, build sub) per candidate.
SOUND = {
    "F1": (("yes", "yes", "yes"), "taken", ("strong", "medium"), ("strong", "open")),   # seed S1, known taken
    "F2": (("yes", "partly", "yes"), "partly", ("medium", "weak"), ("strong", "open")),  # seed S2
    "F3": (("yes", "yes", "yes"), "open", ("strong", "weak"), ("strong", "open")),
    "F4": (("yes", "yes", "partly"), "open", ("weak", "medium"), ("medium", "approval")),
    "F5": (("partly", "partly", "yes"), "partly", ("weak", "strong"), ("strong", "open")),
    "F6": (("no", "no", "yes"), "open", ("strong", "strong"), ("strong", "open")),
    "F7": (("yes", "no", "no"), "open", ("medium", "medium"), ("weak", "gated")),
    "F8": (("partly", "no", "no"), "taken", ("weak", "weak"), ("medium", "open")),
}


def newness_rating(sub):
    total = sum({"yes": 2, "partly": 1, "no": 0}[v] for v in sub)
    return "strong" if total >= 5 else "medium" if total >= 3 else "weak"


def build_rating(fit, access):
    if access == "gated" or fit == "weak":
        return "weak"
    return "strong" if fit == "strong" and access == "open" else "medium"


def sound_parts(workspace):
    """Hand-written outputs of generate and the four lenses that meet the method."""
    root = screen(workspace)
    for url, text in PAGE.items():
        save_page(workspace, url, text)
    cands = []
    for n, cid in enumerate(SOUND, 1):
        cands.append({"id": cid, "seed_id": {"F1": "S1", "F2": "S2"}.get(cid), "name": f"Feature {n}",
                      "what_user_sees": f"Something new number {n}", "job": "choose where to go",
                      "evidence": [{"file": "evidence/REPORT.md", "quote": "Travelers want somewhere new that fits them"}],
                      "notes": ""})
    write(root / "candidates.json", {"candidates": cands})
    write(root / "candidates.md", "# Candidates\n\n" + "\n".join(f"- {c['id']} {c['name']}" for c in cands) + "\n")
    lenses = {lens: {"lens": lens, "ratings": [], "claims": [], "guesses": [], "inaccessible": []} for lens in LENSES}
    for n, (cid, (new, taken, problem, build)) in enumerate(SOUND.items(), 1):
        for lens in LENSES:
            lenses[lens]["guesses"].append({"id": f"G{n}", "candidate": cid, "guess": "a labelled guess", "why": "test"})
        lenses["newness"]["ratings"].append({"candidate": cid, "sub": dict(zip(("seconds", "new", "fits"), new, strict=True)),
                                             "rating": newness_rating(new), "reason": "r", "claims": [], "guesses": [f"G{n}"]})
        checked = [{"player": p, "found": "nothing matching", "claims": []} for p in ("Google", "Expedia", "Booking")]
        row = {"candidate": cid, "sub": {"checked": checked}, "rating": taken, "reason": "r", "claims": [], "guesses": [f"G{n}"]}
        if taken == "taken":
            url = "https://example.com/rival-reels" if cid == "F1" else "https://news.example.org/planners"
            quote = ("Paste a link to any travel reel and we turn it into a full trip plan" if cid == "F1"
                     else "Every big booking site now ships a free AI itinerary planner")
            lenses["taken"]["claims"].append({"id": f"C{n}", "candidate": cid, "claim": "live and free", "quote": quote,
                                              "url": url, "date": "2024-05-01", "fetched": "2026-10-05",
                                              "kind": "product page", "quality": "primary", "how": "cite"})
            row["claims"] = [f"C{n}"]
        lenses["taken"]["ratings"].append(row)
        lenses["problem"]["ratings"].append({"candidate": cid, "sub": dict(zip(("reach", "money"), problem, strict=True)),
                                             "rating": max(problem, key={"strong": 2, "medium": 1, "weak": 0}.get),
                                             "reason": "r", "claims": [], "guesses": [f"G{n}"]})
        lenses["build"]["ratings"].append({"candidate": cid, "sub": dict(zip(("assets_fit", "data_access"), build, strict=True)),
                                           "rating": build_rating(*build), "reason": "r", "claims": [], "guesses": [f"G{n}"]})
    lenses["problem"]["claims"].append({"id": "C1", "candidate": "F6", "claim": "invites spread", "quote":
                                        "Each group trip invite brought 2.1 new sign-ups on average",
                                        "url": "https://example.com/invites", "date": "2025-01-01", "fetched": "2026-10-05",
                                        "kind": "study", "quality": "secondary", "how": "cite"})
    lenses["problem"]["ratings"][5]["claims"] = ["C1"]
    for lens, data in lenses.items():
        write(root / "lenses" / f"{lens}.json", data)
        write(root / "lenses" / f"{lens}.md", f"# {lens}\n\n| candidate | rating |\n|---|---|\n")


def rung(number, **over):
    base = {"rung": number, "kind": "free" if number == 1 else "paid", "method": "a fake door", "metric": "click rate",
            "threshold": 0.05, "sample": 300, "duration_days": 14, "pass_rule": "pass at 5% of 300",
            "kill_rule": "kill under 2% of 300", "basis": ["evidence/REPORT.md", "G1", "problem:C1"]}
    base.update({"cost_usd": 0, "needs_owner": False} if number == 1 else {"owner_go_ahead": True, "budget_usd": 50})
    base.update(over)
    return base


def sound_tests(workspace, top):
    write(screen(workspace) / "tests.json", {
        "tests": [{"candidate": cid, "riskiest_assumption": "people notice it and act", "why_riskiest": "no behaviour yet",
                   "rungs": [rung(1), rung(2)]} for cid in top],
        "claims": [], "guesses": [{"id": "G1", "candidate": top[0], "guess": "a benchmark guess", "why": "test"}]})
    write(screen(workspace) / "tests.md", "# Tests\n\nThree designs.\n")


def check(workspace, planted="S1", run_id="run-1", **answers):
    values = {f"{part}_answer": DONE for part in ("generate", "newness", "taken", "problem", "build", "design")}
    values.update(answers)
    return step("feature_screen_check", workspace, planted_taken=planted, run_id=run_id, **values)


@pytest.fixture
def sound(tmp_path):
    """A whole sound screen, setup to check."""
    workspace, out = staged(tmp_path)
    assert out["status"] == "ready", out
    sound_parts(workspace)
    ranked = step("feature_screen_rank", workspace)
    assert ranked["status"] == "ranked", ranked
    sound_tests(workspace, ranked["top"])
    return workspace


def problems_of(result):
    return "\n".join(result["problems"])


# ---- the configs ---------------------------------------------------------------------------------


def test_the_workflow_runs_setup_generate_four_lenses_rank_design_check():
    assert {p.stem for p in AGENTS} == {agent(p)["name"] for p in AGENTS}, "each agent file is named after its agent"
    n = nodes()
    assert list(n) == ["setup", "generate", "lens_newness", "lens_taken", "lens_problem", "lens_build", "rank",
                       "design", "check"]
    used = {node["agent"] for node in n.values()}
    assert used == {p.stem for p in AGENTS}, "the workflow runs every feature_screen agent"
    ready = {"source": "setup.structured.status", "operator": "equals", "value": "ready"}
    assert "depends_on" not in n["setup"] and "condition" not in n["setup"]
    assert n["generate"]["depends_on"] == ["setup"] and n["generate"]["condition"] == ready
    for lens in LENSES:
        node = n[f"lens_{lens}"]
        assert node["agent"] == "feature_screen_lens" and node["input_map"] == {"lens": lens}
        assert node["depends_on"] == ["generate"] and node["condition"] == ready, "the four lenses run side by side"
    assert n["rank"]["depends_on"] == [f"lens_{lens}" for lens in LENSES] and n["rank"]["run_after_failure"] is True
    assert n["design"]["depends_on"] == ["rank"]
    assert n["design"]["condition"] == {"source": "rank.structured.status", "operator": "equals", "value": "ranked"}
    assert n["check"]["depends_on"] == ["design"] and n["check"]["run_after_failure"] is True
    assert "condition" not in n["check"], "the check runs on every path"


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
    n = nodes()

    def ancestors(name):
        seen, todo = set(), list(n[name].get("depends_on") or [])
        while todo:
            dep = todo.pop()
            if dep not in seen:
                seen.add(dep)
                todo += n[dep].get("depends_on") or []
        return seen

    for name, node in n.items():
        fed = node.get("input_map") or {}
        for value in fed.values():
            head, _, field = value.partition(".")
            if head == "input":
                assert field in wf["inputs"], f"{name}: {value} is not an input"
            elif field == "output":
                assert head in ancestors(name), f"{name}: {value} is not from a step it waits for"
            else:
                assert value in LENSES, f"{name}: {value} is neither an input, a step's answer nor a lens"
        for template in templates_of(by_name(node["agent"])):
            for used in meta.find_undeclared_variables(env.parse(template)) - set(fed) - INJECTED:
                # Unfed, a value renders empty through `(x or '')` or as __unwired__, never as text.
                assert f"({used} or '')" in template or f"{used} is string else '__unwired__'" in template, (
                    f"{node['agent']} needs {used} fed or defaulted")
            if not fed:
                assert not meta.find_undeclared_variables(env.parse(template)) - INJECTED, f"{name} uses unfed values"


def test_only_the_check_learns_which_seeds_are_known_taken():
    n = nodes()
    holders = [name for name, node in n.items() if "input.planted_taken" in (node.get("input_map") or {}).values()]
    assert holders == ["check"], "an agent that knew the expected answer would grade itself"
    for path in AGENTS:
        text = path.read_text()
        if path.stem != "feature_screen_check":
            assert "planted_taken }}" not in text and "(planted_taken or" not in text, f"{path.stem} reads planted_taken"


def test_the_model_steps_keep_claude_codes_own_tools_and_the_rules():
    rules = {
        "feature_screen_generate": ("Do not browse the web", "seed_id", "word for word", "8 to 12"),
        "feature_screen_lens": ("cite.py quote", "Never get around a block", "Desk research only", "{{ lens }}"),
        "feature_screen_design": ("owner_go_ahead", "never run them", "fixed now", "Never get around a block"),
    }
    for name, words in rules.items():
        cfg = by_name(name)
        assert cfg["type"] == "llm" and cfg["provider"] == "claude"
        assert "tools" not in cfg, "provider claude refuses temper tool schemas; it uses its own tools"
        text = cfg["system_prompt"] + cfg["task_template"]
        for rule in words:
            assert rule in text, f"{name} lost {rule!r}"


def test_the_method_is_frozen():
    for rel, sha in FROZEN.items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == sha, f"{rel} changed: a new method version"


def test_the_workflow_outputs_name_fields_the_check_prints(sound):
    printed = set(check(sound))
    for ref in workflow()["outputs"].values():
        node, _, field = ref.partition(".structured.")
        assert node == "check" and field in printed, f"{ref}: the check never prints `{field}`"
    for name in ("feature_screen_check", "feature_screen_rank"):
        fallback = re.search(r"echo '(\{.*\})'", by_name(name)["script_template"])
        assert fallback, f"{name} no longer says what happened when setup did not finish"
    fallback = json.loads(re.search(r"echo '(\{.*\})'", by_name("feature_screen_check")["script_template"]).group(1))
    assert set(fallback) == printed, "the check's fallback prints what the check prints"


def test_every_config_has_a_product_ownership_row():
    section = (ROOT / "docs" / "departments.md").read_text().split("### product (", 1)[1].split("\n### ", 1)[0]
    assets = sorted(p for p in ASSETS.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    for path in [WORKFLOW, *AGENTS, *assets]:
        rel = path.relative_to(ROOT / "configs").as_posix()
        assert f"| `{rel}` |" in section, f"{rel} has no product ownership row"
    assert int(section.split(")", 1)[0]) == section.count("\n| `"), "the product heading counts its rows"


def test_the_product_launcher_starts_feature_screen_as_a_live_workflow():
    tree = ast.parse((ROOT / "configs" / "product" / "bin" / "server_run.py").read_text())
    live = next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["LIVE"])
    assert "feature_screen" in live
    assert "start.sh $JOB feature_screen" in (ROOT / "docs" / "product-runs.md").read_text()


# ---- setup ---------------------------------------------------------------------------------------


def test_setup_stages_the_method_and_evidence_and_never_the_known_taken_cases(tmp_path):
    workspace, out = staged(tmp_path)
    assert out == {"status": "ready", "seeds": ["S1", "S2"], "evidence_files": 2, "problems": []}
    root = screen(workspace)
    for name in ("check_features.py", "cite.py", "method.md"):
        assert (root / name).read_bytes() == (ASSETS / name).read_bytes()
    assert (root / "evidence" / "REPORT.md").read_text() == REPORT
    text = (root / "input.md").read_text()
    for part in ("S1: Trip from a pasted travel reel", "S2: Places like one you love", "Google, Expedia, Booking",
                 "46 place scores", "evidence/REPORT.md", "earning per user"):
        assert part in text
    assert "taken" not in text.lower().replace("(none given: take them", ""), "input.md never hints at the expected answers"


@pytest.mark.parametrize("change, problem", [
    ({"idea": None}, "no idea given"),
    ({"problems": ""}, "no problems given"),
    ({"evidence_dir": "/etc"}, "outside the run workspace"),
    ({"evidence_dir": "missing"}, "not a folder"),
    ({"seeds": "S1: a\nS1: b"}, "seed ids repeat"),
])
def test_setup_stops_at_no_cost_on_a_bad_input(tmp_path, change, problem):
    _, out = staged(tmp_path, **change)
    assert out["status"] == "not_ready" and problem in out["problems"][0]


def test_setup_refuses_a_workspace_that_already_holds_a_screen(sound):
    out = step("feature_screen_setup", sound, idea="x", problems="y", evidence_dir=str(sound / "_evidence"),
               assets_dir=str(sound / "_assets"), run_id="run-2")
    assert out["status"] == "not_ready" and "already holds a screen" in out["problems"][0]


def test_an_input_the_run_did_not_give_is_empty_not_the_text_none(tmp_path):
    workspace, out = staged(tmp_path, seeds=None, players=None, build_on=None)
    assert out["status"] == "ready" and out["seeds"] == []
    text = (screen(workspace) / "input.md").read_text()
    assert "None" not in text and "(none given: take them from the evidence)" in text


# ---- rank: the fixed rule ------------------------------------------------------------------------


def test_rank_applies_the_fixed_rule(sound):
    ranking = json.loads((screen(sound) / "ranking.json").read_text())
    order = [r["id"] for r in ranking["rows"]]
    # F3 qualified, 8 points. F4, F2 and F5 qualified, 6 each: F5's newness is only medium, and F4's ground is
    # open where F2's is partly taken. F6 has 6 points too, but its newness is weak: below the must-have, it
    # comes after every qualified one. F1 and F8 are taken: out.
    assert ranking["top"] == ["F3", "F4", "F2"]
    assert order[:4] == ["F3", "F4", "F2", "F5"] and set(order[-2:]) == {"F1", "F8"}
    assert order.index("F6") > order.index("F5"), "a candidate below the must-have never jumps a qualified one"
    out = {r["id"] for r in ranking["rows"] if r["out"]}
    assert out == {"F1", "F8"}


def test_rank_says_not_ranked_when_a_lens_left_no_file(sound):
    (screen(sound) / "lenses" / "build.json").unlink()
    out = step("feature_screen_rank", sound)
    assert out["status"] == "not_ranked" and "build.json is missing" in out["problems"][0]


def test_rank_says_short_when_fewer_than_three_are_not_taken(sound):
    path = screen(sound) / "lenses" / "taken.json"
    data = json.loads(path.read_text())
    for row in data["ratings"]:
        if row["candidate"] not in ("F2", "F3"):
            row["rating"] = "taken"
    write(path, data)
    out = step("feature_screen_rank", sound)
    assert out["status"] == "short" and out["top"] == ["F3", "F2"]


# ---- the check -----------------------------------------------------------------------------------


def test_a_sound_screen_passes_with_its_known_taken_case_sourced(sound):
    out = check(sound)
    assert out["status"] == "pass", out["problems"]
    assert out["planted"] == {"S1": {"candidate": "F1", "rating": "taken", "sourced": True}}
    assert out["shortlist"] == ["F3 Feature 3", "F4 Feature 4", "F2 Feature 2"]
    report = (screen(sound) / "report.md").read_text()
    for part in ("## Shortlist", "NEEDS THE OWNER'S GO-AHEAD", "out (taken)", "GUESS: a labelled guess"):
        assert part in report
    sample = (screen(sound) / "sample.md").read_text()
    assert sample.count("\n## ") == 3, "every claim is drawn when there are fewer than ten"
    assert "https://example.com/rival-reels" in sample


def test_the_sample_is_the_same_for_the_same_run_and_differs_by_run(sound):
    first = json.loads(json.dumps(check(sound, run_id="run-1")))
    again = json.loads((screen(sound) / "check.json").read_text())["sample"]
    assert check(sound, run_id="run-1") == first
    assert json.loads((screen(sound) / "check.json").read_text())["sample"] == again


def test_a_known_taken_case_that_comes_out_open_fails(sound):
    out = check(sound, planted="S1,S2")
    assert out["status"] == "fail"
    assert "known-taken case S2 (F2 Feature 2) came out partly, not taken" in problems_of(out)


def test_a_taken_rating_needs_a_checked_web_page(sound):
    path = screen(sound) / "lenses" / "taken.json"
    data = json.loads(path.read_text())
    data["claims"][0]["url"] = "evidence/REPORT.md"
    data["claims"][0]["quote"] = "Free planners are bundled everywhere by the big booking sites"
    write(path, data)
    out = check(sound)
    assert out["status"] == "fail"
    assert "taken F1: rated taken, but no cited claim from a web page" in problems_of(out)
    assert out["planted"]["S1"]["sourced"] is False


def test_a_quote_not_on_its_saved_page_fails(sound):
    path = screen(sound) / "lenses" / "problem.json"
    data = json.loads(path.read_text())
    data["claims"][0]["quote"] = "Each group trip invite brought 9.9 new sign-ups on average"
    write(path, data)
    out = check(sound)
    assert out["status"] == "fail" and "problem C1: cited, but quote not on the saved page" in problems_of(out)


def test_a_page_cite_never_read_or_that_was_blocked_fails(sound):
    save_page(sound, "https://example.com/invites", "Forbidden", http="403")
    out = check(sound)
    assert "problem C1: cited, but the saved page answered 403" in problems_of(out)
    path = screen(sound) / "lenses" / "problem.json"
    data = json.loads(path.read_text())
    data["claims"][0]["url"] = "https://example.com/never-read"
    write(path, data)
    assert "no saved page (cite.py never read this URL)" in problems_of(check(sound))


def test_a_rating_its_sub_scores_do_not_give_fails(sound):
    path = screen(sound) / "lenses" / "newness.json"
    data = json.loads(path.read_text())
    data["ratings"][2]["rating"] = "medium"
    write(path, data)
    out = check(sound)
    assert out["status"] == "fail" and "newness F3: rated medium, but its sub-scores give strong" in problems_of(out)


def test_a_missing_or_unsupported_rating_fails(sound):
    path = screen(sound) / "lenses" / "build.json"
    data = json.loads(path.read_text())
    data["ratings"] = [r for r in data["ratings"] if r["candidate"] != "F5"]
    data["ratings"][0]["guesses"] = []
    write(path, data)
    text = problems_of(check(sound))
    assert "build: candidate F5 has 0 ratings (needs exactly one)" in text
    assert "build F1: no source and no labelled guess behind the rating" in text


def test_an_open_rating_needs_three_players_checked(sound):
    path = screen(sound) / "lenses" / "taken.json"
    data = json.loads(path.read_text())
    data["ratings"][2]["sub"]["checked"] = data["ratings"][2]["sub"]["checked"][:2]
    write(path, data)
    assert "taken F3: rated open after checking 2 players (needs at least 3)" in problems_of(check(sound))


@pytest.mark.parametrize("part", ["generate", "newness", "taken", "problem", "build", "design"])
def test_a_part_whose_final_answer_is_a_limit_message_fails_by_name(sound, part):
    out = check(sound, **{f"{part}_answer": LIMIT})
    assert out["status"] == "fail" and f"{part}: its final answer is an account-limit or error message" in problems_of(out)


def test_a_part_whose_files_are_a_limit_message_fails(sound):
    write(screen(sound) / "lenses" / "taken.json", LIMIT)
    write(screen(sound) / "candidates.md", LIMIT)
    text = problems_of(check(sound))
    assert "lenses/taken.json is an account-limit or error message" in text
    assert "candidates.md is an account-limit or error message" in text


def test_an_answer_the_workflow_could_not_find_is_not_a_failure_by_itself(sound):
    out = check(sound, design_answer=None)
    assert out["status"] == "pass", out["problems"]


def test_candidates_must_number_eight_to_twelve_include_every_seed_and_quote_the_evidence(sound):
    path = screen(sound) / "candidates.json"
    data = json.loads(path.read_text())
    data["candidates"][1]["seed_id"] = None
    data["candidates"][2]["evidence"][0]["quote"] = "Travelers want somewhere old that bores them"
    write(path, data)
    text = problems_of(check(sound))
    assert "seed S2 is not among the candidates" in text
    assert "candidate F3: evidence quote not in evidence/REPORT.md" in text
    data["candidates"] = data["candidates"][:7]
    write(path, data)
    assert "7 candidates: the method asks for 8-12" in problems_of(check(sound))


def test_a_ranking_that_is_not_the_fixed_rules_fails(sound):
    path = screen(sound) / "ranking.json"
    data = json.loads(path.read_text())
    data["top"] = ["F6", "F3", "F2"]
    write(path, data)
    out = check(sound)
    assert "ranking.json's top ['F6', 'F3', 'F2'] is not the fixed rule's ['F3', 'F4', 'F2']" in problems_of(out)


@pytest.mark.parametrize("change, problem", [
    ({"owner_go_ahead": False}, "rung 2: a paid or contact rung must be marked owner_go_ahead true"),
    ({"budget_usd": None}, "rung 2: a paid rung needs budget_usd"),
    ({"threshold": "about five percent"}, "rung 2: threshold is not a number"),
    ({"sample": 0}, "rung 2: sample is not a positive number"),
    ({"kind": "free"}, "rung 2: kind 'free' is not paid or contact"),
    ({"basis": ["taken:C99"]}, "rung 2: basis taken:C99 is not in the taken lens"),
    ({"basis": []}, "rung 2: no basis for its numbers"),
])
def test_an_incomplete_or_unmarked_paid_rung_fails(sound, change, problem):
    path = screen(sound) / "tests.json"
    data = json.loads(path.read_text())
    data["tests"][0]["rungs"][1].update(change)
    write(path, data)
    out = check(sound)
    assert out["status"] == "fail" and f"tests F3 {problem}" in problems_of(out)


def test_the_cheapest_rung_is_free_or_first_party_and_costs_nothing(sound):
    path = screen(sound) / "tests.json"
    data = json.loads(path.read_text())
    data["tests"][1]["rungs"][0].update({"kind": "paid", "cost_usd": 20})
    write(path, data)
    text = problems_of(check(sound))
    assert "tests F4 rung 1: kind 'paid' is not free or first-party" in text
    assert "tests F4 rung 1: the cheapest rung must cost 0" in text


def test_tests_must_cover_exactly_the_top_three(sound):
    path = screen(sound) / "tests.json"
    data = json.loads(path.read_text())
    data["tests"][2]["candidate"] = "F6"
    write(path, data)
    assert "tests cover ['F3', 'F4', 'F6'], not the top three ['F3', 'F4', 'F2']" in problems_of(check(sound))


def test_another_runs_screen_fails(sound):
    assert "holds another run's screen" in problems_of(check(sound, run_id="run-9"))


def test_a_screen_whose_setup_never_ran_fails_without_a_crash(tmp_path):
    workspace = tmp_path / "empty"
    workspace.mkdir()
    out = step("feature_screen_check", workspace, planted_taken="S1", run_id="r")
    assert out["status"] == "fail" and "the setup did not finish" in out["problems"][0]
    assert step("feature_screen_rank", workspace)["status"] == "not_ranked"
