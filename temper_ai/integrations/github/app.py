"""temper's GitHub app: logging in as the app, and acting as it on the repos it is installed on.

GitHub work (triggers.github) is signed by the app, so everything it posts
shows as ``<app>[bot]`` and not as the owner. Linear, Notion and builds keep
using the owner's token (TEMPER_GITHUB_TOKEN in tools.github_pr).

How the app logs in. Its private key (``GITHUB_APP_PRIVATE_KEY``, held in
memory by integrations.github.secret) signs a JSON Web Token that says "I am
app ``GITHUB_APP_ID``" for ten minutes. With it temper asks GitHub for an
*installation token*: good for an hour and, when it is for one repository,
good on that repository only. It carries only ``PERMISSIONS``, what temper
does as the app (push a branch, comment, open and review pull requests),
however much more the app was given on GitHub. That token is what every call
and push uses; it is kept in memory and used again until five minutes before
it runs out. Neither the key nor a token is ever logged or put in an error
message.

Where the key is. Only in temper's server (``GitHubApp``). A run works in a
box whose shell an agent drives, so the key is kept out of it (the spawners
drop it, see ``secret.SERVER_ONLY``): a run's ``get_app()`` is a
``ServerApp``, which asks the server for a token for one repository
(``POST /api/github/token``, api.github_tokens) and never holds more than
that token. It asks with the run's own GitHub-token key, which the run's
process makes when the run starts (``use_run_key``; api/run_tokens.py) and
which may do nothing else through the API.

Which repos. The app works on the repos it is installed on, and nowhere
else: ``installed_repos`` asks GitHub (every installation, every repo), and
the answer is kept for five minutes. Installing it on one more repo is how
temper gets to work there.

The private key may be given as the PEM file's text (real newlines, or
``\\n`` in one line) or base64 of it, which fits on one line of ``.env``.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from temper_ai.integrations.github import secret

logger = logging.getLogger(__name__)

APP_ID_ENV = "GITHUB_APP_ID"
API_URL_ENV = "GITHUB_API_URL"
API_URL = "https://api.github.com"
SERVER_ENV = "TEMPER_API"                 # where a run reaches temper's server (docker-compose.yml)
SERVER_URL = "http://localhost:8420"
SERVER_TOKEN_ENV = "TEMPER_API_TOKEN"     # noqa: S105 - a variable name; the server's API token, if it has one
JWT_LIFETIME_S = 540          # GitHub takes at most 600; less, for clock skew
JWT_BACKDATE_S = 60           # iat a minute early, for clock skew the other way
TOKEN_MARGIN_S = 300          # a token is used again until five minutes before it expires
REPOS_TTL_S = 300.0           # how long the list of installed repos is trusted
INSTALL_TTL_S = 600.0         # how long a repo -> installation answer (and what it grants) is trusted
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

# What temper does as the app, and so all its tokens for a repository may do, whatever else the
# app was given: push a branch (contents), comment on issues, open and review pull requests.
PERMISSIONS = {"contents": "write", "issues": "write", "pull_requests": "write", "metadata": "read"}
# A token for a whole installation only lists its repositories.
LISTING = {"metadata": "read"}
_LEVELS = {"read": 1, "write": 2, "admin": 3}


def level(value: Any) -> int:
    """How much a permission's access is: 0 none, 1 read, 2 write, 3 admin."""
    return _LEVELS.get(str(value or "").lower(), 0)


def scoped(granted: dict[str, Any], wanted: dict[str, str] | None = None) -> dict[str, str]:
    """``wanted`` (default ``PERMISSIONS``) cut down to what ``granted`` allows: GitHub refuses a
    token that asks for more than the installation has, so a permission it lacks is left out
    (and the call that needs it fails, saying so) rather than asked for."""
    out: dict[str, str] = {}
    for name, access in (wanted or PERMISSIONS).items():
        have = str(granted.get(name) or "")
        if level(have):
            out[name] = access if level(have) >= level(access) else have
    return out


class GitHubAppError(RuntimeError):
    """The app cannot do what was asked (not set up, not installed there, GitHub said no)."""


