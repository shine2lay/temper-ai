"""Compact noisy command output before it reaches the model.

A Bash result is not read once: with no prompt caching on the anthropic
provider, every tool result stays in the transcript and is re-sent on every
later iteration of the run. A 7,000-token `git log` costs 7,000 tokens per
turn for the rest of the node, not once.

Four stages, each conservative, in order of how much they can lose:

1. **ANSI stripping** — lossless.
2. **Progress collapsing** — lines that are pure progress (pytest's dots,
   download bars, carriage-return spinners) carry a count and nothing else.
   Replaced with that count.
3. **`git log` condensation** — only for plain `git log` (never `-p`/`--stat`,
   which the agent asked for on purpose): one line per commit. This repo's own
   log is 7,146 tokens for 20 commits because the messages are long.
4. **Head+tail window** — the net, if it is still too big. Biased to the tail:
   a build or test run puts the failure and the summary at the END, so the
   existing head-only truncation kept exactly the wrong half.

What is deliberately NOT compacted: anything that looks like a diff, and any
line that could be a failure, error or traceback. pi-rtk-optimizer ships read
compaction defaulted to off because lossy reads break exact-string edits
("old text does not match"); the same reasoning applies to a `git diff` an
agent is about to apply. When in doubt this keeps the bytes.

Every reduction leaves a marker saying what happened and what to do instead —
an agent that cannot see the omission cannot work around it.
"""

import re

# Progress-only lines: pytest's "......F..", coverage bars, npm/pip download ticks.
_PROGRESS_LINE = re.compile(r"^[\s.sFExX%\u2588\u2591\u2500\-=>#\[\]0-9/]*$")
#: pytest's per-file progress, e.g. "tests/test_tools/test_bash.py ......  [ 12%]".
#: Only when every result on the line passed or skipped — a line containing F, E
#: or x names a file the agent needs to see, so it is never collapsed.
_PYTEST_PASS_LINE = re.compile(r"^\S+\.py\s+[.s]+\s*(\[\s*\d{1,3}%\])?\s*$")
_DOWNLOAD_LINE = re.compile(r"^\s*(Downloading|Collecting|Installing|Fetching|Resolving|Building wheel|Using cached|Preparing|Requirement already satisfied)\b")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\r(?!\n)")
_DIFF_MARKER = re.compile(r"^(diff --git |index [0-9a-f]+\.\.|@@ |\+\+\+ |--- )")
_GIT_LOG_COMMIT = re.compile(r"^commit ([0-9a-f]{7,40})")

#: Command output above this is windowed. ~10k tokens; the LLM layer's own cap
#: is 200k chars, which is far too late to be useful.
DEFAULT_MAX_CHARS = 40_000
_HEAD_LINES = 60
_TAIL_LINES = 240


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def looks_like_diff(text: str) -> bool:
    """A diff is content the agent likely intends to apply — never touch it."""
    head = text[:4000]
    return bool(_DIFF_MARKER.search(head)) or head.lstrip().startswith(("diff --git", "--- ", "@@ "))


#: A run shorter than this is kept verbatim: it is probably not progress noise,
#: and dropping a few lines invisibly is worse than the tokens it saves.
_MIN_PROGRESS_RUN = 4


def collapse_progress(text: str) -> tuple[str, int]:
    """Replace long runs of progress-only lines with a count. Returns (text, lines_removed)."""
    out: list[str] = []
    run: list[str] = []
    removed = 0

    def flush() -> None:
        nonlocal removed
        if len(run) >= _MIN_PROGRESS_RUN:
            out.append(f"[{len(run)} progress lines]")
            removed += len(run)
        else:
            out.extend(run)  # too short to be sure it is noise — keep it
        run.clear()

    for line in text.split("\n"):
        stripped = line.strip()
        is_progress = bool(stripped) and (
            (_PROGRESS_LINE.match(stripped) and len(stripped) > 8)
            or _DOWNLOAD_LINE.match(stripped)
            or _PYTEST_PASS_LINE.match(stripped)
        )
        if is_progress:
            run.append(line)
            continue
        flush()
        out.append(line)
    flush()
    return "\n".join(out), removed


def condense_git_log(text: str) -> tuple[str, int]:
    """One line per commit for a plain `git log`. Returns (text, commits_condensed)."""
    lines = text.split("\n")
    out: list[str] = []
    commits = 0
    i = 0
    while i < len(lines):
        m = _GIT_LOG_COMMIT.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        sha = m.group(1)[:9]
        subject = ""
        date = ""
        i += 1
        while i < len(lines) and not _GIT_LOG_COMMIT.match(lines[i]):
            line = lines[i]
            if line.startswith("Date:"):
                date = line.split(":", 1)[1].strip()[:16]
            elif not subject and line.startswith("    ") and line.strip():
                subject = line.strip()
            i += 1
        commits += 1
        out.append(f"{sha} {date}  {subject}".rstrip())
    return "\n".join(out), commits


def window(text: str, max_chars: int) -> tuple[str, int]:
    """Keep the head and (mostly) the tail. Returns (text, lines_omitted)."""
    if len(text) <= max_chars:
        return text, 0
    lines = text.split("\n")
    if len(lines) <= _HEAD_LINES + _TAIL_LINES:
        # Few, very long lines: cut from the middle of the text itself.
        keep = max_chars // 2
        return (
            f"{text[:keep]}\n\n[… {len(text) - max_chars} characters omitted from the middle …]\n\n{text[-keep:]}",
            0,
        )
    omitted = len(lines) - _HEAD_LINES - _TAIL_LINES
    head, tail = lines[:_HEAD_LINES], lines[-_TAIL_LINES:]
    marker = (
        f"[… {omitted} lines omitted from the middle. The end is kept because failures and "
        f"summaries appear there. Narrow the command, or redirect to a file and use Read with offset. …]"
    )
    return "\n".join([*head, "", marker, "", *tail]), omitted


def compact(command: str, text: str, max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, list[str]]:
    """Compact one command's output. Returns (text, notes) — notes describe every reduction."""
    if not text:
        return text, []

    notes: list[str] = []
    original_len = len(text)

    cleaned = strip_ansi(text)
    if len(cleaned) < original_len:
        notes.append("ANSI codes stripped")
    text = cleaned

    # A diff is kept verbatim apart from ANSI and the final size net.
    if not looks_like_diff(text):
        text, progress_removed = collapse_progress(text)
        if progress_removed:
            notes.append(f"{progress_removed} progress lines collapsed")

        stripped_cmd = command.strip()
        if re.search(r"\bgit\b[^|;&]*\blog\b", stripped_cmd) and not re.search(r"-p\b|--patch|--stat|--numstat", stripped_cmd):
            text, commits = condense_git_log(text)
            if commits:
                notes.append(f"{commits} commits condensed to one line each")

    text, omitted = window(text, max_chars)
    if omitted:
        notes.append(f"{omitted} lines omitted")

    if notes and len(text) < original_len:
        saved = round(100 * (1 - len(text) / original_len))
        if saved >= 1:
            notes.append(f"{saved}% smaller")
    return text, notes
