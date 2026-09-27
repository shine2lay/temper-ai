"""One value on every screen (queue task 7).

Most defects the live checks found were two screens showing different values for the same thing:
- b028's DIS entry ticket gave four drop-to-call figures for one after-state (F084): 62.6% in the
  new block, 71.8% in "Can you afford it?", 71.6% in "If the call does not fill";
- b030's /positions filed the AAPL $255 call under "Fine", while its ladder said "Your rule says
  roll this one" (F087);
- b037's Actions showed Margin cushion 80.0% and the entry preview 75.1%, same account, same
  minute (F105).

So the plan lists each figure or verdict a bet changes that shows on more than one screen
(tasks.json `same_value`), QA compares those screens on the build and, where they differ, on
production (read only), and the measure compares them on prod. The owner's rule (2026-09-25):
"Fail it if the bet caused the difference; if it was there before, only note it." The gate
applies it; ship puts the noted ones on the card and the PR.

The gate runs out of the shipped YAML through the real ScriptAgent (the harness of
test_a_clause_nobody_walked_is_not_a_pass), so the Jinja that carries the list is exercised too.
"""

import json
import subprocess
import sys
from pathlib import Path

import yaml

from tests.test_epd import test_epd_loop
from tests.test_epd.test_a_clause_nobody_walked_is_not_a_pass import PASSED, gate
from tests.test_epd.test_epd_loop import propose
from tests.test_epd.test_gate_card import card
from tests.test_epd.test_small_findings_get_a_last_pass import minors, rendered

# The driver, loaded with its state in a temporary directory: test_epd_loop's fixture, by name.
L = test_epd_loop.L

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "configs" / "epd" / "agents"
WORKFLOWS = ROOT / "configs" / "epd" / "workflows"


def check(what, build, before, build_values=(), before_values=()) -> dict:
    """One line of verify's same_value_checks."""
    return {"what": what, "build": build, "build_values": list(build_values),
            "before": before, "before_values": list(before_values), "note": ""}


# F084, as the live check read it on prod (b028 is merged, so production has it too).
DIS_DROP = [{"screen": "/browse DIS entry: the margin block", "value": "62.6%"},
            {"screen": "/browse DIS entry: Can you afford it?", "value": "71.8%"},
            {"screen": "/browse DIS entry: If the call does not fill", "value": "71.6%"}]
B028 = check("Drop to call after this entry", "differ", "differ", DIS_DROP, DIS_DROP)

# F105 made up as a bet's doing: the entry preview changed on the build, production agrees.
B037_CAUSED = check(
    "Margin cushion", "differ", "agree",
    [{"screen": "/actions: Margin cushion", "value": "80.0%"},
     {"screen": "entry preview: Margin cushion, Now", "value": "75.1%"}],
    [{"screen": "/actions: Margin cushion", "value": "80.0%"},
     {"screen": "entry preview: Margin cushion, Now", "value": "80.0%"}])

# F087 as if the ladder's advice were a screen the build adds.
B030_NEW = check(
    "What to do with the AAPL $255 Nov 6 call", "differ", "new",
    [{"screen": "/positions: Later", "value": "Fine"},
     {"screen": "/ladder AAPL $255: the rule's advice", "value": "Your rule says roll this one"}])


def gate_with(*checks, **inputs) -> dict:
    return gate(**(PASSED | inputs), qa_same_value=list(checks))


