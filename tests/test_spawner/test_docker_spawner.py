"""DockerSpawner — the run container is the worker's, minus what a run must not have.

No docker here: a fake `run` records every docker invocation and answers
from a script. What is tested is the command the spawner builds and how
it reads docker's answers, which is the whole contract.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

import pytest

from temper_ai.spawner.base import SpawnerError
from temper_ai.spawner.docker_spawner import (
    DockerSpawner,
    Mount,
    Template,
    container_name,
    workspace_mounts,
)
from temper_ai.worker_proto import ProcessHandle, SpawnerKind

WORKSPACES = "/srv/temper/workspaces"


def _inspect_json(**overrides) -> str:
    """What `docker inspect <worker>` returns for a worker brought up with
    the compose file plus the host-docker overlay."""
    info = {
        "Config": {
            "Image": "temper-ai-worker",
            "Env": ["TEMPER_DATABASE_URL=postgresql://x", "OPENAI_API_KEY=sk-1", "PATH=/usr/bin"],
        },
        "HostConfig": {"ExtraHosts": ["host.docker.internal:host-gateway"]},
        "Mounts": [
            {"Type": "bind", "Source": "/src/temper_ai", "Destination": "/app/temper_ai", "RW": False},
            {"Type": "bind", "Source": "/src/configs", "Destination": "/app/configs", "RW": False},
            {"Type": "bind", "Source": "/home/u/.claude/.credentials.json",
             "Destination": "/home/temperai-worker/.claude/.credentials.json", "RW": False},
            {"Type": "bind", "Source": WORKSPACES, "Destination": WORKSPACES, "RW": True},
            {"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock", "RW": True},
            {"Type": "volume", "Name": "cache", "Source": "/var/lib/docker/volumes/cache", "Destination": "/cache", "RW": True},
        ],
        "NetworkSettings": {"Networks": {"temper-ai_default": {}}},
    }
    info.update(overrides)
    return json.dumps([info])


@dataclass
class FakeDocker:
    """Answers docker invocations from a per-subcommand script; records them all."""

    answers: dict[str, list[tuple[int, str, str]]] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, cmd, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(list(cmd))
        queue = self.answers.get(cmd[1], [])
        code, out, err = queue.pop(0) if queue else (0, "", "")
        return subprocess.CompletedProcess(cmd, code, stdout=out, stderr=err)

    def commands(self, sub: str) -> list[list[str]]:
        return [c for c in self.calls if c[1] == sub]


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspaces" / "run-a"
    ws.mkdir(parents=True)
    return ws


def _spawner(docker: FakeDocker, workspace_path: str | None, **kwargs) -> DockerSpawner:
    return DockerSpawner(
        template_container="worker-self",
        workspace_lookup=lambda _eid: workspace_path,
        run=docker,
        **kwargs,
    )


def _run_cmd(docker: FakeDocker) -> list[str]:
    (cmd,) = docker.commands("run")
    return cmd


def _mounts(cmd: list[str]) -> list[str]:
    return [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "--mount"]


def _envs(cmd: list[str]) -> list[str]:
    return [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "--env"]


# --- What the run container is -------------------------------------------

class TestRunContainer:
    def test_is_the_workers_image_env_and_network_running_the_run(self, workspace):
        docker = FakeDocker(answers={"inspect": [(0, _inspect_json(), "")], "run": [(0, "abc123\n", "")]})
        handle = _spawner(docker, str(workspace)).spawn("exec-1")

        cmd = _run_cmd(docker)
        assert cmd[:3] == ["docker", "run", "--detach"]
        assert "--rm" in cmd and "--init" in cmd
        assert cmd[cmd.index("--name") + 1] == "temper-run-exec-1"
        assert cmd[cmd.index("--hostname") + 1] == "temper-run-exec-1"
        assert cmd[cmd.index("--network") + 1] == "temper-ai_default"
        assert cmd[cmd.index("--add-host") + 1] == "host.docker.internal:host-gateway"
        assert "temper.execution_id=exec-1" in cmd
        assert cmd[cmd.index("--security-opt") + 1] == "no-new-privileges"
        # image, then the run command
        image_at = cmd.index("temper-ai-worker")
        assert cmd[image_at:] == [
            "temper-ai-worker",
            "uv", "run", "python", "-m", "temper_ai.cli.main", "run-workflow",
            "--execution-id", "exec-1",
        ]
        # env: everything the worker had, plus its own name
        assert set(_envs(cmd)) == {
            "TEMPER_DATABASE_URL=postgresql://x", "OPENAI_API_KEY=sk-1", "PATH=/usr/bin",
            "TEMPER_RUN_CONTAINER=temper-run-exec-1",
        }

        assert handle == ProcessHandle(
            kind=SpawnerKind.docker, handle="temper-run-exec-1",
            spawned_at=handle.spawned_at,
            metadata={"execution_id": "exec-1", "container_id": "abc123", "image": "temper-ai-worker"},
        )

    def test_never_gets_the_docker_socket(self, workspace):
        docker = FakeDocker(answers={"inspect": [(0, _inspect_json(), "")]})
        _spawner(docker, str(workspace)).spawn("exec-1")
        assert not any("docker.sock" in m for m in _mounts(_run_cmd(docker)))

    @pytest.mark.parametrize(
        "source, target",
        [
            # rootless docker: the host socket lives under the user's runtime dir
            ("/run/user/1000/docker.sock", "/var/run/docker.sock"),
            # a worker that reaches the daemon through a non-default path
            ("/var/run/docker.sock", "/run/host-docker.sock"),
        ],
    )
    def test_a_socket_mounted_at_a_different_path_is_still_the_socket(
        self, workspace, source, target,
    ):
        # The host-equivalent rule (source == target) happens to catch the
        # compose overlay's socket mount too; this is the case where only the
        # socket rule stands between the run and the host daemon.
        info = json.loads(_inspect_json())[0]
        info["Mounts"] = [
            m for m in info["Mounts"] if "docker.sock" not in m["Source"]
        ] + [{"Type": "bind", "Source": source, "Destination": target, "RW": True}]
        docker = FakeDocker(answers={"inspect": [(0, json.dumps([info]), "")]})
        _spawner(docker, str(workspace)).spawn("exec-1")
        assert not any("docker.sock" in m for m in _mounts(_run_cmd(docker)))

    def test_gets_only_its_own_workspace_not_the_whole_tree(self, workspace):
        docker = FakeDocker(answers={"inspect": [(0, _inspect_json(), "")]})
        _spawner(docker, str(workspace)).spawn("exec-1")
        mounts = _mounts(_run_cmd(docker))
        assert f"type=bind,source={workspace},target={workspace}" in mounts
        assert not any(f"source={WORKSPACES}," in m for m in mounts)

    def test_inherits_the_workers_read_only_mounts_as_read_only(self, workspace):
        docker = FakeDocker(answers={"inspect": [(0, _inspect_json(), "")]})
        _spawner(docker, str(workspace)).spawn("exec-1")
        mounts = _mounts(_run_cmd(docker))
        assert "type=bind,source=/src/temper_ai,target=/app/temper_ai,readonly" in mounts
        assert "type=bind,source=/src/configs,target=/app/configs,readonly" in mounts
        assert (
            "type=bind,source=/home/u/.claude/.credentials.json,"
            "target=/home/temperai-worker/.claude/.credentials.json,readonly"
        ) in mounts
        # named volumes are not bind mounts and are not carried over
        assert not any("/cache" in m for m in mounts)

    def test_a_run_without_a_workspace_gets_no_writable_host_path(self):
        docker = FakeDocker(answers={"inspect": [(0, _inspect_json(), "")]})
        _spawner(docker, "").spawn("exec-1")
        assert all(m.endswith(",readonly") for m in _mounts(_run_cmd(docker)))

    def test_image_override(self, workspace, monkeypatch):
        monkeypatch.setenv("TEMPER_DOCKER_IMAGE", "temper-ai-worker:pinned")
        docker = FakeDocker(answers={"inspect": [(0, _inspect_json(), "")]})
        handle = _spawner(docker, str(workspace)).spawn("exec-1")
        cmd = _run_cmd(docker)
        assert "temper-ai-worker:pinned" in cmd
        assert "temper-ai-worker" not in cmd
        assert handle.metadata["image"] == "temper-ai-worker:pinned"

    def test_resource_limits_from_env(self, workspace, monkeypatch):
        monkeypatch.setenv("TEMPER_DOCKER_MEMORY", "4g")
        monkeypatch.setenv("TEMPER_DOCKER_CPUS", "2")
        monkeypatch.setenv("TEMPER_DOCKER_PIDS_LIMIT", "512")
        docker = FakeDocker(answers={"inspect": [(0, _inspect_json(), "")]})
        _spawner(docker, str(workspace)).spawn("exec-1")
        cmd = _run_cmd(docker)
        assert cmd[cmd.index("--memory") + 1] == "4g"
        assert cmd[cmd.index("--cpus") + 1] == "2"
        assert cmd[cmd.index("--pids-limit") + 1] == "512"

    def test_the_template_is_read_once(self, workspace):
        docker = FakeDocker(answers={"inspect": [(0, _inspect_json(), "")]})
        spawner = _spawner(docker, str(workspace))
        spawner.spawn("exec-1")
        spawner.spawn("exec-2")
        assert len(docker.commands("inspect")) == 1
        assert len(docker.commands("run")) == 2


# --- The workspace mounts ---------------------------------------------------

class TestWorkspaceMounts:
    def test_plain_directory(self, workspace):
        assert workspace_mounts(str(workspace)) == [Mount(str(workspace), str(workspace), read_only=False)]

    def test_a_git_worktree_brings_its_main_repository(self, tmp_path):
        main = tmp_path / "repos" / "proj"
        (main / ".git" / "worktrees" / "feature").mkdir(parents=True)
        wt = main / "worktrees" / "feature"
        wt.mkdir(parents=True)
        (wt / ".git").write_text(f"gitdir: {main}/.git/worktrees/feature\n")

        mounts = workspace_mounts(str(wt))
        assert mounts == [
            Mount(str(wt), str(wt), read_only=False),
            Mount(str(main), str(main), read_only=False),
        ]

    def test_a_worktree_inside_its_main_repo_keeps_both_mounts(self, tmp_path):
        # The repos/<name>/worktrees/<wt> layout: the main repo's mount already
        # covers the worktree, and docker accepts the nested bind. Both stay
        # so the intent (this run's workspace, plus what git needs) is
        # visible in `docker inspect`.
        main = tmp_path / "proj"
        (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
        wt = main / "wt"
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt\n")
        mounts = workspace_mounts(str(wt))
        assert mounts[0] == Mount(str(wt), str(wt), read_only=False)
        assert Mount(str(main), str(main), read_only=False) in mounts

    def test_a_normal_git_checkout_is_just_itself(self, workspace):
        (workspace / ".git").mkdir()
        assert workspace_mounts(str(workspace)) == [Mount(str(workspace), str(workspace), read_only=False)]

    def test_a_missing_workspace_is_a_spawn_error_not_a_root_owned_directory(self, tmp_path):
        with pytest.raises(SpawnerError, match="is not a directory on this host"):
            workspace_mounts(str(tmp_path / "nope"))


# --- Liveness and kill ------------------------------------------------------

def _handle(eid: str = "exec-1") -> ProcessHandle:
    return ProcessHandle(kind=SpawnerKind.docker, handle="whatever", metadata={"execution_id": eid})


class TestLivenessAndKill:
    def test_is_alive_asks_docker_about_the_container_named_for_the_run(self):
        docker = FakeDocker(answers={"inspect": [(0, "true\n", ""), (0, "false\n", ""),
                                                 (1, "", "Error: No such object: temper-run-exec-1")]})
        spawner = _spawner(docker, None)
        assert spawner.is_alive(_handle()) is True
        assert spawner.is_alive(_handle()) is False   # exited (--rm not yet done)
        assert spawner.is_alive(_handle()) is False   # gone
        assert all(c[-1] == "temper-run-exec-1" for c in docker.commands("inspect"))

    def test_the_handle_column_is_not_trusted_for_the_name(self):
        """run-workflow used to overwrite spawner_handle with its PID; the
        reaper still finds the container from the execution_id."""
        docker = FakeDocker(answers={"inspect": [(0, "true\n", "")]})
        handle = ProcessHandle(kind=SpawnerKind.docker, handle="4242", metadata={"execution_id": "exec-9"})
        assert _spawner(docker, None).is_alive(handle) is True
        assert docker.commands("inspect")[0][-1] == "temper-run-exec-9"

    def test_kill_sends_term_then_kill(self):
        docker = FakeDocker()
        spawner = _spawner(docker, None)
        spawner.kill(_handle())
        spawner.kill(_handle(), force=True)
        assert docker.commands("kill") == [
            ["docker", "kill", "--signal", "TERM", "temper-run-exec-1"],
            ["docker", "kill", "--signal", "KILL", "temper-run-exec-1"],
        ]

    @pytest.mark.parametrize("stderr", [
        "Error response from daemon: No such container: temper-run-exec-1",
        "Error response from daemon: cannot kill container: temper-run-exec-1: container is not running",
    ])
    def test_kill_of_a_gone_container_is_not_an_error(self, stderr):
        docker = FakeDocker(answers={"kill": [(1, "", stderr)]})
        _spawner(docker, None).kill(_handle())  # no raise

    def test_kill_failing_for_another_reason_raises(self):
        docker = FakeDocker(answers={"kill": [(1, "", "permission denied while trying to connect to the Docker daemon")]})
        with pytest.raises(SpawnerError, match="permission denied"):
            _spawner(docker, None).kill(_handle())


# --- Failure modes ---------------------------------------------------------

class TestFailures:
    def test_no_socket_means_no_template_and_a_message_that_says_so(self, workspace):
        docker = FakeDocker(answers={"inspect": [(1, "", "Cannot connect to the Docker daemon at unix:///var/run/docker.sock")]})
        with pytest.raises(SpawnerError, match="docker-compose.host-docker.yml"):
            _spawner(docker, str(workspace)).spawn("exec-1")

    def test_docker_run_failure_is_a_spawn_error_with_stderr(self, workspace):
        docker = FakeDocker(answers={"inspect": [(0, _inspect_json(), "")],
                                     "run": [(125, "", "docker: invalid mount config")]})
        with pytest.raises(SpawnerError, match="exit 125.*invalid mount config"):
            _spawner(docker, str(workspace)).spawn("exec-1")

    def test_missing_row_is_a_spawn_error(self):
        docker = FakeDocker()
        with pytest.raises(SpawnerError, match="No WorkflowRun row"):
            _spawner(docker, None).spawn("exec-1")
        assert docker.calls == []

    def test_docker_binary_missing(self, workspace):
        def no_docker(cmd, **kwargs):
            raise FileNotFoundError("docker")
        spawner = DockerSpawner(template_container="w", workspace_lookup=lambda _e: str(workspace), run=no_docker)
        with pytest.raises(SpawnerError, match="not found on PATH"):
            spawner.spawn("exec-1")

    def test_a_handle_with_neither_execution_id_nor_run_name_is_rejected(self):
        bad = ProcessHandle(kind=SpawnerKind.docker, handle="4242", metadata={})
        with pytest.raises(SpawnerError, match="Cannot derive"):
            _spawner(FakeDocker(), None).is_alive(bad)


def test_container_name_is_derived_from_the_execution_id():
    assert container_name("abc") == "temper-run-abc"


def test_template_from_inspect_tolerates_missing_sections():
    t = Template.from_inspect({"Config": {"Image": "img"}})
    assert t == Template(image="img", env=[], mounts=[], networks=[], extra_hosts=[])
