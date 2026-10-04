"""Pi member settings: the model, Temper's tool names and the add-ons a ``type: pi`` agent gets.

Defaults are claude-opus-5-5 at thinking max; ``tools:`` uses Temper's names, mapped to Pi's
built-ins, and refuses a tool Pi doesn't have by name; ``add_ons:`` defaults to every allowed
add-on, refuses the risky ones with the reason, and loads each from a pinned copy whose digest
goes into the turn's pin. A usage limit pauses the step for the owner, naming the limit.
Sealed: no container, no network, no model.
"""

from __future__ import annotations

import json
import shutil
import socket
import tempfile
from pathlib import Path

import pytest

from temper_ai.llm.pi_stream import Redactor
from temper_ai.pi_agent import member
from temper_ai.pi_agent.box import BoxConfig, BoxError, WorkerBox, tree_sha256
from temper_ai.pi_agent.member import (
    ADD_ONS,
    REFUSED_ADD_ONS,
    TOOL_MAP,
    add_on_names,
    config_problems,
    launched_tools,
    pi_tools,
    settings,
    usage_limit,
)
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox

PI_MEMBER = {"name": "design", "type": "pi", "role": "architecture"}


# --- model --------------------------------------------------------------------------------


def test_the_default_model_is_opus_5_5_at_max():
    assert settings(PI_MEMBER) == {"provider": "anthropic", "model": "claude-opus-5-5",
                                   "thinking": "max"}
    assert config_problems(PI_MEMBER) == []


def test_set_model_settings_are_kept_and_checked():
    cfg = {**PI_MEMBER, "provider": "openai-codex", "model": "gpt-6.1-sol", "thinking": "high"}
    assert settings(cfg) == {"provider": "openai-codex", "model": "gpt-6.1-sol",
                             "thinking": "high"}
    assert config_problems({**PI_MEMBER, "thinking": "max"}) == []
    got = config_problems({**PI_MEMBER, "provider": "", "model": 5, "thinking": "ultra"})
    assert got == ["'provider' must be a name (leave it out for anthropic)",
                   "'model' must be a name (leave it out for claude-opus-5-5)",
                   "'thinking' must be one of off, minimal, low, medium, high, xhigh, max"]


# --- tools --------------------------------------------------------------------------------


@pytest.mark.parametrize("temper, pi", [
    ("Read", ["read"]), ("Edit", ["edit"]), ("Write", ["write"]), ("Bash", ["bash"]),
    ("Grep", ["grep"]), ("Glob", ["find", "ls"]),
])
def test_temper_tool_names_become_pi_builtins(temper, pi):
    assert pi_tools([temper]) == pi
    assert config_problems({**PI_MEMBER, "tools": [temper]}) == []


def test_the_whole_tool_list_maps_without_repeats_and_defaults_to_read():
    assert pi_tools(list(TOOL_MAP)) == ["bash", "edit", "find", "grep", "ls", "read", "write"]
    assert pi_tools(["Glob", "Read", "Glob"]) == ["find", "ls", "read"]
    assert pi_tools(None) == ["read"]


def test_a_tool_pi_does_not_have_refuses_the_config_by_name():
    got = config_problems({**PI_MEMBER, "tools": ["Read", "WebFetch", "NotionSearch", "GitHub",
                                                  "Linear", "read"]})
    allowed = "Read, Edit, Write, Bash, Grep, Glob"
    assert got == [f"tool 'WebFetch' has no Pi equivalent (a Pi member can use {allowed})",
                   f"tool 'NotionSearch' has no Pi equivalent (a Pi member can use {allowed})",
                   f"tool 'GitHub' has no Pi equivalent (a Pi member can use {allowed})",
                   f"tool 'Linear' has no Pi equivalent (a Pi member can use {allowed})",
                   "tool 'read' is Pi's own name; use Temper's name 'Read'"]
    for bad in ([], "Read", [1]):
        assert config_problems({**PI_MEMBER, "tools": bad}) == [
            f"'tools' must be a non-empty list of Temper tool names ({allowed})"]


# --- add-ons ------------------------------------------------------------------------------


def test_add_ons_default_to_every_allowed_one():
    assert add_on_names(PI_MEMBER) == ["pi-image-trim", "pi-tldr"]
    assert sorted(ADD_ONS) == list(sup.ADD_ON_NAMES)
    assert add_on_names({**PI_MEMBER, "add_ons": []}) == []
    assert add_on_names({**PI_MEMBER, "add_ons": ["pi-tldr"]}) == ["pi-tldr"]


