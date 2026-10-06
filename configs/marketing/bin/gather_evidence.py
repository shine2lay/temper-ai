#!/usr/bin/env python3
"""Gather a product's evidence folder for the positioning workflow (Product marketing).

Copies each source a sources file names into one folder of plain text files. Every file opens with
where it came from and when, so each line a positioning document quotes can be traced back to its
origin. Runs on the host before the workflow: the workflow's agents read only this folder and never
browse. Standard library only.

    gather_evidence.py SOURCES.json --out DIR [--manifest FILE]

SOURCES.json names the product and its sources, in the order they are written:

    {"product": "Example", "sources": [
      {"kind": "file", "path": "~/repo/README.md", "as": "readme.md"},
      {"kind": "file", "path": "~/repo/docs/guide.md", "as": "docs/guide.md",
       "sections": ["## 2.", "## 7."], "exclude": "(?i)password"},
      {"kind": "file", "path": "~/repo/docs/long.md", "as": "docs/long.md", "lines": "1-40"},
      {"kind": "file", "path": "saved/page.md", "as": "alternatives/x.md",
       "origin": "https://example.com/x", "captured": "2026-10-04"},
      {"kind": "url", "url": "https://example.com/pricing", "as": "alternatives/pricing.md"},
      {"kind": "excerpt", "path": "~/notes.md", "match": "(?i)example", "as": "notes.md"},
      {"kind": "git_log", "repo": "~/repo", "branch": "main", "days": 60, "as": "commits.md"},
      {"kind": "temper_stats", "api": "http://127.0.0.1:8420", "days": 30, "as": "stats.md"}]}

- file: a text file, whole, or only some `sections` (markdown headings starting with the given
  text, each with everything under it; `intro: true` adds the lines between the title and the
  first heading) or `lines` ("a-b"). `exclude` leaves out lines matching a
  regular expression, and the header says how many. `origin` and `captured` record a page saved
  by hand. Files that look like secrets or databases are refused.
- url: a public page, fetched once and turned into plain text.
- excerpt: the lines of a file that match `match` (and not `exclude`), each with its line number.
- git_log: the first-parent commit titles of a branch over the last `days` days, with the command.
- temper_stats: a temper server's runs over the last `days` days, per workflow: runs, completed
  share, median cost and median duration, with the exact query and window. The server's list keeps
  a fixed number of the newest runs: when it doesn't reach back that far, the window is what it
  holds and the file says so. `raw` (a path outside the folder) saves the rows used.

Any source may carry `note`: one line under the header saying who wrote it or what it is.
Writes index.md (every file, its source and what was copied) into the folder, refuses a folder
that is not empty, and prints a manifest (each file's sha256) that --manifest also saves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

MAX_BYTES = 150_000  # one evidence file; bigger sources take `sections` or `lines`
PAGE_BYTES = 3_000_000
MIN_PAGE_TEXT = 200
SECRET_NAME = re.compile(
    r"(^|[._-])(secret|secrets|credential|credentials|token|tokens|password|passwords)([._-]|$)"
    r"|^\.env($|\.)|\.(env|db|sqlite|sqlite3|pem|key|p12|pfx)$|^auth\.json$|^id_(rsa|ed25519|ecdsa)",
    re.I)
HEADING = re.compile(r"^(#{1,6})\s+\S")
FENCE = re.compile(r"^\s*(```|~~~)")
KINDS = ("file", "url", "excerpt", "git_log", "temper_stats")
ENDED = ("completed", "failed", "cancelled")


class GatherError(Exception):
    """A source that can't be gathered as asked."""


def home_short(path: str | Path) -> str:
    text, home = str(path), str(Path.home())
    return "~" + text[len(home):] if text == home or text.startswith(home + os.sep) else text


def captured_now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")


def header(source: str, captured: str, copied: str, note: str = "") -> str:
    lines = [f"Source: {source}", f"Captured: {captured}", f"Copied: {copied}"]
    if note:
        lines.append(f"Note: {note}")
    return "\n".join(lines) + "\n\n---\n\n"


# ---- file ----------------------------------------------------------------------------------------


