"""The Pi pins and their model-free check (queue #53; M4 ADR-M4-04, SW-24, SW-26, SW-29, SW-50;
temper_ai/pi_agent/pins.py and scripts/pi_pins_check.py, which runs it on the host).

A box config pinning every part, over stand-in folders, with Docker a stand-in: the check
passes. One changed byte, a pin for a refused add-on, a default add-on without a pin or a pin
the box config doesn't record is a mismatch; no box config is "not set up"; a check that can't
run (or runs out of time) is an error. The report holds pin names and digests only. No Docker,
no network, no model.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from temper_ai.pi_agent import box, member, pins, turn
from tests.test_pi_agent import support as sup

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "pi_pins_check.py"
NAMES = ["image", "image_tag", "image_tar", "runtime", "pi_version", "search_tool:fd",
         "search_tool:rg", "add_ons", "add_on:pi-image-trim", "add_on:pi-tldr",
         "identity_extension", "identity_settings"]


class FakeDocker:
    """``docker image inspect --format {{.Id}} <ref>``, answered as Docker does."""

    def __init__(self, images: dict[str, str]) -> None:
        self.images = images
        self.asked: list[tuple[str, ...]] = []

    def __call__(self, *args: str, timeout: float = 0) -> SimpleNamespace:
        self.asked.append(args)
        assert args[:4] == ("image", "inspect", "--format", "{{.Id}}") and 0 < timeout <= 20
        if args[4] in self.images:
            return SimpleNamespace(returncode=0, stdout=self.images[args[4]] + "\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="",
                               stderr=f"Error response from daemon: No such image: {args[4]}\n")


@pytest.fixture
def pinned(tmp_path):
    """A box config with every pin over stand-in folders, and Docker holding its image."""
    path = sup.make_box_config(tmp_path / "box")
    raw = sup.pin_everything(path, tmp_path / "pins")
    docker = FakeDocker({sup.IMAGE: sup.IMAGE, sup.IMAGE_TAG: sup.IMAGE})

    def rewrite(**changes):
        data = json.loads(path.read_text())
        data.update(changes)
        path.write_text(json.dumps(data))

    return SimpleNamespace(path=path, raw=raw, docker=docker, tmp=tmp_path, rewrite=rewrite,
                           check=lambda **kw: pins.check_pins(path, docker=docker, **kw))


def by_name(result: dict) -> dict[str, dict]:
    return {p["name"]: p for p in result["pins"]}


# --- the add-on lists (SW-29) ------------------------------------------------------------------


def test_the_default_allowed_proved_and_box_tested_add_ons_are_the_same_two():
    """billion-context-pi stays out: refused by name, never pinned or loaded."""
    assert pins.DEFAULT_ADD_ONS == ("pi-image-trim", "pi-tldr")
    assert tuple(sorted(member.ADD_ONS)) == pins.DEFAULT_ADD_ONS
    assert tuple(sorted(turn.ADD_ON_PROOFS)) == pins.DEFAULT_ADD_ONS
    assert sup.ADD_ON_NAMES == pins.DEFAULT_ADD_ONS
    assert member.add_on_names({}) == list(pins.DEFAULT_ADD_ONS)
    assert "billion-context-pi" in member.REFUSED_ADD_ONS
    assert not set(member.REFUSED_ADD_ONS) & set(pins.DEFAULT_ADD_ONS)


# --- pass -------------------------------------------------------------------------------------


def test_a_box_config_pinning_every_part_passes(pinned):
    result = pinned.check()
    assert result["result"] == pins.PASS and "error" not in result
    assert [p["name"] for p in result["pins"]] == NAMES
    assert all(p["ok"] and p["want"] == p["have"] for p in result["pins"])
    got = by_name(result)
    assert got["image"]["have"] == got["image_tag"]["have"] == sup.IMAGE
    assert got["pi_version"]["have"] == sup.PI_VERSION
    assert got["add_ons"]["have"] == ["pi-image-trim", "pi-tldr"]
    assert got["identity_settings"]["have"] == pinned.raw["identity_config_sha256"]
    assert pinned.docker.asked == [("image", "inspect", "--format", "{{.Id}}", sup.IMAGE),
                                   ("image", "inspect", "--format", "{{.Id}}", sup.IMAGE_TAG)]
    assert pins.exit_code(result) == 0


def test_a_route_s_login_extension_and_catalog_are_pinned_too(pinned):
    ext = pinned.tmp / "auth"
    (ext / "src").mkdir(parents=True)
    (ext / "src" / "index.ts").write_text("export default function () {}\n")
    catalog = pinned.tmp / "models.json"
    catalog.write_text("{}\n")
    pinned.rewrite(routes={"anthropic": {
        "provider": "anthropic", "host": "api.anthropic.com", "extension": str(ext),
        "extension_entry": "src/index.ts", "extension_sha256": pins.tree_sha256(ext),
        "catalog": str(catalog), "catalog_sha256": pins.file_sha256(catalog)}})
    result = pinned.check()
    assert result["result"] == pins.PASS
    assert [p["name"] for p in result["pins"]][-2:] == ["route:anthropic",
                                                        "route:anthropic:catalog"]
    (ext / "src" / "index.ts").write_text("export default function () { return 1 }\n")
    assert pins.failed(pinned.check()) == ["route:anthropic"]


# --- mismatch ---------------------------------------------------------------------------------


@pytest.mark.parametrize("where,name", [
    ("runtime/pi/dist/bundle/cli.js", "runtime"),
    ("runtime/rg", "search_tool:rg"),
    ("pins/addons/pi-tldr/index.ts", "add_on:pi-tldr"),
    ("box/identity-ext/index.ts", "identity_extension"),
    ("box/identity-config/pi-identity.json", "identity_settings"),
    ("pins/image.tar", "image_tar"),
])
def test_one_changed_byte_is_a_mismatch_naming_that_pin(pinned, where, name):
    path = pinned.tmp / ("box/" + where if where.startswith("runtime") else where)
    data = path.read_bytes()
    path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    result = pinned.check()
    expected = [name] if name != "search_tool:rg" else ["runtime", "search_tool:rg"]
    assert (result["result"], pins.failed(result)) == (pins.MISMATCH, expected)
    assert pins.exit_code(result) == 1


def test_a_pin_for_a_refused_add_on_is_a_mismatch(pinned):
    """billion-context-pi, pinned with its own true digest, is still a mismatch (SW-29)."""
    add_ons = sup.make_add_ons(pinned.tmp / "pins", ("billion-context-pi",))
    pinned.rewrite(add_ons={**pinned.raw["add_ons"], **add_ons})
    result = pinned.check()
    assert pins.failed(result) == ["add_ons", "add_on:billion-context-pi"]
    got = by_name(result)
    assert got["add_ons"]["have"] == ["billion-context-pi", "pi-image-trim", "pi-tldr"]
    assert got["add_on:billion-context-pi"]["want"] is None
    assert got["add_on:billion-context-pi"]["have"] == add_ons["billion-context-pi"]["sha256"]


def test_a_default_add_on_without_a_pin_is_a_mismatch(pinned):
    pinned.rewrite(add_ons={"pi-image-trim": pinned.raw["add_ons"]["pi-image-trim"]})
    result = pinned.check()
    assert pins.failed(result) == ["add_ons", "add_on:pi-tldr"]
    assert by_name(result)["add_on:pi-tldr"] == {"name": "add_on:pi-tldr", "want": None,
                                                 "have": None, "ok": False}


@pytest.mark.parametrize("key,name", [
    ("runtime_sha256", "runtime"), ("image_tar_sha256", "image_tar"),
    ("identity_extension_sha256", "identity_extension"),
    ("identity_config_sha256", "identity_settings"), ("image_tag", "image_tag"),
    ("pi_version", "pi_version"),
])
def test_a_pin_the_box_config_doesn_t_record_is_a_mismatch(pinned, key, name):
    pinned.rewrite(**{key: ""})
    result = pinned.check()
    assert pins.failed(result) == [name]
    assert by_name(result)[name]["want"] is None


def test_search_tools_must_both_be_pinned_and_nothing_else(pinned):
    tools = dict(pinned.raw["search_tools"])
    del tools["fd"]
    tools["grep"] = {"version": "3.11", "sha256": "f" * 64}
    pinned.rewrite(search_tools=tools)
    assert pins.failed(pinned.check()) == ["search_tool:fd", "search_tool:grep"]


def test_an_image_docker_doesn_t_have_is_a_mismatch(pinned):
    pinned.docker.images.clear()
    result = pinned.check()
    assert pins.failed(result) == ["image", "image_tag"]
    assert by_name(result)["image"]["have"] is None


def test_a_tag_naming_another_image_is_a_mismatch(pinned):
    """A tag moved to another image no longer keeps the pinned one from a prune."""
    pinned.docker.images[sup.IMAGE_TAG] = "sha256:" + "1" * 64
    assert pins.failed(pinned.check()) == ["image_tag"]


def test_the_pi_version_is_the_one_the_runtime_s_own_pi_prints_offline(pinned, monkeypatch):
    """Run in an empty environment: nothing of this process's (keys included) reaches it."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-for-pi")
    node = pinned.tmp / "box" / "runtime" / "node"
    node.write_text('#!/bin/sh\n[ -z "$ANTHROPIC_API_KEY" ] && [ "$HOME" = /nonexistent ] && '
                    '[ "$PI_OFFLINE$PI_SKIP_VERSION_CHECK" = 11 ] && [ "$(pwd)" = / ] && '
                    f'[ "$2 $3" = "--offline --version" ] && echo {sup.PI_VERSION}\n')
    pinned.rewrite(runtime_sha256=pins.full_tree_sha256(node.parent))
    assert pinned.check()["result"] == pins.PASS
    node.write_text("#!/bin/sh\necho 0.88.0\n")
    pinned.rewrite(runtime_sha256=pins.full_tree_sha256(node.parent))
    result = pinned.check()
    assert pins.failed(result) == ["pi_version"]
    assert by_name(result)["pi_version"]["have"] == "0.88.0"