class TestTheOwnersRule:
    """ "Fail it if the bet caused the difference; if it was there before, only note it." """

    def test_a_difference_production_already_has_is_noted_not_failed(self):
        """b028's four drop-to-call figures read the same way on production: not this build's."""
        out = gate_with(B028)
        assert out["verdict"] == "approve"
        assert out["same_value_caused"] == []
        [noted] = out["same_value_noted"]
        assert "Drop to call after this entry" in noted and "already differs on production" in noted
        assert "62.6%" in noted and "71.8%" in noted, "the values are what the owner judges"
        assert "noted, not failed" in out["summary"]

    def test_a_qa_fail_for_nothing_else_is_lifted(self):
        out = gate_with(B028, qa_verdict="fail")
        assert out["verdict"] == "approve", out["summary"]

    def test_one_screen_changed_by_the_build_fails(self):
        """The made-up case: production's screens agree, the build's do not."""
        out = gate_with(B037_CAUSED)
        assert out["verdict"] == "request_changes"
        assert out["changes_wanted_by"] == ["QA"], "QA's objection, even though QA said pass"
        assert out["same_value_caused"] == [B037_CAUSED]
        assert "this build caused it" in out["summary"]
        [issue] = [i for i in out["qa_issues"] if "Margin cushion" in str(i)]
        assert "80.0%" in issue["what"] and "75.1%" in issue["what"], "the implementer sees both values"
        assert "/actions" in issue["where"]

    def test_a_screen_the_build_adds_counts_as_caused(self):
        out = gate_with(B030_NEW)
        assert out["verdict"] == "request_changes"
        assert any("a screen this build adds" in str(i) for i in out["qa_issues"])

    def test_production_not_read_is_noted_with_the_cause_unknown(self):
        out = gate_with(check("Margin cushion", "differ", "unread", B037_CAUSED["build_values"]))
        assert out["verdict"] == "approve"
        [noted] = out["same_value_noted"]
        assert "the cause is unknown" in noted

    def test_agreeing_or_unread_screens_change_nothing(self):
        out = gate_with(check("Drop to call", "agree", "not_read"), check("Price cushion", "unread", "not_read"))
        assert out["verdict"] == "approve"
        assert out["same_value_noted"] == [] and out["same_value_caused"] == []
        assert "screens" not in out["summary"]

    def test_qa_is_named_once_when_it_also_failed(self):
        out = gate_with(B037_CAUSED, qa_verdict="fail")
        assert out["changes_wanted_by"].count("QA") == 1

    def test_a_real_issue_keeps_the_fail_beside_a_noted_difference(self):
        out = gate_with(B028, qa_verdict="fail",
                        qa_issues=[{"where": "/positions", "what": "The page shows a stack trace"}])
        assert out["verdict"] == "request_changes"

    def test_no_list_is_the_gate_as_before(self):
        out = gate(**PASSED)
        assert out["verdict"] == "approve"
        assert out["same_value_noted"] == [] and out["same_value_caused"] == []

    def test_a_caused_difference_gets_no_last_pass(self):
        """The small-findings pass is for review's small findings alone: QA is asking here."""
        out = gate_with(B037_CAUSED, review_verdict="request_changes",
                        review_findings=[{"severity": "minor", "where": "a.ts:1", "what": "stale comment"}])
        assert minors(out)["take"] is False


def wiring(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / f"{name}.yaml").read_text())["workflow"]


def node(workflow: dict, name: str) -> dict:
    return next(n for n in workflow["nodes"] if n["name"] == name)


class TestTheWiring:
    """The list goes plan -> build's QA -> gate -> ship, and plan -> measure."""

    def test_the_plan_puts_the_list_out(self):
        assert wiring("epd_plan")["outputs"]["same_value"] == "lead.structured.same_value"

    def test_the_loop_hands_it_to_the_build_and_the_measure(self):
        loop = wiring("epd_loop")
        build = node(loop, "build")["input_map"]
        assert build["same_value"] == "tasks.structured.same_value"
        assert (build["before_url"], build["before_email"], build["before_password"]) == (
            "input.measure_url", "input.before_email", "input.measure_password"), "production, as qa@"
        assert node(loop, "measure")["input_map"]["same_value"] == "tasks.structured.same_value"
        assert node(loop, "ship")["input_map"]["same_value_noted"] == "build.structured.same_value_noted"
        assert "before_email" in loop["inputs"]

    def test_the_build_gives_it_to_qa_and_qa_to_the_gate(self):
        task = wiring("epd_task")
        for name in ("same_value", "before_url", "before_email", "before_password"):
            assert name in task["inputs"]
            assert node(task, "verify")["input_map"][name] == f"input.{name}"
        assert node(task, "gate")["input_map"]["qa_same_value"] == "verify.structured.same_value_checks"
        assert task["outputs"]["same_value_noted"] == "gate.structured.same_value_noted"
        assert task["outputs"]["same_value_caused"] == "gate.structured.same_value_caused"
        assert task["outputs"]["verify_same_value"] == "verify.structured.same_value_checks"

    def test_the_measure_and_ship_take_it(self):
        measure = wiring("epd_measure")
        assert "same_value" in measure["inputs"]
        assert node(measure, "measure")["input_map"]["same_value"] == "input.same_value"
        assert measure["outputs"]["same_value"] == "measure.structured.same_value"
        ship = wiring("epd_ship")
        assert "same_value_noted" in ship["inputs"]
        assert node(ship, "ship")["input_map"]["same_value_noted"] == "input.same_value_noted"


