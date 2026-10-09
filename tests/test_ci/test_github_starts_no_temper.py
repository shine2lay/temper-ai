"""GitHub's browser tests run with no temper behind them (AGENTS.md rule 15).

The only temper is the live one: neither the e2e job nor the nightly repeat may start one
of its own, not even for a few minutes. They serve the commit's built pages with
scripts/e2e_static_server.py, which answers every API call with a 503, and run only the
spec files listed in frontend/e2e/server-free.txt. The e2e job keeps its name, because
master's branch protection and ``wt land`` wait for it.
"""

from __future__ import annotations

import importlib.util
import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
LISTED = ROOT / "frontend" / "e2e" / "server-free.txt"


def _jobs(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))["jobs"]


def _listed() -> list[str]:
    return [line.split("#", 1)[0].strip() for line in LISTED.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()]


@pytest.mark.parametrize("workflow", sorted(p.name for p in WORKFLOWS.glob("*.yml")))
def test_no_github_workflow_starts_a_temper(workflow):
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    assert not re.search(r"temper\s+serve|uvicorn|temper_ai\.api", text), f"{workflow} starts a temper of its own"


def test_the_e2e_job_keeps_its_name_and_runs_only_the_server_free_tests():
    job = _jobs("ci.yml")["e2e"]
    runs = "\n".join(step.get("run", "") for step in job["steps"])

    assert "npx playwright test -c playwright.server-free.config.ts" in runs
    assert "frontend/e2e/server-free.txt" in runs and "GITHUB_STEP_SUMMARY" in runs
    assert "rule 15" in runs, "with nothing listed, its summary says why none ran"
    assert not re.search(r"npx playwright test(?! -c playwright\.server-free)", runs)


def test_the_nightly_repeats_the_same_tests():
    job = _jobs("nightly.yml")["repeat-e2e"]
    runs = "\n".join(step.get("run", "") for step in job["steps"])

    assert "-c playwright.server-free.config.ts" in runs and "--retries=0" in runs
    assert not re.search(r"npx playwright test(?! -c playwright\.server-free)", runs)


def test_every_listed_spec_is_there():
    specs = ROOT / "frontend" / "e2e"
    assert [name for name in _listed() if not (specs / name).is_file()] == []


def test_the_server_free_config_starts_the_static_server_and_no_temper():
    config = (ROOT / "frontend" / "playwright.server-free.config.ts").read_text(encoding="utf-8")
    code = "\n".join(line for line in config.splitlines()
                     if not line.lstrip().startswith(("*", "/*", "//")))

    assert "../scripts/e2e_static_server.py" in code
    assert "e2e/server-free.txt" in code and "@needs-server" in code
    assert "const STATIC = `http://127.0.0.1:${PORT}`;" in code
    assert "baseURL: STATIC" in code
    # Helpers that read the address from the environment get the static build too.
    assert "process.env.TEMPER_E2E_BASE_URL = STATIC;" in code
    assert "8420" not in code, "never the live temper's port"


def test_npm_run_e2e_runs_what_github_runs():
    """The everyday command runs the server-free tests; the rest need an address given on
    purpose (frontend/e2e/requireBaseURL.ts), so none of them reaches the live temper by
    accident."""
    scripts = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["scripts"]

    assert scripts["e2e"] == "playwright test -c playwright.server-free.config.ts"
    assert scripts["e2e:ui"] == "playwright test -c playwright.server-free.config.ts --ui"
    config = (ROOT / "frontend" / "playwright.config.ts").read_text(encoding="utf-8")
    assert "globalSetup" in config and "requireBaseURL" in config
    assert "8420" not in config.split("defineConfig(", 1)[1], "no live temper to fall back on"


# -- the static server -----------------------------------------------------------


def _server_module():
    spec = importlib.util.spec_from_file_location("e2e_static_server", ROOT / "scripts" / "e2e_static_server.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>the app</html>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log('hi')", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("not for the browser", encoding="utf-8")
    return tmp_path


def test_it_serves_the_app_the_way_temper_mounts_it(dist):
    server = _server_module()

    assert server.resolve(dist, "/app") == (dist / "index.html", True)
    assert server.resolve(dist, "/app/runs/abc") == (dist / "index.html", True)
    assert server.resolve(dist, "/app/assets/app.js") == ((dist / "assets" / "app.js").resolve(), False)
    assert server.resolve(dist, "/app/assets/gone.js") == (None, False)
    assert server.resolve(dist, "/app/../secret.txt") == (None, False)
    assert server.resolve(dist, "/app/%2e%2e/secret.txt") == (None, False)
    assert server.resolve(dist, "/elsewhere") == (None, False)
    assert server.content_type(dist / "assets" / "app.js") == "text/javascript"


def test_every_api_call_gets_a_503_that_says_no_temper(dist, capsys):
    server = _server_module()
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(dist))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        for method, path in (("GET", "/api/workflows"), ("POST", "/api/runs"), ("GET", "/ws/runs/x")):
            req = urllib.request.Request(base + path, method=method,
                                         data=b"{}" if method == "POST" else None)
            with pytest.raises(urllib.error.HTTPError) as got:
                urllib.request.urlopen(req, timeout=5)
            assert got.value.code == 503
            assert "no temper here" in json.loads(got.value.read())["detail"]
        with urllib.request.urlopen(base + "/app/runs/abc", timeout=5) as resp:
            assert resp.read() == b"<html>the app</html>"
            assert resp.headers["Cache-Control"] == "no-cache"
    finally:
        httpd.shutdown()
        httpd.server_close()

    said = capsys.readouterr().err
    assert "/api/workflows" in said and " 503 " in said, "a call only a temper could answer is named"
    assert "/app/runs/abc" not in said, "a page served fine is not"
