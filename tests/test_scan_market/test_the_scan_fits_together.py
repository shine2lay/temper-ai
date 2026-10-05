"""The market scan (configs/workflows/scan_market.yaml, product role) fits together.

v3 (queue #19) adds a mechanical source check, cite.py's method (desk_check, opportunity_brief).
Its configs: setup, the demand lens, then the market and timing lenses side by side on its pockets,
sources, synthesize, trace, then the frozen scan_check and scan_check_strict beside it; each script
step parses under /bin/sh; the model steps
keep Claude Code's own tools; every template variable is fed by the workflow; the outputs name
fields their steps print; scan_check stays the frozen yardstick byte for byte. Its helpers: setup
clears the last run and writes cite.py (desk_setup's own) and check_sources.py. check_sources.py
confirms a figure only when the one sentence holding it is on its page's saved copy (HTTP 200,
readable text) with the figure's numbers in it; its trace passes only counted figures that are
confirmed, of the right kind, tagged in shortlist.md and on a page that names the candidate's
segment; primary pain only from a community, gov, association, academic or independent survey
source (v3.1); a real price only for the job itself (scope job), its job words on the page and in
the candidate's own name or wedge (v3.1); it names the ranked candidates as scan_serving does. No
model and no network: every input here is synthetic.

v4 (queue #18) adds a first step, pick (scan_pick_industries): it chooses each run's 6-9 industries,
mostly ground past scans never searched, and the demand lens hunts there instead of a fixed list of
nine; setup clears the last run's pick.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
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
WORKFLOW = ROOT / "configs" / "workflows" / "scan_market.yaml"
SCRIPTS = ["scan_setup", "scan_sources", "scan_trace"]
MODELS = ["scan_pick_industries", "scan_lens_demand", "scan_lens_market", "scan_lens_timing", "scan_synthesize",
          "scan_check", "scan_check_strict"]
CHANGED = ["scan_setup", "scan_sources", "scan_trace", "scan_pick_industries", "scan_lens_demand", "scan_lens_market",
           "scan_lens_timing", "scan_synthesize", "scan_check_strict"]
INJECTED = {"workspace_path", "run_id"}  # the agents add these to every template
# The frozen grader every scan version is compared on (product PLAN.md, notebook n3).
SCAN_CHECK_SHA256 = "8072a8227b6eac351b50829b664ae1f6d77daaf94a589d76d75d93497031f4eb"


def served(path):
    """The config as the server hands it out (ConfigStore.get runs the env substitution)."""
    return substitute_env_vars(yaml.safe_load(path.read_text()))


def by_name(name):
    return served(AGENTS_DIR / f"{name}.yaml")["agent"]


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


def heredoc(script, path, marker):
    """The file a setup script writes with `cat > <path> <<'<marker>'`."""
    found = re.search(rf"^cat > {re.escape(path)} <<'{marker}'\n(.*?)\n{marker}$", script, re.S | re.M)
    assert found, f"the script no longer writes {path}"
    return found.group(1) + "\n"


def module_of(text, name, path):
    """A helper's code as a module, without running its command line or leaving bytecode."""
    module = types.ModuleType(name)
    module.__file__ = path
    exec(compile(text, path, "exec"), module.__dict__)
    return module


SETUP_SCRIPT = by_name("scan_setup")["script_template"]
CHECKER_TEXT = heredoc(SETUP_SCRIPT, "state/desk/check_sources.py", "CHECKEOF")
checker = module_of(CHECKER_TEXT, "scan_check_sources", "/nonexistent/state/desk/check_sources.py")
SERVING_CHECKER = AGENTS_DIR / "scan_serving_assets" / "check_serving.py"
serving = module_of(SERVING_CHECKER.read_text(), "scan_serving_check", str(SERVING_CHECKER))


# ---- the configs ---------------------------------------------------------------------------------


def test_the_workflow_checks_sources_before_ranking_and_grades_twice():
    wf = workflow()
    nodes = {n["name"]: n for n in wf["nodes"]}
    assert list(nodes) == ["setup", "pick", "demand", "research", "sources", "synthesize", "trace", "check",
                           "check_strict"]
    assert nodes["setup"]["agent"] == "scan_setup" and not nodes["setup"].get("depends_on")
    assert (nodes["pick"]["agent"], nodes["pick"]["depends_on"]) == ("scan_pick_industries", ["setup"])
    assert nodes["pick"]["input_map"] == {"frame": "input.frame"}, "the picker reads the explored ideas in the frame"
    assert (nodes["demand"]["agent"], nodes["demand"]["depends_on"]) == ("scan_lens_demand", ["pick"]), \
        "the demand lens hunts in the run's pick"
    research = nodes["research"]
    assert (research["type"], research["strategy"], research["depends_on"]) == ("stage", "parallel", ["demand"]), \
        "the market and timing lenses work on the demand lens's pockets"
    assert [a["agent"] for a in research["agents"]] == ["scan_lens_market", "scan_lens_timing"]
    chain = {"sources": ("scan_sources", ["research"]), "synthesize": ("scan_synthesize", ["sources"]),
             "trace": ("scan_trace", ["synthesize"]), "check": ("scan_check", ["trace"]),
             "check_strict": ("scan_check_strict", ["trace"])}
    for name, (agent_name, after) in chain.items():
        assert (nodes[name]["agent"], nodes[name]["depends_on"]) == (agent_name, after), name
    assert set(wf["inputs"]) == {"frame"} and wf["inputs"]["frame"]["required"] is False, \
        "the Monday cadence (weekly_scan.py) starts the scan with a frame at most"


