"""Stage 2's capture, on the host: the product as it is today, captured and measured into 02-existing/.

    design_app_screen.py capture --product P --repo R --base-url URL --workspace W [--credentials ...]

Workers reach neither the app nor a browser, so this runs on the host before the workflow's existing stage
(as intake's collect does). It loads the product's design spec from <repo>/.temper/design/app.yaml
(product_app.py), connects to a provisioned instance over HTTP and Playwright (app_instance.py: checks
GET {base_url}/api/health for {version, commit}, logs in declared accounts, never live production, no build
or process management), opens every screen x state x width look-only in Playwright (existing_capture.mjs,
measuring with measure_in_page.js) and writes:

    02-existing/captures/<screen>-<width>-<state>.png   first view of each capture
    02-existing/audit.json     every capture's measures (existing_measures.measures) + per-width totals
    02-existing/texts.json     every capture's visible text runs (all, and those in the first view)
    02-existing/app.json       the product's job, screens, states and widths, for the model and the checks
    02-existing/sheet.png      the sheet width's first views in one labelled PNG (existing_sheet.py)
    02-existing/capture.json   the record: app file, base_url, commit, version, accounts, captures, failures

Any failed capture fails the command loud, naming each one. Host only (Playwright, Pillow, PyYAML).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import app_instance, existing_measures, existing_sheet, product_app
from .workspace import Workspace

HERE = Path(__file__).resolve().parent
CAPTURE_SCRIPT = HERE / "existing_capture.mjs"
MEASURE_SCRIPT = HERE / "measure_in_page.js"
AUDIT, TEXTS, APP, SHEET, SHEET_INFO, RECORD, RAW = (
    "audit.json", "texts.json", "app.json", "sheet.png", "sheet.json", "capture.json", "raw.json")
CAPTURES = "captures"


class CaptureError(RuntimeError):
    """The capture could not be made; the message names each failed capture or step."""


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _open_to_worker(folder: Path) -> None:
    """The workflow's worker writes as another user: the stage folder and its files stay writable to it."""
    for path in [folder, *folder.rglob("*")]:
        try:
            os.chmod(path, 0o777 if path.is_dir() else 0o666)
        except OSError:
            pass


def app_summary(app: dict[str, Any]) -> dict[str, Any]:
    """What the model and the checks need of the app file: job, screens, states, widths, and commit/version."""
    out: dict[str, Any] = {
        "product": app["product"],
        "name": app["name"],
        "job": app["job"],
        "sheet_width": app["sheet_width"],
        "sizes": {w: s for w, s in app["sizes"].items()},
        "screens": [
            {
                "id": s["id"],
                "name": s["name"],
                "states": {
                    st: {
                        "what": spec.get("what") or s.get("what") or s["name"],
                        "widths": spec.get("widths", s["widths"]),
                    }
                    for st, spec in s["states"].items()
                },
            }
            for s in app["screens"]
        ],
    }
    for k in ("commit", "version", "base_url", "spec_sha256", "path"):
        if app.get(k) is not None:
            out["spec_path" if k == "path" else k] = app[k]
    return out


