#!/usr/bin/env python3
"""Exact page text for citing, and public datasets for counting (desk_check). Plain curl with
its default user agent; PDFs through pdftotext. A page or file that doesn't answer 200 is
INACCESSIBLE: log it and move on, never work around it. Run from the workspace root.

  python3 state/desk/cite.py page <url> [kw1,kw2]   status, dates on the page, text near the keywords
  python3 state/desk/cite.py quote <url> "<words>"  FOUND / NOT FOUND: are these exact words on the page?
  python3 state/desk/cite.py data <url> <name>      download a public dataset whole to state/desk/data/<name>

Every page read is kept in state/desk/pages/ (first line: its URL, HTTP code and fetch time;
then the text) so its words can be checked later. A dataset keeps its own record next to it
(<name>.meta.json: URL, HTTP code, fetch time, size), which the check reads.
"""
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(HERE, "pages")
DATA = os.path.join(HERE, "data")
META_DATE = (r"(?:datePublished|dateModified|published_time|modified_time|updated_time|"
             r"dateCreated)[^0-9<>]{0,40}(\d{4}-\d{2}-\d{2})")
TEXT_DATE = (r"(?i)\b(last updated|last modified|updated|effective(?: date)?|published|posted|"
             r"release date|revised)\s*(?:on|:)?\s*([A-Z][a-z]{2,8}\.? \d{1,2},? \d{4}|"
             r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})")


def norm(s):
    for a, b in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'),
                 ("\u2013", "-"), ("\u2014", "-"), ("\u00a0", " ")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def pdf_text(path):
    try:
        out = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True,
                             timeout=120)
        return norm(out.stdout.decode("utf-8", "replace")), ""
    except (OSError, subprocess.TimeoutExpired):
        return "", ("PDF but no pdftotext here: read it with WebFetch and tag its claims "
                    "how: webfetch, with no quote")


def html_text(raw):
    body = raw.decode("utf-8", "replace")
    dates = set(re.findall(META_DATE, body))
    dates |= set(re.findall(r'<time[^>]*datetime="(\d{4}-\d{2}-\d{2})', body))
    body = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</(script|style|noscript|svg)>",
                  " ", body)
    text = norm(html.unescape(re.sub(r"<[^>]+>", " ", body)))
    return text, sorted(dates)


def curl(url, dest, max_time):
    out = subprocess.run(["curl", "-sS", "-L", "--compressed", "--max-time", str(max_time),
                          "--max-filesize", "400000000", "-o", dest,
                          "-w", "%{http_code}\t%{content_type}\t%{url_effective}", url],
                         capture_output=True, text=True)
    code, ctype, final = (out.stdout.split("\t") + ["", "", ""])[:3]
    meta = {"url": url, "final_url": final or url, "http": code or "000",
            "content_type": ctype, "fetched": time.strftime("%Y-%m-%d %H:%M %Z")}
    if meta["http"] != "200" and out.stderr.strip():
        meta["error"] = out.stderr.strip()[:200]
    return meta


def fetch(url):
    os.makedirs(PAGES, exist_ok=True)
    path = os.path.join(PAGES, hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            head, _, text = f.read().partition("\n")
        return json.loads(head), text
    raw_path = "%s.%d.raw" % (path, os.getpid())
    meta = curl(url, raw_path, 45)
    text = ""
    if meta["http"] == "200" and os.path.exists(raw_path):
        with open(raw_path, "rb") as f:
            raw = f.read()
        if "pdf" in meta["content_type"].lower() or raw[:5] == b"%PDF-":
            text, note = pdf_text(raw_path)
            meta["pdf"] = True
        else:
            text, meta["dates_on_page"] = html_text(raw)
            note = ""
        meta["dated_text"] = ["%s %s" % pair for pair in re.findall(TEXT_DATE, text)[:6]]
        if not note and not text.strip():
            note = ("200 but no readable text (a script-only page?): read it with WebFetch "
                    "and tag its claims how: webfetch, with no quote")
        if note:
            meta["note"] = note
    if os.path.exists(raw_path):
        os.remove(raw_path)
    if meta["http"] == "200" or meta["http"].startswith("4"):
        # Kept, so its words can be checked later and a block is never asked twice. A timeout
        # or a server error is not kept. Researchers run side by side: write whole, then move.
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(meta) + "\n" + text[:3000000])
        os.replace(tmp, path)
    return meta, text


def header(meta):
    print("HTTP", meta["http"], meta.get("final_url"), "|", meta.get("content_type", ""),
          "| fetched", meta.get("fetched"))
    if meta["http"] != "200":
        print("-> INACCESSIBLE (%s): log it, never work around it" % meta.get("error", "status"))
        return False
    if meta.get("dates_on_page") or meta.get("dated_text"):
        print("dates on page:", meta.get("dates_on_page", []), meta.get("dated_text", []))
    if meta.get("note"):
        print("->", meta["note"])
    return True


def page(url, keywords=""):
    meta, text = fetch(url)
    if not header(meta):
        return
    kws = [k.strip() for k in keywords.split(",") if k.strip()]
    if not kws:
        print(text[:5000])
        return
    spots = sorted(m.start() for k in kws for m in re.finditer(re.escape(k), text, re.I))
    hits, shown_to = 0, -1
    for pos in spots:
        if pos < shown_to:
            continue
        print("...", text[max(0, pos - 350):pos + 450], "...")
        shown_to, hits = pos + 450, hits + 1
        if hits >= 12:
            break
    print("keyword hits shown:", hits, "of", len(spots), "| page length", len(text))


def quote(url, words):
    meta, text = fetch(url)
    if not header(meta):
        return
    want = norm(words).lower()
    flat = norm(text)
    at = flat.lower().find(want)
    if at < 0:
        print("NOT FOUND on the page: don't cite these words; quote what the page says")
        return
    print("FOUND: ..." + flat[max(0, at - 200):at + len(want) + 200] + "...")


def data(url, name):
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$", name) or name.endswith(".meta.json"):
        print("name: letters, digits, dots, dashes and underscores (e.g. hospital_owners.csv)")
        return
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, name)
    meta_path = path + ".meta.json"
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("url") != url:
            print("state/desk/data/%s holds another URL (%s): pick another name" % (name, meta.get("url")))
            return
        print("already fetched:", json.dumps(meta))
        return
    part = "%s.%d.part" % (path, os.getpid())
    meta = curl(url, part, 600)
    if meta["http"] == "200" and os.path.exists(part):
        os.replace(part, path)
        digest = hashlib.sha1()
        lines = 0
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
                lines += chunk.count(b"\n")
        meta.update({"file": "state/desk/data/" + name, "bytes": os.path.getsize(path),
                     "lines": lines, "sha1": digest.hexdigest()})
    elif os.path.exists(part):
        os.remove(part)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    if not header(meta):
        return
    print("saved state/desk/data/%s: %d bytes, %d lines" % (name, meta["bytes"], meta["lines"]))
    with open(path, "rb") as f:
        head = f.read(4000).decode("utf-8", "replace").splitlines()
    for line in head[:5]:
        print("  " + line[:400])


def main(argv):
    if len(argv) > 2 and argv[1] == "page":
        page(argv[2], argv[3] if len(argv) > 3 else "")
    elif len(argv) > 3 and argv[1] == "quote":
        quote(argv[2], argv[3])
    elif len(argv) > 3 and argv[1] == "data":
        data(argv[2], argv[3])
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
