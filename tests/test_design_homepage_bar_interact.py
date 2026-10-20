"""design_homepage_bar_interact (Design, queues #79, #96, #110 and #113): the pure scorer and its maths. No browser.

The recorded raw files in configs/design/testpages/bar-interact-v1/raw/ and bar-interact-v2/raw/ come
from real runs of the meter on the fixture pages; scoring each must give exactly the failing rows in
its set's expected.json. bar-interact-v2 holds version 2's UI-part cases (H3c, WCAG 1.4.11). The
test_h3d_* cases are version 3's speed gate (H3d): a fake load reader, clock and Lighthouse run.
The test_a11* cases are version 4's A11 (d), motion with a purpose (#113): its sealed key
bar-interact-a11-v1, and readings made up to hit each part of the definition.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import shutil
import struct
import sys
import types
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


# ---------------------------------------------------------------- H3d: speed only on a quiet machine (queue #110)

BUSY = "could not measure: machine busy (load {:.2f})"


class Machine:
    """A fake machine for the speed gate: a load reader, a clock, a sleep and a Lighthouse run.

    load_at(machine) gives the 1-minute load at the machine's time. Each Lighthouse run takes run_s
    seconds and gives the next (lcp, cls, tbt) of values; the last one repeats.
    """

    def __init__(self, load_at, values=((900.0, 0.0, 0.0),), run_s=20.0):
        self.load_at = load_at
        self.values = list(values)
        self.run_s = run_s
        self.t = 0.0
        self.last = None  # "sleep" or "run": what the machine did last
        self.sleeps: list[float] = []
        self.started: list[float] = []

    def clock(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s
        self.last = "sleep"

    def load(self) -> float:
        return self.load_at(self)

    def once(self) -> dict:
        lcp, cls, tbt = self.values[min(len(self.started), len(self.values) - 1)]
        self.started.append(self.t)
        self.t += self.run_s
        self.last = "run"
        return {
            "lcp": lcp,
            "cls": cls,
            "tbt": tbt,
            "nodes": {"lcp": [], "cls": []},
            "lighthouse": "13.5.0",
            "chrome": "fake",
        }

    def speed(self) -> dict:
        return bi.gated_runs(
            self.once, load=self.load, clock=self.clock, sleep=self.sleep
        )


def _speed_rows(speed: dict) -> dict:
    return {r["check"]: r for r in bi.score_speed(speed)}


def _raw(fixture_set: str, stem: str) -> dict:
    return json.loads((FIX.parent / fixture_set / "raw" / f"{stem}.json").read_text())


def _busy(raw: dict, load: float) -> dict:
    return dict(raw, speed={"runs": [], "error": BUSY.format(load)})


def _want(fixture_set: str, page: str) -> set:
    return {tuple(x) for x in KEYS[fixture_set]["pages"][page]["failing"]}


def test_h3d_gate_values_and_unchanged_speed_definitions():
    assert (bi.LOAD_GATE, bi.LOAD_POLL_S, bi.LOAD_WAIT_S) == (6.0, 15, 600)
    assert bi.SPEED_RUNS == 3 and bi.VERSION == 3
    assert bi.SPEED_CHECKS == [
        ("A8", "lcp", "LCP 2.5 s or less (2500 ms or less)"),
        ("A8", "cls", "CLS 0.1 or less"),
        ("A8", "tbt", "total blocking time 200 ms or less"),
    ]
    assert isinstance(bi.read_load(), float)


def test_h3d_a_quiet_machine_measures_three_runs_as_before():
    m = Machine(
        lambda m: 1.5,
        values=[(900.0, 0.0, 30.0), (950.0, 0.02, 0.0), (910.0, 0.01, 10.0)],
    )
    speed = m.speed()
    assert m.started == [0.0, 20.0, 40.0] and m.sleeps == []
    assert [(r["load_before"], r["load_after"]) for r in speed["runs"]] == [
        (1.5, 1.5)
    ] * 3
    assert speed["dropped"] == [] and "error" not in speed
    assert speed["gate"]["waited_s"] == 0 and speed["gate"]["redone"] == 0
    rows = _speed_rows(speed)
    assert {c: (r["value"], r["pass"]) for c, r in rows.items()} == {
        "lcp": (910, True),
        "cls": (0.01, True),
        "tbt": (10, True),
    }
    plain = {
        "runs": [{"lcp": a, "cls": b, "tbt": c} for a, b, c in m.values],
        "nodes": speed["nodes"],
    }
    assert bi.score_speed(speed) == bi.score_speed(plain)


def test_h3d_b_busy_then_quiet_waits_then_measures():
    m = Machine(lambda m: 8.0 if m.t < 120 else 2.0)
    speed = m.speed()
    assert m.sleeps == [15] * 8 and m.started == [120.0, 140.0, 160.0]
    assert speed["gate"]["waited_s"] == 120 and speed["gate"]["polls"] == 8
    assert [(r["load_before"], r["load_after"]) for r in speed["runs"]] == [
        (2.0, 2.0)
    ] * 3
    assert "error" not in speed
    assert all(r["pass"] is True for r in bi.score_speed(speed))


def test_h3d_c_busy_throughout_could_not_measure():
    m = Machine(lambda m: 9.5)
    speed = m.speed()
    assert m.started == [] and m.t == 600 and len(m.sleeps) == 40
    assert speed["error"] == "could not measure: machine busy (load 9.50)"
    assert speed["gate"]["busy_load"] == 9.5
    rows = bi.score_speed(speed)
    assert [r["check"] for r in rows] == ["lcp", "cls", "tbt"]
    for r in rows:
        assert r["pass"] is None and r["value"] is None
        assert r["evidence"][0]["text"] == "could not measure: machine busy (load 9.50)"
    assert bi.tally({"rows": rows}) == {
        "rows": {"met": 0, "not met": 0, "could not measure": 3},
        "bars": {"A8": "could not measure"},
    }


def test_h3d_d_load_rising_during_a_run_throws_it_away_and_redoes_it():
    m = Machine(
        lambda m: 7.0 if 20 <= m.t < 50 else 1.0,
        values=[
            (2600.0, 0.0, 536.0),
            (900.0, 0.0, 0.0),
            (905.0, 0.0, 12.0),
            (901.0, 0.0, 0.0),
        ],
    )
    speed = m.speed()
    assert m.started == [0.0, 50.0, 70.0, 90.0]
    assert speed["dropped"] == [
        {"lcp": 2600.0, "cls": 0.0, "tbt": 536.0, "load_before": 1.0, "load_after": 7.0}
    ]
    assert speed["gate"]["redone"] == 1 and speed["gate"]["waited_s"] == 30
    assert [r["tbt"] for r in speed["runs"]] == [0.0, 12.0, 0.0]
    assert "error" not in speed
    rows = _speed_rows(speed)
    assert (rows["lcp"]["value"], rows["lcp"]["pass"]) == (901, True)
    assert (rows["tbt"]["value"], rows["tbt"]["pass"]) == (0, True)


def test_h3d_d_every_run_getting_busy_ends_could_not_measure():
    m = Machine(lambda m: 7.0 if m.last == "run" else 1.0)
    speed = m.speed()
    assert speed["runs"] == [] and len(speed["dropped"]) == 18
    assert m.started == [35.0 * k for k in range(18)]
    assert speed["error"] == "could not measure: machine busy (load 7.00)"
    assert all(r["pass"] is None for r in bi.score_speed(speed))


def test_h3d_cap_is_checked_before_each_wait_and_each_run():
    slow = Machine(lambda m: 1.0, run_s=250.0)
    speed = slow.speed()
    assert slow.started == [0.0, 250.0, 500.0] and len(speed["runs"]) == 3
    assert "error" not in speed
    slower = Machine(lambda m: 1.0, run_s=300.0)
    speed = slower.speed()
    assert slower.started == [0.0, 300.0] and len(speed["runs"]) == 2
    assert speed["error"] == "could not measure: 2 of 3 quiet runs in 600 s"
    assert all(r["pass"] is None for r in bi.score_speed(speed))


def test_h3d_lighthouse_error_still_ends_the_step():
    m = Machine(lambda m: 1.0)

    def boom():
        raise RuntimeError("lighthouse exit 1: boom")

    speed = bi.gated_runs(boom, load=m.load, clock=m.clock, sleep=m.sleep)
    assert speed["error"] == "RuntimeError: lighthouse exit 1: boom"
    assert all(r["pass"] is None for r in bi.score_speed(speed))


def test_h3d_measure_speed_runs_through_the_gate(monkeypatch, tmp_path):
    class Server:
        down = False

        def shutdown(self):
            self.down = True

    srv = Server()
    fake_dc = types.SimpleNamespace(
        serve=lambda site, host: ("http://127.0.0.1:1", srv)
    )
    monkeypatch.setitem(sys.modules, "design_capture", fake_dc)
    m = Machine(lambda m: 1.0)
    monkeypatch.setattr(bi, "lighthouse_once", lambda url, tool, chrome: m.once())
    monkeypatch.setattr(bi, "read_load", m.load)
    speed = bi.measure_speed(tmp_path, "index.html", tmp_path, tmp_path)
    assert len(speed["runs"]) == 3 and srv.down and "error" not in speed
    assert all({"load_before", "load_after"} <= set(r) for r in speed["runs"])


def test_h3d_e_could_not_measure_is_counted_apart():
    doc = bi.score(_busy(_raw("bar-interact-v1", "faint-input"), 7.21))
    n = len(doc["rows"])
    assert bi.tally(doc) == {
        "rows": {"met": n - 5, "not met": 2, "could not measure": 3},
        "bars": {"A4": "not met", "A7": "met", "A8": "could not measure"},
    }
    md = bi.to_md(doc)
    assert "- A8: could not measure (lcp 412x823, cls 412x823, tbt 412x823)" in md
    assert "- A4: not met (ui-contrast 1440x900, ui-contrast 390x844)" in md
    assert f"Rows: {n - 5} met, 2 not met, 3 could not measure." in md
    assert (
        "| A8 | tbt | 412x823 | n/a | total blocking time 200 ms or less | could not measure |"
        in md
    )
    evidence, unmeasured = md.split("## Evidence for rows not met")[1].split(
        "## Rows that could not be measured"
    )
    assert "- ui-contrast 1440x900:" in evidence and "412x823" not in evidence
    assert "- tbt 412x823: could not measure: machine busy (load 7.21)" in unmeasured
    want = _want("bar-interact-v1", "faint-input.html")
    assert bi.page_verdict(doc, want) == "could not measure"
    assert (
        bi.page_verdict(doc, want | {("A8", "tbt", "412x823")}) == "could not measure"
    )
    assert bi.page_verdict(doc, set()) == "differ"
    quiet = bi.score(_raw("bar-interact-v1", "faint-input"))
    assert bi.page_verdict(quiet, want) == "match"
    slow = _raw("bar-interact-v1", "slow-script")
    slow_want = _want("bar-interact-v1", "slow-script.html")
    assert bi.page_verdict(bi.score(slow), slow_want) == "match"
    assert bi.page_verdict(bi.score(_busy(slow, 6.4)), slow_want) == "could not measure"


def test_h3d_e_fixture_proof_counts_could_not_measure_apart(tmp_path, capsys):
    src = tmp_path / "raw-in"
    for name in bi.FIXTURE_SETS:
        shutil.copytree(FIX.parent / name / "raw", src / name / "raw")
    clean = src / "bar-interact-v1" / "raw" / "clean.json"
    clean.write_text(json.dumps(_busy(json.loads(clean.read_text()), 6.4)))
    out = tmp_path / "out"
    code = bi.main(["--fixture-proof", "--from-raw", str(src), "--out", str(out)])
    proof = json.loads((out / "fixture-proof.json").read_text())
    assert code == 3 and proof["all_match"] is False
    assert (proof["match"], proof["differ"], proof["could_not_measure"]) == (18, 0, 1)
    entry = next(p for p in proof["pages"] if p["page"] == "clean.html")
    assert entry["verdict"] == "could not measure" and entry["match"] is False
    assert entry["extra"] == [] and entry["missing"] == []
    assert len(entry["unmeasured"]) == 3
    printed = capsys.readouterr().out
    assert "COULD NOT MEASURE bar-interact-v1/clean.html" in printed
    assert "fixture proof: 18/19 pages match, 0 differ, 1 could not measure" in printed


def test_h3d_e_a_real_speed_fail_still_differs(tmp_path, capsys):
    src = tmp_path / "raw-in"
    for name in bi.FIXTURE_SETS:
        shutil.copytree(FIX.parent / name / "raw", src / name / "raw")
    clean = src / "bar-interact-v1" / "raw" / "clean.json"
    raw = json.loads(clean.read_text())
    raw["speed"]["runs"] = [dict(r, tbt=536.0) for r in raw["speed"]["runs"]]
    clean.write_text(json.dumps(raw))
    out = tmp_path / "out"
    code = bi.main(["--fixture-proof", "--from-raw", str(src), "--out", str(out)])
    proof = json.loads((out / "fixture-proof.json").read_text())
    assert code == 1
    assert (proof["match"], proof["differ"], proof["could_not_measure"]) == (18, 1, 0)
    entry = next(p for p in proof["pages"] if p["page"] == "clean.html")
    assert entry["verdict"] == "differ" and entry["extra"] == [["A8", "tbt", "412x823"]]
    assert "fixture proof: 18/19 pages match, 1 differ, 0 could not measure" in (
        capsys.readouterr().out
    )


# ---------------------------------------------------------------- A11 (d): motion with a purpose (#113)

A11 = FIX.parent / "bar-interact-a11-v1"
A11_KEY = json.loads((A11 / "expected.json").read_text())
# The key's sha256, sealed in ~/design-lab/seals/bar-interact-a11-v1.json before version 4's code.
A11_KEY_SHA256 = "b911ac91f7e1fc99abe691f42d022b32fbbe43db2ca11ddf8bf318310c4a0fdf"
A11_SEAL = pathlib.Path.home() / "design-lab" / "seals" / "bar-interact-a11-v1.json"
A11_WIDTHS = ("1440x900", "390x844")
A11_ROWS = ("motion-signature", "motion-feedback", "motion-timing", "motion-reduced")
A11D = pytest.mark.xfail(
    strict=True, reason="A11d: the meter's version 4 code is written after its sealed key (#113)"
)


def test_a11_key_is_the_sealed_one():
    assert hashlib.sha256((A11 / "expected.json").read_bytes()).hexdigest() == A11_KEY_SHA256
    if A11_SEAL.exists():  # the seal is kept outside the repo, in ~/design-lab
        seal = json.loads(A11_SEAL.read_text())
        assert seal["files"] == {
            "configs/design/testpages/bar-interact-a11-v1/expected.json": A11_KEY_SHA256
        }


def test_a11_key_holds_the_planned_cases():
    pages = A11_KEY["pages"]
    assert set(pages) == {p.name for p in A11.glob("*.html")} and len(pages) == 15
    assert [tuple(c) for c in A11_KEY["checks"]] == [("A11", c) for c in A11_ROWS]
    assert tuple(A11_KEY["widths"]) == A11_WIDTHS
    fails = {p: {tuple(x) for x in spec["failing"]} for p, spec in pages.items()}
    for page, rows in fails.items():
        assert all(b == "A11" and c in A11_ROWS and w in A11_WIDTHS for b, c, w in rows), page

    def both(*checks):
        return {("A11", c, w) for c in checks for w in A11_WIDTHS}

    assert fails["clean-motion.html"] == set()
    assert fails["static.html"] == both("motion-signature", "motion-feedback")
    plants = {
        "entrance-second-screen.html": "motion-signature",
        "no-hover-button.html": "motion-feedback",
        "transition-800.html": "motion-timing",
        "linear-easing.html": "motion-timing",
        "loop-600.html": "motion-timing",
        "reduced-ignored.html": "motion-reduced",
    }
    for page, check in plants.items():
        assert fails[page] == both(check), page
    for bad, good in (
        ("timing-110.html", "timing-120.html"),
        ("timing-520.html", "timing-500.html"),
        ("loop-1000.html", "loop-1100.html"),
    ):
        assert fails[bad] == both("motion-timing") and fails[good] == set(), (bad, good)
    assert fails["scroll-linked.html"] == set()
    assert {c for rows in fails.values() for _, c, _ in rows} == set(A11_ROWS)


def _a11_anim(**kw) -> dict:
    """One recorded animation, as the reading writes it: by default the hero's 400 ms rise at load."""
    rec = {
        "kind": "CSSAnimation",
        "name": "rise",
        "selector": "h1.rise",
        "pseudo": "",
        "text": "Tide tables you can trust",
        "box": [40, 568, 461, 110],
        "duration": 400,
        "iterations": 1,
        "delay": 0,
        "easings": [["linear", 0.0], ["cubic-bezier(0.2, 0, 0, 1)", 0.4127]],
        "props": ["opacity", "transform"],
        "seen": "load",
        "scroll_driven": False,
        "progress": None,
    }
    rec.update(kw)
    return rec


