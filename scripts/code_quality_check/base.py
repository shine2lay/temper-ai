"""Base classes for the architecture scanner.

To add a new rule:
    1. Create a file in scripts/scanner/rules/
    2. Subclass Rule, set key/title/severity
    3. Implement scan() returning list[Finding]
    4. The runner auto-discovers it via the rules package
"""

from __future__ import annotations

import ast
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class Finding:
    """A single issue found by a rule."""

    rule: str  # Rule.key
    message: str
    file: str = ""
    line: int = 0
    severity: str = "medium"  # Severity value
    metadata: dict = field(default_factory=dict)


@dataclass
class ScanContext:
    """Shared context passed to every rule.

    Built once by the runner. Rules read from this — never mutate it.
    """

    src_dir: Path
    files: list[dict]  # [{path, abs_path, lines}]
    file_cache: dict[str, tuple[str, ast.Module | None]]  # {abs_path: (source, ast)}

    @property
    def total_lines(self) -> int:
        return sum(f["lines"] for f in self.files)

    def source(self, abs_path: str) -> str:
        """Get source text for a file."""
        entry = self.file_cache.get(abs_path)
        return entry[0] if entry else ""

    def ast_tree(self, abs_path: str) -> ast.Module | None:
        """Get parsed AST for a file."""
        entry = self.file_cache.get(abs_path)
        return entry[1] if entry else None


# ---------------------------------------------------------------------------
# Rule base class
# ---------------------------------------------------------------------------

class Rule:
    """Base class for scanner rules.

    Subclass and implement scan(). The runner calls scan() with a ScanContext
    and collects the returned Findings.

    Class attributes:
        key:      Unique identifier (e.g., "god_objects")
        title:    Human-readable name (e.g., "God Objects")
        severity: Default severity for findings from this rule
        needs_ast: Whether this rule needs the file_cache (AST + source)
        tags:     Optional tags for filtering (e.g., ["security", "structure"])
    """

    key: str = ""
    title: str = ""
    severity: str = Severity.MEDIUM
    needs_ast: bool = True
    tags: list[str] = []

    def scan(self, ctx: ScanContext) -> list[Finding]:
        """Run this rule and return findings. Override in subclasses."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<Rule:{self.key}>"


class ExternalToolRule(Rule):
    """Rule that wraps an external CLI tool (bandit, ruff, mypy, etc.).

    Subclass and implement run_tool(). The base handles:
    - Graceful fallback if the tool isn't installed
    - Timeout protection
    - Structured Finding output
    """

    tool_name: str = ""  # CLI binary name
    timeout: int = 120

    needs_ast = False

    def scan(self, ctx: ScanContext) -> list[Finding]:
        """Run the external tool and convert output to Findings."""
        import shutil
        import subprocess

        if not shutil.which(self.tool_name):
            logger.info("Tool '%s' not installed, skipping rule '%s'", self.tool_name, self.key)
            return []

        try:
            result = subprocess.run(
                self.build_command(ctx),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(ctx.src_dir.parent),
            )
            return self.parse_output(result, ctx)
        except subprocess.TimeoutExpired:
            logger.warning("Tool '%s' timed out after %ds", self.tool_name, self.timeout)
            return []
        except Exception as e:
            logger.warning("Tool '%s' failed: %s", self.tool_name, e)
            return []

    def build_command(self, ctx: ScanContext) -> list[str]:
        """Build the CLI command to run. Override in subclasses."""
        raise NotImplementedError

    def parse_output(self, result: "subprocess.CompletedProcess", ctx: ScanContext) -> list[Finding]:
        """Parse CLI output into Findings. Override in subclasses."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# File cache builder
# ---------------------------------------------------------------------------

def build_file_list(src_dir: Path) -> list[dict]:
    """Collect all .py files with line counts."""
    files = []
    for py_file in sorted(src_dir.rglob("*.py")):
        try:
            lines = py_file.read_text(encoding="utf-8").count("\n") + 1
            rel = str(py_file.relative_to(src_dir))
            files.append({"path": rel, "abs_path": str(py_file), "lines": lines})
        except (OSError, UnicodeDecodeError):
            pass
    return files


def build_file_cache(
    files: list[dict], max_workers: int = 16
) -> dict[str, tuple[str, ast.Module | None]]:
    """Read + parse all files in parallel. Returns {abs_path: (source, ast)}."""

    def _parse(abs_path: str) -> tuple[str, tuple[str, ast.Module | None]]:
        try:
            source = Path(abs_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return abs_path, ("", None)
        try:
            tree = ast.parse(source, filename=abs_path)
        except SyntaxError:
            tree = None
        return abs_path, (source, tree)

    cache: dict[str, tuple[str, ast.Module | None]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_parse, f["abs_path"]): f for f in files}
        for future in as_completed(futures):
            abs_path, entry = future.result()
            cache[abs_path] = entry

    return cache


def compute_content_hash(src_dir: Path) -> str:
    """SHA-256 hash of all source files for change detection."""
    h = hashlib.sha256()
    for py_file in sorted(src_dir.rglob("*.py")):
        try:
            h.update(py_file.read_bytes())
        except OSError:
            pass
    return h.hexdigest()
