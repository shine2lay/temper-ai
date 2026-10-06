"""DockerSpawner — the run container is the worker's, minus what a run must not have.

No docker here: a fake `run` records every docker invocation and answers
from a script. What is tested is the command the spawner builds and how
it reads docker's answers, which is the whole contract.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field

import pytest

from temper_ai.shared.box_env import BoxEnv, BoxEnvError
from temper_ai.spawner.base import SpawnerBusy, SpawnerError
from temper_ai.spawner.docker_spawner import (
    TEMPLATE_GRACE_SECONDS,
    DockerSpawner,
    Mount,
    Template,
    container_name,
    workspace_mounts,
)
from temper_ai.worker_proto import ProcessHandle, SpawnerKind

WORKSPACES = "/srv/temper/workspaces"

#: The box list these tests run with, unless a test passes its own.
LISTED = BoxEnv(names=frozenset({"TEMPER_DATABASE_URL", "OPENAI_API_KEY", "PATH", "GITHUB_APP_ID", "KEY"}),
                agent_tools=frozenset({"PATH"}))


@pytest.fixture(autouse=True)
def _box_env_list_mode(monkeypatch):
    monkeypatch.delenv("TEMPER_BOX_ENV", raising=False)


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
        **{"box_env": lambda: LISTED, **kwargs},
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
        # The image's healthcheck asks for the server's port: no run listens there.
        assert "--no-healthcheck" in cmd
        # image, then the run command
        image_at = cmd.index("temper-ai-worker")
        assert cmd[image_at:] == [
            "temper-ai-worker",
            "uv", "run", "python", "-m", "temper_ai.cli.main", "run-workflow",
            "--execution-id", "exec-1",
        ]
        # env: what the worker had that the box list names, plus its own name
        assert set(_envs(cmd)) == {
            "TEMPER_DATABASE_URL=postgresql://x", "OPENAI_API_KEY=sk-1", "PATH=/usr/bin",
            "TEMPER_RUN_CONTAINER=temper-run-exec-1",
        }

        assert handle == ProcessHandle(
            kind=SpawnerKind.docker, handle="temper-run-exec-1",
            spawned_at=handle.spawned_at,
            metadata={"execution_id": "exec-1", "container_id": "abc123", "image": "temper-ai-worker"},
        )

    def test_never_gets_the_github_app_s_key(self, workspace):
        # The server holds it (a run asks the server for short-lived tokens): a box's
        # shell can read the environment the box started with.
        env = ["PATH=/usr/bin", "GITHUB_APP_ID=1234", "GITHUB_APP_PRIVATE_KEY=-----BEGIN leak",
               "GITHUB_APP_WEBHOOK_SECRET=whsec", "GITHUB_APP_CLIENT_SECRET=cs"]
        info = json.loads(_inspect_json())[0]
        info["Config"]["Env"] = env
        docker = FakeDocker(answers={"inspect": [(0, json.dumps([info]), "")]})
        _spawner(docker, str(workspace)).spawn("exec-1")
        assert set(_envs(_run_cmd(docker))) == {
            "PATH=/usr/bin", "GITHUB_APP_ID=1234", "TEMPER_RUN_CONTAINER=temper-run-exec-1"}

    def test_github_app_s_key_stays_out_even_when_inheriting(self, workspace, monkeypatch):
        monkeypatch.setenv("TEMPER_BOX_ENV", "inherit")
        info = json.loads(_inspect_json())[0]
        info["Config"]["Env"] = ["PATH=/usr/bin", "GITHUB_APP_PRIVATE_KEY=-----BEGIN leak"]
        docker = FakeDocker(answers={"inspect": [(0, json.dumps([info]), "")]})
        _spawner(docker, str(workspace)).spawn("exec-1")
        assert not any(e.startswith("GITHUB_APP_PRIVATE_KEY=") for e in _envs(_run_cmd(docker)))

    @pytest.mark.parametrize("mode", ["list", "inherit"])
    def test_never_gets_the_pi_switch_or_box_config(self, workspace, monkeypatch, mode):
        # M4 SW-42: Pi steps never run in a run box, so neither name reaches one -- not from
        # the list (it can't hold them) and not when inheriting the worker's environment.
        monkeypatch.setenv("TEMPER_BOX_ENV", mode)
        info = json.loads(_inspect_json())[0]
        info["Config"]["Env"] = ["PATH=/usr/bin", "TEMPER_PI_AGENT=1",
                                 "TEMPER_PI_BOX_CONFIG=/home/x/pi/box.json"]
        docker = FakeDocker(answers={"inspect": [(0, json.dumps([info]), "")]})
        _spawner(docker, str(workspace)).spawn("exec-1")
        assert not any(e.startswith("TEMPER_PI_") for e in _envs(_run_cmd(docker)))

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

    def test_the_template_is_read_again_for_every_run(self, workspace):
        """A template container recreated with a new key or image passes it
        to the next run, without restarting the worker."""
        recreated = _inspect_json(Config={"Image": "temper-ai-server:new", "Env": ["KEY=new"]})
        docker = FakeDocker(answers={"inspect": [(0, _inspect_json(), ""), (0, recreated, "")]})
        spawner = _spawner(docker, str(workspace))
        spawner.spawn("exec-1")
        spawner.spawn("exec-2")
        assert len(docker.commands("inspect")) == 2
        first, second = docker.commands("run")
        assert "temper-ai-worker" in first
        assert "temper-ai-server:new" in second and "KEY=new" in _envs(second)

    def test_a_template_being_recreated_leaves_the_last_look_standing(self, workspace):
        gone = (1, "", "Error: No such object: worker-self")
        docker = FakeDocker(answers={"inspect": [(0, _inspect_json(), ""), gone]})
        spawner = _spawner(docker, str(workspace))
        spawner.spawn("exec-1")
        spawner.spawn("exec-2")
        first, second = docker.commands("run")
        assert first[first.index("temper-ai-worker"):][:1] == second[second.index("temper-ai-worker"):][:1]

    def test_with_no_look_yet_a_run_waits_for_the_template_then_fails(self, workspace):
        now = [1000.0]
        down = [(1, "", "Error: No such object: worker-self")] * 3
        docker = FakeDocker(answers={"inspect": list(down)})
        spawner = _spawner(docker, str(workspace), clock=lambda: now[0])
        with pytest.raises(SpawnerBusy):
            spawner.spawn("exec-1")
        now[0] += TEMPLATE_GRACE_SECONDS - 1
        with pytest.raises(SpawnerBusy):
            spawner.spawn("exec-1")
        now[0] += 2
        with pytest.raises(SpawnerError) as failed:
            spawner.spawn("exec-1")
        assert not isinstance(failed.value, SpawnerBusy)
        assert docker.commands("run") == []

    def test_the_run_command_can_be_the_template_images_own_python(self, workspace, monkeypatch):
        monkeypatch.setenv("TEMPER_DOCKER_RUN_COMMAND", ".venv/bin/python -m temper_ai.cli.main run-workflow")
        docker = FakeDocker(answers={"inspect": [(0, _inspect_json(), "")]})
        _spawner(docker, str(workspace)).spawn("exec-1")
        cmd = _run_cmd(docker)
        assert cmd[cmd.index("temper-ai-worker"):] == [
            "temper-ai-worker", ".venv/bin/python", "-m", "temper_ai.cli.main", "run-workflow",
            "--execution-id", "exec-1",
        ]

    def test_claude_home_is_a_writable_tmpfs_around_the_credentials(self, workspace):
        """Docker would make ~/.claude root-owned for the credentials file, and
        the Claude CLI could not save the sessions a node's next turn resumes."""
        docker = FakeDocker(answers={"inspect": [(0, _inspect_json(), "")]})
        _spawner(docker, str(workspace)).spawn("exec-1")
        cmd = _run_cmd(docker)
        tmpfs = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "--tmpfs"]
        assert tmpfs == ["/home/temperai-worker/.claude:mode=1777"]
        # before the credentials mount inside it, which must still be there
        creds = next(m for m in _mounts(cmd) if m.endswith(".credentials.json,readonly")
                     or ".credentials.json" in m)
        assert cmd.index("--tmpfs") < cmd.index(creds)


