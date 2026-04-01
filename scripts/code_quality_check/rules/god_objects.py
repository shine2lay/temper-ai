"""God objects — detect oversized classes and files."""

import ast

from scripts.code_quality_check.base import Finding, Rule, ScanContext, Severity

GOD_CLASS_LINES = 500
GOD_CLASS_METHODS = 20
LARGE_FILE_LINES = 500


class GodObjectsRule(Rule):
    key = "god_objects"
    title = "God Objects"
    severity = Severity.HIGH
    tags = ["structure"]

    def scan(self, ctx: ScanContext) -> list[Finding]:
        findings = []

        for file_info in ctx.files:
            tree = ctx.ast_tree(file_info["abs_path"])
            source = ctx.source(file_info["abs_path"])
            if not tree:
                continue

            rel_path = file_info["path"]
            lines = source.split("\n")

            # God classes
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue

                # Check suppression
                if node.lineno <= len(lines):
                    def_line = lines[node.lineno - 1]
                    if "# noqa" in def_line and "god" in def_line.lower():
                        continue

                end_line = getattr(node, "end_lineno", node.lineno)
                line_span = end_line - node.lineno + 1
                method_count = sum(
                    1 for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                )

                reason = None
                if line_span >= GOD_CLASS_LINES:
                    reason = f"{line_span} lines (limit: {GOD_CLASS_LINES})"
                elif method_count >= GOD_CLASS_METHODS:
                    reason = f"{method_count} methods (limit: {GOD_CLASS_METHODS})"

                if reason:
                    findings.append(Finding(
                        rule=self.key,
                        message=f"God class '{node.name}': {reason}",
                        file=rel_path,
                        line=node.lineno,
                        severity=Severity.HIGH,
                        metadata={"class": node.name, "lines": line_span, "methods": method_count},
                    ))

            # Large files
            if file_info["lines"] >= LARGE_FILE_LINES:
                findings.append(Finding(
                    rule=self.key,
                    message=f"Large file: {file_info['lines']} lines (limit: {LARGE_FILE_LINES})",
                    file=rel_path,
                    line=0,
                    severity=Severity.MEDIUM,
                    metadata={"lines": file_info["lines"]},
                ))

        return findings
