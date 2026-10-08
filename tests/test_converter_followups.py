"""Offline #43 contracts; fictional geometry, no browser/account/network dependency.

DOM helper tests execute the production JavaScript with minimal computed-style doubles.
Live native exports and real-editor proofs are separate private evidence, not unit mocks.
"""
import copy
import importlib
import json
import subprocess
from pathlib import Path

import pytest

from tests.test_design_homepage_v2 import FakePenpot
from tests.test_penpot_layout import BIN, STYLE, board, h2p, pl, text

# Fixture imports above install BIN on sys.path before loading the public helper.
editor = importlib.import_module("penpot_editor_checks")


def curve(fraction=1 / 3, offset=-128 / 3, parent=1320, cap=None):
    samples = [[p, min(fraction * p + offset, cap) if cap is not None else fraction * p + offset]
               for p in (parent * .55, parent * .75, parent, parent * 1.15)]
    return {"parent": parent, "samples": samples, "spec": "calc((100% - 128px) / 3)"}


def test_painted_layout_frames_keep_fractional_dimensions_when_text_is_remeasured():
    # Browser paint can snap, but native layout must retain the CSS content size.
    glyph = {"kind": "board", "box": {"x": 3.25, "y": 10.4, "w": 61.69, "h": 79.83},
             "fills": [{"type": "color", "color": "#223344"}],
             "pp": {"mode": "flex", "item": {"layout-item-h-sizing": "fix", "layout-item-v-sizing": "fix"}}}
    assert h2p.Builder.place(None, glyph, 100, 200) == pytest.approx((103.25, 210.4, 61.69, 79.83))
    assert h2p.Builder.place(None, glyph, 0, 0, root=True) == pytest.approx((3.25, 10.4, 61.69, 79.83))
    decoration = {**glyph, "kind": "rect", "pp": {"item": glyph["pp"]["item"]}}
    assert h2p.Builder.place(None, decoration, 0, 0) == (3, 10, 61, 79)


def test_native_border_paint_is_snapped_but_does_not_change_layout_geometry():
    # Pure builder proof: source paint and native box geometry are separate objects.
    fonts = h2p.Fonts()
    lib = h2p.Library("file-1")
    builder = h2p.Builder("file-1", "page-1", lib, fonts, {})
    builder.begin("Fractional card")
    n = {"box": {"x": 3.25, "y": 10.4, "w": 61.69, "h": 79.83},
         "strokes": [{"color": "#223344", "width": 1}], "pp": {"mode": "flex"}}
    frame = h2p.p.shape("frame", "Card", h2p.p.ROOT, h2p.p.ROOT, 3.25, 10.4, 61.69, 79.83, [])
    frame.update(strokes=[{"stroke-color": "#223344", "stroke-width": 1}], r1=8)
    before = {k: frame[k] for k in ("x", "y", "width", "height")}
    builder.border_paint(frame, n, 0, 0, (0,))
    border = builder.objects[0]
    assert {k: frame[k] for k in before} == before
    assert "strokes" not in frame
    assert tuple(border[k] for k in ("x", "y", "width", "height")) == (3, 10, 62, 80)
    assert border["r1"] == 8 and border["strokes"][0]["stroke-width"] == 1
    assert border["parent-id"] == frame["id"]
    assert border["layout-item-absolute"] is True
    assert border["constraints-h"] == "leftright" and border["constraints-v"] == "topbottom"
    assert builder.paths[border["id"]] == (0, "border-paint")
    assert builder.exact[border["id"]]["width"] == 61.69
    # A native copy at whole pixels still needs the same extra layer/path for linking.
    integer = {**n, "box": {"x": 3, "y": 10, "w": 62, "h": 80}}
    other = h2p.p.shape("frame", "Card copy", h2p.p.ROOT, h2p.p.ROOT, 3, 10, 62, 80, [])
    other["strokes"] = [{"stroke-color": "#223344", "stroke-width": 1}]
    builder.border_paint(other, integer, 0, 0, (1,))
    assert len(builder.objects) == 2 and builder.paths[builder.objects[1]["id"]] == (1, "border-paint")
    positioned = {**n, "pp": {"mode": None}}
    other["strokes"] = [{"stroke-width": 1}]
    builder.border_paint(other, positioned, 0, 0, (2,))
    assert len(builder.objects) == 2 and other["strokes"]


