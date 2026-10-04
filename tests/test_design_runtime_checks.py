"""Model-free tests for Design's runtime checks (configs/design/bin/design_runtime_checks.py).

No browser: the recorded raw measurements in tests/design_runtime_scenes/ were captured from
configs/design/testpages/runtime/planted.html and control.html with the real shared browser
(queue #8). judge() turns raw measurements into findings with fixed rules, so the answer key
(expected.json) can be graded here and every rule change is checked against both pages.
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
PAGES = ROOT / "configs/design/testpages/runtime"
SCENES = Path(__file__).resolve().parent / "design_runtime_scenes"
sys.path.insert(0, str(BIN))

spec = importlib.util.spec_from_file_location("design_runtime_checks", BIN / "design_runtime_checks.py")
rtc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rtc)


def raw(name):
    return json.loads((SCENES / f"{name}.raw.json").read_text())


EXPECTED = json.loads((PAGES / "expected.json").read_text())


def test_planted_page_finds_every_plant_and_the_control_gives_no_finding():
    planted, control = rtc.judge(raw("planted")), rtc.judge(raw("control"))
    graded = rtc.grade(planted, control, EXPECTED)
    assert graded["recall"] == f"{len(EXPECTED['plants'])}/{len(EXPECTED['plants'])}" == "10/10"
    assert all(p["found"] for p in graded["plants"])
    assert graded["unexplained_on_planted"] == 0 and graded["control_false_alarms"] == []
    assert graded["passed"] is True
    assert control["findings"] == [] and control["failures"] == 0
    assert all(s["status"] == "pass" for s in control["checks"].values())
    for check in rtc.CHECKS:  # every check ran on both pages and found its plant on the planted one
        assert planted["checks"][check]["status"] == "fail", check
        assert control["checks"][check]["tested"] > 0, check


def test_every_plant_is_on_the_planted_page_and_not_on_the_control():
    planted_html = (PAGES / "planted.html").read_text()
    control_html = (PAGES / "control.html").read_text()
    for want in ("outline: none", "flex-wrap: nowrap", "height: 2.5em; overflow: hidden", 'tabindex="2"', 'aria-label="Continue"',
                 "width: 24ch; height: 3em"):
        assert want in planted_html and want not in control_html, want
    for quiet in EXPECTED["quiet"]:  # look-alikes on both pages that must never become findings
        assert quiet["match"] in planted_html and quiet["match"] in control_html, quiet["match"]
    # P3: both pages animate the art, but only the control keeps it inside the no-preference media query
    unguarded = "\n.hero-art { animation: drift"
    assert unguarded in planted_html and unguarded not in control_html
    assert "no-preference) {\n  .hero-art { animation: drift" in control_html
    assert "prefers-reduced-motion" in control_html  # the control moves only when motion is allowed


def test_findings_name_element_criterion_and_evidence():
    planted = rtc.judge(raw("planted"))
    ids = [f["id"] for f in planted["findings"]]
    assert ids == [f"R{i}" for i in range(1, len(ids) + 1)]
    for f in planted["findings"]:
        assert f["check"] in rtc.CHECKS and f["criterion"] and f["element"] and f["evidence"] and f["suggestion"]
        assert f["severity"] in (1, 2, 3)
    hover = [f for f in planted["findings"] if f["check"] == "hover"]
    assert hover and all(f["severity"] == 2 for f in hover)  # a craft check, never blocking alone
    assert planted["failures"] == sum(1 for f in planted["findings"] if f["severity"] >= 3)


def test_missing_measurements_are_not_run_never_pass():
    result = rtc.judge({"errors": ["browser unreachable"]})
    assert {c: s["status"] for c, s in result["checks"].items()} == {c: "not run" for c in rtc.CHECKS}
    assert result["findings"] == [] and result["errors"] == ["browser unreachable"]
    partial = raw("control")
    del partial["zoom"]
    statuses = {c: s["status"] for c, s in rtc.judge(partial)["checks"].items()}
    assert statuses["zoom"] == "not run" and statuses["focus"] == "pass"


def test_focus_rules_on_a_changed_control():
    changed = copy.deepcopy(raw("control"))
    stop = changed["focus"]["seq"][1]
    stop["changes"] = []  # nothing changes on screen when it gets focus
    changed["focus"]["candidates"][2]["tabindex"] = "4"
    found = {(f["check"], f["criterion"]) for f in rtc.judge(changed)["findings"]}
    assert ("focus", "2.4.7") in found and ("order", "2.4.3") in found
    faint = copy.deepcopy(raw("control"))
    faint["focus"]["seq"][1]["indicator"] = {"kind": "outline", "color": "rgb(200, 200, 200)",
                                             "against": "rgb(255, 255, 255)", "ratio": 1.67}
    assert [f["criterion"] for f in rtc.judge(faint)["findings"]] == ["1.4.11"]


def test_outputs_are_written_for_the_reviser_and_the_content_review(tmp_path):
    result = rtc.write_outputs(raw("planted"), tmp_path)
    for name in ("raw.json", "runtime.json", "RUNTIME.md", "page-text.md"):
        assert (tmp_path / name).exists(), name
    saved = json.loads((tmp_path / "runtime.json").read_text())
    assert saved["findings"] == result["findings"] and saved["failures"] == result["failures"]
    report = (tmp_path / "RUNTIME.md").read_text()
    assert "WCAG 2.4.7" in report and "R1" in report
    text = (tmp_path / "page-text.md").read_text()
    assert "- [h1] " in text and "Lantern Desk" in text  # visible text in reading order, tagged


def test_fixture_proof_grades_recorded_results_without_a_browser(tmp_path):
    out = rtc.fixture_proof(tmp_path, raws={"planted": raw("planted"), "control": raw("control")})
    assert out["passed"] is True and out["recall"] == "10/10"
    grade_md = (tmp_path / "GRADE.md").read_text()
    assert "MISSED" not in grade_md and "UNEXPLAINED" not in grade_md


def test_browser_code_tests_what_the_rules_promise():
    code = rtc.RUNTIME_CODE
    for needle in ("emulateMedia", "reducedMotion", "'reduce'", "no-preference", "keyboard.press", "Tab", "focus-visible"):
        assert needle in code, needle
    for needle in ("R.hiddenOnPurpose(el)", "harm: R.spillHarm(el, e)", "inset\\(\\s*50%", "kind: 'overlap'", "kind: 'contrast'"):
        assert needle in rtc.HELPERS, needle
    assert rtc.REFLOW_VIEWPORT == (320, 640) and rtc.ZOOM_VIEWPORT == (320, 200)  # 400% of a 1280 x 800 window
    assert rtc.STICKY_SHARE == 0.4 and rtc.SPACING_WIDTHS == (1440, 390)
    for value in ("line-height:1.5", "letter-spacing:0.12em", "word-spacing:0.16em"):
        assert value in rtc.SPACING_CSS
    assert "margin-bottom:2em" in rtc.SPACING_CSS.replace(" ", "")


def spacing_only(name, keep):
    """A recorded page whose only text-spacing problems are the ones `keep` accepts."""
    page = copy.deepcopy(raw(name))
    for res in page["spacing"].values():
        res["problems"] = [p for p in res["problems"] if keep(p)]
    return page


def test_hidden_text_and_harmless_spills_stay_quiet_but_are_reported():
    """Two false alarms on the Morrow pilot page (2026-10-04): screen-reader-only text 'cut off' at 320 px,
    and text running into free space under text spacing. The control now carries both look-alikes."""
    control = rtc.judge(raw("control"))
    assert control["findings"] == []
    notes = " ".join(control["notes"])
    assert "Most booked" in notes and "into free space" in notes and "nothing is cut off or covered" in notes
    assert not any("Three steps" in (t.get("label") or "") for t in raw("control")["reflow"]["text"])
    assert "## Measured and judged harmless" in rtc.report_md(control)


def test_a_spill_that_becomes_unreadable_is_still_a_failure():
    page = spacing_only("planted", lambda p: "Free tours" in (p.get("label") or ""))
    spacing = [f for f in rtc.judge(page)["findings"] if f["check"] == "spacing"]
    assert len(spacing) == 1 and spacing[0]["severity"] == 3 and spacing[0]["criterion"] == "1.4.12"
    assert "Free tours" in spacing[0]["element"]
    assert "onto a background where its contrast is 1.07:1" in spacing[0]["evidence"]


def test_spill_judgment_reads_overlap_and_keeps_old_recordings_strict():
    tag = lambda p: "Most booked" in (p.get("label") or "")  # noqa: E731
    over = spacing_only("control", tag)
    for res in over["spacing"].values():
        for p in res["problems"]:
            p["spill"]["harm"] = {"kind": "overlap", "with": {"tag": "h3", "label": "Team", "section": "Pricing"}}
    found = rtc.judge(over)["findings"]
    assert [f["criterion"] for f in found] == ["1.4.12"] and 'onto h3 "Team" (Pricing)' in found[0]["evidence"]
    old = spacing_only("control", tag)  # recorded before spills were judged: no "harm" key, so it still counts
    for res in old["spacing"].values():
        for p in res["problems"]:
            del p["spill"]["harm"]
    assert [f["criterion"] for f in rtc.judge(old)["findings"]] == ["1.4.12"]


@pytest.mark.parametrize("args", [["--raw", "planted"], ["--raw", "control"]])
def test_cli_judges_a_recorded_result(tmp_path, monkeypatch, capsys, args):
    name = args[1]
    monkeypatch.setattr(sys, "argv", ["design_runtime_checks.py", "--raw", str(SCENES / f"{name}.raw.json"),
                                      "--out", str(tmp_path)])
    assert rtc.main() == 0
    saved = json.loads((tmp_path / "runtime.json").read_text())
    assert (len(saved["findings"]) > 0) == (name == "planted")
