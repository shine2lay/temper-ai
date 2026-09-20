#!/usr/bin/env python3
"""Deterministic credential / risky-file scan of ONLY what a branch ADDED.

Used by the `task_security` agent as its first move. Everything here is regex and arithmetic: no model
sees the diff before this runs, so a key cannot be missed because a 2,000-line diff got skimmed. The
model's job is the part this cannot do — deciding whether a hit is a real credential or a fixture, and
reading the same diff for the problems no pattern finds (an endpoint that lost its auth check, a query
that lost its tenant filter, user input concatenated into SQL).

TWO THINGS THIS DOES THAT THE OBVIOUS VERSION DOES NOT:

1. It reads EVERY COMMIT on the branch, not the net diff. `git diff base..HEAD` shows what the branch
   ships; it does not show a key that was committed in the first commit and deleted in the third. That
   key is still in the branch's history and would still be published the moment the branch is pushed —
   removing a secret in a later commit does not un-commit it. The net diff is exactly the wrong lens for
   this one question, so the scan walks `git log -p base..HEAD` instead.

2. It scans PATHS, not just contents. The worst real leak is not a key pasted into source, it is a file
   that should never have been tracked at all — `.env.pre-deploy`, a `.pem`, a service-account JSON —
   swept in by a `git add -A` because .gitignore listed `.env.local` and the file was called something
   else. A content scan can miss those (a 108-character token in a shell-assignment file may not look
   like anything); the filename never does.

Scope is the branch's additions and nothing else, which is the whole point: a finding has to be about
this change. Pre-existing secrets elsewhere in the repository are not this branch's business and are not
reported here.

Usage:  diff_scan.py <worktree> <base_ref>   ->  one JSON document on stdout
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

# A branch can add a lot; a scan that returns 4,000 hits is a scan nobody reads. These caps keep the
# report inside a prompt, and `truncated` tells the agent when something was left out so it can go look
# rather than assume it saw everything.
MAX_HITS = 80
MAX_LINE_CHARS = 240
BIG_DIFF_LINES = 200_000

#: Files whose added lines are skipped: machine-written, and full of long random-looking strings that are
#: hashes, not secrets. Scanning them produces pages of entropy hits and hides the real one.
SKIP_SUFFIXES = (
    ".lock", ".min.js", ".min.css", ".map", ".snap", ".svg", ".po", ".pot", ".woff", ".woff2",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".whl", ".parquet",
)
SKIP_NAMES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "go.sum", "Cargo.lock", "uv.lock", "poetry.lock")
#: The pipeline's own notes live here (plan.md, review.md). Not the branch's code.
SKIP_PREFIXES = (".epd/",)

#: Paths that should essentially never be committed. Matched on the filename or the path, case-insensitive.
#: The allow-list exists because `.env.example` is how a repository documents its variables — the point is
#: to catch `.env.pre-deploy`, not to ban the word env.
ENV_ALLOWED = re.compile(r"\.env\.(example|sample|template|dist|defaults?)$|^\.env\.example$", re.I)
RISKY_PATHS: tuple[tuple[str, str, str], ...] = (
    # (rule, regex over the full path, why it matters)
    ("env_file", r"(^|/)\.env($|\.)", "an environment file: these hold real credentials and are the most common leak"),
    ("private_key", r"\.(pem|key|p8|pkcs12|p12|pfx|jks|keystore)$", "a private key or keystore"),
    ("ssh_key", r"(^|/)(id_rsa|id_dsa|id_ecdsa|id_ed25519)(\.|$)", "an SSH private key"),
    ("cloud_creds", r"(^|/)(credentials|service[-_]?account.*\.json|gcloud-.*\.json|\.pgpass|\.netrc|\.npmrc|\.pypirc)$",
     "a credentials file for a package registry or cloud provider"),
    ("kubeconfig", r"(^|/)(kubeconfig|\.kube/config)$", "a kubeconfig: usually carries a cluster token"),
    ("tfstate", r"\.tfstate(\.backup)?$", "terraform state: stores resource secrets in plain text"),
    ("dump", r"\.(sql|dump|bak)$", "a database dump or backup: may carry production data"),
)

#: Credential shapes worth naming. Ordered most specific first; the first rule that matches a line wins,
#: so `sk-ant-…` is reported as an Anthropic key rather than as generic entropy.
#: Every one of these is a prefix a provider actually issues, so a match is a strong signal on its own —
#: unlike the generic assignment rule below, which needs the placeholder and entropy filters to be useful.
TOKEN_RULES: tuple[tuple[str, str, str], ...] = (
    ("anthropic_key", r"sk-ant-[A-Za-z0-9_\-]{16,}", "Anthropic API key"),
    ("openai_key", r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}", "OpenAI API key"),
    ("github_token", r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})", "GitHub token"),
    ("gitlab_token", r"\bglpat-[A-Za-z0-9_\-]{16,}", "GitLab token"),
    ("aws_key_id", r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b", "AWS access key id"),
    ("google_key", r"\bAIza[0-9A-Za-z_\-]{35}\b", "Google API key"),
    ("slack_token", r"\bxox[baprs]-[A-Za-z0-9\-]{10,}", "Slack token"),
    ("stripe_key", r"\b[sr]k_live_[A-Za-z0-9]{16,}", "Stripe live key"),
    ("sendgrid_key", r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}", "SendGrid key"),
    ("npm_token", r"\bnpm_[A-Za-z0-9]{30,}", "npm token"),
    ("digitalocean", r"\bdop_v1_[a-f0-9]{32,}", "DigitalOcean token"),
    ("huggingface", r"\bhf_[A-Za-z0-9]{30,}", "Hugging Face token"),
    ("temper_token", r"\btpv\d_[A-Za-z0-9_\-]{16,}", "temper internal API token"),
    ("private_key_block", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----", "an inline private key"),
    ("jwt", r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}", "a signed JWT"),
    ("url_credentials", r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s:/@]{3,}@", "credentials inside a URL"),
)

#: The catch-all: something named like a secret being assigned a literal. On its own this is mostly noise
#: (every test fixture in the world matches), so a hit here is only kept when the value survives the
#: placeholder check and looks random. The model still gets the placeholder/entropy flags and decides.
ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(?P<name>[A-Za-z0-9_\-.]*                     # PROD_DB_PASSWORD, apiKey, client-secret …
       (?:pass(?:wd|word)?|secret|token|api[_\-]?key|access[_\-]?key|
          auth[_\-]?key|private[_\-]?key|credential|client[_\-]?secret|
          bearer|session[_\-]?key|encryption[_\-]?key|master[_\-]?key)
       [A-Za-z0-9_\-.]*)
    \s*[:=]\s*                                      # = or : (env files, YAML, JSON, source)
    (?P<quote>["']?)(?P<value>[^\s"',;)}]{8,})(?P=quote)
    """
)

