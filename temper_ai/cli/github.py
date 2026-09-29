"""``temper github``: make temper's GitHub app, and check it.

    temper github setup --env-file ~/temper-ai/.env
        make the app: serves a page on this machine that hands GitHub the
        app's manifest; open it in a browser and click "Create". GitHub sends
        the browser back here, and the app's id, private key and webhook secret
        go straight into the env file. Nothing secret is printed.
    temper github convert CODE --env-file PATH
        the same last step by hand, with the code GitHub gave back.
    temper github manifest
        the app's manifest, as JSON (what setup hands GitHub).
    temper github check
        the app as GitHub knows it, where it is installed, a token for each
        installation, the webhook secret, the settings and the rules.

``setup`` and ``convert`` run where the env file is (the host); ``check`` runs
where temper runs, with its environment. See docs/github.md.
"""

from __future__ import annotations

import base64
import html
import json
import os
import secrets
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from temper_ai.integrations.github import secret
from temper_ai.integrations.github.app import (
    API_URL,
    APP_ID_ENV,
    GitHubAppError,
    server_app,
    why_not_configured,
)
from temper_ai.integrations.github.settings import load_settings

HOOK_URL = "https://hooks.wai2shine.com/api/hooks/github"
HOMEPAGE = "https://github.com/shine2lay/temper-ai"
EVENTS = ("issues", "issue_comment", "pull_request")
PERMISSIONS = {"issues": "write", "pull_requests": "write", "contents": "write", "metadata": "read"}
DEFAULT_LISTEN = "127.0.0.1:8765"
SETUP_TIMEOUT_S = 3600


def manifest(name: str, hook_url: str = HOOK_URL, redirect_url: str | None = None) -> dict[str, Any]:
    """The app GitHub is asked to make: private, these events, these permissions."""
    out: dict[str, Any] = {
        "name": name,
        "url": HOMEPAGE,
        "description": "temper: works the issues and pull requests it is asked to, and answers in the thread.",
        "hook_attributes": {"url": hook_url, "active": True},
        "public": False,
        "default_permissions": dict(PERMISSIONS),
        "default_events": list(EVENTS),
    }
    if redirect_url:
        out["redirect_url"] = redirect_url
    return out


def new_app_url(org: str | None, state: str) -> str:
    where = f"organizations/{org}/settings/apps/new" if org else "settings/apps/new"
    return f"https://github.com/{where}?state={state}"


def manifest_page(app_manifest: dict[str, Any], action: str) -> str:
    """A page that posts the manifest to GitHub as soon as it opens."""
    value = html.escape(json.dumps(app_manifest), quote=True)
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Make temper's GitHub app</title></head>"
        "<body style='font-family:sans-serif'>"
        f"<form id='f' method='post' action='{html.escape(action, quote=True)}'>"
        f"<input type='hidden' name='manifest' value='{value}'>"
        f"<p>Taking you to GitHub to make the app <b>{html.escape(str(app_manifest.get('name')))}</b>...</p>"
        "<button type='submit'>Go to GitHub</button></form>"
        "<script>document.getElementById('f').submit();</script></body></html>"
    )


