"""Parsing, permission and host-namespace cases for the shared final bind check."""

from __future__ import annotations

from pathlib import Path

import pytest

from temper_ai.spawner.allowed_mounts import (
    Bind,
    MountPolicy,
    MountRefused,
    RootBind,
    check_launch,
    inside_roots,
    launch_binds,
)
from temper_ai.spawner.box_seal import WorkerView


@pytest.mark.parametrize("option", [
    ["--mount", "type=bind,source=/repo,target=/code,readonly"],
    ["--mount=type=bind,src=/repo,dst=/code,ro=true"],
    ["--mount", "type=bind,source=/repo,destination=/code,readonly=1,bind-propagation=rprivate"],
    ["-v", "/repo:/code:ro"], ["--volume", "/repo:/code:ro"],
    ["--volume=/repo:/code:ro"], ["-v=/repo:/code:ro"], ["-v/repo:/code:ro,rprivate"],
])
def test_bind_spellings_preserve_the_exact_fixed_declaration(option):
    bind = Bind("/repo", "/code", True)
    args = ["docker", "create", "--env", "--mount", "--label=lookalike=-v/x:/y",
            *option, "--", "image", "--mount", "type=bind,source=/private,target=/not-a-bind"]
    assert launch_binds(args) == (bind,)
    check_launch(args, MountPolicy(fixed=(bind,)), site="syntax")


@pytest.mark.parametrize("options", [
    [], ["--tmpfs", "/tmp:mode=1777"], ["--tmpfs=/tmp:mode=1777,size=1m"],
    ["--mount=type=tmpfs,target=/tmp,tmpfs-mode=1777,tmpfs-size=1024"],
    ["--tmpfs=/boot:rw,noexec,nosuid,nodev,size=1048576,mode=0700,uid=1000,gid=1000"],
    ["-v", "/anonymous"], ["--mount=type=volume,target=/anonymous"],
    ["-it", "--rm=true", "--read-only", "--env", "VALUE=--volume=/x:/y"],
])
def test_no_host_bind_forms_and_command_lookalikes_are_clean(options):
    args = ["docker", "run", *options, "image", "--volumes-from=not-docker",
            "--mount", "malformed command text", "-v/x:/y"]
    assert launch_binds(args) == ()
    check_launch(args, MountPolicy(), site="mount_free")


@pytest.mark.parametrize("options,category", [
    (["--mount"], "unreadable_arguments"),
    (["--mount="], "unreadable_arguments"),
    (["--volume", "named:/target"], "indirect_host_mount"),
    (["--volumes-from", "other-box"], "indirect_host_mount"),
    (["--volumes-from=other-box:ro"], "indirect_host_mount"),
    (["--volume-driver=local"], "indirect_host_mount"),
    (["--device=/dev/sda"], "indirect_host_mount"),
    (["--privileged"], "indirect_host_mount"),
    (["--mount=type=volume,source=named,target=/target"], "indirect_host_mount"),
    (["--mount=type=volume,target=/target,volume-driver=local"], "indirect_host_mount"),
    (["--mount=type=unknown,target=/target"], "unsupported_mount"),
    (["--mount=type=bind,source=/src,target=/target,bind-propagation=rshared"], "permission_widening"),
    (["--mount=type=bind,source=/src,target=/target,readonly=false,ro"], "malformed_mount"),
    (["--mount=type=bind,source=/src,src=/other,target=/target"], "malformed_mount"),
    (["--mount=type=bind,source=/src,target=/target,readonly=yes"], "malformed_mount"),
    (["--mount=type=bind,source=relative,target=/target"], "malformed_mount"),
    (["--mount=type=bind,source=/src/../private,target=/target"], "malformed_mount"),
    (["--mount=type=bind,source=/src,target=relative"], "malformed_mount"),
    (["--mount=type=bind,source=/src,target=//target"], "malformed_mount"),
    (["--mount=type=bind,source=/src,target=/target,"], "malformed_mount"),
    (["--mount=type=bind,\"source=/src\",target=/target"], "malformed_mount"),
    (["--mount=type=bind,source=/src,target=/target,bind-recursive=disabled"], "unsupported_mount"),
    (["--mount=type=tmpfs,source=/src,target=/target"], "unsupported_mount"),
    (["-v/src:/target:ro,rw"], "malformed_mount"),
    (["-v/src:/target:z"], "unsupported_mount"),
    (["-v/src:/target:ro:extra"], "malformed_mount"),
    (["--future-option", "anything"], "unreadable_arguments"),
    (["--rm=maybe"], "unreadable_arguments"),
    (["--tmpfs=/tmp:bind"], "unsupported_mount"),
    (["--tmpfs=relative"], "malformed_mount"),
    (["--tmpfs=/tmp:rw,ro"], "malformed_mount"),
    (["--tmpfs=/tmp:exec,noexec"], "malformed_mount"),
    (["--tmpfs=/tmp:mode=777,mode=777"], "malformed_mount"),
    (["--tmpfs=/tmp:"], "malformed_mount"),
    (["--mount=type=tmpfs,target=/tmp,tmpfs-size=unreadable"], "unsupported_mount"),
    (["--mount=type=tmpfs,target=/tmp,tmpfs-mode=888"], "unsupported_mount"),
])
def test_unreadable_and_indirect_forms_refuse_without_payloads(options, category):
    # Missing-value cases really end at the missing value, not an image used as that value.
    args = ["docker", "run", *options]
    if options != ["--mount"]:
        args += ["image"]
    with pytest.raises(MountRefused) as error:
        check_launch(args, MountPolicy(), site="syntax")
    assert error.value.category == category
    assert str(error.value) == f"container bind refused: site=syntax category={category}"


