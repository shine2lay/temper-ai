"""Candidate bindings stay unset in the source (#125: Security O-466-3, R-125-1, R-125-2).

While P3 host writes are off, no production code may build, store or hand on candidate bindings. These tests
check that as facts over the source of temper_ai/, configs/, scripts/, p3_host_contracts/ and p3_source_closure/
(outside temper_ai/p3_authority/, which defines the types). Each fact has planted twins the check must report
exactly once under that fact's rule, and clean twins it must pass.

1. Every candidate_bindings parameter, of a function or a lambda, defaults to None.
2. A value handed on (a candidate_bindings= keyword, a "candidate_bindings" dict key, or bindings= to
   submit_candidate) is the calling function's own untouched candidate_bindings parameter, and nothing is splatted
   into submit_candidate. The one exception is routes._start_run's `bindings = _candidate_bindings()`, assigned once.
3. Nothing stores candidate_bindings: no attribute store, no module- or class-level name of that name (a field
   left None or only declared included), no global declaration; and the string "candidate_bindings" appears only
   as a .get/getattr/hasattr read or as a dict key fact 2 checks, so setattr, setdefault, setitem, subscript
   stores and dict(zip(...)) are all seen.
4. Only configs/architecture/bin/first_app_p3_native.py names the P3 composition types and composers (as a name,
   an attribute, an import, or a getattr/hasattr string).
5. submit_candidate appears only as a direct call's function or a plain un-aliased import.
6. The state reader that fact 2's exception trusts is pinned: in temper_ai/api/routes.py the only binding of
   _candidate_bindings is one undecorated plain module-level def with no parameters and no yield or await, every
   return in it gives
   None or vars(<one argument>).get("candidate_bindings"), and vars is not rebound there. With fact 3 holding, that
   read gives None.

Not seen: names built at run time (setattr(obj, name, ...), import_module strings), values loaded from data at run
time, string annotations, and positional passes to functions whose candidate_bindings parameter is not keyword-only
(is_designated(workflow, bindings) only reads).
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
_NAME_LOOKUP_CALLS = {"getattr", "hasattr"}

_DEFAULT_RULE = "candidate_bindings must default to None"
_PASS_THROUGH_RULE = "is not its own untouched parameter"
_STORE_RULE = "stores candidate_bindings"
_REFERENCE_RULE = "named outside first_app_p3_native.py"
_DIRECT_CALL_RULE = "other than as a direct call"
_READER_RULE = "the state reader"


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


def _is_state_read(node) -> bool:
    """True for vars(<one argument>).get("candidate_bindings") and nothing else."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
        return False
    target = node.func.value
    return (
        isinstance(target, ast.Call)
        and isinstance(target.func, ast.Name)
        and target.func.id == "vars"
        and len(target.args) == 1
        and not target.keywords
        and len(node.args) == 1
        and _is_literal(node.args[0], _BINDINGS)
        and not node.keywords
    )


