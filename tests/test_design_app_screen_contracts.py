"""design_app_screen_v1 (Design #198, W0): stage contracts, known case, gates and the step dispatcher.

Each contract accepts the RollCall known case's real output (rollcall-20261104, frozen in
~/design-lab/app-screen-workflow/known-cases/) and rejects a broken copy of it, each for its named reason.
The repo keeps the case's JSON and Markdown outputs in tests/design_app_screen_case/; the pictures, pages
and screen scripts those name are stood in by small placeholder files (the contracts check only that they
exist and are PNG/HTML). On spark the full frozen case is also verified and compared with the repo copy.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
sys.path.insert(0, str(BIN))

from app_screen import contracts, gates, known_case  # noqa: E402
from app_screen.fixture_stage import NotBuiltError  # noqa: E402
from app_screen.workspace import (  # noqa: E402
    FOLDERS,
    STAGES,
    STEPS,
    Workspace,
    WorkspaceError,
)

CASE_NAME = "rollcall-20261104"
REPO_CASE = ROOT / "tests/design_app_screen_case" / CASE_NAME
LAB_CASE = Path.home() / "design-lab/app-screen-workflow/known-cases" / CASE_NAME
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
HTML = "<!doctype html><title>placeholder for the known case's page</title>\n"
# The workflow's steps in run order (configs/design/workflows/design_app_screen_v1.yaml).
ORDER = ["intake_collect", "intake_check", "intake", "existing", "ground", "directions", "gate_direction", "build", "checks", "review", "show",
         "gate_final", "gate_final_next", "handoff"]
DESIGN_ANSWER = {"direction": {"choice": "a", "decided_by": "design", "source": "fixture run",
                               "reason": "the known case's owner picked a"},
                 "final": {"choice": "approve", "decided_by": "design", "source": "fixture run",
                           "reason": "the known case's owner approved"}}


def _load_cli():
    spec = importlib.util.spec_from_file_location("design_app_screen", BIN / "design_app_screen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLI = _load_cli()


def _read(path: Path):
    return json.loads(path.read_text())


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n")


def make_case(dest: Path) -> Path:
    """The known case as a folder: the repo's JSON/Markdown copies plus placeholders for the files they name."""
    case = dest / CASE_NAME
    shutil.copytree(REPO_CASE, case)
    for s in _read(case / "02-existing/audit.json")["screens"]:
        (case / "02-existing" / s["capture"]).parent.mkdir(parents=True, exist_ok=True)
        (case / "02-existing" / s["capture"]).write_bytes(PNG)
    for d in _read(case / "04-directions/directions.json")["directions"]:
        (case / "04-directions" / d["page"]).write_text(HTML)
    build = _read(case / "05-build/build.json")
    (case / "05-build" / build["page"]).write_text(HTML)
    (case / "05-build/shell").mkdir(parents=True, exist_ok=True)
    (case / "05-build/shell/page.html").write_text(HTML)
    for s in build["screens"]:
        (case / "05-build" / s["file"]).parent.mkdir(parents=True, exist_ok=True)
        (case / "05-build" / s["file"]).write_text("// placeholder for the known case's screen script\n")
    return case


@pytest.fixture
def case(tmp_path) -> Path:
    c = make_case(tmp_path / "cases")
    known_case.freeze(c, "rollcall", "test copy of the RollCall known case")
    return c


@pytest.fixture
def filled(tmp_path, case) -> Workspace:
    """A workspace holding every stage's known output at round 1, as after a whole fixture run."""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    known_case.pack(case, ws_dir)
    ws = Workspace(ws_dir)
    ws.next_round()
    for stage in STAGES:
        if stage == "checks":
            shutil.copytree(case / FOLDERS["checks"] / "round-1", ws.round_folder(), dirs_exist_ok=True)
        else:
            shutil.copytree(case / FOLDERS[stage], ws.folder(stage), dirs_exist_ok=True)
    shutil.copyfile(case / "gates/gate_direction.json", ws.folder("directions") / "gate_direction.json")
    shutil.copyfile(case / "gates/gate_final.json", ws.folder("show") / "gate_final.json")
    return ws