def _drift(**kw) -> dict:
    """A scroll-driven animation (a scroll timeline): no duration in time, progress per scroll step."""
    rec = dict(
        name="drift",
        selector="div.hero-art",
        text="",
        box=[1160, 160, 240, 160],
        duration=None,
        easings=[["linear", 0.0], ["linear", 0.0]],
        props=["scale", "translate"],
        scroll_driven=True,
        progress=[0.171, 0.3, 0.45, 0.6, 0.75, 0.9, 1, 1],
    )
    rec.update(kw)
    return _a11_anim(**rec)


def _fb(sel: str, result: str) -> dict:
    changes = [] if result in ("none", "covered") else [
        ["self", "background-color", "rgb(14, 92, 99)", "rgb(10, 70, 76)"]
    ]
    return {
        "selector": sel,
        "text": sel.split(".")[-1],
        "box": [40, 773, 200, 47],
        "result": result,
        "changes": changes,
    }


def _a11_reading(anims=(), feedback=(), smooth=(), vw=1440, vh=900) -> dict:
    return {
        "vw": vw,
        "vh": vh,
        "window_ms": 3000,
        "steps": 8,
        "anims": list(anims),
        "feedback": list(feedback),
        "smooth": list(smooth),
    }


def _a11_rows(normal, reduced, width="1440x900") -> dict:
    rows = bi.score_a11d(normal, reduced, width)
    assert [(r["bar"], r["check"], r["width"]) for r in rows] == [
        ("A11", c, width) for c in A11_ROWS
    ]
    return {r["check"]: r for r in rows}


