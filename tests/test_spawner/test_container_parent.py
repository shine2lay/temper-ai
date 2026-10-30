"""Test-only Docker placement. No production imports, quota copy or policy switch.

The installed test-cpu CLI owns policy and kernel checks. A Docker client being
inside the slice says nothing about daemon-created work. See the contract and
G's outstanding live proof in docs/shared-test-cpu-containers.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

CLI = Path("/usr/local/libexec/test-cpu/bin/test-cpu")
POLICY = Path("/etc/agent-tools/test-cpu.json")
INSPECT = ('{"id":{{json .Id}},"parent":{{json .HostConfig.CgroupParent}},'
           '"running":{{json .State.Running}},"pid":{{json .State.Pid}}}')


class ContainerParentError(RuntimeError):
    """Placement could not be proved; never turn this into an unavailable skip."""


class CommandBudget:
    """The caller's one deadline, including discovery, verification and payload."""

    def __init__(self, command: list[str], timeout: float | None):
        self.command = list(command)
        self.timeout = timeout
        self.deadline = None if timeout is None else time.monotonic() + timeout

    def timeout_error(self, cause=None) -> subprocess.TimeoutExpired:
        return subprocess.TimeoutExpired(self.command, self.timeout,
            output=getattr(cause, "output", None), stderr=getattr(cause, "stderr", None))

    def remaining(self, maximum: float | None = None) -> float | None:
        if self.deadline is None:
            return maximum
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise self.timeout_error()
        return left if maximum is None else min(left, maximum)

    def run(self, argv: list[str], **kwargs) -> subprocess.CompletedProcess:
        if self.deadline is not None:
            kwargs["timeout"] = self.remaining(kwargs.get("timeout"))
        try:
            return subprocess.run(argv, **kwargs)
        except subprocess.TimeoutExpired as exc:
            if self.deadline is None:
                raise
            raise self.timeout_error(exc) from exc


def _read_command(argv: list[str], budget: CommandBudget | None = None) -> str:
    result = (budget or CommandBudget(argv, None)).run(
        argv, capture_output=True, text=True, timeout=30)
    if result.returncode:
        # Do not echo Docker output, a command's environment, or synthetic delivery data.
        raise ContainerParentError(f"placement query failed: {argv[0]} {argv[1]}")
    return result.stdout.strip()


def _json_command(argv: list[str], budget: CommandBudget | None = None):
    try:
        return json.loads(_read_command(argv, budget))
    except (TypeError, ValueError) as exc:
        raise ContainerParentError("malformed placement query") from exc


def _local_endpoint(budget: CommandBudget | None = None) -> str:
    # DOCKER_CONTEXT overrides DOCKER_HOST, just as in Docker's CLI.
    if os.environ.get("DOCKER_CONTEXT") or not os.environ.get("DOCKER_HOST"):
        endpoint = _read_command([
            "docker", "context", "inspect", "--format", '{{.Endpoints.docker.Host}}',
        ], budget)
    else:
        endpoint = os.environ["DOCKER_HOST"]
    if endpoint not in {"unix:///var/run/docker.sock", "unix:///run/docker.sock"}:
        raise ContainerParentError("test parent requires the local Docker socket")
    return endpoint


def _check_daemon(budget: CommandBudget | None = None) -> None:
    _local_endpoint(budget)
    info = _json_command([
        "docker", "info", "--format",
        '{"driver":{{json .CgroupDriver}},"version":{{json .CgroupVersion}},'
        '"os":{{json .OperatingSystem}},"security":{{json .SecurityOptions}}}',
    ], budget)
    if (not isinstance(info, dict) or info.get("driver") != "systemd"
            or str(info.get("version")) != "2"
            or not isinstance(info.get("os"), str)
            or "docker desktop" in info["os"].lower()
            or not isinstance(info.get("security"), list)
            or any("rootless" in str(option) for option in info["security"])):
        raise ContainerParentError("test parent requires rootful Linux Docker, systemd cgroup v2")


def container_parent(budget: CommandBudget | None = None) -> ContainerParent | None:
    """Only an absent installation+policy or CLI exit 3 means inactive."""
    # Establish absence without launching anything. Existing fixture unit tests
    # mock subprocess.run for Docker only; their stub is not an installed CLI.
    # lstat also detects broken symlinks, and permission errors fail closed.
    try:
        CLI.lstat()
    except FileNotFoundError:
        try:
            POLICY.lstat()
        except FileNotFoundError:
            return None
        raise ContainerParentError("test-cpu missing or broken with policy present") from None
    try:
        result = (budget or CommandBudget([str(CLI), "parent"], None)).run(
            [str(CLI), "parent"], capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise ContainerParentError("installed test-cpu command is unavailable") from None
    if result.returncode == 3:
        return None
    parent = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[a-z][a-z0-9]{0,39}\.slice", parent):
        raise ContainerParentError("test-cpu parent refused or returned an invalid slice")
    status = _json_command([str(CLI), "status", "--json"], budget)
    if (not isinstance(status, dict) or status.get("mode") != "enabled"
            or status.get("namespace") != "host" or status.get("slice") != parent):
        raise ContainerParentError("test parent requires the enabled host cgroup namespace")
    _check_daemon(budget)
    return ContainerParent(parent, budget)


def _start_time(pid: int) -> str:
    try:
        # comm may contain spaces/parentheses; field 22 follows the last ')'.
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError) as exc:
        raise ContainerParentError("container host PID disappeared or is unreadable") from exc


