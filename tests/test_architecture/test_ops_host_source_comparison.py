"""N3 independent synthetic clean/bad families; no service or native qualification."""

from __future__ import annotations

import ast
import builtins
import dataclasses
import inspect
import os
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import p3_source_closure as public
from configs.architecture.bin import ops_host_source_comparison as facade
from p3_source_closure import comparison as api
from p3_source_closure import parsing, provenance
from p3_source_closure import records as types
from tests.test_architecture.ops_host_n3_cases import (
    FAMILIES,
    bad_twin,
    clean_world,
    content,
    received,
    wire,
)


def compare(inputs):
    return api.compare_loaded_source(inputs.reviewed, inputs.observed,
                                     expected=inputs.expected, verified=inputs.verified)


def check_answer(inputs, disposition, reason=None):
    result = compare(inputs)
    # Only fixed result labels participate in pytest assertions.
    assert result.disposition == disposition
    assert result.reasons == tuple(sorted(set(result.reasons)))
    if reason:
        assert reason in result.reasons
    assert result.binding == inputs.expected.binding
    assert result.boundary == inputs.expected.boundary
    assert result.reviewed_graph == inputs.expected.reviewed_graph
    return result


@pytest.mark.parametrize("family", FAMILIES, ids=lambda f: f.case_id)
def test_fixed_family(family):
    clean = clean_world(family.case_id)
    parsed_graph = api.validate_reviewed_graph(wire(clean.reviewed.graph))
    parsed_envelope = api.validate_loaded_envelope(wire(clean.observed.envelope))
    assert parsed_graph == clean.reviewed
    assert parsed_envelope == clean.observed
    check_answer(clean, "MATCH")
    if family.case_id == "N3-13":
        value = wire(clean.observed.envelope)
        value["schema"] = "qa-ops-host-source-closure/1"
        with pytest.raises(api.TargetRefused) as caught:
            api.validate_loaded_envelope(value)
        assert caught.value.code == family.disposition
    else:
        check_answer(bad_twin(family.case_id, clean), family.disposition, family.reason)


@pytest.mark.parametrize("kind", ["graph", "envelope"])
@pytest.mark.parametrize("fault", ["extra", "missing", "version", "bool-int", "float-int", "wrong-collection", "bad-hash", "duplicate-id", "subclass", "serialized-trust"])
def test_closed_grammar(kind, fault):
    clean = clean_world()
    value = wire(clean.reviewed.graph if kind == "graph" else clean.observed.envelope)
    validator = api.validate_reviewed_graph if kind == "graph" else api.validate_loaded_envelope
    if fault == "extra":
        value["extra"] = 1
    elif fault == "missing":
        del value["schema"]
    elif fault == "version":
        value["schema"] += "-unknown"
    elif fault in ("bool-int", "float-int"):
        target = value["nodes"][0]["content"] if kind == "graph" else value["binding"]["build"]
        target["byte_length"] = True if fault == "bool-int" else 1.0
    elif fault == "wrong-collection":
        key = "nodes" if kind == "graph" else "process_observations"
        value[key] = tuple(value[key])
    elif fault == "bad-hash":
        target = value["nodes"][0]["content"] if kind == "graph" else value["binding"]["build"]
        target["sha256"] = "x" * 64
    elif fault == "duplicate-id":
        key = "nodes" if kind == "graph" else "process_observations"
        value[key].append(value[key][0])
    elif fault == "subclass":
        class CandidateDict(dict):
            pass
        value = CandidateDict(value)
    else:
        value["verified"] = True
    with pytest.raises(api.TargetRefused) as caught:
        validator(value)
    assert caught.value.code == ("TARGET_SCHEMA_MISMATCH" if fault == "version" else "TARGET_BINDING_INVALID")


