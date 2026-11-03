"""Known-answer and fault-proof tests for p3_source_closure.graph_builder."""

from __future__ import annotations

import dataclasses
import inspect
import subprocess
import textwrap
from pathlib import Path

import pytest

import p3_source_closure as public
from configs.architecture.bin import ops_host_source_comparison as facade
from p3_source_closure import (
    ArtifactProvenance,
    CachedProvenance,
    DeclaredNodeSpec,
    DynamicImportSpec,
    EntrypointSpec,
    EvidenceRef,
    GeneratedProvenance,
    GraphBuildError,
    ProcessProfileSpec,
    RepositorySpec,
    ReviewedSourceGraph,
    SourceNode,
    build_reviewed_source_graph,
    validate_reviewed_graph,
)
from p3_source_closure import graph_builder as gb_mod
from p3_source_closure.parsing import byte_identity, canonical_bytes


def _git(repo_dir: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    return proc.stdout.strip()


def _ref(record_id: str) -> EvidenceRef:
    return EvidenceRef(
        "p3-evidence/1",
        byte_identity(f"evidence:{record_id}".encode("ascii")),
        "independent-verifier",
        record_id,
    )


def _content(tag: str):
    return byte_identity(tag.encode("utf-8"))


def _declared_inventory() -> tuple[SourceNode | DeclaredNodeSpec, ...]:
    nodes: list[SourceNode | DeclaredNodeSpec] = []
    for scope in ("host", "worker"):
        interp_id = f"interpreter-{scope}"
        stdlib_id = f"stdlib-{scope}"
        native_id = f"native_binary-{scope}"
        interp_node = SourceNode(
            interp_id,
            "interpreter",
            _content(interp_id),
            interp_id,
            "0755",
            ArtifactProvenance(
                "artifact",
                _content(interp_id),
                _content(f"build-{scope}"),
                ("main",),
                (),
                interp_id,
                "cpython-312-x86_64-linux-gnu",
                "bytes",
                _content(interp_id),
                _ref(f"artifact-{interp_id}"),
            ),
        )
        stdlib_node = SourceNode(
            stdlib_id,
            "stdlib",
            _content(stdlib_id),
            stdlib_id,
            "0644",
            ArtifactProvenance(
                "artifact",
                _content(stdlib_id),
                _content(f"build-{scope}"),
                ("main",),
                (interp_id,),
                interp_id,
                "cpython-312-x86_64-linux-gnu",
                "bytes",
                _content(stdlib_id),
                _ref(f"artifact-{stdlib_id}"),
            ),
        )
        native_node = SourceNode(
            native_id,
            "native_binary",
            _content(native_id),
            native_id,
            "0755",
            ArtifactProvenance(
                "artifact",
                _content(native_id),
                _content(f"build-{scope}"),
                ("main",),
                (interp_id,),
                interp_id,
                "cpython-312-x86_64-linux-gnu",
                "relocated",
                _content(f"relocated-{native_id}"),
                _ref(f"artifact-{native_id}"),
            ),
        )
        nodes.extend(
            (
                interp_node,
                DeclaredNodeSpec(
                    node=stdlib_node,
                    module_names=("json", "importlib") if scope == "host" else (),
                ),
                native_node,
            )
        )
    gen_node = SourceNode(
        "generated",
        "generated",
        _content("generated-source"),
        "gen/out.py",
        "0644",
        GeneratedProvenance(
            "generated",
            ("pkg.dep",),
            ("main",),
            ("interpreter-host",),
            _content("recipe"),
            _content("generated-source"),
            _content("generated-code"),
            _ref("generation"),
        ),
    )
    cache_node = SourceNode(
        "cache",
        "cached_code",
        _content("main-pyc"),
        "__pycache__/main.cpython-312.pyc",
        "0644",
        CachedProvenance(
            "cache",
            ("main", "generated"),
            "interpreter-host",
            "cpython-312-pyc",
            _content("main-pyc"),
            _ref("cache"),
        ),
    )
    nodes.extend((gen_node, cache_node))
    return tuple(nodes)


def _create_known_repo(tmp_path: Path) -> tuple[Path, str, dict[str, bytes]]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "systems@example.invalid")
    _git(repo, "config", "user.name", "Systems Test")

    files: dict[str, bytes] = {
        "main.py": (
            b"import importlib\n"
            b"import json\n"
            b"from pkg import dep\n\n"
            b"def run(load_opt: bool = False) -> str:\n"
            b"    if load_opt:\n"
            b"        importlib.import_module('optional')\n"
            b"    return json.dumps({'val': dep.value()})\n"
        ),
        "pkg/__init__.py": b"PACKAGE_VERSION = '1'\n",
        "pkg/dep.py": (
            b"from . import helper\n"
            b"import main\n\n"
            b"def value() -> int:\n"
            b"    return helper.base()\n"
        ),
        "pkg/helper.py": b"def base() -> int:\n    return 42\n",
        "optional.py": b"OPTIONAL_FLAG = True\n",
    }
    for rel_path, raw in files.items():
        full = repo / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(raw)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial known-answer tree")
    commit = _git(repo, "rev-parse", "HEAD")
    return repo, commit, files


