# Vendored from pi-multi-pass b8423d2

pi-multi-pass's own limits check (the one behind its `/subs` command), copied byte for byte so the
temper-pi-host auth bridge reads an account's usage windows exactly the way Pi does. Never edit these
files: a change comes as a new vendor folder from a new pi-multi-pass commit, with new digests here and
in `temper_pi_host_bridge.mjs` (`VENDOR`).

- Source: https://github.com/shine2lay/pi-multi-pass (a fork of
  https://github.com/hjanuschka/pi-multi-pass), branch `mine`, commit
  `b8423d27d71e557483319061724528a4b88a83b6`.
- Licence: MIT, see `LICENSE` beside this file (copied unchanged from the same commit).

| file | source path at b8423d2 | sha256 |
|---|---|---|
| subs-limits.ts | extensions/mine/subs-limits.ts | 22a2297e9ad5b493875129a0fb6fa7dea575e7bfb3355d36219f3b9bb73f7489 |
| reset-countdown.ts | extensions/mine/reset-countdown.ts | 3bb5b9f8171726b8c1ce25b2cd3382e8aa2604490a7bac164299ab104427c8b6 |
| LICENSE | LICENSE | 11b2d9776f60557f994e63fd4daceaadfffb5757502121a50eb301a8e03ec535 |

- Runtime files: `subs-limits.ts` and `reset-countdown.ts`. `subs-limits.ts` imports
  `./reset-countdown.ts` (for `formatResetIn`, used only by text the bridge never asks for).
  `reset-countdown.ts` imports nothing but types (`import type ... from "./current-model-limits.ts"`),
  which Node's type stripping erases at load, so `current-model-limits.ts` is not needed and not copied.
- Node 22.18+ loads both as they are (type stripping; the files use erasable TypeScript only). The
  bridge checks both digests before it loads them, and loads them only for a `usage` request.
- The bridge calls only `checkAccount` and `ANTHROPIC_USAGE_URL`: with no `host.refresh` (so it never
  refreshes a sign-in), with a stand-in previous row (so it never asks for the account's profile), with
  a fetch that allows only a GET of `ANTHROPIC_USAGE_URL`, and with no readings file (nothing is
  written or published). See docs/pi-host-helper.md, "usage".
- `tests/test_pi_host/test_usage.py` checks the digests above.
