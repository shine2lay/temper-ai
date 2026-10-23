#!/usr/bin/env python3
"""design_source_checks (design role): the accepted homepage source checks, run on their frozen keys.

Step check of workflows/design_source_checks_next.yaml (agent design_source_checks_next; queue #139,
hypothesis H15, widened by queue #143 after H16, both in ~/design-lab/homepage-workflow/HYPOTHESES.md).
Test-only and model-free: no live workflow runs it. Four browser-free checks passed locally with exact answers, each in its own frozen
packet under ~/design-lab/rubric/2026-10-22-next-steps/:

  a3-01-preflight       A3 input guard (#133)        guard_kernel.preflight
  a2-01-source-h1       A2 one h1 (#134)             source_h1_kernel.source_h1
  a1-02-headline-words  A1 headline words (#136)     headline_words_kernel.evaluate_a1_02_source_headline_words
  a2-05-scale-steps     A2 type-scale steps (#137)   scale_steps_kernel.evaluate_a2_05_declared_scale_steps

The kernels sit in source_checks/ beside this script; only their pure functions are called, never their
async browser check() or their command-line mains. guard_kernel.py and scale_steps_kernel.py are the
packets' files unchanged (lint-only edits). source_h1_kernel.py and headline_words_kernel.py carry H16's
widened shared reader and guard (Design #140), which reads the homepage build stage's own page dialect
(more tags, inline svg, elements without an id named by their document path, data-typography="Body"
marks); what their checks count and decide is unchanged.

A key is a folder with one sub-folder per check (its INPUTS.json and EXPECTED.jsonl) and the fixtures
they name. KEYS, run in this order (folders relative to configs/design):

  v1       testpages/source-checks-v1   all four checks: the packets' keys, copied unchanged (250 records)
  v2       testpages/source-checks-v2   A2-01 and A1-02 on the four public converter test pages in the
                                        build dialect, planted and frozen before the widened kernels came
                                        in (48 records; FREEZE.md)
  real-v1  local/source-checks-real-v1  A2-01 and A1-02 on built homepages: H16's real-page key (144
                                        records). git-ignored, so present only where it was copied (the
                                        configs temper-dev mounts); elsewhere reported absent, not run

A required key that is missing is a crash, never a pass.

Each record is paired and compared the way the packet's supervisor did it: slot = case@WIDTHxHEIGHT,
case-major and environment-minor from INPUTS.json; the role inventory is the case's own when it carries
one (the v2 and real-page pages differ), else the one in INPUTS.json; a fixture whose bytes differ from
its declared actual_sha256 is not run; the arguments go through the same JSON wire the packet used (fresh objects per
record), the answer is serialised and read back as the packet's supervisor read it (a tuple becomes a
list; duplicate keys and NaN refused) and compared exactly: same types, same object key order, every
list item. A record is EXACT, MISMATCH (a different answer, or the kernel raised) or MISSING (no input
for its slot, or its fixture is absent or does not match its declared bytes), never skipped.

Writes every record to --out (default results.json) and prints one JSON summary: per key and per check
the records, exact, mismatch and missing counts, with the Python version and platform. Exits 0 whether
or not the records match; only a crash (an unreadable or missing required key) exits non-zero. --key DIR
runs only that folder, as one key holding the check sub-folders it has.

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
CONFIGS = HERE.parent
KERNELS = HERE / "source_checks"

# inventory: the role inventory's field (the case's own when it has one, else INPUTS.json's); declaration:
# the fifth argument's per-case field, if any; bound: INPUTS.json declares each fixture's actual_sha256.
CHECKS: tuple[dict[str, Any], ...] = (
    {"check": "a3-01-preflight", "task": "#133", "kernel": "guard_kernel.py", "function": "preflight",
     "case": "id", "fixture": "html", "answer": "tuple", "inventory": "inventory",
     "declaration": None, "bound": False},
    {"check": "a2-01-source-h1", "task": "#134", "kernel": "source_h1_kernel.py", "function": "source_h1",
     "case": "case", "fixture": "html", "answer": "record", "inventory": "inventory",
     "declaration": None, "bound": True},
    {"check": "a1-02-headline-words", "task": "#136", "kernel": "headline_words_kernel.py",
     "function": "evaluate_a1_02_source_headline_words", "case": "case", "fixture": "path", "answer": "result",
     "inventory": "role_inventory", "declaration": "headline_declaration", "bound": True},
    {"check": "a2-05-scale-steps", "task": "#137", "kernel": "scale_steps_kernel.py",
     "function": "evaluate_a2_05_declared_scale_steps", "case": "case", "fixture": "fixture", "answer": "result",
     "inventory": "role_inventory", "declaration": "scale_declaration", "bound": True},
)

# folder: relative to configs/design (an absolute folder is used as it is); required: a missing folder is a
# crash, else the key is reported absent and not run.
KEYS: tuple[dict[str, Any], ...] = (
    {"key": "v1", "folder": "testpages/source-checks-v1",
     "checks": ("a3-01-preflight", "a2-01-source-h1", "a1-02-headline-words", "a2-05-scale-steps"),
     "required": True},
    {"key": "v2", "folder": "testpages/source-checks-v2", "checks": ("a2-01-source-h1", "a1-02-headline-words"),
     "required": True},
    {"key": "real-v1", "folder": "local/source-checks-real-v1",
     "checks": ("a2-01-source-h1", "a1-02-headline-words"), "required": False},
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


def run_check(spec: dict[str, Any], key: Path, kernels: Path = KERNELS) -> dict[str, Any]:
    """Every frozen record of one check through its kernel's pure function, compared exactly."""
    folder = key / spec["check"]
    inputs_raw = (folder / "INPUTS.json").read_bytes()
    expected_raw = (folder / "EXPECTED.jsonl").read_bytes()
    inputs = strict_loads(inputs_raw)
    expected = [strict_loads(line) for line in expected_raw.splitlines()]
    kernel_path = kernels / spec["kernel"]
    function = getattr(load_kernel(kernel_path), spec["function"])

    field = spec["inventory"]
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
        inventory = case[field] if field in case else inputs[field]
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


