#!/usr/bin/env python3
"""Build the fixed pmf_evidence benchmark (queue #13): nine labelled synthetic cases.

    python3 construct.py OUTDIR      write OUTDIR/<CASE>/{params.json,users.csv,activity.csv,
                                     survey.csv,payments.csv} and print each file's sha256
                                     (refuses to overwrite a file with different content)

Every value is made up: no real product, person, account or payment. Each case's params say
data_label "synthetic" (P1 is the case whose params are broken on purpose). How each case is built,
and so why expected.json holds what it holds, is in README.md next to this file. expected.json says
what the kit must compute and is never staged into a run. Standard library only; the same bytes
every time.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

HEADERS = {
    "users": ["user_id", "account_id", "started_on"],
    "activity": ["event_id", "user_id", "event", "occurred_on"],
    "survey": ["response_id", "user_id", "submitted_on", "answer"],
    "payments": ["row_id", "account_id", "kind", "amount", "currency", "occurred_on", "ref_row_id"],
}
VERY, SOMEWHAT, NOT = "very_disappointed", "somewhat_disappointed", "not_disappointed"
FEE = {"49.00": "1.72", "39.00": "1.43"}  # a card processor's fee per payment, made up


def d(text: str) -> date:
    return date.fromisoformat(text)


def iso(day: date) -> str:
    return day.isoformat()


class Case:
    """One case's four exports, built row by row in a fixed order."""

    def __init__(self, observed_until: str):
        self.until = d(observed_until)
        self.rows = {name: [] for name in HEADERS}
        self.counter = {"e": 0, "r": 0, "p": 0}

    def next_id(self, kind: str) -> str:
        self.counter[kind] += 1
        width = 5 if kind == "e" else 3
        return f"{kind}{self.counter[kind]:0{width}d}"

    def user(self, user_id: str, account_id: str, started_on: str) -> None:
        self.rows["users"].append([user_id, account_id, started_on])

    def event(self, user_id: str, name: str, day: date) -> str | None:
        if day > self.until:
            return None
        event_id = self.next_id("e")
        self.rows["activity"].append([event_id, user_id, name, iso(day)])
        return event_id

    def response(self, user_id: str, submitted_on: str, answer: str) -> None:
        self.rows["survey"].append([self.next_id("r"), user_id, submitted_on, answer])

    def money(self, account_id: str, kind: str, amount: str, currency: str, day: str, ref: str = "") -> str:
        row_id = self.next_id("p")
        self.rows["payments"].append([row_id, account_id, kind, amount, currency, day, ref])
        return row_id

    def files(self, params: dict) -> dict[str, str]:
        out = {"params.json": json.dumps(params, indent=2, ensure_ascii=False) + "\n"}
        for name, header in HEADERS.items():
            buffer = io.StringIO()
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(self.rows[name])
            out[f"{name}.csv"] = buffer.getvalue()
        return out


def weekly_user(case: Case, user_id: str, start: date, value_event: str, active, skip=()) -> None:
    """A weekly product's user: a login at the start of every week they are observed, and two
    value events (days 1 and 3 of the week) in every week k for which active(k) holds."""
    k = 0
    while start + timedelta(days=7 * k) <= case.until:
        case.event(user_id, "login", start + timedelta(days=7 * k))
        if active(k) and k not in skip:
            case.event(user_id, value_event, start + timedelta(days=7 * k + 1))
            case.event(user_id, value_event, start + timedelta(days=7 * k + 3))
        k += 1


