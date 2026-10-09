"""The opportunity brief (configs/workflows/opportunity_brief.yaml, product role) fits together.

It comes in two versions: opportunity_brief for software sold to businesses and opportunity_brief_consumer
(queue #27) for consumer ideas, with consumer lenses and synthesizer and the same setup, check, inputs and
outputs. Their configs: every script step parses under /bin/sh, the model steps keep Claude Code's own tools,
every template variable is fed by the workflow (a stage hands its input_map to each of its agents) and every
workflow output names a field its step prints. Its two helpers, which brief_setup writes into the
workspace: cite.py answers from the pages it kept (a kept block stays a block), and check_brief.py passes
a brief that meets the bar and names what is missing in one that doesn't, including a lens that left no
usable output (queue #23: run 99732fd1's competition lens answered "You've hit your session limit" and
its brief still passed) and a derived figure whose arithmetic is off or whose inputs don't match in kind
(queue #25: run 57dc513d weighed ads per paying user against margin per active user, and run fc575760
used a lead rate as the share of clickers who start a quiz; every quote in both was real). Nothing here
reaches the network: every page comes from cite.py's own cache, and a proxy that refuses every
connection stands in front of curl in case a page is ever looked up.
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
# Each version and the suffix of its lenses and synthesizer; both run the same brief_setup and brief_check.
VERSIONS = {"opportunity_brief": "", "opportunity_brief_consumer": "_consumer"}
WORKFLOWS = [ROOT / "configs" / "workflows" / f"{name}.yaml" for name in VERSIONS]
SHARED = {"brief_setup", "brief_check"}
INJECTED = {"workspace_path", "run_id"}  # the agents add these to every template
LENS_PARTS = ("feasibility", "viability", "gtm", "competition")
LIMIT = "You've hit your session limit \u00b7 resets 10:50pm (UTC)"  # 99732fd1's competition lens, verbatim
# What the Claude provider returns as an answer when its call failed (finish_reason "error", not read yet).
TIMED_OUT = "Error: Claude Code CLI timed out"
STREAM_ENDED = "[claude_code error] stream ended with no result event: " + " | ".join(["node: stderr line"] * 40)
REFUSED = "http://127.0.0.1:9"
NO_NETWORK = {"http_proxy": REFUSED, "https_proxy": REFUSED, "HTTPS_PROXY": REFUSED, "ALL_PROXY": REFUSED}

RULE = "https://www.example.gov/rule"
PRICES = "https://www.example.com/pricing"
BLOCKED = "https://www.example.org/forum"
ADS = "https://www.example.net/search-ads"
APPS = "https://www.example.com/app-report"
PAGES = {
    RULE: ("200", "Section 1. A plan must decide a standard request within 30 calendar days of receipt."),
    PRICES: ("200", "Pricing. Eligibility check: $0.30 per check for the first 250 a month."),
    BLOCKED: ("403", ""),
    ADS: ("200", "Search ad benchmarks. Average cost per click: $2.00. Average conversion rate: 5.0%, the number "
                 "of leads you get divided by clicks."),
    APPS: ("200", "App report. Median cost per install: $4.00. Freemium apps convert 2.0% of downloads to paid. "
                  "Offices outside the United States pay $50 a month for the plan. Map loads cost $7.00 per "
                  "1,000 events."),
}


def served(path):
    """The config as the server hands it out (ConfigStore.get runs the env substitution)."""
    return substitute_env_vars(yaml.safe_load(path.read_text()))


def agent(path):
    return served(path)["agent"]


def by_name(name):
    return agent(ROOT / "configs" / "agents" / f"{name}.yaml")


def workflow(name="opportunity_brief"):
    return served(ROOT / "configs" / "workflows" / f"{name}.yaml")["workflow"]


def lenses(suffix):
    return {f"brief_{part}{suffix}" for part in LENS_PARTS}


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


def test_every_brief_agent_is_named_after_its_file_and_run_by_a_version():
    names = {agent(p)["name"] for p in AGENTS}
    assert {p.stem for p in AGENTS} == names, "each agent file is named after its agent"
    run = {name for version in VERSIONS for n in workflow(version)["nodes"] for name, _ in runs(n)}
    assert run == names, "the two versions run every brief agent, and only these"


@pytest.mark.parametrize("version, suffix", VERSIONS.items())
def test_four_lenses_run_side_by_side_and_the_synthesizer_leads(version, suffix):
    nodes = workflow(version)["nodes"]
    leader = f"brief_synthesize{suffix}"
    assert {name for n in nodes for name, _ in runs(n)} == SHARED | lenses(suffix) | {leader}
    stage = next(n for n in nodes if n.get("type") == "stage")
    assert stage["strategy"] == "leader"
    assert [a["agent"] for a in stage["agents"] if a.get("role") == "leader"] == [leader]
    assert {a["agent"] for a in stage["agents"]} == lenses(suffix) | {leader}


def test_the_consumer_version_takes_and_gives_what_the_business_one_does():
    """Same inputs, outputs, setup and check: a consumer brief lands in the same files and is checked the same."""
    business, consumer = workflow("opportunity_brief"), workflow("opportunity_brief_consumer")
    assert consumer["inputs"] == business["inputs"] and consumer["outputs"] == business["outputs"]
    for name in ("setup", "check"):
        b, c = (next(n for n in wf["nodes"] if n["name"] == name) for wf in (business, consumer))
        assert c["agent"] == b["agent"] and c.get("depends_on") == b.get("depends_on")
        assert set(c["input_map"]) == set(b["input_map"])


# What the travel study's consumer bar scored, and the consumer version asks for (research/travel-discovery/
# inputs/brief-candidate-bar.md items a-f): revenue per active user a year with a low and high case, how often
# the need comes back from a sampled source, consumer channels, distribution inside AI assistants, a row for
# every named player, and serving barriers apart from the build.
CONSUMER_ASKS = {
    "brief_viability_consumer": ["Revenue per ACTIVE USER per year", "a survey that states its sample"],
    "brief_gtm_consumer": ["Distribution inside AI assistants", "creators and social video"],
    "brief_competition_consumer": ["give EVERY named player a row", '"overlap": "low|med|high"'],
    "brief_feasibility_consumer": ["Barriers to serving users"],
    "brief_synthesize_consumer": ["revenue per active user per year (low and", "list the serving barriers"],
}


@pytest.mark.parametrize("name", CONSUMER_ASKS)
def test_the_consumer_version_asks_for_what_its_bar_scored(name):
    prompt = re.sub(r"\s+", " ", by_name(name)["system_prompt"])
    for words in CONSUMER_ASKS[name]:
        assert words in prompt, f"{name} no longer asks for: {words}"


@pytest.mark.parametrize("path", [p for p in AGENTS if agent(p).get("type") == "script"], ids=lambda p: p.stem)
def test_every_script_step_parses_under_sh(path):
    cfg = agent(path)
    script = jinja().from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render()
    done = subprocess.run(["sh", "-n", "-c", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, f"{path.name} does not parse under /bin/sh: {done.stderr.strip()}"


@pytest.mark.parametrize("path", [*AGENTS, *WORKFLOWS], ids=lambda p: p.stem)
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
            and value.count(".") == 2
            and lens in {a["agent"] for a in stages[stage]["agents"] if a.get("role") != "leader"})


@pytest.mark.parametrize("version", VERSIONS)
def test_every_template_variable_is_fed_by_the_workflow(version):
    env = jinja()
    wf = workflow(version)
    for node in wf["nodes"]:
        for value in (node.get("input_map") or {}).values():
            assert fed_by_the_workflow(wf, node, value), f"{value} is neither an input nor a lens's answer"
        for name, fed in runs(node):
            used = meta.find_undeclared_variables(env.parse(template_of(by_name(name))))
            assert used <= fed | INJECTED, f"{name} uses {sorted(used - fed - INJECTED)} that the workflow never passes"


@pytest.mark.parametrize("version, suffix", VERSIONS.items())
def test_the_check_gets_each_lens_answer(version, suffix):
    check = next(n for n in workflow(version)["nodes"] if n["name"] == "check")
    assert check["input_map"] == {f"{part}_answer": f"brief.brief_{part}{suffix}.output" for part in LENS_PARTS}


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
        "deal_breakers": deal_breakers(K1="yes"),
        "recommendation": {"decision": "change_wedge", "rule": "change_wedge", "deal_breakers": ["K1"],
                           "reason": reason, "new_wedge": "denial follow-up for independent offices"},
        "claims": [dict(c) for c in CLAIMS[:2]],
    }


# The deal-breaker checklist (queue #39): its ids and rows, as check_brief.py and both synthesizers list them.
CHECKLIST = {"K1": "value", "K2": "feasibility", "K3": "feasibility", "K4": "viability", "K5": "viability",
             "K6": "go_to_market"}


def deal_breakers(fixed=("K1", "K2", "K3", "K4", "K5", "K6"), **answers):
    """K1-K6 answered (no unless given), each with its evidence; a yes is fixed by the wedge if it is in fixed."""
    entries = []
    for kid, row in CHECKLIST.items():
        answer = answers.get(kid, "no")
        entry = {"id": kid, "row": row, "answer": answer, "claims": ["F1"] if answer == "yes" else ["F2"],
                 "why": f"What the cited evidence shows for {kid}, in a sentence or two of plain words."}
        if answer == "unknown":
            entry.update(claims=[], test="a desk count of the offices that already pay for it")
        if answer == "yes":
            entry["fixed_by_wedge"] = kid in fixed
            if kid in fixed:
                entry["fix"] = "Independent offices use no tool that does this follow-up yet [F1], so the new wedge leaves it."
        entries.append(entry)
    return entries


FIGURE_CLAIMS = {
    "viability": [claim("V2", ADS, "Average cost per click: $2.00", "benchmark", "secondary"),
                  claim("V3", ADS, "Average conversion rate: 5.0%", "benchmark", "secondary")],
    "gtm": [claim("G2", APPS, "Median cost per install: $4.00", "benchmark", "secondary"),
            claim("G3", APPS, "convert 2.0% of downloads to paid", "benchmark", "primary"),
            claim("G4", APPS, "Offices outside the United States pay $50 a month", "price", "primary"),
            claim("G5", APPS, "Map loads cost $7.00 per 1,000 events", "price", "primary")],
}
LENS_CLAIMS = {"feasibility": CLAIMS, "viability": [dict(CLAIMS[0], id="V1"), *FIGURE_CLAIMS["viability"]],
               "gtm": [dict(CLAIMS[1], id="G1"), *FIGURE_CLAIMS["gtm"]], "competition": [dict(CLAIMS[2], id="C1")]}


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
    # The call rule (queue #39).
    ("no deal-breaker checklist", lambda b, lens: b.pop("deal_breakers"), "deal_breakers: missing"),
    ("a question left out", lambda b, lens: b["deal_breakers"].pop(), "deal-breaker K6 (go_to_market): not answered"),
    ("a question off the checklist", lambda b, lens: b["deal_breakers"].append(dict(b["deal_breakers"][1], id="K7")),
     "deal_breakers: unknown ids K7"),
    ("a question on another row", lambda b, lens: b["deal_breakers"][1].update(row="usability"),
     "deal-breaker K2: row must be feasibility"),
    ("a yes with no evidence", lambda b, lens: b["deal_breakers"][0].update(claims=[]),
     "deal-breaker K1: a yes cites no claim"),
    ("a yes from an invented source", lambda b, lens: b["deal_breakers"][0].update(claims=["F9"]),
     "claim F9: cited but in no lens file"),
    ("an unknown with no test", lambda b, lens: b["deal_breakers"][3].update(answer="unknown", claims=[]),
     "deal-breaker K4: unknown, so say what the next test checks"),
    ("a yes not marked fixed or not", lambda b, lens: b["deal_breakers"][0].pop("fixed_by_wedge"),
     "deal-breaker K1: a yes needs fixed_by_wedge true or false"),
    ("a fix that says nothing", lambda b, lens: b["deal_breakers"][0].update(fix="the wedge"),
     "deal-breaker K1: fixed_by_wedge, so say how the named wedge fixes it"),
    ("a call the deal-breakers don't give", lambda b, lens: b["recommendation"].update(
        decision="advance", first_paid_test="a fake door for independent offices with deposits"),
     "call rule: the deal-breakers give change_wedge"),
    ("the wrong rule named", lambda b, lens: b["recommendation"].update(rule="advance"),
     "recommendation.rule must name the rule that fired: change_wedge"),
    ("the open deal-breakers not listed", lambda b, lens: b["recommendation"].update(deal_breakers=[]),
     "recommendation.deal_breakers must list the open deal-breakers: [K1]"),
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
    ("a failed call for a write-up", lambda ws: lens_file(ws, "feasibility.md").write_text(STREAM_ENDED),
     "feasibility lens left no usable output: lenses/feasibility.md is an account-limit or error message"),
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


@pytest.mark.parametrize("answer", ["API Error: 529 Overloaded. Try again later.", TIMED_OUT, STREAM_ENDED],
                         ids=["overloaded", "timed out", "stream ended"])
def test_a_lens_whose_final_answer_is_a_limit_message_fails_even_with_its_files(workspace, answer):
    result = check(workspace, gtm=answer)
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
    ("Error: claude token pool exhausted \u2014 all 3 tokens cooling; soonest reset 2026-10-05 22:50Z", True),
    (TIMED_OUT, True),
    ("Error: spawn claude ENOENT", True),
    (STREAM_ENDED, True),
    ("Done: wrote lenses/gtm.json and lenses/gtm.md.", False),
    ("No error: both files written.", False),
    ("The vendor's API has a rate limit of 100 calls a minute. " * 12, False),
    ('{"status": "completed", "note": "quota of 250 checks"}', False),
    ('[{"claim": "F1", "note": "[claude_code error] seen in the vendor forum"}]', False),
], ids=["session limit", "usage limit", "credit", "login", "empty", "pool exhausted", "timed out", "cli failed",
        "stream ended", "short research", "error mid-text", "long research", "json", "json array"])
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


@pytest.mark.parametrize("version, suffix", VERSIONS.items())
def test_the_workflow_outputs_name_fields_their_steps_print(workspace, version, suffix):
    prompt = by_name(f"brief_synthesize{suffix}")["system_prompt"]
    contract = re.search(r'(\{"status": "completed",.*?"problems_left": 0\})', prompt, re.S)
    assert contract, f"brief_synthesize{suffix} no longer shows the JSON it finishes with"
    printed = {"brief": set(json.loads(contract.group(1))), "check": set(check(workspace))}
    for ref in workflow(version)["outputs"].values():
        node, _, field = ref.partition(".structured.")
        assert field in printed[node], f"{ref}: {node} never prints `{field}`"


# Derived figures (queue #25): each one recomputed from its inputs, its units followed through its formula,
# and each sourced input held to what its source counts.

def sourced(name, value, unit, source, measures, population="search-ad clicks", scope="search ads, 2026"):
    return {"name": name, "value": value, "unit": unit, "population": population, "scope": scope,
            "source": source, "measures": measures}


def assumed(name, value, unit, why="set against the vendor's per-check price [F2]"):
    return {"name": name, "value": value, "unit": unit, "source": "ASSUMPTION", "why": why}


def figure(fid, name, value, unit, formula, inputs, population="our paying users", scope="our first market"):
    return {"id": fid, "name": name, "value": value, "unit": unit, "population": population, "scope": scope,
            "formula": formula, "inputs": inputs}


CPC = sourced("cpc", 2.00, "USD / click", "V2", "Average cost per click")
LEAD_RATE = sourced("lead_rate", 0.05, "lead / click", "V3", "the number of leads you get divided by clicks")


def figured_brief(questions, rows):
    """A brief whose money numbers are all tabled and counted over matching things."""
    brief = good_brief(questions, rows)
    brief["figures"] = [
        figure("D1", "cost of one search lead", 40, "USD / lead", "cpc / lead_rate", [CPC, LEAD_RATE],
               "search-ad leads", "search ads, 2026"),
        figure("D2", "app-store ads per paying user", 200, "USD / payer", "cpi / paid_share", [
            sourced("cpi", 4.00, "USD / install", "G2", "Median cost per install", "app installs", "app stores"),
            sourced("paid_share", 0.02, "payer / install", "G3", "convert 2.0% of downloads to paid",
                    "app installs", "app stores")]),
        figure("D3", "revenue per paying user a year", 120, "USD / payer / year", "price * months", [
            assumed("price", 10, "USD / payer / month"),
            {"name": "months", "value": 12, "unit": "month / year", "source": "DEFINITION"}]),
        figure("D4", "years for a payer to repay the ads", 1.67, "year", "ads / revenue",
               [{"name": "ads", "source": "D2"}, {"name": "revenue", "source": "D3"}]),
    ]
    why = {
        "viability": "Revenue is about $120 a year per paying user (D3) on an assumed $10 a month price, and no "
                     "source gives our cost to serve yet.",
        "go_to_market": "A search lead costs about $40 (D1, from V2 V3); a paying user costs about $200 in "
                        "app-store ads (D2) against about $120 a year of revenue per payer (D3), so the ads are "
                        "repaid in about 1.7 years (D4).",
    }
    for row in brief["risks"]:
        row["why"] = why.get(row["row"], row["why"])
    brief["recommendation"]["reason"] = ("Change the wedge: a paying user costs about $200 in ads, which "
                                         "revenue of about $120 a year per payer repays in under two years, "
                                         "but the first wedge is crowded.")
    return brief


@pytest.fixture
def figured(workspace):
    checker = load(workspace / "check_brief.py")
    path = workspace / "state" / "brief" / "brief.json"
    path.write_text(json.dumps(figured_brief(checker.QUESTIONS, checker.ROWS)))
    return workspace


def rewrite(ws, mutate):
    path = ws / "state" / "brief" / "brief.json"
    brief = json.loads(path.read_text())
    mutate(brief)
    path.write_text(json.dumps(brief))


def fig(brief, fid):
    return next(f for f in brief["figures"] if f["id"] == fid)


def inp(brief, fid, name):
    return next(i for i in fig(brief, fid)["inputs"] if i["name"] == name)


def row(brief, name):
    return next(r for r in brief["risks"] if r["row"] == name)


def margin_per_active_user(brief):
    brief["figures"].append(figure("D6", "margin per active user a year", 9, "USD / active_user / year",
                                   "commission * bookings", [
                                       assumed("commission", 30, "USD / booking"),
                                       assumed("bookings", 0.3, "booking / active_user / year")],
                                   "active users"))


def weigh(text):
    def mutate(brief):
        margin_per_active_user(brief)
        brief["recommendation"]["reason"] = text
    return mutate


def ads_per_active_user(brief):
    brief["figures"].append(figure("D7", "app-store ads per active user", 10, "USD / active_user",
                                   "ads * paying_share", [
                                       {"name": "ads", "source": "D2"},
                                       assumed("paying_share", 0.05, "payer / active_user")], "active users"))


def office_price(bridge=None, scope="offices outside the United States"):
    def mutate(brief):
        price = sourced("price", 50, "USD / office / month", "G4", "pay $50 a month", "offices", scope)
        if bridge:
            price["bridge"] = bridge
        brief["figures"].append(figure("D8", "revenue per office a year", 600, "USD / office / year",
                                       "price * months", [price, {"name": "months", "value": 12,
                                                              "unit": "month / year", "source": "DEFINITION"}],
                                       "offices", "every office we sell to"))
    return mutate


def test_a_brief_whose_figures_add_up_and_match_in_kind_passes(figured):
    result = check(figured)
    assert result["verdict"] == "pass", result["problems"]
    assert result["items"]["figures"] and result["figures_checked"] == 4
    assert {"V2", "V3", "G2", "G3"} <= {c["id"] for c in result["spot_check"] + [{"id": i} for i in
                                                                                   result["spot_check_reserve"]]}


FIGURE_PASSES = [
    ("like with like, through a tabled step",
     lambda b: (margin_per_active_user(b), ads_per_active_user(b), b["recommendation"].update(
         reason="Change the wedge: margin is about $9 per active user a year (D6), while one active user costs "
                "about $10 in ads (D7), and the first wedge is crowded."))),
    ("a narrower source carried over with a reason",
     office_price(bridge="the vendor lists one price for every country on the same page")),
    ("a price per thousand, converted by a DEFINITION",
     lambda b: b["figures"].append(figure("D9", "map cost per paying user a year", 42, "USD / payer / year",
                                          "loads * price / per_k", [
                                              assumed("loads", 6000, "event / payer / year"),
                                              sourced("price", 7, "USD per 1,000 events", "G5",
                                                      "Map loads cost $7.00 per 1,000 events", "map loads",
                                                      "the map vendor's list price"),
                                              {"name": "per_k", "value": 1000, "unit": "event / k_event",
                                               "source": "DEFINITION"}]))),
    # Run 57dc513d's Places calls, priced per 1,000 events: an API call is a billable event.
    ("API calls priced per thousand events",
     lambda b: b["figures"].append(figure("D9", "map cost per paying user a year", 42, "USD / payer / year",
                                          "loads * price / per_k", [
                                              assumed("loads", 6000, "api call / payer / year"),
                                              sourced("price", 7, "USD per 1,000 events", "G5",
                                                      "Map loads cost $7.00 per 1,000 events", "map loads",
                                                      "the map vendor's list price"),
                                              {"name": "per_k", "value": 1000, "unit": "event / k_event",
                                               "source": "DEFINITION"}]))),
    # Run 57dc513d's feasibility row: "$1 or more per session" is not its $0.89 subscription figure.
    ("a round number near a figure is not that figure",
     lambda b: (b["figures"].append(figure("D10", "subscription per active user a year", 0.89,
                                           "USD / active_user / year", "paying_share * price", [
                                               assumed("paying_share", 0.021, "payer / active_user"),
                                               assumed("price", 42.49, "USD / payer / year")], "active users")),
                row(b, "feasibility").update(why="Hosting the model costs about $1 or more per session, which "
                                                   "no tier we found avoids."))),
]


@pytest.mark.parametrize("mutate", [p[1] for p in FIGURE_PASSES], ids=[p[0] for p in FIGURE_PASSES])
def test_figures_that_hold_pass(figured, mutate):
    rewrite(figured, mutate)
    result = check(figured)
    assert result["verdict"] == "pass", result["problems"]


def test_a_bridged_scope_is_noted(figured):
    rewrite(figured, office_price(bridge="the vendor lists one price for every country on the same page"))
    assert check(figured)["figure_notes"] == [
        "figure D8 (revenue per office a year), input price covers only international; bridged: the vendor lists "
        "one price for every country on the same page"]


FIGURE_BREAKS = [
    ("arithmetic off", lambda b: fig(b, "D1").update(value=36),
     "figure D1 (cost of one search lead): arithmetic: cpc / lead_rate gives 40, but the figure says 36"),
    ("a lead rate used as the share who start (run fc575760)",
     lambda b: b["figures"].append(figure("D5", "cost per quiz start", 40, "USD / quiz_start", "cpc / start_rate", [
         CPC, dict(LEAD_RATE, name="start_rate", unit="quiz_start / click")])),
     "figure D5 (cost per quiz start), input start_rate: its unit counts quiz_start, but V3's own words "
     "(quote and measures) never do"),
    ("a lead rate kept as leads, the figure called per start",
     lambda b: b["figures"].append(figure("D5", "cost per quiz start", 40, "USD / quiz_start", "cpc / lead_rate",
                                          [CPC, LEAD_RATE])),
     "figure D5 (cost per quiz start): inputs don't match in kind: cpc / lead_rate gives USD / lead, but the "
     "figure is USD / quiz_start"),
    ("ads per payer weighed against margin per active user (run 57dc513d)",
     weigh("Kill: margin is about $9 per active user a year (D6), while one paying user costs about $200 in ads "
           "(D2), so paid acquisition never pays back."),
     'recommendation weighs "$9" (figure D6, USD / active_user / year) against "$200" (figure D2, USD / payer): '
     "figures counted per active_user and per payer don't match in kind"),
    ("a figure said to be per something it is not",
     lambda b: row(b, "go_to_market").update(why="A user costs about $200 per active user in ads (D2), so the "
                                                 "first channel has to be free."),
     'risk row go_to_market: "$200 per active user" says per active_user, but figure D2 is USD / payer'),
    ("a derived number with no figure",
     lambda b: row(b, "go_to_market").update(why=row(b, "go_to_market")["why"] + " A demo costs about $55."),
     'A demo costs about $55." is a derived number with no figure'),
    ("a number its source never states", lambda b: inp(b, "D1", "cpc").update(value=2.5),
     "figure D1 (cost of one search lead), input cpc: value 2.5 is not a number that V2's quote or measures "
     "words state"),
    ("measures words that are not on the page", lambda b: inp(b, "D1", "cpc").update(measures="cost per lead"),
     "figure D1 (cost of one search lead), input cpc: its measures words are not on V2's kept page or in its quote"),
    ("a rate written as a percentage", lambda b: inp(b, "D1", "lead_rate").update(unit="%"),
     "figure D1 (cost of one search lead), input lead_rate: unit '%' is a percentage"),
    ("a rate that names no counted thing", lambda b: inp(b, "D1", "lead_rate").update(unit="conversion / click"),
     "input lead_rate: unit 'conversion' names a rate or a share, not what is counted"),
    ("a number hidden in the formula", lambda b: fig(b, "D1").update(formula="cpc / lead_rate * 1.1"),
     "figure D1 (cost of one search lead): formula cpc / lead_rate * 1.1 may use only its inputs' names"),
    ("unlike things added", lambda b: fig(b, "D1").update(formula="cpc + lead_rate"),
     "figure D1 (cost of one search lead): inputs don't match in kind: it adds or subtracts USD / click and "
     "lead / click"),
    ("an input the formula leaves out", lambda b: fig(b, "D1")["inputs"].append(dict(CPC, name="spare")),
     "figure D1 (cost of one search lead): inputs spare are listed but the formula does not use them"),
    ("a figure built on itself", lambda b: fig(b, "D4")["inputs"].append({"name": "again", "source": "D4"}),
     "figure D4: its inputs loop back to itself"),
    ("a DEFINITION that converts nothing", lambda b: inp(b, "D3", "months").update(value=10),
     "figure D3 (revenue per paying user a year), input months: DEFINITION is only for unit conversions"),
    ("an ASSUMPTION with no reason", lambda b: inp(b, "D3", "price").update(why=""),
     "figure D3 (revenue per paying user a year), input price: an ASSUMPTION says why"),
    ("a source that does not exist", lambda b: inp(b, "D1", "cpc").update(source="V9"),
     "figure D1 (cost of one search lead), input cpc: source must be a claim id that exists"),
    ("a figure with no population", lambda b: fig(b, "D2").update(population=""),
     "figure D2 (app-store ads per paying user): say its population"),
    ("a source's limit left out of the input", office_price(scope="every office"),
     "figure D8 (revenue per office a year), input price: G4's words limit it to international; say so in its "
     "scope"),
    ("a narrower source with no reason it carries over", office_price(),
     "figure D8 (revenue per office a year), input price: covers only international, but the figure does not"),
]


@pytest.mark.parametrize(("mutate", "problem"), [b[1:] for b in FIGURE_BREAKS], ids=[b[0] for b in FIGURE_BREAKS])
def test_a_figure_that_does_not_hold_fails_and_says_why(figured, mutate, problem):
    rewrite(figured, mutate)
    result = check(figured)
    assert result["verdict"] == "fail" and not result["items"]["figures"]
    assert any(problem in p for p in result["problems"]), result["problems"]


def test_the_check_reads_the_units_it_is_given(workspace):
    checker = load(workspace / "check_brief.py")
    assert checker.parse_unit("USD per paying user per year") == ({"USD": 1, "payer": -1, "year": -1}, "")
    assert checker.parse_unit("downloads / active users") == ({"install": 1, "active_user": -1}, "")
    assert checker.parse_unit("trip / person / yr") == ({"trip": 1, "person": -1, "year": -1}, "")
    assert checker.parse_unit("USD / MTok") == ({"USD": 1, "m_token": -1}, "")
    assert checker.parse_unit("USD per 1,000 events") == ({"USD": 1, "k_event": -1}, "")
    assert checker.conversion(["token", "m_token"]) == 1000000 and checker.conversion(["year", "month"]) == 1 / 12
    assert checker.evaluate("(a - b) / c", {"a": (10.0, {"USD": 1}), "b": (4.0, {"USD": 1}),
                                            "c": (2.0, {"payer": 1})})[:2] == (3.0, {"USD": 1, "payer": -1})


@pytest.mark.parametrize("name", ["brief_synthesize", "brief_synthesize_consumer"])
def test_the_synthesizer_is_told_to_table_its_figures(name):
    prompt = by_name(name)["system_prompt"]
    assert "DERIVED FIGURES" in prompt and '"figures": [<every derived figure' in prompt
    assert "An input's unit is what ITS SOURCE counts" in prompt


# The call rule: the same evidence should give the same call. Six fixed deal-breaker questions feed
# a written rule, and the check recomputes the decision independently of the synthesizer's judgment.

CALLS = [
    ("nothing open", {}, (), "advance"),
    ("unknowns are no deal-breakers", {"K2": "unknown", "K6": "unknown"}, (), "advance"),
    ("one yes the wedge fixes", {"K1": "yes"}, ("K1",), "change_wedge"),
    ("every yes fixed by the one wedge", {"K1": "yes", "K6": "yes", "K3": "unknown"}, ("K1", "K6"), "change_wedge"),
    ("a yes no wedge fixes", {"K3": "yes"}, (), "kill"),
    ("one of two yes unfixed", {"K1": "yes", "K4": "yes"}, ("K1",), "kill"),
]


@pytest.mark.parametrize(("answers", "fixed", "call"), [c[1:] for c in CALLS], ids=[c[0] for c in CALLS])
def test_the_call_is_the_one_the_deal_breakers_give(workspace, answers, fixed, call):
    open_ids = sorted(k for k, a in answers.items() if a == "yes")

    def as_ruled(brief):
        brief["deal_breakers"] = deal_breakers(fixed, **answers)
        brief["recommendation"].update(decision=call, rule=call, deal_breakers=open_ids,
                                       first_paid_test="a fake door for independent offices with deposits")

    rewrite(workspace, as_ruled)
    result = check(workspace)
    assert result["verdict"] == "pass", result["problems"]
    assert (result["rule"], result["open_deal_breakers"]) == (call, open_ids)
    for other in sorted({"advance", "change_wedge", "kill"} - {call}):
        rewrite(workspace, lambda b: b["recommendation"].update(decision=other, rule=other))
        result = check(workspace)
        assert result["verdict"] == "fail" and not result["items"]["call_rule"]
        assert any(p.startswith(f"call rule: the deal-breakers give {call}") for p in result["problems"]), \
            result["problems"]


def deal_breaker_block(name):
    prompt = by_name(name)["system_prompt"]
    found = re.search(r"^ *E\. DEAL-BREAKERS AND THE CALL\..*?(?=^ *F\. ENGINE SUGGESTION)", prompt, re.S | re.M)
    assert found, f"{name} no longer has its deal-breaker block"
    return found.group(0)


def test_both_synthesizers_ask_the_checklist_the_check_recomputes(workspace):
    business, consumer = deal_breaker_block("brief_synthesize"), deal_breaker_block("brief_synthesize_consumer")
    assert business == consumer, "both versions answer the same questions in the same words"
    assert dict(re.findall(r"^ +(K\d) (\w+) ", business, re.M)) == CHECKLIST
    assert dict(load(workspace / "check_brief.py").DEAL_BREAKERS) == CHECKLIST
    for name in ("brief_synthesize", "brief_synthesize_consumer"):
        prompt = by_name(name)["system_prompt"]
        assert "Rule of thumb" not in prompt, "the call is the rule's, not a weighing of the risk table"
        assert '"deal_breakers": [{"id": "K1"' in prompt and '"rule": "the rule that fired' in prompt
