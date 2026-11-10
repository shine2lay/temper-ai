"""Deterministic tests for Stage 3 proof battery (`configs/design/bin/foundation/proof.py`).

Covers Task #244 verify assertions:
- (a) every planted-fault case under `/home/shinelay/design-lab/foundation/known-cases/proof/`
      is caught by its own rule, with any other firing rule named in that case's `expected.json`
      allow list and justified — an uncaught plant or an unexplained extra row fails the test;
- (b) `base-clean` passes all 8 rules with zero failing rows;
- (g) `signal.separation` fails a green/red pair that is distinguishable to normal vision but
      collapses under deuteranopia simulation, and passes a pair separated in lightness;
- (h) `type.fallback` fails a bare family name and passes a stack;
- (j) contrast rows agree with `configs/design/bin/app_screen/checks_rules.py` on a shared set
      of colour pairs, proving one formula not two.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FOUNDATION_BIN = REPO_ROOT / "configs" / "design" / "bin"
if str(FOUNDATION_BIN) not in sys.path:
    sys.path.insert(0, str(FOUNDATION_BIN))

import wcag_contrast  # noqa: E402
from app_screen import checks_rules  # noqa: E402
from foundation import color, contracts, proof, stubs, workspace  # noqa: E402

KNOWN_CASES_DIR = Path("/home/shinelay/design-lab/foundation/known-cases/proof")

EXPECTED_CASE_DIRS = (
    "base-clean",
    "p01-contrast-text",
    "p02-contrast-ui",
    "p03-signal-separation",
    "p04-gamut-srgb",
    "p05-scale-spacing",
    "p06-scale-type",
    "p07-type-fallback",
    "p08-tokens-schema",
)


def _assert_case_matches_expected(tokens_doc: dict, expected_doc: dict, case_label: str) -> dict:
    """Validate a case's proof evaluation against its `expected.json` specification.

    Fails if:
    - a `must_fire` rule does not fire (`fail`);
    - an allow-list entry is missing a non-empty `reason`;
    - any rule outside `must_fire ∪ allow` fires (`fail`).
    """
    ev = proof.evaluate_tokens(tokens_doc)
    assert ev["verdict"] == expected_doc["verdict"], (
        f"{case_label}: expected verdict={expected_doc['verdict']!r}, got {ev['verdict']!r}"
    )

    must_fire = set(expected_doc.get("must_fire") or [])
    allow_entries = expected_doc.get("allow") or []
    allowed_extra: dict[str, str] = {}
    for entry in allow_entries:
        rule_id = str(entry.get("rule") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        assert rule_id in proof.RULE_IDS, f"{case_label}: unknown rule {rule_id!r} in allow list"
        assert reason, f"{case_label}: allow-listed rule {rule_id!r} must have a non-empty justification reason"
        allowed_extra[rule_id] = reason

    firing_rules = {r["id"] for r in ev["rules"] if r["result"] == "fail"}
    uncaught = must_fire - firing_rules
    assert not uncaught, (
        f"{case_label}: planted rule(s) {sorted(uncaught)} did NOT fire (firing={sorted(firing_rules)})"
    )

    unexplained = firing_rules - must_fire - set(allowed_extra.keys())
    assert not unexplained, (
        f"{case_label}: unexplained extra rule(s) {sorted(unexplained)} fired without allow-list justification "
        f"(failing_rows={ev['failing_rows']})"
    )

    required_row_keys = {"id", "value", "threshold", "result", "evidence", "token_a", "token_b", "theme"}
    for row in ev["rows"]:
        assert set(row.keys()) == required_row_keys, f"{case_label}: row keys mismatch: {set(row.keys())}"
        assert row["id"] in proof.RULE_IDS
        assert row["result"] in ("pass", "fail")

    return ev


def test_b_base_clean_passes_all_eight_rules_with_zero_failing_rows() -> None:
    """Assertion (b): `base-clean` passes all 8 rules with zero failing rows."""
    case_dir = KNOWN_CASES_DIR / "base-clean"
    tokens_doc = json.loads((case_dir / "tokens.json").read_text(encoding="utf-8"))
    expected_doc = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))

    ev = _assert_case_matches_expected(tokens_doc, expected_doc, "base-clean")
    assert ev["verdict"] == "pass"
    assert ev["failing_rows"] == []
    assert [r["id"] for r in ev["rules"]] == list(proof.RULE_IDS)
    assert all(r["result"] == "pass" for r in ev["rules"])


@pytest.mark.parametrize("case_name", EXPECTED_CASE_DIRS)
def test_a_planted_fault_cases_caught_by_own_rule_and_no_unexplained_extras(case_name: str) -> None:
    """Assertion (a): every planted-fault case is caught by its own rule, with any other firing
    rule named in `expected.json` allow list and justified.
    """
    case_dir = KNOWN_CASES_DIR / case_name
    assert case_dir.is_dir(), f"Missing known-case directory: {case_dir}"
    tokens_doc = json.loads((case_dir / "tokens.json").read_text(encoding="utf-8"))
    expected_doc = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))

    ev = _assert_case_matches_expected(tokens_doc, expected_doc, case_name)
    planted_rule = expected_doc.get("planted_rule")
    if planted_rule is not None:
        assert ev["verdict"] == "fail"
        assert any(r["id"] == planted_rule for r in ev["failing_rows"]), (
            f"{case_name}: expected at least one failing row for {planted_rule}"
        )


def test_a_guard_rejects_uncaught_plant_or_unjustified_extra_rule() -> None:
    """Verify the assertion helper itself fails loud on an uncaught plant or an unexplained extra rule."""
    clean_tokens = json.loads((KNOWN_CASES_DIR / "base-clean" / "tokens.json").read_text(encoding="utf-8"))
    with pytest.raises(AssertionError, match="planted rule"):
        _assert_case_matches_expected(
            clean_tokens,
            {"verdict": "pass", "must_fire": ["contrast.text"], "allow": []},
            "synthetic-uncaught",
        )

    fault_tokens = json.loads((KNOWN_CASES_DIR / "p01-contrast-text" / "tokens.json").read_text(encoding="utf-8"))
    with pytest.raises(AssertionError, match="unexplained extra rule"):
        _assert_case_matches_expected(
            fault_tokens,
            {"verdict": "fail", "must_fire": [], "allow": []},
            "synthetic-unexplained",
        )
    with pytest.raises(AssertionError, match="non-empty justification reason"):
        _assert_case_matches_expected(
            fault_tokens,
            {"verdict": "fail", "must_fire": [], "allow": [{"rule": "contrast.text", "reason": "   "}]},
            "synthetic-empty-reason",
        )


def test_g_signal_separation_fails_deuteranopia_collapse_and_passes_lightness_separated_pair() -> None:
    """Assertion (g): `signal.separation` fails a green/red pair distinguishable to normal vision
    that collapses under deuteranopia simulation, and passes a pair separated in lightness.
    """
    base_tokens = color.generate_tokens("rollcall", anchor_hues={"accent": 155.0, "neutral": 250.0})

    # Plant isoluminant green (#2D7226, L=0.49) and red (#993A31, L=0.48) in light theme.
    collapsed = copy.deepcopy(base_tokens)
    tok_good = color.make_color_token(0.49, 0.13, 142.0, description="light good status text")
    tok_risk = color.make_color_token(0.48, 0.13, 28.0, description="light risk status text")
    collapsed["colour"]["light"]["semantic"]["good"]["text"] = tok_good
    collapsed["colour"]["light"]["semantic"]["risk"]["text"] = tok_risk

    m = proof.measure_signal_pair(tok_good, tok_risk)
    assert m["normal_dE"] >= 0.20, f"Pair should be clearly distinguishable to normal vision (got {m['normal_dE']})"
    assert m["dL"] < 0.09
    assert m["sim_distances"]["deuteranopia"] < 0.085
    assert m["passed"] is False

    ev_fail = proof.evaluate_tokens(collapsed)
    sig_fail = [r for r in ev_fail["failing_rows"] if r["id"] == "signal.separation"]
    assert len(sig_fail) == 1
    assert sig_fail[0]["token_a"] == "colour.light.semantic.good.text"
    assert sig_fail[0]["token_b"] == "colour.light.semantic.risk.text"

    # Separating the pair in lightness (good L=0.50 vs risk L=0.37) passes all 3 CVD simulations.
    ev_pass = proof.evaluate_tokens(base_tokens)
    sig_rows = [r for r in ev_pass["rows"] if r["id"] == "signal.separation"]
    assert len(sig_rows) == 4
    assert all(r["result"] == "pass" for r in sig_rows)


def test_h_type_fallback_fails_bare_family_and_passes_stack() -> None:
    """Assertion (h): `type.fallback` fails a bare family name and passes a fallback stack."""
    base_tokens = color.generate_tokens("rollcall", anchor_hues={"accent": 155.0, "neutral": 250.0})
    ev_pass = proof.evaluate_tokens(base_tokens)
    fb_pass_rows = [r for r in ev_pass["rows"] if r["id"] == "type.fallback"]
    assert len(fb_pass_rows) == 2
    assert all(r["result"] == "pass" for r in fb_pass_rows)

    bare_str = copy.deepcopy(base_tokens)
    bare_str["type"]["family"]["sans"]["$value"] = "Inter"
    ev_fail_str = proof.evaluate_tokens(bare_str)
    fb_fail_str = [r for r in ev_fail_str["failing_rows"] if r["id"] == "type.fallback"]
    assert len(fb_fail_str) == 1
    assert fb_fail_str[0]["token_a"] == "type.family.sans"

    single_item_list = copy.deepcopy(base_tokens)
    single_item_list["type"]["family"]["mono"]["$value"] = ["JetBrains Mono"]
    ev_fail_list = proof.evaluate_tokens(single_item_list)
    fb_fail_list = [r for r in ev_fail_list["failing_rows"] if r["id"] == "type.fallback"]
    assert len(fb_fail_list) == 1
    assert fb_fail_list[0]["token_a"] == "type.family.mono"


def test_j_contrast_agrees_with_app_screen_checks_rules_on_shared_pairs() -> None:
    """Assertion (j): contrast rows agree with `configs/design/bin/app_screen/checks_rules.py`
    on a shared set of colour pairs, proving one formula not two.
    """
    assert proof.contrast_ratio is checks_rules.contrast_ratio
    assert proof.contrast_ratio is wcag_contrast.contrast_ratio
    assert proof.is_large_text is checks_rules.is_large_text
    assert proof.check_text_contrast is checks_rules.check_text_contrast
    assert proof.check_ui_contrast is checks_rules.check_ui_contrast

    shared_pairs = [
        ("#12171B", "#F3F5F8", 16.0, 400, "pass"),
        ("#676C73", "#F3F5F8", 25.0, 700, "pass"),  # large text (3.0:1 threshold)
        ("#94999E", "#F3F5F8", 16.0, 400, "fail"),  # normal text fail (< 4.5:1)
        ("#AFB4BA", "#F3F5F8", 25.0, 700, "fail"),  # large text fail (< 3.0:1)
        ("#E4E8ED", "#090B0E", 16.0, 400, "pass"),
        ("#00773B", "#FFFFFF", 16.0, 500, "pass"),
        ("#7C0012", "#F3F5F8", 16.0, 500, "pass"),
    ]
    app_th = checks_rules.load_thresholds()
    proof_th = proof.load_thresholds()
    view = {"id": "v1", "screen": "overview", "state": "populated", "theme": "light", "width": 1280, "open": "/"}

    for idx, (fg_hex, bg_hex, font_px, weight, expected_res) in enumerate(shared_pairs):
        fg_rgb = wcag_contrast.parse_color_rgb(fg_hex)
        bg_rgb = wcag_contrast.parse_color_rgb(bg_hex)
        c_shared = proof.contrast_ratio(fg_rgb, bg_rgb)
        c_app = checks_rules.contrast_ratio(fg_rgb, bg_rgb)
        assert c_shared == c_app

        app_ratio, app_need, app_passed = checks_rules.check_text_contrast(
            fg_hex, bg_hex, size_px=font_px, weight=weight, thresholds=app_th
        )
        proof_ratio, proof_need, proof_passed = proof.check_text_contrast(
            fg_hex, bg_hex, size_px=font_px, weight=weight, thresholds=proof_th
        )
        assert app_ratio == proof_ratio == round(c_shared, 2)
        assert app_need == proof_need
        assert app_passed == proof_passed == (expected_res == "pass")

        # Also exercise checks_rules._view_rows with raw colour/background (no pre-filled contrast)
        m = {
            "opened": True,
            "dm": {
                "contrast_failures": [
                    {
                        "color": fg_hex,
                        "background": bg_hex,
                        "size": font_px,
                        "weight": weight,
                        "sel": f"#pair-{idx}",
                        "text": "Sample Label",
                    }
                ]
            },
        }
        view_rows = checks_rules._view_rows(view, m, {"marked": False}, app_th)
        contrast_rows = [r for r in view_rows if r["id"] == "contrast.text"]
        if expected_res == "fail":
            assert len(contrast_rows) == 1
            assert contrast_rows[0]["value"] == proof_ratio
            assert f"{proof_ratio}:1 needs {proof_need}:1" in contrast_rows[0]["evidence"]
            assert contrast_rows[0]["result"] == "fail"
        else:
            assert contrast_rows == []


def test_proof_stage_step_writes_proof_json_and_table_md(tmp_path: Path) -> None:
    """Stage 3 `proof.run` executes over a workspace, enforces STEP_INPUTS['proof'],
    and writes `03-proof/proof.json` and `03-proof/table.md`.
    """
    from foundation import brief  # noqa: E402

    repo = tmp_path / "product-repo"
    ws_dir = repo / ".temper" / "design"
    ws_dir.mkdir(parents=True, exist_ok=True)
    brief_file = repo / ".temper" / "product" / "brief.md"
    brief_file.parent.mkdir(parents=True, exist_ok=True)
    brief_file.write_text(
        "# RollCall Brief\n\n"
        "## 1. What it is\nCovered-call trading dashboard.\n\n"
        "## 2. Who for\nActive options traders managing roll signals.\n\n"
        "## 3. Where and how used\nDesktop and mobile web during market hours.\n\n"
        "## 4. How it should feel plus what it must not feel like\nCalm, high-precision financial ledger; never purple neon.\n\n"
        "## 5. The neighbours\nStripe Docs and Linear.\n\n"
        "## 6. Hard constraints\n- Body text >= 16px\n- 8px spacing base\n\n"
        "## 7. Taste anchors\n- Stripe Docs restraint\n",
        encoding="utf-8",
    )
    ws = workspace.Workspace(ws_dir)
    brief.run(ws, product="rollcall")
    stubs.directions_collect(ws)
    stubs.directions_check(ws, draft=stubs.stub_model_read("directions_read"))
    stubs.directions_finish(ws)

    res = proof.run(ws)
    assert res["status"] == "done"
    assert res["verdict"] == "pass"
    assert res["table"] == "03-proof/table.md"
    assert res["sheet"] == "03-proof/table.md"

    proof_json_path = ws.path / "03-proof" / "proof.json"
    table_md_path = ws.path / "03-proof" / "table.md"
    assert proof_json_path.is_file()
    assert table_md_path.is_file()

    proof_doc = json.loads(proof_json_path.read_text(encoding="utf-8"))
    contracts.validate("proof", proof_doc, step="proof")
    assert proof_doc["verdict"] == "pass"
    assert proof_doc["table_file"] == "03-proof/table.md"
    assert len(proof_doc["directions"]) == 2
    for d in proof_doc["directions"]:
        assert d["verdict"] == "pass"
        assert [r["id"] for r in d["rules"]] == list(proof.RULE_IDS)
        assert all(r["result"] == "pass" for r in d["rules"])

    table_md = table_md_path.read_text(encoding="utf-8")
    for rule_id in proof.RULE_IDS:
        assert rule_id in table_md
