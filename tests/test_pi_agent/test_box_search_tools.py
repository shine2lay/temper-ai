"""Pi's grep and find in the sealed, offline worker box (queue #47, M2-roles finding P1).

Pi 0.87.1's grep runs ripgrep (``rg``) and its find runs ``fd``. The box has neither and can't
download them, so both tools always failed. The fix: static aarch64 builds pinned by digest at
the runtime folder's top level (``/pi-runtime``, first on the box ``PATH``), made on the host by
``scripts/pi_search_tools.py`` and recorded in the box config's ``search_tools`` block.

The sealed tests (no docker, no network) check the pins, the refusals and the install script.
:func:`test_pi_grep_and_find_work_offline_in_the_box` starts a real box with Pi's own grep and
find; it is skipped unless ``TEMPER_PI_BOX_TEST_RUNTIME`` names a runtime made by the script::

    TEMPER_PI_BOX_TEST_RUNTIME=<runtime> uv run pytest \\
        tests/test_pi_agent/test_box_search_tools.py::test_pi_grep_and_find_work_offline_in_the_box \\
        -v -rs -s
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import io
import json
import os
import shutil
import socket
import stat
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from temper_ai.llm.pi_stream import Redactor
from temper_ai.pi_agent.box import BoxConfig, BoxError, WorkerBox
from temper_ai.pi_agent.rpc import RpcError
from temper_ai.pi_agent.search_tools import (
    MANIFEST,
    PINS,
    SCRIPT,
    TOOL_NEEDS,
    search_tool_problems,
)
from temper_ai.pi_agent.team_check import check_team
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_pi_agent.test_team import GOAL, RUNNABLE, members, team_box_json

REPO = Path(__file__).resolve().parents[2]
RUNTIME_ENV = "TEMPER_PI_BOX_TEST_RUNTIME"
IMAGE_ENV = "TEMPER_PI_BOX_TEST_IMAGE"
#: python:3.12-slim (arm64), the image Architecture's M2 proofs ran the box with.
DEFAULT_IMAGE = "sha256:8cee32bd74cfacf0b0abfb8c919add49c74cf48dfcb967ac0ed73669cac121c0"


@pytest.fixture
def short_root():
    # Unix socket paths must stay under ~108 bytes; pytest's tmp paths can be longer.
    root = Path(tempfile.mkdtemp(prefix="pibox-", dir="/tmp"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _box_json(root: Path, *, drop: tuple[str, ...] = (), **over) -> Path:
    """A box config over stand-in folders with stand-in rg and fd pinned, minus ``drop``."""
    path = sup.make_box_config(root, **over)
    raw = json.loads(path.read_text())
    for name in drop:
        raw["search_tools"].pop(name)
    path.write_text(json.dumps(raw))
    return path


def _refused(path: Path) -> str:
    with pytest.raises(BoxError) as caught:
        BoxConfig.load(str(path))
    assert caught.value.code == "box_config_invalid"
    return str(caught.value)


# --- the pins ---------------------------------------------------------------------------------


def test_the_pins_are_the_official_static_aarch64_releases():
    assert TOOL_NEEDS == {"grep": "rg", "find": "fd"}
    rg, fd = PINS["rg"], PINS["fd"]
    assert (rg.version, fd.version) == ("15.2.0", "10.5.0")
    assert rg.url == ("https://github.com/BurntSushi/ripgrep/releases/download/15.2.0/"
                      "ripgrep-15.2.0-aarch64-unknown-linux-musl.tar.gz")
    assert fd.url == ("https://github.com/sharkdp/fd/releases/download/v10.5.0/"
                      "fd-v10.5.0-aarch64-unknown-linux-musl.tar.gz")
    assert rg.archive_sha256 == "800b1e7206afe799dfb5a6901f23147cfaabe0e52210538100f61e86e1740915"
    assert fd.archive_sha256 == "d76c4317f7d5dba69f8a2a15856c90c777e7f0dd4e85f0de8c76de6992c374d4"
    assert all(len(pin.sha256) == 64 and pin.name == name for name, pin in PINS.items())


def test_a_box_config_with_its_binaries_as_pinned_loads(tmp_path):
    cfg = BoxConfig.load(str(_box_json(tmp_path)))
    assert sorted(cfg.search_tools) == ["fd", "rg"]
    assert cfg.search_tools["rg"].version == "15.2.0"
    assert cfg.search_tool_pin_problems() == []


def test_a_missing_pinned_binary_is_refused(tmp_path):
    path = _box_json(tmp_path)
    (tmp_path / "runtime" / "rg").unlink()
    assert "search tool rg: runtime_dir has no rg file" in _refused(path)


def test_a_changed_pinned_binary_is_refused(tmp_path):
    path = _box_json(tmp_path)
    with open(tmp_path / "runtime" / "fd", "ab") as fh:
        fh.write(b"# changed\n")
    assert "search tool fd: pinned binary changed (digest differs)" in _refused(path)


def test_a_pinned_binary_that_is_a_link_is_refused(tmp_path):
    path = _box_json(tmp_path)
    runtime = tmp_path / "runtime"
    elsewhere = tmp_path / "elsewhere-rg"
    shutil.copy2(runtime / "rg", elsewhere)  # the same bytes, so only the link is wrong
    (runtime / "rg").unlink()
    (runtime / "rg").symlink_to(elsewhere)
    assert "search tool rg: runtime_dir has no rg file (a link doesn't count)" in _refused(path)


def test_a_pinned_binary_that_is_not_executable_is_refused(tmp_path):
    path = _box_json(tmp_path)
    (tmp_path / "runtime" / "rg").chmod(0o644)
    assert "search tool rg: rg in runtime_dir is not executable" in _refused(path)


def test_a_search_tool_temper_does_not_pin_or_a_bad_digest_is_refused(tmp_path):
    path = _box_json(tmp_path)
    raw = json.loads(path.read_text())
    raw["search_tools"]["ag"] = {"version": "2.2.0", "sha256": "0" * 64}
    raw["search_tools"]["fd"]["sha256"] = "not-a-digest"
    path.write_text(json.dumps(raw))
    said = _refused(path)
    assert "search tool 'ag' is not one Temper pins (fd, rg)" in said
    assert "search tool fd: needs a version and a sha256 digest" in said


def test_search_tool_problems_names_the_missing_binary_and_the_script(tmp_path):
    cfg = BoxConfig.load(str(_box_json(tmp_path, drop=("rg", "fd"))))
    assert search_tool_problems(["read", "ls", "tldr"], cfg) == []
    said = search_tool_problems(["find", "grep", "read"], cfg)
    assert said == [
        "Pi's grep tool needs rg, which the worker box config doesn't pin (search_tools); "
        f"make a runtime with {SCRIPT} and point the box config at it",
        "Pi's find tool needs fd, which the worker box config doesn't pin (search_tools); "
        f"make a runtime with {SCRIPT} and point the box config at it"]
    pinned = BoxConfig.load(str(_box_json(tmp_path / "pinned")))
    assert search_tool_problems(["find", "grep", "read"], pinned) == []


# --- the refusal at box start: before any docker call -----------------------------------------


def _worker(tmp_path: Path, short_root: Path, tools: list[str], **over) -> WorkerBox:
    cfg = BoxConfig.load(str(_box_json(tmp_path, socket_root=str(short_root), **over)))
    box = WorkerBox(cfg, sup.spec(tmp_path / "participant", tools=tools), Redactor(),
                    owner_token=lambda _p: "", connector=lambda _host: socket.socketpair()[0])
    box.docker_calls = []

    def docker(*args, timeout=60):
        box.docker_calls.append(args)
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    box._docker = docker
    return box


@pytest.mark.parametrize(("tools", "drop", "said"), [
    (["read", "grep"], ("rg",), "Pi's grep tool needs rg"),
    (["read", "find"], ("fd",), "Pi's find tool needs fd"),
    (["grep", "find"], ("rg", "fd"), "Pi's grep tool needs rg"),
])
def test_grep_or_find_without_its_pinned_binary_is_refused_before_docker(
        tmp_path, short_root, tools, drop, said):
    box = _worker(tmp_path, short_root, tools, drop=drop)
    with pytest.raises(BoxError) as caught:
        box.start(lambda _record: None)
    assert caught.value.code == "search_tool_missing"
    assert said in str(caught.value) and SCRIPT in str(caught.value)
    assert box.docker_calls == []
    assert box.sock_dir is None and not (tmp_path / "participant" / "agent").exists()
    box.close()


def test_grep_and_find_with_rg_and_fd_pinned_go_on_to_create_the_box(tmp_path, short_root):
    box = _worker(tmp_path, short_root, ["read", "grep", "find"])
    try:
        with pytest.raises(BoxError) as caught:
            box.start(lambda _record: None)
        # The stand-in docker refuses the create: the search tools check was passed.
        assert caught.value.code == "box_create_failed"
        assert box.docker_calls[0][0] == "create"
        create = list(box.docker_calls[0])
        assert "--network" in create and create[create.index("--network") + 1] == "none"
        mounts = [a for a in create if a.startswith("type=bind")]
        runtime = str((tmp_path / "runtime").resolve())
        assert f"type=bind,source={runtime},target=/pi-runtime,readonly" in mounts
        assert "PATH=/pi-runtime:/usr/local/bin:/usr/bin:/bin" in create
    finally:
        box.close()


def test_a_tool_set_without_grep_or_find_needs_no_pins(tmp_path, short_root):
    box = _worker(tmp_path, short_root, ["read", "ls"], drop=("rg", "fd"))
    try:
        with pytest.raises(BoxError) as caught:
            box.start(lambda _record: None)
        assert caught.value.code == "box_create_failed"
    finally:
        box.close()


def test_a_binary_changed_after_the_config_loaded_is_refused_at_the_next_start(
        tmp_path, short_root):
    box = _worker(tmp_path, short_root, ["read", "grep"])
    with open(tmp_path / "runtime" / "rg", "ab") as fh:
        fh.write(b"# swapped after load\n")
    with pytest.raises(BoxError) as caught:
        box.start(lambda _record: None)
    assert caught.value.code == "search_tool_changed"
    assert "search tool rg: pinned binary changed" in str(caught.value)
    assert box.docker_calls == []
    box.close()


# --- the refusal before a run: a Pi step, a team member ---------------------------------------


def _set_box(pi, **over) -> None:
    raw = json.loads(Path(pi.box_json).read_text())
    raw.update(over)
    Path(pi.box_json).write_text(json.dumps(raw))


def test_a_pi_step_with_grep_and_find_and_no_pins_fails_before_any_worker(pi, monkeypatch):
    _set_box(pi, search_tools={})
    monkeypatch.setitem(sup.WORKFLOWS, "pi_search", lambda: [
        sup.step("brief"), sup.pi_node(tools=["Read", "Grep", "Glob"])])
    eid = sup.start(pi.client, "pi_search", pi.ws)
    assert sup.wait_ended(eid)[-1]["status"] == "failed"
    assert FakeBox.STARTS == []
    data = [str(e["data"]) for e in sup.events(eid)]
    assert any("Pi's grep tool needs rg" in d and "Pi's find tool needs fd" in d for d in data)


def test_a_pi_step_with_grep_and_find_starts_its_worker_when_rg_and_fd_are_pinned(
        pi, monkeypatch):
    monkeypatch.setitem(sup.WORKFLOWS, "pi_search", lambda: [
        sup.step("brief"), sup.pi_node(tools=["Read", "Grep", "Glob"])])
    eid = sup.start(pi.client, "pi_search", pi.ws)
    sup.open_wait(eid, "owner")
    assert {"grep", "find"} <= set(FakeBox.STARTS[0]["tools"])


def test_check_team_names_a_member_whose_grep_or_find_has_no_pinned_binary(tmp_path):
    team = members()  # frontend has Glob (Pi's find)
    team[2]["tools"] = ["Read", "Grep"]  # qa gets Pi's grep
    bare = BoxConfig.load(str(team_box_json(tmp_path / "bare", search_tools={})))
    hint = f"make a runtime with {SCRIPT} and point the box config at it"
    assert check_team(team, RUNNABLE, inputs=GOAL, box=bare) == [
        "member 'frontend': Pi's find tool needs fd, which the worker box config doesn't pin "
        f"(search_tools); {hint}",
        "member 'qa': Pi's grep tool needs rg, which the worker box config doesn't pin "
        f"(search_tools); {hint}"]
    pinned = BoxConfig.load(str(team_box_json(tmp_path / "pinned")))
    assert check_team(team, RUNNABLE, inputs=GOAL, box=pinned) == []


# --- the install script ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("pi_search_tools_script",
                                                  REPO / "scripts" / "pi_search_tools.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive(member: str, data: bytes) -> bytes:
    """A release-like .tar.gz: the binary and a README next to it."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, body, mode in ((member, data, 0o755),
                                 (member.rsplit("/", 1)[0] + "/README.md", b"read me\n", 0o644)):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(body), mode
            tar.addfile(info, io.BytesIO(body))
    return buf.getvalue()


