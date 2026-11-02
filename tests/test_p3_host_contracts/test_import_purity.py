"""Cold source imports, including controls proving the guards actually reject."""

import ast
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

COLD_CHECK = textwrap.dedent(
    r"""
    import builtins
    import dataclasses
    import importlib.abc
    import io
    import os
    import pathlib
    import socket
    import subprocess
    import sys
    import typing

    root = pathlib.Path.cwd() / "p3_host_contracts"
    stdlib = pathlib.Path(os.__file__).parent
    blocked_modules = (
        "temper_ai", "p3_authority", "p3_source_closure", "adapters", "services",
        "keyring", "secrets", "requests", "httpx", "sqlalchemy", "docker",
    )
    assert not any(name.split(".")[0] in blocked_modules for name in sys.modules)
    assert not any(name.startswith("p3_host_contracts") for name in sys.modules)

    class GuardViolation(RuntimeError):
        pass

    def deny(*args, **kwargs):
        raise GuardViolation("host hook denied")

    class ImportGuard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in blocked_modules:
                raise GuardViolation("provider import denied")
            return None

    def audit(event, args):
        if event == "open":
            path, mode, flags = args
            # CPython's import loader must read source/bytecode. No data reads,
            # writes, arbitrary descriptors or paths outside these code roots.
            if not isinstance(path, str):
                raise GuardViolation("descriptor I/O denied")
            path = pathlib.Path(path)
            if not path.is_absolute():
                path = pathlib.Path.cwd() / path
            if not (path.is_relative_to(root) or path.is_relative_to(stdlib)):
                raise GuardViolation("non-code-root I/O denied")
            if path.suffix not in (".py", ".pyc") or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                raise GuardViolation("non-import I/O denied")
        elif event == "os.listdir":
            # The import loader scans package directories before loading code.
            directory = pathlib.Path(args[0])
            if directory not in (root, root.parent) and not directory.is_relative_to(stdlib):
                raise GuardViolation("non-code directory denied")
        elif event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn")) or event in (
            "os.system", "os.scandir", "os.mkdir", "os.remove", "os.rename", "os.putenv", "os.unsetenv",
        ):
            raise GuardViolation("host activity denied")

    class NoEnvironment(dict):
        __getitem__ = deny
        __iter__ = deny
        __contains__ = deny
        get = deny
        keys = deny
        values = deny
        items = deny

    sys.meta_path.insert(0, ImportGuard())
    sys.addaudithook(audit)
    builtins.open = deny
    io.open = deny
    for name in ("open", "stat", "listdir", "scandir", "read", "write", "getenv"):
        setattr(os, name, deny)
    os.environ = NoEnvironment()
    socket.socket = deny
    subprocess.Popen = deny
    for name in ("open", "read_text", "read_bytes", "stat"):
        setattr(pathlib.Path, name, deny)

    mode = sys.argv[1]
    if mode == "import":
        import p3_host_contracts
        assert len(p3_host_contracts.__all__) == 20
        assert not any(name.split(".")[0] in blocked_modules for name in sys.modules)
        print("cold import passed")
    else:
        controls = {
            "provider": lambda: __import__("temper_ai"),
            "authority": lambda: __import__("p3_authority"),
            "adapter": lambda: __import__("adapters"),
            "closure": lambda: __import__("p3_source_closure"),
            "secret": lambda: __import__("secrets"),
            "file": lambda: open("synthetic-secret"),
            "path": lambda: pathlib.Path("synthetic-secret").read_bytes(),
            "environment": lambda: os.getenv("SYNTHETIC_SECRET"),
            "environ": lambda: os.environ.get("SYNTHETIC_SECRET"),
            "socket": lambda: socket.socket(),
            "process": lambda: subprocess.Popen(["synthetic-program"]),
            "directory": lambda: os.listdir("."),
            "audit": lambda: sys.audit("open", "synthetic-secret", "r", 0),
        }
        try:
            controls[mode]()
        except GuardViolation:
            print("negative control blocked")
        else:
            raise AssertionError("guard did not block control")
"""
)


class ImportPurityTests(unittest.TestCase):
    def test_cold_import_and_negative_controls(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("PYTHON")
        }
        for mode in (
            "import",
            "provider",
            "authority",
            "adapter",
            "closure",
            "secret",
            "file",
            "path",
            "environment",
            "environ",
            "socket",
            "process",
            "directory",
            "audit",
        ):
            with self.subTest(mode=mode):
                result = subprocess.run(
                    [sys.executable, "-B", "-S", "-c", COLD_CHECK, mode],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                expected = (
                    "cold import passed\n"
                    if mode == "import"
                    else "negative control blocked\n"
                )
                self.assertEqual(result.stdout, expected)

    def test_source_import_graph_has_only_stdlib_and_leaf_edges(self):
        allowed = {"dataclasses", "typing", "__future__"}
        package = ROOT / "p3_host_contracts"
        modules = {path.stem for path in package.glob("*.py")}
        definitions = []
        for path in sorted(package.glob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name, allowed, path.name)
                if isinstance(node, ast.ImportFrom):
                    if node.level:
                        self.assertEqual(node.level, 1, path.name)
                        self.assertIn(node.module, modules, path.name)
                    else:
                        self.assertIn(node.module, allowed, path.name)
                if isinstance(node, ast.ClassDef):
                    definitions.append(node.name)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(
                        node.func.id, ("__import__", "eval", "exec", "open")
                    )
        import p3_host_contracts

        self.assertEqual(
            set(definitions), set(p3_host_contracts.__all__) - {"OperationKey"}
        )
        self.assertEqual(len(definitions), 19)


if __name__ == "__main__":
    unittest.main()
