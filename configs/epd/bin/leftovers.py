#!/usr/bin/env python3
"""epd_leftovers: what the build machinery left on spark, whether anything still needs it, and why
it stayed. Read-only; no model; python3 stdlib only.

    python3 /app/configs/epd/bin/leftovers.py [--workspaces-root REPOS] [--server-url URL]
                                              [--standee-local] [--report-dir DIR]

What it lists (the sources), per repository under the workspaces' repos/ folder:
  claim     repos/<repo>/claims/*.json (claims/released/ is history and is skipped)
  worktree  repos/<repo>/worktrees/*
  branch    every local branch of repos/<repo>/main except the base branch
  env       every dev-tier entry of `standee ls --json`
and, from `standee doctor --json`, how many docker volumes are attached to nothing (a count only:
a run box has no docker socket, and standee forgets an environment's volumes once prune takes the
environment down with its volumes kept).

Each item gets a class:
  in_use          something live still needs it
  kept_by_design  kept on purpose: github_work, linear_work and notion_work run epd_task with
                  keep: true so a later reply continues on the branch; a dev environment nothing
                  names whose ttl has not run out (standee takes it down then)
  leftover        nothing needs it; `reason` says why it stayed, `fix_owner` whose fix that is
  unknown         the audit could not tell (a run the runs API does not know or cannot be reached,
                  git records that do not resolve, a status it does not know). Never a guess.

How a class is decided:
  - EPD items (slug epd-bNNN, env <repo>-dev-epd-bNNN) go by the bet's state.json status: being
    built (epd_loop.py LIVE) or shipped with its measure pending -> in_use; finished (TERMINAL,
    stopped, build_failed) -> leftover for RollCall, whose driver releases a bet's claim, worktree and
    branch only after the owner's word on its PR (epd_loop.py release_task).
  - Other claims go by the status of the run that made them (GET /api/workflows/<run_id>): active ->
    in_use; finished and holding its clean-ups for a resume -> in_use; finished in a workflow that
    keeps its task -> kept_by_design (temper's: nothing ever releases them); finished otherwise ->
    leftover (systems': the run ended without its clean-up).
  - Worktrees and branches follow their claim; with no claim they are leftovers.
  - A dev environment follows its bet or claim; with neither it is kept_by_design until its ttl runs
    out, and a leftover after that or when it has no ttl.
Every worktree and branch also says whether a sweep could remove it without losing work: its
uncommitted changes, and whether its commits are on origin/<branch> or origin/<base> (the checks
task_cleanup makes, against the remote-tracking refs as they are: nothing is fetched).
`not_sweepable` is true when either would lose something.

Read-only: git runs with GIT_OPTIONAL_LOCKS=0 (a `git status` that may not refresh the index), and
standee only as `standee ls --json` and `standee doctor --json`. The only thing written is the
report, <workspaces>/leftovers/<UTC timestamp>.json, so later runs give a trend.

Fail loud: a source that cannot be read (no workspaces root, standee unreachable, a claim or state
file or standee answer that is not JSON) exits 1 with the reason. The runs API is the exception:
its items become `unknown` with the run id, because a run box that cannot reach the API can still
say everything else. The last stdout line is the JSON result, like the other EPD script agents.

Standee is reached the way task_stack_down reaches it: ssh to the host with the key mounted at
/app/standee-ssh, copied to a 0600 temp file that is removed on exit. --standee-local runs the
`standee` on PATH instead (on the host, by hand).
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

# epd_loop.py's own sets (TERMINAL near line 261, LIVE near line 1507);
# tests/test_epd/test_leftovers.py fails when they drift apart.
LIVE = {"approved", "running", "tasked", "built", "pr_opened"}
TERMINAL = {"rejected", "kept", "iterate", "killed", "closed", "changes_requested"}
BET_IN_USE = LIVE | {"shipped"}  # shipped: merged, its measure still to run
BET_FINISHED = TERMINAL | {"stopped", "build_failed"}

# The workflows that run epd_task with keep: true, so a later reply continues on the same branch
# (configs/workflows/github_work.yaml, linear_work.yaml, notion_work.yaml). The tests check this
# set against every workflow that says keep: true (epd_loop's EPD items go by their bet instead).
KEEPS_TASK = {"github_work", "linear_work", "notion_work"}

RUN_ACTIVE = {"pending", "queued", "running", "waiting", "paused"}
RUN_FINISHED = {"completed", "failed", "cancelled", "interrupted"}

CLASSES = ("in_use", "kept_by_design", "leftover", "unknown")
EPD_SLUG = re.compile(r"^epd-(b\d{3,})$")
# Where other boxes mount the same workspaces tree: the server container at /app/workspaces, the
# worker and the run boxes also at the host path ($WORKSPACE_DIR). Git records written in one name
# the tree by its path there.
CONTAINER_WORKSPACES = "/app/workspaces"
DEFAULT_SERVER = "http://server:8420"
STANDEE_HOST = "shinelay@host.docker.internal"
STANDEE_SSH_DIR = "/app/standee-ssh"
GIT_ENV = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


class Fail(Exception):
    """A source that cannot be read: the run fails with this reason."""


# ---- small helpers ---------------------------------------------------------------------------------


def iso(t: dt.datetime | None) -> str | None:
    return t.astimezone(dt.UTC).isoformat(timespec="seconds") if t else None


def parse_time(value) -> dt.datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.UTC)


def mtime(path: Path) -> dt.datetime:
    return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC)


def days(since: dt.datetime | None, now: dt.datetime) -> float | None:
    return round((now - since).total_seconds() / 86400, 1) if since else None


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise Fail(f"cannot read {path} as JSON: {e}") from e
    if not isinstance(data, dict):
        raise Fail(f"{path} is not a JSON object")
    return data


def git(*args: str, cwd: Path | None = None, git_dir: Path | None = None,
        work_tree: Path | None = None) -> subprocess.CompletedProcess:
    """Read-only git. safe.directory=*: the clones belong to the containers' user, and whoever runs
    this (a run box, the host) may not; core.fsmonitor=false: no helper process starts."""
    cmd = ["git", "-c", "safe.directory=*", "-c", "core.fsmonitor=false"]
    if git_dir:
        cmd += ["--git-dir", str(git_dir)]
    if work_tree:
        cmd += ["--work-tree", str(work_tree)]
    if cwd:
        cmd += ["-C", str(cwd)]
    return subprocess.run([*cmd, *args], capture_output=True, text=True, env=GIT_ENV, timeout=60)


def git_ok(*args: str, **kw) -> str:
    done = git(*args, **kw)
    if done.returncode != 0:
        where = kw.get("cwd") or kw.get("git_dir")
        raise Fail(f"git {' '.join(args)} failed in {where}: {done.stderr.strip()[-300:]}")
    return done.stdout


def verdict(cls: str, reason: str, fix_owner: str | None = None, **evidence) -> dict:
    return {"class": cls, "reason": reason, "fix_owner": fix_owner, "evidence": evidence}


# ---- where things are -----------------------------------------------------------------------------


def find_repos_root(given: str | None) -> Path:
    """The same choice task_claim makes: the server's mount, else the host path the worker and the
    run boxes export as WORKSPACE_DIR, else ~/workspaces."""
    if given:
        root = Path(given)
    elif Path(CONTAINER_WORKSPACES).is_dir():
        root = Path(CONTAINER_WORKSPACES) / "repos"
    elif os.environ.get("WORKSPACE_DIR") and Path(os.environ["WORKSPACE_DIR"]).is_dir():
        root = Path(os.environ["WORKSPACE_DIR"]) / "repos"
    else:
        root = Path.home() / "workspaces" / "repos"
    if not root.is_dir():
        raise Fail(f"workspaces root {root} does not exist")
    return root


def resolve_recorded(path: Path, workspaces: Path) -> Path | None:
    """A path git recorded in another box: as written, else read through this box's mount."""
    if path.exists():
        return path
    text = str(path)
    for prefix in (CONTAINER_WORKSPACES, os.environ.get("WORKSPACE_DIR", "")):
        prefix = prefix.rstrip("/")
        if prefix and text.startswith(prefix + "/"):
            moved = workspaces / text[len(prefix) + 1:]
            if moved.exists():
                return moved
    return None


