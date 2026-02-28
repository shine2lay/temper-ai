"""Tests for temper_ai.interfaces.server.optimization_routes."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.optimization_routes import (
    CompileRequest,
    TrainingExampleModel,
    _handle_compile_program,
    _handle_list_programs,
    _handle_preview_program,
    _run_dspy_compile,
    create_optimization_router,
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
    app.include_router(create_optimization_router(auth_enabled=auth_enabled))
    if auth_enabled:
        app.dependency_overrides[require_auth] = _mock_auth()
    return TestClient(app, raise_server_exceptions=False)


class TestRunDspyCompile:
    def test_import_error(self):
        body = CompileRequest(
            agent_name="test",
            training_examples=[],
        )
        compiler = MagicMock()
        store = MagicMock()

        with patch.dict("sys.modules", {"dspy": None}):
            with pytest.raises(HTTPException) as exc_info:
                _run_dspy_compile(body, compiler, store, [], MagicMock())
            assert exc_info.value.status_code == 500

    def test_generic_error(self):
        body = CompileRequest(
            agent_name="test",
            training_examples=[],
        )
        compiler = MagicMock()
        compiler.compile.side_effect = RuntimeError("fail")
        store = MagicMock()

        # Make dspy importable but compilation fails
        import types

        mock_dspy = types.ModuleType("dspy")

        class MockModule:
            pass

        class MockPredict:
            def __init__(self, sig):
                pass

        mock_dspy.Module = MockModule
        mock_dspy.Predict = MockPredict

        with patch.dict("sys.modules", {"dspy": mock_dspy}):
            with pytest.raises(HTTPException) as exc_info:
                _run_dspy_compile(body, compiler, store, [], MagicMock())
            assert exc_info.value.status_code == 500


class TestRunDspyCompileSuccess:
    def test_successful_compile(self):
        import types

        mock_dspy = types.ModuleType("dspy")

        class MockModule:
            def __init__(self):
                super().__init__()

        class MockPredict:
            def __init__(self, sig):
                pass

        mock_dspy.Module = MockModule
        mock_dspy.Predict = MockPredict

        body = CompileRequest(
            agent_name="test-agent",
            training_examples=[
                TrainingExampleModel(
                    inputs={"q": "hi"}, outputs={"a": "hello"}, score=0.9
                ),
            ],
        )
        compiler = MagicMock()
        compile_result = MagicMock()
        compile_result.program_data = {"compiled": True}
        compile_result.train_score = 0.95
        compile_result.val_score = 0.88
        compile_result.num_examples = 1
        compile_result.num_demos = 1
        compiler.compile.return_value = compile_result

        store = MagicMock()
        store.save.return_value = "program-id-1"

        with patch.dict("sys.modules", {"dspy": mock_dspy}):
            result = _run_dspy_compile(body, compiler, store, [], MagicMock())

        assert result["program_id"] == "program-id-1"
        assert result["agent_name"] == "test-agent"
        assert result["train_score"] == 0.95
        assert result["status"] == "compiled"


class TestHandleCompileProgram:
    @patch("temper_ai.optimization.dspy.program_store.CompiledProgramStore")
    @patch("temper_ai.optimization.dspy.compiler.DSPyCompiler")
    @patch("temper_ai.interfaces.server.optimization_routes._run_dspy_compile")
    def test_success(self, mock_run, mock_compiler_cls, mock_store_cls):
        mock_run.return_value = {
            "program_id": "p1",
            "agent_name": "agent",
            "train_score": 0.9,
            "val_score": 0.8,
            "num_examples": 5,
            "num_demos": 2,
            "status": "compiled",
        }

        body = CompileRequest(
            agent_name="agent",
            training_examples=[
                TrainingExampleModel(inputs={"q": "x"}, outputs={"a": "y"}, score=1.0),
            ],
        )
        result = _handle_compile_program(body)
        assert result["program_id"] == "p1"
        mock_run.assert_called_once()


class TestHandleListPrograms:
    @patch("temper_ai.optimization.dspy.program_store.CompiledProgramStore")
    def test_success(self, mock_store_cls):
        mock_store = MagicMock()
        mock_store.list_programs.return_value = [{"id": "p1"}]
        mock_store_cls.return_value = mock_store

        result = _handle_list_programs(None)
        assert result["total"] == 1

    @patch("temper_ai.optimization.dspy.program_store.CompiledProgramStore")
    def test_with_agent_filter(self, mock_store_cls):
        mock_store = MagicMock()
        mock_store.list_programs.return_value = []
        mock_store_cls.return_value = mock_store

        result = _handle_list_programs("my-agent")
        assert result["total"] == 0
        mock_store.list_programs.assert_called_with(agent_name="my-agent")

    @patch("temper_ai.optimization.dspy.program_store.CompiledProgramStore")
    def test_error_raises_500(self, mock_store_cls):
        mock_store = MagicMock()
        mock_store.list_programs.side_effect = RuntimeError("fail")
        mock_store_cls.return_value = mock_store

        with pytest.raises(HTTPException) as exc_info:
            _handle_list_programs(None)
        assert exc_info.value.status_code == 500


class TestHandlePreviewProgram:
    @patch("temper_ai.optimization.dspy.program_store.CompiledProgramStore")
    def test_found(self, mock_store_cls):
        mock_store = MagicMock()
        mock_store.load_latest.return_value = {"program": "data"}
        mock_store_cls.return_value = mock_store

        result = _handle_preview_program("agent1")
        assert result == {"program": "data"}

    @patch("temper_ai.optimization.dspy.program_store.CompiledProgramStore")
    def test_not_found(self, mock_store_cls):
        mock_store = MagicMock()
        mock_store.load_latest.return_value = None
        mock_store_cls.return_value = mock_store

        with pytest.raises(HTTPException) as exc_info:
            _handle_preview_program("missing")
        assert exc_info.value.status_code == 404


class TestOptimizationRouterIntegration:
    @patch("temper_ai.optimization.dspy.program_store.CompiledProgramStore")
    def test_list_programs(self, mock_store_cls):
        mock_store = MagicMock()
        mock_store.list_programs.return_value = []
        mock_store_cls.return_value = mock_store

        client = _make_client()
        resp = client.get("/api/optimization/programs")
        assert resp.status_code == 200

    @patch("temper_ai.optimization.dspy.program_store.CompiledProgramStore")
    def test_preview_program(self, mock_store_cls):
        mock_store = MagicMock()
        mock_store.load_latest.return_value = {"data": "test"}
        mock_store_cls.return_value = mock_store

        client = _make_client()
        resp = client.get("/api/optimization/programs/agent1/preview")
        assert resp.status_code == 200