@pytest.mark.parametrize("bad", [b'{"schema":1,"schema":2}', b'{"x":NaN}', b'\xff', b'{} trailing', b'[]', b'null'])
def test_strict_transport_fixed_errors_without_cause(bad):
    with pytest.raises(api.TargetRefused) as caught:
        api.validate_reviewed_graph(bad)
    assert caught.value.code == "TARGET_BINDING_INVALID"
    assert caught.value.__context__ is None
    assert caught.value.args == ("TARGET_BINDING_INVALID",)


@pytest.mark.parametrize("atom,bad", [
    ("text", ""), ("text", "a\x00b"), ("text", "\ud800"),
    ("graph-name", "bad/name"), ("digest", "A" * 64),
    ("integer", -1), ("integer", float("nan")), ("integer", float("inf")),
    ("field-name", 1),
])
def test_new_schema_atoms_have_independent_clean_and_bad_inputs(atom, bad):
    good = wire(clean_world().reviewed.graph)
    assert api.validate_reviewed_graph(good).graph.graph_id == good["graph_id"]
    if atom == "text":
        good["graph_id"] = bad
    elif atom == "graph-name":
        good["repositories"][0]["id"] = bad
    elif atom == "digest":
        good["nodes"][0]["content"]["sha256"] = bad
    elif atom == "integer":
        good["nodes"][0]["content"]["byte_length"] = bad
    else:
        good[bad] = good.pop("graph_id")
    with pytest.raises(api.TargetRefused) as caught:
        api.validate_reviewed_graph(good)
    assert caught.value.code == "TARGET_BINDING_INVALID"


def test_json_duplicate_cannot_hide_a_valid_final_field():
    good = parsing.canonical_bytes(clean_world().reviewed.graph)
    assert api.validate_reviewed_graph(good)
    bad = b'{"schema":"discarded-unknown-version",' + good[1:]
    with pytest.raises(api.TargetRefused) as caught:
        api.validate_reviewed_graph(bad)
    assert caught.value.code == "TARGET_BINDING_INVALID"
    assert caught.value.__context__ is None


def test_n3_refusal_is_not_the_legacy_code_table():
    for code in ("TARGET_BINDING_INVALID", "TARGET_SCHEMA_MISMATCH"):
        error = public.TargetRefused(code)
        assert error.args == (code,)
        assert error.code == code
    with pytest.raises(TypeError):
        public.TargetRefused("TARGET_ISSUER_UNTRUSTED")


def _isolated_status(script, cwd, *, missing_dependency=False):
    # No child stdout/stderr/argv or exception text enters a pytest assertion.
    program = (
        "import runpy, sys\n"
        "try: runpy.run_path(sys.argv[1], run_name='__main__')\n"
        "except ModuleNotFoundError as e:\n"
        " sys.exit(0 if e.name == 'p3_source_closure' else 2)\n"
        "else: sys.exit(3)\n"
    )
    args = [sys.executable, "-I", "-S"]
    args += ["-c", program, str(script)] if missing_dependency else [str(script)]
    status = None
    try:
        status = subprocess.run(args, cwd=cwd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=30, check=False).returncode
    except (OSError, subprocess.SubprocessError):
        pass
    return status


def test_legacy_standalone_and_explicit_n3_dependency_boundary(tmp_path):
    root = Path(__file__).resolve().parents[2]
    legacy_status = _isolated_status(root / "configs/architecture/bin/ops_host_binding.py", tmp_path)
    assert legacy_status == 0
    missing_status = _isolated_status(root / "configs/architecture/bin/ops_host_source_comparison.py",
                                      tmp_path, missing_dependency=True)
    assert missing_status == 0


def test_raw_input_identity_not_normalized_bytes():
    clean = clean_world()
    raw = parsing.canonical_bytes(clean.reviewed.graph) + b"\n"
    parsed = api.validate_reviewed_graph(raw)
    assert parsed.graph == clean.reviewed.graph
    assert parsed.content != clean.reviewed.content
    check_answer(dataclasses.replace(clean, reviewed=parsed), "REFUSED", "REVIEW_ORIGIN")


