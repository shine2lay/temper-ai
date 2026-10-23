# ops-host-inspect/2 decoder (P3)

`configs/architecture/bin/ops_host_inspect.py` decodes one fixed `ops-host-inspect/2` snapshot for one expected window, container and target. It returns the snapshot as UNTRUSTED read-only data, or refuses with one fixed local code. It uses the Python stdlib only, with no I/O, clock or caller wiring.

Architecture task #218 (project three-passing-projects) built it from the HOME-adopted r3 packet `p3-d3-abi-source-plan-r3` (SHA256SUMS `caa690894dbb0802c728b11ba2c65587464f1503fca7ccfe0d51d552f6afdc20`). The sources are ABI.md A1 (limits), A4 with A4.1–A4.4, and A7; CASE-REQUIREMENTS.md F3; and source-plans.json `plans.P3`. Its receivings are Ops #429 (the R3 field audit) and Ops #440 (P3-C1/M1/M2).

## API

```python
data = parse_inspect2(raw, window_id="win-…", container_id="<64 lowercase hex>", target="app")
data.trust     # always "UNTRUSTED"
data.snapshot  # read-only: MappingProxyType objects and tuple arrays, a fresh copy per call
```

- `parse_inspect2(raw: bytes, *, window_id: str, container_id: str, target: str) -> Inspect2Data`. The three expected values are keyword-only and have no defaults.
  - `raw`: exact `bytes`, 1 to 16384 of them.
  - `window_id`: the expected window, a nonempty string.
  - `container_id`: the expected full container ID, 64 lowercase hex characters.
  - `target`: exactly `"app"` or `"forwarder"`. It is data to check the bind against and grants nothing.
- `Inspect2Data` is a frozen dataclass with exactly two fields, `snapshot` and `trust`. `trust` is not a constructor argument. Its repr never shows the snapshot, so Env values do not reach a log through it.
- `TargetRefused(ValueError)` has a read-only `code`. `args == (code,)`, `str()` is the code, and the repr holds the code and nothing else. Building one with anything outside the eleven codes raises a plain `ValueError`.
- `TARGET_CODES` is the eleven-code A7 vocabulary, with one constant per code.
- Constants: `SCHEMA = "ops-host-inspect/2"`, `MAX_INSPECT_BYTES = 16384`, `MAX_DEPTH = 32`, `TARGETS`, and `RUNTIME_RULES` and `STATE_RULES`, whose keys are the exact 23 runtime and 7 state members in contract order.

## Errors (A4.3, A7)

| Refusal | When |
|---|---|
| `TARGET_SCHEMA_MISMATCH` | Strict parsing gave a closed outer object (exactly the six members) whose `schema` is a string other than `ops-host-inspect/2`. This includes /1 with 22 or with 23 runtime members. |
| `TARGET_EVIDENCE_INVALID` | Everything else: bad arguments; non-bytes, empty or oversize input; invalid UTF-8, a BOM or depth over 32; malformed JSON, a duplicate name at any depth, NaN or Infinity, any number with a fraction or exponent; a missing, extra or non-string `schema`; a window or container mismatch; any runtime or state member fault, including /2 with 22 runtime members; the target bind; structural time. |

Only the module's own `TargetRefused` with `TARGET_SCHEMA_MISMATCH` comes out as SCHEMA_MISMATCH. Any other exception while decoding becomes `TARGET_EVIDENCE_INVALID`. That covers a stranger's class with a `.code`, a ProtocolError-shaped error, a `RecursionError` and a `KeyError`. The refusal is raised fresh, with no message, cause or context, and holds no input bytes or Env values.

The checks run in this order: arguments; bytes (size, strict UTF-8, depth, JSON with the duplicate and number rules); the closed outer six with a string `schema`; the fixed /2 literal, which is the only SCHEMA_MISMATCH; the outer members; the expected window; the expected container; runtime 23; state 7; structural time; the target bind. The order only decides the code. A typed wrong schema is SCHEMA_MISMATCH whatever else is wrong after it, and anything wrong before it is EVIDENCE_INVALID.

## Members (A4, A4.1 and the Ops #429 R3 field audit)

Text is a string with no NUL and no lone surrogate. It must be nonempty unless an empty allowance is listed below. Objects are closed: exact keys, in any order. Arrays keep their order. A "sorted unique" array must already be strictly increasing; the decoder never sorts or deduplicates to accept one. Booleans are JSON `true`/`false` only. Integers are JSON integers only, never booleans, fractions or exponents.

Outer six: `schema`; `window_id` (nonempty text); `container_id` (64 lowercase hex); `runtime`; `state`; `observed_at`.