#: Values that are obviously not credentials. A placeholder in a test is the single biggest source of
#: false positives, and a stage that cries wolf gets ignored, which is worse than not having it.
PLACEHOLDER = re.compile(
    r"""(?ix)^(
        x{3,}|\*{3,}|\.{3,}|-+|_+
      | (?:your|my|the)[-_ ]?\w*
      | change[-_]?me | placeholder | example | dummy | fake | sample | redacted | omitted
      | test(?:ing)?[-_]?\w* | foo\w* | bar\w* | baz\w* | secret | password | token | changeit
      | none | null | nil | true | false | undefined | empty
      | \$\{[^}]*\} | \{\{[^}]*\}\} | <[^>]*> | %\([^)]*\)s | \$[A-Z_]+
    )$"""
)
#: Substrings that mark a value as a stand-in wherever they appear inside it.
PLACEHOLDER_INSIDE = ("xxxx", "abc123", "redacted", "example.com", "changeme", "your-", "your_", "notreal", "dummy")

TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|fixtures?|mocks?|testdata|e2e|examples?)(/|$)|(^|/)(conftest|test_[^/]*|[^/]*_test|[^/]*\.spec|[^/]*\.test)\.", re.I)

#: Lines that are documentation of a shape rather than a value: a comment showing the format of a key.
DOC_LINE = re.compile(r"^\s*(#|//|\*|<!--)")

#: A value that is CODE, not a literal. `API_KEY = os.environ["API_KEY"]` is the pattern this stage wants
#: people to use, so flagging it would train everyone to ignore the stage. Only reachable for unquoted
#: values, which the assignment rule has to allow because that is how an .env file is written.
CODE_VALUE = re.compile(
    r"""(?ix)^(
        (?:os\.)?environ | os\.getenv | getenv | process\.env | import\.meta\.env | Deno\.env
      | settings | config | secrets | credentials | self | this | cls | request | ctx
      | \w+\s*\( | \w+(?:\.\w+)+ | \w+\[ | new\s+\w+ | await\s+\w+
    )"""
)


def shannon(s: str) -> float:
    """Bits of entropy per character. A real 40-character token sits above 4.0; an English sentence and a
    dotted module path sit well below it. Used only to rank, never to decide on its own."""
    if not s:
        return 0.0
    return -sum((n / len(s)) * math.log2(n / len(s)) for n in (s.count(c) for c in set(s)))


