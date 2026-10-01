"""The checks reach every criterion (queue task 11, "why most bets ship as iterate").

33 of the 37 bets that came back iterate had a criterion the live check could not reach, so it was
vacuous and the bet could not be kept (~/epd-autopilot/iterate/buckets.md, cause 2):
- a failure nobody can make happen on production: a broker that stalls (b014, b034, b044);
- a book no live login held: an urgent roll, a roll offering several strikes (b005, b009, b030);
- a market open while the check ran shut (b019, b040).

RollCall has routes to most of these now (queue task 18): /dev/states on dev stacks, and
book-situation logins on production (qa-urgent@, qa-multiroll@, qa-catch@, qa-loss@, qa-settled@).
So the plan names each criterion's state and its route on the build and on production, or says
"build only" where production cannot show it (tasks.json `criteria_reach`); QA walks the build
routes; the live check walks the live ones, and counts a build-only criterion QA met as covered
instead of vacuous. The driver holds it to the plan (epd_loop.py build_covered_ok).
"""

import json

import yaml

from tests.test_epd import test_epd_loop
from tests.test_epd.test_epd_loop import propose
from tests.test_epd.test_one_value_on_every_screen import AGENTS, node, wiring
from tests.test_epd.test_small_findings_get_a_last_pass import rendered

# The driver, loaded with its state in a temporary directory: test_epd_loop's fixture, by name.
L = test_epd_loop.L

# b044's kind of bet: criterion 1 on a login production has, 2 only the dev stack can show.
REACH = [
    {"criterion": 1, "state": "an urgent roll card on /actions",
     "build": "qa-urgent@rollcall.test", "live": "qa-urgent@rollcall.test"},
    {"criterion": 2, "state": "the broker stalls past 10 s while /positions loads",
     "build": "/dev/states: Broker slow",
     "live": "build only: production's broker cannot be made to stall"},
]
# QA's walk of the build, as verify reports it.
WALKED = [
    {"clause": "1. The urgent card names the call to roll", "status": "met",
     "evidence": "qa-urgent@: /actions shows 'Roll AAPL $255 now' (shot 3)"},
    {"clause": "2. A stalled broker shows 'Your broker is slow to answer'", "status": "met",
     "evidence": "Broker slow pressed on /dev/states; /positions read the sentence after 10 s (shot 5)"},
]
COVERED = {"criterion": 2, "why": "production's broker cannot be made to stall",
           "qa_evidence": "Broker slow pressed on /dev/states; /positions read the sentence after 10 s"}


class TestTheWiring:
    """The list goes plan -> build's QA, and plan -> measure with QA's walk beside it."""

    def test_the_plan_puts_the_list_out(self):
        assert wiring("epd_plan")["outputs"]["criteria_reach"] == "lead.structured.criteria_reach"

    def test_the_loop_hands_it_to_the_build_and_the_measure(self):
        loop = wiring("epd_loop")
        assert node(loop, "build")["input_map"]["criteria_reach"] == "plan.structured.criteria_reach"
        measure = node(loop, "measure")["input_map"]
        assert measure["criteria_reach"] == "plan.structured.criteria_reach"
        assert measure["verify_threshold_checks"] == "build.structured.verify_threshold_checks"
        assert measure["accepted_unreachable"] == "build.structured.accepted_unreachable"
        for name in ("build_covered", "drifted_logins", "verify_threshold_checks", "accepted_unreachable"):
            assert name in loop["outputs"], f"finish_loop reads {name} from the loop's outputs"

    def test_the_build_gives_it_to_qa(self):
        task = wiring("epd_task")
        assert "criteria_reach" in task["inputs"]
        assert node(task, "verify")["input_map"]["criteria_reach"] == "input.criteria_reach"

    def test_the_measure_takes_it_and_says_what_it_covered(self):
        measure = wiring("epd_measure")
        for name in ("criteria_reach", "verify_threshold_checks", "accepted_unreachable"):
            assert name in measure["inputs"]
            assert node(measure, "measure")["input_map"][name] == f"input.{name}"
        assert measure["outputs"]["build_covered"] == "measure.structured.build_covered"
        assert measure["outputs"]["drifted_logins"] == "measure.structured.drifted_logins"


def prompt(agent: str) -> str:
    return " ".join(yaml.safe_load((AGENTS / f"{agent}.yaml").read_text())["agent"]["system_prompt"].split())


MEASURE = {"outcome_path": "/o.md", "app_url": "https://prod.example.com", "email": "qa@x", "password": "pw",
           "bet_path": "/b.md", "report_path": "/r.md"}


