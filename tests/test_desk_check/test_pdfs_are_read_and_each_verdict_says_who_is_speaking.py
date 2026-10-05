"""desk_check reads PDF reports and says who is speaking (configs/workflows/desk_check.yaml, product role,
queue #28).

The travel study's desk checks left every PDF report unread: cite.py read PDFs with pdftotext, which the run
containers don't have, so agency and research-house figures went uncited. desk_setup now also writes pdftext.py,
a standard-library PDF reader that cite.py uses first (pdftotext only when it finds no text), so a PDF reads the
same on every machine; a PDF its publisher locks (a password, or copying its text not allowed) stays unread.
Every claim now says who is speaking (party, an interested source's stake, and source) and what it shows
(signal: pays, does, says or fact); each verdict states carried_by, the strongest signal among its usable
decisive claims, which check_desk.py works out and shows for the hand check. The tags never move a verdict. No
model; the PDFs are made here and served from this machine.
"""

import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from temper_ai.agent.script_agent import _rewrite_interpolations, _ValueStash
from tests.test_desk_check.test_a_lost_part_fails_the_desk_check import (
    WORKFLOW,
    by_name,
    final,
    helper,
    jinja,
    run,
    served,
    write,
)

HYPOTHESIS = "Travelers want help choosing where to go."
ASSUMPTION = "Leisure travelers use, or would use, a destination recommendation tool."
BAR = "At least 30 percent of leisure travelers use, or say they would use, a destination recommendation tool."
KILL = "Fewer than 10 percent of leisure travelers use such a tool."
NONE = {"decided_by": [], "set_aside": []}
CARRIED = ("- A1: carried_by should be %s, the strongest signal among its usable decisive claims (pays, then does, "
           "then says, then fact; none without one)")

# Two reports that exist only as PDFs: an agency's survey table and a research house's study. The first breaks
# a word at a line end, as reports set in justified columns do.
REPORT = ["Travel Trends Survey 2024, Table 3", "In 2023, 41 percent of leisure travelers used a destina-",
          "tion recommendation tool before booking a trip."]
REPORT_QUOTE = "41 percent of leisure travelers used a destination recommendation tool before booking"
STUDY = ["Example Research, Trip Matching Study (2024)", "Of 2,000 adults surveyed, 58 percent say they would use a",
         "trip-matching quiz to choose where to go."]
STUDY_QUOTE = "58 percent say they would use a trip-matching quiz"

# Kept pages for the tag checks: (URL, who stands behind it, its text).
PAGES = [
    ("https://agency.example.gov/travel-survey-2024", "Example Travel Agency",
     "In 2023, 41 percent of leisure travelers said they used a destination recommendation tool before booking."),
    ("https://research.example.com/matcher-study", "Example Research",
     "Of 2,000 adults surveyed, 58 percent say they would use a trip-matching quiz."),
    ("https://matcher.example.com/investors/q3-2024", "Matcher Inc.",
     "Paid subscribers grew to 120,000 in the third quarter, and bookings through the matcher doubled."),
]
STAKE = "sells the matcher whose growth it reports"

# The standard security handler's password padding (PDF 32000-1, 7.6.3.3).
PAD = bytes.fromhex("28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a")
FILE_ID = bytes(range(16))


