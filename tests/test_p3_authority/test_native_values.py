"""Tests for temper_ai.p3_authority.native_values, the shared native reference values.

Covers:
1. Combined happy path (bp-be8d76b9): each value meets its ``references`` protocol, the
   registry's records accept it, the issuer verifier's subject decoding returns it, and the
   selection snapshot's evidence and default instant carry it with unchanged strings.
2. Cold import in a fresh interpreter: native_values loads nothing past the standard library
   and ``references`` (no cryptography, issuer verifier or admission contract), with a
   control showing the probe sees those modules when they are loaded.
3. Shape pins: fields, order, annotations, no defaults, frozen, slots and properties.
4. The old issuer-side names are gone everywhere, and issuer_verifier re-exports nothing.
"""

from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import sys
import typing
from pathlib import Path

import pytest

from temper_ai.p3_authority import issuer_verifier, selection_snapshot
from temper_ai.p3_authority.native_values import (
    NativeIntervalValue,
    NativeProcessRefValue,
    NativeRootObjectValue,
    NativeWitnessValue,
)
from temper_ai.p3_authority.registry import (
    DecisionEvidenceRecord,
    ExistingSubjectRecord,
    _proc_ref,
)
from temper_ai.p3_authority.selection import TrustedInstant
from tests.test_p3_authority._composition_fixtures import make_pre_dispatch_job

_REPO_ROOT = Path(__file__).resolve().parents[2]

_VALUE_CLASSES = (
    NativeWitnessValue,
    NativeProcessRefValue,
    NativeIntervalValue,
    NativeRootObjectValue,
)

# Built from parts so this file never holds the old names itself.
_OLD_NAMES = tuple(
    "Issuer" + part for part in ("Witness", "ProcessRef", "Interval", "RootObject")
)
_NEW_NAMES = tuple(cls.__name__ for cls in _VALUE_CLASSES)

_ROOT = {
    "filesystem_object": "fs:1",
    "mount_identity": "mnt:1",
    "namespace_identity": "ns:1",
    "observation_epoch": "epoch:1",
}


def test_native_values_combined_happy_path_through_issuer_registry_and_snapshot() -> None:
    witness = NativeWitnessValue("witness:a")
    process = NativeProcessRefValue("proc:a")
    interval = NativeIntervalValue(clock_domain="monotonic:a", interval_witness=witness)
    root = NativeRootObjectValue(**_ROOT)

    # references protocols: NativeWitness, NativeProcessRef, NativeInterval, NativeRootObject
    assert witness.witness_reference == "witness:a"
    assert witness.witness_registration == "witness:a"
    assert process.process_registration == "proc:a"
    assert process.process_reference == "proc:a"
    assert interval.clock_domain == "monotonic:a"
    assert interval.interval_witness is witness
    assert interval.interval_witness.witness_reference == "witness:a"
    for name, value in _ROOT.items():
        assert getattr(root, name) == value

    # registry records accept them and read them by attribute
    assert ExistingSubjectRecord(identity=process).identity is process
    assert ExistingSubjectRecord(identity=root).identity is root
    instant = TrustedInstant(clock_domain="monotonic:a", reading="5", witness=witness)
    assert instant.witness is witness
    assert _proc_ref(process) == "proc:a"

    # issuer verifier: subject decoding returns the shared values
    future = issuer_verifier.record_subject_to_native(
        {"kind": "future", "selected_scope_reference": "scope:a"}
    )
    assert type(future) is issuer_verifier.IssuerFutureSubject
    existing_process = issuer_verifier.record_subject_to_native(
        {"kind": "existing-process", "process_registration": "proc:b"}
    )
    assert type(existing_process) is issuer_verifier.IssuerExistingSubject
    assert existing_process.identity == NativeProcessRefValue("proc:b")
    assert type(existing_process.identity) is NativeProcessRefValue
    existing_root = issuer_verifier.record_subject_to_native(
        {"kind": "existing-root", **_ROOT}
    )
    assert existing_root.identity == root
    assert type(existing_root.identity) is NativeRootObjectValue
    hints = typing.get_type_hints(issuer_verifier.IssuerExistingSubject)
    assert hints["identity"] == NativeProcessRefValue | NativeRootObjectValue

    # selection snapshot: its evidence process keeps the same strings under both names
    evidence = selection_snapshot._build_snapshot_evidence(make_pre_dispatch_job())
    assert type(evidence) is DecisionEvidenceRecord
    assert len(evidence.processes) == 1
    snapshot_process = evidence.processes[0]
    assert type(snapshot_process) is NativeProcessRefValue
    assert snapshot_process.process_registration == "proc:temper-selection-snapshot"
    assert snapshot_process.process_reference == "proc:temper-selection-snapshot"
    assert _proc_ref(snapshot_process) == "proc:temper-selection-snapshot"
    default_at = getattr(selection_snapshot, "_DEFAULT_VERIFIED_AT", None)
    if default_at is not None:  # temper #289 removes the default instant
        assert type(default_at.witness) is NativeWitnessValue
        assert default_at.witness.witness_reference == "witness:temper-selection-snapshot"
        assert default_at.witness.witness_registration == "witness:temper-selection-snapshot"
    # one piece, not three: the look-alike private carriers are gone
    assert not hasattr(selection_snapshot, "_SnapshotProcessRef")
    assert not hasattr(selection_snapshot, "_SnapshotWitness")


