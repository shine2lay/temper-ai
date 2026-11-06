"""Host: put a checks known case into a run workspace, so the checks step can be run on it alone (rule 16).

A checks case is the three folders the checks step reads - 01-request/ (requirements), 03-ground/
(inventory, fixture, design files) and 05-build/ (the prototype) - plus expected.json, what the checks must
find in it. This writes the workspace the stage-alone workflow runs on: the folders copied byte for byte and
a run.json whose build round is 1, as if the build step had just finished.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .workspace import Workspace

CASE_FOLDERS = ("01-request", "03-ground", "05-build")
EXPECTED = "expected.json"


class CaseError(ValueError):
    """The case folder is not a checks case; the message says what is missing."""


def read_case(case_dir: Path | str) -> dict:
    """expected.json: {case, product, about, planted[], expect{}}; planted rows name the check and the view."""
    root = Path(case_dir).expanduser().resolve()
    path = root / EXPECTED
    if not path.is_file():
        raise CaseError(f"{path} is missing: a checks case says what the checks must find in it")
    try:
        expected = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise CaseError(f"{path} is not JSON: {exc}") from exc
    for field in ("case", "product", "expect"):
        if field not in expected:
            raise CaseError(f"{path}: {field} is missing")
    for planted in expected.get("planted") or []:
        for field in ("id", "check", "what"):
            if field not in planted:
                raise CaseError(f"{path}: a planted fault has no {field}")
    return expected


def prep(case_dir: Path | str, workspace: Path | str) -> dict:
    """Copy the case into a fresh workspace and mark the build done at round 1."""
    root = Path(case_dir).expanduser().resolve()
    expected = read_case(root)
    ws_path = Path(workspace).expanduser().resolve()
    ws_path.mkdir(parents=True, exist_ok=True)
    if any(ws_path.iterdir()):
        raise CaseError(f"{ws_path} is not empty; a case goes into a fresh workspace")
    copied = 0
    for folder in CASE_FOLDERS:
        src = root / folder
        if not src.is_dir():
            if folder == "01-request":
                continue                                   # a case may have no requirements to cover
            raise CaseError(f"{src} is missing: a checks case holds {', '.join(CASE_FOLDERS)}")
        shutil.copytree(src, ws_path / folder)
        copied += sum(1 for p in (ws_path / folder).rglob("*") if p.is_file())
    ws = Workspace(ws_path)
    ws.start(expected["product"], "real")
    ws.next_round()
    ws.mark("build", "done", round=1, source=f"checks case {expected['case']}")
    return {"case": expected["case"], "product": expected["product"], "workspace": str(ws_path),
            "files": copied, "round": 1,
            "planted": len(expected.get("planted") or [])}
