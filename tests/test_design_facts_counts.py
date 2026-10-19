"""The homepage workflow's measure stage on a page with known counts (queue #87, W3; BAR.md C "measure, runtime").

configs/design/testpages/facts-v1/index.html plants known problems, and its answer key expected.json (written
from the page's source before any measure ran) holds the counts: 3 failing axe rule ids, 5 failing text
contrast pairs (one of them text over an image), 4 targets under 24 px and exactly 9 text sizes. These tests
run the workflow's own measure code, design_homepage_v2.write_review_inputs with page checks as Job.measure
calls it (design_capture.py: axe-core, design_measure.js, design_page_checks; then craft_metrics), and assert
that what the critics and the rounds trust reports exactly those numbers: review/facts.md, review/craft-facts.md
and the structured facts (capture.json, facts/index-<view>.json, craft-metrics.json).

Two layers, like the runtime and page-check scene tests:
- replay (always): the browser measurements of facts-v1 were recorded once with a real browser into
  facts-v1/recorded/; the test feeds them through write_review_inputs (capture subprocess and craft_metrics
  replaced by the recording) so the real writers build facts.md and craft-facts.md.
- live (opt-in): DESIGN_FACTS_BROWSER=http://127.0.0.1:<port>/mcp points at a local @playwright/mcp (never the
  shared box browser on :8931). With DESIGN_FACTS_RECORD=1 as well it rewrites facts-v1/recorded/ from that run:
  do that after changing the page or the meter, then check the diff.

A mismatch is a finding, not a reason to edit the key: decide whether the page or the meter is wrong.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import urllib.parse
import warnings
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
PAGE = ROOT / "configs/design/testpages/facts-v1"
RECORDED = PAGE / "recorded"
KEY = json.loads((PAGE / "expected.json").read_text())
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v2 = _load("design_homepage_v2")
dc = _load("design_capture")

BRIEF = {**KEY["brief"], "category": "pottery classes"}
CHOSEN = {"id": "K", "name": "Keyed facts page", "brief": "A static page with planted, counted problems.",
          "signature_move": "none", "motion": "none", "imagery": "two flat SVG pictures"}
# Files the measure is a function of: a recording made with other versions is stale.
METER = ["design_capture.py", "design_measure.js", "design_page_checks.py", "design_page_checks.js",
         "design_page_checks_thresholds.json", "vendor/axe-4.13.0.min.js"]


def page_files() -> list[Path]:
    return sorted(p for p in PAGE.rglob("*") if p.is_file() and p.name != "expected.json" and RECORDED not in p.parents)


def sha(paths: list[Path], base: Path) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(str(p.relative_to(base)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def page_sha() -> str:
    return sha(page_files(), PAGE)


def meter_shas() -> dict:
    return {name: sha([BIN / name], BIN) for name in METER}


def site_copy(tmp_path: Path) -> Path:
    """The page as the measure stage sees a round's site: index.html with its fonts and images, nothing else."""
    site = tmp_path / "site"
    shutil.copytree(PAGE, site, ignore=shutil.ignore_patterns("expected.json", "recorded"))
    return site


# --------------------------------------------------------------------------- reading what the meter reported

AXE = re.compile(r"^axe `([a-z0-9-]+)` \(.*?\)\: .*?\. Elements: (.*)$")
CONTRAST = re.compile(r'^text contrast ([\d.]+):1 \(needs ([\d.]+)\): `([^`]+)`')
TARGET = re.compile(r'^target smaller than 24x24 px without the 24 px spacing \(WCAG 2\.5\.8\): `([^`]+)` "[^"]*" (\d+)x(\d+) px')
OVER = re.compile(r"^text over an image, gradient or translucent layer fails contrast: `([^`]+)` .*?\): ([\d.]+):1 at the worst")
PROBLEM = re.compile(r"^- \[([a-z+-]+)\] (.*)$")


