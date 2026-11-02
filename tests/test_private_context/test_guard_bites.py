"""Delete/loosen real contract guards in a scratch import tree; named tests must bite.

Each child returns one fixed label only. Raw failures/fixture bodies never leave
it; a setup error is NOT counted as a guard bite. No changes to the checkout.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from .ipd1 import require
from .test_corpus import child_result

MUTATIONS = [
    ("duplicate", "private_json.py", 'if key in result:', 'if False:', 'checks.test_strict_json_refuses_without_retaining_input(b\'{"a":1,"a":2}\')'),
    ("nonfinite", "private_json.py", 'parse_constant=_constant', 'parse_constant=lambda _: 0', 'checks.test_strict_json_refuses_without_retaining_input(b\'{"a":NaN}\')'),
    ("overflow", "private_json.py", 'not math.isfinite(value)', 'False', 'checks.test_strict_json_refuses_without_retaining_input(b\'{"a":1e999}\')'),
    ("coercion", "wire.py", 'strict=True)', 'strict=False)', 'checks.test_start_context_version_never_coerced("1")'),
    ("extra", "wire.py", 'extra="forbid"', 'extra="ignore"', 'checks.test_start_all_layers_closed("inputs")'),
    ("version-prefix", "wire.py", 'Version = Literal["temper.private-draft.v1"]', 'Version = Annotated[str, Field(pattern=r"^temper\\.private-draft\\.v1")]', 'checks.test_registration_shape_refusal("version", checks.VERSION + ".extra")'),
    ("version-contains", "wire.py", 'Version = Literal["temper.private-draft.v1"]', 'Version = Annotated[str, Field(pattern=r"temper\\.private-draft\\.v1")]', 'checks.test_registration_shape_refusal("version", "prefix." + checks.VERSION)'),
    ("schema-identity", "schema.py", 'value["context_schema"] == self.identity.context_schema', 'True', 'checks.test_real_schema_context_and_exact_schema_identity("schema-prefix")'),
    ("schema-prefix", "schema.py", 'value["context_schema"] == self.identity.context_schema', 'value["context_schema"].startswith(self.identity.context_schema)', 'checks.test_real_schema_context_and_exact_schema_identity("schema-suffix")'),
    ("schema-contains", "schema.py", 'value["context_schema"] == self.identity.context_schema', 'self.identity.context_schema in value["context_schema"]', 'checks.test_real_schema_context_and_exact_schema_identity("schema-prefix")'),
    ("schema-validation", "schema.py", 'valid = self.__result.is_valid(value)', 'valid = True', 'checks.test_real_schema_draft_refusal("missing-summary")'),
    ("context-validation", "schema.py", 'self.__context.is_valid(value["context"])', 'True', 'checks.test_real_schema_context_and_exact_schema_identity("context-extra")'),
    ("external-ref", "schema.py", '_local_references(schema)', 'None', 'checks.test_schema_configuration_refuses_without_retrieval("remote-ref")'),
    ("provenance", "schema.py", 'if identity.source_kind == "synthetic" and not (', 'if False and not (', 'checks.test_schema_configuration_refuses_without_retrieval("false-provenance")'),
    ("result-identity", "schema.py", 'if value["result_schema"] != self.identity.result_schema:', 'if False:', 'checks.test_result_envelope_and_schema_are_separate_mandatory_checks("schema-prefix")'),
    ("status-run", "wire.py", 'if self.state == "registered" and self.execution_id is not None:', 'if False:', 'checks.test_status_binding_and_required_branch("registered-run")'),
    ("status-ready-run", "wire.py", 'if self.state in {"bound", "running", "ready", "acknowledged"} and self.execution_id is None:', 'if False:', 'checks.test_status_binding_and_required_branch("bound-no-run")'),
    ("receipt-run", "wire.py", 'if self.receipt is not None and self.receipt.execution_id != self.execution_id:', 'if False:', 'checks.test_status_binding_and_required_branch("wrong-receipt-run")'),
    ("safe-pre-send", "wire.py", 'if self.retry_class == "safe_pre_send" and self.transmission != "not_sent":', 'if False:', 'checks.test_failure_retry_class_never_implies_ambiguous_resend("safe_pre_send", "refused")'),
    ("explicit-refusal", "wire.py", 'if self.retry_class == "explicit_refusal" and self.transmission != "refused":', 'if False:', 'checks.test_failure_retry_class_never_implies_ambiguous_resend("explicit_refusal", "not_sent")'),
    ("outcome-phase", "contracts.py", 'if self.transmission != expected[self.phase]:', 'if False:', 'checks.test_outcome_phase_and_nullable_usage_refusals("phase")'),
    ("started", "contracts.py", 'if self.phase in {"http_refused", "streaming", "complete"} and not self.request_started:', 'if False:', 'checks.test_outcome_phase_and_nullable_usage_refusals("not-started")'),
    ("http-phase", "contracts.py", 'if (self.http_status is not None) != (self.phase == "http_refused"):', 'if False:', 'checks.test_outcome_phase_and_nullable_usage_refusals("http-on-complete")'),
    ("usage-missing", "contracts.py", 'if self.usage_state == "missing" and any(value is not None for value in counters):', 'if False:', 'checks.test_outcome_phase_and_nullable_usage_refusals("missing-number")'),
    ("usage-known", "contracts.py", 'if self.usage_state == "known" and any(value is None for value in counters):', 'if False:', 'checks.test_outcome_phase_and_nullable_usage_refusals("known-null")'),
    ("usage-partial", "contracts.py", 'if self.usage_state == "partial" and not (any(value is None for value in counters) and any(value is not None for value in counters)):', 'if False:', 'checks.test_outcome_phase_and_nullable_usage_refusals("partial-all-null")'),
    ("http-status", "contracts.py", 'if self.http_status is not None and self.http_status not in {400, 401, 403, 413, 429, 529}:', 'if False:', 'checks.test_http_refusal_status_is_closed_and_never_coerced(500)'),
    ("schema-retrieval", "schema.py", 'registry=Registry(), ', '', 'checks.test_schema_registry_never_retrieves_even_if_reference_precheck_is_removed()'),
    ("private-repr", "private_json.py", 'return "<PrivateJSON>"', 'return self.to_private_json().decode("utf-8")', 'checks.test_supported_private_representations_never_serialize_payload()'),
    ("private-pickle", "private_json.py", 'raise TypeError("private serialization forbidden")', 'return (str, (self.to_private_json().decode("utf-8"),))', 'checks.test_supported_private_representations_never_serialize_payload()'),
    ("private-close", "private_json.py", 'self.__raw = None', 'pass', 'checks.test_supported_private_representations_never_serialize_payload()'),
]


@pytest.mark.parametrize(("label", "filename", "old", "new", "check"), MUTATIONS, ids=[item[0] for item in MUTATIONS])
def test_deleted_or_loosened_guard_fails_named_test(tmp_path: Path, label: str, filename: str, old: str, new: str, check: str) -> None:
    root = Path(__file__).resolve().parents[2]
    package = tmp_path / "private_context"
    shutil.copytree(root / "temper_ai" / "private_context", package, ignore=shutil.ignore_patterns("__pycache__"))
    target = package / filename
    source = target.read_text()
    require(source.count(old) == 1)
    target.write_text(source.replace(old, new), encoding="utf-8")
    code = (
        "import temper_ai\n"
        f"temper_ai.__path__.insert(0, {str(tmp_path)!r})\n"
        "try:\n"
        "    from tests.test_private_context import test_contracts as checks\n"
        f"    {check}\n"
        "except AssertionError:\n"
        "    print('BITTEN')\n"
        "except Exception:\n"
        "    print('SETUP_OR_UNEXPECTED_ERROR')\n"
        "else:\n"
        "    print('SURVIVED')\n"
    )
    env = {"PATH": os.defpath, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    status, output = child_result([sys.executable, "-c", code], env)
    require(status == 0 and output == b"BITTEN\n")
