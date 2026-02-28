"""Tests for temper_ai.interfaces.server.template_routes."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.template_routes import (
    GenerateWorkflowRequest,
    _handle_generate_workflow,
    _handle_get_template,
    _handle_list_templates,
    create_template_router,
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
        create_template_router(templates_dir=td, auth_enabled=auth_enabled)
    )
    if auth_enabled:
        app.dependency_overrides[require_auth] = _mock_auth()
    return TestClient(app, raise_server_exceptions=False)


class TestHandleListTemplates:
    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_success(self, mock_registry_cls):
        mock_registry = MagicMock()
        manifest = MagicMock()
        manifest.model_dump.return_value = {
            "name": "basic",
            "description": "A basic template",
        }
        mock_registry.list_templates.return_value = [manifest]
        mock_registry_cls.return_value = mock_registry

        result = _handle_list_templates(Path("/tmp/templates"))
        assert result["total"] == 1

    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_error_raises_500(self, mock_registry_cls):
        mock_registry_cls.side_effect = RuntimeError("fail")

        with pytest.raises(HTTPException) as exc_info:
            _handle_list_templates(Path("/tmp/templates"))
        assert exc_info.value.status_code == 500


class TestHandleGetTemplate:
    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_found(self, mock_registry_cls):
        mock_registry = MagicMock()
        manifest = MagicMock()
        manifest.model_dump.return_value = {"name": "basic"}
        mock_registry.get_manifest.return_value = manifest
        mock_registry.validate_template.return_value = []
        mock_registry_cls.return_value = mock_registry

        result = _handle_get_template("basic", Path("/tmp/templates"))
        assert result["valid"] is True

    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_not_found(self, mock_registry_cls):
        from temper_ai.workflow.templates.registry import TemplateNotFoundError

        mock_registry = MagicMock()
        mock_registry.get_manifest.side_effect = TemplateNotFoundError("not found")
        mock_registry_cls.return_value = mock_registry

        with pytest.raises(HTTPException) as exc_info:
            _handle_get_template("missing", Path("/tmp/templates"))
        assert exc_info.value.status_code == 404

    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_error_raises_500(self, mock_registry_cls):
        mock_registry_cls.side_effect = RuntimeError("fail")

        with pytest.raises(HTTPException) as exc_info:
            _handle_get_template("basic", Path("/tmp/templates"))
        assert exc_info.value.status_code == 500


class TestHandleGenerateWorkflow:
    @patch("temper_ai.workflow.templates.generator.TemplateGenerator")
    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_success(self, mock_registry_cls, mock_gen_cls):
        mock_gen = MagicMock()
        mock_gen.generate.return_value = Path("/tmp/output/workflow.yaml")
        mock_gen_cls.return_value = mock_gen

        body = GenerateWorkflowRequest(
            product_type="basic", project_name="test", output_dir="/tmp/output"
        )
        result = _handle_generate_workflow(body, Path("/tmp/templates"))
        assert result["product_type"] == "basic"

    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_not_found(self, mock_registry_cls):
        from temper_ai.workflow.templates.registry import TemplateNotFoundError

        mock_registry_cls.side_effect = TemplateNotFoundError("no template")

        body = GenerateWorkflowRequest(
            product_type="unknown", project_name="test", output_dir="/tmp/output"
        )
        with pytest.raises(HTTPException) as exc_info:
            _handle_generate_workflow(body, Path("/tmp/templates"))
        assert exc_info.value.status_code == 404

    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_error_raises_500(self, mock_registry_cls):
        mock_registry_cls.side_effect = RuntimeError("fail")

        body = GenerateWorkflowRequest(
            product_type="basic", project_name="test", output_dir="/tmp/output"
        )
        with pytest.raises(HTTPException) as exc_info:
            _handle_generate_workflow(body, Path("/tmp/templates"))
        assert exc_info.value.status_code == 500


class TestTemplateRouterIntegration:
    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_list_templates(self, mock_registry_cls):
        mock_registry = MagicMock()
        mock_registry.list_templates.return_value = []
        mock_registry_cls.return_value = mock_registry

        client = _make_client()
        resp = client.get("/api/templates")
        assert resp.status_code == 200

    @patch("temper_ai.workflow.templates.registry.TemplateRegistry")
    def test_get_template(self, mock_registry_cls):
        mock_registry = MagicMock()
        manifest = MagicMock()
        manifest.model_dump.return_value = {"name": "basic"}
        mock_registry.get_manifest.return_value = manifest
        mock_registry.validate_template.return_value = []
        mock_registry_cls.return_value = mock_registry

        client = _make_client()
        resp = client.get("/api/templates/basic")
        assert resp.status_code == 200