# ---- standee ---------------------------------------------------------------------------------------


class Standee:
    """`standee ls --json` and `standee doctor --json`, and nothing else."""

    def __init__(self, local: bool, ssh_dir: str = STANDEE_SSH_DIR, host: str = STANDEE_HOST):
        self.local, self.ssh_dir, self.host = local, Path(ssh_dir), host
        self.key: str | None = None

    def __enter__(self) -> Standee:
        if not self.local:
            src = self.ssh_dir / "id_ed25519"
            if not src.is_file():
                raise Fail(f"no standee ssh key at {src}")
            fd, self.key = tempfile.mkstemp(prefix="standee-key-")  # created 0600
            with os.fdopen(fd, "wb") as f:
                f.write(src.read_bytes())
        return self

    def __exit__(self, *_exc) -> None:
        if self.key:
            try:
                os.unlink(self.key)
            except FileNotFoundError:
                pass
            self.key = None

    @property
    def via(self) -> str:
        return "standee on PATH" if self.local else f"ssh {self.host}"

    def run(self, *args: str) -> subprocess.CompletedProcess:
        if self.local:
            cmd = ["standee", *args]
        else:
            cmd = ["ssh", "-i", str(self.key), "-o", "IdentitiesOnly=yes",
                   "-o", f"UserKnownHostsFile={self.ssh_dir / 'known_hosts'}",
                   "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                   self.host, "standee", *args]
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise Fail(f"standee unreachable ({self.via}): {e}") from e
        if not self.local and done.returncode == 255:
            raise Fail(f"standee unreachable ({self.via}): {done.stderr.strip()[-300:]}")
        return done

    def ls(self) -> list[dict]:
        done = self.run("ls", "--json")
        if done.returncode != 0:
            raise Fail(f"standee ls --json failed (exit {done.returncode}): {done.stderr.strip()[-300:]}")
        try:
            entries = json.loads(done.stdout)["entries"]
        except (ValueError, KeyError, TypeError) as e:
            raise Fail(f"standee ls --json did not answer with its entries: {e}") from e
        if not isinstance(entries, list):
            raise Fail("standee ls --json: entries is not a list")
        return entries

    def unattached_volumes(self) -> tuple[int, str]:
        # doctor exits 1 when any check fails; its JSON is the answer either way.
        done = self.run("doctor", "--json")
        try:
            checks = json.loads(done.stdout)
        except ValueError as e:
            raise Fail(f"standee doctor --json did not answer JSON (exit {done.returncode}): "
                       f"{done.stderr.strip()[-300:] or e}") from e
        found = [c for c in checks if isinstance(c, dict) and c.get("area") == "disk" and c.get("name") == "volumes"]
        if not found:
            raise Fail("standee doctor --json has no disk/volumes check (did `docker volume ls` fail on the host?)")
        detail = str(found[0].get("detail") or "")
        m = re.search(r"(\d+) volume\(s\) attached to nothing", detail)
        if m:
            return int(m.group(1)), detail
        if "no orphans" in detail:
            return 0, detail
        raise Fail(f"standee doctor's volumes check says something this audit cannot read: {detail!r}")


# ---- the runs API -----------------------------------------------------------------------------------


class Runs:
    def __init__(self, server: str):
        self.server = server.rstrip("/")
        self.cache: dict[str, dict] = {}
        # Straight to the server: a proxy in the environment is for the outside world.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, run_id: str) -> dict:
        """{"ok": run} or {"why": the reason it is unknown}."""
        if run_id not in self.cache:
            self.cache[run_id] = self._fetch(run_id)
        return self.cache[run_id]

    def _fetch(self, run_id: str) -> dict:
        url = f"{self.server}/api/workflows/{run_id}"
        try:
            with self.opener.open(url, timeout=30) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"why": f"run {run_id} not found on {self.server}"}
            return {"why": f"the runs API answered {e.code} for run {run_id}"}
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            return {"why": f"runs API unreachable at {self.server}: {getattr(e, 'reason', e)}"}
        try:
            run = json.loads(body)
        except ValueError:
            return {"why": f"the runs API did not answer JSON for run {run_id}"}
        return {"ok": run} if isinstance(run, dict) else {"why": f"the runs API answered no run for {run_id}"}


