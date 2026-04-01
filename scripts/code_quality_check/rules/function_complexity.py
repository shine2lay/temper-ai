"""Function complexity — detect long, deeply nested, or high-param functions."""

import ast

from scripts.code_quality_check.base import Finding, Rule, ScanContext, Severity

LONG_FUNCTION_LINES = 50
HIGH_PARAM_COUNT = 7
DEEP_NESTING_DEPTH = 4


class FunctionComplexityRule(Rule):
    key = "function_complexity"
    title = "Function Complexity"
    severity = Severity.MEDIUM
    tags = ["complexity"]

    def scan(self, ctx: ScanContext) -> list[Finding]:
        findings = []

        for file_info in ctx.files:
            tree = ctx.ast_tree(file_info["abs_path"])
            source = ctx.source(file_info["abs_path"])
            if not tree:
                continue

            rel_path = file_info["path"]
            lines = source.split("\n")

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue

                # Check suppression
                if node.lineno <= len(lines):
                    def_line = lines[node.lineno - 1]
                    if "# noqa" in def_line:
                        continue

                end_line = getattr(node, "end_lineno", node.lineno)
                func_lines = _code_line_count(lines, node.lineno - 1, end_line)
                param_count = len(node.args.args) + len(node.args.posonlyargs) + len(node.args.kwonlyargs)
                nesting = _max_nesting(node)

                if func_lines > LONG_FUNCTION_LINES:
                    findings.append(Finding(
                        rule=self.key,
                        message=f"Function '{node.name}' is {func_lines} lines (limit: {LONG_FUNCTION_LINES})",
                        file=rel_path,
                        line=node.lineno,
                        severity=Severity.MEDIUM,
                        metadata={"type": "long", "value": func_lines},
                    ))

                if param_count > HIGH_PARAM_COUNT:
                    findings.append(Finding(
                        rule=self.key,
                        message=f"Function '{node.name}' has {param_count} parameters (limit: {HIGH_PARAM_COUNT})",
                        file=rel_path,
                        line=node.lineno,
                        severity=Severity.LOW,
                        metadata={"type": "params", "value": param_count},
                    ))

                if nesting > DEEP_NESTING_DEPTH:
                    findings.append(Finding(
                        rule=self.key,
                        message=f"Function '{node.name}' has nesting depth {nesting} (limit: {DEEP_NESTING_DEPTH})",
                        file=rel_path,
                        line=node.lineno,
                        severity=Severity.MEDIUM,
                        metadata={"type": "nesting", "value": nesting},
                    ))

        return findings


def _code_line_count(lines: list[str], start: int, end: int) -> int:
    """Count non-blank, non-comment, non-docstring lines in a range."""
    count = 0
    in_docstring = False
    for i in range(start, min(end, len(lines))):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if stripped.startswith(('"""', "'''")):
            if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                continue  # Single-line docstring
            in_docstring = not in_docstring
            continue
        if in_docstring:
            continue
        if stripped.startswith("#"):
            continue
        count += 1
    return count


def _max_nesting(node: ast.AST, depth: int = 0) -> int:
    """Find maximum nesting depth within a function."""
    max_depth = depth
    nesting_nodes = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.ExceptHandler)

    for child in ast.iter_child_nodes(node):
        if isinstance(child, nesting_nodes):
            max_depth = max(max_depth, _max_nesting(child, depth + 1))
        else:
            max_depth = max(max_depth, _max_nesting(child, depth))

    return max_depth
