# Independent admission oracle packet (#306)

Accountable lead: Architecture. Fixture-only groundwork for T1/T2/T3/V1; not an engine contract, compiler, candidate registration or runnable workflow.

## H-A1-ORACLE-1 — written before fixture/test edits

Problem/evidence: #303 freezes V01–V36 but its paper seed is only a subset, with placeholder digests. Expected answers derived by the same normalizer as the consumer can hide a dropped field, swapped position or ignored raw key. HOME H-303-HOME-1 requires Temper's wire contract before the coupled compiler.

Change: hand-author a separate INPUT and EXPECTED packet: full clean graph policy/agent maps, 42 full positions, real hashes of explicitly synthetic fixture bytes, and scenario answers for the existing 36 cases. No production normalization, compiler, preparer, model client or engine imports manufacture expectations. Standard JSON and hashing check integrity only.

Expected measurement: packet tests establish strict representation, complete field inventories, exact 14×3 position coverage, negative-input inequality to independent expected maps, internally consistent hashes and phase/claim predictions. The immutable V01–V36 wording remains traceable without weakening it.

Falsifier: an expected semantic answer imports/derives from production output, a runtime policy/native field is missing, a wrong-valid position passes complete map equality, or a custody placeholder is treated as runnable. A consistency pass is not evidence that the real engine enforces the answer. Outcome: HIT for packet consistency only — the first and only standalone suite run passed 17/17. All 36 original cases (133 literal/scenario variants), 42 full positions, complete source-field inventories and strict internal hashes passed. Consumer drift detection remains a prediction until the real implementation is exercised; no engine result is claimed.

Pre-run author review: raw prohibited `memory`/`defaults` presence is absent even when null; the independently stated effective workflow still includes both defaulted fields. Added explicit positive readiness/identity facts and variant-level answers for mixed preserve/refuse scenarios so an absent baseline field cannot masquerade as an independently stated expected value. This is fixture authoring, not a consumer repair or wire-schema decision.

## Scope and authority

Source basis: `876e2b677a5eeb38a0371d2004cd31ae12aa0c08`, tree `1d773cd5a34b16f3e9274c452bcea213d78fa416`. Fresh worktree starts at that exact source (no initial drift). #303 seal `f44ee360586f95e2f8dc51754ec8ea9474efad12b45965935f4b665065a6d7e6`; #299 final seal `216abd1d35d137eef90c60b74546ebbd54f7776db65d5c03b1a038eed5adfe18`; HOME adoption SHA-256 `bf6f31c0e2f9e4da2a179fafdb234dd32fb2334611ae51262af96cfb96bfd168`. Both source seals checked successfully before authoring.

Only new files under `configs/architecture/stages/context_profile/admission_oracles/`, `tests/test_config/test_context_profile_admission_oracle.py`, and this document are owned. `claim_files` rejected these absolute paths because the task chat is rooted in rollcall; no false rollcall claim was made. Dedicated worktree `temper-ai-arch-306-admission-oracles` provides separation.

No live DB/config/API/worker inspection, private input, answer key, credential/environment value, model-bound request, provider call or second Temper. Synthetic fixture octets are inert test data, not a request, prompt transcript or real candidate. No script in the packet is executed. All runtime scenarios remain UNEXECUTED. Existing native fixed 900-second/8192-token values are represented, not new discretionary limits. Pricing and cap values are synthetic test design, not a live budget policy.

Compiler work must wait for Temper's actual frozen wire contract. This packet is explicitly NOT `ApprovedCandidateDescriptor/v1` and cannot substitute for that deliverable. Binding NOT MET; custody NOT ESTABLISHED; #292 PARTIAL; #293 remains 0/42; Stage1 quality remains unproved.

## Original standalone result (before commit/landing gates)

Command: `/usr/bin/python3 tests/test_config/test_context_profile_admission_oracle.py -v`, working directory the fresh worktree. Retained systemd unit: `arch-306-oracle-suite.service`, invocation `42f9e6e4c63242f79e34a0d957006007`. Main process status 0, Result=success, SubState=exited. The `systemd-run --wait --remain-after-exit` client waited on the retained unit after tests had finished; its now-unneeded terminal was closed. This was not a suite failure or second run.