def _with_env(env: list[str]) -> str:
    info = json.loads(_inspect_json())[0]
    info["Config"]["Env"] = env
    return json.dumps([info])


SERVER_ENV = [
    "PATH=/usr/bin", "TEMPER_DATABASE_URL=postgresql://x", "OPENAI_API_KEY=sk-1",
    "SLACK_BOT_TOKEN=xoxb-fake", "TELEGRAM_BOT_TOKEN=tg-fake", "INTERNAL_API_TOKEN=it-fake",
    "TEMPER_RUN_CONTAINER=temper-ai-server-1",
]


class TestBoxEnvAllowList:
    """A box gets only the listed names: a new secret in .env stays out by default."""

    def test_an_unlisted_variable_never_reaches_docker_run(self, workspace, caplog):
        docker = FakeDocker(answers={"inspect": [(0, _with_env(SERVER_ENV), "")]})
        with caplog.at_level(logging.INFO, logger="temper_ai.spawner.docker_spawner"):
            _spawner(docker, str(workspace)).spawn("exec-1")
        names = {e.split("=", 1)[0] for e in _envs(_run_cmd(docker))}
        assert names == {"PATH", "TEMPER_DATABASE_URL", "OPENAI_API_KEY", "TEMPER_RUN_CONTAINER"}
        # The worker logs the NAMES it left out, never a value.
        line = next(r.getMessage() for r in caplog.records if "left out" in r.getMessage())
        assert "INTERNAL_API_TOKEN, SLACK_BOT_TOKEN, TELEGRAM_BOT_TOKEN" in line
        assert "fake" not in caplog.text

    def test_temper_run_container_is_always_its_own_name(self, workspace):
        empty = BoxEnv(names=frozenset(), agent_tools=frozenset())
        docker = FakeDocker(answers={"inspect": [(0, _with_env(SERVER_ENV), "")]})
        _spawner(docker, str(workspace), box_env=lambda: empty).spawn("exec-1")
        assert _envs(_run_cmd(docker)) == ["TEMPER_RUN_CONTAINER=temper-run-exec-1"]

    def test_the_list_is_read_again_for_every_run(self, workspace):
        lists = [LISTED, BoxEnv(names=frozenset({"SLACK_BOT_TOKEN"}), agent_tools=frozenset())]
        docker = FakeDocker(answers={"inspect": [(0, _with_env(SERVER_ENV), "")]})
        spawner = _spawner(docker, str(workspace), box_env=lambda: lists.pop(0))
        spawner.spawn("exec-1")
        spawner.spawn("exec-2")
        second = {e.split("=", 1)[0] for e in _envs(docker.commands("run")[1])}
        assert second == {"SLACK_BOT_TOKEN", "TEMPER_RUN_CONTAINER"}

    def test_a_broken_list_fails_the_spawn_loudly(self, workspace):
        def broken():
            raise BoxEnvError("configs/boxes/env.yaml: missing")

        docker = FakeDocker(answers={"inspect": [(0, _with_env(SERVER_ENV), "")]})
        with pytest.raises(SpawnerError, match="allow-list is broken"):
            _spawner(docker, str(workspace), box_env=broken).spawn("exec-1")
        assert docker.commands("run") == []

    def test_inherit_restores_the_old_copy_and_warns(self, workspace, monkeypatch, caplog):
        monkeypatch.setenv("TEMPER_BOX_ENV", "inherit")

        def never_read():
            raise AssertionError("inherit does not read the list")

        docker = FakeDocker(answers={"inspect": [(0, _with_env(SERVER_ENV), "")]})
        with caplog.at_level(logging.WARNING, logger="temper_ai.spawner.docker_spawner"):
            _spawner(docker, str(workspace), box_env=never_read).spawn("exec-1")
        envs = set(_envs(_run_cmd(docker)))
        assert envs == {
            "PATH=/usr/bin", "TEMPER_DATABASE_URL=postgresql://x", "OPENAI_API_KEY=sk-1",
            "SLACK_BOT_TOKEN=xoxb-fake", "TELEGRAM_BOT_TOKEN=tg-fake", "INTERNAL_API_TOKEN=it-fake",
            "TEMPER_BOX_ENV=inherit", "TEMPER_RUN_CONTAINER=temper-run-exec-1",
        }
        assert any(r.levelno == logging.WARNING and "inherit" in r.getMessage() for r in caplog.records)

    def test_a_mistyped_switch_keeps_the_list(self, workspace, monkeypatch):
        monkeypatch.setenv("TEMPER_BOX_ENV", "inherrit")
        docker = FakeDocker(answers={"inspect": [(0, _with_env(SERVER_ENV), "")]})
        _spawner(docker, str(workspace)).spawn("exec-1")
        assert not any(e.startswith("SLACK_BOT_TOKEN=") for e in _envs(_run_cmd(docker)))

    def test_the_real_spawner_reads_the_repo_list(self, workspace, monkeypatch):
        # No box_env passed: the default loader reads configs/boxes/env.yaml.
        monkeypatch.delenv("TEMPER_CONFIG_DIR", raising=False)
        docker = FakeDocker(answers={"inspect": [(0, _with_env(SERVER_ENV), "")]})
        DockerSpawner(template_container="worker-self", workspace_lookup=lambda _e: str(workspace),
                      run=docker).spawn("exec-1")
        names = {e.split("=", 1)[0] for e in _envs(_run_cmd(docker))}
        assert {"PATH", "TEMPER_DATABASE_URL", "TEMPER_RUN_CONTAINER"} <= names
        assert not {"SLACK_BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "INTERNAL_API_TOKEN"} & names


class TestAllWorkspaces:
    """TEMPER_DOCKER_WORKSPACES=all: runs see the whole workspaces tree, as
    runs inside the server always have (they share repos, readonly, ...)."""

    @staticmethod
    def _server_like(tmp_path) -> tuple[str, str]:
        host = tmp_path / "workspaces"
        (host / "repos").mkdir(parents=True)
        info = _inspect_json(Mounts=[
            {"Type": "bind", "Source": "/src/temper_ai", "Destination": "/app/temper_ai", "RW": False},
            {"Type": "bind", "Source": str(host), "Destination": "/app/workspaces", "RW": True},
            {"Type": "bind", "Source": str(host), "Destination": str(host), "RW": True},
            {"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock", "RW": True},
        ])
        return str(host), info

    def test_the_whole_tree_at_both_paths_and_no_socket(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEMPER_DOCKER_WORKSPACES", "all")
        host, info = self._server_like(tmp_path)
        docker = FakeDocker(answers={"inspect": [(0, info, "")]})
        _spawner(docker, f"{host}/repos").spawn("exec-1")
        mounts = _mounts(_run_cmd(docker))
        assert f"type=bind,source={host},target=/app/workspaces" in mounts
        assert f"type=bind,source={host},target={host}" in mounts
        assert not any("docker.sock" in m for m in mounts)
        # the run's own workspace is inside the tree: not mounted a second time
        assert not any(f"target={host}/repos" in m for m in mounts)

    def test_a_workspace_named_by_its_path_in_the_container_is_fine(self, tmp_path, monkeypatch):
        """Many runs name /app/workspaces itself, which is no host path."""
        monkeypatch.setenv("TEMPER_DOCKER_WORKSPACES", "all")
        _host, info = self._server_like(tmp_path)
        docker = FakeDocker(answers={"inspect": [(0, info, "")]})
        _spawner(docker, "/app/workspaces").spawn("exec-1")
        assert len(docker.commands("run")) == 1

    def test_own_is_the_default_and_keeps_runs_apart(self, tmp_path):
        host, info = self._server_like(tmp_path)
        run_ws = tmp_path / "workspaces" / "repos"
        docker = FakeDocker(answers={"inspect": [(0, info, "")]})
        _spawner(docker, str(run_ws)).spawn("exec-1")
        mounts = _mounts(_run_cmd(docker))
        assert f"type=bind,source={host},target={host}" not in mounts
        assert f"type=bind,source={run_ws},target={run_ws}" in mounts


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

    @pytest.mark.parametrize("stderr", [
        "error: no such object: temper-run-exec-1",               # docker 29's CLI (seen 2026-09-27)
        "Error: No such object: temper-run-exec-1",               # older CLIs
        "Error response from daemon: No such container: temper-run-exec-1",
    ])
    def test_a_removed_container_is_gone_in_every_docker_wording(self, stderr):
        """Docker 29 says it in lower case. Matched as written, the reaper could not tell a run
        whose box had died, and left it "running" for good (queue task 9's resume probe)."""
        docker = FakeDocker(answers={"inspect": [(1, "", stderr)]})
        assert _spawner(docker, None).is_alive(_handle()) is False

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
        "error response from daemon: no such container: temper-run-exec-1",
        "Error response from daemon: cannot kill container: temper-run-exec-1: container is not running",
    ])
    def test_kill_of_a_gone_container_is_not_an_error(self, stderr):
        docker = FakeDocker(answers={"kill": [(1, "", stderr)]})
        _spawner(docker, None).kill(_handle())  # no raise

    def test_a_docker_that_does_not_answer_is_not_a_dead_run(self):
        """The reaper must not bury a run because the daemon hiccupped."""
        docker = FakeDocker(answers={"inspect": [(1, "", "Cannot connect to the Docker daemon")]})
        with pytest.raises(SpawnerError, match="Cannot connect"):
            _spawner(docker, None).is_alive(_handle())

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


