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
LAST_RESTART = DEPLOY_DIR / "last-restart.json"
TEMPER_DEPLOY = Path.home() / ".local/bin/temper-deploy"
LIVE_API = "http://127.0.0.1:8000"
RESTART_PATIENCE = 60 * 60          # an hour: a long run may be going
LIVE_CHECK_RUNS = "smoke_test"      # $0, script agents only


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

    # One free run, in a box, on the live server — the same thing a person
    # would do first: does it still run anything at all?
    try:
        import urllib.request
        req = urllib.request.Request(  # noqa: S310 - loopback
            f"{LIVE_API}/api/runs", method="POST",
            data=json.dumps({"workflow": LIVE_CHECK_RUNS, "inputs": {"message": "after the deploy"}}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            run_id = json.loads(resp.read()).get("execution_id") or ""
        status, deadline = "", time.time() + 240
        while time.time() < deadline:
            with urllib.request.urlopen(f"{LIVE_API}/api/workflows/{run_id}", timeout=20) as resp:  # noqa: S310
                status = json.loads(resp.read()).get("status") or ""
            if status in ("completed", "failed", "cancelled", "error"):
                break
            time.sleep(3)
        part("a free run on the live temper", status == "completed",
             f"{LIVE_CHECK_RUNS} {run_id[:8]} ended as {status or 'unknown'}")
    except Exception as exc:  # noqa: BLE001
        part("a free run on the live temper", False, f"{type(exc).__name__}: {exc}")

    shots.mkdir(parents=True, exist_ok=True)
    target = shots / "live-dashboard.png"
    r = sh("python3", str(Path(__file__).with_name("shot.py")), LIVE_API + "/", str(target), timeout=180)
    took = r.returncode == 0 and target.exists()
    if took:
        out["shots"].append(str(target))
    part("the dashboard", took, "photographed" if took else (r.stderr or r.stdout).strip()[:300])
    return out


# -- restarting --------------------------------------------------------------

def ask_restart(sha: str, why: str) -> None:
    r = _temper_deploy("restart", "--reason", why, sha, timeout=120)
    log(f"asked temper-deploy to restart for {sha[:12]}: {(r.stdout or r.stderr).strip()[:200]}")


def restart_done_after(when: dt.datetime) -> dict | None:
    """The restart record, once there is one newer than ``when``."""
    row = read_json(LAST_RESTART)
    if not row:
        return None
    try:
        at = dt.datetime.fromisoformat(str(row.get("at")))
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=dt.UTC)
    return row if at > when else None


def wait_for_restart(since: dt.datetime, patience: int = RESTART_PATIENCE) -> dict | None:
    deadline = time.time() + patience
    while time.time() < deadline:
        row = restart_done_after(since)
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
    sh("rm", "-rf", str(work), timeout=60)
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

def deploy(sha: str) -> dict:
    """master is at ``sha``: get it live, and make sure it is well."""
    data = state()
    good = data.get("last_good") or ""
    asked_at = dt.datetime.now(dt.UTC)
    ask_restart(sha, f"temper-ci: {sha[:12]} landed on master")
    row = wait_for_restart(asked_at)
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
        save(data)
        log(f"{sha[:12]}: live and well")
        return out

    bad_parts = "; ".join(p["name"] for p in live["parts"] if not p["ok"])
    log(f"{sha[:12]}: the live check failed ({bad_parts})")
    save(data)
    if not good or good == sha:
        dm(f"temper: the live check failed after {sha[:12]} ({bad_parts}), and there is no "
           "earlier good commit on record to go back to. Temper is up but unwell — "
           f"`temper-deploy status`, report: {report.url(sha)}")
        out["rolled_back"] = False
        return out

    back = revert_to(good, sha, f"the live check failed: {bad_parts}")
    out["rollback"] = back
    data = state()
    data["last_deploy"] = out
    data["deployed"] = back.get("revert") or sha
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
        # First time: whatever is live now is the thing we would go back to.
        data["last_good"] = sha
        data["deployed"] = sha
        save(data)
        log(f"first look: master is {sha[:12]}, and that is the good one to go back to")
        return None
    return deploy(sha)
