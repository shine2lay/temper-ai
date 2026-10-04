"""Model-free contracts for carrying a page's CSS layout into Penpot layouts (penpot_layout.py).

Small hand-made scenes in the shape html_dom_extract.js records (boxes, layout facts, item
facts) stand in for the browser. Each test checks the Penpot layout chosen for them and that
the plan reflows like the page: texts grow, boards hug, and anything Penpot can't say stays
positioned and is reported. The live proofs (real Penpot, real editor) are evidence in Design's
results folder, not unit tests.
"""
import copy
import importlib.util
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[1] / "configs/design/bin"
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pl = _load("penpot_layout")
h2p = _load("html_to_penpot")


def board(name, x, y, w, h, children=(), display="block", pad=(0, 0, 0, 0), item=None, extra=None, **layout):
    return {"kind": "board", "name": name, "box": {"x": x, "y": y, "w": w, "h": h}, "z": 0,
            "fills": [], "strokes": [], "radius": [0, 0, 0, 0], "shadows": [], "opacity": 1,
            "layout": {"display": display, "pad": list(pad), **layout},
            "item": {"pos": "static", "grow": 0, "shrink": 1, "basis": "auto", "margin": [0, 0, 0, 0],
                     "nat": {"w": w, "h": h}, **(item or {})},
            "children": list(children), **(extra or {})}


STYLE = {"family": "Figtree", "weight": "400", "style": "normal", "size": 16, "lineHeight": 20, "color": "#111111"}


def text(name, x, y, w, h, fit="height", align="left", lines=None):
    return {"kind": "text", "name": name, "box": {"x": x, "y": y, "w": w, "h": h}, "z": 0, "fit": fit,
            "text": {"align": align, "plain": name, "paragraphs": [[{"text": name, "style": STYLE}]],
                     "lines": lines or [{"x": x, "y": y, "w": w, "h": h, "p": 0, "l": 0, "text": name}]},
            "item": {"pos": "static", "grow": 0, "shrink": 1, "basis": "auto", "margin": [0, 0, 0, 0],
                     "nat": {"w": w, "h": h}}}


def card(name, x, w, body_h, h=None):
    """A flex column card: 16 px padding, a 28 px title and a body text, 12 px apart; flex: 1."""
    nat_h = 16 + 28 + 12 + body_h + 16
    kids = [text(f"{name} title", x + 16, 16, w - 32, 28), text(f"{name} body", x + 16, 56, w - 32, body_h)]
    return board(name, x, 0, w, h or nat_h, kids, "flex", (16, 16, 16, 16), dir="column", wrap="nowrap",
                 gap=[12, 0], justify="normal", alignItems="normal", alignContent="normal",
                 item={"grow": 1, "basis": "0%", "nat": {"w": w, "h": nat_h}})


def sizing(n):
    it = n["pp"]["item"]
    return it["layout-item-h-sizing"], it["layout-item-v-sizing"]


def test_flex_row_keeps_direction_gap_padding_and_alignment():
    logo, links = board("Logo", 24, 20, 80, 24), board("Links", 216, 12, 160, 40)
    nav = board("Nav", 0, 0, 400, 64, [logo, links], "flex", (12, 24, 12, 24), dir="row", wrap="nowrap",
                gap=[0, 16], justify="space-between", alignItems="center", alignContent="normal")
    pl.plan_tree(nav)
    pp = nav["pp"]
    assert (pp["mode"], pp["kind"], pp["why"]) == ("flex", "flex row", None)
    a = pp["attrs"]
    assert (a["layout-flex-dir"], a["layout-wrap-type"]) == ("row", "nowrap")
    assert a["layout-gap"] == {"row-gap": 0, "column-gap": 16}
    assert a["layout-padding"] == {"p1": 12, "p2": 24, "p3": 12, "p4": 24}
    assert (a["layout-justify-content"], a["layout-align-items"]) == ("space-between", "center")
    assert pp["order"] == [logo, links]
    assert pp["hug"] == [None, 64]  # its height comes from its content, its width from the page
    assert sizing(logo) == sizing(links) == ("fix", "fix")


def test_wrapping_row_wraps_in_penpot_and_one_line_labels_grow_sideways():
    tags = [text(f"Tag {i}", x, y, 80, 24, fit="width") for i, (x, y) in enumerate([(0, 0), (88, 0), (0, 32)])]
    row = board("Tags", 0, 0, 200, 56, tags, "flex", dir="row", wrap="wrap", gap=[8, 8],
                justify="normal", alignItems="normal", alignContent="normal")
    pl.plan_tree(row)
    a = row["pp"]["attrs"]
    assert row["pp"]["kind"] == "flex row" and a["layout-wrap-type"] == "wrap"
    assert a["layout-gap"] == {"row-gap": 8, "column-gap": 8}
    for t in tags:
        assert t["pp"]["grow"] == "auto-width" and sizing(t) == ("auto", "auto")
        assert "layout-item-align-self" not in t["pp"]["item"]
    assert row["pp"]["hug"][1] == 56
    assert row["pp"]["content"] == [168, 56]  # its widest line, not every tag on one line


def test_text_plan_grows_paragraphs_down_and_labels_sideways():
    para = pl.text_plan(text("Body", 10, 20, 300, 47.6, align="center"))
    assert para["grow"] == "auto-height"
    assert para["box"] == [9, 20, 302, 48] and para["delta"] == [1, 0, 1, para["box"][3] - 47.6]
    label = pl.text_plan(text("Label", 10, 20, 60.4, 18, fit="width"))
    assert label["grow"] == "auto-width" and label["box"] == [10, 20, 61, 18]
    # one line in a wider block keeps the block's width and grows downwards
    wide = pl.text_plan(text("Heading", 0, 0, 300, 30, fit="width", lines=[{"x": 0, "y": 0, "w": 120, "h": 30}]))
    assert wide["grow"] == "auto-height"


