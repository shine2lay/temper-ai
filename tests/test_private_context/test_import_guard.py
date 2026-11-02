"""Partition controls: A unchanged; every concrete module freshly contact-trapped."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from .import_guard import (
    CONTRACT_MODULES,
    contract_imports_allowed,
    extension_modules,
    extension_probe,
)
from .ipd1 import require
from .test_corpus import child_result

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "temper_ai" / "private_context"
EXTENSIONS = extension_modules(PACKAGE)


def run_probe(module: str, scratch: Path | None = None) -> tuple[int, bytes]:
    env = {"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    return child_result([sys.executable, "-c", extension_probe(module, scratch)], env)


def test_partition_combined_covers_exact_contracts_and_every_discovered_extension():
    discovered = {".".join(path.relative_to(PACKAGE).with_suffix("").parts) for path in PACKAGE.rglob("*.py")}
    require(set(CONTRACT_MODULES).isdisjoint(EXTENSIONS))
    require(set(CONTRACT_MODULES) | set(EXTENSIONS) == discovered)
    require(set(CONTRACT_MODULES) == {"__init__", "contracts", "errors", "private_json", "schema", "wire"})


@pytest.mark.parametrize("module", EXTENSIONS)
def test_each_extension_fresh_import_has_no_contact(module):
    status, output = run_probe(module)
    require(status == 0 and output == b"IMPORT_OK\n")


@pytest.mark.parametrize("statement", ["import socket", "from socket import socket", "import dataclasses", "from sqlmodel import Session"])
def test_original_contract_import_allowlist_still_bites(statement):
    require(not contract_imports_allowed(statement))
    require(contract_imports_allowed("from datetime import datetime\nimport json"))


def scratch_contracts(tmp_path):
    package = tmp_path / "private_context"
    package.mkdir()
    for name in CONTRACT_MODULES:
        shutil.copyfile(PACKAGE / (name + ".py"), package / (name + ".py"))
    return package


# Fixed nonprivate source. No sockets/DBs/settings files are opened by controls.
EFFECTS = [
    ("db-factory-alias", "from sqlmodel import create_engine as captured\ncaptured('sqlite://')"),
    ("db-core-alias", "from sqlalchemy.engine.create import create_engine as captured\ncaptured('sqlite://')"),
    ("db-session", "from sqlmodel import Session\nSession()"),
    ("network-connect", "import socket\nsocket.create_connection(('127.0.0.1', 9))"),
    ("network-client", "from httpx import Client\nClient()"),
    ("network-async-client", "from httpx import AsyncClient\nAsyncClient()"),
    ("network-url", "from urllib.request import urlopen\nurlopen('http://127.0.0.1:9')"),
    ("thread", "from threading import Thread\nThread(target=lambda: None).start()"),
    ("timer", "from threading import Timer\nTimer(0, lambda: None).start()"),
    ("process", "from subprocess import Popen\nPopen(['true'])"),
    ("multiprocess", "from multiprocessing import Process\nProcess(target=lambda: None).start()"),
    ("shell", "import os\nos.system('true')"),
    ("file-reader", "from pathlib import Path\nPath('synthetic-secret').read_text()"),
    ("file-open", "open('synthetic-secret')"),
    ("file-descriptor", "import os\nos.open('synthetic-secret', os.O_RDONLY)"),
    ("environment", "import os\nos.getenv('SYNTHETIC_KEY')"),
    ("environment-map", "import os\nos.environ.get('SYNTHETIC_KEY')"),
    ("library-env-key", "import os\nos.getenv('PYDANTIC_DISABLE_PLUGINS')"),
    ("settings", "from pydantic_settings import BaseSettings\nBaseSettings()"),
    ("routes", "from fastapi import APIRouter\nAPIRouter()"),
    ("application", "from fastapi import FastAPI\nFastAPI()"),
    ("jobs", "import sched\nsched.scheduler().enter(1, 1, lambda: None)"),
    ("runtime-import", "import temper_ai.database"),
    ("swallowed-contact", "import os\ntry:\n    os.getenv('SYNTHETIC_KEY')\nexcept Exception:\n    pass"),
]


@pytest.mark.parametrize(("label", "source"), EFFECTS, ids=[item[0] for item in EFFECTS])
def test_prohibited_extension_effect_is_blocked_before_contact(tmp_path, label, source):
    package = scratch_contracts(tmp_path)
    (package / "injected.py").write_text(source, encoding="utf-8")
    require(extension_modules(package) == ("injected",))
    status, output = run_probe("injected", tmp_path)
    require(status == 0 and output == b"BLOCKED\n")


def test_added_nested_module_cannot_disappear_from_fresh_probe_coverage(tmp_path):
    package = scratch_contracts(tmp_path)
    nested = package / "new_layer"
    nested.mkdir()
    (nested / "__init__.py").write_text("", encoding="utf-8")
    (nested / "effect.py").write_text("import os\nos.getenv('SYNTHETIC_KEY')", encoding="utf-8")
    modules = extension_modules(package)
    require(modules == ("new_layer.__init__", "new_layer.effect"))
    results = [run_probe(module, tmp_path) for module in modules]
    require(results == [(0, b"IMPORT_OK\n"), (0, b"BLOCKED\n")])


def test_inert_orm_types_and_dataclasses_remain_allowed(tmp_path):
    package = scratch_contracts(tmp_path)
    (package / "inert.py").write_text(
        "from dataclasses import dataclass\n"
        "from sqlmodel import SQLModel, Field\n"
        "@dataclass(frozen=True)\nclass Scope:\n    name: str\n"
        "class Metadata(SQLModel, table=True):\n    id: int = Field(primary_key=True)\n",
        encoding="utf-8",
    )
    status, output = run_probe("inert", tmp_path)
    require(status == 0 and output == b"IMPORT_OK\n")


def test_missing_contract_file_fails_discovery(tmp_path):
    package = scratch_contracts(tmp_path)
    (package / "wire.py").unlink()
    with pytest.raises(AssertionError):
        extension_modules(package)