@A11D
def test_a11d_checks_and_sets():
    assert bi.VERSION == 4
    assert bi.FIXTURE_SETS == ("bar-interact-v1", "bar-interact-v2", "bar-interact-a11-v1")
    assert [(b, c) for b, c, _ in bi.A11_CHECKS] == [("A11", c) for c in A11_ROWS]
    assert bi.covered(KEY) == {(b, c) for b, c, _ in bi.CHECKS + bi.SPEED_CHECKS}
    assert bi.covered(A11_KEY) == {("A11", c) for c in A11_ROWS}


@A11D
def test_a11d_signature_cases():
    def sig(*anims, width="1440x900", vw=1440, vh=900):
        return _a11_rows(
            _a11_reading(anims, vw=vw, vh=vh), _a11_reading(vw=vw, vh=vh), width
        )["motion-signature"]

    r = sig(_a11_anim())
    assert (r["value"], r["pass"]) == (1, True)
    assert r["evidence"] == [
        {
            "selector": "h1.rise",
            "text": "Tide tables you can trust",
            "box": [40, 568, 461, 110],
            "property": "opacity, transform",
            "value": "animation rise 400 ms, load",
        }
    ]
    assert (sig()["value"], sig()["pass"]) == (0, False)
    # On an element of the first screen: its box overlaps the first viewport by more than 0.
    assert sig(_a11_anim(box=[40, 1058, 437, 114]))["value"] == 0
    assert sig(_a11_anim(box=[40, 899, 437, 114]))["value"] == 1
    assert sig(_a11_anim(box=[40, 900, 437, 114]))["value"] == 0
    assert sig(_a11_anim(box=[1440, 100, 50, 50]))["value"] == 0
    assert sig(_a11_anim(box=[0, 0, 0, 0]))["value"] == 0
    small = sig(_a11_anim(box=[20, 860, 350, 92]), width="390x844", vw=390, vh=844)
    assert small["value"] == 0 and small["width"] == "390x844"
    # It changes transform, translate, scale, rotate, opacity, clip-path or offset.
    for prop in ("transform", "translate", "scale", "rotate", "opacity", "clip-path"):
        assert sig(_a11_anim(props=[prop]))["value"] == 1, prop
    for prop in ("offset", "offset-path", "offset-distance", "offset-rotate"):
        assert sig(_a11_anim(props=[prop]))["value"] == 1, prop
    for prop in ("color", "background-color", "filter", "box-shadow", "width", "top"):
        assert sig(_a11_anim(props=[prop]))["value"] == 0, prop
    # It starts within 3 s of load, or as the first 2 screens are scrolled.
    assert sig(_a11_anim(seen="load-late"))["value"] == 0
    reveal = _a11_anim(kind="CSSTransition", name="transform", props=["transform"])
    assert sig(dict(reveal, seen="scroll3"))["value"] == 1
    assert sig(dict(reveal, seen="scroll3"))["evidence"][0]["value"] == (
        "transition transform 400 ms, scroll step 3"
    )
    assert sig(dict(reveal, seen="hover-press"))["value"] == 0
    assert sig(dict(reveal, seen="end"))["value"] == 0
    # It lasts 120 ms or more: its active duration (infinite counts).
    assert sig(_a11_anim(duration=110))["value"] == 0
    assert sig(_a11_anim(duration=120))["value"] == 1
    assert sig(_a11_anim(duration=60, iterations=2))["value"] == 1
    assert sig(_a11_anim(duration=100, iterations="infinite"))["value"] == 1
    # Scroll-linked: a scroll-driven animation whose progress moves with the scroll.
    r = sig(_drift())
    assert (r["value"], r["evidence"][0]["value"]) == (1, "animation drift, scroll-linked")
    assert sig(_drift(progress=[1] * 8))["value"] == 0
    assert sig(_drift(progress=None))["value"] == 0
    assert sig(_drift(box=[40, 1058, 437, 114]))["value"] == 0
    assert sig(_a11_anim(), _drift(), reveal)["value"] == 2


