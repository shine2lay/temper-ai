"""D4 standalone synthetic stage tests; fixed answers, no API/model/workflow."""
import copy
import json
import os
import runpy
import stat
from datetime import timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

F = runpy.run_path(str(Path(__file__).parent / "fixtures/context_t1/compare_aggregate/synthetic.py"))
d3, d4, Corpus, write = F["d3"], F["d4"], F["Corpus"], F["write"]


@pytest.fixture
def corpus(tmp_path):
    return Corpus(tmp_path / "synthetic")


@pytest.fixture
def complete(corpus):
    return corpus.compared()


def test_six_accepted_terminal_records_complete_ledger(complete):
    result = complete.evaluate()
    assert result["status"]["result"] == "T1_ACCEPTED"
    assert not result["status"]["authorizes_later_stage"]
    assert result["coverage"]["accepted_attempts"] == 6
    assert result["coverage"]["accepted_families"] == 2
    assert result["coverage"]["lead_accepted"] == result["coverage"]["lead_denominator"] == 222
    assert result["totals"] == {"class_matches": 222, "applicable_bad_family_matches": 114, "nonbad_null_families": 108,
                                "false_support": 0, "known_bad_or_uncertain_cases": 168, "class_denominator": 222,
                                "bad_family_denominator": 114, "nonbad_null_denominator": 108, "known_bad_or_uncertain_denominator": 168}
    assert {name: item["matches"] for name, item in result["classes"].items()} == {
        "supported": 54, "contradicted": 60, "unsupported": 54, "uncertain": 54}
    assert result["cost"]["measured_usd"] == 7.5
    assert result["cost"]["ledger_complete"]
    for family in ("A", "B"):
        assert result["family_results"][family]["fresh_completed_accepted_attempts"] == 3
        assert len(result["repeatability"][family]["pairs"]) == 3
        for pair in result["repeatability"][family]["pairs"]:
            assert pair["available"] and pair["passed"]
            assert pair["class_matches"] == pair["family_or_null_matches"] == 37
            assert pair["applicable_family_matches"] == 19


def test_out_of_order_concurrent_completion_identical_result(complete):
    expected = complete.evaluate()
    order = ["B3", "A2", "B1", "A1", "B2", "A3"]
    for name in ("attempts", "comparisons", "reviews"):
        records = getattr(complete, name)
        setattr(complete, name, {slot: records[slot] for slot in order})
    complete.ledger["entries"].reverse()
    assert complete.evaluate() == expected
    complete.materialize(order)
    result = d4.aggregate(complete.root, binding_id=F["BINDING"], freeze_sha256=complete.freeze_pin, packet_sha256=complete.packet_pin)
    assert result == expected
    assert stat.S_IMODE((complete.root / "aggregate.json").stat().st_mode) == 0o600
    before = (complete.root / "aggregate.json").read_bytes()
    with pytest.raises(FileExistsError):
        d4.aggregate(complete.root, binding_id=F["BINDING"], freeze_sha256=complete.freeze_pin, packet_sha256=complete.packet_pin)
    assert (complete.root / "aggregate.json").read_bytes() == before


@pytest.mark.parametrize("kind", ["class", "family", "false_support"])
def test_one_bad_class_family_or_false_support_rejected(corpus, kind):
    def mutate(rows):
        if kind == "class":
            rows[0]["label"] = "uncertain"
        elif kind == "family":
            rows[9]["family"] = "F12"
        else:
            rows[9].update(label="supported", family=None)
    corpus.changed_answer("A1", mutate)
    result = corpus.compared().evaluate()
    assert result["status"]["result"] == "T1_REJECTED"
    assert result["coverage"]["accepted_attempts"] == 5
    assert not result["runs"][0]["accepted"]
    assert not result["family_results"]["A"]["accepted"]


