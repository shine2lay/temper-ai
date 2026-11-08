"""The app-screen run workspace: one folder per stage and run.json (product, stage status, round).

Every stage reads and writes only inside the workspace. run.json is the run's own record:
    {"product": "rollcall", "round": 1,
     "stages": {"intake": {"status": "done", "at": "..."}, ...}}

Step 4 (reuse): the host's prepare writes the decision for stages 2-3 into their entries before the run
(status planned, with decision, reason, source_run, store_version and the screens a delta re-captures); the
entry keeps those fields through later marks, and a stage that reused or redid only what changed ends reused
or delta instead of done.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

STAGES = ("intake", "existing", "ground", "directions", "build", "checks", "show", "handoff")
# Workflow steps that are not one of the eight stages: intake's, existing's and ground's collect and draft-check
# steps (their model steps are agents of their own), existing's sheet step, the two owner gates, the review half of
# the checks stage, and the bookkeeping step after the final gate.
STEPS = STAGES + ("intake_collect", "intake_check", "existing_collect", "existing_sheet", "existing_check",
                  "ground_collect", "ground_check", "directions_collect", "directions_check", "gate_direction",
                  "build_check", "build_finish", "review_collect", "review_check", "review",
                  "gate_final", "gate_final_next")
FOLDERS = {"intake": "01-request", "existing": "02-existing", "ground": "03-ground", "directions": "04-directions",
           "build": "05-build", "checks": "06-checks", "show": "07-show", "handoff": "08-handoff"}
STATUSES = ("running", "done", "failed", "planned", "reused", "delta")
DECISIONS = ("reuse", "delta", "run", "pending")       # pending: ground's, finished by ground_collect
DECISION_KEYS = ("decision", "reason", "source_run", "store_version", "screens")
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
            raise WorkspaceError(f"{self.run_file} is missing: run prepare, pack, or intake first")
        data = json.loads(self.run_file.read_text())
        if not isinstance(data, dict) or not PRODUCT_ID.match(str(data.get("product"))):
            raise WorkspaceError(f"{self.run_file}: needs product (lowercase id)")
        return data

    @property
    def round(self) -> int:
        return int(self.run().get("round", 0))

    def start(self, product: str) -> dict:
        """Write a fresh run.json (host prepare, pack, or intake); an existing one with another product fails."""
        if not PRODUCT_ID.match(product or ""):
            raise WorkspaceError(f"product {product!r} is not a lowercase id (a-z, 0-9, -)")
        if self.run_file.exists():
            old = self.run()
            if old["product"] != product:
                raise WorkspaceError(f"{self.run_file} already holds {old['product']}; use a fresh workspace")
            return old
        data = {"product": product, "round": 0, "stages": {}}
        self._save(data)
        return data

    def mark(self, step: str, status: str, **extra) -> dict:
        if step not in STEPS or status not in STATUSES:
            raise WorkspaceError(f"cannot mark {step!r} {status!r}")
        data = self.run()
        before = data["stages"].get(step) or {}
        kept = {k: before[k] for k in DECISION_KEYS if k in before and k not in extra}
        data["stages"][step] = {"status": status, "at": datetime.now(UTC).isoformat(timespec="seconds"), **kept,
                                **extra}
        self._save(data)
        return data

    def decide(self, stage: str, decision: str, reason: str, **fields) -> dict:
        """Record stage 2's or 3's reuse decision (prepare, or ground_collect finishing ground's)."""
        if stage not in ("existing", "ground") or decision not in DECISIONS or not reason:
            raise WorkspaceError(f"cannot record decision {decision!r} for {stage!r} (needs a reason)")
        unknown = set(fields) - set(DECISION_KEYS)
        if unknown:
            raise WorkspaceError(f"unknown decision field(s): {', '.join(sorted(unknown))}")
        # planned until the stage's own step ends it reused, delta or done: store accepts only a finished stage
        data = self.run()
        data["stages"][stage] = {"status": "planned", "at": datetime.now(UTC).isoformat(timespec="seconds"),
                                 "decision": decision, "reason": reason,
                                 **{k: v for k, v in fields.items() if v is not None}}
        self._save(data)
        return data

    def decision(self, stage: str) -> dict | None:
        """Stage 2's or 3's recorded decision ({decision, reason, ...}), or None (no prepare: run as before)."""
        entry = self.run()["stages"].get(stage) or {}
        if entry.get("decision") not in DECISIONS:
            return None
        return {k: entry[k] for k in DECISION_KEYS if k in entry}

    def next_round(self) -> int:
        data = self.run()
        data["round"] = int(data.get("round", 0)) + 1
        self._save(data)
        return data["round"]

    def _save(self, data: dict) -> None:
        tmp = self.run_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(self.run_file)