def test_fractional_width_is_validated_against_more_than_two_browser_samples():
    assert pl.fluid_width(curve()) == pytest.approx((1 / 3, -128 / 3, None))
    wrong = curve()
    wrong["samples"][2][1] += 12
    assert pl.fluid_width(wrong) is None
    assert pl.fluid_width({"samples": [[100, 30], [200, 60]]}) is None
    assert pl.fluid_width({"samples": [[100, 70], [200, 60], [300, 50]]}) is None


def test_percent_max_width_uses_fractional_fill_tracks_not_fixed_pixel_children():
    c = board("Narrow note", 0, 0, (1320 - 128) / 3, 40,
              item={"maxWidthCurve": curve(), "maxW": (1320 - 128) / 3})
    parent = board("Body", 0, 0, 1320, 40, [c])
    pl.plan_tree(parent)
    wrapper = parent["children"][0]
    assert wrapper["synthetic"] and wrapper["children"][0] is c
    assert wrapper["pp"]["mode"] == "grid", wrapper["pp"]
    tracks = wrapper["pp"]["attrs"]["layout-grid-columns"]
    assert all(t["type"] == "flex" for t in tracks)
    assert tracks[0]["value"] / sum(t["value"] for t in tracks) == pytest.approx(1 / 3)
    assert c["pp"]["item"]["layout-item-h-sizing"] == "fill"
    gutter = wrapper["pp"]["attrs"]["layout-padding"]["p2"]
    assert gutter == pytest.approx(128) and c["item"]["margin"][1] == 0
    # Re-evaluate the same native fill representation after the parent narrows.
    assert pl._tracks_px(tracks, 1000 - gutter, 0, [], False, "stretch")[0] == pytest.approx((1000 - 128) / 3)
    assert wrapper["pp"]["content"][0] < 129  # no percent-track minimum pinned to 1320


@pytest.mark.parametrize("fraction", [1 / 3, 2 / 3, 1])
def test_percent_width_respects_its_active_formula_max_width(fraction):
    c = board("Capped note", 0, 0, fraction * (1320 - 128), 40,
              item={"wspec": "100%", "widthCurve": curve(1, 0),
                    "maxWidthCurve": curve(fraction, -128 * fraction)})
    parent = board("Body", 0, 0, 1320, 40, [c])
    pl.plan_tree(parent)
    wrapper = parent["children"][0]
    assert wrapper.get("synthetic") and wrapper["children"] == [c]
    assert wrapper["pp"]["mode"] == "grid", wrapper["pp"]
    tracks = wrapper["pp"]["attrs"]["layout-grid-columns"]
    assert all(t["type"] == "flex" for t in tracks)
    assert tracks[0]["value"] / sum(t["value"] for t in tracks) == pytest.approx(fraction)
    assert c["pp"]["item"]["layout-item-h-sizing"] == "fill"
    gutter = wrapper["pp"]["attrs"]["layout-padding"]["p2"]
    assert gutter == pytest.approx(128) and c["item"]["margin"][1] == 0
    assert pl._tracks_px(tracks, 1000 - gutter, 0, [], False, "stretch")[0] == pytest.approx(fraction * (1000 - 128))
    if fraction == 1:
        assert len(tracks) == 1  # no spurious minimum-sized remainder track


def test_inactive_max_width_does_not_stretch_an_already_narrower_child():
    c = board("Small note", 0, 0, 120, 40, item={"maxWidthCurve": curve()})
    parent = board("Body", 0, 0, 1320, 40, [c])
    pl._fluid_children(parent)
    assert parent["children"] == [c]


