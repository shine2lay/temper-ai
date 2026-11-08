"""Unit tests for configs/epd/bin/stack_ref.py and stack_up_ref / stack_seed / stack_down."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import jinja2
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "configs" / "epd" / "bin" / "stack_ref.py"
AGENTS_DIR = REPO_ROOT / "configs" / "epd" / "agents"


def _load_module():
    spec = importlib.util.spec_from_file_location("stack_ref", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stack_ref"] = mod
    spec.loader.exec_module(mod)
    return mod


stack_ref = _load_module()


def _git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout.strip()


@pytest.fixture()
def git_repos(tmp_path: Path) -> dict[str, Any]:
    """Create an upstream origin repo and a local clone under workspaces/repos/rollcall/main."""
    upstream = tmp_path / "upstream" / "rollcall.git"
    upstream.mkdir(parents=True)
    _git(upstream, "init", "--bare", "-b", "master")

    work = tmp_path / "seed_work"
    work.mkdir(parents=True)
    _git(work, "init", "-b", "master")
    (work / "README.md").write_text("v1\n")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "initial commit")
    sha1 = _git(work, "rev-parse", "HEAD")
    _git(work, "remote", "add", "origin", str(upstream))
    _git(work, "push", "-u", "origin", "master")

    workspaces = tmp_path / "workspaces"
    clone = workspaces / "repos" / "rollcall" / "main"
    clone.parent.mkdir(parents=True)
    subprocess.run(
        ["git", "clone", "--quiet", str(upstream), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )

    def advance_origin(content: str = "v2\n") -> str:
        (work / "README.md").write_text(content)
        _git(work, "add", "README.md")
        _git(work, "commit", "-m", "advance master")
        new_sha = _git(work, "rev-parse", "HEAD")
        _git(work, "push", "origin", "master")
        return new_sha

    return {
        "upstream": upstream,
        "work": work,
        "workspaces": workspaces,
        "clone": clone,
        "sha1": sha1,
        "advance_origin": advance_origin,
    }


@pytest.fixture()
def fake_bins(tmp_path: Path) -> dict[str, Any]:
    """Create stateful fake `standee` and `docker` executables."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state_file = tmp_path / "fake_state.json"
    state_file.write_text(
        json.dumps(
            {
                "envs": {},
                "calls": [],
                "volumes": [],
                "sticky_volumes": [],
                "seed_rc": 0,
                "down_rc": 0,
                "up_rc": 0,
            }
        )
    )

    standee_script = bin_dir / "standee"
    standee_script.write_text(
        f"""#!{sys.executable}
import json, sys
from pathlib import Path

state_path = Path({str(state_file)!r})
state = json.loads(state_path.read_text())
args = sys.argv[1:]
state["calls"].append(["standee", *args])

def save():
    state_path.write_text(json.dumps(state))

cmd = args[0] if args else ""
if cmd == "status":
    name = args[1]
    env = state["envs"].get(name)
    save()
    if not env:
        sys.stderr.write(f"no environment named {{name}}\\n")
        raise SystemExit(1)
    sys.stdout.write(json.dumps(env) + "\\n")
    raise SystemExit(0)

if cmd == "up":
    if state.get("up_rc", 0) != 0:
        save()
        sys.stderr.write("simulated standee up failure\\n")
        raise SystemExit(state["up_rc"])
    project = args[args.index("--project") + 1]
    slug = args[args.index("--as") + 1]
    tier = args[args.index("--tier") + 1]
    ref_sha = args[args.index("--ref") + 1]
    ttl = args[args.index("--ttl") + 1] if "--ttl" in args else "3d"
    name = f"{{project}}-{{tier}}-{{slug}}"
    url = f"https://{{name}}.spark-d496.ts.net"
    state["envs"][name] = {{
        "kind": "managed",
        "name": name,
        "project": project,
        "tier": tier,
        "url": url,
        "status": "running",
        "ttl": ttl,
        "commit": {{
            "sha": ref_sha,
            "short": ref_sha[:7],
            "ref": ref_sha,
            "dirty": False,
            "subject": "pinned commit",
        }},
    }}
    save()
    sys.stdout.write(f"✓ {{name}} is up at {{url}}\\n")
    raise SystemExit(0)

if cmd == "renew":
    name = args[1]
    env = state["envs"].get(name)
    if not env:
        save()
        raise SystemExit(1)
    if "--forever" in args:
        env["ttl"] = None
    elif "--for" in args:
        env["ttl"] = args[args.index("--for") + 1]
    save()
    sys.stdout.write(f"✓ {{name}} renewed\\n")
    raise SystemExit(0)

if cmd == "seed":
    name = args[1]
    rc = state.get("seed_rc", 0)
    save()
    if rc != 0 or name not in state["envs"]:
        sys.stderr.write(f"seed failed for {{name}}\\n")
        raise SystemExit(rc or 1)
    sys.stdout.write(f"✓ {{name}} seeded\\n")
    raise SystemExit(0)

if cmd == "down":
    name = args[1]
    rc = state.get("down_rc", 0)
    if rc != 0:
        save()
        sys.stderr.write(f"down failed for {{name}}\\n")
        raise SystemExit(rc)
    if name not in state["envs"]:
        save()
        sys.stderr.write(f"standee: no environment named {{name}}\\n")
        raise SystemExit(1)
    del state["envs"][name]
    save()
    sys.stdout.write(f"✓ {{name}} is down\\n")
    raise SystemExit(0)

save()
raise SystemExit(2)
"""
    )
    standee_script.chmod(0o755)

    docker_script = bin_dir / "docker"
    docker_script.write_text(
        f"""#!{sys.executable}
import json, sys
from pathlib import Path

state_path = Path({str(state_file)!r})
state = json.loads(state_path.read_text())
args = sys.argv[1:]
state["calls"].append(["docker", *args])

def save():
    state_path.write_text(json.dumps(state))

if args[:2] == ["volume", "ls"]:
    vols = sorted(set(state.get("volumes", [])) | set(state.get("sticky_volumes", [])))
    save()
    if "--filter" in args:
        flt = args[args.index("--filter") + 1]
        proj = flt.split("com.docker.compose.project=", 1)[-1]
        matched = [v for v in vols if v.startswith(proj + "_")]
        sys.stdout.write("\\n".join(matched) + ("\\n" if matched else ""))
        raise SystemExit(0)
    sys.stdout.write("\\n".join(vols) + ("\\n" if vols else ""))
    raise SystemExit(0)

if args[:2] == ["volume", "rm"]:
    target = args[-1]
    if target in state.get("volumes", []) and target not in state.get("sticky_volumes", []):
        state["volumes"].remove(target)
        save()
        sys.stdout.write(target + "\\n")
        raise SystemExit(0)
    save()
    sys.stderr.write("cannot remove volume\\n")
    raise SystemExit(1)

save()
raise SystemExit(0)
"""
    )
    docker_script.chmod(0o755)

    def read_state() -> dict[str, Any]:
        return json.loads(state_file.read_text())

    def update_state(**patch: Any) -> None:
        cur = read_state()
        cur.update(patch)
        state_file.write_text(json.dumps(cur))

    return {
        "bin_dir": bin_dir,
        "standee": str(standee_script),
        "docker": str(docker_script),
        "read_state": read_state,
        "update_state": update_state,
    }


