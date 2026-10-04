#!/usr/bin/env python3
"""Pairwise design judge check (Design, queue #10): validate and summarise judge/verdict.json.

    design_pairwise_judge.py check --workspace W

Before a run the host lays out, under neutral single-letter labels, the page or pair to judge:
judge/task.json ({"mode": "pair" | "single", "pages": ["A", "B"]}) and, for every label,
judge/<label>/brief.md plus screenshot tiles desktop-NN.png and mobile-NN.png. The judge agent
(design_pairwise_judge) writes judge/verdict.json; this step checks it against the task and returns
the verdict. Which page is which version stays on the host. No model here.

The judge is advice: its picks are recorded beside the owner's blind picks on Design's scoreboard to
measure how often it agrees, and never count as approval.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

LABEL = re.compile(r"^[A-Z]$")
STRENGTHS = ("slight", "clear", "strong")


def task_for(workspace: Path) -> dict:
    path = workspace / "judge" / "task.json"
    if not path.is_file():
        raise ValueError("no judge/task.json in this workspace")
    try:
        task = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"judge/task.json is not valid JSON: {exc}") from None
    pages = task.get("pages")
    if task.get("mode") not in ("pair", "single") or not isinstance(pages, list):
        raise ValueError("judge/task.json needs mode pair or single and a pages list")
    want = 2 if task["mode"] == "pair" else 1
    if (len(pages) != want or len(set(pages)) != want
            or not all(isinstance(p, str) and LABEL.match(p) for p in pages)):
        raise ValueError("a pair task names two different single-letter pages, a single task one")
    for page in pages:
        folder = workspace / "judge" / page
        if not (folder / "brief.md").is_file() or not sorted(folder.glob("desktop-*.png")):
            raise ValueError(f"page {page} lacks brief.md or desktop tiles")
    return task


def check(workspace: Path) -> dict:
    task = task_for(workspace)
    pages = task["pages"]
    path = workspace / "judge" / "verdict.json"
    if not path.is_file():
        raise ValueError("the judge wrote no judge/verdict.json")
    try:
        verdict = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"judge/verdict.json is not valid JSON: {exc}") from None
    if not isinstance(verdict, dict):
        raise ValueError("judge/verdict.json must be an object")
    ratings = verdict.get("ratings")
    if (not isinstance(ratings, dict) or sorted(ratings) != sorted(pages)
            or not all(type(v) is int and 1 <= v <= 5 for v in ratings.values())):
        raise ValueError(f"ratings must give every page ({', '.join(pages)}) a whole number from 1 to 5")
    reasons = verdict.get("reasons")
    if not isinstance(reasons, list) or len([r for r in reasons if isinstance(r, str) and r.strip()]) < 2:
        raise ValueError("verdict needs at least two reasons")
    result = {"status": "completed", "mode": task["mode"], "pages": pages, "ratings": ratings,
              "reasons": len(reasons), "verdict_path": "judge/verdict.json"}
    if task["mode"] == "pair":
        pick, strength = verdict.get("pick"), verdict.get("strength")
        if pick not in pages:
            raise ValueError(f"pick must be one of {', '.join(pages)} (no ties)")
        if strength not in STRENGTHS:
            raise ValueError(f"strength must be one of {', '.join(STRENGTHS)}")
        other = next(p for p in pages if p != pick)
        result.update(pick=pick, strength=strength, consistent=ratings[pick] >= ratings[other])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=("check",))
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    try:
        result = check(Path(args.workspace).resolve())
    except (ValueError, OSError) as exc:
        raise SystemExit(f"check: {exc}") from None
    result["seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
