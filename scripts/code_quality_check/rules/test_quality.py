"""Test quality — detect tests with zero assertions."""

import ast

from scripts.code_quality_check.base import Finding, Rule, ScanContext, Severity


class TestQualityRule(Rule):
    key = "zero_assert_tests"
    title = "Test Quality"
    severity = Severity.LOW
    tags = ["testing"]

    def scan(self, ctx: ScanContext) -> list[Finding]:
        findings = []
        test_dir = ctx.src_dir.parent / "tests"

        if not test_dir.is_dir():
            return []

        for py_file in sorted(test_dir.rglob("*.py")):
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (OSError, SyntaxError):
                continue

            rel_path = str(py_file.relative_to(ctx.src_dir.parent))

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not node.name.startswith("test_"):
                    continue

                assert_count = _count_asserts(node)
                if assert_count == 0:
                    findings.append(Finding(
                        rule=self.key,
                        message=f"Test '{node.name}' has no assertions",
                        file=rel_path,
                        line=node.lineno,
                        severity=Severity.LOW,
                    ))

        return findings


def _count_asserts(func_node: ast.FunctionDef) -> int:
    """Count assert statements and pytest assertion method calls."""
    count = 0
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assert):
            count += 1
        elif isinstance(node, ast.Call):
            func = node.func
            # pytest.raises, .assert_called_once_with, etc.
            if isinstance(func, ast.Attribute):
                name = func.attr
                if name.startswith("assert") or name == "raises":
                    count += 1
    return count
