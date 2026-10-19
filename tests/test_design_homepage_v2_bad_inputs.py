"""Bad inputs to two script stages of design_homepage_v2 (queue #87, W3; BAR.md C "bad inputs refused").

The stage map (#77, ~/design-lab/homepage-workflow/STAGE-MAP.md) found no test that feeds the references
stage or the pairings stage a bad input. These tests do, without a browser, a model or Temper.

What "refused" means here (Design's bar for script stages): the stage stops with an error that names the
problem before it does any work (no capture, no receipt, no output file), OR it drops the bad part and says
so in its output. Dropping a bad part silently is not a refusal: the next stage would trust a list that is
quietly shorter than what was recorded.

Where today's code accepts a bad input, the test is xfail(strict=True) with the reason, so it starts failing
(XPASS) the day the code is fixed and the mark has to come off. Fixes belong to the wiring task W4e, not here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v2 = _load("design_homepage_v2")


@pytest.fixture(autouse=True)
def pairing_log(tmp_path, monkeypatch):
    """Each test logs pairings to its own file, never to the shared log beside real run workspaces."""
    log = tmp_path / "pairing-log" / "type-pairings.jsonl"
    monkeypatch.setenv("DESIGN_PAIRING_LOG", str(log))
    return log


@pytest.fixture
def no_browser(monkeypatch):
    """Fails the test if the stage reaches the browser: a bad input must be refused before any capture."""
    calls = []

    def browser_jobs(*args, **kwargs):
        calls.append(args)
        raise AssertionError("the references stage reached the browser with a bad input")

    monkeypatch.setattr(v2, "browser_jobs", browser_jobs)
    return calls


def real_refs(n: int = 8) -> list[dict]:
    return [{"name": f"Studio {i}", "url": f"https://studio-{i}.example.com/", "why": f"how it shows class times ({i})"}
            for i in range(1, n + 1)]


def fixture_refs() -> list[dict]:
    return [{"name": f"Fixture {k}", "fixture": page, "why": "stand-in reference"}
            for k, page in v2.FIXTURE_CONCEPTS.items()]


def with_ref(i: int, **change) -> list[dict]:
    refs = real_refs()
    refs[i] = {k: v for k, v in {**refs[i], **change}.items() if v is not ...}
    return refs


# --------------------------------------------------------------------------- references_contract

def test_good_references_pass_the_contract():
    """The control: well-formed lists go through unchanged, at both ends of each count range."""
    for n in (8, 12):
        assert v2.references_contract(real_refs(n), fixture=False) == real_refs(n)
    assert v2.references_contract(fixture_refs()[:2], fixture=True) == fixture_refs()[:2]
    assert v2.references_contract(fixture_refs(), fixture=True) == fixture_refs()


BAD_REAL = {
    "missing url": (with_ref(3, url=...), "https URLs"),
    "blank url": (with_ref(3, url=""), "https URLs"),
    "http url": (with_ref(3, url="http://studio-4.example.com/"), "https URLs"),
    "ftp url": (with_ref(3, url="ftp://studio-4.example.com/"), "https URLs"),
    "javascript url": (with_ref(3, url="javascript:alert(1)"), "https URLs"),
    "relative url": (with_ref(3, url="/studio-4"), "https URLs"),
    "https url without a host": (with_ref(3, url="https:///path"), "https URLs"),
    "no why": (with_ref(5, why=...), "name and why"),
    "blank why": (with_ref(5, why="   "), "name and why"),
    "no name": (with_ref(5, name=...), "name and why"),
    "too few (7)": (real_refs(7), "give 8-12 references"),
    "none": ([], "give 8-12 references"),
    "too many (13)": (real_refs(13), "give 8-12 references"),
    "not a list": ({"name": "Studio", "url": "https://studio.example.com/", "why": "x"}, "JSON list"),
    "an entry that is not an object": (real_refs(7) + ["https://studio-9.example.com/"], "name and why"),
    "duplicate url": (real_refs(7) + [real_refs(1)[0]], "duplicate reference"),
}


@pytest.mark.parametrize("case", list(BAD_REAL))
def test_bad_real_references_are_refused(case):
    value, message = BAD_REAL[case]
    with pytest.raises(ValueError, match=message):
        v2.references_contract(value, fixture=False)


BAD_FIXTURE = {
    "too few (1)": (fixture_refs()[:1], "give 2-4 references"),
    "too many (5)": (fixture_refs() + [{"name": "Extra", "fixture": "atlas.html", "why": "x"}] * 2, "give 2-4 references"),
    "unknown fixture page": ([*fixture_refs()[:1], {"name": "Elsewhere", "fixture": "../../etc/passwd", "why": "x"}],
                             "fixture page"),
    "no why": ([*fixture_refs()[:1], {"name": "Fixture B", "fixture": "pulse.html"}], "name and why"),
    "duplicate fixture page": ([*fixture_refs()[:1], fixture_refs()[0]], "duplicate reference"),
}


@pytest.mark.parametrize("case", list(BAD_FIXTURE))
def test_bad_fixture_references_are_refused(case):
    value, message = BAD_FIXTURE[case]
    with pytest.raises(ValueError, match=message):
        v2.references_contract(value, fixture=True)


# --------------------------------------------------------------------------- the references stage (Job.references)

def pilot_job(tmp_path):
    job = v2.Job(str(tmp_path), fixture=False, pilot=True)
    job.brief(json.dumps({**v2.FIXTURE_BRIEF, "fixture": False}))  # fictional, but not the fixture
    return job


STAGE_BAD = {
    "missing url": (with_ref(0, url=...), ValueError, "https URLs"),
    "http url": (with_ref(0, url="http://studio-1.example.com/"), ValueError, "https URLs"),
    "no why": (with_ref(0, why=...), ValueError, "name and why"),
    "too few (7)": (real_refs(7), ValueError, "give 8-12 references"),
}


@pytest.mark.parametrize("case", list(STAGE_BAD))
def test_references_stage_refuses_before_any_capture(tmp_path, no_browser, case):
    """The stage itself (as the workflow calls it) stops on the bad list: no browser, no receipt, no files."""
    job = pilot_job(tmp_path)
    value, error, message = STAGE_BAD[case]
    with pytest.raises(error, match=message):
        job.references(json.dumps(value))
    assert no_browser == []
    assert not (job.packet / "references").exists()
    assert "references" not in v2.Job(str(tmp_path), fixture=False, pilot=True).state["stages"]  # no receipt saved


def test_references_stage_refuses_text_that_is_not_json(tmp_path, no_browser):
    job = pilot_job(tmp_path)
    with pytest.raises(ValueError):
        job.references("Studio 1 https://studio-1.example.com/ because it shows class times")
    assert no_browser == [] and not (job.packet / "references").exists()


def test_references_stage_never_treats_an_empty_answer_as_no_references_on_a_real_run(tmp_path, no_browser):
    """Only the fixture fills in stand-in references; a real run with nothing given stops."""
    job = pilot_job(tmp_path)
    with pytest.raises(ValueError, match="give 8-12 references"):
        job.references("")
    assert no_browser == []


# --------------------------------------------------------------------------- the pairings stage (Job.pairings)

SEED = json.loads((ROOT / "configs/design/knowledge/type-pairings.json").read_text())
GOOD_ROW = {"display": "Gloock", "text": "Hanken Grotesk", "kind": "offered", "concept": "A", "workspace": "run-other"}


def fixture_job(tmp_path):
    job = v2.Job(str(tmp_path / "run-self"), fixture=True)
    job.brief("")
    return job


def test_pairings_stage_reads_a_good_log(tmp_path, pairing_log):
    """The control: one good row from another run is listed with the seed."""
    pairing_log.parent.mkdir(parents=True)
    pairing_log.write_text(json.dumps(GOOD_ROW) + "\n")
    out = fixture_job(tmp_path).pairings()
    assert out["status"] == "completed"
    assert out["used_pairings"] == len({v2.pairing_key(p["display"], p["text"]) for p in SEED["pairings"]}) + 1
    assert "Gloock + Hanken Grotesk (offered in run run-other)" in (tmp_path / "run-self/homepage/PAIRINGS.md").read_text()


UNREADABLE_RECORDS = {
    "not json": "not json at all",
    "cut off mid-write": json.dumps(GOOD_ROW | {"display": "Fraunces", "text": "Karla"})[:40],
    "json but not an object": json.dumps(["Fraunces", "Karla"]),
}

SILENT_SKIP = ("recorded_pairings() drops a log line it cannot read (json.loads ValueError -> continue; non-object "
               "-> skipped) and Job.pairings() neither stops nor says so: PAIRINGS.md and the stage's output "
               "list one pairing fewer than the log holds, so a reused pairing can pass the concept check. "
               "Fix in W4e: stop with an error naming the log line, or count and name skipped lines in "
               "PAIRINGS.md and the stage output. tests/test_design_homepage_v2.py::"
               "test_runs_log_their_pairings_and_a_run_never_blocks_its_own asserts today's silent skip and "
               "changes with that fix.")


@pytest.mark.xfail(strict=True, reason=SILENT_SKIP)
@pytest.mark.parametrize("case", list(UNREADABLE_RECORDS))
def test_pairings_stage_refuses_or_reports_an_unreadable_record(tmp_path, pairing_log, case):
    pairing_log.parent.mkdir(parents=True)
    pairing_log.write_text(json.dumps(GOOD_ROW) + "\n" + UNREADABLE_RECORDS[case] + "\n")
    job = fixture_job(tmp_path)
    try:
        out = job.pairings()
    except ValueError as exc:
        assert "line 2" in str(exc) or "unreadable" in str(exc).lower()
        return
    said = (tmp_path / "run-self/homepage/PAIRINGS.md").read_text().lower() + json.dumps(out).lower()
    assert "unreadable" in said or "skipped" in said, "a bad log line was dropped without a word"


def test_pairings_stage_stops_when_the_log_cannot_be_read(tmp_path, pairing_log):
    """A log path that is not a readable file stops the stage before PAIRINGS.md is written."""
    pairing_log.mkdir(parents=True)  # a directory where the log file should be
    job = fixture_job(tmp_path)
    with pytest.raises(OSError):
        job.pairings()
    assert not (tmp_path / "run-self/homepage/PAIRINGS.md").exists()


def test_pairings_stage_stops_when_the_seed_cannot_be_read(tmp_path, monkeypatch):
    seed = tmp_path / "type-pairings.json"
    seed.write_text('{"pairings": [{"display": "Fraunces", ')
    monkeypatch.setattr(v2, "PAIRING_SEED", seed)
    job = fixture_job(tmp_path)
    with pytest.raises(ValueError):
        job.pairings()
    assert not (tmp_path / "run-self/homepage/PAIRINGS.md").exists()
