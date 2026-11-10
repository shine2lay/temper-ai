#!/usr/bin/env python3
"""External bench/replay CLI for design_foundation_v1_bench (Rule 29: test harness outside production code).

Replays workspace_startup/workspace_cleanup, stack_up_ref/stack_seed/stack_down, and model-boundary
draft steps (directions_read/directions_revise/build_read/build_revise) at $0.00 cost while every
production stage step (brief, directions_collect, directions_check, directions, proof, gate_direction,
build_collect, build_check, build, checks, gate_final, handoff) executes via design_foundation_stage_v1.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BIN_DIR = HERE.parent
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from foundation import contracts  # noqa: E402

BENCH_COMMIT = "81117dd509f2272d3f2fb36af16f118819efb0f4"

BENCH_BRIEF_MD = """# Product brief

## 1. What it is
Covered-call trading workspace that shows active option positions, assignment exposure, and roll candidates in one glance.

## 2. Who for
Self-directed equity investors managing weekly and monthly covered calls across taxable and retirement accounts.

## 3. Where and how used
Checked on desktop at market open for roll decisions and glanced at on mobile during market hours when alerts fire.

## 4. How it should feel plus what it must not feel like
Calm, high-precision financial ledger with unmistakable hierarchy; must never feel like a casino ticker, neon crypto dashboard, or flat grey spreadsheet.

## 5. The neighbours
Adjacent to Tastytrade, Interactive Brokers Client Portal, and Linear's keyboard-first clarity.

## 6. What is fixed
- Existing wordmark and symbol proportions stay untouched; foundation covers colour, type, spacing, radius, elevation, and motion only.
- Must satisfy WCAG 2.2 AA 4.5:1 normal text contrast in both light and dark themes.