def weekly_params(name: str, value_event: str, observed_until: str, *, min_responses=30,
                  revenue_target="1500.00", horizon=("2026-01-01", "2026-03-31"), min_accounts=10) -> dict:
    return {
        "schema": "pmf_evidence.params/1",
        "product": name,
        "data_label": "synthetic",
        "buyer": "small agencies that plan work every week (synthetic)",
        "user_unit": "planner seat (one person using the tool)",
        "account_unit": "agency account (the customer that pays)",
        "value_event": value_event,
        "observed_until": observed_until,
        "currency": "USD",
        "survey": {"min_value_events": 2, "lookback_days": 14, "min_responses": min_responses},
        "retention": {"period_days": 7, "cohort_by": "month", "min_users_per_period": 20, "min_periods": 6,
                      "flat_last_periods": 3, "flat_max_drop_pp": 5, "min_plateau_rate": 0.3},
        "payment": {"target_price": "49.00", "price_unit": "per agency account per month",
                    "min_target_price_accounts": min_accounts},
        "revenue": {"target": revenue_target, "horizon_start": horizon[0], "horizon_end": horizon[1]},
        "data_quality": {"max_rejected_share": 0.05},
    }


# ---- N1: normal clean data, weekly product, every indicator met ---------------------------------

JAN, FEB = d("2026-01-05"), d("2026-02-02")


def two_cohort_users(case: Case, value_event: str, jan_core_active) -> None:
    """60 planner seats in 20 agency accounts (3 seats each): u01-u30 start 2026-01-05, u31-u60
    start 2026-02-02. Per cohort: 16 core seats, 8 fading (weeks 0-2), 6 dropping (week 0)."""
    for i in range(1, 61):
        user_id, start = f"u{i:02d}", JAN if i <= 30 else FEB
        case.user(user_id, f"a{(i + 2) // 3:02d}", iso(start))
    for i in range(1, 61):
        user_id, start, j = f"u{i:02d}", JAN if i <= 30 else FEB, (i - 1) % 30 + 1
        if j <= 16:
            active = jan_core_active(i) if i <= 30 else (lambda k: True)
            weekly_user(case, user_id, start, value_event, active, skip=(10,) if user_id == "u05" else ())
        elif j <= 24:
            weekly_user(case, user_id, start, value_event, lambda k: k <= 2)
        else:
            weekly_user(case, user_id, start, value_event, lambda k: k == 0)


def monthly_payments(case: Case) -> dict[str, list[str]]:
    """a01-a08 pay 49.00 on Jan 5, Feb 5, Mar 5; a09-a10 pay 39.00 then; a11-a14 pay 49.00 on
    Feb 2 and Mar 2; a15-a16 pay 39.00 then; a17-a20 never pay. A fee row follows each payment."""
    ids: dict[str, list[str]] = {}
    plan = [(f"a{n:02d}", "49.00", ["2026-01-05", "2026-02-05", "2026-03-05"]) for n in range(1, 9)]
    plan += [(f"a{n:02d}", "39.00", ["2026-01-05", "2026-02-05", "2026-03-05"]) for n in (9, 10)]
    plan += [(f"a{n:02d}", "49.00", ["2026-02-02", "2026-03-02"]) for n in range(11, 15)]
    plan += [(f"a{n:02d}", "39.00", ["2026-02-02", "2026-03-02"]) for n in (15, 16)]
    for account, amount, days in plan:
        for day in days:
            pid = case.money(account, "payment", amount, "USD", day)
            case.money(account, "fee", FEE[amount], "USD", day, pid)
            ids.setdefault(account, []).append(pid)
    return ids


def n1_survey(case: Case) -> None:
    """2026-03-20: the 32 core seats (14 very, 12 somewhat, 6 not), 8 fading seats u17-u24 and 4
    dropped seats u25-u28 (u17-u18 somewhat, the other ten not)."""
    core = [f"u{i:02d}" for i in list(range(1, 17)) + list(range(31, 47))]
    for n, user_id in enumerate(core):
        case.response(user_id, "2026-03-20", VERY if n < 14 else SOMEWHAT if n < 26 else NOT)
    for i in range(17, 29):
        case.response(f"u{i:02d}", "2026-03-20", SOMEWHAT if i <= 18 else NOT)


