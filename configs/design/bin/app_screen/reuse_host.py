"""Step 4 on the host: before a run, reuse a product's stored stage work where nothing it rests on changed;
after a run, store what passed. Workers reach no design lab, so both run here (as capture and ground-prep do).

    design_app_screen.py prepare --product P --workspace W [--force existing,ground]
        decides stages 2 and 3 (reuse.py), records each decision with its reason in run.json, and fills the
        workspace: existing reuse -> the stored 02-existing copied in; delta -> the stored captures copied in
        and only the changed screens captured again (existing_host.recapture); run -> the full capture. Ground's
        prep always runs fresh (ground_host.prep: cheap, and the sources say what changed); a usable stored
        ground is copied to 03-ground/stored/ for ground_collect to settle reuse or delta. reuse.json records
        what was copied, with every file's sha256 (stored_copy.py).
    design_app_screen.py store --workspace W --run RUN [--stages existing,ground] [--workflow-commit SHA]
        writes back each stage that finished (done, reused or delta) with its final check clean (and, for
        ground, the fixture's invariants holding); anything else is refused loud. A stage whose files equal
        the current version adds none; history.json records every request either way.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import existing_host, ground_host, product_app, reuse, stored_copy
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


def _page_items(ps: ProductStore) -> list[dict]:
    """The stored ground's capability-map pages (with their groups): how a server file maps to a route."""
    n = ps.current().get("ground")
    file = ps.version_dir("ground", n) / "sources.json" if n else None
    if not file or not file.is_file():
        return []
    return [i for i in json.loads(file.read_text(encoding="utf-8"))["items"] if i["kind"] == "page"]


def _copy_delta(ps: ProductStore, n: int, folder: Path) -> dict[str, str]:
    """Only the stored captures and raw measurements (the rest of stage 2 is made fresh)."""
    files = (ps.source("existing", n) or {})["files"]
    kept = {rel: sha for rel, sha in files.items() if rel.split("/")[0] in DELTA_COPY}
    for rel in kept:
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ps.version_dir("existing", n) / rel, folder / rel)
    return kept


def prepare(product: str, workspace: str, force: str | None = None, products: Path | None = None) -> dict:
    forced = reuse.parse_force(force)
    app = product_app.load(product, products)
    ws = Workspace(workspace)
    ws.start(product, "real")
    for stage in STAGES:
        if any(ws.folder(stage).glob("*")):
            raise StoreError(f"{ws.folder(stage)} is not empty; prepare needs a fresh workspace")
    ps = ProductStore(product, products)
    now = reuse.fingerprint(app)
    stored_e, problems_e = _stored(ps, "existing")
    dec_e = reuse.decide_existing(app, now, stored_e, problems_e, "existing" in forced, _page_items(ps))
    folder = ws.folder("existing")
    folder.mkdir(parents=True, exist_ok=True)
    record = {"product": product, "fingerprint": now}
    entry_e = {**dec_e.record(), "version": (stored_e or {}).get("version"), "source_run": (stored_e or {}).get("run")}
    if dec_e.decision == "reuse":
        entry_e["files"] = ps.copy_out("existing", stored_e["version"], folder)
        existing_host._open_to_worker(folder)
        captured = {"captures": len(product_app.captures(app)), "reused": True}
    elif dec_e.decision == "delta":
        entry_e["files"] = {rel: sha for rel, sha in _copy_delta(ps, stored_e["version"], folder).items()
                            if not any(rel == f"{existing_host.CAPTURES}/{c['id']}.png"
                                       for c in product_app.captures(app) if c["screen"] in dec_e.screens)}
        captured = existing_host.recapture(product, workspace, dec_e.screens, products)
        entry_e["recaptured"] = captured["recaptured"]
        entry_e["changed"] = dec_e.changed
    else:
        captured = existing_host.capture(product, workspace, products)
    stored_g, problems_g = _stored(ps, "ground")
    dec_g = reuse.decide_ground(dec_e, stored_g, problems_g, "ground" in forced)
    prepped = ground_host.prep(product, workspace, products)
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
    return {"product": product, "existing": dec_e.record(), "ground": dec_g.record(),
            "captures": captured.get("captures"), "recaptured": captured.get("recaptured", []),
            "ground_prep": {k: v for k, v in prepped.items() if k != "product"}}


def _request(ws: Workspace) -> dict:
    file = ws.folder("intake") / "requirements.json"
    if not file.is_file():
        return {}
    data = json.loads(file.read_text(encoding="utf-8"))
    return {"sha256": reuse.sha256_file(file),
            "items": [{"id": r["id"], "owner_words": r.get("owner_words", "")} for r in data.get("items", [])]}


def store(workspace: str, run: str, stages: str | None = None, workflow_commit: str | None = None,
          products: Path | None = None) -> dict:
    """Write the run's finished stages back to its product's store; refuse loud what did not pass."""
    ws = Workspace(workspace)
    data = ws.run()
    if data["mode"] != "real":
        raise StoreError(f"{ws.run_file}: mode {data['mode']}; only a real run is stored")
    if not run:
        raise StoreError("store needs --run (the temper run id the outputs came from)")
    wanted = [s for s in (stages or ",".join(STAGES)).split(",") if s]
    unknown = set(wanted) - set(STAGES)
    if unknown:
        raise StoreError(f"--stages takes {','.join(STAGES)}, not {', '.join(sorted(unknown))}")
    product = data["product"]
    app = product_app.load(product, products)
    ps = ProductStore(product, products)
    prepared = json.loads(stored_copy.path(ws).read_text(encoding="utf-8")) if stored_copy.path(ws).is_file() \
        else None
    fingerprint = prepared["fingerprint"] if prepared else reuse.fingerprint(app)
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
        source = {"fingerprint": fingerprint, "run": run, "workspace": str(ws.path),
                  "workflow_commit": workflow_commit, "viewports": sorted(int(w) for w in app["sizes"]),
                  "fingerprint_from": "prepare" if prepared else "store (no prepare: taken when stored)",
                  "request": _request(ws)}
        if stage == "ground":
            source["existing_version"] = ps.current().get("existing")
        n, new = ps.add(stage, folder, source)
        entry = data["stages"][stage]
        results[stage] = {"version": n, "new": new}
        history[stage] = {"status": entry["status"], "decision": entry.get("decision", "run"),
                          "reason": entry.get("reason", "no prepare: a full run"), "version": n, "new_version": new}
    ps.add_history({"run": run, "workspace": str(ws.path), "stages": history})
    return {"product": product, "stored": results, "store": str(ps.dir)}


def validate(product: str, products: Path | None = None) -> dict:
    """Every stage's current version checked (host): files, sha256s, contracts."""
    ps = ProductStore(product, products)
    found = {stage: ps.validate(stage) for stage in STAGES if ps.current().get(stage)}
    if not found:
        raise StoreError(f"nothing stored for {product} in {ps.dir}")
    bad = {s: p for s, p in found.items() if p}
    if bad:
        raise StoreError("; ".join(f"{s} v{ps.current()[s]}: " + "; ".join(p[:5]) for s, p in bad.items()))
    return {"product": product, "valid": {s: ps.current()[s] for s in found}}
