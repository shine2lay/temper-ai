#!/usr/bin/env python3
"""Product-owned shared Temper launcher. Never executes `temper run` or pins credentials.

Only status metadata is logged. Inputs, config prompts and server outputs are not dumped.
A durable pre-POST record fences uncertain launches; resuming a monitor never submits a run.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("PRODUCT_AUTOPILOT_DIR", Path.home() / "product-autopilot"))
SHARED = Path(os.environ.get("PRODUCT_WORKSPACES_ROOT", Path.home() / "temper-ai/workspaces/product"))
API = os.environ.get("PRODUCT_TEMPER_API", "http://127.0.0.1:8420").rstrip("/")
UI = os.environ.get("PRODUCT_TEMPER_UI", "https://temper-dev.wai2shine.com/app").rstrip("/")
LIVE = {"scan_market", "scan_serving", "signal_harvest", "signal_grade", "opportunity_brief", "desk_check", "shape_mvp",
        "pmf_evidence", "feature_screen", "confidence_check"}
TERMINAL = {"completed": 0, "failed": 1, "cancelled": 2}


class Refused(RuntimeError):
    pass


class APIError(RuntimeError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"Temper HTTP {status}; inspect application status (body not logged)")


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text())


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with tmp.open("x") as out:
        os.chmod(tmp, 0o600)
        out.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        out.flush()
        os.fsync(out.fileno())
    tmp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


KEY_FILE = Path.home() / ".config/temper/api-keys/product.key"


def auth_headers(method: str) -> dict:
    """Name Product as the writer to Temper's write guard (docs/api-access.md).

    Writes only; reads need no key. The key is read from its file at call time
    (TEMPER_API_KEY_FILE, else product.key). No readable key -> no header: the guard decides.
    The value is never printed, logged, stored or passed into a run.
    """
    if method.upper() in ("GET", "HEAD"):
        return {}
    path = Path(os.environ.get("TEMPER_API_KEY_FILE") or KEY_FILE).expanduser()
    try:
        key = path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return {}
    return {"Authorization": "Bearer " + key} if key else {}


def api(method: str, route: str, body=None, base: str | None = None):
    request = urllib.request.Request(
        (base or API) + route,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **auth_headers(method)}, method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise APIError(exc.code) from None


def links(workflow: str, execution_id: str | None = None, ui: str = UI) -> dict:
    result = {"workflow_url": f"{ui}/studio/{urllib.parse.quote(workflow, safe='')}"}
    if execution_id:
        result["run_url"] = f"{ui}/workflow/{execution_id}"
    return result


def filename(name: str, suffix: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", name):
        raise Refused("job name: lowercase letters, digits and dashes only")
    return ROOT / "runs" / f"{name}.{suffix}"


@contextlib.contextmanager
def locked():
    (ROOT / "runs").mkdir(parents=True, exist_ok=True)
    with (ROOT / "runs" / "server-launch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def config(kind: str, name: str, base: str | None = None) -> dict:
    record = api("GET", f"/api/studio/configs/{kind}/{urllib.parse.quote(name, safe='')}", base=base)
    return record["config"] if "config" in record else record


def graph_items(inner: dict):
    yield inner
    for node in inner.get("nodes", []):
        yield from graph_items(node)


def refs(document: dict, kind: str):
    """Only actual graph fields, never prompts or input/output mappings."""
    if kind == "agent":
        return
    for node in graph_items(document[kind]):
        if node.get("type") == "template":
            raise Refused("dynamic template candidates need an explicitly expanded Product closure")
        if node.get("agent"):
            yield "agent", node["agent"]
        if node.get("ref"):
            yield "stage", node["ref"]
        for agent in node.get("agents", []):
            name = agent if isinstance(agent, str) else agent.get("agent") or agent.get("ref")
            if name:
                yield "agent", name


def rewrite(document: dict, kind: str, mapping: dict) -> dict:
    result = json.loads(json.dumps(document))
    result[kind]["name"] = mapping[(kind, document[kind]["name"])]
    if kind == "agent":
        return result
    for node in graph_items(result[kind]):
        if node.get("agent"):
            node["agent"] = mapping[("agent", node["agent"])]
        if node.get("ref"):
            node["ref"] = mapping[("stage", node["ref"])]
        agents = node.get("agents", [])
        for index, agent in enumerate(agents):
            if isinstance(agent, str):
                # Stage topology derives child node names from agent.name. Keep those
                # names stable while changing only the registration reference.
                agents[index] = {"agent": mapping[("agent", agent)], "name": agent}
            else:
                key = "agent" if agent.get("agent") else "ref"
                if agent.get(key):
                    original = agent[key]
                    agent.setdefault("name", original)
                    agent[key] = mapping[("agent", original)]
    return result


def register(directory: Path, workflow: str, namespace: str, receipt: Path) -> dict:
    import yaml  # candidate YAMLs only; launch/status need no extra dependencies

    if not re.fullmatch(r"product_[a-z0-9_]{3,55}", namespace):
        raise Refused("candidate namespace must start product_ and contain lowercase letters/digits/underscores")
    if receipt.exists():
        raise Refused("registration receipt exists; use a fresh namespace, never overwrite")
    records = {}
    for source in sorted(directory.rglob("*.yaml")):
        document = yaml.safe_load(source.read_text())
        if not isinstance(document, dict):
            continue
        for kind in ("agent", "stage", "workflow"):
            if isinstance(document.get(kind), dict) and document[kind].get("name"):
                key = kind, document[kind]["name"]
                if key in records:
                    raise Refused(f"ambiguous candidate config {key}; use an isolated closure directory")
                records[key] = document
    closure = {}
    todo = [("workflow", workflow)]
    while todo:
        key = todo.pop()
        if key in closure:
            continue
        if key not in records:
            raise Refused(f"missing candidate dependency {key}; include it explicitly")
        closure[key] = records[key]
        todo.extend(refs(records[key], key[0]))
    # A content suffix makes accidental name reuse less likely; existence is still checked.
    stamp = digest(sorted((kind, name, doc) for (kind, name), doc in closure.items()))[:10]
    mapping = {key: f"{namespace}_{key[1]}_{stamp}" for key in closure}
    bundle = [(kind, mapping[(kind, name)], rewrite(doc, kind, mapping))
              for (kind, name), doc in closure.items()]
    with locked():
        deployed = Path.home() / "temper-ai/configs"
        deployed_names = set()
        for source in deployed.rglob("*.yaml"):
            doc = yaml.safe_load(source.read_text())
            if isinstance(doc, dict):
                for kind in ("workflow", "stage", "agent"):
                    if isinstance(doc.get(kind), dict):
                        deployed_names.add((kind, doc[kind].get("name")))
        for kind, name, _ in bundle:
            if (kind, name) in deployed_names:
                raise Refused("candidate name collides with worker disk imports")
            try:
                config(kind, name)
            except APIError as exc:
                if exc.status != 404:
                    raise
            else:
                raise Refused(f"candidate name already registered: {name}")
        result = {"workflow": mapping[("workflow", workflow)], "source_workflow": workflow,
                  "created": now(), "source_directory": str(directory.resolve()),
                  "api_url": API, "configs": [], "state": "registering"}
        save(receipt, result)
        # Leaves a partial receipt on uncertainty. Never re-upsert or auto-retry.
        for kind, name, doc in sorted(bundle, key=lambda row: row[0] == "workflow"):
            api("POST", f"/api/studio/configs/{kind}/{name}", {"config": doc})
            if digest(config(kind, name)) != digest(doc):
                raise Refused("registered definition differs from candidate")
            result["configs"].append({"type": kind, "name": name, "sha256": digest(doc)})
            save(receipt, result)
        result["state"] = "registered"
        result.update(links(result["workflow"]))
        save(receipt, result)
    return result


def prepare_workspace(workspace: Path) -> None:
    """Only Product data: grant the configured run UID access, never chmod world-writable.

    Current Docker runs clone temper-ai-server-1 as UID 999, not the watcher UID 1000.
    Re-prove the smoke if that identity changes; do not change service users/defaults.
    """
    uid = os.environ.get("PRODUCT_TEMPER_WORKER_UID", "999")
    if not uid.isdigit():
        raise Refused("PRODUCT_TEMPER_WORKER_UID must be a numeric, verified runtime UID")
    subprocess.run(["setfacl", "-m", f"u:{uid}:rwx,d:u:{uid}:rwx,d:u:{os.getuid()}:rwx,d:m:rwx",
                    str(workspace)], check=True, capture_output=True, timeout=20)


def stage(source: Path, workspace: Path, relative: str) -> dict:
    """Checksum-copy research/config assets into a fresh shared path, never back to source."""
    import shutil
    workspace = workspace.resolve()
    destination = (workspace / relative).resolve()
    if (not workspace.is_relative_to(SHARED.resolve()) or workspace == SHARED.resolve()
            or not destination.is_relative_to(workspace) or destination == workspace):
        raise Refused("staging needs a dedicated shared Product workspace and an internal destination")
    if destination.exists() or source.is_symlink():
        raise Refused("staging destination exists or source is a symlink; never overwrite")
    paths = list(source.rglob("*")) if source.is_dir() else [source]
    if any(path.is_symlink() or path.name in {".env", ".credentials.json", "auth.json"} for path in paths):
        raise Refused("do not stage symlinks or credential files")
    workspace.mkdir(parents=True, exist_ok=True)
    prepare_workspace(workspace)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    uid = os.environ.get("PRODUCT_TEMPER_WORKER_UID", "999")
    subprocess.run(["setfacl", "-R", "-m", f"u:{uid}:r-X", str(destination)],
                   check=True, capture_output=True, timeout=20)
    files = []
    for path in sorted(paths):
        if path.is_file():
            relative_source = path.relative_to(source) if source.is_dir() else Path(source.name)
            target = destination / relative_source if source.is_dir() else destination
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual != hashlib.sha256(path.read_bytes()).hexdigest():
                raise Refused("staged asset checksum mismatch")
            files.append({"relative": str(relative_source), "sha256": actual})
    result = {"source": str(source.resolve()), "destination": str(destination), "files": files}
    save(workspace / (".staged-" + digest(relative)[:12] + ".json"), result)
    return result


def assert_script_only(workflow: str):
    visited = set()
    todo = [("workflow", workflow)]
    while todo:
        kind, name = todo.pop()
        if (kind, name) in visited:
            continue
        visited.add((kind, name))
        document = config(kind, name)
        if kind == "agent" and document[kind].get("type") != "script":
            raise Refused("--non-model requires every referenced agent to be script-only")
        if kind != "agent":
            inner = document[kind]
            if inner.get("defaults") or inner.get("agent_overrides"):
                raise Refused("--non-model cannot prove graphs with agent overrides")
            for node in inner.get("nodes", []):
                allowed = {"name", "type", "agent", "depends_on", "input_map"}
                if (node.get("type", "agent") != "agent" or not node.get("agent")
                        or set(node) - allowed):
                    raise Refused("--non-model requires explicit, non-overridden script agent nodes")
        todo.extend(refs(document, kind))


def no_secrets(value):
    # Inputs are research data and staged paths, never keys/tokens/passwords.
    if isinstance(value, dict):
        for key, item in value.items():
            if re.search(r"token|secret|password|api.?key|credential", key, re.I):
                raise Refused("credentials must stay in server configuration, not inputs")
            no_secrets(item)
    elif isinstance(value, list):
        for item in value:
            no_secrets(item)
    elif isinstance(value, str) and re.search(r"sk-ant-|sk-proj-|Bearer [A-Za-z0-9_-]{20,}", value):
        raise Refused("credential-shaped value refused")


def own_unit() -> str | None:
    """The systemd unit this process runs in, e.g. product-weekly-cadence-<date>.service.

    The weekly cadence hands itself to such a unit and then launches from inside it; that unit
    is the caller, not another workflow, so assert_idle must not count it.
    """
    try:
        text = Path("/proc/self/cgroup").read_text()
    except OSError:
        return None
    for line in text.splitlines():
        last = line.rsplit("/", 1)[-1].strip()
        if last.endswith(".service"):
            return last
    return None


def assert_idle():
    for record in (ROOT / "runs").glob("*.job.json"):
        job = load(record)
        if job.get("state") not in TERMINAL:
            raise Refused(f"unresolved shared job {job['name']} ({job.get('state')}); inspect/resume, never duplicate")
    out = subprocess.run(
        ["systemctl", "--user", "list-units", "--plain", "--no-legend", "--state=active,activating", "product-*.service"],
        check=True, capture_output=True, text=True, timeout=20,
    )
    me = own_unit()
    others = [line.split()[0] for line in out.stdout.splitlines() if line.split() and line.split()[0] != me]
    if others:
        raise Refused(f"another product unit is active ({others[0]}): one workflow at a time")
    for state in ("pending", "queued", "running", "waiting"):
        offset = 0
        while True:
            data = api("GET", f"/api/workflows?status={state}&limit=500&offset={offset}")
            for run in data["runs"]:
                name = run.get("workflow_name") or ""
                if name in LIVE or name.startswith("product_"):
                    raise Refused(f"shared Product execution still {state}: {run['id']}")
            offset += len(data["runs"])
            if offset >= data.get("total", offset) or not data["runs"]:
                break


def launch(name: str, workflow: str, inputs_path: Path | None, workspace: Path,
           receipt: Path | None = None, non_model: bool = False) -> dict:
    record_path = filename(name, "job.json")
    workspace = workspace.resolve()
    if not workspace.is_relative_to(SHARED.resolve()) or workspace == SHARED.resolve() or not workspace.is_dir():
        raise Refused("pre-create a dedicated workspace under the shared Product workspace root")
    if workflow not in LIVE:
        if not receipt:
            raise Refused("non-live Product workflows require their registration receipt")
        registered = load(receipt)
        if registered.get("state") != "registered" or registered.get("workflow") != workflow:
            raise Refused("candidate workflow/receipt mismatch")
        for item in registered["configs"]:
            if digest(config(item["type"], item["name"])) != item["sha256"]:
                raise Refused("candidate changed since registration")
    inputs = load(inputs_path) if inputs_path else {}
    if not isinstance(inputs, dict):
        raise Refused("inputs file must be a JSON object")
    no_secrets(inputs)
    for key, value in inputs.items():
        if isinstance(value, str) and value.startswith("/") and (key.endswith("_dir") or key.endswith("_path")):
            if not Path(value).resolve().is_relative_to(workspace):
                raise Refused("absolute input assets/baselines must be staged in this run's shared workspace")
    if non_model:
        assert_script_only(workflow)
    else:
        sys.path.insert(0, str(ROOT))
        import digest as autopilot
        threshold = float(os.environ.get("POOL_THRESHOLD", autopilot.load(ROOT / "config.json", {}).get("poolThreshold", 90)))
        quota = autopilot._pool(threshold)
        if not quota.get("ok") or not quota.get("headroom"):
            raise Refused("subscription headroom unavailable/exhausted; no launch")
    with locked():
        if any(list((ROOT / folder).glob(f"{name}.*")) for folder in ("runs", "runs/collected")):
            raise Refused("job name already used; never resubmit")
        assert_idle()
        prepare_workspace(workspace)
        job = {"name": name, "workflow": workflow, "workspace": str(workspace),
               "started": now(), "state": "submitting", "execution_id": None,
               "api_url": API, "ui_url": UI, "non_model": non_model,
               "candidate_receipt": str(receipt) if receipt else None, **links(workflow)}
        # Fence written BEFORE the only POST. A crash anywhere afterwards blocks replay.
        save(record_path, job)
        filename(name, "cmd").write_text(f"shared Temper workflow {workflow}\n")
        filename(name, "log").write_text(f"[{now()}] submitting shared workflow {workflow}\n")
        try:
            response = api("POST", "/api/runs", {"workflow": workflow, "inputs": inputs,
                                                  "workspace_path": str(workspace)})
            execution_id = str(uuid.UUID(response["execution_id"]))
        except Exception:
            job["state"] = "uncertain-submit"
            save(record_path, job)
            raise Refused("launch response uncertain; no automatic retry, inspect server run list") from None
        job.update(execution_id=execution_id, state=response.get("status", "queued"),
                   **links(workflow, execution_id))
        save(record_path, job)
        start_monitor(job)
    return job


def start_monitor(job: dict) -> None:
    try:
        subprocess.run([
            "systemd-run", "--user", "--quiet", f"--unit=product-{job['name']}", "--collect",
            f"--working-directory={ROOT}", f"--setenv=PRODUCT_AUTOPILOT_DIR={ROOT}",
            "--setenv=PATH=" + str(Path.home() / ".local/bin") + ":/usr/local/bin:/usr/bin:/bin",
            "--setenv=PRODUCT_SERVER_CODE=" + str(Path(__file__).resolve()),
            str(ROOT / "runner.sh"), job["name"],
        ], check=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise Refused("server run submitted; monitor failed to start; use monitor NAME, do not launch again") from None


def safe_status(data: dict) -> dict:
    def nodes(items):
        return [{"name": item.get("name"), "type": item.get("type"), "status": item.get("status"),
                 "nodes": nodes(item.get("child_nodes") or item.get("nodes") or [])} for item in (items or [])]
    return {key: data.get(key) for key in ("id", "workflow_name", "status", "start_time", "end_time",
                                          "duration_seconds", "total_cost_usd", "total_tokens", "total_llm_calls",
                                          "workspace_path")} | {"nodes": nodes(data.get("nodes", []))}


def refresh(name: str) -> dict:
    path = filename(name, "job.json")
    job = load(path)
    if not job.get("execution_id"):
        raise Refused("no confirmed execution ID; reconcile the uncertain submission in the server first")
    status = safe_status(api("GET", "/api/workflows/" + job["execution_id"], base=job["api_url"]))
    if status["id"] != job["execution_id"] or status["workflow_name"] != job["workflow"]:
        raise Refused("server execution identity mismatch")
    state = status["status"]
    # An unknown status remains unresolved; never turns into a successful local exit.
    job.update(state=state, updated=now(), cost=status["total_cost_usd"], status=status)
    save(path, job)
    with filename(name, "log").open("a") as log:
        log.write(f"[{now()}] {state}: {job['execution_id']}; cost ${job.get('cost')}\n")
    if state in TERMINAL:
        save(filename(name, "done"), {"exit": TERMINAL[state], "started": job["started"], "ended": now(),
             "source": "shared-server", "server_status": state, "execution_id": job["execution_id"],
             "workflow": job["workflow"], "workspace": job["workspace"], "cost": job.get("cost"),
             **links(job["workflow"], job["execution_id"], job["ui_url"])})
    return job


def refresh_links(name: str) -> dict:
    """Fix this helper's link metadata only; never changes server history or IDs."""
    path = filename(name, "job.json")
    job = load(path)
    if not job.get("execution_id"):
        raise Refused("cannot publish a run link without a confirmed ID")
    current = links(job["workflow"], job["execution_id"])
    for url in current.values():
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status != 200:
                raise Refused("UI link did not load; no link metadata changed")
    job.update(ui_url=UI, **current)
    save(path, job)
    done = filename(name, "done")
    if done.exists():
        receipt = load(done)
        receipt.update(current)
        save(done, receipt)
    return job


