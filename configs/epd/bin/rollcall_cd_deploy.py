#!/usr/bin/env python3
"""RollCall's continuous deployer: one job, decide when master goes live and run that deploy.

    rollcall_cd_deploy.py tick
        One decision, printed as one JSON line. temper's epd_cd workflow runs it every minute
        (configs/triggers/epd_cd.yaml). Exit 0 for every decision but `refused`.
    rollcall_cd_deploy.py deploy --sha S --kind deploy|undo --reason TEXT
        One release of S through epd_loop.deploy_prod (backup, up, migrate, health, its own undo),
        from the deploy checkout. What a tick starts, in a systemd unit of its own; the money-test
        undo (RollCall CD 2) calls it with --kind undo (deploy_prod's kind undo: the order guard lets
        it go back; --kind deploy is kind forward). Exit 0 when S is live and healthy (or was live
        already), 75 when another deploy or standee command held the lock, 76 when deploy_prod's
        order guard refused (the live commit is no ancestor of S; both: nothing changed), 1 otherwise.

The rule (owner, 2026-11-05, relayed by RollCall rm-ff184438): "after something lands deploy will
start on that commit ... while deploy is going more landing could happen and deploy can pick up
another that can include everything thats landed"; the wait, "2 minutes". So a tick deploys
origin/master's HEAD when all of these hold:

  * no deploy is running (deploy_running_unit is not alive);
  * HEAD is not what is live (deployed_sha) and not in undone_shas;
  * HEAD has not moved for QUIET (now >= last_seen_at + QUIET): a land inside the window restarts it;
  * the last deploy ended at least QUIET ago (now >= last_deploy_end_at + QUIET). Lands that came in
    during a deploy (or after it) go out together, as HEAD, in the next one. (When HEAD did not move
    during the last deploy, any newer HEAD was seen after it ended, so the first rule already implies
    this one.)

It deploys HEAD, never a land in between, so one deploy carries every land so far. It does not wait
for GitHub's CI: a land only reaches master once its land check has passed.

What stays the same for the live product: epd_loop.deploy_prod does the release (and tags it), and holds
the machine's one deploy lock, so epd_loop's own deploy after a bet merge and this one never overlap.
The live data comes by absolute path (EPD_PROD_HOME, rollcall's deploy/compose.live.yaml): the
standee env rollcall-prod, its container and port 8020, /home/shinelay/rollcall/var at /data and
/home/shinelay/rollcall/.env. Only the tree the images are built from moves to the deploy checkout:
CHECKOUT, a plain clone (not a wt worktree, so `wt gc` never touches it), detached at the sha being
released and clean. ~/rollcall is never checked out to another commit.

Shared with RollCall CD 2 (the money-test undo), kept exactly:
  STATE_DIR (0700)  state.json {deployed_sha, deploy_running_unit, last_seen_head, last_seen_at,
                               last_deploy_end_at, undone_shas: []}
                    deploys.jsonl, one JSON line per event {ts, kind: deploy|undo|refusal|skip, sha,
                               from_sha, reason, result, unit}
  undone_shas: commits this deployer will not release on its own again: undone by the money test,
  or whose release failed (deploy_prod undid it by itself) or ended without saying how, or that
  deploy_prod's order guard refused (result "out of order": the live commit is no ancestor of it;
  it would refuse again). A commit that is live already ends ok, nothing changed. A new land
  is a new HEAD and goes out as usual; `deploy --sha` releases one of them by hand, and a release
  that goes live takes its commit off the list.

Every deploy, undo, refusal and skip-with-reason is one line in deploys.jsonl and one fyi to RollCall
(rollcall_cd_notify.role). A deploy's start is logged too (result "started"), without a message.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import rollcall_cd_notify as notify

BIN = Path(__file__).resolve().parent
STATE_DIR = notify.STATE_DIR  # one directory for the deployer, the undo and their outbox
STATE_FILE = STATE_DIR / "state.json"
LOG_FILE = STATE_DIR / "deploys.jsonl"
STATE_LOCK = STATE_DIR / "state.lock"  # held briefly, around every read-modify-write of state.json
CHECKOUT_LOCK = STATE_DIR / "checkout.lock"  # held by the deploy that is using CHECKOUT's tree
CHECKOUT = Path(os.environ.get("ROLLCALL_CD_CHECKOUT", "/home/shinelay/rollcall-deploy"))
PROD_HOME = Path(os.environ.get("EPD_PROD_HOME", "/home/shinelay/rollcall"))
PROD_ENV = os.environ.get("EPD_PROD_ENV", "rollcall-prod")
REPO_URL = os.environ.get("EPD_REPO_URL", "git@github.com:shine2lay/rollcall.git")
BRANCH = os.environ.get("EPD_BASE_BRANCH", "master")
QUIET = dt.timedelta(seconds=int(os.environ.get("ROLLCALL_CD_QUIET_SECONDS", "120")))  # the owner's 2 minutes
NOTIFY_ROLE = "rollcall"
UNIT_PREFIX = "rollcall-cd-deploy-"
#: epd_loop.DEPLOY_BUSY: deploy_prod's exit code while another deploy holds the lock (checked by a test).
DEPLOY_BUSY = 75
#: epd_loop.DEPLOY_REFUSED: its order guard refused (the live commit is no ancestor of this one); nothing changed.
DEPLOY_REFUSED = 76
#: epd_loop.DEPLOY_ALREADY_LIVE: the commit asked for is the live one; nothing changed.
DEPLOY_ALREADY_LIVE = 77
KINDS = ("deploy", "undo")
#: This CLI's --kind -> epd_loop.deploy_prod's kind (forward: the order guard applies; undo: may go back).
RELEASE_KIND = {"deploy": "forward", "undo": "undo"}
SHA = re.compile(r"^[0-9a-f]{40}$")
STATE_DEFAULTS: dict = {"deployed_sha": None, "deploy_running_unit": None, "last_seen_head": None,
                        "last_seen_at": None, "last_deploy_end_at": None, "undone_shas": []}
# What a deploy unit is given from the caller's environment, by name (systemd-run copies each value,
# so none is on a command line): where things are, never a key.
FORWARD_ENV = ("PATH", "EPD_PROD_ENV", "EPD_PROD_CONTAINER", "EPD_PROD_URL", "EPD_PROD_HOST_PORT",
               "EPD_PROD_HOME", "EPD_PROD_ENV_FILE", "EPD_DEPLOY_LOCK", "EPD_REPO", "EPD_REPO_URL",
               "EPD_BASE_BRANCH", "EPD_WORKSPACES", "ROLLCALL_CD_STATE", "ROLLCALL_CD_CHECKOUT",
               "ROLLCALL_CD_QUIET_SECONDS", "ROLLCALL_CD_TELEGRAM_SENDER", "ROLLCALL_CD_TEMPER_ENV",
               "ROLLCALL_CD_TELEGRAM_CONFIG", "ROLLCALL_CD_PI_WEB_UI_DIR")


class CheckoutProblem(RuntimeError):
    """The deploy checkout is not a clean tree at the commit asked for: nothing was released."""


# ---------------------------------------------------------------- the outside world --
# Each of these is replaced by a fake in tests/test_epd/test_rollcall_cd_deploy.py.

def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def git(*args: str, cwd: Path | None = CHECKOUT) -> str:
    """Run git; its stdout, stripped. A failure is loud: CalledProcessError with git's own words."""
    r = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    if r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, ["git", *args], r.stdout, r.stderr)
    return r.stdout.strip()


