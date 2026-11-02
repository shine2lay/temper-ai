"""Selected job data; constructing it cannot establish independent selection."""

from dataclasses import dataclass
from typing import Generic, Literal

from ._parameters import ReviewedT, SelectionT
from ._shape import choice, record, references, text_fields, words
from .references import RawRef


@dataclass(frozen=True, slots=True)
class ProjectSelection:
    project_id: str
    kit_ref: RawRef
    expected_binding_ref: RawRef

    def __post_init__(self) -> None:
        text_fields(project_id=self.project_id)
        record("kit_ref", self.kit_ref, RawRef)
        record("expected_binding_ref", self.expected_binding_ref, RawRef)


@dataclass(frozen=True, slots=True)
class CalibrationSelection:
    manifest_ref: RawRef
    entry_id: str
    round_id: str
    calibration_run: str
    copy_id: str
    expected_binding_ref: RawRef

    def __post_init__(self) -> None:
        text_fields(
            entry_id=self.entry_id,
            round_id=self.round_id,
            calibration_run=self.calibration_run,
            copy_id=self.copy_id,
        )
        record("manifest_ref", self.manifest_ref, RawRef)
        record("expected_binding_ref", self.expected_binding_ref, RawRef)


@dataclass(frozen=True, slots=True)
class CallerSelection(Generic[ReviewedT]):
    entrypoint: str
    source_review_ref: ReviewedT
    caller_role: str
    writer: str
    allowed_rows: frozenset[str]
    inspect_variant: Literal["/1", "/2"]
    runtime_route: str

    def __post_init__(self) -> None:
        text_fields(
            entrypoint=self.entrypoint,
            caller_role=self.caller_role,
            writer=self.writer,
            runtime_route=self.runtime_route,
        )
        references(source_review_ref=self.source_review_ref)
        words("allowed_rows", self.allowed_rows)
        choice("inspect_variant", self.inspect_variant, ("/1", "/2"))


@dataclass(frozen=True, slots=True)
class SelectedHostJob(Generic[SelectionT, ReviewedT]):
    selection: SelectionT
    job_id: str
    attempt_id: str
    publication_id: str
    build_ref: RawRef
    route: ProjectSelection | CalibrationSelection
    creator_launch_id: str
    caller: CallerSelection[ReviewedT]

    def __post_init__(self) -> None:
        references(selection=self.selection)
        text_fields(
            job_id=self.job_id,
            attempt_id=self.attempt_id,
            publication_id=self.publication_id,
            creator_launch_id=self.creator_launch_id,
        )
        record("build_ref", self.build_ref, RawRef)
        record("route", self.route, (ProjectSelection, CalibrationSelection))
        record("caller", self.caller, CallerSelection)
