"""The machine check: one commit in, a ``temper/boxes`` status out.

Why a plain user service and not a GitHub runner: temper-ai is a public
repository, so a stranger's pull request can propose a workflow file, and
anything self-hosted would then be a stranger's code on the owner's
machine. So GitHub never starts anything here. This service watches from
the inside, and only ever runs commits that are *on a branch of the
repository itself* and were pushed by someone on the allow-list. A fork's
pull request is never a branch here, so it never gets this far.

What a check is:

* docs-only commit → passes at once, nothing is started;
* a tree we have already passed (a rebase that changed no file, a revert
  back to a known-good tree) → passes at once, borrowing that result;
* otherwise → a throwaway temper of that exact commit, the smoke set, a
  report, and the result posted on the commit.

One at a time, by a lock file: two throwaway stacks at once would fight
over docker and make both slower than doing them in turn.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from . import paths, report, smoke, stack
from .paths import CONTEXT, GATE_STATE, LOCK, log, read_json, sh, stamp, write_json
from .stack import Box

POLL_SECONDS = int(os.environ.get("TEMPER_CI_POLL", "25"))
QUEUE = paths.STATE / "queue"


# -- what we remember --------------------------------------------------------

def state() -> dict:
    return read_json(GATE_STATE, {}) or {}


def save(data: dict) -> None:
    write_json(GATE_STATE, data)


def result_for(sha: str) -> dict | None:
    return (state().get("commits") or {}).get(sha)


def passed_trees() -> dict[str, str]:
    """tree sha → the commit that first passed with it."""
    return state().get("trees") or {}


def remember(sha: str, verdict: dict) -> None:
    data = state()
    commits = data.setdefault("commits", {})
    commits[sha] = {k: verdict.get(k) for k in
                    ("ok", "reason", "report", "finished_at", "seconds", "branch", "subject", "skipped")}
    # Keep the last 200; the report folders stay either way.
    if len(commits) > 200:
        for old in sorted(commits, key=lambda s: commits[s].get("finished_at") or "")[:-200]:
            commits.pop(old, None)
    if verdict.get("ok") and verdict.get("tree"):
        data.setdefault("trees", {}).setdefault(verdict["tree"], sha)
    data["last"] = {"sha": sha, "ok": verdict.get("ok"), "at": stamp()}
    save(data)


# -- the queue ---------------------------------------------------------------

def ask_for(sha: str, branch: str = "", why: str = "") -> None:
    """Put a commit in the queue. `wt land` calls this the moment it pushes,
    so landing never waits on GitHub's event feed catching up."""
    QUEUE.mkdir(parents=True, exist_ok=True)
    (QUEUE / f"{sha}.json").write_text(
        json.dumps({"sha": sha, "branch": branch, "why": why, "asked_at": stamp()}), encoding="utf-8")


def queued() -> list[dict]:
    if not QUEUE.exists():
        return []
    rows = []
    for f in sorted(QUEUE.glob("*.json"), key=lambda p: p.stat().st_mtime):
        row = read_json(f)
        if row:
            row["_file"] = str(f)
            rows.append(row)
    return rows


@contextmanager
def one_at_a_time(wait: bool = True):
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = LOCK.open("w")
    try:
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not wait:
                    raise
                time.sleep(3)
        fh.write(f"{os.getpid()} {stamp()}\n")
        fh.flush()
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


# -- GitHub ------------------------------------------------------------------

def gh(*args: str, timeout: int = 60):
    """`gh` with the login the owner already has. No new key, no new secret."""
    return sh("gh", *args, timeout=timeout)


def post_status(sha: str, status: str, description: str, target: str = "") -> bool:
    """Put ``temper/boxes`` on the commit. This is what branch protection waits for."""
    args = ["api", f"repos/{paths.GH_REPO}/statuses/{sha}", "-X", "POST",
            "-f", f"state={status}", "-f", f"context={CONTEXT}",
            "-f", f"description={description[:139]}"]
    if target:
        args += ["-f", f"target_url={target}"]
    r = gh(*args)
    if r.returncode:
        log(f"could not post {CONTEXT}={status} on {sha[:12]}: {r.stderr.strip()[:300]}")
    return r.returncode == 0