def test_the_worker_starts_with_the_mapped_tools_plus_the_add_ons_own_tools():
    assert launched_tools(PI_MEMBER) == ["read", "tldr"]
    assert launched_tools({**PI_MEMBER, "tools": ["Glob"], "add_ons": []}) == ["find", "ls"]
    assert launched_tools({**PI_MEMBER, "add_ons": ["pi-image-trim"]}) == ["read"]


@pytest.mark.parametrize("name", sorted(REFUSED_ADD_ONS))
def test_each_risky_add_on_is_refused_by_name_with_its_reason(name):
    got = config_problems({**PI_MEMBER, "add_ons": [name]})
    assert got == [f"add-on '{name}' is not allowed: {REFUSED_ADD_ONS[name]}"]


def test_the_refused_list_is_the_plans():
    assert set(REFUSED_ADD_ONS) >= {
        "pi-worktree", "pi-subagents", "relays", "pi-memory", "pi-mcp-adapter", "pi-web-access",
        "pi-web-search", "pi-control-chrome", "pi-multi-pass", "pi-queue", "pi-company"}
    assert "not available yet" in REFUSED_ADD_ONS["team-messaging"]
    assert not set(REFUSED_ADD_ONS) & set(ADD_ONS)


def test_an_add_on_that_failed_in_the_box_is_left_out_with_the_reason():
    """M2 box test (2026-10-04): billion-context-pi writes a file beside the Pi session, which
    the turn's private-session check refuses. Left out and reported, not patched around."""
    assert "billion-context-pi" not in ADD_ONS
    assert config_problems({**PI_MEMBER, "add_ons": ["billion-context-pi"]}) == [
        "add-on 'billion-context-pi' is not allowed: left out after the worker box test: it "
        "writes its own file beside the Pi session (<session>.jsonl.acp.json), which the turn's "
        "private session check refuses, so every turn with it fails"]


def test_unknown_and_repeated_add_ons_are_refused():
    got = config_problems({**PI_MEMBER, "add_ons": ["pi-tldr", "pi-tldr", "pi-shiny"]})
    assert got == ["unknown add-on 'pi-shiny' (allowed: pi-image-trim, pi-tldr)",
                   "'add_ons' names an add-on more than once"]
    assert config_problems({**PI_MEMBER, "add_ons": "pi-tldr"}) == [
        "'add_ons' must be a list of add-on names"]


def test_every_problem_comes_at_once():
    got = config_problems({"name": "x", "type": "pi", "role": "two words", "roles": ["a"],
                           "thinking": "ultra", "tools": ["WebFetch"], "add_ons": ["relays"],
                           "message": 3, "workspace_files": {"../x": "y"}})
    assert got == [
        "'role' must be one role name (one role per Pi step)",
        "one role per Pi step ('roles' is not supported)",
        "'thinking' must be one of off, minimal, low, medium, high, xhigh, max",
        "tool 'WebFetch' has no Pi equivalent (a Pi member can use Read, Edit, Write, Bash, Grep, "
        "Glob)",
        "add-on 'relays' is not allowed: starts extra agents or sessions Temper can't see, count "
        "or limit",
        "'message' must be text",
        "'workspace_files' must map plain file names to text"]


# --- pinned add-on copies -----------------------------------------------------------------


def test_each_add_on_needs_an_unchanged_pinned_copy_outside_the_live_pi_folder(tmp_path):
    pins = sup.make_add_ons(tmp_path)
    cfg = sup.box_config(tmp_path / "a", add_ons=pins)
    assert sorted(cfg.add_ons) == list(sup.ADD_ON_NAMES)
    assert cfg.add_ons["pi-tldr"].sha256 == tree_sha256(Path(pins["pi-tldr"]["dir"]))

    changed = {**pins, "pi-tldr": {**pins["pi-tldr"], "sha256": "0" * 64}}
    with pytest.raises(BoxError, match="add-on pi-tldr: pinned copy changed"):
        sup.box_config(tmp_path / "b", add_ons=changed)
    no_entry = {**pins, "pi-tldr": {**pins["pi-tldr"], "entry": "missing.ts"}}
    with pytest.raises(BoxError, match="add-on pi-tldr: pinned copy or its entry file missing"):
        sup.box_config(tmp_path / "c", add_ons=no_entry)
    escape = {**pins, "pi-tldr": {**pins["pi-tldr"], "entry": "../pi-image-trim/index.ts"}}
    with pytest.raises(BoxError, match="entry file missing"):
        sup.box_config(tmp_path / "d", add_ons=escape)

    home = tmp_path / "home"
    live = home / ".pi" / "agent" / "npm" / "pi-tldr"
    shutil.copytree(pins["pi-tldr"]["dir"], live)
    from_live = {"pi-tldr": {**pins["pi-tldr"], "dir": str(live)}}
    with pytest.raises(BoxError, match="must be a pinned copy, not the owner's live"):
        sup.box_config(tmp_path / "e", add_ons=from_live, host_home=str(home))


