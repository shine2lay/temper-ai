"""Source-only domain checks: no pytest conftest, native suppliers or services."""

import dataclasses
import importlib
import types
import unittest
from typing import Literal, Union, get_args, get_origin, get_type_hints

import p3_host_contracts as h

if __package__:
    from .examples import ExampleReference, examples
else:
    from examples import ExampleReference, examples

# Independent field contract, rather than expectations derived from the classes.
FIELDS = {
    "RawRef": "root_locator relative_path byte_length sha256",
    "ProjectSelection": "project_id kit_ref expected_binding_ref",
    "CalibrationSelection": "manifest_ref entry_id round_id calibration_run copy_id expected_binding_ref",
    "CallerSelection": "entrypoint source_review_ref caller_role writer allowed_rows inspect_variant runtime_route",
    "SelectedHostJob": "selection job_id attempt_id publication_id build_ref route creator_launch_id caller",
    "ProcessInstance": "native_identity host_instance_id boot_id pid_namespace_id pid start_identity exec_generation launch_id parent_instance role runtime_ref container_instance mount_namespace_id user_namespace_id",
    "RootScope": "role actor selected_locator expected_existing_object new_leaf required_rights",
    "RootBinding": "role object_identity actor_instance namespace_and_mount_identity actor_visible_path host_visible_path rights grant_refs validity mapping_witness",
    "ObservationScope": "selection phase subjects root_scopes purpose permitted_fields reviewed protected_effects interval",
    "HostObservation": "selection process_instances roots observed source_epoch observation_epoch event_range observed_interval coverage gaps native_witness",
    "HostCoverage": "observation comparison native_binding through_boundary live_watch",
    "HostEffect": "kind selection target operation actor purpose roots boundary",
    "EffectLease": "native_admission effect actor_instance source_epoch observation_epoch validity revocation_revision boundary_token",
    "LifecycleKey": "selection launch_id operation_id",
    "RowKey": "selection window_id binding_ref writer row operation request_id sequence request_raw_ref",
    "OccurrenceHandle": "key witness admitting_process controller executing_processes route_witness targets source_epoch observation_epoch admission_boundary state",
    "RawPublication": "occurrence producer_instance publisher_instance request_raw_ref receipt_raw_ref evidence_refs window_ref numbered_log_ref current_row_ref publication_steps observed_interval outcome cleanup_state",
    "ReceiptProvenance": "occurrence_witness publication_witness issuer_scope_ref operation_key producer_instance publisher_instance raw_publication state predecessor disarm_relation",
    "HostClosureJoin": "selection candidate_ref host_review worker_review_ref host_observed worker_observed_ref comparison native_witness",
}

OPTIONALS = {
    "ProcessInstance": {"parent_instance", "container_instance"},
    "RootScope": {"expected_existing_object", "new_leaf"},
    "OccurrenceHandle": {"controller"},
    "RawPublication": {
        "request_raw_ref",
        "window_ref",
        "numbered_log_ref",
        "current_row_ref",
    },
    "ReceiptProvenance": {"predecessor"},
}

CLOSED = {
    ("CallerSelection", "inspect_variant"): ("/1", "/2"),
    ("RootScope", "role"): ("publication", "host-parent", "host-evidence"),
    ("RootBinding", "role"): ("publication", "host-parent", "host-evidence"),
    ("ObservationScope", "phase"): ("A", "B", "C"),
    ("HostEffect", "kind"): (
        "create",
        "copy",
        "network",
        "container",
        "proof",
        "publish-window",
        "register",
        "arm",
        "stop",
        "cleanup",
        "publish-request",
        "admit-row",
        "execute-row",
        "start",
        "signal",
        "probe",
        "case",
        "publish-receipt",
        "receive",
        "count",
    ),
    ("OccurrenceHandle", "state"): (
        "admitted",
        "started",
        "completed",
        "refused",
        "failed",
        "uncertain",
    ),
    ("RawPublication", "outcome"): (
        "success",
        "app-failure",
        "host-failure",
        "refused",
        "uncertain",
    ),
    ("RawPublication", "cleanup_state"): (
        "not-required",
        "complete",
        "incomplete",
        "uncertain",
    ),
    ("ReceiptProvenance", "state"): ("complete", "incomplete", "uncertain"),
}