def build_n1() -> Case:
    case = Case("2026-03-31")
    two_cohort_users(case, "plan_shared", lambda i: (lambda k: True))
    n1_survey(case)
    monthly_payments(case)
    return case


# ---- E1: empty exports ----------------------------------------------------------------------------

def build_e1() -> Case:
    return Case("2026-03-31")


# ---- I1: four weeks in: too little observation -------------------------------------------------

def build_i1() -> Case:
    case = Case("2026-02-15")
    start = d("2026-01-26")
    for i in range(1, 31):
        case.user(f"u{i:02d}", f"a{(i + 2) // 3:02d}", iso(start))
    for i in range(1, 31):
        weekly_user(case, f"u{i:02d}", start, "plan_shared", (lambda k: True) if i <= 24 else (lambda k: k == 0))
    for i in range(1, 13):
        case.response(f"u{i:02d}", "2026-02-12", VERY if i <= 6 else SOMEWHAT if i <= 10 else NOT)
    for i in range(25, 28):
        case.response(f"u{i:02d}", "2026-02-12", NOT)
    for n in range(1, 7):
        pid = case.money(f"a{n:02d}", "payment", "49.00", "USD", "2026-01-26")
        case.money(f"a{n:02d}", "fee", "1.72", "USD", "2026-01-26", pid)
    case.money("a07", "promise", "490.00", "USD", "2026-02-10")
    return case


# ---- D1: N1 with duplicate and invalid rows in every export ------------------------------------

def build_d1() -> Case:
    case = build_n1()
    users, activity, survey, payments = (case.rows[k] for k in HEADERS)
    users.append(list(users[0]))                                    # exact duplicate of u01
    users.append(["u61", "a21", "2026-02-30"])                       # bad_date
    users.append(["u63", "a21", "2026-02-02"])                       # conflicting_duplicate
    users.append(["u63", "a22", "2026-02-02"])                       # conflicting_duplicate
    first_value = [row for row in activity if row[2] == "plan_shared"]
    activity.append(list(first_value[0]))                            # exact duplicate (u01)
    activity.append(list(next(r for r in first_value if r[1] == "u31")))  # exact duplicate (u31)
    activity.extend([
        ["eX01", "u99", "plan_shared", "2026-03-02"],                # unknown_user
        ["eX02", "u63", "plan_shared", "2026-03-02"],                # unknown_user (u63 rejected)
        ["eX03", "u01", "plan_shared", "2026-13-01"],                # bad_date
        ["eX04", "u01", "plan_shared", "2026-04-01"],                # after_observation_end
        ["eX05", "u31", "plan_shared", "2026-01-30"],                # before_user_start
        ["eX06", "u02", "plan_shared", "2026-03-03"],                # conflicting_duplicate
        ["eX06", "u02", "plan_shared", "2026-03-04"],                # conflicting_duplicate
        ["eX07", "u03", "", "2026-03-03"],                           # missing_value
    ])
    for row in survey:                                               # same answer, label spelling
        if row[1] == "u03":
            row[3] = "Very disappointed"
    survey.append(list(survey[0]))                                   # exact duplicate (u01)
    survey.extend([
        ["r901", "u01", "2026-03-25", NOT],                          # repeat respondent: first kept
        ["r902", "u29", "2026-03-20", "Very dissapointed"],          # bad_answer
        ["r903", "u30", "2026-03-20", ""],                           # missing_value
    ])
    a01_march = next(r[0] for r in payments if r[1] == "a01" and r[2] == "payment" and r[5] == "2026-03-05")
    payments.append(list(payments[0]))                               # exact duplicate (a01 Jan payment)
    payments.extend([
        ["pX01", "a17", "payment", "49.00", "USD", "2026-03-10", ""],      # conflicting_duplicate
        ["pX01", "a17", "payment", "59.00", "USD", "2026-03-10", ""],      # conflicting_duplicate
        ["pX02", "a18", "payment", "-49.00", "USD", "2026-03-10", ""],     # bad_amount
        ["pX03", "a18", "payment", "0", "USD", "2026-03-10", ""],          # bad_amount
        ["pX04", "a18", "payment", "49.999", "USD", "2026-03-10", ""],     # bad_amount
        ["pX05", "a19", "payment", "49.00", "EUR", "2026-03-10", ""],      # currency_mismatch
        ["pX06", "a19", "chargeback", "49.00", "USD", "2026-03-10", "p001"],  # unknown_kind
        ["pX07", "a99", "payment", "49.00", "USD", "2026-03-10", ""],      # unknown_account
        ["pX08", "a01", "refund", "49.00", "USD", "2026-03-10", "p-none"],  # bad_reference
        ["pX09", "a01", "refund", "60.00", "USD", "2026-03-12", a01_march],  # refund_exceeds_payment
        ["pX10", "a20", "payment", "49.00", "USD", "2026-03-10", "p001"],  # unexpected_reference
    ])
    return case


