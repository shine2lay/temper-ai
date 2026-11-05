"""Stage 2's capture, on the host: the product as it is today, captured and measured into 02-existing/.

    design_app_screen.py capture --product P --workspace W

Workers reach neither the app nor a browser, so this runs on the host before the workflow's existing stage
(as intake's collect does). It loads the product's app file (product_app.py), starts a throwaway copy
(throwaway_app.py: the pinned commit in its own checkout with a fresh seeded database, or a static folder; never
the live server), opens every screen x state x width look-only in Playwright (existing_capture.mjs, measuring
with measure_in_page.js) and writes:

    02-existing/captures/<screen>-<width>-<state>.png   first view of each capture
    02-existing/audit.json     every capture's measures (existing_measures.measures) + per-width totals
    02-existing/texts.json     every capture's visible text runs (all, and those in the first view)
    02-existing/app.json       the product's job, screens, states and widths, for the model and the checks
    02-existing/sheet.png      the sheet width's first views in one labelled PNG (existing_sheet.py)
    02-existing/capture.json   the record: app file, commit, captures, failures, raw measurements file

Any failed capture fails the command loud, naming each one. Host only (Playwright, Pillow, PyYAML).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import existing_measures, existing_sheet, product_app, throwaway_app
from .workspace import Workspace

HERE = Path(__file__).resolve().parent
CAPTURE_SCRIPT = HERE / "existing_capture.mjs"
MEASURE_SCRIPT = HERE / "measure_in_page.js"
AUDIT, TEXTS, APP, SHEET, SHEET_INFO, RECORD, RAW = (
    "audit.json", "texts.json", "app.json", "sheet.png", "sheet.json", "capture.json", "raw.json")
CAPTURES = "captures"


class CaptureError(RuntimeError):
    """The capture could not be made; the message names each failed capture or step."""


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _open_to_worker(folder: Path) -> None:
    """The workflow's worker writes as another user: the stage folder and its files stay writable to it."""
    for path in [folder, *folder.rglob("*")]:
        os.chmod(path, 0o777 if path.is_dir() else 0o666)


def _plan(app: dict, caps: list[dict], out_dir: Path, state_dir: Path) -> dict:
    return {"base_url": app["base_url"], "login": app.get("login"), "page": app["page"],
            "captures": [{k: c[k] for k in ("id", "width", "height", "phone", "account", "delay_api", "steps")}
                         for c in caps],
            "out_dir": str(out_dir), "state_dir": str(state_dir), "measure_script": str(MEASURE_SCRIPT)}


def app_summary(app: dict) -> dict:
    """What the model and the checks need of the app file: job, screens, states, widths."""
    return {"product": app["product"], "name": app["name"], "job": app["job"], "sheet_width": app["sheet_width"],
            "sizes": {w: s for w, s in app["sizes"].items()},
            "screens": [{"id": s["id"], "name": s["name"],
                         "states": {st: {"what": spec.get("what") or s.get("what") or s["name"],
                                         "widths": spec.get("widths", s["widths"])}
                                    for st, spec in s["states"].items()}}
                        for s in app["screens"]]}


def audit_from(app: dict, caps: list[dict], raw: dict) -> tuple[dict, dict]:
    """audit.json and texts.json from the capture list and the raw in-page measurements."""
    screens, texts = [], {}
    for c in caps:
        r = raw[c["id"]]
        screens.append({"id": c["id"], "screen": c["screen"], "name": c["name"], "width": c["width"],
                        "height": c["height"], "state": c["state"], "what": c["what"],
                        "capture": f"{CAPTURES}/{c['id']}.png", "measures": existing_measures.measures(r, c["width"])})
        texts[c["id"]] = {"first_view": existing_measures.first_view_text(r), "all": existing_measures.text_runs(r)}
    commit = app["app"].get("commit")
    audit = {"source": f"{app['name']} {'at ' + commit if commit else '(static)'}, captured look-only on loopback "
                       f"by design_app_screen.py capture ({datetime.now(UTC).isoformat(timespec='seconds')})",
             "product": app["product"], "screens": screens, "totals": existing_measures.totals(screens),
             "notes": existing_measures.NOTES}
    return audit, texts


def capture(product: str, workspace: str, store: Path | None = None) -> dict:
    app = product_app.load(product, store)
    ws = Workspace(workspace)
    ws.start(product, "real")
    folder = ws.folder("existing")
    out_dir = folder / CAPTURES
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    caps = product_app.captures(app)
    with tempfile.TemporaryDirectory(prefix="app-screen-capture-") as tmp:
        plan_file = Path(tmp) / "plan.json"
        _write(plan_file, _plan(app, caps, out_dir, Path(tmp)))
        with throwaway_app.Throwaway(app):
            try:
                done = subprocess.run(["node", str(CAPTURE_SCRIPT), str(plan_file)], capture_output=True,
                                      text=True, timeout=60 * 60)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise CaptureError(f"the browser capture did not finish: {exc.__class__.__name__}: {exc}") from None
        if done.returncode:
            raise CaptureError(f"the browser capture exited {done.returncode}: {(done.stderr or done.stdout)[-600:]}")
    raw_file = out_dir / RAW
    raw = json.loads(raw_file.read_text(encoding="utf-8")) if raw_file.is_file() else {}
    shutil.move(raw_file, folder / RAW) if raw_file.is_file() else None
    failed = {c["id"]: raw.get(c["id"], {}).get("failed", "not captured") for c in caps
              if c["id"] not in raw or "failed" in raw[c["id"]] or not (out_dir / f"{c['id']}.png").is_file()}
    record = {"app_file": app["path"], "product": product, "commit": app["app"].get("commit"),
              "captures": len(caps), "failed": failed, "raw": RAW,
              "at": datetime.now(UTC).isoformat(timespec="seconds")}
    _write(folder / RECORD, record)
    if failed:
        _open_to_worker(folder)
        shown = "; ".join(f"{cid}: {why}" for cid, why in list(failed.items())[:12])
        raise CaptureError(f"{len(failed)} of {len(caps)} capture(s) failed: {shown}")
    return write_outputs(app, caps, raw, folder)


def remeasure(product: str, workspace: str, store: Path | None = None) -> dict:
    """Rebuild audit, texts, app and sheet from a finished capture's raw.json and PNGs (no browser, no app):
    for a change to the measures or the sheet, so the same captures are read again."""
    app = product_app.load(product, store)
    folder = Workspace(workspace).folder("existing")
    raw_file = folder / RAW
    if not raw_file.is_file():
        raise CaptureError(f"{raw_file} is missing: run the capture first")
    return write_outputs(app, product_app.captures(app), json.loads(raw_file.read_text(encoding="utf-8")), folder)


def write_outputs(app: dict, caps: list[dict], raw: dict, folder: Path) -> dict:
    out_dir = folder / CAPTURES
    audit, texts = audit_from(app, caps, raw)
    _write(folder / AUDIT, audit)
    _write(folder / TEXTS, texts)
    _write(folder / APP, app_summary(app))
    sheet_caps = [(c["id"], out_dir / f"{c['id']}.png") for c in caps if c["width"] == app["sheet_width"]]
    sheet = existing_sheet.build(sheet_caps, folder / SHEET)
    _write(folder / SHEET_INFO, sheet)
    _open_to_worker(folder)
    return {"captures": len(caps), "failed": 0, "sheet": {k: sheet[k] for k in ("bytes", "width", "height")},
            "sheet_tiles": len(sheet["tiles"]), "written": str(folder)}
