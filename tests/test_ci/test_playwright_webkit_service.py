"""playwright-mcp-webkit, the WebKit browser service in docker-compose.yml (temper queue #123).

The same MCP server as playwright-mcp, from that service's image pinned by digest plus WebKit
(docker/playwright-mcp-webkit/Dockerfile), for configs/architecture/bin/first_app_check.py
--browser http://playwright-mcp-webkit:8931/mcp (QA's Project 3 kit, PH-1: the journey in WebKit
at 390x844 with touch). The narrowest access that does the job: no host port, no mounts, never
pulled from a registry, and no agent has it as a tool. The Chromium service beside it stays as
it was.

Each guard is one function in GUARDS. test_each_guard_bites breaks the real files one way at a
time and checks that the guard meant to catch it names the break, and
test_every_guard_has_a_bite keeps a guard from being added without such a break.
"""

from __future__ import annotations

import copy
import re
import shlex
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
DOCKERFILE = ROOT / "docker" / "playwright-mcp-webkit" / "Dockerfile"
MCP_SERVERS = ROOT / "configs" / "mcp_servers"
SERVICE = "playwright-mcp-webkit"
BUILD = "docker/playwright-mcp-webkit"
BASE = "mcr.microsoft.com/playwright/mcp"
INSTALL = "node /app/node_modules/playwright-core/cli.js install --with-deps webkit"

#: playwright-mcp's command as it was when the WebKit service was added beside it (#123).
CHROMIUM_COMMAND = [
    "/app/cli.js", "--headless", "--browser", "chromium", "--no-sandbox", "--isolated",
    "--port", "8931", "--host", "0.0.0.0",
    "--allowed-hosts", "playwright-mcp:8931,localhost:8931,127.0.0.1:8931",
    "--output-dir", "/tmp/browser-output",
]
#: Service keys that would hand it something of the host's: a port, a path, a device, privileges.
HOST_ACCESS = ("ports", "volumes", "volumes_from", "devices", "privileged", "cap_add",
               "network_mode", "pid", "ipc")


def load() -> dict:
    """What the guards read: the compose services, the Dockerfile, every file under mcp_servers."""
    return {
        "services": yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"],
        "dockerfile": DOCKERFILE.read_text(encoding="utf-8"),
        "mcp_servers": {str(p.relative_to(MCP_SERVERS)): p.read_text(encoding="utf-8", errors="replace")
                        for p in sorted(MCP_SERVERS.rglob("*")) if p.is_file()},
    }


def _service(data: dict) -> dict:
    return data["services"].get(SERVICE) or {}


def _args(service: dict) -> list[str]:
    command = service.get("command") or []
    return shlex.split(command) if isinstance(command, str) else [str(a) for a in command]


def _value(args: list[str], flag: str) -> str | None:
    return args[args.index(flag) + 1] if flag in args[:-1] else None


def _instructions(dockerfile: str) -> list[str]:
    """The Dockerfile's instruction lines, continuation lines joined, comments left out."""
    joined = re.sub(r"\\\n", " ", dockerfile)
    return [line.strip() for line in joined.splitlines() if line.strip() and not line.lstrip().startswith("#")]


# ---------------------------------------------------------------- the guards


def drives_webkit(data: dict) -> list[str]:
    browser = _value(_args(_service(data)), "--browser")
    return [] if browser == "webkit" else [f"{SERVICE}: --browser is {browser!r}, not webkit"]


def headless(data: dict) -> list[str]:
    return [] if "--headless" in _args(_service(data)) else [f"{SERVICE}: no --headless"]


def isolated(data: dict) -> list[str]:
    return [] if "--isolated" in _args(_service(data)) else [
        f"{SERVICE}: no --isolated (a session would keep the cookies of the one before it)"]


def answers_by_its_name(data: dict) -> list[str]:
    hosts = (_value(_args(_service(data)), "--allowed-hosts") or "").split(",")
    return [] if f"{SERVICE}:8931" in hosts else [
        f"{SERVICE}: --allowed-hosts {hosts} lacks {SERVICE}:8931, so requests by its name are refused"]


