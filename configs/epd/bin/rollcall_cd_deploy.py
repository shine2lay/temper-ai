#!/usr/bin/env python3
"""RollCall's release hook for `wt deploy`: one release of one commit from the deploy clone.

    rollcall_cd_deploy.py deploy --sha S --kind deploy|undo --reason TEXT
        One release of S through epd_loop.deploy_prod (backup, up, migrate, health, its own undo, the
        prod/<yyyymmdd-hhmm> tag), from the deploy clone. Exit 0 when S is live and healthy (or was live
        already), 75 when another release holds the clone or deploy_prod's lock, 76 when deploy_prod's
        order guard refused (the live commit is no ancestor of S); both: nothing changed. 1 otherwise.

        --kind deploy wraps the release in QA's smoke tests (rollcall qa/smoke, TEST-SMOKE-BOTH): first
        `rollcall-staging put S` and QA's before-release smoke against the staging copy (red: exit 1,
        prod untouched), then the release, then QA's live smoke against prod (red: exit 1 while S is
        live, and wt deploy's own undo puts the previous live commit back). A red is never run again.
        --kind undo runs neither.

`wt deploy` (agent-tools lib/deploy, `repos.rollcall.deploy` in agent-tools wt.yaml, docs/wt-deploy.md)
decides when and what goes live: the two-minute quiet window, batching, skipped commits, CI verdicts, the
money-test undo, the order of releases, its own lock and every notice. It checks the clone out at S and
runs this as its `run` hook (--kind deploy: deploy_prod's kind forward, the order guard applies) and its
`undo` hook (--kind undo: deploy_prod's kind undo, may go back). Exit 75 makes wt deploy try again on its
next tick. To release by hand, use `wt deploy rollcall --sha S`, which holds the repository's turn.

What this adds for RollCall, and nothing more:
  * the clone: a plain clone (not a wt worktree, so `wt gc` never touches it), clean, detached at S, S on
    origin/master;
  * the live files: each file standee.yaml's backup lists, linked from the clone to the live one in
    EPD_PROD_HOME, so the nightly `standee backup` (which copies them from where the environment was last
    stood up) keeps finding the live master key and book;
  * the release: epd_loop.release_prod with the clone as EPD_REPO_CHECKOUT and the live home, its output
    passed through.

The live data comes by absolute path (EPD_PROD_HOME, rollcall's deploy/compose.live.yaml): the standee env
rollcall-prod, its container and port 8020, /home/shinelay/rollcall/var at /data and
/home/shinelay/rollcall/.env. ~/rollcall is never checked out to another commit.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import fcntl
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

BIN = Path(__file__).resolve().parent
EXTRA_PATH = [str(Path.home() / ".local" / "bin"), "/usr/local/bin", "/usr/bin", "/bin"]
os.environ["PATH"] = os.pathsep.join(
    dict.fromkeys([p for p in os.environ.get("PATH", "").split(os.pathsep) if p] + EXTRA_PATH)
)
CHECKOUT = Path(os.environ.get("ROLLCALL_CD_CHECKOUT", "/home/shinelay/rollcall-deploy"))
PROD_HOME = Path(os.environ.get("EPD_PROD_HOME", "/home/shinelay/rollcall"))
REPO_URL = os.environ.get("EPD_REPO_URL", "git@github.com:shine2lay/rollcall.git")
BRANCH = os.environ.get("EPD_BASE_BRANCH", "master")
#: Held by the release that is using CHECKOUT's tree (0700 directory, shared with rollcall_cd_notify's outbox).
STATE_DIR = Path(os.environ.get("ROLLCALL_CD_STATE", str(Path.home() / ".local" / "state" / "rollcall-cd")))
CHECKOUT_LOCK = STATE_DIR / "checkout.lock"
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
#: The standing staging copy (agent-tools lib/staging, wt.yaml repos.rollcall.staging; Systems #130).
STAGING_PUT = ("rollcall-staging", "put")
STAGING_URL = "http://127.0.0.1:8030"
STAGING_CONTAINER = "rollcall-staging-rollcall-1"
PROD_URL = "http://127.0.0.1:8020"
PROD_CONTAINER = "rollcall-prod-rollcall-1"
#: Staging's QA logins have the seed's password: ROLLCALL_SEED_PASSWORD when the copy was given one, else the
#: seed's own default, read inside the container from the code that seeded it (never copied here).
STAGING_PASSWORD = ("python", "-c", "import os, sys; from rollcall.practice.seed.base import DEFAULT_PASSWORD as d; "
                    "sys.stdout.write(os.environ.get('ROLLCALL_SEED_PASSWORD') or d)")
#: Prod's are the live secret in the container's environment; no default.
PROD_PASSWORD = ("printenv", "ROLLCALL_QA_PASSWORD")
STAGING_CEILING_S = 30 * 60
SMOKE_CEILING_S = 20 * 60
CEILING_EXIT = 124


class CheckoutProblem(RuntimeError):
    """The deploy clone is not a clean tree at the commit asked for: nothing was released."""


# ---------------------------------------------------------------- the outside world --
# Each of these is replaced by a fake in tests/test_epd/test_rollcall_cd_deploy.py.

def git(*args: str, cwd: Path | None = None) -> str:
    """Run git in CHECKOUT (or `cwd`); its stdout, stripped. A failure is loud: CalledProcessError."""
    for attempt in range(5):
        r = subprocess.run(["git", *args], cwd=cwd or CHECKOUT, text=True, capture_output=True)
        if r.returncode == 0 or not re.search(r"cannot lock ref|Unable to create .*\.lock", f"{r.stderr}\n{r.stdout}", re.I):
            break
        if attempt < 4:
            time.sleep(0.15)
    if r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, ["git", *args], r.stdout, r.stderr)
    return r.stdout.strip()


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


def run_step(argv: list[str], *, env: dict[str, str] | None = None, ceiling_s: float) -> tuple[int, list[str]]:
    """Run `argv` in CHECKOUT, its output passed through; (exit code, its last 40 non-empty lines).
    Past `ceiling_s` its process group is killed and the code is CEILING_EXIT."""
    p = subprocess.Popen(argv, cwd=CHECKOUT, env=env, text=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, start_new_session=True)
    tail: collections.deque[str] = collections.deque(maxlen=40)
    stopped = threading.Event()

    def stop() -> None:
        stopped.set()
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, signal.SIGKILL)

    timer = threading.Timer(ceiling_s, stop)
    timer.start()
    try:
        assert p.stdout is not None
        for line in p.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if line.strip():
                tail.append(line.strip())
        code = p.wait()
    finally:
        timer.cancel()
    if stopped.is_set():
        tail.append(f"{argv[0]} passed its {int(ceiling_s // 60)}-minute ceiling and was stopped")
        return CEILING_EXIT, list(tail)
    return code, list(tail)


def container_secret(container: str, argv: tuple[str, ...]) -> str:
    """What `docker exec <container> <argv>` prints, for the process env only: never logged or put on a
    command line. '' when it fails (the smoke run then says the password is missing)."""
    r = subprocess.run(["docker", "exec", container, *argv], text=True, capture_output=True, timeout=60)
    return r.stdout.strip() if r.returncode == 0 else ""


@contextlib.contextmanager
def checkout_lock():
    """CHECKOUT_LOCK, without waiting: yields False when another release holds it."""
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(CHECKOUT_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        os.close(fd)


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
    """Each file standee.yaml's backup lists (`files` and `cold_files`), linked from CHECKOUT to the
    live one in PROD_HOME.

    `standee backup` copies those files (the master key in .env, the backtest cache in data/) from the
    directory the environment was last stood up from. Once that is CHECKOUT, each must lead to the live
    file, or the nightly backup would skip it. A link, not a copy: the live file stays where it is, and
    a link to a file that is absent makes the backup name the live path as missing.
    """
    import yaml  # the host's python3 has it

    backup = (yaml.safe_load((CHECKOUT / "standee.yaml").read_text()) or {}).get("backup") or {}
    for name in [*(backup.get("files") or []), *(backup.get("cold_files") or [])]:
        link, target = CHECKOUT / name, PROD_HOME / name
        if link.is_symlink():
            if os.readlink(link) == str(target):
                continue
            link.unlink()
        elif link.exists():
            raise CheckoutProblem(f"{link} is a file of its own; it would be backed up instead of {target}")
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, link)


# ---------------------------------------------------------------------------- smoke --

def red_lines(tail: list[str]) -> str:
    """The FAILED/ERROR lines of a smoke run's tail, else its last line."""
    bad = [t for t in tail if t.startswith(("FAILED", "ERROR")) or " FAIL " in t]
    return "; ".join(bad[-8:]) if bad else (tail[-1] if tail else "no output")


