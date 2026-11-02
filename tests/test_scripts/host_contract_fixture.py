"""Synthetic repositories for the real host-contract hook; no supplier records or adapters."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from tests.test_shared_test_cpu_entry import Ran

ROOT = Path(__file__).resolve().parents[2]
INFRA = (
    "scripts/select_tests.py", "scripts/dependency_graph.py", "scripts/test-selection.toml",
    "scripts/check_host_contracts.py", "scripts/host_contract_pytest.py", "scripts/show_versions.py",
    "scripts/git-hooks/pre-commit", "tests/machine_slot.py", "pyproject.toml", "uv.lock",
)
PACKAGE = "def value() -> int:\n    return 42\n"
TEST = '''import sys
from pathlib import Path

from p3_host_contracts import value


def test_value(answer):
    assert value() == answer == 42
    assert Path(__file__).with_name("fixture.txt").read_text() == "fixed\\n"


def test_isolated(request):
    assert not any(n.split(".", 1)[0] in {"temper_ai", "local", "anthropic", "sqlalchemy"} for n in sys.modules)
    assert not request.config.pluginmanager.list_plugin_distinfo()
    assert not Path("tests/conftest.py").exists()
    assert not Path("temper_ai").exists()
'''
CONFTEST = "import pytest\n\n\n@pytest.fixture\ndef answer():\n    return 42\n"
NATIVE_SENTINELS = ("docker", "temper", "playwright", "chromium", "npx", "npm", "psql")


class LeafRepo:
    """Real tools and real git hooks. Initial scaffold is committed before installing its hook."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        for name in ("UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "TEMPER_TEST_DATABASE_URL"):
            self.env.pop(name, None)
        # A fixed worker count for these tiny known-answer fixtures, not an admission bypass.
        self.env.update(PRECOMMIT_PYTEST_WORKERS="2", PYTEST_XDIST_AUTO_NUM_WORKERS="2")
        sentinels = root.parent / "sentinel-bin"
        sentinels.mkdir()
        for tool in NATIVE_SENTINELS:
            script = sentinels / tool
            script.write_text("#!/bin/sh\necho FORBIDDEN_NATIVE_ACCESS >&2\nexit 97\n")
            script.chmod(0o755)
        self.env["PATH"] = f"{sentinels}:{self.env.get('PATH', '')}"
        for name in INFRA:
            self.put(name, (ROOT / name).read_text())
        (root / "scripts/git-hooks/pre-commit").chmod(0o755)
        self.put("README.md", "Synthetic check fixture.\n")
        self.put(".gitignore", ".venv/\n__pycache__/\n.pytest_cache/\n.mypy_cache/\n.ruff_cache/\n")
        sentinel = "raise RuntimeError('FORBIDDEN_ROOT_BOOTSTRAP')\n"
        for name in ("conftest.py", "tests/conftest.py", "tests/__init__.py", "temper_ai/__init__.py", "local/__init__.py"):
            self.put(name, sentinel)
        self.git("init", "-q", "-b", "master")
        self.git("config", "user.email", "fixture@example.com")
        self.git("config", "user.name", "Synthetic Fixture")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "synthetic infrastructure")
        self.git("checkout", "-q", "-b", "leaf")
        self.git("config", "core.hooksPath", "scripts/git-hooks")
        self.put("p3_host_contracts/__init__.py", PACKAGE)
        self.put("tests/test_p3_host_contracts/test_contract.py", TEST)
        self.put("tests/test_p3_host_contracts/conftest.py", CONFTEST)
        self.put("tests/test_p3_host_contracts/fixture.txt", "fixed\n")
        self.put("docs/p3-host-contracts.md", "Synthetic package only.\n")
        self.git("add", ".")

    def __repr__(self):
        return "<synthetic leaf repository>"

    def put(self, relative: str, body: str) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)

    def call(self, *args: str) -> Ran:
        command = list(args)
        if command[0] == "git":
            command[1:1] = ["-c", "maintenance.auto=false"]
        return Ran(command, cwd=self.root, env=self.env, timeout=180)

    def git(self, *args: str) -> None:
        result = self.call("git", *args)
        assert result.code == 0, "synthetic repository setup failed"

    def hook(self) -> Ran:
        return self.call("bash", "scripts/git-hooks/pre-commit")

    def remove(self, relative: str) -> None:
        target = self.root / relative
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        self.git("add", "-A")
