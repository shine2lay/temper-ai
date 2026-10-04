"""Mechanical guards for the early tech and serving screen; not semantic fact-checking."""
import hashlib
import json
import math
from pathlib import Path
import re
import sys

FORMULA = "P*W*O*T/(F*B*R)"
FIELDS = {
    "tech": ("job", "human_work", "outside_control"),
    "build": ("inputs", "uncertainty", "smallest_test"),
    "serving": ("buyer", "jurisdiction", "procurement", "security", "data_permission",
                "platform_permission", "agreements", "legal_duties", "licence",
                "onboarding", "approvers", "time_cost", "unknowns"),
    "factor_reasons": ("P", "W", "O", "T", "F", "B", "R"),
}
# Non-blind regression guards. Evidence judgment still needs a separate reviewer.
GUARDS = {
    "enterprise": {"F": 1, "B": 3},
    "regulated_data": {"F": 1, "B": 2},
    "gambling_operator": {"F": 1, "B": 4},
    "gambling_supplier": {"B": 3},
    "human_review": {"T": 3, "F": 1, "B": 1},
    "unknown_permission": {"F": 1, "B": 3},
}


MAX_CANDIDATES = 8
# Ranked headings of a saved scan shortlist, tried in order. The first is the
# frozen replay's format and must keep giving the same names; the second is the
# 2026-10-01 scan's; the last accepts other heading wordings of the same shape.
HEADINGS = (
    re.compile(r"^### #(\d+) — (.*?)\. Score ", re.M),
    re.compile(r"^### (\d+)\. (.*?) — score ", re.M),
    re.compile(r"^###\s+#?(\d+)[.)]?\s+(?:[—–-]\s+)?(.+?)"
               r"(?:\s*(?:[.,(]|[—–-])\s*[Ss]core\b.*)?$", re.M),
)


def parse_identities(text):
    """C1..Cn by original rank from a saved shortlist's ranked headings."""
    for pattern in HEADINGS:
        found = [(int(number), name.strip()) for number, name in pattern.findall(text)]
        if found:
            break
    else:
        raise ValueError("no ranked candidate headings in the saved shortlist")
    numbers = [number for number, _ in found]
    if numbers != list(range(1, len(found) + 1)) or len(found) > MAX_CANDIDATES:
        raise ValueError(f"ranked headings must number 1..n with n <= {MAX_CANDIDATES}: {numbers}")
    if not all(name for _, name in found):
        raise ValueError("empty candidate name in the saved shortlist")
    return {f"C{number}": name for number, name in found}


def identities(root):
    return parse_identities((root / "baseline/shortlist.md").read_text())


def normal(text):
    return " ".join(text.split())


