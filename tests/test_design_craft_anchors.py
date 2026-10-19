"""design_craft_anchors.py (H6, W4c): measured craft numbers become craft findings at fixed levels.

- Each anchor on made-up craft-metrics.json, at both sides of its line: a share on a 4 px grid of 0.59,
  0.6, 0.89 and 0.9; a scale ratio of 1.99 and 2; 9, 8, 7 and 6 text sizes; every font family loaded
  or one not.
- One finding per anchor, at the worse of the two widths; a width with no number is left out.
- The rules table quotes the craft critic's prompt word for word at the lines it cites, and every item
  of the prompt's SEVERITY ANCHORS list is either applied by a rule or named as left to the critic.
- craft-v1 (configs/design/testpages/craft-v1), from the craft-metrics.json the measure stage's own code
  (design_homepage_v2.craft_metrics) gives each page in a headless browser
  (tests/fixtures/design_craft_anchors): every plant of a type an anchor measures is found at level 3 or
  more, the clean controls get no finding, no page gets a finding its key doesn't plant, the key's own
  measured verdicts agree with the anchors on every page, and the plants no anchor measures are listed as
  left to the critic. Two runs give byte-identical files.

The answer key stays on the host (~/design-lab/answers, or DESIGN_ANSWERS); without it the keyed tests
skip. Nothing here says which page carries which plant.
"""

import copy
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "configs" / "design" / "bin"
FIX = ROOT / "tests" / "fixtures" / "design_craft_anchors" / "craft-v1"
MANIFEST = json.loads((ROOT / "configs" / "design" / "testpages" / "craft-v1.json").read_text())
ANSWERS = pathlib.Path(os.environ.get("DESIGN_ANSWERS", pathlib.Path.home() / "design-lab" / "answers"))
KEY = ANSWERS / "craft-v1.yaml"
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ca = _load("design_craft_anchors")
FIELDS = {"id", "page", "width", "viewport", "element", "check", "metric", "value", "threshold", "level", "rule",
          "evidence"}


# ---------------------------------------------------------------- made-up craft-metrics.json

CLEAN = {
    1440: {"width": 1440, "body_px": 18, "display_px": 76, "scale_ratio": 4.22, "text_sizes": 5,
           "families": ["Serif", "Sans"], "loaded_families": ["Serif", "Sans"], "unloaded_families": [],
           "spacing_values": 12, "spacing_on_4px": 1, "consecutive_repeats": 0},
    390: {"width": 390, "body_px": 17, "display_px": 52, "scale_ratio": 3.06, "text_sizes": 5,
          "families": ["Serif", "Sans"], "loaded_families": ["Serif", "Sans"], "unloaded_families": [],
          "spacing_values": 11, "spacing_on_4px": 1, "consecutive_repeats": 0},
}


def _metrics(**at):
    """A clean page's craft-metrics.json; at maps a metric to (value at 1440, value at 390), None = unchanged."""
    m = copy.deepcopy(CLEAN)
    for metric, values in at.items():
        for width, value in zip((1440, 390), values, strict=True):
            if value is not None:
                m[width][metric] = value
    return {str(w): e for w, e in m.items()}


def _only(result):
    assert len(result["findings"]) <= 1
    return result["findings"][0] if result["findings"] else None


@pytest.mark.parametrize("share, level, band", [
    (0.0, 3, "below 0.6"), (0.59, 3, "below 0.6"), (0.6, 2, "0.6 to below 0.9"), (0.89, 2, "0.6 to below 0.9"),
    (0.9, 0, None), (1, 0, None),
])
def test_spacing_share_levels(share, level, band):
    for at, viewport in (((None, share), "mobile"), ((share, None), "desktop"), ((share, share), "all")):
        f = _only(ca.anchors(_metrics(spacing_on_4px=at)))
        if not level:
            assert f is None, at
            continue
        assert (f["level"], f["threshold"], f["check"], f["value"], f["viewport"]) == (level, band, "space", share,
                                                                                      viewport), at


