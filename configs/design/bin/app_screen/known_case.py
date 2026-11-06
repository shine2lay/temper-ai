"""Known cases: a finished app-screen job frozen as each stage's real output, to test stages alone (rule 16).

A known case is a folder laid out like a workspace (01-request/ .. 08-handoff/, with 06-checks/round-1/)
plus gates/ (the gate answers really given) and FREEZE.json: {"case", "product", "frozen_at", "source",
"files": {relative path: sha256}}. The host packs it into a run workspace's known-case/ before a fixture
run (workers cannot see Design's lab); a fixture stage copies its folder from there and validates it.
Any changed, missing or extra file fails the run.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from .workspace import FOLDERS, KNOWN_CASE, PRODUCT_ID, Workspace

FREEZE = "FREEZE.json"


class KnownCaseError(ValueError):
    """A known case is missing, changed or incomplete; the message names the file."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _files(root: Path) -> dict[str, Path]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise KnownCaseError(f"{p} is a link; a known case holds plain files")
        if p.is_file() and p.name != FREEZE:
            out[p.relative_to(root).as_posix()] = p
    return out


def freeze(case_dir: Path | str, product: str, source: str, needs: tuple[str, ...] | None = None) -> dict:
    """Write FREEZE.json for a case folder (once: an existing freeze is never rewritten).

    A whole-job case holds every stage folder. A case that feeds one stage holds only the folders that
    stage reads, named in `needs` (the checks cases, for one, hold 01-request, 03-ground and 05-build).
    """
    root = Path(case_dir)
    if (root / FREEZE).exists():
        raise KnownCaseError(f"{root / FREEZE} exists; a frozen case is never re-frozen, make a new case")
    if not PRODUCT_ID.match(product or ""):
        raise KnownCaseError(f"product {product!r} is not a lowercase id")
    wanted = tuple(needs) if needs else tuple(FOLDERS.values())
    unknown = [f for f in wanted if f not in FOLDERS.values()]
    if unknown:
        raise KnownCaseError(f"{root}: {', '.join(unknown)} is not a stage folder")
    missing = [f for f in wanted if not (root / f).is_dir()]
    if missing:
        raise KnownCaseError(f"{root}: stage folders missing: {', '.join(missing)}")
    files = {rel: _sha256(p) for rel, p in _files(root).items()}
    record = {"case": root.name, "product": product, "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "source": source, "files": files}
    (root / FREEZE).write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    return record


def verify(case_dir: Path | str) -> dict:
    """The case's FREEZE.json, after checking every file's hash and that no file was added or removed."""
    root = Path(case_dir)
    path = root / FREEZE
    if not path.is_file():
        raise KnownCaseError(f"{path} is missing: freeze the case first")
    record = json.loads(path.read_text())
    want = record.get("files") or {}
    have = _files(root)
    problems = [f"{rel}: missing" for rel in sorted(set(want) - set(have))]
    problems += [f"{rel}: not in FREEZE.json" for rel in sorted(set(have) - set(want))]
    problems += [f"{rel}: changed since the freeze" for rel in sorted(set(want) & set(have)) if _sha256(have[rel]) != want[rel]]
    if problems:
        raise KnownCaseError(f"known case {root.name}: " + "; ".join(problems[:8]) + (" ..." if len(problems) > 8 else ""))
    return record


def pack(case_dir: Path | str, workspace: Path | str) -> dict:
    """Host side: copy a verified case into <workspace>/known-case/ and start a fixture run.json."""
    record = verify(case_dir)
    ws = Workspace(workspace)
    dest = ws.path / KNOWN_CASE
    if dest.exists():
        raise KnownCaseError(f"{dest} exists; use a fresh workspace")
    shutil.copytree(Path(case_dir), dest, symlinks=False)
    verify(dest)
    ws.start(record["product"], "fixture")
    return {"case": record["case"], "product": record["product"], "files": len(record["files"]), "packed": str(dest)}


def copy_stage(ws: Workspace, stage: str) -> list[str]:
    """Fixture mode: the known case's output for one stage, copied into the workspace (checks: into this round)."""
    case = ws.path / KNOWN_CASE
    verify(case)
    if stage == "checks" or stage == "review":
        src = case / FOLDERS["checks"] / "round-1"
        dest = ws.round_folder()
        name = "checks.json" if stage == "checks" else "review.json"
        if not (src / name).is_file():
            raise KnownCaseError(f"known case has no {FOLDERS['checks']}/round-1/{name}")
        dest.mkdir(parents=True, exist_ok=True)
        data = json.loads((src / name).read_text())
        data["round"] = ws.round
        (dest / name).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        return [(dest / name).relative_to(ws.path).as_posix()]
    src = case / FOLDERS[stage]
    if not src.is_dir():
        raise KnownCaseError(f"known case has no {FOLDERS[stage]}/")
    shutil.copytree(src, ws.folder(stage), dirs_exist_ok=True)
    return sorted(p.relative_to(ws.path).as_posix() for p in ws.folder(stage).rglob("*") if p.is_file())


def gate_answer(ws: Workspace, gate: str) -> dict:
    """The gate answer really given in the known case (gates/gate_<name>.json), for comparison."""
    path = ws.path / KNOWN_CASE / "gates" / f"gate_{gate}.json"
    if not path.is_file():
        raise KnownCaseError(f"known case has no gates/gate_{gate}.json")
    return json.loads(path.read_text())
