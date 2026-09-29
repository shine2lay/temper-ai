#!/usr/bin/env python3
"""Watch GitHub's checks and say something on Slack when they change.

Master was red for eight days and nobody knew, because knowing required
someone to open the Actions tab and look. Nothing on GitHub was going to
volunteer it: a workflow can only send a message if it holds the Slack
token, and putting temper's bot token in GitHub's secrets is a copy of a
credential in a place the owner does not control.

So the watching happens here, on the box that already has the token. A
timer runs this every ten minutes; it reads the runs with `gh` (which is
already logged in) and sends the owner a DM from temper's bot — the same
bot and the same DM that temper-deploy's notices and the merge nudge use.

What it says, each exactly once per change:

* master's checks went red  — with the jobs that failed
* master's checks are green again
* the nightly found the newest libraries breaking temper
* the nightly found a flaky test — with the names

"Once" is kept honest by a state file: the last thing said about each
subject, and the run it was said about. Nothing is repeated until the
answer changes.

    ci_watch.py            look once and send what is due
    ci_watch.py --test     send one sample DM and record nothing
    ci_watch.py --dry-run  print what it would send
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = os.environ.get("TEMPER_CI_REPO", "shine2lay/temper-ai")
BRANCH = os.environ.get("TEMPER_CI_BRANCH", "master")
STATE = Path(os.environ.get("TEMPER_CI_WATCH_STATE",
                            Path.home() / ".local/state/temper-ci-watch.json"))
TEMPER_ENV = Path(os.environ.get("TEMPER_ENV_FILE", Path.home() / "temper-ai/.env"))
OWNER_SLACK_DM = os.environ.get("EPD_OWNER_SLACK_DM", "U0BDD2J0DAQ")

CI_WORKFLOW = "CI"
NIGHTLY_WORKFLOW = "Nightly"


# ─── talking ──────────────────────────────────────────────────────────────

def slack_token() -> str:
    for line in TEMPER_ENV.read_text(encoding="utf-8").splitlines() if TEMPER_ENV.exists() else []:
        key, sep, value = line.partition("=")
        if sep and key.strip() == "SLACK_BOT_TOKEN":
            return value.strip().strip('"').strip("'")
    return ""


def tell_owner(text: str) -> bool:
    """A Slack DM to the owner from temper's bot. False and a note when it could not be sent."""
    token = slack_token()
    if not token or not OWNER_SLACK_DM:
        print(f"no SLACK_BOT_TOKEN in {TEMPER_ENV} or no owner id: not sent", file=sys.stderr)
        return False

    def call(method: str, **fields):
        req = urllib.request.Request(
            f"https://slack.com/api/{method}",
            data=json.dumps(fields).encode(),
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            reply = json.load(resp)
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error", "unknown Slack error"))
        return reply

    try:
        channel = call("conversations.open", users=OWNER_SLACK_DM)["channel"]["id"]
        call("chat.postMessage", channel=channel, text=text, unfurl_links=False)
        return True
    except Exception as exc:  # noqa: BLE001 — a failed DM is retried on the next tick
        print(f"Slack DM failed: {exc}", file=sys.stderr)
        return False


# ─── looking ──────────────────────────────────────────────────────────────

def gh(*args: str) -> str:
    """Run gh and return stdout. Empty string when gh itself failed."""
    try:
        done = subprocess.run(("gh", *args), capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"gh {' '.join(args)}: {exc}", file=sys.stderr)
        return ""
    if done.returncode != 0:
        print(f"gh {' '.join(args)}: {done.stderr.strip()[:300]}", file=sys.stderr)
        return ""
    return done.stdout


def latest_run(workflow: str, branch: str | None) -> dict | None:
    """The newest finished run of a workflow, as a dict, or None."""
    args = ["run", "list", "--repo", REPO, "--workflow", workflow, "--limit", "12",
            "--json", "databaseId,conclusion,status,headSha,displayTitle,url,createdAt,headBranch"]
    if branch:
        args += ["--branch", branch]
    try:
        runs = json.loads(gh(*args) or "[]")
    except ValueError:
        return None
    finished = [r for r in runs if r.get("status") == "completed"]
    return finished[0] if finished else None


def failed_jobs(run_id: int) -> list[str]:
    try:
        jobs = json.loads(gh("run", "view", str(run_id), "--repo", REPO, "--json", "jobs") or "{}")
    except ValueError:
        return []
    return [j["name"] for j in jobs.get("jobs", []) if j.get("conclusion") == "failure"]


def flaky_names(run_id: int) -> list[str]:
    """The tests the nightly's flaky report named, pulled out of the job log."""
    log = gh("run", "view", str(run_id), "--repo", REPO, "--log-failed")
    names: list[str] = []
    for line in log.splitlines():
        # flaky_report.py prints them as markdown list items: "- `the name`"
        if match := re.search(r"- `([^`]+)`\s*$", line):
            name = match.group(1)
            if name not in names:
                names.append(name)
    return names[:12]


# ─── deciding ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def short(sha: str) -> str:
    return (sha or "")[:7]


def ci_message(run: dict, jobs: list[str], red: bool) -> str:
    if red:
        which = "\n".join(f"  · {name}" for name in jobs[:8]) or "  · (no job named it)"
        return (f"temper: master's checks are RED.\n"
                f"{run['displayTitle']} ({short(run['headSha'])})\n"
                f"Failed:\n{which}\n{run['url']}")
    return (f"temper: master's checks are green again.\n"
            f"{run['displayTitle']} ({short(run['headSha'])})\n{run['url']}")


def nightly_message(run: dict, jobs: list[str], flaky: list[str]) -> str:
    lines = ["temper: the nightly found something."]
    newest = [j for j in jobs if "newest" in j.lower()]
    repeats = [j for j in jobs if "times over" in j.lower()]
    if newest:
        lines.append("· The newest library versions break temper: " + ", ".join(newest))
        lines.append("  (nothing is pinned to them; this is a heads-up, not a breakage.)")
    if repeats:
        lines.append("· A test does not agree with itself: " + ", ".join(repeats))
        for name in flaky:
            lines.append(f"    {name}")
    if not newest and not repeats:
        lines.append("· " + ", ".join(jobs[:6]))
    lines.append(run["url"])
    return "\n".join(lines)


def check_ci(state: dict, send) -> dict:
    run = latest_run(CI_WORKFLOW, BRANCH)
    if not run:
        return state
    conclusion = run.get("conclusion")
    if conclusion not in ("success", "failure"):
        return state                      # cancelled, skipped: not news
    was = state.get("ci", {}).get("conclusion")
    if was == conclusion:
        return state                      # same answer as last time: say nothing
    red = conclusion == "failure"
    jobs = failed_jobs(run["databaseId"]) if red else []
    # The very first look records where things stand without shouting about it;
    # a green master is not news, a red one is.
    if was is None and not red:
        state["ci"] = {"conclusion": conclusion, "run": run["databaseId"]}
        return state
    if send(ci_message(run, jobs, red)):
        state["ci"] = {"conclusion": conclusion, "run": run["databaseId"]}
    return state


def check_nightly(state: dict, send) -> dict:
    run = latest_run(NIGHTLY_WORKFLOW, None)
    if not run or run.get("conclusion") not in ("success", "failure"):
        return state
    seen = state.get("nightly", {}).get("run")
    if seen == run["databaseId"]:
        return state                      # already looked at this one
    if run["conclusion"] == "success":
        state["nightly"] = {"run": run["databaseId"], "conclusion": "success"}
        return state                      # a quiet nightly is not worth a message
    jobs = failed_jobs(run["databaseId"])
    flaky = flaky_names(run["databaseId"]) if any("times over" in j.lower() for j in jobs) else []
    if send(nightly_message(run, jobs, flaky)):
        state["nightly"] = {"run": run["databaseId"], "conclusion": "failure"}
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="send one sample DM and record nothing")
    parser.add_argument("--dry-run", action="store_true", help="print instead of sending")
    parser.add_argument("--show", action="store_true", help="print what it knows and stop")
    args = parser.parse_args()

    if args.show:
        print(json.dumps({"state": load_state(),
                          "ci": latest_run(CI_WORKFLOW, BRANCH),
                          "nightly": latest_run(NIGHTLY_WORKFLOW, None)}, indent=2))
        return 0

    if args.test:
        text = ("Test of temper's CI watcher. From now on you get a message here when master's "
                "checks go red (with the jobs that failed), when they are green again, and when "
                "the nightly finds the newest libraries breaking temper or a test that does not "
                "agree with itself. Each is sent once, when it changes. Nothing is wrong now.")
        if args.dry_run:
            print(text)
            return 0
        print("sent" if tell_owner(text) else "not sent")
        return 0

    def send(text: str) -> bool:
        if args.dry_run:
            print(text + "\n" + "-" * 60)
            return False                  # nothing recorded on a dry run
        return tell_owner(text)

    state = load_state()
    state = check_ci(state, send)
    state = check_nightly(state, send)
    if not args.dry_run:
        save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
