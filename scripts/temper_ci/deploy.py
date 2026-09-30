"""What happens after master moves: it goes live, or it goes back.

The ordinary path is short. master moved, so ask ``temper-deploy restart``
for a restart; it already waits until no run is going, and several lands
that arrive together join one restart. When it has restarted, look at the
live temper for real: its own check, its hooks, one free run in a box, and
the dashboard.

The unhappy path is the point of all this. If the live check fails, master
does not move backwards — a revert commit goes on top, through the same
gate as everything else. That revert's files are exactly those of the last
commit that was live and well, so the machine check passes it at once
instead of spending ten minutes proving the same tree twice. Then temper
restarts onto it, and the owner gets a DM saying what failed and what was
taken back out.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import time
from pathlib import Path

from . import gate, paths, report
from .paths import DEPLOY_STATE, MAIN_REPO, log, read_json, sh, stamp, write_json

DEPLOY_DIR = Path.home() / ".local/state/temper-deploy"
# temper-deploy's own record of the last restart it did: whose, when, and how the checks went.
# temper-ci reads it rather than keeping a second account of the same thing.
LAST_RESTART = Path.home() / ".local/state/temper-deploy/last-restart.json"
TEMPER_DEPLOY = Path.home() / ".local/bin/temper-deploy"
LIVE_PORT_DEFAULT = 8420            # what docker-compose.yml publishes
RESTART_PATIENCE = 60 * 60          # an hour: a long run may be going
LIVE_CHECK_RUNS = "smoke_test"      # $0, script agents only


def live_api() -> str:
    """Where the live temper actually is \u2014 asked, not assumed.

    This was hard-coded to port 8000 and the live server is on 8420, so every
    part of the live check that spoke to the API failed, on every deploy,
    whatever the deploy had done. A check that always says no would have
    reverted good code for ever \u2014 the most expensive kind of wrong, because it
    looks like caution.

    So ask docker what the live server publishes, and keep the compose file's
    port only as the answer when there is nothing to ask.
    """
    r = sh("docker", "port", "temper-ai-server-1", "8420/tcp", timeout=30)
    if r.returncode == 0 and r.stdout.strip():
        # "127.0.0.1:8420" \u2014 possibly several lines, one per family.
        first = r.stdout.strip().splitlines()[0].strip()
        port = first.rsplit(":", 1)[-1]
        if port.isdigit():
            return f"http://127.0.0.1:{port}"
    return f"http://127.0.0.1:{LIVE_PORT_DEFAULT}"


def state() -> dict:
    return read_json(DEPLOY_STATE, {}) or {}


def save(data: dict) -> None:
    write_json(DEPLOY_STATE, data)


def master_sha() -> str:
    return sh("git", "-C", str(MAIN_REPO), "rev-parse", "refs/heads/master").stdout.strip()


# -- the live look -----------------------------------------------------------

def _temper_deploy(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return sh("python3", str(TEMPER_DEPLOY), *args, timeout=timeout)


def live_check(shots: Path) -> dict:
    """Four questions of the temper that is actually serving people."""
    out: dict = {"at": stamp(), "parts": [], "ok": True, "shots": []}

    def part(name: str, ok: bool, detail: str) -> None:
        out["parts"].append({"name": name, "ok": ok, "detail": detail[:600]})
        if not ok:
            out["ok"] = False

    r = _temper_deploy("check")
    part("temper-deploy check", r.returncode == 0, (r.stdout or r.stderr).strip())

    r = _temper_deploy("hooks")
    part("temper-deploy hooks", r.returncode == 0, (r.stdout or r.stderr).strip())

    api = live_api()
    out["api"] = api

    # One free run, in a box, on the live server — the same thing a person
    # would do first: does it still run anything at all?
    run_id = ""
    try:
        import urllib.request
        req = urllib.request.Request(  # noqa: S310 - loopback
            f"{api}/api/runs", method="POST",
            data=json.dumps({"workflow": LIVE_CHECK_RUNS,
                             "inputs": {"message": "after the deploy"}}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            run_id = json.loads(resp.read()).get("execution_id") or ""
        status, deadline = "", time.time() + 240
        while time.time() < deadline:
            with urllib.request.urlopen(f"{api}/api/workflows/{run_id}", timeout=20) as resp:  # noqa: S310
                status = json.loads(resp.read()).get("status") or ""
            if status in ("completed", "failed", "cancelled", "error"):
                break
            time.sleep(3)
        part("a free run on the live temper", status == "completed",
             f"{LIVE_CHECK_RUNS} {run_id[:8]} ended as {status or 'unknown'} (at {api})")
    except Exception as exc:  # noqa: BLE001
        part("a free run on the live temper", False, f"{type(exc).__name__}: {exc} (at {api})")

    # The dashboard lives under /app — its router's basename. The API's own root is a 404
    # by design, and photographing that was once counted as the page being fine.
    shots.mkdir(parents=True, exist_ok=True)
    target = shots / "live-dashboard.png"
    args = ["python3", str(Path(__file__).with_name("shot.py")), f"{api}/app/", str(target),
            "--expect", LIVE_CHECK_RUNS]
    r = sh(*args, timeout=180)
    took = target.exists()
    if took:
        out["shots"].append(str(target))
    part("the dashboard", r.returncode == 0 and took,
         "it showed the workflow list" if r.returncode == 0
         else ((r.stdout or "").strip().splitlines()[-1:] or [(r.stderr or "").strip()])[0][:300])
    return out


# -- restarting --------------------------------------------------------------

def ask_restart(sha: str, why: str) -> None:
    """Ask for a restart and say which commit has to be live after it.

    `--commit` is temper-deploy's own check that the restart really carried
    this change: it refuses if the checkout is not that commit or newer.
    """
    r = _temper_deploy("restart", "--reason", why, "--commit", sha, timeout=120)
    log(f"asked temper-deploy to restart for {sha[:12]}: {(r.stdout or r.stderr).strip()[:200]}")


def restart_done_after(when: dt.datetime, sha: str = "") -> dict | None:
    """The restart record, once temper is on the commit we asked for.

    A record newer than ``when`` means our own restart happened. An older one
    is normally just the file lying around from last time, and reading it as
    "the restart happened" would skip straight to checking a temper that never
    came back -- which is why this is strict.

    But there is one older record that answers the question honestly: the one
    that already says temper is live on ``sha``. Then there is nothing to
    restart, temper-deploy rightly does nothing, and no new record will ever
    be written. Waiting for one waits the whole hour, and because the watcher
    is a single loop it stops checking pushed commits the entire time -- that
    is how a queued commit sat for half an hour behind "checking: nothing
    right now".
    """
    row = read_json(LAST_RESTART)
    if not row:
        return None
    try:
        at = dt.datetime.fromisoformat(str(row.get("at")))
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=dt.UTC)
    if at > when:
        return row
    head = str(row.get("head") or "").strip()
    if sha and head and sha.startswith(head):
        return row
    return None


def wait_for_restart(since: dt.datetime, sha: str = "",
                     patience: int = RESTART_PATIENCE) -> dict | None:
    deadline = time.time() + patience
    while time.time() < deadline:
        row = restart_done_after(since, sha)
        if row:
            return row
        time.sleep(10)
    return None


# -- going back --------------------------------------------------------------

def revert_to(good: str, bad: str, reason: str) -> dict:
    """Put a revert commit on master, through the gate, and restart onto it.

    A revert, never a reset: master only ever moves forwards, so anyone who
    already pulled the bad commit gets the fix by pulling again, and the
    history says plainly what happened and why.
    """
    out: dict = {"at": stamp(), "good": good, "bad": bad, "reason": reason, "ok": False}
    work = paths.STATE / "revert"
    # A revert that was killed half way \u2014 the machine rebooted, the service was
    # restarted \u2014 leaves this worktree and its branch behind, and git then
    # refuses to make them again. That would mean no rollback at all on the
    # next bad deploy, which is the one moment it has to work. So clear both
    # first, every time.
    sh("rm", "-rf", str(work), timeout=60)
    sh("git", "-C", str(MAIN_REPO), "worktree", "prune", timeout=60)
    sh("git", "-C", str(MAIN_REPO), "branch", "-q", "-D", f"revert-{bad[:8]}", timeout=60)
    r = sh("git", "-C", str(MAIN_REPO), "worktree", "add", "--quiet", "-b",
           f"revert-{bad[:8]}", str(work), "master", timeout=300)
    if r.returncode:
        out["detail"] = f"could not make a worktree to revert in: {r.stderr.strip()}"
        return out
    try:
        # The tree of the last good commit, as a new commit on top of master.
        if sh("git", "-C", str(work), "read-tree", "-u", "--reset", good, timeout=120).returncode:
            out["detail"] = f"could not take {good[:12]}'s files"
            return out
        message = (f"Revert to {good[:12]}: the live check failed after {bad[:12]}\n\n"
                   f"{reason}\n\n"
                   "Put in by temper-ci. The files here are exactly those of "
                   f"{good[:12]}, which was live and well, so the machine check "
                   "recognises the tree and passes it at once.")
        c = sh("git", "-C", str(work), "commit", "-q", "-a", "-m", message, timeout=120)
        if c.returncode and "nothing to commit" not in (c.stdout + c.stderr):
            out["detail"] = f"could not make the revert commit: {(c.stderr or c.stdout).strip()}"
            return out
        sha = sh("git", "-C", str(work), "rev-parse", "HEAD").stdout.strip()
        out["revert"] = sha

        # Through the same gate as everything else.
        gate.ask_for(sha, "master", f"revert of {bad[:12]}")
        verdict = gate.check(sha, "master")
        out["gate_ok"] = bool(verdict.get("ok"))
        if not verdict.get("ok"):
            out["detail"] = f"the revert itself did not pass the gate: {verdict.get('reason')}"
            return out
        ff = sh("git", "-C", str(MAIN_REPO), "merge", "-q", "--ff-only", sha, timeout=120)
        if ff.returncode:
            out["detail"] = f"could not move master onto the revert: {ff.stderr.strip()}"
            return out
        push = sh("git", "-C", str(MAIN_REPO), "push", "-q", "origin", "master", timeout=300)
        out["pushed"] = push.returncode == 0
        ask_restart(sha, f"temper-ci: reverting {bad[:12]} after its live check failed")
        out["ok"] = True
        return out
    finally:
        sh("git", "-C", str(MAIN_REPO), "worktree", "remove", "--force", str(work), timeout=120)
        sh("git", "-C", str(MAIN_REPO), "branch", "-q", "-D", f"revert-{bad[:8]}", timeout=60)


def dm(text: str) -> None:
    """Reuse temper-deploy's own DM, so there is one bot and one place it comes from."""
    script = (f"import importlib.machinery, importlib.util, sys\n"
              f"loader = importlib.machinery.SourceFileLoader('td', {str(TEMPER_DEPLOY)!r})\n"
              "spec = importlib.util.spec_from_loader('td', loader)\n"
              "m = importlib.util.module_from_spec(spec)\n"
              "loader.exec_module(m)\n"
              "m.tell_owner(sys.argv[1])\n")
    r = sh("python3", "-c", script, text, timeout=60)
    if r.returncode:
        log(f"could not DM the owner: {(r.stderr or r.stdout).strip()[:300]}")