def unit_running(unit: str) -> bool:
    """Whether the deploy named in deploy_running_unit is still going: a systemd unit, or pid:N."""
    if unit.startswith("pid:"):
        return Path(f"/proc/{unit[4:]}").exists()
    r = subprocess.run(["systemctl", "--user", "show", "--property=ActiveState", "--value", unit],
                       text=True, capture_output=True, env=_user_bus_env())
    if r.returncode != 0:
        raise RuntimeError(f"`systemctl --user show {unit}` exited {r.returncode}: {r.stderr.strip()}")
    return r.stdout.strip() in ("active", "activating", "deactivating", "reloading")


def launch(unit: str, sha: str, reason: str) -> None:
    """Start `deploy --sha` in a transient user unit of its own, detached from whoever ticked."""
    env = _user_bus_env()
    cmd = ["systemd-run", "--user", "--collect", "--quiet", f"--unit={unit}",
           f"--description=RollCall CD: release {sha[:8]}", "--property=UMask=0022",
           f"--property=WorkingDirectory={CHECKOUT}", "--expand-environment=no",
           f"--setenv=ROLLCALL_CD_UNIT={unit}"]
    cmd += [f"--setenv={name}" for name in FORWARD_ENV if name in env]
    cmd += ["--", sys.executable, str(Path(__file__).resolve()), "deploy", "--sha", sha, "--kind", "deploy",
            "--reason", reason]
    r = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"`systemd-run --unit={unit}` exited {r.returncode}: {r.stderr.strip()}")


