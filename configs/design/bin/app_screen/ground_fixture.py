"""Stage 3's fixture checks: the shared sample data holds together, and which states it has data for.

The product file declares the invariants (fixture.invariants in ~/design-lab/products/<product>/app.yaml):

    same_value  {key, field}: every object in the fixture holding `key` carries one value of `field` per key
                value (one spot price per symbol, one status per parcel), wherever it sits
    totals      {total, plus[], minus[]}: the number at `total` equals the sum of the numbers at `plus` minus
                those at `minus`; a "[]" in a path sums over that list, an item without the field adds nothing

No model writes or judges a number here. check() returns the fixture-check.json record; states() the state
names the fixture has data for: every "states" field in it, at any depth (a list of names, or an object keyed
by them), so a part file's own states count.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

TOLERANCE = 0.005
_SEGMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(\[\])?$")


class PathError(ValueError):
    """A declared path does not match the fixture's shape."""


def values(data: Any, path: str) -> list[Any]:
    """Every value the path reaches; a list segment ("x[]") fans out, a missing field below a list is skipped."""
    current = [(data, False)]
    for seg in path.split("."):
        m = _SEGMENT.match(seg)
        if not m:
            raise PathError(f"{path}: {seg!r} is not a field name")
        name, fan = m.group(1), bool(m.group(2))
        nxt = []
        for value, inside_list in current:
            if not isinstance(value, dict) or name not in value or value[name] is None:
                if inside_list:
                    continue
                raise PathError(f"{path}: no field {name!r}")
            got = value[name]
            if fan:
                if not isinstance(got, list):
                    raise PathError(f"{path}: {name} is not a list")
                nxt += [(item, True) for item in got]
            else:
                nxt.append((got, inside_list))
        current = nxt
    return [v for v, _ in current]


def _number(path: str, got: list[Any]) -> float:
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in got):
        raise PathError(f"{path}: holds a value that is not a number")
    return float(sum(got))


def _objects(data: Any, where: str = "") -> Iterator[tuple[str, dict]]:
    if isinstance(data, dict):
        yield where or "(top)", data
        for k, v in data.items():
            yield from _objects(v, f"{where}/{k}" if where else k)
    elif isinstance(data, list):
        for i, v in enumerate(data):
            yield from _objects(v, f"{where}/{i}")


def check(fixture: Any, invariants: dict) -> dict:
    """fixture-check.json: verdict pass|fail, how many invariants were checked, and each problem."""
    problems: list[dict] = []
    checks = 0
    for rule in invariants.get("same_value", []):
        checks += 1
        seen: dict[Any, tuple[Any, str]] = {}
        for where, obj in _objects(fixture):
            if rule["key"] not in obj or rule["field"] not in obj:
                continue
            key, value = obj[rule["key"]], obj[rule["field"]]
            if key in seen and seen[key][0] != value:
                problems.append({"check": "same_value", "where": where,
                                 "problem": f"{rule['key']} {key}: {rule['field']} is {value!r} here but "
                                            f"{seen[key][0]!r} at {seen[key][1]}"})
            seen.setdefault(key, (value, where))
        if not seen:
            problems.append({"check": "same_value", "where": "(fixture)",
                             "problem": f"no object holds both {rule['key']} and {rule['field']}"})
    for rule in invariants.get("totals", []):
        checks += 1
        try:
            total = values(fixture, rule["total"])
            if len(total) != 1:
                raise PathError(f"{rule['total']}: reaches {len(total)} values, not one")
            want = _number(rule["total"], total)
            got = (sum(_number(p, values(fixture, p)) for p in rule["plus"])
                   - sum(_number(p, values(fixture, p)) for p in rule.get("minus", [])))
        except PathError as exc:
            problems.append({"check": "totals", "where": rule["total"], "problem": str(exc)})
            continue
        if abs(want - got) > TOLERANCE:
            minus = " - ".join(rule.get("minus", []))
            problems.append({"check": "totals", "where": rule["total"],
                             "problem": f"is {want:g} but {' + '.join(rule['plus'])}"
                                        f"{' - ' + minus if minus else ''} is {got:g}"})
    return {"verdict": "fail" if problems else "pass", "checks": checks, "problems": problems}


def slug(name: str) -> str:
    """A state's words as one key: "stale quote", "stale-quote" and "Stale_Quote" are all stale_quote."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def states(fixture: Any) -> set[str]:
    out: set[str] = set()
    for _, obj in _objects(fixture):
        held = obj.get("states")
        if isinstance(held, dict):
            out |= {slug(k) for k in held}
        elif isinstance(held, list):
            out |= {slug(k) for k in held if isinstance(k, str)}
    return out
