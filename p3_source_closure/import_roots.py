"""Python source-module resolution over ordered import roots of committed Git trees.

An import root is ``(repository_id, directory)``: one ``sys.path`` entry inside one
repository's committed tree (``""`` is the repository root). Resolution mirrors
importlib's PathFinder/FileFinder for ``.py`` sources, one name part at a time: in
each search directory ``part/__init__.py`` (a regular package) wins, then
``part.py`` (a module); a directory without ``__init__.py`` is a namespace
portion, merged across roots in order. The first root holding a package or
module wins, exactly as the first ``sys.path`` entry does; there is no other
precedence. Declared modules (stdlib, installed packages, generated code) sit
after the roots, like the later ``sys.path`` entries they come from: one is used
for a name part no searched directory holds as a package or module, and it
beats namespace portions there, as a later regular package does in PathFinder.
Built from Git tree paths only, never from a working tree.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

ImportRoot = tuple[str, str]


def module_from_path(rel_path: str) -> tuple[str | None, str | None]:
    """Return (module name, package name) of a ``.py`` path relative to an import root."""
    if not rel_path.endswith(".py"):
        return None, None
    if rel_path == "__init__.py":
        return None, None
    if rel_path.endswith("/__init__.py"):
        mod = rel_path[: -len("/__init__.py")].replace("/", ".")
        return mod, mod
    mod = rel_path[:-3].replace("/", ".")
    pkg = mod.rpartition(".")[0]
    return mod, pkg


@dataclass(frozen=True, slots=True)
class RepositoryTree:
    """File and directory paths of one committed Git tree."""

    files: frozenset[str]
    directories: frozenset[str]

    @classmethod
    def from_paths(cls, paths: Iterable[str]) -> RepositoryTree:
        files = frozenset(paths)
        directories: set[str] = set()
        for path in files:
            parts = path.split("/")[:-1]
            for index in range(1, len(parts) + 1):
                directories.add("/".join(parts[:index]))
        return cls(files=files, directories=frozenset(directories))


@dataclass(frozen=True, slots=True)
class ResolvedModule:
    """One source module a dotted import name binds: its file and the name it binds as."""

    repository_id: str
    path: str
    module_name: str


@dataclass(frozen=True, slots=True)
class Resolution:
    """What ``import <name>`` binds: source files outermost first, then the declared module supplying the rest.

    files omits namespace-package parts (they bind no file); declared_module is None when
    the roots bind every part.
    """

    files: tuple[ResolvedModule, ...]
    declared_module: str | None


def _join(directory: str, name: str) -> str:
    return f"{directory}/{name}" if directory else name


def import_root_problems(roots: Sequence[ImportRoot], trees: Mapping[str, RepositoryTree]) -> list[str]:
    """List every defect of an ordered root list: unknown repository, malformed or missing directory, duplicate."""
    problems: list[str] = []
    seen: set[ImportRoot] = set()
    for root in roots:
        if not (isinstance(root, tuple) and len(root) == 2 and all(isinstance(part, str) for part in root)):
            problems.append(f"malformed_root:{root!r}")
            continue
        repository_id, directory = root
        if repository_id not in trees:
            problems.append(f"unknown_root_repository:{repository_id}")
            continue
        segments = directory.split("/") if directory else []
        if any(segment in ("", ".", "..") for segment in segments):
            problems.append(f"malformed_root_directory:{repository_id}:{directory}")
            continue
        if directory and directory not in trees[repository_id].directories:
            problems.append(f"missing_root_directory:{repository_id}:{directory}")
            continue
        if root in seen:
            problems.append(f"duplicate_root:{repository_id}:{directory}")
            continue
        seen.add(root)
    return problems


class ModuleRootResolver:
    """Resolve dotted module names over one ordered root list (one process profile's sys.path)."""

    def __init__(
        self,
        roots: Sequence[ImportRoot],
        trees: Mapping[str, RepositoryTree],
        declared_modules: frozenset[str] = frozenset(),
    ) -> None:
        problems = import_root_problems(roots, trees)
        if problems:
            raise ValueError(", ".join(problems))
        if not roots:
            raise ValueError("empty_import_roots")
        self._roots: tuple[ImportRoot, ...] = tuple(roots)
        self._trees = trees
        self._declared_modules = declared_modules

    def _declared_prefix(self, parts: Sequence[str], unbound_index: int) -> str | None:
        """Longest declared module name that is a prefix of parts and names part unbound_index or deeper."""
        for end in range(len(parts), unbound_index, -1):
            prefix = ".".join(parts[:end])
            if prefix in self._declared_modules:
                return prefix
        return None

    def resolve(self, module_name: str) -> Resolution | None:
        """Return what ``import <module_name>`` binds; None when it binds nothing (ImportError)."""
        parts = module_name.split(".") if module_name else []
        if not parts or any(not part for part in parts):
            return None
        search: list[ImportRoot] = list(self._roots)
        bound: list[ResolvedModule] = []
        for index, part in enumerate(parts):
            name = ".".join(parts[: index + 1])
            if index and not search:
                return None  # the previous part is a module, not a package: it has no submodules
            portions: list[ImportRoot] = []
            found: ResolvedModule | None = None
            package_dir: ImportRoot | None = None
            for repository_id, directory in search:
                tree = self._trees[repository_id]
                base = _join(directory, part)
                if f"{base}/__init__.py" in tree.files:
                    found = ResolvedModule(repository_id, f"{base}/__init__.py", name)
                    package_dir = (repository_id, base)
                    break
                if f"{base}.py" in tree.files:
                    found = ResolvedModule(repository_id, f"{base}.py", name)
                    break
                if base in tree.directories:
                    portions.append((repository_id, base))
            if found is not None:
                bound.append(found)
                search = [package_dir] if package_dir is not None else []
                continue
            declared = self._declared_prefix(parts, index)
            if declared is not None:
                return Resolution(tuple(bound), declared)
            if not portions:
                return None
            search = portions
        return Resolution(tuple(bound), None)

    def module_name_for_file(self, repository_id: str, path: str) -> str | None:
        """Name under which ``path`` resolves: first root holding it whose resolution binds this file."""
        for root_repository, directory in self._roots:
            if root_repository != repository_id:
                continue
            if directory and not path.startswith(f"{directory}/"):
                continue
            relative = path[len(directory) + 1 :] if directory else path
            module_name, _package = module_from_path(relative)
            if module_name is None:
                continue
            resolution = self.resolve(module_name)
            if resolution is None or resolution.declared_module is not None or not resolution.files:
                continue
            if resolution.files[-1].repository_id == repository_id and resolution.files[-1].path == path:
                return module_name
        return None