@pytest.mark.parametrize("terminal", ["FAILED", "NOT_MEASURED"])
def test_one_bad_run_is_never_partial_success(complete, terminal):
    complete.attempts["B3"]["terminal"] = terminal
    result = complete.evaluate()
    assert result["status"]["result"] == "FAILED_OR_NOT_MEASURED"
    assert result["coverage"]["completed"] == 5
    assert result["coverage"]["accepted_attempts"] == 5
    assert result["totals"]["class_denominator"] == 222


@pytest.mark.parametrize("kind", ["class", "family"])
def test_one_repeat_disagreement_counts_actual_answers(corpus, kind):
    def mutate(rows):
        if kind == "class":
            rows[0]["label"] = "uncertain"
        else:
            rows[9]["family"] = "F12"
    corpus.changed_answer("A2", mutate)
    result = corpus.compared().evaluate()
    table = result["repeatability"]["A"]
    assert not table["passed"]
    assert sum(not pair["passed"] for pair in table["pairs"]) == 2
    assert any("repeat_disagreement" in item for item in result["status"]["semantic_rejections"])
    assert result["status"]["result"] == "T1_REJECTED"
    disagreeing = [pair for pair in table["pairs"] if "A2" in pair["slots"]]
    assert all(pair["class_matches"] == (36 if kind == "class" else 37) for pair in disagreeing)
    assert all(pair["family_or_null_matches"] == (37 if kind == "class" else 36) for pair in disagreeing)
    assert all(pair["applicable_family_matches"] == (19 if kind == "class" else 18) for pair in disagreeing)


def test_different_valid_spans_and_rationales_need_review_not_byte_identity(corpus):
    def mutate(rows):
        rows[0]["source_span"] = 'Alternative exact quote: "blue"'
        rows[0]["rationale"] = "Different independently accepted toy rationale."
    corpus.changed_answer("A2", mutate)
    result = corpus.compared().evaluate()
    assert result["status"]["result"] == "T1_ACCEPTED"
    assert result["repeatability"]["A"]["passed"]


@pytest.mark.parametrize("kind", ["partial", "missing"])
def test_partial_or_missing_review_retains_full_denominator(complete, kind):
    if kind == "partial":
        complete.reviews["A1"]["accepted_ids"].pop()
    else:
        del complete.reviews["A1"]
    result = complete.evaluate()
    assert result["status"]["result"] == "FAILED_OR_NOT_MEASURED"
    assert result["coverage"]["lead_accepted"] == (221 if kind == "partial" else 185)
    assert result["coverage"]["lead_denominator"] == 222
    assert result["coverage"]["accepted_attempts"] == 5


def test_lead_rejection_not_repaired_by_five_good_runs(complete):
    ident = complete.reviews["A1"]["accepted_ids"].pop()
    complete.reviews["A1"]["rejected_ids"].append(ident)
    result = complete.evaluate()
    assert result["status"]["result"] == "T1_REJECTED"
    assert result["coverage"]["lead_accepted"] == 221


def test_source_conflict_wins_without_key_repair(complete):
    before = copy.deepcopy(complete.comparisons)
    ident = complete.reviews["B2"]["accepted_ids"].pop()
    complete.reviews["B2"]["source_conflict_ids"].append(ident)
    complete.attempts["A1"]["cleanup"] = "UNCERTAIN"
    result = complete.evaluate()
    assert result["status"]["result"] == "SOURCE_CONFLICT"
    assert result["status"]["source_conflicts"] == ["B2:unjustifiable_frozen_expectation"]
    assert complete.comparisons == before


@pytest.mark.parametrize("field", ["cost_state", "usage_state"])
def test_unknown_cost_or_usage_never_zero_or_success(complete, field):
    complete.attempts["A1"][field] = "UNKNOWN"
    if field == "cost_state":
        complete.attempts["A1"]["list_price_usd"] = None
    complete.attempts["A1"]["unknown_exposure_usd"] = None
    complete.sync_ledger()
    result = complete.evaluate()
    assert result["status"]["result"] == "FAILED_OR_NOT_MEASURED"
    assert result["cost"]["measured_usd"] is None
    assert result["cost"]["known_measured_usd"] == (6.25 if field == "cost_state" else 7.5)
    assert result["cost"]["unknown_exposure_usd"] is None
    assert not result["cost"]["ledger_complete"]