LISTED = [{"what": "Margin cushion", "source": "backend/rollcall/api/overview.py:margin_cushion",
           "screens": [{"route": "/actions", "where": "the Margin cushion card", "login": "qa@rollcall.test"},
                       {"route": "/browse", "where": "entry preview, Margin cushion row, Now",
                        "login": "qa@rollcall.test"}]}]


class TestWhatTheAgentsAreTold:

    def test_qa_gets_the_screens_and_the_before_side(self):
        text = rendered("task_verify", app_url="https://epd-b001.dev.example.com", email="qa@x", password="pw",
                        same_value=LISTED, before_url="https://prod.example.com",
                        before_email="qa@rollcall.test", before_password="prodpw")
        assert "One value on every screen" in text
        assert "- Margin cushion (from backend/rollcall/api/overview.py:margin_cushion)" in text
        assert "- /actions: the Margin cushion card (as qa@rollcall.test)" in text
        assert "- /browse: entry preview, Margin cushion row, Now (as qa@rollcall.test)" in text
        assert "production at https://prod.example.com" in text and "Read only." in text

    def test_qa_without_a_list_hears_nothing_of_it(self):
        text = rendered("task_verify", app_url="https://epd-b001.dev.example.com", email="qa@x", password="pw")
        assert "One value on every screen" not in text

    def test_qa_knows_the_rule_and_reports_both_sides(self):
        prompt = yaml.safe_load((AGENTS / "task_verify.yaml").read_text())["agent"]["system_prompt"]
        words = " ".join(prompt.split())
        assert "same_value_checks" in prompt and "before_values" in prompt
        assert "is a defect this change caused: the verdict is `fail`" in words
        assert "never press Scan or Refresh" in words

    def test_the_measure_gets_the_screens(self):
        text = rendered("epd_measure", outcome_path="/o.md", app_url="https://prod.example.com",
                        email="qa@x", password="pw", bet_path="/b.md", report_path="/r.md", same_value=LISTED)
        assert "Figures that show on more than one screen" in text
        assert "- /actions: the Margin cushion card (as qa@rollcall.test)" in text

    def test_the_plan_writes_the_list_and_the_check_looks_for_missing_screens(self):
        lead = yaml.safe_load((AGENTS / "epd_plan_lead.yaml").read_text())["agent"]["system_prompt"]
        assert '"same_value": [' in lead and "8. Every figure or verdict" in lead
        assert '"same_value": ["<the same list as in tasks.json>"]' in lead, "the reply carries it on"
        check_prompt = yaml.safe_load((AGENTS / "epd_plan_check.yaml").read_text())["agent"]["system_prompt"]
        assert "same_value (in tasks.json) misses a screen" in check_prompt
        assert "| same_value\"" in check_prompt
        # v6: the live test's plans missed "Can you afford it?", which works the figure out in other code
        assert "by what the figure means, in its words" in " ".join(check_prompt.split())


def write_tasks(L, bet_id: str, same_value) -> None:  # noqa: N803 (the fixture's name)
    tasks = {"bet_id": bet_id, "tasks": [], "not_doing": []}
    if same_value is not None:
        tasks["same_value"] = same_value
    (L.BETS_DIR / bet_id / "tasks.json").write_text(json.dumps(tasks))


