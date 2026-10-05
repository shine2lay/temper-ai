"""The opportunity brief (configs/workflows/opportunity_brief.yaml, product role) fits together.

Its configs: every script step parses under /bin/sh, the model steps keep Claude Code's own tools, every
template variable is fed by the workflow (a stage hands its input_map to each of its agents) and every
workflow output names a field its step prints. Its two helpers, which brief_setup writes into the
workspace: cite.py answers from the pages it kept (a kept block stays a block), and check_brief.py passes
a brief that meets the bar and names what is missing in one that doesn't, including a lens that left no
usable output (queue #23: run 99732fd1's competition lens answered "You've hit your session limit" and
its brief still passed). Nothing here reaches the network: every page comes from cite.py's own cache,
and a proxy that refuses every connection stands in front of curl in case a page is ever looked up.
"""

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
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
AGENTS = sorted((ROOT / "configs" / "agents").glob("brief_*.yaml"))
WORKFLOW = ROOT / "configs" / "workflows" / "opportunity_brief.yaml"
INJECTED = {"workspace_path", "run_id"}  # the agents add these to every template
LENSES = {"brief_feasibility", "brief_viability", "brief_gtm", "brief_competition"}
LIMIT = "You've hit your session limit \u00b7 resets 10:50pm (UTC)"  # 99732fd1's competition lens, verbatim
REFUSED = "http://127.0.0.1:9"
NO_NETWORK = {"http_proxy": REFUSED, "https_proxy": REFUSED, "HTTPS_PROXY": REFUSED, "ALL_PROXY": REFUSED}

RULE = "https://www.example.gov/rule"
PRICES = "https://www.example.com/pricing"
BLOCKED = "https://www.example.org/forum"
PAGES = {
    RULE: ("200", "Section 1. A plan must decide a standard request within 30 calendar days of receipt."),
    PRICES: ("200", "Pricing. Eligibility check: $0.30 per check for the first 250 a month."),
    BLOCKED: ("403", ""),
}


def served(path):
    """The config as the server hands it out (ConfigStore.get runs the env substitution)."""
    return substitute_env_vars(yaml.safe_load(path.read_text()))


def agent(path):
    return served(path)["agent"]


def by_name(name):
    return agent(ROOT / "configs" / "agents" / f"{name}.yaml")


def workflow():
    return served(WORKFLOW)["workflow"]


def template_of(cfg):
    return cfg["script_template"] if cfg.get("type") == "script" else cfg["task_template"]


def runs(node):
    """(agent, the inputs it gets) for each agent a node runs."""
    fed = set(node.get("input_map") or {})
    if node.get("type") == "stage":
        return [(a["agent"], fed) for a in node["agents"]]
    return [(node["agent"], fed)]


def jinja(stash=None):
    """Jinja as the script agent sets it up, with its value filters."""
    env = SandboxedEnvironment(loader=BaseLoader(), undefined=ChainableUndefined)
    stash = stash if stash is not None else _ValueStash()
    env.filters[QUOTED_FILTER] = stash.quoted
    env.filters[BARE_FILTER] = stash.bare
    env.filters[ENV_FILTER] = stash.name
    return env


def test_four_lenses_run_side_by_side_and_the_synthesizer_leads():
    names = {agent(p)["name"] for p in AGENTS}
    assert {p.stem for p in AGENTS} == names, "each agent file is named after its agent"
    nodes = workflow()["nodes"]
    assert {name for n in nodes for name, _ in runs(n)} == names, "the workflow runs every agent, and only these"
    stage = next(n for n in nodes if n.get("type") == "stage")
    assert stage["strategy"] == "leader"
    assert [a["agent"] for a in stage["agents"] if a.get("role") == "leader"] == ["brief_synthesize"]
    assert {a["agent"] for a in stage["agents"]} == LENSES | {"brief_synthesize"}


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


def fed_by_the_workflow(wf, node, value):
    """An input_map value is a workflow input, or the final answer of a lens in a stage the node waits for."""
    if value.startswith("input."):
        return value.split(".", 1)[1] in wf["inputs"]
    stage, lens, field = (value.split(".") + ["", ""])[:3]
    stages = {n["name"]: n for n in wf["nodes"] if n.get("type") == "stage"}
    return (stage in (node.get("depends_on") or []) and stage in stages and field == "output"
            and value.count(".") == 2 and lens in LENSES and lens in {a["agent"] for a in stages[stage]["agents"]})


