#!/usr/bin/env python3
"""The EPD loop: propose (report → bets) → [owner picks, on disk] → tasks → build → ship → [owner] → deploy → measure.

The product, design and engineering departments as one loop. Every stage is a
function from files to files; this script is only the wiring, and the keeper
of the state on disk under

    <workspaces>/epd/<repo>/
        goals.md            the owner writes this; read fresh every proposal
        profile.md          what the product is and how the code is laid out
        bets.tsv            the ledger: one row per bet, status and outcome
        backlog.md          the owner's queue and declines, and the loop's record of acting on
                            them (lines are annotated, never removed)
        reports/<round>/    one per proposal: report.md  walk_N.md  round.json
        bets/<bet_id>/      bet.md  bet.json  decision.md  tasks.json
                            build.json  pr.md  outcome.md  state.json

    The agents' files (report.md, bet.md, tasks.json, outcome.md) are written
    by the temper container's user; the owner's decision goes in its own file
    (decision.md) because this script cannot append to theirs.

Two temper runs make one turn of the loop:

    epd_propose  three browser walks on a dev stack of main → report.md; then
                 one to five candidate bets, each a pitch with a falsifiable
                 invariant and a pre-registered threshold → bets/<id>/bet.md
    epd_loop     for one bet off the top of backlog.md: tasks → build (the
                 engineering pipeline) → ship (PR) → [owner: merge?] → deploy
                 → measure → outcome.md

Between them the owner reads the candidates, edits the ones worth building
and lists them in backlog.md in order. `run` does the right thing: a bet in
the backlog is started; none, and candidates waiting for the owner's word,
is reported; none at all, and a proposal is run. The report is walked only
when there is nothing planned -- or on `run --propose`, for more.

Usage:
    epd_loop.py status
    epd_loop.py run [--propose] [--keep] [--wait]   # one temper run: the top bet, or a proposal
    epd_loop.py collect [--keep]                    # record what the last run produced
    epd_loop.py resume [--at STAGE]                 # fork a failed loop run at its last good stage
    epd_loop.py approve BET [--note TEXT]           # put a candidate at the end of backlog.md
    epd_loop.py reject BET --why TEXT               # turn a candidate down, for the record
    epd_loop.py next [--until STAGE] [--keep]       # the loop's stages one by one, from here
    epd_loop.py stage STAGE --bet BET               # run one stage alone, on its files
    epd_loop.py down BET                            # tear down the bet's stacks
    epd_loop.py scorecard

STAGE is one of: tasks build ship deploy measure.
The places a human is required: backlog.md (which bets, in what order) and
the PR (merge, request changes, close -- in temper's UI or on GitHub).
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("TEMPER_API", "http://localhost:8420")
WORKSPACES = Path(os.environ.get("EPD_WORKSPACES", "/home/shinelay/temper-ai/workspaces"))
# Where this loop's own configs live, so a run can record which version of each
# stage produced it.
CONFIG_DIR = Path(os.environ.get("EPD_CONFIG_DIR", str(Path(__file__).resolve().parent.parent)))
# The same directory as the temper containers see it. Every path handed to
# temper (a run's workspace, a file an agent should write) is a container
# path; every path this script touches itself is a host path. The sandbox
# compares the run's workspace with each tool call's directory as strings,
# so mixing the two refuses every call: the pipeline's agents work in
# /app/workspaces/repos/..., and a run whose workspace was given as
# /home/shinelay/... refused all of them (b001's first build, $1.41 of
# refusals).
CONTAINER_WORKSPACES = os.environ.get("EPD_CONTAINER_WORKSPACES", "/app/workspaces")


def cpath(p: Path | str) -> str:
    """A host path under WORKSPACES as the container sees it."""
    s = str(p)
    if not s.startswith(str(WORKSPACES)):
        raise ValueError(f"{s} is not under {WORKSPACES}")
    return CONTAINER_WORKSPACES + s[len(str(WORKSPACES)):]


def hpath(p: str) -> Path:
    """A container path under /app/workspaces as a host path."""
    if p.startswith(CONTAINER_WORKSPACES):
        return WORKSPACES / p[len(CONTAINER_WORKSPACES):].lstrip("/")
    return Path(p)
REPO_NAME = os.environ.get("EPD_REPO", "rollcall")
REPO_URL = os.environ.get("EPD_REPO_URL", "git@github.com:shine2lay/rollcall.git")
# The owner's own checkout: used only to push the branch and open the PR (the
# container's deploy key is read-only). Never built from.
REPO_CHECKOUT = Path(os.environ.get("EPD_REPO_CHECKOUT", "/home/shinelay/rollcall"))
GH_REPO = os.environ.get("EPD_GH_REPO", "shine2lay/rollcall")
BASE_BRANCH = os.environ.get("EPD_BASE_BRANCH", "master")
# The live product: the standee environment, its URL, and the host port its
# front door is pinned to. `ship` merges, backs this up, and stands it up
# again from the merge commit.
PROD_ENV = os.environ.get("EPD_PROD_ENV", "rollcall-prod")
PROD_CONTAINER = os.environ.get("EPD_PROD_CONTAINER", "rollcall-prod-rollcall-1")
# The live server's env file: its compose reads it, so a secret put here reaches
# the container without ever appearing in a command line.
PROD_ENV_FILE = Path(os.environ.get("EPD_PROD_ENV_FILE", "/home/shinelay/rollcall/.env"))
PROD_URL = os.environ.get("EPD_PROD_URL", "https://rollcall.wai2shine.com")
PROD_HOST_PORT = os.environ.get("EPD_PROD_HOST_PORT", "8020")
# The pipeline's clone of the repository (task_worktree keeps it): the report
# stands its stack up from here and the tasks stage reads it, so the loop
# never depends on the state of the owner's checkout.
MAIN_CLONE = WORKSPACES / "repos" / REPO_NAME / "main"
SERVER_CONTAINER = os.environ.get("EPD_TEMPER_CONTAINER", "temper-ai-server-1")

# The seed's test accounts (backend/rollcall/tenancy/seed.py). The dev tier's
# seed hook creates them on a stack's first `up`.
QA_EMAIL = os.environ.get("EPD_QA_EMAIL", "qa@rollcall.test")
QA_EMPTY_EMAIL = os.environ.get("EPD_QA_EMPTY_EMAIL", "qa-empty@rollcall.test")
QA_PASSWORD = os.environ.get("EPD_QA_PASSWORD", "rollcall-qa")

LOOP_DIR = WORKSPACES / "epd" / REPO_NAME
BETS_DIR = LOOP_DIR / "bets"
LEDGER = LOOP_DIR / "bets.tsv"
LEDGER_COLUMNS = ["bet_id", "date", "title", "threshold", "status", "outcome"]
# The owner's list. One bet id per line, top first; anything else on the line is for the owner.
BACKLOG = LOOP_DIR / "backlog.md"
BACKLOG_HEADER = """# Backlog

Your decisions on the candidate bets, and the loop's record of acting on them. Lines are never
removed: the loop appends "→ what it did, when" to a line instead, and skips lines it has acted on.

## Queue

One bet id per line, top first; anything after the id is a note, kept with the decision. The loop
takes the first bet here that is still waiting (`proposed` in bets.tsv). A line here is your
signature on the invariant as it stands in bets/<id>/bet.md when the loop picks it up -- edit the
pitch first if it is not quite right. Reorder lines to change the loop's mind. A line here for a
bet you declined earlier reopens it.

## Declined

One bet id per line, then why. The loop records each as your decision, with the reason, the next
time it runs (`epd_loop.py reject <id> --why '...'` writes the line for you). Candidates in
neither list wait.
"""
BACKLOG_MARK = "  \u2192 "  # what the loop did with a line, and when; a line with one is done with
# One proposal = one round: a report and the candidates it produced.
REPORTS_DIR = LOOP_DIR / "reports"
SLOTS = 5  # bet directories made before a proposal; the agent fills one to five

STAGES = ["tasks", "build", "ship", "deploy", "measure"]
TERMINAL = {"rejected", "kept", "iterate", "killed", "closed", "changes_requested"}
# On file, waiting for the owner's word: not open, not finished.
WAITING = {"proposed"}
# PRs parked at the loop's gate at once. The loop builds the next bet while one waits for the
# owner's word -- a candidate is cheap next to the owner's time -- but not past this: every
# undecided PR is a build the owner has not looked at and a branch the next one may conflict with.
PARKED_LIMIT = 2
# status after each stage completes; what `next` does is read off the status
AFTER = {
    "tasks": "tasked",
    "build": "built",
    "ship": "pr_opened",
    "deploy": "shipped",
}
NEXT_STAGE = {
    "proposed": None,  # waiting in the backlog (or not yet in it)
    "approved": "tasks",
    "tasked": "build",
    "built": "ship",
    "build_failed": None,
    "pr_opened": None,  # the second gate: waits for the owner's word on the PR
    "shipped": "measure",
}

# The owner's word on a PR, as the gate offers it. The labels are what the dashboard shows and
# what comes back selected, so they are matched exactly and not paraphrased anywhere.
PR_MERGE, PR_CHANGES, PR_CLOSE = "Merge", "Request changes", "Close"
PR_DECISIONS = {PR_MERGE: "merge", PR_CHANGES: "request_changes", PR_CLOSE: "close"}


# ----------------------------------------------------------------- helpers --

def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def die(msg: str, code: int = 1) -> None:
    log(f"ERROR: {msg}")
    sys.exit(code)


def read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def write(path: Path, text: str) -> None:
    """Write the file whole, replacing one the container's user left there if need be.

    A file the container wrote is not this user's to open for writing; the directory is shared,
    so a new file put in its place is. That is how the owner's edits to a pitch land, too.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    # the container user (uid 999) has to be able to write next to it
    os.chmod(tmp, 0o666)
    os.replace(tmp, path)


def mkdir_shared(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o777)


# The loop is started by systemd as often as by a shell, and a user unit gets a
# minimal environment: no ~/.local/bin, so no `standee`. That has now cost two
# runs (b002 on the first stage, b003 on the first line), each time discovered
# only after the stack-up had already begun. The PATH a program needs is part of
# the program, not of whoever happens to launch it, so state it here -- and say
# so at the start of a run, rather than at the first use, hours in.

EXTRA_PATH = [str(Path.home() / ".local" / "bin"), "/usr/local/bin", "/usr/bin", "/bin"]
os.environ["PATH"] = os.pathsep.join(
    dict.fromkeys([p for p in os.environ.get("PATH", "").split(os.pathsep) if p] + EXTRA_PATH)
)


def require_tools(*names: str) -> None:
    """Refuse to start when something the run will need is not there."""
    missing = [n for n in names if not shutil.which(n)]
    if missing:
        die(f"not on PATH: {', '.join(missing)}\n"
            f"PATH is {os.environ['PATH']}\n"
            f"(a systemd user unit does not inherit a login PATH; "
            f"EXTRA_PATH in this file is what should have covered it)")


