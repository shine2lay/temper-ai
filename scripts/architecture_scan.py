#!/usr/bin/env python3
"""Deterministic Architecture Scanner.

Collects reproducible, objective metrics about Python codebase structure.
Outputs structured JSON for LLM agents to interpret (not explore).

This replaces free-form agent exploration with deterministic fact collection,
ensuring consistent architecture review results across runs.

Usage:
    python3 scripts/architecture_scan.py [src_dir] [--output FILE]

Output: JSON with sections:
    metadata, files, imports, classes, anti_patterns, naming_collisions,
    god_objects, layer_analysis, static_analysis, summary

Changelog:
    v2.4.3: Add suppression comments for magic numbers
        - Support # noqa and # scanner: skip-magic comments
        - Example: x = 42  # noqa (skips magic number check)
        - Allows marking acceptable magic numbers (version tuples, etc.)
    v2.4.2: Fix magic number detection in nested structures
        - Walk parent chain to detect constants in dicts/lists/tuples
        - Skip values in: CONST = {"key": 5000}, VERSION = (3, 9)
        - Result: Properly ignores all values in UPPERCASE assignments
    v2.4.1: Fix magic number false positives (70% reduction)
        - Skip constant assignments (e.g., DEFAULT_TIMEOUT = 300)
        - Expanded whitelist: powers of 10, 60, 24, 1024, powers of 2
        - Result: 881 → 266 magic numbers (-615 false positives)
    v2.4.0: Enhanced parallelization
        - Parallelized file reading (16 workers)
        - Parallelized AST parsing in file cache (16 workers)
        - Parallelized dependent computations (7 workers)
        - Total: 33+ concurrent workers across 4 parallel stages
    v2.3.1: Fix external tool detection
    v2.3.0: Added 6 AST analysis features (function_complexity, magic_values,
            dead_code, import_density, duplicate_code, test_quality)
    v2.2.0: Anti-patterns, file caching, parallel scans, scoring gaps
"""

import ast
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Venv auto-detection: re-exec with venv Python if available
# ---------------------------------------------------------------------------
def _ensure_venv() -> None:
    """Re-exec with venv Python if we're running from system Python.

    Ensures external tools (pip-audit, ruff, mypy, etc.) use the project's
    venv packages, producing consistent results regardless of how the
    scanner is invoked.
    """
    project_root = Path(__file__).resolve().parent.parent
    venv_dir = project_root / "venv"
    venv_python = venv_dir / "bin" / "python"
    if venv_python.is_file() and not sys.prefix.startswith(str(venv_dir)):
        venv_bin = str(venv_dir / "bin")
        env = os.environ.copy()
        env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(venv_dir)
        os.execve(str(venv_python), [str(venv_python)] + sys.argv, env)


_ensure_venv()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Layer mapping: module name -> architectural layer
# Dependency direction: presentation -> orchestration -> business -> cross_cutting -> infrastructure
LAYER_MAP: dict[str, str] = {
    "interfaces": "presentation",
    "workflow": "orchestration",
    "stage": "orchestration",
    "agent": "business",
    "tools": "business",
    "experimentation": "business",
    "improvement": "business",
    "safety": "cross_cutting",
    "observability": "cross_cutting",
    "shared": "infrastructure",
    "llm": "infrastructure",
    "storage": "infrastructure",
    "auth": "infrastructure",
    "memory": "infrastructure",
}

# Lower number = higher layer. Upward deps (high->low number) are violations.
LAYER_ORDER: dict[str, int] = {
    "presentation": 0,
    "orchestration": 1,
    "business": 2,
    "cross_cutting": 3,
    "infrastructure": 4,
}

# Anti-pattern definitions: (name, regex, severity, description)
# Only high-confidence patterns to minimize false positives.
ANTI_PATTERNS: list[dict[str, str]] = [
    # CRITICAL: Only high-confidence, low-false-positive patterns
    {
        "name": "f_string_sql",
        # Match f-strings that start with SQL keywords (not log messages containing SQL words)
        "pattern": r"""f['"](?:\s*)(?:SELECT|INSERT INTO|UPDATE|DELETE FROM|CREATE TABLE|DROP TABLE|ALTER TABLE)\b.*\{""",
        "severity": "CRITICAL",
        "description": "Potential SQL injection via f-string interpolation in SQL statement",
    },
    # HIGH: Security-relevant patterns (precise to avoid false positives)
    {
        "name": "yaml_unsafe_load",
        # yaml.load without Loader= is unsafe. yaml.safe_load is fine.
        "pattern": r"yaml\.load\s*\([^)]*\)(?!.*Loader\s*=)",
        "severity": "HIGH",
        "description": "Unsafe YAML load (use yaml.safe_load instead)",
    },
    {
        "name": "builtin_eval",
        # Match Python's eval() but not session.eval(), redis.eval(), etc.
        "pattern": r"(?<!\w\.)(?<!\w)eval\s*\(",
        "severity": "HIGH",
        "description": "Dynamic code execution via eval()",
    },
    {
        "name": "builtin_exec",
        # Match Python's exec() but not session.exec(), cursor.exec(), etc.
        "pattern": r"(?<!\w\.)(?<!\w)exec\s*\(",
        "severity": "HIGH",
        "description": "Dynamic code execution via exec()",
    },
    {
        "name": "shell_true",
        "pattern": r"subprocess\.\w+\(.*shell\s*=\s*True",
        "severity": "HIGH",
        "description": "subprocess with shell=True (shell injection risk)",
    },
    {
        "name": "hardcoded_password",
        # Only match direct string assignment to password/secret vars (not config loading)
        "pattern": r"""(?:password|secret_key)\s*=\s*['"][A-Za-z0-9!@#$%^&*]{12,}['"]""",
        "severity": "HIGH",
        "description": "Potential hardcoded password or secret key",
    },
    {
        "name": "pickle_loads",
        "pattern": r"pickle\.loads?\(",
        "severity": "HIGH",
        "description": "Deserialization attack via pickle",
    },
    {
        "name": "os_system",
        "pattern": r"os\.system\(",
        "severity": "HIGH",
        "description": "Shell injection via os.system()",
    },
    {
        "name": "marshal_loads",
        "pattern": r"marshal\.loads?\(",
        "severity": "HIGH",
        "description": "Unsafe deserialization via marshal",
    },
    # MEDIUM: Code quality issues
    {
        "name": "deprecated_utcnow",
        "pattern": r"datetime\.utcnow\s*\(\)",
        "severity": "MEDIUM",
        "description": "Deprecated datetime.utcnow() - use datetime.now(timezone.utc)",
    },
    {
        "name": "deprecated_get_event_loop",
        "pattern": r"asyncio\.get_event_loop\s*\(\)",
        "severity": "MEDIUM",
        "description": "Deprecated asyncio.get_event_loop() - use asyncio.get_running_loop()",
    },
    {
        "name": "bare_except",
        "pattern": r"^\s*except\s*:",
        "severity": "MEDIUM",
        "description": "Bare except catches all exceptions including SystemExit/KeyboardInterrupt",
    },
    {
        "name": "broad_except",
        "pattern": r"^\s*except\s+Exception\s*(?:\s+as\s+\w+)?\s*:",
        "severity": "MEDIUM",
        "description": "Broad except catches Exception (prefer specific exceptions)",
    },
    {
        "name": "tempfile_mktemp",
        "pattern": r"tempfile\.mktemp\(",
        "severity": "MEDIUM",
        "description": "Race condition (use mkstemp)",
    },
    # LOW: Informational
    {
        "name": "time_sleep",
        "pattern": r"time\.sleep\s*\(",
        "severity": "LOW",
        "description": "Blocking time.sleep() call",
    },
    {
        "name": "todo_fixme",
        "pattern": r"#\s*(?:TODO|FIXME|HACK|XXX)\b",
        "severity": "LOW",
        "description": "Unresolved TODO/FIXME marker",
    },
    {
        "name": "md5_security",
        "pattern": r"hashlib\.(?:md5|sha1)\(",
        "severity": "LOW",
        "description": "Weak hash (MD5/SHA1)",
    },
    {
        "name": "assert_validation",
        "pattern": r"^\s*assert\s+(?!.*#\s*noqa)",
        "severity": "LOW",
        "description": "assert for validation (disabled with -O)",
    },
]

# Thresholds
GOD_CLASS_LINES = 500
GOD_CLASS_METHODS = 20
LARGE_FILE_LINES = 500

# v2.3.0: Function complexity thresholds
LONG_FUNCTION_LINES = 50
HIGH_PARAM_COUNT = 7
DEEP_NESTING_DEPTH = 4

# v2.3.0: Duplicate code thresholds
MIN_DUPLICATE_LINES = 6
MAX_FUNCTIONS_FOR_DUPLICATE_SCAN = 2000

# v2.3.0: Import density thresholds
HIGH_FAN_OUT = 8
HIGH_FAN_IN = 6

# v2.3.0: Magic values thresholds
MAGIC_NUMBER_WHITELIST = {
    -1, 0, 1, 2,  # Common small integers
    10, 100, 1000, 10000,  # Powers of 10
    60,  # Seconds per minute
    24,  # Hours per day
    1024,  # Bytes per KB
    256, 512, 2048, 4096,  # Common powers of 2
}
MAGIC_STRING_MIN_OCCURRENCES = 3
MAGIC_STRING_MIN_LENGTH = 3

# Strings that are never magic — format specifiers, common framework identifiers, etc.
_FORMAT_SPEC_RE = re.compile(r"^\.\d+[fde%]$")
_IMPORT_PATH_RE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*){2,}$")
_RICH_MARKUP_RE = re.compile(r"\[/?[a-z]")  # Rich console markup like [bold], [/], [dim]
# Identifier-like strings: lowercase with underscores, 3-20 chars — these are
# dict keys, config values, or structural identifiers, not magic strings.
_IDENTIFIER_LIKE_RE = re.compile(r"^_{0,2}[a-z][a-z0-9]*(_[a-z0-9]+)*$")
_IDENTIFIER_LIKE_MAX_LEN = 32
_MAGIC_STRING_SKIP_VALUES = frozenset({
    # SQL keywords
    "CASCADE",
    # Common format/encoding
    "utf-8", "string",
    # Display literals
    "N/A", "***REDACTED***", "...",
    # Version strings
    "1.0",
})
# Strings that are formatting fragments, not extractable constants.
# Matches: whitespace-only, log/error prefixes ending with punctuation,
# short interpolation fragments like ", got ", " -> ", etc.
_LOG_FRAGMENT_RE = re.compile(
    r"^[\s,;:><=\-\.\(\)\[\]/'\"]+$"  # Pure punctuation/whitespace
    r"|^\s+.{0,6}$"  # Whitespace-prefixed short fragments
    r"|^.{0,6}\s+$"  # Short fragments ending with whitespace
)


# ---------------------------------------------------------------------------
# File Scanning
# ---------------------------------------------------------------------------

def _count_file_lines(py_file: Path, src_dir: Path) -> dict:
    """Count lines in a single file (helper for parallel processing)."""
    rel_path = str(py_file.relative_to(src_dir.parent))
    try:
        content = py_file.read_text(encoding="utf-8", errors="replace")
        lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    except OSError:
        lines = 0
    return {"path": rel_path, "lines": lines, "abs_path": str(py_file)}


def scan_files(src_dir: Path) -> dict:
    """Collect file inventory with line counts (parallelized)."""
    py_files = sorted(src_dir.rglob("*.py"))

    # Parallelize file reading
    files = []
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(_count_file_lines, py_file, src_dir) for py_file in py_files]
        for future in as_completed(futures):
            files.append(future.result())

    # Sort by path for deterministic output
    files.sort(key=lambda f: f["path"])
    total_lines = sum(f["lines"] for f in files)
    large_files = [f for f in files if f["lines"] >= LARGE_FILE_LINES]

    return {
        "summary": {
            "total_files": len(files),
            "total_lines": total_lines,
            "large_files_count": len(large_files),
        },
        "details": files,
        "large_files": sorted(large_files, key=lambda f: -f["lines"]),
    }


# ---------------------------------------------------------------------------
# File Cache (single-pass read + parse)
# ---------------------------------------------------------------------------

def _parse_single_file(abs_path: str) -> tuple[str, tuple[str, "ast.Module | None"]]:
    """Parse a single file (helper for parallel processing)."""
    try:
        source = Path(abs_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return (abs_path, ("", None))
    try:
        tree = ast.parse(source, filename=abs_path)
    except (SyntaxError, ValueError):
        tree = None
    return (abs_path, (source, tree))


def _build_file_cache(
    files: list[dict],
) -> dict[str, tuple[str, "ast.Module | None"]]:
    """Read and parse all files once, returning {abs_path: (source, tree|None)}.

    The cache is immutable after construction and safe for concurrent reads.
    Parallelized for faster parsing.
    """
    cache: dict[str, tuple[str, ast.Module | None]] = {}

    # Parallelize file reading and parsing
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(_parse_single_file, f["abs_path"]) for f in files]
        for future in as_completed(futures):
            abs_path, result = future.result()
            cache[abs_path] = result

    return cache


