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


# One step on each factor's frozen scale; flip points move one factor of one candidate by one step.
SCALE = {"P": (1, 2, 3), "W": (1, 2, 3), "O": (1, 2, 3), "T": (1, 2, 3), "F": (1, 2, 3),
         "B": (1, 2, 3, 4), "R": (1, 1.5, 2)}
TIE = 0.000051
LENS = {"low": 1, "medium": 1.5, "high": 2}
# Each F, T and R reason names the part it rated (FACTOR CALLS in the screen and audit prompts).
F_LINE = re.compile(r"Hardest part:\s*\S.{2,}?\s+Technique shown:\s*(yes|no)\b.*?"
                    r"Inputs available:\s*(yes|no|unknown)\b", re.S | re.I)
T_LINE = re.compile(r"Core task:\s*\S.{2,}?\s+People:\s*(approval|substantive|none)\b", re.S | re.I)
R_LINE = re.compile(r"Lens:\s*(low|medium|high)\b.*?In R:\s*\S.*?In O:\s*\S", re.S | re.I)
# The O reason starts from the baseline and names the only two facts that move it (O MOVES).
O_LINE = re.compile(r"Baseline:\s*O\s*=\s*([123])\b.*?Host suite:\s*(\S.*?)\s+Segment:\s*(\S.*)",
                    re.S | re.I)


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


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def score_of(values):
    return round(values["P"] * values["W"] * values["O"] * values["T"] /
                 (values["F"] * values["B"] * values["R"]), 4)


def level(value):
    return f"{value:g}"


def flips(upper, lower):
    """Every one-step change of one factor that reorders (swaps) or levels (ties) a neighbouring pair."""
    found = []
    for moved, other, is_upper in ((upper, lower, True), (lower, upper, False)):
        for factor, scale in SCALE.items():
            at = scale.index(moved[factor])
            for to in (scale[i] for i in (at - 1, at + 1) if 0 <= i < len(scale)):
                after = score_of({**moved, factor: to})
                if abs(after - other["score"]) < TIE:
                    result = "ties"
                elif (after < other["score"]) if is_upper else (after > other["score"]):
                    result = "swaps"
                else:
                    continue
                found.append({"id": moved["id"], "factor": factor, "from": moved[factor], "to": to,
                              "score_after": after, "result": result})
    return found


def flip_table(ordered):
    return [{"ranks": [k, k + 1], "upper": upper["id"], "lower": lower["id"],
             "upper_score": upper["score"], "lower_score": lower["score"],
             "tied": abs(upper["score"] - lower["score"]) < TIE, "calls": flips(upper, lower)}
            for k, (upper, lower) in enumerate(zip(ordered, ordered[1:], strict=False), 1)]