def looks_credential(value: str) -> bool:
    """Could this value authenticate somewhere?

    Only the generic `name looks secret-ish = literal` rule needs this; the provider prefixes above are
    evidence on their own. Entropy alone does not separate `TOKEN_HEADER = "Authorization"` from a real
    key — both score around 3.4 — so this asks the question entropy cannot: does it look GENERATED?
    Issued credentials mix character classes or are simply long. English words and header names do not.

    Deliberately lets an all-lowercase passphrase through the net. It is indistinguishable from prose by
    any rule, and the alternative — flagging every lowercase string assigned to a variable with `token` in
    its name — is the noise that makes a scanner worth ignoring. The model still reads the diff.
    """
    v = value.strip().strip("\"'")
    if len(v) >= 32:
        return True
    has_digit = any(c.isdigit() for c in v)
    has_alpha = any(c.isalpha() for c in v)
    if has_digit and has_alpha and len(v) >= 12:
        return True
    if any(c.isupper() for c in v) and any(c.islower() for c in v) and len(v) >= 16:
        return True
    return bool(re.fullmatch(r"[0-9a-fA-F]{24,}", v))


def looks_placeholder(value: str) -> bool:
    low = value.strip().strip("\"'")
    if PLACEHOLDER.match(low):
        return True
    return any(mark in low.lower() for mark in PLACEHOLDER_INSIDE)


def redact(value: str) -> str:
    """Never put a credential in the report. The report is written into the worktree and the JSON goes
    into the run's event log, so printing the match in full would copy the secret into two more places —
    the exact mistake the stage exists to catch. Four characters is enough to find the line."""
    v = value.strip().strip("\"'")
    head = v[:4]
    kind = (
        "hex" if re.fullmatch(r"[0-9a-fA-F]+", v)
        else "base64ish" if re.fullmatch(r"[A-Za-z0-9+/=_\-]+", v)
        else "mixed"
    )
    return f"{head}… ({len(v)} chars, {kind})"


def skip_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (
        path.startswith(SKIP_PREFIXES)
        or name in SKIP_NAMES
        or path.endswith(SKIP_SUFFIXES)
    )


@dataclass
class Hit:
    rule: str
    what: str
    path: str
    line: int
    commit: str
    match_redacted: str
    context: str
    in_test_path: bool
    looks_placeholder: bool
    entropy: float
    #: The matched text. Kept so the value itself can be looked for in the current tree; NEVER serialised —
    #: `as_dict` emits only `match_redacted`, and this field is the reason that distinction has to be kept.
    value: str = ""
    still_present: bool = True
    #: Did the commit that added this value reach a remote? This is the whole difference between "rewrite
    #: the branch and it is genuinely gone" and "rotate, because a rewrite does not un-publish anything".
    #: None means the question could not be answered, which is NOT the same as no and is treated as yes.
    on_remote: bool | None = None

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "what": self.what,
            "path": self.path,
            "line": self.line,
            "commit": self.commit[:12],
            "match_redacted": self.match_redacted,
            "context": self.context,
            "in_test_path": self.in_test_path,
            "looks_placeholder": self.looks_placeholder,
            "entropy": round(self.entropy, 2),
            "still_in_working_tree": self.still_present,
            "commit_reached_remote": self.on_remote,
        }


@dataclass
class Scan:
    commits: list[dict] = field(default_factory=list)
    files: set[str] = field(default_factory=set)
    added_lines: int = 0
    hits: list[Hit] = field(default_factory=list)
    risky_paths: list[dict] = field(default_factory=list)
    ignore_removals: list[dict] = field(default_factory=list)
    skipped: set[str] = field(default_factory=set)
    truncated: bool = False


def git(worktree: str, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", worktree, *args],
        capture_output=True, text=True, errors="replace", check=False,
    )
    if out.returncode != 0 and not out.stdout:
        raise SystemExit(json.dumps({"error": f"git {' '.join(args)} failed: {out.stderr.strip()[:300]}"}))
    return out.stdout


def git_soft(worktree: str, *args: str) -> str:
    """For commands whose non-zero exit IS the answer. ``check-ignore`` exits 1 to say "not ignored", which
    is the case this scan most wants to hear about: a file that should have been ignored and was not."""
    out = subprocess.run(
        ["git", "-C", worktree, *args],
        capture_output=True, text=True, errors="replace", check=False,
    )
    return out.stdout


