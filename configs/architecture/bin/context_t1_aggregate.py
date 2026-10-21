#!/usr/bin/env python3
"""D4: deterministic six-slot T1 aggregation; no dispatch, route or model calls.

ATTEMPT-RECORD CONTRACT (future J writer; attempt.v1.schema.json is normative):
Write exactly one <slot>.attempt.json, exclusively, 0600 in a 0700 private root.
Never overwrite, resume, replace a slot, conceal a retry or substitute a route.
A1/A2/A3 belong to A; B1/B2/B3 to B. Each has fresh UUID session_id AND run_id.
experiment_id and binding_id identify the admitted experiment/source binding;
route/provider/model/auth_mode, source/config/pricing/input/packet SHA256s,
raw_sha256, all transmission_ids and transmissions preserve actual provenance.
resumed/fallback are explicit booleans. terminal is COMPLETED/FAILED/NOT_MEASURED;
failure_reasons preserve parser/transport/auth/quota/timeout/fallback/cancel/
crash/partial/truncation/retry, never reinterpret a failure as an accepted slot.
usage_state and cost_state are KNOWN/UNKNOWN; list_price_usd is a finite
nonnegative number iff cost_state=KNOWN, otherwise null (never a zero fill).
reservation_usd preserves the pre-dispatch worst-case bound, not measured spend;
unknown_exposure_usd is separate and nullable. cleanup is CONFIRMED/UNCERTAIN.
started_utc, ended_utc, cleanup_utc are timezone-aware UTC; dispatch_monotonic_s,
deadline_monotonic_s, cleanup_monotonic_s share the experiment clock; deadline_s
is exactly 900. Null identity/time/raw metadata is retained as missing, NEVER
reconstructed. Monotonic times prove durations; UTC is independently checked.
These records are attestations, NOT proof of runtime enforcement or isolation.

Lead receipt: <slot>.lead-review.json, raw hash plus accepted_ids/rejected_ids/
source_conflict_ids, mutually disjoint subsets of the 37 comparison IDs. Omitted
IDs stay unreviewed; SOURCE_CONFLICT means stop/preserve, not key repair.
Ledger: ledger.json, context-t1-ledger/v1, experiment_id/binding_id, cost_basis
LIST_PRICE, state COMPLETE/INCOMPLETE, measured_usd/reserved_usd/
unknown_exposure_usd, and one entry per attempted slot with raw hash, actual
usage/cost states, price and complete transmission inventory. No unknown=0.
D4 reconciles each entry and total against attempts using decimal arithmetic.

CLI requires --root, --binding-id, --freeze-sha256, --packet-sha256. These are
independent caller pins, never inferred by voting. Reads the six fixed slot
names (missing records remain missing), ledger, comparisons and lead receipts.
Writes aggregate.json exclusively, 0600. Exit 0 only for T1_ACCEPTED, 1 for other
measured dispositions, 2 for refused malformed/unbound/reused evidence. Status
precedence: SOURCE_CONFLICT > FAILED_OR_NOT_MEASURED > T1_REJECTED > T1_ACCEPTED.
A valid mismatch is a result, not a parser refusal. Fixed denominators: 6 runs,
2 families, 222 classes/reviews, 114 bad families, 108 nonbad nulls, 168 known
bad/uncertain opportunities. Three exact unordered pairs per family, each
37 class AND 37 family-or-null observations (19 applicable bad families).
No pooling, majority repair, partial success or later-stage authorization.
"""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import combinations
from pathlib import Path

import context_t1_compare as d3