# -- Box profiles (BS1 model-free gate: G01 refusals, G10, G11, G12) --------------------------
#
# A production-shaped install on disk (tests/test_spawner/box_fixtures.py, synthetic secrets
# only) and a fake docker: nothing here starts a container or touches a service (G12). The
# real containers are in test_box_sealed_docker.py.

import os  # noqa: E402
from pathlib import Path  # noqa: E402

from temper_ai.spawner import box_launches, box_profile  # noqa: E402
from temper_ai.spawner import docker_spawner as ds  # noqa: E402
from temper_ai.spawner.box_profile import BoxProfileError  # noqa: E402
from temper_ai.spawner.box_seal import WorkerView  # noqa: E402
from tests.test_spawner.box_fixtures import (  # noqa: E402
    SYNTHETIC_MARK,
    Install,
    MemoryStore,
)

REPO = Path(__file__).resolve().parents[2]
REAL_CONFIGS = REPO / "configs"
SEALED_RUN = "/app/.venv/bin/python -m temper_ai.cli.main run-workflow"
BOX_LIST = BoxEnv(names=frozenset({"PATH", "HOME", "WORKSPACE_DIR", "TEMPER_DATABASE_URL"}),
                  agent_tools=frozenset({"PATH", "HOME", "WORKSPACE_DIR"}))
PROFILE_VARS = (box_profile.PROFILE_ENV, box_profile.DIGEST_ENV, box_profile.GENERATION_ENV)
#: The configs e8538ff4 changed after the source Security's design acceptance names. No
#: review pin decides anything (Security rm-963c1429): they are classified like any other.
E8538FF4 = (
    "configs/agents/brief_check.yaml", "configs/agents/brief_setup.yaml",
    "configs/agents/desk_final.yaml", "configs/agents/desk_setup.yaml",
    "configs/agents/signal_grade_assets/check_signal.py", "configs/agents/signal_grade_setup.yaml",
    "configs/workflows/desk_check.yaml", "configs/workflows/opportunity_brief.yaml",
    "configs/workflows/signal_harvest.yaml",
)
CURRENT = box_launches.classify_all(box_launches.ConfigIndex.of(box_launches.FsTree(REAL_CONFIGS)))


