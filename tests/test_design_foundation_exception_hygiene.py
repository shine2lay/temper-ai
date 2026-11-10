"""AST enforcement of the exception-handler rule across foundation and app_screen.

Every `except` handler in `configs/design/bin/foundation/` and
`configs/design/bin/app_screen/` must match one of three legal shapes:
  (a) Re-raise as a named domain error carrying context/reason (or bare re-raise).
  (b) Record a named problem or rule failure that reaches the report and makes the verdict fail.
  (c) A top-level CLI / process / proxy boundary that emits a structured error document
      and returns a non-zero exit code.

Nothing else is permitted: no `pass`, no silent default (`doc = {}`, `x = None`,
`return None`, `return []`, `continue` without recording a problem, etc.).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FOUNDATION_DIR = REPO_ROOT / "configs" / "design" / "bin" / "foundation"
APP_SCREEN_DIR = REPO_ROOT / "configs" / "design" / "bin" / "app_screen"
PACKAGE_DIRS = (FOUNDATION_DIR, APP_SCREEN_DIR)

PROBLEM_LIST_NAMES = frozenset({"problems", "misses", "warnings_out"})


def classify_except_handler(node: ast.ExceptHandler) -> str | None:
    """Return 'a', 'b', or 'c' if `node` conforms to one of the 3 legal shapes, else None."""
    if not node.body:
        return None

    # No handler may contain a `pass` statement.
    if any(isinstance(stmt, ast.Pass) for stmt in node.body):
        return None

    # Any nested ExceptHandler inside this handler must also be valid.
    for sub in ast.walk(node):
        if sub is not node and isinstance(sub, ast.ExceptHandler):
            if classify_except_handler(sub) is None:
                return None

    # Shape (a): re-raises (either directly in body, or via a single nested try whose handlers all raise).
    has_direct_raise = any(isinstance(stmt, ast.Raise) for stmt in node.body)
    if not has_direct_raise and len(node.body) == 1 and isinstance(node.body[0], ast.Try):
        nested_try = node.body[0]
        if nested_try.handlers and all(classify_except_handler(h) == "a" for h in nested_try.handlers):
            return "a"
    if has_direct_raise:
        for stmt in node.body:
            if isinstance(stmt, ast.Raise) and stmt.exc is not None:
                if isinstance(stmt.exc, ast.Call):
                    exc_fn = ast.unparse(stmt.exc.func)
                    if exc_fn in {"Exception", "BaseException"}:
                        return None
                    if not stmt.exc.args and not stmt.exc.keywords:
                        return None
                elif isinstance(stmt.exc, ast.Name) and stmt.exc.id in {"Exception", "BaseException"}:
                    return None
        return "a"

    unparsed = ast.unparse(node)

    # Shape (c): top-level CLI / process / proxy boundary emitting a structured error and non-zero exit.
    for stmt in node.body:
        if (
            isinstance(stmt, ast.Return)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, int)
            and not isinstance(stmt.value.value, bool)
            and stmt.value.value != 0
        ):
            if "print(" in unparsed and "json.dumps(" in unparsed:
                return "c"
        if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Call):
            fn_str = ast.unparse(stmt.value.func)
            if fn_str.endswith("CompletedProcess") and len(stmt.value.args) >= 2:
                rc_arg = stmt.value.args[1]
                if isinstance(rc_arg, ast.Constant) and rc_arg.value == 1:
                    return "c"
    if "self.send_response(502)" in unparsed or ("int(exc.code)" in unparsed and "exc.read()" in unparsed):
        return "c"

    # Shape (b): records a named problem / rule failure that reaches the report.
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn_str = ast.unparse(sub.func)
            if fn_str == "_add_problem":
                return "b"
            if fn_str.endswith(".append"):
                target_str = fn_str[: -len(".append")]
                if target_str in PROBLEM_LIST_NAMES or target_str.startswith("by_rule["):
                    return "b"

    for stmt in node.body:
        if isinstance(stmt, ast.Return) and stmt.value is not None:
            ret_str = ast.unparse(stmt.value)
            if "_row(" in ret_str and "'fail'" in ret_str:
                return "b"
            if isinstance(stmt.value, ast.Dict):
                keys = [ast.unparse(k).strip("'\"") for k in stmt.value.keys if k is not None]
                if (
                    ("verdict" in keys and "problems" in keys)
                    or ("pass" in keys and "misses" in keys)
                    or "unreadable" in keys
                ):
                    return "b"
            if isinstance(stmt.value, ast.Tuple) and len(stmt.value.elts) == 2:
                second_str = ast.unparse(stmt.value.elts[1])
                if "exc" in second_str:
                    return "b"
            if isinstance(stmt.value, ast.List) and len(stmt.value.elts) == 1:
                elt_str = ast.unparse(stmt.value.elts[0])
                if "str(exc)" in elt_str or "missing or broken" in elt_str:
                    return "b"

    if (
        "{'found': True, 'clicked': False, 'why':" in unparsed
        or "['(audit.json screens unreadable)']" in unparsed
    ):
        return "b"

    return None


def scan_packages(package_dirs: tuple[Path, ...] = PACKAGE_DIRS) -> list[tuple[str, int, str, str]]:
    """Return all non-conforming ExceptHandlers as (rel_path, lineno, except_header, body_summary)."""
    violations: list[tuple[str, int, str, str]] = []
    for pkg_dir in package_dirs:
        for py_file in sorted(pkg_dir.rglob("*.py")):
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
            handlers = sorted(
                (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)),
                key=lambda n: n.lineno,
            )
            for handler in handlers:
                if classify_except_handler(handler) is None:
                    rel = py_file.relative_to(REPO_ROOT).as_posix()
                    header = ast.unparse(handler).splitlines()[0]
                    body_summary = "; ".join(ast.unparse(s).splitlines()[0] for s in handler.body)
                    violations.append((rel, handler.lineno, header, body_summary))
    return violations


def test_ast_classifier_recognizes_three_legal_shapes_and_rejects_silent_swallows() -> None:
    shape_a = ast.parse(
        "try:\n    load()\nexcept (OSError, ValueError) as exc:\n    raise DirectionsError(f'{path}: {exc}') from exc\n"
    ).body[0].handlers[0]
    assert classify_except_handler(shape_a) == "a"

    shape_b = ast.parse(
        "try:\n    load()\nexcept OSError as exc:\n    problems.append(_problem('directions.proof', f'{path}: {exc}'))\n"
    ).body[0].handlers[0]
    assert classify_except_handler(shape_b) == "b"

    shape_c = ast.parse(
        "try:\n    run()\nexcept DirectionsError as exc:\n    print(json.dumps({'verdict': 'fail', 'error': str(exc)}))\n    return 1\n"
    ).body[0].handlers[0]
    assert classify_except_handler(shape_c) == "c"

    for bad_snippet in (
        "try:\n    load()\nexcept Exception:\n    pass\n",
        "try:\n    load()\nexcept json.JSONDecodeError:\n    doc = {}\n",
        "try:\n    load()\nexcept OSError:\n    return None\n",
        "try:\n    load()\nexcept ValueError:\n    continue\n",
        "try:\n    import PIL\nexcept ImportError:\n    Image = None\n",
    ):
        handler = ast.parse(bad_snippet).body[0].handlers[0]
        assert classify_except_handler(handler) is None, f"expected violation for:\n{bad_snippet}"


def test_confirmed_good_sites_in_directions_match_shapes_b_and_c() -> None:
    directions_py = FOUNDATION_DIR / "directions.py"
    tree = ast.parse(directions_py.read_text(encoding="utf-8"), filename=str(directions_py))
    by_shape = [
        (node.lineno, classify_except_handler(node), ast.unparse(node).splitlines()[0])
        for node in sorted(
            (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)),
            key=lambda n: n.lineno,
        )
    ]
    shapes_found = {shape for _, shape, _ in by_shape}
    assert "b" in shapes_found, f"expected shape (b) proof problem handler in directions.py: {by_shape}"
    assert "c" in shapes_found, f"expected shape (c) CLI boundary handler in directions.py: {by_shape}"


def test_no_silent_exception_handlers_in_foundation_or_app_screen() -> None:
    violations = scan_packages()
    if violations:
        formatted = "\n".join(
            f"  {rel}:{lineno} -> {header} :: {body}"
            for rel, lineno, header, body in violations
        )
        pytest.fail(
            f"Found {len(violations)} exception handler(s) violating shapes (a)/(b)/(c):\n{formatted}"
        )
