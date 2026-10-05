#!/usr/bin/env python3
"""feature_screen's script steps (product role, queue #26). Standard library only; run from the
workspace root. Everything lives in state/feature/ (method.md says what each file holds).

  check_features.py setup --assets DIR [--VALUE VARIABLE ...]   copy the evidence, write input.md
  check_features.py rank                                       ranking.json by the fixed rule
  check_features.py check [--answer PART=VARIABLE ...] [--planted VARIABLE] [--run-id VARIABLE]
                                                               check.json, check.md, report.md, sample.md

Values arrive as the names of environment variables (the script agent's env filter), never as
text on the command line. The last line printed is the step's JSON (its structured output).

The check fails the run (status "fail") when any part left no usable output (its files missing,
invalid or an account-limit message, or its final answer such a message), when a rating is
missing, off its scale or not the one its sub-scores give, when a cited quote is not on the page
saved for it, when a "taken" rating rests on no checked web source, when a known-taken case
(planted: seed ids given to the check only, never to the agents) does not come out taken with
such a source, when the ranking is not the fixed rule's, or when a test design is incomplete.
"""
import argparse
import hashlib
import json
import os
import random
import re
import shutil
import sys
from pathlib import Path

ROOT = Path("state/feature")
EVIDENCE = ROOT / "evidence"
PAGES = ROOT / "pages"
LENSES = ("newness", "taken", "problem", "build")
TESTS = ("newness", "taken", "problem")  # the owner's three tests; build is the extra lens
SCALES = {"newness": ("strong", "medium", "weak"), "taken": ("taken", "partly", "open"),
          "problem": ("strong", "medium", "weak"), "build": ("strong", "medium", "weak")}
POINTS = {"newness": {"strong": 2, "medium": 1, "weak": 0}, "problem": {"strong": 2, "medium": 1, "weak": 0},
          "build": {"strong": 2, "medium": 1, "weak": 0}, "taken": {"open": 2, "partly": 1}}
GRADE = {"strong": 2, "medium": 1, "weak": 0}
YES = {"yes": 2, "partly": 1, "no": 0}
ACCESS = ("open", "approval", "gated")
MIN_CANDIDATES, MAX_CANDIDATES, TOP, SAMPLE = 8, 12, 3, 10
MIN_PLAYERS = 3
HOW = ("cite", "webfetch", "snippet")
QUALITY = ("primary", "secondary", "vendor", "listicle")
PARTS = ("generate", "newness", "taken", "problem", "build", "design")
NOT_PASSED = "__unwired__"  # what the workflow passes for an answer it could not find
# What a part says when its account or the service stopped it, instead of research (the same
# words as signal_grade's, opportunity_brief's and desk_check's checks, queue #23).
NON_ANSWER = re.compile(
    r"session limit|usage limit|weekly limit|daily limit|rate[ _-]?limit|limit (?:reached|exceeded)"
    r"|hit (?:your|the) (?:\w+ )?limit|quota|overloaded|too many requests|credit balance"
    r"|pool exhausted|try again later|resets? (?:at |in |on )?\d|api error|authentication_error"
    r"|oauth token|not logged in|/login|invalid api key|out of (?:extra )?usage|prompt is too long"
    r"|\Aerror: ",
    re.I)
PROVIDER_ERROR = re.compile(r"\[claude_code error\]", re.I)
SEED_LINE = re.compile(r"^\s*(S\d{1,2})\s*[:.)\-]\s*(.+)$")
CLAIM_ID = re.compile(r"^[CG]\d{1,3}$")


# ---- text ----------------------------------------------------------------------------------------

def norm(s):
    for a, b in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'),
                 ("\u2013", "-"), ("\u2014", "-"), ("\u00a0", " ")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def plain(s):
    """norm, lower case, and without markdown marks, for matching a quote copied from a file."""
    return re.sub(r"\s+", " ", re.sub(r"[*`_|#>]", " ", norm(s).lower())).strip()


def flat(text, limit=160):
    text = norm(text or "")
    return text if len(text) <= limit else text[:limit - 3] + "..."


def non_answer(text):
    """Why a part's text is no research ('' when it may be)."""
    text = (text or "").strip()
    if not text:
        return "empty"
    if PROVIDER_ERROR.match(text) or (
            len(text) <= 600 and text[0] not in "{[" and "```" not in text and NON_ANSWER.search(text)):
        return f'an account-limit or error message ("{flat(text)}")'
    return ""


def env_value(name):
    return os.environ.get(name) if name else None


