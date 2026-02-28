"""Tests for temper_ai/stage/executors/_agent_execution.py.

Covers:
- resolve_agent_factory (None → default class, custom class → as-is)
- load_or_cache_agent (cache miss/hit, persistent cache, thread-safety)
- config_to_tracking_dict (model_dump, legacy dict(), plain dict fallback)
- extract_response_data (all fields, tool_calls None → [])
- extract_response_metrics (tokens/cost defaults, duration, tool_calls count)
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from temper_ai.stage.executors._agent_execution import (
    _persistent_agent_cache,
    config_to_tracking_dict,
    extract_response_data,
    extract_response_metrics,
    load_or_cache_agent,
    resolve_agent_factory,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    output="out",
    reasoning="why",
    confidence=0.8,
    tokens=50,
    estimated_cost_usd=0.005,
    tool_calls=None,
):
    resp = MagicMock()
    resp.output = output
    resp.reasoning = reasoning
    resp.confidence = confidence
    resp.tokens = tokens
    resp.estimated_cost_usd = estimated_cost_usd
    resp.tool_calls = tool_calls
    return resp


# ---------------------------------------------------------------------------
# TestResolveAgentFactory
# ---------------------------------------------------------------------------


class TestResolveAgentFactory:
    """resolve_agent_factory returns default or provided class."""

    def test_none_returns_default_agent_factory(self):
        from temper_ai.agent.utils.agent_factory import AgentFactory

        result = resolve_agent_factory(None)
        assert result is AgentFactory

    def test_custom_class_returned_as_is(self):
        class MyFactory:
            pass

        result = resolve_agent_factory(MyFactory)
        assert result is MyFactory

    def test_non_none_not_imported(self):
        """When given a non-None value, the import branch is never reached."""
        sentinel = object()
        result = resolve_agent_factory(sentinel)
        assert result is sentinel


# ---------------------------------------------------------------------------
# TestLoadOrCacheAgent
# ---------------------------------------------------------------------------


class TestLoadOrCacheAgent:
    """load_or_cache_agent handles cache miss/hit and persistent agents."""

    def setup_method(self):
        """Clear persistent cache before each test."""
        _persistent_agent_cache.clear()

    def teardown_method(self):
        """Ensure no state leaks between tests."""
        _persistent_agent_cache.clear()

    def _make_factory(self):
        factory = MagicMock()
        factory.create.return_value = MagicMock(name="created_agent")
        return factory

    def _make_config_loader(self, persistent=False):
        loader = MagicMock()
        loader.load_agent.return_value = {"agent": {"name": "test"}}
        return loader

    def _make_agent_config(self, persistent=False):
        cfg = MagicMock()
        cfg.agent.persistent = persistent
        return cfg

    @patch("temper_ai.storage.schemas.agent_config.AgentConfig")
    def test_cache_miss_creates_new_agent(self, mock_agent_config_cls):
        factory = self._make_factory()
        loader = self._make_config_loader()
        mock_agent_config_cls.return_value = self._make_agent_config(persistent=False)

        agent_cache: dict = {}
        agent, cfg, cfg_dict = load_or_cache_agent(
            "agent-x", loader, agent_cache, factory
        )

        factory.create.assert_called_once()
        assert "agent-x" in agent_cache

    @patch("temper_ai.storage.schemas.agent_config.AgentConfig")
    def test_cache_hit_returns_cached(self, mock_agent_config_cls):
        factory = self._make_factory()
        loader = self._make_config_loader()
        mock_agent_config_cls.return_value = self._make_agent_config(persistent=False)

        cached_agent = MagicMock(name="cached")
        agent_cache = {"agent-y": cached_agent}

        agent, cfg, cfg_dict = load_or_cache_agent(
            "agent-y", loader, agent_cache, factory
        )

        factory.create.assert_not_called()
        assert agent is cached_agent

    @patch("temper_ai.storage.schemas.agent_config.AgentConfig")
    def test_persistent_agent_uses_module_level_cache(self, mock_agent_config_cls):
        factory = self._make_factory()
        loader = self._make_config_loader()
        mock_agent_config_cls.return_value = self._make_agent_config(persistent=True)

        agent_cache: dict = {}
        agent1, _, _ = load_or_cache_agent("p-agent", loader, agent_cache, factory)
        agent2, _, _ = load_or_cache_agent("p-agent", loader, agent_cache, factory)

        # Only one agent created despite two calls
        factory.create.assert_called_once()
        assert agent1 is agent2
        assert "p-agent" in _persistent_agent_cache

    @patch("temper_ai.storage.schemas.agent_config.AgentConfig")
    def test_persistent_cache_thread_safe(self, mock_agent_config_cls):
        """Multiple threads loading the same persistent agent create only one instance."""
        factory = self._make_factory()
        loader = self._make_config_loader()
        mock_agent_config_cls.return_value = self._make_agent_config(persistent=True)

        results = []
        errors = []

        def load():
            try:
                agent, _, _ = load_or_cache_agent("threaded", loader, {}, factory)
                results.append(agent)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=load) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # All results should be the same object
        assert len({id(a) for a in results}) == 1


# ---------------------------------------------------------------------------
# TestConfigToTrackingDict
# ---------------------------------------------------------------------------


class TestConfigToTrackingDict:
    """config_to_tracking_dict handles Pydantic, legacy, and plain dicts."""

    def test_pydantic_model_uses_model_dump(self):
        cfg = MagicMock()
        cfg.model_dump.return_value = {"model": "dumped"}
        del cfg.dict  # Ensure only model_dump path taken

        result = config_to_tracking_dict(cfg, {"fallback": True})
        assert result == {"model": "dumped"}
        cfg.model_dump.assert_called_once()

    def test_legacy_dict_method_used_when_no_model_dump(self):
        cfg = MagicMock(spec=["dict"])
        cfg.dict.return_value = {"legacy": "dict"}

        result = config_to_tracking_dict(cfg, {"fallback": True})
        assert result == {"legacy": "dict"}
        cfg.dict.assert_called_once()

    def test_plain_dict_fallback_when_no_methods(self):
        # Object with neither model_dump nor dict attribute
        cfg = object()
        fallback = {"plain": "dict", "key": "val"}

        result = config_to_tracking_dict(cfg, fallback)
        assert result == fallback

    def test_plain_dict_is_copy(self):
        cfg = object()
        fallback = {"a": 1}
        result = config_to_tracking_dict(cfg, fallback)
        result["b"] = 2
        assert "b" not in fallback


# ---------------------------------------------------------------------------
# TestExtractResponseData
# ---------------------------------------------------------------------------


class TestExtractResponseData:
    """extract_response_data extracts all fields correctly."""

    def test_extracts_output(self):
        resp = _make_response(output="final answer")
        data = extract_response_data(resp)
        assert data["output"] == "final answer"

    def test_extracts_reasoning(self):
        resp = _make_response(reasoning="step by step")
        data = extract_response_data(resp)
        assert data["reasoning"] == "step by step"

    def test_extracts_confidence(self):
        resp = _make_response(confidence=0.95)
        data = extract_response_data(resp)
        assert data["confidence"] == 0.95

    def test_extracts_tokens(self):
        resp = _make_response(tokens=250)
        data = extract_response_data(resp)
        assert data["tokens"] == 250

    def test_extracts_cost_usd(self):
        resp = _make_response(estimated_cost_usd=0.03)
        data = extract_response_data(resp)
        assert data["cost_usd"] == 0.03

    def test_tool_calls_empty_list_when_none(self):
        resp = _make_response(tool_calls=None)
        data = extract_response_data(resp)
        assert data["tool_calls"] == []

    def test_tool_calls_list_returned_as_is(self):
        tc = [{"name": "search", "args": {}}]
        resp = _make_response(tool_calls=tc)
        data = extract_response_data(resp)
        assert data["tool_calls"] == tc


# ---------------------------------------------------------------------------
# TestExtractResponseMetrics
# ---------------------------------------------------------------------------


class TestExtractResponseMetrics:
    """extract_response_metrics extracts metrics with safe defaults."""

    def test_extracts_tokens(self):
        resp = _make_response(tokens=300)
        metrics = extract_response_metrics(resp, duration=1.0)
        assert metrics["tokens"] == 300

    def test_tokens_default_to_zero_when_none(self):
        resp = _make_response(tokens=None)
        resp.tokens = None
        metrics = extract_response_metrics(resp, duration=0.5)
        assert metrics["tokens"] == 0

    def test_extracts_cost(self):
        resp = _make_response(estimated_cost_usd=0.02)
        metrics = extract_response_metrics(resp, duration=0.5)
        assert metrics["cost_usd"] == 0.02

    def test_cost_default_to_zero_when_none(self):
        resp = _make_response()
        resp.estimated_cost_usd = None
        metrics = extract_response_metrics(resp, duration=0.5)
        assert metrics["cost_usd"] == 0.0

    def test_duration_passed_through(self):
        resp = _make_response()
        metrics = extract_response_metrics(resp, duration=3.14)
        assert metrics["duration_seconds"] == 3.14

    def test_tool_calls_count_when_list(self):
        tc = [MagicMock(), MagicMock()]
        resp = _make_response(tool_calls=tc)
        metrics = extract_response_metrics(resp, duration=1.0)
        assert metrics["tool_calls"] == 2

    def test_tool_calls_zero_when_none(self):
        resp = _make_response(tool_calls=None)
        metrics = extract_response_metrics(resp, duration=1.0)
        assert metrics["tool_calls"] == 0
