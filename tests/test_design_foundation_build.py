"""Unit and known-case tests for ``design_foundation_v1`` Stage 5 (``build``).

Covers:
1. Known-case set under ``~/design-lab/foundation/known-cases/build/`` (or synthesized
   into ``tmp_path`` when the lab checkout is absent): ``base-clean`` passes clean (exit 0,
   zero failing rules) and each of the seven planted cases (``p01-tokens-schema``,
   ``p02-proof-gate``, ``p03-tokens-from-color``, ``p04-design-md-contract``,
   ``p05-prose-tokens-agreement``, ``p06-no-raw-colour-literal``, ``p07-brief-evidence``)
   exits non-zero naming its expected rule with zero cross-firing.
2. Hardest planted case against ``build.prose_tokens_agreement``: a plausible ``DESIGN.md``
   that describes a cool-slate, high-chroma, Plus Jakarta Sans palette and non-existent
   token paths while ``04-build/tokens.json`` is warm stone / restrained amber / Fraunces+Inter.
3. Byte-for-byte identity of ``04-build/tokens.json`` against ``color.compile_direction_tokens``
   for the direction chosen at Gate 1.
4. ``build_collect``, ``build_check`` (strict and ``allow_retry=True``), and ``build_finish``
   lifecycle, including cache reuse when inputs are unchanged and re-collection when the
   Gate 1 choice changes from ``a`` to ``b``.
5. Removal of Stage 5 stubs (``stub_tokens``, ``stub_design_md``, ``stub_model_read``,
   ``build_collect``, ``build_check``, ``build_finish``) from ``foundation/stubs.py``,
   zero bare ``except Exception`` in ``configs/design/bin/foundation/``, and preservation of
   ``color.py``, ``contrast.py``, ``proof.py``, ``proof_thresholds.json``, ``directions.py``,
   and ``preview.py``.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "configs" / "design" / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from foundation import (  # noqa: E402
    brief,
    build,
    directions,
    gates,
    stubs,
    workspace,
)
from foundation_harness import (  # noqa: E402
    BENCH_BRIEF_MD,
    BENCH_BUILD_DRAFT,
    BENCH_DIRECTIONS_DRAFT,
)

LAB_BUILD_CASES_DIR = Path.home() / "design-lab" / "foundation" / "known-cases" / "build"

EXPECTED_CAUGHT_BY: dict[str, list[str]] = {
    "base-clean": [],
    "p01-tokens-schema": ["build.tokens_schema"],
    "p02-proof-gate": ["build.proof_gate"],
    "p03-tokens-from-color": ["build.tokens_from_color"],
    "p04-design-md-contract": ["build.design_md_contract"],
    "p05-prose-tokens-agreement": ["build.prose_tokens_agreement"],
    "p06-no-raw-colour-literal": ["build.no_raw_colour_literal"],
    "p07-brief-evidence": ["build.brief_evidence"],
}


def _seed_stage4_workspace(ws_dir: Path, *, choice: str = "a") -> workspace.Workspace:
    repo = ws_dir.parent.parent if ws_dir.parent.name == ".temper" else ws_dir.parent
    ws_dir.mkdir(parents=True, exist_ok=True)
    brief_path = repo / ".temper" / "product" / "brief.md"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(BENCH_BRIEF_MD, encoding="utf-8")

    ws = workspace.Workspace(ws_dir)
    brief.run(ws, product="rollcall")
    directions_draft = copy.deepcopy(BENCH_DIRECTIONS_DRAFT)
    directions_draft["directions"] = directions_draft["directions"][:2]
    directions.directions_collect(ws)
    directions.directions_check(ws, draft=directions_draft)
    directions.directions_finish(ws)
    stubs.proof_run(ws, base_url=None)
    gates.answer(
        ws,
        "direction",
        json.dumps(
            {
                "choice": choice,
                "decided_by": "owner",
                "owner_words": "Warm stone ledger keeps strikes and delta legible without neon chart noise.",
                "source": "gate_direction",
                "reason": "Warm stone ledger keeps strikes and delta legible without neon chart noise.",
            }
        ),
    )
    return ws


def materialize_build_known_cases(root: Path) -> Path:
    """Write ``base-clean`` plus one planted case per ``build_check`` rule under ``root``."""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    seed_dir = root / "_seed_tmp" / ".temper" / "design"
    seed_ws = _seed_stage4_workspace(seed_dir, choice="a")
    build.build_collect(seed_ws)
    clean_draft = copy.deepcopy(BENCH_BUILD_DRAFT)
    build.build_check(seed_ws, draft=clean_draft)
    build.build_finish(seed_ws)

    brief_doc = json.loads((seed_ws.path / "01-brief" / "brief.json").read_text(encoding="utf-8"))
    directions_doc = json.loads((seed_ws.path / "02-directions" / "directions.json").read_text(encoding="utf-8"))
    gate_doc = json.loads((seed_ws.path / "02-directions" / "gate_direction.json").read_text(encoding="utf-8"))
    chosen_dir = directions_doc["directions"][0]
    clean_tokens = json.loads((seed_ws.path / "04-build" / "tokens.json").read_text(encoding="utf-8"))
    clean_md = (seed_ws.path / "04-build" / "DESIGN.md").read_text(encoding="utf-8")

    def write_case(
        case_id: str,
        *,
        tokens_obj: dict[str, Any],
        draft_obj: dict[str, Any],
        design_md_text: str | None = None,
        caught_by: list[str],
        notes: str,
    ) -> None:
        cdir = root / case_id
        for sub in ("01-brief", "02-directions/a", "02-directions/b", "04-build"):
            (cdir / sub).mkdir(parents=True, exist_ok=True)
        shutil.copy2(seed_ws.path / "run.json", cdir / "run.json")
        (cdir / "01-brief" / "brief.json").write_text(json.dumps(brief_doc, indent=2) + "\n", encoding="utf-8")
        (cdir / "02-directions" / "directions.json").write_text(
            json.dumps(directions_doc, indent=2) + "\n", encoding="utf-8"
        )
        (cdir / "02-directions" / "gate_direction.json").write_text(
            json.dumps(gate_doc, indent=2) + "\n", encoding="utf-8"
        )
        for did in ("a", "b"):
            shutil.copy2(
                seed_ws.path / "02-directions" / did / "tokens.json",
                cdir / "02-directions" / did / "tokens.json",
            )
            shutil.copy2(
                seed_ws.path / "02-directions" / did / "DESIGN.md",
                cdir / "02-directions" / did / "DESIGN.md",
            )
        (cdir / "04-build" / "tokens.json").write_text(
            json.dumps(tokens_obj, indent=2) + "\n", encoding="utf-8"
        )
        (cdir / "04-build" / "draft.json").write_text(
            json.dumps(draft_obj, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        md_out = (
            design_md_text
            if design_md_text is not None
            else build.render_design_md(
                product="rollcall",
                draft=draft_obj,
                chosen_direction=chosen_dir,
                gate_direction=gate_doc,
            )
        )
        (cdir / "04-build" / "DESIGN.md").write_text(md_out, encoding="utf-8")
        expected = {
            "case": case_id,
            "verdict": "pass" if not caught_by else "fail",
            "caught_by": caught_by,
            "notes": notes,
        }
        (cdir / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")

    # 0. base-clean
    write_case(
        "base-clean",
        tokens_obj=clean_tokens,
        draft_obj=clean_draft,
        design_md_text=clean_md,
        caught_by=[],
        notes="Clean Stage 5 build for chosen direction a (Quiet Ledger): color.py tokens + matching DESIGN.md.",
    )

    # 1. p01-tokens-schema
    bad_schema_tokens = copy.deepcopy(clean_tokens)
    bad_schema_tokens["colour"]["ink"]["$value"]["rgb"] = [24, 24, 27]
    write_case(
        "p01-tokens-schema",
        tokens_obj=bad_schema_tokens,
        draft_obj=clean_draft,
        caught_by=["build.tokens_schema"],
        notes="Unclosed extra property 'rgb' inside colour.ink.$value violates TOKENS_SCHEMA.",
    )

    # 2. p02-proof-gate
    bad_proof_tokens = copy.deepcopy(clean_tokens)
    bad_proof_tokens["colour"]["light"]["surface"]["canvas"]["$value"] = copy.deepcopy(
        bad_proof_tokens["colour"]["light"]["ramp"]["neutral"]["500"]["$value"]
    )
    write_case(
        "p02-proof-gate",
        tokens_obj=bad_proof_tokens,
        draft_obj=clean_draft,
        caught_by=["build.proof_gate"],
        notes="Light surface canvas uses ramp.neutral.500 and fails proof.py contrast.text.",
    )

    # 3. p03-tokens-from-color
    hand_tweaked_tokens = copy.deepcopy(clean_tokens)
    hand_tweaked_tokens["colour"]["light"]["ramp"]["neutral"]["300"] = copy.deepcopy(
        clean_tokens["colour"]["light"]["ramp"]["neutral"]["200"]
    )
    write_case(
        "p03-tokens-from-color",
        tokens_obj=hand_tweaked_tokens,
        draft_obj=clean_draft,
        caught_by=["build.tokens_from_color"],
        notes="Hand-authored colour number in ramp.accent.400 passes schema and proof.py but differs from color.py output.",
    )

    # 4. p04-design-md-contract
    bad_contract_draft = copy.deepcopy(clean_draft)
    bad_contract_draft["why"][1] = (
        "Use Warm Ledger by default for covered-call roll decisions at market open, or alternatively switch to Mineral Instrument for mobile alert triage."
    )
    write_case(
        "p04-design-md-contract",
        tokens_obj=clean_tokens,
        draft_obj=bad_contract_draft,
        caught_by=["build.design_md_contract"],
        notes="DESIGN.md hedges and names the rejected candidate direction 'Mineral Instrument'.",
    )

    # 5. p05-prose-tokens-agreement (hardest planted case: plausible prose describing a different palette + token paths)
    bad_agreement_draft = copy.deepcopy(clean_draft)
    bad_agreement_draft["premise"] = (
        "Warm Ledger treats the covered-call portfolio ledger as a cool slate command deck with high-chroma signal highlights and Plus Jakarta Sans headings for roll candidates."
    )
    bad_agreement_draft["how_to_use"][0] = (
        "Set the main covered-call portfolio workspace canvas to `colour.light.surface.panel` in light mode and `colour.dark.accent.primary` in dark mode."
    )
    bad_agreement_draft["how_to_use"][2] = (
        "Render covered-call workspace headings and active short call figures in Plus Jakarta Sans with `type.family.mono` for assignment exposure."
    )
    write_case(
        "p05-prose-tokens-agreement",
        tokens_obj=clean_tokens,
        draft_obj=bad_agreement_draft,
        caught_by=["build.prose_tokens_agreement"],
        notes=(
            "Hardest planted case: DESIGN.md looks valid read alone but describes a cool slate neutral palette, "
            "high-chroma signal accent, Plus Jakarta Sans typography, and non-existent token paths "
            "(`colour.light.surface.panel`, `colour.dark.accent.primary`) against warm-stone/balanced/IBM Plex Sans tokens.json."
        ),
    )

    # 6. p06-no-raw-colour-literal
    bad_literal_draft = copy.deepcopy(clean_draft)
    bad_literal_draft["how_to_use"][0] = (
        "Use `colour.paper` (#faf7f2, oklch(0.98 0.01 80)) for the main covered-call portfolio workspace canvas and `colour.surface` for raised roll-candidate cards at 16px and 4.5:1."
    )
    bad_literal_draft["what_not_to_do"][0] = (
        "Never replace `colour.paper` with `rgb(120, 40, 200)` or `hsl(270, 80%, 50%)` on covered-call portfolio ledger views."
    )
    write_case(
        "p06-no-raw-colour-literal",
        tokens_obj=clean_tokens,
        draft_obj=bad_literal_draft,
        caught_by=["build.no_raw_colour_literal"],
        notes="DESIGN.md prose embeds raw hex (#faf7f2), oklch(...), rgb(...), hsl(...), 16px, and 4.5:1 ratio instead of token references only.",
    )

    # 7. p07-brief-evidence
    bad_evidence_draft = copy.deepcopy(clean_draft)
    bad_evidence_draft["evidence"]["why"] = "L99: Automated crypto perpetual futures copy-trading leaderboard with social badges"
    bad_evidence_draft["why"][1] = "Social copy-trading leaderboards gamify crypto perpetual futures streak badges."
    write_case(
        "p07-brief-evidence",
        tokens_obj=clean_tokens,
        draft_obj=bad_evidence_draft,
        caught_by=["build.brief_evidence"],
        notes="DESIGN.md makes an unsourced product claim with a fabricated brief citation (L99).",
    )

    shutil.rmtree(root / "_seed_tmp", ignore_errors=True)
    return root


def _ensure_case_tree(tmp_path: Path) -> Path:
    if LAB_BUILD_CASES_DIR.is_dir() and all(
        (LAB_BUILD_CASES_DIR / name / "expected.json").is_file() for name in EXPECTED_CAUGHT_BY
    ):
        return LAB_BUILD_CASES_DIR
    return materialize_build_known_cases(tmp_path / "known-cases-build")


@pytest.mark.parametrize("case_name,expected_rules", list(EXPECTED_CAUGHT_BY.items()))
def test_known_cases_build_in_process_and_cli(
    tmp_path: Path, case_name: str, expected_rules: list[str]
) -> None:
    cases_root = _ensure_case_tree(tmp_path)
    case_dir = cases_root / case_name
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    assert expected["caught_by"] == expected_rules

    work_case = tmp_path / "run" / case_name
    shutil.copytree(case_dir, work_case)
    ws = workspace.Workspace(work_case)

    report = build.check_workspace(work_case)
    assert report["verdict"] == expected["verdict"]
    assert report["failing_rules"] == expected_rules

    proc = subprocess.run(
        [sys.executable, "-m", "foundation.build", str(work_case), "--json"],
        cwd=str(BIN_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    if not expected_rules:
        assert proc.returncode == 0, proc.stderr
        cli_rep = json.loads(proc.stdout)
        assert cli_rep["verdict"] == "pass"
        assert cli_rep["failing_rules"] == []
        res = build.build_check(ws)
        assert res["verdict"] == "ok"
    else:
        assert proc.returncode == 1
        cli_rep = json.loads(proc.stdout)
        assert cli_rep["verdict"] == "fail"
        assert cli_rep["failing_rules"] == expected_rules
        with pytest.raises(build.BuildError) as exc_info:
            build.build_check(ws)
        for rule_id in expected_rules:
            assert rule_id in str(exc_info.value)


def test_prose_tokens_agreement_catches_palette_type_and_path_drift(tmp_path: Path) -> None:
    cases_root = _ensure_case_tree(tmp_path)
    work_case = tmp_path / "p05"
    shutil.copytree(cases_root / "p05-prose-tokens-agreement", work_case)

    rep = build.check_workspace(work_case)
    assert rep["verdict"] == "fail"
    assert rep["failing_rules"] == ["build.prose_tokens_agreement"]
    messages = " | ".join(p["message"] for p in rep["problems"])
    assert "colour.light.surface.panel" in messages
    assert "colour.dark.accent.primary" in messages
    assert "cool" in messages.lower()
    assert "high-chroma" in messages.lower()
    assert "Plus Jakarta Sans" in messages


def test_tokens_json_is_byte_identical_to_color_engine(tmp_path: Path) -> None:
    ws = _seed_stage4_workspace(tmp_path / "repo" / ".temper" / "design", choice="a")
    col = build.build_collect(ws)
    assert col["model"] == "yes"
    assert col["direction_id"] == "a"

    committed_bytes = (ws.path / "04-build" / "tokens.json").read_bytes()
    directions_doc = json.loads((ws.path / "02-directions" / "directions.json").read_text(encoding="utf-8"))
    chosen_dir = directions_doc["directions"][0]
    committed_obj = json.loads(committed_bytes.decode("utf-8"))
    stamp = committed_obj["colour"]["$extensions"]["com.temper.design-files"]["date"]
    regenerated = directions.build_direction_tokens("rollcall", chosen_dir, date=stamp)
    regenerated_bytes = (json.dumps(regenerated, indent=2) + "\n").encode("utf-8")
    assert committed_bytes == regenerated_bytes


def test_build_collect_check_retry_finish_and_gate_change_recollect(tmp_path: Path) -> None:
    ws = _seed_stage4_workspace(tmp_path / "repo" / ".temper" / "design", choice="a")
    col = build.build_collect(ws)
    assert col["model"] == "yes"
    assert "L01:" in col["task"]
    assert "colour.paper" in col["task"]

    # Bad first draft with a non-existent token triggers verdict="retry" when allow_retry=True
    bad_draft = copy.deepcopy(BENCH_BUILD_DRAFT)
    bad_draft["how_to_use"][0] = "Bind the rollcall blotter background to `colour.nonexistent.token`."
    chk_retry = build.build_check(ws, draft=bad_draft, allow_retry=True)
    assert chk_retry["verdict"] == "retry"
    assert chk_retry["failing_rules"] == ["build.prose_tokens_agreement"]
    assert "build.prose_tokens_agreement" in chk_retry["revise_task"]

    # Revise pass with clean draft finishes Stage 5 and writes valid tokens.json, DESIGN.md, and build.json
    fin = build.build_finish(ws, draft=BENCH_BUILD_DRAFT)
    assert fin["status"] == "done"
    assert fin["direction"] == "a"
    assert (ws.path / "04-build" / "tokens.json").is_file()
    assert (ws.path / "04-build" / "DESIGN.md").is_file()
    assert (ws.path / "04-build" / "build.json").is_file()

    # Second collect on unchanged inputs skips the model stage
    col_cached = build.build_collect(ws)
    assert col_cached["model"] == "no"
    assert col_cached["status"] == "reused"

    # Changing Gate 1 choice to 'b' invalidates the cached build and recompiles tokens.json for 'b'
    gates.answer(
        ws,
        "direction",
        json.dumps(
            {
                "choice": "b",
                "decided_by": "owner",
                "owner_words": "Switch to Harbor Signal.",
                "source": "gate_direction",
                "reason": "Switch to Harbor Signal.",
            }
        ),
    )
    col_b = build.build_collect(ws)
    assert col_b["model"] == "yes"
    assert col_b["direction_id"] == "b"
    directions_doc = json.loads((ws.path / "02-directions" / "directions.json").read_text(encoding="utf-8"))
    dir_b = directions_doc["directions"][1]
    actual_b_bytes = (ws.path / "04-build" / "tokens.json").read_bytes()
    actual_b_obj = json.loads(actual_b_bytes.decode("utf-8"))
    stamp_b = actual_b_obj["colour"]["$extensions"]["com.temper.design-files"]["date"]
    expected_b_bytes = (
        json.dumps(directions.build_direction_tokens("rollcall", dir_b, date=stamp_b), indent=2) + "\n"
    ).encode("utf-8")
    assert actual_b_bytes == expected_b_bytes


def test_stage5_stubs_removed_no_bare_except_and_protected_files_untouched() -> None:
    for removed in (
        "stub_tokens",
        "stub_design_md",
        "stub_model_read",
        "build_collect",
        "build_check",
        "build_finish",
    ):
        assert not hasattr(stubs, removed), f"stubs.{removed} must be removed"

    foundation_dir = REPO_ROOT / "configs" / "design" / "bin" / "foundation"
    for py_file in sorted(foundation_dir.glob("*.py")):
        if py_file.name in ("directions.py", "preview.py"):
            continue
        text = py_file.read_text(encoding="utf-8")
        assert "except Exception" not in text, f"bare except Exception found in {py_file}"

    protected = [
        "configs/design/bin/foundation/color.py",
        "configs/design/bin/foundation/contrast.py",
        "configs/design/bin/foundation/proof.py",
        "configs/design/bin/foundation/proof_thresholds.json",
        "configs/design/bin/foundation/directions.py",
        "configs/design/bin/foundation/preview.py",
    ]
    diff = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--name-only", "HEAD", "--", *protected],
        capture_output=True,
        text=True,
        check=True,
    )
    assert diff.stdout.strip() == "", f"Protected files modified: {diff.stdout}"