def run_release(sha: str, kind: str, reason: str) -> tuple[int, str]:
    """epd_loop.release_prod(sha, kind=RELEASE_KIND[kind], reason=reason) from CHECKOUT, its output passed
    through; (exit code, why it ended)."""
    env = dict(os.environ, EPD_REPO_CHECKOUT=str(CHECKOUT), EPD_PROD_HOME=str(PROD_HOME))
    code = ("import sys, epd_loop; "
            "epd_loop.release_prod(sys.argv[1], kind=sys.argv[2], reason=sys.argv[3])")
    p = subprocess.Popen([sys.executable, "-c", code, sha, RELEASE_KIND[kind], reason],
                         cwd=BIN, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tail: collections.deque[str] = collections.deque(maxlen=40)
    assert p.stdout is not None
    for line in p.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        if line.strip():
            tail.append(line.strip())
    code = p.wait()
    errors = [t for t in tail if "ERROR:" in t]
    why = (errors[-1].split("ERROR:", 1)[1].strip() if errors else (tail[-1] if tail else "no output"))
    return code, why


def live_commit() -> str | None:
    """The commit standee records for the live environment, when it was built from a clean tree."""
    r = subprocess.run(["standee", "status", PROD_ENV, "--json"], text=True, capture_output=True)
    if r.returncode != 0 and f"no environment named '{PROD_ENV}'" in (r.stderr + r.stdout):
        return None  # not stood up yet (a rehearsal's first tick): nothing is live
    if r.returncode != 0:
        raise RuntimeError(f"`standee status {PROD_ENV} --json` exited {r.returncode}: {r.stderr.strip()}")
    commit = json.loads(r.stdout).get("commit") or {}
    sha = commit.get("sha")
    return sha if isinstance(sha, str) and SHA.match(sha) and not commit.get("dirty") else None


def _user_bus_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")  # an ssh forced command may lack it
    return env


# ------------------------------------------------------------------- state and log --

def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).isoformat(timespec="seconds")


