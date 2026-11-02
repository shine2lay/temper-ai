"""Named guard bites: mutate imports in a child interpreter, never source files.

Children run only synthetic C2 checks, not providers, servers or C1 custody.
A collection/setup crash cannot satisfy a bite: the named test must FAIL in call.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from . import ipd1
from .ipd1 import require

CHILD = r'''
import importlib.abc
import importlib.machinery
import json
import sys
module, old, new, test = json.loads(sys.argv[1])
class Loader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        source = self.get_data(self.path).decode("utf-8")
        if source.count(old) != 1:
            raise RuntimeError("mutation no longer matches exactly once")
        return compile(source.replace(old, new), self.path, "exec")
class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != module:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        spec.loader = Loader(fullname, spec.origin)
        return spec
sys.meta_path.insert(0, Finder())
import pytest
class Reports:
    def __init__(self):
        self.failed = []
    def pytest_runtest_logreport(self, report):
        if report.when == "call" and report.failed:
            self.failed.append(report.nodeid)
reports = Reports()
code = pytest.main(["-o", "addopts=", "-q", "--tb=no", test], plugins=[reports])
print("C2_GUARD_RESULT=" + json.dumps({"code": int(code), "failed": reports.failed}))
'''

BINDING = "temper_ai.runner.private_context_binding"
AUTH = "temper_ai.api.auth"
IDENTITY = "temper_ai.api.private_identity"
WORKER = "temper_ai.api.private_worker_keys"
ROOT = "tests/test_private_context/"

# Each changed binding field has its own witness, not just a compound-condition knockout.
FIELD_EXPRESSIONS = {
    "execution_id": "admitted.created and binding.execution_id != allocated",
    "context_ref": "binding.context_ref != descriptor.context_ref",
    "context_version": "binding.context_version != descriptor.context_version",
    "owner_principal": "binding.owner_principal != caller.principal_id",
    "namespace": "binding.namespace != caller.namespace",
    "profile": "binding.profile != caller.profile",
    "profile_revision": "binding.profile_revision != profile.profile_revision",
    "workflow": "binding.workflow != profile.workflow",
    "workflow_revision": "binding.workflow_revision != profile.workflow_revision",
    "node_path": "binding.node_path != profile.node_path",
    "use": 'binding.use != "draft"',
    "context_schema": "binding.context_schema != profile.schema.identity.context_schema",
    "result_schema": "binding.result_schema != profile.schema.identity.result_schema",
    "schema_revision": "binding.schema_revision != profile.schema.identity.revision",
    "expires_at": "_binding_time(binding.expires_at) <= datetime.now(UTC)",
    "deadline_at": "_binding_time(binding.deadline_at) <= datetime.now(UTC)",
    "revoked": "or binding.revoked):",
}
CASES = [pytest.param(BINDING, expression, "False" if field != "revoked" else "or False):",
    ROOT + "test_run_binding.py::test_changed_admission_binding_rolls_back_staged_queue[" + field + "]",
    id="binding-" + field) for field, expression in FIELD_EXPRESSIONS.items()]
CASES += [
    pytest.param(AUTH, "if len(credentials) != 1:", "if not credentials:",
        ROOT + "test_api_auth.py::test_unsupported_identity_refuses_before_receive", id="duplicate-header"),
    pytest.param(AUTH, "if shared is not None and hmac.compare_digest(presented, shared):\n        return None",
        "if False:\n        return None",
        ROOT + "test_api_auth.py::test_named_key_equal_to_shared_token_never_has_private_authority",
        id="shared-key-alias"),
    pytest.param(IDENTITY, "current_caller() is not self.caller", "False",
        ROOT + "test_api_auth.py::test_caller_rebinding_and_key_revocation_invalidate_issued_principal",
        id="exact-current-caller"),
    pytest.param(IDENTITY, "not any(item is principal for item in request.issued)",
        "not any(item == principal for item in request.issued)",
        ROOT + "test_api_auth.py::test_constructed_caller_and_value_equal_principal_are_not_authority",
        id="principal-not-value-equality"),
    pytest.param(WORKER, "or _utc(row.expires_at) != min(authority.deadline_at, authority.profile.credential_deadline)",
        "or False", ROOT + "test_worker_transport.py::test_changed_current_scope_refuses_before_body",
        id="exact-future-key-deadline"),
    pytest.param(BINDING, "binding.runner_generation != previous.runner_generation + 1", "False",
        ROOT + "test_run_binding.py::test_lifecycle_exact_transition_before_normal_or_key_effect",
        id="exact-resume-generation"),
    pytest.param(BINDING, "any(getattr(binding, name) != getattr(previous, name) for name in stable)", "False",
        ROOT + "test_run_binding.py::test_lifecycle_exact_transition_before_normal_or_key_effect",
        id="stable-lifecycle-scope-and-evidence"),
]


@pytest.mark.parametrize("module,old,new,test", CASES)
def test_named_transport_guard_bite(module, old, new, test):
    process = subprocess.run([sys.executable, "-c", CHILD, json.dumps([module, old, new, test])],
        cwd=Path(__file__).resolve().parents[2], env={**os.environ, "PYTEST_ADDOPTS": ""},
        capture_output=True, text=True, check=False)
    report_lines = [line.removeprefix("C2_GUARD_RESULT=") for line in process.stdout.splitlines()
                    if line.startswith("C2_GUARD_RESULT=")]
    require(len(report_lines) == 1)
    report = json.loads(report_lines[0])
    require(process.returncode == 0 and report["code"] == 1 and bool(report["failed"]))
    require(all(item.startswith(test.split("[")[0]) for item in report["failed"]))
    require(ipd1.scan({ipd1.Surface.ERROR: process.stdout + process.stderr}).clean)