def test_records_immutable_and_single_definition():
    clean = clean_world()
    for name in public.__all__:
        assert getattr(public, name) is getattr(facade, name)
    for name in ("ReviewedSourceGraph", "LoadedClosureEnvelope", "NativeClosureExpectation", "VerifiedClosureOrigins", "SourceClosureComparison", "N3SourceEpoch", "N3ObservationEpoch", "N3Coverage", "N3Gap"):
        assert getattr(public, name) is getattr(types, name)
    assert public.compare_loaded_source is api.compare_loaded_source
    with pytest.raises(dataclasses.FrozenInstanceError):
        clean.expected.binding.attempt = 3
    with pytest.raises(api.TargetRefused):
        dataclasses.replace(clean.verified, facts=[])
    assert repr(clean.verified) == "VerifiedClosureOrigins(data)"
    assert repr(clean.expected) == "NativeClosureExpectation(data)"


def test_adopted_epoch_references_are_identities_not_counters():
    clean = clean_world()
    expected = clean.expected
    process = clean.observed.envelope.process_observations[0]
    source = public.N3SourceEpoch(expected.reviewed_graph, expected.review_ref,
                                  expected.binding.selection_revision)
    observed = public.N3ObservationEpoch(process.instance, process.collector_ref,
                                         expected.processes[0].frontier)
    assert parsing.decode_record(wire(source), public.N3SourceEpoch) == source
    assert parsing.decode_record(wire(observed), public.N3ObservationEpoch) == observed
    assert public.N3Coverage is types.Coverage
    assert public.N3Gap is types.Coverage
    with pytest.raises(api.TargetRefused):
        dataclasses.replace(source, selection_revision=1)
    with pytest.raises(api.TargetRefused):
        dataclasses.replace(observed, frontier=expected.processes[1].frontier)
    with pytest.raises(dataclasses.FrozenInstanceError):
        observed.collector_ref = None


@pytest.mark.parametrize("kind", ["graph", "envelope"])
@pytest.mark.parametrize("bad_schema", [True, None, [], 1])
def test_untyped_schema_is_format_refusal(kind, bad_schema):
    clean = clean_world()
    value = wire(clean.reviewed.graph if kind == "graph" else clean.observed.envelope)
    value["schema"] = bad_schema
    validator = api.validate_reviewed_graph if kind == "graph" else api.validate_loaded_envelope
    with pytest.raises(api.TargetRefused) as caught:
        validator(value)
    assert caught.value.code == "TARGET_BINDING_INVALID"


def test_parser_never_invokes_candidate_equality():
    class CandidateEquality:
        def __eq__(self, other):
            raise AssertionError("CANDIDATE_EFFECT")

    for field in ("schema", "tag"):
        value = wire(clean_world().reviewed.graph)
        target = value if field == "schema" else value["nodes"][0]["provenance"]
        target[field] = CandidateEquality()
        with pytest.raises(api.TargetRefused) as caught:
            api.validate_reviewed_graph(value)
        assert caught.value.code == "TARGET_BINDING_INVALID"


def test_same_reference_name_cannot_bind_two_contents():
    value = wire(clean_world().reviewed.graph)
    ref = dict(value["nodes"][0]["provenance"]["membership_ref"])
    ref["content"] = wire(content("different-review-bytes"))
    value["completeness_review_ref"] = ref
    with pytest.raises(api.TargetRefused) as caught:
        api.validate_reviewed_graph(value)
    assert caught.value.code == "TARGET_BINDING_INVALID"


def test_unknown_provider_is_not_match():
    clean = clean_world()
    unavailable = api.VerifiedClosureOrigins(None, None, None, None, ())
    check_answer(dataclasses.replace(clean, verified=unavailable), "UNKNOWN", "OBSERVER_ORIGIN")