def _masters_run_command(spawner: DockerSpawner, execution_id: str, workspace_path: str,
                         template: Template) -> list[str]:
    """master 65f908a3's DockerSpawner.run_command, kept verbatim: the launch before BS1."""
    name = container_name(execution_id)
    cmd = [
        "docker", "run", "--detach", "--rm", "--init",
        "--name", name, "--hostname", name,
        "--label", "temper.role=run",
        "--label", f"temper.execution_id={execution_id}",
        "--security-opt", "no-new-privileges",
        "--no-healthcheck",
    ]
    for network in template.networks[:1]:
        cmd += ["--network", network]
    for host in template.extra_hosts:
        cmd += ["--add-host", host]
    env = spawner.env_split(template)
    for var in env.kept:
        cmd += ["--env", var]
    cmd += ["--env", f"TEMPER_RUN_CONTAINER={name}"]
    all_workspaces = ds._all_workspaces()
    inherited = [m for m in template.mounts if ds._passes_through(m, all_workspaces)]
    for home in ds._claude_homes(inherited):
        cmd += ["--tmpfs", f"{home}:mode=1777"]
    for mount in inherited:
        cmd += ["--mount", mount.to_arg()]
    if workspace_path:
        for mount in workspace_mounts(workspace_path, covered=inherited):
            cmd += ["--mount", mount.to_arg()]
    cmd += spawner._resource_limits()
    cmd.append(template.image)
    cmd += [*ds._run_command(), "--execution-id", execution_id]
    return cmd


def _without_profile(cmd: list[str]) -> list[str]:
    out: list[str] = []
    for part in cmd:
        if part.split("=", 1)[0] in PROFILE_VARS:
            out.pop()  # its --env
            continue
        out.append(part)
    return out


@pytest.fixture
def install(tmp_path) -> Install:
    return Install(tmp_path / "host", user=f"{os.getuid() or 1000}:{os.getgid() or 1000}").build()


@pytest.fixture
def real_configs(install) -> Install:
    """The synthetic install, but with this checkout's own configs at /app/configs."""
    install.configs = REAL_CONFIGS
    return install


def _box_spawner(install: Install, store: MemoryStore, docker: FakeDocker, **kwargs) -> DockerSpawner:
    docker.answers.setdefault("inspect", []).extend([(0, install.inspect(), "")] * 4)
    docker.answers.setdefault("run", []).append((0, "cid-1\n", ""))
    kwargs.setdefault("engine_launches", install.engine_table())
    return DockerSpawner(
        template_container="worker-self",
        workspace_lookup=lambda eid: store.rows[eid]["workspace"],
        run=docker, box_env=lambda: BOX_LIST, profile_store=store,
        worker_view=WorkerView(None), **kwargs,
    )


def _sealed(monkeypatch) -> None:
    monkeypatch.setenv(box_profile.BOUNDARY_ENV, "sealed")
    monkeypatch.setenv("TEMPER_DOCKER_RUN_COMMAND", SEALED_RUN)


@pytest.mark.parametrize("launch", CURRENT, ids=[launch.workflow for launch in CURRENT])
def test_g11_replay_of_every_current_launch(launch, real_configs, monkeypatch):
    """Legacy: master's command plus the profile, byte for byte. Sealed: its class decides."""
    for name in (box_profile.BOUNDARY_ENV, "TEMPER_DOCKER_RUN_COMMAND", "TEMPER_DOCKER_WORKSPACES"):
        monkeypatch.delenv(name, raising=False)
    store = MemoryStore()
    store.add("legacy-1", workflow=launch.workflow, workspace=str(real_configs.run_a))
    docker = FakeDocker()
    spawner = _box_spawner(real_configs, store, docker)
    handle = spawner.spawn("legacy-1")
    run = docker.commands("run")[-1]
    assert _without_profile(run) == _masters_run_command(
        spawner, "legacy-1", str(real_configs.run_a), spawner.template())
    record = handle.metadata["box_profile"]
    assert record == store.record("legacy-1")
    doc = record["doc"]
    assert doc["boundary"] == "legacy" and doc["hardening"] == "partial"
    assert {r["step"] for r in doc["residuals"]} >= {"BS1", "BS2", "BS3", "BS4", "BS5", "BS6",
                                                      "network"}
    bs1 = next(r for r in doc["residuals"] if r["step"] == "BS1")
    assert "keys" in json.dumps(bs1) and "main repo copy" in json.dumps(bs1)
    assert doc["closure"]["network"] == "negative"
    assert SYNTHETIC_MARK not in json.dumps(record)

    _sealed(monkeypatch)
    store.add("sealed-1", workflow=launch.workflow, workspace=str(real_configs.run_b))
    docker = FakeDocker()
    spawner = _box_spawner(real_configs, store, docker)
    if launch.boundary == box_launches.SEALED:
        spawner.spawn("sealed-1")
        doc = store.record("sealed-1")["doc"]
        assert doc["boundary"] == "sealed" and doc["launch"]["digest"] == launch.digest
        assert doc["launch"]["files"] == dict(launch.files)
        assert doc["launch"]["label"] == box_launches.LABEL and "review" not in doc
        assert doc["label"].startswith("sealed (BS1-partial): gate-classified")
    else:
        with pytest.raises(BoxProfileError) as caught:
            spawner.spawn("sealed-1")
        assert launch.workflow in str(caught.value) and launch.reasons
        assert all(reason in str(caught.value) for reason in launch.reasons)
        assert docker.commands("run") == [], "refused before any box started"
        assert "box_profile" not in store.rows["sealed-1"]["metadata"]


def test_g11_e8538ff4s_changed_launches_are_classified_by_the_rules_like_any_other():
    """No review pin: each launch's class comes from the landed rules and its files now."""
    touched = [launch for launch in CURRENT if set(launch.files) & set(E8538FF4)]
    assert {launch.workflow for launch in touched} >= {"desk_check", "opportunity_brief",
                                                       "signal_harvest"}
    index = box_launches.ConfigIndex.of(box_launches.FsTree(REAL_CONFIGS))
    for launch in touched:
        assert box_launches.classify(index, launch.workflow) == launch  # same rules, same class
        record = launch.as_dict()
        assert record["label"] == box_launches.LABEL and "review" not in record
        assert record["classified_by"] == box_launches.GENERATOR
        assert (launch.boundary == box_launches.SEALED) == (not launch.reasons)