@A11D
def test_a11d_timing_cases():
    def timing(*anims):
        return _a11_rows(_a11_reading(anims), _a11_reading())["motion-timing"]

    ok = timing(_a11_anim(), _a11_anim(duration=120), _a11_anim(duration=500))
    assert (ok["value"], ok["pass"], ok["evidence"]) == (0, True, [])
    for ms in (110, 520, 800):
        assert (timing(_a11_anim(duration=ms))["value"], timing(_a11_anim(duration=ms))["pass"]) == (1, False), ms
    assert timing(_a11_anim(duration=110))["evidence"][0]["value"] == (
        "animation 110 ms cubic-bezier(0.2, 0, 0, 1): under 120 ms"
    )
    # Linear: every timing function that applies is on the diagonal (within 0.001).
    lin = timing(_a11_anim(easings=[["linear", 0.0], ["linear", 0.0]]))
    assert (lin["value"], lin["evidence"][0]["property"], lin["evidence"][0]["value"]) == (
        1,
        "rise",
        "animation 400 ms linear: linear timing",
    )
    flat = [["linear", 0.0], ["cubic-bezier(0.3, 0.3, 0.7, 0.7)", 0.0004]]
    assert timing(_a11_anim(easings=flat))["value"] == 1
    assert timing(_a11_anim(easings=[["linear", 0.0], ["steps(4, end)", 0.2]]))["value"] == 0
    # A CSS transition's timing function is on its effect.
    tr = _a11_anim(
        kind="CSSTransition",
        name="background-color",
        selector="a.btn",
        easings=[["cubic-bezier(0, 0, 0.58, 1)", 0.2],["linear", 0.0]],
        props=["background-color"],
        duration=800,
        seen="hover-press",
    )
    ev = timing(tr)["evidence"][0]
    assert (ev["selector"], ev["property"], ev["value"]) == (
        "a.btn",
        "background-color",
        "transition 800 ms cubic-bezier(0, 0, 0.58, 1): over 500 ms",
    )
    both = timing(dict(tr, easings=[["linear", 0.0], ["linear", 0.0]]))["evidence"][0]
    assert both["value"] == "transition 800 ms linear: over 500 ms, linear timing"
    # Infinite loops longer than 1000 ms are exempt; a loop of exactly 1000 ms is not.
    assert timing(_a11_anim(duration=1100, iterations="infinite"))["value"] == 0
    assert timing(_a11_anim(duration=1100, iterations="infinite", easings=[["linear", 0.0]]))["value"] == 0
    loop = timing(_a11_anim(name="pulse", duration=1000, iterations="infinite"))
    assert loop["value"] == 1
    assert loop["evidence"][0]["value"] == (
        "animation 1000 ms cubic-bezier(0.2, 0, 0, 1), infinite: over 500 ms"
    )
    assert timing(_a11_anim(duration=600, iterations="infinite"))["value"] == 1
    assert timing(_a11_anim(duration=1100, iterations=3))["value"] == 1
    # Delays are not counted; 0 s means none; a scroll-driven animation has no duration in time.
    assert timing(_a11_anim(delay=2000, duration=300))["value"] == 0
    assert timing(_a11_anim(duration=0))["value"] == 0
    assert timing(_drift())["value"] == 0
    # Every animation of the normal reading counts, wherever it is and however it starts.
    far = _a11_anim(box=[40, 3000, 100, 100], seen="end", props=["color"], duration=900)
    assert timing(far)["value"] == 1
    six = timing(*[_a11_anim(name=f"a{i}", duration=900) for i in range(6)])
    assert (six["value"], len(six["evidence"])) == (6, 5)
    # The reduced reading is not read here.
    assert _a11_rows(_a11_reading(), _a11_reading([_a11_anim(duration=900)]))[
        "motion-timing"
    ]["pass"] is True


