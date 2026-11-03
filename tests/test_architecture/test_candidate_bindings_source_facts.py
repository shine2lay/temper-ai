"""Candidate bindings stay unset in the source (#125: Security O-466-3, R-125-1, R-125-2, R-125-3).

While P3 host writes are off, no production code may build, store or hand on candidate bindings. These tests
check that as facts over the source of temper_ai/, configs/, scripts/, p3_host_contracts/ and p3_source_closure/
(outside temper_ai/p3_authority/, which defines the types). Each fact has planted twins the check must report
exactly once under that fact's rule, and clean twins it must pass.

1. Every candidate_bindings parameter, of a function or a lambda, is keyword-only and defaults to None; no *args or
   **kwargs takes that name.
2. A value handed on (a candidate_bindings= keyword, a "candidate_bindings" dict key, or bindings= to
   submit_candidate) is the calling function's own untouched candidate_bindings parameter, and nothing is splatted
   into submit_candidate. The one exception is routes._start_run's `bindings = _candidate_bindings()`: a direct
   statement of _start_run's body, placed before the statement holding the call, and the value's only binding
   there (its name is no parameter of _start_run and is not declared global or nonlocal in it).
3. Nothing stores candidate_bindings: no attribute store, no module- or class-level name of that name (a field
   left None or only declared included), no global declaration; and the string "candidate_bindings" appears only
   as a .get/getattr/hasattr read or as a dict key fact 2 checks, so setattr, setdefault, setitem, subscript
   stores and dict(zip(...)) are all seen.
4. Only configs/architecture/bin/first_app_p3_native.py names the P3 composition types and composers (as a name,
   an attribute, an import, or a getattr/hasattr string).
5. submit_candidate appears only as a direct call's function or a plain un-aliased import.
6. The state reader that fact 2's exception trusts is pinned: in temper_ai/api/routes.py the only binding of
   _candidate_bindings is one undecorated plain module-level def with no parameters and no yield or await, every
   return in it gives None or vars(S).get("candidate_bindings"), where S is _state() or a name the reader binds
   exactly once, by S = _state(), and declares neither global nor nonlocal; _state is one undecorated plain
   module-level def there; vars is not rebound there, and no scanned code imports builtins or names __builtins__.
   With fact 3 holding, that read gives None.
7. Nothing shadows or replaces the state reader: the name _candidate_bindings appears only in routes.py, as that
   def and as the function of calls with no arguments. No parameter, attribute, keyword, import, def, class,
   capture, global or nonlocal declaration or string of that name appears anywhere scanned.

Not seen: names built at run time (setattr(obj, name, ...), import_module strings), values loaded from data at run
time, string annotations, an attribute named _state set on the routes module from elsewhere (_state is a common
attribute name, so it is not banned), and positional passes to a parameter of another name
(is_designated(workflow, bindings) only reads; submit_candidate takes bindings keyword-only).
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCANNED_TOPS = ("temper_ai", "configs", "scripts", "p3_host_contracts", "p3_source_closure")
_P3_AUTHORITY_DIR = _ROOT / "temper_ai" / "p3_authority"
_RUNNER_ENTRY_POINTS = {
    ("temper_ai.runner.execute", "execute_workflow"),
    ("temper_ai.cli.run_workflow", "cmd_run_workflow"),
    ("temper_ai.cli.watch_queue", "_scan_and_dispatch"),
    ("temper_ai.cli.watch_queue", "_claim_row"),
    ("temper_ai.cli.main", "_cmd_validate"),
}
_BINDINGS = "candidate_bindings"
# The one module allowed to name the P3 composition types and composers: the disabled consumer, which refuses writes.
_REFERENCE_ALLOWED_FILE = "configs/architecture/bin/first_app_p3_native.py"
_PROTECTED_NAMES = frozenset(
    {
        "P3CandidateBindings",
        "P3AuthorityComposition",
        "P3AuthorityService",
        "compose_p3_authority",
        "compose_disabled_consumer_service",
    }
)
# Admission's entry, which takes the bindings as bindings=.
_ADMISSION_ENTRY = "submit_candidate"
# The one place that reads bindings off the server's state and hands them to admission (facts 2 and 6).
_STATE_READER_FILE = "temper_ai/api/routes.py"
_STATE_READER_CALLER = "_start_run"
_STATE_READER = "_candidate_bindings"
# The server-state getter the reader's vars() argument must come from (fact 6).
_STATE_GETTER = "_state"
_NAME_LOOKUP_CALLS = {"getattr", "hasattr"}
_BUILTINS_MODULE = "builtins"
_BUILTINS_NAME = "__builtins__"

_DEFAULT_RULE = "candidate_bindings must be keyword-only and default to None"
_PASS_THROUGH_RULE = "is not its own untouched parameter"
_STORE_RULE = "stores candidate_bindings"
_REFERENCE_RULE = "named outside first_app_p3_native.py"
_DIRECT_CALL_RULE = "other than as a direct call"
_READER_RULE = "state reader not pinned"
_READER_NAME_RULE = "names _candidate_bindings outside its def and no-argument calls in routes.py"
# No rule text holds another, so each report names exactly one rule.
_RULES = (
    _DEFAULT_RULE,
    _PASS_THROUGH_RULE,
    _STORE_RULE,
    _REFERENCE_RULE,
    _DIRECT_CALL_RULE,
    _READER_RULE,
    _READER_NAME_RULE,
)


def _production_sources():
    for top in _SCANNED_TOPS:
        for path in sorted((_ROOT / top).rglob("*.py")):
            if _P3_AUTHORITY_DIR in path.parents or "__pycache__" in path.parts:
                continue
            yield path.relative_to(_ROOT).as_posix(), path.read_text(encoding="utf-8")


def _parameter_defaults(node):
    args = node.args
    positional = args.posonlyargs + args.args
    padded = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    return list(zip(positional, padded, strict=True)) + list(zip(args.kwonlyargs, args.kw_defaults, strict=True))


def _all_parameters(node) -> list[ast.arg]:
    args = node.args
    stars = [star for star in (args.vararg, args.kwarg) if star is not None]
    return args.posonlyargs + args.args + args.kwonlyargs + stars


def _name_bindings(scope, name):
    """Every node inside scope (a function or a module) that binds name: a store or delete (any assignment, loop,
    with, comprehension), an except or match capture, an import alias, or a definition. A parameter is not one."""
    found = []
    for node in ast.walk(scope):
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del)):
            found.append(node)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name == name:
            found.append(node)
        elif isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) == name:
            found.append(node)
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node is not scope
            and node.name == name
        ):
            found.append(node)
    return found


def _callee(func):
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None


def _is_literal(node, text: str) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == text


def _is_no_argument_call(node, function: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == function
        and not node.args
        and not node.keywords
    )


def _is_module_level_def(tree: ast.Module, name: str) -> tuple[bool, int]:
    """Whether name's only binding in the module is one undecorated plain module-level def, and how many bindings
    it has."""
    bindings = _name_bindings(tree, name)
    only = bindings[0] if len(bindings) == 1 else None
    return isinstance(only, ast.FunctionDef) and only in tree.body and not only.decorator_list, len(bindings)


def _is_state_object(node, reader) -> bool:
    """_state() itself, or a name the reader binds exactly once, by name = _state(), and declares neither global nor
    nonlocal."""
    if _is_no_argument_call(node, _STATE_GETTER):
        return True
    if not isinstance(node, ast.Name) or any(
        isinstance(statement, (ast.Global, ast.Nonlocal)) and node.id in statement.names
        for statement in ast.walk(reader)
    ):
        return False
    bindings = _name_bindings(reader, node.id)
    return len(bindings) == 1 and any(
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and statement.targets[0] is bindings[0]
        and _is_no_argument_call(statement.value, _STATE_GETTER)
        for statement in ast.walk(reader)
    )


def _is_state_read(node, reader) -> bool:
    """True for vars(S).get("candidate_bindings") with S the server's state (see _is_state_object), nothing else."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
        return False
    target = node.func.value
    return (
        isinstance(target, ast.Call)
        and isinstance(target.func, ast.Name)
        and target.func.id == "vars"
        and len(target.args) == 1
        and not target.keywords
        and _is_state_object(target.args[0], reader)
        and len(node.args) == 1
        and _is_literal(node.args[0], _BINDINGS)
        and not node.keywords
    )


