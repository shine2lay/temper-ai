#!/usr/bin/env python3
"""A second, separately written calculation of the pmf_evidence benchmark values (queue #13).

    python3 independent.py CASE_DIR      print the case's values in expected.json's shape

Written before the kit's calculator, from the rules in the kit's data dictionary only, in a
different style (row-by-row lists, the closed-form Wilson interval), to cross-check the values in
expected.json, which were first worked out by hand from each case's construction. It is a check
on the benchmark, not part of the kit. Standard library only.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

ID_FIELD = {"users": "user_id", "activity": "event_id", "survey": "response_id", "payments": "row_id"}
FIELDS = {
    "users": ["user_id", "account_id", "started_on"],
    "activity": ["event_id", "user_id", "event", "occurred_on"],
    "survey": ["response_id", "user_id", "submitted_on", "answer"],
    "payments": ["row_id", "account_id", "kind", "amount", "currency", "occurred_on", "ref_row_id"],
}
ANSWERS = {"very disappointed": "very", "somewhat disappointed": "somewhat", "not disappointed": "not"}


def pct(frac: Fraction) -> str:
    return str((Decimal(frac.numerator) * 100 / Decimal(frac.denominator)).quantize(Decimal("0.1"), ROUND_HALF_UP))


def pct_float(x: float) -> str:
    return str(Decimal(repr(x * 100)).quantize(Decimal("0.1"), ROUND_HALF_UP))


def day(text: str):
    text = text.strip()
    if len(text) < 10 or (len(text) > 10 and text[10] not in "T "):
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def read(folder: Path, name: str) -> list[dict]:
    with open(folder / f"{name}.csv", newline="") as handle:
        reader = csv.DictReader(handle)
        out = []
        for row in reader:
            clean = {k: (row.get(k) or "").strip() for k in FIELDS[name]}
            clean["_line"] = reader.line_num
            out.append(clean)
        return out


def first_pass(rows: list[dict], name: str):
    """Blank ids, then duplicates by id: identical copies dropped, differing copies all rejected."""
    rejected, dropped, keep = [], 0, []
    idf = ID_FIELD[name]
    groups: dict[str, list[dict]] = {}
    for row in rows:
        if not row[idf]:
            rejected.append((row["_line"], "missing_value"))
        else:
            groups.setdefault(row[idf], []).append(row)
    for row in rows:
        if not row[idf]:
            continue
        group = groups[row[idf]]
        same = all(tuple(g[f] for f in FIELDS[name]) == tuple(group[0][f] for f in FIELDS[name]) for g in group)
        if not same:
            rejected.append((row["_line"], "conflicting_duplicate"))
        elif row is not group[0]:
            dropped += 1
        else:
            keep.append(row)
    return keep, rejected, dropped


def money(text: str):
    parts = text.split(".")
    if not parts[0].isdigit() or len(parts) > 2 or (len(parts) == 2 and not (1 <= len(parts[1]) <= 2 and parts[1].isdigit())):
        return None
    value = Decimal(text)
    return value if value > 0 else None


def compute(folder: Path) -> dict:
    p = json.loads((folder / "params.json").read_text())
    until = date.fromisoformat(p["observed_until"])
    raw = {name: read(folder, name) for name in FIELDS}
    files = {}
    reject: dict[str, list] = {}

    # users
    keep, rej, dup = first_pass(raw["users"], "users")
    users = {}
    for row in keep:
        if not all(row[f] for f in FIELDS["users"]):
            rej.append((row["_line"], "missing_value"))
            continue
        start = day(row["started_on"])
        if start is None:
            rej.append((row["_line"], "bad_date"))
            continue
        if start > until:
            rej.append((row["_line"], "after_observation_end"))
            continue
        users[row["user_id"]] = (row["account_id"], start)
    reject["users"], files["users"] = rej, {"rows": len(raw["users"]), "duplicates": dup}

    # activity
    keep, rej, dup = first_pass(raw["activity"], "activity")
    events = []
    other = 0
    for row in keep:
        if not all(row[f] for f in FIELDS["activity"]):
            rej.append((row["_line"], "missing_value"))
            continue
        when = day(row["occurred_on"])
        if when is None:
            rej.append((row["_line"], "bad_date"))
            continue
        if when > until:
            rej.append((row["_line"], "after_observation_end"))
            continue
        if row["user_id"] not in users:
            rej.append((row["_line"], "unknown_user"))
            continue
        if when < users[row["user_id"]][1]:
            rej.append((row["_line"], "before_user_start"))
            continue
        if row["event"] == p["value_event"]:
            events.append((row["user_id"], when))
        else:
            other += 1
    reject["activity"], files["activity"] = rej, {"rows": len(raw["activity"]), "duplicates": dup}

    # survey
    keep, rej, dup = first_pass(raw["survey"], "survey")
    responses = []
    for row in keep:
        if not all(row[f] for f in FIELDS["survey"]):
            rej.append((row["_line"], "missing_value"))
            continue
        when = day(row["submitted_on"])
        if when is None:
            rej.append((row["_line"], "bad_date"))
            continue
        if when > until:
            rej.append((row["_line"], "after_observation_end"))
            continue
        if row["user_id"] not in users:
            rej.append((row["_line"], "unknown_user"))
            continue
        if when < users[row["user_id"]][1]:
            rej.append((row["_line"], "before_user_start"))
            continue
        answer = " ".join(row["answer"].lower().replace("_", " ").replace("-", " ").split())
        if answer not in ANSWERS:
            rej.append((row["_line"], "bad_answer"))
            continue
        responses.append((when, row["_line"], row["user_id"], ANSWERS[answer]))
    reject["survey"], files["survey"] = rej, {"rows": len(raw["survey"]), "duplicates": dup}

    # payments
    keep, rej, dup = first_pass(raw["payments"], "payments")
    accounts = {a for a, _ in users.values()}
    good, pending = {}, []
    for row in keep:
        if not all(row[f] for f in FIELDS["payments"] if f != "ref_row_id"):
            rej.append((row["_line"], "missing_value"))
            continue
        when = day(row["occurred_on"])
        if when is None:
            rej.append((row["_line"], "bad_date"))
            continue
        if when > until:
            rej.append((row["_line"], "after_observation_end"))
            continue
        if row["kind"] not in ("payment", "refund", "fee", "promise"):
            rej.append((row["_line"], "unknown_kind"))
            continue
        amount = money(row["amount"])
        if amount is None:
            rej.append((row["_line"], "bad_amount"))
            continue
        if row["currency"] != p["currency"]:
            rej.append((row["_line"], "currency_mismatch"))
            continue
        if row["account_id"] not in accounts:
            rej.append((row["_line"], "unknown_account"))
            continue
        item = {"id": row["row_id"], "account": row["account_id"], "kind": row["kind"], "amount": amount,
                "when": when, "ref": row["ref_row_id"], "line": row["_line"]}
        if row["kind"] in ("payment", "promise"):
            if row["ref_row_id"]:
                rej.append((row["_line"], "unexpected_reference"))
                continue
            good[row["row_id"]] = item
        else:
            pending.append(item)
    refunded: dict[str, Decimal] = {}
    fees: dict[str, Decimal] = {}
    for item in sorted(pending, key=lambda i: (i["when"], i["line"])):
        target = good.get(item["ref"])
        if target is None or target["kind"] != "payment" or target["account"] != item["account"]:
            rej.append((item["line"], "bad_reference"))
            continue
        if item["when"] < target["when"]:
            rej.append((item["line"], "before_referenced_payment"))
            continue
        if item["kind"] == "refund":
            if refunded.get(item["ref"], Decimal(0)) + item["amount"] > target["amount"]:
                rej.append((item["line"], "refund_exceeds_payment"))
                continue
            refunded[item["ref"]] = refunded.get(item["ref"], Decimal(0)) + item["amount"]
        else:
            fees[item["ref"]] = fees.get(item["ref"], Decimal(0)) + item["amount"]
    reject["payments"], files["payments"] = rej, {"rows": len(raw["payments"]), "duplicates": dup}

    limit = Fraction(Decimal(str(p["data_quality"]["max_rejected_share"])))
    over = {}
    for name in FIELDS:
        counts: dict[str, int] = {}
        for _, code in reject[name]:
            counts[code] = counts.get(code, 0) + 1
        files[name]["rejected"] = dict(sorted(counts.items()))
        rows = files[name]["rows"]
        over[name] = rows > 0 and Fraction(len(reject[name]), rows) > limit
        files[name]["over_limit"] = over[name]

    # ---- survey metric
    s = p["survey"]
    first: dict[str, tuple] = {}
    for item in sorted(responses):
        first.setdefault(item[2], item)
    eligible, answers = 0, {"very": 0, "somewhat": 0, "not": 0}
    for when, _, user, answer in first.values():
        lo = when - timedelta(days=s["lookback_days"])
        used = sum(1 for u, w in events if u == user and lo < w <= when)
        if used >= s["min_value_events"]:
            eligible += 1
            answers[answer] += 1
    reasons = []
    if over["users"] or over["activity"] or over["survey"]:
        reasons.append("data_quality")
    if files["survey"]["rows"] == 0:
        reasons.append("no_data")
    elif eligible < s["min_responses"]:
        reasons.append("too_few_responses")
    if reasons:
        status = "insufficient_evidence"
    elif answers["very"] * 5 >= eligible * 2:
        status = "met"
    else:
        status, reasons = "not_met", ["below_threshold"]
    survey = {"status": status, "reasons": reasons, "valid": len(responses), "repeat": len(responses) - len(first),
              "first": len(first), "eligible": eligible, "ineligible": len(first) - eligible, **answers,
              "share_pct": pct(Fraction(answers["very"], eligible)) if eligible else None,
              "interval_pct": None, "more_needed": max(0, s["min_responses"] - eligible)}
    if eligible:
        n, ph, z = eligible, answers["very"] / eligible, 1.96
        root = z * math.sqrt(z * z + 4 * n * ph * (1 - ph))
        survey["interval_pct"] = [pct_float((2 * n * ph + z * z - root) / (2 * (n + z * z))),
                                  pct_float((2 * n * ph + z * z + root) / (2 * (n + z * z)))]

    # ---- retention metric
    r = p["retention"]
    length = r["period_days"]
    full = {u: ((until - start).days + 1) // length for u, (_, start) in users.items()}
    active: dict[str, set] = {u: set() for u in users}
    for u, w in events:
        active[u].add((w - users[u][1]).days // length)
    top = max(full.values(), default=0)
    curve = []
    for k in range(top):
        seen = [u for u in users if full[u] > k]
        curve.append([k, len(seen), sum(1 for u in seen if k in active[u])])
    adequate = 0
    for k, seen, _ in curve:
        if k >= 1 and seen >= r["min_users_per_period"]:
            adequate = k
    reasons = []
    if over["users"] or over["activity"]:
        reasons.append("data_quality")
    if files["users"]["rows"] == 0 or files["activity"]["rows"] == 0:
        reasons.append("no_data")
    elif adequate < r["min_periods"]:
        reasons.append("too_few_periods")
    window = drop = last = None
    adequate_on = None
    if "too_few_periods" in reasons:
        m = r["min_periods"]
        ends = sorted(start + timedelta(days=(m + 1) * length - 1) for _, start in users.values())
        if len(ends) >= r["min_users_per_period"]:
            adequate_on = ends[r["min_users_per_period"] - 1].isoformat()
    if reasons:
        status = "insufficient_evidence"
    else:
        a, b = adequate - r["flat_last_periods"] + 1, adequate
        first_rate = Fraction(curve[a][2], curve[a][1])
        last_rate = Fraction(curve[b][2], curve[b][1])
        fall = (first_rate - last_rate) * 100
        window, drop, last = [a, b], pct(fall / 100), pct(last_rate)
        bad = []
        if fall > Fraction(Decimal(str(r["flat_max_drop_pp"]))):
            bad.append("still_declining")
        if last_rate < Fraction(Decimal(str(r["min_plateau_rate"]))):
            bad.append("below_plateau")
        status, reasons = ("not_met", bad) if bad else ("met", [])
    retention = {"status": status, "reasons": reasons, "users": len(users), "curve": curve,
                 "adequate_periods": adequate, "window": window, "drop_pp": drop, "last_pct": last,
                 "adequate_on": adequate_on}

    # ---- payment and revenue
    pay, rev = p["payment"], p["revenue"]
    h0, h1 = date.fromisoformat(rev["horizon_start"]), date.fromisoformat(rev["horizon_end"])
    complete = h1 <= until
    inside = [g for g in good.values() if g["kind"] == "payment" and h0 <= g["when"] <= min(h1, until)]
    outside = [g for g in good.values() if g["kind"] == "payment" and not (h0 <= g["when"] <= min(h1, until))]
    promises = [g for g in good.values() if g["kind"] == "promise" and h0 <= g["when"] <= min(h1, until)]
    price = Decimal(pay["target_price"])
    target_acc, paying_acc, all_acc = set(), set(), set()
    for g in inside:
        kept = g["amount"] - refunded.get(g["id"], Decimal(0))
        all_acc.add(g["account"])
        if kept > 0:
            paying_acc.add(g["account"])
        if kept >= price:
            target_acc.add(g["account"])
    gross = sum((g["amount"] for g in inside), Decimal(0))
    back = sum((refunded.get(g["id"], Decimal(0)) for g in inside), Decimal(0))
    cost = sum((fees.get(g["id"], Decimal(0)) for g in inside), Decimal(0))
    net = gross - back - cost
    base = []
    if over["users"] or over["payments"]:
        base.append("data_quality")
    if files["payments"]["rows"] == 0:
        base.append("no_data")
    if base:
        pstatus, preasons = "insufficient_evidence", list(base)
    elif len(target_acc) >= pay["min_target_price_accounts"]:
        pstatus, preasons = "met", []
    elif complete:
        pstatus, preasons = "not_met", ["too_few_accounts"]
    else:
        pstatus, preasons = "insufficient_evidence", ["horizon_open"]
    if base:
        rstatus, rreasons = "insufficient_evidence", list(base)
    elif net >= Decimal(rev["target"]):
        rstatus, rreasons = "met", []
    elif complete:
        rstatus, rreasons = "not_met", ["below_target"]
    else:
        rstatus, rreasons = "insufficient_evidence", ["horizon_open"]
    q = Decimal("0.01")
    payment = {"status": pstatus, "reasons": preasons, "target_accounts": len(target_acc),
               "paying_accounts": len(paying_acc), "below_target_accounts": len(paying_acc - target_acc),
               "fully_refunded_accounts": len(all_acc - paying_acc)}
    revenue = {"status": rstatus, "reasons": rreasons, "gross": str(gross.quantize(q)), "refunds": str(back.quantize(q)),
               "fees": str(cost.quantize(q)), "net": str(net.quantize(q)), "promises": len(promises),
               "promised": str(sum((g["amount"] for g in promises), Decimal(0)).quantize(q)),
               "outside_horizon": len(outside),
               "outside_amount": str(sum((g["amount"] for g in outside), Decimal(0)).quantize(q)),
               "horizon_complete": complete}
    met = survey["status"] == retention["status"] == payment["status"] == "met"
    return {"expected_final_status": "reported", "verdict": "fit_indicators_met" if met else "fit_not_shown",
            "files": files, "survey": survey, "retention": retention, "payment": payment, "revenue": revenue}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(json.dumps(compute(Path(sys.argv[1])), indent=1))