def load_json(path):
    """(data, problem): problem is '' when the file is a usable JSON object."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None, f"{path} is missing"
    why = non_answer(text)
    if why:
        return None, f"{path} is {why}"
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, f"{path} is not valid JSON ({exc})"
    if not isinstance(data, dict):
        return None, f"{path} is not a JSON object"
    return data, ""


def text_problem(path):
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return f"{path} is missing"
    why = non_answer(text)
    return f"{path} is {why}" if why else ""


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def words(text):
    return len((text or "").split())


# ---- setup ---------------------------------------------------------------------------------------

def parse_seeds(text):
    seeds = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        m = SEED_LINE.match(line)
        if m:
            seeds.append({"id": m.group(1).upper(), "text": m.group(2).strip()})
        elif seeds:
            seeds[-1]["text"] += " " + line.strip()
        else:
            seeds.append({"id": "", "text": line.strip()})
    for n, seed in enumerate(seeds, 1):
        seed["id"] = seed["id"] or f"S{n}"
    return seeds


def setup(args):
    def value(flag):
        return (env_value(getattr(args, flag)) or "").strip()

    def stop(problem):
        print(json.dumps({"status": "not_ready", "seeds": [], "evidence_files": 0, "problems": [problem]}))
        return 0

    idea, problems_text, evidence_dir = value("idea"), value("problems"), value("evidence_dir")
    if not idea:
        return stop("no idea given")
    if not problems_text:
        return stop("no problems given: test 3 asks whether a feature fixes one of the idea's real problems")
    if not evidence_dir:
        return stop("no evidence_dir given")
    here = Path.cwd().resolve()
    src = Path(evidence_dir)
    src = (src if src.is_absolute() else here / src).resolve()
    try:
        src.relative_to(here)
    except ValueError:
        return stop(f"evidence_dir {evidence_dir} is outside the run workspace")
    if not src.is_dir():
        return stop(f"evidence_dir {evidence_dir} is not a folder in the run workspace")
    files = []
    for path in sorted(src.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(src)
        if any(part.startswith(".") for part in rel.parts) or path.stat().st_size > 5_000_000:
            continue
        dest = EVIDENCE / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        files.append({"file": f"evidence/{rel.as_posix()}", "bytes": path.stat().st_size})
    if not files:
        return stop(f"evidence_dir {evidence_dir} holds no readable files")
    seeds = parse_seeds(value("seeds"))
    ids = [s["id"] for s in seeds]
    if len(set(ids)) != len(ids):
        return stop("seed ids repeat: " + ", ".join(ids))
    if len(seeds) > MAX_CANDIDATES:
        return stop(f"{len(seeds)} seeds: at most {MAX_CANDIDATES} candidates fit")
    players, build_on = value("players"), value("build_on")
    lines = ["# Feature screen input", "", "## The idea", "", idea, "", "## Its real problems (test 3)", "",
             problems_text, "", "## Seed candidates (include each, do not favour them)", ""]
    lines += [f"- {s['id']}: {s['text']}" for s in seeds] or ["(none)"]
    lines += ["", "## Players to check in test 2 (big platforms and close rivals)", "",
              players or "(none given: take them from the evidence)", "",
              "## What the idea can build on (build lens)", "", build_on or "(none given: see the evidence)",
              "", "## Evidence files (state/feature/evidence/)", ""]
    lines += [f"- {f['file']} ({f['bytes']} bytes)" for f in files]
    (ROOT / "input.md").write_text("\n".join(lines) + "\n")
    (ROOT / "lenses").mkdir(parents=True, exist_ok=True)
    assets = Path(args.assets)
    sha = {}
    for name in ("check_features.py", "cite.py", "method.md"):
        sha[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    (ROOT / "setup.json").write_text(json.dumps({
        "run_id": value("run_id"), "assets_dir": str(assets), "sha256": sha, "seeds": seeds,
        "evidence": files}, indent=1))
    print(json.dumps({"status": "ready", "seeds": ids, "evidence_files": len(files), "problems": []}))
    return 0


# ---- ratings and the fixed ranking ---------------------------------------------------------------

def rule_rating(lens, sub):
    """The rating a lens's sub-scores give by method.md's rule: (rating, problem). taken has no
    sub-score rule (its sub is the players checked), so it returns (None, '')."""
    sub = sub if isinstance(sub, dict) else {}
    if lens == "newness":
        vals = [sub.get(k) for k in ("seconds", "new", "fits")]
        if any(v not in YES for v in vals):
            return None, "sub needs seconds, new and fits, each yes / partly / no"
        total = sum(YES[v] for v in vals)
        return ("strong" if total >= 5 else "medium" if total >= 3 else "weak"), ""
    if lens == "problem":
        vals = [sub.get(k) for k in ("reach", "money")]
        if any(v not in GRADE for v in vals):
            return None, "sub needs reach and money, each strong / medium / weak"
        return max(vals, key=lambda v: GRADE[v]), ""
    if lens == "build":
        fit, access = sub.get("assets_fit"), sub.get("data_access")
        if fit not in GRADE or access not in ACCESS:
            return None, "sub needs assets_fit (strong / medium / weak) and data_access (open / approval / gated)"
        if access == "gated" or fit == "weak":
            return "weak", ""
        return ("strong" if fit == "strong" and access == "open" else "medium"), ""
    return None, ""


def ratings_of(lens_data):
    """candidate id -> list of rating rows."""
    out = {}
    for row in (lens_data or {}).get("ratings") or []:
        if isinstance(row, dict):
            out.setdefault(str(row.get("candidate", "")).strip(), []).append(row)
    return out


def effective(lens, row):
    """The rating used for ranking: the rule's when the sub-scores give one, else the one written."""
    rated, _ = rule_rating(lens, row.get("sub"))
    return rated or row.get("rating")


