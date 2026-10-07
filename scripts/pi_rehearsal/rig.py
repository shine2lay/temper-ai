"""The Pi rehearsal rig: real member boxes with a scripted model, on an isolated compose project.

Queue #74 built it for the preliminary normal run; #54 adds its scenarios. Manual only: the gate
never runs it. Run each step from a temper-ai checkout, under ``systemd-run --user``:

    uv run --frozen python scripts/pi_rehearsal/rig.py prepare --label preparation --head <rev>
    uv run --frozen python scripts/pi_rehearsal/rig.py build|create|up|down --rig <root>
    uv run --frozen python scripts/pi_rehearsal/rig.py drive --rig <root> --via api|page [--runs N]

prepare  makes /tmp/pi-rehearsal/<id>/ (0700): the rig's own clone at <head>, its dashboard
         built, copies of production's pins (digest-matched, never bound), the rehearsal box
         config, the stand-in's CA, synthetic roles, the test helper (stub bridge,
         project_roots []), throwaway API keys and compose.env; and the record folder under
         ~/kept-from-tmp/<date>/pi-rehearsal/prelim/.
build    builds the rig's server and worker images from its checkout.
create   creates the containers without starting them, then the mount check (audit.py).
up       starts the test helper and the rig; refuses while any member box exists on the host.
drive    runs the bundled normal scenario (scenario.py), then reads it back (checks.py).
down     removes the rig's containers, volumes, images and helper; the record stays.

Production is only read: its box config and pins (copied), its guard mode, its containers'
start times and its Pi lane line. Nothing here starts, stops or writes a live container. The
owner key never leaves its 0600 file: the page journey reads it from there, this script only
puts it in request headers.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import audit  # noqa: E402
import checks  # noqa: E402

RIGS = Path("/tmp/pi-rehearsal")
PREFIX = "pi-rehearsal-"
HOME = Path.home()
PIN_HOME = HOME / ".local/share/temper"
PROD_BOX_CONFIG = HOME / "temper-ai/local/pi/pi-box.json"
RECORDS = HOME / "kept-from-tmp"
LIVE = ("temper-ai-server-1", "temper-ai-worker-1", "temper-ai-postgres-1", "temper-ai-redis-1")
SERVICES = ("postgres", "redis", "server", "worker", "pi-worker", "standin")
MEMBERS = ("product", "design", "architecture", "frontend", "qa")
LEADER = "product"
SLOT = "anthropic-4"
OWNER_KEY = "owner-dashboard"
UPSTREAM_PORT = 18443
HELPER_BASE = "rehearsal"
HELPER_SLOT = "rehearsal-2"
MIN_TURNS = 11
#: Commits the counted runs must contain (#75, frontend #8, ADR-M4-21's role view).
LANDED = {"#75": "200dbc64", "frontend #8": "cd37248e", "role view (ADR-M4-21)": "2fda8e05"}
TERMINAL = {"completed", "failed", "cancelled", "error", "stopped", "timeout"}
RUN_ID = re.compile(r"[A-Za-z0-9_-]{8,80}\Z")
#: pi-worker roots that must be read-only as mounted (PW03).
PW03_PATHS = ("projects", "share", "roles", "boxcfg")
#: The synthetic role folders (the box config's identities_dir). Not named "identities", so
#: the chats' role-folder guard never mistakes the rig's tree for the live role folders.
ROLES_DIR = "roles"
PW03_APP = ("/app/temper_ai", "/app/configs", "/app/.git")
DROP_VIEW = {"body", "text", "summary", "goal", "note", "owner_words", "question", "reason",
             "about", "output", "args", "content", "prompt", "words", "message", "detail"}


class RigError(RuntimeError):
    """A rig step failed; the message says which and why."""


# --------------------------------------------------------------------------- plumbing


def clean_env(**extra: str) -> dict[str, str]:
    """Only PATH and HOME from this shell: no COMPOSE_*, TEMPER_* or keys leak into the rig."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(HOME), "LANG": "C.UTF-8"}
    env.update(extra)
    return env


def user_bus_env() -> dict[str, str]:
    """clean_env plus what systemd-run --user and systemctl --user need to reach the user bus."""
    extra = {"XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"}
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        extra["DBUS_SESSION_BUS_ADDRESS"] = os.environ["DBUS_SESSION_BUS_ADDRESS"]
    return clean_env(**extra)