| Runtime member | Rule |
|---|---|
| `image_id` | `sha256:` and 64 lowercase hex, optionally after a repository `R@` (lowercase alphanumeric runs joined by `._/:-`), at most 255 characters. Syntax only, not image equality. |
| `command` | Nonempty array of nonempty text, order kept. |
| `workdir`, `user`, `pid_mode`, `ipc_mode`, `uts_mode` | Text; empty allowed. |
| `env` | Array of `KEY=VALUE` text, split at the first `=`. The key is nonempty; the value may be empty or hold more `=`. Well-formed duplicates are kept in order. |
| `image_env` | The same tokens with unique keys, order kept. |
| `mounts` | Sorted unique array of closed `{type, source, destination, rw, propagation}`. The four text members may be empty; `rw` is a boolean. |
| `tmpfs` | Object with nonempty text keys and text values (empty allowed). |
| `read_only_root`, `privileged`, `init` | Boolean. |
| `cap_drop`, `cap_add`, `security_options` | Sorted unique array of nonempty text. |
| `devices` | Sorted unique array of closed `{path_on_host, path_in_container, cgroup_permissions}`, all nonempty text. |
| `limits` | Closed `{pids, memory_bytes, nano_cpus}`, integers ≥ 0. |
| `restart_policy` | Closed `{name, maximum_retry_count}`: nonempty text and an integer ≥ 0. |
| `ports` | Sorted unique array of closed `{host_ip, host_port, container_port, protocol}`: nonempty text, 1..65535, 1..65535, and `tcp` or `udp`. |
| `networks` | Sorted unique array of closed `{network_id, network_name, aliases}`: 64 lowercase hex, nonempty text, and a sorted unique array of nonempty text. |
| `data_bind` | `null`, or closed `{source, destination, rw}` with absolute canonical paths and a boolean. |

Sorted unique text arrays compare strings. Arrays of records compare the UTF-8 bytes of each full record as `json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, the whole record and never a projection. An absolute canonical path starts with `/` and has no empty, `.` or `..` segment, and no trailing `/` unless it is `/` itself.

State seven:
- `running`: boolean.
- `status`: nonempty text.
- `started_at`, `finished_at`: a timestamp, or the zero sentinel.
- `exit_code`, `restart_count`: integers ≥ 0.
- `oom_killed`: a boolean, as observed. It is never inferred from exit code 137.

## Structural time (the A4.2 subset)

- A timestamp is `YYYY-MM-DDTHH:MM:SS`, then an optional `.` with 1 to 9 fraction digits, then `Z` or `±HH:MM`. T and Z are uppercase; digits are ASCII only. Dates must be real calendar dates, leap years included, and seconds run 00–59. `-00:00` (an unknown offset) is refused.
- `observed_at` needs at least 3 fraction digits (milliseconds) and is never the zero instant.
- The zero sentinel: a `started_at` or `finished_at` at Docker's zero time `0001-01-01T00:00:00Z`, in any spelling of that instant, means "no event". It is not compared.
- Only actual events are compared, as integer nanoseconds across offsets: `started_at ≤ observed_at`, `finished_at ≤ observed_at`, and `started_at ≤ finished_at` when both are events.
- Nothing else: no current time, TTL, deadline, operation order, health or stop judgment. Those stay with P5.

## Target and bind (A4.2)

- For target `app`, `data_bind` must not be null.
- For target `forwarder`, `data_bind` may be null. A present one must still be structurally valid.

## Future clean data, missing compatibility (A4.4)

Clean /2 cases are synthetic future-contract data only. Ops #429 found that the actual producer, validator and corpus emit and require `ops-host-inspect/1` with the 23 runtime members (agent-tools `b4fc303e`). That is disclosed history; it is never imported, copied or used as /2 evidence here. This decoder refuses that /1+23 data with SCHEMA_MISMATCH and /2 with 22 runtime members with EVIDENCE_INVALID. It never retags and never dispatches on member count. Actual /2 producer, validator and corpus compatibility stays MISSING until a separately approved versioned Ops delivery and its own receiving.

## Limits

- Future data only: data passing here is no evidence that anything emits /2.
- No producer, validator or corpus compatibility.
- No native authenticity: the result is UNTRUSTED, and nothing shows who wrote the bytes.
- No equality checks (image, argv, mounts, networks, confinement, image baseline): syntax and structure only.
- No operation chronology, TTL or health verdicts.
- No I/O, clock, environment, process, network or producer import. A test scans the module's syntax tree for them.
- No caller wiring: P5 decides how to use it.

## Choices where the contract leaves room

- Precedence, as in "Errors" above. Unexpected internal errors on bad input become EVIDENCE_INVALID.
- Text: no NUL and no lone surrogate anywhere, keys included. Empty strings only where the table allows them, which matches the disclosed source-empty allowances.
- `command` must be nonempty, because argv needs a program. Other arrays may be empty.
- `env` duplicates are kept and `image_env` keys must be unique (F3-ENV-DUPLICATE).
- The zero sentinel is matched by instant, not by spelling.
- Timestamps follow RFC 3339 with the limits above; `observed_at` needs milliseconds (amendment §6).

## Open finding (handed to the lead, not changed here)

A4.2 applies `started_at ≤ finished_at` whenever both are events. Docker keeps the previous `FinishedAt` when a stopped container is started again, so a restarted running container normally shows `StartedAt` after `FinishedAt`. This decoder refuses that data with EVIDENCE_INVALID, as A4.2 says, and a restart's start leg (ABI A6.1) would hit it. The proposed fix is a contract delta (apply the order only when `running` is false, or drop it), then its Ops receiving, then a one-rule revision here with its own test twin.

## Tests

Run `python3 -m pytest -q tests/test_architecture/test_ops_host_inspect.py` from the repo root. Each F3 row has tests named `test_f3_<row>_n_*` and `test_f3_<row>_c_*`. An `_n_` test is a negative that must refuse with its code, or a mutant that its clean twin catches. A `_c_` test is a clean twin that must be accepted. Guard bites switch one guard off and show that its own negative is then accepted while the other guards still hold. The test file also pins the eleven codes and checks that refusals and the result's repr never carry Env values.