# --- not set up, error ------------------------------------------------------------------------


@pytest.mark.parametrize("path", [None, "", "/nonexistent/pi-box.json"])
def test_no_box_config_is_not_set_up(path):
    result = pins.check_pins(path, docker=FakeDocker({}))
    assert result == {"result": pins.NOT_SET_UP, "pins": [],
                      "error": "there is no private box config yet"}
    assert pins.exit_code(result) == 3


@pytest.mark.parametrize("text,error", [
    ("{not json", "the box config could not be read (JSONDecodeError)"),
    ("[1, 2]", "the box config is not a JSON object"),
])
def test_a_box_config_that_can_t_be_read_is_an_error(tmp_path, text, error):
    path = tmp_path / "pi-box.json"
    path.write_text(text)
    result = pins.check_pins(path, docker=FakeDocker({}))
    assert result == {"result": pins.ERROR, "pins": [], "error": error}
    assert pins.exit_code(result) == 2


@pytest.mark.parametrize("answer,error", [
    (SimpleNamespace(returncode=1, stdout="", stderr="Cannot connect to the Docker daemon at "
                     "unix:///var/run/docker.sock: no such file or directory\n"),
     "Docker didn't answer (is the daemon up, and its socket reachable?)"),
    (subprocess.TimeoutExpired("docker", 20), "Docker did not answer in time"),
    (FileNotFoundError("docker"), "Docker could not be asked (FileNotFoundError)"),
])
def test_docker_not_answering_is_an_error_not_a_missing_image(pinned, answer, error):
    def docker(*args, timeout=0):
        if isinstance(answer, Exception):
            raise answer
        return answer

    result = pins.check_pins(pinned.path, docker=docker)
    assert (result["result"], result["error"], result["pins"]) == (pins.ERROR, error, [])


