#!/usr/bin/env python3
"""Fit and revenue evidence kit (product role; built 2026-10-04, queue #13). Standard library only.

Measures the mission's product-market-fit indicators for one product from a params file and four
CSV exports, and keeps them apart:
  survey     share of eligible respondents answering "Very disappointed" to the Sean Ellis
             question (fixed bar 40%, at least survey.min_responses eligible respondents);
  retention  share of users doing the core value event in each fully observed period after they
             start, judged flat over the last adequate periods;
  payment    customer accounts that kept a payment of at least the target price, after refunds,
             in the horizon;
  revenue    gross receipts, refunds, payment fees and net collected against a target (reported
             apart: it is not one of the three fit indicators).
The verdict fit_indicators_met needs survey, retention and payment all met; anything else is
fit_not_shown. The kit never chooses a target: every product-specific value is a required
parameter, and a missing or invalid one blocks before anything is measured. The rules, row by
row: data_dictionary.md (same folder).

    python3 pmf_kit.py setup PARAMS DATA_DIR    stage the inputs under state/pmf/input/, validate
                                                and measure; writes state/pmf/setup.json,
                                                metrics.json, facts.json, facts.md, rejected.csv
    python3 pmf_kit.py measure PARAMS DATA_DIR  validate and measure without writing anything;
                                                prints the metrics (exit 1, with the problems,
                                                when blocked)
    python3 pmf_kit.py check [--dry-run]        check state/pmf/interpretation.json against the
                                                facts (interpretation_contract.md); writes
                                                check.json unless --dry-run
    python3 pmf_kit.py finalize                 final status, state/pmf/REPORT.md, result.json

Run setup, check and finalize from the run's workspace (the folder holding state/). Each prints
one JSON line last; a blocked input or a failed check is data (exit 0), not a crash.
"""

from __future__ import annotations

import bisect
import csv
import hashlib
import json
import math
import re
import shutil
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from pathlib import Path

PARAMS_SCHEMA = "pmf_evidence.params/1"
METRICS_SCHEMA = "pmf_evidence.metrics/1"
INTERPRETATION_SCHEMA = "pmf_evidence.interpretation/1"
SURVEY_BAR = Fraction(2, 5)  # the mission's bar, 40% "Very disappointed": fixed, not a parameter
Z95 = Decimal("1.96")
STATE = Path("state/pmf")
INDICATORS = ("survey", "retention", "payment", "revenue")
FIT_INDICATORS = ("survey", "retention", "payment")
FILES = {
    "users": ("user_id", ("user_id", "account_id", "started_on")),
    "activity": ("event_id", ("event_id", "user_id", "event", "occurred_on")),
    "survey": ("response_id", ("response_id", "user_id", "submitted_on", "answer")),
    "payments": ("row_id", ("row_id", "account_id", "kind", "amount", "currency", "occurred_on", "ref_row_id")),
}
ANSWERS = {"very disappointed": "very", "somewhat disappointed": "somewhat", "not disappointed": "not"}
KINDS = ("payment", "refund", "fee", "promise")
TEST_KINDS = ("wait_and_remeasure", "data_fix", "analysis", "survey", "contact", "paid")
NEEDS_OWNER = {"survey", "contact", "paid"}
STATUS_TEXT = {"met": "met", "not_met": "not met", "insufficient_evidence": "insufficient evidence"}
REASON_TEXT = {
    "data_quality": "too many rejected rows in a file it uses",
    "no_data": "no rows to measure",
    "too_few_responses": "fewer eligible respondents than the minimum",
    "below_threshold": "below 40% very disappointed",
    "too_few_periods": "fewer adequate periods than the minimum",
    "still_declining": "still declining over the last adequate periods",
    "below_plateau": "last adequate period below the floor",
    "too_few_accounts": "fewer target-price accounts than the minimum",
    "below_target": "net revenue below the target",
    "horizon_open": "the horizon has not ended",
}
LIMIT_TEXT = re.compile(r"you['\u2019]ve hit your (\w+ )?limit|usage limit reached|\b(5-hour|five-hour|weekly|session) "
                        r"limit reached|claude ai usage limit", re.I)
PLACEHOLDER = re.compile(r"^(?:todo|tbd|tbc|n/?a|none|null|unknown|placeholder|changeme|x+|\?+|\.+|-+|_+)$"
                         r"|^<.*>$|^\[.*\]$|^\{.*\}$", re.I)
PARAM_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.A)
ROW_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[T ].*)?", re.A | re.S)
MONEY = re.compile(r"\d+(?:\.\d{1,2})?", re.A)
CENT = Decimal("0.01")

# Every parameter is required and has no default. Leaf: (kind, what it means[, choices]).
PARAMS = {
    "schema": ("schema", f'always "{PARAMS_SCHEMA}"'),
    "product": ("text", "the product's name, as the report shows it"),
    "data_label": ("choice", '"synthetic" for made-up test data, "real" for a product\'s own exports',
                   ("synthetic", "real")),
    "buyer": ("text", "who pays for the product"),
    "user_unit": ("text", "what one row of users.csv is (a person, a seat, a traveller)"),
    "account_unit": ("text", "what one customer account is: the unit that pays"),
    "value_event": ("event", "the activity.csv event name that marks the core value delivered (not a login "
                             "or a page view)"),
    "observed_until": ("date", "the last day the exports cover (YYYY-MM-DD); nothing after it is known"),
    "currency": ("currency", "the three-letter code every payments.csv amount is in (USD, EUR)"),
    "survey": {
        "min_value_events": ("count", "value events a respondent needs in the look-back window to be eligible "
                                      "(whole number, at least 1)"),
        "lookback_days": ("count", "days up to and including the answer day in which those value events count "
                                   "(whole number, at least 1)"),
        "min_responses": ("count", "eligible respondents needed before the survey is judged (whole number, "
                                   "at least 1)"),
    },
    "retention": {
        "period_days": ("count", "days in one retention period, fitted to the product's usage rhythm (7 weekly, "
                                 "30 monthly, 91 quarterly, 365 yearly)"),
        "cohort_by": ("choice", "how users are grouped by start date: week, month, quarter or year",
                      ("week", "month", "quarter", "year")),
        "min_users_per_period": ("count", "users who must be fully observed in a period for it to be adequate "
                                          "(whole number, at least 1)"),
        "min_periods": ("count", "adequate periods, counted from period 1, needed before retention is judged "
                                 "(whole number, at least 1)"),
        "flat_last_periods": ("count2", "how many of the last adequate periods must be flat (whole number, 2 "
                                        "to min_periods)"),
        "flat_max_drop_pp": ("points", "largest drop, in percentage points, from the first to the last of those "
                                       "periods that still counts as flat (0 to 100)"),
        "min_plateau_rate": ("rate", "lowest share of users active in the last adequate period that still counts "
                                     "(above 0, at most 1; 0.3 means 30%)"),
    },
    "payment": {
        "target_price": ("money", 'the amount one payment must keep after refunds, in the params currency, as '
                                  'decimal text ("49.00"): the price of one billing payment'),
        "price_unit": ("text", "what the target price buys (per account per month, per household per year)"),
        "min_target_price_accounts": ("count", "customer accounts that must pay the target price in the horizon "
                                               "(whole number, at least 1)"),
    },
    "revenue": {
        "target": ("money", 'net revenue to collect in the horizon, as decimal text ("1500.00")'),
        "horizon_start": ("date", "first day of the payment and revenue horizon (YYYY-MM-DD)"),
        "horizon_end": ("date", "last day of the payment and revenue horizon (YYYY-MM-DD, not before "
                                "horizon_start)"),
    },
    "data_quality": {
        "max_rejected_share": ("share", "largest share of a file's rows that may be rejected before the "
                                        "indicators using that file are not judged (0 to below 1; 0.05 means 5%)"),
    },
}


# ---------------------------------------------------------------- small helpers

