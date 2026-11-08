"""Unit and planted-fault tests for Stage 7 (show + show_check), W5 (gates prediction + taste),
Stage 8 (handoff + handoff_check), and the gate_final (changes -> Round 2 -> approve -> handoff) loop.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

from app_screen import (  # noqa: E402
    build_scaffold,
    contracts,
    gates,
    handoff,
    handoff_check,
    show,
    show_check,
)
from app_screen.contracts import ContractError  # noqa: E402
from app_screen.workspace import Workspace  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("design_app_screen", BIN / "design_app_screen.py")
CLI = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(CLI)

REPO_CASE = ROOT / "tests/design_app_screen_case/rollcall-20261104"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def real_ws(tmp_path: Path) -> Workspace:
    """Create a workspace populated through Stage 6b review (round 1, verdict='done')."""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    ws = Workspace(ws_dir)
    ws.start("rollcall")

    for rel in (
        "01-request/questions.json",
        "01-request/requirements.json",
        "02-existing/audit.json",
        "02-existing/journeys.json",
        "03-ground/inventory.json",
        "03-ground/fixture.json",
        "03-ground/design-files/DESIGN.md",
        "03-ground/design-files/tokens.json",
        "04-directions/directions.json",
        "04-directions/a/checks.json",
        "04-directions/b/checks.json",
    ):
        dst = ws_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_CASE / rel, dst)
    shutil.copy2(REPO_CASE / "gates/gate_direction.json", ws_dir / "04-directions/gate_direction.json")

    # Run Stage 5a scaffold + render a clean Stage 5b draft so 05-build/ has real HTML/CSS/JS/draft.json
    build_scaffold.write_scaffold(ws)
    inv = _read_json(ws.folder("ground") / "inventory.json")
    draft_screens = []
    for s in inv["screens"]:
        sid = s["id"]
        states = s.get("states") or ["normal", "loading", "empty", "error"]
        state_copy = {}
        for st in states:
            state_copy[st] = {
                "verdict": f"{s.get('name', sid)} — {st} view ready.",
                "band": f"Status band for {sid} in {st} state.",
                "recovery": f"Recovery and next action for {sid} ({st}).",
            }
        shows = []
        for idx, sh in enumerate(s.get("shows") or [], start=1):
            shows.append({
                "id": f"S{idx}",
                "label": sh.get("what", f"Show {idx}"),
                "fields": sh.get("sources") or ["positions"],
            })
        actions = []
        for idx, ac in enumerate(s.get("actions") or [], start=1):
            actions.append({
                "id": f"A{idx}",
                "label": ac.get("do", f"Action {idx}"),
                "kind": "primary" if idx == 1 else "secondary",
                "feedback": ac.get("leads_to", "Immediate banner update before server reply"),
            })
        draft_screens.append({
            "id": sid,
            "title": s.get("name", sid),
            "lead": s.get("job", f"Primary view for {sid}"),
            "layout": "band-cards-table",
            "primary_action": actions[0]["label"] if actions else "Refresh",
            "states": states,
            "state_copy": state_copy,
            "shows": shows,
            "actions": actions,
        })
    draft = {"screens": draft_screens, "notes": ["Initial real-mode build draft"]}
    _write_json(ws.folder("build") / "draft.json", draft)
    build_scaffold.render_draft(ws, draft)

    # Populate Stage 6a checks.json and Stage 6b review.json (verdict="done", 0 open Must findings)
    shutil.copytree(REPO_CASE / "06-checks/round-1", ws_dir / "06-checks/round-1", dirs_exist_ok=True)
    return ws


# ---------------------------------------------------------------- Stage 7: show.py & show_check.py

def test_show_real_mode_builds_self_contained_bundle_and_passes_contracts(real_ws: Workspace):
    out = show.run(real_ws)
    assert out["status"] == "ok"
    assert out["round"] == 1
    assert out["check_passed"] is True

    bundle_path = real_ws.folder("show") / "bundle.html"
    round1_bundle = real_ws.folder("show") / "bundle-round-1.html"
    assert bundle_path.is_file()
    assert round1_bundle.is_file()
    html = bundle_path.read_text(encoding="utf-8")
    assert 'data-st-interactive="true"' in html
    assert 'data-inlined-href="styles/tokens.css"' in html
    assert 'data-inlined-src="shell/router.js"' in html
    assert 'id="rc-fixture-data"' in html
    assert "<script src=" not in html

    contracts.validate("show", real_ws)


def test_prep_show_host_command_seeds_showtell_and_comments(real_ws: Workspace):
    res = show.prep_show(
        real_ws,
        doc_id="d_rcseed1234",
        title="RollCall Prototype v1",
        comments=[
            {
                "number": 1,
                "version": 1,
                "body": "Keep summary strip visible above table",
                "element": "#positions-band",
                "state": "answered",
                "replies": [{"outcome": "done", "version": 1, "body": "Pinned summary strip at top."}],
            }
        ],
    )
    assert res["showtell"]["doc_id"] == "d_rcseed1234"
    assert res["comments"]["doc_id"] == "d_rcseed1234"
    assert len(res["comments"]["comments"]) == 1

    out = show.run(real_ws)
    assert out["doc_id"] == "d_rcseed1234"
    contracts.validate("show", real_ws)


def test_show_fails_loud_when_prerequisites_missing_or_review_not_done(real_ws: Workspace):
    # 1. Missing 05-build/index.html
    index_path = real_ws.folder("build") / "index.html"
    saved_html = index_path.read_text(encoding="utf-8")
    index_path.unlink()
    with pytest.raises(ContractError, match="05-build/index.html: missing Stage 5 prototype HTML"):
        show.run(real_ws)
    index_path.write_text(saved_html, encoding="utf-8")

    # 2. Review verdict != "done"
    rev_path = real_ws.round_folder(1) / "review.json"
    rev_doc = _read_json(rev_path)
    bad_rev = dict(rev_doc, verdict="revise")
    _write_json(rev_path, bad_rev)
    with pytest.raises(ContractError, match="verdict must be 'done' before Stage 7 show"):
        show.run(real_ws)
    _write_json(rev_path, rev_doc)


def test_show_check_planted_fault_1_review_done(real_ws: Workspace):
    show.run(real_ws)
    rev_path = real_ws.round_folder(1) / "review.json"
    rev_doc = _read_json(rev_path)
    rev_doc["findings"].append({
        "id": "F-MUST-OPEN",
        "priority": "must",
        "severity": 3,
        "status": "open",
        "observation": "Planted open Must finding",
    })
    _write_json(rev_path, rev_doc)

    report = show_check.check_show(real_ws)
    assert report["passed"] is False
    assert report["rules"]["review_done"]["passed"] is False
    with pytest.raises(ContractError, match=r"\[review_done\].*open Must finding"):
        show_check.assert_show_clean(real_ws)


def test_show_check_planted_fault_2_bundle_self_contained(real_ws: Workspace):
    show.run(real_ws)
    bundle_path = real_ws.folder("show") / "bundle.html"
    good_html = bundle_path.read_text(encoding="utf-8")

    # Plant forbidden inner data-state attribute (note n131) + external script src
    bad_html = good_html.replace(
        "</body>",
        '<div data-state="open">trap</div><script src="screens/external.js"></script></body>',
    )
    bundle_path.write_text(bad_html, encoding="utf-8")

    report = show_check.check_show(real_ws)
    assert report["passed"] is False
    assert report["rules"]["bundle_self_contained"]["passed"] is False
    probs_text = "; ".join(report["rules"]["bundle_self_contained"]["problems"])
    assert "<script src='screens/external.js'>" in probs_text
    assert "forbidden data-state/data-st-state attribute(s)" in probs_text
    with pytest.raises(ContractError, match=r"\[bundle_self_contained\]"):
        show_check.assert_show_clean(real_ws)


def test_show_check_planted_fault_3_showtell_and_comments_match(real_ws: Workspace):
    show.run(real_ws)
    cm_path = real_ws.folder("show") / "comments.json"
    cm_doc = _read_json(cm_path)
    cm_doc["doc_id"] = "d_mismatched99"
    _write_json(cm_path, cm_doc)

    report = show_check.check_show(real_ws)
    assert report["passed"] is False
    assert report["rules"]["showtell_and_comments_match"]["passed"] is False
    with pytest.raises(ContractError, match=r"\[showtell_and_comments_match\].*does not match"):
        show_check.assert_show_clean(real_ws)


def test_show_check_planted_fault_4_targeted_comments_answered(real_ws: Workspace):
    show.run(real_ws)
    # Record Round 1 gate_final with choice="changes", comments=[1]
    gates.answer(
        real_ws,
        "final",
        json.dumps({
            "choice": "changes",
            "decided_by": "owner",
            "owner_words": "Make the call strike row clearer on mobile.",
            "source": "Show&Tell comment #1",
            "reason": "Targeted mobile row update",
            "comments": [1],
        }),
    )
    # Advance to Round 2 and run Stage 7 show
    real_ws.next_round()
    shutil.copytree(REPO_CASE / "06-checks/round-1", real_ws.folder("checks") / "round-1", dirs_exist_ok=True)
    (real_ws.folder("checks") / "round-2").mkdir(parents=True, exist_ok=True)
    for p in (real_ws.folder("checks") / "round-1").iterdir():
        target = real_ws.folder("checks") / "round-2" / p.name
        if p.is_file():
            target.write_bytes(p.read_bytes())

    show.run(real_ws)
    # Plant fault: reopen targeted comment #1 in 07-show/comments.json
    cm_path = real_ws.folder("show") / "comments.json"
    cm_doc = _read_json(cm_path)
    cm_doc["comments"][0]["state"] = "open"
    _write_json(cm_path, cm_doc)

    report = show_check.check_show(real_ws)
    assert report["passed"] is False
    assert report["rules"]["targeted_comments_answered"]["passed"] is False
    with pytest.raises(ContractError, match=r"\[targeted_comments_answered\].*targeted comment #1"):
        show_check.assert_show_clean(real_ws)


# ---------------------------------------------------------------- W5: gates.py prediction & taste encoding

def test_w5_direction_gate_prediction_and_owner_taste_encoding(real_ws: Workspace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    env_taste = tmp_path / "lab-taste-owner.md"
    monkeypatch.setenv("DESIGN_TASTE_FILE", str(env_taste))

    # Case 1: recommended="a" in 04-directions/directions.json, owner picks "a" -> matched=True, taste="saved"
    dir_path = real_ws.folder("directions") / "directions.json"
    dir_doc = _read_json(dir_path)
    dir_doc["recommended"] = "a"
    _write_json(dir_path, dir_doc)

    out = gates.answer(
        real_ws,
        "direction",
        json.dumps({
            "choice": "a",
            "decided_by": "owner",
            "owner_words": "Direction A gives the clearest 5-second glance.",
            "source": "Show&Tell direction review",
            "reason": "Matches glanceability hierarchy",
        }),
    )
    assert out["prediction"]["choice"] == "a"
    assert out["prediction"]["matched"] is True
    assert "recommended='a'" in out["prediction"]["basis"]
    assert out["taste"] == "saved"

    ws_taste = real_ws.path / "taste-owner.md"
    assert ws_taste.is_file()
    assert env_taste.is_file()
    assert 'owner_words="Direction A gives the clearest 5-second glance."' in ws_taste.read_text(encoding="utf-8")
    assert "gate=direction | choice=a | prediction=a (matched=True)" in env_taste.read_text(encoding="utf-8")

    # Case 2: fallback when "recommended" is absent -> picks direction with fewest should/fail rows
    del dir_doc["recommended"]
    _write_json(dir_path, dir_doc)
    checks_a = _read_json(real_ws.folder("directions") / "a/checks.json")
    checks_b = _read_json(real_ws.folder("directions") / "b/checks.json")
    checks_a["checks"][0]["result"] = "fail"
    _write_json(real_ws.folder("directions") / "a/checks.json", checks_a)
    _write_json(real_ws.folder("directions") / "b/checks.json", checks_b)

    out2 = gates.answer(
        real_ws,
        "direction",
        json.dumps({
            "choice": "a",
            "decided_by": "design",
            "source": "Design trial fallback test",
            "reason": "Testing prediction mismatch when design picks a over b",
        }),
    )
    assert out2["prediction"]["choice"] == "b"
    assert out2["prediction"]["matched"] is False
    assert out2["taste"] == "not-taste"


def test_w5_final_gate_prediction_approve_vs_changes(real_ws: Workspace):
    show.run(real_ws)

    # When review.verdict == "done" and 0 open comments -> predicts "approve"
    out_approve = gates.answer(
        real_ws,
        "final",
        json.dumps({
            "choice": "approve",
            "decided_by": "owner",
            "owner_words": "Ship it to Frontend.",
            "source": "Show&Tell final gate",
            "reason": "All screens and states verified",
        }),
    )
    assert out_approve["prediction"]["choice"] == "approve"
    assert out_approve["prediction"]["matched"] is True
    assert out_approve["taste"] == "saved"

    # When an open comment exists in 07-show/comments.json -> predicts "changes"
    cm_path = real_ws.folder("show") / "comments.json"
    cm_doc = _read_json(cm_path)
    cm_doc["comments"] = [
        {
            "id": "c_1",
            "number": 1,
            "version": 1,
            "body": "Add clearer recovery text on error banner",
            "element": "#rc-feedback",
            "state": "open",
        }
    ]
    _write_json(cm_path, cm_doc)

    out_changes = gates.answer(
        real_ws,
        "final",
        json.dumps({
            "choice": "changes",
            "decided_by": "owner",
            "owner_words": "Fix comment #1 first.",
            "source": "Show&Tell final gate",
            "reason": "Open comment #1 on error banner",
            "comments": [1],
        }),
    )
    assert out_changes["prediction"]["choice"] == "changes"
    assert out_changes["prediction"]["matched"] is True
    assert out_changes["taste"] == "saved"


# ---------------------------------------------------------------- Stage 8: handoff.py & handoff_check.py

def _prepare_approved_show(real_ws: Workspace) -> None:
    show.run(real_ws)
    gates.answer(
        real_ws,
        "final",
        json.dumps({
            "choice": "approve",
            "decided_by": "owner",
            "owner_words": "Approved for Frontend handoff.",
            "source": "Show&Tell final review",
            "reason": "Ready for implementation",
        }),
    )


def test_handoff_real_mode_generates_specs_design_file_and_followup(real_ws: Workspace):
    _prepare_approved_show(real_ws)
    out = handoff.run(real_ws)
    assert out["status"] == "ok"
    assert out["check_passed"] is True

    inv = _read_json(real_ws.folder("ground") / "inventory.json")
    for s in inv["screens"]:
        sid = s["id"]
        spec_file = real_ws.folder("handoff") / "spec" / f"{sid}.md"
        assert spec_file.is_file()
        text = spec_file.read_text(encoding="utf-8")
        for header in handoff_check.REQUIRED_SPEC_HEADERS:
            assert header in text
        for st in s["states"]:
            assert f"#{sid}/{st}" in text

    contracts.validate("handoff", real_ws)


def test_handoff_check_planted_fault_1_gate_final_approved(real_ws: Workspace):
    _prepare_approved_show(real_ws)
    handoff.run(real_ws)

    gate_path = real_ws.folder("show") / "gate_final.json"
    gate_doc = _read_json(gate_path)
    gate_doc["choice"] = "changes"
    gate_doc["comments"] = [1]
    _write_json(gate_path, gate_doc)

    report = handoff_check.check_handoff(real_ws)
    assert report["passed"] is False
    assert report["rules"]["gate_final_approved"]["passed"] is False
    with pytest.raises(ContractError, match=r"\[gate_final_approved\].*choice must be 'approve'"):
        handoff_check.assert_handoff_clean(real_ws)


def test_handoff_check_planted_fault_2_spec_per_inventory_screen(real_ws: Workspace):
    _prepare_approved_show(real_ws)
    handoff.run(real_ws)

    # Plant extra ungrounded spec file
    rogue = real_ws.folder("handoff") / "spec" / "rogue-screen.md"
    rogue.write_text("# Rogue\n", encoding="utf-8")

    report = handoff_check.check_handoff(real_ws)
    assert report["passed"] is False
    assert report["rules"]["spec_per_inventory_screen"]["passed"] is False
    with pytest.raises(ContractError, match=r"\[spec_per_inventory_screen\].*rogue-screen\.md"):
        handoff_check.assert_handoff_clean(real_ws)


def test_handoff_check_planted_fault_3_spec_sections_complete(real_ws: Workspace):
    _prepare_approved_show(real_ws)
    handoff.run(real_ws)

    first_spec = sorted((real_ws.folder("handoff") / "spec").glob("*.md"))[0]
    first_spec.write_text(
        first_spec.read_text(encoding="utf-8").replace("## Grounded Data", "## Missing Data"),
        encoding="utf-8",
    )

    report = handoff_check.check_handoff(real_ws)
    assert report["passed"] is False
    assert report["rules"]["spec_sections_complete"]["passed"] is False
    with pytest.raises(ContractError, match=r"\[spec_sections_complete\].*missing required section '## Grounded Data'"):
        handoff_check.assert_handoff_clean(real_ws)


def test_handoff_check_planted_fault_4_design_file_valid(real_ws: Workspace):
    _prepare_approved_show(real_ws)
    handoff.run(real_ws)

    df_path = real_ws.folder("handoff") / "design-file.json"
    df_doc = _read_json(df_path)
    df_doc["location"] = "05-build/nonexistent.html"
    _write_json(df_path, df_doc)

    report = handoff_check.check_handoff(real_ws)
    assert report["passed"] is False
    assert report["rules"]["design_file_valid"]["passed"] is False
    with pytest.raises(ContractError, match=r"\[design_file_valid\].*does not exist"):
        handoff_check.assert_handoff_clean(real_ws)


def test_handoff_check_planted_fault_5_followup_valid(real_ws: Workspace):
    _prepare_approved_show(real_ws)
    handoff.run(real_ws)

    fu_path = real_ws.folder("handoff") / "followup.json"
    fu_doc = _read_json(fu_path)
    # Remove all frontend items so inventory screens have no frontend implementation item
    fu_doc["items"] = [
        {
            "id": "F1",
            "owner_role": "design",
            "what": "Only a design note",
            "source": "03-ground/inventory.json",
        }
    ]
    _write_json(fu_path, fu_doc)

    report = handoff_check.check_handoff(real_ws)
    assert report["passed"] is False
    assert report["rules"]["followup_valid"]["passed"] is False
    with pytest.raises(ContractError, match=r"\[followup_valid\].*missing frontend implementation item"):
        handoff_check.assert_handoff_clean(real_ws)


def test_handoff_check_planted_fault_6_no_open_must_or_unanswered_comment(real_ws: Workspace):
    _prepare_approved_show(real_ws)
    handoff.run(real_ws)

    cm_path = real_ws.folder("show") / "comments.json"
    cm_doc = _read_json(cm_path)
    cm_doc["comments"].append({
        "id": "c_99",
        "number": 99,
        "version": 1,
        "body": "Unanswered blocker question",
        "element": "body",
        "state": "open",
    })
    _write_json(cm_path, cm_doc)

    report = handoff_check.check_handoff(real_ws)
    assert report["passed"] is False
    assert report["rules"]["no_open_must_or_unanswered_comment"]["passed"] is False
    with pytest.raises(ContractError, match=r"\[no_open_must_or_unanswered_comment\].*unanswered open comment"):
        handoff_check.assert_handoff_clean(real_ws)


# ---------------------------------------------------------------- End-to-end Round 1 (changes) -> Round 2 (approve) -> handoff loop

def test_gate_final_changes_to_round_2_show_approve_and_handoff_loop(real_ws: Workspace):
    # Round 1: Stage 7 show
    r1_show = show.run(real_ws)
    assert r1_show["round"] == 1
    assert r1_show["version"] == 1

    # Round 1: Owner requests changes on comment #1 at gate_final
    r1_gate = gates.answer(
        real_ws,
        "final",
        json.dumps({
            "choice": "changes",
            "decided_by": "owner",
            "owner_words": "Clarify the recovery action copy on the first screen.",
            "source": "Show&Tell v1 review",
            "reason": "Targeted wording refinement on comment #1",
            "comments": [1],
        }),
    )
    assert r1_gate["verdict"] == "changes"
    assert gates.final_next(real_ws) == {"verdict": "changes", "comments": [1]}

    # Comment #1 is now recorded as open in 07-show/comments.json
    cm_r1 = _read_json(real_ws.folder("show") / "comments.json")
    assert any(c["number"] == 1 and c["state"] == "open" for c in cm_r1["comments"])

    # Round 2: Targeted edit to 05-build/draft.json (keeping >95% of non-blank lines per bp-bc056d81)
    round_num = real_ws.next_round()
    assert round_num == 2
    draft_path = real_ws.folder("build") / "draft.json"
    draft_doc = _read_json(draft_path)
    draft_doc["screens"][0]["lead"] = (
        draft_doc["screens"][0]["lead"] + " — Updated recovery copy for Show&Tell comment #1."
    )
    _write_json(draft_path, draft_doc)
    build_scaffold.render_draft(real_ws, draft_doc)
    build_doc = _read_json(real_ws.folder("build") / "build.json")
    build_doc["round"] = 2
    _write_json(real_ws.folder("build") / "build.json", build_doc)

    # Round 2: Stage 6a checks + Stage 6b review (round-2)
    r2_dir = real_ws.round_folder(2)
    r2_dir.mkdir(parents=True, exist_ok=True)
    for item in real_ws.round_folder(1).iterdir():
        if item.is_file():
            (r2_dir / item.name).write_bytes(item.read_bytes())
    r2_checks = _read_json(r2_dir / "checks.json")
    r2_checks["round"] = 2
    _write_json(r2_dir / "checks.json", r2_checks)
    r2_rev = _read_json(r2_dir / "review.json")
    r2_rev["round"] = 2
    _write_json(r2_dir / "review.json", r2_rev)

    # Round 2: Stage 7 show resolves comment #1 and records bp-bc056d81 line retention
    r2_show = show.run(real_ws)
    assert r2_show["round"] == 2
    assert r2_show["version"] == 2
    assert r2_show["answered_comments"] == ["c_1"]

    st_r2 = _read_json(real_ws.folder("show") / "showtell.json")
    assert st_r2["version"] == 2
    assert st_r2["kept_ratio"] >= 0.90
    assert "non-blank lines kept vs previous version v1" in st_r2["change_note"]

    cm_r2 = _read_json(real_ws.folder("show") / "comments.json")
    c1 = [c for c in cm_r2["comments"] if c["number"] == 1][0]
    assert c1["state"] == "answered"
    assert any(r["version"] == 2 and r["outcome"] == "done" for r in c1["replies"])

    # Round 2: Owner approves at gate_final -> prediction="approve", matched=True
    r2_gate = gates.answer(
        real_ws,
        "final",
        json.dumps({
            "choice": "approve",
            "decided_by": "owner",
            "owner_words": "Looks great now, ship v2.",
            "source": "Show&Tell v2 approval",
            "reason": "Comment #1 addressed cleanly",
        }),
    )
    assert r2_gate["verdict"] == "approve"
    assert r2_gate["prediction"]["choice"] == "approve"
    assert r2_gate["prediction"]["matched"] is True
    assert r2_gate["taste"] == "saved"

    # Stage 8: handoff runs and passes all 6 rules + contract validation
    r2_handoff = handoff.run(real_ws)
    assert r2_handoff["status"] == "ok"
    assert r2_handoff["round"] == 2
    assert r2_handoff["check_passed"] is True
    contracts.validate("handoff", real_ws)
