"""Stage 3's host step (ground-prep): everything ground reads from outside the workspace, put into 03-ground/.

Workers reach neither the design lab, the product repo nor the throwaway checkout, so the host runs this before
the workflow (design_app_screen.py ground-prep --product P --workspace W), as stage 2's capture does:

    design files   design_files.pack (configs/design/products.yaml) -> 03-ground/source/pack.json and
                   03-ground/design-files/; a product the registry lacks gets a manifest saying so (status none)
    capabilities   the product file's capability map: `git show <commit>:<path>` for a server app (the repo is
                   only read), a file beside the product file for a static one, or "derive", which runs
                   configs/epd/bin/capabilities.py on the throwaway checkout; its entries -> prep.json
    notes          the product file's other knowledge files, read the same way -> 03-ground/product/notes/
    fixture        the product's shared sample data, copied as it is: its file -> 03-ground/fixture.json and
                   each part file -> 03-ground/fixtures/<name>.json (added to the fixture under <name>; a name
                   the file already holds fails), with the invariants the product file declares

Model-free. Every problem fails loud (GroundPrepError) before anything is half-written into a used workspace.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from . import contracts, product_app
from .model_step import write_json
from .workspace import Workspace

HERE = Path(__file__).resolve().parent
DESIGN_BIN = HERE.parent                       # configs/design/bin (design_files.py)
EPD_BIN = HERE.parents[2] / "epd" / "bin"      # configs/epd/bin (capabilities.py)
PREP, PACK = "source/prep.json", "source/pack.json"
NOTES_DIR, MAP_COPY, PARTS_DIR = "product/notes", "product/capabilities.md", "fixtures"


class GroundPrepError(ValueError):
    """ground-prep cannot finish; the message says what is missing or wrong."""


def _on_path(folder: Path) -> None:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pack_design_files(product: str, ground: Path, registry: Path | None = None,
                      lab_root: Path | str = "~/design-lab") -> dict:
    """design_files.pack into 03-ground; a product not in the registry gets an empty manifest (status none)."""
    _on_path(DESIGN_BIN)
    import design_files
    registry = Path(registry or design_files.REGISTRY)
    if product in design_files.load_registry(registry)["products"]:
        design_files.pack(registry, product, None, ground, lab_root)
        return {"registered": True, "from": str(registry)}
    write_json(ground / PACK, {"version": 1, "product": product, "name": product, "fixture": False,
                               "registry_entry": None, "files": {}, "design_files": {}, "current_state": {}})
    return {"registered": False, "from": f"{product} is not in {registry}: no design files"}


def _source_path(app: dict, path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else Path(app["path"]).parent / p


def read_source(app: dict, path: str) -> tuple[str, str]:
    """(text, where it came from): a server app's file at its pinned commit (read only), else a file on disk."""
    a = app["app"]
    if a["kind"] == "server" and not Path(path).is_absolute():
        try:
            done = subprocess.run(["git", "-C", str(Path(a["repo"]).expanduser()), "show", f"{a['commit']}:{path}"],
                                  capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GroundPrepError(f"git show {a['commit']}:{path} did not run: {exc}") from None
        if done.returncode:
            raise GroundPrepError(f"git show {a['commit']}:{path} failed: {done.stderr.strip()[-300:]}")
        return done.stdout, f"{a['repo']} at {a['commit']}: {path}"
    file = _source_path(app, path)
    if not file.is_file():
        raise GroundPrepError(f"{file} is missing (named in {app['path']})")
    return file.read_text(encoding="utf-8"), str(file)


def read_capabilities(app: dict, ground: Path) -> dict:
    """The capability map's entries (kind, key, group, intent, where), from the map or derived from the code."""
    _on_path(EPD_BIN)
    import capabilities
    named = app.get("capabilities")
    if not named:
        raise GroundPrepError(f"{app['path']}: capabilities: missing; ground needs the product's capability map "
                              "(a path, or derive)")
    if named == "derive":
        checkout = Path(app["app"]["checkout"])
        if not checkout.is_dir():
            raise GroundPrepError(f"{checkout} is missing: derive reads the throwaway checkout (stage 2's capture "
                                  "makes it)")
        caps, where = capabilities.derive(checkout).caps, f"derived from {checkout} by capabilities.py"
    else:
        text, where = read_source(app, named)
        write_json(ground / MAP_COPY, text)    # text is written as it is
        caps = capabilities.read_map(text)
    if not caps:
        raise GroundPrepError(f"{where}: no capability entries (HTTP API or Pages) found")
    return {"from": where, "items": [asdict(c) for c in caps]}


def read_notes(app: dict, ground: Path) -> list[dict]:
    out, seen = [], set()
    for path in app.get("notes", []):
        name = Path(path).stem
        if name in seen:
            raise GroundPrepError(f"{app['path']}: notes: two files named {name}")
        seen.add(name)
        text, where = read_source(app, path)
        rel = f"{NOTES_DIR}/{name}.md"
        write_json(ground / rel, text)
        out.append({"name": name, "from": where, "file": rel})
    return out


def _json_file(path: Path, what: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GroundPrepError(f"{path} ({what}) is not readable JSON: {exc}") from None


def copy_fixture(app: dict, ground: Path) -> dict:
    """The product's shared fixture, copied byte for byte: its file and its part files, checked first."""
    spec = app.get("fixture")
    if not spec:
        raise GroundPrepError(f"{app['path']}: fixture: missing; ground needs the product's shared sample data")
    file = _source_path(app, spec["file"])
    if not file.is_file():
        raise GroundPrepError(f"{file} is missing (fixture named in {app['path']})")
    base = _json_file(file, "the fixture")
    if not isinstance(base, dict):
        raise GroundPrepError(f"{file}: the fixture is not a JSON object")
    parts = {}
    if spec.get("parts"):
        folder = _source_path(app, spec["parts"])
        if not folder.is_dir():
            raise GroundPrepError(f"{folder} is missing (fixture parts named in {app['path']})")
        for part in sorted(folder.glob("*.json")):
            if part.stem in base:
                raise GroundPrepError(f"fixture key {part.stem} is in both {file.name} and {folder}/{part.name}")
            _json_file(part, "a fixture part")
            parts[part.stem] = part
        if not parts:
            raise GroundPrepError(f"{folder} holds no .json part files (fixture parts named in {app['path']})")
    shutil.copyfile(file, ground / "fixture.json")
    record = {"from": str(file), "sha256": sha256_file(ground / "fixture.json"),
              "invariants": spec.get("invariants", {})}
    if parts:
        (ground / PARTS_DIR).mkdir()
        for part in parts.values():
            shutil.copyfile(part, ground / PARTS_DIR / part.name)
        record["parts"] = {name: sha256_file(ground / PARTS_DIR / p.name) for name, p in parts.items()}
        record["parts_from"] = str(folder)
    return record


def prep(product: str, workspace: str | Path, store: Path | None = None, registry: Path | None = None,
         lab_root: Path | str = "~/design-lab") -> dict:
    """Write 03-ground/'s host inputs; a 03-ground that already holds them fails (use a fresh workspace)."""
    app = product_app.load(product, store)
    ws = Workspace(workspace)
    ws.start(product, "real")
    ground = ws.folder("ground")
    used = [p for p in ("source", "product", "design-files", "fixture.json", PARTS_DIR) if (ground / p).exists()]
    if used:
        raise GroundPrepError(f"{ground} already holds {', '.join(used)}; use a fresh workspace")
    ground.mkdir(parents=True, exist_ok=True)
    record = {"product": product,
              "capabilities": read_capabilities(app, ground),
              "notes": read_notes(app, ground),
              "fixture": copy_fixture(app, ground),
              "design_files": pack_design_files(product, ground, registry, lab_root)}
    if app["app"]["kind"] == "server":
        record["commit"] = app["app"]["commit"]
    problems = contracts.check_json("ground_prep", record, f"03-ground/{PREP}")
    if problems:
        raise GroundPrepError("; ".join(problems[:8]))
    write_json(ground / PREP, record)
    caps = record["capabilities"]["items"]
    return {"product": product, "capabilities": len(caps), "pages": sum(c["kind"] == "page" for c in caps),
            "notes": len(record["notes"]), "fixture_sha256": record["fixture"]["sha256"],
            "registered": record["design_files"]["registered"]}