def sh(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    # a multi-line argument (a script) is shown by its first line only
    log("$ " + " ".join(a.split("\n", 1)[0] + (" …" if "\n" in a else "") for a in cmd))
    r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if r.stdout.strip():
        print(r.stdout.rstrip(), flush=True)
    if r.returncode != 0:
        print(r.stderr.rstrip(), flush=True)
        if check:
            die(f"command failed ({r.returncode}): {' '.join(cmd)}")
    return r


def unstr(v):
    """workflow_output values arrive stringified: 'None', 'True', "['a']"."""
    if v is None or v == "None":
        return None
    if v in ("True", "False"):
        return v == "True"
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return json.loads(v)
        except ValueError:
            try:
                import ast
                return ast.literal_eval(v)
            except (ValueError, SyntaxError):
                return v
    return v


# ------------------------------------------------------------------ temper --

def post_run(workflow: str, inputs: dict, workspace: str) -> str:
    body = json.dumps({"workflow": workflow, "workspace_path": workspace, "inputs": inputs}).encode()
    req = urllib.request.Request(f"{API}/api/runs", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)["execution_id"]


def get_run(execution_id: str) -> dict:
    with urllib.request.urlopen(f"{API}/api/workflows/{execution_id}", timeout=60) as resp:
        return json.load(resp)


def wait_for(execution_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    delay, last = 5.0, ""
    while time.monotonic() < deadline:
        time.sleep(delay)
        delay = min(delay * 1.3, 30.0)
        try:
            info = get_run(execution_id)
        except (urllib.error.URLError, TimeoutError):
            continue
        running = [n["name"] for n in info.get("nodes") or [] if n.get("status") == "running"]
        line = f"{info.get('status')} running={running} cost=${info.get('total_cost_usd') or 0:.2f}"
        if line != last:
            log(f"  run {execution_id[:8]}: {line}")
            last = line
        if info.get("status") not in ("running", "pending"):
            return info
    return {"status": "timeout", "id": execution_id}


def config_versions(workflow: str) -> dict[str, int]:
    """The `version:` of the workflow and of every agent it names.

    Read from the YAML rather than parsed with a YAML library: a two-line grep
    has no dependency, and a wrong answer here costs a wrong label on a
    recorded outcome, not a wrong action. Caveat worth knowing: temper imports
    these files at startup, so if one was edited without a restart, the number
    recorded is the file's, not the server's.
    """
    versions: dict[str, int] = {}

    def read(path: Path) -> tuple[int | None, list[str]]:
        if not path.exists():
            return None, []
        text = path.read_text()
        m = re.search(r"^\s{2}version:\s*(\d+)\s*$", text, re.M)
        agents = re.findall(r"^\s+agent:\s*(\S+)\s*$", text, re.M)
        return (int(m.group(1)) if m else None), agents

    # Keys carry the kind: a stage's workflow and its agent usually share a
    # name (epd_measure the workflow drives epd_measure the agent), and an
    # untyped key silently kept only the second one.
    wf_version, agents = read(CONFIG_DIR / "workflows" / f"{workflow}.yaml")
    if wf_version is not None:
        versions[f"workflow:{workflow}"] = wf_version
    for agent in dict.fromkeys(agents):
        agent_version, _ = read(CONFIG_DIR / "agents" / f"{agent}.yaml")
        if agent_version is not None:
            versions[f"agent:{agent}"] = agent_version
    return versions


def rate_limited(run_id: str) -> bool:
    """Did this run fail because the account was rate limited?

    The 429 is only in the run's event log, which lives inside the server
    container; the API's node error_message is empty. A quota wall is not a
    failure of the work, so the loop waits it out rather than dying.
    """
    r = subprocess.run(["docker", "exec", SERVER_CONTAINER, "sh", "-c",
                        f"grep -c -e RateLimitError -e rate_limit_error /app/data/logs/{run_id}/events.jsonl || true"],
                       text=True, capture_output=True)
    return (r.stdout.strip().splitlines() or ["0"])[-1] not in ("0", "")


def run_workflow(workflow: str, inputs: dict, workspace: str, timeout: float,
                 quota_waits: int = 12, quota_wait_s: float = 900.0) -> dict:
    for attempt in range(quota_waits + 1):
        rid = post_run(workflow, inputs, workspace)
        log(f"{workflow} → run {rid}" + (f" (attempt {attempt + 1})" if attempt else ""))
        info = wait_for(rid, timeout)
        if info.get("status") == "completed":
            break
        if attempt < quota_waits and rate_limited(rid):
            log(f"rate limited; the work is fine, the account is not. "
                f"Waiting {quota_wait_s / 60:.0f} min, then running {workflow} again.")
            time.sleep(quota_wait_s)
            continue
        die(f"{workflow} run {rid} ended {info.get('status')}: {info.get('error_message')}")
    out = {k: unstr(v) for k, v in (info.get("workflow_output") or {}).items()}
    out["_versions"] = config_versions(workflow)
    out["_run_id"] = rid
    out["_cost_usd"] = info.get("total_cost_usd")
    out["_duration_s"] = info.get("duration_seconds")
    return out


# ------------------------------------------------------------------ standee --

def standee_up(source: Path, as_name: str, ttl: str) -> tuple[str, str]:
    """Stand a dev stack up from `source`; returns (env_name, url)."""
    r = sh(["standee", "up", str(source), "--project", REPO_NAME, "--as", as_name,
            "--tier", "dev", "--gateway", "--ttl", ttl])
    out = r.stdout + r.stderr
    m = re.search(r"^url\s+(https?://\S+)", out, re.M)
    url = m.group(1) if m else ""
    m = re.search(r"^(?:name|env|environment)\s+(\S+)", out, re.M)
    env = m.group(1) if m else f"{REPO_NAME}-dev-{as_name}"[:62]
    if not url:
        r = sh(["standee", "url", env], check=False)
        url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    if not url:
        die(f"standee up gave no URL for {env}")
    return env, url


def preflight_login(url: str, emails: tuple[str, ...] = (QA_EMAIL, QA_EMPTY_EMAIL), password: str = "") -> None:
    """Refuse to spend anything on a stack nobody can sign in to.

    A walker that cannot get past the login page produces a walk about the login page: three of them ran
    on b002 against an environment whose database was empty, cost $0.77, and would have fed a report and
    a bet built on nothing. The credentials are the first thing the walkers use, so they are the first
    thing we check -- one POST, no model, before a run exists. An environment that is up but unusable is
    a harness failure, and a harness failure must look like one.
    """
    endpoint = url.rstrip("/") + "/api/auth/login"
    for email in emails:
        body = json.dumps({"email": email, "password": password or QA_PASSWORD}).encode()
        req = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    if resp.status < 400:
                        break
                    detail = f"HTTP {resp.status}"
            except urllib.error.HTTPError as e:
                # 429 is the endpoint working and rate-limiting us; anything else is a real answer.
                if e.code == 429 and attempt < 2:
                    time.sleep(20)
                    continue
                detail = f"HTTP {e.code}: {(e.read().decode(errors='replace') or '').strip()[:200]}"
            except urllib.error.URLError as e:
                detail = str(e.reason)
            die(f"{email} cannot sign in at {endpoint} ({detail}). The stack is up but unusable — "
                f"most likely unseeded. Check `standee status` and run `standee seed <env>`; "
                f"nothing was dispatched and nothing was spent.")
    log(f"preflight: {len(emails)} accounts can sign in")


def wait_for_url(url: str, timeout: float = 240.0) -> None:
    """Block until the URL answers over https. The gateway issues the
    certificate on the first request, which can take half a minute; the
    first walk of the first run hit that window and reported the product
    unreachable."""
    deadline = time.monotonic() + timeout
    probe = url.rstrip("/") + "/api/health"
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(probe, timeout=10) as resp:
                if resp.status < 500:
                    log(f"{url} is serving ({resp.status})")
                    return
                last = f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            if e.code < 500:
                log(f"{url} is serving ({e.code})")
                return
            last = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = str(getattr(e, "reason", e))
        time.sleep(5)
    die(f"{url} did not come up in {timeout:.0f}s (last: {last})")


def standee_down(env: str) -> None:
    sh(["standee", "down", env, "--volumes", "--images"], check=False)


def ensure_qa_password() -> str:
    """The live QA account's password: generated once, kept in prod's env file.

    The dev password is public knowledge — it is written in the seed module —
    and the live server is on the open internet, so the seed refuses the default
    there. The loop makes one secret instead, stores it where only the owner and
    the container can read it, and never prints it.
    """
    text = PROD_ENV_FILE.read_text() if PROD_ENV_FILE.exists() else ""
    for line in text.splitlines():
        if line.startswith("ROLLCALL_QA_PASSWORD="):
            return line.split("=", 1)[1].strip()
    import secrets
    pw = secrets.token_urlsafe(24)
    with PROD_ENV_FILE.open("a") as f:
        if text and not text.endswith("\n"):
            f.write("\n")
        f.write("# The QA tenant's login on the live server (paper adapters only; see tenancy/seed.py).\n")
        f.write(f"ROLLCALL_QA_PASSWORD={pw}\n")
    os.chmod(PROD_ENV_FILE, 0o600)
    log(f"generated the live QA password into {PROD_ENV_FILE} (not shown)")
    return pw


def ensure_qa_on_prod() -> bool:
    """Create or refresh the QA tenant on the live server.

    Paper by construction: the seed refuses any config that could reach a
    broker, on every server. The password comes from the container's own
    environment, so it never appears in a command line.
    """
    r = sh(["docker", "exec", PROD_CONTAINER, "rollcall", "qa", "ensure", "--live"], check=False)
    if r.returncode != 0:
        log("could not seed the QA tenant on prod — measure will do signed-in checks on the branch stack")
        return False
    return True


# --------------------------------------------------------------------- github --
#
# The GitHub side of shipping is four HTTP calls, so it is four HTTP calls: no
# `gh` binary on the PATH, no login state on this host, nothing to break when
# systemd hands the unit a minimal environment (which it did, on the first
# run). The credential is the one the github MCP server uses, resolved by the
# same contract it publishes (agent-tools lib/github-mcp.mjs): identity to
# token, first hit wins. `gh auth token` is the one source deliberately left
# out -- borrowing gh's login would be the same dependency wearing a hat.

GH_IDENTITY = os.environ.get("EPD_GH_IDENTITY", "epd-loop")
AGENT_TOOLS_HOME = Path(os.environ.get("AGENT_TOOLS_HOME", Path.home() / ".config" / "agent-tools"))


def github_token() -> str:
    ident = GH_IDENTITY
    env_key = "GITHUB_TOKEN_" + re.sub(r"[^A-Z0-9]", "_", ident.upper())
    if os.environ.get(env_key, "").strip():
        return os.environ[env_key].strip()
    token_file = AGENT_TOOLS_HOME / "github" / "identities" / ident / "token"
    if token_file.exists():
        return token_file.read_text().strip()
    die(f"no GitHub credential for identity {ident!r}. Put a token in {token_file} "
        f"(chmod 600) or set {env_key}. This is the same identity the github MCP server "
        f"resolves, so one file serves both.")
    raise AssertionError("unreachable")


def github(method: str, path: str, body: dict | None = None, allow: tuple[int, ...] = ()):
    """One GitHub REST call. Returns the parsed body (a dict, or a list for the
    list endpoints). A status in `allow` comes back as {"_status", "_error"}
    instead of killing the run -- that is how "the PR already exists" is a
    fact to act on rather than a failure."""
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {github_token()}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json",
                 "User-Agent": "epd-loop"},
    )
    log(f"$ github {method} {path}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        if e.code in allow:
            return {"_status": e.code, "_error": detail}
        die(f"github {method} {path} → {e.code}: {detail}")
        raise AssertionError("unreachable") from e


def open_or_find_pr(branch: str, title: str, body: str) -> dict:
    """The PR for this branch, creating it if it is not there yet. A re-run of
    ship must not fail because the first attempt already got this far."""
    owner, repo = GH_REPO.split("/", 1)
    pr = github("POST", f"/repos/{owner}/{repo}/pulls",
                {"title": title, "body": body, "head": branch, "base": BASE_BRANCH},
                allow=(422,))
    if "_error" not in pr:
        return pr
    log(f"a PR for {branch} exists already; using it")
    existing = github("GET", f"/repos/{owner}/{repo}/pulls?head={owner}:{branch}&state=open")
    if isinstance(existing, list) and existing:
        return existing[0]
    die(f"POST /pulls refused ({pr['_error'][:200]}) and no open PR for {branch} was found")
    raise AssertionError("unreachable")


# ----------------------------------------------------------------- screenshots --
#
# A change the QA browser could see is shown on the pull request, not only
# described. The verify agent screenshots each page the change is on, into the
# browser's output directory (docker-compose.yml bind-mounts it under the
# workspaces tree, so the files are on this side of the wall); ship moves them
# into the bet directory, puts them on an orphan branch of the product repo and
# embeds them in the PR body. An orphan branch rather than the PR branch, so the
# product's history never carries the pipeline's pictures; the links pin the
# commit sha, so a later bet's upload cannot move an older PR's images.

BROWSER_OUTPUT = WORKSPACES / "browser-output"
SHOTS_BRANCH = os.environ.get("EPD_SHOTS_BRANCH", "epd-screenshots")
SHOT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.png$")


def as_list(value) -> list:
    """A list an agent produced, whether it arrived as one or as its JSON text; anything else is []."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def collect_screenshots(bdir: Path, prefix: str, listed) -> list[dict]:
    """The verify run's screenshots, moved into ``<bet>/screenshots/``: [{page, shows, file, path}].

    The files are the truth -- whatever the browser wrote under the prefix the agent was told to use
    -- and the agent's own list adds a caption to each. A model-written name is only ever a basename
    looked up in the output directory, never a path. Moving (not copying) makes a re-run of ship see
    the same set: the bet directory is the durable record, the output directory is scratch.

    The list is the last verify round's, and so is the set that goes on the PR: a build sent back
    and fixed is judged again on the new commit, and the pictures of the commit being shipped are
    the ones the owner should see. A file on disk the last round did not list is an earlier round's
    (the browser names a page's picture the same way each round, so a page the later round shot
    again is already replaced) and is kept under ``earlier/`` for the record, off the PR. With no
    list at all -- an older verify, or one whose reply lost it -- every file counts, captioned by
    its name.
    """
    dest = bdir / "screenshots"
    if prefix and BROWSER_OUTPUT.is_dir():
        for src in sorted(BROWSER_OUTPUT.glob(f"{prefix}-*.png")):
            if src.is_file() and src.stat().st_size > 0 and SHOT_NAME.match(src.name):
                dest.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest / src.name))
    if not dest.is_dir():
        return []
    captions: dict[str, dict] = {}
    for item in as_list(listed):
        if isinstance(item, dict) and item.get("file"):
            captions[Path(str(item["file"])).name] = item
    out = []
    for p in sorted(dest.glob("*.png")):
        if captions and p.name not in captions:
            earlier = dest / "earlier"
            earlier.mkdir(exist_ok=True)
            shutil.move(str(p), str(earlier / p.name))
            log(f"   screenshot {p.name} is from an earlier round; kept under earlier/, not on the PR")
            continue
        cap = captions.get(p.name, {})
        stem = p.name[len(prefix) + 1:-4] if prefix and p.name.startswith(prefix + "-") else p.stem
        out.append({"page": str(cap.get("page") or stem.replace("-", " ")).strip(),
                    "shows": str(cap.get("shows") or "").strip(), "file": p.name, "path": str(p)})
    return out


def threshold_walk_md(checks) -> str:
    """The PR-body section for QA's clause-by-clause walk of the threshold ("" when there is none)."""
    rows = [c for c in as_list(checks) if isinstance(c, dict) and c.get("clause")]
    if not rows:
        return ""
    mark = {"met": "✓", "unmet": "✗", "unverified": "?"}
    lines = ["## What QA checked", "", "Each promise this bet made, and whether QA saw it happen:", ""]
    for c in rows:
        status = str(c.get("status") or "").strip().lower()
        evidence = str(c.get("evidence") or "").strip()
        # The mark says it; repeating the word after it ("✓ **met** — …") is the same thing twice.
        # "unverified" is the exception: it is not a worse ✓ but a different thing, and it reads as
        # a pass to anyone skimming the column of marks.
        tail = " (nothing in the app reached this)" if status == "unverified" else ""
        lines.append(f"- {mark.get(status, '?')} {str(c['clause']).strip()}{tail}"
                     + (f"  \n  {evidence}" if evidence else ""))
    unverified = [c for c in rows if str(c.get("status") or "").strip().lower() == "unverified"]
    if unverified:
        lines += ["", f"Nothing in the app reached {len(unverified)} of these, so QA could not say either "
                      "way. Those are yours to judge."]
    return "\n".join(lines) + "\n"


def publish_screenshots(bet_id: str, shots: list[dict]) -> str:
    """Commit the screenshots to the repo's screenshot branch; return the PR-body section ("" if none).

    Four to six REST calls through the Git Data API: blobs, a tree on top of the branch's tree (or a
    fresh one), a commit, the ref. The first upload creates the branch as a root commit -- nothing of
    the product's history behind it. Image links are ``blob/<sha>/...?raw=true``, which GitHub serves
    to anyone who can see the repository, private or not.
    """
    if not shots:
        return ""
    owner, repo = GH_REPO.split("/", 1)
    base = f"/repos/{owner}/{repo}"
    ref = github("GET", f"{base}/git/ref/heads/{SHOTS_BRANCH}", allow=(404,))
    parent = None if "_error" in ref else ref["object"]["sha"]
    entries = []
    for s in shots:
        blob = github("POST", f"{base}/git/blobs",
                      {"content": base64.b64encode(Path(s["path"]).read_bytes()).decode(), "encoding": "base64"})
        entries.append({"path": f"{bet_id}/{s['file']}", "mode": "100644", "type": "blob", "sha": blob["sha"]})
    tree_body: dict = {"tree": entries}
    if parent:
        tree_body["base_tree"] = github("GET", f"{base}/git/commits/{parent}")["tree"]["sha"]
    tree = github("POST", f"{base}/git/trees", tree_body)
    commit = github("POST", f"{base}/git/commits",
                    {"message": f"{bet_id}: {len(shots)} screenshot(s) from the QA browser",
                     "tree": tree["sha"], "parents": [parent] if parent else []})
    sha = commit["sha"]
    if parent:
        github("PATCH", f"{base}/git/refs/heads/{SHOTS_BRANCH}", {"sha": sha, "force": False})
    else:
        github("POST", f"{base}/git/refs", {"ref": f"refs/heads/{SHOTS_BRANCH}", "sha": sha})
    lines = ["## Screenshots", "",
             f"What the QA browser saw on this branch's dev stack (`{SHOTS_BRANCH}` @ {sha[:7]}).", ""]
    for s in shots:
        url = f"https://github.com/{owner}/{repo}/blob/{sha}/{bet_id}/{s['file']}?raw=true"
        caption = s["page"] + (f" — {s['shows']}" if s.get("shows") else "")
        lines += [f"**{caption}**", "", f"![{s['page']}]({url})", ""]
    log(f"screenshots: {len(shots)} on {SHOTS_BRANCH} @ {sha[:7]}")
    return "\n".join(lines)


def trust_main_clone() -> None:
    """Let this user's git read the pipeline's clone, which the container owns.

    `safe.directory` is *protected* configuration: git reads it from the
    system and global files only, and ignores it from `-c` on the command
    line and from the repository's own config -- silently, which is how the
    first ship died with "detected dubious ownership" despite passing
    `-c safe.directory=*`. So the entry goes in the global file, once, for
    this one path: our own clone, written by our own container.
    """
    have = subprocess.run(["git", "config", "--global", "--get-all", "safe.directory"],
                          text=True, capture_output=True).stdout.split("\n")
    # Both: the working tree for ordinary commands, and the gitdir itself,
    # which is what git resolves to when the clone is used as a remote.
    for want in (str(MAIN_CLONE), str(MAIN_CLONE / ".git")):
        if want in have:
            continue
        sh(["git", "config", "--global", "--add", "safe.directory", want])
        log(f"trusted {want} in ~/.gitconfig (the pipeline's clone, owned by the container's user)")


def deploy_prod(ref: str) -> None:
    """Stand the live product up again at `ref`, backup first.

    `standee up` on an existing environment updates it in place: same name,
    same URL, same host port, previous images kept for `standee rollback`.

    Deliberately WITHOUT --ref. That flag builds from `git archive` into
    ~/.standee/envs/<env>/src/<short>/ and runs compose there, and this
    project's compose file is written against its own directory:

        volumes:
          - ./var:/data          # rollcall.db -- every order ever placed
        env_file:
          - path: .env           # master key, session secret, broker keys
            required: false

    From an export, `./var` is a new empty directory and `.env` does not
    exist at all (it is gitignored, so `git archive` omits it): the live
    product would come up with an empty database and no master key. So the
    deploy runs from the checkout, which the caller has already
    fast-forwarded to the merged commit -- the tree IS the commit, asserted
    here rather than assumed.
    """
    head = sh(["git", "rev-parse", "HEAD"], cwd=REPO_CHECKOUT).stdout.strip()
    if head != ref:
        die(f"{REPO_CHECKOUT} is at {head[:12]}, not the commit being shipped ({ref[:12]})")
    if sh(["git", "status", "--porcelain"], cwd=REPO_CHECKOUT).stdout.strip():
        die(f"{REPO_CHECKOUT} has uncommitted changes; the live product is built from this tree")
    ensure_qa_password()  # before `up`: the container reads the env file at start
    sh(["standee", "backup", PROD_ENV])
    sh(["standee", "up", str(REPO_CHECKOUT), "--tier", "prod", "--host-port", PROD_HOST_PORT, "--wait"])
    assert_prod_kept_its_data()
    wait_for_url(PROD_URL)


def assert_prod_kept_its_data() -> None:
    """The live container must still be mounting the owner's database.

    Cheap, and it tests the exact way a deploy could quietly destroy the
    product: a compose run from the wrong directory gives every relative
    bind mount a fresh empty one instead.
    """
    want = str((REPO_CHECKOUT / "var").resolve())
    r = sh(["docker", "inspect", PROD_CONTAINER, "--format",
            "{{range .Mounts}}{{.Source}}->{{.Destination}} {{end}}"], check=False)
    mounts = r.stdout.strip()
    if f"{want}->/data" not in mounts:
        die(f"the live container is not mounting {want} at /data (mounts: {mounts or 'none'}). "
            f"Its database would be empty -- `standee rollback {PROD_ENV}`.")
    log(f"live database still mounted from {want}")


# ------------------------------------------------------------------- state --

def ledger_rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    lines = LEDGER.read_text().splitlines()
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split("\t")
        cells += [""] * (len(LEDGER_COLUMNS) - len(cells))
        rows.append(dict(zip(LEDGER_COLUMNS, cells, strict=False)))
    return rows


def ledger_write(rows: list[dict]) -> None:
    lines = ["\t".join(LEDGER_COLUMNS)]
    for r in rows:
        lines.append("\t".join(str(r.get(c, "")).replace("\t", " ").replace("\n", " ") for c in LEDGER_COLUMNS))
    write(LEDGER, "\n".join(lines) + "\n")


def ledger_upsert(bet_id: str, **fields) -> None:
    rows = ledger_rows()
    for r in rows:
        if r["bet_id"] == bet_id:
            r.update({k: v for k, v in fields.items() if v is not None})
            break
    else:
        rows.append({"bet_id": bet_id, "date": dt.date.today().isoformat(), **fields})
    ledger_write(rows)


def state_path(bet_id: str) -> Path:
    return BETS_DIR / bet_id / "state.json"


def load_state(bet_id: str) -> dict:
    p = state_path(bet_id)
    return json.loads(p.read_text()) if p.exists() else {"bet_id": bet_id, "status": "new", "stages": {}}


def save_state(st: dict) -> None:
    write(state_path(st["bet_id"]), json.dumps(st, indent=2))
    ledger_upsert(st["bet_id"], status=st["status"])


def bet_text(bdir: Path) -> str:
    """The pitch plus the owner's decision, as one document."""
    return read(bdir / "bet.md").rstrip() + "\n\n" + read(bdir / "decision.md")


def refresh_main() -> str:
    """Bring the pipeline's clone to origin/<base>. Runs inside the temper
    container: the clone is its user's, and the deploy key is mounted there.
    Returns the commit it is at."""
    script = f"""set -e
export GIT_TERMINAL_PROMPT=0
KEY=$(mktemp); trap 'rm -f "$KEY"' EXIT
install -m 600 /app/github-deploy/id_ed25519 "$KEY"
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o UserKnownHostsFile=/app/github-deploy/known_hosts -o StrictHostKeyChecking=yes -o BatchMode=yes"
cd {cpath(MAIN_CLONE)}
git fetch -q --prune origin
git checkout -q -B {BASE_BRANCH} origin/{BASE_BRANCH}
git rev-parse HEAD
"""
    r = sh(["docker", "exec", "-i", SERVER_CONTAINER, "sh", "-c", script])
    head = r.stdout.strip().splitlines()[-1]
    log(f"{MAIN_CLONE} at {head[:12]} (origin/{BASE_BRANCH})")
    return head


def open_bets() -> list[str]:
    """The bets being worked on, oldest first: picked from the backlog and not finished. Candidates
    waiting for the owner's word are not open; they are on file. More than one is open when the
    loop built the next while an earlier one's PR waited at the gate."""
    return [r["bet_id"] for r in ledger_rows() if r["status"] not in TERMINAL and r["status"] not in WAITING]


def open_bet() -> str | None:
    """The latest open bet: what `resume`, `next` and `stage` act on unless told which."""
    bets = open_bets()
    return bets[-1] if bets else None


def waiting_bets() -> list[str]:
    """Candidates on file that the owner has neither listed in the backlog nor rejected."""
    return [r["bet_id"] for r in ledger_rows() if r["status"] in WAITING]


def new_bet_ids(n: int) -> list[str]:
    """The next `n` bet ids, after everything on the ledger or on disk."""
    ids, k = [], len(ledger_rows()) + 1
    while len(ids) < n:
        if not (BETS_DIR / f"b{k:03d}").exists():
            ids.append(f"b{k:03d}")
        k += 1
    return ids


def previous_bet_id(exclude: str = "") -> str | None:
    """The most recently measured bet: the one whose outcome was written last.

    By the outcome file's time, not by position on the ledger: ids are handed out five at a time
    now and taken in the owner's order, so the last row is not the last thing that happened.
    """
    done = [r["bet_id"] for r in ledger_rows()
            if r["bet_id"] != exclude and r["status"] in TERMINAL - {"rejected", "closed", "changes_requested"}]
    with_outcome = [(b, (BETS_DIR / b / "outcome.md").stat().st_mtime) for b in done if (BETS_DIR / b / "outcome.md").exists()]
    return max(with_outcome, key=lambda t: t[1])[0] if with_outcome else None


def previous_outcome(exclude: str = "") -> str:
    """The outcome of the most recently measured bet."""
    prev = previous_bet_id(exclude)
    return read(BETS_DIR / prev / "outcome.md") if prev else ""


#: Sections of an outcome that describe work the last bet did not finish. The
#: bet agent gets these verbatim: a ledger row saying "kept" is not enough to
#: carry "this shipped but nobody ever saw it run" into the next decision.
UNFINISHED_SECTIONS = ("Threshold", "Unverified", "Was this the right threshold", "For the next iteration")


def unfinished_business(exclude: str = "") -> str:
    """What the last measured bet left undone, in its own words.

    b001 shipped both halves of an either/or invariant and could only walk
    one: the measurement said so in prose, the ledger said "kept", and the
    agent choosing the next bet saw only the ledger. This is the repair.
    """
    prev = previous_bet_id(exclude)
    if not prev:
        return ""
    text = read(BETS_DIR / prev / "outcome.md")
    if not text:
        return ""
    wanted, keep, out = {s.lower() for s in UNFINISHED_SECTIONS}, False, [f"From bet {prev}:", ""]
    for line in text.splitlines():
        if line.startswith("## "):
            keep = line[3:].strip().rstrip(":").lower() in wanted
        if keep:
            out.append(line)
    st = load_state(prev)
    m = st["stages"].get("measure") or st["stages"].get("loop") or {}
    if m.get("vacuous_criteria"):
        out += ["", f"({m['vacuous_criteria']} of its success criteria were vacuous: the situation each "
                    f"described never arose on the measured build, so nothing tested them.)"]
    return "\n".join(out).strip()


# ---------------------------------------------------------------- proposal --
#
# One proposal is one round: a dev stack of main, three walks, a report, and one to five candidate
# bets written into slots made ahead of the run. The round's record (reports/<round>/round.json)
# is this driver's; the report and the pitches are the agents'. Nothing in a round is a decision:
# the owner decides afterwards, on disk, by listing bets in backlog.md.

def round_ids() -> list[str]:
    return sorted(p.name for p in REPORTS_DIR.glob("r[0-9][0-9][0-9]") if p.is_dir())


def round_path(round_id: str) -> Path:
    return REPORTS_DIR / round_id / "round.json"


def load_round(round_id: str) -> dict:
    p = round_path(round_id)
    return json.loads(p.read_text()) if p.exists() else {"round_id": round_id}


def save_round(rd: dict) -> None:
    write(round_path(rd["round_id"]), json.dumps(rd, indent=2, default=str))


def new_round_id() -> str:
    ids = round_ids()
    n = int(ids[-1][1:]) + 1 if ids else 1
    return f"r{n:03d}"


def open_rounds() -> list[str]:
    """Proposal runs submitted and not yet collected (nor given up on), oldest first. Usually one;
    `propose --count N` puts N out side by side."""
    out = []
    for rid in round_ids():
        rd = load_round(rid)
        if rd.get("_run_id") and not rd.get("_collected") and not rd.get("_failed"):
            out.append(rid)
    return out


def open_round() -> str | None:
    """The latest proposal run submitted and not yet collected (and not given up on)."""
    rounds = open_rounds()
    return rounds[-1] if rounds else None


def round_of(bet_id: str) -> str:
    """Which proposal round this bet came out of.

    bet.json is the obvious place and the first one asked, but it is not the only record and
    for a while it was not a reliable one: the ship stage used to rewrite that file from the
    four words it had, dropping `round` from every bet it shipped. state.json keeps the same
    fact in two places and no stage overwrites it, so it is asked next. Bets proposed before
    rounds existed have no round at all, and say so with an empty string."""
    bet = json.loads(read(BETS_DIR / bet_id / "bet.json") or "{}")
    if bet.get("round"):
        return str(bet["round"])
    st = json.loads(read(BETS_DIR / bet_id / "state.json") or "{}")
    return str(st.get("round") or (st.get("stages", {}).get("bet") or {}).get("round") or "")


def report_path_for(bet_id: str) -> Path:
    """The report a bet came out of: its round's, or (bets before rounds) the one beside it.

    Returns the path that should hold the report, whether or not it does; callers that are
    about to spend a stage on it should check. Where both are possible, an existing file wins
    over a nominal one -- a bet whose round record went missing still has its own copy."""
    beside = BETS_DIR / bet_id / "report.md"
    rnd = round_of(bet_id)
    if rnd:
        of_round = REPORTS_DIR / rnd / "report.md"
        if of_round.exists() or not beside.exists():
            return of_round
    return beside


def pitch_fields(path: Path) -> dict:
    """Title and invariant as they stand in the pitch. The owner edits the file; this is how the
    edit reaches the record (decision.md, the PR body) without a second place to type it."""
    text = read(path)
    out: dict = {}
    m = re.search(r"^#\s+Bet\s+\S+:\s*(.+?)\s*$", text, re.M) or re.search(r"^#\s+(.+?)\s*$", text, re.M)
    if m:
        out["title"] = m.group(1).strip()
    m = re.search(r"^##\s+Invariant\s*\n(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if m:
        body = " ".join(ln.strip() for ln in m.group(1).strip().splitlines() if ln.strip())
        if body:
            out["invariant"] = body
    return out


def cmd_propose(keep: bool, wait: bool, alongside: bool = False, focus: str = "") -> None:
    """One proposal, as one temper run: the walks, the report, one to five candidates. No gate.

    Two things stay on this side, because neither is part of the proposal's reasoning: the stack
    the walkers need (the ssh key that can stand one up belongs to the host) and the slot
    directories the pitches go into (the container's user cannot make a directory the host can
    then write its records into). `collect` puts the candidates on the ledger when the run is done;
    the owner's list is backlog.md.

    `alongside`: another proposal may be out, and this one runs beside it (`propose --count`).
    Each round has its own stack, slots and run, so nothing is shared but the inputs.

    `focus`: the part of the product this round's walkers stay in (the personas are designed
    inside it). Empty: wherever the goals and the last outcome send them.
    """
    focus = " ".join(focus.split())
    require_tools("standee", "docker", "git", "ssh")
    if open_round() and not alongside:
        die(f"proposal {open_round()} is still out; `collect` it first")
    round_id = new_round_id()
    rdir = REPORTS_DIR / round_id
    mkdir_shared(rdir)
    slots = new_bet_ids(SLOTS)
    for b in slots:
        mkdir_shared(BETS_DIR / b)
    head = refresh_main()
    env, url = standee_up(MAIN_CLONE, f"epd-{round_id}", "12h")
    rd = {"round_id": round_id, "env": env, "url": url, "base_head": head, "slots": slots, "focus": focus,
          "_launched": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
    save_round(rd)
    wait_for_url(url)
    preflight_login(url)
    inputs = {
        "round_id": round_id,
        "report_path": cpath(rdir / "report.md"),
        "bets_dir": cpath(BETS_DIR),
        "slots": " ".join(slots),
        "goals": read(LOOP_DIR / "goals.md"),
        "profile": read(LOOP_DIR / "profile.md"),
        "last_outcome": previous_outcome(),
        "unfinished": unfinished_business(),
        "bets_tsv": read(LEDGER),
        "app_url": url,
        # The walkers seed their own tenants in this stack (one each, or they move each other's book),
        # so they need the name standee knows it by, not just its URL.
        "env_name": env,
        "password": QA_PASSWORD,
        "focus": focus,
    }
    log(f"== {round_id}: proposal (walks, report, up to {SLOTS} bets into {', '.join(slots)}) ==")
    if focus:
        log(f"   focus: {focus}")
    if wait:
        out = run_workflow("epd_propose", inputs, workspace=LOOP_WORKSPACE, timeout=2 * 3600)
        finish_round(rd, out, keep)
        return
    rid = post_run("epd_propose", inputs, LOOP_WORKSPACE)
    rd["_run_id"] = rid
    save_round(rd)
    log(f"epd_propose → run {rid}")
    log("   it is temper's now; `epd_loop.py collect` puts the candidates on the ledger once it is done")


def cmd_propose_many(count: int | None, keep: bool, focuses: list[str] | tuple[str, ...] = ()) -> None:
    """`count` proposals side by side, each with its own stack, slots and run; returns once all
    are submitted.

    `run --propose` is a turn of the loop: it collects first, and a proposal still out or a bet
    that failed stops it. This is the owner asking for more candidates now, whatever else is out
    -- a failed bet makes the product's friction no less worth finding. The rounds do not see each
    other: they start from the same goals, ledger and last outcome, so without a focus their
    walkers go to the same pages and their candidates overlap. `focuses` gives round i the i-th
    one (rounds past the last get none); `count` defaults to one round per focus.
    """
    focuses = [f for f in (" ".join(f.split()) for f in focuses) if f]
    if count is None:
        count = len(focuses) or 1
    if count < 1:
        die("--count must be 1 or more")
    if len(focuses) > count:
        die(f"{len(focuses)} --focus for {count} round(s): one focus per round at most")
    for i in range(count):
        cmd_propose(keep, wait=False, alongside=True, focus=focuses[i] if i < len(focuses) else "")


def collect_round(round_id: str, keep: bool) -> bool:
    """Record what a proposal run produced. True when it was collected (now or before)."""
    rd = load_round(round_id)
    if rd.get("_collected"):
        return True
    rid = rd["_run_id"]
    info = get_run(rid)
    status = info.get("status")
    if status in ("running", "pending"):
        running = [n["name"] for n in info.get("nodes") or [] if n.get("status") == "running"]
        log(f"{round_id}: proposal run {rid[:8]} is still {status} (running={running}, "
            f"cost=${info.get('total_cost_usd') or 0:.2f}); nothing to collect yet")
        return False
    if status != "completed":
        why = "rate limited: the work is fine, the account is not" if rate_limited(rid) else info.get("error_message")
        rd["_failed"] = {"status": status, "why": why, "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
        prune_slots(rd)
        save_round(rd)
        if rd.get("env") and not keep:
            standee_down(rd["env"])
        die(f"{round_id}: proposal run {rid} ended {status}: {why}. `run --propose` starts a new one.")
    out = {k: unstr(v) for k, v in (info.get("workflow_output") or {}).items()}
    out["_versions"] = config_versions("epd_propose")
    out["_run_id"] = rid
    out["_launched"] = rd.get("_launched")
    out["_cost_usd"] = info.get("total_cost_usd")
    out["_duration_s"] = info.get("duration_seconds")
    finish_round(rd, out, keep)
    return True


def prune_slots(rd: dict) -> list[str]:
    """Remove the slots the agent left empty; return the ones it filled, in slot order."""
    filled = []
    for b in rd.get("slots") or []:
        d = BETS_DIR / b
        if (d / "bet.md").exists():
            filled.append(b)
        elif d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return filled


def finish_round(rd: dict, out: dict, keep: bool) -> None:
    """The bookkeeping after a proposal: the walks and report on disk, one record per candidate,
    the ledger rows (`proposed`), the stack down. Then the owner's turn."""
    round_id = rd["round_id"]
    rdir = REPORTS_DIR / round_id
    for i in (1, 2, 3):
        if out.get(f"walk_{i}"):
            write(rdir / f"walk_{i}.md", str(out[f"walk_{i}"]))
    if not (rdir / "report.md").exists():
        die(f"epd_propose finished but wrote no report.md in {rdir}")
    filled = prune_slots(rd)
    listed = {c.get("bet_id"): c for c in (out.get("candidates") or []) if isinstance(c, dict)}
    for b in listed:
        if b not in filled:
            log(f"note: the agent listed {b} but wrote no {BETS_DIR / b / 'bet.md'}; dropped")
    at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    candidates = []
    for rank, b in enumerate(filled, 1):
        c = dict(listed.get(b) or {})
        c.update(pitch_fields(BETS_DIR / b / "bet.md"))  # the pitch is the record; the JSON is its summary
        c.update({"bet_id": b, "rank": c.get("rank") or rank, "round": round_id, "at": at,
                  "_run_id": out.get("_run_id"), "_versions": out.get("_versions")})
        write(BETS_DIR / b / "bet.json", json.dumps(c, indent=2, default=str))
        st = {"bet_id": b, "status": "proposed", "round": round_id, "stages": {"bet": c}}
        save_state(st)
        ledger_upsert(b, title=c.get("title") or "", threshold=c.get("threshold") or "", status="proposed")
        candidates.append(c)
    rd.update({k: v for k, v in out.items() if not k.startswith("walk_") and k != "candidates"})
    rd["candidates"] = [c["bet_id"] for c in candidates]
    rd["_collected"] = at
    save_round(rd)
    if rd.get("env") and not keep:
        standee_down(rd["env"])
    print()
    print(f"=== {round_id}: {len(candidates)} candidate(s) from {rdir / 'report.md'}")
    if rd.get("focus"):
        print(f"Focus: {rd['focus']}")
    print(f"Report: {out.get('report_summary')}")
    for c in candidates:
        print()
        print(f"{c['bet_id']}  {c.get('title')}")
        print(f"    invariant: {c.get('invariant')}")
        print(f"    threshold: {c.get('threshold')}")
        print(f"    appetite:  {c.get('appetite_hours')} h   why this rank: {c.get('why')}")
        print(f"    pitch:     {BETS_DIR / c['bet_id'] / 'bet.md'}")
    for q in out.get("left_out") or []:
        print(f"left out:  {q}")
    for q in out.get("questions_for_owner") or []:
        print(f"question:  {q}")
    print()
    print("YOUR TURN. Read the pitches, edit the ones worth building, and list them in order in")
    print(f"    {BACKLOG}")
    print("(one id per line, top first; or `epd_loop.py approve <id>` to append one). The next `run`")
    print("takes the top one. `epd_loop.py reject <id> --why '...'` turns one down for good.")


# ----------------------------------------------------------------- backlog --
#
# The owner's list: one bet id per line, top first, whatever else they like on the line. It is the
# only input the loop takes from a person between proposals, and it is a file rather than a gate
# so the owner can do it in one sitting, in any editor, and change their mind before the loop gets
# there. A line is the owner's signature on the pitch as it stands in bet.md when the loop picks
# the bet up: the invariant is re-read from the file at that moment.

BACKLOG_LINE = re.compile(r"^\s*(?:[-*]|\d+[.)])?\s*(b\d{3})\b(.*)$")


def ensure_backlog() -> None:
    if not BACKLOG.exists():
        write(BACKLOG, BACKLOG_HEADER)


def backlog_lines() -> list[tuple[str, str, str, str]]:
    """(section, bet_id, note, mark) per bet line, in file order.

    Sections are the `##` headings: queue, declined, or other (a heading of the owner's own, such
    as `## Later`, whose lines the loop leaves alone). Lines above any `##` heading are the queue.
    `mark` is what the loop appended when it acted on the line; empty means it has not.
    """
    section = "queue"
    out = []
    for line in read(BACKLOG).splitlines():
        if line.startswith("## "):
            h = line[3:].strip().lower()
            section = "declined" if h.startswith("declin") else "queue" if h.startswith("queue") else "other"
            continue
        m = BACKLOG_LINE.match(line)
        if not m or section == "other":
            continue
        rest = m.group(2)
        note, mark = rest.rsplit(BACKLOG_MARK, 1) if BACKLOG_MARK in rest else (rest, "")
        out.append((section, m.group(1), note.strip(" -:\u2014\t"), mark.strip()))
    return out


def backlog() -> list[tuple[str, str]]:
    """(bet_id, note) per queue line the loop has not acted on, top first."""
    return [(b, note) for section, b, note, mark in backlog_lines() if section == "queue" and not mark]


def backlog_mark(section: str, bet_id: str, what: str) -> None:
    """Append `→ what` to the first unmarked line for bet_id in the section: the loop's receipt."""
    lines = read(BACKLOG).splitlines()
    current = "queue"
    for i, line in enumerate(lines):
        if line.startswith("## "):
            h = line[3:].strip().lower()
            current = "declined" if h.startswith("declin") else "queue" if h.startswith("queue") else "other"
            continue
        m = BACKLOG_LINE.match(line)
        if current == section and m and m.group(1) == bet_id and BACKLOG_MARK not in line:
            lines[i] = line.rstrip() + BACKLOG_MARK + what
            write(BACKLOG, "\n".join(lines) + "\n")
            return


def backlog_append(section: str, line: str) -> None:
    """Add a line at the end of a section, creating the heading at the end of the file if need be."""
    lines = read(BACKLOG).splitlines()
    heading = "## Declined" if section == "declined" else "## Queue"
    start = next((i for i, ln in enumerate(lines) if ln.startswith("## ") and
                  ln[3:].strip().lower().startswith("declin" if section == "declined" else "queue")), None)
    if start is None:
        lines += ["", heading, "", line]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        lines[end:end] = [line]
    write(BACKLOG, "\n".join(lines) + "\n")


def stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


def record_declines() -> None:
    """Declined lines the owner wrote that the loop has not recorded yet become rejections, with
    the line's text as the reason. Each gets its receipt; a line the loop cannot act on stays
    unmarked and is said so, every time, until the owner changes it."""
    for section, bet_id, why, mark in backlog_lines():
        if section != "declined" or mark:
            continue
        if not (BETS_DIR / bet_id / "bet.md").exists():
            log(f"Declined names {bet_id}, which has no pitch on file; nothing recorded")
            continue
        status = load_state(bet_id)["status"]
        if status == "rejected":
            backlog_mark("declined", bet_id, f"already declined; noted {stamp()}")
            continue
        if status not in WAITING:
            log(f"Declined names {bet_id}, which is {status}; a line does not stop a bet under way -- "
                f"`reject {bet_id} --why ...` once its run is done")
            continue
        reject(bet_id, why or "declined in backlog.md (no reason given)", where="backlog")


def pick_bet() -> str | None:
    """Take the top waiting bet from the queue and make it the open one. None if nothing is waiting.

    This is where the owner's approval becomes a record: the line gets its receipt, decision.md
    is written with the invariant as the pitch has it now, and the decision is logged against the
    configs that proposed it. A line for a bet that is not waiting is marked and skipped (the
    file keeps it); a line for a declined bet reopens it.
    """
    picked: tuple[str, str] | None = None
    for bet_id, note in backlog():
        if not (BETS_DIR / bet_id / "bet.md").exists():
            log(f"Queue names {bet_id}, which has no pitch on file; skipped")
            backlog_mark("queue", bet_id, f"skipped {stamp()}: no pitch on file")
            continue
        st = load_state(bet_id)
        if st["status"] == "rejected":
            log(f"{bet_id} was declined and is listed again: reopened")
            st["status"] = "proposed"
            st["stages"].pop("gate", None)
            save_state(st)
            ledger_upsert(bet_id, status="proposed", outcome="reopened from the backlog")
            record_decision(st, "bet", "reopen", note=note, where="backlog")
        elif st["status"] not in WAITING:
            log(f"Queue names {bet_id}, which is {st['status']}; skipped")
            backlog_mark("queue", bet_id, f"skipped {stamp()}: already {st['status']}")
            continue
        picked = (bet_id, note)
        break
    if not picked:
        return None
    bet_id, note = picked
    st = load_state(bet_id)
    bdir = BETS_DIR / bet_id
    bet = json.loads(read(bdir / "bet.json") or "{}")
    now = pitch_fields(bdir / "bet.md")
    edited = [k for k in ("title", "invariant") if now.get(k) and now[k] != bet.get(k)]
    bet.update(now)
    at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    block = ["## Owner's decision", "", f"Approved on {at[:10]}: listed in backlog.md, taken by the loop at {at}.", "",
             f"**Invariant (signed):** {bet.get('invariant', '')}", ""]
    if edited:
        block += [f"(The owner edited the pitch's {' and '.join(edited)} before the loop took it.)", ""]
    if note:
        block += [f"**Notes:** {note}", ""]
    write(bdir / "decision.md", "\n".join(block))
    if edited:
        write(bdir / "bet.json", json.dumps(bet, indent=2, default=str))
    st["stages"]["bet"] = bet
    st["stages"]["gate"] = {"invariant": bet.get("invariant", ""), "note": note, "at": at, "edited": edited}
    st["status"] = "approved"
    save_state(st)
    ledger_upsert(bet_id, title=bet.get("title") or "", threshold=bet.get("threshold") or "")
    backlog_mark("queue", bet_id, f"taken {stamp()}")
    record_decision(st, "bet", "approve", note=note, where="backlog", ref=bet.get("title") or "",
                    opened_at=bet.get("at"), decided_at=at, run_id=bet.get("_run_id"))
    log(f"{bet_id} taken from the backlog: {bet.get('title')}")
    return bet_id


def approve(bet_id: str, note: str | None) -> None:
    """Append a candidate to the queue. The same as adding the line by hand."""
    st = load_state(bet_id)
    if st["status"] not in WAITING | {"rejected"}:
        die(f"{bet_id} is {st['status']}, not waiting for a decision")
    ensure_backlog()
    if bet_id in {b for b, _ in backlog()}:
        log(f"{bet_id} is already queued in {BACKLOG}")
        return
    backlog_append("queue", bet_id + (f"  {note}" if note else ""))
    log(f"{bet_id} queued at position {len(backlog())}; reorder {BACKLOG} to change it")


def reject(bet_id: str, why: str, where: str = "cli") -> None:
    """Turn a candidate down, for the record: the decision and its reason go in decision.md, the
    ledger, decisions.jsonl, and under Declined in backlog.md. Nothing is removed; the pitch stays
    where it was, and a Queue line for it later reopens it. Also for a bet that was picked but has
    not shipped -- a failed build the owner would rather drop than fix. Not for one with a PR: that
    is decided on GitHub."""
    st = load_state(bet_id)
    if st["status"] not in WAITING | {"approved", "running", "tasked", "built", "build_failed", "stopped"}:
        die(f"{bet_id} is {st['status']}; nothing to reject")
    rid = (st["stages"].get("loop") or {}).get("_run_id")
    if rid and get_run(rid).get("status") in ("running", "pending"):
        die(f"{bet_id}'s run {rid[:8]} is still going; cancel it in temper first")
    at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    bet = st["stages"].get("bet") or json.loads(read(BETS_DIR / bet_id / "bet.json") or "{}")
    write(BETS_DIR / bet_id / "decision.md", f"## Owner's decision\n\nDeclined on {at[:10]}: {why}\n")
    st["stages"]["gate"] = {"rejected": why, "at": at}
    st["status"] = "rejected"
    save_state(st)
    ensure_backlog()
    if not any(s == "declined" and b == bet_id and not mark for s, b, _, mark in backlog_lines()):
        backlog_append("declined", f"{bet_id}  {why}")
    backlog_mark("declined", bet_id, f"recorded {stamp()}")
    # a queue line written before this decline is overtaken by it; only a line written after reopens
    backlog_mark("queue", bet_id, f"declined {stamp()}")
    record_decision(st, "bet", "reject", note=why, where=where, ref=bet.get("title") or "",
                    opened_at=bet.get("at"), decided_at=at, run_id=bet.get("_run_id"))
    ledger_upsert(bet_id, outcome=f"declined: {why}")
    log(f"{bet_id} declined: {why}")


def stage_tasks(st: dict) -> None:
    bet_id = st["bet_id"]
    bdir = BETS_DIR / bet_id
    refresh_main()
    out = run_workflow("epd_tasks", {
        "bet_id": bet_id,
        "tasks_path": cpath(bdir / "tasks.json"),
        "repo_path": cpath(MAIN_CLONE),
        "bet": bet_text(bdir),
        "profile": read(LOOP_DIR / "profile.md"),
    }, workspace=CONTAINER_WORKSPACES, timeout=2400)
    if out.get("status") == "BLOCKED":
        die(f"tasks BLOCKED: {out.get('blocked_because')}")
    if not (bdir / "tasks.json").exists():
        die("epd_tasks finished but wrote no tasks.json")
    st["stages"]["tasks"] = out
    st["status"] = AFTER["tasks"]
    save_state(st)
    log(f"tasks: {out.get('task_count')} tasks touching {len(out.get('files') or [])} files")


def stage_build(st: dict) -> None:
    bet_id = st["bet_id"]
    bdir = BETS_DIR / bet_id
    title = (st["stages"].get("bet") or {}).get("title") or bet_id
    bet_md = bet_text(bdir)
    tasks = read(bdir / "tasks.json")
    # The task name becomes the branch, the worktree, the standee env and a
    # DNS label (<slug>.dev.rollcall…): a label is 63 chars at most and standee
    # caps the env name at 62, so keep the slug short — the bet id plus the
    # first words of the title.
    words = re.findall(r"[a-z0-9]+", title.lower())
    short = f"epd {bet_id}"
    for w in words:
        if len(short) + 1 + len(w) > 40:
            break
        short += f" {w}"
    description = (
        f"This task is bet {bet_id} of the EPD loop. The pitch below is the product decision "
        f"(the owner signed the invariant); the task list is the engineering decomposition, each "
        f"task with the command that proves it. Implement the tasks in order; a task is done when "
        f"its acceptance command gives the expected output. Do nothing listed under no-gos.\n\n"
        f"----- bet.md -----\n{bet_md}\n\n----- tasks.json -----\n{tasks}\n"
    )
    out = run_workflow("epd_task", {
        "repo_url": REPO_URL,
        "task_name": short,
        "task_description": description,
        "base_branch": BASE_BRANCH,
        "keep": True,
        "force": True,
        "stack_ttl": "8h",
        "verify_email": QA_EMAIL,
        "verify_password": QA_PASSWORD,
    }, workspace=cpath(WORKSPACES / "repos"), timeout=4 * 3600)
    write(bdir / "build.json", json.dumps(out, indent=2, default=str))
    st["stages"]["build"] = {k: out.get(k) for k in (
        "_run_id", "_cost_usd", "_duration_s", "_versions", "task_slug", "branch", "worktree_path", "head",
        "env_name", "stack_url", "implement_commit", "implement_summary", "review_verdict",
        "verify_verdict", "verify_screenshots", "security_verdict", "test_verdict", "test_summary",
        "deploy_url", "verdict", "verdict_summary", "changes_wanted_by", "security_human_actions")}
    verdict = out.get("verdict")
    st["status"] = "built" if verdict == "approve" else "build_failed"
    save_state(st)
    log(f"build: verdict={verdict} ({out.get('verdict_summary')}) commit={out.get('implement_commit')} url={out.get('deploy_url')}")
    if verdict != "approve":
        log(f"the build did not pass its judges; see {bdir / 'build.json'}. "
            f"Fix by hand and `epd_loop.py stage ship --bet {bet_id}`, or leave it.")


def artefact(bdir: Path, name: str, st: dict, key: str) -> dict:
    """A stage's structured result: from the bet directory if it is there, else from this driver's state.

    The two hold the same fields — ``stage_build`` writes ``build.json`` and keeps a subset in state — so
    preferring the file costs nothing and buys one thing: ship stops needing the driver to have run the
    earlier stages in this process. A workflow node that writes the same artefacts can then drive it.
    """
    p = bdir / f"{name}.json"
    if p.exists():
        try:
            return json.loads(read(p))
        except ValueError as exc:
            die(f"{p} is not readable JSON: {exc}")
    return st["stages"].get(key) or {}


def stage_ship(st: dict) -> None:
    bet_id = st["bet_id"]
    bdir = BETS_DIR / bet_id
    b = artefact(bdir, "build", st, "build")
    branch = b.get("branch")
    wt = b.get("worktree_path")
    if not branch:
        die(f"no build to ship: neither {bdir / 'build.json'} nor the state file names a branch")
    if (b.get("verdict") or "approve") != "approve":
        die(f"refusing to ship {bet_id}: the build's own judges said {b.get('verdict')!r} "
            f"({b.get('verdict_summary')})")
    if not wt:
        log("note: no worktree path recorded; the branch is in the clone regardless")
    # Fetch from the main clone, never from the worktree. A worktree's `.git`
    # is a file holding `gitdir: /app/workspaces/.../main/.git/worktrees/<n>`
    # -- a *container* path, absent on this side of the mount -- so serving
    # from the worktree dies with "not a git repository", which is exactly
    # how the first full run failed after a clean build. The branch is an
    # ordinary ref in the parent clone, and that is a real repository here.
    # (`safe.directory`: the clone belongs to the container's user.)
    if wt and not hpath(wt).exists():
        log(f"note: worktree gone from the host ({hpath(wt)}); its branch is in the clone regardless")
    trust_main_clone()
    sh(["git", "fetch", "--force", str(MAIN_CLONE), f"{branch}:refs/heads/{branch}"], cwd=REPO_CHECKOUT)
    sh(["git", "push", "--force-with-lease", "-u", "origin", branch], cwd=REPO_CHECKOUT)
    bet = artefact(bdir, "bet", st, "bet")
    shots = collect_screenshots(bdir, b.get("task_slug") or "", b.get("verify_screenshots"))
    body = (
        f"EPD loop bet **{bet_id}** — {bet.get('title')}\n\n"
        f"**Problem:** {bet.get('problem')}\n\n"
        f"**Invariant (signed):** {(st['stages'].get('gate') or {}).get('invariant') or bet.get('invariant')}\n\n"
        f"**Success threshold:** {bet.get('threshold')}\n\n"
        f"Judges on the candidate: review={b.get('review_verdict')}, QA={b.get('verify_verdict')}, "
        f"security={b.get('security_verdict')}, tests={b.get('test_verdict')} → {b.get('verdict')} "
        f"({b.get('verdict_summary')}).\n\n"
        + (f"CI's checks before the PR: {b.get('test_summary')}\n\n" if b.get("test_summary") else "")
        + f"Dev stack of this branch: {b.get('deploy_url')}\n\n"
        f"Artifacts: `{bdir}` (bet.md, tasks.json, build.json"
        f"{', screenshots/' if shots else ''}); report: `{report_path_for(bet_id)}`.\n"
    )
    walk_md = threshold_walk_md(b.get("verify_threshold_checks"))
    if walk_md:
        body += "\n" + walk_md
    shots_md = publish_screenshots(bet_id, shots)
    if shots_md:
        body += "\n" + shots_md
    write(bdir / "pr.md", body)
    pr = open_or_find_pr(branch, f"{bet_id}: {bet.get('title')}", body)
    pr_url, pr_number = pr.get("html_url"), pr.get("number")
    if not pr_url or not pr_number:
        die(f"could not open or find the PR for {branch}")
    st["stages"]["ship"] = {"pr": pr_url, "pr_number": pr_number, "branch": branch,
                            "title": f"{bet_id}: {bet.get('title')}",
                            "screenshots": [s["file"] for s in shots],
                            "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
    st["status"] = AFTER["ship"]
    save_state(st)
    log(f"PR: {pr_url}")
    log("   it stays open until the owner says what happens to it (the loop's gate)")


def pr_decision_from_gate(gate: dict) -> tuple[str, str]:
    """What the owner picked at the PR gate, and the note they wrote: (merge|request_changes|close|'', note).

    The gate response is temper's ``{response, answers: [{question, selected, custom}], text}``.
    The decision is the selected label of whichever answer picked one of the three; the note is
    the free text plus anything typed as a custom answer, so nothing the owner wrote is dropped.
    """
    decision, notes = "", []
    for a in gate.get("answers") or []:
        for label in a.get("selected") or []:
            if label in PR_DECISIONS and not decision:
                decision = PR_DECISIONS[label]
        if (a.get("custom") or "").strip():
            notes.append(a["custom"].strip())
    if (gate.get("response") or "").strip():
        notes.append(gate["response"].strip())
    return decision, "\n".join(notes)


def stage_deploy(st: dict) -> None:
    """Act on the owner's word about the PR, then put a merged one in front of real users.

    The word comes from ``pr-decision.json`` in the bet directory, which the deploy node writes from
    the gate response before it asks for this; and it is checked against GitHub, because the owner
    may have merged or closed the PR there instead of, or before, answering the gate. GitHub's state
    wins when they disagree -- a PR that is merged is merged, whatever the form said -- and the
    record says which of the two it was (``where``).

      merge            -> squash-merge (unless GitHub already did), back production up, deploy the
                          merge commit, check the QA tenant survived. Status ``shipped``.
      request_changes  -> the note goes on the PR as a comment; the PR stays open and the run ends.
                          Status ``changes_requested``. (A rewind into the build with the note is
                          the next thing to build; today the note is the record, and the next bet's
                          context carries it.)
      close            -> close the PR unmerged, with the note. Status ``closed``.
    """
    bet_id = st["bet_id"]
    bdir = BETS_DIR / bet_id
    ship = st["stages"].get("ship") or {}
    pr_number = ship.get("pr_number")
    if not pr_number:
        die(f"{bet_id} has no PR to decide on; `stage ship` first")
    gate: dict = {}
    p = bdir / "pr-decision.json"
    if p.exists():
        try:
            gate = json.loads(read(p))
        except ValueError as exc:
            die(f"{p} is not readable JSON: {exc}")
    decision, note = pr_decision_from_gate(gate)

    owner, repo = GH_REPO.split("/", 1)
    pr = github("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}")
    where = "temper"
    if pr.get("merged"):
        decision, where = "merge", "github"
    elif pr.get("state") == "closed":
        decision, where = "close", "github"
    if not decision:
        die(f"{bet_id}: no decision on PR #{pr_number} -- neither the gate response ({p}) nor GitHub says")
    record = {"decision": decision, "where": where, "note": note,
              "decided_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
    log(f"PR #{pr_number}: {decision} ({where}){' -- ' + note if note else ''}")
    # The run this PR came out of: the composed loop's, or the stage-at-a-time build's.
    run_id = (st["stages"].get("loop") or {}).get("_run_id") or (st["stages"].get("build") or {}).get("_run_id")
    # Once per PR: a deploy re-run after a failed rollout is the same decision, not a second one.
    if not any(r.get("kind") == "pr" and r.get("ref") == ship.get("pr") for r in load_decisions()):
        record_decision(st, "pr", decision, note=note, answers=gate.get("answers") or [], where=where,
                        opened_at=ship.get("at"), decided_at=record["decided_at"], run_id=run_id, upto="ship",
                        ref=ship.get("pr", ""))

    if decision == "merge":
        if where == "temper":
            merged = github("PUT", f"/repos/{owner}/{repo}/pulls/{pr_number}/merge",
                            {"merge_method": "squash", "commit_title": f"{ship.get('title')} (#{pr_number})"})
            log(f"merged PR #{pr_number}: {merged.get('message') or merged.get('sha', '')[:12]}")
        sh(["git", "fetch", "-q", "origin"], cwd=REPO_CHECKOUT)
        sh(["git", "checkout", "-q", BASE_BRANCH], cwd=REPO_CHECKOUT)
        sh(["git", "merge", "--ff-only", f"origin/{BASE_BRANCH}"], cwd=REPO_CHECKOUT)
        merge_sha = sh(["git", "rev-parse", "HEAD"], cwd=REPO_CHECKOUT).stdout.strip()
        ship.update(record, merged=True, merge_sha=merge_sha)
        save_state(st)
        log(f"merged into {BASE_BRANCH} as {merge_sha[:12]}")
        deploy_prod(merge_sha)
        qa_ok = ensure_qa_on_prod()
        ship.update({"prod_url": PROD_URL, "prod_env": PROD_ENV, "prod_qa": qa_ok,
                     "deployed_at": dt.datetime.now().isoformat()})
        st["status"] = AFTER["deploy"]
        save_state(st)
        log(f"live: {PROD_URL} now runs {merge_sha[:12]}")
        return

    if where == "temper":
        body = (f"**Owner's decision at the PR gate: {decision.replace('_', ' ')}.**"
                + (f"\n\n{note}" if note else ""))
        github("POST", f"/repos/{owner}/{repo}/issues/{pr_number}/comments", {"body": body})
        if decision == "close":
            github("PATCH", f"/repos/{owner}/{repo}/pulls/{pr_number}", {"state": "closed"})
    ship.update(record, merged=False)
    st["status"] = "changes_requested" if decision == "request_changes" else "closed"
    save_state(st)
    ledger_upsert(bet_id, status=st["status"], outcome=f"pr {decision.replace('_', ' ')}: {note}".strip(": "))
    log(f"PR #{pr_number} {st['status'].replace('_', ' ')}; nothing shipped")


# --- the owner's decisions as a record --------------------------------------------------------
#
# Every word the owner gives the loop -- approve or reject a bet, merge / request changes / close a
# PR -- is a judgement on what the loop produced, and the only one that counts. Kept as one JSON
# line per decision in decisions.jsonl, the record is what "is the loop getting better" is answered
# from: read against the config versions that produced each artefact, it says which changes to the
# agents moved the owner's verdicts, and which did not. The rows carry what the owner asked for:
# the verbatim note, the answers to the owner questions, every epd config's version, and the run's
# cost and duration up to the gate.

DECISIONS = LOOP_DIR / "decisions.jsonl"


def config_versions_all() -> dict[str, int | str]:
    """Every epd config's version -- `agent:<name>` and `workflow:<name>` -- read off the yaml files.

    Read at recording time, not at run time: a decision is a verdict on the configs as they stood
    when they produced the thing decided on, and versions do not change mid-run. (If one is bumped
    between the run and the decision, the row is off by that bump; the run's own `_versions` in
    the state file is the tie-breaker.)
    """
    out: dict[str, int | str] = {}
    for kind in ("agent", "workflow"):
        for p in sorted((CONFIG_DIR / f"{kind}s").glob("*.yaml")):
            m = re.search(r"^\s+version:\s*['\"]?([^'\"\n]+)", read(p), re.M)
            v = m.group(1).strip() if m else "?"
            out[f"{kind}:{p.stem}"] = int(v) if v.isdigit() else v
    return out


def run_gate_decisions(run_id: str) -> list[dict]:
    """The gates a temper run opened and how each was answered (``GET /api/runs/{id}/decisions``)."""
    try:
        with urllib.request.urlopen(f"{API}/api/runs/{run_id}/decisions", timeout=60) as resp:
            return json.load(resp).get("decisions") or []
    except Exception as exc:  # noqa: BLE001 -- an older server has no such route; the record is still written
        log(f"   (no gate decisions from temper for {run_id[:8]}: {exc})")
        return []


def run_cost(run_id: str, upto: str | None = None) -> tuple[float | None, float | None]:
    """(cost_usd, duration_s) of a temper run, or of its top-level stages up to and including `upto`.

    Up to the gate is what a decision is a verdict on: a bet was proposed for the price of the
    report and the pitch, whatever the build cost afterwards.
    """
    try:
        d = get_run(run_id)
    except Exception:  # noqa: BLE001
        return None, None
    nodes = {n.get("name"): n for n in d.get("nodes") or []}
    if upto and upto in STAGES and nodes:
        wanted = STAGES[: STAGES.index(upto) + 1]
        picked = [nodes[n] for n in wanted if n in nodes]
        cost = sum(n.get("cost_usd") or 0 for n in picked)
        dur = sum(n.get("duration_seconds") or 0 for n in picked)
        return round(cost, 4), round(dur, 1)
    return d.get("total_cost_usd"), d.get("duration_seconds")


def record_decision(st: dict, kind: str, decision: str, *, note: str = "", answers: list | None = None,
                    opened_at: str | None = None, decided_at: str | None = None, where: str = "temper",
                    run_id: str | None = None, upto: str | None = None, ref: str = "") -> dict:
    """Append one decision to decisions.jsonl and return the row.

    kind      bet | pr
    decision  approve | reject | reopen | merge | request_changes | close
    where     temper (the gate in the UI) | github (merged/closed there) | backlog (a line in
              backlog.md: queued and taken, declined, or queued again) | cli (reject here)
    ref       what was decided on: the bet title, or the PR url
    upto      the last stage the decision is a verdict on, for the cost figure
    """
    cost, dur = run_cost(run_id, upto) if run_id else (None, None)
    seconds = None
    if opened_at and decided_at:
        try:
            a, b = dt.datetime.fromisoformat(opened_at), dt.datetime.fromisoformat(decided_at)
            if (a.tzinfo is None) != (b.tzinfo is None):
                a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
            seconds = round((b - a).total_seconds(), 1)
        except ValueError:
            seconds = None
    row = {
        "at": decided_at or dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "bet_id": st["bet_id"],
        "kind": kind,
        "decision": decision,
        "where": where,
        "ref": ref,
        "note": note,
        "answers": answers or [],
        "opened_at": opened_at,
        "seconds_to_decide": seconds,
        "run_id": run_id,
        "run_cost_usd": cost,
        "run_duration_s": dur,
        "versions": config_versions_all(),
    }
    DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    with DECISIONS.open("a") as f:
        f.write(json.dumps(row) + "\n")
    log(f"recorded: {kind} {decision} on {st['bet_id']} -> {DECISIONS}")
    return row


def load_decisions() -> list[dict]:
    rows = []
    for line in read(DECISIONS).splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def bet_title(st: dict) -> str:
    for key in ("bet", "loop"):
        d = st.get("stages", {}).get(key) or {}
        t = d.get("title") or d.get("bet_title")
        if t:
            return t
    bet = json.loads(read(BETS_DIR / st["bet_id"] / "bet.json") or "{}")
    return bet.get("title") or ""


def scorecard() -> str:
    """The owner's verdicts, grouped by the config versions that earned them.

    Two tables -- bets (approve / reject) by `epd_bet` version, PRs (merge / request changes /
    close) by `task_implement` version: the agent whose output each decision is most directly a
    verdict on -- then every row, oldest first, with the notes and answers. Versions are the axis
    because they are what changes on purpose between runs; a change that moves the approve or
    merge rate is one worth keeping.
    """
    rows = load_decisions()
    if not rows:
        return f"no decisions recorded yet ({DECISIONS})"
    lines = [f"{len(rows)} decisions in {DECISIONS}", ""]

    def table(kind: str, agent: str, verdicts: list[str]) -> None:
        by: dict[str, dict[str, int]] = {}
        for r in rows:
            if r.get("kind") != kind:
                continue
            v = str((r.get("versions") or {}).get(f"agent:{agent}", "?"))
            by.setdefault(v, {})
            by[v][r.get("decision", "?")] = by[v].get(r.get("decision", "?"), 0) + 1
        if not by:
            return
        lines.append(f"{kind}s by {agent} version")
        lines.append("  " + "version".ljust(10) + "".join(v.ljust(18) for v in verdicts) + "rate")
        for v in sorted(by):
            counts = by[v]
            total = sum(counts.values())
            lines.append("  " + v.ljust(10) + "".join(str(counts.get(x, 0)).ljust(18) for x in verdicts)
                         + f"{counts.get(verdicts[0], 0)}/{total} {verdicts[0]}")
        lines.append("")

    table("bet", "epd_bet", ["approve", "reject"])
    table("pr", "task_implement", ["merge", "request_changes", "close"])
    waiting = waiting_bets()
    if waiting:
        lines.append(f"undecided: {', '.join(waiting)} (proposed, neither in the backlog nor rejected)")
        lines.append("")
    lines.append("decisions")
    for r in rows:
        when = (r.get("at") or "")[:16].replace("T", " ")
        secs = r.get("seconds_to_decide")
        took = f", decided in {secs / 60:.0f} min" if isinstance(secs, (int, float)) else ""
        cost = r.get("run_cost_usd")
        cost_s = f", ${cost:.2f} to get there" if isinstance(cost, (int, float)) else ""
        lines.append(f"  {when}  {r.get('bet_id')}  {r.get('kind'):<3} {r.get('decision'):<16} "
                     f"({r.get('where')}{took}{cost_s})  {(r.get('ref') or '')[:70]}")
        for ln in (r.get("note") or "").splitlines():
            lines.append(f"      | {ln}")
        for a in r.get("answers") or []:
            picked = ", ".join(a.get("selected") or [])
            if a.get("custom"):
                picked = f"{picked} -- {a['custom']}" if picked else a["custom"]
            if picked:
                lines.append(f"      ? {(a.get('question') or a.get('id') or '')[:70]} -> {picked}")
    return "\n".join(lines)


def stage_measure(st: dict, keep: bool) -> None:
    bet_id = st["bet_id"]
    bdir = BETS_DIR / bet_id
    # Same read as stage_ship: the bet's own build.json first, then state. The composed loop
    # records under stages["loop"], not stages["build"], so reading state alone found nothing
    # for a bet the loop built -- measure then ran with no build_summary (measuring a change
    # without being told what it claims to do) and skipped the teardown below, because the
    # env_name it looks for was in the dict it did not read.
    # The two hold different subsets -- build.json has the summary, the loop record has env_name --
    # so this is a merge, not a fallback, with the file winning where both speak.
    b = {**(st["stages"].get("loop") or {}), **artefact(bdir, "build", st, "build")}
    shipped = st["stages"].get("ship") or {}
    stack = b.get("deploy_url") or b.get("stack_url")
    # The live product if it was shipped, else the branch's stack.
    url = shipped.get("prod_url") or stack
    if not url:
        die("no deployed URL to measure on")
    wait_for_url(url)
    # The live server has its own QA tenant now (paper adapters, its own
    # book), so the whole measurement happens on the build people use. Only
    # if seeding it failed does a signed-in check fall back to the branch's
    # stack, which is the identical commit with data.
    on_prod = bool(shipped.get("prod_url"))
    qa_on_prod = bool(shipped.get("prod_qa"))
    data_url = stack if (on_prod and stack and not qa_on_prod) else ""
    if data_url:
        wait_for_url(data_url)
    password = ensure_qa_password() if (on_prod and qa_on_prod) else QA_PASSWORD
    # Whichever stack the signed-in checks will use has to admit them, and finding that out costs one
    # request here versus a whole measurement spent describing a login page.
    if data_url:
        preflight_login(data_url)
    elif qa_on_prod or not on_prod:
        preflight_login(url, password=password)
    # The measure agent is handed these two as paths and told to read them: the bet is what it
    # checks, the report is the friction it re-walks. A path to a file that is not there buys a
    # measurement that quietly skips the re-walk, so it is worth one stat each to find out here.
    report = report_path_for(bet_id)
    for what, path in (("bet", bdir / "bet.md"), ("report", report)):
        if not path.exists():
            die(f"cannot measure {bet_id}: its {what} should be at {path} and is not"
                + (f" (round {round_of(bet_id) or 'unknown'})" if what == "report" else ""))
    out = run_workflow("epd_measure", {
        "bet_id": bet_id,
        "outcome_path": cpath(bdir / "outcome.md"),
        "app_url": url,
        "data_url": data_url,
        "email": QA_EMAIL, "empty_email": QA_EMPTY_EMAIL, "password": password,
        "bet_path": cpath(bdir / "bet.md"),
        "report_path": cpath(report),
        "build_summary": b.get("implement_summary") or "",
    }, workspace=LOOP_WORKSPACE, timeout=2400)
    if not (bdir / "outcome.md").exists():
        die("epd_measure finished but wrote no outcome.md")
    verdict = settle_verdict(out)
    st["stages"]["measure"] = out
    st["status"] = verdict if verdict in TERMINAL else "iterate"
    save_state(st)
    ledger_upsert(bet_id, outcome=outcome_line(out, verdict))
    log(f"measure: {verdict} — {out.get('summary')}")
    if out.get("unverified"):
        log(f"unverified on the running build: {out['unverified']}")
    if not keep and b.get("env_name"):
        standee_down(b["env_name"])


def settle_verdict(out: dict) -> str:
    """The verdict the ledger gets, held to what was seen.

    A criterion that could not fail did not pass. The agent is told this, and the driver holds it
    to it: a kept verdict with a vacuous criterion, or with the threshold not met, is recorded as
    iterate, because the ledger is what the next proposal inherits and it must not be truer than
    what was seen. Same rule for a measure run alone and for the composed loop.
    """
    verdict = out.get("verdict") or "iterate"
    vacuous = int(out.get("vacuous_criteria") or 0)
    if verdict == "kept" and (vacuous or out.get("threshold_met") is False):
        log(f"measure said kept, but {vacuous} criteria were vacuous / the threshold was not met — recording iterate")
        out["verdict_downgraded_from"] = "kept"
        return "iterate"
    return verdict


def outcome_line(out: dict, verdict: str) -> str:
    vacuous = int(out.get("vacuous_criteria") or 0)
    note = f" [{vacuous} criteria vacuous]" if vacuous else ""
    summary = out.get("summary") or out.get("outcome_summary") or ""
    return f"{verdict}{note}: {summary} (right threshold: {out.get('right_threshold')})"


# ------------------------------------------------------------------- driver --

def loop_inputs(bet_id: str) -> dict:
    """Everything the epd_loop workflow is told, off the bet's files: it starts at `tasks`, on a bet
    the owner already approved, so there is no stack to walk and nothing to propose."""
    bdir = BETS_DIR / bet_id
    bet = json.loads(read(bdir / "bet.json") or "{}")
    return {
        "bet_id": bet_id,
        "bet_dir": cpath(bdir),
        "report_path": cpath(report_path_for(bet_id)),
        "bet_path": cpath(bdir / "bet.md"),
        "tasks_path": cpath(bdir / "tasks.json"),
        "outcome_path": cpath(bdir / "outcome.md"),
        "title": bet.get("title") or bet_id,
        "problem": bet.get("problem") or "",
        "invariant": bet.get("invariant") or "",
        "threshold": bet.get("threshold") or "",
        "profile": read(LOOP_DIR / "profile.md"),
        "measure_url": PROD_URL,
        "email": QA_EMAIL, "empty_email": QA_EMPTY_EMAIL,
        "password": QA_PASSWORD, "measure_password": ensure_qa_password(),
        "repo_url": REPO_URL,
        "repo_path": cpath(MAIN_CLONE),
        "base_branch": BASE_BRANCH,
        "task_name": f"epd {bet_id}",
        "task_description": (
            f"This task is bet {bet_id} of the EPD loop. Read the bet at {cpath(bdir / 'bet.md')} "
            f"for the product decision the owner signed, and {cpath(bdir / 'tasks.json')} for the "
            f"engineering decomposition: implement the tasks in order, each is done when its "
            f"acceptance command gives the expected output. Do nothing listed under no-gos."
        ),
        "stack_ttl": "8h",
    }


# One run is one workspace root, and it has to hold everything the stages write: the bet's own
# files under epd/<repo>/bets/<id>, and the worktrees under repos/. Rooted at repos/ (what the
# build stage alone needs), the report agent's Write of an absolute path into the bet dir was
# outside the root, so the tool relocated it -- silently, to repos/epd/... -- and the bet dir came
# out empty while the run reported success. The union of the stages' roots is their parent.
LOOP_WORKSPACE = CONTAINER_WORKSPACES


def cmd_run(keep: bool, wait: bool, propose: bool, retry: bool) -> None:
    """One turn of the loop. What that is depends on what is on disk:

      a proposal or a bet still running      -> reported, nothing started
      one finished and not yet collected     -> collected (the ledger, the stack down), then:
      --propose, or nothing on file at all   -> a proposal run (walks, report, candidates)
      a bet in backlog.md                    -> the loop run for the top one: tasks .. measure
      candidates on file, none in the backlog -> reported: the owner's turn

    So a scheduler calling `run` every hour turns the loop as fast as the owner's decisions allow,
    and never past them. The loop run is temper's once submitted: it parks at the PR gate for as
    long as the owner takes, and a host process sitting on it for hours added nothing but something
    to keep alive. `--wait` is the blocking form, for a terminal that wants to watch (also the only
    form that re-submits after a rate-limit wall, since re-submitting needs a process around).

    A run that failed is reported and left alone: `resume` forks it at its last good stage, `run
    --retry` starts the bet over, `reject` drops it. Not retried on its own, since a scheduler
    would then spend all night on a bet that fails the same way each hour.
    """
    require_tools("standee", "docker", "git", "ssh")
    ensure_backlog()
    record_declines()
    # Every proposal out is collected if it is done; one still running means nothing new starts.
    if [rnd for rnd in open_rounds() if not collect_round(rnd, keep)]:
        return
    # Every open bet is looked at: the ones parked at the PR gate are counted and left to the
    # owner; one still building, or one that failed and needs a hand, means nothing new starts.
    parked: list[str] = []
    for bet_id in open_bets():
        done = collect_bet(bet_id, keep, retry=retry)
        if done == "retry":
            start_bet(bet_id, keep, wait)
            return
        if done == "parked":
            parked.append(bet_id)
            continue
        if done is not True:
            return
    if propose:
        cmd_propose(keep, wait)
        return
    if len(parked) >= PARKED_LIMIT:
        log(f"{len(parked)} PR(s) waiting for your word ({', '.join(parked)}); "
            f"the loop starts no more until one is decided")
        return
    bet_id = pick_bet()
    if bet_id:
        start_bet(bet_id, keep, wait)
        return
    waiting = waiting_bets()
    if waiting:
        log(f"nothing in {BACKLOG}; {len(waiting)} candidate(s) waiting for your word: {', '.join(waiting)}")
        log("   list the ones worth building there, top first (or `run --propose` for more)")
        return
    log("no candidates on file; proposing")
    cmd_propose(keep, wait)


def start_bet(bet_id: str, keep: bool, wait: bool) -> None:
    """Submit the loop run for a bet the owner approved: tasks -> build -> ship -> [PR gate] -> deploy -> measure."""
    st = load_state(bet_id)
    st["status"] = "running"
    save_state(st)
    log(f"== {bet_id}: the loop, as one run ==")
    log("   it will stop at `deploy` and wait for your word on the PR (temper's UI, or GitHub)")
    inputs = loop_inputs(bet_id)
    if wait:
        out = run_workflow("epd_loop", inputs, workspace=LOOP_WORKSPACE, timeout=8 * 3600)
        finish_loop(st, out, keep)
        return
    rid = post_run("epd_loop", inputs, LOOP_WORKSPACE)
    st["stages"]["loop"] = {"_run_id": rid, "_launched": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
    save_state(st)
    log(f"epd_loop → run {rid}")
    log("   it is temper's now; `epd_loop.py run` (or `collect`) records the outcome once it is done")


def fork_run(source_run_id: str, sequence: int, workflow: str, inputs: dict, workspace: str) -> str:
    """A new run that starts from ``source_run_id``'s checkpoint ``sequence`` and runs the rest."""
    body = json.dumps({"workflow": workflow, "source_execution_id": source_run_id, "sequence": sequence,
                       "inputs": inputs, "workspace_path": workspace}).encode()
    req = urllib.request.Request(f"{API}/api/runs/fork", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)["execution_id"]


def checkpoints(run_id: str) -> list[dict]:
    with urllib.request.urlopen(f"{API}/api/runs/{run_id}/checkpoints", timeout=60) as resp:
        return json.load(resp)["checkpoints"]


def in_server(cmd: str) -> subprocess.CompletedProcess:
    """Run a shell command inside the server container, where the run's files are its own."""
    return subprocess.run(["docker", "exec", SERVER_CONTAINER, "sh", "-c", cmd], text=True, capture_output=True)


def cmd_resume(at: str | None = None, bet: str | None = None) -> None:
    """Fork the open bet's failed loop run at its last good stage and run the rest, in temper.

    The finished stages come back as checkpoints -- report, bet, the owner's approval, tasks: the
    expensive and the human parts -- and the stage that failed runs again whole, in a run temper
    records as a fork of the old one. Temper's own resume would not do: a stage whose inner node
    failed is "completed" to the run above it, so a resume skips the stage and re-skips everything
    conditioned on it. Forking at the checkpoint before the failed stage is the resume this loop needs.

    ``at`` names the stage to start from instead of the first that failed. The case for it: a build
    whose only failed node came after its gate (a teardown step) delivered an approved commit, and
    starting again at `ship` keeps it, where the automatic choice would build it a second time.

    The failed attempt's leftovers are cleared first, since the stage starts over: its claim on the
    task (held by a run that is over), and whatever it left uncommitted in the worktree, which is
    kept as a patch beside the bet, so the new attempt starts where the tasks say and not where the
    old one stopped. Neither is touched when the build is being kept.
    """
    bet_id = bet or open_bet()
    if not bet_id:
        die("no open bet; nothing to resume")
    if bet and bet not in open_bets():
        die(f"{bet} is not open (open: {', '.join(open_bets()) or 'none'})")
    st = load_state(bet_id)
    bdir = BETS_DIR / bet_id
    loop = st["stages"].get("loop") or {}
    rid = loop.get("_run_id")
    if not rid:
        die(f"{bet_id} has no loop run; `run` first")
    info = get_run(rid)
    status = info.get("status")
    if status in ("running", "pending"):
        die(f"{bet_id}: run {rid[:8]} is still {status}; nothing to resume")
    if status == "completed":
        die(f"{bet_id}: run {rid[:8]} completed; `collect` it")
    # "2 node(s) failed: build/deploy, build/cleanup" -> the first failed top-level stage. A run
    # that was interrupted (server restart) or cancelled names none: the stage to redo is then the
    # first one that did not complete, which is the one that was running.
    failed = re.findall(r"(?:^|[:,]\s*)([a-z_]+)(?:/[a-z_/]+)?", info.get("error_message") or "")
    failed = [f for f in failed if f in STAGES]
    if not failed:
        done = {n["name"] for n in info.get("nodes") or [] if n.get("status") == "completed"}
        failed = [s for s in STAGES if s not in done][:1]
    if not failed:
        die(f"{bet_id}: run {rid[:8]} ended {status} but names no failed stage: {info.get('error_message')!r}")
    stage = min(failed, key=STAGES.index)
    if at:
        if at not in STAGES:
            die(f"--at must be one of {', '.join(STAGES)}")
        if STAGES.index(at) > STAGES.index(stage):
            log(f"note: starting at `{at}` although `{stage}` is where the run failed "
                f"({info.get('error_message')}); what `{stage}` delivered is kept")
        stage = at
    before = STAGES[STAGES.index(stage) - 1] if STAGES.index(stage) else None
    # A fork lists only the checkpoints it wrote itself; the stages it restored are checkpoints of
    # the run it was forked from. A second resume of the same stage therefore forks the original
    # again, at the same point.
    source = rid
    seqs = [c["sequence"] for c in checkpoints(rid) if c.get("node_name") == before and c.get("status") == "completed"]
    if before and not seqs and loop.get("_forked_from"):
        source = loop["_forked_from"]
        seqs = [c["sequence"] for c in checkpoints(source) if c.get("node_name") == before and c.get("status") == "completed"]
    if before and not seqs:
        die(f"{bet_id}: run {rid[:8]} has no completed checkpoint for `{before}` to fork from")
    seq = max(seqs) if seqs else 0

    slug = f"epd-{bet_id}"
    claim = f"{CONTAINER_WORKSPACES}/repos/{REPO_NAME}/claims/{slug}.json"
    wt = f"{CONTAINER_WORKSPACES}/repos/{REPO_NAME}/worktrees/{slug}"
    if STAGES.index(stage) <= STAGES.index("build"):
        r = in_server(f"python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(\"run_id\",\"\"))' {claim} 2>/dev/null")
        if r.stdout.strip() == rid:
            in_server(f"rm -f {claim}")
            log(f"cleared the claim on {slug} held by the failed run")
        r = in_server(f"git -C {wt} status --porcelain 2>/dev/null | wc -l")
        if r.returncode == 0 and r.stdout.strip() not in ("", "0"):
            patch = bdir / f"build-{rid[:8]}.patch"
            diff = in_server(f"git -C {wt} add -N . && git -C {wt} diff")
            write(patch, diff.stdout)
            in_server(f"git -C {wt} reset -q --hard && git -C {wt} clean -qfd")
            log(f"the failed attempt left {r.stdout.strip()} uncommitted paths in {slug}; kept as {patch.name}, worktree reset")

    log(f"== {bet_id}: resuming at `{stage}` (fork of {source[:8]} after `{before}`, checkpoint {seq}) ==")
    new = fork_run(source, seq, "epd_loop", loop_inputs(bet_id), LOOP_WORKSPACE)
    st["stages"]["loop"] = {"_run_id": new, "_launched": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                            "_forked_from": source, "_fork_sequence": seq,
                            "_replaces": rid, "_replaced_because": info.get("error_message") or status}
    save_state(st)
    log(f"epd_loop → run {new}")
    log("   it is temper's now; `epd_loop.py collect` records the outcome once it is done")


def cmd_collect(keep: bool) -> None:
    """Record what the last run produced, once temper is done with it. Safe to call early: a run
    still going is reported, not touched."""
    rounds = open_rounds()
    if rounds:
        for rnd in rounds:
            collect_round(rnd, keep)
        return
    bets = open_bets()
    if bets:
        for bet_id in bets:
            collect_bet(bet_id, keep)
        return
    log("nothing out: no proposal and no bet running")


def collect_bet(bet_id: str, keep: bool, retry: bool = False) -> bool | str:
    """Record what a bet's loop run produced. True when the bet is settled (collected, now or
    before); "parked" when its run is waiting at a gate for the owner's word; "running" when it is
    still working; False when it failed or needs the owner some other way; "retry" when the caller
    asked to start it over and may."""
    st = load_state(bet_id)
    loop = st["stages"].get("loop") or {}
    rid = loop.get("_run_id")
    if not rid:
        if retry:
            return "retry"
        log(f"{bet_id} is {st['status']} with no loop run: `next` runs its stages here, `run --retry` "
            f"submits it to temper, `reject` drops it")
        return False
    if loop.get("_collected"):
        log(f"{bet_id}: run {rid[:8]} already collected ({st['status']}); "
            + ("`stage measure --bet` when the deploy is done" if st["status"] == "shipped" else
               "`resume`, `stage <name> --bet`, or `reject` to move it"))
        return False
    info = get_run(rid)
    status = info.get("status")
    if status in ("running", "pending"):
        waiting = [d for d in run_gate_decisions(rid) if d.get("status") == "waiting"]
        if waiting:
            pr = (st["stages"].get("ship") or {}).get("pr") or ""
            since = str(waiting[0].get("opened_at") or "")[:16]
            where = pr or f"temper's UI, at `{waiting[0].get('node_name')}`"
            log(f"{bet_id}: waiting for you since {since} — merge it, send it back with a note, "
                f"or close it: {where}")
            return "parked"
        running = [n["name"] for n in info.get("nodes") or [] if n.get("status") == "running"]
        log(f"{bet_id}: run {rid[:8]} is still {status} (running={running}, "
            f"cost=${info.get('total_cost_usd') or 0:.2f}); nothing to collect yet")
        return "running"
    if status != "completed":
        why = "rate limited: the work is fine, the account is not" if rate_limited(rid) else info.get("error_message")
        if retry:
            log(f"{bet_id}: run {rid[:8]} ended {status} ({why}); starting the bet over as asked")
            return "retry"
        log(f"{bet_id}: run {rid} ended {status}: {why}")
        log("   `resume` forks it at its last good stage; `run --retry` starts the bet over; "
            "`reject <id> --why` drops it. A PR already open is decided on GitHub, then `stage deploy --bet`.")
        return False
    out = {k: unstr(v) for k, v in (info.get("workflow_output") or {}).items()}
    # A completed run that reports nothing is not a run that did nothing. Temper mapped no
    # workflow outputs on resumed runs until the fix in temper_ai/stage/executor.py, and the
    # driver wrote "stopped after build=None" over b004 -- a bet whose PR was merged, deployed
    # and measured. Recording a false outcome is worse than recording none, and the bet's own
    # files say what happened: `stage` writes state.json as each stage lands.
    if not out and any(v for v in (st.get("stages") or {}).values()):
        log(f"{bet_id}: run {rid[:8]} completed but reported no outputs — leaving the bet as "
            f"`{st.get('status')}`, which its own files recorded. Nothing is collected from it.")
        log("   this is temper's, not the work's: check the run in the UI, then "
            f"`stage <name> --bet {bet_id}` for whatever is genuinely left.")
        return False
    out["_versions"] = config_versions("epd_loop")
    out["_run_id"] = rid
    out["_launched"] = loop.get("_launched")
    out["_cost_usd"] = info.get("total_cost_usd")
    out["_duration_s"] = info.get("duration_seconds")
    finish_loop(st, out, keep)
    return True


def finish_loop(st: dict, out: dict, keep: bool) -> None:
    """The bookkeeping after a loop run: state, ledger, the build's stack, the worktree."""
    bet_id = st["bet_id"]
    out["_collected"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    st["stages"]["loop"] = out
    bet = st["stages"].get("bet") or json.loads(read(BETS_DIR / bet_id / "bet.json") or "{}")
    shipped = out.get("shipped")  # deploy's status: shipped | changes_requested | closed | None
    verdict = settle_verdict(out) if out.get("verdict") else None
    if verdict in TERMINAL:
        st["status"], outcome = verdict, outcome_line(out, verdict)
    elif shipped in ("changes_requested", "closed"):
        st["status"], outcome = shipped, None  # deploy wrote the owner's word on the PR
    elif shipped == "shipped":
        st["status"], outcome = "shipped", f"shipped as {out.get('merge_sha', '')[:12]}; not measured"
    else:
        st["status"], outcome = "stopped", f"stopped after build={out.get('build_verdict')}"
    save_state(st)
    ledger_upsert(bet_id, title=bet.get("title") or "", threshold=bet.get("threshold") or "",
                  status=st["status"], outcome=outcome)
    log(f"bet:     {bet.get('title')}")
    log(f"build:   {out.get('build_verdict')} — {out.get('implement_commit')}")
    log(f"ship:    {out.get('shipped')} {out.get('pr') or ''}")
    log(f"outcome: {st['status']} — {out.get('outcome_summary') or ''}")
    if st["status"] == "shipped":
        log(f"   measure did not report; `epd_loop.py stage measure --bet {bet_id}` runs it alone")
    # The build keeps its dev stack up so the PR the owner decides on links to a running candidate;
    # once the PR is decided (or the run stopped short of one), it has done its job.
    if out.get("env_name") and not keep:
        standee_down(str(out["env_name"]))
    if shipped in ("shipped", "changes_requested", "closed"):
        release_task(bet_id)


def release_task(bet_id: str) -> None:
    """Remove the build's worktree and local branch, and release its claim, once the PR is decided.

    The build keeps all three so that `ship` has a branch to push (epd_loop.yaml, the build node);
    what it pushed is the pull request, which holds every commit whatever the owner did with it, so
    the local copies are no longer the only ones. Same three steps as task_cleanup, in the same
    place (the server container, whose paths the clone's worktree records use), without its refusal:
    after a squash merge the commits are on origin as the PR and nowhere else, and GitHub may have
    deleted the branch, which task_cleanup would read as unpushed work. A worktree with uncommitted
    changes is left alone, and said so: whatever put them there is not this driver.
    """
    slug = f"epd-{bet_id}"
    root = f"{CONTAINER_WORKSPACES}/repos/{REPO_NAME}"
    main, wt, claim = f"{root}/main", f"{root}/worktrees/{slug}", f"{root}/claims/{slug}.json"
    r = in_server(f"git -C {wt} status --porcelain --untracked-files=all 2>/dev/null | wc -l")
    if r.returncode == 0 and r.stdout.strip() not in ("", "0"):
        log(f"note: {slug} has {r.stdout.strip()} uncommitted path(s); the worktree stays")
        return
    steps = (
        f"if [ -d {wt} ]; then git -C {main} worktree remove --force {wt} && echo 'worktree removed'; fi; "
        f"git -C {main} worktree prune; "
        f"if git -C {main} rev-parse -q --verify refs/heads/{slug} >/dev/null; then "
        f"git -C {main} branch -D -q {slug} && echo 'branch deleted'; fi; "
        f"if [ -f {claim} ]; then mkdir -p {root}/claims/released && "
        f"mv {claim} {root}/claims/released/{slug}.$(date -u +%Y%m%dT%H%M%SZ).json && echo 'claim released'; fi"
    )
    r = in_server(steps)
    done = ", ".join(r.stdout.strip().splitlines()) if r.stdout.strip() else "nothing to release"
    if r.returncode != 0:
        log(f"note: releasing {slug} did not finish ({r.stderr.strip()[:200]}); {done}")
    else:
        log(f"released {slug}: {done}")


def run_stage(name: str, st: dict, keep: bool) -> None:
    # `ship` arrives here through an sshd forced command, whose environment is
    # smaller than systemd's; it is the stage that most needs this check.
    require_tools("standee", "docker", "git")
    if name == "tasks":
        stage_tasks(st)
    elif name == "build":
        stage_build(st)
    elif name == "ship":
        stage_ship(st)
    elif name == "deploy":
        stage_deploy(st)
    elif name == "measure":
        stage_measure(st, keep)
    else:
        die(f"unknown stage {name}")


def cmd_next(until: str | None, keep: bool) -> None:
    """The open bet's stages one at a time, here, from wherever it is. Takes the top of the backlog
    when no bet is open. For redoing stages by hand; `run` is the loop."""
    ensure_backlog()
    record_declines()
    bet_id = open_bet() or pick_bet()
    if not bet_id:
        waiting = waiting_bets()
        die(f"nothing in {BACKLOG}" + (f"; {len(waiting)} candidate(s) waiting: {', '.join(waiting)}" if waiting
                                       else "; no candidates on file -- `run --propose`"))
    st = load_state(bet_id)
    while True:
        status = st["status"]
        stage = NEXT_STAGE.get(status)
        if stage is None:
            if status in TERMINAL:
                log(f"{bet_id} is finished ({status})")
            elif status == "running":
                log(f"{bet_id} is running in temper ({(st['stages'].get('loop') or {}).get('_run_id', '')[:8]}); `collect` it")
            else:
                log(f"{bet_id} is {status}; nothing runs automatically from here")
            return
        log(f"== {bet_id}: {stage} ==")
        run_stage(stage, st, keep)
        st = load_state(bet_id)
        if until and stage == until:
            return
        if st["status"] in TERMINAL:
            return


def cmd_status() -> None:
    rows = ledger_rows()
    if not rows:
        print("no bets yet; `run` proposes some")
    for r in rows:
        print(f"{r['bet_id']}  {r['date']}  {r['status']:13s}  {r['title'][:60]}")
        if r.get("outcome"):
            print(f"      {r['outcome'][:120]}")
    titles = {r["bet_id"]: r["title"] for r in rows}
    ensure_backlog()
    listed = backlog()
    print(f"\nqueue ({BACKLOG}):" + ("" if listed else " empty"))
    for i, (b, note) in enumerate(listed, 1):
        print(f"  {i}. {b}  {titles.get(b, '?')[:60]}" + (f"  -- {note}" if note else ""))
    unrecorded = [(b, why) for s, b, why, mark in backlog_lines() if s == "declined" and not mark]
    if unrecorded:
        print("declined, not yet recorded (`run` or `next` records them): "
              + ", ".join(f"{b} ({why})" if why else b for b, why in unrecorded))
    declined = [r for r in rows if r["status"] == "rejected"]
    if declined:
        print("declined:")
        for r in declined:
            print(f"  {r['bet_id']}  {r['title'][:50]}  -- {r['outcome'].removeprefix('declined: ').removeprefix('rejected: ')[:80]}")
    waiting = [b for b in waiting_bets() if b not in {x for x, _ in listed}]
    if waiting:
        print(f"waiting for your word (in neither list): {', '.join(waiting)}")
    for rnd in open_rounds():
        rd = load_round(rnd)
        print(f"\nproposal out: {rnd} (run {rd.get('_run_id', '')[:8]}); `collect` when it is done"
              + (f"\n    focus: {rd['focus']}" if rd.get("focus") else ""))
    for b in open_bets():
        st = load_state(b)
        rid = (st["stages"].get("loop") or {}).get("_run_id", "")
        print(f"\nopen bet: {b} ({st['status']}" + (f", run {rid[:8]}" if rid else "") + ")"
              + (f"; next stage here: {NEXT_STAGE[st['status']]}" if NEXT_STAGE.get(st["status"]) else ""))


def cmd_down(what: str) -> None:
    """Tear down a bet's stacks, or a proposal round's (`r001`)."""
    if what.startswith("r"):
        env = load_round(what).get("env")
        if env:
            standee_down(env)
        return
    st = load_state(what)
    for key in ("report", "build", "loop"):
        env = (st["stages"].get(key) or {}).get("env") or (st["stages"].get(key) or {}).get("env_name")
        if env:
            standee_down(str(env))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    r_ = sub.add_parser("run", help="one turn: collect what finished, then the top backlog bet as one temper run, "
                                    "or a proposal when there is nothing planned; returns once submitted")
    r_.add_argument("--propose", action="store_true", help="walk the product and write candidates, whatever the backlog holds")
    r_.add_argument("--retry", action="store_true", help="start the open bet over if its run failed")
    r_.add_argument("--keep", action="store_true", help="leave the stacks up")
    r_.add_argument("--wait", action="store_true", help="block until the run ends and collect it here")
    p = sub.add_parser("propose", help="walk the product and write candidates now, whatever else is out; "
                                       "returns once submitted")
    p.add_argument("--count", type=int, help="proposals side by side, each its own stack (default: one per --focus, else 1)")
    p.add_argument("--focus", action="append", default=[], metavar="TEXT",
                   help="the part of the product a round's walkers stay in; once per round, in order")
    p.add_argument("--keep", action="store_true", help="leave the stacks up")
    rs = sub.add_parser("resume", help="fork the open bet's failed loop run at its last good stage and run the rest")
    rs.add_argument("--at", choices=STAGES, help="start from this stage instead of the first that failed")
    rs.add_argument("--bet", help="which open bet, when more than one is (default: the latest)")
    c = sub.add_parser("collect", help="record what the last run (proposal or bet) produced, once temper is done")
    c.add_argument("--keep", action="store_true", help="leave the stacks up")
    n = sub.add_parser("next", help="the open bet's stages one at a time, here (takes the top backlog bet if none is open)")
    n.add_argument("--until", choices=STAGES)
    n.add_argument("--keep", action="store_true", help="leave the stacks up")
    a = sub.add_parser("approve", help="append a candidate to backlog.md (same as adding the line yourself)")
    a.add_argument("bet")
    a.add_argument("--note")
    r = sub.add_parser("reject", help="turn a candidate down for good")
    r.add_argument("bet")
    r.add_argument("--why", required=True)
    s = sub.add_parser("stage", help="run one stage alone, on the bet's files")
    s.add_argument("stage", choices=STAGES)
    s.add_argument("--bet", required=True)
    s.add_argument("--keep", action="store_true")
    d = sub.add_parser("down", help="tear down a bet's stacks (b004) or a proposal's (r001)")
    d.add_argument("what")
    sub.add_parser("scorecard", help="the owner's decisions on bets and PRs, by the config versions that earned them")
    args = ap.parse_args()

    mkdir_shared(BETS_DIR)
    mkdir_shared(REPORTS_DIR)
    if not LEDGER.exists():
        ledger_write([])
    for f in ("goals.md", "profile.md"):
        if not (LOOP_DIR / f).exists():
            die(f"{LOOP_DIR / f} is missing")

    if args.cmd == "status":
        cmd_status()
    elif args.cmd == "run":
        cmd_run(args.keep, args.wait, args.propose, args.retry)
    elif args.cmd == "propose":
        cmd_propose_many(args.count, args.keep, args.focus)
    elif args.cmd == "resume":
        cmd_resume(args.at, args.bet)
    elif args.cmd == "collect":
        cmd_collect(args.keep)
    elif args.cmd == "next":
        cmd_next(args.until, args.keep)
    elif args.cmd == "approve":
        approve(args.bet, args.note)
    elif args.cmd == "reject":
        reject(args.bet, args.why)
    elif args.cmd == "stage":
        st = load_state(args.bet)
        run_stage(args.stage, st, args.keep)
    elif args.cmd == "down":
        cmd_down(args.what)
    elif args.cmd == "scorecard":
        print(scorecard())


if __name__ == "__main__":
    main()
