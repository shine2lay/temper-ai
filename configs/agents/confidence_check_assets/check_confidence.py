#!/usr/bin/env python3
"""confidence_check's script steps (product role, queue #32). Standard library only; run from the
workspace root. Everything lives in state/confidence/ (method.md says what each file holds).

  check_confidence.py setup --assets DIR [--VALUE VARIABLE ...]   copy the research, write input.md
  check_confidence.py check [--answer PART=VARIABLE ...] [--run-id VARIABLE]
                                                         confidence.json, report.md, check.md
  check_confidence.py quote FILE "EXACT WORDS"             FOUND or NOT FOUND (for the parts)

In setup and check, values arrive as the names of environment variables (the script agent's env
filter), never as text on the command line. The last line printed is the step's JSON (its
structured output).

setup stops at $0 (status not_ready, every problem listed) when the idea or the research folder is
missing, the folder is outside the run workspace or holds no readable text file.

check refuses the run (status fail) when setup did not finish or any part left no usable output
(its file missing, empty, invalid or an account-limit message, or its final answer such a message:
the queue #23 part guard). Otherwise it confirms every quote in the file it cites (a quote not found
is dropped and flagged: status flagged), ranks each line by the file's kind and the line's class,
sets each part's level by method.md's fixed rule, applies the fixed gate and picks the single next
test by the fixed rule. Our own notes never rank above 1, so a claim in them cannot raise a level.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path("state/confidence")
RESEARCH = ROOT / "research"
PARTS_DIR = ROOT / "parts"
ASSET_NAMES = ("check_confidence.py", "method.md")
PARTS = ("value", "viability", "feasibility", "usability", "serving", "breakers")
RISKS = ("value", "viability", "feasibility", "usability", "serving")
GATE = ("value", "viability", "feasibility")
LEVELS = ("unknown", "low", "medium", "high")
CLASSES = ("money", "behaviour", "independent", "words", "vendor", "inference")
DIRECTIONS = ("for", "against", "context")
STATUSES = ("pass", "fail", "open", "owner_settled")  # owner_settled: shown with the owner's words, never counted
ORIGINS = ("kill_if", "research", "test_bar")  # test_bar: a later demand test's pass bar, shown, never counted
INPUT_FILE = "input.md"  # a kill_if deal-breaker may quote the idea's kill list here
TEST_TEXT = 2000  # characters of a test kept (the single next test is printed in full)
BARRIER_TYPES = ("procurement_security", "platform_approval", "licensing", "legal_compliance")
SEVERITIES = ("blocking", "heavy", "light", "none", "unknown")
TEST_KINDS = ("runnable", "needs_owner")
# effort of a test, least first (method.md section 7): runnable and owner_data change nothing, contact no one, spend nothing
EFFORT = {"runnable": 0, "owner_data": 0, "owner_product": 1, "contact": 2, "paid": 3}
TIERS = ("owner_data", "owner_product", "contact", "paid")
RUNG = {"money": 0, "behaviour": 1, "independent": 2, "words": 3}  # what a test's result would be, highest first
SETTLE = {"yes": 1.0, "partly": 0.5}
SOURCE_DIRS = {"pages", "sources", "data"}
OWNER_DIRS = {"owner"}
MAX_FILE = 5_000_000
MIN_QUOTE_WORDS, MAX_QUOTE_WORDS = 3, 120
ELLIPSIS_SPAN = 400  # characters a quote with "..." may span in its file
NOT_PASSED = "__unwired__"  # what the workflow passes for an answer it could not find
QUESTIONS = {
    "value": "Will the target buyer want it enough to switch to it from what they do now?",
    "viability": "Will it pay us: will enough buyers pay enough, at a cost that leaves money over?",
    "feasibility": "Can we build the hard part, with the data and access we can actually get?",
    "usability": "Can the buyer use it in their real work or life, without help we cannot give?",
    "serving": "Can we lawfully and practically serve the first buyer (reviews, approvals, licences, legal duties)?",
    "breakers": "Which original deal-breakers did the research write, and is each passed, failed or open?",
}
RULES = """Levels (fixed rule; money > behaviour > words):
- high: money or behaviour from the target buyer (payments, deposits, sign-ups, usage numbers), shown
  by a saved source or an owner-supplied record, and nothing of that rank against;
- medium: independent public evidence specific to this buyer and job (first-person pain quotes from
  the target buyer counted over 2+ venues, prices this buyer already pays, primary-source figures),
  shown by a saved source, and nothing of a higher rank against (evidence of the same rank against
  makes it contested: the part names the deciding lines; low when the best evidence says the answer
  is no, medium when it says yes; both sides shown); a rival's page is context for value (it
  shows the job is served), against for viability when it serves the same payer cheaper;
- low: words only, vendor or interested-party claims, inference, snippets, our own notes with no saved
  source behind them, or the best evidence says no;
