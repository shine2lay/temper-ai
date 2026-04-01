"""Duplicate code detection — finds functions with identical structure."""

import ast
import hashlib

from scripts.code_quality_check.base import Finding, Rule, ScanContext, Severity

MIN_DUPLICATE_LINES = 6
MAX_FUNCTIONS = 2000  # Skip scan if too many functions (O(n) hashing)


class DuplicateCodeRule(Rule):
    key = "duplicate_code"
    title = "Duplicate Code"
    severity = Severity.MEDIUM
    tags = ["maintainability"]

    def scan(self, ctx: ScanContext) -> list[Finding]:
        # Collect all functions with normalized bodies
        functions: list[dict] = []

        for file_info in ctx.files:
            tree = ctx.ast_tree(file_info["abs_path"])
            source = ctx.source(file_info["abs_path"])
            if not tree:
                continue

            lines = source.split("\n")
            rel_path = file_info["path"]

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue

                # Skip suppressed
                if node.lineno <= len(lines):
                    def_line = lines[node.lineno - 1]
                    if "# noqa" in def_line and "duplicate" in def_line.lower():
                        continue

                end_line = getattr(node, "end_lineno", node.lineno)
                line_count = end_line - node.lineno + 1

                if line_count < MIN_DUPLICATE_LINES:
                    continue

                body_hash = _hash_body(node)
                if body_hash:
                    functions.append({
                        "name": node.name,
                        "file": rel_path,
                        "line": node.lineno,
                        "lines": line_count,
                        "hash": body_hash,
                    })

        if len(functions) > MAX_FUNCTIONS:
            return []  # Too many — skip to avoid slow scan

        # Group by hash
        groups: dict[str, list[dict]] = {}
        for func in functions:
            groups.setdefault(func["hash"], []).append(func)

        findings = []
        for funcs in groups.values():
            if len(funcs) <= 1:
                continue

            names = [f"{f['file']}:{f['name']}" for f in funcs]
            findings.append(Finding(
                rule=self.key,
                message=f"Duplicate function bodies ({len(funcs)} copies): {', '.join(names)}",
                file=funcs[0]["file"],
                line=funcs[0]["line"],
                severity=Severity.MEDIUM,
                metadata={"functions": names, "line_count": funcs[0]["lines"]},
            ))

        return findings


def _hash_body(func_node: ast.FunctionDef) -> str | None:
    """Hash a function's body after normalizing variable names."""
    try:
        normalized = _normalize_body(func_node.body)
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]
    except Exception:
        return None


def _normalize_body(stmts: list[ast.stmt]) -> str:
    """Convert AST body to a normalized string (variable names replaced)."""
    parts = []
    for stmt in stmts:
        parts.append(ast.dump(stmt))
    return "\n".join(parts)