def _default_specs() -> tuple[tuple[EntrypointSpec, ...], tuple[ProcessProfileSpec, ...], tuple[DynamicImportSpec, ...]]:
    entrypoints = (
        EntrypointSpec(
            id="host-entry",
            profile_id="host",
            target="main.py",
            symbol="main:run",
            bootstrap_chain=("pkg/dep.py",),
        ),
        EntrypointSpec(
            id="worker-entry",
            profile_id="worker",
            target="main.py",
            symbol="main:run",
            bootstrap_chain=("pkg/dep.py",),
        ),
        EntrypointSpec(
            id="child-entry",
            profile_id="child",
            target="main.py",
            symbol="main:run",
            bootstrap_chain=("pkg/dep.py",),
        ),
    )
    profiles = (
        ProcessProfileSpec(
            id="host",
            role="controller",
            entrypoint_ids=("host-entry",),
            runtime_nodes=("interpreter-host", "stdlib-host"),
            extra_required_load_ids=("generated", "cache", "native_binary-host"),
            child_profiles=("worker",),
            load_policy_ref=_ref("policy-host"),
        ),
        ProcessProfileSpec(
            id="worker",
            role="worker",
            entrypoint_ids=("worker-entry",),
            runtime_nodes=("interpreter-worker", "stdlib-worker"),
            extra_required_load_ids=("generated", "cache", "native_binary-worker"),
            child_profiles=("child",),
            load_policy_ref=_ref("policy-worker"),
        ),
        ProcessProfileSpec(
            id="child",
            role="child",
            entrypoint_ids=("child-entry",),
            runtime_nodes=("interpreter-worker", "stdlib-worker"),
            extra_required_load_ids=("generated", "cache", "native_binary-worker"),
            child_profiles=(),
            load_policy_ref=_ref("policy-child"),
        ),
    )
    dynamic_imports = (
        DynamicImportSpec(
            source="main.py",
            target="optional.py",
            condition_ref=_ref("condition"),
        ),
    )
    return entrypoints, profiles, dynamic_imports


def install_mutation(monkeypatch, owner, function: str, before: str, after: str) -> None:
    original = getattr(owner, function)
    source = textwrap.dedent(inspect.getsource(original))
    assert source.count(before) == 1
    namespace = dict(original.__globals__)
    exec(compile(source.replace(before, after), "<graph-builder-mutation>", "exec"), namespace)
    monkeypatch.setattr(owner, function, namespace[function])


def test_build_reviewed_source_graph_known_answer_and_reexports(tmp_path: Path) -> None:
    assert public.build_reviewed_source_graph is build_reviewed_source_graph
    assert facade.build_reviewed_source_graph is build_reviewed_source_graph
    assert public.GraphBuildError is GraphBuildError

    repo, commit, files = _create_known_repo(tmp_path)
    entrypoints, profiles, dynamic_imports = _default_specs()

    reviewed = build_reviewed_source_graph(
        repo_path=repo,
        commit=commit,
        entrypoints=entrypoints,
        process_profiles=profiles,
        declared_nodes=_declared_inventory(),
        dynamic_imports=dynamic_imports,
        graph_id="graph-known-1",
        repository_id="repo",
        repository_owner="temper",
    )

    assert reviewed.graph.schema == "p3-reviewed-source-graph/1"
    assert reviewed.graph.completeness_review_ref is None
    assert validate_reviewed_graph(canonical_bytes(reviewed.graph)) == reviewed

    nodes_by_id = {n.id: n for n in reviewed.graph.nodes}
    assert {"main", "pkg", "pkg.dep", "pkg.helper", "optional"} <= nodes_by_id.keys()
    assert nodes_by_id["main"].content == byte_identity(files["main.py"])
    assert nodes_by_id["pkg.dep"].content == byte_identity(files["pkg/dep.py"])
    assert nodes_by_id["pkg.helper"].content == byte_identity(files["pkg/helper.py"])

    edge_triples = {(e.source, e.target, e.kind) for e in reviewed.graph.edges}
    assert ("main", "pkg.dep", "import") in edge_triples
    assert ("main", "pkg", "import") in edge_triples
    assert ("main", "pkg.dep", "bootstrap") in edge_triples
    assert ("pkg.dep", "pkg.helper", "import") in edge_triples
    assert ("pkg.dep", "main", "import") in edge_triples
    assert ("main", "optional", "dynamic_import") in edge_triples
    assert ("main", "generated", "generated_input") in edge_triples
    assert ("pkg.dep", "generated", "generates") in edge_triples
    assert ("cache", "main", "cache_of") in edge_triples
    assert ("main", "main", "spawns") in edge_triples

    host_prof = next(p for p in reviewed.graph.process_profiles if p.id == "host")
    assert {"main", "pkg", "pkg.dep", "pkg.helper", "generated", "cache", "native_binary-host"} <= set(host_prof.required_load_ids)
    assert "optional" not in host_prof.required_load_ids
    assert "optional" in host_prof.allowed_node_ids