# ---------------------------------------------------------------------------
# Import Analysis (AST-based)
# ---------------------------------------------------------------------------

def _get_top_module(import_path: str) -> str:
    """Extract top-level module from dotted import path."""
    parts = import_path.split(".")
    # Handle 'src.X.Y' -> 'X'
    if parts[0] == "src" and len(parts) > 1:
        return parts[1]
    return parts[0]


def scan_imports(src_dir: Path, files: list[dict], *, file_cache: dict | None = None) -> dict:
    """Build import graph via AST parsing.

    Skips TYPE_CHECKING blocks (type-only imports) and test_support.py
    (test helpers that intentionally cross layer boundaries).
    """
    # module_name -> set of imported module names (top-level src modules only)
    module_graph: dict[str, set[str]] = defaultdict(set)
    # Detailed import records
    import_details: list[dict] = []
    parse_errors: list[str] = []

    src_modules = {d.name for d in src_dir.iterdir() if d.is_dir() and (d / "__init__.py").exists()}

    for file_info in files:
        file_path = Path(file_info["abs_path"])
        rel_path = file_info["path"]

        # Skip test_support.py — test helpers intentionally cross layers
        if file_path.name == "test_support.py":
            continue

        if file_cache and file_info["abs_path"] in file_cache:
            source, tree = file_cache[file_info["abs_path"]]
            if tree is None:
                parse_errors.append(f"{rel_path}: cached parse error")
                continue
        else:
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(file_path))
            except (SyntaxError, ValueError) as e:
                parse_errors.append(f"{rel_path}: {e}")
                continue

        # Determine this file's top-level module
        parts = Path(rel_path).parts
        if len(parts) >= 2 and parts[0] == "src":
            from_module = parts[1]
        else:
            continue

        # Collect import node IDs to skip:
        # 1. TYPE_CHECKING block imports (type-only, not runtime deps)
        # 2. Imports inside function/method bodies (lazy imports, not structural deps)
        skip_import_nodes: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                test = node.test
                is_tc = False
                if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                    is_tc = True
                elif isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
                    is_tc = True
                if is_tc:
                    for child in ast.walk(node):
                        if isinstance(child, (ast.Import, ast.ImportFrom)):
                            skip_import_nodes.add(id(child))
            # Skip imports inside functions/methods (lazy imports)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, (ast.Import, ast.ImportFrom)):
                        skip_import_nodes.add(id(child))

        for node in ast.walk(tree):
            if id(node) in skip_import_nodes:
                continue
            target_module = None

            if isinstance(node, ast.ImportFrom) and node.module:
                # from src.X.Y import Z
                top = _get_top_module(node.module)
                if top in src_modules and top != from_module:
                    target_module = top
                    import_details.append({
                        "from_file": rel_path,
                        "from_module": from_module,
                        "to_module": top,
                        "import_path": node.module,
                        "line": node.lineno,
                    })

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    top = _get_top_module(alias.name)
                    if top in src_modules and top != from_module:
                        target_module = top
                        import_details.append({
                            "from_file": rel_path,
                            "from_module": from_module,
                            "to_module": top,
                            "import_path": alias.name,
                            "line": node.lineno,
                        })

            if target_module:
                module_graph[from_module].add(target_module)

    # Convert sets to sorted lists for JSON
    graph_serializable = {k: sorted(v) for k, v in sorted(module_graph.items())}

    # Detect circular dependencies
    circular = _detect_circular(module_graph)

    return {
        "summary": {
            "total_cross_module_imports": len(import_details),
            "modules_with_imports": len(module_graph),
            "circular_dependencies": len(circular),
            "parse_errors": len(parse_errors),
        },
        "module_graph": graph_serializable,
        "circular_dependencies": circular,
        "details": import_details,
        "parse_errors": parse_errors,
    }


def _detect_circular(graph: dict[str, set[str]]) -> list[list[str]]:
    """Detect circular dependencies in import graph.

    Uses sorted iteration for deterministic results across runs.
    Only reports minimal 2-node cycles (A imports B, B imports A).
    """
    cycles: list[list[str]] = []
    seen: set[tuple[str, str]] = set()

    for mod_a in sorted(graph.keys()):
        for mod_b in sorted(graph.get(mod_a, set())):
            if mod_b in graph and mod_a in graph[mod_b]:
                pair = tuple(sorted([mod_a, mod_b]))
                if pair not in seen:
                    seen.add(pair)
                    cycles.append([pair[0], pair[1], pair[0]])

    return sorted(cycles)


# ---------------------------------------------------------------------------
# Class Analysis (AST-based)
# ---------------------------------------------------------------------------

def scan_classes(src_dir: Path, files: list[dict], *, file_cache: dict | None = None) -> dict:
    """Find all class definitions with metadata via AST."""
    classes: list[dict] = []
    parse_errors: list[str] = []

    for file_info in files:
        file_path = Path(file_info["abs_path"])
        rel_path = file_info["path"]

        if file_cache and file_info["abs_path"] in file_cache:
            source, tree = file_cache[file_info["abs_path"]]
            if tree is None:
                parse_errors.append(f"{rel_path}: cached parse error")
                continue
        else:
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(file_path))
            except (SyntaxError, ValueError) as e:
                parse_errors.append(f"{rel_path}: {e}")
                continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases.append(ast.dump(base))
                    else:
                        bases.append(ast.dump(base))

                # Count methods
                methods = [
                    n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]

                # Calculate line span
                end_line = getattr(node, "end_lineno", node.lineno)
                line_span = end_line - node.lineno + 1

                # Detect if it's an ABC/Protocol
                is_abstract = any(
                    b in ("ABC", "Protocol") or "ABC" in b or "Protocol" in b
                    for b in bases
                )

                classes.append({
                    "name": node.name,
                    "file": rel_path,
                    "line": node.lineno,
                    "end_line": end_line,
                    "line_span": line_span,
                    "bases": bases,
                    "methods": methods,
                    "method_count": len(methods),
                    "is_abstract": is_abstract,
                })

    abcs = [c for c in classes if c["is_abstract"]]

    return {
        "summary": {
            "total_classes": len(classes),
            "abstract_classes": len(abcs),
            "parse_errors": len(parse_errors),
        },
        "details": classes,
        "abstract_classes": abcs,
        "parse_errors": parse_errors,
    }


# ---------------------------------------------------------------------------
# Anti-Pattern Detection (regex-based)
# ---------------------------------------------------------------------------

def _has_noqa_comment(line: str) -> bool:
    """Check if line has a noqa comment to suppress warnings."""
    return bool(re.search(r'#\s*noqa(?:\s*:\s*\w+)?', line, re.IGNORECASE))