# ---- what decides a class -----------------------------------------------------------------------------


def bet_verdict(workspaces: Path, repo: str, bet_id: str) -> dict:
    path = workspaces / "epd" / repo / "bets" / bet_id / "state.json"
    if not path.is_file():
        return verdict("unknown", f"bet {bet_id} has no state.json at {path}", bet=bet_id)
    status = read_json(path).get("status")
    changed = iso(mtime(path))
    ev = {"bet": bet_id, "bet_status": status, "state_path": str(path), "state_changed": changed}
    if status in BET_IN_USE:
        what = "shipped, its measure still to run" if status == "shipped" else "being built"
        return verdict("in_use", f"bet {bet_id} is {status} ({what})", **ev)
    if status in BET_FINISHED:
        if status in ("stopped", "build_failed"):
            why = ("epd_loop.py releases a bet's claim, worktree and branch (release_task) only after the "
                   "owner's word on its PR, and this run stopped short of one")
        else:
            why = "release_task, which runs when its PR is decided, did not release it"
        return verdict("leftover", f"bet {bet_id} is {status} (state.json last changed {changed}); {why}",
                       "RollCall", **ev)
    return verdict("unknown", f"bet {bet_id} is {status!r}, in neither epd_loop's live nor its finished statuses",
                   **ev)


