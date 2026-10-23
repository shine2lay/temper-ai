#!/usr/bin/env python3
"""design_source_checks (design role): the accepted homepage source checks, run on their frozen key.

Step check of workflows/design_source_checks_next.yaml (agent design_source_checks_next; queue #139,
hypothesis H15 in ~/design-lab/homepage-workflow/HYPOTHESES.md). Test-only and model-free: no live
workflow runs it. Four browser-free checks passed locally with exact answers, each in its own frozen
packet under ~/design-lab/rubric/2026-10-22-next-steps/:

  a3-01-preflight       A3 input guard (#133)        guard_kernel.preflight
  a2-01-source-h1       A2 one h1 (#134)             source_h1_kernel.source_h1
  a1-02-headline-words  A1 headline words (#136)     headline_words_kernel.evaluate_a1_02_source_headline_words
  a2-05-scale-steps     A2 type-scale steps (#137)   scale_steps_kernel.evaluate_a2_05_declared_scale_steps

The kernels are copied unchanged into source_checks/ beside this script (lint-only edits); only their
pure functions are called, never their async browser check() or their command-line mains. The key is
each packet's INPUTS.json, EXPECTED.jsonl and fixtures, copied unchanged to
configs/design/testpages/source-checks-v1/<check>/.

Each record is paired and compared the way the packet's supervisor did it: slot = case@WIDTHxHEIGHT,
case-major and environment-minor from INPUTS.json; a fixture whose bytes differ from its declared
actual_sha256 is not run; the arguments go through the same JSON wire the packet used (fresh objects per
record), the answer is serialised and read back as the packet's supervisor read it (a tuple becomes a
list; duplicate keys and NaN refused) and compared exactly: same types, same object key order, every
list item. A record is EXACT, MISMATCH (a different answer, or the kernel raised) or MISSING (no input
for its slot, or its fixture is absent or does not match its declared bytes), never skipped.

Writes every record to --out (default results.json) and prints one JSON summary: per check the records,
exact, mismatch and missing counts, with the Python version and platform. Exits 0 whether or not the
records match; only a crash (an unreadable key) exits non-zero.

    design_source_checks.py [--key DIR] [--out results.json]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
KERNELS = HERE / "source_checks"
KEY = HERE.parent / "testpages" / "source-checks-v1"

# inventory: where the role inventory sits (per case, or once in INPUTS.json); declaration: the fifth
# argument's per-case field, if any; bound: INPUTS.json declares each fixture's actual_sha256.
CHECKS: tuple[dict[str, Any], ...] = (
    {"check": "a3-01-preflight", "task": "#133", "kernel": "guard_kernel.py", "function": "preflight",
     "case": "id", "fixture": "html", "answer": "tuple", "inventory": ("case", "inventory"),
     "declaration": None, "bound": False},
    {"check": "a2-01-source-h1", "task": "#134", "kernel": "source_h1_kernel.py", "function": "source_h1",
     "case": "case", "fixture": "html", "answer": "record", "inventory": ("case", "inventory"),
     "declaration": None, "bound": True},
    {"check": "a1-02-headline-words", "task": "#136", "kernel": "headline_words_kernel.py",
     "function": "evaluate_a1_02_source_headline_words", "case": "case", "fixture": "path", "answer": "result",
     "inventory": ("inputs", "role_inventory"), "declaration": "headline_declaration", "bound": True},
    {"check": "a2-05-scale-steps", "task": "#137", "kernel": "scale_steps_kernel.py",
     "function": "evaluate_a2_05_declared_scale_steps", "case": "case", "fixture": "fixture", "answer": "result",
     "inventory": ("inputs", "role_inventory"), "declaration": "scale_declaration", "bound": True},
)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _no_constant(value: str) -> Any:
    raise ValueError("nonfinite JSON constant")


def strict_loads(raw: str | bytes) -> Any:
    """The packets' reader: a duplicate key or a NaN/Infinity constant is refused, not coerced."""
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=_no_constant)


def wire(value: Any) -> str:
    """The packets' wire format (compact, no NaN)."""
    return json.dumps(value, separators=(",", ":"), allow_nan=False)


