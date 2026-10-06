"""The early tech and serving screen (configs/workflows/scan_serving.yaml, product role) fits together.

It re-ranks a saved market scan's candidates by tech fit, build feasibility and serving barriers
(product PLAN.md step 2c; accepted at trial 10 of queue #21). Its configs: the workflow runs every
scan_serving agent and then the unchanged scan_check, each script step parses under /bin/sh, the model
steps keep Claude Code's own tools, every template variable is fed by the workflow and the outputs name
fields the reviewer prints. Its helpers: check_serving.py names a scan's 1-8 saved candidates in the
heading styles scans have written and passes only a screen that keeps all of them with sound arithmetic,
floors and quotes, names the part each F, T and R call rated (queue #30) and names, for each pair of
neighbouring ranks, the one-step factor call that would swap them; prepare copies a saved scan into a fresh workspace and takes retained replay pages
only when they match exactly; cite.py is desk_setup's own. No model and no network: every input here is
synthetic.
"""

import copy
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
AGENTS = sorted(AGENTS_DIR.glob("scan_serving_*.yaml"))
ASSETS = AGENTS_DIR / "scan_serving_assets"
WORKFLOW = ROOT / "configs" / "workflows" / "scan_serving.yaml"
INJECTED = {"workspace_path", "run_id"}  # the agents add these to every template
ORDER = ["scan_serving_prepare", "scan_serving_pain", "scan_serving_screen", "scan_serving_evidence",
         "scan_serving_audit", "scan_serving_verify", "scan_check", "scan_serving_grade"]


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


def load_checker():
    """check_serving.py as prepare copies it into a run, loaded without leaving bytecode in the assets."""
    path = ASSETS / "check_serving.py"
    module = types.ModuleType("scan_serving_check")
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


checker = load_checker()


# ---- the configs ---------------------------------------------------------------------------------


def test_the_workflow_runs_the_screen_then_the_unchanged_scan_check():
    assert {p.stem for p in AGENTS} == {agent(p)["name"] for p in AGENTS}, "each agent file is named after its agent"
    nodes = workflow()["nodes"]
    assert [n["agent"] for n in nodes] == ORDER
    assert set(ORDER) - {"scan_check"} == {p.stem for p in AGENTS}, "the workflow runs every screen agent"
    for before, after in zip(nodes, nodes[1:], strict=False):
        assert after["depends_on"] == [before["name"]], "one step at a time, in order"


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
    assert "tools" not in cfg, "provider claude refuses temper tool schemas; it uses its own Bash/Read/Write/Web tools"


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


def test_the_workflow_outputs_name_fields_the_reviewer_prints():
    prompt = by_name("scan_serving_grade")["system_prompt"]
    contract = re.search(r'(\{"status":"completed",.*?"issues":\[\]\})', prompt, re.S)
    assert contract, "scan_serving_grade no longer shows the JSON it finishes with"
    printed = set(json.loads(contract.group(1)))
    for ref in workflow()["outputs"].values():
        node, _, field = ref.partition(".structured.")
        assert node == "review" and field in printed, f"{ref}: the reviewer never prints `{field}`"


def test_the_cite_helper_is_desk_setups_own():
    script = by_name("desk_setup")["script_template"]
    found = re.search(r"^cat > state/desk/cite\.py <<'CITEEOF'\n(.*?)\nCITEEOF$", script, re.S | re.M)
    assert found, "desk_setup no longer writes cite.py"
    assert (ASSETS / "cite.py").read_text() == found.group(1) + "\n", "the screen's cite.py must be desk_setup's"


# ---- naming the saved candidates ----------------------------------------------------------------------

STYLES = {
    "trial-replay": "### #{n} — {name}. Score 1.00. MARKET-LED",
    "2026-10-01": "### {n}. {name} — score 12.00",
    "parenthesised": "### {n}) {name} (score 3.1)",
    "no-score": "### {n}. {name}",
}
NAMES = ["Trades call handling (electrical first)", "Unit-turn coordination — small landlords",
         "Dental insurance verification", "AP invoice capture. Sold through bookkeepers",
         "Workers'-comp bill review for single-state TPAs"]


def shortlist(count, style=STYLES["trial-replay"], names=None):
    """A saved scan's shortlist.md: sections, a ranking table, then one heading per ranked candidate."""
    names = names or [f"Candidate {n}" for n in range(1, count + 1)]
    lines = ["# Shortlist (synthetic)", "## Ranking table", "| Rank | Candidate | Score |", "## Ranked shortlist"]
    for n, name in enumerate(names, 1):
        lines += [style.format(n=n, name=name), "- Pain: synthetic field", ""]
    return "\n".join([*lines, "## Excluded", "- none"]) + "\n"