def convert(code: str, api_url: str = API_URL, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """Trade the code GitHub gave back after "Create" for the new app and its secrets."""
    code = code.strip()
    if not code or not code.replace("-", "").replace("_", "").isalnum():
        raise ValueError("that is not a code GitHub gave back")
    with httpx.Client(timeout=30.0, transport=transport) as client:
        response = client.post(f"{api_url.rstrip('/')}/app-manifests/{code}/conversions",
                               headers={"Accept": "application/vnd.github+json", "User-Agent": "temper-ai"})
    if response.status_code != 201:
        raise RuntimeError(f"GitHub would not trade the code ({response.status_code}); a code works once, "
                           "for an hour")
    return dict(response.json())


def env_values(app: dict[str, Any]) -> dict[str, str]:
    """What goes into the env file: the id, the key (base64, one line) and the webhook secret."""
    pem = str(app.get("pem") or "")
    hook_secret = str(app.get("webhook_secret") or "")
    if not (app.get("id") and pem and hook_secret):
        raise RuntimeError("GitHub's answer has no app id, private key or webhook secret")
    return {
        APP_ID_ENV: str(app["id"]),
        secret.PRIVATE_KEY_ENV: base64.b64encode(pem.encode()).decode(),
        secret.WEBHOOK_SECRET_ENV: hook_secret,
    }


def write_env(path: str | Path, values: dict[str, str]) -> None:
    """Set these keys in an env file: a line that has one is replaced, the rest are added at the end."""
    target = Path(path).expanduser()
    lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    left = dict(values)
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in left:
            out.append(f"{key}={left.pop(key)}")
        else:
            out.append(line)
    if left:
        if out and out[-1].strip():
            out.append("")
        out.append("# temper's GitHub app (temper github setup; see docs/github.md)")
        out.extend(f"{key}={value}" for key, value in left.items())
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".env.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(out) + "\n")
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _made(app: dict[str, Any], env_file: str | Path) -> dict[str, Any]:
    write_env(env_file, env_values(app))
    slug = str(app.get("slug") or "")
    settings = load_settings()
    out = {
        "app": slug,
        "name": app.get("name"),
        "id": app.get("id"),
        "owner": (app.get("owner") or {}).get("login"),
        "page": app.get("html_url"),
        "install": f"https://github.com/apps/{slug}/installations/new" if slug else None,
        "env_file": str(Path(env_file).expanduser()),
        "wrote": sorted(env_values(app)),
    }
    if slug and slug != settings.app:
        out["warning"] = (f"the app is '{slug}' but configs/github/github.yaml says '{settings.app}': "
                          f"set app: {slug} there, or mentions and the own-doings check use the wrong name")
    return out


def setup(env_file: str, name: str | None, hook_url: str, listen: str, org: str | None,
          timeout: float = SETUP_TIMEOUT_S) -> dict[str, Any]:
    """Serve the manifest page on this machine and wait for GitHub to send the browser back."""
    host, _, port_text = listen.rpartition(":")
    host, port = host or "127.0.0.1", int(port_text)
    state = secrets.token_urlsafe(16)
    app_name = name or load_settings().app
    redirect = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}/done"  # noqa: S104
    page = manifest_page(manifest(app_name, hook_url, redirect), new_app_url(org, state))
    result: dict[str, Any] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:  # the URL carries the code: never logged
            return

        def _send(self, status: int, body: str) -> None:
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 - the http.server name
            url = urlparse(self.path)
            if url.path == "/":
                self._send(200, page)
                return
            if url.path != "/done":
                self._send(404, "Not here.")
                return
            query = parse_qs(url.query)
            if query.get("state", [""])[0] != state:
                self._send(400, "This is not the answer to the page this command served.")
                return
            try:
                result.update(_made(convert(query.get("code", [""])[0]), env_file))
            except Exception as exc:  # noqa: BLE001 - shown to the person, who can run it again
                result["error"] = str(exc)
                self._send(500, f"<p>The app could not be finished here: {html.escape(str(exc))}</p>")
            else:
                install = html.escape(str(result.get("install") or ""), quote=True)
                self._send(200, (
                    f"<p>Made <b>{html.escape(str(result.get('app')))}</b>; its keys are in the env file.</p>"
                    f"<p>Next: <a href='{install}'>install it</a> and pick the repositories it may work on.</p>"))
            done.set()

    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Open http://{host}:{port}/ in a browser on this machine and click Create on GitHub. "
          f"Waiting up to {int(timeout // 60)} minutes...", file=sys.stderr, flush=True)
    try:
        if not done.wait(timeout):
            raise TimeoutError("no answer from GitHub in time; run it again")
    finally:
        server.shutdown()
        server.server_close()
    if "error" in result:
        raise RuntimeError(result["error"])
    return result