@pytest.mark.parametrize("ratio, level", [(1, 3), (1.99, 3), (2, 0), (2.01, 0)])
def test_scale_ratio_levels(ratio, level):
    f = _only(ca.anchors(_metrics(scale_ratio=(None, ratio))))
    if level:
        assert (f["level"], f["threshold"], f["check"], f["width"], f["value"]) == (3, "below 2x", "scale", 390, ratio)
    else:
        assert f is None


@pytest.mark.parametrize("sizes, level, band", [
    (22, 3, "more than 8"), (9, 3, "more than 8"), (8, 2, "7 or 8"), (7, 2, "7 or 8"), (6, 0, None), (5, 0, None),
])
def test_text_size_levels(sizes, level, band):
    f = _only(ca.anchors(_metrics(text_sizes=(sizes, None))))
    if level:
        assert (f["level"], f["threshold"], f["check"], f["width"], f["value"], f["viewport"]) == (
            level, band, "type", 1440, sizes, "desktop")
    else:
        assert f is None


def test_a_font_family_that_failed_to_load_is_3_and_reported_once():
    assert _only(ca.anchors(_metrics(unloaded_families=([], [])))) is None
    f = _only(ca.anchors(_metrics(unloaded_families=(["Sans"], ["Serif", "Sans"]))))
    assert (f["level"], f["check"], f["value"], f["width"], f["viewport"]) == (3, "type", ["Sans", "Serif"], 1440, "all")
    assert "Sans, Serif" in f["element"] and f["threshold"] == "a family failed to load"


def test_one_finding_at_the_worse_of_the_two_widths():
    f = _only(ca.anchors(_metrics(spacing_on_4px=(0.7, 0.5))))  # 2 at 1440, 3 at 390: the worse width sets it
    assert (f["level"], f["width"], f["value"], f["viewport"], f["threshold"]) == (3, 390, 0.5, "all", "below 0.6")
    assert f["evidence"] == "craft-metrics.json: share on a 4 px grid 0.7 at 1440 and 0.5 at 390"
    f = _only(ca.anchors(_metrics(spacing_on_4px=(0.5, 0.5))))  # equal numbers: the wider width
    assert (f["width"], f["viewport"]) == (1440, "all")
    f = _only(ca.anchors(_metrics(text_sizes=(9, 7))))
    assert (f["level"], f["width"], f["value"], f["viewport"]) == (3, 1440, 9, "all")
    f = _only(ca.anchors(_metrics(scale_ratio=(1.67, 1.53))))
    assert (f["width"], f["value"]) == (390, 1.53)
    assert f["evidence"] == ("craft-metrics.json: scale ratio 1.67x at 1440 (body text 18 px, largest text 76 px) and "
                             "1.53x at 390 (body text 17 px, largest text 52 px)")


def test_a_clean_page_gives_every_check_and_no_finding():
    res = ca.anchors(_metrics())
    assert res["findings"] == [] and res["counts"] == {"4": 0, "3": 0, "2": 0, "1": 0}
    assert [c["rule"] for c in res["checks"]] == ca.ANCHORS == ["spacing-grid", "scale-ratio", "text-sizes", "font-loading"]
    assert all(c["level"] == 0 and set(c["values"]) == {"1440", "390"} for c in res["checks"])
    assert res["widths"] == [1440, 390] and res["page"] == "index.html"


def test_a_width_without_a_number_is_left_out():
    m = _metrics(spacing_on_4px=(None, 0.4))
    del m["1440"]["spacing_on_4px"]
    m["1440"]["text_sizes"] = None
    res = ca.anchors(m)
    f = _only(res)
    assert (f["rule"], f["width"], f["viewport"]) == ("spacing-grid", 390, "mobile")  # not "all": 1440 has no number
    assert f["evidence"] == "craft-metrics.json: share on a 4 px grid 0.4 at 390"
    checks = {c["rule"]: c for c in res["checks"]}
    assert checks["spacing-grid"]["values"] == {"1440": None, "390": 0.4}
    assert checks["text-sizes"]["levels"] == {"1440": None, "390": 0}
    assert ca.anchors({"1440": "not measured", "note": 3})["findings"] == []


