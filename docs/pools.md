# Claude account pools and the week line

temper spreads its Claude work over several subscriptions (the `CLAUDE_CODE_OAUTH_TOKEN`,
`_BACKUP` and `_2`..`_9` variables, each named by its `_ACCOUNT` variable). Two pickers choose
the account for each call, and both work the same way:

- `TokenPool.pick` in `temper_ai/llm/token_pool.py`, for the direct providers (`anthropic`);
- `_pick_token` in temper-local's `providers/claude_code.py` and its `claude_code_v2.py` twin,
  for the claude tool (`claude`, the Claude Code CLI).

## How an account is picked

1. **Sticky slot.** One agent in one run always starts on the same account, chosen by a hash of
   `<run id>-<agent name>` (or the call's `session_id`). Anthropic's prompt cache belongs to an
   account, so the rule is: rotate between agents, never within one. A resumed run keeps its run
   id, so every agent goes back to its account.
2. **Cooled and dropped accounts are skipped.** An account that refused (a rate limit, an
   account switched off) sits out until its reset, shared by every process through Redis
   (`temper_ai/llm/shared_cooldowns.py`). A real weekly limit still cools, parks or fails the
   run as before.
3. **The week line.** An account whose weekly figure is at or above the line is skipped while
   another usable account is under it. When every usable account is over the line, the sticky
   slot is used as before.
4. **Stable failover.** When the sticky slot is skipped (cooled, or over the line), the agent
   goes to the account its key weighs highest among those left (rendezvous hashing), so it stays
   on one account instead of bouncing between them.

With no account over the line and none cooled, every agent keeps exactly the account it had
before the week line existed.

## Where the weekly figure comes from

Only from calls made through the claude provider. The claude tool reports each account's rate
limits in its own output (a `rate_limit_event` line in its stream), and the provider, which
reads that output anyway, keeps the weekly figures (`temper_ai/llm/week_usage.py`). Nothing is
polled and no extra call is made. So:

- an account temper hasn't used through the claude tool lately has no figure, and counts as
  under the line;
- the direct `anthropic` provider adds no figures of its own, but reads the same ones, since the
  accounts are the same.

Per account label (never a token) and weekly kind (the account's week, and a single model's week
when the tool reports one), temper keeps the share used, when it was seen and when that week
resets. The highest weekly kind decides. A figure stays in force until its week resets (two hours
after it was seen when no reset time came with it). A figure under the line never moves anyone.

The figures live in Redis (`temper:week_usage`), so what one run's box saw steers every other
run, the server and the worker. Without Redis each process keeps what it saw itself.

## Setting the line

`configs/pools/pools.yaml`:

```yaml
pools:
  week_line: 0.90
```

A copy in `configs/pools/local/pools.yaml` (git-ignored) wins. The default is 0.90: above 90% of
a week, roughly a day of heavy use is left. The next pick in every process reads a change; no
restart is needed. A value that isn't a share of a week (above 0 and at most 1) is logged and
0.90 is used.

## Seeing it

`GET /api/pools` lists, beside each pool's cooling state:

- `week_line`: the line in use;
- `accounts`: one row per account label, with `week_used` (a share, null when there is no figure
  in force), `week_kind`, `seen_at`, `resets_at` and `over_line`.

Labels and times only, never a token.

## Unregistered private native attempts

`temper_ai.llm.private_pool.invoke_private_pool` is an **unused capability**, not
an agent mode or a registered profile. It selects from the native Anthropic OAuth
pool with the real `TokenPool.pick`, including a one-slot pool. An empty,
unavailable or non-OAuth pool refuses: an API key, named token lookup, CLI or
another provider is not a substitute. Existing named-image and ordinary calls
keep their existing behavior.

The entry requires A's `PrivateLease`, `PrivateContextService` and `MediaCapability`,
an invocation id, cancellation/deadline, a `NativePrivateMedia`, and two mandatory
integration callbacks. `guard()` must perform the normal `LLM_CALL` policy check
and current custody/cancellation/expiry fences; `account(outcome)` must pair normal
per-attempt call/usage recording using only the closed `AttemptOutcome` metadata.
There is no default successful policy, accounting, reservation or persistence
implementation. The later runtime integration owns these bindings and result-schema
validation/publication; this capability enables none of them.

Each possible HTTP send first obtains a durable, exactly matching reservation.
The attempt uses the same `send_native_once` reader and `SingleSendControl` as the
legacy named wrapper, with SDK retries and redirects disabled. Only a **fully
consumed pre-stream HTTP refusal** permits a next attempt, after durable refusal
persistence and accounting:

| Status | Next action |
|---|---|
| 429 | Existing model cooldown, then real pool pick |
| 401 / 403 | Exclude this credential for this invocation only, then pick |
| 529 | Existing exponential backoff with jitter, same credential |
| 400 / 413 | Terminal configuration / platform-limit failure |

`TokenPool.pick(..., exclude=frozenset(...))` is optional; its default selection,
weekly preference and cooldown behavior are unchanged. On exhaustion, the safe
receipt includes the picker's earliest existing reset when known; it never probes
an allowance or invents a reset. No retry-count quota is
added. Every attempt and overload wait rechecks the supplied policy and the
existing deadline/cancellation fences. The existing five-second cleanup margin
still applies.

A lost reservation reply, uncertain cleanup, failed refusal persistence/accounting,
partial stream or SSE error after HTTP 200 never triggers another send. A terminal
invalid JSON object likewise never regenerates. Usage remains nullable; unknown
usage names/values, response ids, private text, hashes, request bodies and raw
exceptions are excluded from the private outcome. Every returned private result
must stay on the explicit private boundary, never generic events/checkpoints.
No production capability limits or entitlement are inferred; see [media limits](image-inputs.md#unused-private-zero-or-many-capability).

A pick the line moved logs one warning naming the account it skipped and that account's figure,
for example:

    anthropic-oauth: skipping shinelay at 95% of seven_day until 2026-10-08T19:00:00+00:00, at or above the week line (90%); picked aungshine