def test_generator_reads_only_committed_git_objects_ignoring_dirty_and_untracked(tmp_path: Path) -> None:
    repo, commit, files = _create_known_repo(tmp_path)
    entrypoints, profiles, dynamic_imports = _default_specs()

    # Dirty main.py in working tree and add an untracked file on disk.
    (repo / "main.py").write_bytes(b"raise RuntimeError('dirty working tree')\n")
    (repo / "untracked.py").write_bytes(b"UNTRACKED = 1\n")

    reviewed = build_reviewed_source_graph(
        repo_path=repo,
        commit=commit,
        entrypoints=entrypoints,
        process_profiles=profiles,
        declared_nodes=_declared_inventory(),
        dynamic_imports=dynamic_imports,
    )
    nodes_by_id = {n.id: n for n in reviewed.graph.nodes}
    assert nodes_by_id["main"].content == byte_identity(files["main.py"])
    assert "untracked" not in nodes_by_id

    # Referencing the untracked working-tree file as an entrypoint fails loud.
    bad_entrypoints = (
        *entrypoints,
        EntrypointSpec(
            id="untracked-entry",
            profile_id="host",
            target="untracked.py",
            symbol="untracked:run",
        ),
    )
    with pytest.raises(GraphBuildError) as exc_info:
        build_reviewed_source_graph(
            repo_path=repo,
            commit=commit,
            entrypoints=bad_entrypoints,
            process_profiles=profiles,
            declared_nodes=_declared_inventory(),
            dynamic_imports=dynamic_imports,
        )
    assert exc_info.value.code == "INVALID_GRAPH_SPEC"
    assert "unknown_entrypoint_target:untracked-entry:untracked.py" in exc_info.value.items


def test_generator_fails_loud_listing_unresolved_static_imports(tmp_path: Path) -> None:
    repo, _commit, _files = _create_known_repo(tmp_path)
    (repo / "main.py").write_bytes(
        b"import missing_alpha\n"
        b"from missing_pkg import missing_beta\n"
    )
    _git(repo, "add", "main.py")
    _git(repo, "commit", "-q", "-m", "introduce unresolved imports")
    bad_commit = _git(repo, "rev-parse", "HEAD")

    entrypoints, profiles, _dyn = _default_specs()
    with pytest.raises(GraphBuildError) as exc_info:
        build_reviewed_source_graph(
            repo_path=repo,
            commit=bad_commit,
            entrypoints=entrypoints,
            process_profiles=profiles,
            declared_nodes=_declared_inventory(),
        )
    assert exc_info.value.code == "UNRESOLVED_CLOSURE"
    assert "main.py:1:unresolved_import:missing_alpha" in exc_info.value.items
    assert "main.py:2:unresolved_import:missing_pkg.missing_beta" in exc_info.value.items


def test_generator_fails_loud_listing_unresolved_dynamic_imports_and_exec(tmp_path: Path) -> None:
    repo, _commit, _files = _create_known_repo(tmp_path)
    (repo / "main.py").write_bytes(
        b"import importlib\n"
        b"def run(mod_name: str) -> None:\n"
        b"    importlib.import_module(mod_name)\n"
        b"    __import__('optional')\n"
        b"    exec('x = 1')\n"
    )
    _git(repo, "add", "main.py")
    _git(repo, "commit", "-q", "-m", "introduce dynamic constructs")
    bad_commit = _git(repo, "rev-parse", "HEAD")

    entrypoints, profiles, _dyn = _default_specs()
    with pytest.raises(GraphBuildError) as exc_info:
        build_reviewed_source_graph(
            repo_path=repo,
            commit=bad_commit,
            entrypoints=entrypoints,
            process_profiles=profiles,
            declared_nodes=_declared_inventory(),
            dynamic_imports=(),
        )
    assert exc_info.value.code == "UNRESOLVED_CLOSURE"
    assert "main.py:3:unresolved_dynamic:*.import_module" in exc_info.value.items
    assert "main.py:4:unresolved_dynamic:__import__(optional)" in exc_info.value.items
    assert "main.py:5:unresolved_dynamic:exec" in exc_info.value.items


@pytest.mark.parametrize(
    "source_bytes,before,after",
    [
        (
            b"import missing_alpha\n",
            'errors.append(f"{rel_path}:{node.lineno}:unresolved_import:{alias.name}")',
            "pass",
        ),
        (
            b"exec('x = 1')\n",
            'if isinstance(func, ast.Name) and func.id in ("exec", "eval", "compile"):',
            "if False:",
        ),
    ],
)
def test_generator_guard_mutations_killed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_bytes: bytes,
    before: str,
    after: str,
) -> None:
    repo, _commit, _files = _create_known_repo(tmp_path)
    (repo / "main.py").write_bytes(source_bytes)
    _git(repo, "add", "main.py")
    _git(repo, "commit", "-q", "-m", "fault case")
    fault_commit = _git(repo, "rev-parse", "HEAD")
    entrypoints, profiles, _dyn = _default_specs()

    def check_rejects() -> None:
        try:
            build_reviewed_source_graph(
                repo_path=repo,
                commit=fault_commit,
                entrypoints=entrypoints,
                process_profiles=profiles,
                declared_nodes=_declared_inventory(),
            )
        except GraphBuildError:
            return
        raise AssertionError("expected GraphBuildError for faulty source")

    check_rejects()
    install_mutation(monkeypatch, gb_mod, "_collect_module_ast_deps", before, after)
    with pytest.raises(AssertionError):
        check_rejects()