def smoke(command: str, base_url: str, container: str, password_argv: tuple[str, ...]) -> tuple[int, str]:
    """QA's smoke `command` (a rollcall Makefile target) from CHECKOUT against `base_url`, the QA password from
    `container`'s environment straight into the run's environment; (exit code, its red lines)."""
    env = dict(os.environ, ROLLCALL_SMOKE_BASE_URL=base_url,
               ROLLCALL_QA_PASSWORD=container_secret(container, password_argv))
    print(f"rollcall_cd_deploy: {command} against {base_url}", flush=True)
    code, tail = run_step(command.split(), env=env, ceiling_s=SMOKE_CEILING_S)
    print(f"rollcall_cd_deploy: {command} exit {code}", flush=True)
    return code, red_lines(tail)


def before_prod(sha: str) -> str | None:
    """Staging put at `sha`, then smoke-before on it; None when green, else why prod is not touched."""
    print(f"rollcall_cd_deploy: {' '.join(STAGING_PUT)} {sha[:12]}", flush=True)
    code, tail = run_step([*STAGING_PUT, sha], ceiling_s=STAGING_CEILING_S)
    print(f"rollcall_cd_deploy: staging put exit {code}", flush=True)
    if code != 0:
        return f"staging put of {sha[:12]} exited {code}: {tail[-1] if tail else 'no output'}"
    code, red = smoke("make smoke-before", STAGING_URL, STAGING_CONTAINER, STAGING_PASSWORD)
    return None if code == 0 else f"smoke-before on staging exited {code}: {red}"


