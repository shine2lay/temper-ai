"""Fixed, fake-transport controls. These do not qualify the live Docker daemon."""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

from tests.test_spawner import box_fixtures as boxes
from tests.test_spawner import test_container_parent as placement


class FixedClock:
    """Advance only on explicit synthetic work; enforce the timeout it receives."""

    def __init__(self, monkeypatch, module):
        self.now = 0.0
        monkeypatch.setattr(module, "time", types.SimpleNamespace(
            monotonic=lambda: self.now, sleep=self.advance))

    def advance(self, seconds, timeout=None, cmd=None):
        if timeout is not None and seconds > timeout:
            self.now += timeout
            raise subprocess.TimeoutExpired(cmd, timeout, output=b"partial", stderr=b"query")
        self.now += seconds


class DockerTransport:
    def __init__(self, monkeypatch, module=placement):
        self.module = module
        self.clock = FixedClock(monkeypatch, module)
        self.calls = []
        self.parent_code = 0
        self.parent_text = "testcpu.slice\n"
        self.status = {"mode": "enabled", "namespace": "host", "slice": "testcpu.slice"}
        self.info = {"driver": "systemd", "version": "2", "os": "Linux", "security": []}
        self.row = {"id": "fixture-id", "parent": "testcpu.slice", "running": True, "pid": 101}
        self.top = "PID\n101\n102\n"
        self.member = {"inside": True, "mode": "enabled", "slice": "testcpu.slice",
                       "parentOk": True, "cgroup": "/testcpu.slice/docker-fixture.scope"}
        self.endpoint = "unix:///var/run/docker.sock"
        self.builder = {"Name": "default", "Current": True, "Driver": "docker", "Nodes": [
            {"Endpoint": self.endpoint, "Status": "running"}]}
        self.help = "--cgroup-parent string"
        self.code = 0
        self.change_identity = False
        self.inspects = 0
        # The synthetic installed CLI is intercepted, never executed.
        monkeypatch.setattr(module, "CLI", Path(__file__))
        monkeypatch.delenv("DOCKER_HOST", raising=False)
        monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
        monkeypatch.setattr(module.subprocess, "run", self.run)
        monkeypatch.setattr(module, "_start_time", lambda pid: f"start-{pid}")

    def run(self, cmd, **kwargs):
        cmd = list(cmd)
        self.calls.append((cmd, kwargs))
        code, output = 0, ""
        if cmd[0] == str(self.module.CLI):
            if cmd[1] == "parent":
                code, output = self.parent_code, self.parent_text
            elif cmd[1] == "status":
                output = json.dumps(self.status)
            else:
                output = json.dumps({"pid": int(cmd[3]), **self.member})
        elif cmd[1:3] == ["context", "inspect"]:
            output = self.endpoint
        elif cmd[1] == "info":
            output = json.dumps(self.info)
        elif cmd[1] == "inspect":
            self.inspects += 1
            row = dict(self.row)
            if self.change_identity and self.inspects > 1:
                row["id"] = "replaced"
            output = json.dumps(row)
        elif cmd[1] == "top":
            output = self.top
        elif cmd[1:3] == ["buildx", "ls"]:
            # The installed buildx emits its default builder twice.
            output = json.dumps(self.builder) + "\n" + json.dumps(self.builder)
        elif cmd[1:4] == ["buildx", "build", "--help"]:
            output = self.help
        else:
            code, output = self.code, "payload-output"
        if not kwargs.get("text"):
            output = output.encode()
        result = subprocess.CompletedProcess(cmd, code, output, "" if kwargs.get("text") else b"")
        if kwargs.get("check"):
            result.check_returncode()
        return result


@pytest.fixture
def docker(monkeypatch):
    return DockerTransport(monkeypatch)


