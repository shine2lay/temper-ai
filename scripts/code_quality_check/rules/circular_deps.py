"""Circular dependency detection — finds import cycles between modules."""

import ast

from scripts.code_quality_check.base import Finding, Rule, ScanContext, Severity


class CircularDepsRule(Rule):
    key = "circular_deps"
    title = "Circular Dependencies"
    severity = Severity.HIGH
    tags = ["structure"]

    def scan(self, ctx: ScanContext) -> list[Finding]:
        # Build module import graph
        graph: dict[str, set[str]] = {}
        src_name = ctx.src_dir.name

        for file_info in ctx.files:
            tree = ctx.ast_tree(file_info["abs_path"])
            if not tree:
                continue

            module = file_info["path"].replace("/", ".").removesuffix(".py").removesuffix(".__init__")
            graph.setdefault(module, set())

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(src_name + "."):
                            target = alias.name.removeprefix(src_name + ".")
                            graph[module].add(target)
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith(src_name + "."):
                        target = node.module.removeprefix(src_name + ".")
                        graph[module].add(target)

        # Detect cycles using DFS
        cycles = _find_cycles(graph)

        findings = []
        for cycle in cycles:
            cycle_str = " -> ".join(cycle)
            findings.append(Finding(
                rule=self.key,
                message=f"Circular import: {cycle_str}",
                file=cycle[0].replace(".", "/") + ".py",
                severity=Severity.HIGH,
                metadata={"cycle": cycle},
            ))

        return findings


def _find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Find all unique cycles in a directed graph using DFS."""
    cycles: list[list[str]] = []
    visited: set[str] = set()
    path: list[str] = []
    path_set: set[str] = set()

    def dfs(node: str) -> None:
        if node in path_set:
            # Found a cycle — extract it
            idx = path.index(node)
            cycle = path[idx:] + [node]
            # Normalize: start from lexically smallest to deduplicate
            min_idx = cycle.index(min(cycle[:-1]))
            normalized = cycle[min_idx:] + cycle[1:min_idx + 1]
            if normalized not in cycles:
                cycles.append(normalized)
            return

        if node in visited:
            return

        path.append(node)
        path_set.add(node)

        for neighbor in graph.get(node, set()):
            if neighbor in graph:  # only internal modules
                dfs(neighbor)

        path.pop()
        path_set.discard(node)
        visited.add(node)

    for node in graph:
        dfs(node)

    return cycles