def run_verdict(runs: Runs, run_id: str) -> dict:
    if not run_id:
        return verdict("unknown", "the claim names no run")
    got = runs.get(run_id)
    if "why" in got:
        return verdict("unknown", got["why"], run_id=run_id)
    run = got["ok"]
    status, workflow = run.get("status"), run.get("workflow_name")
    ended = iso(parse_time(run.get("end_time"))) or run.get("end_time")  # the API's times are naive UTC
    ev = {"run_id": run_id, "run_status": status, "workflow": workflow, "run_ended": ended}
    hold = run.get("hold") if isinstance(run.get("hold"), dict) else None
    short = f"run {run_id[:8]} ({workflow})"
    if status in RUN_ACTIVE:
        return verdict("in_use", f"{short} is {status}", **ev)
    if status in RUN_FINISHED:
        if hold and hold.get("status") == "waiting":
            return verdict("in_use", f"{short} {status}; temper holds its clean-ups for a resume until "
                                     f"{hold.get('deadline')}", **ev, hold_deadline=hold.get("deadline"))
        if workflow in KEEPS_TASK:
            return verdict("kept_by_design", f"{short} {status} at {ended}; {workflow} runs epd_task with keep: "
                                             "true so a later reply continues on the branch, and nothing "
                                             "ever releases it", "temper", **ev)
        return verdict("leftover", f"{short} {status} at {ended} without releasing its task (its clean-up "
                                   "never ran or did not finish)", "systems", **ev)
    return verdict("unknown", f"{short} has status {status!r}, which this audit does not know", **ev)


def follow(base: dict, kind: str) -> dict:
    """A worktree, branch or env takes its claim's (or bet's) class."""
    out = json.loads(json.dumps(base))
    out["reason"] = f"follows its {kind}: {base['reason']}"
    return out


# ---- git facts ---------------------------------------------------------------------------------------