def rank_rows(candidates, lenses):
    rows = []
    for order, cand in enumerate(candidates):
        cid = cand.get("id")
        rating = {}
        for lens in LENSES:
            found = ratings_of(lenses.get(lens)).get(cid) or []
            rating[lens] = effective(lens, found[0]) if len(found) == 1 else None
        out = rating["taken"] not in POINTS["taken"]
        points = sum(POINTS[lens].get(rating[lens], 0) for lens in LENSES)
        qualified = POINTS["newness"].get(rating["newness"], 0) >= 1 and POINTS["problem"].get(rating["problem"], 0) >= 1
        rows.append({"id": cid, "name": cand.get("name", ""), "seed_id": cand.get("seed_id"), "ratings": rating,
                     "points": points, "qualified": qualified, "out": out, "order": order})
    def key(r):
        return (r["out"], not r["qualified"], -r["points"],
                -POINTS["newness"].get(r["ratings"]["newness"], 0), -POINTS["problem"].get(r["ratings"]["problem"], 0),
                -POINTS["taken"].get(r["ratings"]["taken"], 0), -POINTS["build"].get(r["ratings"]["build"], 0),
                r["order"])

    rows.sort(key=key)
    for n, row in enumerate(rows, 1):
        row["rank"] = n
    top = [r["id"] for r in rows if not r["out"]][:TOP]
    return rows, top


def load_parts():
    candidates, problem = load_json(ROOT / "candidates.json")
    lenses, problems = {}, [problem] if problem else []
    for lens in LENSES:
        data, problem = load_json(ROOT / "lenses" / f"{lens}.json")
        lenses[lens] = data
        if problem:
            problems.append(problem)
    cands = [c for c in ((candidates or {}).get("candidates") or []) if isinstance(c, dict)]
    return cands, lenses, problems


def rank(args):
    cands, lenses, problems = load_parts()
    if not cands or any(lenses[lens] is None for lens in LENSES):
        print(json.dumps({"status": "not_ranked", "top": [], "ranking_path": "", "problems":
                          problems or ["candidates.json holds no candidates"]}))
        return 0
    rows, top = rank_rows(cands, lenses)
    (ROOT / "ranking.json").write_text(json.dumps({"rule": "feature_screen/1", "top": top, "rows": rows}, indent=1))
    print(json.dumps({"status": "ranked" if len(top) == TOP else "short", "top": top,
                      "ranking_path": str(ROOT / "ranking.json"), "problems": [] if len(top) == TOP else
                      [f"only {len(top)} candidates are not taken: fewer than {TOP} to test"]}))
    return 0


# ---- claims ----------------------------------------------------------------------------------------

def page_file(url):
    return PAGES / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt")


def source_text(url):
    """(text, problem) of the page or evidence file a claim cites, as the check can read it."""
    if url.startswith("evidence/"):
        rel = Path(url)
        if ".." in rel.parts:
            return None, f"{url} leaves the evidence folder"
        try:
            return (ROOT / rel).read_text(errors="replace"), ""
        except OSError:
            return None, f"{url} is not an evidence file"
    path = page_file(url)
    try:
        head, _, text = path.read_text(errors="replace").partition("\n")
        meta = json.loads(head)
    except (OSError, ValueError):
        return None, "no saved page (cite.py never read this URL)"
    if str(meta.get("http")) != "200":
        return None, f"the saved page answered {meta.get('http')}"
    return text, ""


def verify_claim(claim):
    """'' when a cite claim's words are on its saved page or evidence file, else why not."""
    url, quote = str(claim.get("url") or "").strip(), str(claim.get("quote") or "")
    if not url or not quote.strip():
        return "no url or no quote"
    text, problem = source_text(url)
    if problem:
        return problem
    want = plain(quote)
    if want and want in plain(text):
        return ""
    return "quote not on the saved page" if not url.startswith("evidence/") else "quote not in the evidence file"


