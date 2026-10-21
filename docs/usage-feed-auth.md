# Dedicated usage-feed credentials

This is inert groundwork, not an enabled route or permission to create a key.
It creates no key, registry, epoch, journal, collector state or mount at import,
startup or installation. Epoch/identity/cursor implementation and host transition
operations belong to separate changes. The existing general API authentication
is unchanged.

## H-AUTH2 — hypothesis, before implementation

Evidence: `api/api_keys.py` deliberately accepts good entries from a partly bad
registry, and `scripts/api_key.py` manages general write credentials. Reusing that
loader or registry for a feed would permit partial admission or a general writer.
Its raw-file location also needs a feed-specific check against mounted paths.

One change: add a separate, strict, hash-only loader and a `--feed` branch in the
existing host script, leaving general/run/shared authentication untouched. The
loader returns no principals unless the entire dedicated registry is valid.

Expected result: one combined fixture test adds, loads, identifies only for the
feed and revokes a key; fixed clean/catch cases exercise every invalid-store class,
credential class, header precedence and host custody guard. No raw canary reaches
the registry, stdout, stderr or logs. No live credential operation is used.
Disproof: any invalid registry admits a principal, a general credential promotes,
a feed key identifies as a general writer, or any custody/canary test fails.
Result: **HIT within fixture scope**. The single planned stage run passed all
205 tests across the new feed-auth stage and existing API guard/auth suites
(`uv run --frozen pytest tests/test_api/test_usage_feed_keys.py
 tests/test_api/test_api_guard.py tests/test_api/test_auth.py -p no:randomly -q
 --timeout=120`). Ruff passed on all three changed Python files; mypy passed on
the new runtime module. No live key or epoch operation, server copy, model or
workflow proof was used. This is not an activation or universal tamper proof.

Regression bites in `tests/test_api/test_usage_feed_keys.py`:

| Guard | Fixed catch/clean evidence |
|---|---|
| Whole-store validation | Every invalid class starts from a working store, then must admit **zero** names; clean 16-name and empty limits |
| Reload/revoke | Same-size/mtime edit, atomic replacement, deletion and combined remove journey; no stale authority |
| Credential separation | Each foreign class is also placed in the feed registry; it still must fail, with run/DB lookup forbidden |
| Compare/header rules | First/middle/last/absent match compares every hash; empty or wrong Bearer overrides a valid direct header; cookie/query ignored |
| Custody/namespace | Repo/worktree/mount/ancestor/symlink overlap, unknown mount inspection, other auth-store aliases, invalid names, full store and raw collisions all refuse |
| Raw file and output | Exclusive-create race keeps the foreign file; exact 0700/0600 under extreme umasks, wrong-owner refusal, failed-save cleanup and canary redaction |
| Existing behavior | Feed key remains unknown to general auth/middleware; general script behavior is unchanged and does not invoke feed mount inspection |

Each catch has an explicit refusal/no-write assertion, not merely a successful
happy path. Unrelated fixture progress is unchanged through the revocation journey.

## Store and callers

`TEMPER_USAGE_FEED_KEYS_FILE` selects the hash-only registry; its default is
`configs/api/local/usage-feed-keys.json`, under the existing read-only configs
mount. The inline `TEMPER_USAGE_FEED_KEYS` variable is ignored. No environment,
compose or mount change is needed. The file is git-ignored; do not commit it.

The closed format is `{"keys": {"<name>": "sha256:<64 lowercase hex>"}}`.
Names use the existing named-key grammar, excluding server-reserved names.
There may be at most 16 names. Missing, empty, unreadable, non-UTF-8, malformed,
wrong-shaped, duplicate-field or partly invalid input makes the **whole store
OFF**; there is no partial load or fallback. An empty keys object is OFF too.
Changes and revocation take effect on the next lookup, without a restart.
Only fixed status/count messages are logged, never registry contents or paths.

`feed_keys()` supplies a fresh copy of the validated mapping.
`identify_feed_key(presented)` checks store OFF, absent input, run-key prefix
(without any database lookup), shared/tokens-file credentials and general named
keys, in that order; then compares **every** dedicated hash in constant time.
It returns a feed name or `None`, not a general `Caller` or write power.
`identify_feed_headers(headers)` uses Bearer before X-Temper-Token, including an
empty Bearer taking precedence; query strings and cookies are not credentials.
The future route must always self-authenticate, return the fixed 403
`{"error":"not-allowed"}` on refusal, and retain its own exact-head reviews.
This module does not add a route, middleware exemption, MCP or CLI read endpoint.

## Host custody and rotation

The existing `scripts/api_key.py add|remove|list --feed` branch is for separately
authorized host operations only. The agreed logical principal is a host collector;
it is not a separate operating-system user or an isolation boundary. Temper owns
the hash registry and applies authorized additions/removals; Ops loads the raw
file and chooses rotation timing; custody changes need Security agreement.

Raw files use the existing `~/.config/temper/api-keys/<name>.key` location, outside
all container mounts: directory 0700, exclusive creation, file 0600, no printing.
This raw directory is **shared with general API keys**, not isolated. Unchanged
general `remove NAME` without `--feed` can delete a same-name feed raw file even
when NAME is absent from the general registry, **leaving its feed hash registered**.
Do not use general removal for feed names: feed revocation must use the separately
authorized `remove NAME --feed` path. This warning grants no credential operation.

The feed branch checks the repo/worktrees and current container mount sources
using read-only Docker inspection. If mount inspection is unavailable, it refuses
custody-changing operations rather than guessing. Explicit fixture paths use the
same checks. Registry output contains hashes only and remains server-readable.
The script refuses the general registry/tokens-file paths, unsafe names, an
invalid existing store and a raw-file collision. It never overwrites a raw file.

Every add/re-add needs a separate normally approved activation, rotation or
recovery plan. Remove/add rotation keeps the same logical reader: it does not
reset or delete progress/evidence, create an epoch or authorize recovery. OFF,
403, timeout and bad parameters retain progress. A revoke can be requested through
the established Ops/Security process; a revoke does not authorize a later add.
Same-UID tampering and host/DB superuser bypass remain explicit residual risks.