@pytest.mark.parametrize("reason", ["transport", "auth", "quota", "timeout", "fallback", "cancel", "crash", "partial", "truncation", "retry"])
def test_failure_table_run_failures(complete, reason):
    complete.attempts["A1"]["failure_reasons"] = [reason]
    assert complete.evaluate()["status"]["result"] == "FAILED_OR_NOT_MEASURED"


@pytest.mark.parametrize("missing_downstream", [False, True])
def test_strict_parser_failure_is_rejection_not_inferred_success(complete, missing_downstream):
    complete.attempts["A1"]["failure_reasons"] = ["strict_parser"]
    if missing_downstream:
        del complete.comparisons["A1"]
        del complete.reviews["A1"]
    result = complete.evaluate()
    assert result["status"]["result"] == "T1_REJECTED"
    assert result["coverage"]["lead_denominator"] == 222


@pytest.mark.parametrize("mode", ["retry", "cancel", "slot_cap", "total_cap", "reservation", "fallback", "resume", "cleanup", "unknown_exposure"])
def test_retry_cancel_or_cap_exceedance_never_success(complete, mode):
    record = complete.attempts["A1"]
    if mode == "retry":
        record.update(transmissions=2, transmission_ids=["invented-call-A1", "invented-retry-A1"])
    elif mode == "cancel":
        record.update(terminal="FAILED", cleanup="UNCERTAIN", failure_reasons=["cancel"])
    elif mode == "slot_cap":
        record["list_price_usd"] = 5.01
    elif mode == "total_cap":
        for attempt in complete.attempts.values():
            attempt["list_price_usd"] = 5.01
    elif mode == "reservation":
        record["reservation_usd"] = 1
    elif mode in ("fallback", "resume"):
        record["fallback" if mode == "fallback" else "resumed"] = True
    elif mode == "cleanup":
        record["cleanup"] = "UNCERTAIN"
    else:
        record["unknown_exposure_usd"] = 2.5
    complete.sync_ledger()
    result = complete.evaluate()
    assert result["status"]["result"] == "FAILED_OR_NOT_MEASURED"
    if mode == "retry":
        assert result["cost"]["transmissions"] == 7
        assert "all:total_transmission_bound" in result["status"]["failure_reasons"]
    if mode == "total_cap":
        assert "all:total_cost_cap" in result["status"]["failure_reasons"]


def test_exact_money_and_900_second_boundaries_pass(complete):
    for record in complete.attempts.values():
        record.update(list_price_usd=5, cleanup_monotonic_s=record["dispatch_monotonic_s"] + 900,
                      cleanup_utc=(d4.utc(record["started_utc"]) + timedelta(seconds=900)).isoformat())
        # Serialize within each family at the exact cleanup boundary.
        offset = (int(record["slot"][1]) - 1) * 1000
        record.update(dispatch_monotonic_s=1000 + offset, deadline_monotonic_s=1900 + offset, cleanup_monotonic_s=1900 + offset)
        base = d4.utc("2026-01-01T00:00:00Z") + timedelta(seconds=offset)
        record.update(started_utc=base.isoformat(), ended_utc=(base + timedelta(seconds=900)).isoformat(), cleanup_utc=(base + timedelta(seconds=900)).isoformat())
    complete.sync_ledger()
    result = complete.evaluate()
    assert result["status"]["result"] == "T1_ACCEPTED"
    assert result["cost"]["measured_usd"] == 30