def key_from_folder(folder: Path) -> tuple[dict[str, Any], ...]:
    """One ad-hoc key (--key): the check sub-folders the folder has, in CHECKS order; none is an error."""
    folder = folder.resolve()
    checks = tuple(spec["check"] for spec in CHECKS if (folder / spec["check"]).is_dir())
    if not checks:
        raise FileNotFoundError(f"no check folder in {folder}")
    return ({"key": folder.name, "folder": str(folder), "checks": checks, "required": True},)


def _counts(checks: list[dict[str, Any]]) -> dict[str, int]:
    return {field: sum(c[field] for c in checks) for field in ("records", "exact", "mismatch", "missing")}


def run_all(keys: tuple[dict[str, Any], ...] = KEYS, kernels: Path = KERNELS,
            root: Path = CONFIGS) -> dict[str, Any]:
    """Every check of every key present, in KEYS order; an absent optional key is listed, not run."""
    specs = {spec["check"]: spec for spec in CHECKS}
    checks: list[dict[str, Any]] = []
    listed = []
    for key in keys:
        folder = root / key["folder"]
        present = folder.is_dir()
        if not present and key["required"]:
            raise FileNotFoundError(f"required key {key['key']} is missing: {folder}")
        ran = [{"key": key["key"], **run_check(specs[name], folder, kernels)} for name in key["checks"]
               if present]
        checks += ran
        verdict = "ABSENT" if not present else "ALL_EXACT" if all(clean(c) for c in ran) else "NOT_ALL_EXACT"
        listed.append({"key": key["key"], "folder": key["folder"], "required": key["required"],
                       "present": present, "verdict": verdict, "checks": [c["check"] for c in ran],
                       **_counts(ran)})
    return {
        "schema": "design-source-checks-results/2",
        "verdict": "ALL_EXACT" if checks and all(clean(c) for c in checks) else "NOT_ALL_EXACT",
        **_counts(checks),
        "keys": listed,
        "python": {"implementation": platform.python_implementation(), "version": platform.python_version()},
        "platform": platform.platform(),
        "checks": checks,
    }


def summary(results: dict[str, Any], results_path: str, results_sha256: str) -> dict[str, Any]:
    checks = {}
    for c in results["checks"]:
        name = c["key"] + "/" + c["check"]
        checks[name] = {k: c[k] for k in ("task", "records", "exact", "mismatch", "missing",
                                          "order_matches_inputs", "kernel_sha256", "expected_sha256")}
        checks[name]["duplicate_slots"] = len(c["duplicate_slots"])
        checks[name]["unkeyed_slots"] = len(c["unkeyed_slots"])
        checks[name]["not_exact"] = [r["slot"] for r in c["results"] if r["state"] != "EXACT"][:20]
    keys = {k["key"]: {f: k[f] for f in ("folder", "present", "verdict", "records", "exact", "mismatch", "missing")}
            for k in results["keys"]}
    return {
        "status": "completed",
        "verdict": results["verdict"],
        "records": results["records"],
        "exact": results["exact"],
        "mismatch": results["mismatch"],
        "missing": results["missing"],
        "keys": keys,
        "checks": checks,
        "python": results["python"],
        "platform": results["platform"],
        "results_path": results_path,
        "results_sha256": results_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--key", help="run only this folder, as one key holding one sub-folder per check")
    ap.add_argument("--out", default="results.json", help="where every record is written")
    args = ap.parse_args(argv)
    results = run_all(key_from_folder(Path(args.key)) if args.key else KEYS)
    data = (json.dumps(results, indent=1, ensure_ascii=True, allow_nan=False) + "\n").encode()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(json.dumps(summary(results, args.out, sha256(data)), ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