# -- the whole thing ---------------------------------------------------------

def can_be_gone_back_to(sha: str) -> bool:
    """Is this a commit the gate itself has passed?

    Going back to a commit from before the gate existed cannot work: its files
    have no ``docker-compose.ci.yml``, so the throwaway temper cannot be built
    from it, so the revert fails its own gate and master never moves. The
    machine then tries again on the next failure and leaves a trail of revert
    commits nobody can land \u2014 which is what happened here, twice, before this
    check existed.

    A commit is somewhere to go back to only if the box check has been run on
    it and passed. Anything else is a guess, and a guess is worse than saying
    plainly that there is nowhere to go and letting the owner decide.
    """
    if not sha:
        return False
    verdict = gate.result_for(sha)
    return bool(verdict and verdict.get("ok"))


def deploy(sha: str) -> dict:
    """master is at ``sha``: get it live, and make sure it is well."""
    data = state()
    good = data.get("last_good") or ""
    if good and not can_be_gone_back_to(good):
        log(f"{good[:12]} was on record as the good one, but the gate never passed it; "
            "treating it as nowhere to go back to")
        good = ""
    asked_at = dt.datetime.now(dt.UTC)
    ask_restart(sha, f"temper-ci: {sha[:12]} landed on master")
    row = wait_for_restart(asked_at, sha)
    out: dict = {"sha": sha, "asked_at": asked_at.isoformat(), "restarted": bool(row)}
    if not row:
        out["reason"] = "temper never restarted; nothing was rolled back, because nothing went live"
        log(f"{sha[:12]}: {out['reason']}")
        data["last_deploy"] = out
        save(data)
        return out

    shots = report.folder(sha) / "live"
    live = live_check(shots)
    out["live"] = live
    out["ok"] = bool(live.get("ok"))
    data["last_deploy"] = out
    if out["ok"]:
        data["last_good"] = sha
        data["deployed"] = sha
        data["revert_outstanding"] = ""
        save(data)
        log(f"{sha[:12]}: live and well")
        return out

    bad_parts = "; ".join(p["name"] for p in live["parts"] if not p["ok"])
    log(f"{sha[:12]}: the live check failed ({bad_parts})")
    save(data)
    if not good or good == sha:
        dm(f"temper: the live check failed after {sha[:12]} ({bad_parts}), and there is no "
           "earlier commit the gate has passed to go back to. Temper is up but unwell \u2014 "
           f"`temper-deploy status`, report: {report.url(sha)}")
        out["rolled_back"] = False
        return out

    # One revert, then hands off. If the last thing this did was revert and that
    # did not put things right, a second revert is the machine arguing with
    # itself on master while the owner is not looking.
    if data.get("revert_outstanding"):
        dm(f"temper: the live check failed again after {sha[:12]} ({bad_parts}), and a revert "
           f"({str(data['revert_outstanding'])[:12]}) is already outstanding. Stopping here \u2014 "
           f"this needs a person. `temper-ci status`, report: {report.url(sha)}")
        out["rolled_back"] = False
        out["reason"] = "a revert was already outstanding"
        return out

    back = revert_to(good, sha, f"the live check failed: {bad_parts}")
    out["rollback"] = back
    data = state()
    data["last_deploy"] = out
    data["deployed"] = back.get("revert") or sha
    # Cleared once a deploy is well again; until then, no second revert.
    data["revert_outstanding"] = "" if back.get("ok") else (back.get("revert") or sha)
    save(data)
    subjects = sh("git", "-C", str(MAIN_REPO), "log", "--format=%h %s", f"{good}..{sha}").stdout.strip()
    dm("temper: the live check failed after the last land, so master has been put back.\n"
       f"• what failed: {bad_parts}\n"
       f"• taken back out:\n{subjects or f'  {sha[:12]}'}\n"
       f"• master is now the files of {good[:12]}"
       f"{' (revert ' + back['revert'][:12] + ')' if back.get('revert') else ''}\n"
       f"• temper is restarting onto it{'' if back.get('ok') else ' — THE REVERT ITSELF DID NOT GO THROUGH: ' + str(back.get('detail'))}\n"
       f"• report: {report.url(sha)}")
    return out


def watch_master() -> dict | None:
    """Called from the watcher's loop: has master moved since we last deployed?"""
    data = state()
    sha = master_sha()
    if not sha or data.get("deployed") == sha:
        return None
    if not data.get("last_good"):
        # First time: what is live now is where we would go back to \u2014 but only if
        # the gate has passed it. On the day the gate is installed master is a
        # commit from before it existed, and going back to that is impossible
        # (no docker-compose.ci.yml in its files), so record nothing and let the
        # first commit that passes become the one to go back to.
        data["deployed"] = sha
        if can_be_gone_back_to(sha):
            data["last_good"] = sha
            log(f"first look: master is {sha[:12]}, and the gate has passed it, so that is "
                "where we would go back to")
        else:
            log(f"first look: master is {sha[:12]}, which the gate never checked; there is "
                "nowhere to go back to until a commit passes")
        save(data)
        return None
    return deploy(sha)