def test_min_formula_cap_and_frozen_viewport_gutter_are_separate_from_parent_width():
    c = curve(1, -115.2, parent=1600, cap=1320)
    # Two samples on a constant cap are required before calling it an upper branch.
    assert pl.fluid_width(c) == pytest.approx((1, -115.2, 1320))
    centred = board("Wrap", 57.6, 0, 1324.8, 40,
                    item={"wspec": "calc(100% - 8vw)", "margin": [0, 57.6, 0, 57.6],
                          "widthCurve": curve(1, -115.2, parent=1440)})
    parent = board("Page", 0, 0, 1440, 40, [centred])
    pl.plan_tree(parent)
    assert centred["pp"]["item"]["layout-item-h-sizing"] == "fill"
    assert centred["pp"]["item"]["layout-item-margin"]["m4"] == pytest.approx(57.6)
    assert centred["pp"]["item"]["layout-item-margin"]["m2"] == pytest.approx(57.6)


def test_spanning_content_contributes_to_intrinsic_flexible_grid_rows():
    tracks = pl.parse_tracks("auto 1fr auto", 3)
    sizes = pl._tracks_px(tracks, 429, 16, [(0, 1, 110), (1, 1, 195), (0, 2, 413)], True, "stretch")
    assert sizes == pytest.approx([110, 287, 0.01])
    # In a definite-height grid the remaining space, not the span, sets 1fr.
    fixed = pl._tracks_px(tracks, 429, 16, [(0, 1, 110), (1, 1, 195), (0, 2, 413)], False, "stretch")
    assert sum(fixed) + 32 == pytest.approx(429)


@pytest.mark.parametrize("specified", [False, True])
def test_multiline_row_label_can_shrink_without_stretching_past_its_source_width(specified):
    icon = board("Choice box", 0, 12, 16, 16)
    label = text("A choice whose explanation wraps", 26, 0, 300, 40, lines=[
        {"x": 26, "y": 0, "w": 300, "h": 20, "p": 0, "l": 0},
        {"x": 26, "y": 20, "w": 210, "h": 20, "p": 0, "l": 1}])
    label["text"]["lineHeight"] = 20
    label["item"]["wspec"] = "300px" if specified else "auto"
    parent = board("Choice", 0, 0, 340, 40, [icon, label], "flex",
                   dir="row", wrap="nowrap", gap=[0, 10], justify="normal",
                   alignItems="center", alignContent="normal")
    pl.plan_tree(parent)
    assert parent["pp"]["kind"] == "flex row", parent["pp"]
    # Exercise the shrink-aware candidate explicitly; the plain candidate may
    # already match this roomy capture without requesting native shrink.
    plan = pl._try_flex(parent, [icon, label], "semantic", shrink_fill=True)
    assert isinstance(plan, dict), plan
    info = next(f for f in plan["infos"] if f["n"] is label)
    assert info["hs"] == ("fix" if specified else "fill")
    if not specified:
        assert info["minmax"]["max-w"] == label["pp"]["box"][2]


def test_auto_left_margin_is_growing_space_and_not_a_frozen_gap():
    left, right = board("Count", 0, 0, 60, 32), board("Action", 320, 0, 80, 32,
                                                         item={"autoMarginLeft": True})
    row = board("Toolbar", 0, 0, 400, 32, [left, right], "flex", dir="row", wrap="nowrap",
                gap=[0, 12], justify="normal", alignItems="normal", alignContent="normal")
    pl.plan_tree(row)
    spacer = next(n for n in row["children"] if n.get("layoutSpacer"))
    assert spacer["box"]["w"] == 236
    assert spacer["pp"]["item"]["layout-item-h-sizing"] == "fill"
    assert row["pp"]["kind"] == "flex row", row["pp"]
    assert not right["item"]["autoMarginLeft"]