def test_g11_every_current_launch_is_classified_with_reasons():
    """Every workflow at this master has a class; only a launch with no reason runs sealed."""
    assert len(CURRENT) == len(box_launches.ConfigIndex.of(
        box_launches.FsTree(REAL_CONFIGS)).by_kind["workflow"])
    for launch in CURRENT:
        assert launch.boundary in (box_launches.SEALED, box_launches.LEGACY, box_launches.REFUSED)
        if launch.boundary == box_launches.SEALED:
            assert not launch.reasons and launch.digest and launch.files and launch.allowed
        else:
            assert launch.reasons, launch.workflow


def test_a_legacy_box_starts_as_before_when_its_profile_cant_be_kept(install, monkeypatch):
    monkeypatch.delenv(box_profile.BOUNDARY_ENV, raising=False)

    class Broken(MemoryStore):
        def save(self, *args, **kwargs):
            raise BoxProfileError("the database is away")

    store = Broken()
    store.add("legacy-2", workspace=str(install.run_a))
    docker = FakeDocker()
    spawner = _box_spawner(install, store, docker)
    handle = spawner.spawn("legacy-2")
    assert docker.commands("run")[-1] == _masters_run_command(
        spawner, "legacy-2", str(install.run_a), spawner.template())
    assert "box_profile" not in handle.metadata


def test_a_run_that_had_a_sealed_box_never_gets_a_legacy_one(install, monkeypatch):
    _sealed(monkeypatch)
    store = MemoryStore()
    store.add("once-sealed", workflow="sealed_probe", workspace=str(install.run_a))
    _box_spawner(install, store, FakeDocker()).spawn("once-sealed")
    assert store.record("once-sealed")["generation"] == 1

    monkeypatch.setenv(box_profile.BOUNDARY_ENV, "legacy")  # a rollback: never for this run
    docker = FakeDocker()
    with pytest.raises(BoxProfileError, match="sealed"):
        _box_spawner(install, store, docker).spawn("once-sealed")
    assert docker.commands("run") == []

    _sealed(monkeypatch)  # a resume or replacement box: the next generation, sealed again
    _box_spawner(install, store, FakeDocker()).spawn("once-sealed")
    record = store.record("once-sealed")
    assert record["generation"] == 2 and record["doc"]["generation"] == 2
    assert [h["generation"] for h in record["history"]] == [1]


def _refused_before_docker(install: Install, workspace: str, *expect: str,
                           store: MemoryStore | None = None, **kwargs) -> None:
    store = store or MemoryStore()
    store.add("unsafe-1", workflow="sealed_probe", workspace=workspace)
    docker = FakeDocker()
    spawner = _box_spawner(install, store, docker, **kwargs)
    with pytest.raises(BoxProfileError) as caught:
        spawner.spawn("unsafe-1")
    for text in expect:
        assert text in str(caught.value), str(caught.value)
    assert docker.commands("run") == []
    assert "box_profile" not in store.rows["unsafe-1"]["metadata"]


@pytest.mark.parametrize(("variable", "value", "expect"), [
    ("TEMPER_BOX_ENV", "inherit", "inherit"),
    ("TEMPER_DOCKER_WORKSPACES", "all", "TEMPER_DOCKER_WORKSPACES"),
    ("TEMPER_DOCKER_IMAGE", "someone/else:latest", "TEMPER_DOCKER_IMAGE"),
    ("TEMPER_DOCKER_RUN_COMMAND", "uv run temper run-workflow", "uv run"),
    ("TEMPER_BOX_CAPABILITIES", "broker", "TEMPER_BOX_CAPABILITIES"),
    (box_profile.BOUNDARY_ENV, "sealed-ish", box_profile.BOUNDARY_ENV),
])
def test_an_unsafe_combination_is_refused_before_any_box(install, monkeypatch, variable, value,
                                                         expect):
    _sealed(monkeypatch)
    monkeypatch.setenv(variable, value)
    _refused_before_docker(install, str(install.run_a), expect)


def test_a_root_template_is_refused(install, monkeypatch):
    _sealed(monkeypatch)
    install.user = "root"
    _refused_before_docker(install, str(install.run_a), "unprivileged")


@pytest.mark.parametrize("where", ["alias", "whole tree", "outside", "link"])
def test_a_workspace_that_is_not_one_runs_own_folder_is_refused(install, monkeypatch, where):
    _sealed(monkeypatch)
    path = {
        "alias": "/app/workspaces/run-a",
        "whole tree": str(install.workspaces),
        "outside": str(install.repo),
        "link": str(install.workspaces / "run-c"),
    }[where]
    if where == "link":
        (install.workspaces / "run-c").symlink_to(install.run_b)
    _refused_before_docker(install, path)


def test_a_workspace_holding_another_runs_folder_is_refused(install, monkeypatch):
    _sealed(monkeypatch)
    store = MemoryStore()
    nested = install.run_a / "inner"
    nested.mkdir()
    store.add("other-run", workspace=str(nested), status="running")
    _refused_before_docker(install, str(install.run_a), "other-run", store=store)


def test_a_git_worktree_of_an_outside_repository_is_refused(install, monkeypatch):
    _sealed(monkeypatch)
    (install.run_a / ".git").write_text(f"gitdir: {install.repo}/.git/worktrees/run-a\n")
    _refused_before_docker(install, str(install.run_a), "outside")


@pytest.mark.parametrize("target", ["/app/standee-ssh", "/app/repo", "/app/workspaces",
                                    "/var/run/docker.sock", "/app/nowhere"])
def test_declared_data_that_is_not_data_is_refused(install, monkeypatch, target):
    _sealed(monkeypatch)
    (install.configs / "boxes" / "data.yaml").write_text(f"data:\n  sealed_probe: [{target}]\n")
    _refused_before_docker(install, str(install.run_a))


def test_every_box_classifies_its_launch_again_and_never_downgrades(install, monkeypatch):
    """Start, resume, replacement, takeover: each box's class comes from the files then."""
    _sealed(monkeypatch)
    store = MemoryStore()
    store.add("again-1", workflow="sealed_probe", workspace=str(install.run_a))
    _box_spawner(install, store, FakeDocker()).spawn("again-1")
    first = store.record("again-1")["doc"]["launch"]
    agent = install.configs / "agents" / "sealed_probe.yaml"
    agent.write_text(agent.read_text().replace("echo probe", "echo changed"))
    _box_spawner(install, store, FakeDocker()).spawn("again-1")  # still sealed: a new digest
    second = store.record("again-1")["doc"]["launch"]
    assert store.record("again-1")["generation"] == 2 and second["digest"] != first["digest"]
    path = "configs/agents/sealed_probe.yaml"
    assert second["files"][path] != first["files"][path]
    agent.write_text(agent.read_text().replace("echo changed", "cat /app/repo/.env"))
    docker = FakeDocker()  # now it needs a legacy box: refused, never given one
    with pytest.raises(BoxProfileError, match="classified legacy") as caught:
        _box_spawner(install, store, docker).spawn("again-1")
    assert "main repo copy" in str(caught.value)
    assert docker.commands("run") == [] and store.record("again-1")["generation"] == 2


