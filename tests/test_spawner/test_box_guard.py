"""A sealed box's runner loads and starts only its classified launch (BS1, box_guard.py).

Security rm-963c1429 condition 4: static rules can miss a path, so the box backs them.
Every closure file is checked against the blob id the worker classified, configs come
from those files and never the database, and an agent type, tool, provider or MCP server
outside the launch is refused where it would be used, before any tool of it runs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from temper_ai.config.helpers import ConfigNotFoundError
from temper_ai.spawner import box_guard
from temper_ai.spawner.box_launches import blob_id

AGENT = b"agent:\n  name: a\n  type: llm\n  provider: claude\n  system_prompt: hi ${SYNTH_NAME:x}\n"
WORKFLOW = b"workflow:\n  name: wf\n  nodes:\n  - name: one\n    agent: a\n"


def _doc(root: Path, **launch) -> dict:
    files = {"configs/workflows/wf.yaml": WORKFLOW, "configs/agents/a.yaml": AGENT}
    for path, data in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)
    record = {
        "workflow": "wf",
        "files": {path: blob_id(data) for path, data in files.items()},
        "configs": {"agent": {"a": "configs/agents/a.yaml"},
                    "workflow": {"wf": "configs/workflows/wf.yaml"}},
        "allowed": {"agent_types": ["llm"], "mcp_servers": ["web"], "providers": ["claude"],
                    "tools": ["Read", "web.search"]},
        **launch,
    }
    return {"boundary": "sealed", "launch": record}


@pytest.fixture
def guard(tmp_path) -> box_guard.Guard:
    active = box_guard.activate(_doc(tmp_path), root=tmp_path / "configs")
    assert active is not None and box_guard.active() is active
    return active


def test_a_legacy_box_has_no_guard_and_everything_works_as_before(tmp_path):
    assert box_guard.activate({"boundary": "legacy", "launch": {}}) is None
    assert box_guard.activate(None) is None and box_guard.active() is None
    box_guard.check("agent_types", "pi")
    box_guard.check("providers", "openai")
    assert box_guard.classified_tools(["Bash", "Delegate"]) == (["Bash", "Delegate"], [])


def test_configs_come_from_the_checked_files(guard, tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTH_NAME", "named")
    (tmp_path / "configs" / "agents" / "a.yaml").write_text("agent: {name: a, type: pi}\n")
    config = guard.config("a", "agent")  # the bytes checked at activation, not the disk now
    assert config["agent"]["type"] == "llm" and config["agent"]["system_prompt"] == "hi named"
    assert guard.config("wf", "workflow")["workflow"]["name"] == "wf"


def test_a_config_outside_the_launch_is_not_found(guard):
    with pytest.raises(box_guard.NotInLaunch, match="isn't part of this run's classified launch"):
        guard.config("other", "agent")
    assert issubclass(box_guard.NotInLaunch, ConfigNotFoundError)  # callers see not found


def test_the_config_store_never_reads_the_database_in_a_sealed_box(guard, monkeypatch):
    from temper_ai.config import store

    def no_database():
        raise AssertionError("a sealed box read the database")

    monkeypatch.setattr(store, "get_session", no_database)
    assert store.ConfigStore().get("a", "agent")["agent"]["name"] == "a"
    with pytest.raises(ConfigNotFoundError):
        store.ConfigStore().get("b", "agent")


@pytest.mark.parametrize(("change", "message"), [
    (lambda root, doc: (root / "configs/agents/a.yaml").write_text("agent: {name: a}\n"),
     "isn't the file that was classified"),
    (lambda root, doc: (root / "configs/agents/a.yaml").unlink(), "can't be read in this box"),
    (lambda root, doc: doc["launch"].update(files={}), "doesn't say which files"),
    (lambda root, doc: doc["launch"].pop("allowed"), "doesn't say which files"),
    (lambda root, doc: doc["launch"]["files"].update({"/etc/passwd": "0" * 40}),
     "isn't a config file"),
    (lambda root, doc: doc["launch"]["files"].update({"configs/../x": "0" * 40}),
     "isn't a config file"),
    (lambda root, doc: doc["launch"]["configs"]["agent"].update(b="configs/agents/b.yaml"),
     "isn't among its files"),
])
def test_a_box_whose_launch_files_dont_check_out_loads_nothing(tmp_path, change, message):
    doc = _doc(tmp_path)
    change(tmp_path, doc)
    with pytest.raises(box_guard.LaunchRefused, match=message):
        box_guard.activate(doc, root=tmp_path / "configs")
    assert box_guard.active() is None


@pytest.mark.parametrize(("kind", "name"), [
    ("agent_types", "pi"), ("agent_types", "jev"), ("providers", "openai"),
    ("providers", None), ("mcp_servers", "playwright"), ("tools", "Delegate"),
])
def test_anything_outside_the_launch_is_refused(guard, kind, name):
    with pytest.raises(box_guard.LaunchRefused, match="a sealed box refuses it"):
        box_guard.check(kind, name)


def test_only_the_launchs_tools_are_registered(guard):
    kept, left_out = box_guard.classified_tools(["Read", "Bash", "web.search", "git.status"])
    assert kept == ["Read", "web.search"] and left_out == ["Bash", "git.status"]


def test_an_agent_of_another_type_is_refused_before_it_is_made(guard):
    from temper_ai.agent import create_agent

    with pytest.raises(box_guard.LaunchRefused, match="agent type 'pi'"):
        create_agent({"name": "x", "type": "pi"})


def test_a_provider_outside_the_launch_is_refused_even_as_the_default(guard, monkeypatch):
    from temper_ai.shared.types import ExecutionContext

    providers = {"claude": object(), "openai": object()}
    context = SimpleNamespace(llm_providers=providers, resolve_provider=lambda: "openai")
    with pytest.raises(box_guard.LaunchRefused, match="provider 'openai'"):
        ExecutionContext.get_llm(context, "openai")
    with pytest.raises(box_guard.LaunchRefused, match="provider 'openai'"):
        ExecutionContext.get_llm(context, None)  # the install's default, resolved at run time
    assert ExecutionContext.get_llm(context, "claude") is providers["claude"]


def test_an_mcp_server_outside_the_launch_is_never_started(guard):
    from temper_ai.tools.mcp_client import MCPClientManager

    manager = MCPClientManager()
    with pytest.raises(box_guard.LaunchRefused, match="mcp server 'playwright'"):
        asyncio.run(manager.ensure_connected("playwright", caller="t"))
    assert manager._connections == {}