@pytest.fixture
def short_root():
    root = Path(tempfile.mkdtemp(prefix="pibox-", dir="/tmp"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _box(tmp_path: Path, short_root: Path, add_ons: list[str]) -> WorkerBox:
    cfg = sup.box_config(tmp_path, socket_root=str(short_root),
                         add_ons=sup.make_add_ons(tmp_path / "pins"))
    spec = sup.spec(tmp_path / "participant", add_ons=add_ons,
                    tools=["read", "tldr"] if "pi-tldr" in add_ons else ["read"])
    box = WorkerBox(cfg, spec, Redactor(), owner_token=lambda _p: "",
                    connector=lambda _host: socket.socketpair()[0])
    box.sock_dir = short_root / "s"
    return box


def test_the_box_loads_each_add_on_read_only_from_its_pinned_copy(tmp_path, short_root):
    box = _box(tmp_path, short_root, ["pi-image-trim", "pi-tldr"])
    args = box.create_args()
    mounts = [a for a in args if a.startswith("type=bind")]
    addon_mounts = [m for m in mounts if "target=/ext/addons/" in m]
    assert len(addon_mounts) == 2 and all(m.endswith(",readonly") for m in addon_mounts)
    state = Path(box.cfg.state_root).resolve() / "_ext"
    assert all(f"source={state}/addon-" in m for m in addon_mounts)
    assert not any(str(Path.home() / ".pi") in m for m in mounts)
    writable = [m for m in mounts if not m.endswith(",readonly")]
    assert len(writable) == 1 and "target=/w," in writable[0] + ","
    pi = args[args.index("/box/entry.py") + 1:]
    assert [pi[i + 1] for i, a in enumerate(pi) if a == "--extension"] == [
        "/ext/identity/index.ts", "/ext/temper-box/index.ts",
        "/ext/addons/pi-image-trim/index.ts", "/ext/addons/pi-tldr/index.ts"]
    assert pi[pi.index("--tools") + 1] == "read,tldr"


def test_a_read_only_pinned_copy_loads_and_its_box_copy_stays_removable(tmp_path, short_root):
    box = _box(tmp_path, short_root, ["pi-tldr"])
    pinned = Path(box.cfg.add_ons["pi-tldr"].dir)
    (pinned / "index.ts").chmod(0o444)
    pinned.chmod(0o555)  # pinned copies are kept read only
    try:
        args = box.create_args()
    finally:
        pinned.chmod(0o755)
        (pinned / "index.ts").chmod(0o644)
    mount = next(a for a in args if "target=/ext/addons/pi-tldr" in a)
    assert mount.endswith(",readonly")
    copy = Path(mount.split("source=", 1)[1].split(",", 1)[0])
    assert (copy / "node_modules").is_symlink() and (copy / "index.ts").is_file()
    assert tree_sha256(copy) == box.cfg.add_ons["pi-tldr"].sha256
    shutil.rmtree(copy)


def test_a_box_without_add_ons_is_as_before(tmp_path, short_root):
    args = _box(tmp_path, short_root, []).create_args()
    assert not [a for a in args if "/ext/addons/" in a]


def test_an_add_on_copy_changed_after_loading_is_refused_when_the_box_starts(tmp_path,
                                                                             short_root):
    box = _box(tmp_path, short_root, ["pi-tldr"])
    Path(box.cfg.add_ons["pi-tldr"].dir, "index.ts").write_text("// changed\n")
    with pytest.raises(BoxError) as err:
        box.create_args()
    assert err.value.code == "add_on_changed"


def test_add_on_commands_count_only_from_the_members_own_add_ons():
    from temper_ai.pi_agent.turn import TurnFailure, _check_commands

    ours = [{"name": "identity", "source": "extension",
             "sourceInfo": {"path": "/ext/identity/core.ts"}},
            {"name": "temper-box-state", "source": "extension",
             "sourceInfo": {"path": "/ext/temper-box/index.ts"}}]
    tldr = {"name": "tldr-nudges", "source": "extension",
            "sourceInfo": {"path": "/ext/addons/pi-tldr/index.ts"}}
    got = _check_commands(ours + [tldr], None, add_ons=["pi-tldr"])
    assert got["add_ons"] == {"pi-tldr": ["tldr-nudges"]} and got["stray"] == 0
    with pytest.raises(TurnFailure) as err:
        _check_commands(ours + [tldr], None, add_ons=["pi-image-trim"])
    assert err.value.code == "extensions_not_allowed"
    assert _check_commands(ours, None)["add_ons"] == {}


# --- a usage limit ------------------------------------------------------------------------


@pytest.mark.parametrize("error", [
    "429 Too Many Requests", "rate_limit_error: slow down", "You have reached your usage limit",
    "Claude usage limit reached; resets 3am", "This request would exceed your account's rate limit",
    "quota exhausted",
])
def test_a_usage_or_rate_limit_is_recognised(error):
    assert usage_limit(error) == "usage limit: " + error


@pytest.mark.parametrize("error", [None, "", "500 Internal Server Error", "overloaded_error",
                                   "400 invalid_request_error: the request was refused"])
def test_other_provider_errors_are_not_a_usage_limit(error):
    assert usage_limit(error) is None


# --- a member's turn, end to end (stand-in worker) ------------------------------------------


def _add_box_settings(pi, **over) -> None:
    raw = json.loads(Path(pi.box_json).read_text())
    raw.update(over)
    Path(pi.box_json).write_text(json.dumps(raw))


def _member_node(**cfg):
    node = sup.pi_node(**cfg)
    for key in [k for k, v in cfg.items() if v is None]:
        node.agent_config.pop(key)
    return node


def test_a_member_with_defaults_gets_opus_5_5_at_max_and_its_pinned_add_ons(pi, monkeypatch):
    pins = sup.make_add_ons(pi.tmp / "pins")
    _add_box_settings(pi, add_ons=pins, routes={
        "anthropic": {"provider": "anthropic", "host": "api.anthropic.com"},
        "openai-codex": {"provider": "openai-codex", "host": "chatgpt.com"}})
    monkeypatch.setitem(sup.WORKFLOWS, "pi_defaults", lambda: [
        sup.step("brief"), _member_node(provider=None, model=None, thinking=None, add_ons=None)])
    eid = sup.start(pi.client, "pi_defaults", pi.ws)
    sup.open_wait(eid, "owner")
    agents = sup.turn_agents(eid)
    end = sup.agent_end(eid, agents[0]["id"])
    assert end["type"] == "agent.completed"
    effective = end["data"]["pi_effective"]
    assert (effective["provider"], effective["model"], effective["thinking"]) == (
        "anthropic", "claude-opus-5-5", "max")
    assert FakeBox.STARTS[0]["add_ons"] == list(sup.ADD_ON_NAMES)
    assert FakeBox.STARTS[0]["tools"] == launched_tools({"type": "pi", "role": "scout"})
    pin = sup.ledger().snapshot(eid)["participants"][0]["pin"]
    assert pin["add_ons"] == {name: pins[name]["sha256"] for name in sup.ADD_ON_NAMES}
    assert (pin["model"], pin["thinking"]) == ("claude-opus-5-5", "max")
    # The role read its note with Read, which Pi ran as its read tool.
    tools = [e for e in sup.events(eid) if e["type"].startswith("tool.call")]
    assert tools and all((e["data"] or {}).get("tool_name") == "read" for e in tools)


def test_a_member_whose_add_ons_have_no_pinned_copy_fails_before_any_worker(pi, monkeypatch):
    monkeypatch.setitem(sup.WORKFLOWS, "pi_unpinned", lambda: [
        sup.step("brief"), _member_node(add_ons=None)])
    eid = sup.start(pi.client, "pi_unpinned", pi.ws)
    assert sup.wait_ended(eid)[-1]["status"] == "failed"
    assert FakeBox.STARTS == []
    said = [e for e in sup.events(eid) if "no pinned copy of add-on(s)" in str(e["data"])]
    assert said, "the failure names the add-ons without a pinned copy"


def test_a_usage_limit_pauses_for_the_owner_naming_the_limit(pi):
    FakeBox.behaviour = "usage_limit"
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    rec = sup.open_wait(eid, "recovery")
    why = rec["subject"]["why"]
    assert why.startswith("usage limit: ") and why.endswith(sup.USAGE_LIMIT_ERROR)
    assert "usage limit" in rec["subject"]["question"]
    assert rec["subject"]["options"] == ["accept", "retry"]
    # One worker, same model and account: no quiet switch, no retry on its own.
    assert len(FakeBox.STARTS) == 1
    assert sup.ledger().snapshot(eid)["turns"][0]["state"] == "uncertain"


def test_member_module_imports_nothing_from_the_stage_package():
    assert "temper_ai.stage" not in Path(member.__file__).read_text()
    assert BoxConfig  # the pins live in the box config
