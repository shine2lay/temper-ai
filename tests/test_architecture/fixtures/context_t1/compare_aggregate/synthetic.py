"""Invented data ONLY. Never reads C1, heldout, other sessions or a model payload.

Builds a complete independent toy key/freeze, 37 label-free toy controls, D2
receipts, six raw answers/attempts/comparisons/lead receipts and a complete
ledger in pytest's private temporary root. Class/family inventories below are
independent literals from the approved aggregate-only plan, not D3 constants.
All assertion text/IDs/paths/UUIDs/times/routes are fabricated. Nothing here
asserts semantic validity, native-route admission, isolation or Stage 1 success.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

REPO = Path(__file__).resolve().parents[5]
BIN = REPO / "configs/architecture/bin"
SCHEMAS = REPO / "configs/architecture/stages/context_profile/t1"


def module(name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


d3 = module("context_t1_compare")
d4 = module("context_t1_aggregate")
SLOTS = ("A1", "A2", "A3", "B1", "B2", "B3")
LABEL_COUNTS = (("supported", 9), ("contradicted", 10), ("unsupported", 9), ("uncertain", 9))
BAD_FAMILIES = ("F01", "F02", "F03", "F03", "F04", "F05", "F05", "F06", "F06", "F07",
                "F07", "F08", "F08", "F09", "F10", "F10", "F11", "F12", "F12")
BRIEF = 'Invented café α: the toy lamp is blue. Alternative exact quote: "blue".'
BINDING = "synthetic-binding-never-admitted"


def encode(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def pin(text):
    return digest(text.encode())


def write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = value if type(value) is bytes else encode(value)
    path.write_bytes(raw)
    path.chmod(0o600)
    return digest(raw)


def toy_key():
    rows, families = [], iter(BAD_FAMILIES)
    for label, count in LABEL_COUNTS:
        for _ in range(count):
            ident = len(rows) + 1
            rows.append({"id": f"invented-{ident:03d}", "path": f"/toy/{ident}", "label": label,
                         "family": next(families) if label in ("contradicted", "unsupported") else None,
                         "source_span": "none" if label == "unsupported" else "the toy lamp is blue",
                         "rationale": "Invented fixture rationale, not a semantic evaluation."})
    return {"schema": "candidate-decisions/v2", "decisions": rows}


class Corpus:
    def __init__(self, root):
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        self.key = toy_key()
        self.key_pin = write(root, "key/EXPECTED.json", self.key)
        packet = {"schema": "label-free-controls/v2-candidate", "controls": [
            {"id": row["id"], "path": row["path"], "brief": BRIEF,
             "profile": {"facts": ["the toy lamp is blue"], "unknowns": ["lamp weight"],
                         "constraints": ["use the blue lamp"], "relation": "toy joint-section assertion"}}
            for row in self.key["decisions"]]}
        self.packet_pin = write(root, "packet/PACKET.json", packet)
        self.freeze_pin = write(root, "key/EXPECTED-FREEZE.json", {
            "schema": "t0-expected-freeze/v1", "sha256": {
                "key/EXPECTED.json": self.key_pin, "synthetic-only-not-read": pin("invented freeze extra entry")}})
        self.answers, self.attempts, self.comparisons, self.reviews = {}, {}, {}, {}
        for index, slot in enumerate(SLOTS):
            raw_pin = self.answer(slot, copy.deepcopy(self.key))
            start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=(index % 3) * 100)
            dispatch = 1000 + (index % 3) * 100
            self.attempts[slot] = {
                "schema": "context-t1-attempt/v1", "slot": slot, "family": slot[0],
                "experiment_id": "synthetic-experiment", "binding_id": BINDING,
                "session_id": str(UUID(int=100 + index)), "run_id": str(UUID(int=200 + index)),
                "route": f"invented-native-{slot[0]}", "provider": f"invented-provider-{slot[0]}",
                "model": f"invented-model-{slot[0]}", "auth_mode": "invented-subscription",
                "source_sha256": pin("source"), "config_sha256": pin(f"config-{slot[0]}"),
                "pricing_sha256": pin(f"pricing-{slot[0]}"), "input_sha256": pin("invented input bundle"),
                "packet_sha256": self.packet_pin, "raw_sha256": raw_pin, "terminal": "COMPLETED",
                "transmissions": 1, "transmission_ids": [f"invented-call-{slot}"],
                "usage_state": "KNOWN", "list_price_usd": 1.25, "cost_state": "KNOWN", "reservation_usd": 5,
                "unknown_exposure_usd": 0, "cleanup": "CONFIRMED", "started_utc": start.isoformat(),
                "ended_utc": (start + timedelta(seconds=40)).isoformat(), "cleanup_utc": (start + timedelta(seconds=50)).isoformat(),
                "dispatch_monotonic_s": dispatch, "deadline_monotonic_s": dispatch + 900, "cleanup_monotonic_s": dispatch + 50,
                "deadline_s": 900, "resumed": False, "fallback": False, "failure_reasons": [],
            }
            self.reviews[slot] = {"schema": "context-t1-lead-review/v1", "slot": slot, "raw_sha256": raw_pin,
                                  "accepted_ids": [row["id"] for row in self.key["decisions"]], "rejected_ids": [], "source_conflict_ids": []}
        self.sync_ledger()

    def answer(self, slot, document):
        self.answers[slot] = document
        raw = encode(document)
        raw_pin = write(self.root, f"{slot}.raw.json", raw)
        write(self.root, f"{slot}.validation.json", {
            "schema": "context-t1-validation/v1", "slot": slot, "raw_sha256": raw_pin,
            "raw_bytes": len(raw), "packet_sha256": self.packet_pin, "verdict": "PASS", "reject_reasons": [],
            "decision_ids": [row["id"] for row in document["decisions"]]})
        return raw_pin

    def compare(self, slot="A1"):
        result = d3.compare(self.root, slot, self.freeze_pin)
        self.comparisons[slot] = result
        return result

    def compared(self):
        for slot in SLOTS:
            if slot not in self.comparisons:
                self.compare(slot)
        return self

    def changed_answer(self, slot, mutate):
        document = copy.deepcopy(self.answers[slot])
        mutate(document["decisions"])
        raw_pin = self.answer(slot, document)
        self.attempts[slot]["raw_sha256"] = self.reviews[slot]["raw_sha256"] = raw_pin
        self.sync_ledger()
        return self.compare(slot)

    def sync_ledger(self):
        known = all(a["cost_state"] == a["usage_state"] == "KNOWN" for a in self.attempts.values())
        self.ledger = {"schema": "context-t1-ledger/v1", "experiment_id": "synthetic-experiment", "binding_id": BINDING,
                       "cost_basis": "LIST_PRICE", "state": "COMPLETE" if known else "INCOMPLETE",
                       "measured_usd": float(sum(d4.money(a["list_price_usd"]) for a in self.attempts.values())) if known else None,
                       "reserved_usd": 0, "unknown_exposure_usd": 0 if known else None,
                       "entries": [{name: a[name] for name in d4.ENTRY_FIELDS} for a in self.attempts.values()]}

    def evaluate(self):
        return d4.evaluate(self.attempts, self.comparisons, self.reviews, self.ledger,
                           binding_id=BINDING, freeze_sha256=self.freeze_pin, packet_sha256=self.packet_pin)

    def materialize(self, order=None):
        for slot in order or SLOTS:
            for suffix, records in (("attempt", self.attempts), ("comparison", self.comparisons), ("lead-review", self.reviews)):
                if slot in records:
                    write(self.root, f"{slot}.{suffix}.json", records[slot])
        write(self.root, "ledger.json", self.ledger)


def fds():
    return len(os.listdir("/proc/self/fd"))