def check() -> int:
    """Print the app's setup; 0 if it can work, 1 if not."""
    settings = load_settings()
    report: dict[str, Any] = {
        "settings": {"file": settings.path or "(defaults)", "app": settings.app,
                     "allowed_authors": list(settings.allowed_authors)},
        "webhook_secret": "set" if secret.webhook_secret() else f"{secret.WEBHOOK_SECRET_ENV} is not set",
    }
    from temper_ai.triggers.rules import load_triggers

    report["rules"] = {t.name: ("on" if t.enabled else "off") + f" -> {t.workflow}"
                       for t in load_triggers(source="github")}
    ok = report["webhook_secret"] == "set"
    reason = why_not_configured()
    if reason:
        report["app"] = reason
        ok = False
    else:
        try:
            app = server_app()
            me = app.whoami()
            report["app"] = {"id": me.get("id"), "slug": me.get("slug"), "name": me.get("name"),
                             "owner": (me.get("owner") or {}).get("login"), "page": me.get("html_url"),
                             "events": me.get("events"), "permissions": me.get("permissions")}
            if me.get("slug") and me.get("slug") != settings.app:
                report["warning"] = f"the app is '{me.get('slug')}' but the settings say '{settings.app}'"
                ok = False
            installs = []
            for install in app.installations():
                app.installation_token(installation=int(install["id"]))
                installs.append({"account": (install.get("account") or {}).get("login"),
                                 "repositories": install.get("repository_selection"), "token": "ok"})
            report["installations"] = installs
            report["repos"] = sorted(app.installed_repos(refresh=True))
            if not installs:
                report["warning"] = "the app is not installed anywhere yet"
                ok = False
        except (GitHubAppError, httpx.HTTPError) as exc:
            report["app"] = f"error: {exc}"
            ok = False
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


def cmd_github(args: Any) -> int:
    try:
        if args.action == "check":
            return check()
        if args.action == "manifest":
            out: Any = manifest(args.name or load_settings().app, args.hook_url)
        elif args.action == "convert":
            out = _made(convert(args.code), args.env_file)
        else:
            out = setup(args.env_file, args.name, args.hook_url, args.listen, args.org,
                        timeout=max(1.0, float(args.wait_minutes)) * 60)
    except Exception as exc:  # noqa: BLE001 - the message is the whole point of a CLI error
        print(f"temper github {args.action}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2))
    return 0


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("github", help="Make temper's GitHub app, and check it")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("check", help="the app, where it is installed, its tokens, the webhook secret, the rules")
    made = sub.add_parser("manifest", help="print the app's manifest")
    made.add_argument("--name", help="the app's name (default: the settings' app)")
    made.add_argument("--hook-url", default=HOOK_URL, help=f"where GitHub sends events (default {HOOK_URL})")
    setup_p = sub.add_parser("setup", help="make the app: a page to open in a browser, then one click on GitHub")
    setup_p.add_argument("--env-file", required=True, help="the env file the app's keys go into")
    setup_p.add_argument("--name", help="the app's name (default: the settings' app)")
    setup_p.add_argument("--hook-url", default=HOOK_URL, help=f"where GitHub sends events (default {HOOK_URL})")
    setup_p.add_argument("--listen", default=DEFAULT_LISTEN, help=f"host:port to serve the page on ({DEFAULT_LISTEN})")
    setup_p.add_argument("--org", help="make the app under this organization instead of your account")
    setup_p.add_argument("--wait-minutes", type=float, default=SETUP_TIMEOUT_S / 60,
                         help=f"how long to wait for the click on GitHub (default {SETUP_TIMEOUT_S // 60})")
    conv = sub.add_parser("convert", help="trade the code GitHub gave back for the app's keys, into the env file")
    conv.add_argument("code", help="the code GitHub put in the address after Create")
    conv.add_argument("--env-file", required=True, help="the env file the app's keys go into")