def check_flips(root, result, ordered, require):
    """One named call per neighbouring pair, its arithmetic, and the same calls in shortlist.md."""
    points = result.get("flip_points")
    if not isinstance(points, list):
        require(False, "missing flip_points")
        return
    require(len(points) == len(ordered) - 1, "flip_points must name one call per neighbouring pair")
    shortlist = root / "shortlist.md"
    text = shortlist.read_text(errors="replace") if shortlist.is_file() else ""
    section = re.search(r"^## Flip points[ \t]*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    require(bool(section), "shortlist.md: missing '## Flip points' section")
    listed = re.sub(r"\s*(?:->|\u2192)\s*", "->", normal(section.group(1))) if section else ""
    for row, point in zip(flip_table(ordered), points, strict=False):
        label = f"flip {row['ranks'][0]}-{row['ranks'][1]}"
        if not isinstance(point, dict):
            require(False, f"{label}: must be an object")
            continue
        require(point.get("ranks") == row["ranks"] and point.get("upper") == row["upper"] and
                point.get("lower") == row["lower"], f"{label}: wrong pair")
        require(number(point.get("upper_score")) and number(point.get("lower_score")) and
                abs(point["upper_score"] - row["upper_score"]) < TIE and
                abs(point["lower_score"] - row["lower_score"]) < TIE, f"{label}: wrong scores")
        require(point.get("tied") is row["tied"], f"{label}: wrong tied flag")
        if row["tied"]:
            require(isinstance(point.get("tie_break"), str) and bool(point["tie_break"].strip()),
                    f"{label}: a tied pair needs its tie-break")
        require(isinstance(point.get("why"), str) and bool(point["why"].strip()), f"{label}: missing why")
        call = point.get("call")
        if call is None:
            require(not row["calls"], f"{label}: a one-step call reorders or ties this pair; name one")
            require(point.get("result") == "none", f"{label}: wrong result")
            continue
        call = call if isinstance(call, dict) else {}
        match = [option for option in row["calls"] if option["id"] == call.get("id") and
                 option["factor"] == call.get("factor") and number(call.get("from")) and
                 number(call.get("to")) and option["from"] == call["from"] and option["to"] == call["to"]]
        require(bool(match), f"{label}: the call is not one step that reorders or ties the pair")
        if match:
            require(number(point.get("score_after")) and abs(point["score_after"] - match[0]["score_after"]) < TIE
                    and point.get("result") == match[0]["result"], f"{label}: wrong score_after or result")
            named = f"{call['id']} {call['factor']} {level(call['from'])}->{level(call['to'])}"
            require(named in listed, f"{label}: shortlist.md flip points do not name {named}")


def check_parts(cid, candidate, reasons, require):
    """F, T and R reasons name the part they rated, and the level follows from it; O names its two moves."""
    f_line = F_LINE.search(reasons.get("F") or "")
    require(bool(f_line), f"{cid}: F reason must name 'Hardest part:', 'Technique shown:' and 'Inputs available:'")
    if f_line and candidate.get("F") in (1, 2, 3):
        open_part = f_line.group(1).lower() == "no" or f_line.group(2).lower() != "yes"
        require((candidate["F"] == 3) == open_part,
                f"{cid}: F must be 3 exactly when the technique is not shown or inputs are not available")
    t_line = T_LINE.search(reasons.get("T") or "")
    require(bool(t_line), f"{cid}: T reason must name 'Core task:' and 'People: approval|substantive|none'")
    if t_line and candidate.get("T") in (1, 2, 3):
        allowed = (1, 2) if t_line.group(1).lower() == "substantive" else (1, 3)
        require(candidate["T"] in allowed, f"{cid}: T does not follow from the people's work it names")
    r_line = R_LINE.search(reasons.get("R") or "")
    require(bool(r_line), f"{cid}: R reason must name 'Lens:', 'In R:' and 'In O:'")
    if r_line and number(candidate.get("R")):
        require(candidate["R"] >= LENS[r_line.group(1).lower()], f"{cid}: R below the lens level")
    o_line = O_LINE.search(reasons.get("O") or "")
    require(bool(o_line), f"{cid}: O reason must name 'Baseline: O=<n>', 'Host suite:' and 'Segment:'")
    if o_line and candidate.get("O") in (1, 2, 3):
        host = o_line.group(2).strip().lower().rstrip(".")
        segment = o_line.group(3).strip().lower()
        if segment.startswith("not shown"):
            require(candidate["O"] == 2, f"{cid}: O must be 2 while a lens-named segment is not shown served")
        elif host == "none" and segment.startswith("no segment"):
            require(candidate["O"] == int(o_line.group(1)),
                    f"{cid}: O moved from the baseline without a host-suite or segment fact")


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
    ids, ranks, scores, sound = [], [], [], []
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
            sound.append(candidate)
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
        reasons = candidate.get("factor_reasons")
        check_parts(cid, candidate, reasons if isinstance(reasons, dict) else {}, require)
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
    if len(sound) == len(candidates) == count and ranks == list(range(1, count + 1)):
        check_flips(root, result, sound, require)
    else:
        require(isinstance(result.get("flip_points"), list), "missing flip_points")
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


def flips_report(root):
    """--flips: every one-step call that reorders or ties each neighbouring pair of serving.json."""
    candidates = json.loads((Path(root) / "serving.json").read_text()).get("candidates", [])
    ordered = sorted(candidates, key=lambda candidate: candidate["rank"])
    for candidate in ordered:
        for factor, scale in SCALE.items():
            if not (number(candidate.get(factor)) and type(candidate[factor]) is not bool and
                    candidate[factor] in scale):
                raise ValueError(f"{candidate.get('id')}: invalid {factor}")
    return flip_table(ordered)


if __name__ == "__main__":
    if sys.argv[1:] == ["--flips"]:
        try:
            print(json.dumps(flips_report(Path("state/scan")), indent=1))
        except (OSError, ValueError, TypeError, KeyError) as error:
            print(json.dumps({"error": f"cannot list flip points: {error}"}))
            sys.exit(1)
        sys.exit(0)
    try:
        issues = check(Path("state/scan"))
    except (OSError, ValueError, TypeError) as error:
        issues = [f"cannot check output: {error}"]
    print(json.dumps({"verdict": "revise" if issues else "pass", "problems": issues}))
    sys.exit(bool(issues))