def read_text_file(path: Path) -> str:
    if SECRET_NAME.search(path.name):
        raise GatherError(f"{home_short(path)} looks like a secret or a database: not copied")
    if not path.is_file():
        raise GatherError(f"no file at {home_short(path)}")
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        raise GatherError(f"{home_short(path)} is not a text file")
    return data.decode("utf-8", errors="replace")


def line_range(text: str, spec: str) -> tuple[list[str], str]:
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", spec)
    if not match:
        raise GatherError(f"lines {spec!r} is not 'a-b'")
    first, last = int(match.group(1)), int(match.group(2))
    lines = text.split("\n")
    if not 1 <= first <= last <= len(lines):
        raise GatherError(f"lines {spec} is outside the file's {len(lines)} lines")
    return lines[first - 1:last], f"lines {first}-{last}"


def headings(lines: list[str]) -> list[tuple[int, int]]:
    """(index, level) of every markdown heading outside fenced code."""
    found, fenced = [], False
    for i, line in enumerate(lines):
        if FENCE.match(line):
            fenced = not fenced
            continue
        match = None if fenced else HEADING.match(line)
        if match:
            found.append((i, len(match.group(1))))
    return found


def select_sections(text: str, prefixes: list[str], intro: bool = False) -> tuple[list[str], str]:
    """The title line, its opening lines when `intro`, then each heading that starts with one of
    `prefixes` and all under it."""
    lines = text.split("\n")
    marks = headings(lines)
    chosen: set[int] = set()
    title = next((i for i, level in marks if level == 1), None)
    if intro:
        start = title if title is not None else 0
        chosen.update(range(start, next((j for j, _ in marks if j > start), len(lines))))
    for prefix in prefixes:
        hits = [(i, level) for i, level in marks if lines[i].strip().startswith(prefix.strip())]
        if not hits:
            raise GatherError(f"no heading starts with {prefix!r}")
        for i, level in hits:
            end = next((j for j, lv in marks if j > i and lv <= level), len(lines))
            chosen.update(range(i, end))
    keep = sorted(chosen | ({title} if title is not None else set()))
    out, previous = [], None
    for i in keep:
        if previous is not None and i != previous + 1:
            out += ["", "[...]", ""]
        out.append(lines[i])
        previous = i
    parts = ["the title"] + (["its opening lines"] if intro else [])
    if prefixes:
        parts.append("the sections " + ", ".join(repr(p) for p in prefixes))
    return out, ", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]


def gather_file(src: dict) -> tuple[str, str]:
    path = Path(os.path.expanduser(src["path"]))
    text = read_text_file(path)
    if (src.get("sections") or src.get("intro")) and src.get("lines"):
        raise GatherError("give sections or lines, not both")
    if src.get("sections") or src.get("intro"):
        lines, copied = select_sections(text, list(src.get("sections") or []), bool(src.get("intro")))
    elif src.get("lines"):
        lines, copied = line_range(text, str(src["lines"]))
    else:
        lines, copied = text.split("\n"), "whole file"
    if src.get("exclude"):
        pattern = re.compile(src["exclude"])
        kept = [line for line in lines if not pattern.search(line)]
        copied += f"; {len(lines) - len(kept)} lines matching {src['exclude']!r} left out"
        lines = kept
    origin = src.get("origin")
    if origin:
        copied += f" (a copy saved by hand at {home_short(path)})"
    body = "\n".join(lines).strip("\n") + "\n"
    return header(origin or home_short(path), src.get("captured") or captured_now(), copied,
                  src.get("note", "")) + body, origin or home_short(path)


# ---- url -----------------------------------------------------------------------------------------