def test_a_launch_chosen_at_run_time_is_refused(install, monkeypatch):
    _sealed(monkeypatch)
    (install.configs / "agents" / "sealed_probe.yaml").write_text(
        "agent:\n  name: sealed_probe\n  type: llm\n  provider: claude\n  tools: [Delegate]\n")
    _refused_before_docker(install, str(install.run_a), "classified refused", "Delegate",
                           "only known while the run goes")


@pytest.mark.parametrize(("where", "site"), [
    ("code", "temper_ai/sneaky.py::run"),
    ("local", "local/providers/sneaky.py::run"),
])
def test_code_that_starts_programs_from_an_unclassified_place_never_runs_sealed(
        install, monkeypatch, where, site):
    """Security rm-963c1429 condition 1: engine launch paths the gate hasn't classified."""
    _sealed(monkeypatch)
    table = install.engine_table()
    folder = install.code if where == "code" else install.local / "providers"
    (folder / "sneaky.py").write_text("import os\n\n\ndef run():\n    os.system('id')\n")
    (install.local / "standee-ssh" / "not_mounted.py").write_text("import os\nos.system('id')\n")
    _refused_before_docker(install, str(install.run_a), "hasn't classified", site,
                           engine_launches=table)
    store = MemoryStore()
    store.add("engine-1", workflow="sealed_probe", workspace=str(install.run_a))
    _box_spawner(install, store, FakeDocker(), engine_launches={**table, site: "box: test"}
                 ).spawn("engine-1")  # classified: it runs; the unmounted file never counted
    engine = store.record("engine-1")["doc"]["launch"]["engine"]
    assert engine["sites"] == len(table) + 1 and engine["rules"] == box_launches.GENERATOR


def test_code_baked_into_the_image_is_refused(install, monkeypatch):
    """The worker can't look for launch sites in an image's code: a sealed box runs bound code."""
    _sealed(monkeypatch)
    original = install.mounts
    monkeypatch.setattr(install, "mounts", lambda: [m for m in original()
                                                    if m["Destination"] != "/app/temper_ai"])
    _refused_before_docker(install, str(install.run_a), "can't look for the places")


@pytest.mark.parametrize(("default", "expect"), [
    (None, "chosen at run time"),
    ("openai", "isn't classified"),
    ("claude", None),
])
def test_agents_without_a_provider_run_sealed_only_on_a_pinned_default(install, monkeypatch,
                                                                      default, expect):
    _sealed(monkeypatch)
    (install.configs / "agents" / "sealed_probe.yaml").write_text(
        "agent:\n  name: sealed_probe\n  type: llm\n  system_prompt: hi\n")
    if default:
        install.extra_env.append(f"TEMPER_DEFAULT_PROVIDER={default}")
    if expect:
        _refused_before_docker(install, str(install.run_a), expect)
        return
    store = MemoryStore()
    store.add("default-1", workflow="sealed_probe", workspace=str(install.run_a))
    docker = FakeDocker()
    _box_spawner(install, store, docker).spawn("default-1")
    assert "TEMPER_DEFAULT_PROVIDER=claude" in docker.commands("run")[-1]
    launch = store.record("default-1")["doc"]["launch"]
    assert launch["allowed"]["providers"] == ["claude"] and launch["default_provider"] == "claude"


def test_the_subprocess_spawner_is_refused_under_sealed(monkeypatch):
    from temper_ai.spawner.subprocess_spawner import SubprocessSpawner

    monkeypatch.setenv(box_profile.BOUNDARY_ENV, "sealed")
    with pytest.raises(BoxProfileError, match="subprocess spawner"):
        SubprocessSpawner().spawn("any-run")


@pytest.mark.parametrize("boundary", ["sealed", "legacy", None])
def test_unboxed_starts_are_refused_only_under_sealed(monkeypatch, boundary):
    """The server's own process and the subprocess spawner call this before they run anything."""
    if boundary is None:
        monkeypatch.delenv(box_profile.BOUNDARY_ENV, raising=False)
    else:
        monkeypatch.setenv(box_profile.BOUNDARY_ENV, boundary)
    if boundary == "sealed":
        with pytest.raises(BoxProfileError, match="the server's own process has no box"):
            box_profile.refuse_unboxed_under_sealed("the server's own process")
    else:
        box_profile.refuse_unboxed_under_sealed("the server's own process")


# --- Box secrets BS2: the one-shot delivery (TEMPER_BOX_SECRET_BOOTSTRAP=oneshot) -------------
# The worker's side with a fake docker: what the box's command carries, what is delivered,
# and how a failed delivery ends. The runner's side is test_box_bootstrap.py; real boxes
# are test_box_bootstrap_docker.py.

from temper_ai.spawner import box_bootstrap  # noqa: E402

PROXY_WITH_PASSWORD = f"http://user:{SYNTHETIC_MARK}@proxy.synthetic:3128"
#: A box list with a secret-named value, a URL with a password named like a tool setting,
#: and plain tool settings.
ONESHOT_LIST = BoxEnv(
    names=frozenset({"PATH", "HOME", "WORKSPACE_DIR", "TEMPER_DATABASE_URL",
                     "SYNTH_SERVICE_TOKEN", "HTTPS_PROXY", "TEMPER_API"}),
    agent_tools=frozenset({"PATH", "HOME", "WORKSPACE_DIR", "HTTPS_PROXY", "TEMPER_API"}))
BAKED = ["PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
         "GPG_KEY=7169605F62C751356D054A26A821E680E5FA6305", "PYTHON_VERSION=3.12.15"]
CONSUMED = '{"state": "consumed", "names": 3, "generation": 1}\n'


@dataclass
class DeliveringDocker(FakeDocker):
    """The fake docker, also keeping what the writer was handed on stdin."""

    handed: list = field(default_factory=list)
    copies: list[bytes] = field(default_factory=list)

    def __call__(self, cmd, **kwargs) -> subprocess.CompletedProcess:
        if "input" in kwargs:
            self.handed.append(kwargs["input"])
            self.copies.append(bytes(kwargs["input"]))
        return super().__call__(cmd, **kwargs)


def _oneshot(monkeypatch) -> None:
    _sealed(monkeypatch)
    monkeypatch.setenv(box_profile.BOOTSTRAP_ENV, box_bootstrap.ONESHOT)