def test_text_box_is_its_css_line_boxes_not_its_glyph_boxes():
    """Display type overflows a tight line-height (Fraunces 76 px at 1.02) and body text underfills a loose
    one; Penpot re-measures by line boxes, so a box made from glyph boxes would jump when edited."""
    h1 = text("H1", 120, 175.64, 686.66, 248.03, lines=[
        {"x": 120, "y": 268.64, "w": 600, "h": 93}, {"x": 120, "y": 346.16, "w": 650, "h": 93},
        {"x": 120, "y": 423.67, "w": 300, "h": 93}, {"x": 420, "y": 423.67, "w": 200, "h": 93}])
    h1["text"]["lineHeight"] = 77.52
    top, height = pl.line_boxes(h1)
    assert top == pytest.approx(183.38, abs=0.01) and height == pytest.approx(232.55, abs=0.01)  # the h1's own box: 183.64, 232.55
    plan = pl.text_plan(h1)
    assert plan["box"] == pytest.approx([120, top, 688.66, 233])
    assert plan["delta"] == pytest.approx([0, 0, 2, 0.45], abs=0.01)  # glyph overflow is not a margin
    body = text("Body", 148, 1021.56, 328, 44.8, lines=[{"x": 148, "y": 1041.56, "w": 320, "h": 20},
                                                         {"x": 148, "y": 1066.36, "w": 150, "h": 20}])
    body["text"]["lineHeight"] = 24.8
    assert pl.line_boxes(body) == pytest.approx((1019.16, 49.6), abs=0.01)


def test_a_label_that_wraps_in_the_browser_grows_down_not_sideways():
    label = text("Get the notes", 0, 0, 60, 39, fit="width", lines=[
        {"x": 0, "y": 19.5, "w": 30, "h": 19.5}, {"x": 0, "y": 39, "w": 60, "h": 19.5}])
    label["item"]["anon"] = True
    assert pl.text_plan(label)["grow"] == "auto-height"  # auto-width never wraps: the button would widen


def test_text_overrides_say_which_part_changed_so_penpot_keeps_them():
    def para(words, size="16"):
        return {"type": "root", "children": [{"type": "paragraph-set", "children": [
            {"type": "paragraph", "font-size": size, "children": [{"text": words, "font-size": size}]}]}]}
    assert h2p.text_diff(para("Ridge"), para("Ridge")) == set()
    assert h2p.text_diff(para("The quiet coast"), para("Ridge")) == {"text-content-text"}
    assert h2p.text_diff(para("Ridge", "18"), para("Ridge")) == {"text-content-attribute"}
    assert h2p.text_diff(para("Ridge", "16.00001"), para("Ridge")) == set()
    two = para("Ridge")
    two["children"][0]["children"].append(para("loop")["children"][0]["children"][0])
    assert h2p.text_diff(two, para("Ridge")) == {"text-content-structure"}


def test_card_column_texts_fill_the_width_and_the_card_hugs_them():
    c = card("Card", 0, 300, 48)
    pl.plan_tree(c)
    pp = c["pp"]
    assert pp["kind"] == "flex column" and pp["attrs"]["layout-gap"]["row-gap"] == 12
    assert pp["hug"][1] == 120  # 16 + 28 + 12 + 48 + 16: a longer body makes the card taller
    for t in c["children"]:
        assert t["pp"]["grow"] == "auto-height" and sizing(t) == ("fill", "auto")
        assert t["pp"]["item"]["layout-item-margin"]["m2"] == -2  # keeps task #5's wrap slack inside the card


def test_in_a_row_of_stretched_cards_the_tallest_hugs_and_the_rest_fill():
    """Penpot passes a text's growth up only through boards that hug, so the card that sets the
    row's height (the tallest, as in CSS) hugs and its stretched siblings fill."""
    a, b = card("Card A", 0, 300, 48), card("Card B", 316, 300, 24, h=120)
    row = board("Cards", 0, 0, 616, 120, [a, b], "flex", dir="row", wrap="nowrap", gap=[0, 16],
                justify="normal", alignItems="normal", alignContent="normal")
    pl.plan_tree(row)
    assert row["pp"]["kind"] == "flex row" and row["pp"]["hug"][1] == 120
    assert sizing(a) == ("fill", "auto") and sizing(b) == ("fill", "fill")
    assert a["pp"]["item"]["layout-item-min-w"] == b["pp"]["item"]["layout-item-min-w"] == 32  # flex: 1 from its padding
    assert a["pp"]["hug"][1] == 120 and b["pp"]["hug"][1] is None


def test_an_icon_svg_keeps_its_box_through_margins_around_its_paths():
    """Penpot sizes a group by its paths (26 px inside a 30 px svg); the margins keep the browser's
    spacing, so Penpot's own layout puts the label where the browser did."""
    icon = {"kind": "group", "name": "SVG / compass", "box": {"x": 0, "y": 0, "w": 30, "h": 30}, "z": 0,
            "item": {"pos": "static", "grow": 0, "shrink": 0, "basis": "auto", "margin": [0, 0, 0, 0]},
            "children": [{"kind": "path", "name": "Ring", "box": {"x": 2, "y": 2, "w": 26, "h": 26}, "d": "M2 2L28 28"}]}
    label = text("Atlas", 40, 5, 60, 20, fit="width")
    row = board("Wordmark", 0, 0, 100, 30, [icon, label], "flex", dir="row", wrap="nowrap", gap=[10, 10],
                justify="normal", alignItems="center", alignContent="normal")
    pl.plan_tree(row)
    assert row["pp"]["kind"] == "flex row" and row["pp"]["hug"] == [100, 30]
    assert icon["pp"]["box"] == [2, 2, 26, 26]
    assert icon["pp"]["item"]["layout-item-margin"] == {"m1": 2, "m2": 2, "m3": 2, "m4": 2}