@pytest.mark.parametrize("argv", [
    ["docker", "exec", "existing", "echo"], ["docker", "run"],
    ["docker", "create", "--rm"], ["docker", "run", "--"],
    ["docker", "run", "--", "image\x00"], ["docker", "run", 123],
    ["docker", "run", "--env", None, "image"],
])
def test_missing_launch_or_image_is_not_a_clean_parse(argv):
    with pytest.raises(MountRefused):
        check_launch(argv, MountPolicy(), site="syntax")


def test_roots_are_not_target_access_or_fixed_descendant_authority(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    fixed = Bind(str(repo), "/repo", True)
    policy = MountPolicy(fixed=(fixed,), rooted=(RootBind((str(tmp_path),), lambda _b: True),))
    original = f"type=bind,source={repo},target=/repo,readonly"
    check_launch(["docker", "run", "--mount", original, "image"], policy, site="scope")
    for changed in (
        f"type=bind,source={repo},target=/repo,readonly=false",
        f"type=bind,source={repo},target=/elsewhere,readonly",
    ):
        with pytest.raises(MountRefused, match="permission_widening"):
            check_launch(["docker", "run", "--mount", changed, "image"], policy, site="scope")
    for src in (repo / ".git", repo / "nested"):
        with pytest.raises(MountRefused, match="permission_widening"):
            check_launch(["docker", "run", "--mount", original, "-v", f"{src}:/write", "image"],
                         policy, site="scope")
    with pytest.raises(MountRefused, match="missing_declared_bind"):
        check_launch(["docker", "run", "image"], policy, site="scope")
    for extra in (["--mount", original], ["-v", "/repo"], ["--tmpfs", "/repo:rw"]):
        with pytest.raises(MountRefused, match="ambiguous_mounts"):
            check_launch(["docker", "run", "--mount", original, *extra, "image"],
                         policy, site="scope")
    # A different writable source must not shadow a fixed read-only destination either.
    with pytest.raises(MountRefused, match="permission_widening"):
        check_launch(["docker", "run", "--mount", original,
                      "-v", f"{tmp_path}/other:/repo/.git", "image"], policy, site="scope")


def test_source_roots_reject_outside_sibling_symlink_and_missing_declarations(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside)
    rule = RootBind((str(root),), lambda b: b.source == b.target and not b.read_only)
    policy = MountPolicy(rooted=(rule,))
    for source in (root, root / "child"):
        check_launch(["docker", "run", "-v", f"{source}:{source}", "image"], policy, site="roots")
    for source in (outside, tmp_path / "root-sibling", root / "escape" / "child"):
        with pytest.raises(MountRefused, match="undeclared_bind"):
            check_launch(["docker", "run", "-v", f"{source}:{source}", "image"], policy, site="roots")
    for bind in (f"{root}:/different-target", f"{root}:{root}:ro"):
        with pytest.raises(MountRefused, match="undeclared_bind"):
            check_launch(["docker", "run", "-v", bind, "image"], policy, site="roots")
    with pytest.raises(MountRefused, match="undeclared_bind"):
        check_launch(["docker", "run", "-v", f"{root}:{root}", "image"], MountPolicy(), site="none")
    assert not inside_roots("relative", [str(root)])
    assert not inside_roots(str(root), [])


def test_fixed_declarations_still_require_configured_source_roots(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "link"
    link.symlink_to(outside)
    for source in (outside, link):
        fixed = Bind(str(source), "/fixed", True)
        with pytest.raises(MountRefused, match="source_outside_roots"):
            check_launch(["docker", "run", "-v", f"{source}:/fixed:ro", "image"],
                         MountPolicy(fixed=(fixed,), source_roots=(str(root),)), site="rooted_fixed")


def test_host_links_are_interpreted_in_host_namespace_not_worker_namespace(tmp_path):
    worker = tmp_path / "worker"
    other = tmp_path / "other"
    worker.mkdir()
    other.mkdir()
    (worker / "plain").mkdir()
    (other / "private").mkdir()
    (other / "child").mkdir()
    view = WorkerView([("/host/root", str(worker)), ("/host/other", str(other))])
    (worker / "relative").symlink_to("plain")
    (worker / "host-absolute").symlink_to("/host/root/plain")
    (worker / "escape").symlink_to("/host/other/private")
    (worker / "worker-only").symlink_to(str(worker / "plain"))
    (worker / "hop").symlink_to("/host/other/child")
    (worker / "parent-traversal").symlink_to("hop/../private")
    (worker / "loop").symlink_to("loop")
    (worker / "file").write_text("not a directory")
    (worker / "bad-parent").symlink_to("file/../plain")
    (worker / "unmapped-parent").symlink_to("../unmapped/file")
    (worker / "unmapped-end").symlink_to("..")
    assert view.canonical_host_path("/host/root/relative") == "/host/root/plain"
    assert view.canonical_host_path("/host/root/host-absolute") == "/host/root/plain"
    assert inside_roots("/host/root/relative", ["/host/root"], resolve=view.canonical_host_path)
    assert not inside_roots("/host/root/escape", ["/host/root"], resolve=view.canonical_host_path)
    assert view.canonical_host_path("/host/root/parent-traversal") == "/host/other/private"
    assert not inside_roots("/host/root/parent-traversal", ["/host/root"],
                            resolve=view.canonical_host_path)
    # Local realpath would wrongly bless this absolute worker alias as inside its local root.
    assert Path(worker / "worker-only").resolve().is_relative_to(worker)
    policy = MountPolicy(rooted=(RootBind(("/host/root",), lambda _b: True,
                                         view.canonical_host_path),))
    for source in ("/host/root/worker-only", "/host/root/missing", "/invisible",
                   "/host/root/loop", "/host/root/bad-parent",
                   "/host/root/unmapped-parent", "/host/root/unmapped-end"):
        with pytest.raises(MountRefused, match="unreadable_host_path"):
            check_launch(["docker", "run", "-v", f"{source}:/target", "image"], policy, site="mapped")
    # A nested worker mount is not evidence about the hidden host directory.
    shadow = WorkerView([("/host/root", str(worker)), ("/elsewhere", str(worker / "plain"))])
    with pytest.raises(ValueError, match="shadowed"):
        shadow.canonical_host_path("/host/root/plain")
    alias = tmp_path / "alias"
    alias.symlink_to(worker)
    with pytest.raises(ValueError, match="anchor"):
        WorkerView([("/host/root", str(alias))]).canonical_host_path("/host/root")
    assert WorkerView([("/", str(worker))]).canonical_host_path("/plain") == "/plain"
    file_anchor = WorkerView([("/host/root/file", str(worker / "file")),
                              ("/host/root", str(worker))])
    with pytest.raises(ValueError, match="non-directory anchor"):
        file_anchor.canonical_host_path("/host/root/file/../plain")
    with pytest.raises(OSError):
        WorkerView([("/host/missing", str(worker / "missing"))]).canonical_host_path("/host/missing")
