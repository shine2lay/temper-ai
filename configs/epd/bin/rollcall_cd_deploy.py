#!/usr/bin/env python3
"""RollCall's release hook for `wt deploy`: one release of one commit from the deploy clone.

    rollcall_cd_deploy.py deploy --sha S --kind deploy|undo --reason TEXT
        One release of S through epd_loop.deploy_prod (backup, up, migrate, health, its own undo, the
        prod/<yyyymmdd-hhmm> tag), from the deploy clone. Exit 0 when S is live and healthy (or was live
        already), 75 when another release holds the clone or deploy_prod's lock, 76 when deploy_prod's
        order guard refused (the live commit is no ancestor of S); both: nothing changed. 1 otherwise.

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
import subprocess
import sys
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
        code, why = run_release(sha, kind, reason)
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
