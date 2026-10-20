"""::before/::after drawn by the converter, and verify failing on any it can't (queue #103, hypothesis H9).

Offline: the extractor's own code on DOM doubles (tests/fixtures/converter_pseudo_contracts.cjs), the
converter's pseudo_content_drawn check on built and reopened files, and the keyed pseudo-v1 pages' key
itself. With a browser (DESIGN_PSEUDO_BROWSER, a
playwright-mcp address, and DESIGN_PSEUDO_SERVE_HOST, the address it reaches this machine on), the key test
converts the keyed pages for real (in-memory Penpot) and holds every outcome, count and the pixel guard to it.
"""

import copy
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from tests import pseudo_key
from tests.test_converter_followups import build_scene, reopen
from tests.test_design_homepage_v2 import FakePenpot
from tests.test_penpot_layout import BIN, board, h2p, text

GUARD = {"identical": True, "same_size": True, "differing": 0, "pct": 0}


def test_extractor_materialiser_on_dom_doubles():
    fixture = Path(__file__).parent / "fixtures/converter_pseudo_contracts.cjs"
    result = subprocess.run(["node", str(fixture), str(BIN / "html_dom_extract.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
    assert json.loads(result.stdout)["passed"] is True


def record(key, kind, text_="", drawn=True, **extra):
    return {"key": key, "where": f"p#{key}", "id": key, "pseudo": "::before", "kind": kind, "text": text_,
            "content": f'"{text_}"', "drawn": drawn, **extra}


def tick_page(records=None, guard=GUARD):
    """A line with a drawn tick (text) and a dot (shape), as the extractor hands them over."""
    tick = text("✓ Unlimited monitors", 0, 0, 300, 20)
    tick["pseudo"] = ["t1"]
    dot = board("Before / span.state", 0, 30, 8, 8, extra={"fills": [{"type": "color", "color": "#22C55E", "opacity": 1}],
                                                           "pseudo": ["d1"]})
    records = records if records is not None else [record("t1", "text", "✓"), record("d1", "shape")]
    return build_scene([tick, dot], pseudo={"records": records, "kept": True, "guard": guard})


def test_drawn_tick_and_dot_pass_and_are_counted_live():
    built = tick_page()
    assert {tuple(layer["keys"]) for layer in built["pseudo"]["layers"]} == {("t1",), ("d1",)}
    result = h2p.verify(reopen(built), "page-1", built)
    assert result["checks"]["pseudo_content_drawn"], result["pseudo"]["problems"]
    assert result["counts"]["pseudo_texts_live"] == result["counts"]["pseudo_texts"] == 1
    assert result["pseudo"]["counts"]["shapes_live"] == 1 and result["pseudo"]["counts"]["not_drawn"] == 0


def test_a_page_without_pseudo_elements_passes_with_nothing_counted():
    built = build_scene([text("Plain", 0, 0, 100, 20)], pseudo={"records": [], "kept": True})
    result = h2p.verify(reopen(built), "page-1", built)
    assert result["checks"]["pseudo_content_drawn"] and result["pseudo"]["counts"]["painted"] == 0


def test_scenes_without_a_pseudo_record_fail_closed():
    built = build_scene([text("Plain", 0, 0, 100, 20)])  # an extractor that records no pseudo-elements
    result = h2p.verify(reopen(built), "page-1", built)
    assert not result["checks"]["pseudo_content_drawn"]
    assert "no pseudo-element record" in result["pseudo"]["problems"][0]


def test_undrawable_pseudo_fails_the_check():
    records = [record("t1", "text", "✓"), record("d1", "shape"),
               record("c1", "text", "", drawn=False, not_drawn="counter")]
    built = tick_page(records)
    result = h2p.verify(reopen(built), "page-1", built)
    assert not result["checks"]["pseudo_content_drawn"] and not result["passed"]
    assert result["pseudo"]["counts"]["not_drawn"] == 1 and "counter" in result["pseudo"]["problems"][0]


@pytest.mark.parametrize("lose", ["text layer", "text words", "shape layer"])
def test_a_pseudo_lost_in_the_reopened_file_fails(lose):
    built = tick_page()
    fresh = reopen(built)
    objects = fresh["data"]["pages-index"]["page-1"]["objects"]
    layer = {"text layer": "t1", "text words": "t1", "shape layer": "d1"}[lose]
    oid = next(layer_["id"] for layer_ in built["pseudo"]["layers"] if layer in layer_["keys"])
    if lose == "text words":
        objects[oid]["content"]["children"][0]["children"][0]["children"][0]["text"] = "Unlimited monitors"
    else:
        del objects[oid]
    result = h2p.pseudo_check(built["pseudo"], objects)
    assert not result["passed"] and result["counts"]["not_drawn"] == 1


@pytest.mark.parametrize("guard, passed", [
    (GUARD, True),
    ({"identical": False, "same_size": True, "differing": 50, "pct": 0.01}, True),   # at the bar
    ({"identical": False, "same_size": True, "differing": 60, "pct": 0.0105}, False),
    ({"identical": False, "same_size": False, "differing": 0, "pct": 0}, False),
    (None, False),  # drawn pseudo-elements without a screenshot check
])
def test_pixel_guard_bar(guard, passed):
    built = tick_page(guard=guard)
    result = h2p.verify(reopen(built), "page-1", built)
    assert result["checks"]["pseudo_content_drawn"] is passed, result["pseudo"]["problems"]


# --------------------------------------------------------------------------- the keyed pages


PSEUDO_RULE = re.compile(r"([^{}]+?)::?(before|after)\s*\{([^}]*)\}")


def test_key_names_every_pseudo_rule_on_its_pages_and_its_counts_add_up():
    k = pseudo_key.key()
    for name, page in k["pages"].items():
        html = (pseudo_key.FIXTURE / name).read_text()
        ids = set(re.findall(r'id="([^"]+)"', html))
        hosts = {i["host"] for i in page["items"]}
        assert hosts <= ids, hosts - ids
        painted = [i for i in page["items"] if i["outcome"] != "none"]
        drawn = [i for i in painted if i["outcome"] == "drawn"]
        texts = [i for i in painted if i["kind"] in ("text", "box")]
        assert page["counts"]["painted"] == len(painted) and page["counts"]["drawn"] == len(drawn)
        assert page["counts"]["not_drawn"] == len(painted) - len(drawn)
        assert page["counts"]["texts"] == len(texts)
        assert page["counts"]["texts_live"] == sum(i["outcome"] == "drawn" for i in texts)
        assert page["pseudo_check_passes"] is (len(painted) == len(drawn))
        rules = PSEUDO_RULE.findall(re.sub(r"/\*.*?\*/", "", html, flags=re.S))
        sides = {s for _, s, body in rules if "content:" in body}  # rules that make a pseudo-element
        assert sides and sides == {i["pseudo"][2:] for i in page["items"]}
    index = k["pages"]["index.html"]["items"]
    assert sum(i["outcome"] == "none" for i in index) == 2  # the two no-paint negatives
    assert not k["pages"]["control.html"]["pseudo_check_passes"]  # the negative control must fail


def test_recorded_fixture_pages_have_no_pseudo_elements():
    """The older recorded scenes get an empty pseudo record (test_design_homepage_v2.scenes): their pages have none."""
    site = BIN.parent / "testpages/html-fixtures"
    for page in ("atlas.html", "rich.html"):
        assert not re.search(r"::?(before|after)\b", (site / page).read_text()), page


def test_key_check_catches_a_wrong_conversion():
    page = pseudo_key.key()["pages"]["index.html"]
    records, per_width = [], {}
    for w in pseudo_key.key()["widths"]:
        for i in page["items"]:
            if i["outcome"] == "none":
                continue
            records.append({"width": w, "id": i["host"], "pseudo": i["pseudo"], "kind": i["kind"],
                            "text": i.get("text", ""), "drawn": True})
        per_width[str(w)] = dict(page["counts"])
    good = {"pseudo": {"records": records, "guards": {str(w): GUARD for w in pseudo_key.key()["widths"]}},
            "verify": {"pseudo": {"passed": True, "per_width": per_width}}}
    assert pseudo_key.check(page, good) == []
    missing = copy.deepcopy(good)
    missing["pseudo"]["records"] = [r for r in records if r["id"] != "P4a"]
    assert any("P4a" in p for p in pseudo_key.check(page, missing))
    extra = copy.deepcopy(good)
    extra["pseudo"]["records"].append({"width": 390, "id": "N2", "pseudo": "::after", "kind": "shape", "drawn": True})
    assert any("N2" in p for p in pseudo_key.check(page, extra))
    moved = copy.deepcopy(good)
    moved["pseudo"]["guards"]["768"] = {"same_size": True, "pct": 0.02}
    assert any("pixels" in p for p in pseudo_key.check(page, moved))


BROWSER = os.environ.get("DESIGN_PSEUDO_BROWSER")


@pytest.mark.skipif(not BROWSER, reason="needs a playwright-mcp browser (DESIGN_PSEUDO_BROWSER)")
@pytest.mark.parametrize("name", ["index.html", "control.html"])
def test_keyed_pages_convert_as_their_key_says(tmp_path, monkeypatch, name):
    monkeypatch.setattr(h2p, "compare", lambda out, scenes, *a: {
        w: h2p.judge({"browser": [w, 1], "penpot": [w, 1], "overall_pct": 0, "nontext_pct": 0, "text_pct": 0,
                      "tile_max_pct": 0, "tile_mean_max": 0}) for w in scenes})
    report = h2p.convert(pseudo_key.FIXTURE, name, tmp_path, f"pseudo-v1 {name}", browser=BROWSER,
                         serve_host=os.environ.get("DESIGN_PSEUDO_SERVE_HOST"), client=FakePenpot(), label="Pinewick")
    page = pseudo_key.key()["pages"][name]
    assert pseudo_key.check(page, report) == []
    assert report["verify"]["checks"]["pseudo_content_drawn"] is page["pseudo_check_passes"]
    others = {k: v for k, v in report["verify"]["checks"].items() if k != "pseudo_content_drawn"}
    assert [k for k, v in others.items() if not v] == []  # the negative control fails on the pseudo check alone
