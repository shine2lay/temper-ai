"""``temper github``: the app's manifest, making it, and where its keys go.

Pinned: the manifest asks for exactly the events and permissions the work
needs (issues, pull requests and contents read/write, metadata read), private,
with the public hook; the page that hands it to GitHub escapes it; the code
GitHub gives back is traded once, and the id, key and webhook secret land in
the env file (the key base64 on one line), replacing old values and keeping
everything else and the file's mode; nothing secret is printed; and the whole
round trip works through the page setup serves.
"""

from __future__ import annotations

import base64
import json
import stat
import threading
import time
from argparse import Namespace

import httpx
import pytest

from temper_ai.cli import github as cli
from temper_ai.integrations.github import secret

PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----\n"
MADE = {"id": 4242, "slug": "shine-temper", "name": "shine-temper", "owner": {"login": "shine2lay"},
        "html_url": "https://github.com/apps/shine-temper", "pem": PEM, "webhook_secret": "whsec-made",
        "client_id": "Iv1.abc", "client_secret": "cs-made"}


def test_the_manifest_asks_for_what_the_work_needs_and_no_more():
    made = cli.manifest("shine-temper", redirect_url="http://localhost:8765/done")
    assert made["name"] == "shine-temper" and made["public"] is False
    assert made["hook_attributes"] == {"url": "https://hooks.wai2shine.com/api/hooks/github", "active": True}
    assert sorted(made["default_events"]) == ["issue_comment", "issues", "pull_request"]
    assert made["default_permissions"] == {"issues": "write", "pull_requests": "write", "contents": "write",
                                           "metadata": "read"}
    assert made["redirect_url"] == "http://localhost:8765/done"


def test_the_page_escapes_the_manifest():
    page = cli.manifest_page(cli.manifest("x' onload='alert(1)"), cli.new_app_url(None, "st"))
    assert "action='https://github.com/settings/apps/new?state=st'" in page
    assert "x' onload" not in page and "x&#x27; onload=&#x27;alert(1)" in page


def test_under_an_organization():
    assert cli.new_app_url("roamee-org", "st") == "https://github.com/organizations/roamee-org/settings/apps/new?state=st"


class TestTheCode:
    def test_traded_once_for_the_app(self):
        asked = []

        def github(request: httpx.Request) -> httpx.Response:
            asked.append((request.method, request.url.path))
            return httpx.Response(201, json=MADE)

        assert cli.convert("abc123", transport=httpx.MockTransport(github)) == MADE
        assert asked == [("POST", "/app-manifests/abc123/conversions")]

    def test_a_used_or_old_code(self):
        refused = httpx.MockTransport(lambda request: httpx.Response(404, json={"message": "Not Found"}))
        with pytest.raises(RuntimeError, match="a code works once"):
            cli.convert("abc123", transport=refused)

    @pytest.mark.parametrize("code", ["", "../x", "a b", "a?b=c"])
    def test_not_a_code(self, code):
        with pytest.raises(ValueError, match="not a code"):
            cli.convert(code, transport=httpx.MockTransport(lambda r: httpx.Response(201, json=MADE)))


class TestTheEnvFile:
    def test_the_keys_go_in_and_everything_else_stays(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("TEMPER_GITHUB_TOKEN=ghp_mine\n# a note\nGITHUB_APP_ID=1\nLINEAR_CLIENT_ID=lin\n")
        env.chmod(0o640)
        cli.write_env(env, cli.env_values(MADE))
        lines = env.read_text().splitlines()
        assert lines[:4] == ["TEMPER_GITHUB_TOKEN=ghp_mine", "# a note", "GITHUB_APP_ID=4242", "LINEAR_CLIENT_ID=lin"]
        values = dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))
        assert base64.b64decode(values[secret.PRIVATE_KEY_ENV]).decode() == PEM
        assert values[secret.WEBHOOK_SECRET_ENV] == "whsec-made"
        assert stat.S_IMODE(env.stat().st_mode) == 0o640

    def test_a_new_file_is_only_for_its_owner(self, tmp_path):
        env = tmp_path / ".env"
        cli.write_env(env, {"A": "1"})
        assert stat.S_IMODE(env.stat().st_mode) == 0o600

    def test_an_answer_without_the_key_writes_nothing(self, tmp_path):
        with pytest.raises(RuntimeError, match="no app id, private key or webhook secret"):
            cli.env_values({**MADE, "pem": ""})

    def test_the_client_secret_is_not_kept(self):
        assert set(cli.env_values(MADE)) == {"GITHUB_APP_ID", secret.PRIVATE_KEY_ENV, secret.WEBHOOK_SECRET_ENV}


def test_convert_prints_no_secret(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "convert", lambda code: MADE)
    env = tmp_path / ".env"
    assert cli.cmd_github(Namespace(action="convert", code="abc", env_file=str(env))) == 0
    out = capsys.readouterr()
    shown = json.loads(out.out)
    assert shown["install"] == "https://github.com/apps/shine-temper/installations/new"
    assert "whsec-made" not in out.out + out.err and "MIIEow" not in out.out + out.err
    assert "whsec-made" in env.read_text()