@pytest.mark.parametrize("row", [True, False])
def test_zero_cross_size_spacer_keeps_semantic_growing_space(row):
    if row:
        first, last = board("Label", 0, 0, 60, 24), board("Action", 320, 0, 80, 24)
        spacer = board("Empty growing space", 72, 12, 236, 1,
                       item={"grow": 1, "basis": "0%", "minW": 0, "nat": {"w": 236, "h": 0}})
        parent = board("Toolbar", 0, 0, 400, 24, [first, spacer, last], "flex",
                       dir="row", wrap="nowrap", gap=[0, 12], justify="normal",
                       alignItems="center", alignContent="normal")
        main, cross = "h", "v"
    else:
        first, last = board("Label", 0, 0, 24, 60), board("Action", 0, 320, 24, 80)
        spacer = board("Empty growing space", 12, 72, 1, 236,
                       item={"grow": 1, "basis": "0%", "minH": 0, "nat": {"w": 0, "h": 236}})
        parent = board("Stack", 0, 0, 24, 400, [first, spacer, last], "flex",
                       dir="column", wrap="nowrap", gap=[12, 0], justify="normal",
                       alignItems="center", alignContent="normal")
        main, cross = "v", "h"
    spacer["layoutSpacer"] = True
    pl.plan_tree(parent)
    assert parent["pp"]["kind"] == ("flex row" if row else "flex column"), parent["pp"]
    assert spacer["pp"]["item"][f"layout-item-{main}-sizing"] == "fill"
    assert spacer["pp"]["item"][f"layout-item-{cross}-sizing"] == "fix"
    # A genuinely stretched spacer is still allowed to fill its cross axis.
    stretched = copy.deepcopy(spacer)
    stretched["box"]["h" if row else "w"] = 24
    assert pl._stretched(pl._info(stretched, True), row)


@pytest.mark.parametrize("lines", [1, 2])
def test_ellipsis_and_line_clamp_have_fixed_height_but_follow_their_parent_width(lines):
    c = text("Cut text", 0, 0, 300, lines * 20, fit="clip")
    c["text"]["clipped"] = True
    parent = board("Card", 0, 0, 300, lines * 20, [c])
    pl.plan_tree(parent)
    assert c["pp"]["grow"] == "fixed"
    assert c["pp"]["box"] == [0, 0, 300, lines * 20]
    assert c["pp"]["item"]["layout-item-v-sizing"] == "fix"
    assert c["pp"]["item"]["layout-item-h-sizing"] == "fill"


@pytest.mark.parametrize("lines", [1, 2])
def test_cut_text_has_a_real_paint_mask_not_only_fixed_growth(lines):
    t = text("Cut caption", 0, 0, 300, lines * 20, fit="clip")
    t["text"].update(clipped=True, clamp=lines if lines > 1 else 0)
    built = build_scene([t])
    caption = next(o for o in built["objects"] if o["type"] == "text")
    viewport = next(o for o in built["objects"] if o["id"] == caption["parent-id"])
    assert viewport["type"] == "frame" and viewport["show-content"] is False
    assert caption["frame-id"] == viewport["id"] and caption["grow-type"] == "fixed"
    assert viewport["height"] == lines * 20
    assert viewport["layout-item-v-sizing"] == "fix"
    assert caption["constraints-h"] == "leftright"  # width follows the clipped viewport
    assert caption["id"] in built["plain"]
    assert caption["content"]["children"][0]["children"][0]["children"][0]["text"]
    checked = h2p.verify(reopen(built), "page-1", built)["checks"]
    assert checked["all_layers_present"] and checked["types_and_names"]
    assert checked["live_text_equal"] and checked["text_growth_kept"] and checked["layouts_kept"]
    saved = reopen(built)
    saved["data"]["pages-index"]["page-1"]["objects"][viewport["id"]]["show-content"] = True
    lost = h2p.verify(saved, "page-1", built)
    assert not lost["checks"]["layouts_kept"]
    assert any("clipping mask was lost" in failure for failure in lost["problems"]["layout"])


@pytest.mark.parametrize("clamp, height_spec, warned", [(2, None, True), (2, "auto", True),
                                                        (2, "58px", False), (1, None, False)])
