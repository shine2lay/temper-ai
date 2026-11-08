"""Step 4: the workspace's record of what the host's prepare took from the product store (reuse.json), and the
check that the copies are still byte-identical. Read by the workflow's steps (workers reach no design lab).

    reuse.json  {"product", "prepared_at", "fingerprint": {...},
                 "existing": {"decision", "reason", "version", "source_run", "files": {rel: sha256},
                              "screens": [...], "recaptured": [...]},
                 "ground":   {"decision", "reason", "version", "source_run", "files": {rel: sha256}}}

files lists what was copied, relative to the stage folder (ground's copy sits in 03-ground/stored/). For a
delta, existing's files are the kept captures only (the re-captured ones are new).
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from .workspace import Workspace

RECORD = "reuse.json"
GROUND_STORED = "stored"


class StoredCopyError(ValueError):
    """The copy prepare made is missing or changed; the message names the files."""


def path(ws: Workspace) -> Path:
    return ws.path / RECORD


def read(ws: Workspace) -> dict:
    file = path(ws)
    if not file.is_file():
        raise StoredCopyError(f"{RECORD} is missing: the host's prepare writes it "
                              f"(design_app_screen.py prepare --product P --workspace {ws.path})")
    ws_step = ws if ws.step else ws.for_step("prepare")
    try:
        return json.loads(ws_step.read_text(RECORD))
    except ValueError as exc:
        raise StoredCopyError(f"{RECORD}: not readable JSON ({exc})") from None


def write(ws: Workspace, record: dict) -> None:
    file = path(ws)
    file.write_text(json.dumps({**record, "prepared_at": datetime.now(UTC).isoformat(timespec="seconds")},
                               indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    file.chmod(0o666)


def folder(ws: Workspace, stage: str) -> Path:
    return ws.folder(stage) / GROUND_STORED if stage == "ground" else ws.folder(stage)


def problems(ws: Workspace, stage: str) -> list[str]:
    """Copied files that are missing or no longer byte-identical to the stored version."""
    step_name = ws.step or ("existing" if stage == "existing" else "ground_collect")
    ws_step = ws.for_step(step_name)
    entry = read(ws_step).get(stage) or {}
    base, out = folder(ws_step, stage), []
    for rel, sha in (entry.get("files") or {}).items():
        file = base / rel
        if not file.is_file():
            out.append(f"{rel}: missing")
        elif hashlib.sha256(ws_step.read_bytes(file)).hexdigest() != sha:
            out.append(f"{rel}: changed since prepare copied it from stored v{entry.get('version')}")
    if not entry.get("files"):
        out.append(f"{RECORD}: no stored files recorded for {stage}")
    return out


def verify(ws: Workspace, stage: str) -> dict:
    """Fail loud unless every copied file is byte-identical; returns the stage's record."""
    found = problems(ws, stage)
    if found:
        raise StoredCopyError(f"{stage}: the stored copy is broken: " + "; ".join(found[:8])
                              + (f"; and {len(found) - 8} more" if len(found) > 8 else ""))
    return read(ws)[stage]