@A11D
def test_a11d_linear_is_every_timing_function_on_the_diagonal():
    assert bi.is_linear([["linear", 0.0]])
    assert bi.is_linear([["linear", 0.0], ["cubic-bezier(0.3, 0.3, 0.7, 0.7)", 0.001]])
    assert not bi.is_linear([["linear", 0.0], ["ease", 0.0912]])
    assert not bi.is_linear([["linear", 0.0], ["linear", 0.0011]])


@A11D
def test_a11d_reduced_cases():
    def red(*anims, smooth=()):
        return _a11_rows(
            _a11_reading([_a11_anim()]), _a11_reading(anims, smooth=smooth)
        )["motion-reduced"]

    assert (red()["value"], red()["pass"], red()["evidence"]) == (0, True, [])
    r = red(_a11_anim())
    assert (r["value"], r["pass"]) == (1, False)
    assert (r["evidence"][0]["property"], r["evidence"][0]["value"]) == (
        "transform",
        "animation rise 400 ms",
    )
    moves = (
        "transform", "translate", "scale", "rotate", "offset", "offset-distance",
        "top", "left", "inset", "inset-inline-start", "margin-top", "width", "max-height",
        "min-width", "block-size", "background-position", "background-position-x",
        "object-position",
    )
    for prop in moves:
        assert red(_a11_anim(props=[prop]))["value"] == 1, prop
    for prop in ("opacity", "color", "background-color", "filter", "box-shadow", "clip-path"):
        assert red(_a11_anim(props=[prop]))["value"] == 0, prop
    # Under one frame (17 ms) nothing is drawn between start and end.
    assert red(_a11_anim(duration=0.01))["value"] == 0
    assert red(_a11_anim(duration=16.9))["value"] == 0
    assert red(_a11_anim(duration=17))["value"] == 1
    assert red(_a11_anim(duration=0.01, iterations="infinite"))["value"] == 0
    # A scroll-driven one moves when its progress is not the same after every step.
    assert red(_drift())["value"] == 1
    assert red(_drift(progress=[0] * 8))["value"] == 0
    s = red(smooth=[{"selector": "html", "text": "", "box": [0, 0, 1440, 2400]}])
    assert (s["value"], s["evidence"][0]["property"], s["evidence"][0]["value"]) == (
        1,
        "scroll-behavior",
        "smooth",
    )
    assert red(_a11_anim(), _drift(), smooth=[{"selector": "html", "text": "", "box": [0, 0, 1, 1]}])["value"] == 3
    # The normal reading is not read here.
    assert _a11_rows(_a11_reading([_a11_anim()]), _a11_reading())["motion-reduced"]["pass"] is True


