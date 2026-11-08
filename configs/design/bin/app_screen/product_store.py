"""Step 4: a product's proven stage outputs, kept in a store directory so a later run can reuse them.

    <store_root>/<product>/store/
        existing/v<N>/   02-existing as the workspace had it (captures/, audit.json, journeys.json, sheet.png, ...)
        ground/v<N>/     03-ground's product part: inventory.json, sources.json, fixture.json, fixtures/, source/,
                         product/, design-files/, check-final.json, fixture-check.json
        <stage>/v<N>/source.json   what it was made from and how: the fingerprint (reuse.py), the request's
                         requirement ids and words, run, workspace, workflow commit, date, every file's sha256
        current.json     {"existing": N, "ground": N}
        history.json     {"requests": [{at, run, workspace, stages: {stage: {status, reason, version}}}]}

Older versions stay. A version is written only from a run whose stage passed its final checks (reuse_host.py
checks that); the same files as the current version add no new version.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import contracts
from .reuse import sha256_file

STAGES = ("existing", "ground")
SOURCE, CURRENT, HISTORY = "source.json", "current.json", "history.json"
DEFAULT_STORE_ROOT = Path(
    os.environ.get("APP_SCREEN_STORE_DIR")
    or (Path(tempfile.gettempdir()) / "temper-app-screen-store")
)
# What a stored ground keeps: the product part and the proof it passed. The request's working files (task,
# drafts, the first check) and a reuse run's own inputs (stored/, base.json, ...) stay in the workspace.
GROUND_KEEP = ("inventory.json", "sources.json", "check-final.json", "fixture.json", "fixture-check.json",
               "fixtures", "source", "product", "design-files")
# Each stored JSON file's contract (contracts.SCHEMAS), checked when a version is written and before reuse.
SCHEMA_OF = {"existing": {"audit.json": "audit", "journeys.json": "journeys", "check-final.json": "existing_check"},
             "ground": {"inventory.json": "inventory", "sources.json": "ground_sources",
                        "check-final.json": "ground_check", "fixture-check.json": "fixture_check",
                        "source/prep.json": "ground_prep", "fixture.json": "fixture"}}
REQUIRED = {"existing": ("audit.json", "journeys.json", "check-final.json", "texts.json", "app.json", "sheet.png",
                         "raw.json", "capture.json"),
            "ground": ("inventory.json", "sources.json", "check-final.json", "fixture.json", "fixture-check.json",
                       "source/prep.json")}


class StoreError(ValueError):
    """The store refused: a stage that did not pass, a broken version, or a bad request; the message says why."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read_json(path: Path, what: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoreError(f"{path}: not readable ({what}): {exc.__class__.__name__}") from None


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def stage_files(stage: str, folder: Path) -> list[str]:
    """The files of a workspace stage folder a version keeps, relative to the folder, sorted."""
    if stage not in STAGES:
        raise StoreError(f"unknown stage {stage!r}; stored stages are {', '.join(STAGES)}")
    if stage == "existing":
        paths = [p for p in folder.rglob("*") if p.is_file()]
    else:
        paths = []
        for name in GROUND_KEEP:
            p = folder / name
            paths += [p] if p.is_file() else [q for q in p.rglob("*") if q.is_file()] if p.is_dir() else []
    return sorted(p.relative_to(folder).as_posix() for p in paths)


def manifest(folder: Path, files: list[str]) -> dict[str, str]:
    return {rel: sha256_file(folder / rel) for rel in files}


def check_files(stage: str, folder: Path, files: dict[str, str] | list[str]) -> list[str]:
    """Contract problems of a stage's files (present, readable, schema, final checks clean)."""
    problems = [f"{rel}: missing" for rel in REQUIRED[stage] if rel not in files or not (folder / rel).is_file()]
    for rel, schema in SCHEMA_OF[stage].items():
        path = folder / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            problems.append(f"{rel}: not readable JSON")
            continue
        problems += contracts.check_json(schema, data, rel)
        if rel == "check-final.json" and (data.get("verdict") != "ok" or data.get("problems")):
            problems.append(f"{rel}: verdict {data.get('verdict')!r} with {len(data.get('problems') or [])} "
                            "problem(s); only a passed stage is stored")
        if rel == "fixture-check.json" and data.get("verdict") != "pass":
            problems.append(f"{rel}: verdict {data.get('verdict')!r}; the fixture breaks an invariant")
    if stage == "existing" and (folder / "audit.json").is_file():
        try:
            audit = json.loads((folder / "audit.json").read_text(encoding="utf-8"))
            missing = [s["capture"] for s in audit.get("screens", []) if not (folder / s["capture"]).is_file()]
        except (ValueError, KeyError, TypeError):
            missing = ["(audit.json screens unreadable)"]
        problems += [f"{m}: capture named in audit.json is missing" for m in missing[:5]]
    return problems