@pytest.fixture
def release(tmp_path):
    """Stand-in releases for rg and fd, pins that match them, a fetch that serves them and
    a read-only source runtime. Every tree is made writable again afterwards."""
    binaries = {name: f"#!/bin/sh\necho {pin.version_line}\n".encode()
                for name, pin in PINS.items()}
    archives, pins = {}, {}
    for name, pin in PINS.items():
        url = f"https://example.invalid/{name}.tar.gz"
        archives[url] = _archive(pin.member, binaries[name])
        pins[name] = dataclasses.replace(pin, url=url, archive_sha256=_sha(archives[url]),
                                         sha256=_sha(binaries[name]))
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return archives[url]

    source = tmp_path / "proofs" / "runtime"
    (source / "pi" / "dist" / "bundle").mkdir(parents=True)
    (source / "node").write_bytes(b"node stand-in\n")
    (source / "node").chmod(0o755)
    (source / "pi" / "dist" / "bundle" / "cli.js").write_text("// cli\n")
    (source / "pi" / "package.json").write_text(json.dumps({"version": sup.PI_VERSION}))
    (source / "pi" / "cli-link.js").symlink_to("dist/bundle/cli.js")
    for path in sorted([source, *source.rglob("*")], reverse=True):
        if not path.is_symlink():
            path.chmod(stat.S_IMODE(path.lstat().st_mode) & ~0o222)
    root = tmp_path / "pi-runtime"
    root.mkdir(mode=0o700)
    module = SimpleNamespace(PINS=pins, MACHINE="aarch64", MANIFEST=MANIFEST)
    yield SimpleNamespace(source=source, target=root / "pi-0.87.1-rg-fd", root=root, pins=pins,
                          module=module, fetch=fetch, fetched=fetched, binaries=binaries,
                          archives=archives)
    for path in [tmp_path, *tmp_path.rglob("*")]:
        if not path.is_symlink() and path.is_dir():
            path.chmod(0o700)