# --- Several repositories and per-profile import roots (Systems #93, H-N3-MULTIREPO-1) ---


def _commit_tree(repo: Path, files: dict[str, bytes], message: str = "tree") -> str:
    if not (repo / ".git").exists():
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "systems@example.invalid")
        _git(repo, "config", "user.name", "Systems Test")
    for rel_path, raw in files.items():
        full = repo / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(raw)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _runtime_inventory() -> tuple[SourceNode | DeclaredNodeSpec, ...]:
    """Runtime nodes of _declared_inventory without its single-repository ids (generated, cache, source "main")."""
    keep: list[SourceNode | DeclaredNodeSpec] = []
    for item in _declared_inventory():
        node = item.node if isinstance(item, DeclaredNodeSpec) else item
        if node.id in ("generated", "cache"):
            continue
        node = dataclasses.replace(node, provenance=dataclasses.replace(node.provenance, sources=()))
        keep.append(DeclaredNodeSpec(node, item.module_names) if isinstance(item, DeclaredNodeSpec) else node)
    return tuple(keep)


def _profile(profile_id: str, entry_ids: tuple[str, ...], module_path: tuple[tuple[str, str], ...], **extra) -> ProcessProfileSpec:
    return ProcessProfileSpec(
        id=profile_id,
        role="worker",
        entrypoint_ids=entry_ids,
        runtime_nodes=("interpreter-host", "stdlib-host"),
        load_policy_ref=_ref(f"policy-{profile_id}"),
        module_path=module_path,
        **extra,
    )


def _two_repositories(tmp_path: Path) -> tuple[RepositorySpec, RepositorySpec]:
    host_commit = _commit_tree(
        tmp_path / "host",
        {
            "bin/run.py": b"import helper\nimport sharedlib\nfrom toolkit import core\nimport json\n",
            "bin/helper.py": b"VALUE = 1\n",
            "toolkit/__init__.py": b"from . import core\n",
            "toolkit/core.py": b"CORE = 1\n",
        },
    )
    lib_commit = _commit_tree(
        tmp_path / "lib",
        {
            "sharedlib/__init__.py": b"from .impl import compute\n",
            "sharedlib/impl.py": b"def compute() -> int:\n    return 1\n",
        },
    )
    return (
        RepositorySpec("host", "ops", tmp_path / "host", host_commit),
        RepositorySpec("lib", "temper", tmp_path / "lib", lib_commit),
    )


HOST_ROOTS = (("host", "bin"), ("host", ""), ("lib", ""))


def test_multi_repository_cross_repo_imports_and_script_directory_root(tmp_path: Path) -> None:
    assert public.RepositorySpec is RepositorySpec
    host, lib = _two_repositories(tmp_path)
    reviewed = build_reviewed_source_graph(
        repositories=(host, lib),
        entrypoints=(EntrypointSpec("run", "p", "host:bin/run.py", "run:main"),),
        process_profiles=(_profile("p", ("run",), HOST_ROOTS),),
        declared_nodes=_runtime_inventory(),
        graph_id="graph-multi-1",
    )
    graph = reviewed.graph
    assert validate_reviewed_graph(canonical_bytes(graph)) == reviewed
    assert graph.completeness_review_ref is None
    assert [(r.id, r.owner, r.commit) for r in graph.repositories] == [("host", "ops", host.commit), ("lib", "temper", lib.commit)]

    nodes = {n.id: n for n in graph.nodes}
    git_ids = {"host.bin.run", "host.bin.helper", "host.toolkit", "host.toolkit.core", "lib.sharedlib", "lib.sharedlib.impl"}
    assert git_ids | {"stdlib-host", "interpreter-host"} == set(nodes)
    assert nodes["lib.sharedlib.impl"].provenance.repository == "lib"
    assert nodes["lib.sharedlib.impl"].provenance.commit == lib.commit
    assert nodes["lib.sharedlib.impl"].provenance.path == "sharedlib/impl.py"
    assert nodes["lib.sharedlib.impl"].logical_origin == "git:lib:sharedlib/impl.py"
    assert nodes["host.bin.helper"].provenance.repository == "host"
    assert nodes["host.bin.helper"].content == byte_identity(b"VALUE = 1\n")

    edges = {(e.source, e.target, e.kind) for e in graph.edges}
    assert {
        ("host.bin.run", "host.bin.helper", "import"),
        ("host.bin.run", "lib.sharedlib", "import"),
        ("host.bin.run", "host.toolkit", "import"),
        ("host.bin.run", "host.toolkit.core", "import"),
        ("host.bin.run", "stdlib-host", "import"),
        ("host.toolkit", "host.toolkit.core", "import"),
        ("lib.sharedlib", "lib.sharedlib.impl", "import"),
    } <= edges
    profile = graph.process_profiles[0]
    assert git_ids <= set(profile.required_load_ids)