@pytest.mark.parametrize("mode", ["monotonic", "utc", "deadline", "clock", "backwards"])
def test_deadline_or_clock_evidence_failure(complete, mode):
    record = complete.attempts["A1"]
    if mode == "monotonic":
        record["cleanup_monotonic_s"] = record["dispatch_monotonic_s"] + 901
    elif mode == "utc":
        record["cleanup_utc"] = (d4.utc(record["started_utc"]) + timedelta(seconds=901)).isoformat()
    elif mode == "deadline":
        record["deadline_monotonic_s"] += 1
    elif mode == "clock":
        record["cleanup_monotonic_s"] += 0.1
    else:
        record["ended_utc"] = "2025-12-31T23:59:00Z"
    assert complete.evaluate()["status"]["result"] == "FAILED_OR_NOT_MEASURED"


@pytest.mark.parametrize("field", [*d4.IDENTITY_FIELDS, *d4.DIGEST_FIELDS, *d4.TIME_FIELDS, *d4.MONOTONIC_FIELDS])
def test_missing_identity_digest_or_time_is_not_reconstructed(complete, field):
    complete.attempts["A1"][field] = None
    if field == "raw_sha256":
        del complete.comparisons["A1"]
        del complete.reviews["A1"]
        complete.sync_ledger()
    result = complete.evaluate()
    assert result["status"]["result"] == "FAILED_OR_NOT_MEASURED"
    assert "A1:missing_identity_time_or_digest" in result["status"]["failure_reasons"]


@pytest.mark.parametrize("field", ["session_id", "run_id"])
def test_reused_session_or_run_refused(complete, field):
    complete.attempts["B3"][field] = complete.attempts["A1"][field]
    with pytest.raises(d3.Refusal, match=f"reused_{field}"):
        complete.evaluate()


def test_reused_slot_is_refused_on_disk(complete):
    complete.materialize()
    write(complete.root, "A2.attempt.json", complete.attempts["A1"])
    with pytest.raises(d3.Refusal, match="reused_slot"):
        d4.aggregate(complete.root, binding_id=F["BINDING"], freeze_sha256=complete.freeze_pin, packet_sha256=complete.packet_pin)
    assert not (complete.root / "aggregate.json").exists()


def test_reused_transmission_refused(complete):
    complete.attempts["A2"]["transmission_ids"] = complete.attempts["A1"]["transmission_ids"][:]
    with pytest.raises(d3.Refusal, match="reused_transmission"):
        complete.evaluate()


def test_one_bad_run_not_pooled_even_if_all_answers_repeat(complete):
    complete.attempts["B3"]["terminal"] = "NOT_MEASURED"
    result = complete.evaluate()
    assert all(item["passed"] for item in result["repeatability"].values())
    assert result["totals"]["class_matches"] == 222
    assert result["status"]["result"] != "T1_ACCEPTED"


def test_pooled_average_cannot_hide_per_case_errors(corpus):
    def mutate(rows):
        for name in ("label", "family"):
            rows[0][name], rows[9][name] = rows[9][name], rows[0][name]
    for slot in F["SLOTS"]:
        corpus.changed_answer(slot, mutate)
    result = corpus.evaluate()
    assert all(item["passed"] for item in result["repeatability"].values())
    assert result["status"]["result"] == "T1_REJECTED"
    assert result["coverage"]["accepted_attempts"] == 0
    assert result["totals"]["class_matches"] == 210
    assert result["totals"]["class_denominator"] == 222


def test_forged_pooled_counts_refused(complete):
    comparison = complete.comparisons["A1"]
    row = comparison["per_case"][0]
    row["actual_label"] = "uncertain"
    row.update(d3.case_flags(row))
    with pytest.raises(d3.Refusal, match="comparison_counts"):
        complete.evaluate()