def test_every_template_variable_is_fed_by_the_workflow():
    env = jinja()
    wf = workflow()
    for node in wf["nodes"]:
        for value in (node.get("input_map") or {}).values():
            assert fed_by_the_workflow(wf, node, value), f"{value} is neither an input nor a lens's answer"
        for name, fed in runs(node):
            used = meta.find_undeclared_variables(env.parse(template_of(by_name(name))))
            assert used <= fed | INJECTED, f"{name} uses {sorted(used - fed - INJECTED)} that the workflow never passes"


def test_the_check_gets_each_lens_answer():
    check = next(n for n in workflow()["nodes"] if n["name"] == "check")
    assert check["input_map"] == {f"{lens}_answer": f"brief.brief_{lens}.output"
                                  for lens in ("feasibility", "viability", "gtm", "competition")}


def helper(name):
    """A helper's source, cut from the heredoc brief_setup writes it with."""
    script = by_name("brief_setup")["script_template"]
    found = re.search(rf"^cat > {re.escape(name)} <<'(\w+)'\n(.*?)\n\1$", script, re.S | re.M)
    assert found, f"brief_setup no longer writes {name}"
    source = found.group(2)
    assert "{{" not in source and "{%" not in source, "the script agent's Jinja would rewrite the helper"
    return source


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def claim(cid, url, quote, kind, quality):
    return {"id": cid, "claim": quote, "quote": quote, "url": url, "date": "undated", "fetched": "2026-10-01",
            "kind": kind, "quality": quality, "how": "cite"}


CLAIMS = [
    claim("F1", RULE, "must decide a standard request within 30 calendar days", "rule", "primary"),
    claim("F2", PRICES, "$0.30 per check for the first 250 a month", "price", "vendor"),
    claim("F3", RULE, "within 30 calendar days of receipt", "date", "secondary"),
]


def good_brief(questions, rows):
    reason = "Offices feel the pain and the data is cheap, but the first wedge is crowded."
    return {
        "questions": [{"n": n, "question": q, "answer": f"Answer {n}: {reason}", "claims": ["F1"]}
                      for n, q in enumerate(questions, 1)],
        "risks": [{"row": row, "verdict": "med", "why": reason, "claims": ["F1", "F2"]} for row in rows],
        "assumptions": [{"assumption": f"Riskiest assumption number {n}", "row": "value", "rung": "R3",
                         "test": "a refundable deposit on the fake door", "kill_if": "fewer than 2 deposits in 100 visits",
                         "claims": ["F2"]} for n in (1, 2, 3)],
        "kill_criteria": ["Kill if fewer than 2 deposits in 100 visits."],
        "recommendation": {"decision": "change_wedge", "reason": reason,
                           "new_wedge": "denial follow-up for independent offices"},
        "claims": [dict(c) for c in CLAIMS[:2]],
    }


LENS_CLAIMS = {"feasibility": CLAIMS, "viability": [dict(CLAIMS[0], id="V1")], "gtm": [dict(CLAIMS[1], id="G1")],
               "competition": [dict(CLAIMS[2], id="C1")]}


@pytest.fixture
def workspace(tmp_path):
    """A finished run's workspace: both helpers, the pages cite.py kept, the four lenses' files and the brief."""
    for name in ("cite.py", "check_brief.py"):
        (tmp_path / name).write_text(helper(name))
    brief_dir = tmp_path / "state" / "brief"
    (brief_dir / "pages").mkdir(parents=True)
    (brief_dir / "lenses").mkdir()
    for url, (http, text) in PAGES.items():
        record = {"url": url, "final_url": url, "http": http, "content_type": "text/html",
                  "fetched": "2026-10-01 21:35 PDT"}
        page = brief_dir / "pages" / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt")
        page.write_text(json.dumps(record) + "\n" + text)
    for lens, claims in LENS_CLAIMS.items():
        (brief_dir / "lenses" / f"{lens}.json").write_text(json.dumps({"lens": lens, "claims": claims}))
        (brief_dir / "lenses" / f"{lens}.md").write_text(f"# The {lens} lens\nWhat it found, with its sources.\n")
    (brief_dir / "input.md").write_text("# Idea\nDental insurance verification.\n")
    (brief_dir / "brief.md").write_text("# Opportunity brief\n")
    checker = load(tmp_path / "check_brief.py")
    (brief_dir / "brief.json").write_text(json.dumps(good_brief(checker.QUESTIONS, checker.ROWS)))
    return tmp_path


def check(ws, **answers):
    """check_brief.py --final, with each given lens's final answer passed the way brief_check passes it."""
    args, env = [], dict(os.environ)
    for lens, text in answers.items():
        env[f"ANSWER_{lens.upper()}"] = text
        args += ["--answer", f"{lens}=ANSWER_{lens.upper()}"]
    done = subprocess.run([sys.executable, "check_brief.py", "--final", *args], cwd=ws, capture_output=True,
                          text=True, timeout=30, env=env)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def cite(ws, *args):
    done = subprocess.run([sys.executable, "cite.py", *args], cwd=ws, capture_output=True, text=True, timeout=30,
                          env={**os.environ, **NO_NETWORK})
    return done.stdout