def _time(text: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(text) if text else None


@contextlib.contextmanager
def _flock(path: Path, blocking: bool):
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        os.close(fd)


def state_lock():
    return _flock(STATE_LOCK, blocking=True)


def load_state() -> dict:
    """state.json, every seam key present. A file that is not that shape is an error, never a reset."""
    if not STATE_FILE.exists():
        return json.loads(json.dumps(STATE_DEFAULTS))
    st = json.loads(STATE_FILE.read_text())
    if not isinstance(st, dict) or not isinstance(st.get("undone_shas", []), list):
        raise ValueError(f"{STATE_FILE} is not a deployer state (an object with a list undone_shas)")
    for key, default in STATE_DEFAULTS.items():
        st.setdefault(key, json.loads(json.dumps(default)))
    return st


def save_state(st: dict) -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(st, f, indent=2)
        f.write("\n")
    os.replace(tmp, STATE_FILE)


def _last_event() -> dict | None:
    if not LOG_FILE.exists():
        return None
    lines = [line for line in LOG_FILE.read_text().splitlines() if line.strip()]
    return json.loads(lines[-1]) if lines else None


def record(kind: str, sha: str | None, from_sha: str | None, reason: str, result: str, unit: str | None,
           tell: bool = True, once: bool = False) -> dict | None:
    """One line in deploys.jsonl, and one fyi to RollCall when `tell`.

    `once`: not again while the newest line is this same kind, commit and result (a refusal that a
    later tick meets again, unchanged, is said once).
    """
    event = {"ts": _iso(now()), "kind": kind, "sha": sha, "from_sha": from_sha, "reason": reason,
             "result": result, "unit": unit}
    last = _last_event()
    if once and last and all(last.get(k) == event[k] for k in ("kind", "sha", "result")):
        return None
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(LOG_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(event) + "\n").encode())
    finally:
        os.close(fd)
    if tell:
        short = lambda s: s[:8] if s else "none"  # noqa: E731
        notify.role(NOTIFY_ROLE, "fyi", f"rollcall-cd {kind} {short(sha)} (live was {short(from_sha)}): "
                                        f"{result}. {reason}")
    return event


def _started_sha(unit: str) -> str | None:
    """The commit a deploy unit was started for, from its `started` line."""
    if not LOG_FILE.exists():
        return None
    for line in reversed(LOG_FILE.read_text().splitlines()):
        if line.strip():
            e = json.loads(line)
            if e.get("unit") == unit and e.get("result") == "started":
                return e.get("sha")
    return None


# ---------------------------------------------------------------------- the checkout --

def ensure_clone() -> None:
    """CHECKOUT is a plain clone of the repository (made if missing): never a wt worktree."""
    if not CHECKOUT.exists():
        CHECKOUT.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "--quiet", REPO_URL, str(CHECKOUT), cwd=CHECKOUT.parent)
    if not (CHECKOUT / ".git").is_dir():
        raise CheckoutProblem(f"{CHECKOUT} is not a plain clone (no .git directory; a worktree's .git is a file)")


def fetch_head() -> str:
    git("fetch", "--quiet", "origin", BRANCH)
    head = git("rev-parse", f"refs/remotes/origin/{BRANCH}")
    if not SHA.match(head):
        raise CheckoutProblem(f"origin/{BRANCH} resolved to {head!r}, not a commit")
    return head


def dirty() -> str:
    """What `git status --porcelain` lists in CHECKOUT (ignored files are not listed)."""
    return git("status", "--porcelain")


def checkout(sha: str) -> None:
    """CHECKOUT detached at `sha`, clean, `sha` on origin/BRANCH; CheckoutProblem otherwise."""
    if listed := dirty():
        raise CheckoutProblem(f"{CHECKOUT} has changes; refusing to build from it: {listed.splitlines()[0]}")
    try:
        git("merge-base", "--is-ancestor", sha, f"refs/remotes/origin/{BRANCH}")
    except subprocess.CalledProcessError as e:
        raise CheckoutProblem(f"{sha[:12]} is not a commit on origin/{BRANCH}") from e
    git("-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", sha)
    head = git("rev-parse", "HEAD")
    if head != sha:
        raise CheckoutProblem(f"{CHECKOUT} is at {head[:12]} after checking out {sha[:12]}")
    link_live_files()
    if listed := dirty():
        raise CheckoutProblem(f"{CHECKOUT} is not clean at {sha[:12]}: {listed.splitlines()[0]}")


