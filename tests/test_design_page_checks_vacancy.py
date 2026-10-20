"""Model-free tests for the measured empty-column vacancy rule (queue #114, W10b, hypothesis H12).

The page check's empty-column runs are unchanged; on the candidate path only, each run also gets a measured
answer (docs/design.md, "Empty-column vacancy"): yes (vacant_track, trailing, orphan) or no (in_item, between,
block, below_bar, outside_items). The keyed pages are configs/design/testpages/vacancy-v1 (expected.json),
keyed and sealed (~/design-lab/seals/vacancy-v1.json) before the vacancy code was written. No browser here:
tests/design_page_checks_scenes/vacancy-v1/*.raw.json were recorded from those pages with our own host headless
browser (~/design-lab/tools/page_checks_record_scenes.py), vacancy pass on.
"""
import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
FIXTURES = ROOT / "configs/design/testpages/vacancy-v1"
SCENES = Path(__file__).resolve().parent / "design_page_checks_scenes" / "vacancy-v1"
SEAL = Path.home() / "design-lab/seals/vacancy-v1.json"
H12 = "H12 (queue #114): the measured vacancy rule is not built yet"
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pc = _load("design_page_checks")
cap = _load("design_capture")
T = pc.thresholds()
KEY = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))


def test_the_keyed_pages_are_the_sealed_ones():
    """The key and its pages were sealed before the code; a changed page or answer is a new hold-out set."""
    if not SEAL.exists():
        pytest.skip(f"the seal lives on the host: {SEAL}")
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    files = {str(p.relative_to(ROOT)) for p in FIXTURES.rglob("*") if p.is_file()}
    assert files == set(seal["files"])
    for name, digest in seal["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name


def test_every_fixture_page_has_a_keyed_run_and_a_kind():
    groups = KEY["groups"]
    assert sorted(sum(groups.values(), [])) == sorted(KEY["pages"]) == sorted(p.name for p in FIXTURES.glob("*.html"))
    assert all(KEY["pages"][p]["runs"][0]["answer"] == "yes" for p in groups["yes"])
    assert all(KEY["pages"][p]["runs"][0]["answer"] == "no" for p in groups["no"] + groups["added_no"])
    reasons = {r["reason"] for page in KEY["pages"].values() for r in page["runs"]}
    assert reasons <= {"vacant_track", "trailing", "orphan", "in_item", "between", "block", "below_bar",
                       "outside_items"}


@pytest.mark.xfail(strict=True, reason=H12)
def test_the_vacancy_numbers_are_the_ones_decided_before_the_code():
    assert T["empty_column"] == {"viewport": "desktop", "min_share": 0.3, "min_height": 300, "band": 16,
                                 "center_tolerance": 0.1, "min_content_bands": 0.5}  # candidates unchanged
    v = T["vacancy"]
    assert (v["track_cover"], v["set_size_tolerance"], v["edge_px"]) == (0.5, 0.1, 2)


@pytest.mark.xfail(strict=True, reason=H12)
def test_the_vacancy_pass_is_off_unless_asked_for():
    """Live stages never ask: the in-page options stay what they were, so no live output can change."""
    js = (BIN / "design_page_checks.js").read_text(encoding="utf-8")
    opts = {"thresholds": T, "primary": "", "copy": True, "columns": True, "visuals": True, "cues": True,
            "overlays": True, "small_dark": True}
    assert pc.source(T, "", copy=True, columns=True, visuals=True) == js.replace("__OPTS__", json.dumps(opts))
    on = pc.source(T, "", copy=True, columns=True, visuals=True, vacancy=True)
    assert on == js.replace("__OPTS__", json.dumps({**opts, "vacancy": True}))
    assert pc.VACANCY_ENV == "DESIGN_PAGE_CHECKS_VACANCY"


@pytest.mark.xfail(strict=True, reason=H12)
def test_the_capture_asks_for_the_vacancy_pass_only_on_the_desktop_view_and_only_when_switched_on(monkeypatch):
    sent = []

    async def run(s, code):
        sent.append(code)
        return {}

    monkeypatch.setattr(cap, "run", run)
    for vacancy in (False, True):
        for vp, view in (("desktop", "desktop"), ("mobile", "mobile"), ("desktop", "mobile")):
            sent.clear()
            checks = {"thresholds": T, "primary": "Book a pickup", **({"vacancy": True} if vacancy else {})}
            asyncio.run(cap.page_checks(None, vp, view, checks))
            assert ('\\"vacancy\\": true' in sent[0]) is (vacancy and vp == view == "desktop"), (vacancy, vp, view)
    src = (BIN / "design_capture.py").read_text(encoding="utf-8")
    assert 'os.environ.get(pc.VACANCY_ENV) == "1"' in src


def _recorded(page):
    return json.loads((SCENES / page.replace(".html", ".raw.json")).read_text(encoding="utf-8"))["desktop"]


@pytest.mark.xfail(strict=True, reason=H12)
@pytest.mark.parametrize("page", sorted(KEY["pages"]))
def test_each_keyed_page_gets_its_keyed_answer_and_reason(page):
    raw = _recorded(page)
    got = [(c["section"], c["side"], c["x"], c["width"], c["height"], c["vacancy"]["answer"],
            c["vacancy"]["reason"]) for c in raw["columns"]]
    want = [(r["section"], r["side"], r["x"], r["width"], r["height"], r["answer"], r["reason"])
            for r in KEY["pages"][page]["runs"]]
    assert got == want


@pytest.mark.xfail(strict=True, reason=H12)
def test_each_answer_carries_its_container_and_the_numbers_it_was_decided_by():
    for page in sorted(KEY["pages"]):
        for c in _recorded(page)["columns"]:
            v = c["vacancy"]
            assert set(v) == {"answer", "reason", "container", "evidence"}, page
            if v["reason"] == "block" and v["container"] is None:
                assert v["evidence"]["why"], page
                continue
            assert v["container"]["sel"] and v["container"]["display"] and v["container"]["items"] >= 1, page
            if v["reason"] in ("vacant_track", "below_bar"):
                track = v["container"]["tracks"][v["evidence"]["track"] - 1]
                assert v["container"]["placed"][v["evidence"]["track"] - 1] == 0, page
                assert track == v["evidence"]["track_x"], page
                bar = T["vacancy"]["track_cover"]
                assert (v["evidence"]["cover"] >= bar) is (v["reason"] == "vacant_track"), page
            if v["reason"] == "orphan":
                assert v["evidence"]["set"] >= 2 and len(v["evidence"]["abreast"]) == 2, page


@pytest.mark.xfail(strict=True, reason=H12)
def test_judged_text_ignores_the_vacancy_answer():
    """facts.md's empty-column line is the same with or without the measured answer."""
    for page in sorted(KEY["pages"]):
        raw = _recorded(page)
        bare = {**raw, "columns": [{k: v for k, v in c.items() if k != "vacancy"} for c in raw["columns"]]}
        assert pc.judge("desktop", raw, T, raw.get("pixels")) == pc.judge("desktop", bare, T, bare.get("pixels"))