def no_host_access(data: dict) -> list[str]:
    given = [key for key in HOST_ACCESS if key in _service(data)]
    return [f"{SERVICE}: has {', '.join(given)}: no host port, mount or privilege"] if given else []


def built_from_its_folder(data: dict) -> list[str]:
    build = _service(data).get("build")
    context = build.get("context") if isinstance(build, dict) else build
    return [] if context == BUILD else [f"{SERVICE}: built from {context!r}, not {BUILD}"]


def never_pulled(data: dict) -> list[str]:
    policy = _service(data).get("pull_policy")
    return [] if policy == "never" else [
        f"{SERVICE}: pull_policy {policy!r}: pull, or up without the image, would ask Docker Hub for its name"]


def base_pinned_by_digest(data: dict) -> list[str]:
    froms = [line.split()[1:] for line in _instructions(data["dockerfile"]) if line.upper().startswith("FROM ")]
    noted = re.findall(r"^#\s*digest:\s*(sha256:[0-9a-f]{64})\s*$", data["dockerfile"], re.M)
    if len(froms) != 1 or len(froms[0]) != 1:
        return [f"Dockerfile: wants one plain FROM line, has {froms}"]
    image, _, digest = froms[0][0].partition("@")
    problems = []
    if image != BASE or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        problems.append(f"Dockerfile: FROM {froms[0][0]} is not {BASE}@sha256:<digest>")
    if noted != [digest]:
        problems.append(f"Dockerfile: the comment's digest {noted} is not the FROM's {digest!r}")
    return problems


def no_latest(data: dict) -> list[str]:
    found = [line for line in _instructions(data["dockerfile"]) if "latest" in line]
    return [f"Dockerfile: 'latest' in {found}"] if found else []


def own_playwright_core(data: dict) -> list[str]:
    lines = _instructions(data["dockerfile"])
    problems = [] if any(INSTALL in line for line in lines) else [f"Dockerfile: WebKit is not installed by `{INSTALL}`"]
    fetchers = [line for line in lines if re.search(r"\b(npx|npm|yarn|pnpm)\b", line)]
    return problems + ([f"Dockerfile: fetches packages {fetchers}"] if fetchers else [])


def runs_as_node(data: dict) -> list[str]:
    users = [line.split()[1] for line in _instructions(data["dockerfile"]) if line.upper().startswith("USER ")]
    return [] if users and users[-1] == "node" else [f"Dockerfile: the last USER is {users[-1:]}, not node"]


def not_an_agent_tool(data: dict) -> list[str]:
    named = [path for path, text in data["mcp_servers"].items() if SERVICE in text]
    return [f"configs/mcp_servers: {named} name {SERVICE}, making it an agent tool"] if named else []


def chromium_untouched(data: dict) -> list[str]:
    args = _args(data["services"].get("playwright-mcp") or {})
    return [] if args == CHROMIUM_COMMAND else [f"playwright-mcp: command is now {args}"]


GUARDS: dict[str, Callable[[dict], list[str]]] = {g.__name__: g for g in (
    drives_webkit, headless, isolated, answers_by_its_name, no_host_access, built_from_its_folder,
    never_pulled, base_pinned_by_digest, no_latest, own_playwright_core, runs_as_node,
    not_an_agent_tool, chromium_untouched)}


def problems(data: dict) -> dict[str, list[str]]:
    return {name: found for name, guard in GUARDS.items() if (found := guard(data))}


# ---------------------------------------------------------------- the breaks each guard must catch


def _set(key: str, value: object) -> Callable[[dict], None]:
    return lambda data: _service(data).__setitem__(key, value)


def _drop(key: str) -> Callable[[dict], None]:
    return lambda data: _service(data).pop(key)


def _command(old: str, new: str, service: str = SERVICE) -> Callable[[dict], None]:
    def change(data: dict) -> None:
        svc = data["services"][service]
        assert old in svc["command"], (service, old)
        svc["command"] = svc["command"].replace(old, new)
    return change


