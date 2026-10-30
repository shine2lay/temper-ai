"""Resolve FastAPI bindings in an already admitted source/AST index.

Never read files, search sys.path, or import application code. Package roots
come from admitted __init__.py files and src/backend layouts. Ambiguous modules
and unsupported writes/imports resolve to nothing. A function parameter needs
consistent explicit router arguments at direct same-file calls; annotations,
factory returns, argument expansion and include-router prefixes are not evaluated.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

Scope = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class Router:
    prefix: str
    tag: str


@dataclass(frozen=True)
class _Module:
    # None is the known external fastapi module, never an imported Python object.
    path: Path | None


@dataclass(frozen=True)
class _Constructor:
    pass


@dataclass(frozen=True)
class _Function:
    scope: ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class _Call:
    scope: Scope
    statement_index: int
    expression: ast.Call


Value = Router | _Module | _Constructor | _Function | None
ActiveBindings = frozenset[tuple[Scope, str, int]]
_CONSTRUCTORS = {"APIRouter", "FastAPI"}
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _written_names(node: ast.AST) -> set[str]:
    """Names invalidated by a statement, without entering its nested scopes."""
    if isinstance(node, (*_FUNCTIONS, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {
            alias.asname or (alias.name.split('.')[0] if isinstance(node, ast.Import) else alias.name)
            for alias in node.names
        }
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return {node.id}
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
        base = node.value
        while isinstance(base, ast.Attribute):
            base = base.value
        return {base.id} if isinstance(base, ast.Name) else set()
    if isinstance(node, ast.ExceptHandler):
        names = {node.name} if node.name else set()
    elif isinstance(node, (ast.MatchAs, ast.MatchStar)):
        names = {node.name} if node.name else set()
    elif isinstance(node, ast.MatchMapping):
        names = {node.rest} if node.rest else set()
    elif isinstance(node, (ast.Global, ast.Nonlocal)):
        names = set(node.names)
    else:
        names = set()
    for child in ast.iter_child_nodes(node):
        names.update(_written_names(child))
    return names


def _calls_in(node: ast.AST):
    """Call sites in this lexical scope, not bodies of nested scopes."""
    if isinstance(node, (*_FUNCTIONS, ast.ClassDef, ast.Lambda)):
        return
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        yield node
    for child in ast.iter_child_nodes(node):
        yield from _calls_in(child)


class RouterBindings:
    """One source/module/scope index, shared by all router lookups.

    Assignments/imports are ordered: rebinding does not change an earlier
    decorator. Imported exports use the destination's final binding. Conditional
    writes are unknown. Structural cycle detection covers re-exports and local
    parameter forwarding. Nested declarations are read, not invoked; runtime
    factory return values and classes are outside this analysis.
    """

    def __init__(self, sources: Mapping[Path, ast.Module]):
        self.sources = sources
        self.packages = {parent for path in sources for parent in path.parents if parent != Path('.')}
        roots = {Path('.')}
        for path in sources:
            parent = path.parent
            # Top of an explicit package chain, not every possible suffix.
            if parent / '__init__.py' in sources:
                while parent / '__init__.py' in sources and parent != Path('.'):
                    parent = parent.parent
                roots.add(parent)
            roots.update(parent for parent in path.parents if parent.name in {'src', 'backend'})
        self.roots = roots
        self.modules: dict[str, set[Path]] = defaultdict(set)
        for path in sources:
            for root in roots:
                if not path.is_relative_to(root):
                    continue
                relative = path.relative_to(root)
                parts = relative.with_suffix('').parts
                if parts[-1] == '__init__':
                    parts = parts[:-1]
                if not parts or not all(part.isidentifier() for part in parts):
                    continue
                destination = path.parent if path.name == '__init__.py' else path
                self.modules['.'.join(parts)].add(destination)
                for length in range(1, len(relative.parts)):
                    self.modules['.'.join(relative.parts[:length])].add(root.joinpath(*relative.parts[:length]))

        self.paths: dict[Scope, Path] = {}
        self.parents: dict[Scope, Scope] = {}
        self.bindings: dict[Scope, dict[str, list[tuple[int, ast.stmt | None]]]] = {}
        self.parameters: dict[Scope, set[str]] = {}
        self.calls: dict[tuple[Path, str], list[_Call]] = defaultdict(list)
        for path, tree in sources.items():
            self._index_scope(path, tree)

    def _index_scope(self, path: Path, scope: Scope) -> None:
        self.paths[scope] = path
        names: dict[str, list[tuple[int, ast.stmt | None]]] = defaultdict(list)
        self.bindings[scope] = names
        if isinstance(scope, _FUNCTIONS):
            args = scope.args
            self.parameters[scope] = {arg.arg for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
            self.parameters[scope].update(arg.arg for arg in [args.vararg, args.kwarg] if arg)
        for index, statement in enumerate(scope.body):
            supported = isinstance(statement, (ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom, *_FUNCTIONS))
            for name in _written_names(statement):
                names[name].append((index, statement if supported else None))
            for call in _calls_in(statement):
                self.calls[path, call.func.id].append(_Call(scope, index, call))
            if isinstance(statement, _FUNCTIONS):
                self.parents[statement] = scope
                self._index_scope(path, statement)

    def router(self, scope: Scope, expression: ast.expr, statement_index: int) -> Router | None:
        value = self._expression(scope, expression, statement_index, frozenset())
        return value if isinstance(value, Router) else None

    def _module(self, name: str) -> _Module | None:
        parts = name.split('.')
        # Even a unique leaf is unsafe if its parent could mean two packages.
        for length in range(1, len(parts) + 1):
            if len(self.modules.get('.'.join(parts[:length]), ())) != 1:
                if parts[0] == 'fastapi' and 'fastapi' not in self.modules and name == 'fastapi':
                    return _Module(None)
                return None
        return _Module(next(iter(self.modules[name])))

    def _relative_module(self, path: Path, node: ast.ImportFrom) -> _Module | None:
        root = max((root for root in self.roots if path.is_relative_to(root)), key=lambda p: len(p.parts))
        parent = path.parent
        if node.level > len(parent.relative_to(root).parts):
            return None
        for _ in range(node.level - 1):
            parent = parent.parent
        if node.module:
            parent = parent.joinpath(*node.module.split('.'))
        return self._module_at(parent)

    def _module_at(self, base: Path) -> _Module | None:
        choices = []
        if base in self.packages:
            choices.append(base)
        if base.with_suffix('.py') in self.sources:
            choices.append(base.with_suffix('.py'))
        return _Module(choices[0]) if len(choices) == 1 else None

    def _attribute(self, module: _Module, name: str, active: ActiveBindings) -> Value:
        if module.path is None:
            return _Constructor() if name in _CONSTRUCTORS else None
        path = module.path
        source = path if path in self.sources else path / '__init__.py'
        if source in self.sources:
            scope = self.sources[source]
            if name in self.bindings[scope] or '*' in self.bindings[scope]:
                return self._name(scope, name, len(scope.body), active)
        if path in self.packages:
            return self._module_at(path / name)
        return None

    def _name(self, scope: Scope, name: str, before: int, active: ActiveBindings) -> Value:
        events = self.bindings[scope]
        previous = next((event for event in reversed(events.get(name, [])) if event[0] < before), None)
        wildcard = next((event for event in reversed(events.get('*', [])) if event[0] < before), None)
        if wildcard and (previous is None or wildcard[0] > previous[0]):
            return None
        token = (scope, name, previous[0] if previous else -1)
        if token in active:
            return None
        active = active | {token}
        if previous is None:
            if name in self.parameters.get(scope, ()):
                return self._parameter(scope, name, active)
            if scope in self.parents:
                # A local write shadows an outer binding even before assignment.
                if name in events:
                    return None
                parent = self.parents[scope]
                # A free variable with multiple observed writes is not stable.
                if len(self.bindings[parent].get(name, ())) > 1:
                    return None
                return self._name(parent, name, len(parent.body), active)
            # Preserve the original probe's bare same-file constructor spelling.
            return _Constructor() if name in _CONSTRUCTORS else None
        index, statement = previous
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
                # FastAPI's application state holds arbitrary caller data, not
                # router bindings. A state-field write does not rebind the app.
                value = self._name(scope, name, index, active)
                if isinstance(value, Router) and all(self._state_field(target, name) for target in targets):
                    return value
                return None
            return self._expression(scope, statement.value, index, active)
        if isinstance(statement, _FUNCTIONS):
            return _Function(statement) if not statement.decorator_list else None
        if isinstance(statement, ast.Import):
            alias = next(alias for alias in statement.names if (alias.asname or alias.name.split('.')[0]) == name)
            # `import package.module` binds package, but still requires its leaf.
            leaf = self._module(alias.name)
            return leaf if alias.asname else self._module(name) if leaf else None
        if isinstance(statement, ast.ImportFrom):
            alias = next(alias for alias in statement.names if (alias.asname or alias.name) == name)
            module = self._relative_module(self.paths[scope], statement) if statement.level else self._module(statement.module or '')
            return self._attribute(module, alias.name, active) if module else None
        return None

    def _parameter(self, scope: Scope, name: str, active: ActiveBindings) -> Router | None:
        if not isinstance(scope, _FUNCTIONS):
            return None
        found: Router | None = None
        for site in self.calls.get((self.paths[scope], scope.name), ()):
            callee = self._expression(site.scope, site.expression.func, site.statement_index, active)
            if not isinstance(callee, _Function):
                # An unresolved same-name call must not be assumed unrelated.
                return None
            if callee.scope is not scope:
                continue
            argument = self._argument(scope.args, site.expression, name)
            value = self._expression(site.scope, argument, site.statement_index, active)
            if not isinstance(value, Router) or (found is not None and found != value):
                return None
            found = value
        return found

    @staticmethod
    def _state_field(target: ast.expr, name: str) -> bool:
        if not isinstance(target, ast.Attribute) or not isinstance(target.value, ast.Attribute):
            return False
        base = target.value
        while isinstance(base.value, ast.Attribute):
            base = base.value
        return base.attr == 'state' and isinstance(base.value, ast.Name) and base.value.id == name

    @staticmethod
    def _argument(signature: ast.arguments, call: ast.Call, name: str) -> ast.expr | None:
        positional = [*signature.posonlyargs, *signature.args]
        if len(call.args) > len(positional) or any(isinstance(arg, ast.Starred) for arg in call.args):
            return None
        arguments = {param.arg: value for param, value in zip(positional, call.args, strict=False)}
        keyword_names = {param.arg for param in [*signature.args, *signature.kwonlyargs]}
        for keyword in call.keywords:
            if keyword.arg not in keyword_names or keyword.arg in arguments:
                return None  # Includes **kwargs, unknown names and duplicate values.
            arguments[keyword.arg] = keyword.value
        required = {param.arg for param in positional[:len(positional) - len(signature.defaults)]}
        required.update(param.arg for param, default in zip(signature.kwonlyargs, signature.kw_defaults, strict=True) if default is None)
        if not required.issubset(arguments):
            return None
        # A default/variadic router argument is deliberately not inferred.
        return arguments.get(name)

    def _expression(self, scope: Scope, expression: ast.expr | None, before: int, active: ActiveBindings) -> Value:
        if isinstance(expression, ast.Name):
            return self._name(scope, expression.id, before, active)
        if isinstance(expression, ast.Attribute):
            module = self._expression(scope, expression.value, before, active)
            return self._attribute(module, expression.attr, active) if isinstance(module, _Module) else None
        if isinstance(expression, ast.Call):
            constructor = self._expression(scope, expression.func, before, active)
            if not isinstance(constructor, _Constructor):
                return None
            prefix, tag = '', ''
            for keyword in expression.keywords:
                if keyword.arg == 'prefix':
                    prefix = keyword.value.value if isinstance(keyword.value, ast.Constant) else '?'
                    prefix = str(prefix)
                elif keyword.arg == 'tags' and isinstance(keyword.value, ast.List) and keyword.value.elts:
                    first = keyword.value.elts[0]
                    if isinstance(first, ast.Constant):
                        tag = str(first.value)
            return Router(prefix, tag)
        return None