def rc4(key, data):
    s, j = list(range(256)), 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    out, i, j = bytearray(), 0, 0
    for byte in data:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def make_pdf(lines, password=None, permissions=-4):
    """A one-page PDF of text lines in Helvetica, built by hand. With a password (b"" for none) it is locked the
    way the standard security handler locks a file (RC4, a 40-bit key, revision 2); permissions is its P value
    (-4 allows everything; with bit 5, 16, off, copying its text is not allowed)."""
    shown = "".join("({}) Tj T* ".format(line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)"))
                    for line in lines)
    content = zlib.compress(f"BT /F1 11 Tf 14 TL 72 720 Td {shown}ET".encode("latin-1"))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> "
        b"/Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    trailer = b""
    if password is not None:
        owner = hashlib.md5(b"owner").digest() * 2
        key = hashlib.md5((password + PAD)[:32] + owner + permissions.to_bytes(4, "little", signed=True)
                          + FILE_ID).digest()[:5]
        content = rc4(hashlib.md5(key + (5).to_bytes(3, "little") + bytes(2)).digest()[:10], content)
        objects.append(None)    # the stream, object 5
        objects.append(b"<< /Filter /Standard /V 1 /R 2 /O <%s> /U <%s> /P %d >>"
                       % (owner.hex().encode(), rc4(key, PAD).hex().encode(), permissions))
        trailer = b" /Encrypt 6 0 R /ID [<%s> <%s>]" % (FILE_ID.hex().encode(), FILE_ID.hex().encode())
    else:
        objects.append(None)
    objects[4] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content) + content + b"\nendstream"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for num, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % at for at in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R%s >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, trailer, xref)
    return bytes(out)


class Files(http.server.BaseHTTPRequestHandler):
    files = dict()

    def do_GET(self):
        body, kind = self.files.get(self.path, (b"not here", ""))
        self.send_response(200 if kind else 404)
        self.send_header("Content-Type", kind or "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    """This machine serving the files a test puts in site.files: path -> (bytes, content type)."""
    files = dict()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), type("Handler", (Files,), {"files": files}))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield SimpleNamespace(files=files, url=lambda path: f"http://127.0.0.1:{server.server_port}{path}")
    server.shutdown()
    server.server_close()


def setup_desk(ws):
    """desk_setup run for real: the run's input, the one assumption and the three helpers."""
    cfg = by_name("desk_setup")
    stash = _ValueStash()
    assumptions = json.dumps([{"id": "A1", "assumption": ASSUMPTION, "pass_if": BAR, "kill_if": KILL,
                               "fatal": False}])
    script = jinja(stash).from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render(
        workspace_path=str(ws), hypothesis=HYPOTHESIS, assumptions=assumptions)
    done = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=120, cwd=ws,
                          env={**os.environ, **stash.env})
    assert done.returncode == 0, done.stderr
    return script, json.loads(done.stdout)


def cite(ws, *args):
    env = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    done = subprocess.run([sys.executable, "state/desk/cite.py", *args], cwd=ws, capture_output=True, text=True,
                          timeout=120, env=env)
    assert done.returncode == 0, done.stderr
    return done.stdout


def kept(ws, url):
    path = ws / "state" / "desk" / "pages" / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt")
    head, _, text = path.read_text().partition("\n")
    return json.loads(head), text


def claim(n, **tags):
    """Claim A1-<n>, quoted from kept page n: neutral, primary, read with cite.py, a survey (says) unless the tags
    say otherwise; a tag given as None is left out."""
    url, source, text = PAGES[n - 1]
    data = {"id": f"A1-{n}", "claim": text, "quote": " ".join(text.split()[:8]), "url": url, "date": "2024",
            "fetched": "2026-10-05", "kind": "finding", "quality": "primary", "party": "neutral",
            "source": source, "signal": "says", "how": "cite"}
    data.update(tags)
    return {key: value for key, value in data.items() if value is not None}


def check_file(claims, carried_by, decisive=None):
    return {"id": "A1", "assumption": ASSUMPTION, "verdict": "pass",
            "why": "Two neutral surveys put the share of travelers who use such a tool well above the bar.",
            "against_bar": "41 and 58 percent are above the pass bar's 30 percent; nothing near the kill bar.",
            "decisive": decisive or [c["id"] for c in claims], "counter": [], "confidence": "med",
            "carried_by": carried_by, "next_test": "Watch whether visitors finish a matcher on a live page.",
            "rules": NONE, "claims": claims, "searched": ["destination recommendation tool use"]}