def watching_since() -> str:
    """The moment this gate started watching. Nothing older is its business.

    GitHub's event feed hands back the last hundred pushes, which on a first
    start is a pile of history \u2014 commits from before this gate existed, which
    have no docker-compose.ci.yml and could not be checked even in principle.
    Judging them is wrong twice over: it puts red crosses on commits nobody is
    landing, and it spends ten minutes each finding out what was never in
    doubt. So the first pass writes down the time and checks nothing; from
    then on, only what is pushed after that.
    """
    data = state()
    since = data.get("watching_since")
    if not since:
        # GitHub's own shape, so comparing them is comparing like with like:
        # "2026-09-29T23:29:19Z", not the "+00:00" the rest of this file writes.
        since = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        data["watching_since"] = since
        save(data)
        log(f"first pass: watching for pushes from {since} onwards, and leaving history alone")
    return str(since)


def our_pushes() -> list[dict]:
    """Pushes to branches of this repository, by people on the list, since we started."""
    since = watching_since()
    r = gh("api", f"repos/{paths.GH_REPO}/events?per_page=100")
    if r.returncode:
        log(f"could not read the repository's events: {r.stderr.strip()[:200]}")
        return []
    try:
        events = json.loads(r.stdout)
    except ValueError:
        return []
    out = []
    for e in events:
        if e.get("type") != "PushEvent":
            continue
        who = (e.get("actor") or {}).get("login") or ""
        if who not in paths.ALLOWED_PUSHERS:
            continue
        # GitHub stamps every event; anything from before we started is history.
        when = str(e.get("created_at") or "")
        if when and when < since:
            continue
        payload = e.get("payload") or {}
        ref = str(payload.get("ref") or "")
        head = str(payload.get("head") or "")
        if not head or not ref.startswith("refs/heads/"):
            continue
        out.append({"sha": head, "branch": ref.removeprefix("refs/heads/"), "who": who,
                    "when": when})
    return out


def already_posted(sha: str) -> str:
    """What ``temper/boxes`` currently says on this commit, if anything."""
    r = gh("api", f"repos/{paths.GH_REPO}/commits/{sha}/status")
    if r.returncode:
        return ""
    try:
        for s in json.loads(r.stdout).get("statuses", []):
            if s.get("context") == CONTEXT:
                return str(s.get("state") or "")
    except ValueError:
        pass
    return ""


# -- the check itself --------------------------------------------------------

