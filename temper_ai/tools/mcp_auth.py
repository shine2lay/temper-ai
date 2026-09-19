"""OAuth for HTTP MCP servers: authorize once, store the grant, refresh unattended.

The MCP SDK already implements the protocol half — dynamic client
registration, PKCE, the authorization code exchange and refresh — behind
``mcp.client.auth.OAuthClientProvider``, which is an ``httpx.Auth``. What it
does not decide is *where the grant lives*, and that is the whole difference
between "log in every run" and "log in once". It asks for a ``TokenStorage``;
this module provides one backed by the temper database, so the API server, a
CLI run and a container worker all read the same grant.

Tokens are encrypted before they are stored. A refresh token is a standing
key to someone's Notion workspace, and the database is shared infrastructure
that gets dumped, replicated and backed up; plaintext there would outlive any
intention to clean it up. The sealing key comes from ``TEMPER_SECRET_KEY`` if
set, otherwise from ``~/.temper/secret.key``, which is created 0600 on first
use — deployments pin the env var so the key survives container rebuilds,
while a laptop needs no setup at all.

Failure is deliberately closed and legible. No key, wrong key, or a grant
sealed under a previous key does not fall back to plaintext and does not
raise out of a tool call: it reads as "this server is not connected", and the
operator is told to run ``temper connect <server>`` again.
"""

import asyncio
import hashlib
import json
import logging
import os
import socket
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

SECRET_KEY_ENV_VAR = "TEMPER_SECRET_KEY"  # noqa: S105 - variable name, not a secret
DEFAULT_KEY_PATH = Path.home() / ".temper" / "secret.key"
DEFAULT_CALLBACK_PORT = 8765
# The client identity temper presents at dynamic registration. Servers show
# this to the human on the consent screen, so it names temper, not the model.
CLIENT_NAME = "temper"
CLIENT_URI = "https://github.com/shine2lay/temper-ai"


class MCPAuthError(Exception):
    """Raised when an OAuth grant cannot be obtained, sealed or opened."""


# -- key management ----------------------------------------------------------


def _load_or_create_key(key_path: Path | None = None) -> bytes:
    """Resolve the sealing key: env var first, then a 0600 file we may create.

    The env var wins so a deployment can pin one key across replicas and
    rebuilds. The file exists so a developer never has to think about this.
    """
    env_key = os.environ.get(SECRET_KEY_ENV_VAR)
    if env_key:
        key = env_key.strip().encode()
        if not _is_valid_fernet_key(key):
            raise MCPAuthError(
                f"{SECRET_KEY_ENV_VAR} is not a valid key. Generate one with:\n"
                "  python -c \"from cryptography.fernet import Fernet; "
                'print(Fernet.generate_key().decode())"'
            )
        return key

    path = key_path or DEFAULT_KEY_PATH
    if path.exists():
        key = path.read_bytes().strip()
        if not _is_valid_fernet_key(key):
            raise MCPAuthError(
                f"{path} does not contain a valid key. Delete it to have a new one "
                f"generated, then re-run `temper connect` for each server "
                f"(stored grants sealed with the old key become unreadable)."
            )
        return key

    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create 0600 up front rather than chmod-after: between an open(0644) and
    # a chmod there is a window where the key is world-readable on disk.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    logger.info("Generated a new MCP credential key at %s", path)
    return key


def _is_valid_fernet_key(key: bytes) -> bool:
    try:
        from cryptography.fernet import Fernet

        Fernet(key)
        return True
    except Exception:
        return False


def key_fingerprint(key: bytes) -> str:
    """A short, non-reversible id for a key, stored alongside sealed rows.

    Lets a read say "sealed with a different key" instead of failing to
    decrypt for reasons nobody can see.
    """
    return hashlib.sha256(key).hexdigest()[:16]


@dataclass(frozen=True)
class _StoredGrant:
    """A detached snapshot of one credential row.

    Read inside the session and returned by value: handing out a live
    SQLModel instance means every later attribute access hits an expired,
    session-less object (DetachedInstanceError).
    """

    tokens_encrypted: str
    client_info_encrypted: str | None
    key_id: str
    server_url: str
    updated_at: Any