def _state_reader_violations(name: str, tree: ast.Module) -> list[str]:
    """Fact 6, checked in routes.py only: the reader fact 2's exception trusts can only read the state."""
    if name != _STATE_READER_FILE:
        return []
    pinned, count = _is_module_level_def(tree, _STATE_READER)
    if not pinned:
        return [
            f"{name}: {_READER_RULE}: {_STATE_READER} must be one undecorated plain module-level def,"
            f" never rebound or imported ({count} binding(s) found)"
        ]
    reader = _name_bindings(tree, _STATE_READER)[0]
    found = []
    if _all_parameters(reader):
        found.append(f"{name}:{reader.lineno}: {_READER_RULE}: it must take no parameters")
    for node in ast.walk(reader):
        if isinstance(node, (ast.Yield, ast.YieldFrom, ast.Await)):
            found.append(f"{name}:{node.lineno}: {_READER_RULE}: it must not yield or await")
        elif isinstance(node, ast.Return) and not (
            node.value is None or (isinstance(node.value, ast.Constant) and node.value.value is None)
            or _is_state_read(node.value, reader)
        ):
            found.append(
                f"{name}:{node.lineno}: {_READER_RULE}: it must return None or"
                f" vars(_state()).get('candidate_bindings'), not {ast.unparse(node.value)}"
            )
    getter_pinned, getter_count = _is_module_level_def(tree, _STATE_GETTER)
    if not getter_pinned:
        found.append(
            f"{name}: {_READER_RULE}: {_STATE_GETTER} must be one undecorated plain module-level def"
            f" ({getter_count} binding(s) found)"
        )
    if _name_bindings(tree, "vars"):
        found.append(f"{name}: {_READER_RULE}: vars is rebound")
    return found