PARAMETERS = {
    "RawRef": "",
    "ProjectSelection": "",
    "CalibrationSelection": "",
    "CallerSelection": "ReviewedT",
    "SelectedHostJob": "SelectionT ReviewedT",
    "ProcessInstance": "WitnessT BirthT ProcessT ObservedT ContainerT",
    "RootScope": "SubjectT RootObjectT",
    "RootBinding": "RootObjectT ProcessT WitnessT GrantT IntervalT",
    "ObservationScope": "SelectionT SubjectT RootObjectT FieldsT ReviewedT TargetT IntervalT",
    "HostObservation": "SelectionT WitnessT BirthT ProcessT ObservedT ContainerT RootObjectT GrantT IntervalT SourceEpochT ObservationEpochT EventRangeT CoverageT GapT",
    "HostCoverage": "SelectionT WitnessT BirthT ProcessT ObservedT ContainerT RootObjectT GrantT IntervalT SourceEpochT ObservationEpochT EventRangeT CoverageT GapT ComparisonT TargetT SubjectT WatchT",
    "HostEffect": "SelectionT TargetT SubjectT RootObjectT",
    "EffectLease": "AdmissionT SelectionT TargetT SubjectT RootObjectT ProcessT SourceEpochT ObservationEpochT IntervalT WitnessT",
    "LifecycleKey": "SelectionT",
    "RowKey": "SelectionT",
    "OccurrenceHandle": "SelectionT WitnessT ProcessT TargetT SourceEpochT ObservationEpochT SubjectT RootObjectT",
    "RawPublication": "SelectionT WitnessT ProcessT TargetT SourceEpochT ObservationEpochT SubjectT RootObjectT IntervalT",
    "ReceiptProvenance": "WitnessT AdmissionT SelectionT ProcessT TargetT SourceEpochT ObservationEpochT SubjectT RootObjectT IntervalT DisarmT",
    "HostClosureJoin": "SelectionT ReviewedT ObservedT ComparisonT WitnessT",
}


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.examples = examples()

    def test_exact_exports_fields_and_single_definition(self):
        self.assertEqual(set(h.__all__), set(FIELDS) | {"OperationKey"})
        self.assertEqual(len(h.__all__), 20)
        self.assertEqual(set(self.examples), set(FIELDS))
        for name, field_names in FIELDS.items():
            cls = getattr(h, name)
            with self.subTest(record=name):
                self.assertIs(
                    cls, getattr(importlib.import_module(cls.__module__), name)
                )
                self.assertEqual(
                    [f.name for f in dataclasses.fields(cls)], field_names.split()
                )
                self.assertTrue(cls.__dataclass_params__.frozen)
                self.assertFalse(hasattr(self.examples[name], "__dict__"))
                for field in dataclasses.fields(cls):
                    self.assertIs(field.default, dataclasses.MISSING)
                    self.assertIs(field.default_factory, dataclasses.MISSING)
        self.assertEqual(
            tuple(get_origin(arg) for arg in get_args(h.OperationKey)),
            (h.LifecycleKey, h.RowKey),
        )
        self.assertNotIn("sequence", FIELDS["LifecycleKey"].split())

    def test_fields_are_frozen_and_every_argument_is_required(self):
        for name, instance in self.examples.items():
            arguments = {
                f.name: getattr(instance, f.name) for f in dataclasses.fields(instance)
            }
            for field in arguments:
                with self.subTest(record=name, field=field):
                    with self.assertRaises(dataclasses.FrozenInstanceError):
                        setattr(instance, field, arguments[field])
                    with self.assertRaises(dataclasses.FrozenInstanceError):
                        delattr(instance, field)
                    with self.assertRaises(TypeError):
                        type(instance)(
                            **{k: v for k, v in arguments.items() if k != field}
                        )

    def test_explicit_absence_only_where_optional(self):
        for name, instance in self.examples.items():
            hints = get_type_hints(type(instance))
            for field in dataclasses.fields(instance):
                optional = field.name in OPTIONALS.get(name, set())
                with self.subTest(record=name, field=field.name):
                    self.assertEqual(
                        type(None) in get_args(hints[field.name]), optional
                    )
                    if optional:
                        self.assertIsNone(
                            getattr(
                                dataclasses.replace(instance, **{field.name: None}),
                                field.name,
                            )
                        )
                    else:
                        with self.assertRaises(TypeError):
                            dataclasses.replace(instance, **{field.name: None})
        process = self.examples["ProcessInstance"]
        ref = ExampleReference("explicit-example")
        self.assertIs(
            dataclasses.replace(process, parent_instance=ref).parent_instance, ref
        )
        self.assertIs(
            dataclasses.replace(process, container_instance=ref).container_instance, ref
        )
        root = self.examples["RootScope"]
        self.assertEqual(dataclasses.replace(root, new_leaf="").new_leaf, "")
        self.assertIs(
            dataclasses.replace(
                root, expected_existing_object=ref
            ).expected_existing_object,
            ref,
        )
        previous = self.examples["ReceiptProvenance"]
        self.assertIs(
            dataclasses.replace(previous, predecessor=previous).predecessor, previous
        )

    def test_integer_domains_do_not_accept_bool_or_coerce_or_add_ceiling(self):
        for name, field, minimum in (
            ("RawRef", "byte_length", 0),
            ("ProcessInstance", "pid", 1),
            ("RowKey", "sequence", 1),
        ):
            instance = self.examples[name]
            for bad in (True, False, 1.0, "1", b"1"):
                with self.subTest(record=name, value=bad), self.assertRaises(TypeError):
                    dataclasses.replace(instance, **{field: bad})
            with self.assertRaises(ValueError):
                dataclasses.replace(instance, **{field: minimum - 1})
            for value in (minimum, 2**4096):
                self.assertEqual(
                    getattr(dataclasses.replace(instance, **{field: value}), field),
                    value,
                )

    def test_all_literal_domains_remain_closed(self):
        for (name, field), alternatives in CLOSED.items():
            instance = self.examples[name]
            if name == "OccurrenceHandle":
                instance = dataclasses.replace(
                    instance,
                    executing_processes=(ExampleReference("executor-example"),),
                )
            hint = get_type_hints(type(instance))[field]
            self.assertIs(get_origin(hint), Literal)
            self.assertEqual(get_args(hint), alternatives)
            for value in alternatives:
                self.assertEqual(
                    getattr(dataclasses.replace(instance, **{field: value}), field),
                    value,
                )
            for invalid in ("UNKNOWN", "", alternatives[0] + " "):
                with (
                    self.subTest(record=name, field=field, value=invalid),
                    self.assertRaises(ValueError),
                ):
                    dataclasses.replace(instance, **{field: invalid})
            with self.assertRaises(TypeError):
                dataclasses.replace(instance, **{field: alternatives[0].encode()})

    def test_owned_containers_are_immutable_not_converted_and_check_members(self):
        for name, instance in self.examples.items():
            for field, hint in get_type_hints(type(instance)).items():
                origin = get_origin(hint)
                if origin not in (tuple, frozenset):
                    continue
                value = getattr(instance, field)
                with self.subTest(record=name, field=field):
                    self.assertIs(
                        getattr(dataclasses.replace(instance, **{field: value}), field),
                        value,
                    )
                    mutable = list(value) if origin is tuple else set(value)
                    with self.assertRaises(TypeError):
                        dataclasses.replace(instance, **{field: mutable})
                    with self.assertRaises(TypeError):
                        dataclasses.replace(
                            instance,
                            **{
                                field: (None,) if origin is tuple else frozenset({None})
                            },
                        )
                    element = get_args(hint)[0]
                    if dataclasses.is_dataclass(get_origin(element) or element):
                        with self.assertRaises(TypeError):
                            dataclasses.replace(instance, **{field: (object(),)})

    def test_text_is_exact_not_decoded_stripped_normalized_or_domain_authority(self):
        selected_spelling = "  ./MiXeD/../E\u0301  "
        for name, instance in self.examples.items():
            for field, hint in get_type_hints(type(instance)).items():
                if hint is str:
                    with self.subTest(record=name, field=field):
                        value = dataclasses.replace(
                            instance, **{field: selected_spelling}
                        )
                        self.assertIs(getattr(value, field), selected_spelling)
                        self.assertEqual(
                            getattr(
                                dataclasses.replace(instance, **{field: ""}), field
                            ),
                            "",
                        )
                        with self.assertRaises(TypeError):
                            dataclasses.replace(instance, **{field: b"original bytes"})
        raw = self.examples["RawRef"]
        self.assertEqual(raw.relative_path, "./Segment/../Bytes")
        self.assertEqual(raw.sha256, "AB" * 32)
        self.assertNotEqual(raw.root_locator, "synthetic:Root:É")

    def test_owned_record_fields_reject_shape_only_substitutes(self):
        for name, instance in self.examples.items():
            for field, hint in get_type_hints(type(instance)).items():
                candidates = (
                    get_args(hint)
                    if get_origin(hint) in (types.UnionType, Union)
                    else (hint,)
                )
                if not any(
                    dataclasses.is_dataclass(get_origin(item) or item)
                    for item in candidates
                ):
                    continue
                with (
                    self.subTest(record=name, field=field),
                    self.assertRaises(TypeError),
                ):
                    dataclasses.replace(
                        instance, **{field: {"synthetic": "shape-only"}}
                    )

    def test_lifecycle_and_row_publications_have_different_required_presence(self):
        publication = self.examples["RawPublication"]
        for field in OPTIONALS["RawPublication"]:
            self.assertIsNone(getattr(publication, field))
        occurrence = dataclasses.replace(
            self.examples["OccurrenceHandle"],
            key=self.examples["RowKey"],
            controller=ExampleReference("controller-example"),
        )
        refs = {field: self.examples["RawRef"] for field in OPTIONALS["RawPublication"]}
        row_publication = dataclasses.replace(
            publication, occurrence=occurrence, **refs
        )
        for outcome in CLOSED[("RawPublication", "outcome")]:
            for missing in refs:
                with (
                    self.subTest(outcome=outcome, missing=missing),
                    self.assertRaises(ValueError),
                ):
                    dataclasses.replace(
                        row_publication, outcome=outcome, **{missing: None}
                    )
        with self.assertRaises(ValueError):
            dataclasses.replace(occurrence, controller=None)
        for state in ("started", "completed"):
            with self.assertRaises(ValueError):
                dataclasses.replace(self.examples["OccurrenceHandle"], state=state)
            self.assertEqual(
                dataclasses.replace(
                    occurrence,
                    state=state,
                    executing_processes=(ExampleReference("executor-example"),),
                ).state,
                state,
            )

    def test_reference_parameters_are_independent_and_propagated(self):
        all_parameters = set()
        for name, parameter_names in PARAMETERS.items():
            cls = getattr(h, name)
            parameters = getattr(cls, "__parameters__", ())
            with self.subTest(record=name):
                self.assertEqual(
                    [p.__name__ for p in parameters], parameter_names.split()
                )
                self.assertEqual(len(set(parameters)), len(parameters))
                all_parameters.update(parameters)
                if parameters:
                    # Every role can bind a distinct external provider class.
                    bindings = tuple(
                        type(f"Example{p.__name__}", (), {}) for p in parameters
                    )
                    self.assertEqual(get_args(cls[bindings]), bindings)
        self.assertEqual(len(all_parameters), 22)
        hints = get_type_hints(h.HostCoverage)
        self.assertEqual(
            get_args(hints["observation"]), h.HostObservation.__parameters__
        )
        self.assertEqual(
            get_args(hints["through_boundary"]),
            h.HostEffect.__parameters__,
        )
        self.assertEqual(
            get_args(get_type_hints(h.ReceiptProvenance)["raw_publication"]),
            h.RawPublication.__parameters__,
        )

    def test_same_shaped_reference_is_not_authentication_and_is_never_inspected(self):
        # Even matching labels are merely data. No supplier, lookup or verifier
        # is provided by this package, so these cannot become admissions.
        issued_example = ExampleReference("same-shape")
        forged_example = ExampleReference("same-shape")
        self.assertEqual(issued_example, forged_example)
        self.assertIsNot(issued_example, forged_example)
        job = dataclasses.replace(
            self.examples["SelectedHostJob"], selection=forged_example
        )
        self.assertIs(job.selection, forged_example)
        self.assertNotIn("NativeSelection", h.__all__)
        self.assertNotIn("AcceptedData", h.__all__)

        class Uninspectable:
            def __getattr__(self, name):
                raise AssertionError("reference internals inspected")

            def __repr__(self):
                raise AssertionError("reference contents exposed")

            def __eq__(self, other):
                raise AssertionError("reference compared")

        reference = Uninspectable()
        self.assertIs(
            dataclasses.replace(job, selection=reference).selection, reference
        )
        with self.assertRaisesRegex(TypeError, "byte_length must be int, not bool"):
            dataclasses.replace(self.examples["RawRef"], byte_length=reference)


if __name__ == "__main__":
    unittest.main()
