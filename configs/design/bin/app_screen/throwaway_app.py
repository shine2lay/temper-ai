"""Start and stop a throwaway copy of a product's app for stage 2's capture (host only).

A server app runs from its pinned commit exported into its own checkout folder (git archive, never the repo's
own folder), built once per commit, with a fresh database per start, seeded by the app file's seed command and
served on loopback. A static app is served from its folder by Python's http.server on loopback. A port that is
already taken is refused: the capture never reads a server it did not start. Model-free.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RUNS = Path(os.environ.get("APP_SCREEN_RUNS", "/tmp/app-screen/runs"))
BUILT = ".app-screen-built"


class ThrowawayError(RuntimeError):
    """The throwaway copy could not be prepared, started or reached; the message says which step failed."""


def _port_taken(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _fill(value: str, names: dict[str, str]) -> str:
    for key, val in names.items():
        value = value.replace("{" + key + "}", val)
    return value


def _run(argv: list[str], cwd: Path, env: dict[str, str], what: str, log: Path, timeout: int = 1800) -> None:
    with log.open("a", encoding="utf-8") as out:
        out.write(f"\n$ ({what}) {' '.join(argv)}\n")
        out.flush()
        try:
            done = subprocess.run(argv, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ThrowawayError(f"{what}: {exc.__class__.__name__}: {exc} (log {log})") from None
    if done.returncode:
        raise ThrowawayError(f"{what}: exited {done.returncode} (log {log})")


def prepare_checkout(app: dict[str, Any], log: Path) -> Path:
    """Export the pinned commit into the checkout folder and build it, once per commit."""
    a = app["app"]
    checkout = Path(a["checkout"])
    marker = checkout / BUILT
    if marker.is_file() and marker.read_text().strip() == a["commit"]:
        return checkout
    if checkout.exists():
        shutil.rmtree(checkout)
    checkout.mkdir(parents=True)
    archive = subprocess.run(["git", "-C", a["repo"], "archive", a["commit"]], capture_output=True)
    if archive.returncode:
        raise ThrowawayError(f"export {a['commit']}: git archive failed: {archive.stderr.decode()[:300]}")
    untar = subprocess.run(["tar", "-x", "-C", str(checkout)], input=archive.stdout, capture_output=True)
    if untar.returncode:
        raise ThrowawayError(f"export {a['commit']}: tar failed: {untar.stderr.decode()[:300]}")
    names = {"checkout": str(checkout), "port": str(a["port"])}
    env = {**os.environ}
    for step in a["build"]:
        _run([_fill(x, names) for x in step["run"]], checkout / step["cwd"], env, f"build: {step['run'][0]}", log)
    marker.write_text(a["commit"] + "\n")
    return checkout


class Throwaway:
    """with Throwaway(app) as base_url: ... starts the copy, yields its loopback address, stops it after."""

    def __init__(self, app: dict[str, Any]):
        self.app = app
        self.proc: subprocess.Popen | None = None
        self.run_dir: Path | None = None

    def __enter__(self) -> str:
        a = self.app["app"]
        if _port_taken(a["port"]):
            raise ThrowawayError(f"port {a['port']} is already in use: stage 2 captures only a copy it starts itself")
        RUNS.mkdir(parents=True, exist_ok=True)
        self.run_dir = Path(tempfile.mkdtemp(prefix=f"{self.app['product']}-", dir=RUNS))
        log = self.run_dir / "server.log"
        try:
            self._start(a, log)
            self._wait_ready(a.get("ready", "/"), log)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self.app["base_url"]

    def _start(self, a: dict[str, Any], log: Path) -> None:
        if a["kind"] == "static":
            root = Path(a["root"])
            if not root.is_dir():
                raise ThrowawayError(f"static app folder {root} is missing")
            argv = ["python3", "-m", "http.server", str(a["port"]), "--bind", "127.0.0.1", "--directory", str(root)]
            self.proc = subprocess.Popen(argv, stdout=log.open("a"), stderr=subprocess.STDOUT)
            return
        checkout = prepare_checkout(self.app, log)
        names = {"checkout": str(checkout), "port": str(a["port"]), "run": str(self.run_dir)}
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp"),
               **{k: _fill(v, names) for k, v in a.get("env", {}).items()}}
        if a.get("env_file"):
            env_file = self.run_dir / "app.env"
            env_file.write_text("".join(f"{k}={_fill(v, names)}\n" for k, v in a["env_file"].items()))
            env[a.get("env_file_variable", "ENV_FILE")] = str(env_file)
        _run([_fill(x, names) for x in a["seed"]], self.run_dir, env, "seed", log, timeout=900)
        self.proc = subprocess.Popen([_fill(x, names) for x in a["serve"]], cwd=self.run_dir, env=env,
                                     stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True)

    def _wait_ready(self, path: str, log: Path, seconds: float = 90) -> None:
        url = self.app["base_url"] + path
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.proc is not None and self.proc.poll() is not None:
                raise ThrowawayError(f"the app exited {self.proc.returncode} before it answered (log {log})")
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    if resp.status < 500:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.5)
        raise ThrowawayError(f"{url} did not answer in {seconds:.0f} s (log {log})")

    def __exit__(self, *exc) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, 15) if self.app["app"]["kind"] == "server" else self.proc.terminate()
                self.proc.wait(timeout=20)
            except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError):
                self.proc.kill()
        self.proc = None
