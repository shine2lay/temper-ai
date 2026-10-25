# #306 independent, synthetic admission oracles

**TEST FIXTURES ONLY. NOT A RUNNABLE WORKFLOW.** No file here is a production descriptor, candidate config or `ApprovedCandidateDescriptor/v1`. The format is private to the packet tests; Temper owns the future wire contract. JSON files are not config-importable YAML. No fixture script is executed and no listed absolute path is opened.

The fixtures state semantic answers, not measurements of the engine. Every runtime prediction is `UNEXECUTED`. The suite only checks the packet's internal consistency. It cannot prove that a consumer checks a field, that custody exists, or that Stage1 answers are good.

## Reading order

1. `provenance.json`: source seals, synthetic authority and exhaustive source-field inventories.
2. `octets.json`: inert hex-encoded synthetic octets and literal computed SHA-256 values. Pricing is synthetic zero-price test data with an example.invalid evidence URL. Nothing is a real request, credential, private brief or answer key. `source/config/packet` hashes each have separate, noncyclic synthetic preimages, not production preimage definitions.
3. `inputs.json`: hand-written compact INPUT tables and raw closure for one clean preparation/three-call/accounting/receipt graph. Slot paths are literal; no runtime interpolation creates call configs. Table columns are only a test-storage abbreviation. The fixture reader expands INPUT rows with literal INPUT constants; it never builds EXPECTED from these rows.
4. `expected-graph.json`: independently hand-written full workflow policy, full node policy dictionaries and script agent dictionaries. `_KNOWN_FIELDS` is class metadata, not runtime policy. Every field at the pinned source revision is listed, including null/default values. Explicit refs have resolved children; the expected recursive tree is named by the literal children map. Node path is the key, never a sorted bag of configs.
5. `expected-positions.json`: all 42 literal full positions and complete native `single_call` dictionaries, stored as a full-value table. Each key and each value is literal; `zip(columns, row)` merely decodes it (no defaults, formulas, semantic normalization or generated expected values). The five common outer agent fields are an explicit literal envelope, not inherited defaults; each expected native config is exactly that envelope plus the literal per-position `single_call`. Each position states exact node, root and preceding ready/accounting paths. A1/A2/A3 repeat legally under different roots. Legacy script configs also retain the exact source `_KNOWN_FIELDS` frozenset; `expected-graph.json` records this separately as class metadata rather than pretending it is JSON or silently losing it.
6. `cases.json`: V01–V36, original sealed change/expected wording verbatim, independent INPUT mutation/scenario and EXPECTED boundary/counters/claim state. Subcases preserve the alternatives in each original V case. Structural/byte deltas act on INPUT only. Runtime scenarios are metadata assertions for future T1/T2/T3/V1 adapters, not executed tests of state machines.
7. `manifest.json`: SHA-256 of exact frozen data files (not self-referential). It does not confer authority.

`INPUT` and `EXPECTED` live in different files/sections on purpose. Shared JSON/SHA helpers check strictness and byte integrity only. No production engine, normalizer, compiler, preparer or client is imported. A negative map is checked against an independent literal expected map; changing both observed bytes and their self-digest is not external approval.

The complete clean graph covers r01. The 42-position table additionally states each record's serial dependency chain: preparation → A1 → accounting A1 → A2 → accounting A2 → A3 → accounting A3 → receipt. It is an inventory, not another submitted workflow. Ready/accounting edges are substantive; no fanout authority is implied.

Synthetic ownership, inodes, generation and dispatch IDs in scenarios are labelled facts of an imagined test world. Live custody is null/UNKNOWN and `runnable` is false. An unknown tuple may not be made runnable by inserting these numbers. Paper #303 placeholder hashes (all 1s/all 2s) are retained only in provenance, never used as a computed fixture hash.

See `docs/context-profile-admission-oracles.md` for H-A1-ORACLE-1, results and limits. Run the model-free packet suite: `python3 tests/test_config/test_context_profile_admission_oracle.py -v`. No environment values, network, provider, DB or runtime are used by that command.