def _install(script, release, **over):
    kw = {"fetch": release.fetch, "machine": "aarch64", "pins_module": release.module, **over}
    return script.install(release.source, release.target, **kw)


def test_the_script_makes_a_new_read_only_runtime_and_leaves_the_source_as_it_was(
        script, release, tmp_path):
    before = script.tree_digest(release.source)
    block = _install(script, release)

    assert block == {name: {"version": pin.version, "sha256": pin.sha256}
                     for name, pin in sorted(release.pins.items())}
    assert script.tree_digest(release.source) == before
    target = release.target
    assert sorted(p.name for p in release.root.iterdir()) == [target.name]  # no leftovers
    assert stat.S_IMODE(release.root.stat().st_mode) == 0o700  # the root is left as it was
    for name in ("rg", "fd"):
        assert (target / name).read_bytes() == release.binaries[name]
        assert stat.S_IMODE((target / name).lstat().st_mode) == 0o555
    assert sorted(p.name for p in target.iterdir()) == ["fd", "node", "pi", "rg", MANIFEST]
    assert stat.S_IMODE(target.stat().st_mode) == stat.S_IMODE(release.source.stat().st_mode)
    assert (target / "node").read_bytes() == b"node stand-in\n"
    assert os.readlink(target / "pi" / "cli-link.js") == "dist/bundle/cli.js"
    for path in [target, *target.rglob("*")]:
        if not path.is_symlink():
            assert stat.S_IMODE(path.lstat().st_mode) & 0o222 == 0, path
    manifest = json.loads((target / MANIFEST).read_text())
    assert manifest["source_runtime"] == str(release.source)
    assert manifest["source_tree_sha256"] == before
    assert manifest["pi_version"] == sup.PI_VERSION
    assert manifest["machine"] == "aarch64"
    for name, pin in release.pins.items():
        assert manifest["search_tools"][name] == {
            "version": pin.version, "version_line": pin.version_line, "url": pin.url,
            "archive_sha256": pin.archive_sha256, "member": pin.member, "sha256": pin.sha256}
    # The printed block is what a box config needs: it loads against the new runtime.
    cfg = sup.box_config(tmp_path / "box", runtime_dir=str(target), search_tools=block)
    assert cfg.search_tool_pin_problems() == []