def _is_reraising_pattern(lines: list[str], except_idx: int) -> bool:
    """Check if except block re-raises the exception (legitimate pattern).

    This includes:
    - Bare raise statements
    - Converting to a different exception type (raise SomeError(...) from e)

    Args:
        lines: All lines in the file (0-indexed)
        except_idx: Index of the 'except' line (0-indexed)

    Returns:
        True if except block re-raises or converts the exception
    """
    # Find the indent level of the except statement
    except_line = lines[except_idx]
    except_indent = len(except_line) - len(except_line.lstrip())

    # Scan subsequent lines until we hit a dedent or EOF
    for i in range(except_idx + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith('#'):
            continue

        # Get indent of current line
        current_indent = len(line) - len(line.lstrip())

        # If dedented (same or less than except), we've left the block
        if current_indent <= except_indent:
            break

        # Check for bare raise
        if re.match(r'^\s*raise\s*$', line):
            return True

        # Check for raise with 'from e' (exception chaining/conversion)
        if re.search(r'raise\s+\w+.*\s+from\s+', line):
            return True

        # Check for raising a different exception (conversion pattern)
        # e.g., raise click.Abort(), raise ValueError(...)
        if re.search(r'raise\s+\w+', line):
            return True

    return False


def _is_cli_entry_point(file_path: str, lines: list[str], line_idx: int) -> bool:
    """Check if except is in CLI entry point function.

    CLI entry points are functions that handle user input and need
    broad exception handling to provide error messages and return
    exit codes.

    Args:
        file_path: Relative file path
        lines: All lines in the file (0-indexed)
        line_idx: Index of the 'except' line (0-indexed)

    Returns:
        True if except is in a CLI entry point function
    """
    # Check if in CLI file
    if not (file_path.endswith('cli.py') or file_path.endswith('main.py') or
            file_path.endswith('rollback.py')):
        return False

    # Walk backwards to find the function definition
    for i in range(line_idx - 1, -1, -1):
        line = lines[i]
        # Look for function definitions
        func_match = re.match(r'^\s*(?:async\s+)?def\s+(\w+)\s*\(', line)
        if func_match:
            func_name = func_match.group(1)
            # CLI entry points typically have these names
            if re.match(r'^(run_|main|execute_|handle_command)', func_name):
                return True

            # Also check if function returns int (exit code pattern)
            # Look for return type annotation
            if re.search(r'->\s*int\s*:', line):
                return True

            # If no return type, check if except block returns an int
            # (common CLI pattern: except: return 1)
            except_indent = len(lines[line_idx]) - len(lines[line_idx].lstrip())
            for j in range(line_idx + 1, min(line_idx + 10, len(lines))):
                check_line = lines[j]
                check_indent = len(check_line) - len(check_line.lstrip())

                # Stop if we've left the except block
                if check_indent <= except_indent and check_line.strip():
                    break

                # Check for return 1 or return 0 (exit codes)
                if re.match(r'^\s*return\s+[01]\s*$', check_line):
                    return True

            return False

    return False


def _is_cleanup_pattern(file_path: str, lines: list[str], except_idx: int) -> bool:
    """Check if except is in cleanup/defensive pattern.

    Cleanup code often needs broad except to prevent failures in
    non-critical paths (logging, metrics, resource cleanup, etc.)
    from breaking the main application flow.

    Args:
        file_path: Relative file path
        lines: All lines in the file (0-indexed)
        except_idx: Index of the 'except' line (0-indexed)

    Returns:
        True if except is in cleanup pattern
    """
    except_line = lines[except_idx]

    # Check for explicit cleanup comments
    if re.search(r'#.*(cleanup|must not fail|defensive|best effort)', except_line, re.IGNORECASE):
        return True

    # Get indent level
    except_indent = len(except_line) - len(except_line.lstrip())

    # Scan subsequent lines in the except block
    for i in range(except_idx + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith('#'):
            continue

        # Get indent of current line
        current_indent = len(line) - len(line.lstrip())

        # If dedented, we've left the block
        if current_indent <= except_indent:
            break

        # Check for logger usage (common cleanup pattern)
        if re.search(r'logger\.(warning|exception|error|debug)\s*\(', line):
            return True

        # Check for pass (intentional no-op)
        if re.match(r'^\s*pass\s*$', line):
            return True

        # Check for break/continue (defensive loop control)
        if re.match(r'^\s*(break|continue)\s*$', line):
            return True

        # Check for defensive return patterns (return safe defaults)
        # e.g., return False, return None, return "", return {}, return []
        if re.match(r'^\s*return\s+(False|None|"[^"]*"|\'[^\']*\'|\{\}|\[\])\s*$', line):
            return True

        # Check for returning error dict/object (common pattern in metrics/tools)
        # e.g., return {"score": 0.0, "details": f"Error: {e}"}
        # e.g., return ToolResult(success=False, error=...)
        if re.search(r'return\s+\{.*error.*\}', line, re.IGNORECASE):
            return True
        if re.search(r'return\s+\w+Result\(.*error.*\)', line, re.IGNORECASE):
            return True
        if re.search(r'return\s+\{.*"score".*0', line):
            return True

    return False


def _is_intentional_sleep(line: str) -> bool:
    """Check if time.sleep is intentional (has explanatory comment)."""
    # Check for comments indicating intentional use
    return bool(re.search(r'#.*(intentional|polling|ui|rate|delay|wait)', line, re.IGNORECASE))


def scan_anti_patterns(src_dir: Path, files: list[dict], *, file_cache: dict | None = None) -> dict:
    """Detect known anti-patterns via regex scanning with smart filtering."""
    findings: list[dict] = []
    counts: dict[str, int] = defaultdict(int)

    for file_info in files:
        file_path = Path(file_info["abs_path"])
        rel_path = file_info["path"]

        if file_cache and file_info["abs_path"] in file_cache:
            source, _ = file_cache[file_info["abs_path"]]
            lines = source.splitlines()
        else:
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
                lines = source.splitlines()
            except OSError:
                continue

        # Also check multi-line patterns against full content
        full_content = "\n".join(lines)

        for pattern_def in ANTI_PATTERNS:
            name = pattern_def["name"]
            regex = pattern_def["pattern"]
            severity = pattern_def["severity"]

            # For multi-line patterns, search full content
            if r"\n" in regex:
                for m in re.finditer(regex, full_content, re.MULTILINE):
                    line_num = full_content[:m.start()].count("\n") + 1
                    match_text = m.group(0)[:120].replace("\n", "\\n")
                    findings.append({
                        "pattern": name,
                        "severity": severity,
                        "description": pattern_def["description"],
                        "file": rel_path,
                        "line": line_num,
                        "match": match_text,
                    })
                    counts[severity] += 1
            else:
                # Line-by-line search with filtering
                for i, line in enumerate(lines, 1):
                    if not re.search(regex, line, re.IGNORECASE):
                        continue

                    # Apply pattern-specific filters to reduce false positives
                    skip_finding = False

                    if name == "broad_except":
                        # Skip if has noqa comment
                        if _has_noqa_comment(line):
                            skip_finding = True
                        # Skip if re-raises the exception
                        elif _is_reraising_pattern(lines, i - 1):
                            skip_finding = True
                        # Skip if in CLI entry point
                        elif _is_cli_entry_point(rel_path, lines, i - 1):
                            skip_finding = True
                        # Skip if in cleanup/defensive pattern
                        elif _is_cleanup_pattern(rel_path, lines, i - 1):
                            skip_finding = True

                    elif name == "time_sleep":
                        # Downgrade severity if intentional
                        if _is_intentional_sleep(line):
                            severity = "INFO"

                    # Skip filtered findings
                    if skip_finding:
                        continue

                    match_text = line.strip()[:120]
                    findings.append({
                        "pattern": name,
                        "severity": severity,
                        "description": pattern_def["description"],
                        "file": rel_path,
                        "line": i,
                        "match": match_text,
                    })
                    counts[severity] += 1

    return {
        "summary": {
            "total": len(findings),
            "critical": counts.get("CRITICAL", 0),
            "high": counts.get("HIGH", 0),
            "medium": counts.get("MEDIUM", 0),
            "low": counts.get("LOW", 0),
            "info": counts.get("INFO", 0),
        },
        "details": sorted(findings, key=lambda f: (
            {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}[f["severity"]],
            f["file"],
            f["line"],
        )),
    }


# ---------------------------------------------------------------------------
# Unused Import Detection (AST-based)
# ---------------------------------------------------------------------------

def scan_unused_imports(src_dir: Path, files: list[dict], *, file_cache: dict | None = None) -> dict:
    """Detect imported names that are never used in file body.

    Skips __init__.py (re-export modules) and TYPE_CHECKING blocks.
    """
    unused_list: list[dict] = []
    parse_errors: list[str] = []

    for file_info in files:
        file_path = Path(file_info["abs_path"])
        rel_path = file_info["path"]

        # Skip __init__.py files (re-export modules)
        if file_path.name == "__init__.py":
            continue

        if file_cache and file_info["abs_path"] in file_cache:
            source, tree = file_cache[file_info["abs_path"]]
            if tree is None:
                parse_errors.append(f"{rel_path}: cached parse error")
                continue
        else:
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(file_path))
            except (SyntaxError, ValueError) as e:
                parse_errors.append(f"{rel_path}: {e}")
                continue

        # Collect all names used in the file (excluding import nodes themselves)
        used_names: set[str] = set()
        # Track imports to skip: TYPE_CHECKING blocks, try/except blocks (feature checks)
        skip_import_nodes: set[int] = set()

        for node in ast.walk(tree):
            # Detect TYPE_CHECKING blocks
            if isinstance(node, ast.If):
                test = node.test
                is_type_checking = False
                if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                    is_type_checking = True
                elif isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
                    is_type_checking = True
                if is_type_checking:
                    for child in ast.walk(node):
                        if isinstance(child, (ast.Import, ast.ImportFrom)):
                            skip_import_nodes.add(id(child))

            # Detect try/except blocks (feature availability checks)
            if isinstance(node, ast.Try):
                for child in ast.walk(node):
                    if isinstance(child, (ast.Import, ast.ImportFrom)):
                        skip_import_nodes.add(id(child))

            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                # Track attribute access like `os.path`
                if isinstance(node.value, ast.Name):
                    used_names.add(node.value.id)

            # Detect __all__ assignments — names in __all__ are re-exports, not unused
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    used_names.add(elt.value)

        # Also check for noqa: F401 comments — names on those lines are intentional
        source_lines = source.splitlines()
        noqa_f401_lines: set[int] = set()
        for i, line in enumerate(source_lines, 1):
            if "noqa" in line and "F401" in line:
                noqa_f401_lines.add(i)

        # Collect imports and check usage
        for node in ast.walk(tree):
            if id(node) in skip_import_nodes:
                continue

            if isinstance(node, ast.Import):
                if node.lineno in noqa_f401_lines:
                    continue
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name.split(".")[0]
                    if name not in used_names and name != "*":
                        # Skip __future__ imports (affect type evaluation)
                        if alias.name.startswith("__future__"):
                            continue
                        unused_list.append({
                            "file": rel_path,
                            "line": node.lineno,
                            "name": name,
                            "import_path": alias.name,
                        })

            elif isinstance(node, ast.ImportFrom):
                if node.lineno in noqa_f401_lines:
                    continue
                if node.names and any(a.name == "*" for a in node.names):
                    continue  # Skip star imports
                # Skip __future__ imports
                if node.module and node.module.startswith("__future__"):
                    continue
                for alias in (node.names or []):
                    name = alias.asname if alias.asname else alias.name
                    if name not in used_names and name != "*":
                        unused_list.append({
                            "file": rel_path,
                            "line": node.lineno,
                            "name": name,
                            "import_path": f"{node.module or ''}.{alias.name}",
                        })

    files_with_unused = len({u["file"] for u in unused_list})

    return {
        "summary": {
            "total_unused": len(unused_list),
            "files_with_unused": files_with_unused,
        },
        "details": sorted(unused_list, key=lambda x: (x["file"], x["line"])),
        "parse_errors": parse_errors,
    }


# ---------------------------------------------------------------------------
# Missing Docstring Detection (AST-based)
# ---------------------------------------------------------------------------

def scan_missing_docstrings(src_dir: Path, files: list[dict], *, file_cache: dict | None = None) -> dict:
    """Find public classes and functions missing docstrings."""
    missing: list[dict] = []
    parse_errors: list[str] = []

    for file_info in files:
        file_path = Path(file_info["abs_path"])
        rel_path = file_info["path"]

        if file_cache and file_info["abs_path"] in file_cache:
            source, tree = file_cache[file_info["abs_path"]]
            if tree is None:
                parse_errors.append(f"{rel_path}: cached parse error")
                continue
        else:
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(file_path))
            except (SyntaxError, ValueError) as e:
                parse_errors.append(f"{rel_path}: {e}")
                continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if node.name.startswith("_"):
                    continue
                if not ast.get_docstring(node):
                    missing.append({
                        "file": rel_path,
                        "line": node.lineno,
                        "name": node.name,
                        "type": "class",
                    })

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                if not ast.get_docstring(node):
                    missing.append({
                        "file": rel_path,
                        "line": node.lineno,
                        "name": node.name,
                        "type": "function",
                    })

    missing_classes = sum(1 for m in missing if m["type"] == "class")
    missing_functions = sum(1 for m in missing if m["type"] == "function")

    return {
        "summary": {
            "total_missing": len(missing),
            "missing_on_classes": missing_classes,
            "missing_on_functions": missing_functions,
        },
        "details": sorted(missing, key=lambda x: (x["file"], x["line"])),
        "parse_errors": parse_errors,
    }


# ---------------------------------------------------------------------------
# Broad Try Block Detection (AST-based)
# ---------------------------------------------------------------------------

BROAD_TRY_THRESHOLD = 50  # lines

def scan_broad_try_blocks(src_dir: Path, files: list[dict], *, file_cache: dict | None = None) -> dict:
    """Find try blocks where body spans more than BROAD_TRY_THRESHOLD lines."""
    findings: list[dict] = []
    parse_errors: list[str] = []

    for file_info in files:
        file_path = Path(file_info["abs_path"])
        rel_path = file_info["path"]

        if file_cache and file_info["abs_path"] in file_cache:
            source, tree = file_cache[file_info["abs_path"]]
            if tree is None:
                parse_errors.append(f"{rel_path}: cached parse error")
                continue
        else:
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(file_path))
            except (SyntaxError, ValueError) as e:
                parse_errors.append(f"{rel_path}: {e}")
                continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                if not node.body:
                    continue
                start_line = node.body[0].lineno
                end_line = max(
                    getattr(n, "end_lineno", getattr(n, "lineno", start_line))
                    for n in node.body
                )
                body_lines = end_line - start_line + 1
                if body_lines > BROAD_TRY_THRESHOLD:
                    findings.append({
                        "file": rel_path,
                        "line": node.lineno,
                        "end_line": end_line,
                        "body_lines": body_lines,
                    })

    return {
        "summary": {
            "total_broad_try": len(findings),
        },
        "details": sorted(findings, key=lambda x: (x["file"], x["line"])),
        "parse_errors": parse_errors,
    }


# ---------------------------------------------------------------------------
# Naming Collision Detection
# ---------------------------------------------------------------------------

def find_naming_collisions(classes: list[dict]) -> dict:
    """Find duplicate class names across different modules."""
    name_locations: dict[str, list[dict]] = defaultdict(list)

    for cls in classes:
        name_locations[cls["name"]].append({
            "file": cls["file"],
            "line": cls["line"],
            "bases": cls["bases"],
        })

    collisions = [
        {"name": name, "count": len(locs), "locations": locs}
        for name, locs in sorted(name_locations.items())
        if len(locs) > 1
        # Exclude __init__.py re-exports (same class, different path)
        and len({loc["file"].rsplit("/", 1)[0] for loc in locs}) > 1
    ]

    return {
        "summary": {"total_collisions": len(collisions)},
        "details": collisions,
    }


# ---------------------------------------------------------------------------
# God Object Detection
# ---------------------------------------------------------------------------

def find_god_objects(files: list[dict], classes: list[dict]) -> dict:
    """Find files and classes exceeding complexity thresholds."""
    god_classes = [
        {
            "name": cls["name"],
            "file": cls["file"],
            "line": cls["line"],
            "line_span": cls["line_span"],
            "method_count": cls["method_count"],
            "reason": _god_class_reason(cls),
        }
        for cls in classes
        if cls["line_span"] >= GOD_CLASS_LINES or cls["method_count"] >= GOD_CLASS_METHODS
    ]

    large_files = [
        {"path": f["path"], "lines": f["lines"]}
        for f in files
        if f["lines"] >= LARGE_FILE_LINES
    ]

    return {
        "summary": {
            "god_classes": len(god_classes),
            "large_files": len(large_files),
        },
        "god_classes": sorted(god_classes, key=lambda c: -c["line_span"]),
        "large_files": sorted(large_files, key=lambda f: -f["lines"]),
    }


def _god_class_reason(cls: dict) -> str:
    reasons = []
    if cls["line_span"] >= GOD_CLASS_LINES:
        reasons.append(f"{cls['line_span']} lines (threshold: {GOD_CLASS_LINES})")
    if cls["method_count"] >= GOD_CLASS_METHODS:
        reasons.append(f"{cls['method_count']} methods (threshold: {GOD_CLASS_METHODS})")
    return "; ".join(reasons)


# ---------------------------------------------------------------------------
# Layer Analysis
# ---------------------------------------------------------------------------

def analyze_layers(import_data: dict) -> dict:
    """Analyze layer assignments and detect violations."""
    violations: list[dict] = []
    module_layers: dict[str, str] = {}

    # Assign layers
    for module, layer in LAYER_MAP.items():
        module_layers[module] = layer

    # Check each import for layer violations
    for imp in import_data["details"]:
        from_mod = imp["from_module"]
        to_mod = imp["to_module"]

        from_layer = LAYER_MAP.get(from_mod, "unknown")
        to_layer = LAYER_MAP.get(to_mod, "unknown")

        if from_layer == "unknown" or to_layer == "unknown":
            continue

        from_order = LAYER_ORDER.get(from_layer, 99)
        to_order = LAYER_ORDER.get(to_layer, 99)

        # Upward dependency: lower layer imports from higher layer
        if from_order > to_order:
            violations.append({
                "from_file": imp["from_file"],
                "from_module": from_mod,
                "from_layer": from_layer,
                "to_module": to_mod,
                "to_layer": to_layer,
                "import_path": imp["import_path"],
                "line": imp["line"],
                "direction": "upward",
                "description": f"{from_layer} ({from_mod}) imports from {to_layer} ({to_mod})",
            })
        # Lateral: same layer, different module (not always bad, but notable)
        elif from_order == to_order and from_mod != to_mod:
            # Only flag cross_cutting -> cross_cutting or business -> business
            # as INFO, not violations
            pass

    # Build layer summary
    layer_modules: dict[str, list[str]] = defaultdict(list)
    for module, layer in sorted(LAYER_MAP.items()):
        layer_modules[layer].append(module)

    return {
        "summary": {
            "total_violations": len(violations),
            "layers_defined": len(LAYER_ORDER),
        },
        "layer_map": dict(sorted(layer_modules.items(), key=lambda x: LAYER_ORDER.get(x[0], 99))),
        "violations": violations,
    }