def scan_line(scan: Scan, path: str, lineno: int, commit: str, text: str) -> None:
    """One added line against every rule. A line can only produce one token hit — the most specific one —
    so a key does not arrive three times under three names."""
    if len(scan.hits) >= MAX_HITS:
        scan.truncated = True
        return
    stripped = text[:MAX_LINE_CHARS]
    in_test = bool(TEST_PATH.search(path))

    for rule, pattern, what in TOKEN_RULES:
        m = re.search(pattern, stripped)
        if not m:
            continue
        value = m.group(0)
        scan.hits.append(Hit(
            rule=rule, what=what, path=path, line=lineno, commit=commit,
            match_redacted=redact(value),
            context=stripped.replace(value, redact(value)).strip(),
            in_test_path=in_test, looks_placeholder=looks_placeholder(value),
            entropy=shannon(value), value=value,
        ))
        return  # most specific rule wins

    m = ASSIGNMENT.search(stripped)
    if not m:
        return
    value = m.group("value")
    # Reading a secret out of the environment is the fix, not the problem.
    if not m.group("quote") and CODE_VALUE.match(value):
        return
    placeholder = looks_placeholder(value)
    entropy = shannon(value)
    # A documented shape in a comment, or a low-entropy word, is not a credential. Keep the line only when
    # it could plausibly authenticate somewhere; everything else would bury the real hits.
    if DOC_LINE.match(stripped) and placeholder:
        return
    if not looks_credential(value):
        return
    if placeholder and entropy < 3.5:
        return
    scan.hits.append(Hit(
        rule="secret_assignment", what=f"a value assigned to `{m.group('name')}`",
        path=path, line=lineno, commit=commit,
        match_redacted=redact(value),
        context=stripped.replace(value, redact(value)).strip(),
        in_test_path=in_test, looks_placeholder=placeholder, entropy=entropy, value=value,
    ))


def reach(worktree: str, commits: list[str]) -> dict:
    """Has any of this branch's history left the machine?

    A credential that never reached a remote can genuinely be erased by rewriting the branch: nobody else
    ever had the chance to fetch it. One that HAS been pushed cannot — a rewrite only changes what new
    clones see, the old object stays on the server until its owner purges it, so the value is published and
    rotation is the only fix. The two cases want opposite advice, so the question gets answered by looking
    rather than assuming.

    Answered from remote-tracking refs, which is local evidence about a remote and can be out of date. That
    is why an unanswerable question returns None and the caller treats None as "reached": the expensive
    mistake is calling a published key safe, not the reverse.
    """
    remotes = [r for r in git_soft(worktree, "remote").splitlines() if r.strip()]
    if not remotes:
        # Nowhere to have pushed TO. The strongest possible evidence, and the normal case for a worktree
        # the pipeline just created.
        return {"remotes": [], "pushed": {c: False for c in commits}, "confident": True,
                "why": "the repository has no remote configured, so nothing here can have been pushed"}

    tracking = [ln.strip() for ln in git_soft(worktree, "for-each-ref", "--format=%(refname)",
                                              "refs/remotes/").splitlines() if ln.strip()]
    if not tracking:
        return {"remotes": remotes, "pushed": {c: False for c in commits}, "confident": True,
                "why": f"remote(s) {', '.join(remotes)} configured but no remote-tracking ref exists, "
                       "so this repository has never fetched or pushed anything"}

    pushed: dict[str, bool | None] = {}
    for sha in commits:
        out = git_soft(worktree, "branch", "-r", "--contains", sha)
        # `branch -r --contains` prints nothing both when the commit is on no remote branch and when git
        # cannot answer; the exit status is swallowed by git_soft, so an empty answer is only trusted
        # because the tracking refs above proved this repo does talk to a remote.
        pushed[sha] = bool(out.strip())
    return {
        "remotes": remotes,
        "pushed": pushed,
        "confident": False,
        "why": "answered from remote-tracking refs without fetching; a branch pushed from a different "
               "clone since the last fetch would not show here. Run `git fetch --all` first to be sure.",
    }


def _contains(worktree: str, path: str, value: str) -> bool:
    """Is this exact value still in this file? Unreadable or missing counts as yes: a scanner that cannot
    read a file must not be the reason a credential is reported as already gone."""
    if not value:
        return True
    try:
        with open(os.path.join(worktree, path), encoding="utf-8", errors="replace") as fh:
            return value in fh.read()
    except OSError:
        return True


