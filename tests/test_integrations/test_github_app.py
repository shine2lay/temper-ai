"""temper's GitHub app: its login, its tokens, and where its key may be.

Pinned: the app signs a short JSON Web Token with its private key and trades
it for an installation token, which is used again until five minutes before
it runs out; a token works on one repository and does only what temper does,
however much more the app was given; the app works only where it is
installed; a run (no key) gets its tokens from temper's server; and the key
is taken out of the environment, so nothing temper starts inherits it.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from temper_ai.integrations.github import app as github_app
from temper_ai.integrations.github import secret
from temper_ai.integrations.github.app import (
    GitHubApp,
    GitHubAppError,
    NotInstalled,
    ServerApp,
    pem_of,
    scoped,
)

API = "https://api.github.test"
INSTALLED = {"shine2lay/temper-ai": 99, "shine2lay/roamee": 99}
# What the owner gave the real app: more than temper uses.
GRANTED = {"actions": "write", "checks": "write", "code_quality": "write", "contents": "write",
           "issues": "write", "metadata": "read", "pull_requests": "write", "repository_hooks": "write",
           "security_events": "write"}
TEMPERS = {"contents": "write", "issues": "write", "pull_requests": "write", "metadata": "read"}


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def pem(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


class Clock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


class FakeGitHub:
    """GitHub's app endpoints, enough of them."""

    def __init__(self, clock: Clock, installed: dict[str, int] | None = None) -> None:
        self.clock = clock
        self.installed = dict(INSTALLED if installed is None else installed)
        self.granted = dict(GRANTED)
        self.calls: list[tuple[str, str, str]] = []  # (method, path, authorization)
        self.token_bodies: list[dict | None] = []
        self.jwts: list[str] = []
        self.made = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        path = request.url.path
        self.calls.append((request.method, path, auth))
        if path == "/app":
            self.jwts.append(auth.removeprefix("Bearer "))
            return httpx.Response(200, json={"id": 1234, "slug": "shine-temper", "name": "shine-temper",
                                             "owner": {"login": "shine2lay"}})
        if path.startswith("/repos/") and path.endswith("/installation"):
            self.jwts.append(auth.removeprefix("Bearer "))
            repo = path[len("/repos/"):-len("/installation")]
            if repo.lower() in self.installed:
                return httpx.Response(200, json={"id": self.installed[repo.lower()],
                                                 "permissions": dict(self.granted)})
            return httpx.Response(404, json={"message": "Not Found"})
        if path.startswith("/app/installations/") and path.endswith("/access_tokens"):
            self.jwts.append(auth.removeprefix("Bearer "))
            body = json.loads(request.content) if request.content else None
            self.token_bodies.append(body)
            asked = (body or {}).get("permissions") or {}
            if any(github_app.level(self.granted.get(name)) < github_app.level(access)
                   for name, access in asked.items()):
                # GitHub refuses a token asking for more than the installation has.
                return httpx.Response(422, json={"message": "The permissions requested are not granted "
                                                            "to this installation."})
            self.made += 1
            return httpx.Response(201, json={"token": f"ghs_install_{self.made}",
                                             "expires_at": iso(self.clock.now + 3600)})
        if path.startswith("/app/installations/"):
            self.jwts.append(auth.removeprefix("Bearer "))
            install_id = int(path.rsplit("/", 1)[1])
            return httpx.Response(200, json={"id": install_id, "permissions": dict(self.granted)})
        if path == "/app/installations":
            return httpx.Response(200, json=[{"id": i, "permissions": dict(self.granted)}
                                             for i in sorted(set(self.installed.values()))])
        if path == "/installation/repositories":
            return httpx.Response(200, json={"repositories": [{"full_name": r} for r in sorted(self.installed)]})
        if path.startswith("/repos/"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def gh(clock):
    return FakeGitHub(clock)


@pytest.fixture
def the_app(pem, gh, clock):
    return GitHubApp("1234", pem, api_url=API, transport=httpx.MockTransport(gh.handler), clock=clock)


def b64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


class TestTheAppsLogin:
    def test_a_json_web_token_signed_with_the_key(self, the_app, key, clock):
        header, claims, signature = the_app.jwt().split(".")
        assert json.loads(b64url_decode(header)) == {"alg": "RS256", "typ": "JWT"}
        body = json.loads(b64url_decode(claims))
        assert body["iss"] == "1234"
        assert body["iat"] <= clock.now <= body["exp"]
        assert body["exp"] - body["iat"] <= 600  # GitHub takes ten minutes at most
        key.public_key().verify(b64url_decode(signature), f"{header}.{claims}".encode(),
                                padding.PKCS1v15(), hashes.SHA256())  # raises if it does not verify

    def test_whoami(self, the_app):
        assert the_app.whoami()["slug"] == "shine-temper"

    @pytest.mark.parametrize("form", ["pem", "escaped", "base64", "quoted"])
    def test_the_key_in_any_form_env_files_allow(self, pem, form):
        value = {"pem": pem, "escaped": pem.replace("\n", "\\n"),
                 "base64": base64.b64encode(pem.encode()).decode(), "quoted": f'"{pem}"'}[form]
        assert pem_of(value).strip() == pem.encode().strip()
        GitHubApp("1", value)  # loads

    def test_not_a_key(self):
        with pytest.raises(GitHubAppError, match="neither a PEM key nor base64"):
            GitHubApp("1", "not a key")
        with pytest.raises(GitHubAppError, match="GITHUB_APP_ID is not set"):
            GitHubApp("", "whatever")


class TestInstallationTokens:
    def test_made_once_and_used_again(self, the_app, gh):
        first = the_app.installation_token("shine2lay/temper-ai")
        second = the_app.installation_token("shine2lay/temper-ai")
        assert first == second == "ghs_install_1"
        assert gh.made == 1 and the_app.tokens_made == 1

    def test_made_again_five_minutes_before_it_runs_out(self, the_app, gh, clock):
        the_app.installation_token("shine2lay/temper-ai")
        clock.now += 3600 - 301
        assert the_app.installation_token("shine2lay/temper-ai") == "ghs_install_1"
        clock.now += 2
        assert the_app.installation_token("shine2lay/temper-ai") == "ghs_install_2"
        assert gh.made == 2

    def test_a_token_works_on_one_repository(self, the_app, gh):
        the_app.installation_token("shine2lay/temper-ai")
        the_app.installation_token("shine2lay/roamee")
        assert [b["repositories"] for b in gh.token_bodies] == [["temper-ai"], ["roamee"]]
        assert gh.made == 2  # one per repository, not shared

    def test_a_token_does_only_what_temper_does(self, the_app, gh):
        """The app may also run workflows, change webhooks...: its tokens never can."""
        the_app.installation_token("shine2lay/temper-ai")
        assert gh.token_bodies == [{"repositories": ["temper-ai"], "permissions": TEMPERS}]
        assert github_app.PERMISSIONS == TEMPERS

    def test_never_more_than_the_installation_grants(self, the_app, gh):
        gh.granted = {"metadata": "read", "issues": "write", "pull_requests": "read"}
        assert the_app.installation_token("shine2lay/temper-ai") == "ghs_install_1"
        assert gh.token_bodies[0]["permissions"] == {"issues": "write", "pull_requests": "read",
                                                     "metadata": "read"}

    def test_after_the_owner_takes_a_permission_back(self, the_app, gh, clock):
        the_app.installed_repos()  # knows the installation, and what it grants
        gh.granted.pop("contents")
        clock.now += 10
        with pytest.raises(GitHubAppError, match="422: The permissions requested are not granted"):
            the_app.installation_token("shine2lay/temper-ai")
        assert the_app.installation_token("shine2lay/temper-ai") == "ghs_install_2"  # read again
        assert "contents" not in gh.token_bodies[-1]["permissions"]

    def test_a_whole_installation_s_token_only_lists_its_repositories(self, the_app, gh):
        the_app.installed_repos()
        assert gh.token_bodies == [{"permissions": {"metadata": "read"}}]

    def test_what_it_asks_for_given_what_is_granted(self):
        assert scoped(GRANTED) == TEMPERS
        assert scoped({"contents": "read", "metadata": "read"}) == {"contents": "read", "metadata": "read"}
        assert scoped({"contents": "admin", "issues": "none"}) == {"contents": "write"}
        assert scoped({}) == {}

    def test_the_login_to_get_one_is_the_apps_token(self, the_app, gh):
        the_app.installation_token("shine2lay/temper-ai")
        assert gh.jwts and all(j.count(".") == 2 for j in gh.jwts)

    def test_not_installed_there(self, the_app, gh):
        with pytest.raises(NotInstalled, match="not installed on someone/else"):
            the_app.installation_token("someone/else")
        assert gh.made == 0

    @pytest.mark.parametrize("repo", ["", "temper-ai", "a/b/c", "../x", "a/b c"])
    def test_not_a_repository(self, the_app, repo):
        with pytest.raises(GitHubAppError, match="is not an owner/name repository"):
            the_app.installation_token(repo)

    def test_a_call_on_a_repo_goes_as_the_app(self, the_app, gh):
        response = the_app.request("GET", "shine2lay/temper-ai", "/issues/1")
        assert response.status_code == 200
        method, path, auth = gh.calls[-1]
        assert (method, path, auth) == ("GET", "/repos/shine2lay/temper-ai/issues/1", "Bearer ghs_install_1")

    def test_neither_key_nor_token_is_in_an_error(self, pem, clock):
        def refuse(request):
            return httpx.Response(401, json={"message": "Bad credentials"})

        refusing = GitHubApp("1234", pem, api_url=API, transport=httpx.MockTransport(refuse), clock=clock)
        with pytest.raises(GitHubAppError) as caught:
            refusing.installation_token("shine2lay/temper-ai")
        text = str(caught.value)
        assert "401" in text and "Bad credentials" in text
        assert "PRIVATE KEY" not in text and refusing.jwt() not in text  # the clock stands still


class TestWhereItIsInstalled:
    def test_every_repo_of_every_installation(self, the_app):
        assert the_app.installed_repos() == frozenset({"shine2lay/temper-ai", "shine2lay/roamee"})
        assert the_app.is_installed("Shine2lay/Temper-AI")
        assert not the_app.is_installed("someone/else")

    def test_asked_again_after_five_minutes(self, the_app, gh, clock):
        the_app.installed_repos()
        gh.installed["shine2lay/new"] = 99
        assert "shine2lay/new" not in the_app.installed_repos()
        clock.now += 301
        assert "shine2lay/new" in the_app.installed_repos()


class FakeServer:
    """temper's server, as a run sees it: tokens for one repository each."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.asked: list[dict] = []
        self.auth: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.auth.append(request.headers.get("authorization", ""))
        if request.url.host == "api.github.test":
            return httpx.Response(200, json={"authorization": request.headers.get("authorization")})
        if request.url.path == "/api/github/token":
            body = json.loads(request.content)
            self.asked.append(body)
            if body["repo"] != "shine2lay/temper-ai":
                return httpx.Response(404, json={"detail": f"the app is not installed on {body['repo']}"})
            return httpx.Response(200, json={"repo": body["repo"], "token": f"ghs_run_{len(self.asked)}",
                                             "expires_at": iso(self.clock.now + 3600)})
        if request.url.path == "/api/github/repos":
            return httpx.Response(200, json={"repos": ["shine2lay/temper-ai"]})
        return httpx.Response(404)


class TestARunsApp:
    @pytest.fixture
    def server(self, clock):
        return FakeServer(clock)

    @pytest.fixture
    def run_app(self, server, clock):
        return ServerApp("http://server:8420", "api-token", api_url=API,
                         transport=httpx.MockTransport(server.handler), clock=clock)

    def test_asks_the_server_for_a_token_and_uses_it_again(self, run_app, server):
        assert run_app.installation_token("shine2lay/temper-ai") == "ghs_run_1"
        assert run_app.installation_token("shine2lay/temper-ai") == "ghs_run_1"
        assert server.asked == [{"repo": "shine2lay/temper-ai"}]
        assert server.auth[0] == "Bearer api-token"

    def test_calls_github_with_that_token(self, run_app):
        response = run_app.request("GET", "shine2lay/temper-ai", "/issues/1")
        assert response.json() == {"authorization": "Bearer ghs_run_1"}

    def test_the_server_says_where_the_app_is_installed(self, run_app):
        assert run_app.installed_repos() == frozenset({"shine2lay/temper-ai"})

    def test_a_repo_the_app_is_not_on(self, run_app):
        with pytest.raises(GitHubAppError, match="not installed on someone/else"):
            run_app.installation_token("someone/else")

    def test_only_one_repository_at_a_time(self, run_app):
        with pytest.raises(GitHubAppError, match="one repository at a time"):
            run_app.installation_token()

    def test_asks_with_the_run_s_own_key_while_the_run_goes_on(self, run_app, server):
        """The run's GitHub-token key names the run to the server's write guard (api/run_tokens.py)."""
        github_app.use_run_key("tghk_this_run")
        try:
            run_app.installation_token("shine2lay/temper-ai")
            run_app.installed_repos()
        finally:
            github_app.use_run_key(None)
        assert server.auth[:2] == ["Bearer tghk_this_run", "Bearer tghk_this_run"]

    def test_without_a_run_key_it_asks_as_before(self, run_app, server):
        run_app.installed_repos()
        assert server.auth == ["Bearer api-token"]

    def test_the_server_down(self, clock):
        def down(request):
            raise httpx.ConnectError("refused")

        run_app = ServerApp("http://server:8420", transport=httpx.MockTransport(down), clock=clock)
        with pytest.raises(GitHubAppError, match="temper's server did not answer"):
            run_app.installation_token("shine2lay/temper-ai")


class TestWhereTheKeyIs:
    @pytest.fixture(autouse=True)
    def _fresh(self):
        secret.forget()
        github_app.set_app(None)
        yield
        secret.forget()
        github_app.set_app(None)

    def test_taken_out_of_the_environment(self, monkeypatch, pem):
        import os

        monkeypatch.setenv(secret.PRIVATE_KEY_ENV, pem)
        monkeypatch.setenv(secret.WEBHOOK_SECRET_ENV, "whsec")
        secret.take()
        assert secret.PRIVATE_KEY_ENV not in os.environ
        assert secret.WEBHOOK_SECRET_ENV not in os.environ
        assert secret.private_key() == pem.strip() and secret.webhook_secret() == "whsec"

    def test_the_server_holds_the_app(self, monkeypatch, pem):
        monkeypatch.setenv(secret.PRIVATE_KEY_ENV, pem)
        monkeypatch.setenv(github_app.APP_ID_ENV, "1234")
        assert isinstance(github_app.get_app(), GitHubApp)
        assert isinstance(github_app.server_app(), GitHubApp)

    def test_only_a_process_without_the_key_asks_the_server(self, monkeypatch, pem):
        assert github_app.asks_server_for_tokens() is True
        monkeypatch.setenv(secret.PRIVATE_KEY_ENV, pem)
        assert github_app.asks_server_for_tokens() is False

    def test_a_run_holds_only_a_way_to_ask_the_server(self, monkeypatch):
        monkeypatch.setenv(github_app.APP_ID_ENV, "1234")
        monkeypatch.setenv("TEMPER_API", "http://server:8420")
        run_app = github_app.get_app()
        assert isinstance(run_app, ServerApp) and run_app.server_url == "http://server:8420"
        with pytest.raises(GitHubAppError, match="GITHUB_APP_PRIVATE_KEY is not set"):
            github_app.server_app()

    def test_a_run_s_environment_never_has_it(self):
        env = {"PATH": "/bin", secret.PRIVATE_KEY_ENV: "k", secret.WEBHOOK_SECRET_ENV: "w",
               secret.CLIENT_SECRET_ENV: "c", "GITHUB_APP_ID": "1234"}
        assert secret.without_server_only(env) == {"PATH": "/bin", "GITHUB_APP_ID": "1234"}


class TestTheServerHandsOutTokens:
    """POST /api/github/token and GET /api/github/repos: what a run's ServerApp asks."""

    @pytest.fixture
    def client(self, monkeypatch, the_app, pem):
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from temper_ai.api.auth import TokenAuthMiddleware
        from temper_ai.api.github_tokens import router

        secret.forget()
        monkeypatch.setenv(secret.PRIVATE_KEY_ENV, pem)
        monkeypatch.setenv(github_app.APP_ID_ENV, "1234")
        monkeypatch.delenv("TEMPER_API_TOKEN", raising=False)
        github_app.set_app(the_app)
        app = FastAPI()
        app.include_router(router)
        app.add_middleware(TokenAuthMiddleware)
        yield TestClient(app)
        github_app.set_app(None)
        secret.forget()

    def test_a_token_for_one_repository(self, client, gh, clock):
        response = client.post("/api/github/token", json={"repo": "shine2lay/temper-ai"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["repo"], body["token"]) == ("shine2lay/temper-ai", "ghs_install_1")
        assert datetime.fromisoformat(body["expires_at"]).timestamp() == clock.now + 3600
        assert gh.token_bodies == [{"repositories": ["temper-ai"], "permissions": TEMPERS}]

    def test_not_where_the_app_is_not_installed(self, client, gh):
        response = client.post("/api/github/token", json={"repo": "someone/else"})
        assert response.status_code == 404 and "not installed on someone/else" in response.json()["detail"]
        assert gh.made == 0

    @pytest.mark.parametrize("repo", ["", "temper-ai", "a/b/c", "../x/y"])
    def test_not_a_repository(self, client, repo):
        assert client.post("/api/github/token", json={"repo": repo}).status_code == 400

    def test_where_the_app_is_installed(self, client):
        response = client.get("/api/github/repos")
        assert response.json() == {"repos": sorted(INSTALLED)}

    def test_not_set_up(self, client, monkeypatch):
        monkeypatch.delenv(github_app.APP_ID_ENV)
        response = client.post("/api/github/token", json={"repo": "shine2lay/temper-ai"})
        assert response.status_code == 503 and "GITHUB_APP_ID is not set" in response.json()["detail"]
        assert client.get("/api/github/repos").status_code == 503

    def test_behind_the_api_token_when_one_is_set(self, client, monkeypatch):
        monkeypatch.setenv("TEMPER_API_TOKEN", "api-token")
        assert client.post("/api/github/token", json={"repo": "shine2lay/temper-ai"}).status_code == 401
        assert client.get("/api/github/repos").status_code == 401
        ok = client.get("/api/github/repos", headers={"Authorization": "Bearer api-token"})
        assert ok.status_code == 200

    def test_a_run_s_app_gets_its_token_here(self, client, the_app):
        """End to end: a run's ServerApp, talking to this router, acts as the app."""

        def to_server(request: httpx.Request) -> httpx.Response:
            if request.url.host == "server":
                answer = client.request(request.method, request.url.path, content=request.content,
                                        headers={"content-type": "application/json"})
                return httpx.Response(answer.status_code, content=answer.content,
                                      headers={"content-type": "application/json"})
            return httpx.Response(200, json={"authorization": request.headers.get("authorization")})

        run_app = ServerApp("http://server:8420", api_url=API, transport=httpx.MockTransport(to_server))
        assert run_app.request("GET", "shine2lay/temper-ai", "/issues/1").json() == \
            {"authorization": "Bearer ghs_install_1"}
        assert run_app.installed_repos() == frozenset(INSTALLED)
