"""temper-pi-host's config: the example's shape, the values ops installs, and what is refused."""

from __future__ import annotations

import json
import re

import pytest

from .support import BASE, BRIDGE, EXAMPLE, OTHER, REPO, SCRIPT, SLOT, Host, tph


@pytest.fixture
def host():
    h = Host()
    yield h
    h.cleanup()


def problems_of(raw: dict) -> list[str]:
    with pytest.raises(tph.ConfigError) as err:
        tph.parse_config(raw)
    return err.value.problems


def test_the_example_parses_once_its_placeholders_are_filled():
    text = EXAMPLE.read_text()
    assert "/home/" in text and "<user>" in text  # placeholders, not a real home
    filled = (text.replace("<base_provider>", BASE).replace("<sdk-version>", "1.2.3")
              .replace("<ai-version>", "1.2.3"))
    cfg = tph.parse_config(json.loads(filled))
    assert cfg.allowed_slots == (f"{BASE}-2", f"{BASE}-3")
    assert cfg.branch_enabled is False and cfg.tokens_per_hour == 120
    assert cfg.bridge is not None and cfg.bridge.sdk_package == tph.DEFAULT_SDK_PACKAGE
    assert cfg.pi_state_root.endswith("/.local/state/temper/pi/runs")
    assert len(cfg.socket.encode()) < tph.SOCKET_PATH_LIMIT


def test_the_example_names_every_key_the_helper_reads():
    raw = json.loads(EXAMPLE.read_text())
    assert {k for k in raw if not k.startswith("_")} == tph.TOP_KEYS
    assert {k for k in raw["bridge"] if not k.startswith("_")} == tph.BRIDGE_KEYS


def test_the_repo_holds_no_slot_name_or_real_path():
    """Slots and paths come from the private config: the script, the bridge, the example and
    the doc hold none of the host's (the base provider is the config's default), and every
    home folder they show is the placeholder."""
    for path in (SCRIPT, BRIDGE, EXAMPLE, REPO / "docs" / "pi-host-helper.md"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"anthropic-\d", text), path.name
        assert not re.search(r"/home/(?!<user>)", text), path.name


def test_the_values_ops_installs_are_accepted(host):
    cfg = host.cfg(branch_enabled=False, tokens_per_hour=120)
    assert (cfg.branch_enabled, cfg.tokens_per_hour, cfg.token_timeout_s) == (False, 120, 10.0)
    assert cfg.allowed_slots == (SLOT, OTHER)


def test_defaults(host):
    raw = host.config()
    for key in ("pi_cli", "base_provider", "allowed_slots", "project_roots", "branch_enabled",
                "branch_max_bytes", "tokens_per_hour", "token_timeout_s", "bridge"):
        raw.pop(key, None)
    raw["base_provider"] = BASE  # the default is the real provider; the tests use a made-up one
    cfg = tph.parse_config(raw)
    assert cfg.allowed_slots == () and cfg.project_roots == () and cfg.bridge is None
    assert cfg.branch_enabled is False and cfg.tokens_per_hour == 120 and cfg.token_timeout_s == 30.0
    assert cfg.pi_cli == ("pi",)
    assert tph.parse_config({k: v for k, v in raw.items() if k != "base_provider"}).base_provider == "anthropic"


def test_comment_keys_are_ignored(host):
    raw = host.config(_note="anything")
    raw["bridge"]["_note"] = "anything"
    assert tph.parse_config(raw).socket == raw["socket"]


@pytest.mark.parametrize("over, expected", [
    ({"allowed_slots": [BASE]}, "it is account 1, never served"),
    ({"allowed_slots": ["other-2"]}, "is not an alias of acme"),
    ({"allowed_slots": [f"{BASE}-1"]}, "is not an alias of acme"),
    ({"allowed_slots": [SLOT, SLOT]}, "lists a slot twice"),
    ({"socket": "/tmp/" + "s" * 100}, "socket must be shorter than 100 bytes"),
    ({"socket": "relative.sock"}, "socket must be an absolute, normalized path"),
    ({"pi_state_root": "/tmp/../etc"}, "pi_state_root must be an absolute, normalized path"),
    ({"surprise": 1}, "unknown key 'surprise'"),
    ({"tokens_per_hour": 0}, "tokens_per_hour must be a whole number"),
    ({"tokens_per_hour": True}, "tokens_per_hour must be a whole number"),
    ({"token_timeout_s": 0}, "token_timeout_s must be a number of seconds"),
    ({"branch_enabled": "yes"}, "branch_enabled must be true or false"),
    ({"project_roots": ["/"]}, "must be an absolute folder or folder/*"),
    ({"project_roots": ["projects/*"]}, "must be an absolute folder or folder/*"),
    ({"pi_cli": []}, "pi_cli must be a list of words"),
    ({"path": ["bin"]}, "path must be a list of absolute folders"),
    ({"base_provider": "Not A Provider"}, "base_provider must be a provider id"),
])
def test_refused(host, over, expected):
    problems = problems_of(host.config(**over))
    assert any(expected in p for p in problems), problems


@pytest.mark.parametrize("bridge_over, expected", [
    ({"sdk_version": ""}, "bridge.sdk_version must be the exact Pi SDK version"),
    ({"sdk_version": "1.0.1 or later"}, "bridge.sdk_version must be the exact Pi SDK version"),
    ({"script": "bridge.mjs"}, "bridge.script must be an absolute, normalized path"),
    ({"sdk_package": "Not/A Package"}, "bridge.sdk_package must be an npm package name"),
    ({"stop_grace_s": 0}, "bridge.stop_grace_s must be a number of seconds"),
    ({"surprise": 1}, "unknown key bridge.surprise"),
])
def test_bridge_refused(host, bridge_over, expected):
    raw = host.config()
    raw["bridge"].update(bridge_over)
    problems = problems_of(raw)
    assert any(expected in p for p in problems), problems


def test_every_problem_is_named_at_once(host):
    problems = problems_of(host.config(allowed_slots=[BASE], tokens_per_hour=0, surprise=1))
    assert len(problems) == 3


def test_an_unreadable_config_file(host):
    with pytest.raises(tph.ConfigError) as err:
        tph.load_config(str(host.root / "missing.json"))
    assert "could not be read" in err.value.problems[0]