def desk(ws, claims, carried_by, row=None):
    """A desk check of one assumption whose claims quote the kept pages; with row, also the reviewer's report."""
    d = ws / "state" / "desk"
    write(d / "check_desk.py", helper())
    write(d / "assumptions" / "A1.json", {"id": "A1", "assumption": ASSUMPTION, "pass_if": BAR, "kill_if": KILL,
                                          "fatal": False})
    for url, _, text in PAGES:
        write(d / "pages" / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt"),
              json.dumps({"url": url, "http": "200"}) + "\n" + text)
    write(d / "checks" / "A1.json", check_file(claims, carried_by))
    write(d / "checks" / "A1.md", "# A1\nWho uses a destination tool, who says so, and what they pay.\n")
    if row is not None:
        write(d / "report.json", {
            "verdicts": [{"id": "A1", "assumption": ASSUMPTION, "researcher_verdict": "pass", "verdict": "pass",
                          "why": "A neutral survey and the company's own figures put use above the bar.",
                          "decisive": [c["id"] for c in claims], "confidence": "med",
                          "next_test": "Watch whether visitors finish a matcher on a live page.", "rules": NONE,
                          **row}],
            "hypothesis_status": "holds", "status_why": "The only assumption passes its bar as written.",
            "next_steps": ["Watch whether visitors finish a matcher on a live page."]})
        write(d / "report.md", "# Desk check\n")
    return ws


def problems(ws):
    done = run(ws, "A1")
    return done.returncode, done.stdout.splitlines()[:-1]


# ---- the setup and the configs --------------------------------------------------------------------


def test_the_setup_writes_the_pdf_reader_and_the_tags_into_the_run(tmp_path):
    script, out = setup_desk(tmp_path)
    assert len(script.encode()) < 120_000, "the script runs as one sh -c argument, and Linux caps one at 128 KB"
    assert out["helpers"] == ["state/desk/cite.py", "state/desk/pdftext.py", "state/desk/check_desk.py"]
    for name in out["helpers"]:
        assert (tmp_path / name).is_file(), f"setup writes {name}"
    text = (tmp_path / "state" / "desk" / "input.md").read_text()
    assert text.index("## Evidence rules") < text.index("## Who is speaking, and what the evidence shows") < \
        text.index("## Assumptions")
    signals = re.findall(r'"(\w+)"', re.search(r"SIGNALS = \(([^)]*)\)", helper()).group(1))
    assert signals == ["pays", "does", "says", "fact"]
    for tag in ["party", "stake (interested claims)", "source"] + signals:
        assert f"- {tag}:" in text or f" {tag}: " in text, f"input.md says what {tag} means"
    assert "they never move a bar or a rule above" in text


def test_the_workflow_and_its_prompts_carry_the_tags():
    assert served(WORKFLOW)["workflow"]["outputs"]["evidence"] == "final.structured.evidence"
    researcher = " ".join(by_name("desk_assumption")["system_prompt"].split())
    for words in ('"carried_by": "pays|does|says|fact|none"', '"signal": "pays|does|says|fact"',
                  '"source": "who stands behind the evidence"', '"stake": "who gains and how', "PDFs too",
                  "The tags never move a bar or a rule"):
        assert words in researcher, f"the researcher is told {words}"
    reviewer = " ".join(by_name("desk_synthesize")["system_prompt"].split())
    assert '"carried_by": "pays|does|says|fact|none"' in reviewer and "The tags never move a bar or a rule" in reviewer


# ---- PDFs -----------------------------------------------------------------------------------------


