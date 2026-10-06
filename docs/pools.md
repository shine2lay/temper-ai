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

A pick the line moved logs one warning naming the account it skipped and that account's figure,
for example:

    anthropic-oauth: skipping shinelay at 95% of seven_day until 2026-10-08T19:00:00+00:00, at or above the week line (90%); picked aungshine