def test_up_fresh_then_reused_then_rebuild_on_ref_move(
    git_repos: dict[str, Any],
    fake_bins: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_DIR", str(git_repos["workspaces"]))
    sha1 = git_repos["sha1"]

    # 1. First up builds fresh (reused=False).
    out1 = stack_ref.cmd_up(
        product="rollcall",
        ref="origin/master",
        slug="design",
        ttl="12h",
        standee_bin=fake_bins["standee"],
    )
    assert out1 == {
        "status": "up",
        "env_name": "rollcall-dev-design",
        "base_url": "https://rollcall-dev-design.spark-d496.ts.net",
        "url": "https://rollcall-dev-design.spark-d496.ts.net",
        "commit": sha1,
        "short_commit": sha1[:7],
        "ref": "origin/master",
        "product": "rollcall",
        "reused": False,
    }

    # 2. Second up at the same commit reuses existing env without calling `standee up`,
    #    and renews TTL when `--ttl` is supplied.
    calls_before = len(fake_bins["read_state"]()["calls"])
    out2 = stack_ref.cmd_up(
        product="rollcall",
        ref="origin/master",
        slug="design",
        ttl="24h",
        standee_bin=fake_bins["standee"],
    )
    assert out2["reused"] is True
    assert out2["commit"] == sha1
    new_calls = fake_bins["read_state"]()["calls"][calls_before:]
    verbs = [c[1] for c in new_calls if c[0] == "standee"]
    assert verbs == ["status", "renew"]
    assert fake_bins["read_state"]()["envs"]["rollcall-dev-design"]["ttl"] == "24h"

    # 3. Advance origin/master in upstream without manually fetching in clone;
    #    cmd_up must fetch origin, detect the new SHA, and rebuild (reused=False).
    sha2 = git_repos["advance_origin"]("v2 content\n")
    assert sha2 != sha1
    out3 = stack_ref.cmd_up(
        product="rollcall",
        ref="origin/master",
        slug="design",
        standee_bin=fake_bins["standee"],
    )
    assert out3["reused"] is False
    assert out3["commit"] == sha2
    assert out3["short_commit"] == sha2[:7]


def test_seed_and_down_lifecycle_and_leftover_volumes(
    git_repos: dict[str, Any],
    fake_bins: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_DIR", str(git_repos["workspaces"]))
    stack_ref.cmd_up(
        product="rollcall",
        ref="origin/master",
        slug="design",
        standee_bin=fake_bins["standee"],
    )

    # Seed by explicit env_name.
    seeded = stack_ref.cmd_seed(
        env_name="rollcall-dev-design",
        standee_bin=fake_bins["standee"],
    )
    assert seeded == {"status": "seeded", "env_name": "rollcall-dev-design"}

    # Down with a straggler volume that docker volume rm cleans up.
    fake_bins["update_state"](volumes=["rollcall-dev-design_pgdata"])
    down = stack_ref.cmd_down(
        env_name="rollcall-dev-design",
        standee_bin=fake_bins["standee"],
        docker_bin=fake_bins["docker"],
    )
    assert down == {
        "status": "down",
        "env_name": "rollcall-dev-design",
        "volumes_left": "none",
        "leftover_volumes_removed": 1,
    }
    assert fake_bins["read_state"]()["volumes"] == []

    # Second down when already absent returns status="absent".
    absent = stack_ref.cmd_down(
        env_name="rollcall-dev-design",
        standee_bin=fake_bins["standee"],
        docker_bin=fake_bins["docker"],
    )
    assert absent["status"] == "absent"
    assert absent["volumes_left"] == "none"

    # Sticky volume that refuses removal fails loud and fast.
    fake_bins["update_state"](sticky_volumes=["rollcall-dev-design_stuck"])
    with pytest.raises(stack_ref.StackRefError) as exc_info:
        stack_ref.cmd_down(
            env_name="rollcall-dev-design",
            standee_bin=fake_bins["standee"],
            docker_bin=fake_bins["docker"],
        )
    assert exc_info.value.extra.get("volumes_left") == "rollcall-dev-design_stuck"


@pytest.mark.parametrize(
    ("argv", "expected_substring"),
    [
        (["up", "--product", ""], "invalid product"),
        (["up", "--product", "../evil"], "invalid product"),
        (["up", "--product", "temper"], "forbidden"),
        (["up", "--product", "rollcall", "--slug", ""], "invalid slug"),
        (["up", "--product", "rollcall", "--slug", "../bad"], "invalid slug"),
        (["up", "--product=rollcall", "--ref=--upload-pack=evil"], "invalid git ref"),
        (["up", "--product", "rollcall", "--ref", "main..next"], "invalid git ref"),
        (["up", "--product", "rollcall", "--ref", "HEAD@{0}"], "invalid git ref"),
        (["up", "--product", "rollcall", "--ttl", "forever"], "invalid ttl"),
        (["seed", "--env-name", "rollcall-prod"], "invalid env_name"),
        (["seed", "--env-name", "temper-dev"], "invalid env_name"),
        (["down", "--env-name", "rollcall-prod"], "invalid env_name"),
        (["down", "--env-name", "temper-dev"], "invalid env_name"),
    ],
)
def test_cli_fails_loud_and_fast_on_invalid_inputs(
    argv: list[str],
    expected_substring: str,
) -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *argv],
        capture_output=True,
        text=True,
        timeout=15,
    )
    rc = proc.returncode
    assert rc == 1
    payload = json.loads(proc.stdout.strip())
    assert payload["status"] == "failed"
    assert expected_substring in payload["error"]


