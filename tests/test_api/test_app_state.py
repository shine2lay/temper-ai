"""Tests for the AppState shared state management."""

import threading

import pytest

from temper_ai.api.app_state import AppState
from temper_ai.api.routes import init_app_state, _state
from temper_ai.config import ConfigStore
from temper_ai.memory import InMemoryStore, MemoryService
from temper_ai.stage.loader import GraphLoader


class TestAppState:
    def test_creation(self):
        store = ConfigStore()
        state = AppState(
            config_store=store,
            graph_loader=GraphLoader(store),
            llm_providers={"test": "provider"},
            memory_service=MemoryService(InMemoryStore()),
        )
        assert state.config_store is store
        assert state.llm_providers == {"test": "provider"}
        assert isinstance(state.running, dict)
        assert isinstance(state.gates, dict)
        assert len(state.running) == 0
        assert len(state.gates) == 0

    def test_running_dict_independent(self):
        store = ConfigStore()
        state = AppState(
            config_store=store,
            graph_loader=GraphLoader(store),
            llm_providers={},
            memory_service=MemoryService(InMemoryStore()),
        )
        event = threading.Event()
        state.running["test-id"] = event
        assert "test-id" in state.running
        state.running.pop("test-id")
        assert "test-id" not in state.running


class TestInitAppState:
    def test_init_and_access(self):
        store = ConfigStore()
        state = AppState(
            config_store=store,
            graph_loader=GraphLoader(store),
            llm_providers={"mock": "provider"},
            memory_service=MemoryService(InMemoryStore()),
        )
        init_app_state(state)
        retrieved = _state()
        assert retrieved is state
        assert retrieved.llm_providers == {"mock": "provider"}

    def test_state_raises_before_init(self):
        # Reset state
        from temper_ai.api import routes
        old = routes._app_state
        routes._app_state = None
        try:
            with pytest.raises(RuntimeError, match="not initialized"):
                _state()
        finally:
            routes._app_state = old