@pytest.mark.parametrize("style", STYLES.values(), ids=STYLES.keys())
def test_the_saved_candidates_are_named_in_every_heading_style(style):
    names = checker.parse_identities(shortlist(len(NAMES), style, NAMES))
    assert names == {f"C{n}": name for n, name in enumerate(NAMES, 1)}


def test_the_trial_replay_headings_give_the_names_trial_10_used():
    """Trial 10 named its five candidates with exactly this pattern, and its retained pages are keyed by them."""
    text = shortlist(len(NAMES), STYLES["trial-replay"], NAMES)
    before = {"C" + n: name for n, name in re.findall(r"^### #(\d+) — (.*?)\. Score ", text, re.M)}
    assert checker.parse_identities(text) == before


@pytest.mark.parametrize(("text", "problem"), [
    (shortlist(9), "n <= 8"),
    (shortlist(3).replace("### #3 —", "### #4 —"), "1..n"),
    ("# Shortlist\n## Ranked shortlist\nNothing ranked.\n", "no ranked candidate headings"),
], ids=["nine candidates", "a gap in the ranks", "no headings"])
def test_a_shortlist_the_screen_cannot_name_is_refused(text, problem):
    with pytest.raises(ValueError, match=re.escape(problem)):
        checker.parse_identities(text)


# ---- the mechanical check -------------------------------------------------------------------------------


def candidate(n):
    found = {"id": f"C{n}", "name": f"Candidate {n}", "original_rank": n, "rank": n,
             "P": 2, "W": 2, "O": 2, "T": 2, "F": 2, "B": 3, "R": 1, "score": 2.6667,
             "technical_unknown": True, "serving_unknown": True,
             "claims": [{"claim": "Synthetic fixture only", "url": "https://example.invalid/source",
                         "quote": "Documented example source statement.", "source_kind": "primary",
                         "saved_page": "state/desk/pages/source.txt", "scope_and_date": "Fictional"}]}
    for group, keys in checker.FIELDS.items():
        found[group] = {key: "Synthetic nonempty explanation" for key in keys}
    found["factor_reasons"].update(
        F="Hardest part: synthetic reading step. Technique shown: yes - fixture. Inputs available: yes - fixture.",
        T="Core task: synthetic task. People: substantive - they gather a synthetic input.",
        R="Lens: low. In R: none. In O: synthetic vertical suite.",
        O="Baseline: O=2 (medium; no segment). Host suite: none. Segment: no segment.")
    return found


def flip_points(candidates):
    """The first one-step call the checker lists for each neighbouring pair, as a screen would name it."""
    points = []
    for row in checker.flip_table(candidates):
        call = row["calls"][0] if row["calls"] else None
        points.append({**{key: row[key] for key in ("ranks", "upper", "lower", "upper_score", "lower_score",
                                                    "tied")},
                       "tie_break": "original rank" if row["tied"] else "",
                       "call": call and {key: call[key] for key in ("id", "factor", "from", "to")},
                       "score_after": call and call["score_after"], "result": call["result"] if call else "none",
                       "why": "Synthetic reason"})
    return points


def flip_section(points):
    lines = ["## Flip points"]
    for point in points:
        call = point["call"]
        named = (f"{call['id']} {call['factor']} {checker.level(call['from'])} \u2192 {checker.level(call['to'])}"
                 if call else "none")
        lines.append(f"- {point['ranks'][0]}-{point['ranks'][1]}: {named} {point['result']}")
    return "\n".join(lines) + "\n"