def test_a_block_held_at_its_max_width_fills_its_row_up_to_it():
    """blockquote { max-width: 22em } beside an icon: CSS shrinks it with a narrower row, so it
    fills up to its max-width instead of keeping a fixed 880 px that would stick out."""
    icon = board("Icon", 0, 40, 120, 120)
    quote = board("Blockquote", 168, 0, 880, 200, item={"maxW": 880})
    row = board("Quote", 0, 0, 1200, 200, [icon, quote], "flex", dir="row", wrap="nowrap", gap=[48, 48],
                justify="normal", alignItems="center", alignContent="normal")
    pl.plan_tree(row)
    assert row["pp"]["kind"] == "flex row" and sizing(icon) == ("fix", "fix")
    assert sizing(quote)[0] == "fill" and quote["pp"]["item"]["layout-item-max-w"] == 880


def test_css_grid_becomes_a_penpot_grid_with_its_tracks_and_cells():
    a = board("A", 0, 0, 200, 100, item={"nat": {"w": 200, "h": 60}})
    b = board("B", 216, 0, 200, 100)
    grid = board("Grid", 0, 0, 416, 100, [a, b], "grid", gap=[16, 16], cols=[200, 200], rows=[100],
                 colsSpec="repeat(2, minmax(0, 1fr))", rowsSpec="none", autoRows="auto",
                 justify="normal", alignItems="normal", alignContent="normal")
    pl.plan_tree(grid)
    pp = grid["pp"]
    assert (pp["mode"], pp["kind"], pp["why"], pp["notes"]) == ("grid", "grid", None, [])
    assert pp["attrs"]["layout-grid-columns"] == [{"type": "flex", "value": 1}] * 2
    assert pp["attrs"]["layout-grid-rows"] == [{"type": "auto", "value": 1}]
    assert pp["attrs"]["layout-gap"] == {"row-gap": 16, "column-gap": 16}
    assert [(c["child"]["name"], c["row"], c["column"]) for c in pp["cells"]] == [("A", 1, 1), ("B", 1, 2)]
    assert sizing(a) == ("fill", "fill") and sizing(b) == ("fill", "fix")  # the auto row keeps one item that sets it
    assert pp["hug"][1] == 100


def test_grid_track_lists_map_to_penpot_tracks_or_refuse():
    assert pl.parse_tracks("200px 1fr 25%", 3) == [{"type": "fixed", "value": 200}, {"type": "flex", "value": 1},
                                                   {"type": "percent", "value": 25}]
    assert pl.parse_tracks("repeat(auto-fit, minmax(220px, 1fr))", 4) == [{"type": "flex", "value": 1}] * 4
    assert pl.parse_tracks("[full-start] minmax(1rem, 1fr) [content-start] 60ch", 2) is None  # ch: not a Penpot track
    assert pl.parse_tracks("repeat(2, 1fr)", 3) is None and pl.parse_tracks("var(--cols)", 2) is None


def test_layout_penpot_cannot_express_stays_positioned_and_is_reported():
    a, b = board("A", 0, 0, 100, 100), board("B", 50, 50, 100, 100)
    box = board("Overlap", 0, 0, 150, 150, [a, b])
    pl.plan_tree(box)
    assert (box["pp"]["mode"], box["pp"]["kind"]) == (None, "positioned")
    assert "children overlap" in box["pp"]["why"]
    out = pl.summary({390: {"nodes": [box]}}, {390: {"kind": "flex column"}})
    assert out["widths"][390]["positioned"] == 1
    assert out["fallbacks"] == [{"width": 390, "board": "Overlap", "mapped": "positioned", "why": box["pp"]["why"]}]


def test_unsupported_flex_direction_falls_back_to_a_measured_row_and_says_why():
    a, b = board("A", 120, 0, 100, 40), board("B", 0, 0, 100, 40)
    row = board("Reversed", 0, 0, 220, 40, [a, b], "flex", dir="row-reverse", wrap="nowrap", gap=[0, 20],
                justify="normal", alignItems="normal", alignContent="normal")
    pl.plan_tree(row)
    assert row["pp"]["kind"] == "row (measured)" and row["pp"]["order"] == [b, a]
    assert "flex-direction row-reverse" in row["pp"]["why"]


def test_reopened_json_keys_come_back_as_penpot_names():
    got = h2p.p.kebab({"layoutItemHSizing": "fill", "layoutItemVSizing": "auto", "fillColorRefId": "c",
                       "layoutGridCells": {"d6e78769-4453-804d-8008-bc7e5d0ab42d": {"rowSpan": 1}}})
    assert got == {"layout-item-h-sizing": "fill", "layout-item-v-sizing": "auto", "fill-color-ref-id": "c",
                   "layout-grid-cells": {"d6e78769-4453-804d-8008-bc7e5d0ab42d": {"row-span": 1}}}


def scene(nodes, w=400, h=300):
    return {"width": w, "height": h, "background": [], "vars": [], "fonts": [], "nodes": nodes,
            "body": {"box": {"x": 0, "y": 0, "w": w, "h": h}, "layout": {"display": "block", "pad": [0, 0, 0, 0]}}}


def button(color):
    return board("Button", 24, 24, 120, 40, extra={"component": "Button",
                                                   "fills": [{"type": "color", "color": color, "opacity": 1}]})


