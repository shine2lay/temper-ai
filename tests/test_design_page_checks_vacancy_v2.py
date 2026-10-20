"""Model-free tests for H12b: a vacant track counts when its container lies inside the run (queue #118, W10c).

H12 (queue #114, tests/test_design_page_checks_vacancy.py) classifies each empty-column run by the grid or flex-row
container that holds it. H12b adds one way in (docs/design.md, "Empty-column vacancy", H12b): a grid or flex-row
ancestor of the content beside the run that covers the run's x-range, lies within the run give or take one band and
is at least vacancy.inside_share of the run's height; the tests then use the part of the run inside it. The keyed
hold-out pages are configs/design/testpages/vacancy-v2 (expected.json), keyed and sealed
(~/design-lab/seals/vacancy-v2.json) before the H12b code was written. No browser here:
tests/design_page_checks_scenes/vacancy-v2/*.raw.json were recorded from those pages, and
vacancy-known/new-craft02.raw.json from W10a's new-craft02 case site (the one known case H12 missed), with our own
host headless browser (~/design-lab/tools/page_checks_record_scenes.py), vacancy pass on.
"""
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
FIXTURES = ROOT / "configs/design/testpages/vacancy-v2"
SCENES = Path(__file__).resolve().parent / "design_page_checks_scenes"
SEAL = Path.home() / "design-lab/seals/vacancy-v2.json"
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pc = _load("design_page_checks")
T = pc.thresholds()
KEY = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
YES = KEY["groups"]["yes"] + KEY["groups"]["near_yes"]
NO = KEY["groups"]["no"] + KEY["groups"]["near_no"] + KEY["groups"]["control_no"]


def test_the_keyed_pages_are_the_sealed_ones():
    """The key and its pages were sealed before the H12b code; a changed page or answer is a new hold-out set."""
    if not SEAL.exists():
        pytest.skip(f"the seal lives on the host: {SEAL}")
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    files = {str(p.relative_to(ROOT)) for p in FIXTURES.rglob("*") if p.is_file()}
    assert files == set(seal["files"])
    for name, digest in seal["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name


def test_every_page_has_a_keyed_run_a_kind_and_a_heading_and_intro_above_its_layout():
    pages = sorted(p.name for p in FIXTURES.glob("*.html"))
    assert sorted(YES + NO) == sorted(KEY["pages"]) == pages
    assert all(KEY["pages"][p]["runs"][0]["answer"] == "yes" for p in YES)
    assert all(KEY["pages"][p]["runs"][0]["answer"] == "no" for p in NO)
    assert all(len(KEY["pages"][p]["runs"]) == 1 for p in pages)
    for inside, outside in KEY["pairs"].values():  # each near-threshold pair: one yes, one no
        assert (inside, outside) in {(a, b) for a in KEY["groups"]["near_yes"] for b in KEY["groups"]["near_no"]}
    for page in pages:
        html = (FIXTURES / page).read_text(encoding="utf-8")
        layout = min(m.start() for m in re.finditer(r'class="(grid3|row|split|rows|chips)"', html))
        heading = html.index("<h2>")
        intro = min(html.index(c) for c in ('class="intro"', 'class="lead"') if c in html)
        assert heading < intro < layout, page


def test_the_inside_share_was_decided_before_the_code_and_nothing_else_moved():
    assert T["empty_column"] == {"viewport": "desktop", "min_share": 0.3, "min_height": 300, "band": 16,
                                 "center_tolerance": 0.1, "min_content_bands": 0.5}  # candidates unchanged
    v = T["vacancy"]
    assert (v["track_cover"], v["set_size_tolerance"], v["edge_px"], v["inside_share"]) == (0.5, 0.1, 2, 0.5)
    assert "before the vacancy-v2 seal and any H12b code" in v["inside_share_decided"]
    assert "0.61" in v["inside_share_decided"]  # chosen with new-craft02's share known, and says so


def _recorded(path):
    return json.loads(path.read_text(encoding="utf-8"))["desktop"]


def _page(page):
    return _recorded(SCENES / "vacancy-v2" / page.replace(".html", ".raw.json"))


@pytest.mark.parametrize("page", sorted(KEY["pages"]))
def test_each_keyed_page_gets_its_keyed_answer_and_reason(page):
    got = [(c["section"], c["side"], c["x"], c["width"], c["height"], c["top"], c["vacancy"]["answer"],
            c["vacancy"]["reason"]) for c in _page(page)["columns"]]
    want = [(r["section"], r["side"], r["x"], r["width"], r["height"], r["top"], r["answer"], r["reason"])
            for r in KEY["pages"][page]["runs"]]
    assert got == want


def _known():
    return {c["section"]: c for c in _recorded(SCENES / "vacancy-known/new-craft02.raw.json")["columns"]}


def test_new_craft02_classes_is_a_vacant_track_and_its_how_column_stays_no():
    """W10a's new-craft02 (cases-v2.json): the classes run starts at its heading, the one-card grid lies inside it."""
    cols = _known()
    assert (cols["classes"]["x"], cols["classes"]["width"], cols["classes"]["height"], cols["classes"]["top"]) == (
        664, 568, 464, 806)
    assert (cols["classes"]["vacancy"]["answer"], cols["classes"]["vacancy"]["reason"]) == ("yes", "vacant_track")
    assert cols["how"]["vacancy"]["answer"] == "no"


def _inside_cases():
    yield from ((p, _page(p)["columns"][0]) for p in YES)
    yield "new-craft02 classes", _known()["classes"]


@pytest.mark.parametrize("case", YES + ["new-craft02 classes"])
def test_a_yes_from_a_container_inside_the_run_carries_its_share_and_clipped_span(case):
    column = dict(_inside_cases())[case]
    inside = column["vacancy"]["container"]["inside"]
    top, end = column["top"], column["top"] + column["height"]
    y0, y1 = inside["y"]
    band = T["empty_column"]["band"]
    assert y0 >= top - band - 1 and y1 <= end + band + 1, case
    assert inside["share"] == pytest.approx((y1 - y0) / column["height"], abs=0.002), case
    assert inside["share"] >= T["vacancy"]["inside_share"], case
    assert inside["span"] == pytest.approx([max(top, y0), min(end, y1)], abs=1), case


def test_answers_from_a_container_that_holds_the_run_carry_no_inside_field():
    """Holding containers keep the whole run, as in H12: their evidence does not move."""
    for page in sorted(KEY["pages"]):
        v = _page(page)["columns"][0]["vacancy"]
        if page not in YES and v["container"] is not None:
            assert "inside" not in v["container"], page


def test_judged_text_ignores_the_vacancy_answer():
    """facts.md's empty-column line is the same with or without the measured answer."""
    for page in sorted(KEY["pages"]):
        raw = _page(page)
        bare = {**raw, "columns": [{k: v for k, v in c.items() if k != "vacancy"} for c in raw["columns"]]}
        assert pc.judge("desktop", raw, T, raw.get("pixels")) == pc.judge("desktop", bare, T, bare.get("pixels"))
