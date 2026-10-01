"""The measure after the close keeps what the market-hours measure saw (2026-10-01).

A criterion marked "(after the close)" waits while the market is open, and the driver measures the
bet again after the close. That measure walked every criterion again with the market shut, so what
only the open market shows could not be seen: b115's criterion 3 (the open-market line, met in
session) came back vacuous, and b111's criterion 6 (met in session) came back build_covered and was
refused. Both bets stayed iterate with every criterion seen met.

Now the driver hands that measure the market-hours outcome and the criteria that waited, and the
measure measures those and carries the rest.
"""

from tests.test_epd import test_epd_loop
from tests.test_epd.test_epd_loop import WAITING, _shipped_by_the_loop
from tests.test_epd.test_one_value_on_every_screen import node, wiring
from tests.test_epd.test_small_findings_get_a_last_pass import rendered

# The driver, loaded with its state in a temporary directory: test_epd_loop's fixture, by name.
L = test_epd_loop.L

MEASURE = {"outcome_path": "/o.md", "app_url": "https://prod.example.com", "email": "qa@x", "password": "pw",
           "bet_path": "/b.md", "report_path": "/r.md", "market": "shut"}


def test_the_measure_takes_the_market_hours_outcome_and_what_waited():
    measure = wiring("epd_measure")
    for name in ("open_outcome_path", "waited"):
        assert name in measure["inputs"]
        assert node(measure, "measure")["input_map"][name] == f"input.{name}"


def test_after_the_close_it_measures_what_waited_and_carries_the_rest():
    text = rendered("epd_measure", **MEASURE, open_outcome_path="/bets/b115/outcome-open.md", waited=WAITING)
    assert "## This is the measure after the close" in text
    assert f"- {WAITING[0]}" in text
    assert "/bets/b115/outcome-open.md" in text
    assert "Carry each other criterion's result from there" in text
    assert "do not walk it again" in text


def test_an_ordinary_measure_hears_nothing_of_it():
    assert "This is the measure after the close" not in rendered("epd_measure", **MEASURE)


def _after_close(L, monkeypatch) -> list:
    _shipped_by_the_loop(L, monkeypatch)
    st = L.load_state("b001")
    st["after_close"] = {"due": True, "criteria": WAITING, "since": "2026-10-01T17:15:00+00:00"}
    L.save_state(st)
    measured: list = []

    def fake_stage_measure(st, keep, market="", open_outcome="", waited=None):
        measured.append({"market": market, "open_outcome": open_outcome, "waited": waited})
        (L.BETS_DIR / st["bet_id"] / "outcome.md").write_text("# Outcome: after the close\n")
        return {"verdict": "kept", "waits_for_close": []}

    monkeypatch.setattr(L, "stage_measure", fake_stage_measure)
    monkeypatch.setattr(L, "after_close_window", lambda: (True, "shut until Fri Oct 2 06:30 PDT"))
    return measured


def test_the_driver_hands_over_the_market_hours_outcome_and_what_waited(L, monkeypatch):
    measured = _after_close(L, monkeypatch)
    L.cmd_after_close(keep=False)
    opened = L.BETS_DIR / "b001" / "outcome-open.md"
    assert measured == [{"market": "shut", "open_outcome": L.cpath(opened), "waited": WAITING}]
    assert opened.read_text() == "# Outcome: market hours\n"


def test_measuring_after_the_close_again_keeps_the_market_hours_outcome(L, monkeypatch):
    measured = _after_close(L, monkeypatch)
    L.cmd_after_close(keep=False)
    st = L.load_state("b001")
    st["after_close"]["due"] = True  # measured again by hand: outcome.md is the shut one now
    L.save_state(st)
    L.cmd_after_close(keep=False)
    assert len(measured) == 2
    assert (L.BETS_DIR / "b001" / "outcome-open.md").read_text() == "# Outcome: market hours\n", (
        "the second measure carries from the market-hours outcome, not from the first measure after the close")