def test_states_become_a_penpot_variant_set_and_fallbacks_are_issues():
    btn = button("#2255AA")
    btn["states"] = {"Hover": button("#113377")}
    overlap = board("Overlap", 0, 100, 150, 150, [board("A", 0, 100, 100, 100), board("B", 50, 150, 100, 100)])
    b = h2p.build({400: scene([btn, overlap])}, "file", "page", h2p.Fonts(), {}, "Test")
    by_id = {o["id"]: o for o in b["objects"]}
    [box] = [o for o in b["objects"] if o.get("is-variant-container")]
    assert box["name"] == "Components / Button" and box["layout"] == "flex"
    mains = [o for o in b["objects"] if o.get("variant-id") == box["id"]]
    assert [(o["name"], o["variant-name"], o["main-instance"]) for o in mains] == [
        ("Components / Button", "Default", True), ("Components / Button", "Hover", True)]
    assert box["shapes"] == [mains[1]["id"], mains[0]["id"]]  # a flex layout lists its first item last
    added = [c for chunk in b["chunks"] for c in chunk["changes"] if c["type"] == "add-component"]
    assert [(c["path"], c["name"], c["variant-id"], c["variant-properties"]) for c in added] == [
        ("Components", "Button", box["id"], [{"name": "State", "value": "Default"}]),
        ("Components", "Button", box["id"], [{"name": "State", "value": "Hover"}])]
    assert b["layout"]["variants"] == [{"name": "Button", "container": box["id"], "states": ["Default", "Hover"],
                                        "components": {"Default": added[0]["id"], "Hover": added[1]["id"]}}]
    [copy_root] = [o for o in b["objects"] if o.get("component-root") and not o.get("main-instance")]
    assert copy_root["component-id"] == added[0]["id"] and by_id[copy_root["shape-ref"]] is mains[0]
    issue = [i for i in b["issues"] if i["kind"] == "layout-positioned"]
    assert issue and issue[0]["where"] == "Overlap (400 px)" and "children overlap" in issue[0]["detail"]
    page = [o for o in b["objects"] if o["name"] == "Test — 400"][0]
    assert (page["layout"], page["layout-item-h-sizing"], page["layout-item-v-sizing"]) == ("flex", "fix", "auto")


def test_component_copies_link_by_place_and_mark_layout_overrides():
    wide, narrow = button("#2255AA"), button("#2255AA")
    for n, d in ((wide, "row"), (narrow, "column")):
        n["children"] = [text("Label", 40, 34, 60, 20, fit="width"), board("Icon", 108, 34, 16, 16)]
        if d == "column":  # the narrow page stacks the icon under the label
            n["box"].update(w=96, h=58)
            n["children"][1]["box"].update(x=40, y=56)
            n["item"]["nat"] = {"w": 96, "h": 58}
        n["layout"].update(display="flex", pad=[10, 16, 10, 16], dir=d, wrap="nowrap", gap=[2, 8] if d == "column" else [0, 8],
                           justify="normal", alignItems="flex-start", alignContent="normal")
    b = h2p.build({1440: scene([wide], 1440), 390: scene([copy.deepcopy(narrow)], 390)}, "file", "page", h2p.Fonts(), {}, "T")
    by_id = {o["id"]: o for o in b["objects"]}
    [main] = [o for o in b["objects"] if o.get("main-instance")]
    copies = [o for o in b["objects"] if o.get("component-root") and not o.get("main-instance")]
    assert len(copies) == 2
    for root in copies:
        kids = [o for o in b["objects"] if o.get("parent-id") == root["id"]]
        assert {by_id[k["shape-ref"]]["name"] for k in kids} == {"Label", "Icon"}
        assert all(by_id[k["shape-ref"]]["name"] == k["name"] for k in kids)  # linked by place, not by list order
    narrow_root = [r for r in copies if r["layout-flex-dir"] == "column"][0]
    assert "layout-flex-dir" in narrow_root["touched"] and main["layout-flex-dir"] == "row"


def test_a_copy_with_other_words_marks_its_words_as_its_own():
    a, b = button("#2255AA"), button("#2255AA")
    b["box"]["y"] = 100
    for n, words in ((a, "Browse routes"), (b, "Read the journal")):
        n["layout"].update(display="flex", pad=[10, 16, 10, 16], dir="row", wrap="nowrap", gap=[0, 0],
                           justify="normal", alignItems="flex-start", alignContent="normal")
        n["children"] = [text(words, 40, n["box"]["y"] + 10, 88, 20, fit="width")]
    b = h2p.build({400: scene([a, b])}, "file", "page", h2p.Fonts(), {}, "T")
    [other] = [o for o in b["objects"] if o["type"] == "text" and o["name"] == "Read the journal"]
    assert {"content-group", "text-content-text"} <= set(other["touched"])


