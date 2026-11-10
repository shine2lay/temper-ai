"""Workspace preparation from a frozen known case for `design_app_screen_v1` real-mode harness runs.

Seeds only the host-level inputs that precede or sit outside the workflow's stages:
- Stage 1 input: `01-request/sources.json`
- Stage 2 host capture: `02-existing/app.json`, `audit.json`, `texts.json`, `capture.json`, `sheet.png`, `screens/*.png`
- Stage 3 host prep: `03-ground/source/pack.json`, `source/prep.json`, `product/`, `fixture.json`, `fixtures/`, `tokens.json`
- Gate answers: read from `<case_dir>/gates/gate_<name>.json` and fed through the real gate API/CLI in `mode="real"`.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from .replay import BENCH_DEFAULT_COMMIT, load_recorded_json

HERE = Path(__file__).resolve().parent
DESIGN_BIN = HERE.parent
REPO_ROOT = HERE.parents[3]
DEFAULT_CASE_DIR = REPO_ROOT / "tests" / "design_app_screen_case" / "rollcall-20261104"

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c49444154789c63f8cfc0000003010100c9fe92ef0000000049454e44ae426082"
)


class HarnessCaseError(ValueError):
    """Raised when a known case or prepared input is missing or invalid."""


def _ensure_design_bin_on_path() -> None:
    if str(DESIGN_BIN) not in sys.path:
        sys.path.insert(0, str(DESIGN_BIN))


def ensure_playable_case(case_dir: str | Path, target_dir: str | Path) -> Path:
    """Create a complete frozen copy of `case_dir` at `target_dir` with placeholder binary/HTML assets filled in."""
    _ensure_design_bin_on_path()
    from app_screen import known_case

    src = Path(case_dir).expanduser().resolve()
    if not src.is_dir():
        raise HarnessCaseError(f"known case directory {src} does not exist")
    dst = Path(target_dir).expanduser().resolve()
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    html = (
        '<!doctype html><html data-st-interactive data-st-state="default" '
        'data-st-states="default,loading,empty"><meta charset="utf-8">'
        "<title>RollCall</title><body></body></html>\n"
    )
    audit_path = dst / "02-existing/audit.json"
    if audit_path.is_file():
        for s in json.loads(audit_path.read_text(encoding="utf-8")).get("screens", []):
            p = dst / "02-existing" / s["capture"]
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.is_file():
                p.write_bytes(PNG_1X1)
    dirs_path = dst / "04-directions/directions.json"
    if dirs_path.is_file():
        for d in json.loads(dirs_path.read_text(encoding="utf-8")).get("directions", []):
            p = dst / "04-directions" / d["page"]
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.is_file():
                p.write_text(html, encoding="utf-8")
    build_path = dst / "05-build/build.json"
    if build_path.is_file():
        bdoc = json.loads(build_path.read_text(encoding="utf-8"))
        page_p = dst / "05-build" / bdoc["page"]
        page_p.parent.mkdir(parents=True, exist_ok=True)
        if not page_p.is_file():
            page_p.write_text(html, encoding="utf-8")
        shell_p = dst / "05-build/shell/page.html"
        shell_p.parent.mkdir(parents=True, exist_ok=True)
        if not shell_p.is_file():
            shell_p.write_text(html, encoding="utf-8")
        for s in bdoc.get("screens", []):
            sp = dst / "05-build" / s["file"]
            sp.parent.mkdir(parents=True, exist_ok=True)
            if not sp.is_file():
                sp.write_text("// placeholder\n", encoding="utf-8")
    if not (dst / "FREEZE.json").is_file():
        known_case.freeze(dst, "rollcall", "rm-harness")
    return dst


def prepare_intake_inputs(ws_path: Path, case_name: str = "rollcall-20261104") -> None:
    """Write `01-request/sources.json` if not already present in the workspace."""
    _ensure_design_bin_on_path()
    from app_screen import contracts
    from app_screen.model_step import write_json

    sources_path = ws_path / "01-request/sources.json"
    if not sources_path.is_file():
        sources = load_recorded_json("intake_sources.json", case_name)
        write_json(sources_path, sources)
    loaded = json.loads(sources_path.read_text(encoding="utf-8"))
    problems = contracts.check_json("sources", loaded, "01-request/sources.json")
    if problems:
        raise HarnessCaseError("invalid 01-request/sources.json: " + "; ".join(problems[:5]))


def prepare_existing_inputs(ws_path: Path, case_name: str = "rollcall-20261104") -> None:
    """Write Stage 2 host-capture files into `02-existing/` so `existing_collect`, `existing_check`, and `existing_finish` run in real mode."""
    _ensure_design_bin_on_path()
    from app_screen import contracts, existing_measures
    from app_screen.model_step import write_json

    ex_dir = ws_path / "02-existing"
    ex_dir.mkdir(parents=True, exist_ok=True)

    app_doc = load_recorded_json("existing_app.json", case_name)
    measured_doc = load_recorded_json("existing_measured.json", case_name)
    edraft = load_recorded_json("existing_draft.json", case_name)

    cited_measures: dict[tuple[str, str], Any] = {}
    cited_totals: dict[str, dict[str, int]] = {}
    text_refs_by_cap: dict[str, list[str]] = {}

    for j in edraft.get("journeys", []):
        for k in j.get("keep", []):
            for r in k.get("evidence", []):
                if "measure" in r:
                    cited_measures[(r["capture"], r["measure"])] = r["value"]
                elif "total" in r:
                    cited_totals[r["total"]] = {"value": r["value"], "of": r.get("of", 26)}
                elif "text" in r:
                    text_refs_by_cap.setdefault(r["capture"], []).append(r["text"])
    for p in edraft.get("problems", []):
        for r in p.get("evidence", []):
            if "measure" in r:
                cited_measures[(r["capture"], r["measure"])] = r["value"]
            elif "total" in r:
                cited_totals[r["total"]] = {"value": r["value"], "of": r.get("of", 26)}
            elif "text" in r:
                text_refs_by_cap.setdefault(r["capture"], []).append(r["text"])

    base_measures = {
        "layout_width_px": 390,
        "wider_than_screen_px": 0,
        "side_scrolling_boxes": 0,
        "side_scroll_content_px": 0,
        "side_scroll_visible_px": 0,
        "targets_under_24px": 0,
        "text_runs_under_16px": 0,
        "text_runs_under_12px": 0,
        "body_text_runs": 4,
        "body_text_runs_under_16px": 0,
        "smallest_text_px": 14,
        "distinct_text_sizes": 4,
        "truncated_count": 0,
        "truncated_text": [],
        "content_px_in_first_view": 600,
        "screens_tall": 1.2,
        "always_open_blocks": 2,
        "tabbar_rows": 1,
        "tabbar_px": 48,
        "error_messages": 0,
        "error_messages_without_action": 0,
        "missing_values": 0,
        "missing_value_text": [],
        "page_errors": 0,
        "console_errors": [],
        "failed_requests": [],
    }

    screens: list[dict[str, Any]] = []
    texts: dict[str, dict[str, list[str]]] = {}
    for s in app_doc["screens"]:
        sid = s["id"]
        for st, spec in s["states"].items():
            for w in spec["widths"]:
                cid = f"{sid}-{w}-{st}"
                m = dict(base_measures)
                lw = measured_doc.get("layout_width_px", {}).get(cid, w)
                m["layout_width_px"] = lw
                m["wider_than_screen_px"] = max(0, lw - w)
                for (rcid, mkey), mval in cited_measures.items():
                    if rcid == cid:
                        m[mkey] = mval
                for ex in measured_doc.get("exact", []):
                    if ex["capture"] == cid:
                        m[ex["measure"]] = ex["value"]
                rel_cap = f"captures/{cid}.png"
                cap_path = ex_dir / rel_cap
                cap_path.parent.mkdir(parents=True, exist_ok=True)
                if not cap_path.is_file():
                    cap_path.write_bytes(PNG_1X1)
                screens.append({
                    "id": cid,
                    "screen": sid,
                    "name": s["name"],
                    "width": w,
                    "height": app_doc["sizes"][str(w)]["height"],
                    "state": st,
                    "what": spec["what"],
                    "capture": rel_cap,
                    "measures": m,
                })
                runs = text_refs_by_cap.get(cid, [s["name"]])
                texts[cid] = {"first_view": runs, "all": runs}

    if "wider_at_320" in measured_doc:
        cited_totals.setdefault("layout_width_px@320", measured_doc["wider_at_320"])

    audit_doc = {
        "source": "RollCall at 81117dd, captured look-only on loopback by design_app_screen.py capture",
        "product": app_doc["product"],
        "commit": BENCH_DEFAULT_COMMIT,
        "ci_conclusion": "success",
        "allow_red_commit": False,
        "notes": existing_measures.NOTES,
        "screens": screens,
        "totals": cited_totals,
    }
    problems = contracts.check_json("audit", audit_doc, "02-existing/audit.json")
    if problems:
        raise HarnessCaseError("invalid synthesized 02-existing/audit.json: " + "; ".join(problems[:5]))

    write_json(ex_dir / "app.json", app_doc)
    write_json(ex_dir / "audit.json", audit_doc)
    write_json(ex_dir / "texts.json", texts)
    write_json(ex_dir / "capture.json", {
        "product": app_doc["product"],
        "source": audit_doc["source"],
        "commit": BENCH_DEFAULT_COMMIT,
        "short_commit": BENCH_DEFAULT_COMMIT[:7],
        "ref": "origin/master",
        "reused": False,
        "ci_conclusion": "success",
        "allow_red_commit": False,
        "captures": len(screens),
        "failed": [],
    })
    write_json(ex_dir / "sheet.json", {
        "width": app_doc["sheet_width"],
        "tiles": len([c for c in screens if c["width"] == app_doc["sheet_width"]]),
        "file": "sheet.png",
    })
    (ex_dir / "sheet.png").write_bytes(PNG_1X1)


def prepare_ground_inputs(
    ws_path: Path,
    case_dir: Path,
    product: str = "rollcall",
    case_name: str = "rollcall-20261104",
) -> None:
    """Write Stage 3 host-prep files into `03-ground/` using the frozen case's recorded prep bundle and fixture."""
    _ensure_design_bin_on_path()
    from app_screen import contracts, ground_host
    from app_screen.model_step import write_json

    g_dir = ws_path / "03-ground"
    g_dir.mkdir(parents=True, exist_ok=True)
    # Remove any pre-existing DESIGN.md so ground_collect sees status="none" as in the frozen RollCall v3 case
    (g_dir / "design-files/DESIGN.md").unlink(missing_ok=True)

    bundle = load_recorded_json("ground_prep_bundle.json", case_name)
    notes_list = []
    for name, n in bundle["notes"].items():
        rel = f"product/notes/{name}.md"
        non_empty = set(n.get("non_empty", []))
        conds = n.get("conditions", {})
        lines = []
        for idx in range(1, int(n.get("total_lines", 0)) + 1):
            if idx in non_empty:
                lines.append(conds.get(str(idx), "x"))
            else:
                lines.append("")
        write_json(g_dir / rel, "\n".join(lines) + "\n")
        notes_list.append({"name": name, "from": n["from"], "file": rel})

    case_fixture = case_dir / "03-ground/fixture.json"
    if not case_fixture.is_file():
        case_fixture = DEFAULT_CASE_DIR / "03-ground/fixture.json"
    if not case_fixture.is_file():
        raise HarnessCaseError(f"missing 03-ground/fixture.json in {case_dir}")
    shutil.copy2(case_fixture, g_dir / "fixture.json")
    fx = {
        "from": str(case_fixture),
        "sha256": ground_host.sha256_file(g_dir / "fixture.json"),
        "invariants": bundle["invariants"],
    }

    pack_doc = {
        "version": 1,
        "product": product,
        "name": product,
        "fixture": False,
        "registry_entry": None,
        "files": {},
        "design_files": {},
        "current_state": {},
    }
    caps_bundle = dict(bundle["capabilities"])
    caps_bundle["items"] = [
        {
            "kind": item["kind"],
            "key": item["key"],
            "group": item.get("group") or "app",
            "intent": item.get("intent") or "x",
            "where": item.get("where") or "app",
        }
        for item in bundle["capabilities"]["items"]
    ]
    prep_doc = {
        "product": product,
        "capabilities": caps_bundle,
        "notes": notes_list,
        "fixture": fx,
        "design_files": {"registered": False, "from": f"{product}: no design files"},
        "commit": bundle["commit"],
    }
    problems = contracts.check_json("ground_prep", prep_doc, "03-ground/source/prep.json")
    if problems:
        raise HarnessCaseError("invalid 03-ground/source/prep.json: " + "; ".join(problems[:5]))

    write_json(g_dir / "source/pack.json", pack_doc)
    write_json(g_dir / "source/prep.json", prep_doc)

    case_tokens = case_dir / "03-ground/design-files/tokens.json"
    if not case_tokens.is_file():
        case_tokens = DEFAULT_CASE_DIR / "03-ground/design-files/tokens.json"
    if not case_tokens.is_file():
        raise HarnessCaseError(f"missing tokens.json in {case_dir}")
    (g_dir / "design-files").mkdir(parents=True, exist_ok=True)
    shutil.copy2(case_tokens, g_dir / "design-files/tokens.json")
    shutil.copy2(case_tokens, g_dir / "tokens.json")