def check(sha: str, branch: str = "", post: bool = True) -> dict:
    """Run the machine check on one commit and come back with the verdict."""
    started = time.time()
    stack.fetch()
    if not stack.has_commit(sha):
        verdict = {"sha": sha, "ok": False, "reason": f"this machine has no commit {sha[:12]}",
                   "checks": [], "finished_at": stamp(), "seconds": 0}
        if post:
            post_status(sha, "error", verdict["reason"])
        return verdict

    subject = sh("git", "-C", str(stack.mirror()), "log", "-1", "--format=%s", sha).stdout.strip()
    files = stack.changed_files(sha)
    tree = stack.tree_sha(sha)
    verdict: dict = {"sha": sha, "branch": branch, "subject": subject, "tree": tree,
                     "files": len(files), "checks": [], "ok": False}

    if post:
        post_status(sha, "pending", "checking it in a throwaway temper", report.url(sha))

    # -- the two ways a commit passes without a stack ------------------------
    shortcut = ""
    if stack.docs_only(files):
        shortcut = ("Only writing changed, so nothing a run reads is different: "
                    f"{', '.join(files[:6])}{' …' if len(files) > 6 else ''}.")
    else:
        seen = passed_trees().get(tree)
        if seen and seen != sha:
            shortcut = (f"Every file here is exactly as in {seen[:12]}, which already passed, "
                        "so the same stack would run the same code.")
    if shortcut:
        verdict.update({"ok": True, "skipped": shortcut, "seconds": time.time() - started,
                        "finished_at": stamp(), "reason": ""})
        verdict["report"] = report.url(sha)
        report.write(sha, verdict)
        remember(sha, verdict)
        if post:
            post_status(sha, "success", shortcut[:139], report.url(sha))
        log(f"{sha[:12]}: passed at once — {shortcut}")
        return verdict

    # -- the real thing ------------------------------------------------------
    before = stack.live_fingerprint()
    box = Box(sha)
    try:
        with box:
            verdict["project"] = box.project
            verdict["ports"] = (f"server {box.server_port}, postgres {box.postgres_port}, "
                                f"redis {box.redis_port}")
            verdict["built"] = box.built
            verdict["image_inputs_changed"] = stack.touches_image(files)
            results = smoke.run_all(box, report.folder(sha))
            verdict["checks"] = [asdict(r) for r in results]
            failed = [r for r in results if not r.ok]
            verdict["ok"] = not failed
            verdict["reason"] = "" if not failed else (
                f"{len(failed)} of {len(results)} failed: " +
                "; ".join(f"{r.name} — {r.detail[:120]}" for r in failed))
    except Exception as exc:  # noqa: BLE001 - a stack that will not start is a failure
        verdict["ok"] = False
        verdict["reason"] = f"the throwaway temper could not be used: {exc}"
        log(f"{sha[:12]}: {verdict['reason']}")

    after = stack.live_fingerprint()
    leaked = stack.live_saw_box_runs(box.project)
    if before != after:
        verdict["isolation"] = f"CHANGED, which must never happen: {before} → {after}"
    elif leaked:
        verdict["isolation"] = f"the box reached the live temper: {leaked}"
    else:
        verdict["isolation"] = ("untouched — the live containers are the same ones, started at the "
                                "same moment, on the same volumes, and nothing the box ran is in "
                                "the live database")
    if before != after or leaked:
        verdict["ok"] = False
        verdict["reason"] = ((verdict.get("reason") or "") +
                             " The box did not keep to itself; that is a failure by itself.")

    verdict["seconds"] = time.time() - started
    verdict["finished_at"] = stamp()
    verdict["report"] = report.url(sha)
    report.write(sha, verdict)
    remember(sha, verdict)
    if post:
        post_status(sha, "success" if verdict["ok"] else "failure",
                    "the smoke set passed in a throwaway temper" if verdict["ok"]
                    else verdict["reason"], report.url(sha))
    log(f"{sha[:12]}: {'passed' if verdict['ok'] else 'FAILED'} in {verdict['seconds']:.0f}s")
    return verdict


def check_if_new(sha: str, branch: str = "", force: bool = False) -> dict | None:
    """Check a commit unless we already know about it."""
    if not force:
        known = result_for(sha)
        if known:
            return None
        if already_posted(sha) in ("success", "failure", "error"):
            return None
    with one_at_a_time():
        return check(sha, branch)


# -- the loop ----------------------------------------------------------------

def once() -> int:
    """One pass: whatever was asked for, then whatever GitHub shows. Returns how many ran."""
    ran = 0
    for row in queued():
        f = Path(row.pop("_file"))
        try:
            if check_if_new(row["sha"], row.get("branch") or "") is not None:
                ran += 1
        finally:
            f.unlink(missing_ok=True)
    for push in our_pushes():
        if check_if_new(push["sha"], push["branch"]) is not None:
            ran += 1
    return ran


def watch() -> int:
    paths.ensure_dirs()
    log(f"watching {paths.GH_REPO} for pushes by {', '.join(paths.ALLOWED_PUSHERS)}")
    while True:
        try:
            once()
        except Exception as exc:  # noqa: BLE001 - the watcher must outlive one bad pass
            log(f"the pass had a problem (carrying on): {type(exc).__name__}: {exc}")
        time.sleep(POLL_SECONDS)


def watch_with_deploys() -> int:
    """The service: check what is pushed, and take what lands on master live.

    One loop for both on purpose. A deploy asks temper-deploy to restart and
    then waits for it, and while it waits nothing else here should be
    starting a throwaway stack that would make that restart wait longer.
    """
    from . import deploy as deploy_mod

    paths.ensure_dirs()
    log(f"watching {paths.GH_REPO} for pushes by {', '.join(paths.ALLOWED_PUSHERS)}, "
        "and master for things to take live")
    while True:
        try:
            once()
        except Exception as exc:  # noqa: BLE001
            log(f"the checking pass had a problem (carrying on): {type(exc).__name__}: {exc}")
        try:
            deploy_mod.watch_master()
        except Exception as exc:  # noqa: BLE001
            log(f"the deploy pass had a problem (carrying on): {type(exc).__name__}: {exc}")
        time.sleep(POLL_SECONDS)
