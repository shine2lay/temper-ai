"""Registration is not a new sealed credential route or workflow admission."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from temper_ai.agent import AGENT_TYPES
from temper_ai.agent.single_call_agent import SINGLE_CALL_REQUIRED
from temper_ai.spawner import box_launches as bl
from temper_ai.spawner.box_guard import Guard, LaunchRefused


def classify(tmp_path: Path, provider="anthropic", **changes):
    root = tmp_path / "configs"
    (root / "workflows").mkdir(parents=True)
    (root / "agents").mkdir()
    (root / "workflows/wf.yaml").write_text(yaml.safe_dump({"workflow": {
        "name": "wf", "nodes": [{"name": "judge", "agent": "judge"}],
    }}))
    agent = {"name": "judge", "type": "single_call", "provider": provider,
             "model": "claude-opus-5-5", "single_call": dict.fromkeys(SINGLE_CALL_REQUIRED, "FAKE")}
    agent.update(changes)
    if provider is None:
        del agent["provider"]
    (root / "agents/judge.yaml").write_text(yaml.safe_dump({"agent": agent}))
    return bl.classify(bl.ConfigIndex.of(bl.FsTree(root)), "wf")


def test_registered_type_and_anthropic_walk_without_widening_provider_list(tmp_path):
    assert "single_call" in AGENT_TYPES and "single_call" in bl.AGENT_TYPES
    result = classify(tmp_path)
    assert result.boundary == bl.SEALED and result.allowed["providers"] == ["anthropic"]
    assert result.allowed["agent_types"] == ["single_call"]
    assert bl.SEALED_PROVIDERS == frozenset({"claude", "claude_v2", "anthropic"})
    guard = Guard("wf", {}, {}, {key: frozenset(value) for key, value in result.allowed.items()})
    guard.check("agent_types", "single_call")
    guard.check("providers", "anthropic")
    for provider in ("openai", "openai_codex"):
        with pytest.raises(LaunchRefused):
            guard.check("providers", provider)


@pytest.mark.parametrize("provider", ["openai", "openai_codex", None])
def test_codex_and_unnamed_routes_remain_refused(tmp_path, provider):
    result = classify(tmp_path, provider)
    assert result.boundary == bl.REFUSED
    assert result.reasons


@pytest.mark.parametrize("changes", [
    {"single_call": {"shell": "forbidden"}},
    {"single_call": "${unresolved}"},
    {"provider_overrides": {"api_key": "forbidden"}},
    {"shell": "forbidden"},
    {"type": "llm"},
    {"type": "script"},
])
def test_closed_nested_inputs_and_other_agent_mappings_are_not_a_bypass(tmp_path, changes):
    assert classify(tmp_path, **changes).boundary == bl.REFUSED