def section(md: str, title: str) -> list[str]:
    """The lines under a ### heading that starts with title, up to the next heading."""
    out, inside = [], False
    for line in md.splitlines():
        if line.startswith("### ") or line.startswith("## "):
            inside = line.startswith("### " + title)
            continue
        if inside and line.strip():
            out.append(line)
    return out


def type_styles(line: str) -> dict:
    body = line.split("): ", 1)[1]  # "Type styles (size weight: count): 44px 700: 1, ..."
    return {k: int(v) for k, v in (part.rsplit(": ", 1) for part in body.split(", ") if part)}


def from_facts_md(md: str) -> dict:
    """The keyed numbers as a critic reads them in facts.md."""
    axe: dict[str, set] = {}
    contrast: dict[str, dict] = {}
    targets: dict[str, dict] = {}
    over: dict[str, dict] = {}
    views_of: dict[str, set] = {}
    for line in section(md, "Measured problems"):
        m = PROBLEM.match(line)
        if not m:
            continue
        views, text = set(m.group(1).split("+")), m.group(2)
        if a := AXE.match(text):
            axe.setdefault(a.group(1), set()).update(a.group(2).split("; "))
            views_of.setdefault("axe " + a.group(1), set()).update(views)
        elif c := CONTRAST.match(text):
            contrast[c.group(3)] = {"ratio": float(c.group(1)), "needs": float(c.group(2))}
            views_of.setdefault("contrast " + c.group(3), set()).update(views)
        elif t := TARGET.match(text):
            targets[t.group(1)] = {"box": [int(t.group(2)), int(t.group(3))]}
            views_of.setdefault("target " + t.group(1), set()).update(views)
        elif o := OVER.match(text):
            over[o.group(1)] = {"ratio": float(o.group(2))}
            views_of.setdefault("over " + o.group(1), set()).update(views)
    desk = [x for x in section(md, "Text and structure (desktop)") if x.startswith("Type styles")]
    mob = [x for x in section(md, "Text and structure (mobile)") if x.startswith("Type styles")]
    styles = {"desktop": type_styles(desk[0]) if desk else None}
    styles["mobile"] = type_styles(mob[0]) if mob else styles["desktop"]  # "same as above" lists no line
    return {"axe": axe, "contrast": contrast, "targets": targets, "over": over, "views_of": views_of, "styles": styles}


def from_craft_md(md: str) -> dict:
    sizes, width = {}, None
    for line in md.splitlines():
        if m := re.match(r"^## (\d+) px", line):
            width = m.group(1)
        elif width and (m := re.match(r"^- text sizes (\d+),", line)):
            sizes[width] = int(m.group(1))
    return sizes


def measured(review: Path) -> dict:
    """Every keyed number, from each place the workflow reports it."""
    md = from_facts_md((review / "facts.md").read_text())
    index = json.loads((review / "capture.json").read_text())
    views = {v["viewport"]: v for v in index["pages"][0]["views"]}
    raw = {vp: json.loads((review / v["facts"]).read_text()) for vp, v in views.items()}
    craft = json.loads((review / "craft-metrics.json").read_text())
    t = dc.pc.thresholds()
    per_view = {}
    for vp, f in raw.items():
        checks = f.get("page_checks") or {}
        probs, _ = dc.pc.judge(vp, checks, t, checks.get("pixels"))
        per_view[vp] = {
            "axe_violations": views[vp]["axe_violations"],
            "axe_ids": sorted(v["id"] for v in f["axe"]),
            "axe_nodes": {v["id"]: sorted(n["target"] if isinstance(n["target"], str) else "; ".join(n["target"])
                                          for n in v["nodes"]) for v in f["axe"]},
            "contrast_failures": views[vp]["measured"]["contrast_failures"],
            "contrast_sels": sorted(x["sel"] for x in f.get("contrast_failures") or []),
            "contrast_exempt_sels": sorted(x["sel"] for x in f.get("contrast_exempt") or []),
            "small_targets": views[vp]["measured"]["small_targets"],
            "small_target_sels": sorted(x["sel"] for x in f.get("small_targets") or []),
            "type_styles": {s["style"]: s["count"] for s in f.get("type_styles") or []},
            "over_image_failing": sorted(re.search(r"`([^`]+)`", x).group(1) for k, x in probs if k == "text-over-image"),
            "overlay_candidates": len(checks.get("overlays") or []),
        }
    return {"facts_md": md, "per_view": per_view,
            "craft_text_sizes": {w: m["text_sizes"] for w, m in craft.items()},
            "craft_md_text_sizes": from_craft_md((review / "craft-facts.md").read_text())}


