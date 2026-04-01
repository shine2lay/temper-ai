"""Anti-pattern detection — regex-based scan for dangerous code patterns."""

import re

from scripts.code_quality_check.base import Finding, Rule, ScanContext, Severity

# Pattern definitions: (name, regex, severity, description)
PATTERNS: list[tuple[str, str, str, str]] = [
    # CRITICAL
    ("sql_injection", r"""(?:execute|cursor\.execute)\s*\(.*(?:f['\"]|\.format|%s|\+\s*\w+)""",
     Severity.CRITICAL, "Possible SQL injection (string interpolation in query)"),
    ("unsafe_yaml", r"yaml\.load\s*\([^)]*(?:^(?!.*Loader))",
     Severity.CRITICAL, "Unsafe yaml.load without SafeLoader"),
    ("eval_exec", r"(?<!\.)(?:eval|exec)\s*\(",
     Severity.CRITICAL, "Use of eval() or exec()"),

    # HIGH
    ("shell_true", r"subprocess\.\w+\(.*shell\s*=\s*True",
     Severity.HIGH, "subprocess with shell=True"),
    ("hardcoded_password", r"""(?:password|passwd|secret|api_key)\s*=\s*['\"][^'\"]{8,}['\"]""",
     Severity.HIGH, "Possible hardcoded secret"),
    ("pickle_load", r"pickle\.loads?\s*\(",
     Severity.HIGH, "Pickle deserialization (arbitrary code execution risk)"),

    # MEDIUM
    ("broad_except", r"except\s+(?:Exception|BaseException)\s*(?:as\s+\w+)?:",
     Severity.MEDIUM, "Broad exception handler"),
    ("bare_except", r"except\s*:",
     Severity.MEDIUM, "Bare except (catches SystemExit, KeyboardInterrupt)"),
    ("mutable_default", r"def\s+\w+\s*\([^)]*(?:=\s*\[\s*\]|=\s*\{\s*\})",
     Severity.MEDIUM, "Mutable default argument"),

    # LOW
    ("todo_fixme", r"#\s*(?:TODO|FIXME|HACK|XXX)\b",
     Severity.LOW, "TODO/FIXME comment"),
]

# Smart filters for broad_except false positives
_RERAISE_PATTERN = re.compile(r"^\s*raise\b")
_CLEANUP_PATTERN = re.compile(r"^\s*(?:logger\.\w+|logging\.\w+|pass\b|return\b)")


class AntiPatternsRule(Rule):
    key = "anti_patterns"
    title = "Anti-Patterns"
    severity = Severity.MEDIUM
    tags = ["security", "correctness"]

    def scan(self, ctx: ScanContext) -> list[Finding]:
        findings = []

        for file_info in ctx.files:
            source = ctx.source(file_info["abs_path"])
            if not source:
                continue

            lines = source.split("\n")
            rel_path = file_info["path"]

            for name, pattern, severity, description in PATTERNS:
                regex = re.compile(pattern, re.IGNORECASE)
                for i, line in enumerate(lines, 1):
                    stripped = line.lstrip()
                    # Skip comments and docstrings
                    if stripped.startswith("#") or stripped.startswith(('"""', "'''")):
                        continue
                    if regex.search(line):
                        # Skip suppressed lines
                        if _has_noqa(line):
                            continue

                        # Smart filter: broad_except
                        if name == "broad_except" and _is_benign_except(lines, i - 1):
                            continue

                        findings.append(Finding(
                            rule=self.key,
                            message=f"{description}: {line.strip()[:120]}",
                            file=rel_path,
                            line=i,
                            severity=severity,
                        ))

        return findings


def _has_noqa(line: str) -> bool:
    return "# noqa" in line or "# scanner: skip" in line


def _is_benign_except(lines: list[str], except_idx: int) -> bool:
    """Check if a broad except is benign (re-raises or is cleanup code)."""
    # Look at the body (lines after the except)
    for i in range(except_idx + 1, min(except_idx + 10, len(lines))):
        body_line = lines[i]
        # Hit next except/else/finally/def/class → stop
        stripped = body_line.lstrip()
        if stripped and not stripped.startswith("#") and not body_line.startswith(" " * 4):
            break
        if _RERAISE_PATTERN.match(stripped):
            return True
        if _CLEANUP_PATTERN.match(stripped):
            return True
    return False