def test_findings_carry_the_agreed_fields():
    res = ca.anchors(_metrics(spacing_on_4px=(0.8, 0.85), scale_ratio=(1.5, 1.4), text_sizes=(12, 7),
                              unloaded_families=(["Serif"], [])))
    assert [f["rule"] for f in res["findings"]] == ca.ANCHORS
    assert res["counts"] == {"4": 0, "3": 3, "2": 1, "1": 0}
    for f in res["findings"]:
        assert set(f) == FIELDS
        rule = ca.RULES[f["rule"]]
        assert (f["check"], f["metric"], f["id"]) == (rule["check"], rule["metric"], "craft-" + f["rule"])
        assert ca.level_of(f["rule"], f["value"] if f["rule"] != "font-loading" else ["x"]) == (f["level"], f["threshold"])
        assert f["evidence"].startswith("craft-metrics.json: ")


# ---------------------------------------------------------------- the rules table against the prompt


def test_rules_quote_the_craft_prompt_at_the_lines_they_cite():
    norm = lambda s: " ".join(s.split())  # noqa: E731
    for rid, rule in ca.RULES.items():
        parts = [norm(p) for p in rule["says"].split(" | ")]
        texts = [norm(" ".join((ROOT / path).read_text(encoding="utf-8").splitlines()[a - 1:b]))
                 for path, a, b in rule["cites"]]
        for p in parts:
            assert any(p in t for t in texts), (rid, p)
        for (path, a, b), t in zip(rule["cites"], texts, strict=True):
            assert any(p in t for p in parts), (rid, path, a, b)
        assert rule["script"]


def test_every_severity_anchor_of_the_prompt_is_applied_or_left_to_the_critic():
    lines = (ROOT / ca.CRAFT).read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if "SEVERITY ANCHORS" in line)
    end = next(i for i, line in enumerate(lines) if i > start and "When torn between two levels" in line)
    items = []  # [first line, last line, text], 1-based
    for i in range(start + 1, end):
        text = lines[i].strip()
        if text.startswith("- "):
            items.append([i + 1, i + 1, text[2:]])
        elif items and text:
            items[-1][1], items[-1][2] = i + 1, items[-1][2] + " " + text
    assert len(items) == 5
    cited = [(a, b) for rule in ca.RULES.values() for path, a, b in rule["cites"] if path == ca.CRAFT]
    for first, last, text in items:
        applied = any(a <= last and first <= b for a, b in cited)
        left = [k for k in ca.LEFT if text.startswith(k)]
        assert applied != bool(left), (first, text)
    assert all(any(text.startswith(k) for _, _, text in items) for k in ca.LEFT)


# ---------------------------------------------------------------- craft-v1


def _pages():
    return [(page, FIX / page) for page in MANIFEST["pages"]]


def test_craft_v1_fixtures_hold_the_measure_stages_numbers_for_every_page():
    assert [p for p, _ in _pages()] == sorted(d.name for d in FIX.iterdir() if d.is_dir())
    for page, folder in _pages():
        metrics = json.loads((folder / "craft-metrics.json").read_text())
        assert sorted(metrics) == ["1440", "390"], page
        for width, entry in metrics.items():
            assert entry["width"] == int(width), page
            for rule in ca.ANCHORS:
                assert ca._value(rule, entry) is not None, (page, width, rule)


def test_two_runs_are_byte_identical(tmp_path):
    for page, folder in _pages():
        outs = []
        for i in (1, 2):
            out = tmp_path / f"{page}-{i}.json"
            subprocess.run([sys.executable, str(BIN / "design_craft_anchors.py"), str(folder), "--out", str(out)],
                           check=True, capture_output=True, text=True)
            outs.append(out.read_bytes())
        assert outs[0] == outs[1], page
        assert outs[0] == ca.dumps(ca.craft_anchor_findings(folder)).encode()


