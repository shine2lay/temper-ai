"""design_app_screen_v1 stage 1, intake (Design #206): the measured checks around the model step, the
sources collector, the stage's three script steps and the trial grader.

Each check is shown one good and one bad fixed model output. The words here are invented test text (the
repository is public); the real cases with the owner's words live in the lab
(~/design-lab/app-screen-workflow/known-cases/intake/).
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
sys.path.insert(0, str(BIN))

from app_screen import (  # noqa: E402
    contracts,
    intake,
    intake_check,
    intake_grade,
    intake_sources,
)
from app_screen.workspace import Workspace  # noqa: E402

SOURCES = {
    "product": "demo",
    "description": "Demo: a budgeting app that shows a household's spending week by week.",
    "items": [
        {"id": "S1", "kind": "comment", "text": "the chart is too busy, show less",
         "source": "test comment #1 on d_test01 v1", "context": 'Show&Tell "Demo" v1, on: "Spending $1,240 this week"'},
        {"id": "S2", "kind": "comment", "text": "move the add button to the top and make it bigger",
         "source": "test comment #2 on d_test01 v1", "context": 'Show&Tell "Demo" v1, on: "Add"'},
        {"id": "S3", "kind": "answer", "text": "only the weekly total",
         "source": "test answer in dialog dr-test (comment #1)", "context": 'Question asked: "What should the chart show?"'},
    ],
}
GOOD = {
    "requirements": [
        {"id": "R1", "item": "S1", "owner_words": "the chart is too busy, show less", "kind": "change",
         "means": "The spending chart shows less than it does now.", "maps_to": ["spending chart"]},
        {"id": "R2", "item": "S2", "owner_words": "move the add button to the top", "kind": "change",
         "means": "The Add button sits at the top of the screen.", "maps_to": ["Add button"]},
        {"id": "R3", "item": "S2", "owner_words": "make it bigger", "kind": "change",
         "means": "The Add button is bigger; how much is open.", "maps_to": ["Add button"], "open_questions": ["Q2"]},
        {"id": "R4", "item": "S3", "owner_words": "only the weekly total", "kind": "change",
         "means": "The chart shows only the weekly total (today $1,240), per R1 and Q1.", "maps_to": ["spending chart"]},
    ],
    "questions": [
        {"id": "Q1", "about": ["S1"], "question": "What should the chart show?", "why": "less is not a content list",
         "status": "answered", "answer": "only the weekly total", "answer_source": "S3"},
        {"id": "Q2", "about": ["S2"], "question": "How much bigger should Add be?", "why": "size changes the top bar",
         "choices": ["A little", "As big as the title"], "status": "open", "answer": None, "answer_source": None},
    ],
}


def _check(draft) -> dict:
    return intake_check.check_draft(SOURCES, draft)


def _problems(draft, check: str) -> list[dict]:
    return [p for p in _check(draft)["problems"] if p["check"] == check]


def _edit(fn):
    draft = copy.deepcopy(GOOD)
    fn(draft)
    return draft


# ---------------------------------------------------------------- the checks, one good and one bad each
def test_good_draft_passes_every_check():
    found = _check(GOOD)
    assert found["verdict"] == "ok" and found["problems"] == []
    assert {k: found["counts"][k] for k in ("items", "covered", "coverage", "requirements", "questions", "open",
                                             "answered")} == {"items": 3, "covered": 3, "coverage": 1.0,
                                                              "requirements": 4, "questions": 2, "open": 1,
                                                              "answered": 1}


def test_mapping_every_item_needs_a_requirement_or_question():
    def drop_s2(d):
        d["requirements"] = [r for r in d["requirements"] if r["item"] != "S2"]
        d["questions"] = [q for q in d["questions"] if q["id"] != "Q2"]
    bad = _problems(_edit(drop_s2), "coverage")
    assert len(bad) == 1 and bad[0]["problem"].startswith("S2 is in no requirement or question")
    # A question alone covers an item (a vague request may be all questions but its goal).
    def question_only(d):
        d["requirements"] = [r for r in d["requirements"] if r["item"] != "S2"]
    assert _problems(_edit(question_only), "coverage") == []
    assert _check(_edit(drop_s2))["counts"]["coverage"] == round(2 / 3, 3)


def test_substring_owner_words_and_answers_copied_exactly():
    assert _problems(GOOD, "not_verbatim") == []
    for words in ("the chart is to busy, show less", "The chart is too busy, show less", "chart too busy"):
        bad = _problems(_edit(lambda d, w=words: d["requirements"][0].update(owner_words=w)), "not_verbatim")
        assert len(bad) == 1 and bad[0]["where"] == "requirements/0/owner_words", words
    bad = _problems(_edit(lambda d: d["questions"][0].update(answer="just the weekly total")), "not_verbatim")
    assert len(bad) == 1 and bad[0]["where"] == "questions/0/answer"
    # Words from another item are not this item's words.
    bad = _problems(_edit(lambda d: d["requirements"][0].update(owner_words="make it bigger")), "not_verbatim")
    assert len(bad) == 1


def test_unsourced_no_requirement_without_a_source():
    assert _problems(GOOD, "unsourced") == []
    bad = _problems(_edit(lambda d: d["requirements"][1].update(item="S9")), "unsourced")
    assert len(bad) == 1 and "item 'S9' is not a source item" in bad[0]["problem"]
    bad = _problems(_edit(lambda d: d["questions"][1].update(about=["S7"])), "unsourced")
    assert len(bad) == 1 and bad[0]["where"] == "questions/1/about"
    bad = _problems(_edit(lambda d: d["questions"][0].update(answer_source="S8")), "unsourced")
    assert len(bad) == 1 and bad[0]["where"] == "questions/0/answer_source"
    # A requirement with no item at all breaks the draft's contract.
    bad = _problems(_edit(lambda d: d["requirements"][0].pop("item")), "schema")
    assert any("'item' is a required property" in p["problem"] for p in bad)


def test_invented_value_no_number_nobody_said():
    assert _problems(GOOD, "invented") == []  # $1,240 is in S1's context; R1/Q1 are ids, not numbers
    bad = _problems(_edit(lambda d: d["requirements"][2].update(means="The Add button is 48 px tall.")), "invented")
    assert len(bad) == 1 and "R3: states 48" in bad[0]["problem"]
    bad = _problems(_edit(lambda d: d["requirements"][1].update(maps_to=["top bar, 3 buttons"])), "invented")
    assert len(bad) == 1 and "states 3" in bad[0]["problem"]
    assert _problems(_edit(lambda d: d["requirements"][3].update(means="Only the weekly total, 1240.")), "invented") == []
    # Questions may offer numbers as choices: asking is not stating.
    assert _problems(_edit(lambda d: d["questions"][1].update(choices=["48 px", "64 px"])), "invented") == []


def test_ids_unique_and_open_questions_exist():
    assert _problems(GOOD, "ids") == []
    bad = _problems(_edit(lambda d: d["requirements"][1].update(id="R1")), "ids")
    assert len(bad) == 1 and "R1 is used more than once" in bad[0]["problem"]
    bad = _problems(_edit(lambda d: d["requirements"][2].update(open_questions=["Q9"])), "ids")
    assert len(bad) == 1 and "Q9 is not a question" in bad[0]["problem"]


def test_schema_fences_the_model_output():
    bad = _problems(_edit(lambda d: d["requirements"][0].update(kind="nice-to-have")), "schema")
    assert bad and "'nice-to-have' is not one of" in bad[0]["problem"]
    bad = _problems(_edit(lambda d: d["questions"][1].update(choices=["only one"])), "schema")
    assert bad and bad[0]["where"] == "questions/1/choices"
    bad = _problems(_edit(lambda d: d["questions"][0].pop("answer")), "schema")
    assert bad and "'answer' is a required property" in bad[0]["problem"]
    bad = _problems(_edit(lambda d: d.update(notes="extra")), "schema")
    assert bad and "Additional properties are not allowed" in bad[0]["problem"]
    assert _check("not a draft")["verdict"] == "retry"


def test_outputs_fill_source_lines_from_the_items():
    requirements, questions = intake_check.outputs(SOURCES, GOOD)
    assert contracts.check_json("requirements", requirements, "r") == []
    assert contracts.check_json("questions", questions, "q") == []
    assert requirements["items"][1]["source"] == "test comment #2 on d_test01 v1"
    assert questions["questions"][0]["answer_source"] == "test answer in dialog dr-test (comment #1)"
    assert "answer" not in questions["questions"][1]


# ---------------------------------------------------------------- the stage's steps on a workspace
def _load_cli():
    spec = importlib.util.spec_from_file_location("design_app_screen", BIN / "design_app_screen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLI = _load_cli()


def _ws(tmp_path) -> Path:
    path = tmp_path / "ws"
    path.mkdir(parents=True)
    return path


def _draft(ws: Path, draft) -> None:
    (ws / "01-request/draft.json").write_text(json.dumps(draft))


def test_steps_clean_draft_becomes_requirements_and_questions(tmp_path):
    ws = _ws(tmp_path)
    out = CLI.run_step("intake_collect", str(ws), "demo", "real", json.dumps(SOURCES))
    assert out["model"] == "yes" and out["items"] == 3
    assert json.loads((ws / "01-request/sources.json").read_text()) == SOURCES
    _draft(ws, GOOD)
    out = CLI.run_step("intake_check", str(ws), "demo", "real", "")
    assert out["verdict"] == "ok" and out["problems"] == 0
    assert not (ws / "01-request/draft-first.json").exists()
    out = CLI.run_step("intake", str(ws), "demo", "real", "")
    assert out["valid"] and out["revised"] is False and out["coverage"] == 1.0
    assert contracts.validate("intake", Workspace(ws))
    assert json.loads((ws / "01-request/check-final.json").read_text())["verdict"] == "ok"


def test_steps_bad_draft_retries_then_fails_loud(tmp_path):
    ws = _ws(tmp_path)
    CLI.run_step("intake_collect", str(ws), "demo", "real", json.dumps(SOURCES))
    out = CLI.run_step("intake_check", str(ws), "demo", "real", "")
    assert out["verdict"] == "retry"  # no draft yet
    bad = _edit(lambda d: d["requirements"][0].update(owner_words="chart too busy"))
    _draft(ws, bad)
    out = CLI.run_step("intake_check", str(ws), "demo", "real", "")
    assert out["verdict"] == "retry" and out["not_verbatim"] == 1
    assert (ws / "01-request/draft-first.json").is_file()
    with pytest.raises(intake.IntakeError, match="the final draft breaks 1 check"):
        CLI.run_step("intake", str(ws), "demo", "real", "")
    assert not (ws / "01-request/requirements.json").exists()
    assert Workspace(ws).run()["stages"]["intake"]["status"] == "failed"
    _draft(ws, GOOD)  # the revision fixed it
    assert CLI.run_step("intake", str(ws), "demo", "real", "")["revised"] is True


def test_collect_takes_a_plain_request_and_refuses_bad_input(tmp_path):
    ws = _ws(tmp_path)
    raw = json.dumps({"request": "make the history page faster to read", "source": "test request",
                      "description": "Demo: a budgeting app."})
    CLI.run_step("intake_collect", str(ws), "demo", "real", raw)
    doc = json.loads((ws / "01-request/sources.json").read_text())
    assert doc["items"] == [{"id": "S1", "kind": "request", "text": "make the history page faster to read",
                             "source": "test request"}]
    with pytest.raises(intake_sources.SourcesError, match="sources are for 'demo', the run is for 'other'"):
        intake_sources.from_input(json.dumps(SOURCES), "other")
    with pytest.raises(intake_sources.SourcesError, match="unknown fields colour"):
        intake_sources.from_input(json.dumps({"request": "x", "source": "y", "colour": "red"}), "demo")
    with pytest.raises(intake_sources.SourcesError, match="needs description"):
        intake_sources.from_input(json.dumps({"request": "x", "source": "y"}), "demo")
    with pytest.raises(intake_sources.SourcesError, match="not JSON"):
        intake_sources.from_input("make it nicer", "demo")
    with pytest.raises(intake.IntakeError, match="no sources"):
        CLI.run_step("intake_collect", str(_ws(tmp_path / "empty")), "demo", "real", "")
    twice = copy.deepcopy(SOURCES)
    twice["items"][1]["id"] = "S1"
    with pytest.raises(intake_sources.SourcesError, match="duplicate ids S1"):
        intake_sources.load(twice)


def test_collect_showtell_comments_and_dialog_answers(tmp_path):
    doc = {"title": "Demo draft", "comments": [
        {"comment_id": "c_b", "number": 2, "version": 2, "state": "answered", "body": "show less here",
         "anchor": {"element": {"text": "Spending", "selector": "#s"}}},
        {"comment_id": "c_a", "number": 1, "version": 1, "state": "resolved", "body": "the page is blank",
         "anchor": {"element": {"text": "", "selector": "#app"}}},
        {"comment_id": "c_c", "number": 3, "version": 2, "state": "draft", "body": "not sent yet", "anchor": {}}]}
    got = intake_sources.showtell_items("d_test01", fetch=lambda url: doc)
    assert [i["text"] for i in got] == ["the page is blank", "show less here"]
    assert got[0]["context"] == 'Show&Tell "Demo draft" v1, on: "element #app"'
    assert got[1]["source"] == "owner's Show&Tell comment #2 on d_test01 v2"
    assert [i["text"] for i in intake_sources.showtell_items("d_test01", [2], fetch=lambda url: doc)] == ["show less here"]
    with pytest.raises(intake_sources.SourcesError, match="no sent comments on versions"):
        intake_sources.showtell_items("d_test01", [5], fetch=lambda url: doc)
    records = tmp_path / "records.jsonl"
    rows = [{"id": "dr-other", "from": "owner", "questions": []},
            {"id": "dr-test1", "from": "owner", "at": 1793849394970, "questions": [
                {"id": "q1", "header": "comment #1", "question": "What instead?", "picked": [], "typed": " just totals "},
                {"id": "q2", "header": "comment #2", "question": "Which side?", "picked": ["Left"], "typed": ""},
                {"id": "q3", "header": "comment #3", "question": "Skip?", "picked": [], "typed": ""}]},
            {"id": "dr-agent", "from": "design", "questions": [{"id": "q", "typed": "x"}]}]
    records.write_text("".join(json.dumps(r) + "\n" for r in rows))
    got = intake_sources.record_items("dr-test1", records)
    assert [(i["text"], i["ref"]["picked"]) for i in got] == [(" just totals ", False), ("Left", True)]
    assert got[0]["source"].startswith("owner's answer in dialog dr-test1 (comment #1), 2026-")
    assert got[0]["context"] == 'Question asked: "What instead?"'
    assert len(intake_sources.record_items("dr-test1", records, ["q2"])) == 1
    with pytest.raises(intake_sources.SourcesError, match="is from 'design', not the owner"):
        intake_sources.record_items("dr-agent", records)
    with pytest.raises(intake_sources.SourcesError, match="dr-none not in"):
        intake_sources.record_items("dr-none", records)
    built = intake_sources.build("demo", "Demo app.", got + [intake_sources.request_item("x", "test")])
    assert [i["id"] for i in built["items"]] == ["S1", "S2", "S3"]


def test_fixture_mode_collect_and_check_pass_through(tmp_path):
    ws = _ws(tmp_path)
    Workspace(ws).start("demo", "fixture")
    assert intake.collect(Workspace(ws), "ignored") == {"model": "no", "source": "known case"}
    assert intake.check(Workspace(ws), "")["verdict"] == "ok"


# ---------------------------------------------------------------- the trial grader
def _graded_run(tmp_path, draft) -> Path:
    case = tmp_path / "case"
    case.mkdir(parents=True)
    (case / "sources.json").write_text(json.dumps(SOURCES))
    (case / "expected.json").write_text(json.dumps({
        "case": "demo", "key": [{"id": "K1", "what": "Add at the top", "items": ["S2"], "must": [["add"], ["top"]]}],
        "questions_needed": [{"id": "N1", "what": "how big", "any": ["how much bigger"], "about": ["S2"]}],
        "conflicts": [{"id": "X1", "items": ["S1", "S3"], "any": ["chart"]}],
        "specifics": {"forbidden_terms": ["colour"]}}))
    ws = tmp_path / "run"
    ws.mkdir()
    CLI.run_step("intake_collect", str(ws), "demo", "real", json.dumps(SOURCES))
    _draft(ws, draft)
    CLI.run_step("intake_check", str(ws), "demo", "real", "")
    try:
        CLI.run_step("intake", str(ws), "demo", "real", "")
    except intake.IntakeError:
        pass
    return case, ws


def test_grader_counts_key_questions_conflicts_and_specifics(tmp_path):
    def with_conflict(d):
        d["questions"].append({"id": "Q3", "about": ["S1", "S3"], "question": "Your chart comments disagree: which?",
                               "why": "they conflict", "choices": ["S1", "S3"], "status": "open"})
        for r in d["requirements"]:
            if r["item"] in ("S1", "S3"):
                r["open_questions"] = ["Q3"]
    case, ws = _graded_run(tmp_path / "good", _edit(with_conflict))
    graded = intake_grade.grade(case, ws)
    assert graded["pass"], graded["misses"]
    assert graded["measures"]["key"] == "1/1" and graded["measures"]["conflicts_asked"] == "1/1"

    def careless(d):
        d["requirements"][1]["means"] = "The Add button moves; colour stays."
        d["requirements"][2]["owner_words"] = "make it larger"
    case, ws = _graded_run(tmp_path / "bad", _edit(careless))
    graded = intake_grade.grade(case, ws)
    assert not graded["pass"]
    m = graded["measures"]
    assert (m["final_ok"], m["not_verbatim"], m["key"], m["conflicts_asked"], m["specifics"]) == (False, 1, "0/1", "0/1", 1)
    assert m["silent_picks"] == 2 and m["revised"] is True
    assert any(x.startswith("key K1 not met") for x in graded["misses"])


# ---------------------------------------------------------------- the workflow files
def _yaml(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text())


def test_trial_workflow_runs_the_whole_workflows_intake_nodes_unchanged():
    whole = {n["name"]: n for n in _yaml("configs/design/workflows/design_app_screen_v1.yaml")["workflow"]["nodes"]}
    alone = _yaml("configs/design/workflows/design_app_screen_v1_intake.yaml")["workflow"]["nodes"]
    assert [n["name"] for n in alone] == ["intake_collect", "intake_read", "intake_check", "intake_revise", "intake"]
    for node in alone:
        assert node == whole[node["name"]], node["name"]
    assert whole["existing"]["depends_on"] == ["intake"]


def test_intake_agent_is_fenced():
    agent = _yaml("configs/design/agents/design_app_screen_intake_v1.yaml")["agent"]
    assert agent["type"] == "llm" and "tools" not in agent
    prompt = agent["system_prompt"]
    for must in ("01-request/sources.json", "01-request/draft.json", "character for character", "Never answer it",
                 "never pick a side", "2-4 choices"):
        assert must in prompt, must
    assert "check.json" in agent["task_template"]