def test_happy_create_reuse_exec_and_build_share_one_contract(docker):
    parent = placement.container_parent()
    assert parent.create_args() == ["--cgroup-parent=testcpu.slice"]
    run = ["docker", "run", "--detach", "--name", "test-box", "test-image"]
    assert placement.run_test_docker(run, text=True).returncode == 0
    parent.verify("test-box")
    execute = ["docker", "exec", "-i", "--user", "1000:1000", "test-box", "writer"]
    result = placement.run_test_docker(execute, input=b"synthetic", capture_output=True)
    assert result.stdout == b"payload-output" and result.args == execute
    build = ["docker", "build", "-t", "test-image", "-"]
    placement.run_test_docker(build, input="RUN true", text=True)
    actual = [c for c, _ in docker.calls if c[1] == "run"]
    assert actual == [["docker", "run", "--cgroup-parent=testcpu.slice", *run[2:]]]
    assert (["docker", "buildx", "build", "--builder", "default", "--load",
             "--cgroup-parent=testcpu.slice", *build[2:]], {"input": "RUN true", "text": True}) in docker.calls
    assert {c[3] for c, _ in docker.calls if c[1] == "membership"} == {"101", "102"}
    assert not any("--cpus" in c or "--cpu-quota" in c for c, _ in docker.calls)


@pytest.mark.parametrize("verb", ["run", "exec", "build"])
@pytest.mark.parametrize("code", [0, 7])
def test_inactive_keeps_argv_stdin_result_and_no_daemon_checks(docker, verb, code):
    docker.parent_code, docker.code = 3, code
    cmd = ["docker", verb, "synthetic"]
    result = placement.run_test_docker(cmd, input=b"synthetic", capture_output=True, timeout=17)
    assert (result.args, result.returncode, result.stdout, result.stderr) == (cmd, code, b"payload-output", b"")
    assert docker.calls == [([str(placement.CLI), "parent"],
                             {"capture_output": True, "text": True, "timeout": 17}),
                            (cmd, {"input": b"synthetic", "capture_output": True, "timeout": 17})]


def test_missing_install_is_inactive_only_without_any_policy(monkeypatch, tmp_path):
    cli, policy = tmp_path / "cli", tmp_path / "policy"
    monkeypatch.setattr(placement, "CLI", cli)
    monkeypatch.setattr(placement, "POLICY", policy)
    def absent(*args, **kwargs):
        raise FileNotFoundError("not installed")
    monkeypatch.setattr(placement.subprocess, "run", absent)
    assert placement.container_parent() is None
    policy.symlink_to(tmp_path / "missing")
    with pytest.raises(placement.ContainerParentError, match="policy present"):
        placement.container_parent()
    policy.unlink()
    cli.write_text("broken interpreter")
    with pytest.raises(placement.ContainerParentError):
        placement.container_parent()