@A11D
def test_a11d_feedback_cases():
    def fb(*items):
        return _a11_rows(_a11_reading([_a11_anim()], feedback=items), _a11_reading())[
            "motion-feedback"
        ]

    r = fb(_fb("a.btn", "hover"), _fb("input.email", "press"))
    assert (r["value"], r["pass"], r["evidence"]) == (0, True, [])
    many = [_fb(f"a.n{i}", "none") for i in range(7)] + [
        _fb("a.skip", "covered"),
        _fb("a.ok", "hover"),
    ]
    r = fb(*many)
    assert (r["value"], r["pass"], len(r["evidence"])) == (8, False, 8)
    assert r["evidence"][0] == {
        "selector": "a.n0",
        "text": "n0",
        "box": [40, 773, 200, 47],
        "property": "feedback",
        "value": "no change on hover or press",
    }
    assert (r["evidence"][-1]["selector"], r["evidence"][-1]["value"]) == ("a.skip", "covered")
    assert (fb()["value"], fb()["pass"]) == (0, True)


@A11D
def test_a11d_a_failed_reading_could_not_measure():
    rows = _a11_rows({"error": "TimeoutError: boom"}, _a11_reading())
    assert [rows[c]["pass"] for c in A11_ROWS] == [None, None, None, True]
    assert rows["motion-signature"]["evidence"] == [
        {
            "selector": "",
            "text": "error: TimeoutError: boom",
            "box": [0, 0, 0, 0],
            "property": "",
            "value": "",
        }
    ]
    rows = _a11_rows(_a11_reading([_a11_anim()]), {"error": "TimeoutError: boom"})
    assert [rows[c]["pass"] for c in A11_ROWS] == [True, True, True, None]
    rows = _a11_rows(None, None)
    assert [rows[c]["pass"] for c in A11_ROWS] == [None] * 4