class _CandidateBindingFacts(ast.NodeVisitor):
    """Collect one file's breaks of facts 1-5 (see the module docstring), plus every function that takes
    candidate_bindings."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.functions: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda] = []
        self.scopes: list[str] = ["module"]
        self.violations: list[str] = []
        self.takes_bindings: set[str] = set()
        self._allowed_literals: set[int] = set()
        self._direct_calls: set[int] = set()
        self._reader_calls: set[int] = set()

    def _report(self, node, text: str) -> None:
        self.violations.append(f"{self.name}:{node.lineno}: {text}")

    def _own_function(self):
        return self.functions[-1] if self.functions else None

    def _passes_own_parameter(self, value) -> bool:
        own = self._own_function()
        return (
            isinstance(value, ast.Name)
            and value.id == _BINDINGS
            and own is not None
            and any(arg.arg == _BINDINGS for arg, _ in _parameter_defaults(own))
            and not _name_bindings(own, _BINDINGS)
        )

    def _passes_state_reader(self, value) -> bool:
        """Fact 2's one exception: in routes._start_run, value names a local bound exactly once, by a direct
        `name = _candidate_bindings()` statement of its body placed before the statement holding this use."""
        own = self._own_function()
        if (
            own is None
            or (self.name, getattr(own, "name", None)) != (_STATE_READER_FILE, _STATE_READER_CALLER)
            or not isinstance(value, ast.Name)
            or value.id in {arg.arg for arg in _all_parameters(own)}
            or any(
                isinstance(node, (ast.Global, ast.Nonlocal)) and value.id in node.names for node in ast.walk(own)
            )
        ):
            return False
        bindings = _name_bindings(own, value.id)
        if len(bindings) != 1:
            return False
        assigned = next(
            (
                index
                for index, statement in enumerate(own.body)
                if isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and statement.targets[0] is bindings[0]
                and _is_no_argument_call(statement.value, _STATE_READER)
            ),
            None,
        )
        used = next(
            (
                index
                for index, statement in enumerate(own.body)
                if any(node is value for node in ast.walk(statement))
            ),
            None,
        )
        return assigned is not None and used is not None and assigned < used

    def _names_reader(self, node, how: str) -> None:
        self._report(node, f"{how} {_READER_NAME_RULE}")

    def _reader_use_allowed(self, node: ast.Name) -> bool:
        """In routes.py fact 6 owns every binding of the reader's name; a load there is allowed only as the function
        of a call with no arguments. Anywhere else the name is not allowed at all."""
        if self.name != _STATE_READER_FILE:
            return False
        return not isinstance(node.ctx, ast.Load) or id(node) in self._reader_calls

    def _swaps_builtins(self, node, how: str) -> None:
        self._report(node, f"{_READER_RULE}: {how} can swap the vars the state reader calls")

    def _reference(self, node, name: str) -> None:
        if name in _PROTECTED_NAMES and self.name != _REFERENCE_ALLOWED_FILE:
            self._report(node, f"{name} {_REFERENCE_RULE}")
        if name == _ADMISSION_ENTRY and id(node) not in self._direct_calls:
            self._report(node, f"{_ADMISSION_ENTRY} used {_DIRECT_CALL_RULE}")

    def _store(self, target) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._store(element)
        elif isinstance(target, ast.Starred):
            self._store(target.value)
        elif isinstance(target, ast.Attribute) and target.attr == _BINDINGS:
            self._report(target, f"{ast.unparse(target)} = ... {_STORE_RULE}")
        elif isinstance(target, ast.Name) and target.id == _BINDINGS and self.scopes[-1] != "function":
            self._report(target, f"a module- or class-level candidate_bindings name {_STORE_RULE}")

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._store(target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._store(node.target)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._store(node.target)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._store(node.target)
        self.generic_visit(node)

    def _loop(self, node) -> None:
        self._store(node.target)
        self.generic_visit(node)

    visit_For = _loop
    visit_AsyncFor = _loop
    visit_comprehension = _loop

    def _with(self, node) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._store(item.optional_vars)
        self.generic_visit(node)

    visit_With = _with
    visit_AsyncWith = _with

    def _declares(self, node) -> None:
        if _STATE_READER in node.names and self.name != _STATE_READER_FILE:
            self._names_reader(node, f"a {type(node).__name__.lower()} declaration of {_STATE_READER}")

    def visit_Global(self, node: ast.Global) -> None:
        if _BINDINGS in node.names:
            self._report(node, f"global candidate_bindings {_STORE_RULE}")
        self._declares(node)
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self._declares(node)
        self.generic_visit(node)

    def _capture(self, node) -> None:
        if node.name == _STATE_READER and self.name != _STATE_READER_FILE:
            self._names_reader(node, f"a capture named {_STATE_READER}")
        self.generic_visit(node)

    visit_ExceptHandler = _capture
    visit_MatchAs = _capture
    visit_MatchStar = _capture

    def visit_Constant(self, node: ast.Constant) -> None:
        if _is_literal(node, _BINDINGS) and id(node) not in self._allowed_literals:
            self._report(node, f"'candidate_bindings' outside a .get/getattr/hasattr read or a checked dict key {_STORE_RULE}")
        elif _is_literal(node, _STATE_READER):
            self._names_reader(node, f"the string '{_STATE_READER}'")
        elif _is_literal(node, _BUILTINS_NAME):
            self._swaps_builtins(node, f"the string '{_BUILTINS_NAME}'")

    def visit_Name(self, node: ast.Name) -> None:
        self._reference(node, node.id)
        if node.id == _STATE_READER and not self._reader_use_allowed(node):
            self._names_reader(node, f"a {type(node.ctx).__name__.lower()} of {_STATE_READER}")
        elif node.id == _BUILTINS_NAME:
            self._swaps_builtins(node, _BUILTINS_NAME)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._reference(node, node.attr)
        if node.attr == _STATE_READER:
            self._names_reader(node, f"the attribute {ast.unparse(node)}")
        elif node.attr == _BUILTINS_NAME:
            self._swaps_builtins(node, f"the attribute {ast.unparse(node)}")
        self.generic_visit(node)

    def visit_alias(self, node: ast.alias) -> None:
        bound = node.asname or node.name.split(".")[0]
        if node.name.split(".")[0] == _BUILTINS_MODULE:
            self._swaps_builtins(node, f"an import of {node.name}")
        if _STATE_READER in (bound, node.name.split(".")[-1]) and not (
            self.name == _STATE_READER_FILE and bound == _STATE_READER
        ):
            self._names_reader(node, f"an import of {node.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == _BUILTINS_MODULE:
            self._swaps_builtins(node, f"from {_BUILTINS_MODULE} import")
        for alias in node.names:
            if alias.name in _PROTECTED_NAMES and self.name != _REFERENCE_ALLOWED_FILE:
                self._report(node, f"{alias.name} {_REFERENCE_RULE}")
            if alias.name == _ADMISSION_ENTRY and alias.asname not in (None, _ADMISSION_ENTRY):
                self._report(node, f"{_ADMISSION_ENTRY} imported as {alias.asname}: used {_DIRECT_CALL_RULE}")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name == _STATE_READER and self.name != _STATE_READER_FILE:
            self._names_reader(node, f"a class named {_STATE_READER}")
        self.scopes.append("class")
        self.generic_visit(node)
        self.scopes.pop()

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values, strict=True):
            if not _is_literal(key, _BINDINGS):
                continue
            self._allowed_literals.add(id(key))
            if not self._passes_own_parameter(value):
                self._report(node, f"{{'candidate_bindings': {ast.unparse(value)}}} {_PASS_THROUGH_RULE}")
        self.generic_visit(node)

    def _function(self, node) -> None:
        label = getattr(node, "name", "<lambda>")
        keyword_only = {id(arg) for arg in node.args.kwonlyargs}
        for arg, default in _parameter_defaults(node):
            if arg.arg != _BINDINGS:
                continue
            self.takes_bindings.add(label)
            if id(arg) not in keyword_only or not (isinstance(default, ast.Constant) and default.value is None):
                self.violations.append(f"{self.name}:{node.lineno} {label}: {_DEFAULT_RULE}")
        for star in (node.args.vararg, node.args.kwarg):
            if star is not None and star.arg == _BINDINGS:
                self.violations.append(f"{self.name}:{node.lineno} {label}: a starred {star.arg}: {_DEFAULT_RULE}")
        if label == _STATE_READER and self.name != _STATE_READER_FILE:
            self._names_reader(node, f"a def named {_STATE_READER}")
        for arg in _all_parameters(node):
            if arg.arg == _STATE_READER:
                self._names_reader(arg, f"a parameter named {_STATE_READER}")
        self.functions.append(node)
        self.scopes.append("function")
        self.generic_visit(node)
        self.scopes.pop()
        self.functions.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function
    visit_Lambda = _function

    def visit_Call(self, node: ast.Call) -> None:
        callee = _callee(node.func)
        if callee == _ADMISSION_ENTRY:
            self._direct_calls.add(id(node.func))
        if _is_no_argument_call(node, _STATE_READER):
            self._reader_calls.add(id(node.func))
        for keyword in node.keywords:
            value = keyword.value
            if keyword.arg == _STATE_READER:
                self._names_reader(node, f"the keyword {_STATE_READER}=")
            if keyword.arg == _BINDINGS and not self._passes_own_parameter(value):
                self._report(node, f"candidate_bindings={ast.unparse(value)} {_PASS_THROUGH_RULE}")
            if callee != _ADMISSION_ENTRY:
                continue
            if keyword.arg is None:
                self._report(node, f"submit_candidate(**{ast.unparse(value)}) hides bindings: {_PASS_THROUGH_RULE}")
            elif keyword.arg == "bindings" and not (
                self._passes_own_parameter(value) or self._passes_state_reader(value)
            ):
                self._report(
                    node, f"submit_candidate(bindings={ast.unparse(value)}) {_PASS_THROUGH_RULE} or the state reader"
                )
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
            if _is_literal(node.args[0], _BINDINGS):
                self._allowed_literals.add(id(node.args[0]))
        if callee in _NAME_LOOKUP_CALLS:
            if len(node.args) >= 2 and _is_literal(node.args[1], _BINDINGS):
                self._allowed_literals.add(id(node.args[1]))
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    self._reference(arg, arg.value)
        self.generic_visit(node)


class _ScanResult:
    def __init__(self, violations: list[str], takes_bindings: set[str]) -> None:
        self.violations = violations
        self.takes_bindings = takes_bindings


def _scan(name: str, text: str) -> _ScanResult:
    tree = ast.parse(text, filename=name)
    facts = _CandidateBindingFacts(name)
    facts.visit(tree)
    return _ScanResult(facts.violations + _state_reader_violations(name, tree), facts.takes_bindings)


_PLANTED = "temper_ai/planted.py"
_ROUTES = _STATE_READER_FILE
_STATE_DEF = "def _state():\n    return APP\n"
_READER_ONLY = "def _candidate_bindings():\n    return vars(_state()).get('candidate_bindings')\n"
_READER_DEF = _STATE_DEF + _READER_ONLY
_READER_CALLER = "def _start_run():\n    bindings = _candidate_bindings()\n"
# Each twin breaks one fact (or the facts listed); the check must report it under that rule, and only once.
_PLANTED_TWINS = {
    # Fact 1
    "non-None default": (_PLANTED, "def run(*, candidate_bindings=object()):\n    pass\n", _DEFAULT_RULE),
    "required parameter": (_PLANTED, "def run(candidate_bindings):\n    pass\n", _DEFAULT_RULE),
    "positional parameter left None": (_PLANTED, "def run(candidate_bindings=None):\n    pass\n", _DEFAULT_RULE),
    "positional-only parameter": (_PLANTED, "def run(candidate_bindings=None, /):\n    pass\n", _DEFAULT_RULE),
    "star parameter": (_PLANTED, "def run(*candidate_bindings):\n    pass\n", _DEFAULT_RULE),
    "double-star parameter": (_PLANTED, "def run(**candidate_bindings):\n    pass\n", _DEFAULT_RULE),
    "positional lambda left None": (
        _PLANTED,
        "HANDLER = lambda candidate_bindings=None: candidate_bindings\n",
        _DEFAULT_RULE,
    ),
    "lambda default built": (
        _PLANTED,
        "def run(*, candidate_bindings=None):\n"
        "    return (lambda candidate_bindings=make(): go(candidate_bindings=candidate_bindings))()\n",
        _DEFAULT_RULE,
    ),
    # Fact 2
    "built value passed": (
        _PLANTED,
        "def run(*, candidate_bindings=None):\n    go(candidate_bindings=make())\n",
        _PASS_THROUGH_RULE,
    ),
    "name that is not a parameter": (
        _PLANTED,
        "def run():\n    go(candidate_bindings=candidate_bindings)\n",
        _PASS_THROUGH_RULE,
    ),
    "parameter replaced first": (
        _PLANTED,
        "def run(*, candidate_bindings=None):\n    candidate_bindings = make()\n    go(candidate_bindings=candidate_bindings)\n",
        _PASS_THROUGH_RULE,
    ),
    "parameter rebound by a loop": (
        _PLANTED,
        "def run(*, candidate_bindings=None):\n"
        "    for candidate_bindings in [make()]:\n"
        "        go(candidate_bindings=candidate_bindings)\n",
        _PASS_THROUGH_RULE,
    ),
    "module-level call": (_PLANTED, "go(candidate_bindings=BINDINGS)\n", _PASS_THROUGH_RULE),
    "dict key with a built value": (
        _PLANTED,
        "def run():\n    execute_workflow(**{'candidate_bindings': make()})\n",
        _PASS_THROUGH_RULE,
    ),
    "built bindings to submit_candidate": (
        _PLANTED,
        "def start():\n    submit_candidate(bindings=make())\n",
        _PASS_THROUGH_RULE,
    ),
    "splat into submit_candidate": (_PLANTED, "def start(kw):\n    submit_candidate(**kw)\n", _PASS_THROUGH_RULE),
    "state reader outside routes": (
        _PLANTED,
        _READER_CALLER + "    submit_candidate(bindings=bindings)\n",
        (_PASS_THROUGH_RULE, _READER_NAME_RULE),
    ),
    "state reader value replaced": (
        _ROUTES,
        _READER_DEF + _READER_CALLER + "    bindings = make()\n    submit_candidate(bindings=bindings)\n",
        _PASS_THROUGH_RULE,
    ),
    "state reader value from a parameter": (
        _ROUTES,
        _READER_DEF
        + "def _start_run(body, *, bindings=None):\n"
        "    if bindings is None:\n"
        "        bindings = _candidate_bindings()\n"
        "    submit_candidate(bindings=bindings)\n",
        _PASS_THROUGH_RULE,
    ),
    "state reader value used before it is assigned": (
        _ROUTES,
        _READER_DEF
        + "def _start_run():\n    submit_candidate(bindings=bindings)\n    bindings = _candidate_bindings()\n",
        _PASS_THROUGH_RULE,
    ),
    "state reader value assigned conditionally": (
        _ROUTES,
        _READER_DEF
        + "def _start_run(flag):\n"
        "    if flag:\n"
        "        bindings = _candidate_bindings()\n"
        "    submit_candidate(bindings=bindings)\n",
        _PASS_THROUGH_RULE,
    ),
    "state reader value declared global": (
        _ROUTES,
        _READER_DEF
        + "def _start_run():\n"
        "    global bindings\n"
        "    bindings = _candidate_bindings()\n"
        "    submit_candidate(bindings=bindings)\n",
        _PASS_THROUGH_RULE,
    ),
    "state reader value declared nonlocal": (
        _ROUTES,
        _READER_DEF
        + "def outer():\n"
        "    bindings = None\n"
        "    def _start_run():\n"
        "        nonlocal bindings\n"
        "        bindings = _candidate_bindings()\n"
        "        submit_candidate(bindings=bindings)\n"
        "    return _start_run\n",
        _PASS_THROUGH_RULE,
    ),
    # Fact 3
    "attribute store": (_PLANTED, "def boot(state):\n    state.candidate_bindings = make()\n", _STORE_RULE),
    "setattr store": (_PLANTED, "def boot(state):\n    setattr(state, 'candidate_bindings', make())\n", _STORE_RULE),
    "object.__setattr__ store": (
        _PLANTED,
        "def boot(state):\n    object.__setattr__(state, 'candidate_bindings', make())\n",
        _STORE_RULE,
    ),
    "aliased setattr store": (
        _PLANTED,
        "def boot(state):\n    put = setattr\n    put(state, 'candidate_bindings', make())\n",
        _STORE_RULE,
    ),
    "subscript store": (_PLANTED, "def boot(state):\n    vars(state)['candidate_bindings'] = make()\n", _STORE_RULE),
    "setdefault store": (
        _PLANTED,
        "def boot(state):\n    vars(state).setdefault('candidate_bindings', make())\n",
        _STORE_RULE,
    ),
    "operator.setitem store": (
        _PLANTED,
        "def boot(state):\n    operator.setitem(vars(state), 'candidate_bindings', make())\n",
        _STORE_RULE,
    ),
    "dict(zip) keys": (
        _PLANTED,
        "def run():\n    execute_workflow(**dict(zip(['candidate_bindings'], [make()])))\n",
        _STORE_RULE,
    ),
    "class field with a value": (_PLANTED, "class AppState:\n    candidate_bindings: object = make()\n", _STORE_RULE),
    "class field left None": (_PLANTED, "class AppState:\n    candidate_bindings: object = None\n", _STORE_RULE),
    "class field declared": (_PLANTED, "class AppState:\n    candidate_bindings: object\n", _STORE_RULE),
    "class inside a function": (
        _PLANTED,
        "def boot():\n    class State:\n        candidate_bindings = make()\n    return State\n",
        _STORE_RULE,
    ),
    "module-level value": (_PLANTED, "candidate_bindings = make()\n", _STORE_RULE),
    "global store": (
        _PLANTED,
        "def boot():\n    global candidate_bindings\n    candidate_bindings = make()\n",
        _STORE_RULE,
    ),
    # Fact 4
    "composition built": (_PLANTED, "def boot():\n    return compose_p3_authority()\n", _REFERENCE_RULE),
    "disabled composer called": (
        _PLANTED,
        "import first_app_p3_native as n\nn.compose_disabled_consumer_service()\n",
        _REFERENCE_RULE,
    ),
    "composer imported under another name": (
        _PLANTED,
        "from temper_ai.p3_authority.service import compose_p3_authority as build\n",
        _REFERENCE_RULE,
    ),
    "composer reached through getattr": (
        _PLANTED,
        "def boot(module):\n    return getattr(module, 'compose_p3_authority')()\n",
        _REFERENCE_RULE,
    ),
    "bindings type named": (_PLANTED, "def boot():\n    return P3CandidateBindings()\n", _REFERENCE_RULE),
    "service type named": (_PLANTED, "def boot(x):\n    return isinstance(x, P3AuthorityService)\n", _REFERENCE_RULE),
    # Fact 5
    "submit_candidate imported under another name": (
        _PLANTED,
        "from temper_ai.runner.admission import submit_candidate as go\n",
        _DIRECT_CALL_RULE,
    ),
    "submit_candidate through partial": (
        _PLANTED,
        "def start():\n    return functools.partial(submit_candidate, bindings=make())\n",
        _DIRECT_CALL_RULE,
    ),
    "submit_candidate through getattr": (
        _PLANTED,
        "def start(admission):\n    return getattr(admission, 'submit_candidate')\n",
        _DIRECT_CALL_RULE,
    ),
    "submit_candidate rebound": (_PLANTED, "submit_candidate = make()\n", _DIRECT_CALL_RULE),
    # Fact 6
    "state reader returns a built value": (
        _ROUTES,
        _STATE_DEF + "def _candidate_bindings():\n    return make()\n",
        _READER_RULE,
    ),
    "state reader reads another key": (
        _ROUTES,
        _STATE_DEF + "def _candidate_bindings():\n    return vars(_state()).get('bindings')\n",
        _READER_RULE,
    ),
    "state reader yields": (_ROUTES, _STATE_DEF + "def _candidate_bindings():\n    yield None\n", _READER_RULE),
    "state reader rebound": (_ROUTES, _READER_DEF + "_candidate_bindings = make\n", _READER_RULE),
    "state reader imported": (
        _ROUTES,
        _STATE_DEF + "from temper_ai.api.state import _candidate_bindings\n",
        _READER_RULE,
    ),
    "state reader decorated": (_ROUTES, _STATE_DEF + "@cache\n" + _READER_ONLY, _READER_RULE),
    "state reader async": (
        _ROUTES,
        _STATE_DEF + "async def _candidate_bindings():\n    return None\n",
        _READER_RULE,
    ),
    "state reader takes a parameter": (
        _ROUTES,
        _STATE_DEF + "def _candidate_bindings(vars=make):\n    return vars(_state()).get('candidate_bindings')\n",
        _READER_RULE,
    ),
    "state reader missing": (_ROUTES, _STATE_DEF + "def _start_run():\n    pass\n", _READER_RULE),
    "vars rebound in routes": (_ROUTES, "vars = make\n" + _READER_DEF, _READER_RULE),
    "vars reads another object": (
        _ROUTES,
        _STATE_DEF + "def _candidate_bindings():\n    return vars(other()).get('candidate_bindings')\n",
        _READER_RULE,
    ),
    "vars reads a name not from _state()": (
        _ROUTES,
        _STATE_DEF
        + "def _candidate_bindings():\n    state = other()\n    return vars(state).get('candidate_bindings')\n",
        _READER_RULE,
    ),
    "vars reads a name bound twice": (
        _ROUTES,
        _STATE_DEF
        + "def _candidate_bindings():\n"
        "    state = _state()\n"
        "    state = other()\n"
        "    return vars(state).get('candidate_bindings')\n",
        _READER_RULE,
    ),
    "vars reads a name declared global": (
        _ROUTES,
        _STATE_DEF
        + "def _candidate_bindings():\n"
        "    global state\n"
        "    state = _state()\n"
        "    return vars(state).get('candidate_bindings')\n",
        _READER_RULE,
    ),
    "state getter rebound": (_ROUTES, _READER_DEF + "_state = make\n", _READER_RULE),
    "state getter missing": (_ROUTES, _READER_ONLY, _READER_RULE),
    "builtins imported": (_PLANTED, "import builtins\n", _READER_RULE),
    "from builtins import": (_PLANTED, "from builtins import vars\n", _READER_RULE),
    "__builtins__ named": (_PLANTED, "def boot():\n    __builtins__['vars'] = make\n", _READER_RULE),
    # Fact 7
    "reader shadowed by a parameter": (
        _ROUTES,
        _READER_DEF
        + "def _start_run(body, *, _candidate_bindings=None):\n"
        "    bindings = _candidate_bindings()\n"
        "    submit_candidate(bindings=bindings)\n",
        _READER_NAME_RULE,
    ),
    "reader replaced through the module": (
        _PLANTED,
        "from temper_ai.api import routes\nroutes._candidate_bindings = make\n",
        _READER_NAME_RULE,
    ),
    "reader replaced through setattr": (
        _PLANTED,
        "from temper_ai.api import routes\nsetattr(routes, '_candidate_bindings', make)\n",
        _READER_NAME_RULE,
    ),
    "reader replaced through globals()": (
        _ROUTES,
        _READER_DEF + "globals()['_candidate_bindings'] = make\n",
        _READER_NAME_RULE,
    ),
    "reader imported elsewhere": (
        _PLANTED,
        "from temper_ai.api.routes import _candidate_bindings\n",
        _READER_NAME_RULE,
    ),
    "reader called elsewhere": (_PLANTED, "def peek():\n    return _candidate_bindings()\n", _READER_NAME_RULE),
    "reader referenced, not called": (_ROUTES, _READER_DEF + "READ = _candidate_bindings\n", _READER_NAME_RULE),
    "reader called with an argument": (
        _ROUTES,
        _READER_DEF + "def peek(x):\n    return _candidate_bindings(x)\n",
        _READER_NAME_RULE,
    ),
    "reader passed as a keyword": (_PLANTED, "configure(_candidate_bindings=make)\n", _READER_NAME_RULE),
    "reader defined elsewhere": (
        _PLANTED,
        "def _candidate_bindings():\n    return None\n",
        _READER_NAME_RULE,
    ),
    "reader class elsewhere": (_PLANTED, "class _candidate_bindings:\n    pass\n", _READER_NAME_RULE),
    "reader declared global elsewhere": (
        _PLANTED,
        "def boot():\n    global _candidate_bindings\n",
        _READER_NAME_RULE,
    ),
    "reader captured elsewhere": (
        _PLANTED,
        "try:\n    pass\nexcept Exception as _candidate_bindings:\n    pass\n",
        _READER_NAME_RULE,
    ),
}
# Each clean twin keeps every fact; the check must report nothing.
_CLEAN_TWINS = {
    "keyword pass-through": (
        _PLANTED,
        "def outer(*, candidate_bindings=None):\n"
        "    return inner(candidate_bindings=candidate_bindings)\n"
        "async def inner(*, candidate_bindings=None):\n"
        "    return candidate_bindings is None\n",
    ),
    "dict key pass-through": (
        _PLANTED,
        "def outer(*, candidate_bindings=None):\n    return run(**{'candidate_bindings': candidate_bindings})\n",
    ),
    "lambda pass-through": (
        _PLANTED,
        "def outer(*, candidate_bindings=None):\n"
        "    return (lambda *, candidate_bindings=None: go(candidate_bindings=candidate_bindings))(\n"
        "        candidate_bindings=candidate_bindings\n"
        "    )\n",
    ),
    "reads elsewhere": (
        _PLANTED,
        "def peek(state):\n"
        "    return getattr(state, 'candidate_bindings', None), vars(state).get('candidate_bindings')\n",
    ),
    "submit_candidate through its module": (
        _PLANTED,
        "from temper_ai.runner import admission\n"
        "def start(*, candidate_bindings=None):\n"
        "    return admission.submit_candidate(bindings=candidate_bindings)\n",
    ),
    "state reader in routes": (
        _ROUTES,
        "from temper_ai.runner.admission import submit_candidate\n"
        + _READER_DEF
        + _READER_CALLER
        + "    submit_candidate(bindings=bindings)\n",
    ),
    "start run shaped like the live one": (
        _ROUTES,
        "from temper_ai.runner.admission import is_designated, submit_candidate\n"
        + _READER_DEF
        + "def _start_run(body, *, execution_id=None):\n"
        "    bindings = _candidate_bindings()\n"
        "    refuse(execution_id)\n"
        "    if body.admission is not None or is_designated(body.workflow, bindings):\n"
        "        try:\n"
        "            chosen = submit_candidate(execution_id=execution_id, bindings=bindings)\n"
        "        except RuntimeError:\n"
        "            raise\n"
        "        return chosen\n"
        "def _refuse_hold(hold):\n"
        "    return is_designated(hold.get('workflow_name'), _candidate_bindings())\n",
    ),
    "state reader shaped like the live one": (
        _ROUTES,
        _STATE_DEF
        + "def _candidate_bindings():\n"
        "    try:\n"
        "        state = _state()\n"
        "    except RuntimeError:\n"
        "        return None\n"
        "    return vars(state).get('candidate_bindings')\n",
    ),
    "composer named in its own module": (
        _REFERENCE_ALLOWED_FILE,
        "from temper_ai.p3_authority.service import P3AuthorityService, compose_p3_authority\n"
        "def compose(**kwargs):\n    return compose_p3_authority(**kwargs)\n",
    ),
}


@pytest.mark.parametrize("twin", sorted(_PLANTED_TWINS))
def test_candidate_binding_fact_checks_catch_each_planted_twin(twin):
    path, source, rules = _PLANTED_TWINS[twin]
    expected = (rules,) if isinstance(rules, str) else rules
    violations = _scan(path, source).violations
    assert len(violations) == len(expected), violations
    found = sorted(rule for violation in violations for rule in _RULES if rule in violation)
    assert found == sorted(expected), violations


@pytest.mark.parametrize("twin", sorted(_CLEAN_TWINS))
def test_candidate_binding_fact_checks_pass_each_clean_twin(twin):
    path, source = _CLEAN_TWINS[twin]
    assert _scan(path, source).violations == []


def test_candidate_binding_fact_checks_list_the_functions_that_take_bindings():
    facts = _scan(_PLANTED, _CLEAN_TWINS["keyword pass-through"][1])
    assert facts.takes_bindings == {"outer", "inner"}


def test_production_tree_breaks_no_candidate_binding_fact():
    violations: list[str] = []
    takes_bindings: set[tuple[str, str]] = set()
    scanned: set[str] = set()
    for name, text in _production_sources():
        facts = _scan(name, text)
        scanned.add(name)
        violations += facts.violations
        module = name.removesuffix(".py").replace("/", ".")
        takes_bindings |= {(module, function) for function in facts.takes_bindings}
    assert len(scanned) > 100
    assert {_STATE_READER_FILE, _REFERENCE_ALLOWED_FILE} <= scanned
    for package in ("p3_host_contracts", "p3_source_closure"):
        assert any(name.startswith(f"{package}/") for name in scanned), package
    assert violations == []
    assert _RUNNER_ENTRY_POINTS <= takes_bindings
    for module, function in sorted(_RUNNER_ENTRY_POINTS):
        parameter = inspect.signature(getattr(importlib.import_module(module), function)).parameters[_BINDINGS]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is None