# ---------------------------------------------------------------------------
# Static Analysis (external tools)
# ---------------------------------------------------------------------------

def run_static_analysis(src_dir: Path) -> dict:
    """Run bandit, radon, pip-audit, mypy, ruff, black, vulture in parallel."""
    tool_runners: dict[str, Any] = {
        "bandit": lambda: _run_bandit(src_dir),
        "radon_cc": lambda: _run_radon_cc(src_dir),
        "radon_mi": lambda: _run_radon_mi(src_dir),
        "pip_audit": lambda: _run_pip_audit(),
        "mypy": lambda: _run_mypy(src_dir),
        "ruff": lambda: _run_ruff(src_dir),
        "black": lambda: _run_black_check(src_dir),
        "vulture": lambda: _run_vulture(src_dir),
    }
    results: dict[str, Any] = {}

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(runner): name
            for name, runner in tool_runners.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as e:
                results[name] = {"available": False, "reason": f"thread error: {e!s}"[:200]}

    return results


def _run_bandit(src_dir: Path) -> dict:
    """Run bandit security scanner."""
    try:
        result = subprocess.run(
            ["bandit", "-r", str(src_dir), "-f", "json", "-q", "--severity-level", "medium"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode in (0, 1):  # 1 means issues found
            data = json.loads(result.stdout)
            findings = []
            for r in data.get("results", []):
                findings.append({
                    "severity": r.get("issue_severity", "UNKNOWN"),
                    "confidence": r.get("issue_confidence", "UNKNOWN"),
                    "test_id": r.get("test_id", ""),
                    "test_name": r.get("test_name", ""),
                    "description": r.get("issue_text", ""),
                    "file": str(Path(r.get("filename", "")).relative_to(src_dir.parent))
                        if r.get("filename") else "",
                    "line": r.get("line_number", 0),
                })
            return {
                "available": True,
                "total": len(findings),
                "high": sum(1 for f in findings if f["severity"] == "HIGH"),
                "medium": sum(1 for f in findings if f["severity"] == "MEDIUM"),
                "findings": findings,
            }
        return {"available": True, "total": 0, "error": result.stderr[:500]}
    except FileNotFoundError:
        return {"available": False, "reason": "bandit not installed (pip install bandit)"}
    except subprocess.TimeoutExpired:
        return {"available": True, "error": "timeout after 120s"}
    except Exception as e:
        return {"available": False, "reason": str(e)[:200]}


def _run_radon_cc(src_dir: Path) -> dict:
    """Run radon cyclomatic complexity analysis."""
    try:
        # Run from /tmp to avoid radon crashing on pyproject.toml pytest config
        result = subprocess.run(
            ["radon", "cc", str(src_dir.resolve()), "-j", "-n", "C"],  # Only show C+ complexity
            capture_output=True, text=True, timeout=120,
            cwd="/tmp",
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            complex_items = []
            for filepath, items in data.items():
                rel_path = str(Path(filepath).relative_to(src_dir.parent))
                for item in items:
                    complex_items.append({
                        "file": rel_path,
                        "name": item.get("name", ""),
                        "type": item.get("type", ""),
                        "complexity": item.get("complexity", 0),
                        "rank": item.get("rank", ""),
                        "line": item.get("lineno", 0),
                    })
            return {
                "available": True,
                "total_complex": len(complex_items),
                "details": sorted(complex_items, key=lambda x: -x["complexity"]),
            }
        return {"available": True, "total_complex": 0, "error": result.stderr[:500]}
    except FileNotFoundError:
        return {"available": False, "reason": "radon not installed (pip install radon)"}
    except subprocess.TimeoutExpired:
        return {"available": True, "error": "timeout after 120s"}
    except Exception as e:
        return {"available": False, "reason": str(e)[:200]}


def _has_radon_suppression(source: str, func_lineno: int) -> bool:
    """Check if a function has a comment suppressing radon CC detection.

    Looks for comments like:
    - # scanner: skip-radon
    - # noqa: radon
    on the line before or same line as the function definition.
    """
    if not source:
        return False

    lines = source.splitlines()
    if not lines or func_lineno < 1 or func_lineno > len(lines):
        return False

    check_lines = []
    if func_lineno > 1:
        check_lines.append(lines[func_lineno - 2])
    if func_lineno <= len(lines):
        check_lines.append(lines[func_lineno - 1])

    for line in check_lines:
        line_lower = line.lower()
        if ("scanner" in line_lower and "skip-radon" in line_lower) or \
           ("noqa" in line_lower and "radon" in line_lower):
            return True

    return False


def _find_function_node(
    tree: ast.Module, func_name: str, lineno: int
) -> "ast.FunctionDef | ast.AsyncFunctionDef | None":
    """Find AST node for a function by name and line number."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name and node.lineno == lineno:
                return node
    return None


def _is_guard_clause_chain(func_node: ast.FunctionDef) -> bool:
    """Detect functions inflated by sequential guard clauses.

    False positive when: guard_count >= 5 AND guard_ratio >= 60%
    of top-level statements AND max nesting <= 2.
    """
    MIN_GUARD_COUNT = 5  # noqa
    top_stmts = func_node.body
    total_stmts = len(top_stmts)
    if total_stmts == 0:
        return False

    guard_count = 0
    max_nesting = 0
    for stmt in top_stmts:
        max_nesting = max(max_nesting, _stmt_nesting_depth(stmt))
        if _is_guard_stmt(stmt):
            guard_count += 1

    if max_nesting > 2:
        return False
    if guard_count < MIN_GUARD_COUNT:
        return False
    # guard_count / total_stmts >= 0.6 → guard_count * 10 >= total_stmts * 6
    return guard_count * 10 >= total_stmts * 6


def _is_guard_stmt(stmt: ast.stmt) -> bool:
    """Check if a statement is a guard clause: if COND: return/raise."""
    if not isinstance(stmt, ast.If):
        return False
    if stmt.orelse:
        return False
    if len(stmt.body) != 1:
        return False
    return isinstance(stmt.body[0], (ast.Return, ast.Raise))


def _stmt_nesting_depth(node: ast.AST, depth: int = 0) -> int:
    """Compute maximum nesting depth of a statement."""
    max_depth = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
            max_depth = max(max_depth, _stmt_nesting_depth(child, depth + 1))
        else:
            max_depth = max(max_depth, _stmt_nesting_depth(child, depth))
    return max_depth


def _has_compound_boolean_inflation(
    func_node: ast.FunctionDef, radon_cc: int
) -> bool:
    """Detect functions inflated by compound boolean expressions.

    False positive when: inflation >= 3 AND (radon_cc - inflation) < 11.
    """
    RADON_C_THRESHOLD = 11  # noqa
    MIN_INFLATION = 3  # noqa
    inflation = 0
    for node in ast.walk(func_node):
        if isinstance(node, ast.BoolOp):
            inflation += len(node.values) - 1

    if inflation < MIN_INFLATION:
        return False
    return (radon_cc - inflation) < RADON_C_THRESHOLD


def _is_simple_type_dispatch(func_node: ast.FunctionDef) -> bool:
    """Detect functions inflated by simple isinstance dispatch.

    False positive when: isinstance_count >= 4 AND isinstance_ratio >= 50%
    of all ifs AND all isinstance branch bodies have nesting depth <= 1.
    """
    MIN_ISINSTANCE_COUNT = 4  # noqa
    all_ifs = []
    isinstance_ifs = []

    for node in ast.walk(func_node):
        if not isinstance(node, ast.If):
            continue
        all_ifs.append(node)
        if _test_is_isinstance(node.test):
            isinstance_ifs.append(node)

    if len(isinstance_ifs) < MIN_ISINSTANCE_COUNT:
        return False
    if len(all_ifs) == 0:
        return False
    # isinstance_count / all_ifs >= 0.5 → isinstance_count * 2 >= all_ifs
    if len(isinstance_ifs) * 2 < len(all_ifs):
        return False

    # Check all isinstance branch bodies have shallow nesting
    for if_node in isinstance_ifs:
        for stmt in if_node.body:
            if _stmt_nesting_depth(stmt) > 1:
                return False
    return True


def _test_is_isinstance(test: ast.expr) -> bool:
    """Check if an if-test is isinstance(...) or not isinstance(...)."""
    if isinstance(test, ast.Call):
        func = test.func
        if isinstance(func, ast.Name) and func.id == "isinstance":
            return True
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _test_is_isinstance(test.operand)
    return False


def _filter_radon_false_positives(
    radon_cc: dict, src_dir: Path, file_cache: dict
) -> dict:
    """Post-process radon CC results to filter false positives.

    Annotates each item with fp_reason (str or None) and returns
    updated dict with filtered counts.
    """
    if not radon_cc.get("available") or not radon_cc.get("details"):
        return radon_cc

    details = radon_cc["details"]
    total_raw = len(details)
    filtered_count = 0

    for item in details:
        item["fp_reason"] = None
        rel_path = item.get("file", "")
        abs_path = str((src_dir.parent / rel_path).resolve())
        cached = file_cache.get(abs_path)
        if not cached:
            continue

        source, tree = cached
        if not tree:
            continue

        func_name = item.get("name", "")
        lineno = item.get("line", 0)

        # Manual suppression first
        if _has_radon_suppression(source, lineno):
            item["fp_reason"] = "suppressed"
            filtered_count += 1
            continue

        func_node = _find_function_node(tree, func_name, lineno)
        if not func_node:
            continue

        complexity = item.get("complexity", 0)

        if _is_guard_clause_chain(func_node):
            item["fp_reason"] = "guard_clauses"
            filtered_count += 1
        elif _has_compound_boolean_inflation(func_node, complexity):
            item["fp_reason"] = "compound_booleans"
            filtered_count += 1
        elif _is_simple_type_dispatch(func_node):
            item["fp_reason"] = "type_dispatch"
            filtered_count += 1

    genuine = [d for d in details if d["fp_reason"] is None]
    return {
        "available": True,
        "total_complex": len(genuine),
        "total_raw": total_raw,
        "filtered_count": filtered_count,
        "details": details,
        "filtered_details": genuine,
    }


def _run_radon_mi(src_dir: Path) -> dict:
    """Run radon maintainability index analysis."""
    try:
        # Run from /tmp to avoid radon crashing on pyproject.toml pytest config
        result = subprocess.run(
            ["radon", "mi", str(src_dir.resolve()), "-j"],
            capture_output=True, text=True, timeout=120,
            cwd="/tmp",
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            low_mi = []
            for filepath, score_data in data.items():
                rel_path = str(Path(filepath).relative_to(src_dir.parent))
                # radon mi returns {"file": {"mi": X, "rank": Y}} or just a letter
                if isinstance(score_data, dict):
                    mi = score_data.get("mi", 100)
                    rank = score_data.get("rank", "A")
                else:
                    # String rank like "A", "B", etc.
                    rank = str(score_data)
                    mi = 100  # Unknown
                if rank in ("C", "D", "F") or (isinstance(mi, (int, float)) and mi < 20):
                    low_mi.append({"file": rel_path, "mi": mi, "rank": rank})
            return {
                "available": True,
                "total_files": len(data),
                "low_maintainability": sorted(low_mi, key=lambda x: x.get("mi", 100)),
            }
        return {"available": True, "total_files": 0, "error": result.stderr[:500]}
    except FileNotFoundError:
        return {"available": False, "reason": "radon not installed (pip install radon)"}
    except subprocess.TimeoutExpired:
        return {"available": True, "error": "timeout after 120s"}
    except Exception as e:
        return {"available": False, "reason": str(e)[:200]}


def _run_pip_audit() -> dict:
    """Run pip-audit to check for dependency vulnerabilities."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip_audit", "--format", "json", "--desc"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode in (0, 1):  # 1 means vulnerabilities found
            data = json.loads(result.stdout)
            # pip-audit >= 2.x wraps results in {"dependencies": [...]}
            if isinstance(data, dict):
                data = data.get("dependencies", [])
            vulns = []
            for item in data:
                if not isinstance(item, dict) or "skip_reason" in item:
                    continue
                name = item.get("name", "")
                version = item.get("version", "")
                for vuln in item.get("vulns", []):
                    vulns.append({
                        "package": name,
                        "version": version,
                        "id": vuln.get("id", ""),
                        "description": vuln.get("description", "")[:200],
                        "fix_versions": vuln.get("fix_versions", []),
                    })
            high_count = sum(
                1 for v in vulns
                if "critical" in v.get("description", "").lower()
                or v.get("id", "").startswith("GHSA")
            )
            return {
                "available": True,
                "total": len(vulns),
                "high": high_count,
                "other": len(vulns) - high_count,
                "vulnerabilities": vulns[:50],  # Cap details
            }
        return {"available": True, "total": 0, "error": result.stderr[:500]}
    except FileNotFoundError:
        return {"available": False, "reason": "pip-audit not installed (pip install pip-audit)"}
    except subprocess.TimeoutExpired:
        return {"available": True, "error": "timeout after 120s"}
    except (json.JSONDecodeError, KeyError) as e:
        return {"available": True, "total": 0, "error": f"parse error: {e!s}"[:200]}
    except Exception as e:
        return {"available": False, "reason": str(e)[:200]}


def _run_mypy(src_dir: Path) -> dict:
    """Run mypy type checker on source directory."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "mypy", str(src_dir),
             "--no-error-summary", "--show-error-codes", "--no-color"],
            capture_output=True, text=True, timeout=120,
        )
        # mypy returns 1 when errors found, 0 when clean
        errors: list[dict] = []
        for line in result.stdout.splitlines():
            if ": error:" in line:
                parts = line.split(":", 3)
                if len(parts) >= 4:
                    errors.append({
                        "file": parts[0].strip(),
                        "line": parts[1].strip(),
                        "code": parts[3].strip()[:200],
                    })
        return {
            "available": True,
            "total_errors": len(errors),
            "details": errors[:50],  # Cap details
        }
    except FileNotFoundError:
        return {"available": False, "reason": "mypy not installed (pip install mypy)"}
    except subprocess.TimeoutExpired:
        return {"available": True, "total_errors": 0, "error": "timeout after 120s"}
    except Exception as e:
        return {"available": False, "reason": str(e)[:200]}


def _run_ruff(src_dir: Path) -> dict:
    """Run ruff linter and classify findings by rule prefix."""
    try:
        result = subprocess.run(
            ["ruff", "check", str(src_dir), "--output-format", "json", "--quiet"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode in (0, 1):  # 1 means issues found
            data = json.loads(result.stdout) if result.stdout.strip() else []
            details: list[dict] = []
            errors = 0
            warnings = 0
            security = 0
            imports = 0
            for item in data:
                code = item.get("code", "")
                category = "other"
                if code.startswith("S"):
                    category = "security"
                    security += 1
                elif code.startswith("F"):
                    category = "error"
                    errors += 1
                elif code.startswith("E") or code.startswith("W"):
                    category = "style"
                    warnings += 1
                elif code.startswith("I"):
                    category = "import"
                    imports += 1
                else:
                    warnings += 1  # default bucket

                loc = item.get("location", {})
                details.append({
                    "file": item.get("filename", ""),
                    "line": loc.get("row", 0),
                    "code": code,
                    "message": item.get("message", ""),
                    "category": category,
                })
            return {
                "available": True,
                "total": len(data),
                "errors": errors,
                "warnings": warnings,
                "security": security,
                "imports": imports,
                "details": details[:50],  # Cap details
            }
        return {"available": True, "total": 0, "error": result.stderr[:500]}
    except FileNotFoundError:
        return {"available": False, "reason": "ruff not installed (pip install ruff)"}
    except subprocess.TimeoutExpired:
        return {"available": True, "error": "timeout after 120s"}
    except (json.JSONDecodeError, KeyError) as e:
        return {"available": True, "total": 0, "error": f"parse error: {e!s}"[:200]}
    except Exception as e:
        return {"available": False, "reason": str(e)[:200]}


def _run_black_check(src_dir: Path) -> dict:
    """Run black in check mode to find unformatted files."""
    try:
        result = subprocess.run(
            ["black", "--check", "--quiet", str(src_dir)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return {"available": True, "total_unformatted": 0, "files": []}
        elif result.returncode == 1:
            # Parse stderr for "would reformat" lines
            files: list[str] = []
            for line in result.stderr.splitlines():
                if "would reformat" in line:
                    # Line format: "would reformat /path/to/file.py"
                    path = line.replace("would reformat", "").strip()
                    files.append(path)
            return {
                "available": True,
                "total_unformatted": len(files),
                "files": files[:50],  # Cap details
            }
        return {"available": True, "total_unformatted": 0, "error": result.stderr[:500]}
    except FileNotFoundError:
        return {"available": False, "reason": "black not installed (pip install black)"}
    except subprocess.TimeoutExpired:
        return {"available": True, "error": "timeout after 120s"}
    except Exception as e:
        return {"available": False, "reason": str(e)[:200]}


def _run_vulture(src_dir: Path) -> dict:
    """Run vulture to detect dead/unused code."""
    try:
        result = subprocess.run(
            ["vulture", str(src_dir), "--min-confidence", "80"],
            capture_output=True, text=True, timeout=120,
        )
        # vulture returns 1 when unused code found, 0 when clean
        details: list[dict] = []
        for line in result.stdout.splitlines():
            # Format: path/to/file.py:42: unused function 'foo' (90% confidence)
            m = re.match(
                r"^(.+?):(\d+):\s+unused\s+(\w+)\s+'([^']+)'\s+\((\d+)%\s+confidence\)",
                line,
            )
            if m:
                details.append({
                    "file": m.group(1),
                    "line": int(m.group(2)),
                    "type": m.group(3),
                    "name": m.group(4),
                    "confidence": int(m.group(5)),
                })
        return {
            "available": True,
            "total_unused": len(details),
            "details": details[:50],  # Cap details
        }
    except FileNotFoundError:
        return {"available": False, "reason": "vulture not installed (pip install vulture)"}
    except subprocess.TimeoutExpired:
        return {"available": True, "error": "timeout after 120s"}
    except Exception as e:
        return {"available": False, "reason": str(e)[:200]}


def _parse_coverage_json(coverage_path: Path) -> dict:
    """Parse a coverage.json file and extract per-file metrics."""
    try:
        data = json.loads(coverage_path.read_text(encoding="utf-8"))
        meta = data.get("meta", {})
        totals = data.get("totals", {})
        overall_percent = totals.get("percent_covered", 0.0)

        file_data = data.get("files", {})
        low_coverage: list[dict] = []
        for filepath, info in sorted(file_data.items()):
            summary = info.get("summary", {})
            pct = summary.get("percent_covered", 100.0)
            if pct < 50:
                low_coverage.append({
                    "file": filepath,
                    "percent": round(pct, 1),
                    "missing_lines": summary.get("missing_lines", 0),
                })

        return {
            "available": True,
            "source": str(coverage_path),
            "overall_percent": round(overall_percent, 1),
            "total_files": len(file_data),
            "low_coverage_modules": sorted(low_coverage, key=lambda x: x["percent"]),
            "low_coverage_count": len(low_coverage),
        }
    except (json.JSONDecodeError, KeyError, OSError) as e:
        return {"available": False, "reason": f"parse error: {e!s}"[:200]}


def _run_test_coverage(src_dir: Path) -> dict:
    """Get test coverage data, preferring existing coverage.json over running tests."""
    # Strategy 1: Parse existing coverage.json if present
    project_root = src_dir.parent
    for candidate in [
        project_root / "coverage.json",
        project_root / ".coverage.json",
        project_root / "htmlcov" / "coverage.json",
    ]:
        if candidate.exists():
            result = _parse_coverage_json(candidate)
            if result.get("available"):
                return result

    # Strategy 2: Run pytest with coverage (slower)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/",
             f"--cov={src_dir.name}", "--cov-report=json", "-x", "-q",
             "--no-header", "--override-ini=addopts="],
            capture_output=True, text=True, timeout=120,
            cwd=str(project_root),
        )
        coverage_json = project_root / "coverage.json"
        if coverage_json.exists():
            return _parse_coverage_json(coverage_json)
        return {
            "available": False,
            "reason": f"pytest exited {proc.returncode}, no coverage.json generated",
        }
    except FileNotFoundError:
        return {"available": False, "reason": "pytest not installed"}
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "test suite timeout after 120s"}
    except Exception as e:
        return {"available": False, "reason": str(e)[:200]}


# ---------------------------------------------------------------------------
# Function Complexity Analysis (AST-based)
# ---------------------------------------------------------------------------

def _code_line_count(node: ast.FunctionDef | ast.AsyncFunctionDef, source_lines: list[str]) -> int:
    """Count lines of executable code in a function, excluding docstrings, comments, and blanks.

    Args:
        node: AST function node (must have lineno and end_lineno).
        source_lines: Full file source split into lines (0-indexed).

    Returns:
        Number of code-only lines in the function body.
    """
    start = node.lineno  # 1-based inclusive
    end = node.end_lineno or node.lineno  # 1-based inclusive

    # Collect line ranges occupied by docstrings (the function's own + any nested)
    docstring_lines: set[int] = set()

    # Function-level docstring
    if (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    ):
        ds = node.body[0]
        for ln in range(ds.lineno, (ds.end_lineno or ds.lineno) + 1):
            docstring_lines.add(ln)

    count = 0
    for lineno in range(start, end + 1):
        if lineno in docstring_lines:
            continue
        line = source_lines[lineno - 1] if lineno <= len(source_lines) else ""
        stripped = line.strip()
        # Skip blank lines and full-line comments
        if not stripped or stripped.startswith("#"):
            continue
        count += 1

    return count


def _max_nesting_depth(node, *, _is_elif: bool = False) -> int:
    """Recursively calculate the maximum nesting depth of control flow structures.

    ``elif`` branches (an ``ast.If`` as the sole item in the parent
    ``ast.If.orelse``) are treated as siblings at the same depth — they
    don't add +1 nesting.  Only genuinely nested control flow increments
    the depth counter.
    """
    control_flow_types = (
        ast.If, ast.For, ast.While, ast.With, ast.Try,
        ast.AsyncFor, ast.AsyncWith,
    )
    # elif If nodes don't count as additional nesting
    is_cf = isinstance(node, control_flow_types) and not _is_elif

    max_child = 0

    if isinstance(node, ast.If):
        # body children are genuinely nested
        for child in node.body:
            max_child = max(max_child, _max_nesting_depth(child))
        # orelse: single If at same col_offset → elif (same depth)
        # "else: if" has the inner If indented (greater col_offset)
        if (
            len(node.orelse) == 1
            and isinstance(node.orelse[0], ast.If)
            and node.orelse[0].col_offset == node.col_offset
        ):
            max_child = max(
                max_child,
                _max_nesting_depth(node.orelse[0], _is_elif=True),
            )
        else:
            for child in node.orelse:
                max_child = max(max_child, _max_nesting_depth(child))
    else:
        for child in ast.iter_child_nodes(node):
            max_child = max(max_child, _max_nesting_depth(child))

    return (1 if is_cf else 0) + max_child


def scan_function_complexity(src_dir: Path, files: list[dict], *, file_cache: dict | None = None) -> dict:
    """Detect overly complex functions: long bodies, many params, deep nesting."""
    details: list[dict] = []
    parse_errors: list[str] = []
    total_functions = 0
    long_count = 0
    high_param_count = 0
    deep_nesting_count = 0

    for file_info in files:
        file_path = Path(file_info["abs_path"])
        rel_path = file_info["path"]

        if file_cache and file_info["abs_path"] in file_cache:
            source, tree = file_cache[file_info["abs_path"]]
            if tree is None:
                parse_errors.append(f"{rel_path}: cached parse error")
                continue
        else:
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(file_path))
            except (SyntaxError, ValueError) as e:
                parse_errors.append(f"{rel_path}: {e}")
                continue

        source_lines = source.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            total_functions += 1

            # Length — code lines only (excludes docstrings, comments, blanks)
            length = _code_line_count(node, source_lines)

            # Param count: args + kwonlyargs + vararg + kwarg, excluding self/cls
            args = node.args
            positional = args.args
            if positional and positional[0].arg in ("self", "cls"):
                positional = positional[1:]
            param_count = len(positional) + len(args.kwonlyargs)
            if args.vararg:
                param_count += 1
            if args.kwarg:
                param_count += 1

            # Nesting depth across all body statements
            nesting_depth = 0
            for stmt in node.body:
                depth = _max_nesting_depth(stmt)
                nesting_depth = max(nesting_depth, depth)

            # Determine flags
            flags: list[str] = []
            if length > LONG_FUNCTION_LINES:
                flags.append("long_function")
                long_count += 1
            if param_count > HIGH_PARAM_COUNT:
                # Check for # noqa: params suppression on the def line
                def_line = source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
                if "noqa" not in def_line or "params" not in def_line:
                    flags.append("high_param_count")
                    high_param_count += 1
            if nesting_depth > DEEP_NESTING_DEPTH:
                flags.append("deep_nesting")
                deep_nesting_count += 1

            if flags:
                details.append({
                    "file": rel_path,
                    "name": node.name,
                    "line": node.lineno,
                    "end_line": node.end_lineno or node.lineno,
                    "length": length,
                    "param_count": param_count,
                    "nesting_depth": nesting_depth,
                    "flags": flags,
                })

    return {
        "summary": {
            "total_functions": total_functions,
            "long_functions": long_count,
            "high_param_functions": high_param_count,
            "deep_nesting_functions": deep_nesting_count,
            "parse_errors": len(parse_errors),
        },
        "details": sorted(details, key=lambda x: (x["file"], x["line"])),
        "parse_errors": parse_errors,
    }


# ---------------------------------------------------------------------------
# Magic Values Detection (AST-based)
# ---------------------------------------------------------------------------

def scan_magic_values(src_dir: Path, files: list[dict], *, file_cache: dict | None = None) -> dict:
    """Detect magic numbers and repeated string literals."""
    magic_numbers: list[dict] = []
    all_repeated_strings: list[dict] = []
    parse_errors: list[str] = []

    _annotation_types = (ast.AnnAssign, ast.arg, ast.FunctionDef, ast.AsyncFunctionDef)

    for file_info in files:
        file_path = Path(file_info["abs_path"])
        rel_path = file_info["path"]

        if file_cache and file_info["abs_path"] in file_cache:
            source, tree = file_cache[file_info["abs_path"]]
            if tree is None:
                parse_errors.append(f"{rel_path}: cached parse error")
                continue
        else:
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(file_path))
            except (SyntaxError, ValueError) as e:
                parse_errors.append(f"{rel_path}: {e}")
                continue

        # Set _parent on all nodes
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                child._parent = node

        # Collect docstring positions (line numbers to skip)
        docstring_lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if (node.body
                        and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    docstring_lines.add(node.body[0].value.lineno)

        # Collect __name__ / "__main__" comparison lines
        dunder_main_lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                has_dunder = False
                if isinstance(node.left, ast.Name) and node.left.id == "__name__":
                    has_dunder = True
                for comp in node.comparators:
                    if isinstance(comp, ast.Name) and comp.id == "__name__":
                        has_dunder = True
                    if isinstance(comp, ast.Constant) and comp.value == "__main__":
                        has_dunder = True
                if has_dunder:
                    dunder_main_lines.add(node.lineno)

        # Collect lines with magic number suppression comments
        # Supports: # noqa, # noqa: magic, # scanner: skip-magic
        source_lines = source.splitlines()
        suppressed_magic_lines: set[int] = set()
        for i, line in enumerate(source_lines, 1):
            line_lower = line.lower()
            if "# noqa" in line_lower or "# scanner: skip-magic" in line_lower:
                suppressed_magic_lines.add(i)

        # Helper function to check if a node is inside a constant assignment
        def is_in_constant_assignment(node: ast.AST) -> bool:
            """Walk up the parent chain to check if we're inside an UPPERCASE assignment."""
            current = node
            while True:
                parent = getattr(current, "_parent", None)
                if parent is None:
                    return False

                # Check for simple assignment: CONST = value
                if isinstance(parent, ast.Assign):
                    return any(
                        isinstance(target, ast.Name) and target.id.isupper()
                        for target in parent.targets
                    )

                # Check for annotated assignment: CONST: type = value
                if isinstance(parent, ast.AnnAssign):
                    target = parent.target
                    if isinstance(target, ast.Name) and target.id.isupper():
                        return True

                # Continue walking up for containers (Dict, List, Tuple, Set)
                if isinstance(parent, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
                    current = parent
                    continue

                # Stop at other node types
                return False

        # --- Magic numbers ---
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, (int, float)):
                continue
            if isinstance(node.value, bool):
                continue
            if node.value in MAGIC_NUMBER_WHITELIST:
                continue
            if node.lineno in docstring_lines:
                continue
            if node.lineno in dunder_main_lines:
                continue
            if node.lineno in suppressed_magic_lines:
                continue

            # Skip annotations and constant definitions
            parent = getattr(node, "_parent", None)
            if parent is not None:
                if isinstance(parent, ast.AnnAssign) and node is not parent.value:
                    continue
                if isinstance(parent, ast.arg):
                    continue
                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node is parent.returns:
                        continue
                if isinstance(parent, ast.Subscript):
                    grandparent = getattr(parent, "_parent", None)
                    if grandparent is not None and isinstance(grandparent, _annotation_types):
                        continue

            # Skip constants in UPPERCASE assignments (including nested in dicts/lists/tuples)
            # e.g., DEFAULT_TIMEOUT = 300, THRESHOLDS = {"key": 5000}, VERSION = (3, 9)
            if is_in_constant_assignment(node):
                continue

            magic_numbers.append({
                "file": rel_path,
                "line": node.lineno,
                "value": node.value,
            })

        # --- Repeated strings ---
        string_occurrences: dict[str, list[int]] = defaultdict(list)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, str):
                continue
            if len(node.value) < MAGIC_STRING_MIN_LENGTH:
                continue
            if node.lineno in docstring_lines:
                continue
            if node.lineno in suppressed_magic_lines:
                continue
            if node.value in ("__name__", "__main__"):
                continue

            # Skip well-known non-magic values (SQL keywords, display literals)
            if node.value in _MAGIC_STRING_SKIP_VALUES:
                continue
            # Skip identifier-like strings (dict keys, config values, status names)
            val = node.value
            if len(val) <= _IDENTIFIER_LIKE_MAX_LEN and _IDENTIFIER_LIKE_RE.match(val):
                continue
            # Skip format specifiers (.1f, .3f, .1%, etc.)
            if _FORMAT_SPEC_RE.match(val):
                continue
            # Skip formatting/log fragments (whitespace, punctuation, short prefixes)
            if len(val) <= 8 and _LOG_FRAGMENT_RE.match(val):
                continue
            # Skip Python import/module paths (src.module.sub)
            if _IMPORT_PATH_RE.match(val):
                continue
            # Skip Rich console markup fragments ([bold], [/dim], etc.)
            if _RICH_MARKUP_RE.search(val):
                continue

            parent = getattr(node, "_parent", None)
            if parent is not None:
                # Skip type annotations
                if isinstance(parent, ast.AnnAssign) and node is not parent.value:
                    continue
                if isinstance(parent, ast.arg):
                    continue
                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node is parent.returns:
                        continue

                # Skip strings used as dict keys: {"key": val}
                if isinstance(parent, ast.Dict) and node in parent.keys:
                    continue
                # Skip strings used as subscript keys: d["key"]
                if isinstance(parent, ast.Subscript) and node is parent.slice:
                    continue
                # Skip strings in .get("key") / .pop("key") / .setdefault("key")
                if isinstance(parent, ast.Call):
                    func = parent.func
                    if (isinstance(func, ast.Attribute)
                            and func.attr in ("get", "pop", "setdefault")
                            and parent.args
                            and node is parent.args[0]):
                        continue

            # Skip strings in UPPERCASE constant assignments
            if is_in_constant_assignment(node):
                continue

            string_occurrences[node.value].append(node.lineno)

        for value, lines in string_occurrences.items():
            if len(lines) >= MAGIC_STRING_MIN_OCCURRENCES:
                all_repeated_strings.append({
                    "file": rel_path,
                    "value": value,
                    "count": len(lines),
                    "lines": sorted(lines),
                })

    return {
        "summary": {
            "total_magic_numbers": len(magic_numbers),
            "total_repeated_strings": len(all_repeated_strings),
            "parse_errors": len(parse_errors),
        },
        "magic_numbers": sorted(magic_numbers, key=lambda x: (x["file"], x["line"])),
        "repeated_strings": sorted(all_repeated_strings, key=lambda x: (x["file"], x["value"])),
        "parse_errors": parse_errors,
    }


# ---------------------------------------------------------------------------
# Dead Code Detection (AST-based)
# ---------------------------------------------------------------------------

def scan_dead_code(src_dir: Path, files: list[dict], *, file_cache: dict | None = None) -> dict:
    """Detect unreachable statements, empty branches, and constant conditions."""
    unreachable_details: list[dict] = []
    empty_branch_details: list[dict] = []
    constant_condition_details: list[dict] = []
    parse_errors: list[str] = []

    terminal_types = (ast.Return, ast.Raise, ast.Break, ast.Continue)

    def _check_body(body: list, filepath: str) -> None:
        """Check a list of statements for unreachable code after terminal statements."""
        for i, stmt in enumerate(body):
            if isinstance(stmt, terminal_types) and i + 1 < len(body):
                next_stmt = body[i + 1]
                unreachable_details.append({
                    "file": filepath,
                    "line": next_stmt.lineno,
                    "type": "unreachable_statement",
                    "description": f"Code after {type(stmt).__name__.lower()} is unreachable",
                })

    def _walk_bodies(node: ast.AST, filepath: str) -> None:
        """Recursively walk all statement bodies in an AST node."""
        body_attrs: list[list] = []

        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body_attrs.append(node.body)
        elif isinstance(node, ast.If):
            body_attrs.append(node.body)
            if node.orelse:
                body_attrs.append(node.orelse)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            body_attrs.append(node.body)
            if node.orelse:
                body_attrs.append(node.orelse)
        elif isinstance(node, ast.While):
            body_attrs.append(node.body)
            if node.orelse:
                body_attrs.append(node.orelse)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            body_attrs.append(node.body)
        elif isinstance(node, ast.Try):
            body_attrs.append(node.body)
            if node.orelse:
                body_attrs.append(node.orelse)
            if node.finalbody:
                body_attrs.append(node.finalbody)
            for handler in node.handlers:
                body_attrs.append(handler.body)
        elif isinstance(node, ast.ExceptHandler):
            body_attrs.append(node.body)

        for body in body_attrs:
            _check_body(body, filepath)

        for child in ast.iter_child_nodes(node):
            _walk_bodies(child, filepath)

    def _is_pass_or_ellipsis_only(body: list) -> bool:
        """Check if a body consists of only Pass or Ellipsis."""
        if len(body) != 1:
            return False
        stmt = body[0]
        if isinstance(stmt, ast.Pass):
            return True
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is ...:
            return True
        return False

    def _check_empty_branches(node: ast.AST, filepath: str) -> None:
        """Find empty if/else branches."""
        if isinstance(node, ast.If):
            if _is_pass_or_ellipsis_only(node.body):
                empty_branch_details.append({
                    "file": filepath,
                    "line": node.lineno,
                    "type": "empty_branch",
                    "description": "Empty if body (only pass/ellipsis)",
                })
            if node.orelse and _is_pass_or_ellipsis_only(node.orelse):
                empty_branch_details.append({
                    "file": filepath,
                    "line": node.lineno,
                    "type": "empty_branch",
                    "description": "Empty else body (only pass/ellipsis)",
                })
        for child in ast.iter_child_nodes(node):
            _check_empty_branches(child, filepath)

    def _check_constant_conditions(node: ast.AST, filepath: str) -> None:
        """Find if statements with constant True/False conditions (skip while True)."""
        if isinstance(node, ast.If):
            if isinstance(node.test, ast.Constant) and isinstance(node.test.value, bool):
                constant_condition_details.append({
                    "file": filepath,
                    "line": node.lineno,
                    "type": "constant_condition",
                    "description": f"Condition is always {node.test.value}",
                })
        for child in ast.iter_child_nodes(node):
            _check_constant_conditions(child, filepath)

    for file_info in files:
        file_path = Path(file_info["abs_path"])
        rel_path = file_info["path"]

        if file_cache and file_info["abs_path"] in file_cache:
            source, tree = file_cache[file_info["abs_path"]]
            if tree is None:
                parse_errors.append(f"{rel_path}: cached parse error")
                continue
        else:
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(file_path))
            except (SyntaxError, ValueError) as e:
                parse_errors.append(f"{rel_path}: {e}")
                continue

        _walk_bodies(tree, rel_path)
        _check_empty_branches(tree, rel_path)
        _check_constant_conditions(tree, rel_path)

    all_details = unreachable_details + empty_branch_details + constant_condition_details

    return {
        "summary": {
            "unreachable_statements": len(unreachable_details),
            "empty_branches": len(empty_branch_details),
            "constant_conditions": len(constant_condition_details),
            "parse_errors": len(parse_errors),
        },
        "details": sorted(all_details, key=lambda x: (x["file"], x["line"])),
        "parse_errors": parse_errors,
    }


# ---------------------------------------------------------------------------
# Import Density Analysis
# ---------------------------------------------------------------------------

def compute_import_density(import_data: dict) -> dict:
    """Compute fan-out and fan-in metrics from scan_imports output."""
    module_graph = import_data.get("module_graph", {})

    total_modules = len(module_graph)

    if total_modules == 0:
        return {
            "summary": {
                "total_modules": 0,
                "high_fan_out_count": 0,
                "high_fan_in_count": 0,
                "avg_fan_out": 0.0,
                "avg_fan_in": 0.0,
            },
            "fan_out": [],
            "fan_in": [],
            "high_coupling": [],
        }

    # Build fan_out: module -> list of imports
    fan_out_map = {mod: sorted(imports) for mod, imports in module_graph.items()}

    # Build fan_in: module -> list of modules that import it
    fan_in_map: dict[str, list[str]] = {}
    for mod, imports in module_graph.items():
        for imp in imports:
            if imp not in fan_in_map:
                fan_in_map[imp] = []
            fan_in_map[imp].append(mod)

    # Sort imported_by lists for determinism
    for imp in fan_in_map:
        fan_in_map[imp].sort()

    # Calculate averages
    total_fan_out = sum(len(imports) for imports in fan_out_map.values())
    avg_fan_out = round(total_fan_out / total_modules, 2) if total_modules > 0 else 0.0

    total_fan_in = sum(len(importers) for importers in fan_in_map.values())
    all_modules = set(module_graph.keys()) | set(fan_in_map.keys())
    avg_fan_in = round(total_fan_in / len(all_modules), 2) if all_modules else 0.0

    # Flag high fan-out
    high_fan_out_list = []
    for mod in sorted(fan_out_map.keys()):
        count = len(fan_out_map[mod])
        if count >= HIGH_FAN_OUT:
            high_fan_out_list.append({
                "module": mod,
                "fan_out": count,
                "imports": fan_out_map[mod],
            })

    # Flag high fan-in (skip foundational modules with fan_out<=2 —
    # modules like constants, utils, core are *expected* to be widely imported)
    high_fan_in_list = []
    for mod in sorted(fan_in_map.keys()):
        count = len(fan_in_map[mod])
        fan_out = len(fan_out_map.get(mod, []))
        if count >= HIGH_FAN_IN and fan_out > 2:
            high_fan_in_list.append({
                "module": mod,
                "fan_in": count,
                "imported_by": fan_in_map[mod],
            })

    # High coupling: modules flagged for either high fan-out or high fan-in
    high_fan_out_set = {item["module"] for item in high_fan_out_list}
    high_fan_in_set = {item["module"] for item in high_fan_in_list}
    high_coupling_modules = high_fan_out_set | high_fan_in_set

    high_coupling_list = []
    for mod in sorted(high_coupling_modules):
        fo = len(fan_out_map.get(mod, []))
        fi = len(fan_in_map.get(mod, []))
        reasons = []
        if mod in high_fan_out_set:
            reasons.append(f"high fan-out ({fo})")
        if mod in high_fan_in_set:
            reasons.append(f"high fan-in ({fi})")
        high_coupling_list.append({
            "module": mod,
            "fan_out": fo,
            "fan_in": fi,
            "reasons": reasons,
        })

    return {
        "summary": {
            "total_modules": total_modules,
            "high_fan_out_count": len(high_fan_out_list),
            "high_fan_in_count": len(high_fan_in_list),
            "avg_fan_out": avg_fan_out,
            "avg_fan_in": avg_fan_in,
        },
        "fan_out": high_fan_out_list,
        "fan_in": high_fan_in_list,
        "high_coupling": high_coupling_list,
    }


# ---------------------------------------------------------------------------
# Duplicate Code Detection (AST-based)
# ---------------------------------------------------------------------------

def _normalize_ast_body(body: list[ast.stmt]) -> str:
    """Normalize an AST function body for duplicate detection.

    Renames all Name nodes to sequential _v0, _v1, ... and strips
    location info so that structurally identical code with different
    variable names and positions produces the same dump.

    Re-parses from unparse to avoid deepcopy issues with _parent attrs.
    """
    # Re-parse to get a clean AST without custom attributes (e.g. _parent)
    try:
        wrapper = ast.Module(body=body, type_ignores=[])
        source = ast.unparse(wrapper)
        fresh = ast.parse(source)
    except (SyntaxError, ValueError):
        # Fallback: dump without normalization
        return ast.dump(ast.Module(body=body, type_ignores=[]))

    name_map: dict[str, str] = {}
    counter = 0

    for node in ast.walk(fresh):
        if isinstance(node, ast.Name):
            if node.id not in name_map:
                name_map[node.id] = f"_v{counter}"
                counter += 1
            node.id = name_map[node.id]

    for node in ast.walk(fresh):
        for attr in ("lineno", "col_offset", "end_lineno", "end_col_offset"):
            if hasattr(node, attr):
                setattr(node, attr, 0)

    return ast.dump(fresh)


def _has_duplicate_suppression(source: str, node_lineno: int) -> bool:
    """Check if a function has a comment suppressing duplicate detection.

    Looks for comments like:
    - # scanner-ignore: duplicate
    - # noqa: duplicate
    on the line before or same line as the function definition.
    """
    if not source:
        return False

    lines = source.splitlines()
    if not lines or node_lineno < 1 or node_lineno > len(lines):
        return False

    # Check line before function definition (1-indexed to 0-indexed)
    check_lines = []
    if node_lineno > 1:
        check_lines.append(lines[node_lineno - 2])
    if node_lineno <= len(lines):
        check_lines.append(lines[node_lineno - 1])

    for line in check_lines:
        line_lower = line.lower()
        if ('scanner-ignore' in line_lower and 'duplicate' in line_lower) or \
           ('noqa' in line_lower and 'duplicate' in line_lower):
            return True

    return False


def scan_duplicate_code(
    src_dir: Path, files: list[dict], *, file_cache: dict | None = None
) -> dict:
    """Detect duplicate function bodies via AST normalization and hashing.

    Functions can be excluded from duplicate detection by adding a comment:
        # scanner-ignore: duplicate
    or
        # noqa: duplicate
    on the line before the function definition.
    """
    parse_errors: list[str] = []
    func_entries: list[tuple[str, str, int, int, list]] = []

    cache = file_cache if file_cache else _build_file_cache(files)

    for file_info in files:
        abs_path = file_info["abs_path"]
        rel_path = file_info["path"]
        source, tree = cache.get(abs_path, ("", None))
        if tree is None:
            if source or Path(abs_path).exists():
                parse_errors.append(f"{rel_path}: parse error")
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.body:
                    continue

                # Skip if function has duplicate suppression comment
                if _has_duplicate_suppression(source, node.lineno):
                    continue

                start = node.body[0].lineno
                end = max(
                    getattr(n, "end_lineno", getattr(n, "lineno", start))
                    for n in node.body
                )
                body_lines = end - start + 1
                if body_lines < MIN_DUPLICATE_LINES:
                    continue
                func_entries.append((rel_path, node.name, node.lineno, body_lines, node.body))

    if len(func_entries) > MAX_FUNCTIONS_FOR_DUPLICATE_SCAN:
        return {
            "summary": {
                "total_functions_analyzed": len(func_entries),
                "duplicate_groups": 0,
                "total_duplicated_functions": 0,
                "skipped": True,
                "parse_errors": len(parse_errors),
            },
            "details": [],
            "parse_errors": parse_errors,
        }

    # Hash each function body
    hash_groups: dict[str, list[dict]] = defaultdict(list)
    for rel_path, func_name, line, body_lines, body in func_entries:
        normalized = _normalize_ast_body(body)
        h = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        hash_groups[h].append({
            "file": rel_path,
            "name": func_name,
            "line": line,
            "body_lines": body_lines,
        })

    # Filter to groups with 2+ members
    duplicate_groups = []
    for h, locations in hash_groups.items():
        if len(locations) >= 2:
            sorted_locs = sorted(locations, key=lambda loc: (loc["file"], loc["line"]))
            duplicate_groups.append({
                "hash": h[:16],
                "count": len(sorted_locs),
                "lines": sorted_locs[0]["body_lines"],
                "locations": [
                    {"file": loc["file"], "name": loc["name"], "line": loc["line"]}
                    for loc in sorted_locs
                ],
            })

    # Sort groups by first occurrence
    duplicate_groups.sort(key=lambda g: (g["locations"][0]["file"], g["locations"][0]["line"]))

    total_duplicated = sum(g["count"] for g in duplicate_groups)

    return {
        "summary": {
            "total_functions_analyzed": len(func_entries),
            "duplicate_groups": len(duplicate_groups),
            "total_duplicated_functions": total_duplicated,
            "skipped": False,
            "parse_errors": len(parse_errors),
        },
        "details": duplicate_groups,
        "parse_errors": parse_errors,
    }


# ---------------------------------------------------------------------------
# Test Quality Analysis
# ---------------------------------------------------------------------------

def scan_test_quality(src_dir: Path, *, src_total_lines: int = 0) -> dict:
    """Analyze test quality: assert density, zero-assert tests, test-to-code ratio."""
    tests_dir = src_dir.parent / "tests"
    if not tests_dir.exists():
        return {
            "summary": {
                "available": False,
                "total_test_files": 0,
                "total_test_lines": 0,
                "total_test_functions": 0,
                "zero_assert_tests": 0,
                "avg_assert_density": 0.0,
                "test_to_code_ratio": 0.0,
            },
            "zero_assert_details": [],
            "low_density_details": [],
        }

    test_files_result = scan_files(tests_dir)
    test_files = test_files_result["details"]
    total_test_lines = test_files_result["summary"]["total_lines"]
    cache = _build_file_cache(test_files)

    all_test_funcs: list[dict] = []
    total_asserts = 0

    for file_info in test_files:
        abs_path = file_info["abs_path"]
        rel_path = file_info["path"]
        source, tree = cache.get(abs_path, ("", None))
        if tree is None:
            continue

        # Collect test functions: top-level test_* and methods inside Test* classes
        test_nodes: list[tuple[str, ast.FunctionDef]] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                test_nodes.append((node.name, node))
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                        test_nodes.append((item.name, item))

        for func_name, func_node in test_nodes:
            assert_count = 0
            for child in ast.walk(func_node):
                if isinstance(child, ast.Assert):
                    assert_count += 1
                elif isinstance(child, ast.Call):
                    func_attr = child.func
                    if isinstance(func_attr, ast.Attribute):
                        if func_attr.attr == "raises":
                            assert_count += 1
                        elif func_attr.attr.startswith("assert_"):
                            assert_count += 1

            total_asserts += assert_count
            func_info = {
                "file": rel_path,
                "name": func_name,
                "line": func_node.lineno,
                "assert_count": assert_count,
            }
            all_test_funcs.append(func_info)

    zero_assert = [f for f in all_test_funcs if f["assert_count"] == 0]
    low_density = [f for f in all_test_funcs if f["assert_count"] > 0]

    total_test_functions = len(all_test_funcs)
    avg_density = round(total_asserts / total_test_functions, 2) if total_test_functions else 0.0
    ratio = round(total_test_lines / src_total_lines, 2) if src_total_lines else 0.0

    return {
        "summary": {
            "available": True,
            "total_test_files": len(test_files),
            "total_test_lines": total_test_lines,
            "total_test_functions": total_test_functions,
            "zero_assert_tests": len(zero_assert),
            "avg_assert_density": avg_density,
            "test_to_code_ratio": ratio,
        },
        "zero_assert_details": [
            {"file": f["file"], "name": f["name"], "line": f["line"]}
            for f in zero_assert
        ],
        "low_density_details": [
            {"file": f["file"], "name": f["name"], "line": f["line"], "assert_count": f["assert_count"]}
            for f in low_density
        ],
    }


# ---------------------------------------------------------------------------
# Deterministic Score
# ---------------------------------------------------------------------------

def compute_deterministic_score(
    anti_patterns: dict,
    naming_collisions: dict,
    god_objects: dict,
    layer_violations: dict,
    circular_deps: list,
    static_analysis: dict,
    unused_imports: dict | None = None,
    missing_docstrings: dict | None = None,
    test_coverage: dict | None = None,
    function_complexity: dict | None = None,
    magic_values: dict | None = None,
    dead_code: dict | None = None,
    import_density: dict | None = None,
    duplicate_code: dict | None = None,
    test_quality: dict | None = None,
) -> dict:
    """Compute a fully deterministic score from scan results.

    This score is 100% reproducible - same codebase always gets same score.
    Agents can adjust +/-10 based on contextual judgment, but the base is fixed.

    Scoring uses diminishing returns per category to avoid a single noisy
    category (e.g., 100 type-ignore comments) dominating the score.
    """
    score = 100
    deductions: list[dict] = []

    def deduct(reason: str, count: int, per_item: float, cap: float) -> None:
        nonlocal score
        if count <= 0:
            return
        pts = min(count * per_item, cap)
        score -= pts
        deductions.append({"reason": f"{count} {reason}", "points": round(-pts, 1)})

    # Anti-pattern deductions (capped per severity)
    ap = anti_patterns["summary"]
    deduct("CRITICAL anti-patterns", ap["critical"], 10, 25)
    deduct("HIGH anti-patterns", ap["high"], 3, 15)

    # Avoid double-counting: broad_except is already in MEDIUM count from regex scan.
    # Subtract broad_except hits, apply them at their own rate, then apply remaining MEDIUM.
    broad_except_count = sum(
        1 for d in anti_patterns.get("details", [])
        if d.get("pattern") == "broad_except"
    )
    medium_without_broad = ap["medium"] - broad_except_count
    deduct("MEDIUM anti-patterns (excl. broad_except)", medium_without_broad, 1.5, 10)
    deduct("broad_except anti-patterns", broad_except_count, 0.5, 3)
    deduct("LOW anti-patterns", ap["low"], 0.5, 5)

    # Structural issues (diminishing returns — first few matter most)
    nc = naming_collisions["summary"]["total_collisions"]
    deduct("naming collisions", nc, 1, 8)

    gc = god_objects["summary"]["god_classes"]
    deduct("god classes (>" + str(GOD_CLASS_LINES) + " lines)", gc, 1, 12)

    lv = layer_violations["summary"]["total_violations"]
    deduct("layer violations (upward deps)", lv, 1, 8)

    cd = len(circular_deps)
    deduct("circular dependencies", cd, 1.5, 8)

    # Bandit findings (if available)
    bandit = static_analysis.get("bandit", {})
    if bandit.get("available"):
        deduct("bandit HIGH findings", bandit.get("high", 0), 3, 15)
        deduct("bandit MEDIUM findings", bandit.get("medium", 0), 1.5, 10)

    # Radon CC complex items (C+ rating)
    radon_cc = static_analysis.get("radon_cc", {})
    if radon_cc.get("available"):
        filtered = radon_cc.get("filtered_count", 0)
        label = (
            f"radon complex items (C+, {filtered} FP filtered)"
            if filtered
            else "radon complex items (C+)"
        )
        deduct(label, radon_cc.get("total_complex", 0), 0.5, 5)

    # pip-audit findings (if available)
    pip_audit = static_analysis.get("pip_audit", {})
    if pip_audit.get("available"):
        deduct("pip-audit HIGH vulnerabilities", pip_audit.get("high", 0), 5, 20)
        deduct("pip-audit other vulnerabilities", pip_audit.get("other", 0), 2, 10)

    # mypy type errors (if available)
    mypy = static_analysis.get("mypy", {})
    if mypy.get("available"):
        deduct("mypy type errors", mypy.get("total_errors", 0), 0.1, 5)

    # ruff findings (if available)
    ruff = static_analysis.get("ruff", {})
    if ruff.get("available"):
        deduct("ruff errors (F*)", ruff.get("errors", 0), 0.3, 5)
        deduct("ruff security (S*)", ruff.get("security", 0), 0.5, 5)

    # black formatting (if available)
    black = static_analysis.get("black", {})
    if black.get("available"):
        deduct("black unformatted files", black.get("total_unformatted", 0), 0.2, 3)

    # vulture dead code (if available)
    vulture = static_analysis.get("vulture", {})
    if vulture.get("available"):
        deduct("vulture dead code items", vulture.get("total_unused", 0), 0.2, 5)

    # Unused imports (if provided)
    if unused_imports is not None:
        deduct("unused imports", unused_imports["summary"]["total_unused"], 0.3, 5)

    # Missing docstrings on public classes and functions (if provided)
    if missing_docstrings is not None:
        deduct(
            "missing docstrings (public classes)",
            missing_docstrings["summary"]["missing_on_classes"],
            0.2, 5,
        )
        deduct(
            "missing docstrings (public functions)",
            missing_docstrings["summary"].get("missing_on_functions", 0),
            0.1, 5,
        )

    # Low test coverage modules (if provided)
    if test_coverage is not None and test_coverage.get("available"):
        deduct(
            "low coverage modules (<50%)",
            test_coverage.get("low_coverage_count", 0),
            1, 8,
        )
        # Coverage gap severity: 0% is worse than 49%
        # Sum (50 - actual%) for each low module
        coverage_gap = sum(
            50 - m.get("percent", 0)
            for m in test_coverage.get("low_coverage_modules", [])
        )
        deduct("coverage gap severity", int(coverage_gap), 0.01, 5)

    # v2.3.0: Function complexity (if provided)
    if function_complexity is not None:
        fc = function_complexity["summary"]
        deduct("long functions (>50 lines)", fc.get("long_functions", 0), 0.3, 5)
        deduct("high parameter count (>7)", fc.get("high_param_functions", 0), 0.3, 3)
        deduct("deep nesting (>4 levels)", fc.get("deep_nesting_functions", 0), 0.5, 5)

    # v2.3.0: Dead code (if provided)
    if dead_code is not None:
        dc = dead_code["summary"]
        deduct("unreachable code statements", dc.get("unreachable_statements", 0), 0.5, 5)
        deduct("empty if/else branches", dc.get("empty_branches", 0), 0.3, 3)

    # v2.3.0: Import density (if provided)
    if import_density is not None:
        id_s = import_density["summary"]
        deduct("high fan-out modules (>=8)", id_s.get("high_fan_out_count", 0), 1.0, 5)
        deduct("high fan-in modules (>=6)", id_s.get("high_fan_in_count", 0), 0.5, 3)

    # v2.3.0: Magic values (if provided)
    if magic_values is not None:
        mv = magic_values["summary"]
        deduct("magic numbers", mv.get("total_magic_numbers", 0), 0.1, 3)
        deduct("repeated magic strings (3+)", mv.get("total_repeated_strings", 0), 0.2, 3)

    # v2.3.0: Duplicate code (if provided)
    if duplicate_code is not None and not duplicate_code["summary"].get("skipped"):
        deduct("duplicate code groups", duplicate_code["summary"].get("duplicate_groups", 0), 1.5, 8)

    # v2.3.0: Test quality (if provided)
    if test_quality is not None and test_quality["summary"].get("available"):
        deduct("zero-assert test functions", test_quality["summary"].get("zero_assert_tests", 0), 0.5, 5)

    score = max(0, round(score))

    return {
        "score": score,
        "deductions": deductions,
        "total_deducted": 100 - score,
        "grade": _score_to_grade(score),
    }


def _score_to_grade(score: int) -> str:
    if score >= 95: return "A+"
    if score >= 90: return "A"
    if score >= 85: return "A-"
    if score >= 80: return "B+"
    if score >= 75: return "B"
    if score >= 70: return "B-"
    if score >= 65: return "C+"
    if score >= 60: return "C"
    if score >= 50: return "D"
    return "F"


# ---------------------------------------------------------------------------
# Content Hash (for detecting codebase changes)
# ---------------------------------------------------------------------------

def compute_content_hash(src_dir: Path) -> str:
    """SHA-256 hash of all source file contents for change detection."""
    h = hashlib.sha256()
    for py_file in sorted(src_dir.rglob("*.py")):
        try:
            h.update(py_file.read_bytes())
        except OSError:
            pass
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic Architecture Scanner")
    parser.add_argument("src_dir", nargs="?", default="src", help="Source directory to scan")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    args = parser.parse_args()

    src_dir = Path(args.src_dir).resolve()
    if not src_dir.is_dir():
        print(f"Error: {src_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Step 1: Collect facts
    files = scan_files(src_dir)
    file_cache = _build_file_cache(files["details"])

    # Run 10 independent AST scans in parallel (file cache is immutable, thread-safe)
    ast_scan_runners = {
        "imports": lambda: scan_imports(src_dir, files["details"], file_cache=file_cache),
        "classes": lambda: scan_classes(src_dir, files["details"], file_cache=file_cache),
        "anti_patterns": lambda: scan_anti_patterns(src_dir, files["details"], file_cache=file_cache),
        "unused_imports": lambda: scan_unused_imports(src_dir, files["details"], file_cache=file_cache),
        "missing_docstrings": lambda: scan_missing_docstrings(src_dir, files["details"], file_cache=file_cache),
        "broad_try": lambda: scan_broad_try_blocks(src_dir, files["details"], file_cache=file_cache),
        "function_complexity": lambda: scan_function_complexity(src_dir, files["details"], file_cache=file_cache),
        "magic_values": lambda: scan_magic_values(src_dir, files["details"], file_cache=file_cache),
        "dead_code": lambda: scan_dead_code(src_dir, files["details"], file_cache=file_cache),
        "duplicate_code": lambda: scan_duplicate_code(src_dir, files["details"], file_cache=file_cache),
    }
    ast_results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(runner): name
            for name, runner in ast_scan_runners.items()
        }
        for future in as_completed(futures):
            ast_results[futures[future]] = future.result()

    imports = ast_results["imports"]
    classes = ast_results["classes"]
    anti_patterns = ast_results["anti_patterns"]
    unused_imports = ast_results["unused_imports"]
    missing_docstrings = ast_results["missing_docstrings"]
    broad_try = ast_results["broad_try"]
    function_complexity = ast_results["function_complexity"]
    magic_values = ast_results["magic_values"]
    dead_code = ast_results["dead_code"]
    duplicate_code = ast_results["duplicate_code"]

    # Parallelize dependent computations and external tools
    # Group 1: Depends on classes
    # Group 2: Depends on imports
    # Group 3: Independent (external tools)
    dependent_runners = {
        "collisions": lambda: find_naming_collisions(classes["details"]),
        "god_objects": lambda: find_god_objects(files["details"], classes["details"]),
        "layers": lambda: analyze_layers(imports),
        "import_density": lambda: compute_import_density(imports),
        "static": lambda: run_static_analysis(src_dir),
        "test_coverage": lambda: _run_test_coverage(src_dir),
        "test_quality": lambda: scan_test_quality(src_dir, src_total_lines=files["summary"]["total_lines"]),
    }
    dependent_results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = {
            executor.submit(runner): name
            for name, runner in dependent_runners.items()
        }
        for future in as_completed(futures):
            dependent_results[futures[future]] = future.result()

    collisions = dependent_results["collisions"]
    god_objects = dependent_results["god_objects"]
    layers = dependent_results["layers"]
    import_density = dependent_results["import_density"]
    static = dependent_results["static"]
    test_coverage = dependent_results["test_coverage"]
    test_quality = dependent_results["test_quality"]

    # Post-process radon CC to filter false positives
    if static.get("radon_cc", {}).get("available"):
        static["radon_cc"] = _filter_radon_false_positives(
            static["radon_cc"], src_dir, file_cache
        )

    # Step 2: Compute deterministic score
    det_score = compute_deterministic_score(
        anti_patterns=anti_patterns,
        naming_collisions=collisions,
        god_objects=god_objects,
        layer_violations=layers,
        circular_deps=imports.get("circular_dependencies", []),
        static_analysis=static,
        unused_imports=unused_imports,
        missing_docstrings=missing_docstrings,
        test_coverage=test_coverage,
        function_complexity=function_complexity,
        magic_values=magic_values,
        dead_code=dead_code,
        import_density=import_density,
        duplicate_code=duplicate_code,
        test_quality=test_quality,
    )

    # Step 3: Build output
    # Remove abs_path from file details (internal only)
    for f in files["details"]:
        f.pop("abs_path", None)

    # Build results dict with deterministic key ordering
    results = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "src_dir": str(src_dir),
            "scanner_version": "2.4.1",
            "content_hash": compute_content_hash(src_dir),
        },
        "files": files,
        "imports": imports,
        "classes": classes,
        "anti_patterns": anti_patterns,
        "naming_collisions": collisions,
        "god_objects": god_objects,
        "layer_analysis": layers,
        "static_analysis": static,
        # Flatten external tool results to top level for easy access (sorted order)
        "bandit": static.get("bandit", {}),
        "black": static.get("black", {}),
        "mypy": static.get("mypy", {}),
        "pip_audit": static.get("pip_audit", {}),
        "radon_cc": static.get("radon_cc", {}),
        "radon_mi": static.get("radon_mi", {}),
        "ruff": static.get("ruff", {}),
        "vulture": static.get("vulture", {}),
        "coverage": test_coverage,
        "unused_imports": unused_imports,
        "missing_docstrings": missing_docstrings,
        "broad_try_blocks": broad_try,
        "test_coverage": test_coverage,
        "function_complexity": function_complexity,
        "magic_values": magic_values,
        "dead_code": dead_code,
        "import_density": import_density,
        "duplicate_code": duplicate_code,
        "test_quality": test_quality,
        "deterministic_score": det_score,
    }

    # Ensure deterministic JSON output (sort keys)
    output = json.dumps(results, indent=2, default=str, sort_keys=True)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Scan results written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