@dataclass(frozen=True)
class ContainerParent:
    """One query's parent, shared by create, reuse, exec and image build."""

    slice: str
    budget: CommandBudget | None = None

    def create_args(self) -> list[str]:
        return [f"--cgroup-parent={self.slice}"]

    def _inspect(self, name: str) -> dict:
        row = _json_command(["docker", "inspect", "--format", INSPECT, name], self.budget)
        if (not isinstance(row, dict) or row.get("parent") != self.slice
                or not isinstance(row.get("id"), str) or not row["id"]):
            raise ContainerParentError("existing test container has the wrong parent or identity")
        return row

    def verify(self, name: str, *, stopped: bool = False) -> None:
        """Check host init PID and Docker's current PID set, without moving anything.

        An exec and its children inherit this container cgroup, not the client's.
        The live G proof must observe a held exec/child too; a snapshot cannot
        observe a child that already exited. Stopped is only for safe PG cleanup.
        """
        before = self._inspect(name)
        if stopped and before.get("running") is False and before.get("pid") == 0:
            return
        pid = before.get("pid")
        if before.get("running") is not True or type(pid) is not int or pid <= 0:
            raise ContainerParentError("test container is not running with a host init PID")
        birth = _start_time(pid)
        top = _read_command(["docker", "top", name, "-eo", "pid"], self.budget).splitlines()
        if not top or top[0].strip() != "PID" or any(not p.strip().isdigit() for p in top[1:]):
            raise ContainerParentError("Docker returned an invalid host PID list")
        pids = {int(p.strip()) for p in top[1:]}
        if pid not in pids:
            raise ContainerParentError("Docker host PID list excludes init")
        for child in sorted(pids):
            started = _start_time(child)
            member = _json_command([str(CLI), "membership", "--pid", str(child), "--json"], self.budget)
            if (not isinstance(member, dict) or member.get("inside") is not True
                    or member.get("pid") != child or member.get("mode") != "enabled"
                    or member.get("slice") != self.slice or member.get("parentOk") is not True
                    or not str(member.get("cgroup", "")).startswith(f"/{self.slice}/")):
                raise ContainerParentError("test container PID is outside the shared parent")
            if _start_time(child) != started:
                raise ContainerParentError("container host PID identity changed")
        if self._inspect(name) != before or _start_time(pid) != birth:
            raise ContainerParentError("container identity changed during verification")
        if self.budget is not None:
            self.budget.remaining()

    def build_command(self, cmd: list[str]) -> list[str]:
        """Pin the local docker driver and pass its RUN parent explicitly.

        Flag support is not evidence that BuildKit used it. An unsupported or
        ignored builder is a G failure to repair, never a skipped qualification.
        """
        rows = _read_command(["docker", "buildx", "ls", "--format", "{{json .}}"], self.budget)
        try:
            builders = [json.loads(row) for row in rows.splitlines() if row.strip()]
            if any(not isinstance(row, dict) for row in builders):
                raise ValueError("builder row is not an object")
            chosen = {row["Name"]: row for row in builders if row.get("Current") is True}
            if len(chosen) != 1:
                raise ValueError("no unique current builder")
            name, builder = next(iter(chosen.items()))
            if (not isinstance(name, str) or not name or builder["Driver"] != "docker"
                    or not isinstance(builder["Nodes"], list) or len(builder["Nodes"]) != 1):
                raise ValueError("unsupported builder")
            node = builder["Nodes"][0]
            if not isinstance(node, dict) or not isinstance(node.get("Endpoint"), str):
                raise ValueError("builder node is not an endpoint")
            endpoint = node["Endpoint"]
            if not endpoint.startswith("unix://"):
                endpoint = _read_command([
                    "docker", "context", "inspect", endpoint,
                    "--format", '{{.Endpoints.docker.Host}}',
                ], self.budget)
            if endpoint != _local_endpoint(self.budget) or node["Status"] != "running":
                raise ValueError("builder endpoint differs")
        except (KeyError, TypeError, ValueError) as exc:
            raise ContainerParentError("unsupported test builder; G must qualify or repair it") from exc
        help_text = _read_command(["docker", "buildx", "build", "--help"], self.budget)
        if "--cgroup-parent" not in help_text:
            raise ContainerParentError("test builder has no RUN cgroup-parent support")
        return [cmd[0], "buildx", "build", "--builder", name, "--load",
                *self.create_args(), *cmd[2:]]

    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        if self.budget is None:
            return replace(self, budget=CommandBudget(cmd, kwargs.get("timeout"))).run(cmd, **kwargs)
        if any(c == "--cgroup-parent" or c.startswith("--cgroup-parent=") for c in cmd):
            raise ContainerParentError("test command already chooses a cgroup parent")
        cmd = [*cmd[:2], *self.create_args(), *cmd[2:]]
        name = cmd[cmd.index("--name") + 1]
        if "--detach" in cmd or "-d" in cmd:
            result = self.budget.run(cmd, **kwargs)
            if result.returncode == 0:
                self.verify(name)
            return result
        return self._foreground(cmd, name, **kwargs)

    def _foreground(self, cmd: list[str], name: str, **kwargs) -> subprocess.CompletedProcess:
        # The short-lived probes can finish before inspect. Hold their entry on
        # stdin, verify Docker's host init/shell, then exec the exact original
        # entry. No extra mount/env/network permission, no payload before proof.
        entry = cmd.index("--entrypoint") + 1
        image = entry + 1
        gated = [*cmd[:entry], "/bin/sh", cmd[image], "-c",
                 'read -r ready && [ "$ready" = go ] && exec "$@"', "test-cpu-gate",
                 cmd[entry], *cmd[image + 1:]]
        gated.insert(2, "-i")
        options = dict(kwargs)
        options.pop("timeout", None)
        check = options.pop("check", False)
        if options.pop("capture_output", False):
            options.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if "input" in options or "stdin" in options:
            raise ContainerParentError("foreground test gate requires unused stdin")
        budget = self.budget
        budget.remaining()  # do not create a client after discovery exhausted its budget
        verified = False
        with subprocess.Popen(gated, stdin=subprocess.PIPE, **options) as process:
            try:
                # Wait only for this create to publish its PID, under the caller's
                # existing timeout. A terminated client retains its original result.
                while process.poll() is None:
                    row = budget.run(
                        ["docker", "inspect", "--format", "{{.State.Running}}", name],
                        capture_output=True, text=True,
                    )
                    if row.returncode == 0 and row.stdout.strip() == "true":
                        self.verify(name)
                        verified = True
                        break
                    time.sleep(budget.remaining(0.01))
                go = ("go\n" if options.get("text") else b"go\n") if verified else None
                stdout, stderr = process.communicate(go, timeout=budget.remaining())
            except BaseException as exc:
                process.kill()  # this fixture's own Docker client, as subprocess.run does
                process.communicate()
                if isinstance(exc, subprocess.TimeoutExpired) and budget.timeout is not None:
                    raise budget.timeout_error(exc) from exc
                raise
            result = subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
            if result.returncode == 0 and not verified:
                raise ContainerParentError("foreground container ended without membership proof")
            if check:
                result.check_returncode()
            return result


