#!/usr/bin/env python3
"""Run a design review on a planted-problem test site and grade it (design role; host only).

    python3 configs/design/bin/design_trial.py fernway-v1 [--workflow design_review]
    python3 configs/design/bin/design_trial.py fernway-v1 --grade-only <review workspace>

Reads configs/design/testpages/<site>.json (brief, pages, answer key path), starts the review
workflow on testpages/<site>/ with a fresh workspace, waits for it, then starts
design_review_grade with the review's findings.json and the answer key as text, waits, and
prints the score. The key is read here on the host and never enters the review's run (keys
live in ~/design-lab/answers/, off every container mount). Standard library only.

Each start sends the design role's named key, so temper's write guard (docs/api-access.md)
names the caller: it is read at call time from the file named by TEMPER_API_KEY_FILE, else
~/.config/temper/api-keys/design.key. With no readable key file the start goes without one
(an unknown caller; refused once the guard enforces). The key is never printed, logged or
passed into a run.

Workspaces go under ~/temper-ai/workspaces (TEMPER_WORKSPACES), the folder run containers
mount at the same path; the site is served from the server's /app/configs, so a test site
must be on master before a trial can use it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

API = os.environ.get("TEMPER_API", "http://127.0.0.1:8420")
REPO = Path(__file__).resolve().parents[3]
WORKSPACES = Path(
    os.environ.get("TEMPER_WORKSPACES", str(Path.home() / "temper-ai" / "workspaces"))
)
CONTAINER_SITES = "/app/configs/design/testpages"
DEFAULT_KEY_FILE = Path.home() / ".config" / "temper" / "api-keys" / "design.key"


def _key_headers() -> dict[str, str]:
    """The Authorization header with the design key, or {} when its file can't be read."""
    path = Path(os.environ.get("TEMPER_API_KEY_FILE") or DEFAULT_KEY_FILE).expanduser()
    try:
        key = path.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    return {"Authorization": f"Bearer {key}"} if key else {}


def _post_run(workflow: str, workspace: Path, inputs: dict[str, str]) -> str:
    body = json.dumps(
        {"workflow": workflow, "workspace_path": str(workspace), "inputs": inputs}
    )
    req = urllib.request.Request(
        f"{API}/api/runs",
        data=body.encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    for name, value in _key_headers().items():
        req.add_unredirected_header(name, value)  # never follows a redirect elsewhere
    with urllib.request.urlopen(req, timeout=30) as resp:
        return str(json.load(resp)["execution_id"])


def _wait(execution_id: str, limit_s: int = 3600) -> dict:
    end = time.time() + limit_s
    while True:
        with urllib.request.urlopen(
            f"{API}/api/workflows/{execution_id}", timeout=30
        ) as resp:
            run = json.load(resp)
        if run.get("status") not in ("queued", "running", "pending"):
            return run
        if time.time() > end:
            raise SystemExit(
                f"{execution_id} still {run.get('status')} after {limit_s} s"
            )
        time.sleep(15)


def _cost(run: dict) -> float:
    return float(run.get("total_cost_usd") or run.get("estimated_cost_usd") or 0.0)


def _workspace(name: str) -> Path:
    path = WORKSPACES / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    path.mkdir(parents=True)
    path.chmod(0o777)  # the run's container user writes here
    return path


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("site", help="test site name, e.g. fernway-v1")
    ap.add_argument(
        "--workflow",
        default="design_review",
        help="review workflow (a candidate's name to compare)",
    )
    ap.add_argument(
        "--grade-only", metavar="WORKSPACE", help="grade an existing review workspace"
    )
    args = ap.parse_args()

    meta = json.loads(
        (REPO / "configs/design/testpages" / f"{args.site}.json").read_text(
            encoding="utf-8"
        )
    )
    key = Path(os.path.expanduser(meta["key"])).read_text(encoding="utf-8")
    result: dict[str, object] = {"site": args.site, "workflow": args.workflow}

    if args.grade_only:
        review_ws = Path(args.grade_only).resolve()
    else:
        review_ws = _workspace(f"design-trial-{args.site}")
        inputs = {
            "brief": meta["brief"],
            "pages": ",".join(meta["pages"]),
            "site": f"{CONTAINER_SITES}/{args.site}",
        }
        review_id = _post_run(args.workflow, review_ws, inputs)
        print(f"review {review_id} in {review_ws}", file=sys.stderr)
        review = _wait(review_id)
        result.update(
            review_id=review_id,
            review_status=review.get("status"),
            review_cost=_cost(review),
        )
        if review.get("status") != "completed":
            print(json.dumps(result, indent=1))
            return 1
    findings_path = review_ws / "review" / "findings.json"
    if not findings_path.exists():
        raise SystemExit(f"no findings at {findings_path}")

    grade_ws = _workspace(f"design-grade-{args.site}")
    grade_id = _post_run(
        "design_review_grade",
        grade_ws,
        {"findings": findings_path.read_text(encoding="utf-8"), "answer_key": key},
    )
    print(f"grade {grade_id} in {grade_ws}", file=sys.stderr)
    grade = _wait(grade_id, limit_s=1800)
    result.update(
        review_workspace=str(review_ws), grade_id=grade_id, grade_cost=_cost(grade)
    )
    score_path = grade_ws / "grade" / "score.json"
    if score_path.exists():
        result["score"] = json.loads(score_path.read_text(encoding="utf-8"))
    print(json.dumps(result, indent=1))
    return 0 if grade.get("status") == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
