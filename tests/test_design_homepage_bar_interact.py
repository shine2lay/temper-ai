"""design_homepage_bar_interact (Design, queues #79 and #96): the pure scorer and its maths. No browser.

The recorded raw files in configs/design/testpages/bar-interact-v1/raw/ and bar-interact-v2/raw/ come
from real runs of the meter on the fixture pages; scoring each must give exactly the failing rows in
its set's expected.json. bar-interact-v2 holds version 2's UI-part cases (H3c, WCAG 1.4.11).
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
KEYS = {
    name: json.loads((FIX.parent / name / "expected.json").read_text())
    for name in bi.FIXTURE_SETS
}


# ---------------------------------------------------------------- the key on the recorded runs


@pytest.mark.parametrize(
    "fixture_set,page",
    [(name, page) for name in bi.FIXTURE_SETS for page in sorted(KEYS[name]["pages"])],
)
def test_recorded_raw_scores_to_the_key(fixture_set, page):
    raw = json.loads(
        (
            FIX.parent / fixture_set / "raw" / (page.rsplit(".", 1)[0] + ".json")
        ).read_text()
    )
    doc = bi.score(raw)
    want = {tuple(x) for x in KEYS[fixture_set]["pages"][page]["failing"]}
    assert bi.failing(doc) == want


@pytest.mark.parametrize("fixture_set", bi.FIXTURE_SETS)
def test_recorded_raw_is_version_2(fixture_set):
    """Every recorded run was made by version 2: each UI candidate carries its visible-text reading."""
    for page in KEYS[fixture_set]["pages"]:
        stem = page.rsplit(".", 1)[0]
        raw = json.loads(
            (FIX.parent / fixture_set / "raw" / f"{stem}.json").read_text()
        )
        assert raw["version"] == 2 and raw["page"] == f"{fixture_set}/{page}"
        for width in ("1440x900", "390x844"):
            parts = raw["phases"][width]["ui"]["parts"]
            assert parts and all("vtext" in p for p in parts)


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


# ---------------------------------------------------------------- version 2: UI parts (H3c, WCAG 1.4.11)


def test_inside_pixels_keep_one_pixel_in_from_a_square_box():
    clip = {"x": 0, "y": 0, "width": 10, "height": 10}
    px = [(k, 0, 0) for k in range(100)]  # pixel k is row k // 10, column k % 10
    got = bi.inside_pixels(px, 10, 10, clip, [0, 0, 10, 10], [0, 0, 0, 0], [[0, 0]] * 4)
    assert len(got) == 64
    assert (0, 0, 0) not in got and (11, 0, 0) in got
    assert (88, 0, 0) in got and (89, 0, 0) not in got


def test_inside_pixels_leave_out_round_corners_and_borders():
    # a 48 px circle: the box's corners show what is behind it, and must never be read as icon
    clip = {"x": 100, "y": 50, "width": 48, "height": 48}
    px = [(k % 48, k // 48, 0) for k in range(48 * 48)]
    box = [100, 50, 48, 48]
    got = set(bi.inside_pixels(px, 48, 48, clip, box, [0, 0, 0, 0], [[24, 24]] * 4))
    assert (24, 1, 0) in got and (24, 24, 0) in got
    assert (3, 3, 0) not in got and (44, 44, 0) not in got
    assert all(
        ((x + 0.5 - 24) ** 2 + (y + 0.5 - 24) ** 2) ** 0.5 <= 23 + 1e-9
        for x, y, _ in got
    )
    # a 2 px border is left out, with the 1 px inside it
    got = set(bi.inside_pixels(px, 48, 48, clip, box, [2, 2, 2, 2], [[0, 0]] * 4))
    assert (2, 24, 0) not in got and (3, 24, 0) in got
    assert (45, 24, 0) not in got and (44, 24, 0) in got


def test_inside_pixels_map_a_fractional_box_onto_whole_pixels():
    # the box starts at x 10.5 and the shot at 10 (whole pixels): pixel 1's centre, 11.5, is 1 px in
    clip = {"x": 10, "y": 0, "width": 12, "height": 12}
    px = [(k % 12, k // 12, 0) for k in range(144)]
    got = bi.inside_pixels(
        px, 12, 12, clip, [10.5, 0, 11, 12], [0, 0, 0, 0], [[0, 0]] * 4
    )
    assert sorted({x for x, _, _ in got}) == list(range(1, 11))


def test_icon_reading_takes_the_90th_percentile_by_nearest_rank():
    ref = (29, 78, 216)
    faint, white = (91, 138, 245), (255, 255, 255)
    # 9 faint icon pixels and one stray white one, among fill pixels: rank ceil(0.9 x 10) = 9 is faint
    assert bi.icon_reading([faint] * 9 + [white] + [ref] * 30, ref) == (10, faint)
    # with 2 white pixels in 10, rank 9 is white
    assert bi.icon_reading([faint] * 8 + [white] * 2, ref) == (10, white)
    # within 2 of the reference in every channel: no icon pixels
    assert bi.icon_reading([ref, (30, 79, 217)], ref) == (0, None)


def _v2part(kind, vtext, bg=(0, 0, 0, 0), border=(0, 0, 0, 0), **kw):
    """A candidate measured by version 2. kw: full (border), behind ("none": not measured), icon."""
    behind = kw.get("behind", [248, 250, 252])
    behind = None if behind == "none" else list(behind)
    p = _part(kind, list(bg), list(border), kw.get("full", False), behind)
    icon = kw.get("icon")
    p["vtext"] = vtext
    if icon is not None:
        p["icon"] = icon
    return p


def test_ui_reading_version_2_cases():
    blue, white = [29, 78, 216, 1], [255, 255, 255]
    # a solid text button with a 1.6:1 fill is identified by its text: not measured here
    pale = _v2part("button", True, bg=[128, 210, 252, 1])
    assert bi.ui_reading(pale) == ("text", None)
    assert bi.ui_reading(_v2part("button", True, behind="none")) == ("text", None)
    # an icon-only button: its icon against its fill
    icon = {"ref": blue[:3], "pixels": 80, "p90": [91, 138, 245]}
    how, c = bi.ui_reading(_v2part("button", False, bg=blue, icon=icon))
    assert how == "icon" and round(c, 2) == 2.04
    unseen = _v2part("button", False, bg=blue, behind="none", icon=icon)
    assert bi.ui_reading(unseen) == ("unknown", None)
    # a link with no fill and no full border is a text link: not measured, with or without text
    stray = {"ref": [248, 250, 252], "pixels": 5, "p90": [0, 0, 0]}
    assert bi.ui_reading(_v2part("link", False, icon=stray))[0] == "none"
    # a tall link with a full border and a faint icon: the icon against what is behind it
    faint = {"ref": white, "pixels": 300, "p90": [203, 213, 225]}
    tall = _v2part("link", False, border=blue, full=True, behind=white, icon=faint)
    how, c = bi.ui_reading(tall)
    assert how == "icon" and round(c, 2) == 1.48
    # no text and no icon: the shape is read by part contrast, as in version 1
    none = {"ref": blue[:3], "pixels": 0, "p90": None}
    how, c = bi.ui_reading(_v2part("button", False, bg=blue, icon=none))
    assert how == "part" and c > 3
    # no text, no icon, no fill and no border: it draws nothing and is not measured
    bare = _v2part("button", False, icon=dict(none, ref=[248, 250, 252]))
    assert bi.ui_reading(bare)[0] == "none"
    # fields are read as before: a 1.50:1 border
    grey = [202, 207, 214, 1]
    field = _v2part("field", False, bg=[255, 255, 255, 1], border=grey, full=True)
    how, c = bi.ui_reading(field)
    assert how == "part" and round(c, 2) == 1.5


def test_score_ui_reads_version_1_raw_as_version_1():
    section = [248, 250, 252]
    red, cobalt = [200, 49, 26, 1], [30, 51, 200]
    red_on_cobalt = _part("button", red, [0, 0, 0, 0], False, cobalt)
    faint_field = _part("field", [255, 255, 255, 1], [229, 231, 235, 1], True, section)
    row = bi.score_ui([red_on_cobalt, faint_field], "1440x900", "limit")
    assert (row["value"], row["pass"]) == (2, False)
    assert row["evidence"][0]["text"] == "t (1.65:1)"
    # the same parts measured by version 2: the text button is identified by its text
    v2 = [dict(red_on_cobalt, vtext=True), dict(faint_field, vtext=False)]
    row = bi.score_ui(v2, "1440x900", "limit")
    assert (row["value"], row["pass"]) == (1, False)
    assert [e["text"] for e in row["evidence"]] == ["t (1.18:1)"]
    icon = {"ref": [29, 78, 216], "pixels": 80, "p90": [91, 138, 245]}
    v2 = [_v2part("button", False, bg=[29, 78, 216, 1], icon=icon)]
    evidence = bi.score_ui(v2, "390x844", "limit")["evidence"]
    assert evidence[0]["text"] == "t (icon 2.04:1)"


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