- unknown: no evidence.
Accuracy is never a wedge: "more accurate than rivals" raises nothing.
Ready gate (default; the owner may change it): ready to shape only when value, viability and
feasibility are each at least medium, no original deal-breaker is open or failed, and no serving
barrier is rated blocking. Otherwise not ready, with the single cheapest test that would move it most.
Original deal-breakers: the idea's own kill list and the fatal assumptions the research wrote about
its facts before testing them; a later demand test's pass bar (fake door, deposit, pilot) is a test,
not a deal-breaker. One the owner settled in his own words is shown with his words and not counted.
Next tests: "runnable" = free, we can run it now; "needs owner" = the owner's own data, a change on his
live product, contact with anyone, or real money (cost estimate given). The single next test: least
effort first (runnable or owner's data, then his live product, then contact, then money), then the
highest rung of evidence its result would be (money > behaviour > public evidence > words), then the
most blocking items it moves, then cost; a test that settles an open deal-breaker goes first."""
# What a part says when its account or the service stopped it, instead of research (the same words
# as desk_check's, opportunity_brief's, signal_grade's and feature_screen's checks, queue #23).
NON_ANSWER = re.compile(
    r"session limit|usage limit|weekly limit|daily limit|rate[ _-]?limit|limit (?:reached|exceeded)"
    r"|hit (?:your|the) (?:\w+ )?limit|quota|overloaded|too many requests|credit balance"
    r"|pool exhausted|try again later|resets? (?:at |in |on )?\d|api error|authentication_error"
    r"|oauth token|not logged in|/login|invalid api key|out of (?:extra )?usage|prompt is too long"
    r"|\Aerror: ",
    re.I)
PROVIDER_ERROR = re.compile(r"\[claude_code error\]", re.I)
ELLIPSIS = re.compile(r"\s*(?:\.\.\.|\u2026|\[\.\.\.\])\s*")


# ---- text ----------------------------------------------------------------------------------------

def norm(s):
    for a, b in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'), ("\u2032", "'"),
                 ("\u2013", "-"), ("\u2014", "-"), ("\u2212", "-"), ("\u00a0", " "), ("\u2009", " "),
                 ("\u202f", " "), ("\u200b", "")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def plain(s):
    """norm, lower case, without markdown marks and backslash escapes, for matching a quote."""
    s = norm(s).lower().replace("\\n", " ").replace('\\"', '"').replace("\\", " ")
    return re.sub(r"\s+", " ", re.sub(r"[*`_|#>~]", " ", s)).strip()


def flat(text, limit=160):
    text = norm(str(text or ""))
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


def json_strings(data):
    """Every string inside a JSON value, for matching a quote copied from a JSON file."""
    if isinstance(data, str):
        yield data
    elif isinstance(data, dict):
        for key, value in data.items():
            yield str(key)
            yield from json_strings(value)
    elif isinstance(data, list):
        for value in data:
            yield from json_strings(value)
    elif data is not None:
        yield str(data)


_HAYSTACKS = {}


def haystacks(rel):
    """The normalised texts a quote from research file rel may match (raw text, plus the decoded
    strings of a JSON file and the text of an HTML file)."""
    if rel not in _HAYSTACKS:
        text = (ROOT / rel).read_text(errors="replace")
        texts = [text]
        if rel.lower().endswith(".json"):
            try:
                texts.append("\n".join(json_strings(json.loads(text))))
            except ValueError:
                pass
        if rel.lower().endswith((".html", ".htm")):
            texts.append(re.sub(r"<[^>]+>", " ", text))
        _HAYSTACKS[rel] = [plain(t) for t in texts]
    return _HAYSTACKS[rel]


def quote_found(rel, quote):
    """'' when the quote is in research file rel, else why not."""
    q = plain(quote or "")
    if len(q.split()) < MIN_QUOTE_WORDS:
        return f"quote too short to check ({len(q.split())} words)"
    if len(q.split()) > MAX_QUOTE_WORDS:
        return f"quote too long ({len(q.split())} words; copy one passage)"
    pieces = [p for p in (plain(x) for x in ELLIPSIS.split(norm(quote or ""))) if p]
    for hay in haystacks(rel):
        if q in hay:
            return ""
        if len(pieces) > 1:
            start = hay.find(pieces[0])
            while start >= 0:
                pos, ok = start + len(pieces[0]), True
                for piece in pieces[1:]:
                    nxt = hay.find(piece, pos)
                    if nxt < 0 or nxt + len(piece) - start > ELLIPSIS_SPAN:
                        ok = False
                        break
                    pos = nxt + len(piece)
                if ok:
                    return ""
                start = hay.find(pieces[0], start + 1)
    return "quote not found in the file"


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


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def rel_file(name):
    """A cited file as manifest.json names it (research/...), whatever prefix the part wrote."""
    name = str(name or "").strip().replace("\\", "/")
    for prefix in ("./", str(ROOT) + "/", "confidence/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


def kind_of(rel_parts):
    dirs = {p.lower() for p in rel_parts[:-1]}
    if dirs & OWNER_DIRS:
        return "owner"
    if dirs & SOURCE_DIRS:
        return "source"
    return "notes"


# ---- setup ---------------------------------------------------------------------------------------

def setup(args):
    def value(flag):
        return (env_value(getattr(args, flag)) or "").strip()

    problems = []
    idea, research_dir, breakers = value("idea"), value("research_dir"), value("deal_breakers")
    if not idea:
        problems.append("no idea given: name the target buyer, the job it does and how it would earn")
    here = Path.cwd().resolve()
    src = None
    if not research_dir:
        problems.append("no research_dir given: the folder in the run workspace with the idea's saved research")
    else:
        src = Path(research_dir)
        src = (src if src.is_absolute() else here / src).resolve()
        try:
            src.relative_to(here)
        except ValueError:
            problems.append(f"research_dir {research_dir} is outside the run workspace")
            src = None
        if src is not None and not src.is_dir():
            problems.append(f"research_dir {research_dir} is not a folder in the run workspace")
            src = None
    files, skipped = [], []
    if src is not None:
        for path in sorted(src.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(src)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if path.stat().st_size > MAX_FILE:
                skipped.append({"file": rel.as_posix(), "why": "over 5 MB"})
                continue
            data = path.read_bytes()
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                skipped.append({"file": rel.as_posix(), "why": "not UTF-8 text"})
                continue
            if not data.strip():
                skipped.append({"file": rel.as_posix(), "why": "empty"})
                continue
            files.append((path, rel, data))
        if not files:
            problems.append(f"research_dir {research_dir} holds no readable text file")
    if problems:
        (ROOT / "setup.json").write_text(json.dumps({"status": "not_ready", "problems": problems}, indent=1))
        print(json.dumps({"status": "not_ready", "files": 0, "kinds": {}, "problems": problems}))
        return 0
    manifest = []
    for _path, rel, data in files:
        dest = RESEARCH / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        manifest.append({"file": f"research/{rel.as_posix()}", "kind": kind_of(rel.parts), "bytes": len(data),
                         "sha256": hashlib.sha256(data).hexdigest()})
    kinds = {k: sum(1 for f in manifest if f["kind"] == k) for k in ("source", "owner", "notes")}
    (ROOT / "manifest.json").write_text(json.dumps({"files": manifest, "skipped": skipped}, indent=1))
    PARTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Confidence check input", "", "## The idea", "", idea, "",
             "## Original deal-breakers given", "",
             breakers or "(none given: the breakers part finds them in the research)", "",
             "## Research files (state/confidence/research/; kinds in manifest.json)", "",
             f"{kinds['notes']} notes files (our own reports and checks), {kinds['source']} saved sources, "
             f"{kinds['owner']} owner-supplied records.", "", "### Owner-supplied records (owner/)", ""]
    lines += [f"- {f['file']} ({f['bytes']} bytes)" for f in manifest if f["kind"] == "owner"] or ["(none)"]
    lines += ["", "### The owner's own words (read each before you set any deal-breaker's status)", ""]
    lines += [f"- {f['file']} ({f['bytes']} bytes)" for f in manifest
              if f["kind"] == "notes" and "owner" in f["file"].rsplit("/", 1)[-1].lower()] or ["(none)"]
    lines += ["", "### Notes (our own reports, checks and runs)", ""]
    lines += [f"- {f['file']} ({f['bytes']} bytes)" for f in manifest if f["kind"] == "notes"] or ["(none)"]
    lines += ["", "### Saved sources, by folder", ""]
    folders = {}
    for f in manifest:
        if f["kind"] == "source":
            folders.setdefault(f["file"].rsplit("/", 1)[0], []).append(f)
    lines += [f"- {folder}/: {len(fs)} files" for folder, fs in sorted(folders.items())] or ["(none)"]
    if skipped:
        lines += ["", "### Not copied", ""] + [f"- {s['file']}: {s['why']}" for s in skipped]
    (ROOT / "input.md").write_text("\n".join(lines) + "\n")
    sha = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ASSET_NAMES}
    (ROOT / "setup.json").write_text(json.dumps({
        "status": "ready", "run_id": value("run_id"), "assets_dir": str(args.assets), "sha256": sha,
        "idea": idea, "deal_breakers": breakers, "kinds": kinds, "skipped": len(skipped)}, indent=1))
    print(json.dumps({"status": "ready", "files": len(manifest), "kinds": kinds, "problems": []}))
    return 0


# ---- check ---------------------------------------------------------------------------------------

def rank(line, kinds):
    kind = kinds.get(line["file"], "notes")
    primary = kind in ("source", "owner")
    if line["class"] in ("money", "behaviour") and line["target_buyer"] and primary:
        return 3
    if line["class"] in ("independent", "money", "behaviour") and line["specific"] and primary:
        return 2
    return 1


def rule_level(lines):
    """method.md section 4: the level the verified for and against lines give."""
    best_for = max((ln["rank"] for ln in lines if ln["direction"] == "for"), default=0)
    best_against = max((ln["rank"] for ln in lines if ln["direction"] == "against"), default=0)
    if not best_for and not best_against:
        return "unknown"
    if best_against > best_for or best_for == 1:
        return "low"
    return "high" if best_for == 3 and best_against < 3 else "medium"


def contested(lines):
    """Split evidence: an against line ranks as high as the best for line (rank 2 or more)."""
    best_for = max((ln["rank"] for ln in lines if ln["direction"] == "for"), default=0)
    best_against = max((ln["rank"] for ln in lines if ln["direction"] == "against"), default=0)
    return best_for >= 2 and best_against == best_for


def net_level(lines, net):
    """Split evidence (method.md section 4): the part says which way the best evidence answers the
    risk's question and names the deciding line(s) at the top rank on that side. No -> low (the
    best evidence says the answer is no); yes -> medium. Missing or invalid -> low, with the reason.
    The top rank is the tie between the best for and best against lines; context lines never set it."""
    top = max((ln["rank"] for ln in lines if ln["direction"] in ("for", "against")), default=0)
    side = {"yes": "for", "no": "against"}
    if not isinstance(net, dict) or net.get("answer") not in side:
        return "low", 'no "net" with answer yes or no'
    ids = {ln["id"] for ln in lines if ln["rank"] == top and ln["direction"] == side[net["answer"]]}
    decisive = net.get("decisive") if isinstance(net.get("decisive"), list) else []
    if not any(d in ids for d in decisive):
        return "low", f'net "decisive" names no verified rank-{top} {side[net["answer"]]} line'
    return ("medium" if net["answer"] == "yes" else "low"), ""


def count_pain(lines):
    """method.md section 4: first-person pain quotes (class words with a venue, target_buyer and
    specific, from source files) rank 2 together when, in one direction, they come from two or more
    venues and two or more files. Never rank 3."""
    for direction in ("for", "against"):
        pain = [ln for ln in lines if ln["direction"] == direction and ln["class"] == "words"
                and ln["target_buyer"] and ln["specific"] and ln.get("kind") == "source"
                and isinstance(ln.get("venue"), str) and ln["venue"].strip()]
        venues = {" ".join(ln["venue"].lower().split()) for ln in pain}
        files = {ln["file"] for ln in pain}
        if len(venues) >= 2 and len(files) >= 2:
            for ln in pain:
                ln["rank"] = max(ln["rank"], 2)
                ln["counted"] = f"{len(pain)} pain quotes from {len(venues)} venues"


def check_line(part, line, problems):
    """The line with its fields valid (file as manifest.json names it), or None with the reason
    added to problems. The quote is checked by the caller."""
    where = f"{part} {line.get('id', '?') if isinstance(line, dict) else '?'}"
    if not isinstance(line, dict):
        problems.append(f"{where}: an evidence line is not an object")
        return None
    bad = []
    if not isinstance(line.get("id"), str) or not line["id"].strip():
        bad.append("no id")
    if line.get("class") not in CLASSES:
        bad.append(f"class {line.get('class')!r} not one of {', '.join(CLASSES)}")
    if line.get("direction") not in DIRECTIONS:
        bad.append(f"direction {line.get('direction')!r} not one of {', '.join(DIRECTIONS)}")
    for flag in ("target_buyer", "specific"):
        if not isinstance(line.get(flag), bool):
            bad.append(f"{flag} not true or false")
    if bad:
        problems.append(f"{where}: " + "; ".join(bad))
        return None
    return {**line, "file": rel_file(line.get("file"))}


def check(args):
    problems, flags, misses = [], [], []
    setup_info, why = load_json(ROOT / "setup.json")
    manifest, why_m = load_json(ROOT / "manifest.json")
    if why or why_m or setup_info.get("status") != "ready":
        stop = (setup_info or {}).get("problems") or [why or why_m or "setup did not finish"]
        result = {"status": "fail", "verdict": "", "levels": {}, "next_test": None, "deal_breakers": {},
                  "report_path": "", "quote_misses": 0, "flags": 0,
                  "problems": ["setup did not finish: " + "; ".join(stop)]}
        print(json.dumps(result))
        return 0
    kinds = {f["file"]: f["kind"] for f in manifest.get("files", [])}
    answers = dict(a.split("=", 1) for a in (args.answer or []) if "=" in a)
    parts, guard = {}, {}
    for part in PARTS:
        data, why = load_json(PARTS_DIR / f"{part}.json")
        answer = env_value(answers.get(part))
        if not why and answer is not None and answer != NOT_PASSED:
            reason = non_answer(answer)
            if reason:
                why = f"{part}'s final answer is {reason}"
        if not why and data.get("part") != part:
            why = f"parts/{part}.json names part {data.get('part')!r}"
        if not why and not isinstance(data.get("evidence"), list):
            why = f"parts/{part}.json has no evidence list"
        guard[part] = why or "usable"
        if why:
            problems.append(f"part {part} left no usable output: {why}")
        else:
            parts[part] = data
    if len(parts) < len(PARTS):
        result = {"status": "fail", "verdict": "", "levels": {}, "next_test": None, "deal_breakers": {},
                  "report_path": "", "quote_misses": 0, "flags": 0, "problems": problems}
        write_check_md(guard, {}, problems, [], [])
        print(json.dumps(result))
        return 0

    schema = []
    evidence = {}  # part -> list of verified lines
    for part, data in parts.items():
        seen, lines = set(), []
        for raw in data.get("evidence", []):
            line = check_line(part, raw, schema)
            if line is None:
                continue
            if line["id"] in seen:
                schema.append(f"{part} {line['id']}: id used twice (second dropped)")
                continue
            seen.add(line["id"])
            miss = (quote_found(line["file"], line.get("quote")) if line["file"] in kinds
                    else "not a research file in manifest.json")
            if miss:
                misses.append({"part": part, "id": line["id"], "file": line["file"], "quote": flat(line.get("quote"), 200),
                               "why": miss})
                continue
            line["kind"] = kinds[line["file"]]
            line["rank"] = rank(line, kinds)
            if line["class"] in ("money", "behaviour") and line["kind"] == "notes":
                flags.append({"type": "money or behaviour claim without its record", "part": part, "id": line["id"],
                              "file": line["file"], "quote": flat(line.get("quote"), 200),
                              "effect": "ranks 1: our notes are not a record of what buyers did"})
            lines.append(line)
        count_pain(lines)
        evidence[part] = lines
        for item in data.get("unsupported", []) or []:
            if not isinstance(item, dict):
                schema.append(f"{part}: an unsupported item is not an object")
                continue
            item = {**item, "file": rel_file(item.get("file"))}
            entry = {"type": "unsupported claim", "part": part, "file": item["file"],
                     "quote": flat(item.get("quote"), 200), "why": flat(item.get("why"), 200)}
            if item["file"] in kinds:
                miss = quote_found(item["file"], item.get("quote"))
                if miss:
                    misses.append({"part": part, "id": "unsupported", "file": item["file"],
                                   "quote": flat(item.get("quote"), 200), "why": miss})
                    continue
            else:
                misses.append({"part": part, "id": "unsupported", "file": str(item.get("file")),
                               "quote": flat(item.get("quote"), 200), "why": "not a research file in manifest.json"})
                continue
            flags.append(entry)

    # levels
    levels, said = {}, {}
    for part in RISKS:
        levels[part] = rule_level(evidence[part])
        if contested(evidence[part]):
            levels[part], why_net = net_level(evidence[part], parts[part].get("net"))
            if why_net:
                schema.append(f"{part}: evidence is split; {why_net} (taken as low)")
        said[part] = parts[part].get("level")
        if said[part] not in LEVELS:
            schema.append(f"{part}: level {said[part]!r} not one of {', '.join(LEVELS)}")
        elif said[part] != levels[part]:
            flags.append({"type": "level differs from the rule", "part": part,
                          "why": f"the part said {said[part]}, the rule gives {levels[part]} from its verified lines"})

    # deal-breakers
    verified_ids = {part: {ln["id"] for ln in evidence[part]} for part in PARTS}
    breakers = []
    for raw in parts["breakers"].get("breakers", []) or []:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            schema.append("breakers: a deal-breaker is not an object with an id")
            continue
        b = {"id": raw["id"], "text": flat(raw.get("text"), 300), "risk": raw.get("risk", ""),
             "origin": raw.get("origin"),
             "status": raw.get("status"), "evidence": [e for e in raw.get("evidence", []) or [] if isinstance(e, str)],
             "reason": flat(raw.get("reason"), 300), "written": raw.get("written") or {},
             "settled": raw.get("settled") if isinstance(raw.get("settled"), dict) else {}}
        if b["origin"] not in ORIGINS:
            schema.append(f"breakers {b['id']}: origin {b['origin']!r} not one of {', '.join(ORIGINS)} (taken as research)")
            b["origin"] = "research"
        if b["status"] not in STATUSES:
            schema.append(f"breakers {b['id']}: status {b['status']!r} not one of {', '.join(STATUSES)} (taken as open)")
            b["status"] = "open"
        written = b["written"] if isinstance(b["written"], dict) else {}
        written = {**written, "file": rel_file(written.get("file"))}
        if written["file"] in kinds or (written["file"] == INPUT_FILE and b["origin"] == "kill_if"):
            miss = quote_found(written["file"], written.get("quote"))
            if miss:
                misses.append({"part": "breakers", "id": f"{b['id']} written", "file": written["file"],
                               "quote": flat(written.get("quote"), 200), "why": miss})
        else:
            misses.append({"part": "breakers", "id": f"{b['id']} written", "file": str(written.get("file")),
                           "quote": flat(written.get("quote"), 200), "why": "not a research file in manifest.json"})
        if b["status"] == "owner_settled":
            settled = {**b["settled"], "file": rel_file(b["settled"].get("file"))}
            miss = (quote_found(settled["file"], settled.get("quote")) if settled["file"] in kinds
                    else "no settled quote in a research file")
            if miss:
                misses.append({"part": "breakers", "id": f"{b['id']} settled", "file": str(settled.get("file")),
                               "quote": flat(settled.get("quote"), 200), "why": miss})
                flags.append({"type": "owner settlement without the owner's words", "part": "breakers", "id": b["id"],
                              "why": "owner_settled needs the owner's own words found in their file, so it counts as open"})
                b["status"] = "open"
            else:
                b["settled"] = {"file": settled["file"], "quote": flat(settled.get("quote"), 300)}
        if b["status"] in ("pass", "fail") and not any(e in verified_ids["breakers"] for e in b["evidence"]):
            flags.append({"type": "deal-breaker status without verified evidence", "part": "breakers", "id": b["id"],
                          "why": f"{b['status']} cites no verified evidence line, so it counts as open"})
            b["status"] = "open"
        breakers.append(b)
    test_bars = [b for b in breakers if b["origin"] == "test_bar"]
    breakers = [b for b in breakers if b["origin"] != "test_bar"]
    if not breakers:
        flags.append({"type": "no original deal-breakers found", "part": "breakers",
                      "why": "the research wrote no deal-breakers before its tests (or the part found none)"})

    # serving barriers
    barriers = []
    for raw in parts["serving"].get("barriers", []) or []:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            schema.append("serving: a barrier is not an object with an id")
            continue
        bar = {"id": raw["id"], "barrier": flat(raw.get("barrier"), 200), "type": raw.get("type"),
               "severity": raw.get("severity"), "evidence": [e for e in raw.get("evidence", []) or [] if isinstance(e, str)],
               "reason": flat(raw.get("reason"), 300)}
        if bar["type"] not in BARRIER_TYPES:
            schema.append(f"serving {bar['id']}: type {bar['type']!r} not one of {', '.join(BARRIER_TYPES)}")
        if bar["severity"] not in SEVERITIES:
            schema.append(f"serving {bar['id']}: severity {bar['severity']!r} not one of {', '.join(SEVERITIES)} (taken as unknown)")
            bar["severity"] = "unknown"
        if bar["severity"] == "blocking" and not any(e in verified_ids["serving"] for e in bar["evidence"]):
            flags.append({"type": "blocking barrier without verified evidence", "part": "serving", "id": bar["id"],
                          "why": "blocking cites no verified evidence line, so it counts as unknown"})
            bar["severity"] = "unknown"
        barriers.append(bar)

    # tests
    tests = []
    for part in PARTS:
        for raw in parts[part].get("tests", []) or []:
            if not isinstance(raw, dict):
                schema.append(f"{part}: a test is not an object")
                continue
            t = {"part": part, "id": raw.get("id", "?"), "test": flat(raw.get("test"), TEST_TEXT), "kind": raw.get("kind"),
                 "needs": flat(raw.get("needs"), 120), "cost_usd": raw.get("cost_usd"),
                 "cost_note": flat(raw.get("cost_note"), 200), "targets": [],
                 "tier": raw.get("tier"), "yields": raw.get("yields"), "repeats": raw.get("repeats")}
            if t["kind"] not in TEST_KINDS:
                schema.append(f"{part} {t['id']}: kind {t['kind']!r} not runnable or needs_owner (taken as needs_owner)")
                t["kind"] = "needs_owner"
            if t["kind"] == "runnable":
                t["tier"] = None
            elif t["tier"] not in TIERS:
                schema.append(f"{part} {t['id']}: tier {t['tier']!r} not one of {', '.join(TIERS)} (taken as paid)")
                t["tier"] = "paid"
            if t["yields"] not in RUNG:
                schema.append(f"{part} {t['id']}: yields {t['yields']!r} not one of {', '.join(RUNG)} (taken as words)")
                t["yields"] = "words"
            if not is_number(t["cost_usd"]) or t["cost_usd"] < 0:
                schema.append(f"{part} {t['id']}: cost_usd is not a number (taken as unknown, sorted last)")
                t["cost_usd"] = None
            for target in raw.get("targets", []) or []:
                if isinstance(target, dict) and isinstance(target.get("item"), str) and target.get("settle") in SETTLE:
                    item = target["item"].strip()
                    item = item.lower() if item.lower() in PARTS else item.upper()
                    t["targets"].append({"item": item, "settle": target["settle"]})
                else:
                    schema.append(f"{part} {t['id']}: a target needs item and settle yes or partly")
            if t["repeats"] is not None and t["repeats"] not in RUNG:
                schema.append(f"{part} {t['id']}: repeats {t['repeats']!r} not null or one of {', '.join(RUNG)} "
                              "(taken as a repeat of the same rung)")
                t["repeats"] = t["yields"]
            # method.md section 5: a repeat of a test that came back unknown settles nothing unless it climbs the ladder
            if t["repeats"] is not None and RUNG[t["yields"]] >= RUNG[t["repeats"]]:
                for g in t["targets"]:
                    if g["settle"] == "yes":
                        g["settle"] = "partly"
                        g["why"] = "repeats an earlier test at the same rung"
            tests.append(t)

    # gate and the single next test
    open_ids = [b["id"] for b in breakers if b["status"] == "open"]
    failed_ids = [b["id"] for b in breakers if b["status"] == "fail"]
    blocking_barriers = [bar["id"] for bar in barriers if bar["severity"] == "blocking"]
    low_gate = [p for p in GATE if LEVELS.index(levels[p]) < LEVELS.index("medium")]
    reasons = [f"{p} is {levels[p]}" for p in low_gate]
    reasons += [f"deal-breaker {i} is open" for i in open_ids] + [f"deal-breaker {i} failed" for i in failed_ids]
    reasons += [f"serving barrier {i} is blocking" for i in blocking_barriers]
    verdict = "not_ready" if reasons else "ready"
    next_test, pick_rule = None, ""
    if verdict == "not_ready" and failed_ids:
        pick_rule = "a deal-breaker failed its own bar: kill or change the idea; no test needed"
    elif verdict == "not_ready":
        weights = {i: 2.0 for i in open_ids}
        weights.update({p: 1.0 for p in low_gate})
        if blocking_barriers:
            weights["serving"] = 2.0

        def score(t):
            return sum(weights[g["item"]] * SETTLE[g["settle"]] for g in t["targets"] if g["item"] in weights)

        def effort(t):
            return EFFORT["runnable"] if t["kind"] == "runnable" else EFFORT[t["tier"]]

        def cost(t):
            return t["cost_usd"] if t["cost_usd"] is not None else float("inf")

        candidates = [t for t in tests if score(t) > 0]
        # only a test whose result would be independent evidence or better can settle a deal-breaker
        settling = [t for t in candidates if RUNG[t["yields"]] <= RUNG["independent"]
                    and any(g["item"] in open_ids and g["settle"] == "yes" for g in t["targets"])]
        if settling:
            next_test = min(settling, key=lambda t: (effort(t), RUNG[t["yields"]], cost(t), -score(t)))
            pick_rule = ("rule 1: a test settles an open deal-breaker; among those, least effort, then the "
                         "highest rung of evidence, then cost")
        else:
            if candidates:
                next_test = min(candidates, key=lambda t: (effort(t), RUNG[t["yields"]], -score(t),
                                                           0 if t["kind"] == "runnable" else 1, cost(t)))
                pick_rule = ("rule 2: no test settles an open deal-breaker; least effort, then the highest rung "
                             "of evidence, then the most blocking items moved, then cost")
            else:
                pick_rule = "no test targets the blocking items"
                flags.append({"type": "no next test", "part": "", "why": "no part's test targets a blocking item"})

    run_id = (env_value(args.run_id) or "").strip() if args.run_id else ""
    status = "flagged" if misses or schema else "pass"
    result = {
        "status": status, "run_id": run_id, "verdict": verdict, "reasons": reasons, "levels": levels,
        "levels_said": said, "contested": [p for p in RISKS if contested(evidence[p])],
        "next_test": next_test, "pick_rule": pick_rule,
        "deal_breakers": {"open": open_ids, "failed": failed_ids, "all": breakers, "test_bars": test_bars},
        "barriers": barriers,
        "tests": tests, "evidence": {p: evidence[p] for p in PARTS}, "flags": flags, "quote_misses": misses,
        "schema_problems": schema, "guard": guard, "idea": setup_info.get("idea", ""),
        "rules": RULES,
    }
    (ROOT / "confidence.json").write_text(json.dumps(result, indent=1))
    write_report(result, parts)
    write_check_md(guard, evidence, schema, misses, flags)
    print(json.dumps({
        "status": status, "verdict": verdict, "levels": levels,
        "next_test": ({k: next_test[k] for k in ("part", "id", "test", "kind", "tier", "yields", "needs", "cost_usd")}
                      if next_test else None),
        "deal_breakers": {"open": open_ids, "failed": failed_ids},
        "report_path": str(ROOT / "report.md"), "quote_misses": len(misses), "flags": len(flags),
        "problems": schema + [f"quote not found: {m['part']} {m['id']} in {m['file']}" for m in misses]}))
    return 0


def cell(text):
    return flat(text, 400).replace("|", "/")


def test_line(t):
    cost = f"${t['cost_usd']:g}" if t["cost_usd"] is not None else "cost unknown"
    kind = "runnable" if t["kind"] == "runnable" else f"needs owner, {t.get('tier')} ({t['needs']})"
    note = f"; {t['cost_note']}" if t["cost_note"] else ""
    targets = ", ".join(f"{g['item']} ({g['settle']}{'; a repeat at the same rung' if g.get('why') else ''})"
                        for g in t["targets"]) or "no target"
    return f"{t['test']} [{kind}; {cost}{note}; yields {t.get('yields')}; settles: {targets}]"


def write_report(r, parts):
    idea_head = flat((r["idea"] or "").splitlines()[0] if r["idea"] else "", 120)
    lines = [f"# Confidence check: {idea_head}", ""]
    lines.append(f"Run {r['run_id'] or '(no run id)'}. Check status: {r['status']}.")
    lines.append("")
    if r["verdict"] == "ready":
        lines.append("**Verdict: READY to shape** (every gate condition holds).")
    else:
        lines.append("**Verdict: NOT READY to shape**: " + "; ".join(r["reasons"]) + ".")
    lines.append("")
    if r["next_test"]:
        lines.append(f"**Single next test** ({r['pick_rule']}): {r['next_test']['part']} {r['next_test']['id']}: "
                     + test_line(r["next_test"]))
    elif r["pick_rule"]:
        lines.append(f"**Single next test:** none ({r['pick_rule']}).")
    lines += ["", "## Rules (fixed; printed in every output)", "", "```", r["rules"], "```", "",
              "## Risks", "", "| Risk | Level (rule) | Part said | Best for | Best against | Reason (the part's) |",
              "|---|---|---|---|---|---|"]
    for part in RISKS:
        lines_ = r["evidence"][part]
        bf = max(((ln["rank"], ln["id"]) for ln in lines_ if ln["direction"] == "for"), default=None)
        ba = max(((ln["rank"], ln["id"]) for ln in lines_ if ln["direction"] == "against"), default=None)
        split = " (contested)" if part in r.get("contested", []) else ""
        lines.append(f"| {part} | **{r['levels'][part]}**{split} | {r['levels_said'].get(part)} | "
                     f"{f'rank {bf[0]} ({bf[1]})' if bf else '-'} | {f'rank {ba[0]} ({ba[1]})' if ba else '-'} | "
                     f"{cell(parts[part].get('reason'))} |")
    lines += ["", "## Original deal-breakers", "", "| Id | As written | Origin | Risk | Status | Evidence | Reason |",
              "|---|---|---|---|---|---|---|"]
    for b in r["deal_breakers"]["all"]:
        lines.append(f"| {b['id']} | {cell(b['text'])} | {b['origin']} | {b['risk']} | **{b['status']}** | "
                     f"{', '.join(b['evidence']) or '-'} | {cell(b['reason'])} |")
    if not r["deal_breakers"]["all"]:
        lines.append("| - | none found | - | - | - | - | - |")
    if r["deal_breakers"].get("test_bars"):
        lines += ["", "Later test bars the part listed (shown, never counted: a test's pass bar is not a deal-breaker): "
                  + "; ".join(f"{b['id']} {cell(b['text'])}" for b in r["deal_breakers"]["test_bars"]) + "."]
    settled = [b for b in r["deal_breakers"]["all"] if b["status"] == "owner_settled"]
    if settled:
        lines += ["", "Settled by the owner (shown, not counted; the owner may reopen them): "
                  + "; ".join(f"{b['id']}: \"{cell(b['settled'].get('quote'))}\" ({b['settled'].get('file')})"
                              for b in settled) + "."]
    lines += ["", "## Serving barriers", "", "| Id | Barrier | Type | Severity | Evidence | Reason |", "|---|---|---|---|---|---|"]
    for bar in r["barriers"]:
        lines.append(f"| {bar['id']} | {cell(bar['barrier'])} | {bar['type']} | **{bar['severity']}** | "
                     f"{', '.join(bar['evidence']) or '-'} | {cell(bar['reason'])} |")
    if not r["barriers"]:
        lines.append("| - | none listed | - | - | - | - |")
    lines += ["", "## Next tests by part (cheapest first)", ""]
    for part in PARTS:
        ts = sorted((t for t in r["tests"] if t["part"] == part),
                    key=lambda t: (EFFORT["runnable"] if t["kind"] == "runnable" else EFFORT[t["tier"]],
                                   t["cost_usd"] if t["cost_usd"] is not None else float("inf")))
        lines.append(f"- **{part}**: " + ("; ".join(f"{t['id']} " + test_line(t) for t in ts) if ts else "none listed"))
    lines += ["", "## Flags", ""]
    if r["flags"]:
        for f in r["flags"]:
            bits = [f"**{f['type']}**", f.get("part", "")]
            if f.get("id"):
                bits.append(f["id"])
            if f.get("file"):
                bits.append(f"{f['file']}: \"{f.get('quote', '')}\"")
            if f.get("why"):
                bits.append(f["why"])
            if f.get("effect"):
                bits.append(f["effect"])
            lines.append("- " + " / ".join(b for b in bits if b))
    else:
        lines.append("- none")
    if r["quote_misses"]:
        lines += ["", "## Quotes not found (dropped)", ""]
        lines += [f"- {m['part']} {m['id']}: {m['file']}: \"{m['quote']}\" ({m['why']})" for m in r["quote_misses"]]
    lines += ["", "## Evidence (verified lines; rank 3 money or behaviour from the buyer, 2 independent and specific "
              "or pain quotes counted over 2+ venues, 1 the rest)",
              "", "| Part | Id | Rank | Class | Direction | File (kind) | Quote | Says |", "|---|---|---|---|---|---|---|---|"]
    for part in PARTS:
        for ln in r["evidence"][part]:
            counted = f" ({ln['counted']}; venue {cell(ln.get('venue'))})" if ln.get("counted") else ""
            lines.append(f"| {part} | {ln['id']} | {ln['rank']}{counted} | {ln['class']} | {ln['direction']} | "
                         f"{ln['file']} ({ln['kind']}) | {cell(ln.get('quote'))} | {cell(ln.get('says'))} |")
    (ROOT / "report.md").write_text("\n".join(lines) + "\n")


def write_check_md(guard, evidence, schema, misses, flags):
    lines = ["# Confidence check: mechanical check", "", "## Part guard (queue #23)", ""]
    lines += [f"- {part}: {why}" for part, why in guard.items()]
    lines += ["", "## Quotes", ""]
    total = sum(len(v) for v in evidence.values())
    lines.append(f"- verified evidence lines: {total}; quotes not found: {len(misses)}")
    lines += [f"  - {m['part']} {m['id']}: {m['file']} ({m['why']})" for m in misses]
    lines += ["", "## Schema problems", ""] + ([f"- {s}" for s in schema] or ["- none"])
    lines += ["", f"## Flags: {len(flags)} (listed in report.md)"]
    (ROOT / "check.md").write_text("\n".join(lines) + "\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--assets", required=True)
    for flag in ("idea", "research-dir", "deal-breakers", "run-id"):
        s.add_argument(f"--{flag}")
    c = sub.add_parser("check")
    c.add_argument("--answer", action="append")
    c.add_argument("--run-id")
    q = sub.add_parser("quote")
    q.add_argument("file")
    q.add_argument("words")
    args = p.parse_args(argv)
    if args.cmd == "setup":
        return setup(args)
    if args.cmd == "quote":
        return quote_cmd(args)
    return check(args)


def quote_cmd(args):
    """What a part runs to confirm a quote before it records it (the check runs the same test)."""
    manifest, why = load_json(ROOT / "manifest.json")
    kinds = {f["file"]: f["kind"] for f in (manifest or {}).get("files", [])}
    rel = rel_file(args.file)
    if rel == INPUT_FILE and (ROOT / INPUT_FILE).is_file():
        miss = quote_found(rel, args.words)
        print(f"NOT FOUND: {miss}" if miss else f"FOUND in {rel} (the idea's kill list; for a kill_if deal-breaker's written quote only)")
        return 0
    if why or rel not in kinds:
        print(f"NOT FOUND: {rel} is not a research file in manifest.json (cite it as research/...)")
        return 0
    miss = quote_found(rel, args.words)
    print(f"NOT FOUND: {miss}" if miss else f"FOUND in {rel} (kind {kinds[rel]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