def prepare_workspace(
    case_or_workspace: str | Path | None,
    workspace_dir: str | Path | None = None,
    product: str = "rollcall",
    case_name: str = "rollcall-20261104",
) -> Path:
    """Prepare `workspace_dir` from `case_dir` for a full real-mode harness run.

    Supports both `prepare_workspace(workspace_dir)` and `prepare_workspace(case_dir, workspace_dir)`.
    """
    _ensure_design_bin_on_path()
    from app_screen import known_case, workspace

    if workspace_dir is None:
        if case_or_workspace is None:
            raise HarnessCaseError("workspace_dir is required")
        ws_path = Path(case_or_workspace).expanduser().resolve()
        src_case = DEFAULT_CASE_DIR
    else:
        src_case = Path(case_or_workspace).expanduser().resolve() if case_or_workspace else DEFAULT_CASE_DIR
        ws_path = Path(workspace_dir).expanduser().resolve()
    if not src_case.is_dir():
        raise HarnessCaseError(f"case_dir {src_case} does not exist")

    ws_path.mkdir(parents=True, exist_ok=True)

    # If the case has FREEZE.json and all files exist, pack it so known-case/gates is available for inspection.
    if (src_case / "FREEZE.json").is_file():
        try:
            known_case.pack(src_case, ws_path)
        except known_case.KnownCaseError:
            pass
    if (src_case / "gates").is_dir() and not (ws_path / "known-case/gates").is_dir():
        (ws_path / "known-case").mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_case / "gates", ws_path / "known-case/gates", dirs_exist_ok=True)

    ws = workspace.Workspace(ws_path)
    run_file = ws_path / "run.json"
    if run_file.is_file():
        doc = json.loads(run_file.read_text(encoding="utf-8"))
        doc.pop("mode", None)
        doc["product"] = product
        run_file.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    else:
        ws.start(product)

    prepare_intake_inputs(ws_path, case_name)
    prepare_existing_inputs(ws_path, case_name)
    prepare_ground_inputs(ws_path, src_case, product)
    return ws_path