class Clone:
    """repos/<repo>/main: its base branch and what each local branch has that origin does not."""

    def __init__(self, main: Path):
        self.main = main
        head = git("symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", cwd=main)
        if head.returncode == 0 and head.stdout.strip():
            self.base = head.stdout.strip().removeprefix("origin/")
        else:
            self.base = git_ok("rev-parse", "--abbrev-ref", "HEAD", cwd=main).strip()
        fetched = main / ".git" / "FETCH_HEAD"
        self.origin_as_of = iso(mtime(fetched)) if fetched.exists() else None
        self.branches: dict[str, dict] = {}
        out = git_ok("for-each-ref", "refs/heads", "--format=%(refname)%00%(objectname)%00%(committerdate:unix)",
                     cwd=main)
        for line in out.splitlines():
            ref, sha, when = line.split("\0")
            name = ref.removeprefix("refs/heads/")
            self.branches[name] = {"tip": sha, "tip_time": dt.datetime.fromtimestamp(int(when or 0), dt.UTC)}

    def has(self, ref: str) -> bool:
        return git("rev-parse", "-q", "--verify", ref, cwd=self.main).returncode == 0

    def ahead(self, upstream: str, rev: str) -> int:
        return int(git_ok("rev-list", "--count", f"{upstream}..{rev}", cwd=self.main).strip())

    def safety(self, rev: str, branch: str | None) -> dict:
        """task_cleanup's test: everything on origin/<branch>, or everything already on origin/<base>."""
        on_origin = bool(branch) and self.has(f"refs/remotes/origin/{branch}")
        ahead_origin = self.ahead(f"refs/remotes/origin/{branch}", rev) if on_origin else None
        has_base = self.has(f"refs/remotes/origin/{self.base}")
        ahead_base = self.ahead(f"refs/remotes/origin/{self.base}", rev) if has_base else None
        safe = (on_origin and ahead_origin == 0) or ahead_base == 0
        return {"base": self.base, "on_origin": on_origin, "ahead_of_origin_branch": ahead_origin,
                "ahead_of_origin_base": ahead_base, "branch_safe": bool(safe),
                "origin_refs_as_of": self.origin_as_of}


def worktree_facts(wt: Path, workspaces: Path, clone: Clone | None) -> dict:
    """Uncommitted changes and branch safety, or why the git records do not resolve."""
    dot = wt / ".git"
    if not dot.is_file():
        return {"resolves": False, "why": f"{dot} is not a worktree's .git file"}
    m = re.match(r"gitdir:\s*(.+)", dot.read_text().strip())
    if not m:
        return {"resolves": False, "why": f"{dot} names no gitdir"}
    recorded = Path(m.group(1).strip())
    gitdir = resolve_recorded(recorded, workspaces)
    if gitdir is None:
        return {"resolves": False, "why": f"its git records do not resolve: {recorded}", "gitdir": str(recorded)}
    facts = {"resolves": True, "gitdir": str(recorded)}
    if gitdir != recorded:
        facts["read_through"] = str(gitdir)
    status = git("status", "--porcelain", "--untracked-files=all", git_dir=gitdir, work_tree=wt)
    head = git("rev-parse", "HEAD", git_dir=gitdir)
    if status.returncode != 0 or head.returncode != 0:
        return {**facts, "resolves": False,
                "why": f"git cannot read it: {(status.stderr or head.stderr).strip()[-300:]}"}
    facts["uncommitted"] = len([line for line in status.stdout.splitlines() if line.strip()])
    branch = git("symbolic-ref", "-q", "--short", "HEAD", git_dir=gitdir)
    facts["branch"] = branch.stdout.strip() if branch.returncode == 0 else None
    facts["head"] = head.stdout.strip()
    if clone is not None:
        facts.update(clone.safety(facts["head"], facts["branch"]))
    else:
        facts["branch_safe"] = None
    facts["not_sweepable"] = facts["uncommitted"] > 0 or facts.get("branch_safe") is not True
    return facts


# ---- the audit -----------------------------------------------------------------------------------------