def test_contradiction_keeps_gaps():
    clean = clean_world()
    bad = bad_twin("N3-05", clean)
    bad = dataclasses.replace(bad, verified=dataclasses.replace(bad.verified, facts=tuple(f for f in bad.verified.facts if f.purpose != "generation")))
    result = check_answer(bad, "REFUSED", "BYTE_SUBSTITUTION")
    assert "GENERATED_PROVENANCE" in result.reasons


@pytest.mark.parametrize("fault,reason", [("attempt", "BINDING"), ("pid", "PROCESS_INSTANCE"), ("start", "PROCESS_INSTANCE"), ("runtime", "RUNTIME_PROVENANCE"), ("unsealed", "COVERAGE_GAP"), ("native-gap", "COVERAGE_GAP"), ("reordered", "SEQUENCE_GAP"), ("observer-restart", "STALE_FRONTIER"), ("forged-origin", "OBSERVER_ORIGIN"), ("missing-start", "COVERAGE_GAP"), ("dead-child-unsealed", "COVERAGE_GAP")])
def test_additional_fixed_faults(fault, reason):
    clean = clean_world()
    envelope = clean.observed.envelope
    processes = list(envelope.process_observations)
    index = -1 if fault == "dead-child-unsealed" else 0
    p = processes[index]
    if fault == "attempt":
        envelope = dataclasses.replace(envelope, binding=dataclasses.replace(envelope.binding, attempt=9))
    elif fault in ("pid", "start"):
        field = {"pid": {"pid": 999}, "start": {"start_identity": "reused-pid-new-birth"}}[fault]
        p = dataclasses.replace(p, instance=dataclasses.replace(p.instance, **field))
    elif fault == "runtime":
        p = dataclasses.replace(p, runtime_nodes=("interpreter-worker",))
    elif fault in ("unsealed", "dead-child-unsealed"):
        p = dataclasses.replace(p, checkpoint=dataclasses.replace(p.checkpoint, sealed=False))
    elif fault == "native-gap":
        p = dataclasses.replace(p, checkpoint=dataclasses.replace(p.checkpoint, gaps=("native",)))
    elif fault == "reordered":
        p = dataclasses.replace(p, events=(p.events[1], p.events[0], *p.events[2:]))
    elif fault == "observer-restart":
        p = dataclasses.replace(p, checkpoint=dataclasses.replace(p.checkpoint, epoch="observer-restarted"))
    elif fault == "missing-start":
        p = dataclasses.replace(p, events=p.events[1:])
    else:
        facts = list(clean.verified.facts)
        n = next(i for i, f in enumerate(facts) if f.ref == p.collector_ref)
        facts[n] = dataclasses.replace(facts[n], claim=content("forged-observer"))
        bad = dataclasses.replace(clean, verified=dataclasses.replace(clean.verified, facts=tuple(facts)))
        check_answer(bad, "REFUSED", reason)
        return
    processes[index] = p
    bad = received(clean, dataclasses.replace(envelope, process_observations=tuple(processes)), observed_facts=True)
    disposition = "REFUSED" if fault in ("attempt", "pid", "start", "runtime") else "UNKNOWN"
    check_answer(bad, disposition, reason)


def test_authenticated_conflicting_duplicate_refuses():
    clean = clean_world()
    envelope = clean.observed.envelope
    p = envelope.process_observations[0]
    duplicate = dataclasses.replace(p.events[1], loaded=content("conflict"), origin_ref=dataclasses.replace(p.events[1].origin_ref, record_id="conflicting-event"))
    p = dataclasses.replace(p, events=(*p.events, duplicate))
    bad = received(clean, dataclasses.replace(envelope, process_observations=(p, *envelope.process_observations[1:])), observed_facts=True)
    check_answer(bad, "REFUSED", "SEQUENCE_GAP")


def test_required_is_not_permitted():
    clean = clean_world("N3-15")
    assert "optional" in clean.reviewed.graph.process_profiles[0].allowed_node_ids
    assert all(e.node_id != "optional" for p in clean.observed.envelope.process_observations for e in p.events)
    check_answer(clean, "MATCH")
    check_answer(bad_twin("N3-15", clean), "REFUSED", "REQUIRED_LOAD")