@pytest.mark.parametrize("missing", ["attempt", "comparison", "review", "ledger"])
def test_missing_evidence_stays_missing_on_disk(complete, missing):
    complete.materialize()
    relative = "ledger.json" if missing == "ledger" else f"B3.{'lead-review' if missing == 'review' else missing}.json"
    (complete.root / relative).unlink()
    if missing == "attempt":
        (complete.root / "B3.comparison.json").unlink()
        (complete.root / "B3.lead-review.json").unlink()
        complete.ledger["entries"] = [entry for entry in complete.ledger["entries"] if entry["slot"] != "B3"]
        write(complete.root, "ledger.json", complete.ledger)
    result = d4.aggregate(complete.root, binding_id=F["BINDING"], freeze_sha256=complete.freeze_pin, packet_sha256=complete.packet_pin)
    assert result["status"]["result"] == "FAILED_OR_NOT_MEASURED"
    assert result["totals"]["class_denominator"] == 222
    if missing in ("attempt", "comparison"):
        assert result["totals"]["class_matches"] == 185
        pair = result["repeatability"]["B"]["pairs"][-1]
        assert not pair["available"] and pair["class_matches"] is None and not pair["passed"]


@pytest.mark.parametrize("field", ["raw_sha256", "packet_sha256", "freeze_sha256", "key_sha256"])
def test_comparison_hash_disagreement_refused(complete, field):
    complete.comparisons["A2"][field] = "0" * 64
    with pytest.raises(d3.Refusal, match="binding"):
        complete.evaluate()


@pytest.mark.parametrize("field", ["binding_id", "experiment_id", "source_sha256", "input_sha256", "packet_sha256"])
def test_attempt_binding_drift_refused(complete, field):
    complete.attempts["B3"][field] = "different" if field.endswith("id") else "0" * 64
    with pytest.raises(d3.Refusal, match="binding"):
        complete.evaluate()


@pytest.mark.parametrize("field", ["route", "provider", "model", "auth_mode", "config_sha256", "pricing_sha256"])
def test_family_route_metadata_drift_fails(complete, field):
    complete.attempts["A3"][field] = "different" if not field.endswith("sha256") else "0" * 64
    assert complete.evaluate()["status"]["result"] == "FAILED_OR_NOT_MEASURED"


def test_same_provider_family_fails(complete):
    for slot in ("B1", "B2", "B3"):
        complete.attempts[slot]["provider"] = complete.attempts["A1"]["provider"]
    assert complete.evaluate()["status"]["result"] == "FAILED_OR_NOT_MEASURED"


def test_recorded_same_family_overlap_fails(complete):
    for field in (*d4.TIME_FIELDS, *d4.MONOTONIC_FIELDS):
        complete.attempts["A2"][field] = complete.attempts["A1"][field]
    result = complete.evaluate()
    assert result["status"]["result"] == "FAILED_OR_NOT_MEASURED"
    assert "all:concurrency_bound" in result["status"]["failure_reasons"]


@pytest.mark.parametrize("kind", ["overlap", "unknown_id", "hash"])
def test_invalid_lead_receipt_refused(complete, kind):
    review = complete.reviews["B3"]
    if kind == "overlap":
        review["rejected_ids"].append(review["accepted_ids"][0])
    elif kind == "unknown_id":
        review["accepted_ids"][0] = "invented-unknown"
    else:
        review["raw_sha256"] = "0" * 64
    with pytest.raises(d3.Refusal):
        complete.evaluate()


@pytest.mark.parametrize("kind", ["entry", "total", "missing", "duplicate", "reserved", "exposure", "incomplete", "unknown_total"])
def test_ledger_must_reconcile_not_just_claim_complete(complete, kind):
    if kind == "entry":
        complete.ledger["entries"][0]["list_price_usd"] = 0
    elif kind == "total":
        complete.ledger["measured_usd"] = 0
    elif kind == "missing":
        complete.ledger["entries"].pop()
    elif kind == "duplicate":
        complete.ledger["entries"].append(complete.ledger["entries"][0])
    elif kind == "reserved":
        complete.ledger["reserved_usd"] = 1
    elif kind == "exposure":
        complete.ledger["unknown_exposure_usd"] = 2
    elif kind == "incomplete":
        complete.ledger["state"] = "INCOMPLETE"
    else:
        complete.ledger["measured_usd"] = None
    if kind in ("entry", "duplicate"):
        with pytest.raises(d3.Refusal):
            complete.evaluate()
    else:
        assert complete.evaluate()["status"]["result"] == "FAILED_OR_NOT_MEASURED"