def check(root):
    root = Path(root).resolve()
    workspace = root.parent.parent
    problems = []
    def require(condition, message):
        if not condition:
            problems.append(message)
    manifest = json.loads((root / "baseline-manifest.json").read_text())
    for name, expected in manifest.items():
        require(hashlib.sha256((root / "baseline" / name).read_bytes()).hexdigest() == expected,
                "changed baseline: " + name)
        if name in ("demand.md", "market.md", "timing.md"):
            require(hashlib.sha256((root / name).read_bytes()).hexdigest() == expected,
                    "changed lens: " + name)
    names = identities(root)
    count = len(names)
    require(set(names) == {f"C{number}" for number in range(1, count + 1)}, "baseline identities incomplete")
    result = json.loads((root / "serving.json").read_text())
    require(result.get("formula") == FORMULA, "formula changed")
    candidates = result.get("candidates", [])
    if not isinstance(candidates, list):
        return problems + ["candidates must be a list"]
    require(len(candidates) == count, "must retain every candidate")
    ids, ranks, scores = [], [], []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            problems.append("candidate must be an object")
            continue
        cid = candidate.get("id", "missing")
        ids.append(cid)
        require(candidate.get("name") == names.get(cid) and cid in names, f"{cid}: changed identity")
        require(candidate.get("original_rank") == (int(cid[1:]) if cid in names else None),
                f"{cid}: original rank")
        ranks.append(candidate.get("rank"))
        require("D" not in candidate, f"{cid}: old D must not be a score factor")
        valid_factors = True
        for key in ("P", "W", "O", "T", "F", "B"):
            value = candidate.get(key)
            valid = type(value) is int and value in range(1, 5 if key == "B" else 4)
            require(valid, f"{cid}: invalid {key}")
            valid_factors = valid_factors and valid
        rv = candidate.get("R")
        valid_r = type(rv) in (int, float) and rv in (1, 1.5, 2)
        require(valid_r, f"{cid}: invalid R")
        score = candidate.get("score")
        valid_score = type(score) in (int, float) and math.isfinite(score)
        require(valid_score, f"{cid}: invalid score")
        if valid_score:
            scores.append(score)
        if valid_factors and valid_r and valid_score:
            expected = (candidate["P"] * candidate["W"] * candidate["O"] * candidate["T"] /
                        (candidate["F"] * candidate["B"] * rv))
            require(abs(score - round(expected, 4)) < 0.000051, f"{cid}: wrong score")
        for unknown, factor, floor in (("technical_unknown", "F", 2), ("serving_unknown", "B", 3)):
            flag = candidate.get(unknown)
            require(type(flag) is bool, f"{cid}: missing {unknown}")
            if flag is True and type(candidate.get(factor)) is int:
                require(candidate[factor] >= floor, f"{cid}: unknown too cheaply scored in {factor}")
        for group, keys in FIELDS.items():
            section = candidate.get(group, {})
            for key in keys:
                value = section.get(key) if isinstance(section, dict) else None
                require(isinstance(value, str) and bool(value.strip()), f"{cid}: missing {group}.{key}")
        claims = candidate.get("claims", [])
        if not isinstance(claims, list):
            problems.append(f"{cid}: claims must be a list")
            claims = []
        require(bool(claims), f"{cid}: no new source claims")
        primary = False
        for claim in claims:
            if not isinstance(claim, dict):
                problems.append(f"{cid}: malformed claim")
                continue
            for key in ("claim", "url", "quote", "source_kind", "saved_page", "scope_and_date"):
                require(isinstance(claim.get(key), str) and bool(claim[key].strip()),
                        f"{cid}: claim missing {key}")
            require(str(claim.get("url", "")).startswith(("https://", "http://")), f"{cid}: invalid URL")
            kind = claim.get("source_kind")
            require(kind in ("primary", "vendor", "secondary"), f"{cid}: invalid provenance")
            primary = primary or kind in ("primary", "vendor")
            page = (workspace / str(claim.get("saved_page", ""))).resolve()
            allowed = (workspace / "state/desk/pages").resolve()
            if allowed not in page.parents or not page.is_file():
                problems.append(f"{cid}: missing/out-of-bounds saved page")
                continue
            quote = claim.get("quote")
            require(isinstance(quote, str) and len(quote.strip()) >= 12 and
                    normal(quote) in normal(page.read_text(errors="replace")), f"{cid}: quote not on saved page")
        require(primary, f"{cid}: no original/vendor primary support")
    require(sorted(str(cid) for cid in ids) == sorted(names), "candidate ids missing/duplicated")
    require(ranks == list(range(1, count + 1)), "candidate array must follow new ranks 1..n")
    require(scores == sorted(scores, reverse=True), "not ranked by new index")
    cases = result.get("regressions", [])
    if not isinstance(cases, list):
        return problems + ["regressions must be a list"]
    actual = {case.get("id"): case for case in cases if isinstance(case, dict)}
    require(len(cases) == len(GUARDS) and set(actual) == set(GUARDS), "regression cases missing/duplicated")
    for case_id, expectations in GUARDS.items():
        case = actual.get(case_id, {})
        for key, value in expectations.items():
            require(type(case.get(key)) is int and case[key] == value, f"regression {case_id}: {key}")
        require(case.get("excluded_for_sector") is False, f"regression {case_id}: blanket sector exclusion")
        require(isinstance(case.get("reason"), str) and bool(case["reason"].strip()),
                f"regression {case_id}: missing reason")
    require(isinstance(result.get("recommendation"), str) and bool(result["recommendation"].strip()),
            "missing recommendation")
    return problems


if __name__ == "__main__":
    try:
        issues = check(Path("state/scan"))
    except (OSError, ValueError, TypeError) as error:
        issues = [f"cannot check output: {error}"]
    print(json.dumps({"verdict": "revise" if issues else "pass", "problems": issues}))
    sys.exit(bool(issues))
