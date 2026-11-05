"""The app-screen run workspace: one folder per stage and run.json (product, mode, stage status, round).

Every stage reads and writes only inside the workspace. run.json is the run's own record:
    {"product": "rollcall", "mode": "fixture", "round": 1,
     "stages": {"intake": {"status": "done", "at": "..."}, ...}}
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

STAGES = ("intake", "existing", "ground", "directions", "build", "checks", "show", "handoff")
# Workflow steps that are not one of the eight stages: the two owner gates, the review half of the
# checks stage, and the bookkeeping step after the final gate.
STEPS = STAGES + ("gate_direction", "review", "gate_final", "gate_final_next")
FOLDERS = {"intake": "01-request", "existing": "02-existing", "ground": "03-ground", "directions": "04-directions",
           "build": "05-build", "checks": "06-checks", "show": "07-show", "handoff": "08-handoff"}
MODES = ("real", "fixture")
STATUSES = ("running", "done", "failed")
PRODUCT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
KNOWN_CASE = "known-case"


class WorkspaceError(ValueError):
    """The workspace is missing or not usable; the message says what and where."""


class Workspace:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if not self.path.is_dir():
            raise WorkspaceError(f"workspace {self.path} does not exist or is not a folder")

    def folder(self, stage: str) -> Path:
        if stage not in FOLDERS:
            raise WorkspaceError(f"unknown stage {stage!r}; stages are {', '.join(STAGES)}")
        return self.path / FOLDERS[stage]

    def round_folder(self, n: int | None = None) -> Path:
        return self.folder("checks") / f"round-{self.round if n is None else n}"

    @property
    def run_file(self) -> Path:
        return self.path / "run.json"

    def run(self) -> dict:
        if not self.run_file.is_file():
            raise WorkspaceError(f"{self.run_file} is missing: pack a known case (fixture) or run intake first")
        data = json.loads(self.run_file.read_text())
        if not isinstance(data, dict) or data.get("mode") not in MODES or not PRODUCT_ID.match(str(data.get("product"))):
            raise WorkspaceError(f"{self.run_file}: needs product (lowercase id) and mode real|fixture")
        return data

    @property
    def mode(self) -> str:
        return self.run()["mode"]

    @property
    def round(self) -> int:
        return int(self.run().get("round", 0))

    def start(self, product: str, mode: str) -> dict:
        """Write a fresh run.json (host pack or intake); an existing one with another product or mode fails."""
        if mode not in MODES:
            raise WorkspaceError(f"mode is {' or '.join(MODES)}, not {mode!r}")
        if not PRODUCT_ID.match(product or ""):
            raise WorkspaceError(f"product {product!r} is not a lowercase id (a-z, 0-9, -)")
        if self.run_file.exists():
            old = self.run()
            if (old["product"], old["mode"]) != (product, mode):
                raise WorkspaceError(f"{self.run_file} already holds {old['product']}/{old['mode']}; use a fresh workspace")
            return old
        data = {"product": product, "mode": mode, "round": 0, "stages": {}}
        self._save(data)
        return data

    def mark(self, step: str, status: str, **extra) -> dict:
        if step not in STEPS or status not in STATUSES:
            raise WorkspaceError(f"cannot mark {step!r} {status!r}")
        data = self.run()
        data["stages"][step] = {"status": status, "at": datetime.now(UTC).isoformat(timespec="seconds"), **extra}
        self._save(data)
        return data

    def next_round(self) -> int:
        data = self.run()
        data["round"] = int(data.get("round", 0)) + 1
        self._save(data)
        return data["round"]

    def _save(self, data: dict) -> None:
        tmp = self.run_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(self.run_file)
