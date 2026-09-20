#!/usr/bin/env python3
"""The EPD loop: report → bet → [owner signs] → tasks → build → ship → measure → next.

The product, design and engineering departments as one loop, one bet at a
time. Every stage is a function from files to files; this script is only the
wiring. It keeps the state on disk under

    <workspaces>/epd/<repo>/
        goals.md            the owner writes this; read fresh every iteration
        profile.md          what the product is and how the code is laid out
        bets.tsv            the ledger: one row per bet, status and outcome
        bets/<bet_id>/      report.md  bet.md  decision.md  tasks.json
                            build.json  pr.md  outcome.md  state.json

    The agents' files (report.md, bet.md, tasks.json, outcome.md) are written
    by the temper container's user; the owner's decision goes in its own file
    (decision.md) because this script cannot append to theirs.

and drives five temper workflows:

    epd_report   personas → three browser walks on a dev stack of main → report.md
    epd_bet      report + goals + ledger → bet.md  (stops: DECIDE)
    epd_tasks    bet → tasks.json with boolean acceptance per task
    epd_task     the existing engineering pipeline: worktree, plan, implement,
                 review + QA + security on a deployed dev stack, gate
    epd_measure  invariant + threshold on the shipped build → outcome.md

plus two host-side steps this script does itself: the dev stack for the
report (standee) and the ship (push the branch, open the PR).

Usage:
    epd_loop.py status
    epd_loop.py next [--until STAGE] [--auto-approve] [--keep]
    epd_loop.py approve BET [--invariant TEXT] [--note TEXT]
    epd_loop.py reject BET --why TEXT
    epd_loop.py stage STAGE --bet BET            # run one stage alone, on its files
    epd_loop.py down BET                         # tear down the bet's stacks

STAGE is one of: report bet tasks build ship measure.
The only place a human is required is between bet and tasks. `next` stops
there; `approve` signs the invariant (edited or as proposed) and `next`
carries on. `--auto-approve` is for exercising the wiring, not for real bets.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
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

STAGES = ["report", "bet", "tasks", "build", "ship", "measure"]
TERMINAL = {"rejected", "kept", "iterate", "killed"}
# status after each stage completes; what `next` does is read off the status
AFTER = {
    "report": "reported",
    "bet": "proposed",
    "tasks": "tasked",
    "build": "built",
    "ship": "shipped",
}
NEXT_STAGE = {
    "new": "report",
    "reported": "bet",
    "proposed": None,  # the gate: waits for approve/reject
    "approved": "tasks",
    "tasked": "build",
    "built": "ship",
    "build_failed": None,
    "shipped": "measure",
}


# ----------------------------------------------------------------- helpers --

def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def die(msg: str, code: int = 1) -> None:
    log(f"ERROR: {msg}")
    sys.exit(code)


def read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    # the container user (uid 999) has to be able to write next to it
    os.chmod(path, 0o666)


def mkdir_shared(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o777)


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


def open_bet() -> str | None:
    for r in reversed(ledger_rows()):
        if r["status"] not in TERMINAL:
            return r["bet_id"]
    return None


def new_bet_id() -> str:
    n = len(ledger_rows()) + 1
    while (BETS_DIR / f"b{n:03d}").exists():
        n += 1
    return f"b{n:03d}"


def previous_bet_id(bet_id: str) -> str | None:
    """The most recent bet before this one that was actually measured."""
    rows = [r for r in ledger_rows() if r["bet_id"] != bet_id and r["status"] in TERMINAL - {"rejected"}]
    return rows[-1]["bet_id"] if rows else None


def previous_outcome(bet_id: str) -> str:
    """The outcome of the most recent finished bet before this one."""
    prev = previous_bet_id(bet_id)
    return read(BETS_DIR / prev / "outcome.md") if prev else ""


#: Sections of an outcome that describe work the last bet did not finish. The
#: bet agent gets these verbatim: a ledger row saying "kept" is not enough to
#: carry "this shipped but nobody ever saw it run" into the next decision.
UNFINISHED_SECTIONS = ("Threshold", "Unverified", "Was this the right threshold", "For the next iteration")


def unfinished_business(bet_id: str) -> str:
    """What the previous bet left undone, in its own words.

    b001 shipped both halves of an either/or invariant and could only walk
    one: the measurement said so in prose, the ledger said "kept", and the
    agent choosing the next bet saw only the ledger. This is the repair.
    """
    prev = previous_bet_id(bet_id)
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
    m = st["stages"].get("measure") or {}
    if m.get("vacuous_criteria"):
        out += ["", f"({m['vacuous_criteria']} of its success criteria were vacuous: the situation each "
                    f"described never arose on the measured build, so nothing tested them.)"]
    return "\n".join(out).strip()


# ------------------------------------------------------------------ stages --

def stage_report(st: dict, keep: bool) -> None:
    bet_id = st["bet_id"]
    bdir = BETS_DIR / bet_id
    mkdir_shared(bdir)
    head = refresh_main()
    env, url = standee_up(MAIN_CLONE, f"epd-{bet_id}", "6h")
    st["stages"]["report"] = {"env": env, "url": url, "base_head": head}
    save_state(st)
    wait_for_url(url)
    out = run_workflow("epd_report", {
        "app_url": url,
        "email": QA_EMAIL, "empty_email": QA_EMPTY_EMAIL, "password": QA_PASSWORD,
        "goals": read(LOOP_DIR / "goals.md"),
        "profile": read(LOOP_DIR / "profile.md"),
        "last_outcome": previous_outcome(bet_id),
        "bet_id": bet_id,
        "report_path": cpath(bdir / "report.md"),
    }, workspace=cpath(LOOP_DIR), timeout=3600)
    for i in (1, 2, 3):
        if out.get(f"walk_{i}"):
            write(bdir / f"walk_{i}.md", str(out[f"walk_{i}"]))
    if not (bdir / "report.md").exists():
        die("epd_report finished but wrote no report.md")
    st["stages"]["report"].update({k: v for k, v in out.items() if not k.startswith("walk_")})
    st["status"] = AFTER["report"]
    save_state(st)
    log(f"report: {out.get('summary')}")
    if not keep:
        standee_down(env)


def stage_bet(st: dict) -> None:
    bet_id = st["bet_id"]
    bdir = BETS_DIR / bet_id
    out = run_workflow("epd_bet", {
        "bet_id": bet_id,
        "bet_path": cpath(bdir / "bet.md"),
        "goals": read(LOOP_DIR / "goals.md"),
        "profile": read(LOOP_DIR / "profile.md"),
        "report": read(bdir / "report.md"),
        "bets_tsv": read(LEDGER),
        "unfinished": unfinished_business(bet_id),
    }, workspace=cpath(LOOP_DIR), timeout=1800)
    if not (bdir / "bet.md").exists():
        die("epd_bet finished but wrote no bet.md")
    st["stages"]["bet"] = out
    st["status"] = AFTER["bet"]
    save_state(st)
    ledger_upsert(bet_id, title=out.get("title") or "", threshold=out.get("threshold") or "")
    print()
    print(f"=== Bet {bet_id}: {out.get('title')}")
    print(f"Problem:   {out.get('problem')}")
    print(f"Invariant: {out.get('invariant')}")
    print(f"Threshold: {out.get('threshold')}")
    print(f"Appetite:  {out.get('appetite_hours')} h")
    for c in out.get("candidates") or []:
        print(f"Lost:      {c}")
    for q in out.get("questions_for_owner") or []:
        print(f"Question:  {q}")
    print(f"Pitch:     {bdir / 'bet.md'}")
    print(f"\nDECIDE — sign it:   epd_loop.py approve {bet_id} [--invariant '...'] [--note '...']")
    print(f"         or reject: epd_loop.py reject {bet_id} --why '...'")


def approve(bet_id: str, invariant: str | None, note: str | None) -> None:
    st = load_state(bet_id)
    if st["status"] != "proposed":
        die(f"{bet_id} is {st['status']}, not proposed")
    bdir = BETS_DIR / bet_id
    signed = invariant or (st["stages"].get("bet") or {}).get("invariant") or ""
    block = ["## Owner's decision", "", f"Signed on {dt.date.today().isoformat()}.", "",
             f"**Invariant (signed):** {signed}", ""]
    if note:
        block += [f"**Notes:** {note}", ""]
    write(bdir / "decision.md", "\n".join(block))
    st["stages"]["gate"] = {"invariant": signed, "note": note or "", "at": dt.datetime.now().isoformat()}
    st["status"] = "approved"
    save_state(st)
    log(f"{bet_id} approved. Next: epd_loop.py next")


def reject(bet_id: str, why: str) -> None:
    st = load_state(bet_id)
    if st["status"] != "proposed":
        die(f"{bet_id} is {st['status']}, not proposed")
    write(BETS_DIR / bet_id / "decision.md", f"## Owner's decision\n\nRejected on {dt.date.today().isoformat()}: {why}\n")
    st["stages"]["gate"] = {"rejected": why, "at": dt.datetime.now().isoformat()}
    st["status"] = "rejected"
    save_state(st)
    ledger_upsert(bet_id, outcome=f"rejected: {why}")
    log(f"{bet_id} rejected. `next` starts a new bet from a fresh report.")


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
        "verify_verdict", "security_verdict", "deploy_url", "verdict", "verdict_summary",
        "changes_wanted_by", "security_human_actions")}
    verdict = out.get("verdict")
    st["status"] = "built" if verdict == "approve" else "build_failed"
    save_state(st)
    log(f"build: verdict={verdict} ({out.get('verdict_summary')}) commit={out.get('implement_commit')} url={out.get('deploy_url')}")
    if verdict != "approve":
        log(f"the build did not pass its judges; see {bdir / 'build.json'}. "
            f"Fix by hand and `epd_loop.py stage ship --bet {bet_id}`, or leave it.")


def stage_ship(st: dict) -> None:
    bet_id = st["bet_id"]
    bdir = BETS_DIR / bet_id
    b = st["stages"].get("build") or {}
    branch = b.get("branch")
    wt = b.get("worktree_path")
    if not branch or not wt:
        die("no build to ship")
    # Fetch from the main clone, never from the worktree. A worktree's `.git`
    # is a file holding `gitdir: /app/workspaces/.../main/.git/worktrees/<n>`
    # -- a *container* path, absent on this side of the mount -- so serving
    # from the worktree dies with "not a git repository", which is exactly
    # how the first full run failed after a clean build. The branch is an
    # ordinary ref in the parent clone, and that is a real repository here.
    # (`safe.directory`: the clone belongs to the container's user.)
    host_wt = hpath(wt)
    if not host_wt.exists():
        log(f"note: worktree gone from the host ({host_wt}); its branch is in the clone regardless")
    trust_main_clone()
    sh(["git", "fetch", "--force", str(MAIN_CLONE), f"{branch}:refs/heads/{branch}"], cwd=REPO_CHECKOUT)
    sh(["git", "push", "--force-with-lease", "-u", "origin", branch], cwd=REPO_CHECKOUT)
    bet = st["stages"].get("bet") or {}
    body = (
        f"EPD loop bet **{bet_id}** — {bet.get('title')}\n\n"
        f"**Problem:** {bet.get('problem')}\n\n"
        f"**Invariant (signed):** {(st['stages'].get('gate') or {}).get('invariant') or bet.get('invariant')}\n\n"
        f"**Success threshold:** {bet.get('threshold')}\n\n"
        f"Judges on the candidate: review={b.get('review_verdict')}, QA={b.get('verify_verdict')}, "
        f"security={b.get('security_verdict')} → {b.get('verdict')} ({b.get('verdict_summary')}).\n\n"
        f"Dev stack of this branch: {b.get('deploy_url')}\n\n"
        f"Artifacts: `{bdir}` (report.md, bet.md, tasks.json, build.json).\n"
    )
    write(bdir / "pr.md", body)
    pr = open_or_find_pr(branch, f"{bet_id}: {bet.get('title')}", body)
    pr_url, pr_number = pr.get("html_url"), pr.get("number")
    if not pr_url or not pr_number:
        die(f"could not open or find the PR for {branch}")
    st["stages"]["ship"] = {"pr": pr_url, "pr_number": pr_number, "branch": branch,
                            "at": dt.datetime.now().isoformat()}
    save_state(st)
    log(f"PR: {pr_url}")

    # Merge. No human seat here by the owner's decision: the pipeline's own
    # judges (review, QA, security) are the gate, and the gate node already
    # said approve or this stage would not run.
    owner, repo = GH_REPO.split("/", 1)
    merged = github("PUT", f"/repos/{owner}/{repo}/pulls/{pr_number}/merge",
                    {"merge_method": "squash",
                     "commit_title": f"{bet_id}: {bet.get('title')} (#{pr_number})"})
    log(f"merged PR #{pr_number}: {merged.get('message') or merged.get('sha', '')[:12]}")
    sh(["git", "fetch", "-q", "origin"], cwd=REPO_CHECKOUT)
    sh(["git", "checkout", "-q", BASE_BRANCH], cwd=REPO_CHECKOUT)
    sh(["git", "merge", "--ff-only", f"origin/{BASE_BRANCH}"], cwd=REPO_CHECKOUT)
    merge_sha = sh(["git", "rev-parse", "HEAD"], cwd=REPO_CHECKOUT).stdout.strip()
    st["stages"]["ship"].update({"merged": True, "merge_sha": merge_sha})
    save_state(st)
    log(f"merged into {BASE_BRANCH} as {merge_sha[:12]}")

    deploy_prod(merge_sha)
    qa_ok = ensure_qa_on_prod()
    st["stages"]["ship"].update({"prod_url": PROD_URL, "prod_env": PROD_ENV, "prod_qa": qa_ok,
                                 "deployed_at": dt.datetime.now().isoformat()})
    st["status"] = AFTER["ship"]
    save_state(st)
    log(f"live: {PROD_URL} now runs {merge_sha[:12]}")


def stage_measure(st: dict, keep: bool) -> None:
    bet_id = st["bet_id"]
    bdir = BETS_DIR / bet_id
    b = st["stages"].get("build") or {}
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
    out = run_workflow("epd_measure", {
        "bet_id": bet_id,
        "outcome_path": cpath(bdir / "outcome.md"),
        "app_url": url,
        "data_url": data_url,
        "email": QA_EMAIL, "empty_email": QA_EMPTY_EMAIL, "password": password,
        "bet": bet_text(bdir),
        "report": read(bdir / "report.md"),
        "build_summary": b.get("implement_summary") or "",
    }, workspace=cpath(LOOP_DIR), timeout=2400)
    if not (bdir / "outcome.md").exists():
        die("epd_measure finished but wrote no outcome.md")
    verdict = out.get("verdict") or "iterate"
    # A criterion that could not fail did not pass. The agent is told this,
    # and the driver holds it to it: a kept verdict with a vacuous criterion
    # is downgraded here, because the ledger is what the next bet inherits
    # and it must not be truer than what was seen.
    vacuous = int(out.get("vacuous_criteria") or 0)
    if verdict == "kept" and (vacuous or out.get("threshold_met") is False):
        log(f"measure said kept, but {vacuous} criteria were vacuous / the threshold was not met — recording iterate")
        verdict = "iterate"
        out["verdict_downgraded_from"] = "kept"
    st["stages"]["measure"] = out
    st["status"] = verdict if verdict in TERMINAL else "iterate"
    save_state(st)
    note = f" [{vacuous} criteria vacuous]" if vacuous else ""
    ledger_upsert(bet_id, outcome=f"{verdict}{note}: {out.get('summary') or ''} "
                                 f"(right threshold: {out.get('right_threshold')})")
    log(f"measure: {verdict} — {out.get('summary')}")
    if out.get("unverified"):
        log(f"unverified on the running build: {out['unverified']}")
    if not keep and b.get("env_name"):
        standee_down(b["env_name"])


# ------------------------------------------------------------------- driver --

def run_stage(name: str, st: dict, keep: bool) -> None:
    if name == "report":
        stage_report(st, keep)
    elif name == "bet":
        stage_bet(st)
    elif name == "tasks":
        stage_tasks(st)
    elif name == "build":
        stage_build(st)
    elif name == "ship":
        stage_ship(st)
    elif name == "measure":
        stage_measure(st, keep)
    else:
        die(f"unknown stage {name}")


def cmd_next(until: str | None, auto_approve: bool, keep: bool) -> None:
    bet_id = open_bet() or new_bet_id()
    st = load_state(bet_id)
    if st["status"] == "new":
        mkdir_shared(BETS_DIR / bet_id)
        ledger_upsert(bet_id, status="new")
    while True:
        status = st["status"]
        if status == "proposed" and auto_approve:
            approve(bet_id, None, "auto-approved (wiring exercise)")
            st = load_state(bet_id)
            continue
        stage = NEXT_STAGE.get(status)
        if stage is None:
            if status == "proposed":
                log(f"{bet_id} is waiting for you: approve or reject (see bets/{bet_id}/bet.md)")
            elif status in TERMINAL:
                log(f"{bet_id} is finished ({status}); `next` again starts a new bet")
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
        print("no bets yet")
        return
    for r in rows:
        print(f"{r['bet_id']}  {r['date']}  {r['status']:13s}  {r['title'][:60]}")
        if r.get("outcome"):
            print(f"      {r['outcome'][:120]}")
    b = open_bet()
    if b:
        st = load_state(b)
        print(f"\nopen bet: {b} ({st['status']}); next stage: {NEXT_STAGE.get(st['status']) or 'waiting on you'}")


def cmd_down(bet_id: str) -> None:
    st = load_state(bet_id)
    for key in ("report", "build"):
        env = (st["stages"].get(key) or {}).get("env") or (st["stages"].get(key) or {}).get("env_name")
        if env:
            standee_down(env)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    n = sub.add_parser("next")
    n.add_argument("--until", choices=STAGES)
    n.add_argument("--auto-approve", action="store_true")
    n.add_argument("--keep", action="store_true", help="leave the stacks up")
    a = sub.add_parser("approve")
    a.add_argument("bet")
    a.add_argument("--invariant")
    a.add_argument("--note")
    r = sub.add_parser("reject")
    r.add_argument("bet")
    r.add_argument("--why", required=True)
    s = sub.add_parser("stage")
    s.add_argument("stage", choices=STAGES)
    s.add_argument("--bet", required=True)
    s.add_argument("--keep", action="store_true")
    d = sub.add_parser("down")
    d.add_argument("bet")
    args = ap.parse_args()

    mkdir_shared(BETS_DIR)
    if not LEDGER.exists():
        ledger_write([])
    for f in ("goals.md", "profile.md"):
        if not (LOOP_DIR / f).exists():
            die(f"{LOOP_DIR / f} is missing")

    if args.cmd == "status":
        cmd_status()
    elif args.cmd == "next":
        cmd_next(args.until, args.auto_approve, args.keep)
    elif args.cmd == "approve":
        approve(args.bet, args.invariant, args.note)
    elif args.cmd == "reject":
        reject(args.bet, args.why)
    elif args.cmd == "stage":
        st = load_state(args.bet)
        run_stage(args.stage, st, args.keep)
    elif args.cmd == "down":
        cmd_down(args.bet)


if __name__ == "__main__":
    main()