def test_the_ten_questions_are_cagans(workspace):
    questions = load(workspace / "check_brief.py").QUESTIONS
    assert len(questions) == 10
    assert questions[0] == "Exactly what problem will this solve? (value proposition)"
    assert questions[-1] == "Given the above, what's the recommendation? (go or no-go)"


def test_a_brief_that_meets_the_bar_passes_and_draws_its_spot_check(workspace):
    result = check(workspace)
    assert result["verdict"] == "pass", result["problems"]
    assert all(result["items"].values())
    assert result["parts"] == {lens: "ok" for lens in ("feasibility", "viability", "gtm", "competition")}
    assert {c["id"] for c in result["spot_check"]} == {"F1", "F2"}, "only cited claims are drawn"
    assert [c["id"] for c in check(workspace)["spot_check"]] == [c["id"] for c in result["spot_check"]], "seed 7"


BREAKS = [
    ("quote off the page", lambda b, lens: lens["claims"][0].update(quote="must decide every request within a day"),
     "claim F1: quote is not on the page cite.py kept"),
    ("a row from one source", lambda b, lens: b["risks"][0].update(claims=["F1"]),
     "risk row value: 1 usable claims from 1 URLs"),
    ("a row with no primary", lambda b, lens: b["risks"][1].update(claims=["F2", "F3"]),
     "risk row usability: no primary claim read with cite.py"),
    ("a reworded question", lambda b, lens: b["questions"][2].update(question="How big is it?"),
     "question 3 should read exactly"),
    ("an invented source", lambda b, lens: b["questions"][0].update(claims=["F9"]),
     "claim F9: cited but in no lens file"),
    ("two assumptions", lambda b, lens: b.update(assumptions=b["assumptions"][:2]), "assumptions: 2, need >= 3"),
    ("no kill criteria", lambda b, lens: b.update(kill_criteria=[]), "kill_criteria: none"),
    ("an unnamed new wedge", lambda b, lens: b["recommendation"].pop("new_wedge"),
     "recommendation change_wedge: name the new wedge"),
    ("a copy with another URL", lambda b, lens: b["claims"][1].update(url="https://www.example.com/other"),
     "claim F2: the brief's copy has a different URL"),
]


@pytest.mark.parametrize(("mutate", "problem"), [b[1:] for b in BREAKS], ids=[b[0] for b in BREAKS])
def test_a_brief_short_of_the_bar_fails_and_says_why(workspace, mutate, problem):
    brief_path = workspace / "state" / "brief" / "brief.json"
    lens_path = workspace / "state" / "brief" / "lenses" / "feasibility.json"
    brief, lens = json.loads(brief_path.read_text()), json.loads(lens_path.read_text())
    mutate(brief, lens)
    brief_path.write_text(json.dumps(brief))
    lens_path.write_text(json.dumps(lens))
    result = check(workspace)
    assert result["verdict"] == "fail"
    assert any(problem in p for p in result["problems"]), result["problems"]


def lens_file(ws, name):
    return ws / "state" / "brief" / "lenses" / name


LOST = [
    ("both files gone", lambda ws: [lens_file(ws, f"competition.{ext}").unlink() for ext in ("json", "md")],
     "competition lens left no usable output: lenses/competition.json is missing; lenses/competition.md is missing"),
    ("an empty write-up", lambda ws: lens_file(ws, "viability.md").write_text("\n"),
     "viability lens left no usable output: lenses/viability.md is empty"),
    ("broken JSON", lambda ws: lens_file(ws, "gtm.json").write_text('{"lens": "gtm", "claims": ['),
     "gtm lens left no usable output: lenses/gtm.json is not valid JSON"),
    ("JSON that is no object", lambda ws: lens_file(ws, "gtm.json").write_text("[]"),
     "gtm lens left no usable output: lenses/gtm.json is not a JSON object"),
    ("no claims", lambda ws: lens_file(ws, "feasibility.json").write_text('{"lens": "feasibility", "claims": []}'),
     "feasibility lens left no usable output: lenses/feasibility.json has no claims"),
    ("a limit message for a write-up", lambda ws: lens_file(ws, "competition.md").write_text(LIMIT),
     "competition lens left no usable output: lenses/competition.md is an account-limit or error message"),
]