def sh(*cmd: Any, cwd: Path | None = None, env: dict | None = None, input: str | None = None,
       check: bool = True, timeout: float | None = 600) -> subprocess.CompletedProcess:
    proc = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env or clean_env(), input=input,
                          capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise RigError(f"{' '.join(str(c) for c in cmd[:3])} failed ({proc.returncode}): "
                       f"{proc.stderr.strip()[-600:]}")
    return proc


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def write_json(path: Path, data: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")
    os.chmod(path, mode)


def write_text(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.chmod(path, mode)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mkdir(path: Path, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)
    return path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def load(root: Path) -> dict:
    root = root.resolve()
    if root.parent != RIGS or not (root / "rig.json").is_file():
        raise RigError(f"not a rig: {root}")
    return json.loads((root / "rig.json").read_text())


def save(state: dict) -> None:
    write_json(Path(state["root"]) / "rig.json", state)


def compose(state: dict, *args: str, timeout: float = 1800) -> subprocess.CompletedProcess:
    co = Path(state["checkout"])
    return sh("docker", "compose", "-p", state["project"],
              "--env-file", Path(state["root"]) / "compose.env",
              "-f", co / "docker-compose.yml",
              "-f", co / "scripts/pi_rehearsal/docker-compose.rehearsal.yml",
              "--profile", "worker", "--profile", "pi", *args, cwd=co, timeout=timeout)


def inspect(*ids: str) -> list[dict]:
    return json.loads(sh("docker", "inspect", *ids).stdout) if ids else []


def project_containers(state: dict) -> dict[str, dict]:
    ids = sh("docker", "ps", "-aq", "--filter",
             f"label=com.docker.compose.project={state['project']}").stdout.split()
    out = {}
    for c in inspect(*ids):
        out[c["Config"]["Labels"]["com.docker.compose.service"]] = c
    return out


def cid(state: dict, service: str) -> str:
    return state["created"][service]


def psql(state: dict, sql: str) -> list[str]:
    out = sh("docker", "exec", cid(state, "postgres"), "psql", "-U", "temper_ai", "-d",
             "temper_ai", "-tAc", sql, timeout=30).stdout
    return [line for line in out.splitlines() if line.strip()]


def owner_key(state: dict) -> str:
    return (Path(state["root"]) / "keys" / f"{OWNER_KEY}.key").read_text().strip()


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(state: dict, method: str, path: str, body: Any = None, timeout: float = 30) -> Any:
    request = urllib.request.Request(
        f"http://127.0.0.1:{state['port']}{path}", method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {owner_key(state)}",
                 "Content-Type": "application/json"})
    try:
        with _OPENER.open(request, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise RigError(f"{method} {path}: HTTP {exc.code} "
                       f"{exc.read().decode(errors='replace')[:400]}") from None
    return json.loads(raw) if raw else None


def wait_for(what: str, probe, timeout: float, every: float = 2.0) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = probe()
        except (RigError, OSError, ValueError) as exc:
            last = exc
        else:
            if last:
                return last
        time.sleep(every)
    raise RigError(f"timed out waiting for {what} ({last!r})"[:600])


# --------------------------------------------------------------------------- production (read)


def live_names() -> list[str]:
    names = set(sh("docker", "ps", "-a", "--format", "{{.Names}}").stdout.split())
    return [n for n in LIVE if n in names]


def prod_state() -> dict:
    """Production, read only: live start times, guard mode, Pi lane line, Pi keys in Redis."""
    names = live_names()
    started = {c["Name"].lstrip("/"): c["State"]["StartedAt"] for c in inspect(*names)}
    guard = sh("docker", "exec", "temper-ai-server-1", "printenv", "TEMPER_API_GUARD",
               check=False).stdout.strip()
    status = sh("temper-deploy", "status", check=False, timeout=120).stdout
    line = next((ln.strip() for ln in status.splitlines() if "Pi lane" in ln), "")
    keys = None
    if "temper-ai-redis-1" in names:
        scan = sh("docker", "exec", "temper-ai-redis-1", "redis-cli", "--scan", "--pattern",
                  "temper:pi:*", check=False)
        keys = len(scan.stdout.split()) if scan.returncode == 0 else None
    return {"at": now(), "started": started, "guard": guard, "pi_lane_line": line,
            "pi_lane_off": line == "Pi lane: off.", "redis_pi_keys": keys}


# --------------------------------------------------------------------------- prepare


def pin_copy(value: str, share: Path) -> str:
    """Copy one production pin into the rig's share (same relative path); never bind it."""
    src = Path(value).resolve(strict=True)
    base = PIN_HOME.resolve(strict=True)
    if not audit.inside(src, base):
        raise audit.RigRefusal(f"a pin outside {base}: {value}")
    dst = share / src.relative_to(base)
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        sh("cp", "-a", "--reflink=auto", src, dst)
    return str(dst)


def rig_box_config(prod: dict, root: Path) -> dict:
    """Production's box config with copied pins, the rig's roots and mode rehearsal."""
    share = mkdir(root / "share", 0o755)
    cfg = copy.deepcopy(prod)
    for key in ("image_tar", "runtime_dir", "identity_extension", "identity_config"):
        if cfg.get(key):
            cfg[key] = pin_copy(cfg[key], share)
    for add in (cfg.get("add_ons") or {}).values():
        add["dir"] = pin_copy(add["dir"], share)
    for route in (cfg.get("routes") or {}).values():
        for key in ("extension", "catalog"):
            if route.get(key):
                route[key] = pin_copy(route[key], share)
    roots = [root / "state/runs", root / "sock", share, root / ROLES_DIR, root / "projects"]
    providers = sorted({r["provider"] for r in (cfg.get("routes") or {}).values()})
    cfg.update(
        identities_dir=str(root / ROLES_DIR), state_root=str(root / "state/runs"),
        socket_root=str(root / "sock"), host_helper_socket=str(root / "sock/host.sock"),
        roots=[str(p) for p in roots], project_roots=[str(root / "projects")],
        mode="rehearsal",
        rehearsal={"upstream_port": UPSTREAM_PORT, "ca_pem": str(share / "ca/ca.pem"),
                   "tokens": {p: f"sk-ant-oat01-rehearsal-{secrets.token_hex(24)}"
                              for p in providers}})
    leftover = []

    def walk(value: Any, where: str) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{where}.{k}" if where else k)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{where}[{i}]")
        elif isinstance(value, str) and value.startswith(str(HOME)) and where != "host_home":
            leftover.append(where)

    walk(cfg, "")
    if leftover:
        raise audit.RigRefusal(f"box config settings still point into the home folder: {leftover}")
    return cfg


def settings_map(cfg: dict, root: Path, co: Path) -> dict[str, str]:
    """Each bind source's name: the box-config setting (or rig setting) it comes from."""
    out = {k: cfg[k] for k in ("state_root", "socket_root", "identities_dir", "runtime_dir",
                                "identity_extension", "identity_config", "image_tar",
                                "host_helper_socket") if cfg.get(k)}
    for name, add in (cfg.get("add_ons") or {}).items():
        out[f"add_ons.{name}.dir"] = add["dir"]
    for name, route in (cfg.get("routes") or {}).items():
        for key in ("extension", "catalog"):
            if route.get(key):
                out[f"routes.{name}.{key}"] = route[key]
    out["rehearsal.ca_pem"] = cfg["rehearsal"]["ca_pem"]
    for key in ("roots", "project_roots"):
        for i, path in enumerate(cfg.get(key) or []):
            out[f"{key}[{i}]"] = path
    out.update({"rig checkout": str(co), "WORKSPACE_DIR": str(root / "workspaces"),
                "TEMPER_PI_BOX_CONFIG folder": str(root / "boxcfg"),
                "rig stand-in folder": str(root / "standin"),
                "PW02 docker socket": "/var/run/docker.sock"})
    return out


def production_roots(prod: dict, settings: dict[str, str]) -> dict[str, Any]:
    """For each box-config setting the rig names, production's value (paths only)."""
    out: dict[str, Any] = {}
    for name in settings:
        value: Any = prod
        for part in name.split("."):
            m = re.fullmatch(r"(.+)\[(\d+)\]", part)
            if isinstance(value, dict) and m and isinstance(value.get(m[1]), list):
                items = value[m[1]]
                value = items[int(m[2])] if int(m[2]) < len(items) else None
            elif isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
        out[name] = value if isinstance(value, str) else None
    return out


def make_ca(root: Path, hosts: list[str]) -> None:
    """The stand-in's CA (ca.pem for the boxes, rehearsal only) and its leaf; the CA key
    is deleted once the leaf is signed."""
    work = mkdir(root / "ca-work")
    try:
        sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3",
           "-keyout", work / "ca.key", "-out", work / "ca.pem",
           "-subj", f"/CN=pi rehearsal {root.name} CA",
           "-addext", "basicConstraints=critical,CA:TRUE",
           "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        sh("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", work / "leaf.key",
           "-out", work / "leaf.csr", "-subj", f"/CN={hosts[0]}")
        write_text(work / "ext.cnf", "subjectAltName=" + ",".join(f"DNS:{h}" for h in hosts)
                   + "\nbasicConstraints=CA:FALSE\nextendedKeyUsage=serverAuth\n")
        sh("openssl", "x509", "-req", "-in", work / "leaf.csr", "-CA", work / "ca.pem",
           "-CAkey", work / "ca.key", "-CAcreateserial", "-days", "3",
           "-extfile", work / "ext.cnf", "-out", work / "leaf.pem")
        mkdir(root / "share/ca", 0o755)
        shutil.copyfile(work / "ca.pem", root / "share/ca/ca.pem")
        os.chmod(root / "share/ca/ca.pem", 0o644)
        tls = mkdir(root / "standin/tls")
        for name in ("leaf.pem", "leaf.key"):
            shutil.copyfile(work / name, tls / name)
            os.chmod(tls / name, 0o600)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def make_roles(root: Path) -> None:
    """Synthetic role folders named like the trial's members; never the live identities."""
    for role in MEMBERS:
        d = mkdir(root / ROLES_DIR / role, 0o755)
        mkdir(d / "notes", 0o755)
        mkdir(d / "skills", 0o755)
        write_json(d / "identity.json", {
            "id": role, "title": f"Rehearsal {role}",
            "homeChat": f"/home/owner/.pi/sessions/rehearsal-{role}.jsonl",
            "prompt": "prompt.md", "skills": {"own": True, "shared": []},
            "tools": {"allow": None, "deny": []}, "unique": False}, 0o644)
        write_text(d / "about.md", f"# {role}\n\nA synthetic role for the Pi rehearsal rig. It "
                                   "holds nothing real.\n", 0o644)
        write_text(d / "prompt.md", f"You are the rehearsal {role}. A scripted stand-in plays "
                                    "your turns.\n", 0o644)
        write_text(d / "notebook.md", "## Rehearsal\n- synthetic notebook\n", 0o644)