def test_a_copy_whose_label_wraps_keeps_growing_downwards():
    """The main's label sits on one line (auto-width); a narrow copy's wraps (auto-height). Unless the
    copy says so, Penpot's sync hands it the main's auto-width and the button widens."""
    wide, narrow = button("#2255AA"), button("#2255AA")
    narrow["box"].update(w=80, h=59)
    narrow["item"]["nat"] = {"w": 80, "h": 59}
    for n, lines in ((wide, [{"x": 40, "y": 54, "w": 88, "h": 20, "p": 0, "l": 0, "text": "Get the notes"}]),
                     (narrow, [{"x": 40, "y": 54, "w": 48, "h": 20, "p": 0, "l": 0, "text": "Get the"},
                               {"x": 40, "y": 73.5, "w": 40, "h": 20, "p": 0, "l": 0, "text": "notes"}])):
        n["layout"].update(display="flex", pad=[10, 16, 10, 16], dir="row", wrap="nowrap", gap=[0, 0],
                           justify="normal", alignItems="flex-start", alignContent="normal")
        w, h = (88, 20) if n is wide else (48, 39)
        n["children"] = [text("Get the notes", 40, 34, w, h, fit="width", lines=lines)]
        n["children"][0]["item"]["anon"] = True
        n["children"][0]["text"]["lineHeight"] = 20 if n is wide else 19.5
    b = h2p.build({1440: scene([wide], 1440), 390: scene([narrow], 390)}, "file", "page", h2p.Fonts(), {}, "T")
    grows = {o.get("grow-type"): o for o in b["objects"] if o["type"] == "text" and o.get("shape-ref")}
    assert set(grows) == {"auto-width", "auto-height"}
    assert "text-font-group" in grows["auto-height"]["touched"] and "text-font-group" not in grows["auto-width"].get("touched", [])


def test_display_type_overflowing_its_line_height_adds_no_margins():
    """A logo set at line-height 1 draws glyphs 5.5 px past its 48 px line box on both sides. CSS lays it
    out by the line box; margins made from the overflow would make Penpot's header 11 px taller."""
    # a glyph fragment's y is its bottom, as the extractor reports it (Penpot's position-data)
    logo = text("Morrow", 0, -5.5, 200, 59, fit="width", lines=[{"x": 0, "y": 53.5, "w": 200, "h": 59}])
    logo["text"]["lineHeight"] = 48
    head = board("Header", 0, 0, 400, 48, [logo], "flex", dir="row", wrap="nowrap", gap=[0, 0],
                 justify="normal", alignItems="normal", alignContent="normal")
    pl.plan_tree(head)
    assert logo["pp"]["box"] == [0, 0, 200, 48]
    assert logo["pp"]["item"]["layout-item-margin"] == {"m1": 0, "m2": 0, "m3": 0, "m4": 0}
    assert head["pp"]["hug"][1] == 48 and head["pp"]["content"][1] == 48


def test_boards_hugging_labels_in_measured_layouts_are_as_wide_as_in_the_browser():
    """Penpot sizes a label's box in whole pixels. In a measured layout its margins give the excess back,
    so a board hugging labels is the browser's size; else the excess adds up along a row of them, the
    row can't hug, keeps a fixed width and its labels pile up when the page narrows (Morrow C's specs)."""
    def spec(name, x, w):
        return board(f"Li {name}", x, 0, w, 20, [text(name, x, 0, w, 20, fit="width")])
    specs = [spec("12 people", 0, 60.3), spec("$45 / hour example", 72.3, 118.6), spec("Projector", 202.9, 61.4)]
    ul = board("Specs", 0, 0, 264.3, 20, specs)
    pl.plan_tree(ul)
    for s in specs:
        label = s["children"][0]
        assert s["pp"]["kind"] == "column (measured)" and label["pp"]["grow"] == "auto-width"
        assert label["pp"]["item"]["layout-item-margin"]["m2"] == pytest.approx(-label["pp"]["delta"][2])
        assert s["pp"]["hug"] == pytest.approx([s["box"]["w"], 20])
    assert ul["pp"]["kind"] == "row (measured)" and ul["pp"]["hug"] == pytest.approx([264.3, 20])
    assert all(sizing(s) == ("auto", "auto") for s in specs)


def test_penpot_keeps_a_filling_board_whole_only_where_it_does():
    """Penpot's minimum for a filling board with a layout (min_size_layout): in a grid cell its content,
    in a flex row its min-width (only a grid board keeps its content there). The browser let A
    (min-width: 0) shrink below its 200 px label: two flex: 1 boards in a row convert as they are;
    in a grid Penpot would widen A's column, so the boards keep the browser's sizes."""
    def boards():
        label = text("Unbreakable", 0, 0, 200, 20, fit="width")
        a = board("A", 0, 0, 150, 20, [label], "flex", dir="row", wrap="nowrap", gap=[0, 0], justify="normal",
                  alignItems="normal", alignContent="normal", item={"grow": 1, "basis": "0%", "minW": 0})
        return a, board("B", 150, 0, 150, 20, item={"grow": 1, "basis": "0%", "minW": 0})
    a, b = boards()
    row = board("Row", 0, 0, 300, 20, [a, b], "flex", dir="row", wrap="nowrap", gap=[0, 0],
                justify="normal", alignItems="normal", alignContent="normal")
    pl.plan_tree(row)
    assert a["pp"]["content"] == [200, 20]
    assert row["pp"]["kind"] == "flex row" and sizing(a)[0] == sizing(b)[0] == "fill"
    a, b = boards()
    grid = board("Grid", 0, 0, 300, 20, [a, b], "grid", gap=[0, 0], cols=[150, 150], rows=[20],
                 colsSpec="minmax(0, 1fr) minmax(0, 1fr)", rowsSpec="none", autoRows="auto",
                 justify="normal", alignItems="normal", alignContent="normal")
    pl.plan_tree(grid)
    assert grid["pp"]["kind"] != "grid" and "grid: A would land at" in grid["pp"]["why"]
    assert sizing(a)[0] == "fix"


