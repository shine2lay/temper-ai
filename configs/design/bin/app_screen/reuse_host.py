"""Step 4 on the host: before a run, reuse a product's stored stage work where nothing it rests on changed;
after a run, store what passed. Workers reach no design lab, so both run here (as capture and ground-prep do).

    design_app_screen.py prepare --product P --repo R --base-url URL --workspace W [--force existing,ground]
        decides stages 2 and 3 (reuse.py), records each decision with its reason in run.json, and fills the
        workspace: existing reuse -> the stored 02-existing copied in; delta -> the stored captures copied in
        and only the visually changed screens updated (existing_host.recapture); run -> the full capture.
        Ground's prep always runs fresh (ground_host.prep: cheap, and the sources say what changed); a usable
        stored ground is copied to 03-ground/stored/ for ground_collect to settle reuse or delta. reuse.json
        records what was copied, with every file's sha256 (stored_copy.py).
    design_app_screen.py store --workspace W --run RUN [--stages existing,ground] [--workflow-commit SHA]
        writes back each stage that finished (done, reused or delta) with its final check clean (and, for
        ground, the fixture's invariants holding); anything else is refused loud. A stage whose files equal
        the current version adds none; history.json records every request either way.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from . import app_instance, existing_host, ground_host, product_app, reuse, stored_copy
from .product_store import STAGES, ProductStore, StoreError
from .workspace import Workspace

DONE = ("done", "reused", "delta")
DELTA_COPY = (existing_host.CAPTURES, existing_host.RAW)


def _stored(ps: ProductStore, stage: str) -> tuple[dict | None, list[str]]:
    """The current version's source.json and its problems (None, [] when nothing is stored)."""
    try:
        source = ps.source(stage)
    except StoreError as exc:
        return {"version": ps.current().get(stage)}, [str(exc)]
    return (source, ps.validate(stage)) if source else (None, [])


def _copy_delta(ps: ProductStore, n: int, folder: Path) -> dict[str, str]:
    """Only the stored captures and raw measurements (the rest of stage 2 is made fresh)."""
    files = (ps.source("existing", n) or {})["files"]
    kept = {rel: sha for rel, sha in files.items() if rel.split("/")[0] in DELTA_COPY}
    for rel in kept:
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ps.version_dir("existing", n) / rel, folder / rel)
    return kept


def _load_app_for_workspace(product: str | Path, ws: Workspace,
                            products: Path | None = None) -> dict[str, Any]:
    ws_step = ws if ws.step else ws.for_step("store")
    rec_file = ws.folder("existing") / existing_host.RECORD
    if rec_file.is_file():
        rec = json.loads(ws_step.read_text(rec_file))
        app_file = rec.get("app_file")
        if app_file and Path(app_file).is_file():
            app = product_app.load(app_file)
            for k in ("commit", "version", "base_url"):
                if rec.get(k):
                    app[k] = rec[k]
            return app
    app_file_json = ws.folder("existing") / existing_host.APP
    if app_file_json.is_file():
        doc = json.loads(ws_step.read_text(app_file_json))
        spec_path = doc.get("spec_path")
        if spec_path and Path(spec_path).is_file():
            app = product_app.load(spec_path)
            for k in ("commit", "version", "base_url"):
                if doc.get(k):
                    app[k] = doc[k]
            return app
    return product_app.load(product, products)


