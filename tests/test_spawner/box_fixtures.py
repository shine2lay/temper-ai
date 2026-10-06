"""Shared pieces for the box-profile tests (BS1, docs/boxes.md "Sealed boxes").

- MemoryStore: a run's row (workflow, spawner_metadata, workspace, status) without a database.
- Install: a synthetic install tree on disk, shaped like production's template container:
  the runner's code and configs, a local/ folder with key folders in it, Claude CLI
  versions, a login file, a main repo copy with an .env, a workspaces tree with two runs,
  a shared data folder and an unrelated shared root. Every "secret" in it is synthetic
  text (SYNTHETIC_MARK) and nothing is real.
- BoxDocker: the `run` callable DockerSpawner takes, for the real-container gate: it
  answers `docker inspect worker-self` with Install's template and runs `docker run` for
  real, in the foreground (no --detach), labelled temper.test=box-sealed, with no network.
  A ``before_run`` hook can change the host tree (a race) or the command (a tamper) between
  the spawner's check and docker's use.

No production service, account or model is touched (G12): containers run with
--network none, and the box's program is a probe in the synthetic code tree.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from temper_ai.spawner.box_profile import METADATA_KEY, BoxProfileError, RunFacts

SYNTHETIC_MARK = "SYNTHETIC-NOT-A-REAL-SECRET"
TEST_LABEL = "temper.test=box-sealed"
#: This test process's boxes: a clean-up removes only these, never another test process's
#: boxes running at the same time (pytest -n).
OWN_LABEL = f"temper.test.pid={os.getpid()}"
WORKFLOW = "sealed_probe"


# -- the run's row ----------------------------------------------------------------------------


@dataclass
class MemoryStore:
    """A run row per execution id: workflow, spawner_metadata, workspace_path, status."""

    rows: dict[str, dict] = field(default_factory=dict)

    def add(self, execution_id: str, workflow: str = WORKFLOW, workspace: str = "",
            status: str = "queued", metadata: dict | None = None) -> None:
        self.rows[execution_id] = {"workflow": workflow, "metadata": dict(metadata or {}),
                                   "workspace": workspace, "status": status}

    def load(self, execution_id: str) -> RunFacts | None:
        row = self.rows.get(execution_id)
        if row is None:
            return None
        return RunFacts(workflow_name=row["workflow"], metadata=copy.deepcopy(row["metadata"]))

    def save(self, execution_id: str, record: dict, expected_generation: int | None) -> None:
        row = self.rows.get(execution_id)
        if row is None:
            raise BoxProfileError(f"no row for {execution_id}")
        held = (row["metadata"].get(METADATA_KEY) or {}).get("generation")
        if held != expected_generation:
            raise BoxProfileError(f"generation {held}, expected {expected_generation}")
        row["metadata"][METADATA_KEY] = copy.deepcopy(record)

    def neighbours(self, execution_id: str, forms: list[str]) -> list[str]:
        found = []
        for other, row in self.rows.items():
            where = row["workspace"]
            if other == execution_id or not where:
                continue
            inside = any(where.startswith(f.rstrip("/") + "/") for f in forms)
            above = any(f == where or f.startswith(where.rstrip("/") + "/") for f in forms)
            if inside or (above and row["status"] in {"pending", "queued", "running"}):
                found.append(f"{other} ({where}, {row['status']})")
        return sorted(found)

    def record(self, execution_id: str) -> dict:
        return self.rows[execution_id]["metadata"][METADATA_KEY]


# -- a synthetic install ----------------------------------------------------------------------

#: What the box runs instead of the real runner: it looks at the box from inside and writes
#: what it found to its workspace (probe.json). It runs only if the box check passed.
PROBE = textwrap.dedent('''
    import json, os, subprocess, sys

    plan = json.load(open("/app/configs/probe_plan.json"))
    doc = json.loads(os.environ["TEMPER_BOX_PROFILE"])
    ws = next(g["target"] for g in doc["grants"] if g["kind"] == "workspace")
    eid = sys.argv[sys.argv.index("--execution-id") + 1]

    def can_write(path):
        target = os.path.join(path, ".probe-write") if os.path.isdir(path) else path
        try:
            with open(target, "a"):
                pass
        except OSError:
            return False
        if target.endswith(".probe-write"):
            os.unlink(target)
        return True

    def shows(path):
        if not os.path.lexists(path):
            return False
        if os.path.islink(path) or not os.path.isdir(path):
            return True
        try:
            return bool(os.listdir(path))
        except OSError:
            return True

    def shadow(directory):
        try:
            with open(os.path.join(directory, "git"), "w") as fh:
                fh.write("#!/bin/sh\\n")
        except OSError:
            return False
        return True

    with open(os.path.join(ws, f"mark-{eid}"), "w") as fh:
        fh.write(eid)
    path_dirs = [d for d in os.environ["PATH"].split(os.pathsep) if d]
    out = {
        "execution_id": eid,
        "uid": os.getuid(),
        "own_write": can_write(ws),
        "own_marks": sorted(n for n in os.listdir(ws) if n.startswith("mark-")),
        "present": {p: shows(p) for p in plan["absent"]},
        "writable": {p: can_write(p) for p in plan["immutable"] + path_dirs
                     + [os.environ["HOME"]] + [d for d in sys.path if d and os.path.isdir(d)]},
        "shadowed": {d: shadow(d) for d in path_dirs},
        "data_read": open(plan["data_file"]).read() == plan["data_text"],
        "data_write": can_write(plan["data_dir"]),
        "tmp_write": can_write("/tmp"),
        "claude": subprocess.run(["claude"], capture_output=True, text=True,
                                 timeout=10).stdout.strip(),
        "env_names": sorted(os.environ),
        "env_has_mark": any("SYNTHETIC" in v for v in os.environ.values()),
    }
    with open(os.path.join(ws, "probe.json"), "w") as fh:
        json.dump(out, fh)
    print(json.dumps(out))
''')

#: A swapped-in code root: if it ever ran, it would leave PWNED in every workspace it can reach.
HOSTILE = textwrap.dedent('''
    import os, json
    doc = json.loads(os.environ.get("TEMPER_BOX_PROFILE", "{}"))
    for g in doc.get("grants", []):
        try:
            open(os.path.join(g["target"], "PWNED"), "w").write("x")
        except OSError:
            pass
    print("PWNED")
''')


def _write(path: Path, text: str, mode: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mode is not None:
        path.chmod(mode)
    return path


@dataclass
class Install:
    """The synthetic host tree and the template container's description of it."""

    root: Path
    user: str
    image_ref: str = "temper-test-box"
    image_id: str = "sha256:" + "0" * 64
    #: More of the template container's environment ("NAME=value"), e.g. the default provider.
    extra_env: list[str] = field(default_factory=list)

    def engine_table(self) -> dict[str, str]:
        """The synthetic runner's launch sites, classified for tests (the real table can't know them)."""
        from temper_ai.spawner import box_launches
        from temper_ai.spawner.box_seal import LOCAL_CODE

        sites = box_launches.launch_sites(self.code, prefix="temper_ai/")
        sites |= box_launches.launch_sites(self.local, prefix="local/", only=LOCAL_CODE)
        return {site: "box: the synthetic runner (tests)" for site in sites}

    def __post_init__(self) -> None:
        r = self.root
        self.code = r / "src" / "temper_ai"
        self.configs = r / "src" / "configs"
        self.local = r / "src" / "local"
        self.versions = r / "claude-versions"
        self.creds = r / "creds" / ".credentials.json"
        self.repo = r / "repo"
        self.workspaces = r / "workspaces"
        self.run_a = self.workspaces / "run-a"
        self.run_b = self.workspaces / "run-b"
        self.data = r / "shared-data"
        self.command_center = r / "command-center"

    def build(self) -> Install:
        _write(self.code / "__init__.py", "")
        _write(self.code / "cli" / "__init__.py", "")
        _write(self.code / "cli" / "main.py", PROBE)
        _write(self.configs / "workflows" / f"{WORKFLOW}.yaml", textwrap.dedent(f"""
            workflow:
              name: {WORKFLOW}
              nodes:
                - name: probe
                  type: agent
                  agent: {WORKFLOW}
        """))
        _write(self.configs / "agents" / f"{WORKFLOW}.yaml", textwrap.dedent(f"""
            agent:
              name: {WORKFLOW}
              type: script
              script_template: |
                #!/bin/bash
                echo probe
        """))
        _write(self.configs / "boxes" / "data.yaml",
               f"data:\n  {WORKFLOW}: [/app/shared-data]\n")
        for name in ("__init__.py", "register_providers.py"):
            _write(self.local / name, "")
        _write(self.local / "providers" / "__init__.py", "")
        _write(self.local / "agents" / "__init__.py", "")
        _write(self.local / "standee-ssh" / "id_ed25519", f"{SYNTHETIC_MARK} ssh key\n")
        _write(self.local / "github-deploy" / "id_ed25519", f"{SYNTHETIC_MARK} deploy key\n")
        _write(self.local / "README.md", "private notes\n")
        for version in ("2.1.9", "2.1.10"):
            _write(self.versions / version, f"#!/bin/sh\necho fake-claude {version}\n", 0o755)
        _write(self.versions / "latest-download.tmp", "not a version\n")
        _write(self.creds, json.dumps({"claudeAiOauth": {"accessToken": SYNTHETIC_MARK}}))
        _write(self.repo / ".env", f"TEMPER_SECRET_KEY={SYNTHETIC_MARK}\n")
        _write(self.repo / "README.md", "the main repo copy\n")
        _write(self.data / "readme.txt", "declared data\n")
        _write(self.command_center / "notes.txt", "an unrelated shared root\n")
        for ws in (self.run_a, self.run_b):
            ws.mkdir(parents=True, exist_ok=True)
            ws.chmod(0o777)
        self.write_plan()
        return self

    def write_plan(self) -> None:
        """What the probe checks: paths that must be absent, ones it must not write."""
        _write(self.configs / "probe_plan.json", json.dumps({
            "absent": [
                str(self.repo), "/app/repo", "/app/.env", "/app/workspaces", str(self.creds),
                "/app/.claude/.credentials.json", "/app/standee-ssh", "/app/github-deploy",
                "/app/local/standee-ssh", "/app/local/github-deploy", "/app/local/README.md",
                str(self.command_center), "/app/command-center", "/var/run/docker.sock",
                str(self.local), str(self.versions), "/opt/claude/versions",
                str(self.run_a), str(self.run_b), str(self.data),
            ],
            "immutable": ["/app", "/app/temper_ai", "/app/configs", "/app/local",
                          "/app/local/providers", "/app/.local/bin", "/app/.local/bin/claude",
                          "/app/.venv", "/usr/local/bin", "/usr/local/lib"],
            "data_file": "/app/shared-data/readme.txt",
            "data_text": "declared data\n",
            "data_dir": "/app/shared-data",
        }))

    def mounts(self) -> list[dict]:
        """The template's binds, as production's server container has them (docs/boxes.md)."""
        def bind(source: Path | str, target: str, rw: bool = False) -> dict:
            return {"Type": "bind", "Source": str(source), "Destination": target, "RW": rw}
        return [
            bind(self.creds, "/app/.claude/.credentials.json"),
            bind(self.repo, "/app/repo"),
            bind(self.local / "standee-ssh", "/app/standee-ssh"),
            bind(self.workspaces, str(self.workspaces), rw=True),
            bind(self.workspaces, "/app/workspaces", rw=True),
            bind(self.command_center, "/app/command-center", rw=True),
            bind(self.local / "github-deploy", "/app/github-deploy"),
            bind(self.versions, "/opt/claude/versions"),
            bind(self.local, "/app/local"),
            bind(self.code, "/app/temper_ai"),
            bind(self.configs, "/app/configs"),
            bind(self.data, "/app/shared-data"),
            bind("/var/run/docker.sock", "/var/run/docker.sock", rw=True),
        ]

    def inspect(self) -> str:
        return json.dumps([{
            "Image": self.image_id,
            "Config": {
                "Image": self.image_ref,
                "User": self.user,
                "WorkingDir": "/app",
                "Env": [
                    "PATH=/app/.local/bin:/usr/local/bin:/usr/bin:/bin",
                    "HOME=/app",
                    f"WORKSPACE_DIR={self.workspaces}",
                    "TEMPER_DATABASE_URL=postgresql://synthetic",
                    f"SYNTH_SERVICE_TOKEN={SYNTHETIC_MARK}",
                    "PYTHONPATH=/app/workspaces",
                    *self.extra_env,
                ],
            },
            "HostConfig": {"ExtraHosts": []},
            "Mounts": self.mounts(),
            "NetworkSettings": {"Networks": {"none": {}}},
        }])