def test_a_report_published_only_as_a_pdf_is_read_and_cited(tmp_path, site):
    setup_desk(tmp_path)
    site.files["/reports/travel-2024.pdf"] = (make_pdf(REPORT), "application/pdf")
    site.files["/study/trip-matching"] = (make_pdf(STUDY), "application/octet-stream")
    report, study = site.url("/reports/travel-2024.pdf"), site.url("/study/trip-matching")
    shown = cite(tmp_path, "page", report, "percent")
    assert "PDF read by pdftext.py | pages: 1 of 1" in shown
    assert "41 percent of leisure travelers" in shown
    assert "\nFOUND: " in "\n" + cite(tmp_path, "quote", report, REPORT_QUOTE), "a word broken at a line end matches"
    assert "\nFOUND: " in "\n" + cite(tmp_path, "quote", study, STUDY_QUOTE), "a PDF served as octet-stream is read"
    meta, text = kept(tmp_path, study)
    assert meta["pdf"] and meta["pdf_reader"] == "pdftext.py" and meta["pdf_pages"] == "1 of 1"
    assert "Of 2,000 adults surveyed" in text
    claims = [dict(claim(1), url=report, quote=REPORT_QUOTE, source="Example Travel Agency"),
              dict(claim(2), url=study, quote=STUDY_QUOTE, source="Example Research")]
    write(tmp_path / "state" / "desk" / "checks" / "A1.json", check_file(claims, "says"))
    write(tmp_path / "state" / "desk" / "checks" / "A1.md", "# A1\nTwo surveys, both published as PDFs.\n")
    code, found = problems(tmp_path)
    assert code == 0, found


LOCKED = [
    ("copying not allowed", dict(password=b"", permissions=-20), "no-copy",
     "a PDF whose publisher does not allow copying its text: not read"),
    ("a password", dict(password=b"secret"), "password", "a PDF that needs a password: INACCESSIBLE"),
]


@pytest.mark.parametrize(("lock", "locked", "message"), [x[1:] for x in LOCKED], ids=[x[0] for x in LOCKED])
def test_a_pdf_its_publisher_locks_stays_unread(tmp_path, site, lock, locked, message):
    setup_desk(tmp_path)
    site.files["/locked.pdf"] = (make_pdf(REPORT, **lock), "application/pdf")
    url = site.url("/locked.pdf")
    assert "-> " + message in cite(tmp_path, "page", url)
    assert "NOT FOUND" in cite(tmp_path, "quote", url, REPORT_QUOTE)
    meta, text = kept(tmp_path, url)
    assert meta["pdf_locked"] == locked and text == "", "no text kept, and pdftotext is never asked instead"


def test_an_encrypted_pdf_that_allows_copying_is_read(tmp_path, site):
    setup_desk(tmp_path)
    site.files["/open.pdf"] = (make_pdf(REPORT, password=b""), "application/pdf")
    assert "\nFOUND: " in "\n" + cite(tmp_path, "quote", site.url("/open.pdf"), REPORT_QUOTE)
    meta, _ = kept(tmp_path, site.url("/open.pdf"))
    assert meta["pdf_reader"] == "pdftext.py" and "pdf_locked" not in meta


def test_a_copy_of_cite_without_the_reader_beside_it_leaves_pdfs_unread(tmp_path, site):
    """scan_market and scan_serving carry desk_setup's cite.py but not pdftext.py: there a PDF stays unread, as
    before, with a note that says why (and on a machine with no pdftotext either)."""
    desk_dir = tmp_path / "state" / "desk"
    desk_dir.mkdir(parents=True)
    copy = Path(WORKFLOW).parents[1] / "agents" / "scan_serving_assets" / "cite.py"
    (desk_dir / "cite.py").write_bytes(copy.read_bytes())
    tools = tmp_path / "bin"
    tools.mkdir()
    (tools / "curl").symlink_to(shutil.which("curl"))
    site.files["/report.pdf"] = (make_pdf(REPORT), "application/pdf")
    url = site.url("/report.pdf")
    env = {**os.environ, "PATH": str(tools), "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    done = subprocess.run([sys.executable, "state/desk/cite.py", "page", url], cwd=tmp_path, capture_output=True,
                          text=True, timeout=120, env=env)
    assert done.returncode == 0, done.stderr
    assert "-> PDF but no PDF reader here: read it with WebFetch" in done.stdout, done.stdout
    meta, text = kept(tmp_path, url)
    assert meta["pdf_reader"] == "none" and text == ""


# ---- who is speaking, and what it shows ------------------------------------------------------------