def test_layers_kept_in_place_follow_their_board_when_it_is_resized():
    """Borders and badges are positioned: constraints keep a top border spanning the board, a right
    border on the right edge and full height, and a corner badge in its corner."""
    body = text("Body", 16, 16, 300, 20)
    top = {"kind": "rect", "name": "Border / top", "box": {"x": 0, "y": 0, "w": 400, "h": 1}, "deco": "over", "z": 0}
    right = {"kind": "rect", "name": "Border / right", "box": {"x": 399, "y": 0, "w": 1, "h": 200}, "deco": "over", "z": 0}
    badge = board("Badge", 370, 10, 30, 20, item={"pos": "absolute"})
    dot = board("Dot", 0, 50, 10, 10, item={"pos": "absolute"})
    sec = board("Section", 0, 0, 400, 200, [body, top, right, badge, dot], "flex", (16, 16, 164, 16), dir="column",
                wrap="nowrap", gap=[0, 0], justify="normal", alignItems="normal", alignContent="normal")
    pl.plan_tree(sec)
    assert sec["pp"]["mode"] == "flex"
    item = {n["name"]: n["pp"]["item"] for n in (top, right, badge, dot)}
    assert all(i["layout-item-absolute"] for i in item.values())
    assert (item["Border / top"]["constraints-h"], item["Border / top"].get("constraints-v")) == ("leftright", None)
    assert (item["Border / right"]["constraints-h"], item["Border / right"]["constraints-v"]) == ("right", "topbottom")
    assert (item["Badge"]["constraints-h"], item["Badge"].get("constraints-v")) == ("right", None)
    assert "constraints-h" not in item["Dot"] and "constraints-v" not in item["Dot"]
    # in a board Penpot can't lay out, every layer keeps its place the same way
    a, b = board("A", 0, 0, 100, 100), board("B", 50, 50, 100, 100)
    box = board("Overlap", 0, 0, 150, 150, [a, b])
    built = h2p.build({400: scene([box])}, "file", "page", h2p.Fonts(), {}, "T")
    [b_obj] = [o for o in built["objects"] if o["name"] == "B"]
    assert (b_obj["constraints-h"], b_obj["constraints-v"]) == ("right", "bottom")
    assert "layout-item-h-sizing" not in b_obj


def test_a_one_line_text_with_room_to_spare_wraps_when_its_row_narrows():
    """CSS wraps a shrinkable text's words when its row gets narrower; an auto-width text in Penpot
    never wraps and would stick out. With room to spare it fills up to today's width and grows down;
    one word, or white-space: nowrap, can't wrap and keeps growing sideways."""
    note = text("Example rates and illustrative terms", 0, 0, 300, 20, fit="width")
    word = text("Rates", 312, 0, 40, 20, fit="width")
    fixed = text("Kept on one line", 364, 0, 120, 20, fit="width")
    fixed["text"]["nowrap"] = True
    row = board("Foot", 0, 0, 600, 20, [note, word, fixed], "flex", dir="row", wrap="nowrap", gap=[0, 12],
                justify="normal", alignItems="normal", alignContent="normal")
    pl.plan_tree(row)
    assert row["pp"]["kind"] == "flex row"
    assert note["pp"]["grow"] == "auto-height" and sizing(note)[0] == "fill"
    assert note["pp"]["box"] == [0, 0, 302, 20] and note["pp"]["item"]["layout-item-max-w"] == 302
    assert note["pp"]["item"]["layout-item-margin"]["m2"] == -2  # the slack stays inside its 300 px
    for t in (word, fixed):
        assert t["pp"]["grow"] == "auto-width" and sizing(t) == ("auto", "auto")


def test_a_block_held_at_its_max_width_in_a_grid_column_narrows_with_it():
    """An intro capped at 40ch in a minmax(0, 1fr) column: a fixed width would keep Penpot's flexible
    track from narrowing, so it fills its cell up to the cap."""
    h2 = board("H2", 0, 0, 603.08, 100)
    intro = board("Intro", 623.08, 0, 300, 100, item={"maxW": 300})
    grid = board("Head", 0, 0, 1000, 100, [h2, intro], "grid", gap=[20, 20], cols=[603.08, 376.92], rows=[100],
                 colsSpec="minmax(0, 1.6fr) minmax(0, 1fr)", rowsSpec="none", autoRows="auto",
                 justify="normal", alignItems="normal", alignContent="normal")
    pl.plan_tree(grid)
    assert grid["pp"]["kind"] == "grid"
    assert sizing(intro)[0] == "fill" and intro["pp"]["item"]["layout-item-max-w"] == 300
    [cell] = [c for c in grid["pp"]["cells"] if c["child"] is intro]
    assert (cell["column"], cell["justify-self"]) == (2, "auto")


def test_a_label_box_with_room_to_spare_narrows_with_its_row_and_its_words_wrap():
    """A dd around its words in a row with room to spare: CSS narrows the box and wraps the words
    when the row narrows. In Penpot the box fills up to today's width, its text fills the box and
    grows down, and only the box's padding still holds it wide."""
    term = text("Seats", 0, 0, 40, 20, fit="width")
    words = text("Up to twelve people", 52, 0, 200, 20, fit="width")
    dd = board("Dd", 52, 0, 200, 20, [words])
    row = board("Spec", 0, 0, 400, 20, [term, dd], "flex", dir="row", wrap="nowrap", gap=[0, 12],
                justify="normal", alignItems="normal", alignContent="normal")
    pl.plan_tree(row)
    assert row["pp"]["kind"] == "flex row"
    assert sizing(dd)[0] == "fill" and dd["pp"]["item"]["layout-item-max-w"] == 200
    assert words["pp"]["grow"] == "auto-height" and sizing(words)[0] == "fill"
    assert words["pp"]["box"] == [52, 0, 202, 20] and words["pp"]["item"]["layout-item-margin"]["m2"] == -2
    assert dd["pp"]["content"][0] == 0
    assert term["pp"]["grow"] == "auto-width" and sizing(term) == ("auto", "auto")  # one word can't wrap