@pytest.mark.parametrize("wrong", ["archive", "binary"])
def test_a_download_that_is_not_the_pinned_one_is_refused_and_nothing_is_written(
        script, release, wrong):
    field = "archive_sha256" if wrong == "archive" else "sha256"
    release.module.PINS = {**release.pins,
                           "rg": dataclasses.replace(release.pins["rg"], **{field: "f" * 64})}
    with pytest.raises(script.Refused) as caught:
        _install(script, release)
    said = str(caught.value)
    assert said.startswith("rg: ") and "nothing was written" in said
    assert ("archive's sha256" in said) == (wrong == "archive")
    assert list(release.root.iterdir()) == []


def test_an_existing_target_is_refused_before_any_download(script, release):
    release.target.mkdir()
    with pytest.raises(script.Refused, match="already exists; a runtime is never changed"):
        _install(script, release)
    assert release.fetched == [] and list(release.target.iterdir()) == []


def test_a_machine_that_is_not_aarch64_is_refused(script, release):
    with pytest.raises(script.Refused, match="this machine is x86_64; the pinned builds are "
                                             "aarch64 only"):
        _install(script, release, machine="x86_64")
    assert release.fetched == [] and list(release.root.iterdir()) == []


def test_a_target_whose_folder_does_not_exist_is_refused(script, release, tmp_path):
    release.target = tmp_path / "no-such-root" / "runtime"
    with pytest.raises(script.Refused, match="doesn't exist; it is not made here"):
        _install(script, release)
    assert not (tmp_path / "no-such-root").exists()


