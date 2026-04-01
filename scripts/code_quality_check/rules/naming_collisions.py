"""Naming collisions — detect classes with the same name in different modules."""

import ast
from collections import defaultdict

from scripts.code_quality_check.base import Finding, Rule, ScanContext, Severity


class NamingCollisionsRule(Rule):
    key = "naming_collisions"
    title = "Naming Collisions"
    severity = Severity.MEDIUM
    tags = ["structure"]

    def scan(self, ctx: ScanContext) -> list[Finding]:
        # Collect all class names and their locations
        classes: dict[str, list[dict]] = defaultdict(list)

        for file_info in ctx.files:
            tree = ctx.ast_tree(file_info["abs_path"])
            if not tree:
                continue

            # Skip __init__.py (re-exports are fine)
            if file_info["path"].endswith("__init__.py"):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    classes[node.name].append({
                        "file": file_info["path"],
                        "line": node.lineno,
                    })

        # Find names defined in multiple files
        findings = []
        for name, locations in sorted(classes.items()):
            if len(locations) <= 1:
                continue

            files = [loc["file"] for loc in locations]
            findings.append(Finding(
                rule=self.key,
                message=f"Class '{name}' defined in {len(locations)} files: {', '.join(files)}",
                file=locations[0]["file"],
                line=locations[0]["line"],
                severity=Severity.MEDIUM,
                metadata={"class": name, "locations": locations},
            ))

        return findings