def main() -> int:
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: diff_scan.py <worktree> <base_ref>"}))
        return 2
    worktree, base = sys.argv[1], sys.argv[2]
    scan = Scan()

    head = git(worktree, "rev-parse", "HEAD").strip()
    merge_base = git(worktree, "merge-base", base, "HEAD").strip() or base

    # --reverse so the commits read oldest first, -U0 so only the changed lines come back (context lines
    # are not this branch's additions), --no-renames so a renamed file's whole content is seen as added —
    # a secret moved into a new path is a secret this branch put there.
    raw = git(
        worktree, "log", "--reverse", "-p", "-U0", "--no-color", "--no-renames",
        "--format=%x01%H%x1f%s", f"{merge_base}..HEAD",
    )
    if raw.count("\n") > BIG_DIFF_LINES:
        scan.truncated = True

    commit = subject = ""
    path = ""
    lineno = 0
    new_file = False
    for raw_line in raw.splitlines()[:BIG_DIFF_LINES]:
        if raw_line.startswith("\x01"):
            commit, _, subject = raw_line[1:].partition("\x1f")
            scan.commits.append({"sha": commit[:12], "subject": subject})
            path, new_file = "", False
            continue
        if raw_line.startswith("diff --git "):
            path, new_file = "", False
            continue
        if raw_line.startswith("new file mode"):
            new_file = True
            continue
        if raw_line.startswith("+++ "):
            target = raw_line[4:].strip()
            path = "" if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            if path:
                scan.files.add(path)
                if skip_path(path):
                    scan.skipped.add(path)
                elif new_file:
                    _check_path(scan, path, commit)
            continue
        if raw_line.startswith("@@"):
            m = re.match(r"@@ -\S+ \+(\d+)", raw_line)
            lineno = int(m.group(1)) if m else 0
            continue
        if not path or skip_path(path):
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            scan.added_lines += 1
            scan_line(scan, path, lineno, commit, raw_line[1:])
            lineno += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            # A rule LEAVING .gitignore is how a file that was safely ignored starts getting committed.
            if path.endswith(".gitignore") and raw_line[1:].strip() and not raw_line[1:].lstrip().startswith("#"):
                scan.ignore_removals.append({"path": path, "pattern": raw_line[1:].strip(), "commit": commit[:12]})

    # Which hits are still in the working tree, and which were added and later removed. Both matter, and
    # they need different fixes: one is "delete the line", the other is "the line is gone and the secret
    # is still in the history".
    tracked_now = set(git(worktree, "ls-files").splitlines())
    for hit in scan.hits:
        # The VALUE, not the file. "Delete the whole file" and "edit the line and keep the file" are both
        # ordinary fixes, and asking whether the path is still tracked only answers the first: it called a
        # key replaced by `os.environ[...]` still present, which is the exact case this field exists to
        # distinguish. Read the file and look for the value.
        hit.still_present = hit.path in tracked_now and _contains(worktree, hit.path, hit.value)

    # Whether each hit's commit ever left the machine — the difference between "a rewrite really does erase
    # this" and "this is published, rotate it".
    reached = reach(worktree, sorted({h.commit for h in scan.hits}))
    for hit in scan.hits:
        hit.on_remote = reached["pushed"].get(hit.commit)

    for entry in scan.risky_paths:
        entry["still_tracked"] = entry["path"] in tracked_now
        # A pattern that does not actually match the file is how this happens in the first place.
        entry["ignored_by"] = git_soft(worktree, "check-ignore", "-v", "--no-index", entry["path"]).strip() or None

    print(json.dumps({
        "base": merge_base[:12],
        "head": head[:12],
        "scanned": {
            "commits": len(scan.commits),
            "files": len(scan.files),
            "added_lines": scan.added_lines,
            "skipped_generated_files": sorted(scan.skipped)[:20],
        },
        "commits": scan.commits,
        "history_reach": reached,
        "risky_paths": scan.risky_paths,
        "gitignore_rules_removed": scan.ignore_removals,
        "hits": [h.as_dict() for h in scan.hits],
        "truncated": scan.truncated,
        "note": (
            "Added lines across every commit on the branch, not the net diff: a credential committed and "
            "then deleted is still in the branch's history. `still_in_working_tree: false` means exactly "
            "that case. `commit_reached_remote` says whether that history ever left this machine: false "
            "means rewriting the branch genuinely erases the value, true means it is published and only "
            "rotation fixes it, null means the question could not be answered and it must be treated as "
            "true."
        ),
    }, indent=2))
    return 0


def _check_path(scan: Scan, path: str, commit: str) -> None:
    if ENV_ALLOWED.search(path):
        return
    for rule, pattern, why in RISKY_PATHS:
        if re.search(pattern, path, re.I):
            scan.risky_paths.append({"rule": rule, "path": path, "commit": commit[:12], "why": why})
            return


if __name__ == "__main__":
    raise SystemExit(main())