def _dockerfile(old: str, new: str) -> Callable[[dict], None]:
    def change(data: dict) -> None:
        assert old in data["dockerfile"], old
        data["dockerfile"] = data["dockerfile"].replace(old, new)
    return change


def _from(image: str) -> Callable[[dict], None]:
    def change(data: dict) -> None:
        data["dockerfile"], n = re.subn(r"^FROM .*$", f"FROM {image}", data["dockerfile"], flags=re.M)
        assert n == 1, n
    return change


def _append(line: str) -> Callable[[dict], None]:
    return lambda data: data.__setitem__("dockerfile", data["dockerfile"] + line + "\n")


def _register(data: dict) -> None:
    data["mcp_servers"]["webkit.yaml"] = f"mcp_server:\n  name: webkit\n  url: http://{SERVICE}:8931/mcp\n"


BREAKS: list[tuple[str, str, Callable[[dict], None]]] = [
    ("drives_webkit", "browser chromium", _command("--browser webkit", "--browser chromium")),
    ("drives_webkit", "no --browser", _command("--browser webkit", "")),
    ("headless", "headed", _command("--headless", "")),
    ("isolated", "shared profile", _command("--isolated", "")),
    ("answers_by_its_name", "only localhost", _command(f"{SERVICE}:8931,", "")),
    *[("no_host_access", key, _set(key, value)) for key, value in (
        ("ports", ["127.0.0.1:8932:8931"]), ("volumes", ["./workspaces:/tmp/browser-output"]),
        ("volumes_from", ["server"]), ("devices", ["/dev/dri:/dev/dri"]), ("privileged", True),
        ("cap_add", ["SYS_ADMIN"]), ("network_mode", "host"), ("pid", "host"), ("ipc", "host"))],
    ("built_from_its_folder", "built from the repo root", _set("build", ".")),
    ("built_from_its_folder", "no build", _drop("build")),
    ("never_pulled", "default pull policy", _drop("pull_policy")),
    ("never_pulled", "always pulled", _set("pull_policy", "always")),
    ("base_pinned_by_digest", "tag instead of digest", _from(f"{BASE}:0.0.82")),
    ("base_pinned_by_digest", "comment's digest disagrees", _dockerfile("#   digest: sha256:", "#   digest: sha256:0")),
    ("base_pinned_by_digest", "another image", _dockerfile(f"FROM {BASE}@", "FROM mcr.microsoft.com/playwright@")),
    ("base_pinned_by_digest", "a second stage", _append(f"FROM {BASE}:0.0.82")),
    ("no_latest", "FROM :latest", _dockerfile("@sha256:", ":latest@sha256:")),
    ("no_latest", "a later step names latest", _append("RUN node /app/cli.js --version # mcp@latest")),
    ("own_playwright_core", "npx playwright-core", _dockerfile(
        "node /app/node_modules/playwright-core/cli.js install", "npx -y playwright-core install")),
    ("own_playwright_core", "no install", _dockerfile("install --with-deps webkit", "--version")),
    ("runs_as_node", "stays root", _dockerfile("\nUSER node", "\n")),
    ("not_an_agent_tool", "registered in mcp_servers", _register),
    ("chromium_untouched", "Chromium loses --no-sandbox", _command("--no-sandbox", "", "playwright-mcp")),
    ("chromium_untouched", "Chromium becomes webkit", _command("--browser chromium", "--browser webkit", "playwright-mcp")),
]


# ---------------------------------------------------------------- tests


def test_the_webkit_service_is_as_decided():
    """The whole service as decided: every guard passes on the real files."""
    data = load()
    assert SERVICE in data["services"]
    assert problems(data) == {}


@pytest.mark.parametrize(("guard", "change", "breaks"), BREAKS, ids=[f"{g}:{c}" for g, c, _ in BREAKS])
def test_each_guard_bites(guard: str, change: str, breaks: Callable[[dict], None]):
    """The real files broken one way: the guard meant to catch it names the break."""
    data = copy.deepcopy(load())
    breaks(data)
    assert GUARDS[guard](data), f"{guard} let '{change}' through"


def test_every_guard_has_a_bite():
    assert {g for g, _, _ in BREAKS} == set(GUARDS)