def test_setup_round_trip(tmp_path, monkeypatch):
    """The page setup serves, GitHub's redirect back to it, and the keys in the env file."""
    monkeypatch.setattr(cli, "convert", lambda code: MADE if code == "good-code" else {})
    env = tmp_path / ".env"
    result: dict = {}

    def run():
        result.update(cli.setup(str(env), "shine-temper", cli.HOOK_URL, "127.0.0.1:18765", None, timeout=30))

    worker = threading.Thread(target=run)
    worker.start()
    page = ""
    for _ in range(100):
        try:
            page = httpx.get("http://127.0.0.1:18765/").text
            break
        except httpx.ConnectError:
            time.sleep(0.05)
    assert "Taking you to GitHub to make the app <b>shine-temper</b>" in page
    state = page.split("state=", 1)[1].split("'", 1)[0]
    assert httpx.get("http://127.0.0.1:18765/done?code=good-code&state=wrong").status_code == 400
    done = httpx.get(f"http://127.0.0.1:18765/done?code=good-code&state={state}")
    assert done.status_code == 200 and "install it" in done.text
    worker.join(10)
    assert result["app"] == "shine-temper" and "whsec-made" in env.read_text()


# --- temper github check ----------------------------------------------------------------------

NEEDED = {"contents": "write", "issues": "write", "pull_requests": "write", "metadata": "read"}


class StubApp:
    """The app as `check` asks GitHub about it."""

    def __init__(self, permissions=None, events=("issues", "issue_comment", "pull_request"), installed=None):
        self.permissions = dict(NEEDED if permissions is None else permissions)
        self.events = list(events)
        self.installed = dict(self.permissions if installed is None else installed)

    def whoami(self):
        return {"id": 5, "slug": "temper-ai-bot", "name": "temper-ai-bot", "owner": {"login": "shine2lay"},
                "html_url": "https://github.com/apps/temper-ai-bot", "permissions": self.permissions,
                "events": self.events}

    def installations(self):
        return [{"id": 9, "account": {"login": "shine2lay"}, "repository_selection": "all",
                 "permissions": self.installed}]

    def installation_token(self, repo=None, *, installation=None):
        return "ghs_stub"

    def installed_repos(self, refresh=False):
        return frozenset({"shine2lay/temper-ai"})


@pytest.fixture
def checking(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(secret.WEBHOOK_SECRET_ENV, "whsec")
    secret.forget()
    env = tmp_path / ".env"
    env.write_text("GITHUB_APP_ID=5\n")
    env.chmod(0o600)
    monkeypatch.setattr(cli, "ENV_FILES", (env, tmp_path / "absent" / ".env"))
    monkeypatch.setattr(cli, "why_not_configured", lambda: None)

    def run(app):
        monkeypatch.setattr(cli, "server_app", lambda: app)
        code = cli.check()
        return code, json.loads(capsys.readouterr().out)

    yield run, env
    secret.forget()


class TestCheck:
    def test_all_there(self, checking):
        run, _ = checking
        code, report = run(StubApp())
        assert code == 0 and "warnings" not in report and "notes" not in report
        assert report["installations"] == [{"account": "shine2lay", "repositories": "all", "token": "ok"}]

    def test_more_than_temper_uses_is_a_note(self, checking):
        run, _ = checking
        code, report = run(StubApp(permissions={**NEEDED, "actions": "write", "repository_hooks": "write"},
                                   events=("issues", "issue_comment", "pull_request", "workflow_run")))
        assert code == 0 and "warnings" not in report
        assert report["notes"] == [
            "the app may also use actions, repository_hooks: temper's tokens never carry those",
            "the app is also sent workflow_run events: temper answers and drops them",
        ]

    def test_a_missing_permission_or_event_is_a_warning(self, checking):
        run, _ = checking
        lacking = {k: v for k, v in NEEDED.items() if k != "contents"}
        code, report = run(StubApp(permissions=lacking, events=("issues", "pull_request")))
        assert code == 1
        assert report["warnings"] == [
            "the app lacks contents: write (its settings page, Permissions)",
            "the app is not sent issue_comment events (its settings page, Subscribe to events)",
        ]

    def test_an_installation_that_has_not_accepted_new_permissions(self, checking):
        run, _ = checking
        code, report = run(StubApp(installed={**NEEDED, "contents": "read"}))
        assert code == 1
        assert report["warnings"] == ["the installation on shine2lay lacks contents: write: accept the app's "
                                      "new permissions there (Settings, Applications)"]

    def test_an_env_file_others_can_read(self, checking):
        run, env = checking
        env.chmod(0o644)
        code, report = run(StubApp())
        assert code == 1
        assert report["warnings"] == [f"{env} can be read by others (and by agents, where the checkout is "
                                      "mounted): chmod 600 it"]

    def test_the_settings_name_another_app(self, checking, monkeypatch):
        from temper_ai.integrations.github.settings import GitHubSettings

        run, _ = checking
        monkeypatch.setattr(cli, "load_settings", lambda: GitHubSettings(app="shine-temper"))
        code, report = run(StubApp())
        assert code == 1
        assert report["warnings"] == ["the app is 'temper-ai-bot' but the settings say 'shine-temper'"]