@dataclass(frozen=True)
class _Sealer:
    key: bytes

    @property
    def key_id(self) -> str:
        return key_fingerprint(self.key)

    def seal(self, payload: dict[str, Any]) -> str:
        from cryptography.fernet import Fernet

        raw = json.dumps(payload, separators=(",", ":")).encode()
        return Fernet(self.key).encrypt(raw).decode()

    def open(self, ciphertext: str) -> dict[str, Any] | None:
        """Decrypt, or None if this key cannot open it. Never raises."""
        from cryptography.fernet import Fernet, InvalidToken

        try:
            raw = Fernet(self.key).decrypt(ciphertext.encode())
        except (InvalidToken, ValueError, TypeError):
            return None
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return result if isinstance(result, dict) else None


def _sealer(key_path: Path | None = None) -> _Sealer:
    return _Sealer(_load_or_create_key(key_path))


# -- token storage -----------------------------------------------------------


class DatabaseTokenStore:
    """``mcp.client.auth.TokenStorage`` over the ``mcp_credentials`` table.

    The SDK calls these four methods; everything else here exists to keep the
    encryption and the "unreadable means disconnected" rule in one place.

    The MCP protocol methods are async but the queries underneath are sync
    SQLModel — each is a single primary-key hit on a local connection, so it
    runs inline rather than through a thread hop.
    """

    def __init__(self, server_name: str, server_url: str = "", key_path: Path | None = None):
        self.server_name = server_name
        self.server_url = server_url
        self._key_path = key_path
        self._sealer_cache: _Sealer | None = None

    @property
    def _seal(self) -> _Sealer:
        if self._sealer_cache is None:
            self._sealer_cache = _sealer(self._key_path)
        return self._sealer_cache

    # -- sync core (usable from CLI code that is not in an event loop) --

    def _row(self) -> _StoredGrant | None:
        from sqlmodel import select

        from temper_ai.database.session import get_session
        from temper_ai.tools.mcp_models import MCPCredential

        with get_session() as session:
            stmt = select(MCPCredential).where(MCPCredential.server_name == self.server_name)
            row = session.exec(stmt).first()
            if row is None:
                return None
            return _StoredGrant(
                tokens_encrypted=row.tokens_encrypted,
                client_info_encrypted=row.client_info_encrypted,
                key_id=row.key_id,
                server_url=row.server_url,
                updated_at=row.updated_at,
            )

    def _read(self, column: str) -> dict[str, Any] | None:
        row = self._row()
        if row is None:
            return None
        if row.key_id and row.key_id != self._seal.key_id:
            logger.warning(
                "MCP server '%s' has a stored grant sealed with a different key "
                "(stored %s, current %s). Re-run `temper connect %s`.",
                self.server_name, row.key_id, self._seal.key_id, self.server_name,
            )
            return None
        # A config that repoints a name at another endpoint must not reuse the
        # old server's grant — same name, different resource, different consent.
        if self.server_url and row.server_url and row.server_url != self.server_url:
            logger.warning(
                "MCP server '%s' is configured for %s but the stored grant is for %s. "
                "Re-run `temper connect %s`.",
                self.server_name, self.server_url, row.server_url, self.server_name,
            )
            return None
        ciphertext = getattr(row, column)
        if not ciphertext:
            return None
        opened = self._seal.open(ciphertext)
        if opened is None:
            logger.warning(
                "MCP server '%s' has a stored grant that could not be decrypted. "
                "Re-run `temper connect %s`.",
                self.server_name, self.server_name,
            )
        return opened

    def _write(self, **columns: str) -> None:
        from datetime import UTC, datetime

        from sqlmodel import select

        from temper_ai.database.session import get_session
        from temper_ai.tools.mcp_models import MCPCredential

        with get_session() as session:
            stmt = select(MCPCredential).where(MCPCredential.server_name == self.server_name)
            row = session.exec(stmt).first()
            if row is None:
                row = MCPCredential(
                    server_name=self.server_name,
                    tokens_encrypted="",
                    key_id=self._seal.key_id,
                    server_url=self.server_url,
                )
            for column, value in columns.items():
                setattr(row, column, value)
            # Any write re-stamps identity: the row is now sealed with this
            # key, for this URL, whatever it held before.
            row.key_id = self._seal.key_id
            if self.server_url:
                row.server_url = self.server_url
            row.updated_at = datetime.now(UTC)
            session.add(row)

    def delete(self) -> bool:
        """Forget this server's grant. True if there was one."""
        from sqlmodel import select

        from temper_ai.database.session import get_session
        from temper_ai.tools.mcp_models import MCPCredential

        with get_session() as session:
            stmt = select(MCPCredential).where(MCPCredential.server_name == self.server_name)
            row = session.exec(stmt).first()
            if row is None:
                return False
            session.delete(row)
            return True

    def describe(self) -> dict[str, Any]:
        """Connection status for `temper connections`, without exposing tokens."""
        row = self._row()
        if row is None:
            return {"connected": False, "reason": "never authorized"}
        if row.key_id and row.key_id != self._seal.key_id:
            return {"connected": False, "reason": "sealed with a different key", "url": row.server_url}
        tokens = self._seal.open(row.tokens_encrypted) if row.tokens_encrypted else None
        if tokens is None:
            return {"connected": False, "reason": "grant could not be decrypted", "url": row.server_url}
        return {
            "connected": True,
            "url": row.server_url,
            "has_refresh_token": bool(tokens.get("refresh_token")),
            "updated_at": row.updated_at,
        }

    # -- the TokenStorage protocol the SDK calls --

    async def get_tokens(self) -> Any | None:
        from mcp.shared.auth import OAuthToken

        data = self._read("tokens_encrypted")
        if data is None:
            return None
        try:
            return OAuthToken.model_validate(data)
        except Exception:
            logger.warning("MCP server '%s': stored tokens are malformed", self.server_name)
            return None

    async def set_tokens(self, tokens: Any) -> None:
        self._write(tokens_encrypted=self._seal.seal(tokens.model_dump(mode="json")))

    async def get_client_info(self) -> Any | None:
        from mcp.shared.auth import OAuthClientInformationFull

        data = self._read("client_info_encrypted")
        if data is None:
            return None
        try:
            return OAuthClientInformationFull.model_validate(data)
        except Exception:
            logger.warning("MCP server '%s': stored client info is malformed", self.server_name)
            return None

    async def set_client_info(self, client_info: Any) -> None:
        self._write(client_info_encrypted=self._seal.seal(client_info.model_dump(mode="json")))


