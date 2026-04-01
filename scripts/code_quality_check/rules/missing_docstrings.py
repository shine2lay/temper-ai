"""Missing docstrings — detect public classes without docstrings."""

import ast

from scripts.code_quality_check.base import Finding, Rule, ScanContext, Severity


class MissingDocstringsRule(Rule):
    key = "missing_docstrings"
    title = "Missing Docstrings"
    severity = Severity.LOW
    tags = ["documentation"]

    def scan(self, ctx: ScanContext) -> list[Finding]:
        findings = []

        for file_info in ctx.files:
            tree = ctx.ast_tree(file_info["abs_path"])
            if not tree:
                continue

            rel_path = file_info["path"]

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue

                # Skip private classes
                if node.name.startswith("_"):
                    continue

                if not ast.get_docstring(node):
                    findings.append(Finding(
                        rule=self.key,
                        message=f"Public class '{node.name}' has no docstring",
                        file=rel_path,
                        line=node.lineno,
                        severity=Severity.LOW,
                    ))

        return findings
