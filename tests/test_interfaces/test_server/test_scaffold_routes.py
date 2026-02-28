"""Tests for temper_ai.interfaces.server.scaffold_routes."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.scaffold_routes import (
    ScaffoldRequest,
    _generate_zip_archive,
    _handle_scaffold_project,
    create_scaffold_router,
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


def _make_client(templates_dir=None, auth_enabled=False):
    app = FastAPI()
    td = templates_dir or Path("/tmp/test-templates")
    app.include_router(
        create_scaffold_router(templates_dir=td, auth_enabled=auth_enabled)
    )
    if auth_enabled:
        app.dependency_overrides[require_auth] = _mock_auth()
    return TestClient(app, raise_server_exceptions=False)


class TestGenerateZipArchive:
    def test_creates_zip(self, tmp_path):
        (tmp_path / "file.txt").write_text("hello")
        result = _generate_zip_archive(tmp_path, "test-project")
        assert result.media_type == "application/zip"
        assert "test-project" in result.headers.get("Content-Disposition", "")


class TestHandleScaffoldProject:
    @patch("temper_ai.workflow.templates.generator.TemplateGenerator")
    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_success(self, mock_registry_cls, mock_gen_cls, tmp_path):
        mock_gen = MagicMock()
        mock_gen.generate.return_value = None
        mock_gen_cls.return_value = mock_gen

        body = ScaffoldRequest(product_type="basic", project_name="my-project")
        result = _handle_scaffold_project(body, tmp_path)
        assert result.media_type == "application/zip"

    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_template_not_found(self, mock_registry_cls):
        from temper_ai.workflow.templates.registry import TemplateNotFoundError

        mock_registry_cls.side_effect = TemplateNotFoundError("not found")

        body = ScaffoldRequest(product_type="unknown", project_name="test")
        with pytest.raises(HTTPException) as exc_info:
            _handle_scaffold_project(body, Path("/tmp"))
        assert exc_info.value.status_code == 404

    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_generic_error(self, mock_registry_cls):
        mock_registry_cls.side_effect = RuntimeError("boom")

        body = ScaffoldRequest(product_type="basic", project_name="test")
        with pytest.raises(HTTPException) as exc_info:
            _handle_scaffold_project(body, Path("/tmp"))
        assert exc_info.value.status_code == 500


class TestScaffoldRouterIntegration:
    @patch("temper_ai.workflow.templates.generator.TemplateGenerator")
    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_scaffold_project(self, mock_registry_cls, mock_gen_cls, tmp_path):
        mock_gen = MagicMock()
        mock_gen.generate.return_value = None
        mock_gen_cls.return_value = mock_gen

        client = _make_client(templates_dir=tmp_path)
        resp = client.post(
            "/api/projects/scaffold",
            json={"product_type": "basic", "project_name": "test"},
        )
        assert resp.status_code == 200
