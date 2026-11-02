"""New synthetic data only; these objects are not service-issued references."""

from dataclasses import dataclass

import p3_host_contracts as h


@dataclass(frozen=True, slots=True)
class ExampleReference:
    label: str


def examples():
    refs = {
        name: ExampleReference(name)
        for name in (
            "selection",
            "witness",
            "admission",
            "process",
            "birth",
            "container",
            "root",
            "subject",
            "target",
            "grant",
            "interval",
            "fields",
            "events",
            "disarm",
            "watch",
            "reviewed",
            "observed",
            "comparison",
            "source_epoch",
            "observation_epoch",
            "coverage",
            "gap",
        )
    }
    raw = h.RawRef("synthetic:Root:E\u0301", "./Segment/../Bytes", 0, "AB" * 32)
    project = h.ProjectSelection("project-example", raw, raw)
    calibration = h.CalibrationSelection(
        raw, "entry-example", "round-example", "run-example", "copy-example", raw
    )
    caller = h.CallerSelection(
        "entry-example",
        refs["reviewed"],
        "caller-example",
        "writer-example",
        frozenset({"row-example"}),
        "/2",
        "route-example",
    )
    job = h.SelectedHostJob(
        refs["selection"],
        "job-example",
        "attempt-example",
        "publication-example",
        raw,
        project,
        "launch-example",
        caller,
    )
    process = h.ProcessInstance(
        refs["witness"],
        "host-example",
        "boot-example",
        "pid-namespace-example",
        1,
        refs["birth"],
        refs["witness"],
        "launch-example",
        None,
        "role-example",
        refs["observed"],
        None,
        "mount-namespace-example",
        "user-namespace-example",
    )
    root_scope = h.RootScope(
        "publication",
        refs["subject"],
        "synthetic:locator",
        None,
        None,
        frozenset({"right-example"}),
    )
    root = h.RootBinding(
        "publication",
        refs["root"],
        refs["process"],
        refs["witness"],
        "./actor-spelling",
        "./host-spelling",
        frozenset({"right-example"}),
        (refs["grant"],),
        refs["interval"],
        refs["witness"],
    )
    effect = h.HostEffect(
        "create",
        refs["selection"],
        refs["target"],
        "operation-example",
        refs["subject"],
        "purpose-example",
        (root_scope,),
        "boundary-example",
    )
    scope = h.ObservationScope(
        refs["selection"],
        "A",
        (refs["subject"],),
        (root_scope,),
        "purpose-example",
        refs["fields"],
        refs["reviewed"],
        (effect,),
        refs["interval"],
    )
    observation = h.HostObservation(
        refs["selection"],
        (process,),
        (root,),
        refs["observed"],
        refs["source_epoch"],
        refs["observation_epoch"],
        refs["events"],
        refs["interval"],
        refs["coverage"],
        (refs["gap"],),
        refs["witness"],
    )
    coverage = h.HostCoverage(
        observation, refs["comparison"], refs["witness"], effect, refs["watch"]
    )
    lease = h.EffectLease(
        refs["admission"],
        effect,
        refs["process"],
        refs["source_epoch"],
        refs["observation_epoch"],
        refs["interval"],
        refs["witness"],
        refs["witness"],
    )
    lifecycle = h.LifecycleKey(refs["selection"], "launch-example", "operation-example")
    row = h.RowKey(
        refs["selection"],
        "window-example",
        raw,
        "writer-example",
        "row-example",
        "operation-example",
        "request-example",
        1,
        raw,
    )
    occurrence = h.OccurrenceHandle(
        lifecycle,
        refs["witness"],
        refs["process"],
        None,
        (),
        refs["witness"],
        (refs["target"],),
        refs["source_epoch"],
        refs["observation_epoch"],
        effect,
        "admitted",
    )
    publication = h.RawPublication(
        occurrence,
        refs["process"],
        refs["process"],
        None,
        raw,
        (raw,),
        None,
        None,
        None,
        (refs["witness"],),
        refs["interval"],
        "success",
        "not-required",
    )
    provenance = h.ReceiptProvenance(
        refs["witness"],
        refs["witness"],
        refs["admission"],
        lifecycle,
        refs["process"],
        refs["process"],
        publication,
        "complete",
        None,
        refs["disarm"],
    )
    join = h.HostClosureJoin(
        refs["selection"],
        raw,
        refs["reviewed"],
        refs["reviewed"],
        refs["observed"],
        refs["observed"],
        refs["comparison"],
        refs["witness"],
    )
    return {
        type(value).__name__: value
        for value in (
            raw,
            project,
            calibration,
            caller,
            job,
            process,
            root_scope,
            root,
            effect,
            scope,
            observation,
            coverage,
            lease,
            lifecycle,
            row,
            occurrence,
            publication,
            provenance,
            join,
        )
    }