# ---- L1: survey passed, early plateau, then a later decline ------------------------------------

def build_l1() -> Case:
    case = Case("2026-03-31")

    def jan_core(i: int):
        last = 99 if i <= 7 else 10 if i <= 9 else 9 if i <= 12 else 8
        return lambda k: k <= last

    two_cohort_users(case, "plan_shared", jan_core)
    eligible = [f"u{i:02d}" for i in list(range(1, 13)) + list(range(31, 47))]
    for n, user_id in enumerate(eligible):
        case.response(user_id, "2026-03-20", VERY if n < 13 else SOMEWHAT if n < 23 else NOT)
    for i in list(range(13, 17)):
        case.response(f"u{i:02d}", "2026-03-20", VERY)
    for i in list(range(17, 23)) + [25, 26]:
        case.response(f"u{i:02d}", "2026-03-20", NOT)
    monthly_payments(case)
    return case


# ---- R1: refunds, partial refunds, fees, promises, discounts, out-of-horizon payments ------------

def build_r1() -> Case:
    case = Case("2026-03-31")
    two_cohort_users(case, "plan_shared", lambda i: (lambda k: True))
    n1_survey(case)
    jan_days = ["2026-01-05", "2026-02-05", "2026-03-05"]
    feb_days = ["2026-02-02", "2026-03-02"]
    refunds = {  # (account, payment day) -> [(refund day, amount)]
        ("a01", "2026-03-05"): [("2026-03-10", "49.00")],
        ("a02", "2026-01-05"): [("2026-01-20", "49.00")],
        ("a02", "2026-02-05"): [("2026-02-20", "49.00")],
        ("a02", "2026-03-05"): [("2026-03-20", "49.00")],
        ("a03", "2026-01-05"): [("2026-01-15", "20.00")],
        ("a03", "2026-02-05"): [("2026-02-10", "49.00")],
        ("a03", "2026-03-05"): [("2026-03-10", "49.00")],
        ("a04", "2026-01-05"): [("2026-01-12", "5.00")],
        ("a05", "2026-01-05"): [("2026-01-25", "49.00")],
        ("a05", "2026-02-05"): [("2026-02-25", "49.00")],
        ("a05", "2026-03-05"): [("2026-03-25", "49.00")],
        ("a07", "2026-01-05"): [("2026-01-09", "49.00")],
        ("a07", "2026-02-05"): [("2026-02-09", "49.00")],
        ("a07", "2026-03-05"): [("2026-03-09", "15.00")],
        ("a14", "2026-03-02"): [("2026-03-09", "10.00")],
    }
    plan = [(f"a{n:02d}", "49.00", jan_days) for n in range(1, 9)]
    plan += [(f"a{n:02d}", "39.00", jan_days) for n in (9, 10)]
    plan += [(f"a{n:02d}", "49.00", feb_days) for n in range(11, 15)]
    plan += [(f"a{n:02d}", "39.00", feb_days) for n in (15, 16)]
    plan += [("a18", "49.00", ["2025-12-28"]), ("a19", "49.00", ["2026-03-31"])]
    for account, amount, days in plan:
        for day in days:
            pid = case.money(account, "payment", amount, "USD", day)
            case.money(account, "fee", FEE[amount], "USD", day, pid)
            for refund_day, refund in refunds.get((account, day), []):
                case.money(account, "refund", refund, "USD", refund_day, pid)
    case.money("a17", "promise", "590.00", "USD", "2026-03-15")
    case.money("a20", "promise", "49.00", "USD", "2026-03-25")
    return case