def _state_reader_violations(name: str, tree: ast.Module) -> list[str]:
    """Fact 6, checked in routes.py only: the reader fact 2's exception trusts can only read the state."""
    if name != _STATE_READER_FILE:
        return []
    bindings = _name_bindings(tree, _STATE_READER)
    reader = bindings[0] if len(bindings) == 1 else None
    if not (isinstance(reader, ast.FunctionDef) and reader in tree.body and not reader.decorator_list):
        return [
            f"{name}: the state reader {_STATE_READER} must be one undecorated plain module-level def,"
            f" never rebound or imported ({len(bindings)} binding(s) found)"
        ]
    found = []
    parameters = reader.args
    if parameters.posonlyargs or parameters.args or parameters.kwonlyargs or parameters.vararg or parameters.kwarg:
        found.append(f"{name}:{reader.lineno}: the state reader must take no parameters")
    for node in ast.walk(reader):
        if isinstance(node, (ast.Yield, ast.YieldFrom, ast.Await)):
            found.append(f"{name}:{node.lineno}: the state reader must not yield or await")
        elif isinstance(node, ast.Return) and not (
            node.value is None or (isinstance(node.value, ast.Constant) and node.value.value is None)
            or _is_state_read(node.value)
        ):
            found.append(
                f"{name}:{node.lineno}: the state reader must return None or vars(...).get('candidate_bindings'),"
                f" not {ast.unparse(node.value)}"
            )
    if _name_bindings(tree, "vars"):
        found.append(f"{name}: vars is rebound, so the state reader's read can't be trusted")
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
        own = self._own_function()
        if (
            own is None
            or (self.name, getattr(own, "name", None)) != (_STATE_READER_FILE, _STATE_READER_CALLER)
            or not isinstance(value, ast.Name)
        ):
            return False
        bindings = _name_bindings(own, value.id)
        if len(bindings) != 1:
            return False
        for node in ast.walk(own):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and node.targets[0] is bindings[0]:
                call = node.value
                return (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == _STATE_READER
                    and not call.args
                    and not call.keywords
                )
        return False

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

    def visit_Global(self, node: ast.Global) -> None:
        if _BINDINGS in node.names:
            self._report(node, f"global candidate_bindings {_STORE_RULE}")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if _is_literal(node, _BINDINGS) and id(node) not in self._allowed_literals:
            self._report(node, f"'candidate_bindings' outside a .get/getattr/hasattr read or a checked dict key {_STORE_RULE}")

    def visit_Name(self, node: ast.Name) -> None:
        self._reference(node, node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._reference(node, node.attr)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name in _PROTECTED_NAMES and self.name != _REFERENCE_ALLOWED_FILE:
                self._report(node, f"{alias.name} {_REFERENCE_RULE}")
            if alias.name == _ADMISSION_ENTRY and alias.asname not in (None, _ADMISSION_ENTRY):
                self._report(node, f"{_ADMISSION_ENTRY} imported as {alias.asname}: used {_DIRECT_CALL_RULE}")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
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
        for arg, default in _parameter_defaults(node):
            if arg.arg != _BINDINGS:
                continue
            self.takes_bindings.add(label)
            if not (isinstance(default, ast.Constant) and default.value is None):
                self.violations.append(f"{self.name}:{node.lineno} {label}: {_DEFAULT_RULE}")
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
        for keyword in node.keywords:
            value = keyword.value
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
_READER_DEF = "def _candidate_bindings():\n    return vars(_state()).get('candidate_bindings')\n"
_READER_CALLER = "def _start_run():\n    bindings = _candidate_bindings()\n"
# Each twin breaks one fact; the check must report it under that fact's rule, and only once.
_PLANTED_TWINS = {
    # Fact 1
    "non-None default": (_PLANTED, "def run(*, candidate_bindings=object()):\n    pass\n", _DEFAULT_RULE),
    "required parameter": (_PLANTED, "def run(candidate_bindings):\n    pass\n", _DEFAULT_RULE),
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
        _PASS_THROUGH_RULE,
    ),
    "state reader value replaced": (
        _ROUTES,
        _READER_DEF + _READER_CALLER + "    bindings = make()\n    submit_candidate(bindings=bindings)\n",
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
    "state reader returns a built value": (_ROUTES, "def _candidate_bindings():\n    return make()\n", _READER_RULE),
    "state reader reads another key": (
        _ROUTES,
        "def _candidate_bindings():\n    return vars(_state()).get('bindings')\n",
        _READER_RULE,
    ),
    "state reader yields": (_ROUTES, "def _candidate_bindings():\n    yield None\n", _READER_RULE),
    "state reader rebound": (_ROUTES, _READER_DEF + "_candidate_bindings = make\n", _READER_RULE),
    "state reader imported": (_ROUTES, "from temper_ai.api.state import _candidate_bindings\n", _READER_RULE),
    "state reader decorated": (_ROUTES, "@cache\n" + _READER_DEF, _READER_RULE),
    "state reader async": (_ROUTES, "async def _candidate_bindings():\n    return None\n", _READER_RULE),
    "state reader takes a parameter": (
        _ROUTES,
        "def _candidate_bindings(vars=make):\n    return vars(_state()).get('candidate_bindings')\n",
        _READER_RULE,
    ),
    "state reader missing": (_ROUTES, "def _start_run():\n    pass\n", _READER_RULE),
    "vars rebound in routes": (_ROUTES, "vars = make\n" + _READER_DEF, _READER_RULE),
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
        "    return (lambda candidate_bindings=None: go(candidate_bindings=candidate_bindings))(candidate_bindings)\n",
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
    "state reader shaped like the live one": (
        _ROUTES,
        "def _candidate_bindings():\n"
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
    path, source, rule = _PLANTED_TWINS[twin]
    violations = _scan(path, source).violations
    assert len(violations) == 1, violations
    assert rule in violations[0]


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
    assert any(name.startswith(("p3_host_contracts/", "p3_source_closure/")) for name in scanned)
    assert violations == []
    assert _RUNNER_ENTRY_POINTS <= takes_bindings
    for module, function in sorted(_RUNNER_ENTRY_POINTS):
        parameter = inspect.signature(getattr(importlib.import_module(module), function)).parameters[_BINDINGS]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is None