def check_claims(label, data, problems, notes):
    """Validates a part's claims and guesses; returns ({id: claim with 'verified'}, {id: guess})."""
    claims, guesses = {}, {}
    for claim in (data or {}).get("claims") or []:
        if not isinstance(claim, dict):
            problems.append(f"{label}: a claim is not an object")
            continue
        cid = str(claim.get("id", "")).strip()
        if not cid or cid in claims:
            problems.append(f"{label}: claim id {cid or '(none)'} missing or repeated")
            continue
        missing = [k for k in ("claim", "url", "how", "quality") if not str(claim.get(k) or "").strip()]
        if missing:
            problems.append(f"{label} {cid}: no {', '.join(missing)}")
        how, quality = claim.get("how"), claim.get("quality")
        if how not in HOW:
            problems.append(f"{label} {cid}: how {how!r} is not cite, webfetch or snippet")
        if quality not in QUALITY:
            problems.append(f"{label} {cid}: quality {quality!r} is not primary, secondary, vendor or listicle")
        claim = dict(claim, verified=False, why="")
        if how == "cite":
            n = words(claim.get("quote"))
            if n and not 6 <= n <= 40:
                notes.append(f"{label} {cid}: quote of {n} words (method asks 6-40)")
            why = verify_claim(claim)
            claim["verified"], claim["why"] = not why, why
            if why:
                problems.append(f"{label} {cid}: cited, but {why} ({flat(claim.get('url'), 100)})")
        claims[cid] = claim
    for guess in (data or {}).get("guesses") or []:
        gid = str((guess or {}).get("id", "")).strip() if isinstance(guess, dict) else ""
        if not gid or gid in guesses or not str(guess.get("guess") or "").strip():
            problems.append(f"{label}: guess {gid or '(none)'} missing, repeated or empty")
            continue
        guesses[gid] = guess
    return claims, guesses


def strong_web(claim):
    """A claim that can carry a taken rating: cite-checked, from a web page, primary or secondary."""
    return (bool(claim) and claim.get("verified") and claim.get("how") == "cite"
            and str(claim.get("url", "")).startswith("http") and claim.get("quality") in ("primary", "secondary"))


def counts_as_support(claim):
    return bool(claim) and claim.get("how") in ("cite", "webfetch") and claim.get("quality") != "listicle" and (
        claim.get("how") != "cite" or claim.get("verified"))


def row_refs(row):
    claims = [str(c) for c in (row.get("claims") or [])]
    guesses = [str(g) for g in (row.get("guesses") or [])]
    sub = row.get("sub") if isinstance(row.get("sub"), dict) else {}
    for player in sub.get("checked") or []:
        if isinstance(player, dict):
            claims += [str(c) for c in (player.get("claims") or [])]
    return claims, guesses


def taken_problem(row, claims):
    """Why a taken rating is not carried by a checked web source ('' when it is)."""
    refs, _ = row_refs(row)
    if any(strong_web(claims.get(c)) for c in refs):
        return ""
    return "rated taken, but no cited claim from a web page (primary or secondary) whose words are on its saved page"


# ---- the check -------------------------------------------------------------------------------------