def test_rejected_multiline_mapping_falls_back_to_real_fixed_masks_with_explicit_limit(clamp, height_spec, warned):
    t = text("Cut caption", 0, 0, 300, 40, fit="clip")
    t["text"].update(clipped=True, clamp=clamp, clipHeight=40, heightSpec=height_spec)
    built = build_scene([t])
    caption = next(o for o in built["objects"] if o["type"] == "text")
    viewport = next(o for o in built["objects"] if o["id"] == caption["parent-id"])
    assert viewport["show-content"] is False and viewport["height"] == 40
    assert caption["grow-type"] == "fixed" and viewport["layout-item-v-sizing"] == "fix"
    assert caption["constraints-h"] == "leftright" and caption["constraints-v"] == "top"
    assert caption["id"] in built["plain"] and caption.get("position-data")
    assert "layout-item-max-h" not in viewport and "layout" not in viewport
    checked = h2p.verify(reopen(built), "page-1", built)
    assert bool(checked["clipping_limits"]) is warned
    assert any("cannot shrink on widening" in w for w in checked["warnings"]) is warned


@pytest.mark.parametrize("key", ["layout-item-v-sizing", "show-content"])
def test_fixed_clip_mask_and_sizing_are_required_on_fresh_saved_reopen(key):
    # Structural contract only; native edits/widths use the private editor flow.
    t = text("Cut caption", 0, 0, 300, 40, fit="clip")
    t["text"].update(clipped=True, clamp=2, clipHeight=40)
    built = build_scene([t])
    caption = next(o for o in built["objects"] if o["type"] == "text")
    saved = reopen(built)
    viewport = saved["data"]["pages-index"]["page-1"]["objects"][caption["parent-id"]]
    checked = h2p.verify(saved, "page-1", built)
    assert checked["checks"]["layouts_kept"] and checked["checks"]["text_growth_kept"]
    # The page itself also clips. Count the dedicated text viewport separately.
    assert checked["counts"]["clipping_frames"] == 2
    assert sum(o["name"].startswith("Clip / ") for o in built["objects"]) == 1
    viewport.pop(key)
    failed = h2p.verify(saved, "page-1", built)
    assert not failed["checks"]["layouts_kept"]
    assert any(key in message or "clipping mask was lost" in message for message in failed["problems"]["layout"])


def test_wrapping_flex_keeps_wrappable_labels_bounded_in_narrower_viewports():
    a = text("Dispatch status", 0, 0, 200, 20, fit="width")
    b = text("Read the activity log", 300, 0, 200, 20, fit="width")
    parent = board("Footer", 0, 0, 500, 20, [a, b], "flex", dir="row", wrap="wrap",
                   gap=[12, 20], justify="space-between", alignItems="baseline", alignContent="normal")
    # plan_tree installs text plans while visiting a board's children; a leaf
    # on its own is not planned. Initialize those child facts for this direct probe.
    pl._pp(a).update(pl.text_plan(a))
    pl._pp(b).update(pl.text_plan(b))
    plan = pl._try_flex(parent, [a, b], "semantic", text_fill=True)
    assert isinstance(plan, dict)
    assert plan["attrs"]["layout-wrap-type"] == "wrap"
    assert all(f["hs"] == "fill" and f["text"] == "auto-height" for f in plan["infos"])
    assert all(f["minmax"]["max-w"] <= 202 for f in plan["infos"])
    assert plan["attrs"]["layout-gap"]["row-gap"] == 12


@pytest.mark.parametrize("minimum", [None, 0])
def test_zero_min_fractional_cells_allow_fixed_glyph_overflow_without_freezing_the_row(minimum):
    letters = []
    for i, value in enumerate("ABC"):
        t = text("Glyph " + value, i * 40, 0, 40, 20)
        t["text"]["plain"] = value
        for paragraph in t["text"]["paragraphs"]:
            for run in paragraph:
                run["text"] = value
        for line in t["text"]["lines"]:
            line["text"] = value
        letters.append(t)
    c = board("Glyph run", 0, 0, 120, 20, letters, "flex", dir="row", wrap="nowrap",
              gap=[0, 0], justify="normal", alignItems="normal", alignContent="normal",
              item={"minW": minimum})
    parent = board("Grid", 0, 0, 220, 20, [c], "grid", cols=[120, 100], rows=[20],
                   colsSpec="minmax(0px, 1.2fr) minmax(0px, 1fr)", rowsSpec="auto",
                   gap=[0, 0], justify="start", alignItems="center", alignContent="start")
    pl.plan_tree(parent)
    cell = parent["children"][0]
    assert cell.get("isolateGridMinimum") and cell["children"] == [c]
    assert cell["pp"]["mode"] is None
    assert cell["pp"]["item"]["layout-item-v-sizing"] == "fix"
    assert cell["pp"]["item"]["layout-item-h-sizing"] == "fill"
    assert c["pp"]["item"]["constraints-h"] == "leftright"
    assert parent["pp"]["content"][0] < 1
    assert parent["pp"]["hug"][1] == pytest.approx(20)


