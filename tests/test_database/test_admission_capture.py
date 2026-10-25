"""Synthetic transaction tests: existing DB-tier path runs these on CI Postgres."""
from dataclasses import FrozenInstanceError, replace

import pytest
from sqlalchemy import update
from sqlmodel import select

from temper_ai.config.admission_capture import RawCapture, SnapshotResolver
from temper_ai.config.admission_contract import (
    AdmissionRefused,
    CandidateInvocationBinding,
    DispatchIdentity,
    FrozenJSON,
    RefusalCode,
)
from temper_ai.config.candidate_admission import load_candidate
from temper_ai.config.models import Config
from temper_ai.config.store import ConfigStore
from temper_ai.database import get_session
from temper_ai.shared.types import ExecutionContext
from temper_ai.spawner import box_guard
from tests.test_config.admission_cases import hashed, text, typed_case


def test_capture_closure_resolver_actual_projection_and_context_happy_path(monkeypatch):
    raw, codec, authority, descriptor, _, source = typed_case()
    store = ConfigStore()

    def no_transformed_read(*args, **kwargs):
        raise AssertionError("transformed source lookup is forbidden")

    monkeypatch.setattr(store, "get", no_transformed_read)
    monkeypatch.setattr("temper_ai.config.store.substitute_env_vars", no_transformed_read)
    with get_session() as transaction:
        # Uncommitted rows are visible only through this supplied transaction.
        for (kind, name), config in raw.items():
            transaction.add(Config(type=kind, name=name, schema_version="1.0", config=config))
        transaction.flush()
        records = RawCapture(codec, authority, store).capture(descriptor, transaction=transaction)
        resolver = SnapshotResolver(codec, descriptor, records, authority=authority)
        nodes, workflow, projection = load_candidate(codec, descriptor, resolver.closure, authority=authority, source=source)
        assert projection.wire == text(descriptor.value()["graph"]).encode()
        assert [n.name for n in nodes[0].child_nodes] == ["prepare", "call"]
        assert workflow.nodes[0].ref is None
        # Capture keeps bytes, never an ORM mapping or one of its returned parses.
        config_copy = resolver.get("caller", "agent")
        config_copy["agent"]["single_call"]["slot"] = "A2"
        raw[("agent", "caller")]["agent"]["single_call"]["slot"] = "A3"
        assert resolver.get("caller", "agent")["agent"]["single_call"]["slot"] == "A1"
        transaction.rollback()
    # No DB lifetime is needed to resolve the captured snapshot again.
    again, _, same = load_candidate(codec, descriptor, resolver.closure, authority=authority, source=source)
    assert same.wire == projection.wire
    assert again is not nodes
    d = descriptor.value()
    native_node = d["graph"]["nodes"][2]
    binding = CandidateInvocationBinding(
        descriptor, resolver.closure, hashed("graph", d["graph"]),
        DispatchIdentity(d["execution_uuid"], "00000000-0000-0000-0000-000000000002", 1),
        ("group", "call"), "position-1", FrozenJSON(native_node["node_json"].encode()),
        FrozenJSON(native_node["factory"]["config_json"].encode()), None,
    )
    context = ExecutionContext(d["execution_uuid"], "sample", "", "", None, None, admission=binding)
    child = replace(context, node_path="group.call", agent_name="caller")
    assert child.admission is binding and context.node_path == ""
    with pytest.raises(FrozenInstanceError):
        binding.node_path = ("forged",)
    parsed = child.admission.expected_agent.value()
    parsed["single_call"]["slot"] = "B1"
    assert child.admission.expected_agent.value()["single_call"]["slot"] == "A1"
    assert replace(context, admission=None).admission is None
    with pytest.raises(AdmissionRefused, match="^invalid_type$"):
        replace(context, admission={})


def test_raw_get_separate_version_no_env_substitution_and_owned_copy(monkeypatch):
    store = ConfigStore()
    literal = {"agent": {"name": "raw", "value": "${ADMISSION_SYNTHETIC_VARIABLE}"}}
    store.put("raw", "agent", literal, schema_version="future")
    monkeypatch.setenv("ADMISSION_SYNTHETIC_VARIABLE", "changed")
    with get_session() as transaction, transaction.begin():
        raw, version = store.get_raw_record("raw", "agent", transaction=transaction)
        assert version == "future" and raw == literal
        raw["agent"]["name"] = "changed"
        assert store.get_raw_record("raw", "agent", transaction=transaction)[0] == literal
    # Normal get remains unchanged: its version check still refuses this row.
    from temper_ai.config.helpers import SchemaVersionError
    with pytest.raises(SchemaVersionError):
        store.get("raw", "agent")
    store.put("raw", "agent", literal)
    assert store.get("raw", "agent")["agent"]["value"] == "changed"


def test_raw_columns_do_not_reuse_stale_orm_identity():
    store = ConfigStore()
    store.put("raw", "agent", {"old": True})
    with get_session() as transaction:
        row = transaction.exec(select(Config).where(Config.name == "raw")).one()
        transaction.execute(update(Config).where(Config.id == row.id).values(
            config={"new": True}, schema_version="2.0"), execution_options={"synchronize_session": False})
        assert row.config == {"old": True}
        assert store.get_raw_record("raw", "agent", transaction=transaction) == ({"new": True}, "2.0")


def test_capture_binds_original_raw_not_db_authoring_file_identity():
    raw, codec, authority, descriptor, _, _ = typed_case()
    store = ConfigStore()
    with get_session() as transaction:
        for (kind, name), config in raw.items():
            if kind == "workflow":
                config["workflow"]["description"] = "different DB value"
            transaction.add(Config(type=kind, name=name, schema_version="1.0", config=config))
        transaction.flush()
        with pytest.raises(AdmissionRefused, match="^digest_mismatch$"):
            RawCapture(codec, authority, store).capture(descriptor, transaction=transaction)


@pytest.mark.parametrize("bad_version", ["2.0", "1.1"])
def test_capture_binds_separate_schema_column(bad_version):
    raw, codec, authority, descriptor, _, _ = typed_case()
    with get_session() as transaction:
        for (kind, name), config in raw.items():
            transaction.add(Config(type=kind, name=name, schema_version=bad_version, config=config))
        transaction.flush()
        with pytest.raises(AdmissionRefused, match="^closure_mismatch$"):
            RawCapture(codec, authority, ConfigStore()).capture(descriptor, transaction=transaction)


def test_raw_transaction_missing_type_and_classified_fences(monkeypatch):
    store = ConfigStore()
    with pytest.raises(AdmissionRefused, match="^source_origin$"):
        store.get_raw_record("missing", "agent", transaction=object())
    with get_session() as transaction:
        with pytest.raises(AdmissionRefused, match="^source_origin$"):
            store.get_raw_record("missing", "agent", transaction=transaction)
        with transaction.begin():
            with pytest.raises(AdmissionRefused, match="^outside_closure$"):
                store.get_raw_record("missing", "agent", transaction=transaction)
            with pytest.raises(AdmissionRefused, match="^invalid_type$"):
                store.get_raw_record("missing", "not-a-kind", transaction=transaction)
            monkeypatch.setattr(box_guard, "active", lambda: object())
            with pytest.raises(AdmissionRefused, match="^source_origin$"):
                store.get_raw_record("missing", "agent", transaction=transaction)
            _, codec, authority, descriptor, _, _ = typed_case()
            with pytest.raises(AdmissionRefused) as exc:
                RawCapture(codec, authority, store).capture(descriptor, transaction=transaction)
            assert exc.value.code == RefusalCode.MODE
