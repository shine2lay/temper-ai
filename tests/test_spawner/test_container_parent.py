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
from dataclasses import dataclass
from pathlib import Path

CLI = Path("/usr/local/libexec/test-cpu/bin/test-cpu")
POLICY = Path("/etc/agent-tools/test-cpu.json")
INSPECT = ('{"id":{{json .Id}},"parent":{{json .HostConfig.CgroupParent}},'
           '"running":{{json .State.Running}},"pid":{{json .State.Pid}}}')


class ContainerParentError(RuntimeError):
    """Placement could not be proved; never turn this into an unavailable skip."""


def _read_command(argv: list[str]) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    if result.returncode:
        # Do not echo Docker output, a command's environment, or synthetic delivery data.
        raise ContainerParentError(f"placement query failed: {argv[0]} {argv[1]}")
    return result.stdout.strip()


def _json_command(argv: list[str]):
    try:
        return json.loads(_read_command(argv))
    except (TypeError, ValueError) as exc:
        raise ContainerParentError("malformed placement query") from exc


def _local_endpoint() -> str:
    # DOCKER_CONTEXT overrides DOCKER_HOST, just as in Docker's CLI.
    if os.environ.get("DOCKER_CONTEXT") or not os.environ.get("DOCKER_HOST"):
        endpoint = _read_command([
            "docker", "context", "inspect", "--format", '{{.Endpoints.docker.Host}}',
        ])
    else:
        endpoint = os.environ["DOCKER_HOST"]
    if endpoint not in {"unix:///var/run/docker.sock", "unix:///run/docker.sock"}:
        raise ContainerParentError("test parent requires the local Docker socket")
    return endpoint


def _check_daemon() -> None:
    _local_endpoint()
    info = _json_command([
        "docker", "info", "--format",
        '{"driver":{{json .CgroupDriver}},"version":{{json .CgroupVersion}},'
        '"os":{{json .OperatingSystem}},"security":{{json .SecurityOptions}}}',
    ])
    if (not isinstance(info, dict) or info.get("driver") != "systemd"
            or str(info.get("version")) != "2"
            or not isinstance(info.get("os"), str)
            or "docker desktop" in info["os"].lower()
            or not isinstance(info.get("security"), list)
            or any("rootless" in str(option) for option in info["security"])):
        raise ContainerParentError("test parent requires rootful Linux Docker, systemd cgroup v2")


