"""Dead code detection — unreachable statements and empty branches."""

import ast

from scripts.code_quality_check.base import Finding, Rule, ScanContext, Severity

_TERMINAL = (ast.Return, ast.Raise, ast.Break, ast.Continue)


class DeadCodeRule(Rule):
    key = "dead_code"
    title = "Dead Code"
    severity = Severity.MEDIUM
    tags = ["correctness"]

    def scan(self, ctx: ScanContext) -> list[Finding]:
        findings = []

        for file_info in ctx.files:
            tree = ctx.ast_tree(file_info["abs_path"])
            if not tree:
                continue

            rel_path = file_info["path"]
            _walk_body(tree, rel_path, findings)

        return findings


def _walk_body(node: ast.AST, file_path: str, findings: list[Finding]) -> None:
    """Recursively check all statement bodies for dead code."""
    for child in ast.iter_child_nodes(node):
        # Check bodies of compound statements
        for attr in ("body", "orelse", "finalbody", "handlers"):
            body = getattr(child, attr, None)
            if isinstance(body, list):
                _check_unreachable(body, file_path, findings)
                _check_empty_branch(body, child, attr, file_path, findings)

        _walk_body(child, file_path, findings)


def _check_unreachable(stmts: list[ast.stmt], file_path: str, findings: list[Finding]) -> None:
    """Find statements after return/raise/break/continue."""
    for i, stmt in enumerate(stmts):
        if isinstance(stmt, _TERMINAL) and i < len(stmts) - 1:
            next_stmt = stmts[i + 1]
            # Skip if the next statement is a function/class def (valid pattern)
            if isinstance(next_stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            findings.append(Finding(
                rule="dead_code",
                message=f"Unreachable code after {type(stmt).__name__.lower()}",
                file=file_path,
                line=next_stmt.lineno,
                severity=Severity.MEDIUM,
            ))
            break  # Only report first unreachable per block


def _check_empty_branch(
    body: list[ast.stmt],
    parent: ast.AST,
    attr: str,
    file_path: str,
    findings: list[Finding],
) -> None:
    """Detect empty branches (only 'pass' or docstring)."""
    if not body or len(body) > 1:
        return

    stmt = body[0]
    is_pass = isinstance(stmt, ast.Pass)
    is_docstring = (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )

    if not (is_pass or is_docstring):
        return

    # Skip: abstract methods, protocol stubs, exception handlers (cleanup pass)
    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # Abstract method with pass is fine
        for decorator in parent.decorator_list:
            name = getattr(decorator, "id", "") or getattr(decorator, "attr", "")
            if name in ("abstractmethod", "overload"):
                return
        return  # pass in function body is a stub, not dead code

    if isinstance(parent, ast.ExceptHandler):
        return  # pass in except is intentional suppression

    if attr == "orelse" and isinstance(parent, ast.If):
        findings.append(Finding(
            rule="dead_code",
            message="Empty else branch (only pass)",
            file=file_path,
            line=stmt.lineno,
            severity=Severity.LOW,
        ))
