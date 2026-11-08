"""Provisioned product instance boundary for stage 2 capture.

One job: given base_url + credentials (and optional version override), check reachability,
read GET {base_url}/api/health for {ok, version, commit}, log in accounts, and expose
"go to screen S in state T" / shoot captures over HTTP and Playwright.
No build, no process management, no git/standee/uv/npm/docker calls, and no credentials
written to files or error messages.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import product_app

HERE = Path(__file__).resolve().parent
CAPTURE_JS = HERE / "existing_capture.mjs"
MEASURE_JS = HERE / "measure_in_page.js"
LIVE_HOSTS = frozenset({"rollcall.wai2shine.com"})
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


class AppInstanceError(RuntimeError):
    """A provisioned product instance could not be reached, checked, or logged into."""


InstanceError = AppInstanceError


def _scrub(text: str, secrets: list[str]) -> str:
    out = str(text or "")
    for secret in secrets:
        if secret and len(secret) >= 2:
            out = out.replace(secret, "[REDACTED]")
    return out


def validate_base_url(base_url: str) -> str:
    raw = str(base_url or "").strip().rstrip("/")
    if not raw:
        raise AppInstanceError("base_url is required (got empty base_url)")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise AppInstanceError(f"base_url {raw!r} must be an http:// or https:// URL")
    host = (parsed.hostname or "").lower()
    if host in LIVE_HOSTS:
        raise AppInstanceError(f"refusing live production base_url {raw!r}")
    return raw


def normalize_credentials(credentials: dict[str, str] | str | None) -> dict[str, str]:
    if credentials is None:
        return {}
    if isinstance(credentials, str):
        val = credentials.strip()
        if not val:
            return {}
        if val.startswith("{"):
            try:
                parsed = json.loads(val)
            except ValueError as exc:
                raise AppInstanceError(f"credentials JSON is invalid: {exc}") from None
            if not isinstance(parsed, dict):
                raise AppInstanceError("credentials JSON must be an object mapping account -> password")
            return {str(k): str(v) for k, v in parsed.items() if v is not None}
        return {"*": val, "default": val}
    if isinstance(credentials, dict):
        return {str(k): str(v) for k, v in credentials.items() if v is not None}
    raise AppInstanceError("credentials must be a dict or string")


def _read_health_url(url: str, base: str, opener: Any = None, timeout: float = 15.0) -> str:
    if opener is None:
        req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                if status and int(status) >= 400:
                    raise AppInstanceError(f"GET {url} returned HTTP {status} (base_url={base})")
                return resp.read().decode("utf-8", errors="replace")
        except AppInstanceError:
            raise
        except urllib.error.HTTPError as exc:
            raise AppInstanceError(f"GET {url} returned HTTP {exc.code} (base_url={base})") from None
        except Exception as exc:
            raise AppInstanceError(f"GET {url} is unreachable for base_url {base}: {exc}") from None

    try:
        try:
            res = opener(url, timeout)
        except TypeError:
            req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
            res = opener(req, timeout=timeout)
    except AppInstanceError:
        raise
    except urllib.error.HTTPError as exc:
        raise AppInstanceError(f"GET {url} returned HTTP {exc.code} (base_url={base})") from None
    except Exception as exc:
        raise AppInstanceError(f"GET {url} is unreachable for base_url {base}: {exc}") from None

    if isinstance(res, tuple) and len(res) == 2:
        status, body = res
        if int(status) >= 400:
            raise AppInstanceError(f"GET {url} returned HTTP {status} (base_url={base})")
        return body.decode("utf-8", errors="replace") if isinstance(body, (bytes, bytearray)) else str(body)
    if hasattr(res, "__enter__"):
        with res as resp:
            raw = resp.read() if hasattr(resp, "read") else resp
            return raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    if hasattr(res, "read"):
        raw = res.read()
        return raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    if isinstance(res, (bytes, bytearray)):
        return res.decode("utf-8", errors="replace")
    if isinstance(res, dict):
        return json.dumps(res)
    return str(res)


def fetch_health(base_url: str, *, version: str | None = None,
                 opener: Any = None, timeout: float = 15.0) -> dict[str, Any]:
    """Fetch GET {base_url}/api/health -> {base_url, health_url, commit, version, ok}."""
    base = validate_base_url(base_url)
    url = f"{base}/api/health"
    body = _read_health_url(url, base, opener=opener, timeout=timeout)
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise AppInstanceError(f"{url} returned invalid JSON for base_url {base}: {exc}") from None
    if not isinstance(data, dict):
        raise AppInstanceError(f"{url} must return a JSON object for base_url {base}")
    if "ok" in data and data.get("ok") is not True:
        raise AppInstanceError(f"{url} reported ok={data.get('ok')!r} (expected ok=True for base_url {base})")
    commit = str(data.get("commit") or "").strip()
    if not commit or not COMMIT_RE.match(commit):
        raise AppInstanceError(f"{url} response is missing a valid 'commit' field (base_url={base})")
    resolved_version = str(version or data.get("version") or "").strip() or commit[:7]
    return {
        "base_url": base,
        "health_url": url,
        "commit": commit,
        "version": resolved_version,
        "ok": True,
    }


read_health = fetch_health


def resolve_screen_target(app: dict[str, Any], screen_id: str, state_name: str) -> dict[str, Any]:
    """Return the navigation recipe for 'go to screen S in state T'."""
    for item in product_app.captures(app):
        if item["screen"] == screen_id and item["state"] == state_name:
            return {
                "screen": screen_id,
                "state": state_name,
                "account": item.get("account"),
                "steps": item["steps"],
                "wait_for": item["wait_for"],
            }
    raise AppInstanceError(f"unknown screen/state ({screen_id!r}, {state_name!r}) in {app.get('product', 'app')}")


class AppInstance:
    """A reachable, health-checked product instance at base_url."""

    def __init__(self, first: dict[str, Any] | str,
                 second: dict[str, str] | str | None = None,
                 third: dict[str, str] | str | None = None,
                 *,
                 app: dict[str, Any] | None = None,
                 base_url: str | None = None,
                 credentials: dict[str, str] | str | None = None,
                 version: str | None = None,
                 opener: Any = None,
                 health_opener: Any = None,
                 timeout: float = 15.0) -> None:
        if isinstance(first, dict):
            resolved_app = first
            resolved_url = str(second or base_url or "")
            resolved_creds = third if third is not None else credentials
        else:
            resolved_url = str(first or base_url or "")
            resolved_creds = second if second is not None else credentials
            resolved_app = app or {}
        self.app = resolved_app
        self.base_url = validate_base_url(resolved_url)
        self._credentials = normalize_credentials(resolved_creds)
        self._opener = health_opener or opener
        self._version_override = version
        self._timeout = timeout
        self._health: dict[str, Any] | None = None
        if self._opener is not None:
            self._health = fetch_health(self.base_url, version=version, opener=self._opener, timeout=timeout)

    def read_health(self) -> dict[str, Any]:
        if self._health is None:
            self._health = fetch_health(
                self.base_url,
                version=self._version_override,
                opener=self._opener,
                timeout=self._timeout,
            )
        return self._health

    @property
    def health(self) -> dict[str, Any]:
        return self.read_health()

    @property
    def commit(self) -> str:
        return self.read_health()["commit"]

    @property
    def version(self) -> str:
        return self.read_health()["version"]

    def _secrets(self) -> list[str]:
        return [v for v in self._credentials.values() if v]

    def password_for(self, account: str) -> str:
        acct = str(account or "").strip()
        if not acct:
            raise AppInstanceError("account name is empty")
        short = acct.split("@", 1)[0]
        for key in (acct, short, "*", "default", "password"):
            if key in self._credentials and self._credentials[key]:
                return self._credentials[key]
        raise AppInstanceError(
            f"missing password for account {acct!r} on {self.base_url} "
            f"(supply credentials for {acct!r} or 'default')"
        )

    def validate_accounts(self, caps: list[dict[str, Any]] | None = None) -> dict[str, str]:
        if not self.app.get("login"):
            return {}
        items = caps if caps is not None else product_app.captures(self.app)
        resolved: dict[str, str] = {}
        for c in items:
            acct = c.get("account")
            if acct and acct not in resolved:
                resolved[acct] = self.password_for(acct)
        return resolved

    def login_spec(self) -> dict[str, Any] | None:
        lg = self.app.get("login")
        if not lg:
            return None
        user_sel = lg.get("email_field") or lg.get("user_field") or lg.get("user_selector")
        pwd_sel = lg.get("password_field") or lg.get("password_selector")
        fields = dict(lg.get("fields") or {})
        return {
            "path": lg["path"],
            "fields": fields,
            "user_selector": user_sel,
            "password_selector": pwd_sel,
            "submit": lg["submit"],
            "wait_for": lg["wait_for"],
        }

    def login_account(self, browser: Any, account: str) -> Any:
        """Log into `account` in a new browser context and return that context.

        On any error, raises AppInstanceError naming `account` and `base_url`, never the password.
        """
        pwd = self.password_for(account)
        lg = self.login_spec()
        if not lg:
            return browser.new_context()
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(f"{self.base_url}{lg['path']}", wait_until="domcontentloaded", timeout=20000)
            for sel, tmpl in (lg.get("fields") or {}).items():
                s = str(tmpl)
                filled = account if ("{account}@" in s and "@" in account) else s.replace("{account}", account)
                page.fill(sel, filled)
            user_sel = lg.get("user_selector")
            if user_sel and user_sel not in (lg.get("fields") or {}):
                val = account if ("@" in account or lg.get("fields")) else f"{account}@rollcall.test"
                page.fill(user_sel, val)
            if lg.get("password_selector"):
                page.fill(lg["password_selector"], pwd)
            page.click(lg["submit"])
            page.wait_for_selector(lg["wait_for"], timeout=20000)
            return ctx
        except Exception as exc:
            try:
                ctx.close()
            except Exception:
                pass
            clean = _scrub(str(exc), self._secrets())
            raise AppInstanceError(
                f"login failed for account {account!r} on {self.base_url}: {clean}"
            ) from None

    def go_to_screen(self, page: Any, screen_id: str, state_name: str) -> dict[str, Any]:
        """Drive a Playwright page to screen `screen_id` in state `state_name`."""
        target = resolve_screen_target(self.app, screen_id, state_name)
        try:
            for step in target["steps"]:
                if "goto" in step:
                    page.goto(f"{self.base_url}{step['goto']}", wait_until="domcontentloaded", timeout=20000)
                elif "click" in step:
                    page.click(step["click"], timeout=10000)
                elif "fill" in step:
                    page.fill(step["fill"]["selector"], step["fill"]["value"], timeout=10000)
                elif "wait_for" in step:
                    page.wait_for_selector(step["wait_for"], timeout=15000)
                elif "wait_ms" in step:
                    page.wait_for_timeout(step["wait_ms"])
            page.wait_for_selector(target["wait_for"], timeout=15000)
            return target
        except Exception as exc:
            clean = _scrub(str(exc), self._secrets())
            raise AppInstanceError(
                f"navigation failed for screen {screen_id!r} state {state_name!r} on {self.base_url}: {clean}"
            ) from None

    def plan(self, caps: list[dict[str, Any]], out_dir: Path, state_dir: Path) -> dict[str, Any]:
        """Build the Playwright capture plan without embedding any password."""
        self.validate_accounts(caps)
        page_spec = dict(self.app["page"])
        if "key_regions" not in page_spec and "areas" in page_spec:
            page_spec["key_regions"] = dict(page_spec["areas"])
        plan: dict[str, Any] = {
            "base_url": self.base_url,
            "commit": self.commit,
            "version": self.version,
            "out_dir": str(out_dir),
            "state_dir": str(state_dir),
            "measure_script": str(MEASURE_JS),
            "measure_js": str(MEASURE_JS),
            "page": page_spec,
            "captures": caps,
        }
        lg = self.login_spec()
        if lg:
            plan["login"] = lg
        return plan

    def shoot(self, caps: list[dict[str, Any]], out_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
        """Run existing_capture.mjs against this instance and return (raw_measures, failed_by_id)."""
        creds = self.validate_accounts(caps)
        secrets = self._secrets()
        out_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="app-screen-instance-") as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / "states"
            state_dir.mkdir(parents=True, exist_ok=True)
            plan_doc = self.plan(caps, out_dir, state_dir)
            plan_file = tmp_path / "plan.json"
            plan_file.write_text(json.dumps(plan_doc, indent=2) + "\n", encoding="utf-8")

            env = dict(os.environ)
            creds_json = json.dumps(creds)
            env["APP_SCREEN_CREDENTIALS"] = creds_json
            env["APP_SCREEN_CREDENTIALS_JSON"] = creds_json
            proc = subprocess.run(
                ["node", str(CAPTURE_JS), str(plan_file)],
                capture_output=True,
                text=True,
                env=env,
                timeout=600,
                check=False,
            )
            if proc.returncode != 0:
                msg = _scrub((proc.stderr or proc.stdout or "")[-1200:], secrets)
                raise AppInstanceError(
                    f"existing_capture.mjs exited {proc.returncode} against {self.base_url}: {msg}"
                )
            failed: dict[str, str] = {}
            stdout_clean = _scrub((proc.stdout or "").strip(), secrets)
            if stdout_clean.startswith("{"):
                try:
                    summary = json.loads(stdout_clean)
                except ValueError:
                    summary = {}
                failed_raw = summary.get("failed") or {}
                if isinstance(failed_raw, dict):
                    for cid, why in failed_raw.items():
                        failed[str(cid)] = _scrub(str(why), secrets)
                elif isinstance(failed_raw, list):
                    for item in failed_raw:
                        if isinstance(item, dict):
                            cid = str(item.get("id") or item.get("account") or "unknown")
                            why = _scrub(str(item.get("error") or item.get("reason") or "failed"), secrets)
                            if cid.startswith("login:"):
                                acct = cid.split(":", 1)[1]
                                raise AppInstanceError(f"login failed for account {acct!r} on {self.base_url}: {why}")
                            failed[cid] = why

            for cid, why in list(failed.items()):
                if cid.startswith("login:"):
                    acct = cid.split(":", 1)[1]
                    raise AppInstanceError(f"login failed for account {acct!r} on {self.base_url}: {why}")

            raw_path = out_dir / "raw.json"
            if not raw_path.is_file():
                raise AppInstanceError(f"existing_capture.mjs did not write {raw_path}")
            raw_data = json.loads(_scrub(raw_path.read_text(encoding="utf-8"), secrets))
            for cid, entry in raw_data.items():
                if isinstance(entry, dict) and entry.get("failed"):
                    failed.setdefault(str(cid), _scrub(str(entry["failed"]), secrets))
            return raw_data, failed