class NotInstalled(GitHubAppError):
    """The app is not installed on that repository."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def pem_of(value: str) -> bytes:
    """The PEM bytes of a private key given as PEM text, PEM with ``\\n``, or base64 of PEM."""
    text = value.strip().strip('"').strip("'").strip()
    if "-----BEGIN" in text:
        return text.replace("\\n", "\n").encode()
    try:
        decoded = base64.b64decode("".join(text.split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GitHubAppError(f"{secret.PRIVATE_KEY_ENV} is neither a PEM key nor base64 of one") from exc
    if b"-----BEGIN" not in decoded:
        raise GitHubAppError(f"{secret.PRIVATE_KEY_ENV} is neither a PEM key nor base64 of one")
    return decoded


@dataclass
class Token:
    value: str
    expires_at: float  # unix time


def _expiry(text: Any, now: float) -> float:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return now + 3600.0  # GitHub's installation tokens last an hour


def check_repo(repo: str) -> str:
    repo = str(repo or "").strip()
    if not _REPO_RE.match(repo) or ".." in repo:
        raise GitHubAppError(f"'{repo}' is not an owner/name repository")
    return repo


def _raise_for(response: httpx.Response, doing: str) -> None:
    if response.is_success:
        return
    try:
        said = str(response.json().get("message") or response.json().get("detail") or "")
    except (ValueError, AttributeError):
        said = response.text[:200]
    raise GitHubAppError(f"could not {doing} ({response.status_code}{': ' + said if said else ''})")


class _Base:
    """What both kinds of app do the same way: calls on a repo with a token for it."""

    def __init__(self, api_url: str, transport: httpx.BaseTransport | None, clock: Callable[[], float]) -> None:
        self.api_url = api_url.rstrip("/")
        self._transport = transport
        self._clock = clock
        self._lock = threading.Lock()
        self._tokens: dict[str, Token] = {}
        self._repos: tuple[frozenset[str], float] | None = None
        self.tokens_made = 0  # how many tokens were asked for (tests, `temper github check`)

    def _client(self, token: str) -> httpx.Client:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "temper-ai",
        }
        return httpx.Client(timeout=30.0, headers=headers, transport=self._transport)

    def _held(self, key: str) -> str | None:
        now = self._clock()
        with self._lock:
            held = self._tokens.get(key)
            if held and now < held.expires_at - TOKEN_MARGIN_S:
                return held.value
        return None

    def _keep(self, key: str, token: Token) -> str:
        with self._lock:
            self._tokens[key] = token
            self.tokens_made += 1
        return token.value

    def installation_token(self, repo: str | None = None, *, installation: int | None = None) -> str:
        raise NotImplementedError

    def installed_repos(self, refresh: bool = False) -> frozenset[str]:
        raise NotImplementedError

    def is_installed(self, repo: str) -> bool:
        return check_repo(repo).lower() in self.installed_repos()

    def request(self, method: str, repo: str, path: str, **kwargs: Any) -> httpx.Response:
        """One API call on ``repo`` as the app. ``path`` starts at /repos/<repo>."""
        repo = check_repo(repo)
        token = self.installation_token(repo)
        suffix = path if path.startswith("/") or not path else "/" + path
        with self._client(token) as client:
            return client.request(method, f"{self.api_url}/repos/{repo}{suffix}", **kwargs)

    def forget_tokens(self) -> None:
        with self._lock:
            self._tokens.clear()
            self._repos = None


class GitHubApp(_Base):
    """The app itself, with its key: temper's server."""

    def __init__(
        self,
        app_id: str,
        private_key: str,
        *,
        api_url: str = API_URL,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        super().__init__(api_url, transport, clock)
        self.app_id = str(app_id).strip()
        if not self.app_id:
            raise GitHubAppError(f"{APP_ID_ENV} is not set")
        try:
            key = serialization.load_pem_private_key(pem_of(private_key), password=None)
        except GitHubAppError:
            raise
        except (ValueError, TypeError) as exc:
            raise GitHubAppError(f"{secret.PRIVATE_KEY_ENV} is not a private key temper can read") from exc
        if not isinstance(key, rsa.RSAPrivateKey):
            raise GitHubAppError(f"{secret.PRIVATE_KEY_ENV} is not an RSA key (GitHub apps sign with RS256)")
        self._key = key
        self._installs: dict[str, tuple[int, float]] = {}
        self._granted: dict[int, tuple[dict[str, Any], float]] = {}  # installation -> its permissions
        self._me: dict[str, Any] | None = None

    # --- the app's own login ------------------------------------------------------------------

    def jwt(self) -> str:
        """A JSON Web Token saying "this is the app", signed RS256 with its key."""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        now = int(self._clock())
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {"iat": now - JWT_BACKDATE_S, "exp": now + JWT_LIFETIME_S, "iss": self.app_id}
        signing_input = ".".join(
            _b64url(json.dumps(part, separators=(",", ":")).encode()) for part in (header, claims)
        )
        signature = self._key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{signing_input}.{_b64url(signature)}"

    def _as_app(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        with self._client(self.jwt()) as client:
            return client.request(method, f"{self.api_url}{path}", **kwargs)

    def whoami(self) -> dict[str, Any]:
        """The app as GitHub knows it (``slug``, ``name``, ``id``, ``owner``...)."""
        if self._me is None:
            response = self._as_app("GET", "/app")
            _raise_for(response, "read the app from GitHub")
            self._me = dict(response.json())
        return self._me

    # --- installations and their tokens --------------------------------------------------------

    def installation_id(self, repo: str) -> int:
        """The installation that covers ``repo``; an error if the app is not installed there."""
        repo = check_repo(repo)
        key = repo.lower()
        now = self._clock()
        with self._lock:
            known = self._installs.get(key)
            if known and now - known[1] < INSTALL_TTL_S:
                return known[0]
        response = self._as_app("GET", f"/repos/{repo}/installation")
        if response.status_code == 404:
            raise NotInstalled(f"the app is not installed on {repo}")
        _raise_for(response, f"find the app's installation on {repo}")
        found = response.json()
        install_id = int(found["id"])
        with self._lock:
            self._installs[key] = (install_id, now)
            if isinstance(found.get("permissions"), dict):
                self._granted[install_id] = (dict(found["permissions"]), now)
        return install_id

    def granted(self, installation: int) -> dict[str, Any]:
        """The permissions the owner granted that installation (they may lag behind the app's)."""
        now = self._clock()
        with self._lock:
            known = self._granted.get(installation)
            if known and now - known[1] < INSTALL_TTL_S:
                return known[0]
        response = self._as_app("GET", f"/app/installations/{installation}")
        _raise_for(response, "read the app's installation")
        permissions = response.json().get("permissions")
        permissions = dict(permissions) if isinstance(permissions, dict) else {}
        with self._lock:
            self._granted[installation] = (permissions, now)
        return permissions

    def token(self, repo: str | None = None, *, installation: int | None = None) -> Token:
        """A token for one repository (only that one), or for a whole installation; made or reused."""
        if repo is not None:
            repo = check_repo(repo)
        install_id = installation if installation is not None else self.installation_id(str(repo))
        key = f"{install_id}:{(repo or '*').lower()}"
        now = self._clock()
        with self._lock:
            held = self._tokens.get(key)
            if held and now < held.expires_at - TOKEN_MARGIN_S:
                return held
        # A repository's token works on that repository only, whatever else the installation
        # covers, and does only what temper does (PERMISSIONS), whatever else the app may do.
        # A whole installation's token only lists its repositories.
        body: dict[str, Any] = {"permissions": scoped(self.granted(install_id)) if repo else dict(LISTING)}
        if repo:
            body["repositories"] = [repo.split("/", 1)[1]]
        response = self._as_app("POST", f"/app/installations/{install_id}/access_tokens", json=body)
        if response.status_code in (404, 422):
            with self._lock:  # uninstalled, or its permissions changed: ask again next time
                self._granted.pop(install_id, None)
                if repo is not None:
                    self._installs.pop(repo.lower(), None)
        _raise_for(response, f"get a token for {repo or 'the installation'}")
        answer = response.json()
        made = Token(str(answer["token"]), _expiry(answer.get("expires_at"), now))
        self._keep(key, made)
        return made

    def installation_token(self, repo: str | None = None, *, installation: int | None = None) -> str:
        return self.token(repo, installation=installation).value

    def installations(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            response = self._as_app("GET", "/app/installations", params={"per_page": 100, "page": page})
            _raise_for(response, "list the app's installations")
            batch = response.json()
            if not isinstance(batch, list):
                break
            out.extend(i for i in batch if isinstance(i, dict))
            if len(batch) < 100:
                break
            page += 1
        return out

    def installed_repos(self, refresh: bool = False) -> frozenset[str]:
        """Every repo the app is installed on, as lower-case owner/name."""
        now = self._clock()
        with self._lock:
            if self._repos and not refresh and now - self._repos[1] < REPOS_TTL_S:
                return self._repos[0]
        found: set[str] = set()
        installs: dict[str, tuple[int, float]] = {}
        for install in self.installations():
            install_id = int(install["id"])
            if isinstance(install.get("permissions"), dict):
                with self._lock:
                    self._granted[install_id] = (dict(install["permissions"]), now)
            token = self.installation_token(installation=install_id)
            page = 1
            with self._client(token) as client:
                while True:
                    response = client.get(f"{self.api_url}/installation/repositories",
                                          params={"per_page": 100, "page": page})
                    _raise_for(response, "list the installation's repositories")
                    repos = response.json().get("repositories") or []
                    for r in repos:
                        name = str(r.get("full_name") or "").lower()
                        if name:
                            found.add(name)
                            installs[name] = (install_id, now)
                    if len(repos) < 100:
                        break
                    page += 1
        result = frozenset(found)
        with self._lock:
            self._repos = (result, now)
            self._installs.update(installs)
        return result

    def forget_tokens(self) -> None:
        super().forget_tokens()
        with self._lock:
            self._installs.clear()
            self._granted.clear()


class ServerApp(_Base):
    """The app as a run has it: no key, only tokens for one repository each, from temper's server."""

    def __init__(
        self,
        server_url: str = SERVER_URL,
        api_token: str | None = None,
        *,
        api_url: str = API_URL,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(api_url, transport, clock)
        self.server_url = server_url.rstrip("/")
        self._api_token = api_token

    def _ask_server(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        # The run's own key names the run to the server's write guard; the server's shared
        # API token, when a box has one, would name nobody.
        key = _this_run_key or self._api_token
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        try:
            with httpx.Client(timeout=30.0, transport=self._transport, headers=headers) as client:
                return client.request(method, f"{self.server_url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubAppError(
                f"temper's server did not answer at {self.server_url} ({type(exc).__name__})") from exc

    def installation_token(self, repo: str | None = None, *, installation: int | None = None) -> str:
        if repo is None:
            raise GitHubAppError("a run gets tokens for one repository at a time")
        repo = check_repo(repo)
        key = repo.lower()
        held = self._held(key)
        if held:
            return held
        response = self._ask_server("POST", "/api/github/token", json={"repo": repo})
        _raise_for(response, f"get a token for {repo} from temper's server")
        answer = response.json()
        return self._keep(key, Token(str(answer["token"]), _expiry(answer.get("expires_at"), self._clock())))

    def installed_repos(self, refresh: bool = False) -> frozenset[str]:
        now = self._clock()
        with self._lock:
            if self._repos and not refresh and now - self._repos[1] < REPOS_TTL_S:
                return self._repos[0]
        response = self._ask_server("GET", "/api/github/repos")
        _raise_for(response, "list the app's repositories from temper's server")
        result = frozenset(str(r).lower() for r in response.json().get("repos") or [] if str(r).strip())
        with self._lock:
            self._repos = (result, now)
        return result


# --- the process's one app ----------------------------------------------------------------------

App = GitHubApp | ServerApp
_app: App | None = None
_app_lock = threading.Lock()

# The GitHub-token key of the run this process runs (one run per box), set by the runner
# while the run goes on (runner/execute.py) and read by ServerApp when it asks the server.
_this_run_key: str | None = None


def asks_server_for_tokens() -> bool:
    """Whether this process gets its GitHub tokens from temper's server (a run in its box,
    without the app's private key) rather than making them itself (the server)."""
    return not secret.private_key()


def use_run_key(key: str | None) -> None:
    """Ask the server for tokens with this run's own GitHub-token key; None when the run ends."""
    global _this_run_key
    _this_run_key = key


def app_id() -> str | None:
    return os.environ.get(APP_ID_ENV, "").strip() or None


def configured() -> bool:
    """Whether this process holds the app itself (the id and the key): temper's server."""
    return bool(app_id() and secret.private_key())


def why_not_configured() -> str | None:
    missing = [name for name, value in ((APP_ID_ENV, app_id()), (secret.PRIVATE_KEY_ENV, secret.private_key()))
               if not value]
    return f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set" if missing else None


def get_app() -> App:
    """The app: itself where the key is (the server), else tokens from the server (a run)."""
    global _app
    with _app_lock:
        if _app is None:
            api = os.environ.get(API_URL_ENV, "").strip() or API_URL
            if secret.private_key():
                if not app_id():
                    raise GitHubAppError(f"temper's GitHub app is not set up: {APP_ID_ENV} is not set "
                                         "(see docs/github.md)")
                _app = GitHubApp(str(app_id()), str(secret.private_key()), api_url=api)
            else:
                server = os.environ.get(SERVER_ENV, "").strip() or SERVER_URL
                token = os.environ.get(SERVER_TOKEN_ENV, "").strip() or None
                _app = ServerApp(server, token, api_url=api)
        return _app


def server_app() -> GitHubApp:
    """The app with its key, for the server's own use; an error saying what is missing if it can't be."""
    reason = why_not_configured()
    if reason:
        raise GitHubAppError(f"temper's GitHub app is not set up here: {reason} (see docs/github.md)")
    app = get_app()
    if not isinstance(app, GitHubApp):
        raise GitHubAppError("temper's GitHub app is not set up here (see docs/github.md)")
    return app


def set_app(app: App | None) -> None:
    """Use this app for the process (tests), or None to set it up from the environment again."""
    global _app
    with _app_lock:
        _app = app