# ---- F1: low-frequency use (a few trips a year), quarter-length periods ------------------------

def build_f1() -> Case:
    case = Case("2026-06-30")
    starts = {1: d("2024-01-15"), 2: d("2024-07-15")}
    people = []
    for cohort, start in starts.items():
        for j in range(1, 41):
            n = (cohort - 1) * 40 + j
            role = "regular" if j <= 24 else "even" if j <= 28 else "odd" if j <= 32 else "once"
            people.append((f"t{n:03d}", f"h{n:03d}", start, role))
            case.user(f"t{n:03d}", f"h{n:03d}", iso(start))
    trips = {"regular": lambda k: True, "even": lambda k: k % 2 == 0, "odd": lambda k: k == 0 or k % 2 == 1,
             "once": lambda k: k == 0}
    for user_id, _, start, role in people:
        k = 0
        while start + timedelta(days=91 * k) <= case.until:
            case.event(user_id, "app_open", start + timedelta(days=91 * k + 10))
            if trips[role](k):
                case.event(user_id, "trip_booked", start + timedelta(days=91 * k + 30))
            k += 1
    eligible = [p for p in people if p[3] != "once"]
    for n, (user_id, _, _, _) in enumerate(eligible):
        case.response(user_id, "2026-06-01", VERY if n < 28 else SOMEWHAT if n < 52 else NOT)
    for user_id, _, start, role in people:
        if role == "once" and start == starts[1]:
            case.response(user_id, "2026-06-01", NOT)
    for user_id, account, start, role in people:
        if role == "once":
            case.money(account, "payment", "79.00", "EUR", iso(start))
    for user_id, account, start, role in people:
        if role == "regular":
            pid = case.money(account, "payment", "79.00", "EUR", "2026-01-10")
            if account in ("h001", "h041"):
                case.money(account, "refund", "79.00", "EUR", "2026-02-01", pid)
        elif role in ("even", "odd"):
            case.money(account, "payment", "59.00", "EUR", "2026-01-10")
    return case


def f1_params() -> dict:
    return {
        "schema": "pmf_evidence.params/1",
        "product": "Synthetic fixture F1 (trip planner used a few times a year)",
        "data_label": "synthetic",
        "buyer": "independent travellers who book a few trips a year (synthetic)",
        "user_unit": "traveller (one person planning trips)",
        "account_unit": "traveller household (the customer that pays)",
        "value_event": "trip_booked",
        "observed_until": "2026-06-30",
        "currency": "EUR",
        "survey": {"min_value_events": 1, "lookback_days": 365, "min_responses": 40},
        "retention": {"period_days": 91, "cohort_by": "quarter", "min_users_per_period": 30, "min_periods": 4,
                      "flat_last_periods": 3, "flat_max_drop_pp": 5, "min_plateau_rate": 0.5},
        "payment": {"target_price": "79.00", "price_unit": "per traveller household per year",
                    "min_target_price_accounts": 30},
        "revenue": {"target": "3000.00", "horizon_start": "2026-01-01", "horizon_end": "2026-06-30"},
        "data_quality": {"max_rejected_share": 0.05},
    }


# ---- S1: survey threshold passed, retention and payment not yet adequate -----------------------