def load_gate_answer(
    gate_name: str,
    case_dir: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Load the prepared gate answer (`direction` or `final`) from `case_dir` or `workspace_dir/.case/gates`."""
    if gate_name not in ("direction", "final"):
        raise HarnessCaseError(f"unknown gate {gate_name!r}; expected 'direction' or 'final'")
    filename = f"gate_{gate_name}.json"
    candidates: list[Path] = []
    if case_dir is not None:
        candidates.append(Path(case_dir).expanduser().resolve() / "gates" / filename)
    if workspace_dir is not None:
        ws_resolved = Path(workspace_dir).expanduser().resolve()
        candidates.append(ws_resolved / "known-case" / "gates" / filename)
        candidates.append(ws_resolved / ".case" / "gates" / filename)
    candidates.append(DEFAULT_CASE_DIR / "gates" / filename)

    allowed_fields = ("choice", "decided_by", "owner_words", "source", "reason", "comments", "at")
    for path in candidates:
        if path.is_file():
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or "choice" not in doc:
                raise HarnessCaseError(f"invalid gate answer in {path}: missing 'choice'")
            return {k: v for k, v in doc.items() if k in allowed_fields}
    raise HarnessCaseError(f"prepared gate answer {filename} not found in {[str(c) for c in candidates]}")
