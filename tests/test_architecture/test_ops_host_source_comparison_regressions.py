"""Permanent Architecture #441 regression controls: invented data, no authority."""

from dataclasses import replace

import pytest

from p3_source_closure import comparison as api
from tests.test_architecture.ops_host_n3_cases import (
    bad_twin,
    child_stream,
    clean_world,
    content,
    omit_collector,
    received,
    ref,
    rename_child_last,
    select_synthetic_graph,
    separate_exec_instance,
)
from tests.test_architecture.test_ops_host_source_comparison import install_mutation


def assert_contract(inputs, disposition, reasons):
    result = api.compare_loaded_source(inputs.reviewed, inputs.observed,
                                       expected=inputs.expected, verified=inputs.verified)
    assert result.binding == inputs.expected.binding
    assert result.boundary == inputs.expected.boundary
    assert result.reviewed_graph == inputs.expected.reviewed_graph
    frontiers = (tuple(sorted((p.frontier for p in inputs.expected.processes),
                              key=lambda p: p.instance_id)) if disposition == "MATCH" else ())
    assert result.frontiers == frontiers
    assert result.reasons == reasons
    assert result.disposition == disposition


@pytest.mark.parametrize("case,disposition,reasons", [
    ("clean", "MATCH", ()),
    ("complete-missing-required", "REFUSED", ("REQUIRED_LOAD",)),
    ("local-collector-missing", "UNKNOWN", ("OBSERVER_ORIGIN", "REQUIRED_LOAD")),
    ("unrelated-child-first", "REFUSED", ("OBSERVER_ORIGIN", "REQUIRED_LOAD")),
    ("unrelated-child-last", "REFUSED", ("OBSERVER_ORIGIN", "REQUIRED_LOAD")),
    ("both-collectors-missing", "UNKNOWN", ("OBSERVER_ORIGIN", "REQUIRED_LOAD")),
])
def test_process_local_completeness(case, disposition, reasons):
    inputs = clean_world("N3-15")
    if case != "clean":
        inputs = bad_twin("N3-15", inputs)
    if case == "local-collector-missing":
        inputs = omit_collector(inputs, "creator")
    elif case == "unrelated-child-first":
        inputs = omit_collector(inputs, "child")
    elif case == "unrelated-child-last":
        inputs = omit_collector(rename_child_last(inputs), "z-child")
    elif case == "both-collectors-missing":
        inputs = omit_collector(omit_collector(inputs, "child"), "creator")
    assert_contract(inputs, disposition, reasons)


@pytest.mark.parametrize("case,disposition,reasons", [
    ("clean", "MATCH", ()),
    ("load-before-sole-end", "MATCH", ()),
    ("end-load-end", "REFUSED", ("PROCESS_INSTANCE",)),
    ("end-use-end", "REFUSED", ("PROCESS_INSTANCE",)),
    ("end-end", "REFUSED", ("PROCESS_INSTANCE",)),
    ("end-load", "REFUSED", ("COVERAGE_GAP", "PROCESS_INSTANCE")),
    ("missing-end", "UNKNOWN", ("COVERAGE_GAP",)),
    ("unsealed", "UNKNOWN", ("COVERAGE_GAP",)),
])
def test_terminated_history(case, disposition, reasons):
    assert_contract(child_stream(clean_world(), case), disposition, reasons)


def test_distinct_exec_instance_keeps_terminated_predecessor():
    inputs = separate_exec_instance(clean_world())
    prior = next(p for p in inputs.observed.envelope.process_observations if p.instance.instance_id == "child")
    current = next(p for p in inputs.observed.envelope.process_observations if p.instance.instance_id == "child-exec-2")
    assert prior.instance.pid == current.instance.pid
    assert prior.instance.start_identity == current.instance.start_identity
    assert prior.instance.exec_epoch != current.instance.exec_epoch
    assert prior.checkpoint.epoch != current.checkpoint.epoch
    assert prior.state == "terminated" and current.state == "running"
    assert len(inputs.expected.processes) == 5
    assert_contract(inputs, "MATCH", ())


@pytest.mark.parametrize("case,disposition,reasons", [
    ("clean", "MATCH", ()),
    ("absent-proof", "UNKNOWN", ("REVIEW_ORIGIN",)),
    ("absent-reference", "UNKNOWN", ("COVERAGE_GAP", "REVIEW_ORIGIN")),
    ("different-reference", "REFUSED", ("REVIEW_ORIGIN",)),
    ("contrary-claim", "REFUSED", ("REVIEW_ORIGIN",)),
    ("absent-review-wrong-transport", "REFUSED", ("COVERAGE_GAP", "REVIEW_ORIGIN")),
])
def test_missing_review_is_not_contrary_review(case, disposition, reasons):
    inputs = clean_world()
    if case == "absent-proof":
        inputs = bad_twin("N3-01", inputs)
    elif case in ("absent-reference", "absent-review-wrong-transport"):
        inputs = select_synthetic_graph(inputs, None)
        if case == "absent-review-wrong-transport":
            envelope = inputs.observed.envelope
            inputs = received(inputs, replace(envelope, reviewed_graph=replace(
                envelope.reviewed_graph, content=content("wrong-transport-graph"))))
    elif case == "different-reference":
        inputs = select_synthetic_graph(inputs, ref("different-review"))
    elif case == "contrary-claim":
        inputs = replace(inputs, verified=replace(inputs.verified, facts=tuple(
            replace(f, claim=content("contrary-review-claim")) if f.purpose == "review" else f
            for f in inputs.verified.facts)))
    assert_contract(inputs, disposition, reasons)


@pytest.mark.parametrize("mutation,function,before,after", [
    ("shared-process-gaps", "compare_loaded_source",
     "_check_process(process, required[key], graph, envelope, local)",
     "_check_process(process, required[key], graph, envelope, findings)"),
    ("terminal-order", "_check_process",
     "if end_positions and end_positions != (len(events) - 1,):", "if False:"),
    ("absent-is-contrary", "compare_loaded_source",
     "elif graph.completeness_review_ref != expected.review_ref:",
     "if graph.completeness_review_ref != expected.review_ref:"),
    ("ignore-contrary-review", "compare_loaded_source",
     "elif graph.completeness_review_ref != expected.review_ref:", "elif False:"),
])
def test_review_guard_mutation_killed(mutation, function, before, after, monkeypatch):
    clean = clean_world()
    assert_contract(clean, "MATCH", ())
    if mutation == "shared-process-gaps":
        bad = omit_collector(bad_twin("N3-15", clean), "child")
        disposition, reasons = "REFUSED", ("OBSERVER_ORIGIN", "REQUIRED_LOAD")
    elif mutation == "terminal-order":
        bad = child_stream(clean, "end-load-end")
        disposition, reasons = "REFUSED", ("PROCESS_INSTANCE",)
    elif mutation == "absent-is-contrary":
        bad = select_synthetic_graph(clean, None)
        disposition, reasons = "UNKNOWN", ("COVERAGE_GAP", "REVIEW_ORIGIN")
    else:
        bad = select_synthetic_graph(clean, ref("different-review"))
        disposition, reasons = "REFUSED", ("REVIEW_ORIGIN",)
    assert_contract(bad, disposition, reasons)
    install_mutation(monkeypatch, api, function, before, after)
    with pytest.raises(AssertionError):
        assert_contract(bad, disposition, reasons)
    assert_contract(clean, "MATCH", ())