def _exec_container(cmd: list[str]) -> str:
    # These fixtures use only -i and --user before the container name.
    index = 2
    while index < len(cmd) and cmd[index] in {"-i", "--interactive", "--user"}:
        index += 2 if cmd[index] == "--user" else 1
    if index >= len(cmd) or cmd[index].startswith("-"):
        raise ContainerParentError("unsupported test exec flags")
    return cmd[index]


def run_test_docker(cmd: list[str], *, before_exec=None, **kwargs) -> subprocess.CompletedProcess:
    """One caller budget; exec hooks arm only after verification, beside exec."""
    if cmd[1] not in {"run", "exec", "build"}:
        return subprocess.run(cmd, **kwargs)
    budget = CommandBudget(cmd, kwargs.get("timeout"))
    parent = container_parent(budget)
    if cmd[1] == "exec":
        prefix = list(cmd[:2])
        name = _exec_container(cmd) if parent is not None else None
        if parent is not None:
            parent.verify(name)
        budget.remaining()
        if before_exec is not None:
            cmd, kwargs = before_exec(cmd, kwargs)
            if parent is not None and (cmd[:2] != prefix or _exec_container(cmd) != name):
                raise ContainerParentError("exec callback changed the verified container")
        return budget.run(cmd, **kwargs)
    if parent is None:
        return budget.run(cmd, **kwargs)
    if cmd[1] == "run":
        return parent.run(cmd, **kwargs)
    result = budget.run(parent.build_command(cmd), **kwargs)
    if result.returncode:
        raise ContainerParentError("enabled test build failed; G must qualify or repair the builder")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["parent", "verify"])
    parser.add_argument("name", nargs="?")
    parser.add_argument("--stopped", action="store_true")
    args = parser.parse_args()
    try:
        parent = container_parent()
        if parent is None:
            return 3
        if args.action == "parent":
            print(parent.slice)
        elif args.name:
            parent.verify(args.name, stopped=args.stopped)
        else:
            parser.error("verify requires a container name")
        return 0
    except (ContainerParentError, OSError, subprocess.SubprocessError) as exc:
        print(f"test container placement refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
