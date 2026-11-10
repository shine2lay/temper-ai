"""The foundation run workspace: one folder per stage and run.json (product, stage status, round).

Brief-led stages and workspace folders:
    01-brief       brief.json (7-section product brief contract, extracted constraints + taste anchors)
    02-directions  task.md, directions.json, <id>/{tokens.json, DESIGN.md}, gate_direction.json
    03-proof       proof.json, sample-screen.html (when no live app render surface)
    04-build       build.json, tokens.json, DESIGN.md
    05-checks      round-<n>/checks.json, gate_final.json
    06-handoff     handoff.json, tokens.json, DESIGN.md

Reuses the proven Workspace base from app_screen.workspace while enforcing foundation/contracts.py's
per-step STEP_INPUTS declarations on every read.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app_screen.workspace import (
    DECISION_KEYS,
    PRODUCT_ID,
    STATUSES,
    WorkspaceError,
)
from app_screen.workspace import (
    Workspace as AppScreenWorkspace,
)

STAGES = ("brief", "directions", "proof", "build", "checks", "handoff")
STEPS = STAGES + (
    "directions_collect",
    "directions_check",
    "gate_direction",
    "build_collect",
    "build_check",
    "gate_final",
)
FOLDERS = {
    "brief": "01-brief",
    "directions": "02-directions",
    "proof": "03-proof",
    "build": "04-build",
    "checks": "05-checks",
    "handoff": "06-handoff",
}

__all__ = [
    "DECISION_KEYS",
    "FOLDERS",
    "PRODUCT_ID",
    "STAGES",
    "STATUSES",
    "STEPS",
    "Workspace",
    "WorkspaceError",
]


class Workspace(AppScreenWorkspace):
    """Foundation workspace accessor enforcing foundation.contracts.STEP_INPUTS on every read."""

    def __init__(
        self,
        path: Path | str,
        *,
        step: str | None = None,
        extra_inputs: Iterable[str] = (),
    ):
        super().__init__(path, step=step)
        self.extra_inputs: tuple[str, ...] = tuple(extra_inputs)

    @property
    def repo_root(self) -> Path:
        """Product repository root when workspace lives at <repo>/.temper/design, else workspace root."""
        resolved = self.path.resolve()
        if resolved.name == "design" and resolved.parent.name == ".temper":
            return resolved.parent.parent.resolve()
        return resolved

    def for_step(
        self,
        step: str,
        *,
        extra_inputs: Iterable[str] | None = None,
    ) -> Workspace:
        """Return a Workspace view bound to ``step`` so every read validates against STEP_INPUTS[step]."""
        merged = self.extra_inputs if extra_inputs is None else tuple(extra_inputs)
        return Workspace(self.path, step=step, extra_inputs=merged)

    def bind_step(
        self,
        step: str | None,
        *,
        extra_inputs: Iterable[str] | None = None,
    ) -> Workspace:
        """Bind this Workspace instance to ``step`` in place and return self."""
        self.step = step
        if extra_inputs is not None:
            self.extra_inputs = tuple(extra_inputs)
        return self

    bind = bind_step

    def resolve_input(
        self,
        target: Path | str,
        *,
        step: str | None = None,
        repo_input: bool = False,
        allowed_topics: Iterable[str] | None = None,
    ) -> Path:
        """Resolve ``target`` only if declared for ``step`` in foundation/contracts.py; fail loud otherwise."""
        del allowed_topics  # foundation steps never read .temper/topics/*
        from . import contracts

        active_step = step if step is not None else self.step
        if not active_step:
            raise contracts.ContractError("Workspace read requires a step name")

        ws_root = self.path.resolve()
        r_root = self.repo_root
        raw_str = str(target).strip().replace("\\", "/")
        while raw_str.startswith("./"):
            raw_str = raw_str[2:]

        t_path = Path(target)
        if t_path.is_absolute():
            resolved_t = t_path.resolve(strict=False)
            if resolved_t.is_relative_to(ws_root):
                rel = resolved_t.relative_to(ws_root).as_posix()
                norm = contracts.check_input(
                    active_step, rel, repo_input=False, extra_inputs=self.extra_inputs
                )
                return ws_root / norm
            if resolved_t.is_relative_to(r_root):
                rel = resolved_t.relative_to(r_root).as_posix()
                norm = contracts.check_input(
                    active_step, rel, repo_input=True, extra_inputs=self.extra_inputs
                )
                return r_root / norm
            norm = contracts.check_input(
                active_step, resolved_t.as_posix(), repo_input=True, extra_inputs=self.extra_inputs
            )
            return Path(norm)

        is_repo = repo_input or raw_str.startswith(".temper/")
        if is_repo:
            norm = contracts.check_input(
                active_step, raw_str, repo_input=True, extra_inputs=self.extra_inputs
            )
            cand = (r_root / norm).resolve(strict=False)
            if not cand.is_relative_to(r_root):
                raise contracts.ContractError(
                    f"step '{active_step}' refused undeclared read of '{raw_str}' (path escapes repository); "
                    f"declared inputs: {contracts.declared_inputs(active_step, extra_inputs=self.extra_inputs)}"
                )
            return cand

        norm = contracts.check_input(
            active_step, raw_str, repo_input=False, extra_inputs=self.extra_inputs
        )
        return ws_root / norm

    def folder(self, stage: str) -> Path:
        if stage not in FOLDERS:
            raise WorkspaceError(f"unknown stage {stage!r}; stages are {', '.join(STAGES)}")
        return self.path / FOLDERS[stage]

    def mark(self, step: str, status: str, **extra: Any) -> dict[str, Any]:
        if step not in STEPS or status not in STATUSES:
            raise WorkspaceError(f"cannot mark {step!r} {status!r}")
        data = self.run()
        before = data["stages"].get(step) or {}
        kept = {k: before[k] for k in DECISION_KEYS if k in before and k not in extra}
        data["stages"][step] = {
            "status": status,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            **kept,
            **extra,
        }
        self._save(data)
        return data