# -- real docker ------------------------------------------------------------------------------


def docker_ok() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


#: The small image the gate builds when no temper image is at hand: the shape the sealed
#: box relies on (an interpreter at /app/.venv/bin/python with /app on its import path).
TINY_DOCKERFILE = textwrap.dedent("""
    FROM python:3.12-slim
    RUN mkdir -p /app/.venv/bin /app/.local/bin /app/.claude /opt/claude/versions \\
     && ln -s /usr/local/bin/python3 /app/.venv/bin/python \\
     && echo /app > /usr/local/lib/python3.12/site-packages/temper_app.pth
    WORKDIR /app
""")


def box_image() -> str | None:
    """The image the gate runs: TEMPER_TEST_BOX_IMAGE, the newest temper CI server image
    on this machine, or a tiny one built from python:3.12-slim. None if none can be had."""
    given = os.environ.get("TEMPER_TEST_BOX_IMAGE")
    if given:
        return given
    listed = subprocess.run(
        ["docker", "images", "--filter", "reference=temper-ci-server", "--format",
         "{{.CreatedAt}}\t{{.Repository}}:{{.Tag}}"],
        capture_output=True, text=True, timeout=30,
    )
    rows = sorted(line.split("\t") for line in listed.stdout.splitlines() if "\t" in line)
    if rows:
        return rows[-1][1]
    tag = "temper-test-box:" + hashlib.sha256(TINY_DOCKERFILE.encode()).hexdigest()[:12]
    have = subprocess.run(["docker", "image", "inspect", tag], capture_output=True, timeout=30)
    if have.returncode == 0:
        return tag
    built = subprocess.run(
        ["docker", "build", "--label", TEST_LABEL, "-t", tag, "-"],
        input=TINY_DOCKERFILE, capture_output=True, text=True, timeout=600,
    )
    return tag if built.returncode == 0 else None