def test_absent_install_is_not_invented_by_an_existing_docker_mock(monkeypatch, tmp_path):
    monkeypatch.setattr(placement, "CLI", tmp_path / "absent-cli")
    monkeypatch.setattr(placement, "POLICY", tmp_path / "absent-policy")
    calls = []
    def docker_only(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(placement.subprocess, "run", docker_only)
    execute = ["docker", "exec", "box-d"]
    assert placement.run_test_docker(execute).returncode == 0
    assert calls == [execute]
    placement.POLICY.write_text("present, not a valid bypass")
    with pytest.raises(placement.ContainerParentError, match="policy present"):
        placement.run_test_docker(execute)
    assert calls == [execute]


@pytest.mark.parametrize(("code", "text"), [(1, "testcpu.slice"), (125, ""),
    (0, "../other.slice"), (0, "testcpu.slice\nextra"), (0, "other-name.slice"), (0, "")])
def test_parent_refusal_is_not_inactive(docker, code, text):
    docker.parent_code, docker.parent_text = code, text
    with pytest.raises(placement.ContainerParentError, match="parent refused"):
        placement.container_parent()
    assert len(docker.calls) == 1


@pytest.mark.parametrize(("field", "value"), [("mode", "inactive"), ("namespace", "foreign"),
                                            ("slice", "another.slice")])
def test_host_status_must_agree_with_parent(docker, field, value):
    docker.status[field] = value
    with pytest.raises(placement.ContainerParentError, match="host cgroup namespace"):
        placement.container_parent()


@pytest.mark.parametrize(("field", "value"), [("driver", "cgroupfs"), ("version", "1"),
    ("os", "Docker Desktop"), ("security", ["name=rootless"]), ("security", None)])
def test_wrong_daemon_is_refused_before_create(docker, field, value):
    docker.info[field] = value
    with pytest.raises(placement.ContainerParentError, match="rootful"):
        placement.run_test_docker(["docker", "run", "--name", "box", "image"])
    assert not any(c[1] == "run" for c, _ in docker.calls)


def test_remote_endpoint_and_context_precedence(docker, monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "ssh://remote")
    with pytest.raises(placement.ContainerParentError, match="local Docker"):
        placement.container_parent()
    monkeypatch.setenv("DOCKER_CONTEXT", "local-fixture")
    assert placement.container_parent() is not None  # context overrides host, like Docker
    docker.endpoint = "tcp://127.0.0.1:2375"
    with pytest.raises(placement.ContainerParentError, match="local Docker"):
        placement.container_parent()


@pytest.mark.parametrize(("field", "value"), [("parent", ""), ("parent", "other.slice"),
    ("pid", 0), ("pid", "101"), ("running", False), ("id", "")])
def test_reuse_wrong_parent_or_identity_never_moves_or_deletes(docker, field, value):
    docker.row[field] = value
    with pytest.raises(placement.ContainerParentError):
        placement.ContainerParent("testcpu.slice").verify("box")
    assert not any(c[1] in {"rm", "update", "kill", "run"} for c, _ in docker.calls)


@pytest.mark.parametrize(("field", "value"), [("inside", False), ("pid", 888),
    ("mode", "inactive"), ("slice", "another.slice"), ("parentOk", False),
    ("cgroup", "/testcpu.slice-other/container"), ("cgroup", "/user.slice/container")])
def test_membership_requires_host_pid_path_policy_and_quota(docker, field, value):
    docker.member[field] = value
    with pytest.raises(placement.ContainerParentError, match="outside"):
        placement.ContainerParent("testcpu.slice").verify("box")


@pytest.mark.parametrize("top", ["", "PID\n102\n", "PID\nnot-a-pid\n", "COMMAND\n101\n"])
def test_unreadable_or_incomplete_pid_set_is_not_proof(docker, top):
    docker.top = top
    with pytest.raises(placement.ContainerParentError):
        placement.ContainerParent("testcpu.slice").verify("box")


def test_replaced_container_or_recycled_pid_refuses(docker, monkeypatch):
    docker.change_identity = True
    with pytest.raises(placement.ContainerParentError, match="identity changed"):
        placement.ContainerParent("testcpu.slice").verify("box")
    docker.change_identity = False
    ticks = iter(["init", "before", "after"])
    monkeypatch.setattr(placement, "_start_time", lambda pid: next(ticks))
    with pytest.raises(placement.ContainerParentError, match="PID identity changed"):
        placement.ContainerParent("testcpu.slice").verify("box")


def test_stopped_check_is_not_membership_or_permission_to_adopt(docker):
    docker.row.update(running=False, pid=0)
    parent = placement.ContainerParent("testcpu.slice")
    parent.verify("box", stopped=True)
    assert len(docker.calls) == 1
    with pytest.raises(placement.ContainerParentError):
        parent.verify("box")
    docker.row["parent"] = ""
    with pytest.raises(placement.ContainerParentError):
        parent.verify("box", stopped=True)


@pytest.mark.parametrize("broken", ["driver", "remote", "stopped", "multiple", "flag", "failed"])
def test_builder_unsupported_or_failed_is_failure_not_skip(docker, broken):
    if broken == "driver":
        docker.builder["Driver"] = "docker-container"
    elif broken == "remote":
        docker.builder["Nodes"][0]["Endpoint"] = "unix:///other.sock"
    elif broken == "stopped":
        docker.builder["Nodes"][0]["Status"] = "stopped"
    elif broken == "multiple":
        docker.builder["Nodes"].append(dict(docker.builder["Nodes"][0]))
    elif broken == "flag":
        docker.help = "no supported parent option"
    else:
        docker.code = 1
    with pytest.raises(placement.ContainerParentError):
        placement.run_test_docker(["docker", "build", "-"], input="RUN true", text=True)


def test_no_caller_selected_parent_and_no_exec_before_verification(docker):
    with pytest.raises(placement.ContainerParentError, match="already chooses"):
        placement.run_test_docker(["docker", "run", "--cgroup-parent=escape", "--name", "box", "image"])
    docker.member["inside"] = False
    with pytest.raises(placement.ContainerParentError):
        placement.run_test_docker(["docker", "exec", "-i", "--user", "1:1", "box", "writer"], input=b"fixed")
    assert not any(c[1] in {"run", "exec"} for c, _ in docker.calls)


def test_box_adapter_and_old_call_site_control(docker, monkeypatch):
    """Execute the old subprocess.run call site as a negative wiring control."""
    fake_install = types.SimpleNamespace()
    name = boxes.run_id("parent")
    cmd = ["docker", "run", "--detach", "--name", name, "--entrypoint", "python", "image"]
    monkeypatch.setattr(placement.ContainerParent, "_foreground",
                        lambda self, cmd, name, **kw: subprocess.run(cmd, **kw))
    box = boxes.BoxDocker(fake_install)
    box(cmd)
    runs = [c for c, _ in docker.calls if c[1] == "run"]
    assert "--cgroup-parent=testcpu.slice" in runs[-1]
    assert [c for c, _ in docker.calls if c[1] == "rm"] == [["docker", "rm", "-f", name]]
    source = textwrap.dedent(inspect.getsource(boxes.BoxDocker.__call__))
    source = source.replace("run_test_docker(cmd,", "subprocess.run(cmd,")
    namespace = dict(vars(boxes))
    exec(compile(source, "old-BoxDocker-call", "exec"), namespace)
    namespace["__call__"](box, cmd)
    assert not any(c.startswith("--cgroup-parent") for c in docker.calls[-2][0])


@pytest.mark.parametrize("error", [False, True])
def test_box_inactive_failure_or_timeout_always_cleans_own_name(docker, monkeypatch, error):
    docker.parent_code = 3
    name = boxes.run_id("cleanup")
    original = docker.run
    def payload(cmd, **kw):
        if cmd[1] == "run":
            if error:
                raise subprocess.TimeoutExpired(cmd, 120)
            docker.code = 4
        return original(cmd, **kw)
    monkeypatch.setattr(placement.subprocess, "run", payload)
    box = boxes.BoxDocker(types.SimpleNamespace())
    cmd = ["docker", "run", "--detach", "--name", name, "image"]
    if error:
        with pytest.raises(subprocess.TimeoutExpired):
            box(cmd)
    else:
        assert box(cmd).returncode == 4
    assert docker.calls[-1][0] == ["docker", "rm", "-f", name]


def test_foreground_holds_original_entry_until_membership_then_preserves_result(docker, monkeypatch):
    events = []
    class Process:
        returncode = 9
        def __init__(self, cmd, **kwargs):
            events.append((cmd, kwargs))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def poll(self):
            return None
        def communicate(self, data=None, **kwargs):
            events.append(data)
            return "out", "err"
        def kill(self):
            events.append("kill")
    original = docker.run
    def query(cmd, **kw):
        if cmd[1] == "inspect" and cmd[3] == "{{.State.Running}}":
            return subprocess.CompletedProcess(cmd, 0, "true", "")
        return original(cmd, **kw)
    monkeypatch.setattr(placement.subprocess, "run", query)
    monkeypatch.setattr(placement.subprocess, "Popen", Process)
    monkeypatch.setattr(placement.ContainerParent, "verify", lambda *a: events.append("verified"))
    result = placement.run_test_docker(
        ["docker", "run", "--name", "box", "--entrypoint", "python", "image", "-c", "fixed"],
        capture_output=True, text=True, timeout=120)
    assert (result.returncode, result.stdout, result.stderr) == (9, "out", "err")
    gated, options = events[0]
    assert gated[-3:] == ["python", "-c", "fixed"]
    assert gated[gated.index("--entrypoint") + 1] == "/bin/sh"
    assert options["stdin"] == subprocess.PIPE
    assert events[1:] == ["verified", "go\n"]


def test_oneshot_reuses_helper_preserves_delivery_and_owned_cleanup(docker):
    from tests.test_spawner.test_box_bootstrap_docker import OneshotDocker

    name = boxes.run_id("delivery")
    oneshot = OneshotDocker(types.SimpleNamespace(), on_exec=lambda cmd, kw: (cmd, kw))
    run = ["docker", "run", "--detach", "--rm", "--name", name, "image"]
    result = oneshot(run, capture_output=True, text=True)
    assert "--cgroup-parent=testcpu.slice" in result.args
    assert "--rm" not in result.args
    execute = ["docker", "exec", "-i", "--user", "1:1", name, "writer"]
    docker.code = 4
    delivered = oneshot(execute, input=b"synthetic", capture_output=True)
    assert delivered.args == execute and delivered.returncode == 4
    assert oneshot.execs == [delivered] and oneshot.names == [name]
    oneshot.cleanup()
    assert docker.calls[-1][0] == ["docker", "rm", "-f", name]


@pytest.mark.parametrize("failure", ["membership", "timeout"])
def test_foreground_failed_proof_never_releases_payload_and_client_is_reaped(docker, monkeypatch, failure):
    events = []
    class Process:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def poll(self):
            return None
        def communicate(self, data=None, **kwargs):
            events.append(data)
            return "", ""
        def kill(self):
            events.append("kill")
    def query(cmd, **kw):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd, 120)
        return subprocess.CompletedProcess(cmd, 0, "true", "")
    def refuse(*args):
        raise placement.ContainerParentError("fixed refusal")
    monkeypatch.setattr(placement.subprocess, "Popen", Process)
    monkeypatch.setattr(placement.subprocess, "run", query)
    monkeypatch.setattr(placement.ContainerParent, "verify", refuse)
    expected = placement.ContainerParentError if failure == "membership" else subprocess.TimeoutExpired
    with pytest.raises(expected):
        placement.ContainerParent("testcpu.slice").run(
            ["docker", "run", "--name", "box", "--entrypoint", "python", "image"],
            text=True, capture_output=True, timeout=120)
    assert events == ["kill", None]