def test_the_script_prints_the_box_config_block_and_exits_1_on_a_refusal(
        script, release, capsys):
    argv = ["--from", str(release.source), "--to", str(release.target)]
    kw = {"fetch": release.fetch, "machine": "aarch64", "pins_module": release.module}
    assert script.main(argv, **kw) == 0
    out = capsys.readouterr().out
    assert (f"tree sha256 {script.tree_digest(release.source)} before and after (unchanged)"
            in out)
    printed = json.loads(out[out.index("{"):])
    assert printed == {
        "runtime_dir": str(release.target), "pi_version": sup.PI_VERSION,
        "search_tools": {name: {"version": pin.version, "sha256": pin.sha256}
                         for name, pin in sorted(release.pins.items())}}
    assert script.main(argv, **kw) == 1
    assert capsys.readouterr().err.startswith("refused: ")


def test_the_script_reads_the_same_pins_as_temper(script):
    theirs = script.load_pins()
    assert theirs.MACHINE == "aarch64" and theirs.MANIFEST == MANIFEST
    assert {n: vars(p) for n, p in theirs.PINS.items()} == {n: vars(p) for n, p in PINS.items()}


# --- the real box: Pi's own grep and find, offline ------------------------------------------

#: Runs inside the box as the container's command (through the image's python, which execs
#: node): Pi's own grep and find tools from the mounted runtime, then the version read-back.
#: Every line it prints is one JSON record (the box's stdout is read as JSON lines).
PROBE = r"""
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const say = (record) => process.stdout.write(JSON.stringify({ type: "probe", ...record }) + "\n");
const text = (result) => (result?.content ?? []).map((part) => part.text ?? "").join("\n");

async function use(name, factory, params) {
  try {
    const tools = await import(`/pi-runtime/pi/dist/core/tools/${name}.js`);
    const result = await tools[factory]("/w/workspace").execute(`probe-${name}`, params);
    say({ tool: name, ok: true, text: text(result) });
  } catch (error) {
    say({ tool: name, ok: false, error: String(error?.message ?? error) });
  }
}

await use("grep", "createGrepTool", { pattern: "lanternmoss" });
await use("find", "createFindTool", { pattern: "*.md" });
for (const binary of ["rg", "fd"]) {
  const path = (process.env.PATH ?? "").split(":").map((dir) => join(dir, binary))
    .find((candidate) => existsSync(candidate)) ?? null;
  const got = spawnSync(binary, ["--version"], { encoding: "utf8" });
  say({ binary, path, status: got.status, error: got.error ? String(got.error.message) : null,
        version_line: String(got.stdout ?? "").split("\n")[0] });
}
say({ offline: process.env.PI_OFFLINE ?? null, path_env: process.env.PATH ?? null });
say({ done: true });
"""

