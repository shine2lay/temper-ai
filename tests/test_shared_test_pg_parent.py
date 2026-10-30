"""Run the real PG shell script against fixed synthetic Docker/CLI transports.

Only scratch files and the fake daemon state are changed. No live policy,
container, listener, service, credentials or database is read or changed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

TRANSPORT = r'''
import json, os, pathlib, sys
state_path = pathlib.Path(os.environ["FIXTURE_STATE"])
s = json.loads(state_path.read_text())
a = sys.argv[1:]
tool = pathlib.Path(sys.argv[0]).name
with open(os.environ["FIXTURE_CALLS"], "a") as f:
    f.write(json.dumps([tool, *a]) + "\n")
def done(value="", code=0):
    if value != "":
        print(value if isinstance(value, str) else json.dumps(value))
    sys.exit(code)
if tool == "test-cpu":
    if a[0] == "parent":
        if s["mode"] == "inactive":
            done(code=3)
        if s["mode"] == "broken":
            done(code=1)
        done("testcpu.slice")
    if a[0] == "status":
        done({"mode":"enabled", "namespace":"host", "slice":"testcpu.slice"})
    done({"pid":int(a[2]), "inside":s.get("inside", True), "mode":"enabled",
          "slice":"testcpu.slice", "parentOk":True, "cgroup":"/testcpu.slice/docker-fixed.scope"})
if tool == "timeout":
    done(code=0 if s.get("occupied") or s["running"] else 1)
if a[:2] == ["context", "inspect"]:
    done("unix:///var/run/docker.sock")
if a[0] == "info":
    if "CgroupDriver" in a[-1]:
        done({"driver":"systemd", "version":"2", "os":"Linux", "security":[]})
    done("Linux|[]")
if a[:2] == ["container", "inspect"]:
    done(code=0 if s["exists"] else 1)
if a[0] == "inspect":
    if not s["exists"]:
        done(code=1)
    fmt = a[2]
    if "CgroupParent" in fmt:
        done({"id":"fixed-container", "parent":s["parent"], "running":s["running"],
              "pid":s["pid"] if s["running"] else 0})
    if fmt == "{{.State.Running}}":
        done("true" if s["running"] else "false")
    if fmt == "{{.State.Status}}":
        done("running" if s["running"] else "exited")
    if fmt == "{{.HostConfig.NetworkMode}}":
        done(s["network"])
if a[0] == "top":
    done("PID\n" + str(s["pid"]))
if a[0] == "run":
    s.update(exists=True, running=True)
    s["parent"] = next((x.split("=", 1)[1] for x in a if x.startswith("--cgroup-parent=")), "")
    s["network"] = "host" if "host" in a else "bridge"
    state_path.write_text(json.dumps(s))
    done("fixed-container")
if a[0] == "rm":
    s.update(exists=False, running=False)
    state_path.write_text(json.dumps(s))
    done()
if a[0] == "port":
    done("127.0.0.1:" + str(s["port"]))
if a[0] == "exec":
    sql = a[-1]
    if "SHOW listen_addresses" in sql:
        done("127.0.0.1")
    if "SHOW port" in sql:
        done(str(s["port"]))
    if "pg_stat_activity" in sql:
        done(str(s["clients"]))
    if "pg_namespace" in sql:
        done(s["schemas"])
raise AssertionError("unhandled synthetic command: " + repr([tool, *a]))
'''


class PgFixture:
    def __init__(self, root, monkeypatch):
        self.root = root
        self.state = {"mode": "enabled", "exists": False, "running": False,
                      "parent": "testcpu.slice", "pid": os.getpid(), "port": 5456,
                      "clients": 0, "schemas": "", "network": "host"}
        self.script = root / "scripts/test-postgres.sh"
        self.script.parent.mkdir()
        self.script.write_text((REPO / "scripts/test-postgres.sh").read_text())
        helper = root / "tests/test_spawner/test_container_parent.py"
        helper.parent.mkdir(parents=True)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name in ("docker", "test-cpu", "timeout"):
            program = bin_dir / name
            program.write_text(f"#!{sys.executable}\n" + TRANSPORT)
            program.chmod(0o755)
        source = (REPO / "tests/test_spawner/test_container_parent.py").read_text()
        source = source.replace('Path("/usr/local/libexec/test-cpu/bin/test-cpu")',
                                f"Path({str(bin_dir / 'test-cpu')!r})")
        source = source.replace('Path("/etc/agent-tools/test-cpu.json")',
                                f"Path({str(root / 'policy')!r})")
        helper.write_text(source)
        for key in ("TEMPER_TEST_PG_NAME", "TEMPER_TEST_PG_PORT", "TEMPER_TEST_PG_NETWORK",
                    "DOCKER_HOST", "DOCKER_CONTEXT"):
            monkeypatch.delenv(key, raising=False)
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "FIXTURE_STATE": str(root / "state.json"),
                    "FIXTURE_CALLS": str(root / "calls.jsonl"), "XDG_RUNTIME_DIR": str(root)}

    def run(self, *args, **env):
        Path(self.env["FIXTURE_STATE"]).write_text(json.dumps(self.state))
        Path(self.env["FIXTURE_CALLS"]).write_text("")
        result = subprocess.run(["bash", str(self.script), *args], env={**self.env, **env},
                                capture_output=True, text=True, timeout=30)
        self.state = json.loads(Path(self.env["FIXTURE_STATE"]).read_text())
        self.calls = [json.loads(line) for line in Path(self.env["FIXTURE_CALLS"]).read_text().splitlines()]
        return result

    def changes(self):
        return [c for c in self.calls if c[:2] in [["docker", "run"], ["docker", "rm"]]]


@pytest.fixture
def pg(tmp_path, monkeypatch):
    return PgFixture(tmp_path, monkeypatch)


def test_new_capped_pg_loopback_then_reuse_then_nonforce_cleanup(pg):
    result = pg.run("url")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "postgresql://temper_ai:test@127.0.0.1:5456/temper_ai_test\n"
    creates = [c for c in pg.changes() if c[1] == "run"]
    assert len(creates) == 1
    cmd = creates[0]
    assert cmd[cmd.index("--name") + 1] == "temper-test-postgres-cpu"
    assert cmd.count("--cgroup-parent=testcpu.slice") == 1
    assert "listen_addresses=127.0.0.1" in cmd and "PGPORT=5456" in cmd
    assert "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256" in cmd
    assert "--tmpfs" in cmd and "max_connections=300" in cmd
    assert not any("temper-test-postgres" in c[1:] for c in pg.calls)
    assert (pg.root / "temper-test-postgres-temper-test-postgres-cpu.lock").exists()
    assert pg.run("url").returncode == 0
    assert pg.changes() == []
    assert pg.run("down").returncode == 0
    assert pg.changes() == [["docker", "rm", "-f", "temper-test-postgres-cpu"]]


def test_inactive_legacy_name_port_and_create_flags_stay_the_same(pg):
    pg.state.update(mode="inactive", port=5455)
    result = pg.run("url")
    assert result.returncode == 0, result.stderr
    assert ":5455/" in result.stdout
    creates = [c for c in pg.changes() if c[1] == "run"]
    assert creates[0][creates[0].index("--name") + 1] == "temper-test-postgres"
    assert not any(x.startswith("--cgroup-parent") for x in creates[0])
    assert not any(c[1] == "membership" for c in pg.calls)


@pytest.mark.parametrize("mode", ["inactive", "enabled"])
@pytest.mark.parametrize("use", ["clients", "schemas"])
def test_client_and_live_schema_fences_still_protect_pg(pg, mode, use):
    pg.state.update(mode=mode, exists=True, running=True)
    if use == "clients":
        pg.state["clients"] = 2
    else:
        pg.state["schemas"] = f"tier_p{os.getpid()}_main"
    result = pg.run("down")
    assert result.returncode == 1 and "it is in use" in result.stderr
    assert pg.changes() == []


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("verb", ["url", "down"])
def test_existing_off_parent_is_not_adopted_replaced_or_removed(pg, running, verb):
    pg.state.update(exists=True, running=running, parent="")
    result = pg.run(verb)
    assert result.returncode == 1 and "wrong parent" in result.stderr
    assert pg.changes() == []


@pytest.mark.parametrize("env", [{"TEMPER_TEST_PG_NAME": "temper-test-postgres"},
    {"TEMPER_TEST_PG_PORT": "5455"}, {"TEMPER_TEST_PG_PORT": "5433"},
    {"TEMPER_TEST_PG_PORT": "5432"}, {"TEMPER_TEST_PG_PORT": "65536"},
    {"TEMPER_TEST_PG_NAME": "production"}])
def test_enabled_explicit_legacy_or_live_names_ports_refused(pg, env):
    result = pg.run("url", **env)
    assert result.returncode == 1 and "separate" in result.stderr
    assert pg.changes() == []


def test_broken_contract_occupied_port_and_wrong_membership_have_no_fallback(pg):
    pg.state["mode"] = "broken"
    assert pg.run("url").returncode == 1
    assert pg.changes() == []
    pg.state.update(mode="enabled", occupied=True)
    result = pg.run("url")
    assert result.returncode == 1 and "something already answers" in result.stderr
    assert not any(c[1] == "run" for c in pg.changes())
    pg.state.update(occupied=False, exists=True, running=True, inside=False)
    result = pg.run("url")
    assert result.returncode == 1
    assert pg.changes() == []


@pytest.mark.parametrize("network", ["host", "bridge"])
def test_reuse_must_match_the_requested_loopback_port(pg, network):
    pg.state.update(exists=True, running=True, network=network, port=5459)
    result = pg.run("url")
    assert result.returncode == 1 and "mismatch" in result.stderr
    assert pg.changes() == []


def test_active_force_cannot_override_live_pg_safety(pg):
    pg.state.update(exists=True, running=True, clients=1)
    result = pg.run("down", "--force")
    assert result.returncode == 1 and "refuses forced cleanup" in result.stderr
    assert pg.changes() == []


def test_bridge_new_pg_is_loopback_only(pg):
    result = pg.run("url", TEMPER_TEST_PG_NETWORK="bridge")
    assert result.returncode == 0, result.stderr
    create = next(c for c in pg.changes() if c[1] == "run")
    assert create[create.index("-p") + 1] == "127.0.0.1:5456:5432"


@pytest.mark.parametrize("remove", ["parent", "verify"])
def test_removed_parent_or_reuse_verifier_is_caught(pg, remove):
    """A fixed red control, not an assertion that old code is compliant."""
    source = pg.script.read_text()
    if remove == "parent":
        source = source.replace('"${parent_args[@]}" "${net[@]}"', '"${net[@]}"')
        pg.script.write_text(source)
        result = pg.run("url")
        assert result.returncode == 1 and "wrong parent" in result.stderr
    else:
        pg.state.update(exists=True, running=True, parent="")
        assert pg.run("url").returncode == 1  # correct verifier catches the broken reuse
        source = source.replace('python3 "$PARENT_CONTRACT" verify "$NAME" --stopped', ':')
        source = source.replace('python3 "$PARENT_CONTRACT" verify "$NAME"', ':')
        pg.script.write_text(source)
        assert pg.run("url").returncode == 0  # guard removal would fail that fixed answer