# ---------------------------------------------------------------- the known case passes, end to end
def test_fixture_run_passes_every_contract(tmp_path, case, monkeypatch):
    ws_dir = tmp_path / "run"
    ws_dir.mkdir()
    assert CLI.host("pack", CLI.argparse.Namespace(case=str(case), workspace=str(ws_dir), product=None, source=None))
    for step in ORDER:
        raw = json.dumps(DESIGN_ANSWER[step.split("_")[1]]) if step in ("gate_direction", "gate_final") else ""
        out = CLI.run_step(step, str(ws_dir), None, "fixture", raw)
        assert out["valid"] and out["step"] == step, out
        if step == "gate_direction":
            assert out["choice"] == out["known_case_choice"] == "a"
        if step == "review":
            assert out["verdict"] == "done" and out["round"] == 1
        if step == "gate_final_next":
            assert out["verdict"] == "approve"
    run = Workspace(ws_dir).run()
    assert {s: v["status"] for s, v in run["stages"].items()} == {s: "done" for s in ORDER}
    assert _read(ws_dir / "04-directions/gate_direction.json")["taste"] == "not-taste"


def test_every_step_has_a_contract_and_the_known_case_meets_it(filled):
    assert set(contracts.FILES) == set(STEPS)
    for step in ORDER:
        # gate_final_next leaves nothing; intake's collect and draft-check files are absent in a fixture run.
        assert contracts.validate(step, filled) or step in ("gate_final_next", "intake_collect", "intake_check")


def test_known_case_gate_answers_are_the_owners(case):
    for gate in ("direction", "final"):
        record = _read(case / f"gates/gate_{gate}.json")
        assert contracts.check_json("gate", record, gate) == []
        assert record["decided_by"] == "owner" and record["owner_words"] and record["source"]


# ---------------------------------------------------------------- broken copies fail, each for its reason
def _del(*path):
    def f(data):
        node = data
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]
    return f


def _set(value, *path):
    def f(data):
        node = data
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
    return f


def _must_finding(data):
    data["findings"].append({"id": "F9", "element": "Send roll", "location": "roll ticket", "evidence": "check",
                             "severity": 3, "priority": "must"})