def test_new_graph_accepts_cycle_without_legacy_relaxation():
    clean = clean_world()
    graph = api.validate_reviewed_graph(wire(clean.reviewed.graph)).graph
    assert (graph.edges[0].source, graph.edges[0].target) == ("main", "dep")
    assert (graph.edges[1].source, graph.edges[1].target) == ("dep", "main")
    # R2's independent unchanged carry suite owns its complete grammar/oracles.
    from configs.architecture.bin import ops_host_binding as legacy
    assert legacy.TRUST == "UNTRUSTED"
    assert len(legacy.REQUIRED_NATIVE_CHECKS) == 5
    assert legacy.TargetRefused is not api.TargetRefused
    assert len(legacy.CODES) == 11


def test_phase_a_does_not_require_future_window():
    clean = clean_world("N3-11")
    assert clean.expected.binding.window_id is None
    assert clean.expected.boundary.receipt is None
    assert len(clean.expected.processes) == 1
    check_answer(clean, "MATCH")
    for phase in ("B_PRE_REQUEST", "C_BEFORE_COUNT"):
        value = wire(clean.observed.envelope)
        value["boundary"]["phase"] = phase
        with pytest.raises(api.TargetRefused):
            api.validate_loaded_envelope(value)


def test_dangling_edges_and_unsupported_owner_refuse():
    clean = clean_world()
    for fault in ("edge", "owner", "profile"):
        value = wire(clean.reviewed.graph)
        if fault == "edge":
            value["edges"][0]["to"] = "absent"
        elif fault == "owner":
            value["repositories"][0]["owner"] = "candidate"
        else:
            value["process_profiles"][0]["child_profiles"] = ["absent"]
        with pytest.raises(api.TargetRefused):
            api.validate_reviewed_graph(value)


def test_pure_import_and_comparison_no_services_or_effects(monkeypatch):
    clean = clean_world()
    prefix = "p3_source_closure."
    names = ("validation", "records", "parsing", "reviewed_graph", "loaded_envelope", "provenance", "comparison", "__init__")
    # Read/compile by the test before installing effect sentinels. Normal imports
    # need Python's own filesystem loader; the module bodies must not do I/O.
    compiled = []
    root = Path(api.__file__).parent
    for name in names:
        source = (root / (name + ".py")).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                assert not any(v.startswith(("temper_ai", "p3_authority", "pathlib", "socket", "subprocess", "os")) for v in imports)
        compiled.append((name, compile(source, "<pure-module>", "exec")))

    def forbidden(*args, **kwargs):
        raise AssertionError("PURE_EFFECT")

    for module, name in ((builtins, "open"), (os, "open"), (os, "listdir"), (os, "stat"), (subprocess, "run"), (subprocess, "Popen"), (socket, "socket"), (Path, "read_bytes"), (Path, "resolve")):
        monkeypatch.setattr(module, name, forbidden)
    # Compile/executed module bodies use canonical already-imported records; this
    # exercises import-time code without confusing importlib's own reads with I/O.
    for name, code in compiled:
        namespace = {"__name__": prefix + name, "__package__": prefix.rstrip(".")}
        exec(code, namespace)
    check_answer(clean, "MATCH")
    api.validate_reviewed_graph(wire(clean.reviewed.graph))
    api.validate_loaded_envelope(wire(clean.observed.envelope))


def install_mutation(monkeypatch, owner, function, before, after):
    original = getattr(owner, function)
    source = textwrap.dedent(inspect.getsource(original))
    assert source.count(before) == 1
    namespace = dict(original.__globals__)
    exec(compile(source.replace(before, after), "<synthetic-single-guard-mutation>", "exec"), namespace)
    monkeypatch.setattr(owner, function, namespace[function])


