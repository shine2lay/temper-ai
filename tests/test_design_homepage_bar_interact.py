"""design_homepage_bar_interact (Design, queue #79): the pure scorer and its maths. No browser.

The recorded raw files in configs/design/testpages/bar-interact-v1/raw/ come from real runs of the
meter on the fixture pages; scoring each must give exactly the failing rows in expected.json.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import struct
import zlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "configs" / "design" / "bin" / "design_homepage_bar_interact.py"
FIX = ROOT / "configs" / "design" / "testpages" / "bar-interact-v1"

spec = importlib.util.spec_from_file_location("design_homepage_bar_interact", BIN)
bi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bi)

KEY = json.loads((FIX / "expected.json").read_text())


# ---------------------------------------------------------------- the key on the recorded runs


@pytest.mark.parametrize("page", sorted(KEY["pages"]))
def test_recorded_raw_scores_to_the_key(page):
    raw = json.loads((FIX / "raw" / (page.rsplit(".", 1)[0] + ".json")).read_text())
    doc = bi.score(raw)
    want = {tuple(x) for x in KEY["pages"][page]["failing"]}
    assert bi.failing(doc) == want


def test_every_check_is_broken_by_some_fixture():
    broken = {tuple(x)[1] for p in KEY["pages"].values() for x in p["failing"]}
    every = {c for _, c, _ in bi.CHECKS} | {c for _, c, _ in bi.SPEED_CHECKS}
    assert broken == every
    assert KEY["pages"]["clean.html"]["failing"] == []


def test_output_contract_shape():
    raw = json.loads((FIX / "raw" / "clean.json").read_text())
    doc = bi.score(raw)
    assert set(doc) == {"meter", "version", "page", "page_sha256", "widths", "rows"}
    assert doc["widths"] == ["1440x900", "390x844", "412x823"]
    assert len(doc["rows"]) == 2 * len(bi.CHECKS) + len(bi.SPEED_CHECKS)
    for r in doc["rows"]:
        assert set(r) == {"bar", "check", "width", "value", "limit", "pass", "evidence"}
        assert r["pass"] in (True, False, None)
        for e in r["evidence"]:
            assert set(e) == {"selector", "text", "box"} and len(e["text"]) <= 80
    md = bi.to_md(doc)
    assert "| bar | check | width | value | limit | pass |" in md


def test_scoring_is_deterministic():
    raw = json.loads((FIX / "raw" / "sticky-cover.json").read_text())
    assert bi.score(raw) == bi.score(json.loads(json.dumps(raw)))


# ---------------------------------------------------------------- keyboard order


def _stop(box, fixed=None, vbox=None):
    return {"box": box, "vbox": vbox or box, "fixed": fixed}


def test_inversions_reading_order_has_none():
    stops = [
        _stop([0, 0, 100, 20]),
        _stop([120, 0, 100, 20]),
        _stop([0, 100, 100, 20]),
        _stop([0, 200, 100, 20]),
    ]
    assert bi.inversions(stops) == []


def test_inversion_upwards_more_than_24px():
    stops = [_stop([0, 200, 100, 20]), _stop([0, 100, 100, 20])]
    assert bi.inversions(stops) == [1]
    # 24 px up exactly is not an inversion
    assert bi.inversions([_stop([0, 124, 100, 20]), _stop([0, 100, 100, 20])]) == []


def test_next_column_up_is_not_an_inversion():
    # card grid: card 1 "Read more" (low, left), then card 2 title (higher, wholly right)
    stops = [_stop([40, 400, 120, 24]), _stop([200, 300, 200, 30])]
    assert bi.inversions(stops) == []


def test_jump_left_on_same_row_is_an_inversion():
    stops = [_stop([300, 100, 100, 40]), _stop([100, 110, 100, 40])]
    assert bi.inversions(stops) == [1]


def test_fixed_and_page_stops_are_not_compared():
    stops = [
        _stop([0, 900, 100, 20]),
        _stop([0, 0, 100, 20], fixed="body > header:nth-child(1)"),
    ]
    assert bi.inversions(stops) == []


def test_same_fixed_container_uses_viewport_boxes():
    h = "body > header:nth-child(1)"
    stops = [
        _stop([0, 900, 100, 20], h, [300, 10, 100, 20]),
        _stop([0, 900, 100, 20], h, [100, 10, 100, 20]),
    ]
    assert bi.inversions(stops) == [1]


def test_keyboard_reach_counts_radio_group_once():
    walk = {
        "interactive": [
            {"key": "radio:0:size", "sel": "a", "text": "", "box": [0, 0, 1, 1]},
            {"key": "radio:0:size", "sel": "b", "text": "", "box": [0, 0, 1, 1]},
            {"key": "el:3", "sel": "c", "text": "", "box": [0, 0, 1, 1]},
        ],
        "stops": [],
    }
    limits = {c: limit for _, c, limit in bi.CHECKS}
    rows = bi.score_walk(walk, "1440x900", limits)
    assert (
        rows[0]["check"] == "keyboard-reach"
        and rows[0]["value"] == 2
        and rows[0]["pass"] is False
    )


# ---------------------------------------------------------------- pixels and contrast


def test_contrast_known_values():
    assert bi.contrast((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert bi.contrast((29, 78, 216), (255, 255, 255)) == pytest.approx(6.7, abs=0.05)
    # #e5e7eb on white: L = 0.798, (1.05) / (0.848) = 1.238
    assert bi.contrast((229, 231, 235), (255, 255, 255)) == pytest.approx(
        1.238, abs=0.002
    )


def test_composite_alpha():
    assert bi.composite([0, 0, 0, 0.5], (255, 255, 255)) == (128, 128, 128)
    assert bi.composite([10, 20, 30, 0], (1, 2, 3)) == (1, 2, 3)


def test_changed_pairs_tolerance_two():
    a = [(10, 10, 10), (10, 10, 10), (10, 10, 10)]
    b = [(12, 10, 10), (13, 10, 10), (10, 10, 7)]
    assert bi.changed_pairs(a, b) == [
        ((10, 10, 10), (13, 10, 10)),
        ((10, 10, 10), (10, 10, 7)),
    ]


def test_indicator_contrast_is_perimeter_th_highest():
    white, blue, grey = (255, 255, 255), (29, 78, 216), (229, 231, 235)
    pairs = [(blue, white)] * 10 + [(grey, white)] * 30
    assert bi.indicator_contrast(pairs, 10) == pytest.approx(bi.contrast(blue, white))
    assert bi.indicator_contrast(pairs, 11) == pytest.approx(bi.contrast(grey, white))
    assert bi.indicator_contrast(pairs, 41) == 1.0


def test_perimeter_is_cut_to_viewport():
    assert bi.perimeter_of([10, 10, 100, 20], 1440, 900) == 240
    assert bi.perimeter_of([-50, 10, 100, 20], 1440, 900) == 140
    assert bi.perimeter_of([0, 2000, 100, 20], 1440, 900) == 4


def test_median_lum_pixel():
    px = [(0, 0, 0), (255, 255, 255), (120, 120, 120), (128, 128, 128), (250, 250, 250)]
    assert bi.median_lum_pixel(px) == (128, 128, 128)


def _png(w, h, rows, ctype=2, filt=0):
    bpp = 3 if ctype == 2 else 4
    raw = b""
    for row in rows:
        line = bytes(v for p in row for v in p[:bpp])
        if filt == 1:  # sub
            line = bytes(
                (line[i] - (line[i - bpp] if i >= bpp else 0)) & 255
                for i in range(len(line))
            )
        raw += bytes([filt]) + line

    def chunk(kind, body):
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize("ctype,filt", [(2, 0), (6, 0), (2, 1), (6, 1)])
def test_decode_png(ctype, filt):
    rows = [[(1, 2, 3, 255), (40, 50, 60, 255)], [(200, 100, 0, 255), (9, 9, 9, 255)]]
    w, h, px = bi.decode_png(_png(2, 2, rows, ctype, filt))
    assert (w, h) == (2, 2)
    assert px == [(1, 2, 3), (40, 50, 60), (200, 100, 0), (9, 9, 9)]


# ---------------------------------------------------------------- UI parts, states, motion, speed


def _part(kind, bg, border, full, behind):
    return {
        "sel": "x",
        "text": "t",
        "box": [0, 0, 10, 10],
        "kind": kind,
        "behind": behind,
        "fill_image": None,
        "style": {
            "background_rgba": bg,
            "background_image": "none",
            "border_rgba": border,
            "full_border": full,
        },
    }


def test_part_contrast_cases():
    section = [248, 250, 252]
    assert (
        bi.part_contrast(
            _part("button", [29, 78, 216, 1], [29, 78, 216, 1], True, section)
        )[1]
        > 3
    )
    # outlined button: transparent fill, blue border
    is_part, c = bi.part_contrast(
        _part("button", [0, 0, 0, 0], [29, 78, 216, 1], True, section)
    )
    assert is_part and c > 3
    # text link: no fill, no border -> not a UI part
    assert (
        bi.part_contrast(_part("button", [0, 0, 0, 0], [0, 0, 0, 0], False, section))[0]
        is False
    )
    # faint input: white fill, light grey border -> part under 3:1
    is_part, c = bi.part_contrast(
        _part("field", [255, 255, 255, 1], [229, 231, 235, 1], True, section)
    )
    assert is_part and c < 3


def _props(**kw):
    base = {
        p: "none" for p in ("outline-style", "text-decoration-line", "border-top-style")
    }
    base.update(
        {
            "outline-offset": "0px",
            "outline-color": "rgb(0, 0, 0)",
            "color": "rgb(0, 0, 0)",
        }
    )
    base.update({k.replace("_", "-"): v for k, v in kw.items()})
    return base


def test_has_state_ignores_props_that_draw_nothing():
    rest, state = _props(), _props(outline_offset="1px")
    assert bi.has_state({"self": {"rest": rest, "state": state}}) is False
    assert (
        bi.has_state({"self": {"rest": rest, "state": _props(outline_style="solid")}})
        is True
    )
    assert (
        bi.has_state({"self": {"rest": rest, "state": _props(color="rgb(1, 2, 3)")}})
        is True
    )
    assert bi.has_state({"self::after": {"rest": None, "state": rest}}) is True
    assert bi.has_state({}) is False


def test_states_share_counts_revealed_and_covered_elements():
    changed = {
        "self": {"rest": _props(), "state": _props(text_decoration_line="underline")}
    }
    items = [
        {"sel": "a.nav", "text": "Plans", "box": [0, 0, 1, 1], "diff": changed},
        # a skip link off the page at rest, hovered while focus reveals it: its own change counts
        {
            "sel": "a.skip",
            "text": "Skip to content",
            "box": [0, -96, 1, 1],
            "diff": changed,
            "via": "focus",
        },
        {"sel": "a.under", "text": "Hidden", "box": [0, 0, 1, 1], "note": "covered"},
        {"sel": "a.flat", "text": "Flat", "box": [0, 0, 1, 1], "diff": {}},
    ]
    row = bi.score_states(items, "hover-states", "1440x900", "every element")
    assert row["value"] == 50.0 and row["pass"] is False
    assert [e["selector"] for e in row["evidence"]] == ["a.under", "a.flat"]
    assert (
        bi.score_states(items[:2], "hover-states", "1440x900", "every element")["pass"]
        is True
    )


def test_motion_rows():
    limits = {c: limit for _, c, limit in bi.CHECKS}
    anim = {
        "key": ".wave|drift",
        "target": ".wave",
        "infinite": True,
        "active_ms": None,
        "box": [0, 0, 1, 1],
    }
    short = {
        "key": ".a|color",
        "target": ".a",
        "infinite": False,
        "active_ms": 150,
        "box": [0, 0, 1, 1],
    }
    normal = {"samples": [[anim]], "t_before": {}, "t_after": {}, "events": []}
    reduced = {
        "r1": [short],
        "r2": [[anim]],
        "videos": [],
        "t_before": {".wave": {"v": "a"}},
        "t_after": {".wave": {"v": "b"}},
    }
    rows = {r["check"]: r for r in bi.score_motion(normal, reduced, "1440x900", limits)}
    assert rows["reduced-motion-animation"]["value"] == 1
    assert (
        rows["reduced-motion-scroll"]["value"] == 0
    )  # the animated element is the animation row's
    assert (
        rows["motion-present"]["value"] == 1 and rows["motion-present"]["pass"] is True
    )


def test_speed_medians_and_limits():
    runs = [
        {"lcp": 2400.0, "cls": 0.2, "tbt": 100.0},
        {"lcp": 2600.0, "cls": 0.0, "tbt": 300.0},
        {"lcp": 2550.0, "cls": 0.05, "tbt": 150.0},
    ]
    rows = {r["check"]: r for r in bi.score_speed({"runs": runs})}
    assert rows["lcp"]["value"] == 2550 and rows["lcp"]["pass"] is False
    assert rows["cls"]["value"] == 0.05 and rows["cls"]["pass"] is True
    assert rows["tbt"]["value"] == 150 and rows["tbt"]["pass"] is True
    missing = {r["check"]: r for r in bi.score_speed({"runs": runs[:2]})}
    assert missing["lcp"]["pass"] is None
    assert bi.median_or_none([1, None, 3]) is None