def link_live_files() -> None:
    """Each file standee.yaml's backup lists, linked from CHECKOUT to the live one in PROD_HOME.

    `standee backup` copies those files (the master key in .env, the owner's book) from the directory
    the environment was last stood up from. Once that is CHECKOUT, each must lead to the live file, or
    the nightly backup would skip it. A link, not a copy: the live file stays where it is.
    """
    import yaml  # the host's python3 has it

    names = ((yaml.safe_load((CHECKOUT / "standee.yaml").read_text()) or {}).get("backup") or {}).get("files") or []
    for name in names:
        link, target = CHECKOUT / name, PROD_HOME / name
        if link.is_symlink():
            if os.readlink(link) == str(target):
                continue
            link.unlink()
        elif link.exists():
            raise CheckoutProblem(f"{link} is a file of its own; it would be backed up instead of {target}")
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, link)


# --------------------------------------------------------------------------- decide --

def decide(st: dict, head: str, at: dt.datetime) -> tuple[str, str, dt.datetime | None]:
    """(decision, reason, due) for HEAD, from the state alone: deploy, idle, waiting or skip."""
    short = head[:8]
    if head in st["undone_shas"]:
        return "skip", f"{short} is in undone_shas: not released again on its own", None
    if head == st["deployed_sha"]:
        return "idle", f"{short} is live", None
    due = _time(st["last_seen_at"]) + QUIET
    ended = _time(st["last_deploy_end_at"])
    if ended and ended + QUIET > due:
        due = ended + QUIET
    if at < due:
        return "waiting", f"{short}: quiet until {_iso(due)}", due
    return "deploy", f"master {short}, unchanged since {st['last_seen_at']}", None


def tick() -> dict:
    """One decision: note a moved HEAD, notice a deploy that ended, start the next one when due."""
    ensure_clone()
    head = fetch_head()
    with state_lock():
        at = now()
        fresh = not STATE_FILE.exists()
        st = load_state()
        if fresh:
            st["deployed_sha"] = live_commit()  # what is live already is not deployed again
        moved = head != st["last_seen_head"]
        if moved or not st["last_seen_at"]:
            st["last_seen_head"], st["last_seen_at"] = head, _iso(at)
        out = {"head": head, "deployed_sha": st["deployed_sha"], "unit": st["deploy_running_unit"]}
        unit = st["deploy_running_unit"]
        if unit and unit_running(unit):
            save_state(st)
            return {**out, "decision": "running", "reason": f"{unit} is releasing"}
        lost = None
        if unit:  # it ended without recording its end: do not guess how it went
            lost_sha = _started_sha(unit)
            st["deploy_running_unit"], st["last_deploy_end_at"] = None, _iso(at)
            if lost_sha and lost_sha not in st["undone_shas"]:
                st["undone_shas"].append(lost_sha)
            lost = (lost_sha, unit)
        decision, reason, due = decide(st, head, at)
        if decision == "deploy" and (listed := dirty()):
            decision, reason = "refused", f"{CHECKOUT} has changes; refusing to build from it: {listed.splitlines()[0]}"
        new_unit = None
        if decision == "deploy":
            new_unit = UNIT_PREFIX + head[:8]
            st["deploy_running_unit"] = new_unit
        save_state(st)
        out.update(decision=decision, reason=reason, unit=new_unit or out["unit"])
        if due:
            out["due_at"] = _iso(due)
    if lost:
        record("deploy", lost[0], st["deployed_sha"], "its unit ended without recording how the release went; "
               "added to undone_shas", "lost", lost[1])
    if decision == "skip" and moved:
        record("skip", head, st["deployed_sha"], reason, "skipped", None)
    elif decision == "refused":
        record("refusal", head, st["deployed_sha"], reason, "refused", None, once=True)
    elif decision == "deploy":
        record("deploy", head, st["deployed_sha"], reason, "started", new_unit, tell=False)
        try:
            launch(new_unit, head, reason)
        except Exception as e:
            with state_lock():
                st = load_state()
                if st["deploy_running_unit"] == new_unit:
                    st["deploy_running_unit"], st["last_deploy_end_at"] = None, _iso(now())
                    save_state(st)
            record("refusal", head, st["deployed_sha"], f"could not start {new_unit}: {e}", "refused", new_unit)
            raise
    return out


