"""Every Python package the image installs reaches every place temper_ai does, the same way.

pyproject.toml ships three top-level packages (temper_ai, p3_source_closure,
p3_host_contracts); temper_ai.p3_authority imports the other two. Before temper #295 only
temper_ai/ reached the image, the server, the workers and the boxes, so the import failed
there ("No module named 'p3_source_closure'"). Each place gives the others exactly what it
gives temper_ai: the Dockerfile's COPY and bytecode clean-up, compose's read-only binds,
and a sealed box's read-only, pinned, digested, scanned code grant.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

from temper_ai.spawner import box_seal
from temper_ai.spawner.box_profile import BoxProfileError

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.host-docker.yml")
OTHERS = [p for p in box_seal.CODE_PACKAGES if p != "temper_ai"]


def _stages(dockerfile: str) -> dict[str, list[str]]:
    """Each build stage's instruction lines (continuations joined), by stage name."""
    stages: dict[str, list[str]] = {}
    current: list[str] = []
    for line in re.sub(r"\\\n", " ", dockerfile).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        found = re.match(r"FROM\s+\S+(?:\s+AS\s+(\S+))?", line, re.IGNORECASE)
        if found:
            current = stages.setdefault(found.group(1) or f"stage{len(stages)}", [])
        current.append(line)
    return stages


def _binds(service: dict) -> dict[str, tuple[str, str]]:
    """target -> (source, mode) of a service's volumes, short or long syntax."""
    found = {}
    for volume in service.get("volumes") or []:
        if isinstance(volume, dict):
            mode = "ro" if volume.get("read_only") else "rw"
            found[str(volume.get("target"))] = (str(volume.get("source")), mode)
        else:
            source, target, *rest = str(volume).split(":")
            found[target] = (source, rest[0] if rest else "rw")
    return found


def test_the_code_package_list_is_the_one_pyproject_installs():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    wheel = project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert tuple(wheel) == box_seal.CODE_PACKAGES
    assert box_seal.CODE_TARGETS == tuple(f"/app/{p}" for p in box_seal.CODE_PACKAGES)
    assert box_seal.CODE_TARGET == "/app/temper_ai" == box_seal.CODE_TARGETS[0]
    for package in box_seal.CODE_PACKAGES:
        assert (ROOT / package / "__init__.py").is_file(), package


@pytest.mark.parametrize("package", OTHERS)
def test_the_image_copies_each_package_where_it_copies_temper_ai(package):
    stages = _stages((ROOT / "Dockerfile").read_text())
    copying = [name for name, lines in stages.items()
               if "COPY temper_ai/ ./temper_ai/" in lines]
    assert copying == ["base"]
    for name in copying:
        lines = stages[name]
        assert f"COPY {package}/ ./{package}/" in lines
        clean = [line for line in lines if "__pycache__" in line and "find" in line]
        assert clean and all(f"/app/{package}" in line for line in clean), clean
        assert lines.index(f"COPY {package}/ ./{package}/") < lines.index(clean[0])


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_every_service_that_binds_temper_ai_binds_each_package_the_same_way(compose):
    services = yaml.safe_load((ROOT / compose).read_text())["services"]
    checked = []
    for name, service in services.items():
        binds = _binds(service)
        if box_seal.CODE_TARGET not in binds:
            assert not any(f"/app/{p}" in binds for p in OTHERS), name
            continue
        source, mode = binds[box_seal.CODE_TARGET]
        assert (source, mode) == ("./temper_ai", "ro"), name
        for package in OTHERS:
            assert binds.get(f"/app/{package}") == (f"./{package}", mode), (name, package)
        checked.append(name)
    if compose == "docker-compose.yml":
        assert sorted(checked) == ["pi-worker", "server", "worker"]


def _template(tmp_path: Path, packages: list[str]) -> list[tuple[str, str]]:
    mounts = []
    for package in packages:
        folder = tmp_path / "src" / package
        folder.mkdir(parents=True)
        (folder / "__init__.py").write_text(f"NAME = {package!r}\n")
        mounts.append((str(folder), f"/app/{package}"))
    configs = tmp_path / "src" / "configs"
    configs.mkdir(parents=True)
    return [*mounts, (str(configs), box_seal.CONFIG_TARGET)]


def test_a_sealed_box_grants_every_code_package_as_it_grants_temper_ai(tmp_path):
    mounts = _template(tmp_path, list(box_seal.CODE_PACKAGES))
    with box_seal.plan_sealed(mounts=mounts, workspace_dir=None, workspace_path="",
                              data_targets=[], view=box_seal.WorkerView(None)) as plan:
        grants = {g.target: g for g in plan.grants}
        for package, target in zip(box_seal.CODE_PACKAGES, box_seal.CODE_TARGETS, strict=True):
            grant = grants[target]
            assert (grant.read_only, grant.kind) == (True, "code"), package
            assert grant.source == str(tmp_path / "src" / package) and grant.pin
            source = plan.sources[box_seal.CODE_SOURCES[package]]
            assert source["from"] == "bind" and source["digest"].startswith("sha256:")
            assert target not in plan.absent
            assert box_seal.mount_class(grant.source, target, None) == "code"
    assert box_seal.CODE_SOURCES["temper_ai"] == "code"
    assert len(set(box_seal.CODE_SOURCES.values())) == len(box_seal.CODE_PACKAGES)


@pytest.mark.parametrize("package", OTHERS)
def test_a_package_the_template_does_not_bind_comes_from_the_image(tmp_path, package):
    mounts = _template(tmp_path, [p for p in box_seal.CODE_PACKAGES if p != package])
    with box_seal.plan_sealed(mounts=mounts, workspace_dir=None, workspace_path="",
                              data_targets=[], view=box_seal.WorkerView(None)) as plan:
        assert plan.sources[box_seal.CODE_SOURCES[package]] == {"from": "image"}
        assert f"/app/{package}" not in {g.target for g in plan.grants}


@pytest.mark.parametrize("package", OTHERS)
def test_a_package_is_never_declared_data(tmp_path, package):
    mounts = _template(tmp_path, list(box_seal.CODE_PACKAGES))
    with pytest.raises(BoxProfileError, match="is code: never data"):
        box_seal.plan_sealed(mounts=mounts, workspace_dir=None, workspace_path="",
                             data_targets=[f"/app/{package}"], view=box_seal.WorkerView(None))