def test_the_time_limit_spent_is_an_error(pinned):
    now = [0.0]

    def clock():
        now[0] += 7.0  # every look at the clock, 7 s more
        return now[0]

    result = pinned.check(clock=clock)
    assert result["result"] == pins.ERROR
    assert result["error"] == "the pin check took longer than 60 s"


# --- what the report says ---------------------------------------------------------------------


def test_the_report_holds_pin_names_and_digests_only(pinned):
    """No path, no file name, no environment: temper-ci's live check publishes it."""
    elsewhere = pinned.tmp / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "index.ts").write_text("// not an add-on\n")
    pinned.rewrite(add_ons={**pinned.raw["add_ons"],
                            "../../etc": {"dir": str(elsewhere), "entry": "index.ts",
                                          "sha256": "0" * 64}})
    result = pinned.check()
    text = json.dumps(result)
    assert str(pinned.tmp) not in text and "etc" not in text and "image.tar" not in text
    for p in result["pins"]:
        assert set(p) == {"name", "want", "have", "ok"}
        for value in (p["want"], p["have"]):
            assert value is None or isinstance(value, list) or pins.SHA256_RE.match(value) \
                or pins.IMAGE_RE.match(value) or pins.VERSION_RE.match(value)
    assert "add_on:(not a plain name)" in [p["name"] for p in result["pins"]]


def test_the_check_writes_nothing(pinned):
    before = sorted((str(p), p.stat().st_mtime_ns) for p in pinned.tmp.rglob("*"))
    assert pinned.check()["result"] == pins.PASS
    assert sorted((str(p), p.stat().st_mtime_ns) for p in pinned.tmp.rglob("*")) == before


# --- the digests -------------------------------------------------------------------------------


