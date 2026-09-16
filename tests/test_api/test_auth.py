"""Token authentication at the HTTP edge.

The case that matters most is the MCP endpoint: its tools call the API's
route functions in-process, so authentication attached to those handlers
would have checked HTTP callers and waved every MCP call through. These
tests pin the behaviour that /mcp is covered by the same check as /api.
"""

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient

from temper_ai.api.auth import TokenAuthMiddleware, configured_token

TOKEN = "s3cret-token"  # noqa: S105


@pytest.fixture
def client():
    async def ok(request):
        return JSONResponse({"ok": True})

    async def socket(websocket):
        await websocket.accept()
        await websocket.send_json({"ok": True})
        await websocket.close()

    app = Starlette(
        routes=[
            Route("/api/health", ok),
            Route("/api/workflows", ok),
            Route("/api/runs", ok, methods=["POST"]),
            Route("/mcp", ok, methods=["POST"]),
            Route("/app", ok),
            Route("/app/assets/index.js", ok),
            WebSocketRoute("/ws/{execution_id}", socket),
        ]
    )
    app.add_middleware(TokenAuthMiddleware)
    return TestClient(app)


class TestDisabledByDefault:
    def test_no_token_configured_means_no_checks(self, client, monkeypatch):
        monkeypatch.delenv("TEMPER_API_TOKEN", raising=False)
        assert client.get("/api/workflows").status_code == 200
        assert client.post("/mcp").status_code == 200
        assert configured_token() is None

    def test_an_empty_token_does_not_enable_it(self, client, monkeypatch):
        monkeypatch.setenv("TEMPER_API_TOKEN", "   ")
        assert client.get("/api/workflows").status_code == 200


class TestEnforcement:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch):
        monkeypatch.setenv("TEMPER_API_TOKEN", TOKEN)

    def test_api_requires_a_token(self, client):
        assert client.get("/api/workflows").status_code == 401

    def test_mcp_requires_a_token(self, client):
        """The whole reason this is middleware and not a route dependency."""
        assert client.post("/mcp").status_code == 401

    def test_starting_a_run_requires_a_token(self, client):
        assert client.post("/api/runs").status_code == 401

    def test_a_bearer_token_is_accepted(self, client):
        response = client.get("/api/workflows", headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200

    def test_a_wrong_token_is_rejected(self, client):
        response = client.get("/api/workflows", headers={"Authorization": "Bearer nope"})
        assert response.status_code == 401

    def test_the_header_alternative_works(self, client):
        assert client.get("/api/workflows", headers={"X-Temper-Token": TOKEN}).status_code == 200

    def test_a_cookie_works_so_the_dashboard_can_hold_it(self, client):
        client.cookies.set("temper_token", TOKEN)
        assert client.get("/api/workflows").status_code == 200

    def test_health_stays_open_for_container_checks(self, client):
        assert client.get("/api/health").status_code == 200

    def test_the_dashboard_shell_loads_so_a_token_can_be_entered(self, client):
        # Static HTML and JS carrying no data; every data call it then
        # makes is checked.
        assert client.get("/app").status_code == 200
        assert client.get("/app/assets/index.js").status_code == 200

    def test_the_rejection_says_what_to_send(self, client):
        response = client.get("/api/workflows")
        assert "Authorization: Bearer" in response.json()["detail"]
        assert response.headers["www-authenticate"].startswith("Bearer")


class TestWebSocket:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch):
        monkeypatch.setenv("TEMPER_API_TOKEN", TOKEN)

    def test_a_socket_without_a_token_is_closed(self, client):
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc:  # noqa: PT012
            with client.websocket_connect("/ws/abc") as ws:
                ws.receive_json()
        assert exc.value.code == 4401

    def test_a_token_in_the_query_string_is_accepted(self, client):
        """Browsers cannot set headers on a WebSocket handshake."""
        with client.websocket_connect(f"/ws/abc?token={TOKEN}") as ws:
            assert ws.receive_json() == {"ok": True}