def prepare(product: str | Path, workspace: str | Path, force: str | None = None,
            products: Path | None = None, *,
            base_url: str | None = None,
            credentials: dict[str, str] | str | None = None,
            version: str | None = None,
            stack_commit: str | None = None,
            health_opener: Any = None,
            opener: Any = None,
            instance: app_instance.AppInstance | None = None) -> dict[str, Any]:
    forced = reuse.parse_force(force)
    app = product_app.load(product, products)
    prod_name = app["product"]
    ws = Workspace(workspace, step="prepare")
    ws.start(prod_name)
    for stage in STAGES:
        if any(ws.folder(stage).glob("*")):
            raise StoreError(f"{ws.folder(stage)} is not empty; prepare needs a fresh workspace")

    eff_url = base_url or app.get("base_url") or os.environ.get("APP_SCREEN_BASE_URL", "")
    eff_creds = (
        credentials
        if credentials is not None
        else (os.environ.get("APP_SCREEN_CREDENTIALS") or os.environ.get("ROLLCALL_QA_PASSWORD"))
    )
    eff_commit = (stack_commit or os.environ.get("APP_SCREEN_STACK_COMMIT") or "").strip() or None
    inst = instance
    if inst is None and eff_url:
        inst = app_instance.AppInstance(
            app,
            eff_url,
            eff_creds,
            version=version,
            stack_commit=eff_commit,
            health_opener=health_opener or opener,
        )
    elif inst is not None and eff_commit:
        app_instance.verify_stack_commit(eff_commit, inst.commit, base_url=inst.base_url)
    if inst is not None:
        app["base_url"] = inst.base_url
        app["commit"] = inst.commit
        app["version"] = inst.version

    ps = ProductStore(prod_name, products)
    now = reuse.fingerprint(app, commit=app.get("commit"))
    stored_e, problems_e = _stored(ps, "existing")
    dec_e = reuse.decide_existing(app, now, stored_e, problems_e, "existing" in forced)
    folder = ws.folder("existing")
    folder.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"product": prod_name, "fingerprint": now}

    cand_tmp_ctx = None
    cand_dir: Path | None = None
    cand_raw: dict[str, Any] | None = None
    try:
        if dec_e.decision == "pending":
            if inst is None:
                raise StoreError("prepare requires base_url (or instance) to run visual diff when commit moved")
            cand_tmp_ctx = tempfile.TemporaryDirectory(prefix="app-screen-vdiff-")
            cand_root = Path(cand_tmp_ctx.name)
            cand_dir = cand_root / existing_host.CAPTURES
            cand_dir.mkdir(parents=True, exist_ok=True)
            caps = product_app.captures(app)
            cand_raw, cand_failed = existing_host.shoot(inst, caps, cand_dir)
            if cand_failed:
                existing_host._fail(folder, cand_failed, len(caps))
            stored_vdir = ps.version_dir("existing", stored_e["version"])
            changed_screens, _ = reuse.diff_screens_by_visual(app, stored_vdir, cand_root)
            dec_e = reuse.decide_existing(
                app, now, stored_e, problems_e, "existing" in forced,
                visual_diff_screens=changed_screens,
            )

        entry_e: dict[str, Any] = {
            **dec_e.record(),
            "version": (stored_e or {}).get("version"),
            "source_run": (stored_e or {}).get("run"),
        }
        if dec_e.decision == "reuse":
            entry_e["files"] = ps.copy_out("existing", stored_e["version"], folder)
            existing_host._open_to_worker(folder)
            captured: dict[str, Any] = {"captures": len(product_app.captures(app)), "reused": True}
        elif dec_e.decision == "delta":
            entry_e["files"] = {
                rel: sha for rel, sha in _copy_delta(ps, stored_e["version"], folder).items()
                if not any(
                    rel == f"{existing_host.CAPTURES}/{c['id']}.png"
                    for c in product_app.captures(app)
                    if c["screen"] in dec_e.screens
                )
            }
            captured = existing_host.recapture(
                product, str(ws.path), dec_e.screens, products,
                base_url=eff_url, credentials=eff_creds, version=version,
                health_opener=health_opener or opener, instance=inst,
                pre_captured_dir=cand_dir, pre_raw=cand_raw,
            )
            entry_e["recaptured"] = captured["recaptured"]
            entry_e["changed"] = dec_e.changed
        elif cand_dir is not None and cand_raw is not None:
            caps = product_app.captures(app)
            out_dir = folder / existing_host.CAPTURES
            out_dir.mkdir(parents=True, exist_ok=True)
            for c in caps:
                shutil.copy2(cand_dir / f"{c['id']}.png", out_dir / f"{c['id']}.png")
            existing_host._write(folder / existing_host.RAW, cand_raw)
            existing_host._write(folder / existing_host.RECORD, existing_host._record(app, caps, {}))
            captured = existing_host.write_outputs(app, caps, cand_raw, folder)
        else:
            captured = existing_host.capture(
                product, str(ws.path), products,
                base_url=eff_url, credentials=eff_creds, version=version,
                health_opener=health_opener or opener, instance=inst,
            )
    finally:
        if cand_tmp_ctx is not None:
            cand_tmp_ctx.cleanup()

    stored_g, problems_g = _stored(ps, "ground")
    dec_g = reuse.decide_ground(dec_e, stored_g, problems_g, "ground" in forced)
    prepped = (
        ground_host.prep(product, str(ws.path), products)
        if "fixture" in app
        else {"product": prod_name}
    )
    entry_g = {**dec_g.record(), "version": (stored_g or {}).get("version"), "source_run": (stored_g or {}).get("run")}
    if dec_g.decision == "pending":
        target = stored_copy.folder(ws, "ground")
        entry_g["files"] = ps.copy_out("ground", stored_g["version"], target)
        existing_host._open_to_worker(target)
    record.update(existing=entry_e, ground=entry_g)
    stored_copy.write(ws, record)
    for stage, dec, entry in (("existing", dec_e, entry_e), ("ground", dec_g, entry_g)):
        ws.decide(stage, dec.decision, dec.reason, source_run=entry["source_run"], store_version=entry["version"],
                  screens=dec.screens or None)
    return {
        "product": prod_name,
        "existing": dec_e.record(),
        "ground": dec_g.record(),
        "captures": captured.get("captures"),
        "recaptured": captured.get("recaptured", []),
        "ground_prep": {k: v for k, v in prepped.items() if k != "product"},
    }