def test_wrapping_label_is_not_isolated_from_its_height_layout():
    t = text("Wrapping label", 0, 0, 120, 20)
    c = board("Label", 0, 0, 120, 20, [t], "flex", dir="row", item={"minW": 0})
    parent = board("Grid", 0, 0, 220, 20, [c], "grid", colsSpec="minmax(0px, 1fr) minmax(0px, 1fr)")
    pl._zero_min_grid_cells(parent)
    assert parent["children"] == [c]


def test_table_columns_use_equivalent_fill_ratios_and_narrow_with_the_row():
    cells = [board("Job", 0, 0, 180, 32), board("Destination", 180, 0, 300, 32),
             board("Status", 480, 0, 120, 32)]
    row = board("Jobs row", 0, 0, 600, 32, cells, "grid", cols=[180, 300, 120], rows=[32],
                colsSpec="30% 50% 20%", rowsSpec="auto", gap=[0, 0],
                justify="start", alignContent="start")
    pl.plan_tree(row)
    assert row["pp"]["mode"] == "grid", row["pp"]
    tracks = row["pp"]["attrs"]["layout-grid-columns"]
    assert pl._tracks_px(tracks, 400, 0, [], False, "stretch") == [120, 200, 80]
    assert all(c["pp"]["item"]["layout-item-h-sizing"] == "fill" for c in cells)
    assert all(t["type"] == "flex" for t in tracks)
    assert row["pp"]["content"][0] <= 1  # native track floor, not the old 600px width


def build_scene(nodes, **extra):
    scene = {"width": 600, "height": 200, "nodes": nodes, "vars": [], "issues": [],
             "background": [{"type": "color", "color": "#FFFFFF", "opacity": 1}], **extra}
    fonts = h2p.Fonts()
    fonts.add(STYLE["family"], 400, "normal", "font")
    return h2p.build({600: scene}, "file-1", "page-1", fonts, {}, "Beacon")


def reopen(built):
    client = FakePenpot()
    for chunk in built["chunks"]:
        client.update("file-1", chunk["changes"])
    # A real API reopen deserializes new objects. The fake retains payload
    # references, so mutation contracts must not mutate the expected build too.
    return copy.deepcopy(client.get("file-1"))


def test_field_text_after_blank_lines_keeps_its_paragraph_index_and_position_data():
    t = text("Notes value", 0, 0, 300, 60)
    t["text"].update(plain="First\n\nLast", paragraphs=[[{"text": "First", "style": STYLE}], [],
                                                   [{"text": "Last", "style": STYLE}]],
                     lines=[{"p": 0, "l": 0, "text": "First", "x": 0, "y": 20, "w": 40, "h": 20},
                            {"p": 2, "l": 0, "text": "Last", "x": 0, "y": 60, "w": 32, "h": 20}])
    built = build_scene([t])
    obj = next(o for o in built["objects"] if o["type"] == "text")
    paragraphs = obj["content"]["children"][0]["children"]
    assert len(paragraphs) == 3 and paragraphs[1]["children"][0]["text"] == ""
    assert [p["text"] for p in obj["position-data"]] == ["First", "Last"]


def test_omitted_screen_reader_text_is_listed_and_warned_not_silently_lost():
    hidden = [{"where": "span.sr-only", "text": "Dispatch status", "reason": "screen-reader-only (clipped, not visible)"}]
    built = build_scene([text("Visible status", 0, 0, 200, 20)], omittedText=hidden)
    result = h2p.verify(reopen(built), "page-1", built)
    assert result["checks"]["text_matches_page"]
    assert result["omitted_text"] == [{"width": 600, **hidden[0]}]
    assert any("screen-reader-only" in w for w in result["warnings"])
    assert not any("Dispatch status" == v for v in built["plain"].values())