# -- building the httpx.Auth for a configured server -------------------------


def oauth_configured(config: dict) -> bool:
    """Whether this server config asks for OAuth."""
    return str(config.get("auth", "")).lower() in ("oauth", "oauth2")


def build_oauth_provider(
    config: dict,
    *,
    callback_port: int = DEFAULT_CALLBACK_PORT,
    interactive: bool = False,
    manual: bool = False,
) -> Any:
    """An ``httpx.Auth`` that attaches (and silently refreshes) the stored grant.

    ``interactive`` decides what happens when there is no usable grant. During
    a run it is False: the handlers raise instead of trying to open a browser
    on a headless worker, so the failure says "not connected" rather than
    hanging forever waiting for a callback that cannot arrive.

    ``manual`` is for the case the loopback redirect cannot work at all: a
    headless or remote box where the browser is on a different machine, so
    nothing can reach ``localhost`` here. The human approves anywhere, the
    redirect fails harmlessly in their browser, and they paste the URL back.
    """
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata

    server_name = config.get("name", "unnamed")
    url = config["url"]
    port = int(config.get("callback_port", callback_port))
    redirect_uri = f"http://localhost:{port}/callback"

    storage = DatabaseTokenStore(server_name, server_url=url)
    metadata = OAuthClientMetadata(
        client_name=CLIENT_NAME,
        client_uri=CLIENT_URI,  # type: ignore[arg-type]  # pydantic coerces str -> AnyHttpUrl
        redirect_uris=[redirect_uri],  # type: ignore[list-item]
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
        scope=config.get("scope"),
    )

    if interactive and manual:
        redirect_handler = _browser_redirect_handler
        callback_handler = _make_manual_callback_handler()
    elif interactive:
        redirect_handler = _browser_redirect_handler
        callback_handler = _make_callback_handler(port)
    else:
        redirect_handler = _make_refuse_redirect(server_name)
        callback_handler = _make_refuse_callback(server_name)

    return OAuthClientProvider(
        server_url=url,
        client_metadata=metadata,
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


def _make_refuse_redirect(server_name: str) -> Any:
    async def _refuse(authorization_url: str) -> None:
        raise MCPAuthError(
            f"MCP server '{server_name}' needs authorization and this process cannot "
            f"open a browser. Run `temper connect {server_name}` once on a machine "
            f"with a browser; the stored grant is then reused automatically."
        )

    return _refuse


def _make_refuse_callback(server_name: str) -> Any:
    async def _refuse() -> tuple[str, str | None]:
        raise MCPAuthError(
            f"MCP server '{server_name}' is not connected. Run `temper connect {server_name}`."
        )

    return _refuse


# -- the interactive half: browser + loopback callback -----------------------


async def _browser_redirect_handler(authorization_url: str) -> None:
    """Send the human to the consent screen."""
    opened = False
    try:
        opened = webbrowser.open(authorization_url)
    except Exception:  # pragma: no cover - platform dependent
        opened = False
    if not opened:
        print("\nOpen this URL to authorize:\n")
    else:
        print("\nOpened your browser to authorize. If it did not open, use:\n")
    print(f"  {authorization_url}\n")


class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches the one redirect the authorization server sends back."""

    result: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(parsed.query)
        code = params.get("code", [""])[0]
        state = params.get("state", [""])[0]
        error = params.get("error", [""])[0]

        type(self).result = {"code": code, "state": state, "error": error}

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if error:
            body = f"<h2>Authorization failed</h2><p>{error}</p>"
        else:
            body = "<h2>Connected.</h2><p>You can close this tab and return to the terminal.</p>"
        self.wfile.write(f"<html><body style='font-family:system-ui'>{body}</body></html>".encode())

    def log_message(self, *args: Any) -> None:
        """Silence the default stderr access log."""


def _make_callback_handler(port: int) -> Any:
    async def _wait_for_callback() -> tuple[str, str | None]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _serve_one_callback, port)

    return _wait_for_callback


def _serve_one_callback(port: int, timeout: float = 300.0) -> tuple[str, str | None]:
    """Serve exactly one request on the loopback callback port, then stop."""
    _CallbackHandler.result = {}
    try:
        server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    except OSError as exc:
        raise MCPAuthError(
            f"Cannot listen on localhost:{port} for the OAuth redirect ({exc}). "
            f"Free the port, or set `callback_port` in the server's YAML config."
        ) from exc

    server.timeout = timeout
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout)
    server.server_close()

    result = _CallbackHandler.result
    if not result:
        raise MCPAuthError(
            f"Timed out after {int(timeout)}s waiting for the authorization redirect."
        )
    if result.get("error"):
        raise MCPAuthError(f"Authorization was refused: {result['error']}")
    if not result.get("code"):
        raise MCPAuthError("Authorization redirect carried no code.")
    return result["code"], result.get("state") or None


def parse_pasted_callback(pasted: str) -> tuple[str, str | None]:
    """Pull ``(code, state)`` out of whatever the human pasted.

    Accepts the whole redirected URL, just its query string, or a bare code,
    because all three are things people actually paste. The code is taken
    percent-decoded: providers issue codes containing ``:`` and friends, and
    a raw paste carries them as ``%3A``.
    """
    text = pasted.strip().strip('"').strip("'")
    if not text:
        raise MCPAuthError("Nothing pasted.")

    query = ""
    if "?" in text:
        query = urlparse(text).query or text.split("?", 1)[1]
    elif "=" in text:
        query = text

    if query:
        params = parse_qs(query)
        if params.get("error"):
            raise MCPAuthError(f"Authorization was refused: {params['error'][0]}")
        code = (params.get("code") or [""])[0]
        state = (params.get("state") or [""])[0] or None
        if not code:
            raise MCPAuthError(
                "That URL has no `code` parameter. Paste the full URL your browser "
                "was redirected to after approving."
            )
        return code, state

    # A bare code, pasted without the surrounding URL.
    return text, None


def _make_manual_callback_handler() -> Any:
    async def _prompt() -> tuple[str, str | None]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _read_pasted_callback)

    return _prompt


def _read_pasted_callback() -> tuple[str, str | None]:
    print(
        "After you approve, the browser will fail to open a localhost URL.\n"
        "That is expected on this machine. Copy that URL from the address bar\n"
        "and paste it here.\n"
    )
    try:
        pasted = input("Redirected URL: ")
    except EOFError as exc:
        raise MCPAuthError("No input available to read the authorization code.") from exc
    return parse_pasted_callback(pasted)


def find_free_port(preferred: int) -> int:
    """The preferred port if it is free, else an ephemeral one.

    Only used by `temper connect`: the redirect URI is registered during that
    same flow, so a fallback port is consistent with what the server is told.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def generate_key() -> str:
    """A fresh sealing key, for `TEMPER_SECRET_KEY` in a deployment."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()