@pytest.mark.parametrize(("old", "new", "broken"), [
    ('row.get("parent") != self.slice', 'False', 'parent'),
    ('member.get("inside") is not True', 'False', 'inside'),
    ('member.get("parentOk") is not True', 'False', 'quota'),
    ('info.get("driver") != "systemd"', 'False', 'driver'),
    ('if endpoint not in {"unix:///var/run/docker.sock", "unix:///run/docker.sock"}:', 'if False:', 'endpoint'),
    ('builder["Driver"] != "docker"', 'False', 'builder'),
    ('if "--cgroup-parent" not in help_text:', 'if False:', 'flag'),
])
def test_each_removed_guard_is_caught_by_its_fixed_answer(monkeypatch, old, new, broken):
    """The negative assertion is run on correct AND deliberately broken code."""
    def check(module):
        fake = DockerTransport(monkeypatch, module)
        if broken == "parent":
            fake.row["parent"] = ""
        elif broken == "inside":
            fake.member["inside"] = False
        elif broken == "quota":
            fake.member["parentOk"] = False
        elif broken == "driver":
            fake.info["driver"] = "cgroupfs"
        elif broken == "endpoint":
            fake.endpoint = "ssh://remote"
        elif broken == "builder":
            fake.builder["Driver"] = "remote"
        else:
            fake.help = "no flag"
        try:
            if broken in {"parent", "inside", "quota"}:
                module.ContainerParent("testcpu.slice").verify("box")
            elif broken in {"builder", "flag"}:
                module.ContainerParent("testcpu.slice").build_command(["docker", "build", "-"])
            else:
                module.container_parent()
        except module.ContainerParentError:
            return
        raise AssertionError("accepted broken placement")
    check(placement)
    mutant = placement_mutation(monkeypatch, old, new)
    with pytest.raises(AssertionError, match="accepted broken placement"):
        check(mutant)