def check(args):
    problems, notes = [], []
    run_id = (env_value(args.run_id) or "").strip()
    setup_data, problem = load_json(ROOT / "setup.json")
    if problem:
        problems.append("the setup did not finish: " + problem)
        setup_data = {}
    elif run_id and setup_data.get("run_id") and setup_data.get("run_id") != run_id:
        problems.append("state/feature holds another run's screen: run in a fresh workspace")
    planted = [p.strip().upper() for p in re.split(r"[,\s]+", env_value(args.planted) or "") if p.strip()]

    # 1. every part left usable output, and no final answer is a limit message
    answers = {}
    for item in args.answer:
        part, _, var = item.partition("=")
        answers[part] = env_value(var)
    for part in PARTS:
        answer = answers.get(part)
        if answer is None or answer == NOT_PASSED:
            continue
        why = non_answer(answer)
        if why:
            problems.append(f"{part}: its final answer is {why}")
    for path in (ROOT / "candidates.md", ROOT / "tests.md", *[ROOT / "lenses" / f"{lens}.md" for lens in LENSES]):
        problem = text_problem(path)
        if problem:
            problems.append(problem)
    cands, lenses, load_problems = load_parts()
    problems += load_problems
    tests_data, problem = load_json(ROOT / "tests.json")
    if problem:
        problems.append(problem)

    # 2. candidates
    ids = [str(c.get("id", "")).strip() for c in cands]
    if not MIN_CANDIDATES <= len(cands) <= MAX_CANDIDATES:
        problems.append(f"{len(cands)} candidates: the method asks for {MIN_CANDIDATES}-{MAX_CANDIDATES}")
    if len(set(ids)) != len(ids) or not all(ids):
        problems.append("candidate ids are missing or repeat: " + ", ".join(ids))
    seeds = {s["id"]: s for s in (setup_data.get("seeds") or [])}
    by_seed = {str(c.get("seed_id") or "").upper(): c for c in cands if c.get("seed_id")}
    for sid in seeds:
        if sid not in by_seed:
            problems.append(f"seed {sid} is not among the candidates")
    for cand in cands:
        cid = cand.get("id")
        for key in ("name", "what_user_sees", "job"):
            if not str(cand.get(key) or "").strip():
                problems.append(f"candidate {cid}: no {key}")
        evidence = [e for e in (cand.get("evidence") or []) if isinstance(e, dict)]
        if not evidence and not cand.get("seed_id"):
            problems.append(f"candidate {cid}: no evidence quote (only a seed may have none)")
        for item in evidence:
            file, quote = str(item.get("file") or ""), str(item.get("quote") or "")
            if not file.startswith("evidence/"):
                problems.append(f"candidate {cid}: evidence file {file!r} is not in evidence/")
                continue
            text, problem = source_text(file)
            if problem or plain(quote) not in plain(text or "") or not plain(quote):
                problems.append(f"candidate {cid}: evidence quote not in {file} (\"{flat(quote, 80)}\")")

    # 3. claims, guesses and ratings, lens by lens
    registry, guesses_of = {}, {}
    for lens in LENSES:
        claims, guesses = check_claims(lens, lenses.get(lens), problems, notes)
        registry[lens], guesses_of[lens] = claims, guesses
        if lenses.get(lens) is None:
            continue
        rows = ratings_of(lenses[lens])
        for extra in sorted(set(rows) - set(ids)):
            problems.append(f"{lens}: rates {extra or '(no id)'}, which is not a candidate")
        for cid in ids:
            found = rows.get(cid) or []
            if len(found) != 1:
                problems.append(f"{lens}: candidate {cid} has {len(found)} ratings (needs exactly one)")
                continue
            row = found[0]
            rating = row.get("rating")
            if rating not in SCALES[lens]:
                problems.append(f"{lens} {cid}: rating {rating!r} is not one of {', '.join(SCALES[lens])}")
            rated, why = rule_rating(lens, row.get("sub"))
            if why:
                problems.append(f"{lens} {cid}: {why}")
            elif rated and rated != rating:
                problems.append(f"{lens} {cid}: rated {rating}, but its sub-scores give {rated}")
            refs, grefs = row_refs(row)
            for ref in refs:
                if ref not in claims:
                    problems.append(f"{lens} {cid}: names claim {ref}, which is not in its claims")
            for ref in grefs:
                if ref not in guesses:
                    problems.append(f"{lens} {cid}: names guess {ref}, which is not in its guesses")
            if not any(counts_as_support(claims.get(r)) for r in refs) and not any(g in guesses for g in grefs):
                problems.append(f"{lens} {cid}: no source and no labelled guess behind the rating "
                                "(snippets and listicles do not count alone)")
            if not str(row.get("reason") or "").strip():
                problems.append(f"{lens} {cid}: no reason")
            if lens == "taken":
                sub = row.get("sub") if isinstance(row.get("sub"), dict) else {}
                players = {str(p.get("player", "")).strip().lower() for p in (sub.get("checked") or [])
                           if isinstance(p, dict) and str(p.get("player", "")).strip()}
                if rating == "taken":
                    problem = taken_problem(row, claims)
                    if problem:
                        problems.append(f"taken {cid}: {problem}")
                elif len(players) < MIN_PLAYERS:
                    problems.append(f"taken {cid}: rated {rating} after checking {len(players)} players "
                                    f"(needs at least {MIN_PLAYERS})")
        for item in (lenses[lens].get("inaccessible") or []):
            if isinstance(item, dict):
                notes.append(f"{lens}: inaccessible {flat(item.get('url'), 90)} ({item.get('http', '?')})")

    # 4. known-taken cases (planted, given to the check only)
    planted_result = {}
    taken_rows = ratings_of(lenses.get("taken"))
    for sid in planted:
        cand = by_seed.get(sid)
        if cand is None:
            problems.append(f"known-taken case {sid} is not among the candidates")
            planted_result[sid] = "missing"
            continue
        rows = taken_rows.get(cand.get("id")) or []
        row = rows[0] if len(rows) == 1 else {}
        rating = row.get("rating")
        problem = taken_problem(row, registry.get("taken", {})) if rating == "taken" else ""
        if rating != "taken":
            problems.append(f"known-taken case {sid} ({cand.get('id')} {cand.get('name')}) came out {rating}, not taken")
        elif problem:
            problems.append(f"known-taken case {sid} ({cand.get('id')}): {problem}")
        planted_result[sid] = {"candidate": cand.get("id"), "rating": rating, "sourced": rating == "taken" and not problem}

    # 5. the ranking is the fixed rule's
    rows, top = rank_rows(cands, lenses) if cands else ([], [])
    ranking, problem = load_json(ROOT / "ranking.json")
    if problem:
        problems.append(problem)
    elif ranking.get("top") != top:
        problems.append(f"ranking.json's top {ranking.get('top')} is not the fixed rule's {top}")
    if len(top) < TOP:
        problems.append(f"only {len(top)} candidates are not taken: fewer than {TOP} to test")

    # 6. test designs for exactly the top three
    tests = [t for t in ((tests_data or {}).get("tests") or []) if isinstance(t, dict)]
    tclaims, tguesses = check_claims("tests", tests_data, problems, notes) if tests_data else ({}, {})
    tested = [str(t.get("candidate", "")).strip() for t in tests]
    if tests_data is not None and sorted(tested) != sorted(top):
        problems.append(f"tests cover {tested}, not the top three {top}")
    for test in tests:
        cid = test.get("candidate")
        for key in ("riskiest_assumption", "why_riskiest"):
            if not str(test.get(key) or "").strip():
                problems.append(f"tests {cid}: no {key}")
        rungs = {r.get("rung"): r for r in (test.get("rungs") or []) if isinstance(r, dict)}
        for number in (1, 2):
            rung = rungs.get(number)
            if rung is None:
                problems.append(f"tests {cid}: no rung {number}")
                continue
            label = f"tests {cid} rung {number}"
            for key in ("method", "metric", "pass_rule", "kill_rule"):
                if not str(rung.get(key) or "").strip():
                    problems.append(f"{label}: no {key}")
            if not is_number(rung.get("threshold")):
                problems.append(f"{label}: threshold is not a number")
            for key in ("sample", "duration_days"):
                if not is_number(rung.get(key)) or rung.get(key) <= 0:
                    problems.append(f"{label}: {key} is not a positive number")
            basis = [str(b) for b in (rung.get("basis") or [])]
            if not basis:
                problems.append(f"{label}: no basis for its numbers")
            for ref in basis:
                lens, _, rid = ref.partition(":")
                if ref.startswith("evidence/"):
                    if source_text(ref)[1]:
                        problems.append(f"{label}: basis {ref} is not an evidence file")
                elif rid and lens in registry:
                    if rid not in registry[lens] and rid not in guesses_of[lens]:
                        problems.append(f"{label}: basis {ref} is not in the {lens} lens")
                elif ref not in tclaims and ref not in tguesses:
                    problems.append(f"{label}: basis {ref} is not a claim or guess in tests.json")
            if number == 1:
                if rung.get("kind") not in ("free", "first-party"):
                    problems.append(f"{label}: kind {rung.get('kind')!r} is not free or first-party")
                if rung.get("cost_usd") != 0:
                    problems.append(f"{label}: the cheapest rung must cost 0 (cost_usd {rung.get('cost_usd')!r})")
                if not isinstance(rung.get("needs_owner"), bool):
                    problems.append(f"{label}: needs_owner is not true or false")
            else:
                if rung.get("kind") not in ("paid", "contact"):
                    problems.append(f"{label}: kind {rung.get('kind')!r} is not paid or contact")
                if rung.get("owner_go_ahead") is not True:
                    problems.append(f"{label}: a paid or contact rung must be marked owner_go_ahead true")
                if rung.get("kind") == "paid" and (not is_number(rung.get("budget_usd")) or rung.get("budget_usd") <= 0):
                    problems.append(f"{label}: a paid rung needs budget_usd")

    # 7. results
    all_claims = [(lens, cid, c) for lens in LENSES for cid, c in registry[lens].items()]
    all_claims += [("tests", cid, c) for cid, c in tclaims.items()]
    counts = {"candidates": len(cands), "claims": len(all_claims),
              "cite_verified": sum(1 for _, _, c in all_claims if c.get("verified")),
              "webfetch": sum(1 for _, _, c in all_claims if c.get("how") == "webfetch"),
              "snippet": sum(1 for _, _, c in all_claims if c.get("how") == "snippet"),
              "guesses": sum(len(g) for g in guesses_of.values()) + len(tguesses),
              "pages_saved": len(list(PAGES.glob("*.txt"))) if PAGES.is_dir() else 0}
    status = "pass" if not problems else "fail"
    sample = draw_sample(all_claims, run_id)
    result = {"status": status, "rule": "feature_screen/1", "run_id": run_id, "problems": problems, "notes": notes,
              "counts": counts, "top": top, "planted": planted_result, "ranking": rows,
              "sample": [f"{lens}:{cid}" for lens, cid, _ in sample]}
    (ROOT / "check.json").write_text(json.dumps(result, indent=1))
    (ROOT / "check.md").write_text(check_md(result))
    (ROOT / "sample.md").write_text(sample_md(sample, run_id))
    (ROOT / "report.md").write_text(report_md(result, cands, lenses, registry, guesses_of, tests, tclaims, tguesses))
    names = {c.get("id"): c.get("name") for c in cands}
    print(json.dumps({"status": status, "report_path": str(ROOT / "report.md"), "check_path": str(ROOT / "check.md"),
                      "sample_path": str(ROOT / "sample.md"), "shortlist": [f"{t} {names.get(t, '')}" for t in top],
                      "candidates": len(cands), "claims": counts["claims"], "planted": planted_result,
                      "problems": problems}))
    return 0


