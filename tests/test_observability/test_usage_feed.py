"""Fixed metadata only: pure item stage, then landed #129 -> #125 on throwaway SQLite.

No provider, model, workflow, live DB, runtime process or event-content fixture.
Mutation controls compile the serializer in memory; they never edit source files.
"""

from __future__ import annotations

import ast
import inspect
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from temper_ai.llm.pi_stream import PiEventMapper
from temper_ai.observability import usage_feed as feed
from temper_ai.observability import usage_rows as writer
from temper_ai.observability.models import Event
from temper_ai.pi_agent.turn import ChunkSink, _record_end

AT = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)
KEYS = {"event_id", "revision", "call_key", "origin", "execution_id", "agent_event_id", "event",
        "call_kind", "llm_call_id", "started_event_id", "provider", "model", "occurred_at",
        "occurrence_basis", "observed_tokens", "token_convention", "exclusive_tokens", "legacy_cost",
        "lost_attempts", "faults"}
OBSERVED = {"prompt": 150, "completion": 10, "total": 160, "cache_read": 30, "cache_write": 20}
EXCLUSIVE = {"input": 100, "output": 10, "cache_read": 30, "cache_write": 20}
NATIVE = {"prompt_tokens": 150, "completion_tokens": 10, "total_tokens": 160,
          "cache_read_tokens": 30, "cache_write_tokens": 20}


def row(**changes):
    return {"seq": 999, "event_id": "end-1", "revision": 0, "instance": "not-on-wire",
            "execution_id": "execution-1", "parent_id": "agent-1", "event_type": "llm.call.completed",
            "call_kind": "model", "llm_call_id": "call-1", "started_event_id": "start-1",
            "provider": "anthropic", "model": "model-v1", **NATIVE, "token_source": "service",
            "legacy_cost_usd": 0.30000000000000004, "legacy_cost_source": "service", "lost_attempts": 0,
            "event_at": AT + timedelta(days=1), "occurred_at": AT, "occurrence_basis": "call_end",
            "origin": "live", "fault_codes": "", **changes}


def pi(**changes):
    return row(**{"token_source": "pi", "prompt_tokens": 100, "legacy_cost_source": "pi_estimate", **changes})


def encoded(item):
    return json.dumps(item, allow_nan=False, ensure_ascii=True)


def test_00_combined_whole_item_happy_path():
    original = row()
    item = feed.to_item(original)
    assert set(item) == KEYS and "seq" not in item
    assert item["observed_tokens"] == OBSERVED
    assert item["exclusive_tokens"] == EXCLUSIVE  # 150 - 30 - 20; total is NOT a class.
    assert item["token_convention"] == "service-inclusive-prompt"
    assert sum(item["exclusive_tokens"].values()) == 160
    assert item["legacy_cost"] == {"text": "0.30000000000000004", "source": "service", "basis": "unproven"}
    assert item["occurred_at"] == "2026-01-02T03:04:05.678Z" and item["occurrence_basis"] == "call_end"
    assert item["agent_event_id"] == "agent-1" and item["faults"] == []
    start = feed.to_item(row(event_id="start-1", event_type="llm.call.started", occurrence_basis="call_start"))
    assert item["call_key"] == start["call_key"] == "svc:start-1"
    pi_start = feed.to_item(pi(event_id="pi-start", event_type="llm.call.started", occurrence_basis="call_start"))
    pi_end = feed.to_item(pi(started_event_id="pi-start"))
    assert pi_start["call_key"] == pi_end["call_key"] == "pi:call-1"
    assert pi_end["observed_tokens"] == {**OBSERVED, "prompt": 100}
    assert pi_end["exclusive_tokens"] is None  # Never subtract caches from Pi's input.
    assert pi_end["token_convention"] == "pi-unverified"
    assert "pi-convention-unverified" in pi_end["faults"]
    revised = feed.to_item(row(revision=3, origin="reconciled", prompt_tokens=120, total_tokens=130))
    assert revised["call_key"] == item["call_key"] and revised["revision"] == 3
    assert revised["observed_tokens"]["prompt"] == 120 and revised["exclusive_tokens"]["input"] == 70
    assert original == row()  # No remembered maxima and no input mutation.
    assert len(encoded(item).encode("ascii")) <= 2048
    assert feed.to_item(SimpleNamespace(**row())) == item