# --------------------------------------------------------------------------- deploy --

def deploy(sha: str, kind: str, reason: str) -> int:
    """Release `sha` from CHECKOUT through epd_loop.deploy_prod; the exit code wt deploy reads."""
    if not isinstance(sha, str) or not SHA.match(sha):
        raise ValueError(f"--sha must be a full 40-character commit sha, got {sha!r}")
    if kind not in KINDS:
        raise ValueError(f"--kind must be one of {', '.join(KINDS)}, got {kind!r}")
    if not reason or not reason.strip():
        raise ValueError("--reason must say why this release")
    with checkout_lock() as got:
        if not got:
            print(f"rollcall_cd_deploy: another release is using {CHECKOUT}; nothing was changed", flush=True)
            return DEPLOY_BUSY
        try:
            ensure_clone()
            fetch_head()
            checkout(sha)
        except CheckoutProblem as e:  # before the release: nothing changed
            print(f"rollcall_cd_deploy: refused: {e}", flush=True)
            return 1
        if kind == "deploy" and (stop := before_prod(sha)):
            print(f"rollcall_cd_deploy: release of {sha[:12]} stopped before prod: {stop}; prod was not "
                  f"touched", flush=True)
            return 1
        code, why = run_release(sha, kind, reason)
        if kind == "deploy" and code == 0:
            live_code, red = smoke("make smoke-live", PROD_URL, PROD_CONTAINER, PROD_PASSWORD)
            if live_code != 0:  # red: exit 1 naming the last good commit, which wt deploy's undo puts back
                good = os.environ.get("DEPLOY_LIVE_SHA", "")
                print(f"rollcall_cd_deploy: smoke-live on prod exited {live_code} after {sha[:12]} went live: "
                      f"{red}; exit 1, wt deploy's undo puts the last good commit "
                      f"{good[:12] or '(none known: no undo)'} back", flush=True)
                return 1
    if code == DEPLOY_ALREADY_LIVE:  # what was asked for is live: done, nothing changed
        print(f"rollcall_cd_deploy: {sha[:12]} is live already; nothing was changed", flush=True)
        return 0
    if code != 0:
        print(f"rollcall_cd_deploy: release of {sha[:12]} ended {code}: {why}", flush=True)
    return code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("deploy", help="release one commit from the deploy clone through epd_loop.deploy_prod")
    d.add_argument("--sha", required=True)
    d.add_argument("--kind", required=True, choices=KINDS)
    d.add_argument("--reason", required=True)
    a = ap.parse_args(argv)
    return deploy(a.sha, a.kind, a.reason)


if __name__ == "__main__":
    sys.exit(main())
