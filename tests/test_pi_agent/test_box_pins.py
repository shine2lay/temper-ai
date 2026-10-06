"""The pins a worker box reads back itself (queue #53; M2-roles D3, SW-26): the identity
extension, the shared identity settings and the member's route login extension and catalog
are checked at load and read back before every start, and a start is refused, before any
docker call, when one no longer has the digest the box config pins. The pins' form is checked
at load. The runtime, the image and the add-ons are the pin check's (test_pins.py) and the
add-ons' own checks. No Docker, no network, no model."""

from __future__ import annotations

import json
import shutil
import socket
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from temper_ai.llm.pi_stream import Redactor
from temper_ai.pi_agent import pins, turn
from temper_ai.pi_agent.box import BoxConfig, BoxError, WorkerBox
from tests.test_pi_agent import support as sup


@pytest.fixture
def short_root():
    # Unix socket paths must stay under ~108 bytes; pytest's tmp paths can be longer.
    root = Path(tempfile.mkdtemp(prefix="pibox-", dir="/tmp"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _login(folder: Path) -> str:
    (folder / "src").mkdir(parents=True)
    (folder / "src" / "index.ts").write_text("export default function () {}\n")
    return str(folder)


def _pinned(tmp_path: Path, short_root: Path) -> tuple[Path, dict]:
    """Every pin over stand-in folders; the member's route and another one with a login."""
    catalog = tmp_path / "models-store.json"
    catalog.write_text("{}\n")
    routes = {
        "openai-codex": {"provider": "openai-codex", "host": "chatgpt.com",
                         "extension": _login(tmp_path / "login"),
                         "extension_entry": "src/index.ts", "catalog": str(catalog)},
        "anthropic": {"provider": "anthropic", "host": "api.anthropic.com",
                      "extension": _login(tmp_path / "other-login"),
                      "extension_entry": "src/index.ts"},
    }
    path = sup.make_box_config(tmp_path, socket_root=str(short_root), routes=routes)
    return path, sup.pin_everything(path, tmp_path / "pins")


def _worker(path: Path, tmp_path: Path) -> WorkerBox:
    box = WorkerBox(BoxConfig.load(str(path)), sup.spec(tmp_path / "participant"), Redactor(),
                    owner_token=lambda _p: "", connector=lambda _host: socket.socketpair()[0])
    box.docker_calls = []

    def docker(*args, timeout=60):
        box.docker_calls.append(args)
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    box._docker = docker
    return box


def _start(box: WorkerBox) -> str:
    with pytest.raises(BoxError) as caught:
        box.start(lambda _record: None)
    return caught.value.code


def _change(path: Path) -> None:
    with open(path, "a") as fh:
        fh.write("// changed\n")


# --- at load ----------------------------------------------------------------------------------


@pytest.mark.parametrize("over,said", [
    ({"image_tar_sha256": "abc"}, "image_tar_sha256 must be a sha256 digest"),
    ({"runtime_sha256": "A" * 64}, "runtime_sha256 must be a sha256 digest"),
    ({"identity_extension_sha256": 7}, "identity_extension_sha256 must be a sha256 digest"),
    ({"identity_config_sha256": "f" * 63}, "identity_config_sha256 must be a sha256 digest"),
    ({"image_tag": "temper pi box"}, "image_tag must be a name:tag"),
    ({"image_tar": "pi-image/box.tar"}, "image_tar must be an absolute path"),
    ({"routes": {"openai-codex": {"provider": "openai-codex", "host": "chatgpt.com",
                                  "extension_sha256": "nope"}}},
     "route openai-codex: extension_sha256 must be a sha256 digest"),
])
def test_a_pin_that_is_not_a_digest_is_refused_at_load(tmp_path, over, said):
    with pytest.raises(BoxError, match=said) as caught:
        sup.box_config(tmp_path, **over)
    assert caught.value.code == "box_config_invalid"


@pytest.mark.parametrize("where,name", [
    ("identity-ext/index.ts", "identity_extension"),
    ("identity-config/pi-identity.json", "identity_settings"),
    ("login/src/index.ts", "route:openai-codex"),
    ("other-login/src/index.ts", "route:anthropic"),
    ("models-store.json", "route:openai-codex:catalog"),
])
def test_a_pinned_part_changed_before_load_is_refused_at_load(tmp_path, short_root, where, name):
    path, _raw = _pinned(tmp_path, short_root)
    _change(tmp_path / where)
    with pytest.raises(BoxError) as caught:
        BoxConfig.load(str(path))
    assert caught.value.code == "box_config_invalid"
    assert f"{name} changed (digest differs from its pin)" in str(caught.value)


# --- at every start ---------------------------------------------------------------------------


def test_a_start_reads_back_the_identity_and_its_own_route_s_login(tmp_path, short_root):
    path, raw = _pinned(tmp_path, short_root)
    box = _worker(path, tmp_path)
    try:
        # The stand-in docker refuses the create: the read-back was passed.
        assert _start(box) == "box_create_failed"
        assert box.docker_calls[0][0] == "create"
        route = raw["routes"]["openai-codex"]
        assert box.pins_read_back == {
            "identity_extension": raw["identity_extension_sha256"],
            "identity_settings": raw["identity_config_sha256"],
            "route:openai-codex": route["extension_sha256"],
            "route:openai-codex:catalog": route["catalog_sha256"]}
    finally:
        box.close()


@pytest.mark.parametrize("where,name", [
    ("identity-ext/index.ts", "identity_extension"),
    ("identity-config/pi-identity.json", "identity_settings"),
    ("login/src/index.ts", "route:openai-codex"),
    ("models-store.json", "route:openai-codex:catalog"),
])
def test_a_pinned_part_changed_after_load_is_refused_before_docker(
        tmp_path, short_root, where, name):
    path, _raw = _pinned(tmp_path, short_root)
    box = _worker(path, tmp_path)
    _change(tmp_path / where)
    assert _start(box) == "pin_changed"
    assert box.docker_calls == []
    assert box.sock_dir is None and not (tmp_path / "participant" / "agent").exists()
    box.close()


def test_the_refusal_names_the_pin_and_no_path(tmp_path, short_root):
    path, _raw = _pinned(tmp_path, short_root)
    box = _worker(path, tmp_path)
    _change(tmp_path / "identity-config" / "pi-identity.json")
    with pytest.raises(BoxError) as caught:
        box.start(lambda _record: None)
    assert str(caught.value).endswith(
        "Pi worker box: identity_settings no longer read back with the pinned digest")
    assert str(tmp_path) not in str(caught.value)
    box.close()


def test_another_route_s_login_is_not_this_member_s_to_read_back(tmp_path, short_root):
    path, _raw = _pinned(tmp_path, short_root)
    box = _worker(path, tmp_path)
    _change(tmp_path / "other-login" / "src" / "index.ts")
    try:
        assert _start(box) == "box_create_failed"
        assert "route:anthropic" not in box.pins_read_back
    finally:
        box.close()


def test_a_box_config_without_the_pins_refuses_nothing_and_records_what_it_read(
        tmp_path, short_root):
    """Tests and host-process proofs: nothing pinned, nothing refused; the read-back still
    says what the member started on (the pin check calls the missing pins a mismatch)."""
    path = sup.make_box_config(tmp_path, socket_root=str(short_root))
    box = _worker(path, tmp_path)
    try:
        assert _start(box) == "box_create_failed"
        assert box.pins_read_back == {
            "identity_extension": pins.tree_sha256(tmp_path / "identity-ext"),
            "identity_settings": pins.tree_sha256(tmp_path / "identity-config")}
    finally:
        box.close()


def test_the_turn_keeps_the_read_back_in_its_public_checks():
    read = {"identity_extension": "a" * 64, "identity_settings": "b" * 64}
    checks = {"pins_read_back": read, "sealed": {"id": "x"}, "add_ons": ["pi-tldr"]}
    assert turn._public_checks(checks) == {"pins_read_back": read, "add_ons": ["pi-tldr"]}
    assert json.dumps(turn._public_checks(checks))