@pytest.mark.parametrize("case_id,reason,before,after", [
    ("N3-02", "UNREVIEWED_LOAD", 'findings.refuse("UNREVIEWED_LOAD")', "pass"),
    ("N3-05", "BYTE_SUBSTITUTION", "if event.loaded != executed:", "if False:"),
    ("N3-06", "RUNTIME_PROVENANCE", "if process.runtime_nodes != profile.runtime_nodes or process.instance.runtime_id not in profile.runtime_nodes:", "if False:"),
    ("N3-07", "PROCESS_INSTANCE", "if process.instance != required.instance or process.profile_id != required.profile_id:", "if False:"),
    ("N3-08", "SEQUENCE_GAP", "if not events or cp.first_sequence != 0 or sequences != tuple(range(cp.first_sequence, cp.first_sequence + len(events))) or (events and cp.last_sequence != events[-1].sequence):", "if False:"),
    ("N3-09", "STALE_FRONTIER", "if actual_frontier != required.frontier or cp.boundary != envelope.boundary:", "if False:"),
    ("N3-15", "REQUIRED_LOAD", "if not mandatory <= loads:", "if False:"),
])
def test_source_guard_mutation_killed(case_id, reason, before, after, monkeypatch):
    clean = clean_world(case_id)
    check_answer(clean, "MATCH")
    bad = bad_twin(case_id, clean)
    family = next(f for f in FAMILIES if f.case_id == case_id)
    check_answer(bad, family.disposition, reason)
    install_mutation(monkeypatch, api, "_check_process", before, after)
    with pytest.raises(AssertionError):
        check_answer(bad, family.disposition, reason)
    check_answer(clean, "MATCH")


@pytest.mark.parametrize("case_id,before,after", [
    ("N3-03", "elif actual != claim_identity(claim):", "elif False:"),
    ("N3-10", "self.unknown(reason)", "pass"),
])
def test_origin_mutation_killed(case_id, before, after, monkeypatch):
    clean = clean_world(case_id)
    family = next(f for f in FAMILIES if f.case_id == case_id)
    bad = bad_twin(case_id, clean)
    check_answer(clean, "MATCH")
    check_answer(bad, family.disposition, family.reason)
    install_mutation(monkeypatch, provenance.Findings, "origin", before, after)
    with pytest.raises(AssertionError):
        check_answer(bad, family.disposition, family.reason)
    check_answer(clean, "MATCH")


def test_verified_byte_binding_mutant_is_killed(monkeypatch):
    clean = clean_world()
    bad = dataclasses.replace(clean, verified=dataclasses.replace(clean.verified, observed_bytes=content("other-observed-bytes")))
    check_answer(clean, "MATCH")
    check_answer(bad, "REFUSED", "OBSERVER_ORIGIN")
    install_mutation(monkeypatch, api, "compare_loaded_source", "elif supplied != actual:", "elif False:")
    with pytest.raises(AssertionError):
        check_answer(bad, "REFUSED", "OBSERVER_ORIGIN")
    check_answer(clean, "MATCH")


def test_coverage_guard_mutant_is_killed(monkeypatch):
    clean = clean_world()
    envelope = clean.observed.envelope
    p = envelope.process_observations[0]
    p = dataclasses.replace(p, checkpoint=dataclasses.replace(p.checkpoint, gaps=("native",)))
    bad = received(clean, dataclasses.replace(envelope, process_observations=(p, *envelope.process_observations[1:])), observed_facts=True)
    check_answer(clean, "MATCH")
    check_answer(bad, "UNKNOWN", "COVERAGE_GAP")
    install_mutation(monkeypatch, api, "_check_process", "if not cp.sealed or cp.loss_count or cp.gaps or not set(required.coverage) <= set(cp.coverage):", "if False:")
    with pytest.raises(AssertionError):
        check_answer(bad, "UNKNOWN", "COVERAGE_GAP")
    check_answer(clean, "MATCH")