def make_helper(root: Path, co: Path) -> dict:
    """The test helper (#50) with a stub bridge and stub pi that count calls; base rehearsal,
    project_roots [] (branch verb off), as the first-trial profile sets it."""
    spec = importlib.util.spec_from_file_location(
        "rig_pi_host", co / "scripts/pi_host/temper_pi_host.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # its dataclasses look their module up while it loads
    spec.loader.exec_module(mod)
    helper = mkdir(root / "helper")
    agent = mkdir(helper / "agent")
    mkdir(helper / "home")
    mod.write_stub_sdk(helper / "sdk", base=HELPER_BASE, version=mod.SELFTEST_SDK_VERSION)
    write_json(agent / "multi-pass.json",
               {"subscriptions": [{"provider": HELPER_BASE, "index": 2}]})
    expires = int(time.time() * 1000) + 6 * 3600 * 1000
    write_json(agent / "auth.json", {HELPER_SLOT: {
        "type": "oauth", "access": "rehearsal-not-a-token", "refresh": "rehearsal-not-a-token",
        "expires": expires}})
    mod.write_stub_pi(helper / "stub_pi.py", mod.SELFTEST_PI_VERSION)
    node = shutil.which("node")
    if not node:
        raise RigError("node isn't on PATH (the helper's bridge needs it)")
    config = {
        "socket": str(root / "sock/host.sock"), "uid": os.getuid(),
        "pi_state_root": str(root / "state/runs"), "home": str(helper / "home"),
        "pi_agent_dir": str(agent),
        "path": [d for d in os.environ.get("PATH", "").split(":") if d and Path(d).is_dir()],
        "pi_cli": ["/usr/bin/python3", str(helper / "stub_pi.py")],
        "base_provider": HELPER_BASE, "allowed_slots": [HELPER_SLOT],
        "bridge": {"node": node, "script": str(co / "scripts/pi_host/temper_pi_host_bridge.mjs"),
                   "sdk_root": str(helper / "sdk"), "sdk_version": mod.SELFTEST_SDK_VERSION,
                   "ai_version": mod.SELFTEST_SDK_VERSION},
        "project_roots": [], "branch_enabled": False, "tokens_per_hour": 120,
        "token_timeout_s": 30}
    write_json(helper / "config.json", config)
    return {"config": str(helper / "config.json"), "log": str(helper / "helper.log"),
            "stub_events": str(helper / "sdk/stub-events.log")}


def make_keys(root: Path) -> None:
    keys = mkdir(root / "keys")
    raw = "tk_" + secrets.token_urlsafe(32)
    write_text(keys / f"{OWNER_KEY}.key", raw)
    write_json(root / "workspaces/.api-keys.json",
               {"keys": {OWNER_KEY: "sha256:" + hashlib.sha256(raw.encode()).hexdigest()}},
               0o644)


def check_pins(config: Path) -> dict:
    from temper_ai.pi_agent import pins

    return pins.check_pins(str(config))


def cmd_prepare(args: argparse.Namespace) -> Path:
    if args.label not in ("preparation", "evidence"):
        raise RigError("--label is preparation or evidence")
    repo = Path(sh("git", "-C", HERE, "rev-parse", "--show-toplevel").stdout.strip())
    sha = sh("git", "-C", repo, "rev-parse", "--verify", f"{args.head}^{{commit}}").stdout.strip()
    guard = sh("docker", "exec", "temper-ai-server-1", "printenv", "TEMPER_API_GUARD",
               check=False).stdout.strip()
    if guard not in ("record", "enforce"):
        raise audit.RigRefusal(f"production's guard mode reads {guard!r}, below record")
    rig_id = args.id or secrets.token_hex(4)
    if not re.fullmatch(r"[0-9a-f]{8}", rig_id):
        raise RigError("--id is 8 hex digits")
    mkdir(RIGS)
    root = RIGS / rig_id
    root.mkdir(mode=0o700)
    project = PREFIX + rig_id
    co = root / "checkout"
    print(f"rig {rig_id}: cloning {sha[:12]}", flush=True)
    sh("git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", repo, co)
    sh("git", "-C", co, "checkout", "--quiet", "--detach", sha)
    sh("git", "-C", co, "remote", "remove", "origin")
    tree = sh("git", "-C", co, "rev-parse", "HEAD^{tree}").stdout.strip()
    landed = {name: sh("git", "-C", co, "merge-base", "--is-ancestor", commit, "HEAD",
                       check=False).returncode == 0 for name, commit in LANDED.items()}
    rig_dir = co / "scripts/pi_rehearsal"
    mine = {p.name: sha256(p) for p in sorted(HERE.iterdir())
            if p.is_file() and p.suffix in (".py", ".yml", ".md")}
    if args.label == "preparation":
        mkdir(rig_dir, 0o755)
        for name in mine:
            shutil.copy2(HERE / name, rig_dir / name)
        rig_files = {"source": "copied from the worktree, uncommitted (preparation only)",
                     "sha256": mine}
    else:
        theirs = {name: sha256(rig_dir / name) for name in mine if (rig_dir / name).is_file()}
        if theirs != mine:
            raise audit.RigRefusal("evidence runs run the committed rig: the head's "
                                   "scripts/pi_rehearsal differs from this one")
        if not all(landed.values()):
            raise audit.RigRefusal(f"evidence head lacks a landed commit: {landed}")
        rig_files = {"source": "committed at the head", "sha256": mine}

    print("building the dashboard in the rig's checkout", flush=True)
    sh("npm", "ci", "--no-audit", "--no-fund", cwd=co / "frontend", timeout=1200)
    sh("npm", "run", "build", cwd=co / "frontend", timeout=1200)
    if not (co / "frontend/dist/index.html").is_file():
        raise RigError("the dashboard build left no frontend/dist/index.html")

    print("copying production's pins and checking their digests", flush=True)
    prod = json.loads(PROD_BOX_CONFIG.read_text())
    for d in ("state/runs", "sock", ROLES_DIR, "projects", "boxcfg", "standin/gates"):
        mkdir(root / d, 0o755 if d in (ROLES_DIR, "projects") else 0o700)
    mkdir(root / "workspaces", 0o777)
    cfg = rig_box_config(prod, root)
    box_config = root / "boxcfg/pi-box.json"
    write_json(box_config, cfg)
    prod_pins, rig_pins = check_pins(PROD_BOX_CONFIG), check_pins(box_config)
    from temper_ai.pi_agent import pins

    if prod_pins["result"] != "pass" or rig_pins["result"] != "pass" or (
            pins.digests(prod_pins) != pins.digests(rig_pins)):
        raise audit.RigRefusal(f"pins don't match: production {prod_pins['result']}, "
                               f"rig {rig_pins['result']}")
    make_ca(root, sorted({r["host"] for r in cfg["routes"].values()}))
    make_roles(root)
    helper = make_helper(root, co)
    make_keys(root)
    write_text(co / "configs/team/local/team.yaml", (
        "# The rehearsal rig's team settings: the first trial's profile (ADR-M4-19, ADR-M4-22).\n"
        "# Written by scripts/pi_rehearsal/rig.py in the rig's own checkout only.\n"
        "project_roots: []\n"
        f"owner_callers: [{OWNER_KEY}]\n"
        f"account_slots: [{SLOT}]\n"
        "account_pick: settings_order\n"), 0o644)
    port = free_port()
    env = {
        "COMPOSE_PROJECT_NAME": project, "RIG_ID": rig_id, "RIG_ROOT": str(root),
        "RIG_PORT": str(port), "RIG_UPSTREAM_PORT": str(UPSTREAM_PORT),
        "RIG_UID": str(os.getuid()), "RIG_GID": str(os.getgid()), "RIG_SCENARIO": "normal",
        "WORKSPACE_DIR": str(root / "workspaces"), "POSTGRES_PASSWORD": secrets.token_hex(16),
        "TEMPER_API_GUARD": guard, "TEMPER_PI_WORKER_IMAGE": f"pi-rehearsal-worker:{rig_id}",
        "TEMPER_PI_BOX_CONFIG": str(box_config),
        "TEMPER_DOCKER_TEMPLATE_CONTAINER": f"{project}-server-1",
        "DOCKER_GID": str(os.stat("/var/run/docker.sock").st_gid), "TEMPER_LOG_LEVEL": "INFO"}
    write_text(root / "compose.env", "".join(f"{k}={v}\n" for k, v in env.items()))
    day = dt.datetime.now().astimezone().date().isoformat()
    record = RECORDS / day / "pi-rehearsal/prelim" / f"{args.label}-{rig_id}"
    mkdir(record)
    settings = settings_map(cfg, root, co)
    state = {
        "id": rig_id, "project": project, "root": str(root), "checkout": str(co),
        "label": args.label, "head": sha, "tree": tree, "landed": landed,
        "landed_commits": LANDED, "rig_files": rig_files, "port": port, "record": str(record),
        "guard": guard, "image_id": prod["image"], "pins": pins.digests(rig_pins),
        "pin_checks": {"production": prod_pins, "rig": rig_pins}, "settings": settings,
        "production_roots": production_roots(prod, settings), "helper": helper,
        "helper_unit": f"pi-rehearsal-helper-{rig_id}", "created": {}, "runs": [],
        "prepared_at": now()}
    save(state)
    write_json(record / "prepare.json", {k: v for k, v in state.items() if k != "runs"})
    print(f"prepared rig {rig_id}: root {root}, project {project}, head {sha[:12]}, "
          f"landed {landed}, record {record}", flush=True)
    return root


# --------------------------------------------------------------------------- build, create


def cmd_build(state: dict) -> None:
    compose(state, "build", "server", "worker", timeout=3600)
    state["images"] = {
        name: sh("docker", "image", "inspect", "--format", "{{.Id}}",
                 f"pi-rehearsal-{name}:{state['id']}").stdout.strip()
        for name in ("server", "worker")}
    save(state)
    print(f"built {state['images']}", flush=True)


def cmd_create(state: dict) -> None:
    """Create every container, start none, and check every mount before anything runs."""
    compose(state, "create", "--pull", "never", "--no-build", *SERVICES)
    containers = project_containers(state)
    if set(containers) != set(SERVICES):
        raise audit.RigRefusal(f"the rig's containers are {sorted(containers)}, "
                               f"not {sorted(SERVICES)}")
    result = audit.mount_check(list(containers.values()), root=Path(state["root"]),
                               checkout=Path(state["checkout"]), project=state["project"])
    nets = []
    for net in inspect(*sh("docker", "network", "ls", "-q", "--filter",
                           f"label=com.docker.compose.project={state['project']}").stdout.split()):
        nets.append({"name": net["Name"], "internal": net.get("Internal"),
                     "driver": net.get("Driver"),
                     "masquerade": (net.get("Options") or {}).get(
                         "com.docker.network.bridge.enable_ip_masquerade")})
    rig_net = [n for n in nets if n["name"].endswith("_rig")]
    if not rig_net or rig_net[0]["internal"] is not True:
        raise audit.RigRefusal("the rig network isn't internal")
    result.update(networks=nets, checked_at=now(), head=state["head"])
    write_json(Path(state["record"]) / "mount-check.json", result)
    state["created"] = {s: c["Id"] for s, c in containers.items()}
    state["mount_check"] = {"result": result["result"], "checked_at": result["checked_at"],
                            "mounts": len(result["mounts"])}
    save(state)
    print(f"mount check {result['result']}: {len(result['mounts'])} mounts, networks "
          f"{[(n['name'], n['internal']) for n in nets]}", flush=True)


# --------------------------------------------------------------------------- up


def cmd_up(state: dict) -> None:
    boxes = sh("docker", "ps", "-aq", "--filter", "label=temper.pi.box=1").stdout.split()
    if boxes:
        raise audit.RigRefusal(f"{len(boxes)} member box(es) exist on this host; the rig's "
                               "pi-worker sweeps every member box at start-up")
    containers = project_containers(state)
    if {s: c["Id"] for s, c in containers.items()} != state["created"] or any(
            c["State"]["Status"] != "created" for c in containers.values()):
        raise audit.RigRefusal("the rig's containers changed since the mount check")
    state["prod_before"] = prod_state()
    save(state)
    root = Path(state["root"])
    log = state["helper"]["log"]
    sh("systemd-run", "--user", "--unit", state["helper_unit"], "--collect", "--quiet",
       "-p", f"StandardOutput=append:{log}", "-p", f"StandardError=append:{log}",
       "/usr/bin/python3", Path(state["checkout"]) / "scripts/pi_host/temper_pi_host.py",
       "serve", "--config", state["helper"]["config"], env=user_bus_env())
    wait_for("the test helper's socket", lambda: (root / "sock/host.sock").exists(), 60, 1)
    sh("docker", "start", cid(state, "postgres"), cid(state, "redis"))
    wait_for("postgres and redis healthy", lambda: all(
        c["State"].get("Health", {}).get("Status") == "healthy"
        for c in inspect(cid(state, "postgres"), cid(state, "redis"))), 120)
    sh("docker", "start", cid(state, "server"))
    wait_for("the rig's server", lambda: api(state, "GET", "/api/health") is not None, 180)
    sh("docker", "start", cid(state, "worker"), cid(state, "pi-worker"))
    sh("docker", "start", cid(state, "standin"))

    def roles_ready():
        pi = inspect(cid(state, "pi-worker"))[0]["State"]
        if not pi.get("Running"):
            raise RigError(f"pi-worker stopped (exit {pi.get('ExitCode')})")
        status = api(state, "GET", "/api/team/status")
        return status if status and status.get("roles_configured") else None

    status = wait_for("the Team page's roles (the Pi lane view)", roles_ready, 300, 3)

    def worker_ready():
        main = inspect(cid(state, "worker"))[0]["State"]
        if not main.get("Running"):
            raise RigError(f"the main worker stopped (exit {main.get('ExitCode')})")
        out = sh("docker", "logs", cid(state, "worker"), check=False)
        return "Watcher DB connected" in out.stdout + out.stderr

    wait_for("the main worker's watcher", worker_ready, 120, 2)
    stopped = {s: c["State"].get("ExitCode") for s, c in project_containers(state).items()
               if not c["State"].get("Running")}
    if stopped:
        raise RigError(f"rig service(s) stopped: {stopped}")
    logs = sh("docker", "logs", cid(state, "pi-worker"), check=False)
    startup = [ln for ln in (logs.stdout + logs.stderr).splitlines() if "Pi lane start-up" in ln]
    state["up"] = {"at": now(), "pi_lane_start_up": startup[-1:] or None,
                   "team_status_keys": sorted(status)}
    save(state)
    print(f"rig up on 127.0.0.1:{state['port']}; Pi lane start-up: {startup[-1:]}", flush=True)


# --------------------------------------------------------------------------- drive


class BoxWatcher(threading.Thread):
    """Names-only readings of every member box as Docker creates it (docker events)."""

    def __init__(self, state: dict) -> None:
        super().__init__(daemon=True)
        self.state = state
        self.rows: dict[str, dict] = {}
        self.proc = subprocess.Popen(
            ["docker", "events", "--filter", "type=container", "--filter",
             "label=temper.pi.box=1", "--format", "{{json .}}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=clean_env())

    def read(self, row: dict, container_id: str) -> None:
        try:
            container = inspect(container_id)[0]
        except (RigError, IndexError) as exc:
            row["inspect_error"] = str(exc)[:200]
            return
        settings, root = self.state["settings"], Path(self.state["root"])
        try:
            row["names"] = audit.names_only(container, settings=settings, root=root, member=True)
        except audit.RigRefusal as exc:
            row["refusal"] = str(exc)
            row["names"] = audit.names_only(container, settings=settings, root=root)

    def run(self) -> None:
        for line in self.proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            action = str(event.get("Action") or event.get("status") or "")
            if action not in ("create", "start", "die", "destroy"):
                continue
            attrs = (event.get("Actor") or {}).get("Attributes") or {}
            name = attrs.get("name", "?")
            row = self.rows.setdefault(name, {"name": name, "events": {}})
            row["events"].setdefault(action, event.get("time"))
            if action in ("create", "start") and "names" not in row:
                self.read(row, event.get("id") or (event.get("Actor") or {}).get("ID", ""))

    def stop(self) -> list[dict]:
        time.sleep(2)
        self.proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.proc.wait(5)
        return list(self.rows.values())


def size(path: str | Path) -> int:
    p = Path(path)
    return p.stat().st_size if p.exists() else 0


def tail_from(path: str | Path, offset: int) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    with open(p, "rb") as fh:
        fh.seek(offset)
        return fh.read().decode(errors="replace")


def run_status(state: dict, run_id: str) -> str:
    rows = psql(state, f"SELECT status FROM workflow_runs WHERE execution_id = '{run_id}'")
    return rows[0].strip() if rows else ""


def owner_messages(state: dict, run_id: str) -> int:
    rows = psql(state, "SELECT count(*) FROM pi_messages WHERE run_id = "
                       f"'{run_id}' AND sender_kind = 'owner'")
    return int(rows[0]) if rows else 0


def known_runs(state: dict) -> set[str]:
    return set(psql(state, "SELECT execution_id FROM workflow_runs"))


def start_page(state: dict, shots: Path) -> subprocess.Popen:
    """Frontend's live journey (frontend #8), unchanged, against the rig's dashboard."""
    mkdir(shots)
    env = clean_env(
        TEAM_JOURNEY_BASE_URL=f"http://127.0.0.1:{state['port']}",
        TEAM_JOURNEY_SHOTS_DIR=str(shots),
        TEAM_JOURNEY_OWNER_KEY_FILE=str(Path(state["root"]) / "keys" / f"{OWNER_KEY}.key"),
        TEAM_JOURNEY_ROLES=",".join(MEMBERS), TEAM_JOURNEY_PAUSE="1",
        TEAM_JOURNEY_TIMEOUT_S="600")
    out = open(shots / "playwright.log", "w")  # noqa: SIM115 - closed with the process
    return subprocess.Popen(["npx", "playwright", "test", "-c", "playwright.live.config.ts"],
                            cwd=Path(state["checkout"]) / "frontend", env=env, stdout=out,
                            stderr=subprocess.STDOUT)


def drive_one(state: dict, via: str) -> dict:
    root = Path(state["root"])
    index = len(state["runs"]) + 1
    gate = root / "standin/gates/owner-message"
    gate.unlink(missing_ok=True)
    offsets = {"standin": size(root / "standin/standin.jsonl"),
               "helper": size(state["helper"]["log"]),
               "stub_events": size(state["helper"]["stub_events"])}
    before = known_runs(state)
    watcher = BoxWatcher(state)
    watcher.start()
    started = now()
    page = None
    record = Path(state["record"])
    if via == "api":
        trial = api(state, "POST", "/api/team/trials", {
            "request_id": str(uuid.uuid4()),
            "goal": "Rehearsal: write NOTES.md for the team and agree it is done.",
            "members": [{"role": r} for r in MEMBERS], "leader": LEADER,
            "pause_after_rounds": 1, "communication": "all"})
        run_id = trial["execution_id"]
    else:
        page = start_page(state, record / "runs" / f"{index}-page")
        run_id = wait_for("the page's run to start", lambda: next(iter(
            known_runs(state) - before), None), 300, 2)
    if not RUN_ID.fullmatch(run_id):
        raise RigError("unexpected run id shape")
    run = {"index": index, "run_id": run_id, "via": via, "label": state["label"],
           "started": started, "offsets": offsets}
    state["runs"].append(run)
    save(state)
    print(f"run {index}: {run_id} ({via}) started {started}", flush=True)
    answered = messaged = gated = False
    deadline = time.monotonic() + 25 * 60
    status = ""
    try:
        while time.monotonic() < deadline:
            status = run_status(state, run_id)
            if via == "api" and status not in TERMINAL:
                waits = (api(state, "GET", f"/api/team/runs/{run_id}") or {}).get(
                    "open_waits") or []
                if waits and waits[0].get("kind") != "pause":
                    # Only the team's pause is in the bundled run; anything else is a finding,
                    # left open for the record, never answered by the driver.
                    raise RigError(f"an open wait of kind {waits[0].get('kind')!r} (answers "
                                   f"{[a.get('answer') for a in waits[0].get('answers') or []]})")
                if waits and not answered:
                    api(state, "POST",
                        f"/api/team/runs/{run_id}/waits/{waits[0]['wait_id']}/answer",
                        {"request_id": str(uuid.uuid4()), "answer": "continue", "text": ""})
                    answered = True
                elif answered and not messaged and not waits:
                    api(state, "POST", f"/api/team/runs/{run_id}/messages", {
                        "request_id": str(uuid.uuid4()), "to": LEADER,
                        "body": "Owner here: thanks, carry on and finish when the team agrees."})
                    messaged = True
            if not gated and owner_messages(state, run_id) > 0:
                gate.touch()
                gated = True
            if status in TERMINAL and (page is None or page.poll() is not None):
                break
            time.sleep(2)
        else:
            run["error"] = "the run didn't end within 25 minutes"
    except (RigError, OSError, ValueError) as exc:
        run["error"] = f"{type(exc).__name__}: {exc}"
        print(f"run {index}: driving stopped: {run['error']}", flush=True)
    run.update(ended=now(), status=status, gate_released=gated)
    if page is not None:
        if page.poll() is None:
            page.terminate()
        run["page_exit"] = page.wait(30)
    boxes = watcher.stop()
    save(state)
    readback(state, run, boxes)
    return run


def strip_view(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip_view(v) for k, v in value.items() if k not in DROP_VIEW}
    if isinstance(value, list):
        return [strip_view(v) for v in value]
    if isinstance(value, str) and len(value) > 200:
        return f"<{len(value)} characters dropped>"
    return value


def pw03_probe(state: dict) -> list[dict]:
    root = Path(state["root"])
    paths = [str(root / p) for p in PW03_PATHS] + list(PW03_APP)
    script = (
        "import errno, json, os, sys\n"
        "out = []\n"
        "for p in json.loads(sys.argv[1]):\n"
        "    probe = os.path.join(p, '.pw03-probe')\n"
        "    try:\n"
        "        open(probe, 'w').close()\n"
        "    except OSError as exc:\n"
        "        out.append({'path': p, 'errno': exc.errno, 'error': errno.errorcode.get(exc.errno)})\n"
        "    else:\n"
        "        os.unlink(probe)\n"
        "        out.append({'path': p, 'errno': None, 'error': 'WRITABLE'})\n"
        "print(json.dumps(out))\n")
    out = sh("docker", "exec", "-i", cid(state, "pi-worker"), "/app/.venv/bin/python", "-",
             json.dumps(paths), input=script).stdout
    return json.loads(out)


PREFLIGHT_PROBE = (
    "import json, os\n"
    "from temper_ai.database import init_database\n"
    "from temper_ai.runner.pi_preflight import preflight\n"
    "init_database(os.environ['TEMPER_DATABASE_URL'])  # as the watcher does (watch_queue.py)\n"
    "seen = {}\n"
    "failed = preflight(record=seen)\n"
    "print(json.dumps({'failed': [list(f) for f in failed], 'pins': seen.get('pins'),"
    " 'host_pi': seen.get('host_pi')}, default=str))\n")


def preflight_probe(state: dict) -> dict:
    """The real preflight (#51, with #53's pin check), unchanged, run once more inside the
    rig's pi-worker: what failed (nothing, when it passes) and the pins it checked."""
    proc = sh("docker", "exec", "-i", "-w", "/app", cid(state, "pi-worker"),
              "/app/.venv/bin/python", "-", input=PREFLIGHT_PROBE, check=False, timeout=120)
    lines = proc.stdout.strip().splitlines()
    try:
        return json.loads(lines[-1])
    except (IndexError, ValueError):
        return {"failed": [["unreadable", f"exit {proc.returncode}"]], "pins": None}


def log_counts(state: dict, run: dict, folder: Path) -> dict:
    texts = {}
    for service in SERVICES:
        proc = sh("docker", "logs", "--since", run["started"], cid(state, service), check=False)
        texts[service] = proc.stdout + proc.stderr
        write_text(folder / f"{service}.log", texts[service])
    every = "\n".join(texts.values())
    return {
        "failed_checkpoint": every.count("Failed to save checkpoint"),
        "guard_warnings": sum(t.count("api guard (") for t in texts.values()),
        "pi_preflight_refusals": sum(1 for ln in texts["pi-worker"].splitlines()
                                     if "refus" in ln.lower()),
        "main_worker_claims": texts["worker"].count(run["run_id"]),
        "pi_worker_mentions": texts["pi-worker"].count(run["run_id"]),
    }


def topology(state: dict) -> dict:
    settings, root = state["settings"], Path(state["root"])
    containers = project_containers(state)
    nets = [{"name": n["Name"], "internal": n.get("Internal"), "driver": n.get("Driver"),
             "masquerade": (n.get("Options") or {}).get(
                 "com.docker.network.bridge.enable_ip_masquerade")}
            for n in inspect(*sh("docker", "network", "ls", "-q", "--filter",
                                 f"label=com.docker.compose.project={state['project']}"
                                 ).stdout.split())]
    return {"containers": {s: audit.names_only(c, settings=settings, root=root)
                           for s, c in sorted(containers.items())},
            "networks": nets}


def readback(state: dict, run: dict, boxes: list[dict]) -> None:
    run_id = run["run_id"]
    folder = mkdir(Path(state["record"]) / "runs" / f"{run['index']}-{run_id[:8]}")
    co = Path(state["checkout"])
    ledger = json.loads(sh(
        "docker", "exec", "-i", "-w", "/app", cid(state, "server"), "/app/.venv/bin/python",
        "-", run_id, input=(co / "scripts/pi_rehearsal/readback_inner.py").read_text()).stdout)
    view = strip_view(api(state, "GET", f"/api/team/runs/{run_id}"))
    standin_text = Path(state["root"], "standin/standin.jsonl")
    all_rows = [json.loads(ln) for ln in tail_from(standin_text, 0).splitlines() if ln.strip()]
    rows = [json.loads(ln) for ln in tail_from(standin_text, run["offsets"]["standin"]
                                               ).splitlines() if ln.strip()]
    helper_text = tail_from(state["helper"]["log"], run["offsets"]["helper"])
    stub_text = tail_from(state["helper"]["stub_events"], run["offsets"]["stub_events"])
    helper = {"token": helper_text.count(" verb=token "),
              "branch": helper_text.count(" verb=branch "),
              "stub_mints": sum(1 for ln in stub_text.splitlines()
                                if ln.startswith(("get-auth", "write-auth")))}
    topo = topology(state)
    rig_guard = sh("docker", "exec", cid(state, "server"), "printenv", "TEMPER_API_GUARD",
                   check=False).stdout.strip()
    rig_view_key = sh("docker", "exec", cid(state, "redis"), "redis-cli", "--scan",
                      "--pattern", "temper:pi:*", check=False).stdout.split()
    prod_after = prod_state()
    before = state["prod_before"]
    report = None
    if run["via"] == "page":
        path = Path(state["record"]) / "runs" / f"{run['index']}-page" / "report.json"
        report = json.loads(path.read_text()) if path.is_file() else {}
        report["exit_code"] = run.get("page_exit")
    turns = {t.get("box_name"): t for t in ledger.get("pi_turns") or []}
    member_boxes = []
    for box in boxes:
        turn = turns.get(box["name"]) or {}
        member_boxes.append({"turn": {k: turn.get(k) for k in (
            "turn_id", "participant_id", "turn_no", "state", "account_slot", "started_at",
            "ended_at")},
            "events": box.get("events"), "refusal": box.get("refusal"),
            **(box.get("names") or {"inspect_error": box.get("inspect_error")})})
    names_file = {
        "label": state["label"], "run_id": run_id,
        "note": "Names only: no environment value, token or model-bound content.",
        "rig": {k: state[k] for k in ("project", "root", "checkout", "head", "tree")},
        "settings": state["settings"], "production_roots": state["production_roots"],
        "rehearsal_only": {"mounts": ["/box-ca/ca.pem"], "env_names": ["NODE_EXTRA_CA_CERTS"],
                           "why": "the stand-in's CA; a live box has neither"},
        "pi_worker": topo["containers"].get("pi-worker"), "member_boxes": member_boxes}
    data = {
        "run_id": run_id, "ledger": ledger, "run_view": view, "helper": helper,
        "driver_error": run.get("error"),
        "expected": {"image_id": state["image_id"], "min_turns": MIN_TURNS,
                     "owner_callers": [OWNER_KEY], "slot": SLOT, "head": state["head"],
                     "pins": state["pins"]},
        "boxes": [{"name": b["name"], "names": b.get("names"), "refusal": b.get("refusal")}
                  for b in boxes],
        "standin": rows, "standin_all": all_rows, "logs": log_counts(state, run, folder / "logs"),
        "guard_mode": rig_guard,
        "prod": {"before": before["started"], "after": prod_after["started"],
                 "guard_before": before["guard"], "guard_after": prod_after["guard"],
                 "pi_lane_off": prod_after["pi_lane_off"],
                 "pi_lane_line": prod_after["pi_lane_line"],
                 "redis_pi_keys_before": before["redis_pi_keys"],
                 "redis_pi_keys_after": prod_after["redis_pi_keys"],
                 "rig_redis_pi_keys": rig_view_key},
        "pw03": pw03_probe(state), "preflight": preflight_probe(state), "page": report}
    rows_out = checks.run_checks(data)
    ok = checks.passed(rows_out)
    write_json(folder / "ledger.json", ledger)
    write_json(folder / "run-view.json", view)
    write_json(folder / "topology.json", topo)
    write_json(folder / "member-boxes.names.json", names_file)
    write_json(folder / "readback.json", {k: v for k, v in data.items() if k != "ledger"})
    write_json(folder / "checks.json", {"label": state["label"], "run_id": run_id, "via": run["via"],
                                        "head": state["head"], "passed": ok, "rows": rows_out})
    run.update(passed=ok, folder=str(folder))
    save(state)
    failed = [r["name"] for r in rows_out if not r["ok"]]
    print(f"run {run['index']} {run_id}: status {run.get('status')}, checks "
          f"{len(rows_out) - len(failed)}/{len(rows_out)} ok", flush=True)
    for name in failed:
        print(f"  FAILED: {name}", flush=True)


def cmd_drive(state: dict, via: str, runs: int) -> None:
    if via not in ("api", "page"):
        raise RigError("--via is api or page")
    for _ in range(runs):
        drive_one(state, via)


# --------------------------------------------------------------------------- down


def remove_tree(root: Path) -> None:
    """Remove the rig's temp tree; the pin copies keep production's read-only folders, so make
    this user's folders writable first. Files a container user wrote may stay behind."""
    for folder, _dirs, _files in os.walk(root):
        with contextlib.suppress(OSError):
            os.chmod(folder, os.stat(folder).st_mode | 0o700)
    shutil.rmtree(root, ignore_errors=True)


def cmd_down(state: dict) -> None:
    compose(state, "down", "-v", "--remove-orphans", timeout=600)
    sh("systemctl", "--user", "stop", state["helper_unit"], check=False, env=user_bus_env())
    for run in state["runs"]:
        left = sh("docker", "ps", "-aq", "--filter", "label=temper.pi.box=1", "--filter",
                  f"label=temper.pi.run={run['run_id']}").stdout.split()
        if left:
            sh("docker", "rm", "-f", *left, check=False)
            run["boxes_left_at_down"] = len(left)
    sh("docker", "image", "rm", f"pi-rehearsal-server:{state['id']}",
       f"pi-rehearsal-worker:{state['id']}", check=False)
    state["down_at"] = now()
    root = Path(state["root"])
    write_json(Path(state["record"]) / "rig.json", state)
    if Path(state["helper"]["log"]).exists():
        shutil.copyfile(Path(state["helper"]["log"]), Path(state["record"]) / "helper.log")
    remove_tree(root)
    left = root.exists()
    print(f"rig {state['id']} down; temp tree {'left (owned by container users)' if left else 'removed'}",
          flush=True)


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("command", choices=("prepare", "build", "create", "up", "drive", "down"))
    parser.add_argument("--rig", type=Path, help="the rig's root (/tmp/pi-rehearsal/<id>)")
    parser.add_argument("--label", default="preparation")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--id", help="the rig id (8 hex digits); random if not given")
    parser.add_argument("--via", default="api")
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            cmd_prepare(args)
            return 0
        if not args.rig:
            raise RigError("--rig is required")
        state = load(args.rig)
        {"build": cmd_build, "create": cmd_create, "up": cmd_up, "down": cmd_down,
         "drive": lambda s: cmd_drive(s, args.via, args.runs)}[args.command](state)
        return 0
    except (RigError, audit.RigRefusal) as exc:
        print(f"rig {args.command}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