def test_a_box_fitted_to_its_content_in_a_flex_column_fills_up_to_its_width():
    """In a flex column that doesn't stretch its items, a box with width auto is as wide as its
    content, at most the column's: in Penpot it fills up to today's width and its words wrap."""
    words = text("Free cancellation up to a day before", 0, 0, 260, 20, fit="width")
    note = board("Note", 0, 0, 260, 20, [words])
    head = text("Terms", 0, 32, 50, 20, fit="width")
    col = board("Terms", 0, 0, 400, 52, [note, head], "flex", dir="column", wrap="nowrap", gap=[12, 0],
                justify="normal", alignItems="flex-start", alignContent="normal")
    pl.plan_tree(col)
    assert col["pp"]["kind"] == "flex column"
    assert sizing(note)[0] == "fill" and note["pp"]["item"]["layout-item-max-w"] == 260
    assert words["pp"]["grow"] == "auto-height" and sizing(words)[0] == "fill"
    assert head["pp"]["grow"] == "auto-width"


def test_items_narrower_than_their_grid_column_fill_up_to_their_width():
    """Grid items at the start of a wider column (justify-self: start) are as wide as their content,
    at most the column's: a wrappable text and a box fill up to today's width, so a narrower column
    narrows them and their words wrap."""
    note = text("Seats and tables move", 0, 0, 180, 20, fit="width")
    words = text("Projector and screen", 320, 0, 150, 20, fit="width")
    kit = board("Kit", 320, 0, 150, 20, [words])
    grid = board("Specs", 0, 0, 620, 20, [note, kit], "grid", gap=[0, 20], cols=[300, 300], rows=[20],
                 colsSpec="minmax(0, 1fr) minmax(0, 1fr)", rowsSpec="none", autoRows="auto",
                 justify="normal", justifyItems="start", alignItems="normal", alignContent="normal")
    pl.plan_tree(grid)
    assert grid["pp"]["kind"] == "grid"
    assert note["pp"]["grow"] == "auto-height" and sizing(note)[0] == "fill"
    assert note["pp"]["item"]["layout-item-max-w"] == 182
    assert sizing(kit)[0] == "fill" and kit["pp"]["item"]["layout-item-max-w"] == 150
    assert words["pp"]["grow"] == "auto-height" and sizing(words)[0] == "fill"


def test_layers_of_a_board_with_no_flow_children_follow_it_when_it_is_resized():
    """A dotted leader is a span drawn only by its bottom border: nothing to lay out, but the border
    spans the span and stays at its bottom when a layout resizes it."""
    rule = {"kind": "rect", "name": "Border / bottom", "box": {"x": 100, "y": 18, "w": 200, "h": 2},
            "deco": "over", "z": 0}
    leader = board("Leader", 100, 0, 200, 20, [rule])
    pl.plan_tree(leader)
    assert leader["pp"]["kind"] == "no flow children"
    assert rule["pp"]["item"] == {"constraints-h": "leftright", "constraints-v": "bottom"}


def test_a_badge_hung_past_its_card_follows_that_edge_and_the_card_keeps_room_for_it():
    """Seat badges hang past their table's right edge, centred on it (right: -116px; top:
    calc(50% - 44px)), and each table is held at its max-width with room after it for the badge.
    The badge keeps to the table's right edge and centre; the room stays when the column narrows."""
    # a max-width the browser reports in px, or a calc() with % it doesn't (then: fitted to content)
    for known in ({"maxW": 1192, "wspec": "100%"}, {}):
        name = text("Atlas", 76, 56, 120, 40, fit="width")
        badge = board("Badge", 1280, 100, 88, 88, item={"pos": "absolute"})
        table = board("Room table", 60, 40, 1192, 208, [name, badge], "flex", (16, 16, 16, 16), dir="column",
                      wrap="nowrap", gap=[0, 0], justify="normal", alignItems="flex-start",
                      alignContent="normal", item=known)
        tables = board("Tables", 60, 40, 1320, 208, [table], "flex", dir="column", wrap="nowrap", gap=[44, 0],
                       justify="normal", alignItems="flex-start", alignContent="normal")
        pl.plan_tree(tables)
        assert tables["pp"]["kind"] == "flex column"
        item = table["pp"]["item"]
        assert sizing(table)[0] == "fill" and item["layout-item-max-w"] == 1192
        assert item["layout-item-margin"]["m2"] == 116  # the badge's room: a narrower column narrows the table
        assert badge["pp"]["item"]["layout-item-absolute"]
        assert (badge["pp"]["item"]["constraints-h"], badge["pp"]["item"]["constraints-v"]) == ("right", "center")


def test_baseline_aligned_items_in_a_wrapping_row_keep_their_offsets():
    """align-items: baseline has no Penpot twin: each item keeps its offset from its line's top as a
    margin, so a short tag still sits on the heading's baseline."""
    h2 = board("H2", 0, 0, 380, 72)
    tag = text("Compare", 730, 45.7, 70, 20, fit="width")
    row = board("Board top", 0, 0, 800, 72, [h2, tag], "flex", dir="row", wrap="wrap", gap=[8, 24],
                justify="space-between", alignItems="baseline", alignContent="normal")
    pl.plan_tree(row)
    assert row["pp"]["kind"] == "flex row" and row["pp"]["attrs"]["layout-wrap-type"] == "wrap"
    assert tag["pp"]["item"]["layout-item-margin"]["m1"] == pytest.approx(45.7)
    assert h2["pp"]["item"]["layout-item-margin"]["m1"] == 0