def test_list_counts_fail_when_a_marker_is_missing_or_its_words_change():
    marker = text("List marker", 0, 0, 12, 20, fit="clip")
    item = {"where": "ol > li", "text": "4.", "style": "decimal", "expected": True}
    marker["text"]["paragraphs"][0][0]["text"] = marker["text"]["plain"] = "4."
    marker["text"]["lines"][0]["text"] = "4."
    marker["listMarker"] = item
    built = build_scene([marker], lists=[item])
    fresh = reopen(built)
    result = h2p.verify(fresh, "page-1", built)
    assert result["checks"]["list_markers_drawn"]
    assert (result["counts"]["list_items"], result["counts"]["expected_markers"], result["counts"]["drawn_markers"]) == (1, 1, 1)
    missing = copy.deepcopy(built)
    missing["list_markers"] = []
    assert not h2p.verify(fresh, "page-1", missing)["checks"]["list_markers_drawn"]
    obj = fresh["data"]["pages-index"]["page-1"]["objects"][built["list_markers"][0]["id"]]
    obj["content"]["children"][0]["children"][0]["children"][0]["text"] = "9."
    assert not h2p.verify(fresh, "page-1", built)["checks"]["list_markers_drawn"]


def test_editor_colour_proof_counts_text_and_shapes_but_not_the_render_cache():
    linked = {"fillColorRefId": "accent", "fillColor": "#71DBAB"}
    text_obj = {"content": {"children": [{"children": [{"children": [{"text": "Ready", "fills": [linked]}]}]}]},
                "position-data": [{"fills": [linked]}]}
    objects = {"label": text_obj, "button": {"fills": [linked]},
               "unlinked": {"fills": [{"fillColor": "#71DBAB"}]}}
    assert editor.linked_fills(objects, "accent", "#71dbab") == {("label", "text", 0, 0), ("button", "shape", 0, 0)}
    assert editor.linked_fills(objects, "accent", "#000000") == set()
    assert editor.linked_fills({"s": {"fills": [{"fill-color-ref-id": "accent", "fill-color": "#71DBAB"}]}}, "accent") == {("s", "shape", 0, 0)}


def test_editor_colour_proof_accepts_svg_xml_content_without_losing_shape_fills():
    linked = {"fillColorRefId": "accent", "fillColor": "#71DBAB"}
    objects = {"drawing": {"type": "svg-raw", "content": '<svg><path d="M0 0"/></svg>',
                           "fills": [linked]},
               "label": {"type": "text", "content": {"children": [{"children": [{"children": [
                   {"text": "Ready", "fills": [linked]}]}]}]}}}
    assert editor.linked_fills(objects, "accent", "#71dbab") == {
        ("drawing", "shape", 0, 0), ("label", "text", 0, 0)}
    assert editor.text_leaves(None) == []
    assert editor.text_leaves(objects["drawing"]["content"]) == []


@pytest.mark.parametrize("verdicts, attempts, passed", [([True], 1, True), ([False, True], 2, True), ([False, False], 2, False)])
def test_editor_open_retries_once_and_retains_the_first_attempt_evidence(verdicts, attempts, passed):
    calls = []
    def attempt(n):
        calls.append(n)
        return {"passed": verdicts[n - 1], "failure": None if verdicts[n - 1] else "Internal Error",
                "console": f"console-{n}.json", "backend": f"backend-{n}.log"}
    result = editor.open_with_one_retry(attempt)
    assert calls == list(range(1, attempts + 1)) and result["passed"] == passed
    assert result["attempts"][0]["console"] == "console-1.json"
    assert len(result["warnings"]) == attempts - 1
    if attempts == 2:
        assert "Internal Error" in result["warnings"][0]


def test_production_dom_helpers_on_fictional_fields_themes_tables_and_lists():
    fixture = Path(__file__).parent / "fixtures/converter_dom_contracts.cjs"
    result = subprocess.run(["node", str(fixture), str(BIN / "html_dom_extract.js")],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["passed"] is True