def exact(a: Any, b: Any) -> bool:
    """The packets' comparator: no coercion or tolerance; object key order and every list item count."""
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return list(a) == list(b) and all(exact(a[k], b[k]) for k in a)
    if type(a) is list:
        return len(a) == len(b) and all(exact(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_kernel(path: Path) -> ModuleType:
    """Import one kernel file by its path, under its own module name, without writing bytecode
    (the configs folder is mounted read-only in the container)."""
    spec = importlib.util.spec_from_file_location("design_source_checks_" + path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def run_check(spec: dict[str, Any], key: Path = KEY, kernels: Path = KERNELS) -> dict[str, Any]:
    """Every frozen record of one check through its kernel's pure function, compared exactly."""
    folder = key / spec["check"]
    inputs_raw = (folder / "INPUTS.json").read_bytes()
    expected_raw = (folder / "EXPECTED.jsonl").read_bytes()
    inputs = strict_loads(inputs_raw)
    expected = [strict_loads(line) for line in expected_raw.splitlines()]
    kernel_path = kernels / spec["kernel"]
    function = getattr(load_kernel(kernel_path), spec["function"])

    where, field = spec["inventory"]
    slots: dict[str, tuple[dict[str, Any], list[Any]]] = {}
    order = []
    for case in inputs["cases"]:
        for environment in inputs["environments"]:
            slot = f"{case[spec['case']]}@{environment[0]}x{environment[1]}"
            order.append(slot)
            slots[slot] = (case, environment)

    records = []
    for row in expected:
        slot = row["slot"]
        record: dict[str, Any] = {"slot": slot, "state": "MISSING", "expected": row[spec["answer"]], "observed": None}
        records.append(record)
        if slot not in slots:
            record["reason"] = "NO_INPUT_FOR_SLOT"
            continue
        case, environment = slots[slot]
        try:
            html = (folder / case[spec["fixture"]]).read_bytes()
        except OSError:
            record["reason"] = "FIXTURE_UNREADABLE"
            continue
        if spec["bound"] and sha256(html) != case["actual_sha256"]:
            record["reason"] = "FIXTURE_BINDING_MISMATCH"
            continue
        inventory = case[field] if where == "case" else inputs[field]
        arguments = [case["declared_sha256"], inventory, environment]
        if spec["declaration"]:
            arguments.append(case[spec["declaration"]])
        arguments = strict_loads(wire(arguments))  # fresh objects per record, as the packet's JSON wire gave them
        try:
            observed = strict_loads(wire(function(html, *arguments)))
        except Exception as exc:  # a kernel that raises answered differently from the key
            record["state"] = "MISMATCH"
            record["error"] = f"{type(exc).__name__}: {exc}"
            continue
        record["observed"] = observed
        record["state"] = "EXACT" if exact(record["expected"], observed) else "MISMATCH"

    keyed = [r["slot"] for r in records]
    counts = {state: sum(r["state"] == state for r in records) for state in ("EXACT", "MISMATCH", "MISSING")}
    return {
        "check": spec["check"],
        "task": spec["task"],
        "function": spec["function"],
        "kernel_sha256": sha256(kernel_path.read_bytes()),
        "inputs_sha256": sha256(inputs_raw),
        "expected_sha256": sha256(expected_raw),
        "records": len(records),
        "exact": counts["EXACT"],
        "mismatch": counts["MISMATCH"],
        "missing": counts["MISSING"],
        "order_matches_inputs": keyed == order,
        "duplicate_slots": sorted({s for s in keyed if keyed.count(s) > 1}),
        "unkeyed_slots": [s for s in order if s not in set(keyed)],
        "results": records,
    }


def clean(result: dict[str, Any]) -> bool:
    return (result["records"] > 0 and result["exact"] == result["records"] and result["mismatch"] == 0
            and result["missing"] == 0 and result["order_matches_inputs"]
            and not result["duplicate_slots"] and not result["unkeyed_slots"])


def run_all(key: Path = KEY, kernels: Path = KERNELS) -> dict[str, Any]:
    checks = [run_check(spec, key, kernels) for spec in CHECKS]
    return {
        "schema": "design-source-checks-results/1",
        "verdict": "ALL_EXACT" if all(clean(c) for c in checks) else "NOT_ALL_EXACT",
        "records": sum(c["records"] for c in checks),
        "exact": sum(c["exact"] for c in checks),
        "mismatch": sum(c["mismatch"] for c in checks),
        "missing": sum(c["missing"] for c in checks),
        "python": {"implementation": platform.python_implementation(), "version": platform.python_version()},
        "platform": platform.platform(),
        "checks": checks,
    }


def summary(results: dict[str, Any], results_path: str, results_sha256: str) -> dict[str, Any]:
    checks = {}
    for c in results["checks"]:
        checks[c["check"]] = {k: c[k] for k in ("task", "records", "exact", "mismatch", "missing",
                                                 "order_matches_inputs", "kernel_sha256", "expected_sha256")}
        checks[c["check"]]["duplicate_slots"] = len(c["duplicate_slots"])
        checks[c["check"]]["unkeyed_slots"] = len(c["unkeyed_slots"])
        checks[c["check"]]["not_exact"] = [r["slot"] for r in c["results"] if r["state"] != "EXACT"][:20]
    return {
        "status": "completed",
        "verdict": results["verdict"],
        "records": results["records"],
        "exact": results["exact"],
        "mismatch": results["mismatch"],
        "missing": results["missing"],
        "checks": checks,
        "python": results["python"],
        "platform": results["platform"],
        "results_path": results_path,
        "results_sha256": results_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--key", default=str(KEY), help="folder holding one sub-folder per check")
    ap.add_argument("--out", default="results.json", help="where every record is written")
    args = ap.parse_args(argv)
    results = run_all(Path(args.key))
    data = (json.dumps(results, indent=1, ensure_ascii=True, allow_nan=False) + "\n").encode()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(json.dumps(summary(results, args.out, sha256(data)), ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
