"""Real-mode stage and full-workflow runner for `design_app_screen_v1` outside the production path.

Drives `configs/design/bin/design_app_screen.py` in `mode="real"` using prepared workspace inputs and
model-boundary draft replay (`app_screen_harness.replay`), with prepared gate answers fed explicitly
through the real gate API/CLI.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

from .cases import (
    DEFAULT_CASE_DIR,
    HarnessCaseError,
    load_gate_answer,
    prepare_existing_inputs,
    prepare_ground_inputs,
    prepare_intake_inputs,
    prepare_workspace,
)
from .replay import draft_for_step, synthesize_measures_for_workspace

HERE = Path(__file__).resolve().parent
DESIGN_BIN = HERE.parent

ALL_ORDERED_STEPS: tuple[str, ...] = (
    "intake",
    "existing",
    "ground",
    "directions",
    "gate_direction",
    "build",
    "checks",
    "review",
    "show",
    "gate_final",
    "gate_final_next",
    "handoff",
)


def _ensure_design_bin_on_path() -> None:
    if str(DESIGN_BIN) not in sys.path:
        sys.path.insert(0, str(DESIGN_BIN))


def _switch_to_real_mode(ws_path: Path, product: str = "rollcall") -> None:
    _ensure_design_bin_on_path()
    from app_screen import workspace

    ws = workspace.Workspace(ws_path)
    run_file = ws_path / "run.json"
    if run_file.is_file():
        doc = json.loads(run_file.read_text(encoding="utf-8"))
        doc.pop("mode", None)
        if not doc.get("product"):
            doc["product"] = product
        run_file.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    else:
        ws.start(product)


def ensure_upstream_for_stage(
    stage: str,
    ws_path: Path,
    product: str = "rollcall",
    case_name: str = "rollcall-20261104",
) -> None:
    """Ensure host/upstream inputs exist in `ws_path` when running a single stage in isolation."""
    _switch_to_real_mode(ws_path, product)
    base = stage.removesuffix("_collect").removesuffix("_check").removesuffix("_finish")
    if (ws_path / "known-case").is_dir():
        case_src = ws_path / "known-case"
    elif (ws_path / ".case").is_dir():
        case_src = ws_path / ".case"
    else:
        case_src = DEFAULT_CASE_DIR

    if base == "intake":
        prepare_intake_inputs(ws_path, case_name)
        return

    if base == "existing":
        if not (ws_path / "01-request/requirements.json").is_file():
            run_stage("intake", ws_path, product=product, case_name=case_name)
        if not (ws_path / "02-existing/app.json").is_file() or not (ws_path / "02-existing/texts.json").is_file():
            prepare_existing_inputs(ws_path, case_name)
        return

    if base == "ground":
        if not (ws_path / "01-request/requirements.json").is_file():
            run_stage("intake", ws_path, product=product, case_name=case_name)
        if not (ws_path / "02-existing/journeys.json").is_file():
            run_stage("existing", ws_path, product=product, case_name=case_name)
        if not (ws_path / "03-ground/source/prep.json").is_file():
            prepare_ground_inputs(ws_path, case_src, product=product)
        return

    # For stages 4..8, if upstream folders are missing in ws_path, seed from .case or run upstream
    upstream_folders = {
        "directions": [("01-request", "requirements.json"), ("02-existing", "journeys.json"), ("03-ground", "inventory.json")],
        "gate_direction": [("04-directions", "directions.json")],
        "build": [("01-request", "requirements.json"), ("02-existing", "journeys.json"), ("03-ground", "inventory.json"), ("04-directions", "directions.json")],
        "checks": [("01-request", "requirements.json"), ("03-ground", "inventory.json"), ("05-build", "build.json")],
        "review": [("01-request", "requirements.json"), ("02-existing", "journeys.json"), ("03-ground", "inventory.json"), ("05-build", "build.json"), ("06-checks/round-1", "checks.json")],
        "show": [("05-build", "build.json"), ("06-checks/round-1", "review.json")],
        "gate_final": [("07-show", "showtell.json")],
        "handoff": [("01-request", "requirements.json"), ("03-ground", "inventory.json"), ("05-build", "build.json"), ("06-checks/round-1", "review.json"), ("07-show", "showtell.json")],
    }
    for folder, marker in upstream_folders.get(base, []):
        if not (ws_path / folder / marker).is_file() and (case_src / folder).is_dir():
            shutil.copytree(case_src / folder, ws_path / folder, dirs_exist_ok=True)
    if base in ("directions", "build", "checks", "review", "handoff"):
        tok_src = ws_path / "03-ground/design-files/tokens.json"
        tok_dst = ws_path / "03-ground/tokens.json"
        if tok_src.is_file() and not tok_dst.is_file():
            shutil.copy2(tok_src, tok_dst)
        design_md_dst = ws_path / "03-ground/design-files/DESIGN.md"
        design_md_src = case_src / "03-ground/design-files/DESIGN.md"
        if not design_md_src.is_file():
            design_md_src = DEFAULT_CASE_DIR / "03-ground/design-files/DESIGN.md"
        if not design_md_dst.is_file() and design_md_src.is_file():
            design_md_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(design_md_src, design_md_dst)


def run_step(
    step: str,
    workspace_dir: str | Path,
    product: str | None = "rollcall",
    raw: str = "",
    case_name: str = "rollcall-20261104",
) -> dict[str, Any]:
    """Run a single CLI step (`*_collect`, `*_check`, gate, or finish) in `mode="real"` through `design_app_screen.run_step`.

    If a stage finish step (`existing`, `ground`, `directions`, `review`) is called directly
    without a prior `*_collect` / `*_check` (as in `ORDER` in `test_design_app_screen_contracts.py`),
    automatically runs `*_collect` and `*_check` in `mode="real"` first so the real finish path succeeds.
    """
    _ensure_design_bin_on_path()
    import design_app_screen as cli
    from app_screen import checks

    ws_path = Path(workspace_dir).expanduser().resolve()
    prod = product or "rollcall"
    ensure_upstream_for_stage(step, ws_path, product=prod, case_name=case_name)

    if step in ("gate_direction", "gate_final"):
        gate_name = step.removeprefix("gate_")
        gate_raw = raw or json.dumps(load_gate_answer(gate_name, workspace_dir=ws_path), ensure_ascii=False)
        out = cli.run_step(step, str(ws_path), product, gate_raw)
        out["known_case_choice"] = load_gate_answer(gate_name, workspace_dir=ws_path).get("choice")
        return out

    if step == "intake_check":
        draft_raw = raw or json.dumps(draft_for_step("intake", ws_path, case_name=case_name), ensure_ascii=False)
        draft_path = ws_path / "01-request/draft.json"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(draft_raw + "\n", encoding="utf-8")
        return cli.run_step("intake_check", str(ws_path), product, draft_raw)

    if step in ("intake", "existing", "ground", "directions", "review"):
        check_rel = {
            "intake": "01-request/check.json",
            "existing": "02-existing/check.json",
            "ground": "03-ground/check.json",
            "directions": "04-directions/check.json",
            "review": "06-checks/round-1/check.json",
        }[step]
        draft_raw = raw or json.dumps(draft_for_step(step, ws_path, case_name=case_name), ensure_ascii=False)
        if not (ws_path / check_rel).is_file():
            if step == "directions":
                target_folder = ws_path / "04-directions"
                if target_folder.is_dir():
                    for child in list(target_folder.iterdir()):
                        if child.name != "gate_direction.json":
                            if child.is_dir():
                                shutil.rmtree(child)
                            else:
                                child.unlink()
            elif step == "review":
                (ws_path / "06-checks/round-1/review.json").unlink(missing_ok=True)
            cli.run_step(f"{step}_collect", str(ws_path), product, "")
            if step == "intake":
                draft_path = ws_path / "01-request/draft.json"
                draft_path.parent.mkdir(parents=True, exist_ok=True)
                draft_path.write_text(draft_raw + "\n", encoding="utf-8")
            chk = cli.run_step(f"{step}_check", str(ws_path), product, draft_raw)
            if chk.get("verdict") != "ok":
                raise HarnessCaseError(f"{step}_check failed in real mode: {chk}")
        return cli.run_step(step, str(ws_path), product, draft_raw)

    if step == "build":
        if not (ws_path / "04-directions/gate_direction.json").is_file():
            answer_gate("direction", ws_path)
        target_folder = ws_path / "05-build"
        if target_folder.is_dir():
            shutil.rmtree(target_folder)
        out = cli.run_step("build", str(ws_path), product, raw)
        draft_raw = json.dumps(draft_for_step("build", ws_path, case_name=case_name), ensure_ascii=False)
        chk = cli.run_step("build_check", str(ws_path), product, draft_raw)
        if chk.get("verdict") != "ok":
            raise HarnessCaseError(f"build_check failed in real mode: {chk}")
        cli.run_step("build_finish", str(ws_path), product, draft_raw)
        return out

    base = step.removesuffix("_collect").removesuffix("_check").removesuffix("_finish")
    is_collect = step.endswith("_collect")
    if not raw and base in ("intake", "existing", "ground", "directions", "build", "review") and not is_collect:
        raw = json.dumps(draft_for_step(base, ws_path, case_name=case_name), ensure_ascii=False)

    if step == "checks":
        with patch.object(checks, "measure", side_effect=synthesize_measures_for_workspace):
            return cli.run_step("checks", str(ws_path), product, raw)

    if step == "show":
        target_folder = ws_path / "07-show"
        if target_folder.is_dir():
            for child in list(target_folder.iterdir()):
                if child.name != "gate_final.json":
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
    elif step == "handoff":
        shutil.rmtree(ws_path / "08-handoff", ignore_errors=True)

    return cli.run_step(step, str(ws_path), product, raw)


def run_stage(
    stage: str,
    workspace_dir: str | Path,
    product: str = "rollcall",
    raw: str = "",
    case_name: str = "rollcall-20261104",
) -> dict[str, Any]:
    """Run a complete stage (`collect` -> `check` with model-boundary draft -> `finish`) in `mode="real"`."""
    ws_path = Path(workspace_dir).expanduser().resolve()
    ensure_upstream_for_stage(stage, ws_path, product=product, case_name=case_name)

    if stage in ("intake", "existing", "ground", "directions", "build", "review"):
        if stage in ("directions", "build"):
            # Clear any pre-baked directions.json or build.json so real scaffold_directions / scaffold_build runs
            target_folder = ws_path / ("04-directions" if stage == "directions" else "05-build")
            if target_folder.is_dir():
                for child in list(target_folder.iterdir()):
                    if child.name != "gate_direction.json":
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
        if stage == "review":
            (ws_path / "06-checks/round-1/review.json").unlink(missing_ok=True)
        collect_step = "build" if stage == "build" else f"{stage}_collect"
        finish_step = "build_finish" if stage == "build" else stage
        run_step(collect_step, ws_path, product=product, case_name=case_name)
        draft_raw = raw or json.dumps(draft_for_step(stage, ws_path, case_name=case_name), ensure_ascii=False)
        if stage == "intake":
            draft_path = ws_path / "01-request/draft.json"
            draft_path.parent.mkdir(parents=True, exist_ok=True)
            draft_path.write_text(draft_raw + "\n", encoding="utf-8")
        chk = run_step(f"{stage}_check", ws_path, product=product, raw=draft_raw, case_name=case_name)
        if chk.get("verdict") != "ok":
            raise HarnessCaseError(f"{stage}_check failed in real mode: {chk}")
        return run_step(finish_step, ws_path, product=product, raw=draft_raw, case_name=case_name)

    if stage in ("checks", "show", "handoff", "gate_final_next"):
        if stage == "show":
            shutil.rmtree(ws_path / "07-show", ignore_errors=True)
        elif stage == "handoff":
            shutil.rmtree(ws_path / "08-handoff", ignore_errors=True)
        return run_step(stage, ws_path, product=product, raw=raw, case_name=case_name)

    raise HarnessCaseError(f"unknown stage {stage!r}")


def answer_gate(
    gate_name: str,
    workspace_dir: str | Path,
    answer: dict[str, Any] | str | None = None,
    case_dir: str | Path | None = None,
    taste_file: Path | None = None,
) -> dict[str, Any]:
    """Feed a prepared gate answer through the real gate path (`mode="real"`)."""
    _ensure_design_bin_on_path()
    import design_app_screen as cli
    from app_screen import contracts, gates, workspace

    ws_path = Path(workspace_dir).expanduser().resolve()
    ensure_upstream_for_stage(f"gate_{gate_name}", ws_path)
    if answer is None:
        raw_json = json.dumps(load_gate_answer(gate_name, case_dir=case_dir, workspace_dir=ws_path), ensure_ascii=False)
    elif isinstance(answer, str):
        raw_json = answer
    else:
        raw_json = json.dumps(answer, ensure_ascii=False)

    if taste_file is not None:
        ws = workspace.Workspace(ws_path)
        step = f"gate_{gate_name}"
        ws.mark(step, "running")
        try:
            result = gates.answer(ws, gate_name, raw_json, taste_file=taste_file)
            files = contracts.validate(step, ws)
        except Exception as exc:
            ws.mark(step, "failed", str(exc))
            raise
        ws.mark(step, "done")
        known_choice = load_gate_answer(gate_name, case_dir=case_dir, workspace_dir=ws_path).get("choice")
        return {
            "ok": True,
            "valid": True,
            "step": step,
            "checked": len(files),
            "files": len(files),
            "known_case_choice": known_choice,
            **result,
        }

    out = cli.run_step(f"gate_{gate_name}", str(ws_path), None, raw_json)
    out["known_case_choice"] = load_gate_answer(gate_name, case_dir=case_dir, workspace_dir=ws_path).get("choice")
    return out


def run_all(
    case_or_workspace: str | Path | None,
    workspace_dir: str | Path | None = None,
    product: str = "rollcall",
    case_name: str = "rollcall-20261104",
    taste_file: Path | None = None,
) -> dict[str, Any]:
    """Prepare `workspace_dir` from `case_dir` and run all 8 stages + 2 gates at $0.

    Supports both `run_all(workspace_dir)` and `run_all(case_dir, workspace_dir)`.
    """
    _ensure_design_bin_on_path()
    from app_screen import contracts, workspace

    if workspace_dir is None:
        if case_or_workspace is None:
            raise HarnessCaseError("workspace_dir is required")
        case_dir: str | Path | None = None
        ws_target: str | Path = case_or_workspace
    else:
        case_dir = case_or_workspace
        ws_target = workspace_dir

    ws_path = prepare_workspace(case_dir, ws_target, product=product, case_name=case_name)
    results: dict[str, Any] = {}

    for st in ("intake", "existing", "ground", "directions"):
        results[st] = run_stage(st, ws_path, product=product, case_name=case_name)

    results["gate_direction"] = answer_gate(
        "direction", ws_path, case_dir=case_dir, taste_file=taste_file
    )

    for st in ("build", "checks", "review", "show"):
        results[st] = run_stage(st, ws_path, product=product, case_name=case_name)

    results["gate_final"] = answer_gate(
        "final", ws_path, case_dir=case_dir, taste_file=taste_file
    )
    results["gate_final_next"] = run_stage("gate_final_next", ws_path, product=product, case_name=case_name)
    results["handoff"] = run_stage("handoff", ws_path, product=product, case_name=case_name)

    ws = workspace.Workspace(ws_path)
    contract_counts: dict[str, int] = {}
    for st in workspace.STAGES + ("gate_direction", "review", "gate_final"):
        contract_counts[st] = len(contracts.validate(st, ws))

    return {
        "ok": True,
        "workspace": str(ws_path),
        "cost_usd": 0.0,
        "live_model_calls": 0,
        "stages": results,
        "contract_files": contract_counts,
    }