def test_cli_writes_craft_anchors_json_by_default(tmp_path):
    review = shutil.copytree(FIX / MANIFEST["pages"][0], tmp_path / "review")
    done = subprocess.run([sys.executable, str(BIN / "design_craft_anchors.py"), str(review)],
                          capture_output=True, text=True, check=True)
    out = review / "craft" / "anchors.json"
    assert out.is_file() and str(out) in done.stdout
    assert json.loads(out.read_text()) == ca.craft_anchor_findings(review)
    empty = subprocess.run([sys.executable, str(BIN / "design_craft_anchors.py"), str(tmp_path / "none")],
                           capture_output=True, text=True)
    assert empty.returncode == 2 and "no craft-metrics.json" in empty.stderr
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "craft-metrics.json").write_text("{}")
    bad = subprocess.run([sys.executable, str(BIN / "design_craft_anchors.py"), str(tmp_path / "bad")],
                         capture_output=True, text=True)
    assert bad.returncode == 2 and "no measured widths" in bad.stderr


# The key's measured problem types that an anchor measures, and the rule that measures each. The key's
# other types are left to the critic; which page carries which type is read from the key at run time.
MEASURES = {"spacing_scale": "spacing-grid", "scale_contrast": "scale-ratio", "type_sizes": "text-sizes"}
KEY_NUMBERS = {"spacing_scale": ("on_4px_{w}", "spacing_on_4px"), "scale_contrast": ("ratio_{w}", "scale_ratio"),
               "type_sizes": ("text_sizes_{w}", "text_sizes")}
needs_key = pytest.mark.skipif(not KEY.is_file(), reason="the answer key lives on the host only")


def _graded():
    """Per page: the key's plant, the anchors' findings, and which are found, missed or false."""
    key = yaml.safe_load(KEY.read_text(encoding="utf-8"))
    rows = []
    for page, folder in _pages():
        plant = str(key["pages"][page]["plant"])
        rule = MEASURES.get(plant)
        res = ca.craft_anchor_findings(folder)
        found = [f for f in res["findings"] if rule and f["rule"] == rule and f["level"] >= 3]
        rows.append({"page": page, "plant": plant, "control": plant.startswith("none"), "rule": rule,
                     "findings": res["findings"], "found": found,
                     "false": [f for f in res["findings"] if f["rule"] != rule],
                     "missed": bool(rule) and not found})
    return key, rows


@needs_key
def test_craft_v1_measured_plants_are_found_at_level_3_or_more_and_controls_stay_clean():
    key, rows = _graded()
    print("\npage     plant                 anchor rule         found                                false  missed")
    for r in rows:
        found = ", ".join(f"{f['id']} {f['level']} ({f['value']} at {f['width']})" for f in r["found"]) or "-"
        rule = r["rule"] or ("(clean control)" if r["control"] else "left to the critic")
        print(f"{r['page']:<8} {r['plant']:<21} {rule:<19} {found:<36} {len(r['false']):<6} "
              f"{'MISSED' if r['missed'] else '-'}")
    measured = [r for r in rows if r["rule"]]
    controls = [r for r in rows if r["control"]]
    left = sorted(r["plant"] for r in rows if not r["rule"] and not r["control"])
    print(f"measured-type plants found {sum(bool(r['found']) for r in measured)}/{len(measured)}; "
          f"findings on clean controls {sum(len(r['findings']) for r in controls)}; "
          f"false findings {sum(len(r['false']) for r in rows)}; left to the critic: {', '.join(left)}")
    assert measured and all(r["found"] and not r["missed"] for r in measured)
    assert len(controls) == 2 and all(r["findings"] == [] for r in controls)
    assert all(r["false"] == [] for r in rows)
    assert len(measured) + len(left) == len(rows) - len(controls)


@needs_key
def test_craft_v1_key_measures_and_the_anchors_agree_on_every_page():
    key, rows = _graded()
    for r in rows:
        measured = key["pages"][r["page"]]["measured"]
        metrics = json.loads((FIX / r["page"] / "craft-metrics.json").read_text())
        for kind, rule in MEASURES.items():
            fired = [f for f in r["findings"] if f["rule"] == rule]
            assert (measured[kind]["verdict"] == "flawed") == bool(fired and fired[0]["level"] >= 3), (r["page"], kind)
            assert (measured[kind]["verdict"] == "clean") == (not fired), (r["page"], kind)
            name, metric = KEY_NUMBERS[kind]
            for w in ("1440", "390"):  # the fixtures hold the numbers the key was written from
                if name.format(w=w) in measured[kind]:
                    assert metrics[w][metric] == measured[kind][name.format(w=w)], (r["page"], kind, w)