def build_s1() -> Case:
    case = Case("2026-03-01")
    start = d("2026-02-02")
    for i in range(1, 51):
        case.user(f"s{i:02d}", f"a{(i + 1) // 2:02d}", iso(start))
    for i in range(1, 51):
        weekly_user(case, f"s{i:02d}", start, "report_sent", (lambda k: True) if i <= 40 else (lambda k: k == 0))
    for i in range(1, 41):
        case.response(f"s{i:02d}", "2026-02-27", VERY if i <= 18 else SOMEWHAT if i <= 32 else NOT)
    for i in range(41, 46):
        case.response(f"s{i:02d}", "2026-02-27", NOT)
    for n in range(1, 5):
        pid = case.money(f"a{n:02d}", "payment", "49.00", "USD", "2026-02-02")
        case.money(f"a{n:02d}", "fee", "1.72", "USD", "2026-02-02", pid)
    for n in range(5, 8):
        case.money(f"a{n:02d}", "promise", "49.00", "USD", "2026-02-20")
    return case


def s1_params() -> dict:
    params = weekly_params("Synthetic fixture S1 (survey ahead of the rest)", "report_sent", "2026-03-01",
                           min_responses=40, revenue_target="2000.00", horizon=("2026-02-01", "2026-04-30"))
    params["buyer"] = "small teams that send a weekly client report (synthetic)"
    params["user_unit"] = "team member (one person sending reports)"
    params["account_unit"] = "team account (the customer that pays)"
    params["payment"]["price_unit"] = "per team account per month"
    return params


# ---- P1: missing and invalid runtime parameters ------------------------------------------------

def p1_params() -> dict:
    params = weekly_params("Synthetic fixture P1 (parameters left out or wrong)", "plan_shared", "2026-03-31")
    del params["observed_until"], params["value_event"], params["revenue"]
    del params["retention"]["period_days"], params["payment"]["target_price"]
    params["retention"]["perod_days"] = 7
    params["data_label"] = "test"
    params["currency"] = "usd"
    params["survey"]["min_responses"] = 0
    params["payment"]["min_target_price_accounts"] = "10"
    return params


def cases() -> dict[str, dict[str, str]]:
    n1 = build_n1()
    return {
        "N1": n1.files(weekly_params("Synthetic fixture N1 (weekly planning tool)", "plan_shared", "2026-03-31")),
        "E1": build_e1().files(weekly_params("Synthetic fixture E1 (empty exports)", "plan_shared", "2026-03-31")),
        "I1": build_i1().files(weekly_params("Synthetic fixture I1 (three weeks in)", "plan_shared", "2026-02-15")),
        "D1": build_d1().files(weekly_params("Synthetic fixture D1 (messy exports)", "plan_shared", "2026-03-31")),
        "L1": build_l1().files(weekly_params("Synthetic fixture L1 (late decline)", "plan_shared", "2026-03-31",
                                             min_responses=25)),
        "R1": build_r1().files(weekly_params("Synthetic fixture R1 (refunds and promises)", "plan_shared",
                                             "2026-03-31", revenue_target="1900.00")),
        "F1": build_f1().files(f1_params()),
        "S1": build_s1().files(s1_params()),
        "P1": n1.files(p1_params()),
    }


def materialise(outdir: Path) -> dict[str, dict[str, str]]:
    hashes: dict[str, dict[str, str]] = {}
    for name, files in cases().items():
        folder = outdir / name
        folder.mkdir(parents=True, exist_ok=True)
        for filename, text in files.items():
            target = folder / filename
            if target.exists() and target.read_text() != text:
                raise SystemExit(f"{target} exists with different content: use a fresh folder")
            target.write_text(text)
            hashes.setdefault(name, {})[filename] = hashlib.sha256(text.encode()).hexdigest()
    return hashes


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    for case_name, files in materialise(Path(sys.argv[1])).items():
        for filename, digest in files.items():
            print(f"{digest}  {case_name}/{filename}")