@pytest.mark.parametrize(
    "roots,expected,shadowed",
    [
        ((("r", "bin"), ("r", "")), "r.bin.util", "r.util"),
        ((("r", ""), ("r", "bin")), "r.util", "r.bin.util"),
    ],
)
def test_first_root_holding_the_module_wins(tmp_path: Path, roots, expected: str, shadowed: str) -> None:
    commit = _commit_tree(
        tmp_path / "r",
        {"bin/main.py": b"import util\n", "bin/util.py": b"WHERE = 'bin'\n", "util.py": b"WHERE = 'root'\n"},
    )
    reviewed = build_reviewed_source_graph(
        repositories=(RepositorySpec("r", "temper", tmp_path / "r", commit),),
        entrypoints=(EntrypointSpec("e", "p", "r:bin/main.py", "main"),),
        process_profiles=(_profile("p", ("e",), roots),),
        declared_nodes=_runtime_inventory(),
    )
    node_ids = {n.id for n in reviewed.graph.nodes}
    assert ("r.bin.main", expected, "import") in {(e.source, e.target, e.kind) for e in reviewed.graph.edges}
    assert expected in node_ids
    assert shadowed not in node_ids


def test_conflicting_resolution_across_profiles_fails_loud(tmp_path: Path) -> None:
    commit = _commit_tree(
        tmp_path / "r",
        {"shared.py": b"import util\n", "one/util.py": b"A = 1\n", "two/util.py": b"B = 2\n"},
    )
    repository = RepositorySpec("r", "temper", tmp_path / "r", commit)
    with pytest.raises(GraphBuildError) as exc_info:
        build_reviewed_source_graph(
            repositories=(repository,),
            entrypoints=(
                EntrypointSpec("ea", "a", "r:shared.py", "shared"),
                EntrypointSpec("eb", "b", "r:shared.py", "shared"),
            ),
            process_profiles=(
                _profile("a", ("ea",), (("r", "one"), ("r", ""))),
                _profile("b", ("eb",), (("r", "two"), ("r", ""))),
            ),
            declared_nodes=_runtime_inventory(),
        )
    assert exc_info.value.code == "CONFLICTING_RESOLUTION"
    assert exc_info.value.items == ("r.shared:a/shared:b/shared",)

    # Same roots in both profiles: one resolution, no conflict.
    reviewed = build_reviewed_source_graph(
        repositories=(repository,),
        entrypoints=(
            EntrypointSpec("ea", "a", "r:shared.py", "shared"),
            EntrypointSpec("eb", "b", "r:shared.py", "shared"),
        ),
        process_profiles=(
            _profile("a", ("ea",), (("r", "one"), ("r", ""))),
            _profile("b", ("eb",), (("r", "one"), ("r", ""))),
        ),
        declared_nodes=_runtime_inventory(),
    )
    assert ("r.shared", "r.one.util", "import") in {(e.source, e.target, e.kind) for e in reviewed.graph.edges}


def test_multi_repository_spec_errors_fail_loud(tmp_path: Path) -> None:
    host, lib = _two_repositories(tmp_path)
    entry = EntrypointSpec("run", "p", "host:bin/run.py", "run:main")
    good_profile = _profile("p", ("run",), HOST_ROOTS)

    def spec_error(**overrides) -> GraphBuildError:
        kwargs = {
            "repositories": (host, lib),
            "entrypoints": (entry,),
            "process_profiles": (good_profile,),
            "declared_nodes": _runtime_inventory(),
            **overrides,
        }
        with pytest.raises(GraphBuildError) as exc_info:
            build_reviewed_source_graph(**kwargs)
        return exc_info.value

    unqualified = spec_error(
        entrypoints=(EntrypointSpec("run", "p", "bin/run.py", "run:main", bootstrap_chain=("toolkit",)),),
        process_profiles=(_profile("p", ("run",), HOST_ROOTS, extra_required_load_ids=("toolkit.core",), extra_allowed_node_ids=("sharedlib",)),),
        dynamic_imports=(DynamicImportSpec("bin/run.py", "host:toolkit", _ref("condition")),),
    )
    assert unqualified.code == "INVALID_GRAPH_SPEC"
    assert unqualified.items == (
        "unqualified_ref:dynamic_import:bin/run.py->host:toolkit",
        "unqualified_ref:unknown_allowed_node:p:sharedlib",
        "unqualified_ref:unknown_bootstrap_target:run:toolkit",
        "unqualified_ref:unknown_entrypoint_target:run:bin/run.py",
        "unqualified_ref:unknown_required_load:p:toolkit.core",
    )
    unknown = spec_error(entrypoints=(EntrypointSpec("run", "p", "nope:bin/run.py", "run:main"),))
    assert unknown.items == ("unknown_entrypoint_target:run:nope:bin/run.py",)

    missing = spec_error(process_profiles=(_profile("p", ("run",), ()),))
    assert missing.code == "INVALID_GRAPH_SPEC"
    assert missing.items == ("missing_module_path:p",)
    bad_roots = spec_error(process_profiles=(_profile("p", ("run",), (("host", "absent"), ("other", ""), ("host", "../x"))),))
    assert bad_roots.items == (
        "invalid_module_path:p:malformed_root_directory:host:../x",
        "invalid_module_path:p:missing_root_directory:host:absent",
        "invalid_module_path:p:unknown_root_repository:other",
    )

    both = spec_error(repo_path=tmp_path / "host", commit=host.commit)
    assert both.code == "INVALID_REPOSITORY_FORM"
    neither = spec_error(repositories=None)
    assert neither.code == "INVALID_REPOSITORY_FORM"
    duplicate = spec_error(repositories=(host, RepositorySpec("host", "temper", lib.repo_path, lib.commit)))
    assert duplicate.code == "INVALID_REPOSITORY_SPEC"
    assert duplicate.items == ("duplicate_repository_id:host",)
    bad_owner = spec_error(repositories=(host, RepositorySpec("lib", "nobody", lib.repo_path, lib.commit)))
    assert bad_owner.items == ("invalid_repository_owner:lib:nobody",)

    single_with_roots = spec_error(
        repositories=None,
        repo_path=tmp_path / "host",
        commit=host.commit,
        entrypoints=(EntrypointSpec("run", "p", "bin/run.py", "run:main"),),
    )
    assert single_with_roots.items == ("module_path_needs_repositories:p",)


