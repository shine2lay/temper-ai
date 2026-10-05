"""Model-free contracts for the HTML->Penpot converter's rich details (Design queue #31).

A recorded browser scene of configs/design/testpages/html-fixtures/rich.html (tests/design_rich_scenes/,
390 and 1440 px) stands in for the browser. It holds what real designed pages use and the converter
used to lose: real text inside aria-hidden step circles, half-circle ticket notches, a rounded arch
with no bottom border, layered backgrounds, a radial-gradient dot texture, and dashed, dotted and
double borders. The live proofs (fidelity against the browser, the real editor) are evidence in
Design's results folder (~/design-lab/results/converter-rich/), not unit tests.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
SCENES = Path(__file__).resolve().parent / "design_rich_scenes"
sys.path.insert(0, str(BIN))

_spec = importlib.util.spec_from_file_location("html_to_penpot", BIN / "html_to_penpot.py")
h2p = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h2p)

WIDTHS = (390, 1440)


def scenes():
    return {w: json.loads((SCENES / f"scene-{w}.json").read_text()) for w in WIDTHS}


@pytest.fixture(scope="module")
def built():
    recorded = scenes()
    fonts = h2p.Fonts()
    for scene in recorded.values():
        for f in scene["fonts"]:
            fonts.add(f["family"], int(float(f["weight"])), f["style"],
                      "11111111-1111-4111-8111-" + str(len(fonts.faces)).zfill(12))
    media = {}
    for scene in recorded.values():
        for n in h2p.walk_scene(scene["nodes"]):
            for fill in n.get("fills", []):
                if fill.get("type") == "image":
                    media[fill["src"]] = {"id": "22222222-2222-4222-8222-222222222222", "width": 10, "height": 10,
                                          "mtype": "image/png", "name": "background-texture.png"}
    b = h2p.build(recorded, "file", "page", fonts, media, "Rich")
    b["by_id"] = {o["id"]: o for o in b["objects"]}
    adds = [c for chunk in b["chunks"] for c in chunk["changes"] if c["type"] == "add-obj"]
    b["kids"] = {}
    for c in adds:  # each board's :shapes, in the order they are added
        b["kids"].setdefault(c["parent-id"], []).append(c["id"])
    return b


def named(b, name):
    return [o for o in b["objects"] if o["name"] == name]


def ancestors(b, o):
    out, cur = [], b["by_id"].get(o.get("parent-id"))
    while cur is not None:
        out.append(cur)
        cur = b["by_id"].get(cur.get("parent-id"))
    return out


def on_page(b, o):
    return any(a["id"] in {x["id"] for x in b["boards"]} for a in ancestors(b, o))


def strokes(o):
    return [(s["stroke-style"], s["stroke-width"], s["stroke-alignment"]) for s in o.get("strokes", [])]


def test_scenes_record_the_rich_details_and_their_textures():
    for w, scene in scenes().items():
        assert scene["width"] == w and scene["version"] == 2
        assert [t["key"].split("-")[1].split("x")[0] for t in scene["textures"]] == [str(w)] * 2
        srcs = {f["src"] for n in h2p.walk_scene(scene["nodes"]) for f in n.get("fills", []) if f.get("type") == "image"}
        assert srcs == {t["key"] + ".png" for t in scene["textures"]}


def test_text_inside_aria_hidden_step_circles_is_drawn_above_the_route_line(built):
    """aria-hidden hides text from screen readers, not from the screen: the step numbers stay, as live
    text, and the circles holding them paint over the route line drawn behind the tickets."""
    stops = named(built, "Span / stop")
    on_pages = [s for s in stops if on_page(built, s)]
    assert len(on_pages) == 2 * 3  # three tickets at each width
    for stop in stops:
        texts = [built["by_id"][i] for i in built["kids"][stop["id"]]]
        assert [t["type"] for t in texts] == ["text"]
        assert h2p.content_text(texts[0]["content"]).strip() in {"1", "2", "3"}
        assert stop["r1"] == stop["width"] / 2  # a circle
    for line in named(built, "Route line"):
        kids = [built["by_id"][i]["name"] for i in built["kids"][line["id"]]]
        # a layout board paints lower :shapes indexes on top: the tickets (and their stops) over the track
        assert kids == ["Ol / tickets", "Span / track"]


def test_half_circle_notches_and_the_arch_follow_their_rounded_outline(built):
    """Borders on some sides of a rounded box become one path along the rounded outline, never small
    squares or a straight-cornered rectangle."""
    for side, name in (("left", "Border / top right bottom"), ("right", "Border / top bottom left")):
        paths = [p for p in named(built, name) if ancestors(built, p)[0]["name"] == "Span / notch"]
        assert len(paths) == 2 * 3 + 1  # each ticket's notch on that side at both widths, and the component main
        for p in paths:
            assert p["type"] == "path" and "C" in p["content"], side
            assert strokes(p) == [("solid", 3, "center")]
    arches = [p for p in named(built, "Border / top right left") if ancestors(built, p)[0]["name"] == "Closing arch"]
    assert len(arches) == 2
    for p in arches:
        assert "C" in p["content"] and strokes(p) == [("solid", 3, "center")]
        arch = ancestors(built, p)[0]
        assert arch["r1"] == arch["r2"] > 100 and arch["r3"] == arch["r4"] == 0
        assert not arch.get("strokes")  # the outline is the path, not a square-cornered stroke


def test_radii_larger_than_the_box_shrink_like_css(built):
    """CSS shrinks overlapping corner radii by one factor; the converter sends the used radii."""
    arch390 = next(o for o in named(built, "Closing arch") if o["width"] < 400)
    assert arch390["r1"] == arch390["width"] / 2  # 180px + 180px on a 350px box -> 175 each
    for proof in (p for p in named(built, "Proof") if on_page(built, p)):
        assert proof["r1"] == proof["r2"] and proof["r3"] == proof["r4"]
        assert proof["r1"] + proof["r4"] <= proof["height"] + 0.5  # 12rem + 1.5rem shrunk to fit the side (box snapped)
        assert proof["r1"] / proof["r4"] == pytest.approx(8, rel=0.01)  # the proportion stays


def test_layered_backgrounds_keep_every_layer_in_css_order(built):
    """Hero: radial glow (native) over tiled grid lines (picture) over a base gradient (native)."""
    for hero in named(built, "Section / Hero"):
        assert [f["fill-color-gradient"]["type"] for f in hero["fills"]] == ["linear"]
        kids = [built["by_id"][i] for i in built["kids"][hero["id"]]]
        assert [k["name"] for k in kids] == ["Div / wrap", "Background layers", "Background texture (raster)"]
        glow, texture = kids[1], kids[2]
        assert [f["fill-color-gradient"]["type"] for f in glow["fills"]] == ["radial"]
        assert ["fill-image" in f for f in texture["fills"]] == [True]
        for layer in (glow, texture):
            assert (layer["x"], layer["y"], layer["width"], layer["height"]) == (
                hero["x"], hero["y"], hero["width"], hero["height"])
    for card in named(built, "Paper card"):  # a glow fading to transparent over the paper colour
        glow, paper = card["fills"]
        stops = glow["fill-color-gradient"]["stops"]
        assert glow["fill-color-gradient"]["type"] == "radial"
        assert [(s["color"], s["opacity"]) for s in stops] == [("#FFFDF7", 1), ("#FFFDF7", 0)]  # not grey
        assert paper["fill-color"] == "#F6EBD6"


def test_textures_are_named_picture_fills_and_each_is_an_issue(built):
    """A dot pattern Penpot can't draw is the browser's own drawing of that background, named as such
    and listed as an issue: never a flat colour or a wrong approximation."""
    textures = named(built, "Background texture (raster)")
    assert len(textures) == 2 * 2
    assert sorted(ancestors(built, t)[0]["name"] for t in textures) == ["Section / Fares"] * 2 + ["Section / Hero"] * 2
    kinds = [i["kind"] for i in built["issues"]]
    assert kinds.count("background-rasterized") == len(textures)
    for fares in named(built, "Section / Fares"):
        assert [f.get("fill-color") for f in fares["fills"]] == ["#F2B33D"]  # the colour under the dots stays native


def test_dashed_dotted_and_double_borders_are_native_strokes(built):
    kinds = [i["kind"] for i in built["issues"]]
    assert "border-style-approximated" not in kinds and "background-unsupported" not in kinds
    for box in named(built, "Price list"):  # four equal dashed sides: the box's own stroke
        assert strokes(box) == [("dashed", 2, "inner")]
    heads = [p for p in named(built, "Border / bottom") if ancestors(built, p)[0]["name"] == "Div / ticket-head"]
    assert heads and all(strokes(p) == [("dashed", 2, "center")] for p in heads)
    steps = [p for p in named(built, "Border / left") if ancestors(built, p)[0]["name"] == "Span / step-line"]
    assert steps and all(strokes(p) == [("dashed", 3, "center")] for p in steps)
    leaders = [p for p in named(built, "Border / bottom") if ancestors(built, p)[0]["name"] == "Span / leader"]
    assert len(leaders) == 2 * 3 and all(strokes(p) == [("dotted", 2, "center")] for p in leaders)
    marks = [p for p in named(built, "Border / bottom") if ancestors(built, p)[0]["name"] == "P / fine"]
    assert len(marks) == 2 and all(strokes(p) == [("dotted", 2, "center")] for p in marks)  # an inline word
    for stamp in (s for s in named(built, "Stamp") if s["type"] == "frame"):  # a double ring: outer line on the box, inner line as a layer
        assert strokes(stamp) == [("solid", 2, "inner")]
        inner = [built["by_id"][i] for i in built["kids"][stamp["id"]] if built["by_id"][i]["name"] == "Border / double (inner line)"]
        assert len(inner) == 1 and strokes(inner[0]) == [("solid", 2, "inner")]
        assert inner[0]["width"] == stamp["width"] - 8 and inner[0]["r1"] == stamp["r1"] - 4
    for fares in named(built, "Section / Fares"):  # double top and bottom sides: two lines each
        lines = sorted(built["by_id"][i]["name"] for i in built["kids"][fares["id"]] if built["by_id"][i]["name"].startswith("Border"))
        assert lines == ["Border / bottom (inner line)", "Border / bottom (outer line)",
                         "Border / top (inner line)", "Border / top (outer line)"]
        assert all(built["by_id"][i]["height"] == 2 for i in built["kids"][fares["id"]]
                   if built["by_id"][i]["name"].startswith("Border"))


def test_painted_boxes_on_the_pages_sit_on_whole_pixels(built):
    """Chrome paints box edges on whole pixels; Penpot would draw half-tone seams at fractional ones."""
    painted = [o for o in built["objects"] if o["type"] in ("rect", "frame") and (o.get("fills") or o.get("strokes"))
               and on_page(built, o)]
    assert len(painted) > 40
    for o in painted:
        for v in (o["x"], o["y"], o["x"] + o["width"], o["y"] + o["height"]):
            assert v == pytest.approx(round(v), abs=1e-6), o["name"]


def test_textures_are_read_only_from_the_capture_folder(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
    (tmp_path / "tex-390x700-64b0249b.png").write_bytes(png)
    issues = []
    ok = h2p.read_texture("tex-390x700-64b0249b.png", tmp_path, issues)
    assert ok["ok"] and ok["data"] == png and ok["mtype"] == "image/png" and not issues
    for src in ("../secret.png", "/etc/passwd", "tex-missing.png"):
        assert not h2p.read_texture(src, tmp_path, issues)["ok"]
    assert [i["kind"] for i in issues] == ["texture-missing"] * 3