@pytest.mark.parametrize(("lose", "problem"), [x[1:] for x in LOST], ids=[x[0] for x in LOST])
def test_a_lens_that_left_no_usable_output_fails_the_brief_by_name(workspace, lose, problem):
    lose(workspace)
    result = check(workspace)
    assert result["verdict"] == "fail"
    assert any(p.startswith(problem) for p in result["problems"]), result["problems"]
    lens = problem.split()[0]
    assert result["parts"][lens] != "ok" and [k for k, v in result["parts"].items() if v != "ok"] == [lens]


def test_the_lost_competition_lens_of_run_99732fd1_fails_the_brief(workspace):
    """No competition files and a final answer that is the account's limit message: the brief still cites
    enough from the other lenses to meet every item, as 99732fd1's did, and fails all the same."""
    for ext in ("json", "md"):
        lens_file(workspace, f"competition.{ext}").unlink()
    result = check(workspace, competition=LIMIT)
    assert result["verdict"] == "fail" and all(result["items"].values())
    assert result["problems"][0] == (
        "competition lens left no usable output: lenses/competition.json is missing; lenses/competition.md is "
        f'missing; its final answer is an account-limit or error message ("{LIMIT}")')
    assert result["answers_checked"] == ["competition"]


def test_a_lens_whose_final_answer_is_a_limit_message_fails_even_with_its_files(workspace):
    result = check(workspace, gtm="API Error: 529 Overloaded. Try again later.")
    assert result["verdict"] == "fail"
    assert result["problems"][0].startswith("gtm lens left no usable output: its final answer is an account-limit")


def test_research_answers_and_answers_not_passed_in_leave_the_brief_passing(workspace):
    research = '```json\n{"status": "completed", "lens": "feasibility", "claims": ["F1"], "note": "rate limit 100/min"}\n```'
    result = check(workspace, feasibility=research, viability='{"status": "completed", "lens": "viability"}',
                   gtm="__unwired__")
    assert result["verdict"] == "pass", result["problems"]
    assert result["answers_checked"] == ["feasibility", "viability"], "an answer not passed in leaves the files to judge"


@pytest.mark.parametrize(("text", "lost"), [
    (LIMIT, True),
    ("Claude AI usage limit reached|1759630800", True),
    ("Credit balance is too low", True),
    ("Invalid API key \u00b7 Please run /login", True),
    ("", True),
    ("Done: wrote lenses/gtm.json and lenses/gtm.md.", False),
    ("The vendor's API has a rate limit of 100 calls a minute. " * 12, False),
    ('{"status": "completed", "note": "quota of 250 checks"}', False),
], ids=["session limit", "usage limit", "credit", "login", "empty", "short research", "long research", "json"])
def test_a_non_answer_is_empty_or_a_short_limit_or_error_message(workspace, text, lost):
    assert bool(load(workspace / "check_brief.py").non_answer(text)) is lost


def test_the_check_step_passes_each_lens_answer_to_the_checker(workspace):
    """brief_check rendered the way the script agent renders it: a lens's answer reaches check_brief.py, and
    an answer the workflow could not find (None, or a node the workflow never had) is left to the files."""
    cfg = by_name("brief_check")
    stash = _ValueStash()
    script = jinja(stash).from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render(
        workspace_path=str(workspace), competition_answer=LIMIT, feasibility_answer="x" * 9000, viability_answer=None)
    done = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=60, cwd=workspace,
                          env={**os.environ, **stash.env})
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["answers_checked"] == ["feasibility", "competition"]
    assert result["verdict"] == "fail" and result["problems"][0].startswith("competition lens left no usable output")
    assert max(len(v) for v in stash.env.values()) <= 4000, "a long answer is cut to its first 4000 characters"


def test_cite_answers_from_the_pages_it_kept(workspace):
    assert "FOUND: ..." in cite(workspace, "quote", RULE, "decide a standard request")
    assert "NOT FOUND" in cite(workspace, "quote", PRICES, "free for every practice")
    blocked = cite(workspace, "quote", BLOCKED, "anything")
    assert "INACCESSIBLE" in blocked and "never work around it" in blocked


def test_the_workflow_outputs_name_fields_their_steps_print(workspace):
    prompt = by_name("brief_synthesize")["system_prompt"]
    contract = re.search(r'(\{"status": "completed",.*?"problems_left": 0\})', prompt, re.S)
    assert contract, "brief_synthesize no longer shows the JSON it finishes with"
    printed = {"brief": set(json.loads(contract.group(1))), "check": set(check(workspace))}
    for ref in workflow()["outputs"].values():
        node, _, field = ref.partition(".structured.")
        assert field in printed[node], f"{ref}: {node} never prints `{field}`"