def test_multi_repository_declared_dynamic_imports(tmp_path: Path) -> None:
    commit = _commit_tree(
        tmp_path / "r",
        {
            "bin/main.py": b"import importlib\nimportlib.import_module('plugin')\n__import__('json')\n",
            "bin/plugin.py": b"P = 1\n",
        },
    )
    kwargs = {
        "repositories": (RepositorySpec("r", "temper", tmp_path / "r", commit),),
        "entrypoints": (EntrypointSpec("e", "p", "r:bin/main.py", "main"),),
        "process_profiles": (_profile("p", ("e",), (("r", "bin"),)),),
        "declared_nodes": _runtime_inventory(),
    }
    reviewed = build_reviewed_source_graph(
        **kwargs,
        dynamic_imports=(
            DynamicImportSpec("r:bin/main.py", "r:bin/plugin.py", _ref("plugin-condition")),
            DynamicImportSpec("r:bin/main.py", "json", _ref("json-condition")),
        ),
    )
    edges = {(e.source, e.target, e.kind) for e in reviewed.graph.edges}
    assert {("r.bin.main", "r.bin.plugin", "dynamic_import"), ("r.bin.main", "stdlib-host", "dynamic_import")} <= edges
    profile = reviewed.graph.process_profiles[0]
    assert "r.bin.plugin" in profile.allowed_node_ids
    assert "r.bin.plugin" not in profile.required_load_ids
    with pytest.raises(GraphBuildError) as exc_info:
        build_reviewed_source_graph(**kwargs)
    assert exc_info.value.items == (
        "r:bin/main.py:2:unresolved_dynamic:*.import_module(plugin)",
        "r:bin/main.py:3:unresolved_dynamic:__import__(json)",
    )


def test_relative_import_without_parent_package_fails_loud(tmp_path: Path) -> None:
    commit = _commit_tree(tmp_path / "r", {"bin/main.py": b"from . import sibling\n", "bin/sibling.py": b"S = 1\n"})
    with pytest.raises(GraphBuildError) as exc_info:
        build_reviewed_source_graph(
            repositories=(RepositorySpec("r", "temper", tmp_path / "r", commit),),
            entrypoints=(EntrypointSpec("e", "p", "r:bin/main.py", "main"),),
            process_profiles=(_profile("p", ("e",), (("r", "bin"),)),),
            declared_nodes=_runtime_inventory(),
        )
    assert exc_info.value.code == "UNRESOLVED_CLOSURE"
    assert exc_info.value.items == ("r:bin/main.py:1:unresolved_import:relative_without_package",)


def test_same_repository_at_two_commits_is_two_repositories(tmp_path: Path) -> None:
    old_commit = _commit_tree(tmp_path / "r", {"main.py": b"A = 1\n"}, "old")
    new_commit = _commit_tree(tmp_path / "r", {"main.py": b"A = 2\n"}, "new")
    reviewed = build_reviewed_source_graph(
        repositories=(
            RepositorySpec("old", "temper", tmp_path / "r", old_commit),
            RepositorySpec("new", "temper", tmp_path / "r", new_commit),
        ),
        entrypoints=(EntrypointSpec("eo", "po", "old:main", "main"), EntrypointSpec("en", "pn", "new:main.py", "main")),
        process_profiles=(_profile("po", ("eo",), (("old", ""),)), _profile("pn", ("en",), (("new", ""),))),
        declared_nodes=_runtime_inventory(),
    )
    assert validate_reviewed_graph(canonical_bytes(reviewed.graph)) == reviewed
    nodes = {n.id: n for n in reviewed.graph.nodes}
    assert nodes["old.main"].content == byte_identity(b"A = 1\n")
    assert nodes["new.main"].content == byte_identity(b"A = 2\n")
    assert (nodes["old.main"].provenance.commit, nodes["new.main"].provenance.commit) == (old_commit, new_commit)
    assert [(r.id, r.commit) for r in reviewed.graph.repositories] == [("old", old_commit), ("new", new_commit)]