class _Text(HTMLParser):
    """Readable text of an HTML page: headings as '#', list items as '- ', no scripts or menus."""

    SKIP = {"script", "style", "noscript", "svg", "template", "nav", "footer", "iframe", "form"}
    BLOCK = {"p", "div", "section", "article", "main", "header", "aside", "ul", "ol", "table", "tr",
             "blockquote", "pre", "figure", "figcaption", "dl", "dt", "dd", "br", "hr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0
        self.title: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self.skipping += 1
        elif tag == "title":
            self.in_title = True
        elif not self.skipping:
            if re.fullmatch(r"h[1-6]", tag):
                self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
            elif tag == "li":
                self.parts.append("\n- ")
            elif tag in self.BLOCK:
                self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag == "title":
            self.in_title = False
        elif not self.skipping and (re.fullmatch(r"h[1-6]", tag) or tag in self.BLOCK or tag == "li"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title.append(data)
        elif not self.skipping:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """(title, text) of a page."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    lines, blank = [], False
    for raw in "".join(parser.parts).split("\n"):
        line = re.sub(r"[ \t\r\f\v\u00a0]+", " ", raw).strip()
        if line in ("", "-", "#"):
            if lines and not blank:
                lines.append("")
            blank = True
            continue
        lines.append(line)
        blank = False
    return re.sub(r"\s+", " ", "".join(parser.title)).strip(), "\n".join(lines).strip() + "\n"


def fetch_page(url: str) -> tuple[str, str]:
    """(content type, text) of a public page."""
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) gather_evidence/1",
        "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5"})
    with urllib.request.urlopen(request, timeout=30) as response:  # gather_url allows only http(s)
        kind = response.headers.get("Content-Type", "")
        charset = response.headers.get_content_charset() or "utf-8"
        return kind, response.read(PAGE_BYTES).decode(charset, errors="replace")


def gather_url(src: dict) -> tuple[str, str]:
    url = src["url"]
    if not url.startswith(("https://", "http://")):
        raise GatherError(f"{url} is not an http(s) address")
    try:
        kind, body = fetch_page(url)
    except Exception as exc:  # noqa: BLE001 - any network failure is the same answer
        raise GatherError(f"could not fetch {url}: {exc}") from exc
    title = ""
    if "html" in kind.lower() or body.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        title, body = html_to_text(body)
    if len(body.strip()) < MIN_PAGE_TEXT:
        raise GatherError(f"{url} gave almost no text (a page drawn by JavaScript?): save it by hand "
                          f"and give it as a file with origin")
    copied = "the page's text" + (f" (title: {title})" if title else "")
    return header(url, src.get("captured") or captured_now(), copied, src.get("note", "")) + body, url


# ---- excerpt and git_log -------------------------------------------------------------------------


def gather_excerpt(src: dict) -> tuple[str, str]:
    path = Path(os.path.expanduser(src["path"]))
    text = read_text_file(path)
    match = re.compile(src["match"])
    exclude = re.compile(src["exclude"]) if src.get("exclude") else None
    kept = [f"L{n}: {line}" for n, line in enumerate(text.split("\n"), 1)
            if match.search(line) and not (exclude and exclude.search(line))]
    if not kept:
        raise GatherError(f"no line of {home_short(path)} matches {src['match']!r}")
    copied = f"the lines matching {src['match']!r}" + (f", without those matching {src['exclude']!r}"
                                                       if exclude else "") + ", each with its line number"
    return header(home_short(path), src.get("captured") or captured_now(), copied,
                  src.get("note", "")) + "\n".join(kept) + "\n", home_short(path)


def gather_git_log(src: dict) -> tuple[str, str]:
    repo = Path(os.path.expanduser(src["repo"]))
    days = int(src.get("days", 60))
    branch = src.get("branch", "HEAD")
    since = (datetime.now().astimezone() - timedelta(days=days)).strftime("%Y-%m-%d")
    cmd = ["git", "-C", str(repo), "log", "--first-parent", branch, f"--since={since}",
           "--format=%h %ad %s", "--date=short"]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise GatherError(f"git log failed in {home_short(repo)}: {done.stderr.strip()}")
    lines = [line for line in done.stdout.split("\n") if line.strip()]
    shown = " ".join([*cmd[:2], home_short(repo), *cmd[3:]])
    copied = (f"the output of: {shown} ({len(lines)} commits: short hash, date, title; "
              f"the last {days} days)")
    return header(f"{home_short(repo)} (git, branch {branch})", src.get("captured") or captured_now(),
                  copied, src.get("note", "")) + "\n".join(lines) + "\n", home_short(repo)


# ---- temper_stats --------------------------------------------------------------------------------


def fetch_json(url: str):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def started(run: dict) -> datetime | None:
    text = run.get("start_time")
    if not text:
        return None
    when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def money(value: float) -> str:
    return f"${value:.2f}"


def listed_runs(api: str, page: int = 1000, max_pages: int = 50) -> tuple[list[dict], list[str]]:
    """Every run the server's list holds, each once, and the queries that fetched them.

    The list is newest first and grows while it is read, so later pages can repeat rows: they are
    kept once, by id. Big pages keep the read to one request where they can.
    """
    by_id: dict[str, dict] = {}
    queries = []
    for k in range(max_pages):
        url = f"{api.rstrip('/')}/api/workflows?limit={page}&offset={k * page}"
        queries.append(url)
        rows = fetch_json(url).get("runs") or []
        for row in rows:
            by_id.setdefault(str(row.get("id")), row)
        if len(rows) < page:
            return list(by_id.values()), queries
    raise GatherError(f"more than {max_pages * page} runs listed: raise max_pages")


def whole_minute(when: datetime, up: bool) -> datetime:
    floor = when.replace(second=0, microsecond=0)
    return floor + timedelta(minutes=1) if up and floor != when else floor


def stats_table(runs: list[dict]) -> tuple[list[str], dict]:
    by_name: dict[str, list[dict]] = {}
    for run in runs:
        by_name.setdefault(run.get("workflow_name") or "(unnamed)", []).append(run)

    def row(rs: list[dict]) -> dict:
        done = [r for r in rs if r.get("status") == "completed"]
        ended = [r for r in rs if r.get("status") in ENDED]
        costs = [float(r.get("total_cost_usd") or 0) for r in done]
        secs = [float(r["duration_seconds"]) for r in done if r.get("duration_seconds") is not None]
        return {"runs": len(rs), "completed": len(done),
                "failed": sum(r.get("status") == "failed" for r in rs),
                "cancelled": sum(r.get("status") == "cancelled" for r in rs),
                "share": f"{100 * len(done) / len(ended):.1f}%" if ended else "-",
                "cost": money(statistics.median(costs)) if costs else "-",
                "minutes": f"{statistics.median(secs) / 60:.1f}" if secs else "-"}

    lines = ["| workflow | runs | completed | failed | cancelled | completed share | median cost | median minutes |",
             "|---|---|---|---|---|---|---|---|"]
    for name, rs in sorted(by_name.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        r = row(rs)
        lines.append(f"| {name} | {r['runs']} | {r['completed']} | {r['failed']} | {r['cancelled']} | "
                     f"{r['share']} | {r['cost']} | {r['minutes']} |")
    total = row(runs)
    total["workflows"] = len(by_name)
    return lines, total


def gather_temper_stats(src: dict) -> tuple[str, str]:
    """Runs per workflow over the last `days` days, or over the part of them the server's run list
    still holds (it keeps a fixed number of the newest runs), said plainly. Both ends of the window
    are whole minutes, so the same window can be asked again. `raw` saves the rows used."""
    api, days = src.get("api", "http://127.0.0.1:8420"), int(src.get("days", 30))
    now = datetime.now(UTC)
    try:
        listed, queries = listed_runs(api)
    except GatherError:
        raise
    except Exception as exc:  # noqa: BLE001 - any API failure is the same answer
        raise GatherError(f"could not read {api}/api/workflows: {exc}") from exc
    times = [when for when in (started(r) for r in listed) if when]
    if not times:
        raise GatherError(f"{api}/api/workflows lists no runs")
    oldest = min(times)
    first = whole_minute(max(now - timedelta(days=days), oldest), up=True)
    last = whole_minute(now, up=False)
    runs = [r for r in listed if (when := started(r)) and first <= when < last]
    table, t = stats_table(runs)
    if src.get("raw"):
        keep = ("id", "workflow_name", "status", "start_time", "end_time", "duration_seconds", "total_cost_usd")
        Path(os.path.expanduser(src["raw"])).write_text(json.dumps(
            {"queries": queries, "window_utc": [f"{first:%Y-%m-%d %H:%M}", f"{last:%Y-%m-%d %H:%M}"],
             "runs": [{k: r.get(k) for k in keep} for r in runs]}, indent=1) + "\n")
    span = (last - first).total_seconds() / 86400
    reach = "" if oldest <= now - timedelta(days=days) else (
        f"The server's run list holds a fixed number of the newest runs; when this ran they reached back "
        f"only to {oldest:%Y-%m-%d %H:%M} UTC, so this covers {span:.1f} days, not the {days} asked for.")
    captured = now.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    body = [
        f"# Workflow runs on the temper server, {first:%Y-%m-%d %H:%M} to {last:%Y-%m-%d %H:%M} UTC",
        "",
        f"Query: GET {queries[0]}" + (f" and {len(queries) - 1} more pages" if len(queries) > 1 else "")
        + f" ({len(listed)} runs listed, each counted once), keeping every run whose start_time is at or "
        f"after {first:%Y-%m-%d %H:%M} UTC and before {last:%Y-%m-%d %H:%M} UTC ({span:.1f} days, ending "
        f"when it ran)." + (f" {reach}" if reach else ""),
        "Definitions: completed share is completed runs out of runs that ended (completed, failed or "
        "cancelled); runs still going are left out of it. Median cost (total_cost_usd as the server "
        "records it) and median duration are over completed runs only.",
        "",
        f"Totals: {t['runs']} runs of {t['workflows']} workflows; {t['completed']} completed, "
        f"{t['failed']} failed, {t['cancelled']} cancelled; completed share {t['share']}; "
        f"median cost {t['cost']}; median duration {t['minutes']} minutes.",
        "",
        *table,
    ]
    copied = f"runs per workflow computed from the server's run list ({len(runs)} runs)"
    return header(f"{api} (temper server API)", captured, copied, src.get("note", "")) + "\n".join(body) + "\n", api


# ---- the folder ----------------------------------------------------------------------------------

GATHER = {"file": gather_file, "url": gather_url, "excerpt": gather_excerpt, "git_log": gather_git_log,
          "temper_stats": gather_temper_stats}


def load_sources(path: Path) -> dict:
    spec = json.loads(path.read_text())
    if not isinstance(spec, dict) or not spec.get("product") or not isinstance(spec.get("sources"), list):
        raise GatherError(f"{path}: needs a product and a list of sources")
    seen = set()
    for n, src in enumerate(spec["sources"], 1):
        kind, target = src.get("kind"), src.get("as", "")
        if kind not in KINDS:
            raise GatherError(f"source {n}: kind {kind!r} is not one of {', '.join(KINDS)}")
        rel = PurePosixPath(target)
        if not target or rel.is_absolute() or ".." in rel.parts or target == "index.md":
            raise GatherError(f"source {n}: 'as' must be a new relative path inside the folder, not {target!r}")
        if target in seen:
            raise GatherError(f"source {n}: {target} is written twice")
        seen.add(target)
        needs = {"file": ("path",), "url": ("url",), "excerpt": ("path", "match"), "git_log": ("repo",),
                 "temper_stats": ()}[kind]
        missing = [k for k in needs if not src.get(k)]
        if missing:
            raise GatherError(f"source {n} ({kind}): missing {', '.join(missing)}")
    return spec


def gather(sources_path: Path, out: Path) -> dict:
    spec = load_sources(sources_path)
    if out.exists() and any(out.iterdir()):
        raise GatherError(f"{out} is not empty: gather into a new folder")
    written: list[tuple[str, str, str]] = []
    texts: dict[str, str] = {}
    for src in spec["sources"]:
        text, origin = GATHER[src["kind"]](src)
        if len(text.encode()) > MAX_BYTES:
            raise GatherError(f"{src['as']} would be {len(text.encode())} bytes (over {MAX_BYTES}): "
                              f"take sections or lines")
        texts[src["as"]] = text
        copied = text.split("\n")[2].removeprefix("Copied: ")
        written.append((src["as"], origin, copied))
    captured = captured_now()
    index = [f"# Evidence index: {spec['product']}", "",
             f"Gathered {captured} by gather_evidence.py from {sources_path.name}. Each file opens with "
             "its source, when it was captured and what was copied.", "",
             "| file | source | copied |", "|---|---|---|"]
    index += [f"| {rel} | {origin} | {copied} |" for rel, origin, copied in written]
    texts["index.md"] = "\n".join(index) + "\n"
    out.mkdir(parents=True, exist_ok=True)
    for rel, text in texts.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return {"product": spec["product"], "captured": captured, "folder": home_short(out.resolve()),
            "files": {rel: hashlib.sha256((out / rel).read_bytes()).hexdigest() for rel in sorted(texts)}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = gather(args.sources, args.out)
    except GatherError as exc:
        print(f"gather_evidence: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(manifest, indent=1)
    if args.manifest:
        args.manifest.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
