"""The machine check: one commit in, a ``temper/boxes`` status out.

Why a plain user service and not a GitHub runner: temper-ai is a public
repository, so a stranger's pull request can propose a workflow file, and
anything self-hosted would then be a stranger's code on the owner's
machine. So GitHub never starts anything here. This service watches from
the inside, and only ever looks at commits that are *on a branch of the
repository itself* and were pushed by someone on the allow-list. A fork's
pull request is never a branch here, so it never gets this far.

What a check is, since 2026-10-08: the commit is fetched, its tree is
written down, and ``temper/boxes`` is posted as passed. Nothing is built
and no temper is started. There is one temper only, the live one
(temper-dev): no test copies of it, and the throwaway temper this check
used to build for every commit was one.

The status keeps its name because master's protection and ``wt land`` wait
for it, and because the deploy's way back reads what is written down here:
the last good commit is one this gate recorded, and a revert comes through
here too. What stands in front of master is GitHub's lint, types and tests;
what looks at the code once it runs is the deploy's live check on the live
temper, which reverts a commit that fails it (deploy.py).

One at a time, by a lock file, so two looks at one commit never write over
each other's record.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from . import paths, report, stack
from .paths import CONTEXT, GATE_STATE, LOCK, log, read_json, sh, stamp, write_json

POLL_SECONDS = int(os.environ.get("TEMPER_CI_POLL", "25"))
QUEUE = paths.STATE / "queue"

# What the status (GitHub cuts a description at 140) and the report say about every commit.
PASSED_SHORT = ("recorded; no test temper (one live temper only): GitHub's checks gate it, "
                "the live check follows the deploy")
PASSED_WHY = ("Nothing was built: since 2026-10-08 there is one temper only, the live one, and "
              "no test copies of it. GitHub's lint, types and tests stand in front of master; "
              "once this lands, the deploy's live check looks at the live temper and reverts "
              "it if that fails.")


# -- what we remember --------------------------------------------------------

def state() -> dict:
    return read_json(GATE_STATE, {}) or {}


def save(data: dict) -> None:
    write_json(GATE_STATE, data)


def result_for(sha: str) -> dict | None:
    return (state().get("commits") or {}).get(sha)


def remember(sha: str, verdict: dict) -> None:
    data = state()
    commits = data.setdefault("commits", {})
    commits[sha] = {k: verdict.get(k) for k in
                    ("ok", "reason", "report", "finished_at", "seconds", "branch", "subject", "skipped")}
    # Keep the last 200; the report folders stay either way.
    if len(commits) > 200:
        for old in sorted(commits, key=lambda s: commits[s].get("finished_at") or "")[:-200]:
            commits.pop(old, None)
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


def only_we_can_push() -> bool:
    """Is write access to this repository still just the people on the list?

    This is what makes looking at branch heads safe. A branch under
    ``refs/heads/`` in the repository itself can only be put there by someone
    with write access \u2014 a fork's branches and a stranger's pull request are
    never in that list. So if write access is exactly the people we already
    trust, every branch head is by definition one of their pushes.

    If someone new is given write access, that reasoning stops holding, and
    this machine would start building and running their code. So it is asked
    every pass, and the answer is loud when it changes.
    """
    r = gh("api", f"repos/{paths.GH_REPO}/collaborators?per_page=100")
    if r.returncode:
        log(f"could not read who can push: {r.stderr.strip()[:200]}")
        return False
    try:
        people = json.loads(r.stdout)
    except ValueError:
        return False
    writers = {p.get("login") for p in people if (p.get("permissions") or {}).get("push")}
    extra = writers - set(paths.ALLOWED_PUSHERS)
    if extra:
        log(f"someone else can push to {paths.GH_REPO} now ({', '.join(sorted(extra))}); "
            "not checking branch heads until they are on the list in paths.ALLOWED_PUSHERS")
        return False
    return True


def branch_heads() -> dict[str, str]:
    """Every branch of the repository itself, and what it points at \u2014 asked of git.

    Not GitHub's event feed. That feed is cached hard: a push can take many
    minutes to appear on it, and some never do. A gate that finds out about
    work late, or not at all, is a gate people learn to go round. ``ls-remote``
    asks the server what the refs are right now, and answers in a moment.

    Only ``refs/heads/*`` of this repository, which is the same trust boundary
    as before: no fork branches, no ``refs/pull/*``.
    """
    r = sh("git", "-C", str(paths.MAIN_REPO), "ls-remote", "--heads", "origin", timeout=120)
    if r.returncode:
        log(f"could not ask git for the branches: {(r.stderr or r.stdout).strip()[:200]}")
        return {}
    heads: dict[str, str] = {}
    for line in r.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        ref = ref.strip()
        if ref.startswith("refs/heads/") and len(sha.strip()) == 40:
            heads[ref.removeprefix("refs/heads/")] = sha.strip()
    return heads


def our_pushes() -> list[dict]:
    """Branch heads that have moved since the last look.

    The first look writes down where every branch is and checks nothing. On
    the day this is installed the repository has a dozen branches, all from
    before the gate existed; answering for them all at once would be
    answering for work nobody asked about.
    """
    if not only_we_can_push():
        return []
    heads = branch_heads()
    if not heads:
        return []

    data = state()
    seen = data.get("seen_heads")
    if not isinstance(seen, dict) or not seen:
        data["seen_heads"] = dict(heads)
        data.setdefault("watching_since", dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        save(data)
        log(f"first look: {len(heads)} branch(es) noted where they are; "
            "from now on, whatever moves gets checked")
        return []

    out = []
    for branch, sha in sorted(heads.items()):
        if seen.get(branch) == sha:
            continue
        out.append({"sha": sha, "branch": branch, "who": paths.ALLOWED_PUSHERS[0]})
        seen[branch] = sha
    # Branches that have gone away stop being our business.
    gone = [b for b in seen if b not in heads]
    for b in gone:
        seen.pop(b, None)
    if out or gone:
        data["seen_heads"] = seen
        save(data)
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
    """Record one commit and pass it: fetched, its tree written down, nothing built or started."""
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

    # Nothing is built and nothing is started: see the module's docstring.
    verdict.update({"ok": True, "skipped": PASSED_WHY, "reason": "",
                    "seconds": time.time() - started, "finished_at": stamp(),
                    "report": report.url(sha)})
    report.write(sha, verdict)
    remember(sha, verdict)
    if post:
        post_status(sha, "success", PASSED_SHORT, report.url(sha))
    log(f"{sha[:12]}: recorded and passed at once; nothing built (one live temper only)")
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


def own_code_fingerprint() -> str:
    """What this process's own code looks like on disk, right now."""
    here = Path(__file__).parent
    bits = []
    for f in sorted(here.glob("*.py")):
        try:
            bits.append(f"{f.name}:{f.stat().st_mtime_ns}:{f.stat().st_size}")
        except OSError:
            bits.append(f"{f.name}:gone")
    return "|".join(bits)


def restart_if_our_code_changed(known: str) -> str:
    """Start again if this gate's own code has been landed over.

    The gate lives in the repository it guards, so landing a fix *to the gate*
    leaves the running process still holding the old code \u2014 Python read it at
    start-up and will not read it again. That is how a fix to the live check
    got reverted by the very bug it fixed: the fix landed, the old code did
    the deploy, the old check failed as it always had, and the old rollback
    undid the fix.

    So before deciding anything about master, notice that the code on disk is
    no longer the code in memory, and start again from it. systemd puts the
    process back; anything in flight is safe, because a check that does not
    finish is simply not reported and gets picked up again.
    """
    now = own_code_fingerprint()
    if known and now != known:
        log("this gate's own code changed underneath it \u2014 starting again so the new code "
            "is what decides about master")
        os.execv(sys.executable, [sys.executable, *sys.argv])
    return now


def watch_with_deploys() -> int:
    """The service: check what is pushed, and take what lands on master live.

    One loop for both on purpose: a deploy that waits for its restart holds
    the next look at pushes, so the two never run over each other. A deploy
    held back while runs are going on the live temper returns at once
    (deploy.watch_master), so pushes are still answered meanwhile.
    """
    from . import deploy as deploy_mod

    paths.ensure_dirs()
    log(f"watching {paths.GH_REPO} for pushes by {', '.join(paths.ALLOWED_PUSHERS)}, "
        "and master for things to take live")
    mine = own_code_fingerprint()
    while True:
        try:
            once()
        except Exception as exc:  # noqa: BLE001
            log(f"the checking pass had a problem (carrying on): {type(exc).__name__}: {exc}")
        # Between checking and deploying: if a land has just replaced this very
        # code, the deploy must be decided by the new code, not by this process.
        mine = restart_if_our_code_changed(mine)
        try:
            deploy_mod.watch_master()
        except Exception as exc:  # noqa: BLE001
            log(f"the deploy pass had a problem (carrying on): {type(exc).__name__}: {exc}")
        time.sleep(POLL_SECONDS)