# A fresh interpreter loads references first (the one allowed dependency, which also
# runs temper_ai's package initialiser), then the target, and reports every module the
# target added beyond the standard library, and which forbidden modules are loaded.
_COLD_IMPORT_PROBE = """
import importlib, json, sys
import temper_ai.p3_authority.references
target = sys.argv[1]
before = set(sys.modules)
importlib.import_module(target)
added = set(sys.modules) - before - {target}
outside_stdlib = sorted(
    name for name in added if name.split(".")[0] not in sys.stdlib_module_names
)
forbidden = sorted(
    name
    for name in sys.modules
    if name == "cryptography"
    or name.startswith("cryptography.")
    or name in ("temper_ai.p3_authority.issuer_verifier", "temper_ai.config.admission_contract")
)
print(json.dumps({"outside_stdlib": outside_stdlib, "forbidden": forbidden}))
"""


def _cold_import_report(target: str) -> tuple[int, dict[str, list[str]] | None]:
    proc = subprocess.run(
        [sys.executable, "-c", _COLD_IMPORT_PROBE, target],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    code = proc.returncode
    lines = proc.stdout.strip().splitlines()
    try:
        report = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError:
        report = None
    return code, report


def test_native_values_cold_import_loads_only_stdlib_and_references() -> None:
    code, report = _cold_import_report("temper_ai.p3_authority.native_values")
    assert code == 0
    assert report is not None
    outside_stdlib = report["outside_stdlib"]
    forbidden = report["forbidden"]
    assert outside_stdlib == []
    assert forbidden == []


def test_cold_import_probe_sees_cryptography_issuer_and_admission_when_loaded() -> None:
    """Control: the same probe on issuer_verifier reports all three forbidden modules."""
    code, report = _cold_import_report("temper_ai.p3_authority.issuer_verifier")
    assert code == 0
    assert report is not None
    forbidden = set(report["forbidden"])
    outside_stdlib = set(report["outside_stdlib"])
    assert "cryptography" in forbidden
    assert "temper_ai.p3_authority.issuer_verifier" not in outside_stdlib  # the target
    assert "temper_ai.config.admission_contract" in forbidden
    assert "temper_ai.config.admission_contract" in outside_stdlib
    assert "temper_ai.p3_authority.native_values" in outside_stdlib


@pytest.mark.parametrize(
    ("cls", "fields", "properties"),
    [
        (NativeWitnessValue, (("witness_reference", "str"),), {"witness_registration": "witness_reference"}),
        (NativeProcessRefValue, (("process_registration", "str"),), {"process_reference": "process_registration"}),
        (
            NativeIntervalValue,
            (("clock_domain", "str"), ("interval_witness", "NativeWitness")),
            {},
        ),
        (
            NativeRootObjectValue,
            (
                ("filesystem_object", "str"),
                ("mount_identity", "str"),
                ("namespace_identity", "str"),
                ("observation_epoch", "str"),
            ),
            {},
        ),
    ],
    ids=lambda value: value.__name__ if isinstance(value, type) else None,
)
def test_value_class_keeps_fields_frozen_slots_and_properties(
    cls: type, fields: tuple[tuple[str, str], ...], properties: dict[str, str]
) -> None:
    declared = dataclasses.fields(cls)
    assert tuple((f.name, f.type) for f in declared) == fields
    assert all(f.default is dataclasses.MISSING for f in declared)
    assert all(f.default_factory is dataclasses.MISSING for f in declared)
    assert all(f.init and not f.kw_only for f in declared)
    params = cls.__dataclass_params__  # type: ignore[attr-defined]
    assert params.frozen is True
    assert params.eq is True
    assert cls.__slots__ == tuple(name for name, _ in fields)  # type: ignore[attr-defined]
    assert cls.__module__ == "temper_ai.p3_authority.native_values"

    values = [f"{name}-value" for name, _ in fields]
    instance = cls(*values)
    assert not hasattr(instance, "__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, fields[0][0], "changed")
    assert instance == cls(*values)
    assert hash(instance) == hash(cls(*values))

    own_properties = {
        name for name, member in vars(cls).items() if isinstance(member, property)
    }
    assert own_properties == set(properties)
    for prop, source in properties.items():
        assert getattr(instance, prop) == getattr(instance, source)


def test_issuer_verifier_has_no_old_names_and_reexports_no_native_value() -> None:
    exported = set(issuer_verifier.__all__)
    for name in _OLD_NAMES:
        assert not hasattr(issuer_verifier, name), name
        assert name not in exported, name
    for name in _NEW_NAMES:
        assert name not in exported, name
    assert "IssuerFutureSubject" in exported
    assert "IssuerExistingSubject" in exported


def test_old_issuer_value_names_are_absent_from_code_tests_and_docs() -> None:
    pattern = re.compile(r"\b(?:" + "|".join(_OLD_NAMES) + r")\b")
    hits: list[str] = []
    for top in ("temper_ai", "tests", "docs"):
        for path in sorted((_REPO_ROOT / top).rglob("*")):
            if path.suffix not in {".py", ".md", ".yaml", ".yml", ".txt", ".toml"}:
                continue
            if "__pycache__" in path.parts or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if pattern.search(text):
                hits.append(str(path.relative_to(_REPO_ROOT)))
    assert hits == []
