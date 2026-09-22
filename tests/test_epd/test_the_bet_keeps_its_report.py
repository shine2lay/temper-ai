"""A shipped bet can still say which report it came from.

The measure stage re-walks the friction a bet was meant to remove, so it is handed the report
the bet came out of. It finds that report through `round` in bets/<id>/bet.json.

epd_ship rewrote that file from the four words it had:

    keys = ["title", "problem", "invariant", "threshold"]
    json.dump(dict(zip(keys, values)), open(path, "w"), indent=2)

so shipping a bet deleted `round` -- along with bet_id, rank, at and _run_id. The lookup then
fell through to the pre-rounds location, bets/<id>/report.md, which for any bet proposed in a
round does not exist. Nothing failed: the driver passed the missing path to the agent, which
was told to read it for "the friction that was there before the change".

Both halves are tested here: the lookup survives a bet.json with no round, and ship's own
record-keeping keeps what it was not given.
"""

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SHIP = REPO / "configs/epd/agents/epd_ship.yaml"


def _bet(tmp_path: Path, bet_json: dict, state_json: dict, round_id: str = "r001") -> Path:
    """A workspace with one bet and one round, laid out as the driver lays it out."""
    bdir = tmp_path / "bets" / "b004"
    bdir.mkdir(parents=True)
    (bdir / "bet.json").write_text(json.dumps(bet_json))
    (bdir / "state.json").write_text(json.dumps(state_json))
    rdir = tmp_path / "reports" / round_id
    rdir.mkdir(parents=True)
    (rdir / "report.md").write_text("# Report\n")
    return tmp_path


def _driver(workspace: Path):
    """The driver's path logic, pointed at a throwaway workspace."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "epd_loop_under_test", REPO / "configs/epd/bin/epd_loop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.BETS_DIR = workspace / "bets"
    mod.REPORTS_DIR = workspace / "reports"
    return mod


def test_a_bet_that_lost_its_round_still_finds_its_report(tmp_path):
    """The damage ship did is survivable: state.json remembers what bet.json forgot."""
    ws = _bet(
        tmp_path,
        bet_json={"title": "t", "problem": "p", "invariant": "i", "threshold": "x"},
        state_json={"bet_id": "b004", "round": "r001", "stages": {"bet": {"round": "r001"}}},
    )
    d = _driver(ws)
    assert d.round_of("b004") == "r001"
    found = d.report_path_for("b004")
    assert found == ws / "reports/r001/report.md"
    assert found.exists(), "the measure stage would have been given a path to nothing"


def test_the_round_in_the_bet_is_used_when_it_is_there(tmp_path):
    ws = _bet(tmp_path, bet_json={"round": "r001"}, state_json={})
    assert _driver(ws).report_path_for("b004") == ws / "reports/r001/report.md"


def test_a_bet_older_than_rounds_uses_the_report_beside_it(tmp_path):
    """Bets b001-b003 predate rounds and keep their own copy; that path must still win."""
    ws = _bet(tmp_path, bet_json={"title": "t"}, state_json={})
    beside = ws / "bets/b004/report.md"
    beside.write_text("# Older report\n")
    assert _driver(ws).report_path_for("b004") == beside


def _ship_bet_json_script() -> str:
    """The heredoc in epd_ship that maintains bet.json, lifted out of the template."""
    script = yaml.safe_load(SHIP.read_text())["agent"]["script_template"]
    blocks = re.findall(r"<<'PY'\n(.*?)\n\s*PY", script, re.S)
    assert blocks, "epd_ship no longer has an inline python block"
    body = [b for b in blocks if '"threshold"' in b and "keys" in b]
    assert len(body) == 1, f"expected one bet.json writer, found {len(body)}"
    # yaml already stripped the block scalar's own indent; dedent only what the heredoc adds,
    # so lines nested inside an `if` keep the indentation that makes them nested.
    return textwrap.dedent(body[0])


@pytest.mark.parametrize("existing,expect_round", [
    ({"bet_id": "b004", "round": "r001", "rank": 1}, "r001"),
    ({}, None),
])
def test_ship_updates_bet_json_and_does_not_flatten_it(tmp_path, existing, expect_round):
    """Ship refreshes the four words it knows and leaves every other field alone."""
    path = tmp_path / "bet.json"
    path.write_text(json.dumps(existing))
    run = subprocess.run(
        [sys.executable, "-c", _ship_bet_json_script(), str(path),
         "new title", "new problem", "new invariant", "new threshold"],
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr

    after = json.loads(path.read_text())
    assert after["title"] == "new title"
    assert after["threshold"] == "new threshold"
    assert after.get("round") == expect_round, (
        "ship dropped the bet's round; the measure stage finds the report through it"
    )
    if existing:
        assert after["rank"] == 1 and after["bet_id"] == "b004"


def test_ship_does_not_blank_a_field_it_has_nothing_for(tmp_path):
    """An empty value is this node lacking the field, not the bet losing it."""
    path = tmp_path / "bet.json"
    path.write_text(json.dumps({"title": "kept", "problem": "kept too", "round": "r001"}))
    run = subprocess.run(
        [sys.executable, "-c", _ship_bet_json_script(), str(path),
         "", "", "new invariant", ""],
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr

    after = json.loads(path.read_text())
    assert after["title"] == "kept" and after["problem"] == "kept too"
    assert after["invariant"] == "new invariant"
    assert after["round"] == "r001"
