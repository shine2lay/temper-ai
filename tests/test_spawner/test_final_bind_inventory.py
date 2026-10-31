"""Repository-wide inventory of engine Docker launch construction and guarded boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class LaunchInventory(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path.relative_to(ROOT).as_posix()
        self.scope: list[str] = []
        self.launches: set[str] = set()

    def visit_ClassDef(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_List(self, node):
        if len(node.elts) >= 2:
            first, second = node.elts[:2]
            docker = ((isinstance(first, ast.Constant) and isinstance(first.value, str)
                       and Path(first.value).name == "docker")
                      or (isinstance(first, ast.Attribute) and first.attr == "_docker"))
            if docker and isinstance(second, ast.Constant) and second.value in {"run", "create"}:
                self.launches.add(self.path + "::" + ".".join(self.scope))
        self.generic_visit(node)

    visit_Tuple = visit_List

    def visit_Call(self, node):
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "_docker" and node.args
                and isinstance(node.args[0], ast.Constant) and node.args[0].value in {"run", "create"}):
            self.launches.add(self.path + "::" + ".".join(self.scope))
        self.generic_visit(node)


def test_every_engine_docker_launch_constructor_has_a_named_final_guard():
    launches = set()
    for path in (ROOT / "temper_ai").rglob("*.py"):
        inventory = LaunchInventory(path)
        inventory.visit(ast.parse(path.read_text()))
        launches.update(inventory.launches)
    assert launches == {
        "temper_ai/spawner/docker_spawner.py::DockerSpawner.run_command",
        "temper_ai/spawner/docker_spawner.py::DockerSpawner.sealed_command",
        "temper_ai/spawner/docker_spawner.py::DockerSpawner._uid_probe_command",
        "temper_ai/pi_agent/box.py::WorkerBox.create_args",
    }


def _method(path, class_name, name):
    tree = ast.parse((ROOT / path).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _calls(node, name):
    return sorted((n for n in ast.walk(node) if isinstance(n, ast.Call)
                   and ((isinstance(n.func, ast.Name) and n.func.id == name)
                        or (isinstance(n.func, ast.Attribute) and n.func.attr == name))),
                  key=lambda n: n.lineno)


def test_execution_boundaries_check_final_argv_and_writer_is_existing_container_exec():
    spawner = "temper_ai/spawner/docker_spawner.py"
    for method, site in (("spawn", "legacy"), ("_spawn_sealed", "sealed"), ("_box_ids", "uid_probe")):
        node = _method(spawner, "DockerSpawner", method)
        calls = _calls(node, "_launch_container")
        assert len(calls) == 1
        assert any(k.arg == "site" and isinstance(k.value, ast.Constant) and k.value.value == site
                   for k in calls[0].keywords)
    boundary = _method(spawner, "DockerSpawner", "_launch_container")
    assert _calls(boundary, "check_launch")[0].lineno < _calls(boundary, "_docker_run")[0].lineno
    pi = _method("temper_ai/pi_agent/box.py", "WorkerBox", "start")
    assert (_calls(pi, "create_args")[0].lineno < _calls(pi, "check_launch")[0].lineno
            < _calls(pi, "_docker")[0].lineno)
    writer = _method(spawner, "DockerSpawner", "_deliver")
    commands = [n for n in ast.walk(writer) if isinstance(n, ast.List) and len(n.elts) > 1
                and isinstance(n.elts[0], ast.Attribute) and n.elts[0].attr == "_docker"]
    # Delivery executes inside the existing box; revocation kills that same box.
    assert len(commands) == 2 and all(isinstance(n.elts[1], ast.Constant) for n in commands)
    assert [n.elts[1].value for n in sorted(commands, key=lambda n: n.lineno)] == ["exec", "kill"]
    assert not _calls(writer, "_launch_container")