def audit_from(app: dict[str, Any], caps: list[dict[str, Any]], raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """audit.json and texts.json from the capture list and the raw in-page measurements."""
    screens, texts = [], {}
    for c in caps:
        r = raw[c["id"]]
        screens.append({
            "id": c["id"],
            "screen": c["screen"],
            "name": c["name"],
            "width": c["width"],
            "height": c["height"],
            "state": c["state"],
            "what": c["what"],
            "capture": f"{CAPTURES}/{c['id']}.png",
            "measures": existing_measures.measures(r, c["width"]),
        })
        texts[c["id"]] = {
            "first_view": existing_measures.first_view_text(r),
            "all": existing_measures.text_runs(r),
        }
    commit = app.get("commit")
    version = app.get("version")
    base_url = app.get("base_url")
    audit: dict[str, Any] = {
        "source": f"{app['name']} {'at ' + commit if commit else '(static)'}, captured look-only "
                  f"by design_app_screen.py capture ({datetime.now(UTC).isoformat(timespec='seconds')})",
        "product": app["product"],
        "screens": screens,
        "totals": existing_measures.totals(screens),
        "notes": existing_measures.NOTES,
    }
    if commit is not None:
        audit["commit"] = commit
    if version is not None:
        audit["version"] = version
    if base_url is not None:
        audit["base_url"] = base_url
    return audit, texts


def shoot(instance_or_app: app_instance.AppInstance | dict[str, Any],
          caps: list[dict[str, Any]], out_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """Open the given captures against a provisioned instance into out_dir: (raw measurements by capture id,
    failed ones with why). out_dir/raw.json is left for the caller to move."""
    if isinstance(instance_or_app, app_instance.AppInstance):
        inst = instance_or_app
    else:
        base_url = instance_or_app.get("base_url") or os.environ.get("APP_SCREEN_BASE_URL", "")
        creds = instance_or_app.get("credentials") or os.environ.get("APP_SCREEN_CREDENTIALS")
        inst = app_instance.AppInstance(instance_or_app, base_url, creds)
    try:
        raw, failed_summary = inst.shoot(caps, out_dir)
    except app_instance.AppInstanceError as exc:
        raise CaptureError(str(exc)) from None
    failed = dict(failed_summary)
    for c in caps:
        cid = c["id"]
        if cid not in raw or "failed" in raw[cid] or not (out_dir / f"{cid}.png").is_file():
            failed.setdefault(cid, raw.get(cid, {}).get("failed", "not captured"))
    return raw, failed


def _record(app: dict[str, Any], caps: list[dict[str, Any]], failed: dict[str, str], **extra: Any) -> dict[str, Any]:
    return {
        "app_file": app.get("path"),
        "product": app["product"],
        "spec_sha256": app.get("spec_sha256"),
        "base_url": extra.pop("base_url", app.get("base_url")),
        "commit": extra.pop("commit", app.get("commit")),
        "version": extra.pop("version", app.get("version")),
        "accounts": {c["id"]: c.get("account") for c in caps},
        "captures": len(caps),
        "failed": failed,
        "raw": RAW,
        **extra,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _fail(folder: Path, failed: dict[str, str], total: int) -> None:
    _open_to_worker(folder)
    shown = "; ".join(f"{cid}: {why}" for cid, why in list(failed.items())[:12])
    raise CaptureError(f"{len(failed)} of {total} capture(s) failed: {shown}")


def _resolve_instance(app: dict[str, Any], *,
                      base_url: str | None = None,
                      credentials: dict[str, str] | str | None = None,
                      version: str | None = None,
                      health_opener: Any = None,
                      opener: Any = None,
                      instance: app_instance.AppInstance | None = None) -> app_instance.AppInstance:
    if instance is not None:
        return instance
    eff_url = base_url or app.get("base_url") or os.environ.get("APP_SCREEN_BASE_URL", "")
    eff_creds = credentials if credentials is not None else os.environ.get("APP_SCREEN_CREDENTIALS")
    return app_instance.AppInstance(
        app,
        eff_url,
        eff_creds,
        version=version,
        health_opener=health_opener or opener,
    )


def capture(product: str | Path, workspace: str | Path, store: Path | None = None, *,
            base_url: str | None = None,
            credentials: dict[str, str] | str | None = None,
            version: str | None = None,
            health_opener: Any = None,
            opener: Any = None,
            instance: app_instance.AppInstance | None = None) -> dict[str, Any]:
    app = product_app.load(product, store)
    inst = _resolve_instance(
        app,
        base_url=base_url,
        credentials=credentials,
        version=version,
        health_opener=health_opener,
        opener=opener,
        instance=instance,
    )
    app["base_url"] = inst.base_url
    app["commit"] = inst.commit
    app["version"] = inst.version

    Path(workspace).mkdir(parents=True, exist_ok=True)
    ws = Workspace(workspace)
    ws.start(app["product"])
    folder = ws.folder("existing")
    out_dir = folder / CAPTURES
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    caps = product_app.captures(app)
    raw, failed = shoot(inst, caps, out_dir)
    if (out_dir / RAW).is_file():
        shutil.move(out_dir / RAW, folder / RAW)
    else:
        _write(folder / RAW, raw)
    _write(folder / RECORD, _record(app, caps, failed))
    if failed:
        _fail(folder, failed, len(caps))
    return write_outputs(app, caps, raw, folder)


def recapture(product: str | Path, workspace: str | Path, screens: list[str], store: Path | None = None, *,
              base_url: str | None = None,
              credentials: dict[str, str] | str | None = None,
              version: str | None = None,
              health_opener: Any = None,
              opener: Any = None,
              instance: app_instance.AppInstance | None = None,
              pre_captured_dir: Path | None = None,
              pre_raw: dict[str, Any] | None = None) -> dict[str, Any]:
    """Step 4's delta: capture again only the given screens' captures, over a stored capture prepare copied in
    (captures/ and raw.json); every other capture's PNG and raw measurements stay byte-identical. Then audit,
    texts, app and sheet are rebuilt over all captures (the kept ones measure the same from the same raw)."""
    app = product_app.load(product, store)
    folder = Workspace(workspace).folder("existing")
    out_dir, raw_file = folder / CAPTURES, folder / RAW
    if not raw_file.is_file() or not out_dir.is_dir():
        raise CaptureError(f"{folder}: captures/ and {RAW} must be copied from the store before a delta")
    caps = product_app.captures(app)
    known = {c["screen"] for c in caps}
    if not screens or set(screens) - known:
        raise CaptureError(f"recapture needs screens of the app file; got {screens}, unknown "
                           f"{sorted(set(screens) - known)}")
    todo = [c for c in caps if c["screen"] in screens]
    kept = json.loads(raw_file.read_text(encoding="utf-8"))
    missing = [c["id"] for c in caps if c not in todo and (c["id"] not in kept
                                                           or not (out_dir / f"{c['id']}.png").is_file())]
    if missing:
        raise CaptureError(f"the stored capture lacks {len(missing)} kept capture(s): {', '.join(missing[:8])}")

    inst = _resolve_instance(
        app,
        base_url=base_url,
        credentials=credentials,
        version=version,
        health_opener=health_opener,
        opener=opener,
        instance=instance,
    )
    app["base_url"] = inst.base_url
    app["commit"] = inst.commit
    app["version"] = inst.version

    if pre_captured_dir is not None and pre_raw is not None:
        raw_new = {c["id"]: pre_raw[c["id"]] for c in todo}
        for c in todo:
            shutil.copyfile(pre_captured_dir / f"{c['id']}.png", out_dir / f"{c['id']}.png")
    else:
        with tempfile.TemporaryDirectory(prefix="app-screen-recapture-") as tmp:
            raw_new, failed = shoot(inst, todo, Path(tmp))
            if failed:
                _write(folder / RECORD, _record(app, caps, failed, delta=[c["id"] for c in todo]))
                _fail(folder, failed, len(todo))
            for c in todo:
                shutil.copyfile(Path(tmp) / f"{c['id']}.png", out_dir / f"{c['id']}.png")
    raw = {c["id"]: raw_new[c["id"]] if c in todo else kept[c["id"]] for c in caps}
    _write(raw_file, raw)
    _write(folder / RECORD, _record(app, caps, {}, delta=[c["id"] for c in todo], screens=list(screens)))
    return {**write_outputs(app, caps, raw, folder), "recaptured": [c["id"] for c in todo]}


def remeasure(product: str | Path, workspace: str | Path, store: Path | None = None) -> dict[str, Any]:
    """Rebuild audit, texts, app and sheet from a finished capture's raw.json and PNGs (no browser, no app):
    for a change to the measures or the sheet, so the same captures are read again."""
    app = product_app.load(product, store)
    folder = Workspace(workspace).folder("existing")
    raw_file = folder / RAW
    if not raw_file.is_file():
        raise CaptureError(f"{raw_file} is missing: run the capture first")
    rec_file = folder / RECORD
    if rec_file.is_file():
        rec = json.loads(rec_file.read_text(encoding="utf-8"))
        for k in ("commit", "version", "base_url"):
            if rec.get(k):
                app[k] = rec[k]
    return write_outputs(app, product_app.captures(app), json.loads(raw_file.read_text(encoding="utf-8")), folder)


def write_outputs(app: dict[str, Any], caps: list[dict[str, Any]], raw: dict[str, Any], folder: Path) -> dict[str, Any]:
    out_dir = folder / CAPTURES
    audit, texts = audit_from(app, caps, raw)
    _write(folder / AUDIT, audit)
    _write(folder / TEXTS, texts)
    _write(folder / APP, app_summary(app))
    sheet_caps = [(c["id"], out_dir / f"{c['id']}.png") for c in caps if c["width"] == app["sheet_width"]]
    sheet = existing_sheet.build(sheet_caps, folder / SHEET)
    _write(folder / SHEET_INFO, sheet)
    _open_to_worker(folder)
    return {
        "captures": len(caps),
        "failed": 0,
        "commit": app.get("commit"),
        "version": app.get("version"),
        "base_url": app.get("base_url"),
        "sheet": {k: sheet[k] for k in ("bytes", "width", "height")},
        "sheet_tiles": len(sheet["tiles"]),
        "written": str(folder),
    }