ATTEMPT_FIELDS = {
    "schema", "slot", "family", "experiment_id", "binding_id", "session_id", "run_id", "route", "provider", "model", "auth_mode",
    "source_sha256", "config_sha256", "pricing_sha256", "input_sha256", "packet_sha256", "raw_sha256",
    "terminal", "transmissions", "transmission_ids", "usage_state", "list_price_usd", "cost_state",
    "reservation_usd", "unknown_exposure_usd", "cleanup", "started_utc", "ended_utc", "cleanup_utc",
    "dispatch_monotonic_s", "deadline_monotonic_s", "cleanup_monotonic_s", "deadline_s", "resumed", "fallback", "failure_reasons",
}
DIGEST_FIELDS = ("source_sha256", "config_sha256", "pricing_sha256", "input_sha256", "packet_sha256", "raw_sha256")
IDENTITY_FIELDS = ("experiment_id", "binding_id", "session_id", "run_id", "route", "provider", "model", "auth_mode")
TIME_FIELDS = ("started_utc", "ended_utc", "cleanup_utc")
MONOTONIC_FIELDS = ("dispatch_monotonic_s", "deadline_monotonic_s", "cleanup_monotonic_s")
FAILURES = {"strict_parser", "transport", "auth", "quota", "timeout", "fallback", "cancel", "crash", "partial", "truncation", "retry"}
ENTRY_FIELDS = {"slot", "raw_sha256", "list_price_usd", "cost_state", "usage_state", "transmissions", "transmission_ids"}
LEDGER_FIELDS = {"schema", "experiment_id", "binding_id", "cost_basis", "state", "measured_usd", "reserved_usd", "unknown_exposure_usd", "entries"}
REVIEW_FIELDS = {"schema", "slot", "raw_sha256", "accepted_ids", "rejected_ids", "source_conflict_ids"}


def money(value):
    return Decimal(str(value))


def json_amount(value):
    # Even a failed ledger can contain huge finite amounts; never emit Infinity.
    return int(value) if value == value.to_integral_value() else float(value)


def utc(value):
    d3.require(d3.text(value), "utc")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise d3.Refusal("utc") from None
    d3.require("T" in value and result.tzinfo is not None and result.utcoffset() == timedelta(0), "utc")
    return result


def uuid_or_missing(value):
    if value is None:
        return
    d3.require(d3.text(value), "uuid")
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise d3.Refusal("uuid") from None
    d3.require(str(parsed) == value and parsed.int != 0, "uuid")


def attempt_shape(record):
    d3.fields(record, ATTEMPT_FIELDS)
    d3.require(record["schema"] == "context-t1-attempt/v1" and record["slot"] in d3.SLOTS
               and record["family"] == record["slot"][0], "attempt_schema")
    for name in IDENTITY_FIELDS:
        d3.require(record[name] is None or d3.text(record[name]), "identity_type")
    for name in ("session_id", "run_id"):
        uuid_or_missing(record[name])
    for name in DIGEST_FIELDS:
        d3.require(record[name] is None or d3.is_digest(record[name]), "digest_type")
    for name in TIME_FIELDS:
        if record[name] is not None:
            utc(record[name])
    for name in (*MONOTONIC_FIELDS, "reservation_usd", "unknown_exposure_usd"):
        d3.require(record[name] is None or d3.number(record[name]), "numeric_type")
    d3.require(type(record["deadline_s"]) is int and record["deadline_s"] == 900, "deadline_contract")
    d3.require(record["terminal"] in ("COMPLETED", "FAILED", "NOT_MEASURED")
               and record["cleanup"] in ("CONFIRMED", "UNCERTAIN"), "terminal_contract")
    for name in ("cost_state", "usage_state"):
        d3.require(record[name] in ("KNOWN", "UNKNOWN"), "cost_state")
    d3.require((record["cost_state"] == "KNOWN" and d3.number(record["list_price_usd"]))
               or (record["cost_state"] == "UNKNOWN" and record["list_price_usd"] is None), "cost_value")
    d3.require(type(record["transmissions"]) is int and record["transmissions"] >= 0, "transmissions")
    ids = record["transmission_ids"]
    d3.require(type(ids) is list and all(d3.text(ident) for ident in ids) and len(ids) == len(set(ids))
               and len(ids) == record["transmissions"], "transmission_inventory")
    d3.require(type(record["resumed"]) is bool and type(record["fallback"]) is bool, "attempt_flags")
    reasons = record["failure_reasons"]
    d3.require(type(reasons) is list and all(type(reason) is str and reason in FAILURES for reason in reasons)
               and len(reasons) == len(set(reasons)), "failure_reasons")