def test_prefixed_node_id_overflow_and_collision_fail_loud(tmp_path: Path) -> None:
    long_path = f"{'a' * 70}/{'b' * 70}.py"
    commit = _commit_tree(tmp_path / "r", {"main.py": b"import " + f"{'a' * 70}.{'b' * 70}".encode() + b"\n", long_path: b"X = 1\n"})
    with pytest.raises(GraphBuildError) as exc_info:
        build_reviewed_source_graph(
            repositories=(RepositorySpec("r", "temper", tmp_path / "r", commit),),
            entrypoints=(EntrypointSpec("e", "p", "r:main.py", "main"),),
            process_profiles=(_profile("p", ("e",), (("r", ""),)),),
            declared_nodes=_runtime_inventory(),
        )
    assert exc_info.value.code == "UNRESOLVED_CLOSURE"
    assert exc_info.value.items == (f"r:{long_path}:0:invalid_node_id:r.{'a' * 70}.{'b' * 70}",)

    a_commit = _commit_tree(tmp_path / "a", {"b/c.py": b"C = 1\n"})
    ab_commit = _commit_tree(tmp_path / "ab", {"c.py": b"C = 2\n"})
    with pytest.raises(GraphBuildError) as exc_info:
        build_reviewed_source_graph(
            repositories=(
                RepositorySpec("a", "temper", tmp_path / "a", a_commit),
                RepositorySpec("a.b", "temper", tmp_path / "ab", ab_commit),
            ),
            entrypoints=(EntrypointSpec("e", "p", "a:b/c.py", "c"),),
            process_profiles=(_profile("p", ("e",), (("a", ""),)),),
            declared_nodes=_runtime_inventory(),
        )
    assert exc_info.value.code == "NODE_ID_COLLISION"
    assert exc_info.value.items == ("a.b.c:a:b/c.py:a.b:c.py",)


def _declared_package(node_id: str, module_names: tuple[str, ...]) -> DeclaredNodeSpec:
    """A declared installed package, shaped like _runtime_inventory's stdlib node."""
    stdlib = next(item for item in _runtime_inventory() if isinstance(item, DeclaredNodeSpec) and item.node.id == "stdlib-host")
    return DeclaredNodeSpec(dataclasses.replace(stdlib.node, id=node_id, kind="package", logical_origin=node_id), module_names)


def test_declared_module_beats_a_root_namespace_portion(tmp_path: Path) -> None:
    # PathFinder keeps scanning sys.path past a namespace portion; a later regular package wins.
    commit = _commit_tree(tmp_path / "r", {"main.py": b"import yaml\n", "yaml/README.md": b"data, not a package\n"})
    spec = {
        "repositories": (RepositorySpec("r", "temper", tmp_path / "r", commit),),
        "entrypoints": (EntrypointSpec("e", "p", "r:main.py", "main"),),
        "process_profiles": (_profile("p", ("e",), (("r", ""),)),),
    }
    declared = build_reviewed_source_graph(**spec, declared_nodes=(*_runtime_inventory(), _declared_package("yaml-pkg", ("yaml",))))
    assert ("r.main", "yaml-pkg", "import") in {(e.source, e.target, e.kind) for e in declared.graph.edges}
    namespace_only = build_reviewed_source_graph(**spec, declared_nodes=_runtime_inventory())
    assert [e for e in namespace_only.graph.edges if e.source == "r.main"] == []


def test_declared_module_never_supplies_a_submodule_of_a_root_module(tmp_path: Path) -> None:
    # A regular package found on a root binds its submodule search to its own directory; a module has none.
    declared = (
        *_runtime_inventory(),
        _declared_package("pkg-dist", ("pkg",)),
        _declared_package("pkg-extra", ("pkg.extra",)),
        _declared_package("mod-sub", ("mod.sub",)),
    )
    repository = tmp_path / "r"
    files = {"pkg/__init__.py": b"", "mod.py": b"M = 1\n"}
    bad = _commit_tree(repository, {**files, "main.py": b"import pkg.missing\nimport mod.sub\n"}, "bad")
    good = _commit_tree(repository, {**files, "main.py": b"import pkg.extra\nfrom pkg import extra\n"}, "good")

    def build(commit: str) -> ReviewedSourceGraph:
        return build_reviewed_source_graph(
            repositories=(RepositorySpec("r", "temper", repository, commit),),
            entrypoints=(EntrypointSpec("e", "p", "r:main.py", "main"),),
            process_profiles=(_profile("p", ("e",), (("r", ""),)),),
            declared_nodes=declared,
        )

    with pytest.raises(GraphBuildError) as exc_info:
        build(bad)
    assert exc_info.value.code == "UNRESOLVED_CLOSURE"
    assert exc_info.value.items == ("r:main.py:1:unresolved_import:pkg.missing", "r:main.py:2:unresolved_import:mod.sub")
    edges = {(e.source, e.target, e.kind) for e in build(good).graph.edges if e.source == "r.main"}
    assert edges == {("r.main", "r.pkg", "import"), ("r.main", "pkg-extra", "import")}


def _one_repository_two_roots(repository: Path, commit: str) -> dict[str, object]:
    return {
        "repositories": (RepositorySpec("r", "temper", repository, commit),),
        "entrypoints": (EntrypointSpec("e", "p", "r:r1/main.py", "main"),),
        "process_profiles": (_profile("p", ("e",), (("r", "r1"), ("r", "r2"))),),
        "declared_nodes": _runtime_inventory(),
    }