class Screen:
    """A finished screen's workspace: the saved scan, one saved page and a serving.json that meets every guard."""

    def __init__(self, workspace, count=5):
        self.root = workspace / "state" / "scan"
        (self.root / "baseline").mkdir(parents=True)
        pages = workspace / "state" / "desk" / "pages"
        pages.mkdir(parents=True)
        (pages / "source.txt").write_text("Documented example source statement.\n")
        texts = {name: "Synthetic unchanged lens\n" for name in ("demand.md", "market.md", "timing.md", "grade.md")}
        texts["shortlist.md"] = shortlist(count)
        manifest = {}
        for name, text in texts.items():
            (self.root / "baseline" / name).write_text(text)
            (self.root / name).write_text(text)
            manifest[name] = hashlib.sha256(text.encode()).hexdigest()
        (self.root / "baseline-manifest.json").write_text(json.dumps(manifest))
        self.shortlist = texts["shortlist.md"]
        candidates = [candidate(n) for n in range(1, count + 1)]
        self.result = {"formula": checker.FORMULA, "candidates": candidates,
                       "flip_points": flip_points(candidates),
                       "regressions": [{"id": cid, **values, "excluded_for_sector": False,
                                        "reason": "Synthetic nonempty reason"} for cid, values in checker.GUARDS.items()],
                       "recommendation": "Synthetic fixture, not a real recommendation"}

    def issues(self, section=None):
        (self.root / "serving.json").write_text(json.dumps(self.result))
        listed = section if section is not None else flip_section(self.result.get("flip_points") or [])
        (self.root / "shortlist.md").write_text(self.shortlist + "\n" + listed)
        return checker.check(self.root)


@pytest.fixture
def screen(tmp_path):
    return Screen(tmp_path)


@pytest.mark.parametrize("count", [1, 5, 7, 8])
def test_a_screen_that_keeps_every_candidate_passes(tmp_path, count):
    assert Screen(tmp_path, count).issues() == []


def test_spacing_inside_a_quote_is_not_content(screen):
    screen.result["candidates"][0]["claims"][0]["quote"] = "Documented\n example   source statement."
    assert screen.issues() == []


BREAKS = [
    ("a changed name", lambda r: r["candidates"][0].update(name="Different buyer"), "C1: changed identity"),
    ("an unknown build scored as easy", lambda r: r["candidates"][0].update(F=1), "C1: unknown too cheaply scored in F"),
    ("an unknown permission scored as light", lambda r: r["candidates"][0].update(B=2),
     "C1: unknown too cheaply scored in B"),
    ("the old D counted again", lambda r: r["candidates"][0].update(D=2), "C1: old D must not be a score factor"),
    ("wrong arithmetic", lambda r: r["candidates"][0].update(score=100), "C1: wrong score"),
    ("a fractional factor", lambda r: r["candidates"][0].update(F=2.5), "C1: invalid F"),
    ("a boolean factor", lambda r: r["candidates"][1].update(P=True), "C2: invalid P"),
    ("a missing serving field", lambda r: r["candidates"][0]["serving"].pop("licence"), "C1: missing serving.licence"),
    ("a quote its page never said", lambda r: r["candidates"][0]["claims"][0].update(quote="This source never said this."),
     "C1: quote not on saved page"),
    ("a page outside the evidence folder",
     lambda r: r["candidates"][0]["claims"][0].update(saved_page="state/scan/baseline/shortlist.md"),
     "C1: missing/out-of-bounds saved page"),
    ("secondary evidence only", lambda r: r["candidates"][0]["claims"][0].update(source_kind="secondary"),
     "C1: no original/vendor primary support"),
    ("a duplicated candidate", lambda r: r["candidates"].__setitem__(1, copy.deepcopy(r["candidates"][0])),
     "candidate ids missing/duplicated"),
    ("a dropped candidate", lambda r: r["candidates"].pop(), "must retain every candidate"),
    ("ranks out of order", lambda r: r["candidates"][0].update(rank=2), "candidate array must follow new ranks 1..n"),
    ("scores out of order", lambda r: r["candidates"][1].update(P=3, score=4.0), "not ranked by new index"),
    ("a changed formula", lambda r: r.update(formula="P*W*O*T"), "formula changed"),
    ("an F reason that names no part", lambda r: r["candidates"][0]["factor_reasons"].update(F="Bounded."),
     "C1: F reason must name 'Hardest part:', 'Technique shown:' and 'Inputs available:'"),
    ("an open part scored as bounded",
     lambda r: r["candidates"][0]["factor_reasons"].update(
         F="Hardest part: reading notes. Technique shown: yes - x. Inputs available: unknown - nobody says."),
     "C1: F must be 3 exactly when the technique is not shown or inputs are not available"),
    ("a T reason that names no task", lambda r: r["candidates"][0]["factor_reasons"].update(T="Partial."),
     "C1: T reason must name 'Core task:' and 'People: approval|substantive|none'"),
    ("approval scored as partial",
     lambda r: r["candidates"][0]["factor_reasons"].update(T="Core task: drafting. People: approval - signs it."),
     "C1: T does not follow from the people's work it names"),
    ("an R reason that sorts no company", lambda r: r["candidates"][0]["factor_reasons"].update(R="Low."),
     "C1: R reason must name 'Lens:', 'In R:' and 'In O:'"),
    ("R below the lens",
     lambda r: r["candidates"][0]["factor_reasons"].update(R="Lens: high. In R: a lab. In O: none."),
     "C1: R below the lens level"),
    ("an O reason without its two moves", lambda r: r["candidates"][0]["factor_reasons"].update(O="Crowded."),
     "C1: O reason must name 'Baseline: O=<n>', 'Host suite:' and 'Segment:'"),
    ("an unserved segment scored as crowded",
     lambda r: r["candidates"][0].update(O=1) or r["candidates"][0]["factor_reasons"].update(
         O="Baseline: O=2 (high; one-state segment). Host suite: none. Segment: not shown - only 'all TPAs'.")
     or r["candidates"][0].update(score=checker.score_of(r["candidates"][0])),
     "C1: O must be 2 while a lens-named segment is not shown served"),
    ("an O moved with nothing named",
     lambda r: r["candidates"][0].update(O=1) or r["candidates"][0].update(score=checker.score_of(r["candidates"][0])),
     "C1: O moved from the baseline without a host-suite or segment fact"),
    ("no flip points", lambda r: r.pop("flip_points"), "missing flip_points"),
    ("a pair without its flip point", lambda r: r["flip_points"].pop(), "flip_points must name one call per neighbouring pair"),
    ("a tied pair without its tie-break", lambda r: r["flip_points"][0].update(tie_break=""),
     "flip 1-2: a tied pair needs its tie-break"),
    ("a call that moves nothing", lambda r: r["flip_points"][0].update(call={"id": "C1", "factor": "P", "from": 2, "to": 3}),
     "flip 1-2: the call is not one step that reorders or ties the pair"),
    ("a two-step call", lambda r: r["flip_points"][0].update(call={"id": "C1", "factor": "T", "from": 2, "to": 0}),
     "flip 1-2: the call is not one step that reorders or ties the pair"),
    ("no call where one exists", lambda r: r["flip_points"][0].update(call=None, result="none"),
     "flip 1-2: a one-step call reorders or ties this pair; name one"),
    ("a wrong score after the call", lambda r: r["flip_points"][0].update(score_after=9.0),
     "flip 1-2: wrong score_after or result"),
]