def mismatches(got: dict) -> list[str]:
    """Each way the measured facts differ from the key, in words (empty when they agree)."""
    out: list[str] = []
    counts = KEY["counts"]
    md = got["facts_md"]

    def check(where: str, value, want):
        if value != want:
            out.append(f"{where}: measured {value!r}, key {want!r}")

    # 3 failing axe rule ids, each naming its planted elements, in both views
    check("facts.md axe rule ids", sorted(md["axe"]), sorted(k for k in KEY["axe"] if k != "about"))
    check("facts.md axe rule id count", len(md["axe"]), counts["axe_rule_ids"])
    for rule, sels in KEY["axe"].items():
        if rule == "about":
            continue
        check(f"facts.md axe {rule} elements", sorted(md["axe"].get(rule, [])), sorted(sels))
        check(f"facts.md axe {rule} views", md["views_of"].get("axe " + rule), {"desktop", "mobile"})
    # 5 failing contrast pairs: four from the declared colours, one from the pixels behind text over an image
    pairs = KEY["contrast_pairs"]["pairs"]
    declared = [p for p in pairs if p["meter"] == "contrast_failures"]
    pixel = [p for p in pairs if p["meter"] != "contrast_failures"]
    check("facts.md failing contrast pairs (declared + over image)", len(set(md["contrast"]) | set(md["over"])),
          counts["failing_contrast_pairs"])
    check("facts.md text contrast elements", sorted(md["contrast"]), sorted(p["sel"] for p in declared))
    check("facts.md text-over-image elements", sorted(md["over"]), sorted(p["sel"] for p in pixel))
    for p in declared:
        got_p = md["contrast"].get(p["sel"])
        if got_p and (abs(got_p["ratio"] - p["ratio"]) > 0.02 or got_p["needs"] != p["needs"]):
            out.append(f"facts.md {p['id']} {p['sel']}: measured {got_p}, key ratio {p['ratio']} needs {p['needs']}")
        check(f"facts.md {p['id']} views", md["views_of"].get("contrast " + p["sel"]), {"desktop", "mobile"})
    for p in pixel:
        got_p = md["over"].get(p["sel"])
        low, high = p["ratio_range"]
        if got_p and not low - 0.01 <= got_p["ratio"] <= high + 0.01:
            out.append(f"facts.md {p['id']} {p['sel']}: pixel ratio {got_p['ratio']} outside {p['ratio_range']}")
        check(f"facts.md {p['id']} views", md["views_of"].get("over " + p["sel"]), {"desktop", "mobile"})
    # 4 small targets
    want_targets = {t["sel"]: t["box"] for t in KEY["small_targets"]["targets"]}
    check("facts.md small targets", sorted(md["targets"]), sorted(want_targets))
    check("facts.md small target count", len(md["targets"]), counts["small_targets"])
    for sel, box in want_targets.items():
        if sel in md["targets"]:
            check(f"facts.md {sel} size", md["targets"][sel]["box"], box)
            check(f"facts.md {sel} views", md["views_of"].get("target " + sel), {"desktop", "mobile"})
    # 9 text sizes, one weight each
    styles = KEY["text_sizes"]["type_styles"]
    for vp in ("desktop", "mobile"):
        check(f"facts.md type styles ({vp})", md["styles"][vp], styles)
        if md["styles"][vp]:
            check(f"facts.md distinct text sizes ({vp})", len({k.split("px")[0] for k in md["styles"][vp]}),
                  counts["text_sizes"])
    for w in KEY["craft_widths"]:
        check(f"craft-metrics.json text_sizes ({w} px)", got["craft_text_sizes"].get(w), counts["text_sizes"])
        check(f"craft-facts.md text sizes ({w} px)", got["craft_md_text_sizes"].get(w), counts["text_sizes"])
    # The structured facts, view by view
    axe_ids = sorted(k for k in KEY["axe"] if k != "about")
    for vp, v in got["per_view"].items():
        check(f"capture.json {vp} axe_violations", v["axe_violations"], counts["axe_rule_ids"])
        check(f"facts/{vp} axe ids", v["axe_ids"], axe_ids)
        for rule in axe_ids:
            check(f"facts/{vp} axe {rule} nodes", v["axe_nodes"].get(rule), sorted(KEY["axe"][rule]))
        check(f"capture.json {vp} contrast_failures", v["contrast_failures"], len(declared))
        check(f"facts/{vp} contrast_failures", v["contrast_sels"], sorted(p["sel"] for p in declared))
        check(f"facts/{vp} text-over-image failing", v["over_image_failing"], sorted(p["sel"] for p in pixel))
        check(f"facts/{vp} failing contrast pairs", len(v["contrast_sels"]) + len(v["over_image_failing"]),
              counts["failing_contrast_pairs"])
        check(f"facts/{vp} text over pictures measured", v["overlay_candidates"],
              KEY["also_measured"]["text_over_image_candidates_per_view"])
        check(f"capture.json {vp} small_targets", v["small_targets"], counts["small_targets"])
        check(f"facts/{vp} small_targets", v["small_target_sels"], sorted(want_targets))
        check(f"facts/{vp} type_styles", v["type_styles"], styles)
        check(f"facts/{vp} contrast_exempt", v["contrast_exempt_sels"], ["#waitlist"])
    return out


