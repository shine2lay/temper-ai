"""Static pytest fixture uses, separate from ordinary file imports.

Conftests register optional fixtures; registration is not a use of every fixture body.
Keep dependencies of collection hooks/module-level expressions, then add each test's
requested and autouse fixture bodies (including their prerequisite fixtures). Module
imports through helpers such as tests/pgtier.py remain ordinary graph edges.

No pytest import or collection: selection must not execute application/test code.
Ambiguous names are unioned conservatively; unsupported dynamic requests cause the
caller to select everything, rather than silently drop an edge.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dependency_graph import References, RepoIndex

Function = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class Fixture:
    name: str
    autouse: bool
    requests: frozenset[str]
    references: References


@dataclass(frozen=True)
class FixtureModule:
    fixtures: tuple[Fixture, ...]
    requests: frozenset[str]
    collection: References
    # Repository helpers whose fixtures may be re-exported into this module.
    imports: tuple[tuple[str, int, str, str], ...]
    plugins: tuple[str, ...]
    uncertain: bool = False


def _text(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _names(target: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}


def _functions(tree: ast.Module | ast.ClassDef):
    # Do not mistake fixtures defined *inside* a test for fixtures of that test.
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node
        elif isinstance(node, ast.ClassDef):
            yield from _functions(node)


def _requests(node: ast.AST, *, parameters: bool = False) -> tuple[set[str], bool]:
    names: set[str] = set()
    uncertain = False
    if parameters and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        names.update(a.arg for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                     if a.arg not in {"self", "cls"})
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        method = child.func.attr if isinstance(child.func, ast.Attribute) else ""
        if method not in {"usefixtures", "getfixturevalue"}:
            continue
        for arg in child.args:
            value = _text(arg)
            if value is None:
                uncertain = True
            else:
                names.add(value)
        if not child.args or child.keywords:
            uncertain = True
    return names, uncertain


def parse_fixtures(tree: ast.Module, read: Callable[[ast.AST], References]) -> FixtureModule:
    """Parse one test/helper/conftest module using the graph's existing reference reader."""
    bindings: dict[str, list[ast.AST]] = defaultdict(list)
    imports: list[tuple[str, int, str, str]] = []
    fixture_aliases = {"fixture"}
    executed: list[ast.AST] = []
    plugins: list[str] = []
    uncertain = False
    for node in tree.body:
        if isinstance(node, ast.Import):
            executed.append(node)  # module imports execute even when a fixture is unused
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".")[0]].append(ast.Import(names=[alias]))
        elif isinstance(node, ast.ImportFrom):
            executed.append(node)
            for alias in node.names:
                bindings[alias.asname or alias.name].append(
                    ast.ImportFrom(module=node.module, level=node.level, names=[alias]))
                imports.append((node.module or "", node.level, alias.name, alias.asname or alias.name))
                if node.module in {"pytest", "pytest_asyncio"} and alias.name == "fixture":
                    fixture_aliases.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings[node.name].append(node)
            if node.name.startswith("pytest_") or isinstance(node, ast.ClassDef):
                executed.append(node)  # hooks run regardless of requested fixtures
            else:
                executed.extend(node.decorator_list)
                executed.extend(node.args.defaults)
                executed.extend(d for d in node.args.kw_defaults if d is not None)
        else:
            executed.append(node)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                assigned = set().union(*(_names(t) for t in targets))
                for name in assigned:
                    bindings[name].append(node)
                if "pytest_plugins" in assigned:
                    # Plugin collection and requested fixture bodies are separate graph
                    # edges; the literal must not also load every uncalled fixture body.
                    executed.remove(node)
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        value = None
                    if isinstance(value, str):
                        plugins.append(value)
                    elif isinstance(value, (tuple, list)) and all(isinstance(p, str) for p in value):
                        plugins.extend(value)
                    else:
                        uncertain = True

    def used_references(nodes: list[ast.AST]) -> References:
        chosen = list(nodes)
        pending = list(nodes)
        seen: set[str] = set()
        while pending:
            used = {n.id for root in pending for n in ast.walk(root)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)} - seen
            seen.update(used)
            pending = [binding for name in used for binding in bindings.get(name, ())]
            chosen.extend(pending)
        return read(ast.Module(body=chosen, type_ignores=[]))

    fixtures: list[Fixture] = []
    requests: set[str] = set()
    for node in _functions(tree):
        fixture_decorator: ast.AST | None = None
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if ((isinstance(target, ast.Attribute) and target.attr == "fixture")
                    or (isinstance(target, ast.Name) and target.id in fixture_aliases)):
                fixture_decorator = decorator
                break
        names, dynamic = _requests(node, parameters=True)
        if fixture_decorator is not None:
            name, autouse = node.name, False
            if isinstance(fixture_decorator, ast.Call):
                for kw in fixture_decorator.keywords:
                    if kw.arg == "name":
                        value = _text(kw.value)
                        if value is None:
                            uncertain = True
                        else:
                            name = value
                    elif kw.arg == "autouse":
                        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, bool):
                            autouse = kw.value.value
                        else:
                            uncertain = True
            fixtures.append(Fixture(name, autouse, frozenset(names), used_references([node])))
            uncertain |= dynamic
        elif node.name.startswith("test_"):
            requests.update(names)
            uncertain |= dynamic
    # Includes module/class usefixtures marks and helper request.getfixturevalue calls.
    explicit, dynamic = _requests(tree)
    requests.update(explicit)
    uncertain |= dynamic
    return FixtureModule(tuple(fixtures), frozenset(requests), used_references(executed),
                         tuple(imports), tuple(plugins), uncertain)