@pytest.mark.parametrize(("mutate", "problem"), [b[1:] for b in BREAKS], ids=[b[0] for b in BREAKS])
def test_a_screen_short_of_the_guards_fails_and_says_why(screen, mutate, problem):
    mutate(screen.result)
    assert problem in screen.issues()


def test_flip_points_must_also_be_listed_in_the_shortlist(screen):
    assert "shortlist.md: missing '## Flip points' section" in screen.issues(section="")
    named = screen.result["flip_points"][0]["call"]
    named = f"{named['id']} {named['factor']} {checker.level(named['from'])}->{checker.level(named['to'])}"
    assert f"flip 1-2: shortlist.md flip points do not name {named}" in screen.issues(section="## Flip points\n- none\n")


def ranked(*rows):
    """Candidates from (P, W, O, T, F, B, R) rows, scored and ranked in the given order."""
    out = []
    for n, row in enumerate(rows, 1):
        values = dict(zip("PWOTFBR", row, strict=True))
        out.append({"id": f"C{n}", "rank": n, **values, "score": checker.score_of(values)})
    return out


def test_the_flip_list_finds_the_one_step_calls_by_hand():
    """Run 11's C1 3.0 over a C5-like 2.0 (T=2), worked out by hand: every step that brings C1 down to 2.0 or
    below, or C5 up to 3.0 or above. C1 B 3->4 (2.25) and C5 R 2->1.5 (2.6667) fall short."""
    top, second = ranked((2, 3, 1, 3, 2, 3, 1), (3, 2, 2, 2, 2, 3, 2))
    assert (top["score"], second["score"]) == (3.0, 2.0)
    calls = {(c["id"], c["factor"], c["from"], c["to"]): (c["score_after"], c["result"])
             for c in checker.flips(top, second)}
    assert calls == {
        ("C1", "P", 2, 1): (1.5, "swaps"), ("C1", "W", 3, 2): (2.0, "ties"), ("C1", "T", 3, 2): (2.0, "ties"),
        ("C1", "F", 2, 3): (2.0, "ties"), ("C1", "R", 1, 1.5): (2.0, "ties"),
        ("C2", "W", 2, 3): (3.0, "ties"), ("C2", "O", 2, 3): (3.0, "ties"), ("C2", "T", 2, 3): (3.0, "ties"),
        ("C2", "F", 2, 1): (4.0, "swaps"), ("C2", "B", 3, 2): (3.0, "ties"),
    }