@pytest.mark.parametrize("name", SCRIPTS + MODELS)
def test_each_agent_file_is_named_after_its_agent(name):
    assert by_name(name)["name"] == name


@pytest.mark.parametrize("name", SCRIPTS)
def test_every_script_step_parses_under_sh(name):
    cfg = by_name(name)
    assert cfg["type"] == "script"
    script = jinja().from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render()
    done = subprocess.run(["sh", "-n", "-c", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, f"{name} does not parse under /bin/sh: {done.stderr.strip()}"


@pytest.mark.parametrize("path", [*(AGENTS_DIR / f"{n}.yaml" for n in CHANGED), WORKFLOW], ids=lambda p: p.stem)
def test_no_file_holds_the_config_stores_env_syntax(path):
    assert "${" not in path.read_text(), "the config store would substitute it as an env var"


@pytest.mark.parametrize(("path", "marker"), [("state/desk/cite.py", "CITEEOF"),
                                              ("state/desk/check_sources.py", "CHECKEOF")])
def test_the_helpers_hold_no_jinja_delimiters(path, marker):
    assert not re.search(r"\{\{|\{%|\{#", heredoc(SETUP_SCRIPT, path, marker)), \
        "the script template is rendered by Jinja: a delimiter would change the helper"


@pytest.mark.parametrize("name", MODELS)
def test_the_model_steps_keep_claude_codes_own_tools(name):
    cfg = by_name(name)
    assert cfg["provider"] == "claude"
    assert "tools" not in cfg, "provider claude refuses temper tool schemas; it uses its own Bash/Read/Write/Web tools"


def test_every_template_variable_is_fed_by_the_workflow():
    env = jinja()
    wf = workflow()
    for node in wf["nodes"]:
        fed = set(node.get("input_map") or {})
        for value in (node.get("input_map") or {}).values():
            assert value.startswith("input.") and value.split(".", 1)[1] in wf["inputs"], f"{value} is not an input"
        names = [a["agent"] for a in node["agents"]] if node.get("type") == "stage" else [node["agent"]]
        for name in names:
            for template in templates_of(by_name(name)):
                used = meta.find_undeclared_variables(env.parse(template))
                assert used <= fed | INJECTED, f"{name} uses {sorted(used - fed - INJECTED)} that the workflow never passes"


def printed(name):
    """The fields of the JSON a grader is told to finish with."""
    text = "\n".join(templates_of(by_name(name)))
    block = re.search(r"```json\n(\{.*?\})\n```", text, re.S)
    assert block, f"{name} no longer shows the JSON it finishes with"
    return set(json.loads(block.group(1)))


TRACE_PRINTS = {"status", "trace_path", "ok", "c2", "c4", "problems"}


def test_the_workflow_outputs_name_fields_their_steps_print():
    fields = {"check": printed("scan_check"), "check_strict": printed("scan_check_strict"), "trace": TRACE_PRINTS,
              "pick": printed("scan_pick_industries")}
    for ref in workflow()["outputs"].values():
        node, _, field = ref.partition(".structured.")
        assert field in fields[node], f"{ref}: {node} never prints `{field}`"


def test_scan_check_is_the_frozen_yardstick():
    digest = hashlib.sha256((AGENTS_DIR / "scan_check.yaml").read_bytes()).hexdigest()
    assert digest == SCAN_CHECK_SHA256, ("scan_check is the frozen grader every scan version is compared on; "
                                         "change it only by an owner decision, then update this pin")


def test_the_strict_grader_never_reads_the_frozen_graders_verdict():
    text = "\n".join(templates_of(by_name("scan_check_strict")))
    assert "Never read or cite state/scan/grade.md" in text
    assert "state/scan/grade-strict.md" in text and "state/scan/trace.json" in text


def test_the_demand_lens_hunts_in_the_runs_pick_not_a_fixed_list():
    text = "\n".join(templates_of(by_name("scan_lens_demand")))
    assert "state/scan/industries.md" in text
    assert "Cover these domains" not in text and "logistics & trucking" not in text, \
        "the nine fixed industries (through v3) are the picker's explored ground now, not the hunting ground"
    # Trial run 4 (76c5b77e): pockets became the record or roster beside a priced course, device or
    # medical evaluation, a job with no price; a pocket is the job the pick priced.
    flat = " ".join(text.split())
    assert "a pocket is that job itself" in flat and "is a different job, with no price" in flat


def test_the_picker_widens_the_ground_and_bans_nothing():
    cfg = by_name("scan_pick_industries")
    text = "\n".join(templates_of(cfg))
    assert "6 to 9 industries" in text and "At most 2 from the explored ground" in text
    assert "no industry is off limits" in text, "owner rule: no blanket sector exclusion"
    assert "state/scan/industries.json" in text and "state/scan/industries.md" in text
    # Trial run 1 (88aaab5c) picked industries whose software sells only as suites, so the market lens
    # had no job's own price for 5 of 12 pockets: a pick must show a job sold at a price.
    flat = " ".join(text.split())
    assert "THAT SAME JOB" in flat and "a whole suite's price" in flat and '"priced_jobs"' in flat
    assert "Open that pricing page with cite.py" in flat
    # Trial run 2 (2613d31d) picked industries nobody measures (breweries' TTB filing, machine shops'
    # calibration), so the demand lens counted one brewer's Reddit comment relayed by a newsletter:
    # a pick must also show a pain number a named body measured for one of its jobs.
    assert "MEASURED PAIN NUMBER" in flat and '"pain_numbers"' in flat and '"measured_by"' in flat
    assert "one person's story or comment" in flat and "even when a newsletter" in flat
    assert "Open that page with cite.py" in flat
    # Trial run 3 (a03874a3): the picker saw the nonprofits' own-job price (Tax990) only through
    # WebFetch's summary; the page draws its prices with a script, so the market lens's cite.py saw
    # none and counted a neighbouring job's price. Both pages are now read with cite.py (a FOUND
    # quote), for the SAME job, and the pain number is measured 2016 or later.
    assert "python3 state/desk/cite.py quote" in flat and "keep only a FOUND quote" in flat
    assert "never as the check" in flat and "A product for a neighbouring job" in flat
    assert "2016 or later" in flat and '"quote"' in flat and '"year"' in flat
    # Trial run 4 (76c5b77e): three picks priced a device, a training course and a medical
    # evaluation, so the ideas built beside them (audit trail, certification records, roster) had
    # no price. The product must do the job the way a software company could.
    assert "the way a software company could" in flat and "hardware (an ID scanner" in flat
    assert "a training course" in flat and "a licensed or certified person performs" in flat
    assert "not a device, a course or a licensed person's examination" in flat
    assert "frame" in meta.find_undeclared_variables(jinja().parse(cfg["task_template"]))


def test_setup_writes_desk_setups_own_cite_helper():
    desk = by_name("desk_setup")["script_template"]
    assert heredoc(SETUP_SCRIPT, "state/desk/cite.py", "CITEEOF") == heredoc(desk, "state/desk/cite.py", "CITEEOF")


# ---- setup: a clean desk and both helpers ---------------------------------------------------------------


def setup(workspace):
    """The real setup step, rendered the way the script agent renders it and run by /bin/sh."""
    cfg = by_name("scan_setup")
    stash = _ValueStash()
    script = jinja(stash).from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render(
        workspace_path=str(workspace))
    env = {**os.environ, **stash.env, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=30, cwd=workspace, env=env)


def test_setup_clears_the_last_run_and_writes_both_helpers(tmp_path):
    scan, desk = tmp_path / "state" / "scan", tmp_path / "state" / "desk"
    stale = [scan / "evidence" / "demand.json", desk / "pages" / "old.txt", scan / "shortlist.md",
             scan / "shortlist.json", scan / "sources.json", scan / "trace.json", scan / "grade-strict.md",
             scan / "industries.md", scan / "industries.json"]
    kept = scan / "history" / "2026-10-01" / "shortlist.md"
    for path in [*stale, kept]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale")
    done = setup(tmp_path)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["status"] == "completed"
    assert not [path for path in stale if path.exists()]
    assert list((scan / "evidence").iterdir()) == [] and list((desk / "pages").iterdir()) == []
    assert kept.read_text() == "stale", "setup removes only what a scan writes"
    assert (desk / "check_sources.py").read_text() == CHECKER_TEXT
    assert (desk / "cite.py").read_bytes() == (AGENTS_DIR / "scan_serving_assets" / "cite.py").read_bytes()


# ---- the source check: one figure, one sentence, one saved page -------------------------------------------

URL = "https://example.org/fictional-clinic-survey"
PAGE = ("FICTIONAL survey of independent dental clinics, 2026. Front-desk staff spend 13 hours per week "
        "re-keying insurance details. Nine percent of claims are denied for missing data. Pricing starts at "
        "$79 per location per month. The vendor raised $4.6 million in seed funding.")
BLOCKED = "https://example.org/fictional-blocked-report"
PDF = "https://example.org/fictional-report.pdf"
STARTUP = "https://example.org/fictional-claims-startup"
STARTUP_PAGE = ("FICTIONAL claims-automation startup raises $4.6 million. It is live with several third-party "
                "administrators, including a California-based multiline TPA.")
# The trial run 0de83c03 case: an association's article whose figure is a software vendor's platform data.
NEWS = "https://example.org/fictional-association-news"
NEWS_PAGE = ("FICTIONAL Apartment Association news: 10 things about maintenance work orders. The average work order "
             "takes 3.88 days to complete, from creation to completion. Source: 2024 FICTIONAL WorkApp data. Share "
             "Print. Copyright FICTIONAL Apartment Association.")
OWN = "https://example.org/fictional-association-survey"
OWN_PAGE = ("FICTIONAL Apartment Association survey results. The average work order takes 3.88 days to complete, "
            "from creation to completion. Source: FICTIONAL Apartment Association 2024 members survey.")
STUDY = "https://example.org/fictional-claims-study"
STUDY_PAGE = "2026 FICTIONAL Claims Study - JD Metrics. The average repair takes 19.3 days in this year's study."
# The trial run 3f0f2283 case: figures on a page that look like prices but are not what a seller charges.
REVIEW = "https://example.org/fictional-software-directory"
REVIEW_PAGE = ("FICTIONAL InsureCheck review for dental insurance checks. Its pricing is estimated to range between "
               "$20-$100/user/month. Without it, your clinic could spend over $7,000 a year on insurance checks. "
               "Members get the insurance checks plan free, a $995/year value. InsureCheck charges $49 per month "
               "for insurance checks. Owners also make estimated tax payments of $500 for insurance checks. "
               "InsureCheck raised $12 million at an estimated valuation of $60 million.")


class Desk:
    """A workspace after the real setup: saved pages and the lenses' evidence records."""

    def __init__(self, workspace):
        done = setup(workspace)
        assert done.returncode == 0, done.stderr
        self.root = workspace
        self.records = {"demand": [], "market": []}
        self.page(URL, PAGE)
        self.page(BLOCKED, PAGE, http="403")
        self.page(PDF, "", note="PDF but no pdftotext here")
        self.page(STARTUP, STARTUP_PAGE)
        self.page(NEWS, NEWS_PAGE)
        self.page(OWN, OWN_PAGE)
        self.page(STUDY, STUDY_PAGE)
        self.page(REVIEW, REVIEW_PAGE)

    def page(self, url, text, http="200", note=None):
        head = {"url": url, "final_url": url, "http": http, "content_type": "text/html",
                "fetched": "2026-10-04T00:00:00+00:00"}
        if note:
            head["note"] = note
        name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt"
        (self.root / "state" / "desk" / "pages" / name).write_text(json.dumps(head) + "\n" + text)

    def add(self, lens, record):
        self.records[lens].append(record)

    def run(self, *args, write=True):
        if write:
            for lens, records in self.records.items():
                (self.root / "state" / "scan" / "evidence" / f"{lens}.json").write_text(json.dumps(records))
        done = subprocess.run([sys.executable, "state/desk/check_sources.py", *args], cwd=self.root,
                              capture_output=True, text=True, timeout=60,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        assert done.returncode == 0, done.stderr
        return done.stdout

    def sources(self):
        self.run("--record")
        return json.loads((self.root / "state" / "scan" / "sources.json").read_text())


@pytest.fixture
def desk(tmp_path):
    return Desk(tmp_path)


def pain(rid="D1", **change):
    return {"id": rid, "area": "Dental: insurance verification", "kind": "pain", "figure": "13 hours per week",
            "quote": "Front-desk staff spend 13 hours per week re-keying insurance details.", "url": URL,
            "source": "FICTIONAL survey body", "primary": True, "source_type": "association",
            "measured_by": "FICTIONAL survey", "measured_by_quote": "FICTIONAL survey of independent dental clinics, 2026.",
            **change}


def relayed(rid="D1", **change):
    """The run 0de83c03 miss: the publisher named as the measurer of a vendor's data."""
    return pain(rid, **{"area": "Multifamily: work orders", "figure": "3.88 days",
                        "quote": "The average work order takes 3.88 days to complete, from creation to completion.",
                        "url": NEWS, "source": "FICTIONAL Apartment Association",
                        "measured_by": "FICTIONAL Apartment Association",
                        "measured_by_quote": "Copyright FICTIONAL Apartment Association.", **change})


def price(rid="M1", **change):
    return {"id": rid, "area": "Dental: insurance verification", "kind": "price",
            "figure": "$79 per location per month", "quote": "Pricing starts at $79 per location per month.",
            "url": URL, "source": "FICTIONAL vendor pricing page", "provenance": "vendor_page_fetched",
            "scope": "job", "job": "insurance", **change}


CONFIRMED = [
    ("a sentence copied from the page", "demand", pain()),
    ("case, spacing and a dropped full stop", "demand",
     pain(quote="front-desk staff  spend 13 HOURS per week re-keying insurance details")),
    ("a dash written differently", "demand",
     pain(quote="Front\u2013desk staff spend 13 hours per week re\u2011keying insurance details.")),
    ("a number written in words", "demand",
     pain(figure="9%", quote="Nine percent of claims are denied for missing data.")),
    ("a price", "market", price()),
    ("a scaled number", "market",
     price(kind="funding", figure="$4.6M", quote="The vendor raised $4.6 million in seed funding.")),
]


@pytest.mark.parametrize(("lens", "record"), [c[1:] for c in CONFIRMED], ids=[c[0] for c in CONFIRMED])
def test_a_figure_whose_sentence_is_on_its_saved_page_is_confirmed(desk, lens, record):
    desk.add(lens, record)
    row = desk.sources()["records"][0]
    assert (row["status"], row["reasons"]) == ("CONFIRMED", [])


UNCONFIRMED = [
    ("a sentence the page never says", "demand",
     pain(figure="10.9 days", quote="Average invoice receipt-to-approval cycle is 10.9 days."),
     "the quote is not on the saved page"),
    ("a figure missing from its sentence", "demand", pain(figure="21%"), "the figure's number(s) 21 are not in the quote"),
    ("the wrong scale", "market",
     price(kind="funding", figure="$4.6 billion", quote="The vendor raised $4.6 million in seed funding."),
     "are not in the quote"),
    ("a page never read", "demand", pain(url="https://example.org/never-read"), "no saved copy of this address"),
    ("a blocked page", "demand", pain(url=BLOCKED), "the page answered HTTP 403"),
    ("a page with no readable text", "demand", pain(url=PDF), "no readable text (PDF but no pdftotext here)"),
    ("a kind its lens never records", "demand", pain(kind="price"), "kind must be one of"),
    ("a fragment, not a sentence", "demand", pain(quote="13 hours per"), "4 to 80 words"),
    ("an id from the other lens", "demand", pain(rid="M1"), "id must be D1, D2, ..."),
    ("words without digits not in the quote", "demand", pain(figure="most clinics"),
     "the figure (no digits) is not in the quote"),
]


@pytest.mark.parametrize(("lens", "record", "reason"), [c[1:] for c in UNCONFIRMED], ids=[c[0] for c in UNCONFIRMED])
def test_a_figure_the_saved_page_does_not_hold_stays_unconfirmed_and_says_why(desk, lens, record, reason):
    desk.add(lens, record)
    row = desk.sources()["records"][0]
    assert row["status"] == "UNCONFIRMED"
    assert any(reason in why for why in row["reasons"]), row["reasons"]


def test_a_duplicate_id_is_never_confirmed(desk):
    desk.add("demand", pain())
    desk.add("demand", pain())
    rows = desk.sources()["records"]
    assert [r["status"] for r in rows] == ["CONFIRMED", "UNCONFIRMED"] and "duplicate id" in rows[1]["reasons"]


def test_the_record_step_labels_every_figure_and_counts_only_confirmed_ones(desk):
    desk.add("demand", pain())
    desk.add("demand", pain("D2", primary=False))
    desk.add("demand", pain("D3", figure="10.9 days", quote="Average approval cycle is 10.9 days."))
    desk.add("demand", pain("D4", source_type="vendor_survey"))
    desk.add("market", price())
    desk.add("market", price("M2", scope="suite"))
    data = desk.sources()
    assert data["problems"] == []
    assert data["summary"] == {"demand": {"records": 4, "confirmed": 3}, "market": {"records": 2, "confirmed": 2},
                               "confirmed_primary_pain": 1, "confirmed_price_or_funding": 2,
                               "confirmed_job_price_or_funding": 1}
    report = (desk.root / "state" / "scan" / "sources.md").read_text()
    measurer = "measured by FICTIONAL survey"
    assert f"| D1 | pain | 13 hours per week | CONFIRMED | primary pain | association, primary, {measurer} |" in report
    assert f"| D3 | pain | 10.9 days | UNCONFIRMED | - | association, primary, {measurer} |" in report
    assert "the quote is not on the saved page" in report
    assert f"| D4 | pain | 13 hours per week | CONFIRMED | - | vendor_survey, primary, {measurer} |" in report, \
        "a vendor's own survey is kept and confirmed, but never counts as primary pain"
    assert "| M1 | price | $79 per location per month | CONFIRMED | real price | job (insurance) |" in report
    assert "| M2 | price | $79 per location per month | CONFIRMED | - | suite (insurance) |" in report, \
        "a suite's price is context, never a real price"


def test_a_lens_file_that_is_not_a_list_is_a_problem_not_a_crash(desk):
    desk.run("--record")
    (desk.root / "state" / "scan" / "evidence" / "demand.json").write_text("not JSON")
    desk.run("--record", write=False)
    problems = json.loads((desk.root / "state" / "scan" / "sources.json").read_text())["problems"]
    assert problems == ["state/scan/evidence/demand.json: must hold a JSON list of records"]


def test_a_lens_sees_its_own_records_with_reasons_and_hints(desk):
    desk.add("demand", pain())
    desk.add("demand", pain("D2", quote="Staff spend 13 hours per week on insurance details."))
    out = desk.run("demand")
    assert "D1 CONFIRMED pain | 13 hours per week" in out
    assert "D2 UNCONFIRMED pain" in out and "hint: the page has 13 at:" in out
    assert ("demand: 2 records, 1 CONFIRMED (1 primary pain in 1 areas, 0 job-scope price/funding in 0 areas), "
            "1 UNCONFIRMED") in out


MEASURERS = [
    ("the publisher named while the page credits a vendor's data", relayed(), False,
     "the page credits the data next to this figure to '2024 FICTIONAL WorkApp data', not to "
     "'FICTIONAL Apartment Association'"),
    ("the publisher's own survey, credited to it",
     relayed(url=OWN, measured_by_quote="FICTIONAL Apartment Association survey results."), True, None),
    ("the vendor named and labelled honestly",
     relayed(measured_by="FICTIONAL WorkApp", measured_by_quote="Source: 2024 FICTIONAL WorkApp data.",
             source_type="vendor"), False, "its source_type is vendor"),
    ("one person's story", pain(source_type="anecdote"), False, "its source_type is anecdote"),
    ("a generic measurer", pain(measured_by="the association"), False,
     "measured_by must name the body that collected the data"),
    ("a measurer sentence the page never says",
     pain(measured_by_quote="The FICTIONAL survey polled 900 dental clinics."), False,
     "its measured_by_quote is not on the saved page"),
    ("a measurer sentence naming someone else", pain(measured_by="FICTIONAL Clinic Group"), False,
     "its measured_by_quote never names 'FICTIONAL Clinic Group'"),
    ("no measurer recorded", pain(measured_by=None, measured_by_quote=None), False, "no measured_by_quote"),
    ("a name written with dots",
     pain(figure="19.3 days", quote="The average repair takes 19.3 days in this year's study.", url=STUDY,
          source_type="independent_survey", measured_by="J.D. Metrics",
          measured_by_quote="2026 FICTIONAL Claims Study - JD Metrics."), True, None),
]


@pytest.mark.parametrize(("record", "counts", "reason"), [m[1:] for m in MEASURERS], ids=[m[0] for m in MEASURERS])
def test_primary_pain_needs_its_measurer_named_on_the_page_and_in_its_credit_line(desk, record, counts, reason):
    desk.add("demand", record)
    data = desk.sources()
    assert data["records"][0]["status"] == "CONFIRMED", "the measurer never changes what is confirmed"
    assert data["summary"]["confirmed_primary_pain"] == (1 if counts else 0)
    if reason:
        report = (desk.root / "state" / "scan" / "sources.md").read_text()
        assert reason in report, report
        if record["source_type"] in ("association", "independent_survey"):
            out = desk.run("demand")
            assert "counts? " in out and reason in out, "the lens is told, so it can fix the record"


NOT_PRICES = [
    ("a third party's estimate of a seller's price", "$20-$100/user/month",
     "Its pricing is estimated to range between $20-$100/user/month.", "its quote gives an estimate ('estimated')"),
    ("what a buyer could spend", "$7,000 a year",
     "Without it, your clinic could spend over $7,000 a year on insurance checks.",
     "its quote gives a cost a buyer could incur ('could spend')"),
    ("what something given away is worth", "$995/year",
     "Members get the insurance checks plan free, a $995/year value.",
     "its quote gives what something is worth ('$995/year value')"),
    ("a seller's own price", "$49 per month", "InsureCheck charges $49 per month for insurance checks.", None),
    ("'estimated tax' is not an estimate of a price", "$500",
     "Owners also make estimated tax payments of $500 for insurance checks.", None),
]


@pytest.mark.parametrize(("figure", "quote", "reason"), [n[1:] for n in NOT_PRICES], ids=[n[0] for n in NOT_PRICES])
def test_a_real_price_is_what_a_seller_charges(desk, figure, quote, reason):
    desk.add("market", price(figure=figure, quote=quote, url=REVIEW))
    data = desk.sources()
    assert data["records"][0]["status"] == "CONFIRMED", "the price rule never changes what is confirmed"
    assert data["summary"]["confirmed_job_price_or_funding"] == (0 if reason else 1)
    if reason:
        assert reason in (desk.root / "state" / "scan" / "sources.md").read_text()
        out = desk.run("market")
        assert "counts? " in out and reason in out, "the lens is told, so it can fix the record"


def test_funding_quoting_an_estimated_valuation_still_counts(desk):
    desk.add("market", price(kind="funding", figure="$12 million", url=REVIEW,
                             quote="InsureCheck raised $12 million at an estimated valuation of $60 million."))
    assert desk.sources()["summary"]["confirmed_job_price_or_funding"] == 1


def test_a_lens_hears_why_a_confirmed_figure_still_cannot_count(desk):
    desk.add("demand", pain(source_type="vendor_survey"))
    desk.add("market", price(scope="suite"))
    desk.add("market", price("M2", job="credentialing"))
    assert "counts? marked primary, but a vendor_survey source never counts as primary pain" in desk.run("demand")
    out = desk.run("market")
    assert "M1 CONFIRMED price" in out and "counts? its saved page never names its job 'credentialing'" in out
    assert "market: 2 records, 2 CONFIRMED (0 primary pain in 0 areas, 0 job-scope price/funding in 0 areas)" in out


# ---- the trace: what the shortlist counted -------------------------------------------------------------


def candidate(rank=1, name="Insurance verification for independent dental clinics", terms=("dental",),
              pain_ids=("D1",), price_ids=("M1",), market_led=False):
    return {"rank": rank, "name": name, "wedge": "Check coverage before the visit", "segment_terms": list(terms),
            "market_led": market_led, "pain_ids": list(pain_ids), "price_ids": list(price_ids)}


def shortlist_md(candidates, extra=()):
    lines = ["# Shortlist (synthetic)", "## Ranking table", "| Rank | Candidate | Score |", "|---|---|---|"]
    lines += [f"| {c['rank']} | {c['name']} | 3.0 |" for c in candidates]
    lines += ["## Ranked shortlist"]
    for c in candidates:
        lines += [f"### #{c['rank']} \u2014 {c['name']}. Score 3.0",
                  "- pain_and_source: " + " ".join(f"[{i}]" for i in c["pain_ids"]),
                  "- price: " + " ".join(f"[{i}]" for i in c["price_ids"]), ""]
    return "\n".join([*lines, *extra]) + "\n"


def traced(desk, candidates, md=None):
    scan = desk.root / "state" / "scan"
    (scan / "shortlist.json").write_text(json.dumps({"candidates": candidates}))
    (scan / "shortlist.md").write_text(md if md is not None else shortlist_md(candidates))
    desk.run("--record")
    printed_line = json.loads(desk.run("--trace").strip().splitlines()[-1])
    assert set(printed_line) == TRACE_PRINTS
    return json.loads((scan / "trace.json").read_text())


@pytest.fixture
def evidence(desk):
    desk.add("demand", pain())
    desk.add("demand", pain("D2", figure="10.9 days", quote="Average approval cycle is 10.9 days."))
    desk.add("demand", pain("D3", primary=False))
    desk.add("demand", pain("D4", source_type="vendor_survey"))
    desk.add("demand", relayed("D5"))
    desk.add("market", price())
    desk.add("market", price("M2", kind="funding", figure="$4.6 million", job="claims",
                             quote="FICTIONAL claims-automation startup raises $4.6 million.", url=STARTUP))
    desk.add("market", price("M3", scope="suite"))
    desk.add("market", price("M4", job="credentialing"))
    desk.add("market", price("M5", job="claims"))
    desk.add("market", price("M6", job="software platform"))
    desk.add("market", price("M7", figure="$20-$100/user/month", url=REVIEW,
                             quote="Its pricing is estimated to range between $20-$100/user/month."))
    return desk


def test_a_shortlist_counting_confirmed_figures_from_its_segments_pages_passes(evidence):
    trace = traced(evidence, [candidate()])
    assert (trace["ok"], trace["problems"]) == (True, [])
    assert trace["c2"] == {"confirmed_primary_pain": 1, "candidates": 1, "met": True}
    assert trace["c4"] == {"confirmed_price": 1, "candidates": 1, "met": True}
    assert (evidence.root / "state" / "scan" / "trace.md").exists()


def test_funding_from_a_page_that_never_names_the_segment_does_not_count_as_its_price(evidence):
    """The 2026-10-02 trial 2 case: a claims startup's funding counted as the price for workers' comp."""
    trace = traced(evidence, [candidate(name="Workers' comp claims review for single-state TPAs",
                                        terms=("workers comp",), pain_ids=(), market_led=True,
                                        price_ids=("M2",))])
    assert trace["problems"] == ["#1 Workers' comp claims review for single-state TPAs counts M2 as a real price, but "
                                 "its saved page never names the segment term(s) ['workers comp']"]
    assert trace["c4"]["met"] is False


def test_the_same_funding_counts_for_a_segment_its_page_names(evidence):
    trace = traced(evidence, [candidate(name="Claims intake for TPAs", terms=("tpa",), pain_ids=(),
                                        market_led=True, price_ids=("M2",))])
    assert (trace["ok"], trace["c4"]["met"]) == (True, True)


TRACE_BREAKS = [
    ("an unconfirmed figure counted", dict(pain_ids=("D2",)), "counts D2 as primary pain, but the script left it UNCONFIRMED"),
    ("a pain stat not marked primary", dict(pain_ids=("D3",)), "counts D3 as primary pain, but its record is not marked primary"),
    ("a pain stat counted as a price", dict(price_ids=("D1",)), "counts D1 as a real price, but its kind is pain"),
    ("an id no lens recorded", dict(price_ids=("M9",)), "counts M9 as a real price, but no such record"),
    ("a generic segment term", dict(terms=("small businesses",)),
     "segment term 'small businesses' names no segment on its own"),
    ("a segment term not in its own name", dict(terms=("veterinary",)),
     "segment term 'veterinary' is not in its own name or wedge"),
    ("no segment term", dict(terms=()), "needs 1-3 segment_terms"),
    ("four segment terms", dict(terms=("dental", "insurance", "verification", "visit")), "at most 3 segment_terms"),
    ("no pain and not market-led", dict(pain_ids=()), "not market-led, so it must count a primary pain id"),
    ("a vendor's own survey counted as primary pain", dict(pain_ids=("D4",)),
     "counts D4 as primary pain, but its source_type is vendor_survey; primary pain needs one of"),
    ("a vendor's data relayed on an association's page", dict(pain_ids=("D5",)),
     "counts D5 as primary pain, but the page credits the data next to this figure to '2024 FICTIONAL WorkApp data'"),
    ("a suite's price counted", dict(price_ids=("M3",)), "counts M3 as a real price, but its scope is suite"),
    ("a price for a job its page never names", dict(price_ids=("M4",)),
     "counts M4 as a real price, but its saved page never names its job 'credentialing'"),
    ("a price for another candidate's job", dict(price_ids=("M5",)),
     "counts M5 as a real price, but its job 'claims' is not in the candidate's own name or wedge"),
    ("a price whose job is generic words", dict(price_ids=("M6",)),
     "counts M6 as a real price, but its job must be 1-4 words naming the job it pays for"),
    ("a third party's estimate counted as a price", dict(price_ids=("M7",)),
     "counts M7 as a real price, but its quote gives an estimate ('estimated')"),
]


@pytest.mark.parametrize(("change", "problem"), [b[1:] for b in TRACE_BREAKS], ids=[b[0] for b in TRACE_BREAKS])
def test_a_counted_figure_short_of_the_rules_fails_the_trace_and_says_why(evidence, change, problem):
    trace = traced(evidence, [candidate(**change)])
    assert trace["ok"] is False
    assert any(problem in p for p in trace["problems"]), trace["problems"]


def test_every_counted_figure_must_be_tagged_in_the_shortlist(evidence):
    md = shortlist_md([candidate()]).replace(" [M1]", "")
    trace = traced(evidence, [candidate()], md)
    assert any("counts M1 as a real price, but shortlist.md never tags [M1]" in p for p in trace["problems"])


def test_an_unconfirmed_figure_may_be_shown_only_labelled_unconfirmed(evidence):
    labelled = traced(evidence, [candidate()], shortlist_md([candidate()], ["- context: 10.9 days (unconfirmed) [D2]"]))
    assert (labelled["ok"], labelled["problems"]) == (True, [])
    bare = traced(evidence, [candidate()], shortlist_md([candidate()], ["- context: 10.9 days [D2]"]))
    assert any("cites D2, which the script left UNCONFIRMED, without the word 'unconfirmed'" in p
               for p in bare["problems"])
    unknown = traced(evidence, [candidate()], shortlist_md([candidate()], ["- context: [D7]"]))
    assert any("tags [D7], which no lens recorded" in p for p in unknown["problems"])


def test_the_json_must_name_the_same_ranked_candidates_as_the_markdown(evidence):
    md = shortlist_md([candidate()]).replace("### #1 \u2014 Insurance verification", "### #1 \u2014 Insurance checks")
    trace = traced(evidence, [candidate()], md)
    assert any("shortlist.json's (rank, name) pairs must equal shortlist.md's ranked headings" in p
               for p in trace["problems"])


def five(market_led=(), no_price=()):
    return [candidate(rank=n, name=f"Insurance verification for dental clinics, variant {n}",
                      pain_ids=() if n in market_led else ("D1",), market_led=n in market_led,
                      price_ids=() if n in no_price else ("M1",)) for n in range(1, 6)]


@pytest.mark.parametrize(("market_led", "met"), [((), True), ((5,), True), ((4, 5), False)],
                         ids=["5 of 5", "4 of 5", "3 of 5"])
def test_primary_pain_needs_four_in_five_candidates(evidence, market_led, met):
    trace = traced(evidence, five(market_led=market_led))
    assert trace["c2"]["met"] is met and trace["c2"]["confirmed_primary_pain"] == 5 - len(market_led)


def test_a_real_price_needs_every_candidate(evidence):
    assert traced(evidence, five())["c4"]["met"] is True
    trace = traced(evidence, five(no_price=(5,)))
    assert trace["c4"] == {"confirmed_price": 4, "candidates": 5, "met": False}


def test_the_trace_says_so_when_the_sources_step_never_ran(evidence):
    traced(evidence, [candidate()])
    (evidence.root / "state" / "scan" / "sources.json").unlink()
    json.loads(evidence.run("--trace", write=False).strip().splitlines()[-1])
    trace = json.loads((evidence.root / "state" / "scan" / "trace.json").read_text())
    assert "no readable state/scan/sources.json: the sources step did not run" in trace["problems"]


# ---- naming the ranked candidates as scan_serving does -----------------------------------------------------


def test_the_trace_reads_headings_with_scan_servings_patterns():
    """The same patterns in the same order; the checker spells its dashes as \\u escapes (its heredoc stays ASCII)."""
    spelled = [p.pattern.replace("\\u2014", "\u2014").replace("\\u2013", "\u2013") for p in checker.HEADINGS]
    assert spelled == [p.pattern for p in serving.HEADINGS]
    assert [p.flags for p in checker.HEADINGS] == [p.flags for p in serving.HEADINGS]


@pytest.mark.parametrize("style", ["### #{n} \u2014 {name}. Score 3.0", "### {n}. {name} \u2014 score 12.00",
                                   "### {n}) {name} (score 3.1)"], ids=["v3", "2026-10-01", "parenthesised"])
def test_the_trace_and_the_screen_name_the_same_candidates(style):
    names = ["Dental insurance verification", "Unit-turn coordination \u2014 small landlords",
             "AP invoice capture. Sold through bookkeepers"]
    md = "\n".join(["# Shortlist", "## Ranked shortlist", *(style.format(n=n, name=name) for n, name in
                                                          enumerate(names, 1))]) + "\n"
    assert [name for _, name in checker.headings(md)] == [checker.norm(name) for name in
                                                          serving.parse_identities(md).values()]