def _import_paths(path: str, module: str, level: int, name: str, index: RepoIndex) -> set[str]:
    package = path.rpartition("/")[0].replace("/", ".")
    if level:
        parts = package.split(".") if package else []
        parts = parts[:len(parts) - level + 1]
        module = ".".join([*parts, module] if module else parts)
    return index.module_files(module) | index.module_files(f"{module}.{name}")


def _visible_fixtures(test: str, index: RepoIndex, modules: Mapping[str, FixtureModule]) -> dict[str, list[tuple[str, Fixture]]]:
    visible: dict[str, list[tuple[str, Fixture]]] = defaultdict(list)
    sources = [p for p in modules if p == test or (
        p.endswith("/conftest.py") and test.startswith(p.rpartition("/")[0] + "/"))]
    visited: set[str] = set()

    def register(path: str) -> None:
        if path in visited or path not in modules:
            return
        visited.add(path)
        info = modules[path]
        for fixture in info.fixtures:
            visible[fixture.name].append((path, fixture))
        for module, level, name, alias in info.imports:
            for source in _import_paths(path, module, level, name, index):
                if source not in modules:
                    continue
                register(source)
                if alias != name:
                    visible[alias].extend((source, f) for f in modules[source].fixtures if f.name == name)
        for plugin in info.plugins:
            for source in index.module_files(plugin):
                register(source)

    for source in sources:
        register(source)
    return visible


def fixture_uses(index: RepoIndex, modules: Mapping[str, FixtureModule], tests: set[str]) -> dict[str, list[tuple[str, Fixture]]]:
    """Per test file, the visible requested/autouse fixture definitions, transitively.

    Resolve in the consumer's scope (as pytest does), not the provider's folder.
    Union overrides conservatively, including classes in the same file. No same-name
    fixture in a sibling folder is visible unless explicitly imported as a plugin.
    """
    result: dict[str, list[tuple[str, Fixture]]] = {}
    for test in sorted(tests):
        visible = _visible_fixtures(test, index, modules)
        pending = set(modules[test].requests) if test in modules else set()
        pending.update(name for name, definitions in visible.items() if any(f.autouse for _, f in definitions))
        seen: set[str] = set()
        uses: list[tuple[str, Fixture]] = []
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            for source, fixture in visible.get(name, ()):
                uses.append((source, fixture))
                pending.update(fixture.requests - seen)
        result[test] = uses
    return result