## 7. Taste anchors
<!-- Filled by owner at gate_direction when empty -->
"""


def default_bench_repo(product: str, run_id: str = "") -> Path:
    suffix = f"{product}-{run_id[:12]}" if run_id else product
    shared_root = Path("/app/workspaces")
    if shared_root.is_dir() and os.access(shared_root, os.W_OK):
        return shared_root / f"bench-foundation-{suffix}"
    return Path(f"/tmp/temper-bench-foundation-{suffix}")


def _chmod_tree(root: Path) -> None:
    for cur, dirs, files in os.walk(root):
        cur_p = Path(cur)
        try:
            cur_p.chmod(0o777)
        except OSError:
            pass
        for d in dirs:
            try:
                (cur_p / d).chmod(0o777)
            except OSError:
                pass
        for f in files:
            try:
                (cur_p / f).chmod(0o666)
            except OSError:
                pass


def replay_workspace(
    step: str,
    *,
    product: str,
    workspace: str = "",
    run_slug: str = "design",
    run_id: str = "",
) -> dict[str, Any]:
    prod = (product or "rollcall").strip() or "rollcall"
    slug = f"{prod}-{run_slug or 'design'}-foundation"

    suffix = f"{prod}-{run_id.strip()[:12]}" if run_id.strip() else prod
    ws_override = workspace.strip() or os.environ.get("FOUNDATION_BENCH_WORKSPACE", "").strip()
    if ws_override:
        ws_p = Path(ws_override).expanduser().resolve()
        if str(ws_p) in ("/app/workspaces", "/home/shinelay/temper-ai/workspaces"):
            repo_root = ws_p / f"bench-foundation-{suffix}"
            dept_path = repo_root / ".temper" / "design"
        elif ws_p.name == "design" and ws_p.parent.name == ".temper":
            repo_root = ws_p.parent.parent
            dept_path = ws_p
        else:
            repo_root = ws_p
            dept_path = repo_root / ".temper" / "design"
    else:
        repo_root = default_bench_repo(prod, run_id=run_id.strip())
        dept_path = repo_root / ".temper" / "design"

    temper_path = dept_path.parent

    if step == "workspace_startup":
        already_initialized = (repo_root / ".temper").exists()
        brief_file = repo_root / ".temper" / "product" / "brief.md"
        seed_default = os.environ.get("FOUNDATION_BENCH_SEED_BRIEF", "1").strip() != "0"
        if not already_initialized and seed_default and not brief_file.is_file():
            brief_file.parent.mkdir(parents=True, exist_ok=True)
            brief_file.write_text(BENCH_BRIEF_MD, encoding="utf-8")
        dept_path.mkdir(parents=True, exist_ok=True)
        _chmod_tree(repo_root)
        return {
            "status": "ready",
            "repo": prod,
            "task_slug": slug,
            "worktree_path": str(repo_root),
            "temper_path": str(temper_path),
            "department_path": str(dept_path),
            "department": "design",
            "excluded_dirs": [".temper/design"],
            "head": BENCH_COMMIT,
            "worktree": "created",
        }

    if step == "workspace_cleanup":
        env_ws = os.environ.get("FOUNDATION_BENCH_WORKSPACE", "").strip()
        explicit_bench = bool(env_ws and repo_root == Path(env_ws).expanduser().resolve())
        if repo_root.exists() and (
            repo_root.name.startswith("bench-foundation-")
            or str(repo_root).startswith("/tmp/")
            or explicit_bench
        ):
            _chmod_tree(repo_root)
            for child in list(repo_root.iterdir()):
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    try:
                        child.unlink()
                    except OSError:
                        pass
            shutil.rmtree(repo_root, ignore_errors=True)
        return {
            "status": "clean",
            "repo": prod,
            "task_slug": slug,
            "worktree": "removed",
            "branch": "deleted",
            "claim": "released",
        }

    raise ValueError(f"unknown bench workspace step {step!r}")


def replay_stack(
    step: str,
    *,
    product: str,
    ref: str = "origin/master",
    slug: str = "design",
) -> dict[str, Any]:
    prod = (product or "rollcall").strip() or "rollcall"
    env_name = f"{prod}-dev-{slug or 'design'}"
    url = f"https://{slug or 'design'}.dev.{prod}.wai2shine.com"
    if step == "stack_up_ref":
        return {
            "status": "up",
            "env_name": env_name,
            "base_url": url,
            "url": url,
            "commit": BENCH_COMMIT,
            "short_commit": BENCH_COMMIT[:12],
            "ref": ref or "origin/master",
            "product": prod,
            "reused": True,
        }
    if step == "stack_seed":
        return {
            "status": "seeded",
            "env_name": env_name,
        }
    if step == "stack_down":
        return {
            "status": "down",
            "env_name": env_name,
            "volumes_left": "none",
            "leftover_volumes_removed": [],
        }
    raise ValueError(f"unknown bench stack step {step!r}")


BENCH_DIRECTIONS_DRAFT: dict[str, Any] = {
    "recommended": "a",
    "directions": [
        {
            "id": "a",
            "name": "Warm Ledger",
            "premise": "Warm stone ledger surfaces with disciplined forest-emerald primary emphasis and high-precision tabular figures for covered-call position triage.",
            "anchor_hue_deg": 155.0,
            "chroma_intent": "balanced",
            "neutral_temp": "warm",
            "type_family": "IBM Plex Sans",
            "why": "Fits self-directed equity investors scanning roll candidates at market open with calm ledger hierarchy and zero casino-ticker noise.",
            "evidence": {
                "premise": "L01: assignment exposure, and roll candidates",
                "anchor_hue_deg": "L04: Calm, high-precision financial ledger",
                "chroma_intent": "L04: casino ticker",
                "neutral_temp": "L02: Self-directed equity investors managing weekly and monthly covered calls",
                "type_family": "L05: Tastytrade, Interactive Brokers Client Portal",
                "why": "L03: at market open for roll decisions",
            },
        },
        {
            "id": "b",
            "name": "Mineral Instrument",
            "premise": "Cool slate instrument workspace with crisp mineral-blue primary actions and keyboard-first typographic hierarchy across desktop and mobile.",
            "anchor_hue_deg": 230.0,
            "chroma_intent": "crisp",
            "neutral_temp": "cool",
            "type_family": "Plus Jakarta Sans",
            "why": "Gives dense options chains and mobile alert triage crisp contrast in both light and dark themes while keeping existing wordmark proportions untouched.",
            "evidence": {
                "premise": "L03: at market open for roll decisions",
                "anchor_hue_deg": "L05: Tastytrade, Interactive Brokers Client Portal",
                "chroma_intent": "L07: in both light and dark themes",
                "neutral_temp": "L04: Calm, high-precision financial ledger",
                "type_family": "L06: foundation covers colour, type, spacing, radius, elevation, and motion only",
                "why": "L02: Self-directed equity investors managing weekly and monthly covered calls",
            },
        },
        {
            "id": "c",
            "name": "Copper Desk",
            "premise": "True-neutral institutional desk with muted amber-ochre action focus and editorial sans hierarchy for calm portfolio review.",
            "anchor_hue_deg": 55.0,
            "chroma_intent": "muted",
            "neutral_temp": "true",
            "type_family": "Source Sans 3",
            "why": "Separates weekly and monthly covered-call exposure across taxable and retirement accounts without neon dashboard glare.",
            "evidence": {
                "premise": "L01: assignment exposure, and roll candidates",
                "anchor_hue_deg": "L04: Calm, high-precision financial ledger",
                "chroma_intent": "L07: in both light and dark themes",
                "neutral_temp": "L06: foundation covers colour, type, spacing, radius, elevation, and motion only",
                "type_family": "L05: Tastytrade, Interactive Brokers Client Portal",
                "why": "L02: Self-directed equity investors managing weekly and monthly covered calls",
            },
        },
    ],
}


BENCH_BUILD_DRAFT: dict[str, Any] = {
    "product": "rollcall",
    "direction_id": "a",
    "direction_name": "Warm Ledger",
    "users": [
        "Self-directed equity investors managing weekly and monthly covered calls across accounts.",
        "Traders reviewing active short calls, assignment exposure, and roll candidates at market open on desktop or mobile alert triage.",
    ],
    "premise": "Warm stone ledger surfaces with disciplined forest-emerald primary emphasis and high-precision tabular figures for covered-call position triage.",
    "why": [
        "Supports calm financial ledger hierarchy at market open for roll decisions without casino-ticker noise.",
        "Keeps active short calls, assignment exposure, and roll candidates readable across light and dark themes.",
    ],
    "how_to_use": [
        "Use `colour.paper` for the main portfolio workspace canvas and `colour.surface` for raised covered-call position and roll-candidate cards.",
        "Reserve `colour.accent` and `colour.accent_on` for the primary roll decision action in each view.",
        "Set workspace headings and labels in `type.family.sans` and all active short call and assignment exposure figures in `type.family.mono` with `spacing.2` and `radius.md`.",
    ],
    "what_not_to_do": [
        "Never replace `colour.paper` or `colour.dark.surface.canvas` with neon purple gradients on portfolio ledger views.",
        "Never stack competing `colour.accent` solid buttons or introduce casino ticker chrome around covered-call tables.",
        "Never render assignment exposure or roll candidate figures in proportional fonts instead of `type.family.mono`.",
    ],
    "evidence": {
        "users": "L02: Self-directed equity investors managing weekly and monthly covered calls",
        "premise": "L01: assignment exposure, and roll candidates",
        "why": "L03: at market open for roll decisions",
        "how_to_use": "L07: in both light and dark themes",
        "what_not_to_do": "L04: must never feel like a casino ticker, neon crypto dashboard",
    },
}


def replay_model(step: str, *, task: str = "", draft: str = "", problems: str = "") -> dict[str, Any]:
    if step not in contracts.MODEL_STEPS:
        raise ValueError(f"step {step!r} is not a declared MODEL_STEPS entry ({sorted(contracts.MODEL_STEPS)})")
    del draft, problems
    if step in ("directions_read", "directions_revise"):
        return dict(BENCH_DIRECTIONS_DRAFT)
    if step in ("build_read", "build_revise"):
        payload = copy.deepcopy(BENCH_BUILD_DRAFT)
        m_prod = re.search(
            r"# Stage 5 \(`build_read`\) — `([a-z0-9-]+)` \(round \d+, direction `([a-z0-9][a-z0-9_-]*)`: ([^)]+)\)",
            task,
        )
        if m_prod:
            payload["product"] = m_prod.group(1)
            payload["direction_id"] = m_prod.group(2)
            payload["direction_name"] = m_prod.group(3).strip()
        else:
            m_p = re.search(r"(?:Product|`product`):\s*`([a-z0-9-]+)`", task)
            if m_p:
                payload["product"] = m_p.group(1)
            m_d_id = re.search(r"`direction_id`:\s*`([a-z0-9][a-z0-9_-]*)`", task)
            if m_d_id:
                payload["direction_id"] = m_d_id.group(1)
            m_d_name = re.search(r"`direction_name`:\s*`([^`]+)`", task)
            if m_d_name:
                payload["direction_name"] = m_d_name.group(1).strip()
            m_d = re.search(r"Chosen direction:\s*`([a-z0-9][a-z0-9_-]*)`\s*—\s*\*\*([^*]+)\*\*", task)
            if m_d:
                payload["direction_id"] = m_d.group(1)
                payload["direction_name"] = m_d.group(2).strip()
        return payload
    raise ValueError(f"unsupported replay model step {step!r}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="foundation_harness/cli.py", description=__doc__)
    p.add_argument(
        "--step",
        required=True,
        choices=(
            "workspace_startup",
            "workspace_cleanup",
            "stack_up_ref",
            "stack_seed",
            "stack_down",
            *contracts.MODEL_STEPS,
        ),
    )
    p.add_argument("--product", default="rollcall")
    p.add_argument("--workspace", default="")
    p.add_argument("--run-slug", default="design")
    p.add_argument("--run-id", default="")
    p.add_argument("--ref", default="origin/master")
    p.add_argument("--task", default="")
    p.add_argument("--draft", default="")
    p.add_argument("--problems", default="")
    args = p.parse_args(argv)

    if args.step in contracts.MODEL_STEPS:
        if args.workspace.strip():
            print(f"model step {args.step!r} refuses workspace_path", file=sys.stderr)
            return 1
        out = replay_model(args.step, task=args.task, draft=args.draft, problems=args.problems)
    elif args.step in ("workspace_startup", "workspace_cleanup"):
        out = replay_workspace(
            args.step,
            product=args.product,
            workspace=args.workspace,
            run_slug=args.run_slug,
            run_id=args.run_id,
        )
    else:
        out = replay_stack(args.step, product=args.product, ref=args.ref, slug=args.run_slug)

    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