@A11D
def test_a11d_rows_come_last_and_older_raw_files_have_none():
    old = json.loads((FIX / "raw" / "clean.json").read_text())
    before = bi.score(old)
    assert not any(r["bar"] == "A11" for r in before["rows"])
    assert "A11" not in bi.to_md(before)
    raw = json.loads(json.dumps(old))
    raw["version"] = 4
    for width in A11_WIDTHS:
        vw, vh = (int(v) for v in width.split("x"))
        raw["phases"][width]["a11d"] = _a11_reading(
            [_a11_anim()], [_fb("a.btn", "hover")], vw=vw, vh=vh
        )
        raw["phases"][width]["a11d_reduced"] = _a11_reading(vw=vw, vh=vh)
    doc = bi.score(raw)
    n = 2 * len(bi.CHECKS) + len(bi.SPEED_CHECKS)
    assert len(doc["rows"]) == n + 8 and doc["version"] == 4
    assert doc["rows"][:n] == before["rows"]
    assert [(r["bar"], r["check"], r["width"]) for r in doc["rows"][n:]] == [
        ("A11", c, w) for c in A11_ROWS for w in A11_WIDTHS
    ]
    assert all(r["pass"] is True for r in doc["rows"][n:])
    for r in doc["rows"][n:]:
        for e in r["evidence"]:
            assert set(e) == {"selector", "text", "box", "property", "value"}
    assert bi.tally(doc)["bars"]["A11"] == "met"
    cls = next(r for r in doc["rows"] if r["check"] == "cls")
    md = bi.to_md(doc)
    assert "- A11 (d): met\n" in md
    assert (
        f"  - A8 cls 412x823, next to (d): {cls['value']} ({bi.OUTCOME[cls['pass']]})\n" in md
    )
    raw["phases"]["390x844"]["a11d"]["anims"] = []
    md = bi.to_md(bi.score(raw))
    assert "- A11 (d): not met (motion-signature 390x844)\n" in md
    # A version 4 raw file with no readings could not measure them.
    del raw["phases"]["1440x900"]["a11d"]
    rows = {(r["check"], r["width"]): r for r in bi.score(raw)["rows"]}
    assert rows[("motion-signature", "1440x900")]["pass"] is None
    assert rows[("motion-reduced", "1440x900")]["pass"] is True