def test_data_missing_overlap_total_only_and_unproven_labels():
    missing = feed.to_item(row(cache_read_tokens=None))
    assert missing["observed_tokens"]["cache_read"] is None and missing["exclusive_tokens"] is None
    assert "exclusive-unavailable" in missing["faults"]
    overlap = feed.to_item(row(prompt_tokens=40))
    assert overlap["exclusive_tokens"] is None and "token-overlap" in overlap["faults"]
    only_total = feed.to_item(row(**{key: None for key in NATIVE if key != "total_tokens"}))
    assert only_total["observed_tokens"] == dict.fromkeys(OBSERVED, None) | {"total": 160}
    assert only_total["exclusive_tokens"] is None
    missing = feed.to_item(row(provider=None, model=None, **dict.fromkeys(NATIVE)))
    assert missing["provider"] is None and missing["model"] is None
    assert missing["observed_tokens"] == dict.fromkeys(OBSERVED)
    assert {"provider-unproven", "model-unproven", "usage-absent"} <= set(missing["faults"])
    assert missing["legacy_cost"]["text"] == "0.30000000000000004"


@pytest.mark.parametrize("provider", ["openai", "codex", "gemini", "other", None])
def test_non_anthropic_has_no_exclusive_inference(provider):
    item = feed.to_item(row(provider=provider))
    assert item["observed_tokens"] == OBSERVED and item["exclusive_tokens"] is None
    assert item["token_convention"] == "service-unverified" and "exclusive-unavailable" in item["faults"]