def image_id(ref: str) -> str:
    out = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", ref],
                         capture_output=True, text=True, timeout=30, check=True)
    return out.stdout.strip()


def box_user() -> str:
    """The box's user: this one (so the synthetic tree is its own), never root."""
    uid, gid = os.getuid(), os.getgid()
    return "65534:65534" if uid == 0 else f"{uid}:{gid}"


@dataclass
class BoxDocker:
    """DockerSpawner's ``run``: a fake template inspect, a real foreground `docker run`."""

    install: Install
    before_run: Callable[[list[str]], list[str] | None] | None = None
    runs: list[subprocess.CompletedProcess] = field(default_factory=list)
    names: list[str] = field(default_factory=list)

    def __call__(self, cmd, **kwargs) -> subprocess.CompletedProcess:
        cmd = list(cmd)
        if cmd[1] == "inspect":
            return subprocess.CompletedProcess(cmd, 0, stdout=self.install.inspect(), stderr="")
        if cmd[1] != "run":
            return subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if self.before_run is not None:
            cmd = self.before_run(cmd) or cmd
        cmd = [c for c in cmd if c != "--detach"]
        cmd[2:2] = ["--label", TEST_LABEL, "--label", OWN_LABEL]
        self.names.append(cmd[cmd.index("--name") + 1])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        finally:
            self.cleanup()
        self.runs.append(result)
        return result

    def cleanup(self) -> None:
        for name in self.names:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)


def swap_dir(path: Path, replacement: Callable[[Path], None]) -> None:
    """Move ``path`` away (it stays alive, pinned) and build something else in its place."""
    path.rename(path.with_name(path.name + ".moved"))
    replacement(path)


def hostile_code(path: Path) -> None:
    _write(path / "__init__.py", "")
    _write(path / "cli" / "__init__.py", "")
    _write(path / "cli" / "main.py", HOSTILE)


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