BROKEN = [
    ("intake", "01-request/requirements.json", _del("items", 0, "owner_words"),
     "01-request/requirements.json: items/0: 'owner_words' is a required property"),
    ("intake", "01-request/requirements.json", _set("R1", "items", 0, "maps_to"),
     "01-request/requirements.json: items/0/maps_to: 'R1' is not of type 'array'"),
    ("intake", "01-request/questions.json", _del("questions", 0, "answer_source"),
     "01-request/questions.json: questions/0: 'answer_source' is a required property"),
    ("existing", "02-existing/audit.json", _set("390", "screens", 0, "width"),
     "02-existing/audit.json: screens/0/width: '390' is not of type 'integer'"),
    ("existing", "02-existing/audit.json", _set("captures/nowhere.png", "screens", 0, "capture"),
     "02-existing/audit.json: screens/0/capture: captures/nowhere.png is not in 02-existing/"),
    ("existing", "02-existing/journeys.json", _del("journeys", 0, "problems", 0, "evidence"),
     "02-existing/journeys.json: journeys/0/problems/0: 'evidence' is a required property"),
    ("ground", "03-ground/inventory.json", _del("design_files"),
     "03-ground/inventory.json: (top): 'design_files' is a required property"),
    ("ground", "03-ground/inventory.json", _set(390, "screens", 0, "widths"),
     "03-ground/inventory.json: screens/0/widths: 390 is not of type 'array'"),
    ("directions", "04-directions/directions.json", _del("directions", 0, "page"),
     "04-directions/directions.json: directions/0: 'page' is a required property"),
    ("directions", "04-directions/a/checks.json", _set(True, "checks", 0, "result"),
     "04-directions/a/checks.json: checks/0/result: True is not one of ['pass', 'fail', 'skipped']"),
    ("gate_direction", "04-directions/gate_direction.json", _set("z", "choice"),
     "04-directions/gate_direction.json: choice: 'z' is not a direction (a, b)"),
    ("gate_direction", "04-directions/gate_direction.json", _del("source"),
     "04-directions/gate_direction.json: (top): 'source' is a required property"),
    ("build", "05-build/build.json", _del("screens"), "05-build/build.json: (top): 'screens' is a required property"),
    ("build", "05-build/build.json", _set("1", "round"), "05-build/build.json: round: '1' is not of type 'integer'"),
    ("build", "05-build/build.json", _set("screens/gone.js", "screens", 0, "file"),
     "05-build/build.json: screens/0/file: screens/gone.js is not in 05-build/"),
    ("checks", "06-checks/round-1/checks.json", _del("checks", 0, "evidence"),
     "06-checks/round-1/checks.json: checks/0: 'evidence' is a required property"),
    ("checks", "06-checks/round-1/checks.json", _set("one", "round"),
     "06-checks/round-1/checks.json: round: 'one' is not of type 'integer'"),
    ("review", "06-checks/round-1/review.json", _must_finding,
     "06-checks/round-1/review.json: verdict: is 'done' but must be 'revise' (a Must finding is open)"),
    ("review", "06-checks/round-1/review.json", _set(5, "findings", 0, "severity"),
     "06-checks/round-1/review.json: findings/0/severity: 5 is greater than the maximum of 4"),
    ("show", "07-show/showtell.json", _set("3", "version"), "07-show/showtell.json: version: '3' is not of type 'integer'"),
    ("show", "07-show/comments.json", _del("comments", 0, "body"),
     "07-show/comments.json: comments/0: 'body' is a required property"),
    ("gate_final", "07-show/gate_final.json", _set("a", "choice"),
     "07-show/gate_final.json: choice: 'a' is not one of ['approve', 'changes']"),
    ("gate_final", "07-show/gate_final.json", _set("maybe", "decided_by"),
     "07-show/gate_final.json: decided_by: 'maybe' is not one of ['owner', 'design']"),
    ("handoff", "08-handoff/design-file.json", _set("no", "editable"),
     "08-handoff/design-file.json: editable: 'no' is not of type 'boolean'"),
    ("handoff", "08-handoff/followup.json", _del("items", 0, "owner_role"),
     "08-handoff/followup.json: items/0: 'owner_role' is a required property"),
]


@pytest.mark.parametrize("step,rel,breaks,reason", BROKEN, ids=[f"{b[0]}-{i}" for i, b in enumerate(BROKEN)])
def test_broken_copy_fails_for_its_reason(filled, step, rel, breaks, reason):
    path = filled.path / rel
    good = _read(path)
    contracts.validate(step, filled)  # the real output passes
    bad = copy.deepcopy(good)
    breaks(bad)
    _write(path, bad)
    with pytest.raises(contracts.ContractError) as err:
        contracts.validate(step, filled)
    assert reason in str(err.value), str(err.value)
    assert str(err.value).startswith(f"{step}: 1 problem(s): ")


def test_missing_and_unreadable_files_fail(filled):
    (filled.path / "08-handoff/followup.json").unlink()
    with pytest.raises(contracts.ContractError, match=r"08-handoff/followup.json: \(file\): needs at least 1, found 0"):
        contracts.validate("handoff", filled)
    (filled.path / "07-show/showtell.json").write_text("{not json")
    with pytest.raises(contracts.ContractError, match=r"07-show/showtell.json: \(file\): not readable JSON"):
        contracts.validate("show", filled)
    capture = sorted((filled.path / "02-existing/captures").glob("*.png"))[0]
    capture.write_bytes(b"GIF89a")
    with pytest.raises(contracts.ContractError, match=rf"02-existing/captures/{capture.name}: \(file\): not a PNG"):
        contracts.validate("existing", filled)
    with pytest.raises(contracts.ContractError, match="no contract for step 'polish'"):
        contracts.validate("polish", filled)