def _oneshot_spawner(install: Install, store: MemoryStore, docker: FakeDocker, *,
                     baked: list[str] | None = None, writer: str | None = CONSUMED,
                     **kwargs) -> DockerSpawner:
    install.extra_env += [f"HTTPS_PROXY={PROXY_WITH_PASSWORD}", "TEMPER_API=http://server:8420"]
    docker.answers.setdefault("inspect", []).extend([(0, install.inspect(), "")] * 4)
    docker.answers.setdefault("run", []).append((0, "cid-1\n", ""))
    docker.answers.setdefault("image", []).append((0, json.dumps(BAKED if baked is None
                                                                 else baked), ""))
    if writer is not None:
        docker.answers.setdefault("exec", []).append((0, writer, ""))
    kwargs.setdefault("engine_launches", install.engine_table())
    return DockerSpawner(
        template_container="worker-self",
        workspace_lookup=lambda eid: store.rows[eid]["workspace"],
        run=docker, box_env=lambda: ONESHOT_LIST, profile_store=store,
        worker_view=WorkerView(None), **kwargs,
    )


def _flag(cmd: list[str], flag: str) -> list[str]:
    return [cmd[i + 1] for i, part in enumerate(cmd) if part == flag]


def test_oneshot_needs_bs1s_sealed_profile(install, monkeypatch):
    monkeypatch.delenv(box_profile.BOUNDARY_ENV, raising=False)
    monkeypatch.setenv(box_profile.BOOTSTRAP_ENV, box_bootstrap.ONESHOT)
    store = MemoryStore()
    store.add("oneshot-legacy", workflow="sealed_probe", workspace=str(install.run_a))
    docker = DeliveringDocker()
    with pytest.raises(BoxProfileError, match="needs BS1's sealed profile"):
        _oneshot_spawner(install, store, docker).spawn("oneshot-legacy")
    assert docker.commands("run") == [] and docker.commands("exec") == []


def test_a_oneshot_box_starts_with_no_secret_and_takes_them_once(install, monkeypatch):
    _oneshot(monkeypatch)
    store = MemoryStore()
    store.add("oneshot-1", workflow="sealed_probe", workspace=str(install.run_a))
    docker = DeliveringDocker()
    handle = _oneshot_spawner(install, store, docker).spawn("oneshot-1")

    (run,) = docker.commands("run")
    assert not any(SYNTHETIC_MARK in part for part in run)
    names = {var.split("=", 1)[0] for var in _flag(run, "--env")}
    assert {"TEMPER_DATABASE_URL", "SYNTH_SERVICE_TOKEN", "HTTPS_PROXY"}.isdisjoint(names)
    assert {"PATH", "HOME", "TEMPER_API", *PROFILE_VARS} <= names
    assert "--init" in run and "--no-healthcheck" in run and "--read-only" in run
    uid, gid = install.user.split(":")
    assert (f"{box_bootstrap.BOOT_DIR}:rw,noexec,nosuid,nodev," in _flag(run, "--tmpfs")[-1]
            and _flag(run, "--tmpfs")[-1].endswith(f",mode=0700,uid={uid},gid={gid}"))

    (exec_,) = docker.commands("exec")
    assert exec_[:6] == ["docker", "exec", "-i", "--user", install.user, "temper-run-oneshot-1"]
    assert exec_[7:11] == ["-I", "-S", "-c", ds.WRITER_PROGRAM]
    assert not any(SYNTHETIC_MARK in part for part in exec_)
    (sent,) = docker.copies
    header = box_bootstrap.header_of(sent)
    assert header["execution_id"] == "oneshot-1" and header["generation"] == 1
    assert header["names"] == ["HTTPS_PROXY", "SYNTH_SERVICE_TOKEN", "TEMPER_DATABASE_URL"]
    assert SYNTHETIC_MARK.encode() in sent[box_bootstrap.HEADER_BYTES:]
    assert set(docker.handed[0]) == {0}, "the worker's copy is zeroed once sent"

    record = handle.metadata["box_profile"]
    assert record == store.record("oneshot-1")
    assert SYNTHETIC_MARK not in json.dumps(record)
    doc = record["doc"]
    assert doc["bootstrap"]["mode"] == box_bootstrap.ONESHOT
    assert doc["bootstrap"]["names"] == header["names"]
    assert doc["label"] == box_profile.SEALED_ONESHOT_LABEL
    assert doc["runtime"]["writer"] == ds.WRITER_DIGEST
    assert box_bootstrap.tmpfs_spec(doc["bootstrap"]) in doc["tmpfs"]
    still = {r["step"]: r["still"] for r in doc["residuals"]}
    assert still["BS2"] == "partial" and "cli credential" in still
    assert (record["delivery"]["state"], record["delivery"]["names"]) == ("consumed", 3)
    assert docker.commands("kill") == []


@pytest.mark.parametrize(("answer", "state"), [
    ((0, '{"state": "refused", "reason": "wrong envelope: it is for another run"}', ""),
     "refused: wrong envelope: it is for another run"),
    ((0, '{"state": "timeout", "reason": "timeout: no acknowledgement within 30s"}', ""),
     "timeout: timeout: no acknowledgement within 30s"),
    ((1, "", "Error response from daemon: container is not running"),
     "error: the writer gave no status (exit 1; docker said: Error response from daemon"),
    (subprocess.TimeoutExpired(["docker"], 120), "timeout: the writer did not finish in time"),
], ids=["refused", "no ack", "box gone", "exec hangs"])
def test_a_failed_delivery_stops_the_box_and_is_revoked(install, monkeypatch, answer, state):
    _oneshot(monkeypatch)
    store = MemoryStore()
    store.add("oneshot-2", workflow="sealed_probe", workspace=str(install.run_a))
    docker = DeliveringDocker()
    if isinstance(answer, Exception):
        spawner = _oneshot_spawner(install, store, docker, writer=None)
        original = docker.__call__

        def hanging(cmd, **kwargs):
            if cmd[1] == "exec":
                docker.handed.append(kwargs["input"])
                raise answer
            return original(cmd, **kwargs)

        spawner._run = hanging
    else:
        spawner = _oneshot_spawner(install, store, docker, writer=None)
        docker.answers["exec"] = [answer]
    with pytest.raises(SpawnerError) as caught:
        spawner.spawn("oneshot-2")
    message = str(caught.value)
    assert f"one-shot secret delivery failed ({state}" in message, message
    assert "the box was stopped and the delivery revoked" in message
    assert SYNTHETIC_MARK not in message
    assert docker.commands("kill") == [["docker", "kill", "temper-run-oneshot-2"]]
    delivery = store.record("oneshot-2")["delivery"]
    assert delivery["state"] == "revoked" and delivery["why"].startswith(state.split(":")[0])
    assert SYNTHETIC_MARK not in json.dumps(store.record("oneshot-2"))
    assert all(set(handed) == {0} for handed in docker.handed)


