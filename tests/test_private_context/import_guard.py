"""Fresh-process import probes; fixed labels, no child diagnostics exported.

This is an operational check of named Python paths, not a hostile-code sandbox.
Dependency setup precedes arming; no private_context extension is preimported.
"""
from __future__ import annotations

import ast
from pathlib import Path

from .ipd1 import require

CONTRACT_MODULES = frozenset({"__init__", "contracts", "errors", "private_json", "schema", "wire"})
CONTRACT_IMPORTS = frozenset({"__future__", "typing", "enum", "types", "json", "math", "datetime", "uuid", "pydantic", "jsonschema", "referencing"})


def contract_imports_allowed(source: str) -> bool:
    for node in ast.parse(source).body:
        if isinstance(node, ast.Import):
            if not all(name.name.split(".")[0] in CONTRACT_IMPORTS for name in node.names):
                return False
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if (node.module or "").split(".")[0] not in CONTRACT_IMPORTS:
                return False
    return True


def extension_modules(package: Path) -> tuple[str, ...]:
    files = {path.relative_to(package) for path in package.rglob("*.py")}
    require({Path(name + ".py") for name in CONTRACT_MODULES} <= files)
    return tuple(sorted(".".join(path.with_suffix("").parts) for path in files if path not in {Path(name + ".py") for name in CONTRACT_MODULES}))


# The selected module and optional scratch package path are inserted by the caller
# before execution. Each module gets a new interpreter so aliases cannot escape.
EXTENSION_PROBE = r'''
import asyncio
import builtins
import concurrent.futures
import importlib
import importlib.abc
import io
import multiprocessing.process
import os
import pathlib
import sched
import socket
import subprocess
import sys
import threading
import urllib.request
import httpx
import sqlalchemy
import sqlalchemy.engine.create
import sqlalchemy.orm
import sqlmodel
import fastapi
import pydantic_settings
import pydantic.plugin._loader
import jsonschema
import referencing
import temper_ai
# Existing root/environment behavior is outside this probe and uses clean env.
if scratch is not None:
    temper_ai.__path__.insert(0, scratch)
# Warm external dependencies only; even A can re-export an extension.
# The first private_context package/target execution must occur below the traps.
calls = []
def denied(*args, **kwargs):
    calls.append(1)
    raise RuntimeError("import contact forbidden")
class NoInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("temper_ai.config", "temper_ai.database", "temper_ai.api", "temper_ai.runner", "temper_ai.llm", "temper_ai.spawner", "temper_ai.cli", "anthropic", "openai", "apscheduler")):
            denied()
        return None
sys.meta_path.insert(0, NoInfrastructure())
# Guard factories AND already-defined methods before the extension binds aliases.
for target in (sqlalchemy, sqlalchemy.engine, sqlalchemy.engine.create, sqlmodel):
    if hasattr(target, "create_engine"):
        target.create_engine = denied
sqlalchemy.engine.Engine.__init__ = denied
sqlalchemy.engine.Engine.connect = denied
sqlalchemy.engine.Engine.raw_connection = denied
sqlalchemy.engine.Connection.__init__ = denied
sqlalchemy.orm.Session.__init__ = denied
sqlmodel.Session.__init__ = denied
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
httpx.Client.__init__ = denied
httpx.AsyncClient.__init__ = denied
httpx.Client.send = denied
httpx.AsyncClient.send = denied
urllib.request.urlopen = denied
urllib.request.build_opener = denied
subprocess.Popen = denied
os.system = denied
os.fork = denied
os.posix_spawn = denied
multiprocessing.process.BaseProcess.start = denied
threading.Thread.start = denied
sched.scheduler.enter = denied
sched.scheduler.enterabs = denied
asyncio.BaseEventLoop.call_later = denied
asyncio.BaseEventLoop.call_at = denied
asyncio.BaseEventLoop.create_task = denied
asyncio.run = denied
for target in (fastapi.FastAPI, fastapi.APIRouter):
    target.__init__ = denied
    target.add_api_route = denied
    target.include_router = denied
fastapi.BackgroundTasks.add_task = denied
pydantic_settings.BaseSettings.__init__ = denied
# Python file/credential readers; importlib's source loader remains available.
builtins.open = denied
io.open = denied
os.open = denied
def read_environment(key, default=None):
    # Inert Pydantic model construction always asks this library-only knob.
    # Supply a constant that DISABLES plugins, never read the actual environment.
    # Exact caller code and key: the same key from an extension is still denied.
    if key == "PYDANTIC_DISABLE_PLUGINS" and sys._getframe(1).f_code is pydantic.plugin._loader.get_plugins.__code__:
        return "__all__"
    return denied()
os.getenv = read_environment
os._Environ.__getitem__ = denied
os._Environ.__iter__ = denied
try:
    importlib.import_module("temper_ai.private_context." + module)
except BaseException:
    print("BLOCKED" if calls else "IMPORT_ERROR")
else:
    print("BLOCKED" if calls else "IMPORT_OK")
'''


def extension_probe(module: str, scratch: Path | None = None) -> str:
    return f"module = {module!r}\nscratch = {str(scratch) if scratch is not None else None!r}\n" + EXTENSION_PROBE