# ---------------------------------------------------------------- gates
def test_gate_needs_a_real_answer(filled):
    with pytest.raises(gates.GateError, match="no answer given"):
        gates.answer(filled, "direction", "")
    with pytest.raises(gates.GateError, match="not JSON"):
        gates.answer(filled, "direction", "pick a")
    mixed = {**DESIGN_ANSWER["direction"], "owner_words": "I like A"}
    with pytest.raises(gates.GateError, match="owner_words are for decided_by owner only"):
        gates.answer(filled, "direction", json.dumps(mixed))
    silent = {**DESIGN_ANSWER["direction"], "decided_by": "owner"}
    with pytest.raises(gates.GateError, match="owner_words"):
        gates.answer(filled, "direction", json.dumps(silent))
    with pytest.raises(gates.GateError, match="comments: changes needs the comment numbers"):
        gates.answer(filled, "final", json.dumps({**DESIGN_ANSWER["final"], "choice": "changes"}))
    with pytest.raises(gates.GateError, match="unknown answer fields mood"):
        gates.answer(filled, "final", json.dumps({**DESIGN_ANSWER["final"], "mood": "good"}))


def test_final_changes_loops_back_with_its_comments(filled):
    out = gates.answer(filled, "final", json.dumps({**DESIGN_ANSWER["final"], "choice": "changes", "comments": [2, 5]}))
    assert out["verdict"] == "changes"
    assert gates.final_next(filled) == {"verdict": "changes", "comments": [2, 5]}


# ---------------------------------------------------------------- known case freeze
def test_freeze_catches_changed_added_and_refrozen(case):
    assert known_case.verify(case)["case"] == CASE_NAME
    with pytest.raises(known_case.KnownCaseError, match="a frozen case is never re-frozen"):
        known_case.freeze(case, "rollcall", "again")
    (case / "07-show/extra.json").write_text("{}")
    with pytest.raises(known_case.KnownCaseError, match="07-show/extra.json: not in FREEZE.json"):
        known_case.verify(case)
    (case / "07-show/extra.json").unlink()
    (case / "01-request/questions.json").write_text("{}")
    with pytest.raises(known_case.KnownCaseError, match="01-request/questions.json: changed since the freeze"):
        known_case.verify(case)


@pytest.mark.skipif(not (LAB_CASE / "FREEZE.json").is_file(), reason="the frozen known case lives on spark")
def test_lab_case_is_frozen_and_matches_the_repo_copy():
    record = known_case.verify(LAB_CASE)
    repo = sorted(p.relative_to(REPO_CASE).as_posix() for p in REPO_CASE.rglob("*") if p.is_file())
    assert repo and set(repo) <= set(record["files"])
    for rel in repo:
        assert (REPO_CASE / rel).read_bytes() == (LAB_CASE / rel).read_bytes(), rel


# ---------------------------------------------------------------- dispatcher
def test_dispatcher_refuses_unknown_step_and_missing_workspace(tmp_path, capsys):
    with pytest.raises(SystemExit) as err:
        CLI.main(["polish", "--workspace", str(tmp_path)])
    assert err.value.code == 2 and "invalid choice: 'polish'" in capsys.readouterr().err
    with pytest.raises(SystemExit, match=f"intake: workspace {tmp_path / 'nowhere'} does not exist or is not a folder"):
        CLI.main(["intake", "--workspace", str(tmp_path / "nowhere"), "--product", "rollcall", "--mode", "fixture"])
    with pytest.raises(SystemExit, match="intake needs --workspace W"):
        CLI.main(["intake"])
    with pytest.raises(SystemExit, match=r"existing: .*run.json is missing"):
        CLI.main(["existing", "--workspace", str(tmp_path)])


def test_real_mode_stage_fails_loud_until_built(tmp_path):
    with pytest.raises(NotBuiltError, match="directions: the real stage is not built yet"):
        CLI.run_step("directions", str(tmp_path), "rollcall", "real", "")
    assert Workspace(tmp_path).run()["stages"]["directions"]["status"] == "failed"
    with pytest.raises(WorkspaceError, match="run.json says mode real, the step was called with fixture"):
        CLI.run_step("ground", str(tmp_path), None, "fixture", "")