@A11D
@pytest.mark.parametrize("page", sorted(A11_KEY["pages"]))
def test_a11d_recorded_raw_scores_to_the_key(page):
    raw = json.loads((A11 / "raw" / (page.rsplit(".", 1)[0] + ".json")).read_text())
    assert raw["version"] == 4 and raw["page"] == f"bar-interact-a11-v1/{page}"
    cov = bi.covered(A11_KEY)
    rows = [r for r in bi.score(raw)["rows"] if (r["bar"], r["check"]) in cov]
    assert len(rows) == 8 and all(r["pass"] is not None for r in rows)
    got = {(r["bar"], r["check"], r["width"]) for r in rows if r["pass"] is not True}
    assert got == {tuple(x) for x in A11_KEY["pages"][page]["failing"]}


@A11D
def test_a11d_fixture_proof_from_the_recorded_raw_files(tmp_path, capsys):
    out = tmp_path / "all"
    code = bi.main(["--fixture-proof", "--from-raw", str(FIX.parent), "--out", str(out)])
    proof = json.loads((out / "fixture-proof.json").read_text())
    assert code == 0 and proof["all_match"] is True
    assert (proof["match"], len(proof["pages"])) == (34, 34)
    assert [p["set"] for p in proof["pages"]].count("bar-interact-a11-v1") == 15
    assert "fixture proof: 34/34 pages match, 0 differ, 0 could not measure" in (
        capsys.readouterr().out
    )
    one = tmp_path / "a11"
    args = ["--fixture-proof", "--from-raw", str(FIX.parent), "--out", str(one)]
    code = bi.main(args + ["--set", "bar-interact-a11-v1"])
    proof = json.loads((one / "fixture-proof.json").read_text())
    assert code == 0 and (proof["match"], len(proof["pages"])) == (15, 15)
    assert {p["set"] for p in proof["pages"]} == {"bar-interact-a11-v1"}