def test_unresolvable_ref_fails_loud_and_fast(
    git_repos: dict[str, Any],
    fake_bins: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_DIR", str(git_repos["workspaces"]))
    with pytest.raises(stack_ref.StackRefError) as exc_info:
        stack_ref.cmd_up(
            product="rollcall",
            ref="origin/does-not-exist",
            slug="design",
            standee_bin=fake_bins["standee"],
        )
    assert "cannot resolve ref" in exc_info.value.message


def test_script_agent_yamls_render_and_execute(
    git_repos: dict[str, Any],
    fake_bins: dict[str, Any],
) -> None:
    env = {
        **os.environ,
        "WORKSPACE_DIR": str(git_repos["workspaces"]),
        "STANDEE_BIN": fake_bins["standee"],
        "DOCKER_BIN": fake_bins["docker"],
    }

    def run_agent_yaml(filename: str, variables: dict[str, str]) -> dict[str, Any]:
        doc = yaml.safe_load((AGENTS_DIR / filename).read_text())
        rendered = jinja2.Environment().from_string(doc["agent"]["script_template"]).render(
            **variables
        )
        assert "${" not in rendered
        proc = subprocess.run(
            ["sh", "-c", rendered],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        rc = proc.returncode
        assert rc == 0
        return json.loads(proc.stdout.strip())

    up_res = run_agent_yaml(
        "stack_up_ref.yaml",
        {"product": "rollcall", "ref": "origin/master", "slug": "design"},
    )
    assert up_res["status"] == "up"
    assert up_res["reused"] is False
    assert up_res["commit"] == git_repos["sha1"]

    up_reused = run_agent_yaml(
        "stack_up_ref.yaml",
        {"product": "rollcall"},
    )
    assert up_reused["status"] == "up"
    assert up_reused["reused"] is True

    seed_res = run_agent_yaml(
        "stack_seed.yaml",
        {"env_name": "rollcall-dev-design"},
    )
    assert seed_res == {"status": "seeded", "env_name": "rollcall-dev-design"}

    down_res = run_agent_yaml(
        "stack_down.yaml",
        {"env_name": "rollcall-dev-design"},
    )
    assert down_res["status"] == "down"
    assert down_res["volumes_left"] == "none"


def test_departments_md_lists_systems_stack_ref_configs() -> None:
    text = (REPO_ROOT / "docs" / "departments.md").read_text()
    section = text.split("### systems (", 1)[1].split("\n### ", 1)[0]
    declared_count = int(section.split(")", 1)[0])
    rows = [
        line
        for line in section.splitlines()
        if line.startswith("| `")
    ]
    assert len(rows) == declared_count
    for expected in (
        "`epd/agents/stack_up_ref.yaml`",
        "`epd/agents/stack_seed.yaml`",
        "`epd/agents/stack_down.yaml`",
        "`epd/bin/stack_ref.py`",
    ):
        assert any(expected in r for r in rows)


def test_run_standee_uses_default_ssh_target_when_target_file_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ssh_dir = tmp_path / "standee-ssh"
    ssh_dir.mkdir(parents=True)
    key_file = ssh_dir / "id_ed25519"
    key_file.write_text("fake-key\n")
    key_file.chmod(0o644)
    known_hosts = ssh_dir / "known_hosts"
    known_hosts.write_text("host.docker.internal ssh-ed25519 AAAAC3Nza\n")

    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        idx = cmd.index("-i")
        temp_key_path = Path(cmd[idx + 1])
        captured["cmd"] = cmd
        captured["key_exists_during_run"] = temp_key_path.is_file()
        captured["key_mode"] = oct(temp_key_path.stat().st_mode & 0o777)
        captured["temp_key_path"] = temp_key_path
        return subprocess.CompletedProcess(cmd, 0, '{"state":"running"}\n', "")

    monkeypatch.delenv("STANDEE_BIN", raising=False)
    monkeypatch.setattr(stack_ref.subprocess, "run", fake_run)

    proc = stack_ref.run_standee(["status", "rollcall-dev-design", "--json"], ssh_dir=ssh_dir)
    assert proc.returncode == 0
    assert captured["key_exists_during_run"] is True
    assert captured["key_mode"] == "0o600"
    assert not captured["temp_key_path"].exists()
    assert stack_ref.DEFAULT_STANDEE_SSH_TARGET in captured["cmd"]
    assert f"UserKnownHostsFile={known_hosts}" in captured["cmd"]


def test_fetch_and_resolve_ref_fast_forwards_clean_main_checkout(
    git_repos: dict[str, Any],
) -> None:
    clone: Path = git_repos["clone"]
    sha1: str = git_repos["sha1"]
    sha2: str = git_repos["advance_origin"]("new content\n")
    assert sha2 != sha1
    head_before = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_before == sha1

    resolved = stack_ref.fetch_and_resolve_ref(clone, "origin/master")
    assert resolved == sha2
    head_after = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_after == sha2
    assert (clone / "README.md").read_text() == "new content\n"