def audit(repos_root: Path, runs: Runs, standee: Standee, now: dt.datetime) -> dict:
    workspaces = repos_root.parent
    entries = standee.ls()
    volumes, volumes_detail = standee.unattached_volumes()

    items: list[dict] = []
    notes: list[str] = []
    claims_by_repo: dict[str, dict[str, dict]] = {}
    repos = sorted(p for p in repos_root.iterdir() if p.is_dir())

    def add(kind: str, repo: str, name: str, slug: str | None, v: dict, age: float | None, **extra) -> None:
        items.append({"kind": kind, "repo": repo, "name": name, "slug": slug, "class": v["class"],
                      "reason": v["reason"], "fix_owner": v["fix_owner"] if v["class"] == "leftover"
                      or v["class"] == "kept_by_design" else None,
                      "age_days": age, **extra, "evidence": v["evidence"]})

    def owner_of(repo: str, slug: str) -> dict | None:
        m = EPD_SLUG.match(slug)
        if m:
            return bet_verdict(workspaces, repo, m.group(1))
        claim = claims_by_repo.get(repo, {}).get(slug)
        return claim["verdict"] if claim else None

    for repo_dir in repos:
        repo = repo_dir.name
        claims_dir, worktrees_dir, main = repo_dir / "claims", repo_dir / "worktrees", repo_dir / "main"
        if not (claims_dir.is_dir() or worktrees_dir.is_dir() or main.is_dir()):
            continue  # not a clone's folder (repos/epd holds stray bet files)

        claims: dict[str, dict] = {}
        for path in sorted(claims_dir.glob("*.json")) if claims_dir.is_dir() else []:
            claim = read_json(path)
            slug = claim.get("task_slug") or path.stem
            m = EPD_SLUG.match(slug)
            v = bet_verdict(workspaces, repo, m.group(1)) if m else run_verdict(runs, claim.get("run_id") or "")
            v["evidence"].update({"claim_path": str(path), "claim_run_id": claim.get("run_id"),
                                  "claimed_at": claim.get("claimed_at"), "claim_status": claim.get("status")})
            claims[slug] = {"claim": claim, "verdict": v, "branch": claim.get("branch") or slug}
            claimed = parse_time(claim.get("claimed_at")) or mtime(path)
            add("claim", repo, path.stem, slug, v, days(claimed, now))
        claims_by_repo[repo] = claims
        branch_slug = {c["branch"]: slug for slug, c in claims.items()}

        clone = Clone(main) if (main / ".git").exists() else None

        for wt in sorted(p for p in worktrees_dir.iterdir()) if worktrees_dir.is_dir() else []:
            slug = wt.name
            facts = worktree_facts(wt, workspaces, clone)
            base = owner_of(repo, slug)
            if not facts["resolves"]:
                v = verdict("unknown", f"worktree {wt}: {facts['why']}", path=str(wt))
                if base:
                    v["evidence"]["claim_or_bet"] = base["class"]
            elif base:
                v = follow(base, "bet" if EPD_SLUG.match(slug) else "claim")
            else:
                v = verdict("leftover", f"no claim names {slug}: nothing owns this worktree", "systems")
            v["evidence"].update({"path": str(wt), **{k: facts[k] for k in facts if k not in ("resolves", "why")}})
            add("worktree", repo, slug, slug, v, days(mtime(wt / ".git") if (wt / ".git").exists() else mtime(wt), now),
                not_sweepable=facts.get("not_sweepable") if facts["resolves"] else None,
                uncommitted=facts.get("uncommitted"), branch_safe=facts.get("branch_safe"))

        if clone is not None:
            for name, b in sorted(clone.branches.items()):
                if name == clone.base:
                    continue
                slug = branch_slug.get(name, name)
                base = owner_of(repo, slug)
                v = (follow(base, "bet" if EPD_SLUG.match(slug) else "claim") if base else
                     verdict("leftover", f"no claim names {name} and no worktree is on it" if not
                             (worktrees_dir / name).exists() else f"no claim names {name}", "systems"))
                safety = clone.safety(f"refs/heads/{name}", name)
                v["evidence"].update({"tip": b["tip"], "tip_time": iso(b["tip_time"]), **safety})
                add("branch", repo, name, slug, v, days(b["tip_time"], now),
                    not_sweepable=not safety["branch_safe"], branch_safe=safety["branch_safe"])
        elif main.exists():
            notes.append(f"{repo}: {main} is not a git clone; its branches were not read")

    repo_names = sorted((p.name for p in repos), key=len, reverse=True)
    dev = [e for e in entries if isinstance(e, dict) and e.get("kind") == "managed" and e.get("tier") == "dev"]
    for env in dev:
        name = str(env.get("name"))
        repo, slug = next(((r, name[len(r) + 5:]) for r in repo_names if name.startswith(f"{r}-dev-")),
                          (env.get("project") or "", None))
        base = owner_of(repo, slug) if slug else None
        expires = parse_time(env.get("expires_at"))
        if base:
            v = follow(base, "bet" if EPD_SLUG.match(slug) else "claim")
        elif expires and expires > now:
            v = verdict("kept_by_design", f"no claim or bet names {name}; standee takes it down when its ttl "
                                          f"({env.get('ttl')}) runs out at {env.get('expires_at')}")
        elif expires:
            v = verdict("leftover", f"no claim or bet names {name}, and its ttl ran out at {env.get('expires_at')} "
                                    "but it is still here (standee prune has not taken it down)", "systems")
        else:
            v = verdict("leftover", f"no claim or bet names {name}, and it has no ttl: nothing will take it down",
                        "systems")
        v["evidence"].update({"env": name, "env_status": env.get("status"), "created_at": env.get("created_at"),
                              "ttl": env.get("ttl"), "expires_at": env.get("expires_at")})
        add("env", repo, name, slug, v, days(parse_time(env.get("created_at")), now), expires_at=env.get("expires_at"))

    counts = collections.Counter(i["class"] for i in items)
    by_kind: dict[str, dict] = {}
    for i in items:
        by_kind.setdefault(i["kind"], {c: 0 for c in CLASSES})[i["class"]] += 1
    leftovers = [i for i in items if i["class"] == "leftover"]
    return {
        "status": "ok",
        "generated_at": iso(now),
        "workspaces": str(repos_root),
        "counts": {c: counts.get(c, 0) for c in CLASSES},
        "by_kind": by_kind,
        "leftovers_by_fix_owner": dict(collections.Counter(i["fix_owner"] for i in leftovers)),
        "not_sweepable": sum(1 for i in leftovers if i.get("not_sweepable")),
        "volumes_attached_to_nothing": volumes,
        "volumes_detail": volumes_detail,
        "sources": {"repos": [p.name for p in repos], "runs_api": runs.server, "standee": standee.via,
                    "dev_envs": len(dev)},
        "notes": notes,
        "items": items,
    }


