#!/usr/bin/env python3
"""Score finished pmf_evidence runs against the fixed benchmark (queue #13).

    python3 score.py CASE=WORKSPACE [CASE=WORKSPACE ...]

WORKSPACE is a run's workspace (the folder holding state/pmf/). For each case it checks, against
expected.json and the bar's criteria (product results/2026-10-04-pmf-kit-13/criteria.md):
  inputs  the run measured the frozen fixture: every staged input's sha256 equals expected.json's
  B1      metrics.json equals expected.json on every listed value, and the verdict
  B2      the final status; a blocked case lists exactly the expected problems and has no model file
  B3      REPORT.md shows each rate with its numerator and denominator, the observation end, the
          censoring, the money rows kept apart and every file's data-quality row
  B4      the synthetic banner and the survey-alone sentence, no product-market-fit claim
          anywhere in the report, the interpretation's statuses echo the measured ones, a passing
          check and no usage-limit text
Prints one line per case (PASS, or FAIL with every reason) and a JSON summary last; exits 0 only
when every case passes. Standard library only; it never imports the kit, so a defect in the kit
cannot hide itself here. The bar's manual reading (M1-M5) is not scored here.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

BENCH = Path(__file__).resolve().parent
EXPECTED = json.loads((BENCH / "expected.json").read_text())
CASES = {c["case"]: c for c in EXPECTED["cases"]}
PHRASES = EXPECTED["report_phrases"]
FILES = ("users", "activity", "survey", "payments")
INDICATORS = ("survey", "retention", "payment", "revenue")
MODEL_FILES = ("interpretation.json", "check.json")
LIMIT = re.compile(r"you['\u2019]ve hit your (?:\w+ )?limit|usage limit|session limit|limit (?:will )?resets?|"
                   r"out of (?:extra )?usage|rate[- ]limited", re.I)
FIT = re.compile(r"(?i:product[\s\-\u2010-\u2015]*market[\s\-\u2010-\u2015]*fit)|\bPMF\b|"  # PMF in capitals: not a state/pmf path
                 r"(?i:\b(?:has|have|had|reach\w*|achiev\w*|found|show\w*|demonstrat\w*|prov\w*|confirm\w*|establish\w*)"
                 r"\s+(?:a\s+|real\s+|clear\s+|strong\s+)?fit\b(?!\s+indicator))")
NEGATION = re.compile(r"\b(?:not|no|never|cannot|can['\u2019]t|doesn['\u2019]t|does not|isn['\u2019]t|aren['\u2019]t|"
                      r"without|neither|nor)\b", re.I)
SENTENCE = re.compile(r"(?<=[.!?;:])\s+|\n+")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pct(num: int, den: int) -> str:
    """num/den as a percentage with one decimal, half up: the report's rounding, worked out here again."""
    return str((Decimal(num) * 100 / Decimal(den)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def fit_claims(text: str) -> list[str]:
    """Sentences that mention product-market fit (or say a product has or shows fit) with no negation."""
    return [s.strip() for s in SENTENCE.split(text) if FIT.search(s) and not NEGATION.search(s)]


def read_json(path: Path, fails: list, what: str):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        fails.append(f"{what}: unreadable ({type(exc).__name__})")
        return None


def check_inputs(case: dict, pmf: Path, fails: list) -> None:
    for name, digest in sorted(case["sha256"].items()):
        staged = pmf / "input" / (name if name == "params.json" else f"data/{name}")
        if not staged.is_file():
            fails.append(f"inputs: {name} was not staged into state/pmf/input")
        elif sha256(staged) != digest:
            fails.append(f"inputs: {name} is not the frozen fixture (sha256 differs)")


def check_blocked(case: dict, pmf: Path, result: dict, fails: list) -> None:
    setup = read_json(pmf / "setup.json", fails, "setup.json") or {}
    if setup.get("status") != case["setup_status"]:
        fails.append(f"B2: setup status {setup.get('status')!r}, expected {case['setup_status']!r}")
    got = sorted([p.get("code"), p.get("field")] for p in setup.get("problems", []))
    if got != case["setup_problems"]:
        fails.append(f"B2: setup problems {got}, expected {case['setup_problems']}")
    for name in MODEL_FILES:
        if (pmf / name).exists():
            fails.append(f"B2: {name} exists although setup blocked (a model step ran)")
    if result.get("verdict") != "not_measured":
        fails.append(f"B2: verdict {result.get('verdict')!r} on a blocked run")
    report = (pmf / "REPORT.md").read_text() if (pmf / "REPORT.md").is_file() else ""
    if "blocked at setup" not in report:
        fails.append("B2: REPORT.md does not say the run was blocked at setup")
    for _code, field in case["setup_problems"]:
        if f"| {field} |" not in report:
            fails.append(f"B2: REPORT.md does not list the problem with {field}")


def check_metrics(case: dict, metrics: dict, fails: list) -> None:
    if metrics.get("verdict") != case["verdict"]:
        fails.append(f"B1: verdict {metrics.get('verdict')!r}, expected {case['verdict']!r}")
    for name, want in case["files"].items():
        have = metrics.get("files", {}).get(name, {})
        for key, value in want.items():
            if have.get(key) != value:
                fails.append(f"B1: files.{name}.{key} = {have.get(key)!r}, expected {value!r}")
    for section in INDICATORS:
        have = metrics.get(section, {})
        for key, value in case[section].items():
            if have.get(key) != value:
                fails.append(f"B1: {section}.{key} = {have.get(key)!r}, expected {value!r}")


def required_lines(case: dict, params: dict) -> list[str]:
    """Text REPORT.md must hold, built from expected.json and the case's own params."""
    cur, s, r, p, rv = params["currency"], case["survey"], case["retention"], case["payment"], case["revenue"]
    lines = [PHRASES["fit_rule"], f"**Verdict: {case['verdict']}**", f"Observed until {params['observed_until']}",
             f"| eligible respondents | {s['eligible']} |", f"| valid responses | {s['valid']} |",
             f"| very disappointed (eligible) | {s['very']} |", "Censoring: ",
             f"| refunds of those payments | | {rv['refunds']} {cur} |",
             f"| payment fees on those payments | | {rv['fees']} {cur} |",
             f"| net collected | | {rv['net']} {cur} |",
             f"| promises (not money, never counted) | {rv['promises']} rows | {rv['promised']} {cur} |",
             f"| payments outside the horizon (not counted) | {rv['outside_horizon']} rows | {rv['outside_amount']} {cur} |",
             f"Customer accounts: {p['target_accounts']} kept a payment of at least "
             f"{params['payment']['target_price']} {cur} after refunds; {p['paying_accounts']} kept some payment; "
             f"{p['below_target_accounts']} only below the target price; {p['fully_refunded_accounts']} fully refunded"]
    if params["data_label"] == "synthetic":
        lines.append(PHRASES["synthetic"])
    if s["eligible"]:
        lines.append(f"{s['very']} of {s['eligible']} eligible respondents very disappointed ({s['share_pct']}%")
    else:
        lines.append("undefined: 0 eligible respondents")
    if r["curve"]:
        lines += [f"| {k} | {n} | {a} | {pct(a, n)}% | {r['users'] - n} |" for k, n, a in r["curve"]]
    else:
        lines.append("| none | 0 | 0 | undefined | 0 |")
    if r["adequate_on"]:
        lines.append(f"Retention can be judged from {r['adequate_on']}")
    return lines


def check_report(case: dict, params: dict, pmf: Path, report: str, fails: list) -> None:
    for line in required_lines(case, params):
        if line not in report:
            fails.append(f"B3: REPORT.md lacks {line!r}")
    gross = [x for x in report.splitlines() if x.startswith("| gross receipts (payments in the horizon) |")]
    if not gross or not gross[0].endswith(f"| {case['revenue']['gross']} {params['currency']} |"):
        fails.append(f"B3: REPORT.md gross receipts row does not show {case['revenue']['gross']} {params['currency']}")
    for name, want in case["files"].items():
        rows = [x for x in report.splitlines() if x.startswith(f"| {name}.csv | ")]
        total = sum(want["rejected"].values())
        head = f"| {name}.csv | {want['rows']} | {want['duplicates']} | {total} | "
        if not rows or not rows[0].startswith(head):
            fails.append(f"B3: REPORT.md data-quality row for {name}.csv is not {head!r}")
            continue
        if f"| {'yes' if want['over_limit'] else 'no'} |" not in rows[0]:
            fails.append(f"B3: REPORT.md data-quality row for {name}.csv shows the wrong over-limit flag")
        for code, n in want["rejected"].items():
            if f"{code} {n}" not in rows[0]:
                fails.append(f"B3: REPORT.md data-quality row for {name}.csv lacks '{code} {n}'")
    for heading in ("## Interpretation (checked against the facts)", "## Next tests (proposals only)"):
        if heading not in report:
            fails.append(f"B4: REPORT.md lacks {heading!r} (interpretation withheld or missing)")
    claims = fit_claims(report)
    if claims:
        fails.append(f"B4: fit claims in REPORT.md: {claims[:3]}")


def check_interpretation(case: dict, pmf: Path, fails: list) -> None:
    interp = read_json(pmf / "interpretation.json", fails, "B4: interpretation.json") or {}
    for section in INDICATORS:
        echoed = (interp.get("indicators") or {}).get(section, {}).get("status")
        if echoed != case[section]["status"]:
            fails.append(f"B4: interpretation gives {section} status {echoed!r}, measured {case[section]['status']!r}")
    claims = fit_claims(json.dumps(interp, ensure_ascii=False).replace("\\n", "\n"))
    if claims:
        fails.append(f"B4: fit claims in interpretation.json: {claims[:3]}")
    check = read_json(pmf / "check.json", fails, "B4: check.json") or {}
    if check.get("status") != "pass":
        fails.append(f"B4: check.json status {check.get('status')!r} with problems {check.get('problems')}")


def score(case_name: str, workspace: Path) -> list[str]:
    case, pmf, fails = CASES[case_name], workspace / "state" / "pmf", []
    if not pmf.is_dir():
        return [f"no state/pmf in {workspace}"]
    check_inputs(case, pmf, fails)
    result = read_json(pmf / "result.json", fails, "result.json") or {}
    if result.get("final_status") != case["expected_final_status"]:
        fails.append(f"B2: final status {result.get('final_status')!r}, expected {case['expected_final_status']!r}"
                     f" (problems: {result.get('problems')})")
    for name in sorted(pmf.rglob("*")):
        if name.is_file() and name.suffix in (".md", ".json") and "input" not in name.relative_to(pmf).parts:
            if name.name not in ("data_dictionary.md", "interpretation_contract.md") and LIMIT.search(name.read_text()):
                fails.append(f"B4: usage-limit text in {name.relative_to(workspace)}")
    if case["expected_final_status"] == "blocked":
        check_blocked(case, pmf, result, fails)
        return fails
    params = read_json(pmf / "input" / "params.json", fails, "params.json")
    metrics = read_json(pmf / "metrics.json", fails, "B1: metrics.json")
    if params is None or metrics is None:
        return fails
    check_metrics(case, metrics, fails)
    if result.get("verdict") != case["verdict"]:
        fails.append(f"B1: result.json verdict {result.get('verdict')!r}, expected {case['verdict']!r}")
    report = (pmf / "REPORT.md").read_text() if (pmf / "REPORT.md").is_file() else ""
    if not report:
        fails.append("B3: no REPORT.md")
    else:
        check_report(case, params, pmf, report, fails)
    check_interpretation(case, pmf, fails)
    return fails


def main(argv: list[str]) -> int:
    pairs = [a.split("=", 1) for a in argv]
    if not pairs or any(len(p) != 2 or p[0] not in CASES for p in pairs):
        raise SystemExit(__doc__)
    summary = {}
    for name, workspace in pairs:
        fails = score(name, Path(workspace).expanduser())
        summary[name] = {"pass": not fails, "fails": fails}
        print(f"{name}: PASS" if not fails else f"{name}: FAIL\n  - " + "\n  - ".join(fails))
    passed = sum(v["pass"] for v in summary.values())
    print(json.dumps({"passed": passed, "failed": len(summary) - passed, "cases": summary}))
    return 0 if passed == len(summary) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