def placement_mutation(monkeypatch, old, new):
    source = Path(placement.__file__).read_text()
    assert source.count(old) == 1
    mutant = types.ModuleType("container_parent_mutant")
    monkeypatch.setitem(sys.modules, mutant.__name__, mutant)
    exec(compile(source.replace(old, new), "mutant", "exec"), mutant.__dict__)
    return mutant


@pytest.mark.parametrize("mode", ["absent", "installed-inactive", "installed-enabled"])
def test_offline_kill_accounting_is_hermetic_in_every_install_state(docker, monkeypatch, tmp_path, mode):
    from tests.test_spawner import test_box_refused_ending as refused

    if mode == "absent":
        monkeypatch.setattr(placement, "CLI", tmp_path / "absent-cli")
        monkeypatch.setattr(placement, "POLICY", tmp_path / "absent-policy")
    elif mode == "installed-inactive":
        docker.parent_code = 3
    original = refused.test_the_wrapper_counts_only_a_kill_of_that_box_docker_took
    with monkeypatch.context() as isolated:
        original(isolated)  # every original kill assertion runs, never a placement query
    assert docker.calls == []
    if mode != "absent":
        source = textwrap.dedent(inspect.getsource(original)).replace(
            'monkeypatch.setattr("tests.test_spawner.test_box_bootstrap_docker.run_test_docker", run)',
            'monkeypatch.setattr(subprocess, "run", run)')
        namespace = dict(vars(refused))
        exec(compile(source, "old-broad-subprocess-mock", "exec"), namespace)
        with monkeypatch.context() as isolated, pytest.raises(placement.ContainerParentError, match="parent refused"):
            namespace[original.__name__](isolated)