def draw_sample(all_claims, run_id):
    """SAMPLE claims for the hand check, seeded by the run id: web pages checked by cite first."""
    rng = random.Random(hashlib.sha256((run_id or "feature_screen").encode()).hexdigest())
    web = [c for c in all_claims if c[2].get("how") == "cite" and str(c[2].get("url", "")).startswith("http")]
    rest = [c for c in all_claims if c not in web]
    picked = rng.sample(web, min(SAMPLE, len(web)))
    if len(picked) < SAMPLE:
        picked += rng.sample(rest, min(SAMPLE - len(picked), len(rest)))
    return picked


# ---- writing -----------------------------------------------------------------------------------------

def cell(text):
    return flat(str(text or ""), 400).replace("|", "/")


def check_md(result):
    lines = [f"# feature_screen check: {result['status'].upper()}", "",
             f"Rule {result['rule']}; run {result['run_id'] or '(no id)'}.", "",
             "Counts: " + ", ".join(f"{k} {v}" for k, v in result["counts"].items()), "",
             f"Top three by the fixed rule: {', '.join(result['top']) or '(none)'}", ""]
    if result["planted"]:
        lines += ["Known-taken cases: " + "; ".join(
            f"{k} -> {v if isinstance(v, str) else v['candidate'] + ' ' + str(v['rating']) + (' sourced' if v['sourced'] else ' NOT sourced')}"
            for k, v in result["planted"].items()), ""]
    lines += ["## Problems", ""] + ([f"- {p}" for p in result["problems"]] or ["(none)"])
    lines += ["", "## Notes", ""] + ([f"- {n}" for n in result["notes"]] or ["(none)"])
    return "\n".join(lines) + "\n"