class TestWhatTheAgentsAreTold:

    def test_the_plan_writes_a_route_for_every_criterion(self):
        lead = prompt("epd_plan_lead")
        assert "10. Every numbered criterion goes in criteria_reach" in lead
        assert '"criteria_reach": [' in lead
        assert '"criteria_reach": ["<the same list as in tasks.json>"]' in lead, "the reply carries it on"
        assert "build only: <why production cannot show it>" in lead

    def test_the_plan_check_fails_a_missing_or_made_up_route(self):
        check = prompt("epd_plan_check")
        assert "criteria_reach (in tasks.json) has no entry for a numbered criterion" in check
        assert "Kind `reach`" in check

    def test_qa_gets_each_route_on_its_stack(self):
        text = rendered("task_verify", app_url="https://epd-b044.dev.example.com", email="qa@x", password="pw",
                        criteria_reach=REACH)
        assert "How to reach each criterion's state" in text
        assert "- criterion 1: an urgent roll card on /actions -- here: qa-urgent@rollcall.test" in text
        assert ("- criterion 2: the broker stalls past 10 s while /positions loads -- here: /dev/states: "
                "Broker slow; on production: build only: production's broker cannot be made to stall") in text

    def test_qa_without_the_list_hears_nothing_of_it(self):
        text = rendered("task_verify", app_url="https://epd-b044.dev.example.com", email="qa@x", password="pw")
        assert "How to reach each criterion's state" not in text

    def test_the_measure_gets_the_routes_and_qas_walk(self):
        text = rendered("epd_measure", **MEASURE, criteria_reach=REACH, verify_threshold_checks=WALKED)
        assert "How each criterion's state is reached on production (from the plan)" in text
        assert "- criterion 1: an urgent roll card on /actions -- on production: qa-urgent@rollcall.test" in text
        assert "- met: 2. A stalled broker shows 'Your broker is slow to answer' -- Broker slow pressed" in text
        assert "shipped these unproven" not in text

    def test_the_measure_hears_when_qas_walk_cannot_cover_anything(self):
        no_walk = rendered("epd_measure", **MEASURE, criteria_reach=REACH)
        assert "QA's walk was not given: no criterion is build_covered." in no_walk
        unproven = rendered("epd_measure", **MEASURE, criteria_reach=REACH, verify_threshold_checks=WALKED,
                            accepted_unreachable=["2. A stalled broker shows the sentence"])
        assert "The build shipped these unproven, so nothing is build_covered" in unproven

    def test_the_measure_without_the_list_hears_nothing_of_it(self):
        text = rendered("epd_measure", **MEASURE)
        assert "How each criterion's state is reached" not in text

    def test_the_measure_knows_the_state_logins_and_checks_them_first(self):
        measure = prompt("epd_measure")
        for login in ("qa-urgent@", "qa-multiroll@", "qa-catch@", "qa-loss@", "qa-settled@", "qa-orders@"):
            assert login in measure
        assert "drifted_logins" in measure and "the login has drifted" in measure
        assert "\"Build only\" never covers a state one of the logins above holds" in measure
        assert '"result": "met|unmet|vacuous|build_covered|waits_for_close"' in measure
        assert 'true only if every criterion is "met" or "build_covered"' in measure


class TestTheRule:
    """Covered by the build only when the plan says production cannot show it, and QA's walk is there."""

    def test_a_build_only_criterion_qa_met_is_covered(self, L):  # noqa: N803 (the fixture's name)
        ok, refused = L.build_covered_ok({"build_covered": [COVERED]}, REACH, [], WALKED)
        assert ok == [COVERED] and refused == []

    def test_a_criterion_production_can_show_is_not(self, L):  # noqa: N803
        claim = {**COVERED, "criterion": 1}
        ok, refused = L.build_covered_ok({"build_covered": [claim]}, REACH, [], WALKED)
        assert ok == [] and refused == [claim], "qa-urgent@ holds it on prod: measure it there"

    def test_nothing_is_covered_when_the_build_shipped_a_clause_unproven(self, L):  # noqa: N803
        ok, refused = L.build_covered_ok({"build_covered": [COVERED]}, REACH,
                                         ["2. A stalled broker shows the sentence"], WALKED)
        assert ok == [] and refused == [COVERED]

    def test_nothing_is_covered_without_qas_walk(self, L):  # noqa: N803
        ok, refused = L.build_covered_ok({"build_covered": [COVERED]}, REACH, [], [])
        assert ok == [] and refused == [COVERED]

    def test_a_claim_that_quotes_no_evidence_is_refused(self, L):  # noqa: N803
        claim = {**COVERED, "qa_evidence": " "}
        assert L.build_covered_ok({"build_covered": [claim]}, REACH, [], WALKED) == ([], [claim])

    def test_criteria_are_read_by_number_however_written(self, L):  # noqa: N803
        assert [L.criterion_no(x) for x in (2, "2", "criterion 2", "", None, True)] == [2, 2, 2, None, None, None]
        reach = [{"criterion": "criterion 2", "live": "Build only: the broker"}, {"criterion": 3, "live": "qa@"}]
        assert L.build_only(reach) == {2}

    def test_kept_stays_kept_when_the_covered_one_holds(self, L):  # noqa: N803
        out = {"verdict": "kept", "threshold_met": True, "vacuous_criteria": 0, "build_covered": [COVERED]}
        assert L.settle_verdict(out, REACH, [], WALKED) == "kept"
        assert "build_covered_refused" not in out

    def test_a_refused_claim_counts_vacuous_and_kept_becomes_iterate(self, L):  # noqa: N803
        claim = {**COVERED, "criterion": 1}
        out = {"verdict": "kept", "threshold_met": True, "vacuous_criteria": 0, "build_covered": [claim]}
        assert L.settle_verdict(out, REACH, [], WALKED) == "iterate"
        assert out["build_covered_refused"] == [claim] and out["build_covered"] == []
        assert out["vacuous_criteria"] == 1 and out["threshold_met"] is False
        assert L.settle_verdict(out, REACH, [], WALKED) == "iterate", "a second look changes nothing"
        assert out["vacuous_criteria"] == 1

    def test_the_ledger_line_says_what_was_covered_and_which_login_drifted(self, L):  # noqa: N803
        out = {"verdict": "iterate", "summary": "the urgent card was gone", "build_covered": [COVERED],
               "drifted_logins": [{"criterion": 1, "login": "qa-urgent@rollcall.test", "missing": "the card"}]}
        line = L.outcome_line(out, "iterate")
        assert "[1 covered by the build's QA]" in line
        assert "[login drifted: qa-urgent@rollcall.test]" in line