def monitor(name: str, once: bool = False) -> int:
    import threading
    waiter = threading.Event()
    while True:
        try:
            job = refresh(name)
        except (OSError, ValueError, APIError, Refused):
            # Do not manufacture a terminal receipt or release the fence on a read error.
            if once:
                raise Refused("server status unavailable; job remains fenced") from None
            with filename(name, "log").open("a") as log:
                log.write(f"[{now()}] status unavailable; no resubmission, fence retained\n")
            waiter.wait(15)
            continue
        if job["state"] in TERMINAL:
            return TERMINAL[job["state"]]
        if once:
            return 75  # queued/running/waiting are not completion
        waiter.wait(15)  # detached status monitor, not a chat polling loop


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    reg = commands.add_parser("register")
    reg.add_argument("directory", type=Path)
    reg.add_argument("workflow")
    reg.add_argument("--namespace", required=True)
    reg.add_argument("--receipt", type=Path, required=True)
    run = commands.add_parser("launch")
    run.add_argument("name")
    run.add_argument("workflow")
    run.add_argument("--inputs", type=Path)
    run.add_argument("--workspace", type=Path, required=True)
    run.add_argument("--receipt", type=Path)
    run.add_argument("--non-model", action="store_true")
    copy = commands.add_parser("stage")
    copy.add_argument("source", type=Path)
    copy.add_argument("--workspace", type=Path, required=True)
    copy.add_argument("--relative", required=True)
    mon = commands.add_parser("monitor")
    mon.add_argument("name")
    mon.add_argument("--once", action="store_true")
    relink = commands.add_parser("refresh-links")
    relink.add_argument("name")
    resume = commands.add_parser("resume-monitor")
    resume.add_argument("name")
    args = parser.parse_args()
    try:
        if args.command == "register":
            result = register(args.directory, args.workflow, args.namespace, args.receipt)
        elif args.command == "launch":
            result = launch(args.name, args.workflow, args.inputs, args.workspace, args.receipt, args.non_model)
        elif args.command == "stage":
            result = stage(args.source, args.workspace, args.relative)
        elif args.command == "refresh-links":
            result = refresh_links(args.name)
        elif args.command == "resume-monitor":
            result = load(filename(args.name, "job.json"))
            if not result.get("execution_id") or result["state"] in TERMINAL:
                raise Refused("resume-monitor needs a known, unresolved server execution")
            start_monitor(result)
        else:
            return monitor(args.name, args.once)
        if args.command == "stage":
            print(json.dumps({"destination": result["destination"], "file_count": len(result["files"])}))
        else:
            print(json.dumps({key: result.get(key) for key in
                              ("name", "workflow", "state", "execution_id", "workflow_url", "run_url")}, indent=2))
        return 0
    except (Refused, APIError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
