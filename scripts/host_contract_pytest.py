"""Pytest entry for the isolated host-contract tree; admission is shared, not copied.

Only pytest's locked xdist/timeout plugins are enabled. The copied infrastructure conftest calls
pytest_configure in controller and workers, without importing tests/__init__ or root conftest.
This narrows accidental imports; it is not a security sandbox for hostile Python.
"""
from __future__ import annotations

import importlib.abc
import os
import sys
import sysconfig
from pathlib import Path

# Public application, server, browser and provider packages must never be imported by a pure contract test.
FORBIDDEN = frozenset({
    "temper_ai", "local", "anthropic", "google", "openai", "mcp",
    "sqlalchemy", "sqlmodel", "fastapi", "starlette", "uvicorn",
    "psycopg2", "asyncpg", "redis", "httpx", "requests", "playwright", "docker",
})


class NoApplicationImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in FORBIDDEN:
            raise ImportError("Application/provider import forbidden in host-contract checks")
        return None


def isolate_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    locations = sysconfig.get_paths()
    # Drop .pth-added editable projects, the calling checkout and arbitrary PYTHONPATH entries.
    sys.path[:] = list(dict.fromkeys([
        str(root), str(root / "_checks"), locations["stdlib"],
        str(Path(locations["stdlib"]) / "lib-dynload"), locations["purelib"], locations["platlib"],
    ]))
    if any(name.split(".", 1)[0] in FORBIDDEN for name in sys.modules):
        raise RuntimeError("Application/provider was loaded before host-contract checks")
    sys.meta_path.insert(0, NoApplicationImports())


def pytest_configure(config):
    # Workers also get this boundary. Placement is mandatory even when admission is inherited.
    isolate_imports()
    if hasattr(config, "workerinput"):
        return  # inherits controller placement, matching the ordinary root conftest
    from machine_slot import EXIT_PLACEMENT, HostEntryError, enter_machine_slot

    try:
        enter_machine_slot(config.getoption("numprocesses", default=None))
    except HostEntryError:
        print("Host-contract tests cannot enter the shared test CPU.", file=sys.stderr)
        raise SystemExit(EXIT_PLACEMENT) from None


def main() -> int:
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH", "PYTHONHOME"):
        os.environ.pop(key, None)
    import pytest

    root = Path(__file__).resolve().parents[1]
    return pytest.main([
        "-c", str(root / "pytest.ini"), "--rootdir", str(root), "--confcutdir", str(root),
        "--import-mode=importlib", "-p", "xdist.plugin", "-p", "pytest_timeout",
        "-n", "auto", "--timeout=120", "-q", "tests/test_p3_host_contracts", *sys.argv[1:],
    ])


# Also on workers: establish the boundary when the infrastructure conftest is imported,
# before pytest loads any supplier conftest (pytest_configure would be too late).
isolate_imports()

if __name__ == "__main__":
    raise SystemExit(main())
