"""Fresh import contact traps; no provider/model request or settings snapshots."""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

from .ipd1 import require
from .test_corpus import child_result

IMPORT_PROBE = '''
import importlib.abc
import os
import socket
import subprocess
import sys
import httpx
# The existing package root takes GitHub secrets from environment. This child
# receives no such environment; establish that unchanged root before the probe.
import temper_ai
calls = []
def denied(*args, **kwargs):
    calls.append("contact")
    raise RuntimeError("contact forbidden")
class NoInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("temper_ai.config", "temper_ai.database", "temper_ai.api", "temper_ai.runner", "temper_ai.llm", "temper_ai.spawner", "anthropic")):
            denied()
        return None
sys.meta_path.insert(0, NoInfrastructure())
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
httpx.Client.__init__ = denied
httpx.AsyncClient.__init__ = denied
httpx.Client.send = denied
httpx.AsyncClient.send = denied
subprocess.Popen = denied
old_getenv = os.getenv
def getenv(key, default=None):
    if key.startswith(("TEMPER", "ANTHROPIC", "OPENAI")):
        denied()
    return old_getenv(key, default)
os.getenv = getenv
from temper_ai.private_context import contracts, wire, schema, errors, private_json
from temper_ai.shared.types import ExecutionContext
assert not calls
assert ExecutionContext.__dataclass_fields__["private_context"].default is None
print("IMPORT_OK")
'''


def test_fresh_contract_import_performs_no_infrastructure_contact() -> None:
    root = Path(__file__).resolve().parents[2]
    require((root / "temper_ai" / "private_context").is_dir())
    env = {"PATH": os.defpath, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    code, output = child_result([sys.executable, "-c", IMPORT_PROBE], env)
    # Exact label, never prefix matching; stdout/stderr/argv never in a failure.
    require(code == 0 and output == b"IMPORT_OK\n")


def test_contract_package_does_not_register_or_import_runtime_consumers() -> None:
    root = Path(__file__).resolve().parents[2]
    package = root / "temper_ai" / "private_context"
    require({"__init__.py", "contracts.py", "errors.py", "private_json.py", "schema.py", "wire.py"} <= {path.name for path in package.glob("*.py")})
    allowed_imports = {"__future__", "typing", "enum", "types", "json", "math", "datetime", "uuid", "pydantic", "jsonschema", "referencing"}
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, ast.Import):
                require(all(name.name.split(".")[0] in allowed_imports for name in node.names))
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                require((node.module or "").split(".")[0] in allowed_imports)