def test_space_around_and_space_evenly_rows_keep_their_spacing():
    """Penpot spaces these as CSS does (half a share at the ends for space-around, equal gaps for
    space-evenly), so the rows convert as they are and keep sharing out a wider board."""
    m = (365.33 - 2 * 63.36) / 2 / 2
    chairs = [board("Chair", 16 + m, 0, 63.36, 34), board("Chair", 16 + 3 * m + 63.36, 0, 63.36, 34)]
    around = board("Chairs", 0, 0, 397.33, 34, chairs, "flex", (0, 16, 0, 16), dir="row", wrap="nowrap",
                   gap=[0, 0], justify="space-around", alignItems="normal", alignContent="normal")
    dots = [board("Dot", x, 0, 40, 40) for x in (45, 130, 215)]
    evenly = board("Dots", 0, 0, 300, 40, dots, "flex", dir="row", wrap="nowrap", gap=[0, 0],
                   justify="space-evenly", alignItems="normal", alignContent="normal")
    for row, justify in ((around, "space-around"), (evenly, "space-evenly")):
        pl.plan_tree(row)
        assert (row["pp"]["kind"], row["pp"]["why"]) == ("flex row", None)
        assert row["pp"]["attrs"]["layout-justify-content"] == justify


def test_a_wrapping_text_is_as_wide_as_penpot_needs_to_break_its_lines_like_the_browser():
    """Penpot breaks text like CSS break-spaces: the space at a line's end takes room (the browser
    drops it) and a word comes up once it fits with its own space. The box width is picked between
    those limits, as near the browser's as it can be (Morrow A's kicker and terms note, measured live)."""
    kicker = text("Now showing", 42, 235.89, 276.48, 51.2)
    kicker["text"]["wrap"] = [{"w": 276.48, "k": "space", "sp": 11.53, "fw": 34.56, "fsp": 11.55},
                              {"w": 241.92, "k": "end", "sp": 0, "fw": 57.61, "fsp": 11.53}]
    plan = pl.text_plan(kicker)
    assert plan["box"][2] == pytest.approx(276.48 + 11.53 + pl.WRAP_MARGIN)  # 'DEMO ' still fits its line
    assert plan["delta"][2] == pytest.approx(11.53 + pl.WRAP_MARGIN) and "rewrap" not in plan
    centred = copy.deepcopy(kicker)
    centred["text"]["align"] = "center"
    assert pl.text_plan(centred)["box"][0] == pytest.approx(42 - (11.53 + pl.WRAP_MARGIN) / 2)
    terms = text("A real venue", 47, 3482.73, 300, 76.8)
    terms["text"]["wrap"] = [{"w": 268.81, "k": "space", "sp": 9.61, "fw": 9.61, "fsp": 9.61},
                             {"w": 211.2, "k": "space", "sp": 9.61, "fw": 38.41, "fsp": 9.63},
                             {"w": 76.81, "k": "end", "sp": 0, "fw": 76.81, "fsp": None}]
    plan = pl.text_plan(terms)
    # 'booking.' ends the paragraph, so it needs no space after it: in a 297.62 px box it comes up
    assert plan["box"][2] == pytest.approx(211.2 + 9.61 + 76.81 - pl.WRAP_MARGIN)
    assert plan["delta"][2] < 0  # narrower than the browser's block; its margin keeps the block's place
    wide = copy.deepcopy(terms)
    wide["box"]["w"] = 290  # a width that already breaks both ways like the browser is kept as it is
    assert pl.text_plan(wide)["box"][2] == 290


def test_a_text_no_width_can_break_like_the_browser_is_flagged_and_reported():
    tight = text("Tight", 0, 0, 100, 40)
    tight["text"]["wrap"] = [{"w": 98, "k": "space", "sp": 8, "fw": 20, "fsp": 8},   # needs 106 px
                             {"w": 60, "k": "space", "sp": 8, "fw": 30, "fsp": None},  # 'end' comes up at 98 px
                             {"w": 30, "k": "end", "sp": 0, "fw": 30, "fsp": None}]
    plan = pl.text_plan(tight)
    assert plan["rewrap"] is True and plan["box"][2] == pytest.approx(106 + pl.WRAP_MARGIN / 2)
    tight["pp"] = plan
    out = pl.summary({390: {"nodes": [tight]}}, {390: {"kind": "flex column"}})
    assert [(n["width"], n["board"]) for n in out["notes"]] == [(390, "Tight")]
    assert pl.wrap_width({"align": "left"}, 100) is None  # no facts (older scenes): task #5's slack


def test_grid_fractions_below_one_keep_their_css_shares_in_penpot():
    """Penpot shares a grid's free space by sum(max(1, fr)) (grid layout_data), so 0.9fr and 0.95fr
    tracks would leave space unused: the tracks are scaled until the smallest is 1fr, same ratios."""
    spec = "minmax(0px, 2fr) minmax(0px, 0.9fr) minmax(0px, 1.3fr) minmax(0px, 0.95fr) minmax(0px, 1.25fr)"
    tracks = pl.parse_tracks(spec, 5)
    values = [t["value"] for t in tracks]
    assert min(values) == 1 and values[0] / values[1] == pytest.approx(2 / 0.9, abs=1e-3)
    sizes = pl._tracks_px(tracks, 1244, 24, [], False, "stretch")
    assert sizes == pytest.approx([358.75, 161.44, 233.19, 170.41, 224.22], abs=0.02)  # the browser's columns
    unscaled = [{"type": "flex", "value": v} for v in (2, 0.9, 1.3, 0.95, 1.25)]
    assert sum(pl._tracks_px(unscaled, 1244, 24, [], False, "stretch")) < 1244 - 4 * 24 - 20  # Penpot's own sharing
    assert pl.parse_tracks("0.3fr 0.3fr", 2) == [{"type": "flex", "value": 0.3}] * 2  # CSS leaves space too: kept