# --------------------------------------------------------------------------- deploy --

def deploy(sha: str, kind: str, reason: str) -> int:
    """Release `sha` from CHECKOUT through epd_loop.deploy_prod, and record how it went."""
    if not isinstance(sha, str) or not SHA.match(sha):
        raise ValueError(f"--sha must be a full 40-character commit sha, got {sha!r}")
    if kind not in KINDS:
        raise ValueError(f"--kind must be one of {', '.join(KINDS)}, got {kind!r}")
    if not reason or not reason.strip():
        raise ValueError("--reason must say why this release")
    me = os.environ.get("ROLLCALL_CD_UNIT") or f"pid:{os.getpid()}"
    unit = None if me.startswith("pid:") else me
    with state_lock():
        st = load_state()
        from_sha, other = st["deployed_sha"], st["deploy_running_unit"]
        busy = bool(other and other != me and unit_running(other))
        if not busy:
            st["deploy_running_unit"] = me
            save_state(st)
    if busy:
        record("refusal", sha, from_sha, f"{reason} | {other} is releasing; nothing was changed", "busy", unit)
        return DEPLOY_BUSY
    # Until the release starts nothing has changed: a failure before it is a refusal, and the commit
    # may be tried again. From then on it is a failed release, which deploy_prod has undone.
    code, ev_kind, result, why = 1, "refusal", "refused", ""
    try:
        with _flock(CHECKOUT_LOCK, blocking=False) as got:
            if not got:
                code, result = DEPLOY_BUSY, "busy"
                why = f"another release is using {CHECKOUT}; nothing was changed"
            else:
                ensure_clone()
                fetch_head()
                checkout(sha)
                ev_kind, result = kind, "failed"
                code, why = run_release(sha, kind, reason)
                if code == 0:
                    result = "ok"
                elif code == DEPLOY_ALREADY_LIVE:  # what was asked for is live: done, nothing changed
                    code, result = 0, "ok"
                elif code == DEPLOY_BUSY:
                    ev_kind, result = "refusal", "busy"
                elif code == DEPLOY_REFUSED:  # the order guard: it would refuse again, so not again on its own
                    ev_kind, result = "refusal", "out of order"
    except CheckoutProblem as e:
        code, why = 1, str(e)
    except Exception as e:  # recorded, then raised: a deploy never ends without a line saying so
        code, why = 1, f"{type(e).__name__}: {e}"
        raise
    finally:
        with state_lock():
            st = load_state()
            if result == "ok":  # live now (a hand release of an undone commit too): not undone any more
                st["deployed_sha"] = sha
                st["undone_shas"] = [s for s in st["undone_shas"] if s != sha]
            elif result in ("failed", "out of order") and sha not in st["undone_shas"]:
                st["undone_shas"].append(sha)
            st["last_deploy_end_at"] = _iso(now())
            if st["deploy_running_unit"] == me:
                st["deploy_running_unit"] = None
            save_state(st)
        record(ev_kind, sha, from_sha, f"{reason} | {why}" if why else reason, result, unit)
    return code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tick", help="one decision: deploy master's HEAD once it has been quiet for 2 minutes")
    d = sub.add_parser("deploy", help="release one commit from the deploy checkout through epd_loop.deploy_prod")
    d.add_argument("--sha", required=True)
    d.add_argument("--kind", required=True, choices=KINDS)
    d.add_argument("--reason", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "tick":
        out = tick()
        print(json.dumps(out))
        return 1 if out["decision"] == "refused" else 0
    return deploy(a.sha, a.kind, a.reason)


if __name__ == "__main__":
    sys.exit(main())