@pytest.mark.parametrize("builder", [None, [], "wrong", 7, {"Current": True, "Name": []},
    {"Current": True, "Name": "default", "Driver": "docker", "Nodes": "wrong"},
    {"Current": True, "Name": "default", "Driver": "docker", "Nodes": [None]},
    {"Current": True, "Name": "default", "Driver": "docker", "Nodes": [{"Endpoint": 1}]}])
def test_malformed_builder_shapes_have_placement_diagnostics(docker, builder):
    docker.builder = builder
    with pytest.raises(placement.ContainerParentError, match="unsupported test builder"):
        placement.run_test_docker(["docker", "build", "-"], input="RUN true", text=True)


@pytest.mark.parametrize("cmd", [
    ["docker", "run", "--name", "box", "--entrypoint", "python", "image"],
    ["docker", "run", "--detach", "--name", "box", "image"],
    ["docker", "exec", "-i", "--user", "1:1", "box", "writer"],
    ["docker", "build", "-"],
])
def test_policy_and_daemon_queries_share_the_original_deadline(docker, monkeypatch, cmd):
    observations = []
    original = docker.run
    def slow(cmd, **kw):
        observations.append((list(cmd), kw["timeout"]))
        docker.clock.advance(0.4, kw["timeout"], cmd)
        return original(cmd, **kw)
    monkeypatch.setattr(placement.subprocess, "run", slow)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        placement.run_test_docker(cmd, capture_output=True, timeout=1.0)
    assert caught.value.cmd == cmd and caught.value.timeout == 1.0
    assert (caught.value.output, caught.value.stderr) == (b"partial", b"query")
    assert docker.clock.now == pytest.approx(1.0)
    assert [timeout for _, timeout in observations] == pytest.approx([1.0, 0.6, 0.2])
    assert not any(c[1] in {"run", "exec", "build"} for c, _ in docker.calls)


@pytest.mark.parametrize("verb", ["exec", "build", "detached"])
def test_successful_discovery_leaves_only_remaining_payload_and_proof_time(docker, monkeypatch, verb):
    observations = []
    original = docker.run
    def timed(cmd, **kw):
        observations.append((list(cmd), docker.clock.now, kw["timeout"]))
        docker.clock.advance(0.1, kw["timeout"], cmd)
        return original(cmd, **kw)
    monkeypatch.setattr(placement.subprocess, "run", timed)
    cmd = {"exec": ["docker", "exec", "box", "writer"],
           "build": ["docker", "build", "-"],
           "detached": ["docker", "run", "--detach", "--name", "box", "image"]}[verb]
    placement.run_test_docker(cmd, capture_output=True, timeout=2.0)
    assert all(timeout == pytest.approx(2.0 - at) for _, at, timeout in observations)
    payloads = [row for row in observations if row[0][1] in {"run", "exec"}
                or row[0][1:3] == ["buildx", "build"] and "--help" not in row[0]]
    assert len(payloads) == 1 and payloads[0][2] < 2.0
    if verb == "detached":
        assert any(at > payloads[0][1] for _, at, _ in observations)  # post-create proof, same clock