Original `journalctl --user -u arch-306-oracle-suite.service --no-pager -o cat` export at capture: 2,954 bytes, SHA-256 `edbcdc7199db13e537ec9adc3043a1f131f121e62a693242609072339c63ba4a`. Complete unittest output:

```text
test_alias_independence_is_only_a_packet_property (__main__.AdmissionOraclePacketTests.test_alias_independence_is_only_a_packet_property) ... ok
test_clean_recursive_graph_and_serial_ready_accounting_edges (__main__.AdmissionOraclePacketTests.test_clean_recursive_graph_and_serial_ready_accounting_edges) ... ok
test_closed_packet_sections_and_frozen_file_hashes (__main__.AdmissionOraclePacketTests.test_closed_packet_sections_and_frozen_file_hashes) ... ok
test_complete_native_field_inventory_without_engine_import (__main__.AdmissionOraclePacketTests.test_complete_native_field_inventory_without_engine_import) ... ok
test_complete_policy_field_inventory_without_engine_import (__main__.AdmissionOraclePacketTests.test_complete_policy_field_inventory_without_engine_import) ... ok
test_diagnostic_expected_record_is_metadata_only (__main__.AdmissionOraclePacketTests.test_diagnostic_expected_record_is_metadata_only) ... ok
test_every_mutation_is_materializable_and_differs_from_literal_oracle (__main__.AdmissionOraclePacketTests.test_every_mutation_is_materializable_and_differs_from_literal_oracle) ... ok
test_exact_42_full_positions_not_global_slot_uniqueness (__main__.AdmissionOraclePacketTests.test_exact_42_full_positions_not_global_slot_uniqueness) ... ok
test_input_maps_equal_separately_literal_expected_maps (__main__.AdmissionOraclePacketTests.test_input_maps_equal_separately_literal_expected_maps) ... ok
test_original_36_expectations_are_not_weakened (__main__.AdmissionOraclePacketTests.test_original_36_expectations_are_not_weakened) ... ok
test_phase_counter_and_consumed_claim_predictions_are_explicit (__main__.AdmissionOraclePacketTests.test_phase_counter_and_consumed_claim_predictions_are_explicit) ... ok
test_script_templates_metadata_and_hashes_are_closed (__main__.AdmissionOraclePacketTests.test_script_templates_metadata_and_hashes_are_closed) ... ok
test_strict_json_rejects_duplicate_nonfinite_and_trailing_data (__main__.AdmissionOraclePacketTests.test_strict_json_rejects_duplicate_nonfinite_and_trailing_data) ... ok
test_synthetic_octets_and_noncyclic_hash_bindings (__main__.AdmissionOraclePacketTests.test_synthetic_octets_and_noncyclic_hash_bindings) ... ok
test_test_module_has_only_stdlib_imports_and_no_external_io (__main__.AdmissionOraclePacketTests.test_test_module_has_only_stdlib_imports_and_no_external_io) ... ok
test_unknown_custody_never_becomes_runnable (__main__.AdmissionOraclePacketTests.test_unknown_custody_never_becomes_runnable) ... ok
test_wrong_valid_slot_and_whole_map_swap_are_not_syntax_or_bag_checks (__main__.AdmissionOraclePacketTests.test_wrong_valid_slot_and_whole_map_swap_are_not_syntax_or_bag_checks) ... ok
----------------------------------------------------------------------
Ran 17 tests in 0.079s
OK
```

Fixture manifest SHA-256: `65c388386130b7707cb241be6e5ed59cbf5ebab403e7563051e038c34f696161`. Test file SHA-256: `4fac32c64acaa0203f5fa71521825edbb7358bc933baf6335963603e49057f5c`. The manifest lists all eight exact data/README hashes, eight expanded raw-record hashes, five script-template hashes and canonical expected graph/native-map hashes. These are integrity evidence, not semantic engine acceptance.

Normal commit/land hooks and remote-only GitHub CI are still required. Any rebase/source drift and exact final commit/tree/parent are delivered with the landing result rather than guessed in this self-referential file. Normal gates may rerun the packet as part of the repository suite; they do not execute its imagined runtime scenarios.