# --------------------------------------------------------------------------- the key and the page

def test_key_counts_match_its_own_lists():
    counts = KEY["counts"]
    assert len([k for k in KEY["axe"] if k != "about"]) == counts["axe_rule_ids"] == 3
    assert len(KEY["contrast_pairs"]["pairs"]) == counts["failing_contrast_pairs"] == 5
    assert sum(p["meter"] != "contrast_failures" for p in KEY["contrast_pairs"]["pairs"]) == 1  # one over an image
    assert len(KEY["small_targets"]["targets"]) == counts["small_targets"] == 4
    sizes = KEY["text_sizes"]["sizes"]
    assert len(sizes) == len(set(sizes)) == counts["text_sizes"] == 9
    assert sorted({int(k.split("px")[0]) for k in KEY["text_sizes"]["type_styles"]}, reverse=True) == sizes


def test_page_is_a_valid_measure_input():
    """The measure stage refuses a round whose page breaks the page contract; the keyed page must pass it."""
    assert v2.html_problems(PAGE / "index.html") == []
    html = (PAGE / "index.html").read_text()
    for ref in re.findall(r'(?:src|href)="([^"#]+)"|url\("([^"]+)"\)', html):
        path = ref[0] or ref[1]
        assert (PAGE / path).is_file(), f"index.html refers to {path}, which is not in facts-v1/"
    for p in page_files():
        if p.suffix == ".svg":
            assert "<text" not in p.read_text() and "http" not in p.read_text().replace("http://www.w3.org/2000/svg", "")
    for sel in [*(t["sel"] for t in KEY["small_targets"]["targets"]), *(p["sel"] for p in KEY["contrast_pairs"]["pairs"])]:
        assert f'id="{sel[1:]}"' in html


def test_the_recording_is_of_this_page():
    """The replay must be a measurement of the page as it is now; a stale meter is reported, not failed."""
    source = json.loads((RECORDED / "source.json").read_text())
    assert source["page_sha256"] == page_sha(), (
        "facts-v1 changed since its measurements were recorded: re-record (DESIGN_FACTS_BROWSER + DESIGN_FACTS_RECORD=1)")
    stale = [name for name, digest in meter_shas().items() if source["meter_sha256"].get(name) != digest]
    if stale:
        warnings.warn(f"facts-v1/recorded/ was measured with older {', '.join(stale)}; re-record to test the meter as it is now",
                      stacklevel=2)


