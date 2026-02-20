"""Tests for API key authentication middleware."""
import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from temper_ai.interfaces.server.auth import APIKeyMiddleware


def _create_app(api_key: str | None = None) -> FastAPI:
    """Create a test app with auth middleware."""
    app = FastAPI()
    app.add_middleware(APIKeyMiddleware, api_key=api_key)

    @app.get("/api/health")
    def health():
        return {"status": "healthy"}

    @app.get("/api/health/ready")
    def readiness():
        return {"status": "ready"}

    @app.get("/api/runs")
    def list_runs():
        return {"runs": []}

    @app.post("/api/runs")
    def create_run():
        return {"execution_id": "exec-1"}

    return app


class TestAPIKeyMiddleware:
    """Test API key authentication."""

    def test_auth_disabled_when_no_key(self) -> None:
        """All requests pass when no API key is configured."""
        app = _create_app(api_key=None)
        client = TestClient(app)
        resp = client.get("/api/runs")
        assert resp.status_code == 200

    def test_valid_key_passes(self) -> None:
        """Valid API key allows access."""
        app = _create_app(api_key="test-secret")
        client = TestClient(app)
        resp = client.get("/api/runs", headers={"X-API-Key": "test-secret"})
        assert resp.status_code == 200

    def test_invalid_key_returns_401(self) -> None:
        """Invalid API key returns 401."""
        app = _create_app(api_key="test-secret")
        client = TestClient(app)
        resp = client.get("/api/runs", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401
        assert "Invalid or missing API key" in resp.json()["detail"]

    def test_missing_key_returns_401(self) -> None:
        """Missing API key header returns 401."""
        app = _create_app(api_key="test-secret")
        client = TestClient(app)
        resp = client.get("/api/runs")
        assert resp.status_code == 401

    def test_health_bypasses_auth(self) -> None:
        """Health endpoint bypasses authentication."""
        app = _create_app(api_key="test-secret")
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_readiness_bypasses_auth(self) -> None:
        """Readiness endpoint bypasses authentication."""
        app = _create_app(api_key="test-secret")
        client = TestClient(app)
        resp = client.get("/api/health/ready")
        assert resp.status_code == 200

    def test_post_requires_auth(self) -> None:
        """POST endpoints also require auth."""
        app = _create_app(api_key="test-secret")
        client = TestClient(app)
        resp = client.post("/api/runs", json={})
        assert resp.status_code == 401

    def test_env_var_fallback(self) -> None:
        """API key can be loaded from TEMPER_API_KEY env var."""
        with patch.dict(os.environ, {"TEMPER_API_KEY": "env-secret"}):
            app = _create_app()  # No explicit key → reads env
            client = TestClient(app)
            resp = client.get("/api/runs")
            assert resp.status_code == 401

            resp = client.get("/api/runs", headers={"X-API-Key": "env-secret"})
            assert resp.status_code == 200
