"""Tests for temper_ai.interfaces.server.visualize_routes."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.visualize_routes import (
    VisualizeRequest,
    _extract_stage_info,
    _handle_visualize_workflow,
    _load_workflow_config,
    _render_dag_output,
    create_visualize_router,
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


def _make_client(config_root="/tmp/test-configs", auth_enabled=False):
    app = FastAPI()
    app.include_router(
        create_visualize_router(config_root=config_root, auth_enabled=auth_enabled)
    )
    if auth_enabled:
        app.dependency_overrides[require_auth] = _mock_auth()
    return TestClient(app, raise_server_exceptions=False)


class TestLoadWorkflowConfig:
    def test_path_traversal_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _load_workflow_config("/tmp/configs", "../../etc/passwd")
        assert exc_info.value.status_code == 400

    def test_file_not_found_raises_404(self):
        with pytest.raises(HTTPException) as exc_info:
            _load_workflow_config("/tmp/configs", "nonexistent.yaml")
        assert exc_info.value.status_code == 404

    def test_valid_file(self, tmp_path):
        (tmp_path / "test.yaml").write_text("workflow:\n  name: test")
        result = _load_workflow_config(str(tmp_path), "test.yaml")
        assert result["workflow"]["name"] == "test"

    def test_invalid_yaml_raises_400(self, tmp_path):
        (tmp_path / "bad.yaml").write_bytes(b"\x00\x01\x02")
        with pytest.raises(HTTPException) as exc_info:
            _load_workflow_config(str(tmp_path), "bad.yaml")
        assert exc_info.value.status_code == 400


class TestExtractStageInfo:
    def test_string_stages(self):
        names, refs = _extract_stage_info(["stage_a", "stage_b"])
        assert names == ["stage_a", "stage_b"]
        assert refs == ["stage_a", "stage_b"]

    def test_dict_stages(self):
        stages = [{"name": "s1", "extra": "data"}, {"name": "s2"}]
        names, refs = _extract_stage_info(stages)
        assert names == ["s1", "s2"]
        assert len(refs) == 2

    def test_dict_without_name_skipped(self):
        stages = [{"extra": "data"}]
        names, refs = _extract_stage_info(stages)
        assert names == []

    def test_mixed_types(self):
        stages = ["stage_a", {"name": "stage_b"}]
        names, refs = _extract_stage_info(stages)
        assert names == ["stage_a", "stage_b"]


class TestRenderDagOutput:
    @patch("temper_ai.interfaces.server.visualize_routes.export_mermaid", create=True)
    def test_mermaid(self, mock_mermaid):
        mock_mermaid.return_value = "graph TD"
        dag = MagicMock()
        with patch(
            "temper_ai.workflow.dag_visualizer.export_mermaid",
            return_value="graph TD",
        ):
            result = _render_dag_output(dag, "mermaid")
        assert result is not None

    def test_json_format(self):
        dag = MagicMock()
        dag.topo_order = ["a", "b"]
        dag.roots = ["a"]
        dag.terminals = ["b"]
        dag.predecessors = {"b": ["a"]}
        dag.successors = {"a": ["b"]}
        result = _render_dag_output(dag, "json")
        assert result["topo_order"] == ["a", "b"]

    def test_unsupported_format(self):
        dag = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            _render_dag_output(dag, "svg")
        assert exc_info.value.status_code == 400


class TestHandleVisualizeWorkflow:
    def test_no_stages(self, tmp_path):
        (tmp_path / "test.yaml").write_text("workflow:\n  name: test\n  stages: []")
        body = VisualizeRequest(workflow="test.yaml")
        result = _handle_visualize_workflow(body, str(tmp_path))
        assert result["message"] == "Workflow has no stages"

    def test_empty_config(self, tmp_path):
        (tmp_path / "test.yaml").write_text("---")
        body = VisualizeRequest(workflow="test.yaml")
        result = _handle_visualize_workflow(body, str(tmp_path))
        assert result["stages"] == []

    @patch("temper_ai.interfaces.server.visualize_routes.build_stage_dag", create=True)
    @patch(
        "temper_ai.interfaces.server.visualize_routes.has_dag_dependencies", create=True
    )
    def test_dag_value_error(self, mock_has_deps, mock_build_dag, tmp_path):
        (tmp_path / "test.yaml").write_text(
            "workflow:\n  name: test\n  stages:\n    - stage_a"
        )
        with patch(
            "temper_ai.workflow.dag_builder.build_stage_dag",
            side_effect=ValueError("cyclic"),
        ):
            body = VisualizeRequest(workflow="test.yaml")
            with pytest.raises(HTTPException) as exc_info:
                _handle_visualize_workflow(body, str(tmp_path))
            assert exc_info.value.status_code == 400

    @patch(
        "temper_ai.workflow.dag_builder.build_stage_dag",
        side_effect=RuntimeError("boom"),
    )
    def test_dag_generic_error(self, mock_build, tmp_path):
        (tmp_path / "test.yaml").write_text(
            "workflow:\n  name: test\n  stages:\n    - stage_a"
        )
        body = VisualizeRequest(workflow="test.yaml")
        with pytest.raises(HTTPException) as exc_info:
            _handle_visualize_workflow(body, str(tmp_path))
        assert exc_info.value.status_code == 500


class TestVisualizeRouterIntegration:
    def test_no_stages(self, tmp_path):
        (tmp_path / "test.yaml").write_text("workflow:\n  name: test\n  stages: []")
        client = _make_client(config_root=str(tmp_path))
        resp = client.post("/api/visualize", json={"workflow": "test.yaml"})
        assert resp.status_code == 200
        assert resp.json()["message"] == "Workflow has no stages"