def container_parent() -> ContainerParent | None:
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
        result = subprocess.run([str(CLI), "parent"], capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise ContainerParentError("installed test-cpu command is unavailable") from None
    if result.returncode == 3:
        return None
    parent = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[a-z][a-z0-9]{0,39}\.slice", parent):
        raise ContainerParentError("test-cpu parent refused or returned an invalid slice")
    status = _json_command([str(CLI), "status", "--json"])
    if (not isinstance(status, dict) or status.get("mode") != "enabled"
            or status.get("namespace") != "host" or status.get("slice") != parent):
        raise ContainerParentError("test parent requires the enabled host cgroup namespace")
    _check_daemon()
    return ContainerParent(parent)


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

    def create_args(self) -> list[str]:
        return [f"--cgroup-parent={self.slice}"]

    def _inspect(self, name: str) -> dict:
        row = _json_command(["docker", "inspect", "--format", INSPECT, name])
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
        top = _read_command(["docker", "top", name, "-eo", "pid"]).splitlines()
        if not top or top[0].strip() != "PID" or any(not p.strip().isdigit() for p in top[1:]):
            raise ContainerParentError("Docker returned an invalid host PID list")
        pids = {int(p.strip()) for p in top[1:]}
        if pid not in pids:
            raise ContainerParentError("Docker host PID list excludes init")
        for child in sorted(pids):
            started = _start_time(child)
            member = _json_command([str(CLI), "membership", "--pid", str(child), "--json"])
            if (not isinstance(member, dict) or member.get("inside") is not True
                    or member.get("pid") != child or member.get("mode") != "enabled"
                    or member.get("slice") != self.slice or member.get("parentOk") is not True
                    or not str(member.get("cgroup", "")).startswith(f"/{self.slice}/")):
                raise ContainerParentError("test container PID is outside the shared parent")
            if _start_time(child) != started:
                raise ContainerParentError("container host PID identity changed")
        if self._inspect(name) != before or _start_time(pid) != birth:
            raise ContainerParentError("container identity changed during verification")

    def build_command(self, cmd: list[str]) -> list[str]:
        """Pin the local docker driver and pass its RUN parent explicitly.

        Flag support is not evidence that BuildKit used it. An unsupported or
        ignored builder is a G failure to repair, never a skipped qualification.
        """
        rows = _read_command(["docker", "buildx", "ls", "--format", "{{json .}}"])
        try:
            builders = [json.loads(row) for row in rows.splitlines() if row.strip()]
            chosen = {row["Name"]: row for row in builders if row.get("Current") is True}
            if len(chosen) != 1:
                raise ValueError("no unique current builder")
            name, builder = next(iter(chosen.items()))
            if builder["Driver"] != "docker" or len(builder["Nodes"]) != 1:
                raise ValueError("unsupported builder")
            node = builder["Nodes"][0]
            endpoint = node["Endpoint"]
            if not endpoint.startswith("unix://"):
                endpoint = _read_command([
                    "docker", "context", "inspect", endpoint,
                    "--format", '{{.Endpoints.docker.Host}}',
                ])
            if endpoint != _local_endpoint() or node["Status"] != "running":
                raise ValueError("builder endpoint differs")
        except (KeyError, TypeError, ValueError) as exc:
            raise ContainerParentError("unsupported test builder; G must qualify or repair it") from exc
        help_text = _read_command(["docker", "buildx", "build", "--help"])
        if "--cgroup-parent" not in help_text:
            raise ContainerParentError("test builder has no RUN cgroup-parent support")
        return [cmd[0], "buildx", "build", "--builder", name, "--load",
                *self.create_args(), *cmd[2:]]

    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        if any(c == "--cgroup-parent" or c.startswith("--cgroup-parent=") for c in cmd):
            raise ContainerParentError("test command already chooses a cgroup parent")
        cmd = [*cmd[:2], *self.create_args(), *cmd[2:]]
        name = cmd[cmd.index("--name") + 1]
        if "--detach" in cmd or "-d" in cmd:
            result = subprocess.run(cmd, **kwargs)
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
        timeout = options.pop("timeout")
        check = options.pop("check", False)
        if options.pop("capture_output", False):
            options.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if "input" in options or "stdin" in options:
            raise ContainerParentError("foreground test gate requires unused stdin")
        deadline = time.monotonic() + timeout
        verified = False
        with subprocess.Popen(gated, stdin=subprocess.PIPE, **options) as process:
            try:
                # Wait only for this create to publish its PID, under the caller's
                # existing timeout. A terminated client retains its original result.
                while process.poll() is None:
                    row = subprocess.run(
                        ["docker", "inspect", "--format", "{{.State.Running}}", name],
                        capture_output=True, text=True, timeout=max(0.001, deadline - time.monotonic()),
                    )
                    if row.returncode == 0 and row.stdout.strip() == "true":
                        self.verify(name)
                        verified = True
                        break
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(cmd, timeout)
                    time.sleep(0.01)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(cmd, timeout)
                go = "go\n" if options.get("text") else b"go\n"
                stdout, stderr = process.communicate(go, timeout=remaining)
            except BaseException:
                process.kill()  # this fixture's own Docker client, as subprocess.run does
                process.communicate()
                raise
            result = subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
            if result.returncode == 0 and not verified:
                raise ContainerParentError("foreground container ended without membership proof")
            if check:
                result.check_returncode()
            return result


def run_test_docker(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Reuse the existing subprocess API, including byte stdin/output and failures."""
    if cmd[1] not in {"run", "exec", "build"}:
        return subprocess.run(cmd, **kwargs)
    parent = container_parent()
    if parent is None:
        return subprocess.run(cmd, **kwargs)
    if cmd[1] == "run":
        return parent.run(cmd, **kwargs)
    if cmd[1] == "exec":
        # These fixtures use only -i and --user before the container name.
        index = 2
        while cmd[index] in {"-i", "--interactive", "--user"}:
            index += 2 if cmd[index] == "--user" else 1
        if cmd[index].startswith("-"):
            raise ContainerParentError("unsupported test exec flags")
        parent.verify(cmd[index])
        return subprocess.run(cmd, **kwargs)
    result = subprocess.run(parent.build_command(cmd), **kwargs)
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