def test_the_folder_digest_is_the_one_every_pin_was_taken_with(tmp_path):
    """Regular files' paths and contents; node_modules and links left out. The pinned
    digests in the private box config were taken with it: it must not change."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_bytes(b"one\n")
    (tmp_path / "sub" / "b.txt").write_bytes(b"two\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_bytes(b"left out\n")
    os.symlink("a.txt", tmp_path / "link")
    assert pins.tree_sha256(tmp_path) == (
        "d2ba69df7be34aa8c8d234f09d9d7330dcff18b31d7bf87fc69b4096644dc0f8")
    assert box.tree_sha256 is pins.tree_sha256 and box.file_sha256 is pins.file_sha256


def test_the_runtime_digest_is_the_one_its_install_script_prints(tmp_path):
    """scripts/pi_search_tools.py digests the runtime it builds the same way."""
    spec = importlib.util.spec_from_file_location("_pi_search_tools_for_pins",
                                                  REPO / "scripts" / "pi_search_tools.py")
    script = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = script
    try:
        spec.loader.exec_module(script)
        runtime = tmp_path / "runtime"
        (runtime / "pi" / "node_modules" / ".bin").mkdir(parents=True)
        (runtime / "node").write_bytes(b"\x7fELF stand-in")
        (runtime / "node").chmod(0o755)
        (runtime / "pi" / "node_modules" / "x.js").write_text("x\n")
        os.symlink("../x.js", runtime / "pi" / "node_modules" / ".bin" / "x")
        digest = pins.full_tree_sha256(runtime)
        assert digest == script.tree_digest(runtime)
        (runtime / "node").chmod(0o700)
        assert pins.full_tree_sha256(runtime) != digest
    finally:
        sys.modules.pop(spec.name, None)


# --- the host script ---------------------------------------------------------------------------


def run_script(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """The script as temper-ci runs it: plain python3, no temper package on its path (-I)."""
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], cwd=cwd,
                          capture_output=True, text=True, timeout=60, check=False)


def test_the_host_script_needs_no_temper_package_and_says_not_set_up(tmp_path):
    got = run_script("--json", "--config", str(tmp_path / "pi-box.json"), cwd=tmp_path)
    assert got.returncode == 3, got.stderr
    assert json.loads(got.stdout) == {"result": "not_set_up", "pins": [],
                                      "error": "there is no private box config yet"}


def test_the_host_script_s_default_box_config_is_the_private_one():
    spec = importlib.util.spec_from_file_location("_pi_pins_check_default", SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.DEFAULT_CONFIG == REPO / "local" / "pi" / "pi-box.json"


def test_the_host_script_says_error_for_a_box_config_it_can_t_read(tmp_path):
    (tmp_path / "pi-box.json").write_text("{not json")
    got = run_script("--json", "--config", "pi-box.json", cwd=tmp_path)
    assert got.returncode == 2
    assert json.loads(got.stdout)["error"] == "the box config could not be read (JSONDecodeError)"
    plain = run_script("--config", "pi-box.json", cwd=tmp_path)
    assert (plain.returncode, plain.stdout) == (
        2, "pin check: error: the box config could not be read (JSONDecodeError)\n")


@pytest.fixture
def script(monkeypatch):
    """The host script in this process, its pins module answering Docker with a stand-in."""
    spec = importlib.util.spec_from_file_location("_pi_pins_check_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    loaded = module.load_pins()
    docker = FakeDocker({sup.IMAGE: sup.IMAGE, sup.IMAGE_TAG: sup.IMAGE})
    monkeypatch.setattr(loaded, "docker_cli", docker)
    monkeypatch.setattr(module, "load_pins", lambda: loaded)
    yield SimpleNamespace(main=module.main, module=module, pins=loaded, docker=docker)
    sys.modules.pop(spec.name, None)
    sys.modules.pop("_temper_pi_pins", None)


def test_the_host_script_passes_and_fails_with_its_exit_codes(script, tmp_path, capsys):
    path = sup.make_box_config(tmp_path / "box")
    sup.pin_everything(path, tmp_path / "pins")
    assert script.main(["--json", "--config", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["result"] == "pass" and [p["name"] for p in result["pins"]] == NAMES
    tar = tmp_path / "pins" / "image.tar"
    tar.write_bytes(tar.read_bytes() + b"!")
    assert script.main(["--config", str(path)]) == 1
    out = capsys.readouterr().out
    assert out.startswith("pin check: mismatch (1 of 12 pins)\n  image_tar: want ")
    assert str(tmp_path) not in out


def test_the_host_script_stops_a_check_that_outlasts_its_limit(script, monkeypatch, capsys,
                                                               tmp_path):
    """The alarm behind the check's own clock: past it, an error, whatever the check is on."""
    monkeypatch.setattr(script.pins, "LIMIT_S", 0.0)
    monkeypatch.setattr(script.module, "BACKSTOP_S", 1)
    monkeypatch.setattr(script.pins, "check_pins", lambda path: time.sleep(5))
    started = time.monotonic()
    assert script.main(["--json", "--config", str(tmp_path / "pi-box.json")]) == 2
    assert time.monotonic() - started < 4
    assert json.loads(capsys.readouterr().out) == {
        "result": "error", "pins": [], "error": "the pin check took longer than 0 s"}