def write_tasks(L, bet_id: str, reach) -> None:  # noqa: N803 (the fixture's name)
    tasks = {"bet_id": bet_id, "tasks": [], "not_doing": []}
    if reach is not None:
        tasks["criteria_reach"] = reach
    (L.BETS_DIR / bet_id / "tasks.json").write_text(json.dumps(tasks))


class TestTheDriver:

    def test_the_build_gets_the_routes(self, L, monkeypatch):  # noqa: N803
        monkeypatch.setattr(L, "ensure_qa_password", lambda: "prodpw")
        propose(L, bets=("b001",), empty=())
        write_tasks(L, "b001", REACH)
        seen = {}
        monkeypatch.setattr(L, "run_workflow", lambda name, inputs, **kw: seen.update(inputs) or {"verdict": "approve"})
        L.stage_build(L.load_state("b001"))
        assert seen["criteria_reach"] == REACH

    def test_a_plan_without_the_list_adds_nothing(self, L, monkeypatch):  # noqa: N803
        monkeypatch.setattr(L, "ensure_qa_password", lambda: "prodpw")
        propose(L, bets=("b001",), empty=())
        write_tasks(L, "b001", None)
        seen = {}
        monkeypatch.setattr(L, "run_workflow", lambda name, inputs, **kw: seen.update(inputs) or {"verdict": "approve"})
        L.stage_build(L.load_state("b001"))
        assert "criteria_reach" not in seen

    def measured(self, L, monkeypatch, build: dict, reply: dict) -> tuple[dict, dict]:  # noqa: N803
        """Measure b001 on prod with this build.json and this reply; what it was given, and its state."""
        propose(L, bets=("b001",), empty=())
        bdir = L.BETS_DIR / "b001"
        write_tasks(L, "b001", REACH)
        (bdir / "build.json").write_text(json.dumps(build))
        st = L.load_state("b001")
        st["status"] = "shipped"
        st["stages"]["ship"] = {"prod_url": "https://prod.example.com", "prod_qa": True}
        L.save_state(st)
        seen = {}
        for name in ("wait_for_url", "preflight_login", "ledger_upsert", "release_task"):
            monkeypatch.setattr(L, name, lambda *a, **k: None)
        monkeypatch.setattr(L, "ensure_qa_password", lambda: "pw")

        def fake_run_workflow(name, inputs, **kw):
            seen.update(inputs)
            (bdir / "outcome.md").write_text("# outcome\n")
            return dict(reply)

        monkeypatch.setattr(L, "run_workflow", fake_run_workflow)
        L.stage_measure(L.load_state("b001"), keep=True)
        return seen, L.load_state("b001")

    def test_the_measure_gets_the_routes_and_qas_walk_and_keeps_a_covered_bet(self, L, monkeypatch):  # noqa: N803
        seen, st = self.measured(L, monkeypatch, {"verify_threshold_checks": WALKED, "accepted_unreachable": []},
                                 {"verdict": "kept", "threshold_met": True, "vacuous_criteria": 0,
                                  "build_covered": [COVERED], "summary": "all met; 2 covered by the build"})
        assert seen["criteria_reach"] == REACH
        assert seen["verify_threshold_checks"] == WALKED and seen["accepted_unreachable"] == []
        assert st["status"] == "kept"

    def test_a_bet_that_shipped_a_clause_unproven_is_not_kept_on_qas_word(self, L, monkeypatch):  # noqa: N803
        _, st = self.measured(L, monkeypatch,
                              {"verify_threshold_checks": WALKED, "accepted_unreachable": ["2. the stalled broker"]},
                              {"verdict": "kept", "threshold_met": True, "vacuous_criteria": 0,
                               "build_covered": [COVERED], "summary": "all met"})
        assert st["status"] == "iterate"
        assert st["stages"]["measure"]["build_covered_refused"] == [COVERED]
