"""Known-answer and fault-proof tests for p3_source_closure.graph_builder."""

from __future__ import annotations

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