def test_namespace_portions_merge_in_root_order(tmp_path: Path) -> None:
    commit = _commit_tree(
        tmp_path / "r",
        {
            "r1/main.py": b"import ns.m\nimport ns.only2\n",
            "r1/ns/m.py": b"WHERE = 'r1'\n",
            "r2/ns/m.py": b"WHERE = 'r2'\n",
            "r2/ns/only2.py": b"ONLY = 2\n",
        },
    )
    reviewed = build_reviewed_source_graph(**_one_repository_two_roots(tmp_path / "r", commit))
    edges = {(e.source, e.target, e.kind) for e in reviewed.graph.edges if e.source == "r.r1.main"}
    assert edges == {("r.r1.main", "r.r1.ns.m", "import"), ("r.r1.main", "r.r2.ns.only2", "import")}
    assert "r.r2.ns.m" not in {n.id for n in reviewed.graph.nodes}


def test_regular_package_restricts_submodule_search(tmp_path: Path) -> None:
    commit = _commit_tree(
        tmp_path / "r",
        {"r1/main.py": b"import p.sub\n", "r1/p/__init__.py": b"", "r2/p/sub.py": b"SUB = 2\n"},
    )
    with pytest.raises(GraphBuildError) as exc_info:
        build_reviewed_source_graph(**_one_repository_two_roots(tmp_path / "r", commit))
    assert exc_info.value.code == "UNRESOLVED_CLOSURE"
    assert exc_info.value.items == ("r:r1/main.py:1:unresolved_import:p.sub",)


def test_symlink_or_gitlink_at_a_search_position_fails_loud(tmp_path: Path) -> None:
    # Python follows a symlink or a checked-out gitlink, so r1's entry would win over r2's package.
    repository = tmp_path / "r"
    base = _commit_tree(
        repository,
        {
            "r1/main.py": b"import sym\n",
            "real/sym/__init__.py": b"WHERE = 'link target'\n",
            "r2/sym/__init__.py": b"WHERE = 'r2'\n",
            "r2/gl/__init__.py": b"WHERE = 'r2'\n",
        },
    )
    (repository / "r1" / "sym").symlink_to("../real/sym")
    _git(repository, "add", "r1/sym")
    _git(repository, "commit", "-q", "-m", "symlink")
    symlink_commit = _git(repository, "rev-parse", "HEAD")
    _git(repository, "update-index", "--add", "--cacheinfo", f"160000,{base},r1/gl")
    (repository / "r1" / "main.py").write_bytes(b"import gl\n")
    _git(repository, "add", "r1/main.py")
    _git(repository, "commit", "-q", "-m", "gitlink")
    gitlink_commit = _git(repository, "rev-parse", "HEAD")

    for commit, expected in (
        (symlink_commit, ("r:r1/main.py:1:unresolved_import:sym", "r:r1/sym:0:unsupported_git_entry:120000:blob")),
        (gitlink_commit, ("r:r1/gl:0:unsupported_git_entry:160000:commit", "r:r1/main.py:1:unresolved_import:gl")),
    ):
        with pytest.raises(GraphBuildError) as exc_info:
            build_reviewed_source_graph(**_one_repository_two_roots(repository, commit))
        assert exc_info.value.code == "UNRESOLVED_CLOSURE"
        assert exc_info.value.items == expected

    # A root that binds before the link is reached never meets it.
    spec = _one_repository_two_roots(repository, symlink_commit)
    spec["process_profiles"] = (_profile("p", ("e",), (("r", "r2"), ("r", "r1"))),)
    reviewed = build_reviewed_source_graph(**spec)
    assert ("r.r1.main", "r.r2.sym", "import") in {(e.source, e.target, e.kind) for e in reviewed.graph.edges}


def test_multi_repository_reads_only_committed_git_objects(tmp_path: Path) -> None:
    host, lib = _two_repositories(tmp_path)
    (tmp_path / "host" / "bin" / "helper.py").write_bytes(b"raise RuntimeError('dirty working tree')\n")
    (tmp_path / "lib" / "sharedlib" / "impl.py").write_bytes(b"import untracked_mod\n")
    (tmp_path / "host" / "bin" / "untracked_mod.py").write_bytes(b"U = 1\n")
    entry = EntrypointSpec("run", "p", "host:bin/run.py", "run:main")
    reviewed = build_reviewed_source_graph(
        repositories=(host, lib),
        entrypoints=(entry,),
        process_profiles=(_profile("p", ("run",), HOST_ROOTS),),
        declared_nodes=_runtime_inventory(),
    )
    nodes = {n.id: n for n in reviewed.graph.nodes}
    assert nodes["host.bin.helper"].content == byte_identity(b"VALUE = 1\n")
    assert nodes["lib.sharedlib.impl"].content == byte_identity(b"def compute() -> int:\n    return 1\n")
    assert "host.bin.untracked_mod" not in nodes
    with pytest.raises(GraphBuildError) as exc_info:
        build_reviewed_source_graph(
            repositories=(host, lib),
            entrypoints=(entry,),
            process_profiles=(_profile("p", ("run",), HOST_ROOTS, extra_required_load_ids=("host:bin/untracked_mod.py",)),),
            declared_nodes=_runtime_inventory(),
        )
    assert exc_info.value.items == ("unknown_required_load:p:host:bin/untracked_mod.py",)