# --------------------------------------------------------------------------- the measure stage, replayed and live

class Done:
    returncode, stdout, stderr = 0, "", ""


def replay(tmp_path: Path, monkeypatch) -> Path:
    """write_review_inputs as Job.measure calls it, with the browser parts replaced by the recording."""
    calls = []

    def fake_capture(cmd, **kwargs):
        calls.append(cmd)
        assert Path(cmd[1]).name == "design_capture.py"
        arg = lambda name: cmd[cmd.index(name) + 1]  # noqa: E731
        assert "--page-checks" in cmd and arg("--primary-action") == BRIEF["cta"]
        assert arg("--pages") == "index.html" and arg("--viewports") == "desktop,mobile"
        assert sha(sorted(p for p in Path(arg("--site")).rglob("*") if p.is_file()), Path(arg("--site"))) == page_sha()
        out = Path(arg("--out"))
        shutil.copytree(RECORDED / "facts", out / "facts", dirs_exist_ok=True)
        shutil.copyfile(RECORDED / "capture.json", out / "capture.json")
        dc.write_summary(out, json.loads((out / "capture.json").read_text()))  # the real facts.md writer
        return Done()

    monkeypatch.setattr(v2.subprocess, "run", fake_capture)
    monkeypatch.setattr(v2, "craft_metrics", lambda site: json.loads((RECORDED / "craft-metrics.json").read_text()))
    review = tmp_path / "review"
    review.mkdir()
    v2.write_review_inputs(review, site_copy(tmp_path), BRIEF, 1, CHOSEN, "keyed facts page", None, page_checks=True)
    assert len(calls) == 1
    return review


def test_measure_stage_reports_the_keyed_counts(tmp_path, monkeypatch):
    review = replay(tmp_path, monkeypatch)
    assert mismatches(measured(review)) == []


def live_browser() -> str:
    url = os.environ.get("DESIGN_FACTS_BROWSER", "")
    if not url:
        pytest.skip("live measure needs DESIGN_FACTS_BROWSER=http://127.0.0.1:<port>/mcp (a local @playwright/mcp)")
    parsed = urllib.parse.urlparse(url)
    if parsed.port == 8931 or parsed.hostname == "playwright-mcp":
        pytest.fail("never the shared box browser (:8931): start a local @playwright/mcp on another port")
    return url


def test_measure_stage_reports_the_keyed_counts_live(tmp_path, monkeypatch):
    url = live_browser()
    monkeypatch.setattr(v2, "BROWSER", url)
    monkeypatch.setattr(v2, "SERVE_HOST", urllib.parse.urlparse(url).hostname)
    review = tmp_path / "review"
    review.mkdir()
    v2.write_review_inputs(review, site_copy(tmp_path), BRIEF, 1, CHOSEN, "keyed facts page", None, page_checks=True)
    if os.environ.get("DESIGN_FACTS_RECORD") == "1":
        if RECORDED.exists():
            shutil.rmtree(RECORDED)
        (RECORDED / "facts").mkdir(parents=True)
        for f in (review / "facts").glob("*.json"):
            shutil.copyfile(f, RECORDED / "facts" / f.name)
        shutil.copyfile(review / "capture.json", RECORDED / "capture.json")
        shutil.copyfile(review / "craft-metrics.json", RECORDED / "craft-metrics.json")
        (RECORDED / "source.json").write_text(json.dumps({
            "about": "Measurements of facts-v1 by a real browser, replayed by tests/test_design_facts_counts.py.",
            "recorded": datetime.now(UTC).date().isoformat(), "browser": "local @playwright/mcp (" + url + ")",
            "page_sha256": page_sha(), "meter_sha256": meter_shas()}, indent=1) + "\n")
    assert mismatches(measured(review)) == []