def test_no_call_is_named_when_no_single_step_reaches_the_lower_score():
    far = ranked((3, 3, 3, 3, 1, 1, 1), (1, 1, 1, 1, 3, 4, 2))
    assert checker.flips(*far) == []
    workspace_points = flip_points(far)
    assert workspace_points[0]["call"] is None and workspace_points[0]["result"] == "none"


def test_the_flips_option_prints_the_list_for_the_current_screen(screen):
    screen.issues()
    workspace = screen.root.parent.parent
    done = subprocess.run(["python3", str(ASSETS / "check_serving.py"), "--flips"], cwd=workspace,
                          capture_output=True, text=True, timeout=30, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert done.returncode == 0, done.stdout + done.stderr
    rows = json.loads(done.stdout)
    assert [row["ranks"] for row in rows] == [[1, 2], [2, 3], [3, 4], [4, 5]]
    assert rows == checker.flip_table(screen.result["candidates"])


def factor_calls(name):
    prompt = by_name(name)["system_prompt"]
    found = re.search(r"^ *FACTOR CALLS: .*?Recompute flip points whenever a score or rank changes\.$", prompt, re.S | re.M)
    assert found, f"{name} no longer holds the FACTOR CALLS and FLIP POINTS rules"
    return found.group(0)


def test_the_screen_and_the_audit_apply_the_same_factor_calls():
    """Queue #30: trial 10 and run 11 split on which part F, T and R rated; both steps must read one rule."""
    assert factor_calls("scan_serving_screen") == factor_calls("scan_serving_audit")
    rules = factor_calls("scan_serving_screen")
    for needed in ("HARDEST PART OF THE SOFTWARE'S JOB", "TYPICAL CASE OF THE STATED JOB",
                   "FRONTIER LABS AND MAJOR CROSS-INDUSTRY PLATFORMS", "Worked example", "--flips",
                   "ONE BUYER", "P COUNTS", "W COUNTS", "O MOVES"):
        assert needed in rules
    assert rules.count("Worked example") == 3


def test_the_fictional_guards_need_their_levels_a_reason_and_no_sector_ban(screen):
    case = screen.result["regressions"][0]
    case.update(B=1, excluded_for_sector=True, reason="")
    issues = screen.issues()
    assert "regression enterprise: B" in issues
    assert "regression enterprise: blanket sector exclusion" in issues
    assert "regression enterprise: missing reason" in issues


def test_a_changed_saved_scan_or_lens_is_refused(screen):
    saved = screen.root / "baseline" / "shortlist.md"
    saved.write_text(saved.read_text() + "\nchanged")
    (screen.root / "market.md").write_text("changed")
    issues = screen.issues()
    assert "changed baseline: shortlist.md" in issues
    assert "changed lens: market.md" in issues


# ---- prepare: a saved scan into a fresh workspace -----------------------------------------------------


def prepare(workspace, baseline, assets, cite, retain=None):
    """The real prepare step, rendered the way the script agent renders it and run by /bin/sh."""
    cfg = by_name("scan_serving_prepare")
    stash = _ValueStash()
    values = {"workspace_path": str(workspace), "baseline_dir": str(baseline), "assets_dir": str(assets),
              "cite_path": str(cite)}
    if retain is not None:
        values["retain_sources"] = retain
    script = jinja(stash).from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render(**values)
    env = {**os.environ, **stash.env, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=30, cwd=workspace, env=env)


IDENTITIES = {f"C{n}": f"FICTIONAL infrastructure candidate {n}" for n in range(1, 6)}
PAGE = "0123456789abcdef.txt"
BODY = b"Fictional public-source infrastructure fixture, no market claim.\n"


@pytest.fixture
def scan(tmp_path):
    """A saved scan, the screen's real helpers plus one retained replay page, and a fresh workspace."""
    baseline, assets, workspace = tmp_path / "baseline", tmp_path / "assets", tmp_path / "workspace"
    for path in (baseline, assets / "retained_source_pages", workspace):
        path.mkdir(parents=True)
    for name in ("demand.md", "market.md", "timing.md", "grade.md"):
        (baseline / name).write_text("Infrastructure fixture, not research evidence.\n")
    (baseline / "shortlist.md").write_text(shortlist(5, names=list(IDENTITIES.values())))
    for name in ("check_serving.py", "fixtures.json", "cite.py"):
        shutil.copyfile(ASSETS / name, assets / name)
    (assets / "retained_source_pages" / PAGE).write_bytes(BODY)
    registry = {"schema": 1, "candidate_identities": IDENTITIES,
                "pages": [{"file": PAGE, "sha256": hashlib.sha256(BODY).hexdigest()}],
                "capture": "FICTIONAL earlier infrastructure capture; not newly fetched"}
    return types.SimpleNamespace(baseline=baseline, assets=assets, workspace=workspace, cite=assets / "cite.py",
                                 registry=registry)


def run(scan, retain=None):
    return prepare(scan.workspace, scan.baseline, scan.assets, scan.cite, retain)


def write_registry(scan):
    data = json.dumps(scan.registry).encode()
    (scan.assets / "retained-sources.json").write_bytes(data)
    return data


def test_prepare_copies_the_saved_scan_names_its_candidates_and_refuses_reuse(scan):
    done = run(scan)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["retained_pages"] == 0
    copied = scan.workspace / "state" / "scan"
    manifest = json.loads((copied / "baseline-manifest.json").read_text())
    assert manifest["shortlist.md"] == hashlib.sha256((scan.baseline / "shortlist.md").read_bytes()).hexdigest()
    assert json.loads((copied / "candidate-identities.json").read_text()) == IDENTITIES
    assert (scan.workspace / "state" / "desk" / "cite.py").read_bytes() == (ASSETS / "cite.py").read_bytes()
    assert not (copied / "retained-sources.json").exists()
    before = (copied / "baseline" / "shortlist.md").read_bytes()
    again = run(scan)
    assert again.returncode != 0 and "Refusing to overwrite an existing screen" in again.stderr
    assert (copied / "baseline" / "shortlist.md").read_bytes() == before


def test_prepare_stops_on_a_shortlist_it_cannot_name(scan):
    (scan.baseline / "shortlist.md").write_text(shortlist(9))
    done = run(scan)
    assert done.returncode != 0 and "Cannot identify the saved candidates" in done.stderr


def test_a_registry_is_ignored_unless_retention_is_asked_for(scan):
    write_registry(scan)
    done = run(scan, retain="false")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["retained_pages"] == 0
    assert not (scan.workspace / "state" / "scan" / "retained-sources.json").exists()


def test_retained_pages_are_copied_byte_for_byte(scan):
    data = write_registry(scan)
    done = run(scan, retain="true")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["retained_pages"] == 1
    assert (scan.workspace / "state" / "desk" / "pages" / PAGE).read_bytes() == BODY
    assert (scan.workspace / "state" / "scan" / "retained-sources.json").read_bytes() == data


def corrupt_body(scan):
    (scan.assets / "retained_source_pages" / PAGE).write_bytes(b"Changed fixture bytes")


def traversal(scan):
    scan.registry["pages"][0]["file"] = "../outside.txt"


def other_identity(scan):
    scan.registry["candidate_identities"] = dict(IDENTITIES, C1="Different fictional identity")


def symlinked_body(scan):
    body = scan.assets / "retained_source_pages" / PAGE
    body.unlink()
    body.symlink_to(scan.cite)


def conflicting_cache(scan):
    target = scan.workspace / "state" / "desk" / "pages" / PAGE
    target.parent.mkdir(parents=True)
    target.write_bytes(b"Conflicting fixture bytes")


@pytest.mark.parametrize(("spoil", "problem"), [
    (corrupt_body, "hash mismatch"),
    (traversal, "Unsafe retained-source filename"),
    (other_identity, "does not match this replay"),
    (symlinked_body, "Missing or unsafe retained-source body"),
    (conflicting_cache, "Conflicting existing retained-source body"),
], ids=["a changed body", "a path outside the pages", "other candidates", "a symlinked body", "a different cached page"])
def test_a_retained_page_that_does_not_match_exactly_stops_prepare(scan, spoil, problem):
    spoil(scan)
    write_registry(scan)
    done = run(scan, retain="true")
    assert done.returncode != 0 and problem in done.stderr


def test_a_different_cached_page_is_left_as_it_was(scan):
    conflicting_cache(scan)
    write_registry(scan)
    assert run(scan, retain="true").returncode != 0
    assert (scan.workspace / "state" / "desk" / "pages" / PAGE).read_bytes() == b"Conflicting fixture bytes"


def test_retention_must_be_true_or_false(scan):
    done = run(scan, retain="yes")
    assert done.returncode != 0 and "retain_sources must be true or false" in done.stderr