FIXTURE = {
    "notes/alpha.md": "The check word is lanternmoss.\n",
    "notes/delta.md": "Nothing to find in here.\n",
    "src/beta.py": "WORD = 'lanternmoss'\n",
    "src/gamma.txt": "no match here either\n",
}


@pytest.mark.skipif(not os.environ.get(RUNTIME_ENV),
                    reason=f"set {RUNTIME_ENV} to a runtime made by scripts/pi_search_tools.py "
                           "(and docker must be reachable)")
@pytest.mark.timeout(300)  # a real container: create, inspect, start, probe, remove
def test_pi_grep_and_find_work_offline_in_the_box(tmp_path, short_root):
    runtime = Path(os.environ[RUNTIME_ENV])
    image = os.environ.get(IMAGE_ENV) or DEFAULT_IMAGE
    manifest = json.loads((runtime / MANIFEST).read_text())
    block = {name: {"version": pin.version, "sha256": pin.sha256} for name, pin in PINS.items()}
    for name, pin in PINS.items():
        assert manifest["search_tools"][name]["sha256"] == pin.sha256
    cfg = sup.box_config(tmp_path / "box", runtime_dir=str(runtime), image=image,
                         search_tools=block, socket_root=str(short_root))

    pdir = tmp_path / "participant"
    for rel, body in FIXTURE.items():
        (pdir / "workspace" / rel).parent.mkdir(parents=True, exist_ok=True)
        (pdir / "workspace" / rel).write_text(body)
    (pdir / "tmp").mkdir(parents=True)
    (pdir / "tmp" / "probe.mjs").write_text(PROBE)
    box = WorkerBox(cfg, sup.spec(pdir, tools=["read", "grep", "find"]), Redactor(),
                    owner_token=lambda _p: "", connector=lambda _host: socket.socketpair()[0])
    records: list[dict] = []
    try:
        # The box's own create args, mounts and environment; only the command is the probe's.
        rpc = box.start(records.append, command=[
            "-c", "import os; os.execv('/pi-runtime/node', ['node', '/w/tmp/probe.mjs'])"])
        deadline = time.monotonic() + 120
        while not any(r.get("done") for r in records):
            try:
                rpc.next(deadline)
            except RpcError:
                break
        network = box._docker("inspect", "--format", "{{.HostConfig.NetworkMode}}",
                              box.name).stdout.strip()
        stderr = bytes(rpc.stderr_buf).decode("utf-8", "replace")
    finally:
        receipt = box.close()

    got = {r.get("tool") or r.get("binary") or ("env" if "offline" in r else "done"): r
           for r in records}
    print(f"\nruntime: {runtime}\nimage: {image}\nnetwork (docker inspect): {network}; "
          f"sealed checks passed: {sorted(k for k, ok in (box.inspected or {}).items() if ok)}")
    for name, pin in PINS.items():
        seen = got.get(name, {})
        print(f"{name} in the box: {seen.get('path')} -> {seen.get('version_line')!r} "
              f"(pinned {pin.version}, sha256 {pin.sha256})")
    for tool in ("grep", "find"):
        seen = got.get(tool, {})
        print(f"Pi's {tool}: ok={seen.get('ok')}\n{seen.get('text') or seen.get('error')}")
    print(f"PI_OFFLINE={got.get('env', {}).get('offline')} "
          f"PATH={got.get('env', {}).get('path_env')}")
    print(f"container removed: {receipt.get('container_removed')}")
    assert "done" in got, f"the probe did not finish; its stderr:\n{stderr[-4000:]}"

    assert network == "none" and box.inspected["network_none"] is True
    assert got["env"]["offline"] == "1"
    assert got["env"]["path_env"].split(":")[0] == "/pi-runtime"
    for name, pin in PINS.items():
        assert got[name]["path"] == f"/pi-runtime/{name}"
        assert got[name]["status"] == 0 and got[name]["version_line"] == pin.version_line
    assert got["grep"]["ok"], got["grep"]
    assert "notes/alpha.md" in got["grep"]["text"] and "src/beta.py" in got["grep"]["text"]
    assert "gamma" not in got["grep"]["text"] and "delta" not in got["grep"]["text"]
    assert got["find"]["ok"], got["find"]
    found = sorted(line.strip() for line in got["find"]["text"].splitlines() if line.strip())
    assert found == ["notes/alpha.md", "notes/delta.md"]
    assert receipt["container_removed"] is True
