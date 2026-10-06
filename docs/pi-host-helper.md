# temper-pi-host: the host helper for Pi team members — switched off

`scripts/pi_host/temper_pi_host.py` is a small service that runs on the host, outside
Temper's containers, as the owner's own user. Pi team members (and the Pi worker that
runs them) ask it, over one Unix socket, for three things they must not do themselves
(M4 ADR-M4-02, -12 and -15):

- `token <slot>`: a login token for the run's pinned account slot, so the worker never
  holds the owner's Pi logins, host node or host Pi;
- `status`: the host's Pi, git and Pi SDK versions and each slot's login state, as words;
- `branch <repo> <leader git dir> <commit> <trial id>`: create one branch
  `team/<trial id>` in a source repo, from a team leader's git copy, and nothing else.

It is stdlib-only Python plus its auth bridge `scripts/pi_host/temper_pi_host_bridge.mjs`,
a small Node script delivered beside it. Nothing in this repo starts it: ops installs it as
a user unit, inactive and disabled until Pi is switched on. Everything about the machine
(paths, the served uid, the slots, the SDK version, the project roots, branch on or off,
the hourly ceiling) comes from a private config file outside the repo;
`scripts/pi_host/temper-pi-host.example.json` shows its shape with placeholders.

## What it can touch

- It reads its config file.
- It binds the socket named there. The socket's folder must already exist, belong to the
  helper's user and be mode 0700; the helper never creates, chmods or chowns a folder. The
  socket is made mode 0600 and removed when the helper stops. A stale socket left by a
  helper that died is replaced; a live one makes the start fail.
- It runs the host `pi` CLI (`pi_cli`) for `--version` and for the read-only
  `auth check --provider <slot> --json --no-refresh`, and nothing else.
- It runs `git --version`, and with the branch verb on, the hardened git below.
- It runs the auth bridge, which reads Pi's logins in `<pi_agent_dir>/auth.json` and Pi's
  multi-pass subscriptions in `<pi_agent_dir>/multi-pass.json`, and refreshes a login that
  is due, only through the pinned Pi SDK's own auth storage (its lock file is
  `<pi_agent_dir>/auth.json.lock`), for the allowed slots only.
- With the branch verb on, in a source repo under the project roots: one new ref
  `refs/heads/team/<trial id>`, and a temporary `refs/temper/branch-tmp/<trial id>` that is
  always removed again. It reads the leader's git copy under the Pi state root. Never a
  checkout, a push, a force or a moved branch.
- It stores nothing, and writes no file of its own. Its only output is one line per
  request on stderr (the journal, under systemd).

It never serves the base provider's own slot (account 1), never serves a slot other than
the one asked for, never copies a login to another slot or keeps one under another key,
never edits auth.json itself, never patches or upgrades the SDK, and never falls back to
another CLI.

## Config

A JSON object; keys starting with `_` are comments, any other unknown key refuses the
start. Defaults in brackets.