def sample_md(sample, run_id):
    lines = [f"# Hand-check sample ({len(sample)} claims, seeded by run {run_id or '(no id)'})", "",
             "For each: open the saved page and say whether the claim holds on it (holds / not on page / "
             "page says less / contradicted).", ""]
    for n, (lens, cid, c) in enumerate(sample, 1):
        url = str(c.get("url", ""))
        saved = url if url.startswith("evidence/") else str(page_file(url))
        lines += [f"## {n}. {lens}:{cid} (candidate {c.get('candidate', '?')})", "",
                  f"- claim: {flat(c.get('claim'), 600)}", f"- quote: \"{flat(c.get('quote'), 600)}\"",
                  f"- url: {url}", f"- saved: {saved}", f"- date: {c.get('date', '?')}; quality {c.get('quality')}; "
                  f"how {c.get('how')}; script check: {'quote on page' if c.get('verified') else c.get('why') or 'not cite-checked'}",
                  "- verdict: ", ""]
    return "\n".join(lines) + "\n"


def report_md(result, cands, lenses, registry, guesses_of, tests, tclaims, tguesses):
    by_id = {c.get("id"): c for c in cands}
    rows = {r["id"]: r for r in result["ranking"]}

    def rated(lens, cid):
        found = ratings_of(lenses.get(lens)).get(cid) or []
        return found[0] if len(found) == 1 else {}

    def sources(lens, row):
        refs, grefs = row_refs(row)
        out = []
        for ref in dict.fromkeys(refs):
            c = registry[lens].get(ref)
            if c:
                mark = "checked" if c.get("verified") else c.get("how")
                out.append(f"[{lens}:{ref}] {cell(c.get('claim'))} ({cell(c.get('url'))}, {c.get('date', '?')}, {mark})")
        for ref in dict.fromkeys(grefs):
            g = guesses_of[lens].get(ref)
            if g:
                out.append(f"[{lens}:{ref}] GUESS: {cell(g.get('guess'))}")
        return out

    lines = [f"# Feature screen report ({result['status']})", "",
             "Every rating below follows method.md (feature_screen/1); the order is the fixed rule's, "
             "not anyone's pick. Sources are cited claims (words checked on the saved page when marked "
             "checked) or labelled guesses.", ""]
    lines += ["## Shortlist", ""]
    for n, cid in enumerate(result["top"], 1):
        c, r = by_id.get(cid, {}), rows.get(cid, {})
        lines += [f"{n}. **{cid} {c.get('name', '')}**: {cell(c.get('what_user_sees'))} "
                  f"(newness {r.get('ratings', {}).get('newness')}, taken {r.get('ratings', {}).get('taken')}, "
                  f"problem {r.get('ratings', {}).get('problem')}, build {r.get('ratings', {}).get('build')}; "
                  f"{r.get('points')} points)"]
    lines += ["", "## All candidates, in rank order", "",
              "| rank | candidate | seed | newness | taken | problem | build | points | status |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in result["ranking"]:
        status = "out (taken)" if r["out"] else ("qualified" if r["qualified"] else "below must-have")
        rt = r["ratings"]
        lines.append(f"| {r['rank']} | {r['id']} {cell(r['name'])} | {r.get('seed_id') or ''} | {rt['newness']} | "
                     f"{rt['taken']} | {rt['problem']} | {rt['build']} | {r['points']} | {status} |")
    lines += ["", "## Each candidate", ""]
    for cand in cands:
        cid = cand.get("id")
        lines += [f"### {cid} {cand.get('name', '')}" + (f" (seed {cand.get('seed_id')})" if cand.get("seed_id") else ""),
                  "", f"What the user sees: {cell(cand.get('what_user_sees'))}", "", f"Job: {cell(cand.get('job'))}", ""]
        for lens in LENSES:
            row = rated(lens, cid)
            lines.append(f"- **{lens}: {row.get('rating', '(none)')}** {json.dumps(row.get('sub', {}))[:300]}. "
                         f"{cell(row.get('reason'))}")
            lines += [f"  - {s}" for s in sources(lens, row)]
        lines.append("")
    lines += ["## Test designs for the top three", "",
              "Numbers fixed before any test. Rung 1 is free or first-party; rung 2 spends money or "
              "contacts people and waits for the owner's go-ahead.", ""]
    for test in tests:
        cid = test.get("candidate")
        lines += [f"### {cid} {by_id.get(cid, {}).get('name', '')}", "",
                  f"Riskiest assumption: {cell(test.get('riskiest_assumption'))} ({cell(test.get('why_riskiest'))})", ""]
        for rung in sorted((r for r in (test.get("rungs") or []) if isinstance(r, dict)), key=lambda r: str(r.get("rung"))):
            owner = " NEEDS THE OWNER'S GO-AHEAD." if rung.get("owner_go_ahead") else (
                " Needs the owner (their data or product)." if rung.get("needs_owner") else "")
            money = f" budget ${rung.get('budget_usd')}." if rung.get("budget_usd") else ""
            lines += [f"- Rung {rung.get('rung')} ({rung.get('kind')}):{owner}{money} {cell(rung.get('method'))}",
                      f"  - metric {cell(rung.get('metric'))}; threshold {rung.get('threshold')}; sample "
                      f"{rung.get('sample')}; {rung.get('duration_days')} days",
                      f"  - pass: {cell(rung.get('pass_rule'))}", f"  - kill: {cell(rung.get('kill_rule'))}",
                      f"  - basis: {', '.join(str(b) for b in rung.get('basis') or [])}"]
        lines.append("")
    if tclaims or tguesses:
        lines += ["Sources used by the test designs:", ""]
        lines += [f"- [tests:{k}] {cell(c.get('claim'))} ({cell(c.get('url'))}, {c.get('date', '?')}, "
                  f"{'checked' if c.get('verified') else c.get('how')})" for k, c in tclaims.items()]
        lines += [f"- [tests:{k}] GUESS: {cell(g.get('guess'))}" for k, g in tguesses.items()]
        lines.append("")
    lines += ["## Check", "", f"Status {result['status']}. Problems:", ""]
    lines += [f"- {p}" for p in result["problems"]] or ["- (none)"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--assets", required=True)
    for flag in ("idea", "problems", "evidence_dir", "seeds", "players", "build_on", "run_id"):
        s.add_argument("--" + flag.replace("_", "-"), dest=flag, default="", metavar="VARIABLE")
    sub.add_parser("rank")
    c = sub.add_parser("check")
    c.add_argument("--answer", action="append", default=[], metavar="PART=VARIABLE")
    c.add_argument("--planted", default="", metavar="VARIABLE")
    c.add_argument("--run-id", dest="run_id", default="", metavar="VARIABLE")
    args = p.parse_args(argv)
    return {"setup": setup, "rank": rank, "check": check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