@pytest.mark.parametrize("field,value", [("transmissions", True), ("list_price_usd", True), ("deadline_s", 901),
                                         ("cost_state", "UNKNOWN"), ("session_id", "not-uuid"), ("terminal", "OK"),
                                         ("failure_reasons", ["not-known"]), ("started_utc", "2026-01-01T01:00:00+01:00")])
def test_attempt_contract_wrong_types_or_states_refused(complete, field, value):
    complete.attempts["A1"][field] = value
    with pytest.raises(d3.Refusal):
        complete.evaluate()


@pytest.mark.parametrize("unsafe", ["symlink", "hardlink", "mode", "fifo", "oversize", "bad_json"])
def test_aggregate_input_envelope_refused(complete, unsafe):
    complete.materialize()
    path = complete.root / "ledger.json"
    if unsafe == "symlink":
        path.unlink()
        path.symlink_to(complete.root / "A1.attempt.json")
    elif unsafe == "hardlink":
        os.link(path, complete.root / "linked-ledger")
    elif unsafe == "mode":
        path.chmod(0o644)
    elif unsafe == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    else:
        write(complete.root, "ledger.json", b"x" * 2_000_001 if unsafe == "oversize" else b'{"x": NaN}')
    with pytest.raises((d3.Refusal, OSError)):
        d4.aggregate(complete.root, binding_id=F["BINDING"], freeze_sha256=complete.freeze_pin, packet_sha256=complete.packet_pin)
    assert not (complete.root / "aggregate.json").exists()


def test_all_four_schemas_and_complete_records_validate(complete):
    instances = {"comparison": complete.comparisons["A1"], "attempt": complete.attempts["A1"],
                 "lead_review": complete.reviews["A1"], "aggregate": complete.evaluate()}
    for name, instance in instances.items():
        schema = json.loads((F["SCHEMAS"] / f"{name}.v1.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(instance)
        assert set(schema["required"]) == set(instance)
    assert set(instances["attempt"]) == d4.ATTEMPT_FIELDS


def test_empty_evidence_is_not_measured_with_fixed_denominators(corpus):
    corpus.attempts, corpus.comparisons, corpus.reviews, corpus.ledger = {}, {}, {}, None
    result = corpus.evaluate()
    assert result["status"]["result"] == "FAILED_OR_NOT_MEASURED"
    assert result["coverage"]["missing_attempts"] == list(F["SLOTS"])
    assert result["totals"]["class_matches"] == 0 and result["totals"]["class_denominator"] == 222
    assert result["cost"]["measured_usd"] is None
    schema = json.loads((F["SCHEMAS"] / "aggregate.v1.schema.json").read_text())
    Draft202012Validator(schema).validate(result)


def test_decimal_cost_ledger_reconciles_without_binary_sum_error(complete):
    for record in complete.attempts.values():
        record["list_price_usd"] = 0.1
    complete.sync_ledger()
    result = complete.evaluate()
    assert result["status"]["result"] == "T1_ACCEPTED"
    assert result["cost"]["measured_usd"] == 0.6


def test_aggregate_cli_status_only_and_exclusive(complete, capsys):
    complete.materialize()
    argv = ["--root", str(complete.root), "--binding-id", F["BINDING"], "--freeze-sha256", complete.freeze_pin,
            "--packet-sha256", complete.packet_pin]
    assert d4.main(argv) == 0
    assert json.loads(capsys.readouterr().out) == {"result": "T1_ACCEPTED", "authorizes_later_stage": False}
    assert d4.main(argv) == 2
    assert json.loads(capsys.readouterr().out) == {"result": "REFUSED", "authorizes_later_stage": False}
