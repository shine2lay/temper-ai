"""Final argv at fake Docker boundaries, not just the earlier mount builders."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from temper_ai.pi_agent import box as pi_box
from temper_ai.spawner import box_profile
from temper_ai.spawner.allowed_mounts import Bind, launch_binds
from temper_ai.spawner.base import SpawnerError
from tests.test_pi_agent.test_box import _box
from tests.test_pi_agent.test_box import short_root as short_root
from tests.test_spawner import test_docker_spawner as fixtures
from tests.test_spawner.box_fixtures import Install, MemoryStore


def test_allowed_launches_keep_all_four_callers_and_exec_semantics(tmp_path, short_root, monkeypatch):
    """Whole-feature opening: own workspace, E7 worktree, fixed RO, seals, probe, Pi, writer."""
    install = Install(tmp_path / "host", user="1000:1000").build()
    store = MemoryStore()
    store.add("own", workspace=str(install.run_a))
    store.add("tree", workspace=str(install.run_b))
    docker = fixtures.FakeDocker()
    spawner = fixtures._box_spawner(install, store, docker)
    template = spawner.template()
    expected = spawner.run_command("own", str(install.run_a), template)
    spawner.spawn("own")
    assert fixtures._without_profile(docker.commands("run")[-1]) == expected
    own = launch_binds(docker.commands("run")[-1])
    assert Bind(str(install.run_a), str(install.run_a), False) in own
    assert any(b.read_only for b in own)

    # A real-shaped, back-linked worktree record, within the configured workspace root.
    main = install.run_a.parent / "main"
    _link_worktree(main, install.run_b)
    spawner.spawn("tree")
    assert Bind(str(main), str(main), False) in launch_binds(docker.commands("run")[-1])

    # Sealed grants and the one-shot writer keep their existing exact shape.
    fixtures._oneshot(monkeypatch)
    sealed_workspace = install.run_a.parent / "sealed-run"
    sealed_workspace.mkdir()
    store.add("sealed", workspace=str(sealed_workspace))
    delivery = fixtures.DeliveringDocker()
    sealed = fixtures._oneshot_spawner(install, store, delivery)
    sealed.spawn("sealed")
    doc = store.record("sealed")["doc"]
    assert launch_binds(delivery.commands("run")[0]) == tuple(
        Bind(g["source"], g["target"], g["read_only"]) for g in doc["grants"])
    assert len(delivery.commands("run")) == 1
    assert len(delivery.commands("exec")) == 1
    writer = delivery.commands("exec")[0]
    assert writer[1] == "exec" and "--mount" not in writer and "--volume" not in writer

    # A named user requires the mount-free probe, whose command is not Docker options.
    template = replace(template, user="worker")
    probe = fixtures.FakeDocker(answers={"run": [(0, "1000 1000\n", "")]})
    spawner._run = probe
    assert spawner._box_ids(template, "/usr/bin/python3") == (1000, 1000)
    assert launch_binds(probe.commands("run")[0]) == ()

    # Pi's default compatibility and declared-roots configurations both keep their argv.
    monkeypatch.delenv(box_profile.BOUNDARY_ENV, raising=False)
    for roots in ([], [str(tmp_path), str(short_root)]):
        box = _box(tmp_path / ("rooted" if roots else "compat"), short_root, roots=roots)
        box.sock_dir = Path(short_root) / ("rooted" if roots else "compat")
        monkeypatch.setattr(box, "_open_sockets", lambda: None)
        monkeypatch.setattr(box, "_inspect", lambda: {})
        calls = []

        def docker_call(*args, **kwargs):
            calls.append(["docker", *args])
            return subprocess.CompletedProcess(args, 0, "created", "")

        monkeypatch.setattr(box, "_docker", docker_call)
        monkeypatch.setattr(pi_box, "Rpc", lambda *a, **k: object())
        command = ["echo", "--mount", "type=bind,source=/not-a-docker-option,target=/ignored"]
        expected = box.create_args(command)
        box.start(lambda _event: None, command, fence=lambda: True)
        assert calls == [expected]
        assert len(launch_binds(calls[0])) == len(box.mounts())
        box.rpc = None


def _link_worktree(main, workspace):
    record = main / ".git" / "worktrees" / workspace.name
    record.mkdir(parents=True)
    (workspace / ".git").write_text(f"gitdir: {record}\n")
    (record / "gitdir").write_text(f"{workspace}/.git\n")


def _insert_before_image(args, image, options):
    index = args.index(image)
    return args[:index] + options + args[index:]


def _alter_bind(args, *, destination=None, writable=False):
    altered = list(args)
    index = next(i for i, value in enumerate(args)
                 if value.startswith("type=bind,") and value.endswith(",readonly"))
    value = args[index]
    if writable:
        value = value.removesuffix(",readonly") + ",readonly=false"
    if destination:
        value = value.split("target=", 1)[0] + f"target={destination},readonly"
    altered[index] = value
    return altered


@pytest.mark.parametrize("site", ["legacy", "sealed"])
@pytest.mark.parametrize("attack", ["late", "alternate", "indirect", "malformed", "mode", "target"])
def test_spawner_final_guard_refuses_before_docker(tmp_path, monkeypatch, site, attack):
    install = Install(tmp_path / "host", user="1000:1000").build()
    store = MemoryStore()
    store.add("checked", workspace=str(install.run_a))
    docker = fixtures.FakeDocker()
    spawner = fixtures._box_spawner(install, store, docker)
    if site == "sealed":
        fixtures._sealed(monkeypatch)
    else:
        monkeypatch.setenv(box_profile.BOUNDARY_ENV, "legacy")
    template = spawner.template()
    builder_name = "run_command" if site == "legacy" else "sealed_command"
    image = template.image if site == "legacy" else template.image_id
    builder = getattr(spawner, builder_name)
    outside = tmp_path / "outside"
    outside.mkdir()

    def tampered(*args, **kwargs):
        command = builder(*args, **kwargs)
        if attack == "mode":
            return _alter_bind(command, writable=True)
        if attack == "target":
            return _alter_bind(command, destination="/different-target")
        options = {
            "late": ["--mount", f"type=bind,source={outside},target=/late"],
            "alternate": [f"--volume={outside}:/late:ro"],
            "indirect": ["--volumes-from=another-box"],
            "malformed": ["--mount=type=bind,source=/a,src=/b,target=/late"],
        }[attack]
        return _insert_before_image(command, image, options)

    monkeypatch.setattr(spawner, builder_name, tampered)
    with pytest.raises(SpawnerError, match=f"site={site}"):
        spawner.spawn("checked")
    assert docker.commands("run") == []


def test_uid_probe_final_guard_refuses_before_docker(tmp_path, monkeypatch):
    install = Install(tmp_path / "host", user="worker").build()
    store = MemoryStore()
    docker = fixtures.FakeDocker(answers={"run": [(0, "1000 1000\n", "")]})
    spawner = fixtures._box_spawner(install, store, docker)
    template = spawner.template()
    builder = spawner._uid_probe_command

    def tampered(*args):
        return _insert_before_image(builder(*args), template.image_id,
                                    ["-v", "/anywhere:/late:ro"])

    monkeypatch.setattr(spawner, "_uid_probe_command", tampered)
    with pytest.raises(SpawnerError, match="site=uid_probe"):
        spawner._box_ids(template, "/usr/bin/python3")
    assert docker.commands("run") == []
    assert spawner._box_ids_seen == {}


@pytest.mark.parametrize("attack", ["outside", "inside", "mode", "target", "indirect"])
@pytest.mark.parametrize("rooted", [True, False])
def test_pi_final_guard_refuses_before_docker(tmp_path, short_root, monkeypatch, attack, rooted):
    roots = [str(tmp_path), str(short_root)] if rooted else []
    box = _box(tmp_path, short_root, roots=roots)
    box.sock_dir = short_root / "socket"
    monkeypatch.setattr(box, "_open_sockets", lambda: None)
    monkeypatch.setattr(box, "_inspect", lambda: {})
    calls = []

    def docker_call(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "created", "")

    monkeypatch.setattr(box, "_docker", docker_call)
    monkeypatch.setattr(pi_box, "Rpc", lambda *a, **k: object())
    builder = box.create_args

    def tampered(*args):
        command = builder(*args)
        if attack == "mode":
            return _alter_bind(command, writable=True)
        if attack == "target":
            return _alter_bind(command, destination="/another-target")
        options = {
            "outside": ["--volume=/unrelated:/late"],
            "inside": ["--mount", f"type=bind,source={tmp_path}/other,target=/late"],
            "indirect": ["--volumes-from=another-box"],
        }[attack]
        return _insert_before_image(command, box.cfg.image, options)

    monkeypatch.setattr(box, "create_args", tampered)
    with pytest.raises(pi_box.BoxError) as error:
        box.start(lambda _event: None, fence=lambda: True)
    assert error.value.code in {"bind_source_outside_roots", "bind_launch_refused"}
    assert "site=pi_create" in str(error.value)
    assert calls == [] and box.created is False


@pytest.mark.parametrize("source_kind", ["workspace", "repository"])
@pytest.mark.parametrize("attack", ["target", "mode", "neighbour"])
def test_legacy_dynamic_roots_keep_target_mode_and_git_selection(
    tmp_path, monkeypatch, source_kind, attack,
):
    install = Install(tmp_path / "host", user="1000:1000").build()
    main = install.run_a.parent / "main"
    _link_worktree(main, install.run_a)
    store = MemoryStore()
    store.add("checked", workspace=str(install.run_a))
    docker = fixtures.FakeDocker()
    spawner = fixtures._box_spawner(install, store, docker)
    builder = spawner.run_command
    source = install.run_a if source_kind == "workspace" else main
    template = spawner.template()

    def tampered(*args, **kwargs):
        command = builder(*args, **kwargs)
        if attack == "neighbour":
            return _insert_before_image(command, template.image,
                                        ["-v", f"{install.run_b}:{install.run_b}"])
        original = f"type=bind,source={source},target={source}"
        index = command.index(original)
        command[index] = (original + ",readonly" if attack == "mode" else
                          f"type=bind,source={source},target=/another-target")
        return command

    monkeypatch.setattr(spawner, "run_command", tampered)
    with pytest.raises(SpawnerError, match="site=legacy"):
        spawner.spawn("checked")
    assert docker.commands("run") == []


@pytest.mark.parametrize("attack", ["outside", "sibling", "symlink", "outside-alias", "missing"])
def test_legacy_workspace_requires_its_own_independent_root(tmp_path, monkeypatch, attack):
    install = Install(tmp_path / "host", user="1000:1000").build()
    original = install.run_a
    # Keep the template's declaration unchanged while replacing the row's request.
    if attack == "missing":
        workspace = original
        install.extra_env = [entry for entry in install.extra_env
                             if not entry.startswith("WORKSPACE_DIR=")]
    elif attack == "sibling":
        workspace = original.parent.with_name(original.parent.name + "-sibling") / "run"
        workspace.mkdir(parents=True)
    elif attack == "outside-alias":
        workspace = tmp_path / "outside-alias"
        workspace.symlink_to(original)
    elif attack == "symlink":
        outside = tmp_path / "outside"
        outside.mkdir()
        workspace = original.parent / "link"
        workspace.symlink_to(outside)
    else:
        workspace = tmp_path / "outside"
        workspace.mkdir()
    store = MemoryStore()
    store.add("checked", workspace=str(workspace))
    docker = fixtures.FakeDocker()
    spawner = fixtures._box_spawner(install, store, docker)
    if attack == "missing":
        template = spawner.template()
        template = replace(template, env=[e for e in template.env
                                          if not e.startswith("WORKSPACE_DIR=")])
        monkeypatch.setattr(spawner, "template", lambda: template)
    with pytest.raises(SpawnerError, match="site=legacy"):
        spawner.spawn("checked")
    assert docker.commands("run") == []