def read_slots(store, suffix, check):
    records = {}
    for slot in d3.SLOTS:
        try:
            record = store.load(f"{slot}.{suffix}.json")
        except FileNotFoundError:
            continue
        check(record)
        # A renamed duplicate is a reuse, never an apparent missing slot.
        d3.require(record["slot"] == slot and record["slot"] not in records, "reused_slot")
        records[slot] = record
    return records


def review_shape(record):
    d3.fields(record, REVIEW_FIELDS)
    d3.require(record["schema"] == "context-t1-lead-review/v1" and record["slot"] in d3.SLOTS
               and d3.is_digest(record["raw_sha256"]), "review_schema")
    seen = set()
    for name in ("accepted_ids", "rejected_ids", "source_conflict_ids"):
        ids = record[name]
        d3.require(type(ids) is list and all(d3.text(ident) for ident in ids) and len(ids) == len(set(ids)), "review_ids")
        d3.require(not seen.intersection(ids), "review_overlap")
        seen.update(ids)


def ledger_shape(ledger):
    d3.fields(ledger, LEDGER_FIELDS)
    d3.require(ledger["schema"] == "context-t1-ledger/v1" and ledger["cost_basis"] == "LIST_PRICE"
               and ledger["state"] in ("COMPLETE", "INCOMPLETE"), "ledger_schema")
    for name in ("experiment_id", "binding_id"):
        d3.require(ledger[name] is None or d3.text(ledger[name]), "ledger_identity")
    for name in ("measured_usd", "reserved_usd", "unknown_exposure_usd"):
        d3.require(ledger[name] is None or d3.number(ledger[name]), "ledger_money")
    d3.require(type(ledger["entries"]) is list, "ledger_entries")
    seen = set()
    for entry in ledger["entries"]:
        d3.fields(entry, ENTRY_FIELDS)
        slot = entry["slot"]
        d3.require(type(slot) is str and slot in d3.SLOTS and slot not in seen, "reused_ledger_slot")
        seen.add(slot)
        d3.require(entry["raw_sha256"] is None or d3.is_digest(entry["raw_sha256"]), "ledger_digest")
        for name in ("cost_state", "usage_state"):
            d3.require(entry[name] in ("KNOWN", "UNKNOWN"), "ledger_cost_state")
        d3.require((entry["cost_state"] == "KNOWN" and d3.number(entry["list_price_usd"]))
                   or (entry["cost_state"] == "UNKNOWN" and entry["list_price_usd"] is None), "ledger_cost_value")
        ids = entry["transmission_ids"]
        d3.require(type(entry["transmissions"]) is int and entry["transmissions"] >= 0
                   and type(ids) is list and all(d3.text(ident) for ident in ids)
                   and len(ids) == len(set(ids)) == entry["transmissions"], "ledger_transmissions")


