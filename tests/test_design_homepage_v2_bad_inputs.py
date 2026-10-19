"""Bad inputs to two script stages of design_homepage_v2 (queue #87, W3; BAR.md C "bad inputs refused").

The stage map (#77, ~/design-lab/homepage-workflow/STAGE-MAP.md) found no test that feeds the references
stage or the pairings stage a bad input. These tests do, without a browser, a model or Temper.

What "refused" means here (Design's bar for script stages): the stage stops with an error that names the
problem before it does any work (no capture, no receipt, no output file), OR it drops the bad part and says
so in its output. Dropping a bad part silently is not a refusal: the next stage would trust a list that is
quietly shorter than what was recorded.

Where the code accepts a bad input, the test is xfail(strict=True) with the reason, so it starts failing
(XPASS) the day the code is fixed and the mark has to come off. W3 found one such gap: unreadable pairing-log
lines were dropped without a word. W3c (queue #98) fixed it (skipped, so the run goes on, but named), and no
xfail is left.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
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


CLEAN = Path(__file__).resolve().parent / "design_homepage_v2_pairings" / "clean-log"


def run_clean_log(root: Path, log: Path) -> dict[str, bytes]:
    """The pairings stage on the fixed clean log in CLEAN: PAIRINGS.md, the stage output and the list the concept
    check reads, as bytes. The caller points DESIGN_PAIRING_LOG at `log` and v2.PAIRING_SEED at CLEAN / seed.json."""
    log.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CLEAN / "type-pairings.jsonl", log)
    job = v2.Job(str(root / "run-self"), fixture=True)
    job.brief("")
    shutil.copyfile(CLEAN / "brief.json", job.packet / "brief.json")  # brand fonts fixed here, not by FIXTURE_BRIEF
    out = job.pairings()
    return {"PAIRINGS.md": (job.packet / "PAIRINGS.md").read_bytes(),
            "output.json": json.dumps(out, ensure_ascii=False).encode(),
            "recorded.json": json.dumps(v2.recorded_pairings(log, "run-self"), ensure_ascii=False, indent=1).encode()}


def test_pairings_stage_on_a_clean_log_writes_the_same_bytes_as_before(tmp_path, pairing_log, monkeypatch, capsys):
    """W3c only adds a report of unreadable log lines. On a log with none (CLEAN: other runs' rows, the run's own row,
    an event that is no pairing, a seed pairing the other way round, a blank face, a blank line, rows without kind or
    workspace, a last line without a newline) PAIRINGS.md, the stage output and the concept check's list are byte
    for byte the recording made with the code before W3c (temper-ai fecacf06), and nothing is written to stderr."""
    monkeypatch.setattr(v2, "PAIRING_SEED", CLEAN / "seed.json")
    made = run_clean_log(tmp_path, pairing_log)
    for name, data in made.items():
        assert data == (CLEAN / name).read_bytes(), name
    assert capsys.readouterr().err == ""


CUT_ROW = json.dumps(GOOD_ROW | {"display": "Fraunces", "text": "Karla"})[:40]  # a write stopped part-way

UNREADABLE_RECORDS = {
    "not json": ("not json at all", "not JSON"),
    "cut off mid-write": (CUT_ROW, "cut off"),
    "json but not an object": (json.dumps(["Fraunces", "Karla"]), "not an object"),
}

# What the concept check reads from a log holding GOOD_ROW and bad lines: the seed and GOOD_ROW, as before W3c.
READABLE = [*({"display": p["display"], "text": p["text"], "source": p.get("source", "recorded")} for p in SEED["pairings"]),
            {"display": "Gloock", "text": "Hanken Grotesk", "source": "offered in run run-other"}]


@pytest.mark.parametrize("case", list(UNREADABLE_RECORDS))
def test_pairings_stage_refuses_or_reports_an_unreadable_record(tmp_path, pairing_log, capsys, case):
    """W3c (queue #98): a log line the stage can't read is skipped, so the run goes on, and named by line number
    and kind in PAIRINGS.md, in the output (unreadable_log_lines) and in one warning line. The list is as before."""
    record, kind = UNREADABLE_RECORDS[case]
    pairing_log.parent.mkdir(parents=True)
    pairing_log.write_text(json.dumps(GOOD_ROW) + "\n" + record + "\n")
    out = fixture_job(tmp_path).pairings()
    assert out["status"] == "completed" and out["unreadable_log_lines"] == [{"line": 2, "kind": kind}]
    assert out["used_pairings"] == len({v2.pairing_key(p["display"], p["text"]) for p in SEED["pairings"]}) + 1
    text = (tmp_path / "run-self/homepage/PAIRINGS.md").read_text()
    assert (f"\n\nSkipped: the pairing log has 1 unreadable line (line 2: {kind}), so this list may be missing a "
            "pairing from it.\n\n- ") in text
    assert "Gloock + Hanken Grotesk (offered in run run-other)" in text
    assert capsys.readouterr().err.splitlines() == [
        f"pairings: warning: skipped 1 unreadable line (line 2: {kind}) in {pairing_log}"]
    assert v2.recorded_pairings(pairing_log, "run-self") == READABLE  # the concept check's list is unchanged


def test_pairings_stage_counts_every_unreadable_line_and_names_the_first_ten(tmp_path, pairing_log, capsys):
    """A cut-off row with the next run's row appended to it (how a write stopped part-way meets the next one) is
    named cut off; a blank line holds no row and is not counted. Past ten unreadable lines PAIRINGS.md and the
    warning name ten and count the rest; the output lists them all."""
    rows = [json.dumps(GOOD_ROW), CUT_ROW + json.dumps(GOOD_ROW | {"workspace": "run-later"}), "",
            *(f"not json {n}" for n in range(4, 15))]
    pairing_log.parent.mkdir(parents=True)
    pairing_log.write_text("\n".join(rows) + "\n")
    out = fixture_job(tmp_path).pairings()
    assert out["unreadable_log_lines"] == [{"line": 2, "kind": "cut off"},
                                           *({"line": n, "kind": "not JSON"} for n in range(4, 15))]
    named = "12 unreadable lines (line 2: cut off; " + "; ".join(f"line {n}: not JSON" for n in range(4, 13)) + "; and 2 more)"
    assert f"Skipped: the pairing log has {named}, so this list may be missing pairings from them.\n" in (
        tmp_path / "run-self/homepage/PAIRINGS.md").read_text()
    assert capsys.readouterr().err.splitlines() == [f"pairings: warning: skipped {named} in {pairing_log}"]
    assert out["status"] == "completed" and v2.recorded_pairings(pairing_log, "run-self") == READABLE


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