def _request(ws: Workspace) -> dict:
    file = ws.folder("intake") / "requirements.json"
    if not file.is_file():
        return {}
    ws_step = ws if ws.step else ws.for_step("store")
    data = json.loads(ws_step.read_text(file))
    return {
        "sha256": reuse.sha256_file(file),
        "items": [{"id": r["id"], "owner_words": r.get("owner_words", "")} for r in data.get("items", [])],
    }


def store(workspace: str | Path, run: str, stages: str | None = None, workflow_commit: str | None = None,
          products: Path | None = None) -> dict:
    """Write the run's finished stages back to its product's store; refuse loud what did not pass."""
    ws = Workspace(workspace, step="store")
    data = ws.run()
    if not run:
        raise StoreError("store needs --run (the temper run id the outputs came from)")
    wanted = [s for s in (stages or ",".join(STAGES)).split(",") if s]
    unknown = set(wanted) - set(STAGES)
    if unknown:
        raise StoreError(f"--stages takes {','.join(STAGES)}, not {', '.join(sorted(unknown))}")
    product = data["product"]
    app = _load_app_for_workspace(product, ws, products)
    ps = ProductStore(app["product"], products)
    prepared = json.loads(ws.read_text(stored_copy.path(ws))) if stored_copy.path(ws).is_file() \
        else None
    fingerprint = prepared["fingerprint"] if prepared else reuse.fingerprint(app, commit=app.get("commit"))
    refused = []
    for stage in wanted:
        status = (data["stages"].get(stage) or {}).get("status")
        if status not in DONE:
            refused.append(f"{stage}: status {status!r}; only a finished stage ({', '.join(DONE)}) is stored")
    if refused:
        raise StoreError("not stored: " + "; ".join(refused))
    results, history = {}, {}
    for stage in wanted:
        folder = ws.folder(stage)
        source = {
            "commit": fingerprint.get("commit"),
            "fingerprint": fingerprint,
            "run": run,
            "workspace": str(ws.path),
            "workflow_commit": workflow_commit,
            "viewports": sorted(int(w) for w in app["sizes"]),
            "fingerprint_from": "prepare" if prepared else "store (no prepare: taken when stored)",
            "request": _request(ws),
        }
        if stage == "ground":
            source["existing_version"] = ps.current().get("existing")
        n, new = ps.add(stage, folder, source)
        entry = data["stages"][stage]
        results[stage] = {"version": n, "new": new}
        history[stage] = {
            "status": entry["status"],
            "decision": entry.get("decision", "run"),
            "reason": entry.get("reason", "no prepare: a full run"),
            "version": n,
            "new_version": new,
        }
    ps.add_history({"run": run, "workspace": str(ws.path), "stages": history})
    return {"product": app["product"], "stored": results, "store": str(ps.dir)}


def validate(product: str | Path, products: Path | None = None) -> dict:
    """Every stage's current version checked (host): files, sha256s, contracts."""
    if isinstance(product, Path) or "/" in str(product):
        prod_name = product_app.load(product, products)["product"]
    else:
        prod_name = str(product)
    ps = ProductStore(prod_name, products)
    found = {stage: ps.validate(stage) for stage in STAGES if ps.current().get(stage)}
    if not found:
        raise StoreError(f"nothing stored for {prod_name} in {ps.dir}")
    bad = {s: p for s, p in found.items() if p}
    if bad:
        raise StoreError("; ".join(f"{s} v{ps.current()[s]}: " + "; ".join(p[:5]) for s, p in bad.items()))
    return {"product": prod_name, "valid": {s: ps.current()[s] for s in found}}