def evaluate(attempts, comparisons, reviews, ledger, *, binding_id, freeze_sha256, packet_sha256):
    """Pure aggregation. All collections retain their slot identities."""
    d3.require(d3.text(binding_id) and d3.is_digest(freeze_sha256) and d3.is_digest(packet_sha256), "aggregate_pins")
    for slot, record in attempts.items():
        attempt_shape(record)
        d3.require(slot == record["slot"], "reused_slot")
    cases = {}
    for slot, record in comparisons.items():
        cases[slot] = d3.checked_comparison(record)
        d3.require(slot == record["slot"] and record["freeze_sha256"] == freeze_sha256
                   and record["packet_sha256"] == packet_sha256, "comparison_binding")
    for slot, record in reviews.items():
        review_shape(record)
        d3.require(slot == record["slot"], "reused_slot")
    if ledger is not None:
        ledger_shape(ledger)

    # No first result is silently replaced by another slot/session/run/call.
    for name in ("session_id", "run_id"):
        ids = [record[name] for record in attempts.values() if record[name] is not None]
        d3.require(len(ids) == len(set(ids)), f"reused_{name}")
    transmission_ids = [ident for record in attempts.values() for ident in record["transmission_ids"]]
    d3.require(len(transmission_ids) == len(set(transmission_ids)), "reused_transmission")
    d3.require(set(comparisons) <= set(attempts) and set(reviews) <= set(attempts), "orphan_evidence")
    canonical = None
    key_digest = None
    for slot, comparison in comparisons.items():
        d3.require(comparison["raw_sha256"] == attempts[slot]["raw_sha256"], "raw_binding")
        inventory = {ident: (row["path"], row["expected_label"], row["expected_family"]) for ident, row in cases[slot].items()}
        if canonical is None:
            canonical, key_digest = inventory, comparison["key_sha256"]
        d3.require(inventory == canonical and comparison["key_sha256"] == key_digest, "key_inventory_binding")
    for slot, review in reviews.items():
        d3.require(review["raw_sha256"] == attempts[slot]["raw_sha256"], "review_raw_binding")
        reviewed = set(review["accepted_ids"] + review["rejected_ids"] + review["source_conflict_ids"])
        if canonical is not None:
            d3.require(reviewed <= set(canonical), "review_unknown_id")

    reasons, semantic, conflicts = [], [], []
    per_run_reasons = {slot: [] for slot in d3.SLOTS}

    def failed(slot, reason):
        reasons.append(f"{slot}:{reason}")
        if slot in per_run_reasons:
            per_run_reasons[slot].append(reason)
        elif slot in ("A", "B"):
            for member in d3.SLOTS:
                if member.startswith(slot):
                    per_run_reasons[member].append(reason)

    experiment_ids = {a["experiment_id"] for a in attempts.values() if a["experiment_id"] is not None}
    d3.require(len(experiment_ids) <= 1, "experiment_binding")
    experiment_id = next(iter(experiment_ids), None)
    # Source/input/packet bindings must be identical; config/pricing/route metadata
    # are identical within each family, never guessed from model-name defaults.
    for name in ("source_sha256", "input_sha256", "packet_sha256"):
        values = {a[name] for a in attempts.values() if a[name] is not None}
        d3.require(len(values) <= 1, "source_binding")
    for family in ("A", "B"):
        for name in ("route", "provider", "model", "auth_mode", "config_sha256", "pricing_sha256"):
            values = {a[name] for a in attempts.values() if a["family"] == family and a[name] is not None}
            if len(values) > 1:
                failed(family, f"route_drift:{name}")
    providers = [{a["provider"] for a in attempts.values() if a["family"] == family and a["provider"] is not None}
                 for family in ("A", "B")]
    if providers[0].intersection(providers[1]):
        failed("all", "same_provider_family")

    intervals = []
    for slot in d3.SLOTS:
        if slot not in attempts:
            failed(slot, "missing_attempt")
            continue
        record = attempts[slot]
        if record["binding_id"] is not None:
            d3.require(record["binding_id"] == binding_id, "attempt_binding")
        if record["packet_sha256"] is not None:
            d3.require(record["packet_sha256"] == packet_sha256, "packet_binding")
        if any(record[name] is None for name in (*IDENTITY_FIELDS, *DIGEST_FIELDS, *TIME_FIELDS, *MONOTONIC_FIELDS)):
            failed(slot, "missing_identity_time_or_digest")
        if record["terminal"] != "COMPLETED":
            failed(slot, "terminal_not_completed")
        if record["resumed"] or record["fallback"]:
            failed(slot, "resume_or_fallback")
        if record["failure_reasons"]:
            if "strict_parser" in record["failure_reasons"]:
                semantic.append(f"{slot}:strict_parser")
            if set(record["failure_reasons"]) - {"strict_parser"}:
                failed(slot, "run_failure")
        if record["transmissions"] != 1:
            failed(slot, "transmission_bound")
        if record["cost_state"] != "KNOWN" or record["usage_state"] != "KNOWN":
            failed(slot, "unknown_cost_or_usage")
        if record["list_price_usd"] is not None and money(record["list_price_usd"]) > 5:
            failed(slot, "attempt_cost_cap")
        reservation = record["reservation_usd"]
        if reservation is None or not 0 < reservation <= 5:
            failed(slot, "reservation_bound")
        elif record["list_price_usd"] is not None and money(record["list_price_usd"]) > money(reservation):
            failed(slot, "unreserved_spend")
        if record["unknown_exposure_usd"] is None or record["unknown_exposure_usd"] != 0:
            failed(slot, "unknown_exposure")
        if record["cleanup"] != "CONFIRMED":
            failed(slot, "cleanup_uncertain")
        if all(record[name] is not None for name in MONOTONIC_FIELDS):
            start, deadline, cleanup = (money(record[name]) for name in MONOTONIC_FIELDS)
            if deadline - start != 900 or not start <= cleanup <= deadline:
                failed(slot, "monotonic_deadline")
            else:
                intervals.append((start, cleanup, record["family"]))
        if all(record[name] is not None for name in TIME_FIELDS):
            start_utc, end_utc, cleanup_utc = (utc(record[name]) for name in TIME_FIELDS)
            if not start_utc <= end_utc <= cleanup_utc <= start_utc + timedelta(seconds=900):
                failed(slot, "utc_deadline")
            if record["dispatch_monotonic_s"] is not None and record["cleanup_monotonic_s"] is not None:
                if Decimal(str((cleanup_utc - start_utc).total_seconds())) != money(record["cleanup_monotonic_s"]) - money(record["dispatch_monotonic_s"]):
                    failed(slot, "clock_disagreement")
        parser_failed = "strict_parser" in record["failure_reasons"]
        if slot not in comparisons:
            if not parser_failed:
                failed(slot, "missing_comparison")
        elif comparisons[slot]["verdict"] != "PASS":
            semantic.append(f"{slot}:class_or_family_error")
        if slot not in reviews:
            if not parser_failed:
                failed(slot, "missing_review")
        else:
            review = reviews[slot]
            if review["source_conflict_ids"]:
                conflicts.append(f"{slot}:unjustifiable_frozen_expectation")
            if review["rejected_ids"]:
                semantic.append(f"{slot}:lead_evidence_rejection")
            if len(review["accepted_ids"]) + len(review["rejected_ids"]) + len(review["source_conflict_ids"]) != 37:
                failed(slot, "incomplete_review")

    transmissions = sum(a["transmissions"] for a in attempts.values())
    if transmissions > 6:
        failed("all", "total_transmission_bound")
    # Check recorded overlap without scheduler/model inference. A zero-duration
    # attempt cannot occupy two time instants but still needs all other proof.
    for moment in sorted({start for start, end, _ in intervals if start < end}):
        active = [family for start, end, family in intervals if start <= moment < end]
        if len(active) > 2 or any(active.count(family) > 1 for family in ("A", "B")):
            failed("all", "concurrency_bound")
            break

    measured_known = sum((money(a["list_price_usd"]) for a in attempts.values() if a["list_price_usd"] is not None), Decimal(0))
    fully_known = len(attempts) == 6 and all(a["cost_state"] == a["usage_state"] == "KNOWN" for a in attempts.values())
    measured = measured_known if fully_known else None
    if measured_known > 30:
        failed("all", "total_cost_cap")
    ledger_complete = False
    if ledger is None:
        failed("all", "missing_ledger")
    else:
        if ledger["binding_id"] is not None:
            d3.require(ledger["binding_id"] == binding_id, "ledger_binding")
        if ledger["experiment_id"] is not None:
            d3.require(ledger["experiment_id"] == experiment_id, "ledger_experiment")
        entries = {entry["slot"]: entry for entry in ledger["entries"]}
        d3.require(set(entries) <= set(attempts), "orphan_ledger_entry")
        for slot, entry in entries.items():
            actual = {name: attempts[slot][name] for name in ENTRY_FIELDS}
            d3.require(entry == actual, "ledger_entry_disagreement")
        if (ledger["measured_usd"] is not None and fully_known
                and money(ledger["measured_usd"]) != measured_known):
            failed("all", "ledger_total_disagreement")
        if not fully_known and ledger["measured_usd"] is not None:
            failed("all", "unknown_ledger_total")
        ledger_complete = (ledger["state"] == "COMPLETE" and len(entries) == 6 and fully_known
                           and ledger["measured_usd"] is not None and money(ledger["measured_usd"]) == measured_known
                           and ledger["reserved_usd"] == 0 and ledger["unknown_exposure_usd"] == 0
                           and ledger["experiment_id"] is not None and ledger["binding_id"] is not None)
        if not ledger_complete:
            failed("all", "ledger_incomplete_or_unreconciled")
        if ledger["measured_usd"] is not None and money(ledger["measured_usd"]) > 30:
            failed("all", "ledger_cost_cap")

    repeatability = {}
    for family in ("A", "B"):
        slots = [slot for slot in d3.SLOTS if slot[0] == family]
        pairs = []
        for left, right in combinations(slots, 2):
            available = left in cases and right in cases
            class_matches = family_matches = applicable_matches = None
            if available:
                class_matches = sum(row["actual_label"] == cases[right][ident]["actual_label"] for ident, row in cases[left].items())
                family_matches = sum(row["actual_family"] == cases[right][ident]["actual_family"] for ident, row in cases[left].items())
                applicable_matches = sum(row["actual_family"] == cases[right][ident]["actual_family"] for ident, row in cases[left].items()
                                         if row["expected_label"] in d3.BAD)
            passed = available and class_matches == family_matches == 37 and applicable_matches == 19
            pairs.append({"slots": [left, right], "available": available, "class_matches": class_matches,
                          "class_denominator": 37, "family_or_null_matches": family_matches, "family_or_null_denominator": 37,
                          "applicable_family_matches": applicable_matches, "applicable_family_denominator": 19, "passed": passed})
            if available and not passed:
                semantic.append(f"{left}:{right}:repeat_disagreement")
        repeatability[family] = {"pairs": pairs, "pairs_required": 3, "passed": all(pair["passed"] for pair in pairs)}

    runs = []
    for slot in d3.SLOTS:
        accepted = (slot in attempts and not per_run_reasons[slot] and slot in comparisons and comparisons[slot]["verdict"] == "PASS"
                    and slot in reviews and len(reviews[slot]["accepted_ids"]) == 37 and not attempts[slot]["failure_reasons"])
        runs.append({"slot": slot, "family": slot[0], "terminal": attempts[slot]["terminal"] if slot in attempts else None,
                     "comparison": comparisons[slot]["verdict"] if slot in comparisons else None,
                     "lead_accepted": len(reviews[slot]["accepted_ids"]) if slot in reviews else None,
                     "accepted": accepted, "failure_reasons": per_run_reasons[slot]})
    family_table = {family: {"fresh_completed_accepted_attempts": sum(run["accepted"] for run in runs if run["family"] == family),
                             "required": 3, "repeatability_passed": repeatability[family]["passed"]}
                    for family in ("A", "B")}
    for item in family_table.values():
        item["accepted"] = item["fresh_completed_accepted_attempts"] == 3 and item["repeatability_passed"]
    class_table = {label: {"matches": sum(c["classes"][label]["matches"] for c in comparisons.values()),
                           "required": total * 6, "denominator": total * 6} for label, total in d3.CLASS_TOTALS.items()}
    family_counts = {family: {"matches": sum(c["families"][family]["matches"] for c in comparisons.values()),
                              "required": total * 6, "denominator": total * 6} for family, total in d3.FAMILY_TOTALS.items()}
    counts = {name: sum(c[name] for c in comparisons.values()) for name in
              ("class_matches", "applicable_bad_family_matches", "nonbad_null_families", "false_support", "known_bad_or_uncertain_cases")}
    lead_accepted = sum(len(review["accepted_ids"]) for review in reviews.values())
    all_bars = (len(attempts) == len(comparisons) == len(reviews) == 6 and all(run["accepted"] for run in runs)
                and all(item["accepted"] for item in family_table.values()) and counts["class_matches"] == 222
                and counts["applicable_bad_family_matches"] == 114 and counts["nonbad_null_families"] == 108
                and counts["false_support"] == 0 and counts["known_bad_or_uncertain_cases"] == 168
                and lead_accepted == 222 and all(item["matches"] == item["required"] for item in (*class_table.values(), *family_counts.values()))
                and ledger_complete)
    if conflicts:
        result = "SOURCE_CONFLICT"
    elif reasons:
        result = "FAILED_OR_NOT_MEASURED"
    elif semantic or not all_bars:
        result = "T1_REJECTED"
    else:
        result = "T1_ACCEPTED"
    return {
        "schema": "context-t1-aggregate/v1", "binding_id": binding_id,
        "freeze_sha256": freeze_sha256, "packet_sha256": packet_sha256,
        "coverage": {"attempts": len(attempts), "comparisons": len(comparisons), "reviews": len(reviews), "required_attempts": 6,
                     "completed": sum(run["terminal"] == "COMPLETED" for run in runs), "accepted_attempts": sum(run["accepted"] for run in runs),
                     "accepted_families": sum(item["accepted"] for item in family_table.values()),
                     "missing_attempts": sorted(set(d3.SLOTS) - set(attempts)), "missing_comparisons": sorted(set(d3.SLOTS) - set(comparisons)),
                     "missing_reviews": sorted(set(d3.SLOTS) - set(reviews)), "lead_accepted": lead_accepted, "lead_denominator": 222},
        "runs": runs, "classes": class_table, "families": family_counts, "family_results": family_table,
        "totals": {**counts, "class_denominator": 222, "bad_family_denominator": 114, "nonbad_null_denominator": 108,
                   "known_bad_or_uncertain_denominator": 168},
        "repeatability": repeatability,
        "cost": {"measured_usd": json_amount(measured) if measured is not None else None, "known_measured_usd": json_amount(measured_known),
                 "limit_usd": 30, "attempt_limit_usd": 5, "transmissions": transmissions, "transmission_limit": 6,
                 "reserved_usd": ledger["reserved_usd"] if ledger is not None else None,
                 "unknown_exposure_usd": ledger["unknown_exposure_usd"] if ledger is not None else None, "ledger_complete": ledger_complete},
        "status": {"result": result, "failure_reasons": sorted(set(reasons)), "semantic_rejections": sorted(set(semantic)),
                   "source_conflicts": sorted(set(conflicts)), "authorizes_later_stage": False,
                   "interpretation": "known-control reproducibility only; not Stage 1 qualification or unseen error rates"},
    }


def aggregate(root, *, binding_id, freeze_sha256, packet_sha256):
    with d3.PrivateStore(root) as store:
        attempts = read_slots(store, "attempt", attempt_shape)
        comparisons = read_slots(store, "comparison", d3.checked_comparison)
        reviews = read_slots(store, "lead-review", review_shape)
        try:
            ledger = store.load("ledger.json")
        except FileNotFoundError:
            ledger = None
        result = evaluate(attempts, comparisons, reviews, ledger, binding_id=binding_id,
                          freeze_sha256=freeze_sha256, packet_sha256=packet_sha256)
        store.emit("aggregate.json", result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    for name in ("binding-id", "freeze-sha256", "packet-sha256"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args(argv)
    try:
        result = aggregate(args.root, binding_id=args.binding_id, freeze_sha256=args.freeze_sha256, packet_sha256=args.packet_sha256)
        print(json.dumps({"result": result["status"]["result"], "authorizes_later_stage": False}))
        return 0 if result["status"]["result"] == "T1_ACCEPTED" else 1
    except (d3.Refusal, OSError):
        print(json.dumps({"result": "REFUSED", "authorizes_later_stage": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
