"""A member box as the Pi lane's worker builds it (ADR-M4-03, SW-43, SW-44).

pi-worker mounts the Pi folders at their own host paths, so every bind a member box asks the
Docker daemon for names a real host path inside the box config's ``roots``: the config refuses
a Pi path outside them, the box refuses a bind outside them, and Temper's box files are
sealed-copied into the state root first (the package folder is a path only pi-worker has).
Every socket a turn opens stays under 100 bytes. The owner's Pi folder is looked for under the
configured ``host_home`` too, since in pi-worker that isn't this process's home.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from temper_ai.llm.pi_stream import Redactor
from temper_ai.pi_agent.box import (
    ASSETS,
    PROBE_DIR,
    SOCKET_PATH_LIMIT,
    SOCKET_TAIL_BYTES,
    BoxError,
    WorkerBox,
    inside_roots,
    tree_sha256,
)
from temper_ai.runner import pi_lane
from tests.test_pi_agent import support as sup


@pytest.fixture
def short_root():
    root = Path(tempfile.mkdtemp(prefix="pilane-", dir="/tmp"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _box(tmp_path: Path, short_root: Path, **over) -> WorkerBox:
    over.setdefault("socket_root", str(short_root))
    cfg = sup.box_config(tmp_path, **over)
    return WorkerBox(cfg, sup.spec(tmp_path / "participant"), Redactor(),
                     owner_token=lambda _p: "")


# --- The config's roots ----------------------------------------------------------------------


def test_without_roots_nothing_is_checked_against_them(tmp_path, short_root):
    box = _box(tmp_path, short_root)
    assert box.cfg.roots == [] and box.cfg.root_problems() == []


def test_with_roots_every_pi_path_must_be_inside_them(tmp_path, short_root):
    box = _box(tmp_path, short_root, roots=[str(tmp_path), str(short_root)],
               project_roots=[str(tmp_path / "project")])
    assert box.cfg.root_problems() == []
    assert set(box.cfg.pi_paths()) >= {"state_root", "socket_root", "runtime_dir",
                                       "identity_extension", "identity_config",
                                       "identities_dir", "project root 1"}


def test_a_pi_path_outside_the_roots_is_refused_by_name(tmp_path, short_root):
    with pytest.raises(BoxError) as refused:
        _box(tmp_path, short_root, roots=[str(tmp_path)])
    assert refused.value.code == "box_config_invalid"
    assert "socket_root is outside the roots" in str(refused.value)
    with pytest.raises(BoxError, match="project root 1 is outside the roots"):
        _box(tmp_path, short_root, roots=[str(tmp_path), str(short_root)],
             project_roots=["/srv/elsewhere"])


@pytest.mark.parametrize("root", ["relative/root", "/home/../etc"])
def test_a_root_must_be_a_plain_absolute_path(tmp_path, short_root, root):
    with pytest.raises(BoxError, match="is not an absolute path"):
        _box(tmp_path, short_root, roots=[root])


def test_project_roots_need_roots(tmp_path, short_root):
    with pytest.raises(BoxError, match="project_roots need roots"):
        _box(tmp_path, short_root, project_roots=[str(tmp_path)])


def test_inside_the_roots_is_decided_with_links_resolved(tmp_path):
    inside, outside = tmp_path / "root", tmp_path / "other"
    inside.mkdir()
    outside.mkdir()
    (inside / "link").symlink_to(outside)
    roots = [str(inside)]
    assert inside_roots(str(inside / "sub"), roots)
    assert inside_roots(str(inside), roots)
    assert not inside_roots(str(inside / "link"), roots)
    assert not inside_roots(str(tmp_path / "rootless"), roots)
    assert not inside_roots("root/sub", roots) and not inside_roots("", roots)


# --- The box's binds -------------------------------------------------------------------------


def test_every_bind_inside_the_roots_creates_the_box(tmp_path, short_root):
    box = _box(tmp_path, short_root, roots=[str(tmp_path), str(short_root)])
    box.sock_dir = short_root / "s"
    args = box.create_args()
    sources = [a.split("source=", 1)[1].split(",", 1)[0] for a in args
               if a.startswith("type=bind")]
    assert sources and all(inside_roots(s, box.cfg.roots) for s in sources)


def test_a_bind_outside_the_roots_is_refused_naming_where_it_goes(tmp_path, short_root):
    box = _box(tmp_path, short_root, roots=[str(tmp_path), str(short_root)])
    box.sock_dir = Path(tempfile.mkdtemp(prefix="elsewhere-", dir="/tmp"))
    try:
        with pytest.raises(BoxError) as refused:
            box.create_args()
    finally:
        shutil.rmtree(box.sock_dir, ignore_errors=True)
    assert refused.value.code == "bind_source_outside_roots"
    assert str(refused.value).endswith(
        "the box would bind a host folder outside the Pi roots (for /box-sock); the box was "
        "not created")


# --- Temper's box files ----------------------------------------------------------------------


def test_the_box_files_are_bound_from_a_sealed_copy_in_the_state_root(tmp_path, short_root):
    box = _box(tmp_path, short_root)
    box.sock_dir = short_root / "s"
    mounts = {dst: src for src, dst, _w in box.mounts()}
    state = Path(box.cfg.state_root).resolve()
    assets = Path(mounts["/box"])
    assert assets.is_relative_to(state / "_ext")
    assert assets.name == f"assets-{tree_sha256(ASSETS)[:16]}"
    assert Path(mounts["/ext/temper-box"]) == assets / PROBE_DIR.name
    assert str(ASSETS.resolve()) not in mounts.values()
    assert not (assets / "node_modules").exists()
    assert not list(assets.rglob("__pycache__"))
    assert {p.relative_to(assets) for p in assets.rglob("*")} >= {
        p.relative_to(ASSETS) for p in ASSETS.rglob("*") if "__pycache__" not in p.parts}
    assert box.mounts() == box.mounts(), "the copy is made once and reused"


def test_no_member_box_gets_temper_s_git_folder(tmp_path, short_root):
    """It is pi-worker's alone, for the commit each Pi run records (SW-16, SW-38)."""
    box = _box(tmp_path, short_root)
    box.sock_dir = short_root / "s"
    git = (pi_lane.CODE_ROOT / ".git").resolve()
    for src, dst, _w in box.mounts():
        source = Path(src).resolve()
        assert not (source == git or source.is_relative_to(git) or git.is_relative_to(source)), src
        assert ".git" not in Path(dst).parts, dst