| key | what it is |
|---|---|
| `socket` | the socket's path, absolute and shorter than 100 bytes |
| `uid` | the only peer uid it serves (SO_PEERCRED) [the helper's own uid] |
| `pi_state_root` | Temper's Pi state root: team leaders' git copies live at `<root>/<run>/<team>/git/<name>.git` |
| `home` | HOME for the Pi CLI and the bridge [the helper's HOME] |
| `pi_agent_dir` | Pi's agent folder holding `auth.json` and `multi-pass.json` [`<home>/.pi/agent`] |
| `path` | PATH folders for the Pi CLI, node and git [the helper's PATH] |
| `pi_cli` | the command that runs Pi, as a list [`["pi"]`] |
| `base_provider` | the base provider whose multi-pass aliases are served [`anthropic`] |
| `allowed_slots` | the slots it serves, each an alias `<base_provider>-<n>` with n ≥ 2; the base slot itself (account 1) is refused in the config [none] |
| `bridge.node` | node's path [`node`] |
| `bridge.script` | the bridge's path (the pinned copy beside the script) |
| `bridge.sdk_root` | the folder whose `node_modules` holds the Pi SDK the running chats load |
| `bridge.sdk_package` | the SDK package [`@earendil-works/pi-coding-agent`] |
| `bridge.sdk_version` | the exact SDK version the running chats use |
| `bridge.ai_version` | the exact `@earendil-works/pi-ai` version beside it ["" = not checked] |
| `bridge.start_timeout_s` | how long the bridge may take to say hello [20] |
| `bridge.stop_grace_s` | how long a stopping bridge may take to finish a request [120] |
| `project_roots` | folders a source repo may be: `/a/b` (that folder) or `/a/*` (any folder directly in it) [none] |
| `branch_enabled` | the branch verb on or off [false] |
| `branch_max_bytes` | the largest new history a branch may bring, in bytes [104857600] |
| `tokens_per_hour` | the hourly token ceiling, a tripwire [120] |
| `token_timeout_s` | how long a token request may take [30] |

Without `bridge`, every token request is refused ("no auth bridge is configured"); the
status and branch verbs still work.

## Launch

```bash
python3 <pinned folder>/temper_pi_host.py serve --config <private config>
```

- Run it as the user it serves, with `python3` 3.11 or newer. No arguments but the config;
  no environment it relies on (the Pi CLI and the bridge get a fixed environment built
  from the config: `HOME`, `PATH`, `LANG=C.UTF-8`, `PI_CODING_AGENT_DIR`, `PI_OFFLINE=1`,
  `PI_SKIP_VERSION_CHECK=1`, `PI_TELEMETRY=0`, nothing else).
- Start: the config is checked, the socket folder is checked, the bridge is started and
  its Pi SDK checked (below), then the socket is bound. Any problem: one
  `temper-pi-host: refused to start: <why>` line, exit 2, no socket.
- SIGTERM or SIGINT: it finishes the request in hand, removes its socket, stops the
  bridge at its next safe point, says `temper-pi-host: stopped` and exits 0.
- `python3 <pinned folder>/temper_pi_host.py check --config <private config>` checks the
  config and the bridge's start (the same SDK check) without serving, prints a JSON
  report and exits 0 or 1.
- `python3 <pinned folder>/temper_pi_host.py ask --socket <socket> status` asks a running
  helper for its status (it can't ask for a token).

## Requests and answers

One request line per connection, one answer line back, one request at a time. A peer
whose uid is not `uid` gets `denied uid <n> is not served` and nothing else.

| request | answers |
|---|---|
| `token <slot>` | `ok <token>` or `denied <why, naming the slot>` |
| `status` | `ok <json>` |
| `branch <repo> <leader git dir> <commit> <trial id>` | `made`, `exists` or `denied <why>` |

Anything else: `denied the request is not one this helper knows`.

**token.** The slot must be one of `allowed_slots`; the helper checks that before the
bridge, and the bridge checks it again. Then the hourly ceiling, then the bridge, within
`token_timeout_s`. The refusals, each naming the slot and none carrying text from the SDK:
`slot <s> is account 1 and is never served`, `slot <s> is not an alias of <base>`,
`slot <s> is not one this helper serves`, `slot <s> is not registered in Pi's multi-pass
subscriptions`, `slot <s>: Pi's multi-pass subscriptions could not be read`,
`slot <s> has no stored login`, `slot <s> has no OAuth login`,
`slot <s>: its login could not be refreshed`, `slot <s>: the login gave no token`,
`slot <s>: Pi's auth storage could not be used`, `slot <s>: the Pi SDK on disk changed since
the helper started (now <found>, expected <expected>); auth.json was not read or written`,
`slot <s>: the Pi SDK could not be read; auth.json was not read or written`,
`slot <s>: the Pi SDK has no <base> login flow`, `slot <s>: the Pi SDK is <found>, expected
<expected>` (a bridge restarted after a timeout found another SDK),
`slot <s>: no token within <n> s`, `slot <s>: the hourly token ceiling (<n>) is reached`,
`slot <s>: no auth bridge is configured`, `slot <s>: the auth bridge stopped`,
`slot <s>: the auth bridge gave an unusable answer`, and for a malformed name
`the slot name is missing or malformed`. A token is handed out with at least 30 minutes
left on it. The ceiling counts the requests that reach the bridge over the last hour; past
it every token request is refused and a `tripwire` line is logged.

When a request times out, the bridge is told to stop at its next safe point (never in the
middle of a request: Pi writes auth.json in place); it is killed only if it is still
running `stop_grace_s` later. The next request starts a new bridge, with the start check.

**status.** Words only, never a token or an account id: `helper`, `protocol`, `uid`, `pi`
(the host Pi's version), `git`, `branch` (on/off), `tokens_last_hour`, `tokens_per_hour`,
`bridge` (`state`: `ready`, `sdk_changed`, `sdk_unreadable`, `refused`, `no_answer` or
`not_configured`; `expected`; the `package`, `version`, `ai_package`, `ai_version` and
`node` it loaded; `found` when the SDK on disk changed) and `slots`, for each allowed slot
`pi` (the stock CLI's status and reason words; the stock CLI does not know multi-pass
aliases, so expect `not_ready provider_not_found`) and `bridge` (`registered` or a refusal
code, then `login_ready`, `login_refresh_due`, `login_missing`, `login_not_oauth` or
`login_unknown_expiry`). Status never refreshes and does not count toward the ceiling.

**branch.** The repo must be absolute and normalized, under a project root both as given
and as its real path, the top of its git work tree, with its git folder and common git
folder inside the project roots. The leader's git dir must resolve to
`<pi_state_root>/<run>/<team>/git/<name>.git`, hold `HEAD` and `objects`, and borrow no
objects (`alternates`). The commit is a full 40-character id present in the leader's copy;
the trial id is 12 hex characters. Git runs hardened: no system or global config,
`core.hooksPath=/dev/null`, `core.fsmonitor=false`, `fetch.fsckObjects=true`,
`transfer.fsckObjects=true`, only the local file transport, no submodules, no automatic
maintenance. The new history the branch would bring is measured in the leader's copy
first (`rev-list --objects --disk-usage`); past `branch_max_bytes` the answer is
`denied branch not made: too large (<n> bytes, cap <m>)`. Then the commit is fetched into
the temporary ref and the branch is created with
`git update-ref refs/heads/team/<trial id> <commit> 0000000000000000000000000000000000000000`,
which can only create. A branch already at that commit counts as `made` (as Temper's own
path does); one elsewhere is `exists` and is left alone. With `branch_enabled` false:
`denied the branch verb is off`.

## The auth bridge

The helper starts the bridge as a child process and talks to it over its stdin and stdout
only (the private pipe). The bridge has no other output: no file, no log, its stderr goes
nowhere.

```bash
<node> <pinned folder>/temper_pi_host_bridge.mjs --sdk-root <sdk root> \
  --sdk-package <sdk package> --sdk-version <sdk version> --ai-version <ai version or -> \
  --agent-dir <pi agent dir> --base-provider <base> --slots <slot,slot or -> \
  --min-validity-ms 1800000 --timeout-ms <0.8 × token_timeout_s, in ms>
```

No secret is ever on its command line or in its environment (the fixed list above), in
cwd `/`, in its own session.

- Runtime: node 22 (the chats' node) and the Pi SDK the running chats load, imported from
  `<sdk root>/node_modules/<sdk package>` and the `@earendil-works/pi-ai` that package
  resolves, through their published entry points (`.` and `./providers/all`). Nothing else.
- Hello, its first line: `{"bridge":1,"ok":true,"package","version","loaded_version",
  "ai_package","ai_version","node"}`, or `{"bridge":1,"ok":false,"reason":
  "sdk_version_mismatch"|"sdk_unreadable"|"sdk_surface"|"bad_args", ...}` and exit 2.
- Requests: `{"id":N,"op":"token","slot":"<slot>"}` and `{"id":N,"op":"status"}`.
- Answers: `{"id":N,"ok":true,"slot","token"}`, `{"id":N,"ok":false,"slot","reason",
  "found_version"?}`, and for status `{"id":N,"ok":true,"state","found_version"?,"slots"}`.

**Version check at start.** Before it imports the SDK, the bridge reads the SDK's
`package.json` from disk (and pi-ai's), and says `sdk_version_mismatch` when the package,
the version or the pi-ai version is not the expected one, or `sdk_unreadable`; after the
import it compares the SDK's own `VERSION` too. The helper also compares the hello with its
config. Either way the start is refused before any login was read: no auth storage is
created, auth.json and its lock are not touched.

**Version check before every request.** A deploy can upgrade the chats' SDK while the
helper runs, and a running bridge keeps its old code loaded; both write auth.json, so a
skew could spend or garble a refresh token every chat on that slot uses. So before every
token and status request the bridge reads the versions on disk again and compares them
with what it loaded; a change refuses that one request (`sdk_changed`, with the version
found) before any read, modify or write of auth.json. The refresh step checks once more,
under auth.json's lock, just before the network refresh. **Whenever the chats' Pi SDK is
upgraded, the helper's `bridge.sdk_version` (and `ai_version`) are updated, and the helper
restarted, in the same step**; until then every token request is refused, plainly.

**How a token is served.** The bridge registers the slot on the SDK's `ModelRuntime` the
way the chats' multi-pass extension does: under the slot's own auth key, with the base
provider's built-in OAuth flow. It checks that Pi's multi-pass subscriptions list the
slot and that auth.json holds an OAuth login for it, then asks
`ModelRuntime.getAuth(<slot>, {minOAuthValidityMs: 1800000})`. A login that expires within
30 minutes is refreshed by the SDK's credential-modify path: under auth.json's lock it
reads the file again and refreshes only if the login still expires soon, so the chats and
the helper refresh once between them, and both get the same new login.

## The journal

One line per request, words only, never a token, a fingerprint of one, an account id or
any content:

```text
temper-pi-host: serving <socket> for uid <uid>: pi <version>, sdk <package> <version>, slots <slots>, branch off, ceiling 120/h
temper-pi-host: verb=status result=ok ms=<n> pi=<version> sdk=<version> peer=<pid>
temper-pi-host: verb=token slot=<slot> result=ok ms=<n> pi=<version> sdk=<version> peer=<pid>
temper-pi-host: verb=token slot=<slot> result=denied why=<code> ms=<n> pi=<version> sdk=<version> peer=<pid>
temper-pi-host: verb=branch repo=<repo> ref=team/<trial id> result=made ms=<n> pi=<version> sdk=<version> peer=<pid>
temper-pi-host: tripwire: the hourly token ceiling (<n>) is reached; hand-offs are refused
temper-pi-host: refused to start: <why>
temper-pi-host: stopped
```

## Temper's side

With `host_helper_socket` set in the Pi worker box config, a worker's login hand-off asks
the helper for the run's pinned slot (`BoxSpec.slot`) and nothing else, and the box config
no longer needs `host_node` or `host_pi`; without it, a live box config still needs both
and the hand-off runs the host Pi CLI as before (host-process instances, tests). The client
is `temper_ai/pi_agent/host_helper.py`. A hand-off with no pinned slot does not ask the
helper. A refusal hands the worker nothing; the turn's receipt records `handoff_slot`
(the slot label, exactly) and `handoff_refused` (the helper's words, naming the slot), and
a failed turn shows that refusal first. The token goes to the turn's redactor before the
worker has it. A done trial's branch uses the branch verb (`temper_ai/pi_agent/team_branch.py`).

## The selftest (no real login, no model call)

```bash
python3 <pinned folder>/temper_pi_host.py selftest --journald --node <node>
```

It makes a temp folder (mode 0700), a stub Pi CLI (answers `--version` and
`auth check ... --no-refresh`; any other call is recorded as forbidden and fails), a stub
Pi SDK, and a canary login in a temp auth.json. It runs the real helper (`serve`, under
`systemd-cat` with `--journald`) with the real bridge beside the script, which can only
load the stub SDK. It checks: the socket is served; `status` answers `ok <json>` with the
stub Pi version, the bridge's SDK package and version and both slot words, and no login
text; a token comes back on the socket only; the base slot is refused; changing the SDK
version on disk refuses the next token and shows `sdk_changed` in status, with auth.json
byte-for-byte and mtime unchanged; SIGTERM stops the helper and removes its socket; one
journal line per request, the status line among them, and no login text in the journal; a
different expected version refuses the start (exit 2, no socket) naming both versions,
before the SDK is loaded and with auth.json unchanged; the stub Pi CLI was asked for no
login or model call; no file but the temp auth.json holds the canary. A pass prints 20
`PASS` lines and `selftest: PASS (20/20 checks)`, exits 0 and removes its temp folder; a
failure prints `FAIL` lines, keeps the folder (stub data only) and exits 1. Without
`--journald` the helper's lines go to a file in the temp folder instead.

## Tests

- `tests/test_pi_host/`: the config (`test_config.py`), every verb in-process
  (`test_helper.py`), the branch verb on throwaway repos (`test_branch.py`), the bridge
  over a stub SDK (`test_bridge.py`), the real service process and the selftest
  (`test_serve.py`). Stub Pi CLI, stub SDK, temp auth.json and temp sockets only.
- `tests/test_pi_host/test_real_sdk.py`: the bridge over the real, pinned Pi SDK with a
  fake token endpoint (a test-only preload, `fake_fetch.mjs`, sends the SDK's token
  requests to a local fake and refuses all other network), including a chat-side SDK
  (`chat_side.mjs`, set up as the chats set it up) and the bridge refreshing the same
  login at the same moment: exactly one refresh, the same new login on both sides. Skipped
  unless `TEMPER_PI_HOST_TEST_SDK_ROOT` names a folder whose `node_modules` holds the SDK:

  ```bash
  TEMPER_PI_HOST_TEST_SDK_ROOT=<chat app checkout> uv run pytest tests/test_pi_host/test_real_sdk.py -v
  ```

- `tests/test_pi_agent/test_host_helper.py`: Temper's side against the real helper process
  (the hand-off for the pinned slot, refusals, the box config) and #48's E10 branch client
  end to end.