@pytest.mark.parametrize("value", [True, False, 1.5, 1.0, -1, 2**53, "7", float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", list(NATIVE) + ["lost_attempts"])
def test_each_integer_guard(value, field):
    item = feed.to_item(row(**{field: value}))
    if field == "lost_attempts":
        assert item["lost_attempts"] is None and "lost-invalid" in item["faults"]
    else:
        key = next(key for key, source in feed._FIELDS.items() if source == field)
        assert item["observed_tokens"][key] is None and feed._TOKEN_FAULTS[key] in item["faults"]
    assert "NaN" not in encoded(item) and "Infinity" not in encoded(item)


def test_integer_boundaries_service_known_zeros_and_all_safe_fields():
    for value in (0, 2**53 - 1):
        item = feed.to_item(row(**dict.fromkeys(NATIVE, value), lost_attempts=value))
        assert set(item["observed_tokens"].values()) == {value} and item["lost_attempts"] == value
    assert feed.to_item(row(**dict.fromkeys(NATIVE, 0)))["exclusive_tokens"] == dict.fromkeys(EXCLUSIVE, 0)


def test_failure_and_compaction_never_inherit_usage_or_labels():
    with_usage = feed.to_item(row(event_type="llm.call.failed"))
    assert with_usage["observed_tokens"] == OBSERVED and with_usage["event"] == "call_failed"
    absent = feed.to_item(row(event_type="llm.call.failed", **dict.fromkeys(NATIVE)))
    assert absent["observed_tokens"] == dict.fromkeys(OBSERVED) and "usage-absent" in absent["faults"]
    compact = feed.to_item(pi(call_kind="compaction", provider=None, model=None, **dict.fromkeys(NATIVE),
                              tokensBefore=999, estimatedTokensAfter=111))
    assert compact["call_kind"] == "compaction" and compact["provider"] is None and compact["model"] is None
    assert compact["observed_tokens"] == dict.fromkeys(OBSERVED)
    assert "usage-absent" in compact["faults"]


def test_pi_zero_null_and_total_rules_old_and_new():
    all_zero = feed.to_item(pi(**dict.fromkeys(NATIVE, 0)))
    assert all_zero["observed_tokens"] == dict.fromkeys(OBSERVED) and "usage-absent" in all_zero["faults"]
    for field in ("prompt_tokens", "completion_tokens", "cache_read_tokens", "cache_write_tokens"):
        zero = feed.to_item(pi(**{field: 0, "total_tokens": 200}))
        key = next(key for key, source in feed._FIELDS.items() if source == field)
        assert zero["observed_tokens"][key] is None and zero["observed_tokens"]["total"] is None
        assert {"pi-zero-or-absent", "pi-total-unverified"} <= set(zero["faults"])
        unknown = feed.to_item(pi(**{field: None}))
        assert unknown["observed_tokens"][key] is None and unknown["observed_tokens"]["total"] is None
        assert "pi-count-unreported" in unknown["faults"]
    mismatch = feed.to_item(pi(total_tokens=161))
    assert mismatch["observed_tokens"]["total"] is None and "pi-total-unverified" in mismatch["faults"]
    assert feed.to_item(pi(total_tokens=None))["observed_tokens"]["total"] is None
    assert feed.to_item(pi())["observed_tokens"] == {**OBSERVED, "prompt": 100}
    # An alleged version/API in unknown columns cannot promote this convention.
    claimed = feed.to_item(pi(pi_version="0.87.1", api="anthropic-messages"))
    assert claimed["token_convention"] == "pi-unverified" and claimed["exclusive_tokens"] is None


def test_call_key_revisions_unlinked_and_row_fault_allowlist():
    old = feed.to_item(row(started_event_id=None))
    assert old["call_key"] is None and "call-unlinked" in old["faults"]
    missing_pi = feed.to_item(pi(llm_call_id=None))
    assert missing_pi["call_key"] is None and "call-unlinked" in missing_pi["faults"]
    # #126 adds this one closed code without DDL, independently of this task.
    # The task landing second must assert writer membership on its exact head.
    assert feed.ROW_FAULT_CODES == writer.FAULT_CODES | {"call-unended"}
    for code in sorted(writer.FAULT_CODES | {"call-unended"}):
        item = feed.to_item(row(fault_codes=code))
        assert (code in item["faults"]) is (code != "ordering-deferred")
        assert "ordering-deferred" not in item["faults"]
    faults = feed.to_item(row(fault_codes="usage-missing,model-unproven,usage-missing,ordering-deferred"))["faults"]
    assert faults == sorted(set(faults))


def test_unended_start_is_only_the_explicit_marker_never_revision_or_origin():
    for factory, key in ((row, "svc:start-1"), (pi, "pi:call-1")):
        initial = factory(event_id="start-1", event_type="llm.call.started", occurrence_basis="call_start",
                          **dict.fromkeys(NATIVE), legacy_cost_usd=None)
        revised = {**initial, "revision": 1, "origin": "reconciled"}
        assert feed.to_item(initial)["occurrence_basis"] == "call_start"
        assert feed.to_item(revised)["occurrence_basis"] == "call_start"
        marked = feed.to_item({**revised, "fault_codes": "call-unended"})
        assert marked["call_key"] == key and marked["occurrence_basis"] == "call_start_unended"
        assert marked["observed_tokens"] == dict.fromkeys(OBSERVED)
        assert "call-unended" in marked["faults"]
        end = feed.to_item(factory(fault_codes="call-unended"))
        assert end["occurrence_basis"] == "call_end" and "call-unended" in end["faults"]
    # SQL accepts only two basis values. Wire-only spelling is never a substitute
    # for explicit producer evidence, on a start OR an end.
    for event_type in ("llm.call.started", "llm.call.completed"):
        with pytest.raises(ValueError, match="^usage item occurrence-basis invalid$"):
            feed.to_item(row(event_type=event_type, occurrence_basis="call_start_unended"))


def test_data_pi_arithmetic_consistent_total_is_not_exclusive_provenance():
    item = feed.to_item(pi(model="claude-sonnet-4-5", prompt_tokens=100, completion_tokens=20,
                          cache_read_tokens=80, cache_write_tokens=10, total_tokens=210))
    assert item["observed_tokens"] == {"prompt": 100, "completion": 20, "cache_read": 80,
                                      "cache_write": 10, "total": 210}
    assert item["exclusive_tokens"] is None and item["token_convention"] == "pi-unverified"
    assert "pi-convention-unverified" in item["faults"] and "pi-total-unverified" not in item["faults"]


@pytest.mark.parametrize("field", ["event_id", "execution_id", "parent_id", "llm_call_id", "started_event_id", "provider", "model"])
@pytest.mark.parametrize("value", ["x" * 129, "non-ascii-é", "CANARY content", "line\nCANARY", {"CANARY": "object"}, True, ""])
def test_label_and_id_limits(field, value):
    item = feed.to_item(row(**{field: value}))
    wire = "agent_event_id" if field == "parent_id" else field
    assert item[wire] is None and "CANARY" not in encoded(item)
    assert (f"{field}-invalid" if field in ("provider", "model") else "id-invalid") in item["faults"]


def test_native_label_policy_and_ascii_allowed_values():
    for field in ("provider", "model"):
        for value in ("/CANARY/path", "../CANARY", "C:/CANARY", "https://CANARY", "user:CANARY@host"):
            item = feed.to_item(row(**{field: value}))
            assert item[field] is None and "CANARY" not in encoded(item)
    allowed = "aZ09._:/@+-"
    item = feed.to_item(row(provider="org/model@v1", model="model+version-1", llm_call_id=allowed))
    assert item["provider"] == "org/model@v1" and item["model"] == "model+version-1"
    assert item["llm_call_id"] == allowed
    assert feed.to_item(row(model="x" * 128))["model"] == "x" * 128


@pytest.mark.parametrize("value", [None, True, -1.0, float("nan"), float("inf"), -float("inf"), "CANARY", 1])
def test_legacy_cost_fails_closed(value):
    item = feed.to_item(row(legacy_cost_usd=value))
    assert item["legacy_cost"]["text"] is None and "legacy-cost-invalid" in item["faults"]
    assert "CANARY" not in encoded(item) and "NaN" not in encoded(item) and "Infinity" not in encoded(item)


def test_cost_zero_source_and_fault_input_limits():
    for value in (0.0, -0.0, 1.7976931348623157e308):
        assert feed.to_item(row(legacy_cost_usd=value))["legacy_cost"]["text"] == repr(value)
    for value in ("CANARY", [], True):
        cost = feed.to_item(row(legacy_cost_source=value))
        assert cost["legacy_cost"]["source"] is None and "legacy-cost-invalid" in cost["faults"]
    assert feed.to_item(row(legacy_cost_source=None))["legacy_cost"]["source"] is None
    for value in (None, [], "CANARY", "x" * 257, "usage-missing,CANARY"):
        item = feed.to_item(row(fault_codes=value))
        assert "faults-invalid" in item["faults"] and "CANARY" not in encoded(item)
        assert set(item["faults"]) <= feed.FAULT_CODES


def test_unknown_columns_are_never_read_and_closed_enums_never_echo():
    class Poison:
        def __str__(self):
            raise AssertionError("unknown value read")
    item = feed.to_item(row(data=Poison(), prompt=Poison(), task_id=Poison(), project=Poison(),
                            initiative=Poison(), payer=Poison(), root=Poison(), scope=Poison()))
    assert set(item) == KEYS
    for field in ("event_type", "origin", "token_source", "occurrence_basis"):
        for value in ("CANARY", None, []):
            with pytest.raises(ValueError) as error:
                feed.to_item(row(**{field: value}))
            assert "CANARY" not in str(error.value)
    for value in (True, -1, 2**53, None, 1.5):
        with pytest.raises(ValueError, match="^usage item revision invalid$"):
            feed.to_item(row(revision=value))
    item = feed.to_item(row(call_kind="CANARY"))
    assert item["call_kind"] is None and "kind-invalid" in item["faults"]


def test_native_times_utc_milliseconds_not_recording_time():
    assert feed.to_item(row(occurred_at=AT.replace(tzinfo=None)))["occurred_at"] == "2026-01-02T03:04:05.678Z"
    shifted = AT.astimezone(timezone(timedelta(hours=5, minutes=30)))
    item = feed.to_item(row(occurred_at=shifted, event_at=AT + timedelta(days=100)))
    assert item["occurred_at"] == "2026-01-02T03:04:05.678Z"
    for value in (None, "CANARY", float("nan")):
        with pytest.raises(ValueError, match="^usage item occurred-at invalid$"):
            feed.to_item(row(occurred_at=value))


def test_byte_bound_is_fail_closed_and_item_encoder_forbids_nonfinite():
    # Legal individual fields can still exceed the item-wide budget. No partial truncation.
    # Measured 2050 bytes with the guard disabled (the first 2008-byte fixture
    # was below the bound and correctly did not trigger it).
    large = pi(**{key: "x" * 128 for key in ("event_id", "execution_id", "parent_id", "llm_call_id",
                                                      "started_event_id", "provider", "model")},
               **dict.fromkeys(NATIVE, 2**53 - 1), lost_attempts=2**53 - 1,
               revision=2**53 - 1, origin="reconciled", call_kind="compaction",
               legacy_cost_usd=1.7976931348623157e308,
               fault_codes=",".join(sorted(writer.FAULT_CODES - {"ordering-deferred"})))
    with pytest.raises(ValueError, match="^usage item exceeds byte bound$"):
        feed.to_item(large)
    assert len(encoded(feed.to_item(row())).encode("ascii")) <= 2048
    # Catch the defensive json setting, even when upstream numeric guards are bypassed.
    namespace = {}
    exec(compile(inspect.getsource(feed), feed.__file__, "exec"), namespace)
    namespace["_legacy_cost"] = lambda *args: {"text": float("nan"), "source": None, "basis": "unproven"}
    with pytest.raises(ValueError, match="Out of range float values"):
        namespace["to_item"](row())


def test_serializer_has_no_io_or_database_imports():
    tree = ast.parse(inspect.getsource(feed))
    roots = {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    roots |= {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert roots == {"__future__", "json", "math", "re", "collections", "datetime", "typing"}


def test_later_129_125_sqlite_integration_preserves_unknowns_cost_identity_and_faults():
    """The deferred check, NOW: landed mapper/turn sink -> landed SQL writer -> item.

    A local recorder accepts only metadata produced from these fixed usage records.
    It stores no event payload and exposes only numeric agent-end cost, never text.
    """
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    class NumericSink:
        cost = None
        def record(self, event_type, data=None, **ids):
            if event_type not in writer.CALL_TYPES:
                if event_type in ("agent.completed", "agent.failed"):
                    self.cost = data["cost_usd"]
                return ids.get("event_id")
            projection = writer.extract(event_type, data, ids, AT)
            with Session(engine) as session:
                session.add(Event(id=ids["event_id"], type=event_type, timestamp=AT,
                                  execution_id=ids["execution_id"], parent_id=ids["parent_id"], data=None))
                writer.write_or_queue_row(session, projection)
                session.commit()
            return ids["event_id"]
        def broadcast_stream_chunk(self, *args, **kwargs):
            pass
    cases = [
        ({"input": 100, "output": 10, "cacheRead": 30, "cacheWrite": 20, "totalTokens": 160},
         {"prompt": 100, "completion": 10, "cache_read": 30, "cache_write": 20, "total": 160}, "stop", False),
        ({"input": 100, "output": 10, "cacheRead": 90, "cacheWrite": 0, "totalTokens": 200},
         {"prompt": 100, "completion": 10, "cache_read": 90, "cache_write": None, "total": None}, "stop", False),
        ({"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 200},
         dict.fromkeys(OBSERVED), "stop", False),
        ({"input": 100, "output": 10, "cacheRead": 30, "cacheWrite": 20, "totalTokens": 161},
         {"prompt": 100, "completion": 10, "cache_read": 30, "cache_write": 20, "total": None}, "error", False),
        ({"input": 100, "output": 10, "cacheRead": 30, "cacheWrite": 20, "cacheWrite1h": 4, "totalTokens": 160},
         {"prompt": 100, "completion": 10, "cache_read": 30, "cache_write": None, "total": None}, "stop", False),
        ({"input": True, "output": 1.5, "cacheRead": -1, "cacheWrite": 2**53, "totalTokens": 200},
         dict.fromkeys(OBSERVED), "stop", False),
        ({}, dict.fromkeys(OBSERVED), "stop", False),
        ({"input": 100, "output": 10, "cacheRead": 30, "cacheWrite": 0, "totalTokens": 140},
         {"prompt": 100, "completion": 10, "cache_read": 30, "cache_write": None, "total": None}, "stop", True),
    ]
    try:
        for number, (usage, expected, stop, compact) in enumerate(cases):
            sink = NumericSink()
            mapper = PiEventMapper(ChunkSink(sink), execution_id=f"run-{number}", agent_event_id=f"agent-{number}",
                                   agent_name="fixture", session_id="fixture", clock=lambda: 1.0)
            raw = {**usage, "cost": {"total": 0.30000000000000004}}
            if compact:
                mapper.handle({"type": "auto_compaction_start"})
                mapper.handle({"type": "auto_compaction_end", "result": {"usage": raw,
                               "tokensBefore": 999, "estimatedTokensAfter": 111}})
            else:
                message = {"role": "assistant", "provider": "anthropic", "model": "model-v1",
                           "stopReason": stop, "usage": raw}
                mapper.handle({"type": "message_start", "message": message})
                mapper.handle({"type": "message_end", "message": message})
            mapper.handle({"type": "agent_end"})
            _record_end(sink, mapper, mapper.finish(), 1.0, {})
            # Existing agent-end aggregation rounds to ten places; the SQL
            # per-call legacy float is separate and must retain its exact repr.
            assert sink.cost == 0.3 and mapper.usage_snapshot()["cost_usd"] == 0.3
            with Session(engine) as session:
                records = session.exec(select(writer.UsageCallRow).where(
                    writer.UsageCallRow.execution_id == f"run-{number}").order_by(writer.UsageCallRow.seq)).all()
                assert len(records) == 2
                start, end = [deepcopy(record) for record in records]
                assert {key: getattr(end, field) for key, field in feed._FIELDS.items()} == expected
                assert end.legacy_cost_usd == 0.30000000000000004
                start_item, item = feed.to_item(start), feed.to_item(end)
                assert item["observed_tokens"] == expected
                assert start_item["call_key"] == item["call_key"] == f"pi:{end.llm_call_id}"
                assert item["legacy_cost"] == {"text": "0.30000000000000004", "source": "pi_estimate", "basis": "unproven"}
                assert set(filter(None, end.fault_codes.split(","))) <= set(item["faults"])
                assert item["event"] == ("call_failed" if stop == "error" else "call_completed")
                if compact:
                    assert item["call_kind"] == "compaction" and item["provider"] is None and item["model"] is None
                # Same event, higher revision, lower reported values: never clamp a restatement upward.
                revised = writer.UsageCallRow(**end.model_dump(exclude={"seq"}))
                revised.revision, revised.origin = 1, "reconciled"
                revised.prompt_tokens = 50 if expected["prompt"] is not None else None
                revised.total_tokens = None
                session.get(Event, end.event_id)  # SQLite's single writer is the event lock.
                writer.write_or_queue_row(session, revised)
                session.commit()
                stored = session.exec(select(writer.UsageCallRow).where(writer.UsageCallRow.event_id == end.event_id,
                                                                       writer.UsageCallRow.revision == 1)).one()
                restated = feed.to_item(stored)
                assert restated["call_key"] == item["call_key"] and restated["revision"] == 1
                assert restated["observed_tokens"]["prompt"] == (50 if expected["prompt"] is not None else None)
                assert restated["occurred_at"] == item["occurred_at"]
    finally:
        engine.dispose()


# The SAME clean assertion is applied to a mutant. If it still passes, the guard
# has not earned its place. This is deterministic in-memory code, not a second test run.
MUTANTS = [
    ("bool", "type(value) is int and 0 <= value <= MAX_SAFE_INTEGER", "isinstance(value, int) and 0 <= value <= MAX_SAFE_INTEGER"),
    ("fraction", "type(value) is int and 0 <= value <= MAX_SAFE_INTEGER", "isinstance(value, (int, float)) and 0 <= value <= MAX_SAFE_INTEGER"),
    ("missing-count", "if value is None:\n        return None", "if value is None:\n        return 0"),
    ("negative", "0 <= value <= MAX_SAFE_INTEGER", "value <= MAX_SAFE_INTEGER"),
    ("unsafe", "0 <= value <= MAX_SAFE_INTEGER", "0 <= value"),
    ("label", "_LABEL.fullmatch(value)", "True"),
    ("path", "not _UNSAFE_LABEL.search(value)", "True"),
    ("link", "faults.add(\"call-unlinked\")", "pass"),
    ("deferred", "faults.discard(\"ordering-deferred\")", "pass"),
    ("unknown-fault", "faults.intersection_update(ROW_FAULT_CODES)", "pass"),
    ("fault-bound", "len(value) > 256", "False"),
    ("unended-marker", "event_type == \"llm.call.started\" and \"call-unended\" in faults", "event_type == \"llm.call.started\""),
    ("unended-start", "event_type == \"llm.call.started\" and \"call-unended\" in faults", "\"call-unended\" in faults"),
    ("unended-wire", "basis = \"call_start_unended\"", "pass"),
    ("overlap", "fresh < 0", "False"),
    ("provider", "elif provider == \"anthropic\":", "else:"),
    ("absent", "faults.add(\"usage-absent\")", "pass"),
    ("all-zero", "if all(type(raw[key]) is int and raw[key] == 0 for key in _COMPONENTS):", "if False:"),
    ("pi-zero", "tokens[key] == 0", "False"),
    ("pi-null", "faults.add(\"pi-count-unreported\")", "pass"),
    ("pi-total-components", "any(count is None for count in components)", "False"),
    ("pi-total-sum", "tokens[\"total\"] != sum(count for count in components if count is not None)", "False"),
    ("pi-convention", "faults.add(\"pi-convention-unverified\")", "pass"),
    ("cost-finite", "math.isfinite(value)", "True"),
    ("cost-negative", "value >= 0", "True"),
    ("revision", "not 0 <= revision <= MAX_SAFE_INTEGER", "False"),
    ("revision-bool", "type(revision) is not int", "not isinstance(revision, int)"),
    ("enum", "if not isinstance(value, str) or value not in allowed:", "if False:"),
    ("kind", "if kind is not None and (not isinstance(kind, str) or kind not in (\"model\", \"compaction\")):", "if False:"),
    ("cost-source", "if source is not None and (not isinstance(source, str) or source not in (\"pi_estimate\", \"service\")):", "if False:"),
    ("cost-type", "type(value) is float", "type(value) in (int, float)"),
    ("utc", "value.astimezone(UTC)", "value"),
    ("keys", "encoded = json.dumps(item,", "item[\"seq\"] = _get(row, \"seq\")\n    encoded = json.dumps(item,"),
    ("time", "_occurred_at(_get(row, \"occurred_at\"))", "_occurred_at(_get(row, \"event_at\"))"),
    ("bytes", "len(encoded.encode(\"ascii\")) > MAX_ITEM_BYTES", "False"),
    ("json", "allow_nan=False", "allow_nan=True"),
]


def guard_probe(name, namespace):
    fn = namespace["to_item"]
    if name in ("bool", "fraction", "missing-count", "negative", "unsafe"):
        value = {"bool": True, "fraction": 1.5, "missing-count": None, "negative": -1, "unsafe": 2**53}[name]
        assert fn(row(prompt_tokens=value))["observed_tokens"]["prompt"] is None
    elif name in ("label", "path"):
        assert fn(row(model="CANARY words" if name == "label" else "/CANARY"))["model"] is None
    elif name == "link":
        assert "call-unlinked" in fn(row(started_event_id=None))["faults"]
    elif name == "deferred":
        assert "ordering-deferred" not in fn(row(fault_codes="ordering-deferred"))["faults"]
    elif name == "unknown-fault":
        assert "CANARY" not in encoded(fn(row(fault_codes="CANARY")))
    elif name == "fault-bound":
        assert fn(row(fault_codes="," * 257))["faults"] == ["faults-invalid"]
    elif name in ("unended-marker", "unended-start", "unended-wire"):
        if name == "unended-marker":
            assert fn(row(event_type="llm.call.started", occurrence_basis="call_start", revision=1,
                          origin="reconciled"))["occurrence_basis"] == "call_start"
        elif name == "unended-start":
            assert fn(row(fault_codes="call-unended"))["occurrence_basis"] == "call_end"
        else:
            assert fn(row(event_type="llm.call.started", occurrence_basis="call_start",
                          fault_codes="call-unended"))["occurrence_basis"] == "call_start_unended"
    elif name == "overlap":
        assert fn(row(prompt_tokens=40))["exclusive_tokens"] is None
    elif name == "provider":
        assert fn(row(provider="openai"))["exclusive_tokens"] is None
    elif name == "absent":
        assert "usage-absent" in fn(row(**dict.fromkeys(NATIVE)))["faults"]
    elif name == "all-zero":
        item = fn(pi(**dict.fromkeys(NATIVE, 0)))
        assert item["observed_tokens"] == dict.fromkeys(OBSERVED)
        assert "usage-absent" in item["faults"] and "pi-zero-or-absent" not in item["faults"]
    elif name == "pi-zero":
        assert fn(pi(cache_write_tokens=0))["observed_tokens"]["cache_write"] is None
    elif name == "pi-null":
        assert "pi-count-unreported" in fn(pi(cache_write_tokens=None))["faults"]
    elif name == "pi-total-components":
        assert fn(pi(cache_write_tokens=None, total_tokens=140))["observed_tokens"]["total"] is None
    elif name == "pi-total-sum":
        assert fn(pi(total_tokens=161))["observed_tokens"]["total"] is None
    elif name == "pi-convention":
        assert "pi-convention-unverified" in fn(pi())["faults"]
    elif name in ("cost-finite", "cost-negative"):
        assert fn(row(legacy_cost_usd=float("inf") if name == "cost-finite" else -1.0))["legacy_cost"]["text"] is None
    elif name in ("revision", "revision-bool", "enum"):
        try:
            fn(row(origin="CANARY") if name == "enum" else row(revision=True if name == "revision-bool" else -1))
        except ValueError:
            return
        raise AssertionError("required-field guard did not refuse")
    elif name == "kind":
        assert fn(row(call_kind="CANARY"))["call_kind"] is None
    elif name == "cost-source":
        assert fn(row(legacy_cost_source="CANARY"))["legacy_cost"]["source"] is None
    elif name == "cost-type":
        assert fn(row(legacy_cost_usd=1))["legacy_cost"]["text"] is None
    elif name == "utc":
        shifted = AT.astimezone(timezone(timedelta(hours=5, minutes=30)))
        assert fn(row(occurred_at=shifted))["occurred_at"] == "2026-01-02T03:04:05.678Z"
    elif name == "keys":
        assert set(fn(row())) == KEYS
    elif name == "time":
        assert fn(row())["occurred_at"] == "2026-01-02T03:04:05.678Z"
    elif name == "bytes":
        namespace["MAX_ITEM_BYTES"] = 1
        try:
            fn(row())
        except ValueError:
            return
        raise AssertionError("byte guard did not refuse")
    elif name == "json":
        namespace["_legacy_cost"] = lambda *args: {"text": float("nan"), "source": None, "basis": "unproven"}
        try:
            fn(row())
        except ValueError:
            return
        raise AssertionError("JSON guard did not refuse")
    else:
        raise AssertionError("missing probe")


@pytest.mark.parametrize("name,old,new", MUTANTS, ids=[case[0] for case in MUTANTS])
def test_each_guard_bites_on_known_counterexample(name, old, new):
    source = inspect.getsource(feed)
    clean, mutant = {}, {}
    assert old in source
    exec(compile(source, feed.__file__, "exec"), clean)
    exec(compile(source.replace(old, new), feed.__file__, "exec"), mutant)
    guard_probe(name, clean)
    with pytest.raises(AssertionError):
        guard_probe(name, mutant)
