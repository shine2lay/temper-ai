"""Tests for temper_ai.interfaces.server.memory_routes."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.memory_routes import (
    AddMemoryRequest,
    SearchMemoryRequest,
    _handle_add_memory,
    _handle_clear_memories,
    _handle_list_memories,
    _handle_search_memories,
    create_memory_router,
)

_MOCK_AUTH_CTX = AuthContext(
    user_id="test-user",
    tenant_id="test-tenant",
    role="owner",
    api_key_id="key-test",
)


def _mock_auth():
    async def _dep():
        return _MOCK_AUTH_CTX

    return _dep


def _make_client(auth_enabled=False):
    app = FastAPI()
    app.include_router(create_memory_router(auth_enabled=auth_enabled))
    if auth_enabled:
        app.dependency_overrides[require_auth] = _mock_auth()
    return TestClient(app, raise_server_exceptions=False)


class TestHandleListMemories:
    @patch("temper_ai.memory.service.MemoryService")
    def test_success(self, mock_svc_cls):
        mock_svc = MagicMock()
        entry = MagicMock()
        entry.model_dump.return_value = {"content": "mem1"}
        mock_svc.list_memories.return_value = [entry]
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        result = _handle_list_memories("default", "", "", None, None)
        assert result["total"] == 1

    @patch("temper_ai.memory.service.MemoryService")
    def test_error_raises_500(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.list_memories.side_effect = RuntimeError("fail")
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        with pytest.raises(HTTPException) as exc_info:
            _handle_list_memories("default", "", "", None, None)
        assert exc_info.value.status_code == 500


class TestHandleAddMemory:
    @patch("temper_ai.memory.service.MemoryService")
    def test_episodic(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.store_episodic.return_value = "mem-1"
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        body = AddMemoryRequest(content="test memory", memory_type="episodic")
        result = _handle_add_memory(body)
        assert result["memory_id"] == "mem-1"
        assert result["memory_type"] == "episodic"

    @patch("temper_ai.memory.service.MemoryService")
    def test_procedural(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.store_procedural.return_value = "mem-2"
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        body = AddMemoryRequest(content="test", memory_type="procedural")
        result = _handle_add_memory(body)
        assert result["memory_type"] == "procedural"

    @patch("temper_ai.memory.service.MemoryService")
    def test_cross_session(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.store_cross_session.return_value = "mem-3"
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        body = AddMemoryRequest(content="test", memory_type="cross_session")
        result = _handle_add_memory(body)
        assert result["memory_type"] == "cross_session"

    @patch("temper_ai.memory.service.MemoryService")
    def test_error_raises_500(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.store_episodic.side_effect = RuntimeError("fail")
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        body = AddMemoryRequest(content="test")
        with pytest.raises(HTTPException) as exc_info:
            _handle_add_memory(body)
        assert exc_info.value.status_code == 500


class TestHandleSearchMemories:
    @patch("temper_ai.memory.service.MemoryService")
    def test_success(self, mock_svc_cls):
        mock_svc = MagicMock()
        entry = MagicMock()
        entry.model_dump.return_value = {"content": "result"}
        mock_svc.search.return_value = [entry]
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        body = SearchMemoryRequest(query="test query")
        result = _handle_search_memories(body)
        assert result["total"] == 1

    @patch("temper_ai.memory.service.MemoryService")
    def test_error_raises_500(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.search.side_effect = RuntimeError("fail")
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        body = SearchMemoryRequest(query="test")
        with pytest.raises(HTTPException) as exc_info:
            _handle_search_memories(body)
        assert exc_info.value.status_code == 500


class TestHandleClearMemories:
    @patch("temper_ai.memory.service.MemoryService")
    def test_success(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.clear_memories.return_value = 5
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        result = _handle_clear_memories("default", "", "", None)
        assert result["deleted"] == 5

    @patch("temper_ai.memory.service.MemoryService")
    def test_error_raises_500(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.clear_memories.side_effect = RuntimeError("fail")
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        with pytest.raises(HTTPException) as exc_info:
            _handle_clear_memories("default", "", "", None)
        assert exc_info.value.status_code == 500


class TestMemoryRouterIntegration:
    @patch("temper_ai.memory.service.MemoryService")
    def test_list_memories(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.list_memories.return_value = []
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        client = _make_client()
        resp = client.get("/api/memory")
        assert resp.status_code == 200

    @patch("temper_ai.memory.service.MemoryService")
    def test_add_memory(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.store_episodic.return_value = "m1"
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        client = _make_client()
        resp = client.post("/api/memory", json={"content": "test"})
        assert resp.status_code == 200

    @patch("temper_ai.memory.service.MemoryService")
    def test_search_memories(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.search.return_value = []
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        client = _make_client()
        resp = client.post("/api/memory/search", json={"query": "test"})
        assert resp.status_code == 200

    @patch("temper_ai.memory.service.MemoryService")
    def test_clear_memories(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.clear_memories.return_value = 0
        mock_svc.build_scope.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        client = _make_client()
        resp = client.delete("/api/memory")
        assert resp.status_code == 200
