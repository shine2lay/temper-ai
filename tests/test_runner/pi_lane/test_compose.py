"""pi-worker, the Pi lane's service in docker-compose.yml (ADR-M4-03, docs/pi-lane.md).

Off by default (profile ``pi``), the worker's image with no build of its own, nothing
depending on it and it on nothing (temper-deploy recreates server and worker without
touching it, Systems rm-a8af8c68), a grace period longer than a turn, and an explicit
setting and mount list that holds no secret beyond the database and Redis URLs. This
machine's folders go in the git-ignored override, never here.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "docker-compose.yml"
HOST_DOCKER = ROOT / "docker-compose.host-docker.yml"

#: pi-worker's grace period: a turn (900 s) settles inside it (runner/pi_lane.py drain).
GRACE_S = 960

SETTINGS = {
    "HOME", "PYTHONDONTWRITEBYTECODE", "TEMPER_DATABASE_URL", "TEMPER_REDIS_URL",
    "TEMPER_LOG_LEVEL", "TEMPER_LANE", "TEMPER_SPAWNER", "TEMPER_PI_AGENT",
    "TEMPER_PI_BOX_CONFIG", "TEMPER_DOCKER_TEMPLATE_CONTAINER", "WORKSPACE_DIR",
}
MOUNTS = [
    "./temper_ai:/app/temper_ai:ro",
    "./configs:/app/configs:ro",
    "./.git:/app/.git:ro",
    "/var/run/docker.sock:/var/run/docker.sock",
]


def services(path: Path = COMPOSE) -> dict:
    return yaml.safe_load(path.read_text())["services"]


def _seconds(value: str) -> int:
    match = re.fullmatch(r"(?:(\d+)m)?(?:(\d+)s)?", str(value))
    assert match and any(match.groups()), value
    return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)


def pi_worker() -> dict:
    service = dict(services()["pi-worker"])
    service["stop_grace_period_s"] = _seconds(service["stop_grace_period"])
    return service


def _binds(service: dict) -> list[tuple[str, str]]:
    """``(source, target)`` of each of a service's volumes, short or long syntax."""
    found = []
    for volume in service.get("volumes") or []:
        if isinstance(volume, dict):
            found.append((str(volume.get("source") or ""), str(volume.get("target") or "")))
        else:
            source, _, rest = str(volume).partition(":")
            found.append((source, rest.partition(":")[0]))
    return found


def test_only_pi_worker_mounts_temper_s_git_folder_and_only_to_read_it():
    """Each Pi run's commit is read from it (SW-16). SW-38 lists it for pi-worker alone, never
    a member box or a run box (Architecture rm-c9c941d4 1(c)); nothing runs git on it."""
    found = {(path.name, name): [(src, dst) for src, dst in _binds(service)
                                 if src.rstrip("/").endswith(".git") or dst.startswith("/app/.git")]
             for path in (COMPOSE, HOST_DOCKER) for name, service in services(path).items()}
    assert {where: binds for where, binds in found.items() if binds} == {
        ("docker-compose.yml", "pi-worker"): [("./.git", "/app/.git")]}
    assert "./.git:/app/.git:ro" in pi_worker()["volumes"]


def test_pi_worker_is_off_unless_its_profile_is_asked_for():
    every = services()
    assert every["pi-worker"]["profiles"] == ["pi"]
    default = [name for name, s in every.items() if not s.get("profiles")]
    assert "pi-worker" not in default
    assert {"server", "postgres", "redis"} <= set(default)


def test_it_is_the_worker_s_image_with_no_build_of_its_own():
    every = services()
    service = every["pi-worker"]
    assert "build" not in service
    # The worker's image is built as <project>-worker: temper-ai-worker in production's
    # project; another project names its own with TEMPER_PI_WORKER_IMAGE.
    assert service["image"] == "${TEMPER_PI_WORKER_IMAGE:-temper-ai-worker}"
    assert every["worker"]["build"]["target"] == "worker" and "image" not in every["worker"]
    assert service["pull_policy"] == "never"


def test_nothing_depends_on_it_and_it_depends_on_nothing():
    """temper-deploy recreates server and worker (its SERVICES): no cascade into pi-worker."""
    every = services()
    assert "depends_on" not in every["pi-worker"]
    for name, service in every.items():
        needs = service.get("depends_on") or {}
        assert "pi-worker" not in needs, f"{name} depends on pi-worker"


def test_a_turn_settles_inside_its_grace_period():
    service = pi_worker()
    assert service["stop_grace_period_s"] == GRACE_S >= 960
    assert service["init"] is True  # SIGTERM reaches the watcher
    assert service["command"] == ["/app/.venv/bin/python", "-m", "temper_ai.cli.main",
                                  "watch-queue"]


def test_its_settings_are_explicit_and_hold_no_secret():
    service = services()["pi-worker"]
    assert "env_file" not in service
    env = service["environment"]
    assert set(env) == SETTINGS
    assert (env["TEMPER_LANE"], env["TEMPER_SPAWNER"], env["TEMPER_PI_AGENT"]) == (
        "pi", "subprocess", "1")
    assert "TEMPER_SECRET_KEY" not in env
    for name in env:
        assert not re.search(r"KEY|TOKEN|SECRET|PASSWORD|OAUTH|CLAUDE", name), name
    # The only secret is the database password inside its URL, as the worker has it.
    assert env["TEMPER_DATABASE_URL"] == services()["worker"]["environment"][
        "TEMPER_DATABASE_URL"]


def test_its_mounts_are_explicit_and_none_of_the_forbidden_ones():
    service = services()["pi-worker"]
    assert service["volumes"] == MOUNTS
    text = "\n".join(service["volumes"])
    for forbidden in (".claude", ".credentials.json", ".env", "/local", ".temper",
                      "share/claude", "workspaces", "WORKSPACE_DIR"):
        assert forbidden not in text, forbidden
    assert "user" not in service, "pi-worker keeps the image's user, uid 1000"


def test_only_pi_worker_runs_in_the_pi_lane():
    every = services()
    for name, service in every.items():
        env = service.get("environment") or {}
        if name != "pi-worker":
            assert "TEMPER_LANE" not in env, name
            assert env.get("TEMPER_PI_AGENT") in (None, "", "0"), name


def test_the_host_docker_overlay_leaves_pi_worker_alone():
    overlay = services(HOST_DOCKER)
    assert "pi-worker" not in overlay
    for name, service in overlay.items():
        assert (service.get("environment") or {}).get("TEMPER_SPAWNER") != "subprocess", \
            f"{name}: the subprocess spawner beside a Docker socket is the Pi lane's alone (H1)"


def test_no_machine_path_in_the_public_file():
    """The same-path mounts and the box config live in the git-ignored override."""
    service = services()["pi-worker"]
    text = yaml.safe_dump(service)
    assert "/home/" not in text.replace("/home/temperai-worker", "")
    assert ".local/state" not in text and ".local/share" not in text
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert "docker-compose.override.yml" in ignored