MISSING = [
    ("no party", dict(party=None), "party must be neutral or interested"),
    ("an interested party with no stake", dict(party="interested"),
     "party is interested, but no stake (who gains from the answer, and how)"),
    ("no source", dict(source=" "), "no source (who stands behind the evidence, as the page names it)"),
    ("a signal that isn't one", dict(signal="clicks"), "signal must be one of: pays, does, says, fact"),
]


@pytest.mark.parametrize(("tags", "problem"), [x[1:] for x in MISSING], ids=[x[0] for x in MISSING])
def test_every_claim_says_who_is_speaking_and_what_it_shows(tmp_path, tags, problem):
    code, found = problems(desk(tmp_path, [claim(1, **tags), claim(2)], "says"))
    assert code == 1 and "- A1: claim A1-1: " + problem in found, found


def test_one_source_has_one_party(tmp_path):
    claims = [claim(1, source="Example Research"), claim(2, party="interested", stake="sells the study")]
    code, found = problems(desk(tmp_path, claims, "says"))
    assert code == 1 and found == ["- A1: source 'example research' is neutral in A1-1 and interested in A1-2: one "
                                   "source has one party"]


CARRIED_BY = [
    ("words", [("says", "cite"), ("fact", "cite")], "says"),
    ("behaviour over words", [("says", "cite"), ("does", "cite")], "does"),
    ("money over behaviour", [("does", "cite"), ("pays", "cite")], "pays"),
    ("facts alone", [("fact", "cite"), ("fact", "cite")], "fact"),
    ("never a snippet", [("says", "cite"), ("says", "cite"), ("pays", "snippet")], "says"),
]


@pytest.mark.parametrize(("shown", "carried"), [x[1:] for x in CARRIED_BY], ids=[x[0] for x in CARRIED_BY])
def test_a_verdict_states_what_carried_it(tmp_path, shown, carried):
    claims = [claim(n, signal=signal, how=how) for n, (signal, how) in enumerate(shown, 1)]
    code, found = problems(desk(tmp_path, claims, carried))
    assert code == 0, found
    wrong = "none" if carried == "says" else "says"
    code, found = problems(desk(tmp_path, claims, wrong))
    assert code == 1 and found == [CARRIED % carried]


@pytest.mark.parametrize("signal", ["says", "fact", "does", "pays"])
def test_the_tags_never_move_a_verdict(tmp_path, signal):
    """A pass on what people say stands as firmly as one on what they pay: the bar decides, the tags inform."""
    code, found = problems(desk(tmp_path, [claim(1, signal=signal), claim(2, signal=signal)], signal))
    assert code == 0, found


# ---- the reviewer's report and the hand check ------------------------------------------------------


def test_the_hand_check_shows_who_is_speaking_and_what_carried_each_verdict(tmp_path):
    claims = [claim(2), claim(3, party="interested", stake=STAKE, signal="pays")]
    result = final(desk(tmp_path, claims, "pays", row={"carried_by": "pays"}))
    assert result["verdict"] == "pass", result["problems"]
    evidence = {"carried_by": "pays", "signals": {"pays": 1, "does": 0, "says": 1, "fact": 0}, "speaking": "both",
                "sources": [{"source": "Example Research", "party": "neutral"},
                            {"source": "Matcher Inc.", "party": "interested", "stake": STAKE}]}
    assert result["evidence"]["A1"] == result["assumptions"]["A1"]["evidence"] == evidence
    shown = [{k: c[k] for k in ("id", "party", "stake", "source", "signal")} for c in result["spot_check"]]
    assert shown == [{"id": "A1-2", "party": "neutral", "stake": "", "source": "Example Research", "signal": "says"},
                     {"id": "A1-3", "party": "interested", "stake": STAKE, "source": "Matcher Inc.", "signal": "pays"}]


def test_a_report_row_states_what_carried_its_verdict(tmp_path):
    claims = [claim(2), claim(3, party="interested", stake=STAKE, signal="pays")]
    result = final(desk(tmp_path, claims, "pays", row={"carried_by": "says"}))
    assert result["verdict"] == "fail"
    assert result["problems"] == [CARRIED.replace("- A1: ", "report: A1: ") % "pays"]