# --- Sockets ---------------------------------------------------------------------------------


def test_a_socket_root_too_long_for_a_turn_s_sockets_is_refused(tmp_path):
    long_root = Path(tempfile.mkdtemp(prefix="pilane-", dir="/tmp"))
    try:
        sockets = long_root / ("s" * (SOCKET_PATH_LIMIT - SOCKET_TAIL_BYTES
                                      - len(str(long_root)) + 1))
        box = _box(tmp_path, long_root, socket_root=str(sockets))
        assert len(str(sockets).encode()) + SOCKET_TAIL_BYTES > SOCKET_PATH_LIMIT
        with pytest.raises(BoxError) as refused:
            box._open_sockets()
        assert refused.value.code == "socket_path_too_long"
        assert str(refused.value).endswith(
            f"a box socket path would be {SOCKET_PATH_LIMIT} bytes or more; use a shorter "
            f"socket_root")
        assert box.sock_dir is None and list(sockets.iterdir()) == []
    finally:
        shutil.rmtree(long_root, ignore_errors=True)


def test_a_short_socket_root_opens_the_turn_s_sockets(tmp_path, short_root):
    box = _box(tmp_path, short_root)
    box._open_sockets()
    try:
        assert box.sock_dir is not None
        assert all(len(str(box.sock_dir / n).encode()) < SOCKET_PATH_LIMIT
                   for n in ("handoff.sock", "egress.sock"))
    finally:
        for server in box.servers:
            server.close()


# --- The owner's Pi folder -------------------------------------------------------------------


def _inspect(box: WorkerBox, extra: dict) -> dict:
    mounts = [{"Source": s, "Destination": d, "RW": w} for s, d, w in box.mounts()]
    return {"Image": box.cfg.image, "Config": {"User": f"{os.getuid()}:{os.getgid()}"},
            "Mounts": [*mounts, extra],
            "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                           "CapDrop": ["ALL"], "CapAdd": None,
                           "SecurityOpt": ["no-new-privileges"], "PidMode": "",
                           "Devices": [], "LogConfig": {"Type": "none"}, "Init": True}}


@pytest.mark.parametrize("home", ["process", "host_home"])
def test_the_owner_s_pi_folder_is_found_under_either_home(tmp_path, short_root, monkeypatch,
                                                         home):
    host_home = tmp_path / "owner"
    box = _box(tmp_path, short_root, host_home=str(host_home))
    box.sock_dir = short_root / "s"
    base = Path.home() if home == "process" else host_home
    info = _inspect(box, {"Source": str(base / ".pi" / "agent"), "Destination": "/w/agent",
                          "RW": False})
    monkeypatch.setattr(box, "_docker", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, json.dumps([info]), ""))
    with pytest.raises(BoxError) as refused:
        box._inspect()
    assert refused.value.code == "box_not_sealed"
    assert "no_owner_pi_mount" in str(refused.value)