def fake_foreground(monkeypatch, module, events, *, early_exit=None, exit_code=0):
    class Process:
        returncode = early_exit
        def __init__(self, cmd, **kwargs):
            events.append(("popen", cmd, kwargs))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def poll(self):
            return self.returncode
        def communicate(self, data=None, timeout=None):
            events.append(("communicate", data, timeout))
            if self.returncode is None:
                self.returncode = exit_code
            return "out", "err"
        def kill(self):
            events.append(("kill",))
            self.returncode = -9
    monkeypatch.setattr(module.subprocess, "Popen", Process)


def test_foreground_queries_do_not_each_receive_a_new_budget(monkeypatch):
    def fixed_answer(module):
        transport = DockerTransport(monkeypatch, module)
        transport.top = "PID\n101\n"
        events = []
        fake_foreground(monkeypatch, module, events)
        original = transport.run
        def timed(cmd, **kw):
            ready = cmd[1] == "inspect" and cmd[3] == "{{.State.Running}}"
            transport.clock.advance(0.1 if ready else 0.4, kw["timeout"], cmd)
            return subprocess.CompletedProcess(cmd, 0, "true", "") if ready else original(cmd, **kw)
        monkeypatch.setattr(module.subprocess, "run", timed)
        cmd = ["docker", "run", "--name", "box", "--entrypoint", "python", "image"]
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            module.ContainerParent("testcpu.slice").run(cmd, text=True, capture_output=True, timeout=1.0)
        assert caught.value.cmd == cmd and caught.value.timeout == 1.0
        assert events[-2:] == [("kill",), ("communicate", None, None)]
        assert not any(e[0] == "communicate" and e[1] is not None for e in events)
        assert transport.clock.now == pytest.approx(1.0), "verification renewed the budget"
    fixed_answer(placement)
    mutant = placement_mutation(monkeypatch,
        "result = (budget or CommandBudget(argv, None)).run(",
        "result = CommandBudget(argv, None).run(")
    with pytest.raises(AssertionError, match="verification renewed the budget"):
        fixed_answer(mutant)


@pytest.mark.parametrize("code", [0, 4])
def test_foreground_exit_before_proof_is_not_a_success_or_a_go(docker, monkeypatch, code):
    events = []
    fake_foreground(monkeypatch, placement, events, early_exit=code)
    cmd = ["docker", "run", "--name", "box", "--entrypoint", "python", "image"]
    if code == 0:
        with pytest.raises(placement.ContainerParentError, match="without membership proof"):
            placement.ContainerParent("testcpu.slice").run(cmd, text=True, capture_output=True, timeout=1)
    else:
        result = placement.ContainerParent("testcpu.slice").run(cmd, text=True, capture_output=True, timeout=1)
        assert (result.returncode, result.stdout, result.stderr) == (4, "out", "err")
    assert events[-1] == ("communicate", None, 1)
    assert docker.calls == []


def test_foreground_payload_gets_remaining_time_and_check_still_raises(docker, monkeypatch):
    events = []
    fake_foreground(monkeypatch, placement, events, exit_code=4)
    original = docker.run
    def timed(cmd, **kw):
        docker.clock.advance(0.1, kw["timeout"], cmd)
        if cmd[1] == "inspect" and cmd[3] == "{{.State.Running}}":
            return subprocess.CompletedProcess(cmd, 0, "true", "")
        return original(cmd, **kw)
    monkeypatch.setattr(placement.subprocess, "run", timed)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        placement.run_test_docker(
            ["docker", "run", "--name", "box", "--entrypoint", "python", "image"],
            text=True, capture_output=True, check=True, timeout=2.0)
    assert (caught.value.returncode, caught.value.stdout, caught.value.stderr) == (4, "out", "err")
    assert events[-1][:2] == ("communicate", "go\n")
    assert events[-1][2] == pytest.approx(2.0 - docker.clock.now)
    assert not any(e[0] == "kill" for e in events)


