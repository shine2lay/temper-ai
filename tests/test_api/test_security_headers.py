"""Framing policy: deny by default, allow-list only when explicitly configured.

The dashboard is not embeddable unless an operator names the origins that may
frame it (TEMPER_FRAME_ANCESTORS) — for example a private pi-web-ui instance on
the same tailnet showing runs beside its chats. X-Frame-Options cannot express
an allow-list, so a configured allow-list is published as CSP frame-ancestors
and XFO is omitted (a browser honouring XFO DENY would otherwise block the very
origin that was just allowed).
"""

import pytest

from temper_ai.server import frame_ancestors


class TestFrameAncestors:
    def test_unset_means_no_origins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEMPER_FRAME_ANCESTORS", raising=False)
        assert frame_ancestors() == ""

    def test_blank_is_treated_as_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPER_FRAME_ANCESTORS", "   ")
        assert frame_ancestors() == ""

    def test_single_origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPER_FRAME_ANCESTORS", "https://pi.example.com")
        assert frame_ancestors() == "https://pi.example.com"

    @pytest.mark.parametrize(
        "raw",
        [
            "https://pi.example.com https://host.ts.net:8787",
            "https://pi.example.com,https://host.ts.net:8787",
            "  https://pi.example.com ,\thttps://host.ts.net:8787  ",
        ],
    )
    def test_space_or_comma_separated(self, raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPER_FRAME_ANCESTORS", raw)
        assert frame_ancestors() == "https://pi.example.com https://host.ts.net:8787"

    def test_wildcard_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """"*" would let any site frame the dashboard — an allow-list must be explicit."""
        monkeypatch.setenv("TEMPER_FRAME_ANCESTORS", "*")
        assert frame_ancestors() == ""

    def test_wildcard_does_not_poison_valid_origins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPER_FRAME_ANCESTORS", "* https://pi.example.com")
        assert frame_ancestors() == "https://pi.example.com"

    def test_bare_hostnames_are_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CSP frame-ancestors needs origins; a bare host is a config mistake."""
        monkeypatch.setenv("TEMPER_FRAME_ANCESTORS", "pi.example.com https://ok.example.com")
        assert frame_ancestors() == "https://ok.example.com"


class TestSecurityHeadersMiddleware:
    """Headers on a real response, through the actual middleware stack."""

    @staticmethod
    def _client():
        from fastapi.testclient import TestClient

        from temper_ai.server import app

        return TestClient(app)

    def test_default_denies_framing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEMPER_FRAME_ANCESTORS", raising=False)
        response = self._client().get("/health")
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    def test_allow_list_publishes_csp_and_drops_xfo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPER_FRAME_ANCESTORS", "https://pi.example.com")
        response = self._client().get("/health")
        assert response.headers["Content-Security-Policy"] == (
            "frame-ancestors 'self' https://pi.example.com"
        )
        # XFO DENY alongside the allow-list would defeat it in XFO-honouring browsers.
        assert "X-Frame-Options" not in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    def test_policy_is_read_per_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No import-time caching: flipping the env var takes effect on restart-free reads."""
        client = self._client()
        monkeypatch.delenv("TEMPER_FRAME_ANCESTORS", raising=False)
        assert client.get("/health").headers["X-Frame-Options"] == "DENY"
        monkeypatch.setenv("TEMPER_FRAME_ANCESTORS", "https://pi.example.com")
        assert "X-Frame-Options" not in client.get("/health").headers