class TestTheDriver:

    def test_the_build_gets_the_list_and_production_as_the_before_side(self, L, monkeypatch):  # noqa: N803
        monkeypatch.setattr(L, "ensure_qa_password", lambda: "prodpw")
        propose(L, bets=("b001",), empty=())
        write_tasks(L, "b001", LISTED)
        seen = {}
        monkeypatch.setattr(L, "run_workflow", lambda name, inputs, **kw: seen.update(inputs) or {"verdict": "approve"})
        L.stage_build(L.load_state("b001"))
        assert seen["same_value"] == LISTED
        assert (seen["before_url"], seen["before_email"], seen["before_password"]) == (
            L.PROD_URL, "qa@rollcall.test", "prodpw")

    def test_a_plan_without_the_list_adds_nothing(self, L, monkeypatch):  # noqa: N803
        monkeypatch.setattr(L, "ensure_qa_password", lambda: "prodpw")
        propose(L, bets=("b001",), empty=())
        write_tasks(L, "b001", None)
        seen = {}
        monkeypatch.setattr(L, "run_workflow", lambda name, inputs, **kw: seen.update(inputs) or {"verdict": "approve"})
        L.stage_build(L.load_state("b001"))
        assert "same_value" not in seen and "before_url" not in seen

    def test_the_measure_gets_the_list(self, L, monkeypatch):  # noqa: N803
        propose(L, bets=("b001",), empty=())
        bdir = L.BETS_DIR / "b001"
        write_tasks(L, "b001", LISTED)
        st = L.load_state("b001")
        st["status"] = "shipped"
        st["stages"]["ship"] = {"prod_url": "https://prod.example.com", "prod_qa": True}
        L.save_state(st)
        seen = {}
        for name in ("wait_for_url", "preflight_login", "ledger_upsert"):
            monkeypatch.setattr(L, name, lambda *a, **k: None)
        monkeypatch.setattr(L, "ensure_qa_password", lambda: "pw")

        def fake_run_workflow(name, inputs, **kw):
            seen.update(inputs)
            (bdir / "outcome.md").write_text("# outcome\n")
            return {"verdict": "iterate", "summary": "one figure differs"}

        monkeypatch.setattr(L, "run_workflow", fake_run_workflow)
        L.stage_measure(L.load_state("b001"), keep=True)
        assert seen["same_value"] == LISTED

    def test_the_composed_loop_names_qa_as_the_before_login(self, L, monkeypatch):  # noqa: N803
        monkeypatch.setattr(L, "ensure_qa_password", lambda: "pw")
        propose(L, bets=("b001",), empty=())
        assert L.loop_inputs("b001")["before_email"] == L.QA_EMAIL == "qa@rollcall.test"

    def test_the_pr_body_lists_the_noted_figures(self, L):  # noqa: N803
        md = L.same_value_md(["Drop to call (62.6% / 71.8%): it already differs on production"])
        assert md.startswith("## Same figure, different screens")
        assert "- Drop to call (62.6% / 71.8%): it already differs on production" in md
        assert L.same_value_md([]) == L.same_value_md(None) == ""


def record_block() -> str:
    """The python the ship agent runs to write build.json, taken out of the shipped YAML."""
    text = (AGENTS / "epd_ship.yaml").read_text()
    start = text.index('python3 - "$BET_DIR/build.json" \\')
    body = text[text.index("<<'PY'\n", start) + len("<<'PY'\n"):]
    body = body[:body.index("\n    PY\n")]
    return "\n".join(line[4:] if line.startswith("    ") else line for line in body.split("\n"))


class TestTheOwnerSeesTheNotedOnes:

    def test_the_record_keeps_them(self, tmp_path):
        noted = ["Drop to call (62.6% / 71.8%): it already differs on production"]
        values = ["epd-b001", "/w", "approve", "review approved", "approve", "pass", "pass",
                  "https://dev", "abc123", "did it", "epd-b001"]
        run = subprocess.run([sys.executable, "-c", record_block(), str(tmp_path / "build.json"), *values,
                              "[]", "[]", json.dumps(noted)], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        assert json.loads((tmp_path / "build.json").read_text())["same_value_noted"] == noted

    def test_the_card_lists_them(self, tmp_path):
        doc, _ = card(tmp_path, build={"same_value_noted": ["Drop to call: it already differs on production"]})
        assert "**Same figure, different screens**" in doc["summary"]
        assert "- Drop to call: it already differs on production" in doc["summary"]

    def test_a_card_with_none_says_nothing_of_it(self, tmp_path):
        doc, _ = card(tmp_path)
        assert "Same figure" not in doc["summary"]
