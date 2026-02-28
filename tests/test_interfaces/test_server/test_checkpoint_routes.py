"""Tests for temper_ai.interfaces.server.checkpoint_routes."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.checkpoint_routes import (
    CheckpointResumeRequest,
    _handle_get_checkpoint,
    _handle_list_checkpoints,
    _handle_resume_checkpoint,
    create_checkpoint_router,
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
    app.include_router(create_checkpoint_router(auth_enabled=auth_enabled))
    if auth_enabled:
        app.dependency_overrides[require_auth] = _mock_auth()
    return TestClient(app, raise_server_exceptions=False)


class TestHandleListCheckpoints:
    @patch("temper_ai.workflow.checkpoint_manager.CheckpointManager")
    def test_success(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        mock_mgr.list_checkpoints.return_value = [{"id": "cp1"}]
        mock_mgr_cls.return_value = mock_mgr

        result = _handle_list_checkpoints("wf1")
        assert result["total"] == 1
        assert result["workflow_id"] == "wf1"

    @patch("temper_ai.workflow.checkpoint_manager.CheckpointManager")
    def test_error_raises_500(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        mock_mgr.list_checkpoints.side_effect = RuntimeError("db error")
        mock_mgr_cls.return_value = mock_mgr

        with pytest.raises(HTTPException) as exc_info:
            _handle_list_checkpoints("wf1")
        assert exc_info.value.status_code == 500


class TestHandleGetCheckpoint:
    @patch("temper_ai.workflow.checkpoint_manager.CheckpointManager")
    def test_found(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        domain_state = MagicMock()
        domain_state.current_stage = "stage1"
        domain_state.stage_outputs = {"stage1": "output"}
        mock_mgr.load_checkpoint.return_value = domain_state
        mock_mgr_cls.return_value = mock_mgr

        result = _handle_get_checkpoint("cp1", "wf1")
        assert result["checkpoint_id"] == "cp1"
        assert result["current_stage"] == "stage1"

    @patch("temper_ai.workflow.checkpoint_manager.CheckpointManager")
    def test_not_found(self, mock_mgr_cls):
        from temper_ai.workflow.checkpoint_backends import CheckpointNotFoundError

        mock_mgr = MagicMock()
        mock_mgr.load_checkpoint.side_effect = CheckpointNotFoundError("not found")
        mock_mgr_cls.return_value = mock_mgr

        with pytest.raises(HTTPException) as exc_info:
            _handle_get_checkpoint("missing", "wf1")
        assert exc_info.value.status_code == 404

    @patch("temper_ai.workflow.checkpoint_manager.CheckpointManager")
    def test_generic_error_raises_500(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        mock_mgr.load_checkpoint.side_effect = RuntimeError("boom")
        mock_mgr_cls.return_value = mock_mgr

        with pytest.raises(HTTPException) as exc_info:
            _handle_get_checkpoint("cp1", "wf1")
        assert exc_info.value.status_code == 500


class TestHandleResumeCheckpoint:
    @patch("temper_ai.workflow.checkpoint_manager.CheckpointManager")
    def test_success(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        domain_state = MagicMock()
        domain_state.current_stage = "stage2"
        mock_mgr.load_checkpoint.return_value = domain_state
        mock_mgr_cls.return_value = mock_mgr

        body = CheckpointResumeRequest(workflow_id="wf1")
        result = _handle_resume_checkpoint("cp1", body)
        assert result["status"] == "resumed"
        assert result["resume_stage"] == "stage2"

    @patch("temper_ai.workflow.checkpoint_manager.CheckpointManager")
    def test_not_found(self, mock_mgr_cls):
        from temper_ai.workflow.checkpoint_backends import CheckpointNotFoundError

        mock_mgr = MagicMock()
        mock_mgr.load_checkpoint.side_effect = CheckpointNotFoundError("not found")
        mock_mgr_cls.return_value = mock_mgr

        body = CheckpointResumeRequest(workflow_id="wf1")
        with pytest.raises(HTTPException) as exc_info:
            _handle_resume_checkpoint("missing", body)
        assert exc_info.value.status_code == 404

    @patch("temper_ai.workflow.checkpoint_manager.CheckpointManager")
    def test_generic_error_raises_500(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        mock_mgr.load_checkpoint.side_effect = RuntimeError("boom")
        mock_mgr_cls.return_value = mock_mgr

        body = CheckpointResumeRequest(workflow_id="wf1")
        with pytest.raises(HTTPException) as exc_info:
            _handle_resume_checkpoint("cp1", body)
        assert exc_info.value.status_code == 500


class TestCheckpointRouterIntegration:
    @patch("temper_ai.workflow.checkpoint_manager.CheckpointManager")
    def test_list_checkpoints(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        mock_mgr.list_checkpoints.return_value = []
        mock_mgr_cls.return_value = mock_mgr

        client = _make_client()
        resp = client.get("/api/checkpoints?workflow_id=wf1")
        assert resp.status_code == 200

    @patch("temper_ai.workflow.checkpoint_manager.CheckpointManager")
    def test_get_checkpoint(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        ds = MagicMock()
        ds.current_stage = "s1"
        ds.stage_outputs = {}
        mock_mgr.load_checkpoint.return_value = ds
        mock_mgr_cls.return_value = mock_mgr

        client = _make_client()
        resp = client.get("/api/checkpoints/cp1?workflow_id=wf1")
        assert resp.status_code == 200

    @patch("temper_ai.workflow.checkpoint_manager.CheckpointManager")
    def test_resume_checkpoint(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        ds = MagicMock()
        ds.current_stage = "s2"
        mock_mgr.load_checkpoint.return_value = ds
        mock_mgr_cls.return_value = mock_mgr

        client = _make_client()
        resp = client.post(
            "/api/checkpoints/cp1/resume",
            json={"workflow_id": "wf1"},
        )
        assert resp.status_code == 200
