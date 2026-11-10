#!/usr/bin/env python3
"""Gate-backed pause relay for `code_land`.

Runs after a human or lead approves the `code_land_pause` gate on a paused
`code_land_attempt`. Echoes durable repository/PR/branch context plus the gate
approval payload so Round 2+ of `code_land_attempt` can resume statelessly even
when Round 1's container or `/tmp` `work_dir` no longer exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_BIN_DIR = Path(__file__).resolve().parent
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

import code_checkout  # noqa: E402


class CodeLandPauseError(Exception):
    """Raised when pause relay inputs are missing or malformed."""


def _parse_json_obj(raw: str | dict[str, Any] | None, *, field: str, required: bool) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if required:
            raise CodeLandPauseError(f"missing required {field} JSON object")
        return {}
    if not isinstance(raw, str):
        raise CodeLandPauseError(f"invalid {field}: expected JSON object string")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        if not required:
            return {"raw": raw}
        raise CodeLandPauseError(f"invalid {field} JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        if not required:
            return {"value": parsed}
        raise CodeLandPauseError(f"invalid {field}: expected JSON object")
    return parsed


def build_pause_relay(
    *,
    attempt_state: str | dict[str, Any] | None,
    gate: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce durable retry payload from `attempt_state` + human `gate` response."""
    state = _parse_json_obj(attempt_state, field="attempt_state", required=True)
    gate_obj = _parse_json_obj(gate, field="gate", required=False)

    repo = str(state.get("repo") or "").strip()
    branch = str(state.get("branch") or "").strip()
    base = str(state.get("base") or "").strip()
    if not repo or not branch or not base:
        raise CodeLandPauseError(
            "attempt_state must include non-empty 'repo', 'branch', and 'base'"
        )

    resolved_files_raw = state.get("resolved_files")
    resolved_files = (
        [str(f) for f in resolved_files_raw if isinstance(f, str) and f]
        if isinstance(resolved_files_raw, list)
        else []
    )

    return {
        "verdict": "retry",
        "repo": repo,
        "pr_url": str(state.get("pr_url") or ""),
        "pr_number": state.get("pr_number"),
        "branch": branch,
        "base": base,
        "sha": str(state.get("sha") or ""),
        "mode": str(state.get("mode") or "pr"),
        "merge_method": str(state.get("merge_method") or "squash"),
        "require_checks": bool(state.get("require_checks", True)),
        "auto_resolved": bool(state.get("auto_resolved", False)),
        "resolved_files": resolved_files,
        "prior_reason": str(state.get("reason") or ""),
        "gate_response": gate_obj,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Echo durable code_land state after gate approval to trigger a stateless retry."
    )
    parser.add_argument(
        "--attempt-state",
        default="",
        help="JSON structured output from the paused code_land_attempt node",
    )
    parser.add_argument(
        "--gate",
        default="",
        help="Optional JSON gate response supplied on gate approval",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        payload = build_pause_relay(
            attempt_state=args.attempt_state,
            gate=args.gate,
        )
    except CodeLandPauseError as exc:
        code_checkout.fail(str(exc))
    code_checkout.emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