def problem(code: str, field: str, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def problem_text(item: dict) -> str:
    return f"{item['code']} {item['field']}: {item['message']}"


def pct(frac: Fraction) -> str:
    """A share as a percentage with one decimal, rounded half up ("43.8")."""
    value = Decimal(frac.numerator) * 100 / Decimal(frac.denominator)
    return str(value.quantize(Decimal("0.1"), ROUND_HALF_UP))


def money(value: Decimal) -> str:
    return str(value.quantize(CENT, ROUND_HALF_UP))


def count(n: int, word: str) -> str:
    """A count with its noun: "1 row", "2 rows" (the noun's last word takes the plural s)."""
    return f"{n} {word if n == 1 else word + 's'}"


def number_text(value) -> str:
    """A parameter number as written (5 -> "5", 5.0 -> "5", 0.3 -> "0.3")."""
    return format(Decimal(str(value)).normalize(), "f")


def wilson(k: int, n: int) -> list[str]:
    """95% Wilson score interval for k of n, in percent with one decimal (exact decimal arithmetic)."""
    with localcontext() as ctx:
        ctx.prec = 50
        z2 = Z95 * Z95
        big_k, big_n = Decimal(k), Decimal(n)
        root = Z95 * (z2 + 4 * big_k * (big_n - big_k) / big_n).sqrt()
        den = 2 * (big_n + z2)
        tenth = Decimal("0.1")
        return [str(((2 * big_k + z2 - root) / den * 100).quantize(tenth, ROUND_HALF_UP)),
                str(((2 * big_k + z2 + root) / den * 100).quantize(tenth, ROUND_HALF_UP))]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def read_json(path: Path):
    return json.loads(path.read_text())


def say(data: dict) -> int:
    print(json.dumps(data, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- parameters

def param_date(value):
    if not isinstance(value, str) or not PARAM_DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def leaf_ok(rule: tuple, value) -> bool:
    kind = rule[0]
    if kind == "schema":
        return value == PARAMS_SCHEMA
    if kind in ("text", "event"):
        if not isinstance(value, str) or not value.strip() or PLACEHOLDER.match(value.strip()):
            return False
        return kind == "text" or value == value.strip()
    if kind == "choice":
        return isinstance(value, str) and value in rule[2]
    if kind == "date":
        return param_date(value) is not None
    if kind == "currency":
        return isinstance(value, str) and re.fullmatch(r"[A-Z]{3}", value) is not None
    if kind in ("count", "count2"):
        return isinstance(value, int) and not isinstance(value, bool) and value >= (2 if kind == "count2" else 1)
    if kind == "money":
        return isinstance(value, str) and MONEY.fullmatch(value) is not None and Decimal(value) > 0
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
    if kind == "points":
        return 0 <= value <= 100
    if kind == "rate":
        return 0 < value <= 1
    return 0 <= value < 1  # share


def validate_params(raw) -> list[dict]:
    """Every problem with the parameters, sorted by (code, field). Nothing is defaulted."""
    if not isinstance(raw, dict):
        return [problem("invalid_param", "(params file)", "the params file must hold one JSON object; start from "
                                                          "templates/params.json")]
    problems: list[dict] = []

    def walk(spec: dict, given: dict, prefix: str) -> None:
        for key in given:
            if key not in spec:
                problems.append(problem("unknown_param", prefix + key,
                                        f"not a parameter of {PARAMS_SCHEMA} (misspelt?); remove or rename it"))
        for key, rule in spec.items():
            field = prefix + key
            value = given.get(key)
            if isinstance(rule, dict):
                if value is None:
                    problems.append(problem("missing_param", field, "the whole block is missing; it needs "
                                            + ", ".join(f"{field}.{k}" for k in rule)))
                elif not isinstance(value, dict):
                    problems.append(problem("invalid_param", field, "must be an object with "
                                            + ", ".join(f"{field}.{k}" for k in rule)))
                else:
                    walk(rule, value, field + ".")
            elif value is None:
                problems.append(problem("missing_param", field, f"required, no default: {rule[1]}"))
            elif not leaf_ok(rule, value):
                problems.append(problem("invalid_param", field, f"is {json.dumps(value)}; it must be {rule[1]}"))

    walk(PARAMS, raw, "")
    bad = {item["field"] for item in problems}
    retention, revenue = raw.get("retention"), raw.get("revenue")
    if isinstance(retention, dict) and not bad & {"retention", "retention.flat_last_periods", "retention.min_periods"} \
            and retention["flat_last_periods"] > retention["min_periods"]:
        problems.append(problem("invalid_param", "retention.flat_last_periods",
                                f"is {retention['flat_last_periods']} but min_periods is {retention['min_periods']}; "
                                "the flat window must fit inside the adequate periods"))
    if isinstance(revenue, dict) and not bad & {"revenue", "revenue.horizon_start", "revenue.horizon_end"} \
            and param_date(revenue["horizon_end"]) < param_date(revenue["horizon_start"]):
        problems.append(problem("invalid_param", "revenue.horizon_end",
                                f"is {revenue['horizon_end']}, before horizon_start {revenue['horizon_start']}"))
    return sorted(problems, key=lambda item: (item["code"], item["field"]))


# ---------------------------------------------------------------- exports

def read_export(folder: Path, name: str):
    """(rows, problems, extra_columns). File-level problems block the run; row problems never do."""
    _, fields = FILES[name]
    label = f"{name}.csv"
    path = folder / label
    if not path.is_file():
        return [], [problem("missing_file", label, "not in the data folder; give it with this header even when it "
                            "has no rows: " + ",".join(fields))], []
    rows = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header is None:
                return [], [problem("unreadable_file", label, "the file is empty; it needs at least the header row "
                                    + ",".join(fields))], []
            header = [cell.strip() for cell in header]
            named = [column for column in header if column]
            problems = [problem("duplicate_column", label, f"column {column} appears more than once")
                        for column in sorted({c for c in named if named.count(c) > 1})]
            problems += [problem("missing_column", label, f"column {column} is missing; the header must have "
                                 + ",".join(fields)) for column in fields if column not in header]
            if problems:
                return [], problems, []
            where = {column: header.index(column) for column in fields}
            for cells in reader:
                if not cells:
                    continue  # a blank line
                row = {column: cells[i].strip() if i < len(cells) else "" for column, i in where.items()}
                row["_line"] = reader.line_num
                row["_extra"] = max(0, len(cells) - len(header))
                rows.append(row)
    except (UnicodeDecodeError, csv.Error) as exc:
        return [], [problem("unreadable_file", label, f"cannot be read as UTF-8 CSV: {exc}")], []
    extra = [column for column in header if column and column not in fields]
    return rows, [], extra


def row_day(text: str):
    match = ROW_DATE.fullmatch(text)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def first_pass(rows: list, name: str, rejected: list):
    """Rows with extra cells or no id are rejected; copies by id: exact ones dropped, differing ones all
    rejected. Returns (kept rows, exact duplicates dropped)."""
    idf, fields = FILES[name]
    usable, groups = [], {}
    for row in rows:
        if row["_extra"]:
            reject(rejected, name, row, "extra_cells", f"{row['_extra']} more cell(s) than the header")
        elif not row[idf]:
            reject(rejected, name, row, "missing_value", f"{idf} is empty")
        else:
            usable.append(row)
            groups.setdefault(row[idf], []).append(row)
    keep, dropped = [], 0
    for row in usable:
        group = groups[row[idf]]
        if any(tuple(g[f] for f in fields) != tuple(group[0][f] for f in fields) for g in group):
            reject(rejected, name, row, "conflicting_duplicate",
                   f"{idf} {row[idf]} appears {len(group)} times with different values")
        elif row is not group[0]:
            dropped += 1
        else:
            keep.append(row)
    return keep, dropped


def reject(rejected: list, name: str, row: dict, code: str, detail: str) -> None:
    rejected.append({"file": f"{name}.csv", "line": row["_line"], "id": row[FILES[name][0]], "code": code,
                     "detail": detail})


def missing(row: dict, fields) -> list:
    return [f for f in fields if not row[f]]


# ---------------------------------------------------------------- measurement

def measure(params: dict, exports: dict) -> tuple[dict, list]:
    """All metrics for valid params and readable exports. Returns (metrics, rejected rows)."""
    until = date.fromisoformat(params["observed_until"])
    value_event = params["value_event"]
    limit = Fraction(Decimal(str(params["data_quality"]["max_rejected_share"])))
    rejected: dict[str, list] = {name: [] for name in FILES}
    dropped: dict[str, int] = {}

    # users
    keep, dropped["users"] = first_pass(exports["users"], "users", rejected["users"])
    users: dict[str, tuple] = {}
    for row in keep:
        empty = missing(row, FILES["users"][1])
        start = row_day(row["started_on"]) if not empty else None
        if empty:
            reject(rejected["users"], "users", row, "missing_value", "empty: " + ", ".join(empty))
        elif start is None:
            reject(rejected["users"], "users", row, "bad_date", f"started_on {row['started_on']!r} is not YYYY-MM-DD")
        elif start > until:
            reject(rejected["users"], "users", row, "after_observation_end", f"started_on {start} is after {until}")
        else:
            users[row["user_id"]] = (row["account_id"], start)

    # activity
    keep, dropped["activity"] = first_pass(exports["activity"], "activity", rejected["activity"])
    events: dict[str, list] = {}
    value_count = other_count = 0
    for row in keep:
        reason = row_problem(row, "activity", "occurred_on", until, users)
        if reason:
            reject(rejected["activity"], "activity", row, *reason)
        elif row["event"] == value_event:
            events.setdefault(row["user_id"], []).append(row_day(row["occurred_on"]))
            value_count += 1
        else:
            other_count += 1
    for days in events.values():
        days.sort()

    # survey
    keep, dropped["survey"] = first_pass(exports["survey"], "survey", rejected["survey"])
    responses = []
    for row in keep:
        reason = row_problem(row, "survey", "submitted_on", until, users)
        answer = " ".join(row["answer"].lower().replace("_", " ").replace("-", " ").split())
        if reason:
            reject(rejected["survey"], "survey", row, *reason)
        elif answer not in ANSWERS:
            reject(rejected["survey"], "survey", row, "bad_answer",
                   f"answer {row['answer']!r} is not very_disappointed, somewhat_disappointed or not_disappointed")
        else:
            responses.append((row_day(row["submitted_on"]), row["_line"], row["user_id"], ANSWERS[answer]))

    # payments
    keep, dropped["payments"] = first_pass(exports["payments"], "payments", rejected["payments"])
    accounts = {account for account, _ in users.values()}
    money_rows: dict[str, dict] = {}
    pending = []
    for row in keep:
        empty = missing(row, FILES["payments"][1][:-1])
        when = row_day(row["occurred_on"]) if not empty else None
        amount = Decimal(row["amount"]) if MONEY.fullmatch(row["amount"]) else None
        if empty:
            reason = ("missing_value", "empty: " + ", ".join(empty))
        elif when is None:
            reason = ("bad_date", f"occurred_on {row['occurred_on']!r} is not YYYY-MM-DD")
        elif when > until:
            reason = ("after_observation_end", f"occurred_on {when} is after {until}")
        elif row["kind"] not in KINDS:
            reason = ("unknown_kind", f"kind {row['kind']!r} is not payment, refund, fee or promise")
        elif amount is None or amount <= 0:
            reason = ("bad_amount", f"amount {row['amount']!r} is not a positive decimal with at most 2 places")
        elif row["currency"] != params["currency"]:
            reason = ("currency_mismatch", f"currency {row['currency']!r} is not {params['currency']}")
        elif row["account_id"] not in accounts:
            reason = ("unknown_account", f"account {row['account_id']} has no user in users.csv")
        elif row["kind"] in ("payment", "promise") and row["ref_row_id"]:
            reason = ("unexpected_reference", f"a {row['kind']} row must not reference another row")
        else:
            reason = None
        if reason:
            reject(rejected["payments"], "payments", row, *reason)
            continue
        item = {"id": row["row_id"], "account": row["account_id"], "kind": row["kind"], "amount": amount,
                "when": when, "ref": row["ref_row_id"], "line": row["_line"], "row": row}
        if row["kind"] in ("payment", "promise"):
            money_rows[row["row_id"]] = item
        else:
            pending.append(item)
    refunded: dict[str, Decimal] = {}
    fees: dict[str, Decimal] = {}
    for item in sorted(pending, key=lambda i: (i["when"], i["line"])):
        target = money_rows.get(item["ref"])
        if target is None or target["kind"] != "payment" or target["account"] != item["account"]:
            reject(rejected["payments"], "payments", item["row"], "bad_reference",
                   f"ref_row_id {item['ref']!r} is not a payment row of account {item['account']}")
        elif item["when"] < target["when"]:
            reject(rejected["payments"], "payments", item["row"], "before_referenced_payment",
                   f"dated {item['when']}, before payment {target['id']} on {target['when']}")
        elif item["kind"] == "refund" and refunded.get(item["ref"], Decimal(0)) + item["amount"] > target["amount"]:
            reject(rejected["payments"], "payments", item["row"], "refund_exceeds_payment",
                   f"refunds of {target['id']} would exceed its {money(target['amount'])}")
        elif item["kind"] == "refund":
            refunded[item["ref"]] = refunded.get(item["ref"], Decimal(0)) + item["amount"]
        else:
            fees[item["ref"]] = fees.get(item["ref"], Decimal(0)) + item["amount"]

    files, over = {}, {}
    for name in FILES:
        counts: dict[str, int] = {}
        for item in rejected[name]:
            counts[item["code"]] = counts.get(item["code"], 0) + 1
        rows = len(exports[name])
        over[name] = rows > 0 and Fraction(len(rejected[name]), rows) > limit
        files[name] = {"rows": rows, "duplicates": dropped[name], "rejected": dict(sorted(counts.items())),
                       "over_limit": over[name], "rejected_total": len(rejected[name]),
                       "rejected_pct": pct(Fraction(len(rejected[name]), rows)) if rows else None}

    survey = measure_survey(params, files, over, users, events, responses)
    retention = measure_retention(params, files, over, users, events, until)
    payment, revenue = measure_money(params, files, over, money_rows, refunded, fees, until)
    met = [name for name in FIT_INDICATORS if {"survey": survey, "retention": retention,
                                                "payment": payment}[name]["status"] == "met"]
    metrics = {
        "schema": METRICS_SCHEMA, "product": params["product"], "data_label": params["data_label"],
        "observed_until": params["observed_until"], "currency": params["currency"],
        "verdict": "fit_indicators_met" if len(met) == 3 else "fit_not_shown", "fit_indicators_met": len(met),
        "files": files,
        "counts": {"users": len(users), "accounts": len({a for a, _ in users.values()}), "value_events": value_count,
                   "other_events": other_count},
        "survey": survey, "retention": retention, "payment": payment, "revenue": revenue,
    }
    flat = sorted((item for name in FILES for item in rejected[name]), key=lambda i: (i["file"], i["line"]))
    return metrics, flat


def row_problem(row: dict, name: str, day_field: str, until: date, users: dict):
    """The first rule an activity or survey row breaks, or None."""
    empty = missing(row, FILES[name][1])
    if empty:
        return "missing_value", "empty: " + ", ".join(empty)
    when = row_day(row[day_field])
    if when is None:
        return "bad_date", f"{day_field} {row[day_field]!r} is not YYYY-MM-DD"
    if when > until:
        return "after_observation_end", f"{day_field} {when} is after {until}"
    if row["user_id"] not in users:
        return "unknown_user", f"user {row['user_id']} is not a kept row of users.csv"
    if when < users[row["user_id"]][1]:
        return "before_user_start", f"{day_field} {when} is before the user started on {users[row['user_id']][1]}"
    return None


def measure_survey(params, files, over, users, events, responses) -> dict:
    rules = params["survey"]
    first: dict[str, tuple] = {}
    for item in sorted(responses):
        first.setdefault(item[2], item)
    answers = {"very": 0, "somewhat": 0, "not": 0}
    all_very = eligible = 0
    for when, _, user, answer in first.values():
        all_very += answer == "very"
        days = events.get(user, [])
        start = when - timedelta(days=rules["lookback_days"])
        if bisect.bisect_right(days, when) - bisect.bisect_right(days, start) >= rules["min_value_events"]:
            eligible += 1
            answers[answer] += 1
    reasons = []
    if over["users"] or over["activity"] or over["survey"]:
        reasons.append("data_quality")
    if files["survey"]["rows"] == 0:
        reasons.append("no_data")
    elif eligible < rules["min_responses"]:
        reasons.append("too_few_responses")
    if reasons:
        status = "insufficient_evidence"
    elif Fraction(answers["very"], eligible) >= SURVEY_BAR:
        status = "met"
    else:
        status, reasons = "not_met", ["below_threshold"]
    return {"status": status, "reasons": reasons, "valid": len(responses), "repeat": len(responses) - len(first),
            "first": len(first), "eligible": eligible, "ineligible": len(first) - eligible, **answers,
            "share_pct": pct(Fraction(answers["very"], eligible)) if eligible else None,
            "interval_pct": wilson(answers["very"], eligible) if eligible else None,
            "more_needed": max(0, rules["min_responses"] - eligible),
            "all_very": all_very, "all_share_pct": pct(Fraction(all_very, len(first))) if first else None}


def cohort_label(day: date, by: str) -> str:
    if by == "week":
        year, week, _ = day.isocalendar()
        return f"{year}-W{week:02d}"
    if by == "month":
        return f"{day.year}-{day.month:02d}"
    if by == "quarter":
        return f"{day.year}-Q{(day.month - 1) // 3 + 1}"
    return str(day.year)


def measure_retention(params, files, over, users, events, until) -> dict:
    rules = params["retention"]
    length = rules["period_days"]
    full = {u: ((until - start).days + 1) // length for u, (_, start) in users.items()}
    active = {u: {(day - users[u][1]).days // length for day in events.get(u, [])} for u in users}
    top = max(full.values(), default=0)
    curve = []
    for k in range(top):
        seen = [u for u in users if full[u] > k]
        curve.append([k, len(seen), sum(1 for u in seen if k in active[u])])
    adequate = 0
    for k, seen, _ in curve:
        if k >= 1 and seen >= rules["min_users_per_period"]:
            adequate = k
    reasons = []
    if over["users"] or over["activity"]:
        reasons.append("data_quality")
    if files["users"]["rows"] == 0 or files["activity"]["rows"] == 0:
        reasons.append("no_data")
    elif adequate < rules["min_periods"]:
        reasons.append("too_few_periods")
    adequate_on = None
    if "too_few_periods" in reasons:
        ends = sorted(start + timedelta(days=(rules["min_periods"] + 1) * length - 1) for _, start in users.values())
        if len(ends) >= rules["min_users_per_period"]:
            adequate_on = ends[rules["min_users_per_period"] - 1].isoformat()
    window = drop = last = first_pct = None
    if reasons:
        status = "insufficient_evidence"
    else:
        a, b = adequate - rules["flat_last_periods"] + 1, adequate
        first_rate = Fraction(curve[a][2], curve[a][1])
        last_rate = Fraction(curve[b][2], curve[b][1])
        fall = (first_rate - last_rate) * 100
        window, drop, last, first_pct = [a, b], pct(fall / 100), pct(last_rate), pct(first_rate)
        bad = []
        if fall > Fraction(Decimal(str(rules["flat_max_drop_pp"]))):
            bad.append("still_declining")
        if last_rate < Fraction(Decimal(str(rules["min_plateau_rate"]))):
            bad.append("below_plateau")
        status, reasons = ("not_met", bad) if bad else ("met", [])
    cohorts = {}
    for u, (_, start) in sorted(users.items(), key=lambda item: (item[1][1], item[0])):
        cohorts.setdefault(cohort_label(start, rules["cohort_by"]), []).append(u)
    cohort_rows = []
    for label, members in cohorts.items():
        periods = max(full[u] for u in members)
        rows = []
        for k in range(periods):
            seen = [u for u in members if full[u] > k]
            rows.append([k, len(seen), sum(1 for u in seen if k in active[u])])
        cohort_rows.append({"cohort": label, "users": len(members), "full_periods": periods, "curve": rows})
    censored_users = sum(1 for _, start in users.values() if ((until - start).days + 1) % length)
    censored_events = sum(1 for u in users for day in events.get(u, []) if (day - users[u][1]).days // length >= full[u])
    return {"status": status, "reasons": reasons, "users": len(users), "curve": curve, "adequate_periods": adequate,
            "window": window, "drop_pp": drop, "last_pct": last, "first_pct": first_pct, "adequate_on": adequate_on,
            "period_days": length, "cohorts": cohort_rows, "censored_users": censored_users,
            "censored_value_events": censored_events}


def measure_money(params, files, over, money_rows, refunded, fees, until) -> tuple[dict, dict]:
    pay, rev = params["payment"], params["revenue"]
    start, end = date.fromisoformat(rev["horizon_start"]), date.fromisoformat(rev["horizon_end"])
    complete = end <= until
    last = min(end, until)
    payments = [g for g in money_rows.values() if g["kind"] == "payment"]
    inside = [g for g in payments if start <= g["when"] <= last]
    outside = [g for g in payments if not start <= g["when"] <= last]
    promises = [g for g in money_rows.values() if g["kind"] == "promise" and start <= g["when"] <= last]
    price = Decimal(pay["target_price"])
    at_price, paying, every, before = set(), set(), set(), set()
    for g in inside:
        kept = g["amount"] - refunded.get(g["id"], Decimal(0))
        every.add(g["account"])
        if kept > 0:
            paying.add(g["account"])
        if kept >= price:
            at_price.add(g["account"])
        if g["amount"] >= price:
            before.add(g["account"])
    gross = sum((g["amount"] for g in inside), Decimal(0))
    back = sum((refunded.get(g["id"], Decimal(0)) for g in inside), Decimal(0))
    cost = sum((fees.get(g["id"], Decimal(0)) for g in inside), Decimal(0))
    net = gross - back - cost
    base = []
    if over["users"] or over["payments"]:
        base.append("data_quality")
    if files["payments"]["rows"] == 0:
        base.append("no_data")

    def judge(reached: bool, short: str):
        if base:
            return "insufficient_evidence", list(base)
        if reached:
            return "met", []
        return ("not_met", [short]) if complete else ("insufficient_evidence", ["horizon_open"])

    pay_status, pay_reasons = judge(len(at_price) >= pay["min_target_price_accounts"], "too_few_accounts")
    rev_status, rev_reasons = judge(net >= Decimal(rev["target"]), "below_target")
    payment = {"status": pay_status, "reasons": pay_reasons, "target_accounts": len(at_price),
               "paying_accounts": len(paying), "below_target_accounts": len(paying - at_price),
               "fully_refunded_accounts": len(every - paying), "target_accounts_before_refunds": len(before),
               "payments_in_horizon": len(inside)}
    revenue = {"status": rev_status, "reasons": rev_reasons, "gross": money(gross), "refunds": money(back),
               "fees": money(cost), "net": money(net), "promises": len(promises),
               "promised": money(sum((g["amount"] for g in promises), Decimal(0))),
               "outside_horizon": len(outside), "outside_amount": money(sum((g["amount"] for g in outside), Decimal(0))),
               "horizon_complete": complete, "counted_until": last.isoformat()}
    return payment, revenue


def evaluate(params_path: Path, data_dir: Path) -> tuple:
    """(params, problems, metrics, rejected). Problems block: then metrics is None."""
    problems = []
    try:
        params = json.loads(params_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        params = None
        problems.append(problem("unreadable_file", "params.json", f"cannot be read as JSON: {exc}"))
    if params is not None:
        problems += validate_params(params)
    exports = {}
    for name in FILES:
        rows, trouble, _ = read_export(data_dir, name)
        exports[name] = rows
        problems += trouble
    if problems:
        return params, problems, None, []
    metrics, rejected = measure(params, exports)
    for name in FILES:
        metrics["files"][name]["extra_columns"] = read_export(data_dir, name)[2]
    return params, problems, metrics, rejected


# ---------------------------------------------------------------- facts

def status_line(section: dict) -> str:
    text = f"Status: {STATUS_TEXT[section['status']]}"
    if section["reasons"]:
        text += " (" + "; ".join(REASON_TEXT[r] for r in section["reasons"]) + ")"
    return text + "."


def build_facts(params: dict, m: dict) -> list[dict]:
    """Numbered facts the interpretation must cite; every number it uses must be in a cited fact."""
    facts = []

    def add(about: str, text: str) -> None:
        facts.append({"id": f"F{len(facts) + 1}", "about": about, "text": text})

    unit, cur, ev = params["user_unit"], params["currency"], params["value_event"]
    add("scope", f"Data label: {params['data_label']}. Product: {params['product']}. Buyer: {params['buyer']}. "
                 f"User unit: {unit}. Customer account unit: {params['account_unit']}. Core value event: {ev}. "
                 f"The exports cover up to {m['observed_until']}; nothing after that day is known. Currency: {cur}.")
    limit = pct(Fraction(Decimal(str(params["data_quality"]["max_rejected_share"]))))
    for name in FILES:
        f = m["files"][name]
        if f["rows"] == 0:
            add(f"file {name}", f"{name}.csv: 0 rows (no data).")
            continue
        text = (f"{name}.csv: {count(f['rows'], 'row')}; {count(f['duplicates'], 'exact duplicate row')} dropped; "
                f"{count(f['rejected_total'], 'row')} rejected ({f['rejected_pct']}% of rows; limit {limit}%)")
        if f["rejected"]:
            text += ": " + ", ".join(f"{code} {n}" for code, n in f["rejected"].items())
        if f["over_limit"]:
            text += "; over the limit, so the indicators that use this file are not judged"
        add(f"file {name}", text + ".")
    c = m["counts"]
    add("users and events", f"{count(c['users'], 'user')} kept in {count(c['accounts'], 'customer account')}; "
                            f"{count(c['value_events'], ev + ' event')} and {count(c['other_events'], 'other event')} "
                            "kept.")
    s, rules = m["survey"], params["survey"]
    add("survey sample", f"Survey: {count(s['valid'], 'valid response')} from {count(s['first'], 'respondent')}; "
                         f"{count(s['repeat'], 'repeat answer')} set aside (a respondent's first answer counts). "
                         f"Eligible respondents (at least {count(rules['min_value_events'], ev + ' event')} in the "
                         f"{rules['lookback_days']} days up to their answer): {s['eligible']}; not eligible: "
                         f"{s['ineligible']}.")
    if s["eligible"]:
        text = (f"Of {s['eligible']} eligible respondents, {s['very']} answered very disappointed ({s['share_pct']}%; "
                f"95% Wilson interval {s['interval_pct'][0]}% to {s['interval_pct'][1]}%), {s['somewhat']} somewhat "
                f"disappointed and {s['not']} not disappointed.")
    else:
        text = "No eligible respondents: the very-disappointed share is undefined."
    text += (f" Rule: met when at least 40% of eligible respondents answer very disappointed, with at least "
             f"{rules['min_responses']} eligible respondents. {status_line(s)}")
    if s["more_needed"]:
        text += f" {s['more_needed']} more eligible respondents are needed."
    add("survey result", text)
    if s["first"]:
        add("survey context", f"Counting all {s['first']} first answers, eligible or not, {s['all_very']} were very "
                              f"disappointed ({s['all_share_pct']}%); this context share is not the indicator.")
    r, rr = m["retention"], params["retention"]
    if r["curve"]:
        add("retention curve", f"Retention: share of users with at least one {ev} event in each "
                               f"{r['period_days']}-day period after they started, fully observed periods only: "
                               + "; ".join(f"period {k}: {a} of {n} ({pct(Fraction(a, n))}%)" for k, n, a in r["curve"])
                               + ".")
    else:
        add("retention curve", f"Retention: no fully observed {r['period_days']}-day period (no users or no data).")
    if r["cohorts"]:
        add("retention cohorts", f"Retention by cohort ({rr['cohort_by']} the user started), fully observed periods "
                                 "only: " + "; ".join(
            f"{co['cohort']}: {count(co['users'], 'user')}, {count(co['full_periods'], 'full period')} observed"
            + (": " + ", ".join(f"period {k}: {a} of {n} ({pct(Fraction(a, n))}%)" for k, n, a in co["curve"])
               if co["curve"] else "")
            for co in r["cohorts"]) + ".")
    add("retention censoring", f"Censoring: {count(r['censored_users'], 'user')} "
                               f"{'has' if r['censored_users'] == 1 else 'have'} a partly observed last period and "
                               f"{count(r['censored_value_events'], ev + ' event')} "
                               f"{'falls' if r['censored_value_events'] == 1 else 'fall'} in partly observed periods; "
                               "these are not counted. Users not yet observed for a period are left out of its "
                               "denominator, never counted as lost.")
    text = (f"Adequate periods (from period 1, at least {rr['min_users_per_period']} users fully observed): "
            f"{r['adequate_periods']}; at least {rr['min_periods']} needed.")
    if r["window"]:
        a, b = r["window"]
        text += (f" Flat window: periods {a} to {b}: from {r['first_pct']}% to {r['last_pct']}%, a drop of "
                 f"{r['drop_pp']} percentage points; last period {r['last_pct']}%.")
    text += (f" Rule: met when there are at least {rr['min_periods']} adequate periods and, over the last "
             f"{rr['flat_last_periods']} adequate periods, the share drops by at most "
             f"{number_text(rr['flat_max_drop_pp'])} percentage points and the last is at least "
             f"{pct(Fraction(Decimal(str(rr['min_plateau_rate']))))}%. {status_line(r)}")
    if "too_few_periods" in r["reasons"]:
        text += (f" Period {rr['min_periods']} will be fully observed for {rr['min_users_per_period']} users on "
                 f"{r['adequate_on']} at the earliest." if r["adequate_on"] else
                 f" Fewer than {rr['min_users_per_period']} users in total: more users must start before retention "
                 "can be judged.")
    add("retention judgement", text)
    p, pp, rv, rp = m["payment"], params["payment"], m["revenue"], params["revenue"]
    span = f"between {rp['horizon_start']} and {rv['counted_until']}"
    text = (f"Payment: {p['target_accounts']} customer accounts kept a payment of at least the target price "
            f"{pp['target_price']} {cur} ({pp['price_unit']}) after refunds, {span}; {p['paying_accounts']} accounts "
            f"kept some payment, {p['below_target_accounts']} only below the target price, "
            f"{p['fully_refunded_accounts']} were fully refunded; before refunds, "
            f"{p['target_accounts_before_refunds']} accounts had a payment at the target price. Rule: met with at "
            f"least {pp['min_target_price_accounts']} such accounts by {rp['horizon_end']}. {status_line(p)}")
    add("payment", text)
    state = ("horizon complete" if rv["horizon_complete"] else
             f"horizon open: it ends {rp['horizon_end']}, after the data ends on {m['observed_until']}")
    add("revenue", f"Revenue {span} ({state}): gross receipts {rv['gross']} {cur}, refunds {rv['refunds']}, payment "
                   f"fees {rv['fees']}, net collected {rv['net']}; target {rp['target']} {cur} net by "
                   f"{rp['horizon_end']}. {status_line(rv)}")
    add("promises and outside payments", f"Promises (not money, never counted): {count(rv['promises'], 'row')}, "
                                         f"{rv['promised']} {cur}. Payments outside the horizon (not counted): "
                                         f"{count(rv['outside_horizon'], 'row')}, {rv['outside_amount']} {cur}.")
    text = (f"Fit indicators met: {m['fit_indicators_met']} of 3 (survey {STATUS_TEXT[s['status']]}, retention "
            f"{STATUS_TEXT[r['status']]}, payment {STATUS_TEXT[p['status']]}); revenue "
            f"{STATUS_TEXT[rv['status']]} is reported apart. Verdict: {m['verdict']}. Rule: fit_indicators_met needs "
            "survey, retention and payment all met; the survey alone never shows product-market fit.")
    if params["data_label"] == "synthetic":
        text += " The data is synthetic, so nothing here is evidence about any product."
    add("verdict", text)
    return facts


def facts_markdown(facts: list) -> str:
    return "# Facts (cite these ids)\n\n" + "\n".join(f"- **{f['id']}** ({f['about']}): {f['text']}" for f in facts) + "\n"


# ---------------------------------------------------------------- interpretation check

NUMBER = re.compile(r"(?<![\w.])(\d{4}-\d{2}-\d{2}|\d+(?:,\d{3})*(?:\.\d+)?)(?!\w)")
FIT_MENTION = re.compile(r"product[\s\-\u2010-\u2015]*market[\s\-\u2010-\u2015]*fit|\bPMF\b", re.I)
FIT_VERB = re.compile(r"\b(?:has|have|had|achiev\w*|reach\w*|found|find\w*|prov\w*|confirm\w*|establish\w*|"
                      r"demonstrat\w*|show\w*|reveal\w*|indicat\w*)\s+(?:a\s+|clear\s+|strong\s+)?fit\b(?!\s+indicator)",
                      re.I)
NEGATION = re.compile(r"\b(?:not|no|never|cannot|can['\u2019]t|doesn['\u2019]t|does not|isn['\u2019]t|aren['\u2019]t|"
                      r"without|nor|neither|insufficient|unproven|too early)\b", re.I)
SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+|\n+")


def numbers(text: str) -> set:
    found = set()
    for token in NUMBER.findall(text):
        if "-" in token:
            found.add(token)
            continue
        token = token.replace(",", "")
        whole, _, frac = token.partition(".")
        frac = frac.rstrip("0")
        found.add((whole.lstrip("0") or "0") + ("." + frac if frac else ""))
    return found


def fit_claims(text: str) -> list:
    """Sentences that claim product-market fit (a mention or a fit verb with no negation)."""
    return [s.strip() for s in SENTENCE_END.split(text)
            if (FIT_MENTION.search(s) or FIT_VERB.search(s)) and not NEGATION.search(s)]


SPAN_RANGE = (r"(?:periods\s+(\d+)\s*(to|through|and|-|–)\s*(\d+)"
              r"|period\s+(\d+)\s*(to|through|and|-|–)\s*period\s+(\d+))(?![\d.%])")
SPAN_AFTER = (
    ("range", re.compile(r"\)?\s*(from|in|for|over|across|between)?\s*" + SPAN_RANGE, re.I)),
    ("every", re.compile(r"\)?\s*(?:in|for)\s+(?:every|each|all)\s+periods?\s+(after|from|since)\s+period\s+(\d+)"
                         r"(?![\d.%])", re.I)),
    ("open", re.compile(r"\)?\s*(?:from|since)\s+period\s+(\d+)(?![\d.%])", re.I)),
    ("through", re.compile(r"\)?\s*(?:through|until|up to)\s+period\s+(\d+)(?![\d.%])", re.I)),
)
SPAN_BEFORE = re.compile(r"(?:^|\s)()" + SPAN_RANGE + r"\s+(?:hold|holds|held|stay|stays|stayed|sit|sits|sat|remain|"
                         r"remains|remained)\s+(?:flat\s+|steady\s+)?at\s+(?:\d+\s+of\s+\d+\s+\()?$", re.I)
LAST_PERIOD = re.compile(r"\bperiods?\s+(\d+)(?:\s*(?:to|through|and|-|–)\s*(?:period\s+)?(\d+))?", re.I)
CLAUSE_END = re.compile(r";|\.(?!\d)")
SHARE = re.compile(r"(\d+(?:\.\d+)?)%")


def span_of(groups) -> tuple:
    """(first, last, only) from a SPAN_RANGE match: "periods 1 and 2" lists two periods, the rest are ranges."""
    prep, *nums = groups
    a, joiner, b = nums[:3] if nums[0] is not None else nums[3:]
    a, b = int(a), int(b)
    return a, b, ({a, b} if joiner == "and" and prep != "between" else None), False


def span_claims(text: str, retention: dict) -> list:
    """Clauses that give one share for a span of periods ("holds at 53.3% from period 3 to period 11") where the
    curve, or each cohort the clause names, does not have that share in every period of the span. A period that
    differs is fine when the clause names it with its own share ("(50.0% in period 10)"). "Through period b" starts
    at the last period named before the share, or the one after it when that period has another share."""
    out = []
    for clause in CLAUSE_END.split(text):
        named = [co for co in retention["cohorts"]
                 if re.search(rf"(?<![\w-]){re.escape(co['cohort'])}(?![\w-])", clause)]
        curves = [(f"cohort {co['cohort']}", co["curve"]) for co in named] or [("the curve", retention["curve"])]
        for m in SHARE.finditer(clause):
            share, rest, before = m.group(1), clause[m.end():], clause[:m.start()]
            if re.search(r"\b(?:to|from)\s*$", before, re.I):
                continue  # one end of a movement ("from 40.0% to 23.3% over periods 9 to 11"), not a level held
            span = None
            for kind, pattern in SPAN_AFTER:
                hit = pattern.match(rest)
                if not hit:
                    continue
                if kind == "range":
                    span = span_of(hit.groups())
                elif kind == "every":
                    span = (int(hit.group(2)) + (hit.group(1) == "after"), None, None, False)
                elif kind == "open":
                    span = (int(hit.group(1)), None, None, False)
                else:
                    marks = LAST_PERIOD.findall(before)
                    if marks:
                        span = (int(marks[-1][1] or marks[-1][0]), int(hit.group(1)), None, True)
                break
            if span is None and (hit := SPAN_BEFORE.search(before)):
                span = span_of(hit.groups())
            if span is None:
                continue
            for name, curve in curves:
                first, last, only, after_mark = span
                if after_mark and first < len(curve) and \
                        Decimal(pct(Fraction(curve[first][2], curve[first][1]))) != Decimal(share):
                    first += 1
                end = len(curve) - 1 if last is None else last
                wrong = []
                for k in sorted(only) if only else range(first, end + 1):
                    if k >= len(curve):
                        wrong.append(f"period {k} is not observed")
                        continue
                    got = pct(Fraction(curve[k][2], curve[k][1]))
                    if Decimal(got) != Decimal(share) and not (
                            f"{got}%" in clause and re.search(rf"\bperiod\s+{k}\b", clause, re.I)):
                        wrong.append(f"period {k} is {got}% ({curve[k][2]} of {curve[k][1]})")
                if wrong:
                    said = (f"periods {first} and {last}" if only else f"period {first} on" if last is None
                            else f"periods {first} to {last}")
                    out.append(f"{share}% is given for {said} of {name}, but " + "; ".join(wrong[:4])
                               + ": name each period that differs with its share, or give the lowest and highest "
                               "share in the span")
    return out


def check_interpretation(interp, facts: list, metrics: dict, params: dict) -> list:
    """Every way interpretation.json breaks the contract (interpretation_contract.md). [] when clean."""
    out: list[str] = []
    known = {f["id"]: numbers(f["text"]) for f in facts}

    def statement(item, where: str) -> str:
        if not isinstance(item, dict) or set(item) != {"text", "facts"}:
            out.append(f"shape {where}: a statement is {{\"text\": ..., \"facts\": [...]}} and nothing else")
            return ""
        text, cited = item["text"], item["facts"]
        if not isinstance(text, str) or not text.strip() or len(text) > 600:
            out.append(f"shape {where}.text: non-empty text of at most 600 characters")
            text = text if isinstance(text, str) else ""
        traced(text, cited, where)
        return text

    def traced(text: str, cited, where: str) -> None:
        if not isinstance(cited, list) or not cited or not all(isinstance(f, str) for f in cited):
            out.append(f"shape {where}.facts: cite at least one fact id (F1, F2, ...)")
            return
        unknown = [f for f in cited if f not in known]
        if unknown:
            out.append(f"unknown_fact {where}: {', '.join(unknown)} is not in facts.json")
        allowed = set().union(*(known[f] for f in cited if f in known))
        loose = sorted(numbers(text) - allowed)
        if loose:
            out.append(f"untraced_number {where}: {', '.join(loose)} not in the cited facts ({', '.join(cited)}); "
                       "cite the fact that has it, copy it exactly as written there, or drop it")
        for claim in fit_claims(text):
            out.append(f"fit_claim {where}: \"{claim[:160]}\" reads as a claim of product-market fit")
        for claim in span_claims(text, metrics["retention"]):
            out.append(f"span_claim {where}: {claim}")

    def statements(items, where: str, low: int, high: int) -> list:
        if not isinstance(items, list) or not low <= len(items) <= high:
            out.append(f"shape {where}: a list of {low} to {high} statements")
            return []
        return [statement(item, f"{where}[{i}]") for i, item in enumerate(items)]

    if not isinstance(interp, dict):
        return ["shape interpretation: one JSON object (see interpretation_contract.md)"]
    expected = {"schema", "summary", "indicators", "data_quality", "next_tests", "limitations"}
    for key in sorted(set(interp) - expected):
        out.append(f"shape {key}: not part of {INTERPRETATION_SCHEMA}")
    for key in sorted(expected - set(interp)):
        out.append(f"shape {key}: missing")
    if interp.get("schema") != INTERPRETATION_SCHEMA:
        out.append(f"shape schema: must be \"{INTERPRETATION_SCHEMA}\"")
    summary = statements(interp.get("summary"), "summary", 1, 4)
    if params["data_label"] == "synthetic" and summary and not any("synthetic" in t.lower() for t in summary):
        out.append("synthetic summary: say in the summary that the data is synthetic and not evidence about any "
                   "product")
    indicators = interp.get("indicators")
    if not isinstance(indicators, dict) or set(indicators) != set(INDICATORS):
        out.append("shape indicators: an object with exactly survey, retention, payment and revenue")
        indicators = {}
    for name, block in indicators.items():
        if not isinstance(block, dict) or set(block) != {"status", "statements"}:
            out.append(f"shape indicators.{name}: {{\"status\": ..., \"statements\": [...]}}")
            continue
        if block["status"] != metrics[name]["status"]:
            out.append(f"status indicators.{name}.status: is {block['status']!r}, the measured status is "
                       f"{metrics[name]['status']!r}")
        statements(block["statements"], f"indicators.{name}.statements", 1, 4)
    touched = sum(f["rejected_total"] + f["duplicates"] for f in metrics["files"].values())
    statements(interp.get("data_quality"), "data_quality", 1 if touched else 0, 4)
    statements(interp.get("limitations"), "limitations", 0, 4)
    tests = interp.get("next_tests")
    if not isinstance(tests, list) or not 1 <= len(tests) <= 6:
        out.append("shape next_tests: a list of 1 to 6 tests")
        tests = []
    keys = {"id", "indicator", "kind", "test", "pass_rule", "when", "needs_owner_approval", "facts"}
    good, ids = [], set()
    for i, test in enumerate(tests):
        where = f"next_tests[{i}]"
        if not isinstance(test, dict) or set(test) != keys:
            out.append(f"shape {where}: exactly the keys " + ", ".join(sorted(keys)))
            continue
        if not isinstance(test["id"], str) or not re.fullmatch(r"T\d+", test["id"]) or test["id"] in ids:
            out.append(f"shape {where}.id: a unique id T1, T2, ...")
        ids.add(test["id"])
        if test["indicator"] not in INDICATORS + ("data",):
            out.append(f"shape {where}.indicator: one of survey, retention, payment, revenue, data")
            continue
        if test["kind"] not in TEST_KINDS:
            out.append(f"shape {where}.kind: one of " + ", ".join(TEST_KINDS))
            continue
        if not isinstance(test["needs_owner_approval"], bool):
            out.append(f"shape {where}.needs_owner_approval: true or false")
        elif test["kind"] in NEEDS_OWNER and not test["needs_owner_approval"]:
            out.append(f"owner_approval {where}: a {test['kind']} test contacts people or spends money, so "
                       "needs_owner_approval must be true")
        for field in ("test", "pass_rule", "when"):
            value = test[field]
            if not isinstance(value, str) or len(value) > 600 or (field != "when" and not value.strip()):
                out.append(f"shape {where}.{field}: text of at most 600 characters" +
                           ("" if field == "when" else ", not empty"))
            else:
                traced(value, test["facts"], f"{where}.{field}")
        good.append(test)
    status = {name: metrics[name]["status"] for name in INDICATORS}
    reasons = {r for name in INDICATORS for r in metrics[name]["reasons"]}
    if good:
        for name in INDICATORS:
            if status[name] != "met" and not any(t["indicator"] == name for t in good):
                out.append(f"coverage next_tests: {name} is {STATUS_TEXT[status[name]]}, so propose a test for it")
        if reasons & {"data_quality", "no_data"} and not any(t["kind"] == "data_fix" for t in good):
            out.append("coverage next_tests: some data is missing or over the rejection limit, so propose a "
                       "data_fix test")
        ranks = [0 if t["indicator"] == "data" or status[t["indicator"]] != "met" else 1 for t in good]
        if ranks != sorted(ranks):
            out.append("order next_tests: put tests for indicators that are not met (and data fixes) before tests "
                       "for met indicators")
        for t in good:
            if t["indicator"] != "data" and status[t["indicator"]] == "insufficient_evidence" \
                    and isinstance(t["when"], str) and not t["when"].strip():
                out.append(f"when next_tests {t['id']}: {t['indicator']} is not judged yet, so say when to "
                           "measure again")
        on = metrics["retention"]["adequate_on"]
        if on and not any(t["indicator"] == "retention" and on in str(t["when"]) for t in good):
            out.append(f"when next_tests: retention can be judged from {on}; a retention test's when must say so")
        end = params["revenue"]["horizon_end"]
        for name in ("payment", "revenue"):
            if "horizon_open" in metrics[name]["reasons"] and not any(
                    t["indicator"] == name and end in str(t["when"]) for t in good):
                out.append(f"when next_tests: the {name} horizon ends {end}; a {name} test's when must say so")
    return out


# ---------------------------------------------------------------- report

def cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def status_cell(section: dict) -> str:
    text = STATUS_TEXT[section["status"]]
    return text + (" (" + "; ".join(REASON_TEXT[r] for r in section["reasons"]) + ")" if section["reasons"] else "")


def report(params: dict, m: dict, facts: list, rejected: list, interp, final_status: str, problems: list) -> str:
    cur, ev = params["currency"], params["value_event"]
    s, r, p, rv = m["survey"], m["retention"], m["payment"], m["revenue"]
    sp, rr, pp, rp = params["survey"], params["retention"], params["payment"], params["revenue"]
    lines = [f"# Fit and revenue evidence: {params['product']}", ""]
    if params["data_label"] == "synthetic":
        lines += ["> **Synthetic example:** made-up data used to test the kit. Nothing in this report is evidence "
                  "about any product.", ""]
    else:
        lines += ["> Real exports, as given in the params file. Each figure says what it counts and what is not yet "
                  "observed.", ""]
    lines += [f"**Verdict: {m['verdict']}** ({m['fit_indicators_met']} of 3 fit indicators met). The survey alone "
              "never shows product-market fit: the verdict fit_indicators_met needs the survey, retention and payment "
              "indicators all met; revenue is reported apart.", ""]
    if final_status == "revise":
        lines += ["**Status: revise.** The interpretation did not pass its check, so it is not shown; the "
                  "measurements below stand. Problems:", ""] + [f"- {cell(x)}" for x in problems] + [""]
    lines += [f"Observed until {m['observed_until']} (nothing after this day is known). User unit: "
              f"{params['user_unit']}. Customer account unit: {params['account_unit']}. Value event: `{ev}`. "
              f"Currency: {cur}.", "", "## Indicators", "",
              "| Indicator | Status | Result | Rule |", "|---|---|---|---|"]
    if s["eligible"]:
        survey_result = (f"{s['very']} of {s['eligible']} eligible respondents very disappointed ({s['share_pct']}%; "
                         f"95% interval {s['interval_pct'][0]}% to {s['interval_pct'][1]}%)")
    else:
        survey_result = "undefined: 0 eligible respondents"
    if r["window"]:
        a, b = r["window"]
        retention_result = (f"periods {a} to {b}: {r['curve'][a][2]} of {r['curve'][a][1]} ({r['first_pct']}%) to "
                            f"{r['curve'][b][2]} of {r['curve'][b][1]} ({r['last_pct']}%), drop {r['drop_pp']} points; "
                            f"{r['adequate_periods']} adequate periods")
    else:
        retention_result = f"{r['adequate_periods']} adequate periods of {r['period_days']} days"
    floor = pct(Fraction(Decimal(str(rr["min_plateau_rate"]))))
    lines += [
        f"| Survey: very disappointed | {status_cell(s)} | {survey_result} | at least 40% of eligible respondents, "
        f"at least {sp['min_responses']} eligible |",
        f"| Retention | {status_cell(r)} | {retention_result} | at least {rr['min_periods']} adequate "
        f"{rr['period_days']}-day periods (at least {rr['min_users_per_period']} users observed); the last "
        f"{rr['flat_last_periods']} drop at most {number_text(rr['flat_max_drop_pp'])} points and end at or above "
        f"{floor}% |",
        f"| Payment at the target price | {status_cell(p)} | {p['target_accounts']} customer accounts kept a payment of "
        f"at least {pp['target_price']} {cur} ({cell(pp['price_unit'])}); {p['paying_accounts']} paying | at least "
        f"{pp['min_target_price_accounts']} accounts from {rp['horizon_start']} to {rp['horizon_end']} |",
        f"| Net revenue (reported apart) | {status_cell(rv)} | net {rv['net']} {cur} = gross {rv['gross']} - refunds "
        f"{rv['refunds']} - fees {rv['fees']} | at least {rp['target']} {cur} net from {rp['horizon_start']} to "
        f"{rp['horizon_end']} |", ""]
    lines += ["## Survey", "",
              f"Question: \"How would you feel if you could no longer use {cell(params['product'])}?\" Eligible: at "
              f"least {count(sp['min_value_events'], '`' + ev + '` event')} in the {sp['lookback_days']} days up to "
              "the answer. "
              "A respondent's first answer counts.", "",
              "| Count | Value |", "|---|---|",
              f"| valid responses | {s['valid']} |", f"| repeat answers set aside | {s['repeat']} |",
              f"| respondents (first answers) | {s['first']} |", f"| eligible respondents | {s['eligible']} |",
              f"| not eligible | {s['ineligible']} |", f"| very disappointed (eligible) | {s['very']} |",
              f"| somewhat disappointed (eligible) | {s['somewhat']} |",
              f"| not disappointed (eligible) | {s['not']} |",
              f"| very-disappointed share | {s['share_pct'] + '%' if s['share_pct'] else 'undefined'} |",
              f"| more eligible respondents needed | {s['more_needed']} |", ""]
    if s["first"]:
        lines += [f"Context only, not the indicator: of all {s['first']} first answers, {s['all_very']} were very "
                  f"disappointed ({s['all_share_pct']}%).", ""]
    lines += ["## Retention", "",
              f"Share of users with at least one `{ev}` event in each {r['period_days']}-day period after they "
              "started. Only fully observed periods count: a user not yet observed for a period is left out of its "
              "denominator, never counted as lost.", "",
              "| Period | Users fully observed | Active | Share | Not yet observed |", "|---|---|---|---|---|"]
    lines += [f"| {k} | {n} | {a} | {pct(Fraction(a, n))}% | {r['users'] - n} |" for k, n, a in r["curve"]]
    if not r["curve"]:
        lines += ["| none | 0 | 0 | undefined | 0 |"]
    lines += ["", f"Censoring: {r['censored_users']} users have a partly observed last period; "
              f"{r['censored_value_events']} `{ev}` events fall in partly observed periods and are not counted.", ""]
    if r["adequate_on"]:
        lines += [f"Retention can be judged from {r['adequate_on']}, when period {rr['min_periods']} is fully observed "
                  f"for {rr['min_users_per_period']} users.", ""]
    if r["cohorts"]:
        lines += [f"Retention by cohort ({rr['cohort_by']} the user started) and period: active users of those "
                  "fully observed for the period. Not yet observed: no user of that cohort is fully observed for it "
                  "yet.", "",
                  "| Period | " + " | ".join(f"{cell(co['cohort'])} ({count(co['users'], 'user')})"
                                         for co in r["cohorts"]) + " |",
                  "|---|" + "---|" * len(r["cohorts"])]
        for k in range(max(len(co["curve"]) for co in r["cohorts"])):
            lines.append(f"| {k} | " + " | ".join(
                f"{co['curve'][k][2]} of {co['curve'][k][1]} ({pct(Fraction(co['curve'][k][2], co['curve'][k][1]))}%)"
                if k < len(co["curve"]) else "not yet observed" for co in r["cohorts"]) + " |")
        if not any(co["curve"] for co in r["cohorts"]):
            lines.append("| none |" + " not yet observed |" * len(r["cohorts"]))
        lines.append("")
    lines += ["## Payment and revenue", "",
              f"Horizon {rp['horizon_start']} to {rp['horizon_end']}"
              + (" (complete)." if rv["horizon_complete"] else f" (open: the data ends on {m['observed_until']}; "
                 f"counted until {rv['counted_until']}).")
              + " Refunds and fees count against the payment they reference. Promises are not money.", "",
              "| Item | Rows or accounts | Amount |", "|---|---|---|",
              f"| gross receipts (payments in the horizon) | {p['payments_in_horizon']} payments | {rv['gross']} {cur} |",
              f"| refunds of those payments | | {rv['refunds']} {cur} |",
              f"| payment fees on those payments | | {rv['fees']} {cur} |",
              f"| net collected | | {rv['net']} {cur} |",
              f"| promises (not money, never counted) | {rv['promises']} rows | {rv['promised']} {cur} |",
              f"| payments outside the horizon (not counted) | {rv['outside_horizon']} rows | {rv['outside_amount']} {cur} |",
              "",
              f"Customer accounts: {p['target_accounts']} kept a payment of at least {pp['target_price']} {cur} after "
              f"refunds; {p['paying_accounts']} kept some payment; {p['below_target_accounts']} only below the target "
              f"price; {p['fully_refunded_accounts']} fully refunded; {p['target_accounts_before_refunds']} had a payment "
              "at the target price before refunds.", ""]
    lines += ["## Data quality", "",
              f"Rejection limit per file: {pct(Fraction(Decimal(str(params['data_quality']['max_rejected_share']))))}% "
              "of its rows; over it, the indicators using that file are not judged. Exact duplicate rows are "
              "dropped; rows sharing an id with different values are all rejected.", "",
              "| File | Rows | Exact duplicates dropped | Rejected | Share rejected | Over limit | Rejected by code |",
              "|---|---|---|---|---|---|---|"]
    for name in FILES:
        f = m["files"][name]
        codes = ", ".join(f"{code} {n}" for code, n in f["rejected"].items()) or "none"
        lines.append(f"| {name}.csv | {f['rows']} | {f['duplicates']} | {f['rejected_total']} | "
                     f"{f['rejected_pct'] + '%' if f['rejected_pct'] else 'no rows'} | {'yes' if f['over_limit'] else 'no'} "
                     f"| {codes} |")
    lines.append("")
    if rejected:
        shown = rejected[:50]
        lines += [f"Rejected rows ({len(shown)} of {len(rejected)} shown; all in state/pmf/rejected.csv):", "",
                  "| File | Line | Id | Code | Detail |", "|---|---|---|---|---|"]
        lines += [f"| {x['file']} | {x['line']} | {cell(x['id'])} | {x['code']} | {cell(x['detail'])} |" for x in shown]
        lines.append("")
    if final_status == "reported":
        lines += interpretation_markdown(interp)
    lines += ["## Facts", "", "Numbered facts computed by the kit; the interpretation cites them.", ""]
    lines += [f"- **{f['id']}** ({f['about']}): {f['text']}" for f in facts]
    lines += ["", "## Files", "", "state/pmf/metrics.json (every measured value), facts.json, rejected.csv, "
              "interpretation.json, check.json, input/ (the params and exports measured), data_dictionary.md "
              "(the rules).", ""]
    return "\n".join(lines)


def interpretation_markdown(interp: dict) -> list:
    def said(item) -> str:
        return f"{item['text']} [{', '.join(item['facts'])}]"

    lines = ["## Interpretation (checked against the facts)", ""]
    lines += [f"- {said(x)}" for x in interp["summary"]]
    for name in INDICATORS:
        lines += ["", f"**{name.capitalize()}** ({STATUS_TEXT[interp['indicators'][name]['status']]}):", ""]
        lines += [f"- {said(x)}" for x in interp["indicators"][name]["statements"]]
    if interp["data_quality"]:
        lines += ["", "**Data quality:**", ""] + [f"- {said(x)}" for x in interp["data_quality"]]
    if interp["limitations"]:
        lines += ["", "**Limitations:**", ""] + [f"- {said(x)}" for x in interp["limitations"]]
    lines += ["", "## Next tests (proposals only)", "",
              "Nothing here has been done. Contacting people, running surveys and any spending need the owner's "
              "approval first.", "",
              "| Id | Indicator | Kind | Test | Pass rule | When | Owner approval | Facts |",
              "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {t['id']} | {t['indicator']} | {t['kind']} | {cell(t['test'])} | {cell(t['pass_rule'])} | "
              f"{cell(t['when'])} | {'needed' if t['needs_owner_approval'] else 'not needed'} | "
              f"{', '.join(t['facts'])} |" for t in interp["next_tests"]]
    return lines + [""]


def blocked_report(problems: list) -> str:
    lines = ["# Fit and revenue evidence: blocked at setup", "",
             "Nothing was measured and no model ran. The survey alone never shows product-market fit, and this kit "
             "never chooses a target: every product-specific value is a required parameter. Fix each problem "
             "below (templates/params.json and data_dictionary.md describe every parameter and file) and start a "
             "fresh run.", "", "| Code | Field | What is needed |", "|---|---|---|"]
    lines += [f"| {x['code']} | {cell(x['field'])} | {cell(x['message'])} |" for x in problems]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- commands

def outputs(final_status: str, metrics, problems: list) -> dict:
    get = (lambda name: metrics[name]["status"]) if metrics else (lambda name: "not_measured")
    return {"status": "completed", "final_status": final_status,
            "verdict": metrics["verdict"] if metrics else "not_measured",
            "report_path": str(STATE / "REPORT.md"), "survey_status": get("survey"),
            "retention_status": get("retention"), "payment_status": get("payment"), "revenue_status": get("revenue"),
            "problems": problems}


def cmd_setup(params_arg: str, data_arg: str) -> int:
    inputs = STATE / "input"
    (inputs / "data").mkdir(parents=True, exist_ok=True)
    problems = []
    params_src = Path(params_arg) if params_arg.strip() else None
    data_src = Path(data_arg) if data_arg.strip() else None
    if params_src is None or not params_src.is_file():
        problems.append(problem("missing_input", "params_path", "give the path of a params file (start from "
                                "templates/params.json)" + (f"; there is no file at {params_arg}" if params_src else "")))
    else:
        shutil.copyfile(params_src, inputs / "params.json")
    if data_src is None or not data_src.is_dir():
        problems.append(problem("missing_input", "data_dir", "give the folder holding users.csv, activity.csv, "
                                "survey.csv and payments.csv" + (f"; there is no folder at {data_arg}" if data_src else "")))
    else:
        for name in FILES:
            if (data_src / f"{name}.csv").is_file():
                shutil.copyfile(data_src / f"{name}.csv", inputs / "data" / f"{name}.csv")
    metrics = None
    if not problems:
        params, problems, metrics, rejected = evaluate(inputs / "params.json", inputs / "data")
    setup = {"schema": "pmf_evidence.setup/1", "status": "blocked" if problems else "measured", "problems": problems,
             "inputs": {str(path.relative_to(inputs)): sha256(path) for path in sorted(inputs.rglob("*"))
                        if path.is_file()}}
    write_json(STATE / "setup.json", setup)
    if metrics:
        facts = build_facts(params, metrics)
        write_json(STATE / "metrics.json", metrics)
        write_json(STATE / "facts.json", facts)
        (STATE / "facts.md").write_text(facts_markdown(facts))
        with open(STATE / "rejected.csv", "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["file", "line", "id", "code", "detail"])
            writer.writeheader()
            writer.writerows(rejected)
    return say({"status": setup["status"], "problems": [problem_text(x) for x in problems],
                "verdict": metrics["verdict"] if metrics else "not_measured",
                **{f"{name}_status": metrics[name]["status"] if metrics else "not_measured" for name in INDICATORS}})


def cmd_measure(params_arg: str, data_arg: str) -> int:
    params, problems, metrics, rejected = evaluate(Path(params_arg), Path(data_arg))
    if problems:
        print(json.dumps({"status": "blocked", "problems": problems}, indent=1))
        return 1
    print(json.dumps({"status": "measured", "metrics": metrics, "rejected": rejected}, indent=1, ensure_ascii=False))
    return 0


def loaded():
    params = read_json(STATE / "input" / "params.json")
    return params, read_json(STATE / "metrics.json"), read_json(STATE / "facts.json")


def interpretation_problems(params, metrics, facts) -> tuple:
    path = STATE / "interpretation.json"
    if not path.is_file():
        return None, ["missing interpretation: state/pmf/interpretation.json was not written"]
    text = path.read_text()
    try:
        interp = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [f"shape interpretation: not valid JSON ({exc})"]
    found = check_interpretation(interp, facts, metrics, params)
    if LIMIT_TEXT.search(text):
        found.append("limit_text interpretation: it contains usage-limit text, so the model run did not finish")
    return interp, found


def cmd_check(dry_run: bool) -> int:
    params, metrics, facts = loaded()
    _, found = interpretation_problems(params, metrics, facts)
    if dry_run:
        print("\n".join(f"PROBLEM {x}" for x in found) or "CLEAN: no problems")
        return 0
    write_json(STATE / "check.json", {"status": "revise" if found else "pass", "problems": found})
    return say({"status": "revise" if found else "pass", "problems": found})


def cmd_finalize() -> int:
    setup = read_json(STATE / "setup.json")
    if setup["status"] == "blocked":
        (STATE / "REPORT.md").write_text(blocked_report(setup["problems"]))
        result = outputs("blocked", None, [problem_text(x) for x in setup["problems"]])
    else:
        params, metrics, facts = loaded()
        interp, found = interpretation_problems(params, metrics, facts)
        if not (STATE / "check.json").is_file():
            found.append("missing check: the check step did not write state/pmf/check.json")
        final = "revise" if found else "reported"
        with open(STATE / "rejected.csv", newline="") as handle:
            rejected = list(csv.DictReader(handle))
        (STATE / "REPORT.md").write_text(report(params, metrics, facts, rejected, interp, final, found))
        result = outputs(final, metrics, found)
    write_json(STATE / "result.json", result)
    return say(result)


def main(argv: list) -> int:
    if len(argv) == 3 and argv[0] in ("setup", "measure"):
        return (cmd_setup if argv[0] == "setup" else cmd_measure)(argv[1], argv[2])
    if argv[:1] == ["check"] and argv[1:] in ([], ["--dry-run"]):
        return cmd_check(argv[1:] == ["--dry-run"])
    if argv == ["finalize"]:
        return cmd_finalize()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