def test_verification_precedes_cancellation_and_real_spawner_revocation(monkeypatch):
    from temper_ai.spawner import box_bootstrap
    from temper_ai.spawner.docker_spawner import (
        DockerSpawner,
        SpawnerError,
        container_name,
    )
    from tests.test_spawner import test_box_bootstrap_docker as oneshot

    def fixed_answer(module):
        transport = DockerTransport(monkeypatch, module)
        monkeypatch.setattr(oneshot, "run_test_docker", module.run_test_docker)
        events, deliveries, armed = [], [], []
        eid = "fixed-cancel"
        name = container_name(eid)
        def cancel_soon(cmd, kw):
            events.append("callback")
            armed.append(transport.clock.now + 2.0)
            cmd[-1] = "tampered-writer-argument"
            return cmd, {**kw, "input": b"tampered-stdin"}
        wrapper = oneshot.OneshotDocker(install=None, on_exec=cancel_soon)
        original = transport.run
        def timed(cmd, **kw):
            if cmd[1] == "exec":
                events.append("exec")
                assert len(armed) == 1 and transport.clock.now == pytest.approx(armed[0] - 2.0)
                assert cmd[-1] == "tampered-writer-argument" and kw["input"] == b"tampered-stdin"
                transport.clock.advance(2.0, kw["timeout"], cmd)
                events.append("timer-kill")
                assert not wrapper.killed(name)  # timer/observer action is not a spawner kill
                return subprocess.CompletedProcess(cmd, 137, b"", b"")
            if cmd[1] == "kill":
                events.append("spawner-kill")
                return subprocess.CompletedProcess(cmd, 0, "", "")
            events.append("preflight")
            transport.clock.advance(0.4, kw["timeout"], cmd)
            if armed and transport.clock.now >= armed[0]:
                transport.row.update(running=False, pid=0)
            return original(cmd, **kw)
        monkeypatch.setattr(module.subprocess, "run", timed)
        monkeypatch.setattr(box_bootstrap, "envelope", lambda *a: bytearray(b"fixed-envelope"))
        harness = types.SimpleNamespace(_docker="docker", _run=wrapper, _docker_run=wrapper,
            _record_delivery=lambda eid, record, state: deliveries.append(state))
        doc = {"generation": 1, "bootstrap": {"deadlines": {"ready": 8, "ack": 30},
               "dir": "/synthetic", "leaf": "fixed", "max_bytes": 100}}
        with pytest.raises(SpawnerError, match="error: the writer gave no status.*delivery revoked"):
            DockerSpawner._deliver(harness, eid, doc, {"digest": "fixed"}, {}, "1:1", "python")
        assert events.count("preflight") * 0.4 > 2.0
        assert events[-4:] == ["callback", "exec", "timer-kill", "spawner-kill"]
        assert len(armed) == 1 and deliveries[0]["state"] == "revoked"
        assert wrapper.killed(name) and len(wrapper.execs) == 1
        oneshot._refused_ending(137, killed=wrapper.killed(name), said=False)
    fixed_answer(placement)
    mutant = placement_mutation(monkeypatch, "    parent = container_parent(budget)\n",
        "    if cmd[1] == 'exec' and before_exec is not None:\n"
        "        cmd, kwargs = before_exec(cmd, kwargs)\n"
        "        before_exec = None\n"
        "    parent = container_parent(budget)\n")
    with pytest.raises(mutant.ContainerParentError, match="not running"):
        fixed_answer(mutant)


@pytest.mark.parametrize("failure", ["membership", "callback-timeout", "callback-target"])
def test_exec_failure_cannot_arm_early_or_run_unverified_target(docker, monkeypatch, failure):
    calls = []
    def callback(cmd, kw):
        calls.append("callback")
        if failure == "callback-timeout":
            docker.clock.advance(2.0)
        else:
            cmd[2] = "other-container"
        return cmd, kw
    if failure == "membership":
        docker.member["inside"] = False
    error = subprocess.TimeoutExpired if failure == "callback-timeout" else placement.ContainerParentError
    with pytest.raises(error):
        placement.run_test_docker(["docker", "exec", "box", "writer"], before_exec=callback, timeout=1.0)
    assert calls == ([] if failure == "membership" else ["callback"])
    assert not any(c[1] == "exec" for c, _ in docker.calls)