@pytest.mark.parametrize(("baked", "expect"), [
    ([*BAKED, "SOME_SERVICE_TOKEN=synthetic"], "bakes variables named or valued like secrets"),
    ([*BAKED, f"SOME_URL=postgresql://u:{SYNTHETIC_MARK}@db/x"], "SOME_URL"),
    (["GPG_KEY=not-a-fingerprint"], "GPG_KEY"),
    ("not a list", "can't be inspected for the variables it bakes in"),
], ids=["token", "password url", "odd gpg key", "uninspectable"])
def test_an_image_that_bakes_secrets_is_refused_for_oneshot(install, monkeypatch, baked, expect):
    _oneshot(monkeypatch)
    store = MemoryStore()
    store.add("unsafe-1", workflow="sealed_probe", workspace=str(install.run_a))
    docker = DeliveringDocker()
    spawner = _oneshot_spawner(install, store, docker, baked=baked if isinstance(baked, list)
                               else None)
    if not isinstance(baked, list):
        docker.answers["image"] = [(1, "", "no such image")]
    with pytest.raises(BoxProfileError) as caught:
        spawner.spawn("unsafe-1")
    assert expect in str(caught.value) and SYNTHETIC_MARK not in str(caught.value)
    assert docker.commands("run") == []


@pytest.mark.parametrize(("probe", "expect"), [
    ((0, "999 998\n", ""), None),
    ((0, "0 0\n", ""), "a oneshot box's user is root"),
    ((125, "", "unable to find user temperai"), "the uid of 'temperai' in the image can't be read"),
], ids=["named user", "root", "unknown"])
def test_a_named_users_ids_are_read_from_the_image(install, monkeypatch, probe, expect):
    _oneshot(monkeypatch)
    install.user = "temperai"
    store = MemoryStore()
    store.add("named-1", workflow="sealed_probe", workspace=str(install.run_a))
    docker = DeliveringDocker(answers={"run": [probe]})
    spawner = _oneshot_spawner(install, store, docker)
    if expect:
        with pytest.raises(BoxProfileError, match=expect):
            spawner.spawn("named-1")
        assert len(docker.commands("run")) == 1, "only the probe ran"
        return
    spawner.spawn("named-1")
    probe_cmd, run = docker.commands("run")
    assert "--rm" in probe_cmd and "--network" in probe_cmd and "temper.role=probe" in probe_cmd
    assert _flag(run, "--tmpfs")[-1].endswith(",uid=999,gid=998")


def test_a_penpot_login_workflow_is_refused_plainly_under_oneshot(install, monkeypatch):
    # (named without "password": pytest's tmp_path takes the test's name, and a path that
    # looks like a key folder is never granted as data)
    (install.configs / "agents" / "sealed_probe.yaml").write_text(
        "agent:\n  name: sealed_probe\n  type: script\n  script_template: |\n"
        "    #!/bin/bash\n    curl -u \"$PENPOT_AGENT_EMAIL:$PENPOT_AGENT_PASSWORD\" x\n")
    _sealed(monkeypatch)  # sealed with the start environment: runs as in BS1
    store = MemoryStore()
    store.add("penpot-1", workflow="sealed_probe", workspace=str(install.run_a))
    _box_spawner(install, store, FakeDocker()).spawn("penpot-1")

    _oneshot(monkeypatch)
    store.add("penpot-2", workflow="sealed_probe", workspace=str(install.run_b))
    docker = DeliveringDocker()
    with pytest.raises(BoxProfileError) as caught:
        _oneshot_spawner(install, store, docker).spawn("penpot-2")
    assert "the Penpot password" in str(caught.value)
    assert "explicit legacy profile" in str(caught.value)
    assert docker.commands("run") == [] and docker.commands("exec") == []


def test_split_delivery_keeps_only_declared_plain_settings_in_docker():
    plain, delivered = ds.split_delivery(
        ["PATH=/bin", "HOME=/app", "TEMPER_API=http://server:8420",
         f"HTTPS_PROXY={PROXY_WITH_PASSWORD}", "TEMPER_LOG_LEVEL=INFO",
         f"OPENAI_API_KEY={SYNTHETIC_MARK}", "GITHUB_TOKEN=tghk_synthetic",
         "SAFE_LOOKING=tghk_synthetic", f"{box_profile.PROFILE_ENV}={{}}"],
        agent_tools={"PATH", "HOME", "TEMPER_API", "HTTPS_PROXY", "SAFE_LOOKING",
                     "OPENAI_API_KEY"})
    assert plain == ["PATH=/bin", "HOME=/app", "TEMPER_API=http://server:8420",
                     f"{box_profile.PROFILE_ENV}={{}}"]
    assert sorted(delivered) == ["GITHUB_TOKEN", "HTTPS_PROXY", "OPENAI_API_KEY",
                                 "SAFE_LOOKING", "TEMPER_LOG_LEVEL"]


def test_a_secret_value_in_a_command_is_found():
    delivered = {"SYNTH_SERVICE_TOKEN": SYNTHETIC_MARK, "TEMPER_LOG_LEVEL": "INFO",
                 "SHORT_TOKEN": "abc"}
    cmd = ["docker", "run", "--label", f"x={SYNTHETIC_MARK}", "--env", "LEVEL=INFO", "abc"]
    assert ds.secrets_in_command(cmd, delivered) == ["SYNTH_SERVICE_TOKEN"]


def test_env_stays_the_default_and_its_profile_says_so(install, monkeypatch):
    _sealed(monkeypatch)
    monkeypatch.delenv(box_profile.BOOTSTRAP_ENV, raising=False)
    store = MemoryStore()
    store.add("env-1", workflow="sealed_probe", workspace=str(install.run_a))
    docker = FakeDocker()
    _box_spawner(install, store, docker).spawn("env-1")
    doc = store.record("env-1")["doc"]
    assert doc["settings"][box_profile.BOOTSTRAP_ENV] == box_bootstrap.ENV
    assert doc["bootstrap"] == box_bootstrap.ENV_SECTION
    assert "writer" not in doc["runtime"] and "delivery" not in store.record("env-1")
    assert docker.commands("exec") == [] and docker.commands("image") == []
    assert not any(box_bootstrap.BOOT_DIR in part for part in docker.commands("run")[-1])