class ProductStore:
    def __init__(self, product: str, root: Path | None = None):
        self.product = product
        self.dir = Path(root or DEFAULT_STORE_ROOT) / product / "store"

    def stage_dir(self, stage: str) -> Path:
        if stage not in STAGES:
            raise StoreError(f"unknown stage {stage!r}; stored stages are {', '.join(STAGES)}")
        return self.dir / stage

    def version_dir(self, stage: str, n: int) -> Path:
        return self.stage_dir(stage) / f"v{n}"

    def versions(self, stage: str) -> list[int]:
        folder = self.stage_dir(stage)
        found = [int(p.name[1:]) for p in folder.glob("v*") if p.is_dir() and p.name[1:].isdigit()] \
            if folder.is_dir() else []
        return sorted(found)

    def current(self) -> dict[str, int]:
        path = self.dir / CURRENT
        return _read_json(path, "current versions") if path.is_file() else {}

    def source(self, stage: str, n: int | None = None) -> dict | None:
        """A version's source.json (the current one when n is None); None when nothing is stored."""
        n = self.current().get(stage) if n is None else n
        if n is None:
            return None
        path = self.version_dir(stage, n) / SOURCE
        if not path.is_file():
            raise StoreError(f"{path} is missing: version v{n} of {stage} is broken")
        return _read_json(path, "version source")

    def validate(self, stage: str, n: int | None = None) -> list[str]:
        """Problems of a stored version: its source.json, every file against its recorded sha256, contracts."""
        n = self.current().get(stage) if n is None else n
        if n is None:
            return [f"nothing stored for {stage}"]
        folder = self.version_dir(stage, n)
        try:
            source = self.source(stage, n)
        except StoreError as exc:
            return [str(exc)]
        problems = []
        for key in ("product", "stage", "version", "fingerprint", "files", "run", "date"):
            if key not in source:
                problems.append(f"source.json: {key} is missing")
        if source.get("product") != self.product or source.get("stage") != stage or source.get("version") != n:
            problems.append("source.json: product, stage or version does not match where it is stored")
        files = source.get("files") or {}
        for rel, sha in files.items():
            path = folder / rel
            if not path.is_file():
                problems.append(f"{rel}: missing")
            elif sha256_file(path) != sha:
                problems.append(f"{rel}: changed since it was stored")
        extra = sorted(set(stage_files(stage, folder)) - set(files) - {SOURCE})
        problems += [f"{rel}: not in source.json's files" for rel in extra[:5]]
        return problems + check_files(stage, folder, files)

    def add(self, stage: str, folder: Path, source: dict) -> tuple[int, bool]:
        """Store a stage folder's files as a new version (or keep the current one when every file is the
        same). Returns (version, new). The caller has checked the stage passed."""
        files = stage_files(stage, folder)
        problems = check_files(stage, folder, files)
        if problems:
            raise StoreError(f"{stage}: not stored: " + "; ".join(problems[:8]))
        sums = manifest(folder, files)
        now = self.current().get(stage)
        if now is not None and (self.source(stage, now) or {}).get("files") == sums \
                and (self.source(stage, now) or {}).get("fingerprint") == source.get("fingerprint"):
            return now, False
        n = (self.versions(stage) or [0])[-1] + 1
        target = self.version_dir(stage, n)
        tmp = target.with_name(target.name + ".writing")
        if tmp.exists():
            shutil.rmtree(tmp)
        for rel in files:
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(folder / rel, tmp / rel)
        _write_json(tmp / SOURCE, {"product": self.product, "stage": stage, "version": n, "date": _now(),
                                   **source, "files": sums})
        tmp.rename(target)
        if (got := manifest(target, files)) != sums:
            raise StoreError(f"{target}: the copy differs from the workspace ({len(got)} files)")
        current = self.current()
        current[stage] = n
        _write_json(self.dir / CURRENT, current)
        return n, True

    def copy_out(self, stage: str, n: int, dest: Path) -> dict[str, str]:
        """Copy a version's files (not source.json) into a workspace folder; returns their sha256s."""
        folder, files = self.version_dir(stage, n), (self.source(stage, n) or {}).get("files", {})
        for rel in files:
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(folder / rel, dest / rel)
        return dict(files)

    def history(self) -> dict:
        path = self.dir / HISTORY
        return _read_json(path, "history") if path.is_file() else {"product": self.product, "requests": []}

    def add_history(self, entry: dict) -> None:
        data = self.history()
        data["requests"].append({"at": _now(), **entry})
        _write_json(self.dir / HISTORY, data)
