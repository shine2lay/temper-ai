# P4: ops host Env comparator (ABI A5, CASE F4)

`configs/architecture/bin/ops_host_env.py` is a pure, stdlib-only comparator for the Env arrays the
ops host client (P5) supplies. It implements r3 ABI A5 with the Ops429 P4-01..12 semantics
received unchanged. It collects nothing: no Docker, file, network, subprocess or clock access, and
nothing in temper-ai imports it yet (P5 will). Tests: `tests/test_architecture/test_ops_host_env.py`.

## API

```python
compare_window_env(image_env: tuple, creation_env: tuple, observed_env: tuple, *, target: str, port: int) -> EnvAssessment
compare_a5_env(image_env: tuple, creation_env: tuple, observed_env: tuple, *,
               expected_argv: tuple, observed_argv: tuple, expected_env: tuple) -> EnvAssessment
```

- Every argument is mandatory. There are no defaults and no profile or dispatch argument: the
  window comparison and the A5 comparison are two separate functions.
- `EnvAssessment` is a frozen, slotted dataclass with exactly `trust`, `env_matches`,
  `creation_matches`, `reason`. `trust` is always `UNTRUSTED`; the booleans come only from the
  comparison; `reason` is one of `NONE`, `ENV_VALUE`, `ENV_DUPLICATE`, `ENV_ORDER`. It never holds
  an Env key or value, so its repr and fields export nothing from the arrays.
- `TargetRefused(ValueError)` is local to this module and carries the exact A7 vocabulary
  (`REFUSAL_CODES`, eleven codes in A7 order). Its args, str and repr hold exactly the code; no value,
  path or Env is interpolated, and no exception context is attached. The comparators raise only
  `TARGET_EVIDENCE_INVALID`.

## Input grammar (refuses with TARGET_EVIDENCE_INVALID)

- Each Env/argv array is an exact `tuple` of exact `str` items. `None`, a list, a map, a set, a
  string, or any subclass refuses; so does a non-str item. An explicit `()` is data and is judged.
- Items are nonempty, contain no NUL and are valid UTF-8. One array's total UTF-8 size is at most
  1,048,576 bytes (the ops host snapshot bound); larger input refuses, nothing is truncated.
- Env tokens split at the first `=` only. The key before it must be nonempty; the value is kept
  exactly, including an empty value and further `=` characters. No case folding, trimming,
  Unicode normalization, filtering, sorting, deduplication or last-wins.
- The image baseline's keys must be unique. A container array (creation or observed) may repeat
  a key in the window comparison: that is well-formed evidence of a mismatch, not invalid input.
- Window `target` is exactly `app` or `forwarder`. `port` is an actual `int` (not `bool`, not a
  subclass) in 1..65535, checked for both targets.

## Window comparison

- Expected map: the full image baseline map. For `app` only, the exact four overrides are applied
  on top: `HOST=0.0.0.0`, `PORT=8000`, `DATA_DIR=/data`,
  `ALLOWED_HOSTS=100.110.162.4:<port>,scanapp:8080`. The forwarder gets no overrides. Every
  inherited key must stay with its exact value; no key may be lost or added. An image key that is
  one of the four is legitimately replaced for `app` (the A5 four-key exclusion does not apply here).
- Initial map equivalence: the recorded creation array, read as a map, must equal the expected map.
  Its order is not checked against the image: Docker's array order is not invented from a map.
- Later ordered equality: the observed array must equal the recorded creation array token by token,
  in order. `creation_matches` reports exactly this.
- `env_matches` is true only when both arrays are duplicate-free, both maps equal the expected map
  and the observed array equals the creation array.
- Reason, first that applies: `ENV_DUPLICATE` (a container array repeats a key; never resolved by
  last-wins), `ENV_VALUE` (a map differs), `ENV_ORDER` (same content, order drifted), else `NONE`.

## A5 comparison (separate)

- A5 grammar on every Env array (image, creation, observed, expected_env): key regex
  `[A-Za-z_][A-Za-z_0-9]*` (full match) and no repeated key; either violation refuses.
- The image baseline may not carry `HOST`, `PORT`, `DATA_DIR` or `ALLOWED_HOSTS`; if it does, the
  call refuses (create_spec's four-key exclusion).
- `expected_argv` (nonempty) and `expected_env` are the separately frozen holder/case recipe,
  supplied by the caller as mandatory data. This module holds no recipe literal and grants nothing:
  a match is a comparison result, not permission to run a recipe.
- Expected map: image baseline updated with `expected_env` (the holder passes `()`). `env_matches`
  needs exact ordered argv equality, both container maps equal to it and the observed array equal to
  the creation array. Any argv or env difference is `ENV_VALUE`; order drift is `ENV_ORDER`.

## Missing versus explicit null

The A5 collector turns a present Docker `Config.Env: null` into `[]`. That is the collector's
decision about data it collected, made before this module is called. It is not permission for this
comparator to default anything: `None` (or any absent or malformed array) refuses here, while an
explicit `()` is compared as data. A3's collection is stricter and refuses `null` itself.

## What stays with P5

- Provenance. `image_env` is only the data P5 passes in. P5 proves on its own that it is the pinned
  image's exact baseline array, with its order, and that creation used the actual inputs. Two
  baselines with the same content in different orders get the same verdict here; the caller's
  arrays are not altered, so P5's ordered equality of `image_env` (a non-env runtime member, BLOCKED
  on drift) still sees the difference.
- The window port range. This module accepts any actual port 1..65535; the narrower authorized
  8970..8979 and window equality checks are P5's.
- The four-key runtime. The window/calibration runtime env and its hash stay the exact four keys.
  Inherited baseline keys widen only the compared container map, never that runtime or its hash.
- Refusal routing. P5 catches only this module's own `TargetRefused` and maps the result into its
  verdict; `TARGET_ISSUER_UNTRUSTED` and the other codes are vocabulary, not raised here.

## Limits

No image-baseline collection or provenance, no A5 or S5 qualification, no launch, no new recipe, no
native admission, no host or runtime action. A true `env_matches` is UNTRUSTED evidence for P5 to
weigh, never a verdict on its own.