def write_report(report: dict, report_dir: Path, now: dt.datetime) -> Path:
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / f"{now:%Y%m%dT%H%M%SZ}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, indent=2) + "\n")
        os.replace(tmp, path)
    except OSError as e:
        raise Fail(f"cannot write the report to {report_dir}: {e}") from e
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Read-only audit of what the build machinery left behind.")
    p.add_argument("--workspaces-root", help="the repos folder (default: as task_claim finds it)")
    p.add_argument("--server-url", default=os.environ.get("TEMPER_SERVER_URL") or DEFAULT_SERVER)
    p.add_argument("--standee-local", action="store_true", help="run the standee on PATH, not over ssh")
    p.add_argument("--standee-ssh-dir", default=STANDEE_SSH_DIR)
    p.add_argument("--report-dir", help="default: <workspaces>/leftovers")
    args = p.parse_args(argv)
    now = dt.datetime.now(dt.UTC)
    try:
        repos_root = find_repos_root(args.workspaces_root)
        with Standee(args.standee_local, args.standee_ssh_dir) as standee:
            report = audit(repos_root, Runs(args.server_url), standee, now)
        path = write_report(report, Path(args.report_dir) if args.report_dir else repos_root.parent / "leftovers", now)
    except Fail as e:
        print(json.dumps({"status": "failed", "error": str(e)}))
        return 1
    for i in report["items"]:
        flag = " (not sweepable)" if i.get("not_sweepable") and i["class"] == "leftover" else ""
        print(f"{i['class']:<15} {i['kind']:<8} {i['repo']}/{i['name']}{flag}: {i['reason']}")
    c = report["counts"]
    print(f"{len(report['items'])} items: {c['in_use']} in use, {c['kept_by_design']} kept by design, "
          f"{c['leftover']} leftover ({report['not_sweepable']} not sweepable), {c['unknown']} unknown; "
          f"{report['volumes_attached_to_nothing']} volumes attached to nothing. Report: {path}")
    report["report_path"] = str(path)
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
